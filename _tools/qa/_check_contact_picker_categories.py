# -*- coding: utf-8 -*-
"""选人弹层的「左分类 + 右列表 + 可搜」（CHG-0128）—— 结构判据。

## 这一单钉的是什么
用户 2026-10-15 口述（逐字）：
> 「像**选地点库那样**（左分类、右对应项）」

动机（同一段口述）：
> 「联系人**一多起来**…找起来**非常麻烦**」

定语（同一段口述，决定了这次怎么做）：
> 「我们好像**已经有了对应的代码**啊，具体是哪些功能实现了这个我忘记了」

所以这一单**不新造一套**：分组算法照用商品/库存/预设单在用的
`ui/common/ProductPicker.kt::categoryTabsOf`，版式照抄同一页
`ui/shipper/OrderCreateScreen.kt::AddressPickerSheet`（用户点名的「选地点库」那一份）。
本判据把这两句话变成可执行的门。

## 为什么值得单独钉（坏法都是**不报错**的）
| 改坏的样子 | 屏幕上的表现 | 谁会先发现 |
|---|---|---|
| 左栏那一列没了 | 还是能用，只是「一多起来就非常麻烦」 | 用户（过几天） |
| 点了分类不筛（右栏还是全部） | 看着像筛了，其实没筛 | 几乎没人 |
| 「未分类」那一格被藏起来 | 少几个人，**不报错** | 用户以为这个人没存上 → 再建一个 → 同一个人两本账 |
| 分组算法在选人这里又写一遍 | 一开始一模一样，改一处就分叉 | 没人（两边都「能跑」） |
| 谁又抄了第二套挑联系人的弹层 | 在这页搜得到、在那页搜不到 | 用户 |

## R4-BOUNDARY-JUSTIFICATION:
本判据只钉**展示结构**与**唯一实现**这两类事实，都能从源码字面量直接算出来：
左边的分类栏在不在、分类键是不是分类名本身、右边是不是按选中的那一类筛、
搜索框是不是在左栏**上面**（搜索是「那个人在哪」，左栏是「分在哪一类」，两个维度）、
两份弹层是不是**同一份**分组算法。
⛔ 不钉的东西（钉了会变成假红、或者挡住正常维护）：
- **不钉行号 / 不钉像素尺寸**：`0.92f`、`112.dp` 这类数值只作为「长这样」的锚各出现一次，
  它们的美术调整属于别单（挤压基线归 `_check_adaptive_layout.py`）；
- **不钉右栏的行高与卡片样式**：那是 `ContactRow` / 名册卡片的事；
- **不代替** `_check_contact_picker_self.py`：「我自己」那一行、搜索占位语、
  `SelfContact.withSelf(` 全仓唯一这些规矩都在那份判据里，本判据**一条都不放宽**它们
  （本判据只**追加**：左栏、分类筛、未分类兜底、同一份分组算法、同一份弹层）；
- **不钉后端**：分类字段（`shipper_contacts.category` / `users.category`）与名册端点
  早已存在（FEAT-0007），本单一个后端字段都没加，所以这里也不看后端。

## 判据（清单全部自己算，不许手写文件列表）
0. 反空转：关键文件都在、两份弹层都读到了（字符数下限）、ANDROID 下 .kt 数量下限、单测条数下限；
1. **分组算法只有一份**：`fun <T> groupTabsOf(` / `fun <T> inGroup(` 全树各恰好 1 处定义且都在
   PersonGroups.kt；它转发 `categoryTabsOf(items.map(categoryOf))`（自己不复写一遍）；
   「全部」/「未分类」两个哨兵常量的唯一来源是 ProductPicker.kt（PersonGroups.kt 里一个 const 都不许有）；
2. **左分类栏**：两份弹层都有常驻 `MasterRail(`（键 = 分类名本身）、都在右列表**左边**、
   每一格都**不带条数**、**不是**抽屉（`ModalNavigationDrawer(` / `CategoryDrawerSheet(` 都不许有）、
   也不是地址页那种「标题行胶囊 + 抽屉」（`CategoryTriggerChip(` 不许有）；
3. **右列表 + 搜索框**：搜索框在左栏**上面**（源码顺序自算）、有词时右上有「清除」、
   右列表吃的是**筛过之后**的那一列（不是原始名册）；
4. **未分类兜底 + 交叉筛**：两份弹层都用 `groupTabsOf` 拿左栏（⇒ 没分类的人归「未分类」、
   永远排最后、名册外的老分类也出一格，三条都在那一份实现里）；右栏走 `inGroup`；
   选中项在名册变化时自愈回「全部」；切分类**不清空**搜索词；选中那一类是空时有专门文案；
5. **三处入口走同一份弹层**（自算清单）：定义全树**只有一处**；调用它的 main 源文件集合
   ＝ 派单/地址/订单编辑那三处（多一处、少一处都报错）；
   「同时含 `MasterRail(` 与联系人/账号 DTO」的文件集合**恰好**是那两份选人弹层
   （⇒ 谁再抄第二套，这里先红）；
6. **一色一功能**：联系人弹层用地址湖蓝 `ShipperTeal`、货主弹层用货主松绿 `InventoryTeal`，
   互不串色，且与 `ui/nav/Modules.kt` 里那两个模块自己的色一致；
7. **单测**：PersonGroupsTest.kt 在、`@Test` ≥ 6、含「与 categoryTabsOf 同源」那一条；
8. **文书**：docs/changes/CHG-0128.md 九节齐全且正文非空、引到用户原话、
   「未分类」兜底与两条取舍（不透传名册顺序）都写在纸面上；
9. **反验脚本自查**：注入条数 ≥ 5、四个关键字齐全、会打印「N/N 种破坏方式都被判据抓住了」。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
    配套：python _tools/qa/_reverse_verify_contact_picker_categories.py（7 种破坏方式全被抓）
用法：python _tools/qa/_check_contact_picker_categories.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
TESTDIR = ROOT / "android" / "app" / "src" / "test" / "java" / "com" / "tapmoay" / "sorders"
COMMON = ANDROID / "ui" / "common"

CONTACT_SHEET = COMMON / "ContactPickerSheet.kt"
SHIPPER_SHEET = COMMON / "ShipperPickerSheet.kt"
GROUPS = COMMON / "PersonGroups.kt"
PRODUCT = COMMON / "ProductPicker.kt"
MODULES = ANDROID / "ui" / "nav" / "Modules.kt"
ORDER_CREATE = ANDROID / "ui" / "shipper" / "OrderCreateScreen.kt"
ADDRESS = ANDROID / "ui" / "shipper" / "AddressScreen.kt"
ORDER_EDIT = ANDROID / "ui" / "order" / "OrderEditInline.kt"
TEST = TESTDIR / "ui" / "common" / "PersonGroupsTest.kt"
DOC = ROOT / "docs" / "changes" / "CHG-0128.md"
REVERSE = Path(__file__).resolve().parent / "_reverse_verify_contact_picker_categories.py"

REQUIRED = [CONTACT_SHEET, SHIPPER_SHEET, GROUPS, PRODUCT, MODULES,
            ORDER_CREATE, ADDRESS, ORDER_EDIT, TEST, DOC, REVERSE]

# 字符数下限：文件被换成空壳/被截断时先报错，而不是后面几条安静地过
FLOOR = {
    "ContactPickerSheet.kt": 8000,
    "ShipperPickerSheet.kt": 5000,
    "PersonGroups.kt": 900,
    "PersonGroupsTest.kt": 2000,
    "CHG-0128.md": 4000,
}
MIN_KT = 100           # ANDROID 下的 .kt 数量下限（现在远不止）
MIN_TESTS = 200        # 单测目录 @Test 条数下限（现在上千）
MIN_INJECTIONS = 5     # 反验至少 5 条注入

# 挑联系人的入口：全 App **就这几处**（自算清单与它比对，多一处少一处都要红）
PICKER_FILES = {
    "ui/common/ContactPickerSheet.kt",     # 定义处
    "ui/shipper/OrderCreateScreen.kt",     # 代理下单「收货人」
    "ui/shipper/AddressScreen.kt",         # 地址与联系人（线路收货人 / 地点绑定）
    "ui/order/OrderEditInline.kt",         # 订单详情里改收货人
}

C = Checker()


def ok(label: str, cond: bool, detail: str = "") -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def raw(path: Path) -> str:
    if not path.is_file():
        return ""
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def kt(path: Path) -> str:
    """去注释后的源码：判「这段代码里有没有」要用它（注释里写着这几个字不算数）。"""
    text = raw(path)
    return strip_comments(text) if text else ""


def rel(path: Path) -> str:
    """仓库内部的短路径：main 源集 = ui/...；单测 = test/...（清单里的写法）。"""
    for base, prefix in ((ANDROID, ""), (TESTDIR, "test/")):
        try:
            return prefix + path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.relative_to(ROOT).as_posix()


def main_kt_files() -> list[Path]:
    return sorted(ANDROID.rglob("*.kt"))


def finish() -> int:
    print("\n" + "=" * 60)
    total = C.n_ok + len(C.fails)
    if C.fails:
        print(f"❌ {len(C.fails)} 项不通过（通过 {C.n_ok} 项）：")
        for label, _detail in C.fails:
            print(f"   - {label}")
        print(f"_check_contact_picker_categories: {C.n_ok}/{total} 通过")
        return 1
    print(f"✅ 全部 {total} 项通过：选人弹层左分类 + 右列表 + 可搜（CHG-0128）")
    print(f"_check_contact_picker_categories: {C.n_ok}/{total} 通过")
    return 0


def main() -> int:
    # ---- 0. 反空转 ----
    section("0. 反空转")
    missing = [p for p in REQUIRED if not p.is_file()]
    ok("关键文件都在：" + "、".join(p.name for p in REQUIRED), not missing,
       "缺：" + "、".join(rel(p) for p in missing))
    if missing:
        print("\n❌ 关键文件缺失，后面的判据全部跳过（不许安静地绿）")
        return finish()

    texts = {p: raw(p) for p in REQUIRED}
    for name, floor in FLOOR.items():
        hit = [p for p in REQUIRED if p.name == name]
        if hit:
            n = len(texts[hit[0]])
            ok(f"{name} 读到了（{n} 字符，下限 {floor}）", n >= floor)

    kts = main_kt_files()
    ok(f"ANDROID 下扫到 {len(kts)} 个 .kt（下限 {MIN_KT}）", len(kts) >= MIN_KT)
    tests = sorted(TESTDIR.rglob("*.kt"))
    n_test = sum(raw(p).count("@Test") for p in tests)
    ok(f"单测目录扫到 {len(tests)} 个测试文件 / {n_test} 条 @Test（下限 {MIN_TESTS}）",
       n_test >= MIN_TESTS and len(tests) >= 20)

    contact = texts[CONTACT_SHEET]
    shipper = texts[SHIPPER_SHEET]
    contact_code = kt(CONTACT_SHEET)
    shipper_code = kt(SHIPPER_SHEET)
    groups_code = kt(GROUPS)

    # ---- 1. 分组算法只有一份 ----
    section("1. 分组算法只有一份（PersonGroups.kt 转发 categoryTabsOf）")
    src = {p: kt(p) for p in kts}
    def_tabs = [rel(p) for p in kts if "fun <T> groupTabsOf(" in src[p]]
    def_in = [rel(p) for p in kts if "fun <T> inGroup(" in src[p]]
    ok("groupTabsOf( 全树恰好 1 处定义，且在 ui/common/PersonGroups.kt",
       def_tabs == ["ui/common/PersonGroups.kt"], "实际：" + "、".join(def_tabs or ["（没有）"]))
    ok("inGroup( 全树恰好 1 处定义，且在 ui/common/PersonGroups.kt",
       def_in == ["ui/common/PersonGroups.kt"], "实际：" + "、".join(def_in or ["（没有）"]))
    ok("PersonGroups.kt 的分组是**转发**给商品那一份（categoryTabsOf(items.map(categoryOf))）",
       "categoryTabsOf(items.map(categoryOf))" in groups_code)
    ok("PersonGroups.kt 的筛选按 categoryNameOf(categoryOf(it)) == group（「未分类」也是按这一条比）",
       "if (group == ALL_CATEGORY) items else items.filter { categoryNameOf(categoryOf(it)) == group }" in groups_code)
    ok("PersonGroups.kt 里没有自己再分组一遍（无 ifBlank / 无 sortedByDescending / 无 linkedMapOf）",
       "ifBlank" not in groups_code and "sortedByDescending" not in groups_code
       and "linkedMapOf" not in groups_code)
    ok("PersonGroups.kt 里一个 const 都没有（「全部」/「未分类」不许在这里再定义一份）",
       "const val" not in groups_code)
    ok("「全部」/「未分类」的哨兵常量唯一来源是 ProductPicker.kt（internal const val，各自恰好 1 处）",
       src[PRODUCT].count("internal const val ALL_CATEGORY") == 1
       and src[PRODUCT].count("internal const val NO_CATEGORY") == 1
       and sum(src[p].count("internal const val ALL_CATEGORY") for p in kts) == 1
       and sum(src[p].count("internal const val NO_CATEGORY") for p in kts) == 1)

    # ---- 2. 左分类栏 ----
    section("2. 左分类栏（常驻 MasterRail，不是抽屉、不带条数）")
    for path, code, who in ((CONTACT_SHEET, contact_code, "联系人"), (SHIPPER_SHEET, shipper_code, "货主")):
        tag = f"{who}弹层"
        ok(f"{tag}：有左分类栏 MasterRail(", "MasterRail(" in code)
        ok(f"{tag}：左栏的键就是分类名本身（items = groups.map {{ RailItem(key = it, label = it) }}）",
           "items = groups.map { RailItem(key = it, label = it) }" in code)
        row_at = code.find("Row(Modifier.fillMaxWidth().weight(1f))")
        rail_at = code.find("MasterRail(")
        right_m = re.search(r"Column\(\s*Modifier\.weight\(1f\)\.fillMaxHeight", code)
        right_at = right_m.start() if right_m else -1
        ok(f"{tag}：左栏在右列表**左边**（同一个 Row 里先 rail 后右栏）",
           row_at >= 0 and rail_at > row_at and right_at > rail_at)
        ok(f"{tag}：左栏每一格都不带条数（RailItem 只有 key/label 两个实参）",
           code.count("RailItem(key = it, label = it)") == 1 and "contactCount" not in code
           and "categoryCount" not in code)
        ok(f"{tag}：不是「抽屉里再套一层」（没有 ModalNavigationDrawer(）",
           "ModalNavigationDrawer(" not in code)
        ok(f"{tag}：不是「标题行胶囊 + 抽屉」那一份（没有 CategoryTriggerChip(）",
           "CategoryTriggerChip(" not in code)
        ok(f"{tag}：也不是 CategoryDrawerSheet(（那是页面里半展开那一份）",
           "CategoryDrawerSheet(" not in code)
        ok(f"{tag}：左栏里没有「管理分组/管理分类」那种「去别处」的格子",
           'RailItem("manage"' not in code and "manageLabel" not in code)

    # ---- 3. 右列表 + 搜索框 ----
    section("3. 右列表 + 搜索框（搜索框在左栏上面、右列表吃筛过的那一列）")
    ok("联系人弹层：搜索占位语一字未改（搜索姓名或手机号）", '"搜索姓名或手机号"' in contact)
    ok("货主弹层：搜索走唯一实现（placeholder = UserSearch.HINT），不就地写一套",
       "placeholder = UserSearch.HINT" in shipper)
    for path, code, who in ((CONTACT_SHEET, contact_code, "联系人"), (SHIPPER_SHEET, shipper_code, "货主")):
        tag = f"{who}弹层"
        ok(f"{tag}：搜索框在左栏**上面**（源码顺序自算）",
           code.find("keyword.isNotBlank()") >= 0
           and code.find("keyword.isNotBlank()") < code.find("MasterRail("))
        ok(f"{tag}：有词时右上角有「清除」", 'Text("清除")' in code and "TextButton(" in code)
    ok("联系人弹层：右列表吃的是筛过的那一列（items(visible, key = { it.id })）",
       "items(visible, key = { it.id })" in contact_code)
    ok("货主弹层：右列表吃的是筛过的那一列（visibleTop.forEach + take(100)）",
       "visibleTop.forEach" in shipper_code and "val visibleTop = visible.take(100)" in shipper_code)

    # ---- 4. 未分类兜底 + 交叉筛 ----
    section("4. 未分类兜底 + 交叉筛（切分类不清空搜索词、选中项自愈）")
    for path, code, who in ((CONTACT_SHEET, contact_code, "联系人"), (SHIPPER_SHEET, shipper_code, "货主")):
        tag = f"{who}弹层"
        ok(f"{tag}：左栏由 groupTabsOf( 算（⇒「未分类」永远最后、名册外的老分类也出一格）",
           "groupTabsOf(" in code)
        ok(f"{tag}：右栏由 inGroup( 筛（⇒ 选中「全部」时一条都不少）", "inGroup(" in code)
        ok(f"{tag}：选中项在名册变化时自愈回「全部」（LaunchedEffect(groups) ...）",
           "LaunchedEffect(groups) { if (group !in groups) group = ALL_CATEGORY }" in code)
        after = code.split("onSelect")[1][:60] if "onSelect" in code else ""
        ok(f"{tag}：切分类**不清空**搜索词（onSelect = {{ group = it }}，不是顺手把 keyword 也清了）",
           "onSelect = { group = it }" in code and "keyword" not in after)
    ok("联系人弹层：选中那一类是空的时候有专门文案（「$group」里还没有人 / 没有匹配）",
       "「$group」里还没有人" in contact and "「$group」里没有匹配「$kw」的联系人" in contact)
    ok("货主弹层：同上（「」里还没有货主 / 没有匹配）",
       '"「" + group + "」里还没有货主。"' in shipper and '"没有匹配「" + kw + "」的货主。"' in shipper)
    ok("两份弹层都不在自己取数（弹层里没有 container / repo. 字样）",
       "container" not in contact_code and "repo." not in contact_code
       and "container" not in shipper_code and "repo." not in shipper_code)

    # ---- 5. 三处入口走同一份弹层 ----
    section("5. 三处入口走同一份弹层（清单自己算）")
    defined = [rel(p) for p in kts if "fun ContactPickerSheet(" in src[p]]
    ok("fun ContactPickerSheet( 全树恰好 1 处定义，且在 ui/common/ContactPickerSheet.kt",
       defined == ["ui/common/ContactPickerSheet.kt"], "实际：" + "、".join(defined or ["（没有）"]))
    callers = sorted(rel(p) for p in kts if "ContactPickerSheet(" in src[p])
    ok(f"挑联系人的入口就是那 {len(PICKER_FILES)} 处（派单/地址/订单编辑 + 定义处），一处不多一处不少",
       set(callers) == PICKER_FILES,
       "实际：" + "、".join(callers) + "；期望：" + "、".join(sorted(PICKER_FILES)))
    for p in (ORDER_CREATE, ADDRESS, ORDER_EDIT):
        body = kt(p)
        ok(f"{p.name} 仍然走同一份弹层，且把自己那一份「我自己」传进去",
           "ContactPickerSheet(" in body and "selfContact =" in body)
    rail_person = sorted(rel(p) for p in kts
                         if "MasterRail(" in src[p]
                         and ("ContactDto" in src[p] or "UserDto" in src[p]))
    ok("「同时有左栏 MasterRail( 与人名 DTO」的文件**恰好**是那两份选人弹层（谁再抄第二套，这里先红）",
       rail_person == ["ui/common/ContactPickerSheet.kt", "ui/common/ShipperPickerSheet.kt"],
       "实际：" + "、".join(rail_person))

    # ---- 6. 一色一功能 ----
    section("6. 一色一功能（联系人=地址湖蓝 / 货主=货主松绿）")
    ok("联系人弹层用 ShipperTeal（地址与联系人那一格的颜色）",
       "accent = Color(ShipperTeal)" in contact_code
       and "import com.tapmoay.sorders.ui.theme.ShipperTeal" in contact)
    ok("货主弹层用 InventoryTeal（货主管理那一格的颜色）",
       "accent = Color(InventoryTeal)" in shipper_code
       and "import com.tapmoay.sorders.ui.theme.InventoryTeal" in shipper)
    ok("两份弹层不串色（联系人弹层里没有 InventoryTeal，货主弹层里没有 ShipperTeal）",
       "InventoryTeal" not in contact_code and "ShipperTeal" not in shipper_code)
    modules = kt(MODULES)
    ok("ui/nav/Modules.kt：地址与联系人 = ShipperTeal、货主管理 = InventoryTeal（左栏取的就是这两个模块的色）",
       re.search(r'ModuleEntry\("地址与联系人".*?ShipperTeal', modules, re.S) is not None
       and re.search(r'ModuleEntry\("货主管理".*?InventoryTeal', modules, re.S) is not None)

    # ---- 7. 单测 ----
    section("7. 单测（分组是纯函数，单独测）")
    test = raw(TEST)
    ok("PersonGroupsTest.kt 在单测目录里（ui/common/）", TEST.is_file())
    n = test.count("@Test")
    ok(f"PersonGroupsTest.kt 有 {n} 条 @Test（下限 6）", n >= 6)
    for needle, why in (("groupTabsOf(", "测的是转发出去的那一份"),
                        ("inGroup(", "测的是「全部」不筛 / 按分类筛"),
                        ("NO_CATEGORY", "测的是「未分类」兜底"),
                        ("categoryTabsOf(", "测的是与商品那边同一份实现")):
        ok(f"PersonGroupsTest.kt {why}（含 {needle}）", needle in test)
    ok("PersonGroupsTest.kt 与实现同包（com.tapmoay.sorders.ui.common）",
       "package com.tapmoay.sorders.ui.common" in test)

    # ---- 8. 文书 ----
    section("8. 文书 docs/changes/CHG-0128.md（九节齐全 + 引到用户原话）")
    doc = texts[DOC]
    heads = ["## ① 六问", "## ② Must Change / Must Not Change",
             "## ③ Boundary（Core / Extension / Infrastructure / Presentation）",
             "## ④ Behavior Contract", "## ⑤ Data Contract",
             "## ⑥ CHG 专章", "## ⑦ 测试", "## ⑧ 证据", "## ⑨ 关闭"]
    for h in heads:
        i = doc.find(h)
        body = ""
        if i >= 0:
            j = doc.find("\n## ", i + len(h))
            body = doc[i + len(h): j if j >= 0 else len(doc)].strip()
        ok(f"文书有「{h}」且正文非空（{len(body)} 字符）", i >= 0 and len(body) >= 60)
    ok("文书里有子节 ### Before / ### After / ### Must Preserve / ### Blast Radius",
       all(s in doc for s in ("### Before", "### After", "### Must Preserve", "### Blast Radius")))
    doc_flat = doc.replace("**", "")
    ok("文书引到用户 2026-10-15 原话（像选地点库那样 / 联系人一多起来）",
       "像选地点库那样" in doc_flat and "联系人一多起来" in doc_flat)
    ok("文书里有「未分类」兜底那一条口径（不许藏）", "未分类" in doc and "不许藏" in doc)
    sec5 = doc[doc.find("## ⑤"): doc.find("## ⑥")] if "## ⑤" in doc and "## ⑥" in doc else ""
    ok("文书 ⑤ 写了「不适用：<理由>」（只写不适用不给理由＝红）", "不适用：" in sec5)
    ok("文书 ③ 结尾有核心改动声明行（核心改动：不适用（…理由…））", "核心改动：不适用（" in doc)
    ok("文书点了三件套的文件名（判据 / 反验 / 单测）",
       "_check_contact_picker_categories.py" in doc
       and "_reverse_verify_contact_picker_categories.py" in doc
       and "PersonGroupsTest" in doc)
    ok("文书如实写明取舍：没有透传名册顺序（categoryOrder）", "categoryOrder" in doc)

    # ---- 9. 反验脚本自查 ----
    section("9. 反验脚本自查（本判据必须有自己的注入式反验）")
    rev = texts[REVERSE]
    for kw in ("read_bytes", "write_bytes", "sha256", "anchor_preflight", "INJECTIONS"):
        ok(f"反验脚本里有 {kw}", kw in rev)
    block = rev[rev.find("INJECTIONS"):]
    end = block.find("\n]")
    if end >= 0:
        block = block[:end]
    n_inj = len(re.findall(r'^    \("', block, re.M))
    ok(f"反验脚本有 {n_inj} 条注入（下限 {MIN_INJECTIONS}）", n_inj >= MIN_INJECTIONS)
    ok("反验脚本会打印「N/N 种破坏方式都被判据抓住了」", "种破坏方式" in rev)

    return finish()


if __name__ == "__main__":
    raise SystemExit(main())
