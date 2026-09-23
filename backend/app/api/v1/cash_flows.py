"""资金流水总账查询——账本 V2（所有收付的唯一写入点由各业务钩子保证）。"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.date_window import date_window
from app.core.pagination import finish_page
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import CashFlow, User
from app.models.enums import UserRole
from app.schemas.accounting_v2 import CashFlowOut

router = APIRouter(prefix="/cash-flows", tags=["cash-flows"])


def _scoped_stmt(
    current: User, direction: str | None, biz_type: str | None,
    party_type: str | None, party_id: int | None,
    date_from: date | None, date_to: date | None,
):
    """列表与汇总**共用**同一套筛选（两处各写一遍必然走散）。"""
    stmt = select(CashFlow)
    # ⛔ **已撤销的流水一律不出现**（2026-09-22 加了软删之后）：
    #    供应商付款的"撤销"就是把那一行藏起来（用户定的硬规矩：删除一律软删 + 可恢复）。
    #    少了这一句，撤销过的付款照样算进支出 —— 而供应商那边"还欠多少"已经变回来了，
    #    于是同一笔钱两个答案，两边都不报错。
    #    判据在 `_tools/qa/_check_supplier_payables.py`（它自己扫出所有读取处再逐处断言）。
    stmt = stmt.where(CashFlow.is_deleted.is_(False))
    if direction:
        # 大小写不敏感（枚举是小写 in/out）：写死大写会让这一页的流入恒为 0
        stmt = stmt.where(func.lower(CashFlow.direction) == direction.lower())
    if biz_type:
        stmt = stmt.where(CashFlow.biz_type == biz_type)
    if party_type:
        stmt = stmt.where(CashFlow.party_type == party_type)
    if party_id is not None:
        stmt = stmt.where(CashFlow.party_id == party_id)
    # ⚠️ 日期窗口走**唯一**那一处校验（2026-09-24 第 19 轮）：格式错 400、**顺序反了也 400**。
    #    原来这两行只把值直接塞进 WHERE —— `date_from > date_to` 会安静地返回 0 条，
    #    界面上就是「这段时间没有流水、流入 0」（而资金流水页正是对账要看的页）。
    start, end = date_window(date_from, date_to)
    if start is not None:
        stmt = stmt.where(CashFlow.flow_date >= start)
    if end is not None:
        stmt = stmt.where(CashFlow.flow_date <= end)
    return stmt


@router.get("", response_model=list[CashFlowOut])
def list_cash_flows(
    current: CurrentUser,
    response: Response,
    db: Session = Depends(get_db),
    direction: str | None = Query(None),
    biz_type: str | None = Query(None),
    party_type: str | None = Query(None),
    party_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> list[CashFlowOut]:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可查看")
    stmt = (
        _scoped_stmt(current, direction, biz_type, party_type, party_id, date_from, date_to)
        .order_by(CashFlow.flow_date.desc(), CashFlow.id.desc())
        # 多取一行：拿到 limit+1 行就说明还有更多（`finish_page` 据此写 X-Truncated）
        .limit(limit + 1)
    )
    return finish_page(list(db.scalars(stmt).all()), limit, response)


@router.get("/summary")
def cash_flow_summary(
    current: CurrentUser,
    db: Session = Depends(get_db),
    direction: str | None = Query(None),
    biz_type: str | None = Query(None),
    party_type: str | None = Query(None),
    party_id: int | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> dict:
    """**服务端**汇总流入/流出/净额（与列表同一套筛选）。

    ⚠️ 为什么必须有这个端点（2026-09-19 审计）：客户端原来是"拉一页流水、自己求和"，
    而 `GET /cash-flows` 有 `limit`（默认 200）。实测同一窗口：默认 limit 只拿到 200 条、
    求和流入 **¥18,842**；limit=1000 拿到 273 条、流入 **¥48,905.50** —— 页面少算 62%，
    而同一页的 Excel 导出是**在 SQL 侧全窗口求和**的（真值）。于是"页面一个数、导出一个数"。
    金额必须在数据库里算完再给客户端，客户端的 limit 只影响"看得见几行明细"。
    """
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可查看")
    stmt = _scoped_stmt(current, direction, biz_type, party_type, party_id, date_from, date_to)
    scoped = stmt.subquery()
    row = db.execute(
        select(
            func.coalesce(
                func.sum(case((func.lower(scoped.c.direction) == "in", scoped.c.amount), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((func.lower(scoped.c.direction) == "out", scoped.c.amount), else_=0)),
                0,
            ),
            func.count(),
        ).select_from(scoped)
    ).one()
    income = Decimal(str(row[0] or 0))
    expense = Decimal(str(row[1] or 0))
    return {
        "income": str(income),
        "expense": str(expense),
        "net": str(income - expense),
        "count": int(row[2] or 0),
    }


@router.get("/breakdown")
def cash_flow_breakdown(
    current: CurrentUser,
    db: Session = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> dict:
    """按**钱的来路 / 去处**分组求和（账本管理「收支」页那两段：收入来源明细 + 支出明细）。

    与 `/summary` 的分工（两个都要，不要拿一个去顶另一个）：
      · `/summary` 回答「这一段一共进了多少、出了多少、净额多少」（三个数，页顶上那个大字）；
      · `/breakdown` 回答「这些钱**分别**是从哪来的、花到哪去了」（一路一行，点得进去看明细）。

    ⚠️ 两条口径与 `/summary` 是**共用**的，不是各算各的：
      ① 筛选走同一个 `_scoped_stmt`；② 求和都在 SQL 侧 `SUM`。
      所以「分项加起来」必然等于 `/summary` 的总数 —— 这正是它存在的理由：
      客户端拉一页流水自己分类求和会**少算**（那个列表有 `limit`，实测少 62%，见 `/summary` 注释）。
      出参里的 `income_total`/`expense_total`/`net` 就是拿分项加的，页面上不必再算一遍。

    每一行：`biz_type`（枚举名，如 `RECEIPT_CASH`/`EXPENSE_FUEL`/`PAYMENT_SUPPLIER`）、
    `amount`、`count`（这一路几笔）。**中文名由客户端翻**（`ReportFinance.bizLabel` 是唯一那一份），
    这里只给枚举名 —— 后端再存一份中文词表就会与界面走散。

    ⚠️ 只有派单员能看：这是**全公司**的经营数据（成本与开销都在里面）。货主/批发商各有各的那本账
    （`/shipper-ledger` + 他们的「我的账本」），不从这一个端点出。
    """
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可查看")
    scoped = _scoped_stmt(current, None, None, None, None, date_from, date_to).subquery()
    # ⚠️ 分组键里的方向也要 `lower()`：老数据里存过大写（枚举是小写），
    #    不归一就会出现 `IN` 与 `in` 两行，而且其中一行会被下面判成"支出"。
    dir_col = func.lower(scoped.c.direction)
    rows = db.execute(
        select(
            dir_col.label("dir"),
            scoped.c.biz_type,
            func.coalesce(func.sum(scoped.c.amount), 0),
            func.count(),
        )
        .select_from(scoped)
        .group_by(dir_col, scoped.c.biz_type)
    ).all()

    income: list[dict] = []
    expense: list[dict] = []
    for direction, biz_type, amount, count in rows:
        item = {
            # NULL / 空串照样占一行（⛔ 不要并进"其他"：账上出现了没见过的东西，
            # 恰恰是这一页该让人看见的）
            "biz_type": str(biz_type or ""),
            "amount": str(Decimal(str(amount or 0))),
            "count": int(count or 0),
        }
        # 只有 `in` 算收入；其余（含历史脏值）一律归支出那一侧，页面上看得见就能查
        (income if str(direction or "").lower() == "in" else expense).append(item)

    # 钱多的排前面（与"这一页用来发现钱去哪了"一致；并列时按枚举名稳定排序）
    for bucket in (income, expense):
        bucket.sort(key=lambda x: (-Decimal(x["amount"]), x["biz_type"]))
    income_total = sum((Decimal(x["amount"]) for x in income), Decimal("0"))
    expense_total = sum((Decimal(x["amount"]) for x in expense), Decimal("0"))
    return {
        "income": income,
        "expense": expense,
        "income_total": str(income_total),
        "expense_total": str(expense_total),
        "net": str(income_total - expense_total),
        "count": sum(x["count"] for x in income) + sum(x["count"] for x in expense),
    }
