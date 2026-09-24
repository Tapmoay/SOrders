# -*- coding: utf-8 -*-
"""红线：**单位换算**（一车 = 8 方）—— 判据一处、显示一处、钱不动（2026-09-24 用户要求）。

## 用户原话
> 「我们再加一个功能叫做**自动换算单位**。比如说我们有个单位叫一车，但是这一车如果是去拉沙子的话，
>  大概是八方，所以就说**一车是等于 8 方**。自动的换算单位也可以自动的选择匹配单位 ——
>  我们的**货主和派单员**，他可以自动的设置单位……这换算单位啊，我们就把它加在那个添加单位的
>  那个页面当中，添加单位那里再加个按钮可以说**添加单位换算**，那个按钮点进去，就是一个**新的弹窗**
>  就可以在那里设置新的单位换算了。然后我们再计算的时候或者是算账的时候会自动启动换算的功能，
>  比如说我下的十车，会有 **2 个数据**：第一个是 10 车，第 2 个则是 80 方。」

## 这条为什么必须有机器的判据
换算率是**用户自己填的数**，而它会出现在订单卡片、订单明细、账本小卡、下单页四处的数量里。
写错的后果全是静默的：

* 同一个源单位有两条换算（`1 车 = 8 方` + `1 车 = 50 袋`）→「10 车 ≈ ?」**没有唯一答案**，
  而界面只会挑一条显示，用户以为是系统算的；
* 反向对并存（`1 车 = 8 方` + `1 方 = 0.2 车`）→ 同一批货两个互相矛盾的数；
* 显示层各写一份换算 → 订单卡片说 80 方、订单详情说 50 袋；
* 换算跑去动钱（单价 × 换算率）→ 账目全错，而且**每一张单看起来都很合理**。

所以判据分六层：
1. **判据只有一处**（后端 `services/unit_conversion.py`）：四个纯函数各定义一次、别处 0 处；
2. **表与端点**：五个端点齐、删除是**软删**、**刻意不加**数据库唯一约束
   （加了之后"删掉再建同一条"会 500 —— 那条路必须由"把被删过的放回来"来走）；
3. **显示只有一处**（`Units.kt::convertedQty` / `qtyWithUnitConverted`），四个落点都用它，
   且**量列宽与渲染同源**（不同源 = 右对齐当场错位）；
4. **钱一个字节都不参与**：显示判据的函数体里不许出现价格/金额；
5. **一份来源**：全 App 的换算表只有 `UnitConv` 一个持有者；
6. **两处入口一份弹窗**（`UnitConversionDialog` 只定义一次）、删除有手边的恢复入口、
   审计码有中文名、单测/文档/反向验证都在。

用法：python _tools/qa/_check_unit_conversion.py
     python _tools/qa/_check_unit_conversion.py --list
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

BE_MODEL = BE / "models/unit_conversion.py"
BE_RULES = BE / "services/unit_conversion.py"
BE_API = BE / "api/v1/unit_conversions.py"
BE_SCHEMA = BE / "schemas/unit_conversion.py"
BE_ROUTER = BE / "api/v1/router.py"

UNITS = AND / "ui/common/Units.kt"
STORE = AND / "ui/common/UnitConverts.kt"
DIALOG = AND / "ui/common/UnitConversionDialog.kt"
PAGE = AND / "ui/common/UnitConversionsScreen.kt"
PAGE_VM = AND / "ui/common/UnitConversionsViewModel.kt"
SHEET = AND / "ui/common/UnitPickerSheet.kt"
FORM_SCREEN = AND / "ui/dispatcher/ProductFormScreen.kt"
CARD = AND / "ui/common/OrderCard.kt"
PEEK = AND / "ui/common/OrderPeek.kt"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
CREATE = AND / "ui/shipper/OrderCreateScreen.kt"
REPORT = AND / "ui/dispatcher/ReportCenter.kt"

TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/common/UnitConversionDisplayTest.kt"
BE_TEST = ROOT / "backend/tests/test_unit_conversions.py"
BE_TEST_RULES = ROOT / "backend/tests/test_unit_conversion_rules.py"

REVERSE = "_tools/qa/_reverse_verify_unit_conversion.py"
DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

#: 扫到的界面文件数下限（防目录改名/搬走之后"一个文件都没扫到"也算过）
MIN_UI_FILES = 110
#: 抽出来的函数体字符数下限（**抽取失效比判据腐烂更危险** —— 那会变成一条永远绿的检查）
BODY_FLOOR = 120

#: 换算显示**只许出现这几个落点**（每个落点必须用共用的那个函数）
SITES = (("订单卡片", CARD), ("账本小卡", PEEK), ("订单明细", DETAIL), ("下单页清单", CREATE))


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def fn_body(src: str, sig: str) -> str:
    """`sig`（如 `fun convertedQty(`）那个函数的**函数体**（大括号配对）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        c = src[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


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
    if refuse_if_injecting("单位换算检查"):
        return 1

    c = Checker()
    print("单位换算（一车 = 8 方）：2026-09-24")

    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    # ---- 1. 文件都在 ----
    for p, why in (
        (BE_MODEL, "换算表模型"),
        (BE_RULES, "四条判据的唯一实现处"),
        (BE_API, "五个端点"),
        (BE_SCHEMA, "出入参"),
        (STORE, "全 App 那一份换算表"),
        (DIALOG, "「添加单位换算」弹窗（一份实现）"),
        (PAGE, "「单位换算」管理页"),
        (TEST, "显示判据的 JVM 单测"),
        (BE_TEST, "端点链路的用例"),
        (BE_TEST_RULES, "四条判据的纯单测"),
    ):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 存在（{why}）", p.exists(), "文件被搬走/改名了")

    rules = code(BE_RULES)
    api = code(BE_API)
    model = code(BE_MODEL)
    units = code(UNITS)

    # ---- 2. 判据只有一处（0 处也红）----
    for name in ("clean_unit", "unit_key", "validate_units", "validate_factor", "conflict_reason", "format_factor"):
        here = count(rf"^def {name}\(", rules) + count(rf"\ndef {name}\(", rules)
        elsewhere = [
            p.relative_to(ROOT).as_posix()
            for p in BE.rglob("*.py")
            if p != BE_RULES and count(rf"def {name}\(", code(p))
        ]
        c.ok(
            f"`{name}` 只有一处定义（在 services/unit_conversion.py，且别处 0 处）",
            here == 1 and not elsewhere,
            f"这里 {here} 处；别处还有 {elsewhere}",
        )

    c.ok(
        "「一个源单位只能一条」写成一个常量而不是藏在查询里（调用点看得见）",
        "MAX_TARGETS_PER_UNIT = 1" in rules,
        "MAX_TARGETS_PER_UNIT 不是 1（或没了）",
    )
    c.ok(
        "同一个源单位已有换算时**拒绝并点名那一条**",
        "已经有换算了" in rules and "只能换算到一处" in rules,
        "冲突提示没了（用户不知道挡住了他的是哪一条）",
    )
    c.ok(
        "反向对（1 车=8 方 与 1 方=0.125 车）也被拒绝",
        # ⚠️ 锚**结构**（那条反向判定本身），不锚那句中文 ——
        #    「反过来」这种词加个前缀就还在，反向验证实测能骗过只判子串的版本。
        re.search(r"unit_key\(r\.from_unit\) == t and unit_key\(r\.to_unit\) == f", rules) is not None
        and "两个方向同时存在" in rules,
        "反向对判据没了 —— 同一批货会有两个互相矛盾的数",
    )
    c.ok("换算率必须 > 0", "大于 0" in rules, "换算率下限判据没了（1 车 = 0 方 会显示成 0 方）")

    # ---- 3. 表与端点 ----
    c.ok(
        "换算表有五个字段 + 软删（用户 2026-09-20 的硬规矩：删除一律软删）",
        "SoftDeleteMixin" in model
        and count(r"from_unit: Mapped\[str\]", model) == 1
        and count(r"to_unit: Mapped\[str\]", model) == 1
        and count(r"factor: Mapped\[Decimal\]", model) == 1,
        "字段/软删混入缺了",
    )
    c.ok(
        "⛔ **没有**数据库唯一约束（加了之后「删掉再建同一条」会 500）",
        "UniqueConstraint" not in model,
        "模型里出现了 UniqueConstraint —— 那条恢复路会变成 500",
    )
    c.ok(
        "新增时认出**被删过的同一条**并把它放回来（不是新建一条同源单位的）",
        "restore_by_create" in api,
        "没有这条分支：删掉再建会在库里留下两条同源换算",
    )
    for label, pat in (
        ("列表", r'@router\.get\("", response_model'),
        ("新增", r'@router\.post\("", response_model'),
        ("修改", r'@router\.patch\("/\{conversion_id\}"'),
        ("删除", r'@router\.delete\("/\{conversion_id\}"'),
        ("恢复", r'@router\.post\("/\{conversion_id\}/restore"'),
    ):
        c.ok(f"端点齐：{label}", count(pat, api) == 1, "缺这个端点（或写了两遍）")
    c.ok(
        "删除是**伪装删除**（打标记而不是真删）",
        re.search(r"row\.is_deleted = True", api) is not None and "sa_delete" not in api,
        "删除写成了物理删除",
    )
    c.ok(
        "恢复时**重新过一遍冲突判据**（这一条被删之后可能已经建了同源单位的）",
        re.search(r"def restore_conversion\([\s\S]{0,1500}?conflict_reason\(", api) is not None,
        "恢复没查冲突 —— 放回来会让「10 车 ≈ ?」有两个答案",
    )
    c.ok(
        "路由注册在 router.py 里",
        "unit_conversions.router" in code(BE_ROUTER),
        "没注册（端点根本不存在）",
    )
    c.ok(
        "**货主与派单员**都能读写（用户点名的两个角色），司机被挡在外面",
        count(r"require_roles\(UserRole\.SHIPPER, UserRole\.DISPATCHER\)", api) == 1,
        "角色门槛不是「货主 + 派单员」",
    )

    # ---- 4. 显示只有一处 + 钱不参与 ----
    for name in ("convertedQty", "qtyWithUnitConverted"):
        here = count(rf"fun {name}\(", units)
        elsewhere = [
            p.relative_to(AND).as_posix() for p in ui_files if p != UNITS and count(rf"fun {name}\(", code(p))
        ]
        c.ok(
            f"`{name}` 只有一处定义（在 ui/common/Units.kt，且别处 0 处）",
            here == 1 and not elsewhere,
            f"这里 {here} 处；别处还有 {elsewhere}",
        )

    body = fn_body(units, "fun convertedQty(")
    c.ok(
        f"抽出了 `convertedQty` 的函数体（≥ {BODY_FLOOR} 字符 —— 抽取失效会让下面两条变成假绿）",
        len(body) >= BODY_FLOOR,
        f"只有 {len(body)} 字符",
    )
    c.ok(
        "⛔ **钱一个字节都不参与**（函数体里没有价格/金额/行合计）",
        not re.search(r"price|money|Money|lineTotal|amount|fee", body),
        "换算里出现了钱 —— 账目会全错，而每张单看起来都很合理",
    )
    c.ok(
        "用 BigDecimal 算（浮点会印出 79.99999999999999）",
        "toBigDecimalOrNull()" in body,
        "用了 Double",
    )
    c.ok(
        "显示的是**约等号**（换算率是用户填的「大概」，写成等号等于替他担保）",
        "≈" in units,
        "没有 ≈",
    )
    c.ok(
        "没有换算时**逐字退回**原样（走 `qtyWithUnit`，不编数字）",
        "qtyWithUnit(quantity, rawUnit)" in fn_body(units, "fun qtyWithUnitConverted("),
        "退回那一支没了",
    )

    # ---- 5. 四个落点都用共用的那一份 ----
    for label, p in SITES:
        src = code(p)
        c.ok(
            f"{label} 用共用判据 `qtyWithUnitConverted(`",
            "qtyWithUnitConverted(" in src,
            "这个落点还在自己拼数量",
        )
    for label, p in (("账本小卡", PEEK), ("订单明细", DETAIL)):
        src = code(p)
        # 量列宽与渲染必须同一个函数：不同源 = 右对齐当场错位
        c.ok(
            f"{label} 量列宽与渲染**同源**（`rememberTextWidth` 那一行也用同一个函数）",
            re.search(r"rememberTextWidth\([\s\S]{0,120}?qtyWithUnitConverted\(", src) is not None,
            "量宽与渲染用了两个函数 —— 长出来的后半截会把右对齐挤歪",
        )

    # ---- 6. 一份来源 ----
    c.ok(
        "全 App 的换算表只有一个持有者（`object UnitConv`）",
        count(r"object UnitConv\b", code(STORE)) == 1
        and not [p.relative_to(AND).as_posix() for p in ui_files if p != STORE and count(r"object UnitConv\b", code(p))],
        "出现了第二个持有者",
    )
    for label, p in SITES:
        c.ok(f"{label} 从共用持有者读（`UnitConv.rows`）", "UnitConv.rows" in code(p), "没读那一份")
    c.ok(
        "退出登录会清掉缓存（换个人登录不该沿用上一个人的换算）",
        "UnitConv.clear()" in code(AND / "core/RealtimeHub.kt"),
        "RealtimeHub 里没有 clear —— 换账号会看到别人的换算",
    )

    # ---- 7. 两处入口、一份弹窗 ----
    dialog_defs = [p.relative_to(AND).as_posix() for p in ui_files if count(r"fun UnitConversionDialog\(", code(p))]
    c.ok(
        "「添加单位换算」弹窗只有一处定义",
        dialog_defs == ["ui/common/UnitConversionDialog.kt"],
        f"定义处：{dialog_defs}",
    )
    c.ok(
        "单位选择页里有那颗按钮（`onAddConversion`）—— 用户点名要放这儿",
        # ⚠️ 锚**那颗按钮的条件渲染**（不是"参数名出现过"）：只判 `onAddConversion` 字符串的话，
        #    把分支写成 `if (false)` 照样绿 —— 反向验证实测抓到过。
        "if (onAddConversion != null) {" in code(SHEET) and "添加单位换算" in read(SHEET),
        "那颗按钮没了",
    )
    c.ok(
        "管理页与商品表单页**都**用它（两处入口一份实现）",
        "UnitConversionDialog(" in code(PAGE) and "UnitConversionDialog(" in code(FORM_SCREEN),
        "有一处自己又画了一个弹窗",
    )
    c.ok(
        "两端的模块入口都在（货主与派单员各一格）",
        count(r'ModuleEntry\("单位换算"', code(AND / "ui/nav/Modules.kt")) == 2,
        "不是两格 —— 用户点名的两个角色要都能进",
    )

    # ---- 8. 删除要有手边的恢复入口 ----
    c.ok(
        "管理页有「已删除」区（删除是软删，恢复入口要手边就有）",
        "已删除" in read(PAGE) and "vm.restore(" in code(PAGE),
        "只能在别处找到恢复入口（或根本没有）",
    )
    c.ok(
        "三个审计码都有中文名（否则审计页印原始码）",
        count(r'"UNIT_CONVERSION_(UPSERT|DELETE|RESTORE)" ->', code(REPORT)) == 3,
        "ReportCenter 里缺中文名",
    )

    # ---- 9. 单测 / 文档 / 反向验证 ----
    test = read(TEST)
    c.ok(
        "显示判据有 JVM 单测，且钉着关键用例（用户举的十车例子 / 没换算退回原样 / 脏数据不显示）",
        test.count("@Test") >= 8
        and test.count("convertedQty(") >= 3
        and test.count("qtyWithUnitConverted(") >= 3
        and "80 方" in test
        and "换算率是脏数据时宁可不显示" in test,
        f"@Test {test.count('@Test')} 个、convertedQty( {test.count('convertedQty(')} 处",
    )
    bt = read(BE_TEST) + read(BE_TEST_RULES)
    c.ok(
        "后端用例钉着「删除可恢复」「恢复冲突要拒绝」「一个源单位只能一条」",
        "回收站" in bt and "恢复" in bt and "只能换算到一处" in bt,
        "后端用例缺关键场景",
    )
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")
    c.ok(
        "设计规范里记着这条（否则下一个人还会各写一份）",
        DOC.exists() and "换算" in read(DOC) and "UnitConv" in read(DOC),
        "06_DESIGN_SYSTEM.md 里没记单位换算这一节",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 判据唯一：clean_unit/unit_key/validate_units/validate_factor/conflict_reason/format_factor")
        print("     · 表与五个端点齐、删除是软删、**不加**数据库唯一约束、恢复要重查冲突")
        print("     · 显示唯一：convertedQty/qtyWithUnitConverted；四个落点都用它且量宽同源")
        print("     · **钱不参与**（函数体里没有 price/money/lineTotal）")
        print("     · 一份来源（UnitConv）、两处入口一份弹窗、删除有手边恢复入口")
        print("     · 单测 / 后端用例 / 设计规范 / 反向验证脚本都在")

    return c.report("单位换算（一车 = 8 方）")


if __name__ == "__main__":
    sys.exit(main())
