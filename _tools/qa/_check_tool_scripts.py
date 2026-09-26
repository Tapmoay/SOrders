#!/usr/bin/env python3
"""_check_tool_scripts.py —— `_tools/**/*.py` 自己的健康度（进 `_check_all.py` 自动跑）。

### 为什么值得单列一条判据（两件事都是 2026-09-25 CI 第一次拿到真实日志时暴露的）

**① 一个工具脚本坏掉了整整几轮，没有任何检查发现。**
`_tools/baseline/_capture_baseline.py` 的 `except OSError:` 块体被一次编辑「换成了注释」，
整个文件 `IndentationError` —— 也就是说阶段 0 的基线采集工具**根本跑不起来**。
为什么没人发现：Fast Gate 的语法检查是 `python -m compileall -q backend/app backend/scripts`，
**只 compile `backend/`**，`_tools/` 从来没被编译过；而它又不是 `_check_*.py`，不进必跑组。
→ 所以这里把「每个工具脚本都能被 AST 解析」变成一条判据。

**② 反向验证里写死了本机路径，于是它在 CI 上是死的。**
CI 报「3 条注入的锚点已经失效（这些反向验证现在是恒 SKIP 的）」，目标路径写着
`D:\\AProjects\\ASDH\\orders/backend/...` —— 在 CI 的 `/home/runner/work/...` 上根本找不到那个文件。
比红糟得多：那 3 条注入**永远不生效**，而本机因为那个目录真的存在，永远看不出来。
同族 4 处（`_verify_ast.py` / `_reverse_verify_multi_request.py` /
`_probe_security_round5.py` / `_reverse_verify_loop_e2e.py`）：**本机全绿、CI 全死**。

### 判据（两条，都是「要么对要么错」，没有需要解释的例外）

**A. 可解析性**：`_tools/**/*.py` 每一个都能 `ast.parse`（BOM 用 `utf-8-sig` 读）。

**B. 不许写死「本仓库的检出位置」**（可执行字符串常量里）。判的是两件事：
   · 路径里出现了**与本仓库同名的那一层目录**（`ROOT.name`，即检出目录名）；
   · 或出现了**别人家目录**（`Users/<名字>/`、`/home/<名字>/`，CI 自己的 runner 不算）。

为什么只判这两条、而不是「所有 Windows 绝对路径」：
`D:\\APPS\\sdk\\platform-tools\\adb.exe`、`C:\\Program Files\\Git\\bin\\bash.exe`、
`D:\\APPS\\AndroidStudio\\jbr`、`D:\\omap-tiles` 这些是**外部工具/数据装在哪**，
与「仓库在哪」是两件事，而且 `adb` 实测不在 PATH 上（改成 `shutil.which()` 会当场失效）。
把它们一并判红只会逼出一张豁免表 —— 而豁免表恰恰是本项目反复吃过亏的东西。
反过来，「仓库在哪」**没有任何正当理由**要写死：永远可以从 `__file__` 推。

⛔ 判的是 **AST 里的字符串常量**，不是整份文本：`#` 注释里正好写着「⛔ 不许写死 `D:\\...`」
这种**反面教材**不该被判红（`_reverse_verify_multi_request.py` 顶上就有一处）。
docstring 同理（那里的用法示例常常正是劝人别这么写的段落）。

用法：python _tools/qa/_check_tool_scripts.py            # 打印明细
      python _tools/qa/_check_tool_scripts.py --check    # 非零退出＝有问题
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "_tools"

#: 扫描下限：只是防「扫错目录了还报绿」，**不是**「文件数不许减少」（删工具是正常的）。
MIN_FILES = 200

#: Windows 盘符绝对路径。前面那个 (?<![A-Za-z0-9]) 挡掉 http:// / socks5h:// 这类假阳性
#: （`p:/` 前面是字母）；`[^\s]*` 只是让匹配止于空白，路径本身不做语法解析。
WIN_PATH = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]):[\\/][^\s]*")

#: 会打 ✅/❌ 的脚本**必须能把它们打出来**：要么自己 `reconfigure`，要么 import `_airepo`（它顺手设了 stdout）。
#: ⛔ 2026-09-26 实测事故：`_reverse_verify_shipper_settle_ceiling.py` 两样都没有 —— 在 GBK 控制台/管道下
#: 打第一个 ✅ 就 `UnicodeEncodeError` 崩掉（EXIT=1、4 秒），看着像「反向验证跑过了」，其实**一条都没验**。
MARKS = ("\u2705", "\u274c")

#: 别人家目录（CI 自己的 /home/runner/ 不算）。
HOME_DIR = re.compile(r"[\\/](?:Users|home)[\\/]([A-Za-z0-9._-]+)")


def segments(text: str) -> list[str]:
    return [s for s in re.split(r"[\\/]+", text) if s]


def why_offence(text: str) -> str | None:
    """返回犯规原因；不是犯规就返回 None。"""
    for s in segments(text):
        if s == ROOT.name:
            return f"写死了本仓库的检出目录 {ROOT.name}"
    m = HOME_DIR.search(text)
    if m and m.group(1) != "runner":
        return f"写死了别人家目录（{m.group(1)}）"
    return None


def provides_encoding(path: Path, seen: set[Path] | None = None, depth: int = 3) -> bool:
    """这个脚本（**或它 import 的本仓库模块**）有没有把 stdout 设成 UTF-8。

    ⛔ 必须跟着 import 走：`_check_shipper_settle_ceiling.py` 自己一个 `reconfigure` 都没有，
    但它 `from _check_pagination_wiring import …`，而那一份会 import `_airepo`（顺手设了 stdout）——
    只看本文件会**虚报**（实测第一版就虚报了 5 份）。判据读宽了与读窄了同样糟。
    """
    seen = seen if seen is not None else set()
    if path in seen or depth < 0:
        return False
    seen.add(path)
    try:
        src = path.read_bytes().decode("utf-8-sig")
    except OSError:
        return False
    if "reconfigure" in src or "_airepo" in src:
        return True
    for m in re.finditer(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", src, re.M):
        name = m.group(1).split(".")[0]
        for cand in (path.parent / (name + ".py"), TOOLS / "ai" / (name + ".py")):
            if cand.is_file() and provides_encoding(cand, seen, depth - 1):
                return True
    return False


def docstrings(tree: ast.AST) -> set[int]:
    """收集 docstring 那些字符串节点的 id（判据要跳过它们，理由见文件头）。"""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        b = getattr(node, "body", None) or []
        if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) \
                and isinstance(b[0].value.value, str):
            out.add(id(b[0].value))
    return out


def main() -> int:
    files = sorted(p for p in TOOLS.rglob("*.py") if "__pycache__" not in p.parts)
    broken: list[str] = []
    offences: list[str] = []
    noenc: list[str] = []
    seen = 0

    for p in files:
        rel = str(p.relative_to(ROOT))
        try:
            src = p.read_bytes().decode("utf-8-sig")
            tree = ast.parse(src)
        except SyntaxError as exc:
            broken.append(f"{rel}:{exc.lineno}  {str(exc)[:100]}")
            continue
        if any(mk in src for mk in MARKS) and not provides_encoding(p):
            noenc.append(rel)
        skip = docstrings(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in skip:
                continue
            for m in WIN_PATH.finditer(node.value):
                seen += 1
                why = why_offence(m.group(0))
                if why:
                    offences.append(f"{rel}:{node.lineno}  {m.group(0)[:90]}  —— {why}")

    print(f"扫了 {len(files)} 个 _tools/**/*.py；其中 Windows 绝对路径字面量 {seen} 处"
          "（外部工具/数据的位置不判红，只看有没有把**本仓库在哪**写死）")
    for e in offences[:30]:
        print("  ⛔ " + e)
    if len(offences) > 30:
        print(f"  …… 还有 {len(offences) - 30} 处")
    for b in broken[:20]:
        print("  ⛔ 解析不了（这个工具根本跑不起来）  " + b)
    for r in noenc[:10]:
        print("  ⛔ 会打 ✅/❌ 却没法把它们打出来（没 reconfigure、也没 import _airepo）  " + r)

    problems: list[str] = []
    if broken:
        problems.append(f"{len(broken)} 个工具脚本解析不了（语法错/缩进错 —— 它们整个跑不起来）")
    if offences:
        problems.append(f"{len(offences)} 处把**本仓库的检出位置**写死了"
                        "（本机跑得通、CI 上那个文件不存在 → 反向验证会变成恒 SKIP）")
    if noenc:
        problems.append(f"{len(noenc)} 个脚本会打 ✅/❌ 却没法把它们打出来"
                        "（GBK 控制台/管道下会 UnicodeEncodeError——看着跑过了，其实没验）")
    if len(files) < MIN_FILES:
        problems.append(f"只扫到 {len(files)} 个文件（< {MIN_FILES}）—— 判据可能扫错目录了")

    if problems:
        for x in problems:
            print("  ❌ " + x)
        print("  修法：根目录从 __file__ 推（Path(__file__).resolve().parents[N]），"
              "或直接用 _tools/ai/_airepo.py::repo_root()。")
        return 1
    print(f"  ✅ {len(files)} 个工具脚本全部可解析，且没有一处把**本仓库在哪**写死。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())