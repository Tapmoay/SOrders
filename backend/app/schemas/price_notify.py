from decimal import Decimal

from pydantic import Field

from app.schemas.money import MoneyInput


class PriceChangeNotifyBody(MoneyInput):
    """派单员：价格变更后向选定货主发送消息中心通知。"""

    shipper_ids: list[int] = Field(..., min_length=1, max_length=200)
    product_id: int
    product_name: str = Field(..., min_length=1, max_length=256)
    price_type: str = Field(..., pattern="^(default|special)$")
    new_price: Decimal
    old_price: Decimal | None = None
    product_image_url: str | None = Field(
        None,
        max_length=512,
        description="商品展示图 URL（货主端消息条展示）",
    )
