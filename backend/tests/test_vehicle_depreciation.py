"""车辆台账折旧（FEAT-0012 第二期）：直线法按月计提、按天摊进窗口。

## 为什么要有这个文件（2026-10-04）

老板第 1 问「这月赚了多少」一直少一块：**车自己每个月也在花钱**。第一期那张经营利润表的口径
说明第 2 条原文写着「折旧没有算进去……所以这张表的营业利润偏高（少了折旧那一块），
第二期补车辆台账时接进来」—— 这个文件就是那一步的护栏。

折旧只有**这一份**实现（`app/services/vehicle_depreciation.py`），利润表与车辆成本页都 import 它；
一旦两处各算一套，老板看到的两个页面会互相打架。所以这里的断言全是**逐个数字**的：

1. 月折旧额 = 购置价 × (1 − 残值率) ÷ (使用年限 × 12)，四舍五入到分；
2. 窗口内 = Σ 各自然月（月额 × 交集天数 ÷ 当月天数）—— 购买当月按天摊、**买之前的天不摊**；
3. 提足之后 = 0，而且**不是**「未覆盖」（到期就是不花钱了，不是"缺数据"）；
4. 残值率留空 = 0%（四格里**唯一**"留空有意义"的一格）；
5. 三个数缺任何一格 ⇒ 该车未覆盖、金额 0、单列并写明缺哪一项（⛔ 不猜一个数出来）；
6. **明细 == 合计**（逐车可复算），停用（is_active = 0）的车**照提**；
7. 落地形状：模型的四列 / 迁移 `018_vehicle_depreciation` / `schema_bootstrap` 自愈副本
   **三处逐列一致**，且本模块是**纯函数**（⛔ 不 import sqlalchemy、⛔ 不落库）。
8. 台账四格怎么**写进去**（接口侧，`PATCH /vehicles/{id}` 一格一格、清空 = 传空串）：
   校验不通过 → 400 ＋ 一句中文，**库里一个字节不改**（连半截的车都不许留下）；
   四栏只记**真的变了的**（审计页最怕"改了但什么都没变"）。
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import Date, Numeric, select

from app.migrations._runner import discover
from app.models import OperationLog
from app.models.enums import OperationAction
from app.models.vehicle import Vehicle
from app.services import vehicle_depreciation as vd
from tests.conftest import auth_headers

#: 四列的落地形状：迁移里的 DDL 片段 / 模型的类型 / Numeric 的 (precision, scale)
EXPECTED_COLUMNS = {
    "purchase_price": ("DECIMAL(12,2) NULL", Numeric, (12, 2)),
    "purchase_date": ("DATE NULL", Date, None),
    "useful_life_years": ("DECIMAL(4,1) NULL", Numeric, (4, 1)),
    "residual_rate": ("DECIMAL(5,4) NULL", Numeric, (5, 4)),
}


def _car(**kw) -> SimpleNamespace:
    """一辆车的替身（折旧是纯函数：只认这七个属性，不需要数据库）。"""
    base = dict(
        id=1,
        plate_no="川A12345",
        is_active=True,
        purchase_price=None,
        purchase_date=None,
        useful_life_years=None,
        residual_rate=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _five_years(**kw) -> SimpleNamespace:
    """12 万、5 年 —— 不含残值时月折旧额正好 2,000.00，方便心算按天摊。"""
    base = dict(
        purchase_price=Decimal("120000.00"),
        purchase_date=date(2025, 9, 16),
        useful_life_years=Decimal("5.0"),
    )
    base.update(kw)
    return _car(**base)


# ---------------------------------------------------------------- ① 月折旧额
def test_monthly_depreciation_formula() -> None:
    """月额 = 购置价 × (1 − 残值率) ÷ (年限 × 12)，四舍五入到分。"""
    # 12 万 / 5 年 / 残值 5% -> 120000 × 0.95 / 60 = 1900.00
    assert vd.monthly_depreciation(Decimal("120000.00"), Decimal("5.0"), Decimal("0.05")) == Decimal("1900.00")
    # 残值率**留空 = 0%** -> 120000 / 60 = 2000.00（⛔ 不是"未覆盖"）
    assert vd.monthly_depreciation(Decimal("120000.00"), Decimal("5.0"), None) == Decimal("2000.00")
    # 残值率 0 与留空是同一个答案
    assert vd.monthly_depreciation(Decimal("120000.00"), Decimal("5.0"), Decimal("0")) == Decimal("2000.00")
    # 残值 50%（上限）-> 120000 × 0.5 / 60 = 1000.00
    assert vd.monthly_depreciation(Decimal("120000.00"), Decimal("5.0"), Decimal("0.5")) == Decimal("1000.00")
    # 年限带小数：0.1 年 = 1.2 个月 -> 120000 / 1.2 = 100000.00
    assert vd.monthly_depreciation(Decimal("120000.00"), Decimal("0.1"), None) == Decimal("100000.00")


def test_monthly_depreciation_rounds_to_cent() -> None:
    """分位四舍五入（ROUND_HALF_UP）—— 与账本 / 结算单 / 利润表同一套。"""
    # 100000 × 0.97 / 36 = 2694.4444… -> 2694.44
    assert vd.monthly_depreciation(Decimal("100000.00"), Decimal("3.0"), Decimal("0.03")) == Decimal("2694.44")
    # 100000 × 1 / (0.9 × 12) = 9259.2592… -> 9259.26
    assert vd.monthly_depreciation(Decimal("100000.00"), Decimal("0.9"), None) == Decimal("9259.26")


def test_monthly_is_none_when_not_covered() -> None:
    """缺格就返回 None（⛔ 不拿 0 顶替：0 是"这月不花钱"，None 是"不知道"）。"""
    assert vd.monthly_depreciation(None, Decimal("5.0"), None) is None
    assert vd.monthly_depreciation(Decimal("120000.00"), None, None) is None
    assert vd.monthly_depreciation(Decimal("0"), Decimal("5.0"), None) is None
    assert vd.monthly_depreciation(Decimal("-1"), Decimal("5.0"), None) is None
    assert vd.monthly_depreciation(Decimal("120000.00"), Decimal("0"), None) is None


# ---------------------------------------------------------------- ② 按天摊进窗口
def test_purchase_month_is_prorated_by_days() -> None:
    """购置日期落在窗口中间：当月按天摊，**买之前的天不摊**。"""
    car = _five_years()  # 2025-09-16 入手，9 月 30 天
    # 9 月只有 16..30 这 15 天：2000 × 15 / 30 = 1000.00
    assert vd.of_vehicle(car, date(2025, 9, 1), date(2025, 9, 30)).window_amount == Decimal("1000.00")
    # 8 月：这车还没买 -> 0
    assert vd.of_vehicle(car, date(2025, 8, 1), date(2025, 8, 31)).window_amount == Decimal("0.00")
    # 购置当天那一天的窗口：1 天 -> 2000 / 30 = 66.67
    assert vd.of_vehicle(car, date(2025, 9, 16), date(2025, 9, 16)).window_amount == Decimal("66.67")


def test_window_prorates_across_months_and_years() -> None:
    """跨月 / 跨年照摊：逐自然月按当月天数，不是"按 30 天一份"。"""
    car = _five_years()
    # 2025-09-16 起 9 个月：9 月 15/30 -> 1000，10 月..次年 5 月各整月 2000 × 8
    assert vd.of_vehicle(car, date(2025, 9, 1), date(2026, 5, 31)).window_amount == Decimal("17000.00")
    # 整年（12 个整月，含 2 月 28 天）-> 24000.00
    assert vd.of_vehicle(car, date(2025, 10, 1), date(2026, 9, 30)).window_amount == Decimal("24000.00")
    # 闰年 2 月整月 = 2000.00（当月天数就是 29，摊满）
    leap = _five_years(purchase_date=date(2024, 1, 15))
    assert vd.of_vehicle(leap, date(2024, 2, 1), date(2024, 2, 29)).window_amount == Decimal("2000.00")
    # 30 天的月里只取前 15 天 -> 1000.00
    assert vd.of_vehicle(leap, date(2024, 4, 1), date(2024, 4, 15)).window_amount == Decimal("1000.00")


def test_window_amount_is_rounded_once_per_vehicle() -> None:
    """逐车算完**最后一次**四舍五入：所以明细与合计逐分相等，手工复算也对得上。"""
    car = _five_years(purchase_price=Decimal("10000.00"), useful_life_years=Decimal("7.0"))
    one = vd.of_vehicle(car, date(2025, 9, 16), date(2025, 9, 16)).window_amount
    # 10000 / 84 = 119.0476… -> 月额 119.05；一天 = 119.05 / 30 = 3.9683… -> 3.97
    assert vd.monthly_depreciation(car.purchase_price, car.useful_life_years, car.residual_rate) == Decimal("119.05")
    assert one == Decimal("3.97")


def test_empty_and_reversed_window_is_zero() -> None:
    """空窗口 / 反了的窗口 -> 0（不炸：报表那边的窗口校验是 400，这里是纯函数兜底）。"""
    car = _five_years()
    assert vd.of_vehicle(car, date(2025, 10, 3), date(2025, 10, 1)).window_amount == Decimal("0.00")
    assert vd.of_vehicle(car, date(2025, 9, 1), date(2025, 8, 31)).window_amount == Decimal("0.00")


# ---------------------------------------------------------------- ③ 提足之后
def test_fully_depreciated_is_zero_and_still_covered() -> None:
    """提足之后 = 0，而且**不是**未覆盖。"""
    car = _five_years(purchase_date=date(2021, 10, 4), residual_rate=Decimal("0.05"))
    row = vd.of_vehicle(car, date(2026, 10, 1), date(2026, 10, 31))
    assert row.covered is True  # 到期不是"缺数据"
    # 提足时点 = 2026-10-04：窗口只沾到 10-01..10-03 三天 -> 1900 × 3 / 31 = 183.87
    assert vd.depreciation_end(date(2021, 10, 4), Decimal("5.0")) == date(2026, 10, 4)
    assert row.window_amount == Decimal("183.87")
    # 下个月起一分钱都不提
    assert vd.of_vehicle(car, date(2026, 11, 1), date(2026, 11, 30)).window_amount == Decimal("0.00")


def test_depreciation_end_is_anniversary() -> None:
    """提足时点 = 购置日期 + 年限 × 12 个月（整月走日历加法，日号越界取该月末）。"""
    assert vd.depreciation_end(date(2021, 10, 4), Decimal("5.0")) == date(2026, 10, 4)
    assert vd.depreciation_end(date(2024, 1, 31), Decimal("1.0")) == date(2025, 1, 31)
    assert vd.depreciation_end(date(2024, 8, 31), Decimal("0.5")) == date(2025, 2, 28)  # 日号越界夹到 2 月末（4/6/9/11 月同理）
    assert vd.depreciation_end(date(2024, 1, 31), Decimal("0.5")) == date(2024, 7, 31)
    # 1.1 年 = 13.2 个月：13 个整月 -> 2025-02-28（日号夹月末），余 0.2 个月 × 30.4375 ≈ 6 天
    assert vd.depreciation_end(date(2024, 1, 31), Decimal("1.1")) == date(2025, 3, 6)
    # 带小数、乘出来不是整月：余数按 30.4375 天/月折天（39.6 个月 = 39 个月 + 18 天）
    assert vd.depreciation_end(date(2024, 1, 31), Decimal("3.3")) == date(2027, 5, 18)


# ---------------------------------------------------------------- ④ 未覆盖
def test_uncovered_reasons_are_explicit() -> None:
    """缺哪一格就写哪一格（界面上要照抄给用户看）。"""
    assert vd.missing_items(None, date(2025, 1, 1), Decimal("5.0")) == (vd.MISSING_PRICE,)
    assert vd.missing_items(Decimal("120000"), None, Decimal("5.0")) == (vd.MISSING_DATE,)
    assert vd.missing_items(Decimal("120000"), date(2025, 1, 1), None) == (vd.MISSING_LIFE,)
    assert vd.missing_items(None, None, None) == (vd.MISSING_PRICE, vd.MISSING_DATE, vd.MISSING_LIFE)
    assert vd.missing_items(Decimal("120000"), date(2025, 1, 1), Decimal("5.0")) == ()
    # 残值率留空**不算**缺：它有意义（0%）。
    assert vd.missing_items(Decimal("120000"), date(2025, 1, 1), Decimal("5.0")) == ()


def test_uncovered_vehicle_contributes_zero_and_is_listed() -> None:
    """未覆盖的车：金额 0、月额 None、在 uncovered 里带车牌与原因 —— ⛔ 不猜。"""
    car = _car(id=7, plate_no="川B00007", purchase_price=Decimal("80000.00"))
    row = vd.of_vehicle(car, date(2026, 10, 1), date(2026, 10, 31))
    assert row.covered is False
    assert row.monthly_amount is None
    assert row.window_amount == Decimal("0.00")
    assert row.missing == (vd.MISSING_DATE, vd.MISSING_LIFE)
    s = vd.summarize([car], date(2026, 10, 1), date(2026, 10, 31))
    assert s["total"] == 0.0 and s["covered_count"] == 0 and s["uncovered_count"] == 1
    assert s["uncovered"] == [{"vehicle_id": 7, "plate_no": "川B00007", "reasons": [vd.MISSING_DATE, vd.MISSING_LIFE]}]
    note = vd.uncovered_note(s)
    assert "1 台车" in note and "川B00007" in note
    assert "**" not in note  # 这些字会原样进手机与导出的表


def test_residual_rate_is_clamped_to_legal_range() -> None:
    """越界残值率防呆夹取（API 已校验，只有手改库才可能越界）。"""
    assert vd.residual_rate_of(None) == Decimal("0")
    assert vd.residual_rate_of(Decimal("-0.2")) == Decimal("0")
    assert vd.residual_rate_of(Decimal("0.9")) == Decimal("0.5")
    assert vd.residual_rate_of(Decimal("0.125")) == Decimal("0.125")


# ---------------------------------------------------------------- ⑤ 合计
def test_detail_equals_total_and_idle_vehicle_still_depreciates() -> None:
    """明细 == 合计；停用（is_active = 0）的车**照提**。"""
    a = _five_years(id=1, plate_no="川A1")
    b = _five_years(id=2, plate_no="川A2", purchase_price=Decimal("60000.00"), is_active=False)
    c = _car(id=3, plate_no="川A3")  # 四格全空 -> 未覆盖
    s = vd.summarize([a, b, c], date(2025, 10, 1), date(2025, 10, 31))
    assert s["covered_count"] == 2 and s["uncovered_count"] == 1
    assert s["total"] == 3000.0  # 2000（12 万）+ 1000（6 万，停用照提）
    assert s["total"] == round(sum(r["window_depreciation"] for r in s["per_vehicle"]), 2)
    assert s["monthly_total"] == 3000.0
    assert s["window"] == {"date_from": "2025-10-01", "date_to": "2025-10-31"}
    assert vd.summarize([a, b], date(2025, 10, 1), date(2025, 10, 31))["uncovered"] == []
    assert "都算进来了" in vd.uncovered_note({"uncovered_count": 0})


# ---------------------------------------------------------------- ⑥ 落地形状
def test_module_is_pure_no_db() -> None:
    """本模块是**纯函数**：不 import sqlalchemy、不碰 session、不写任何表。"""
    src = Path(vd.__file__).read_text(encoding="utf-8")
    assert "sqlalchemy" not in src
    assert "Session" not in src
    assert "INSERT" not in src and "UPDATE " not in src and "DELETE " not in src


def test_columns_match_model_migration_and_bootstrap() -> None:
    """模型的四列 / 迁移 018 / `schema_bootstrap` 自愈副本**逐列一致**。"""
    # ① 模型
    for name, (ddl_tail, type_cls, numeric_args) in EXPECTED_COLUMNS.items():
        col = Vehicle.__table__.c[name]
        assert type(col.type) is type_cls, name
        assert col.nullable is True, name
        if numeric_args is not None:
            assert (col.type.precision, col.type.scale) == numeric_args, name
        # ② 迁移 018：DDL 片段逐字一致 + 迁移文件自己声明了版本与表
        mig = [m for m in discover(load=True) if m.version == 18]
        assert len(mig) == 1
        module = mig[0].module
        assert module.NAME == "vehicle_depreciation"
        assert module.TABLE == "vehicles"
        assert module.COLUMNS[name] == f"{name} {ddl_tail}", name
        # ③ schema_bootstrap 自愈副本：同一句 ALTER 逐字出现
        from app.core import schema_bootstrap

        boot = Path(schema_bootstrap.__file__).read_text(encoding="utf-8")
        assert f"ALTER TABLE vehicles ADD COLUMN {name} {ddl_tail}" in boot, name


def test_depreciation_is_never_stored() -> None:
    """折旧额**不进库**：`vehicles` 表里没有也不许有折旧额列（只有那四个输入）。"""
    names = {c.name for c in Vehicle.__table__.columns}
    assert "monthly_depreciation" not in names
    assert "accumulated_depreciation" not in names
    assert {"purchase_price", "purchase_date", "useful_life_years", "residual_rate"} <= names


# ══════════════════════════════════════════════════ ⑦ 四格怎么校验（唯一一份中文话术）


def test_clean_fields_accepts_and_normalises() -> None:
    """原始输入（字符串、一位小数）→ 归一到 Decimal / date。"""
    got = vd.clean_fields(
        purchase_price="120000.50",
        purchase_date="2025-09-16",
        useful_life_years="4.5",
        residual_rate="0.05",
        today=date(2026, 10, 4),
    )
    assert got["purchase_price"] == Decimal("120000.50")
    assert got["purchase_date"] == date(2025, 9, 16)
    assert got["useful_life_years"] == Decimal("4.5")
    assert got["residual_rate"] == Decimal("0.05")


def test_clean_fields_blank_is_none() -> None:
    """空串 = 「没录」（安卓 `explicitNulls = false`，清空只能靠空串表达）。"""
    got = vd.clean_fields(purchase_price="", purchase_date="", useful_life_years="", residual_rate="")
    assert got == {
        "purchase_price": None,
        "purchase_date": None,
        "useful_life_years": None,
        "residual_rate": None,
    }


@pytest.mark.parametrize(
    "kw, tip",
    [
        ({"purchase_price": "0"}, "购置价要大于 0 元"),
        ({"purchase_price": "-1"}, "购置价要大于 0 元"),
        ({"purchase_price": "abc"}, "购置价要写成数字"),
        ({"purchase_price": "1.234"}, "购置价最多两位小数"),
        ({"purchase_date": "2099-01-01"}, "购置日期不能晚于今天"),
        ({"purchase_date": "去年"}, "购置日期要写成 2025-09-16"),
        ({"useful_life_years": "40"}, "使用年限要在 0.5 到 30 年之间"),
        ({"useful_life_years": "0.4"}, "使用年限要在 0.5 到 30 年之间"),
        ({"useful_life_years": "4.55"}, "使用年限最多一位小数"),
        ({"residual_rate": "0.8"}, "残值率要在 0% 到 50% 之间"),
        ({"residual_rate": "0.12345"}, "残值率最多四位小数"),
    ],
)
def test_clean_fields_rejects_in_chinese(kw: dict, tip: str) -> None:
    """越界 / 写错一律是**一句能照着改的中文**（⛔ 不给英文结构体，用户改不对）。"""
    with pytest.raises(ValueError) as err:
        vd.clean_fields(today=date(2026, 10, 4), **kw)
    assert tip in str(err.value)


def test_field_lines_records_only_real_changes() -> None:
    """审计只记真的变了的；清空也记（「这辆车从此没有购置信息」必须能回查）。"""
    before = {
        "purchase_price": Decimal("120000.00"),
        "purchase_date": None,
        "useful_life_years": Decimal("5.0"),
        "residual_rate": Decimal("0.05"),
    }
    after = {
        "purchase_price": Decimal("120000.00"),
        "purchase_date": date(2025, 9, 16),
        "useful_life_years": Decimal("5.0"),
        "residual_rate": None,
    }
    assert vd.field_lines(before, after) == ["购置日期 2025-09-16", "残值率 5% → （清空）"]
    assert vd.field_lines(before, before) == []


# ══════════════════════════════════════════════════ ⑧ 台账四格的写入（接口侧）


@pytest.fixture
def vehicles_restore(db_session):
    """跑完把车辆表恢复原状。

    测试库是整个会话共用的**一个文件**，而接口调用会 `db.commit()` —— 不还原的话，
    「我建的那台车」会留在库里把别的用例弄红（`test_product_catalog.py` 栽过的那一次）。
    """
    before = {v.id for v in db_session.scalars(select(Vehicle)).all()}
    yield
    db_session.rollback()
    for v in db_session.scalars(select(Vehicle)).all():
        if v.id not in before:
            db_session.delete(v)
    db_session.commit()


BASE = {
    "purchase_price": "120000",
    "purchase_date": "2025-09-16",
    "useful_life_years": "5",
    "residual_rate": "0.05",
}


def _mk(client, token, plate: str, **fields):
    return client.post(
        "/api/v1/vehicles",
        json={"plate_no": plate, "vehicle_type": "small", **fields},
        headers=auth_headers(token),
    )


def _last_upsert(db_session) -> dict | None:
    """最后一条车辆变更审计的 payload（明细列叫 `change_content`，里面是 JSON 文本）。"""
    db_session.expire_all()
    rows = list(
        db_session.scalars(
            select(OperationLog)
            .where(OperationLog.action == OperationAction.VEHICLE_UPSERT.value)
            .order_by(OperationLog.id)
        )
    )
    return json.loads(rows[-1].change_content) if rows else None


def test_api_create_keeps_ledger_and_computes_monthly(client, token_dispatcher, db_session, vehicles_restore):
    """建车带齐四格：四栏**真的落库**，接口当场把月折旧算给用户看。"""
    r = _mk(client, token_dispatcher, "测折00001", **BASE)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["depreciation_covered"] is True
    assert got["depreciation_missing"] == []
    assert got["depreciation_monthly"] == "1900.00"  # 120000 × 95% ÷ (5×12)
    # 只看返回值的话，一个「能算但不落库」的实现也能过 —— 所以要看库里那四列
    v = db_session.get(Vehicle, got["id"])
    db_session.refresh(v)
    assert Decimal(str(v.purchase_price)) == Decimal("120000")
    assert v.purchase_date == date(2025, 9, 16)
    assert Decimal(str(v.useful_life_years)) == Decimal("5")
    assert Decimal(str(v.residual_rate)) == Decimal("0.05")


def test_api_create_audit_lists_all_four_cells(client, token_dispatcher, db_session, vehicles_restore):
    """建车时填的台账四格同样要能回查（与车牌 / 车型 / 属性同一条审计）。"""
    _mk(client, token_dispatcher, "测折00002", **BASE)
    assert _last_upsert(db_session)["changes"] == [
        "车牌 测折00002",
        "车型 小货车",
        "购置价 120000 元",
        "购置日期 2025-09-16",
        "使用年限 5 年",
        "残值率 5%",
    ]


def test_api_blank_rate_means_zero_percent(client, token_dispatcher, vehicles_restore):
    """残值率留空 = 0%（四格里**唯一**「留空有意义」的一格，界面上也要这么写）。"""
    base = {k: v for k, v in BASE.items() if k != "residual_rate"}
    got = _mk(client, token_dispatcher, "测折00003", **base).json()
    assert got["residual_rate"] is None
    assert got["depreciation_covered"] is True, "留空不是「缺一格」"
    assert got["depreciation_monthly"] == "2000.00", "按 0% 计提：120000 ÷ 60"


def test_api_missing_cells_are_uncovered_not_zero(client, token_dispatcher, vehicles_restore):
    """缺格的组合：单列、写明缺哪一项，金额是 `null` —— ⛔ 不猜一个数出来。"""
    got = _mk(client, token_dispatcher, "测折00004", purchase_price="120000").json()
    assert got["depreciation_covered"] is False
    assert got["depreciation_missing"] == ["没录购置日期", "没录使用年限"]
    assert got["depreciation_monthly"] is None, "算不出来是 null，⛔ 不是 0（0 是已经提足）"
    none_at_all = _mk(client, token_dispatcher, "测折00005").json()
    assert none_at_all["depreciation_missing"] == ["没录购置价", "没录购置日期", "没录使用年限"]
    assert none_at_all["depreciation_monthly"] is None


@pytest.mark.parametrize(
    "fields, tip",
    [
        ({"purchase_price": "0"}, "购置价要大于 0 元"),
        ({"purchase_date": "2099-01-01"}, "购置日期不能晚于今天"),
        ({"useful_life_years": "40"}, "使用年限要在 0.5 到 30 年之间"),
        ({"residual_rate": "0.8"}, "残值率要在 0% 到 50% 之间"),
    ],
)
def test_api_rejects_bad_ledger_values_in_chinese(
    client, token_dispatcher, db_session, vehicles_restore, fields: dict, tip: str
) -> None:
    """校验不过 → 400 ＋ 中文，且**一辆半截的车都不许留下**。"""
    r = _mk(client, token_dispatcher, "测折00006", **{**BASE, **fields})
    assert r.status_code == 400, r.text
    assert tip in r.json()["detail"]
    db_session.expire_all()
    left = db_session.scalars(select(Vehicle).where(Vehicle.plate_no == "测折00006")).first()
    assert left is None, "校验不过就不该产生半截的车"


def test_api_type_error_is_422(client, token_dispatcher, vehicles_restore):
    """类型不对是 pydantic 的活（422）；数值越界才是那句中文（400）—— 两种别混。"""
    assert _mk(client, token_dispatcher, "测折00007", purchase_price="abc").status_code == 422


def _patch(client, token, vid: int, body: dict):
    return client.patch(f"/api/v1/vehicles/{vid}", json=body, headers=auth_headers(token))


def test_api_patch_clears_one_cell_only(client, token_dispatcher, db_session, vehicles_restore):
    """`PATCH` 传空串 = 清空**这一格**，另外三格一个字不动（与 attrs 的「整份替换」不同）。"""
    v = _mk(client, token_dispatcher, "测折00008", **BASE).json()
    r = _patch(client, token_dispatcher, v["id"], {"residual_rate": ""})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["residual_rate"] is None
    assert got["depreciation_covered"] is True, "清空残值率 = 按 0% 计提，不是未覆盖"
    assert got["depreciation_monthly"] == "2000.00"
    assert Decimal(got["purchase_price"]) == Decimal("120000")
    assert got["purchase_date"] == "2025-09-16"
    assert Decimal(got["useful_life_years"]) == Decimal("5")
    assert _last_upsert(db_session)["changes"] == ["残值率 5% → （清空）"]


def test_api_patch_untouched_cells_are_not_touched(client, token_dispatcher, db_session, vehicles_restore):
    """没传这四格 = 一格不动；传了同样的值 = 也不算改（审计页最怕「改了但什么都没变」）。"""
    v = _mk(client, token_dispatcher, "测折00009", **BASE).json()
    r = _patch(client, token_dispatcher, v["id"], {"vehicle_type": "large"})
    assert r.status_code == 200, r.text
    assert r.json()["depreciation_monthly"] == "1900.00", "改车型不许顺手动折旧"
    assert _last_upsert(db_session)["changes"] == ["车型 小货车 → 大货车"]
    r = _patch(client, token_dispatcher, v["id"], {"residual_rate": "0.05"})
    assert r.status_code == 200, r.text
    assert _last_upsert(db_session)["changes"] == ["车型 小货车 → 大货车"], "四格没变就不许产生审计行"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
