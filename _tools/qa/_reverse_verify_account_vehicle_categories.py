"""_reverse_verify_account_vehicle_categories.py —— FEAT-0010 的反向验证（破坏性注入）。

## 为什么必须有它

`_tools/qa/_check_account_vehicle_categories.py` 是**静态**判据：它只读源码与文档。
静态判据最大的风险是"看着在管、其实永远绿"（本仓库栽过：判据断言写成了永远成立的形式）。
所以每一条重要断言都要拿一次**真的破坏**去撞它：把源码改坏一处、跑判据、
必须看到对应的那一行变红，然后按字节还原。

## 手法

每条 = (说明, 相对路径, 锚点原文, 替换成, 期望标签)。锚点必须**唯一**（`re.subn(count=1)`），
`re:` 前缀 = 正则锚点（文档类的注入要用它，因为归档提交会改状态那几格）。
期望标签以 `~` 开头 = 判据输出里**任意**一条 `[!!]` 行包含这个子串即可（参数化标签用）。
跑的时候**不许**并发跑别的判据（注入是临时写进源码的）。

配套：python _tools/qa/_check_account_vehicle_categories.py（**55** 种破坏方式全被抓）

用法：

    python _tools/qa/_reverse_verify_account_vehicle_categories.py --list
    python _tools/qa/_reverse_verify_account_vehicle_categories.py

R4-BOUNDARY-JUSTIFICATION: 本脚本只读写工作区文件（临时注入后按字节还原），不连库、不起服务、
不调外部接口；它验证的对象是本事项自己的判据，属于测试工具（Infrastructure），不碰业务核心。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_account_vehicle_categories.py"

A = "android/app/src/main/java/com/tapmoay/sorders/"
BE = "backend/app/"
UMODEL = BE + "models/user_category.py"
VMODEL = BE + "models/vehicle_category.py"
MINIT = BE + "models/__init__.py"
UMODELUSER = BE + "models/user.py"
VMODELVEH = BE + "models/vehicle.py"
MIG14 = BE + "migrations/014_user_categories.py"
MIG15 = BE + "migrations/015_vehicle_categories.py"
ROUTER = BE + "api/v1/router.py"
UAPI = BE + "api/v1/user_categories.py"
VAPI = BE + "api/v1/vehicle_categories.py"
USERS = BE + "api/v1/users.py"
VEHICLES = BE + "api/v1/vehicles.py"
ENUMS = BE + "models/enums.py"
COV = BE + "core/capability_audit_coverage.py"
DTO = A + "data/remote/dto/Dtos.kt"
API = A + "data/remote/api/Apis.kt"
REPO = A + "data/repo/AppRepository.kt"
ROSTER_VM = A + "ui/dispatcher/CategoryRostersViewModel.kt"
PANEL = A + "ui/dispatcher/CategoryRostersPanel.kt"
DRAWER = A + "ui/common/CategoryDrawer.kt"
ACC = A + "ui/dispatcher/AccountManageScreen.kt"
USR = A + "ui/dispatcher/UsersManageScreen.kt"
VEH = A + "ui/dispatcher/VehicleManageScreen.kt"
ACC_VM = A + "ui/dispatcher/AccountManageViewModel.kt"
DOC = "docs/changes/FEAT-0010.md"
README = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"

INJECTIONS: list[tuple[str, str, str, str, str]] = [
    # ---- 名册表与归属列 ----
    ("① 名册表名被改掉：create_all 建出来的就不是判据认识的那张表了",
     UMODEL, '__tablename__ = "user_categories"', '__tablename__ = "user_category"',
     "~两张名册表都建在模型里"),
    ("② 车辆名册表名被改掉", VMODEL, '__tablename__ = "vehicle_categories"',
     '__tablename__ = "vehicle_category"', "~两张名册表都建在模型里"),
    ("③ 重导出被拿掉：表在模型里、create_all 却看不到它（本仓库踩过的坑）",
     MINIT, '"UserCategory",', '"UserCategoryHidden",', "~两张名册都重导出进 models/__init__.py"),
    ("④ 账号那一列被收窄：与自由文本口径不一致", UMODELUSER,
     'category: Mapped[str] = mapped_column(String(32), default="", index=True)',
     'category: Mapped[str] = mapped_column(String(16), default="", index=True)',
     "~账号那一列按共用口径声明"),
    ("⑤ 车辆那一列被收窄", VMODELVEH,
     'category: Mapped[str] = mapped_column(String(32), default="", index=True)',
     'category: Mapped[str] = mapped_column(String(16), default="", index=True)',
     "~车辆那一列按共用口径声明"),
    # ---- 迁移 ----
    ("⑥ 014 改错了表：users 那一列跑到别的表上去了", MIG14,
     'TABLE = "users"', 'TABLE = "accounts"', "~014 管的是 users"),
    ("⑦ 015 改错了表", MIG15, 'TABLE = "vehicles"', 'TABLE = "cars"', "~015 管的是 vehicles"),
    ("⑧ 014 的列定义丢了默认值（老库会多出一列 NULL）", MIG14,
     'DDL = "category VARCHAR(32) NOT NULL DEFAULT', 'DDL = "category VARCHAR(32)',
     "~014 的列定义是 NOT NULL DEFAULT"),
    ("⑨ 015 的列定义丢了默认值", MIG15,
     'DDL = "category VARCHAR(32) NOT NULL DEFAULT', 'DDL = "category VARCHAR(32)',
     "~015 的列定义是 NOT NULL DEFAULT"),
    ("⑩ 014 不再建索引（老库上左栏筛选要全表扫）", MIG14,
     'conn.execute(text(f"CREATE INDEX {INDEX_NAME} ON {TABLE} ({COLUMN})"))', "pass",
     "~014 加列与建索引分开判"),
    ("⑪ 015 不再建索引", MIG15,
     'conn.execute(text(f"CREATE INDEX {INDEX_NAME} ON {TABLE} ({COLUMN})"))', "pass",
     "~015 加列与建索引分开判"),
    ("⑫ 迁移里顺手建表了（新表只能由 create_all 建）", MIG14,
     'INDEX_NAME = "ix_users_category"',
     'INDEX_NAME = "ix_users_category"\nCREATE_STRAY = "CREATE TABLE user_categories (id INT)"',
     "~014 不建表"),
    ("⑬ 迁移里回填了老数据（谁属于哪一类没人能证明）", MIG15,
     'INDEX_NAME = "ix_vehicles_category"',
     'INDEX_NAME = "ix_vehicles_category"\nBACKFILL = "UPDATE vehicles SET category = '' WHERE 1=1"',
     "~015 不回填老数据"),
    # ---- 端点 ----
    ("⑭ 账号名册的 prefix 被改掉（App 与 AI 目录里的路径就全对不上了）", UAPI,
     'prefix="/user-categories"', 'prefix="/ucats"', "~账号名册的 prefix 是 /user-categories"),
    ("⑮ 车辆名册的 prefix 被改掉", VAPI, 'prefix="/vehicle-categories"', 'prefix="/vcats"',
     "~车辆名册的 prefix 是 /vehicle-categories"),
    ("⑯ 少了 reorder 端点（排序提交没地方去）", UAPI, '@router.post("/reorder", response_model=list[UserCategoryOut])', '@router.post("/sort", response_model=list[UserCategoryOut])',
     "~账号名册五个端点齐"),
    ("⑰ 车辆名册少了 reorder 端点", VAPI, '@router.post("/reorder", response_model=list[VehicleCategoryOut])', '@router.post("/sort", response_model=list[VehicleCategoryOut])',
     "~车辆名册五个端点齐"),
    ("⑱ 账号名册有个写端点没走权限点（登录就能改名册）", UAPI,
     "re:@router\\.delete\\([\\s\\S]{0,240}?require_permission\\(Permission\\.USER_MANAGE\\)\\)",
     "current: CurrentUser", "~账号名册四个写端点都走 require_permission"),
    ("⑲ 车辆名册有个写端点没走权限点", VAPI,
     "re:@router\\.delete\\([\\s\\S]{0,240}?require_permission\\(Permission\\.USER_MANAGE\\)\\)",
     "current: CurrentUser", "~车辆名册四个写端点都走 require_permission"),
    ("⑳ 账号名册的排序不整份提交了（少了的那几行会被悄悄漏掉）", UAPI,
     "ordered_ids(by_id, body.ids)", "body.ids", "~账号名册排序走唯一的 ordered_ids"),
    ("㉑ 车辆名册的排序不整份提交了", VAPI, "ordered_ids(by_id, body.ids)", "body.ids",
     "~车辆名册排序走唯一的 ordered_ids"),
    ("㉒ 账号名册少写一条审计日志（改名不留痕）", UAPI, "re:write_log\\([\\s\\S]*write_log\\(", "write_logX(",
     "~账号名册三个写动作都写审计日志"),
    ("㉓ 车辆名册少写一条审计日志", VAPI, "re:write_log\\([\\s\\S]*write_log\\(", "write_logX(",
     "~车辆名册三个写动作都写审计日志"),
    ("㉔ 账号的「在用」口径丢掉了回收站排除（账号删光了分类还删不掉）", UAPI,
     "has_del_suffix(", "has_del_suffixX(", "账号名册数「在用」时排除回收站"),
    ("㉕ 两个名册里有一个没在 router 注册（接口根本不存在）", ROUTER,
     "api_router.include_router(user_categories.router)",
     "# api_router.include_router(user_categories.router)", "两个名册都在 router.py 注册了"),
    ("㉖ 另一个也没注册", ROUTER, "api_router.include_router(vehicle_categories.router)",
     "# api_router.include_router(vehicle_categories.router)", "两个名册都在 router.py 注册了"),
    # ---- 审计与自动补名册 ----
    ("㉗ 审计动作码被改名（审计页上这条就说不清了）", ENUMS,
     'USER_CATEGORY_UPSERT = "USER_CATEGORY_UPSERT"', 'USER_CATEGORY_UP = "USER_CATEGORY_UP"',
     "~动作码 USER_CATEGORY_UPSERT 在 enums 里"),
    ("㉘ 新的六个码没有认领（审计覆盖表里说不清归属）", COV, "'USER_CATEGORY_UPSERT',",
     "'USER_CATEGORY_UPSERT_X',", "六个新动作码在审计覆盖表里被认领"),
    ("㉙ 建号时不再把新分类名补进名册（派单员要多做一步）", USERS,
     "re:ensure_user_category\\(db, u\\.category\\)[\\s\\S]*ensure_user_category\\(db, u\\.category\\)", "pass",
     "账号/车辆建号建车时会顺手把新分类名补进名册"),
    ("㉚ 建车时不再补名册", VEHICLES, "ensure_vehicle_category(db, v.category)", "pass",
     "账号/车辆建号建车时会顺手把新分类名补进名册"),
    # ---- 安卓数据层 ----
    ("㉛ 账号名册的 DTO 改名（数据层与后端对不上）", DTO, "data class UserCategoryDto(",
     "data class UserCategoryDtoX(", "~UserCategoryDto 在 Dtos.kt 里"),
    ("㉜ 条数字段与后端不一致（面板上的「N 个账号」永远是 0）", DTO,
     '@SerialName("user_count")', '@SerialName("users_count")',
     "两份名册的条数字段名与后端一致"),
    ("㉝ 账号名册的读端点没进 Apis.kt", API, '@GET("user-categories")', '@GET("user-categories-x")',
     "~的五个端点都在 Apis.kt 里"),
    ("㉞ 车辆名册的读端点没进 Apis.kt", API, '@GET("vehicle-categories")', '@GET("vehicle-categories-x")',
     "~的五个端点都在 Apis.kt 里"),
    ("㉟ 仓库少了账号名册入口", REPO, "suspend fun userCategories(", "suspend fun userCategoriesX(",
     "~AppRepository.userCategories() 在"),
    ("㊱ 仓库少了车辆名册入口", REPO, "suspend fun vehicleCategories(", "suspend fun vehicleCategoriesX(",
     "~AppRepository.vehicleCategories() 在"),
    # ---- 安卓页面形态 ----
    ("㊲ 共用抽屉件被改坏（CategoryTriggerChip 没了，五页一起塌）", DRAWER,
     "fun CategoryTriggerChip(", "fun CategoryTriggerChipX(",
     "共用件 CategoryDrawer.kt 没被改坏"),
    ("㊳ 账户管理页不再是抽屉（变回光秃秃一个列表）", ACC, "ModalNavigationDrawer(",
     "ModalNavigationDrawerX(", "~页面被 ModalNavigationDrawer 包住"),
    ("㊴ 司机管理页不再是抽屉", USR, "ModalNavigationDrawer(", "ModalNavigationDrawerX(",
     "~页面被 ModalNavigationDrawer 包住"),
    ("㊵ 车辆管理页不再是抽屉", VEH, "ModalNavigationDrawer(", "ModalNavigationDrawerX(",
     "~页面被 ModalNavigationDrawer 包住"),
    ("㊶ 车辆管理页标题右边那一格没了（用户画的红框位置）", VEH, "CategoryTriggerChip(",
     "CategoryTriggerChipX(", "~标题右边那一格是 CategoryTriggerChip"),
    ("㊷ 抽屉底部那格不叫「管理分类」了（用户要的那一句）", ACC, 'manageLabel = "管理分类"',
     'manageLabel = "分类管理"', "~抽屉底部那格是「管理分类」"),
    ("㊸ 选中分类后不关抽屉（菜单一直压在列表上）", ACC,
     "                    onManage = {\n                        managingCategory = true\n                        scope.launch { drawer.close() }\n                    },",
     "                    onManage = {\n                        managingCategory = true\n                    },",
     "~选中与「管理分类」都先关抽屉"),
    ("㊹ 商品管理那种常驻左栏又被引进来了（用户否过）", ACC,
     "val drawer = rememberDrawerState(DrawerValue.Closed)",
     "val drawer = rememberDrawerState(DrawerValue.Closed)\n    MasterRail(listOf(), \"\", {})",
     "~⛔ 没有把被否掉的常驻左栏 MasterRail 引进来"),
    ("㊺ 名册面板不再是同屏第二层（挂一个不存在的东西）", ACC, "UserCategoriesPanel(",
     "UserCategoriesPanelX(", "~同屏第二层是共用面板"),
    ("㊻ VM 里选中格坏掉后不再自愈（左栏停在一个已经删掉的分组上）", ACC_VM,
     'railKey = ""', "railKey = railKey",
     "~选中格是 railKey，且选中的格没了会自愈回「全部」"),
    ("㊼ VM 不再本地过滤（每点一格都要往返后端）", ACC_VM, "inRail(", "inRailX(",
     "~筛选是本地过一遍（inRail 共用件，不往返后端）"),
    ("㊽ 名册面板的排序不再整份提交", ROSTER_VM, "re:reorderRows\\([\\s\\S]*reorderRows\\([\\s\\S]*reorderRows\\([\\s\\S]*reorderRows\\(", "reorderRowsX(",
     "名册面板的排序是整份提交"),
    ("㊾ 表单里的分类不再是下拉（又变回自己写的一格）", PANEL, "ExposedDropdownMenuBox",
     "ExposedDropdownMenuBoxX",
     "共用件 CategoryPickRow 是下拉（ExposedDropdownMenuBox + FormPickRow），⛔ 不是再套一层弹层"),
    ("㊿ 「＋ 新建分类…」那一格没了（现场建分类这件事做不了）", PANEL, "re:新建分类…[\\s\\S]*新建分类…", "新建分类",
     "~「＋ 新建分类…」在那一格里"),
    ("51 车辆表单里那一格分类没了", VEH, "CategoryPickRow(", "CategoryPickRowX(",
     "~里有分类那一格"),
    # ---- 文档三件 ----
    ("52 事项文档少了一节", DOC, "## ⑨", "## 九", "docs/changes/FEAT-0010.md 存在且九节齐"),
    ("53 文档里的半径写错了", DOC, "re:\\*\\*L2\\*\\*[\\s\\S]*\\*\\*L2\\*\\*", "**L1**", "~文档里写着半径是 L2"),
    ("54 登记表里没有这一行", README,
     "re:\\| `FEAT-0010` \\| FEAT \\|", "| `FEAT-001X` | FEAT |",
     "变更登记表里有 FEAT-0010 这一行"),
    ("55 声明页里没有这一块", CLAIM,
     "re:### \\[2026-10-05 [^\\]]*\\][^\\n]*\\*\\*FEAT-0010", "### [2026-10-05 进行中] 会话：**FEAT-001X",
     "AI_WORK_CLAIM.md 里有 FEAT-0010 声明块"),
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def run_check() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列出破坏方式，不动文件")
    args = ap.parse_args()
    if args.list:
        for i, (name, rel, old, _new, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}")
            print(f"      {rel}   ← 期望被「{want}」抓到")
        return 0

    code, out = run_check()
    if code != 0:
        print("❌ 现在就是红的，先修好再跑反向验证：")
        print(out[-2000:])
        return 2

    caught = 0
    missed: list[str] = []
    for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
        path = ROOT / rel
        if not path.exists():
            print(f"{i:>2}. ⛔ 目标文件不存在：{rel}")
            missed.append(name)
            continue
        raw = path.read_bytes()
        orig_sha = sha(raw)
        text = raw.decode("utf-8")
        eol = "\r\n" if "\r\n" in text else "\n"
        old_s = old.replace("\n", eol)
        new_s = new.replace("\n", eol)
        pat = old_s[3:] if old_s.startswith("re:") else re.escape(old_s)
        injected, n = re.subn(pat, new_s, text, count=1)
        if n != 1:
            print(f"{i:>2}. ❌ 锚点没命中，跳过（注入点腐烂了）：{name}")
            missed.append(name)
            continue
        path.write_text(injected, encoding="utf-8", newline="")
        try:
            _code, out2 = run_check()
        finally:
            now = path.read_bytes()
            if sha(now) != sha(injected.encode("utf-8")):
                print(f"🛑 有别的东西改了 {rel}，拒绝还原（请人工检查）")
                return 2
            path.write_bytes(raw)
            if sha(path.read_bytes()) != orig_sha:
                print(f"🛑 {rel} 没还原干净")
                return 2
        # 注意 「~」 的语义是「任意一条 [!!] 行**包含**这个子串」——不能写成
        # f"[!!]   {want[1:]}" in out2：参数化标签（f"{name}：…"）的 [!!] 行里，
        # 子串前面还有「账户管理：」这种前缀，拼前缀就永远匹配不上（第一版就栽在这里）。
        if want.startswith("~"):
            hit = any("[!!]" in ln and want[1:] in ln for ln in out2.splitlines())
        else:
            hit = any("[!!]" in ln and want in ln for ln in out2.splitlines())
        if hit:
            caught += 1
            print(f"{i:>2}. ✅ {name}")
        else:
            missed.append(name)
            print(f"{i:>2}. ❌ 红线居然还是绿的：{name}  ← 期望「{want}」")

    print()
    print(f"{caught}/{len(INJECTIONS)} 种破坏方式被抓住")
    if missed:
        print("漏网的：")
        for name in missed:
            print(f"   - {name}")
        return 1
    print("✅ 全部注入都被抓住，且每个文件都按字节还原")
    return 0


if __name__ == "__main__":
    sys.exit(main())