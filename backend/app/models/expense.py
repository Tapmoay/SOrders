"""开销单：加油/维修/过路/停车/罚款/保险/货损/其他（**分类可维护**，见 `expense_category.py`），
保存后自动生成资金流水。"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Expense(Base, TimestampMixin):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exp_date: Mapped[date] = mapped_column(Date, index=True)
    # 分类**不再是一个枚举**（2026-09-20）：它是可维护名册（`expense_categories`）里的一个名字，
    # 所以这里存自由字符串、宽度与名册一致（32）。
    # ⚠️ 原来写的是 `String(16)` + 注解 `Mapped[ExpenseCategory]`：那种列存的是**枚举值**，
    #    写一个名册里的新分类会 500（`ExpenseOut` 校验不过），而写库那一刻一声不响。
    category: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    driver_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    vehicle_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    order_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
