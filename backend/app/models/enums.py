import enum


class UserRole(str, enum.Enum):
    SHIPPER = "shipper"
    DRIVER = "driver"
    DISPATCHER = "dispatcher"


class OrderStatus(str, enum.Enum):
    """待派单 → 已派单（已派未接） → 已接单 → 已送达；另含已撤销、已退货与撤回后的待派单。"""

    PENDING_DISPATCH = "PENDING_DISPATCH"
    DISPATCHED = "DISPATCHED"
    ACCEPTED = "ACCEPTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    # 已退货（2026-09-20 用户拍板新增这一档）：货物送达之后客户又把货退回来。
    #
    # ⛔ **不是「已撤销」**（用户明确选了"新增一个状态"，不是沿用）：
    #    · 已撤销 = 这张单**没发生过**（还在待派/已派未接时撤掉，货没出门）；
    #    · 已退货 = 单**发生过**（送了、入了账、司机也拿到了那一单的钱），事后货退回来了。
    #    混成一个状态会让「营业额为什么要减」「司机那单的钱还在不在」都答不上来。
    # 只有**整单退完**才进这个状态；退了一部分仍然留在 DELIVERED（界面打「部分退货」标记），
    # 理由同账本：一张单一个结论，部分退货的"结论"是"还欠着一部分"。
    RETURNED = "RETURNED"


