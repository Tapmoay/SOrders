from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.inventory import InventoryMovement
    from app.models.order import OrderProduct
    from app.models.user import User


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), index=True)
    name_color: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    default_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    # 成本价：报表计算毛利率用（售价 - 成本）
    cost_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    # 当前库存（只由库存流水增减，不走商品编辑接口）
    stock: Mapped[int] = mapped_column(Integer, default=0)
    # ⛔ 已废弃（2026-09-19 用户拍板删掉「批发价档位」这个概念）：原来存的是多档批发价
    #    （形如 [{"label": "批发价一", "unit_price": "12.0000"}, ...]）。
    #    废弃的原因：它**看起来像批发价，下单时却一个字节都不照它走** —— 下单只认
    #    `price_rules` 的按（批发商×商品）专属价，没有专属价才用 `default_unit_price`。
    #    这种"看着像价、其实谁都不按它成交"的概念正是用户说的「操作与逻辑不匹配」。
    #    ⚠️ **列与历史数据一律保留，不写迁移、不清数据、也不 drop**：它此前只在两处当过
    #    "预设值"（`POST /price-rules/batch` 的 `mode="tier"`、App 批发商定价页的下拉），
    #    那两处已删，所以这列**不再被任何接口读写**（schema_bootstrap 补列的那段也保留，
    #    老库缺列时会报错）。留着只为不丢数据 —— **不是漏了迁移**。
    #    ⚠️ 别按它写新逻辑：要"这个批发商的这个商品多少钱"就查 `price_rules`。
    tier_prices: Mapped[list] = mapped_column(JSON, default=list)
    # 商品单位（如 件/箱/斤/桶），下单与库存均展示
    unit: Mapped[str] = mapped_column(String(32), default="件")
    # 商品分类（如 饮料/粮油/日化）：选品页左侧导航按它分组。
    # ⚠️ 空串 = 「未分类」，不是错误：老数据全部落在这一档，选品页会把它归到「未分类」组，
    #    并且**全部商品都没有分类时左侧只显示「全部」**（不逼用户先补分类才能下单）。
    category: Mapped[str] = mapped_column(String(32), default="", index=True)
    # 库存报警阈值：库存 <= 该值视为低库存（0=不报警）
    low_stock_alert: Mapped[int] = mapped_column(Integer, default=0)
    # 软删除：删除 = 打标记（可 restore），不再物理删除。
    # ⚠️ 为什么必须软删（v3.26 修）：物理删除时 `inventory_movements` 会被
    #    `cascade="all, delete-orphan"` **整批删掉**（而订单行/账本只是解除外键），
    #    也就是"同一个商品的三种历史，两种留、一种抹"。软删之后一张流水都不会掉，
    #    而且用户发现删错了还能恢复——「删了就搞不回来」正是要消灭的那种后果。
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    price_rules: Mapped[list["PriceRule"]] = relationship(back_populates="product")
    order_products: Mapped[list["OrderProduct"]] = relationship(back_populates="product")
    # ⛔ 不再 cascade 删除：流水是业务历史，商品软删后它必须原样留着（见 is_deleted 注释）。
    inventory_movements: Mapped[list["InventoryMovement"]] = relationship(back_populates="product")


class PriceRule(Base, TimestampMixin, SoftDeleteMixin):
    """货主特殊定价：货主 + 商品 + 特殊单价。

    ⚠️ 这张表有 (shipper_id, product_id) 唯一约束，所以**删掉的行仍然占着那个组合**
    （不能像联系人那样把键改名——改了就对不上哪对货主×商品了）。
    因此再设一次同样的价必须**复活那一行**而不是插一条新的：
    见 price_rules.py 的 upsert，它查已有行时**不过滤 is_deleted**。
    """

    __tablename__ = "price_rules"
    __table_args__ = (UniqueConstraint("shipper_id", "product_id", name="uq_price_rule_shipper_product"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    special_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))

    shipper: Mapped["User"] = relationship(foreign_keys=[shipper_id])
    product: Mapped["Product"] = relationship(back_populates="price_rules")
