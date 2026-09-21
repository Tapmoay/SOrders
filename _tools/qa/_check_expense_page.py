"""红线：开销管理（2026-09-20 用户第六轮重写）的版式与"卡片按分类突出"的规矩。

## 用户原话（这一页就是照它做的）

> 这个开销管理，前一部分为**新增开销**（就相当于新增订单一样）……下面开销记录我们**按照商品记录**，
> 有个分类（商品分类我们已经做好了），开销分类**也有个分类管理**；右边就是该分类的记录。
> 同时我们也可以**按照时间**进行 —— 同样以**右上角时间药丸**的形式。关于开销的卡片也做相应改动：
> 对于一些**需要明确的信息给凸显出来**，不需要明显的就保持原样；这个关联跟**分类**是有关系的
> （燃油/维修主要是车辆，所以首要突出的是车辆）……**要具体问题具体判断，不能一刀切**；
> 关联订单号放在**点详情**的时候看。

## 这条规则会被写坏成什么样（都不是假想）

| 写坏的方式 | 表现 |
|---|---|
| 新增表单又内嵌回列表页顶部 | 用户选的是"按钮 → 单独一页"（字段还会继续长，内嵌会把记录区挤到屏幕外） |
| 左栏自己画一遍分类（不用共用版式） | 与商品/库存/结算的左栏行高、圆角各偏一点，一眼看出是两个时代做的 |
| 时间控件又变回一行胶囊 / 干脆没有 | 用户点名要"右上角时间药丸"（与账本页同一个控件） |
| **卡片按分类名 `when(...)` 判该突出什么** | 用户新加一个分类就失效（"突出什么"必须由**名册**带下来） |
| 卡片上金额/日期出现两次 | 同一屏两个数，用户只会以为其中一个坏了 |
| 订单来源只留在卡片上（详情里看不到） | 用户明确说"**点详情**的时候看这笔订单到底哪来的" |
| 改名不级联 | 挂着的开销变成"名册外的分类"，界面看着像钱丢了（后端拒绝 vs 悄悄改，见下） |

用法：python _tools/qa/_check_expense_page.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = ANDROID / "ui/dispatcher/ExpensesScreen.kt"
CREATE = ANDROID / "ui/dispatcher/ExpenseCreateScreen.kt"
CATS = ANDROID / "ui/dispatcher/ExpenseCategoriesScreen.kt"
LINK = ANDROID / "core/ExpenseLink.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
NAVGRAPH = ANDROID / "ui/nav/NavGraph.kt"
PICKER = ANDROID / "ui/common/ProductPicker.kt"
API = ROOT / "backend/app/api/v1/expense_categories.py"
#: 四个名册共用的「整份顺序」校验（2026-09-21 从四个端点里收出来的一份）
CAT_ORDER = ROOT / "backend/app/services/category_order.py"
EXPENSES_API = ROOT / "backend/app/api/v1/expenses.py"
ENUMS = ROOT / "backend/app/models/enums.py"
BOOTSTRAP = ROOT / "backend/app/core/schema_bootstrap.py"
MODEL = ROOT / "backend/app/models/expense.py"
TEST_KT = ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/ExpenseLinkTest.kt"

#: 反空转下限：认出的文件数与断言数低于它就先报错（"检查在空转"比"没有检查"更糟）
MIN_FILES = 10


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return strip_comments(p.read_text(encoding="utf-8"))


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

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)[:60]!r}" if m else "")


def main() -> int:
    c = Checker()
    files = {
        "screen": read(SCREEN),
        "create": read(CREATE),
        "cats": read(CATS),
        "link": read(LINK),
        "routes": read(ROUTES),
        "nav": read(NAVGRAPH),
        "picker": read(PICKER),
        # 共用组件（`DateFilterDialogs` 那份"两个弹层 + 状态机"住在它里面）
        "common_components": read(ANDROID / "ui/common/Components.kt"),
        "api": read(API),
        "cat_order": read(CAT_ORDER),
        "expenses_api": read(EXPENSES_API),
        "enums": read(ENUMS),
        "bootstrap": read(BOOTSTRAP),
        "model": read(MODEL),
        "accounting": read(ROOT / "backend/app/services/accounting_service.py"),
        "test": read(TEST_KT),
    }
    c.ok(f"认得出这一块的 {len(files)} 个文件（少了就先报错，别安静地跳过）", len(files) >= MIN_FILES)
    screen, create, cats, link = files["screen"], files["create"], files["cats"], files["link"]

    # ---- ① 一页一件事：新增开销是**单独一页** ----
    c.present("新增开销有自己的路由", files["routes"], r'const val EXPENSE_CREATE =')
    c.present("分类管理也有自己的路由", files["routes"], r'const val EXPENSE_CATEGORIES =')
    c.present("两个路由都在 NavGraph 里注册了", files["nav"], r"composable\(Routes\.EXPENSE_CREATE\)")
    c.present("分类管理页也注册了", files["nav"], r"composable\(Routes\.EXPENSE_CATEGORIES\)")
    c.present("列表页的按钮去新增页（不是内嵌表单）", files["nav"], r"onCreate = \{ navController\.navigate\(Routes\.EXPENSE_CREATE\) \}")
    c.absent("列表页**不再内嵌**新增表单（页面里没有 ExpenseCreateRequest / 保存开销）",
             screen, r"ExpenseCreateRequest\(|保存开销")
    c.present("新增页是整页表单（有 Scaffold 与返回）", create, r"fun ExpenseCreateScreen\(")

    # ---- ② 版式：时间药丸 + 共用左栏 + 底部两个按钮 ----
    c.present("右上角是**时间药丸**（与账本页同一个控件）", screen, r"DatePresetPill\(")
    # 2026-09-21 精简轮：五个页面那段「档位清单 + 自定义区间」的接线收进了
    # `ui/common/Components.kt::DateFilterDialogs`（原来各抄一遍，约 130 行）。
    # 锚点跟着搬：页面**真的调用**那份共用 host，"点开是档位清单"这条行为在 host 里。
    c.present("药丸点开是档位清单（走共用的 DateFilterDialogs）", screen, r"DateFilterDialogs\(")
    c.present("那份 host 里确实开着档位清单（行为没搬丢）",
              files["common_components"], r"fun DateFilterDialogs\([\s\S]{0,1200}?DatePresetDialog\(")
    c.absent("不再铺那一行日期胶囊", screen, r"DatePresetRow\(")
    c.present("左栏走**共用**的分类栏（不是自己画的）", screen, r"CategoryRail\(")
    c.present("分类栏的实现只有一处（ProductPicker.kt）", files["picker"], r"internal fun CategoryRail\(")
    c.present("底部左边是「分类管理」", screen, r'Text\("分类管理"\)')
    c.present("底部右边是「新增开销」", screen, r'Text\("新增开销"\)')

    # ---- ③ 卡片：突出哪一项由**分类**决定，不许按分类名 when ----
    c.present("卡片取「突出项」走共用的纯函数", screen, r"ExpenseLink\.primary\(")
    c.present("卡片取「次要项」也走它", screen, r"ExpenseLink\.secondary\(")
    c.absent("**不许**按分类名硬判（用户新加分类就失效）",
             screen, r'when \(e\.category\)|if \(e\.category == "')
    c.present("金额在卡片上**只出现一次**", screen, r'Text\(\s*"¥" \+ formatMoney\(e\.amount\)')
    # 卡片那一段里金额只渲染一次（详情弹层里那一处是另一个界面，不算重复）
    card_body = screen[screen.index("private fun ExpenseCard("):screen.index("private fun ExpenseDetailDialog(")]
    n_money = len(re.findall(r"formatMoney\(e\.amount\)", card_body))
    c.ok(f"卡片上金额只渲染一次（实测 {n_money}）", n_money == 1, "同一屏两个数，用户只会以为其中一个坏了")
    c.present("详情里能看到**订单来源**", screen, r'"关联订单"')
    c.present("详情里那一单可以点进去", screen, r'Text\("看这一单"\)')

    # ---- ④ 纯函数那一份：兜底 + 认不出当不关联 ----
    c.present("突出项有兜底顺序（分类说车辆但没填车 → 退到司机/订单）", link, r"VEHICLE -> listOf\(VEHICLE, DRIVER, ORDER\)")
    c.present("认不出的 link_kind 当「不关联」（不乱挑一个）", link, r"else -> return null")
    c.present("中文名表只有一份（分类管理页也用它）", cats, r"ExpenseLink\.CHOICES")
    c.present("纯函数有单测", files["test"], r"class ExpenseLinkTest")

    # ---- ⑤ 分类管理页：改名级联 / 删除拒绝 / 排序整份 ----
    c.present("排序复用商品那一份搬运逻辑（**一份实现**）", cats, r"moveItemTo\(")
    # ⚠️ 2026-09-21：这条规则收进了 `ui/common/CategoryRoster.kt::submittableIds`（四个名册共用），
    #    所以断言从"这一行出现过 `filter { it.id > 0 }`"改成"**这一页真的用了那份共用规则**"——
    #    只钉写法会在实现搬家之后变成恒绿，而这条规则本身（名册外的 id=0 不许发过去）照样要有牙
    #    （`_tools/qa/_check_category_roster.py` + 它的反向验证逐条注入盯着）。
    c.present("保存顺序只提交名册内的（名册外的 id=0 不带上去，走共用规则）", cats, r"submittableIds\(categories\)")
    c.present("「主要关联」在这一页可改", cats, r"fun setLinkKind\(")
    c.present("改名会级联（后端同一事务里 UPDATE expenses）", files["api"], r"Expense\.__table__\.update\(\)\.where\(Expense\.category == old_name\)")
    c.present("删除还有开销挂着的分类 → 拒绝并说明几笔", files["api"], r"还有 \{used\} 笔开销挂在这个分类下")
    # 2026-09-21：这段校验原来是四个端点各抄一遍，已收成 `services/category_order.py` 一份。
    # 断言跟着从"这个文件里有那句文案"改成"**这个端点真的调用了共用校验** + 文案在那份共用文件里"
    # —— 老写法在收口之后会变成**假红**（文案搬走了），而假红会被下一个人改成更松的写法。
    c.present("排序走共用的「整份顺序」校验（不是自己再抄一遍）",
              files["api"], r"ordered_ids\(by_id, body\.ids\)")
    c.present("「整份顺序」的判据只有一份（文案也在那一份里）",
              files["cat_order"], r"请提交\*\*完整\*\*的分类顺序")

    # ---- ⑥ 后端：分类是自由字符串（枚举已删），新分类自动补名册 ----
    c.absent("`ExpenseCategory` 枚举已删（留着就会被当成「合法取值表」）", files["enums"], r"class ExpenseCategory\(")
    c.present("`expenses.category` 是自由字符串（String(32)）", files["model"], r'__tablename__ = "expenses"[\s\S]{0,400}?category: Mapped\[str\] = mapped_column\(String\(32\)')
    c.present("新开销的分类会自动补进名册", files["accounting"], r"ensure_category\(db, clean\)")
    c.present("出参带上分类的 link_kind（客户端不许自己判）", files["expenses_api"], r"link_kind=link_kinds\.get")
    c.present("迁移把老英文键翻成中文名", files["bootstrap"], r"EXPENSE_CATEGORY_RENAME")
    c.present("名册表由迁移回填（没有开销时给八个默认分类）", files["bootstrap"], r"EXPENSE_CATEGORY_LINK\.get\(name")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：开销管理=时间药丸 + 分类栏 + 按分类突出的卡片；新增单独一页、分类可维护。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
