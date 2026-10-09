"""开销单的关联必须真实存在；挂不上的那笔钱必须在报表上看得见（TB-07 / BUG-0023）。

## 为什么要有这个文件（2026-10-10）

测试会话在 8020 的副本库上抓到两件事，两件都不报错：

1. POST /api/v1/expenses 对 driver_id / vehicle_id / order_id 一个都不校验 ——
   三个 999999 也能 200 落库（expense id=55，7.77 元），开销页那一行三个名字全是空字符串。
2. 那 7.77 元在两张表里一个认一个不认：利润表的 operating_expense_total 含它（5804.87），
   车辆成本表的 expense_total 不含它（5598.50），而车辆成本表的口径说明里没有一个字
   提到被丢掉的那部分 —— 用户拿同一窗口对不上账，也看不到「另有 N 笔 X 元没挂车」。

这个文件钉五件事：

1. 三个关联字段指不到真实对象（或账号已停用/已删除、订单在回收站里）→ 400，
   且错误文案要点名是哪个字段、哪个 id；
2. 关联都真实存在时照旧能记（守卫不许顺手把正常路径一起拒了）；
3. 车辆成本表把窗口开销分成三块报出来：挂到真实车辆的 / 没挂车的 / 挂到查无此车的；
   三块相加 = expense_window_total = 窗口内全部开销，口径说明里带上笔数与金额；
4. 两张表能对上：expense_window_total == 利润表 operating_expense_total + tax_total
   （利润表把分类名带「税」的那些挖出来单列，对账要把那两块加回来）；
5. 数据契约：司机账号被软删、车辆被停用之后，历史开销照旧留在它们名下、名字照旧解析得出，
   但**新**记一笔挂到它们身上必须被拒。

本文件不连开发库：tests/conftest.py:143 把 DATABASE_URL 指向本进程自己的
backend/tests/.test_dbs/sorders_test_<worker>_<pid>.db（每个 pytest 进程一份）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Expense, ExpenseCategory, Order, User, Vehicle
from app.models.enums import OrderStatus, UserRole
from app.services.soft_delete import del_suffix
from tests.conftest import auth_headers

#: 探针标记：本文件造出来的行都带它，收尾按它清干净。
PROBE = "TB07-PROBE"
#: 固定窗口取远期（2031-05）：避开其它用例的数据，也让「同一窗口两张表」的断言是确定的。
WIN_FROM = date(2031, 5, 1)
WIN_TO = date(2031, 5, 31)
ANCHOR = "2031-05-15"
#: 探针分类：一个普通开销分类 + 一个会被利润表挖去「税金及附加」的分类（判据是名字里有「税」）。
CAT_PLAIN = "TB07探针普通开销"
CAT_TAX = "TB07探针税金及附加"
#: 探针司机账号的手机号前缀 / 探针车牌前缀 / 探针订单号前缀。
PHONE_PREFIX = "1990000"
PLATE_PREFIX = "测联TB07"
ORDER_PREFIX = "TB07PROBE"
#: 一个**故意不存在**的编号：999999（测试会话当时就是拿它写进库的）。
GHOST = 999999


@pytest.fixture(autouse=True)
def clean_probe(db_session):
    """收尾把探针行删干净，别给同 worker 的其它用例留垃圾（尤其别留车、别留开销行）。"""
    yield
    db_session.rollback()
    for e in db_session.scalars(select(Expense).where(Expense.note == PROBE)).all():
        db_session.delete(e)
    for c in db_session.scalars(
        select(ExpenseCategory).where(ExpenseCategory.name.in_([CAT_PLAIN, CAT_TAX]))
    ).all():
        db_session.delete(c)
    for o in db_session.scalars(select(Order).where(Order.order_no.like(ORDER_PREFIX + "%"))).all():
        db_session.delete(o)
    for u in db_session.scalars(select(User).where(User.phone.like(PHONE_PREFIX + "%"))).all():
        db_session.delete(u)
    for v in db_session.scalars(select(Vehicle).where(Vehicle.plate_no.like(PLATE_PREFIX + "%"))).all():
        db_session.delete(v)
    db_session.commit()


def _mk_driver(db_session, phone: str, name: str) -> User:
    u = User(phone=phone, username=phone, full_name=name, password_hash="x", role=UserRole.DRIVER.value)
    db_session.add(u)
    db_session.commit()
    return u


def _mk_vehicle(client, h, plate: str) -> int:
    r = client.post("/api/v1/vehicles", json={"plate_no": plate, "vehicle_type": "small"}, headers=h)
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _mk_order(db_session, no: str, *, driver_id: int | None = None) -> Order:
    o = Order(
        order_no=ORDER_PREFIX + no,
        status=OrderStatus.PENDING_DISPATCH,
        order_date=WIN_FROM,
        address_detail=PROBE,
        driver_id=driver_id,
    )
    db_session.add(o)
    db_session.commit()
    return o


def _mk_expense(
    db_session,
    *,
    amount: str,
    category: str = CAT_PLAIN,
    vehicle_id: int | None = None,
    driver_id: int | None = None,
    order_id: int | None = None,
) -> Expense:
    """直接落一行开销（报表用例用它，绕开接口 —— 孤儿 vehicle_id 正是接口该拦的那一类）。"""
    e = Expense(
        exp_date=WIN_FROM,
        category=category,
        amount=Decimal(amount),
        vehicle_id=vehicle_id,
        driver_id=driver_id,
        order_id=order_id,
        note=PROBE,
    )
    db_session.add(e)
    db_session.commit()
    return e


def _post_expense(client, h, **fields):
    body = {"exp_date": str(WIN_FROM), "category": CAT_PLAIN, "amount": "7.77", "note": PROBE}
    body.update(fields)
    return client.post("/api/v1/expenses", json=body, headers=h)


def _vehicle_cost(client, h) -> dict:
    r = client.get("/api/v1/reports/vehicle-cost", params={"mode": "month", "date": ANCHOR}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _profit(client, h) -> dict:
    r = client.get("/api/v1/reports/profit", params={"mode": "month", "date": ANCHOR}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _expenses(client, h) -> list[dict]:
    r = client.get(
        "/api/v1/expenses",
        params={"date_from": str(WIN_FROM), "date_to": str(WIN_TO)},
        headers=h,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _row(data: dict, vehicle_id: int) -> dict:
    """按车找行（⛔ 不许按顺序取：并发/别的用例都会插车）。"""
    for r in data["per_vehicle"]:
        if int(r["vehicle_id"]) == int(vehicle_id):
            return r
    raise AssertionError("车辆成本表里没有这台车：" + str(vehicle_id))


def _dec(d: dict, key: str) -> Decimal:
    assert key in d, "报表返回体里没有这一格：" + key
    return Decimal(str(d[key]))


def test_不存在的关联必须被拒绝(client, token_dispatcher, db_session):
    """① 三个外键一个都不许指到不存在的行上，且要说清是哪个字段、哪个 id。"""
    h = auth_headers(token_dispatcher)
    for field in ("driver_id", "vehicle_id", "order_id"):
        r = _post_expense(client, h, **{field: GHOST})
        assert r.status_code == 400, field + " 应该 400，实际 " + str(r.status_code) + "：" + r.text
        detail = str(r.json()["detail"])
        assert field in detail and str(GHOST) in detail, "错误里要点名字段与 id：" + detail

    # 一笔都不许落库（改前这里会看到 3 行 7.77）
    left = [x for x in _expenses(client, h) if x["note"] == PROBE]
    assert left == [], "被拒绝的开销不许落库：" + str(left)

    # 关联都真实时照旧能记：司机 + 车辆 + 订单全给上
    d = _mk_driver(db_session, PHONE_PREFIX + "01", "TB07探针司机甲")
    vid = _mk_vehicle(client, h, PLATE_PREFIX + "A")
    o = _mk_order(db_session, "0001", driver_id=d.id)
    r = _post_expense(client, h, driver_id=d.id, vehicle_id=vid, order_id=o.id)
    assert r.status_code in (200, 201), "关联都真实时必须能记：" + r.text

    # 名字照旧解析得出来（改前「名字全是空」那一格）
    row = [x for x in _expenses(client, h) if x["id"] == r.json()["id"]][0]
    assert row["driver_name"] == "TB07探针司机甲"
    assert row["vehicle_name"] == PLATE_PREFIX + "A"
    assert row["order_no"] == ORDER_PREFIX + "0001"


def test_停用或已删掉的关联也不许挂(client, token_dispatcher, db_session):
    """① 后半：账号停用、账号已删（回收站）、车辆停用、订单在回收站 —— 都算「关联不成立」。"""
    h = auth_headers(token_dispatcher)
    d = _mk_driver(db_session, PHONE_PREFIX + "02", "TB07探针司机乙")
    vid = _mk_vehicle(client, h, PLATE_PREFIX + "B")

    # 账号停用
    d.is_active = False
    db_session.commit()
    r = _post_expense(client, h, driver_id=d.id)
    assert r.status_code == 400, r.text
    assert str(d.id) in str(r.json()["detail"])

    # 账号已删（照 api/v1/users.py::delete_user 的口径：is_active=False + 号码/用户名加 _del{id}）
    d.phone = del_suffix(d.phone, d.id, 32)
    d.username = del_suffix(d.username, d.id, 32)
    d.is_active = True  # 故意留一个「后缀在、但还活着」的账号（恢复时撞号就是这个样子）
    db_session.commit()
    r = _post_expense(client, h, driver_id=d.id)
    assert r.status_code == 400, r.text

    # 车辆停用
    r = client.patch("/api/v1/vehicles/" + str(vid), json={"is_active": False}, headers=h)
    assert r.status_code == 200, r.text
    r = _post_expense(client, h, vehicle_id=vid)
    assert r.status_code == 400, r.text
    assert str(vid) in str(r.json()["detail"])

    # 订单在回收站
    o = _mk_order(db_session, "0002")
    o.deleted_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    db_session.commit()
    r = _post_expense(client, h, order_id=o.id)
    assert r.status_code == 400, r.text
    assert str(o.id) in str(r.json()["detail"])

    left = [x for x in _expenses(client, h) if x["note"] == PROBE]
    assert left == [], "被拒绝的开销不许落库：" + str(left)


def test_车辆成本表把三块开销都摆出来(client, token_dispatcher, db_session):
    """② 三块：挂到真实车的 / 没挂车的 / 挂到查无此车的；相加 = 窗口内全部开销。"""
    h = auth_headers(token_dispatcher)
    vid = _mk_vehicle(client, h, PLATE_PREFIX + "C")
    _mk_expense(db_session, amount="100.00", vehicle_id=vid)
    _mk_expense(db_session, amount="20.50")
    _mk_expense(db_session, amount="7.77", vehicle_id=GHOST)  # 改前接口放它进来、报表又把它吞了

    d = _vehicle_cost(client, h)
    assert _dec(_row(d, vid), "expense_total") == Decimal("100.00")
    # ⛔ expense_total 的语义一个字都不许变（只有挂到这台车的）
    assert _dec(d, "expense_total") == Decimal("100.00")
    assert _dec(d, "unlinked_expense_total") == Decimal("20.50")
    assert int(d["unlinked_expense_count"]) == 1
    assert _dec(d, "orphan_expense_total") == Decimal("7.77")
    assert int(d["orphan_expense_count"]) == 1
    assert _dec(d, "expense_window_total") == Decimal("128.27")
    assert int(d["expense_window_count"]) == 3
    assert _dec(d, "expense_window_total") == (
        _dec(d, "expense_total") + _dec(d, "unlinked_expense_total") + _dec(d, "orphan_expense_total")
    )

    notes = [str(n) for n in d["notes"]]
    assert not any("**" in n for n in notes), "口径说明里不许出现 markdown 星号"
    # 说明行按「未挂车」认：静态那六条口径里说的是「没挂车的开销进不了本表」（讲司机的那条
    # 也写「没挂车的司机」），动态这一行是**唯一**一处把这两块钱的笔数与金额摆出来的地方。
    hit = [n for n in notes if "未挂车" in n]
    assert len(hit) == 1, "要有一行说明被漏掉的钱（笔数 + 金额）：" + str(notes)
    line = hit[0]
    # 金额印的是共享显示口径 money_text（去尾零）：20.50 印成 20.5
    for token in ("20.5", "7.77", "128.27"):
        assert token in line, "说明里要能核对上这一笔：" + line


def test_同一个窗口两张表能对上(client, token_dispatcher, db_session):
    """③ 车辆成本表三块相加 == 利润表（期间费用 + 税金及附加），一分不差。"""
    h = auth_headers(token_dispatcher)
    vid = _mk_vehicle(client, h, PLATE_PREFIX + "D")
    _mk_expense(db_session, amount="100.00", vehicle_id=vid)
    _mk_expense(db_session, amount="20.50")
    _mk_expense(db_session, amount="7.77", vehicle_id=GHOST)
    _mk_expense(db_session, amount="30.00", category=CAT_TAX)

    vc = _vehicle_cost(client, h)
    pf = _profit(client, h)
    assert _dec(vc, "expense_window_total") == Decimal("158.27")
    assert _dec(pf, "tax_total") == Decimal("30.00")
    assert _dec(vc, "expense_window_total") == _dec(pf, "operating_expense_total") + _dec(pf, "tax_total")


def test_软删司机与停用车辆之后历史开销还在(client, token_dispatcher, db_session):
    """④ 数据契约：主数据被软删/停用，历史开销不搬家、不抹名；但新挂必须被拒。"""
    h = auth_headers(token_dispatcher)
    d = _mk_driver(db_session, PHONE_PREFIX + "03", "TB07探针司机丙")
    vid = _mk_vehicle(client, h, PLATE_PREFIX + "E")
    r = _post_expense(client, h, driver_id=d.id, vehicle_id=vid)
    assert r.status_code in (200, 201), r.text
    eid = int(r.json()["id"])

    # 软删司机（口径同 delete_user）+ 停用车辆
    d.is_active = False
    d.phone = del_suffix(d.phone, d.id, 32)
    d.username = del_suffix(d.username, d.id, 32)
    db_session.commit()
    r = client.patch("/api/v1/vehicles/" + str(vid), json={"is_active": False}, headers=h)
    assert r.status_code == 200, r.text

    # ① 车辆成本表照旧把这笔算进这台车那一行（历史事实不因为停用而消失）
    row = _row(_vehicle_cost(client, h), vid)
    assert _dec(row, "expense_total") == Decimal("7.77")

    # ② 开销页那一行名字照旧解析得出来（司机已软删、车已停用，但历史开销上写的就是他们）
    row = [x for x in _expenses(client, h) if x["id"] == eid][0]
    assert row["driver_name"] == "TB07探针司机丙", row
    assert row["vehicle_name"] == PLATE_PREFIX + "E", row

    # ③ 但新记一笔挂到已删司机 / 已停用车辆 → 400
    r = _post_expense(client, h, driver_id=d.id)
    assert r.status_code == 400, r.text
    r = _post_expense(client, h, vehicle_id=vid)
    assert r.status_code == 400, r.text
