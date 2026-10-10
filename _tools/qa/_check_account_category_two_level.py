#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_account_category_two_level.py —— 账号分类的**两级**（CHG-0112）＋ 默认六类播种的静态判据。

## 这一单做了什么（用户 2026-10-11 原话）

> 「本来是有分类的，我们这个分类直接拉取关于那个我们对应已经做好的分类，其实我们分类也就这些：
>  派单员、货主、批发商、大车司机、小车司机、挂车司机……假如我的货主和批发商做了分类的话，
>  然后我这个账户管理就会显示 2 级分类，也就会显示他们里面的子分类。这就方便我们去查角色嘛」

两件事：① 名册不能是空的（**代码里**要有默认来源，否则新装 / 清库之后左栏又只剩「全部」）；
② 名册支持**两级**（大类 + 子类），账户管理页左栏画成两级、点大类筛出它下面所有子类。

## 判据盯的是什么（选的是**方案 B：`parent_id`**）

1. **结构**：`user_categories.parent_id`（可空 + 索引 + 自引用外键）、迁移 `030` 与模型同形
   （加列与建索引分开判、能重跑、不回填、不建表、方言可携 —— ⛔ MySQL 没有 `CREATE INDEX IF NOT EXISTS`）；
2. **默认六类**：六个名字与顺序在 `schema_bootstrap.py` 里是**常量**，且**只在名册整个为空时**播种
   （清库能自己长回来，用户删掉**一个**不会被重启复活 —— 那是本项目踩过的坑）；
3. **只两级**：父必须自己是**大类**（`_parent_or_400`），子类的子类在建的时候就 400 ——
   界面只画两层，放任第三层等于那一层永远看不见；
4. **账号那一格没变**：`users.category` 仍是**叶子名**，改名级联（`User.category == old_name`）
   与「还有账号挂着不许删」两条一个字节都没动（这一条是回归，⛔ 不许被两级改造破坏）；
5. **界面**：左栏两级（`railRows` / `RailRow.depth`）、点大类覆盖它下面所有子类（`railCovers`）、
   三个筛选的**顺序**不变（先搜索 → 再左栏 → 最后状态档）；
6. **纯函数有单测**：`AccountCategoryTree.kt` 零 Compose import + `AccountCategoryTreeTest.kt`。

## ⛔ 它证不了什么

它只读源码与文档，**不连库、不起服务**：认证的是「形态与不变量齐不齐」，跑不出「改名真的级联了」
「点大类真的把子类账号端出来了」那种运行时事实 —— 那一头由 `backend/tests/test_user_category_tree.py`
（两级 + 播种 10 例）与 `AccountCategoryTreeTest.kt`（8 例）负责。

R4-BOUNDARY-JUSTIFICATION: 这一条**没法用边界消除**。它管的是「**同一个不变量在四个地方各写了一遍**」：
结构（模型/迁移）、默认来源（bootstrap）、写入校验（API）、画与筛（Kotlin）。
这几处没有共同的类型或编译期约束能表达「父必须也是大类」「名册为空才播种」——
把它们合成一个函数是**做不到**的（一个在后端启动期、一个在请求期、一个在客户端渲染期）。
所以唯一的边界就是**当场可核**：把每一处的形状与那几条不变量逐条钉住，
再配一份 `_reverse_verify_account_category_two_level.py` 证明这些钉子真的会红。

用法：

    python _tools/qa/_check_account_category_two_level.py            # 打印每一项
    python _tools/qa/_check_account_category_two_level.py --check    # 非零退出 = 有问题
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _check_hints import Checker, read  # noqa: E402

BE = "backend/app/"
A = "android/app/src/main/java/com/tapmoay/sorders/"
T = "android/app/src/test/java/com/tapmoay/sorders/"

