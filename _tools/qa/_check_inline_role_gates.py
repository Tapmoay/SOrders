#!/usr/bin/env python3
"""体内角色门槛：**只许降不许升**（棘轮）—— 目标是全部收敛到签名级 `Depends(require_roles(...))`。

## 为什么要有这一条
报告 §9 要求权限只有**一个统一模型**：授权写在**入口**（函数签名上的 Depends），
而不是散在**函数体**里的 `if 角色 != X: raise 403`。体内门槛有两个真实后果：

1. 端点索引（`docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md`）的「授权」列只能写出
   「仅登录 + 体内仅允许:派单员」—— **机器读不出真实授权**。想知道"这个接口谁能调"
   必须人肉读函数体；AI 读能力裁剪（`_tools/ai/_gen_ai_read_catalog.py`）也只能靠猜。
2. 同一段两行判断在几十处各抄一遍，**抄漏一处就是一个越权口子**，而当时的判据
   只看得到"有没有登录"，看不见这个差别。

⚠️ 实证（2026-09-25）：往 `expense_categories.py` 一个端点体内加回一段真实的角色门槛，
`_check_permission_model.py` 仍然 8/8 全绿 —— 当时**没有任何判据抓得住它**。这一条就是补这个洞。

## 为什么是棘轮而不是"必须为 0"
有一类门槛**依赖请求内容**，签名级表达不了，例如：
- `GET /users/{id}`：要么是派单员、要么是你自己；
- `GET /orders?deleted_only=`：这个查询参数只有派单员能用。
这类要么改成"读参数的 Depends"，要么就得留在体内。所以判据定成棘轮：
**上限只许改小**，每轮收敛一个域，数字跟着降。

## 什么时候删掉这一条
当 `HISTORY` 里最后一个计数降到 0（全部收敛完）时，把本判据**改成绝对判据**
（体内门槛必须为 0）、删掉 `MAX_INLINE_GATES` / `HISTORY` 与这段棘轮说明。
在那之前，它的价值就是"不许长回来"。

## 判据口径（认代码形状，不认文字）
`backend/app/api/**/*.py` 里，被 `@router.<verb>` 装饰的处理函数体内，
**由角色/权限比较决定**的 `raise HTTPException(401/403)` 记为一处。
⛔ 不 raise 的角色分支（数据范围裁剪，如 `if role == DRIVER: 只看自己`）**不是**门槛；
⛔ 不由角色决定的 403（如「这张单不是你的」）也**不是**。
这两条由 `_reverse_verify_inline_role_gates.py` 的两个「必须仍然绿」用例钉着。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
API_DIR = ROOT / "backend/app/api"
ENUMS = ROOT / "backend/app/models/enums.py"

HISTORY: list[tuple[str, int, str]] = [
    ("2026-09-25", 44, "首次建账：§9 第②步收敛 expense_categories 时的全库实测（13 个文件）"),
    ("2026-09-25", 41, "§9 第②步第二域：cash_flows 3 个端点收到签名级 DispatcherUser（13→12 个文件）"),
]
"""计数台账（日期, 处数, 说明）。**逐条不增**；不减的那一条必须带「理由:」并写清为什么。

为什么要有台账而不是只留一个上限：只留一个 `MAX_INLINE_GATES` 的话，
"棘轮被绕过"的方式就是**把上限自己调大**（一次编辑、判据全绿、谁也不会注意到）。
台账把这件事变成"要往回填一个更大的数字"，而"不增"这条判据会当场拦下它。
"""

MAX_INLINE_GATES = HISTORY[-1][1]
"""棘轮上限 = 台账最后一条。**不要手写数字**，改数字请往 HISTORY 追加一条。"""

CONVERTED: dict[str, str] = {
    "app/api/v1/expense_categories.py":
        "2026-09-25 §9 第②步第一域：5 个端点全部收到签名级 DispatcherUser，体内 0 处",
    "app/api/v1/cash_flows.py":
        "2026-09-25 §9 第②步第二域：3 个端点全部收到签名级 DispatcherUser，体内 0 处",
}
"""已经收敛完的文件：体内角色门槛必须为 **0**（防"改完又长回来"）。"""

MIN_HANDLERS = 60
"""扫描到的路由处理函数下限 —— 低于它说明 AST 扫描坏了。

