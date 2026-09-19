"""红线：**计数列只能由数据库自增，不许 Python 读改写**（2026-09-19 审计，核心循环）。

## 由来
`products.stock`（库存）与 `place_user_usage.use_count` / `places.use_count` 都犯过同一个错：

```python
prod = db.get(Product, m.product_id)
prod.stock = (prod.stock or 0) + m.change      # ← 读改写（read-modify-write）
```

这是教科书级的 **lost update**：两个请求同时扣同一个商品（两张不同的单同时送达、
或"送达 × 派单员手工出库"）时，两边都读到同一个旧值、各自算出新值、**后写的人把前一个人的
减扣整段盖掉**。库存 100、两单各扣 3 → 最终 97 而不是 94，而且谁都不报错、日志里也看不出是哪两次。

同一形状还有更难看的一处：手工出库的"够不够扣"是 `check-then-act`（先读库存、算一遍、
再写回绝对值）→ **库存不足拦不住**：库存 10、两人同时出库 8、各自读到 10 都算出 2 ≥ 0，
都放行 → 一共出库 16，账面 2。

⚠️ **本机 SQLite 写是串行的，这个缝隙在本机根本测不出来**（和 §25 那批状态跃迁一样），
所以必须有一条**静态**判据盯着"写法本身"，而不是等本机跑出来。

## 判据（清单全部自己算）
1. **从 `backend/app/models/*.py` 自己算出「数值列」清单**（`Mapped[int|float|Decimal]` 且
   不是 Boolean）——只有这些列才有"计数/金额"语义；
2. 在这份清单上，`backend/app/**/*.py`（剥掉注释与文档字符串）里不许出现
   **"把同一对象的同一数值列读出来再写回"**的形状 `obj.col = ... obj.col ...`（[RMW]）。
   ⚠️ 判据必须先按**列类型**过滤再匹配：文本列的 `x.name = del_suffix(x.name)`、
   `notes = (notes or "") + "…"` 是另一码事（不是计数），把它们一起报出来的话，
   白名单会膨胀到十几条，判据就废了（"允许的例外比规则还多"＝没有规则）；
3. `products.stock` 特别条款：不许出现 `xxx.stock = ...` 赋值（库存是核心数，
   只能写成 `.values(stock=... + ...)` 这种 SQL 表达式）；有理由的例外写进 [ASSIGN_ALLOW]；
4. 反空转：整仓 `update(Product)` 与 `.values(stock=` 必须各有 ≥ 2 处，
   `values(use_count=` ≥ 2 处（两处库存消费点 + 两处地点计数都改成 SQL 表达式才可能满足）。

用法：python _tools/qa/_check_counter_updates.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_single_source import code_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"
MODELS = BACKEND / "models"

#: 「读同一列 → 写回同一列」：`obj.col = ... obj.col ...`
RMW = re.compile(r"\b(\w+)\.(\w+)\s*=\s*[^\n=]*\b\1\.\2\b")
#: `xxx.stock = ` 这种赋值（不含 `stock=` 关键字参数、也不含 `Product.stock + 1` 这类表达式）
STOCK_ASSIGN = re.compile(r"\b\w+\.stock\s*=(?!=)")
#: 模型里的数值列声明：`stock: Mapped[int] = mapped_column(Integer, ...)`
#: ⚠️ 两种写法都要认：① `mapped_column(Integer, …)` 显式给了类型；
#:    ② `mapped_column(default=1)` **不给类型**（靠注解 `Mapped[int]` 决定）。
#:    只认第 ① 种的话，`order_products.quantity` 这类列会漏在清单外 →
#:    "读改写"判据在那几列上静默失效（2026-09-19 实测：第一版就是这么漏的）。
NUMERIC_COL = re.compile(
    r"^\s*(\w+)\s*:\s*Mapped\[\s*(int|float|Decimal)\s*\]\s*=\s*mapped_column\(([^\n]*)",
    re.M,
)

#: 允许 `xxx.stock = ...` 的地方 → 理由（每条都要说清为什么不走 SQL 表达式）
ASSIGN_ALLOW: dict[str, str] = {}


def numeric_columns() -> set[str]:
    """从模型里算出「数值列」清单（Boolean 不算：布尔不是计数）。"""
    cols: set[str] = set()
    for f in sorted(MODELS.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        for m in NUMERIC_COL.finditer(src):
            name, _anno, args = m.group(1), m.group(2), m.group(3)
            if "Boolean" in args:
                continue
            cols.add(name)
    return cols


def main() -> int:
    fails: list[str] = []
    files = sorted(BACKEND.rglob("*.py"))
    if len(files) < 50:
        print(f"❌ 只扫到 {len(files)} 个后端文件——判据在空转，停。")
        return 1

    rmw_hits: list[str] = []
    stock_hits: list[str] = []
    srcs: dict[Path, str] = {}
    numeric = numeric_columns()
    print(f"模型里算出数值列 {len(numeric)} 个：{'、'.join(sorted(numeric))}")
    if len(numeric) < 20:
        fails.append(f"只认出 {len(numeric)} 个数值列（<20）——列清单解析失效，判据会静默变宽")
    for f in files:
        code = code_only(f.read_text(encoding="utf-8"))
        srcs[f] = code
        rel = str(f.relative_to(BACKEND)).replace("\\", "/")
        for m in RMW.finditer(code):
            if m.group(2) not in numeric:
                continue  # 文本列的拼接/改名不是计数，不归这条判据管
            line_no = code[: m.start()].count("\n") + 1
            rmw_hits.append(f"{rel}:{line_no} {m.group(0).strip()[:70]}")
        for m in STOCK_ASSIGN.finditer(code):
            line_no = code[: m.start()].count("\n") + 1
            if rel not in ASSIGN_ALLOW:
                stock_hits.append(f"{rel}:{line_no} {m.group(0).strip()[:40]}")

    print(f"扫了 {len(files)} 个文件")
    for h in rmw_hits:
        print(f"   · [读改写] {h}")
    for h in stock_hits:
        print(f"   · [库存赋值] {h}")

    if rmw_hits:
        fails.append(
            "这些地方把同一列读出来又写回（并发下必然 lost update，谁都不报错）："
            + "；".join(rmw_hits[:6])
        )
    if stock_hits:
        fails.append(
            "这些地方用赋值改库存（应当写成 SQL 表达式 `.values(stock=... + delta)`）："
            + "；".join(stock_hits[:6])
        )

    # ---- 反空转：原子写法必须真的在用 ----
    counts = {}
    for name, pat in (
        ("update(Product)", r"update\(Product\)"),
        (".values(stock=", r"\.values\(stock="),
        (".values(use_count=", r"\.values\(use_count="),
    ):
        n = sum(len(re.findall(pat, code)) for code in srcs.values())
        counts[name] = n
        print(f"   `{name}` {n} 处")
    for name, low in (("update(Product)", 2), (".values(stock=", 2), (".values(use_count=", 2)):
        if counts[name] < low:
            fails.append(
                f"`{name}` 只有 {counts[name]} 处（<{low}）——原子写法没被真正接线，判据在空转"
            )

    if len(ASSIGN_ALLOW) > 2:
        fails.append(f"「允许赋值改库存」的白名单有 {len(ASSIGN_ALLOW)} 条（上限 2）——变长说明有地方在绕开判据")

    if fails:
        print("\n❌ 计数列的写法被破坏：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ 库存与计数列都由数据库自增，没有读改写。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
