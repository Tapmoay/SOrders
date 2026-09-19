"""库存流水：商品出入库记录；商品当前库存冗余在 Product.stock。"""

from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class InventoryMovement(Base, TimestampMixin):
    __tablename__ = "inventory_movements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    # 正数入库 / 负数出库
    change: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(256), default="")
    operator_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # 来源：MANUAL=手工出入库 / ORDER=订单自动
    source: Mapped[str] = mapped_column(String(20), default="MANUAL")
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True, default=None)
    # ORDER 行状态：RESERVED=派送预占 / COMMITTED=送达实扣 / RELEASED=撤销回冲；MANUAL 行=COMMITTED
    status: Mapped[str] = mapped_column(String(20), default="COMMITTED")
    # **这批货的进货单价**（只有手工入库且填了才有值；订单自动流水与出库都是 NULL）。
    #
    # ⛔ 这一列以前**不存在**：入库时填的进货价只被拿去改 `products.cost_price`，
    #    流水上什么都没留下 —— 于是"按入库记录算平均成本"根本无从下手，
    #    毛利只能用"最新一次进货价"当成本，进货价一涨，旧库存的毛利就偏低。
    #    现在毛利按这一列算加权平均进货价（`services/cost_basis.py` 是唯一实现）。
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), default=None)

    product: Mapped["Product"] = relationship(back_populates="inventory_movements")
    order: Mapped["Order | None"] = relationship()

    @property
    def order_no(self) -> str | None:
        return self.order.order_no if self.order is not None else None
