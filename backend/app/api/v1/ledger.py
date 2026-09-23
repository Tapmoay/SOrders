from decimal import Decimal
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.core.pagination import finish_page
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
from app.services.ledger_export_worker import (
    acquire_export_slot,
    release_export_slot,
    run_ledger_export_job_with_slot,
)
from app.services.ledger_response import ledger_rows_to_out, ledger_to_out
from app.services.ledger_scope import visible_ledger_select
from app.services.ledger_sync import (
    sync_delivered_orders_to_ledger,
    sync_order_product_from_ledger,
)
from app.services.operation_log_service import write_log
from app.services.push_events import push_ledger_updated
from app.services.soft_delete import strip_del_suffix
from app.core.date_window import date_window
#: 「订单明细能不能改」的唯一判据（与订单侧共用一份状态清单，不许在账本侧再抄一遍）
from app.api.v1.order_products import LINE_EDITABLE_STATUSES

router = APIRouter(prefix="/ledger", tags=["ledger"])


def _ensure_export_job_visible(job, current) -> None:
    """导出任务的**归属闸 —— 只有这一处**（查询与下载共用）。

    ## 为什么必须收成一处（2026-09-24 第 19 轮实测）
    两个端点原来各写一份，而**下载那一份对派单员是空的**：
    `elif role == DISPATCHER: if not role_has_permission(role, LEDGER_EDIT): 403` ——
    而 `core/rbac.py:145-147` 对派单员**任何权限点恒返回 True**（"派单员为最高业务权限"），
    于是那道闸永远放行。同一个任务：`GET /export-jobs/{id}` 对派单员 B 是 403，
    `GET /export-jobs/{id}/download` 却 200 —— 他能把**另一个派单员给别的货主导出的整本账**拖走。
    （原来那句注释还写着"归属校验与 `get_export_job` 同一套"，与代码相反：
    下一个维护者会以为已经校验过了。）

    ## 口径
    只有两种人能碰：**这个任务是他建的**（`created_by_id`）或**这本账就是他的**（`shipper_id`）。
    ⛔ 别在这里写 `role_has_permission(...)` —— 对派单员它是恒真的，等于没写。
    """
    role = user_role_key(current)
    if role not in (UserRole.SHIPPER.value, UserRole.DISPATCHER.value):
        raise HTTPException(status_code=403, detail="无权访问")
    if job.created_by_id != current.id and job.shipper_id != current.id:
        raise HTTPException(status_code=403, detail="无权访问")


def _apply_date_window(q, date_from: str | None, date_to: str | None):
    """把 `?date_from&date_to` 收成 `entry_date` 的**闭区间**条件 —— 两个端点共用这一份。

    ⚠️ 为什么收成一处（2026-09-21 精简轮）：`GET /ledger/entries` 与 `GET /ledger/accounts`
    原来各抄了同样一段（含两句中文报错）。两份副本真正的代价不是"多十几行"，而是**它们会分叉**：
    一端哪天改了容错（例如支持时间戳或放宽成半开区间），另一端还是老写法 —— 同一个 `?date_from`
    在两个页面上表现不同，而它们在接口文档里是同一个参数。
    ⛔ **不许**换成 `deps.parse_date_range`：它返回 `datetime`，而这里比的是 `Date` 列，
       带上时间的那一端会变成"当天不算"（闭区间悄悄变半开）。
    ✅ 但**校验**必须与它同口径：`core.date_window.date_window()` 负责"格式错 400、
       顺序反了 400"（2026-09-24 第 19 轮补：这一段原来只查格式，反序会安静地返回空集）。
    """
    start, end = date_window(date_from, date_to)
    if start is not None:
        q = q.where(Ledger.entry_date >= start)
    if end is not None:
        q = q.where(Ledger.entry_date <= end)
    return q

