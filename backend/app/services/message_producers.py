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

## 哪几类做了（如实，判据与变更单对账）

**十类全都有生产者了** —— FEAT-0022（2026-10-11）把 FEAT-0021 如实留下的最后两类补齐：

FEAT-0021 当时写着"没做"的两类，理由都是"**字段全库不存在**"（不是"没来得及"）。
2026-10-11 需求方给了口径，两条都不需要新造那份数据：

* **`stock.near_low`**：不新增任何字段，改用**百分比**口径 —— 偏低线 = 报警阈值 ×
  `(1 + NEAR_LOW_RATIO_PERCENT%)`。用户原话：「在**报警的那个水平宽松一点**，
  就显示『库存偏低』」。分档的唯一实现 = [stock_band]。
* **`vehicle.inspection_due` / `vehicle.inspection_overdue`**：车辆台账加了两个**可空**日期
  （上牌日期 / 上次年检日期，迁移 `033_vehicle_inspection.py`），"下次该检了"是**派生量**
  （`services/inspection_due.py` 现算，⛔ 不落库）。用户原话：「到我给那个车子建档案的时候
  会填一下就是这车的**上牌日期**。或者说是**上一个年检日期**啊方便我们去做一个提醒」。

## 触发时机

- **事件驱动**（跟着业务那一次写库走，同一个事务）：
  `account.new_device_login`（登录时真的新绑了一台）、`account.device_unfrozen`（派单员解冻）、
  `stock.low`（手工出入库 / 送达实扣之后）、`invoice.issued`（开票）。
- **每日兜底扫描**（`run_daily_scan`，挂在 `main.py` 既有的每日循环旁边）：
  库存不足 / 库存偏低 / 应付临期 / 应付逾期 / 挂账单位超限 / 年检临期 / 年检逾期。
  事件驱动的几类也会被它兜到（防漏），幂等键保证不会重复刷屏。
  ⚠️ **年检没有别的触发点**：它不跟着任何一次写库走（"今天到没到期"与用户改了什么无关），
  所以这里是它唯一的入口 —— 每日扫一遍全车队。

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

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import outbox
from app.core.business_time import business_today
from app.models.invoice import Invoice
from app.models.notification import Notification
from app.models.product import Product
from app.models.supplier import Supplier, SupplierPayable
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import inspection_due
from app.services import message_center
from app.services.message_center import active_dispatchers, create_message
from app.services.money_text import money_text

logger = logging.getLogger(__name__)

__all__ = [
    "NEAR_LOW_RATIO_PERCENT",
    "NOT_PRODUCED",
    "PAYABLE_DUE_SOON_DAYS",
    "PAYABLE_TERM_DAYS",
    "PRODUCED",
    "notify_device_unfrozen",
    "notify_inspection",
    "notify_invoice_issued",
    "notify_new_device_login",
    "notify_payable",
    "notify_stock_low",
    "payable_due_date",
    "payable_kind",
    "run_daily_scan",
    "scan_arrears_over_limit",
    "scan_inspection_due",
    "scan_payables",
    "scan_stock_low",
    "stock_band",
]

#: **真有**生产者的十类（判据拿它跟 `NOT_PRODUCED` 一起对十类做全集核对）。
#: FEAT-0022（2026-10-11）把 `stock.near_low` 与两类年检补齐后，这里就是全集。
PRODUCED: tuple[str, ...] = (
    "stock.low",
    "stock.near_low",
    "payable.due_soon",
    "payable.overdue",
    "arrears.over_limit",
    "invoice.issued",
    "vehicle.inspection_due",
    "vehicle.inspection_overdue",
    "account.new_device_login",
    "account.device_unfrozen",
)

#: **没有**生产者的类型 ＋ 逐条理由。
#:
#: FEAT-0022 之后这里是**空的** —— 十类全都有生产者了。⛔ 不要顺手删掉这张表：
#: 它的用处是"下一单如果又不做某一类，理由必须写在这里"（判据与变更单都拿它对账）。
#: ⛔ 更不许往里塞"下一单做"这种没信息量的话 —— 理由必须是"**数据不存在**"，因为那才是事实。
#: ⚠️ 已经做了的类型**必须从这里移走**：同一类既在 `PRODUCED` 又在 `NOT_PRODUCED`，
#: 等于"告诉下一个人它还缺字段"（判据专门钉着这一条）。
NOT_PRODUCED: dict[str, str] = {}

