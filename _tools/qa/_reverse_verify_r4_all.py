# -*- coding: utf-8 -*-
"""反向验证：R4 的架构检查器**真的会红**吗（R4 指南 §30 的硬要求）。

## 为什么 R4 的每个检查器都必须有这一份
指南 §30 原话：「每个检查器必须有：**为什么代码边界无法解决 / 反向破坏用例 / 静默空转保护**。
没有这些，**不准进入 R4 核心工具**。」
而 R3 已经用事实说明为什么：R3 暴露过 checker self-reference、checker 被弱化、
file existence 伪通过、报告数字漂移 —— **一条永远绿的检查等于没有检查**。

所以这里对每一个 R4 检查器：先证明「源码完好时它是绿的」（前提），
再**把每一条判据分别弄坏一次**，看它是不是**点出了那一条**（不是「随便红了就行」：
期望里带关键字，红的位置不对也算不成立），最后证明**还原之后它又绿了**。

⚠️ 注入只改**文档与声明**，尽量不动源码；非动源码不可的那几条（§28 的派发表、
钱的口径对账）只做**语法合法**的改动，跑完按字节还原。

用法：python _tools/qa/_reverse_verify_r4_all.py            # 全部成立 → 退出码 0
     python _tools/qa/_reverse_verify_r4_all.py --list      # 只列场景
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
APP = ROOT / "backend" / "app"

CHECKS = {
    "boundary": HERE / "_check_core_extension_boundary.py",
    "contracts": HERE / "_check_extension_contracts.py",
    "dependencies": HERE / "_check_extension_dependencies.py",
    "ownership": HERE / "_check_data_ownership.py",
    "manifest": HERE / "_check_extension_manifest.py",
}
MAP = ROOT / "docs" / "R4_CORE_EXTENSION_MAP.md"
CDOC = ROOT / "docs" / "R4_CONTRACTS.md"
MAIN = APP / "main.py"
CONTRACTS = APP / "core" / "contracts"
EDOC = ROOT / "docs" / "R4_EXTENSIONS.md"
REGISTRY = APP / "core" / "extension_registry.py"
EXT_INIT = APP / "extensions" / "__init__.py"
MODELS_ORDER = APP / "models" / "order.py"
CORE_SVC = APP / "services" / "reports_service.py"

FENCE = chr(96) * 3
TICK = chr(96)


class Sandbox:
    """按字节记住原样，最后一次性还原（⛔ 不用 git checkout --：那会抹掉未提交的真实改动）。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def _keep(self, p: Path) -> None:
        if p not in self.saved:
            self.saved[p] = p.read_bytes()

    def append(self, p: Path, text: str) -> None:
        self._keep(p)
        p.write_bytes(p.read_bytes() + text.encode("utf-8"))

    def replace(self, p: Path, old: str, new: str) -> None:
        self._keep(p)
        text = p.read_text(encoding="utf-8")
        assert text.count(old) == 1, p.name + ": 原文出现 " + str(text.count(old)) + " 次，无法唯一替换"
        p.write_bytes(text.replace(old, new).encode("utf-8"))

    def sub(self, p: Path, old: str, new: str) -> None:
        """全局替换（用在「每一条都改一下」的注入上）。"""
        self._keep(p)
        p.write_bytes(p.read_text(encoding="utf-8").replace(old, new).encode("utf-8"))

    def write(self, p: Path, text: str) -> None:
        self._keep(p)
        p.write_bytes(text.encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)
            if p.read_bytes() != raw:
                print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        self.saved.clear()


def run_check(which: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECKS[which])], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ------------------------------------------------ 边界图判据的注入

def b_ok(sb: Sandbox) -> None:
    """正面前提：什么都不动 → 必须绿。"""


def b_orphan_table(sb: Sandbox) -> None:
    """把 orders 这张表从图上摘掉（＝ 有东西没被定档，Unclassified > 0）。"""
    sb.replace(MAP, "owns: orders, order_products, order_templates, order_template_categories",
               "owns: order_products, order_templates, order_template_categories")


def b_ghost_table(sb: Sandbox) -> None:
    """往 owns 里塞一个不存在的表名（防化石那一组该红）。"""
    sb.replace(MAP, "owns: orders, order_products, order_templates, order_template_categories",
               "owns: orders, order_products, order_templates, order_template_categories, orders_v2")


def b_double_owner(sb: Sandbox) -> None:
    """让两条能力同时认领 orders（同一个事实两个主人）。"""
    sb.replace(MAP, "owns: inventory_movements", "owns: inventory_movements, orders")


