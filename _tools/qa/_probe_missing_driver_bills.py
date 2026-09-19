"""「有没有已送达的单，司机该拿钱却没生成应付」——**钱这一侧的覆盖度探针**（第十七轮审计）。

## 为什么要有它
台账里挂着一条悬案：本机库 **266 张 PIECE 已送达单没有 `driver_bills`**（占 574 张的 46%）。
它有两种可能，而两者的处置完全相反：
- **数据来源问题**（种子/测试数据绕过了接口，直接写库）→ 不用改代码；
- **代码路径问题**（某条送达路径不生成账单）→ 司机白跑、账面上查不出来，是要命的缺陷。

静态红线看不见数据，单测只能钉住"我想到的那几条路径"。这个探针用**系统自己的判据**
（`driver_pay.pay_for_order` / `has_per_order_pay` —— 与账单、结算页、报表同源的那一处实现）
逐单算一遍"这张单该不该有账单"，再和库里实际的 `driver_bills` 对账。

## 判据
对每张 `DELIVERED` 订单：
```
该有账单  ⇔  has_per_order_pay(order) 且 pay_for_order(order).total > 0
```
- 不该有（`SALARY` 固定工资、运费为 0/空且没有规则）→ **正常**，只在统计里报数；
- 该有却没有 → **真实缺口**，逐条列出来（单号 / 司机 / 金额 / 送达时间）。

⚠️ 探针**只读**：一条 `SELECT` 都不改写，也不修数据。要处置缺口，先看清单再决定。

## 用法
```
python _tools/qa/_probe_missing_driver_bills.py                 # 本机开发库（backend/sorders.db）
python _tools/qa/_probe_missing_driver_bills.py --db-url mysql+pymysql://...   # 别的库（只读）
python _tools/qa/_probe_missing_driver_bills.py --seed-prefix SOTEST           # 把某类前缀当种子数据
```
退出码：非零 = 存在**非种子**的真实缺口（可以被 CI/收尾清单当判据用）。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

#: 种子/测试数据的前缀（本机库里那些 "SOTEST*" 单是造数据脚本直接写库的，没有账单很正常）。
DEFAULT_SEED_PREFIXES = ("SOTEST", "TEST", "探针")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-url", default=None, help="缺省用 backend/sorders.db（本机开发库）")
    ap.add_argument("--seed-prefix", action="append", default=[],
                    help="把这些前缀的单号当种子数据（可重复；缺省 SOTEST/TEST/探针）")
    ap.add_argument("--show", type=int, default=20, help="真实缺口最多列几条")
    a = ap.parse_args()

    import os

    if a.db_url:
        os.environ["DATABASE_URL"] = a.db_url
    elif not os.environ.get("DATABASE_URL"):
        os.environ.setdefault("DATABASE_URL", f"sqlite:///{(BACKEND / 'sorders.db').as_posix()}")

    # ⚠️ **不许** `import app.database`：它在导入时就跑 `bootstrap_schema(engine)`（DDL/补列），
    #    而这是一个**只读**探针 —— 对着生产库跑的时候，探针自己去改表结构是不可接受的。
    #    这里只借 `app.config.get_settings()` 拿到连接串，自己建引擎。
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session, selectinload

    from app.config import get_settings
    from app.models import DriverBill, Order
    from app.models.enums import DriverBillType, OrderStatus
    from app.services.driver_pay import has_per_order_pay, pay_for_order

    seeds = tuple(a.seed_prefix) or DEFAULT_SEED_PREFIXES
    url = get_settings().database_url
    engine = create_engine(url)
    print(f"库：{url.split('@')[-1]}")

    with Session(engine) as db:
        # ⚠️ 全程在同一个 Session 里算：`pay_for_order` 要读 `order.order_products`
        #    （商品金额提成要用），Session 一关就 DetachedInstanceError。
        orders = list(
            db.scalars(
                select(Order)
                .options(selectinload(Order.order_products))
                .where(Order.status == OrderStatus.DELIVERED)
            ).unique()
        )
        billed = {
            int(oid)
            for oid in db.scalars(
                select(DriverBill.order_id).where(
                    DriverBill.bill_type == DriverBillType.PIECE,
                    DriverBill.order_id.isnot(None),
                )
            )
            if oid is not None
        }

        should_have: list[tuple[Order, Decimal]] = []
        no_need = 0
        for o in orders:
            if not has_per_order_pay(o):
                no_need += 1
                continue
            total = pay_for_order(o).total
            if total is None or Decimal(str(total)) <= 0:
                no_need += 1
                continue
            should_have.append((o, Decimal(str(total))))

        missing = [(o, amt) for o, amt in should_have if o.id not in billed]
        real = [(o, amt) for o, amt in missing if not (o.order_no or "").startswith(seeds)]
        seeded = [(o, amt) for o, amt in missing if (o.order_no or "").startswith(seeds)]

        print(f"已送达订单 {len(orders)} 张：")
        print(f"  · 按设计**不该**有按单应付（固定工资 / 运费为 0 且无规则）：{no_need}")
        print(f"  · 该有按单应付：{len(should_have)}，其中库里真有账单：{len(should_have) - len(missing)}")
        print(f"  · 缺账单：{len(missing)}（种子数据 {len(seeded)}、**真实缺口 {len(real)}**）")
        if missing:
            print(f"    缺账单金额合计：¥{sum((amt for _o, amt in missing), Decimal('0'))}")
        if real:
            print("\n❌ 真实缺口 —— 这些单该付钱却没有应付明细（司机白跑，账面上看不出来）：")
            for o, amt in real[: a.show]:
                print(
                    f"   订单 {o.order_no}（id={o.id}）司机 {o.driver_id} 应付 ¥{amt} "
                    f"送达 {o.delivered_at} 模式 {o.driver_billing_mode_snapshot or '(空)'}"
                )
            if len(real) > a.show:
                print(f"   …… 还有 {len(real) - a.show} 条")
            print("\n处置提示：先看这些单的送达路径（是接口送达还是脚本直写库），")
            print("         再决定是补 `POST /driver-bills`（补单）还是修生成逻辑——**别直接改库**。")
        if seeded:
            by_prefix = Counter((o.order_no or "")[:6] for o, _ in seeded)
            print(f"\n（种子数据的 {len(seeded)} 条按前缀分布：{dict(by_prefix)}——"
                  f"它们是造数据脚本直接写库的，不代表代码路径有问题）")

    if real:
        return 1
    print(f"\n✅ 没有真实缺口：该有应付的 {len(should_have)} 张单里，只有种子数据缺账单。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
