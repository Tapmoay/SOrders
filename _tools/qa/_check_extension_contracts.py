# -*- coding: utf-8 -*-
"""扩展契约判据（R4-02 的机器形态）。

R4-BOUNDARY-JUSTIFICATION: 契约这种东西**天生拦不住自己**。「核心只接受 Money」是一句承诺，
而承诺的失效方式全都不是代码错误：扩展返回一个裸 Decimal（注解是 Any 时完全合法）、
契约模块里悄悄 import 了 sqlalchemy（测试照样全绿）、有人为了「统一」造了一个 Plugin 基类
（每个实现都能跑，只是复杂度全藏起来了）。这些错误**没有任何单点边界能消除** ——
它们要的是把契约与仓库全局口径**对账**。所以这一条必须存在，而且必须是对账式的。

## 它自己算的东西（⛔ 一样都不从文档抄）

1. **进位口径**：把 backend/app 里每一处 quantize 调用用 AST 抠出来，逐条核对它显式写了
   rounding=、且两位小数那一档就是 ROUND_HALF_UP —— 与 contracts/money.py 的 QUANTUM/ROUNDING 对账。
   这是本仓库唯一一条「跨十几个文件的口头约定」，机器核过之后它才真的只有一处定义。
2. **契约的输出类型**：AST 核对 PricingResult.money 是 Money、ConversionResult.quantity 是 Quantity；
3. **契约是不是真的没有实现**：在**去掉文档字符串与注释的代码**里扫 db / Session / select 的痕迹；
4. **有没有长出万能插件基类**（指南 §7 明确否掉的那个坑）。

## 判据（八组）

1. 两个契约模块存在、声明了 CONTRACT_NAME / CONTRACT_VERSION，且版本在 1..MAX_CONTRACT_VERSION；
2. 契约模块里**一行实现都没有**；
3. 核心契约包**不 import 任何具体扩展**（依赖方向单向，指南 §13）；
4. **没有万能插件基类**（Plugin / initialize / execute / shutdown 一律不许出现）；
5. **钱的口径对账**：全项目每一处 quantize 都显式写了 rounding，且两位小数那一档 = ROUND_HALF_UP；
6. **输出必须是核心类型**（AST 取注解）；
7. 文档 docs/R4_CONTRACTS.md 里两个契约的六个要素（输入/输出/错误/不变量/兼容要求/生命周期）齐全；
8. **静默空转保护**：契约数 / quantize 处数 / 输出类型数 / 要素数都有下限，
   「一个都没核到」时**报红**而不是全绿。

用法：
    python _tools/qa/_check_extension_contracts.py           # 非零退出＝有对不上的
    python _tools/qa/_check_extension_contracts.py --list    # 只列契约
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402

ROOT = repo_root()
APP = ROOT / "backend" / "app"
CONTRACTS = APP / "core" / "contracts"
EXTENSIONS = APP / "extensions"
DOC = ROOT / "docs" / "R4_CONTRACTS.md"

#: 两个契约：模块名 -> (契约名, 结果类, 结果字段, 该字段的**核心**类型)。
CONTRACTS_DECL = {
    "unit_conversion": ("UnitConversionContract", "ConversionResult", "quantity", "Quantity"),
    "pricing": ("PricingContract", "PricingResult", "money", "Money"),
}
CONTRACT_FILES = ("money.py", "quantity.py", "unit_conversion.py", "pricing.py")
ELEMENTS = ("输入", "输出", "错误", "不变量", "兼容要求", "生命周期")
CORE_VALUE_TYPES = ("Money", "Quantity")
PLUGIN_SMELLS = ("class Plugin", "def initialize(self", "def execute(self", "def shutdown(self")
IMPL_SMELLS = ("sqlalchemy", "Session", "select(", "commit(")

MIN_CONTRACTS = 2
MIN_QUANTIZE_SITES = 8
MAX_CONTRACT_VERSION = 3


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def parse(p: Path) -> ast.Module | None:
    try:
        return ast.parse(read(p))
    except SyntaxError:
        return None


# 这个文件的**代码**（去掉注释与文档字符串）。
# ⚠️ 为什么必须这么剥：第一版直接在原文里搜 Session，于是「刻意不带 Session」那句
#    **文档字符串**把自己判红了 —— 同一个判断被两处文本满足，本仓库栽过的老账。
def code_only(path: Path) -> str:
    tree = parse(path)
    if tree is None:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:]
    try:
        return ast.unparse(tree)
    except Exception:  # noqa: BLE001 —— 核不了就说核不了，不静默放过
        return ""


def module_const(path: Path, name: str) -> str:
    """取模块级常量的**字面量值**（用 AST，不用正则 —— 数括号数不过 AST）。"""
    tree = parse(path)
    if tree is None:
        return ""
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    try:
                        return str(ast.literal_eval(stmt.value))
                    except Exception:  # noqa: BLE001
                        # 不是字面量（例如 Decimal 构造 / ROUND_HALF_UP）就退回**源码形态**：
                        # 这一条要的正是「声明长什么样」，不是它的值。
                        try:
                            return ast.unparse(stmt.value)
                        except Exception:  # noqa: BLE001
                            return ""
    return ""


def imports_extension(path: Path) -> bool:
    tree = parse(path)
    if tree is None:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.extensions"):
            return True
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("app.extensions"):
                    return True
    return False


# 全项目每一处 quantize 调用 —— **AST 取，不用正则**。
# ⚠️ 为什么必须 AST：第一版用正则抠实参，而 quantize(Decimal("0.01"), rounding=...) 的
#    **第一个右括号在 Decimal(...) 里面** —— 实参被截成半个表达式，于是
#    「显式写了 rounding=」这条判据把**全都写对了**的那批判成了没写（实测）。
# 返回 [(相对路径, 行号, 关键字参数名, 量子表达式, rounding 表达式)]。
def quantize_sites() -> list[tuple[str, int, tuple[str, ...], str, str]]:
    out: list[tuple[str, int, tuple[str, ...], str, str]] = []
    for f in sorted(APP.rglob("*.py")):
        tree = parse(f)
        if tree is None:
            continue
        rel = str(f.relative_to(APP)).replace(chr(92), "/")
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "quantize"):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            quantum = ast.unparse(node.args[0]) if node.args else ""
            rounding = ast.unparse(kw["rounding"]) if "rounding" in kw else ""
            out.append((rel, node.lineno, tuple(sorted(kw)), quantum, rounding))
    return out


def annotation_of(module: Path, cls_name: str, field_name: str) -> str:
    """AST 取某个类字段的类型注解名（拿不到返回空串）。"""
    tree = parse(module)
    if tree is None:
        return ""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) \
                        and stmt.target.id == field_name:
                    return ast.unparse(stmt.annotation)
    return ""


def main() -> int:
    if refuse_if_injecting("扩展契约检查"):
        return 1
    if "--list" in sys.argv[1:]:
        for mod, spec in CONTRACTS_DECL.items():
            print(mod + "  " + spec[0] + "  输出 " + spec[1] + "." + spec[2] + ": " + spec[3])
        return 0

    c = Checker()
    print("== 1. 契约声明 ==")
    c.ok("契约包存在（core/contracts/）", CONTRACTS.is_dir(), str(CONTRACTS))
    found = 0
    for mod, spec in CONTRACTS_DECL.items():
        path = CONTRACTS / (mod + ".py")
        name = module_const(path, "CONTRACT_NAME")
        ver = module_const(path, "CONTRACT_VERSION")
        c.ok(mod + ".py 声明了 " + spec[0] + " 与 CONTRACT_VERSION",
             name == spec[0] and ver.isdigit() and int(ver) > 0,
             "契约名=" + repr(name) + " 版本=" + repr(ver))
        c.ok(mod + " 的版本在 1.." + str(MAX_CONTRACT_VERSION) + "（§31 坑 13：不许留 10 代接口）",
             ver.isdigit() and 0 < int(ver) <= MAX_CONTRACT_VERSION, "version=" + repr(ver))
        if name == spec[0] and ver.isdigit() and int(ver) > 0:
            found += 1
    c.ok("找到 " + str(found) + " 个契约（≥" + str(MIN_CONTRACTS) + "）",
         found >= MIN_CONTRACTS, "契约数低于下限 —— 这一组在空转")

    print()
    print("== 2. 契约里一行实现都没有 ==")
    dirty: list[str] = []
    for fn in CONTRACT_FILES:
        text = code_only(CONTRACTS / fn)
        for smell in IMPL_SMELLS:
            if smell in text:
                dirty.append(fn + " 里有 " + smell)
    c.ok("契约模块不碰库（代码里没有 sqlalchemy / Session / select / commit）",
         not dirty, str(dirty[:4]))

    print()
    print("== 3. 依赖方向单向：核心契约包不 import 具体扩展 ==")
    cross = [str(f.relative_to(APP)).replace(chr(92), "/")
             for f in sorted(CONTRACTS.rglob("*.py")) if imports_extension(f)]
    c.ok("契约包没有 import app.extensions（Core -> Extension 是禁止方向，指南 §13）",
         not cross, str(cross))

    print()
    print("== 4. 没有万能插件基类（指南 §7）==")
    smells: list[str] = []
    for root in (CONTRACTS, EXTENSIONS):
        for f in (sorted(root.rglob("*.py")) if root.exists() else []):
            text = read(f)
            for smell in PLUGIN_SMELLS:
                if smell in text:
                    smells.append(str(f.relative_to(APP)).replace(chr(92), "/") + " 里有 " + smell)
    c.ok("契约与扩展里都没有 Plugin/initialize/execute/shutdown", not smells, str(smells[:4]))

    print()
    print("== 5. 钱的口径对账：QUANTUM / ROUNDING 与全项目对得上 ==")
    q_decl = module_const(CONTRACTS / "money.py", "QUANTUM")
    r_decl = module_const(CONTRACTS / "money.py", "ROUNDING")
    c.ok("money.py 声明了 QUANTUM 与 ROUNDING", bool(q_decl) and bool(r_decl),
         "QUANTUM=" + repr(q_decl) + " ROUNDING=" + repr(r_decl))
    q_src = q_decl.replace(chr(39), chr(34))
    c.ok("QUANTUM = Decimal(0.01) 且 ROUNDING = ROUND_HALF_UP（两位小数 + 四舍五入）",
         q_src == 'Decimal("0.01")' and r_decl == "ROUND_HALF_UP",
         "实测 QUANTUM=" + q_src + " ROUNDING=" + r_decl + " —— 改了定义就要来改这一条")
    sites = quantize_sites()
    c.ok("扫到 " + str(len(sites)) + " 处 quantize（≥" + str(MIN_QUANTIZE_SITES) + "）",
         len(sites) >= MIN_QUANTIZE_SITES, "扫不到 quantize —— 这一组在空转")
    no_rounding: list[str] = []
    bad_cent: list[str] = []
    for rel, line, kwargs, quantum, rounding in sites:
        tag = rel + ":" + str(line)
        if "rounding" not in kwargs:
            no_rounding.append(tag + "  quantize(" + quantum + ")")
        elif "0.01" in quantum and rounding != "ROUND_HALF_UP":
            bad_cent.append(tag + "  " + quantum + " -> " + rounding)
    c.ok("每一处 quantize 都**显式写了** rounding=（默认是 ROUND_HALF_EVEN，半分上差一分钱）",
         not no_rounding, str(no_rounding[:3]))
    c.ok("两位小数那一档用的都是 ROUND_HALF_UP（与 money.QUANTUM 同一条口径）",
         not bad_cent, str(bad_cent[:3]))

    print()
    print("== 6. 契约的输出必须是核心类型（AST）==")
    checked = 0
    bad_out: list[str] = []
    for mod, spec in CONTRACTS_DECL.items():
        ann = annotation_of(CONTRACTS / (mod + ".py"), spec[1], spec[2])
        checked += 1
        if ann != spec[3]:
            bad_out.append(mod + "." + spec[1] + "." + spec[2] + " = " + repr(ann)
                           + "（应为 " + spec[3] + "）")
    c.ok("核对过 " + str(checked) + " 个契约的输出类型", checked >= MIN_CONTRACTS, "一个都没核到")
    c.ok("输出全是核心类型（" + "、".join(CORE_VALUE_TYPES) + "）—— ⛔ 不接受扩展自己的对象",
         not bad_out, str(bad_out))

    print()
    print("== 7. 六个要素写进文档（指南 §35）==")
    doc = read(DOC)
    c.ok("docs/R4_CONTRACTS.md 存在", bool(doc.strip()), "契约没有文档 = 没有承诺")
    per = {e: doc.count(e) for e in ELEMENTS}
    all_twice = all(per[e] >= 2 for e in ELEMENTS)
    c.ok("六个要素**每个契约各一份**（出现次数都 ≥ 2）", all_twice,
         "没写全：" + str({e: n for e, n in per.items() if n < 2}))
    for spec in CONTRACTS_DECL.values():
        c.ok("文档里写了 " + spec[0], spec[0] in doc, "文档没提这个契约")

    print()
    print("== 8. 静默空转保护 ==")
    c.ok("契约数 / quantize 处数 / 输出类型数 / 要素数四项下限都达标",
         found >= MIN_CONTRACTS and len(sites) >= MIN_QUANTIZE_SITES
         and checked >= MIN_CONTRACTS and all_twice and bool(doc.strip()))

    print()
    print("=" * 60)
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 " + str(c.passes) + " 项通过：" + str(found) + " 个契约都只有声明没有实现；")
    print("   全项目 " + str(len(sites)) + " 处 quantize 与 money.QUANTUM/ROUNDING 对得上。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())