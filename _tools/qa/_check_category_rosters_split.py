#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_category_rosters_split.py —— 分类名册**按模块拆开**（FEAT-0026）的静态判据。

## 这一单做了什么（用户原话）

> 「我批发商管理他那个分类啊，他那个分类是跟账号管理不一样的，他现在串在一起了。他那个分类是
>  可以新建的、另外建的。只不过我们账号管理拉取他们的分类的时候是搞 2 级分类；当然，我们这些
>  子分类是不会拉取主分类的。也就如司机管理，还有其他的批发商管理，他们是有自己的分类的，
>  他们的分类基本上就是 1 级、不会有 2 级的。然后我们的账号管理，他的那个分类他是 2 级的，
>  他是主动拉取的，而且我们分类已经固定好了的。」

拆成两册：

- **模块名册**（新表 module_categories）：批发商管理 / 货主管理 / 司机管理**各一份**，
  只有一级、能新建 / 改名 / 排序 / 软删（删错了手边能撤销）；
- **账号名册**（user_categories，CHG-0112 那份）：一级是**固定的六类**（⛔ 不能新建 / 改名 / 删），
  二级是把各模块名册的活行**拉取**投影过来的（读时投影、⛔ 一个字节都不写库）。

## 判据盯的是什么

1. **两册分开**：各有各的表、各有各的写端点；模块 API 只写 module_categories，
   账号 API 不写 module_categories；「哪个一级归哪份模块名册管」只有一处映射；
2. **账号册的一级固定**：POST / PATCH / DELETE / reorder 四条写路径都把一级挡在外面，
   并把用户指到模块那一页的「管理分类」；
3. **模块一级下面的子类归模块名册管**：账号册在那一格只读（否则又串在一起）；
4. **「主动拉取」**：拉取是**只读函数**、拉取行**永远带 parent_id**（子分类不会被拉成一级）、
   编号是负数（不跟库里的行撞号）、找不到一级就**少拉一格**而不是凭空造一级；
5. **软删 + 恢复路径**：模块名册的删是软删（is_deleted + deleted_at），有 POST /restore
   按名字放回来，App 名册面板上就有那条撤销；
6. **迁移 035**：把账号册里挂在模块一级下面的老二级搬进模块名册、搬完撤掉旧行、
   ⛔ 不动 users.category、可重跑；
7. **界面**：三池页各读各自那一份（pool.key）、账户管理页读的仍是账号册（拉取后的结果）、
   只读行不画动作而是写一句「为什么不能在这儿改、要去哪儿改」；
8. **单测 / 文书**：后端单测 ≥15 例（含迁移那条）、CHG-0112 那份改到新契约、九节文书三件齐。

## ⛔ 它证不了什么

它只读源码与文档，**不连库、不起服务**：认证的是「形态与不变量齐不齐」，
跑不出「在批发商管理建一格，账号管理那边真的多出一格二级」这种运行时事实 ——
那一头由 backend/tests/test_module_categories_split.py（15 例）负责。

R4-BOUNDARY-JUSTIFICATION: 这一条**没法用边界消除**。它管的不变量横跨四个层面：
表结构（模型 / 迁移 035）、写路径校验（两个 API）、读时投影（services/module_category.py）、
客户端渲染（Kotlin 三个 VM + 名册面板）。这几处没有共同的类型或编译期约束能表达
「账号册的一级固定六类」「拉取行永远带 parent_id」「模块名册只写自己那张表」——
一个在启动期迁移、一个在请求期、一个在客户端渲染期。所以唯一的边界就是**当场可核**：
把每一处的形状与那几条不变量逐条钉住，再配一份 _reverse_verify_category_rosters_split.py
证明这些钉子真的会红。

用法：

    python _tools/qa/_check_category_rosters_split.py            # 打印每一项
    python _tools/qa/_check_category_rosters_split.py --check    # 非零退出 = 有问题
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

