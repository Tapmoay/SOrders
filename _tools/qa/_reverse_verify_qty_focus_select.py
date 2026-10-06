# -*- coding: utf-8 -*-
"""反向验证「数量框点进去就是整串选中」这条红线**真的会红**（2026-10-06，台账 L-25 / CHG-0059）。

## 为什么这条要反向验证
它的判据大多是「某段代码里必须出现某个零件/某一种形状」，这类判据有三种典型失效方式，
每一种都必须被单独证明会红：

1. **判据变成空转**：共用件被改名/搬走、或者判据清单指向一个不存在的文件之后，
   它会安静地全绿 —— 本脚本把 Stepper 常量指向不存在的文件，必须报红。
2. **只认名字不认形状**：名字还在、位置或语义已经不对。比如 selectedAll 里把
   TextRange(0, len) 改成只把光标挪到末尾（名字还叫「全选」、其实一个字都没选中），
   或者包装件的开关默认值从 false 偷偷变成 true（全 App 几十个普通字段跟着变）。
   这两种文件里那个标识符一个都没少，整文件扫的话照样绿。
3. **少一处挂载**：步进器上那一挂被摘掉（用户点进去光标又落末尾 ⇒ 1 + 15 = 115 回来），
   或者反过来**多**出一处挂载（某个普通字段被顺手打开，范围扩大）。两个方向都要能报红。

另外几条打「这件事的边界」本身：框又退回 value = qty.toString()（光标只能落末尾）、
数量判据内联回步进器（typedQty 不再被调用、上限又抄一份 9999）、
账本那一处又被改回默认值、旧病那条单测被删、设计规范那一段被删。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

R4-BOUNDARY-JUSTIFICATION: 本脚本只读写工作区里的 7 个文件（注入后按字节还原），
不编译、不跑 UI、不连后端 —— 它证明的是「这条红线自己不会说谎」，不是功能本身。

用法：python _tools/qa/_reverse_verify_qty_focus_select.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_qty_focus_select.py"
CHECK_REL = "_tools/qa/_check_qty_focus_select.py"

FIELD = "android/app/src/main/java/com/tapmoay/sorders/ui/common/FieldSelection.kt"
STEPPER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/QtyStepper.kt"
COMPONENTS = "android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt"
LEDGER = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/LedgerCreateScreen.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/common/FieldSelectionTest.kt"
DOC = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 步进器上那一挂被摘掉（用户点进去光标又落末尾 ⇒ 1 + 15 = 115 回来）",
        STEPPER,
        lambda s: s.replace(
            "                .selectAllOnFocus { field = selectedAll(field) },\n",
            "",
            1,
        ),
        "挂上去",
    ),
    (
        "② 名字还叫「全选」、其实只把光标挪到末尾（一个字都没选中）",
        FIELD,
        lambda s: s.replace(
            "v.copy(selection = TextRange(0, v.text.length))",
            "v.copy(selection = TextRange(v.text.length))",
            1,
        ),
        "选中区",
    ),
    (
        "③ 开关成了摆设（关掉 enabled 也照样全选 ⇒ 全 App 字段跟着变）",
        FIELD,
        lambda s: s.replace(
            "    if (!enabled) this\n    else onFocusChanged { state -> if (state.isFocused) onSelectAll() }",
            "    onFocusChanged { state -> if (state.isFocused) onSelectAll() }",
            1,
        ),
        "原样返回",
    ),
    (
        "④ 包装件的开关默认值偷偷改成 true（范围扩大到几十个普通字段）",
        COMPONENTS,
        lambda s: s.replace(
            "    selectAllOnFocus: Boolean = false,",
            "    selectAllOnFocus: Boolean = true,",
            1,
        ),
        "默认",
    ),
    (
        "⑤ 框又退回 value = qty.toString()（光标只能落末尾，病立刻回来）",
        STEPPER,
        lambda s: s.replace(
            "            value = field,",
            "            value = qty.toString(),",
            1,
        ),
        "TextFieldValue 受控",
    ),
    (
        "⑥ 数量判据内联回步进器（typedQty 不再被调用，上限又抄一份 9999）",
        STEPPER,
        lambda s: s.replace(
            "                val n = typedQty(v.text)",
            "                val n = InputRules.intInput(v.text, 4).toIntOrNull()?.coerceIn(1, 9999) ?: 1",
            1,
        ),
        "typedQty",
    ),
    (
        "⑦ 顺手把别的字段也打开（范围扩大 —— 用户只说数量那几个框）",
        LEDGER,
        lambda s: s.replace(
            "                        onValueChange = { vm.price = InputRules.priceInput(it) },",
            "                        onValueChange = { vm.price = InputRules.priceInput(it) },\n"
            "                        selectAllOnFocus = true,",
            1,
        ),
        "账本",
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
            'REVERSE = "_tools/qa/_reverse_verify_qty_focus_select.py"',
            'REVERSE = "_tools/qa/_reverse_verify_qty_focus_select_gone.py"',
            1,
        ),
        "反向验证",
    ),
    (
        "⑩ 旧病那一条单测被删（谁把全选拿掉都没人说话）",
        TEST,
        lambda s: s.replace('"115"', '"105"'),
        "FieldSelectionTest",
    ),
    (
        "⑪ 设计规范那一段被删（下一个人还会各写一份）",
        DOC,
        lambda s: s.replace("聚焦即全选", "聚焦即选中"),
        "设计规范",
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
