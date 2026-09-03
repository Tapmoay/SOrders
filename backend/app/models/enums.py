import enum


class UserRole(str, enum.Enum):
    SHIPPER = "shipper"
    DRIVER = "driver"
    DISPATCHER = "dispatcher"


class OrderStatus(str, enum.Enum):
    """待派单 → 已派单（已派未接） → 已接单 → 已送达；另含已撤销与撤回后的待派单。"""

    PENDING_DISPATCH = "PENDING_DISPATCH"
    DISPATCHED = "DISPATCHED"
    ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class VehicleType(str, enum.Enum):
    SMALL = "small"
    LARGE = "large"
    TRAILER = "trailer"


class BillingMode(str, enum.Enum):
    SALARY = "salary"
    PIECE = "piece"


class LedgerSource(str, enum.Enum):
    ORDER = "order"
    MANUAL = "manual"
    REFUND = "refund"


class OperationAction(str, enum.Enum):
    """操作日志动作（与 OperationLog.action 对应，可存枚举名或自定义字符串）。"""

    ORDER_CREATE = "ORDER_CREATE"
    ORDER_UPDATE = "ORDER_UPDATE"
    ORDER_DISPATCH = "ORDER_DISPATCH"
    ORDER_RECALL = "ORDER_RECALL"
    ORDER_COMPLETE = "ORDER_COMPLETE"
    ORDER_CANCEL = "ORDER_CANCEL"
    ORDER_EXCEPTION = "ORDER_EXCEPTION"
    ORDER_FREIGHT = "ORDER_FREIGHT"
    ORDER_SPLIT = "ORDER_SPLIT"
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

class CustomerKind(str, enum.Enum):
    REGISTERED = "registered"
    TMP = "tmp"


class DriverBillType(str, enum.Enum):
    PIECE = "piece"
    SALARY = "salary"


class DriverBillStatus(str, enum.Enum):
    OPEN = "open"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class SettlementStatus(str, enum.Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    PAID = "paid"
    CANCELLED = "cancelled"


class CashFlowDirection(str, enum.Enum):
    IN = "in"
    OUT = "out"


class CashFlowBizType(str, enum.Enum):
    RECEIPT_CASH = "RECEIPT_CASH"
    RECEIPT_TRANSFER = "RECEIPT_TRANSFER"
    RECEIPT_ARREARS = "RECEIPT_ARREARS"
    RECEIPT_PREPAID = "RECEIPT_PREPAID"
    PAYMENT_DRIVER = "PAYMENT_DRIVER"
    PAYMENT_SALARY = "PAYMENT_SALARY"
    PAYMENT_DRIVER_ADVANCE = "PAYMENT_DRIVER_ADVANCE"
    PAYMENT_SUPPLIER = "PAYMENT_SUPPLIER"
    PAYMENT_TAX = "PAYMENT_TAX"
    EXPENSE_FUEL = "EXPENSE_FUEL"
    EXPENSE_REPAIR = "EXPENSE_REPAIR"
    EXPENSE_TOLL = "EXPENSE_TOLL"
    EXPENSE_PARKING = "EXPENSE_PARKING"
    EXPENSE_FINE = "EXPENSE_FINE"
    EXPENSE_INSURANCE = "EXPENSE_INSURANCE"
    EXPENSE_LOSS = "EXPENSE_LOSS"
    EXPENSE_OTHER = "EXPENSE_OTHER"
    REFUND_CUSTOMER = "REFUND_CUSTOMER"
    REFUND_DRIVER = "REFUND_DRIVER"
    ADJUST = "ADJUST"


class ExpenseCategory(str, enum.Enum):
    FUEL = "fuel"
    REPAIR = "repair"
    TOLL = "toll"
    PARKING = "parking"
    FINE = "fine"
    INSURANCE = "insurance"
    LOSS = "loss"
    OTHER = "other"


class ReceiptSettleMode(str, enum.Enum):
    ITEMIZED = "itemized"
    ROLLING = "rolling"