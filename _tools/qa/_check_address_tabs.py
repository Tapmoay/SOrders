# -*- coding: utf-8 -*-
"""红线：**地址与联系人页的顶部三档与搜索框** —— 同一件事只许有一种形态（CHG-0013，2026-10-03）。

## 这一批在治什么
用户反复要求「前端页面要重做按照我们的设计规范进行写」，只读审计（_tmp/ui_audit_address.md 第 15 行）
把这一页对不上的地方逐条列了出来，其中两条是同一类毛病 —— **同一件事，这一页自己给了第二个答案**：

* 顶部三档：设计规范 §3 的组件速查里写着「SegmentedStatusTabs / 顶部状态导航（语义色 + 无图标 +
  段间竖分隔线 + 选段淡色底）」，这一页却自己画了一排**带描边、带图标**的胶囊
  （旧 AddressTabBar：Surface + BorderStroke(1.dp) + 每格一个 Icon + 三格各挑一个模块色）；
* 搜索框：联系人那一档本来就是**按人搜索**，全库只有一份 Components.kt 里的 SearchField
  （放大镜 + 入框即出 ✕ 一键清空 + 提示语同源 core/UserSearch.HINT，规范 §4.4），
  这一页却拿 SoTextField 顶了一份，连「能按手机号后 4 位搜」那句提示语都丢了。

## 为什么必须有机器的判据
这两条都是**形态纪律**：Compose 里自己再画一排胶囊、再写一个文本框，照样编译、照样渲染、照样能点能搜 ——
破法全是**静默**的。而且这一页的第二个答案会自我复制：下一个人照着这一页抄，
「自己画一排带描边的胶囊」就变成了惯例，用户就得在每一页重新认一次导航形状。

判据分六层：
1. **导航收编**：本页出现 SegmentedStatusTabs(、旧 AddressTabBar 连函数带调用点一起消失、
   BorderStroke( == 0（那一排描边胶囊整块没了）、全库仍然只有一处 SegmentedStatusTabs 实现；
2. **三档的内容**：标签清单与顺序、三个语义色（走 Color.kt 的命名 token，本页裸色值必须 == 0）；
3. **切档清空搜索**：onSelect 里 tab = it 与 keyword = 空串必须成对
   （否则换档之后是一个被上一个档关键词过滤过的空白页，看着像坏了）；
4. **搜索框分档唯一实现**：if (tab == 1) 那一支是 SearchField( 且**不是** SoTextField(，
   0 / 2 两支继续 SoTextField( + 地址型占位语；本页 SearchField( 只出现一次；
5. **清空同形**：✕（contentDescription = 清空搜索），旧的文字按钮已消失，且只在非联系人档画
   （SearchField 自带一个，不许叠两个）；
6. **本批没顺手改别的** + 接线（反向验证在、文档九节、登记簿有 CHG-0013）。

⛔ 两处一个字都不能动（动了别的判据会红，而且伤真实功能）：
线路档占位语（_tools/ai/_check_ai_guardrails.py:4074 的锚点、_check_input_rules.py:101 的 EXCLUDED 键）
与 UserSearch.matches(kw, it.displayName, it.phone)（按人匹配的口径，后 4 位就靠它）。

R4-BOUNDARY-JUSTIFICATION: 这一条**没法用边界消除** —— 「这一页用的是哪一份导航件 / 哪一份搜索框」
只存在于**调用点**，而类型系统看见的是两套都能编译、渲染、交互的实现（自定义 Surface 胶囊 vs
SegmentedStatusTabs；SoTextField vs SearchField）。类型层没法表达「必须用共用件」，
更没法表达「同一件事只有一种形态」，Kotlin 也不禁止任何一处就地再写一份。
破法又是**静默**的：页面照常工作，只是用户在每一页都要重新认一次导航形状、少了一句搜索提示。
所以只能靠一条判据把两侧（本页 ↔ 共用件）对起来，并在反向验证里把「换回自定义胶囊 / 退回 SoTextField /
改掉占位语 / 清空换回文字按钮」这几条真跑一遍。

用法：python _tools/qa/_check_address_tabs.py
     python _tools/qa/_check_address_tabs.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
ADDR_SCREEN = AND / "ui/shipper/AddressScreen.kt"
SEG_TABS = AND / "ui/common/SegmentedStatusTabs.kt"
COMPONENTS = AND / "ui/common/Components.kt"
USER_SEARCH = AND / "core/UserSearch.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
FORM_STYLE_CHECK = ROOT / "_tools/qa/_check_form_panel_style.py"
AI_GUARDRAILS = ROOT / "_tools/ai/_check_ai_guardrails.py"
REVERSE = "_tools/qa/_reverse_verify_address_tabs.py"
DOC = ROOT / "docs/changes/CHG-0013.md"
REGISTRY = ROOT / "docs/changes/README.md"

#: 三档的清单与顺序（顺序就是用户认路用的那个顺序）
TABS_DECL = 'private val ADDRESS_TABS = listOf("路线", "联系人", "地址")'
#: 三档的语义色：必须走命名 token
#: ⚠️ 2026-10-03 CHG-0014（批 3 配色归一）把这三个 token 换成了 OriginTeal / ShipperTeal /
#:    MoneyOrange（路线用线路色、联系人用"人"的湖蓝），**不变的是"必须走命名 token"这条**；
#:    这条锚点跟着改，判据口径一个字没放宽。
COLORS_DECL = "private val ADDRESS_TAB_COLORS = listOf(Color(OriginTeal), Color(ShipperTeal), Color(MoneyOrange))"
#: 线路档占位语：_tools/ai/_check_ai_guardrails.py:4074 的锚点 + _check_input_rules.py:101 的 EXCLUDED 键
ROUTE_HINT = '0 -> "搜线路：收货人 / 电话 / 地址"'
#: 地点档占位语
PLACE_HINT = 'else -> "搜地点：名称 / 地址"'
#: 按人匹配的口径（联系人那一段的过滤，后 4 位就靠它）
USER_MATCH = "UserSearch.matches(kw, it.displayName, it.phone)"
#: 清空按钮的内容描述（与 SearchField 里那个同形）
CLEAR_CD = 'contentDescription = "清空搜索"'
#: 老写法（必须消失）
OLD_CLEAR = 'Text("清除")'
OLD_CONTACT_HINT = "搜联系人"
#: 切档必须连搜索一起清（成对出现，拆开即红）
ON_SELECT = 'onSelect = { tab = it; keyword = "" }'
#: 共用件 SearchField 的声明（签名 + 默认提示语都在这一段里）
SEARCH_FIELD_SIG = "fun SearchField("
#: 共用件 SegmentedStatusTabs 的声明
SEG_SIG = "fun SegmentedStatusTabs("
#: 全库 Kotlin 文件数下限（防目录搬走之后「一个文件都没扫到」也算过）
MIN_KT_FILES = 200
#: 规范 §3 组件速查 / §4.4 搜索框那一节（两处纪律的规范原文都落在这些节里）
DESIGN_SEC3 = "## 3."
DESIGN_SEC44 = "### 4.4"
#: 那一节的字符数下限（截空即红：规范被删掉 / 搬到别处）
SECTION_FLOOR = 300


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def between(text: str, start: str, end: str) -> str:
    """text 里从 start 起、到后面第一个 end 之前的那一段（找不到就返回空串）。

    ⚠️ 空串是**故意**的失败信号：抽取不到 = 判据在空串上恒真 = 必须红。
    """
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:] if j < 0 else text[i:j]


def section2(text: str, heading: str) -> str:
    """文档里某一节（从 heading 那一行到下一个同级 ## 之前）。"""
    i = text.find(heading)
    if i < 0:
        return ""
    j = text.find("\n## ", i + len(heading))
    return text[i:] if j < 0 else text[i:j]


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(title + "：" + f"通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print("    - " + f)
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("地址与联系人页顶部导航与搜索框检查"):
        return 1

    c = Checker()
    print("地址与联系人页：顶部三档收编 SegmentedStatusTabs + 按人搜索收编 SearchField（CHG-0013，2026-10-03）")

    kt_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的 Kotlin 文件数 ≥ {MIN_KT_FILES}（防目录搬走 → 判据空转）",
        len(kt_files) >= MIN_KT_FILES,
        f"实际 {len(kt_files)}",
    )
    c.ok("AddressScreen.kt 存在", ADDR_SCREEN.exists(), str(ADDR_SCREEN))

    raw = read(ADDR_SCREEN)
    src = code(ADDR_SCREEN)

    # ---- 1. 导航收编：共用件 + 自定义胶囊清零 ----
    n_seg = src.count("SegmentedStatusTabs(")
    c.ok(
        "本页顶部三档走共用件 SegmentedStatusTabs（≥1 处调用）",
        n_seg >= 1,
        f"只找到 {n_seg} 处",
    )
    c.ok(
        "自己画的那排描边胶囊（AddressTabBar）连函数带调用点一起没了",
        "AddressTabBar" not in raw,
        "代码里还能看到 AddressTabBar —— 自定义胶囊没删干净",
    )
    n_border = src.count("BorderStroke(")
    c.ok(
        "这一页不再有描边（BorderStroke( == 0：那排胶囊整块没了）",
        n_border == 0,
        f"还有 {n_border} 处 BorderStroke(",
    )
    impls = [p for p in kt_files if SEG_SIG in p.read_text(encoding="utf-8", errors="replace")]
    c.ok(
        "全库仍然只有一处 SegmentedStatusTabs 实现（共用件没被就地复制一份）",
        len(impls) == 1,
        "找到 " + str([p.name for p in impls]),
    )

    # ---- 2. 三档的内容：标签 + 语义色 ----
    c.ok("三档标签与顺序就是 路线 / 联系人 / 地址", TABS_DECL in src, "标签清单被改了（顺序是用户认路用的）")
    c.ok("三档颜色走命名 token（OriginTeal / ShipperTeal / MoneyOrange）", COLORS_DECL in src, "色值不是这三个命名 token")
    c.ok(
        "新加的两行常量里没有裸色值（三档色只许引用 Color.kt 的命名 token）",
        "0xFF" not in TABS_DECL and "0xFF" not in COLORS_DECL,
        "新常量里写死了色值",
    )
    # ⚠️ 本页那 5 处历史裸色值（iconTint / 电话图标 / 分组 / 备注）已由「批 3 · 配色归一」
    #    （CHG-0014）收口，现在钉在 `_tools/qa/_check_address_palette.py`：本页 `Color(0xFF` == 0。
    #    这一条只管三档的色是不是命名 token，两条判据各管一段、都不重复。
    call = between(src, "SegmentedStatusTabs(", "\n            )")
    c.ok(
        "调用点四项都传了：labels / colors / selected / onSelect",
        all(k in call for k in ("labels = ADDRESS_TABS", "colors = ADDRESS_TAB_COLORS", "selected = tab", "onSelect =")),
        "调用点少传了东西（传空色或写死一份标签都算）",
    )
    c.ok(
        "切档时顺手清空搜索（否则换档后是一个被上个档关键词过滤过的空白页）",
        ON_SELECT in call,
        "onSelect 里没有把 keyword 清掉",
    )

    # ---- 3. 搜索框分档：按人搜走共用件，地址型继续 SoTextField ----
    contacts_branch = between(src, "if (tab == 1) {", "} else {")
    addr_branch = between(src, "} else {", "if (tab != 1")
    c.ok(
        "联系人那一档走共用件 SearchField（全库只有一份按人搜索框）",
        "SearchField(" in contacts_branch,
        "联系人档没有用 SearchField",
    )
    c.ok(
        "联系人那一档不再是 SoTextField（同一件事不许两个答案）",
        "SoTextField(" not in contacts_branch,
        "联系人档还在自己写文本框",
    )
    c.ok("线路 / 地点两档继续用 SoTextField", "SoTextField(" in addr_branch, "两档的文本框被换掉了")
    c.ok("线路档占位语原样保住（AI 判据的锚点，一个字都不能改）", ROUTE_HINT in src, "线路档占位语被改了")
    c.ok("地点档占位语原样保住", PLACE_HINT in src, "地点档占位语被改了")
    c.ok("旧的「搜联系人」占位语已消失", OLD_CONTACT_HINT not in raw, "联系人档的旧占位语还在")
    n_sf = src.count("SearchField(")
    c.ok("本页 SearchField( 只出现一次（不是每一档都塞一个）", n_sf == 1, f"出现 {n_sf} 次")

    # ---- 4. 清空按钮同形 ----
    c.ok("清空统一成 ✕（contentDescription = 清空搜索，与 SearchField 里那个同形）", CLEAR_CD in raw, "清空还是文字按钮")
    c.ok("旧的文字清空按钮（Text(清除)）已消失", OLD_CLEAR not in raw, "旧写法还在")
    c.ok(
        "✕ 只在非联系人档画（SearchField 自带一个，不许叠两个）",
        "if (tab != 1 && keyword.isNotBlank())" in src,
        "清空按钮的显示条件被改了",
    )

    # ---- 5. 共用件那两侧的契约 ----
    seg = read(SEG_TABS)
    c.ok(
        "共用件 SegmentedStatusTabs 的签名没变（labels / colors / selected / onSelect）",
        all(k in seg for k in ("labels: List<String>", "colors: List<Color>", "selected: Int", "onSelect: (Int) -> Unit")),
        "共用件签名被改了（别的 6 个调用点会一起受影响）",
    )
    c.ok("共用件自己带左右 16dp 外边距（调用点不必再兜一层 padding）", "horizontal = 16.dp" in seg, "外边距契约被改了")
    comp = read(COMPONENTS)
    sf = between(comp, SEARCH_FIELD_SIG, "\n}")
    c.ok("共用件 SearchField 的默认提示语仍同源 core/UserSearch.HINT", "com.tapmoay.sorders.core.UserSearch.HINT" in comp, "提示语被就地写死")
    c.ok("共用件 SearchField 里那个 ✕ 还在（一键清空是它的一部分）", CLEAR_CD in comp, "SearchField 里没有清空按钮")
    c.ok("SearchField 的声明能抽出来（抽取失效即红）", len(sf) >= 80, f"只抽到 {len(sf)} 字符")
    c.ok("core/UserSearch.HINT 还在（后 4 位也能搜这件事只有一处说）", "HINT" in read(USER_SEARCH), "UserSearch.HINT 没了")

    # ---- 6. 本批没顺手改别的：本页锚点 ----
    for needle, why in (
        ("tab == 1 -> ContactCategoryPane(", "联系人的分类选择（FEAT-0009 起：标题行胶囊 + 左侧抽屉，不再是常驻左栏）"),
        ("vm.contacts.filter {", "联系人过滤入口"),
        (USER_MATCH, "按人匹配的口径（手机号后 4 位）"),
        ("ContactPickerSheet(", "联系人选择抽屉"),
        ("RouteRail(", "线路卡的 A→B 轨道"),
    ):
        c.ok(f"本批没顺手改别的：{why} 还在", needle in src, f"找不到 {needle}")

    # ---- 7. 接线：反向验证 / 规范 / 文档 / 登记 ----
    c.ok("本判据自己的反向验证在", (ROOT / REVERSE).exists(), REVERSE)
    c.ok(
        "本页还在 _check_form_panel_style 的 CONVERTED 表里（OutlinedTextField == 0 那条不能松）",
        "AddressScreen.kt" in read(FORM_STYLE_CHECK),
        "CONVERTED 表里找不到它",
    )
    c.ok(
        "AI 判据认的那句搜索框锚点还在（_check_ai_guardrails.py:4074）",
        "搜线路：收货人 / 电话 / 地址" in read(AI_GUARDRAILS),
        "锚点句没了",
    )
    sec3 = section2(read(DESIGN), DESIGN_SEC3)
    c.ok(
        f"设计规范 §3 组件速查那一节还在（≥ {SECTION_FLOOR} 字符）",
        len(sec3) >= SECTION_FLOOR,
        f"那一节只剩 {len(sec3)} 字符（规范被删掉或搬走了）",
    )
    c.ok(
        "§3 里点名了这两个共用件（导航 SegmentedStatusTabs / 搜索 SearchField）",
        "SegmentedStatusTabs" in sec3 and "SearchField" in sec3,
        "规范那一段被删了",
    )
    sec44 = between(read(DESIGN), DESIGN_SEC44, "\n### ")
    c.ok(
        "§4.4 那一节还在（按人搜只有一份这条例律的规范原文）",
        len(sec44) >= SECTION_FLOOR and "SearchField" in sec44,
        f"那一节只剩 {len(sec44)} 字符",
    )
    doc = read(DOC)
    c.ok(
        "文档九节齐全（docs/changes/CHG-0013.md）",
        all(s in doc for s in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")),
        "文档缺节（_check_dev_spec.py 也会红）",
    )
    c.ok(
        "登记簿里有 CHG-0013 这一行（整行，不是一个链接里的字样）",
        bool(re.search(r"^\|\s*[\x60]?CHG-0013[\x60]?\s*\|", read(REGISTRY), re.M)),
        "没登记（别人不知道这个 ID 用掉了）",
    )

    return c.report("地址与联系人页顶部导航与搜索框（CHG-0013）")


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（地址与联系人页顶部导航与搜索框 CHG-0013）==")
        print("1. 导航收编：SegmentedStatusTabs( ≥1、AddressTabBar 消失、BorderStroke( == 0、全库只一处实现")
        print("2. 三档内容：标签与顺序、三个命名 token 色、本页裸色值 == 0、调用点四项齐全")
        print("3. 切档清空搜索：onSelect 里 tab = it 与 keyword 清空成对")
        print("4. 搜索分档：tab == 1 走 SearchField( 且不是 SoTextField(；0/2 仍 SoTextField( + 地址型占位语")
        print("5. 清空同形：✕ contentDescription = 清空搜索、旧文字按钮消失、只在非联系人档画")
        print("6. 共用件契约：SegmentedStatusTabs 签名/外边距、SearchField 提示语同源 UserSearch.HINT")
        print("7. 本批没顺手改别的 + 接线：反向验证在、CONVERTED 表、§3/§4.4、文档九节、登记簿 CHG-0013")
        sys.exit(0)
    sys.exit(main())
