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

## 车身型式与车辆属性（2026-09-27 · 迁移 010）

用户 2026-09-27：
> 「可以给一辆车**固定一个属性**……在**创建车辆的时候就需要填相应的属性**。
>  **不同的车型会需要填的属性是不同的**……别说有可能是个**平板车**、有可能是一个**自卸车**。」

⚠️ **车型与车身型式是两件事**，所以是两个字段、两套取值：

| 字段 | 取值 | 它回答什么 | 谁在用 |
|---|---|---|---|
| `vehicle_type` | 小货车 / 大货车 / 挂车 | **这辆车按什么算钱** | 司机计费规则 / 运费模板 / 司机应付 / `resolve_billing_mode`（**钱**） |
| `body_type` | 箱式车 / 平板车 / 自卸车 / 挂车 / 未设置 | **这辆车能填哪些属性** | 只有这张台账 |

⛔ **不扩 `vehicle_type` 的取值**：往里塞 `box`/`flat`/`dump` 等于问"箱式车按什么算钱"，
而那个问题从来没有人回答过 —— 答错了不报错，只会让某些司机从固定工资悄悄变成按单计费。

判据（哪些型式能填哪些项、每项叫什么、范围多少）的**唯一实现**在
`services/vehicle_attrs.py`（纯函数 + 单测 `backend/tests/test_vehicle_attrs.py`）；
这个文件只负责取数与落库 —— 与单位换算那边"判据在 services、API 只取数"同一种切法。

### 属性的两条语义（改之前先读）

1. **`POST` 收属性，但不强制填**：一辆还没量过容积的车也照样要能登记。硬性必填会让
   "先把车建出来"被一个还不知道的数卡住，而卡住之后用户只会**瞎填一个数** ——
   那比留空糟得多（留空是"没量过"，瞎填是"量过，是 8 方"）。
2. **`PATCH` 里传了 `attrs` 就是整份替换**（没写进去的属性被清空）。
   ⛔ 不能用 `body.attrs is not None` 判"要不要改"：那样"传了个空对象 = 全部清空"
   就表达不出来 —— 与 `driver_id` 那条 `model_fields_set` 是同一个坑，同一个修法。
   型式与属性**一起校验**（型式决定属性），所以改型式时要么同时把属性改对、
   要么先清掉 —— 分开两步写会留下"型式已换、属性还是旧那批"的中间态，
   而它恰恰是最难查的一种（界面上看着正常，读出来全是错的）。

## 年检台账两格（2026-10-11 · 迁移 033 · FEAT-0022）

用户 2026-10-11：
> 「到我给那个车子建档案的时候会填一下就是这车的**上牌日期**。
>   或者说是**上一个年检日期**啊方便我们去做一个提醒」

所以这里收的是**已经发生过的事实**两格：`registration_date`（上牌日期）/`last_inspection_date`（上次年检日期）。
「下次该检了」**不在这里算**、也不落库 —— 唯一一处在 `services/inspection_due.py`
（API 只做取数与留痕，与折旧「判据在 services、接口只取数」同一种切法）。

* **两格都可以留空**：都空 = 这台车不产生任何年检提醒（⛔ 不许拿今天或建档日期凑一个出来）；
* **`PATCH` 用 `model_fields_set` 逐格判"传没传"**：⛔ 老客户端根本不带这两格，
  把"没传"当成"清空"的后果是「改个车牌就把用户录的年检日期抹掉了」；
* 审计行只在**真的变了**时记（清空记 `→ （清空）`）—— 清空等于这台车从此不再提醒。
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import User, Vehicle
from app.models.enums import OperationAction, UserRole
from app.schemas.accounting_v2 import VehicleCreate, VehicleDriverSet, VehicleOut, VehicleUpdate
from app.api.v1.vehicle_categories import ensure_vehicle_category
from app.services.operation_log_service import write_log
from app.services import usage_service
from app.services import vehicle_attrs as vattrs
from app.services import vehicle_depreciation as vdep

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

_VEHICLE_TYPES = ("small", "large", "trailer", "")
_VEHICLE_CN = {"small": "小货车", "large": "大货车", "trailer": "挂车", "": "未设置车型"}


def _must_dispatcher(current: User) -> None:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")


