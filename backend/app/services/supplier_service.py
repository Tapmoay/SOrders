"""供应商应付款的口径与写操作（**欠款只有一个实现**）。

## 这个模块存在的唯一理由
「还欠他多少」这个数一旦在两处各算一遍，就一定会有一天两边不一样，而**两边都不报错**：
列表卡片写「还欠 1,200」、详情页写「还欠 800」，用户只能猜哪个是真的。
所以 口径全部收在这里：

    payable_total（应付合计） = Σ alive 应付单金额          （按 supplier_id）
    paid_total   （已付合计） = Σ alive 付款流水金额        （按 party_type='supplier' + party_id）
    unpaid_total （还欠）     = payable_total − paid_total  （按单张应付单时是同一套减法）

⚠️ 三个数**都从库里现算**，不落在任何列上（落一列就要维护它，而"维护"总会漏）。

## 付款＝`cash_flows` 的一行（不是新表）
理由写在 `models/supplier.py` 的文件头。这里只强调两条工程后果：
1. 付款流水**必须**带 `is_deleted.is_(False)` 才参与求和（软删是"撤销付款"的实现方式）；
2. `cash_flows` 是钱的总账，所以**付款与撤销付款都要在审计里留痕**（动作码见 `enums.py`）。

## 三条"宁可拒绝也不猜"（每一条都对应一种会让账变错的操作）
1. **付款不许超过这张单还差的**：超了他就是"预付"，而预付款在这套账里没有位置
   （欠款会变成负数，界面上没人读得对）。要么改小，要么另建一张应付单。
2. **有付款的应付单不许删**（不管是活的还是已撤的付款）：删了单据、付款流水还挂着
   `doc_id`，那笔钱就变成"付出去了、账上没有任何对应的应付款"——正是
   `paying a settlement with no lines` 那一类历史缺陷。
3. **供应商名下有应付单不许删**：删除会把档案藏起来，而欠款还挂在一个看不见的供应商上。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.business_time import utc_now_naive
from app.models import CashFlow, Supplier, SupplierPayable
from app.models.enums import CashFlowBizType, CashFlowDirection
from app.services.order_money import q2
from app.services.soft_delete import del_suffix

ZERO = Decimal("0")

#: 供应商档案名的列宽（软删加后缀时要过 `del_suffix`，宽度必须与模型一致）。
SUPPLIER_NAME_WIDTH = 64

#: `party_type` 的取值：付款流水的"对方是谁"。
PARTY_SUPPLIER = "supplier"


def _paid_filter(*extra):
    """付款流水的**统一判据**：是供应商的、是付出去的钱、而且**没被撤销**。

    ⛔ `CashFlow.is_deleted.is_(False)` 这一句是这个模块最不能省的一行 ——
       少了它，撤销过的付款照样算进"已付"，表现是"撤销了但欠款还是没变回来"。
    """
    return (
        CashFlow.party_type == PARTY_SUPPLIER,
        func.lower(CashFlow.direction) == CashFlowDirection.OUT.value,
        CashFlow.biz_type == CashFlowBizType.PAYMENT_SUPPLIER,
        CashFlow.is_deleted.is_(False),
        *extra,
    )


# ---------------- 读：口径在这里，别处只许调用 ----------------
def payable_paid(db: Session, payable_id: int) -> Decimal:
    """**这张应付单**已经付了多少（只数活着的付款流水）。"""
    v = db.scalar(select(func.coalesce(func.sum(CashFlow.amount), 0)).where(*_paid_filter(CashFlow.doc_id == payable_id)))
    return q2(Decimal(v or 0))


def payable_payment_count(db: Session, payable_id: int) -> int:
    """付过几次（分次付款要看得见）。"""
    n = db.scalar(select(func.count()).select_from(CashFlow).where(*_paid_filter(CashFlow.doc_id == payable_id)))
    return int(n or 0)


def supplier_totals(db: Session, supplier_id: int) -> tuple[Decimal, Decimal]:
    """这个供应商的（应付合计, 已付合计）—— **一对**返回，别再分别查一遍。

    ⚠️ 两个数都按 `supplier_id` 汇总：已付按流水的 `party_id`（不是 `doc_id`），
       这样"某张单被删了"不会让他的已付总额凭空少掉一块。
    """
    due = db.scalar(
        select(func.coalesce(func.sum(SupplierPayable.amount), 0)).where(
            SupplierPayable.supplier_id == supplier_id,
            SupplierPayable.is_deleted.is_(False),
        )
    )
    paid = db.scalar(
        select(func.coalesce(func.sum(CashFlow.amount), 0)).where(*_paid_filter(CashFlow.party_id == supplier_id))
    )
    return q2(Decimal(due or 0)), q2(Decimal(paid or 0))


def unpaid_of(payable: SupplierPayable, paid: Decimal) -> Decimal:
    """单张单还差多少。**减法也只有这一处**（负数说明数据被外部改过，照样如实返回）。"""
    return balance_of(payable.amount, paid)


def balance_of(due: Decimal, paid: Decimal) -> Decimal:
    """**还欠 = 应付合计 − 已付合计**（全项目唯一那个减法）。

    ⛔ 为什么连"两个数相减"都要收进函数：端点上写一句 `due - paid` 看着无害，
       但那就是第二个口径的起点 —— 下一个人改口径时只改一处，另一处静默留旧。
       判据 `_tools/qa/_check_supplier_payables.py` 会拦"端点里出现 paid 参与的加减"。
    """
    return q2(Decimal(due or 0) - Decimal(paid or 0))


def get_supplier_or_404(db: Session, supplier_id: int, *, need_alive: bool = True) -> Supplier:
    s = db.get(Supplier, supplier_id)
    if s is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    if need_alive and s.is_deleted:
        raise HTTPException(
            status_code=400,
            detail="这个供应商已经删除了（在回收站里），先恢复它：POST /suppliers/{id}/restore",
        )
    return s


def get_payable_or_404(db: Session, payable_id: int, *, need_alive: bool = True) -> SupplierPayable:
    p = db.get(SupplierPayable, payable_id)
    if p is None:
        raise HTTPException(status_code=404, detail="应付单不存在")
    if need_alive and p.is_deleted:
        raise HTTPException(
            status_code=400,
            detail="这张应付单已经删除了（在回收站里），先恢复它：POST /supplier-payables/{id}/restore",
        )
    return p


# ---------------- 写 ----------------
def pay_supplier(
    db: Session,
    payable: SupplierPayable,
    *,
    amount: Decimal,
    pay_date: date,
    channel: str,
    remark: str,
    operator_id: int | None,
) -> CashFlow:
    """给这张应付单付一笔钱 → 写一行 `cash_flows`（OUT / PAYMENT_SUPPLIER）。

    校验全部在这里（端点不许自己判一遍）：金额 > 0、不超过还差、供应商必须还活着。
    """
    supplier = get_supplier_or_404(db, payable.supplier_id)
    if payable.is_deleted:
        raise HTTPException(status_code=400, detail="这张应付单已经删除了（在回收站里），先恢复它再付款")
    amt = q2(Decimal(amount))
    if amt <= ZERO:
        raise HTTPException(status_code=400, detail="付款金额要大于 0")
    paid = payable_paid(db, payable.id)
    left = unpaid_of(payable, paid)
    if left <= ZERO:
        raise HTTPException(
            status_code=400,
            detail=f"「{payable.title}」已经付清了（应付 {q2(Decimal(payable.amount))}，已付 {paid}），不用再付",
        )
    if amt > left:
        raise HTTPException(
            status_code=400,
            detail=(
                f"付款金额 {amt} 超过了这张单还差的 {left}（应付 {q2(Decimal(payable.amount))}，已付 {paid}）；"
                "要付这么多就另建一张应付单（预付款在这里没有位置）"
            ),
        )
    # ⚠️ **上面那两句只是"提前告知"，真正的闸门在这一句**（2026-09-23 并发实测抓到的真缺陷）：
    #    付款写的是**一行新的 `cash_flows`**，没有行可以像订单那样 CAS（`paid=false→true`），
    #    所以"已付合计 + 这次 ≤ 应付"这个判据必须**和占位写在同一个语句里**，
    #    否则它就是典型的"读-判断-写"：三个并发的付款请求各自读到"已付 0、还差 1000"，
    #    各自插一行 1000 —— 实测一张 1000 元的应付单**付出去 3000**（三条资金流水）。
    #    做法与全项目其它地方同一条纪律：**条件 UPDATE 占位**，只不过这里的"行"是应付单本身，
    #    条件里放的是"还差的钱够不够"（子查询在语句执行时求值，由数据库的写锁串行化；
    #    MySQL 的加锁读、SQLite 的写锁，两种库上都成立）。
    paid_sub = (
        select(func.coalesce(func.sum(CashFlow.amount), 0))
        .where(*_paid_filter(CashFlow.doc_id == payable.id))
        .scalar_subquery()
    )
    claimed = db.execute(
        update(SupplierPayable)
        .where(
            SupplierPayable.id == payable.id,
            SupplierPayable.is_deleted.is_(False),
            SupplierPayable.amount - paid_sub >= amt,
        )
        .values(updated_at=utc_now_naive())
    )
    if claimed.rowcount != 1:
        # 抢不到 = 就在刚才这一瞬间，这笔钱被另一笔付款用掉了（或整张单被付清）
        paid_now = payable_paid(db, payable.id)
        left_now = unpaid_of(payable, paid_now)
        db.rollback()
        if left_now <= ZERO:
            raise HTTPException(
                status_code=400,
                detail=f"「{payable.title}」刚刚被另一笔付款付清了（应付 {q2(Decimal(payable.amount))}，"
                       f"已付 {paid_now}），这一次没有付出去任何钱",
            )
        raise HTTPException(
            status_code=400,
            detail=f"这张单还差的钱刚刚被另一笔付款用掉了，现在只剩 {left_now} 可付"
                   f"（你要付 {amt}）；请刷新后按剩下的金额再付",
        )
    note = f"{payable.title}（第 {payable_payment_count(db, payable.id) + 1} 次付款）"
    if remark.strip():
        note = f"{note} · {remark.strip()}"
    flow = CashFlow(
        flow_date=pay_date,
        direction=CashFlowDirection.OUT,
        amount=amt,
        party_type=PARTY_SUPPLIER,
        party_id=payable.supplier_id,
        party_name=supplier.name,
        channel=channel,
        biz_type=CashFlowBizType.PAYMENT_SUPPLIER,
        order_id=None,
        doc_id=payable.id,
        note=note[:256],
        operator_id=operator_id,
    )
    db.add(flow)
    db.flush()
    return flow


def soft_delete_supplier(db: Session, supplier: Supplier) -> None:
    """伪装删除一个供应商：**有应付单就不许删**（欠款不能挂在一个看不见的供应商上）。"""
    n = db.scalar(
        select(func.count())
        .select_from(SupplierPayable)
        .where(SupplierPayable.supplier_id == supplier.id, SupplierPayable.is_deleted.is_(False))
    )
    if n:
        raise HTTPException(
            status_code=400,
            detail=f"这个供应商名下还有 {n} 张应付单（还没结清或没删），删了欠款就挂在一个看不见的供应商上了；先处理这些单",
        )
    supplier.is_deleted = True
    supplier.deleted_at = utc_now_naive()
    # 名字要**释放出来**（唯一索引）：不释放的话"删掉再建同名"直接撞唯一约束（500）。
    supplier.name = del_suffix(supplier.name, supplier.id, SUPPLIER_NAME_WIDTH)


def restore_supplier(db: Session, supplier: Supplier) -> None:
    """把删掉的供应商放回来：名字能拿回来就拿回来（被占了就保留带后缀的名字，不硬抢）。"""
    if not supplier.is_deleted:
        raise HTTPException(status_code=400, detail="这个供应商没有被删除，不需要恢复")
    suffix = f"_del{supplier.id}"
    if supplier.name.endswith(suffix):
        want = supplier.name[: -len(suffix)]
        taken = db.scalars(select(Supplier).where(Supplier.name == want, Supplier.id != supplier.id)).first()
        if taken is None:
            supplier.name = want
    supplier.is_deleted = False
    supplier.deleted_at = None


def soft_delete_payable(db: Session, payable: SupplierPayable) -> None:
    """伪装删除一张应付单：**还有活着的付款就不许删**。

    已撤销（软删）的付款**不拦** —— 那正是"付错了 → 撤销 → 这张单也不要了"这条正常路径。
    只有"活着的付款"才会被拦：单据一删，那笔钱就变成"付出去了、账上没有任何对应的应付款"，
    正是"付了一张没有明细的结算单"那一类历史缺陷。

    ⚠️ 已撤销的付款行**仍然带着 `doc_id = 这张单`**（软删是藏起来，不是抹掉），
       所以"恢复那笔付款"这条路必须自己把门（`api/v1/suppliers.py::restore_payment`
       会拒绝"单据还在回收站里"的情况）—— 两道判据合起来才没有孤儿。
    """
    n = payable_payment_count(db, payable.id)
    if n:
        raise HTTPException(
            status_code=400,
            detail=(
                f"这张应付单还有 {n} 笔没撤销的付款，删了这些钱就对不上单据了；"
                "先把那些付款撤销掉（撤销之后这张单就能删）"
            ),
        )
    payable.is_deleted = True
    payable.deleted_at = utc_now_naive()


def restore_payable(db: Session, payable: SupplierPayable) -> None:
    if not payable.is_deleted:
        raise HTTPException(status_code=400, detail="这张应付单没有被删除，不需要恢复")
    supplier = db.get(Supplier, payable.supplier_id)
    if supplier is None:
        raise HTTPException(status_code=400, detail="它对应的供应商已经不存在了，恢复不了")
    if supplier.is_deleted:
        raise HTTPException(
            status_code=400,
            detail="它对应的供应商还在回收站里，先把供应商恢复回来（POST /suppliers/{id}/restore）",
        )
    payable.is_deleted = False
    payable.deleted_at = None
