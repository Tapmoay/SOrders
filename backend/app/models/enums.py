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
    ORDER_DELETE = "ORDER_DELETE"
    ORDER_RESTORE = "ORDER_RESTORE"
    ORDER_EXCEPTION = "ORDER_EXCEPTION"
    ORDER_FREIGHT = "ORDER_FREIGHT"
    ORDER_SPLIT = "ORDER_SPLIT"
    ORDER_LINE_ADD = "ORDER_LINE_ADD"
    ORDER_LINE_UPDATE = "ORDER_LINE_UPDATE"
    ORDER_LINE_DELETE = "ORDER_LINE_DELETE"
    LEDGER_CREATE = "LEDGER_CREATE"
    LEDGER_UPDATE = "LEDGER_UPDATE"
    LEDGER_DELETE = "LEDGER_DELETE"
    # 钱的写操作必须留痕（2026-09-19 审计）：下面这几条以前**一条日志都不写**，
    # 于是"这笔收款谁录的""这张 675 谁点的付款"事后无法回答；而
    # `docs/ACCOUNTING_V2_DESIGN.md` §4.10 明确写着「所有写账接口都要写 operation_logs」。
    RECEIPT_CREATE = "RECEIPT_CREATE"
    SETTLEMENT_CREATE = "SETTLEMENT_CREATE"
    SETTLEMENT_STATUS = "SETTLEMENT_STATUS"
    EXPENSE_CREATE = "EXPENSE_CREATE"
    DRIVER_BILL_GENERATE = "DRIVER_BILL_GENERATE"
    CUSTOMER_MERGE = "CUSTOMER_MERGE"
    PRODUCT_CREATE = "PRODUCT_CREATE"
    PRODUCT_UPDATE = "PRODUCT_UPDATE"
    PRODUCT_DELETE = "PRODUCT_DELETE"
    PRODUCT_RESTORE = "PRODUCT_RESTORE"
    PRICE_RULE_UPSERT = "PRICE_RULE_UPSERT"
    USER_CREATE = "USER_CREATE"
    USER_UPDATE = "USER_UPDATE"
    USER_DELETE = "USER_DELETE"
    USER_RESTORE = "USER_RESTORE"
    # 库存调整（出入库流水）：和改价同一类——动了货/钱的账，月底对不上要能回查。
    # 以前**一条都不写**，审计页上永远看不到"谁把库存改了多少"（v3.29 补上）。
    INVENTORY_ADJUST = "INVENTORY_ADJUST"
    # AI 撤回：用户点了「撤回」，把一次 AI 写操作回滚掉。单独一个动作码，
    # 是为了让"这次是谁撤的、撤掉了哪一条"在审计页上一眼可辨（v3.26）。
    AI_UNDO = "AI_UNDO"
    # 司机计费规则（v3.36）：改的是"他以后怎么算钱"，属于必须留痕的一类。
    # 拆两个动作码而不是一个，是因为要回答的是两个不同的问题：
    # 「这份规则被谁改成什么样了」和「谁的计费规则被换了」——合成一个，审计页上只能看到一团。
    DRIVER_RULE_UPSERT = "DRIVER_RULE_UPSERT"
    DRIVER_RULE_ATTACH = "DRIVER_RULE_ATTACH"
    # 司机到场补录导航信息（2026-09-18）：单独一个动作码，因为要回答的是
    # 「这个坐标是谁标的、标在哪一单上」——它会被写进全库共享地点库，
    # 混在 ORDER_UPDATE 里就再也分不出"改地址"和"标坐标"了。
    ORDER_NAVIGATION_FILL = "ORDER_NAVIGATION_FILL"
    # 商品分类名册（v3.43）：改的是"下单页左侧那一列叫什么、按什么顺序"，
    # 会影响所有人下单时的选品体验，属于必须留痕的主数据。
    PRODUCT_CATEGORY_UPSERT = "PRODUCT_CATEGORY_UPSERT"
    PRODUCT_CATEGORY_DELETE = "PRODUCT_CATEGORY_DELETE"
    PRODUCT_CATEGORY_REORDER = "PRODUCT_CATEGORY_REORDER"
    # 地点分类名册（2026-09-19）：与商品分类同一类东西（主数据、管顺序），
    # 但**按人分区**（每个人管自己地址库左侧那一列）。单独一套动作码而不是复用商品分类那两个：
    # 审计页上「改了商品分类」和「改了自己的地点分类」是两件事，混在一起就分不出是哪一件了。
    PLACE_CATEGORY_UPSERT = "PLACE_CATEGORY_UPSERT"
    PLACE_CATEGORY_DELETE = "PLACE_CATEGORY_DELETE"
    PLACE_CATEGORY_REORDER = "PLACE_CATEGORY_REORDER"
    # 商品可见范围（v3.43）：白名单直接决定"某个货主/批发商在选品页能看到什么"，
    # 本质是一种授权 —— 改动必须能回查"是谁给谁开了哪些商品"。
    PRODUCT_VISIBILITY_SET = "PRODUCT_VISIBILITY_SET"
    # 常用共享地点自动进「我的地点」（v3.43）：这是**系统替用户改了他自己的库**，
    # 必须留痕 —— 否则他下次看到多出一条来源不明的地点，只能猜是谁加的。
    PLACE_AUTO_ADDED = "PLACE_AUTO_ADDED"
    # 车辆台账（v3.44）：车牌/车型会出现在记支出、算油耗选车的地方，
    # 而"这辆车现在挂在谁名下"直接决定派单时能不能选到它 —— 改车辆必须留痕。
    # 拆两个动作码：要回答的是两个不同的问题 ——「这辆车被谁改成什么样了」
    # 和「谁把车从张三名下拿走挂到李四名下了」。合成一个，审计页上只能看到一团。
    VEHICLE_UPSERT = "VEHICLE_UPSERT"
    VEHICLE_DRIVER_SET = "VEHICLE_DRIVER_SET"
    # 挂账单位（2026-09-19 审计 R14-1）：**钱挂在谁名下**这件事原来一条日志都不写
    # （`arrears.py` 四个写端点、0 次 `write_log`）——单位改名/删掉之后，
    # 历史欠款按 `arrears_unit_name` 快照分组，谁也说不清"这名字是谁改的、什么时候改的"。
    # 真机实证：用 AI 建了一个挂账单位，库里多了一行、审计页上却什么都没有。
    ARREARS_UNIT_UPSERT = "ARREARS_UNIT_UPSERT"
    ARREARS_UNIT_DELETE = "ARREARS_UNIT_DELETE"
    ARREARS_UNIT_RESTORE = "ARREARS_UNIT_RESTORE"
    # 运费模板（同上一轮审计）：它是派单填运费的**参考价**，改一个数字会影响所有人报价，
    # 而原来同样一次日志都不写。
    FREIGHT_TEMPLATE_UPSERT = "FREIGHT_TEMPLATE_UPSERT"
    FREIGHT_TEMPLATE_DELETE = "FREIGHT_TEMPLATE_DELETE"
    FREIGHT_TEMPLATE_RESTORE = "FREIGHT_TEMPLATE_RESTORE"

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