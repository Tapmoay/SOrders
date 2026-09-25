"""报表（派单员）：营业额/商品明细 按日/周/月聚合，供折线图与条形图使用。"""

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from app.core.business_time import business_date, business_local, business_range_utc, local_stamp
from app.services.ledger_scope import visible_ledger_select
from app.core.date_window import ensure_date_order
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import Order, OrderProduct, User
from app.models.enums import OrderStatus
from app.schemas.reports import ProductReportItem, ProductReportOut, ReportArrearsUnitItem, ReportSeriesItem, TurnoverReportOut
from app.services.cost_basis import SNAPSHOT, CostBasis
from app.services.money_contract import has_per_order_pay, line_receivable, money_map, pay_for_order
from app.services.sheet_text import append_text_row

from app.services.reports_service import (
    _window, _label, _span_label, _span, _range_dates, delivered_span_sql, load_delivered, build_turnover, build_products, _cost_basis_note, build_arrears_summary, _money,   # noqa: F401 —— 阶段 4 下沉到 service 层，这里 re-export 保住既有引用
)


router = APIRouter(prefix="/reports", tags=["reports"])






















@router.get("/turnover", response_model=TurnoverReportOut)
def turnover_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: date = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
    date_from: date | None = Query(None, description="YYYY-MM-DD（与 date_to 成对给，优先于 mode+anchor）"),
    date_to: date | None = Query(None, description="YYYY-MM-DD"),
) -> TurnoverReportOut:
    span = _span(mode, anchor, date_from, date_to)
    data = build_turnover(db, mode, anchor, span=span)
    data.pop("_window", None)
    return TurnoverReportOut(**{**data, "period_label": data["period_label"]})


@router.get("/products", response_model=ProductReportOut)
def product_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: date = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
    date_from: date | None = Query(None, description="YYYY-MM-DD（与 date_to 成对给，优先于 mode+anchor）"),
    date_to: date | None = Query(None, description="YYYY-MM-DD"),
) -> ProductReportOut:
    span = _span(mode, anchor, date_from, date_to)
    data = build_products(db, mode, anchor, span=span)
    data.pop("_window", None)
    return ProductReportOut(**data)




@router.get("/arrears-summary")
def arrears_summary(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    date_from: date = Query(..., description="YYYY-MM-DD"),
    date_to: date = Query(..., description="YYYY-MM-DD"),
) -> list[dict]:
    ensure_date_order(date_from, date_to)
    start = date_from
    end = date_to
    return build_arrears_summary(db, start, end)




