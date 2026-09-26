"""反向验证：把「工作台头部＝一行 + 右侧描边胶囊」那条红线逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这条规则的坏法**全部不报错、不崩** ——
头部又长回三行只是"页面看着也挺正常"；右边胶囊变回实底只是"重了一点"；
抄了图一的铃铛只是**和底部导航那颗红点重复**；文案里又写上"货主端"只是重复一句话；
给司机端加个工作台只是多一个 Tab。用户是照着截图提要求的人，这些都得由机器守着。

⚠️ 有两处注入**故意打在最容易漏的地方**：`_install_all.py` 的角色强标志（改了文案不改它，
装包脚本会报"没抓到角色"而 App 一切正常）、以及单测里**司机**那条断言（货主那端有一模一样的
字符串，只锚 content 的话把它翻成 assertTrue 也照样绿）。

用法：python _tools/qa/_reverse_verify_workbench_header.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_workbench_header.py"

WORKBENCH = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/home/WorkbenchScreen.kt"
COMPONENTS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt"
MODULES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Modules.kt"
HEADER_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/home/WorkbenchHeaderTest.kt"
INSTALL = ROOT / "_tools/qa/_install_all.py"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

# (说明, 文件, 原文, 替换成, 期望变红的那条检查名关键词)
MUTATIONS = [
    (
        "头部又长回三行（里面套一个 Column —— 「长而扁」这条要求当场没了）",
        WORKBENCH,
        "            Text(\n                workbenchHeaderText(role),",
        "            Column {\n            Text(\n                workbenchHeaderText(role),",
        "只有 1 个行容器",
    ),
    (
        "左边那半句不再来自唯一判据（就地写一个字面量）",
        WORKBENCH,
        "                workbenchHeaderText(role),\n",
        '                "工作台",\n',
        "左边那条文案来自唯一那处判据",
    ),
    (
        "右边那颗胶囊被换成裸文字（用户要的就是那颗「管理员那种形式」的胶囊）",
        WORKBENCH,
        "            RoleBadge(role.key)",
        "            Text(role.key)",
        "右边就是角色胶囊",
    ),
    (
        "可伸缩的文本丢了 weight（它会去吃宽度、把右边的胶囊挤瘪 —— §4.19 第二条教训）",
        WORKBENCH,
        "                modifier = Modifier.weight(1f),\n            )\n            Spacer(Modifier.width(10.dp))",
        "                modifier = Modifier,\n            )\n            Spacer(Modifier.width(10.dp))",
        "文案吃剩余宽度",
    ),
    (
        "改成「放不下就切」（maxLines = 1 + Ellipsis）—— §4.19 明令不缩字号、不截断",
        WORKBENCH,
        "                maxLines = 2,\n",
        "                maxLines = 1,\n                overflow = TextOverflow.Ellipsis,\n",
        "Ellipsis",
    ),
    (
        "把图一的**铃铛/未读**抄进来（用户：「未读的那个不需要，导航栏已经有了」）",
        WORKBENCH,
        "            Spacer(Modifier.width(10.dp))\n            RoleBadge(role.key)",
        "            Spacer(Modifier.width(10.dp))\n"
        "            Icon(Icons.Default.Notifications, contentDescription = null)\n"
        "            RoleBadge(role.key)",
        "没有铃铛/未读",
    ),
    (
        "把图一的**扫码**抄进来（我们本来就没有扫码）",
        WORKBENCH,
        "            Spacer(Modifier.width(10.dp))\n            RoleBadge(role.key)",
        "            Spacer(Modifier.width(10.dp))\n"
        '            Icon(Icons.Default.QrCodeScanner, contentDescription = "扫码")\n'
        "            RoleBadge(role.key)",
        "没有扫码",
    ),
    (
        "胶囊上又加回下拉三角（用户：「不需要那个三角」）",
        COMPONENTS,
        "            modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp),\n        )\n    }\n}",
        "            modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp),\n        )\n"
        "        Icon(Icons.Default.ArrowDropDown, contentDescription = null)\n    }\n}",
        "胶囊上没有下拉三角",
    ),
    (
        "胶囊的描边被拿掉（变回没有边界的一块字）",
        COMPONENTS,
        "        border = BorderStroke(1.dp, accent),\n",
        "",
        "用的是 `Surface` + `border`",
    ),
    (
        "别处又冒出一份角色配色（两份必然分叉：换个角色色要改两处）",
        WORKBENCH,
        "fun workbenchHeaderText(role: Role): String = when (role) {",
        'internal fun rolePaletteOf(r: String) = "第二份"\n\n'
        "fun workbenchHeaderText(role: Role): String = when (role) {",
        "只有一处定义",
    ),
    (
        "某一支少给一档色（暗色页面上那颗胶囊就糊了）",
        COMPONENTS,
        '    "shipper" -> RolePalette("货主", Color(0xFF005A78), Color(0xFF8FDCF0))',
        '    "shipper" -> RolePalette("货主", Color(0xFF005A78))',
        "亮/暗两档色",
    ),
    (
        "左文案里又写上「货主端」（与右边胶囊重复 —— 用户要的就是「一行概括」）",
        WORKBENCH,
        'Role.SHIPPER -> "工作台 · 订单与账本"',
        'Role.SHIPPER -> "货主端 · 订单与账本"',
        "不再出现「货主端",
    ),
    (
        "顺手给**司机端**也加一个工作台 Tab（用户第 1.1 条：司机不做）",
        MODULES,
        '        Role.DRIVER -> listOf(\n'
        '            BottomTab("进行中", Icons.Default.LocalShipping, "driverOpen", color = ProgressYellow),',
        '        Role.DRIVER -> listOf(\n'
        '            BottomTab("工作台", Icons.Default.Apps, "workbench", color = NavBlue),\n'
        '            BottomTab("进行中", Icons.Default.LocalShipping, "driverOpen", color = ProgressYellow),',
        "司机端的 Tab 里**没有**工作台",
    ),
    (
        "装包脚本的角色强标志退回旧文案（App 一切正常，但装包脚本从此报「没抓到角色」）",
        INSTALL,
        'STRONG_MARK = ("工作台 · 全量管理", "工作台 · 订单与账本")',
        'STRONG_MARK = ("派单端 · 全量管理", "货主端 · 订单与账本")',
        "旧文案",
    ),
    (
        "单测里**司机**那条断言被翻成 assertTrue（货主那端有一模一样的字符串，只锚 content 会漏）",
        HEADER_TEST,
        "        assertFalse(\n            \"司机端不该有工作台 Tab",
        "        assertTrue(\n            \"司机端不该有工作台 Tab",
        "单测钉着「司机端没有工作台这一屏」",
    ),
    (
        "设计规范里删掉指路（规矩还在，但没人找得到判据脚本）",
        DESIGN,
        "`_tools/qa/_check_workbench_header.py`（含反向验证）",
        "判据脚本（名字待补）",
        "指路到本判据",
    ),
    (
        "定位表「工作台」那一行不再指路判据（改了却没更新地图）",
        LOCATOR,
        "红线 `_tools/qa/_check_workbench_header.py`",
        "红线（脚本名待补）",
        "指路到本判据",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out



def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**（R3-07b）：写回后**重新读回来逐字节比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是（L2 要的就是这一句）。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1500:]}")
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            restore_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
