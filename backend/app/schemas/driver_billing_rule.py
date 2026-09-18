"""司机计费规则模板的出入参 + **参数合法性校验（创建与修改共用一份）**。"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.schemas.money import MoneyInput
from app.schemas.text import MAX_TEXT
from app.services.driver_pay import COMMISSION_BASES, PIECE_UNITS

_VEHICLE_TYPES = ("small", "large", "trailer")


def validate_rule_params(p: dict) -> str | None:
    """校验一份规则的参数，返回**中文**错误信息（None = 通过）。

    ⚠️ 修改走的是"合并后的完整参数"，不是补丁本身：只校验补丁的话，
    `{"commission_base": "freight"}` 这种单字段修改会绕过"比例必须大于 0"的检查，
    于是库里出现一份"有基数没比例"的规则——它算出来的钱永远是 0，
    而界面上看着像配置好了（**这种静默的 0 比报错难查得多**）。
    """
    name = (p.get("name") or "").strip()
    if not name:
        return "规则名称不能为空（AI 和界面都按名字找它）"
    if len(name) > 128:
        return "规则名称太长（最多 128 字）"

    vt = p.get("vehicle_type") or None
    if vt is not None and vt not in _VEHICLE_TYPES:
        return "适用车型只能是 small/large/trailer（小型车/大车/挂车），或留空表示通用"

    unit = p.get("piece_unit") or "order"
    if unit not in PIECE_UNITS:
        return "计件单位只能是 order（每单/每车固定数）、order_price（拿这一单的钱）或 item（每件）"

    base = p.get("commission_base") or "none"
    if base not in COMMISSION_BASES:
        return "提成基数只能是 none/freight（运费）/goods（商品金额）"

    for key, cn in (("salary", "固定工资"), ("piece_amount", "每单金额"), ("commission_rate", "提成比例")):
        v = p.get(key)
        if v is None:
            continue
        if Decimal(str(v)) < 0:
            return f"{cn}不能是负数"
    rate = Decimal(str(p.get("commission_rate") or 0))
    if rate > 100:
        return "提成比例不能超过 100%"

    piece = Decimal(str(p.get("piece_amount") or 0))
    salary = Decimal(str(p.get("salary") or 0))
    scope = list(p.get("commission_product_ids") or [])
    if scope and base != "goods":
        # 按整单运费抽成时没有"哪些商品"这回事——收下它只会让人以为范围生效了
        return "「只对指定商品抽成」只能配在按商品金额抽成上（按运费抽成时没有商品范围这回事）"
    if rate > 0 and base == "none":
        return "填了提成比例，就要选提成基数（按运费还是按商品金额）——否则这份规则一分钱都算不出来"
    if base != "none" and rate <= 0:
        return "选了提成基数，就要填提成比例（百分比）"
    if unit == "order_price" and base == "freight" and rate > 0:
        # "拿这一单全额" 再加 "按这单运费抽 X%" = 拿了 100%+X%，几乎一定是配错了
        return "「每单拿这一单的钱」和「按运费抽成」不能同时配（那等于拿 100% 再加提成）；只留一个"
    if unit == "order_price" and piece > 0:
        return "「每单拿这一单的钱」时不要再填固定每单金额（两者取一）"
    if salary <= 0 and piece <= 0 and rate <= 0 and unit != "order_price":
        return "这份规则一分钱都不给（固定工资/每单金额/提成/拿这一单的钱 至少要有一个）"
    return None


class DriverBillingRuleCreate(MoneyInput):
    # ⚠️ 这里**故意不加 ge/le 业务范围约束**：加了之后越界会被 Pydantic 拦成 422，
    #    返回的是一段英文结构体，而不是 `validate_rule_params` 里那句中文原因。
    #    用户（和 AI）看到的必须是"填了提成比例就要选基数"这种能照着改的话，
    #    所以**业务**范围/取值/组合校验只有一份，就在下面那个函数里。
    #    而"能不能存进数据库"是**平台约束**（钱列是 Numeric(12,2)，上限 9999999999.99），
    #    它不该按模型各写一遍——统一由 `MoneyInput` 管，报错也是中文。
    name: str = Field(..., max_length=128)
    vehicle_type: str | None = Field(None, max_length=16)
    salary: Decimal = Decimal("0")
    piece_amount: Decimal = Decimal("0")
    piece_unit: str = Field("order", max_length=8)
    commission_base: str = Field("none", max_length=16)
    commission_rate: Decimal = Decimal("0")
    commission_product_ids: list[int] = []
    remark: str = Field("", max_length=MAX_TEXT)


class DriverBillingRuleUpdate(MoneyInput):
    """部分更新：只放用户点名的字段（没点名的保持原样）。"""

    name: str | None = Field(None, max_length=128)
    vehicle_type: str | None = Field(None, max_length=16)
    salary: Decimal | None = None
    piece_amount: Decimal | None = None
    piece_unit: str | None = Field(None, max_length=8)
    commission_base: str | None = Field(None, max_length=16)
    commission_rate: Decimal | None = None
    commission_product_ids: list[int] | None = None
    remark: str | None = Field(None, max_length=MAX_TEXT)


class DriverBillingRuleOut(BaseModel):
    id: int
    name: str
    vehicle_type: str | None = None
    salary: Decimal
    piece_amount: Decimal
    piece_unit: str
    commission_base: str
    commission_rate: Decimal
    # 抽成范围（商品 id 列表；空 = 不限）
    commission_product_ids: list[int] = []
    # 这些商品叫什么（出参给人看，不用客户端再查一次商品库）
    commission_product_names: list[str] = []
    remark: str = ""
    # 一句话说清它怎么给钱（由 `driver_pay.PayRule.describe()` 生成，界面/卡片直接显示）
    summary: str = ""
    # 有几个司机挂着它（删之前要让人看见"还有 3 个人在用"）
    attached_count: int = 0
    is_deleted: bool = False
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class AttachRuleBody(BaseModel):
    """把规则挂到司机身上（`rule_id=null` = 解挂，退回老口径）。"""

    driver_id: int
    rule_id: int | None = None
