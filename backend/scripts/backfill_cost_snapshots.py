"""账本 V2 存量回填（一次性）：
1) order_products/ledgers 成本快照 = 当前 products.cost_price（仅 product_id 存在且商品在售）；
2) 散客 customers：按 temp_shipper_name 归并（phone 从 orders.contact_boss_phone → contact_dongjia_phone 尽力提取）；
   registered：按 shipper_id 关联 users 懒建档案。
用法：python -m scripts.backfill_cost_snapshots
"""

from datetime import date

from sqlalchemy import select, func

from app.database import SessionLocal
from app.models import Customer, Ledger, Order, OrderProduct, Product
from app.models.enums import CustomerKind


def backfill_cost_snapshots(db) -> tuple[int, int]:
    """回填商品成本快照（在售商品按当前成本价；已删商品标 0）。"""
    op_done = 0
    lg_done = 0
    products = {p.id: (p.cost_price or 0) for p in db.scalars(select(Product)).all()}
    ops = list(db.scalars(select(OrderProduct)).all())
    for op in ops:
        if op.cost_price_snapshot is None or op.cost_price_snapshot == 0:
            cost = products.get(op.product_id)
            if cost is not None:
                op.cost_price_snapshot = cost
                op_done += 1
    leds = list(db.scalars(select(Ledger).where(Ledger.source != "refund")).all())
    for lg in leds:
        if lg.cost_price_snapshot is None or lg.cost_price_snapshot == 0:
            cost = products.get(lg.product_id)
            if cost is not None:
                lg.cost_price_snapshot = cost
                lg_done += 1
    db.commit()
    return op_done, lg_done


def migrate_customers(db) -> tuple[int, dict]:
    """① registered：按 ledgers.shipper_id（orders.shipper_id 补充）建客户档案；
    ② tmp：按 temp_shipper_name 归并，phone 尽力提取；③ ledgers.customer_id 回填。"""
    created_registered = 0
    created_tmp = 0
    # registered
    shipper_ids = set(
        db.scalars(
            select(Ledger.shipper_id).where(Ledger.shipper_id.isnot(None)).distinct()
        ).all()
    )
    shipper_ids |= set(
        db.scalars(select(Order.shipper_id).where(Order.shipper_id.isnot(None)).distinct()).all()
    )
    user_map: dict[int, Customer] = {}
    for sid in shipper_ids:
        if sid is None:
            continue
        existing = db.scalars(select(Customer).where(Customer.user_id == sid)).first()
        if existing is not None:
            user_map[sid] = existing
            continue
        from app.models import User

        u = db.get(User, sid)
        if u is None:
            continue
        c = Customer(
            kind=CustomerKind.REGISTERED,
            user_id=sid,
            name=(u.full_name or u.phone or f"货主#{sid}"),
            phone=u.phone or None,
            is_member=bool(getattr(u, "is_member", False)),
        )
        db.add(c)
        db.flush()
        user_map[sid] = c
        created_registered += 1
    # tmp：按 temp_shipper_name + 电话提取
    tmp_groups = db.execute(
        select(Ledger.temp_shipper_name, func.count()).where(Ledger.shipper_id.is_(None)).group_by(Ledger.temp_shipper_name)
    ).all()
    tmp_map: dict[str, Customer] = {}
    for (name, _cnt) in tmp_groups:
        nm = (name or "").strip()
        if not nm:
            continue
        existing = db.scalars(select(Customer).where(Customer.kind == CustomerKind.TMP, Customer.name == nm)).first()
        if existing is not None:
            tmp_map[nm] = existing
            continue
        # 同一电话视为同一散客（唯一键=电话）：先查同名，再查同电话
        phone = None
        for row in db.execute(
            select(Order.temp_shipper_name, Order.contact_boss_phone, Order.contact_dongjia_phone)
            .where(Order.temp_shipper_name == nm)
            .order_by(Order.id.desc())
            .limit(5)
        ):
            p = (row[1] if row[1] else row[2] if row[2] else "") or ""
            if p.strip():
                phone = p.strip()
                break
        if phone:
            by_phone = db.scalars(select(Customer).where(Customer.kind == CustomerKind.TMP, Customer.phone == phone)).first()
            if by_phone is not None:
                tmp_map[nm] = by_phone
                continue
        c = Customer(kind=CustomerKind.TMP, name=nm, phone=phone)
        db.add(c)
        db.flush()
        tmp_map[nm] = c
        created_tmp += 1
    # ledgers.customer_id 回填
    for lg in db.scalars(select(Ledger).where(Ledger.customer_id.is_(None))).all():
        if lg.shipper_id is not None and lg.shipper_id in user_map:
            lg.customer_id = user_map[lg.shipper_id].id
        elif (lg.temp_shipper_name or "").strip() in tmp_map:
            lg.customer_id = tmp_map[(lg.temp_shipper_name or "").strip()].id
    db.commit()
    return created_registered, {"tmp": created_tmp}


if __name__ == "__main__":
    db = SessionLocal()
    try:
        a, b = backfill_cost_snapshots(db)
        print(f"成本快照回填：order_products={a} 行，ledgers={b} 行")
        r, t = migrate_customers(db)
        print(f"客户档案迁移：registered={r}，tmp={t}")
    finally:
        db.close()