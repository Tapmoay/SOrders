# -*- coding: utf-8 -*-
r"""反向验证「地址与联系人三档分类显示 + 左侧抽屉」这条红线**真的会红**（FEAT-0009，2026-10-04）。

## 为什么这条要反向验证
它的判据几乎全是**正向存在性**判据（「必须出现某个零件 / 某句话」），这类判据有三种典型失效方式，
每一种都要单独证明会红 —— 否则那 90 项通过只是「文字还在」，不是「红线在守」：

1. **空转**：文件改名/搬走、函数改名之后判据静默全绿（本脚本把 ensure_route_category、
   createRouteCategoryAndSelect、CategoryManagePanel 逐个改名）。
2. **抽取失效 → 函数体取到空串**：update_category / update_address 这两段是从大文件里截出来的，
   截空之后「级联有没有漏掉回收站」「改线路有没有补名册」全变成空体上恒真。
3. **只扫整个文件、不扫函数体**：create_address 与 update_address 在同一个文件里，
   判据不限定函数体就会被互相顶包（这一条正是本脚本第 ⑲/⑳ 条要证明的）。

外加「静默改事实」那条最隐蔽的路：改名不级联、级联漏掉回收站、删分类不拦挂载、
reorder 不走共用那份整份顺序、迁移偷偷回填、抽屉里偷偷加条数、常驻左栏悄悄回来。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

用法：python _tools/qa/_reverse_verify_route_categories.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / '_tools/qa/_check_route_categories.py'

AND = 'android/app/src/main/java/com/tapmoay/sorders'
BE_MODEL = 'backend/app/models/route_category.py'
BE_SHIPPER_MODEL = 'backend/app/models/shipper.py'
BE_API = 'backend/app/api/v1/route_categories.py'
BE_SHIPPER_API = 'backend/app/api/v1/shipper.py'
BE_SHIPPER_SCHEMA = 'backend/app/schemas/shipper.py'
BE_ROUTER = 'backend/app/api/v1/router.py'
BE_MIG = 'backend/app/migrations/013_route_categories.py'
BE_ENUMS = 'backend/app/models/enums.py'
BE_INIT = 'backend/app/models/__init__.py'
BE_TEST = 'backend/tests/test_route_categories.py'
ADDR_SCREEN = AND + '/ui/shipper/AddressScreen.kt'
ADDR_VM = AND + '/ui/shipper/AddressViewModel.kt'
DRAWER = AND + '/ui/common/CategoryDrawer.kt'

#: (说明, 相对路径, 原文, 替换成, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, str, str, str]] = [
    # ---- 一、后端名册：角色 / 名册形状 / 上限 ----
    (
        '① 角色门跟 shipper.py 不是同一份（司机也能建线路分类）',
        BE_API,
        'require_roles(UserRole.SHIPPER, UserRole.DISPATCHER))]',
        'require_roles(UserRole.SHIPPER, UserRole.DISPATCHER, UserRole.DRIVER))]',
        '角色门与 shipper.py',
    ),
    (
        '② 名册表名被改（真名册与判据说的不是同一张表）',
        BE_MODEL,
        '__tablename__ = "route_categories"',
        '__tablename__ = "route_cat"',
        '名册表名',
    ),
    (
        '③ 唯一约束被改名（同一个货主能有两条同名分类）',
        BE_MODEL,
        'UniqueConstraint("shipper_id", "name", name="uq_route_category_owner_name")',
        'UniqueConstraint("shipper_id", "name", name="uq_route_category_name_dup")',
        '唯一',
    ),
    (
        '④ 名册丢了 sort_order（「整份顺序」那套就没地方落了）',
        BE_MODEL,
        'sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)',
        'sort_order: Mapped[int] = mapped_column(Integer, default=0)',
        'sort_order',
    ),
    (
        '⑤ 上限从 200 悄悄放大（用户点的名册会失控）',
        BE_API,
        'MAX_CATEGORIES = 200',
        'MAX_CATEGORIES = 9999',
        '名册上限',
    ),
    # ---- 二、归属那一格：三处必须逐字同形 ----
    (
        '⑥ 线路那一格的列宽跟联系人/地点不一样（同一套口径被拆成两套）',
        BE_SHIPPER_MODEL,
        'category: Mapped[str] = mapped_column(String(32), default="", index=True)',
        'category: Mapped[str] = mapped_column(String(64), default="", index=True)',
        '逐字同形',
    ),
    # ---- 三、迁移 013 ----
    (
        '⑦ 迁移版本号被改（apply 记录与文件名不同号）',
        BE_MIG,
        'VERSION = 13',
        'VERSION = 12',
        'VERSION',
    ),
    (
        '⑧ 新列丢了 NOT NULL DEFAULT（老线路变成 NULL，空串即未分类那条口径就不成立了）',
        BE_MIG,
        'DDL = "category VARCHAR(32) NOT NULL DEFAULT',
        'DDL = "category VARCHAR(32) DEFAULT',
        '空串',
    ),
    (
        '⑨ 迁移偷偷回填（把老线路按某条规则塞进某个分类）',
        BE_MIG,
        'NAME = "route_categories"',
        'NAME = "UPDATE route_categories"',
        '不回填',
    ),
    (
        '⑩ 迁移里顺手建新表（与 create_all 打两次架）',
        BE_MIG,
        'INDEX_NAME = "ix_shipper_addresses_category"',
        'INDEX_NAME = "ix_shipper_addresses_category"  # CREATE TABLE route_categories',
        '迁移不建新表',
    ),
    # ---- 四、改名级联 / 删除守卫 / 顺序 / 审计 ----
    (
        '⑪ 改名级联漏掉回收站里的行（恢复出来掉进一个不存在的分类）',
        BE_API,
        'ShipperAddress.__table__.update()',
        'ShipperAddress.is_deleted.is_(False) or ShipperAddress.__table__.update()',
        '回收站',
    ),
    (
        '⑫ 还挂着线路也敢删（用户的线路被静默清空分类）',
        BE_API,
        '条线路挂在这个分类下',
        '条记录',
        '还挂着线路就拒绝删',
    ),
    (
        '⑬ reorder 不走共用那份整份顺序校验（丢一格也不报错）',
        BE_API,
        'ordered_ids(by_id, body.ids)',
        'body.ids',
        '整份顺序',
    ),
    (
        '⑭ 三个审计动作码少一个（删分类不留痕）',
        BE_API,
        'OperationAction.ROUTE_CATEGORY_DELETE,',
        'OperationAction.ROUTE_CATEGORY_DELETE_X,',
        '三个写动作',
    ),
    (
        '⑮ ensure_route_category 被改名（自由文本分类不再顺手补进名册）',
        BE_API,
        'def ensure_route_category(db: Session, owner_id: int, name: str) -> RouteCategory | None:',
        'def ensure_route_category_off(db: Session, owner_id: int, name: str) -> RouteCategory | None:',
        '有则用、无则补进名册',
    ),
    # ---- 五、接线 ----
    (
        '⑯ 审计动作码没进枚举（写日志时 AttributeError）',
        BE_ENUMS,
        'ROUTE_CATEGORY_REORDER = "ROUTE_CATEGORY_REORDER"',
        'ROUTE_CATEGORY_REORDER_X = "ROUTE_CATEGORY_REORDER"',
        '审计动作枚举',
    ),
    (
        '⑰ 总路由没挂 route_categories.router（端点是死的）',
        BE_ROUTER,
        'api_router.include_router(route_categories.router)',
        'api_router.include_router(place_categories.router)',
        '总路由挂了',
    ),
    (
        '⑱ 模型包没导出（create_all 建不出这张表）',
        BE_INIT,
        'from app.models.route_category import RouteCategory',
        'from app.models.route_category import RouteCategoryX',
        '模型包导出',
    ),
    (
        '⑲ 建线路时不写分类（选了也白选）',
        BE_SHIPPER_API,
        'category=_clean_category(body.category),',
        'category="",',
        '建线路时把分类写进去',
    ),
    (
        '⑳ 改线路时不补名册（用户手打的新分类名永远不进名册）',
        BE_SHIPPER_API,
        'ensure_route_category(db, current.id, a.category)',
        'None  # 不补名册',
        '改线路时分类可改',
    ),
    (
        '㉑ 线路出参把 category 弄丢（列表里看不出分类）',
        BE_SHIPPER_SCHEMA,
        'category: str = ""',
        'category: str | None = None',
        'AddressCreate / Update / Out',
    ),
    # ---- 六、用例 ----
    (
        '㉒ 用例里连回收站一起改那条断言被删（级联只剩口头承诺）',
        BE_TEST,
        'assert gone.category == new, "回收站里那条没跟着改名（恢复后会掉进一个不存在的分类）"',
        'assert True',
        '改名级联',
    ),
    (
        '㉓ 用例里「1 条」那条断言被删（删除守卫没了行为证据）',
        BE_TEST,
        'assert "1 条" in r.json()["detail"], r.json()["detail"]',
        'assert True',
        '还挂着线路不许删',
    ),
    # ---- 七、Android：三档同形 ----
    (
        '㉔ 页面不再被抽屉包住（回到常驻结构）',
        ADDR_SCREEN,
        'ModalNavigationDrawer(',
        'Column(',
        'ModalNavigationDrawer 包住',
    ),
    (
        '㉕ 抽屉内容不用共用件（各页开始各写一份抽屉）',
        ADDR_SCREEN,
        'CategoryDrawerSheet(',
        'DrawerSheetX(',
        '共用件',
    ),
    (
        '㉖ 三档少一档胶囊（线路/地点/联系人不再同形）',
        ADDR_SCREEN,
        'CategoryTriggerChip(',
        'FolderChipX(',
        '三档各自一个分类胶囊',
    ),
    (
        '㉗ 选中不再写回 rail key（点了没反应）',
        ADDR_SCREEN,
        'vm.routeRailKey = key',
        'vm.routeRailKey = ""',
        '写回三个 rail key',
    ),
    (
        '㉘ 选中不关抽屉（挡着列表，用户还得手滑一次）',
        ADDR_SCREEN,
        'scope.launch { drawer.close() }',
        'Unit',
        '都先关抽屉',
    ),
    (
        '㉙ 常驻左栏 MasterRail 悄悄回来（用户点名否掉的商品管理式布局）',
        ADDR_SCREEN,
        'CategoryManagePanel(',
        'MasterRail(items = emptyList()) CategoryManagePanel(',
        '常驻左栏',
    ),
    (
        '㉚ 列表不再按分类筛（抽屉点了，列表还是全部）',
        ADDR_SCREEN,
        'it.category == routeRailName',
        'true',
        '两个列表的过滤',
    ),
    # ---- 八、线路表单里的分类入口 ----
    (
        '㉛ 线路表单的下拉不再绑 vm.routeCategory（选了不生效）',
        ADDR_SCREEN,
        'value = vm.routeCategory.trim()',
        'value = ""',
        '下拉绑定',
    ),
    (
        '㉜ 线路表单的名册不再带条数（那正是管理面板才需要的影响面）',
        ADDR_SCREEN,
        '条线路）',
        '条）',
        '线路表单里有分类下拉',
    ),
    # ---- 九、ViewModel ----
    (
        '㉝ 编辑时不回填分类（保存是整份回传 ⇒ 分类被静默清掉）',
        ADDR_VM,
        'routeCategory = a.category',
        'routeCategory = ""',
        '回填',
    ),
    (
        '㉞ 保存时不传分类（选了也存不下去）',
        ADDR_VM,
        'category = routeCategory.trim(),',
        'category = "",',
        '保存时把分类一起传上去',
    ),
    (
        '㉟ load() 不拉线路名册（抽屉永远是空的）',
        ADDR_VM,
        'routeCategories = container.repo.routeCategories()',
        'Unit',
        'load() 里拉线路名册',
    ),
    (
        '㊱ 表单里不能当场建分类（用户得先去管理面板绕一圈）',
        ADDR_VM,
        'fun createRouteCategoryAndSelect(',
        'fun createRouteCategoryAndSelectX(',
        '当场建分类并选中',
    ),
    # ---- 十、抽屉零件本身的纪律 ----
    (
        '㊲ 抽屉零件里被塞进条数字段（用户裁定：分组下不显示条数）',
        DRAWER,
        'data class CategoryDrawerItem(val key: String, val label: String)',
        'data class CategoryDrawerItem(val key: String, val label: String, val addressCount: Int)',
        '条数字段',
    ),
    (
        '㊳ 胶囊丢了宽度上限（长分类名把「新增」挤出屏幕）',
        DRAWER,
        'modifier = modifier.widthIn(max = 132.dp),',
        'modifier = modifier.fillMaxWidth(),',
        '宽度上限',
    ),
    (
        '㊴ 胶囊上不再显示「全部」（当前是全部时是个空框）',
        DRAWER,
        'if (current.isBlank()) "全部" else current,',
        'current,',
        '显示「全部」',
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding='utf-8', errors='replace'
    )
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print('❌ 前提不成立：源码完好时这条红线就没过')
        print(out[-1500:])
        return 1
    print('✅ 前提：源码完好时红线是绿的')

    touched = sorted({rel for _l, rel, _o, _n, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, old, new, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        # 按行尾归一后再替换（Windows 上 Kotlin 文件可能是 CRLF），写回时按原样还原
        crlf = b'\r\n' in original_bytes
        plain = original_bytes.decode('utf-8').replace('\r\n', '\n')
        if old not in plain:
            fails.append(label + '：注入没生效（锚点变了，请更新本脚本）')
            print('  [SKIP] ' + label)
            continue
        mutated = plain.replace(old, new, 1)
        try:
            out_txt = mutated
            if crlf:
                out_txt = out_txt.replace('\n', '\r\n')
            path.write_bytes(out_txt.encode('utf-8'))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print('  [OK] ' + label + ' → 报红')
        else:
            fails.append(label + '：注入之后没有按预期报红（退出码 ' + str(code) + '，期望关键词「' + expect + '」）')
            print('  [MISS] ' + label + ' → 仍然全绿')

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append('跑完没逐字节还原：' + '、'.join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print('⚠️  已强制还原：' + '、'.join(dirty))
    else:
        print('✅ 还原检查：' + str(len(touched)) + ' 个被碰过的文件与运行前逐字节一致')

    print('')
    if fails:
        print('❌ 反向验证不通过：')
        for f in fails:
            print('   - ' + f)
        return 1
    print('✅ ' + str(len(CASES)) + ' 条注入都证明这条红线真的在检查。')
    return 0


if __name__ == '__main__':
    sys.exit(main())