def _out(db: Session, v: Vehicle) -> VehicleOut:
    u = db.get(User, v.driver_id) if v.driver_id else None
    # 折旧：**能不能算得出来**与**每月多少钱**都由 `services/vehicle_depreciation.py` 一处给
    # （⛔ 接口层不许再写一份"缺哪格"的判断：两处判据迟早不一样，而这里判错的后果是
    #  报表上少一笔钱、或者凭空多一笔）。月额一起给，是为了让用户在编辑抽屉里
    #  当场看到"这一格填下去，每月会变成多少钱"。
    missing = vdep.missing_items(v.purchase_price, v.purchase_date, v.useful_life_years)
    return VehicleOut(
        id=v.id, plate_no=v.plate_no, vehicle_type=v.vehicle_type,
        driver_id=v.driver_id, is_active=v.is_active,
        driver_name=(u.full_name or u.phone or "") if u else "", created_at=v.created_at,
        # 车身型式与属性：中文名与"值怎么显示"都由 `services/vehicle_attrs.py` 一处给，
        # ⛔ 这里和客户端都不许再写一份 when(型式)（两处叫法迟早不一样）。
        body_type=v.body_type or "",
        category=v.category or "",
        body_label=vattrs.body_label(v.body_type),
        attrs=vattrs.attrs_of(v),
        # 折旧台账四格原值 + 现算出来的"算不算得出来 / 每月多少"
        purchase_price=v.purchase_price,
        purchase_date=v.purchase_date,
        useful_life_years=v.useful_life_years,
        residual_rate=v.residual_rate,
        depreciation_covered=not missing,
        depreciation_missing=list(missing),
        depreciation_monthly=vdep.monthly_depreciation(
            v.purchase_price, v.useful_life_years, v.residual_rate
        ),
        # 年检台账两格**原值**（⛔ 不回"下次年检日期"：那是派生量，
        #   见 services/inspection_due.py —— 回一个算出来的日期，客户端就会自己拿它比今天）
        registration_date=v.registration_date,
        last_inspection_date=v.last_inspection_date,
    )