def b_bad_class(sb: Sandbox) -> None:
    """把一条的 class 改成四档之外的值。"""
    sb.replace(MAP, "id: audit.operation_log" + chr(10) + "中文名: 核心审计（谁在什么时候对什么做了什么）" + chr(10) + "class: CORE",
               "id: audit.operation_log" + chr(10) + "中文名: 核心审计（谁在什么时候对什么做了什么）" + chr(10) + "class: KERNEL")


def b_short_why(sb: Sandbox) -> None:
    """把一条的 why 砍到两个字（等于没写为什么是这一档）。"""
    sb.replace(MAP, "why: 只增不改的事实，全项目所有域都能往里写一条，但格式与落库只有一处实现（判定规则 1）",
               "why: 审计")


def b_rename_event(sb: Sandbox) -> None:
    """§5.2 里把一个真事件改成一个不存在的名字（代码里产生的事件没人认领）。"""
    sb.replace(MAP, "| " + TICK + "orders.created" + TICK + " |", "| " + TICK + "orders.bogus" + TICK + " |")


def b_fake_event(sb: Sandbox) -> None:
    """§5.2 里塞一条代码里根本不产生的事件（化石）。"""
    row = ("| " + TICK + "notifications.unread_changed" + TICK + " | " + TICK + "notification.data"
           + TICK + " | 未读数变了 | 同上 | ❌ 不会 |")
    sb.replace(MAP, row, row + chr(10) + "| " + TICK + "fake.event" + TICK + " | " + TICK
               + "money.ledger" + TICK + " | 假事件 | 无 | ❌ 不会 |")


def b_event_is_business(sb: Sandbox) -> None:
    """把 §5.2 某一行的结论改成 ✅（＝ 这个事件其实在承担核心业务）。"""
    sb.replace(MAP, "❌ 不会（订单行已在库里）", "✅ 会改变核心事实")


def b_point_without_contract(sb: Sandbox) -> None:
    """把一个扩展点的契约摘掉（铁律 4：没有契约的扩展点只是愿望）。"""
    sb.replace(MAP, "id: pricing.freight" + chr(10) + "中文名: 运费计算（这一单该收多少）" + chr(10)
               + "class: EXTENSION_POINT" + chr(10) + "domain: freight" + chr(10) + "owns: -" + chr(10)
               + "contract: PricingContract v1",
               "id: pricing.freight" + chr(10) + "中文名: 运费计算（这一单该收多少）" + chr(10)
               + "class: EXTENSION_POINT" + chr(10) + "domain: freight" + chr(10) + "owns: -" + chr(10)
               + "contract: -")


def b_ghost_impl(sb: Sandbox) -> None:
    """impl 指向一个不存在的符号（防化石那一组该红）。"""
    sb.replace(MAP, "impl: services/order_flow.py", "impl: services/order_flow.py::this_symbol_never_existed")


def b_unknown_domain(sb: Sandbox) -> None:
    """把一个域写成不存在的名字（该域没人定档 + 图上出现假域，两组都该红）。"""
    sb.replace(MAP, "id: inventory.movement" + chr(10) + "中文名: 库存流水（货动了没有）" + chr(10)
               + "class: CORE" + chr(10) + "domain: inventory",
               "id: inventory.movement" + chr(10) + "中文名: 库存流水（货动了没有）" + chr(10)
               + "class: CORE" + chr(10) + "domain: warehouse")


def b_empty_map(sb: Sandbox) -> None:
    """把整张图掏空成一条（块数下限 + 表归属两组都该红）。"""
    sb.write(MAP, "# 反向验证：图被掏空" + chr(10) + chr(10) + FENCE + "capability" + chr(10)
             + "id: x" + chr(10) + "中文名: x" + chr(10) + "class: CORE" + chr(10) + "domain: -" + chr(10)
             + "owns: -" + chr(10) + "contract: -" + chr(10)
             + "why: 反向验证注入用的假条目，需要够长才不会被长度判据先拦住" + chr(10)
             + "impl: main.py" + chr(10) + "pending: no" + chr(10) + FENCE + chr(10))


def b_pending_flood(sb: Sandbox) -> None:
    """把所有条目都标成 pending（＝ 用 pending 躲判定）。"""
    sb.sub(MAP, "pending: no",
           "pending: yes" + chr(10) + "pending_reason: 反向验证注入用的理由，需要够长才不会被长度判据先拦住")


