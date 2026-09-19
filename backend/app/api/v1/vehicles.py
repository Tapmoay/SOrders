"""车辆台账——账本 V2：车牌/车型/挂靠司机。

## 绑定的唯一落点

一辆车最多挂一个司机，落点就是 `vehicles.driver_id`（**不是** `users.vehicle_type`：
车型是"他能开什么车"的计费口径，跟"他现在开哪辆"是两件事，见文末）。

## ⚠️ v3.44 修掉的两条老缺陷（真机上都表现为"界面说改好了、其实没改"）

1. **`PATCH` 不查车牌重复**（只有 `POST` 查）。于是可以把它改成另一个已存在的车牌，
   两台车同号，而"哪台是哪台"再也分不出来——偏偏车牌就是这个台账的主键感。
   现在两边查重，且 `PATCH` 要**排除自己**（不然改车型也会撞上自己的车牌）。

2. **`driver_id=null` 被 `if body.x is not None` 静默忽略 → 解绑司机做不到**。
   旧行为下用户说「把 A12345 从张三名下拿掉」只有两种结局：换成了别人，或者什么都不变。
   现在两条入口都能解绑：
   - `PATCH /vehicles/{id}` 用 `model_fields_set` 认「**显式传 null** = 解绑」
     （没传这个键 = 不动，仍然是部分更新语义）；
   - `POST /vehicles/{id}/driver` 是**专用入口**：`driver_id` 缺省或 null 都 = 解绑。
     为什么要多一条专用入口：安卓端的 JSON 配置是 `explicitNulls = false`
     （见 `core/ApiClient.kt`），`Long?` 字段传 null 会被**整个丢掉**——
     它没法表达"显式 null"。这条入口照抄 `POST /driver-billing-rules/attach`
     的形状（那边也是"缺省/null = 解挂"），两份实现共用 [_apply_driver]，
     校验与留痕只有一份（两条入口给出**同一句**中文错误）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import User, Vehicle
from app.models.enums import OperationAction, UserRole
from app.schemas.accounting_v2 import VehicleCreate, VehicleDriverSet, VehicleOut, VehicleUpdate
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

_VEHICLE_TYPES = ("small", "large", "trailer", "")
_VEHICLE_CN = {"small": "小货车", "large": "大货车", "trailer": "挂车", "": "未设置车型"}


def _must_dispatcher(current: User) -> None:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")


def _out(db: Session, v: Vehicle) -> VehicleOut:
    u = db.get(User, v.driver_id) if v.driver_id else None
    return VehicleOut(
        id=v.id, plate_no=v.plate_no, vehicle_type=v.vehicle_type,
        driver_id=v.driver_id, is_active=v.is_active,
        driver_name=(u.full_name or u.phone or "") if u else "", created_at=v.created_at,
    )


def _clean_plate(db: Session, plate: str, *, exclude_id: int | None = None) -> str:
    """车牌去掉首尾空格并查重。

    ⚠️ 查重必须能**排除自己**：`PATCH` 只改车型时也会带上车牌，
    不排除的话每改一次都会撞上"该车牌已存在"（自己撞自己）。
    """
    out = (plate or "").strip()
    if not out:
        raise HTTPException(status_code=400, detail="请输入车牌号")
    q = select(Vehicle).where(Vehicle.plate_no == out)
    if exclude_id is not None:
        q = q.where(Vehicle.id != exclude_id)
    if db.scalars(q).first() is not None:
        raise HTTPException(status_code=400, detail=f"车牌「{out}」已经被另一辆车用了，请核对是不是同一辆")
    return out


def _clean_type(raw: str | None) -> str | None:
    if raw is None:
        return None
    v = raw.strip()
    if v not in _VEHICLE_TYPES:
        raise HTTPException(status_code=400, detail="车型只能是：小货车 / 大货车 / 挂车")
    return v


def _apply_driver(db: Session, current: User, v: Vehicle, driver_id: int | None) -> None:
    """绑司机 / 解绑司机（**两条入口共用的唯一实现**）。

    三条校验，每一条都对应一种"看着像成功了、其实绑错了"：
    1. 编号不存在 → 绑了个空；
    2. 目标不是司机（是货主/派单员）→ 车上挂着一个永远不出车的人；
    3. 解绑一个本来就没绑的车 → 不是错误，但**什么都不变就不留痕**
       （审计页最怕"（未绑）→（未绑）"这种记录：翻十屏找不到真改动就是它们）。
    """
    before_id = v.driver_id
    before = db.get(User, before_id) if before_id else None
    before_name = (before.full_name or before.phone) if before else None
    if driver_id == before_id:
        # 绑的还是同一个人 / 本来就没人可解 —— 不算错误（用户可能只是想确认），但**不写日志**
        return
    if driver_id is not None:
        u = db.get(User, driver_id)
        if u is None:
            raise HTTPException(status_code=404, detail="未找到该司机")
        if user_role_key(u) != UserRole.DRIVER.value:
            raise HTTPException(
                status_code=400,
                detail=f"「{u.full_name or u.phone}」不是司机账号，车辆只能绑给司机",
            )
        v.driver_id = driver_id
        after_name = u.full_name or u.phone
    else:
        v.driver_id = None
        after_name = None
    db.flush()
    # 留痕走**全库唯一那条路**（`operation_log_service.write_log`）：审计页的口径、
    # 字段名、时间戳都只有一份，自己 `OperationLog(...)` 是踩过的坑（那边没有 change_payload）。
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.VEHICLE_DRIVER_SET,
        change_payload={
            "vehicle_id": v.id,
            "plate_no": v.plate_no,
            "before_driver": before_name,
            "after_driver": after_name,
            "op": "detach" if after_name is None else "attach",
        },
    )


def _log_upsert(db: Session, current: User, v: Vehicle, op: str, changes: list[str]) -> None:
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.VEHICLE_UPSERT,
        change_payload={
            "vehicle_id": v.id,
            "plate_no": v.plate_no,
            "op": op,
            "changes": changes,
        },
    )


@router.get("", response_model=list[VehicleOut])
def list_vehicles(current: CurrentUser, db: Session = Depends(get_db)) -> list[VehicleOut]:
    _must_dispatcher(current)
    return [_out(db, v) for v in db.scalars(select(Vehicle).order_by(Vehicle.id.desc()))]


@router.post("", response_model=VehicleOut)
def create_vehicle(body: VehicleCreate, current: CurrentUser, db: Session = Depends(get_db)) -> VehicleOut:
    _must_dispatcher(current)
    plate = _clean_plate(db, body.plate_no)
    v = Vehicle(plate_no=plate, vehicle_type=_clean_type(body.vehicle_type) or "", driver_id=None)
    db.add(v)
    db.flush()
    if body.driver_id is not None:
        _apply_driver(db, current, v, body.driver_id)
    _log_upsert(db, current, v, "create", [f"车牌 {plate}", f"车型 {_VEHICLE_CN.get(v.vehicle_type, v.vehicle_type)}"])
    db.commit()
    db.refresh(v)
    return _out(db, v)


@router.patch("/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(vehicle_id: int, body: VehicleUpdate, current: CurrentUser, db: Session = Depends(get_db)) -> VehicleOut:
    _must_dispatcher(current)
    v = db.get(Vehicle, vehicle_id)
    if v is None:
        raise HTTPException(status_code=404, detail="车辆不存在")

    changed: list[str] = []
    if body.plate_no is not None:
        plate = _clean_plate(db, body.plate_no, exclude_id=v.id)
        if plate != v.plate_no:
            changed.append(f"车牌 {v.plate_no} → {plate}")
            v.plate_no = plate
    if body.vehicle_type is not None:
        vt = _clean_type(body.vehicle_type)
        if vt != v.vehicle_type:
            changed.append(f"车型 {_VEHICLE_CN.get(v.vehicle_type, v.vehicle_type)} → {_VEHICLE_CN.get(vt, vt)}")
            v.vehicle_type = vt or ""
    if body.is_active is not None and body.is_active != v.is_active:
        changed.append("启用" if body.is_active else "停用")
        v.is_active = body.is_active

    # ⚠️ 这里必须用 `model_fields_set`：`body.driver_id is not None` 分不出
    #    "没传这个键"（不动）和"传了 null"（解绑）——旧代码正是因此**解绑不了司机**。
    if "driver_id" in body.model_fields_set:
        _apply_driver(db, current, v, body.driver_id)

    if changed:
        _log_upsert(db, current, v, "update", changed)
    db.commit()
    db.refresh(v)
    return _out(db, v)


@router.post("/{vehicle_id}/driver", response_model=VehicleOut)
def set_vehicle_driver(
    vehicle_id: int,
    body: VehicleDriverSet,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> VehicleOut:
    """把车绑给某个司机 / 解绑。`driver_id` 缺省或 null **都算解绑**。

    为什么不复用 `PATCH`（两条入口的分工）：
    安卓端 `Json { explicitNulls = false }` 会把 `Long? = null` **整个键丢掉**，
    所以它表达不出"显式 null"。这条专用入口把"缺省 = 解绑"写进契约，
    和 `POST /driver-billing-rules/attach` 完全同形——同一个实现（[_apply_driver]），
    所以两条入口的校验和错误文案不可能分叉。
    """
    _must_dispatcher(current)
    v = db.get(Vehicle, vehicle_id)
    if v is None:
        raise HTTPException(status_code=404, detail="车辆不存在")
    _apply_driver(db, current, v, body.driver_id)
    db.commit()
    db.refresh(v)
    return _out(db, v)
