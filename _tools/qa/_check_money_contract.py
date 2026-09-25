#!/usr/bin/env python3
"""_check_money_contract.py —— 「钱只有一个实现」的**显式契约**判据（整改报告 §7）。

### 为什么要有它
报告 §7 的原话是：**「不要碰它」不是架构。** 这个项目现在靠 `_core_files.txt` 把几个钱模块冻起来 ——
方法是对的，但它只保证「没人改」，不保证「没人**另算一遍**」：

```text
以前：谁想用就 import 文件 → 靠 freeze 保证
以后：Domain Contract → 接口 → 唯一实现 → 所有消费方依赖接口
```

于是 `backend/app/services/money_contract.py` 把每个「钱数」声明成一条契约
（口径 / 唯一实现站点 / 消费方），这一页负责**逐条核对声明与源码是否一致** ——
声明是文档，判据才是边界。

### 判据
1. 契约条目 / 模式 / 消费方的**数量下限**（少了说明契约被掏空，而不是「没问题」）；
2. 每条实现站点 `文件::符号` 都存在，且**那个文件里真的定义了这个符号**（AST）；
3. 每个声明的消费方**真的 import 了那条实现**（假消费方比漏写更糟：它让人以为那处在走契约）；
4. **实现区之外**不许出现「自己又算一遍」的写法（每条模式都带一句「为什么它是重复实现」）；
5. `ALLOWED` 例外必须**仍然命中**（不再命中的豁免是化石，会让人以为这里有洞）；
6. 契约模块自己**一行算术都没有**（接口里藏实现 = 又长出第二个实现点）。

### 第 ② 步（2026-09-25 第 23 轮）：消费方依赖**接口**，不依赖实现
报告要的是「所有消费方依赖接口」。契约里有 `REEXPORTS`（**惰性**转出实现符号），于是第 7/8/9 条：

7. `REEXPORTS` 里每个符号**真的取得到**，而且它的 `__module__` 就是**声明的那条实现** ——
   防的是「契约里又抄了一份实现」（那样接口就成了第二个实现点，比不改还糟）；
8. 每个声明的消费方必须**从契约** `import` 那条契约的符号（不是从实现模块），
   于是「钱只有一处实现」变成**一条 import 语句**就能看出来的事；
9. `app/` 里**不许**再从实现模块 import 这些符号（实现文件自己、以及 `PENDING` 里写明理由的除外）。

用法：
    python _tools/qa/_check_money_contract.py --check   # 非零退出＝有问题
    python _tools/qa/_check_money_contract.py           # 打印逐条明细
"""

from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
APP = ROOT / "backend" / "app"
CONTRACT_REL = "services/money_contract.py"
CONTRACT = APP / CONTRACT_REL

MIN_FIGURES = 5
MIN_PATTERNS = 6
MIN_CONSUMERS = 10
MIN_REEXPORTS = 12

#: ⚠️ 还没改过来的消费方 → 理由。**必须仍然命中**（不命中＝化石，报红），
#: 也就是「等它落地后必须把这条例外删掉」，而不是让它悄悄留着。
#: ✅ 2026-09-25 清空：原来那 2 条（`api/v1/reports.py` / `services/reports_service.py`）写的是
#:    「正在被另一个会话下沉成 service、尚未提交，改了会把两个会话的改动搅在一起」——
#:    **那个下沉早就落地并提交了**，所以这两处消费方现在也指到契约，例外随之删掉。
#:    ⚠️ 清空不是形式主义：判据第 ⑨ 条「`app/` 里不许再从实现模块 import 契约符号」在
#:    `PENDING` 非空时对这两条是**放行**的 —— 表一空，那条判据才真正对全仓生效。
PENDING: dict[str, str] = {}

