"""运费模板（派单员）：路线×车型×一车价，派单选价一键带出。"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import FreightTemplate, User
from app.models.enums import OperationAction
from app.schemas.freight_template import (
    FreightTemplateCreate,
    FreightTemplateOut,
    FreightTemplateUpdate,
)
from app.services.operation_log_service import write_log
from app.services.soft_delete import ensure_alive

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
    q = select(FreightTemplate).where(FreightTemplate.is_deleted.is_(False)).order_by(
        FreightTemplate.id.desc()
    )
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
    db.flush()
    # ⚠️ 运费模板是派单填运费的**参考价**，改一个数字影响所有人报价——原来一次日志都不写
    #    （2026-09-19 审计 R14-1，与挂账单位同一批）。审计页上必须能回答"这条价是谁定的"。
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_TEMPLATE_UPSERT,
        change_payload={
            "template_id": t.id,
            "scope": "create",
            "name": t.name,
            "from_place": t.from_place,
            "to_place": t.to_place,
            "vehicle_type": t.vehicle_type,
            "fee": str(t.fee),
        },
    )
    db.commit()
    db.refresh(t)
    return t


@router.put("/{template_id}", response_model=FreightTemplateOut)
def update_template(
    template_id: int,
    body: FreightTemplateUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> FreightTemplate:
    t = db.get(FreightTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="未找到该模板")
    # ⚠️ 软删的模板**改不了**（R11-F4）：列表里看不见它，改它只会得到一句「已完成」，
    #    用户以为改好了、界面上却什么都没有（AI 助手走的也是这条路）。
    ensure_alive(t, "运费模板", "POST /freight-templates/{id}/restore")
    before = {"name": t.name, "from_place": t.from_place, "to_place": t.to_place,
              "vehicle_type": t.vehicle_type, "fee": str(t.fee)}
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
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_TEMPLATE_UPSERT,
        change_payload={
            "template_id": t.id,
            "scope": "update",
            "before": before,
            "after": {"name": t.name, "from_place": t.from_place, "to_place": t.to_place,
                      "vehicle_type": t.vehicle_type, "fee": str(t.fee)},
        },
    )
    db.commit()
    db.refresh(t)
    return t


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> None:
    t = db.get(FreightTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="未找到该模板")
    # 伪装删除（v3.26）：模板是下次派单时的参考价，删错了要能原样回来。
    t.is_deleted = True
    t.deleted_at = utc_now_naive()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_TEMPLATE_DELETE,
        change_payload={"template_id": t.id, "name": t.name, "fee": str(t.fee),
                        "note": "伪装删除，可 restore 恢复"},
    )
    db.commit()


@router.post("/{template_id}/restore", response_model=FreightTemplateOut)
def restore_template(
    template_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
) -> FreightTemplate:
    """把删掉的运费模板恢复回来（DELETE /{id} 的逆操作）。"""
    t = db.get(FreightTemplate, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="未找到该模板")
    if not t.is_deleted:
        raise HTTPException(status_code=400, detail="这个模板没有被删除，不需要恢复")
    t.is_deleted = False
    t.deleted_at = None
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.FREIGHT_TEMPLATE_RESTORE,
        change_payload={"template_id": t.id, "name": t.name},
    )
    db.commit()
    db.refresh(t)
    return t
