"""订单图片（地址图 / 送达照片）（orders_media）—— 2026-09-24 整改阶段 4 **纯搬迁**的产物。

从 `api/v1/orders.py` 原样搬来的 2 个函数（upload_order_address_image,upload_delivery_photos）。
除代码组织外**一个字没改** —— URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变；
证据：`_tools/qa/_api_contract_snapshot.py --diff <搬之前> <搬之后>` 契约零差异。

⚠️ 本模块**自己声明** `router`：按文件解析的 AST 工具（端点索引 / AI 能力表）靠这一行算 URL 前缀。
"""

import json
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.rbac import Permission, user_role_key
from app.core.upload_read import MAX_IMAGE_BYTES, read_limited
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.schemas.order import DeliveryPhotoUploadOut, OrderOut
from app.services.operation_log_service import write_log
from app.services import place_service
from app.api.v1.orders_common import (
    UPLOAD_DIR,
    ALLOWED_IMAGE_CT,
    _order_not_deleted_or_404,
    _save_delivery_uploads,
)
from app.api.v1.orders_common import (UPLOAD_DIR, ALLOWED_IMAGE_CT, _save_delivery_uploads, _order_not_deleted_or_404)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("/{order_id}/address-image", response_model=OrderOut)
async def upload_order_address_image(
    order_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
) -> Order:
    """上传收货地址参考图（定位不清时辅助找路）。

    **谁能传**（2026-09-20 扩容）：派单员 / 这单的货主 / **这单的司机**。
    司机加进来是用户点名要的：「司机他也可以去上交补交照片，如果他到了地方没有照片的话，
    他也可以补」—— 到了现场的人正是唯一拍得出"这个门口长什么样"的人。
    （原来只放行前两个角色，司机在订单详情页连入口都没有，只能打电话问路。）

    **照片会同时进「我的地点」**（`place_service.attach_order_photo`）：用户要的是
    「照片跟地点是一样自动保存在库里的」—— 下次下单选到这个位置，图就在库里，
    不用再让每个货主各拍一次。
    """
    order = _order_not_deleted_or_404(db.get(Order, order_id))
    rk = user_role_key(current)
    if (
        rk != UserRole.DISPATCHER.value
        and current.id != order.shipper_id
        and current.id != order.driver_id
    ):
        raise HTTPException(status_code=403, detail="无权操作")
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
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        ext = ".jpg"
    sub = UPLOAD_DIR / str(order_id)
    name = f"{uuid.uuid4().hex}{ext}"
    path = sub / name
    try:
        sub.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="图片保存失败：服务器无法写入 uploads 目录",
        ) from e
    url = f"/static/uploads/delivery/{order_id}/{name}"
    # 多图：拼进 image_urls（JSON 数组），address_image_url 始终指向首图（兼容旧客户端）
    try:
        urls = json.loads(order.image_urls or "[]")
    except Exception:
        urls = []
    if url not in urls:
        urls.append(url)
    order.image_urls = json.dumps(urls, ensure_ascii=False)
    order.address_image_url = urls[0] if urls else url
    # 照片跟着**同一条判据、同一批人**进「我的地点」（用户 2026-09-20：
    # 「照片跟地点是一样是自动保存在库里的」）。代理下单时两边都记 —— 与
    # `remember_order_address` 完全同一批 owner，判据也只有 `place_service` 那一处。
    # 司机传的图也进**货主**的库（司机自己没有"我的地点"这个概念）。
    photo_owners = place_service.attach_order_photo(
        db,
        owner_ids=[current.id, order.shipper_id],
        name=order.address_detail or "",
        detail_address=order.address_detail or "",
        url=url,
        lat=float(order.address_lat) if order.address_lat is not None else None,
        lng=float(order.address_lng) if order.address_lng is not None else None,
    )
    if photo_owners:
        write_log(
            db,
            operator_id=current.id,
            order_id=order.id,
            action=OperationAction.PLACE_AUTO_ADDED,
            change_payload={
                "photo": url,
                "owner_ids": photo_owners,
                "note": "位置照片存进「我的地点」（判据见 place_service.attach_order_photo）",
            },
        )
    db.commit()
    db.refresh(order)
    return order


@router.post("/{order_id}/delivery-photos", response_model=DeliveryPhotoUploadOut)
async def upload_delivery_photos(
    order_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.ORDER_UPLOAD_DELIVERY)),
    files: list[UploadFile] = File(...),
) -> DeliveryPhotoUploadOut:
    order = _order_not_deleted_or_404(
        db.scalars(select(Order).where(Order.id == order_id)).first()
    )
    if user_role_key(current) != UserRole.DRIVER.value or order.driver_id != current.id:
        raise HTTPException(status_code=403, detail="无权操作")
    if order.status != OrderStatus.ACCEPTED:
        raise HTTPException(status_code=400, detail="仅「已接单」订单可上传凭证")
    if not files:
        raise HTTPException(status_code=400, detail="未选择文件")

    urls = await _save_delivery_uploads(order_id, files)
    return DeliveryPhotoUploadOut(urls=urls)
