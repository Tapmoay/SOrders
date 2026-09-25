#!/usr/bin/env python3
"""_check_business_transactions.py —— 跨域事务地图与真实调用图的逐条对账（第二轮 R2-03）。

### 为什么需要它（指南 §六）
指南说这一轮要把「现在散落在 service 中的**隐式协作**变成**显式业务契约**」，
每条事务都要写清：谁负责？什么时候发生？是否同一个 DB transaction？失败怎么办？重复执行怎么办？

⛔ 但一张**没人核对**的事务地图就是散文：写的时候是真的，改完代码就没人再读它。
所以这一条判据把它钉在**真实调用图**上 —— 地图上写的每个参与者，
都必须在入口函数的调用链里**真的被调到**（AST 解析，跨文件、跨模块）。

### 判据
1. 入口（entry）与每个参与者都是真实存在的 `模块:函数`；
2. ⭐ **可达性**：每个参与者都必须能从入口沿调用链走到；
3. ⭐ **同一事务**：声明 `same_db: yes` 的事务，入口那个模块里必须有 db.commit()；
4. ⭐ **守卫机制**：声明的 `guards` 必须在可达代码里找得到对应形状；
5. 每条事务必须写清 `failure` / `repeat` / `why`（≥12 字）；
6. 反空转：事务条数、函数数、调用边数都要达标。

用法：python _tools/qa/_check_business_transactions.py [--check] [--show <事务名>]
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _domain_map as dm  # noqa: E402

DOC = ROOT / "docs/BUSINESS_TRANSACTION_MAP.md"
APP = ROOT / "backend/app"

MIN_TXNS = 10
MIN_FUNCS = 400
MIN_CALL_EDGES = 800
MIN_TEXT = 12

BLOCK_RE = re.compile(r"(?ms)^```txn[ \t]*$(.*?)^```[ \t]*$")
REQUIRED_KEYS = ("name", "中文名", "entry", "participants", "same_db", "guards", "failure", "repeat", "why")

#: 守卫机制词表 → 判定它「真的在」的正则。判据是在**入口可达的那些函数体**里找这个形状。
#: ⛔ 只放函数体里能锚到的机制。第一版把 `unique_index`（表上的唯一约束）也放进来，
#:    而那时是在**整个可达模块的源码**里找 —— 于是连 `models/__init__.py` 里那句
#:    `UniqueConstraint` 导入都算命中，等于没查。表级约束不属于「这条事务的守卫」，
#:    要写就写进散文（**判据做不到的事就不要假装做得到**）。
GUARD_SHAPES: dict[str, str] = {
    "row_lock": r"lock_order_row\(|with_for_update\(",
    "cas": r"db\.execute\(\s*update\(",
    "outbox_same_txn": r"outbox\.enqueue\(|enqueue\(",
    "soft_delete": r"is_deleted|deleted_at",
}


#: 节点/被调的路径口径 = **相对 `backend/`**（与 `dm.dotted_to_rel` 一致）。
#: ⚠️ 第一版写成相对 `app/`，于是 `dotted_to_rel("app.api.v1…")` 返回的键（`app/api/…`）
#: 与图里的键（`api/…`）对不上，十条事务全报「入口函数不存在」—— 两张图的键必须同一套口径。
BACKEND = ROOT / "backend"


def module_of(path: Path) -> str:
    return path.relative_to(BACKEND).as_posix()


def file_of(key: str) -> Path:
    return BACKEND / key.split(":")[0]


def _imports(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """文件里「本地名字 → (app 内相对路径, 符号名或空串)」。

    ⚠️ **必须把符号名一起记下来**（第一版只记了模块路径，当场被自己的判据抓到）：
    `from app.services.order_flow import assign_driver` 之后调的是裸名 `assign_driver(...)`，
    只记路径的话这条边会落成「import 了整个模块」—— 于是十条事务的参与者**全部**报
    「入口的调用链里走不到它」，而代码明明是对的。**错的是判据，不是代码。**
    """
    out: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
            target = dm.dotted_to_rel(node.module or "")
            if target is None:
                continue
            for a in node.names:
                sub = dm.dotted_to_rel((node.module or "") + "." + a.name)
                out[a.asname or a.name] = (sub or target, "" if sub else a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("app"):
                    t = dm.dotted_to_rel(a.name)
                    if t:
                        out[a.asname or a.name.split(".")[-1]] = (t, "")
    return out


def build_graph() -> tuple[dict[str, set[str]], int, int]:
    """(调用图 「模块:函数」→ 被调集合, 函数数, 边数)。

    ⚠️ 解析三种写法：裸名（同模块的函数）、from X import f 之后 f()、
    以及 from app.core import outbox 之后 outbox.enqueue()（属性调用）。
    少了第三种，发件箱那条边会整条消失 —— 而「事件与业务同一个事务」正是它要证的事。
    """
    files = sorted(APP.rglob("*.py"))
    per_file: dict[str, tuple[ast.Module, dict[str, str]]] = {}
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        per_file[module_of(f)] = (tree, _imports(tree))

    graph: dict[str, set[str]] = {}
    #: key → (文件相对路径, 起行, 止行)：守卫检查只在**函数体**里找，不再读整份文件。
    spans: dict[str, tuple[str, int, int]] = {}
    n_func = 0
    for mod, (tree, imports) in per_file.items():
        local = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            n_func += 1
            key = mod + ":" + node.name
            spans[key] = (mod, node.lineno, node.end_lineno or node.lineno)
            callees = graph.setdefault(key, set())
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                fn = call.func
                if isinstance(fn, ast.Name) and fn.id in local:
                    callees.add(mod + ":" + fn.id)
                elif isinstance(fn, ast.Name) and fn.id in imports:
                    tgt, sym = imports[fn.id]
                    callees.add(tgt + ":" + (sym or fn.id))
                elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                    hit = imports.get(fn.value.id)
                    if hit:
                        callees.add(hit[0] + ":" + fn.attr)
    edges = sum(len(v) for v in graph.values())
    return graph, n_func, edges, spans


def _forward_contract(graph: dict[str, set[str]]) -> int:
    """把「经由钱契约取的符号」解开到**真正的实现**上（PEP 562 惰性转出）。

    ⚠️ 为什么必须解开：`api/v1/orders_return.py` 写的是
    `from app.services.money_contract import return_order` —— 这正是指南 §五 要的
    「消费方依赖接口，不依赖实现」。但调用图上它落在**契约**那个节点上，
    而真正做事的函数在 `order_return.py`：不解开，参与者就报「走不到」。
    解开之后这张图证明的正是那件事：**依赖指向契约，而执行落在实现**。
    """
    sys.path.insert(0, str(ROOT / "backend"))
    from app.services.money_contract import REEXPORTS  # noqa: PLC0415

    contract = dm.dotted_to_rel("app.services.money_contract")
    rewrite: dict[str, str] = {}
    for sym, (mod, name) in REEXPORTS.items():
        target = dm.dotted_to_rel(mod)
        if target and contract:
            rewrite[contract + ":" + sym] = target + ":" + name
    n = 0
    for src, callees in graph.items():
        for c in list(callees):
            if c in rewrite:
                callees.discard(c)
                callees.add(rewrite[c])
                n += 1
    return n


def reachable(graph: dict[str, set[str]], start: str) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        for nxt in graph.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def parse_txns(text: str) -> tuple[list[dict], list[str]]:
    out: list[dict] = []
    bad: list[str] = []
    for m in BLOCK_RE.finditer(text):
        d: dict = {}
        for line in m.group(1).splitlines():
            if not line.strip():
                continue
            k, sep, v = line.partition(":")
            if not sep or not k.strip():
                bad.append(line.strip()[:60])
                continue
            d[k.strip()] = v.strip()
        out.append(d)
    return out, bad


def main() -> int:
    args = sys.argv[1:]
    check_mode = "--check" in args
    show = args[args.index("--show") + 1] if "--show" in args else ""

    text = DOC.read_text(encoding="utf-8")
    txns, unparsed = parse_txns(text)
    graph, n_func, n_edges, spans = build_graph()
    n_fwd = _forward_contract(graph)

    def body_of_key(key: str) -> str:
        """这个函数自己的源码（按 AST 的行号切片）—— 守卫检查只看它。"""
        span = spans.get(key)
        if span is None:
            return ""
        mod, lo, hi = span
        lines = file_of(key).read_text(encoding="utf-8").splitlines()
        return chr(10).join(lines[lo - 1:hi])

    fails: list[str] = []
    passed = 0

    if unparsed:
        fails.append("这些行不是 `键: 值` 的形状：" + "、".join(unparsed))
    else:
        passed += 1
    if len(txns) < MIN_TXNS:
        fails.append(f"只登记到 {len(txns)} 条事务（<{MIN_TXNS}）—— 地图缩水了？")
    else:
        passed += 1
    if n_func < MIN_FUNCS:
        fails.append(f"只解析出 {n_func} 个函数（<{MIN_FUNCS}）—— 调用图解析坏了")
    else:
        passed += 1
    if n_edges < MIN_CALL_EDGES:
        fails.append(f"只解析出 {n_edges} 条调用边（<{MIN_CALL_EDGES}）—— 调用图解析坏了")
    else:
        passed += 1

    if show:
        t = next((x for x in txns if x.get("name") == show), None)
        if t is None:
            print("没有这条事务：" + show)
            return 1
        mod, _, fn = t["entry"].partition(":")
        key = (dm.dotted_to_rel("app." + mod) or "") + ":" + fn
        r = reachable(graph, key)
        print("入口 " + key + " 的可达集合（" + str(len(r)) + " 个）：")
        for x in sorted(r):
            print("   " + x)
        return 0

    for t in txns:
        nm = t.get("name", "?")
        miss = [k for k in REQUIRED_KEYS if k not in t]
        if miss:
            fails.append(f"事务 {nm} 缺字段：" + "、".join(miss))
            continue
        if t["same_db"] not in ("yes", "no"):
            fails.append(f"事务 {nm} 的 same_db 只能是 yes / no")
        for k in ("failure", "repeat", "why"):
            if len(t[k].strip()) < MIN_TEXT:
                fails.append(f"事务 {nm} 的 {k} 太短（<{MIN_TEXT} 字，等于没写）")

        mod, _, fn = t["entry"].partition(":")
        target = dm.dotted_to_rel("app." + mod) if mod else None
        if target is None:
            fails.append(f"事务 {nm} 的入口模块不存在：{t['entry']}")
            continue
        entry_key = target + ":" + fn
        if entry_key not in graph:
            fails.append(f"事务 {nm} 的入口函数不存在：{t['entry']}")
            continue

        refs = dm.split_list(t["participants"])
        keys: list[str] = []
        for ref in refs:
            why = dm.command_problem(ref)
            if why:
                fails.append(f"事务 {nm} 的参与者 {ref} 对不上代码：{why}")
                continue
            m2, _, f2 = ref.partition(":")
            keys.append((dm.dotted_to_rel("app." + m2) or "?") + ":" + f2)

        reach = reachable(graph, entry_key)
        for ref, key in zip(refs, keys):
            if key not in reach:
                fails.append(f"事务 {nm} 声明了参与者 {ref}，但入口的调用链里**走不到它**")

        entry_src = file_of(entry_key).read_text(encoding="utf-8")
        if t["same_db"] == "yes" and "db.commit()" not in entry_src:
            fails.append(f"事务 {nm} 声明 same_db=yes，但入口那个模块里没有 db.commit()（谁提交的？）")

        blob = chr(10).join(body_of_key(k) for k in sorted(reach))
        for g in dm.split_list(t["guards"]):
            shape = GUARD_SHAPES.get(g)
            if shape is None:
                fails.append(f"事务 {nm} 的守卫 {g} 不在词表里：" + "、".join(sorted(GUARD_SHAPES)))
            elif re.search(shape, blob) is None:
                fails.append(f"事务 {nm} 声明有守卫 {g}，但可达代码里找不到对应形状")
    if not fails:
        passed += 1

    print(f"跨域事务：{len(txns)} 条 / 调用图 {n_func} 个函数 {n_edges} 条边 / 经由钱契约转发的调用 {n_fwd} 处")
    if fails:
        for f in fails:
            print("  ❌ " + f)
        return 1
    if check_mode:
        print("  ✅ 全部通过")
    else:
        print(f"  ✅ {passed} 组判据全部通过：每条事务的参与者都在入口的调用链里真的被调到、"
              "提交点只有一个、声明的守卫机制在代码里找得到、失败与重复执行都写了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
