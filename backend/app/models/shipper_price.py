from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.shipper import ShipperContact
    from app.models.user import User


class ShipperPrice(Base, TimestampMixin, SoftDeleteMixin):
    """**第三层价**：批发商自己给下游客户定的价（CHG-0077 / 台账 L-38）。

    ## 语义（用户 2026-10-07 原话，ref m01547）
    > 「他同样可以给他**自己的商品进行定价**，但这个定价**只走他自己的账**……
    >    **别人欠他的就按照他自己定的价**来……同理，他也可以**给不同的人不同的价格**
    >    （给他的**联系人**不同价格）」

    三层价，各管一层，⛔ 不许互相改写：

    | 层 | 谁定的 | 存在哪 | 影响谁的钱 |
    |---|---|---|---|
    | 一 | 平台 / 派单员的商品价 | `products.unit_price` | 下单参考 |
    | 二 | 派单员给这个批发商的专属价 | `price_rules.special_unit_price`（`shipper_id` = **被给价**的批发商） | 公司那本账（他欠公司的） |
    | 三 | **批发商自己给下游客户定的价** | **本表** | 只有他自己那本账（下游欠他的） |

    ## 一行代表什么
    - `contact_id` 有值 ⇒ **对这个下游联系人的单独价**（优先）；
    - `contact_id` 为 NULL ⇒ 该商品对**所有下游**的**默认价**（回落档）。

    ## 三条设计约束
    1. **`contact_id` 存外键、不复用「姓名|电话」**：口径 m13365 第②问 —— 「不同的人」
       用他的**联系人名册**（`shipper_contacts`）。账本里那套 `姓名|电话` 分组是
       **展示口径**，⛔ 不是实体；挂它等于让「改一次备注 / 换一次号」就把价丢了。
    2. **唯一约束拦不住「默认价」**：SQLite / MySQL 里 NULL 互不相等，
       `uq_shipper_price_scope(shipper_id, contact_id, product_id)` 对
       `contact_id IS NULL` 那一档**不生效** ⇒ 默认价由服务层查重 / 归一
       （与 `user_product_visibility` 那条注释同一口径）。
    3. **软删、不物理删**：价是「当时定过的价」的凭据；删了之后订单行上的历史快照就没人能解释
       —— 与「价格规则不随商品删除消失」同一个取向。
    """

    __tablename__ = "shipper_prices"
    __table_args__ = (
        # ⚠️ 只管「对某个联系人」那一档；默认价（contact_id IS NULL）由服务层归一
        UniqueConstraint("shipper_id", "contact_id", "product_id", name="uq_shipper_price_scope"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    #: 定价的人（批发商本人）；写入口只写 current.id，⛔ 派单员不代设（L-39 口径）
    shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: NULL = 该商品的**默认下游价**（对这个批发商的全部下游生效）
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipper_contacts.id"), nullable=True, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    #: 他自己定的下游单价（与 order_products.unit_price 同一个精度，q2 到分在算法出口里做）
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))

    shipper: Mapped["User"] = relationship()
    contact: Mapped["ShipperContact | None"] = relationship()
    product: Mapped["Product"] = relationship()