class ReturnRequestStatus(str, enum.Enum):
    """货主申请退货的四种归宿（2026-09-21）。

    ⚠️ **没有「已删除」这一档**：撤回（`WITHDRAWN`）与删除是两件事 ——
       撤回是"我不想退了"（申请仍然留在这张单的历史里，派单员看得到"他提过又撤了"），
       删除走 `SoftDeleteMixin`（`is_deleted`）。把撤回做成删除，后果是货主反复提了又撤，
       派单员那边什么都看不见，只能看到"这张单一直没人申请过"。
    """

    #: 等派单员处理（**同一张单同时只允许一条**，见 `services/order_return_request.py`）
    PENDING = "pending"
    #: 派单员已经照这张申请**实际退过货**了（钱、库存、订单状态都在那一刻才变）
    DONE = "done"
    #: 派单员驳回（必带理由 —— 货主凭什么被拒，得能回查）
    REJECTED = "rejected"
    #: 货主自己撤回（申请作废，但记录留着）
    WITHDRAWN = "withdrawn"
    #: **派单员直接退了货**（2026-09-21 用户拍板：「把规则改成派单员退货之后，自动取消申请」）。
    #:
    #: ⛔ 为什么不是 `DONE`：`DONE` 的语义是"**照这张申请**办的"；而派单员走订单管理那条直连退货时，
    #:    退的件数/商品**不一定**等于申请上写的（他退 3 件、申请写 2 件）。
    #:    标成 DONE 就等于替他把这个差异说成"一致"，而事后谁都查不出来 ——
    #:    本仓库最贵的一类错就是这种"把差异盖掉"。所以单独一档，中文写明是"直接退货"，
    #:    件数与结果以**订单/账本**为准（"退了多少"只有一处口径），差异写进审计与站内信。
    CLOSED = "closed"


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
    # 退货红冲（2026-09-20）：客户把货退回来 → 按行写**负金额**红冲行（售价冲减 + 负成本快照）。
    #
    # ⛔ 为什么不复用 REFUND：`ledgers` 上有唯一约束 `(order_product_id, source)`，而
    #    REFUND 那一格已经被**货损成本回冲行**占着（`apply_damage_accounting`，一单一行）。
    #    复用会直接撞唯一约束（500），或者更糟——把两次退货累加到货损那一行上。
    # 语义上也该分开：REFUND = 货损（货没回来，只冲成本），RETURN = 退货（货回来了，营收与成本一起冲）。
    # 同一条行上的**多次退货累加到同一行**（数量与金额一起加），所以唯一约束仍然成立。
    RETURN = "return"


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
    # 退货（2026-09-20）：动了钱（红冲营收 + 可能退现）也动了库存，必须留痕。
    ORDER_RETURN = "ORDER_RETURN"
    # 货主**申请**退货（2026-09-21 用户要求：「批发商只是一个申请，派单员才是实际性的操作」）。
    #
    # ⛔ 为什么不复用 `ORDER_RETURN`：这两个动作要回答的是**两个不同的问题** ——
    #    「这张单的货是谁退的、退了多少钱」（ORDER_RETURN，钱和库存都动了）
    #    和「这个货主什么时候提过退货、后来是被办的还是被驳的」（下面三个码，一分钱没动）。
    #    合成一个的后果是审计页上分不出"真的退了货"和"只是提了个申请"，
    #    而这恰恰是这一轮新增流程的**全部意义**（申请与执行是两个人、两个时刻）。
    # 拆三个而不是一个：驳回与撤回是**两个不同的人**做的相反的决定（派单员驳回 / 货主自己撤回），
    # 出问题时第一个要问的就是"这是谁决定的"。
    ORDER_RETURN_REQUEST = "ORDER_RETURN_REQUEST"
    ORDER_RETURN_REQUEST_REJECT = "ORDER_RETURN_REQUEST_REJECT"
    ORDER_RETURN_REQUEST_WITHDRAW = "ORDER_RETURN_REQUEST_WITHDRAW"
    #: 派单员**直接退了货**，那张待处理申请被自动关掉（2026-09-21 用户拍板）。
    #: 单独一个码：审计页上要能回答"这张申请为什么没被办理就消失了"——
    #: 它既不是货主撤回的，也不是派单员驳回的，而是**另一条路把这件事做完了**。
    ORDER_RETURN_REQUEST_CLOSE = "ORDER_RETURN_REQUEST_CLOSE"
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
    # 开销分类名册（2026-09-20，用户「开销分类……也有个分类管理」）：与商品/地点分类同一类东西
    # （主数据、管顺序），但它还决定**卡片上突出哪一项关联**（vehicle/driver/order/none）——
    # 改它会改所有人看开销的方式，必须留痕。
    EXPENSE_CATEGORY_UPSERT = "EXPENSE_CATEGORY_UPSERT"
    EXPENSE_CATEGORY_DELETE = "EXPENSE_CATEGORY_DELETE"
    EXPENSE_CATEGORY_REORDER = "EXPENSE_CATEGORY_REORDER"
    # 商品可见范围（v3.43）：白名单直接决定"某个货主/批发商在选品页能看到什么"，
    # 本质是一种授权 —— 改动必须能回查"是谁给谁开了哪些商品"。
    PRODUCT_VISIBILITY_SET = "PRODUCT_VISIBILITY_SET"
    # 常用共享地点自动进「我的地点」（v3.43）：这是**系统替用户改了他自己的库**，
    # 必须留痕 —— 否则他下次看到多出一条来源不明的地点，只能猜是谁加的。
    PLACE_AUTO_ADDED = "PLACE_AUTO_ADDED"
    # 共享地点库的**管理**（2026-09-19 用户要求「派单员可以改名称…也可以撤销某些共享地址…
    # 或者直接删除」）：这张表**全库共用**，改/撤/删动的是**所有人**都要看的那一条导航信息。
    # 拆三个动作码而不是一个 —— 审计页上「有人改了个名字」和「有人删掉一条、别人再也选不到」
    # 是严重程度完全不同的两件事，合成一个就分不出来了。
    # （「设为共享地址」也单独一个码：它把一条**私有**地点变成了所有人可见的记录。）
    PLACE_UPDATE = "PLACE_UPDATE"
    PLACE_PUBLISH = "PLACE_PUBLISH"
    PLACE_DEMOTE = "PLACE_DEMOTE"
    PLACE_DELETE = "PLACE_DELETE"
    #: 从回收站把共享地点放回来（2026-09-19 用户要求"删除一律软删"，那就必须有恢复）。
    PLACE_RESTORE = "PLACE_RESTORE"
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
    # 运费分类名册（2026-09-21）：运费模板与计费规则**共用**的一套分类。
    # 它决定"这类货走哪条价目/每单给司机多少"——改一个分类名或顺序会影响报价口径，
    # 所以要能回答"这个分类是谁建的、谁改的、谁删的"。
    FREIGHT_CATEGORY_UPSERT = "FREIGHT_CATEGORY_UPSERT"
    FREIGHT_CATEGORY_DELETE = "FREIGHT_CATEGORY_DELETE"
    FREIGHT_CATEGORY_REORDER = "FREIGHT_CATEGORY_REORDER"
    # 派单员**手动定价**（2026-09-21）：这一单没匹配到任何价目 → 没有运费 → 待定价，
    # 他手填一个数，并（可选）把这条路线+价目**沉淀**成模板。这是一个改钱的动作，
    # 必须能回答"这单的运费是谁定的、什么时候定的、当时说了什么"。
    ORDER_FREIGHT_PRICE = "ORDER_FREIGHT_PRICE"
    # 预订单 / 订单模板（2026-09-22 用户要求：「预设好的订单，参数没有变直接下单」）。
    # 它自己不生成订单（下单仍走 `POST /orders`），但**预设单会变成真订单** ——
    # 所以"这条预设是谁建的、谁改的、谁删的"必须查得到：一张被人改过的预设单
    # 会让以后每一次"一键下单"都按改后的参数生成，而界面上完全看不出来。
    ORDER_TEMPLATE_UPSERT = "ORDER_TEMPLATE_UPSERT"
    ORDER_TEMPLATE_DELETE = "ORDER_TEMPLATE_DELETE"
    ORDER_TEMPLATE_RESTORE = "ORDER_TEMPLATE_RESTORE"
    # 批发商自记账核销（2026-09-20 用户要求）：他向下游货主收钱时在自己账本上核销。
    # ⛔ 这本账**不写** cash_flows / orders.paid / ledgers（见 `models/shipper_settlement.py`），
    #    所以 operation_logs 是**唯一**能回答"这笔核销谁在什么时候记的、撤的"的地方 ——
    #    三个动作码都要有，唯独不能不记。
    # 拆三个：要回答的是三个不同的问题 ——「他向谁收了多少钱」「谁把这笔核销撤了」
    # 「谁又把撤掉的放回来了」。合成一个，审计页上只能看到一团。
    SHIPPER_SETTLE_CREATE = "SHIPPER_SETTLE_CREATE"
    SHIPPER_SETTLE_REVOKE = "SHIPPER_SETTLE_REVOKE"
    SHIPPER_SETTLE_RESTORE = "SHIPPER_SETTLE_RESTORE"
    # 供应商 / 厂商档案 + 应付款（2026-09-22 用户要求「给供应商付尾款」「采购设备」「邮费」）。
    # ⛔ 这一组**必须**留痕，而且是本项目里最该留痕的一组之一：它同时决定了
    #    「我们还欠他多少」（应付单）与「钱什么时候出去的」（付款流水）。
    #    档案改名不影响历史（欠款按 `supplier_id` 挂，不按名字），但**改金额**会 —— 那是钱。
    #
    # 拆三组（档案 / 应付单 / 付款）而不是一组：审计页上要能分开回答
    # 「这个供应商是谁建的、名字谁改的」（主数据）、
    # 「这笔欠款是谁录的、金额谁改的」（单据）、
    # 「这笔钱谁付的、谁撤的」（钱）。合成一个，三件事会混成一团，而它们的严重程度完全不同。
    SUPPLIER_UPSERT = "SUPPLIER_UPSERT"
    SUPPLIER_DELETE = "SUPPLIER_DELETE"
    SUPPLIER_RESTORE = "SUPPLIER_RESTORE"
    SUPPLIER_PAYABLE_UPSERT = "SUPPLIER_PAYABLE_UPSERT"
    SUPPLIER_PAYABLE_DELETE = "SUPPLIER_PAYABLE_DELETE"
    SUPPLIER_PAYABLE_RESTORE = "SUPPLIER_PAYABLE_RESTORE"
    #: 付一笔款（写一行 `cash_flows` OUT）。钱真的出去了，单独一个码。
    SUPPLIER_PAYMENT_CREATE = "SUPPLIER_PAYMENT_CREATE"
    #: **撤销**一笔付款（软删那一行流水）。⛔ 不复用 `SUPPLIER_PAYMENT_CREATE`：
    #: 「这笔钱付出去了」和「这笔钱其实不算」是相反的结论，审计页必须一眼分得出。
    SUPPLIER_PAYMENT_CANCEL = "SUPPLIER_PAYMENT_CANCEL"
    #: 把撤掉的付款放回来。
    SUPPLIER_PAYMENT_RESTORE = "SUPPLIER_PAYMENT_RESTORE"

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


# ⛔ `ExpenseCategory` 枚举**已删除**（2026-09-20）：开销分类改成**可维护名册**
#    （`models/expense_category.py` + `/expense-categories`），`expenses.category`
#    存的是名册里的名字（中文，≤32 字）。留着这个枚举，下一个人还会拿它当"合法取值表"，
#    于是"用户新加的分类存不进去"这件事会换个地方再发生一次。
#    ⚠️ 老英文键（fuel/repair/…）由 `core/schema_bootstrap.py` 的迁移翻成中文名；
#    `services/accounting_service.py` 的现金流水口径映射**两种都认**（认不出落 OTHER）。


class ReceiptSettleMode(str, enum.Enum):
    ITEMIZED = "itemized"
    ROLLING = "rolling"