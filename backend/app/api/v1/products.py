import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.config import uploads_root
from app.core.business_time import utc_now_naive
from app.core.pagination import finish_page
from app.core.rbac import Permission, role_has_permission, user_role_key
from app.core.upload_read import MAX_IMAGE_BYTES, read_limited
from app.database import get_db
from app.deps import CurrentUser, require_permission, require_product_recycle_bin_access
from app.models import OperationLog, Product, ProductCostHistory, ProductCostPrice, User
from app.models.enums import OperationAction, UserRole
from app.api.v1.product_categories import ensure_category
from app.schemas.product_visibility import product_visible_to, visible_product_ids
from app.schemas.product import (
    ProductCostHistoryOut,
    ProductCostPriceCreate,
    ProductCostPriceOut,
    ProductCostPriceUpdate,
    ProductCreate,
    ProductOut,
    ProductUpdate,
)
from app.services import cost_history
from app.services import usage_service
from app.services.cost_history import record_cost
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/products", tags=["products"])

UPLOAD_DIR = uploads_root() / "products"
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
    # ⚠️ 2026-09-25 §9 第②步第四域：这道门原来是**函数体里的**
    #    `if not role_has_permission(rk, Permission.ORDER_CREATE): raise 403`。
    #    现在挂在签名上（`require_permission` 是权限的唯一入口）—— 等价，但它
    #    ① 在端点索引的授权列里读得出来；② 不会再被漏抄/漏改；
    #    ③ 403 文案统一成入口那一份（原来这里是「无权访问」，更含糊）。
    current: Annotated[User, Depends(require_permission(Permission.ORDER_CREATE))],
    _gate: None = Depends(require_product_recycle_bin_access),
    db: Session = Depends(get_db),
    include_inactive: bool = Query(
        False,
        description="含已下架商品（派单员价格管理、货主下单选品目录）",
    ),
    # ⚠️ 2026-10-10 BUG-0035（测试台账 TA-11 / TA-03）：商品删除弹窗一直承诺
    #    「列表顶端的『回收站』里可以把它恢复回来」，而这里**恒过滤 is_deleted=false**、
    #    连一个回收站参数都没有 —— 客户端即便想画那个入口也取不到数据。
    #    两个参数都是**查询参数**（不是新端点）；缺省 false 时行为与加它们之前逐字一致。
    deleted_only: bool = Query(
        False,
        description="只看回收站（被软删的商品，按删除时间倒序）——仅能恢复商品的角色（派单员）",
    ),
    include_deleted: bool = Query(
        False,
        description="连回收站一起看（已删除的排在最后）——仅能恢复商品的角色（派单员）",
    ),
) -> list[ProductOut]:
    rk = user_role_key(current)
    if include_inactive and rk not in (UserRole.DISPATCHER.value, UserRole.SHIPPER.value):
        include_inactive = False
    if deleted_only:
        # ⛔ 回收站分支**不许**再套 is_active 过滤：删除那条路会强制 is_active=False
        #    （见 delete_product），套上去的结果是回收站恒为空 ——
        #    「删掉了，但回收站里也找不到」比没有回收站更让人以为数据丢了。
        # 排序 = 删除时间倒序（刚删的在最上面，用户要找的就是它）；同一时刻按 id 倒序。
        q_bin = (
            select(Product)
            .where(Product.is_deleted.is_(True))
            .order_by(Product.deleted_at.desc(), Product.id.desc())
        )
        # 白名单照旧（None = 不受限；派单员不受限，所以这一条对回收站通常是空操作）
        ids_bin = visible_product_ids(db, current)
        if ids_bin is not None:
            q_bin = q_bin.where(Product.id.in_(ids_bin or {-1}))
        return [product_out(p, rk) for p in db.scalars(q_bin).all()]
    q = select(Product)
    if not include_deleted:
        q = q.where(Product.is_deleted.is_(False))
    if include_deleted:
        # 「连回收站一起看」时已删的一律殿后。它写在 is_active **之前**是有意的：
        # 已删商品一定 is_active=False，不先钉住这一项，它们会与「下架」混在同一段里。
        q = q.order_by(case((Product.is_deleted.is_(False), 0), else_=1))
    q = q.order_by(
        case((Product.is_active.is_(True), 0), else_=1),
        # ⚠️ 顺序 = 在售优先 → **排过序的在前**（小的在前）→ **没排过的排最后**（按 id 倒序，新的在前）。
        #
        # ⛔ 那个 `sort_order == 0` 的 CASE **不是多余的**，它是这一列的正确性所在：
        #    0 = "没排过"（列默认值），而 1 是"排在第 1 位"。只写 `sort_order ASC` 的话，
        #    **0 会排在 1 前面** —— 于是用户在排序页点「置顶」（写 1）反而把它
        #    沉到所有没排过的商品**后面**（实测抓到的：置顶之后前三个变成 36/35/33，
        #    被置顶的 34 直接不见了）。
        #    加了这个 CASE 之后：排过的一律在前、没排过的按 id 倒序殿后；
        #    而"全是 0"（老库、没碰过排序）时这一项恒等，列表与加这一列之前**一字不差**。
        case((Product.sort_order == 0, 1), else_=0),
        Product.sort_order.asc(),
    )
    # 再按 2026-09-22 的统一规则：**常用度 → 先创建的在前**（`id` 升序，见 usage_service）。
    # ⚠️ 它排在**手工排序之后**是有意的：置顶/拖动是用户**明确摆**出来的位置（"我就要它在这儿"），
    #    比"用过几次"更硬的意愿；常用度只在"都没手工排过"的那一批里决定先后。
    #    ⛔ 上一版的 `Product.id.desc()`（新的在前）由这一行取代 —— 用户定的基础序是"先创建的在前"。
    q = usage_service.with_popularity(q, Product, usage_service.KIND_PRODUCT, current)
    if not include_inactive:
        if include_deleted:
            # 缺省只看在售 —— 但「连回收站一起看」时要放行**已删的**：
            # 它们一定 is_active=False，否则上面那一行会把回收站里的行整批滤掉
            # （表现是「删掉的商品在『连回收站一起看』里也不见了」）。
            q = q.where(or_(Product.is_active.is_(True), Product.is_deleted.is_(True)))
        else:
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
        # 「不参与打折」（CHG-0071 / 台账 L-34）：建商品时就能勾；不勾 = False（参与打折）。
        no_discount=bool(body.no_discount),
    )
    db.add(p)
    db.flush()
    # 建商品时填的成本价 = 成本价时间轴的第一段（用户 2026-09-19 要求留痕）。
    # ⚠️ 必须走 `record_cost`（唯一写入口），别在这里直接 `p.cost_price = …`：
    #    绕开它的话价格变了、区间表没变，"这段时间的成本价是多少"从此对不上账。
    record_cost(
        db, p, p.cost_price, source=cost_history.SOURCE_CREATE, operator_id=current.id,
        when=p.created_at or None,
    )
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