「算不出真值＝红」：一个扫不到东西的检查会永远绿，那是这个仓库栽过 5 次的坑
（清单手写 / 扫描器静默返回空），所以这里钉一个下限（实测 225 个，留足余量）。
"""

MIN_REASON = 12
"""台账说明的字数下限（防"理由：无"这种敷衍）。"""

VERBS = {"get", "post", "put", "patch", "delete"}
HELPERS = {
    "user_role_key",
    "role_has_permission",
    "has_permission",
    "_has_permission",
    "current_role",
    "require_roles_if",
}
"""判"这个 if 是不是在按角色/权限决定"的函数名。加大于删：认不出＝少报＝棘轮失效。"""


def role_literals() -> set[str]:
    """从 `enums.py` 里解析 UserRole 的取值（**不 import** —— 免得依赖 sys.path 与运行环境）。"""
    tree = ast.parse(ENUMS.read_text(encoding="utf-8"))
    out: set[str] = set()
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "UserRole"]:
        for stmt in cls.body:
            value = stmt.value if isinstance(stmt, (ast.Assign, ast.AnnAssign)) else None
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                out.add(value.value)
    return out


def is_route(fn: ast.AST) -> bool:
    for d in getattr(fn, "decorator_list", []):
        node = d.func if isinstance(d, ast.Call) else d
        if isinstance(node, ast.Attribute) and node.attr in VERBS:
            return True
    return False


def status_node(call: ast.Call) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == "status_code":
            return kw.value
    return call.args[0] if call.args else None


def is_401_or_403(node: ast.expr | None) -> bool:
    if isinstance(node, ast.Attribute):
        return "403" in node.attr or "401" in node.attr
    if isinstance(node, ast.Constant):
        return node.value in (401, 403)
    return False


def role_decided(test: ast.expr, literals: set[str]) -> bool:
    for n in ast.walk(test):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in HELPERS:
            return True
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "UserRole":
            return True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in literals:
            return True
    return False


def scan() -> tuple[list[tuple[str, str, int]], int]:
    """返回（体内角色门槛清单, 路由处理函数总数）。"""
    literals = role_literals()
    hits: list[tuple[str, str, int]] = []
    handlers = 0
    for path in sorted(API_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        rel = path.relative_to(ROOT / "backend").as_posix()
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            if not is_route(fn):
                continue
            handlers += 1
            parents: dict[ast.AST, ast.AST] = {}
            for parent in ast.walk(fn):
                for child in ast.iter_child_nodes(parent):
                    parents[child] = parent
            for node in ast.walk(fn):
                if not isinstance(node, ast.Raise) or node.exc is None:
                    continue
                call = node.exc if isinstance(node.exc, ast.Call) else None
                if call is None or not (isinstance(call.func, ast.Name) and call.func.id == "HTTPException"):
                    continue
                if not is_401_or_403(status_node(call)):
                    continue
                cur: ast.AST | None = node
                while cur is not None and cur is not fn:
                    if isinstance(cur, ast.If) and role_decided(cur.test, literals):
                        hits.append((rel, fn.name, node.lineno))
                        break
                    cur = parents.get(cur)
    return hits, handlers


def check_history() -> list[str]:
    """台账自身：非增、有理由、说明不敷衍。"""
    fails: list[str] = []
    for i, (day, count, why) in enumerate(HISTORY):
        if len(why.strip()) < MIN_REASON:
            fails.append(f"台账第 {i + 1} 条（{day}）的说明只有 {len(why.strip())} 个字（下限 {MIN_REASON}）——"
                         "等于没写，下一个人看不出这个数字是怎么来的")
        if i == 0:
            continue
        prev_day, prev = HISTORY[i - 1][0], HISTORY[i - 1][1]
        if count > prev and "理由:" not in why:
            fails.append(f"台账第 {i + 1} 条（{day}）从 {prev} 涨到 {count} 却没写「理由:」——"
                         "棘轮不许悄悄松掉，涨就要写明为什么、什么时候能降回去")
    return fails


def main() -> int:
    fails: list[str] = []
    hits, handlers = scan()
    by_file: dict[str, list[str]] = {}
    for rel, name, ln in hits:
        by_file.setdefault(rel, []).append(name + ":" + str(ln))

    print(f"体内角色门槛：{len(hits)} 处 / {len(by_file)} 个文件（棘轮上限 {MAX_INLINE_GATES}，"
          f"路由处理函数 {handlers} 个）")

    # ① 棘轮：只许降不许升
    if len(hits) > MAX_INLINE_GATES:
        fails.append(
            f"体内角色门槛涨到 {len(hits)} 处（上限 {MAX_INLINE_GATES}）：新增的必须写成"
            "签名级 Depends(require_roles(...))，别在函数体里再抄一遍 if 角色 != X: raise 403"
        )
        for rel in sorted(by_file):
            print("     " + str(len(by_file[rel])).rjust(2) + "  " + rel)

    # ② 已收敛的文件必须归零（防回退）
    for rel, why in sorted(CONVERTED.items()):
        if not (ROOT / "backend" / rel).exists():
            fails.append(f"清单里的 {rel} 不存在了（清单化石）—— 路径写错或文件被挪走，先修清单")
            continue
        left = by_file.get(rel, [])
        if left:
            fails.append(f"{rel} 声明已收敛（{why}），但体内还有 {len(left)} 处：" + "、".join(left))

    # ③ 扫描没空转（"算不出真值＝红"）
    if handlers < MIN_HANDLERS:
        fails.append(f"只扫到 {handlers} 个路由处理函数（下限 {MIN_HANDLERS}）——"
                     "AST 扫描坏了或 API 目录被挪走，这条判据此刻不作数")

    # ④ 台账自身（防"把上限自己调大"绕过棘轮）
    fails.extend(check_history())

    print()
    if fails:
        for f in fails:
            print("❌ " + f)
        print(f"❌ 体内角色门槛：{len(fails)} 条不成立")
        return 1
    print("  ✅ 4 组判据全部通过：总数没超棘轮上限、已收敛文件体内归零、"
          "清单没有化石、台账非增且有理由、扫描没空转。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
