"""能力注册表（Capability Registry）—— 第二轮 R2 · 贯穿层。

## 它解决什么（方向指南 §十一）
指南画的是：

```text
  Capability Registry
          │
     ┌────┼─────┬──────┐
     ↓    ↓     ↓      ↓
   API   AI    UI    Audit
```

> 这样 AI 就不会成为自己的权限系统。

在这之前，「一个权限点是什么」散在**四处**：`rbac.py` 的枚举、`ROLE_PERMISSIONS` 矩阵、
`SCOPES` 那张只写了 scope 的表、以及各端点签名上的 `require_permission(...)`。
四处各说各话时**没有任何地方会报错**（本项目吃过这个亏：改矩阵不改端点，接口照样能读）。

## 现在：只有这一张表
每个权限点在这里**声明一次**，`rbac.py` 的 `ROLE_PERMISSIONS` 与 `SCOPES` 都由它**派生** ——
⛔ 不再有第二份可以改歪的副本。判据 `_tools/qa/_check_capability_registry.py` 核对两件事：

1. 每个权限点**恰好一条**能力（不多不少、不重复、不变化石）；
2. ⭐ **每条能力有没有真的执行点** —— 它去 `backend/app/api/**` 里找
   `require_permission(Permission.X)` / `require_any_permission` / `require_roles`；
   找不到的必须写进 `DECLARED_ONLY` 例外表（带理由与「什么时候删掉这一条」）。
   ⛔ **执行点是机器算出来的，不是声明出来的** —— 声明一个"已经生效"然后没人执行，是这一条要防的事。

## 与 AI / UI / 审计的关系
- **AI**：读能力的角色裁剪走 `ROLE_PERMISSIONS`（由本表派生）—— AI 因此没有自己的权限系统；
- **UI**：安卓侧显示不显示一个按钮，判据是「这个角色有没有这条能力」；
- **审计**：`models/enums.OperationAction` 的动作码与 `kind=write` 的能力一一对照。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    """一条能力：**谁**（roles）能对**什么**（resource/action，由权限点的值拆出来）做**到什么范围**（scope）。"""

    #: `Permission` 的成员名（不写值：值就是 `resource:action`，写两遍必然有一天不一致）。
    permission: str
    #: 这句话是给**人**看的：这条能力到底允许什么。
    what: str
    #: 数据范围（`SCOPE_KINDS` 里的一个）+ 为什么是这一档。
    scope: str
    scope_why: str
    #: 哪些角色有它（⛔ 不含 dispatcher 的**绕过** —— 那条在 rbac.BYPASS_ROLES 里单独声明）。
    roles: tuple[str, ...]
    #: read / write。审计口径按它分（写能力要有动作码）。
    kind: str


#: ⛔ 权限点 → 能力，**一条不落**。判据按 `Permission` 的成员逐个核对。
CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        permission="ORDER_CREATE",
        what="客户（或代客）下一张新订单",
        scope="self",
        scope_why="建单是自己发起的动作，数据归属看行上的 shipper_id",
        roles=("shipper", "dispatcher"),
        kind="write",
    ),
    Capability(
        permission="ORDER_READ_OWN",
        what="看自己名下的订单",
        scope="own",
        scope_why="货主只看自己名下的单（行级过滤）",
        roles=("shipper",),
        kind="read",
    ),
    Capability(
        permission="ORDER_READ_ASSIGNED",
        what="看派给自己的订单",
        scope="assigned",
        scope_why="司机只看派给自己的单（行级过滤）",
        roles=("driver",),
        kind="read",
    ),
    Capability(
        permission="ORDER_READ_ALL",
        what="看全部订单",
        scope="all",
        scope_why="派单员看全部：单店经营者，没有「只看自己」这一档",
        roles=("dispatcher",),
        kind="read",
    ),
    Capability(
        permission="ORDER_CANCEL_SHIPPER",
        what="撤销自己名下的单",
        scope="own",
        scope_why="货主只能撤销自己名下的单（行级过滤按 shipper_id）",
        roles=("shipper",),
        kind="write",
    ),
    Capability(
        permission="ORDER_CANCEL_DISPATCHER",
        what="撤销任意单（含代客撤销）",
        scope="all",
        scope_why="派单员可撤任意单（含代客撤销）",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="ORDER_RETURN",
        what="执行退货（红冲营收、回补库存、可能退现）",
        scope="all",
        scope_why="退货动账本与库存，只有派单员能做，不分归属",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="ORDER_RETURN_REQUEST",
        what="给自己的单提退货申请",
        scope="own",
        scope_why="货主只能给自己的单提退货申请",
        roles=("shipper",),
        kind="write",
    ),
    Capability(
        permission="ORDER_DELETE_CANCELLED",
        what="把订单软删进回收站",
        scope="own",
        scope_why="软删进回收站：货主限自己的、派单员不限",
        roles=("shipper", "dispatcher"),
        kind="write",
    ),
    Capability(
        permission="ORDER_DISPATCH",
        what="把待派单派给某位司机",
        scope="all",
        scope_why="派单是全局动作：要看到所有待派单与所有司机",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="ORDER_RECALL",
        what="撤回派单（把单从司机手里收回来）",
        scope="all",
        scope_why="撤回改派是全局动作：把单从某个司机手里收回来再派给别人",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="ORDER_EDIT",
        what="代客改单与拆单",
        scope="all",
        scope_why="派单员代客改单，改的往往是别人名下的单，所以不分归属",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="ORDER_COMPLETE_DRIVER",
        what="确认接单与完成配送",
        scope="assigned",
        scope_why="司机只能完成派给自己的单",
        roles=("driver",),
        kind="write",
    ),
    Capability(
        permission="ORDER_INTERNAL_NOTE",
        what="在订单上写内部备注",
        scope="assigned",
        scope_why="内部备注写在单上，司机限自己的单",
        roles=("driver", "dispatcher"),
        kind="write",
    ),
    Capability(
        permission="ORDER_UPLOAD_DELIVERY",
        what="上传送达照片",
        scope="assigned",
        scope_why="送达照片只能传到派给自己的那张单上（行级过滤按 driver_id）",
        roles=("driver",),
        kind="write",
    ),
    Capability(
        permission="PRODUCT_MANAGE",
        what="维护商品目录与库存",
        scope="all",
        scope_why="商品是全局主数据，不分归属",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="PRICE_RULE_MANAGE",
        what="维护批发商专属价",
        scope="all",
        scope_why="专属价按批发商维度，管理动作是全局的",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="LEDGER_READ_OWN",
        what="看自己那本账",
        scope="own",
        scope_why="货主看自己的账（行级过滤）",
        roles=("shipper",),
        kind="read",
    ),
    Capability(
        permission="LEDGER_READ_ALL",
        what="看全部账本",
        scope="all",
        scope_why="派单员看全部账：账本页是仪表盘",
        roles=("dispatcher",),
        kind="read",
    ),
    Capability(
        permission="LEDGER_EDIT",
        what="手工记账与核销",
        scope="all",
        scope_why="手工记账写的是全局账本，不挂在某一个人的名下",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="NOTIFICATION_READ",
        what="看发给自己的消息",
        scope="self",
        scope_why="消息按 recipient_id 过滤 —— 这里的「自己的」是收件人本人，比其他 own 更窄",
        roles=("shipper", "driver", "dispatcher"),
        kind="read",
    ),
    Capability(
        permission="NOTIFICATION_MANAGE",
        what="群发与管理消息",
        scope="all",
        scope_why="群发与管理面向所有人；个人消息在 NOTIFICATION_READ 那一档",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="OPERATION_LOG_READ",
        what="看审计日志",
        scope="all",
        scope_why="审计日志是全局只读视图，任何角色看到的都是同一份",
        roles=("dispatcher",),
        kind="read",
    ),
    Capability(
        permission="USER_MANAGE",
        what="维护账号、司机名册、货主名册",
        scope="all",
        scope_why="账号、司机名册、货主名册都是全局主数据，不分归属",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="ORDER_PRODUCT_EDIT",
        what="增删改订单商品行",
        scope="all",
        scope_why="订单商品行是订单的一部分，编辑权归派单员",
        roles=("dispatcher",),
        kind="write",
    ),
    Capability(
        permission="STATS_READ",
        what="看报表与统计",
        scope="all",
        scope_why="报表是全店口径（营业额/毛利/司机绩效），没有「只看自己那份」的版本",
        roles=("dispatcher",),
        kind="read",
    ),
)


def by_permission() -> dict[str, Capability]:
    """权限点成员名 → 能力（重复键留给判据去报红，这里取先出现的那个）。"""
    out: dict[str, Capability] = {}
    for c in CAPABILITIES:
        out.setdefault(c.permission, c)
    return out


def role_matrix() -> dict[str, frozenset[str]]:
    """角色 → 它有的能力（由本表**派生** —— 这就是"只有一处声明"的意思）。"""
    out: dict[str, set[str]] = {}
    for c in CAPABILITIES:
        for r in c.roles:
            out.setdefault(r, set()).add(c.permission)
    return {k: frozenset(v) for k, v in out.items()}


def scope_table() -> dict[str, tuple[str, str]]:
    """权限点 → (scope, 为什么)（`rbac.SCOPES` 由它派生）。"""
    return {c.permission: (c.scope, c.scope_why) for c in CAPABILITIES}
