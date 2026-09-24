"""orders 路由的**共享底座**（阶段 4 纯搬迁的产物）。

这里只放**几个模块都要用**的助手，不放 router：
· 背景任务助手（`_bg_*`）与上传落盘（`_save_delivery_uploads`）；
· `_get_order_scoped` —— 「这单你能不能看」的唯一实现（读侧按角色卡）。

⛔ 搬迁期间**不许顺手改业务逻辑**：这个文件里的每一行都是从 `orders.py` 原样搬过来的。

### 为什么 router 不在这里（第一版就踩了这个坑）

第一版把唯一的 `router` 放在这个文件、其余模块 import 它。语法上没问题，但**AST 工具会瞎**：
`backend/scripts/gen_endpoint_index.py` 与 `_tools/ai/_gen_ai_read_catalog.py` 都是按
「本文件里有 `router = APIRouter(prefix=…)`」来算 URL 前缀的 —— 于是搬过去的那几个端点
在机器生成的端点索引 / AI 能力表里**整批消失**（实测：索引里 `/api/v1/orders` 一行都没有）。
现在改成每个路由模块自己声明 `router = APIRouter(prefix="/orders", tags=["orders"])`，
由 `orders.py` 用 `include_router` 挂上去 —— 前缀写了两遍，换来所有既有工具零改动。
"""

import uuid
from pathlib import Path
from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from app.core.rbac import user_role_key
from app.core.upload_read import MAX_DELIVERY_PHOTO_BYTES, read_limited
from app.models import Order, User
from app.models.enums import UserRole
from app.services.push_events import (
    push_new_order_to_dispatchers,
    push_driver_ack_shipper,
    push_driver_ack_to_dispatchers,
    push_ledger_updated,
    push_order_freight_updated,
    push_order_edited_to_driver,
    push_navigation_filled,
    push_return_request_closed,
)


async def _bg_ledger_updated_shipper(shipper_id: int) -> None:
    await push_ledger_updated(shipper_id)


UPLOAD_DIR = Path("uploads") / "delivery"
ALLOWED_IMAGE_CT = frozenset({"image/jpeg", "image/png", "image/webp", "image/jpg", "image/pjpeg"})


async def _save_delivery_uploads(order_id: int, files: list[UploadFile]) -> list[str]:
    sub = UPLOAD_DIR / str(order_id)
    sub.mkdir(parents=True, exist_ok=True)
    urls: list[str] = []
    for f in files[:20]:
        ct = (f.content_type or "").split(";")[0].strip().lower()
        if ct not in ALLOWED_IMAGE_CT:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型：{ct}")
        # ⚠️ 限量读（2026-09-23 复核 G8）：原来是无参数 `await f.read()` 再判 8MB ——
        #    "上限"挡的是读进来之后的处理，挡不住内存本身；一次最多 20 张，成倍放大。
        #    提示语保持原来那句「文件过大」不变（客户端已经熟悉它）。
        raw = await read_limited(f, MAX_DELIVERY_PHOTO_BYTES, detail="文件过大")
        ext = Path(f.filename or "").suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            ext = ".jpg"
        name = f"{uuid.uuid4().hex}{ext}"
        path = sub / name
        path.write_bytes(raw)
        urls.append(f"/static/uploads/delivery/{order_id}/{name}")
    return urls


def _get_order_scoped(order_id: int, current: User, db: Session) -> Order:
    order = db.scalars(
        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)
    ).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    role = user_role_key(current)
    # 软删除（隔离区）订单：仅派单员可见可操作；普通用户视为不存在
    if order.deleted_at is not None and role != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    if role == UserRole.SHIPPER.value and (
        order.shipper_id is None or order.shipper_id != current.id
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    if role == UserRole.DRIVER.value and order.driver_id != current.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    # ⚠️ 认不出的角色**一律拒绝**（2026-09-19 审计 R12-L5）：
    #    原来是 if/if 两个分支，role 是第三种值（将来新增角色、或库里出现枚举外的值）时
    #    **两个分支都不进 → 直接放行**，那个角色能读全库订单详情；
    #    而同一个文件的列表接口对这种情况是 403（`list_orders` 的 else 分支）——
    #    同一份判据两处不一致，改一处就会留下一个口子。fail-closed 才对。
    if role not in (UserRole.SHIPPER.value, UserRole.DRIVER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    return order


async def _bg_freight_updated(order_id: int) -> None:
    await push_order_freight_updated(order_id)


async def _bg_notify_driver_ack(shipper_id: int, order_id: int) -> None:
    await push_driver_ack_shipper(shipper_id, order_id)
    await push_driver_ack_to_dispatchers(order_id)


async def _bg_notify_navigation_filled(shipper_id: int, order_id: int, place_name: str) -> None:
    await push_navigation_filled(shipper_id, order_id, place_name)


async def _bg_notify_return_request_closed(request_id: int, amount: str, note: str) -> None:
    """直连退货把那张申请自动关掉之后，告诉货主（2026-09-21 用户拍板的那条规则）。"""
    await push_return_request_closed(request_id, returned_amount=amount, note=note)


async def _bg_notify_new_order(order_id: int) -> None:
    await push_new_order_to_dispatchers(order_id)


async def _bg_notify_order_edited(driver_id: int, order_id: int) -> None:
    """改单（地址/联系人/配送说明）→ 让司机那一页自己重拉（2026-09-24 第 20 轮 C12-3）。"""
    await push_order_edited_to_driver(driver_id, order_id)


def _order_not_deleted_or_404(order: Order | None) -> Order:
    """取到单之后**统一挡掉隔离区（已进回收站）的单**（2026-09-19 审计 R13-D1）。

    ### 为什么需要它
    读侧对所有非派单员是「订单不存在」（`_get_order_scoped`），而司机端的**写路径**
    （送达 / 上传凭证 / 追加备注 / 派单）原来一个都不看 `deleted_at`：
    派单员把一张在途单删进回收站之后（客户催单 → 标记异常 → 删单，是日常操作，
    而且这条删除**没有任何推送**告诉司机），司机手上那一页还停在旧数据，点「送达」返回 **200**：
    库存实扣、账本入账、**司机应付账单生成**，而这张单在司机/货主/派单员的普通查询里都不存在。
    30 天后它被物理清理，那笔 OPEN 应付随之作废——司机白跑一趟，全程无提示。

    ⚠️ 用 404 而不是 403：与读侧同一种答复（"这张单对你来说不存在"），
    否则司机能从状态码差异反推出"有一张我看不到的已删除单"。
    """
    if order is None or order.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    return order
