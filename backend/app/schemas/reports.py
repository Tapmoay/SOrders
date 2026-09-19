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
    cost_total: Decimal = Decimal("0")          # 有成本快照订单行的成本合计（毛利基数）
    # ⚠️ 毛利的**收入侧**必须与成本侧同一批行（2026-09-19 审计）：
    #    原先毛利 = 全部行的金额 − 只有成本行的成本合计 → 没成本快照的行以"0 成本、100% 毛利"进账，
    #    本机实测毛利 ¥64,213（真值 ¥25,969，虚高 2.5 倍）；界面那句"未计入的订单未参与毛利计算"
    #    正好说反。现在把"参与毛利计算的收入"单独报出来，毛利 = cost_covered_amount − cost_total。
    cost_covered_amount: Decimal = Decimal("0")  # 有成本快照订单行的**金额**合计（毛利收入侧）
    total_lines: int = 0                        # 订单行总数（覆盖率分母）
    cost_covered_lines: int = 0                 # cost_price_snapshot>0 的行数（覆盖率分子）
    damage_qty: int = 0                         # 货损件数合计
    damage_amount: Decimal = Decimal("0")       # 货损金额 = Σ(成本快照×货损件数)
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
    cost: Decimal = Decimal("0")                # 该商品成本合计（有快照行）
    damage_qty: int = 0
    damage_amount: Decimal = Decimal("0")
    #: 该商品**参与毛利**的收入（只有带成本快照的那些行）—— 2026-09-19 审计第十七轮补。
    #  ⛔ 少了它，"这个商品的毛利"就只能拿**全额**收入去减成本 → 系统性虚高
    #  （本机实测：唯一混合组 ttt 正确 305.50−260=45.50，页面/导出行印 587.50−260=327.50，7.2 倍）。
    #  毛利口径与营业纵览**同一句**：`covered_amount − cost`。
    covered_amount: Decimal = Decimal("0")
    #: 该商品有多少行带成本快照（没带的行**不进毛利**，界面要如实说）
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
    #: 参与毛利的收入合计（= Σ 有成本快照行的 line_total）。与 `cost_total` 相减才是毛利。
    #  2026-09-19 审计第十七轮补：缺了它，商品页与导出只能拿**全额**收入去减成本 → 毛利虚高。
    cost_covered_amount: Decimal = Decimal("0")
