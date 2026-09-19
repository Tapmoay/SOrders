"""反向验证「预占判据必须看订单状态」这条红线**真的会红**（2026-09-19 审计，K1 的漏口）。

## 四类破坏，各注入一次
| 注入 | 红线 | 回归测试 |
|---|---|---|
| 判据改回「有没有 RESERVED 流水」 | 红 | `test_binding_a_product_after_dispatch_creates_the_reservation` 也红 |
| 重算前不锁订单行 | 红 | 结构判据（并发写偏斜本机测不了，只能静态钉） |
| 删掉一个调用点（删行那条路径不再重算） | 红 | — |
| 扫描路径指错 | 红 | — |

⚠️ 快照/还原按**字节**做（`inventory.py` 是 CRLF，文本往返会把整个文件改掉），跑完逐字节核对。

用法：python _tools/qa/_reverse_verify_inventory_reservation.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_inventory_reservation.py"
OP = "backend/app/api/v1/order_products.py"
CHECKREL = "_tools/qa/_check_inventory_reservation.py"
TEST_NODE = "tests/test_audit_round17_reservations.py::test_binding_a_product_after_dispatch_creates_the_reservation"

CASES: list[tuple[str, str, object, bool, str | None]] = [
    (
        "判据改回『有没有 RESERVED 流水』（手输商品名的单永远补不上预占）",
        OP,
        lambda s: s.replace(
            "    if order.dispatched_at is None:\n        return 0\n",
            "    from app.models import InventoryMovement\n"
            "    has = db.scalars(\n"
            "        select(InventoryMovement.id).where(\n"
            "            InventoryMovement.order_id == order.id,\n"
            '            InventoryMovement.source == "ORDER",\n'
            '            InventoryMovement.status == "RESERVED",\n'
            "        ).limit(1)\n"
            "    ).first()\n"
            "    if has is None:\n        return 0\n",
            1,
        ),
        True,
        TEST_NODE,
    ),
    (
        "重算前不锁订单行（两个并发行编辑各写同一差额 → 预占翻倍 → 送达多扣）",
        OP,
        lambda s: s.replace(
            "    db.execute(select(Order.id).where(Order.id == order.id).with_for_update())\n", "", 1
        ),
        True,
        None,
    ),
    (
        "删行那条路径不再重算预占（调用点从 3 个变成 2 个）",
        OP,
        lambda s: s.replace(
            "        # 行删了 → 对应的预占要放掉，否则送达会照扣一件已经不存在的货\n"
            "        db.flush()\n"
            "        _resync_stock_if_assigned(db, order, current.id)\n",
            "        db.flush()\n",
            1,
        ),
        True,
        None,
    ),
    (
        "扫描路径指错（判据空转）",
        CHECKREL,
        lambda s: s.replace(
            'ORDER_PRODUCTS = ROOT / "backend/app/api/v1/order_products.py"',
            'ORDER_PRODUCTS = ROOT / "backend/app/api/v1/order_products_nope.py"',
            1,
        ),
        True,
        None,
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check(target: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(target or CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_test(node: str) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header"],
        cwd=str(ROOT / "backend"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1200:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _r, _t in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate, want_red, node in CASES:
        path = ROOT / rel
        plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        tmp: Path | None = None
        try:
            if rel == CHECKREL:
                tmp = path.with_suffix(".py.injected")
                write_src(tmp, mutated, crlfs[rel])
                code, red_out = run_check(tmp)
            else:
                write_src(path, mutated, crlfs[rel])
                code, red_out = run_check()
            red = code != 0
            if red == want_red:
                print(f"  [OK] {label} → 红线{'报红' if red else '全绿'}")
            else:
                fails.append(f"{label}：期望{'报红' if want_red else '全绿'}，实际相反")
                print(f"  [MISS] {label} → 实际{'报红' if red else '全绿'}")
                continue
            if node is not None:
                tcode, _tout = run_test(node)
                if tcode != 0:
                    print(f"        └ 回归测试也报红 ✓")
                else:
                    fails.append(f"{label}：红线红了，但回归测试**仍然通过**（测试没牙）")
                    print(f"        └ [MISS] 回归测试照常通过")
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()
            path.write_bytes(originals[rel])

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

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