#: 应付账期（天）。库里**没有**账期/到期日字段，到期日只能按"单据日期 + 这个数"**推定**。
PAYABLE_TERM_DAYS = 30

#: 到期前多少天开始提醒（warn 档）。7 天 = 一周，够走一次付款流程。
PAYABLE_DUE_SOON_DAYS = 7

#: 「库存偏低」比「库存不足」放宽多少**百分比**（用户 2026-10-11：在报警水平上宽松一点按百分比算）。
#:
#: 用户口径（逐字）：「**库存偏低**的话，我们**按百分比来算** —— 也就是说，他肯定会设置这个
#: 库存的报警嘛……然后我们在**报警的那个水平宽松一点**，就显示『库存偏低』，是这样子的。」
#:
#: 于是偏低线 = `low_stock_alert × (1 + NEAR_LOW_RATIO_PERCENT / 100)`：
#: 阈值 10 件的商品，10~11 件报「偏低」（warn）、10 件以下才报「不足」（danger）。
#: ⚠️ **恰好等于阈值算「偏低」**（等于阈值说明还没有跌破它）—— 判据与单测都钉着这条边界。
#: ⛔ 比较一律走整数（`stock * 100 < alert * 100 + alert * NEAR_LOW_RATIO_PERCENT`），
#: 不用浮点：`alert * 1.2` 在大数上会给出"差一件"的边界错，而这是"该不该补货"的判断。
NEAR_LOW_RATIO_PERCENT = 20

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
def stock_band(stock: int, alert: int) -> str | None:
    """库存落在哪一档（**唯一**的分档判据）；还没到线 = `None`。

    | 当前库存 | 返回 | 档位（由 `message_center` 定） | 说的是什么 |
    | --- | --- | --- | --- |
    | `< alert` | `"stock.low"` | danger | 已经跌破报警阈值，该补货了 |
    | `alert <= stock` 且 `< alert ×`(1 + `NEAR_LOW_RATIO_PERCENT`%) | `"stock.near_low"` | warn | 已经到报警阈值，留意别跌破 |
    | 更高 | `None` | —— | 不发 |

    ⚠️ **恰好等于阈值算「偏低」（warn），不是「危险」**：等于阈值说明还没有跌破它，
    与"已经跌破"是两件不同的事 —— 而用户 2026-10-11 要的正是"在报警的那个水平**宽松一点**"
    的这一档。这条边界有单测与判据各自钉着（⛔ 别把它改成 `<`）。
    ⚠️ `alert <= 0` 是"**不报警**"，不是"阈值是 0"（见 `models/product.py`）——
    没有阈值就没有偏低线，两档都不发。
    ⛔ 比较一律走整数（`stock * 100 < alert * (100 + NEAR_LOW_RATIO_PERCENT)`）：
    `alert * 1.2` 是浮点，大数上会给出"差一件"的边界错，而这是"该不该补货"的判断。
    """
    if alert <= 0:
        return None
    if stock < alert:
        return "stock.low"
    if stock * 100 < alert * (100 + NEAR_LOW_RATIO_PERCENT):
        return "stock.near_low"
    return None


#: 两档库存提醒**全部的**差异（结论词 / 正文尾句）。判档只有 [stock_band] 一处，
#: 文案与类型名只有这一张表一处 —— 将来加第三档改这里，⛔ 不是往下面的函数里塞 if。
#: ⚠️ 键**就是** `notifications.type`，而幂等键前缀也用它拼：类型名与幂等键前缀
#: 于是在构造上不可能分叉（改一处必然两处一起变）。
_STOCK_BANDS: dict[str, tuple[str, str]] = {
    "stock.low": ("库存不足", "，已低于报警阈值 {alert} {unit}，请及时补货。"),
    "stock.near_low": ("库存偏低", "，已到报警阈值 {alert} {unit}，请留意补货，别跌破阈值。"),
}


