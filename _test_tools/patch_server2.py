# -*- coding: utf-8 -*-
"""服务器手术补丁 v2：软删除隔离/3年保留/图片压缩/静态handler（与本地 p 分支同步，逐处唯一校验）"""
import io

PAIRS = [
# ---------- enums.py ----------
("/opt/SOrders/backend/app/models/enums.py",
 "    ORDER_COMPLETE = \"ORDER_COMPLETE\"\n    ORDER_CANCEL = \"ORDER_CANCEL\"",
 "    ORDER_COMPLETE = \"ORDER_COMPLETE\"\n    ORDER_CANCEL = \"ORDER_CANCEL\"\n    ORDER_DELETE = \"ORDER_DELETE\"\n    ORDER_RESTORE = \"ORDER_RESTORE\""),
# ---------- models/order.py : deleted_at ----------
("/opt/SOrders/backend/app/models/order.py",
 "    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)",
 "    # 软删除隔离时间：用户删除后 30 天内隔离（用户不可见），派单员可恢复；到期后物理清理\n    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)\n\n    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)"),
# ---------- schemas/order.py : OrderOut.deleted_at ----------
("/opt/SOrders/backend/app/schemas/order.py",
 "    damage_note: str = \"\"  # 送达货损备注（公司自担）\n    image_urls: list[str] = []  # 收货地址参考图（多图，JSON 数组）",
 "    damage_note: str = \"\"  # 送达货损备注（公司自担）\n    image_urls: list[str] = []  # 收货地址参考图（多图，JSON 数组）\n    deleted_at: datetime | None = None  # 软删除隔离时间（派单员可查，用户不可见）"),
# ---------- orders.py : import ----------
("/opt/SOrders/backend/app/api/v1/orders.py",
 "from app.services.cancelled_order_retention import delete_orders_by_ids",
 "from app.services.data_retention import delete_orders_by_ids"),
# ---------- orders.py : _get_order_scoped 隔离 ----------
("/opt/SOrders/backend/app/api/v1/orders.py",
 "    role = user_role_key(current)\n    if role == UserRole.SHIPPER.value and (\n        order.shipper_id is None or order.shipper_id != current.id\n    ):",
 "    role = user_role_key(current)\n    # 软删除（隔离区）订单：仅派单员可见可操作；普通用户视为不存在\n    if order.deleted_at is not None and role != UserRole.DISPATCHER.value:\n        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=\"订单不存在\")\n    if role == UserRole.SHIPPER.value and (\n        order.shipper_id is None or order.shipper_id != current.id\n    ):"),
# ---------- orders.py : 签名 include_deleted ----------
("/opt/SOrders/backend/app/api/v1/orders.py",
 "    limit: int | None = Query(None, ge=1, le=5000, description=\"返回条数上限（待派池缺省=300，其余缺省=全量）\"),\n) -> list[OrderOut]:\n    role = user_role_key(current)",
 "    limit: int | None = Query(None, ge=1, le=5000, description=\"返回条数上限（待派池缺省=300，其余缺省=全量）\"),\n    include_deleted: bool = Query(False, description=\"含软删除(隔离区)订单——仅派单员\"),\n    deleted_only: bool = Query(False, description=\"仅软删除(回收站)订单——仅派单员\"),\n) -> list[OrderOut]:\n    role = user_role_key(current)\n    if (include_deleted or deleted_only) and role != UserRole.DISPATCHER.value:\n        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=\"无权查看隔离数据\")"),
# ---------- orders.py : 搜索分支过滤 ----------
("/opt/SOrders/backend/app/api/v1/orders.py",
 "        elif shipper_id_filter is not None:\n            stmt = stmt.where(Order.shipper_id == shipper_id_filter)\n        if effective_limit is not None:",
 "        elif shipper_id_filter is not None:\n            stmt = stmt.where(Order.shipper_id == shipper_id_filter)\n        if deleted_only:\n            stmt = stmt.where(Order.deleted_at.isnot(None))\n        elif not include_deleted:\n            stmt = stmt.where(Order.deleted_at.is_(None))\n        if effective_limit is not None:"),
# ---------- orders.py : 主查询过滤 ----------
("/opt/SOrders/backend/app/api/v1/orders.py",
 "    q = select(Order).options(selectinload(Order.order_products)).order_by(Order.id.desc())\n\n    if role == UserRole.SHIPPER.value:",
 "    q = select(Order).options(selectinload(Order.order_products)).order_by(Order.id.desc())\n    if deleted_only:\n        q = q.where(Order.deleted_at.isnot(None))\n    elif not include_deleted:\n        q = q.where(Order.deleted_at.is_(None))\n\n    if role == UserRole.SHIPPER.value:"),
# ---------- orders.py : pending_dispatch_count 排除软删 ----------
("/opt/SOrders/backend/app/api/v1/orders.py",
 "    q = select(func.count()).select_from(Order).where(Order.status == OrderStatus.PENDING_DISPATCH)\n    n = db.scalar(q)",
 "    q = select(func.count()).select_from(Order).where(\n        Order.status == OrderStatus.PENDING_DISPATCH,\n        Order.deleted_at.is_(None),\n    )\n    n = db.scalar(q)"),
# ---------- orders.py : 软删除改造 ----------
("/opt/SOrders/backend/app/api/v1/orders.py",
 "    \"\"\"仅删除「已撤销」状态的订单（货主删自己的单；派单员可删含临时货主单）。\"\"\"\n    order = _get_order_scoped(order_id, current, db)\n    role = user_role_key(current)\n    if role not in (UserRole.SHIPPER.value, UserRole.DISPATCHER.value):\n        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=\"无权操作\")\n    if not role_has_permission(role, Permission.ORDER_DELETE_CANCELLED):\n        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=\"无权操作\")\n    if order.status != OrderStatus.CANCELLED:\n        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=\"仅已撤销的订单可删除\")\n    delete_orders_by_ids(db, [order_id])\n    db.commit()",
 "    \"\"\"软删除订单 → 进入隔离区 30 天（用户不可见；派单员可恢复；到期物理清理）。\n    货主：本人 已送达/已撤销/异常 订单；派单员：任意状态（含待派单）。\"\"\"\n    order = _get_order_scoped(order_id, current, db)\n    role = user_role_key(current)\n    if role not in (UserRole.SHIPPER.value, UserRole.DISPATCHER.value):\n        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=\"无权操作\")\n    if role == UserRole.SHIPPER.value:\n        if not role_has_permission(role, Permission.ORDER_DELETE_CANCELLED):\n            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=\"无权操作\")\n        if order.status not in (OrderStatus.CANCELLED, OrderStatus.DELIVERED) and not bool(order.is_exception):\n            raise HTTPException(\n                status_code=status.HTTP_400_BAD_REQUEST,\n                detail=\"仅已送达/已撤销/异常订单可删除（进行中的订单请走撤销或撤回）\",\n            )\n    if order.deleted_at is not None:\n        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=\"订单已在隔离区，如需恢复请联系派单员\")\n    order.deleted_at = datetime.now(timezone.utc)\n    write_log(\n        db,\n        operator_id=current.id,\n        order_id=order.id,\n        action=OperationAction.ORDER_DELETE,\n        change_payload={\"order_no\": order.order_no},\n    )\n    db.commit()"),
# ---------- orders.py : restore 端点（插在老 delete_order 前） ----------
("/opt/SOrders/backend/app/api/v1/orders.py",
 "@router.delete(\"/{order_id}\", status_code=status.HTTP_204_NO_CONTENT)\ndef delete_order(\n    order_id: int,\n    db: Session = Depends(get_db),\n    current: User = Depends(require_permission(Permission.ORDER_EDIT)),\n) -> None:\n    order = db.scalars(select(Order).where(Order.id == order_id)).first()\n    if order is None:\n        raise HTTPException(status_code=404, detail=\"未找到对应记录\")\n    if order.status != OrderStatus.PENDING_DISPATCH:\n        raise HTTPException(status_code=400, detail=\"仅「待派单」订单可删除\")\n    db.delete(order)\n    db.commit()",
 "@router.post(\"/{order_id}/restore\", response_model=OrderOut)\ndef restore_order(\n    order_id: int,\n    current: CurrentUser,\n    db: Session = Depends(get_db),\n) -> OrderOut:\n    \"\"\"派单员：从隔离区恢复订单（软删除后 30 天内可恢复）。\"\"\"\n    if user_role_key(current) != UserRole.DISPATCHER.value:\n        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=\"仅派单员可恢复\")\n    order = db.scalars(\n        select(Order).options(selectinload(Order.order_products)).where(Order.id == order_id)\n    ).first()\n    if order is None or order.deleted_at is None:\n        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=\"订单不在隔离区\")\n    order.deleted_at = None\n    write_log(\n        db,\n        operator_id=current.id,\n        order_id=order.id,\n        action=OperationAction.ORDER_RESTORE,\n        change_payload={\"order_no\": order.order_no},\n    )\n    db.commit()\n    full = load_order_for_response(db, order.id)\n    if full is None:\n        raise HTTPException(status_code=500, detail=\"订单数据异常\")\n    return enrich_order_out(full, db, current)\n\n\n@router.delete(\"/{order_id}\", status_code=status.HTTP_204_NO_CONTENT)\ndef delete_order(\n    order_id: int,\n    db: Session = Depends(get_db),\n    current: User = Depends(require_permission(Permission.ORDER_EDIT)),\n) -> None:\n    # 老路由（仅待派单物理删除）已被 307 行的软删除路由覆盖匹配；\n    # 保留为兜底：改为软删除，避免物理删后遗留子表/文件\n    order = db.scalars(select(Order).where(Order.id == order_id)).first()\n    if order is None:\n        raise HTTPException(status_code=404, detail=\"未找到对应记录\")\n    if order.status != OrderStatus.PENDING_DISPATCH:\n        raise HTTPException(status_code=400, detail=\"仅「待派单」订单可删除\")\n    order.deleted_at = datetime.now(timezone.utc)\n    db.commit()"),
# ---------- main.py : imports ----------
("/opt/SOrders/backend/app/main.py",
 "from contextlib import asynccontextmanager\nfrom typing import Any\n\nimport socketio\nfrom fastapi import FastAPI\nfrom fastapi.middleware.cors import CORSMiddleware\nfrom fastapi.staticfiles import StaticFiles",
 "from contextlib import asynccontextmanager\nfrom pathlib import Path\nfrom typing import Any\n\nimport socketio\nfrom fastapi import FastAPI, HTTPException\nfrom fastapi.middleware.cors import CORSMiddleware\nfrom fastapi.responses import FileResponse"),
# ---------- main.py : 循环函数 ----------
("/opt/SOrders/backend/app/main.py",
 "from app.services.cancelled_order_retention import purge_expired_cancelled_orders",
 "from app.services.data_retention import run_daily_retention"),
("/opt/SOrders/backend/app/main.py",
 "def _purge_cancelled_sync() -> None:\n    db = SessionLocal()\n    try:\n        purge_expired_cancelled_orders(db)\n        db.commit()\n    except Exception:\n        logger.exception(\"清理过期已撤销订单失败\")\n        db.rollback()\n    finally:\n        db.close()\n\n\nasync def _purge_cancelled_loop() -> None:\n    \"\"\"启动后立即执行一次，之后每 24 小时清理一次。\"\"\"\n    while True:\n        await asyncio.to_thread(_purge_cancelled_sync)\n        await asyncio.sleep(86400)",
 "def _retention_sync() -> None:\n    db = SessionLocal()\n    try:\n        r = run_daily_retention(db)\n        logger.info(\"数据保留治理完成: %s\", r)\n    except Exception:\n        logger.exception(\"数据保留治理失败\")\n        db.rollback()\n    finally:\n        db.close()\n\n\nasync def _retention_loop() -> None:\n    \"\"\"数据保留治理：启动后立即执行一次，之后每 24 小时一次。\n    治理内容（用户拍板 2026-09-04）：业务数据 3 年 / 软删除隔离 30 天 /\n    原始图片 1 年后自动压缩为感知无损 WebP。\"\"\"\n    while True:\n        await asyncio.to_thread(_retention_sync)\n        await asyncio.sleep(86400)"),
("/opt/SOrders/backend/app/main.py",
 "    task = asyncio.create_task(_purge_cancelled_loop())",
 "    task = asyncio.create_task(_retention_loop())"),
("/opt/SOrders/backend/app/main.py",
 "    application.include_router(api_router, prefix=settings.api_v1_prefix)\n    application.mount(\"/static/uploads\", StaticFiles(directory=\"uploads\"), name=\"static_uploads\")",
 "    application.include_router(api_router, prefix=settings.api_v1_prefix)\n\n    @application.get(\"/static/uploads/{file_path:path}\")\n    def static_uploads(file_path: str):\n        \"\"\"静态文件服务（经应用层：防目录穿越；图片已由数据治理自动压缩归档）。\n        客户端 URL 如 /static/uploads/delivery/{order_id}/{name}。\"\"\"\n        base = Path(\"uploads\").resolve()\n        target = (base / file_path).resolve()\n        if not str(target).startswith(str(base)) or not target.is_file():\n            raise HTTPException(status_code=404, detail=\"文件不存在\")\n        suffix = target.suffix.lower()\n        media_type = {\n            \".jpg\": \"image/jpeg\", \".jpeg\": \"image/jpeg\", \".png\": \"image/png\",\n            \".webp\": \"image/webp\", \".bmp\": \"image/bmp\", \".pdf\": \"application/pdf\",\n        }.get(suffix)\n        return FileResponse(target, media_type=media_type)"),
]

ok = 0; miss = []
for path, old, new in PAIRS:
    try:
        s = io.open(path, encoding="utf-8").read()
    except Exception as e:
        print("READ_FAIL", path, e); continue
    if old not in s:
        miss.append((path, old[:70].replace(chr(10), "|"))); continue
    n = s.count(old)
    if n != 1:
        print("MULTI(%d):" % n, path, old[:70].replace(chr(10), "|")); continue
    io.open(path, "w", encoding="utf-8").write(s.replace(old, new))
    ok += 1
print("OK:", ok, "/", len(PAIRS))
for p, o in miss: print("MISS:", p, o)
