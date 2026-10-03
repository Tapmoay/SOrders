"""_check_account_vehicle_categories.py —— 账号分类 / 车辆分类名册（FEAT-0010）的静态判据。

## 这一批做了什么（用户 2026-10-05 原话）

> 「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……在这个位置也加个分类，
>  默认是显示，全部，同样也是左边侧边栏，然后左边侧边栏同样也是可以新增分类的，
>  那个左边侧分栏的底下，凡是跟地点是同样的」

账户 / 司机 / 货主 / 批发商 / 车辆五个名册页的标题右边多一个分类胶囊，点开是**左侧抽屉**
（⛔ 不是商品管理那种常驻左栏），抽屉底部那格「管理分类」进名册管理面板；分类名存
`users.category` / `vehicles.category`（自由文本、空串 = 未分类），名册管「有哪些类 + 顺序」。

## 判据盯的是什么

1. **形态**：三个页面真的被 `ModalNavigationDrawer` 包住、抽屉用共用件 `CategoryDrawerSheet`、
   胶囊是 `CategoryTriggerChip`、抽屉里**一格条数都不许有**（用户 2026-09-19：
   「那个分组下面不要显示有多少条啊，这是多余信息」）、⛔ 不许出现 `MasterRail(`
   （那是被否掉的常驻左栏）；
2. **两层名册**：后端两张表 + 两列 + 两条迁移（一事一迁移）+ 两套端点（写端点走
   `require_permission(Permission.USER_MANAGE)`、三个写动作都写审计日志）；
3. **四个端点各管各的**：账号名册数条数时**排除回收站**（`has_del_suffix`），车辆名册把
   停用的车**算在内** —— 这两条口径故意相反，是写进单测的。

## 一条容易踩的坑（判据自己记着）

「条数只在管理面板里出现」不是「代码里不许有 count」：`RosterRowCard` 里那一行
`"N 个账号"` 是对的，被禁的只是**抽屉那几格**。所以下面第 5 节数的是
`CategoryDrawerItem(` 的构造里有没有夹带条数，而不是全文搜 `count`。

R4-BOUNDARY-JUSTIFICATION: 本判据只读源码与文档（`read()`），不 import 后端、不连库、
不跑迁移；它认证的是「形态与登记齐不齐」，**跑不出**「分类改名真的级联了」那种运行时事实 ——
那一头由 `backend/tests/test_user_categories.py`、`test_vehicle_categories.py`（各 12 例）负责。

用法：

    python _tools/qa/_check_account_vehicle_categories.py            # 打印每一项
    python _tools/qa/_check_account_vehicle_categories.py --check    # 非零退出 = 有问题
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _check_hints import Checker, read  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BE = ROOT / "backend" / "app"
AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
UI = AND / "ui" / "dispatcher"

USER_API = BE / "api" / "v1" / "user_categories.py"
VEH_API = BE / "api" / "v1" / "vehicle_categories.py"
MIG14 = BE / "migrations" / "014_user_categories.py"
MIG15 = BE / "migrations" / "015_vehicle_categories.py"
MODEL_U = BE / "models" / "user_category.py"
MODEL_V = BE / "models" / "vehicle_category.py"
SCHEMA_U = BE / "schemas" / "user_category.py"
SCHEMA_V = BE / "schemas" / "vehicle_category.py"

ACCOUNT = UI / "AccountManageScreen.kt"
ACCOUNT_VM = UI / "AccountManageViewModel.kt"
USERS = UI / "UsersManageScreen.kt"
USERS_VM = UI / "UsersManageViewModel.kt"
VEHICLE = UI / "VehicleManageScreen.kt"
PANEL = UI / "CategoryRostersPanel.kt"
ROSTER_VM = UI / "CategoryRostersViewModel.kt"
DRAWER = AND / "ui" / "common" / "CategoryDrawer.kt"
DTO = AND / "data" / "remote" / "dto" / "Dtos.kt"
APIS = AND / "data" / "remote" / "api" / "Apis.kt"
REPO = AND / "data" / "repo" / "AppRepository.kt"

DOC = ROOT / "docs" / "changes" / "FEAT-0010.md"
README = ROOT / "docs" / "changes" / "README.md"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"

MIN_LINES = 80


def main() -> int:
    c = Checker()

    # ---------- 1. 反空转：文件在、不是空壳 ----------
    c.section("1. 文件都在（判据不是空转）")
    for p in (USER_API, VEH_API, MODEL_U, MODEL_V, SCHEMA_U, SCHEMA_V, MIG14, MIG15,
              ACCOUNT, USERS, VEHICLE, PANEL, ROSTER_VM, DRAWER, DOC):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 存在", p.exists())
    for p in (USER_API, VEH_API, PANEL, ROSTER_VM):
        n = len(read(p).splitlines()) if p.exists() else 0
        c.ok(f"{p.name} 不是空壳（≥{MIN_LINES} 行）", n >= MIN_LINES, f"现在 {n} 行")

    api_u = read(USER_API) if USER_API.exists() else ""
    api_v = read(VEH_API) if VEH_API.exists() else ""
    mig14 = read(MIG14) if MIG14.exists() else ""
    mig15 = read(MIG15) if MIG15.exists() else ""

    # ---------- 2. 后端：两张表 + 两列 ----------
    c.section("2. 后端：名册表与归属列")
    c.ok("两张名册表都建在模型里（create_all 才看得到）",
         '__tablename__ = "user_categories"' in read(MODEL_U)
         and '__tablename__ = "vehicle_categories"' in read(MODEL_V))
    # 2026-10-05 反向验证抓出来的缺陷：原来只判 "UserCategory" 这个**子串**在不在，
    # 把 __all__ 里那一行改成 "UserCategoryHidden", 照样绿 —— 表建了、却没被 __all__ 重导出。
    # 现在逐条判「import 行 + __all__ 里的带引号带逗号那一条」。
    init_src = read(BE / "models" / "__init__.py")
    c.ok("两张名册都重导出进 models/__init__.py（import 与 __all__ 两处都要在）",
         "from app.models.user_category import UserCategory" in init_src
         and "from app.models.vehicle_category import VehicleCategory" in init_src
         and '"UserCategory",' in init_src
         and '"VehicleCategory",' in init_src)
    c.ok("账号那一列按共用口径声明（自由文本 + 索引）",
         'category: Mapped[str] = mapped_column(String(32), default="", index=True)' in read(BE / "models" / "user.py"))
    c.ok("车辆那一列按共用口径声明（自由文本 + 索引）",
         'category: Mapped[str] = mapped_column(String(32), default="", index=True)' in read(BE / "models" / "vehicle.py"))

    # ---------- 3. 迁移：一事一迁移 + 可重跑 ----------
    c.section("3. 迁移 014 / 015")
    c.ok("014 管的是 users",
         'TABLE = "users"' in mig14 and 'INDEX_NAME = "ix_users_category"' in mig14 and "VERSION = 14" in mig14)
    c.ok("015 管的是 vehicles",
         'TABLE = "vehicles"' in mig15 and 'INDEX_NAME = "ix_vehicles_category"' in mig15 and "VERSION = 15" in mig15)
    for name, src in (("014", mig14), ("015", mig15)):
        c.ok(f"{name} 的列定义是 NOT NULL DEFAULT ''（空串 = 未分类）",
             "VARCHAR(32) NOT NULL DEFAULT ''" in src)
        # 同上：原来只判两个 if 还在，把执行 CREATE INDEX 那一行删掉照样绿 ——
        # 「分开判」是手段，「索引真的建出来」才是目的（老库上左栏筛选要靠它）。
        c.ok(f"{name} 加列与建索引分开判、分开执行，且索引真的建得出来（MySQL DDL 隐式提交，必须能重跑）",
             "if COLUMN not in have:" in src
             and "if INDEX_NAME not in _indexes(engine):" in src
             and "CREATE INDEX" in src)
        c.ok(f"{name} 不建表（新表由 create_all 建）", "CREATE TABLE" not in src)
        c.ok(f"{name} 不回填老数据（⛔ 猜不出老账号/老车属于哪一类）", "UPDATE " not in src)

    # ---------- 4. 端点：五个 + 门 + 审计 ----------
    c.section("4. 两套端点（五个 + 门 + 审计）")
    for name, src, prefix in (("账号", api_u, "/user-categories"), ("车辆", api_v, "/vehicle-categories")):
        c.ok(f"{name}名册的 prefix 是 {prefix}", f'prefix="{prefix}"' in src)
        c.ok(f"{name}名册五个端点齐（GET/POST/PATCH/reorder/DELETE）",
             src.count("@router.") >= 5 and '@router.post("/reorder"' in src)
        c.ok(f"{name}名册四个写端点都走 require_permission(Permission.USER_MANAGE)",
             src.count("Depends(require_permission(Permission.USER_MANAGE))") == 4)
        c.ok(f"{name}名册的读端点是「登录即可」（与地点/联系人名册同一条）",
             "def list_categories(current: CurrentUser" in src)
        c.ok(f"{name}名册排序走唯一的 ordered_ids（整份提交，缺一行整份拒绝）",
             "ordered_ids(" in src)
        c.ok(f"{name}名册三个写动作都写审计日志", src.count("write_log(") >= 3)
    c.ok("账号名册数「在用」时排除回收站（否则会出现账号都删了分类删不掉）",
         "has_del_suffix(" in api_u)
    # 2026-10-05 反向验证抓出来的缺陷：原判是「子串在不在」，把整行注释掉照样绿 ——
    # 而注释掉之后接口**根本不存在**。改成从行首锚定的整行调用。
    router_src = read(BE / "api" / "v1" / "router.py")
    c.ok("两个名册都在 router.py 注册了（是行首的整行调用，不是被注释掉的那一行）",
         re.search(r"^api_router\.include_router\(user_categories\.router\)", router_src, re.M) is not None
         and re.search(r"^api_router\.include_router\(vehicle_categories\.router\)", router_src, re.M) is not None)
    enums = read(BE / "models" / "enums.py")
    for code in ("USER_CATEGORY_UPSERT", "USER_CATEGORY_DELETE", "USER_CATEGORY_REORDER",
                 "VEHICLE_CATEGORY_UPSERT", "VEHICLE_CATEGORY_DELETE", "VEHICLE_CATEGORY_REORDER"):
        c.ok(f"动作码 {code} 在 enums 里", code in enums)
    cov = read(BE / "core" / "capability_audit_coverage.py")
    # 同上：原来只判子串，把 单项改成 单项_X 照样绿。
    codes6 = ("USER_CATEGORY_UPSERT", "USER_CATEGORY_DELETE", "USER_CATEGORY_REORDER",
              "VEHICLE_CATEGORY_UPSERT", "VEHICLE_CATEGORY_DELETE", "VEHICLE_CATEGORY_REORDER")
    c.ok("六个新动作码在审计覆盖表里被认领（挂在 user:manage 上，逐条带引号核）",
         all(f"'{code}'" in cov for code in codes6))
    # 同上：只判名字在不在的话，把调用改成 pass、只留 import 那一行，照样绿 ——
    # 而「建号时顺手补名册」正是这一条要保证的行为，import 什么都不保证。
    users_src = read(BE / "api" / "v1" / "users.py")
    veh_src = read(BE / "api" / "v1" / "vehicles.py")
    c.ok("账号/车辆建号建车时会顺手把新分类名补进名册（ensure_*_category 真的被调用，不只是 import）",
         users_src.count("ensure_user_category(db,") >= 2
         and veh_src.count("ensure_vehicle_category(db,") >= 2)

    # ---------- 5. Android 数据层 ----------
    c.section("5. Android 数据层（DTO / 端点 / 仓库）")
    dto = read(DTO)
    apis = read(APIS)
    repo = read(REPO)
    for cls in ("UserCategoryDto", "UserCategoryCreateRequest", "UserCategoryUpdateRequest",
                "UserCategoryReorderRequest", "VehicleCategoryDto", "VehicleCategoryCreateRequest",
                "VehicleCategoryUpdateRequest", "VehicleCategoryReorderRequest"):
        # 同上：只判子串的话，类名后面加一个 X 还是绿的。
        c.ok(f"{cls} 在 Dtos.kt 里", f"data class {cls}(" in dto)
    c.ok("两份名册的条数字段名与后端一致（user_count / vehicle_count）",
         '@SerialName("user_count")' in dto and '@SerialName("vehicle_count")' in dto)
    for path in ("user-categories", "vehicle-categories"):
        c.ok(f"{path} 的五个端点都在 Apis.kt 里",
             f'@GET("{path}")' in apis and f'@POST("{path}/reorder")' in apis
             and f'@PATCH("{path}/{{categoryId}}")' in apis and f'@DELETE("{path}/{{categoryId}}")' in apis)
    for fn in ("userCategories", "createUserCategory", "updateUserCategory", "deleteUserCategory",
               "reorderUserCategories", "vehicleCategories", "createVehicleCategory",
               "updateVehicleCategory", "deleteVehicleCategory", "reorderVehicleCategories"):
        c.ok(f"AppRepository.{fn}() 在", f"fun {fn}(" in repo)
    c.ok("账号与车辆的出参都带上了分类（空串 = 未分类）",
         "val category: String = \"\"" in dto)

    # ---------- 6. 三个页面的形态（用户那个红框位置） ----------
    c.section("6. 三个页面的抽屉与分类胶囊")
    c.ok("共用件 CategoryDrawer.kt 没被改坏（CategoryDrawerSheet / CategoryTriggerChip / 管理分类那格都还在）",
         "fun CategoryDrawerSheet(" in read(DRAWER)
         and "fun CategoryTriggerChip(" in read(DRAWER)
         and "item(key = \"manage\")" in read(DRAWER))
    pages = [("账户管理", ACCOUNT), ("司机/货主/批发商", USERS), ("车辆管理", VEHICLE)]
    for name, p in pages:
        src = read(p) if p.exists() else ""
        c.ok(f"{name}：页面被 ModalNavigationDrawer 包住（⛔ 不是常驻左栏）",
             "ModalNavigationDrawer(" in src and "ModalDrawerSheet" in src)
        c.ok(f"{name}：抽屉内容用共用件 CategoryDrawerSheet(", "CategoryDrawerSheet(" in src)
        c.ok(f"{name}：标题右边那一格是 CategoryTriggerChip（用户画的红框位置）",
             "CategoryTriggerChip(" in src)
        c.ok(f"{name}：抽屉底部那格是「管理分类」", 'manageLabel = "管理分类"' in src)
        c.ok(f"{name}：选中与「管理分类」都先关抽屉", src.count("scope.launch { drawer.close() }") >= 2)
        c.ok(f"{name}：抽屉那几格一个条数都不显示（用户 2026-09-19 的裁定）",
             "CategoryDrawerItem(\"\" + it.name, it.name)" in src.replace("c|", ""))
        c.ok(f"{name}：⛔ 没有把被否掉的常驻左栏 MasterRail 引进来", "MasterRail(" not in src)
        c.ok(f"{name}：分类管理是同屏第二层（不新开路由）", "managingCategory" in src and "Panel(" in src)
    c.ok("同屏第二层是共用面板（UserCategoriesPanel / VehicleCategoriesPanel 各就各位）",
         "UserCategoriesPanel(" in read(ACCOUNT) and "UserCategoriesPanel(" in read(USERS)
         and "VehicleCategoriesPanel(" in read(VEHICLE))

    # ---------- 7. 三个 VM：分类态与本地过滤 ----------
    c.section("7. 三个 VM：分类态 + 本地过滤")
    for name, p in (("账户管理", ACCOUNT_VM), ("司机/货主/批发商", USERS_VM), ("车辆管理", VEHICLE)):
        src = read(p) if p.exists() else ""
        c.ok(f"{name} VM：有一份分类名（categoryNames）", "categoryNames" in src)
        c.ok(f"{name} VM：选中格是 railKey，且选中的格没了会自愈回「全部」",
             "railKey" in src and 'railKey = ""' in src)
        c.ok(f"{name} VM：筛选是本地过一遍（inRail 共用件，不往返后端）", "inRail(" in src)
        c.ok(f"{name} VM：草稿里有 draftCategory", "draftCategory" in src)
        c.ok(f"{name} VM：读不到名册不吵（静默，左栏只剩「全部」）", "catch (_: Exception)" in src)
    c.ok("账号分类名册的 VM 两个都在共用件文件里派生",
         "class UserCategoriesViewModel" in read(ROSTER_VM)
         and "class VehicleCategoriesViewModel" in read(ROSTER_VM))
    c.ok("名册面板的排序是整份提交（move/up/down 走同一处）", "reorderRows(" in read(ROSTER_VM))

    # ---------- 8. 表单：分类那一格是下拉 ----------
    c.section("8. 三处表单里的分类那一格")
    c.ok("共用件 CategoryPickRow 是下拉（ExposedDropdownMenuBox + FormPickRow），⛔ 不是再套一层弹层",
         "fun CategoryPickRow(" in read(PANEL) and "ExposedDropdownMenuBox(" in read(PANEL)
         and "FormPickRow(" in read(PANEL))
    c.ok("「＋ 新建分类…」在那一格里（建完自动选中）", "新建分类…" in read(PANEL))
    for name, p in (("账户表单", ACCOUNT), ("账号表单（司机/货主/批发商）", USERS), ("车辆表单", VEHICLE)):
        c.ok(f"{name}里有分类那一格", "CategoryPickRow(" in read(p))

    # ---------- 9. 文档与登记 ----------
    c.section("9. 文档三件")
    doc = read(DOC) if DOC.exists() else ""
    c.ok("docs/changes/FEAT-0010.md 存在且九节齐", all(f"## {x}" in doc for x in "①②③④⑤⑥⑦⑧⑨"))
    c.ok("文档里写着半径是 L2（两张表 + 两列 + 两套端点 + 五个页面）", "**L2**" in doc)
    # 同上：只判「FEAT-0010 在不在」的话，把 ID 格改成别的号也还是绿的（链接文字里还有一次）。
    c.ok("变更登记表里有 FEAT-0010 这一行（行首的 ID 格 + 链接那一格）",
         re.search(r"^\| " + chr(96) + "FEAT-0010" + chr(96) + " \| FEAT \|", read(README), re.M) is not None
         and "[FEAT-0010.md](FEAT-0010.md)" in read(README))
    c.ok("AI_WORK_CLAIM.md 里有 FEAT-0010 声明块（标题行里带这个 ID，进行中 / 已完成都算）",
         re.search(r"^### \[2026-10-05 [^\]]*\][^\n]*\*\*FEAT-0010", read(CLAIM), re.M) is not None)

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, detail in c.fails:
            print(f"   - {label}")
            if detail:
                print(f"     {detail}")
        return 1
    print(
        f"✅ 全部 {c.n_ok} 项通过：账号分类 / 车辆分类名册（FEAT-0010）——"
        " 两份全局名册、五个名册页都是胶囊 + 抽屉、三处表单的分类是下拉。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())