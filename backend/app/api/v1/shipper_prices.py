"""批发商**给自己名下的商品定价** —— 第三层价（CHG-0077 / 台账 L-38，用户原话 ref m01547）。

## 这一层价是什么、不是什么（逐层对照见 `models/shipper_price.py` 开头那张表）

| 层 | 谁定的 | 存在哪 | 算进哪本账 |
| --- | --- | --- | --- |
| ① 商品目录价 | 派单员 | `products.default_unit_price` | 公司那本账 |
| ② 给他的专属价 | 派单员 | `price_rules.special_unit_price` | 公司那本账（他进货实付） |
| ③ **他给下游的价** | **批发商自己（本文件）** | **`shipper_prices`** | **他自己那本下游账** |

⛔ 本文件**只碰第三层**：一个字节都不动 `products` / `price_rules`、不动订单行金额
（`order_products.unit_price` / `line_total`）、不动公司那本账（`ledger` / `cash_flows`）——
两层价之间的差额归他，公司侧照旧（口径 m13365）。
⛔ 历史订单永不追改：这一层价只在**下单建行时**定格到 `order_products.shipper_unit_price`
（`services/shipper_price.py::snapshot_order_lines`，而且**只填 NULL**），改价 / 删价都不动任何老单。

## 五个端点

| 端点 | 作用 |
| --- | --- |
| `GET /shipper-prices/products` | 可定价商品（他下过单的 ∪ 派单员给他设过专属价的）＋ 他拿货的价 ＋ 他已定的默认价 |
| `GET /shipper-prices` | 价目表（**他自己那几行**；`include_deleted=true` 看回收站） |
| `POST /shipper-prices` | 设一条价：商品 ＋（可选）联系人 ＋ 单价；已有则覆盖，软删过的**复活** |
| `DELETE /shipper-prices/{price_id}` | 删一条价（**软删**，用户：「我们的操作都是走软删除」） |
| `POST /shipper-prices/{price_id}/restore` | 把删掉的价放回来 |

## 三道闸，缺一道就有洞

1. 权限点 `shipper_price:manage`（`core/rbac.py` 只给了 shipper 角色）—— 「你是谁」；
2. `_require_member`（[app.api.v1.shipper_ledger] :77）—— 「是不是批发商货主」（普通货主没有下游这本账）；
3. `_require_downstream`（同上 :104）—— 「有没有把下游这本账关掉」（CHG-0076 / 台账 L-39）。

⚠️ 第 2、3 道**从 `shipper_ledger` import 过来，⛔ 不在这里复制一份**：复制就是第二份真相，
而这两道闸的口径与理由（关掉之后连入口一起收、文案要说清出路）都写在那边。
⚠️ 逐行的行级过滤写在**每一条查询**里（`ShipperPrice.shipper_id == current.id`）：这个权限点是
scope=own，任何一条漏掉它就是"他能改别人的价目表"。
⛔ **派单员不代设**：本文件没有 `shipper_id` 入参，写的永远是 `current.id`（谁调就写谁的）；
不是批发商货主的账号由 `_require_member` 拦下 —— 结构上就代设不了。
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.v1.shipper_ledger import _require_downstream, _require_member
from app.core.business_time import utc_now_naive
from app.core.rbac import Permission
from app.database import get_db
from app.deps import require_permission
from app.models import PriceRule, Product, ShipperContact, ShipperPrice, User
from app.models.enums import OperationAction
from app.schemas.shipper_price import (
    ShipperPriceOut,
    ShipperPriceProductOut,
    ShipperPriceSet,
)
from app.services import shipper_price
from app.services.operation_log_service import write_log
from app.services.soft_delete import ensure_alive

router = APIRouter(prefix="/shipper-prices", tags=["shipper-prices"])


def _to_out(db: Session, row: ShipperPrice) -> ShipperPriceOut:
    """出参补上名字：编号在界面上没有意义（与操作日志同一条口径）。"""
    product = db.get(Product, row.product_id)
    contact = db.get(ShipperContact, row.contact_id) if row.contact_id else None
    return ShipperPriceOut(
        id=row.id,
        product_id=row.product_id,
        contact_id=row.contact_id,
        unit_price=row.unit_price,
        product_name=product.name if product is not None else None,
        contact_name=contact.display_name if contact is not None else None,
        is_deleted=bool(row.is_deleted),
    )


def _special_prices(db: Session, shipper_id: int, product_ids: list[int]) -> dict[int, Decimal]:
    """派单员**给他设过**的专属价（第二层价），按商品编号索引。

    ⛔ 只作参考、不参与任何计算（钱只有一套算法）。回退口径与下单页逐字一致 ——
    `models/product.py:39`：「下单页读 `price_rules` 的按（批发商×商品）专属价，
    没有专属价才用 `default_unit_price`」；所以这里的缺口由调用方拿商品目录价补。
    """
    if not product_ids:
        return {}
    rows = db.scalars(
        select(PriceRule).where(
            PriceRule.shipper_id == shipper_id,
            PriceRule.product_id.in_(product_ids),
            PriceRule.is_deleted.is_(False),
        )
    ).all()
    return {int(r.product_id): r.special_unit_price for r in rows}


# ⚠️ 静态路径 `/products` 必须写在动态路径 `/{price_id}` **之前** ——
#    否则它会被 `/{price_id}` 挡住（`_tools/qa/_api_contract_snapshot.py` 的遮蔽分析会当场判红）。
@router.get("/products", response_model=list[ShipperPriceProductOut])
def list_priceable_products(
    current: User = Depends(require_permission(Permission.SHIPPER_PRICE_MANAGE)),
    db: Session = Depends(get_db),
) -> list[ShipperPriceProductOut]:
    """他能定价的商品：**他下过单的** ∪ **派单员给他设过专属价的**（`allowed_product_ids`）。

    ⛔ 不是平台上的全部商品（口径 m13365 第①问「只能定他自己名下的商品」）——
    少了这一层过滤，他能给任意商品定价，而那些价**对谁都不生效**（他没卖过、下游也拿不到）。
    回收站里的商品不出现（`is_deleted` 过滤）：与写入口那道校验同一条口径。
    """
    _require_member(current)
    _require_downstream(current)
    ids = shipper_price.allowed_product_ids(db, current.id)
    if not ids:
        return []
    products = list(
        db.scalars(
            select(Product)
            .where(Product.id.in_(ids), Product.is_deleted.is_(False))
            .order_by(Product.name)
        ).all()
    )
    if not products:
        return []
    pids = [p.id for p in products]
    mine = db.scalars(
        select(ShipperPrice).where(
            ShipperPrice.shipper_id == current.id,
            ShipperPrice.product_id.in_(pids),
            ShipperPrice.is_deleted.is_(False),
        )
    ).all()
    default_of: dict[int, Decimal] = {}
    contact_count: dict[int, int] = {}
    for row in mine:
        if row.contact_id is None:
            default_of[row.product_id] = row.unit_price
        else:
            contact_count[row.product_id] = contact_count.get(row.product_id, 0) + 1
    special = _special_prices(db, current.id, pids)
    return [
        ShipperPriceProductOut(
            product_id=p.id,
            product_name=p.name,
            unit=p.unit or "件",
            supply_unit_price=special.get(p.id, p.default_unit_price),
            default_unit_price=default_of.get(p.id),
            contact_price_count=contact_count.get(p.id, 0),
        )
        for p in products
    ]


@router.get("", response_model=list[ShipperPriceOut])
def list_shipper_prices(
    current: User = Depends(require_permission(Permission.SHIPPER_PRICE_MANAGE)),
    db: Session = Depends(get_db),
    product_id: int | None = Query(None, ge=1, description="只看某个商品（点进去看「给不同的人不同的价」）"),
    contact_id: int | None = Query(None, ge=1, description="只看某个人"),
    include_deleted: bool = Query(False, description="true = 连回收站里的一起看（用在恢复那一步）"),
) -> list[ShipperPriceOut]:
    """他自己那本价目表。

    ⚠️ **行级过滤只有一处**：`ShipperPrice.shipper_id == current.id`。少了它（或写成从参数取）
    就是"谁的价都能看 / 都能改"——这个权限点是 scope=own，那一层过滤**不在**依赖里，在本函数里。
    ⛔ 不接常用度排序（`usage_service.with_popularity`）：那一套管的是"选一条"（选品页、名册页），
    这里是**价目表**，按商品分组、组内先创建的在前，更好核对（同一个商品的行挨着）。
    """
    _require_member(current)
    _require_downstream(current)
    stmt = select(ShipperPrice).where(ShipperPrice.shipper_id == current.id)
    if not include_deleted:
        stmt = stmt.where(ShipperPrice.is_deleted.is_(False))
    if product_id is not None:
        stmt = stmt.where(ShipperPrice.product_id == product_id)
    if contact_id is not None:
        stmt = stmt.where(ShipperPrice.contact_id == contact_id)
    rows = list(db.scalars(stmt.order_by(ShipperPrice.product_id, ShipperPrice.id)).all())
    return [_to_out(db, r) for r in rows]


@router.post("", response_model=ShipperPriceOut, status_code=status.HTTP_201_CREATED)
def set_shipper_price(
    body: ShipperPriceSet,
    current: User = Depends(require_permission(Permission.SHIPPER_PRICE_MANAGE)),
    db: Session = Depends(get_db),
) -> ShipperPriceOut:
    """设 / 改一条下游价（`contact_id` 留空 = 这个商品的**默认价**）。

    ## 三道前置校验：宁可当场拒绝，也不写一条"对谁都不生效"的价
    ① 商品真的在、不在回收站 —— 与 `price_rules.py` 的 K5-② 同一条（回收站里的商品在选品页
       对谁都不显示、下单也选不到，给它写的价**从写进去那一刻就不生效**，而返回与日志都写着"设好了"）；
    ② 商品**在他可定价的范围里**（他下过单的 ∪ 派单员给他设过专属价的）；
    ③ 联系人**是他自己的**、不在回收站（`ensure_alive` 那句 400 会告诉他先去恢复）。
    单价 > 0 与可存范围由 `ShipperPriceSet`（`gt=0` ＋ `MoneyInput` 的上限）挡在 422。
    校验失败时**一行都不写**（不产生半成品价目）。

    ## 一个组合只有一行：软删过的**复活**，⛔ 不插新行
    唯一键 `uq_shipper_price_scope(shipper_id, contact_id, product_id)` 是硬的，插新行会直接撞约束 ——
    与 `price_rules.py::create_price_rule` 的复活分支同一条口径。
    ⚠️ `contact_id IS NULL`（默认价）那一档唯一键**管不住**（SQLite / MySQL 里 NULL 互不相等），
    所以默认价的查重全靠 `services/shipper_price.py::find_row` —— 它**故意不过滤 `is_deleted`**，
    正是为了命中软删那一行并复活它，而不是插一条新的。
    """
    _require_member(current)
    _require_downstream(current)
    product = db.get(Product, body.product_id)
    if product is None or product.is_deleted:
        raise HTTPException(
            status_code=400,
            detail="这个商品不存在或在回收站里，先确认商品再定价（否则这条价对谁都不生效）",
        )
    if body.product_id not in shipper_price.allowed_product_ids(db, current.id):
        raise HTTPException(
            status_code=400,
            detail=(
                "这个商品不在你可定价的范围里：只能给自己下过单的、或派单员给你设过专属价的商品定价"
                "（可定价商品见 GET /shipper-prices/products）"
            ),
        )
    contact: ShipperContact | None = None
    if body.contact_id is not None:
        contact = db.get(ShipperContact, body.contact_id)
        if contact is None or contact.shipper_id != current.id:
            raise HTTPException(
                status_code=400,
                detail="这个联系人不属于你 —— 只能给自己联系人名册里的人定价（⛔ 不是别人的客户）",
            )
        ensure_alive(contact, "联系人", "先到「联系人」里把它从回收站恢复，再给他定价")
    row = shipper_price.find_row(
        db, shipper_id=current.id, contact_id=body.contact_id, product_id=body.product_id
    )
    created = row is None
    revived = bool(row is not None and row.is_deleted)
    before = None if row is None else row.unit_price
    if row is None:
        row = ShipperPrice(
            shipper_id=current.id,
            contact_id=body.contact_id,
            product_id=body.product_id,
            unit_price=body.unit_price,
        )
        db.add(row)
    else:
        # ⚠️ 命中**软删**那一行时必须连 `is_deleted` 一起放回 False（2026-09-19 价格规则批量调价
        #    K4 那次修的是同一个病）：只写价不改软删标记 ⇒ 列表按 is_deleted 过滤、界面上看不见这条价，
        #    而用户以为"改成功了"；顺带 `adjust` 那类"按当前价算"的用法会在一份看不见的价上反复滚。
        row.is_deleted = False
        row.deleted_at = None
        row.unit_price = body.unit_price
    db.flush()
    if created or revived or before != body.unit_price:
        # ⚠️ 只在**真的变了**时记日志：把"点了保存但什么都没改"也记上，审计页会被无意义的行淹没
        #    （那一页只显示最近 60 条）；但"新建一行"和"从回收站里复活"与改价一样是实质变动。
        payload = {
            "scope": "single",
            "mode": "restore" if revived else "set",
            "product": (product.name or "")[:64],
            "contact": contact.display_name if contact is not None else None,
            "before": None if before is None else str(before),
            "after": str(body.unit_price),
        }
        if revived:
            payload["note"] = "这一行原来在回收站里，这次定价把它复活了"
        write_log(
            db,
            operator_id=current.id,
            order_id=None,
            action=OperationAction.SHIPPER_PRICE_UPSERT,
            change_payload=payload,
        )
    # ⚠️ 写入与审计**共用一次提交**（与 price_rules.py 那条注释同一条纪律）：分成两次提交时，
    #    "价改了但日志没落"会留下一笔查不到是谁改的价 —— 而这是最需要追溯的一类改动。
    db.commit()
    db.refresh(row)
    return _to_out(db, row)


@router.delete("/{price_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shipper_price(
    price_id: int,
    current: User = Depends(require_permission(Permission.SHIPPER_PRICE_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    """删一条下游价（**软删**：行留着，`POST /{price_id}/restore` 逐字段放回来）。

    ⚠️ 删掉之后**谁走哪一档**要说清（日志里也这么记）：
    - 删的是**某个人的专属价** ⇒ 他回落「默认下游价」（没有默认价就回落订单行单价）；
    - 删的是**默认价** ⇒ 没单独定价的人一起回落「订单行单价」（他自己那本账按公司给他的价算）。
    ⛔ 历史订单一个字节都不动 —— 快照写在下单那一刻（`order_products.shipper_unit_price`）。
    ⚠️ 用**条件 UPDATE**（`WHERE is_deleted = 0`）而不是"读到没有 → 再写"：连点两下 / 两个请求
    同时删同一条时，只有一个能改成 1，另一个 `rowcount=0` 被拒 —— 否则审计日志里会出现两条一样的
    "删掉了"（这本书只有日志能回查，重复的日志会让人以为还有第二条价）。
    """
    _require_member(current)
    _require_downstream(current)
    row = db.get(ShipperPrice, price_id)
    if row is None or row.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="这条下游价不存在")
    changed = db.execute(
        update(ShipperPrice)
        .where(
            ShipperPrice.id == price_id,
            ShipperPrice.shipper_id == current.id,
            ShipperPrice.is_deleted.is_(False),
        )
        .values(is_deleted=True, deleted_at=utc_now_naive())
    ).rowcount
    if changed != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="这条下游价已经删掉了，不用再删")
    db.refresh(row)
    product = db.get(Product, row.product_id)
    contact = db.get(ShipperContact, row.contact_id) if row.contact_id else None
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.SHIPPER_PRICE_UPSERT,
        change_payload={
            "scope": "single",
            "mode": "delete",
            "product": (product.name or "")[:64] if product is not None else "",
            "contact": contact.display_name if contact is not None else None,
            "before": str(row.unit_price),
            "after": (
                "（删掉这个人的专属价：他回落默认下游价，没有默认价就回落订单行单价）"
                if contact is not None
                else "（删掉默认下游价：没单独定价的人回落订单行单价）"
            ),
            "note": "软删（可 restore 恢复）",
        },
    )
    db.commit()


@router.post("/{price_id}/restore", response_model=ShipperPriceOut)
def restore_shipper_price(
    price_id: int,
    current: User = Depends(require_permission(Permission.SHIPPER_PRICE_MANAGE)),
    db: Session = Depends(get_db),
) -> ShipperPriceOut:
    """把删掉的下游价放回来（`DELETE` 的逆操作）。

    ⚠️ 与**核销**的恢复不是一回事（`shipper_ledger.py::restore_settlement` 那边放回来要重算上限，
    因为一笔钱会重新活过来）：这里放回来的只是"以后按这个价卖"，⛔ **不放回任何一笔已经算过的钱** ——
    下游账的历史仍按订单行上的快照算，改价 / 复活都不动历史（口径⑤ m13365）。
    ⚠️ 同样用**条件 UPDATE**（`WHERE is_deleted = 1`）：连点两下只有一个能改成 0。
    """
    _require_member(current)
    _require_downstream(current)
    row = db.get(ShipperPrice, price_id)
    if row is None or row.shipper_id != current.id:
        raise HTTPException(status_code=404, detail="这条下游价不存在")
    if not row.is_deleted:
        raise HTTPException(status_code=400, detail="这条下游价没有被删掉，不需要恢复")
    changed = db.execute(
        update(ShipperPrice)
        .where(
            ShipperPrice.id == price_id,
            ShipperPrice.shipper_id == current.id,
            ShipperPrice.is_deleted.is_(True),
        )
        .values(is_deleted=False, deleted_at=None)
    ).rowcount
    if changed != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="这条下游价没有被删掉，不需要恢复")
    db.refresh(row)
    product = db.get(Product, row.product_id)
    contact = db.get(ShipperContact, row.contact_id) if row.contact_id else None
    write_log(
        db,
        operator_id=current.id,
        order_id=None,
        action=OperationAction.SHIPPER_PRICE_UPSERT,
        change_payload={
            "scope": "single",
            "mode": "restore",
            "product": (product.name or "")[:64] if product is not None else "",
            "contact": contact.display_name if contact is not None else None,
            "before": "（已删除）",
            "after": str(row.unit_price),
            "note": "把这条下游价放回来（价格一个字节没变）",
        },
    )
    db.commit()
    db.refresh(row)
    return _to_out(db, row)
