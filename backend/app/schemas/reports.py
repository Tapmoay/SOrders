from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class ReportSeriesItem(BaseModel):
    label: str
    amount: Decimal = Decimal("0")
    orders: int = 0
    freight: Decimal = Decimal("0")


class ReportArrearsUnitItem(BaseModel):
    name: str
    amount: Decimal = Decimal("0")


class TurnoverReportOut(BaseModel):
    period_label: str
    total_amount: Decimal
    total_orders: int
    # ⚠️ 「司机运费支出」= **司机应得的钱**（Σ `driver_pay.pay_for_order`），
    #    不是 Σ `orders.freight_fee`（后者只是提成基数）。2026-09-19 审计 R12-M2：
    #    这一格原来累加订单运费，与「司机运费结算」页/司机绩效导出是两个数
    #    （同一天实测 47870.00 vs 24770.00），而两边都不报错。
    #    工资制司机不在这里（他们不按单拿钱）——与结算页的口径一致。
    total_freight: Decimal
    avg_order: Decimal = Decimal("0")
    series: list[ReportSeriesItem] = []
    # ---- 报表中心 v2：成本/毛利/货损/资金/撤销 ----
    #
    # ⚠️ **成本口径 2026-09-19 换过一次**（用户要求）：不再用订单行的 `cost_price_snapshot`
    #    （"下单那一刻的最新进货价"，进货价一涨就把旧库存的毛利压低），改成
    #    **入库流水的加权平均进货价**。唯一实现在 `services/cost_basis.py`，
    #    三级口径（期间均价／累计均价／下单快照兜底）与理由都写在那份文件的 docstring 里。
    cost_total: Decimal = Decimal("0")          # **参与毛利的行**的成本合计（毛利基数）
    # ⚠️ 毛利的**收入侧**必须与成本侧同一批行（2026-09-19 审计）：
    #    原先毛利 = 全部行的金额 − 只有成本行的成本合计 → 没成本的行以"0 成本、100% 毛利"进账，
    #    本机实测毛利 ¥64,213（真值 ¥25,969，虚高 2.5 倍）；界面那句"未计入的订单未参与毛利计算"
    #    正好说反。现在把"参与毛利计算的收入"单独报出来，毛利 = cost_covered_amount − cost_total。
    cost_covered_amount: Decimal = Decimal("0")  # **参与毛利的行**的金额合计（毛利收入侧）
    total_lines: int = 0                        # 订单行总数（覆盖率分母）
    cost_covered_lines: int = 0                 # 算得出成本的行数（覆盖率分子）
    #: 分子里有多少行用的是"入库加权平均进货价"（①②级）—— 这个数越大，毛利越接近真实成本。
    cost_avg_lines: int = 0
    #: 分子里有多少行退回了"下单时的成本快照"（③级：这个商品从来没按带价入过库，或老数据）。
    #  ⛔ 界面必须同时报这两个数：只报覆盖率的话，用户会以为整份毛利都已经是平均口径。
    cost_snapshot_lines: int = 0
    damage_qty: int = 0                         # 货损件数合计
    #: 货损金额 = Σ(成本快照 × 货损件数)。**故意不跟毛利一起改成均价**：送达那一刻就按当时的
    #  快照把损失写进了开销账与现金流水（`accounting_service`），是一笔已入账的历史金额。
    damage_amount: Decimal = Decimal("0")
    collected: Decimal = Decimal("0")           # 已收（paid=True 即算，含挂账结清）
    arrears_total: Decimal = Decimal("0")       # 挂账未收（paid=False）——与 collected 构成完整划分：两者之和恒等于营业额
    cancelled_orders: int = 0                   # 周期内已撤销订单数
    arrears_units: list[ReportArrearsUnitItem] = []   # 挂账未收按单位 TOP5