# ⛔⛔ **这条路由必须声明在 `@router.get("/{product_id}")` 之前，顺序不能动。**
#
# Starlette 按**声明顺序**匹配：`/products/cost-history` 会被先声明的 `/{product_id}` 接住，
# 然后后端拿 "cost-history" 去转 int → **422**（不是 404，看起来像"参数填错了"），
# 而接口本身完全正常 —— 这类"位置决定行为"的坑正是本项目记过好几次的那种。
# 判据钉在 `_tools/qa/_check_cost_history.py`（它就查这两条路由的先后）。
@router.get("/cost-history", response_model=list[ProductCostHistoryOut])
def product_cost_history(
    response: Response,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    product_id: int | None = Query(None, description="按商品筛；不传 = 全部商品"),
    limit: int = Query(200, ge=1, le=500),
) -> list[ProductCostHistory]:
    """成本价的**生效时间轴**（新的在前）：某个价从什么时候到什么时候、是哪来的。

    用户 2026-09-19：「不仅保留成本价，还保留这个成本价存在的时间…从什么时候开始变、
    从什么时候结束，精确到小时和分钟，这样子我们就能方便且精确地算出来在这段时间的毛利率」。

    ## 为什么是"带 ?product_id= 的列表"而不是 "/products/{id}/cost-history"
    因为 **AI 看不到任何内部编号**（本项目第一条硬规矩）：带路径参数的端点对模型是死的
    （`_gen_ai_read_catalog.py` 明确按"路径里有没有 `{}`"把这类端点排除掉 ——
    暴露了它也只能瞎猜 id）。而这个能力用户明确要求 AI 也要有。
    所以商品用**查询参数**给：模型说商品名 → App 按名字解析成编号 → 调这里。
    商品侧另有 `GET /products/{product_id}/cost-history` 的写法就没有必要了 —— 一条路由两副面孔
    只会让人分不清哪条在生效。

    ⛔ 权限是 `product:manage`（派单员）。成本是内部数：货主与司机连商品详情里的
    `cost_price` 都拿不到（见 `schemas/product.py::ProductOut.cost_price`），这里当然也不能给。
    **不要**为了"方便"把它降成登录即可。
    """
    q = (
        select(ProductCostHistory)
        .order_by(ProductCostHistory.effective_from.desc(), ProductCostHistory.id.desc())
        # 多取一行判截断（2026-09-19 的分页红线）：不给 `X-Truncated` 的话，
        # "这个价改过 200 次以上"会静默变成"就改了 200 次"——而用户正要拿它去对账。
        .limit(limit + 1)
    )
    if product_id is not None:
        q = q.where(ProductCostHistory.product_id == product_id)
    # ⚠️ 不按 `products.is_deleted` 过滤：删掉的是商品，不是"这批货当时的成本是多少"这个事实，
    #    而派单员正是要靠它核对历史订单的毛利 —— 商品删了反而更需要这份记录。
    return finish_page(list(db.scalars(q)), limit, response)


