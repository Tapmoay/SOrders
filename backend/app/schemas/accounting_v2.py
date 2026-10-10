"""账本 V2（P0）：客户档案 / 司机应付明细 / 客户收款单 / 司机结算单 / 开销单 / 资金流水 / 车辆台账。"""

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.business_time import business_local
from app.core.phone import OptionalContactPhone
from app.models.enums import (
    CashFlowBizType,
    CashFlowDirection,
    CustomerKind,
    DriverBillStatus,
    DriverBillType,
    ReceiptSettleMode,
    SettlementStatus,
)
from app.schemas.money import MoneyInput

#: 归属月份只接受 `YYYY-MM`。
#:
#: ⚠️ 为什么必须校验（2026-09-18 实测）：`driver_bills` 的**列表**查询参数带着
#: `pattern=^\d{4}-\d{2}$`，而**生成**接口的 `month` 原来是一个自由字符串。
#: 于是一次 `POST /driver-bills/generate {"month": "fuzz-xxx"}` 会造出一批
#: "月份不是月份"的工资单：任何界面按月份都查不到它们，结算单也永远收不进它们
#: （结算按 month 取 OPEN 明细）——**生成了、但结不掉的幽灵工资单**。
#: 实测一次模糊测试就造出 70 张、合计 34.5 万。
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MONTH_TIP = "月份要写成 YYYY-MM（例如 2026-09）"


def validate_month(v: str) -> str:
    """月份格式校验：报错必须是**中文**且带正确写法（英文 422 用户看不懂）。

    ⚠️ 接收的是**原始输入**（`mode="before"`）：写成 `mode="after"` 时，`month=202609`
    这种数字会先被 Pydantic 拦成 `string_type`（英文），用户看不到下面这句中文提示。

    ⚠️ **上界：不能晚于本月**（2026-09-19 审计 R13-D3）。原来只校验格式，
    于是 9 月就能造出 10 月的工资单——而账单**没有删除入口**（`DriverBillStatus.CANCELLED`
    只有保留任务会写），它会被结算单收走、被真金白银付出去；等 10 月真的到了，
    幂等逻辑又会跳过重算，金额定格在造单当时（期间离职/调薪都不纠正）。
    本机库里就躺着这样一张：`driver_bills id=8`，`month='2026-10'`、6500 元、`created_at=2026-09-15`。
    """
    s = str(v).strip() if v is not None else ""
    if not MONTH_RE.match(s):
        raise ValueError(MONTH_TIP)
    now_month = business_local(datetime.now(timezone.utc)).strftime("%Y-%m")
    if s > now_month:
        raise ValueError(
            f"月份不能晚于本月（现在是 {now_month}）。{s} 还没到，"
            "提前生成会造出一笔现在就能付款的应付，而且账单没有删除入口。"
        )
    return s


# ---------------- 客户档案 ----------------
class CustomerCreate(MoneyInput):
    #: `registered`（有账号的货主）/ `tmp`（散客）。⚠️ 原来是自由字符串：
    #: 模糊测试把 8000 个字符塞进 kind 也是 200，而列宽是 String(12)——生产 MySQL
    #: 直接 Data too long。更要紧的是**未知取值会被当成临客**（`accounting_service`
    #: 按 kind 分流：registered→按 user_id，其余→按名称），错得无声无息。
    kind: CustomerKind = CustomerKind.TMP
    user_id: int | None = None
    name: str = Field(..., min_length=1, max_length=128)
    # 客户电话：规则在 `app/core/phone.py`（去空格后 7~12 位数字，空/None = 没填）
    phone: OptionalContactPhone = Field(None, max_length=32)
    is_member: bool = False
    arrears_unit_id: int | None = None

    @model_validator(mode="after")
    def _tmp_need_phone_or_name(self) -> "CustomerCreate":
        if self.kind == "tmp" and not (self.phone or "").strip() and not self.name.strip():
            raise ValueError("散客需提供名称")
        return self


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    user_id: int | None = None
    name: str
    phone: str | None = None
    is_member: bool = False
    arrears_unit_id: int | None = None
    created_at: datetime | None = None


