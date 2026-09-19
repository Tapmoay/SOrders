from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import Permission, role_has_permission, user_role_key
from app.database import get_db
from app.deps import CurrentUser, require_permission
from app.models import Ledger, LedgerExportJob, Order, User
from app.models.enums import LedgerSource, OperationAction, OrderStatus, UserRole
from app.models.export_job import ExportFormat, ExportJobStatus
from app.schemas.export_job import LedgerExportJobCreate, LedgerExportJobOut
from app.schemas.accounting_v2 import ShipperReceiptCreate, ShipperReceiptOut
from app.schemas.ledger import (
    LedgerAccountOut,
    LedgerCreate,
    LedgerOut,
    LedgerSyncFromOrdersBody,
    LedgerUpdate,
)
from app.services.ledger_export_worker import run_ledger_export_job_task
from app.services.ledger_response import ledger_to_out
from app.services.ledger_scope import visible_ledger_select
from app.services.ledger_sync import (
    sync_delivered_orders_to_ledger,
    sync_order_product_from_ledger,
)
from app.services.operation_log_service import write_log
from app.services.push_events import push_ledger_updated

router = APIRouter(prefix="/ledger", tags=["ledger"])


async def _bg_push_ledger_shipper(shipper_id: int) -> None:
    await push_ledger_updated(shipper_id)


def _reject_if_order_closed(db: Session, row: Ledger, *, wants_detail: bool, what: str) -> None:
    """订单来的账本行：**单子已结束就不许再改它连带的那笔钱**（2026-09-19 审计 R12-M3）。

    ### 为什么这条判据必须和订单侧同源
    `PATCH /order-products` 与 `PATCH /orders` 对「已送达/已撤销」是明确拒绝的；
    而账本行这条路上，`sync_order_product_from_ledger` 会把值**直接写回订单行**。
    两处判据不一致时，正规入口堵住的事从侧门照样能做——而且侧门这条**不看订单状态**。

    后果很具体：司机账单在送达那一刻就按当时的行金额冻结了，而结算页/绩效/导出
    是实时按当前订单行重算 → 同一张单出现两个数，且事后从审计页看不出改前是多少。

    `what` 只用于拼一句能照着做的中文（"改这一行的商品与金额" / "删这一行"）。
    """
    if not wants_detail or row.source != LedgerSource.ORDER or row.order_id is None:
        return
    order = db.get(Order, row.order_id)
    if order is None:
        return
    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):
        state = "已送达" if order.status == OrderStatus.DELIVERED else "已撤销"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"这张单{state}，账上这笔钱已经定了，不能{what}。"
                "已送达的单金额在司机账单生成时就冻结了；要改请先处理那张单本身"
                "（例如先在订单里说明情况），不要从账本侧改。"
            ),
        )


@router.get("/entries", response_model=list[LedgerOut])
def list_entries(
    current: CurrentUser,
    db: Session = Depends(get_db),
    shipper_id: int | None = Query(None),
    temp_shipper_name: str | None = Query(None, description="临时货主名称（与 shipper_id 二选一）"),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
) -> list[LedgerOut]:
    from datetime import date as date_type

    role = user_role_key(current)
    # ⚠️ 只有**没进回收站**的订单的那份账（R13-R6）：与报表侧同一句，
    #    否则"账本"和"营业额"差一张已删单的钱（本机 2026-09 差 ¥4,600），两个页面都不报错。
    q = (
        visible_ledger_select()
        .order_by(Ledger.entry_date.desc(), Ledger.id.desc())
    )
    tsn = (temp_shipper_name or "").strip()
    if role == UserRole.SHIPPER.value:
        q = q.where(Ledger.shipper_id == current.id)
    elif role == UserRole.DISPATCHER.value:
        if shipper_id is not None and tsn:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请只指定 shipper_id 或 temp_shipper_name 之一",
            )
        if shipper_id is not None:
            q = q.where(Ledger.shipper_id == shipper_id)
        elif tsn:
            q = q.where(Ledger.shipper_id.is_(None)).where(Ledger.temp_shipper_name == tsn)
        # 无筛选参数 = 派单员查看全部流水（账本管理总览），有参数则按货主过滤
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")

    if date_from:
        try:
            df = date_type.fromisoformat(date_from[:10])
            q = q.where(Ledger.entry_date >= df)
        except ValueError:
            raise HTTPException(status_code=400, detail="开始日期格式无效") from None
    if date_to:
        try:
            dt = date_type.fromisoformat(date_to[:10])
            q = q.where(Ledger.entry_date <= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="结束日期格式无效") from None

    rows = list(db.scalars(q).all())
    return [ledger_to_out(r, db) for r in rows]


