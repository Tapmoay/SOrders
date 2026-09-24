"""红线：**毛利成本 = 入库流水的加权平均进货价**（2026-09-19 用户要求）。

## 由来（用户原话）

> 「他那个毛利率会做一个计算的…他不是有那个入库记录吗？不能这么算啊，这么算的话，
>   毛利率会偏低啊。所以要分开来，算毛利率的话，我们可以算一个平均的成本，
>   也就是说在单位时间内的平均成本」

改之前：毛利成本 = 订单行的 `cost_price_snapshot` = **下单那一刻的最新进货价**。
进货价一涨，从旧库存出的货就被按新的高价算成本 → 毛利偏低。

改之后：`services/cost_basis.py` 是**唯一实现**（期间均价 → 累计均价 → 下单快照三级兜底）。

## 为什么必须有这条静态判据

这一整套东西**坏起来是完全静默的**：

| 坏法 | 界面上看起来 |
|---|---|
| `create_movement` 又不把进货价写进流水（回到"只改商品成本价"） | 入库照常成功、库存照常加，**只是毛利又退回旧口径** |
| 报表改回读 `cost_price_snapshot` | 毛利数字照常有，只是系统性偏低（没有报错、没有第二处能对上） |
| `schema_bootstrap` 少了那条 ALTER | 本机新库照样跑（`create_all` 建的新表自带这一列），**只有老库会炸** |
| 三级兜底里的第三级被删掉 | 老数据（一条进货价都没有）的毛利覆盖率**一夜之间变成 0** |

前三种在**本机 SQLite 新库**上都测不出来（和 `_check_counter_updates.py` 那批并发缺陷同一个形状），
所以必须有一条**静态**判据盯着"写法本身"。

## 判据（全部先剥注释与文档字符串再匹配，免得被自己文档里的"反例"喂饱）

1. **进货价真的落库**：模型有列、老库有迁移、写端点把它写进行对象、出参带出来；
2. **毛利成本只有一个来源**：`reports.py` 必须调 `CostBasis.of(...)`（两个聚合函数各一次），
   且**不许**再出现老写法 `cost = lp.cost_price_snapshot`；
3. **三级兜底都在**：`PERIOD` / `CUMULATIVE` / `SNAPSHOT` 常量 + `of()` 里第三级的真实现；
4. **口径必须说到用户面前**：`cost_avg_lines` / `cost_snapshot_lines` 要一路走到
   后端出参 → 出参 schema → Android DTO → 报表页文案（否则用户会以为整份毛利都已经是平均口径）；
5. **货损仍走快照**（`lp.cost_price_snapshot` 在 reports.py 里还在用）——
   它在送达那一刻就已经按快照写进开销账与现金流水，追溯改成均价会让账本和报表各说一套。

用法：python _tools/qa/_check_cost_basis.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import reports_source  # noqa: E402
from _check_single_source import code_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

#: 「口径要说到用户面前」的两种写法：后端是 snake_case，Kotlin 是 camelCase
BASIS_FIELDS = {
    "cost_avg_lines": "costAvgLines",
    "cost_snapshot_lines": "costSnapshotLines",
}


def read(p: Path) -> str:
    return code_only(p.read_text(encoding="utf-8"))


def main() -> int:
    fails: list[str] = []

    inv_model = read(BACKEND / "models/inventory.py")
    inv_api = read(BACKEND / "api/v1/inventory.py")
    inv_schema = read(BACKEND / "schemas/inventory.py")
    bootstrap = read(BACKEND / "core/schema_bootstrap.py")
    basis = read(BACKEND / "services/cost_basis.py")
    reports = reports_source(ROOT)
    report_schema = read(BACKEND / "schemas/reports.py")
    dto = read(ANDROID / "data/remote/dto/Dtos.kt")
    report_screen = read(ANDROID / "ui/dispatcher/ReportCenter.kt")

    # ---- ① 进货价真的落在流水上（四段链路缺一段都不算）----
    for label, src, needle in (
        ("模型有 unit_cost 列", inv_model, "unit_cost: Mapped[Decimal | None]"),
        ("写端点把进货价写进流水行", inv_api, "unit_cost=Decimal(body.unit_cost)"),
        ("出参带 unit_cost（成本从哪来看得见）", inv_schema, "unit_cost: Decimal | None = None"),
        ("老库有补列迁移", bootstrap, "ALTER TABLE inventory_movements ADD COLUMN unit_cost"),
    ):
        if needle not in src:
            fails.append(f"{label} —— 没找到 `{needle}`")

    # ---- ② 毛利成本只有一个来源 ----
    calls = reports.count("basis.of(lp.product_id, lp.cost_price_snapshot)")
    print(f"reports.py 里 `basis.of(...)` 调用 {calls} 处（营业纵览 + 商品经营各一处）")
    if calls < 2:
        fails.append(
            f"reports.py 只有 {calls} 处 `basis.of(...)`（<2）——"
            "有一个聚合函数没走 cost_basis，两页毛利会走散"
        )
    if "cost = lp.cost_price_snapshot" in reports:
        fails.append(
            "reports.py 里又出现了 `cost = lp.cost_price_snapshot` ——"
            "那正是被废止的旧口径（进货价一涨、从旧库存出的货毛利就偏低）"
        )

    # ---- ③ 三级兜底都在 ----
    for name in ("PERIOD", "CUMULATIVE", "SNAPSHOT"):
        if f'{name} = "' not in basis:
            fails.append(f"cost_basis.py 少了 `{name}` 这一级常量")
    if 'return (snapshot or Decimal("0")), SNAPSHOT' not in basis:
        fails.append(
            "cost_basis.of() 的**第三级兜底**（退回下单快照）不见了 ——"
            "`unit_cost` 是后加的列、老数据一条都没有，删了它历史报表的毛利会全部变成 0"
        )

    # ---- ④ 货损仍走快照（改了它就和开销账对不上）----
    snaps = reports.count("lp.cost_price_snapshot")
    print(f"reports.py 里 `lp.cost_price_snapshot` 出现 {snaps} 处（2 处传给 CostBasis + 2 处货损）")
    if snaps < 4:
        fails.append(
            f"reports.py 里 `lp.cost_price_snapshot` 只有 {snaps} 处（<4）——"
            "货损金额应当仍是快照口径（它对应开销账里那笔**已经入账**的钱）"
        )

    # ---- ⑤ 口径必须说到用户面前 ----
    for label, src, camel in (
        ("后端出参", reports, False),
        ("出参 schema", report_schema, False),
        ("Android DTO", dto, True),
        ("报表页文案", report_screen, True),
    ):
        for snake, camel_name in BASIS_FIELDS.items():
            if (camel_name if camel else snake) not in src:
                fails.append(f"{label} 没有 {camel_name if camel else snake} —— 用户看不到「这份毛利有多少行是平均口径」")
    if "入库" not in report_screen:
        fails.append("报表页的口径说明里没有提到成本来自**入库**流水")

    # ---- 反空转 ----
    if "func.sum(InventoryMovement.change * InventoryMovement.unit_cost)" not in basis:
        fails.append("cost_basis.py 里的**加权**求和不见了（判据在空转）")
    if "ROUND_HALF_UP" not in basis:
        fails.append("cost_basis.py 没有量化平均价 —— 会带出 28 位商，导出到 Excel 里是个怪物数字")

    if fails:
        print("\n❌ 毛利成本口径被破坏：")
        for f in fails:
            print("   - " + f)
        return 1
    print(
        "\n✅ 成本口径只有一处实现：进货价落在流水上、毛利用加权平均进货价、"
        "三级兜底都在，且口径说明到了用户面前。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