# =====================================================================================
# 商品的**成本价口径**（FEAT-0025，用户 2026-10-11）
#
# 用户原话：「我们是可以设置多个成本价的，AI 也都可以调。只不过我们一般情况下是默认按
# 一个成本价，也就是真实成本价，按那个来计算的……当然，我们有时候计算的时候还有第二个成本价 ——
# 这个成本价可能是加了其他东西、或者比如说有补贴啊等等之后的成本价。所以一定要有多个成本价啊。」
#
# ⛔ 这里的东西**一个字都不参与金额计算**：订单、账单、毛利、快照一律仍按"真实成本价"
#    （`products.cost_price` → 订单行 `cost_price_snapshot` → 毛利只算 `cost_price_snapshot > 0` 的行）。
#    默认那一条在列表里是**合成出来的**（id=0，金额直接取自 products.cost_price）——
#    因此它天然不可改名/改价/删除：改它只有一条路（PATCH /products/{id} 的 cost_price，
#    由 services/cost_history.py::record_cost 写时间轴）。
#
# ⛔ 路由顺序：`GET /cost-prices` 必须声明在 `@router.get("/{product_id}")` 之前（与 cost-history
#    同一个坑：Starlette 按声明顺序匹配，先声明的 `/{product_id}` 会把 "cost-prices" 接住，
#    然后拿它去转 int → 422）。
# =====================================================================================

#: 默认口径在列表里的显示名（它不在 `product_cost_prices` 表里，是 products.cost_price 的投影）
DEFAULT_COST_PRICE_NAME = "真实成本价"
#: 口径说明文案 —— **只在这里写一份**，App 与 AI 卡片都照它显示（⛔ 别在两边各写一套说法）
COST_PRICE_DEFAULT_NOTE = "订单与毛利按它算（真实成本价）"
COST_PRICE_EXTRA_NOTE = "参考口径：不参与订单与毛利的计算"


def _cost_price_out(cost_row: ProductCostPrice) -> ProductCostPriceOut:
    """表里的一条附加口径。"""
    return ProductCostPriceOut(
        id=cost_row.id,
        product_id=cost_row.product_id,
        name=cost_row.name,
        cost_price=cost_row.cost_price,
        sort_order=cost_row.sort_order,
        is_default=False,
        note=COST_PRICE_EXTRA_NOTE,
    )