def _clean_body(raw: str | None) -> str:
    """校验车身型式；不合法时把 `vehicle_attrs` 那句中文原样转成 400。

    ⛔ 不许在这里兜一个默认值（比如认不出就 `box`）：那等于替用户认了一辆车的型式，
    而型式决定这辆车能填哪些属性 —— 认错了，用户会在一个错误的表单上填一堆数。
    """
    try:
        return vattrs.clean_body(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


def _clean_attrs(body_type: str, raw: object) -> dict:
    """校验一份属性；不合法时把 `vehicle_attrs` 那句中文原样转成 400。"""
    try:
        return vattrs.parse_attrs(body_type, raw)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


def _clean_depreciation(**raw: object) -> dict:
    """校验折旧台账四格；不合法时把 `vehicle_depreciation` 那句中文**原样**转成 400。

    ⛔ 与 [_clean_body] / [_clean_attrs] 同一条纪律：不在接口层兜默认值，也不让用户看到
    pydantic 的英文结构体 —— 他需要的是一句能照着改的话（「残值率要在 0% 到 50% 之间」）。
    ⛔ 四条规则（>0 / 不晚于今天 / 0.5–30 年 / 0–50%）的**唯一实现**在 services 里，
    这里只负责把 `ValueError` 翻译成 HTTP。
    """
    try:
        return vdep.clean_fields(**raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


def _apply_fields(v: Vehicle, fields: dict) -> None:
    """把校验过的四格写到车上 —— ⛔ `setattr` 这四个字段**只有这一处**。"""
    for key, value in fields.items():
        setattr(v, key, value)


def _date_line(label: str, before: date | None, after: date | None) -> str:
    """一格日期的审计行；**没变就返回空串**（由调用方自己决定要不要 append）。

    与 `_attr_lines` / `vdep.field_lines` 同一条纪律：
    ① 一点都没变就**不记** —— 审计页上"改了但什么都没变"的记录会把真正的改动淹掉；
    ② **清空也要记**（`→ （清空）`）：把上牌日期清空等于「这台车从此不会有年检提醒」，
       而界面上只会少一个日期，看不出后果。
    """
    if (before or None) == (after or None):
        return ""
    was = before.isoformat() if before else None
    now = after.isoformat() if after else None
    if now is None:
        return f"{label} {was} → （清空）"
    if was is None:
        return f"{label} {now}"
    return f"{label} {was} → {now}"


def _inspection_lines(
    before: tuple[date | None, date | None], after: tuple[date | None, date | None]
) -> list[str]:
    """年检两格的审计行（逐格，只记真的变了的那些）—— 形状对齐 `vdep.field_lines`。

    `before` / `after` 都是 `(上牌日期, 上次年检日期)`。⛔ 两格是**互相独立**的：
    清空"上次年检日期"不该顺手把"上牌日期"也抹掉（那是两件不同的事）。
    """
    out: list[str] = []
    for label, was, now in (
        ("上牌日期", before[0], after[0]),
        ("上次年检日期", before[1], after[1]),
    ):
        line = _date_line(label, was, now)
        if line:
            out.append(line)
    return out


def _attr_lines(body_type: str, before: dict[str, str], after: dict) -> list[str]:
    """属性改动怎么记进审计 —— **只记真的变了的**。

    两条纪律（与批发商定价 `price_rules.py` 那一条同源）：
    ① 一点都没变就**不记**：审计页上"改了但什么都没变"的记录会让真正的改动更难找；
    ② **清空也要记**（`→ （清空）`）：把容积从 8 改回"没量过"是一件必须能回查的事 ——
       它等于"这辆车从此没有换算依据"，而界面上只会少一个数。

    ⚠️ 标题一律按**改完之后**的型式取（换型式时旧值那一项的通用名可能对不上，
    比如箱式车→平板车时 `cargo_height_m` 只回落到通用名「货厢高」）。
    这是**刻意的**：写一个旧型式的叫法会让人以为"这项还在"。
    """
    out: list[str] = []
    for f in vattrs.FIELDS:
        was = before.get(f.key)
        now = after.get(f.key)
        now_text = vattrs.format_value(now) if now is not None else None
        if was == now_text:
            continue
        title = vattrs.title_of(f, body_type)
        if now_text is None:
            out.append(f"{title} {was} → （清空）")
        elif was is None:
            out.append(f"{title} {now_text}")
        else:
            out.append(f"{title} {was} → {now_text}")
    return out


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
        # 已停用/已删除的账号不该再绑车（2026-09-19 审计）：删号是**软删**（is_active=False +
        # 手机号加 `_del{id}` 后缀），full_name 原样保留 → 它仍出现在按角色拉的列表里。
        # 绑上去的后果不是报错，而是"这台车看起来有司机、实际没人开"。
        if not getattr(u, "is_active", True):
            raise HTTPException(
                status_code=400,
                detail=f"「{u.full_name or u.phone}」的账号已停用（离职或被删除），不能绑车；请先恢复账号",
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
    # 2026-09-22 统一规则：常用度 → 先创建的在前
    q = usage_service.with_popularity(select(Vehicle), Vehicle, usage_service.KIND_VEHICLE, current)
    return [_out(db, v) for v in db.scalars(q)]


@router.post("", response_model=VehicleOut)
def create_vehicle(body: VehicleCreate, current: CurrentUser, db: Session = Depends(get_db)) -> VehicleOut:
    """新增一辆车（车牌 / 车型 / **车身型式** / **车辆属性** / 司机）。

    ⚠️ 属性是**建车时定下的事实**（用户 2026-09-27：「他的属性是不是**不可能变**；
    也就是说，在**创建车辆的时候就需要填相应的属性**」），所以这个入口收 `attrs`。

    ⛔ 但**不强制填**：一辆还没量过容积的车也照样要能登记（老车、临时借来的车）。
    硬性必填会让"先把车建出来"这件事被一个还不知道的数卡住，而卡住之后
    用户只会瞎填一个数 —— 那比留空糟得多（留空是"没量过"，瞎填是"量过，是 8 方"）。
    """
    _must_dispatcher(current)
    plate = _clean_plate(db, body.plate_no)
    body_type = _clean_body(body.body_type)
    values = _clean_attrs(body_type, body.attrs)
    # 折旧台账四格：**先校验再建对象** —— 校验不过就不该产生一辆半截的车
    # （与属性同一条路：规则与中文话术在 services，这里只落库与留痕）。
    # ⚠️ 四格**都可以留空**（老车、临时借来的车照样要能登记）：缺格不是错误，
    #    它只是让这辆车的折旧"未覆盖"，并在报表里单列说明 —— 见 FEAT-0012 ④。
    fields = _clean_depreciation(
        purchase_price=body.purchase_price,
        purchase_date=body.purchase_date,
        useful_life_years=body.useful_life_years,
        residual_rate=body.residual_rate,
    )
    v = Vehicle(
        plate_no=plate,
        vehicle_type=_clean_type(body.vehicle_type) or "",
        driver_id=None,
        body_type=body_type,
        category=(body.category or "").strip()[:32],
    )
    vattrs.apply_attrs(v, values)
    _apply_fields(v, fields)
    # 年检台账两格：**原样收下**，⛔ 不在这里推"下次年检日期"（派生量，
    #   services/inspection_due.py 现算）。两格都可以留空 —— 都空 = 这台车不产生任何年检提醒。
    v.registration_date = body.registration_date
    v.last_inspection_date = body.last_inspection_date
    db.add(v)
    db.flush()
    # 分类是自由文本，名册只决定"左侧那一列有哪些格、按什么顺序"（见
    # api/v1/vehicle_categories.py）：建车时带了个名册里没有的分类名 → 顺手补进名册。
    ensure_vehicle_category(db, v.category)
    if body.driver_id is not None:
        _apply_driver(db, current, v, body.driver_id)
    lines = [f"车牌 {plate}", f"车型 {_VEHICLE_CN.get(v.vehicle_type, v.vehicle_type)}"]
    if body_type:
        lines.append(f"车身型式 {vattrs.body_label(body_type)}")
    lines.extend(_attr_lines(body_type, {}, values))
    lines.extend(vdep.field_lines({}, fields))  # 建车时就填的台账四格，同样要能回查
    # 建车时就填的年检两格，同样要能回查（清空记「→ （清空）」，这里只会是"填了"）
    lines.extend(_inspection_lines((None, None), (v.registration_date, v.last_inspection_date)))
    _log_upsert(db, current, v, "create", lines)
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
    if body.category is not None:
        want_category = (body.category or "").strip()[:32]
        if want_category != (v.category or ""):
            changed.append(f"分类 {v.category or '（未分类）'} → {want_category or '（未分类）'}")
            v.category = want_category
        ensure_vehicle_category(db, want_category)

    # ⚠️ 这里必须用 `model_fields_set`：`body.driver_id is not None` 分不出
    #    "没传这个键"（不动）和"传了 null"（解绑）——旧代码正是因此**解绑不了司机**。
    if "driver_id" in body.model_fields_set:
        _apply_driver(db, current, v, body.driver_id)

    # ---------------- 车身型式 + 车辆属性 ----------------
    #
    # ⚠️ 两者**相互约束**（型式决定能填哪些项），所以必须**先算出"改完之后长什么样"再一起校验**：
    #    分成两步写的话，会出现"型式先改了、属性还是旧的那批"这种中间态被落库，
    #    而它恰恰是最难查的一种（界面上看着正常，读出来全是错的）。
    want_body = _clean_body(body.body_type) if body.body_type is not None else (v.body_type or "")
    # ⛔ 只有**真的传了 attrs 这个键**才算改属性；没传 = 不动（部分更新语义）。
    #    ⛔ 不能用 `body.attrs is not None`：那样"传了个空对象 = 全部清空"就表达不出来。
    raw_attrs = body.attrs if "attrs" in body.model_fields_set else vattrs.attrs_of(v)
    want_attrs = _clean_attrs(want_body, raw_attrs)
    before_attrs = vattrs.attrs_of(v)
    if want_body != (v.body_type or ""):
        changed.append(
            f"车身型式 {vattrs.body_label(v.body_type)} → {vattrs.body_label(want_body)}"
        )
    changed.extend(_attr_lines(want_body, before_attrs, want_attrs))
    v.body_type = want_body
    vattrs.apply_attrs(v, want_attrs)

    # ---------------- 折旧台账四格（一格一格，清空 = 传空串）----------------
    #
    # ⚠️ 与 `attrs` 的"整份替换"**不同**：这四格各自独立 —— 清空购置日期不该顺手把购置价
    #    也抹掉（那是两件不同的事，用户只会以为自己改坏了）。所以判"要不要改"必须**逐格**
    #    看 `model_fields_set`：`is not None` 分不出"没传这个键"（不动）与"传了空串"（清空），
    #    这正是 `driver_id` 当年解绑不了司机的那个坑，同一个修法。
    #
    # ⚠️ 校验一律看"**改完之后**长什么样"：四格相互独立，但各自都要合法 ——
    #    不能出现"购置价已经改了、购置日期校验失败"这种半截状态（校验在 setattr 之前）。
    before_fields = vdep.fields_of(v)
    after_fields = dict(before_fields)
    touched = False
    for key in vdep.FIELD_KEYS:
        if key in body.model_fields_set:
            after_fields[key] = getattr(body, key)
            touched = True
    if touched:
        want_fields = _clean_depreciation(**after_fields)
        # 只有**真的变了**才记（清空记 `→ （清空）`），与 `_attr_lines` 同一条纪律：
        # 审计页上"改了但什么都没变"的记录会把真正的改动淹掉。
        changed.extend(vdep.field_lines(before_fields, want_fields))
        _apply_fields(v, want_fields)

    # ---------------- 年检台账两格（一格一格；没传 = 不动，传空串 = 清空）--------
    #
    # ⚠️ 判"要不要改"必须**逐格**看 `model_fields_set`，⛔ **不是** `is not None`：
    #    安卓端 `explicitNulls = false`，老客户端与"只改车牌"的常规编辑**根本不带这两格**，
    #    用 `is not None` 就再也表达不出"清空这一格"；反过来若把"没传"当成"清空"，
    #    一次改车牌就会把用户录的年检日期抹掉（这是本条最坏的一种错法）。
    #    与 `driver_id` 解绑、折旧四格是同一个坑、同一个修法。
    before_inspection = (v.registration_date, v.last_inspection_date)
    if "registration_date" in body.model_fields_set:
        v.registration_date = body.registration_date
    if "last_inspection_date" in body.model_fields_set:
        v.last_inspection_date = body.last_inspection_date
    changed.extend(
        _inspection_lines(before_inspection, (v.registration_date, v.last_inspection_date))
    )

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
