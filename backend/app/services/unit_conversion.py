"""单位换算的**判据**（一车 = 8 方）—— 纯函数，唯一实现处。

## 为什么判据要单独一份（而不是散在 API 里）
"这个换算能不能建"有**四条**规则，而其中两条一旦写错就是**静默的两个答案**：

| 规则 | 写错的后果 |
|---|---|
| 源单位非空、目标单位非空、两者不能相同 | `1 车 = 1 车` 这种行会在列表里显示成一条"正常"的换算 |
| 换算率必须 > 0 | `1 车 = 0 方` 让"10 车 ≈ 0 方"看起来像个正经结果 |
| **同一个 `from_unit` 只能有一条** | `1 车 = 8 方` 与 `1 车 = 50 袋` 并存 → "10 车 ≈ ?" 没有唯一答案（界面只能任选一条，而用户以为是系统算的） |
| **反向对不许同时存在** | `1 车 = 8 方` 与 `1 方 = 0.2 车` 并存 → 同一批货两个互相矛盾的数，谁也不知道哪个对 |

这四条都由这里给出**一句能照着改的中文**（后端抛出的中文会被 App 原样显示），
API 只负责把库里活着的行读成 [ConversionPair] 再调它 —— 所以这些规则可以在**没有数据库**的
情况下逐条单测（`backend/tests/test_unit_conversion_rules.py`）。

⛔ **不做链式换算**（`一车=8方` + `1方=50袋` **不**推 `一车=400袋`）：链式要防环、要选路径、
还要在界面上说清"这个数是推出来的"。第一版明确不做 —— 写在这里，免得下一个人以为漏了。
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

#: 单位名的长度上限（与 `unit_conversions.from_unit` 的列宽一致）。单位是短词（"车"/"方"/"袋"）。
MAX_UNIT_LEN = 16

#: 一个源单位最多能配几条换算 —— 恒等于 1（见文件头第三条规则）。
#: 写成一个常量是为了让"只能一条"这件事出现在**调用点**的字面上，而不是藏在查询里。
MAX_TARGETS_PER_UNIT = 1

#: 换算率的合法区间。上限取 1_000_000：再大就不是"单位换算"而是数据错了（1 车 = 100 万袋）。
FACTOR_MAX = Decimal("1000000")


@dataclass(frozen=True)
class ConversionPair:
    """一条**活着的**换算。只带判据需要的字段，不依赖 ORM 类型 → 可以纯单测。"""

    id: int | None
    from_unit: str
    to_unit: str
    factor: Decimal


def clean_unit(raw: str | None) -> str:
    """单位名归一：去首尾空格。**不改大小写**（"t" 与 "T" 是用户自己的写法，改了会认不出）。"""
    return (raw or "").strip()


def unit_key(raw: str | None) -> str:
    """比较用的键：**忽略大小写**（"kg" 与 "KG" 是同一个单位，不该各自配一条）。"""
    return clean_unit(raw).casefold()


def format_factor(raw: Decimal) -> str:
    """换算率怎么显示：去掉末尾多余的 0（`8.0000` → `8`，`0.5000` → `0.5`）。

    与金额那边同一个口径（设计系统 §4.1.1：末尾多余的 0 一律去掉），但**不复用**
    `formatMoney` —— 那是钱，会带货币符号与两位小数。
    """
    text = format(raw, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def validate_units(from_unit: str | None, to_unit: str | None) -> tuple[str, str]:
    """校验两个单位名，返回归一后的 `(from, to)`；不合法就抛一句中文。"""
    f = clean_unit(from_unit)
    t = clean_unit(to_unit)
    if not f:
        raise ValueError("「从这个单位」不能为空（例如「车」）")
    if not t:
        raise ValueError("「换算成哪个单位」不能为空（例如「方」）")
    if len(f) > MAX_UNIT_LEN or len(t) > MAX_UNIT_LEN:
        raise ValueError(f"单位名最多 {MAX_UNIT_LEN} 个字")
    if unit_key(f) == unit_key(t):
        raise ValueError(f"「{f}」换成「{t}」没有意义（两边是同一个单位）")
    return f, t


def validate_factor(raw: object) -> Decimal:
    """校验换算率：必须是一个大于 0、不超过 [FACTOR_MAX] 的数。

    接受字符串与数字（App 传字符串，AI 可能传数字）—— 两种都收，但进来就转成 `Decimal`，
    **不在这里做浮点运算**（浮点会让"10 车"显示成 `79.99999999999999`）。
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ValueError("换算率不能为空（例如 1 车 = 8 方，就填 8）")
    try:
        value = raw if isinstance(raw, Decimal) else Decimal(str(raw).strip())
    except (InvalidOperation, ArithmeticError, ValueError):
        raise ValueError(f"换算率「{raw}」不是数字（只填数字，例如 8，不要带单位）") from None
    if value <= 0:
        raise ValueError("换算率必须大于 0（1 车 = 0 方 会让「10 车 ≈ 0 方」看起来像个正经结果）")
    if value > FACTOR_MAX:
        raise ValueError(f"换算率太大了（上限 {format_factor(FACTOR_MAX)}）—— 是不是多打了几位？")
    return value


def conflict_reason(
    rows: list[ConversionPair],
    from_unit: str,
    to_unit: str,
    exclude_id: int | None = None,
) -> str | None:
    """这一对能不能建：返回 `None`（可以）或**一句照着改的中文**。

    [rows] 是**活着的**换算（软删的不算 —— 删掉一条再建同一条是正常操作，
    由 API 认出被删过的那一行并把它的换算率改过来）。
    [exclude_id] 用在"改这一条自己"的时候：不算它跟自己冲突。
    """
    f = unit_key(from_unit)
    t = unit_key(to_unit)
    for r in rows:
        if exclude_id is not None and r.id == exclude_id:
            continue
        if unit_key(r.from_unit) == f:
            return (
                f"「{clean_unit(r.from_unit)}」已经有换算了：1 {clean_unit(r.from_unit)} = "
                f"{format_factor(r.factor)} {clean_unit(r.to_unit)}。"
                f"一个单位只能换算到一处（{MAX_TARGETS_PER_UNIT} 条）—— 否则同一批货会有两个"
                f"都像是对的答案。要改就改那一条，或者先删掉它。"
            )
    for r in rows:
        if exclude_id is not None and r.id == exclude_id:
            continue
        if unit_key(r.from_unit) == t and unit_key(r.to_unit) == f:
            return (
                f"库里已经有反过来的「1 {clean_unit(r.from_unit)} = {format_factor(r.factor)} "
                f"{clean_unit(r.to_unit)}」了 —— 两个方向同时存在时，同一批货会有两个互相矛盾的数。"
                f"要么删掉那一条，要么就按它的方向填。"
            )
    return None


def pair_of(from_unit: str, to_unit: str, factor: Decimal, id: int | None = None) -> ConversionPair:
    """小工具：把库里那一行拼成判据要的形状（**一处实现**，免得每个调用点各写一遍字段名）。"""
    return ConversionPair(id=id, from_unit=from_unit, to_unit=to_unit, factor=factor)