#: 允许出现在实现区之外的写法 → 理由。⚠️ 每条都要说清「为什么它不是第二个实现」，
#: 而且**必须仍然命中**（不命中的豁免会变成化石，让人以为这里有洞）。
ALLOWED: dict[tuple[str, str], str] = {
    ("services/stats_service.py", "line_total_arith"): (
        "报表层的**营业额聚合**（按商品/按天把已送达订单的行金额加起来）—— 与 OrderMoney.total 同源、"
        "粒度不同：它回答「这段时间卖了多少」，不回答「这一单还欠多少」，也不参与核销与催收。"
        "⚠️ 这条豁免是**看得见**的：改到这里就会报出来。"
    ),
}


def code_only(src: str) -> str:
    """剥掉**所有字符串常量与注释**，但**保留行号**（判据报的位置必须是真的）。

    ⚠️ 用 AST 而不是正则：正则会被三引号与转义骗过去，而本项目已经栽过两次 ——
    一次是注释里写着「这里原来是无条件赋值」被判成「谁在写这个字段」，
    一次是行尾注释里的 REFUND_CUSTOMER 被判成「谁在写退款」。

    ⚠️ 也**不能**用 `ast.unparse()` 再扫：那会把代码压成一行，报出来的行号全是假的
    （第一版就是这么写的，于是「stats_service.py:58」指的其实是原文件 115 行）。
    这里把字符串区间**原地涂成空格**（保留换行），行号因此与源文件逐行对齐。
    """
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    starts: list[int] = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))

    def char_col(lineno: int, byte_col: int) -> int:
        """AST 的列号是 **UTF-8 字节偏移**，而这个文件里满是中文 —— 必须换算成字符偏移。"""
        raw = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        return len(raw.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))

    chars = list(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            end_line = node.end_lineno or node.lineno
            a = starts[node.lineno - 1] + char_col(node.lineno, node.col_offset)
            b = starts[end_line - 1] + char_col(end_line, node.end_col_offset or 0)
            for i in range(a, min(b, len(chars))):
                if chars[i] != "\n":
                    chars[i] = " "
    out = "".join(chars)
    # 字符串已经清空 → 这个正则不会咬到字符串里的 `#`（颜色值那种）
    return re.sub(r"(?m)#.*$", "", out)


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8", errors="replace").read()


def defines(path: Path, symbol: str) -> bool:
    try:
        tree = ast.parse(read(path))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            return True
    return False


def imports_of(path: Path) -> set[tuple[str, str]]:
    """{(模块尾名, 符号)} —— 这个文件从 app.services.* 里 import 了什么。"""
    try:
        tree = ast.parse(read(path))
    except SyntaxError:
        return set()
    out: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.module == "app.services":
            # `from app.services import supplier_service`（模块对象）—— 也算消费：
            # 第一版只认「import 符号」，于是把 `api/v1/suppliers.py` 误判成假消费方。
            for a in node.names:
                out.add((a.name, "*"))
            continue
        if node.module.startswith("app.services"):
            tail = node.module.split(".")[-1]
            for a in node.names:
                out.add((tail, a.name))
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    check_mode = "--check" in sys.argv[1:]
    passed: list[str] = []
    failures: list[str] = []

    def want(ok: bool, good: str, bad: str) -> bool:
        (passed if ok else failures).append(("OK  " if ok else "BAD ") + (good if ok else bad))
        return ok

    if not CONTRACT.exists():
        print("❌ 契约模块不存在：" + CONTRACT_REL)
        return 1
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from app.services import money_contract as _contract_module  # noqa: PLC0415
        from app.services.money_contract import (  # noqa: PLC0415
            FIGURES,
            IMPLEMENTATION_FILES,
            REEXPORTS,
        )
    except Exception as exc:  # noqa: BLE001
        print("❌ 契约模块 import 失败：" + str(exc))
        return 1

    patterns = [(fig, key, pat, why) for fig in FIGURES for key, pat, why in fig.forbid]
    consumers = [(fig, c) for fig in FIGURES for c in fig.consumers]
    want(len(FIGURES) >= MIN_FIGURES, "契约条目 " + str(len(FIGURES)) + " ≥ " + str(MIN_FIGURES),
         "契约只剩 " + str(len(FIGURES)) + " 条 —— 被掏空了（不是「没问题」）")
    want(len(patterns) >= MIN_PATTERNS, "「不许自己算」的模式 " + str(len(patterns)) + " ≥ " + str(MIN_PATTERNS),
         "模式只剩 " + str(len(patterns)) + " 条 —— 契约挡不住任何重复实现")
    want(len(consumers) >= MIN_CONSUMERS, "消费方声明 " + str(len(consumers)) + " ≥ " + str(MIN_CONSUMERS),
         "消费方只剩 " + str(len(consumers)) + " 条 —— 契约没有覆盖面")

    for fig in FIGURES:
        for impl in fig.impls:
            rel, _, symbol = impl.partition("::")
            p = APP / rel
            if not p.exists():
                want(False, "", fig.key + "：实现站点的文件不存在 " + rel)
                continue
            want(defines(p, symbol), fig.key + "：" + rel + " 里定义了 " + symbol,
                 fig.key + "：声明的实现符号 " + symbol + " 在 " + rel + " 里**找不到** —— 契约指向了不存在的东西")

    impl_symbols = {fig.key: set() for fig in FIGURES}
    for fig in FIGURES:
        for impl in fig.impls:
            rel, _, symbol = impl.partition("::")
            module = Path(rel).stem
            impl_symbols[fig.key].add((module, symbol))
    for fig in FIGURES:
        for rel in fig.consumers:
            p = APP / rel
            if not p.exists():
                want(False, "", fig.key + "：声明的消费方不存在 " + rel)
                continue
            got = imports_of(p)
            # ⚠️ 第 ② 步之后，消费方走的是**契约**（`from app.services.money_contract import 符号`），
            #    所以「真的在用」要同时认两条路：直接 import 实现（历史写法）与经契约转出。
            used = sorted(s for s in impl_symbols[fig.key]
                          if s in got or (s[0], "*") in got
                          or (s[1] in REEXPORTS and ("money_contract", s[1]) in got))
            want(bool(used), fig.key + " 的消费方 " + rel + " 确实在用（" + "、".join(s[1] for s in used) + "）",
                 fig.key + "：声明 " + rel + " 是消费方，但它**没有 import** 这条契约的任何实现符号 —— "
                 + "假消费方比漏写更糟：它让人以为那处在走契约")

    # ---- ⑥ 接口：消费方依赖契约，不依赖实现（报告 §7 第 ② 步）----
    reexports = sorted(REEXPORTS)
    want(len(reexports) >= MIN_REEXPORTS,
         "契约转出的钱符号 " + str(len(reexports)) + " ≥ " + str(MIN_REEXPORTS),
         "契约只剩 " + str(len(reexports)) + " 个转出符号 —— 接口被掏空了（消费方会退回去直接 import 实现）")
    wrong: list[str] = []
    for name in reexports:
        module, symbol = REEXPORTS[name]
        try:
            obj = getattr(_contract_module, name)
        except AttributeError:
            wrong.append(name + "（契约里取不到）")
            continue
        owner = getattr(obj, "__module__", "")
        if owner != module:
            wrong.append(name + " 来自 " + str(owner) + "，声明的是 " + module)
    want(not wrong, "契约转出的 " + str(len(reexports)) + " 个钱符号都取得到、且都来自声明的那条实现",
         "转出的符号与声明对不上：" + "；".join(wrong[:3])
         + " —— 契约里**又包/又抄**一份实现，就是长出第二个实现点（比不改还糟）")

    not_via_contract: list[str] = []
    for fig in FIGURES:
        wanted = {sym for _mod, sym in impl_symbols[fig.key] if sym in REEXPORTS}
        if not wanted:
            continue
        for rel in fig.consumers:
            p = APP / rel
            if not p.exists() or rel in PENDING:
                continue
            if not any((m, s) in imports_of(p) for s in wanted for m in ("money_contract",)):
                not_via_contract.append(fig.key + "：" + rel)
    want(not not_via_contract,
         "声明的消费方都从契约 import（" + str(sum(len(f.consumers) for f in FIGURES) - len(PENDING)) + " 个）",
         "这些消费方还在直接 import 实现：" + "、".join(not_via_contract[:5])
         + " —— 判据要说的是「消费方依赖接口」，漏一个就等于那处没走契约")

    impl_tails = {mod.rsplit(".", 1)[-1] for mod, _sym in REEXPORTS.values()}
    bypass: list[str] = []
    for p in sorted(APP.rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        rel = p.relative_to(APP).as_posix()
        if rel in IMPLEMENTATION_FILES or rel == CONTRACT_REL or rel in PENDING:
            continue
        for mod, sym in imports_of(p):
            if mod in impl_tails and sym in REEXPORTS:
                bypass.append(rel + " → " + mod + "." + sym)
    want(not bypass, "app/ 里没有从实现模块直接 import 契约符号（" + "、".join(sorted(impl_tails)) + "）",
         "这些地方绕过了契约：" + "、".join(bypass[:5])
         + " —— 实现模块只该被契约自己 import（否则「唯一实现」又变成口头约定）")

    pending_hit = [rel for rel in PENDING if (APP / rel).exists()]
    want(len(pending_hit) == len(PENDING),
         "PENDING 例外 " + str(len(pending_hit)) + "/" + str(len(PENDING)) + " 条仍然命中",
         "PENDING 里有化石（文件不在了/已经改好了）：" + str(sorted(set(PENDING) - set(pending_hit)))
         + " —— 该把例外删掉了")

    hits: dict[tuple[str, str], list[str]] = {}
    WHY: dict[tuple[str, str], tuple[str, str]] = {}
    for p in sorted(APP.rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        rel = p.relative_to(APP).as_posix()
        if rel in IMPLEMENTATION_FILES:
            continue
        try:
            code = code_only(read(p))
        except SyntaxError:
            continue
        lines = code.splitlines()
        for fig, key, pat, why in patterns:
            rx = re.compile(pat)
            for i, line in enumerate(lines, 1):
                if rx.search(line):
                    hits.setdefault((rel, key), []).append(str(i))
                    WHY.setdefault((rel, key), (fig.key, why))
    for (rel, key), where in sorted(hits.items()):
        if (rel, key) in ALLOWED:
            continue
        fig_key, why = WHY.get((rel, key), ("", ""))
        want(False, "", "[" + fig_key + "] " + rel + ":" + "、".join(where[:4]) + " 命中「" + why + "」"
             + " —— 同一个数在两处算，两边都不报错时谁也不知道该信哪个")
    allowed_hit = [k for k in ALLOWED if k in hits]
    want(len(allowed_hit) == len(ALLOWED),
         "允许表 " + str(len(allowed_hit)) + "/" + str(len(ALLOWED)) + " 条例外仍然命中",
         "允许表里有化石（早就不命中了）：" + str(sorted(set(ALLOWED) - set(allowed_hit)))
         + " —— 一条不再生效的豁免会让人以为这里有洞")

    bare = code_only(read(CONTRACT))
    money_names = ["line_total", "freight_fee", "arrears", "settled", "refunded",
                   "commission_rate", "piece_amount"]
    arith = [n for n in money_names if re.search(r"\b" + n + r"\b\s*[-+*/]", bare)]
    want(not arith, "契约模块里没有钱算式（只有声明）",
         "契约模块里出现了算术（" + "、".join(arith) + "）—— 接口里藏实现，等于又长出第二个实现点")

    print("钱契约判据：" + str(len(passed)) + " 通过 / " + str(len(failures)) + " 失败"
          + "（契约 " + str(len(FIGURES)) + " 条 / 模式 " + str(len(patterns))
          + " 条 / 消费方 " + str(len(consumers)) + " 个）")
    if not check_mode:
        for n in passed:
            print("  ✅ " + n[4:])
    for f in failures:
        print("  " + f)
    if failures:
        return 1
    print("  ✅ 全部通过（每个钱数只有一处实现，消费方真的在用它）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
