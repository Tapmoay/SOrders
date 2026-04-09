from sqlalchemy.orm import Session

from app.models import Ledger, Order
from app.schemas.ledger import LedgerOut


def ledger_to_out(row: Ledger, db: Session) -> LedgerOut:
    order_no: str | None = None
    order_delivery_description: str | None = None
    if row.order_id:
        o = db.get(Order, row.order_id)
        if o:
            order_no = o.order_no
            d = (o.delivery_description or "").strip()
            order_delivery_description = d or None
    return LedgerOut(
        id=row.id,
        shipper_id=row.shipper_id,
        temp_shipper_name=row.temp_shipper_name,
        entry_date=row.entry_date,
        product_name=row.product_name,
        quantity=row.quantity,
        unit_price=row.unit_price,
        total=row.total,
        order_id=row.order_id,
        order_product_id=row.order_product_id,
        product_id=row.product_id,
        order_no=order_no,
        order_delivery_description=order_delivery_description,
        source=row.source,
        note=row.note,
        created_at=row.created_at,
    )
