"""AI 调用计数上报（整改报告 §15 ② 的 `AI_calls`）。

## 为什么需要它（也为什么它只有一个端点）
模型跑在 **App 里**（后端没有 AI 代理端点），所以后端**看不到**这次对话 ——
`AI_calls` 只能由 App 跑完一次对话后来报一个数。这是「服务端能知道的事」与
「只有客户端知道的事」的分界：

· `sorders_ai_write_confirmed_today` —— **后端从库里数**（`operation_logs.origin = ai`），
  能逐行对回审计表；
· `sorders_ai_calls_today` —— **只能信客户端上报**（就是本端点）。
  两者的口径差异写在各自指标的 `help` 里，⛔ 不要把它们当成同源的两个数。

## 三条纪律
1. **上限 `MAX_REPORT`**：这是唯一可见的上报口，没有上限就等于给了一个「一句话把指标刷到天上去」
   的入口（而指标被刷坏之后，没人再会信它）；
2. **认不出用户就不收**（正常登录鉴权）—— 不记 IP、不记设备，只累加一个计数；
3. **同一天并发上报要安全**：`day` 是主键，两个 worker 同时 insert 会有一个撞 `IntegrityError`
   → 撞了就改成累加（见下面那段注释），⛔ 不许让它变成 500。
"""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.business_time import business_today, utc_now_naive
from app.database import get_db
from app.deps import CurrentUser
from app.models.ai_call_daily import AiCallDaily

router = APIRouter(prefix="/ai", tags=["ai"])

#: 单次上报的上限。为什么要有它：见模块说明第 1 条 —— 没有上限，指标就是可被刷坏的。
MAX_REPORT = 100


class AiCallReport(BaseModel):
    calls: int = Field(
        default=1,
        ge=1,
        le=MAX_REPORT,
        description=f"这次要累加的 AI 调用次数（1~{MAX_REPORT}）。App 可以在一次批量对话后合并上报。",
    )


@router.post("/telemetry", status_code=status.HTTP_200_OK)
def report_ai_calls(
    body: AiCallReport,
    db: Session = Depends(get_db),
    current: CurrentUser = None,  # noqa: ARG001 —— 只为鉴权；这个端点不记「谁报的」
) -> dict:
    """把「刚跑了 N 次 AI 对话」累加进今天那一行。"""
    day = business_today().isoformat()
    row = db.get(AiCallDaily, day)
    if row is None:
        # ⛔ 必须**赋回 `row`**：第一版写成 `db.add(AiCallDaily(...))` 而没接住对象，
        #    于是插入成功、返回时 `row.calls` 抛 AttributeError → **数据进去了但接口回 500**。
        #    这种"写成功了却报错"的形状最坏：客户端会重试，而计数没有幂等保护。
        row = AiCallDaily(day=day, calls=body.calls, updated_at=utc_now_naive())
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # ⚠️ 两个 worker 同时给今天开第一行时的竞态：后到的那个撞主键。
            #    ⛔ 撞了就退回去累加，**不许**让它变成 500 —— 上报失败不该影响任何业务，
            #    而它本来就是一个"尽力而为"的计数。
            db.rollback()
            row = db.get(AiCallDaily, day)
            if row is None:                     # 极端情况：那一行又被删了
                return {"day": day, "calls": 0, "reported": body.calls}
            row.calls += body.calls
            row.updated_at = utc_now_naive()
            db.commit()
    else:
        row.calls += body.calls
        row.updated_at = utc_now_naive()
        db.commit()
    return {"day": day, "calls": row.calls, "reported": body.calls}