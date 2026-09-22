"""「常用度」的管理接口（2026-09-22 统一列表排序规则）。

只有一个动作：**把我自己的常用计数清空**（用户 2026-09-22：
「在我的基础设置里加一个**重置计数**」）。

## 为什么单开一个小模块
重置这件事横跨"所有挑东西的列表"（联系人/线路/地点/商品/人/客户/…都在同一张表里），
挂在任何一个业务 router（shipper / products / users）下都是**归错门**：下一个人要找它时
会先想"它属于哪个业务"，而正确答案是"它属于那张计数表"。

## 三条边界（都在下面这个函数里落）
1. ⛔ **只清自己那几行**（`user_id == current.id`）：常用度是**按人**的（用户定的口径），
   清别人的等于替所有人把"常用"这件事抹掉 —— 而界面上完全看不出是谁干的。
2. **硬删**（不是软删）：这张表是**派生统计**（"我用过它几次"），不是用户录入的业务记录，
   留着一堆 `use_count = 0` 的空行只会让排序多绕几圈。⚠️ 与"删除一律软删"那条硬规矩不冲突
   —— 那条管的是**用户的数据**（订单/客户/商品…）。代价是**重置后无法还原**，
   所以界面上必须**先说明再确认**（`ui/profile/BasicSettingsScreen.kt` 那一格）。
3. **不影响主数据**：商品、地点、联系人一条都不会少，只是"排在前面的依据"没了。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser
from app.models import UsageCounter
from app.schemas.usage import UsageResetOut

router = APIRouter(prefix="/usage", tags=["usage"])


@router.post("/reset", response_model=UsageResetOut)
def reset_usage(current: CurrentUser, db: Session = Depends(get_db)) -> UsageResetOut:
    """清空**我自己的**常用计数（列表回到「先创建的在前」）。"""
    n = db.execute(delete(UsageCounter).where(UsageCounter.user_id == current.id)).rowcount or 0
    db.commit()
    # 返回清掉了几行：界面用它说"清掉了 N 条记录"——只说"重置成功"的话，
    # 用户无法区分"真的清了 20 条"和"本来就没有、什么都没发生"。
    return UsageResetOut(deleted=int(n))
