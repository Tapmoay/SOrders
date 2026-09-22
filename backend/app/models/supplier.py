"""供应商 / 厂商档案 + 应付单（2026-09-22 用户要求）。

用户原话：「支出主要是**给某个供应商或者说是厂商支付尾款**……**购买一个装备或者说是设备**……
比如说类似**邮费**啊」；拍板的口径是**跟客户一个量级的档案**：**可挂账、可查还欠多少、可分次付款**。

## 两张表，不是三张 —— 付款**不在这两张表里**
`Supplier`（档案）与 `SupplierPayable`（应付单：欠了人家多少钱）。
**付款＝`cash_flows` 的一行**（`direction=out` / `biz_type=PAYMENT_SUPPLIER` /
`party_type='supplier'` / `party_id=供应商` / `doc_id=应付单`）：

- `cash_flows` 的模型 docstring 写着它是「所有实际收付（…）的**唯一写入点**」。付款再造一张表，
  就是"同一笔钱在两个地方各记一份"，两边一旦不一致（漏写、删了一边）**谁都不会报错**；
- 而且这样**收支页天生就有它**（那一页按 `biz_type` 分组求和），视图层不需要再 union 一次；
- 「分次付款」＝同一张应付单下面多行流水，本来就是这个形状，不需要额外的"付款单"。

## 欠款只有一个口径
`欠款 = Σ(alive 应付单金额) − Σ(alive 付款流水)`，实现在 `services/supplier_service.py`
**一处**。⛔ 端点里不许各写一遍 SUM（本项目最贵的一类错是"同一个数在两处算，只有一个地方改了"）。

## 名字唯一 + 软删要释放
`suppliers.name` 上建**普通唯一索引**（两库语义一致，不用 `sqlite_where` —— 那个参数
MySQL 会**静默忽略**，见 `models/customer.py` 里那段踩坑记录）：重复档案会把同一个供应商的
欠款拆成两半，而两边都不报错。删除是软删（用户定死的硬规矩），所以删除时要把 `name`
改成 `name_del{id}` **把名字释放出来**（`services/soft_delete.py::del_suffix`），
否则"删掉再建同名"会直接撞唯一索引（500）。
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Supplier(Base, TimestampMixin, SoftDeleteMixin):
    """供应商 / 厂商档案（用户说的"供应商或者说是厂商"是同一件事，不开两个名册）。"""

    __tablename__ = "suppliers"
    __table_args__ = (Index("uq_suppliers_name", "name", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 名称就是它的"编号"（找供应商按名字找），所以唯一。宽度 64：够写
    #: 「惠州仲恺永盛食品有限公司」这一级的全称。
    name: Mapped[str] = mapped_column(String(64), index=True)
    #: 联系人 / 电话 / 地址：**都是纯展示**，不参与任何计算（电话不校验成手机号 ——
    #: 供应商给的多半是座机，校验成 11 位手机反而把真实号码挡在外面）。
    contact_name: Mapped[str] = mapped_column(String(32), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    address: Mapped[str] = mapped_column(String(128), default="")
    remark: Mapped[str] = mapped_column(String(256), default="")
    operator_id: Mapped[int | None] = mapped_column(nullable=True)


class SupplierPayable(Base, TimestampMixin, SoftDeleteMixin):
    """应付单：**欠这个供应商的一笔钱**（还没付、或只付了一部分）。"""

    __tablename__ = "supplier_payables"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(index=True)
    #: 这笔应付是什么（「永盛食品 10 月货款」「采购叉车」）—— 对账时全靠它。
    title: Mapped[str] = mapped_column(String(64))
    #: 用途分类（货款 / 设备采购 / 运费 / 尾款 / 其他）。**自由字符串，不是枚举** ——
    #: 与 `expenses.category` 同一个理由（2026-09-20 那次教训）：写死成枚举之后，
    #: 用户新加一个分类会在**写库那一刻**一声不响地存不进去。
    category: Mapped[str] = mapped_column(String(32), default="货款", index=True)
    #: 应付**总额**。已付**不存在这里**（见文件头：已付从流水算，只有一处口径）。
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    #: 单据日期（这笔欠款从哪天算）——与付款日期是两件事。
    doc_date: Mapped[date] = mapped_column(Date, index=True)
    remark: Mapped[str] = mapped_column(String(256), default="")
    operator_id: Mapped[int | None] = mapped_column(nullable=True)
