# -*- coding: utf-8 -*-
"""**只读诊断面**（R4-49 · P4-②）：把 pricing_runtime 的只读那一半，暴露成一个**实例级观测面**。

## 它为什么存在（证据缺陷，不是新功能）

P4-② 要证明的命题是：

    两个**当前正在运行**的生产实例，对**同一份** Pricing 输入，实际执行出了**相同**的 Decision。

在此之前，那个 Decision **只在写路径上露面**（派单 / 手动定价 / 改运费三条）。
两个看起来"像"的只读面其实都不算数：

    GET /freight-templates/quote   -> services.freight_pricing.quote_for  ← **旧路**，不经过组装点
    GET /pricing/quote             -> 扩展自己的试算；只收 pricing_kind/amount/单价/数量，
                                      **连 order / driver / route 上下文都没有**，也绕过组装点的策略与冻结

⇒ 生产上**不存在**「只读 + 真正经过 pricing_runtime」的面，双实例一致性因此**证不了**。
✅ 这属于 docs/R4_CANARY_WINDOW.md 里「修**明确发现的**证明缺陷」，⛔ 不是新的架构工程。

## ⛔ 六条硬限制（用户 2026-09-27 定；写进代码，⛔ 不靠记性）

1. **只做诊断**：⛔ 不是新的业务能力、⛔ 不给 App 调用、⛔ 不进正常业务路由 —— 挂在 /diagnostics/ 下；
2. **输入只来自现有业务对象**：只收 order_id + driver_id + claimed_fee，
   ⛔ 不接受调用方自己拼一份 Pricing Context（那测的就是假上下文）；
3. **直接调 pricing_runtime.decide** —— 生产写路径调的**同一个函数**（orders_assignment._freight_decision），
   ⛔ 不复制一份 decide_for_diagnostic()：复制了立刻就是"生产路 vs 诊断路"两套逻辑；
4. **零写入**：decide() 本身不写任何表（落快照是**调用方**的事，这里没有那个调用方）。
   ⛔ 这不是靠嘴说的：P4-② 的运行记录里带**请求前后订单四列逐字节相同**的判据；
5. **走现有安全边界**：require_permission(Permission.ORDER_DISPATCH)，⛔ 不是匿名 GET；
6. **⛔ 不顺便解决别的问题**：不重新定价、⛔ 不覆盖快照、⛔ 不保存 decision、⛔ 不写 audit、
   ⛔ 不引入新的 Pricing 抽象。它唯一的职责就是**把已有的只读计算暴露出来**。

⚠️ 本模块**自己声明** router：按文件解析的 AST 工具（端点索引 / AI 能力表）靠这一行算 URL 前缀。
"""

import os
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Order, User

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


class PricingDecisionOut(BaseModel):
    """一次**只读**的定价判定。

    字段就是 P4-② 要比的那四项（kind / resolution / contract / quoted_fee），
    再加两样"这条响应是谁给的"—— pid 与 resolver。
    """

    #: 谁回答的：**那个进程自己的 PID**。配合 ss -lntp 就能把「响应 ←→ 实例」钉死，
    #: ⛔ 不用"我打的是 8111 所以它一定是 A"这种推断。
    pid: int
    #: 这一次进程**实际生效**的算价装配（与 /health 的 pricing 同源：pricing_fingerprint()）。
    resolver: dict

    order_id: int
    driver_id: int | None
    claimed_fee: str | None

    kind: str
    resolution: str
    #: 契约身份（order_money.FREIGHT_KIND_CONTRACTS 那张唯一真相表）——「结果相同 ≠ 实现一致」那一维。
    contract: dict
    quoted_fee: str | None
    agreed: bool | None
    override: bool
    reason: str
    rule: dict | None


@router.get("/orders/{order_id}/pricing-decision", response_model=PricingDecisionOut)
def pricing_decision(
    order_id: int,
    driver_id: int | None = Query(None, description="按这个司机算（不传 = 没司机那一档）"),
    claimed_fee: str | None = Query(None, description="派单员会给的那个数；不传 = 没有金额"),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> PricingDecisionOut:
    """**只读**：这个真实订单在当前生产状态下，交给当前 Pricing Runtime 会得到什么 Decision。

    ⛔ 它不写库、不落快照、不留 decision —— 想看"如果派单会怎么样"，这里给的就是那个答案，
    但**产生那个答案的写入动作不在这里**。
    """
    from app.core.pricing_runtime import decide, pricing_fingerprint
    from app.services.order_money import FREIGHT_KIND_CONTRACTS

    if claimed_fee is not None:
        try:
            Decimal(claimed_fee)
        except (InvalidOperation, TypeError, ValueError) as exc:
            # 与扩展那条 quote 同一个口径：给人一句能照着改的中文，⛔ 不是英文结构体
            raise HTTPException(
                status_code=400,
                detail="claimed_fee 请填一个正常的数字：" + str(claimed_fee),
            ) from exc

    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")

    # ⭐ 与生产写路径**同一个函数**（orders_assignment._freight_decision 也是这一句）——
    #    ⛔ 这里没有第二份"诊断用的判定逻辑"。
    d = decide(db, order, driver_id=driver_id, claimed_fee=claimed_fee)

    return PricingDecisionOut(
        pid=os.getpid(),
        resolver=pricing_fingerprint(),
        order_id=order_id,
        driver_id=driver_id,
        claimed_fee=claimed_fee,
        kind=d.kind,
        resolution=d.resolution,
        contract=dict(FREIGHT_KIND_CONTRACTS.get(d.kind) or {}),
        quoted_fee=d.quoted_fee,
        agreed=d.agreed,
        override=d.override,
        reason=d.reason,
        rule=d.rule,
    )
