from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class ShipperAddress(Base, TimestampMixin, SoftDeleteMixin):
    """常用线路：联系人 + 地点（起点可选 + 终点必填）"""

    __tablename__ = "shipper_addresses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    receiver_name: Mapped[str] = mapped_column(String(128), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    detail_address: Mapped[str] = mapped_column(String(512), default="")
    remark: Mapped[str] = mapped_column(String(256), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    address_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    address_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    # 线路起点（可选）
    origin_address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    origin_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    origin_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 多张图片（JSON 数组，如 ["/static/...", ...]）；image_url 保留兼容（= 首图）
    image_urls: Mapped[str] = mapped_column(Text, default="[]")

    shipper: Mapped["User"] = relationship(back_populates="addresses")


class ShipperContact(Base, TimestampMixin, SoftDeleteMixin):
    """常用联系人（与地点解耦，可编辑）"""

    __tablename__ = "shipper_contacts"
    __table_args__ = (UniqueConstraint("shipper_id", "phone", name="uq_shipper_contact_phone"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")

    shipper: Mapped["User"] = relationship(back_populates="contacts")


class ShipperLocation(Base, TimestampMixin, SoftDeleteMixin):
    """单独地点（纯地点，不含人）：支持图片，派单/下单时组合起点与终点"""

    __tablename__ = "shipper_locations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    detail_address: Mapped[str] = mapped_column(String(512), default="")
    remark: Mapped[str] = mapped_column(String(256), default="")
    address_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    address_lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # 多张图片（JSON 数组）；image_url 保留兼容（= 首图）
    image_urls: Mapped[str] = mapped_column(Text, default="[]")
    #: 自定义分类（用户 2026-09-19：「地点库的分类…他们都可以自行的添加分类，也可以进行分类的
    #  管理」）。自由文本 + 一张按人分区的名册表（`PlaceCategory`）管顺序，与商品分类同一套做法。
    #  空串 = 未分类。
    category: Mapped[str] = mapped_column(String(32), default="", index=True)
    #: 这个地点是**仓库**（用户 2026-09-19：「给派单员有一个选择可以选择一个地点作为仓库，
    #  不一定只能选一个，可以选好多个」）。送到仓库的单按"货进来了"处理（自动入库，
    #  见 `services/warehouse.py`）。**只有派单员能改**（`api/v1/shipper.py` 里判）。
    is_warehouse: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    #: 这个地点默认的联系人（收货人）——
    #: 用户 2026-09-24：「同时再给他添加个功能就是**可以通过地点来绑定联系人**，
    #: 就大家选择地点之后，自动填入对应的联系人」。
    #:
    #: ⛔ **与线路（[ShipperAddress].receiver_name / phone）同一口径：存快照串、不存外键**。
    #: 两件事别混：名册（[ShipperContact]）回答的是"我认识哪些人"，这里回答的是
    #: "送到这个地点通常谁收货"。挂外键的后果是名册里删掉一个人（或改个名），
    #: 某个地点的收货人就跟着消失/改名 —— 而那一单要照着这个人打电话。
    #: 线路那边存的就是串，两处必须同形，否则下单页带出联系人的那一段要分两套写法。
    #:
    #: ⚠️ 只有「我的地点」（本表）能绑人；**共享地点库（`places`）不绑** —— 那张表全库共用
    #:    （司机补录的坐标大家都能选），绑一个人的电话等于给所有人都换了默认收货人。
    contact_name: Mapped[str] = mapped_column(String(128), default="")
    contact_phone: Mapped[str] = mapped_column(String(32), default="")

    shipper: Mapped["User"] = relationship()
