"""数据不变式审计（fuzz #3）：**直接查库**，看钱、库存、状态、单据之间还对不对得上。

## 它和接口测试的分工
接口测试问"这个请求会怎样"；这里问"**库里现在这些行自相矛盾吗**"——
很多缺陷的表现是"接口全 200、界面上也看不出来，只有把两张表摆一起才发现对不上"
（本项目已经有过实例：挂账结清的钱在报表里凭空消失、司机账单与结算页两个数）。

## 判据的写法（关键）
- **金额口径与后端同源**：司机应付不在这里重写公式，直接把 `orders.driver_rule_snapshot`
  喂给 `app.services.driver_pay.order_pay` —— "钱只算一处"这条规矩，审计工具也必须守。
- **先校准再定罪**：每条判据先统计"命中率"。如果**所有**行都不满足，那是判据写错了
  （列名语义理解错），脚本会明说"判据可能写错"，而不是报一堆假缺陷。
- 只读：`mode=ro` 打开数据库，绝不写。

用法：
```
python _tools/fuzz/_fuzz_invariants.py              # 全部
python _tools/fuzz/_fuzz_invariants.py --limit 20   # 每条最多列几个例子
```
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fuzzlib import DB_PATH, ROOT, Report, db_q, money  # noqa: E402

sys.path.insert(0, str(ROOT / "backend"))

TOL = Decimal("0.01")
#: 负数金额"修复线"：这一天之前建的行算历史（当年探测出来的缺陷留下的证据），
#: 之后还出现就是新的洞。日期来自那次修复（`schemas/product.py` 加 ge=0 / 行金额收口）。
FIX_DATE_ROWS = "2026-09-18"


def check_negative(rep: Report, table: str, col: str, extra: str,
                   since: str | None, limit: int = 5) -> None:
    """负数金额检查：按 `created_at` 分成"历史"与"新增"两桶。"""
    try:
        rows = db_q(f"select id, {col} as v, created_at from {table} where {extra} and {col} < 0")
        total = db_q(f"select count(*) from {table} where {extra}")[0][0]
    except Exception as e:
        rep.risk(f"判据执行失败：{table}.{col} 有负数", f"{type(e).__name__}: {e}")
        return
    if not rows:
        rep.ok(f"{table}.{col} 没有负数（检查 {total} 行）")
        return
    old = [r for r in rows if since and str(r["created_at"] or "") < since]
    new = [r for r in rows if r not in old]
    if new:
        rep.bug(f"{table}.{col} 出现负数（修复线 {since} 之后建的）：{len(new)} 行",
                "; ".join(f"id={r['id']} {col}={r['v']} 建于 {r['created_at']}" for r in new[:limit]))
    if old:
        rep.risk(f"{table}.{col} 有负数（历史行，修复前留下）：{len(old)} 行",
                 "; ".join(f"id={r['id']} {col}={r['v']} 建于 {r['created_at']}" for r in old[:limit])
                 + "　—— 属于旧缺陷的遗留数据，建议清理或忽略（新行会单独报成缺陷）")


def check_ic(rep: Report, title: str, bad_sql: str, total_sql: str | None = None,
             detail_sql: str | None = None, limit: int = 5, kind: str = "BUG") -> None:
    """通用一条：`bad_sql` 返回坏行（可为 id+说明），`total_sql` 返回检查总数。

    ⚠️ 校准：坏行 == 总数 且 总数 > 0 时判为"判据写错"，不算缺陷。
    """
    try:
        bad = db_q(bad_sql)
    except Exception as e:
        rep.risk(f"判据执行失败：{title}", f"{type(e).__name__}: {e}（SQL 或表结构变了？）")
        return
    total = None
    if total_sql:
        try:
            total = db_q(total_sql)[0][0]
        except Exception:
            total = None
    if not bad:
        rep.ok(f"{title}（检查 {total if total is not None else '?'} 行）")
        return
    if total is not None and len(bad) >= total and total > 0:
        rep.risk(f"判据可能写错：{title}", f"{len(bad)}/{total} 行都不满足——先怀疑判据，不是数据")
        return
    head = f"{title}：{len(bad)} 行"
    if total:
        head += f"（共 {total} 行）"
    examples = "; ".join(
        " ".join(str(v) for v in (dict(r).values() if isinstance(r, dict) else tuple(r)) if v is not None)[:160]
        for r in bad[:limit]
    )
    getattr(rep, kind if kind in ("bug", "risk", "info") else "bug")(head, examples)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    lim = ap.parse_args().limit

    rep = Report("数据不变式审计：钱 / 库存 / 状态 / 单据还对不对得上", module="_fuzz_invariants")
    n_orders = db_q("select count(*) from orders")[0][0]
    rep.guard("库里有订单可查（空库等于没测）", n_orders > 0, f"orders={n_orders}")

    # ---------------------------------------------------------------- 订单行金额
    rep.section("订单行金额 = 数量 × 单价（服务端口径，先乘后按分四舍五入）")
    rows = db_q("select p.id, p.order_id, p.quantity, p.unit_price, p.line_total, p.created_at, "
                "o.deleted_at from order_products p left join orders o on o.id = p.order_id "
                "where o.deleted_at is null")
    bad = [r for r in rows if money(Decimal(str(r["quantity"])) * Decimal(str(r["unit_price"])))
           != money(r["line_total"])]
    rep.guard("订单行不是空的（不然这条判据在空转）", len(rows) > 0, f"{len(rows)} 行")
    if bad:
        # ⚠️ 这条**故意报 RISK 而不是 BUG**：`line_total` 允许与"数量×单价"不等，
        #    因为账本行回写时会把订单行金额一起改掉（记忆里那条：账本 576→500，订单行也跟着变）。
        #    所以对不上只能说明"值得看一眼"，不能直接定罪。
        rep.risk(f"订单行金额与 数量×单价 不一致：{len(bad)}/{len(rows)} 行（可能是账本回写，也可能真是脏数据）",
                 "; ".join(f"行{r['id']} 单{r['order_id']} {r['quantity']}×{r['unit_price']}≠{r['line_total']}"
                           f"（建于 {r['created_at']}）" for r in bad[:lim]))
    else:
        rep.ok(f"订单行金额逐行一致（{len(rows)} 行，不含回收站里的单）")

    # ---------------------------------------------------------------- 司机账单 vs 规则快照
    rep.section("司机账单 = 按派单时快照重算（**直接调 driver_pay.pay_for_order**，不重写公式）")
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session as OrmSession

        from app.models.order import Order  # type: ignore
        from app.services.driver_pay import pay_for_order  # type: ignore

        # 只读引擎：审计绝不写库（mode=ro 由 SQLite 自己保证）
        eng = create_engine(f"sqlite:///file:{DB_PATH}?mode=ro&uri=true",
                            connect_args={"uri": True})
        mismatch: list[str] = []
        n_bills = 0
        with OrmSession(eng) as s:
            bills = db_q("select id, order_id, amount, rule_name from driver_bills "
                         "where bill_type='piece' and order_id is not null")
            n_bills = len(bills)
            for b in bills:
                order = s.get(Order, b["order_id"])
                if order is None:
                    mismatch.append(f"账单{b['id']} 指向不存在的订单 {b['order_id']}")
                    continue
                want = money(pay_for_order(order).total)
                got = money(b["amount"])
                if want != got:
                    mismatch.append(f"账单{b['id']} 单{order.id} 重算 {want} vs 账单 {got}"
                                    f"（规则 {b['rule_name'] or '无'}）")
        if mismatch:
            rep.bug(f"司机账单与规则快照对不上：{len(mismatch)}/{n_bills} 张",
                    "; ".join(mismatch[:lim]))
        else:
            rep.ok(f"司机账单逐张重算一致（{n_bills} 张）")
        rep.guard("这条判据真的算到了账单（否则是空转）", n_bills > 0, "库里没有 PIECE 账单")
    except Exception as e:
        rep.risk("无法复用 driver_pay 重算账单", f"{type(e).__name__}: {e}")

    # ---------------------------------------------------------------- 幂等：账单唯一性
    rep.section("账单唯一性（同一单同一类型只能有一张）")
    check_ic(rep, "同一订单同一类型的司机账单重复",
             "select order_id, bill_type, count(*) c, group_concat(id) ids from driver_bills "
             "where order_id is not null group by order_id, bill_type having c > 1",
             "select count(distinct order_id) from driver_bills where order_id is not null", limit=lim)
    check_ic(rep, "同一司机同一月同一类型的工资单重复",
             "select driver_id, month, bill_type, count(*) c, group_concat(id) ids from driver_bills "
             "where bill_type='salary' group by driver_id, month, bill_type having c > 1",
             "select count(*) from driver_bills where bill_type='salary'", limit=lim)

    # ---------------------------------------------------------------- 账本 vs 订单
    rep.section("账本净额 = 订单行金额合计（未撤销单）")
    check_ic(rep, "订单账本净额与订单金额对不上",
             "select o.id, o.order_no, o.status, "
             "(select coalesce(sum(l.total),0) from ledgers l where l.order_id=o.id) net, "
             "(select coalesce(sum(p.line_total),0) from order_products p where p.order_id=o.id) want "
             "from orders o where o.status='delivered' and o.deleted_at is null and exists "
             "(select 1 from ledgers l where l.order_id=o.id) and "
             "abs((select coalesce(sum(l.total),0) from ledgers l where l.order_id=o.id) - "
             "(select coalesce(sum(p.line_total),0) from order_products p where p.order_id=o.id)) > 0.01",
             "select count(*) from orders where status='delivered'", limit=lim)

    # ---------------------------------------------------------------- 收款 vs paid
    rep.section("收款与 paid 标记")
    check_ic(rep, "逐单核销的收款单里绑了未标记 paid 的订单",
             "select r.id, r.amount, r.order_ids from shipper_receipts r where r.settle_mode='itemized' "
             "and exists (select 1 from json_each(r.order_ids) j join orders o on o.id = j.value "
             "where o.paid = 0)",
             "select count(*) from shipper_receipts where settle_mode='itemized' "
             "and order_ids is not null", limit=lim)
    check_ic(rep, "收款单绑了不存在的订单",
             "select r.id, r.order_ids from shipper_receipts r where r.order_ids is not null "
             "and exists (select 1 from json_each(r.order_ids) j where j.value not in "
             "(select id from orders))",
             "select count(*) from shipper_receipts where order_ids is not null", limit=lim)
    check_ic(rep, "多单核销的资金流水金额不为空（历史口径：多单不写金额）",
             "select id, doc_id, amount from cash_flows where biz_type like '%receipt%' "
             "and id in (select id from cash_flows where amount is not null)", None, limit=lim, kind="info")

    # ---------------------------------------------------------------- 结算单
    rep.section("司机结算单")
    check_ic(rep, "已结算账单没有挂结算单号",
             "select id, driver_id, month, status from driver_bills "
             "where status='settled' and (settled_doc_id is null or settled_doc_id=0)",
             "select count(*) from driver_bills where status='settled'", limit=lim)
    check_ic(rep, "未结算账单却挂着结算单号",
             "select id, driver_id, month, status, settled_doc_id from driver_bills "
             "where status='open' and settled_doc_id is not null",
             "select count(*) from driver_bills where status='open'", limit=lim)
    check_ic(rep, "结算单金额与明细合计对不上（已确认/已付款的单）",
             "select s.id, s.amount, s.status, "
             "(select coalesce(sum(b.amount),0) from driver_bills b where b.settled_doc_id=s.id) want, "
             "(select count(*) from driver_bills b where b.settled_doc_id=s.id) n_bills "
             "from driver_settlements s where s.status in ('confirmed','paid') and "
             "exists (select 1 from driver_bills b where b.settled_doc_id=s.id) and "
             "abs(s.amount - (select coalesce(sum(b.amount),0) from driver_bills b "
             "where b.settled_doc_id=s.id)) > 0.01",
             "select count(*) from driver_settlements where status in ('confirmed','paid')",
             limit=lim)

    # ---------------------------------------------------------------- 库存
    rep.section("库存账（按订单核对：出库合计必须等于该单数量之和）")
    # ⚠️ 判据改过一次：原来写"product.stock == 流水合计"，结果 39/39 行都不满足——
    #    因为 `products.stock` 是**创建时的初始值**（后续只由流水增减），初始值没存在任何地方，
    #    所以"库存 = 流水合计"在库里根本不可判。换成**能判的**那条：按订单核。
    check_ic(rep, "已送达订单的出库数量与该单数量之和对不上",
             "select o.id, o.order_no, "
             "(select coalesce(sum(m.change),0) from inventory_movements m "
             " where m.order_id=o.id and m.status='committed') mv, "
             "-(select coalesce(sum(p.quantity),0) from order_products p where p.order_id=o.id) want "
             "from orders o where exists (select 1 from inventory_movements m "
             " where m.order_id=o.id and m.status='committed') and "
             "(select coalesce(sum(m.change),0) from inventory_movements m "
             " where m.order_id=o.id and m.status='committed') != "
             "-(select coalesce(sum(p.quantity),0) from order_products p where p.order_id=o.id)",
             "select count(distinct order_id) from inventory_movements where status='committed' "
             "and order_id is not null", limit=lim)
    check_ic(rep, "库存为负（超卖）", 
             "select id, name, stock from products where is_deleted=0 and stock < 0",
             "select count(*) from products where is_deleted=0", limit=lim, kind="risk")
    check_ic(rep, "预占流水没有对应的撤销/实扣（订单已终结但仍 RESERVED）",
             "select m.id, m.order_id, m.change, m.status from inventory_movements m "
             "join orders o on o.id = m.order_id "
             "where m.status='reserved' and o.status in ('cancelled','delivered','recalled')",
             "select count(*) from inventory_movements where status='reserved'", limit=lim)

    # ---------------------------------------------------------------- 状态机一致性
    rep.section("状态与时间戳/字段的对应")
    check_ic(rep, "已送达但没有送达时间",
             "select id, order_no, status, delivered_at from orders "
             "where status='delivered' and delivered_at is null",
             "select count(*) from orders where status='delivered'", limit=lim)
    check_ic(rep, "派单中/已接单但没有司机",
             "select id, order_no, status, driver_id from orders "
             "where status in ('dispatched','acked') and driver_id is null",
             "select count(*) from orders where status in ('dispatched','acked')", limit=lim)
    check_ic(rep, "待派单却已经有司机",
             "select id, order_no, status, driver_id from orders "
             "where status='pending_dispatch' and driver_id is not null",
             "select count(*) from orders where status='pending_dispatch'", limit=lim)
    check_ic(rep, "已撤销但没有撤销时间",
             "select id, order_no, status, cancelled_at from orders "
             "where status='cancelled' and cancelled_at is null",
             "select count(*) from orders where status='cancelled'", limit=lim)
    check_ic(rep, "既已送达又有撤销时间",
             "select id, order_no, status, delivered_at, cancelled_at from orders "
             "where delivered_at is not null and cancelled_at is not null", None, limit=lim, kind="info")

    # ---------------------------------------------------------------- 孤儿行
    rep.section("孤儿行（指向已不存在的父行）")
    for child, col, parent in (
        ("order_products", "order_id", "orders"),
        ("driver_bills", "order_id", "orders"),
        ("ledgers", "order_id", "orders"),
        ("inventory_movements", "order_id", "orders"),
        ("cash_flows", "order_id", "orders"),
    ):
        check_ic(rep, f"{child}.{col} 指向不存在的订单",
                 f"select id, {col} from {child} where {col} is not null and {col} not in "
                 f"(select id from {parent})",
                 f"select count(*) from {child} where {col} is not null", limit=lim)

    # ---------------------------------------------------------------- 金额符号
    rep.section("金额符号（不该出现负数的地方出现负数）")
    # ⚠️ 这里按**时间**分成两桶：修复前建的行是"历史的证据"，修复后还出现就是"新的洞"。
    #    不分开的话只有两种做法，都糟：要么把历史行也报成缺陷（每次跑都红，慢慢没人看），
    #    要么把判据删掉（新洞也一起放过）。分桶之后历史行留在报告里，新行立刻是缺陷。
    LIVE_LINE = "order_id in (select id from orders where deleted_at is null)"
    for table, col, extra, since in (
        ("order_products", "line_total", LIVE_LINE, FIX_DATE_ROWS),
        ("order_products", "unit_price", LIVE_LINE, FIX_DATE_ROWS),
        ("products", "default_unit_price", "is_deleted=0", FIX_DATE_ROWS),
        ("products", "cost_price", "is_deleted=0", FIX_DATE_ROWS),
        ("driver_bills", "amount", "1=1", None),
        ("shipper_receipts", "amount", "1=1", None),
        ("expenses", "amount", "1=1", None),
        ("price_rules", "special_unit_price", "1=1", None),
    ):
        check_negative(rep, table, col, extra, since, lim)
    check_ic(rep, "products.stock 有负数（超卖，口径待用户拍板）",
             "select id, name, stock from products where is_deleted=0 and stock < 0",
             "select count(*) from products where is_deleted=0", limit=lim, kind="risk")

    # ---------------------------------------------------------------- 结算单脱钩
    #
    # ⚠️ 这条原来报 RISK（"要看产品口径"）。2026-09-18 之后**升级成缺陷**：
    #    API 三条路都堵着（建单要待结明细、确认要金额 == 明细合计、付款前还要再复核一次明细），
    #    所以再出现这种行只能是"绕过业务规则直接写库/删行"——那是缺陷，不是口径问题。
    #    库里那张 352 元的（造数工具直接 INSERT 出来的假账）已按
    #    `_tools/qa/_repair_orphan_settlement.py` 处置掉。
    check_ic(rep, "已确认/已付款结算单在库里没有任何关联明细",
             "select s.id, s.driver_id, s.month, s.amount, s.status, s.note from driver_settlements s "
             "where s.status in ('confirmed','paid') and not exists "
             "(select 1 from driver_bills b where b.settled_doc_id = s.id)",
             "select count(*) from driver_settlements where status in ('confirmed','paid')",
             limit=lim)

    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
