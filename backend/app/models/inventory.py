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

    product: Mapped["Product"] = relationship(back_populates="inventory_movements")