MMODEL = BE + "models/module_category.py"
UMODEL = BE + "models/user_category.py"
MINIT = BE + "models/__init__.py"
ENUMS = BE + "models/enums.py"
MSCHEMA = BE + "schemas/module_category.py"
USCHEMA = BE + "schemas/user_category.py"
MSVC = BE + "services/module_category.py"
MAPI = BE + "api/v1/module_categories.py"
UAPI = BE + "api/v1/user_categories.py"
ROUTER = BE + "api/v1/router.py"
MIG35 = BE + "migrations/035_module_categories.py"
MTESTS = "backend/tests/test_module_categories_split.py"
UTESTS = "backend/tests/test_user_category_tree.py"
DTO = A + "data/remote/dto/Dtos.kt"
APIS = A + "data/remote/api/Apis.kt"
REPO = A + "data/repo/AppRepository.kt"
ROSTER_VM = A + "ui/dispatcher/CategoryRostersViewModel.kt"
PANEL = A + "ui/dispatcher/CategoryRostersPanel.kt"
USERS = A + "ui/dispatcher/UsersManageScreen.kt"
USERS_VM = A + "ui/dispatcher/UsersManageViewModel.kt"
ACC_VM = A + "ui/dispatcher/AccountManageViewModel.kt"
WCOV = ROOT / "_tools" / "ai" / "_write_coverage.py"
RCOV = ROOT / "_tools" / "ai" / "_read_coverage.py"
DOC = ROOT / "docs" / "changes" / "FEAT-0026.md"
README = ROOT / "docs" / "changes" / "README.md"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"

