# -*- coding: utf-8 -*-
r"""红线：**地址与联系人三档（线路 / 联系人 / 地点）共用一套「分类显示 + 左侧抽屉」** —— FEAT-0009。

## 用户原话（2026-10-04）
> 「干脆给线路联系人以及地点，这3个的界面玩个框了框的位置加一个分类显示，它目前，全部的话，
>  就显示，全部如果是其他分类就显示，其他分类点击这个按钮的时候，它就会弹出一个在左侧来，
>  它这个左侧抽屉左侧抽屉就是我们的那个分类显示，可以去参考账本管理的那些代码**就不要使用那个
>  商品管理的界面了**，商品管理的话，那样子的界面导致了右边的卡片的信息被挤压了不是很好看。」

## 这条为什么必须有机器的判据
1. **三档必须同形。** 用户要的是「路线 / 联系人 / 地址」三个页签在同一个位置长得一模一样；任何一个
   页签漏掉胶囊、或者只有一档把分类画成常驻左栏，肉眼一眼看去是「三个版本」，而它并不会让任何
   现有检查变红 —— 现有判据只盯卡片、表单、删除与撤回，没有一个盯「分类显示」。
2. **线路这一档的分类是**新建的名册**（迁移 013 + 五端点）。名册建了但表单里没有赋值入口，就等于
   名册永远空、功能是死的 —— 所以判据必须同时盯「名册在」与「线路表单里能选/能新建」。
3. **归属那一格是自由文本，不是外键。** `shipper_addresses.category` / `shipper_contacts.category` /
   `shipper_locations.category` 三处逐字同形；谁哪天把某一处改成外键或加了 NOT NULL 之外的约束，
   「改名级联」那条路就会断，而用例只会红一条、看不出是同一套口径被拆了。
4. **改名必须级联到自由文本列，且必须连回收站里的行一起改。** 只改活行 ⇒ 恢复出来的是孤儿分类。
5. **删分类必须挡住「还挂着线路」的那一类。** 悄悄把线路的分类清空，用户看不出数据被改了。
6. **抽屉里不许出现条数。** 用户 2026-09-19 就裁定过「那个分组下面不要显示有多少条啊，这是多余信息」；
   条数只留在管理面板（删之前要看影响面）。这一条最容易被「顺手加个角标」破坏。
7. **不许用商品管理那种常驻左栏。** 用户点名否掉了它（右侧卡片被挤压）。常驻栏与抽屉在源码上
   是两种完全不同的结构，靠人复读机记不住 —— 只能靠判据盯 `MasterRail(` 不在这一屏出现。

R4-BOUNDARY-JUSTIFICATION: 这条判据守的是**本轮自己的施工契约**（三档同形 / 名册与表单入口成对 /
抽屉不带条数），不是对用户的额外承诺，也不是新的产品能力边界。它不新增权限、不改数据模型语义、
不碰任何既有端点的行为 —— 因此按 R4 记录即可，不按 R3 走「能力边界」那一套审批。

用法：python _tools/qa/_check_route_categories.py
     python _tools/qa/_check_route_categories.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ai'))
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / 'android/app/src/main/java/com/tapmoay/sorders'
BE = ROOT / 'backend/app'

BE_MODEL = BE / 'models/route_category.py'
BE_SHIPPER_MODEL = BE / 'models/shipper.py'
BE_SCHEMA = BE / 'schemas/route_category.py'
BE_SHIPPER_SCHEMA = BE / 'schemas/shipper.py'
BE_API = BE / 'api/v1/route_categories.py'
BE_SHIPPER_API = BE / 'api/v1/shipper.py'
BE_ROUTER = BE / 'api/v1/router.py'
BE_MIG = BE / 'migrations/013_route_categories.py'
BE_ENUMS = BE / 'models/enums.py'
BE_INIT = BE / 'models/__init__.py'
BE_TEST = ROOT / 'backend/tests/test_route_categories.py'

ADDR_SCREEN = AND / 'ui/shipper/AddressScreen.kt'
ADDR_VM = AND / 'ui/shipper/AddressViewModel.kt'
CAT_VM = AND / 'ui/dispatcher/RouteCategoriesViewModel.kt'
CAT_SCREEN = AND / 'ui/dispatcher/RouteCategoriesScreen.kt'
DRAWER = AND / 'ui/common/CategoryDrawer.kt'
DTOS = AND / 'data/remote/dto/Dtos.kt'
APIS = AND / 'data/remote/api/Apis.kt'
REPO = AND / 'data/repo/AppRepository.kt'

REVERSE = '_tools/qa/_reverse_verify_route_categories.py'
DOC = ROOT / 'docs/changes/FEAT-0009.md'
REGISTRY = ROOT / 'docs/changes/README.md'
CLAIM = ROOT / 'docs/AI_WORK_CLAIM.md'

MIN_UI_FILES = 100
BODY_FLOOR = 80
CATEGORY_COL = 'category: Mapped[str] = mapped_column(String(32), default="", index=True)'
ROLE_DEP = 'Depends(require_roles(UserRole.SHIPPER, UserRole.DISPATCHER))'
RAIL_KEYS = ('routeRailKey', 'contactRailKey', 'locRailKey')


def read(p: Path) -> str:
    if not p.exists():
        return ''
    return p.read_text(encoding='utf-8')


def code(p: Path) -> str:
    return strip_comments(read(p))


def fn_body(src: str, sig: str) -> str:
    i = src.find(sig)
    if i < 0:
        return ''
    b = src.find('{', i)
    if b < 0:
        return ''
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ''


def py_func(src: str, sig: str) -> str:
    i = src.find(sig)
    if i < 0:
        return ''
    ends = [x for x in (src.find(chr(10) + 'def ', i + 1), src.find(chr(10) + '@router', i + 1)) if x > 0]
    return src[i : min(ends)] if ends else src[i:]


def dto_body(src: str, name: str) -> str:
    i = src.find('data class ' + name + '(')
    if i < 0:
        return ''
    j = src.find(chr(10) + ')', i)
    return src[i:] if j < 0 else src[i : j + 2]


def hits(pat: str, text: str) -> int:
    return len(re.findall(pat, text))


class Checker:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def ok(self, label: str, cond: bool, detail: str = '') -> None:
        if cond:
            self.passed += 1
            print('  [OK] ' + label)
        else:
            self.failed += 1
            print('  [FAIL] ' + label + (('  → ' + detail) if detail else ''))

    def report(self, title: str) -> int:
        print('')
        print('通过 ' + str(self.passed) + ' 项，失败 ' + str(self.failed) + ' 项')
        if self.failed:
            print('❌ ' + title + '：有红线被踩了')
            return 1
        print('✅ ' + title + '：全部 ' + str(self.passed) + ' 项通过')
        return 0


def main() -> int:
    if refuse_if_injecting('线路分类检查'):
        return 1
    c = Checker()
    print('线路分类（FEAT-0009）：三档分类显示 + 左侧抽屉 + 线路分类名册')
    print('')

    # ---------- 0. 反空转 ----------
    ui_files = list(AND.rglob('*.kt'))
    c.ok('Android 界面文件扫到 ' + str(len(ui_files)) + ' 个（≥' + str(MIN_UI_FILES) + '）', len(ui_files) >= MIN_UI_FILES)
    api = read(BE_API)
    mig = read(BE_MIG)
    screen = read(ADDR_SCREEN)
    vm = read(ADDR_VM)
    drawer = read(DRAWER)
    c.ok('后端名册端点文件非空', len(api) > 2000, str(len(api)))
    c.ok('迁移文件非空', len(mig) > 1000, str(len(mig)))
    c.ok('AddressScreen.kt 非空', len(screen) > 30000, str(len(screen)))
    c.ok('分类抽屉零件非空', 3000 < len(drawer) < 12000, str(len(drawer)))
    c.ok('线路表单分段能抽出来（抽取失效 = 一条永远绿的检查）', len(fn_body(screen, 'FormGroup(icon = Icons.Default.Place, title = "终点（必填）"')) > BODY_FLOOR)

    # ---------- 1. 文件都在 ----------
    c.ok('后端七个文件都在', all(p.exists() for p in (BE_MODEL, BE_SCHEMA, BE_API, BE_MIG, BE_TEST, CAT_VM, CAT_SCREEN)), '缺文件')
    c.ok('Android 数据层三个文件都在', all(p.exists() for p in (DTOS, APIS, REPO)))
    c.ok('共用件 ui/common/CategoryDrawer.kt 在', DRAWER.exists())
    c.ok('反向验证脚本在', (ROOT / REVERSE).exists())

    # ---------- 2. 后端模型与归属 ----------
    model = read(BE_MODEL)
    c.ok('名册表名是 route_categories', '__tablename__ = "route_categories"' in model)
    c.ok('(货主, 分类名) 唯一（uq_route_category_owner_name）', 'UniqueConstraint("shipper_id", "name", name="uq_route_category_owner_name")' in model)
    c.ok('名册带 shipper_id 外键并建索引', 'shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)' in model)
    c.ok('名册名 32 字并建索引', 'name: Mapped[str] = mapped_column(String(32), index=True)' in model)
    c.ok('名册带 sort_order（整份顺序）', 'sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)' in model)
    shipper_model = read(BE_SHIPPER_MODEL)
    c.ok('归属那一格在 线路 / 联系人 / 地点 三处逐字同形（恰好 3 处）', hits(re.escape(CATEGORY_COL), shipper_model) == 3, str(hits(re.escape(CATEGORY_COL), shipper_model)))
    c.ok('线路表没有把分类做成外键（仍是自由文本）', 'ForeignKey("route_categories' not in shipper_model)

    # ---------- 3. 迁移 013 ----------
    c.ok('迁移 VERSION = 13', 'VERSION = 13' in mig)
    c.ok('迁移 NAME = route_categories', 'NAME = "route_categories"' in mig)
    c.ok('迁移改的是 shipper_addresses', 'TABLE = "shipper_addresses"' in mig and 'COLUMN = "category"' in mig)
    c.ok('新列 NOT NULL DEFAULT 空串（空串 = 未分类）', 'DDL = "category VARCHAR(32) NOT NULL DEFAULT' in mig)
    c.ok('新列建索引 ix_shipper_addresses_category', 'INDEX_NAME = "ix_shipper_addresses_category"' in mig)
    c.ok('加列与建索引分开判（可重跑）', 'if COLUMN not in have:' in mig and 'if INDEX_NAME not in _indexes(engine):' in mig)
    c.ok('迁移不建新表（新表交给 create_all）', 'CREATE TABLE' not in mig)
    c.ok('迁移不回填任何一行（老线路一律未分类）', 'UPDATE ' not in mig)

    # ---------- 4. 名册端点 ----------
    c.ok('路由前缀 /route-categories 且 tag 同名', 'APIRouter(prefix="/route-categories", tags=["route-categories"])' in api)
    c.ok('角色门与 shipper.py 是同一份（货主 + 派单员）', ROLE_DEP in api and ROLE_DEP in read(BE_SHIPPER_API))
    c.ok('名册上限 200', 'MAX_CATEGORIES = 200' in api)
    c.ok('五个端点齐全（GET / POST / PATCH / reorder / DELETE）', all(s in api for s in ('@router.get(""', '@router.post(""', '@router.patch("/{category_id}"', '@router.post("/reorder"', '@router.delete("/{category_id}"')))
    c.ok('改名的级联是同一事务里的整表 update', 'ShipperAddress.__table__.update()' in api)
    rename = py_func(api, 'def update_category(')
    c.ok('改名级联**连回收站里的行一起改**（不按 is_deleted 过滤）', bool(rename) and 'is_deleted' not in rename)
    dell = py_func(api, 'def delete_category(')
    c.ok('删分类前先数还挂着几条线路', 'ShipperAddress.is_deleted.is_(False)' in dell and 'used' in dell)
    c.ok('还挂着线路就拒绝删，并说清怎么办', '条线路挂在这个分类下' in api and '先把它们改成别的分类' in api)
    c.ok('reorder 走共用那份整份顺序校验', 'ordered_ids(by_id, body.ids)' in api)
    c.ok('三个写动作都写审计日志', all(re.search(r'OperationAction\.' + s + r'\b', api) for s in ('ROUTE_CATEGORY_UPSERT', 'ROUTE_CATEGORY_REORDER', 'ROUTE_CATEGORY_DELETE')))
    ens = py_func(api, 'def ensure_route_category(')
    c.ok('ensure_route_category 是「有则用、无则补进名册」', bool(ens) and 'sort_order' in ens and 'return None' in ens and len(ens) > BODY_FLOOR, str(len(ens)))

    # ---------- 5. 接线 ----------
    enums = read(BE_ENUMS)
    c.ok('审计动作枚举三格都在', all(s in enums for s in ('ROUTE_CATEGORY_UPSERT = "ROUTE_CATEGORY_UPSERT"', 'ROUTE_CATEGORY_DELETE = "ROUTE_CATEGORY_DELETE"', 'ROUTE_CATEGORY_REORDER = "ROUTE_CATEGORY_REORDER"')))
    c.ok('模型包导出了 RouteCategory', re.search(r'^from app\.models\.route_category import RouteCategory$', read(BE_INIT), re.M) is not None and '"RouteCategory",' in read(BE_INIT))
    c.ok('总路由挂了 route_categories.router', 'api_router.include_router(route_categories.router)' in read(BE_ROUTER))
    sch = read(BE_SHIPPER_SCHEMA)
    c.ok('AddressCreate / Update / Out 都带上 category', 'category: str = Field(default="", max_length=32)' in sch and 'category: str | None = Field(None, max_length=32)' in sch and sch.count('category: str = ""') >= 3)
    shipper_api = read(BE_SHIPPER_API)
    create_addr = py_func(shipper_api, 'def create_address(')
    c.ok('建线路时把分类写进去，并顺手补名册', 'category=_clean_category(body.category),' in create_addr and 'ensure_route_category(db, current.id, addr.category)' in create_addr)
    upd = py_func(shipper_api, 'def update_address(')
    c.ok('改线路时分类可改、也要补名册', 'a.category = _clean_category(body.category)' in upd and 'ensure_route_category(db, current.id, a.category)' in upd)
    c.ok('分类名统一走 _clean_category（与联系人/地点同一把尺）', 'def _clean_category(value: str | None) -> str:' in shipper_api)

    # ---------- 6. 用例 ----------
    test = read(BE_TEST)
    c.ok('用例文件有 12 个以上 def test_', hits(r'def test_', test) >= 12, str(hits(r'def test_', test)))
    c.ok('用例钉了改名级联（连回收站里那条一起改）', 'assert gone.category == new' in test)
    c.ok('用例钉了「还挂着线路不许删」（连影响面都说出来）', 'assert "1 条" in r.json()["detail"]' in test)
    c.ok('用例钉了越权（司机进不来 / 别人的名册看不见）', '403' in test and '404' in test)
    c.ok('用例问出了「/shipper/addresses 不是 upsert」这条与联系人不同的纪律', '不是 upsert' in test)

    # ---------- 7. Android 数据层 ----------
    dtos = read(DTOS)
    rb = dto_body(dtos, 'RouteCategoryDto')
    c.ok('RouteCategoryDto 四格（id / name / sortOrder / addressCount）', all(s in rb for s in ('val id: Long', 'val name: String', 'val sortOrder: Int', 'val addressCount: Int')), rb[:200])
    c.ok('名册请求四件套齐全', all(('data class ' + n + '(') in dtos for n in ('RouteCategoryCreateRequest', 'RouteCategoryUpdateRequest', 'RouteCategoryReorderRequest')))
    ad = dto_body(dtos, 'AddressDto')
    c.ok('AddressDto 带回 category', 'val category: String' in ad, ad[:200])
    acr = dto_body(dtos, 'AddressCreateRequest')
    c.ok('AddressCreateRequest 收下 category', 'val category: String' in acr, acr[:200])
    apis = read(APIS)
    c.ok('五个端点都在 Apis.kt', all(s in apis for s in ('@GET("route-categories")', '@POST("route-categories")', '@PATCH("route-categories/{categoryId}")', '@DELETE("route-categories/{categoryId}")', '@POST("route-categories/reorder")')))
    repo = read(REPO)
    c.ok('仓库五个方法都在', all(s in repo for s in ('routeCategories()', 'createRouteCategory(', 'updateRouteCategory(', 'deleteRouteCategory(', 'reorderRouteCategories(')))

    # ---------- 8. 三档同形（本批的正面红线） ----------
    scode = code(ADDR_SCREEN)
    c.ok('页面被 ModalNavigationDrawer 包住（不是常驻左栏）', 'ModalNavigationDrawer(' in scode and 'ModalDrawerSheet' in scode)
    c.ok('抽屉内容用的是共用件 CategoryDrawerSheet(', 'CategoryDrawerSheet(' in scode)
    c.ok('三档各自一个分类胶囊（CategoryTriggerChip 调用 ≥ 3 处）', hits(re.escape('CategoryTriggerChip('), scode) >= 3, str(hits(re.escape('CategoryTriggerChip('), scode)))
    c.ok('抽屉标题随页签切换（线路分类 / 联系人分类 / 地点分类 三句都在）', all(s in scode for s in ('"线路分类"', '"联系人分类"', '"地点分类"')))
    c.ok('选中项写回三个 rail key（三档各一处）', all(('vm.' + k + ' = key') in scode for k in RAIL_KEYS))
    c.ok('选中与「管理分类」都先关抽屉', hits(re.escape('scope.launch { drawer.close() }'), scode) >= 2, str(hits(re.escape('scope.launch'), scode)))
    c.ok('⛔ 常驻左栏 MasterRail( 在这一屏彻底没了', 'MasterRail(' not in scode)
    c.ok('抽屉选中的那一类名从 key 里剥出来（共用一把尺）', 'private fun railCategoryName(key: String)' in scode and 'removePrefix("c|")' in scode)
    c.ok('两个列表的过滤都叠了分类（routeRailName / locRailName 各被用上）', 'routeRailName' in scode and 'locRailName' in scode and hits(r'it.category == ', scode) >= 3, str(hits(r'it\.category == ', scode)))
    c.ok('「管理分类」是同一屏的第二层，不是新路由', 'CategoryManagePanel(' in scode and 'managingCategory' in scode)
    c.ok('第二层三档齐全（Contact / Place / Route 三个 Panel 都接上了）', all(s in scode for s in ('ContactCategoriesPanel(', 'PlaceCategoriesPanel(', 'RouteCategoriesPanel(')))

    # ---------- 9. 线路表单里的分类入口（名册不能是死的） ----------
    c.ok('线路表单里有分类下拉（名册里带条数）', 'label = "分类"' in scode and '条线路）' in scode)
    c.ok('下拉绑定 vm.routeCategory', 'value = vm.routeCategory.trim()' in scode)
    c.ok('下拉能当场新建分类（＋ 新建分类…）', '＋ 新建分类…' in scode and 'vm.createRouteCategoryAndSelect(' in scode)
    c.ok('未选时显示「未分类」而不是空白', 'placeholder = "未分类"' in scode)

    # ---------- 10. ViewModel ----------
    c.ok('三个 rail key 都在 VM 里', all(('var ' + k) in vm for k in RAIL_KEYS))
    c.ok('VM 里存了线路名册', 'routeCategories' in vm and 'RouteCategoryDto' in vm)
    c.ok('openCreate 把分类清空', 'routeCategory = ""' in vm)
    c.ok('openEdit 把分类回填（保存是整份回传，不回填就静默清掉）', 'routeCategory = a.category' in vm)
    c.ok('保存时把分类一起传上去', 'category = routeCategory.trim(),' in vm)
    c.ok('load() 里拉线路名册', 'routeCategories = container.repo.routeCategories()' in fn_body(vm, 'fun load()'))
    c.ok('管理面板返回后回读名册（reloadRouteCategories / reloadPlaceCategories 都在）', 'fun reloadRouteCategories()' in vm and 'fun reloadPlaceCategories()' in vm)
    c.ok('表单里能当场建分类并选中', 'fun createRouteCategoryAndSelect(' in vm)

    # ---------- 11. 抽屉零件本身的纪律 ----------
    dcode = code(DRAWER)
    c.ok('零件只认一套 key 约定（空串 = 全部 / c| 名）', '"c|" + it.name' in read(ADDR_SCREEN) or '"c|" + c.name' in read(ADDR_SCREEN))
    c.ok('⛔ 抽屉零件里没有任何条数字段（用户裁定：分组下不显示条数）', not any(s in drawer for s in ('addressCount', 'locationCount', 'contactCount', 'productCount')))
    c.ok('胶囊上的当前分类空 → 显示「全部」', 'if (current.isBlank()) "全部" else current' in dcode)
    c.ok('胶囊有宽度上限（长分类名不许把「新增」挤出去）', 'widthIn(max = 132.dp)' in dcode)
    c.ok('抽屉行高 48dp + 选中打勾', 'height(48.dp)' in dcode and 'Icons.Default.Check' in dcode)
    c.ok('抽屉最后一行是动作行（管理分类）', 'onManage' in dcode and 'Icons.Default.Settings' in dcode)

    # ---------- 12. 文档与登记 ----------
    doc = read(DOC)
    c.ok('变更文档 FEAT-0009.md 在', DOC.exists())
    c.ok('九个编号小节齐全', all(('## ' + s) in doc for s in ('①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨')))
    c.ok('文档里记着用户原话', '干脆给线路联系人以及地点' in doc)
    c.ok('文档写了 Blast Radius', 'Blast Radius' in doc and re.search(r'L[0-3]', doc) is not None)
    c.ok('登记簿有 FEAT-0009 那一行', 'FEAT-0009' in read(REGISTRY))
    c.ok('工作声明页有 FEAT-0009 的声明块', 'FEAT-0009' in read(CLAIM))

    return c.report('线路分类（FEAT-0009）')


if __name__ == '__main__':
    if '--list' in sys.argv:
        print('线路分类（FEAT-0009）：三档分类显示 + 左侧抽屉 + 线路分类名册')
        sys.exit(0)
    sys.exit(main())