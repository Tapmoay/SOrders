# -*- coding: utf-8 -*-
"""_check_downstream_price_cards.py —— 「下游定价」页面走**甲案**（CHG-0131）的判据。

## 用户在样张三选一里拍板的那句话（2026-10-15 口述逐字）
> 「然后我那个改的样式啊，我选择方案甲」

甲案是什么（样张 _tmp/mock_pricing/index.html 与 preview_full.png 的甲＝推荐版）：
- 商品列表页上**一件商品一张卡**：卡上写着「卖给下游的价」大字价 ＋「我拿货（参考）」，
  中段是**「全部下游的默认价」一个输入框 ＋ 保存**，下段是「按人定价 · N 人」＋ 右边一颗「定价」。
- **默认价直接在列表卡片上改**（不必进抽屉）；只有要给**某一个人**单独定价时，才点「定价」进底部抽屉。
- 抽屉里两档（在用 / 回收站）＋ 每位下游一行（姓名 ＋ 电话 ＋ 单价输入框 ＋ 保存）＋「删除这条价」。

## 这条改动最容易走样的地方（走样了不报错、不崩、单测也不会红）
| 写法 | 后果 |
| --- | --- |
| 把默认价那一格又塞回抽屉 | 用户明说「默认价直接在列表卡片上改」，多一层就多一次点错 |
| 卡片上不做按人的入口 | 「按人定价 · N 人」那行没了，就没法给某一个人单独定价 |
| 一人一行改成「一人一条价」 | 没单独定过价的人**整行消失**，用户以为那个人不能定价 |
| 单价输入框抄成三份 | 过滤规则 / 整串选中的口径迟早漏一处（全 App 就一处 SoTextField） |
| 主色写成 #009663 | 那是派单文书里的旧值，**全仓不存在**（现值 ThemeGreen = 0xFF006C43） |
| 钱用别的颜色 | 钱的焦糖是 MoneyOrange = 0xFFBC7730，与这一页那个大字价同一个色 |
| 抽屉不 fillMaxHeight + verticalScroll | 人一多就滚不动，错误行（FormErrorLine）还跟表单不在同一屏 |
| 旧的两条红留着 | _check_input_rules.py / _check_sheet_form_pages.py 会一直红着 |

## 判据（清单全部自己算，不许手写文件列表）
 0. 反空转：三个源码文件 / 单测 / 变更单读得到；屏 ≥400 行、纯函数 ≥60 行；卡片与抽屉两个窗口抽得出来
 1. 一人一（商品）卡：列表 items(vm.products) 在；DownstreamPriceCard 定义 1 处、调用 1 处；卡走共用 SectionCard（16dp 圆角）；卡上有「按人定价 · N 人」且 N 现算；**卡里不再展开按人明细**
 2. 默认价就在卡片上改：卡体里 DownstreamPriceInput ＋ saveLabel = "保存" ＋ onSave = { vm.save(product, null) }；「我拿货（参考）」兜底「没记录」；大字价 ¥ + 26sp + MoneyOrange；卡体里**没有** ModalBottomSheet(（不必进抽屉）；错误跟这张卡走（formErrorProductId）
 3. 单人定价才走抽屉：全屏恰 1 个 ModalBottomSheet( 且**没自己传 containerColor**（抽屉底色走 Token）；「定价」按钮 onclick = vm.openPricing(product)；VM 有 pricingProductId / openPricing / closePricing；抽屉 fillMaxHeight(0.9f) ＋ verticalScroll；两档 SegmentedPicker ＋「在用 · N 人」「回收站 · N 条」；每人一行 personRows(...) ＋ vm.save(product, row.contactId)；抽屉里没有裸输入框
 4. 三个视觉常量按**仓库现值**：Color.kt 的 ThemeGreen 0xFF006C43 / MoneyOrange 0xFFBC7730；Theme.kt 的 medium = RoundedCornerShape(16.dp)；全仓 ui/ 下现算 #009663 命中 0；主按钮 Modifier.height(52.dp) 恰 1 处且落在单价输入组里；SoTextField( 恰 1 处调用；selectAllOnFocus = true 恰 1 处
 5. 「删除这条价」的入口：PersonPriceRow 里 TextButton{ Text("删除这条价") } 的 onclick 是 vm.askDelete(own)；二次确认 title = "删除这条价？" ＋ deleteHint；回收站那条仍挂本行（"已删除 ¥" ＋「恢复」）；按人行不再有旧版泛泛的 Text("删除")
 6. 顺手修掉的两条旧红：python -X utf8 跑 _check_input_rules.py / _check_sheet_form_pages.py 都要 EXIT 0；口径名称框的书面排除键在旧判据里；ProductCostPriceSheet.kt 抽屉补了 fillMaxHeight（含 import）
 7. 纯函数 + 单测：DownstreamPriceCards.kt 里没有 @Composable / MaterialTheme / androidx.compose；八个纯函数都在；draftKeyOf 带商品编号；软删那条不算价；行序跟联系人表一致；无主价排最后；单测 @Test ≥8 且引用 ≥6 个纯函数名
 8. 由来与配套：屏 KDoc 写下 甲案 / 2026-10-15 / CHG-0131；变更单九节齐全且含拍板原话；反验脚本 ≥5 条注入且含 read_bytes/write_bytes/sha256/anchor_preflight 四个关键字
 9. 数量判据：本判据跑到的项数不低于下限（低于下限＝清单过期，先报错而不是安静地什么都不查）

## R4-BOUNDARY-JUSTIFICATION:
本判据钉的是**表现层**（ui/shipper 的两屏 + 共用件用量）与**纯计算层**（DownstreamPriceCards.kt 的八个纯函数）的字面量结构，
外加两条**既有**静态判据的 EXIT（它们本来就是这块的账：ProductCostPriceSheet.kt 的 :173 输入框与 :80 抽屉）。
不改核心区（core/ / data/ 的协议与存储），不碰后端；Data Contract 无变化（沿用 /api/v1/shipper-prices 的既有字段）。
之所以逐条钉死而不是"看截图对不对"：这几个形状（一人一行、默认价在卡上、删除入口、抽屉滚动）
错了都**不会报错**，只会在真机上让用户多点一次、或者让某个人从列表里消失。

## ⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：python _tools/qa/_reverse_verify_downstream_price_cards.py
用法：python _tools/qa/_check_downstream_price_cards.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SHIPPER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper"
SCREEN = SHIPPER / "ShipperPricesScreen.kt"
VM = SHIPPER / "ShipperPricesViewModel.kt"
PURE = SHIPPER / "DownstreamPriceCards.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/shipper/DownstreamPriceCardsTest.kt"
OLD_SHEET = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductCostPriceSheet.kt"
COLOR = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt"
THEME = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Theme.kt"
UI_DIR = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui"
INPUT_RULES_CHECK = ROOT / "_tools/qa/_check_input_rules.py"
SHEET_CHECK = ROOT / "_tools/qa/_check_sheet_form_pages.py"
REVERSE = ROOT / "_tools/qa/_reverse_verify_downstream_price_cards.py"
CHANGE = ROOT / "docs/changes/CHG-0131.md"

MIN_SCREEN_LINES = 400      # 现算：改版后 518 行
MIN_PURE_LINES = 60         # 现算：106 行
MIN_MONEY_COLOR = 3         # 卡上徽标 / 大字价 / 保存键
MIN_TESTS = 8               # 现算：10 个 @Test
MIN_INJECTIONS = 5
MIN_CHECKS = 55             # 本脚本实际会跑的项数下限（低于它＝清单过期）

C = Checker()


def raw(p: Path) -> str:
    return read(p) if p.is_file() else ""


def body_of(src: str, decl: str) -> str:
    """从 decl 那句声明起，切到下一个同级声明之前（@Composable / @OptIn / fun 都算边界）。"""
    i = src.find(decl)
    if i < 0:
        return ""
    heads = ("\n@Composable", "\n@OptIn", "\nprivate fun ", "\ninternal fun ", "\nfun ")
    ends = [j for j in (src.find(h, i + len(decl)) for h in heads) if j >= 0]
    return src[i:min(ends)] if ends else src[i:]


def call_args(src: str, call: str) -> str:
    """抠出 call( ... ) 括号里的文本（按括号配平，够用：这几处括号在字符串里也是配平的）。"""
    i = src.find(call)
    if i < 0:
        return ""
    j = src.find("(", i)
    depth = 0
    for k in range(j, len(src)):
        ch = src[k]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return src[j + 1:k]
    return ""


def run_check(path: Path) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-X", "utf8", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def finish() -> int:
    total = C.n_ok + len(C.fails)
    if C.fails:
        print("")
        print(f"❌ {len(C.fails)} 项不通过（通过 {C.n_ok} 项）")
        for label, detail in C.fails:
            print(f"   - {label}")
            if detail:
                print(f"       {detail}")
        print(f"_check_downstream_price_cards: {C.n_ok}/{total} 通过")
        return 1
    print("")
    print(f"✅ 全部 {C.n_ok} 项通过：下游定价＝甲案（一人一行 / 默认价在卡上 / 删除有入口 / 两条旧红已修）")
    print(f"_check_downstream_price_cards: {C.n_ok}/{total} 通过")
    return 0


def main() -> int:
    src = raw(SCREEN)
    vm = raw(VM)
    pure = raw(PURE)
    test = raw(TEST)
    old_sheet = raw(OLD_SHEET)
    code = strip_comments(src)
    pure_code = strip_comments(pure)

    # ── 0. 反空转 ───────────────────────────────────────────────────────────
    C.section("0. 反空转（读不到 / 窗口抽不出来时，下面每一条都会空过）")
    C.ok("三个源码文件都读得到（屏 / VM / 纯函数）", bool(src) and bool(vm) and bool(pure),
         f"screen={len(src)}ch vm={len(vm)}ch pure={len(pure)}ch")
    C.ok(f"屏正文 ≥{MIN_SCREEN_LINES} 行", len(src.splitlines()) >= MIN_SCREEN_LINES,
         f"现算 {len(src.splitlines())} 行")
    C.ok(f"纯函数文件 ≥{MIN_PURE_LINES} 行", len(pure.splitlines()) >= MIN_PURE_LINES,
         f"现算 {len(pure.splitlines())} 行")

    card_decl = "private fun DownstreamPriceCard("
    sheet_decl = "private fun DownstreamPersonSheet("
    row_decl = "private fun PersonPriceRow("
    input_decl = "private fun DownstreamPriceInput("
    card = body_of(src, card_decl)
    sheet = body_of(src, sheet_decl)
    prow = body_of(src, row_decl)
    pinput = body_of(src, input_decl)
    card_c = strip_comments(card)
    sheet_c = strip_comments(sheet)
    prow_c = strip_comments(prow)
    pinput_c = strip_comments(pinput)
    C.ok("卡片 / 抽屉 / 按人行 / 单价输入 四个窗口都抽得出来",
         bool(card) and bool(sheet) and bool(prow) and bool(pinput),
         f"card={len(card)} sheet={len(sheet)} row={len(prow)} input={len(pinput)}")
    C.ok("卡片组件定义恰 1 处（不许有第二份「一人一卡」的实现）",
         src.count(card_decl) == 1, f"现算 {src.count(card_decl)} 处")
    C.ok("卡片渲染点 ≥1 处（列表真的把它画出来了）",
         len(re.findall(r"items\(vm\.products", code)) >= 1,
         f"现算 {len(re.findall(r'items\(vm\.products', code))} 处")

    # ── 1. 一人（一商品）一卡 ───────────────────────────────────────────────
    C.section("1. 甲案·一：商品列表页一件商品一张卡")
    C.ok("列表按商品铺卡：items(vm.products, key = { it.productId })",
         "items(vm.products, key = { it.productId })" in code,
         "改回手写 forEach 或丢掉 key 都会让「重进页面卡片乱跳」回归")
    C.ok("卡组件被调用恰 1 处（定义 1 + 调用 1）", src.count("DownstreamPriceCard(") == 2,
         f"现算 {src.count('DownstreamPriceCard(')} 处")
    C.ok("卡走共用 SectionCard（圆角 16dp 从 MaterialTheme.shapes.medium 来）",
         "SectionCard {" in card_c, "卡片不许自己 new 一个 Surface + RoundedCornerShape")
    C.ok("卡上有「按人定价 · N 人」且 N 现算（product.contactPriceCount）",
         '"按人定价 · " + product.contactPriceCount + " 人"' in card_c)
    C.ok("卡里有进按人明细的「定价」按钮", "vm.openPricing(product)" in card_c)
    C.ok("卡里**不再**展开按人明细（改版前的卡内展开必须消失）",
         "personRows(" not in card_c and "vm.contacts" not in card_c,
         "卡里一旦重新铺人，就退回「默认价和按人挤在一张卡里」的旧样子")
    C.ok("空态那句仍在（一件能定价的商品都没有时要说人话）",
         "你能定价的商品还一个都没有" in src)

    # ── 2. 默认价就在卡片上改 ───────────────────────────────────────────────
    C.section("2. 甲案·一：默认价直接在列表卡片上改（不必进抽屉）")
    C.ok("卡上就是「全部下游的默认价」那一格：DownstreamPriceInput(", "DownstreamPriceInput(" in card_c)
    C.ok('卡上那颗按钮写的是「保存」', 'saveLabel = "保存",' in card_c)
    C.ok("卡上保存写的是默认价（save(product, null)）", "onSave = { vm.save(product, null) }," in card_c)
    C.ok("卡上仍写「我拿货（参考）」（只作参考，不是给下游的价）", "我拿货（参考）" in card_c)
    C.ok("没记进货价时兜底「没记录」", '"没记录"' in card_c)
    C.ok("大字价 = ¥ + formatMoney(...)（钱必须过显示漏斗）",
         '"¥" + formatMoney(fallback)' in card_c)
    C.ok("大字价用 26sp ＋ 钱的焦糖 MoneyOrange（与账本同一个色）",
         "fontSize = 26.sp" in card_c and "Color(MoneyOrange)" in card_c)
    C.ok("卡体里**没有** ModalBottomSheet(（默认价不必进抽屉）",
         "ModalBottomSheet(" not in card_c, "用户明说：默认价就在卡片上改")
    C.ok("错误跟着这张卡走：按 productId 分流",
         "if (vm.formErrorProductId == product.productId) {" in code and "FormErrorLine(vm.formError)" in code)

    # ── 3. 单人定价才走抽屉 ─────────────────────────────────────────────────
    C.section("3. 甲案·二：只有给某一个人单独定价，才进底部抽屉")
    C.ok("全屏恰 1 个 ModalBottomSheet(（抽屉只有一处）",
         src.count("ModalBottomSheet(") == 1, f"现算 {src.count('ModalBottomSheet(')} 处")
    C.ok("这个抽屉没自己传 containerColor（底色走 Token，房规）",
         "containerColor" not in call_args(code, "ModalBottomSheet("),
         "全库抽屉底色只认 SheetSurface 一个来源")
    C.ok("抽屉体 fillMaxHeight(0.9f)：一打开就占满可用高度", "fillMaxHeight(0.9f)" in sheet_c)
    C.ok("抽屉体 verticalScroll(rememberScrollState())：人多了能滚",
         "verticalScroll(rememberScrollState())" in sheet_c)
    C.ok("抽屉里错误行与表单同屏（FormErrorLine）", "FormErrorLine(vm.formError)" in sheet_c)
    C.ok("抽屉顶上两档：SegmentedPicker(", "SegmentedPicker(" in sheet_c)
    C.ok("两档的文案带现算人数：「在用 · N 人」", '"在用 · " + activePersonCount(vm.prices) + " 人"' in sheet_c)
    C.ok("两档的文案带现算条数：「回收站 · N 条」", '"回收站 · " + deletedCount(vm.prices) + " 条"' in sheet_c)
    C.ok("切档真的传到 VM（toggleIncludeDeleted）", "vm.toggleIncludeDeleted(it == 1)" in sheet_c)
    C.ok("**一位下游一行**（personRows 把「没价的人也铺出来」）",
         "personRows(vm.contacts, vm.prices, vm.includeDeleted).forEach { row ->" in sheet_c,
         "按「有价才有一行」铺，没定过价的人会整行消失")
    C.ok("抽屉里那一格（全部下游的默认价）也走同一个 DownstreamPriceInput（不另抄一个）",
         sheet_c.count("DownstreamPriceInput(") == 1,
         f"现算 {sheet_c.count('DownstreamPriceInput(')} 处")
    C.ok("抽屉里那一格走的是同一个单价输入组（不另抄一个 SoTextField）",
         sheet_c.count("SoTextField(") == 0 and "DownstreamPriceInput(" in sheet_c,
         "抽屉那一格只是把 DownstreamPriceInput 摆进来，自己不再写输入框")
    C.ok("抽屉里没有裸输入框（全 App 只认 SoTextField 一个实现）",
         "OutlinedTextField(" not in code and "BasicTextField(" not in code)
    C.ok("抽屉左上角那颗「收起」在（SheetCloseButton）", "SheetCloseButton(" in sheet_c)

    # ── 4. 视觉常量 ─────────────────────────────────────────────────────────
    C.section("4. 三个视觉常量按仓库现值（派单文书里的 #009663 / 45dp 在仓库里不存在）")
    color = raw(COLOR)
    theme = raw(THEME)
    C.ok("主色现值在 Color.kt：val ThemeGreen = 0xFF006C43",
         re.search(r"val ThemeGreen = 0xFF006C43", color) is not None,
         "2026-10-09 由蓝换深绿；#009663 是派单文书里的旧值")
    C.ok("钱的焦糖在 Color.kt：val MoneyOrange = 0xFFBC7730",
         re.search(r"val MoneyOrange = 0xFFBC7730", color) is not None)
    C.ok("卡片圆角 16dp 的真身在 Theme.kt：medium = RoundedCornerShape(16.dp)",
         re.search(r"medium = RoundedCornerShape\(16\.dp\)", theme) is not None)
    stale = sorted(p.relative_to(ROOT).as_posix()
                   for p in UI_DIR.rglob("*.kt") if "009663" in raw(p))
    C.ok("全仓 ui/ 下没有 #009663（现算 glob：一个文件都不许有）", not stale,
         f"现算命中：{stale}")
    C.ok(f"屏上钱的焦糖 ≥{MIN_MONEY_COLOR} 处（卡上徽标 / 大字价 / 保存键）",
         src.count("Color(MoneyOrange)") >= MIN_MONEY_COLOR,
         f"现算 {src.count('Color(MoneyOrange)')} 处")
    C.ok("主色用在卡片主按钮上：accent = Color(ThemeGreen)", "accent = Color(ThemeGreen)," in src)
    C.ok("主按钮高 52dp：Modifier.height(52.dp) 恰 1 处",
         src.count("Modifier.height(52.dp)") == 1, f"现算 {src.count('Modifier.height(52.dp)')} 处")
    C.ok("那 52dp 落在单价输入组里（主按钮就是它右边那颗）",
         "Modifier.height(52.dp)" in pinput_c)
    C.ok("主按钮底色是钱的焦糖（ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange))）",
         "colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange))," in pinput_c)
    C.ok("输入框唯一实现：SoTextField( 全屏恰 1 处调用",
         src.count("SoTextField(") == 1, f"现算 {src.count('SoTextField(')} 处")
    C.ok("那唯一一处就在单价输入组里", "SoTextField(" in pinput_c)
    C.ok("单价框「点进去整串选中」：selectAllOnFocus = true 恰 1 处",
         src.count("selectAllOnFocus = true") == 1)
    C.ok("那唯一一处也在单价输入组里", "selectAllOnFocus = true" in pinput_c)

    # ── 5. 删除这条价 ───────────────────────────────────────────────────────
    C.section("5. 「删除这条价」的入口（一人一行，各删各的）")
    C.ok("按人行里那颗按钮逐字是「删除这条价」", 'Text("删除这条价")' in prow_c)
    C.ok("按人行的保存写的是这个人的价（save(product, row.contactId)）",
         "onSave = { vm.save(product, row.contactId) }," in prow_c)
    C.ok("每人那一行也走同一个 DownstreamPriceInput（不另抄一个）",
         prow_c.count("DownstreamPriceInput(") == 1,
         f"现算 {prow_c.count('DownstreamPriceInput(')} 处")
    C.ok("点它走的是这一行那条价（vm.askDelete(own)）",
         "TextButton(onClick = { vm.askDelete(own) }, enabled = !vm.acting) { Text(\"删除这条价\") }" in prow_c)
    C.ok("删除前二次确认：title = 「删除这条价？」", 'title = "删除这条价？"' in src)
    C.ok("确认框把这条价的价钱说清楚（deleteHint）", "deleteHint(deleting)" in src)
    C.ok("确认按钮逐字「删除」（不是「确定」）", 'confirmText = "删除",' in src)
    C.ok("软删那句必须说：以后下的单按新价算，已经算过的钱一分不动",
         "已删除这条价 —— 以后下的单按新价算，已经算过的钱一分不动" in vm)
    C.ok("回收站里那一行仍挂在原处：「已删除 ¥…」＋「恢复」",
         '"已删除 ¥" + money(own)' in prow_c and "vm.restore(own)" in prow_c)
    C.ok("默认价那一行也有自己的已删除长相（fallback）", '"已删除 ¥" + money(fallback)' in sheet_c)
    C.ok("按人行不再有旧版那颗泛泛的 Text(「删除」)",
         'Text("删除")' not in code, "旧文案分不清删的是哪条价")

    # ── 6. 顺手修掉的两条旧红 ───────────────────────────────────────────────
    C.section("6. 顺手修掉的两条旧红（同一块账：ProductCostPriceSheet.kt）")
    rc1, out1 = run_check(INPUT_RULES_CHECK)
    C.ok("_check_input_rules.py 变绿（EXIT 0）", rc1 == 0, out1.strip().splitlines()[-1] if out1.strip() else "")
    rc2, out2 = run_check(SHEET_CHECK)
    C.ok("_check_sheet_form_pages.py 变绿（EXIT 0）", rc2 == 0, out2.strip().splitlines()[-1] if out2.strip() else "")
    C.ok("口径名称框的书面排除键写在旧判据里（不是靠改判据蒙过去）",
         "口径名称，例如「返点后成本」" in raw(INPUT_RULES_CHECK),
         "这一格是自由文本的中文口径名，不是金额；排除要留字面证据")
    C.ok("ProductCostPriceSheet.kt 抽屉补了 fillMaxHeight（含 import）",
         "Modifier.fillMaxWidth().fillMaxHeight(0.9f)" in old_sheet
         and "import androidx.compose.foundation.layout.fillMaxHeight" in old_sheet)

    # ── 7. 纯函数 + 单测 ────────────────────────────────────────────────────
    C.section("7. 纯函数 + 单测（钱的那几个数不许长在界面里）")
    want_fns = ["personName", "defaultPrice", "personPrice", "effectiveUnitPrice",
                "activePersonCount", "deletedCount", "draftKeyOf", "personRows"]
    got_fns = set(re.findall(r"^fun ([A-Za-z][A-Za-z0-9]*)\(", pure, re.M))
    missing = [f for f in want_fns if f not in got_fns]
    C.ok("纯函数文件里没有 @Composable（真的能在 JVM 单测里直接调）", "@Composable" not in pure)
    C.ok("纯函数文件里没有 MaterialTheme（不碰主题）", "MaterialTheme" not in pure)
    C.ok("纯函数文件里没有 androidx.compose 导入（不碰 Compose）", "androidx.compose" not in pure)
    C.ok(f"八个纯函数都在（缺一个就报出来）：现算 {len(got_fns)} 个", not missing, f"缺：{missing}")
    C.ok("草稿键按商品编号算（draftKeyOf 带 productId）",
         'productId.toString() + ":" +' in pure_code)
    C.ok("软删的那条不算价（effectiveUnitPrice 先看 !own.isDeleted）",
         "if (own != null && !own.isDeleted) return own.unitPrice" in pure_code)
    C.ok("同一套优先级也给默认价用（fallback 也要 !isDeleted）",
         "return if (fallback != null && !fallback.isDeleted) fallback.unitPrice else null" in pure_code)
    C.ok("一人一行的行序跟联系人表一致（contacts.map）",
         "val rows = contacts.map { contact ->" in pure_code)
    C.ok("无主价排最后（不跟人混在一起）",
         "filter { it.contactId != null && it.contactId !in known }" in pure_code)
    C.ok(f"单测 @Test ≥{MIN_TESTS} 个", test.count("@Test") >= MIN_TESTS, f"现算 {test.count('@Test')} 个")
    C.ok("单测是 JUnit4（import org.junit.Test）", "import org.junit.Test" in test)
    cited = [f for f in want_fns if f + "(" in test]
    C.ok("单测至少点到 6 个纯函数（不然测的是别的东西）", len(cited) >= 6, f"现算点到：{cited}")
    C.ok("VM 侧接线：草稿键按商品 + 人算（draftKeyOf( 在 VM 里被用）", "draftKeyOf(" in vm)
    C.ok("草稿表的键是 String（同一件商品上每个人的草稿互不串）",
         "mutableStateMapOf<String, String>()" in vm)

    # ── 8. 由来与配套 ───────────────────────────────────────────────────────
    C.section("8. 由来与配套（用户口径 / 变更单 / 反验）")
    C.ok("屏 KDoc 写下由来：甲案 + 日期 + 单号",
         "甲案" in src and "2026-10-15" in src and "CHG-0131" in src)
    md = raw(CHANGE)
    C.ok("变更单 docs/changes/CHG-0131.md 在", bool(md))
    heads = re.findall(r"^## .*$", md, re.M)
    need_heads = ["## ① 六问", "## ② Must Change / Must Not Change", "## ③ Boundary",
                  "## ④ Behavior Contract", "## ⑤ Data Contract", "## ⑥ CHG 专章",
                  "## ⑦ 测试", "## ⑧ 证据", "## ⑨ 关闭"]
    miss_heads = [h for h in need_heads if not any(x.startswith(h) for x in heads)]
    C.ok(f"变更单九个 H2 小节齐全（现算 {len(heads)} 个 H2）", not miss_heads, f"缺：{miss_heads}")
    C.ok("变更单里引用了用户拍板原话（逐字）",
         "然后我那个改的样式啊，我选择方案甲" in md)
    rev = raw(REVERSE)
    C.ok("反验脚本 _tools/qa/_reverse_verify_downstream_price_cards.py 在", bool(rev))
    # ⚠️ 不能在 "INJECTIONS" 后面找第一个 "]"：类型标注 list[tuple[str, ...]] 自己就带方括号，
    #    那样切出来的块是空的（现算 0 条注入＝假红）。要从 "= [" 起、到行首的 "]" 止。
    _i0 = rev.find("INJECTIONS")
    _i1 = rev.find("= [", _i0) if _i0 >= 0 else -1
    _i2 = rev.find("\n]", _i1) if _i1 >= 0 else -1
    block = rev[_i1:_i2] if (_i0 >= 0 and _i1 >= 0 and _i2 > _i1) else ""
    n_inj = len(re.findall(r"^\s*\(\s*$", block, re.M))
    C.ok(f"反验脚本 ≥{MIN_INJECTIONS} 条注入（现算 {n_inj} 条）", n_inj >= MIN_INJECTIONS)
    for kw in ("read_bytes", "write_bytes", "sha256", "anchor_preflight"):
        C.ok(f"反验脚本含关键字 {kw}", kw in rev)

    # ── 9. 数量判据 ─────────────────────────────────────────────────────────
    C.section("9. 数量判据（低于下限＝清单过期，先报错）")
    total = C.n_ok + len(C.fails)
    C.ok(f"本判据一共跑了 {total} 项（下限 {MIN_CHECKS}）", total >= MIN_CHECKS,
         "项数掉下来通常意味着上面某段清单被删空了")
    return finish()


if __name__ == "__main__":
    sys.exit(main())
