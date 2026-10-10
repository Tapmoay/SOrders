"""FEAT-0021 消息生产者：九类新消息要**自己出现**，而且不刷屏。

## 这条测试在钉什么
FEAT-0019 把渲染做完了（`notifications.severity` ＋ `payload["emphasis"]` ＋ App 卡片），
但九类新消息**一个生产者都没有** —— 界面上它们永远不会出现。本条测试钉的是
「谁在什么时候写这条消息」，以及四件不许出错的事：

1. **阈值上下**：库存「正好到线」要报、「高一件」不许报、阈值 0 = 不报警（⛔ 不是阈值 0）；
   应付「逾期 / 临期 / 还没到」三档各自归位，边界（第 7 天、第 0 天）都要有例子；
2. **去重**：同一件事不许反复刷屏 —— 同一商品同一天只有一条；每日兜底扫描**连续跑两次，
   通知条数不增加**（幂等键在 `notifications.idem_key` 的唯一索引上，不是"先查再发"）；
3. **emphasis 真的在正文里**：点名片段必须原样出现在标题或正文里（照
   `docs/MESSAGE_CARD_DESIGN.md` §四），最多 2 词 + 2 数字；⛔ 不许退化成整行上色；
4. **深链键**：按 §五给目标键（库存 `product_id` / 应付 `payable_id`＋`supplier_id` /
   账号 `user_id` …），缺键就不给。

⛔ 这里刻意**不**断言"实现放在哪个函数里"之外的细节（比如文案的每一个字）：
测试认的是"这条事实出来是哪一档、点了什么、能不能重复发"。

⚠️ 本文件**不碰** App 侧渲染（那是 FEAT-0019 的交付、已真机验收）。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models import (
    ArrearsUnit,
    Invoice,
    Notification,
    Order,
    OrderProduct,
    Product,
    Supplier,
    SupplierPayable,
    User,
)
from app.models.enums import OrderStatus
from app.services import device_service, message_center, message_producers
from tests.conftest import auth_headers

#: 固定的"今天"：写死一个日期，用例才不会在跨天那一刻跑出两种结果。
D = date(2026, 10, 11)


# ---------------------------------------------------------------- 小工具

def _msgs(db: Session, type_: str, prefix: str | None = None) -> list[Notification]:
    """某类消息（可按幂等键前缀收窄到"我这一件事"）。"""
    stmt = select(Notification).where(Notification.type == type_)
    if prefix:
        stmt = stmt.where(Notification.idem_key.like(prefix + "%"))
    return list(db.scalars(stmt.order_by(Notification.id)))


def _product(db: Session, *, stock: int, alert: int, unit: str = "件") -> Product:
    p = Product(
        name="测试商品-" + uuid.uuid4().hex[:8],
        stock=stock,
        low_stock_alert=alert,
        unit=unit,
        is_active=True,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _payable(
    db: Session, *, doc_date: date, amount: str = "1000.00", title: str = "十月货款"
) -> SupplierPayable:
    s = Supplier(name="测试供应商-" + uuid.uuid4().hex[:8])
    db.add(s)
    db.flush()
    p = SupplierPayable(
        supplier_id=int(s.id), title=title, category="货款", amount=Decimal(amount), doc_date=doc_date
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _fresh_user(db: Session, *, role: str = "shipper") -> User:
    """**本用例自己的账号**。

    ⛔ 不拿 conftest 那三个共用账号（13800000001/2/3）做设备绑定：绑定是**真写库**的，
    共用账号的额度会被这条用例吃掉，别的用例就会偶发红（conftest 里那段
    `_reset_shared_users` 的说明记着同样的教训：一个用例改状态、别人当中枪的那个）。
    """
    from app.core.security import hash_password

    tail = uuid.uuid4().int % 100000000
    u = User(
        username="t" + uuid.uuid4().hex[:10],
        phone="139%08d" % tail,
        password_hash=hash_password("pass12345"),
        full_name="设备用例账号",
        role=role,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _assert_emphasis_ok(n: Notification) -> None:
    """照 §四 的四条：片段在正文里、不是整行、最多 4 处、不重复。"""
    words = list((n.payload or {}).get("emphasis") or [])
    text = (n.title or "") + "\n" + (n.content or "")
    assert words, "这条消息一个重点词都没有：" + str(n.type)
    assert len(words) <= message_center.MAX_EMPHASIS, words
    assert len(set(words)) == len(words), words
    for w in words:
        assert w in text, ("重点词不在标题/正文里（客户端会当成没点名）：" + w + " / " + str(words))
        assert w != (n.title or "").strip() and w != (n.content or "").strip(), (
            "整条标题/整段正文不许当重点词：" + w
        )
        assert len(w) <= message_center.MAX_EMPHASIS_CHARS, w


# ---------------------------------------------------------------- ① 库存 low

def test_stock_low_fires_at_or_below_the_alert_and_stays_quiet_above(db_session: Session) -> None:
    """阈值上下：正好到线要报、高一件不许报、阈值 0 = 不报警。"""
    low = _product(db_session, stock=3, alert=10)
    assert message_producers.notify_stock_low(db_session, product_id=int(low.id), day=D) >= 1
    db_session.commit()

    rows = _msgs(db_session, "stock.low", "stock.low:" + str(int(low.id)) + ":")
    assert len(rows) == 1
    n = rows[0]
    assert n.severity == "danger"                    # 档位只在 SEVERITY_BY_TYPE 一处定
    assert n.payload["product_id"] == int(low.id)    # §五：库存族的深链键
    assert "库存不足" in n.title
    assert n.payload["emphasis"] == ["库存不足", "3 件", "10 件"]
    _assert_emphasis_ok(n)

    edge = _product(db_session, stock=10, alert=10)  # 正好到线 = 报警（判据是 <=）
    assert message_producers.notify_stock_low(db_session, product_id=int(edge.id), day=D) >= 1

    above = _product(db_session, stock=11, alert=10)  # 高一件 = 一个字都不发
    assert message_producers.notify_stock_low(db_session, product_id=int(above.id), day=D) == 0

    off = _product(db_session, stock=1, alert=0)      # 0 = 不报警（不是"阈值是 0"）
    assert message_producers.notify_stock_low(db_session, product_id=int(off.id), day=D) == 0


def test_stock_low_sends_once_a_day_and_again_the_next_day(db_session: Session) -> None:
    """去重：同商品同一天只有一条；第二天还低就再提醒一次（那是新的一天）。"""
    p = _product(db_session, stock=2, alert=5)
    prefix = "stock.low:" + str(int(p.id)) + ":"
    assert message_producers.notify_stock_low(db_session, product_id=int(p.id), day=D) >= 1
    db_session.commit()
    before = len(_msgs(db_session, "stock.low", prefix))

    assert message_producers.notify_stock_low(db_session, product_id=int(p.id), day=D) == 0
    db_session.commit()
    assert len(_msgs(db_session, "stock.low", prefix)) == before == 1

    assert message_producers.notify_stock_low(
        db_session, product_id=int(p.id), day=D + timedelta(days=1)
    ) >= 1
    db_session.commit()
    assert len(_msgs(db_session, "stock.low", prefix)) == 2


def test_stock_near_low_is_honestly_absent() -> None:
    """偏低那档**如实不做**：库里只有报警阈值一个字段，"建议水位"不存在。

    ⛔ 不许为了凑齐两档去编一个阈值：那是"看起来实现了"。档位登记保留着，
    等真有建议水位字段时不用再动 `message_center`。
    """
    assert "stock.low" in message_producers.PRODUCED
    assert "stock.near_low" in message_producers.NOT_PRODUCED
    assert "建议水位" in message_producers.NOT_PRODUCED["stock.near_low"]
    assert not hasattr(message_producers, "notify_stock_near_low")
    assert message_center.SEVERITY_BY_TYPE["stock.near_low"] == "warn"


# ---------------------------------------------------------------- ② 应付 临期 / 逾期

def test_payable_kind_buckets_overdue_due_soon_and_not_yet(db_session: Session) -> None:
    """三档与两条边界：到期日 = 单据日期 + PAYABLE_TERM_DAYS，剩下 0 天 = 临期、-1 天 = 逾期。"""
    term = message_producers.PAYABLE_TERM_DAYS
    soon_days = message_producers.PAYABLE_DUE_SOON_DAYS

    overdue = _payable(db_session, doc_date=D - timedelta(days=term + 10))
    assert message_producers.payable_due_date(overdue) == D - timedelta(days=10)
    assert message_producers.payable_kind(overdue, day=D) == "payable.overdue"

    same_day = _payable(db_session, doc_date=D - timedelta(days=term))       # 就是今天到期
    assert message_producers.payable_kind(same_day, day=D) == "payable.due_soon"
    last_day = _payable(db_session, doc_date=D - timedelta(days=term - soon_days))  # 还剩 7 天
    assert message_producers.payable_kind(last_day, day=D) == "payable.due_soon"
    just_out = _payable(db_session, doc_date=D - timedelta(days=term - soon_days - 1))  # 还剩 8 天
    assert message_producers.payable_kind(just_out, day=D) is None
    one_day_late = _payable(db_session, doc_date=D - timedelta(days=term + 1))  # 逾期 1 天
    assert message_producers.payable_kind(one_day_late, day=D) == "payable.overdue"


def test_payable_messages_split_warn_and_danger_with_amount_and_days(db_session: Session) -> None:
    """两条文案：临期 warn、逾期 danger；都点名"还欠多少"和"还有几天/逾期几天"。"""
    term = message_producers.PAYABLE_TERM_DAYS
    soon = _payable(db_session, doc_date=D - timedelta(days=term - 3), amount="1234.00")
    assert message_producers.notify_payable(db_session, payable=soon, kind="payable.due_soon", day=D) >= 1
    overdue = _payable(db_session, doc_date=D - timedelta(days=term + 10), amount="1234.00")
    assert message_producers.notify_payable(
        db_session, payable=overdue, kind="payable.overdue", day=D
    ) >= 1
    db_session.commit()

    soon_n = _msgs(db_session, "payable.due_soon", "payable.due_soon:" + str(int(soon.id)) + ":")[0]
    assert soon_n.severity == "warn"
    assert soon_n.payload["payable_id"] == int(soon.id)
    assert soon_n.payload["supplier_id"] == int(soon.supplier_id)
    assert "将到期" in soon_n.content and "1234 元" in soon_n.content
    # 固定词（档位登记里那一个）排在前，后面才是本条点名的金额与天数
    assert soon_n.payload["emphasis"] == ["将到期", "1234 元", "3 天"]
    _assert_emphasis_ok(soon_n)

    late_n = _msgs(db_session, "payable.overdue", "payable.overdue:" + str(int(overdue.id)) + ":")[0]
    assert late_n.severity == "danger"
    assert "已逾期 10 天" in late_n.content
    assert late_n.payload["emphasis"] == ["已逾期", "1234 元", "10 天"]
    assert late_n.payload["due_date"] == (D - timedelta(days=10)).isoformat()
    _assert_emphasis_ok(late_n)


def test_payable_due_today_still_emphasises_the_fragment(db_session: Session) -> None:
    """边界：**就是今天到期**那张单，点名的片段也必须真的在正文里。

    这是"正文与重点词各写一遍"的经典坑：重点词写"今天到期"、正文写"就是今天" ——
    `emphasis_for` 的「正文里找不到就不标」那道闸会**安静地**把它丢掉
    （消息照样发出去，只是卡片上少一个落点，谁都不会报错）。
    """
    term = message_producers.PAYABLE_TERM_DAYS
    today = _payable(db_session, doc_date=D - timedelta(days=term), amount="1234.00")
    assert message_producers.payable_kind(today, day=D) == "payable.due_soon"
    assert message_producers.notify_payable(
        db_session, payable=today, kind="payable.due_soon", day=D
    ) >= 1
    db_session.commit()
    n = _msgs(db_session, "payable.due_soon", "payable.due_soon:" + str(int(today.id)) + ":")[0]
    assert "今天" in n.content
    assert n.payload["emphasis"] == ["将到期", "1234 元", "今天"]
    _assert_emphasis_ok(n)


def test_payable_is_not_repeated_and_stops_once_paid(db_session: Session) -> None:
    """去重（同单据同到期日一条）＋ 付清之后不再提醒。"""
    from app.services import supplier_service

    term = message_producers.PAYABLE_TERM_DAYS
    p = _payable(db_session, doc_date=D - timedelta(days=term + 2), amount="500.00")
    prefix = "payable.overdue:" + str(int(p.id)) + ":"
    assert message_producers.notify_payable(db_session, payable=p, kind="payable.overdue", day=D) >= 1
    db_session.commit()
    assert message_producers.notify_payable(db_session, payable=p, kind="payable.overdue", day=D) == 0
    db_session.commit()
    assert len(_msgs(db_session, "payable.overdue", prefix)) == 1

    assert supplier_service.unpaid_of(p, Decimal("0")) == Decimal("500.00")
    supplier_service.pay_supplier(
        db_session,
        p,
        amount=Decimal("500.00"),
        pay_date=D,
        channel="bank",
        remark="",
        operator_id=None,
    )
    db_session.commit()
    assert message_producers.notify_payable(db_session, payable=p, kind="payable.overdue", day=D) == 0


# ---------------------------------------------------------------- ③ 挂账单位超额度

def test_arrears_over_limit_fires_only_over_the_credit_limit(db_session: Session) -> None:
    """超了才发 danger；没超一个字都不发（"额度空 = 不限额"由报表侧解释，这里不重算）。"""
    over_unit = ArrearsUnit(name="测试挂账单位-" + uuid.uuid4().hex[:8], credit_limit=Decimal("100.00"))
    under_unit = ArrearsUnit(name="测试挂账单位-" + uuid.uuid4().hex[:8], credit_limit=Decimal("9999.00"))
    db_session.add_all([over_unit, under_unit])
    db_session.commit()
    order_ids = [
        _delivered_order(db_session, unit=over_unit, amount="300.00"),
        _delivered_order(db_session, unit=under_unit, amount="300.00"),
    ]
    try:
        assert message_producers.scan_arrears_over_limit(db_session, day=D) >= 1
        db_session.commit()
        rows = _msgs(db_session, "arrears.over_limit", "arrears.over_limit:" + str(int(over_unit.id)) + ":")
        assert len(rows) == 1
        n = rows[0]
        assert n.severity == "danger"
        assert n.payload["unit_id"] == int(over_unit.id)
        assert "已超额度" in n.content and "超出 200 元" in n.content
        assert n.payload["emphasis"] == ["已超额度", "300 元", "200 元"]
        _assert_emphasis_ok(n)
        # 没超的那家一个字都没有
        assert _msgs(db_session, "arrears.over_limit", "arrears.over_limit:" + str(int(under_unit.id)) + ":") == []
    finally:
        _drop_orders(db_session, order_ids)


def test_arrears_over_limit_is_once_a_month(db_session: Session) -> None:
    """额度是**持续状态**不是事件：同一单位同一自然月只有一条，下个月才是新的一条。"""
    unit = ArrearsUnit(name="测试挂账单位-" + uuid.uuid4().hex[:8], credit_limit=Decimal("10.00"))
    db_session.add(unit)
    db_session.commit()
    order_ids = [_delivered_order(db_session, unit=unit, amount="99.00")]
    prefix = "arrears.over_limit:" + str(int(unit.id)) + ":"
    try:
        assert message_producers.scan_arrears_over_limit(db_session, day=D) >= 1
        db_session.commit()
        assert message_producers.scan_arrears_over_limit(db_session, day=D) == 0   # 同月重跑不增加
        db_session.commit()
        assert len(_msgs(db_session, "arrears.over_limit", prefix)) == 1
        nxt = date(D.year + (1 if D.month == 12 else 0), 1 if D.month == 12 else D.month + 1, 1)
        assert message_producers.scan_arrears_over_limit(db_session, day=nxt) >= 1
        db_session.commit()
        assert len(_msgs(db_session, "arrears.over_limit", prefix)) == 2
    finally:
        _drop_orders(db_session, order_ids)


def _delivered_order(db: Session, *, unit: ArrearsUnit, amount: str) -> int:
    """一张"已送达、挂这家单位、钱还没收"的单 —— 欠款报表的唯一输入。

    ⚠️ 用例结束**必须删掉**（见 `_drop_orders`）：这些是**已提交**的行，
    留着会改掉别的报表用例看到的余额（共用一份测试库）。
    """
    from app.models import User as _User

    shipper = db.scalars(select(_User).where(_User.phone == "13800000002")).first()
    o = Order(
        order_no="T" + uuid.uuid4().hex[:10].upper(),
        status=OrderStatus.DELIVERED,
        order_date=D,
        shipper_id=int(shipper.id) if shipper is not None else None,
        delivered_at=datetime(D.year, D.month, D.day, 4, 0, 0),   # UTC 04:00 = 当地 12:00
        payment_method="arrears",
        paid=False,
        arrears_unit_id=int(unit.id),
        arrears_unit_name=str(unit.name),
    )
    db.add(o)
    db.flush()
    db.add(
        OrderProduct(
            order_id=int(o.id),
            product_name_snapshot="测试货物",
            quantity=1,
            unit_price=Decimal(amount),
            line_total=Decimal(amount),
        )
    )
    db.commit()
    return int(o.id)


def _drop_orders(db: Session, order_ids: list[int]) -> None:
    if not order_ids:
        return
    db.execute(delete(OrderProduct).where(OrderProduct.order_id.in_(order_ids)))
    db.execute(delete(Order).where(Order.id.in_(order_ids)))
    db.commit()


# ---------------------------------------------------------------- ④ 发票已开具

def test_invoice_issued_is_info_and_points_at_the_invoice(db_session: Session) -> None:
    """发票开具 = info（只是告知，不上色之外的风险色）；深链键 invoice_id。"""
    inv = Invoice(
        direction="output",
        invoice_no="INV" + uuid.uuid4().hex[:8].upper(),
        invoice_date=D,
        amount=Decimal("1130.00"),
    )
    db_session.add(inv)
    db_session.commit()
    db_session.refresh(inv)

    assert message_producers.notify_invoice_issued(db_session, invoice=inv) >= 1
    db_session.commit()
    rows = _msgs(db_session, "invoice.issued", "invoice.issued:" + str(int(inv.id)) + ":")
    assert len(rows) == 1
    n = rows[0]
    assert n.severity == "info"
    assert n.payload["invoice_id"] == int(inv.id)
    assert "已开具" in n.content and "销项发票" in n.content and "1130 元" in n.content
    assert n.payload["emphasis"] == ["已开具", "1130 元", n.payload["invoice_no"]]
    _assert_emphasis_ok(n)

    # 同一张票只发一条（重复点开具不会刷屏）
    assert message_producers.notify_invoice_issued(db_session, invoice=inv) == 0
    db_session.commit()
    assert len(_msgs(db_session, "invoice.issued", "invoice.issued:" + str(int(inv.id)) + ":")) == 1


# ---------------------------------------------------------------- ⑤ 账号：新设备登录 / 解冻

def test_new_device_login_notifies_only_the_owner_and_only_on_login(db_session: Session) -> None:
    """新设备登录：只给**本人**发 danger、点名设备尾号；老设备重访 / 注册绑第一台都不发。"""
    u = _fresh_user(db_session)
    device = "testinstall" + uuid.uuid4().hex[:10]

    binding = device_service.bind_device(db_session, user=u, device_id=device, source="login")
    db_session.commit()
    assert binding is not None

    rows = _msgs(
        db_session, "account.new_device_login", "account.new_device_login:" + str(int(binding.id)) + ":"
    )
    assert len(rows) == 1
    n = rows[0]
    assert n.recipient_id == int(u.id)                 # ⛔ 只给本人，不给派单员
    assert n.severity == "danger"
    assert n.payload["user_id"] == int(u.id)           # §五：账号族的深链键
    assert n.payload["device_tail"] == device[-4:]
    assert device[-4:] in n.content
    assert "新设备登录" in n.content
    assert device not in n.content                     # 只给尾号，不给整串设备指纹
    _assert_emphasis_ok(n)

    # 本机重访：不是新设备，一个字都不发
    device_service.bind_device(db_session, user=u, device_id=device, source="login")
    db_session.commit()
    assert len(_msgs(db_session, "account.new_device_login")) == 1

    # 注册时绑第一台设备不是"新设备登录"
    u2 = _fresh_user(db_session)
    device_service.bind_device(db_session, user=u2, device_id="testinstall" + uuid.uuid4().hex[:10], source="register")
    db_session.commit()
    assert _msgs(db_session, "account.new_device_login", "%:" + str(int(u2.id))) == []
    assert len(_msgs(db_session, "account.new_device_login")) == 1


def test_device_unfrozen_is_info_and_once_per_action(db_session: Session) -> None:
    """解冻：给本人一条 info（点名"几台"）；同一次操作重放不再发第二条。"""
    u = _fresh_user(db_session)
    assert message_producers.notify_device_unfrozen(db_session, user_id=int(u.id), count=2, anchor="2026-10-11T03:00:00") >= 1
    db_session.commit()
    n = _msgs(db_session, "account.device_unfrozen", "account.device_unfrozen:" + str(int(u.id)) + ":")[0]
    assert n.recipient_id == int(u.id)
    assert n.severity == "info"
    assert n.payload["user_id"] == int(u.id)
    assert "已解冻" in n.content and "2 台" in n.content
    assert n.payload["emphasis"] == ["已解冻", "2 台"]
    _assert_emphasis_ok(n)

    assert message_producers.notify_device_unfrozen(
        db_session, user_id=int(u.id), count=2, anchor="2026-10-11T03:00:00"
    ) == 0
    # 今天又解冻一次 = 另一件事，该有第二条
    assert message_producers.notify_device_unfrozen(
        db_session, user_id=int(u.id), count=1, anchor="2026-10-11T09:00:00"
    ) >= 1
    db_session.commit()
    assert len(_msgs(db_session, "account.device_unfrozen", "account.device_unfrozen:" + str(int(u.id)) + ":")) == 2


# ---------------------------------------------------------------- 每日兜底扫描（防漏）

def test_daily_scan_reruns_without_adding_a_single_row(db_session: Session) -> None:
    """**这条就是任务书要的那个判据**：连续跑两次扫描，通知条数不增加。

    扫描是"按当前状态重算一遍"，与事件谁先谁后无关 —— 所以它必须可以随便重跑：
    第二次的四个计数全是 0，而且通知表的行数一个都不涨。
    """
    term = message_producers.PAYABLE_TERM_DAYS
    _product(db_session, stock=1, alert=20)
    _payable(db_session, doc_date=D - timedelta(days=term + 5))

    first = message_producers.run_daily_scan(db_session, day=D)
    assert set(first) == {"stock_low", "payable_due_soon", "payable_overdue", "arrears_over_limit"}
    assert first["stock_low"] >= 1
    assert first["payable_overdue"] >= 1
    total_after_first = db_session.scalar(select(func.count()).select_from(Notification))

    second = message_producers.run_daily_scan(db_session, day=D)
    assert second == {"stock_low": 0, "payable_due_soon": 0, "payable_overdue": 0, "arrears_over_limit": 0}
    assert db_session.scalar(select(func.count()).select_from(Notification)) == total_after_first


def test_every_produced_type_has_a_producer_and_a_severity() -> None:
    """七类都真的有人生产；两类如实不做但理由写清楚了。"""
    for t in message_producers.PRODUCED:
        assert t in message_center.SEVERITY_BY_TYPE
    assert set(message_producers.PRODUCED) | set(message_producers.NOT_PRODUCED) == {
        "stock.low",
        "stock.near_low",
        "arrears.over_limit",
        "payable.due_soon",
        "payable.overdue",
        "invoice.issued",
        "vehicle.inspection_due",
        "account.new_device_login",
        "account.device_unfrozen",
    }
    for t, why in message_producers.NOT_PRODUCED.items():
        assert len(why) >= 40, t       # 理由必须是"数据不存在"这种有信息量的话
