"""车辆台账——账本 V2：车牌/车型/挂靠司机。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import User, Vehicle
from app.models.enums import UserRole
from app.schemas.accounting_v2 import VehicleCreate, VehicleOut, VehicleUpdate

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


def _must_dispatcher(current: User) -> None:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")


@router.get("", response_model=list[VehicleOut])
def list_vehicles(current: CurrentUser, db: Session = Depends(get_db)) -> list[VehicleOut]:
    _must_dispatcher(current)
    rows = list(db.scalars(select(Vehicle).order_by(Vehicle.id.desc())))
    names: dict[int, str] = {}
    out = []
    for v in rows:
        if v.driver_id and v.driver_id not in names:
            u = db.get(User, v.driver_id)
            names[v.driver_id] = (u.full_name or u.phone or "") if u else ""
        out.append(
            VehicleOut(
                id=v.id, plate_no=v.plate_no, vehicle_type=v.vehicle_type,
                driver_id=v.driver_id, is_active=v.is_active,
                driver_name=names.get(v.driver_id, ""), created_at=v.created_at,
            )
        )
    return out


@router.post("", response_model=VehicleOut)
def create_vehicle(body: VehicleCreate, current: CurrentUser, db: Session = Depends(get_db)) -> VehicleOut:
    _must_dispatcher(current)
    plate = body.plate_no.strip()
    if not plate:
        raise HTTPException(status_code=400, detail="请输入车牌号")
    dup = db.scalars(select(Vehicle).where(Vehicle.plate_no == plate)).first()
    if dup is not None:
        raise HTTPException(status_code=400, detail="该车牌已存在")
    v = Vehicle(plate_no=plate, vehicle_type=body.vehicle_type, driver_id=body.driver_id)
    db.add(v)
    db.commit()
    db.refresh(v)
    u = db.get(User, v.driver_id) if v.driver_id else None
    return VehicleOut(
        id=v.id, plate_no=v.plate_no, vehicle_type=v.vehicle_type,
        driver_id=v.driver_id, is_active=v.is_active,
        driver_name=(u.full_name or u.phone or "") if u else "", created_at=v.created_at,
    )


@router.patch("/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(vehicle_id: int, body: VehicleUpdate, current: CurrentUser, db: Session = Depends(get_db)) -> VehicleOut:
    _must_dispatcher(current)
    v = db.get(Vehicle, vehicle_id)
    if v is None:
        raise HTTPException(status_code=404, detail="车辆不存在")
    if body.plate_no is not None:
        v.plate_no = body.plate_no.strip()
    if body.vehicle_type is not None:
        v.vehicle_type = body.vehicle_type
    if body.driver_id is not None:
        v.driver_id = body.driver_id
    if body.is_active is not None:
        v.is_active = body.is_active
    db.commit()
    db.refresh(v)
    u = db.get(User, v.driver_id) if v.driver_id else None
    return VehicleOut(
        id=v.id, plate_no=v.plate_no, vehicle_type=v.vehicle_type,
        driver_id=v.driver_id, is_active=v.is_active,
        driver_name=(u.full_name or u.phone or "") if u else "", created_at=v.created_at,
    )