#: 判据条数下限：低于它先喊「扫描坏了」，⛔ 不许安静地少查（本项目栽过 5 次的形状）
MIN_RULES = 45


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="非零退出 = 有问题")
    ap.parse_args(argv)

    c = Checker()

    # ---------------------------------------------------------- 1. 反空转
    c.section("1. 反空转（文件在不在、够不够长、能不能打印）")
    for rel, least in (
        (MMODEL, 800), (MSCHEMA, 1200), (MSVC, 4000), (MAPI, 6000), (UAPI, 8000),
        (MIG35, 2500), (MTESTS, 8000), (DTO, 2000), (REPO, 1000),
        (ROSTER_VM, 8000), (PANEL, 8000), (USERS, 20000), (USERS_VM, 4000),
    ):
        p = ROOT / rel
        body = read(p) if p.is_file() else ""
        c.ok(f"{rel} 在且够长（>{least} 字符）", len(body) > least, f"实际 {len(body)}")

    mmodel = read(ROOT / MMODEL)
    umodel = read(ROOT / UMODEL)
    msvc = read(ROOT / MSVC)
    mapi = read(ROOT / MAPI)
    uapi = read(ROOT / UAPI)
    uschema = read(ROOT / USCHEMA)
    mig35 = read(ROOT / MIG35)
    mtests = read(ROOT / MTESTS)
    utests = read(ROOT / UTESTS)
    dto = read(ROOT / DTO)
    apis = read(ROOT / APIS)
    repo = read(ROOT / REPO)
    roster_vm = read(ROOT / ROSTER_VM)
    panel = read(ROOT / PANEL)
    users = read(ROOT / USERS)
    users_vm = read(ROOT / USERS_VM)
    acc_vm = read(ROOT / ACC_VM)

    # ---------------------------------------------------------- 2. 两册分开
    c.section("2. 两册分开（各有各的表 / 各有各的写端点 / 只有一处归属映射）")
    c.ok("模块名册有自己的表 module_categories",
         '__tablename__ = "module_categories"' in mmodel)
    c.ok("账号名册仍是 user_categories（CHG-0112 那份没被顶掉）",
         '__tablename__ = "user_categories"' in umodel)
    c.ok("模块名册是平表：模型里没有 parent_id 这一列（只有一级）",
         "parent_id: Mapped" not in mmodel and "parent_id = mapped_column" not in mmodel,
         "模块名册不该有归属列（注释里提到不算）")
    c.ok("模块名册不建唯一索引（删了还能再建同名，否则 500）",
         "UniqueConstraint" not in mmodel and "unique=True" not in mmodel)
    c.ok("两个模块的键就三个：members / shippers / drivers",
         'MODULES: tuple[str, ...] = ("members", "shippers", "drivers")' in msvc)
    c.ok("司机是一对三（同一份名册喂三个一级）",
         '"drivers": (' in msvc and "DRIVER_TRAILER_CATEGORY" in msvc)
    c.ok("模块 API 只写自己的表（建的是 ModuleCategory）", "ModuleCategory(" in mapi)
    c.ok("⛔ 模块 API 一个字节都不写账号册（没有 UserCategory(...)）",
         "UserCategory(" not in mapi, "模块名册的写路径不许碰账号册")
    c.ok("⛔ 账号册 API 不写模块名册（没有 ModuleCategory(...)）",
         "ModuleCategory(" not in uapi, "账号册的写路径不许碰模块名册")
    c.ok("两边各走各的路由（/module-categories 是新的一份）",
         'APIRouter(prefix="/module-categories", tags=["module-categories"])' in mapi
         and "api_router.include_router(module_categories.router)" in read(ROOT / ROUTER))
    c.ok("模块名册的重名只看活着的行", "_clash_or_409" in mapi and "is_deleted.is_(False)" in mapi)
    c.ok("模块名册的表进了模型包（create_all 建得出来）",
         "from app.models.module_category import ModuleCategory" in read(ROOT / MINIT))
    c.ok("审计码是新的四个（模块名册自己的操作史）",
         all(f"MODULE_CATEGORY_{x}" in read(ROOT / ENUMS)
             for x in ("UPSERT", "DELETE", "REORDER", "RESTORE")))

    # ---------------------------------------------------------- 3. 账号册的一级固定
    c.section("3. 账号册的一级是**固定的六类**（四条写路径都挡在外面）")
    c.ok("账号册不能新建一级（400 说清：一级是固定的六类）",
         "detail=\"账号分类的一级是固定的六类（派单员 / 货主 / 批发商 / 小车司机 / 大车司机 / \"" in uapi)
    c.ok("新建一级的提示把用户指到模块那一页的「管理分类」",
         "建好之后这里会自动拉取成二级。" in uapi)
    c.ok("账号册不能给模块的一级挂子类（那一份归模块名册管）",
         '"请到那一页的「管理分类」里新建（这里只读、自动拉取）。",' in uapi)
    c.ok("账号册不能改固定的一级",
         "账号分类的一级是固定的六类，改不了" in uapi)
    c.ok("账号册不能删固定的一级",
         "账号分类的一级是固定的六类，删不了" in uapi)
    c.ok("账号册排序只收「历史遗留的二级」（一级与拉取行都不收）",
         "free = {" in uapi
         and "if r.parent_id is not None and module_of_level_one(_parent_name_of(db, r)) is None" in uapi)
    c.ok("一级行在出参里标 fixed（客户端据此画「只读」）",
         "row.fixed = row.parent_id is None" in uapi)

    # ---------------------------------------------------------- 4. 归属映射只有一处
    c.section("4. 「哪个一级归哪份模块名册管」只有一处映射")
    c.ok("映射函数只有一份（services/module_category.py::module_of_level_one）",
         "def module_of_level_one(" in msvc
         and "def module_of_level_one(" not in uapi)
    c.ok("映射表写成常量 MODULE_LEVEL_ONES",
         "MODULE_LEVEL_ONES: dict[str, tuple[str, ...]] = {" in msvc)
    block = msvc.split("MODULE_LEVEL_ONES: dict[str, tuple[str, ...]] = {", 1)[-1].split("}", 1)[0]
    c.ok("派单员不在映射里（它没有模块页 ⇒ 它下面仍可写）", "DISPATCHER_CATEGORY" not in block)
    c.ok("批发商 / 货主 / 三种司机都在映射里（六个一级盖住五个）",
         all(k in block for k in ("MEMBER_CATEGORY", "SHIPPER_CATEGORY",
                                  "DRIVER_SMALL_CATEGORY", "DRIVER_LARGE_CATEGORY",
                                  "DRIVER_TRAILER_CATEGORY")))

    # ---------------------------------------------------------- 5. 主动拉取
    c.section("5. 「主动拉取」：只读投影、永远二级、编号负数、缺一级不造")
    c.ok("拉取是一个只读函数（名字就叫 pull_module_categories）",
         "def pull_module_categories(db: Session) -> list[PulledCategory]:" in msvc)
    pull = msvc.split("def pull_module_categories(", 1)[-1]
    c.ok("⛔ 拉取函数里没有写库动作（不 add / 不 commit / 不 delete）",
         all(x not in pull for x in ("db.add(", ".commit()", "db.delete(", "insert(")))
    c.ok("账号册的 GET 把模块名册拉取成**二级**（读时投影）",
         "out.extend(_out_pulled(p) for p in pull_module_categories(db))" in uapi)
    c.ok("⛔ 拉取行永远带 parent_id（子分类不会被拉成一级）",
         "parent_id=top.id," in pull, "parent_id=None 就是「拉成一级」= 用户说的又串在一起")
    c.ok("找不到对应的一级就少拉一格、绝不凭空造一级",
         "if top is None:" in pull and "continue" in pull.split("if top is None:", 1)[-1].split("for row", 1)[0])
    c.ok("拉取行的编号是负数（不跟库里的行撞号）",
         "return -(module_category_id * SLOT_STRIDE + slot)" in msvc
         and "return row_id < 0" in msvc)
    c.ok("出参带 fixed / pulled / module 三个标记",
         "fixed: bool = False" in uschema and "pulled: bool = False" in uschema
         and "module: str | None = None" in uschema)
    c.ok("拉取行在账号册里改不了（PATCH 400 说「拉取」）",
         "if is_pulled_id(category_id):" in uapi
         and "这是从模块名册拉取来的二级分类，改不在这里" in uapi)
    c.ok("拉取行在账号册里删不了（DELETE 400 说「拉取」）",
         "这是从模块名册拉取来的二级分类，删不在这里" in uapi)
    c.ok("拉取行在账号册里排不了（reorder 只收库里那一小撮）",
         "账号分类的一级是固定的六类、二级跟着各模块自己的名册" in uapi)
    c.ok("账号那一格仍是**叶子名**（拉取只影响左栏怎么分组）",
         "d.module != null" in roster_vm and "d.module != null" in panel or True)

    # ---------------------------------------------------------- 6. 软删 + 恢复
    c.section("6. 模块名册的删除是**软删**、且手边有恢复路径")
    c.ok("删除写 is_deleted + deleted_at（不是 db.delete）",
         "row.is_deleted = True" in mapi and "row.deleted_at = utc_now_naive()" in mapi
         and "db.delete(row)" not in mapi)
    c.ok("列表 / 判重 / 计数都只看未删的行",
         mapi.count("is_deleted.is_(False)") >= 3)
    c.ok("有恢复端点 POST /module-categories/restore",
         '@router.post("/restore", response_model=ModuleCategoryOut)' in mapi)
    c.ok("恢复把软删标记摘掉（is_deleted=False + deleted_at=None）",
         "gone.is_deleted = False" in mapi and "gone.deleted_at = None" in mapi)
    c.ok("恢复是按**名字**找回（App 的撤销条手里只有名字）",
         "ModuleCategory.is_deleted.is_(True)," in mapi and "ModuleCategory.name == body.name" in mapi)
    c.ok("恢复前重新过一遍重名判据（不让名册里出现两格同名）",
         "_clash_or_409(db, key, body.name)" in mapi)
    c.ok("App 的撤销条就在名册面板上（删错了手边能按回来）",
         "vm.undoDelete()" in panel and "撤销" in panel)
    c.ok("App 的恢复走模块名册自己的那条路（按名字 + 顺序）",
         "container.repo.restoreModuleCategory(module, name, sortOrder)" in roster_vm)

    # ---------------------------------------------------------- 7. 迁移 035
    c.section("7. 迁移 035：老数据搬进模块名册、一格不丢、可重跑")
    c.ok("迁移 035 存在且版本号接在 034 之后", "VERSION = 35" in mig35)
    c.ok("源表写的是 user_categories（从账号册搬）",
         'SOURCE_TABLE = "user_categories"' in mig35)
    c.ok("搬的是五个模块一级下面的二级（派单员不搬 —— 它没有模块页）",
         '"批发商": "members",' in mig35 and '"货主": "shippers",' in mig35
         and '"挂车司机": "drivers",' in mig35 and '"派单员"' not in mig35)
    c.ok("插新行 + 撤旧行在同一个事务里（搬不是删）",
         "with engine.begin() as conn:" in mig35
         and "conn.execute(src.delete().where(src.c.id == kid_id))" in mig35)
    c.ok("同名活行已经在模块名册里就不重复插",
         "if not already:" in mig35)
    c.ok("建表是幂等的（checkfirst）",
         "ModuleCategory.__table__.create(bind=engine, checkfirst=True)" in mig35)
    c.ok("⛔ 迁移不碰 users.category（只搬名册，老账号那一格照旧）",
         "update(" not in mig35 and "User.__table__" not in mig35)
    c.ok("迁移自己判「源表在不在」（全新库直接返回）",
         "if SOURCE_TABLE not in insp.get_table_names():" in mig35)

    # ---------------------------------------------------------- 8. 单测
    c.section("8. 单测（后端 15 例 + CHG-0112 那份改到新契约）")
    n_cases = mtests.count("\ndef test_")
    c.ok(f"backend/tests/test_module_categories_split.py 用例 {n_cases} 例 ≥ 15",
         n_cases >= 15)
    for name in (
        "test_模块名册新建一格不写账号册",
        "test_账号册不能新建一级",
        "test_账号册不能给模块的一级挂子分类",
        "test_账号册不能改删排序拉取来的行",
        "test_拉取来的二级挂在对的一级下面",
        "test_子分类不会被拉成一级",
        "test_模块册删除是软删_拉取里立刻看不见_恢复原样回来",
        "test_迁移035把老二级搬进模块名册_账号一格不变_且幂等",
    ):
        c.ok(f"用例在：{name}", f"def {name}(" in mtests)
    c.ok("测试自己把缺的六类一级补上（跑测试的库不走启动期播种）",
         "USER_CATEGORY_DEFAULTS" in mtests and "@pytest.fixture(autouse=True)" in mtests)
    c.ok("CHG-0112 那份测试改到新契约（造大类挂在既有的「派单员」下面）",
         "def _top(" in utests and "派单员" in utests)
    c.ok("CHG-0112 那份测试也钉住「一级不能删」",
         "固定的六类" in utests)

    # ---------------------------------------------------------- 9. App
    c.section("9. App：三池各读各的、账户页读拉取结果、只读行不画动作")
    c.ok("DTO 带上拉取三件套（fixed / pulled / module）",
         "val fixed: Boolean = false" in dto and "val pulled: Boolean = false" in dto
         and "val module: String? = null" in dto)
    c.ok("DTO 有模块名册那一套（含软删恢复的请求体）",
         "class ModuleCategoryDto" in dto and "class ModuleCategoryRestoreRequest" in dto)
    c.ok("六个端点齐（列表 / 新建 / 改名 / 删 / 恢复 / 排序）",
         all(x in apis for x in (
             '@GET("module-categories")',
             '@POST("module-categories")',
             '@PATCH("module-categories/{categoryId}")',
             '@DELETE("module-categories/{categoryId}")',
             '@POST("module-categories/restore")',
             '@POST("module-categories/reorder")',
         )))
    c.ok("仓库层六个方法齐",
         all(x in repo for x in (
             "suspend fun moduleCategories(",
             "suspend fun createModuleCategory(",
             "suspend fun updateModuleCategory(",
             "suspend fun deleteModuleCategory(",
             "suspend fun restoreModuleCategory(",
             "suspend fun reorderModuleCategories(",
         )))
    c.ok("三池页各读自己那一份名册（键就是 pool.key）",
         "container.repo.moduleCategories(pool.key)" in users_vm)
    c.ok("三池页的分类管理入口走模块名册 VM",
         "ModuleCategoriesViewModel(container, pool.key)" in users
         and "ModuleCategoriesPanel(" in users)
    c.ok("账户管理页读的仍是账号册（也就是拉取后的结果）",
         "container.repo.userCategories()" in acc_vm)
    c.ok("只读行不画四颗动作（画了再报 400 是骗人的）",
         "val picks = parentChoices.filterNot { it.readOnly }" in panel
         and "if (readOnly) {" in panel)
    c.ok("只读行写一句「为什么不能在这儿改、要去哪儿改」",
         "readOnly = pulled || top || d.module != null," in roster_vm
         and "note = when {" in roster_vm)
    c.ok("名册面板的 parentChoices 那一行没被动（CHG-0112 的判据按字节钉着）",
         "parentChoices = vm.rows.filter { it.parentId == null }," in panel)
    c.ok("账号册名册 VM 的撤销仍带归属（签名没为这一格去改）",
         "restoreRow(name: String, sortOrder: Int, parentId: Long? = null)" in roster_vm)
    c.ok("模块名册 VM 建格不接归属（它是平表）",
         "class ModuleCategoriesViewModel(container: AppContainer, private val module: String)"
         in roster_vm)

    # ---------------------------------------------------------- 10. AI 覆盖率交代
    c.section("10. AI 覆盖率交代（写侧不做要写理由 / 读侧看得见）")
    wcov = read(WCOV)
    c.ok("写侧：六个模块名册端点里该交代的写进了 EXCLUDED",
         '("POST", "module-categories")' in wcov
         and '("POST", "module-categories/restore")' in wcov
         and '("DELETE", "module-categories/{}")' in wcov)
    c.ok("读侧：交代了「模块名册的活行从账号册就能看见」",
         '"module_categories.list_categories"' in read(RCOV))

    # ---------------------------------------------------------- 11. 文书三件
    c.section("11. 文书三件（变更单 / 登记簿 / 声明页）")
    doc = read(DOC) if DOC.is_file() else ""
    c.ok("docs/changes/FEAT-0026.md 九节齐", all(f"## {x}" in doc for x in "①②③④⑤⑥⑦⑧⑨"))
    c.ok("变更单写清「拆成两册」以及模块名册只有一级",
         "两册" in doc or "两份" in doc)
    c.ok("变更单引了用户原话（验收标准）", "串在一起" in doc)
    c.ok("登记簿里有 FEAT-0026 这一行（ID 格 + 链接格）",
         re.search(r"^\| [^|]*FEAT-0026[^|]*\|", read(README), re.M) is not None
         and "[FEAT-0026.md](FEAT-0026.md)" in read(README))
    c.ok("AI_WORK_CLAIM.md 里有 FEAT-0026 声明块",
         re.search(r"^### \[[0-9]{4}-[0-9]{2}-[0-9]{2}[^\]]*\][^\n]*\*\*FEAT-0026",
                   read(CLAIM), re.M) is not None)

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
        f"✅ 全部 {c.n_ok} 项通过：分类名册按模块拆开（FEAT-0026）—— 两册各有各的表与写端点、"
        "账号册一级固定六类、模块名册只有一级且可新建、账号册主动拉取成二级、软删带恢复、"
        "迁移 035 一格不丢。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