def notify_stock_low(
    db: Session, *, product_id: int, stock: int | None = None, day: date | None = None
) -> int:
    """库存到了该提醒的线 → 每个在用派单员一条（**同商品同一天只一条**）。

    一个入口判两档，**两档互斥、只会发一条**（判据钉着"两类同时只发一条"）：

    * 低于报警阈值 → `stock.low`（danger，「库存不足」）；
    * 到了阈值、但还在 `×(1 + NEAR_LOW_RATIO_PERCENT%)` 以内 → `stock.near_low`（warn，「库存偏低」）。

    ⛔ 档位**不在这里定**（`message_center.SEVERITY_BY_TYPE` 说了算），这里只回答"算哪一档"
    （[stock_band]）。

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
    band = stock_band(stock, alert)
    if band is None:
        return 0
    when = day or business_today()
    unit = (product.unit or "件").strip() or "件"
    verb, tail = _STOCK_BANDS[band]
    title = verb + "：" + str(product.name)
    content = (
        "商品「" + str(product.name) + "」" + verb + "：当前库存 " + str(int(stock)) + " " + unit
        + tail.format(alert=alert, unit=unit)
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
        type_=band,
        category="reminder",
        title=title,
        content=content,
        payload=payload,
        idem_key=band + ":" + str(int(product.id)) + ":" + when.isoformat(),
        emphasis=(str(int(stock)) + " " + unit, str(alert) + " " + unit),
    )


def scan_stock_low(db: Session, *, day: date) -> tuple[int, int]:
    """每日兜底：把所有"活着、上架、设了阈值、库存已到线"的商品各发一条。

    返回 `(低于报警阈值, 偏低)` 两个计数 —— 与 `scan_payables` 同一个形状（那边是
    `(临期, 逾期)`），让 `run_daily_scan` 的返回字典能把两档分开报。

    ⚠️ 选行条件用**同一个百分比口径**（`×100` 的整数写法），⛔ 不是另抄一遍
    `coalesce(stock,0) <= low_stock_alert`：抄一遍的下场是"每日扫描扫不出来、
    手工出入库却发得出"（两处判断悄悄分家，而两边都不报错）。
    """
    rows = db.scalars(
        select(Product).where(
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
            Product.low_stock_alert > 0,
            func.coalesce(Product.stock, 0) * 100
            < Product.low_stock_alert * (100 + NEAR_LOW_RATIO_PERCENT),
        )
    ).all()
    low = near_low = 0
    for p in rows:
        stock = int(p.stock or 0)
        if notify_stock_low(db, product_id=int(p.id), stock=stock, day=day):
            if stock_band(stock, int(p.low_stock_alert or 0)) == "stock.near_low":
                near_low += 1
            else:
                low += 1
    return low, near_low


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
# ④ 车辆年检：临期（warn）/ 逾期（danger）
# ---------------------------------------------------------------------------
def notify_inspection(db: Session, *, vehicle: Vehicle, kind: str, day: date) -> int:
    """一台车的年检提醒（**临期与逾期只会有一条**）。

    `kind` 必须来自 `inspection_due.inspection_kind()`（**唯一**的分档判据）——
    ⛔ 这里不自己比日期分档，也不定档位（档位由 `message_center.SEVERITY_BY_TYPE` 定）。

    ⚠️ **两格日期都空的车不发**：`inspection_due.next_due_date()` 返回 None 时直接 0。
    ⛔ 不许拿"今天"或建档日期凑一个到期日出来 —— 那不是提醒，是系统自己编的事实。

    ⚠️ 正文必须**由 `days_text` 拼出来**：它就是重点词里那个片段。
    （FEAT-0021 踩过一次：把"还有 N 天"只写进重点词、正文里换了个说法，
      `emphasis_for` 的 `word not in text` 那道闸会把片段**静默丢掉**，卡片上就少一个落点。）
    """
    due = inspection_due.next_due_date(vehicle.registration_date, vehicle.last_inspection_date)
    if due is None:
        return 0
    plate = str(vehicle.plate_no or "").strip()
    plate_text = plate or "（无车牌）"
    left = (due - day).days
    if kind == "vehicle.inspection_overdue":
        days_text = str(-left) + " 天"
        title = "车辆年检已逾期：" + plate_text
        content = (
            "车辆「" + plate_text + "」的年检已逾期 " + days_text
            + "（下次年检日期 " + due.isoformat() + "），请尽快安排年检。"
        )
    else:
        days_text = ("还有 " + str(left) + " 天") if left > 0 else "今天到期"
        title = "车辆年检将到期：" + plate_text
        content = (
            "车辆「" + plate_text + "」的下次年检日期是 " + due.isoformat()
            + "，" + days_text + "，请提前安排年检。"
        )
    payload = {
        # ⚠️ §五：车辆族**永远不跳**（`MessageGrading.noticeRoute` 该支返回 null）。
        # 这里给 vehicle_id / plate_no 只是让卡片与排障**按车定位**，⛔ 不是深链承诺。
        "vehicle_id": int(vehicle.id),
        "plate_no": plate,
        "due_date": due.isoformat(),
        "days_left": left,
    }
    return _to_dispatchers(
        db,
        type_=kind,
        category="reminder",
        title=title,
        content=content,
        payload=payload,
        # 「事实 + 到期日」：同一台车的**同一次**年检只发一条；
        # 明年算出来的 due 变了 → 键变了 → 明年那条照发（这正是要的）。
        idem_key=kind + ":" + str(int(vehicle.id)) + ":" + due.isoformat(),
        emphasis=(plate_text, days_text),
    )


def scan_inspection_due(db: Session, *, day: date) -> tuple[int, int]:
    """每日兜底：把"该年检了"的车各发一条，返回 `(临期, 逾期)` 两个计数。

    **为什么年检只有这一个入口**：它不跟着任何一次写库走 —— "今天到没到期"与用户改了
    什么无关（改的是车牌、司机、分类）。每日扫一遍全车队是唯一能保证不漏的地方。

    ⚠️ 只挑**在用**的车（`is_active`）：停用 = 卖了 / 封存，再催年检是噪音
    （车辆没有软删列，`is_active` 就是"这台车还算不算数"的唯一判据）。

    ⚠️ 过滤条件「两格日期至少一个非空」只是"这台车有没有可算的起点"，
    ⛔ **不是**分档判据：分档仍然只有 `inspection_due.inspection_kind()` 一处。
    """
    rows = db.scalars(
        select(Vehicle).where(
            Vehicle.is_active.is_(True),
            or_(
                Vehicle.registration_date.is_not(None),
                Vehicle.last_inspection_date.is_not(None),
            ),
        )
    ).all()
    soon = overdue = 0
    for v in rows:
        kind = inspection_due.inspection_kind(
            v.registration_date, v.last_inspection_date, day=day
        )
        if kind is None:
            continue
        sent = notify_inspection(db, vehicle=v, kind=kind, day=day)
        if kind == "vehicle.inspection_overdue":
            overdue += sent
        else:
            soon += sent
    return soon, overdue


# ---------------------------------------------------------------------------
# ⑤ 发票开具（info）
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
# ⑥ 账号：新设备登录（danger）/ 设备解冻（info）—— 发给**账号本人**
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
    """每日兜底扫描：库存不足 / 库存偏低 / 应付临期 / 应付逾期 / 挂账单位超限 /
    年检临期 / 年检逾期。

    **为什么要有它**：事件驱动的钩子挂在几条写路径上，任何一条被绕过（脚本直接改库、
    以后新增的写路径、钩子之前进程崩了）消息就永远丢了 —— 而"没发"和"没出事"在界面上
    长得一模一样。扫描按**当前状态**重算一遍，与事件谁先谁后无关。
    ⚠️ 年检两类**只**靠它（没有任何写路径钩子），所以它是那两类的唯一入口。

    **可以随便重跑**：每一条都带幂等键（同商品同一天 / 同单据同到期日 / 同单位同自然月 /
    同车同到期日），第二次跑出来的条数是 0（判据连续跑两次断言"通知条数不增加"）。

    返回七个计数（键名 = 人读的名字，⛔ 不是消息类型名）：`stock_low` / `stock_near_low` /
    `payable_due_soon` / `payable_overdue` / `arrears_over_limit` / `inspection_due` /
    `inspection_overdue`。
    """
    when = day or business_today()
    soon, overdue = scan_payables(db, day=when)
    low, near_low = scan_stock_low(db, day=when)
    insp_soon, insp_overdue = scan_inspection_due(db, day=when)
    result = {
        "stock_low": low,
        "stock_near_low": near_low,
        "payable_due_soon": soon,
        "payable_overdue": overdue,
        "arrears_over_limit": scan_arrears_over_limit(db, day=when),
        "inspection_due": insp_soon,
        "inspection_overdue": insp_overdue,
    }
    db.commit()
    return result
