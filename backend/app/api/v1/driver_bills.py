"""司机应付明细（按月）——账本 V2：送达自动生成 PIECE 单；月薪单手工/定时生成。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.business_time import business_local
from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import DriverBill, Order, User
from app.models.enums import DriverBillStatus, DriverBillType, OperationAction, UserRole
from app.schemas.accounting_v2 import DriverBillGenerateBody, DriverBillOut
from app.services.operation_log_service import write_log
from app.services.money_contract import has_per_order_pay, pay_for_order, per_order_pay_filter
from app.services.driver_pay import (
    monthly_salary_of,
    rule_from_snapshot,
)

router = APIRouter(prefix="/driver-bills", tags=["driver-bills"])


def _bill_month(dt) -> str:
    """这一单的账单属于哪个月 = **业务当地月**（与 `accounting_service._month_of` 同源）。"""
    return business_local(dt).strftime("%Y-%m")


def _is_open_unlocked(bill: DriverBill) -> bool:
    """这张单**还没核销**吗（2026-10-15 CHG-0127 的刷新判据）。

    「未核销」= 两个条件同时成立：
    - `status == open` —— 结算单确认（`confirm`）之后会翻成 `settled`；
    - `settled_doc_id is None` —— 建结算单当刻就会写上它（`accounting_service`），
      状态此时**还是 open**：所以只判状态会把「已被一张草稿结算单点名」的单当成未核销，
      重算它就等于把那张草稿单的金额与明细改成不一致（confirm 的校验会当场拒），
      或者更糟：草稿单作废时把这张单放回去，两边数字对不上。
    """
    status = getattr(bill, "status", None)
    if str(getattr(status, "value", status) or "") != DriverBillStatus.OPEN.value:
        return False
    return getattr(bill, "settled_doc_id", None) is None


def _can_view_or_raise(current: User, db: Session, driver_id: int) -> None:
    role = user_role_key(current)
    if role == UserRole.DISPATCHER.value:
        return
    if role == UserRole.DRIVER.value and driver_id == current.id:
        return
    raise HTTPException(status_code=403, detail="无权操作")


@router.get("", response_model=list[DriverBillOut])
def list_driver_bills(
    current: CurrentUser,
    db: Session = Depends(get_db),
    driver_id: int | None = Query(None),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    status: str | None = Query(None),
    bill_type: str | None = Query(None),
    include_deleted: bool = Query(
        False, description="含「订单已进回收站」的账单（对账/审计用；缺省不显示）"
    ),
) -> list[DriverBillOut]:
    """司机账单列表。

    ⛔ 缺省要把「订单已经进回收站」的账单据掉（2026-09-24 第 25 轮；第 24 轮 08 区 D2 实测）：
    这个接口原来一个订单级的过滤都没有，于是**同一个月同一名司机有三个数**：

    | 页面 | 数字（本机实测，司机 3 / 2026-09） | 它自己的判据 |
    | --- | --- | --- |
    | 本接口（账单驱动） | 9 笔 **¥198** | 只看 `driver_bills`，不看订单 |
    | 结算单能结的（`accounting_service.create_settlement`） | 6 笔 **¥132** | 外加 `订单未软删` |
    | 运费结算页（`/freight-settlement`，订单驱动） | 4 单 **¥88** | 外加 `status=DELIVERED`（整单退货的单是 RETURNED，被排掉） |

    第一行与第二行的差**正好是"订单已被软删"的那几笔** —— 而结算页那句注释写得很清楚：
    「口径统一到**页面看得见的单才结得掉**：软删单的账单留给保留任务作废」
    （`accounting_service.py` 把这条写成了 `or_(order_id is None, Order.deleted_at is None)`）。
    账单页现在与它**同一条判据**（同一句话、同一处 `or_`），要留痕就传 `include_deleted=true`。

    ⚠️ 第三行与第二行的差是**另一件事**（整单退货的单：司机跑了这一趟，那笔应付还算不算），
    那是**产品决策**，不该由这里顺手改 —— 已在声明页的「待拍板」里挂着，附样本数字。
    """
    role = user_role_key(current)
    if role != UserRole.DISPATCHER.value and role != UserRole.DRIVER.value:
        raise HTTPException(status_code=403, detail="仅派单员/司机可查看")
    if role == UserRole.DRIVER.value:
        driver_id = current.id
    stmt = (
        select(DriverBill)
        # `outerjoin`：`order_id` 为空的历史孤儿账单仍按原样处理（那是另一条已知问题，见台账 D2）
        .outerjoin(Order, Order.id == DriverBill.order_id)
        .order_by(DriverBill.month.desc(), DriverBill.id.desc())
    )
    if not include_deleted:
        stmt = stmt.where(or_(DriverBill.order_id.is_(None), Order.deleted_at.is_(None)))
    if driver_id is not None:
        stmt = stmt.where(DriverBill.driver_id == driver_id)
    if month:
        stmt = stmt.where(DriverBill.month == month)
    if status:
        stmt = stmt.where(DriverBill.status == status)
    if bill_type:
        stmt = stmt.where(DriverBill.bill_type == bill_type)
    rows = list(db.scalars(stmt).all())
    names: dict[int, str] = {}
    out = []
    for r in rows:
        if r.driver_id not in names:
            u = db.get(User, r.driver_id)
            names[r.driver_id] = (u.full_name or u.phone or "") if u else ""

        order_no = ""
        if r.order_id:
            o = db.get(Order, r.order_id)
            order_no = o.order_no if o else ""
        out.append(
            DriverBillOut(
                **{
                    "id": r.id,
                    "driver_id": r.driver_id,
                    "bill_type": r.bill_type,
                    "order_id": r.order_id,
                    "month": r.month,
                    "amount": r.amount,
                    "status": r.status,
                    "settled_doc_id": r.settled_doc_id,
                    "note": r.note,
                    "driver_name": names[r.driver_id],
                    "order_no": order_no,
                    # v3.36：这几个字段**必须显式列出来**——这个接口是手工拼 DTO 的，
                    # 模型上加了列不等于出参里有（漏了就是"账单页看不到怎么算的"，
                    # 而钱本身是对的，所以只有测试对得上号才会发现）。
                    "rule_id": r.rule_id,
                    "rule_name": r.rule_name,
                    "piece_amount": r.piece_amount,
                    "commission_amount": r.commission_amount,
                }
            )
        )
    return out


@router.post("/generate", response_model=list[DriverBillOut])
def generate_bills(
    body: DriverBillGenerateBody,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> list[DriverBillOut]:
    """SALARY：对指定司机（或全部薪资司机，含已停用）生成当月月薪单（幂等）；PIECE：该月已送达未生成的补单（幂等）。

    2026-10-15 CHG-0127：`refresh_unsettled=True` 时**顺带重算未核销的月薪单** ——
    派单员改了某人的固定工资之后，那个月还没核销的工资单要按现在的规则重算
    （用户原话：「已经核销了……表示已核销啊，就是重新计算，那个**没有核销的**工资」）。
    已核销（SETTLED）与已被草稿结算单锁住（`settled_doc_id` 非空）的单**一个字段都不碰**；
    缺省 False＝老行为一字不变（幂等＝跳过）。
    """
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="仅派单员可操作")
    from decimal import Decimal

    if body.bill_type == DriverBillType.SALARY:
        # ⚠️ 这里原来按 `lower(User.billing_mode) == "salary"` 在 SQL 里筛人。v3.36 起不能这么筛了：
        #    挂了计费规则的司机可能**既有按单应付、又有固定工资**（例如"工资 6000 + 运费 5%"），
        #    他的 billing_mode 是 PIECE，但月薪单必须照生成。所以改成逐个问 `monthly_salary_of`——
        #    "谁有月薪"只有一处实现，SQL 里再写一遍判据必然和它走散。
        #    （顺带修掉一个老毛病：司机总数是几十个，这里本来就该在 Python 里判。）
        drivers = [d for d in db.scalars(select(User).where(User.role == UserRole.DRIVER.value)) if monthly_salary_of(d) > 0]
        if body.driver_id is not None:
            drivers = [d for d in drivers if d.id == body.driver_id]
        created = []
        # [(单, 改之前的金额)] —— 刷新过的单（`refresh_unsettled=True` 时才可能有）
        refreshed = []
        for d in drivers:
            # ⛔ 并发保护（2026-09-19 审计第十七轮，台账 M6 一直没修）：
            #    月薪单的"先查再插"没有任何兜底 —— 唯一的唯一索引是
            #    `uq_driver_bills_order_type (order_id, bill_type)`，而月薪单的 `order_id` 是 **NULL**，
            #    NULL 在唯一索引里互不相等（SQLite / MySQL 都如此）→ **挡不住第二行**。
            #    两个并发的 `POST /driver-bills/generate {SALARY, 本月}` 会各插一行，
            #    `create_settlement` 把两行一起 sum（¥4500 变 ¥9000），
            #    而 confirm 的"金额与明细合计一致"校验**会通过**（两边都自洽）。
            #    修法：先把司机行锁住（MySQL 上是 `SELECT … FOR UPDATE`，SQLite 忽略），
            #    同一个月薪单的生成因此串行，第二个人进来时 `exists` 已经查得到。
            db.execute(select(User.id).where(User.id == d.id).with_for_update())
            # ⛔ **锁住了行还不够，判据本身也要加锁读**（2026-09-23 第 18 轮并行渗透 A5-2）：
            #    MySQL 的 REPEATABLE READ 下，**普通 SELECT 读的是事务开始那一刻的快照** ——
            #    第一个请求插完提交之后，第二个请求（即使已经拿到行锁）用普通 SELECT 仍然
            #    看不到那一行，于是照样插第二张月薪单（工资付两遍）。
            #    加锁读永远读**最新已提交值**，与 `order_money.money_map(lock=True)` 同一个手法。
            exists = db.scalars(
                select(DriverBill)
                .where(
                    DriverBill.driver_id == d.id,
                    DriverBill.bill_type == DriverBillType.SALARY,
                    DriverBill.month == body.month,
                )
                .with_for_update()
            ).first()
            sal = monthly_salary_of(d)
            if sal <= 0:
                continue
            dr = getattr(d, "driver_rule", None)
            note = (
                "月度工资单（规则：" + (dr.name or "") + "）"
                if dr is not None
                else "月度工资单（自动生成）"
            )
            if exists is not None:
                # ---- 未核销的重新计算（2026-10-15 CHG-0127）----
                # 用户原话：「如果……已经核销了……表示已核销啊，就是重新计算，那个**没有核销的**工资」。
                # 旧行为是一律 `continue`：派单员把某人的固定工资从 6500 改成 7000 之后，
                # 那个月还没核销的工资单**还印着旧数**，核销时照旧数结账（钱少付了，而且没人报错）。
                # ⛔ 只动 `_is_open_unlocked` 为真的单：已核销 / 已被草稿结算单锁住的是**已经对过的账**，
                #    刷新它就是改历史。⛔ 金额没变就一个字都不写（不留空转日志）。
                if body.refresh_unsettled and _is_open_unlocked(exists) and exists.amount != sal:
                    refreshed.append((exists, exists.amount))
                    exists.amount = sal
                    exists.note = note
                    exists.rule_id = dr.id if dr is not None else None
                    exists.rule_name = (dr.name or "") if dr is not None else ""
                continue
            b = DriverBill(
                driver_id=d.id,
                bill_type=DriverBillType.SALARY,
                month=body.month,
                amount=sal,
                status=DriverBillStatus.OPEN,
                note=note,
                rule_id=dr.id if dr is not None else None,
                rule_name=(dr.name or "") if dr is not None else "",
            )
            db.add(b)
            created.append(b)
        # 月薪单＝**造出可支付的应付**（月结时会被结算单收走），必须留痕（2026-09-19 审计）。
        # 一条汇总日志：写明这次生成了多少张、合计多少钱、哪个月。
        # 2026-10-15 CHG-0127：刷新（重算未核销的）也要留痕 —— 它改的是**金额**，
        # 是这一组动作里唯一会动已存在的钱的一步，不能只在界面上说一句。
        if created or refreshed:
            write_log(
                db,
                operator_id=current.id,
                order_id=None,
                action=OperationAction.DRIVER_BILL_GENERATE,
                change_payload={
                    "bill_type": "SALARY",
                    "month": body.month,
                    "driver_id": body.driver_id,
                    "created_count": len(created),
                    "created_total": str(sum((x.amount for x in created), Decimal("0"))),
                    "refreshed_count": len(refreshed),
                    "refreshed_total": str(sum((b.amount for b, _ in refreshed), Decimal("0"))),
                    # 只开一个口子：开关只在上面那道门里读（`_check_driver_salary_ledger` 钉着
                    # 这个字面量全文只能出现一次）—— 这里记的是"这次**真的**刷了几笔"。
                    "refresh_unsettled": bool(refreshed),
                },
            )
        db.commit()
        # 2026-10-15 CHG-0127：把**重算过的**也回给调用方 —— 只说"生成了几张"的话，
        # 界面没法区分"本来就有一张、这次按新工资改了数"和"什么都没发生"（空转报"已重算"）。
        # 顺序：新建的先、刷新的后（刷新的单一定已存在，id 更小，按 id 分不出这两类）。
        return created + [b for b, _ in refreshed]
    else:
        # PIECE 补单：该月送达、有"按单应付"、运费非空的订单
        from app.models.enums import OrderStatus

        # ⚠️ 补单的金额也走 `pay_for_order`（规则 + 订单快照），不再直接抄 freight_fee。
        #    否则"送达时自动生成的账单按规则算 120、手工补单按运费算 500"，
        #    同一张单两条路径两个数——这正是本仓库最怕的那种不一致。
        stmt = (
            select(Order)
            .options(selectinload(Order.order_products))
            .where(Order.status == OrderStatus.DELIVERED)
            .where(Order.freight_fee.isnot(None))
            # 隔离区（软删）的单不生成应付：账单一旦生成就是一条要付钱记录，
            # 而那张单用户已经删掉了（"伪装删除"，行还在库里）。
            .where(Order.deleted_at.is_(None))
            # 与结算页同一处判据（`driver_pay.per_order_pay_filter`）：两张表必须对同一批单
            .where(per_order_pay_filter())
        )
        if body.driver_id is not None:
            stmt = stmt.where(Order.driver_id == body.driver_id)
        orders = list(db.scalars(stmt))
        created = []
        for o in orders:
            # ⚠️ 月份按**业务当地月**比（2026-09-19 审计 R13-D2）：账单落库用的就是
            #    `accounting_service._month_of`（同样按当地月），两边必须同源——
            #    否则当地月初 00:00~08:00 送达的单会被这里跳过，用户点"补单"得到
            #    「已完成」而一张都没生成（AI 那条路会一直重复申请）。
            if o.delivered_at is None or _bill_month(o.delivered_at) != body.month:
                continue
            if not has_per_order_pay(o):
                continue
            exists = db.scalars(
                select(DriverBill).where(
                    DriverBill.order_id == o.id,
                    DriverBill.bill_type == DriverBillType.PIECE,
                )
            ).first()
            if exists is not None:
                continue
            rule = rule_from_snapshot(getattr(o, "driver_rule_snapshot", None))
            pay = pay_for_order(o)
            if pay.total <= 0:
                continue
            b = DriverBill(
                driver_id=o.driver_id or 0,
                bill_type=DriverBillType.PIECE,
                order_id=o.id,
                month=body.month,
                amount=pay.total,
                status=DriverBillStatus.OPEN,
                note=(
                    f"规则「{rule.name}」（补单）：每单 {pay.piece} + 提成 {pay.commission}"
                    if rule is not None
                    else "订单运费（补单）"
                )[:250],
                rule_id=rule.rule_id if rule is not None else None,
                rule_name=rule.name if rule is not None else "",
                piece_amount=pay.piece if rule is not None else None,
                commission_amount=pay.commission if rule is not None else None,
            )
            db.add(b)
            created.append(b)
        # 手工补单同样**造出可支付的应付**，必须留痕（2026-09-19 审计）：一条汇总日志。
        if created:
            write_log(
                db,
                operator_id=current.id,
                order_id=None,
                action=OperationAction.DRIVER_BILL_GENERATE,
                change_payload={
                    "bill_type": "PIECE",
                    "month": body.month,
                    "driver_id": body.driver_id,
                    "created_count": len(created),
                    "created_total": str(sum((x.amount for x in created), Decimal("0"))),
                },
            )
        db.commit()
        return created