class ProductReportItem(BaseModel):
    product_name: str
    qty: int = 0
    amount: Decimal = Decimal("0")
    order_count: int = 0
    # ---- 报表中心 v2 ----
    cost: Decimal = Decimal("0")                # 该商品成本合计（参与毛利的行；单位成本见 cost_basis.py）
    damage_qty: int = 0
    damage_amount: Decimal = Decimal("0")
    #: 该商品**参与毛利**的收入（只有算得出成本的那些行）—— 2026-09-19 审计第十七轮补。
    #  ⛔ 少了它，"这个商品的毛利"就只能拿**全额**收入去减成本 → 系统性虚高
    #  （本机实测：唯一混合组 ttt 正确 305.50−260=45.50，页面/导出行印 587.50−260=327.50，7.2 倍）。
    #  毛利口径与营业纵览**同一句**：`covered_amount − cost`。
    covered_amount: Decimal = Decimal("0")
    #: 该商品有多少行算得出成本（算不出的行**不进毛利**，界面要如实说）
    covered_lines: int = 0


class ProductReportOut(BaseModel):
    period_label: str
    total_qty: int = 0
    total_amount: Decimal = Decimal("0")
    items: list[ProductReportItem] = []
    # ---- 报表中心 v2 ----
    cost_total: Decimal = Decimal("0")
    damage_qty: int = 0
    damage_amount: Decimal = Decimal("0")
    total_lines: int = 0
    cost_covered_lines: int = 0
    #: 参与毛利的收入合计（= Σ 参与毛利行的 line_total）。与 `cost_total` 相减才是毛利。
    #  2026-09-19 审计第十七轮补：缺了它，商品页与导出只能拿**全额**收入去减成本 → 毛利虚高。
    cost_covered_amount: Decimal = Decimal("0")
    #: 参与毛利的行里，用"入库加权平均进货价"的有多少行、退回"下单快照"的有多少行
    #  （口径与理由见 `TurnoverReportOut` 那两行的注释；两页必须同口径）。
    cost_avg_lines: int = 0
    cost_snapshot_lines: int = 0

class ProfitExpenseItem(BaseModel):
    """期间费用的一行（按开销分类聚合；顺序由服务端定：金额降序、同额按分类名）。"""

    category: str
    amount: Decimal = Decimal("0")


class ProfitDepreciationUncovered(BaseModel):
    """一台**算不出折旧**的车（缺购置信息）：单列，⛔ 不拿 0 或平均值替它猜。"""

    vehicle_id: int = 0
    plate_no: str = ""
    #: 缺哪几格（「没录购置价」/「没录购置日期」/「没录使用年限」），顺序固定
    reasons: list[str] = []


