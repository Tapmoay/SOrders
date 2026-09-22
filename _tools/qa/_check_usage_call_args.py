"""红线：`usage_service` 那些调用的**实参**必须在所在函数里真的有定义。

## 为什么值得一条常驻检查（2026-09-22 真机踩出来的）
「挑东西的列表按常用度排」这一轮把 `with_popularity(stmt, Model, kind, <当前用户>)` 加到了
12 个挑单端点。那个第 4 个实参在大多数文件里叫 `current`，而**有 4 个端点的用户参数叫 `_` 或 `user`**
（`_: User = Depends(...)` 这种"只要鉴权、不要值"的老写法）→ 复制粘贴过去就成了：

    NameError: name 'current' is not defined

**这类 bug 编译期看不出来、单测也不一定盖到**：`python -m compileall` 只查语法，
而 `pytest` 没打到那个端点就一路绿。表现是**那个端点每次调用都 500**
（真机上是"运费模板页打不开/列表空"，看起来像网络问题）。
实测一次抓到 **4 处**：`arrears` / `driver_billing_rules` / `freight_templates` / `price_rules`。

## 判据（只认一条，但认得准）
对 `usage_service.<任何名字>(` 的每一次调用，把实参按顶层逗号切开，**凡是"裸标识符"**
（`current` / `user` / `Place` 这种，不是 `x.y`、不是字面量、不是调用）都必须在下面任一处有定义：
1. 所在函数的形参；
2. 本文件 import 进来的名字；
3. 本文件模块级定义的类/函数/变量；
4. 该函数体里**这一次调用之前**赋值过的局部名（`q = ...` 这种）。

⛔ 为什么不做成通用 linter：本机没装 `pyflakes`/`ruff`/`flake8`
（`python -m ruff` → No module named ruff），而给项目加一个新依赖要用户拍板。
所以这里只钉**这一类**（helper 的实参最容易复制粘贴错的那一族），并在下面守住"扫到的调用数"下限，
避免哪天调用全被删光、判据空转还报绿。

用法：python _tools/qa/_check_usage_call_args.py
配套：python _tools/qa/_reverse_verify_usage_call_args.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend" / "app"

#: 这一族的调用：`usage_service.xxx(`（常用度排序 / 记一次使用，全项目就这两类）
CALL = re.compile(r"\busage_service\.(\w+)\s*\(")
DEF = re.compile(r"^def\s+(\w+)\s*\((.*?)\)\s*(?:->[^:]*)?:", re.S | re.M)
BARE = re.compile(r"^[A-Za-z_]\w*$")
#: 扫到的调用数下限（防"调用全被删光 → 判据空转还报绿"）
MIN_CALLS = 12
#: 关键字实参名不算"要定义的名字"（`usage_service.record_usage(db, user=current)` 里 user= 是参数名）
KWARG = re.compile(r"^[A-Za-z_]\w*\s*=")


def read(p: Path) -> str:
    with io.open(p, "r", encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read()


def strip_comments(src: str) -> str:
    """去掉注释（保住行号）：注释里写着 `with_popularity(..., current)` 时不该被当成调用。"""
    out, i, n = [], 0, len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote:
            out.append(ch)
            if ch == "\\":
                out.append(src[i + 1] if i + 1 < n else "")
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#":
            while i < n and src[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def call_args(src: str, start: int) -> str:
    """从 [start] 处那个 `(` 起按括号配平取出实参。"""
    i = src.find("(", start)
    if i < 0:
        return ""
    depth = 0
    for j in range(i, len(src)):
        if src[j] in "([{":
            depth += 1
        elif src[j] in ")]}":
            depth -= 1
            if depth == 0:
                return src[i + 1:j]
    return src[i + 1:]


def top_level_parts(args: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in args:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def module_level_names(src: str) -> set[str]:
    """本文件"在模块一级绑定过"的名字：import 进来的 + 模块级的类/函数/变量。

    ⚠️ 必须认**多行 import**（`from app.models.x import (\\n    DriverBillingRule,\\n)`）：
    第一版只按行抓 `^from … import (.+)$`，于是那种写法里的名字一个都收不到 ——
    判据当场把 `driver_billing_rules.py` 的 `DriverBillingRule` 判成"没定义"（**假阳性**）。
    假阳性比漏报更耗人：下一个人会把判据关掉。
    """
    names: set[str] = set()
    for m in re.finditer(r"^import\s+([\w.]+)", src, re.M):
        names.add(m.group(1).split(".")[0])
    for m in re.finditer(r"^from\s+[\w.]+\s+import\s+", src, re.M):
        tail = src[m.end():]
        if tail.lstrip().startswith("("):
            tail = tail.lstrip()
            depth, block = 0, tail
            for j, ch in enumerate(tail):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        block = tail[1:j]
                        break
        else:
            block = tail.split("\n")[0]
        for piece in block.split(","):
            piece = piece.strip().strip("()").strip()
            if not piece or piece == "*":
                continue
            names.add(piece.split(" as ")[-1].strip())
    for m in re.finditer(r"^(?:class|def)\s+(\w+)", src, re.M):
        names.add(m.group(1))
    for m in re.finditer(r"^(\w+)\s*(?::[^=]+)?=", src, re.M):
        names.add(m.group(1))
    return names


def check_file(p: Path, c: Checker) -> int:
    raw = read(p)
    src = strip_comments(raw)
    rel = p.relative_to(ROOT).as_posix()
    mod = module_level_names(src)
    n = 0
    for m in CALL.finditer(src):
        n += 1
        args = call_args(src, m.end() - 1)
        heads = list(DEF.finditer(src[: m.start()]))
        if not heads:
            c.ok(f"{rel}:{raw[:m.start()].count(chr(10)) + 1} 这个调用在某个 def 里", False,
                 "找不到所在函数（判据要跟着搬）")
            continue
        head = heads[-1]
        params = set()
        for pp in head.group(2).split(","):
            pp = pp.strip()
            if not pp:
                continue
            params.add(pp.split(":")[0].split("=")[0].strip())
        body_before = src[head.end(): m.start()]
        fn = head.group(1)
        for a in top_level_parts(args):
            if KWARG.match(a):          # `user=current` 这种：键是形参名，不看
                continue
            if not BARE.match(a):       # `x.y` / 字面量 / 调用结果：不算
                continue
            bound = (a in params) or (a in mod) or re.search(rf"\b{re.escape(a)}\s*=", body_before)
            c.ok(f"{rel}:{fn}() 里 usage_service.{m.group(1)}(…) 的实参 {a!r} 有定义",
                 bool(bound),
                 f"{a!r} 既不是 {fn}() 的形参、也不是本文件 import/模块级/前面赋过的名字"
                 f" —— 这一调用**每次都会 NameError（端点 500）**，而且编译期看不出来")
    return n


def main() -> int:
    c = Checker()
    print("usage_service 调用的实参必须有定义（2026-09-22：一次抓到 4 处 NameError）")

    files = sorted((BACKEND / "api" / "v1").glob("*.py")) + sorted((BACKEND / "services").glob("*.py"))
    c.ok("扫到后端文件 ≥ 30 个（防目录搬走 → 判据空转）", len(files) >= 30, f"实际 {len(files)}")

    total = 0
    for p in files:
        total += check_file(p, c)

    c.ok(f"扫到的 usage_service 调用 ≥ {MIN_CALLS} 处（防调用被删光后判据空转）",
         total >= MIN_CALLS, f"实际 {total}")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：{total} 处 usage_service 调用的实参都在所在函数里有定义。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
