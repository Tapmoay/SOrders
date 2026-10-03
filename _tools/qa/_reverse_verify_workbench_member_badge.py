# -*- coding: utf-8 -*-
"""反向验证：把「工作台右上角那颗胶囊按实际身份写字」（CHG-0033）**逐条打断**，
看 `_tools/qa/_check_workbench_member_badge.py` 是否每次都报红。

用法（从仓库根）：python _tools/qa/_reverse_verify_workbench_member_badge.py

纪律（与兄弟脚本一致）：

* 先确认**源码完好时判据是全绿的**（前提不成立就直接失败，不做任何注入）；
* 每条注入只改一处、改完立刻跑判据、`finally` 里**逐字节还原**；
* 结束时核对「被碰过的文件与运行前逐字节一致」；
* 注入没生效（锚点变了 → 替换结果与原文件相同）算 **SKIP = 失败**，
  因为那意味着这条注入已经**证明不了任何事**，而不是「通过」；
* 全程拿着 `lock_reverse_verify`：注入期间别的检查看这份工作区会得到不可信的结论。

这 18 条对应的正是这条需求最容易被「改回去 / 抄一份 / 忘了传」的写法：
删那一支色、标签改回「货主」、借名册的琥珀色、丢掉只对货主生效那道门、映射退化成照抄、
映射被抄第二份、默认值翻成 true（fail-open）、胶囊绕开映射、工作台忘了交身份、
问不到时按批发商兜底、重新问的条件挪走、整段取数被删、单测不再调纯函数、
规范里那条规矩被抹掉、定位表不再指路、装包脚本的强标志里塞进胶囊上的字、登记簿撤行、
以及本脚本自己摘掉注入锁。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools/ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = ROOT / "_tools/qa/_check_workbench_member_badge.py"

COMP = "android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt"
WORK = "android/app/src/main/java/com/tapmoay/sorders/ui/home/WorkbenchScreen.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/common/RoleBadgeKeyTest.kt"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
INSTALL = "_tools/qa/_install_all.py"
REGISTRY = "docs/changes/README.md"
SELF = "_tools/qa/_reverse_verify_workbench_member_badge.py"

#: 反引号与引号**不写进源码字面量**：这样整份脚本里不会出现「某种引号被迫转义」的角落。
BT = chr(96)
Q = chr(34)

#: 色源里那一支（一整行，与 Components.kt 里逐字一致）
ARM = f"{Q}shipper_member{Q} -> RolePalette({Q}批发商{Q}, Color(0xFF005A78), Color(0xFF8FDCF0))"
#: 纯函数里那一行（含两个维度的判断）
GATE = f"if (roleKey == {Q}shipper{Q} && memberShipper) {Q}shipper_member{Q} else roleKey"
#: 工作台里那条注释（拿它当「往文件里塞东西」的落点 —— 注释被改不影响别的判据）
ONE_COL = "/** 一屏 4 列（与改造前的工作台同一列数：图标大小、字距都不用重新适应） */"
REMEMBER_BLOCK = (
    "    var memberShipper by remember(role.key) { mutableStateOf(false) }\n"
    "    LaunchedEffect(role.key) {\n"
    "        memberShipper = runCatching { container.repo.me().isMember }.getOrDefault(false)\n"
    "    }\n"
)
REMEMBER_KEPT = (
    "    var memberShipper by remember(role.key) { mutableStateOf(false) }\n"
    "    // 故意不问身份：把 LaunchedEffect 那一段整段删掉（模拟「忘了问」）。\n"
    "    // 这一段的长度留在反空转的下限之上，否则命中的会是反空转那条而不是这一条。\n"
)
#: 定位表那一行尾部那条指路（只删「指路」这一截，不动整行）
LOC_TAIL = (
    f"红线 {BT}_tools/qa/_check_workbench_member_badge.py{BT}"
    f"（含反向验证 {BT}_tools/qa/_reverse_verify_workbench_member_badge.py{BT}）"
)
STRONG = f"STRONG_MARK = ({Q}工作台 · 全量管理{Q}, {Q}工作台 · 订单与账本{Q})"
IMPORT_LINE = "from _airepo import lock_reverse_verify, unlock_reverse_verify\n"
MAIN_BODY = (
    "    lock_reverse_verify()\n"
    "    try:\n"
    "        return run_all()\n"
    "    finally:\n"
    "        unlock_reverse_verify()"
)


# --------------------------------------------------------------- 18 条注入

#: 每条只改一处，改完立刻跑判据。末列是**判据应当报红那一行里的关键词**
#: （判词里的原话，不是源码锚点）：钉的是「判据仍然认这件事」，而不是「源码长得像这样」。


def _drop_arm(s: str) -> str:
    """① 把色源里多出来的那一支整行删掉（回到「批发商也照货主画」）。"""
    return s.replace("    " + ARM + "\n", "")


def _arm_back_to_owner(s: str) -> str:
    """② 那一支还在，但标签改回「货主」。"""
    return s.replace(ARM, ARM.replace("批发商", "货主"))


def _arm_borrows_roster_amber(s: str) -> str:
    """③ 那一支借了名册小标的琥珀色（把「与货主同族」这条改回去）。"""
    return s.replace(
        ARM,
        ARM.replace(
            "Color(0xFF005A78), Color(0xFF8FDCF0)",
            "Color(0xFFFFF1C6), Color(0xFF7A5900)",
        ),
    )


def _gate_drop_role(s: str) -> str:
    """④ 丢掉只对货主生效那道门：身份溢出成第四种角色。"""
    return s.replace(GATE, f"if (memberShipper) {Q}shipper_member{Q} else roleKey")


def _gate_collapse(s: str) -> str:
    """⑤ 映射退化成照抄键（等于没做这个映射）。"""
    return s.replace("    " + GATE, "    roleKey")


def _map_copied_into_workbench(s: str) -> str:
    """⑥ 把映射抄第二份进工作台（全树就不止一处真源了）。"""
    body = f"internal fun roleBadgeKey(roleKey: String, memberShipper: Boolean): String =\n    {GATE}\n\n"
    return s.replace(ONE_COL, body + ONE_COL)


def _badge_default_true(s: str) -> str:
    """⑦ 胶囊那一维的默认值翻成 true（fail-open：谁忘了传都按批发商画）。"""
    return s.replace(
        "fun RoleBadge(role: String, memberShipper: Boolean = false) {",
        "fun RoleBadge(role: String, memberShipper: Boolean = true) {",
    )


def _badge_bypasses_map(s: str) -> str:
    """⑧ 胶囊绕开映射，直接按角色取色。"""
    return s.replace(
        "    val p = rolePaletteOf(roleBadgeKey(role, memberShipper))",
        "    val p = rolePaletteOf(role)",
    )


def _workbench_forgets_identity(s: str) -> str:
    """⑨ 工作台忘了把身份交给胶囊。"""
    return s.replace(
        "            RoleBadge(role.key, memberShipper)",
        "            RoleBadge(role.key)",
    )


def _fallback_to_member(s: str) -> str:
    """⑩ 问不到身份时改按批发商兜底（fail-open）。"""
    return s.replace(".getOrDefault(false)", ".getOrDefault(true)")


def _ask_not_keyed_on_role(s: str) -> str:
    """⑪ 重新问的条件从 role.key 挪走（换号不重问）。"""
    return s.replace(
        "remember(role.key) { mutableStateOf(false) }",
        "remember(role) { mutableStateOf(false) }",
    ).replace("LaunchedEffect(role.key) {", "LaunchedEffect(Unit) {")


def _never_asks(s: str) -> str:
    """⑫ 整段取数被删：工作台从此不问自己的身份。"""
    return s.replace(REMEMBER_BLOCK, REMEMBER_KEPT)


def _test_stops_calling_pure(s: str) -> str:
    """⑬ 单测不再调那个纯函数。"""
    return s.replace("roleBadgeKey(", "roleBadgeX(")


def _design_rule_erased(s: str) -> str:
    """⑭ 规范 §4.13 里那条规矩被抹掉（函数名在规范里整个消失）。

    注：只把两个参数改成一个是**注不掉的** —— 判据查的是「roleBadgeKey 这个词在不在」
    （"roleBadgeKey" in sec），所以注入必须让这个词从那个 4000 字符窗口里消失。
    """
    return s.replace("roleBadgeKey", "roleBadgeMap")


def _locator_stops_pointing(s: str) -> str:
    """⑮ 定位表里那行不再指路本判据。"""
    return s.replace(LOC_TAIL, "（已改写：不再指路本判据）")


def _install_marker_gets_label(s: str) -> str:
    """⑯ 装包脚本的强标志里塞进胶囊上的字（把角色判据从头部文案改成这枚字）。"""
    return s.replace(STRONG, STRONG[:-2] + f", {Q}批发商{Q})")


def _registry_row_gone(s: str) -> str:
    """⑰ 登记簿里撤掉 CHG-0033 这一行。"""
    return s.replace(f"| {BT}CHG-0033{BT} | CHG |", f"| {BT}CHG-XXXX{BT} | CHG |")


def _self_drops_lock(s: str) -> str:
    """⑱ 本脚本自己摘掉注入锁。

    注：unlock_reverse_verify 里**含子串** lock_reverse_verify，docstring 里也提过一次
    —— 判据查的是「这个词在不在文件里」（"lock_reverse_verify" in rev），所以只删
    import 与那两处调用是**注不掉的**，必须让这个词整个消失。
    """
    return (
        s.replace(IMPORT_LINE, "")
        .replace(MAIN_BODY, "    return run_all()")
        .replace("lock_reverse_verify", "locked_x")
    )


CASES = [
    ("① 色源里那一支被删掉", COMP, _drop_arm, "多出来的那一支的键是"),
    ("② 那一支的标签改回「货主」", COMP, _arm_back_to_owner, "那一支写着「批发商」"),
    ("③ 那一支借了名册的琥珀色", COMP, _arm_borrows_roster_amber, "批发商与货主同一族色"),
    ("④ 丢掉只对货主生效那道门", COMP, _gate_drop_role, "那道门写着 roleKey == shipper"),
    ("⑤ 映射退化成照抄键", COMP, _gate_collapse, "两种身份各回各的键"),
    ("⑥ 映射被抄第二份进工作台", WORK, _map_copied_into_workbench, "全树只有一个 roleBadgeKey"),
    ("⑦ 胶囊那一维的默认值翻成 true", COMP, _badge_default_true, "RoleBadge 收下身份那一维，默认 false"),
    ("⑧ 胶囊绕开映射", COMP, _badge_bypasses_map, "体内只有一次 rolePaletteOf"),
    ("⑨ 工作台忘了交身份", WORK, _workbench_forgets_identity, "那颗胶囊被喂上身份"),
    ("⑩ 问不到时按批发商兜底", WORK, _fallback_to_member, "问不到就当普通货主"),
    ("⑪ 重新问的条件挪离 role.key", WORK, _ask_not_keyed_on_role, "重新问的条件挂在 role.key 上"),
    ("⑫ 整段取数被删（从此不问）", WORK, _never_asks, "工作台真的问了一次自己的身份"),
    ("⑬ 单测不再调纯函数", TEST, _test_stops_calling_pure, "单测真的在调纯函数"),
    ("⑭ 规范 §4.13 里那条规矩被抹掉", DESIGN, _design_rule_erased, "规范 §4.13 里写了这条规矩"),
    ("⑮ 定位表不再指路本判据", LOCATOR, _locator_stops_pointing, "定位表「工作台」那一行指路到本判据"),
    ("⑯ 装包强标志里塞进胶囊上的字", INSTALL, _install_marker_gets_label, "装包脚本认角色靠头部文案"),
    ("⑰ 登记簿里撤掉 CHG-0033 这一行", REGISTRY, _registry_row_gone, "登记簿里有 CHG-0033 这一行"),
    ("⑱ 本脚本自己摘掉注入锁", SELF, _self_drops_lock, "反验脚本拿着注入锁"),
]


# --------------------------------------------------------------- 脚手架


def read_src(rel):
    """读成 LF 规范化文本，并记住原本是不是 CRLF（写回时要还原）。"""
    path = rel if isinstance(rel, Path) else (ROOT / rel)
    data = path.read_bytes()
    crlf = b"\r\n" in data
    return path, data.decode("utf-8").replace("\r\n", "\n"), crlf


def write_src(path: Path, text: str, crlf: bool) -> None:
    out = text.replace("\n", "\r\n") if crlf else text
    path.write_bytes(out.encode("utf-8"))


def run_judge():
    r = subprocess.run(
        [sys.executable, str(JUDGE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def hit(out: str, want: str) -> bool:
    """判据报红的那一行里必须出现关键词（只认 [FAIL] 行，防「别处碰巧提到」）。"""
    for ln in out.splitlines():
        if "[FAIL]" in ln and want in ln:
            return True
    return False


def run_all() -> int:
    rc, out = run_judge()
    if rc != 0:
        print("❌ 前提不成立：源码完好时判据必须是绿的，实际 rc=" + str(rc))
        print(out[-4000:])
        return 1
    print("前提成立：源码完好时判据全绿。")
    print("")
    touched = {}
    ok = 0
    skipped = []
    missed = []
    try:
        for label, rel, mutate, want in CASES:
            path, plain, crlf = read_src(rel)
            if path not in touched:
                touched[path] = (plain, crlf)
            mutated = mutate(plain)
            if mutated == plain:
                print("  [SKIP] " + label + " —— 注入没生效（锚点过期，请更新本脚本的常量）")
                skipped.append(label)
                continue
            write_src(path, mutated, crlf)
            try:
                rc2, out2 = run_judge()
            finally:
                write_src(path, plain, crlf)
            if rc2 != 0 and hit(out2, want):
                print("  [OK]   " + label + " → 判据报红：" + want)
                ok += 1
            else:
                print("  [!!]   " + label + " → 期望判据报红「" + want + "」，实际 rc=" + str(rc2))
                missed.append(label)
    finally:
        for path, (plain, crlf) in touched.items():
            write_src(path, plain, crlf)
    dirty = []
    for path, (plain, crlf) in touched.items():
        if read_src(path)[1] != plain:
            dirty.append(str(path.relative_to(ROOT)))
    print("")
    if dirty:
        print("❌ 还原检查：这些文件没还原干净：" + "、".join(dirty))
        return 1
    print("✅ 还原检查：" + str(len(touched)) + " 个被碰过的文件与运行前逐字节一致")
    if skipped:
        print("❌ " + str(len(skipped)) + " 条注入没生效（锚点过期）：" + "、".join(skipped))
    if missed:
        print("❌ " + str(len(missed)) + " 条注入没能让判据报红：" + "、".join(missed))
    if skipped or missed:
        return 1
    print("✅ " + str(ok) + " 条注入都证明「工作台胶囊按实际身份写字」真的被钉住了。")
    return 0


def main() -> int:
    print("反向验证 · 工作台那颗胶囊按实际身份写字（CHG-0033）")
    print("判据：" + str(JUDGE.relative_to(ROOT)))
    print("")
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    sys.exit(main())