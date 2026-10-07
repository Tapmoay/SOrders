"""批发商给下游客户定的价（台账 L-38 / CHG-0077）。

## 这是第几层价（三层价，只加第三层）

| 层 | 谁定 | 存在哪 | 算进哪本账 |
| --- | --- | --- | --- |
| ① 商品目录价 | 派单员 | `products.unit_price` | 公司那本账（他进货按它） |
| ② 给他的专属价 | 派单员 | `price_rules.special_unit_price` | 公司那本账（他进货实付） |
| ③ **他给下游的价** | **批发商自己（本模块）** | `shipper_prices.unit_price` | **他自己那本下游账** |

③ 与 ①② **互不写**：订单行金额（`order_products.line_total`）与公司那本账一个字节都不动，
下游账只按 `order_products.shipper_unit_price`（下单当时的快照）算，差额归他 ——
钱只在 [app.services.order_money.line_downstream_receivable] 一处算（口径 m13365）。

## 三条设计约束

1. **「不同的人」= 他的联系人名册**（`shipper_contacts.id`）：`contact_id IS NULL` 那一档是该商品的
   **默认价**（对没单独定价的人全部生效），有值则只对那一个人生效、并覆盖默认价。
   ⛔ 不用订单上的收货人「姓名|电话」当主数据：那个东西不是实体（同名的会并成一个人）。
2. **老单永不追改**：价只在下单那一刻定格到 `order_products.shipper_unit_price`
   （[snapshot_order_lines]，而且**只填 NULL**）；改价、删联系人、删商品都不动任何历史订单。
3. ⛔ **唯一约束拦不住「默认价」那一档**：`uq_shipper_price_scope(shipper_id, contact_id, product_id)`
   在 SQLite / MySQL 里对 `contact_id IS NULL` 的行**不生效**（NULL 互不相等），所以默认价必须在
   服务层查重/归一 —— [find_row] 查已有行时**不过滤 is_deleted**（照 `api/v1/price_rules.py` 的口径：
   删掉的行仍占着那个组合，再设一次要**复活那一行**，不能插一条新的）。
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Order, OrderProduct, PriceRule, ShipperContact, ShipperPrice


def customer_identity(order: Order) -> tuple[str, str]:
    """这一单「归谁」：收货人（姓名, 电话）→ 下单人 → 空。

    ⛔ **与下面两处逐字同一套回退**（账本按这个身份分人、核销按这个身份记人，价必须挂在同一个人身上，
    否则「给他定的价」会算到另一个人头上，而两边都不报错）：

    - `api/v1/shipper_ledger.py::_customer_name_expr / _customer_phone_expr`（按人筛与合计）
    - `android/.../ui/shipper/ShipperLedgerGrouping.kt::customerNameOf / customerPhoneOf`（页面分组）
    """
    name = (order.contact_dongjia_name or "").strip() or (order.contact_boss_name or "").strip()
    phone = (order.contact_dongjia_phone or "").strip() or (order.contact_boss_phone or "").strip()
    return name, phone


def allowed_product_ids(db: Session, shipper_id: int) -> set[int]:
    """他能定价的商品：**他下过单的商品** ∪ **派单员给他设过专属价的商品**。

    口径①（m13365）是「只能定**他自己名下**的商品」，⛔ 不是平台上所有商品 ——
    这两类才是「他名下的」：前一类他真卖过，后一类别人已经按专属价给他供过货。
    """
    mine = set(
        db.scalars(
            select(OrderProduct.product_id)
            .join(Order, Order.id == OrderProduct.order_id)
            .where(Order.shipper_id == shipper_id, OrderProduct.product_id.is_not(None))
        ).all()
    )
    granted = set(
        db.scalars(
            select(PriceRule.product_id).where(
                PriceRule.shipper_id == shipper_id, PriceRule.is_deleted.is_(False)
            )
        ).all()
    )
    return {int(pid) for pid in (mine | granted) if pid is not None}


def find_row(
    db: Session, *, shipper_id: int, contact_id: int | None, product_id: int
) -> ShipperPrice | None:
    """定位「这个批发商 × 这个人 × 这个商品」那一行；⛔ **不要按 is_deleted 过滤**。

    唯一键 `uq_shipper_price_scope` 是硬的（SQLite/MySQL 都建了真约束，只有 contact_id 为 NULL 时例外）：
    软删过的行**仍然占着那个组合**，所以「再设一次」必须复活它，插新的会直接撞唯一键。
    """
    stmt = select(ShipperPrice).where(
        ShipperPrice.shipper_id == shipper_id,
        ShipperPrice.product_id == product_id,
    )
    if contact_id is None:
        stmt = stmt.where(ShipperPrice.contact_id.is_(None))
    else:
        stmt = stmt.where(ShipperPrice.contact_id == int(contact_id))
    return db.scalars(stmt.order_by(ShipperPrice.id)).first()


def price_of(
    db: Session, *, shipper_id: int, contact_id: int | None, product_id: int
) -> Decimal | None:
    """他给**这个人**在这个商品上定的单价：联系人专属价 → 默认价 → None（从没定过价）。

    ⛔ 只认没软删的行；⛔ 这里算的是**此刻的价**，只用于「下单时定格」与界面上的参考价 ——
    历史账单一律读取订单行上的快照（[order_money.line_downstream_receivable]），改价不许改历史。
    """
    stmt = select(ShipperPrice).where(
        ShipperPrice.shipper_id == shipper_id,
        ShipperPrice.product_id == product_id,
        ShipperPrice.is_deleted.is_(False),
    )
    if contact_id is not None:
        own = db.scalars(stmt.where(ShipperPrice.contact_id == int(contact_id))).first()
        if own is not None:
            return own.unit_price
    default = db.scalars(stmt.where(ShipperPrice.contact_id.is_(None))).first()
    return default.unit_price if default is not None else None


def match_contact(
    db: Session,
    *,
    shipper_id: int,
    picked_contact_id: int | None = None,
    name: str = "",
    phone: str = "",
) -> int | None:
    """这一单是给名册里的哪一条（口径②：只认 `shipper_contacts`）。

    顺序：① 下单时从联系人库里点的那一条（`body.contact_id`，要验它属于他自己且没进回收站）
    → ② 电话精确命中（`uq_shipper_contact_phone` 保证同一个货主下号码唯一）
    → ③ 姓名命中，而且**必须唯一命中**（多命中就不认：同名的两个客户并成一个的后果是
    「他的欠款翻倍、另一个人的欠款不见了」，两边都不报错）→ ④ 都没认出来 = None（只有默认价）。
    """
    if picked_contact_id:
        row = db.get(ShipperContact, int(picked_contact_id))
        if row is not None and row.shipper_id == shipper_id and not row.is_deleted:
            return int(row.id)
    phone = (phone or "").strip()
    if phone:
        row = db.scalars(
            select(ShipperContact).where(
                ShipperContact.shipper_id == shipper_id,
                ShipperContact.phone == phone,
                ShipperContact.is_deleted.is_(False),
            )
        ).first()
        if row is not None:
            return int(row.id)
    name = (name or "").strip()
    if name:
        rows = db.scalars(
            select(ShipperContact).where(
                ShipperContact.shipper_id == shipper_id,
                ShipperContact.display_name == name,
                ShipperContact.is_deleted.is_(False),
            )
        ).all()
        if len(rows) == 1:
            return int(rows[0].id)
    return None


def snapshot_order_lines(
    db: Session, order: Order, *, picked_contact_id: int | None = None
) -> int:
    """把「他给这个人定的价」定格到这一单的每一行，返回定格了几行（0 = 没定过价，一切照旧）。

    ⛔ **只填 NULL**：已经带快照的行、以及老单（改数量 / 转单 / 拆单 / 派单员加行都不经过这里）
    永不被追改 —— 与「订单行金额不可回改」是同一条纪律（口径⑤ m13365）。
    ⛔ 没定过价的行**不写 0**：留 NULL ⇒ 下游账逐字退回订单口径（[line_downstream_receivable]），
    钱一分不少也一分不多。
    """
    shipper_id = getattr(order, "shipper_id", None)
    if shipper_id is None:
        return 0
    lines = list(order.order_products or [])
    if not lines:
        return 0
    name, phone = customer_identity(order)
    contact_id = match_contact(
        db,
        shipper_id=int(shipper_id),
        picked_contact_id=picked_contact_id,
        name=name,
        phone=phone,
    )
    cache: dict[int, Decimal | None] = {}
    filled = 0
    for op in lines:
        pid = op.product_id
        if pid is None or op.shipper_unit_price is not None:
            continue
        if int(pid) not in cache:
            cache[int(pid)] = price_of(
                db, shipper_id=int(shipper_id), contact_id=contact_id, product_id=int(pid)
            )
        price = cache[int(pid)]
        if price is None:
            continue
        op.shipper_unit_price = price
        filled += 1
    return filled
