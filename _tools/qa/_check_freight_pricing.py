"""红线：**运费怎么算**（2026-09-21：运费分类 + 价目归计费规则 + 没匹配到就待定价）。

## 用户原话（这一节就是照它写的）

> 「这个运费模板，我们也可以按商品做一个相应的分类，也可以**创建分类进行管理**……他那个运费模板
>  是**有自己的一套分类的**，只是我们复用他那个代码和方法」；
> 「运费管理它会是有一个**拉取地点库里的路线**，按照地点库的路线进行定价」；
> 「**运费模板不会去匹配车型也不会匹配司机**，匹配车型和匹配司机在**计费规则**中……
>  他要在计费规则中取得这一个目录，**这一目录就归这个计费规则**，而这个规则在匹配对应的司机」；
> 「它就像匹配商品一样，勾选的时候就是一个商品界面，**可以全选本分类**，也可以单独勾」；
> 「计费规则……按单计费有**两种规则**：所有单统一价/统一提成，或者**按分类匹配**」；
> 「**如果没有匹配到**……这个订单就得派单员**手动去给他定价**，定价完之后，他会**新增对应的
>  地点/路线和对应的运费模板**，并且放到那个分类当中去」；
> 「司机管理他现在有固定工资和按单计费，但后面又加了一个计费规则，其实**计费规则就已经包括他们上面的**」。

## 这条规则会被写坏成什么样（都不是假想）

| 写坏的方式 | 表现 |
|---|---|
| 匹配里又去看车型/司机绑定 | 「价目归规则」这条链断了：同一单在两处带出两个价，**两边都不报错** |
| 候选不按"规则勾了哪几条价目"过滤 | 规则白勾：司机拿的是别人的价目 |
| 多条同样优先时"随便取一条" | 运费看运气 —— 该**报歧义让人挑** |
| 没挂规则/没勾价目却照常给价 | 用户以为配好了，帐上却是另一回事 |
| 没匹配到当成 0 元 | 司机白跑、账面查不到（旧伤：`pay.total <= 0` 连账单都不生成） |
| 没匹配到就自动标"异常单" | 与人工标的业务异常混在一列（用户选的是"只标待定价"） |
| 沉淀出来的价目不勾进司机的规则 | 「下次自动带价」是假的 —— 沉淀等于白存 |
| 沉淀顺手改历史单 | 已派出去的单记的是当时的运费 |
| 按分类定价时又填统一金额 | 「填了不生效」 |
| 分类模式的规则不算"有按单应付" | 派单快照写成 SALARY → 送达连账单都不生成 |
| 司机编辑页又长出「固定工资/计费方式」 | 同一个数两处写 |
| 勾了不存在的价目/分类 | 那条规则永远匹配不到，界面上看不出来 |

用法：python _tools/qa/_check_freight_pricing.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend/app"
A = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

PRICING = APP / "services/freight_pricing.py"
PAY = APP / "services/driver_pay.py"
RULES_API = APP / "api/v1/driver_billing_rules.py"
RULE_SCHEMA = APP / "schemas/driver_billing_rule.py"
RULE_MODEL = APP / "models/driver_billing_rule.py"
TPL_API = APP / "api/v1/freight_templates.py"
ORDERS = APP / "api/v1/orders.py"
CAT_API = APP / "api/v1/freight_categories.py"
CAT_MODEL = APP / "models/freight_category.py"
TPL_MODEL = APP / "models/freight_template.py"
BOOTSTRAP = APP / "core/schema_bootstrap.py"

KT_TPL = A / "ui/dispatcher/FreightTemplatesScreen.kt"
KT_TPL_VM = A / "ui/dispatcher/FreightTemplatesViewModel.kt"
KT_CATS = A / "ui/dispatcher/FreightCategoriesScreen.kt"
KT_UNPRICED = A / "ui/dispatcher/FreightPricingScreens.kt"
KT_RULE = A / "ui/dispatcher/DriverBillingRulesScreen.kt"
KT_USERS = A / "ui/dispatcher/UsersManageScreen.kt"
KT_USERS_VM = A / "ui/dispatcher/UsersManageViewModel.kt"
KT_REPORT = A / "ui/dispatcher/ReportCenter.kt"

MIN_FILES = 12


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
        "pricing": read(PRICING),
        "pay": read(PAY),
        "rules_api": read(RULES_API),
        "rule_schema": read(RULE_SCHEMA),
        "rule_model": read(RULE_MODEL),
        "tpl_api": read(TPL_API),
        "orders": read(ORDERS),
        "cat_api": read(CAT_API),
        "cat_model": read(CAT_MODEL),
        "tpl_model": read(TPL_MODEL),
        "bootstrap": read(BOOTSTRAP),
        "kt_tpl": read(KT_TPL),
        "kt_tpl_vm": read(KT_TPL_VM),
        "kt_cats": read(KT_CATS),
        "kt_unpriced": read(KT_UNPRICED),
        "kt_rule": read(KT_RULE),
        "kt_users": read(KT_USERS),
        "kt_users_vm": read(KT_USERS_VM),
        "kt_report": read(KT_REPORT),
    }
    c.ok(f"认得出这一块的 {len(files)} 个文件（少了就先报错）", len(files) >= MIN_FILES)

    # ---- ① 匹配：价目归规则，候选来自"司机的规则勾了哪几条" ----
    print("\n① 运价匹配 = 一处实现，而且候选来自「这个司机的规则勾了哪几条价目」")
    c.present("匹配算法在 services/freight_pricing.py", files["pricing"], r"def quote_for\(")
    c.present("路线判据来自**地点库的线路**（终点等于这一单的送货地址）",
              files["pricing"], r"ShipperAddress\.detail_address == addr")
    c.present("候选先按「规则勾的价目」过滤",
              files["pricing"], r"FreightTemplate\.id\.in_\(picked_template_ids\)")
    c.present("规则勾的价目来自 DriverBillingRuleTemplate",
              files["pricing"], r"DriverBillingRuleTemplate\.template_id")
    c.present("没挂规则 → 说清原因（进待定价，不静默给 0）",
              files["pricing"], r"这个司机还没挂计费规则")
    c.present("规则没勾价目 → 也说清", files["pricing"], r"还没勾价目")
    c.absent("匹配里**不许**看车型（价目不匹配车型）", files["pricing"], r"vehicle_type")
    c.absent("匹配里**不许**看司机绑定（价目不绑司机）", files["pricing"], r"FreightTemplateDriver")
    c.present("多条同样优先 → **不猜**，把候选交回去",
              files["pricing"], r"if len\(same\) > 1:[\s\S]{0,400}?ambiguous=\[")
    c.present("没匹配到要说明为什么（界面直接显示那句话）",
              files["pricing"], r"这条路线还没有价目")
    c.present("报价端点只有一处（界面不许自己算）", files["tpl_api"], r'@router\.get\("/quote"')
    c.absent("App 侧没有第二份匹配实现（`underFreightTab` 只管分类栏分组）",
             files["kt_tpl_vm"], r"quote_for|ShipperAddress|detail_address")

    # ---- ② 运费分类名册：自己一套，形制照商品分类 ----
    print("\n② 运费分类 = 自己的一套名册（形制照商品分类那一套）")
    c.present("有独立的运费分类表", files["cat_model"], r'__tablename__ = "freight_categories"')
    c.present("名册只有名字 + 顺序（与商品/开销分类同形）",
              files["cat_model"], r"name: Mapped\[str\] = mapped_column\(String\(32\), unique=True")
    c.present("删除还有人在用时**拒绝**（并说有价目/规则几处）",
              files["cat_api"], r"if used_t or used_r:[\s\S]{0,400}?先改到别的分类（或改个名）再删")
    c.absent("改分类名**不级联**改价目（两条线按编号挂）",
             files["cat_api"], r"FreightTemplate\.__table__\.update")
    c.present("模板↔分类是多对多（一个模板可以多个分类）",
              files["tpl_model"], r'__tablename__ = "freight_template_categories"')
    c.present("挂一个不存在的分类会被拒（否则那条价目永远匹配不到）",
              files["tpl_api"], r"这些运费分类不存在")

    # ---- ③ 价目 ↔ 计费规则（这一轮的新链子） ----
    print("\n③ 价目归计费规则：规则里勾价目（像选商品那样）")
    c.present("价目↔规则是多对多表",
              files["rule_model"], r'__tablename__ = "driver_billing_rule_templates"')
    c.present("规则收发 template_ids（编号）", files["rules_api"], r"template_briefs=_template_briefs")
    c.present("价目摘要**带价格**（卡片要答「跑一趟多少钱」，光有路线名答不上来）",
              files["rules_api"], r"label\} ¥")
    c.present("App 卡片把价目**收敛**成「条数 + 前两条 + 等」（勾 20 条也不许把卡片撑爆）",
              files["kt_rule"], r"价目 \$\{briefs\.size\} 条")
    c.present("没勾价目的规则在卡片上是**红字提示**（否则用户看不出这条规则还没配好）",
              files["kt_rule"], r"还没勾价目 —— 派给这个司机的单会进")
    c.present("勾了不存在的价目会被拒", files["rules_api"], r"勾的价目里有对不上的编号")
    c.present("模板出参带「被哪几份规则用着」", files["tpl_api"], r"_rule_names\(db")
    c.present("App 有选品页那种价目选择器（左分类 + 全选本分类）",
              files["kt_rule"], r"全选本分类")
    c.present("选择器按分类栏过滤（与模板页同一套分组规则）",
              files["kt_rule"], r"vm\.pickerItems\(\)|vm\.pickerTabs\(\)")
    c.absent("运费模板表单里**没有**车型与司机两段",
             files["kt_tpl"], r'Text\("适用车型"\)|可用司机（可多选')
    c.absent("运费模板 VM 不再发 vehicle_type / driver_ids",
             files["kt_tpl_vm"], r"vehicleType = draftVehicle|driverIds = draftDriverIds")

    # ---- ④ 计费规则：所有单统一 / 按分类匹配 ----
    print("\n④ 计费规则的「按单计费」两种形态（互斥）")
    c.present("规则上有 piece_mode（uniform / category）",
              files["rule_model"], r"piece_mode: Mapped\[str\] = mapped_column")
    c.present("按分类的金额表是一张真表",
              files["rule_model"], r'__tablename__ = "driver_billing_rule_categories"')
    c.present("选了按分类就必须给至少一个分类填金额",
              files["rule_schema"], r"就要至少给一个分类填金额")
    c.present("按分类时**不许**再填统一的每单金额（填了不生效）",
              files["rule_schema"], r"or 0\)\) > 0[\s\S]{0,300}?就不要再填统一的每单金额")
    c.present("没选按分类却填了分类金额 → 也拒绝", files["rule_schema"], r"否则那些数字不会生效")
    c.present("钱只有一处算法：基价先按 piece_mode 解析",
              files["pay"], r"base_piece, base_rate = rule\.piece_amount, rule\.commission_rate")
    c.present("逐单覆盖仍然优先（派单员定的比例不许被规则盖掉）",
              files["pay"], r"rate = money\(rate_override\) if rate_override is not None else base_rate")
    c.present("按分类的规则**必须算「有按单应付」**（否则快照写成 SALARY、账单都不生成）",
              files["pay"], r"if self\.by_category_pay:\s*\n\s*return True")
    c.present("分类表进快照（改规则不追溯已派单）", files["pay"], r'"piece_mode": rule\.piece_mode')

    # ---- ⑤ 没匹配到 → 待定价 → 手动定价 → 沉淀 ----
    print("\n⑤ 没匹配到 = 待定价（**不是异常单**）→ 派单员定价 → 沉淀")
    c.present("待定价的口径在订单列表上（已派单 + 没运费）",
              files["orders"], r"Order\.freight_fee\.is_\(None\)")
    c.present("手动定价端点", files["orders"], r"def price_freight\(")
    c.present("定价会写分类（编号 + 名字快照）",
              files["orders"], r"order\.freight_category_id = body\.category_id")
    c.present("可选沉淀：建/找**线路**", files["orders"], r'saved\["route_created"\] = route\.id')
    c.present("可选沉淀：建/改**价目**并绑分类",
              files["orders"], r"FreightTemplateCategory\(template_id=tmpl\.id")
    c.present("沉淀出来的价目**自动勾进这位司机的规则**（否则「下次自动带价」是假的）",
              files["orders"], r"DriverBillingRuleTemplate\(rule_id=int\(rule_id\)")
    c.absent("沉淀不再「绑司机」（价目不绑司机）", files["orders"], r"FreightTemplateDriver\(")
    c.present("沉淀有审计（改钱的动作必须能回答「谁定的」）",
              files["orders"], r"OperationAction\.ORDER_FREIGHT_PRICE")
    c.present("新的审计码有中文名（App 侧）", files["kt_report"], r'"ORDER_FREIGHT_PRICE" ->')
    c.present("App 有「待定价」一页（点一行就定价）", files["kt_unpriced"], r"fun UnpricedOrdersScreen\(")
    # ⚠️ 2026-09-21 真机抓到的静默 bug：`list_orders` 有**两条**查询构造路径（派单员+搜索词 用 `stmt`、
    #    普通列表 用 `q`），同一个过滤条件要各写一遍。`unpriced` 一开始只加在前者上 ——
    #    待定价页（不带 q）于是返回**全部**订单，而页面上写着"这些单已经派出去了、但还没有运费"。
    #    静态检查当时只断言"参数存在 / 这段文本在"，两处只坏一处时它照样绿 —— 所以这里**数两条路径**。
    _missing = [
        frag
        for frag in (
            "if unpriced:",
            "Order.driver_id.isnot(None),",
            "Order.freight_fee.is_(None),",
            "Order.status.notin_([OrderStatus.PENDING_DISPATCH, OrderStatus.CANCELLED])",
        )
        if files["orders"].count(frag) < 2
    ]
    c.ok(
        "待定价的过滤在**两条查询路径上都写全了**（漏一条 = 待定价页静默返回全部订单）",
        not _missing,
        f"只出现一次的片段：{_missing}",
    )
    c.present("App 定价时能选分类 + 勾「存成价目」",
              files["kt_unpriced"], r"存成价目（下次自动带价）")
    # 用户 2026-09-21 第二轮：「他在带定价的时候**要么直接沿用司机已有规则**进行定价，要么假如
    # 以前没有规则的话，那就走**普通的定价规则**（这个模板的规则，它规一个分类）」——两级兜底，
    # 都用同一个已存在的 `/freight-templates/quote`（`driver_id` 传 / 不传），不新增后端逻辑。
    c.present("定价时**先按这位司机的规则**问价（`driverId = o.driverId`）",
              files["kt_unpriced"], r"quoteFreight\(o\.id, driverId = o\.driverId")
    c.present("规则里没勾到 → 退回**运费模板**那一层（`driverId = null`：只看路线 + 分类）",
              files["kt_unpriced"], r"quoteFreight\(o\.id, driverId = null")
    c.present("同样优先多于一条时**不猜**，把候选列出来让人点一条",
              files["kt_unpriced"], r"vm\.pickQuote\(c\)")
    seg_price = re.search(r"def price_freight\([\s\S]*?@router\.post\(\"/\{order_id\}/assign", files["orders"])
    c.ok("手动定价那一段里没有 `is_exception = True`",
         seg_price is not None and "is_exception = True" not in seg_price.group(0),
         "改钱的动作不该顺手改业务状态")

    # ---- ⑥ 司机管理编辑页：怎么算钱只有一个入口 ----
    print("\n⑥ 司机管理编辑页：怎么算钱只有一个入口")
    c.absent("编辑弹窗里**没有**「固定工资」输入框", files["kt_users"], r'placeholder = "固定工资')
    c.absent("编辑弹窗里**没有**「计费方式」下拉", files["kt_users"], r'label = \{ Text\("计费方式"\)')
    c.absent("VM 里不再发 billing_mode / salary",
             files["kt_users_vm"], r"billingMode = draftBillingMode|salary = draftSalary")
    c.present("只剩「计费规则」这一个入口", files["kt_users"], r"计费规则（他怎么算钱就看这一项）")
    c.present("没挂规则时**如实说**兜底口径", files["kt_users"], r"没挂规则 → 按车型的老口径兜底")

    # ---- ⑦ 卡片：按钮贴**最右**、和最后一行信息同排（用户 2026-09-21 第二轮修正：
    #      「编辑和删除移到最右边去……卡片高度变窄一点」—— 按钮单独占一行 = 卡片白白高一行） ----
    print("\n⑦ 卡片版式：编辑/删除贴**最右**、和最后一行信息同排（卡片少一行）")
    c.present("运费模板卡片：信息与按钮同一个 Row（按钮被挤到最右）",
              files["kt_tpl"], r"Row\(Modifier\.fillMaxWidth\(\), verticalAlignment = Alignment\.CenterVertically\)")
    c.present("计费规则卡片：同上",
              files["kt_rule"], r"Row\(Modifier\.fillMaxWidth\(\), verticalAlignment = Alignment\.CenterVertically\)")
    c.present("计费规则卡片的信息行确实让了宽度（`weight(1f)`，否则按钮挤不到最右）",
              files["kt_rule"], r"modifier = Modifier\.weight\(1f\),\s*\n\s*text = buildString")
    c.absent("运费模板卡片按钮**不再**单独占一行靠左", files["kt_tpl"], r"Arrangement\.Start")
    c.absent("计费规则卡片按钮**不再**单独占一行靠左", files["kt_rule"], r"Arrangement\.Start")

    # ---- ⑧ 反空转 ----
    print("\n⑧ 反空转")
    anchors = [
        (files["pricing"], r"class Quote"),
        (files["pricing"], r"def quote_for\("),
        (files["pay"], r"PIECE_MODES"),
        (files["cat_api"], r"def reorder_categories\("),
        (files["orders"], r"unpriced: bool = Query"),
        (files["kt_unpriced"], r"class UnpricedOrdersViewModel"),
        (files["kt_cats"], r"class FreightCategoriesViewModel"),
        (files["kt_rule"], r"class FreightPickSheet|private fun FreightPickSheet"),
        (files["bootstrap"], r"freight_category_id"),
    ]
    missing = [p for f, p in anchors if not re.search(p, f)]
    c.ok(f"{len(anchors)} 个关键锚点都在（缺一个说明判据失配）", not missing, f"缺：{missing}")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：价目归计费规则、分类一套、按分类给司机算钱、没匹配到进待定价能沉淀。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
