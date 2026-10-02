# -*- coding: utf-8 -*-
"""红线：**联系人可以分类**（左分类 / 右列表，按人分区）—— FEAT-0007，2026-10-03 用户点名。

## 用户原话
> 「我们的联系人好像是可以做分类的吧，同样以**左边为分类右边为列表**的形式展示出来。
>  如果没有分类功能的话，则添加新的分类功能」
> 「**对分类管理的话啊，就像我们的复用地点管理一样**」
> 「这个不只是派单人员，他拥有其他的账户也是拥有比如说**货主批发商**」

## 这条为什么必须有机器的判据
「分类」在本仓库是一套**五条纪律**（见 services/category_order.py 里那句
「整份顺序的校验几个名册共用一份」）：名册管顺序、字符串管归属、名册外的分类名不是错误、
改名必须级联、还有挂载时不许删。这五条**任何一条破了都不会报错**，只会在某一天被用户发现
「联系人怎么全变成未分类了」。三种具体破法：

* 归属存成**名册 id** → 名册里删一行，档案上的分类变成一串数字，界面上看就是「分类丢了」；
* 改名**不级联** → 联系人挂着一个已经不存在的分类名，右栏按新名字筛，看到的是空列表；
* 删除**不拦挂载** → 用户点一下「删除分类」，十几位联系人静默变成未分类，而且**界面上看不出来**。

另外两条只有本功能才有：**两张名册不许合并**（地点分类挂地点、联系人分类挂联系人，合表每次都要先判
kind，判错一次就是把联系人分类搬进地点库）、**编辑抽屉必须回填分类**（整个保存是「整份回传」语义，
不回填 = 改个称呼顺手把分类清掉）。

所以判据分七层：

1. **两张名册分开**：place_categories 不加 kind、shipper_contacts 上不挂名册外键；
2. **归属是自由文本**（shipper_contacts.category 与 shipper_locations.category 逐字同形）；
3. **迁移 012 的形状**：加列 + 补索引 + ⛔ 不回填 + 能重跑 + 新表不在这里建；
4. **端点五条纪律**：角色集与 shipper.py 同一份、删除拦挂载、改名级联（连回收站里的一起改）、
   整份顺序走共用 ordered_ids、四个写端点都有审计留痕；
5. **界面是「左分类 + 右列表」**，且左栏**一格都不带条数**（用户 2026-09-19 点名：「那个分组下面
   不要显示有多少条啊，这是多余信息」）、选中格失效要自愈、编辑抽屉要**回填**分类；
6. **AI 也能做**（本仓库惯例：人能操作的 AI 都要能操作），且重排撤不回来的理由是**它自己一句**；
7. **用例 / 文档 / 反向验证**三件都在。

用法：python _tools/qa/_check_contact_categories.py
     python _tools/qa/_check_contact_categories.py --list
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
BE = ROOT / "backend/app"

BE_MODEL = BE / "models/contact_category.py"
BE_PLACE_MODEL = BE / "models/place_category.py"
BE_SHIPPER_MODEL = BE / "models/shipper.py"
BE_SCHEMA = BE / "schemas/contact_category.py"
BE_SHIPPER_SCHEMA = BE / "schemas/shipper.py"
BE_API = BE / "api/v1/contact_categories.py"
BE_SHIPPER_API = BE / "api/v1/shipper.py"
BE_ROUTER = BE / "api/v1/router.py"
BE_MIG = BE / "migrations/012_contact_categories.py"
BE_ENUMS = BE / "models/enums.py"
BE_ROLE_CAPS = BE / "core/role_capabilities.py"
BE_AUDIT_COV = BE / "core/capability_audit_coverage.py"
BE_TEST = ROOT / "backend/tests/test_contact_categories.py"

ADDR_SCREEN = AND / "ui/shipper/AddressScreen.kt"
ADDR_VM = AND / "ui/shipper/AddressViewModel.kt"
CAT_VM = AND / "ui/dispatcher/ContactCategoriesViewModel.kt"
CAT_SCREEN = AND / "ui/dispatcher/ContactCategoriesScreen.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"
APIS = AND / "data/remote/api/Apis.kt"
REPO = AND / "data/repo/AppRepository.kt"
AI_WRITE = AND / "ai/AiWrite.kt"
AI_BASIC = AND / "ai/AiWriteBasicData.kt"
AI_SVC = AND / "ai/AiWriteService.kt"
AI_DS = AND / "ai/AiWriteDataSource.kt"
AI_RES = AND / "ai/AiResources.kt"
AI_REVERT = AND / "ai/AiRevert.kt"
AI_READ_CATALOG = AND / "ai/AiReadCatalog.kt"
READ_JSON = ROOT / "docs/ai/ai_read_catalog.json"

REVERSE = "_tools/qa/_reverse_verify_contact_categories.py"
DOC = ROOT / "docs/changes/FEAT-0007.md"
REGISTRY = ROOT / "docs/changes/README.md"

#: 扫到的界面文件数下限（防目录改名/搬走之后「一个文件都没扫到」也算过）
MIN_UI_FILES = 100
#: 抽出来的函数体字符数下限（**抽取失效比判据腐烂更危险** —— 那会变成一条永远绿的检查）
BODY_FLOOR = 80
#: 归属那一格的列声明：地点与联系人**逐字同形**（只改一处就是两套写法）
CATEGORY_COL = 'category: Mapped[str] = mapped_column(String(32), default="", index=True)'
#: 角色门：名册端点与 shipper.py 必须是**同一份**（批发商在本仓库就是货主，没有独立角色）
ROLE_DEP = "Depends(require_roles(UserRole.SHIPPER, UserRole.DISPATCHER))"


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def fn_body(src: str, sig: str) -> str:
    """sig 那个函数的**函数体**（大括号配对，不按行猜）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


