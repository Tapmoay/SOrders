"""运费模板（派单员）：路线×车型×一车价，派单选价一键带出。"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import FreightTemplate, User
from app.schemas.freight_template import (
    FreightTemplateCreate,
    FreightTemplateOut,
    FreightTemplateUpdate,
)

router = APIRouter(prefix="/freight-templates", tags=["freight-templates"])

_VALID_VEHICLE = {"small", "large", "trailer", ""}


def _validate_vehicle(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if v not in _VALID_VEHICLE:
        raise HTTPException(status_code=400, detail="车型不合法")
    return v


@router.get("", response_model=list[FreightTemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    vehicle_type: str | None = Query(None),
) -> list[FreightTemplate]:
    q = select(FreightTemplate).order_by(FreightTemplate.id.desc())
    if vehicle_type:
        q = q.where(FreightTemplate.vehicle_type == vehicle_type)
    return list(db.scalars(q))


@router.post("", response_model=FreightTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: FreightTemplateCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> FreightTemplate:
    t = FreightTemplate(
        name=body.name.strip(),
        from_place=body.from_place.strip(),
        to_place=body.to_place.strip(),
        vehicle_type=_validate_vehicle(body.vehicle_type),
        fee=body.fee,
        remark=body.remark,
        created_by=current.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.put("/{template_id}", response_model=FreightTemplateOut)
def update_template(
    template_id: int,
    body: FreightTemplateUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> FreightTemplate:
    t = db.get(FreightTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="未找到该模板")
    if body.name is not None:
        t.name = body.name.strip()
    if body.from_place is not None:
        t.from_place = body.from_place.strip()
    if body.to_place is not None:
        t.to_place = body.to_place.strip()
    if body.vehicle_type is not None:
        t.vehicle_type = _validate_vehicle(body.vehicle_type)
    if body.fee is not None:
        t.fee = body.fee
    if body.remark is not None:
        t.remark = body.remark
    db.commit()
    db.refresh(t)
    return t


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> None:
    t = db.get(FreightTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="未找到该模板")
    db.delete(t)
    db.commit()
