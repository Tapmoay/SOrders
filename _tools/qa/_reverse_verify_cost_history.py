"""反向验证 `_tools/qa/_check_cost_history.py`（红线：成本价只有一个写入口）。

## 为什么必须做
那条判据守的事**坏起来完全静默**：绕开 `record_cost` 直接 `product.cost_price = x`，
价格变了、区间表没变 —— "这段时间的成本价是多少"从此对不上账，
而**界面上一切正常**（商品卡显示的就是新价，只是历史少了一段、没人知道少的是哪段）。
本机新库、单测、真机点一遍，三种方式都测不出来。

所以逐条**注入真缺陷**，每条都必须让判据报红。

用法：python _tools/qa/_reverse_verify_cost_history.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_cost_history.py"

PRODUCTS = ROOT / "backend/app/api/v1/products.py"
INVENTORY = ROOT / "backend/app/api/v1/inventory.py"
SERVICE = ROOT / "backend/app/services/cost_history.py"

FLAT = '@router.get("/cost-history", response_model=list[ProductCostHistoryOut])'
PATH_ROUTE = '@router.get("/{product_id}", response_model=ProductOut)'


def _swap_route_order(s: str) -> str:
    """把两条路由的**声明顺序**对调（判据④要抓的就是这个）。"""
    if FLAT not in s or PATH_ROUTE not in s or s.index(FLAT) > s.index(PATH_ROUTE):
        return s
    return s.replace(FLAT, "@@FLAT@@", 1).replace(PATH_ROUTE, FLAT, 1).replace("@@FLAT@@", PATH_ROUTE, 1)


#: (说明, 目标文件, 替换函数)
CASES: list[tuple[str, Path, object]] = [
    (
        "建商品时不再开第一段成本价区间（「这个价从什么时候开始」从此没有起点）",
        PRODUCTS,
        lambda s: s.replace("record_cost(\n        db, p, p.cost_price,", "noop(\n        db, p, p.cost_price,", 1),
    ),
    (
        "进货带价不再写区间（毛利与成本价历史从此各说各的）",
        INVENTORY,
        lambda s: s.replace("        record_cost(\n            db,\n            product,", "        noop(\n            db,\n            product,", 1),
    ),
    (
        "record_cost 不再给旧区间收尾（时间轴上会同时有两段「生效中」）",
        SERVICE,
        lambda s: s.replace("        open_row.effective_to = at", "        pass", 1),
    ),
    (
        "record_cost 只记账、不真的改商品成本价",
        SERVICE,
        lambda s: s.replace("    product.cost_price = new_cost", "    pass", 1),
    ),
    (
        "有人绕开入口直接改成本价（区间表缺一段，而界面上看不出来）",
        PRODUCTS,
        lambda s: s.replace(
            "    cost_before = p.cost_price",
            "    cost_before = p.cost_price\n    p.cost_price = Decimal(\"0\")",
            1,
        ),
    ),
    (
        "路由顺序反了（`/cost-history` 被 `/{product_id}` 先接住 → 返回 422 而不是 404）",
        PRODUCTS,
        _swap_route_order,
    ),
]


def run(path: Path) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    code, out = run(CHECK)
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条判据就没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时判据是绿的")

    fails: list[str] = []
    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code2, _ = run(CHECK)
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        if code2 != 0:
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    if fails:
        print("\n❌ 反向验证没通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(CASES)}/{len(CASES)} 种破坏方式全部被抓到。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
