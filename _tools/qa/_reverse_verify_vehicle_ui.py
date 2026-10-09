# -*- coding: utf-8 -*-
r"""反向验证「车辆管理页按规范重做（列表与卡片）」这条红线**真的会红**（CHG-0016，2026-10-03）。

## 为什么这条要反向验证
本批判据查的四件事，每一件都有自己典型的失效方式，而且**都不影响编译**：

1. **黄绿只有一个定义**（跨文件性质）：谁都能在任意一个文件里再写一遍 0xFF9AA35F ——
   界面照样好看、编译照样过，只有下一个人改色时才发现少改了一处。本脚本把色值塞回三个不同的文件，
   逼判据把它们都认出来。
2. **卡片动作的形态与位置**（规范 §4.2c）：把圈底动作换回裸 IconButton、把 label 拿掉、
   把编辑那枚挪到最左边 —— 三种都是「顺手一改」，肉眼审代码时最容易被放过。
3. **搜索框统一**（规范 §4.4）：换回 SoTextField、给按人搜的那个框补一句自己的提示语。
4. **既有约束没被踩坏**：capacityText / 车型取值表 / 解绑的二次确认。
   这几条是**别的判据的命根子**（计费口径），动一下就是钱的事。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

用法：python _tools/qa/_reverse_verify_vehicle_ui.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_vehicle_ui.py"

AND = "android/app/src/main/java/com/tapmoay/sorders"
VEHICLE = AND + "/ui/dispatcher/VehicleManageScreen.kt"
USERS = AND + "/ui/dispatcher/UsersManageScreen.kt"
MODULES = AND + "/ui/nav/Modules.kt"
COLOR = AND + "/ui/theme/Color.kt"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
DOC = "docs/changes/CHG-0016.md"
REGISTRY = "docs/changes/README.md"

BT = chr(96)  # 反引号（本文件里直接写反引号会把外面的模板串截断，一律用这个拼）

ROW_ANCHOR = "        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {" + chr(10)
EDIT_START = "            CardActionIcon(" + chr(10) + "                icon = Icons.Default.Edit"


def drop_line(s: str, needle: str) -> str:
    """整行删掉（表格行、单行声明）。"""
    return chr(10).join(ln for ln in s.split(chr(10)) if needle not in ln)


def cut_block(s: str, marker: str, tail: str = chr(10) + "            )" + chr(10)) -> tuple[str, str | None]:
    """从含 marker 的那一行起，切出到 tail 结束的一块；返回 (剩下的, 切下的)。"""
    i = s.find(marker)
    if i < 0:
        return s, None
    j = s.find(tail, i)
    if j < 0:
        return s, None
    end = j + len(tail)
    return s[:i] + s[end:], s[i:end]


def paste_after(s: str, anchor: str, block: str) -> str:
    k = s.find(anchor)
    if k < 0:
        return s
    k += len(anchor)
    return s[:k] + block + s[k:]


def move_edit_first(s: str) -> str:
    """把「编辑」那枚圈底动作挪到动作行最前面（位置判据必须抓到）。"""
    rest, block = cut_block(s, EDIT_START)
    if block is None:
        return s
    return paste_after(rest, ROW_ANCHOR, block)


CASES: list[tuple[str, str, object, str]] = [
    (
        "① 模块色常量退回手写色值（一个色又有了两处定义）",
        VEHICLE,
        lambda s: s.replace(
            "internal val VehicleAccent = Color(DriverLime)",
            "internal val VehicleAccent = Color(0xFF9AA35F)",
            1,
        ),
        "还手写着",
    ),
    (
        "② Color.kt 里的 DriverLime 定义被删（token 凭空消失）",
        COLOR,
        lambda s: drop_line(s, "val DriverLime = 0xFF9AA35FL"),
        "Color.kt 里定义了 val DriverLime",
    ),
    (
        "③ Color.kt 里的 OnDriverLime（黄绿底上那个字色）被删",
        COLOR,
        lambda s: drop_line(s, "val OnDriverLime = 0xFF3A3F00L"),
        "OnDriverLime",
    ),
    (
        "④ 规范 §2 模块色表那一格退回「-」（表与代码又对不上了）",
        DESIGN,
        lambda s: s.replace("| 司机管理 | 黄绿 #CDDC39 | DriverLime |", "| 司机管理 | 黄绿 #CDDC39 | - |", 1),
        "那一格写的是 DriverLime",
    ),
    (
        "⑤ 模块网格里的司机格子退回手写色（跨到第三个文件也得被抓）",
        MODULES,
        lambda s: s.replace("Icons.Default.Groups, color = DriverLime)", "Icons.Default.Groups, color = 0xFF9AA35FL)", 1),
        "还手写着",
    ),
    (
        "⑥ 卡片上一枚圈底动作换回裸 IconButton（用户点名「这个不行」的那种）",
        VEHICLE,
        lambda s: s.replace(EDIT_START, "            IconButton(" + chr(10) + "                icon = Icons.Default.Edit", 1),
        "裸 IconButton",
    ),
    (
        "⑦ 解绑那枚动作的 label 被拿掉（只剩一个图标，逼人靠猜）",
        VEHICLE,
        lambda s: drop_line(s, "label = " + chr(34) + "解绑" + chr(34) + ","),
        "解绑：LinkOff",
    ),
    (
        "⑧ 「编辑」被挪到动作行最前面（右＝惯用手那侧这条位置规律被破坏）",
        VEHICLE,
        move_edit_first,
        "位置：编辑在最右",
    ),
    (
        "⑨ 撑开左右两端的 Spacer 被删（编辑不再贴右边，位置判据要红）",
        VEHICLE,
        lambda s: drop_line(s, "Spacer(Modifier.weight(1f))"),
        "位置：编辑在最右",
    ),
    (
        "⑩ 解绑那枚动作的图标被换成停用那个（警示不再独立可辨）",
        VEHICLE,
        lambda s: s.replace("icon = Icons.Default.LinkOff", "icon = Icons.Default.Pause", 1),
        "警示放最左",
    ),
    (
        "⑪ 解绑的二次确认弹层被删（危险动作一点就走）",
        VEHICLE,
        lambda s: drop_line(s, "DangerConfirmDialog("),
        "解绑仍有二次确认",
    ),
    (
        "⑫ 列表搜索框换回 SoTextField（没有 ✕ 一键清空，两页两样）",
        VEHICLE,
        lambda s: s.replace(
            "                            SearchField(" + chr(10) + "                                value = vm.query",
            "                            SoTextField(" + chr(10) + "                                value = vm.query",
            1,
        ),
        "SoTextField",
    ),
    (
        "⑬ 按人搜那个框又写上了自己的一句提示语（规范 §4.4 要治的病）",
        VEHICLE,
        lambda s: s.replace(
            "                        value = vm.driverQuery," + chr(10) + "                        onValueChange = { vm.driverQuery = it },",
            "                        value = vm.driverQuery," + chr(10) + "                        placeholder = " + chr(34) + "搜司机" + chr(34) + "," + chr(10) + "                        onValueChange = { vm.driverQuery = it },",
            1,
        ),
        "按人搜那个不写自己的提示语",
    ),
    (
        "⑭ 提醒色又借回账本的金橙（同一个色两个含义）",
        VEHICLE,
        lambda s: s.replace("                color = Color(WarningAmber),", "                color = Color(MoneyOrange),", 1),
        "MoneyOrange",
    ),
    (
        "⑮ 司机管理页退回手写黄绿（同一个色在第二页各写一遍）",
        USERS,
        lambda s: s.replace("Color(DriverLime)", "Color(0xFF9AA35F)"),
        "司机管理页不再手写黄绿",
    ),
    (
        "⑯ 卡片不再用 capacityText（自己拼载重 / 容积文字）",
        VEHICLE,
        lambda s: drop_line(s, "val capacity = capacityText(v.attrs)"),
        "capacityText",
    ),
    (
        "⑰ 车型取值表被改（那是计费口径：挂车按件、其余按月）",
        VEHICLE,
        lambda s: s.replace(chr(34) + "large" + chr(34) + " to " + chr(34) + "大货车" + chr(34), chr(34) + "large" + chr(34) + " to " + chr(34) + "中货车" + chr(34), 1),
        "车型取值表",
    ),
    (
        "⑱ 登记簿里 CHG-0016 那一行被撤",
        REGISTRY,
        lambda s: drop_line(s, "| " + BT + "CHG-0016" + BT + " |"),
        "没登记",
    ),
    (
        "⑲ 文档少一节（九节是 _check_dev_spec 与本判据共同的底线）",
        DOC,
        lambda s: s.replace("## ⑨", "", 1),
        "文档缺节",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
            continue
        try:
            out_txt = mutated.replace("\r\n", "\n")
            if crlf:
                out_txt = out_txt.replace("\n", "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print("  [OK] " + label + " → 报红")
        else:
            fails.append(label + f"：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print("  [MISS] " + label + " → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