def _default_cost_price_out(p: Product) -> ProductCostPriceOut:
    """**合成**默认那一条（id=0、is_default=True）。

    为什么不在库里也存一行：存了就有两份真值 —— 而"订单与毛利按哪个算"只允许有一个答案。
    `sort_order=-1` 让它永远排在最前（客户端就算自己按 sort_order 排也不会把它挤下去）。
    """
    return ProductCostPriceOut(
        id=0,
        product_id=p.id,
        name=DEFAULT_COST_PRICE_NAME,
        cost_price=p.cost_price,
        sort_order=-1,
        is_default=True,
        note=COST_PRICE_DEFAULT_NOTE,
    )


def _cost_product_or_404(db: Session, product_id: int) -> Product:
    p = db.get(Product, product_id)
    if p is None or p.is_deleted:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return p


def _cost_row_or_404(db: Session, row_id: int, *, include_deleted: bool = False) -> ProductCostPrice:
    cost_row = db.get(ProductCostPrice, row_id)
    # 软删的那些对普通查询不可见（与商品同一条语义）；回收站的入口显式传 include_deleted=True
    if cost_row is None or (cost_row.is_deleted and not include_deleted):
        raise HTTPException(status_code=404, detail="未找到对应记录")
    return cost_row


def _cost_row_by_name(db: Session, product_id: int, name: str) -> ProductCostPrice | None:
    """按（商品, 名字）找那一条。

    ⚠️ **不过滤 is_deleted**：软删的行仍然占着 `(product_id, name)` 唯一约束（不能像联系人
    那样把键改名，改了就对不上"是哪个口径"了）—— 所以"再设一次同名的价"必须**复活那一行**，
    而不是插一条新的（插会直接撞唯一约束报 500）。这与 `price_rules` 的 upsert 同一条口径。
    """
    return db.scalars(
        select(ProductCostPrice).where(
            ProductCostPrice.product_id == product_id,
            ProductCostPrice.name == name,
        )
    ).first()


def _next_cost_sort(db: Session, product_id: int) -> int:
    """新加的口径排到最后（用户不填顺序时）——"先加的在前"比"按 id 倒序"更像他心里的顺序。"""
    biggest = db.scalar(
        select(func.max(ProductCostPrice.sort_order)).where(
            ProductCostPrice.product_id == product_id
        )
    )
    return int(biggest or 0) + 1


@router.get("/cost-prices", response_model=list[ProductCostPriceOut])
def product_cost_prices(
    response: Response,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    product_id: int | None = Query(None, description="按商品筛；不传 = 全部商品的附加口径"),
    deleted_only: bool = Query(False, description="只看回收站里被删掉的那些"),
    limit: int = Query(200, ge=1, le=500),
) -> list[ProductCostPriceOut]:
    """某个商品的**成本价口径**列表：第一条永远是默认口径（真实成本价）。

    ## 口径（用户 2026-10-11 的原话就是这三句）
    · **默认那个＝真实成本价**：订单与毛利按它算（`note` 字段里写死这句话）；
    · 其余的（"返点后成本" / "补贴后成本"…）是**参考口径**：一个字节都不参与金额计算；
    · 一个商品可以有**多个**，⛔ 不再是"只能留一个"。

    ## 为什么是"带 ?product_id= 的列表"而不是 "/products/{id}/cost-prices"
    与 `/products/cost-history` 同一条硬规矩：**AI 看不到任何内部编号**，带路径参数的端点
    对模型是死的（`_gen_ai_read_catalog.py` 按"路径里有没有 `{}`"排除）。商品走查询参数之后，
    模型说商品名 → App 解析成编号 → 调同一条路由。**AI 必须能设第二个成本价**正是本单要治的痛。

    ⛔ 权限是 `product:manage`（派单员）。成本是内部数：货主与司机连商品详情里的
    `cost_price` 都拿不到，这里当然也不能给。
    """
    q = (
        select(ProductCostPrice)
        .order_by(
            ProductCostPrice.product_id.asc(),
            ProductCostPrice.sort_order.asc(),
            ProductCostPrice.id.asc(),
        )
        # 多取一行判截断（2026-09-19 分页红线）：不给 X-Truncated 的话，
        # "这个商品有 200 多条口径"会静默变成"就 200 条"。
        .limit(limit + 1)
    )
    q = q.where(ProductCostPrice.is_deleted.is_(deleted_only))
    if product_id is not None:
        # 回收站里看的是"删掉的口径"，此时不合成默认那条（它不是可删的行）
        p = None if deleted_only else _cost_product_or_404(db, product_id)
        q = q.where(ProductCostPrice.product_id == product_id)
    else:
        p = None

    items = [_cost_price_out(r) for r in db.scalars(q)]
    if p is not None:
        # 默认口径排在最前 —— 用户要一眼看到"订单/毛利按哪个算"
        items.insert(0, _default_cost_price_out(p))
    return finish_page(items, limit, response)


