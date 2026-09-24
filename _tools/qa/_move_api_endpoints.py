#!/usr/bin/env python3
"""_move_api_endpoints.py —— 把 `api/v1/<源文件>.py` 里的一组函数**原样搬到**新模块（纯搬迁工具）。

### 为什么要写成工具（而不是手工剪切）

整改报告 §6 要求的是"纯搬迁"：URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变。
手工搬 2000 行的文件，靠的是**眼睛**；这个工具按 AST 找边界、按行原样切片 ——
搬过去的字节与原地一模一样，并且：

1. **只搬顶层函数块**（连同它上面的注释与装饰器），别的一行不碰；
2. **按用法剪裁 import**（每个新模块只留它正文里真的用到的名字，逐名剪 —— 见 `import_block`）；
3. **自动补跨模块 import**（`from app.api.v1.<源文件>_common import …`）；
4. **新模块自带 `router = APIRouter(prefix=…)`** —— 这一条是被实测逼出来的：
   共享一个 router 会让按文件解析的 AST 工具（`gen_endpoint_index` / `_gen_ai_read_catalog`）
   算不出 URL 前缀，**整批端点会从机器生成的索引里消失**；
5. 不碰 `api/v1/router.py`：挂载那一行由人写（那是个需要判断"顺序/前缀"的地方，工具不该猜）。

用法：
    python _tools/qa/_move_api_endpoints.py --from orders --to orders_payment \
        --funcs _payment_scoped_order,_reject_if_already_collected,pay_order,charge_order \
        --title "收款与现金" [--apply]

⚠️ 不改 `--from` 之外的文件；`--apply` 之前先把新模块打印出来看一眼。
搬完**必须**跑：`_tools/qa/_api_contract_snapshot.py --diff <搬之前> <搬之后>`（契约零差异才算数）。
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "backend" / "app" / "api" / "v1"


def rd(p: Path) -> str:
    return io.open(p, encoding="utf-8").read()


def wr(p: Path, text: str) -> None:
    io.open(p, "w", encoding="utf-8", newline="").write(text)


def block_range(lines: list[str], node) -> tuple[int, int]:
    """块范围（1-based 闭区间）：装饰器/def 往上吃掉连续注释行。"""
    first = node.decorator_list[0].lineno if node.decorator_list else node.lineno
    i = first - 1
    while i - 1 >= 0 and lines[i - 1].lstrip().startswith("#"):
        i -= 1
    return i + 1, node.end_lineno


def import_block(imports: list, body: str) -> str:
    """按**正文里真的用到**剪裁 import（逐名剪；`import a.b` 按顶层名判）。"""
    out: list[str] = []

    def used(name: str) -> bool:
        return re.search(r"(?<![A-Za-z0-9_.])" + re.escape(name) + r"(?![A-Za-z0-9_])", body) is not None

    for n in imports:
        if isinstance(n, ast.Import):
            keep = [(al.name, al.asname) for al in n.names if used(al.asname or al.name.split(".")[0])]
            for name, asname in keep:
                out.append("import " + name + (f" as {asname}" if asname else ""))
        elif isinstance(n, ast.ImportFrom):
            keep = [(al.name, al.asname) for al in n.names if used(al.asname or al.name)]
            if not keep:
                continue
            items = [name + (f" as {asname}" if asname else "") for name, asname in keep]
            one = f"from {n.module} import " + ", ".join(items)
            if len(one) <= 110:
                out.append(one)
            else:
                out.append(f"from {n.module} import (")
                out += [f"    {it}," for it in items]
                out.append(")")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="把一组端点原样搬到新模块（纯搬迁）")
    ap.add_argument("--from", dest="src", required=True, help="源模块名（不含 .py），如 orders")
    ap.add_argument("--to", dest="dst", required=True, help="新模块名，如 orders_payment")
    ap.add_argument("--funcs", required=True, help="逗号分隔的函数名（按源码顺序搬）")
    ap.add_argument("--title", default="", help="新模块的用途（写进 docstring）")
    ap.add_argument("--common", default="", help="跨模块助手的来源模块（默认 <src>_common）")
    ap.add_argument("--apply", action="store_true", help="真的写盘（默认只打印）")
    args = ap.parse_args(argv)

    src_path = API / f"{args.src}.py"
    dst_path = API / f"{args.dst}.py"
    common = args.common or f"{args.src}_common"
    src = rd(src_path)
    lines = src.split("\n")
    tree = ast.parse(src)
    nodes = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    want = [f.strip() for f in args.funcs.split(",") if f.strip()]
    missing = [f for f in want if f not in nodes]
    if missing:
        print(f"⛔ 源文件里没有这些函数：{missing}")
        return 2

    ranges = sorted((block_range(lines, nodes[f])[0], block_range(lines, nodes[f])[1], f) for f in want)
    imports = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    moved = "\n\n\n".join("\n".join(lines[a - 1:b]) for a, b, _ in ranges)
    router_line = next(l for l in lines if l.startswith("router = APIRouter("))
    covered = {i for a, b, _ in ranges for i in range(a, b + 1)}
    rest = "\n".join(l for i, l in enumerate(lines, 1) if i not in covered)

    common_names = []
    cpath = API / f"{common}.py"
    if cpath.exists():
        ctree = ast.parse(rd(cpath))
        for n in ctree.body:
            names = [n.name] if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) else (
                [t.id for t in n.targets if isinstance(t, ast.Name)] if isinstance(n, ast.Assign) else [])
            for nm in names:
                if re.search(r"(?<![A-Za-z0-9_.])" + re.escape(nm) + r"(?![A-Za-z0-9_])", moved):
                    common_names.append(nm)

    title = args.title or f"{args.src} 的一部分"
    new = (
        f'"""{title}（{args.dst}）—— 2026-09-24 整改阶段 4 **纯搬迁**的产物。\n\n'
        f"从 `api/v1/{args.src}.py` 原样搬来的 {len(want)} 个函数（{chr(44).join(want)}）。\n"
        "除代码组织外**一个字没改** —— URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变；\n"
        "证据：`_tools/qa/_api_contract_snapshot.py --diff <搬之前> <搬之后>` 契约零差异。\n\n"
        "⚠️ 本模块**自己声明** `router`：按文件解析的 AST 工具（端点索引 / AI 能力表）靠这一行算 URL 前缀。\n"
        '"""'
        + "\n\n" + import_block(imports, moved) + "\n"
        + (f"from app.api.v1.{common} import {common_names[0]}" if len(common_names) == 1 else
           (f"from app.api.v1.{common} import (" + ", ".join(common_names) + ")") if common_names else "")
        + "\n\n" + router_line + "\n\n\n" + moved.rstrip() + "\n"
    )

    print(f"源：{src_path.name}（{len(lines)} 行） → 新模块 {dst_path.name}：{len(new.splitlines())} 行")
    print(f"搬走：{want}")
    if common_names:
        print(f"从 {common} 导入：{common_names}")
    print(f"源文件还剩 {len(rest.splitlines())} 行")
    if not args.apply:
        print("\n（未加 --apply，什么都没写）")
        return 0
    if dst_path.exists():
        print(f"⛔ {dst_path.name} 已存在，拒绝覆盖")
        return 3
    wr(dst_path, new)
    wr(src_path, rest)
    print(f"✅ 已写出 {dst_path.name}，并瘦身 {src_path.name}")
    print("   下一步：在 api/v1/router.py 里 include 新 router（顺序/前缀要人判断）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
