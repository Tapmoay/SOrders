from datetime import datetime

from sqlalchemy import Boolean, DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.business_time import utc_now_naive


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """`created_at` / `updated_at`：**由 Python 写 UTC**，不用库端时钟。

    ### 为什么（2026-09-19 外部完整检查 C-2，本轮收敛）
    原来是 `server_default=func.now()` + `onupdate=func.now()`，也就是**库端时钟**。
    而本项目的口径是"库里一律存 UTC"（`core/business_time.py`）——于是在生产 MySQL
    （会话时区 +08:00）上，**同一个库里同时存在两种基准**：

    | 列 | 谁写 | 生产基准 |
    |---|---|---|
    | `created_at` / `updated_at`（所有表） | 库端 `NOW()` | **+08:00 墙上时间** |
    | `orders.delivered_at`、各类 `*_at` | Python `utc_now_naive()` | UTC |

    后果是**静默**的：拿 UTC 的 Python 值去减库端的 `created_at`，差整整 8 小时 ——
    "待派超时 4 小时"实际 12 小时、保留策略与审计窗口整体偏 8 小时；
    而**本机 SQLite 两边都是 UTC，所以所有单测与探针都是绿的**（这正是它活了这么久的原因）。

    ### 现在的形状
    - **Python 提供值**（`default` / `onupdate`）→ 新写入的行一律是 UTC；
    - `server_default` **保留**：只是给"绕过 ORM 的原生 SQL 插入"兜底，而
      `database.py` 已把 MySQL 会话时区钉成 UTC，所以那条兜底路径**也是 UTC**（不再有两个基准）。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now_naive, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now_naive,
        onupdate=utc_now_naive,
        server_default=func.now(),
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