@router.get("/accounts", response_model=list[LedgerAccountOut])
def list_accounts(
    current: CurrentUser,
    db: Session = Depends(get_db),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    kind: str = Query("shipper", pattern="^(shipper|member)$"),
) -> list[LedgerAccountOut]:
    """派单员账本账户汇总：货主账 / 批发商账（按流水累计 + 笔数）。"""
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")

    from datetime import date as date_type

    q = visible_ledger_select()  # 同上：隔离区订单的账不算（R13-R6）
    if date_from:
        try:
            df = date_type.fromisoformat(date_from[:10])
            q = q.where(Ledger.entry_date >= df)
        except ValueError:
            raise HTTPException(status_code=400, detail="开始日期格式无效") from None
    if date_to:
        try:
            dt = date_type.fromisoformat(date_to[:10])
            q = q.where(Ledger.entry_date <= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="结束日期格式无效") from None

    rows = list(db.scalars(q).all())
    buckets: dict[tuple, dict] = {}
    user_cache: dict[int, User | None] = {}
    for r in rows:
        if r.shipper_id is not None:
            if r.shipper_id not in user_cache:
                user_cache[r.shipper_id] = db.get(User, r.shipper_id)
            u = user_cache[r.shipper_id]
            if kind == "member" and not (u is not None and getattr(u, "is_member", False)):
                continue
            key = ("u", r.shipper_id)
            b = buckets.setdefault(key, {"id": r.shipper_id, "temp_name": None, "name": "", "count": 0, "total": Decimal("0")})
            if not b["name"]:
                b["name"] = (u.full_name or u.phone or f"货主#{r.shipper_id}") if u else f"货主#{r.shipper_id}"
        else:
            if kind == "member":
                continue
            name = (r.temp_shipper_name or "").strip() or "临时货主"
            key = ("t", name)
            b = buckets.setdefault(key, {"id": None, "temp_name": name, "name": name, "count": 0, "total": Decimal("0")})
        b["count"] += 1
        b["total"] = b["total"] + (r.total or Decimal("0"))
    result = sorted(buckets.values(), key=lambda x: -x["total"])
    return [LedgerAccountOut(**x) for x in result]


