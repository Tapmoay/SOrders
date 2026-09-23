from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ledger, Order, User
from app.schemas.ledger import LedgerOut


def _shipper_name(row: Ledger, user: User | None) -> str | None:
    """这一笔账挂在**谁**名下（注册货主 → 人名；临时货主 → 那句称呼）。

    ⚠️ 为什么要后端算、而不是让客户端拿 `shipper_id` 自己查（2026-09-19 补）：
    1. **AI 看不到任何内部编号**（本项目第一条硬规矩）—— 只给 `shipper_id` 的话，
       模型能读这张表却**说不出这一笔是谁的**，等于半个瞎子；
    2. 客户端拿 id 去查还要为每一行发一次请求（本项目在 `ledger_rows_to_out` 上
       刚修过一次"逐行 `db.get()` → 85,474 条 SQL"的同类问题）。
    批量版在下面**一次 `IN`** 把所有人取回来，SQL 条数仍是常数。

    空名字的处理与后端其它地方一致（`users.py` 那套）：**人名 → 手机号 → `货主#编号`**。
    宁可给个编号，也不要给一个"临时货主"——那会把**注册货主的账说成临时货主的**。
    """
    if row.shipper_id is not None:
        if user is None:
            return f"货主#{row.shipper_id}"
        return user.full_name or user.phone or f"货主#{row.shipper_id}"
    name = (row.temp_shipper_name or "").strip()
    return name or None


def order_shipper_label(db: Session, order: Order) -> str:
    """**这一单的货主叫什么**（钱的行上那个"对象"字段用它，2026-09-23 第 15 轮补）。

    ### 与 `_shipper_name` **同一条规矩**，只是输入是订单而不是账本行
    注册货主（`order.shipper_id` 有值）→ **人名/手机号/`货主#编号`**；
    临时货主（无账号）→ 下单时那句称呼；两者都没有 → `临时货主`。

    ### 为什么必须有它（真机 E2E 抓到的）
    退款那一行的对象名原来写的是
    `cust.name if cust else ((order.temp_shipper_name or "").strip() or "临时货主")` ——
    而 `cust`（客户档案行）**不是每个注册货主都有**（生产 34 个货主账号里 32 个有）。
    于是「注册货主 + 没有客户档案」这一类单**退现时对象名会写成「临时货主」**：
    资金收支里那一笔看着像是给了一个没账号的临时客户的退款，而同一张单在账本/订单页上
    写着「永盛食品」——**同一笔钱两个名字**，与本文件 `_shipper_name` 那条注释里
    「宁可给个编号，也不要把注册货主的账说成临时货主的」是同一件事。
    """
    if order.shipper_id is not None:
        user = db.get(User, order.shipper_id)
        if user is None:
            return f"货主#{order.shipper_id}"
        return user.full_name or user.phone or f"货主#{order.shipper_id}"
    name = (order.temp_shipper_name or "").strip()
    return name or "临时货主"


def _to_out(row: Ledger, order: Order | None, user: User | None = None) -> LedgerOut:
    """把一行账本 + 它关联的订单（可能没有）拼成出参。**唯一**拼装处。"""
    order_no: str | None = None
    order_delivery_description: str | None = None
    if order is not None:
        order_no = order.order_no
        d = (order.delivery_description or "").strip()
        order_delivery_description = d or None
    return LedgerOut(
        id=row.id,
        shipper_id=row.shipper_id,
        temp_shipper_name=row.temp_shipper_name,
        shipper_name=_shipper_name(row, user),
        entry_date=row.entry_date,
        product_name=row.product_name,
        quantity=row.quantity,
        unit_price=row.unit_price,
        total=row.total,
        order_id=row.order_id,
        order_product_id=row.order_product_id,
        product_id=row.product_id,
        order_no=order_no,
        order_delivery_description=order_delivery_description,
        source=row.source,
        note=row.note,
        created_at=row.created_at,
    )


def ledger_to_out(row: Ledger, db: Session) -> LedgerOut:
    """单行版（`GET/PATCH/DELETE /ledger/entries/{id}` 这类只处理一行的端点用）。"""
    user = db.get(User, row.shipper_id) if row.shipper_id is not None else None
    return _to_out(row, db.get(Order, row.order_id) if row.order_id else None, user)


def ledger_rows_to_out(rows: list[Ledger], db: Session) -> list[LedgerOut]:
    """**列表版**：一次 `IN` 查询把所有关联订单取回来。

    ⚠️ 为什么不能用逐行 `ledger_to_out`（2026-09-19 外部完整检查 C-4 / PERF-02 / R2B-2）：
    原来列表端点就是 `[ledger_to_out(r, db) for r in rows]`，而 `db.get()` **每次都真发一条 SQL**
    —— Session 的身份映射对已加载对象持**弱引用**，行对象被回收后缓存就没了，"靠 identity map
    兜着"这个假设不成立（实测同一个 id 连取 10 次 = 10 条 SQL）。
    于是 `GET /ledger/entries` 的 SQL 条数 ≈ 行数：实测 85,474 行 → **85,476 条 SQL / 27.75 秒**。
    批量化之后 SQL 条数变成**常数 3**（1 条取流水 + 1 条取订单 + 1 条取货主），与行数无关。
    """
    order_ids = {int(r.order_id) for r in rows if r.order_id}
    orders: dict[int, Order] = {}
    if order_ids:
        for o in db.scalars(select(Order).where(Order.id.in_(order_ids))).all():
            orders[int(o.id)] = o
    # 货主名字同理**一次 IN 取回来**（见 `_shipper_name` 的说明）：逐行 `db.get(User, …)`
    # 会把"常数 2 条 SQL"重新变成"每行一条"——那正是上面那段注释里刚修掉的那个坑。
    shipper_ids = {int(r.shipper_id) for r in rows if r.shipper_id is not None}
    users: dict[int, User] = {}
    if shipper_ids:
        for u in db.scalars(select(User).where(User.id.in_(shipper_ids))).all():
            users[int(u.id)] = u
    return [
        _to_out(
            r,
            orders.get(int(r.order_id)) if r.order_id else None,
            users.get(int(r.shipper_id)) if r.shipper_id is not None else None,
        )
        for r in rows
    ]

