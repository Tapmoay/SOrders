"""毛利的成本口径：**入库流水的加权平均进货价**（用户 2026-09-19 要求）。

## 为什么不能再用订单行的 `cost_price_snapshot` 当毛利成本

`cost_price_snapshot` 是**下单那一刻商品的最新进货价**（`products.cost_price` 的快照）。
进货价一涨，从旧库存出的货就被按**新的高价**算成本 → 毛利偏低。
用户原话：「他那个毛利率会做一个计算的…他不是有那个入库记录吗？不能这么算啊，
这么算的话毛利率会偏低啊。所以要分开来，算毛利率的话，我们可以算一个平均的成本，
也就是说在单位时间内的平均成本，比如在这 1 年之内或者一个月之内的」。

库里其实有更准的一手数据：每次入库都记了**这批货的进货价**
（`inventory_movements.unit_cost`，2026-09-19 起才真的落库——在那之前它只被拿去改
`products.cost_price`，流水上什么都没留）。毛利现在就从它算。

## 三级口径（每一级都要能一句话解释给用户听）

| 级 | 什么时候用 | 怎么算 |
|---|---|---|
| ① 期间均价 | 该商品在**本期**有带价入库 | Σ(本期入库数量 × 进货价) ÷ Σ(本期入库数量) |
| ② 累计均价 | 本期没进货，但**截至期末**进过 | Σ(截至期末的入库数量 × 进货价) ÷ Σ(数量) |
| ③ 下单快照 | 从来没按带价入过库 | 该订单行的 `cost_price_snapshot` |

⚠️ **第③级不是可有可无的**：`unit_cost` 是 2026-09-19 才加的列，老数据一条都没有。
   没有这一级，所有历史报表的毛利覆盖率会在一夜之间变成 0（界面变成"全都没有成本"）——
   而那是**数据还没开始录**的正常状态，不是错误。

⚠️ **一个商品在同一个报表里只用一级**（不会出现"同一个商品一半行按均价、一半行按快照"），
   所以合计是"均价行 + 快照行"两段相加。两段的行数都要报出去
   （`cost_avg_lines` / `cost_snapshot_lines`），界面必须写清楚各是多少行——
   否则用户会以为整份毛利都已经是平均口径。

⛔ **货损金额不走这里**，仍然用 `cost_price_snapshot`：送达那一刻就已经按当时的快照
   把损失金额写进开销账与现金流水了（`accounting_service.apply_damage_accounting`）。
   那是一笔**已经入账**的历史金额，追溯改成均价只会让账本和报表各说一套。
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.business_time import business_day_start_utc
from app.models import InventoryMovement

#: 本期入库流水算出来的加权平均进货价（用户要的"单位时间内的平均成本"）
PERIOD = "period"
#: 本期没有带价入库 → 退回"截至期末"的累计加权平均进货价
CUMULATIVE = "cumulative"
#: 从来没按带价入过库 → 退回下单时的成本快照（老数据都走这一级）
SNAPSHOT = "snapshot"

#: 均价的精度 = 进货价列的精度（`inventory_movements.unit_cost` 是 Numeric(14,4)）。
#: ⚠️ 必须量化：不量化的话 `均价 × 数量` 会带出 28 位商（实测导出单元格出现过
#:    `193.4895418326693227091633466`），Excel 又难看、又和界面上的两位小数对不上。
_Q = Decimal("0.0001")


def _dec(v) -> Decimal:
    """SQL 聚合的返回值可能是 Decimal 也可能是 float（SQLite/MySQL 方言差异），
    一律走 `str` 转，避免 `Decimal(0.1)` 那种二进制噪声。"""
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _weighted_avg(db: Session, until: date, period: tuple[date, date] | None) -> dict[int, Decimal]:
    """带价入库的加权平均进货价：`Σ(数量 × 进货价) ÷ Σ数量`，按商品分组。

    `period=None` = 从最早一笔算起（②累计口径）；否则只算 `period` 这个当地日区间（①）。
    只认 `change > 0 AND unit_cost IS NOT NULL`：订单自动流水（预占/实扣/回冲）没有进货价，
    天然被排除；出库也不参与"进货均价"。
    """
    hi = business_day_start_utc(until + timedelta(days=1))
    qty = func.sum(InventoryMovement.change)
    amount = func.sum(InventoryMovement.change * InventoryMovement.unit_cost)
    q = (
        select(InventoryMovement.product_id, qty, amount)
        .where(
            InventoryMovement.change > 0,
            InventoryMovement.unit_cost.isnot(None),
            InventoryMovement.created_at < hi,
        )
        .group_by(InventoryMovement.product_id)
    )
    if period is not None:
        q = q.where(InventoryMovement.created_at >= business_day_start_utc(period[0]))
    out: dict[int, Decimal] = {}
    for pid, q_total, a_total in db.execute(q).all():
        if pid is None or not q_total or a_total is None:
            continue
        out[int(pid)] = (_dec(a_total) / Decimal(int(q_total))).quantize(_Q, rounding=ROUND_HALF_UP)
    return out


class CostBasis:
    """一个报表窗口内的商品成本口径（三级表见模块 docstring）。

    用法就一句：`cost, source = basis.of(lp.product_id, lp.cost_price_snapshot)`。
    **不要**在别处再写一份"取成本"的逻辑——一处一套是这类报表数字对不上的根源。
    """

    def __init__(self, db: Session, start: date, end: date) -> None:
        self._period = _weighted_avg(db, until=end, period=(start, end))
        self._cumulative = _weighted_avg(db, until=end, period=None)

    def of(self, product_id: int | None, snapshot: Decimal | None) -> tuple[Decimal, str]:
        """→ (这个商品的单位成本, 用的是哪一级)。"""
        if product_id is not None:
            pid = int(product_id)
            avg = self._period.get(pid)
            if avg is not None:
                return avg, PERIOD
            avg = self._cumulative.get(pid)
            if avg is not None:
                return avg, CUMULATIVE
        return (snapshot or Decimal("0")), SNAPSHOT
