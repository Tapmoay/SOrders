from typing import Annotated
import json

from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.rbac import user_role_key
from app.api.v1.place_categories import ensure_place_category
from app.database import get_db
from app.deps import require_roles
from app.services.soft_delete import del_suffix, ensure_alive
from app.models import ShipperAddress, ShipperContact, ShipperLocation, User
from app.models.enums import UserRole
from app.schemas.shipper import AddressCreate, AddressOut, AddressUpdate, ContactCreate, ContactOut, ContactUpdate, LocationCreate, LocationImageOut, LocationOut, LocationUpdate

router = APIRouter(prefix="/shipper", tags=["shipper"])

ShipperOrDispatcher = Annotated[User, Depends(require_roles(UserRole.SHIPPER, UserRole.DISPATCHER))]


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
    rows = db.scalars(
        select(ShipperAddress)
        .where(ShipperAddress.shipper_id == current.id, ShipperAddress.is_deleted.is_(False))
        .order_by(ShipperAddress.is_default.desc(), ShipperAddress.id.desc())
    ).all()
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
    )
    _apply_images(
        addr,
        body.image_urls if body.image_urls else ([body.image_url] if body.image_url else []),
    )
    db.add(addr)
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
    rows = db.scalars(
        select(ShipperContact)
        .where(ShipperContact.shipper_id == current.id, ShipperContact.is_deleted.is_(False))
        .order_by(ShipperContact.id.desc())
    ).all()
    return list(rows)


@router.post("/contacts", response_model=ContactOut, status_code=status.HTTP_201_CREATED)
def upsert_contact(
    body: ContactCreate,
    current: ShipperOrDispatcher,
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
    new_phone = body.phone.strip() if body.phone and body.phone.strip() else None
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
    if body.display_name is not None:
        c.display_name = body.display_name.strip()
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
    raw = await file.read()
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
    sub = Path("uploads") / "locations"
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
    rows = db.scalars(
        select(ShipperLocation)
        .where(ShipperLocation.shipper_id == current.id, ShipperLocation.is_deleted.is_(False))
        .order_by(ShipperLocation.id.desc())
    ).all()
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
    if c.phone.endswith(suffix):
        want = c.phone[: -len(suffix)]
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
