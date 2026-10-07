# -*- coding: utf-8 -*-
"""数量类输入框「点进去就是整串选中」这条红线（2026-10-06，台账 L-25 / CHG-0059）。

## 用户原话（对着「添加商品」的数量框）
> 「添加商品的时候……那里就**不要填 1 了，就默认是 0**」「如果他自己已经填好了 1 的话……
>   我们又填 15 的话，那就变成了 **115**，这就**显示了错误**了」
> 「**假如它没有去改的话就是 1；如果它去改的话，就是 0**，它按它填的数额去计算。是这样子的，这是个 bug」

## 为什么这件事必须有机器的判据
根因不在数值上 —— 后端收 115 也照样建单（它是合法正整数），数据库里也只存那个数。
病长在**框里那一串字符**上：数量框里放着上一次那个数（1），点进去光标落在**末尾**，
用户想填 15、敲 1 5，框里成了 115。编译器、类型系统、后端校验**一个都拦不住** ——
而改法极容易被下一个人「顺手」改回去：
- 把 TextFieldValue 换回 String ⇒ 光标又只能落在末尾，病立刻回来；
- 把「聚焦即全选」在每个字段里各抄一份 ⇒ 三处数量框哪天又各不一样；
- 把包装件的开关默认值从 false 改成 true ⇒ 全 App 几十个普通字段跟着变（那是**扩大**改动面）。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。「点进去选中了哪几个字」是纯界面状态，
下沉不到任何一层：TextFieldValue 不参与类型约束，后端只看见最终那个整数，库里只存最终那个数 ——
「用户敲的 1 5 是替换还是追加」这一步**只存在于界面里**。它同时守三件跨文件的口径：
共用件**只有一份**、开关**默认关**、三处数量字段**都打开**；任意少一件，用户看到的病就回来一部分。

用法：
    python _tools/qa/_check_qty_focus_select.py
    python _tools/qa/_check_qty_focus_select.py --list
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402
from _check_product_card_single_source import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TESTDIR = ROOT / "android/app/src/test/java/com/tapmoay/sorders"

FIELD = AND / "ui/common/FieldSelection.kt"
STEPPER = AND / "ui/common/QtyStepper.kt"
COMPONENTS = AND / "ui/common/Components.kt"
FORMROWS = AND / "ui/common/FormRows.kt"
LEDGER = AND / "ui/dispatcher/LedgerCreateScreen.kt"
PURCHASE = AND / "ui/dispatcher/PurchaseOrderFormScreen.kt"
SHIPPER_PRICES = AND / "ui/shipper/ShipperPricesScreen.kt"
DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

TEST = TESTDIR / "ui/common/FieldSelectionTest.kt"
STEPPER_TEST = TESTDIR / "ui/common/QtyStepperTest.kt"

REVERSE = "_tools/qa/_reverse_verify_qty_focus_select.py"

#: 认识 selectAllOnFocus 这个标识符的界面文件（**只有这些** —— 抄到别处就是又开了一份）
#: ⚠️ 三个是共用件（实现与两个包装件），另外三个是**使用者**：账本数量、采购单行数量、
#:    下游定价的单价框（2026-10-07 CHG-0077 登记的第三个使用者 —— 价框与数量框同类，都是
#:    "点进去就是要重打一个数"：`888` 改 `999` 不整串选中就成了 `888999`）。
OWNERS = (
    "Components.kt",
    "FieldSelection.kt",
    "FormRows.kt",
    "LedgerCreateScreen.kt",
    "PurchaseOrderFormScreen.kt",
    "QtyStepper.kt",
    "ShipperPricesScreen.kt",
)

#: 挂上去的地方（步进器 / SoTextField / FormInputRow）—— 恰好 3 处
MOUNTS = ("Components.kt", "FormRows.kt", "QtyStepper.kt")

#: 扫到的界面文件数下限（防目录改名/搬走之后「一个文件都没扫到」也算过）
MIN_UI_FILES = 100

#: 抽出来的函数体字符数下限（**抽取失效比判据腐烂更危险** —— 那会变成一条永远绿的检查）
BODY_FLOOR = 120


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def subs(text: str, needle: str) -> int:
    """子串出现次数。

    ⚠️ 这里**故意用纯字符串**而不是正则：这些锚点里全是 ( ) . 这类正则元字符
    （如 .selectAllOnFocus( ），当正则用会直接报 unterminated subpattern —— 或者更糟：
    静默匹配到别的东西，判据就成了假的。
    """
    return text.count(needle)


def after(text: str, needle: str, span: int) -> str:
    """needle 之后 span 个字符。

    表达式体函数（fun selectedAll(v: TextFieldValue): TextFieldValue = ...）**没有花括号**，
    不能用 fn_body（它会一路找到下一个函数的 { 去配平，取回来的是别人的函数体）。
    """
    i = text.find(needle)
    return text[i : i + span] if i >= 0 else ""


def between(text: str, start: str, end: str) -> str:
    """start 与 end 之间那一段（取不到返回空串，交给判据报红）。"""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:j] if j > 0 else ""


def fn_body(src: str, sig: str) -> str:
    """sig（如 fun QtyStepper( ）那个函数的**函数体**（按大括号配对，不是按行猜）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


def files_with(needle: str) -> list[str]:
    """界面文件里**代码**含 needle 的那些（注释先剥掉 —— 文档里提一句名字不算又抄一份）。"""
    return sorted(p.name for p in AND.rglob("*.kt") if needle in code(p))


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("数量框聚焦全选检查"):
        return 1

    c = Checker()
    print("数量框「点进去就是整串选中」：2026-10-06")

    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    # ---- 1. 六个文件都在 ----
    for p, why in (
        (FIELD, "「聚焦即全选」的唯一实现处"),
        (STEPPER, "三个数量框共用的小窗"),
        (COMPONENTS, "SoTextField（账本数量用的是它）"),
        (FORMROWS, "FormInputRow（采购单行数量用的是它）"),
        (LEDGER, "账本「记一笔账」数量框"),
        (PURCHASE, "采购单行数量框"),
    ):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 存在（{why}）", p.exists(), "文件被搬走/改名了")

    # ---- 2. 共用件只有一个，而且真的做了那件事 ----
    field_src = code(FIELD)
    c.ok(
        "selectedAll 只定义一处（整串选中）",
        subs(field_src, "fun selectedAll(") == 1,
        f"找到 {subs(field_src, 'fun selectedAll(')} 处",
    )
    c.ok(
        "selectedAll 体内真的把选中区设成 0..length（不是只把光标挪走）",
        "TextRange(0, v.text.length)" in after(field_src, "fun selectedAll(", 200),
        "没找到 TextRange(0, v.text.length)",
    )
    c.ok(
        "fieldAtEnd 只定义一处（回填时把光标放末尾）",
        subs(field_src, "fun fieldAtEnd(") == 1,
        f"找到 {subs(field_src, 'fun fieldAtEnd(')} 处",
    )
    c.ok(
        "fieldAtEnd 体内的光标确实在末尾（text.length）",
        "TextRange(text.length)" in after(field_src, "fun fieldAtEnd(", 200),
        "没找到 TextRange(text.length)",
    )
    mod_body = after(field_src, "fun Modifier.selectAllOnFocus(", 400)
    c.ok(
        "selectAllOnFocus 只在聚焦那一刻动作（onFocusChanged）",
        "onFocusChanged" in mod_body and "state.isFocused" in mod_body,
        "没挂 onFocusChanged",
    )
    c.ok(
        "开关关着时**原样返回**（否则「默认关」是假的，全 App 字段跟着变）",
        "if (!enabled) this" in mod_body,
        "没找到 if (!enabled) this",
    )

    # ---- 3. 「只有一份」：认识它/挂上它的文件与次数都被钉死 ----
    owners = files_with("selectAllOnFocus")
    c.ok(
        f"认识 selectAllOnFocus 的界面文件恰好这 {len(OWNERS)} 个（多一个就是在别处又抄了一份）",
        tuple(owners) == OWNERS,
        "实际：" + "、".join(owners),
    )
    # 看的是「挂上去」那个形状（{ field = selectedAll(field) }），不是标识符本身 ——
    # 定义那一行（fun Modifier.selectAllOnFocus( ）也含 .selectAllOnFocus( ，会把它自己算进来。
    mounts = files_with("{ field = selectedAll(field) }")
    c.ok(
        "挂上去的地方恰好 3 处（步进器 / SoTextField / FormInputRow）",
        tuple(mounts) == MOUNTS,
        "实际：" + "、".join(mounts),
    )
    callers = {p.name: subs(code(p), "selectedAll(") for p in AND.rglob("*.kt") if "selectedAll(" in code(p)}
    c.ok(
        "selectedAll( 全树 4 处＝定义 1 ＋ 三个挂载点各 1（谁又抄一份会当场多出来）",
        callers
        == {"FieldSelection.kt": 1, "QtyStepper.kt": 1, "Components.kt": 1, "FormRows.kt": 1},
        str(callers),
    )
    c.ok(
        "没有任何一处把开关默认成 true（默认开＝全 App 几十个字段一起变）",
        not any("selectAllOnFocus: Boolean = true" in code(p) for p in AND.rglob("*.kt")),
        "有人把它默认打开当成了「统一体验」",
    )

    # ---- 4. 步进器：TextFieldValue 受控 ＋ 挂全选 ＋ 仍然走 typedQty ----
    st = code(STEPPER)
    body = fn_body(st, "fun QtyStepper(")
    c.ok(
        "步进器的数量框走 TextFieldValue 受控（value = field）",
        "value = field," in body,
        f"函数体 {len(body)} 字符；没找到 value = field,",
    )
    c.ok(
        "步进器挂上了「聚焦即全选」",
        "selectAllOnFocus { field = selectedAll(field) }" in body,
        "步进器没挂全选（用户点进去还是会 1 + 15 = 115）",
    )
    c.ok(
        "步进器仍然走共用的 typedQty(（判据只有一份）",
        "val n = typedQty(" in body and "onQtyChange(n)" in body,
        "步进器没走 typedQty / 递出去的不是它夹好的数",
    )
    region = between(body, "val n = typedQty(", "onQtyChange(n)")
    c.ok(
        "归一这一段里没有第二份上下限（9999 / coerceIn 不许出现）",
        region != "" and "9999" not in region and "coerceIn(" not in region,
        (region or "取不到这一段")[:80],
    )
    c.ok(
        "外面改了数量会回填（LaunchedEffect(qty) ＋ fieldAtEnd），光标放末尾",
        "LaunchedEffect(qty)" in body and "fieldAtEnd(want)" in body,
        "回填那一段不见了",
    )
    c.ok(
        "上下限与位数一个字没动（默认值不动，改的是「既有内容＋光标」）",
        "const val QTY_MIN: Int = 1" in st
        and "const val QTY_MAX: Int = 9999" in st
        and "const val QTY_DIGITS: Int = 4" in st,
        "QTY_MIN / QTY_MAX / QTY_DIGITS 被改过",
    )

    # ---- 5. 两个包装件：开关默认关，且只在签名区一处 ----
    for p, sig in ((COMPONENTS, "fun SoTextField("), (FORMROWS, "fun FormInputRow(")):
        src = code(p)
        params = between(src, sig, ") {")
        c.ok(
            f"{p.name} 的 selectAllOnFocus 默认 false（其余几十个普通字段行为一个字不变）",
            "selectAllOnFocus: Boolean = false," in params,
            "签名区里没找到 selectAllOnFocus: Boolean = false,",
        )
        c.ok(
            f"{p.name} 的这个开关只声明一处",
            subs(src, "selectAllOnFocus: Boolean =") == 1,
            f"声明了 {subs(src, 'selectAllOnFocus: Boolean =')} 处",
        )
        wbody = fn_body(src, sig)
        c.ok(
            f"{p.name} 体内按开关挂全选（关着就一个字不加）",
            "selectAllOnFocus(enabled = selectAllOnFocus) { field = selectedAll(field) }" in wbody,
            f"函数体 {len(wbody)} 字符；没按开关挂",
        )
        c.ok(
            f"{p.name} 的文本状态在本件内部用 TextFieldValue（对外仍是 String）",
            "var field by remember { mutableStateOf(fieldAtEnd(value)) }" in wbody
            and "value = field," in wbody,
            "文本状态没换成 TextFieldValue（光标又只能落末尾）",
        )

    # ---- 6. 打开开关的字段：两处数量 ＋ 一处理价（都恰好一处）----
    led = code(LEDGER)
    c.ok(
        "账本「记一笔账」数量框打开了开关（就在 vm.qty 那个框上）",
        subs(led, "selectAllOnFocus = true") == 1
        and "selectAllOnFocus = true" in after(led, "value = vm.qty,", 400),
        f"账本里开了 {subs(led, 'selectAllOnFocus = true')} 处",
    )
    pur = code(PURCHASE)
    c.ok(
        "采购单行数量打开了开关（就在那一行的 onQty 上）",
        subs(pur, "selectAllOnFocus = true") == 1
        and "selectAllOnFocus = true"
        in after(pur, "onValueChange = { onQty(InputRules.intInput(it, 7)) },", 300),
        f"采购单里开了 {subs(pur, 'selectAllOnFocus = true')} 处",
    )
    sp = code(SHIPPER_PRICES)
    c.ok(
        "下游定价的单价框打开了开关（就在 vm.draftFor 那个框上）",
        subs(sp, "selectAllOnFocus = true") == 1
        and "selectAllOnFocus = true"
        in after(sp, "onValueChange = { vm.setDraft(draftKey, InputRules.priceInput(it)) },", 400),
        f"下游定价里开了 {subs(sp, 'selectAllOnFocus = true')} 处",
    )

    # ---- 7. 默认值没被动过（用户：「没去改的话就是 1」）----
    c.ok(
        "账本数量框的默认值仍是 1",
        subs(led, 'var qty by mutableStateOf("1")') == 1,
        "默认值被改了（那不是这次要改的东西）",
    )
    c.ok(
        "采购单行数量的默认值仍是 1",
        'quantity = if (it.qty > 0) it.qty.toString() else "1"' in pur,
        "默认值被改了",
    )
    st_test = read(STEPPER_TEST)
    c.ok(
        "QtyStepper 那几条纯函数单测原样都在（数值判据本来就没坏）",
        st_test.count("@Test") >= 5
        and st_test.count("typedQty(") >= 5
        and "QTY_MIN" in st_test
        and "QTY_MAX" in st_test,
        f"@Test {st_test.count('@Test')} 条、typedQty( {st_test.count('typedQty(')} 处",
    )

    # ---- 8. 退货页那一行**故意**不动（它体内没有输入框，口径别被顺手统一）----
    ret = fn_body(code(COMPONENTS), "fun OrderReturnLines(")
    c.ok(
        "退货页那一行仍是「加减号 ＋ 只读数字」，体内没有输入框",
        len(ret) >= BODY_FLOOR
        and "BasicTextField(" not in ret
        and "OutlinedTextField(" not in ret
        and "SoTextField(" not in ret
        and "Icons.Default.Add" in ret,
        f"函数体 {len(ret)} 字符",
    )

    # ---- 9. 新单测在、且钉着关键两条；设计规范里记着这条 ----
    t = read(TEST)
    c.ok(
        "FieldSelectionTest.kt 在，且钉着「打 15 得 15」与旧病「115」两条",
        t.count("@Test") >= 5
        and '"15"' in t
        and '"115"' in t
        and "typedQty(" in t
        and "selectedAll(" in t
        and "fieldAtEnd(" in t,
        f"@Test {t.count('@Test')} 条",
    )
    doc = read(DOC)
    c.ok(
        "设计规范里记着这条（否则下一个人还会各写一份）",
        "聚焦即全选" in doc and "FieldSelection" in doc,
        "06_DESIGN_SYSTEM.md 里没记这条",
    )

    # ---- 10. 新红线必须配反向验证（防「永远红/永远绿」两边都不成立）----
    c.ok(
        "这条红线配了反向验证脚本",
        (ROOT / REVERSE).exists(),
        f"找不到 {REVERSE}",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 共用件唯一：selectedAll / fieldAtEnd / selectAllOnFocus 各 1 处（0 处也红）")
        print("     · selectedAll 真的选中 0..length；开关关着时原样返回")
        print("     · 全树只有 6 个文件认识它、只有 3 处挂上去；没人把它默认成 true")
        print("     · 步进器走 value = field ＋ 挂全选 ＋ 仍然走 typedQty（没有第二份 9999）")
        print("     · SoTextField / FormInputRow 的开关默认 false，只在签名区一处")
        print("     · 账本数量 / 采购单行数量这两处都打开了开关")
        print("     · 默认值（1 / 1）与 QTY_MIN/QTY_MAX/QTY_DIGITS 一个字没动")
        print("     · 退货页 OrderReturnLines 体内仍然没有输入框（口径没被顺手统一）")
        print("     · 新单测 / 设计规范 / 反向验证脚本都在")

    return c.report("数量框「点进去就是整串选中」")


if __name__ == "__main__":
    sys.exit(main())