class CustomerMergeBody(BaseModel):
    keep_id: int
    merge_ids: list[int] = Field(..., min_length=1)


# ---------------- 司机应付明细 ----------------
class DriverBillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    driver_id: int
    bill_type: DriverBillType
    order_id: int | None = None
    month: str
    amount: Decimal
    status: DriverBillStatus
    settled_doc_id: int | None = None
    note: str = ""
    driver_name: str | None = None
    order_no: str | None = None
    # v3.36：这一单是按哪份计费规则算的、两件各多少（账单页把账摆开给人看，不再只给一个总数）
    rule_id: int | None = None
    rule_name: str = ""
    piece_amount: Decimal | None = None
    commission_amount: Decimal | None = None

    @field_validator("note", "rule_name", mode="before")
    @classmethod
    def _null_str_to_empty(cls, v: object) -> object:
        """`NULL` 归一成空串（2026-09-19 审计 R12-L10）。

        这两列在模型里是 `Mapped[str]`（NOT NULL），但它们是 **v3.36 才加的列**，
        由 `schema_bootstrap` 用 `ALTER TABLE ADD COLUMN` 补出来（`rule_name` 带了
        `DEFAULT ''`，`note` 更早、也带默认）——**生产库里只要有一行为 NULL，
        整个司机账单列表就会 500**（`ResponseValidationError`），结算页与司机端一起打不开。
        这是本项目已经栽过一次的同一类问题（出参 JSON 列被 NULL 毒化），
        所以在 schema 层统一兜住：显示用字符串读不出来就当空串，不让一行脏数据打垮一个列表。
        """
        return "" if v is None else v


class DriverBillGenerateBody(BaseModel):
    driver_id: int | None = None      # 空=全部在职司机
    # 长度 7 与列宽 String(7) 一致；格式另有一份中文判据（validate_month）
    month: str = Field(..., max_length=7, description="YYYY-MM")
    bill_type: DriverBillType = DriverBillType.SALARY

    @field_validator("month", mode="before")
    @classmethod
    def _month(cls, v: str) -> str:
        return validate_month(v)


# ---------------- 客户收款单 ----------------
class ShipperReceiptCreate(MoneyInput):
    customer_id: int = Field(..., description="customers.id（含散客）")
    amount: Decimal = Field(..., gt=0)
    method: str = Field("cash", pattern="^(cash|transfer|wechat|arrears_settle)$")
    received_at: date
    order_ids: list[int] = Field(default_factory=list, description="逐单核销绑定的订单，必填（itemized 默认）")
    # **按商品核销**（2026-09-20 用户要求：「点击订单点击核销……也可以按商品进行核销」）：
    # 只核销点名的商品行，`amount` 必须等于**这些行**的 line_total 合计。
    # 留空 = 整单核销（老语义一字不变：金额 = 该单全部行合计）。
    # ⛔ 传了行就必须落在 `order_ids` 这几张单里（服务层逐行校验）：
    #    不校验的话，可以拿 A 单的行去核销 B 单的额度。
    order_product_ids: list[int] = Field(
        default_factory=list, description="按商品核销：只核销这些订单行（空=整单核销）"
    )
    settle_mode: ReceiptSettleMode = ReceiptSettleMode.ITEMIZED
    arrears_unit_id: int | None = None
    note: str = Field("", max_length=256)

    @model_validator(mode="after")
    def _itemized_needs_orders(self) -> "ShipperReceiptCreate":
        if self.settle_mode == ReceiptSettleMode.ITEMIZED and not self.order_ids:
            raise ValueError("逐单核销需绑定订单")
        return self


class ShipperReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    #: 「这笔收款已经被撤销」——撤销是**软删**（行还在、`is_deleted=1`）。回收站档
    #: （`GET /ledger/receipts?include_deleted=true`）靠它把已撤销的那几行标出来，
    #: 界面上的「恢复」键也只在它上面出现（2026-10-10，BUG-0029 / 台账 TB-09）。
    is_deleted: bool = False
    deleted_at: datetime | None = None
    amount: Decimal
    method: str
    received_at: date
    order_ids: list | None = None
    settle_mode: ReceiptSettleMode
    arrears_unit_id: int | None = None
    invoiced: bool = False
    note: str = ""
    operator_id: int | None = None
    customer_name: str | None = None
    created_at: datetime | None = None


# ---------------- 司机结算单 ----------------
class DriverSettlementCreate(MoneyInput):
    driver_id: int
    settle_type: DriverBillType = DriverBillType.PIECE
    month: str = Field(..., max_length=7, description="YYYY-MM；PIECE 按该月送达单，SALARY 按该月薪资单")
    amount: Decimal | None = Field(None, description="空=自动按范围内 OPEN 明细汇总")
    note: str = Field("", max_length=256)

    @field_validator("month", mode="before")
    @classmethod
    def _month(cls, v: str) -> str:
        return validate_month(v)


class DriverSettlementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    driver_id: int
    settle_type: DriverBillType
    month: str
    period_from: date | None = None
    period_to: date | None = None
    amount: Decimal
    status: SettlementStatus
    order_ids: list | None = None
    #: 这一单覆盖的明细行（`driver_bills.id`）与手工改额的差额 —— 「金额与明细同源」的两个凭据
    #: （2026-10-03 BUG-0007）。老单可能为空 / 0。
    bill_ids: list | None = None
    adjustment: Decimal = Decimal("0")
    paid_at: datetime | None = None
    method: str = ""
    operator_id: int | None = None
    note: str = ""
    driver_name: str | None = None
    created_at: datetime | None = None


class SettlementActionBody(BaseModel):
    action: str = Field(..., pattern="^(confirm|pay|cancel)$")
    method: str = Field("cash", pattern="^(cash|transfer|wechat|bank)$")
    paid_at: date | None = None


# ---------------- 开销单 ----------------
class ExpenseCreate(MoneyInput):
    exp_date: date
    # 分类是**可维护名册里的名字**（自由字符串，≤32 字）：
    # 原来这里是 `ExpenseCategory` 枚举 —— 枚举认不出的名字会让读接口整个 500，
    # 现在由 `services/expense_category_service.ensure_category` 把新名字自动补进名册。
    category: str = Field(..., max_length=32)
    amount: Decimal = Field(..., gt=0)
    driver_id: int | None = None
    vehicle_id: int | None = None
    order_id: int | None = None
    note: str = Field("", max_length=256)


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exp_date: date
    category: str
    amount: Decimal
    driver_id: int | None = None
    vehicle_id: int | None = None
    order_id: int | None = None
    note: str = ""
    operator_id: int | None = None
    driver_name: str | None = None
    # 车牌（卡片上「突出车辆」时显示的就是它；原来只回 vehicle_id，客户端拿不到车牌）
    vehicle_name: str | None = None
    # 这个分类「卡片上突出哪一项」（vehicle/driver/order/none）——**由分类名册带下来**，
    # 客户端不许自己按分类名 when(...) 判（用户新加一个分类就失效了）。
    link_kind: str = "none"
    order_no: str | None = None
    created_at: datetime | None = None
    # **这笔开销已经被撤销**（2026-10-10 BUG-0034 / 台账 TA-16）。
    # 撤销是**软删**：这一行还在库里（is_deleted=1），默认从「开销管理」里消失，
    # 只有 `GET /expenses?deleted_only=true`（界面顶上那颗「显示已撤销」档）才看得见它 ——
    # 那一档就是「恢复」的落点。
    # ⚠️ 默认 False：老后端/老快照回来的出参没有这两个键时，界面照旧只画「撤销」，
    #    不会把一笔正常的开销误画成已撤销。
    is_deleted: bool = False
    deleted_at: datetime | None = None


