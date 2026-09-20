"""退货申请的出参/入参（2026-09-21）。

⚠️ 为什么单独一个文件而不是塞进 `schemas/order.py`：这一轮改动同时有别的会话在动订单相关文件，
   新增的**独立**东西放自己的文件里，冲突面最小（约定见 `docs/AI_WORK_CLAIM.md`）。
"""

from datetime import datetime

from pydantic import BaseModel, Field

# 退货明细行**复用**订单退货那一个模型：它已经有"上限只写在两处"的口径注释
# （schema 里 `ge=1` 挡 0/负数，业务上限在 `order_return.max_returnable`），
# 再定义一个"申请用的行"就等于把同一套校验写两遍 —— 两遍就会有一天不一致。
from app.schemas.order import OrderReturnItem, OrderReturnOut

# 备注长度**复用全项目那一份**（与 `String(256)` 列宽对齐）：
# 这里再写一个 256 就是第二个定义处 —— 改一处漏一处，迟早与列宽对不上
# （`tools/qa/_audit_text_fields.py` 会逐字段比列宽，但"两个常量都叫 MAX_NOTE"它看不出来）。
from app.schemas.text import MAX_NOTE  # noqa: E402


class ReturnRequestCreateBody(BaseModel):
    """货主提交退货申请。

    ⛔ 这里**没有数量上限的业务判断**（只挡 0/负数）：上限的唯一来源是
       `order_return.max_returnable`，越界要回一句"「苹果」最多只能退 2 件"，
       而不是 422 + 英文结构体。
    """

    order_id: int
    items: list[OrderReturnItem] = Field(..., min_length=1, max_length=20)
    note: str = Field("", max_length=MAX_NOTE)


class ReturnRequestRejectBody(BaseModel):
    """派单员驳回。理由**必填**（货主唯一能拿到的答复）。"""

    reason: str = Field(..., min_length=1, max_length=MAX_NOTE)


class ReturnRequestLineOut(BaseModel):
    order_product_id: int
    product_name: str
    quantity: int


class ReturnRequestOut(BaseModel):
    """一张退货申请（货主端与派单端**同一个形状**）。

    · `status_label` 由**后端**给出中文名：状态机在后端，前端各自写一套映射
      就会出现"后端加了新状态、某一个端显示 RETURNED 这种原始码"（这个项目栽过）。
    · `shipper_name` / `handled_by_name` 给派单员看（他要回答"谁申请的、谁办的"）。
    """

    id: int
    order_id: int
    order_no: str
    shipper_id: int
    shipper_name: str
    status: str
    status_label: str
    note: str
    reject_reason: str
    lines: list[ReturnRequestLineOut] = []
    created_at: datetime | None = None
    handled_at: datetime | None = None
    handled_by: int | None = None
    handled_by_name: str = ""
    source: str = "app"


class ReturnRequestFulfillOut(BaseModel):
    """办理完成：申请单的最终样子 + 那次真实退货的回参（账、库存、退现都在里面）。"""

    request: ReturnRequestOut
    returned: OrderReturnOut


class ReturnRequestListOut(BaseModel):
    """列表 + 派单员要看的一个数（待处理几张），让角标不用自己数。"""

    items: list[ReturnRequestOut] = []
    pending_count: int = 0
