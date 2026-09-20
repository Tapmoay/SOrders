"""一次性报告：**反向验证脚本里的注入锚点还活着吗**（2026-09-21 加）。

## 为什么需要它（这不是理论问题）
反向验证靠"改坏一处 → 断言红线变红"证明判据有牙。可它的注入是**字面量替换**：
源码一改，那段字面量就对不上了 —— 此时脚本的行为是**安静地跳过**那一格
（`[SKIP] 原文出现 0 次` / `注入没生效`），于是那条红线**重新变成没有证据的断言**，
而整套检查照样全绿。本仓已经实测撞到 4 次：

| 脚本 | 腐烂的注入 | 怎么发现的 |
| --- | --- | --- |
| `_reverse_verify_catalog_and_scope.py` | OneShotSnackbar 顺序 | 2026-09-21 跑的时候报 `[MISS]` |
| `_reverse_verify_expense_page.py` | 设置页试听 | 同上 |
| `_reverse_verify_ledger_dashboard.py` | 共享阶梯 / 不许抢方向盘 ×2 | 同上（一次 30/33）|
| `_reverse_verify_order_return.py` | 两处（改名导致） | 我改代码时主动改的 |

## 为什么不用"跑一遍 --deep"来代替它
`python _tools/ai/_reverse_verify_all.py` 是权威判据（真跑真注入），但它要跑 **50 分钟以上**，
而且**跑的时候一个字都不能改源码**（它会注入、快照、还原；中途被杀会留下注入 ——
2026-09-21 实测杀了一次，留下 4 个带 bug 的文件）。所以它适合"改红线时专门跑一次"，
不适合天天跑。这个扫描器是它的**廉价预检**：只读源码、不动任何文件、秒级。

## 判据（宁可漏报，不要误报）
只用 AST 认**能确定**的两种形状（认不出就跳过，不猜）：
1. `(说明, PATH 常量, "旧串", "新串", 期望)` 这种 4/5 元组 —— 旧串就是锚点；
2. 元组第 3 项是 `sub("旧串", ...)` 调用，或 `lambda s: s.replace("旧串", ...)` —— 取那个字面量。
`PATH 常量` 只认模块级 `NAME = ROOT / "a/b"` 与 `NAME = HERE / "x.py"` 两种写法
（ROOT=仓库根、HERE=脚本自己的目录）。目标是 `.kt/.py/.json/.md/.vue/.ts` 才查。

用法：python _tools/qa/_scan_stale_anchors.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
TARGET_EXTS = {".kt", ".py", ".json", ".md", ".vue", ".ts", ".ps1", ".xml"}

#: 看着像正则的锚点（含这些转义/通配）→ 用 `re.search` 查，不按字面量查。
_LOOKS_RE = re.compile(r"\\\(|\\s|\\d|\\w|\[\^|\.\*|\\n\\s|\|")


def _join_str_parts(node: ast.AST) -> str | None:
    """把 `ROOT / "a" / "b"` 这种表达式里的字面量部分拼起来（认不出返回 None）。"""
    parts: list[str] = []
    cur: ast.AST | None = node
    while isinstance(cur, ast.BinOp) and isinstance(cur.op, ast.Div):
        if isinstance(cur.right, ast.Constant) and isinstance(cur.right.value, str):
            parts.insert(0, cur.right.value)
        else:
            return None
        cur = cur.left
    return "/".join(parts) if parts else None


def _path_map(tree: ast.Module, script_dir: Path) -> dict[str, Path]:
    """模块级 `NAME = ROOT / "…"` / `NAME = HERE / "…"` → 真实路径。"""
    out: dict[str, Path] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        val = node.value
        if not isinstance(val, ast.BinOp) or not isinstance(val.op, ast.Div):
            continue
        # 找最左边的基名
        base: ast.AST = val
        while isinstance(base, ast.BinOp):
            base = base.left
        if not isinstance(base, ast.Name):
            continue
        rel = _join_str_parts(val)
        if not rel:
            continue
        if base.id == "ROOT":
            out[tgt.id] = ROOT / rel
        elif base.id == "HERE":
            out[tgt.id] = script_dir / rel
    return out


def _as_anchor(node: ast.AST) -> tuple[str, bool] | None:
    """字面量 → (锚点文本, 是不是正则)。

    ⚠️ 两种锚点要分开判：**多行代码片段**是字面量（用 `in` 查），
    而 `re.sub(r"\\n\\s*ensure_alive\\(…", …)` 那种是**正则**（只能用 `re.search` 查）——
    第一版对后者一律按字面量查，于是把正则锚点全报成"腐烂"（会淹掉真问题）。
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        s = node.value
        return s, bool(_LOOKS_RE.search(s))
    return None


