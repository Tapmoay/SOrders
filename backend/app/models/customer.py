"""客户主数据：registered（注册用户/代理商）与 tmp（散客，电话为唯一键）。"""

from sqlalchemy import Boolean, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import CustomerKind


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        Index(
            "uq_customers_tmp_phone",
            "phone",
            unique=True,
            sqlite_where=text("kind='tmp' AND phone IS NOT NULL"),
        ),
        Index("uq_customers_registered", "user_id", unique=True, sqlite_where=text("kind='registered'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[CustomerKind] = mapped_column(String(12), default=CustomerKind.TMP, index=True)
    user_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_member: Mapped[bool] = mapped_column(Boolean, default=False)
    arrears_unit_id: Mapped[int | None] = mapped_column(nullable=True)