@router.post(
    "/{product_id}/cost-prices",
    response_model=ProductCostPriceOut,
    status_code=status.HTTP_201_CREATED,
)
def upsert_product_cost_price(
    product_id: int,
    body: ProductCostPriceCreate,
    response: Response,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> ProductCostPriceOut:
    """新增或**改价**一条附加成本口径（按名字 upsert：有就改、没有就建）。

    · 回收站里已经有一条同名的 → **把它放回来并改成这个价**（唯一约束让它没有第二种做法）；
    · 返回码：建出来是 **201**，改的是 **200**（客户端据此知道是"新增"还是"改了已有的"）；
    · ⛔ 这个名字**不许**叫默认那个口径（"真实成本价"）：那是 `products.cost_price`，
      改它只有一条路（PATCH /products/{id} 的 cost_price，会写成本价时间轴）。
    """
    p = _cost_product_or_404(db, product_id)
    if body.name == DEFAULT_COST_PRICE_NAME:
        raise HTTPException(
            status_code=409,
            detail=(
                f"「{DEFAULT_COST_PRICE_NAME}」是默认口径（订单与毛利按它算），"
                "不在这张表里 —— 要改它请直接改商品的成本价"
            ),
        )

    cost_row = _cost_row_by_name(db, product_id, body.name)
    if cost_row is not None:
        before = str(cost_row.cost_price)
        was_deleted = cost_row.is_deleted
        cost_row.cost_price = body.cost_price
        if body.sort_order is not None:
            cost_row.sort_order = body.sort_order
        if was_deleted:
            cost_row.is_deleted = False
            cost_row.deleted_at = None
        response.status_code = status.HTTP_200_OK
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.PRODUCT_COST_PRICE_UPSERT,
            change_payload={
                "product_id": p.id,
                "product_name": p.name,
                "cost_price_id": cost_row.id,
                "name": cost_row.name,
                "changes": {"cost_price": [before, str(cost_row.cost_price)]},
                "restored": was_deleted,
                "note": "附加成本口径：不参与订单与毛利的计算",
            },
        )
        db.commit()
        db.refresh(cost_row)
        return _cost_price_out(cost_row)

    cost_row = ProductCostPrice(
        product_id=product_id,
        name=body.name,
        cost_price=body.cost_price,
        sort_order=(
            body.sort_order if body.sort_order is not None else _next_cost_sort(db, product_id)
        ),
    )
    db.add(cost_row)
    db.flush()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_COST_PRICE_UPSERT,
        change_payload={
            "product_id": p.id,
            "product_name": p.name,
            "cost_price_id": cost_row.id,
            "name": cost_row.name,
            "cost_price": str(cost_row.cost_price),
            "note": "附加成本口径：不参与订单与毛利的计算",
        },
    )
    db.commit()
    db.refresh(cost_row)
    return _cost_price_out(cost_row)


