from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import OrderStatus

if TYPE_CHECKING:
    from app.models.operation_log import OperationLog
    from app.models.product import Product
    from app.models.user import User


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

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
    # 收货地址参考图（定位不清时上传辅助）
    address_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True, default=None)

    contact_dongjia_phone: Mapped[str] = mapped_column(String(32), default="")
    contact_boss_phone: Mapped[str] = mapped_column(String(32), default="")
    remark: Mapped[str] = mapped_column(Text, default="")
    internal_notes: Mapped[str] = mapped_column(Text, default="")
    driver_remark: Mapped[str] = mapped_column(Text, default="")
    # 司机运费（由派单员指定，与货主货款无关）；空=未定价（司机端显示"运费待定"）
    freight_fee: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # 派单时司机计费方式快照：司机换类型后历史订单可见性仍按快照
    driver_billing_mode_snapshot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 派单时勾选「收取现金」：司机完成订单时可选择现场收现金或挂账；未勾选则送达自动挂账
    collect_cash: Mapped[bool] = mapped_column(Boolean, default=False)
    # 拆分子订单：指向原（父）订单；空=普通订单
    parent_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True, index=True
    )

    delivery_photo_urls: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)

    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    driver_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, doc="撤销时间；用于已撤销订单保留期限与自动清理"
    )
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

    order: Mapped["Order"] = relationship(back_populates="order_products")
    product: Mapped["Product | None"] = relationship(back_populates="order_products")