@router.get("/export")
def export_report(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),
    kind: str = Query(..., pattern="^(turnover|products|drivers|customers|finance|audit)$"),
    mode: str = Query("day", pattern="^(day|week|month)$"),
    anchor: date = Query(..., alias="date", description="YYYY-MM-DD 锚点日期"),
    date_from: date | None = Query(None, description="YYYY-MM-DD（finance/customers 可用，优先于 mode+anchor）"),
    date_to: date | None = Query(None, description="YYYY-MM-DD"),
) -> StreamingResponse:
    """报表 Excel 导出（内存流 xlsx）。"""
    from io import BytesIO
    from openpyxl import Workbook

    from app.models import CashFlow, DriverSettlement, Expense, Ledger
    from app.models.enums import SettlementStatus

    d = anchor
    # 文件名的日期段 = **这一份报表真实取数的区间**（不是锚点日）。
    # ⛔ 原来只有 drivers/customers/finance/audit 四个 kind 按真实区间命名，
    #    `turnover`/`products` 一律写锚点日 —— 而它们的内容是 `_window(mode, anchor)`
    #    （mode=month 时是整月）：`kind=turnover&mode=month&date=2026-09-18` 导出的文件叫
    #    `turnover-report-2026-09-18.xlsx`、内容却是 09-01~09-30。对账/存档时按文件名找回来
    #    会拿到一份"名字与内容不符"的凭证（2026-09-19 第二轮外部检查 R2-4；
    #    第十一轮报过一次，第十五轮只修了另外四个 kind，这两个漏了）。
    # ⚠️ 2026-09-22（报表时间控件换成档位药丸那一轮）：**六个 kind 现在都认 `date_from/date_to`**
    #    （`turnover`/`products` 也收下了），所以这一段的判据收成**一个** `_span(...)` ——
    #    与页面上、与下面 `build_*` 用的是**同一个窗口**。原来那段"turnover/products 一律按 mode"
    #    的分支留着就又会分叉（App 现在发的就是区间）。
    s, e = _span(mode, d, date_from, date_to)
    range_label = f"{s}_{e}" if s != e else str(s)
    wb = Workbook()

    def next_sheet(title: str):
        if wb.active.title == "Sheet" and wb.active.max_row == 1 and wb.active.max_column == 1:
            ws = wb.active
            ws.title = title
            return ws
        return wb.create_sheet(title)

    if kind == "turnover":
        data = build_turnover(db, mode, d, span=(s, e))
        ws = next_sheet("营业纵览")
        append_text_row(ws, ["营业纵览", _span_label(s, e), "金额口径：已送达未撤销"])
        append_text_row(ws, ["营业金额", _money(data["total_amount"]), "订单数", data["total_orders"], "单均价", _money(data["avg_order"])])
        append_text_row(ws, [
            # 口径同「司机运费结算」页：按计费规则应付（不是订单上的运费）——审计 R12-M2
            "司机运费支出(按计费规则应付)", _money(data["total_freight"]),
            "商品毛利(仅算得出成本的行)",
            # 毛利 = 参与计算的收入 − 那些行的成本。**两侧必须是同一批行**（见 schemas/reports.py 的注释）
            _money(data["cost_covered_amount"] - data["cost_total"]),
            _cost_basis_note(data),
        ])
        append_text_row(ws, ["货损件数", data["damage_qty"], "货损金额", _money(data["damage_amount"]), "已收", _money(data["collected"])])
        append_text_row(ws, ["挂账未收", _money(data["arrears_total"]), "已撤销订单", data["cancelled_orders"]])
        append_text_row(ws, [])
        append_text_row(ws, ["时间", "单数", "金额", "运费"])
        for pt in data["series"]:
            # ⚠️ 循环变量刻意不叫 `s`：`s`/`e` 是上面算好的**导出区间**（文件名与内容同源），
            #    拿 `s` 当循环变量会把它盖掉 —— 而这里恰好是"营业纵览"分支，改名零风险。
            append_text_row(ws, [pt.label, pt.orders, _money(pt.amount), _money(pt.freight)])
        append_text_row(ws, [])
        append_text_row(ws, ["挂账未收单位TOP"])
        for u in data["arrears_units"]:
            append_text_row(ws, [u.name, _money(u.amount)])
    elif kind == "products":
        data = build_products(db, mode, d, span=(s, e))
        ws = next_sheet("商品经营")
        append_text_row(ws, ["商品经营", _span_label(s, e)])
        # ⚠️ 毛利的两侧必须**同一批行**（2026-09-19 审计第十七轮）：这里原来用
        #    "Σ 有成本行的**全额**金额 − cost_total" 当表头毛利 → 与营业纵览
        #    （cost_covered_amount − cost_total）差 ¥282（本机 11,071.00 vs 10,789.00），
        #    而逐行列更离谱：用的是 `amount − cost` 老公式，合计回到修复前那个错数 72,177.75。
        append_text_row(ws, ["销售总额", _money(data["total_amount"]), "总件数", data["total_qty"],
                   "商品毛利(仅算得出成本的行)",
                   _money((data["cost_covered_amount"] or Decimal("0")) - (data["cost_total"] or Decimal("0")))])
        append_text_row(ws, ["货损件数", data["damage_qty"], "货损金额", _money(data["damage_amount"]), _cost_basis_note(data)])
        append_text_row(ws, [])
        append_text_row(ws, ["商品", "件数", "单数", "金额", "参与毛利的金额", "毛利", "货损件数", "货损金额"])
        for it in data["items"]:
            cov = it.covered_amount or Decimal("0")
            # 算不出成本的行**不进毛利**（写"—"，不是写一个看起来像毛利的大数）
            gross = _money(cov - it.cost) if (it.covered_lines or 0) > 0 else "—"
            append_text_row(ws, [it.product_name, it.qty, it.order_count, _money(it.amount), _money(cov), gross, it.damage_qty, _money(it.damage_amount)])
    elif kind in ("drivers", "customers", "finance", "audit"):
        # `s`/`e` 与文件名已经按同一套规则算好（见函数开头）——这里不许再算一遍
        if kind == "drivers":
            from app.services.stats_service import driver_performance

            ws = next_sheet("司机绩效")
            append_text_row(ws, ["司机绩效", f"{s} ~ {e}"])
            append_text_row(ws, ["司机", "完成单量", "准时率", "拍照率", "平均送达分钟", "计费方式", "待结运费"])
            # ⚠️ 这一块原来自己又写了一遍算法，于是三处与页面不是同一件事（2026-09-19 审计 R13-R5）：
            #    ① 「平均送达分钟」写死 `""` → 所有行、所有月份恒空；
            #    ② 准时率分母只算**有 `expected_deliver_before`** 的单，而页面按 models 的口径
            #       **空则按订单日末**（本库 637 张已送达单里 419 张没有 SLA → 导出恒空、页面有值）；
            #    ③ 工资制司机这里印 0，页面印"工资制"。
            #    现在**直接复用页面那一个服务**（`stats_service.driver_performance`）：
            #    一个指标只有一处实现，导出与页面不可能再走散。
            for row in driver_performance(db, s, e):
                rate = row["on_time_rate"]
                avg_sec = row["avg_delivery_seconds"]
                owed = row["freight_owed"]
                append_text_row(ws, 
                    [
                        row["driver_name"],
                        row["completed_count"],
                        "" if rate is None else round(rate, 4),
                        round(row["photo_upload_rate"] or 0.0, 4),
                        "" if avg_sec is None else round(avg_sec / 60, 2),
                        row["billing_mode"] or "",
                        # ⚠️ 待结运费必须是**数字**（2026-09-19 第二轮外部检查 R2-3(exp)）：
                        #    `stats_service.driver_performance` 这一格给的是**字符串**
                        #    （`str(Decimal)` —— 页面按 JSON 收它没问题），原样写进 xlsx
                        #    会让整列变成文本，用户在 Excel 里选这一列 `SUM` 得 **0**，
                        #    账得自己拿计算器重算（与 R13-R7 修金额列是同一个毛病，两处都走 `_money`）。
                        #    两位小数口径与页面一致（页面 `formatMoney`，`_money` 也是 ROUND_HALF_UP）。
                        # ⚠️ 工资制司机这一格仍是**文字"工资制"**（页面同款，刻意）：印 0 会被读成
                        #    "这个月一分钱都不用付给他"。
                        # ⚠️ 没有待结值（既不是工资制、服务层也没算出应付）时写真数值 0，
                        #    不再写文本 "0" —— 那一格同样是文本列里的坑。
                        "工资制" if row["billing_mode"] == "SALARY" else (_money(owed) if owed else 0),
                    ]
                )
        elif kind == "customers":
            from app.models import User

            ws = next_sheet("客户经营")
            append_text_row(ws, ["客户账汇总", f"{s} ~ {e}"])
            # 货主账/批发商账（复用 ledger accounts 逻辑的简化：按流水聚合）
            # ⚠️ 隔离区（软删）订单的那份账不算（R13-R6）：与营业纵览同一句，否则
            #    "客户经营"的订货总额会比"营业额"多出一张已删单的钱（本机差 ¥4,600）。
            # ⚠️ 日期条件**下推到 SQL**（2026-09-19 第二轮外部检查 R2-7(exp)）：原来是
            #    `list(db.scalars(visible_ledger_select()))` —— 把**整张 ledgers 表**读进内存，
            #    再在 Python 里 `if r.entry_date < s or r.entry_date > e: continue` 丢掉区间外的行。
            #    导一份"9 月客户经营"要先把三年的账全部拉进进程（还得逐行过一遍
            #    `visible_ledger_clause` 的 exists 判据），库越大越慢、内存越高。
            #    口径**一处没变**：可见性仍只由 `visible_ledger_select()` 决定，区间交给数据库。
            #    ⚠️ 原来那两行 Python 过滤是**删掉**、不是留成双保险：同一件事两个判据，
            #    下次改口径时必然只改一处（本仓库已经在"两处口径"上栽过好几次）。
            #    ⚠️ `s`/`e` 是 `date` 对象（`_window` 返回的就是 date，`date_from`/`date_to`
            #    也是），与 `Ledger.entry_date`（Date 列）同类型比较，不存在"字符串比大小"。
            rows = list(
                db.scalars(
                    visible_ledger_select()
                    .where(Ledger.entry_date >= s)
                    .where(Ledger.entry_date <= e)
                )
            )
            users: dict[int, User | None] = {}
            shipper_buckets: dict[int, dict] = {}
            member_buckets: dict[int, dict] = {}
            temp_bucket: dict[str, dict] = {}
            for r in rows:
                if r.shipper_id is not None:
                    if r.shipper_id not in users:
                        u = db.get(User, r.shipper_id)
                        users[r.shipper_id] = u
                    u = users[r.shipper_id]
                    b = (member_buckets if (u is not None and getattr(u, "is_member", False)) else shipper_buckets).setdefault(
                        r.shipper_id, {"name": (u.full_name or u.phone or f"货主#{r.shipper_id}") if u else f"货主#{r.shipper_id}", "count": 0, "total": Decimal("0")}
                    )
                else:
                    name = (r.temp_shipper_name or "").strip() or "临时货主"
                    b = temp_bucket.setdefault(name, {"name": name, "count": 0, "total": Decimal("0")})
                b["count"] += 1
                b["total"] += r.total or Decimal("0")
            append_text_row(ws, ["类别", "客户", "笔数", "总额"])
            for b in sorted(shipper_buckets.values(), key=lambda x: -x["total"]):
                append_text_row(ws, ["货主", b["name"], b["count"], _money(b["total"])])
            for b in sorted(temp_bucket.values(), key=lambda x: -x["total"]):
                append_text_row(ws, ["临时货主", b["name"], b["count"], _money(b["total"])])
            for b in sorted(member_buckets.values(), key=lambda x: -x["total"]):
                append_text_row(ws, ["批发商", b["name"], b["count"], _money(b["total"])])
            append_text_row(ws, [])
            append_text_row(ws, ["挂账未收 TOP"])
            append_text_row(ws, ["单位", "笔数", "金额"])
            for g in build_arrears_summary(db, s, e):
                append_text_row(ws, [g["name"], g["count"], _money(g["amount"])])
        elif kind == "finance":
            ws = next_sheet("资金收支")
            flows = list(
                db.scalars(
                    select(CashFlow)
                    # ⛔ 导出的数与页面上的数必须是同一批行：已撤销的流水两边都不算
                    #    （2026-09-22 起 `cash_flows` 有软删，见 `models/cash_flow.py` 文件头）。
                    .where(
                        CashFlow.flow_date >= s,
                        CashFlow.flow_date <= e,
                        CashFlow.is_deleted.is_(False),
                    )
                    .order_by(CashFlow.flow_date.desc())
                )
            )
            income = sum((f.amount for f in flows if str(f.direction).lower() == "in"), Decimal("0"))
            expense = sum((f.amount for f in flows if str(f.direction).lower() == "out"), Decimal("0"))
            append_text_row(ws, ["资金收支", f"{s} ~ {e}"])
            append_text_row(ws, ["流入", _money(income), "流出", _money(expense), "净额", _money(income - expense)])
            append_text_row(ws, [])
            append_text_row(ws, ["日期", "方向", "金额", "对象", "渠道", "类型", "备注"])
            for f in flows:
                append_text_row(ws, [f.flow_date.isoformat(),
                           "收入" if str(f.direction).lower() == "in" else "支出",
                           _money(f.amount), f.party_name or "", f.channel, f.biz_type, f.note])
            append_text_row(ws, [])
            append_text_row(ws, ["开销分类"])
            append_text_row(ws, ["分类", "金额"])
            exp_rows = list(db.scalars(select(Expense).where(Expense.exp_date >= s, Expense.exp_date <= e)))
            cat_map: dict[str, Decimal] = {}
            for x in exp_rows:
                cat_map[x.category] = cat_map.get(x.category, Decimal("0")) + x.amount
            for cat, amt in sorted(cat_map.items(), key=lambda kv: -kv[1]):
                append_text_row(ws, [cat, _money(amt)])
        elif kind == "audit":
            from app.models import OperationLog

            ws = next_sheet("异常与审计")
            from app.services import stats_service
            ex = stats_service.exception_orders(db, s, e)
            append_text_row(ws, ["异常订单", f"{s} ~ {e}"])
            append_text_row(ws, ["订单号", "货主", "司机", "异常原因", "处理结果", "解决时间"])
            for o in ex:
                append_text_row(ws, [
                    o["order_no"], o["shipper_name"] or "", o["driver_name"] or "",
                    o["exception_reason"], o["exception_resolution"],
                    # ⚠️ 同一张 sheet 里两个时间列必须是**同一个口径**（2026-09-24 第 20 轮 D3-F3）：
                    #    这一列原来 `isoformat()` 印的是 **UTC naive**，而下面「敏感操作日志」的
                    #    时间列（第 19 轮修的）印的是**当地时刻** —— 实测同一件事能同时出现
                    #    `2026-09-21T11:50:01.206089`（上）与 `2026-09-21 19:50`（下），
                    #    差 8 小时，看的人会以为导出的窗口错了。口径只有 `business_time.local_stamp`。
                    local_stamp(o["exception_resolved_at"], fmt="%Y-%m-%d %H:%M")
                    if o["exception_resolved_at"] else "",
                ])
            append_text_row(ws, [])
            # ⛔ 「敏感操作日志」原来**完全不看区间**（就是 `order_by(id.desc()).limit(200)`）：
            #    导出一份"09-01 的审计报告"，里面躺着的却是**库里最新**的 200 条日志（可能是 09-18 的）。
            #    审计凭证"名字写着 A、内容是 B"比"少给几条"严重得多——看的人会以为那就是当天的全部动作。
            #    现在按**业务当地日区间**过滤（与保留任务同一个 UTC 换算），并且如实说清有没有被截断。
            lo, hi = business_range_utc(s, e)
            in_range = (OperationLog.created_at >= lo, OperationLog.created_at < hi)
            total = db.scalar(
                select(func.count()).select_from(OperationLog).where(*in_range)
            ) or 0
            logs = list(
                db.scalars(
                    select(OperationLog).where(*in_range).order_by(OperationLog.id.desc()).limit(200)
                )
            )
            note = f"{s} ~ {e}"
            if total > len(logs):
                note += f"（区间内共 {total} 条，这里只列了最近 {len(logs)} 条）"
            else:
                note += f"（共 {total} 条）"
            append_text_row(ws, ["敏感操作日志", note])
            append_text_row(ws, ["时间", "操作", "内容"])
            for log in logs:
                # ⚠️ 印**当地时刻**（2026-09-24 第 19 轮）：这一列原来直接 `created_at.isoformat()`，
                #    而 `created_at` 存的是 **UTC naive** —— 东八区当地 00:00~08:00 的动作会被印成
                #    **前一天**的时间（导出的窗口却是"业务当地日"）：一份"09-24 的审计报告"里
                #    躺着一行 `2026-09-23T16:29`，看的人会以为这条动作不属于这一天、
                #    或者怀疑导出窗口没生效。口径只有一处：`business_time.local_stamp`
                #    （第 18 轮为"印给人看的时间戳"建的那个入口）；这里要带年份，所以显式给 fmt。
                append_text_row(ws, [
                    local_stamp(log.created_at, fmt="%Y-%m-%d %H:%M") if log.created_at else "",
                    log.action,
                    log.change_content or "",
                ])

    buf = BytesIO()
    wb.save(buf)
    fn = f"{kind}-report-{range_label}.xlsx"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fn}"'},
    )