@router.patch("/cost-prices/{row_id}", response_model=ProductCostPriceOut)
def update_product_cost_price(
    row_id: int,
    body: ProductCostPriceUpdate,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> ProductCostPriceOut:
    """改名 / 改价 / 改顺序（**部分更新**：只动请求里真的出现的字段）。

    ⛔ 改名撞上同商品已有的名字 → **409**（含糊地合并两条价会让用户以为改错了行）；
    改名撞上**回收站里**的名字也拒绝，并在话里说清"回收站里有一条同名的，先把它放回来"。
    """
    cost_row = _cost_row_or_404(db, row_id)
    data = body.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="没有要改的内容（名称、金额、顺序至少要给一个）")

    p = db.get(Product, cost_row.product_id)
    changes: dict[str, list[str]] = {}

    if data.get("name") is not None and data["name"] != cost_row.name:
        clash = _cost_row_by_name(db, cost_row.product_id, data["name"])
        if clash is not None and clash.id != cost_row.id:
            if clash.is_deleted:
                raise HTTPException(
                    status_code=409,
                    detail=f"回收站里已经有一条叫「{data['name']}」的成本价了，先把它放回来（或换个名字）",
                )
            raise HTTPException(
                status_code=409, detail=f"这个商品已经有一条叫「{data['name']}」的成本价了"
            )
        changes["name"] = [cost_row.name, data["name"]]
        cost_row.name = data["name"]

    if data.get("cost_price") is not None and data["cost_price"] != cost_row.cost_price:
        changes["cost_price"] = [str(cost_row.cost_price), str(data["cost_price"])]
        cost_row.cost_price = data["cost_price"]

    if data.get("sort_order") is not None and data["sort_order"] != cost_row.sort_order:
        changes["sort_order"] = [str(cost_row.sort_order), str(data["sort_order"])]
        cost_row.sort_order = data["sort_order"]

    if changes:
        db.flush()
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.PRODUCT_COST_PRICE_UPDATE,
            change_payload={
                "product_id": cost_row.product_id,
                "product_name": p.name if p else "",
                "cost_price_id": cost_row.id,
                "name": cost_row.name,
                "changes": changes,
                "note": "附加成本口径：不参与订单与毛利的计算",
            },
        )
    db.commit()
    db.refresh(cost_row)
    return _cost_price_out(cost_row)


@router.delete("/cost-prices/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product_cost_price(
    row_id: int,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> Response:
    """**软删**一条附加成本口径（行还在，可 `POST /products/cost-prices/{id}/restore` 放回来）。

    ⛔ 默认那条口径不在本表里，所以这里**删不到它**（想"不再用它"是另一件事：
    订单与毛利的口径不许被随手关掉）。
    """
    cost_row = _cost_row_or_404(db, row_id)
    p = db.get(Product, cost_row.product_id)
    cost_row.is_deleted = True
    cost_row.deleted_at = utc_now_naive()
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_COST_PRICE_DELETE,
        change_payload={
            "product_id": cost_row.product_id,
            "product_name": p.name if p else "",
            "cost_price_id": cost_row.id,
            "name": cost_row.name,
            "cost_price": str(cost_row.cost_price),
            "note": "软删（伪装删除）：行还在，可以恢复",
        },
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/cost-prices/{row_id}/restore", response_model=ProductCostPriceOut)
def restore_product_cost_price(
    row_id: int,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> ProductCostPriceOut:
    """把回收站里的那条口径**原样放回来**（逐字段照搬，不重建）。"""
    cost_row = _cost_row_or_404(db, row_id, include_deleted=True)
    if not cost_row.is_deleted:
        raise HTTPException(status_code=400, detail="这一条没有在回收站里，不需要恢复")
    p = db.get(Product, cost_row.product_id)
    cost_row.is_deleted = False
    cost_row.deleted_at = None
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_COST_PRICE_RESTORE,
        change_payload={
            "product_id": cost_row.product_id,
            "product_name": p.name if p else "",
            "cost_price_id": cost_row.id,
            "name": cost_row.name,
            "cost_price": str(cost_row.cost_price),
        },
    )
    db.commit()
    db.refresh(cost_row)
    return _cost_price_out(cost_row)


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
    # 成本价**单独处理**：它还要维护"生效区间"（见 services/cost_history.py），
    # 不能跟着下面这个通用循环 setattr —— 那样区间表就缺了一段，而且是静默的。
    cost_before = p.cost_price
    if "cost_price" in update_data:
        cost_new = update_data.pop("cost_price")
        if cost_new is not None and record_cost(
            db, p, cost_new, source=cost_history.SOURCE_MANUAL, operator_id=current.id
        ):
            changes.append({"field": "cost_price", "from": str(cost_before), "to": str(p.cost_price)})
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
    # ⚠️ 限量读（2026-09-23 复核 G8）：原来是 `await file.read()` 再判 4MB ——
    #    "上限"挡的是读进来之后的处理，挡不住内存本身。
    #    下面那句按前 32 字节嗅探类型仍然成立（我们本来就只读回了一小段）。
    raw = await read_limited(file, MAX_IMAGE_BYTES, detail="图片过大（最大 4MB）")
    if ct not in ALLOWED_IMAGE_CT or ct in ("", "application/octet-stream"):
        sniffed = _sniff_image_mime(raw[:32])
        if sniffed:
            ct = sniffed
    if ct not in ALLOWED_IMAGE_CT:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片类型：{(file.content_type or '') or '空'}（请使用 JPG/PNG/WebP）",
        )
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
    # ⚠️ 先把"删除前它是不是上架的"记下来（2026-09-23 复核 K6）：删除会强制下架
    #    （`is_active=False`），而恢复原来**无条件**把它设回上架 —— 于是"我当初是
    #    刻意把它下架的，后来删掉，再恢复"会静默变成"它又回到货架上了"。
    #    这条事实以前只在 `note` 里写了一句人话，机器读不回来，所以恢复只能猜。
    was_active = bool(p.is_active)
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
            # 恢复时要照它还原（见 `restore_product` / `_was_active_before_delete`）
            "was_active": was_active,
            "note": "软删除（可恢复）；库存流水/订单/账本/专属价均未改动",
        },
    )
    db.commit()


