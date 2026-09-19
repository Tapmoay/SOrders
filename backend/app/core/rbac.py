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
    if key == UserRole.DISPATCHER.value:
        return True
    perms = ROLE_PERMISSIONS.get(key)
    if not perms:
        return False
    return permission in perms
