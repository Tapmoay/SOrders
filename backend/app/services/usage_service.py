"""「常用的排前面」的**唯一实现**（用户 2026-09-22 定的列表排序规则）。

## 规则（一句话）
所有"挑东西的列表"：**① 常用度降序（按人）→ ② 先创建的在前（`id` 升序）**。
"看记录的列表"（订单/账本/消息/审计/流水/账单）**不适用** —— 那些必须最新在前。

## 这个文件为什么存在（而不是每个端点自己写）
排序表达式写成两行很容易，**写歪了也不报错**：`kind` 拼错、`user_id` 忘了带、`coalesce` 漏了
（漏了的话"没用过的行"因为 NULL 排到最后 —— 与"先创建的在前"正好相反，而且看不出来）。
所以 JOIN 与 ORDER BY **只有这一处**：列表端点写一行 `stmt = with_popularity(stmt, Model, KIND, me)`。

## 计数怎么记
`record_usage(db, user=me, kind=KIND_X, target_id=id)`：**计数由数据库自增**
（⛔ 不许读改写，见 `models/usage.py` 的第 2 条约束；那是 2026-09-19 审计与库存同一个形状的坑）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session, aliased

from app.models.usage import UsageCounter

# ── `kind` 的取值：**只有这一处**（列表端点排序用的 kind 必须与"记一次"时用的完全一致）──
KIND_CONTACT = "contact"                    # 联系人（shipper_contacts）
KIND_ADDRESS = "address"                    # 线路 / 地址（shipper_addresses）
KIND_LOCATION = "location"                  # 「我的地点」（shipper_locations）
KIND_PLACE = "place"                        # 全局共享地点库（places）—— 沿用时记
KIND_PRODUCT = "product"                    # 商品（products）
KIND_USER = "user"                          # 人：货主 / 批发商 / 司机（users）
KIND_CUSTOMER = "customer"                  # 客户（customers）
KIND_ARREARS_UNIT = "arrears_unit"          # 挂靠单位
KIND_VEHICLE = "vehicle"                    # 车辆
KIND_FREIGHT_TEMPLATE = "freight_template"  # 运费模板
KIND_BILLING_RULE = "billing_rule"          # 司机计费规则
KIND_PRICE_RULE = "price_rule"              # 批发商专属价
#: 预订单 / 订单模板（order_templates）：`POST /order-templates/{id}/use` 记一次"用它下了单"。
KIND_ORDER_TEMPLATE = "order_template"
#: 供应商 / 厂商（suppliers）：记一次"给这个供应商建了应付单/付了款/查了他"。
#: ⚠️ 记账点只有一处（`api/v1/suppliers.py::_touch`），别在几个端点里各记一次不同 kind。
KIND_SUPPLIER = "supplier"


def _kind_key(kind: Any) -> str:
    """`kind` 归一成字符串（调用方可能传枚举；归一只有这一处，避免两种写法各记一份计数）。"""
    return (kind.value if hasattr(kind, "value") else str(kind or "")).strip().lower()


def record_usage(
    db: Session,
    *,
    user: Any,
    kind: Any,
    target_id: int | None,
    now: datetime | None = None,
) -> int:
    """记一次「这个人用了这个东西」，返回**累计次数**。

    - 第一次用：插一行 `use_count = 1`；
    - 之后：`UPDATE … SET use_count = use_count + 1`（**数据库自增**，并发安全）；
    - `target_id` 为空 / 用户为空时**什么都不做并返回 0**（匿名或脏调用不该在库里留垃圾行）。

    ⚠️ **调用方要保证 kind 与排序时用的 kind 一致**；不一致的后果是"计数在涨、列表不往前"，
    不报错、不崩溃 —— 这一条在 `kind` 常量唯一的本文件里已经尽量兜住，但仍需人工别拼字符串。
    """
    if user is None or not target_id or int(target_id) <= 0:
        return 0
    key = _kind_key(kind)
    if not key:
        return 0
    stamp = now or datetime.now(timezone.utc)
    user_id = int(getattr(user, "id", 0) or 0)
    if not user_id:
        return 0

    row = db.scalars(
        select(UsageCounter).where(
            UsageCounter.user_id == user_id,
            UsageCounter.kind == key,
            UsageCounter.target_id == int(target_id),
        )
    ).first()
    if row is None:
        row = UsageCounter(user_id=user_id, kind=key, target_id=int(target_id), use_count=1, last_used_at=stamp)
        db.add(row)
        db.flush()
        return 1
    # ⛔ 计数列必须由数据库自增（见 models/usage.py 第 2 条约束）
    db.execute(
        update(UsageCounter)
        .where(UsageCounter.id == row.id)
        .values(use_count=func.coalesce(UsageCounter.use_count, 0) + 1, last_used_at=stamp)
    )
    db.refresh(row)
    return int(row.use_count or 1)


def _usage_join(stmt: Any, model: Any, kind: Any, user_id: int) -> tuple[Any, Any]:
    """给一条 `select` 挂上"我这个人在这一类东西上的次数"（外连接，没用过就是 NULL）。"""
    uc = aliased(UsageCounter)
    stmt = stmt.outerjoin(
        uc,
        and_(
            uc.target_id == model.id,
            uc.kind == _kind_key(kind),
            uc.user_id == int(user_id),
        ),
    )
    return stmt, uc


def with_popularity(stmt: Any, model: Any, kind: Any, user: Any) -> Any:
    """列表端点**唯一一行**的排序改造：`with_popularity(stmt, Model, KIND_X, current)`。

    排序 = **常用度降序 → 先创建的在前**：
    - `coalesce(use_count, 0)` ⛔ 不能省：漏了的话"没用过的行"因为 `NULL` 在**降序里排最后**，
      与"先创建的在前"正好相反，而且界面上看不出来（看起来只是"顺序有点怪"）；
    - 第二键用 `model.id`（自增主键 ≈ 创建顺序）而不是 `created_at`：少一次比较、且**同一秒**
      创建的两条也有确定顺序（`created_at` 同秒时顺序会随数据库而变）。
    """
    user_id = int(getattr(user, "id", 0) or 0)
    if not user_id:
        # 认不出人（理论上不会发生：这些都是登录后端）→ 退回"先创建的在前"，
        # 而不是让整个列表 500 —— 排序永远不该是让用户看不到数据的原因。
        return stmt.order_by(model.id.asc())
    stmt, uc = _usage_join(stmt, model, kind, user_id)
    return stmt.order_by(func.coalesce(uc.use_count, 0).desc(), model.id.asc())