# ---------------- 资金流水 ----------------
class CashFlowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    flow_date: date
    direction: CashFlowDirection
    amount: Decimal
    party_type: str
    party_id: int | None = None
    party_name: str | None = None
    channel: str
    biz_type: CashFlowBizType
    order_id: int | None = None
    doc_id: int | None = None
    note: str = ""
    operator_id: int | None = None
    created_at: datetime | None = None


# ---------------- 车辆台账 ----------------
#
# ⚠️ **车型与车身型式是两件事**（2026-09-27 用户要的「车辆属性」）：
#   · `vehicle_type`（小货车 / 大货车 / 挂车）＝ **计费口径**，被司机计费规则 / 运费模板 /
#     `models/user.py::resolve_billing_mode` 共用，其中「挂车→按单计费、其余→固定工资」**是钱**
#     ⇒ ⛔ 它的取值一个字不扩；
#   · `body_type`（箱式车 / 平板车 / 自卸车 / 挂车 / 未设置）＝ **车身型式**，
#     决定**这辆车能填哪些属性**。
# 判据（哪些型式能填哪些项、每项叫什么、范围多少）的**唯一实现**在 `services/vehicle_attrs.py`，
# 这里只声明出入参形状。
class VehicleCreate(MoneyInput):
    #: ⚠️ 继承 `MoneyInput`（2026-10-04 FEAT-0012）：`purchase_price` 命中 `money.MONEY_RE`，
    #: 平台上限（`MONEY_MAX` = 9,999,999,999.99 = `Numeric(12,2)` 能存下的最大）由它一处给 ——
    #: 与下面「折旧台账四格」那条纪律**不冲突**：这里管的是"能不能存进数据库"（`money.py` 是唯一判据），
    #: 业务区间（> 0、最多两位小数）仍只在 `services/vehicle_depreciation.clean_fields`（中文 400）。
    plate_no: str = Field(..., min_length=1, max_length=16)
    vehicle_type: str = Field("", max_length=16)
    #: 分组用的分类（空串 = 未分类，2026-10-05）。⛔ 与 `vehicle_type`（计费口径）、
    #: `body_type`（车身型式）是**三件事**：这一格只决定车辆管理页左侧那一列怎么分组，
    #: **不参与任何计费/匹配**。名册与顺序在 `vehicle_categories` 表里。
    category: str = Field("", max_length=32)
    driver_id: int | None = None
    #: 车身型式（`services/vehicle_attrs.BODY_TYPES`）。空串 = 未设置 —— 它是**正式取值**
    #: （老车、以及"还不知道这车是什么型式"），不是"没填"。
    body_type: str = Field("", max_length=16)
    #: 车辆属性 `{属性键: 数值}`（键见 `services/vehicle_attrs.ATTR_KEYS`）。
    #: ⚠️ 值**收字符串也收数字**（App 传字符串、AI 可能传数字）；校验与归一在
    #: `vehicle_attrs.parse_attrs`（那里给的是**中文**，不是 pydantic 的英文结构体）。
    #: ⛔ 这里刻意**不写** per-key 的 Field 约束：写了越界会变成 422 + 英文结构体，
    #:    而用户需要的是一句能照着改的话（与司机计费规则 `validate_rule_params` 同一条纪律）。
    attrs: dict[str, Any] | None = None

    #: ── 折旧台账四格（FEAT-0012 第二期，2026-10-04）──────────────────────────────
    #: ⛔ 校验**不在这里**：越界要回一句**中文**、用户能照着改的话，而 `Field` 约束会变成
    #: 422 ＋ 英文结构体（与上面 `attrs` 同一条纪律）。规则与话术的唯一实现在
    #: `services/vehicle_depreciation.clean_fields`，接口层把它的 `ValueError` 原样转成 400。
    #: ⚠️ 空串 = 没录（安卓发得出空串，发不出显式 null）。四个数缺任何一个 ⇒ 这辆车折旧「未覆盖」。
    purchase_price: Decimal | None = None  # 购置价（元，折旧的计提基数）
    purchase_date: date | None = None  # 购置日期（计提起点；不许晚于今天）
    useful_life_years: Decimal | None = None  # 使用年限（年，0.5–30，一位小数）
    residual_rate: Decimal | None = None  # 残值率（0–0.5；**留空 = 0%**）

    #: ── 年检台账两格（FEAT-0022，2026-10-11）────────────────────────────────────
    #: 用户口径（逐字）：「到我给那个车子建档案的时候会填一下就是这车的上牌日期。
    #: 或者说是上一个年检日期啊方便我们去做一个提醒」—— 他只录**已经发生过的事实**，
    #: 「下次该检了」由系统算（唯一一处：services/inspection_due.py，⛔ 不落库、
    #: ⛔ 这里没有也不需要「下次年检日期」这个入参）。
    #: ⚠️ 空串 = 没录（安卓发得出空串、发不出显式 null）；**两格都空 ⇒ 这台车不产生任何年检提醒**
    #:    （⛔ 不许拿建档日期或今天当上牌日期去凑一条出来）。
    registration_date: date | None = None  # 上牌日期
    last_inspection_date: date | None = None  # 上次年检日期

    @field_validator("purchase_price", "purchase_date", "useful_life_years", "residual_rate",
                     "registration_date", "last_inspection_date", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        """空串 = 没录（安卓 `explicitNulls = false` 发不出显式 null，清空只能靠空串表达）。"""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


class VehicleUpdate(MoneyInput):
    #: ⚠️ 同上（FEAT-0012）：`purchase_price` 的平台上限由 `MoneyInput` 一处给；
    #: 业务区间与中文话术仍只在 `services/vehicle_depreciation.clean_fields`。
    """改车辆：**只传要改的键**，没传的后端不动。

    ⚠️ **两个键各有一套"没传 vs 传空"的语义**，都必须说清：

    * `driver_id`：**没传这个键** = 不动司机；**显式传 `null`** = 解绑（v3.44）。
      以前两种都走 `is not None`，于是"解绑"这件事根本没有表达方式。
    * `attrs`：**没传** = 不动属性；**传了就是整份替换** —— 没写进去的属性会被清空。
      需求方 2026-09-27 要的是「属性**不可能变**」：改就是一次说清"这辆车现在是什么样"，
      别让两次改动之间留一个谁也说不清的状态。（安卓 `explicitNulls = false` 发不出
      "显式 null"，整份替换正好把"清空某一项"表达成"不带这一项"，不需要额外协议。）
    """

    plate_no: str | None = Field(None, max_length=16)
    vehicle_type: str | None = Field(None, max_length=16)
    #: 分类。**没传** = 不改；传了名册里没有的名字 → 自动补进名册（见上面的三件事说明）。
    category: str | None = Field(None, max_length=32)
    driver_id: int | None = None
    is_active: bool | None = None
    #: 车身型式。**没传** = 不改；传了要过 `vehicle_attrs.clean_body`。
    body_type: str | None = Field(None, max_length=16)
    #: 车辆属性。**没传** = 不改；**传了就是整份替换**（没写进去的属性会被清空）——
    #: 见类注释里那一段。
    attrs: dict[str, Any] | None = None

    #: ── 折旧台账四格（FEAT-0012 第二期，2026-10-04）──────────────────────────────
    #: **没传** = 不改；**传了空串** = 清空这一格（`model_fields_set` 判"传没传"，空串归一成 None）。
    #: ⚠️ 与 `attrs` 的"整份替换"不同：这四格是**一格一格**的，清空一格不影响其它三格。
    #: 校验与中文话术的唯一实现在 `services/vehicle_depreciation.clean_fields`（越界 → 400）。
    purchase_price: Decimal | None = None  # 购置价（元）
    purchase_date: date | None = None  # 购置日期
    useful_life_years: Decimal | None = None  # 使用年限（年）
    residual_rate: Decimal | None = None  # 残值率（0–0.5）

    #: ── 年检台账两格（FEAT-0022，2026-10-11）────────────────────────────────────
    #: **没传** = 不改（⛔ 老客户端不带这两格时**不许把它们清空** —— PATCH 语义，判据钉着）；
    #: **传了空串** = 清空这一格（model_fields_set 判「传没传」，空串归一成 None）。
    #: ⚠️ 与折旧四格同一套逐格语义：清空一格不影响另一格。
    registration_date: date | None = None  # 上牌日期
    last_inspection_date: date | None = None  # 上次年检日期

    @field_validator("purchase_price", "purchase_date", "useful_life_years", "residual_rate",
                     "registration_date", "last_inspection_date", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        """空串 = 没录（安卓 `explicitNulls = false` 发不出显式 null，清空只能靠空串表达）。"""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


class VehicleDriverSet(BaseModel):
    """绑司机 / 解绑：`driver_id` **缺省或 null 都 = 解绑**。

    形状照抄 `DriverBillingRuleAttachBody`（那边 `rule_id=null` = 解挂）——
    因为客户端（安卓 `explicitNulls = false`）发不出"显式 null"，
    只能把"没带这个键"本身定义成解绑。
    """

    driver_id: int | None = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plate_no: str
    vehicle_type: str
    driver_id: int | None = None
    is_active: bool = True
    driver_name: str | None = None
    created_at: datetime | None = None
    #: 车身型式（`box` / `flat` / `dump` / `trailer` / 空串）与它的**中文名**。
    #: ⚠️ 中文名由**后端**给：客户端再写一份 `when(...)`，两处叫法迟早不一样。
    body_type: str = ""
    body_label: str = ""
    #: 分类（空串 = 未分类）。只用于分组视图，不影响计费/匹配。
    category: str = ""
    #: 填过的属性 `{属性键: 数值字符串}` —— **只回填过的那些**，没量过的不出现。
    #: ⚠️ 值是**字符串**不是数字：`load_tons` / `volume_cubic` 要参与「一车 = 多少方 / 多少吨」
    #:    的换算，浮点会让 8 变成 7.999999999999999；客户端用 BigDecimal 接
    #:    （与 `UnitConversionDto.factor` 同一个做法）。
    attrs: dict[str, str] = Field(default_factory=dict)

    #: ── 折旧台账四格原值 ＋ 算不算得出来（FEAT-0012 第二期，2026-10-04）────────────
    #: ⚠️ 原值与"算不算得出来"是两件事：原值 `None` = 没录；`depreciation_covered=False` = 缺格。
    #: 下面两格由 `api/v1/vehicles._out()` 用 `services/vehicle_depreciation` **现算**，
    #: ⛔ 库里没有这几列（折旧永不落库）。
    purchase_price: Decimal | None = None
    purchase_date: date | None = None
    useful_life_years: Decimal | None = None
    residual_rate: Decimal | None = None
    #: 这台车的折旧**算不算得出来**（购置价 / 购置日期 / 使用年限三个缺一个就是 False）。
    depreciation_covered: bool = False
    #: 缺的是哪几格（中文，逐项；空 = 都齐）。话术由 `vehicle_depreciation.missing_items` 给。
    depreciation_missing: list[str] = Field(default_factory=list)
    #: 每月折旧额（元，两位小数）。⛔ 算不出来时是 `null`，**不是 0** ——
    #: 「0」是"已经提足"，「null」是"算不出来"，报表上这是两件事。
    depreciation_monthly: Decimal | None = None

    #: ── 年检台账两格原值（FEAT-0022，2026-10-11）────────────────────────────────
    #: ⚠️ 回的是**原值**：None = 没录。⛔ 这里**不回**「下次年检日期」——
    #: 那是派生量（services/inspection_due.next_due_date 现算），
    #: 回一个算出来的日期会让客户端以为库里存着它、进而自己去比今天。
    registration_date: date | None = None
    last_inspection_date: date | None = None
