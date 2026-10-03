# -*- coding: utf-8 -*-
r"""反向验证「联系人分类（左分类右列表）」这条红线**真的会红**（FEAT-0007，2026-10-03）。

## 为什么这条要反向验证
它的判据大多是「某段代码里必须出现某个零件」这类**正向存在性**判据，这类判据有三种典型失效方式，
每一种都必须被单独证明会红：

1. **判据变成空转**：目标被改名/搬走之后判据静默全绿。本脚本把角色门、级联、守卫逐个改坏。
2. **抽取失效 → 类体/函数体取到空串**：两个类体、ContactCategoryPane 面板体、update_contact 函数体
   都是从大文件里截出来的，截空之后「有没有那一列」「是不是外键」全变成空体上恒真。
   本脚本把列宽改掉、把左栏塞进条数。
3. **只扫整个文件、不扫函数体**：upsert 与 update 在同一个文件里，判据不限定函数体就会被互相顶包。

外加「静默改事实」那条最隐蔽的路：改名不级联、delete 不拦挂载、级联把回收站漏掉、
upsert 顺手把没选的分类抹成空、迁移偷偷回填、影响面把回收站算进去。

另有三条打「接线义务」：新审计动作码没被能力认领、能力 gate 行号漂移、AI 侧读目录丢了。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

用法：python _tools/qa/_reverse_verify_contact_categories.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_contact_categories.py"

AND = "android/app/src/main/java/com/tapmoay/sorders"
BE_API = "backend/app/api/v1/contact_categories.py"
BE_SHIPPER_API = "backend/app/api/v1/shipper.py"
BE_MIG = "backend/app/migrations/012_contact_categories.py"
BE_PLACE_MODEL = "backend/app/models/place_category.py"
BE_CAP = "backend/app/core/capability_audit_coverage.py"
BE_ROLE_CAPS = "backend/app/core/role_capabilities.py"
BE_TEST = "backend/tests/test_contact_categories.py"
ADDR_SCREEN = AND + "/ui/shipper/AddressScreen.kt"
ADDR_VM = AND + "/ui/shipper/AddressViewModel.kt"
CAT_VM = AND + "/ui/dispatcher/ContactCategoriesViewModel.kt"
DTOS = AND + "/data/remote/dto/Dtos.kt"
AI_WRITE = AND + "/ai/AiWrite.kt"
AI_RES = AND + "/ai/AiResources.kt"
AI_REVERT = AND + "/ai/AiRevert.kt"
AI_READ = AND + "/ai/AiReadCatalog.kt"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    # ---- 一、后端：角色 / 守卫 / 级联 / 顺序 / 动作码 ----
    (
        "① 角色门跟 shipper.py 不是同一份（货主能建联系人、却建不了分类）",
        BE_API,
        lambda s: s.replace(
            "require_roles(UserRole.SHIPPER, UserRole.DISPATCHER))]",
            "require_roles(UserRole.SHIPPER, UserRole.DISPATCHER, UserRole.DRIVER))]",
            1,
        ),
        "两边的角色集不一样",
    ),
    (
        "② 删除不拦挂载（点一下就把十几位联系人静默变成未分类）",
        BE_API,
        lambda s: s.replace("位联系人挂在这个分类下", "分类还在用", 1),
        "删除守卫没了",
    ),
    (
        "③ 改名不级联（联系人挂着一个已经不存在的分类名）",
        BE_API,
        lambda s: s.replace("ShipperContact.__table__.update()", "ShipperContact.__table__.select()", 1),
        "改名没级联",
    ),
    (
        "④ 级联把回收站漏掉（恢复出来的那条挂着一个不存在的分类）",
        BE_API,
        lambda s: s.replace(
            ".where(ShipperContact.shipper_id == current.id, ShipperContact.category == old_name)",
            ".where("
            "ShipperContact.shipper_id == current.id, "
            "ShipperContact.category == old_name, "
            "ShipperContact.is_deleted.is_(False))",
            1,
        ),
        "不过滤软删",
    ),
    (
        "⑤ 顺序校验自己写了一套（只传一半也能过）",
        BE_API,
        lambda s: s.replace("ids = ordered_ids(by_id, body.ids)", "ids = body.ids", 1),
        "顺序校验自己写了一套",
    ),
    (
        "⑥ 动作码写串成地点那三个（审计里两条链路混在一起）",
        BE_API,
        lambda s: s.replace(
            "OperationAction.CONTACT_CATEGORY_UPSERT", "OperationAction.PLACE_CATEGORY_UPSERT", 1
        ),
        "写串了动作码",
    ),
    (
        "⑦ 名册行数上限被抬高（那条边界再也守不住）",
        BE_API,
        lambda s: s.replace("MAX_CATEGORIES = 200", "MAX_CATEGORIES = 20000", 1),
        "上限被删/改了",
    ),
    (
        "⑧ 影响面把回收站里的联系人也算进去（用户因为一个看不见的人删不掉分类）",
        BE_API,
        lambda s: s.replace("is_deleted.is_(False)", "is_deleted.is_(True)"),
        "把回收站里的也算进去了",
    ),
    (
        "⑨ 建联系人时不再顺手把分类补进名册",
        BE_SHIPPER_API,
        lambda s: s.replace("ensure_contact_category(db, current.id, category)", "pass", 1),
        "两处都顺手补名册",
    ),
    (
        "⑩ PATCH 丢掉 None 三档语义（改个称呼顺手把分类清掉）",
        BE_SHIPPER_API,
        # ⚠️ FEAT-0009：`if body.category is not None:` 在这份文件里已经出现了 3 处（地址/联系人/地点），
        #    直接 replace(..., 1) 会命中**地址**那一处 —— 联系人这半条线判据照样绿，注入等于白打。
        #    锚点带上紧邻的那行注释，把它钉死在 update_contact 里。
        lambda s: s.replace(
            "    # FEAT-0007：分类 —— `None` = 不改；**空串 = 明确清成未分类**（界面上把分类清空再保存）。\n"
            "    if body.category is not None:",
            "    if body.category:",
            1,
        ),
        "PATCH 走三档语义",
    ),
    # ---- 二、迁移 012 ----
    (
        "⑪ 迁移列宽与模型不一致（MySQL 上会截断）",
        BE_MIG,
        lambda s: s.replace("VARCHAR(32) NOT NULL DEFAULT", "VARCHAR(16) NOT NULL DEFAULT", 1),
        "列定义与模型不一致",
    ),
    (
        "⑫ 迁移偷偷回填老数据（替用户猜这一位是「老客户」还是「司机」）",
        BE_MIG,
        lambda s: s.replace(
            "def upgrade(engine", "# UPDATE 老数据：全塞进「老客户」\ndef upgrade(engine", 1
        ),
        "迁移体里出现了 UPDATE",
    ),
    (
        "⑬ 迁移里自己建表（与 create_all 撞车：同一件事两边都写了）",
        BE_MIG,
        lambda s: s.replace(
            'COLUMN = "category"', 'COLUMN = "category"\n_SQL = "CREATE TABLE contact_categories (id INT)"', 1
        ),
        "迁移里出现了 CREATE TABLE",
    ),
    (
        "⑭ 迁移少了存在性判断（第二次 upgrade 就炸）",
        BE_MIG,
        lambda s: s.replace("if COLUMN not in have:", "if True:", 1),
        "少了存在性判断",
    ),
    # ---- 三、名册归属 / 两套名册分开 ----
    (
        "⑮ 给 place_categories 加上 kind 列（合表：每次增删改都要判 kind）",
        BE_PLACE_MODEL,
        lambda s: s.replace(
            "class PlaceCategory(Base, TimestampMixin):",
            'class PlaceCategory(Base, TimestampMixin):\n    kind = Column(String(8), default="place")',
            1,
        ),
        "地点分类名册上出现了 kind",
    ),
    # ---- 四、接线义务：能力 / gate / 读目录 ----
    (
        "⑯ 三个新审计动作码没被能力认领（_check_capability_unification 会算成孤儿）",
        BE_CAP,
        lambda s: s.replace(
            "'address:manage': ('CONTACT_CATEGORY_UPSERT', 'CONTACT_CATEGORY_DELETE', "
            "'CONTACT_CATEGORY_REORDER',",
            "'address:manage': (",
            1,
        ),
        "没认领",
    ),
    (
        "⑰ 能力 gate 行号漂到没有角色门的那一行",
        BE_ROLE_CAPS,
        lambda s: s.replace("gate='backend/app/api/v1/shipper.py:32'", "gate='backend/app/api/v1/shipper.py:29'", 1),
        "gate 行号",
    ),
    (
        "⑱ AI 读目录里丢了联系人分类名册（想重排却读不到当前顺序）",
        AI_READ,
        lambda s: s.replace("contact_categories.list_categories", "contact_categories.list_X", 1),
        "读目录里没有它",
    ),
    # ---- 五、Android：左栏 / 筛选 / 自愈 / 回填 / 路由形态 ----
    (
        "⑲ 左栏那一格又显示条数（用户 2026-09-19 点名的「多余信息」）",
        ADDR_SCREEN,
        # ⚠️ FEAT-0009：左栏搬成了标题行胶囊 + 左侧抽屉，那一格现在叫 `CategoryDrawerItem`。
        #    锚点必须带上 `vm.contactCategories`：三档的抽屉都用同一个零件，只按零件名注入会打到线路档。
        lambda s: s.replace(
            'vm.contactCategories.map { CategoryDrawerItem("c|" + it.name, it.name) }',
            'vm.contactCategories.map { CategoryDrawerItem("c|" + it.name, it.name + it.contactCount) }',
            1,
        ),
        "没有条数",
    ),
    (
        "⑳ 右栏不再按分类名筛（左栏点了没反应）",
        ADDR_SCREEN,
        lambda s: s.replace("it.category == railName", "true", 1),
        "右栏没接上分类过滤",
    ),
    (
        "㉑ 左栏少了「管理分类」那一格（第二层进不去）",
        ADDR_SCREEN,
        # ⚠️ FEAT-0009：管理入口现在是抽屉最后一行（`manageLabel = "管理分类"`），不再是 RailItem。
        lambda s: s.replace('manageLabel = "管理分类"', 'manageLabel = "分类管理"', 1),
        "管理入口没了",
    ),
    (
        "㉒ 选中格失效不自愈（名册改名后用户看到「这个分类是空的」）",
        ADDR_VM,
        lambda s: s.replace(
            '            if (contactRailKey.startsWith("c|") &&\n'
            '                contactCategories.none { "c|" + it.name == contactRailKey }\n'
            '            ) contactRailKey = ""',
            '            if (contactRailKey.isEmpty()) contactRailKey = ""',
            1,
        ),
        "少了自愈",
    ),
    (
        "㉓ 打开联系人编辑时不回填分类（改个称呼顺手把分类清掉）",
        ADDR_VM,
        lambda s: s.replace('contactCategory = c?.category ?: ""', 'contactCategory = ""', 1),
        "openContactDialog 里没有回填",
    ),
    (
        "㉔ 名册页的「拖动即提交」不走共用草稿态",
        CAT_VM,
        lambda s: s.replace("submittableIds(", "submittableIdsX(", 1),
        "名册页的提交没走共用件",
    ),
    (
        "㉕ 出参 ContactDto 的分类改成可空（Gson 会把 null 解成字符串 null）",
        DTOS,
        lambda s: s.replace(
            '    val category: String = "",\n    @SerialName("created_at") val createdAt: String = "",',
            '    val category: String? = null,\n    @SerialName("created_at") val createdAt: String = "",',
            1,
        ),
        "出参缺分类",
    ),
    (
        "㉖ 联系人抽屉里没有分类这一格（连「＋ 新建分类…」一起没了）",
        ADDR_SCREEN,
        lambda s: s.replace('text = { Text("＋ 新建分类…") },', 'text = { Text("换一换") },', 1),
        "抽屉里没有分类这一格",
    ),
    # ---- 六、AI 写侧四个动作 ----
    (
        "㉗ 四个动作码少一个进角色白名单（货主/派单员用不了）",
        AI_WRITE,
        lambda s: s.replace("        CONTACT_CATEGORY_DELETE,", "        PLACE_CATEGORY_DELETE,", 1),
        "四个动作码都进了角色白名单",
    ),
    (
        "㉘ 撤销资源没登记（撤销/恢复认不出联系人分类）",
        AI_RES,
        lambda s: s.replace('key = "contact_category"', 'key = "place_category"', 1),
        "资源没登记",
    ),
    (
        "㉙ 重排「撤不回来」的理由并进了地点分组那条（单测给共用设了上限）",
        AI_REVERT,
        lambda s: s.replace(
            "listOf(AiWrites.CONTACT_CATEGORY_REORDER),",
            "listOf(AiWrites.CONTACT_CATEGORY_REORDER, AiWrites.PLACE_CATEGORY_REORDER),",
            1,
        ),
        "并进了地点那条共用理由",
    ),
    # ---- 七、用例与文档 ----
    (
        "㉚ 用例里「还有几位」那条断言被删（删除守卫没了行为证据）",
        BE_TEST,
        lambda s: s.replace('assert "1 位" in r.json()["detail"], r.json()["detail"]', "assert True", 1),
        "用例里找不到",
    ),
    (
        "㉛ 进名册面板不重新取名册（面板显示上一次的「N 位联系人」，删除确认框也跟着说错）",
        ADDR_SCREEN,
        lambda s: s.replace("LaunchedEffect(Unit) { catVm.load() }", "// 不重取", 1),
        "进面板不重取名册",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        # 按行尾归一后再替换（Windows 上 Kotlin 文件可能是 CRLF），写回时按原样还原
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated.replace("\r\n", "\n")
            if crlf:
                out_txt = out_txt.replace("\n", "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"  [OK] {label} → 报红")
        else:
            fails.append(f"{label}：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print(f"  [MISS] {label} → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
