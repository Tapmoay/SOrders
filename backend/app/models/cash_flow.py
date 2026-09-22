"""资金流水总账：所有实际收付（客户收款/司机付款/开销/退款/调账）的唯一写入点。

## 为什么会带软删（2026-09-22，供应商付款那一期）
用户定的硬规矩是「**所有删除一律软删（伪装删除）+ 必须有恢复路径**」。在这一期之前
`cash_flows` 是**只增不删**的：钱付出去就撤不回来（`cancel_settlement` 只允许作废**草稿**，
已付款的结算单没有任何回头路）。而「给供应商付尾款」这件事天然会录错（金额打错、付错供应商），
没有回头路就只能**再写一笔反向的钱**——那会让账上多出一对谁也不敢删的行。

所以 `cash_flows` 加了 `is_deleted` / `deleted_at`（线上迁移在
`core/schema_bootstrap.py`）：**撤销一笔付款 = 把那一行藏起来**，恢复 = 原样放回来，
钱的历史一行不丢。

⚠️ **代价与纪律**：凡是从 `cash_flows` 取数的地方**都必须带 `is_deleted.is_(False)`**，
漏一处的后果是"欠款说没付、收支说付了"（同一笔钱两个答案，而两边都不报错）。
这一条有红线钉着：`_tools/qa/_check_supplier_payables.py` **自己算出**读取处清单
（扫描 `backend/app` 里所有出现 `CashFlow` 的文件），逐处断言它带了这一句。
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.enums import CashFlowBizType, CashFlowDirection


class CashFlow(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "cash_flows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    flow_date: Mapped[date] = mapped_column(Date, index=True)
    direction: Mapped[CashFlowDirection] = mapped_column(String(3), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    party_type: Mapped[str] = mapped_column(String(8), index=True)  # customer/driver/supplier/expense/other
    party_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    party_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="cash")
    biz_type: Mapped[CashFlowBizType] = mapped_column(String(20), index=True)
    order_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    doc_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    note: Mapped[str] = mapped_column(String(256), default="")
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
