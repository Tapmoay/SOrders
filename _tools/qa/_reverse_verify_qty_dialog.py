# -*- coding: utf-8 -*-
"""反向验证「数量小窗形态」这条红线**真的会红**（2026-09-23 用户点名的那一版）。

## 为什么这条要反向验证
它的判据大多是"某段代码里必须出现某个零件/某一句话"，这类判据有三种典型失效方式，
每一种都必须被单独证明会红：

1. **判据变成空转**：`QtyStepper` 被改名/搬走之后，如果判据只写"别处不许再定义一份"，
   它会安静地全绿 —— 本脚本把定义改名，必须报红（**0 处也红**）。
2. **只扫整个文件、不扫函数体**：`OrderCreateScreen.kt` 里别处本来就有一个合法的
   `Icons.Default.Add`（"再加一件商品"那个按钮）。判据要是扫整个文件，它会把好人打成假红；
   反过来，判据要是只锚函数名不锚函数体，把步进器删掉换成手写的一份也照样绿。
   本脚本往 `LineEditDialog` **函数体里**塞回一份手写步进器，必须报红。
3. **被"移个位置"骗过去**：单位标签从标题槽挪进正文 —— 文件里那个 `UnitTag(` 还在，
   整个文件扫的话照样绿，而用户看到的位置已经不对了。本脚本专门做这一次搬家。

另外三条打"用户点名的那两条"本身：数字又贴左（删 `TextAlign.Center`）、
单位标签变成能改的输入框（`UnitTag` 体内塞一个 `OutlinedTextField`）、
数量判据又内联回弹窗里（`typedQty` 不再被调用）。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_qty_dialog.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_qty_dialog_style.py"
CHECK_REL = "_tools/qa/_check_qty_dialog_style.py"

STEPPER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/QtyStepper.kt"
PICKER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPicker.kt"
ORDER = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/common/QtyStepperTest.kt"

#: 两个弹窗里那一行（**逐字节相同**，所以锚点只能靠"文件"来区分）
STEPPER_CALL = (
    "                    QtyStepper(qty = qty, onQtyChange = { qty = it }, "
    "modifier = Modifier.weight(1f))"
)

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 下单页行编辑弹窗**又自己写一份**步进器（两个弹窗从此又会不一样）",
        ORDER,
        lambda s: s.replace(
            STEPPER_CALL,
            "                    FilledTonalIconButton(onClick = { qty = (qty - 1).coerceAtLeast(1) }) {\n"
            '                        Icon(Icons.Default.Remove, contentDescription = "减")\n'
            "                    }\n"
            "                    OutlinedTextField(\n"
            "                        value = qty.toString(),\n"
            "                        onValueChange = { v -> qty = v.filter { it.isDigit() }.toIntOrNull() ?: 1 },\n"
            "                        singleLine = true,\n"
            "                        modifier = Modifier.width(96.dp),\n"
            "                    )\n"
            "                    FilledTonalIconButton(onClick = { qty = (qty + 1).coerceAtMost(9999) }) {\n"
            '                        Icon(Icons.Default.Add, contentDescription = "加")\n'
            "                    }",
            1,
        ),
        "第二份加减号/数量框",
    ),
    (
        "② 数量数字又贴左（删掉 `TextAlign.Center`）—— 用户点名的第 ① 条",
        STEPPER,
        lambda s: s.replace("                textAlign = TextAlign.Center,\n", "", 1),
        "居中",
    ),
    (
        "③ 单位标签从**标题槽**挪进正文（文件里那个 `UnitTag(` 还在，位置已经不对了）",
        PICKER,
        lambda s: s.replace(
            "                UnitTag(unit, modifier = Modifier.padding(start = 10.dp))\n",
            "",
            1,
        ).replace(
            '                    Text("数量", style = MaterialTheme.typography.bodyLarge)',
            '                    Text("数量", style = MaterialTheme.typography.bodyLarge)\n'
            "                    UnitTag(unit)",
            1,
        ),
        "标题槽",
    ),
    (
        "④ 单位标签变成**能改的输入框**（下单的人又能改单位了）",
        STEPPER,
        lambda s: s.replace(
            "        Text(\n            text = text,",
            "        OutlinedTextField(value = text, onValueChange = {},",
            1,
        ),
        "只读",
    ),
    (
        "⑤ 数量判据内联回弹窗里（`typedQty` 不再被调用，上限又抄一份 `9999`）",
        STEPPER,
        lambda s: s.replace(
            "            onValueChange = { onQtyChange(typedQty(it)) },",
            "            onValueChange = { onQtyChange(InputRules.intInput(it, 4).toIntOrNull()"
            "?.coerceIn(1, 9999) ?: 1) },",
            1,
        ),
        "typedQty",
    ),
    (
        "⑥ 步进器的定义被改名（判据必须报红，而不是安静地空转）",
        STEPPER,
        lambda s: s.replace("fun QtyStepper(", "fun QtyStepperZZZ(", 1),
        "只有一处定义",
    ),
    (
        "⑦ 数量判据的单测被改坏（`typedQty` 一个用例都不调了）",
        TEST,
        lambda s: s.replace("typedQty(", "typedQtyZZZ("),
        "单测",
    ),
    (
        "⑧ 判据清单指向不存在的文件（红线变成空转）",
        CHECK_REL,
        lambda s: s.replace(
            'STEPPER = AND / "ui/common/QtyStepper.kt"',
            'STEPPER = AND / "ui/common/QtyStepperGone.kt"',
            1,
        ),
        "存在",
    ),
    (
        "⑨ 反向验证脚本自己不见了（新红线没配反向验证）",
        CHECK_REL,
        lambda s: s.replace(
            'REVERSE = "_tools/qa/_reverse_verify_qty_dialog.py"',
            'REVERSE = "_tools/qa/_reverse_verify_qty_dialog_gone.py"',
            1,
        ),
        "反向验证",
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
        # 按行尾归一后再替换（Windows 上 Kotlin 文件可能是 CRLF），写回时按原样还原
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
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
            print(f"  [OK] {label} → 报红")
        else:
            fails.append(f"{label}：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print(f"  [MISS] {label} → 仍然全绿")

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
