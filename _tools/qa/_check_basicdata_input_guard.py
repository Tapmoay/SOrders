# -*- coding: utf-8 -*-
"""红线：凡是把用户输入改成别的值再保存的路径，必须让用户看见（BUG-0028 / TA-08 · TA-09 · TA-10）。

### 为什么这条检查存在（2026-10-10 测试台账方向 A 的实测）
测试 agent 在隔离栈（8010 + 5556）里按下三颗**不会报错**的雷：

- **TA-08**：同一件商品的单价在两个地方是两个数 —— 商品卡走 `formatMoney`（到分四舍五入）把
  `0.005` 印成 `¥0.01/箱`（**真值的两倍**），改价弹窗预填 `trimMoneyZeros` 显示 `0.005`。
  库里是 `Numeric(14,4)`，两个都不是"照着库显示"。
- **TA-09**：改价弹窗里打进 `-3`，框子**当场变成 `3`**、确定键照样亮着、库里存 3 —— 全程没有一句话。
- **TA-10**：联系人电话填 `abc`，框子当场变空、保存成功、库里 `phone = NULL` ——
  用户以为"我填过电话了"；而且这条联系人之后在界面上是**一行空白**，看不出它没有电话。

三类毛病的共同点：**不报错、不崩、只有用户自己发现**。所以它们只能靠判据守，不能靠"跑一遍看看"。

### 这条检查在防什么
1. **别把说明又删掉**：`InputRules` 里那两句 note 文案是"用户看得见"的唯一来源；
   界面上的红字、确定键的禁用、保存前的拒绝，全都从它长出来。
2. **别再退回静默**：`price = InputRules.priceInput(it)` 这一行本身就是病 ——
   它把"过滤"和"告诉用户"合成了一件事，过滤完就没人知道被改过。
3. **口径跟列精度走**：`Numeric(12,2)` 的钱用 `formatMoney`，`Numeric(14,4)` 的单价用 `trimMoneyZeros`；
   卡片 / 弹窗 / 库三处必须是同一个数（或明确标注是四舍五入值 —— 本单选的是前者）。
4. **"没有电话"要看得见**：空电话是合法状态（CHG-0010 明确不要求必填），但合法 ≠ 可以不显示。

### 行为的证据在哪
本脚本是**静态锚点**（改坏了会红，但它不执行安卓代码）。真正的行为证据是两条单测，
在本单的容器里跑过（日志见 `docs/changes/BUG-0028.md` §⑧）：
- `android/app/src/test/java/com/tapmoay/sorders/core/InputRulesRewriteTest.kt`
- `android/app/src/test/java/com/tapmoay/sorders/ui/common/ProductCardKitTest.kt`（子分价那一条）
本脚本顺带钉住这两条断言**还在**（锚点被删掉 = 行为的证据没了）。

R4-BOUNDARY-JUSTIFICATION: 这一单加的是**一个新的扩展点**（InputRules 里那两句 note 文案 ＋ 三个调用点的
「改了就说」），核心区只碰展示层：不新增端点、不动库结构、Numeric(12,2) / Numeric(14,4) 的列精度
一个字节都没改。边界解决不了 —— 三类毛病的共同点是**不报错、不崩、只有用户自己发现**：
priceInput(it) 那一行把「过滤」和「告诉用户」合成了一件事，过滤完就没人知道值被改过，
而这在类型上完全合法；电话填 abc 存成 NULL 也是合法状态（CHG-0010 不要求必填），合法 ≠ 可以静默。
所以必须有一条机器判据钉住「note 文案还在、别再退回静默过滤、卡片/弹窗/库三处同一个数」，
外加两条行为单测（InputRulesRewriteTest / ProductCardKitTest）作为「用户真看得见」的证据。

用法：
    python _tools/qa/_check_basicdata_input_guard.py
    python _tools/qa/_check_basicdata_input_guard.py --list   # 只列锚点清单
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402

ROOT = repo_root()
AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
TESTD = ROOT / "android" / "app" / "src" / "test" / "java" / "com" / "tapmoay" / "sorders"

KIT = AND / "ui/common/ProductCardKit.kt"
LIST = AND / "ui/dispatcher/ProductsScreen.kt"
RULES = AND / "core/InputRules.kt"
MONEY = AND / "util/Money.kt"
VM = AND / "ui/shipper/AddressViewModel.kt"
SCR = AND / "ui/shipper/AddressScreen.kt"
KIT_TEST = TESTD / "ui/common/ProductCardKitTest.kt"
RULES_TEST = TESTD / "core/InputRulesRewriteTest.kt"

FILES = (KIT, LIST, RULES, MONEY, VM, SCR, KIT_TEST, RULES_TEST)

#: 断言的**下限**：`need()` 调用的次数低于它 = 这份判据被人删空了（不是"项目变干净了"）。
MIN_ANCHORS = 24


def read(p: Path) -> str:
    if not p.is_file():
        # 缺文件由 main() 开头那条 need() 报红 —— 这里不许抛异常：拿崩溃当红 = 判据其实没说话。
        return ""
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def code(text: str) -> str:
    """抠掉注释（等长空格）—— 注释里提到某函数**不算接线**（_check_input_rules.py 栽过这一次）。"""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in text[i:j]))
            i = j
        elif c == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


errs: list[str] = []
anchors: list[str] = []


def need(cond: object, what: str) -> None:
    anchors.append(what)
    if not cond:
        errs.append("[FAIL] " + what)


def main() -> int:
    missing = [str(p.relative_to(ROOT)).replace("\\", "/") for p in FILES if not p.exists()]
    need(not missing, "八个文件都在（缺：" + ", ".join(missing) + "）" if missing else "八个文件都在")

    kit_raw, list_raw, rules_raw = read(KIT), read(LIST), read(RULES)
    money_raw, vm_raw, scr_raw = read(MONEY), read(VM), read(SCR)
    kit_test, rules_test = read(KIT_TEST), read(RULES_TEST)
    kit, lst, rules, money, vm, scr = (code(x) for x in
                                       (kit_raw, list_raw, rules_raw, money_raw, vm_raw, scr_raw))

    # ---------------------------------------------------------------- TA-08 一个数一个口径
    need("trimMoneyZeros(price)" in kit,
         "TA-08 商品卡的售价走 trimMoneyZeros(price)（单价列 Numeric(14,4)，保到四位）")
    need("formatMoney(price)" not in kit,
         "TA-08 商品卡的售价**不再**走 formatMoney(price)（它到分四舍五入：0.005 → 0.01，真值两倍）")
    need("Numeric(14,4)" in kit_raw and "别把这一行换回" in kit_raw,
         "TA-08 卡片那行写着为什么不能用 formatMoney（Numeric(14,4) + 「别换回」）")
    need("trimMoneyZeros(p.defaultUnitPrice)" in lst,
         "TA-08 改价弹窗的预填仍走 trimMoneyZeros(p.defaultUnitPrice)（与卡片同一个口径）")
    need("0.005" in money_raw and "Numeric(14,4)" in money_raw,
         "TA-08 Money.kt 的 ⛔ 已收窄成「金额用 formatMoney、单价用 trimMoneyZeros」（写明 0.005 会翻倍）")
    need('assertEquals("¥0.005/箱", productPriceFact("0.005", "箱").value)' in kit_test,
         "TA-08 行为锚点：单测里钉着「0.005 的卡片值是 ¥0.005/箱」")

    # ---------------------------------------------------------------- TA-09 被改写了要看见
    need("data class InputRewrite(val value: String, val note: String?)" in rules,
         "TA-09 InputRules 里有 InputRewrite（过滤结果 + 一句给用户看的说明）")
    need("fun priceRewrite(raw: String): InputRewrite" in rules,
         "TA-09 InputRules.priceRewrite 存在（规则层唯一实现）")
    need("fun priceRewriteNote(raw: String): String? = priceRewrite(raw).note" in rules,
         "TA-09 InputRules.priceRewriteNote 存在（界面用的那一句）")
    need("负数" in rules and "只能填数字" in rules and "一个小数点" in rules,
         "TA-09 note 文案点出了三件事：负数 / 非数字字符 / 多余的点儿")
    need("onValueChange = { price = InputRules.priceInput(it) }" not in lst,
         "TA-09 改价框**不再**是那个静默一行（price = InputRules.priceInput(it)）")
    need("val next = InputRules.priceInput(raw)" in lst and "val note = InputRules.priceRewriteNote(raw)" in lst,
         "TA-09 改价框同时算「过滤后的值」与「说明」")
    need("price = if (note == null) next else raw" in lst,
         "TA-09 有说明时**保留用户打的字**（不许当场换成另一个数给他看）")
    need("priceNote = note" in lst, "TA-09 说明存进 priceNote 状态，界面据此显示红字")
    need("isError = priceNote != null" in lst, "TA-09 输入框标红（isError）")
    need("if (priceNote != null)" in lst, "TA-09 框下画红字（说明画在输入框下面）")
    need("enabled = !busy && priceNote == null && price.toDoubleOrNull() != null" in lst,
         "TA-09 确定键被禁用：有说明就**拒绝**保存（口径是拒绝，不是转正）")
    need("priceRewriteNote" in rules_test and "-3" in rules_test,
         "TA-09 行为锚点：单测里钉着「-3 → 3 但必须有说明」")

    # ---------------------------------------------------------------- TA-10 丢字要说 + 空电话看得见
    need("fun contactPhoneRewrite(raw: String): InputRewrite" in rules,
         "TA-10 InputRules.contactPhoneRewrite 存在")
    need("fun phoneInputNote(raw: String): String? = contactPhoneRewrite(raw).note" in rules,
         "TA-10 InputRules.phoneInputNote 存在")
    need("要留空就直接别填" in rules,
         "TA-10 电话的说明写清了「留空 = 没有电话」（空是合法状态，不是错误）")
    need("onValueChange = { vm.contactPhone = InputRules.phoneInput(it) }" not in scr,
         "TA-10 联系人电话栏**不再**是那个静默一行")
    need("vm.contactPhoneNote = InputRules.phoneInputNote(it)" in scr,
         "TA-10 电话栏把丢字算成 note（丢的字符必须说出来）")
    need("var contactPhoneNote by mutableStateOf<String?>(null)" in vm,
         "TA-10 ViewModel 有 contactPhoneNote 状态")
    need(re.search(r"contactPhoneNote\?\.let \{\s*formError = it\s*return\s*\}", vm) is not None,
         "TA-10 saveContact 里的丢字是 formError + **return**（不只提示：return 才拦得住保存）")
    i_note = vm.find("contactPhoneNote?.let {")
    i_fmt = vm.find("InputRules.phoneError(contactPhone.trim()")
    need(i_note >= 0 and i_fmt > i_note,
         "TA-10 saveContact 里「丢字」的拒绝排在格式校验**之前**（先说你丢了什么，再说格式）")
    need("FormErrorLine(vm.contactPhoneNote ?: vm.formError)" in scr,
         "TA-10 抽屉里的红字优先显示丢字说明（再轮到格式错）")
    need('ifBlank { "无电话" }' in scr,
         "TA-10 联系人卡：空电话画成「无电话」，不是一行空白")
    need("选填；留空 = 无电话" in scr,
         "TA-10 电话框的 placeholder 说清了「留空 = 无电话」")
    need("phoneInputNote" in rules_test and '"abc"' in rules_test,
         "TA-10 行为锚点：单测里钉着「abc → 空串但必须有说明」")

    # ---------------------------------------------------------------- 判据自己不许被删空
    if len(anchors) < MIN_ANCHORS:
        errs.append(
            f"[FAIL] 本判据只剩 {len(anchors)} 项锚点（下限 {MIN_ANCHORS}）——"
            f"是被人删空了，不是项目变干净了。修这个脚本，别删 MIN_ANCHORS。"
        )

    if "--list" in sys.argv:
        print(f"锚点清单（{len(anchors)} 项）：")
        for i, a in enumerate(anchors, 1):
            print(f"  {i:2d}. {a}")
        return 0

    if errs:
        print("\n❌ 基础数据输入守卫没通过：\n")
        for e in errs:
            print("  " + e + "\n")
        return 1

    print(
        f"✅ {len(anchors)} 项锚点全绿：改价框拒绝负数并说明（TA-09）、联系人电话丢字要说明且空电话可见（TA-10）、"
        f"商品卡与改价弹窗同一个单价口径（TA-08）"
    )
    return 0


if __name__ == "__main__":
    if refuse_if_injecting("基础数据输入守卫（BUG-0028）"):
        sys.exit(2)
    sys.exit(main())
