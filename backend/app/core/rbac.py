from enum import Enum

from app.models.enums import UserRole


class Permission(str, Enum):
    """权限点。

    ⚠️ **这几个"读"权限点只是声明，没有 `require_permission(...)` 在用它们**
    （2026-09-19 审计 F8）：`ORDER_READ_OWN` / `ORDER_READ_ASSIGNED` /
    `LEDGER_READ_OWN` / `LEDGER_READ_ALL` / `NOTIFICATION_READ` —— 读侧的真实判据是
    各端点体内**内联的 `user_role_key(current)` 判断**（因为"货主只看自己的、派单员看全部"
    这种行级规则一个权限点表达不了）。

    于是存在一个**会静默失效的错觉**：改 `ROLE_PERMISSIONS`（比如把 `LEDGER_READ_ALL`
    从派单员那儿去掉）**不会**改变任何端点的行为，而 `08A_ENDPOINT_INDEX.md` 的权限列
    与 AI 读能力目录又是从这张矩阵推导的 → 文档说"没权限了"、接口照样能读。
    机器判据见 `_tools/qa/_check_permission_points.py`（未使用的权限点必须在这张表里写清理由，
    且这张表不许变长）。要真正按矩阵收口，得逐个端点把内联判断换成 `require_permission`。
    """
    ORDER_CREATE = "order:create"
    ORDER_READ_OWN = "order:read_own"
    ORDER_READ_ASSIGNED = "order:read_assigned"
    ORDER_READ_ALL = "order:read_all"
    ORDER_CANCEL_SHIPPER = "order:cancel_shipper"
    ORDER_CANCEL_DISPATCHER = "order:cancel_dispatcher"
    # 退货（2026-09-20）：**只有派单员**能做。
    # 为什么不给货主：一次退货同时动四样东西（账本红冲、库存回补、可能退现、订单状态），
    # 而货主端看到的就是"应收"这个数 —— 让他按一下就把自己的应收改掉，这份账就没有第二个人核对了。
    # 与撤销的差别正在这里：撤销不动钱也不动库存（把还没发生的单作废），所以货主可以自己做。
    ORDER_RETURN = "order:return"
    # 货主**申请**退货（2026-09-21 用户要求：「批发商只是一个申请，派单员才是实际性的操作」）。
    #
    # ⛔ 为什么必须与 `ORDER_RETURN` **分开两个权限点**（而不是给货主加上 ORDER_RETURN）：
    #    两者的差别正是这一轮要保住的那条线 ——
    #    · `ORDER_RETURN_REQUEST` = **写一张申请单**（不碰账本、不碰库存、不改订单状态）；
    #    · `ORDER_RETURN` = **真的退货**（红冲营收、回补库存、可能退现、订单转「已退货」）。
    #    合成一个权限点的后果不是"少一层校验"，而是把上面那条注释的理由原地作废：
    #    货主按一下就能改自己的应收和公司库存，而派单员根本不知道。
    ORDER_RETURN_REQUEST = "order:return_request"
    ORDER_DELETE_CANCELLED = "order:delete_cancelled"
    ORDER_DISPATCH = "order:dispatch"
    ORDER_RECALL = "order:recall"
    ORDER_EDIT = "order:edit"
    ORDER_COMPLETE_DRIVER = "order:complete_driver"
    ORDER_INTERNAL_NOTE = "order:internal_note"
    ORDER_UPLOAD_DELIVERY = "order:upload_delivery"
    PRODUCT_MANAGE = "product:manage"
    PRICE_RULE_MANAGE = "price_rule:manage"
    LEDGER_READ_OWN = "ledger:read_own"
    LEDGER_READ_ALL = "ledger:read_all"
    LEDGER_EDIT = "ledger:edit"
    NOTIFICATION_READ = "notification:read"
    NOTIFICATION_MANAGE = "notification:manage"
    OPERATION_LOG_READ = "operation_log:read"
    USER_MANAGE = "user:manage"
    ORDER_PRODUCT_EDIT = "order_product:edit"
    STATS_READ = "stats:read"


ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "shipper": frozenset(
        {
            Permission.ORDER_CREATE,
            Permission.ORDER_READ_OWN,
            Permission.ORDER_CANCEL_SHIPPER,
            # 申请退货（2026-09-21）：**只申请**。真正的退货是**另一个权限点**，
            # 它只在 dispatcher 那一格里（见上面两段注释）。
            # ⚠️ 这条注释里刻意**不写**那个权限点的完整名字：`_check_order_return.py` 会在
            #    "货主这一段"里搜它，写了就等于声明"货主也有退货权"（那是错的）。
            Permission.ORDER_RETURN_REQUEST,
            Permission.ORDER_DELETE_CANCELLED,
            Permission.LEDGER_READ_OWN,
            Permission.NOTIFICATION_READ,
        }
    ),
    "driver": frozenset(
        {
            Permission.ORDER_READ_ASSIGNED,
            Permission.ORDER_COMPLETE_DRIVER,
            Permission.ORDER_INTERNAL_NOTE,
            Permission.ORDER_UPLOAD_DELIVERY,
            Permission.NOTIFICATION_READ,
        }
    ),
    "dispatcher": frozenset(
        {
            Permission.ORDER_CREATE,
            Permission.ORDER_READ_ALL,
            Permission.ORDER_CANCEL_DISPATCHER,
            Permission.ORDER_RETURN,
            Permission.ORDER_DELETE_CANCELLED,
            Permission.ORDER_DISPATCH,
            Permission.ORDER_RECALL,
            Permission.ORDER_EDIT,
            Permission.PRODUCT_MANAGE,
            Permission.PRICE_RULE_MANAGE,
            Permission.LEDGER_READ_ALL,
            Permission.LEDGER_EDIT,
            Permission.NOTIFICATION_READ,
            Permission.NOTIFICATION_MANAGE,
            Permission.OPERATION_LOG_READ,
            Permission.USER_MANAGE,
            Permission.ORDER_PRODUCT_EDIT,
            Permission.ORDER_INTERNAL_NOTE,
            Permission.STATS_READ,
        }
    ),
}


