import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.rbac import Permission, role_has_permission, user_role_key
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Product, User
from app.models.enums import OperationAction, UserRole
from app.api.v1.product_categories import ensure_category
from app.schemas.product_visibility import product_visible_to, visible_product_ids
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate
from app.services.operation_log_service import write_log

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


def product_out(p: Product, role_key: str) -> ProductOut:
    """商品出参：**进价只给管商品的人看**（2026-09-19 审计 R12-H1）。

    ### 为什么要有这个函数
    `ProductOut.cost_price` 原来是**无条件下发**的，而
    - `GET /products`（列表）货主与派单员都能调，
    - `GET /products/{id}`（详情）**只要求登录**——连 `order:create` 都不要求，
    于是司机也能拿到。实测：货主列表里每行都带 `cost_price`；司机 `GET /products/1`
    返回 200 且带 `cost_price: 20.0000`（同一个司机打列表是 403，两个入口两个结论）。

    后果不是"信息多一点"：进价是**报价体系的底牌**，客户拿到它就能算出每一单的加价空间，
    谈判时直接压到成本线；而这条信息一旦发出去，**收不回来**。

    ### 口径
    只有持有 `product:manage` 的角色（派单员）看得到真实进价；其余角色拿到 `null`
    （字段仍在，但值是"未披露"，不是 0——0 会被读成"这东西没成本"，那是个假数）。
    """
    out = ProductOut.model_validate(p)
    if not role_has_permission(role_key, Permission.PRODUCT_MANAGE):
        out.cost_price = None
    return out


@router.get("", response_model=list[ProductOut])
def list_products(
    current: CurrentUser,
    db: Session = Depends(get_db),
    include_inactive: bool = Query(
        False,
        description="含已下架商品（派单员价格管理、货主下单选品目录）",
    ),
) -> list[ProductOut]:
    rk = user_role_key(current)
    # 与全局 RBAC 一致：货主/派单员均可浏览商品目录；派单员在 role_has_permission 中一律放行
    if not role_has_permission(rk, Permission.ORDER_CREATE):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    if include_inactive and rk not in (UserRole.DISPATCHER.value, UserRole.SHIPPER.value):
        include_inactive = False
    q = select(Product).where(Product.is_deleted.is_(False)).order_by(
        case((Product.is_active.is_(True), 0), else_=1),
        Product.id.desc(),
    )
    if not include_inactive:
        q = q.where(Product.is_active.is_(True))
    # 白名单（v3.43）：`custom` 的货主只看到勾选的那些。`None` = 不受限。
    # ⚠️ 过滤放在**这一个**出口上（列表 + 详情都用同一份判据），
    #    否则会出现"列表里看不到、接口还收他的单"——看起来限制了、其实没有。
    ids = visible_product_ids(db, current)
    if ids is not None:
        # 空集合 = 真的什么都不给看（他自己选了自定义却没勾）——照做，不能退化成"全部"
        q = q.where(Product.id.in_(ids or {-1}))
    rows = db.scalars(q).all()
    return [product_out(p, rk) for p in rows]


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    body: ProductCreate,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> Product:
    p = Product(
        name=body.name,
        name_color=body.name_color,
        default_unit_price=body.default_unit_price,
        cost_price=body.cost_price,
        image_url=body.image_url,
        stock=body.stock if body.stock is not None else 0,
        unit=body.unit or "件",
        category=(body.category or "").strip()[:32],
        low_stock_alert=body.low_stock_alert or 0,
    )
    db.add(p)
    db.flush()
    # 新建商品时带了一个名册里没有的分类名 → **自动补进名册**（排到最后）。
    # 不补的话派单员得先建分类、再建商品，两步做完才能用；而且选品页左侧那一列的顺序
    # 来自名册 —— 名单外的分类只能排到最后，用户会以为"我刚建的分类怎么跑最后去了"。
    ensure_category(db, body.category or "")
    # 商品的新建/改动以前**一条日志都不写**（`PRODUCT_CREATE` 枚举存在但没人用）——
    # 于是"这个商品谁建的、什么时候改的价"永远查不到。补上（v3.26）。
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_CREATE,
        change_payload={
            "product_id": p.id,
            "name": p.name,
            "default_unit_price": str(p.default_unit_price),
            "unit": p.unit,
            "stock": p.stock,
        },
    )
    db.commit()
    db.refresh(p)
    return p