UMODEL = BE + "models/user_category.py"
MIG30 = BE + "migrations/030_user_category_parent.py"
BOOT = BE + "core/schema_bootstrap.py"
UAPI = BE + "api/v1/user_categories.py"
USCHEMA = BE + "schemas/user_category.py"
UTESTS = "backend/tests/test_user_category_tree.py"
DTO = A + "data/remote/dto/Dtos.kt"
REPO = A + "data/repo/AppRepository.kt"
TREE = A + "ui/dispatcher/AccountCategoryTree.kt"
ACC_VM = A + "ui/dispatcher/AccountManageViewModel.kt"
ACC = A + "ui/dispatcher/AccountManageScreen.kt"
DRAWER = A + "ui/common/CategoryDrawer.kt"
PANEL = A + "ui/dispatcher/CategoryRostersPanel.kt"
ROSTER_VM = A + "ui/dispatcher/CategoryRostersViewModel.kt"
KTEST = T + "ui/dispatcher/AccountCategoryTreeTest.kt"
DOC = ROOT / "docs" / "changes" / "CHG-0112.md"
README = ROOT / "docs" / "changes" / "README.md"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"

#: 六个默认分类 —— 用户 2026-10-11 点名的顺序（⛔ 手写，不许从被检查的代码里算）
DEFAULTS = ["派单员", "货主", "批发商", "小车司机", "大车司机", "挂车司机"]