def b_event_hidden_rpc(sb: Sandbox) -> None:
    """§28 的核心场景：让发件箱派发表去调一个**业务服务**（事件变成隐形 RPC）。"""
    # ⚠️ 锚点必须**唯一**：第一版用「    raise RuntimeError(」当锚点，而 main.py 里有两处，
    #    注入当场抛 AssertionError（实测）—— 注入脚本自己的失败会被误读成「判据不红」。
    anchor = '    raise RuntimeError("发件箱没有登记处理器：'
    sb.replace(MAIN, anchor,
               "    await accounting_service.create_receipt(1, 1)" + chr(10) + anchor)


# ------------------------------------------------ 契约判据的注入

def c_ok(sb: Sandbox) -> None:
    """正面前提。"""


def c_bad_version(sb: Sandbox) -> None:
    """把契约版本改成 9（§31 坑 13：不许留 10 代接口）。"""
    sb.replace(CONTRACTS / "pricing.py", "CONTRACT_VERSION = 1", "CONTRACT_VERSION = 9")


def c_impl_in_contract(sb: Sandbox) -> None:
    """让契约模块偷偷 import 数据库（契约里藏了实现）。"""
    sb.append(CONTRACTS / "unit_conversion.py", chr(10) + "from sqlalchemy import select" + chr(10))


def c_core_imports_extension(sb: Sandbox) -> None:
    """让核心契约包 import 具体扩展（Core -> Extension 是禁止方向）。"""
    sb.append(CONTRACTS / "money.py", chr(10) + "from app.extensions import unit_conversion as _ext" + chr(10))


def c_plugin_base(sb: Sandbox) -> None:
    """造一个万能插件基类（指南 §7 明确否掉）。"""
    sb.append(CONTRACTS / "pricing.py",
              chr(10) + chr(10) + "class Plugin:" + chr(10) + "    def initialize(self):" + chr(10)
              + "        pass" + chr(10) + chr(10) + "    def execute(self):" + chr(10) + "        pass" + chr(10))


def c_wrong_output_type(sb: Sandbox) -> None:
    """把 PricingResult.money 的注解改成裸 Decimal（核心就不再"只接受 Money"了）。"""
    sb.replace(CONTRACTS / "pricing.py", "    money: Money", "    money: Decimal")


def c_quantum_changed(sb: Sandbox) -> None:
    """改掉 QUANTUM（钱的最小单位变了，而全项目那十几处没跟着变）。"""
    sb.replace(CONTRACTS / "money.py", 'QUANTUM = Decimal("0.01")', 'QUANTUM = Decimal("0.001")')


def c_missing_rounding(sb: Sandbox) -> None:
    """删掉某一处既有实现的 rounding=（退回 ROUND_HALF_EVEN，半分上差一分钱）。"""
    sb.sub(APP / "services" / "order_money.py", ', rounding=ROUND_HALF_UP)', ")")


def c_wrong_rounding(sb: Sandbox) -> None:
    """把某一处两位小数的进位方式改成 ROUND_HALF_EVEN。"""
    sb.sub(APP / "api" / "v1" / "price_rules.py", "ROUND_HALF_UP", "ROUND_HALF_EVEN")


def c_missing_element(sb: Sandbox) -> None:
    """把文档里的「生命周期」全部改名（六个要素少一个）。"""
    sb.sub(CDOC, "生命周期", "生存期")


# ------------------------------------------------ 依赖防火墙判据的注入


def d_ok(sb: Sandbox) -> None:
    """正面前提。"""


def d_core_imports_ext(sb: Sandbox) -> None:
    """让一个核心 service 去 import 具体扩展（Core -> Extension 是禁止方向）。"""
    sb.append(CORE_SVC, chr(10) + "from app.extensions import unit_conversion  # rv" + chr(10))


def d_ext_imports_private(sb: Sandbox) -> None:
    """让扩展去 import 核心私有内部（规则④）。"""
    sb.append(EXT_INIT, chr(10) + "from app.services import accounting_service  # rv" + chr(10))


def d_ext_auth(sb: Sandbox) -> None:
    """让扩展自己写一套鉴权（§31 坑 11）。"""
    sb.append(EXT_INIT, chr(10) + "def rv_guard(user):" + chr(10)
              + "    return require_permission(user)" + chr(10))


# ------------------------------------------------ 数据归属判据的注入


def o_ok(sb: Sandbox) -> None:
    """正面前提。"""


def o_write(sb: Sandbox) -> None:
    """让扩展写一行数据（§31 坑 4）。"""
    sb.append(EXT_INIT, chr(10) + "def rv_write(db, obj):" + chr(10) + "    db.add(obj)" + chr(10))


