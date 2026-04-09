from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_roles
from app.models import ShipperAddress, ShipperContact, User
from app.models.enums import UserRole
from app.schemas.shipper import AddressCreate, AddressOut, AddressUpdate, ContactCreate, ContactOut

router = APIRouter(prefix="/shipper", tags=["shipper"])

ShipperOnly = Annotated[User, Depends(require_roles(UserRole.SHIPPER))]


def _clear_defaults(db: Session, shipper_id: int, except_id: int | None = None) -> None:
    q = select(ShipperAddress).where(
        ShipperAddress.shipper_id == shipper_id,
        ShipperAddress.is_default.is_(True),
    )
    if except_id is not None:
        q = q.where(ShipperAddress.id != except_id)
    for row in db.scalars(q).all():
        row.is_default = False


@router.get("/addresses", response_model=list[AddressOut])
def list_addresses(current: ShipperOnly, db: Session = Depends(get_db)) -> list[ShipperAddress]:
    rows = db.scalars(
        select(ShipperAddress)
        .where(ShipperAddress.shipper_id == current.id)
        .order_by(ShipperAddress.is_default.desc(), ShipperAddress.id.desc())
    ).all()
    return list(rows)


@router.post("/addresses", response_model=AddressOut, status_code=status.HTTP_201_CREATED)
def create_address(
    body: AddressCreate,
    current: ShipperOnly,
    db: Session = Depends(get_db),
) -> ShipperAddress:
    if body.is_default:
        _clear_defaults(db, current.id)
    addr = ShipperAddress(
        shipper_id=current.id,
        receiver_name=body.receiver_name,
        phone=body.phone,
        detail_address=body.detail_address,
        remark=body.remark,
        is_default=body.is_default,
        address_lat=body.address_lat,
        address_lng=body.address_lng,
    )
    db.add(addr)
    db.commit()
    db.refresh(addr)
    return addr


@router.get("/addresses/{address_id}", response_model=AddressOut)
def get_address(address_id: int, current: ShipperOnly, db: Session = Depends(get_db)) -> ShipperAddress:
    a = db.get(ShipperAddress, address_id)
    if a is None or a.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return a


@router.patch("/addresses/{address_id}", response_model=AddressOut)
def update_address(
    address_id: int,
    body: AddressUpdate,
    current: ShipperOnly,
    db: Session = Depends(get_db),
) -> ShipperAddress:
    a = db.get(ShipperAddress, address_id)
    if a is None or a.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if body.is_default is True:
        _clear_defaults(db, current.id, except_id=address_id)
    if body.receiver_name is not None:
        a.receiver_name = body.receiver_name
    if body.phone is not None:
        a.phone = body.phone
    if body.detail_address is not None:
        a.detail_address = body.detail_address
    if body.remark is not None:
        a.remark = body.remark
    if body.is_default is not None:
        a.is_default = body.is_default
    if body.address_lat is not None:
        a.address_lat = body.address_lat
    if body.address_lng is not None:
        a.address_lng = body.address_lng
    db.commit()
    db.refresh(a)
    return a


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(address_id: int, current: ShipperOnly, db: Session = Depends(get_db)) -> None:
    a = db.get(ShipperAddress, address_id)
    if a is None or a.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    db.delete(a)
    db.commit()


@router.post("/addresses/{address_id}/set-default", response_model=AddressOut)
def set_default_address(address_id: int, current: ShipperOnly, db: Session = Depends(get_db)) -> ShipperAddress:
    a = db.get(ShipperAddress, address_id)
    if a is None or a.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    _clear_defaults(db, current.id, except_id=address_id)
    a.is_default = True
    db.commit()
    db.refresh(a)
    return a


@router.get("/contacts", response_model=list[ContactOut])
def list_contacts(current: ShipperOnly, db: Session = Depends(get_db)) -> list[ShipperContact]:
    rows = db.scalars(
        select(ShipperContact).where(ShipperContact.shipper_id == current.id).order_by(ShipperContact.id.desc())
    ).all()
    return list(rows)


@router.post("/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def upsert_contact(
    body: ContactCreate,
    current: ShipperOnly,
    db: Session = Depends(get_db),
) -> ShipperContact:
    phone = body.phone.strip()
    row = db.scalars(
        select(ShipperContact).where(
            ShipperContact.shipper_id == current.id,
            ShipperContact.phone == phone,
        )
    ).first()
    if row:
        if body.display_name:
            row.display_name = body.display_name
    else:
        row = ShipperContact(shipper_id=current.id, phone=phone, display_name=body.display_name or "")
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(contact_id: int, current: ShipperOnly, db: Session = Depends(get_db)) -> None:
    c = db.get(ShipperContact, contact_id)
    if c is None or c.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    db.delete(c)
    db.commit()
