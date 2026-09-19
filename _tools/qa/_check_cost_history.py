"""红线：**成本价的改动只有一条路**，而且它的历史必须跟着一起写。

## 由来（用户 2026-09-19）

> 「那个成本价去做一个保留…**这个保留是跟着他的账本走的**。如果成本价发生了变化，
>   就直接变化成本价就可以了，这样子我们就好溯源。而且我们保留的时候不仅保留成本价，
>   还保留这个成本价存在的时间，从什么时候开始变、从什么时候结束的，**精确到小时和分钟**。」

于是有了 `product_cost_history`（**生效区间**表）。它的正确性只依赖一件事：
**`products.cost_price` 的每一个写入口都走 `services/cost_history.record_cost`**
（它同时补旧区间的尾巴、插新区间、写 `products.cost_price`）。

## 为什么必须是静态判据

绕开它直接 `product.cost_price = x` 的后果**完全静默**：
价格变了、区间表没变 —— 于是"这段时间的成本价是多少"从此对不上账，
而**界面上一切正常**（商品卡显示的就是新价，价格历史少了一段而没人知道少的是哪段）。
本机新库、单测、真机点一遍，**三种方式都测不出来**。

## 判据（先剥注释再匹配，免得被自己文档里的反例喂饱）

1. `backend/app/**` 里除了 `services/cost_history.py` **不许**出现 `X.cost_price = …` 赋值；
2. 三个写入口必须真的调了 `record_cost(`（建商品 / 进货带价 / 编辑里改）；
3. `record_cost` 必须真的做那两件事（补旧区间 `effective_to`、插新行）；
4. 路由顺序：`/cost-history` 必须在 `/{product_id}` **之前**声明
   （Starlette 按声明顺序匹配，反了会返回 **422 而不是 404**，看起来像"参数填错了"）；
5. 反空转：`record_cost(` 的调用点 ≥3 处。

用法：python _tools/qa/_check_cost_history.py
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
SERVICE = BACKEND / "services/cost_history.py"

#: `xxx.cost_price = …`（赋值，不是关键字参数 `cost_price=`）
ASSIGN = re.compile(r"\b\w+\.cost_price\s*=(?!=)")
MIN_CALLS = 3

#: 允许赋值的地方 → 理由（按**匹配到的那一小段代码**索引，不是按文件 —— 按文件会把整个文件放开）。
ASSIGN_ALLOW: dict[str, str] = {
    "out.cost_price =": (
        "`products.py::product_out` 的**出参按角色裁剪**：非派单员的 `cost_price` 一律置 None"
        "（2026-09-19 审计 R12-H1：原来无条件下发，货主与司机都能读到进价）。"
        "它改的是 Pydantic 出参对象，**不是 `products` 那一列**。"
    ),
}


def main() -> int:
    fails: list[str] = []
    py = sorted(BACKEND.rglob("*.py"))
    if len(py) < 50:
        print(f"❌ 只扫到 {len(py)} 个后端文件 —— 判据在空转，停。")
        return 1

    hits: list[str] = []
    for f in py:
        rel = str(f.relative_to(BACKEND)).replace("\\", "/")
        if rel == "services/cost_history.py":
            continue  # 唯一允许赋值的地方（它就是那个入口）
        src = code_only(f.read_text(encoding="utf-8"))
        for m in ASSIGN.finditer(src):
            line = src.splitlines()[src[: m.start()].count("\n")].strip()
            # 有理由的例外按**那一小段代码**放行（按文件放行会把整个文件都放开）
            if any(snippet in line for snippet in ASSIGN_ALLOW):
                continue
            hits.append(f"{rel}:{src[: m.start()].count(chr(10)) + 1} {m.group(0)}")

    print(f"扫了 {len(py)} 个后端文件（另有 {len(ASSIGN_ALLOW)} 条书面例外）")
    for h in hits:
        print(f"   · [直接改成本价] {h}")
    if hits:
        fails.append(
            "这些地方直接给 cost_price 赋值（成本价区间表会缺一段，而且看不出来）："
            + "；".join(hits[:6])
            + "。改用 services/cost_history.record_cost(...)。"
        )

    svc = code_only(SERVICE.read_text(encoding="utf-8"))
    # ---- ② record_cost 必须真的做那两件事 ----
    if "open_row.effective_to = at" not in svc:
        fails.append("record_cost 没有给旧区间补上 effective_to（时间轴会同时有两段「生效中」）")
    if "ProductCostHistory(" not in svc:
        fails.append("record_cost 没有插入新区间")
    if "product.cost_price = new_cost" not in svc:
        fails.append("record_cost 没有写 products.cost_price（那这个入口就只是记账、没真改价）")

    # ---- ③ 三个写入口都接了 ----
    calls = 0
    for rel in ("api/v1/products.py", "api/v1/inventory.py"):
        src = code_only((BACKEND / rel).read_text(encoding="utf-8"))
        n = len(re.findall(r"\brecord_cost\(", src))
        calls += n
        print(f"   {rel}：record_cost( {n} 处")
    if calls < MIN_CALLS:
        fails.append(
            f"`record_cost(` 只被调了 {calls} 处（<{MIN_CALLS}）：建商品 / 进货带价 / 编辑里改"
            "三个入口，少一个就会缺一段成本价历史"
        )

    # ---- ④ 路由顺序 ----
    # ⚠️ 必须**剥掉注释**再找：这个文件的注释里就写着 `@router.get("/{product_id}")` 这个名字
    #    （解释为什么顺序不能反）—— 不剥的话判据会被自己的文档骗到，得出"顺序反了"的假结论
    #    （第一版就是这么写的，当场红了一次）。
    prod = code_only((BACKEND / "api/v1/products.py").read_text(encoding="utf-8"))
    i_flat = prod.find('@router.get("/cost-history"')
    i_path = prod.find('@router.get("/{product_id}"')
    if i_flat < 0 or i_path < 0:
        fails.append("products.py 里找不到 /cost-history 或 /{product_id} 路由（清单过期了？）")
    elif i_flat > i_path:
        fails.append(
            "`/cost-history` 声明在 `/{product_id}` **之后** —— Starlette 按声明顺序匹配，"
            "那样 `GET /products/cost-history` 会被 `/{product_id}` 接住并返回 **422**"
            "（不是 404，看起来像参数填错了）。把 flat 那条往上挪。"
        )

    if fails:
        print("\n❌ 成本价的改动没有一个统一入口：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ 成本价只有一个写入口（record_cost），三个入口都接了，历史与价格同事务。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