def o_ledger(sb: Sandbox) -> None:
    """让扩展碰到账本那一路（§31 坑 5，最高危）。"""
    sb.append(EXT_INIT, chr(10) + "RV_LEDGER_TABLE = 'ledgers'" + chr(10))


def o_ghost_core_table(sb: Sandbox) -> None:
    """往核心表清单里塞一个模型里不存在的表名（防化石那一组该红）。"""
    sb.replace(MAP, "owns: ledgers, cash_flows,", "owns: ledgers_v2, cash_flows,")


def o_missing_snapshot(sb: Sandbox) -> None:
    """删掉订单上的计费规则快照列（历史就不再可解释，§31 坑 9）。"""
    sb.sub(MODELS_ORDER, "driver_rule_snapshot", "rv_dropped_rule_snapshot")


# ------------------------------------------------ 扩展清单判据的注入


def m_ok(sb: Sandbox) -> None:
    """正面前提。"""


def m_field_removed(sb: Sandbox) -> None:
    """把清单的一个字段从 dataclass 里删掉（三方一致那条该红）。"""
    sb.replace(REGISTRY, "    emits: tuple[str, ...] = ()" + chr(10), "")


def m_kind_removed(sb: Sandbox) -> None:
    """把四类扩展删掉一类。"""
    sb.replace(REGISTRY, '"pure-function", "policy", "provider", "presentation"',
               '"pure-function", "policy", "provider"')


def m_doc_field_removed(sb: Sandbox) -> None:
    """把文档里的一个必备字段名改名（文档覆盖度那条该红）。"""
    sb.sub(EDOC, "compatibility", "兼容性")


def m_exec_in_registry(sb: Sandbox) -> None:
    """在注册表里加一句 eval（动态加载禁令那条该红）。"""
    sb.append(REGISTRY, chr(10) + "RV_X = eval('1+1')" + chr(10))


def m_env_in_extension(sb: Sandbox) -> None:
    """让扩展直接读环境变量（配置必须走注册表那条该红）。"""
    sb.append(EXT_INIT, chr(10) + "import os as _rv_os" + chr(10)
              + "RV_ENV = _rv_os.environ.get('CORE_DATABASE_URL')" + chr(10))


