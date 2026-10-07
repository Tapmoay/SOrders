"""批发商**自己那层价**（下游定价）的入参 / 出参 —— CHG-0077 / 台账 L-38。

⛔ 入参里**没有「谁」（`shipper_id`）**：写的人只能是 `current.id` 自己 —— 口径 m13365 第①问
「只能定他自己名下的商品」。派单员给他定的价走 `price_rules`（第二层价），与本文件是两件事：
本文件写的是**他给下游客户**的价，只进他自己那本下游账。

⛔ 入参里也**没有 `order_id`**：这一层价只在**下单建行时**定格到
`order_products.shipper_unit_price`（见 `services/shipper_price.py::snapshot_order_lines`），
历史订单永不追改 —— 改价不许改历史（口径⑤ m13365）。
"""
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.money import MoneyInput


class ShipperPriceSet(MoneyInput):
    """设一条下游价：一个商品 ＋（可选）一个联系人 ＋ 单价。

    `contact_id=None` ⇒ 这个商品对**全部下游**的**默认价**（回落档）；
    有值 ⇒ 只对那一个联系人生效、并覆盖默认价（口径 m13365 第②问：「给不同的人不同的价格」）。
    """

    product_id: int = Field(..., ge=1, description="他名下可定价的商品（见 GET /shipper-prices/products）")
    contact_id: int | None = Field(
        None, ge=1, description="留空 = 这个商品的默认下游价；填了 = 只对这一个联系人生效"
    )
    #: ⚠️ `gt=0`（不是 `ge=0`）：0 元的价目表行看着像"设过了"，实际等于白送 ——
    #    CHG-0077 行为契约把「单价 ≤ 0」与「超过上限」并列写成 Failure（都要 4xx）。
    #    上限由 `MoneyInput` 统一管（`Numeric(14,4)` 能存的范围，判据只有 `schemas/money.py` 一处）。
    unit_price: Decimal = Field(..., gt=Decimal("0"), description="他自己定的下游单价（元）")


class ShipperPriceOut(BaseModel):
    """价目表一行（商品 / 联系人 / 单价）。

    `contact_id=None` ⇒ 这是该商品的**默认下游价**（对这一行的商品、所有下游生效）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    contact_id: int | None = None
    unit_price: Decimal
    #: 名字是给界面直接用的：编号在页面上没有意义（与操作日志同一条口径）
    product_name: str | None = None
    contact_name: str | None = None
    #: 软删的行只在 `include_deleted=true` 时出现（回收站里那几行，用来恢复）
    is_deleted: bool = False


class ShipperPriceProductOut(BaseModel):
    """「可定价商品」一行：他名下有哪些商品、他拿货什么价、他给下游定过什么价。

    ⛔ `supply_unit_price` **只作参考**（填下游价时别填亏了），不参与任何计算：
    钱只有一套算法（`services/order_money.py` ＋ `services/money_contract.py`）。
    """

    product_id: int
    product_name: str
    unit: str | None = None
    #: 他拿货的价 = 派单员给他的专属价 → 回落商品目录价（口径见 `models/product.py:39`）
    supply_unit_price: Decimal | None = None
    #: 他给全部下游定的默认价（没定过 = None ⇒ 下单时快照留 NULL、回落订单行单价）
    default_unit_price: Decimal | None = None
    #: 他单独定过价的联系人数（> 0 就是"给不同的人不同的价"）
    contact_price_count: int = 0
