from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ShipperContact


def upsert_boss_contact(db: Session, shipper_id: int, phone: str, display_name: str = "") -> None:
    phone = phone.strip()
    if not phone:
        return
    row = db.scalars(
        select(ShipperContact).where(
            ShipperContact.shipper_id == shipper_id,
            ShipperContact.phone == phone,
        )
    ).first()
    if row is None:
        db.add(
            ShipperContact(
                shipper_id=shipper_id,
                phone=phone,
                display_name=display_name or "",
            )
        )
    elif display_name and not row.display_name:
        row.display_name = display_name