# (说明, 判据, 场景, 期望)；期望 = ("red", 关键字) 或 ("green", "")
SCENARIOS = [
    ("✅ 正面前提：边界图不动 → 应当通过", "boundary", b_ok, ("green", "")),
    ("把 orders 从图上摘掉（有东西没定档）", "boundary", b_orphan_table, ("red", "都在图上")),
    ("owns 里塞一个不存在的表名", "boundary", b_ghost_table, ("red", "不存在的表名")),
    ("两张能力同时认领 orders", "boundary", b_double_owner, ("red", "两个归属")),
    ("class 改成四档之外的 KERNEL", "boundary", b_bad_class, ("red", "四档之一")),
    ("把一条的 why 砍成两个字", "boundary", b_short_why, ("red", "why ≥")),
    ("§5.2 里把一个真事件改成假名字", "boundary", b_rename_event, ("red", "没人认领")),
    ("§5.2 里塞一条代码不产生的事件", "boundary", b_fake_event, ("red", "化石")),
    ("§5.2 把某一行的结论改成 ✅（事件在承担业务）", "boundary", b_event_is_business, ("red", "全是 ❌")),
    ("把一个扩展点的 contract 摘掉", "boundary", b_point_without_contract, ("red", "都写了 contract")),
    ("impl 指向不存在的符号", "boundary", b_ghost_impl, ("red", "实现站点全部存在")),
    ("把一个域写成不存在的名字", "boundary", b_unknown_domain, ("red", "没被定档的域")),
    ("把整张图掏空成一条", "boundary", b_empty_map, ("red", "边界图有")),
    ("把所有条目都标成 pending", "boundary", b_pending_flood, ("red", "pending 的条数")),
    ("§28：派发表里加一个业务服务调用", "boundary", b_event_hidden_rpc, ("red", "白名单内")),
    ("✅ 正面前提：契约不动 → 应当通过", "contracts", c_ok, ("green", "")),
    ("把契约版本改成 9", "contracts", c_bad_version, ("red", "不许留 10 代接口")),
    ("让契约模块偷偷 import 数据库", "contracts", c_impl_in_contract, ("red", "不碰库")),
    ("让核心契约包 import 具体扩展", "contracts", c_core_imports_extension, ("red", "没有 import app.extensions")),
    ("造一个万能插件基类", "contracts", c_plugin_base, ("red", "都没有 Plugin")),
    ("把 PricingResult.money 的注解改成 Decimal", "contracts", c_wrong_output_type, ("red", "不接受扩展自己的对象")),
    ("改掉 QUANTUM（钱的最小单位）", "contracts", c_quantum_changed, ("red", "ROUNDING = ROUND_HALF_UP")),
    ("删掉某一处既有实现的 rounding=", "contracts", c_missing_rounding, ("red", "显式写了")),
    ("把某一处两位小数的进位改成 ROUND_HALF_EVEN", "contracts", c_wrong_rounding, ("red", "两位小数那一档")),
    ("把文档里的「生命周期」全部改名", "contracts", c_missing_element, ("red", "每个契约各一份")),
    ("✅ 正面前提：防火墙不动 → 应当通过", "dependencies", d_ok, ("green", "")),
    ("让核心 service import 具体扩展", "dependencies", d_core_imports_ext, ("red", "能 import app.extensions")),
    ("让扩展 import 核心私有内部", "dependencies", d_ext_imports_private, ("red", "越界 import")),
    ("让扩展自己写一套鉴权", "dependencies", d_ext_auth, ("red", "一行鉴权都没有")),
    ("✅ 正面前提：数据归属不动 → 应当通过", "ownership", o_ok, ("green", "")),
    ("让扩展写一行数据", "ownership", o_write, ("red", "一条写语句都没有")),
    ("让扩展碰到账本那一路", "ownership", o_ledger, ("red", "碰不到账本")),
    ("往核心表清单里塞一个不存在的表", "ownership", o_ghost_core_table, ("red", "模型里没有")),
    ("删掉订单上的计费规则快照列", "ownership", o_missing_snapshot, ("red", "历史快照")),
    ("✅ 正面前提：扩展清单不动 → 应当通过", "manifest", m_ok, ("green", "")),
    ("把清单的一个字段从 dataclass 删掉", "manifest", m_field_removed, ("red", "REQUIRED_FIELDS 一致")),
    ("把四类扩展删掉一类", "manifest", m_kind_removed, ("red", "两项下限都达标")),
    ("把文档里的一个必备字段名改名", "manifest", m_doc_field_removed, ("red", "每个必备字段都在文档里写了")),
    ("在注册表里加一句 eval", "manifest", m_exec_in_registry, ("red", "都没有 exec")),
    ("让扩展直接读环境变量", "manifest", m_env_in_extension, ("red", "不许直接读环境变量")),
]


def main() -> int:
    if "--list" in sys.argv[1:]:
        for label, which, _setup, _expect in SCENARIOS:
            print("[" + which + "] " + label)
        return 0
    for which, path in CHECKS.items():
        if not path.exists():
            print("❌ 找不到 " + str(path))
            return 1

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        for which in CHECKS:
            code, out = run_check(which)
            if code != 0:
                print("❌ 前提不成立：" + which + " 在源码完好时没过" + chr(10) + out[-1200:])
                return 1
            last = [ln for ln in out.splitlines() if ln.strip()][-1]
            print("✅ 前提：" + which + " 在源码完好时是绿的 —— " + last.strip()[:110])
        print()

        for label, which, setup, expect in SCENARIOS:
            sb.restore()
            setup(sb)
            try:
                code, out = run_check(which)
            finally:
                sb.restore()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            kind, keyword = expect
            if kind == "green":
                hit = code == 0
                detail = "通过（这正是要的）" if hit else ("按格式写好后仍报红：" + (fails[0].strip()[:80] if fails else "?"))
            else:
                hit = code != 0 and any(keyword in ln for ln in fails)
                detail = "实际红 " + str(len(fails)) + " 条" + ("" if hit else "：" + str([f.strip()[:70] for f in fails[:2]]))
            print("  [" + ("OK" if hit else "MISS") + "] " + label + " → " + detail)
            if not hit:
                bad += 1

        sb.restore()
        for which in CHECKS:
            code, _out = run_check(which)
            ok = code == 0
            print("  [OK] 还原后 " + which + " 全绿" if ok else "  [MISS] 还原后 " + which + " 没恢复")
            bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    total = len(SCENARIOS) + len(CHECKS)
    print()
    if bad:
        print("❌ " + str(bad) + "/" + str(total) + " 条不成立")
        return 1
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：每条注入都让判据点出了那一条，正面场景也能过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())