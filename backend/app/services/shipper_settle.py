"""批发商**自己那一本账**的金额口径 —— 只有这一份实现。

## 口径（改这里就是改全局）

对**每一行商品**（`order_products`）：

    行应收     = `order_money.line_receivable(op)`      ← 复用已有那一份，**不另算一套**
    行已核销   = Σ 未删核销记录里这一行的金额（`shipper_settlement_lines`）
    行还可核销 = 行应收 − 行已核销            （≤ 0 = 这一行收齐了）

对**每一张订单**：

    单已核销   = Σ 各行已核销
    单还可核销 = Σ 各行还可核销

## 为什么必须只有一份
界面上"这一单还能核销 ¥X"是拿这份算的，提交时后端也拿它校验上限。
两边各写一遍必然走散（本项目栽过：界面让填 3、后端只认 2），
而走散的表现是**用户按界面上的数点了核销、后端报一句看不懂的错**。

## ⛔ 这份钱与派单员的钱是两笔
`order_money`（应收/已收/欠款）是**公司 ↔ 货主**的账；
本模块是**批发商 ↔ 他的下游货主**的账。两者**共用一张订单**，但一个字段都不交叉：
本模块只**读**订单行金额（那是我卖给他的货值），一个字节都不写回订单、账本或资金流水。

## ⛔ 同一笔钱不许被记两遍（2026-09-23 第 16 轮补的两道防线）

上面那张"还可核销"的表有个前提：**它读到的必须是此刻库里的真数**。原来它是普通
`SELECT` 读出来的，于是有两条路能把同一笔钱记两遍：

1. **恢复路径**（不需要并发）—— 核销 80 → 撤销 → 再核销 80 → **把撤掉的那笔恢复回来**：
   两笔都活着，这一单记了 160，而它的应收只有 80。界面上就有「已撤销」区的恢复入口，
   所以这是用户**点得到**的路径。
2. **并发路径** —— 两个请求同时读到"还可核销 100"，各自记 100（MySQL 的 REPEATABLE READ
   下普通 SELECT 读的是事务开始那一刻的快照）。派单员那份收款（`accounting_service`）
   早就用加锁读治过这一类错，这本账漏了。

两道防线分别在：
· **加锁读**（[settled_line_map] 的 `lock=True` + 调用方先 `lock_order_row`）—— 同一张单的
  两个核销请求在这里排队，后到的读到的是"还可核销 0"；
· **写后再算一次**（[over_settled_lines]）—— 不依赖锁（SQLite 上 `FOR UPDATE` 会被忽略），
  真超了就整笔回滚 + 一句能照着做的中文。
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderProduct
from app.models.enums import OrderStatus
from app.models.shipper_settlement import ShipperSettlement, ShipperSettlementLine
from app.services.order_money import line_receivable, q2

ZERO = Decimal("0")

#: 一次核销最多覆盖多少行（真正的上限来自订单本身：`OrderCreate.lines` 最多 10 行）
MAX_SETTLE_LINES = 50


def _alive_settlement_ids(db: Session) -> object:
    """没进回收站的核销记录（父记录的标记是唯一判据，见模型注释）。"""
    return select(ShipperSettlement.id).where(ShipperSettlement.is_deleted.is_(False))


def settled_line_map(
    db: Session, order_product_ids: list[int], *, lock: bool = False
) -> dict[int, Decimal]:
    """这几行**各自已经核销了多少**（一次查询，与行数无关）。

    `lock=True` = **核销时要用的那一档**：查询变成加锁读（MySQL 上 `SELECT … FOR UPDATE`），
    读的是**最新已提交**的值而不是本事务开始那一刻的快照。为什么非这样不可：
    REPEATABLE READ 下两个并发核销各自读到"还可核销 100"，就都能通过上限校验，
    结果收了两倍的钱（**这正是本项目最贵的一类错**，`order_money.money_map` 与
    `accounting_service.create_receipt` 都是同一个手法）。

    ⚠️ SQLite 不支持行锁，SQLAlchemy 会**忽略**它（本地开发与测试行为不变）——
        所以调用方**不能只靠它**：写完之后还要再算一次（见 [over_settled_lines]）。
    """
    ids = [int(i) for i in order_product_ids if i]
    if not ids:
        return {}
    stmt = (
        select(
            ShipperSettlementLine.order_product_id,
            ShipperSettlementLine.amount,
        )
        .where(ShipperSettlementLine.order_product_id.in_(ids))
        .where(ShipperSettlementLine.settlement_id.in_(_alive_settlement_ids(db)))
    )
    if lock:
        stmt = stmt.with_for_update()
    rows = db.execute(stmt).all()
    out: dict[int, Decimal] = {}
    for opid, amount in rows:
        key = int(opid)
        out[key] = q2(out.get(key, ZERO) + Decimal(amount or 0))
    return out


def line_remaining(op: OrderProduct, settled: Decimal) -> Decimal:
    """这一行**现在还能核销多少**（= 行应收 − 已核销；不会小于 0）。"""
    left = q2(line_receivable(op) - Decimal(settled or 0))
    return left if left > ZERO else ZERO


def remaining_of_lines(order: Order, settled_lines: dict[int, Decimal]) -> list[tuple[OrderProduct, Decimal]]:
    """订单的每一行 + 它还可核销多少（顺序与 `order.order_products` 一致）。"""
    out: list[tuple[OrderProduct, Decimal]] = []
    for op in order.order_products:
        out.append((op, line_remaining(op, settled_lines.get(op.id, ZERO))))
    return out


def lines_of_order(db: Session, order: Order, *, lock: bool = False) -> list[tuple[OrderProduct, Decimal]]:
    """订单各行 + 各行还可核销多少（**界面与提交共用这一份**）。"""
    settled = settled_line_map(db, [op.id for op in order.order_products], lock=lock)
    return remaining_of_lines(order, settled)


@dataclass(frozen=True)
class CeilingBreach:
    """某一行**被记超了**（记的比它该收的多）。

    这是"同一笔钱被记两遍"的唯一判据形态：只要有这么一行，下游那本账就多了一笔钱，
    而**两个数都不报错**（行上"还可核销"被夹成 0、汇总的"待收"变成负数）。
    """

    op: OrderProduct
    #: 这一行现在该收多少（`line_receivable`：行金额 − 已退）
    receivable: Decimal
    #: 算上"马上要记的那一笔"之后，这一行一共记了多少
    settled: Decimal
    #: 超了多少（> 0 才是一个 breach）
    over: Decimal
    #: 本次想记的那一笔在这一行上是多少（0 = 与本次无关，是历史遗留的超额）
    wanted: Decimal

    @property
    def name(self) -> str:
        return self.op.product_name_snapshot or "（未命名商品）"


def over_settled_lines(
    db: Session, order: Order, *, extra: dict[int, Decimal] | None = None, lock: bool = False
) -> list[CeilingBreach]:
    """算上 `extra` 之后，这一单**哪些行被记超了**（空 = 没超）。

    `extra` = **还没写进库**的那些金额（按 `order_product_id` 汇总）。两个场景用它：

    · **恢复一笔撤销过的核销**（`POST /settlements/{id}/restore`）：那几行此刻还不算活着，
      所以要先把它们当作"要记进来"算一遍 —— 撤销之后他又重新收过的话，放回来就会超；
    · **写完之后再算一次**（不传 `extra`，因为新行已经 flush 进本事务了）：这是不依赖行锁的
      那道防线（SQLite 上 `FOR UPDATE` 会被忽略；将来若有别的写入口忘了先加锁，这里也拦得住）。
    """
    ops = list(order.order_products)
    settled = settled_line_map(db, [op.id for op in ops], lock=lock)
    add = extra or {}
    out: list[CeilingBreach] = []
    for op in ops:
        want = q2(Decimal(add.get(op.id, ZERO) or 0))
        got = q2(settled.get(op.id, ZERO) + want)
        recv = line_receivable(op)
        if got > recv:
            out.append(
                CeilingBreach(
                    op=op, receivable=recv, settled=got, over=q2(got - recv), wanted=want
                )
            )
    return out


def settle_blocker(order: Order) -> str | None:
    """**现在能不能核销这一单**；不能就返回一句能照着做的中文（能则 None）。

    三道门，都是"这笔钱现在还不该存在"的情形：
    · 单子还没送达 / 已撤销：货没到客户手上，他还没向客户收钱；
    · 单子已整单退货：应收被红冲冲平了（`line_receivable` = 0），没得收；
    · 单子已软删（在回收站里）：它连自己的列表都进不去，别在它上面记账。
    """
    if order.deleted_at is not None:
        return "这张单在回收站里（已删除），先恢复它再核销"
    if order.status in (OrderStatus.PENDING_DISPATCH, OrderStatus.DISPATCHED, OrderStatus.ACCEPTED):
        return "这张单还没送达，先别核销（送达之后才有这笔应收）"
    if order.status == OrderStatus.CANCELLED:
        return "这张单已撤销，没有应收可核销"
    if order.status == OrderStatus.RETURNED:
        return "这张单已整单退货，货款已经冲平，没有可核销的金额"
    return None
