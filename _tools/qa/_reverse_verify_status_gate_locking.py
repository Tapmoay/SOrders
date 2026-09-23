"""反向验证「状态门必须先取锁再判」这条红线**真的会红**（2026-09-23 第 6 轮新增）。

## 为什么这一条必须配反向验证
这条红线守的是**两处实测缺陷的复发**（改明细 × 送达 → 账本与订单行两个数；
送达后补定价 → 账单 300 而结算页 350），而它们的共同特征是**不报错、不崩**：

- 把 `_locked_editable_order` 里的 `lock_order_row` 删掉 → 功能"看起来一切正常"，
  串行跑一百遍都是对的，只有并发那一瞬间会放行一个已送达的单；
- 把某个写端点改回"自己 `db.get` 再判状态" → 同上，单测/探针**全都不会红**；
- 把 `price_freight` 的锁删掉 → 同上。

六种失效方式各一条注入（含两条"判据自己空转"的兜底）：
  ① 门里先判后锁；② 写端点绕开那道门；③ 写运费的端点不取锁；
  ④ 别处又冒出一个直接判状态的地方（没登记理由）；⑤ 允许表里塞一条化石；
  ⑥ 锁调用点的数量下限失守。

用法：`python _tools/qa/_reverse_verify_status_gate_locking.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
CHECK = HERE / "_check_status_gate_locking.py"
PROD = ROOT / "backend/app/api/v1/order_products.py"
ORDERS = ROOT / "backend/app/api/v1/orders.py"

#: (说明, 目标文件, 被替换的原文, 替换成, 期望在 [FAIL] 行里出现的关键词)
CASES: list[tuple[str, Path, str, str, str]] = [
    (
        "明细编辑那道门先判后锁（判完到拿锁之间那道缝还在）",
        PROD,
        "    order = lock_order_row(db, order)\n    if not _order_allows_line_edit(order):",
        "    if not _order_allows_line_edit(order):\n        raise HTTPException(status_code=400, detail=\"当前订单状态不可编辑商品明细\")\n    order = lock_order_row(db, order)\n    if False:",
        "先取锁、再判状态",
    ),
    (
        "只留锁、把原子占位拿掉（SQLite 上那条缝又回来了 —— 实测会落成账本≠订单行）",
        PROD,
        "    claimed = db.execute(\n        update(Order)\n        .where(\n"
        "            Order.id == order.id,\n            Order.status.in_(LINE_EDITABLE_STATUSES),",
        "    claimed = db.execute(\n        update(Order)\n        .where(\n"
        "            Order.id == order.id,\n            Order.status.in_((OrderStatus.PENDING_DISPATCH,)),",
        "与数据库无关的原子占位",
    ),
    (
        "写端点绕开那道门（自己读了订单对象就判状态）",
        PROD,
        "    order = _locked_editable_order(db, op.order_id)\n    if body.product_id is not None:",
        "    order = db.get(Order, op.order_id)\n    if not _order_allows_line_edit(order):\n"
        "        raise HTTPException(status_code=400, detail=\"当前订单状态不可编辑商品明细\")\n"
        "    if body.product_id is not None:",
        "走 `_locked_editable_order`",
    ),
    (
        "定价端点不取锁（判完到写之间正是送达能挤进来的窗口）",
        ORDERS,
        "    order = lock_order_row(db, order)\n    if order.status == OrderStatus.CANCELLED:\n"
        "        raise HTTPException(status_code=400, detail=\"这一单已经撤销了，不用再定价\")",
        "    if order.status == OrderStatus.CANCELLED:\n"
        "        raise HTTPException(status_code=400, detail=\"这一单已经撤销了，不用再定价\")",
        "orders.freight_fee ← orders.py::price_freight",
    ),
    (
        "别处又冒出一个直接判状态的地方（没登记理由就是绕过那道门）",
        PROD,
        "    if body.quantity is not None:\n        op.quantity = body.quantity",
        "    if not _order_allows_line_edit(db.get(Order, op.order_id)):\n"
        "        raise HTTPException(status_code=400, detail=\"状态不对\")\n"
        "    if body.quantity is not None:\n        op.quantity = body.quantity",
        "是允许的状态门调用点",
    ),
    (
        "理由表里塞一条化石（那个字段已经不是多写入点了）",
        CHECK,
        "SAME_FIELD_REASONS: dict[str, str] = {",
        "SAME_FIELD_REASONS: dict[str, str] = {\n"
        "    \"早就删掉的字段\": \"化石化石化石化石化石化石化石化石化石化石化石\",",
        "没有化石",
    ),
    (
        "某个多写入点字段的理由被删掉（而它又没取锁）",
        CHECK,
        '    "paid": (\n        "三个写入点写的是**同一个事实**',
        '    "paid__X": (\n        "三个写入点写的是**同一个事实**',
        "orders.paid ←",
    ),
    (
        "理由写得太短（等于没写）",
        CHECK,
        '    "exception_reason": (\n'
        '        "与 `is_exception` 同一次写入：标记时写原因、解除时保留原因为「异常订单」，见上一条。"\n'
        "    ),",
        '    "exception_reason": "没事",',
        "理由太短",
    ),
    (
        "新加一个没人交代的多写入点字段（两个函数各写一处，谁都没取锁也没理由）",
        ORDERS,
        ['    order.exception_reason = body.exception_reason or ""\n',
         "    if body.internal_notes is not None:\n        order.internal_notes = body.internal_notes\n"],
        ['    order.exception_reason = body.exception_reason or ""\n'
         "    order.zzz_probe_field = 1\n",
         "    if body.internal_notes is not None:\n        order.internal_notes = body.internal_notes\n"
         "        order.zzz_probe_field = 2\n"],
        "orders.zzz_probe_field",
    ),
    (
        "锁调用点的数量下限失守（扫描坏了却不喊）",
        CHECK,
        "MIN_LOCKS = 3",
        "MIN_LOCKS = 999",
        "锁调用点不少于",
    ),
    (
        "多写入点的盘点下限失守（盘点逻辑坏了却不喊）",
        CHECK,
        "MIN_MULTI_FIELDS = 4",
        "MIN_MULTI_FIELDS = 999",
        "多写入点字段不少于",
    ),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0 or "[FAIL]" in out:
        print(f"❌ 前提不成立：源码完好时这条红线就没过（code={code}）\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    touched = sorted({p for _l, p, _o, _n, _e in CASES})
    originals = {p: p.read_bytes() for p in touched}

    for label, path, old, new, expect in CASES:
        original_bytes = originals[path]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        # `old`/`new` 可以是**一串**替换（一次注入要在两个函数里各加一行时用它 ——
        # 例："新加一个没人交代的多写入点字段"必须让那个字段真的有两个写入点）。
        olds = old if isinstance(old, list) else [old]
        news = new if isinstance(new, list) else [new]
        data = plain
        ok_anchor = len(olds) == len(news)
        for o, nw in zip(olds, news):
            if data.count(o) != 1:
                ok_anchor = False
                break
            data = data.replace(o, nw, 1)
        if not ok_anchor:
            fails.append(f"{label}：注入没生效（某个原文不是恰好出现 1 次，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            path.write_bytes((data.replace("\n", "\r\n") if crlf else data).encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and expect in out and "[FAIL]" in out
        detail = "报红" if hit else f"没有红在预期那条（{expect!r}）"
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            for ln in [x for x in out.splitlines() if "[FAIL]" in x][:3]:
                print("        " + ln.strip())
            fails.append(f"{label}：{detail}")

    dirty = [p for p in touched if p.read_bytes() != originals[p]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(p.name for p in dirty))
        for p in dirty:
            p.write_bytes(originals[p])
        print("⚠️  已强制还原：" + "、".join(p.name for p in dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    code, out = run_check()
    if code == 0 and "[FAIL]" not in out:
        print("  [OK] 还原后红线恢复全绿")
    else:
        fails.append("还原之后红线没恢复全绿")
        print("  [MISS] 还原后红线没恢复全绿")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
