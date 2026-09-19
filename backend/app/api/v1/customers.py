"""客户档案（注册用户/散客）——账本 V2：收款、欠款、挂账均需客户档案。"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.rbac import user_role_key
from app.database import get_db
from app.deps import CurrentUser
from app.models import Customer, Order, User
from app.models.enums import CustomerKind, OperationAction, UserRole
from app.schemas.accounting_v2 import CustomerCreate, CustomerMergeBody, CustomerOut
from app.services.operation_log_service import write_log

router = APIRouter(prefix="/customers", tags=["customers"])


def _require_dispatcher(current: User) -> None:
    if user_role_key(current) != UserRole.DISPATCHER.value:
        raise HTTPException(status_code=403, detail="无权操作")


@router.get("", response_model=list[CustomerOut])
def list_customers(
    current: CurrentUser,
    db: Session = Depends(get_db),
    kind: str | None = Query(None, pattern="^(registered|tmp)$"),
    q: str | None = Query(None, description="名称/电话模糊"),
) -> list[CustomerOut]:
    _require_dispatcher(current)
    stmt = select(Customer).order_by(Customer.id.desc())
    if kind:
        stmt = stmt.where(Customer.kind == kind)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(Customer.name.like(like) | Customer.phone.like(like))
    return list(db.scalars(stmt).all())


@router.post("", response_model=CustomerOut)
def create_customer(
    body: CustomerCreate,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> CustomerOut:
    _require_dispatcher(current)
    if body.kind == "tmp" and body.phone and body.phone.strip():
        dup = db.scalars(
            select(Customer).where(
                Customer.kind == CustomerKind.TMP,
                Customer.phone == body.phone.strip(),
            )
        ).first()
        if dup is not None:
            return dup  # 电话一致视为同一散客，复用档案
    if body.user_id is not None:
        dup = db.scalars(select(Customer).where(Customer.user_id == body.user_id)).first()
        if dup is not None:
            return dup
    c = Customer(
        kind=body.kind,
        user_id=body.user_id,
        name=body.name.strip(),
        phone=(body.phone or "").strip() or None,
        is_member=body.is_member,
        arrears_unit_id=body.arrears_unit_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.post("/merge", response_model=CustomerOut)
def merge_customers(
    body: CustomerMergeBody,
    current: CurrentUser,
    db: Session = Depends(get_db),
) -> CustomerOut:
    _require_dispatcher(current)
    keep = db.get(Customer, body.keep_id)
    if keep is None:
        raise HTTPException(status_code=404, detail="保留客户不存在")
    # ⛔ ①「保留的那个」不能同时出现在待合并列表里（2026-09-19 审计）。
    #    原来没有这道校验：`{"keep_id":5,"merge_ids":[5,6]}` 会把 5 自己也 `db.delete` 掉，
    #    而 `db.commit()` 先把删除提交了、下一行 `db.refresh(keep)` 才抛
    #    `InvalidRequestError: Instance ... is not persistent` → 接口 500，**两个客户档案都已经真没了**
    #    （用户看到的是"合并失败"，库里是"两个客户都没了、账本还指着已删的 id"）。不可逆。
    merge_ids = sorted({int(x) for x in body.merge_ids if int(x) != keep.id})
    if len(merge_ids) != len(set(body.merge_ids)):
        raise HTTPException(
            status_code=400,
            detail="待合并列表里包含了要保留的那个客户 —— 合并会把它自己也删掉。请把保留的客户从待合并列表里去掉。",
        )
    # ⛔ ③ 两个**不同账号**（user_id 不同）的注册客户**不许合并**（2026-09-19 审计 R14-3）。
    #    合并做的是"把引用搬到 keep 上，然后把被并档案**物理删除**"（customers 表连 is_deleted 都没有，
    #    不可逆）。而决定订单归属的是 `orders.shipper_id = customer.user_id`，这一列**没有搬**：
    #    合并之后被并客户的订单在「客户收款」页里列不出来（App 按 `shipper_id` 查），
    #    直接打接口核销也会被 `accounting_service` 的"订单不属于该客户"拦下 ——
    #    那批历史应收**永久失去正规核销入口**（本机注册货主侧已送达未收 356 张 / ¥147,935）。
    #    系统自己的身份规则就是"注册客户按 user_id 唯一"，两个不同 user_id 本来就代表两个账号：
    #    要合并请先在账号层面处理。这条闸门比"搬一半引用"安全得多。
    if keep.user_id is not None:
        clashing = []
        for mid in merge_ids:
            m0 = db.get(Customer, mid)
            if m0 is not None and m0.user_id is not None and m0.user_id != keep.user_id:
                clashing.append(f"{m0.name}(账号 {m0.user_id})")
        if clashing:
            raise HTTPException(
                status_code=400,
                detail=(
                    "这两个客户各自绑着不同的登录账号，不能合并："
                    + "、".join(clashing)
                    + "。合并会把被并的档案**彻底删掉**（不可恢复），而订单归属是绑在账号上的，"
                    "合并后那批订单将无法再通过收款单核销。要合并请先在账号层面处理。"
                ),
            )
    moved_receipts = 0
    moved_ledgers = 0
    renamed_orders = 0
    for mid in merge_ids:
        m = db.get(Customer, mid)
        if m is None:
            continue
        from app.models import Ledger, ShipperReceipt

        ledgers = list(db.scalars(select(Ledger).where(Ledger.customer_id == mid)))
        for lg in ledgers:
            lg.customer_id = keep.id
        moved_ledgers += len(ledgers)
        # ② 收款单也要跟着搬（2026-09-19 审计）。`shipper_receipts.customer_id` 是**裸 Integer 无外键**，
        #    原来不搬 → 合并之后那些收款记录指向一个不存在的客户：收款单列表里客户名变成空、
        #    按客户筛钱筛不到，而"钱"是这套系统里最不能对不上的东西。
        receipts = list(db.scalars(select(ShipperReceipt).where(ShipperReceipt.customer_id == mid)))
        for r in receipts:
            r.customer_id = keep.id
        moved_receipts += len(receipts)
        # ③ 临时货主（无账号）的账本行按**名字**归集（`list_accounts` 就是这么聚合的），
        #    合并时名字不改 → 用户做合并的主要目的（把两笔账并到一起）根本不会发生。
        old_name = (m.name or "").strip()
        new_name = (keep.name or "").strip()
        if old_name and new_name and old_name != new_name:
            others = list(db.scalars(
                select(Ledger).where(Ledger.temp_shipper_name == old_name, Ledger.shipper_id.is_(None))
            ))
            for lg in others:
                lg.temp_shipper_name = new_name
            # ④ ⛔ `orders.temp_shipper_name` 也必须一起改（2026-09-19 审计 R14-4）。
            #    临时货主的名字在这个系统里存**两份**：`orders.temp_shipper_name`（下单时定的）
            #    与 `ledgers.temp_shipper_name`（送达自动记账时从订单抄过来的）。
            #    只改账本那一份的后果是**改名会在下一次同步时被悄悄还原**：
            #    `ledger_sync.sync_ledger_from_delivered_order` 会拿**订单上的旧名字**
            #    覆盖同名账本行（`existing.temp_shipper_name = temp_shipper_name`），
            #    于是"合并过的两笔账"又裂回两行，而全程没有任何提示。
            #    两份名字同改之后，再同步写进去的就是新名字（幂等）。
            moved_orders = list(db.scalars(
                select(Order).where(
                    Order.shipper_id.is_(None),
                    Order.temp_shipper_name == old_name,
                )
            ))
            for o in moved_orders:
                o.temp_shipper_name = new_name
            renamed_orders += len(moved_orders)
        db.delete(m)
    # 合并会**改写归属**（账本/收款单都换到保留的客户名下）并删掉档案，必须留痕（2026-09-19 审计）：
    # `docs/ACCOUNTING_V2_DESIGN.md` §4.10 明确要求"客户合并操作也留痕"。
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.CUSTOMER_MERGE,
        change_payload={
            "keep_id": keep.id,
            "merged_ids": merge_ids,
            "moved_ledgers": moved_ledgers,
            "moved_receipts": moved_receipts,
            # 临时货主改名影响到的**订单行数**也要留痕：不然"合并之后报表里那个名字还是旧名"
            # 这件事在审计页上查不出来（2026-09-19 审计 R14-4）
            "renamed_orders": renamed_orders,
        },
    )
    db.commit()
    db.refresh(keep)
    return keep
