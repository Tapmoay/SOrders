# -*- coding: utf-8 -*-
"""依赖防火墙判据（R4-03）：模块可以依赖，但**只能依赖稳定契约**。

R4-BOUNDARY-JUSTIFICATION: 指南 §12 说得很直接 —— 「这个是 R4 的真正核心工程。目标不是
模块之间没有依赖，而是：**模块可以依赖，但只能依赖稳定契约**」。
而"依赖了不该依赖的东西"这个错误，**代码边界本身拦不住**：

    from app.services import accounting_service      # 语法正确、能跑、测试全绿

它没有任何单点的类型或结构错误 —— 错的是**方向**，而方向只有在整张图上才看得出来。
所以这一条必须是对账式的：把全仓库的 import 边按分区（core / extension / infra）归类，
再逐条核对它落在允许的方向上。

## 四条防火墙规则（指南 §12）与它们各自的判据

| 规则 | 本判据的第几组 |
| --- | --- |
| ① Core 不能 import 具体 Extension | 第 1 组 |
| ② Extension 不能直接改 Core 拥有的数据 | `_check_data_ownership.py` |
| ③ Extension 不能绕过 Capability | 第 3 组 |
| ④ Extension 不能 direct-import 私有内部 | 第 2 组 |

## 依赖方向（指南 §13，单向）

    Core Contract  <-  Extension Implementation  <-  Infrastructure Adapter

    Core -> PricingContract        ✅（核心认识契约）
    Pricing -> MoneyCore           ✅（扩展认识核心的值类型）
    Core -> ColdChainPricing       ❌（核心认识具体实现 —— 一旦出现，R4 就开始倒退）

## 它自己算的东西（⛔ 一样都不从文档抄）

import 边来自 AST 的 ImportFrom / Import 节点；能力点来自 `core/rbac.py` 的 Permission 枚举；
扩展清单来自 `core/extension_registry.py` 的字段表。

用法：
    python _tools/qa/_check_extension_dependencies.py            # 非零退出＝有越界依赖
    python _tools/qa/_check_extension_dependencies.py --graph    # 打印依赖图（指南 §29）
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
EXTENSIONS = APP / "extensions"
RBAC = APP / "core" / "rbac.py"

#: 谁**可以** import `app.extensions`：只有装配根（指南 §13 的 Core -> Contract 那一条边）。
#: ⛔ 其余任何核心文件都不许 —— 那正是「核心反向依赖具体扩展」。
ALLOWED_EXTENSION_IMPORTERS = {"main.py"}

#: 扩展**可以** import 的模块前缀（指南 §12 规则④：不许 direct-import 私有内部）。
#: * `app.core.contracts` —— 它要实现的接口；
#: * `app.core.extension_registry` —— 它声明自己的方式；
#: * `app.extensions` —— **同区内的兄弟模块**（R4-04 实测补的：路由模块要 import 自己包的 PROVIDERS）。
#:   ⚠️ 该禁的是"碰核心私有内部"，不是"扩展之间不能互相看见"；后者是另一件事
#:   （指南 §12 禁的是"直接改另一个 Extension 的表"，那由 _check_data_ownership.py 管）。
#:   其余 `app.*`（services / api / models / database / deps / commands / schemas）一律不许。
EXTENSION_ALLOWED_CORE_PREFIXES = ("app.core.contracts", "app.core.extension_registry", "app.extensions")

#: 扩展里出现这些 = 自己写了一套鉴权（§31 坑 11）。
AUTH_SMELLS = ("require_permission", "require_roles", "require_any_permission",
               "get_current_user", "current_user", "Permission.")

MIN_CORE_FILES = 40
MIN_PERMISSIONS = 15


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


def code_only(path: Path) -> str:
    """这个文件的**代码**（去掉注释与文档字符串）。

    ⚠️ 为什么必须这么剥：第一版直接在原文里搜 require_permission，于是 extensions/__init__.py
    里那句「路由由核心装配并施加 require_permission」**把自己判成了"扩展自己写鉴权"**（实测）——
    同一个判断被两处文本满足。本仓库栽过的老账，这里第二次遇到，所以这一条统一走 AST。
    """
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
    except Exception:  # noqa: BLE001
        return ""


def imports_of(path: Path) -> list[str]:
    """这个文件 import 了哪些 `app.*` 模块（AST，⛔ 不用正则）。"""
    tree = parse(path)
    if tree is None:
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
            out.append(node.module or "")
            for a in node.names:
                if a.name != "*":
                    out.append((node.module or "") + "." + a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("app"):
                    out.append(a.name)
    return out


def python_files(root: Path, skip_extensions: bool = True) -> list[Path]:
    out = []
    for f in sorted(root.rglob("*.py")):
        if skip_extensions and EXTENSIONS in f.parents:
            continue
        if "__pycache__" in f.parts:
            continue
        out.append(f)
    return out


def rel(p: Path) -> str:
    return str(p.relative_to(APP)).replace(chr(92), "/")


def rbac_permissions() -> set[str]:
    """`core/rbac.py` 里 Permission 枚举的成员名（AST 取，⛔ 不 import）。"""
    tree = parse(RBAC)
    if tree is None:
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Permission":
            out: set[str] = set()
            for s in node.body:
                if isinstance(s, ast.Assign) and s.targets and isinstance(s.targets[0], ast.Name):
                    out.add(s.targets[0].id)
            return out
    return set()


def extension_dirs() -> list[Path]:
    if not EXTENSIONS.exists():
        return []
    return sorted(d for d in EXTENSIONS.iterdir() if d.is_dir() and d.name != "__pycache__")


def manifest_of(d: Path):
    """取扩展的 MANIFEST（静态 import 那个模块，与注册表的做法一致）。"""
    import importlib

    try:
        mod = importlib.import_module("app.extensions." + d.name + ".manifest")
    except Exception:  # noqa: BLE001 —— 清单本身坏了由 _check_extension_manifest.py 报
        return None
    return getattr(mod, "MANIFEST", None)


def main() -> int:
    if refuse_if_injecting("依赖防火墙检查"):
        return 1
    files = python_files(APP)
    exts = extension_dirs()

    c = Checker()
    print("== 1. Core 不能 import 具体 Extension（指南 §13）==")
    c.ok("扫到 " + str(len(files)) + " 个核心 .py（≥" + str(MIN_CORE_FILES) + "）",
         len(files) >= MIN_CORE_FILES, "扫不到文件 —— 这一组在空转")
    bad_core: list[str] = []
    for f in files:
        if rel(f) in ALLOWED_EXTENSION_IMPORTERS:
            continue
        for mod in imports_of(f):
            if mod == "app.extensions" or mod.startswith("app.extensions."):
                bad_core.append(rel(f) + " -> " + mod)
    c.ok("只有装配根（" + "、".join(sorted(ALLOWED_EXTENSION_IMPORTERS)) + "）能 import app.extensions",
         not bad_core, "核心反向依赖了具体扩展：" + str(bad_core[:3]))

    print()
    print("== 2. Extension 不能 direct-import 私有内部（指南 §12 规则④）==")
    bad_ext: list[str] = []
    ext_files = python_files(EXTENSIONS, skip_extensions=False) if EXTENSIONS.exists() else []
    for f in ext_files:
        for mod in imports_of(f):
            if not mod.startswith("app."):
                continue
            if any(mod == p or mod.startswith(p + ".") for p in EXTENSION_ALLOWED_CORE_PREFIXES):
                continue
            bad_ext.append(rel(f) + " -> " + mod)
    c.ok("扩展只 import 契约 / 注册表 / 同区兄弟（" + "、".join(EXTENSION_ALLOWED_CORE_PREFIXES) + "）",
         not bad_ext, "越界 import：" + str(bad_ext[:3]))
    print("  扩展文件 " + str(len(ext_files)) + " 个 / 扩展目录 " + str(len(exts)) + " 个")

    print()
    print("== 3. Extension 不能绕过 Capability（指南 §27）==")
    auth_smells: list[str] = []
    for f in ext_files:
        text = code_only(f)
        for smell in AUTH_SMELLS:
            if smell in text:
                auth_smells.append(rel(f) + " 里有 " + smell)
    c.ok("扩展代码里**一行鉴权都没有**（路由的能力点由核心施加）", not auth_smells,
         str(auth_smells[:3]))
    perms = rbac_permissions()
    c.ok("从 core/rbac.py 读到 " + str(len(perms)) + " 个权限点（≥" + str(MIN_PERMISSIONS) + "）",
         len(perms) >= MIN_PERMISSIONS, "读不到权限点 —— 下面那条会变成空转")
    bad_cap: list[str] = []
    for d in exts:
        m = manifest_of(d)
        if m is None:
            continue
        if getattr(m, "routes", "") and getattr(m, "capability", "") not in perms:
            bad_cap.append(d.name + " 声明了 routes 却把能力点写成 " + repr(getattr(m, "capability", "")))
    c.ok("声明了路由的扩展，其能力点都是**真实存在**的 Permission 成员",
         not bad_cap, str(bad_cap[:3]))

    print()
    print("== 4. 依赖图（指南 §29）==")
    graph = []
    for d in exts:
        m = manifest_of(d)
        if m is None:
            continue
        graph.append((getattr(m, "id", d.name), getattr(m, "kind", "?"),
                      tuple(getattr(m, "requires", ())), tuple(getattr(m, "provides", ())),
                      tuple(getattr(m, "owns_tables", ())), getattr(m, "capability", "")))
    print("  扩展 " + str(len(graph)) + " 个：")
    for gid, kind, requires, provides, owns, cap in graph:
        print("    " + gid + " [" + kind + "]  provides=" + str(list(provides))
              + "  requires=" + str(list(requires)) + "  owns_tables=" + str(list(owns))
              + ("  capability=" + cap if cap else ""))
    if "--graph" in sys.argv[1:]:
        print()
        print("  谁依赖谁（扩展 -> 核心契约）：")
        for gid, _kind, _r, provides, _o, _cap in graph:
            print("    " + gid + "  ->  " + (", ".join(provides) or "（没有声明 provides）"))
        print("  谁拥有表：")
        for gid, _kind, _r, _p, owns, _cap in graph:
            for t in owns:
                print("    " + t + "  <-  " + gid)
        return 0
    c.ok("依赖图能生成（每个扩展都有 kind/provides 可打印）",
         all(g[1] and g[3] for g in graph) if graph else True,
         "有扩展缺 kind 或 provides")

    print()
    print("== 5. 静默空转保护 ==")
    c.ok("核心文件数 / 权限点数 两项下限都达标",
         len(files) >= MIN_CORE_FILES and len(perms) >= MIN_PERMISSIONS)
    if not exts:
        print("  [--]   现在扩展数为 0：第 2/3/4 组**只核了「没有越界」这一半** ——")
        print("         等 R4-04 落地第一个扩展，它们才真正开始核「扩展本身合不合规」。")

    print()
    print("=" * 60)
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 " + str(c.passes) + " 项通过：依赖方向单向、扩展不越界、鉴权归核心。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())