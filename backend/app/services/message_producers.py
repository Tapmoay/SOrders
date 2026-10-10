"""九类新消息的**生产者**（FEAT-0021）：让消息自己出现，而不是等人手工发。

## 这一单治的病

FEAT-0019 把**渲染**做完了（`notifications.severity` ＋ `payload["emphasis"]` ＋ App 卡片的竖条/配色/深链），
九类 type 也早就在 `message_center.SEVERITY_BY_TYPE` 里登记了档位 —— 但**没有生产者**：
没有任何一行代码往库里写它们。表现是"这九种消息永远不会出现"，而不是"显示了但样子不对"。

## 三条口径（⛔ 判据逐条钉着，别绕开）

1. **发什么**（文案 / 点名 / 深链）只有这一个文件；**怎么发**（档位判定 `severity_for`、
   `emphasis` 的四道闸、幂等键的拼法）仍然只有 `message_center` 一处。
   ⛔ 本文件里不许出现 `Notification(`、不许出现 `severity=`。
2. **去重靠 `idem_key` 的数据库唯一索引**（`uq_notifications_idem_key`），不靠"先查再发"：
   同一件事被算第二遍 = 返回已有那条。所以**每日兜底扫描可以随便重跑**（进程重启 / 多 worker /
   手工补跑都安全），而"同商品同一天只发一条"这种事不需要任何人记着。
3. **投递走事务发件箱**（`outbox.enqueue(..., "notifications.created")`）：消息与业务写在
   **同一个事务**里，"库里改了但没发"与"发出去了但库里没有"两种半边状态都不存在。

## 哪几类做了、哪几类没做（如实，判据与变更单对账）

做了（7）：`stock.low`、`payable.due_soon`、`payable.overdue`、`arrears.over_limit`、
`invoice.issued`、`account.new_device_login`、`account.device_unfrozen`。

⛔ 没做（2，理由在 `NOT_PRODUCED`，两份理由都是"字段全库不存在"，不是"没来得及"）：
`stock.near_low`、`vehicle.inspection_due`。两类都只是**登记了档位、不生产**，⛔ 不留半成品。

## 触发时机

- **事件驱动**（跟着业务那一次写库走，同一个事务）：
  `account.new_device_login`（登录时真的新绑了一台）、`account.device_unfrozen`（派单员解冻）、
  `stock.low`（手工出入库 / 送达实扣之后）、`invoice.issued`（开票）。
- **每日兜底扫描**（`run_daily_scan`，挂在 `main.py` 既有的每日循环旁边）：
  库存低 / 应付临期 / 应付逾期 / 挂账单位超限。事件驱动的几类也会被它兜到（防漏），
  幂等键保证不会重复刷屏。

## 收件人是谁

库存、应付、超限、发票都是**派单端的事**（工作台的那几格就在派单员那里）⇒ 发给**所有在用派单员**
（判据只有 `message_center.active_dispatchers` 一处）。
新设备登录 / 设备解冻是**账号自己的事** ⇒ 发给**账号本人**（`users.id`）。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import outbox
from app.core.business_time import business_today
from app.models.invoice import Invoice
from app.models.notification import Notification
from app.models.product import Product
from app.models.supplier import Supplier, SupplierPayable
from app.models.user import User
from app.services import message_center
from app.services.message_center import active_dispatchers, create_message
from app.services.money_text import money_text

logger = logging.getLogger(__name__)

__all__ = [
    "NOT_PRODUCED",
    "PAYABLE_DUE_SOON_DAYS",
    "PAYABLE_TERM_DAYS",
    "PRODUCED",
    "notify_device_unfrozen",
    "notify_invoice_issued",
    "notify_new_device_login",
    "notify_payable",
    "notify_stock_low",
    "payable_due_date",
    "payable_kind",
    "run_daily_scan",
    "scan_arrears_over_limit",
    "scan_payables",
    "scan_stock_low",
]

#: 本轮**真有**生产者的七类（判据拿它跟 `NOT_PRODUCED` 一起对九类做全集核对）。
PRODUCED: tuple[str, ...] = (
    "stock.low",
    "payable.due_soon",
    "payable.overdue",
    "arrears.over_limit",
    "invoice.issued",
    "account.new_device_login",
    "account.device_unfrozen",
)

#: 本轮**没有**生产者的两类 ＋ 逐条理由。
#: ⛔ 不许往里塞"下一单做"这种没信息量的话 —— 理由必须是"数据不存在"，因为那才是事实。
NOT_PRODUCED: dict[str, str] = {
    "stock.near_low": (
        "「建议水位」字段**全库不存在**（FEAT-0019 与 FEAT-0021 两次全库查过：products 只有 "
        "low_stock_alert 一个阈值）。要分两档就得先加一个可空的建议水位列，并且迁移 / 商品表单 / "
        "AI 动作三处一起跟上 —— 那是另一单。本轮**只做真实存在的那个阈值**（stock.low），"
        "stock.near_low 保留档位登记、不生产。"
    ),
    "vehicle.inspection_due": (
        "年检 / 保险日期字段**全库不存在**（grep 年检|inspection 在 backend/app 里只命中 "
        "message_center 自己的注释），没有到期日就没有「该提醒谁、提醒什么」。"
        "另外 App 的 MessageFamily.VEHICLE 本来就 → null（不跳），界面上也没有年检录入处。"
        "要做先得给车辆加年检日期（迁移 ＋ 表单），那是另一单。"
    ),
}

#: 应付账期（天）。库里**没有**账期/到期日字段，到期日只能按"单据日期 + 这个数"**推定**。
PAYABLE_TERM_DAYS = 30

#: 到期前多少天开始提醒（warn 档）。7 天 = 一周，够走一次付款流程。
PAYABLE_DUE_SOON_DAYS = 7

#: 发票方向 → 文案前缀。认不出的方向**不猜**（前缀留空，正文照样发得出去）。
_INVOICE_DIRECTION_TEXT = {"output": "销项发票", "input": "进项发票"}


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _yuan(v: Any) -> str:
    """金额在**文案里**的写法（去尾零）—— 与全项目同一条显示口径（`money_text`）。

    ⚠️ 顺带解决了点名的一致性：重点词里那个金额片段就是本函数的返回值，
    所以"片段必须原样出现在正文里"这件事是**构造上成立**的，不靠人核对。
    """
    return money_text(v) + " 元"


def _device_tail(device_id: str | None) -> str:
    """设备尾号（给人看的）：设备号的最后 4 位。

    ⛔ 只给尾号、不给整串：`X-Device-Id` 里带着 install_id 与签名，整串铺在通知列表里
    等于把设备指纹放在一个会被转发出屏幕的地方。尾号够本人认出"是不是我那台"。
    """
    s = str(device_id or "").strip()
    if not s:
        return "未知"
    return s[-4:] if len(s) >= 4 else s


def _send(
    db: Session,
    *,
    recipient_id: int,
    category: str,
    type_: str,
    title: str,
    content: str,
    payload: dict[str, Any],
    idem_key: str,
    emphasis: tuple[str, ...] = (),
) -> Notification | None:
    """建一条消息 ＋ 把 `notifications.created` 事件写进**同一个事务**。

    返回 `None` = 这个收件人已经有同键的那条（**去重命中**，本次没有新写）。

    ⚠️ 开头那个 `select` **不是**去重机制，只是为了让调用方如实知道"这次到底新写了没有"
    （扫描要报数字、要能证明"连跑两次不增加"）。真正的去重是 `notifications.idem_key` 上的
    **唯一索引** —— `create_message` 把插入包在 SAVEPOINT 里，撞了唯一键就回头取已有那条
    （两个 worker 同时跑也只有一个能插进去）。
    """
    key = message_center.idem_key_for(idem_key, recipient_id)
    if db.scalars(select(Notification.id).where(Notification.idem_key == key)).first() is not None:
        return None
    try:
        n = create_message(
            db,
            recipient_id=recipient_id,
            category=category,
            type=type_,
            title=title,
            content=content,
            payload=payload,
            idem_key=idem_key,
            emphasis=emphasis,
        )
    except IntegrityError as exc:
        # 两个 worker 同时跑兜底扫描（uvicorn --workers 2 的启动瞬间）时：同一条事实两边都算出来了，
        # 对方先插进去并提交。MySQL 是 REPEATABLE READ ⇒ 本事务的读快照早于对方提交，
        # `create_message` 撞键后**重查看不到那一行**、于是把 IntegrityError 原样抛出来。
        # 那不是故障 —— 同一条事实**已经有人发了**，正是幂等键要的效果（至少一次 + 去重）。
        # ⛔ 只吞这一个唯一索引：别的完整性错误照旧往上抛（吞错会把真 bug 变成"静默没发"）。
        if "uq_notifications_idem_key" not in str(exc):
            raise
        logger.info("幂等键已被另一个进程写入，跳过这条：%s", key)
        return None
    outbox.enqueue(
        db,
        "notifications.created",
        {"notification_id": n.id},
        dedupe_key="notification.created:" + str(n.id),
    )
    return n


def _to_dispatchers(
    db: Session,
    *,
    type_: str,
    category: str,
    title: str,
    content: str,
    payload: dict[str, Any],
    idem_key: str,
    emphasis: tuple[str, ...] = (),
) -> int:
    """发给**所有在用派单员**，返回新写的条数。

    "谁算在用的派单员"只有 `message_center.active_dispatchers` 一处判据（本文件不自己写 where）。
    一个派单员都没有 = 0 条，⛔ 不报错：没人在用不是故障。
    """
    sent = 0
    for d in active_dispatchers(db):
        if _send(
            db,
            recipient_id=int(d.id),
            category=category,
            type_=type_,
            title=title,
            content=content,
            payload=payload,
            idem_key=idem_key,
            emphasis=emphasis,
        ) is not None:
            sent += 1
    return sent


# ---------------------------------------------------------------------------
# ① 库存：低于报警阈值（danger）
# ---------------------------------------------------------------------------
def notify_stock_low(
    db: Session, *, product_id: int, stock: int | None = None, day: date | None = None
) -> int:
    """库存低于报警阈值 → 每个在用派单员一条 danger（**同商品同一天只一条**）。

    `stock` 能传就传**刚写完的那个数**（调用方手上就有，省一次查询）；不传就现读 ——
    但现读走的是 `select(Product.stock)`（只取列值），**不是** `product.stock`：
    送达实扣走的是 `update(...).values(stock=func.coalesce(...) + change)` 的 SQL 表达式自减，
    ORM 实例上那个数在同一个 session 里可能是**扣减前**的（那就是"库存 3 报成库存 8"）。

    ⚠️ `low_stock_alert = 0` 是"不报警"，不是"阈值是 0"（见 `models/product.py`）。
    """
    product = db.get(Product, int(product_id))
    if product is None or product.is_deleted:
        return 0
    if stock is None:
        stock = db.scalar(select(Product.stock).where(Product.id == int(product_id)))
    stock = int(stock or 0)
    alert = int(product.low_stock_alert or 0)
    if alert <= 0 or int(stock) > alert:
        return 0
    when = day or business_today()
    unit = (product.unit or "件").strip() or "件"
    title = "库存不足：" + str(product.name)
    content = (
        "商品「" + str(product.name) + "」库存不足：当前库存 " + str(int(stock)) + " " + unit
        + "，已低于报警阈值 " + str(alert) + " " + unit + "，请及时补货。"
    )
    payload = {
        # §五：库存族的深链键是 product_id（App 拿它开库存管理并定位到这个商品）。
        "product_id": int(product.id),
        "product_name": str(product.name),
        "stock": int(stock),
        "low_stock_alert": alert,
        "stock_date": when.isoformat(),
    }
    return _to_dispatchers(
        db,
        type_="stock.low",
        category="reminder",
        title=title,
        content=content,
        payload=payload,
        idem_key="stock.low:" + str(int(product.id)) + ":" + when.isoformat(),
        emphasis=(str(int(stock)) + " " + unit, str(alert) + " " + unit),
    )


def scan_stock_low(db: Session, *, day: date) -> int:
    """每日兜底：把所有"活着、上架、设了阈值、库存已到线"的商品各发一条。"""
    rows = db.scalars(
        select(Product).where(
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
            Product.low_stock_alert > 0,
            func.coalesce(Product.stock, 0) <= Product.low_stock_alert,
        )
    ).all()
    sent = 0
    for p in rows:
        sent += notify_stock_low(db, product_id=int(p.id), stock=int(p.stock or 0), day=day)
    return sent


# ---------------------------------------------------------------------------
# ② 应付：临期（warn）/ 逾期（danger）
# ---------------------------------------------------------------------------
def payable_due_date(payable: SupplierPayable) -> date:
    """应付单的**推定**到期日 = 单据日期 + `PAYABLE_TERM_DAYS`。

    ⚠️ 库里**没有**账期 / 到期日字段（FEAT-0021 全库查过：`due_date` / `账期` 只出现在
    `message_center` 自己的注释里）。所以这是**推定**，推定规则只此一处，
    消息正文如实写出"到期日"与"还剩几天"，用户看得见它是怎么来的。
    等真有了账期字段（下一单），只改这一个函数。
    """
    return payable.doc_date + timedelta(days=PAYABLE_TERM_DAYS)


def payable_kind(payable: SupplierPayable, *, day: date) -> str | None:
    """一张应付单**今天算哪一档**（唯一的分档判据），还没到点 = `None`。

    ⛔ 风险档不在这里定：`payable.due_soon`=warn、`payable.overdue`=danger 由
    `message_center.SEVERITY_BY_TYPE` 说了算。这里只回答"算哪一档"。
    """
    left = (payable_due_date(payable) - day).days
    if left < 0:
        return "payable.overdue"
    if left <= PAYABLE_DUE_SOON_DAYS:
        return "payable.due_soon"
    return None


def notify_payable(db: Session, *, payable: SupplierPayable, kind: str, day: date) -> int:
    """一张应付单的临期 / 逾期提醒（**已付清的不发**）。

    口径：还差多少由 `supplier_service.payable_paid` ＋ `unpaid_of` 算 ——
    ⛔ 本文件不自己 SUM 现金流水（那是"同一笔钱两个数"的开头，`_check_supplier_payables.py` 会拦）。
    """
    from app.services import supplier_service

    supplier = db.get(Supplier, int(payable.supplier_id))
    if supplier is None or supplier.is_deleted:
        return 0
    unpaid = supplier_service.unpaid_of(payable, supplier_service.payable_paid(db, int(payable.id)))
    if unpaid <= Decimal("0"):
        # 已经付清 = 没有该付的钱。「还差 0 元」不是提醒，是噪音。
        return 0
    due = payable_due_date(payable)
    left = (due - day).days
    money = _yuan(unpaid)
    if kind == "payable.overdue":
        days_text = str(-left) + " 天"
        title = "应付款已逾期：" + str(payable.title)
        content = (
            "应付给「" + str(supplier.name) + "」的「" + str(payable.title) + "」还欠 " + money
            + "，已逾期 " + days_text + "（到期日 " + due.isoformat() + "），请尽快安排付款。"
        )
    else:
        # ⚠️ 正文必须**由 `days_text` 拼出来** —— 它就是重点词里那个片段。
        # 每个分支各写一遍的那一版里，"今天到期"只写在重点词里、正文写的是"就是今天"，
        # 于是 `emphasis_for` 那道「正文里找不到就不标」的闸会**安静地**把它丢掉：
        # 消息照发、卡片上少一个字，谁都不会报错。边界用例（就是今天那张单）钉的就是这条。
        days_text = "今天" if left == 0 else (str(left) + " 天")
        title = "应付款将到期：" + str(payable.title)
        content = (
            "应付给「" + str(supplier.name) + "」的「" + str(payable.title) + "」还欠 " + money
            + "，将到期：" + ("就是今天" if left == 0 else "还有 " + days_text)
            + "（" + due.isoformat() + "），请安排付款。"
        )
    payload = {
        # §五：应付族的深链键是 payable_id / supplier_id。
        "payable_id": int(payable.id),
        "supplier_id": int(payable.supplier_id),
        "supplier_name": str(supplier.name),
        "amount_unpaid": str(unpaid),
        "doc_date": payable.doc_date.isoformat(),
        "due_date": due.isoformat(),
    }
    return _to_dispatchers(
        db,
        type_=kind,
        category="reminder",
        title=title,
        content=content,
        payload=payload,
        idem_key=kind + ":" + str(int(payable.id)) + ":" + due.isoformat(),
        emphasis=(money, days_text),
    )


def scan_payables(db: Session, *, day: date) -> tuple[int, int]:
    """每日兜底：扫一遍所有活着的应付单。返回（临期条数, 逾期条数）。"""
    soon = overdue = 0
    rows = db.scalars(
        select(SupplierPayable).where(SupplierPayable.is_deleted.is_(False))
    ).all()
    for p in rows:
        kind = payable_kind(p, day=day)
        if kind is None:
            continue
        n = notify_payable(db, payable=p, kind=kind, day=day)
        if kind == "payable.overdue":
            overdue += n
        else:
            soon += n
    return soon, overdue


# ---------------------------------------------------------------------------
# ③ 挂账单位欠款超信用额度（danger）
# ---------------------------------------------------------------------------
def scan_arrears_over_limit(db: Session, *, day: date) -> int:
    """每日兜底：欠款超了信用额度的挂账单位各发一条（**同一单位同一自然月只一条**）。

    「超没超」由 `reports/balance_query.build_customer_balances` 现算 ——
    ⛔ 那是"逐债务人应收余额与账龄"的唯一实现（它自己已经算好 `over_limit`），
    本文件不重新 SUM 订单、也不重新解释"额度空 = 不限额"。
    额度是**持续状态**不是**事件** ⇒ 幂等键按自然月，不然每天一条、一个月 30 条。
    """
    from app.services.reports.balance_query import build_customer_balances

    sent = 0
    data = build_customer_balances(db, day)
    for row in data.get("rows") or []:
        if not row.get("over_limit"):
            continue
        unit_id = row.get("unit_id")
        limit = row.get("limit")
        used = row.get("credit_used")
        if unit_id is None or limit is None or used is None:
            continue
        name = str(row.get("name") or ("挂账单位#" + str(unit_id)))
        over = _yuan(Decimal(used) - Decimal(limit))
        title = "挂账单位已超额度：" + name
        content = (
            "挂账单位「" + name + "」已超额度：当前欠款 " + _yuan(used)
            + "，信用额度 " + _yuan(limit) + "，超出 " + over + "。"
        )
        payload = {
            # §五：欠款族的深链键是 customer_id（这里是"挂账单位"的身份键 unit_id）。
            "unit_id": int(unit_id),
            "unit_name": name,
            "credit_limit": str(limit),
            "credit_used": str(used),
        }
        sent += _to_dispatchers(
            db,
            type_="arrears.over_limit",
            category="reminder",
            title=title,
            content=content,
            payload=payload,
            idem_key="arrears.over_limit:" + str(int(unit_id)) + ":" + ("%04d-%02d" % (day.year, day.month)),
            emphasis=(_yuan(used), over),
        )
    return sent


# ---------------------------------------------------------------------------
# ④ 发票开具（info）
# ---------------------------------------------------------------------------
def notify_invoice_issued(db: Session, *, invoice: Invoice, operator_id: int | None = None) -> int:
    """发票开具成功 → 每个在用派单员一条 info（**同一张票只一条**）。

    `operator_id` 只是留个签名位（收款人是谁由 `tax_service` 的审计日志回答，
    ⛔ 不往消息里塞第二份操作人记录）。
    """
    if invoice is None or invoice.id is None:
        return 0
    raw = getattr(invoice.direction, "value", invoice.direction)
    prefix = _INVOICE_DIRECTION_TEXT.get(str(raw or "").strip().lower(), "")
    no = str(invoice.invoice_no or "").strip()
    no_text = no or "票号待补"
    amount = _yuan(invoice.amount)
    date_text = invoice.invoice_date.isoformat() if invoice.invoice_date else ""
    title = "发票已开具：" + no_text
    content = (
        prefix + "（票号 " + no_text + "）已开具，价税合计 " + amount
        + ("，开票日期 " + date_text + "。" if date_text else "。")
    )
    payload = {
        # §五：发票族的深链键是 invoice_id。
        "invoice_id": int(invoice.id),
        "invoice_no": no,
        "direction": str(raw or ""),
        "amount": str(invoice.amount),
    }
    emphasis = (amount, no) if no else (amount,)
    return _to_dispatchers(
        db,
        type_="invoice.issued",
        category="reminder",
        title=title,
        content=content,
        payload=payload,
        # 同一张票只一条；键里带上开票日期，与其它几族一样是"事实 + 日期"，
        # 判据也就能按 "invoice.issued:<id>:" 前缀只捞这一张票的消息。
        idem_key="invoice.issued:" + str(int(invoice.id)) + ":" + (date_text or "unknown"),
        emphasis=emphasis,
    )


# ---------------------------------------------------------------------------
# ⑤ 账号：新设备登录（danger）/ 设备解冻（info）—— 发给**账号本人**
# ---------------------------------------------------------------------------
def notify_new_device_login(
    db: Session,
    *,
    user: User,
    binding: Any,
    source: str,
) -> int:
    """账号在**新设备**上登录成功 → 给**本人**发一条 danger（一条绑定一条）。

    ⛔ 本函数**不判断"是不是新设备"**：那个判断只有一处 —— `device_service.bind_device` 里
    "本机重访就 early return"那个分叉，调用点就在它 `db.flush()` 之后
    （能走到那里就一定是一次新的绑定）。在登录路径里再写一套设备判断就是第二个口径。

    `source != SOURCE_LOGIN` 直接不发：注册时绑第一台设备不是"新设备登录"，
    给刚注册完的人发一条"您的账号在新设备上登录"只会吓人。
    """
    from app.services.device_service import SOURCE_LOGIN

    if str(source or "") != SOURCE_LOGIN:
        return 0
    if user is None or binding is None or getattr(binding, "id", None) is None:
        return 0
    tail = _device_tail(getattr(binding, "device_id", None))
    title = "新设备登录提醒"
    content = (
        "您的账号刚刚在新设备登录成功（设备尾号 " + tail + "）。"
        "如非本人操作，请尽快在账户管理里解冻这台设备并修改密码。"
    )
    payload = {
        # §五：账号/设备族的深链键是 user_id（账户管理看绑定设备）。
        "user_id": int(user.id),
        "device_tail": tail,
        "binding_id": int(binding.id),
    }
    n = _send(
        db,
        recipient_id=int(user.id),
        category="reminder",
        type_="account.new_device_login",
        title=title,
        content=content,
        payload=payload,
        idem_key=(
            "account.new_device_login:" + str(int(binding.id))
            + ":" + str(getattr(binding, "bound_at", "") or "")
        ),
        emphasis=(tail,),
    )
    return 1 if n is not None else 0


def notify_device_unfrozen(db: Session, *, user_id: int, count: int, anchor: str) -> int:
    """派单员解冻了这个账号的设备 → 给**本人**发一条 info（一次性操作对应用一条）。

    `anchor` 由调用方给（这次操作的时间戳）：同一个账号今天被解冻两次 = 两件事，
    但同一次操作被重复执行（幂等返回、请求重放）不会再发一条。
    """
    if int(count) <= 0:
        return 0
    title = "您的设备已解冻"
    content = (
        "您的账号有 " + str(int(count)) + " 台设备已解冻，现在可以在新设备上登录。"
        "如非本人申请，请联系派单员。"
    )
    payload = {
        # §五：账号/设备族的深链键是 user_id。
        "user_id": int(user_id),
        "device_count": int(count),
    }
    n = _send(
        db,
        recipient_id=int(user_id),
        category="reminder",
        type_="account.device_unfrozen",
        title=title,
        content=content,
        payload=payload,
        idem_key="account.device_unfrozen:" + str(int(user_id)) + ":" + str(anchor),
        emphasis=(str(int(count)) + " 台",),
    )
    return 1 if n is not None else 0


# ---------------------------------------------------------------------------
# 每日兜底扫描（挂 `main.py` 的每日循环；⛔ 可以随便重跑）
# ---------------------------------------------------------------------------
def run_daily_scan(db: Session, *, day: date | None = None) -> dict[str, int]:
    """每日兜底扫描：库存低 / 应付临期 / 应付逾期 / 挂账单位超限。

    **为什么要有它**：事件驱动的钩子挂在几条写路径上，任何一条被绕过（脚本直接改库、
    以后新增的写路径、钩子之前进程崩了）消息就永远丢了 —— 而"没发"和"没出事"在界面上
    长得一模一样。扫描按**当前状态**重算一遍，与事件谁先谁后无关。

    **可以随便重跑**：每一条都带幂等键（同商品同一天 / 同单据同到期日 / 同单位同自然月），
    第二次跑出来的条数是 0（判据连续跑两次断言"通知条数不增加"）。
    """
    when = day or business_today()
    soon, overdue = scan_payables(db, day=when)
    result = {
        "stock_low": scan_stock_low(db, day=when),
        "payable_due_soon": soon,
        "payable_overdue": overdue,
        "arrears_over_limit": scan_arrears_over_limit(db, day=when),
    }
    db.commit()
    return result