#: 单次导出最多包含多少笔流水（见 `create_export_job` 的说明）。
#: 实测 85,474 行 → 39.77 秒 / 85,119 条 SQL / 峰值 RSS 469MB；20000 行约 9 秒、100MB 级。
MAX_EXPORT_ROWS = 20_000
#: 同一账号 24 小时内最多导出几次（产物可重复下载，不需要反复生成）。
EXPORT_DAILY_QUOTA = 20


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
    # ⛔ 判据与"订单明细能不能改"**同一处**（2026-09-23 第 17 轮并行渗透抓到：这里原来是
    #    手写的两个状态，注释却声称复用订单侧判据 —— 于是 `RETURNED` 漏在外面：
    #    已退货的单那一行 ORDER 账本还能改，改完 `ledger_sync` 会**回写订单行金额**
    #    （`ledger_sync.py:113-115`），破了「同一笔钱一个数」这条不变式）。
    #    写成 import 而不是再抄一遍状态清单：清单只有一处，加了新状态这里自动跟上。
    if order.status not in LINE_EDITABLE_STATUSES:
        state = {
            OrderStatus.DELIVERED: "已送达",
            OrderStatus.CANCELLED: "已撤销",
            OrderStatus.RETURNED: "已退货",
        }.get(order.status, "已完成")
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
    response: Response,
    db: Session = Depends(get_db),
    shipper_id: int | None = Query(None),
    temp_shipper_name: str | None = Query(None, description="临时货主名称（与 shipper_id 二选一）"),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    limit: int | None = Query(None, ge=1, le=5000, description="返回条数上限（缺省=1000，最多 5000）"),
    offset: int = Query(0, ge=0, description="跳过前 N 条（翻页用）"),
) -> list[LedgerOut]:
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

    # 日期窗口：`entry_date` 闭区间 —— 与 `GET /ledger/entries` 共用 `_apply_date_window`
    q = _apply_date_window(q, date_from, date_to)

    # ⚠️ **所有**查询都有缺省上限，并且把"是不是被截断了"如实写进响应头
    #    （2026-09-19 外部完整检查 C-4）。原来这条端点**没有 limit**：实测 85,474 行
    #    → 27.75 秒 / 响应体 29.12 MB / 客户端把整包解析成 DTO 再交给列表，
    #    而两个已经发到用户手机上的安卓账本页在"清掉日期筛选"时走的正是这条全量路径。
    #    形状与 `GET /orders` / `GET /notifications` 同源：多取一行判截断，
    #    `X-Result-Limit` 说明本次上限（裸数组响应体加不了元数据，只能走头）。
    #    缺省取 1000（比订单列表的 300 大）：账本一行的体量小得多，而"账本少看见一笔钱"
    #    比"订单少看见几条"严重；1000 行的响应体约 0.3MB，SQL 条数与行数无关。
    DEFAULT_LEDGER_LIMIT = 1000
    effective_limit = limit or DEFAULT_LEDGER_LIMIT
    rows = list(db.scalars(q.offset(offset).limit(effective_limit + 1)).all())
    return ledger_rows_to_out(finish_page(rows, effective_limit, response), db)


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

    q = visible_ledger_select()  # 同上：隔离区订单的账不算（R13-R6）
    # 日期窗口：`entry_date` 闭区间 —— 与 `GET /ledger/entries` 共用 `_apply_date_window`
    q = _apply_date_window(q, date_from, date_to)

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
            b = buckets.setdefault(
                key,
                {
                    "id": r.shipper_id,
                    "temp_name": None,
                    "name": "",
                    "phone": None,
                    "is_active": False,
                    "count": 0,
                    "total": Decimal("0"),
                },
            )
            if not b["name"]:
                b["name"] = (u.full_name or u.phone or f"货主#{r.shipper_id}") if u else f"货主#{r.shipper_id}"
                # 手机号去软删后缀（`13800001234_del160` → `13800001234`）：给用户看的是一个能拨的号
                b["phone"] = (strip_del_suffix(u.phone) or None) if u else None
                b["is_active"] = bool(getattr(u, "is_active", True)) if u else False
        else:
            if kind == "member":
                continue
            name = (r.temp_shipper_name or "").strip() or "临时货主"
            key = ("t", name)
            # 临时货主没有账号 → 没有手机号；`is_active` 恒 True（"没有账号"不是"账号停用"）
            b = buckets.setdefault(
                key,
                {
                    "id": None,
                    "temp_name": name,
                    "name": name,
                    "phone": None,
                    "is_active": True,
                    "count": 0,
                    "total": Decimal("0"),
                },
            )
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
    """建一个账本导出任务（异步生成，完成后发站内信带下载链接）。

    ### 三道闸（2026-09-19 外部完整检查 C-5）
    这条端点原来是**完全无闸**的：只要有账号就能 fire-and-forget 地连点，而重活
    （读全区间流水 + 拼 xlsx）跑在同一进程的线程池里。实测单任务 39.77 秒 / 85,119 条 SQL /
    峰值 RSS 469MB，并且能把最廉价的端点（`/health` 级）从 1ms 拖到 29.77 秒 ——
    一个货主就能让所有人的请求排队。三道闸分别是：

    1. **同一个账号同时只能有一个在跑**（`acquire_export_slot`，OS 文件锁，进程死了自动释放）；
    2. **每天最多 [EXPORT_DAILY_QUOTA] 次**（配额，拦住"跑完立刻再来一次"的循环）；
    3. **单次区间最多 [MAX_EXPORT_ROWS] 笔** —— 这是**按行数**而不是按天数的上限：
       天数是个猜的数字（一天的流水可能是 3 笔也可能是 3000 笔），而行数是成本的直接度量。
       超了就告诉用户实际有多少笔、请他缩小范围，而不是闷头跑 40 秒。

    ⚠️ 三道闸都在**落库之前**，失败时不留下一个永远不会被执行的 PENDING 任务。
    ⚠️ 第 1 条是"最好努力"：两个请求同时到达时可能都看到空槽（真正的互斥由文件锁在
       紧接的 `acquire_export_slot` 里做，那个是原子的）。
    """
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

    # ---- 闸 3：先算这次要导多少笔（与导出侧同一句 `visible_ledger_select`，口径不许分叉）----
    rows_in_range = int(
        db.scalar(
            select(func.count()).select_from(
                visible_ledger_select()
                .where(Ledger.shipper_id == body.shipper_id)
                .where(Ledger.entry_date >= body.date_from)
                .where(Ledger.entry_date <= body.date_to)
                .subquery()
            )
        )
        or 0
    )
    if rows_in_range > MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"这个区间有 {rows_in_range} 笔流水，一次最多导出 {MAX_EXPORT_ROWS} 笔"
                f"（导出会占用服务器很久，也会拖慢其他人的操作）。请把日期范围缩小一些，分几次导。"
            ),
        )

    # ---- 闸 2：配额 ----
    # ⚠️ 这里的 24 小时窗口用的是 `utc_now_naive()`，而生产 MySQL 的 `created_at` 是
    #    会话时区的墙上时间（+08:00）—— 两者差 8 小时，所以实际窗口会略宽于 24 小时。
    #    这是 **C-2（时间基准不统一）** 的已知代价，方向是"更宽松"，不影响闸 1 的拦截；
    #    等时间基准收敛之后再回来把这条改成同源（台账里记了）。
    recent_jobs = int(
        db.scalar(
            select(func.count())
            .select_from(LedgerExportJob)
            .where(
                LedgerExportJob.created_by_id == current.id,
                LedgerExportJob.created_at > utc_now_naive() - timedelta(hours=24),
            )
        )
        or 0
    )
    if recent_jobs >= EXPORT_DAILY_QUOTA:
        raise HTTPException(
            status_code=429,
            detail=(
                f"今天已经导出 {recent_jobs} 次（上限 {EXPORT_DAILY_QUOTA} 次）。"
                "导出产物在消息中心能重复下载，不需要重新生成；确实还要导，请明天再试。"
            ),
        )

    # ---- 闸 1：占槽位（原子；占不到说明上一个还在跑）----
    slot = acquire_export_slot(current.id)
    if slot is None:
        raise HTTPException(
            status_code=429,
            detail="上一次导出还在生成中，请等它完成（完成后会发站内信，里面有下载链接）再导下一次。",
        )
    try:
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
    except Exception:
        release_export_slot(slot)   # 落库失败就别把槽位锁死
        raise
    background_tasks.add_task(run_ledger_export_job_with_slot, job.id, slot)
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
    _ensure_export_job_visible(job, current)
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
      ② 只有本端点能取，归属校验 = `_ensure_export_job_visible`（与查询端点**同一处**）。

    ⛔ 2026-09-24 第 19 轮：这里原来自己写了一份，而那一份**对派单员是空的**
    （`role_has_permission(role, …)` 对派单员恒真）→ 同一个任务查询 403、下载 200，
    派单员 B 能把派单员 A 给别的货主导出的整本账拖走。现在两处共用一个判据。
    """
    from fastapi.responses import FileResponse

    from app.services.ledger_export_paths import find_export_file

    job = db.get(LedgerExportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="未找到对应记录")
    _ensure_export_job_visible(job, current)

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
    # 日期窗口：`received_at` 也是 `Date` 列 → 同一处校验（格式错 400、**反序也 400**）。
    # 这一条原来只把值塞进 WHERE：`date_from > date_to` 会安静地返回 0 条（2026-09-24 第 19 轮）。
    r_start, r_end = date_window(date_from, date_to)
    if r_start is not None:
        stmt = stmt.where(ShipperReceipt.received_at >= r_start)
    if r_end is not None:
        stmt = stmt.where(ShipperReceipt.received_at <= r_end)
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