def py_func(src: str, sig: str) -> str:
    """Python 版的「函数体」：从 sig 到下一个顶格 def / 装饰器 / class，或文件末尾。

    ⚠️ 不能用上面那个大括号版：Python 没有大括号。也不能让 strip_comments 参与 ——
    它只认 Kotlin 的 // 与 /* */，而后端文件里一句 api/v1/* 这样的散文就会被当成
    块注释开头，把**后面整个文件**吃掉（所以本判据读后端文件一律走 read()）。
    """
    i = src.find(sig)
    if i < 0:
        return ""
    ends = [x for x in (src.find(chr(10) + "def ", i + 1), src.find(chr(10) + "@router", i + 1)) if x > 0]
    return src[i : min(ends)] if ends else src[i:]


def class_body(src: str, decl: str) -> str:
    """decl（如 class ShipperContact( ）那个类的类体：取到下一个顶层 class 或文件末尾。"""
    i = src.find(decl)
    if i < 0:
        return ""
    j = src.find(chr(10) + "class ", i + 1)
    return src[i:] if j < 0 else src[i:j]


def dto_body(src: str, name: str) -> str:
    """data class <name>( 的那一段（取到第一个顶格的右括号）。"""
    i = src.find("data class " + name + "(")
    if i < 0:
        return ""
    j = src.find(chr(10) + ")", i)
    return src[i:] if j < 0 else src[i : j + 2]


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("联系人分类检查"):
        return 1

    c = Checker()
    print("联系人分类（左分类 / 右列表，按人分区）：FEAT-0007，2026-10-03")

    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    # ---- 1. 文件都在 ----
    for p, why in (
        (BE_MODEL, "联系人分类名册的模型（表 contact_categories）"),
        (BE_SCHEMA, "名册的出入参"),
        (BE_API, "名册的五个端点"),
        (BE_MIG, "加列 + 补索引的迁移"),
        (BE_TEST, "后端用例"),
        (CAT_VM, "名册管理页的状态机（拖动即提交）"),
        (CAT_SCREEN, "名册管理面板"),
        (DOC, "这条功能的九节文档"),
        (ROOT / REVERSE, "本判据自己的反向验证"),
    ):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 存在（{why}）", p.exists(), "文件被搬走/改名了")

    # ⚠️ 后端文件一律 read() 原样读：strip_comments 只处理 Kotlin 的 // 与 /* */，
    #    遇到 Python 散文中一个 api/v1/* 就会把后面整个文件吃掉（实测 capability_audit_coverage
    #    被吃成空串），于是"能力有没有认领动作码"这条会永远失败，或者更糟——永远通过。
    model = read(BE_MODEL)
    place_model = read(BE_PLACE_MODEL)
    shipper_model = read(BE_SHIPPER_MODEL)
    schema = read(BE_SCHEMA)
    shipper_schema = read(BE_SHIPPER_SCHEMA)
    api = read(BE_API)
    shipper_api = read(BE_SHIPPER_API)
    router = read(BE_ROUTER)
    mig = read(BE_MIG)
    enums = read(BE_ENUMS)
    role_caps = read(BE_ROLE_CAPS)
    audit_cov = read(BE_AUDIT_COV)
    addr_screen = code(ADDR_SCREEN)
    addr_vm = code(ADDR_VM)
    cat_vm = code(CAT_VM)
    cat_screen = code(CAT_SCREEN)
    dtos = code(DTOS)
    apis = code(APIS)
    repo = code(REPO)
    ai_write = code(AI_WRITE)
    ai_basic = code(AI_BASIC)
    ai_svc = code(AI_SVC)
    ai_ds = code(AI_DS)
    ai_res = code(AI_RES)
    ai_revert = code(AI_REVERT)
    read_catalog = read(AI_READ_CATALOG) + read(READ_JSON)

    # ---- 2. 两张名册**分开**（本功能最容易"顺手套用"的一步）----
    c.ok(
        "⛔ place_categories 上没有 kind 列（合表每次都要判 kind，判错一次＝把联系人分类搬进地点库）",
        place_model != "" and "kind" not in place_model,
        "地点分类名册上出现了 kind",
    )
    c.ok(
        "联系人分类**另起一张表** contact_categories（不是复用地点那张）",
        "class ContactCategory(Base, TimestampMixin)" in model
        and '__tablename__ = "contact_categories"' in model,
        "模型名 / 表名不对",
    )
    c.ok(
        "名册唯一键是 (shipper_id, name)（按人分区：货主 A 的「老客户」不该出现在货主 B 的列表里）",
        'UniqueConstraint("shipper_id", "name", name="uq_contact_category_owner_name")' in model,
        "唯一键没了 / 改名了",
    )
    for col, label in (
        ("id: Mapped[int] = mapped_column(primary_key=True", "id 主键"),
        ('shipper_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)', "shipper_id（谁的库）"),
        ("name: Mapped[str] = mapped_column(String(32), index=True)", "name（≤32 字，带索引）"),
        ("sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)", "sort_order（顺序）"),
    ):
        c.ok(f"名册有这一列：{label}", col in model, "列声明对不上（类型 / 索引 / 默认值任一不同都要重写）")

    # ---- 3. 归属是**自由文本**，与地点那一格逐字同形 ----
    contact_body = class_body(shipper_model, "class ShipperContact(")
    location_body = class_body(shipper_model, "class ShipperLocation(")
    c.ok(
        "抽出了 ShipperContact / ShipperLocation 两个类体（≥ 300 字符 —— 抽取失效会让下面两条变成假绿）",
        len(contact_body) >= 300 and len(location_body) >= 300,
        f"联系人 {len(contact_body)} 字符、地点 {len(location_body)} 字符",
    )
    c.ok(
        "shipper_contacts.category 与 shipper_locations.category **逐字同形**（String(32) / 默认空串 / 带索引）",
        CATEGORY_COL in contact_body and CATEGORY_COL in location_body,
        "两边的分类列写法不一样 —— 读侧会出现两套口径",
    )
    c.ok(
        "⛔ 联系人上没有指向名册的外键（归属存分类**名**：名册删一行不该让档案上的分类变成一串数字）",
        # ⚠️ 按**列声明**判，不按词判：Python 的 # 注释不在这份判据的剥离范围内
        #    （strip_comments 只去 Kotlin 的 // 与 /* */），散文里提到名册名是正常的。
        'ForeignKey("contact_categories' not in contact_body
        and "category_id: Mapped" not in contact_body,
        "挂上了名册外键",
    )

    # ---- 4. 迁移 012 ----
    c.ok(
        "迁移 012 在册（VERSION / NAME 对不上 = 线上 upgrade 会跳过它）",
        "VERSION = 12" in mig and 'NAME = "contact_categories"' in mig,
        "版本号 / 名字对不上（或文件不在）",
    )
    c.ok(
        "加的是 category VARCHAR(32) NOT NULL DEFAULT 空串（与模型同宽同默认）",
        "VARCHAR(32) NOT NULL DEFAULT" in mig and 'COLUMN = "category"' in mig,
        "列定义与模型不一致（MySQL 上会截断/报错）",
    )
    c.ok(
        "索引名与 index=True 的默认名一致（两处建的是**同一张**索引，别建两条）",
        "ix_shipper_contacts_category" in mig,
        "索引名不同 —— 老库上会多出一条重复索引",
    )
    c.ok(
        "⛔ 不回填老数据（这一位到底是「老客户」还是「司机」没人能证明 —— 与 009/010/011 同一条纪律）",
        "UPDATE " not in mig.replace("UPDATED_AT", ""),
        "迁移体里出现了 UPDATE —— 它在替用户猜分类",
    )
    c.ok(
        "迁移能重跑（先 inspect 判列/索引在不在，在就安静返回）",
        # ⛔ 不能只断言「文件里出现过 inspect(engine)」：迁移里有好几处，抹掉一处照样绿（反向验证 ⑭ 抓到的洞）。
        #    真正要守的是：加列与建索引**各自**被存在性判断守着，所以第二次 upgrade 不会炸。
        "have = _columns(engine)" in mig
        and "if COLUMN not in have:" in mig
        and "if INDEX_NAME not in _indexes(engine):" in mig,
        "少了存在性判断 —— 第二次 upgrade 会炸",
    )
    c.ok(
        "⛔ 新表不在这里建（建表归 create_all(checkfirst=True)，迁移只做正式变更）",
        "CREATE TABLE" not in mig.upper(),
        "迁移里出现了 CREATE TABLE —— 同一件事两边都写了",
    )

    # ---- 5. 端点：五条纪律 ----
    c.ok(
        "名册端点的前缀是 /contact-categories",
        'APIRouter(prefix="/contact-categories"' in api,
        "前缀变了（客户端 5 个方法与 AI 读动作都要跟着改）",
    )
    c.ok(
        "角色门与 shipper.py 的**同一份**（批发商在本仓库就是货主，没有独立角色）",
        ROLE_DEP in api and ROLE_DEP in shipper_api,
        "两边的角色集不一样 —— 会出现「货主能建联系人、却建不了分类」",
    )
    c.ok(
        "五个端点都走同一个角色门（current: ContactOwner ≥ 5 处）",
        count("current: ContactOwner", api) >= 5,
        f"只有 {count('current: ContactOwner', api)} 处",
    )
    c.ok(
        "删除时**还有联系人挂着就拒绝**，且文案点出影响面（「还有 N 位联系人挂在这个分类下…」）",
        "位联系人挂在这个分类下" in api and "status_code=400" in api,
        "删除守卫没了 —— 点一下就把十几位联系人静默变成未分类",
    )
    c.ok(
        "改名级联改 shipper_contacts.category（同一事务）",
        "ShipperContact.__table__.update()" in api and ".values(category=body.name)" in api,
        "改名没级联 —— 联系人挂着一个已经不存在的分类名",
    )
    i_upd = api.find("ShipperContact.__table__.update()")
    j_val = api.find(".values(category=body.name)", i_upd) if i_upd >= 0 else -1
    cascade = api[i_upd:j_val] if i_upd >= 0 and j_val > i_upd else ""
    c.ok(
        "级联**不过滤软删**（回收站里那条也要改名，否则恢复出来挂着一个不存在的分类）",
        len(cascade) >= 40 and "is_deleted" not in cascade,
        f"片段长 {len(cascade)}；出现了 is_deleted 过滤",
    )
    c.ok(
        "整份顺序走共用的 ordered_ids（几个名册同一份校验：不许只传一半）",
        "ids = ordered_ids(by_id, body.ids)" in api,
        "顺序校验自己写了一套（或没校验）",
    )
    c.ok(
        "四个写端点都有审计留痕（write_log( ≥ 4）",
        count(r"write_log\(", api) >= 4,
        f"只有 {count(r'write_log\(', api)} 处",
    )
    c.ok(
        "三个动作码是**新的**（不复用 PLACE_CATEGORY_* —— 否则审计里分不清改的是哪份名册）",
        all(x in enums for x in ("CONTACT_CATEGORY_UPSERT", "CONTACT_CATEGORY_DELETE", "CONTACT_CATEGORY_REORDER")),
        "动作码没进枚举（审计页会显示成生码）",
    )
    c.ok(
        "名册端点写的是 CONTACT_CATEGORY_*，一处 PLACE_CATEGORY_* 都没有",
        "OperationAction.CONTACT_CATEGORY_UPSERT" in api and "OperationAction.PLACE_CATEGORY" not in api,
        "写串了动作码 —— 审计里两条链路会混在一起",
    )
    c.ok(
        "名册行数上限 200（与商品/地点同一档）",
        # ⛔ 必须是「整行等于 200」：写成子串判的话，MAX_CATEGORIES = 20000 也包含它（反向验证 ⑦ 抓到的洞）
        re.search(r"^MAX_CATEGORIES = 200$", api, re.M) is not None,
        "上限被删/改了",
    )
    c.ok(
        "ensure_contact_category 只有一处实现，并被 shipper.py 复用（建联系人时顺手建分类）",
        api.count("def ensure_contact_category(") == 1
        and "from app.api.v1.contact_categories import ensure_contact_category" in shipper_api,
        "实现不唯一 / 没被复用",
    )
    c.ok(
        "影响面数字只数**没被软删**的联系人（回收站里的不该算进「还有 N 位」）",
        "is_deleted.is_(False)" in api,
        "把回收站里的也算进去了 —— 用户会因为一个看不见的人删不掉分类",
    )

    # ---- 6. 出入参 ----
    c.ok(
        "名册出参带 contact_count（删之前要让用户看见影响面）",
        "contact_count: int = 0" in schema,
        "出参少了一格",
    )
    c.ok(
        "整份顺序的入参限定 1..200 条",
        "min_length=1, max_length=200" in schema,
        "顺序入参没限长",
    )
    c.ok(
        "分类名只 strip 不截断（超 32 字由 schema 的 max_length 挡成 422，不是悄悄截断）",
        "分类名不能为空或纯空格" in schema,
        "空名/纯空格的下限没了",
    )
    c.ok(
        "ContactCreate.category 默认空串（= 未分类）",
        'category: str = Field(default="", max_length=32)' in shipper_schema,
        "入参缺这一格",
    )
    c.ok(
        "ContactUpdate.category 是 str | None（None = 不改、空串 = 明确清成未分类）",
        "category: str | None = Field(None, max_length=32)" in shipper_schema,
        "三档语义被写丢（改个名字会把分类清掉）",
    )
    c.ok(
        "出参 category 是 str 默认空串（⛔ 不是可空 —— Gson 会把 null 解成字符串 null）",
        'category: str = ""' in shipper_schema,
        "出参改成了可空",
    )

    # ---- 7. 挂在 shipper.py 上的那两处 + 路由 + 能力 ----
    c.ok(
        "POST /shipper/contacts 写分类，且**只在这次真的给了才覆盖**（upsert 没选分类不该抹掉老档案的）",
        count(r"if category:", shipper_api) == 1
        and "category = _clean_category(body.category)" in shipper_api,
        "覆盖语义写丢了",
    )
    upd_contact = py_func(shipper_api, "def update_contact(")
    c.ok(
        "PATCH 走三档语义（update_contact 里 if body.category is not None 恰好 1 处）",
        len(upd_contact) >= BODY_FLOOR and count(r"if body\.category is not None:", upd_contact) == 1,
        f"函数体长 {len(upd_contact)}；出现 {count(r'if body.category is not None:', upd_contact)} 处",
    )
    c.ok(
        "两处都顺手补名册（ensure_contact_category(db ≥ 2 —— 敲个新分类名就是在建它）",
        count(r"ensure_contact_category\(db", shipper_api) >= 2,
        f"只有 {count(r'ensure_contact_category\(db', shipper_api)} 处",
    )
    c.ok(
        "路由挂上了（include_router(contact_categories.router)）",
        "include_router(contact_categories.router)" in router,
        "端点没挂上去（404）",
    )
    c.ok(
        "能力 address:manage 认领了三个动作码（新增审计动作码必须被能力认领）",
        all(
            x in audit_cov
            for x in ("CONTACT_CATEGORY_UPSERT", "CONTACT_CATEGORY_DELETE", "CONTACT_CATEGORY_REORDER")
        ),
        "没认领 —— _check_capability_unification.py 会把它算成孤儿",
    )
    # ⚠️ 必须取**最后一处** AUDIT_CAPABILITY_EXEMPT：文件头的散文里也提过这个名字，
    #    find() 会命中那次提及，于是大括号配到别处、exempt 变成半截串（假红）。
    i_ex = audit_cov.rfind("AUDIT_CAPABILITY_EXEMPT")
    j_ex = audit_cov.find("{", i_ex) if i_ex >= 0 else -1
    exempt = ""
    if j_ex >= 0:
        depth = 0
        k = j_ex
        while k < len(audit_cov):
            if audit_cov[k] == "{":
                depth += 1
            elif audit_cov[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        exempt = audit_cov[j_ex : k + 1]
    c.ok(
        "例外表里没有 address:manage 那条化石（认领之后它就该销掉；例外表只减不增）",
        exempt != "" and "address:manage" not in exempt,
        f"例外表片段：{exempt[:120]}",
    )
    i_cap = role_caps.find("key='address:manage'")
    entry = role_caps[i_cap : i_cap + 700] if i_cap >= 0 else ""
    m_gate = re.search(r"gate='([^']+):(\d+)'", entry)
    gate_ok = False
    gate_why = "找不到 role_capabilities 里 address:manage 的 gate 字段"
    if m_gate:
        target = ROOT / m_gate.group(1)
        ln = int(m_gate.group(2))
        src_lines = read(target).splitlines()
        hit = src_lines[ln - 1] if 0 <= ln - 1 < len(src_lines) else ""
        gate_ok = "require_roles(" in hit
        gate_why = f"{m_gate.group(1)}:{ln} = {hit.strip() or '<空行>'}"
    c.ok(
        "角色能力 address:manage 的 gate 行号**真的指向那一行角色门**（行号会随 import 漂移）",
        gate_ok,
        gate_why,
    )
    c.ok(
        "能力文案里写明了「含分类」（用户看的能力清单要跟得上）",
        "含分类" in entry,
        "文案没更新",
    )

    # ---- 8. Android：DTO / Api / Repository ----
    cdto = dto_body(dtos, "ContactDto")
    c.ok(
        "抽出了 ContactDto（≥ 100 字符）",
        len(cdto) >= 100,
        f"只有 {len(cdto)} 字符",
    )
    c.ok(
        "ContactDto 有 val category: String = 空串（出参带分类，右栏才筛得动）",
        'val category: String = ""' in cdto,
        "出参缺分类",
    )
    cat_dto = dto_body(dtos, "ContactCategoryDto")
    c.ok(
        "ContactCategoryDto 四格齐全（id / name / sort_order / contact_count）",
        len(cat_dto) >= 100
        and 'val name: String = ""' in cat_dto
        and '@SerialName("sort_order") val sortOrder: Int = 0' in cat_dto
        and '@SerialName("contact_count") val contactCount: Int = 0' in cat_dto,
        "DTO 缺字段",
    )
    c.ok(
        "三个请求体都在（新建 / 改 / 整份重排）",
        dto_body(dtos, "ContactCategoryCreateRequest") != ""
        and dto_body(dtos, "ContactCategoryUpdateRequest") != ""
        and dto_body(dtos, "ContactCategoryReorderRequest") != "",
        "请求 DTO 缺一个",
    )
    for p in (
        '@GET("contact-categories")',
        '@POST("contact-categories")',
        '@PATCH("contact-categories/{categoryId}")',
        '@DELETE("contact-categories/{categoryId}")',
        '@POST("contact-categories/reorder")',
    ):
        c.ok(f"Apis.kt 有 {p}", p in apis, "接口方法丢了")
    c.ok(
        "Repository 有 reorderContactCategories（名册页的「拖动即提交」靠它；改名就会被判据点名）",
        "suspend fun reorderContactCategories(" in repo,
        "读不到名册页要求的那条方法",
    )

    # ---- 9. Android：左分类 + 右列表 ----
    pane = fn_body(addr_screen, "private fun ContactCategoryPane(")
    i_rail = pane.find("MasterRail(")
    i_items = pane.find("items = buildList {", i_rail) if i_rail >= 0 else -1
    j_rail = pane.find("selectedKey", i_items) if i_items >= 0 else -1
    rail = pane[i_items:j_rail] if i_items >= 0 and j_rail > i_items else ""
    c.ok(
        "「地址与联系人 → 联系人」是**左分类 + 右列表**（面板里有 MasterRail，且左栏是 buildList 拼的）",
        len(pane) >= BODY_FLOOR and i_rail >= 0 and len(rail) >= BODY_FLOOR,
        f"面板体长 {len(pane)}；左栏片段长 {len(rail)}",
    )
    c.ok(
        "左栏那几格的构造里**没有条数**（用户 2026-09-19：「那个分组下面不要显示有多少条啊，这是多余信息」）",
        len(rail) >= BODY_FLOOR and "contactCount" not in rail,
        f"左栏片段长 {len(rail)}；出现了 contactCount",
    )
    c.ok(
        "右栏按分类**名**过滤（it.category == railName）",
        "it.category == railName" in pane,
        "右栏没接上分类过滤",
    )
    c.ok(
        "左栏有一格「管理分类」（打开名册页的第二层，不新开路由）",
        'RailItem("manage"' in pane,
        "管理入口没了",
    )
    c.ok(
        "从管理面板回来会重取名册（不然改了名左栏还是旧名字）",
        "vm.reloadContactCategories()" in pane,
        "没重取",
    )
    c.ok(
        "每次进名册面板都重新拉一次名册（appViewModel 是 Activity 级缓存，VM 的 init { load() } 只跑第一次 —— "
        "不补这一下，用户改完分类再进来看到的还是上一次的「N 位联系人」）",
        "catVm.load()" in pane,
        "进面板不重取名册 —— 面板会显示上一次的「N 位联系人」，删除确认框也跟着说错",
    )
    #: 抽屉里「分类」那一格的下拉段（从 label = "分类" 到紧跟的 if (newCatDialog)）。
    _i_pick = addr_screen.find("label = " + chr(34) + "分类" + chr(34))
    _i_dlg = addr_screen.find("if (newCatDialog)", _i_pick) if _i_pick >= 0 else -1
    _cat_menu = addr_screen[_i_pick:_i_dlg] if _i_pick >= 0 and _i_dlg > _i_pick else ""
    c.ok(
        "联系人抽屉里分类是**下拉**，且带「未分类」与「＋ 新建分类…」两条",
        # ⛔ 必须落在**同一段**里判：全文件出现过两次「新建分类…」，抹掉一处照样绿（反向验证 ㉖ 抓到的洞）。
        len(_cat_menu) >= 200 and "未分类" in _cat_menu and "新建分类…" in _cat_menu,
        "抽屉里没有分类这一格（或少了新建入口）",
    )
    open_body = fn_body(addr_vm, "fun openContactDialog(")
    c.ok(
        "打开联系人编辑时**回填**分类（不回填 = 改个称呼顺手把分类清掉）",
        "contactCategory = c?.category ?: " in open_body,
        "openContactDialog 里没有回填",
    )
    save_body = fn_body(addr_vm, "fun saveContact(")
    c.ok(
        "保存联系人时把分类带进请求体（新建 + 修改两处）",
        count(r"category = contactCategory\.trim\(", save_body) >= 2,
        f"只有 {count(r'category = contactCategory\.trim\(', save_body)} 处",
    )
    c.ok(
        "选中格失效会自愈（名册里那一格改名/删掉后，选中格回到「全部」而不是筛出空列表）",
        # ⛔ 不能只找 contactRailKey = ""：写成 if (contactRailKey.isEmpty()) contactRailKey = "" 也含它，
        #    那样名册改名后照样停在老分类上（反向验证 ㉒ 抓到的洞）。要钉住「拿名册里的名字去比」这一步。
        'contactCategories.none { "c|" + it.name == contactRailKey }' in addr_vm,
        "少了自愈 —— 用户会看到「这个分类是空的」",
    )
    c.ok(
        "名册面板是 public 的 ContactCategoriesPanel（被联系人页当第二层调用）",
        "fun ContactCategoriesPanel(" in cat_screen,
        "面板入口改名/私有化了",
    )
    c.ok(
        "拖动即提交走共用草稿态（submittableIds —— 非草稿页必须自己调它）",
        "submittableIds(" in cat_vm and "repo.reorderContactCategories(" in cat_vm,
        "名册页的提交没走共用件",
    )
    c.ok(
        "删除前的确认写清影响面（「现在有 N 位联系人挂在这一类下。」）",
        "位联系人挂在这一类下" in cat_screen,
        "确认框没告诉用户要动多少人",
    )

    # ---- 10. AI 也能做（本仓库惯例：人能操作的 AI 都要能操作）----
    for const, val in (
        ("CONTACT_CATEGORY_CREATE", "contact_category.create"),
        ("CONTACT_CATEGORY_UPDATE", "contact_category.update"),
        ("CONTACT_CATEGORY_DELETE", "contact_category.delete"),
        ("CONTACT_CATEGORY_REORDER", "contact_category.reorder"),
    ):
        c.ok(
            f"动作码 {val} 在 AiWrite.kt 里",
            f'const val {const} = "{val}"' in ai_write,
            "常量丢了",
        )
    #: 角色白名单那一段：从地点分组那四行（同一个人分区家族）到消息那一条之间。
    _i_wl = ai_write.find("PLACE_CATEGORY_CREATE,")
    _j_wl = ai_write.find("NOTIFICATIONS_READ_ALL,", _i_wl) if _i_wl >= 0 else -1
    _wl = ai_write[_i_wl:_j_wl] if _i_wl >= 0 and _j_wl > _i_wl else ""
    c.ok(
        "四个动作码都进了角色白名单（否则货主/派单员用不了）",
        # ⛔ 不能全文数：AiWrite.kt:2209 的手写目录条目 `id = CONTACT_CATEGORY_REORDER,` 也算一处，
        #    抹掉白名单里那一行照样 ≥4（反向验证 ㉗ 抓到的洞）。切出角色白名单那一段来数。
        len(_wl) >= 200
        and all(
            f"{x}," in _wl
            for x in ("CONTACT_CATEGORY_CREATE", "CONTACT_CATEGORY_UPDATE", "CONTACT_CATEGORY_DELETE", "CONTACT_CATEGORY_REORDER")
        ),
        "四个动作码没都进角色白名单（货主/派单员就用不了）",
    )
    c.ok(
        "分组常量 G_CONTACT_CATEGORY 在（整份重排跟别的分类名册分开）",
        'const val G_CONTACT_CATEGORY = "联系人分类"' in ai_write,
        "分组常量丢了",
    )
    c.ok(
        "三条声明式 CRUD（新建 / 改 / 删）都在 AiWriteBasicData",
        count(r"AiWrites\.CONTACT_CATEGORY_(CREATE|UPDATE|DELETE)", ai_basic) >= 3,
        "声明式动作缺一个 —— 写端点会变成「没交代」",
    )
    c.ok(
        "目标规格与键白名单都在（targetContactCategory + CONTACT_CATEGORY_KEYS）",
        "private fun targetContactCategory()" in ai_basic and "CONTACT_CATEGORY_KEYS = setOf(" in ai_basic,
        "少一个 —— 卡片上写了也传不进去",
    )
    c.ok(
        "整份重排的处理器**注册进了服务**（只定义不注册 = 那个动作点不到）",
        "ReorderContactCategoriesHandler(ds, store)" in ai_svc,
        "没注册",
    )
    c.ok(
        "读动作进了目录（contact_categories.list_categories，生成物里也要有）",
        "contact_categories.list_categories" in read_catalog,
        "读目录里没有它（AI 想重排却读不到当前名册）",
    )
    c.ok(
        "数据源给了「N 位联系人」的 note（删/改名卡片上那句影响面靠它）",
        "位联系人" in ai_ds,
        "note 没了 —— 卡片上说不清要动多少人",
    )
    c.ok(
        '撤销表里认了这条资源（AiResource(key = "contact_category") 且进了 TABLE）',
        'key = "contact_category"' in ai_res and "CONTACT_CATEGORY," in ai_res,
        "资源没登记（撤销/恢复认不出它）",
    )
    i_rev = ai_revert.find("CONTACT_CATEGORY_REORDER")
    rev_seg = ai_revert[max(0, i_rev - 500) : i_rev + 200] if i_rev >= 0 else ""
    c.ok(
        "重排「撤不回来」的理由是**它自己一句**（⛔ 不许与地点分组共用一条：单测给共用设了上限）",
        i_rev >= 0 and "PLACE_CATEGORY_REORDER" not in rev_seg,
        "并进了地点那条共用理由",
    )

    # ---- 11. 用例 / 文档 / 登记 ----
    test = read(BE_TEST)
    c.ok(
        "后端用例 ≥ 12 条（这不是一条 happy path 就能算数的功能）",
        test.count("def test_") >= 12,
        f"只有 {test.count('def test_')} 条",
    )
    for label, needle in (
        ("按人分区（拿别人的分类编号去改 → 404，不是 403）", "404"),
        ("司机整组被挡（403）", "403"),
        ("重名 409", "409"),
        ("超 32 字 / 纯空格 → 422", "422"),
        ("名册行数上限摆到边界", "MAX_CATEGORIES"),
        ("删除拦挂载那句文案（把还有几位写进 detail）", '位" in r.json()["detail"'),
        ("回收站里那条也一起改名", "回收站"),
    ):
        c.ok(f"用例覆盖到：{label}", needle in test, f"用例里找不到 {needle}")
    c.ok(
        "文档九节齐全（docs/changes/FEAT-0007.md）",
        DOC.exists() and all(s in read(DOC) for s in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")),
        "文档缺节（_check_dev_spec.py 也会红）",
    )
    c.ok(
        "登记簿里有 FEAT-0007 这一行",
        "FEAT-0007" in read(REGISTRY),
        "没登记（别人不知道这个 ID 用掉了）",
    )
    c.ok(
        "设计规范里那条「左栏不带条数」的来历记在文档里（用户 2026-09-19 原话）",
        DOC.exists() and "多余信息" in read(DOC),
        "文档没记这条来历 —— 下一个人会顺手加回去",
    )

    return c.report("联系人分类（FEAT-0007）")


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（联系人分类 FEAT-0007）==")
        print("1. 两张名册分开：place_categories 不加 kind、联系人不挂名册外键")
        print("2. 归属是自由文本，与 shipper_locations.category 逐字同形")
        print("3. 迁移 012：加列 / 补索引 / 不回填 / 能重跑 / 不建表")
        print("4. 端点五条纪律：角色门同一份、删除拦挂载、改名级联（不过滤软删）、ordered_ids、审计留痕")
        print("5. 出入参三档语义 + 名册 schema 的边界")
        print("6. 路由 / 能力认领 / gate 行号 / 例外表化石")
        print("7. Android：DTO、5 条路径、reorder 方法、左分类右列表、左栏不带条数、抽屉回填")
        print("8. AI 四个动作码 + 白名单 + 声明式 CRUD + 目标规格 + 处理器注册 + 读目录 + 撤销资源")
        print("9. 用例覆盖 / 文档九节 / 登记簿")
        sys.exit(0)
    sys.exit(main())
