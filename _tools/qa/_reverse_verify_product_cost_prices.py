#!/usr/bin/env python
"""反向验证 _tools/qa/_check_product_cost_prices.py（FEAT-0025：商品可以有多个成本价）。

为什么非得有它：这一族**坏起来全是安静的** —— 把默认口径改成按第二个成本价算、把软删改成真删、
把同名 upsert 拆了、把 AI 动作摘掉、把卡片里的「改前」抹掉、把界面上那句钱的口径改词……
**没有一条会报错**，用户看到的是一张漂亮的卡和一个照常出数的报表。
所以这里故意把源码一件一件弄坏，一条一条喂给判据：每条都必须让它**当场变红**，改完再逐字节还原。

R4-BOUNDARY-JUSTIFICATION: 本脚本只改**附加口径这一族的实现与界面**（后端那一格默认口径的取值、
软删/同名判定、Kotlin 处理器与数据源、界面弹层、一句话的文案），不碰数据库结构、
不动 orders 与 ledgers 的字段、不改权限。它验证的那条判据也在同一层（附加口径有没有越过边界去算钱）；
越界是**读**出来的，不是**写**出来的 —— 所以只能靠在源码里注入来验，不能靠表约束。

⚠️ 注入锚点必须唯一（count != 1 就原样返回，末尾会报「注入没生效」），否则等于没注入。
⚠️ 每条跑完立刻 write_bytes 还原，末尾再逐字节核对一遍。

用法：python _tools/qa/_reverse_verify_product_cost_prices.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_product_cost_prices.py"

BACKEND = ROOT / "backend/app"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

F_ORDER = BACKEND / "services/order_flow.py"
F_PROFIT = BACKEND / "services/reports/product_query.py"
F_TURNOVER = BACKEND / "services/reports/turnover_query.py"
F_API = BACKEND / "api/v1/products.py"
F_MODEL = BACKEND / "models/product.py"
F_CP = AND / "ai/AiWriteCostPrices.kt"
F_AW = AND / "ai/AiWrite.kt"
F_SVC = AND / "ai/AiWriteService.kt"
F_SHEET = AND / "ui/dispatcher/ProductCostPriceSheet.kt"
F_SCREEN = AND / "ui/dispatcher/ProductFormScreen.kt"
F_GUARD = ROOT / "_tools/ai/_check_ai_guardrails.py"


def sub(old: str, new: str) -> Callable[[str], str]:
    def f(s: str) -> str:
        if s.count(old) != 1:
            return s
        return s.replace(old, new, 1)
    return f


def sub_all(old: str, new: str) -> Callable[[str], str]:
    def f(s: str) -> str:
        if old not in s:
            return s
        return s.replace(old, new)
    return f


CASES: list[tuple[str, Path, Callable[[str], str]]] = [
    ("⛔ 把默认口径改成按「第二个成本价」算（下单定格改读附加口径）",
     F_ORDER, sub('cost_snap = prod.cost_price or Decimal("0")',
                  'cost_snap = _extra_cost(prod) or Decimal("0")')),
    ("⛔ 毛利聚合改读附加口径（报表照出数，口径却不是真实成本价）",
     F_PROFIT, sub("basis.of(lp.product_id, lp.cost_price_snapshot)",
                   "basis.of(lp.product_id, lp.extra_cost_price)")),
    ("⛔ 附加口径表飘进营业额报表（越界扫描要拦住它）",
     F_TURNOVER, sub("cost, basis_src = basis.of(",
                     "ProductCostPrice\n        cost, basis_src = basis.of(")),
    ("⛔ 默认那条不再取自商品的 cost_price（界面那句话指向了别的数）",
     F_API, sub("cost_price=p.cost_price,", 'cost_price=Decimal("0"),')),
    ("软删改成真删（用户 2026-09-20 的硬规矩：删了必须能拿回来）",
     F_API, sub("cost_row.is_deleted = True", "db.delete(cost_row)")),
    ("同名不再 upsert（改价变成插第二条）",
     F_API, sub("cost_row = _cost_row_by_name(db, product_id, body.name)", "cost_row = None")),
    ("改名撞了别的活行也不再拒绝（同名可以重复）",
     F_API, sub("if clash is not None and clash.id != cost_row.id:", "if False:")),
    ("数据库层也不再保证同名唯一（唯一约束被摘掉）",
     F_MODEL, sub('UniqueConstraint("product_id", "name", name="uq_product_cost_price_product_name")',
                  'Index("ix_product_cost_price_dummy", "product_id")')),
    ("列表只给默认那条（参考口径一条都不列）",
     F_API, sub("items = [_cost_price_out(r) for r in db.scalars(q)]", "items = []")),
    ("AI 动作里去掉「设置成本价口径」（AI 又设不了第二条了）",
     F_CP, sub("        setAction(),\n", "")),
    ("AI 动作没并入总表（模型根本看不到这三条）",
     F_AW, sub("AiWriteCostPrices.ACTIONS", "emptyList()")),
    ("写调用挪进 prepare（预览阶段就落库 —— 卡片还没点，行已经动了）",
     F_CP, sub_all("override suspend fun prepare(params: JsonObject): AiWriteOutcome {",
                   "override suspend fun prepare(params: JsonObject): AiWriteOutcome {\n        ds.deleteProductCostPrice(0L)")),
    ("handler 没注册（动作在清单里，点下去没人接）",
     F_SVC, sub("SetCostPriceHandler(ds, store),", "")),
    ("默认口径名改成另一个字面量（App 与后端从此各说一个名字）",
     F_CP, sub('DEFAULT_COST_PRICE_NAME = "真实成本价"', 'DEFAULT_COST_PRICE_NAME = "实际成本"')),
    ("卡片丢掉改前的数（只说改成什么，不说原来多少）",
     F_CP, sub_all("金额：原来：", "金额：现在：")),
    ("默认那条被当成参考口径处理（护栏认不出默认口径）",
     F_CP, sub_all(".filter { !it.isDefault }", ".filter { false }")),
    ("护栏白名单里去掉这两个读方法（prepare 一读就被判成写）",
     F_GUARD, sub('"productCostPrices", "deletedProductCostPrices",', "")),
    ("回收站里没有「恢复」入口（删了就真拿不回来了）",
     F_SHEET, sub("{ onRestore(row.id) }", "{ }")),
    ("商品表单页那句「钱的口径」被改词（最关键的提示没了）",
     F_SCREEN, sub("订单与毛利算账用的那个", "成本价")),
]


def run_check() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    print("反向验证 _tools/qa/_check_product_cost_prices.py（FEAT-0025）")
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据就是红的 —— 先修绿再谈反向验证")
        print(out[-3000:])
        return 2
    print("✅ 前提成立：判据在完好源码上是绿的")

    fails: list[str] = []
    originals: dict[Path, bytes] = {}
    print("")
    print("== 注入 " + str(len(CASES)) + " 条：每条都必须让判据当场变红 ==")
    for label, path, mutate in CASES:
        if path not in originals:
            originals[path] = path.read_bytes()
        original_bytes = originals[path]
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        mutated = mutate(original)
        if mutated == original:
            fails.append("注入没生效（锚点不唯一或已过期，请更新本脚本）：" + label)
            print("⚠️  注入没生效：" + label)
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code2, out2 = run_check()
        finally:
            path.write_bytes(original_bytes)
        if path.read_bytes() != original_bytes:
            fails.append("还原后与快照不一致 —— 注入污染了源码树：" + label)
        if code2 != 0:
            print("✅ 注入「" + label + "」→ 判据报红")
        else:
            fails.append("注入之后没有报红 —— 这条判据是空转的：" + label)
            print("❌ 注入「" + label + "」→ 判据没反应")
            print(out2[-1500:])

    dirty = [str(p.relative_to(ROOT)) for p, b in originals.items() if p.read_bytes() != b]
    print("")
    print("逐字节还原核对：动过 " + str(len(originals)) + " 个文件，脏 = " + str(len(dirty)))
    for d in dirty:
        print("⚠️  " + d)
        fails.append("文件没有逐字节还原：" + d)

    if fails:
        print("")
        for f in fails:
            print("❌ " + f)
        print("")
        print("❌ 反向验证不完整：" + str(len(CASES) - len(fails)) + " / " + str(len(CASES)) + " 条注入被抓")
        return 1
    print("")
    print("✅ " + str(len(CASES)) + " 条注入全部被拦住，且源码树逐字节还原")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
