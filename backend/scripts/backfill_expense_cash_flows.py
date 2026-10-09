"""开销单 → 现金流水 存量回填（一次性，2026-10-09 BUG-0018 / 台账 TB-02）。

## 为什么要有这一步

`scripts/seed_demo_data.py` 原来用 `db.add(Expense(...))` 直接造 30 笔历史开销 —— 那一步**绕过了
服务层的记账**（只有 `accounting_service.create_expense` 会写 `cash_flows` OUT）。后果：那些开销在
「开销管理」页上看得见、在「账本 / 收支」页上一分钱都看不见。开发库实测：`expenses` 53 张 /
44560.51 元，其中只有 23 张有流水（EXPENSE_* 合计 8720.51 元），缺的 30 张 `created_at` 全是
`2026-09-20 09:58:27.189947`（正是播种那一刻）。播种脚本已一并改成走服务层（不会再产生新的），
这一遍负责把**已经写进库里的**那些补齐。

## 口径

· 一条开销单 → 一条 `cash_flows` OUT：账期 / 金额 / 分类 / 备注 / 订单与那张开销单逐字一致；
· 写入走 `accounting_service.write_expense_cash_flow`（**记账与回填是同一个函数**）；
· `biz_type` 走服务层**同一张表**（`accounting_service.expense_biz_type`）——⛔ 本脚本不抄第二份；
· **幂等**：已经有流水的开销单一条都不碰（按 `party_type = "expense"` + `direction = out` + `doc_id`
  认）。跑两遍的结果与跑一遍相同 —— 第二遍应当是「0 张」。

用法（在 backend/ 目录下跑）：

    python -m scripts.backfill_expense_cash_flows           # 预览（默认，不写库）
    python -m scripts.backfill_expense_cash_flows --yes     # 真的写库
"""

from __future__ import annotations

import argparse

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import CashFlow, Expense
from app.models.enums import CashFlowDirection
from app.services.accounting_service import write_expense_cash_flow


def expenses_without_cash_flow(db) -> list[Expense]:
    """没有任何现金流水的开销单（按 id 正序）。

    ⚠️ 「什么算已经有流水」只写在这一处（预览与写库共用）：抄第二份的话，两边对这个条件的看法
    会慢慢走散，而症状是**重复补写** —— 同一张开销单两条流水，报表上那笔钱翻倍。
    """
    covered = set(
        db.scalars(
            select(CashFlow.doc_id).where(
                CashFlow.party_type == "expense",
                CashFlow.direction == CashFlowDirection.OUT,
                CashFlow.doc_id.isnot(None),
            )
        ).all()
    )
    return [e for e in db.scalars(select(Expense).order_by(Expense.id)).all()
            if e.id not in covered]


def backfill_expense_cash_flows(db, *, dry_run: bool = True) -> tuple[int, int]:
    """给缺流水的开销单补一条 OUT。返回 `(待补 / 已补 条数, 本来就有流水 的条数)`。

    `dry_run=True`（默认）只算不写 —— 一次性脚本的第一条纪律是"先看清楚要改什么"。
    """
    missing = expenses_without_cash_flow(db)
    total = db.scalar(select(func.count()).select_from(Expense)) or 0
    if dry_run:
        return len(missing), total - len(missing)
    for e in missing:
        write_expense_cash_flow(db, e)
    db.commit()
    return len(missing), total - len(missing)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="开销单 → 现金流水 存量回填（默认只预览，--yes 才写库）")
    ap.add_argument("--yes", action="store_true", help="真的写库（不带这个参数就是预览）")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        missing = expenses_without_cash_flow(db)
        print(f"没有现金流水的开销单：{len(missing)} 张")
        for e in missing[:5]:
            print(f"    #{e.id} {e.exp_date} {e.category} ¥{e.amount}")
        if len(missing) > 5:
            print(f"    …另有 {len(missing) - 5} 张")
        n, had = backfill_expense_cash_flows(db, dry_run=not args.yes)
        if not args.yes:
            print(f"预览模式（默认）：待补 {n} 条；本来就有流水的 {had} 张。加 --yes 才写库。")
        else:
            print(f"✅ 已补写 {n} 条现金流水；本来就有流水的 {had} 张。"
                  f"（幂等：再跑一次应当是「没有现金流水的开销单：0 张」）")
    finally:
        db.close()