# ---------------------------------------------------------------- 三维模型（报告 §9）
#: 报告要的是 `User → Role → Permission → Action → Resource → Scope`。
#: 前两维在本文件上面（`ROLE_PERMISSIONS`），**后三维在这里补齐**：
#:
#: · **Action / Resource 不手写第二份** —— 枚举值本身就是 `"resource:action"` 的形状，
#:   `split()` 从它拆出来。手写一张映射表＝又一处「同一个事实写两遍」，本项目在那种地方栽过很多次。
#: · **Scope 是新增的那一维**：一个权限点**管到哪一层数据**。
#:   它正是「货主只看自己的单」这类**行级规则**没法用一个权限点表达的原因 ——
#:   以前这些规则散在 26 个文件、72 处内联判断里，现在至少**先在模型上有一维**。

#: 允许的 Scope 取值（⛔ 不放别的：多一个取值就要有人解释它和行级过滤怎么对应）。
SCOPE_KINDS = frozenset({"all", "own", "assigned", "self"})


def split(permission: Permission) -> tuple[str, str]:
    """`Permission.ORDER_CREATE` → `("order", "create")`（从枚举值拆，不写第二份表）。

    ⚠️ 值里必须**恰好一个** `:`：多一个少一个都会让资源 / 动作分不清。
    """
    resource, sep, action = permission.value.partition(":")
    if not sep or not resource or not action:
        raise ValueError(f"权限点 {permission.name} 的值 {permission.value!r} 不是 resource:action 的形状")
    return resource, action