class ProfitReportOut(BaseModel):
    """经营利润表：一个窗口里「这月赚了多少」的完整链条。**只汇合，不新增事实。**

    ⛔ 六条恒等式由 `services/reports/profit_query.py::build_profit` **构造上**保证，
       判据 `_tools/qa/_check_profit_report.py` 与 `backend/tests/test_profit_report.py` 两边都钉：

       ① revenue_total == 营业纵览的 total_amount（同一 span）
       ② revenue_covered + revenue_uncovered == revenue_total
       ③ gross_profit == revenue_covered − cost_total（毛利两侧同一批行）
       ④ operating_profit == gross_profit − delivery_cost − operating_expense_total
          − depreciation_total − tax_total
       ⑤ delivery_cost == 营业纵览的 total_freight（司机应得，同一 span）
       ⑥ Σ operating_expenses[].amount == 区间内 expenses 合计
       ⑦ vat_payable == 销项税额 - 进项税额（价外税，单列一行，不进 operating_profit）；
          Σ tax_expenses[].amount == tax_total
    """

    period_label: str
    # ---- 收入侧 ----
    #: 营业收入（应收）—— 与营业纵览**同一批行、同一个数**（口径唯一实现 order_money.receivable）
    revenue_total: Decimal = Decimal("0")
    #: 「参与毛利」的收入：只有算得出成本的那些行（与营业纵览/商品经营同一句口径）
    revenue_covered: Decimal = Decimal("0")
    #: 没有成本数据、因此**不进毛利**的收入。⛔ 单列而不猜：既不按 0 成本、也不按平均成本替它算
    revenue_uncovered: Decimal = Decimal("0")
    # ---- 成本与毛利 ----
    cost_total: Decimal = Decimal("0")            # 参与毛利行的成本合计（cost_basis 三级口径）
    gross_profit: Decimal = Decimal("0")          # = revenue_covered − cost_total
    total_lines: int = 0                          # 覆盖率分母（订单行总数）
    covered_lines: int = 0                        # 覆盖率分子（算得出成本的行数）
    cost_avg_lines: int = 0                       # 分子里走"入库加权平均进货价"的行数
    cost_snapshot_lines: int = 0                  # 分子里退回"下单成本快照"的行数（⛔ 界面必须两个都报）
    # ---- 三级利润 ----
    #: 配送成本 = 司机应得的按单金额（`driver_pay.pay_for_order`）—— 与营业纵览的"司机运费支出"同源。
    #  ⛔ 不是 Σ orders.freight_fee（那只是提成基数；2026-09-19 审计实测虚高 93%）；
    #  ⛔ 也不含固定工资制司机的工资（他们不按单拿钱，见 notes）。
    delivery_cost: Decimal = Decimal("0")
    operating_expense_total: Decimal = Decimal("0")
    #: 区间内的开销（按分类），**已含货损开销** —— ⛔ 不要再单独扣一次 damage_amount
    operating_expenses: list[ProfitExpenseItem] = []
    #: 车辆折旧：Σ 有购置信息的车在窗口内摊到的折旧（唯一实现 `services/vehicle_depreciation.py`）。
    #  ⛔ 缺购置信息的车**不算进来**（它们的折旧是「算不出来」而不是 0），单列在下面。
    depreciation_total: Decimal = Decimal("0")
    #: 算得出折旧的那些车的**月折旧合计**（页面上写「N 台车 · 每月 ¥X」用；⛔ 不是窗口金额）
    depreciation_monthly_total: Decimal = Decimal("0")
    #: 算得出折旧的车数
    depreciation_vehicle_count: int = 0
    #: 缺购置信息、折旧没进上面那一格的车数（>0 时界面必须把名单摆出来）
    depreciation_uncovered_count: int = 0
    #: 未覆盖的车（车牌 + 缺哪几格）—— 明细 = 合计那一条只对**覆盖到的**车成立
    depreciation_uncovered: list[ProfitDepreciationUncovered] = []
    #: 税金及附加（FEAT-0014）：开销里分类名带「税」的那些笔（口径唯一判据 tax_query.is_tax_category）。
    #  ⛔ 它只可能来自真实开销：没有这种分类就是 0，不许按一个税率编一个数出来。
    #  ⛔ 这些笔在 operating_expenses 里**不再重复出现**（挖出来单列，否则会被扣两次）。
    tax_total: Decimal = Decimal("0")
    #: 应交增值税 = 销项税额 - 进项税额（价外税，FEAT-0014）：单列一行，⛔ 不进 operating_profit
    #  —— 代收代付的钱，不是这一期赚的钱。三个数都来自发票台账（唯一实现 tax_service.sum_taxes）。
    vat_output: Decimal = Decimal("0")
    vat_input: Decimal = Decimal("0")
    vat_payable: Decimal = Decimal("0")
    #: 税金及附加的明细（开销里分类名带「税」的那些笔）
    tax_expenses: list[ProfitExpenseItem] = []
    #: 营业利润 = 商品毛利 − 配送成本 − 期间费用 − 车辆折旧 − 税金及附加
    operating_profit: Decimal = Decimal("0")
    # ---- 资金与风险（与营业纵览同源，摆在利润旁边是为了"赚了但没收到钱"一眼可见 ----
    collected: Decimal = Decimal("0")
    arrears_total: Decimal = Decimal("0")
    cancelled_orders: int = 0
    damage_qty: int = 0
    damage_amount: Decimal = Decimal("0")
    #: 口径说明：凡「今天是 0」或「今天算不进」的地方都逐条写在这里（税、车辆折旧、固定工资、未覆盖收入、货损）
    notes: list[str] = []


