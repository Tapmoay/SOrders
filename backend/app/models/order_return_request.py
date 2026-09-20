"""货主**申请**退货（2026-09-21 用户要求）。

## 用户口径（口述原话）

「批发商……他要进行退货，他**可以直接在订单上**作退货。然后我们的那个派单员，他会接到一个**通知**，
这个时候派单员就会去帮他进行一个退货的操作。**派单员进行完了之后，整个才进行库存才会发生一个改变和变动**。
也就是说**批发商只是一个申请，派单员才是实际性的操作**。」

## ⛔ 这张表**什么都不改**——这是它存在的全部理由

申请只往这张表里写一行 + 几行明细。它**不碰**：

| 不碰 | 为什么（这一轮的核心约束） |
| --- | --- |
| `ledgers`（退货红冲） | 红冲是"生意改了一部分"，只有**真的把货收回来**了才成立 |
| `inventory_movements`（库存回补） | 用户原话：「派单员进行完了之后，整个才进行库存才会发生一个改变和变动」——申请阶段货还在客户手里 |
| `order_products.returned_quantity` | 同上：那是"已经退了几件"的事实，不是"想退几件" |
| `orders.status` | 一张还在申请中的单**仍然是「已送达」**（它确实送到了）；变成「已退货」只能由退货那一刻决定 |
| `cash_flows`（退现） | 钱只能跟着实际操作走 |

**为什么这条要写在这里**：把"申请"做成"直接退货"是很自然的偷懒（复用同一个弹窗、少一个状态机），
后果是货主按一下就改了自己的应收和公司库存，而派单员**根本不知道**——
`core/rbac.py` 当初不给货主退货权，理由正是「让他按一下就把自己的应收改掉，这份账就没有第二个人核对了」。
申请制保留了那份核对，所以申请权和执行权可以分开给。

## 与「谁来做」的分工

· **货主**（含批发商，`orders.shipper_id == 申请人`）：提交申请 / 撤回申请 / 看结果；
· **派单员**：收到站内信 → 对着这张申请**实际执行退货**（走 `services/order_return.py` 那条唯一路径）
  或**驳回**（必带理由）。
· 数量**锁死**（2026-09-21 用户拍板）：申请多少就退多少，派单员不能改数量 ——
  要改就得驳回，让货主重新提。理由：数量一改，"他申请的是 5 件、账上退了 3 件"就成了两边各说各话，
  而这条流程的产出物就是"谁申请了什么、最后办成了什么"。

## 删除

走 `SoftDeleteMixin`（用户定的硬规矩：删除一律软删 + 有恢复路径）。
明细行（[OrderReturnRequestLine]）**自己不设标记** —— 跟着父记录走
（与 `ShipperSettlementLine` 同一条理由：父被删 = 这张申请整体不存在，
不会出现"父还在、某几行却被单独删掉"的中间态）。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class OrderReturnRequest(Base, TimestampMixin, SoftDeleteMixin):
    """一张退货申请单：某个货主对某张**已送达**订单提出的退货请求。"""

    __tablename__ = "order_return_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    #: 申请人 = 登录的货主本人（`orders.shipper_id`）。
    #: ⚠️ 代理下单给**临时货主**的单（`orders.shipper_id is None`）没有账号可以登录，
    #:    所以申请不了 —— 那种单本来就是派单员代下的，退货也由他直接办。
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: 见 `ReturnRequestStatus`。存字符串而不是 MySQL 原生枚举：
    #: 原生枚举每加一档都要动迁移（`orders.status` 已经栽过一次：本机 SQLite 一路正常、
    #: 生产一按就 500），而这个字段的取值将来大概率还会长。
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    #: 申请备注（货主写的话：「这几件破了」「客户不要了」）。会显示在派单员的办理界面上。
    note: Mapped[str] = mapped_column(String(256), default="")
    #: 驳回理由（派单员必填）。⛔ 与 `note` 分开两列而不是共用一列：
    #: 出错时第一个要问的是"这话是谁说的"。
    reject_reason: Mapped[str] = mapped_column(String(256), default="")
    #: 谁办的 / 谁驳的（`DONE` 与 `REJECTED` 共用这两列 —— 都是"派单员做了决定"）。
    handled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 留痕：这张申请是从哪个端进来的（app=人工点、ai=AI 助手确认卡）。
    #: 与 `shipper_settlements.source` 同一套词，报表/审计按它区分人机。
    source: Mapped[str] = mapped_column(String(16), default="app")

    lines: Mapped[list["OrderReturnRequestLine"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class OrderReturnRequestLine(Base, TimestampMixin):
    """这张申请要退哪几行、每行几件（**数量锁死**的那份原始诉求）。"""

    __tablename__ = "order_return_request_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("order_return_requests.id"), index=True)
    order_product_id: Mapped[int] = mapped_column(ForeignKey("order_products.id"), index=True)
    #: 商品名快照：订单商品行**没有软删**（改单是物理增删），订单行可能真的消失；
    #: 而"他当时申请退的是哪样货"事后必须还能读出来（与 `ShipperSettlementLine` 同一条理由）。
    product_name: Mapped[str] = mapped_column(String(256), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)

    request: Mapped[OrderReturnRequest] = relationship(back_populates="lines")
