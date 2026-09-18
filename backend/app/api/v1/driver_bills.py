"""司机应付明细（按月）——账本 V2：送达自动生成 PIECE 单；月薪单手工/定时生成。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import DriverBill, User
from app.models.enums import DriverBillStatus, DriverBillType, UserRole
from app.schemas.accounting_v2 import DriverBillGenerateBody, DriverBillOut
from app.services.driver_pay import (
    has_per_order_pay,
    monthly_salary_of,
    pay_for_order,
    rule_from_snapshot,
)

router = APIRouter(prefix="/driver-bills", tags=["driver-bills"])


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
) -> list[DriverBillOut]:
    role = user_role_key(current)
    if role != UserRole.DISPATCHER.value and role != UserRole.DRIVER.value:
        raise HTTPException(status_code=403, detail="仅派单员/司机可查看")
    if role == UserRole.DRIVER.value:
        driver_id = current.id
    stmt = select(DriverBill).order_by(DriverBill.month.desc(), DriverBill.id.desc())
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
        from app.models import Order

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
    """SALARY：对指定司机（或全部薪资司机，含已停用）生成当月月薪单（幂等）；PIECE：该月已送达未生成的补单（幂等）。"""
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
        for d in drivers:
            exists = db.scalars(
                select(DriverBill).where(
                    DriverBill.driver_id == d.id,
                    DriverBill.bill_type == DriverBillType.SALARY,
                    DriverBill.month == body.month,
                )
            ).first()
            if exists is not None:
                continue
            sal = monthly_salary_of(d)
            if sal <= 0:
                continue
            dr = getattr(d, "driver_rule", None)
            b = DriverBill(
                driver_id=d.id,
                bill_type=DriverBillType.SALARY,
                month=body.month,
                amount=sal,
                status=DriverBillStatus.OPEN,
                note=("月度工资单（规则：" + (dr.name or "") + "）" if dr is not None else "月度工资单（自动生成）"),
                rule_id=dr.id if dr is not None else None,
                rule_name=(dr.name or "") if dr is not None else "",
            )
            db.add(b)
            created.append(b)
        db.commit()
        return created
    else:
        # PIECE 补单：该月送达、有"按单应付"、运费非空的订单
        from app.models import Order
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
            .where(
                or_(
                    func.upper(Order.driver_billing_mode_snapshot) == "PIECE",
                    Order.driver_billing_mode_snapshot.is_(None),
                )
            )
        )
        if body.driver_id is not None:
            stmt = stmt.where(Order.driver_id == body.driver_id)
        orders = list(db.scalars(stmt))
        created = []
        for o in orders:
            if o.delivered_at is None or o.delivered_at.strftime("%Y-%m") != body.month:
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
        db.commit()
        return created