#: 判据条数下限：低于它先喊「扫描坏了」，⛔ 不许安静地少查（本项目栽过 5 次的形状）
MIN_RULES = 40


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="非零退出 = 有问题")
    ap.parse_args(argv)

    c = Checker()

    # ---------------------------------------------------------- 1. 反空转
    c.section("1. 反空转（文件在不在、够不够长、能不能打印）")
    for p in (UMODEL, MIG30, BOOT, UAPI, USCHEMA, UTESTS, DTO, REPO, TREE,
              ACC_VM, ACC, DRAWER, PANEL, ROSTER_VM, KTEST):
        c.ok(f"{p} 在", (ROOT / p).is_file())
    c.ok("新判据脚本自己会把结果打成 UTF-8", True)
    uapi = read(ROOT / UAPI)
    boot = read(ROOT / BOOT)
    mig = read(ROOT / MIG30)
    umodel = read(ROOT / UMODEL)
    tree = read(ROOT / TREE)
    acc_vm = read(ROOT / ACC_VM)
    acc = read(ROOT / ACC)
    drawer = read(ROOT / DRAWER)
    panel = read(ROOT / PANEL)
    roster_vm = read(ROOT / ROSTER_VM)
    ktest = read(ROOT / KTEST)
    dto = read(ROOT / DTO)
    repo = read(ROOT / REPO)
    uschema = read(ROOT / USCHEMA)
    utests = read(ROOT / UTESTS)

    # ---------------------------------------------------------- 2. 方案 B：结构
    c.section("2. 结构（方案 B：parent_id，两级；不是名字里带分隔）")
    c.ok("模型有 parent_id（可空 + 索引 + 自引用外键）",
         "parent_id: Mapped[int | None] = mapped_column(" in umodel
         and 'ForeignKey("user_categories.id")' in umodel
         and "index=True" in umodel)
    c.ok("模型里写清「只有两级、由写入路径拦」与「users.category 仍是叶子名」",
         "只有两级" in umodel and "叶子名" in umodel)
    c.ok("迁移 030 的版本号与文件名一致", "VERSION = 30" in mig and "NAME = \"user_category_parent\"" in mig)
    c.ok("迁移 030 加的是 user_categories.parent_id",
         'TABLE = "user_categories"' in mig and 'COLUMN = "parent_id"' in mig)
    c.ok("迁移 030 的索引名与模型 index=True 的默认名一致（两处建同一张索引）",
         'INDEX_NAME = "ix_user_categories_parent_id"' in mig)
    c.ok("迁移 030 能重跑（加列分开判）", "if COLUMN not in have:" in mig)
    c.ok("迁移 030 能重跑（建索引分开判）", "if INDEX_NAME not in _indexes(engine):" in mig)
    c.ok("迁移 030 真的建索引（不是只写在注释里）", "CREATE INDEX" in mig)
    c.ok("迁移 030 不建表（新表由 create_all 建）", "CREATE TABLE" not in mig)
    c.ok("迁移 030 不回填（谁是谁的子类没人能证明）", "UPDATE " not in mig)
    # ⚠️ 只看**代码**：这一份的 docstring 里正举着 `CREATE INDEX IF NOT EXISTS` 这个反面教材
    mig_code = mig.split('"""', 2)[2] if mig.count('"""') >= 2 else mig
    c.ok("迁移 030 不用 IF NOT EXISTS（MySQL 没有这个语法，发版栽过）", "IF NOT EXISTS" not in mig_code)
    c.ok("迁移 030 有 upgrade(engine)", re.search(r"^def upgrade\(", mig, re.M) is not None)
    c.ok("迁移 030 表不存在时直接返回（全新库交给 create_all）", "return" in mig and "is None" in mig)

    # ---------------------------------------------------------- 3. 默认六类
    c.section("3. 默认六类（代码里要有默认来源；只在名册整个为空时播种）")
    c.ok("默认六类是模块级常量（不是散在函数里的字面量）", "USER_CATEGORY_DEFAULTS: tuple[str, ...] = (" in boot)
    # ⚠️ 必须是**顺序敏感**的：只判「六个名字都在」的话，把两个名字对调照样绿
    #    （反向验证第 4 条注入抓到的正是这一种）——所以把那段元组原文解出来逐个比。
    _dflt_block = boot.split("USER_CATEGORY_DEFAULTS: tuple[str, ...] = (", 1)[1].split(")", 1)[0]
    c.ok("默认六类的名字与顺序（用户点名的顺序）", re.findall(r'"([^"]+)"', _dflt_block) == DEFAULTS)
    c.ok("播种是一个能被单测直接调的具名函数", "def seed_default_user_categories(engine: Engine) -> int:" in boot)
    c.ok("bootstrap 的启动路径里真的调了它", "seed_default_user_categories(engine)" in boot)
    c.ok("只有在名册整个为空时才播种", "if existing:" in boot and "SELECT COUNT(*) FROM user_categories" in boot)
    c.ok("播种只 INSERT，⛔ 不 DELETE / 不 UPDATE（不复活用户删掉的单个分类）",
         "INSERT INTO user_categories" in boot
         and "DELETE FROM user_categories" not in boot
         and "UPDATE user_categories" not in boot)
    c.ok("已经挂在账号上的分类名也收进来（否则那些账号在左栏里点不到）", "TRIM(category)" in boot)
    c.ok("回收站里的账号不算在用（与 /user-categories 的条数同一口径）", "has_del_suffix(" in boot)
    c.ok("播种失败不许拦启动（try/except DBAPIError）",
         "账号分类名册播种跳过" in boot)

    # ---------------------------------------------------------- 4. 出入参
    c.section("4. 出入参两端都带归属")
    c.ok("UserCategoryOut 带 parent_id", "parent_id: int | None = None" in uschema)
    c.ok("UserCategoryCreate 能收 parent_id",
         'parent_id: int | None = Field(None, description="上层分类编号' in uschema)
    c.ok("UserCategoryOut 写明条数只数直接的（不含子类）", "不含子类" in uschema)
    c.ok("App 的 UserCategoryDto 带 parent_id",
         '@SerialName("parent_id") val parentId: Long? = null' in dto)
    c.ok("App 的建请求能带 parent_id",
         "data class UserCategoryCreateRequest(" in dto and dto.count('@SerialName("parent_id")') >= 2)
    c.ok("AppRepository.createUserCategory 带上 parentId",
         "suspend fun createUserCategory(name: String, sortOrder: Int? = null, parentId: Long? = null)" in repo)
    c.ok("撤销删除（重建一格）也把归属带回来",
         "suspend fun restoreUserCategory(name: String, sortOrder: Int? = null, parentId: Long? = null)" in repo)

    # ---------------------------------------------------------- 5. 后端不变量
    c.section("5. 后端不变量（只两级 + 老规矩一个字没动）")
    c.ok("父必须存在（父不存在 → 400 说清）", "def _parent_or_400(" in uapi and "上层分类不存在" in uapi)
    c.ok("子类的子类被拒（只两级）", "只能做两级" in uapi and "parent.parent_id is not None" in uapi)
    c.ok("建分类时真的把父写进去", "parent_id=parent.id if parent is not None else None" in uapi)
    c.ok("归属进审计日志（两级之后它是名册的一部分）", '"parent_id": row.parent_id,' in uapi)
    c.ok("大类下面还有子类时不许删", "UserCategory.parent_id == row.id" in uapi and "子分类" in uapi)
    c.ok("改名级联一个字没动（⛔ 不许被两级改造破坏）",
         "User.category == old_name" in uapi and "users_moved" in uapi)
    c.ok("还有账号挂着不许删（老规矩照旧）", "先把它们改成别的分类" in uapi)
    c.ok("「在用」仍然排除回收站", "has_del_suffix" in uapi)
    c.ok("建号时顺手补的分类仍然是大类（不带 parent）", "UserCategory(name=clean, sort_order=_next_sort(db))" in uapi)
    c.ok("GET 仍是平铺一列按 sort_order 排（树由界面画）", "order_by(UserCategory.sort_order, UserCategory.id)" in uapi)
    c.ok("后端单测在（两级 + 播种）",
         (ROOT / UTESTS).is_file() and utests.count("\ndef test_") >= 8)

    # ---------------------------------------------------------- 6. App 纯函数
    c.section("6. App 侧：两级的判断是纯函数 + 有单测")
    c.ok("新的两级逻辑在独立文件里", "package com.tapmoay.sorders.ui.dispatcher" in tree)
    c.ok("纯函数文件零 Compose import（JVM 单测直接钉）", "import androidx.compose" not in tree)
    c.ok("左栏的一格带 depth（0 大类 / 1 子类）", "data class RailRow(" in tree and "val depth: Int," in tree)
    c.ok("大类覆盖自己 + 它下面的子类", "covers = (kids.map { it.name } + top.name).toSet()," in tree)
    c.ok("父不在 / 父自己是子类时降级成大类（不许把行藏起来）",
         "return if (parent.parentId == null) parent else null" in tree)
    c.ok("inRail 多了第 4 个参数（这一格覆盖的名字）",
         "fun <T> inRail(rows: List<T>, key: String, nameOf: (T) -> String, covers: Set<String> = emptySet()): List<T>" in tree)
    c.ok("key 的解析只有一份实现",
         "fun railCategoryName(key: String)" in tree
         and "fun railNameOf(key: String): String = railCategoryName(key)" in panel)
    c.ok("单测文件在且 ≥6 条", (ROOT / KTEST).is_file() and ktest.count("@Test") >= 6)
    c.ok("单测钉住「点大类筛出所有子类」",
         'assertEquals(setOf("货主", "食堂", "超市"), railNamesUnder(roster, "c|货主"))' in ktest)
    c.ok("单测钉住「脏数据不许消失」", "一行都不许消失" in ktest)

    # ---------------------------------------------------------- 7. 页面：两级 + 顺序
    c.section("7. 账户管理页（两级 + 筛选顺序不许换）")
    c.ok("左栏那几格由 railRows 给（大类一行、紧跟子类）",
         "val railRows: List<RailRow> get() = categoryRailRows(categoryRows)" in acc_vm)
    c.ok("点大类覆盖它下面所有子类",
         "val railCovers: Set<String> get() = railNamesUnder(categoryRows, railKey)" in acc_vm)
    c.ok("筛选带上覆盖集合（点大类 = 子类账号一起端出来）",
         "inRail(shown, railKey, { it.category }, railCovers)" in acc_vm)
    c.ok("三个筛选的顺序没换（先搜索/名册 → 左栏 → 状态档）",
         acc_vm.index("inRail(shown, railKey, { it.category }, railCovers)")
         < acc_vm.index(".filter { matchesStatus(it, statusTab) }"))
    c.ok("选中那一格的自愈还在（改名/删掉 → 回「全部」）",
         'railKey = ""' in acc_vm and 'categoryNames' in acc_vm)
    c.ok("读不到名册不吵（左栏退化成只有「全部」）", "catch (_: Exception)" in acc_vm)
    c.ok("抽屉那几格用 railRows 画（不是把名册平铺）",
         'items = listOf(CategoryDrawerItem("", "全部")) + vm.railRows.map {' in acc)
    c.ok("每一格把 depth 传下去", "CategoryDrawerItem(it.key, it.label, it.depth)" in acc)
    c.ok("空态判断也跟着覆盖集合走", "inRail(vm.shown, vm.railKey, { it.category }, vm.railCovers)" in acc)
    c.ok("抽屉零件支持缩进（子类靠它排在大类下面）",
         "data class CategoryDrawerItem(" in drawer and "val depth: Int = 0," in drawer
         and "if (depth > 0) Spacer(Modifier.width((18 * depth).dp))" in drawer)
    c.ok("抽屉那几格仍然一个条数都不显示（用户 2026-09-19 的裁定）",
         not any("count" in a.lower() for a in re.findall(r"CategoryDrawerItem\(([^)]*)\)", acc)))
    c.ok("名册面板：只有账号这份名册画「上层分类」（车辆是平表）",
         "parentChoices = vm.rows.filter { it.parentId == null }," in panel
         and "parentChoices: List<RosterRow> = emptyList()," in panel)
    c.ok("名册面板：子类那一行写出它挂在哪一类下面",
         'else "「" + parentName + "」下 · " + row.count + " " + unit,' in panel)
    c.ok("名册 VM 的 RosterRow 带上归属", "val parentId: Long? = null," in roster_vm)
    c.ok("新建/撤销都把归属带上",
         "var draftParentId by mutableStateOf<Long?>(null)" in roster_vm
         and "createRow(name: String, parentId: Long? = null)" in roster_vm
         and "restoreRow(name: String, sortOrder: Int, parentId: Long? = null)" in roster_vm)

    # ---------------------------------------------------------- 8. 文书三件
    c.section("8. 文书三件（文档 / 登记簿 / 声明页）")
    doc = read(DOC) if DOC.is_file() else ""
    c.ok("docs/changes/CHG-0112.md 九节齐", all(f"## {x}" in doc for x in "①②③④⑤⑥⑦⑧⑨"))
    c.ok("CHG-0112.md 里写明选了方案 B 以及为什么不选 A", "方案 B" in doc and "方案 A" in doc)
    c.ok("登记簿里有 CHG-0112 这一行（ID 格 + 链接格）",
         re.search(r"^\| `CHG-0112` \| CHG \| ", read(README), re.M) is not None
         and "[CHG-0112.md](CHG-0112.md)" in read(README))
    c.ok("AI_WORK_CLAIM.md 里有 CHG-0112 声明块",
         re.search(r"^### \[2026-10-11 [^\]]*\][^\n]*\*\*CHG-0112", read(CLAIM), re.M) is not None)

    c.ok(f"判据条数 {c.n_ok} ≥ {MIN_RULES}（防扫描空转）", c.n_ok >= MIN_RULES)

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, detail in c.fails:
            print(f"   - {label}")
            if detail:
                print(f"     {detail}")
        return 1
    print(
        f"✅ 全部 {c.n_ok} 项通过：账号分类两级（CHG-0112）—— parent_id 结构、默认六类播种、"
        "只两级、账号那一格仍是叶子名、左栏两级与点父筛全子。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
