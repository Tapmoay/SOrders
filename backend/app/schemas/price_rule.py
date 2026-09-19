from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.money import MoneyInput


class PriceRuleBatchBody(MoneyInput):
    """批量调价：多批发商 × 多商品，统一一套价格逻辑。

    ⚠️ `mode` 只有三档（2026-09-19 用户拍板删掉第四档 `tier`）：原来是
    `Literal["fixed", "tier", "percent", "adjust"]`，`tier` = 取商品自身的"批发价第 N 档"。
    那个档位（`products.tier_prices`）**下单时谁都不照它走**（下单只认 `price_rules` 的
    按（批发商×商品）专属价，或商品默认售价），属于"看着像批发价、其实是纯预设值"的概念，
    所以整套删掉、由 `Literal` 直接 422 拒掉（不留一个"接受但静默无效"的口子）。
    """

    shipper_ids: list[int] = Field(default_factory=list, description="空=全部批发商")
    product_ids: list[int] = Field(default_factory=list, description="空=全部商品")
    mode: Literal["fixed", "percent", "adjust"] = "fixed"
    value: Decimal | None = Field(None, ge=Decimal("0"), description="fixed=统一单价；percent=默认售价的百分比(如95=95%)")
    adjust_percent: Decimal | None = Field(
        None,
        ge=Decimal("-100"),
        le=Decimal("1000"),
        description="adjust=在【当前生效价】基础上涨/降百分之多少"
        "（+10=涨10%，-15=降15%）。当前生效价 = 已有的专属价；没有专属价则用商品默认价。",
    )


class PriceRuleBatchChange(BaseModel):
    """一条改动的前后值。**接口回报它，卡片和结果才对得上账。**

    before=None 表示这个批发商之前没有专属价（按通用价买）。
    """

    shipper_name: str
    product_name: str
    before: Decimal | None = None
    after: Decimal


class PriceRuleBatchOut(BaseModel):
    count: int
    skipped: int = 0
    changes: list[PriceRuleBatchChange] = []


class PriceRuleCreate(MoneyInput):
    shipper_id: int
    product_id: int
    special_unit_price: Decimal = Field(..., ge=Decimal("0"))


class PriceRuleUpdate(MoneyInput):
    special_unit_price: Decimal | None = Field(None, ge=Decimal("0"))
    shipper_id: int | None = None


class PriceRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipper_id: int
    product_id: int
    special_unit_price: Decimal
    shipper_name: str | None = None
    product_name: str | None = None
