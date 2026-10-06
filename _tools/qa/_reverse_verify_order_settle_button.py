# -*- coding: utf-8 -*-
"""反向验证「已挂账的单，底部换成核销＋改挂账单位」这条红线**真的会红**（L-44 / CHG-0069）。

## 为什么这条要反向验证
它的判据几乎全是"某个文件里必须出现某个零件 / 某句话 / 某两行的顺序"，这类判据有五种典型失效方式，
每一种都必须被单独证明会红：

1. **分档看着改了、其实没接上**：`when` 里那三个分支的顺序换一下、或者把 `val charged` 换成 `false` ——
   界面上照样编译、照样跑，只是已挂账的单退回原来那两颗（用户报的那条 bug 原样回来）。
2. **口径悄悄漂**：金额从 `arrearsAmount` 换成 `amount`、或者顺手多传一个 `orderProductIds` ——
   退过货的单上两个数差一大截，后端逐单校验会 400，而卡片上"看起来更合理"（按商品收）。
3. **两道门被拆**：没有客户档案时不再分岔、直接弹核销（后端必 400「订单 X 无客户归属」）——
   用户看到的是一句红字，而不是"去建客户档案"的引导。
4. **共用件被抄回页面**：账本页又排一份收款方式、或者建档案弹层里又造一份描边表单行 ——
   两处文案开始各走各的（"挂账结清"只会出现在其中一处）。
5. **红线失配**：`_check_paid_actions.py` 与它的反验按**缩进逐字**钉着原文那两行 ——
   给它们多包一层块，两条既有判据会一起失配，而界面上一点看不出区别。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_order_settle_button.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_order_settle_button.py"

#: Windows 上 Kotlin 文件是 CRLF：按字节快照、归一后再替换、写回时按原样还原
CR = bytes((13,))
LF = bytes((10,))
CRLF = CR + LF

SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailViewModel.kt"
EDITOR = "android/app/src/main/java/com/tapmoay/sorders/ui/common/CustomerEditorDialog.kt"
LEDGER_PERSON = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/LedgerPersonScreen.kt"
PICKER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/SettleMethodPicker.kt"
AI_WRITE = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt"
AI_HANDLERS = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteOrderHandlers.kt"
CATALOG = "docs/PROJECT_MAP/09A_HINT_CATALOG.md"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 分档条件被换掉（已挂账的单退回原来那两颗 —— 用户报的那条原样回来）",
        SCREEN,
        lambda s: s.replace(
            "val charged = OrderStatusModel.isChargedToArrears(order.paymentMethod, order.paid, order.settledAmount)",
            "val charged = false",
            1,
        ),
        "分档条件逐字",
    ),
    (
        "② 已收清那一档被删掉（那一档掉进 else，重新长出两颗禁用按钮）",
        SCREEN,
        lambda s: s.replace("                        order.paid -> CollectedActionsRow()\n", "", 1),
        "三档都在",
    ),
    (
        "③ 已挂账那一档又画回「现场支付」（点下去＝欠款静默蒸发且不记流水）",
        SCREEN,
        lambda s: s.replace('Text("核销")', 'Text("现场支付")', 1),
        "不再画「现场支付」",
    ),
    (
        "④ 核销金额换成商品行合计（退过货的单会被后端逐单校验打回 400）",
        VM,
        lambda s: s.replace("amount = o.arrearsAmount,", "amount = o.amount,", 1),
        "金额取欠款",
    ),
    (
        "⑤ 整单核销里多传了 orderProductIds（口径②说好了整单，这里变成按商品）",
        VM,
        lambda s: s.replace(
            '                        settleMode = "itemized",',
            '                        settleMode = "itemized",\n                        orderProductIds = emptyList(),',
            1,
        ),
        "整单核销",
    ),
    (
        "⑥ 没有客户档案时不再分岔、直接弹核销（后端必 400「订单 X 无客户归属」）",
        VM,
        lambda s: s.replace(
            "if (cust != null) showSettleConfirm = true else showCustomerDialog = true",
            "showSettleConfirm = true",
            1,
        ),
        "的分岔",
    ),
    (
        "⑦ 建档案弹层被抄成描边输入框（表单行有唯一实现，_check_form_panel_style.py 盯着）",
        EDITOR,
        lambda s: s.replace("FormInputRow(", "OutlinedTextField(", 1),
        "不许出现描边输入框",
    ),
    (
        "⑧ 账本页又自己排了一份收款方式（两处文案开始各走各的）",
        LEDGER_PERSON,
        lambda s: s.replace(
            "SettleMethodPicker(selected = vm.settleMethod, onSelect = { vm.settleMethod = it })",
            'SettleMethodPicker(selected = vm.settleMethod, onSelect = { vm.settleMethod = it })\n    val dup = "arrears_settle"',
            1,
        ),
        "搬走之后一行都不许留",
    ),
    (
        "⑨ 账本页那个签名行被改成表达式体（原判据与反验的锚点失配）",
        LEDGER_PERSON,
        lambda s: s.replace(
            "private fun SettleMethodChips(vm: DispatcherLedgerViewModel) {",
            "private fun SettleMethodChips(vm: DispatcherLedgerViewModel): Unit = run {",
            1,
        ),
        "签名行逐字",
    ),
    (
        "⑩ 收款方式那张表被抄到第三处（各页自己排一遍的开始）",
        PICKER,
        lambda s: s.replace(
            '    "arrears_settle" to "挂账结清",',
            '    "arrears_settle" to "挂账结清",\n)\nval EXTRA_METHODS: List<Pair<String, String>> = listOf(\n    "arrears_settle" to "挂账结清",',
            1,
        ),
        "不许再长第三份",
    ),
    (
        "⑪ AI 侧「已挂账」判据被删（已挂账的单又弹一张注定失败的挂账卡）",
        AI_HANDLERS,
        lambda s: s.replace(
            "if (OrderStatusModel.isChargedToArrears(order.paymentMethod, order.paid, order.settledAmount)) {",
            "if (false) {",
            1,
        ),
        "新判据排在旧判据",
    ),
    (
        "⑫ AiOrderRef 的 paymentMethod 被删（AI 侧再也分不出已挂账）",
        AI_WRITE,
        lambda s: s.replace('    val paymentMethod: String = "cash",\n', "", 1),
        "末尾追加了 paymentMethod",
    ),
    (
        "⑬ 反验锚点①被改缩进（_check_paid_actions.py 与它的反验会一起失配）",
        SCREEN,
        lambda s: s.replace(
            "                                OrderStatusModel.canChargeToArrears(order.paid, order.settledAmount),",
            "                                    OrderStatusModel.canChargeToArrears(order.paid, order.settledAmount),",
            1,
        ),
        "反验锚点①",
    ),
    (
        "⑭ 新提示从提示清单里消失（提示总开关再也管不到它）",
        CATALOG,
        lambda s: s.replace("档案先记这两样", "档案先记这么两样", 1),
        "新提示进了提示清单",
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
        crlf = CRLF in original_bytes
        plain = original_bytes.decode("utf-8").replace(CRLF.decode(), LF.decode())
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated
            if crlf:
                out_txt = out_txt.replace(LF.decode(), CRLF.decode())
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
