# -*- coding: utf-8 -*-
"""扩展清单判据（R4-03）：清单是**契约**，不是注释。

R4-BOUNDARY-JUSTIFICATION: 指南 §15 说清单（Manifest）「非常有价值」，而它最容易烂掉的方式
**不是写错字段，是根本没人核**。一份没人核的清单会同时烂成三种样子：
① 字段少写了几个（而注册表照样收）；② 声明 owns_tables 却跟核心表撞名（一个事实两个主人）；
③ 声明了 capability 但那个能力点**根本不存在**（于是路由永远 403，或者更糟 —— 有人干脆删了它绕过去）。
这三种都没有任何单点的代码错误，只有对账才看得出来。

## 判据（六组）

1. **清单契约三方一致**：ExtensionManifest 的字段 == REQUIRED_FIELDS == docs/R4_EXTENSIONS.md 列出的；
2. **每个扩展目录都有清单**，且目录名 == 清单 id（否则「找不到它时该信谁」）；
3. **每条清单都合规**：kind 在四类里、version 是正整数、provides 非空、compatibility 非空、
   why ≥ 20 字（写不出为什么存在，就不该存在）、routes 与 capability 必须成对；
4. **不许动态加载**（指南 §31 坑 7）：扩展树与注册表里没有 exec / eval / reload / 文件监听；
5. **配置必须走注册表**（指南 §26）：扩展不许直接读环境变量，只认 EXT_ 前缀；
6. **静默空转保护**：字段数 / 类别数 / 文档覆盖度都有下限。

用法：python _tools/qa/_check_extension_manifest.py [--list]
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting  # noqa: E402

# ⛔ 字段清单**只有一处**：注册表里的 REQUIRED_FIELDS（本判据从那里读，不自己再抄一份）。
from app.core.extension_registry import (  # noqa: E402
    CORE_CONFIG_PREFIX,
    EXTENSION_CONFIG_PREFIX,
    KINDS,
    MANIFEST_ATTR,
    MANIFEST_MODULE,
    REQUIRED_FIELDS,
    ExtensionManifest,
    discover,
)

APP = ROOT / "backend" / "app"
EXTENSIONS = APP / "extensions"
REGISTRY = APP / "core" / "extension_registry.py"
DOC = ROOT / "docs" / "R4_EXTENSIONS.md"

# ⛔ 动态加载与热插拔的形状（指南 §31 坑 7 / §16）。
DYNAMIC_SMELLS = ("exec(", "eval(", "importlib.reload", "watchdog", "subprocess",
                  "os.system", "__import__(", "watchfiles")
# ⛔ 扩展直接读环境变量的形状（指南 §26）。
ENV_SMELLS = ("os.environ", "os.getenv", "getenv(")

MIN_FIELDS = 12
MIN_KINDS = 4
MIN_DOC_HITS = 12
# ⚠️ R4-03 时这里写着 0（当时一个扩展都没有，「每个扩展都合规」那一半只核了空集）。
# R4-04 落地第一个扩展时按台账的承诺**抬到 1** —— 这是一次收紧，不是放松：
# 从这一刻起，"扩展数掉到 0"会当场报红，而不是安静地全绿。
# 现在实际有 2 个（unit_conversion / pricing）；下限仍写 1，因为它是**反空转**的下限，
# 不是"当前有几个"的镜像（后者会随着加扩展而变成要维护的第二个真相）。
MIN_EXTENSIONS = 1


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


def code_only(path: Path) -> str:
    """代码（去掉注释与文档字符串）—— 说明文字里出现 exec 不算动态加载。"""
    try:
        tree = ast.parse(read(path))
    except SyntaxError:
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


def dataclass_fields() -> list[str]:
    """ExtensionManifest 声明的字段名（AST 取）。"""
    tree = ast.parse(read(REGISTRY))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ExtensionManifest":
            out = []
            for s in node.body:
                if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name):
                    out.append(s.target.id)
            return out
    return []


def extension_dirs() -> list[Path]:
    if not EXTENSIONS.exists():
        return []
    return sorted(d for d in EXTENSIONS.iterdir() if d.is_dir() and d.name != "__pycache__")


def main() -> int:
    if refuse_if_injecting("扩展清单检查"):
        return 1
    exts = extension_dirs()
    registry = discover()
    if "--list" in sys.argv[1:]:
        for m in registry.all():
            print(m.id + "  " + m.kind + "  " + str(list(m.provides)))
        return 0

    c = Checker()
    print("== 1. 清单契约三方一致 ==")
    fields = dataclass_fields()
    c.ok("ExtensionManifest 有 " + str(len(fields)) + " 个字段（≥" + str(MIN_FIELDS) + "）",
         len(fields) >= MIN_FIELDS, str(fields))
    c.ok("字段与 REQUIRED_FIELDS 一致（注册表内部自洽）",
         set(fields) >= set(REQUIRED_FIELDS),
         "dataclass 少了：" + str(sorted(set(REQUIRED_FIELDS) - set(fields))))
    doc = read(DOC)
    c.ok("docs/R4_EXTENSIONS.md 存在", bool(doc.strip()), "清单没有文档 = 没有契约")
    undocumented = [f for f in REQUIRED_FIELDS if f not in doc]
    c.ok("每个必备字段都在文档里写了（缺 " + str(len(undocumented)) + " 个）",
         not undocumented, "没写：" + str(undocumented))
    c.ok("四类扩展都在文档里写了", all(k in doc for k in KINDS),
         "没写：" + str([k for k in KINDS if k not in doc]))
    c.ok("文档提到了注册表 / 配置前缀 / 路由能力点 / 依赖图",
         all(w in doc for w in ("extension_registry", "EXT_", "capability", "依赖图")),
         "缺：" + str([w for w in ("extension_registry", "EXT_", "capability", "依赖图") if w not in doc]))

    print()
    print("== 2. 每个扩展目录都有清单 ==")
    c.ok("扩展目录数 " + str(len(exts)) + "（≥" + str(MIN_EXTENSIONS) + "）",
         len(exts) >= MIN_EXTENSIONS, "低于下限")
    no_manifest = [d.name for d in exts if not (d / (MANIFEST_MODULE + ".py")).exists()]
    c.ok("每个扩展目录都有 " + MANIFEST_MODULE + ".py", not no_manifest, str(no_manifest))
    c.ok("注册表收进来的扩展数与目录数一致", len(registry) == len(exts),
         "目录 " + str(len(exts)) + " 个，注册表 " + str(len(registry)) + " 个")

    print()
    print("== 3. 每条清单都合规 ==")
    bad: list[str] = []
    for m in registry.all():
        tag = m.id
        if not isinstance(m, ExtensionManifest):
            bad.append(tag + " 不是 ExtensionManifest")
            continue
        if m.kind not in KINDS:
            bad.append(tag + " kind=" + repr(m.kind))
        if not (isinstance(m.version, int) and m.version > 0):
            bad.append(tag + " version=" + repr(m.version))
        if not m.provides:
            bad.append(tag + " 没有 provides（它到底提供什么？）")
        if not m.compatibility:
            bad.append(tag + " 没有 compatibility（按哪个契约版本写的？）")
        if len(m.why) < 20:
            bad.append(tag + " 的 why 太短（写不出为什么存在，就不该存在）")
        if bool(m.routes) != bool(m.capability):
            bad.append(tag + " 的 routes 与 capability 不成对")
    c.ok("每条清单都合规（kind / version / provides / compatibility / why / routes 成对）",
         not bad, str(bad[:3]))

    print()
    print("== 4. 不许动态加载（指南 §31 坑 7）==")
    dyn: list[str] = []
    for f in (sorted(EXTENSIONS.rglob("*.py")) if EXTENSIONS.exists() else []):
        if "__pycache__" in f.parts:
            continue
        code = code_only(f)
        for smell in DYNAMIC_SMELLS:
            if smell in code:
                dyn.append(str(f.relative_to(APP)).replace(chr(92), "/") + " 里有 " + smell)
    reg_code = code_only(REGISTRY)
    for smell in DYNAMIC_SMELLS:
        if smell in reg_code:
            dyn.append("core/extension_registry.py 里有 " + smell)
    c.ok("扩展树与注册表里都没有 exec / eval / reload / 文件监听 / subprocess", not dyn, str(dyn[:3]))
    c.ok("注册表只做部署期包扫描（pkgutil + import_module），没有运行期热加载",
         "pkgutil" in reg_code and "import_module" in reg_code,
         "包扫描的形状变了？改了它就要来改这一条")

    print()
    print("== 5. 配置必须走注册表（指南 §26）==")
    env_hits: list[str] = []
    for f in (sorted(EXTENSIONS.rglob("*.py")) if EXTENSIONS.exists() else []):
        if "__pycache__" in f.parts:
            continue
        code = code_only(f)
        for smell in ENV_SMELLS:
            if smell in code:
                env_hits.append(str(f.relative_to(APP)).replace(chr(92), "/") + " 里有 " + smell)
    c.ok("扩展不许直接读环境变量（配置一律经 extension_config）", not env_hits, str(env_hits[:3]))
    c.ok("注册表把两个前缀分开（CORE_ 与 EXT_）",
         CORE_CONFIG_PREFIX == "CORE_" and EXTENSION_CONFIG_PREFIX == "EXT_",
         "前缀定义变了 —— 改了它就要来改这一条")

    print()
    print("== 6. 静默空转保护 ==")
    hits = sum(1 for f in REQUIRED_FIELDS if f in doc)
    c.ok("文档覆盖度 " + str(hits) + "/" + str(len(REQUIRED_FIELDS)) + "（下限 " + str(MIN_DOC_HITS) + "）",
         hits >= MIN_DOC_HITS, "文档被掏空了")
    c.ok("字段数 / 类别数 两项下限都达标", len(fields) >= MIN_FIELDS and len(KINDS) >= MIN_KINDS)
    if not exts:
        print("  [--]   现在扩展数为 0：第 3/5 组只核了空集。")
        print("         ⚠️ 台账里记着：R4-04 落地第一个扩展时，MIN_EXTENSIONS 要从 0 抬到 1。")

    print()
    print("=" * 60)
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 " + str(c.passes) + " 项通过：清单契约三方一致、禁止动态加载、配置只走 EXT_ 前缀。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
