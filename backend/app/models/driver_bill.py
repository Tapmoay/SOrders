"""司机应付明细：PIECE（按单计费）与 SALARY（按月薪）统一表，按月归属。"""

from decimal import Decimal

from sqlalchemy import Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import DriverBillStatus, DriverBillType


class DriverBill(Base, TimestampMixin):
    __tablename__ = "driver_bills"
    #: 同一张单的同一类应付**只能有一条**（2026-09-18 补的数据库级闸）。
    #:
    #: 为什么不能只靠代码里的"先查再插"：送达生成账单原来是"读-判断-写"，
    #: 两个并发请求各自读到"还没有账单"，于是同一张单生成两条（本机实测复现，
    #: 见 `tests/test_concurrent_delivery_money.py`）。v3.40 给状态跃迁加了条件 UPDATE
    #: 占位，把这一条路径的并发挡住了；但补单接口、脚本、以后新写的批处理都可能再插一次。
    #:
    #: ⚠️ 只对 `order_id` 非空的行生效（月薪单不绑单，`order_id` 为 NULL）：
    #: 标准 SQL 里 NULL 不参与唯一性比较，所以多行 `(NULL,'salary')` 不会被误拦。
    #: 月薪单的幂等仍由代码里的"同司机同月只生成一次"负责（那是业务规则，不是数据完整性）。
    __table_args__ = (
        Index("uq_driver_bills_order_type", "order_id", "bill_type", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    driver_id: Mapped[int] = mapped_column(index=True)
    bill_type: Mapped[DriverBillType] = mapped_column(String(8), index=True)
    order_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    month: Mapped[str] = mapped_column(String(7), index=True)  # YYYY-MM
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[DriverBillStatus] = mapped_column(String(12), default=DriverBillStatus.OPEN, index=True)
    settled_doc_id: Mapped[int | None] = mapped_column(nullable=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    # 这一单是按哪份计费规则算出来的（v3.36）。只留 4 个字段而不是整份快照：
    # 规则本身可能被改，账单要能**独立**说清"当时按什么算的、每件多少钱"，
    # 否则月底对账时只能看到一句"合计 120"，没人能复核。
    rule_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    rule_name: Mapped[str] = mapped_column(String(128), default="")
    piece_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    commission_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