class VehicleCostItem(BaseModel):
    """一台车在窗口里的三笔成本（折旧 / 这台车的开销 / 挂靠司机的配送成本）。

    ⛔ 没有收入：订单上只有司机、没有「这一台是哪台车拉的」这个事实，
       按台数或按比例摊出来的收入会被拿去决定这车留不留（摊错了比不摊更糟）。
    """

    vehicle_id: int = 0
    plate_no: str = ""
    is_active: bool = True
    driver_id: int | None = None
    driver_name: str = ""
    #: 折旧**算不算得出来**（缺购置价 / 购置日期 / 使用年限的车算不出来，不是 0）
    depreciation_covered: bool = False
    depreciation_uncovered_reasons: list[str] = []
    purchase_price: Decimal | None = None
    purchase_date: date | None = None
    useful_life_years: Decimal | None = None
    #: 台账里那一格的原值（留空 = None）；真正参与计提的是下面那一格
    residual_rate: Decimal | None = None
    #: 实际参与计提的残值率（台账留空 = 0）
    residual_rate_effective: Decimal = Decimal("0")
    #: 月折旧额；**算不出来是 None，不是 0**（0 是「已经提足」）
    monthly_depreciation: Decimal | None = None
    #: 这个窗口里摊到的折旧
    depreciation: Decimal = Decimal("0")
    #: 这台车的开销（按分类，金额降序）—— 与 `ProfitExpenseItem` 同一个形状
    expenses: list[ProfitExpenseItem] = []
    expense_total: Decimal = Decimal("0")
    #: 挂在这台车上的司机在窗口内的按单应付合计（工资制司机不按单拿钱，所以他们名下是 0）
    delivery_cost: Decimal = Decimal("0")
    #: = depreciation + expense_total + delivery_cost
    total_cost: Decimal = Decimal("0")


class VehicleCostReportOut(BaseModel):
    """车辆成本表：每台车在三笔成本上各花了多少。**只算成本，收入不按车拆。**

    恒等式由 `services/reports/vehicle_cost_query.py::build_vehicle_cost` **构造上**保证：

        total_cost == depreciation + expense_total + delivery_cost（逐车）
        total_cost == Σ per_vehicle[].total_cost（合计 = 逐车相加）
    """

    period_label: str
    date_from: str = ""
    date_to: str = ""
    vehicle_count: int = 0
    #: 折旧算得出来的车数
    covered_count: int = 0
    #: 缺购置信息、折旧没进上面那一格的车数（>0 时界面必须把名单摆出来）
    uncovered_count: int = 0
    depreciation_total: Decimal = Decimal("0")
    #: 算得出折旧的那些车的月折旧合计（⛔ 不是窗口金额）
    depreciation_monthly_total: Decimal = Decimal("0")
    expense_total: Decimal = Decimal("0")
    delivery_cost_total: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    per_vehicle: list[VehicleCostItem] = []
    #: 口径说明（为什么只算成本、哪笔开销进不来、换司机怎么算、折旧未覆盖、折旧不是现金）
    notes: list[str] = []


class CostCoverageProduct(BaseModel):
    """一个「从来没记过进货价」的商品（成本覆盖页的补录清单）。"""

    product_id: int = 0
    name: str = ""
    unit: str = ""
    stock: int = 0
    #: 台账上最近一次记过的进货价（⛔ 不是报表算成本时用的那个加权平均价）
    cost_price: Decimal | None = None
    is_active: bool = True


class CostCoverageReportOut(BaseModel):
    """成本覆盖表：这一段窗口里有多少收入因为「没有进货价」算不出成本。**只搬运，不重算。**

    ⛔ `missing_purchase_price` 是**商品**清单，`revenue_uncovered` 是**订单行**算出来的钱：
    两者相关但不等价（一笔算不出成本的收入也可能来自当期没进货、其实有进价的商品），
    所以这里并排列出来，⛔ 不写成比例、也不说「这笔钱就是这些商品造成的」。
    """

    period_label: str
    date_from: str = ""
    date_to: str = ""
    #: 这一段窗口的营业额（与营业纵览同一个数）
    revenue_total: Decimal = Decimal("0")
    #: 参与毛利的收入（成本 > 0 的那些行）
    revenue_covered: Decimal = Decimal("0")
    #: 算不出成本的收入 = 营业额 − 参与毛利的收入（不进毛利）
    revenue_uncovered: Decimal = Decimal("0")
    #: 交付过的订单行数 / 其中算得出成本的
    total_lines: int = 0
    covered_lines: int = 0
    #: 参与毛利的那几行里，按入库加权均价算的 / 按成本快照算的
    cost_avg_lines: int = 0
    cost_snapshot_lines: int = 0
    missing_purchase_price_count: int = 0
    missing_purchase_price: list[CostCoverageProduct] = []
    #: 口径说明（算不出成本怎么判、两份清单为什么不相等、补录入口在哪）
    notes: list[str] = []
