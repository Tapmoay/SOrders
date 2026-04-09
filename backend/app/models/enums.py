import enum


class UserRole(str, enum.Enum):
    SHIPPER = "shipper"
    DRIVER = "driver"
    DISPATCHER = "dispatcher"


class OrderStatus(str, enum.Enum):
    """派单中 → 已接单 → 已送达；另含已撤销与撤回后的派单中。"""

    PENDING_DISPATCH = "PENDING_DISPATCH"
    ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class LedgerSource(str, enum.Enum):
    ORDER = "order"
    MANUAL = "manual"


class OperationAction(str, enum.Enum):
    """操作日志动作（与 OperationLog.action 对应，可存枚举名或自定义字符串）。"""

    ORDER_CREATE = "ORDER_CREATE"
    ORDER_UPDATE = "ORDER_UPDATE"
    ORDER_DISPATCH = "ORDER_DISPATCH"
    ORDER_RECALL = "ORDER_RECALL"
    ORDER_COMPLETE = "ORDER_COMPLETE"
    ORDER_CANCEL = "ORDER_CANCEL"
    ORDER_EXCEPTION = "ORDER_EXCEPTION"
    ORDER_LINE_ADD = "ORDER_LINE_ADD"
    ORDER_LINE_UPDATE = "ORDER_LINE_UPDATE"
    ORDER_LINE_DELETE = "ORDER_LINE_DELETE"
    LEDGER_CREATE = "LEDGER_CREATE"
    LEDGER_UPDATE = "LEDGER_UPDATE"
    LEDGER_DELETE = "LEDGER_DELETE"
    PRODUCT_CREATE = "PRODUCT_CREATE"
    PRICE_RULE_UPSERT = "PRICE_RULE_UPSERT"
    USER_CREATE = "USER_CREATE"
    USER_UPDATE = "USER_UPDATE"