@router.get("/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int, current: CurrentUser, db: Session = Depends(get_db)
) -> ProductOut:
    p = db.get(Product, product_id)
    # 软删的商品对普通查询不可见（这正是"删掉了"该有的样子；要恢复走 /restore）
    if p is None or p.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 白名单外的商品：**按"不存在"回**（和软删同一种答复）。
    # 回 403 等于告诉他"有个你看不到的商品"，而白名单的意义就是让他看不到。
    if not product_visible_to(db, current, p.id):
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # ⚠️ 详情原来只要求"登录"，比列表还宽（列表至少要求 order:create）——
    #    同一个司机打列表 403、打详情 200 且带进价（2026-09-19 审计 R12-H1 实测）。
    #    这里不额外收紧"谁能看商品"（下单要看得见商品名和售价），只**按角色裁剪进价**。
    return product_out(p, user_role_key(current))


@router.patch("/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    body: ProductUpdate,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> Product:
    """按请求中**实际出现的字段**更新（含显式 name_color=null 以清除颜色）。"""
    p = db.get(Product, product_id)
    if p is None or p.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # 始终更新所有提供的字段（Pydantic 已验证并转换了值）
    update_data = body.model_dump(exclude_unset=True)
    # 分类/单位先 strip：与创建路径同一口径。不归一的话「饮料」与「饮料  」会是
    # 选品页左侧的**两个不同分类**（列表上看不出差别，只会觉得"怎么多了一组空的"）。
    for short_field in ("category", "unit"):
        if isinstance(update_data.get(short_field), str):
            update_data[short_field] = update_data[short_field].strip()[:32]
    # 改成一个名册里没有的分类名 → 同样自动补进名册（与创建路径同一口径）
    if isinstance(update_data.get("category"), str):
        ensure_category(db, update_data["category"])
    # 改前 → 改后**逐字段**记下来：商品改价是"钱"的事，查不到就等于没留痕（v3.26）。
    changes = []
    for field, value in update_data.items():
        if not hasattr(p, field):
            continue
        old = getattr(p, field)
        if old == value:
            continue
        changes.append({"field": field, "from": str(old), "to": str(value)})
        setattr(p, field, value)
    if changes:
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.PRODUCT_UPDATE,
            change_payload={"product_id": p.id, "name": p.name, "changes": changes},
        )
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
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    """**软删除**商品（可 `POST /{id}/restore` 恢复）。下架请用 PATCH is_active=false。

    ### v3.26 为什么从"物理删除"改成"软删除"
    物理删除那条路有两个问题，第二个是真丢数据：
    1. 它把 `price_rules` 硬删、把订单行/账本的 `product_id` 置空 —— 历史被"改名换姓"；
    2. `Product.inventory_movements` 带 `cascade="all, delete-orphan"`，
       于是**库存流水被整批物理删除**（同一个商品的三种历史：订单留、账本留、流水抹）。

    现在删除只打标记：订单行、账本、库存流水、专属价**全部原样留着**，
    用户发现删错了可以恢复。这条策略和订单的 30 天回收站是同一个取向：
    **删除是"我不想再看到它"，不是"把证据烧掉"。**
    """
    p = db.get(Product, product_id)
    if p is None or p.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    p.is_deleted = True
    p.deleted_at = utc_now_naive()
    p.is_active = False
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_DELETE,
        change_payload={
            "product_id": p.id,
            "name": p.name,
            "stock": p.stock,
            "note": "软删除（可恢复）；库存流水/订单/账本/专属价均未改动",
        },
    )
    db.commit()


@router.post("/{product_id}/restore", response_model=ProductOut)
def restore_product(
    product_id: int,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> Product:
    """把软删除的商品恢复回来（`DELETE /{id}` 的逆操作）。"""
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if not p.is_deleted:
        raise HTTPException(status_code=400, detail="这个商品没有被删除，不需要恢复")
    p.is_deleted = False
    p.deleted_at = None
    p.is_active = True
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_RESTORE,
        change_payload={"product_id": p.id, "name": p.name},
    )
    db.commit()
    db.refresh(p)
    return p
