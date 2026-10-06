# -*- coding: utf-8 -*-
r"""弹窗语言那条红线，一条条被真的破坏一次 —— 台账 L-20 / CHG-0064。

一条红线要能被「真的破坏一次」证明它在检查：下面每一条注入都只改一处，然后要求
_tools/qa/_check_dialog_language.py 报红，而且报的是**这一条**（关键词比对）。
跑完按字节还原，再逐字节核对 —— 一个字节都不许留在工作区。

这一组破坏方式的来路都是真实会发生的改法：某处又自己画一层底（回潮）、零件那三行被抽掉
一行、档位被抹平（DANGER 用主色 / WARN 用 Info / 多长一档 SUCCESS）、DangerConfirmDialog
不再显式带档、危险弹窗忘了给 DANGER、设计基线文档没跟上。

⛔ 锚点一律用文件里的真实长相（含前导空格）。⛔ CHG-0064 的迁移是在每个调用点
`CardAlertDialog(` 之后**插一行 tone**，所以任何「调用点后面紧跟 onDismissRequest」形状的旧
锚点都会腐烂 —— 本件一律把 tone 那行写进锚点。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_dialog_language.py"

COMP = "android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt"
DETAIL = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"
DISP = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherOrdersScreen.kt"
WITHDRAW = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperReturnRequestsScreen.kt"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

NL = chr(10)

CASES: list[tuple[str, str, object, str]] = [
    (
        "回潮：司机端订单详情那个「打电话确认」又自己画一层底（裸 AlertDialog）",
        DETAIL,
        lambda s: s.replace(
            "                        CardAlertDialog(" + NL + "                            onDismissRequest = { confirmCall",
            "                        AlertDialog(" + NL + "                            onDismissRequest = { confirmCall", 1),
        "只剩 CardAlertDialog 定义体内那一处",
    ),
    (
        "白卡被抽回 M3 那层灰：containerColor = surface → surfaceContainerHigh",
        COMP,
        lambda s: s.replace(
            "        containerColor = MaterialTheme.colorScheme.surface,",
            "        containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,", 1),
        "白卡",
    ),
    (
        "M3 那 6dp 抬升被加回来：tonalElevation 0.dp → 6.dp",
        COMP,
        lambda s: s.replace(
            "        containerColor = MaterialTheme.colorScheme.surface,\n        tonalElevation = 0.dp,",
            "        containerColor = MaterialTheme.colorScheme.surface,\n        tonalElevation = 6.dp,"),
        "tonalElevation",
    ),
    (
        "默认档被抽掉：tone 不再是 INFO（忘传就是提示蓝）",
        COMP,
        lambda s: s.replace("    tone: DialogTone = DialogTone.INFO," + NL, "", 1),
        "默认档",
    ),
    (
        "图标接线被抽掉：icon 不再兜底到 DialogToneIcon(tone)",
        COMP,
        lambda s: s.replace("        icon = icon ?: { DialogToneIcon(tone) }," + NL, "", 1),
        "图标接线",
    ),
    (
        "DANGER 档被抹成主色（「删了就回不来」不再发红）",
        COMP,
        lambda s: s.replace(
            "        DialogTone.DANGER -> MaterialTheme.colorScheme.error",
            "        DialogTone.DANGER -> MaterialTheme.colorScheme.primary", 1),
        "DANGER 档",
    ),
    (
        "WARN 档被抹成 Info（警告橙没了，形状也不再区分）",
        COMP,
        lambda s: s.replace(
            "        DialogTone.WARN -> Icons.Filled.WarningAmber",
            "        DialogTone.WARN -> Icons.Filled.Info", 1),
        "WARN 档",
    ),
    (
        "档位长到第四档：enum 里多了 SUCCESS",
        COMP,
        lambda s: s.replace("enum class DialogTone { INFO, WARN, DANGER }",
                            "enum class DialogTone { INFO, WARN, DANGER, SUCCESS }", 1),
        "只三档",
    ),
    (
        "DangerConfirmDialog 不再显式带 DANGER（老调用点跟着变回提示蓝）",
        COMP,
        lambda s: s.replace(
            "        tone = DialogTone.DANGER," + NL + "        title = { Text(title, style = MaterialTheme.typography.titleMedium) },",
            "        title = { Text(title, style = MaterialTheme.typography.titleMedium) },", 1),
        "显式带 DANGER 档",
    ),
    (
        "危险正文被降档：派单员「退货」那次确认被改成 WARN",
        DISP,
        lambda s: s.replace(
            "            CardAlertDialog(" + NL + "                tone = DialogTone.DANGER," + NL + "                onDismissRequest = { if (!vm.returnSubmitting) vm.showReturnDialog = false },",
            "            CardAlertDialog(" + NL + "                tone = DialogTone.WARN," + NL + "                onDismissRequest = { if (!vm.returnSubmitting) vm.showReturnDialog = false },", 1),
        "一条都没漏",
    ),
    (
        "用户点名那处「撤回这张退货申请？」被降成 INFO",
        WITHDRAW,
        lambda s: s.replace(
            "        CardAlertDialog(" + NL + "            tone = DialogTone.DANGER," + NL + "            onDismissRequest = { vm.cancelWithdraw() },",
            "        CardAlertDialog(" + NL + "            tone = DialogTone.INFO," + NL + "            onDismissRequest = { vm.cancelWithdraw() },", 1),
        "撤回这张退货申请？",
    ),
    (
        "设计基线文档没跟上：弹窗那一行又退回「选择/确认类用 AlertDialog」",
        DESIGN,
        lambda s: s.replace("CardAlertDialog", "AlertDialog", 1),
        "设计基线写了弹窗容器口径",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    fails: list[str] = []

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", NL)
        mutated = mutate(plain)
        if mutated == plain:
            print(f"  [SKIP] {label}：注入没生效（锚点变了，请更新本脚本）")
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            continue
        text = mutated.replace(NL, "\r\n") if crlf else mutated
        try:
            path.write_bytes(text.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        if code != 0 and (not expect or expect in out):
            print(f"  [OK]   {label} → 报红")
        else:
            print(f"  [MISS] {label}（退出码 {code}，期望关键词「{expect}」）")
            fails.append(f"{label}（退出码 {code}，期望关键词「{expect}」）")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    for rel in dirty:
        (ROOT / rel).write_bytes(originals[rel])
        print(f"  [!!]   {rel} 没还原干净，已强制写回")
        fails.append(f"{rel} 没还原干净")

    print("=" * 60)
    if fails:
        print(f"❌ 反向验证不通过：{len(fails)} 条")
        for f in fails:
            print(f"   - {f}")
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
