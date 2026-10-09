# -*- coding: utf-8 -*-
"""红线：**地址与联系人页的配色与常驻文案** —— 一个概念只许有一个色、一句常驻话只许站得住 8 个字（CHG-0014，2026-10-03）。

## 这一批在治什么
用户反复要求「前端页面要重做按照我们的设计规范进行写」。只读审计（_tmp/ui_audit_address.md）在这一页上
抓到两类毛病，都不是功能问题，都是**同一件事有两个答案**：

* 配色（审计第 41 / 42 / 55 / 56 行）：同一条线路的「起点 / 终点」，卡片轨道用 RouteRail 的私有色
  OriginTeal(#00BCD4) / DestOrange(#F5A623)，表单分组却用 InventoryTeal(#00A8A8) / MoneyOrange(#FF9500)；
  「电话」在三处写死 Color(0xFF567A5F)，别处又用 MgrGreen；「人」的图标一处湖蓝一处青绿；
  地点抽屉的「分组」借了商品管理的紫、备注借了订单状态「已撤销」的灰 —— 全是**裸色值**。
* 文案（审计第 48 行）：常驻标题「常用线路（联系人+地点）」12 个字，比规范 §4.10 的上限（7~8 字）多一半；
  ImageStrip 里那句说明是裸 Text（该走 ui/common/Hints.kt::Hint，用户关掉提示就该跟着消失）。

## 为什么必须有机器的判据
颜色纪律只存在于 **tint 实参**里：Color(0xFF567A5F) 与 Color(MgrGreen) 的**类型完全相同**，
编译、渲染、点击全都没问题 —— 破法是**静默**的，页面看上去「就是有点花」，谁也说不出哪一行不对。
文案同理：多写四个字、把 Hint 退回 Text，没有任何一处会报错。而且这一页的第二个答案会自我复制：
下一个人照着抄，「电话就写 00B578」就成了惯例，用户就得在每一页重新认一次颜色。

判据分六层：
1. **裸色值清零**：本页与 RouteRail.kt 里 Color(0xFF 必须 == 0（那些值只能在 ui/theme/Color.kt 里出现一次）；
2. **一个概念一个色**：起点 = OriginTeal（1 个分组 tint + 3 处行 tint，那一支里不许再冒别的橙 / 库存青）、
   终点 = DestOrange、电话 = MgrGreen（4 处，不多不少）、人 = ShipperTeal、
   「分组」= ShipperTeal（结构类字段不借商品紫）、「备注」= colorScheme.outline（中性、跟随暗色）；
   地点组仍然是 MoneyOrange（**本批没顺手改别的**）；
3. **定义只有一份**：Color.kt 里 val OriginTeal / val DestOrange 各一次，全库再没有第二处
   （RouteRail.kt 改成 import，不许再自带 private val）；
4. **顶部三档**：三档色走命名 token（OriginTeal / ShipperTeal / MoneyOrange）；
5. **文案**：常驻标题压到 ≤ 8 字（「常用线路」/「起点（可选）」），说明句走 Hint(hint 而不是 Text(hint，
   而抽屉里那句带字面量的 Hint 仍在（反向验证注入① 按全库第一处 Hint( 定位，它必须还是那一处）；
6. **规范同步 + 接线**：规范 §2 里有「线路语义色」这一节并点名两个 token；上一批的判据
   （_check_address_tabs.py 的三档色常量、_reverse_verify_form_panel.py 的起点那一行锚点）同批改过；
   反向验证在、文档九节、登记簿有 CHG-0014。

⛔ 本页一个字都不能动的两处（动了别的判据会红、也伤真实功能）：
线路档占位语「搜线路：收货人 / 电话 / 地址」（_check_ai_guardrails.py:4074 的锚点、_check_input_rules.py:101 的 EXCLUDED 键）
与 UserSearch.matches(kw, it.displayName, it.phone)（按人匹配的口径，手机号后 4 位就靠它）。

R4-BOUNDARY-JUSTIFICATION: 这一条**没法用边界消除** —— 「同一个概念该用哪个色」只存在于 tint 实参里，
而 Color(0xFF567A5F) 与 Color(MgrGreen) 在类型系统里是同一个类型：编译器、渲染器、无障碍树都看不出区别，
破法因此是静默的（页面照常工作，只是同一个「电话」在两处是两种绿）。类型层也没法表达
「这两个 token 只许给起点 / 终点用」，Kotlin 不禁止任何人在任何地方再写一遍字面量。
所以只能靠一条判据把「本页的每个概念 ↔ ui/theme/Color.kt 里唯一那份定义」对起来，
并在反向验证里把「电话裸值回潮 / 起点回 InventoryTeal / 终点回 MoneyOrange / 人回青绿 /
RouteRail 又写私有 val / 三档色写死 / 两个标题回潮 / Hint 退回 Text / 分组回紫 / 备注回灰」这一批真跑一遍。

用法：python _tools/qa/_check_address_palette.py
     python _tools/qa/_check_address_palette.py --list
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
RAIL = AND / "ui/common/RouteRail.kt"
COLOR_KT = AND / "ui/theme/Color.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = "_tools/qa/_reverse_verify_address_palette.py"
REV_FORM_PANEL = ROOT / "_tools/qa/_reverse_verify_form_panel.py"
TABS_CHECK = ROOT / "_tools/qa/_check_address_tabs.py"
DOC = ROOT / "docs/changes/CHG-0014.md"
REGISTRY = ROOT / "docs/changes/README.md"

#: 裸色值（0xFF 字面量）—— 本页与 RouteRail 里都不许出现
RAW_COLOR = "Color(0xFF"
#: 起点 / 终点两个公有 token（定义在 ui/theme/Color.kt）
#: ⚠️ 期望值随 CHG-0101（台账 L-64）整套换色而变，但这条判据要看的性质没变：
#:    两个色仍然只在这里定义一次，这一页也没有绕开 token 自己写死色值。
#:    换色时连同这两个期望一起改（改的是"值是多少"，不是"要不要管"）。
#: ⛔ 两行的 `L` 后缀**不一致**（`Color.kt` 里一个带一个不带，历史遗留），
#:    所以 `L?`；写死任一种都会让另一行永远对不上（这条判据就是这么红过一次的）。
#:    也**不能**用字面量 `in`：后面是"对齐空格 + 行尾注释"，
#:    `strip_comments()` 只吃掉注释、留下空格，字面量永远差那几个空格。
ORIGIN_DECL = re.compile(r"^val OriginTeal = 0xFF6BA6AEL?\b", re.M)
DEST_DECL = re.compile(r"^val DestOrange = 0xFFC9A15EL?\b", re.M)
#: 顶部三档的三个语义色（顺序 = 路线 / 联系人 / 地址）
TAB_COLORS = "listOf(Color(OriginTeal), Color(ShipperTeal), Color(MoneyOrange))"
#: 线路卡上那个电话图标（整行钉住：色 + 尺寸 + 无障碍文案）
PHONE_ICON_LINE = (
    'Icon(Icons.Default.Phone, contentDescription = "电话", modifier = Modifier.size(11.dp), tint = Color(MgrGreen))'
)
#: 「新增联系人」那个图标（人 = 湖蓝）
PERSON_ADD_LINE = 'Icon(Icons.Default.PersonAddAlt, null, Modifier.size(16.dp), tint = Color(ShipperTeal))'
#: 抽屉里那句带字面量的 Hint（反向验证注入① 按第一处 Hint( 定位，它必须还是那一处）
HINT_LITERAL = "顺序到地址库左栏的「管理分组」里排。"
#: 起点分组那一行（判据用切片定位，锚点就是它）
ORIGIN_GROUP = 'title = "起点（可选）"'
END_GROUP = 'title = "终点（必填）"'
PLACE_GROUP = 'title = "地点"'
#: 常驻文案上限（规范 §4.10：常驻的数 / 标签 / 按钮 / 行内说明 ≤ 8 字）
TEXT_MAX = 8
#: 切片下限（抽不到 = 判据在空串上恒真 = 必须红）
SLICE_FLOOR = 100
SECTION_FLOOR = 300
MIN_KT_FILES = 200


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
    if refuse_if_injecting("地址与联系人页配色与常驻文案检查"):
        return 1

    c = Checker()
    print("地址与联系人页：一个概念一个色 + 常驻文案压到 8 字内（CHG-0014，2026-10-03）")

    kt_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的 Kotlin 文件数 ≥ {MIN_KT_FILES}（防目录搬走 → 判据空转）",
        len(kt_files) >= MIN_KT_FILES,
        f"实际 {len(kt_files)}",
    )
    c.ok("AddressScreen.kt 存在", ADDR_SCREEN.exists(), str(ADDR_SCREEN))
    c.ok("RouteRail.kt 存在（线路卡上那条 A→B 轨道）", RAIL.exists(), str(RAIL))
    c.ok("Color.kt 存在（全部语义色的唯一定义处）", COLOR_KT.exists(), str(COLOR_KT))

    raw = read(ADDR_SCREEN)
    src = code(ADDR_SCREEN)

    # ---- 1. 裸色值清零 ----
    n_raw = src.count(RAW_COLOR)
    c.ok(
        "本页 Color(0xFF 字面量 == 0（全部走命名 token / colorScheme）",
        RAW_COLOR not in src,
        f"还有 {n_raw} 处裸色值",
    )
    rail_src = code(RAIL)
    n_rail_raw = rail_src.count(RAW_COLOR)
    c.ok(
        "RouteRail.kt 里 Color(0xFF 也 == 0（起点 / 终点两个色已经提成公有 token）",
        RAW_COLOR not in rail_src,
        f"还有 {n_rail_raw} 处裸色值",
    )
    n_tint = src.count("tint = Color(") + src.count("iconTint = Color(")
    c.ok(
        "本页 tint 实参 ≥ 25 处（防抽取失败 → 下面的「一个概念一个色」在空表上恒真）",
        n_tint >= 25,
        f"实际 {n_tint} 处",
    )

    # ---- 2. 一个概念一个色：起点 / 终点 ----
    start_slice = between(src, ORIGIN_GROUP, END_GROUP)
    c.ok(
        f"起点组切片抽得到（≥ {SLICE_FLOOR} 字符）",
        len(start_slice) >= SLICE_FLOOR,
        f"只抽到 {len(start_slice)} 字符",
    )
    c.ok(
        "起点组的分组 tint 就是 Color(OriginTeal)（和卡片上那个圆点同一个色）",
        "tint = Color(OriginTeal)" in start_slice,
        "起点组没用 OriginTeal",
    )
    n_origin_rows = start_slice.count("iconTint = Color(OriginTeal)")
    c.ok(
        "起点组里 3 处行 tint 全是 Color(OriginTeal)",
        n_origin_rows == 3,
        f"实际 {n_origin_rows} 处",
    )
    c.ok(
        "起点组里没有别的橙 / 库存青（一个概念一个色）",
        ("MoneyOrange" not in start_slice) and ("InventoryTeal" not in start_slice),
        "起点组混进了别的语义色",
    )
    end_slice = between(src, END_GROUP, PLACE_GROUP)
    c.ok(
        f"终点那一支切片抽得到（≥ {SLICE_FLOOR} 字符）",
        len(end_slice) >= SLICE_FLOOR,
        f"只抽到 {len(end_slice)} 字符",
    )
    c.ok(
        "终点组的分组 tint 就是 Color(DestOrange)（和卡片上那个定位针同一个色）",
        "tint = Color(DestOrange)" in end_slice,
        "终点组没用 DestOrange",
    )
    n_dest_rows = end_slice.count("iconTint = Color(DestOrange)")
    c.ok(
        "终点组里 3 处行 tint 全是 Color(DestOrange)",
        n_dest_rows == 3,
        f"实际 {n_dest_rows} 处",
    )
    c.ok(
        "终点组里不再混着 MoneyOrange / 库存青",
        ("iconTint = Color(MoneyOrange)" not in end_slice) and ("InventoryTeal" not in end_slice),
        "终点组混进了别的语义色",
    )
    c.ok(
        "地点组仍然是 MoneyOrange（地点 = 橙，是另一个概念，本批没顺手改）",
        'FormGroup(icon = Icons.Default.Place, title = "地点", tint = Color(MoneyOrange)) {' in raw,
        "地点组的 tint 被顺手改了",
    )

    # ---- 3. 一个概念一个色：电话 / 人 / 分组 / 备注 ----
    n_green = src.count("Color(MgrGreen)")
    c.ok(
        "本页 Color(MgrGreen) 恰好 4 处（收货人电话 / 联系人电话 / 分类型电话 / 线路卡电话图标）",
        n_green == 4,
        f"实际 {n_green} 处",
    )
    c.ok(
        "线路卡上那个电话图标整行都是 MgrGreen（色 + 尺寸 + 无障碍文案）",
        PHONE_ICON_LINE in raw,
        "那一行被改了",
    )
    n_green_rows = src.count("iconTint = Color(MgrGreen)")
    c.ok(
        "三处「电话」表单行的 tint 也是 MgrGreen（绿只留给电话）",
        n_green_rows == 3,
        f"实际 {n_green_rows} 处",
    )
    c.ok(
        "「新增联系人」的图标是湖蓝（人 = 湖蓝，绿留给电话）",
        PERSON_ADD_LINE in raw,
        "那个图标又变回别的色了",
    )
    c.ok(
        "联系人分组的语义色是湖蓝（本页模块色 + 人 = 湖蓝）",
        'FormGroup(icon = Icons.Default.Person, title = "联系人", tint = Color(ShipperTeal)) {' in raw,
        "联系人分组的语义色变了",
    )
    cat_slice = between(src, 'label = "分组"', "onClick = { catExpanded = true }")
    c.ok(
        f"地点「分组」那一行切片抽得到（≥ {SLICE_FLOOR} 字符）",
        len(cat_slice) >= SLICE_FLOOR,
        f"只抽到 {len(cat_slice)} 字符",
    )
    c.ok(
        "地点「分组」的图标是湖蓝（结构类字段不借商品管理的紫）",
        "iconTint = Color(ShipperTeal)" in cat_slice,
        "分组那一行的 tint 不是湖蓝",
    )
    c.ok(
        "本页不再出现商品紫（Color(0xFF8A7BB0) / ProductPurple）",
        ("8455E6" not in src) and ("ProductPurple" not in src),
        "商品紫又回来了",
    )
    note_slice = between(src, "icon = Icons.Default.Notes", "FormErrorLine(vm.formError)")
    c.ok(
        f"地点「备注」那一行切片抽得到（≥ {SLICE_FLOOR} 字符）",
        len(note_slice) >= SLICE_FLOOR,
        f"只抽到 {len(note_slice)} 字符",
    )
    c.ok(
        "地点「备注」走中性色 colorScheme.outline（跟随暗色，不借「已撤销」那个灰）",
        "iconTint = MaterialTheme.colorScheme.outline" in note_slice,
        "备注那一行的 tint 变了",
    )
    c.ok(
        "本页不再写死「已撤销」那个灰（Color(0xFF8A8A8E)）",
        "8A8A8E" not in src,
        "那个灰又写死回来了",
    )

    # ---- 4. 定义只有一份 ----
    color_src = code(COLOR_KT)
    n_orig = color_src.count("val OriginTeal")
    n_dest = color_src.count("val DestOrange")
    c.ok("Color.kt 里 val OriginTeal 恰好定义一次", n_orig == 1, f"实际 {n_orig} 处")
    c.ok("Color.kt 里 val DestOrange 恰好定义一次", n_dest == 1, f"实际 {n_dest} 处")
    c.ok(
        "两个色值没被顺手改（起点 #6BA6AE / 终点 #C9A15E，CHG-0101 换的那套）",
        (ORIGIN_DECL.search(color_src) is not None) and (DEST_DECL.search(color_src) is not None),
        "色值变了",
    )
    orig_files = [p for p in kt_files if "val OriginTeal" in p.read_text(encoding="utf-8", errors="replace")]
    dest_files = [p for p in kt_files if "val DestOrange" in p.read_text(encoding="utf-8", errors="replace")]
    c.ok(
        "全库只有 Color.kt 定义 OriginTeal（没有第二处私有副本）",
        [p.resolve() for p in orig_files] == [COLOR_KT.resolve()],
        "找到 " + str([p.name for p in orig_files]),
    )
    c.ok(
        "全库只有 Color.kt 定义 DestOrange（没有第二处私有副本）",
        [p.resolve() for p in dest_files] == [COLOR_KT.resolve()],
        "找到 " + str([p.name for p in dest_files]),
    )
    c.ok(
        "RouteRail.kt 改成 import 这两个 token（不许再自带 private val）",
        ("import com.tapmoay.sorders.ui.theme.OriginTeal" in rail_src)
        and ("import com.tapmoay.sorders.ui.theme.DestOrange" in rail_src)
        and ("private val OriginTeal" not in rail_src)
        and ("private val DestOrange" not in rail_src),
        "RouteRail.kt 里还留着私有定义 / 没 import",
    )
    c.ok(
        "RouteRail.kt 的轨道两个 tint 接在 token 上（Color(OriginTeal) / Color(DestOrange)）",
        ("Color(OriginTeal)" in rail_src) and ("Color(DestOrange)" in rail_src),
        "轨道那两个色没接到 token 上",
    )

    # ---- 5. 顶部三档 + 常驻文案 ----
    c.ok(
        "顶部三档的三个色走命名 token（OriginTeal / ShipperTeal / MoneyOrange，顺序 = 路线 / 联系人 / 地址）",
        TAB_COLORS in src,
        "三档色变了",
    )
    c.ok(
        f"常驻标题压到 {TEXT_MAX} 字内（Text(\"常用线路\",）",
        'Text("常用线路",' in src,
        "4 字标题不在",
    )
    c.ok(
        "那条 12 字标题（常用线路（联系人+地点））已经没了",
        "常用线路（联系人+地点）" not in raw,
        "旧标题又回来了",
    )
    c.ok(
        f"起点分组标题压到 {TEXT_MAX} 字内（起点（可选），旧的是 11 字）",
        ORIGIN_GROUP in src and ("起点（可选，从这出发）" not in raw),
        "起点分组标题没压 / 旧标题又回来了",
    )
    c.ok(
        "说明句走 Hint(hint 而不是 Text(hint（ImageStrip 那句说明跟着提示开关显隐）",
        ("Text(hint," not in src) and ("Hint(hint," in src),
        "ImageStrip 那句说明又变回裸 Text",
    )
    c.ok(
        "抽屉里那句带字面量的 Hint 仍在（反向验证注入① 按第一处 Hint( 定位）",
        HINT_LITERAL in raw,
        "那句话没了 —— 同批要更新 _reverse_verify_hints.py",
    )

    # ---- 6. 规范同步 + 接线 ----
    sec2 = section2(read(DESIGN), "## 2.")
    c.ok(
        f"规范 §2 语义色那一节还在（≥ {SECTION_FLOOR} 字符）",
        len(sec2) >= SECTION_FLOOR,
        f"那一节只剩 {len(sec2)} 字符",
    )
    c.ok(
        "规范 §2 里新增了「线路语义色」这一节并点名两个 token",
        ("OriginTeal" in sec2) and ("DestOrange" in sec2) and ("线路" in sec2),
        "规范没同步（下一个改色的人查不到口径）",
    )
    c.ok("反向验证脚本在（同名 _reverse_verify_address_palette.py）", (ROOT / REVERSE).exists(), REVERSE)
    c.ok(
        "上一批的判据同批改了锚点（_check_address_tabs.py 的三档色常量）",
        TAB_COLORS in read(TABS_CHECK),
        "跨批锚点没同步 → 上一批的判据会红",
    )
    # 那个脚本里 Kotlin 的双引号是**转义过**的（写成反斜杠 + 双引号），
    # 所以要先去掉反斜杠再比 —— 直接 grep 原文会假红（本判据第一版就栽在这一条）。
    rev_fp = read(REV_FORM_PANEL).replace(chr(92) + chr(34), chr(34))
    c.ok(
        "反向验证的表单锚点也同批改了（_reverse_verify_form_panel.py 的起点那一行）",
        'title = "起点（可选）", tint = Color(OriginTeal)' in rev_fp,
        "那个注入会 MISS（锚点还写着旧标题 / 旧色）",
    )
    doc = read(DOC)
    c.ok(
        "文档九节齐全（docs/changes/CHG-0014.md）",
        all(s in doc for s in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")),
        "文档缺节（_check_dev_spec.py 也会红）",
    )
    c.ok(
        "登记簿里有 CHG-0014 这一行（整行，不是一个链接里的字样）",
        re.search(r"^\|\s*[\x60]?CHG-0014[\x60]?\s*\|", read(REGISTRY), re.M) is not None,
        "没登记（别人不知道这个 ID 用掉了）",
    )

    return c.report("地址与联系人页配色与常驻文案（CHG-0014）")


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（地址与联系人页配色与常驻文案 CHG-0014）==")
        print("1. 裸色值清零：本页与 RouteRail.kt 里 Color(0xFF == 0、tint 实参 ≥ 25 处")
        print("2. 一个概念一个色：起点 OriginTeal / 终点 DestOrange / 电话 MgrGreen / 人 ShipperTeal / 分组湖蓝 / 备注 outline")
        print("3. 地点组仍是 MoneyOrange（没顺手改）+ 商品紫与已撤销灰都不在")
        print("4. 定义只有一份：Color.kt 各一次、全库无第二处、RouteRail 改成 import")
        print("5. 文案：常驻标题 ≤ 8 字、旧 12 字与旧 11 字标题消失、说明句走 Hint(hint")
        print("6. 规范 §2 同步 + 跨批锚点同批改过 + 反向验证在 + 文档九节 + 登记簿有 CHG-0014")
        sys.exit(0)
    sys.exit(main())
