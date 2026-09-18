from datetime import datetime

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SoftDeleteMixin:
    """「伪装删除」：删除只打标记，`POST /{id}/restore` 可以原样返回。

    ### 为什么主数据一律走这条（v3.26）
    用户的底线是「不要删了就搞不回来了」。物理删除满足不了这条：
    它把行连同外键关系一起抹掉（商品那次更狠——`inventory_movements` 被级联整批删除），
    而**没有任何地方留着它原来的样子**。

    加了这两列之后，「删掉」的真实语义变成"我不希望再看到它"，而恢复是**逐字段照搬**的
    ——不是"按记忆重建一条像的"（重建会换编号、会丢图片、会在同号冲突时顶掉别人）。

    ### 查询侧必须一起改（不然等于没删）
    凡是列这些表的地方都要 `.where(X.is_deleted.is_(False))`；
    红线/单测会盯着"删掉之后列表里真的看不见了、恢复之后又看得见"。
    """

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
