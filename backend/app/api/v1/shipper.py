from typing import Annotated
import json

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import uploads_root
from app.core.business_time import utc_now_naive
from app.core.rbac import user_role_key
from app.core.upload_read import MAX_IMAGE_BYTES, read_limited
from app.api.v1.contact_categories import ensure_contact_category
from app.api.v1.place_categories import ensure_place_category
from app.api.v1.route_categories import ensure_route_category
from app.database import get_db
from app.deps import require_roles
from app.services import place_service, usage_service
from app.services.operation_log_service import write_log
from app.services.soft_delete import del_suffix, ensure_alive
from app.models import OperationAction, ShipperAddress, ShipperContact, ShipperLocation, User
from app.models.enums import UserRole
from app.schemas.place import PlaceOut
from app.schemas.shipper import AddressCreate, AddressOut, AddressUpdate, ContactCreate, ContactOut, ContactUpdate, LocationCreate, LocationImageOut, LocationOut, LocationUpdate

router = APIRouter(prefix="/shipper", tags=["shipper"])

ShipperOrDispatcher = Annotated[User, Depends(require_roles(UserRole.SHIPPER, UserRole.DISPATCHER))]

#: 共享库的**管理**动作（设为共享地址）只有派单员能做 —— 与 `api/v1/places.py` 的
#: 改/撤销/删除同一个角色集合，理由也在那边（共享库全库共用，改它要一个人负责）。
DispatcherOnly = Annotated[User, Depends(require_roles(UserRole.DISPATCHER))]


def _clean_category(value: str | None) -> str:
    """分类名清洗（与 `PlaceCategory` 同一个口径：strip、≤32 字、空=未分类）。"""
    return (value or "").strip()[:32]


def _may_mark_warehouse(user: User) -> bool:
    """只有派单员能把地点标成仓库（见 `update_location` 里的说明）。"""
    return user_role_key(user) == UserRole.DISPATCHER.value