def _anchor_from_mutator(node: ast.AST) -> tuple[str, bool] | None:
    """从注入表达式里取锚点：`sub("旧", …)` / `lambda s: s.replace("旧", …)` / `re.sub(r"旧", …)`。"""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "sub" and node.args:
            return _as_anchor(node.args[0])
        return None
    if isinstance(node, ast.Lambda):
        for n in ast.walk(node.body):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in ("replace", "sub")
                and n.args
            ):
                got = _as_anchor(n.args[0])
                if got:
                    return got
    return None


def _resolve_target(node: ast.AST, pmap: dict[str, Path], script: Path) -> Path | None:
    """元组里那一项"目标文件"→ 真实路径（认不出来返回 None，不猜）。"""
    if isinstance(node, ast.Name):
        return pmap.get(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return ROOT / node.value          # 直接写仓库相对路径的那种（不少脚本这么写）
    if isinstance(node, ast.BinOp):
        rel = _join_str_parts(node)
        base: ast.AST = node
        while isinstance(base, ast.BinOp):
            base = base.left
        if rel and isinstance(base, ast.Name):
            if base.id == "ROOT":
                return ROOT / rel
            if base.id == "HERE":
                return script.parent / rel
    return None


def anchors_of(script: Path) -> list[tuple[str, bool, Path]]:
    tree = ast.parse(script.read_text(encoding="utf-8"))
    pmap = _path_map(tree, script.parent)
    found: list[tuple[str, bool, Path]] = []

    for node in ast.walk(tree):
        # 形状：(说明, 目标文件, "旧串"/sub("旧串"…)/lambda s: s.replace("旧串"…), …)
        if not (isinstance(node, ast.Tuple) and len(node.elts) >= 3):
            continue
        target = _resolve_target(node.elts[1], pmap, script)
        if target is None:
            continue
        anchor = _anchor_from_mutator(node.elts[2])
        if anchor is None:
            continue
        lit, is_re = anchor
        if lit:
            found.append((lit, is_re, target))
    return found


def main() -> int:
    scripts = sorted((ROOT / "_tools").rglob("_reverse_verify_*.py"))
    scripts = [p for p in scripts if p.name != "_reverse_verify_all.py"]
    if len(scripts) < 40:
        print(f"❌ 只扫到 {len(scripts)} 份反向验证（<40）：路径或 glob 坏了，停。")
        return 1

    n_anchor = 0
    n_checked = 0
    stale: list[tuple[str, str, Path, bool]] = []
    cache: dict[Path, str] = {}

    for s in scripts:
        try:
            items = anchors_of(s)
        except SyntaxError as e:
            print(f"  ⚠️ {s.name} 解析失败：{e}")
            continue
        for lit, is_re, target in items:
            n_anchor += 1
            if target in cache:
                text = cache[target]
            else:
                if not target.exists() or target.suffix.lower() not in TARGET_EXTS:
                    continue
                text = target.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n")
                cache[target] = text
            n_checked += 1
            if is_re:
                try:
                    alive = re.search(lit, text) is not None
                except re.error:
                    continue          # 正则本身写不通 → 不判（宁可漏报）
            else:
                alive = lit.replace("\r\n", "\n") in text
            if not alive:
                stale.append((s.name, lit[:70].replace("\n", "⏎"), target.relative_to(ROOT), is_re))

    print(f"扫到反向验证 {len(scripts)} 份；解析出锚点 {n_anchor} 个；能核对的 {n_checked} 个\n")
    if n_checked < 150:
        print(f"⚠️ 只核对了 {n_checked} 个锚点（<150）——**解析覆盖率太低，这份报告的说服力不足**，"
              "别把它当成\"全部锚点都活着\"的证明。")
    if not stale:
        print("✅ 解析到的锚点全部还在目标文件里（没发现腐烂的注入）")
        return 0
    print(f"❌ 有 {len(stale)} 个锚点**已经对不上目标文件**（那些注入此刻是静默跳过的）：")
    for name, lit, target, is_re in stale:
        kind = "正则" if is_re else "字面量"
        print(f"   · {name}（{kind}）\n       锚点：{lit}\n       目标：{target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
