"""车辆折旧：直线法按月计提、按天摊进窗口 —— **唯一实现**（FEAT-0012 第二期）。

需求方 2026-10-04 拍板的三条口径（`docs/changes/FEAT-0012.md` ①）：

1. **直线法按月计提** —— 录「购置价 ＋ 购置日期 ＋ 使用年限 ＋ 残值率」四个数，
   系统自己按月计提。老板不需要每个月手工填一笔折旧（他也没有那个功夫，忘了就永远少一块）。
2. **并入「期间费用」那一层** —— 利润表的利润构成多一行「− 车辆折旧」，与开销同一层
   （⛔ 不是商品成本、也不是配送成本：这笔钱跟哪一单没关系，是"车放在那里"本身的花费）。
3. **不回溯** —— 缺购置信息的车**不算**折旧（报表里单列「未覆盖折旧」并说明缺哪一项），
   ⛔ 不按车型猜购置价、也⛔ 不拿 0 顶替：编一个数出来等于替用户记错账。

## 公式（与 `docs/changes/FEAT-0012.md` ④ Behavior Contract 逐字一致）

```text
月折旧额   = 购置价 × (1 − 残值率) ÷ (使用年限 × 12)      # 四舍五入到「分」（ROUND_HALF_UP）
窗口内折旧 = Σ 各自然月（月折旧额 × 该月与窗口的交集天数 ÷ 当月天数）  # 逐车算完再四舍五入到分
```

### 几条边界，写死在实现里

- **计提起点** = 购置日期当天（含）。购置日期落在窗口中间时，当月按天摊，**买之前的天不摊**。
- **提足之后 = 0**，而且**不是**「未覆盖」：到期后这台车就是不花钱了。
  提足时点 = 购置日期 + 使用年限 × 12 个月（年限带小数、乘出来不是整月时，余数按 30.4375 天/月
  折成天数四舍五入 —— 整月的情形就是购置日期的**周年日**，一天不差）。
- **残值率留空 = 0%**（购置价全额计提）。界面必须写「留空 = 0%」——
  这是四格里**唯一**「留空有意义」的一格；其余三格留空 = 没录 = 未覆盖。
- **停用（is_active = 0）的车照提**：系统里没有「什么时候停用的」这个事实，
  按它停提会凭空造一个事实出来（见 Known Limitations）。
- ⛔ **折旧额永不落库**：本模块全是纯函数，输入是台账四列 + 窗口，输出是金额；
  没有任何一行 SQL、不碰任何表。报表、导出、AI 读取都只是调用它。

## 为什么单独一个文件

折旧只有**这一份**实现：利润表（`reports/profit_query.py`）与车辆成本页
（`reports/vehicle_cost_query.py`）都 import 这里的函数，⛔ 不许各算一套 ——
两处口径一旦分叉，老板看到的两个页面会互相打架，而他把两张表当成同一件事。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Sequence

from app.services.money_text import money_text

# ---- 台账四格的合法区间（与 `schemas/accounting_v2.py` 的校验、界面的提示同一套数）----
YEARS_MIN = Decimal("0.5")
YEARS_MAX = Decimal("30")
RATE_MIN = Decimal("0")
RATE_MAX = Decimal("0.5")
PRICE_MIN = Decimal("0")

#: 未覆盖的三个原因（顺序就是报错与界面上列出来的顺序）
MISSING_PRICE = "没录购置价"
MISSING_DATE = "没录购置日期"
MISSING_LIFE = "没录使用年限"

_CENT = Decimal("0.01")
_DAYS_PER_MONTH = Decimal("30.4375")  # 非整月的使用年限折天数用（整月走日历加法，不用它）


def _dec(value: Any) -> Decimal | None:
    """把库里的值转成 Decimal；None / 空串 → None（**NULL 的含义是「没录」，不是 0**）。"""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    """金额四舍五入到分（ROUND_HALF_UP —— 与账本、结算单、利润表同一套）。"""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _add_months(day: date, months: int) -> date:
    """日历加法：加整月，日号越界时取该月最后一天（1/31 + 1 月 = 2/28）。"""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, _days_in_month(year, month)))


def depreciation_end(purchase_date: date, useful_life_years: Decimal) -> date:
    """提足时点（**不含**当天）：购置日期 + 使用年限 × 12 个月。"""
    months = _dec(useful_life_years) * 12
    whole = int(months)  # months > 0，int() 即向下取整
    tail = months - whole
    end = _add_months(purchase_date, whole)
    if tail > 0:
        end = end + timedelta(days=int((tail * _DAYS_PER_MONTH).to_integral_value(rounding=ROUND_HALF_UP)))
    return end


def missing_items(
    purchase_price: Any, purchase_date: Any, useful_life_years: Any
) -> tuple[str, ...]:
    """这台车**缺哪几项**（空元组 = 折旧覆盖得到它）。"""
    missing: list[str] = []
    price = _dec(purchase_price)
    if price is None or price <= PRICE_MIN:
        missing.append(MISSING_PRICE)
    if purchase_date is None:
        missing.append(MISSING_DATE)
    years = _dec(useful_life_years)
    if years is None or years <= 0:
        missing.append(MISSING_LIFE)
    return tuple(missing)


def residual_rate_of(value: Any) -> Decimal:
    """残值率取值：**留空 = 0%**；越界值防呆夹到 [0, 50%]（API 已校验，只有手改库才可能越界）。"""
    rate = _dec(value)
    if rate is None:
        return RATE_MIN
    if rate < RATE_MIN:
        return RATE_MIN
    if rate > RATE_MAX:
        return RATE_MAX
    return rate


def monthly_depreciation(
    purchase_price: Any, useful_life_years: Any, residual_rate: Any
) -> Decimal | None:
    """月折旧额（四舍五入到分）；购置信息不全 → None（**不猜**）。"""
    price = _dec(purchase_price)
    years = _dec(useful_life_years)
    if price is None or years is None or price <= PRICE_MIN or years <= 0:
        return None
    return _money(price * (Decimal(1) - residual_rate_of(residual_rate)) / (years * 12))


def window_depreciation(
    monthly: Decimal | None,
    purchase_date: date | None,
    useful_life_years: Any,
    window_start: date,
    window_end: date,
) -> Decimal:
    """窗口内折旧：逐自然月按交集天数摊，最后四舍五入到分。

    窗口是**闭区间** `[window_start, window_end]`（与第一期报表的日期口径同一套），
    `window_end < window_start` 或一个月都不沾 → 0。
    """
    if monthly is None or purchase_date is None or window_end < window_start:
        return Decimal("0.00")
    years = _dec(useful_life_years)
    if years is None or years <= 0:
        return Decimal("0.00")
    # 参与计提的日子 = 窗口 ∩ [购置日期, 提足时点)
    start = max(window_start, purchase_date)
    end = min(window_end, depreciation_end(purchase_date, years) - timedelta(days=1))
    if end < start:
        return Decimal("0.00")
    total = Decimal("0")
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        first = date(year, month, 1)
        days = _days_in_month(year, month)
        overlap_start = max(first, start)
        overlap_end = min(_add_months(first, 1) - timedelta(days=1), end)
        span = (overlap_end - overlap_start).days + 1
        if span > 0:
            total += monthly * Decimal(span) / Decimal(days)
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return _money(total)


@dataclass(frozen=True)
class VehicleDepreciation:
    """一辆车的折旧答案（报表与车辆成本页共用这一个形状）。"""

    vehicle_id: int
    plate_no: str
    is_active: bool
    covered: bool
    missing: tuple[str, ...]
    purchase_price: Decimal | None
    purchase_date: date | None
    useful_life_years: Decimal | None
    residual_rate: Decimal | None
    residual_rate_effective: Decimal
    monthly_amount: Decimal | None
    window_amount: Decimal

    def as_dict(self) -> dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "plate_no": self.plate_no,
            "is_active": self.is_active,
            "covered": self.covered,
            "uncovered_reasons": list(self.missing),
            "purchase_price": _num(self.purchase_price),
            "purchase_date": self.purchase_date.isoformat() if self.purchase_date else None,
            "useful_life_years": _num(self.useful_life_years),
            "residual_rate": _num(self.residual_rate),
            "residual_rate_effective": _num(self.residual_rate_effective),
            "monthly_depreciation": _num(self.monthly_amount),
            "window_depreciation": _num(self.window_amount),
        }


def _num(value: Decimal | None) -> float | None:
    """Decimal → float（JSON 出参统一用 float，与既有报表的金额同一个做法）。"""
    if value is None:
        return None
    return float(value)


def of_vehicle(vehicle: Any, window_start: date, window_end: date) -> VehicleDepreciation:
    """一辆车在窗口里的折旧。`vehicle` 是 `models.vehicle.Vehicle` 行（或任何带同名属性的东西）。"""
    price = _dec(getattr(vehicle, "purchase_price", None))
    bought = getattr(vehicle, "purchase_date", None)
    years = _dec(getattr(vehicle, "useful_life_years", None))
    raw_rate = _dec(getattr(vehicle, "residual_rate", None))
    missing = missing_items(price, bought, years)
    monthly = monthly_depreciation(price, years, raw_rate)
    return VehicleDepreciation(
        vehicle_id=int(getattr(vehicle, "id", 0) or 0),
        plate_no=str(getattr(vehicle, "plate_no", None) or getattr(vehicle, "plate_number", "") or ""),
        is_active=bool(getattr(vehicle, "is_active", True)),
        covered=not missing,
        missing=missing,
        purchase_price=price,
        purchase_date=bought,
        useful_life_years=years,
        residual_rate=raw_rate,
        residual_rate_effective=residual_rate_of(raw_rate),
        monthly_amount=monthly,
        window_amount=window_depreciation(monthly, bought, years, window_start, window_end),
    )


def summarize(vehicles: Iterable[Any], window_start: date, window_end: date) -> dict[str, Any]:
    """逐车算完再合计 —— 利润表那一格「车辆折旧」用的就是这里的 `total`。

    恒等式：`total == Σ per_vehicle[*].window_depreciation`（**明细 = 合计**，逐车可复算）。
    """
    rows = [of_vehicle(v, window_start, window_end) for v in vehicles]
    covered = [r for r in rows if r.covered]
    uncovered = [r for r in rows if not r.covered]
    total = _money(sum((r.window_amount for r in covered), Decimal("0")))
    return {
        "total": _num(total),
        "monthly_total": _num(_money(sum((r.monthly_amount or Decimal("0") for r in covered), Decimal("0")))),
        "vehicle_count": len(rows),
        "covered_count": len(covered),
        "uncovered_count": len(uncovered),
        "uncovered": [
            {"vehicle_id": r.vehicle_id, "plate_no": r.plate_no, "reasons": list(r.missing)}
            for r in uncovered
        ],
        "per_vehicle": [r.as_dict() for r in rows],
        "window": {"date_from": window_start.isoformat(), "date_to": window_end.isoformat()},
    }


def uncovered_note(summary: dict[str, Any]) -> str:
    """未覆盖那件事的一句话说明（利润表 notes 与车辆成本页共用，⛔ 不带 markdown 星号）。"""
    count = int(summary.get("uncovered_count") or 0)
    if count <= 0:
        return "车辆折旧按直线法按月计提、按天摊进窗口；有购置信息的车都算进来了。"
    plates = "、".join(str(r.get("plate_no") or "") for r in (summary.get("uncovered") or [])[:6])
    more = "" if count <= 6 else f" 等 {count} 台"
    return (
        f"车辆折旧按直线法按月计提、按天摊进窗口；还有 {count} 台车没有完整购置信息"
        f"（{plates}{more}），它们的折旧没算进来 —— 缺的那一格补上之后，这张表就会跟着变。"
    )


# ---------------------------------------------------------------- 四格的显示与校验
#
# 显示名 / 报错话术 / 审计行都从这里取**唯一一份**（与 `services/vehicle_attrs.py` 同一条纪律：
# ⛔ 界面与后端各写一份 when(字段)，两处叫法迟早不一样）。

FIELD_KEYS = ("purchase_price", "purchase_date", "useful_life_years", "residual_rate")

FIELD_LABELS = {
    "purchase_price": "购置价",
    "purchase_date": "购置日期",
    "useful_life_years": "使用年限",
    "residual_rate": "残值率",
}

_PRICE_MAX = Decimal("9999999999.99")  # Numeric(12, 2) 的上限
_DATE_TIP = "购置日期要写成 2025-09-16 这样的日期"


def format_field(key: str, value: Any) -> str:
    """一格怎么显示（界面 / 审计 / 报错共用）：`None` = 「（未录）」。"""
    if value is None or value == "":
        return "（未录）"
    if key == "purchase_price":
        return f"{money_text(value)} 元"
    if key == "purchase_date":
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    if key == "useful_life_years":
        return f"{Decimal(str(value)).normalize()} 年"
    if key == "residual_rate":
        return f"{(Decimal(str(value)) * 100).normalize()}%"
    return str(value)


def _same(a: Any, b: Any) -> bool:
    """两个值算不算同一个（None / 空串 都是「没录」；Decimal 比数值不比写法）。"""
    a = None if a in (None, "") else a
    b = None if b in (None, "") else b
    if a is None or b is None:
        return a is None and b is None
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except Exception:  # noqa: BLE001 - 日期等非数值字段：直接比
        return a == b


def field_lines(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """这四格的改动怎么记进审计 —— **只记真的变了的**，清空也记。

    两条纪律与 `api/v1/vehicles._attr_lines` 完全一致：① 一点没变就不记（审计页上"改了但什么都没变"
    的记录会把真正的改动淹掉）；② **清空也要记**（`→ （清空）`）——「这辆车从此没有购置信息」
    是一件必须能回查的事。
    """
    out: list[str] = []
    for key in FIELD_KEYS:
        was, now = before.get(key), after.get(key)
        if _same(was, now):
            continue
        label = FIELD_LABELS[key]
        if now is None or now == "":
            out.append(f"{label} {format_field(key, was)} → （清空）")
        elif was is None or was == "":
            out.append(f"{label} {format_field(key, now)}")
        else:
            out.append(f"{label} {format_field(key, was)} → {format_field(key, now)}")
    return out


def _to_decimal(raw: Any, tip: str) -> Decimal | None:
    """原始输入 → Decimal；空串 = 「没录」返回 None；解析不了就抛那句中文。"""
    if raw is None:
        return None
    if isinstance(raw, str) and raw.strip() == "":
        return None
    try:
        return Decimal(str(raw).strip())
    except Exception:  # noqa: BLE001
        raise ValueError(tip) from None


def clean_fields(
    *,
    purchase_price: Any = None,
    purchase_date: Any = None,
    useful_life_years: Any = None,
    residual_rate: Any = None,
    today: date | None = None,
) -> dict[str, Any]:
    """校验台账四格，返回归一后的 `{键: Decimal | date | None}`（None = 没录）。

    ⚠️ 报错一律**中文 + 带正确写法**（与 `vehicle_attrs.parse_attrs`、`validate_month` 同一条纪律：
    英文结构体用户看不懂，也改不对）。⛔ 这里**不许兜默认值** —— 兜一个等于替用户记错账。
    """
    if today is None:
        from app.core.business_time import business_today

        today = business_today()

    price = _to_decimal(purchase_price, "购置价要写成数字（元），比如 120000 或 120000.50")
    if price is not None:
        if price <= 0:
            raise ValueError("购置价要大于 0 元（这辆车多少钱买的）")
        if price > _PRICE_MAX:
            raise ValueError(f"购置价最多 {money_text(_PRICE_MAX)} 元")
        if price != price.quantize(_CENT, rounding=ROUND_HALF_UP):
            raise ValueError("购置价最多两位小数（到分）")

    bought: date | None = None
    blank_date = isinstance(purchase_date, str) and purchase_date.strip() == ""
    if purchase_date is not None and not blank_date:
        if isinstance(purchase_date, str):
            try:
                bought = date.fromisoformat(purchase_date.strip().replace("/", "-"))
            except ValueError:
                raise ValueError(_DATE_TIP) from None
        elif isinstance(purchase_date, date):
            bought = purchase_date
        elif hasattr(purchase_date, "date"):
            bought = purchase_date.date()  # datetime -> date
        else:
            raise ValueError(_DATE_TIP)
        if bought > today:
            raise ValueError("购置日期不能晚于今天（还没买的车不能先提折旧）")

    years = _to_decimal(useful_life_years, "使用年限要写成数字（年），比如 5 或 4.5")
    if years is not None:
        if years < YEARS_MIN or years > YEARS_MAX:
            raise ValueError("使用年限要在 0.5 到 30 年之间（可以带一位小数，比如 4.5）")
        if years != years.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP):
            raise ValueError("使用年限最多一位小数（比如 4.5 年）")

    rate = _to_decimal(residual_rate, "残值率要写成数字（0 到 0.5 之间），比如 5% 就填 0.05")
    if rate is not None:
        if rate < RATE_MIN or rate > RATE_MAX:
            raise ValueError("残值率要在 0% 到 50% 之间（比如 5% 就填 0.05）")
        if rate != rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP):
            raise ValueError("残值率最多四位小数（比如 0.05）")

    return {
        "purchase_price": price,
        "purchase_date": bought,
        "useful_life_years": years,
        "residual_rate": rate,
    }


def fields_of(vehicle: Any) -> dict[str, Any]:
    """一辆车现在的四格（给 `field_lines` 当 before / after 用）。"""
    return {key: getattr(vehicle, key, None) for key in FIELD_KEYS}