#: 权限点 →（Scope, 为什么是这一档）。判据要求 26 个**一个不少**、理由非空、取值合法。
#: ⛔ Scope 不是装饰：它就是那些内联行级过滤**在模型上的名字**。
SCOPES: dict[Permission, tuple[str, str]] = {
    Permission.ORDER_CREATE: ("self", "建单是自己发起的动作，数据归属看行上的 shipper_id"),
    Permission.ORDER_READ_OWN: ("own", "货主只看自己名下的单（行级过滤）"),
    Permission.ORDER_READ_ASSIGNED: ("assigned", "司机只看派给自己的单（行级过滤）"),
    Permission.ORDER_READ_ALL: ("all", "派单员看全部：单店经营者，没有「只看自己」这一档"),
    Permission.ORDER_CANCEL_SHIPPER: ("own", "货主只能撤销自己名下的单（行级过滤按 shipper_id）"),
    Permission.ORDER_CANCEL_DISPATCHER: ("all", "派单员可撤任意单（含代客撤销）"),
    Permission.ORDER_RETURN: ("all", "退货动账本与库存，只有派单员能做，不分归属"),
    Permission.ORDER_RETURN_REQUEST: ("own", "货主只能给自己的单提退货申请"),
    Permission.ORDER_DELETE_CANCELLED: ("own", "软删进回收站：货主限自己的、派单员不限"),
    Permission.ORDER_DISPATCH: ("all", "派单是全局动作：要看到所有待派单与所有司机"),
    Permission.ORDER_RECALL: ("all", "撤回改派是全局动作：把单从某个司机手里收回来再派给别人"),
    Permission.ORDER_EDIT: ("all", "派单员代客改单，改的往往是别人名下的单，所以不分归属"),
    Permission.ORDER_COMPLETE_DRIVER: ("assigned", "司机只能完成派给自己的单"),
    Permission.ORDER_INTERNAL_NOTE: ("assigned", "内部备注写在单上，司机限自己的单"),
    Permission.ORDER_UPLOAD_DELIVERY: ("assigned", "送达照片只能传到派给自己的那张单上（行级过滤按 driver_id）"),
    Permission.PRODUCT_MANAGE: ("all", "商品是全局主数据，不分归属"),
    Permission.PRICE_RULE_MANAGE: ("all", "专属价按批发商维度，管理动作是全局的"),
    Permission.LEDGER_READ_OWN: ("own", "货主看自己的账（行级过滤）"),
    Permission.LEDGER_READ_ALL: ("all", "派单员看全部账：账本页是仪表盘"),
    Permission.LEDGER_EDIT: ("all", "手工记账写的是全局账本，不挂在某一个人的名下"),
    Permission.NOTIFICATION_READ: ("self", "消息按 recipient_id 过滤 —— 这里的「自己的」是收件人本人，比其他 own 更窄"),
    Permission.NOTIFICATION_MANAGE: ("all", "群发与管理面向所有人；个人消息在 NOTIFICATION_READ 那一档"),
    Permission.OPERATION_LOG_READ: ("all", "审计日志是全局只读视图，任何角色看到的都是同一份"),
    Permission.USER_MANAGE: ("all", "账号、司机名册、货主名册都是全局主数据，不分归属"),
    Permission.ORDER_PRODUCT_EDIT: ("all", "订单商品行是订单的一部分，编辑权归派单员"),
    Permission.STATS_READ: ("all", "报表是全店口径（营业额/毛利/司机绩效），没有「只看自己那份」的版本"),
}

#: 绕过矩阵的角色 → 为什么 + **什么时候删掉这一条**。
#:
#: ⛔ 这不是「漏判」，恰恰相反 —— 它原来是 `role_has_permission` 里一句
#:    `if key == UserRole.DISPATCHER.value: return True`：读代码的人只看到「恒真」，
#:    看不到**谁批的、为什么、什么时候该收回去**。装进这张表之后，例外变成一条可审计的声明，
#:    判据也钉得住「不许再在函数体里硬编码角色名」。
#: 三条纪律与证书例外表同：① 每条写理由；② 理由里写什么时候删；③ 没命中就是化石（判据报红）。
BYPASS_ROLES: dict[str, str] = {
    "dispatcher": (
        "派单员是这家店的**实际经营者**：所有业务动作他都要能替客户做（代下单、代撤销、代改单）。"
        "把他塞进 ROLE_PERMISSIONS 的每一格，只会让那 26 行越写越长、而且每加一个权限点都要记得加他一次，"
        "漏一次就是「派单员忽然做不了某件事」。**这家店出现第二个派单员角色、或引入「只读派单员」之后，"
        "删掉这一条，改成逐格授权。**"
    ),
}


def user_role_key(user: object) -> str:
    """从 ORM User 读取 `role` 并归一化，便于与 `UserRole.xxx.value`（小写）比较。

    解决部分库表/驱动中角色存成枚举名、大小写不一致时，`== 'shipper'` 判断失败、误报「当前角色不能创建订单」等问题。
    """
    r = getattr(user, "role", None)
    if isinstance(r, UserRole):
        return normalize_role_key(r.value)
    return normalize_role_key(str(r) if r is not None else "")


def normalize_role_key(role: str | None) -> str:
    """与 ROLE_PERMISSIONS 的键对齐：部分旧库/驱动会把枚举存成名称（如 DISPATCHER），此前会导致权限全否。"""
    if role is None:
        return ""
    s = str(role).strip()
    if not s:
        return ""
    for ur in UserRole:
        if s == ur.value or s == ur.name:
            return ur.value
    low = s.lower()
    if low in ROLE_PERMISSIONS:
        return low
    sup = s.upper()
    for ur in UserRole:
        if sup == ur.name:
            return ur.value
    return low


def role_has_permission(role: str, permission: Permission) -> bool:
    """派单员为最高业务权限：通过 `require_permission` 校验时一律放行（仍须有效登录）。"""
    key = normalize_role_key(role)
    if key in BYPASS_ROLES:
        return True
    perms = ROLE_PERMISSIONS.get(key)
    if not perms:
        return False
    return permission in perms
