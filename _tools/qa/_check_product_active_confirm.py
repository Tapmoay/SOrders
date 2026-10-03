# -*- coding: utf-8 -*-
"""红线：沽清 / 上架必须先问一句，而且那句话只有一份（CHG-0025 / P29，2026-10-03）。

## 这条是怎么来的
2026-10-03 的 E2E 走查（P29）实测：商品管理卡上的「沽清」与批量操作页的
「沽清（下架）/ 上架」都是**一点即改**，只有一句事后提示 —— 走查当时误触一次，
就把一件商品静默下架了，是事后翻列表才发现的。同一个页面上的「删除」反倒有确认
（DangerConfirmDialog），而"改在售状态"这个每天都会点的动作一句都不问。

## 为什么必须有机器的判据
"补一个确认弹窗"本身很容易做对，难的是它不被绕开：

- 卡片上那个按钮只要有人改回 onToggle = { vm.toggleActive(p) }，弹层就成了摆设；
- 单卡与批量各写一句后果文案，下一次改口径必然漏一页（本仓库的老毛病）；
- 判据若只写"别处不许再定义一份"，把零件改名之后它会安静地全绿 —— 所以 0 处也红。

所以判据分五层：

1. 弹层**只有一处定义**（在 ui/common/ProductCardKit.kt，且别处 0 处）；
2. **两个入口都用它**（商品管理页的卡片、批量操作页的两个胶囊）；
3. **入口不许绕开**：卡片那行只能是 onToggle = { toggleFor = p }；
   批量页 vm.setActive( 只许出现在弹层的 onConfirm 里，两个胶囊都先过 canAct()；
4. **两个方向都在**（上架 = 绿 Success / 沽清 = 红 colorScheme.error），
   而且后果那两句话**全库只有一份**；
5. 与反向验证脚本配对（防"永远红 / 永远绿"）。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。P29 的病是「点一下没有任何回问」——
卡片上写 `onToggle = { vm.toggleActive(p) }`（一点即改）与写 `onToggle = { toggleFor = p }`
（先问一句）**类型上完全一样**，弹层写得再对、没人调用也照样编译、照样跑单测全绿；
单卡与批量各写一份后果文案，同样没有任何编译器会拦。所以只能扫**结构**：弹层唯一一份、
两个入口都真的用它、入口那条线不许绕开、两个方向与那两句话都只有一份、批量先过勾选闸。
反向破坏用例由 `_tools/qa/_reverse_verify_product_active_confirm.py`（9 条注入）负责；
「点了确实弹、取消确实什么都没改」那一头由 2026-10-03 模拟器 5554 实测的九张截图负责
（`_tmp/c25_a…i`）。本判据只读源码与文档（`read()`），不连库、不 import 后端、不跑迁移。

用法：python _tools/qa/_check_product_active_confirm.py
     python _tools/qa/_check_product_active_confirm.py --list   # 只列它到底在查什么
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
# 注释剥离**只有一份实现**（那个状态机是为 "image/*" 这种字符串写的，抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

KIT = AND / "ui/common/ProductCardKit.kt"
LIST = AND / "ui/dispatcher/ProductsScreen.kt"
LIST_VM = AND / "ui/dispatcher/ProductsViewModel.kt"
BATCH = AND / "ui/dispatcher/ProductBatchScreen.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = "_tools/qa/_reverse_verify_product_active_confirm.py"

#: 扫到的界面文件数下限（防目录改名 / 搬走之后"一个文件都没扫到"也算过）
MIN_UI_FILES = 100

#: 抽出来的函数体字符数下限（**抽取失效比判据腐烂更危险** —— 那会变成一条永远绿的检查）
BODY_FLOOR = 300

#: 弹层的名字（改名也要红：0 处定义 = 这条红线在空转）
DIALOG = "ProductActiveConfirmDialog"

#: 两句话后果 —— 全库只许各有一份（单卡与批量各写一句，下次改口径必然漏一页）
CONSEQUENCES = ["库存、订单、账本都不动", "库存、价格、分组都不动"]


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def count(needle: str, text: str) -> int:
    return text.count(needle)


def fn_body(src: str, sig: str) -> str:
    """sig（如 fun toggleActive(）那个函数的**函数体**（按大括号配对，不是按行猜）。

    为什么必须只看函数体：ProductsScreen.kt 与 ProductBatchScreen.kt 都是大文件，
    而"这一段里还有没有第二个入口"只有限定在那一段里问才成立。
    """
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
    if refuse_if_injecting("沽清/上架二次确认检查"):
        return 1

    c = Checker()
    print("沽清 / 上架的二次确认（CHG-0025 / P29）：2026-10-03")

    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    # ---- 1. 四个文件都在 ----
    for p, why in (
        (KIT, "确认弹层的唯一实现处（商品卡工具箱）"),
        (LIST, "商品管理页（卡片上的沽清 / 上架）"),
        (LIST_VM, "商品管理页 VM（toggleActive）"),
        (BATCH, "批量操作页（那一排胶囊）"),
    ):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 存在（{why}）", p.exists(), "文件被搬走 / 改名了")

    kit = code(KIT)
    lst = code(LIST)
    lvm = code(LIST_VM)
    bat = code(BATCH)

    # ---- 2. 弹层只有一处定义（0 处也红）----
    here = count(f"fun {DIALOG}(", kit)
    elsewhere = [
        p.relative_to(AND).as_posix()
        for p in ui_files
        if p != KIT and count(f"fun {DIALOG}(", code(p))
    ]
    c.ok(
        f"{DIALOG} 只有一处定义（在 ui/common/ProductCardKit.kt，且别处 0 处）",
        here == 1 and not elsewhere,
        f"这里 {here} 处；别处还有 {elsewhere}",
    )

    # ---- 3. 弹层函数体抽得出来 + 它长什么样 ----
    body = fn_body(kit, f"fun {DIALOG}(")
    c.ok(
        f"弹层函数体抽得出来（≥ {BODY_FLOOR} 字符）",
        len(body) >= BODY_FLOOR,
        f"只抽到 {len(body)} 字符 —— 判据会空转",
    )
    c.ok("弹层是个 AlertDialog", "AlertDialog(" in body, "没找到 AlertDialog(")
    directions = body.count("if (toActive)")
    c.ok(
        "两个方向都在（上架 = 绿 Success / 沽清 = 红 colorScheme.error）",
        directions >= 2 and "Success" in body and "colorScheme.error" in body,
        f"if (toActive) {directions} 处；Success={'Success' in body}；error={'colorScheme.error' in body}",
    )
    c.ok(
        "确认钮文案跟着方向走（上架 / 沽清）",
        'Text(if (toActive) "上架" else "沽清")' in body,
        "确认钮文案不是跟着 toActive 走的",
    )
    c.ok(
        "两句标题都在（重新上架 / 沽清（下架））",
        "重新上架" in body and "沽清（下架）" in body,
        "标题少了某一个方向",
    )
    # Kotlin 里中文是合法的标识符字符：少了花括号，$subject重新上架 会被当成一个标识符（编译不过）
    brace = "$" + "{subject}"
    c.ok(
        "标题里的商品名带花括号（少了花括号编译不过）",
        brace + "重新上架？" in read(KIT) and brace + "沽清（下架）？" in read(KIT),
        "标题里的 subject 少了花括号",
    )

    # ---- 4. 两个入口都用同一个弹层 ----
    for label, src in (("商品管理页", lst), ("批量操作页", bat)):
        c.ok(f"{label} 用共用弹层 {DIALOG}(", f"{DIALOG}(" in src, "这一页没用共用弹层")

    # ---- 5. 商品管理页：卡片只打开弹层，不许直接改 ----
    c.ok(
        "商品管理页：卡片入口写成 onToggle = { toggleFor = p }",
        "onToggle = { toggleFor = p }" in lst,
        "卡片入口不再只是打开弹层",
    )
    c.ok(
        "商品管理页：没有 onToggle = { vm.toggleActive(p) }（P29 那一行）",
        "onToggle = { vm.toggleActive(p) }" not in lst,
        "一点即改的入口又回来了",
    )
    calls = count("vm.toggleActive(", lst)
    i_call = lst.find("vm.toggleActive(")
    i_dlg = lst.find(f"{DIALOG}(")
    c.ok(
        "商品管理页：vm.toggleActive( 只出现一次，且落在弹层调用之后（= 在 onConfirm 里）",
        calls == 1 and i_dlg >= 0 and i_call > i_dlg,
        f"{calls} 处；弹层在第 {i_dlg} 字符、调用在第 {i_call} 字符",
    )
    c.ok(
        "商品管理页：弹层状态是函数级的 var toggleFor（声明在 Scaffold 之外）",
        "var toggleFor by remember" in lst and "mutableStateOf<ProductDto?>(null)" in lst,
        "toggleFor 没了",
    )
    c.ok(
        "商品管理页：弹层说清了动的是哪一件（subject = 「商品名」）",
        '"「" + p.name + "」"' in lst,
        "弹层没把商品名写进去",
    )

    # ---- 6. 批量操作页：两个胶囊先过勾选闸，动作只在 onConfirm 里 ----
    chip_lines = [
        ln
        for ln in bat.splitlines()
        if 'ActionChip("沽清（下架）"' in ln or 'ActionChip("上架"' in ln
    ]
    bad_chips = [ln.strip()[:70] for ln in chip_lines if "canAct()" not in ln]
    c.ok(
        "批量操作页：两个胶囊都在动作前过 canAct() 勾选闸",
        len(chip_lines) == 2 and not bad_chips,
        f"找到 {len(chip_lines)} 行胶囊；没带 canAct() 的：{bad_chips}",
    )
    c.ok(
        "批量操作页：canAct() 在 VM 里，且没勾选时说的是「先勾选商品」",
        "fun canAct(" in bat and "先勾选商品" in fn_body(bat, "fun canAct("),
        "canAct() 没了（或者它不再拦人）",
    )
    setactive = count("vm.setActive(", bat)
    i_sa = bat.find("vm.setActive(")
    i_layer = bat.find("confirmingActive?.let")
    c.ok(
        "批量操作页：vm.setActive( 只出现一次，且落在 confirmingActive?.let 之后（= 在 onConfirm 里）",
        setactive == 1 and i_layer >= 0 and i_sa > i_layer,
        f"{setactive} 处；弹层在第 {i_layer} 字符、调用在第 {i_sa} 字符",
    )
    c.ok(
        "批量操作页：弹层说清了要动几个（选中的 N 个商品）",
        '"选中的 " + vm.selected.size + " 个商品"' in bat,
        "弹层没写清要动几个商品",
    )
    c.ok(
        "批量操作页：vm.error 有人渲染（否则「先勾选商品」一个字都看不见）",
        "OneShotSnackbar(snackbar, vm.error" in bat,
        "vm.error 又没有渲染处",
    )

    # ---- 7. 后果文案全库只有一份 ----
    for phrase in CONSEQUENCES:
        hits = [p.relative_to(AND).as_posix() for p in ui_files if phrase in code(p)]
        c.ok(
            f"「{phrase}」全库只有一份（单卡与批量不许各写一句）",
            hits == ["ui/common/ProductCardKit.kt"],
            f"出现在 {hits}",
        )

    # ---- 8. VM 里那次改动的反馈（成功看得见、失败看得见）----
    tb = fn_body(lvm, "fun toggleActive(")
    c.ok("VM 的 toggleActive 抽得出来", len(tb) >= 100, f"只抽到 {len(tb)} 字符")
    c.ok(
        "VM：toggleActive 期间 acting = true（按钮禁用，防连点两次又改回去）",
        "acting = true" in tb and "finally" in tb,
        "acting 没设（以前就没设过）",
    )
    c.ok(
        "VM：toggleActive 成功后有一句 actionResult（事后看得见改成了什么）",
        "actionResult" in tb and "已沽清" in tb and "已上架" in tb,
        "成功之后没有一句汇报",
    )

    # ---- 9. 规范文档里记了这条 ----
    doc = read(DESIGN)
    c.ok(
        "设计规范里记着这条（否则下一个人还会再补一句自己的文案）",
        DESIGN.exists() and DIALOG in doc,
        "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md 里没记这条",
    )

    # ---- 10. 新红线必须配反向验证（防"永远红 / 永远绿"两边都不成立）----
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 弹层唯一：ProductActiveConfirmDialog 只许在 ui/common/ProductCardKit.kt 定义一次（0 处也红）")
        print("     · 两个入口都用它：商品管理页的卡片、批量操作页的两个胶囊")
        print("     · 入口不许绕开：onToggle 只开弹层；批量页 vm.setActive( 只许在 onConfirm 里，且两个胶囊都过 canAct()")
        print("     · 两个方向都在（上架 = 绿 / 沽清 = 红），后果那两句话全库只有一份")
        print("     · 反向验证脚本在")

    return c.report("沽清 / 上架二次确认（CHG-0025 / P29）")


if __name__ == "__main__":
    sys.exit(main())