def _was_active_before_delete(db: Session, product_id: int) -> bool | None:
    """这一次删除之前，这个商品是上架的吗 —— 从**审计日志**里读回来。

    为什么不新加一列：`schema_bootstrap.py` 是核心区（加列要连带 MySQL 迁移），
    而"删除前是什么状态"本来就是审计日志该记住的事实。以前那条 `PRODUCT_DELETE` 日志
    只记了 id / 名字 / 库存，**唯独没记它当时是上架还是下架**，所以恢复只能无条件上架。

    取值口径：扫最近 [LOOKBACK] 条 `PRODUCT_DELETE`，取**第一条属于这个商品**的
    （= 最近一次删除；先删后恢复再来一轮也能对上）。
    读不到（历史数据、日志已过保留期）→ `None`，由调用方按"不上架"处理（fail-closed：
    宁可让用户手动上架一次，也不许把一个他刻意下架的商品悄悄放回货架）。
    """
    LOOKBACK = 500
    rows = db.scalars(
        select(OperationLog)
        .where(OperationLog.action == OperationAction.PRODUCT_DELETE.value)
        .order_by(OperationLog.id.desc())
        .limit(LOOKBACK)
    ).all()
    for row in rows:
        try:
            payload = json.loads(row.change_content or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("product_id") == product_id:
            if "was_active" not in payload:
                return None  # 这条日志是加 was_active 之前写的 → 不知道，别猜
            return bool(payload["was_active"])
    return None


@router.post("/{product_id}/restore", response_model=ProductOut)
def restore_product(
    product_id: int,
    current: User = Depends(require_permission(Permission.PRODUCT_MANAGE)),
    db: Session = Depends(get_db),
) -> Product:
    """把软删除的商品恢复回来（`DELETE /{id}` 的逆操作）。

    ⚠️ **恢复 = 还原，不是"顺手重新上架"**（2026-09-23 复核 K6）：
    删除会强制下架，但"删除"和"下架"是两件事（用户可能先刻意下架、之后才删）。
    所以这里把 `is_active` 还原成**删除前**的值（从那条 `PRODUCT_DELETE` 日志里读回来）；
    读不到就**保持下架**（fail-closed）—— 宁可多一次手动上架，也不许把他刻意下架的商品
    悄悄放回货架（那会让它在选品页/下单页重新出现，而他以为自己早就下架了）。
    """
    p = db.get(Product, product_id)
    if p is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    if not p.is_deleted:
        raise HTTPException(status_code=400, detail="这个商品没有被删除，不需要恢复")
    was_active = _was_active_before_delete(db, product_id)
    p.is_deleted = False
    p.deleted_at = None
    p.is_active = bool(was_active)  # None（读不到）→ 保持下架
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.PRODUCT_RESTORE,
        change_payload={
            "product_id": p.id,
            "name": p.name,
            "was_active": was_active,
            "restored_active": p.is_active,
            "note": "恢复只还原状态，不会把刻意下架的商品重新上架"
            if not p.is_active
            else "删除前它就是上架的，已一并还原",
        },
    )
    db.commit()
    db.refresh(p)
    return p
