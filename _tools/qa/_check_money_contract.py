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
        from app.services.money_contract import FIGURES, IMPLEMENTATION_FILES  # noqa: PLC0415
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
            used = sorted(s for s in impl_symbols[fig.key] if s in got or (s[0], "*") in got)
            want(bool(used), fig.key + " 的消费方 " + rel + " 确实在用（" + "、".join(s[1] for s in used) + "）",
                 fig.key + "：声明 " + rel + " 是消费方，但它**没有 import** 这条契约的任何实现符号 —— "
                 + "假消费方比漏写更糟：它让人以为那处在走契约")

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
