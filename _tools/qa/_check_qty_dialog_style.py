# -*- coding: utf-8 -*-
"""红线：数量小窗的「单位只读显示 / 数字居中 / 步进器」**只有一份实现**（2026-09-23 用户点名）。

## 用户原话（对着选品页「＋」弹出的那个数量小窗）
> 「…**放在最右边**…那个**显示单位**也就这个商品的单位，然后下面是**数量**…
>  那个**中间的数字**把它改成**居中**…还有那个 **+- 的样式和图标样式也全部改一下**，
>  **整体的样貌全都发生改变一下**…非常的不顺眼啊，非常的难受」。

## 这条为什么必须有机器的判据
改之前，「`−` + 数量框 + `+`」这一组东西在**两个弹窗里各写了一遍**，而且长得不一样：

| | 选品页 `QtyDialog` | 下单页行编辑 `LineEditDialog` |
|---|---|---|
| `−` / `+` | 淡蓝实心圆 | **默认色的灰紫**实心圆 |
| 数量框 | 92dp、数字贴左 | 96dp、数字贴左 |
| 数量判据 | `InputRules.intInput(v, 4)…coerceIn(1, 9999) ?: 1` | **同一串再抄一遍** |

而 `OrderCreateScreen.kt` 里当时那句注释写着「全 App 同一个形态，见 `ProductPicker::QtyDialog`」——
**注释说的是愿望，代码是两份**。而"又写一份"这件事从来不报错：编译过、真机上也能用，
只是一次改样式漏一页，两页从此永远不是一个形态。「数字贴左」同理：那是 `textAlign` 的
**缺省值**，没人写错，只是没人写。

所以判据分四层：

1. **只有一处定义**：`QtyStepper` / `typedQty` / `UnitTag` 各 1 处（**0 处也红** ——
   判据不许因为"零件被改名/删掉"而空转）；
2. **两个弹窗都用它**（`QtyDialog`、`LineEditDialog`），而且那两个**函数体里**不许再冒出
   第二份步进器（判据只看函数体：同一个文件别处一个合法的 `Icons.Default.Remove`
   不该被打成假红）；
3. **用户点名的两条**：数字**居中**（`TextAlign.Center` 在步进器体内）、
   单位在**标题槽的最右边**（`title = {` 与 `text = {` 之间出现 `UnitTag(`）；
4. **单位是只读的**：`UnitTag` 体内不许有输入框，`QtyDialog` 的 `unit` **不许回传**
   （`onConfirm` 只回数量）。这与 2026-09-19 用户定的「下单的人不能改单位」是同一条规矩 ——
   那条禁的是**能改的入口**，不是"不许看见单位"。

用法：python _tools/qa/_check_qty_dialog_style.py
     python _tools/qa/_check_qty_dialog_style.py --list   # 只列它到底在查什么
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
# 注释剥离**只有一份实现**（那个状态机是为 `"image/*"` 这种字符串写的，抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

STEPPER = AND / "ui/common/QtyStepper.kt"
PICKER = AND / "ui/common/ProductPicker.kt"
ORDER = AND / "ui/shipper/OrderCreateScreen.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/common/QtyStepperTest.kt"
DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = "_tools/qa/_reverse_verify_qty_dialog.py"

#: 扫到的界面文件数下限（防目录改名/搬走之后"一个文件都没扫到"也算过）
MIN_UI_FILES = 100

#: 抽出来的函数体字符数下限（**抽取失效比判据腐烂更危险** —— 那会变成一条永远绿的检查）
BODY_FLOOR = 200

#: 三个零件的定义名（每一个都必须**只**在 STEPPER 里出现一次）
PARTS = ["QtyStepper", "typedQty", "UnitTag"]


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def fn_body(src: str, sig: str) -> str:
    """`sig`（如 `fun QtyDialog(`）那个函数的**函数体**（按大括号配对，不是按行猜）。

    为什么必须只看函数体：`LineEditDialog` 与 `QtyDialog` 各自在一个大文件里，
    而"这一段里有没有第二份步进器"只有限定在那一段里问才成立。
    """
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


def slot(body: str, start: str, end: str) -> str:
    """函数体里 `start` 与 `end` 之间那一段（用来只看"标题槽"这种具名参数块）。"""
    i = body.find(start)
    if i < 0:
        return ""
    j = body.find(end, i + len(start))
    return body[i:j] if j > 0 else ""


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


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
    if refuse_if_injecting("数量小窗形态检查"):
        return 1

    c = Checker()
    print("数量小窗（单位只读 / 数字居中 / 步进器一份实现）：2026-09-23")

    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    # ---- 1. 三个文件都在 ----
    for p, why in (
        (STEPPER, "数量步进器 + 单位标签的唯一实现处"),
        (PICKER, "选品页（货主与代理下单共用）"),
        (ORDER, "下单页（含行编辑弹窗）"),
    ):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 存在（{why}）", p.exists(), "文件被搬走/改名了")

    stepper = code(STEPPER)
    picker = code(PICKER)
    order = code(ORDER)

    # ---- 2. 三个零件各只有一处定义（0 处也红）----
    for name in PARTS:
        here = count(rf"fun {name}\(", stepper)
        elsewhere = [
            p.relative_to(AND).as_posix()
            for p in ui_files
            if p != STEPPER and count(rf"fun {name}\(", code(p))
        ]
        c.ok(
            f"{name} 只有一处定义（在 ui/common/QtyStepper.kt，且别处 0 处）",
            here == 1 and not elsewhere,
            f"这里 {here} 处；别处还有 {elsewhere}",
        )

    # ---- 3. 四个函数体都抽得出来（抽取失效 → 判据空转）----
    stepper_body = fn_body(stepper, "fun QtyStepper(")
    unit_body = fn_body(stepper, "fun UnitTag(")
    qty_body = fn_body(picker, "fun QtyDialog(")
    line_body = fn_body(order, "fun LineEditDialog(")
    bodies = {
        "QtyStepper": stepper_body,
        "UnitTag": unit_body,
        "QtyDialog": qty_body,
        "LineEditDialog": line_body,
    }
    thin = [k for k, v in bodies.items() if len(v) < BODY_FLOOR]
    c.ok(
        f"四个函数体都抽得出来（各 ≥ {BODY_FLOOR} 字符）",
        not thin,
        f"抽不出来的：{ {k: len(v) for k, v in bodies.items() if k in thin} } —— 判据会空转",
    )

    # ---- 4. 两个弹窗都用同一个步进器（不是各写一遍）----
    for label, body in (("QtyDialog", qty_body), ("LineEditDialog", line_body)):
        c.ok(
            f"{label} 用共用步进器 `QtyStepper(`（不是自己再画一份）",
            "QtyStepper(" in body,
            "没用共用步进器",
        )
        own = []
        if count(r"\bOutlinedTextField\s*\(", body):
            own.append("OutlinedTextField")
        if count(r"Icons\.\w+\.Remove\b", body) or count(r"Icons\.\w+\.Add\b", body):
            own.append("Icons.*.Add/Remove")
        c.ok(
            f"{label} 里没有第二份加减号/数量框（自己画的那几个件）",
            not own,
            f"又自己写了：{own}",
        )

    # ---- 5. 用户点名的两条 ----
    c.ok(
        "数量数字**居中**（`TextAlign.Center` 在步进器体内）—— 用户 2026-09-23 点名的第 ① 条",
        "TextAlign.Center" in stepper_body,
        "数字又贴左了（textAlign 的缺省值就是贴左）",
    )
    for label, body in (("QtyDialog", qty_body), ("LineEditDialog", line_body)):
        title_slot = slot(body, "title = {", "text = {")
        c.ok(
            f"{label} 的单位在**标题槽**里（`UnitTag(` 出现在 `title = {{` 与 `text = {{` 之间）"
            f"—— 用户点名的第 ② 条「放在最右边」",
            "UnitTag(" in title_slot,
            "标题槽里没有单位标签（挪到正文里了 / 删掉了 / title 与 text 的结构变了）",
        )

    # ---- 6. 单位是**只读**的（不许变成能改的输入框、也不许回传）----
    c.ok(
        "单位标签是只读的（`UnitTag` 体内没有任何文本输入框）",
        unit_body != "" and not count(r"\w*TextField\s*\(", unit_body),
        "单位标签里出现了输入框 —— 下单的人又能改单位了（2026-09-19 定的规矩）",
    )
    c.ok(
        "单位**不回传**（`QtyDialog` 只 `onConfirm(qty)`，没有把 unit 递出去）",
        qty_body != ""
        and count(r"onConfirm\(qty\)", qty_body) >= 1
        and not count(r"onConfirm\([^)]*unit", qty_body),
        "unit 被递给 onConfirm 了",
    )

    # ---- 7. 数量判据与上下限只有一份来源 ----
    c.ok(
        "数量判据走共用的 `typedQty(`（步进器的 onValueChange 里）",
        count(r"onValueChange\s*=\s*\{\s*onQtyChange\(typedQty\(", stepper_body) >= 1,
        "步进器没走 typedQty（判据又内联回来了）",
    )
    relit = [
        label
        for label, body in (("QtyDialog", qty_body), ("LineEditDialog", line_body))
        if "9999" in body or "InputRules.intInput(" in body
    ]
    c.ok(
        "两个弹窗里都没有数量的第二位判据（`9999` 字面量 / `InputRules.intInput(`）",
        not relit,
        f"又抄回去了：{relit}",
    )

    # ---- 8. 单测在、且钉着关键用例 ----
    test = read(TEST)
    c.ok(
        "数量判据有 JVM 单测，且钉着关键用例（全角归一 / 0 与空串退下限 / 上限截断）",
        test.count("@Test") >= 5
        and test.count("typedQty(") >= 5
        and "QTY_MAX" in test
        and "QTY_MIN" in test,
        f"@Test {test.count('@Test')} 个、typedQty( {test.count('typedQty(')} 处",
    )

    # ---- 9. 规范文档里记了这条 ----
    doc = read(DOC)
    c.ok(
        "设计规范里记着这条（否则下一个人还会各写一份）",
        DOC.exists() and "QtyStepper" in doc,
        "06_DESIGN_SYSTEM.md §4.21 里没记这条",
    )

    # ---- 10. 新红线必须配反向验证（防"永远红/永远绿"两边都不成立）----
    c.ok(
        "这条红线配了反向验证脚本",
        (ROOT / REVERSE).exists(),
        f"找不到 {REVERSE}",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 零件唯一：QtyStepper / typedQty / UnitTag 各 1 处（0 处也红）")
        print("     · 两个弹窗都用它，且函数体里不许有第二份加减号/数量框")
        print("     · 数字居中 TextAlign.Center；单位在 title 槽（最右边），只读、不回传")
        print("     · 上限只有一个来源（9999 只许在 QtyStepper.kt）")
        print("     · 单测 / 设计规范 / 反向验证脚本都在")

    return c.report("数量小窗形态（单位只读 / 数字居中 / 步进器一份）")


if __name__ == "__main__":
    sys.exit(main())
