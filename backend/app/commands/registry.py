"""订单域命令的**声明表** —— 第二轮整改 R2-02。

## 这一页是什么
它把「订单有哪些命令、每条允许从什么状态到什么状态、要什么权限、会发出什么事实」
写成一张**可以被机器核对的表**。

⛔ 它**不是第二份实现**：真正做事的是 `impl` 指到的那个函数；本表只声明。
判据 `_tools/qa/_check_order_commands.py` 拿它与 `services/order_flow.py` 里的
条件 UPDATE（CAS）**逐条对账** —— 声明与代码不一致就报红（多一条、少一条、前置状态写错都算）。

## 为什么值得有这张表（指南 §三 / §十一）
- **状态机只有一处实现**（`order_flow`），但「这条命令的前置状态是什么」原来只写在函数体的注释里。
  注释会腐烂，表不会 —— 表有判据钉着，而且钉的是**代码里的条件 UPDATE**，不是文字。
- **权限与命令是同一件事的两面**：`order:dispatch` 这个权限点到底管哪个动作？在这张表出现之前，
  答案散在几十个端点的签名里；现在是 `CommandSpec.capabilities`。
- **事件也是**：`orders.assigned` 是谁产生的事实？表里写着，判据还会核对它有没有域认领。

## ⛔ 为什么不建一个万能 transition
指南 §三 明确：「不要为了唯一入口而建立一个巨大万能函数」—— 那会变成
`transition(order, action, context, anything...)`。所以这里是**一条命令一个对象**，
每条命令的前置条件与结果各写各的，由**表**把它们放在一起看，而不是由**函数**吞掉它们。

## 本模块刻意不 import 任何 app 内部的东西
它只装字符串，所以判据可以在**不连数据库、不装配 FastAPI** 的情况下先核对"名字对不对"，
再去读源码核对"形状对不对"。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    """一条订单命令的声明。

    ⚠️ 字段全是**字符串**（不是枚举）：这样本模块不依赖 `app.models.enums` / `app.core.rbac`，
    判据负责把每个字符串拿去与真枚举核对 —— 拼错了会当场报红，而不是在运行期悄悄失效。
    """

    #: 稳定标识（`order.assign`）。判据按它报错，所以**不许改名**（改名等于换了一条命令）。
    name: str
    #: 归属领域 —— 必须出现在 `docs/DOMAIN_BOUNDARIES.md` 里（订单命令一律 `order`）。
    domain: str
    #: 真正做事的那一个函数（`backend/app 相对路径:函数名`）。
    impl: str
    #: 需要的权限点（`Permission` 的成员名）。多条 = 任一即可（读侧那种"多角色各一条"的形状）。
    capabilities: tuple[str, ...]
    #: 前置状态（`OrderStatus` 成员名）。空 = 不依赖状态（例如建单）。
    from_states: tuple[str, ...]
    #: 跃迁之后的状态；空串 = 这条命令**不改状态**（例如改单）。
    to_state: str
    #: 这条命令这条链路上会入队的事件类型（判据核对它是真事件、且有域认领）。
    events: tuple[str, ...]
    #: 会写到**别的域**的表（表名）。判据核对：表真实存在、且不属于本域。
    effects: tuple[str, ...]
    #: 一句话：为什么它是**一条独立命令**，而不是别的命令的一个分支。
    why: str


ORDER_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        name="order.create",
        domain="order",
        impl="commands.order:create_order",
        capabilities=("ORDER_CREATE",),
        from_states=(),
        to_state="PENDING_DISPATCH",
        events=("orders.created", "orders.pending_pool_changed"),
        effects=("operation_logs", "places", "usage_counters", "shipper_contacts"),
        why="建单是所有跃迁的**起点**：它没有前置状态，但必须把初始状态写在一个地方"
            "（第二轮之前它写在路由里 —— 那是唯一一处绕过状态机的状态写入）。",
    ),
    CommandSpec(
        name="order.assign",
        domain="order",
        impl="services.order_flow:assign_driver",
        capabilities=("ORDER_DISPATCH",),
        from_states=("PENDING_DISPATCH",),
        to_state="DISPATCHED",
        events=("orders.assigned", "orders.pending_pool_changed"),
        effects=("operation_logs",),
        why="派单与派单之前的改价/改单是两回事：这一条只做「待派单 → 派给某位司机」"
            "并定格计费规则快照。",
    ),
    CommandSpec(
        name="order.accept",
        domain="order",
        impl="services.order_flow:accept_order",
        capabilities=("ORDER_COMPLETE_DRIVER",),
        from_states=("DISPATCHED",),
        to_state="ACCEPTED",
        events=("orders.driver_acked",),
        effects=(),
        why="司机确认接单：唯一一条**由司机本人**发起、且要求「必须是派给我的那一张」的跃迁。",
    ),
    CommandSpec(
        name="order.complete",
        domain="order",
        impl="services.order_flow:complete_delivery",
        capabilities=("ORDER_COMPLETE_DRIVER",),
        from_states=("ACCEPTED",),
        to_state="DELIVERED",
        events=("orders.delivered", "ledger.updated"),
        effects=("operation_logs", "ledgers", "inventory_movements", "driver_bills"),
        why="送达是本系统**副作用最多**的一条：账本入账、库存提交、司机应付、货损、到仓入库都在这里发生 ——"
            "所以它必须是一条命名的命令，而不是散在路由里的十几行。",
    ),
    CommandSpec(
        name="order.cancel",
        domain="order",
        impl="services.order_flow:cancel_pending",
        capabilities=("ORDER_CANCEL_SHIPPER", "ORDER_CANCEL_DISPATCHER"),
        from_states=("PENDING_DISPATCH", "DISPATCHED"),
        to_state="CANCELLED",
        events=("orders.cancelled", "orders.pending_pool_changed"),
        effects=("operation_logs", "inventory_movements"),
        why="撤销 = 把**还没发生**的单作废（不动钱）：货主与派单员各有一个权限点，"
            "但走的是同一条命令 —— 权限点不一样，状态机一样。",
    ),
    CommandSpec(
        name="order.recall",
        domain="order",
        impl="services.order_flow:recall_dispatch",
        capabilities=("ORDER_RECALL",),
        from_states=("DISPATCHED", "ACCEPTED"),
        to_state="PENDING_DISPATCH",
        events=("orders.recalled", "orders.pending_pool_changed"),
        effects=("operation_logs", "inventory_movements"),
        why="撤回派单 = 把单从司机手里收回来**再派给别人**（与撤销的差别是它回到待派池）——"
            "它还要清掉逐单覆盖值，否则下一任司机按上一任的数字拿钱。",
    ),
    CommandSpec(
        name="order.split",
        domain="order",
        impl="services.order_flow:split_order",
        capabilities=("ORDER_EDIT",),
        from_states=("PENDING_DISPATCH",),
        to_state="CANCELLED",
        events=("orders.created", "orders.pending_pool_changed"),
        effects=("operation_logs", "inventory_movements"),
        why="拆单是**一条命令产生 N 张子单**：父单被作废（CANCELLED）、子单全部回到待派单。"
            "把它与「撤销」分开，是因为它同时改变一批订单，而不是一张。",
    ),
    CommandSpec(
        name="order.return",
        domain="order",
        impl="services.order_flow:mark_returned",
        capabilities=("ORDER_RETURN",),
        from_states=("DELIVERED",),
        to_state="RETURNED",
        events=("ledger.updated", "returns.request_closed"),
        effects=("ledgers", "inventory_movements", "cash_flows"),
        why="整单退完 → 已退货。退钱的算法在退货域与钱域，本命令只管**状态这一格**："
            "这也正是它必须是一条独立命令的原因（状态与红冲是两个不同的事实）。",
    ),
    CommandSpec(
        name="order.edit",
        domain="order",
        impl="commands.order:update_order",
        capabilities=("ORDER_EDIT",),
        from_states=("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"),
        to_state="",
        events=("orders.edited",),
        effects=("operation_logs",),
        why="改单**不改状态**（to_state 是空串）：它改的是地址 / 电话 / 说明 ——"
            "而这三样在「已派单 / 已接单」时正是最需要改的（客户在电话里改地址）。",
    ),
)


def by_name(name: str) -> CommandSpec | None:
    """按标识取一条命令（工具与文档用；找不到返回 None，⛔ 不抛）。"""
    for c in ORDER_COMMANDS:
        if c.name == name:
            return c
    return None
