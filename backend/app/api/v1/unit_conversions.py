"""单位换算（一车 = 8 方）：列表 / 新增 / 改 / 删（软删）/ 恢复。

用户 2026-09-24：
> 「我们再加一个功能叫做**自动换算单位**……这换算单位啊，我们就把它加在那个添加单位的那个页面当中，
>  添加单位那里再加个按钮可以说**添加单位换算**，那个按钮点进去就是一个**新的弹窗**，
>  就可以在那里设置新的单位换算了。然后我们再计算的时候或者是算账的时候会自动启动换算的功能。」

## 三条约定
1. **全库共用**（不按人分区）：`1 车 = 8 方` 是这车沙子的事实 —— 货主下的单与派单员看的同一张单
   必须显示同一个换算。按人分区会让同一单在两个角色那儿出现两个数。
2. **谁能改**＝`ShipperOrDispatcher`（**货主和派单员**，用户点名了这两个角色）。
   司机没有这个功能（他不下单也不录单位），进来会被角色门槛挡掉。
3. **判据不在这里**：四条规则（非空 / 不同名 / >0 / 一个源单位只能一条 / 反向对不许并存）全在
   `services/unit_conversion.py`（纯函数 + 单测）。这里只负责取数与落库。

⛔ **不加数据库唯一约束**：约束会把"删掉再建同一条"变成 500（`shipper_contacts` 被这个坑逼出了
`_del{id}` 后缀那一套）。这里改成：新增时若发现**被软删过的同一条**，就把它的换算率改过来并放回来
（见 [create_conversion]）—— 用户看到的是"这条换算又生效了"，而不是一句数据库报错。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.database import get_db
from app.deps import require_roles
from app.models import OperationAction, UnitConversion, User
from app.models.enums import UserRole
from app.schemas.unit_conversion import (
    UnitConversionCreate,
    UnitConversionOut,
    UnitConversionUpdate,
)
from app.services import unit_conversion as rules
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/unit-conversions", tags=["unit-conversions"])

#: 谁能管单位换算：**货主和派单员**（用户 2026-09-24 点名的两个角色）。
#: 与 `api/v1/shipper.py` 的 `ShipperOrDispatcher` 是同一个角色集合 —— 下单与录单位都是这批人干的。
UnitOwner = Annotated[User, Depends(require_roles(UserRole.SHIPPER, UserRole.DISPATCHER))]


def _alive(db: Session) -> list[UnitConversion]:
    return list(
        db.scalars(
            select(UnitConversion)
            .where(UnitConversion.is_deleted.is_(False))
            .order_by(UnitConversion.from_unit, UnitConversion.id)
        ).all()
    )


def _pairs(rows: list[UnitConversion]) -> list[rules.ConversionPair]:
    return [rules.pair_of(r.from_unit, r.to_unit, r.factor, r.id) for r in rows]


@router.get("", response_model=list[UnitConversionOut])
def list_conversions(
    current: UnitOwner,
    deleted_only: bool = Query(False, description="只看回收站（删掉的换算可以恢复）"),
    db: Session = Depends(get_db),
) -> list[UnitConversion]:
    """换算表。`deleted_only=true` 时给的是**回收站**（恢复入口要用它，不许只藏在 AI 撤回卡里）。"""
    if deleted_only:
        return list(
            db.scalars(
                select(UnitConversion)
                .where(UnitConversion.is_deleted.is_(True))
                .order_by(UnitConversion.deleted_at.desc(), UnitConversion.id.desc())
            ).all()
        )
    return _alive(db)


@router.post("", response_model=UnitConversionOut, status_code=status.HTTP_201_CREATED)
def create_conversion(
    body: UnitConversionCreate,
    current: UnitOwner,
    db: Session = Depends(get_db),
) -> UnitConversion:
    """新增一条换算。四类不合法的输入由判据给中文；**被删过的同一条会被放回来**（见文件头）。"""
    try:
        from_unit, to_unit = rules.validate_units(body.from_unit, body.to_unit)
        factor = rules.validate_factor(body.factor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    rows = _alive(db)
    reason = rules.conflict_reason(_pairs(rows), from_unit, to_unit)
    if reason:
        raise HTTPException(status_code=409, detail=reason)

    # 删掉过的那一条：把它放回来并改成现在填的换算率。
    # ⚠️ 为什么不是新建一条：那条被删的行还占着"这个源单位"，再建一条会让库里同时存在
    #    两条同源单位的换算（`_alive` 看不到它，但导出/审计里会出现两个数）。
    gone = db.scalars(
        select(UnitConversion).where(
            UnitConversion.is_deleted.is_(True),
            UnitConversion.from_unit == from_unit,
            UnitConversion.to_unit == to_unit,
        )
    ).first()
    if gone is not None:
        gone.factor = factor
        gone.remark = body.remark.strip()
        gone.is_deleted = False
        gone.deleted_at = None
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.UNIT_CONVERSION_UPSERT,
            change_payload={
                "conversion_id": gone.id,
                "from_unit": gone.from_unit,
                "to_unit": gone.to_unit,
                "factor": str(gone.factor),
                "op": "restore_by_create",
            },
        )
        db.commit()
        db.refresh(gone)
        return gone

    row = UnitConversion(
        from_unit=from_unit,
        to_unit=to_unit,
        factor=factor,
        remark=body.remark.strip(),
        created_by=current.id,
    )
    db.add(row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.UNIT_CONVERSION_UPSERT,
        change_payload={
            "conversion_id": row.id,
            "from_unit": row.from_unit,
            "to_unit": row.to_unit,
            "factor": str(row.factor),
            "op": "create",
        },
    )
    db.commit()
    db.refresh(row)
    return row


@router.patch("/{conversion_id}", response_model=UnitConversionOut)
def update_conversion(
    conversion_id: int,
    body: UnitConversionUpdate,
    current: UnitOwner,
    db: Session = Depends(get_db),
) -> UnitConversion:
    """改一条换算（单位名或换算率）。`None` = 不改这一项。"""
    row = db.get(UnitConversion, conversion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if row.is_deleted:
        raise HTTPException(status_code=400, detail="这条换算已经被删除了（在回收站里），不能修改")

    want_from = body.from_unit if body.from_unit is not None else row.from_unit
    want_to = body.to_unit if body.to_unit is not None else row.to_unit
    try:
        from_unit, to_unit = rules.validate_units(want_from, want_to)
        factor = rules.validate_factor(body.factor if body.factor is not None else row.factor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    reason = rules.conflict_reason(_pairs(_alive(db)), from_unit, to_unit, exclude_id=row.id)
    if reason:
        raise HTTPException(status_code=409, detail=reason)

    changes: list[dict] = []
    if from_unit != row.from_unit:
        changes.append({"field": "from_unit", "from": row.from_unit, "to": from_unit})
        row.from_unit = from_unit
    if to_unit != row.to_unit:
        changes.append({"field": "to_unit", "from": row.to_unit, "to": to_unit})
        row.to_unit = to_unit
    if factor != row.factor:
        changes.append({"field": "factor", "from": str(row.factor), "to": str(factor)})
        row.factor = factor
    if body.remark is not None and body.remark.strip() != row.remark:
        changes.append({"field": "remark", "from": row.remark, "to": body.remark.strip()})
        row.remark = body.remark.strip()

    # ⚠️ 一点都没变就**不写日志**：审计页上一条"改了但什么都没变"的记录会让真正的那次改动更难找
    #    （与批发商定价 `price_rules.py` 那条"只在价格真的变了时记"同一条纪律）。
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.UNIT_CONVERSION_UPSERT,
            change_payload={"conversion_id": row.id, "op": "update", "changes": changes},
        )
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{conversion_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversion(conversion_id: int, current: UnitOwner, db: Session = Depends(get_db)) -> None:
    """删掉一条换算（**伪装删除**：行留着，可 `POST /unit-conversions/{id}/restore` 放回来）。"""
    row = db.get(UnitConversion, conversion_id)
    if row is None or row.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    row.is_deleted = True
    row.deleted_at = utc_now_naive()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.UNIT_CONVERSION_DELETE,
        change_payload={
            "conversion_id": row.id,
            "from_unit": row.from_unit,
            "to_unit": row.to_unit,
            "factor": str(row.factor),
        },
    )
    db.commit()


@router.post("/{conversion_id}/restore", response_model=UnitConversionOut)
def restore_conversion(
    conversion_id: int, current: UnitOwner, db: Session = Depends(get_db)
) -> UnitConversion:
    """把删掉的换算放回来（`DELETE` 的逆操作）。

    ⚠️ 恢复时**要重新过一遍冲突判据**：这一条被删掉之后，用户可能已经建了一条同源单位的换算
    （那是允许的 —— 判据只看活着的行）。硬放回来会让库里出现两条同源换算，
    也就是"10 车 ≈ ?"有两个答案。冲突时**如实拒绝**并点名那条挡住它的换算。
    """
    row = db.get(UnitConversion, conversion_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if not row.is_deleted:
        raise HTTPException(status_code=400, detail="这条换算没有被删除，不需要恢复")
    reason = rules.conflict_reason(_pairs(_alive(db)), row.from_unit, row.to_unit)
    if reason:
        raise HTTPException(status_code=409, detail="恢复不了：" + reason)
    row.is_deleted = False
    row.deleted_at = None
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.UNIT_CONVERSION_RESTORE,
        change_payload={
            "conversion_id": row.id,
            "from_unit": row.from_unit,
            "to_unit": row.to_unit,
            "factor": str(row.factor),
        },
    )
    db.commit()
    db.refresh(row)
    return row
