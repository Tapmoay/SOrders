from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import OrderStatus

if TYPE_CHECKING:
    from app.models.operation_log import OperationLog
    from app.models.product import Product
    from app.models.user import User


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    #: 报表/导出那一族查询的索引：它们全是
    #: `status='DELIVERED' AND deleted_at IS NULL AND delivered_at ∈ [窗口)`。
    #: ⚠️ 为什么必须有（2026-09-23 第 9 轮，**在生产 MySQL 上用 EXPLAIN ANALYZE 实测**）：
    #: 没有它时优化器走 `Table scan on o`（读全表 2402 行），而 `delivered_at` 上的窗口
    #: **一点都没少读** —— 也就是说第 3 轮那个"窗口预过滤"只减少了**内存里的行**，
    #: 从库里读出来的行数没变；代价随 3 年保留策略线性增长（正是第 3 轮要治的病）。
    #: 与之对照：待派池那条查询走了 `ix_orders_status_created`、账本那条走了
    #: `ix_ledgers_entry_date` 的 covering index —— 只有报表这一族缺索引。
    #: 老库由 `core/schema_bootstrap.py` 补（SQLite 新库由 create_all 直接建出来）。
    __table_args__ = (
        Index("ix_orders_status_delivered", "status", "delivered_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), index=True)

    shipper_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    # 派单员代下单：无系统货主账号时的展示名，仅用于订单/账本关联，不登录
    temp_shipper_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)

    order_date: Mapped[date] = mapped_column(Date, index=True)

    delivery_description: Mapped[str] = mapped_column(String(512), default="")
    address_detail: Mapped[str] = mapped_column(String(512), default="")
    address_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    address_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    # 导航信息的**来源**：driver=司机到场补录，dispatcher=派单员补录；空=下单时就带坐标。
    # 为什么要存：货主看到的 "司机帮你补上了导航信息" 必须是真的（不能靠猜），
    # 而且补录这件事会写进共享地点库——出了问题要能顺着这一列查回是谁在哪一单上标的。
    nav_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 收货地址参考图（定位不清时上传辅助）：address_image_url 兼容首图；image_urls 全量（JSON 数组）
    address_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)
    image_urls: Mapped[str] = mapped_column(Text, default="[]")

    contact_dongjia_phone: Mapped[str] = mapped_column(String(32), default="")
    contact_boss_phone: Mapped[str] = mapped_column(String(32), default="")
    # 两个联系人的**名称**（2026-09-20 用户要求：「加收货人的名称和下单人的名称……卡片与详情都显示」）。
    # 口径与上面两个电话**一一对应**：dongjia=**收货人**（到现场接货的人）、boss=**下单人**
    # （下这一单的人：货主账号本人，或代下单的派单员）。
    # 为什么名称要单独存而不是每次去 join：收货人可能是没有账号的人（地址库里的 receiver_name），
    # 下单人的姓名也可能事后被改 —— 已下的单要留住**当时**那个名字（与 `contact_*_phone`
    # 同一个道理：这几列都是这一单的联系信息快照）。
    contact_dongjia_name: Mapped[str] = mapped_column(String(64), default="")
    contact_boss_name: Mapped[str] = mapped_column(String(64), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    driver_remark: Mapped[str] = mapped_column(Text, default="")
    # 司机运费（由派单员指定，与货主货款无关）；空=未定价（司机端显示"运费待定"）
    freight_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    #: 这一单属于**哪一类货**（运费分类名册编号）。派单时由匹配出来的那条价目带过来，
    #: 也可以由派单员手动定价时指定。它决定：① 用哪条价目（路线+分类+司机）；
    #: ② 司机计费规则在 `piece_mode=category` 时按哪一档给钱。
    #: ⚠️ 没匹配到价目时它是 NULL —— 那就是"运费待定价"（**不标异常**，用户 2026-09-21 定的）。
    freight_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("freight_categories.id"), nullable=True, index=True
    )
    #: 分类名的**快照**（分类改名/删掉之后，历史单仍然看得懂"当时按哪一类算的"）。
    #: 与 `driver_rule_snapshot` 同一个道理：历史单据要能独立复核。
    freight_category: Mapped[str] = mapped_column(String(32), default="")
    # 派单时司机计费方式快照：司机换类型后历史订单可见性仍按快照
    driver_billing_mode_snapshot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 派单时挂着的**计费规则**快照（JSON）：规则后来被改了/换了，已送完的单金额不能跟着变。
    # 空 = 这单没挂规则，按老口径算（计件=全额运费）。
    driver_rule_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 派单员对**这一单**单独定的数（空=用规则里的）：
    # 用户 2026-09-18：「每单有多少钱，但每单是不固定的，几百块、几十块，由派单员决定」。
    driver_piece_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # 「提成又是另外一回事，可能设置这一单、或者这一类单」→ 比例也能逐单给。
    driver_commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    # 派单时勾选「收取现金」：司机完成订单时可选择现场收现金或挂账；未勾选则送达自动挂账
    collect_cash: Mapped[bool] = mapped_column(Boolean, default=False)
    # 司机送达时录入的货损备注（选填）
    damage_note: Mapped[str] = mapped_column(Text, default="")
    # 拆分子订单：指向原（父）订单；空=普通订单
    parent_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True
    )

    delivery_photo_urls: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    # 软删除隔离时间：用户删除后 30 天内隔离（用户不可见），派单员可恢复；到期后物理清理
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    driver_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="撤销时间；用于已撤销订单保留期限与自动清理"
    )
    # 最后一次退货的时间（2026-09-20）：整单退完时与 status=RETURNED 一起写。
    # 留着它是为了回答"这单什么时候退的"——账本红冲行的 entry_date 只有一个日期，
    # 而退货是**可能分几次**发生的（部分退货），最后一次才是"这单结束"的时刻。
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_deliver_before: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="约定送达时间（用于准时率；空则按订单日末）"
    )
    is_exception: Mapped[bool] = mapped_column(default=False, index=True)
    exception_reason: Mapped[str] = mapped_column(Text, default="")
    exception_resolution: Mapped[str] = mapped_column(Text, default="")
    # 异常解决时间（派单员处理后非空=已解决）
    exception_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 支付：cash=现场支付（货到付款），arrears=挂账（记到挂账单位名下）
    payment_method: Mapped[str] = mapped_column(String(16), default="cash")
    paid: Mapped[bool] = mapped_column(default=False)
    arrears_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("arrears_units.id"), nullable=True
    )
    arrears_unit_name: Mapped[str] = mapped_column(String(128), default="")

    shipper: Mapped["User"] = relationship(
        back_populates="orders_as_shipper", foreign_keys=[shipper_id]
    )
    driver: Mapped["User | None"] = relationship(
        back_populates="orders_as_driver", foreign_keys=[driver_id]
    )
    order_products: Mapped[list["OrderProduct"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    operation_logs: Mapped[list["OperationLog"]] = relationship(back_populates="order")


class OrderProduct(Base, TimestampMixin):
    __tablename__ = "order_products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    product_name_snapshot: Mapped[str] = mapped_column(String(256))
    quantity: Mapped[int] = mapped_column(default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    # 下单时这一行的单位快照（件/箱/斤…）。空串 = 老数据 → 出参回退商品单位。
    # ⚠️ 用户在选品弹窗里能**改单位**（"数量后面是要有对应的单位的"），
    #    所以它必须跟着行存下来：不存的话界面上选了「3 箱」、订单和送货单上还是「3 件」。
    #    它**不参与任何金额计算**（钱只认 quantity × unit_price），改动它不动账。
    unit_snapshot: Mapped[str] = mapped_column(String(32), default="")
    # 商品成本快照（报表毛利率/利润用；货运损金额=该快照×货损数量）
    cost_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    # 司机送达时录入的货损数量（≤quantity；0=无货损）
    damage_quantity: Mapped[int] = mapped_column(default=0)
    # **已退货数量**（2026-09-20）：客户把货退回来了几件。
    #
    # 为什么记在**行**上而不是只在订单上打一个「已退货」标记：用户明确要求
    # 「可以整单退货，也可以只退其中的某几个商品或者一个商品，他自己勾选」——
    # 只有行级数量才能同时表达"整单退完"（每行 returned == quantity）与"部分退货"，
    # 也才能让退货红冲行**按行**写、库存**按行**回补。
    # 判据：`0 <= returned_quantity <= quantity`（红线 `_check_order_return.py`）。
    returned_quantity: Mapped[int] = mapped_column(default=0)

    order: Mapped["Order"] = relationship(back_populates="order_products")
    product: Mapped["Product | None"] = relationship(back_populates="order_products")
