"""每天一行**的 AI 调用计数（整改报告 §15 ② 的 `AI_calls`）。

## 为什么这张表是「客户端报上来的」，而 `AI_write_confirmed` 不是
模型跑在 App 里（后端没有 AI 代理端点），所以**后端看不到这次调用** ——
这是本项目 AI 架构的既定事实（见 AI 写操作架构：模型只能"申请"，写入走真实接口）。
于是 `AI_calls` 只有一条路：App 每跑完一次对话，向后端报一个数。

⛔ 与它相对的 `sorders_ai_write_confirmed_today` 是**后端从库里数出来的**
（`operation_logs.origin = ai`）—— 两者口径不同，**写在这里免得后人以为它们同源**：
一个能与审计表逐行对回去，一个只能信客户端。

## 为什么按「业务当地日」存一行，而不是每次调用存一行
这个数只用于看趋势（今天跑了几次），不需要逐条留痕；逐条存会让这张表长得比审计表还快，
而它承载的信息量只有"今天 N 次"。所以：一天一行、累加。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.business_time import utc_now_naive
from app.models.base import Base


class AiCallDaily(Base):
    __tablename__ = "ai_call_daily"

    #: 业务当地日（`YYYY-MM-DD`，与 `business_today()` 同口径）—— 主键，一天一行。
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now_naive, nullable=False
    )