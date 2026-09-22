"""批发商（高级货主）**自己那一本账**：他给下游货主核销。

## 这是谁的账
货主分两种（用户 2026-09-20 原话）：
「现在他是分两种货主，一个是普通货主、一个是批发商货主，我们做的这些核销
 全是**批发商货主**的……普通货主是没有这些功能的，他只有搜索订单，还有按照
 今天/昨天/上周/上个月等日期来筛选订单，而且他也没有核销功能，因为他就是给自己下单，
 所以不需要核销。」

- **普通货主**：本模块的四个端点对他**一律 403**（他给自己下单，没有第二个债务人）；
- **批发商货主**（`users.is_member = 1`）：他替下游货主下单 → 那些货主欠他钱 →
  他在**这本账上**核销。

用户还特意把两本账分清楚：「真正的批发商核销是派单员，他是另外一回事」——
派单员向他收钱走 `POST /ledger/receipts`（写 `cash_flows` + 翻 `orders.paid`），
**与本模块完全不相干**（见 `models/shipper_settlement.py` 开头那张"不写什么"的表）。

## 四个端点
| 端点 | 作用 |
| --- | --- |
| `GET /shipper-ledger/settlements` | 这一段（按**订单送达日**）他记下的核销 |
| `POST /shipper-ledger/settlements` | 核销：整单 / 按商品行 |
| `DELETE /shipper-ledger/settlements/{id}` | **撤掉核销**（软删，用户：「我们的操作都是走软删除」） |
| `POST /shipper-ledger/settlements/{id}/restore` | 把撤掉的那笔放回来 |

⚠️ **窗口按订单的送达日、不按核销时间**：否则"上个月送的单、今天收到钱"会从
本月的账面上消失，那一单看起来又变成"没核销" —— 钱和状态两边打架。
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.business_time import business_range_utc, utc_now_naive
from app.core.pagination import finish_page
from app.database import get_db
from app.deps import parse_date_range, require_roles
from app.models import Order, User
from app.models.enums import OperationAction, UserRole
from app.models.shipper_settlement import ShipperSettlement, ShipperSettlementLine
from app.schemas.shipper_settlement import (
    ShipperLedgerSummaryOut,
    ShipperSettlementCreate,
    ShipperSettlementLineOut,
    ShipperSettlementOut,
)
from app.services.money_text import money_text
from app.services.operation_log_service import write_log
from app.services.order_money import line_receivable, money_map, q2
from app.services.shipper_settle import lines_of_order, settle_blocker

router = APIRouter(prefix="/shipper-ledger", tags=["shipper-ledger"])

#: 这本账**只有货主自己**能读能写。
#: ⚠️ 用 `Depends(require_roles(...))` 而不是在函数体里手写 403：端点索引与 AI 读能力目录
#:    都是**从依赖注解**推导"谁能调"的（体内那种间接调用它们看不出来），
#:    写成体内判断会让目录把这张表标成"派单员/司机也能读"——AI 于是会答应一件必然 403 的事。
ShipperOnly = Annotated[User, Depends(require_roles(UserRole.SHIPPER))]

#: 列表缺省一次回多少笔核销（与订单页同量级；核销远少于订单，500 足够）
DEFAULT_SETTLE_LIMIT = 500

#: 金额零（统计那几个累加器的起点）。与 `services/order_money.ZERO` 同一个值，
#: 但本模块只用它做**累加起点**，不参与任何口径判断。
ZERO_D = Decimal("0")


def _require_member(current: User) -> None:
    """能不能写这本账：只有**批发商**。

    ⚠️ 这一道留在函数体里是**刻意**的：它是"同一种角色的两种人"（普通货主 / 批发商货主），
       角色目录表达不了它；而它拦下的是**写**，写端点不进读能力目录。
       报错要把原因说透 —— 普通货主看到"403"只会以为系统坏了。
    """
    if not bool(getattr(current, "is_member", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "只有批发商（高级货主）需要给下游货主核销 —— "
                "普通货主是给自己下单、收自己的货，没有这一项"
            ),
        )


def _own_order(db: Session, current: User, order_id: int) -> Order:
    """取出**自己的**订单（别人的单一律 404 —— 不说"存在但不是你的"）。"""
    order = db.get(Order, order_id)
    if order is None or order.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


def _assemble(
    rows: list[tuple[ShipperSettlement, str | None, list[ShipperSettlementLine]]],
) -> list[ShipperSettlementOut]:
    out: list[ShipperSettlementOut] = []
    for s, order_no, lines in rows:
        out.append(
            ShipperSettlementOut.model_validate(s).model_copy(
                update={
                    "order_no": order_no,
                    "lines": [ShipperSettlementLineOut.model_validate(x) for x in lines],
                }
            )
        )
    return out


def _lines_for(db: Session, settlement_ids: list[int]) -> dict[int, list[ShipperSettlementLine]]:
    if not settlement_ids:
        return {}
    rows = db.scalars(
        select(ShipperSettlementLine)
        .where(ShipperSettlementLine.settlement_id.in_(settlement_ids))
        .order_by(ShipperSettlementLine.id)
    ).all()
    out: dict[int, list[ShipperSettlementLine]] = {}
    for r in rows:
        out.setdefault(r.settlement_id, []).append(r)
    return out


#: 归属人为空时那一档的名字。⛔ 必须与客户端 `ui/shipper/ShipperLedgerGrouping.kt::UNSET_CUSTOMER`
#: **逐字一致**：它既是一个显示用的名字，也是"按人筛"时的**过滤依据**（见 [_customer_filter]）。
UNSET_CUSTOMER = "未指定货主"


def _customer_name_expr():
    """「这一单归谁」的名字表达式 —— **与客户端 `customerNameOf` 同一套回退**。

    收货人名 → 下单人名 → 空。客户端（`ShipperLedgerGrouping.kt`）就是这么分组的，
    这里必须一字不差地照抄，否则"按人筛"的合计会与页面上那个人的行对不上。
    """
    return func.coalesce(
        func.nullif(func.trim(func.coalesce(Order.contact_dongjia_name, "")), ""),
        func.trim(func.coalesce(Order.contact_boss_name, "")),
        "",
    )


def _customer_phone_expr():
    """归属人的电话（收货人优先，其次下单人）—— 与客户端 `customerPhoneOf` 同一套回退。"""
    return func.coalesce(
        func.nullif(func.trim(func.coalesce(Order.contact_dongjia_phone, "")), ""),
        func.trim(func.coalesce(Order.contact_boss_phone, "")),
        "",
    )


def _customer_filter(stmt, customer_name: str | None, customer_phone: str | None):
    """只看**某一个下游货主**（侧边抽屉里点了谁）。

    ⚠️ 判据是**名字 + 电话**（与客户端的 `customerKeyOf` 同一个键）：
       只用名字会把两个同名的货主并成一个 —— "张老板"在这个行业里遍地都是，
       并起来的后果是"他的欠款翻倍、另一个人的欠款不见了"，而两边都不报错。
    ⚠️ `customer_phone` 允许为空（老单没记电话）：那时按**名字 + 电话也为空**比，
       否则"电话为空的那些单"永远筛不出来。
    """
    if not customer_name:
        return stmt
    want_name = customer_name.strip()
    want_phone = (customer_phone or "").strip()
    return stmt.where(_customer_name_expr() == want_name).where(_customer_phone_expr() == want_phone)


@router.get("/summary", response_model=ShipperLedgerSummaryOut)
def ledger_summary(
    current: ShipperOnly,
    db: Session = Depends(get_db),
    delivered_from: str | None = Query(
        None, description="YYYY-MM-DD（含当天，按**订单送达日**的当地日；与订单列表同窗口）"
    ),
    delivered_to: str | None = Query(None, description="YYYY-MM-DD（含当天）"),
    customer_name: str | None = Query(
        None, description="只看这一个下游货主（订单上的**收货人**，空则下单人；缺省 = 全部）"
    ),
    customer_phone: str | None = Query(None, description="与名字一起构成归属人的键（同名不同电话不合并）"),
) -> ShipperLedgerSummaryOut:
    """「我的账本」顶上那段**收支统计**（2026-09-22 用户要求：账本的统计对货主与批发商也做）。

    ## 它回答两个方向
    · **支出（我该付的）**：这一段我下的这些单 —— 货款 / 已付 / 还欠；
    · **收入（我该收的）**：只有**批发商**才有真数 —— 他向他的下游货主收的钱
      （应收货款 / 已收 = 他自己记的核销 / 待收）。

    ⚠️ **「我该付的」是货款，不是"货款＋运费"**：`order_money.OrderMoney.receivable`
        = `Σ 行金额 − 已退`（`orders` 上那笔运费是**公司付给司机**的钱，不进他与公司之间的账）。
        ⛔ 别在这里"顺手加上运费" —— 那会让界面上这个数与订单详情里的欠款对不上
        （同一个概念两个答案，本项目最贵的一类错）。

    ## ⛔ 为什么必须是服务端算（这一页最容易踩的坑）
    这一页的订单列表是**带 limit 的一页**（`LEDGER_PAGE_LIMIT`）。界面原来把这一页的钱
    加起来当"这一段合计"，**列表一被截断它就偏小** —— 而页面上写着"这一段"。
    期① 的审计里那个"客户端求和少算 62%"就是同一个形状（同一个数两个答案，两边都不报错）。

    ## 口径一律复用，不另算一套
    · 订单侧三个数走 `services/order_money.py::money_map`（"一张单的钱"唯一实现，
      与订单出参里的 `settled_amount` / `arrears_amount` 同源）；
    · 下游侧三个数走 `order_money.line_receivable` + 未撤销的核销行（`services/shipper_settle.py`）。
    """
    stmt = (
        select(Order)
        .options(selectinload(Order.order_products))
        .where(Order.shipper_id == current.id)
        .where(Order.deleted_at.is_(None))
    )
    # 窗口按**送达日**（与列表同一套换算，见 `_apply_delivered_window` 那段注释里记的时区坑）。
    if delivered_from or delivered_to:
        df, dt = parse_date_range(delivered_from, delivered_to)
        if df is not None and dt is not None:
            lo, hi = business_range_utc(df.date(), dt.date())
            stmt = stmt.where(Order.delivered_at.isnot(None))
            stmt = stmt.where(Order.delivered_at >= lo).where(Order.delivered_at < hi)
    stmt = _customer_filter(stmt, customer_name, customer_phone)

    # ⚠️ 这里**不设 limit**：统计要的是"这一段全部"，截断正是这张卡要修掉的那个 bug。
    orders = list(db.scalars(stmt).unique().all())

    money = money_map(db, orders)
    payable = ZERO_D
    paid = ZERO_D
    unpaid = ZERO_D
    cleared = 0
    for o in orders:
        m = money.get(o.id)
        if m is None:
            continue
        # 「应付」= 订单金额 − 已退（`OrderMoney.receivable` 就是这个定义）
        payable += m.receivable
        # 「已付」= 已收 − 已退现金（净额；退现不该算成"他还欠着"）
        paid += m.net_collected
        unpaid += m.arrears
        if m.arrears <= ZERO_D:
            cleared += 1
    payable, paid, unpaid = q2(payable), q2(paid), q2(unpaid)

    is_member = bool(getattr(current, "is_member", False))
    receivable = ZERO_D
    received = ZERO_D
    settle_count = 0
    if is_member:
        # 收入侧（只有批发商有）：应收货款 → 行应收之和（退掉的部分 `line_receivable` 里已经扣了）
        for o in orders:
            receivable += sum((line_receivable(op) for op in o.order_products), ZERO_D)
        order_ids = [o.id for o in orders]
        if order_ids:
            # 已收 = **未撤销**的核销合计。⚠️ 窗口在这条查询上按**这些单**（而不是按核销时间）：
            #    与列表同集合，界面上不会出现"单在这段里、他的核销却不算"。
            row = db.execute(
                select(
                    func.coalesce(func.sum(ShipperSettlement.amount), 0),
                    func.count(),
                )
                .where(ShipperSettlement.shipper_id == current.id)
                .where(ShipperSettlement.order_id.in_(order_ids))
                .where(ShipperSettlement.is_deleted.is_(False))
            ).one()
            received = q2(Decimal(row[0] or 0))
            settle_count = int(row[1] or 0)

    # ⚠️ 这三个数**无条件**过 `q2`（普通货主那一支也要）：`Decimal("0")` 会被序列化成 `"0"`
    #    而不是 `"0.00"`，同一张卡上出现两种金额写法（`0` 与 `0.00`）比数字错还难看出来。
    receivable = q2(receivable)
    received = q2(received)

    return ShipperLedgerSummaryOut(
        orders=len(orders),
        cleared_orders=cleared,
        payable=payable,
        paid=paid,
        unpaid=unpaid,
        receivable=receivable,
        received=received,
        unreceived=q2(receivable - received),
        settlements=settle_count,
        is_member=is_member,
    )


@router.get("/settlements", response_model=list[ShipperSettlementOut])
def list_settlements(
    current: ShipperOnly,
    response: Response,
    db: Session = Depends(get_db),
    order_id: int | None = Query(None, description="只看这一单的核销记录"),
    delivered_from: str | None = Query(
        None, description="YYYY-MM-DD（含当天，按**订单送达日**的当地日；与订单列表同窗口）"
    ),
    delivered_to: str | None = Query(None, description="YYYY-MM-DD（含当天）"),
    include_deleted: bool = Query(
        False, description="连**已撤销**的核销一起回（界面上的回收站用；恢复要先找得到它）"
    ),
    limit: int | None = Query(None, ge=1, le=2000, description="返回条数上限（缺省 500）"),
    offset: int = Query(0, ge=0),
) -> list[ShipperSettlementOut]:
    """他记下的核销（默认只回没撤销的）。"""
    effective_limit = limit or DEFAULT_SETTLE_LIMIT

    stmt = (
        select(ShipperSettlement, Order.order_no)
        .join(Order, Order.id == ShipperSettlement.order_id)
        .where(ShipperSettlement.shipper_id == current.id)
        .order_by(ShipperSettlement.id.desc())
    )
    if order_id is not None:
        stmt = stmt.where(ShipperSettlement.order_id == order_id)
    if not include_deleted:
        stmt = stmt.where(ShipperSettlement.is_deleted.is_(False))
    if delivered_from or delivered_to:
        # ✅ 这一处**过了换算**（`business_range_utc`）：`delivered_from/to` 是业务当地日，
        #    而 `Order.delivered_at` 存的是 UTC naive —— 直接比会让当地 00:00~08:00 送达的单
        #    掉出窗口（与审计 R12-M11 同族）。
        df, dt = parse_date_range(delivered_from, delivered_to)
        if df is not None and dt is not None:
            lo, hi = business_range_utc(df.date(), dt.date())
            stmt = stmt.where(Order.delivered_at.isnot(None))
            stmt = stmt.where(Order.delivered_at >= lo).where(Order.delivered_at < hi)

    rows = list(db.execute(stmt.offset(offset).limit(effective_limit + 1)).all())
    page = finish_page(rows, effective_limit, response)
    lines_by = _lines_for(db, [s.id for s, _ in page])
    return _assemble([(s, no, lines_by.get(s.id, [])) for s, no in page])


@router.post("/settlements", response_model=ShipperSettlementOut, status_code=status.HTTP_201_CREATED)
def create_settlement(
    body: ShipperSettlementCreate,
    current: ShipperOnly,
    db: Session = Depends(get_db),
) -> ShipperSettlementOut:
    """核销一笔：**整单**（`lines` 留空）或**按商品**（给要核的那几行）。

    金额**由服务端算**：`lines` 留空时每行按「还可核销」全额；给了行就按给的行，
    但**一行都不许超过它还可核销的数**（超收会把"他还欠我多少"算成负数，
    而负数在下游客户的账上没有人认领）。
    """
    _require_member(current)
    order = _own_order(db, current, body.order_id)
    blocker = settle_blocker(order)
    if blocker:
        raise HTTPException(status_code=400, detail=blocker)

    pairs = lines_of_order(db, order)
    by_line = {op.id: (op, left) for op, left in pairs}

    picks: list[tuple[int, str, Decimal]] = []  # (order_product_id, 商品名, 本次核销金额)
    if body.lines:
        seen: set[int] = set()
        for want in body.lines:
            if want.order_product_id in seen:
                raise HTTPException(
                    status_code=400,
                    detail=f"同一行商品只能核销一次（重复给了 #{want.order_product_id}）",
                )
            seen.add(want.order_product_id)
            entry = by_line.get(want.order_product_id)
            if entry is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"商品行 #{want.order_product_id} 不属于这张单，不能核销",
                )
            op, left = entry
            amount = q2(Decimal(want.amount))
            name = op.product_name_snapshot or "（未命名商品）"
            if left <= 0:
                raise HTTPException(
                    status_code=400, detail=f"「{name}」这一行已经收齐了，不用再核销"
                )
            if amount > left:
                raise HTTPException(
                    status_code=400,
                    # 这句话会原样弹给用户看（安卓侧明确"失败要把后端那句中文原样显示"）→
                    # 金额过 `money_text` 去尾零；判据仍是上面那行 `amount > left`（`Decimal`）。
                    detail=f"「{name}」还可核销 ¥{money_text(left)}，不能核 ¥{money_text(amount)}",
                )
            picks.append((op.id, name, amount))
    else:
        picks = [
            (op.id, op.product_name_snapshot or "（未命名商品）", left)
            for op, left in pairs
            if left > 0
        ]
        if not picks:
            raise HTTPException(
                status_code=400, detail="这张单已经核销完了（没有可核销的金额）"
            )

    total = q2(sum((amount for _, _, amount in picks), Decimal("0")))
    customer_name = (order.contact_dongjia_name or "").strip() or (
        order.contact_boss_name or ""
    ).strip()
    customer_phone = (order.contact_dongjia_phone or "").strip() or (
        order.contact_boss_phone or ""
    ).strip()

    s = ShipperSettlement(
        shipper_id=current.id,
        order_id=order.id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        amount=total,
        method=body.method,
        note=(body.note or "").strip(),
        settled_at=utc_now_naive(),
        source=body.source,
    )
    db.add(s)
    db.flush()
    lines = [
        ShipperSettlementLine(
            settlement_id=s.id,
            order_id=order.id,
            order_product_id=opid,
            product_name=name,
            amount=amount,
        )
        for opid, name, amount in picks
    ]
    for line in lines:
        db.add(line)

    # 钱动了必须留痕（与人工操作同形）：这本账**不写** cash_flows / orders.paid，
    # 所以 operation_logs 是唯一能回答"这笔核销谁在什么时候记的"的地方。
    write_log(
        db,
        operator_id=current.id,
        order_id=order.id,
        action=OperationAction.SHIPPER_SETTLE_CREATE,
        change_payload={
            "settlement_id": s.id,
            "order_no": order.order_no,
            "customer_name": customer_name,
            "amount": str(total),
            "method": body.method,
            "source": body.source,
            "lines": [
                {"order_product_id": opid, "product_name": name, "amount": str(amount)}
                for opid, name, amount in picks
            ],
        },
    )
    db.commit()
    db.refresh(s)
    return _assemble([(s, order.order_no, lines)])[0]


@router.delete("/settlements/{settlement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_settlement(
    settlement_id: int,
    current: ShipperOnly,
    db: Session = Depends(get_db),
) -> None:
    """**撤掉核销**（软删：行留着，`POST /{id}/restore` 逐字段放回来）。"""
    _require_member(current)
    s = db.get(ShipperSettlement, settlement_id)
    if s is None or s.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="这笔核销记录不存在")
    if s.is_deleted:
        raise HTTPException(status_code=400, detail="这笔核销已经撤掉了，不用再撤")
    order = db.get(Order, s.order_id)
    s.is_deleted = True
    s.deleted_at = utc_now_naive()
    write_log(
        db,
        operator_id=current.id,
        order_id=s.order_id,
        action=OperationAction.SHIPPER_SETTLE_REVOKE,
        change_payload={
            "settlement_id": s.id,
            "order_no": order.order_no if order else None,
            "customer_name": s.customer_name,
            "amount": str(s.amount),
            "note": "撤销核销（软删，可 restore 恢复）",
        },
    )
    db.commit()


@router.post("/settlements/{settlement_id}/restore", response_model=ShipperSettlementOut)
def restore_settlement(
    settlement_id: int,
    current: ShipperOnly,
    db: Session = Depends(get_db),
) -> ShipperSettlementOut:
    """把撤掉的核销放回来（`DELETE` 的逆操作）。"""
    _require_member(current)
    s = db.get(ShipperSettlement, settlement_id)
    if s is None or s.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="这笔核销记录不存在")
    if not s.is_deleted:
        raise HTTPException(status_code=400, detail="这笔核销没有被撤销，不需要恢复")
    s.is_deleted = False
    s.deleted_at = None
    order = db.get(Order, s.order_id)
    write_log(
        db,
        operator_id=current.id,
        order_id=s.order_id,
        action=OperationAction.SHIPPER_SETTLE_RESTORE,
        change_payload={
            "settlement_id": s.id,
            "order_no": order.order_no if order else None,
            "customer_name": s.customer_name,
            "amount": str(s.amount),
        },
    )
    db.commit()
    db.refresh(s)
    lines = _lines_for(db, [s.id]).get(s.id, [])
    return _assemble([(s, order.order_no if order else None, lines)])[0]
