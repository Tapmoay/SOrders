"""客户主数据：registered（注册用户/代理商）与 tmp（散客，电话为唯一键）。"""

from sqlalchemy import Boolean, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import CustomerKind


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        # ⛔ 散客电话的唯一性**不许**写成 `sqlite_where=text("kind='tmp' AND phone IS NOT NULL")`
        #    （2026-09-19 外部完整检查 S2，本项目踩过的最贵的一类坑）：
        #    `sqlite_where` 是 **SQLite 专属**参数，MySQL 上被**静默忽略**，于是这条"部分唯一索引"
        #    在生产被编译成**整表唯一** —— 给一个已存在的注册货主建同号散客档案，必然撞唯一约束
        #    → 409「已经有一条一模一样的记录了」，而本机 SQLite 上是 201。两库行为不同、都不报错。
        #    而"注册货主与散客同号"在业务上完全正常：散客就是没有账号的人，电话相同恰恰是常态。
        #
        # 现在的形式：把"谁参与唯一"编码进**列值**（[Customer.tmp_phone_key]），
        # 在它上面建**普通唯一索引**。两种数据库对"唯一索引里的多个 NULL"语义一致（都不算冲突），
        # 于是再也没有方言差异。唯一性仍然由**数据库**保证（并发下"先查再插"挡不住重复档案，
        # 而重复档案会把同一个散客的应收拆成两半）。
        Index("uq_customers_tmp_phone", "tmp_phone_key", unique=True),
        # ⚠️ 这一条同样是 `sqlite_where`，但**它无害**（留着，不为了对称再加一列）：
        #    MySQL 上它退化成 `UNIQUE(user_id)`，比"只约束注册客户"更严；而 `user_id` 只有注册客户
        #    会填，应用侧"按 user_id 先查再插"对**任何** kind 都会复用已存在的档案
        #    （`customers.create_customer`），所以那道更严的约束在实践中永远撞不到。
        Index("uq_customers_registered", "user_id", unique=True, sqlite_where=text("kind='registered'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[CustomerKind] = mapped_column(String(12), default=CustomerKind.TMP, index=True)
    user_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 「散客电话」的唯一键：散客填电话，**其余情况一律 NULL**（NULL 在唯一索引里不算冲突）。
    #: 只有一个写入点（`create_customer`）——`customers` 没有改档案的端点，
    #: 所以这个不变量不需要在别处维护；真加了改电话/改 kind 的端点，必须同步维护它。
    tmp_phone_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_member: Mapped[bool] = mapped_column(Boolean, default=False)
    arrears_unit_id: Mapped[int | None] = mapped_column(nullable=True)
