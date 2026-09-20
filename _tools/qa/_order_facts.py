"""真机 E2E 用：打印某张订单的**账实状态**（库存/账本/已退/申请单/流水）。

用途单一：在模拟器上点一遍退货申请之前与之后各跑一次，用**库里的数**证明
「申请阶段什么都没动、派单员办理之后库存与账本才变」—— 截图只能证明界面对了，
账实要靠这个。用法：

    python _tools/qa/_order_facts.py 422
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "backend" / "sorders.db"


def main() -> int:
    oid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    c = sqlite3.connect(DB)
    q = lambda s, *a: c.execute(s, a).fetchall()  # noqa: E731

    row = q("select order_no, status, returned_at from orders where id=?", oid)
    print(f"订单 {oid}: {row}")
    lines = q(
        "select id, product_name_snapshot, quantity, returned_quantity "
        "from order_products where order_id=?",
        oid,
    )
    print("商品行（id / 名称 / 下单 / 已退）:")
    for r in lines:
        print("   ", r)
    pids = [r[0] for r in q("select distinct product_id from order_products where order_id=?", oid)]
    for pid in pids:
        if pid:
            print(f"库存 product_id={pid}:", q("select name, stock from products where id=?", pid))
    print("账本行数:", q("select count(*) from ledgers where order_id=?", oid)[0][0])
    print("退货红冲行（数量/金额）:", q(
        # ⚠️ 必须 lower()：`LedgerSource.RETURN` 的值是小写 `return`，而列里可能存的是
        #    枚举**名**（老库/驱动差异，见 `rbac.normalize_role_key` 那段同一类问题）。
        #    第一版照小写查，结果是空 —— 看起来像"没红冲"，其实是查错了大小写。
        "select quantity, total from ledgers where order_id=? and lower(source)='return'", oid
    ))
    print("库存流水（change/状态）:", q(
        "select change, status from inventory_movements where order_id=?", oid
    ))
    print("退货申请单（id/状态/备注/驳回理由）:")
    for r in q(
        "select id, status, note, reject_reason from order_return_requests "
        "where order_id=? order by id",
        oid,
    ):
        print("   ", r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
