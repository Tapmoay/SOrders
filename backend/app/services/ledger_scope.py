"""账本**可见性**的唯一判据：自动账本行跟着**订单**走（已送达且没进回收站），手工账不受限。

## 为什么必须有这一处（2026-09-19 审计 R13-R6，第十六轮修）
订单的"删除"是**打标记**（进回收站，30 天可恢复），而账本行是送达时按订单明细自动生成的 ——
删单**不会**删账本行。于是同一个月的钱出现两个数，而且**两个页面都不报错**：

| 页面 | 口径 | 本机 2026-09 实测 |
|---|---|---|
| 报表中心 · 营业纵览 | 已送达且未进回收站的单 | **97,131.75** |
| 账本管理 · 货主账/批发商账、客户经营页、账本导出 | **没排除** | **101,731.75** |

差 ¥4,600 = 隔离区订单的账本行 4,200（38 行）+ **非已送达状态的历史账本行** 400（7 行：
`source=ORDER` 的自动行却挂在一张 `ACCEPTED` 的单上，而按代码契约自动行只在送达那一刻写）。

## 口径（一句话）
- **`source=ORDER` 的行**：只算"订单**已送达或已退货**且**没进回收站**"的那些（与报表侧**同一句**）；
- **不挂订单的行**（手工记账）：一律算；
- **别的来源**（`RETURN` / `REFUND` 红冲等）：只要求订单没进回收站（红冲是对一份已经存在的送达账的冲回）。

### ⚠️ 为什么"已退货"也要算（BUG-0001，2026-10-03 真机抓到的）
`source=RETURN` 的红冲行只要求"订单没进回收站"，所以整单退货之后**它自己是可见的**；
而它冲的那行 `source=ORDER` 如果还只认 `DELIVERED`，就会**被读口径吃掉** ——
一减一加变成**只剩一减**。真机实测（订单 551，速冻水饺 ×3 袋 ¥85.5）：
整单退货后「订单账（今天）」显示 **合计 −85.5 / 1 笔流水**，而库里明明是 +85.5 与 −85.5 两行
（`ledgers` id=878 / 879，`order_id=551`），看账的人会以为这一天倒亏 85.5 元；
「货主账」「批发商账」同错。部分退货的单仍是 `DELIVERED`、两行本来就都可见 ——
所以这个不对称**只在整单退货**时出现，平时看不出来。

⚠️ 这一条**不是**"把营业额也改宽"：`services/reports/loader.py::load_delivered` 只收
`status == DELIVERED`，整单退货的单对营业额贡献 0；账本两行相抵也是 0 —— **两边仍然是同一个数**。

修完之后本机 2026-09 两个口径**逐位一致**：账本流水 97,131.75 = 营业额 97,131.75。

⚠️ 这里**不是**"删掉那些行"：隔离区是可恢复的，删了账本行就没法恢复；这个函数只负责
"读的时候不把它们算进来"。物理清理时 `data_retention.delete_orders_by_ids` 会把它们一起删。
"""

from __future__ import annotations

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.sql import Select

from app.models import Ledger, Order
from app.models.enums import LedgerSource, OrderStatus


def visible_ledger_clause():
    """`WHERE` 片段（见模块文档的"口径"一节）。

    - `source=ORDER` 的自动行：订单必须**已送达或已退货**且**没进回收站**
      （已退货也要算的理由见模块文档「为什么已退货也要算」）；
    - 不挂订单的手工行：一律算；
    - 别的来源（`REFUND` 等）：只要求订单没进回收站。
    """
    order_row = select(Order.id).where(Order.id == Ledger.order_id)
    return or_(
        Ledger.order_id.is_(None),
        and_(
            # 隔离区（软删）的单：它的账一律不算
            ~exists(order_row.where(Order.deleted_at.isnot(None))),
            or_(
                # 自动账本行：订单必须**已送达**（否则那行是漂移出来的 —— 本机 2026-09
                # 就有 7 行挂在 `ACCEPTED` 的单上 ¥400，而按代码契约自动行只在送达时写）；
                # ⚠️ **整单退货（RETURNED）也算**（BUG-0001）：它的红冲行本来就可见，
                # 这里再把原行藏掉，账上就只剩一减（真机：合计 −85.5 而不是相抵的 0）。
                Ledger.source != LedgerSource.ORDER,
                exists(
                    order_row.where(
                        Order.status.in_((OrderStatus.DELIVERED, OrderStatus.RETURNED))
                    )
                ),
            ),
        ),
    )


def visible_ledger_select() -> Select:
    """账本列表/聚合的统一入口：`select(Ledger).where(visible_ledger_clause())`。

    ⛔ 任何"按账本求和/列表"的地方都应当从这里出发（`ledger.py` 的列表与账户汇总、
    `reports.py` 的客户经营导出、`ledger_export.build_ledger_rows`）——
    少接一处就会出现"同一个月的钱两个数"（见模块文档）。
    """
    return select(Ledger).where(visible_ledger_clause())
