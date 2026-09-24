"""反向验证 `_tools/qa/_check_cost_basis.py`（红线：毛利成本 = 入库加权平均进货价）。

## 为什么必须做

`_check_cost_basis.py` 守的四件事**坏起来全是静默的**（入库照样成功、毛利照样有数字、
本机新库照样跑），所以那条判据本身要是空转的，等于没有：

- 判据写成"文件里有没有 `unit_cost` 这个词" → 文档/注释里提一句就绿了；
- 判据只锚函数名 → 函数体里改回旧口径也绿；
- 判据漏了三级兜底那一句 → 删掉它（老数据毛利覆盖率归零）也绿。

所以这里逐条**注入真缺陷**，每条都必须让判据报红。注入点刻意选在
"旧判据（只 grep 关键词）看不到的地方"。

用法：python _tools/qa/_reverse_verify_cost_basis.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_cost_basis.py"

INV_API = ROOT / "backend/app/api/v1/inventory.py"
INV_SCHEMA = ROOT / "backend/app/schemas/inventory.py"
BOOTSTRAP = ROOT / "backend/app/core/schema_bootstrap.py"
BASIS = ROOT / "backend/app/services/cost_basis.py"
#: ⚠️ 2026-09-25 第 21 轮：成本/毛利的聚合**下沉到 service 层**了 —— 这一族的两条注入
#: （`basis.of(...)` 与货损快照）现在住在 `services/reports_service.py`。
#: ⛔ 注入必须打在**那段原文真正住着的文件**上，否则反向验证静默 SKIP（＝锚点腐烂，红线没有牙）。
REPORTS = ROOT / "backend/app/services/reports_service.py"
REPORT_SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"

BASIS_CALL = "cost, basis_src = basis.of(lp.product_id, lp.cost_price_snapshot)"

#: (说明, 目标文件, 替换函数)
CASES: list[tuple[str, Path, object]] = [
    (
        "入库的进货价不再写进流水（回到「只改商品成本价」—— 入库照常成功，毛利悄悄退回旧口径）",
        INV_API,
        lambda s: s.replace(
            "unit_cost=Decimal(body.unit_cost) if body.unit_cost is not None else None,",
            "unit_cost=None,",
            1,
        ),
    ),
    (
        "毛利改回读下单快照（进货价一涨、从旧库存出的货成本被按高价算）",
        REPORTS,
        lambda s: s.replace(BASIS_CALL, 'cost = lp.cost_price_snapshot or Decimal("0")', 2),
    ),
    (
        "老库不再补 unit_cost 列（本机新库照样跑，只有生产老库会炸）",
        BOOTSTRAP,
        lambda s: s.replace(
            'text("ALTER TABLE inventory_movements ADD COLUMN unit_cost NUMERIC(14,4)")',
            'text("SELECT 1")',
            1,
        ),
    ),
    (
        "出参不再带进货价（「成本从哪来」在 App 上看不见了）",
        INV_SCHEMA,
        lambda s: s.replace("unit_cost: Decimal | None = None", "unit_cost_hidden: Decimal | None = None", 1),
    ),
    (
        "第三级兜底被删（老数据没有进货价 → 历史报表的毛利覆盖率一夜变成 0）",
        BASIS,
        lambda s: s.replace(
            'return (snapshot or Decimal("0")), SNAPSHOT',
            'return Decimal("0"), SNAPSHOT',
            1,
        ),
    ),
    (
        "加权平均退化成算术平均（数量 3@10 与 4@20 会算成 15 而不是 15.7143）",
        BASIS,
        lambda s: s.replace(
            "func.sum(InventoryMovement.change * InventoryMovement.unit_cost)",
            "func.sum(InventoryMovement.unit_cost)",
            1,
        ),
    ),
    (
        "货损金额也改成均价口径（账本里那笔已入账的损失会和报表对不上）",
        REPORTS,
        lambda s: s.replace('snap = lp.cost_price_snapshot or Decimal("0")', "snap = cost", 2),
    ),
    (
        "报表页不再报口径（用户会以为整份毛利都已经是平均口径）",
        REPORT_SCREEN,
        lambda s: s.replace("data.costAvgLines, data.costSnapshotLines", "0, 0", 2),
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
        print(f"❌ 前提不成立：源码完好时这条判据就没过\n{out[-1500:]}")
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
            code2, out2 = run(CHECK)
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
