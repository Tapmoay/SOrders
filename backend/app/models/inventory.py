"""库存流水：商品出入库记录；商品当前库存冗余在 Product.stock。"""

from sqlalchemy import ForeignKey, Integer, String
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

    product: Mapped["Product"] = relationship(back_populates="inventory_movements")
    order: Mapped["Order | None"] = relationship()

    @property
    def order_no(self) -> str | None:
        return self.order.order_no if self.order is not None else None