@router.get("/temp-shipper-names", response_model=list[str])
def list_temp_shipper_names(
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> list[str]:
    """派单员：曾出现过的临时货主称呼（账本或订单），用于快捷筛选；订单送达时已自动入账，无需「创建账本」。"""
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问")
    names: set[str] = set()
    for raw in db.scalars(
        select(Ledger.temp_shipper_name).where(
            Ledger.shipper_id.is_(None),
            Ledger.temp_shipper_name.isnot(None),
        )
    ).all():
        t = (raw or "").strip()
        if t:
            names.add(t)
    for raw in db.scalars(
        select(Order.temp_shipper_name).where(
            Order.shipper_id.is_(None),
            Order.temp_shipper_name.isnot(None),
        )
    ).all():
        t = (raw or "").strip()
        if t:
            names.add(t)
    return sorted(names)


@router.post("/sync-from-delivered-orders")
def sync_ledger_from_delivered_orders(
    body: LedgerSyncFromOrdersBody,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> dict:
    """按历史已送达订单补全/刷新账本（幂等）。仅派单员。"""
    n, shipper_ids = sync_delivered_orders_to_ledger(db, body.shipper_id, body.temp_shipper_name)
    db.commit()
    for sid in shipper_ids:
        background_tasks.add_task(_bg_push_ledger_shipper, sid)
    return {"orders_synced": n, "shippers_notified": len(shipper_ids)}


@router.post("/entries", response_model=LedgerOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    body: LedgerCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> LedgerOut:
    total = body.total
    if total is None or total == Decimal("0"):
        total = body.unit_price * body.quantity
    sid = body.shipper_id
    tname = body.temp_shipper_name if sid is None else None
    # ⛔ `source` **不许由客户端指定**（2026-09-19 审计）：
    #    这个接口是"手工记账"的入口，`source` 本该固定 MANUAL。原来它照抄请求体，于是派单员
    #    （或拿到他 token 的任何东西）可以传 `source="order"` 造一行**系统订单账**，
    #    而 `sync_order_product_from_ledger` 只对 MANUAL 早退 —— 结果一次 POST 干了三件事：
    #      ① 账本凭空多一行（货主账与账本导出都算它）；
    #      ② **改写那张已送达订单的商品行**（数量/单价/行金额），绕过了 `_order_allows_line_edit`
    #         的状态锁（已送达本该不可编辑）与 ORDER_LINE_UPDATE 审计；
    #      ③ 送达时幂等生成的那条原始账本行不动 → 同一张单在账本里两行、金额不同 →
    #         营业额（按订单行算）与货主账（按 ledgers 算）各说一个数。
    #    系统侧的 ORDER/REFUND 行只由 `ledger_sync` 写（送达、红冲），不从 HTTP 入口进。
    source = body.source
    if source != LedgerSource.MANUAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="手工记账只能记为「手动」来源。订单账（ORDER）与红冲（REFUND）由系统在送达/货损时自动写入，"
                   "不能手工造 —— 否则会凭空多出一行账、并顺带改写已送达订单的金额。",
        )
    row = Ledger(
        shipper_id=sid,
        temp_shipper_name=tname,
        entry_date=body.entry_date,
        product_name=body.product_name,
        quantity=body.quantity,
        unit_price=body.unit_price,
        total=total,
        order_id=None,          # 手工行不挂订单（挂了会被当日订单账重复计入）
        order_product_id=None,
        product_id=body.product_id,
        source=source,
        note=body.note,
    )
    db.add(row)
    db.flush()
    sync_order_product_from_ledger(db, row)
    write_log(
        db,
        operator_id=current.id,
        # ⚠️ 痕迹**不许挂在账本行没挂的那张单上**（2026-09-19 审计 R14-6）：
        #    账本行刻意 `order_id=None`（挂了会被当日订单账重复计入），而日志原来写的是
        #    `body.order_id` → 审计页把一笔手工账归到它并不属于的订单上，
        #    从那张单的轨迹看会以为"这单多了一笔手工账"。想保留关联就放进 payload。
        order_id=None,
        action=OperationAction.LEDGER_CREATE,
        change_payload={
            "ledger_id": row.id,
            "shipper_id": row.shipper_id,
            "temp_shipper_name": row.temp_shipper_name,
            "total": str(row.total),
            # 用户请求里带的订单号（如果有）：只作为线索保留，不当归属
            "requested_order_id": body.order_id,
        },
    )
    db.commit()
    db.refresh(row)
    if row.shipper_id is not None:
        background_tasks.add_task(_bg_push_ledger_shipper, row.shipper_id)
    return ledger_to_out(row, db)


@router.get("/entries/{entry_id}", response_model=LedgerOut)
def get_entry(
    entry_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> LedgerOut:
    row = db.get(Ledger, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value and (
        row.shipper_id is None or row.shipper_id != current.id
    ):
        raise HTTPException(status_code=403, detail="无权访问")
    if role not in (UserRole.SHIPPER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=403, detail="无权访问")
    return ledger_to_out(row, db)


@router.patch("/entries/{entry_id}", response_model=LedgerOut)
def update_entry(
    entry_id: int,
    body: LedgerUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> LedgerOut:
    """派单员：订单自动同步行与手动行均可改明细；修改订单来源行时会尝试回写对应订单明细。"""
    row = db.get(Ledger, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    shipper_id = row.shipper_id
    detail_editable = row.source in (LedgerSource.MANUAL, LedgerSource.ORDER)
    detail_keys = (
        "entry_date",
        "product_name",
        "quantity",
        "unit_price",
        "total",
        "order_id",
        "product_id",
    )
    raw = body.model_dump(exclude_unset=True)
    wants_detail = any(k in raw for k in detail_keys)
    if wants_detail and not detail_editable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无法修改该行商品与金额",
        )
    # ⚠️ 订单来的账本行 = 订单金额的**第二个写入口**（2026-09-19 审计 R12-M3）：
    #    正规入口（`PATCH /order-products`、`PATCH /orders`）对已送达/已撤销的单是明确拒绝的，
    #    而这里 `sync_order_product_from_ledger` 会把值**直接写回订单行**——不看订单状态。
    #    于是"已结束"之后钱还能改，而司机账单已经冻结（账单只在送达那一刻按当时的行金额生成），
    #    结算页/绩效/导出却是实时按当前订单行重算 → 同一张单两个数。
    #    口径与订单侧**同一条**（复用 `_order_allows_line_edit` 的判据，不另立一套）。
    _reject_if_order_closed(db, row, wants_detail=wants_detail, what="改这一行的商品与金额")
    if detail_editable:
        before = {
            "entry_date": str(row.entry_date),
            "product_name": row.product_name,
            "quantity": row.quantity,
            "unit_price": str(row.unit_price),
            "total": str(row.total),
        }
        if "entry_date" in raw and raw["entry_date"] is not None:
            row.entry_date = raw["entry_date"]
        if "product_name" in raw and raw["product_name"] is not None:
            row.product_name = raw["product_name"].strip()
        if "unit_price" in raw and raw["unit_price"] is not None:
            row.unit_price = raw["unit_price"]
        if "quantity" in raw and raw["quantity"] is not None:
            row.quantity = raw["quantity"]
        # ⛔ **不许改 order_id**（2026-09-19 审计 F3）：`_reject_if_order_closed` 是按**改之前**
        #    的那个 order_id 判的（`row.order_id`），改完之后 `sync_order_product_from_ledger`
        #    却按**新的** order_id 回写 —— 于是可以把一行订单账改挂到别的单上，
        #    并且**让回写落到那张单的商品行**（订单状态守卫在这条路上等于被绕过）。
        #    本机已有 7 行 `source=ORDER` 但订单并非已送达的账（早期竞态遗留）→ 这条路真实可用。
        #    挂错单要改，正确做法是删掉这一行、在正确的单上重记（两件事都留痕）。
        if "order_id" in raw and raw["order_id"] != row.order_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "账本行不能改挂到别的订单上：这笔钱的归属决定了它会回写哪张单的商品行。"
                    "要纠正挂错的账，请删掉这一行、在正确的订单上重新记一笔（两次操作都会留痕）。"
                ),
            )
        if "product_id" in raw:
            row.product_id = raw["product_id"]
        if "total" in raw and raw["total"] is not None:
            row.total = raw["total"]
        elif "unit_price" in raw or "quantity" in raw:
            row.total = row.unit_price * row.quantity
    else:
        before = None
    if body.note is not None:
        row.note = body.note
    db.flush()
    sync_order_product_from_ledger(db, row)
    write_log(
        db,
        operator_id=current.id,
        order_id=row.order_id,
        action=OperationAction.LEDGER_UPDATE,
        change_payload={
            "ledger_id": row.id,
            # ⚠️ 改钱必须留下**改前是多少**（2026-09-19 审计 R12-M3）：原来这里只有
            #    `{"ledger_id": …}`，事后从审计页完全看不出这一笔原来记的是多少钱。
            "before": before,
            "after": {
                "entry_date": str(row.entry_date),
                "product_name": row.product_name,
                "quantity": row.quantity,
                "unit_price": str(row.unit_price),
                "total": str(row.total),
            },
        },
    )
    db.commit()
    db.refresh(row)
    if shipper_id is not None:
        background_tasks.add_task(_bg_push_ledger_shipper, shipper_id)
    return ledger_to_out(row, db)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: User = Depends(require_permission(Permission.LEDGER_EDIT)),
) -> None:
    row = db.get(Ledger, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    # ⚠️ 已送达/已撤销的单，账上那一笔不许删（2026-09-19 审计 R12-M3）：
    #    删掉之后订单行还在（营业额按订单行算、一分不减），账本侧少一笔 →
    #    两个口径永久差这一笔，而删除动作在审计里只有一句「删了第 N 行」。
    _reject_if_order_closed(db, row, wants_detail=True, what="删掉这一行")
    shipper_id = row.shipper_id
    oid = row.order_id
    write_log(
        db,
        operator_id=current.id,
        order_id=oid,
        action=OperationAction.LEDGER_DELETE,
        change_payload={
            "ledger_id": entry_id,
            # 删钱必须留下**删掉的是什么**（否则事后无法复原也无法对账）
            "before": {
                "entry_date": str(row.entry_date),
                "product_name": row.product_name,
                "quantity": row.quantity,
                "unit_price": str(row.unit_price),
                "total": str(row.total),
                "source": row.source,
                "order_id": row.order_id,
                "shipper_id": row.shipper_id,
                "note": row.note,
            },
        },
    )
    db.delete(row)
    db.commit()
    if shipper_id is not None:
        background_tasks.add_task(_bg_push_ledger_shipper, shipper_id)


@router.post(
    "/export-jobs",
    response_model=LedgerExportJobOut,
    status_code=status.HTTP_201_CREATED,
)
def create_export_job(
    body: LedgerExportJobCreate,
    background_tasks: BackgroundTasks,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> LedgerExportJob:
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value:
        if body.shipper_id != current.id:
            raise HTTPException(status_code=403, detail="仅能导出自己的账本")
    elif role == UserRole.DISPATCHER.value:
        if not role_has_permission(role, Permission.LEDGER_EDIT):
            raise HTTPException(status_code=403, detail="无权访问")
    else:
        raise HTTPException(status_code=403, detail="无权访问")
    if body.date_from > body.date_to:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    job = LedgerExportJob(
        created_by_id=current.id,
        shipper_id=body.shipper_id,
        file_format=body.export_format,
        date_from=body.date_from,
        date_to=body.date_to,
        status=ExportJobStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(run_ledger_export_job_task, job.id)
    return job


@router.get("/export-jobs/{job_id}", response_model=LedgerExportJobOut)
def get_export_job(
    job_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> LedgerExportJob:
    job = db.get(LedgerExportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value:
        if job.created_by_id != current.id or job.shipper_id != current.id:
            raise HTTPException(status_code=403, detail="无权访问")
    elif role == UserRole.DISPATCHER.value:
        if job.created_by_id != current.id:
            raise HTTPException(status_code=403, detail="无权访问")
    else:
        raise HTTPException(status_code=403, detail="无权访问")
    return job


@router.get("/export-jobs/{job_id}/download")
def download_export_job(
    job_id: int,
    current: CurrentUser,
    db: Session = Depends(get_db),
):
    """下载导出的账本文件（**带鉴权**）。

    ⚠️ 为什么需要这个端点（2026-09-19 审计）：导出产物原来直接给 `/static/uploads/exports/...`，
    而那条静态路由**没有任何鉴权**（生产 nginx 更是 alias 直出磁盘），文件名又是
    `ledger_{货主id}_{任务id}.xlsx` 这种可枚举的小整数 → 任何能访问公网的人不需要账号
    就能把每个货主的完整账本拖走，且不留登录痕迹。现在：
      ① 产物写在 `exports/`（不在公开的 `uploads/` 之下）；
      ② 只有本端点能取，归属校验与 `get_export_job` **同一套**（货主只能下自己的、派单员可下全部）。
    """
    from fastapi.responses import FileResponse

    from app.services.ledger_export_paths import find_export_file

    job = db.get(LedgerExportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    role = user_role_key(current)
    if role == UserRole.SHIPPER.value:
        if job.created_by_id != current.id or job.shipper_id != current.id:
            raise HTTPException(status_code=403, detail="无权访问")
    elif role == UserRole.DISPATCHER.value:
        if not role_has_permission(role, Permission.LEDGER_EDIT):
            raise HTTPException(status_code=403, detail="无权访问")
    else:
        raise HTTPException(status_code=403, detail="无权访问")

    # ⚠️ `file_path` 里存的是**产物文件名**（老数据可能是一条 URL，[find_export_file] 兼容两种）。
    #    这里原来读的是 `job.download_url` —— **模型上根本没有这个属性**，于是任何下载都 500
    #    （2026-09-19 审计 R12-A1）。定位规则现在只有一处实现（`ledger_export_paths`）。
    stored = job.file_path or ""
    if not stored:
        raise HTTPException(status_code=404, detail="这个导出任务还没有产物（可能仍在生成或已失败）")
    path = find_export_file(stored, job.shipper_id, job.id)
    if path is None:
        raise HTTPException(status_code=404, detail="导出文件不存在（可能已被清理）")
    return FileResponse(str(path), filename=path.name)


@router.post("/receipts", response_model=ShipperReceiptOut)
def create_receipt_endpoint(
    body: ShipperReceiptCreate,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> ShipperReceiptOut:
    """客户收款单（逐单核销默认）：绑定订单并标记 paid=1；生成资金流水。"""
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅派单员可操作")
    from app.services.accounting_service import create_receipt

    try:
        r = create_receipt(db, body, current.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    # 钱动了必须留痕（2026-09-19 审计）：这条路径会写 `shipper_receipts` + `cash_flows`
    # 并把订单标成已收款，以前**一条 operation_logs 都没有** —— 事后问"这笔钱谁录的"答不上来。
    # 与写入**同一事务**提交：日志写不进去就一起回滚，不留"钱记了、痕迹没有"的中间态。
    write_log(
        db,
        operator_id=current.id,
        order_id=(body.order_ids[0] if body.order_ids else None),
        action=OperationAction.RECEIPT_CREATE,
        change_payload={
            "receipt_id": r.id,
            "customer_id": r.customer_id,
            "amount": str(r.amount),
            "method": r.method,
            "settle_mode": str(getattr(r.settle_mode, "value", r.settle_mode)),
            "order_ids": list(body.order_ids or []),
            "arrears_unit_id": r.arrears_unit_id,
        },
    )
    db.commit()
    db.refresh(r)
    from app.models import Customer

    c = db.get(Customer, r.customer_id)
    return ShipperReceiptOut(
        id=r.id, customer_id=r.customer_id, amount=r.amount, method=r.method,
        received_at=r.received_at, order_ids=r.order_ids, settle_mode=r.settle_mode,
        arrears_unit_id=r.arrears_unit_id, invoiced=r.invoiced, note=r.note,
        operator_id=r.operator_id,
        customer_name=c.name if c else "", created_at=r.created_at,
    )


@router.get("/receipts", response_model=list[ShipperReceiptOut])
def list_receipts(
    current: CurrentUser,
    db: Session = Depends(get_db),
    customer_id: int | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
) -> list[ShipperReceiptOut]:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅派单员可查看")
    from app.models import ShipperReceipt

    stmt = select(ShipperReceipt).order_by(ShipperReceipt.received_at.desc(), ShipperReceipt.id.desc())
    if customer_id is not None:
        stmt = stmt.where(ShipperReceipt.customer_id == customer_id)
    if date_from:
        stmt = stmt.where(ShipperReceipt.received_at >= date_from)
    if date_to:
        stmt = stmt.where(ShipperReceipt.received_at <= date_to)
    rows = list(db.scalars(stmt).all())
    from app.models import Customer

    names: dict[int, str] = {}
    out = []
    for r in rows:
        if r.customer_id not in names:
            c = db.get(Customer, r.customer_id)
            names[r.customer_id] = c.name if c else ""
        out.append(
            ShipperReceiptOut(
                id=r.id, customer_id=r.customer_id, amount=r.amount, method=r.method,
                received_at=r.received_at, order_ids=r.order_ids, settle_mode=r.settle_mode,
                arrears_unit_id=r.arrears_unit_id, invoiced=r.invoiced, note=r.note,
                operator_id=r.operator_id,
                customer_name=names.get(r.customer_id, ""), created_at=r.created_at,
            )
        )
    return out
