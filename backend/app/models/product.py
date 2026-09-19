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


class ProductCostHistory(Base, TimestampMixin):
    """商品成本价的**生效区间**（用户 2026-09-19 要求）。

    ## 用户原话
    > 「那个成本价去做一个保留…这个保留是跟着他的账本走的。假如他的账本是一直保留着，
    >   那他这个成本价就一直保留着。如果成本价发生了变化，就直接变化成本价就可以了，
    >   这样子我们就好溯源。而且我们保留的时候不仅保留成本价，还保留这个成本价存在的时间，
    >   比如说他是从什么时候开始变的、从什么时候结束的，**精确到小时和分钟**，
    >   这样子的话，我们就能方便且精确地算出来在这段时间的毛利率是多少。」

    ## 语义：一个商品的多行 = 一条时间轴（不是"改动日志"）
    每行是**一段区间**：
      · `effective_to IS NULL` 的那一行 = **当前生效价**
      · 改价 = 给旧行补上 `effective_to`，再插一行 `effective_from=这一刻`
      · "某个时刻的价" = `effective_from <= t AND (effective_to IS NULL OR effective_to > t)`

    ⚠️ **为什么用区间而不是"旧价→新价"的事件日志**：用户要的是"**在这段时间的**毛利率"
    —— 那需要按**任意时刻**取价。事件日志要从头累一遍，区间表一次比较就定位；
    而且区间表能一眼看出"这个价用了多久"，事件日志看不出来。
    代价是每次改价写两行（旧行补尾巴 + 插新行），两行在**同一事务**里做，不会留空洞。

    ⚠️ **"恰好一行当前价"由应用层保证**，不靠数据库：MySQL 不支持带 `WHERE` 的过滤唯一索引，
    所以做不出"每个商品只能有一行 effective_to IS NULL"这个约束。
    唯一的写入口是 `services/cost_history.py::record_cost`（红线钉着"不许别处直接改 cost_price"）。

    ## 保留期**跟着账本走**（用户明确要求）
    "账本留多久，成本价历史就留多久" → 与 `ledgers` 同一档：
    `data_retention.DATA_RETENTION_DAYS`（3 年），清理写在 `purge_expired_data` 里。

    ## 为什么还要 `source` / `movement_id` / `operator_id`
    溯源时下一个问题一定是"**这条价是怎么来的**"：是进货带进来的（那批货多少件、谁进的），
    还是有人在商品编辑里手填的。前者能连回 `inventory_movements`，后者只能连操作日志。
    """

    __tablename__ = "product_cost_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    #: 这一段区间内的单位成本（与 `products.cost_price` 同精度）
    cost_price: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    #: 从这一刻（**UTC**，与全库时间基准一致）开始生效
    effective_from: Mapped[datetime] = mapped_column(DateTime, index=True)
    #: 到这一刻为止（**半开区间**：不含这一刻）；NULL = 仍在生效中
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    #: CREATE=建商品时填的 / PURCHASE=进货带进来的 / MANUAL=编辑里改的 / BACKFILL=老数据回填
    source: Mapped[str] = mapped_column(String(16), default="MANUAL")
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, default=None)
    #: 进货带进来的那条库存流水（溯源：那批货多少件、备注是什么）。
    #  ⚠️ 这里**刻意不加外键**：保留任务物理清理老订单时会连 `inventory_movements` 一起删
    #     （`data_retention.delete_orders_by_ids`），有外键的话那样删会直接失败。
    #     今天不会被删（只有手工入库才带价，那种流水 order_id 为空），但"今天不会"不是约束。
    movement_id: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)

    product: Mapped["Product"] = relationship()


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