def _apply_images(row, urls: list[str] | None) -> None:
    """写入多图（JSON 数组），并同步兼容字段 image_url = 首图。urls=None 表示不修改。"""
    if urls is None:
        return
    clean = [u for u in urls if isinstance(u, str) and u.strip()]
    row.image_urls = json.dumps(clean)
    row.image_url = clean[0] if clean else None


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
def list_addresses(current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> list[ShipperAddress]:
    # 排序（用户 2026-09-22 定的统一规则）：**常用度优先 → 先创建的在前**。
    # ⚠️ "默认线路"仍在最前（那是用户**明确设过**的偏好，比"用过几次"更硬）；
    #    它下面才轮到常用度、再然后是创建顺序。
    stmt = (
        select(ShipperAddress)
        .where(ShipperAddress.shipper_id == current.id, ShipperAddress.is_deleted.is_(False))
        .order_by(ShipperAddress.is_default.desc())
    )
    rows = db.scalars(usage_service.with_popularity(stmt, ShipperAddress, usage_service.KIND_ADDRESS, current)).all()
    return list(rows)


@router.post("/addresses", response_model=AddressOut, status_code=status.HTTP_201_CREATED)
def create_address(
    body: AddressCreate,
    current: ShipperOrDispatcher,
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
        origin_address=body.origin_address,
        origin_lat=body.origin_lat,
        origin_lng=body.origin_lng,
        category=_clean_category(body.category),
    )
    _apply_images(
        addr,
        body.image_urls if body.image_urls else ([body.image_url] if body.image_url else []),
    )
    db.add(addr)
    # 用户在新建线路时直接敲一个新分类名 = 顺手把它建进名册（与联系人/地点侧同一条）。
    # ⚠️ 名册里没有的分类名不是错误（老数据 / 别处直接写库），所以这里只补、不校验。
    ensure_route_category(db, current.id, addr.category)
    db.commit()
    db.refresh(addr)
    return addr


@router.get("/addresses/{address_id}", response_model=AddressOut)
def get_address(address_id: int, current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> ShipperAddress:
    a = db.get(ShipperAddress, address_id)
    if a is None or a.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return a


@router.patch("/addresses/{address_id}", response_model=AddressOut)
def update_address(
    address_id: int,
    body: AddressUpdate,
    current: ShipperOrDispatcher,
    db: Session = Depends(get_db),
) -> ShipperAddress:
    a = db.get(ShipperAddress, address_id)
    if a is None or a.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")

    # 软删（回收站）里的行**不许再被改**（2026-09-19 审计）：删除是「伪装删除」（行还在库里），
    # 于是这些端点会返回 200、改一条**用户已经看不见的线路** ——
    # 界面上什么都没变，用户以为自己改的是另一条。
    if getattr(a, "is_deleted", False):
        raise HTTPException(status_code=400, detail="这条线路已经被删除了（在回收站里），不能修改")
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
    if body.origin_address is not None:
        a.origin_address = body.origin_address
    if body.origin_lat is not None:
        a.origin_lat = body.origin_lat
    if body.origin_lng is not None:
        a.origin_lng = body.origin_lng
    if body.category is not None:
        a.category = _clean_category(body.category)
        ensure_route_category(db, current.id, a.category)
    # 多图：显式传 image_urls 用新列表；旧客户端传 image_url 单图兼容
    if body.image_urls is not None:
        _apply_images(a, body.image_urls)
    elif body.image_url is not None:
        _apply_images(a, [body.image_url])
    db.commit()
    db.refresh(a)
    return a


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(address_id: int, current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> None:
    a = db.get(ShipperAddress, address_id)
    if a is None or a.shipper_id != current.id or a.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 伪装删除：只打标记，POST /addresses/{id}/restore 能原样返回（v3.26）
    a.is_deleted = True
    a.deleted_at = utc_now_naive()
    a.is_default = False
    db.commit()


@router.post("/addresses/{address_id}/restore", response_model=AddressOut)
def restore_address(address_id: int, current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> ShipperAddress:
    """把删掉的常用地址恢复回来（DELETE /addresses/{id} 的逆操作）。"""
    a = db.get(ShipperAddress, address_id)
    if a is None or a.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if not a.is_deleted:
        raise HTTPException(status_code=400, detail="这条地址没有被删除，不需要恢复")
    a.is_deleted = False
    a.deleted_at = None
    # 2026-10-10（BUG-0032 / 测试台账 TA-14）：删的时候顺手把「默认」清了（理由见
    # services/soft_delete.ensure_alive：默认标记不能留在看不见的行上），恢复时如果
    # **这期间没有任何人当上默认**，就把用户原来那条偏好还回去 —— 不还的话用户得手动
    # 再设一次（第 4 轮实测：删一条默认地址再恢复，diff = {"is_default":[1,0]}）。
    # ⛔ 不抢别人的默认：被删期间别人被设成了默认，就保持不动（那是用户后来的选择）。
    others_default = db.scalar(
        select(func.count())
        .select_from(ShipperAddress)
        .where(
            ShipperAddress.shipper_id == current.id,
            ShipperAddress.is_deleted.is_(False),
            ShipperAddress.is_default.is_(True),
            ShipperAddress.id != a.id,
        )
    )
    if not others_default:
        a.is_default = True
    db.commit()
    db.refresh(a)
    return a


@router.post("/addresses/{address_id}/set-default", response_model=AddressOut)
def set_default_address(address_id: int, current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> ShipperAddress:
    a = db.get(ShipperAddress, address_id)
    if a is None or a.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # ⚠️ 软删的地址**不能设成默认**（R11-F4）：`delete_address` 特意把 `is_default` 置 false
    #    （防止默认标记留在看不见的行上），而这里能一句话把它设回去——
    #    结果是"默认地址"落在一条列表里根本看不见的记录上：下单页取不到默认地址、
    #    地址列表里一条带默认标记的都没有，而接口还回了一张"已设为默认"的卡。
    ensure_alive(a, "地址", "POST /shipper/addresses/{id}/restore")
    _clear_defaults(db, current.id, except_id=address_id)
    a.is_default = True
    db.commit()
    db.refresh(a)
    return a


@router.get("/contacts", response_model=list[ContactOut])
def list_contacts(current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> list[ShipperContact]:
    # 排序（2026-09-22 统一规则）：**常用度优先 → 先创建的在前**
    # （用户原话：「我在下单的时候经常用到这个联系人或者批发商……用得越多越往前」）
    stmt = select(ShipperContact).where(
        ShipperContact.shipper_id == current.id, ShipperContact.is_deleted.is_(False)
    )
    rows = db.scalars(usage_service.with_popularity(stmt, ShipperContact, usage_service.KIND_CONTACT, current)).all()
    return list(rows)


@router.post("/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def upsert_contact(
    body: ContactCreate,
    current: ShipperOrDispatcher,
    db: Session = Depends(get_db),
) -> ShipperContact:
    phone = (body.phone or "").strip()
    name = (body.display_name or "").strip()
    # FEAT-0007：分类与地点那一格同一个口径（strip、≤32 字、空串 = 未分类）。
    category = _clean_category(body.category)
    # L-10 备注：与姓名同一套清洗（strip；长度上限由 ContactCreate.remark 的 max_length 给）。
    remark = (body.remark or "").strip()
    # 姓名和手机号**至少填一个**：两个都空的联系人在列表里是一行认不出、也没法拨的空白。
    # 用户只要求"手机号不必填"，没要求"可以什么都不填"。
    if not phone and not name:
        raise HTTPException(status_code=400, detail="联系人的姓名和手机号至少填一个")
    if phone:
        row = db.scalars(
            select(ShipperContact).where(
                ShipperContact.shipper_id == current.id,
                ShipperContact.phone == phone,
            )
        ).first()
    else:
        # 没填号的行**不能按号认人**（NULL 不参与等值比较，`phone == ""` 谁都不匹配），
        # 改按「同名且同样没填号」认人 —— 否则同一个人的名字会被反复建出一串空号联系人。
        row = db.scalars(
            select(ShipperContact).where(
                ShipperContact.shipper_id == current.id,
                ShipperContact.phone.is_(None),
                ShipperContact.display_name == name,
            )
        ).first()
    if row:
        if name:
            row.display_name = name
        # 分类**只在这次真的给了才覆盖**（空串 = 这次没提分类，不是"改成未分类"）：
        # POST /contacts 是 upsert（按号认人），界面上新建时没选分类，不该把老档案的分类抹掉。
        if category:
            row.category = category
        # 备注（L-10）与分类**同一条**：这次真的给了才覆盖（空串 = 这次没提备注，不是
        # 「把老备注清掉」）—— POST 是 upsert（按号认人），清空备注要走 PATCH。
        if remark:
            row.remark = remark
    else:
        # 空号一律写 NULL，⛔ 不写空串：空串是真值，两条空号会撞 (shipper_id, phone) 唯一约束。
        row = ShipperContact(
            shipper_id=current.id,
            phone=phone or None,
            display_name=name,
            category=category,
            remark=remark,
        )
        db.add(row)
    # 名册里没有这个分类名就顺手补一个（与地点创建同一条：用户敲个新名字 = 建了它）。
    ensure_contact_category(db, current.id, category)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: int,
    body: ContactUpdate,
    current: ShipperOrDispatcher,
    db: Session = Depends(get_db),
) -> ShipperContact:
    c = db.get(ShipperContact, contact_id)
    if c is None or c.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")

    # 软删（回收站）里的行**不许再被改**（2026-09-19 审计）：删除是「伪装删除」（行还在库里），
    # 于是这些端点会返回 200、改一条**用户已经看不见的联系人** ——
    # 界面上什么都没变，用户以为自己改的是另一条。
    if getattr(c, "is_deleted", False):
        raise HTTPException(status_code=400, detail="这条联系人已经被删除了（在回收站里），不能修改")
    # CHG-0010：`None` = 这一项不改；**空串 = 明确要清掉**（界面上把号码删空再保存）。
    # 分开之后"删空保存"不再是一次**静默无效**的写入（改之前空串会被当成"没给这一项"）。
    new_phone = c.phone if body.phone is None else (body.phone.strip() or None)
    new_name = c.display_name if body.display_name is None else body.display_name.strip()
    if not (new_phone or "").strip() and not new_name.strip():
        raise HTTPException(status_code=400, detail="联系人的姓名和手机号至少填一个")
    # ⛔ 先判后写：中途 raise 会让 ORM 上的半截改动留在 session 里（下面还有别的调用方在用）。
    if new_phone and new_phone != c.phone:
        dup = db.scalars(
            select(ShipperContact).where(
                ShipperContact.shipper_id == current.id,
                ShipperContact.phone == new_phone,
            )
        ).first()
        if dup is not None:
            raise HTTPException(status_code=409, detail="该电话已存在已有联系人")
    c.phone = new_phone
    c.display_name = new_name
    # FEAT-0007：分类 —— `None` = 不改；**空串 = 明确清成未分类**（界面上把分类清空再保存）。
    if body.category is not None:
        c.category = _clean_category(body.category)
        ensure_contact_category(db, current.id, c.category)
    # L-10 备注 —— 与分类同一条 PATCH 语义：None = 不改；**空串 = 明确清掉**。
    # ⛔ 清空只能走这里：POST 那边空串代表「这次没提」，抹不掉老备注。
    if body.remark is not None:
        c.remark = body.remark.strip()
    db.commit()
    db.refresh(c)
    return c


@router.post("/locations/image", response_model=LocationImageOut)
async def upload_location_image(
    current: ShipperOrDispatcher,
    file: UploadFile = File(...),
) -> LocationImageOut:
    """上传地点图片（创建订单时随地点信息一并带入）。"""
    from app.api.v1.products import ALLOWED_IMAGE_CT, _sniff_image_mime

    ct = (file.content_type or "").split(";")[0].strip().lower()
    # ⚠️ 限量读（2026-09-23 复核 G8）：原来是 `await file.read()` 再判 4MB
    raw = await read_limited(file, MAX_IMAGE_BYTES, detail="图片过大（最大 4MB）")
    if ct not in ALLOWED_IMAGE_CT or ct in ("", "application/octet-stream"):
        sniffed = _sniff_image_mime(raw[:32])
        if sniffed:
            ct = sniffed
    if ct not in ALLOWED_IMAGE_CT:
        raise HTTPException(status_code=400, detail="不支持的图片类型（请使用 JPG/PNG/WebP）")
    if len(raw) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片过大（最大 4MB）")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        ext = ".jpg"
    sub = uploads_root() / "locations"
    name = f"{uuid4().hex}{ext}"
    path = sub / name
    try:
        sub.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="图片保存失败：服务器无法写入 uploads 目录",
        ) from e
    url = f"/static/uploads/locations/{name}"
    return LocationImageOut(url=url)


@router.get("/locations", response_model=list[LocationOut])
def list_locations(current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> list[ShipperLocation]:
    # 排序（2026-09-22 统一规则）：**常用度优先 → 先创建的在前**
    stmt = select(ShipperLocation).where(
        ShipperLocation.shipper_id == current.id, ShipperLocation.is_deleted.is_(False)
    )
    rows = db.scalars(usage_service.with_popularity(stmt, ShipperLocation, usage_service.KIND_LOCATION, current)).all()
    return list(rows)


@router.post("/locations", response_model=LocationOut, status_code=status.HTTP_201_CREATED)
def create_location(
    body: LocationCreate,
    current: ShipperOrDispatcher,
    db: Session = Depends(get_db),
) -> ShipperLocation:
    loc = ShipperLocation(
        shipper_id=current.id,
        name=body.name,
        detail_address=body.detail_address,
        remark=body.remark,
        address_lat=body.address_lat,
        address_lng=body.address_lng,
        category=_clean_category(body.category),
        is_warehouse=_may_mark_warehouse(current) and body.is_warehouse,
        # 地点绑定的联系人（用户 2026-09-24）：与线路的 receiver_name/phone 同一口径 ——
        # 存快照串，名册（shipper_contacts）只是"给用户挑一个人"的来源，不做外键。
        contact_name=body.contact_name,
        contact_phone=body.contact_phone,
    )
    # 顺手建分类：用户在"保存地点"时直接敲一个新分类名 = 他就是在建分类。
    # 放在 flush 之前不影响；名册里已经有了就什么都不做。
    ensure_place_category(db, current.id, loc.category)
    _apply_images(
        loc,
        body.image_urls if body.image_urls else ([body.image_url] if body.image_url else []),
    )
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


@router.patch("/locations/{location_id}", response_model=LocationOut)
def update_location(
    location_id: int,
    body: LocationUpdate,
    current: ShipperOrDispatcher,
    db: Session = Depends(get_db),
) -> ShipperLocation:
    loc = db.get(ShipperLocation, location_id)
    if loc is None or loc.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")

    # 软删（回收站）里的行**不许再被改**（2026-09-19 审计）：删除是「伪装删除」（行还在库里），
    # 于是这些端点会返回 200、改一条**用户已经看不见的地点** ——
    # 界面上什么都没变，用户以为自己改的是另一条。
    if getattr(loc, "is_deleted", False):
        raise HTTPException(status_code=400, detail="这条地点已经被删除了（在回收站里），不能修改")
    if body.name is not None:
        loc.name = body.name
    if body.detail_address is not None:
        loc.detail_address = body.detail_address
    if body.remark is not None:
        loc.remark = body.remark
    if body.address_lat is not None:
        loc.address_lat = body.address_lat
    if body.address_lng is not None:
        loc.address_lng = body.address_lng
    if body.category is not None:
        loc.category = _clean_category(body.category)
        ensure_place_category(db, current.id, loc.category)
    if body.is_warehouse is not None:
        # ⛔ **只有派单员能标仓库**（用户 2026-09-19：「给**派单员**有一个选择可以选择一个地点
        #    作为仓库」）。货主自己标的话，他随便一条地点就能让"送到这儿=入库"生效 ——
        #    那是**改库存**的口子，必须有明确的权限边界。
        #    给了货主一个 false 只是不许他开；不许他关别人的（他的库里本来也只有他自己的）。
        if body.is_warehouse and not _may_mark_warehouse(current):
            raise HTTPException(status_code=403, detail="只有派单员可以把地点设为仓库")
        loc.is_warehouse = body.is_warehouse
    # 地点绑定的联系人（2026-09-24）：None = 不改，"" = 解绑（与线路那套 PATCH 语义一致）
    if body.contact_name is not None:
        loc.contact_name = body.contact_name
    if body.contact_phone is not None:
        loc.contact_phone = body.contact_phone
    # 多图：显式传 image_urls 用新列表；旧客户端传 image_url 单图兼容
    if body.image_urls is not None:
        _apply_images(loc, body.image_urls)
    elif body.image_url is not None:
        _apply_images(loc, [body.image_url])
    db.commit()
    db.refresh(loc)
    return loc


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: int, current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> None:
    loc = db.get(ShipperLocation, location_id)
    if loc is None or loc.shipper_id != current.id or loc.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 伪装删除：图片等字段原样留着，恢复时逐字段照搬（v3.26）
    loc.is_deleted = True
    loc.deleted_at = utc_now_naive()
    db.commit()


@router.post("/locations/{location_id}/share", response_model=PlaceOut)
def share_location(
    location_id: int,
    current: DispatcherOnly,
    db: Session = Depends(get_db),
) -> PlaceOut:
    """把「我的地点」里的一个地点**设为共享地址**（进全库共用的那张表）。**只有派单员**。

    用户 2026-09-19：「派单员可以改名称，也可以把一些地点给**设置为共享地址**」。

    为什么单独一个端点、而不是让客户端直接打 `POST /places`（那条路三种角色都能走）：
    ① 这条路的**唯一输入是一个地点编号**，坐标/名字/地址都从那条地点上取 ——
       客户端（以及 AI）**没有机会自己编一组坐标**塞进共享库；
    ② 它要有审计（`PLACE_PUBLISH`）与"已并入已有地点"的如实回报，那两件事都需要一个落点。
    合并判据仍然只有一处（`place_service.upsert_place`）。
    """
    loc = db.get(ShipperLocation, location_id)
    if loc is None or loc.shipper_id != current.id or loc.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    try:
        place, merged = place_service.share_location(db, location=loc, operator_id=current.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PLACE_PUBLISH,
        change_payload={
            "location_id": loc.id,
            "place_id": place.id,
            "name": place.name,
            "detail_address": place.detail_address,
            "address_lat": str(place.lat),
            "address_lng": str(place.lng),
            "merged": merged,
            "note": "把「我的地点」里的一个地点设为共享地址（全库共用）",
        },
    )
    db.commit()
    db.refresh(place)
    out = PlaceOut.model_validate(place)
    out.merged = merged
    return out


@router.post("/locations/{location_id}/restore", response_model=LocationOut)
def restore_location(location_id: int, current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> ShipperLocation:
    """把删掉的地点恢复回来（DELETE /locations/{id} 的逆操作）。"""
    loc = db.get(ShipperLocation, location_id)
    if loc is None or loc.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if not loc.is_deleted:
        raise HTTPException(status_code=400, detail="这个地点没有被删除，不需要恢复")
    loc.is_deleted = False
    loc.deleted_at = None
    db.commit()
    db.refresh(loc)
    return loc


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(contact_id: int, current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> None:
    c = db.get(ShipperContact, contact_id)
    if c is None or c.shipper_id != current.id or c.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 伪装删除：行留着（恢复时逐字段照搬），但**手机号要释放出来**——
    # 这张表有 (shipper_id, phone) 唯一约束，不释放的话删掉再加同一个号会直接 500。
    # 和账号删除（users.py 的 _del{id} 后缀）是同一个套路。
    c.is_deleted = True
    c.deleted_at = utc_now_naive()
    # CHG-0010：没填号的行**跳过**这一手 —— NULL 在唯一索引里本来就不互相冲突；
    # 给它编一个 "_del{id}" 反而会把一个假号码写进"电话"列，恢复时还会被当成"原来号是空的"。
    if c.phone:
        c.phone = del_suffix(c.phone, c.id, 32)   # shipper_contacts.phone 是 String(32)
    db.commit()


@router.post("/contacts/{contact_id}/restore", response_model=ContactOut)
def restore_contact(contact_id: int, current: ShipperOrDispatcher, db: Session = Depends(get_db)) -> ShipperContact:
    """把删掉的联系人恢复回来（DELETE /contacts/{id} 的逆操作）。

    手机号冲突时**保留现在的号码**并把冲突写进日志：硬抢回来会把另一个联系人顶掉，
    那是更大的错（和账号恢复同一条规则）。
    """
    c = db.get(ShipperContact, contact_id)
    if c is None or c.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if not c.is_deleted:
        raise HTTPException(status_code=400, detail="这个联系人没有被删除，不需要恢复")
    suffix = f"_del{c.id}"
    # `or ""`：删除时没填号的行走的是 NULL（见 DELETE），endswith 直接调会 AttributeError。
    if (c.phone or "").endswith(suffix):
        want = c.phone[: -len(suffix)]
        if not want:
            # 老数据：号码本来就是空串、删的时候被加了后缀。恢复成 NULL（"没填号"的正解），
            # ⛔ 不写回空串 —— 空串是**真值**，会占掉 (shipper_id, phone) 唯一键的一位。
            c.phone = None
        else:
            taken = db.scalars(
                select(ShipperContact).where(
                    ShipperContact.shipper_id == current.id,
                    ShipperContact.phone == want,
                    ShipperContact.id != c.id,
                    ShipperContact.is_deleted.is_(False),
                )
            ).first()
            if taken is None:
                c.phone = want
    c.is_deleted = False
    c.deleted_at = None
    db.commit()
    db.refresh(c)
    return c
