import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import case, delete, select, update
from sqlalchemy.orm import Session

from app.core.rbac import Permission, role_has_permission, user_role_key
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Ledger, OrderProduct, PriceRule, Product, User
from app.models.enums import UserRole
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate

router = APIRouter(prefix="/products", tags=["products"])

UPLOAD_DIR = Path("uploads") / "products"
ALLOWED_IMAGE_CT = frozenset(
    {
        "image/jpeg",
        "image/jpg",
        "image/pjpeg",
        "image/png",
        "image/webp",
        "image/x-png",
        "image/bmp",
        "image/x-ms-bmp",
    }
)


def _sniff_image_mime(head: bytes) -> str | None:
    """部分浏览器/相册上传时 content-type 为空或为 octet-stream，用文件头判断。"""
    if len(head) >= 3 and head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(head) >= 8 and head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if len(head) >= 2 and head[:2] == b"BM":
        return "image/bmp"
    return None


@router.get("", response_model=list[ProductOut])
def list_products(
    current: CurrentUser,
    db: Session = Depends(get_db),
    include_inactive: bool = Query(
        False,
        description="含已下架商品（派单员价格管理、货主下单选品目录）",
    ),
) -> list[Product]:
    rk = user_role_key(current)
    # 与全局 RBAC 一致：货主/派单员均可浏览商品目录；派单员在 role_has_permission 中一律放行
    if not role_has_permission(rk, Permission.ORDER_CREATE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    if include_inactive and rk not in (UserRole.DISPATCHER.value, UserRole.SHIPPER.value):
        include_inactive = False
    q = select(Product).order_by(
        case((Product.is_active.is_(True), 0), else_=1),
        Product.id.desc(),
    )
    if not include_inactive:
        q = q.where(Product.is_active.is_(True))
    rows = db.scalars(q).all()
    return list(rows)


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    body: ProductCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
) -> Product:
    p = Product(
        name=body.name,
        name_color=body.name_color,
        default_unit_price=body.default_unit_price,
        cost_price=body.cost_price,
        image_url=body.image_url,
        tier_prices=[t.model_dump(mode="json") for t in body.tier_prices],
        stock=body.stock if body.stock is not None else 0,
        unit=body.unit or "件",
        low_stock_alert=body.low_stock_alert or 0,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int, current: CurrentUser, db: Session = Depends(get_db)
) -> Product:
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return p


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    body: ProductUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
) -> Product:
    """按请求中**实际出现的字段**更新（含显式 name_color=null 以清除颜色）。"""
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 始终更新所有提供的字段（Pydantic 已验证并转换了值）
    update_data = body.model_dump(exclude_unset=True)
    if "tier_prices" in update_data and update_data["tier_prices"] is not None:
        update_data["tier_prices"] = [t.model_dump(mode="json") for t in update_data["tier_prices"]]
    for field, value in update_data.items():
        if hasattr(p, field):
            setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return p


@router.post("/{product_id}/image", response_model=ProductOut)
async def upload_product_image(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    file: UploadFile = File(...),
) -> Product:
    """上传商品展示图，写入 image_url（静态路径）。"""
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    ct = (file.content_type or "").split(";")[0].strip().lower()
    raw = await file.read()
    if ct not in ALLOWED_IMAGE_CT or ct in ("", "application/octet-stream"):
        sniffed = _sniff_image_mime(raw[:32])
        if sniffed:
            ct = sniffed
    if ct not in ALLOWED_IMAGE_CT:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片类型：{(file.content_type or '') or '空'}（请使用 JPG/PNG/WebP）",
        )
    if len(raw) > 4 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片过大（最大 4MB）")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        if ct == "image/png":
            ext = ".png"
        elif ct == "image/webp":
            ext = ".webp"
        elif ct in ("image/bmp", "image/x-ms-bmp"):
            ext = ".bmp"
        else:
            ext = ".jpg"
    sub = UPLOAD_DIR / str(product_id)
    name = f"{uuid.uuid4().hex}{ext}"
    path = sub / name
    try:
        sub.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="图片保存失败：服务器无法写入 uploads 目录，请检查进程对该目录的写入权限",
        ) from e
    url = f"/static/uploads/products/{product_id}/{name}"
    p.image_url = url
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
) -> None:
    """永久删除商品（下架请用 PATCH is_active=false）。会清理特殊价、解除订单/账本外键并删除上传目录。"""
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    db.execute(delete(PriceRule).where(PriceRule.product_id == product_id))
    db.execute(
        update(OrderProduct)
        .where(OrderProduct.product_id == product_id)
        .values(product_id=None),
    )
    db.execute(
        update(Ledger).where(Ledger.product_id == product_id).values(product_id=None),
    )
    sub = UPLOAD_DIR / str(product_id)
    if sub.exists():
        shutil.rmtree(sub, ignore_errors=True)
    db.delete(p)
    db.commit()
