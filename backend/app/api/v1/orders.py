"""orders 路由的其余部分：创建 / 派单 / 送达 / 收款 / 退货 / 撤回 / 图片。

2026-09-24（整改阶段 4）**纯搬迁**：查询组（列表 / 待派计数 / 详情）搬到了 `orders_query.py`，
三模块共用的 router 与助手搬到了 `orders_common.py`。
除代码组织外**一个字没改** —— 端点集合 / 入参 / 出参 / 权限 / 状态机 / 数据库全不变，
证据：`_tools/qa/_api_contract_snapshot.py --diff before-orders-move now` 契约零差异。
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload
from app.api.v1.arrears import find_or_create_unit
from app.core.business_time import local_stamp, utc_now_naive
from app.core.rbac import Permission, role_has_permission, user_role_key
from app.core.upload_read import MAX_IMAGE_BYTES, read_limited
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import ArrearsUnit, Order, User
from app.models.enums import OperationAction, OrderStatus, UserRole
from app.models import (
    DriverBillingRuleTemplate,
    FreightCategory,
    FreightTemplate,
    FreightTemplateCategory,
    ShipperAddress,
)
from app.schemas.order import (
    OrderFreightPriceBody,
    BatchAssignResultItem,
    DeliveryPhotoUploadOut,
    DriverNoteBody,
    OrderAssignBody,
    OrderFreightBody,
    OrderSplitBody,
    OrderBatchAssignBody,
    OrderBatchAssignOut,
    OrderChargeBody,
    OrderCompleteBody,
    OrderCreate,
    OrderExceptionBody,
    OrderOut,
    OrderRecallBody,
    OrderReturnBody,
    OrderReturnOut,
    OrderUpdate,
)
from app.schemas.place import OrderNavigationBody
from app.schemas.product_visibility import product_visible_to
from app.services.auth_service import new_order_no
from app.services.operation_log_service import write_log
from app.services.order_flow import split_order
from app.services.order_flow import (
    assign_driver,
    build_order_products,
    cancel_pending,
    complete_delivery,
    ensure_order_date,
    lock_order_row,
    recall_dispatch,
)
from app.services.order_money import money_map
from app.services.accounting_service import BillAlreadySettledError, resync_open_piece_bill
from app.services.order_response import enrich_order_out, load_order_for_response
from app.services.order_return import OrderReturnError, ReturnItem, return_order
from app.services import order_return_request as return_request_svc
from app.services import usage_service
from app.services.shipper_contact_service import upsert_boss_contact
from app.services import place_service
# ⚠️ 付款家族（_already_collected / _apply_complete_payment / …）2026-09-24 阶段 4 搬去了
# `orders_payment.py`；**完成订单时要写那笔钱**，所以这里要把它引回来（跨模块 import，无环）。
from app.api.v1.orders_payment import _apply_complete_payment_logged, _reject_if_already_collected
from app.api.v1.orders_common import (
    UPLOAD_DIR, ALLOWED_IMAGE_CT, _bg_dispatcher_pending_pool, _bg_freight_updated,
    _bg_ledger_updated_shipper, _bg_notify_cancel, _bg_notify_delivered, _bg_notify_driver_ack,
    _bg_notify_navigation_filled, _bg_notify_new_order, _bg_notify_order_edited,
    _bg_notify_return_request_closed, _bg_push_assigned, _bg_push_revoked,
    _bg_push_shipper_recalled, _get_order_scoped, _order_not_deleted_or_404,
    _save_delivery_uploads,
)

router = APIRouter(prefix="/orders", tags=["orders"])


































































