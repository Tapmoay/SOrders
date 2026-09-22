"""红线：**预订单（订单模板）**——后端 + AI + 界面（2026-09-22 用户要求）。

## 用户原话
> 「其实我们**还可以再增加一个叫做「预定单」界面**，**专门去管理**预设的订单 ——
> 就是**预设好的订单**，这个**参数没有变**，**直接下单就可以了**……**这些也给 AI 全部开放**。」

## 这一块最容易悄悄坏掉的七件事（每条都有判据）
1. **预设单偷偷变成了"第二套下单路径"**：一旦页面/AI 自己去建订单，订单状态核对、库存、账本口径
   就会有三份实现。⛔ 判据：这一页**不许出现任何建单调用**，AI 那边也不许有"从预设单下单"的动作。
2. **行里存了单价**：价格会变，存旧价＝几个月后按旧价下单，而界面上看不出来。
3. **运费"空"被当成"0"**：每张没填运费的预设单都变成免运费单 —— 一键下单时钱就少收了。
4. **预填把用户改过的值冲回去**：预填只能发生**一次**（LaunchedEffect 的 key），
   而且商品行必须**整份替换**（追加会把上次没提交干净的行混进来 = 多订一样货）。
5. **价格不走唯一那份口径**：预填时的单价必须走下单页的 `priceFor`（按货主专属价算），
   不许自己再写一遍"取 defaultUnitPrice"。
   ⚠️ **2026-09-22 补（真机错价）**：光"走了 `priceFor`"还不够 —— 专属价是**异步**取回来的，
   在它到齐之前算出来的行价必然是默认价，而**已经填好的行不会**被重算。
   所以还有三条：**预填先等价到齐再填行** · **价到齐/换货主后重算已有的行** ·
   **价没拿到就不许下单**（回退默认价对谈好价的批发商＝多收钱，静默错钱）。
   （旧版本只钉了字面上有没有 `priceFor(`，所以带着这个 bug 一路全绿 —— 教训：判据要钉**时序**，
   不是钉**字面**。）
6. **常用度记在"点开"而不是"下单成功"**：那样列表会按"谁点开过"排序（用户要的是"我常用哪一张"）。
7. **AI 那一头漏登记**：四个写动作、一个读动作都要进目录/工具清单，读能力还要被某个 App 模块认领
   （否则用户从界面上根本看不到这个功能 —— `_app_feature_coverage` 会红）。

用法：python _tools/qa/_check_order_templates.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
COMMON = ANDROID / "ui/common"
API = ROOT / "backend/app/api/v1/order_templates.py"
MODEL = ROOT / "backend/app/models/order_template.py"
SCHEMA = ROOT / "backend/app/schemas/order_template.py"
TEST = ROOT / "backend/tests/test_order_templates.py"
SCREEN = ANDROID / "ui/dispatcher/OrderTemplatesScreen.kt"
CREATE_VM = ANDROID / "ui/shipper/OrderCreateViewModel.kt"
CREATE_SCREEN = ANDROID / "ui/shipper/OrderCreateScreen.kt"
# 「新建 / 编辑预订单」= 单独一页（2026-09-22 用户：「还可以新建一个订单」）
FORM_SCREEN = ANDROID / "ui/dispatcher/OrderTemplateFormScreen.kt"
# 预订单分类名册（2026-09-22 用户：「左边是分类管理…右边就是订单」）
CAT_API = ROOT / "backend/app/api/v1/order_template_categories.py"
CAT_MODEL = ROOT / "backend/app/models/order_template_category.py"
CAT_SCHEMA = ROOT / "backend/app/schemas/order_template_category.py"
CATS_SCREEN = ANDROID / "ui/dispatcher/OrderTemplateCategoriesScreen.kt"
ROUTES = ANDROID / "ui/nav/Routes.kt"
NAV = ANDROID / "ui/nav/NavGraph.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
AI_DECL = ANDROID / "ai/AiWriteOrderTemplates.kt"
AI_HANDLER = ANDROID / "ai/AiWriteOrderTemplateHandlers.kt"
AI_RES = ANDROID / "ai/AiResources.kt"
AI_SVC = ANDROID / "ai/AiWriteService.kt"
COVERAGE = ROOT / "_tools/ai/_app_feature_coverage.py"
ENDPOINTS = ROOT / "docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is not None, f"没找到 /{pattern}/")

    def absent(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is None, f"不该出现 /{pattern}/ 却出现了")


def main() -> int:
    c = Checker()
    for p in (API, MODEL, SCHEMA, TEST, SCREEN, CREATE_VM, CREATE_SCREEN, ROUTES, NAV, MODULES,
              AI_DECL, AI_HANDLER, AI_RES, AI_SVC, COVERAGE, ENDPOINTS, DESIGN, LOCATOR,
              CAT_API, CAT_MODEL, CAT_SCHEMA, CATS_SCREEN, FORM_SCREEN):
        if not p.exists():
            print(f"❌ 文件不存在：{p}")
            return 1

    api = strip_comments(read(API))
    model = strip_comments(read(MODEL))
    schema = read(SCHEMA)
    test = read(TEST)
    screen = strip_comments(read(SCREEN))
    vm = strip_comments(read(CREATE_VM))
    routes = strip_comments(read(ROUTES))
    nav = strip_comments(read(NAV))
    modules = strip_comments(read(MODULES))
    ai_decl = strip_comments(read(AI_DECL))
    ai_handler = strip_comments(read(AI_HANDLER))
    ai_res = strip_comments(read(AI_RES))
    cat_api = strip_comments(read(CAT_API))
    cat_model = strip_comments(read(CAT_MODEL))
    cat_schema = read(CAT_SCHEMA)
    cats_screen = strip_comments(read(CATS_SCREEN))
    form_src = strip_comments(read(FORM_SCREEN))

    # ---- ① 后端：六个端点、只有派单员、软删 + 恢复 ----
    # ⚠️ 模式里**不能带结尾的 `)`**：这些装饰器后面还有 `response_model=…` / `status_code=…`
    #    （写成 `@router\.get\(""\)` 会一个都匹配不上 —— 实测踩过一次）。
    for verb, path in (
        (r'@router\.get\(""', "列表"),
        (r'@router\.post\(""', "新建"),
        (r'@router\.patch\("/\{template_id\}"', "改"),
        (r'@router\.post\("/\{template_id\}/use"', "记一次使用"),
        (r'@router\.delete\("/\{template_id\}"', "删"),
        (r'@router\.post\("/\{template_id\}/restore"', "恢复"),
    ):
        c.present(f"{path}端点存在", api, verb)
    n_guard = len(re.findall(r"Permission\.ORDER_EDIT", api))
    c.ok(f"六个端点全都守在 ORDER_EDIT 上（= 只有派单员；实测 {n_guard} 处）", n_guard == 6,
         f"实际 {n_guard}（少一处就是漏权限）")
    c.present("列表按常用度排序（走共用的 with_popularity）",
              api, r"usage_service\.with_popularity\(")
    c.present("那条 kind 是 KIND_ORDER_TEMPLATE（与记一次那处同源）",
              api, r"usage_service\.KIND_ORDER_TEMPLATE")
    c.present("删除是伪装删除（del_suffix 给出可见痕迹）", api, r"del_suffix\(tpl\.name, tpl\.id, 64\)")
    # ⚠️ **数它出现几次**（不是"有没有"）：改与「记一次使用」两条路上各有一处，
    #    只留一处的话另一条路照样能改到回收站里的预设单 —— 而"有没有"那条判据会一直是绿的
    #    （反向验证实测抓到过一次）。这里同时钉住"每条能改到 tpl 的路都挡了"。
    n_alive = len(re.findall(r'ensure_alive\(tpl, "预设单"', api))
    c.ok("回收站里的预设单改不了（改 + 记一次使用**两条路都要挡**）", n_alive == 2, f"实际 {n_alive} 处")
    c.present("恢复把后缀去掉（还原原名）", api, r"tpl\.name = tpl\.name\[: -len\(suffix\)\]")
    c.ok("每个写端点都写审计（建/改/删/恢复四处 UPsert/Delete/Restore）",
         len(re.findall(r"write_log\(", api)) >= 4 and "OperationAction.ORDER_TEMPLATE_DELETE" in api
         and "OperationAction.ORDER_TEMPLATE_RESTORE" in api,
         f"write_log 出现 {len(re.findall(r'write_log', api))} 次")

    # ---- ② 物流费：空 ≠ 0（这条最贵）----
    c.present("空串/None 一律当「不预设」（返回 None，不是 0）",
              api, r'if not text:\s*\n\s*return None')
    c.present("金额出参统一两位小数（走 q2）", api, r"str\(q2\(Decimal\(row\.freight_fee\)\)\)")
    c.ok("模型那边也把「空 = 不预设」写进注释（⛔ 别只写在代码里）",
         "不预设" in model and "免运费" in model)
    c.present("预设运费的字段可空（None = 不预设）",
              MODEL.read_text(encoding="utf-8"), r"freight_fee: Mapped\[Decimal \| None\] = mapped_column\(Numeric\(12, 2\), nullable=True\)")

    # ---- ③ 行：只有商品与数量，且三条拒绝规则 ----
    c.absent("行里**没有单价**（价格会变，存旧价＝以后按旧价下单）",
             schema, r"class OrderTemplateLine[\s\S]{0,400}?price")
    c.present("没有商品的行直接拒绝", api, r"第 \{i\} 行没有选商品")
    c.present("同一个商品出现两次也拒绝（让用户自己合成一行）", api, r"又出现了一次，请合成一行")
    c.present("行数上限（与 schema 的 MAX_LINES 同一处）", schema, r"MAX_LINES = 30")
    c.present("行的 JSON 列把 None 归一到 []（老库/裸 SQL 会写 NULL）",
              schema, r'@field_validator\("lines", mode="before"\)')

    # ---- ④ 货主：能换、也能清空（clear_shipper）----
    c.present("显式清空货主的开关存在（Android 的 explicitNulls 会把 null 丢掉）",
              schema, r"clear_shipper: bool = False")
    c.present("端点认这个开关", api, r"if body\.clear_shipper:\s*\n\s*tpl\.shipper_id = None")
    c.present("`shipper_id` 键出现就写（model_fields_set）", api, r'elif "shipper_id" in sent:')

    # ---- ⑤ 后端测试：三条口径都有断言 ----
    c.present("测试钉住「空 ≠ 0」", test, r'assert blank\["freight_fee"\] is None')
    c.present("测试钉住「部分更新不覆盖没提到的键」", test, r'assert len\(got\["lines"\]\) == 2')
    c.present("测试钉住「软删 + 恢复 + 回收站里改不了」", test, r'assert blocked\.status_code == 400')
    c.present("测试钉住「只有派单员能管」", test, r"def test_只有派单员能管预设单")

    # ---- ⑥ 界面：只带参去下单，绝不自己建单 ----
    c.present("那一格存在且指向它自己那一页",
              modules, r'ModuleEntry\("预订单", Routes\.DISPATCH_ORDER_TEMPLATES')
    c.present("路由常量存在", routes, r'const val DISPATCH_ORDER_TEMPLATES = "dispatcher/order-templates"')
    c.present("NavGraph 注册了它", nav, r"composable\(Routes\.DISPATCH_ORDER_TEMPLATES\)")
    c.present("「用这张下单」是**带参跳下单页**（不是在这里建单）",
              nav, r'Routes\.DISPATCH_ORDER_CREATE \+ "\?template=" \+ t\.id')
    c.present("下单页那条路由认 ?template=",
              nav, r'Routes\.DISPATCH_ORDER_CREATE \+ "\?template=\{template\}"')
    c.present("下单页把 template 传给预填", nav, r"prefillTemplateId = entry\.arguments\?\.getLong\(\"template\"\) \?: 0L")
    for bad in ("createOrder(", "repo.createOrder"):
        c.absent(f"这一页**不许**出现建单调用（{bad}）—— 下单只有一条路", screen, re.escape(bad))

    # ---- ⑦ 界面：撤回在手边、说明如实 ----
    c.present("删除二次确认（危险操作，走共用的危险确认件）", screen, r"DangerConfirmDialog\(")
    c.present("删完给「撤回」（用户定的硬规矩：手边要有撤销入口）",
              screen, r'actionLabel = "撤回"')
    c.present("撤回走 restore 那条路", screen, r"fun restoreLastDeleted\(")
    # ⚠️ 2026-09-22 第二轮：这句"不含单价"的说明**从列表页搬到了表单页**（用户要求把
    #    「预设单是什么」那张常驻解释卡改成提示的形式）——**事实本身不许丢**，所以改成
    #    "在表单页里必须还在"。运费那句同理。
    c.present("「不含单价」这条事实还在（落点＝新建/编辑表单页）", form_src, r"预设单不含单价")
    c.present("「运费只是参考」这条事实还在（下单接口根本不收运费）",
              form_src, r"预设运费只是参考值")
    c.present("列表页那句解释走 `Hint`（总开关能关掉，不是常驻说明卡）", screen, r"Hint\(")
    c.absent("列表页不再有那张常驻解释卡（用户：「这个解释没必要…绑到提示当中」）",
             screen, r"预设单是什么")

    # ---- ⑧ 预填：一次、整份替换、价格走唯一口径、常用度记在下单成功 ----
    # ⚠️ 这一段**只看 `prefillFromTemplate` 的函数体**：整个 VM 里还有别的地方会碰 `lines`,
    #    在全文件上搜"有没有 lines.clear()"会被别处满足 —— 判据就成了空转（反向验证抓到过）。
    pf_m = re.search(r"fun prefillFromTemplate\(([\s\S]*?)\n    \}\n", vm)
    prefill = pf_m.group(1) if pf_m else ""
    c.ok("取到 prefillFromTemplate 的函数体（取不到这几条检查就是空转）", len(prefill) > 500)
    c.present("预填只发生一次（LaunchedEffect 的 key 是 template id）",
              strip_comments(read(CREATE_SCREEN)), r"LaunchedEffect\(prefillTemplateId\)")
    c.present("商品行**整份替换**（lines.clear()）", prefill, r"lines\.clear\(\)")
    c.present("单价走唯一那份口径（priceFor：按货主专属价算）", prefill, r"priceFor\(it\)")
    c.present("商品已不在库里时**说出来**（不静默留空价）",
              prefill, r"已不在商品库，这一行删掉才能下单")
    # ⛔ 而且**不许**再让用户"自己填价"：下单页没有单价输入框（红线
    #    `_check_input_rules.py::NO_PRICE_EDIT_FILES`），那是一句用户照做不了的假话（2026-09-22 修）。
    c.absent("不再让用户去填一个页面上根本不存在的框", prefill, r"价格要自己填")
    # ⚠️ **顺序**才是这个 bug 的根：专属价是异步取的，`setShipper` 只是**发起**请求，
    #    紧接着算行价拿到的必然是"规则还没到"的回退价（默认价），而后来的规则**不会**
    #    重算已经填好的行 —— 用户量到的就是 20 而不是谈好的 10。
    # ⚠️ 用 `find` 不用 `index`：少了任一边要**报红**，不是让这条检查自己崩掉
    #    （崩掉时没有任何 [FAIL] 行，反向验证会把它读成"红线没抓到"，把注入放过去 —— 真发生过）。
    i_await, i_price = prefill.find("awaitPriceRules()"), prefill.find("priceFor(it)")
    c.ok("预填**先等这个货主的专属价到齐**再算行价",
         i_await >= 0 and i_price >= 0 and i_await < i_price,
         "顺序必须是 setShipper → awaitPriceRules() → priceFor；反了这个 bug 就回来了")
    # ⛔ **报价依据只有一处**（2026-09-22 真机抓到）：横幅是"回执"（写完就定住），
    #    报价依据是**实时状态**（换货主就变）。两处都写 → 同屏上同时出现
    #    "按商品默认售价"和"按「永盛食品」的专属价"两句互相打架的话。
    c.absent("预填横幅里**不许**再写一遍报价依据（会与商品明细那行打架）", prefill, r"priceBasisText\(")
    c.present("先把商品库拉回来再填行（不然价格一片空白）",
              prefill, r"if \(products\.isEmpty\(\)\) \{\s*\n\s*products = container\.repo\.products\(\)")
    c.present("货主先设（setShipper 会拉专属价，顺序反了会先按默认价算）",
              prefill, r"if \(t\.shipperId != null\) setShipper\(t\.shipperId, null\)")
    c.present("常用度记在**下单成功之后**", vm, r"success = true[\s\S]{0,600}?useOrderTemplate\(tid\)")

    # ---- ⑨ AI：四个写动作 + 一个读动作 + 撤回 + 认领 ----
    for act in ("ORDER_TEMPLATE_CREATE", "ORDER_TEMPLATE_UPDATE", "ORDER_TEMPLATE_DELETE",
                "ORDER_TEMPLATE_RESTORE"):
        c.present(f"{act} 已声明", ai_decl + read(ANDROID / "ai/AiWrite.kt"), act)
    c.present("create/update 是手写处理器（要收一组商品+数量）",
              ai_handler, r"class OrderTemplateWriteHandler\(")
    c.present("参数表走共用的 crudParams（唯一一份推导）",
              ai_decl, r"params = crudParams\(targets, fields\)")
    c.present("撤回按资源表声明（改→写回旧值 / 删→恢复）",
              ai_res, r'AiWrites\.ORDER_TEMPLATE_RESTORE,\s*\n?\s*AiInverse\(AiWrites\.ORDER_TEMPLATE_DELETE')
    # ⚠️ 判据要看到**认领的内容**（`["预订单"…]`），不只看键名：只看键名的话"把读列清空"
    #    这种破坏照样绿（反向验证当场抓到过）。
    c.present("读能力被 App 模块认领（否则用户在界面上看不到它）",
              read(COVERAGE), r'"预订单": \(\s*\n?\s*\["预订单"')
    c.present("端点索引里有它（文档不许过期）",
              read(ENDPOINTS), r"GET /api/v1/order-templates")
    c.present("分类名册那一条读能力也被同一格认领",
              read(COVERAGE), r'"预订单分类"')
    c.present("端点索引里有分类名册",
              read(ENDPOINTS), r"GET /api/v1/order-template-categories")
    c.absent("AI 那边**没有**「从预设单下单」的动作（下单走已有的 orders.create）",
             ai_decl, r'id = "order_templates\.create_order"')

    # ---- ⑩ 文档指针 ----
    # ⚠️ 判据要**同时**要求"指路本判据"与"指路后端那一半"：只要求前者的那次被反向验证抓到了
    #    （我的新小节里也提到了本判据的文件名 → 注入把原来那一句换掉之后，判据照样绿＝空转）。
    design = read(DESIGN)
    c.ok("设计规范里写了预订单那一条规矩（并指路本判据 + 指路后端那一半）",
         "预订单" in design and "_check_order_templates.py" in design
         and "api/v1/order_templates.py" in design,
         "缺一条：预订单的规矩 + 指路到本文件与后端那个文件")
    loc = read(LOCATOR)
    c.ok("定位表里指到了预订单（并点名本判据）",
         "预订单" in loc and "_check_order_templates.py" in loc,
         "改这一块的人应当能从定位表找到本文件")

    # ---- ⑪ 报价必须绑到「这个货主的价」：异步取价的**时序**（2026-09-22 真机错价补的）----
    # ⚠️ 旧的第 ⑤ 组只钉了"字面上有没有 `priceFor(`"—— 而**带着这个 bug 它一路全绿**：
    #    代码确实走了 `priceFor`，只是走得太早（专属价还在路上，`priceFor` 回退默认价）。
    #    所以这一节钉的是**顺序**与**缺价时的行为**，不是字面。

    def body_of(sig: str) -> str:
        m = re.search(re.escape(sig) + r"([\s\S]*?)\n    \}\n", vm)
        return m.group(1) if m else ""

    fetch_body = body_of("private suspend fun fetchPriceRules(")
    apply_body = body_of("private fun applyPriceRules(")
    await_body = body_of("private suspend fun awaitPriceRules(")
    load_body = body_of("fun loadPriceRulesFor(")
    submit_body = body_of("fun submit(")
    price_body = body_of("fun priceFor(")
    c.ok("取到这几段的函数体（取不到下面就是在空转）",
         all(len(b) > 60 for b in (fetch_body, apply_body, await_body, load_body, submit_body, price_body)),
         f"长度={[len(b) for b in (fetch_body, apply_body, await_body, load_body, submit_body)]}")

    c.present("重算是一个**纯函数**（唯一实现，能被单测直接调）",
              vm, r"fun repriceLines\([\s\S]{0,160}?priceOf: \(Long\) -> String\?,")
    c.present("规则落地是**唯一写入点**", vm, r"private fun applyPriceRules\(")
    c.present("落完规则就**重算已有的行**（先挑商品、后换货主 → 行上留着上一个货主的价）",
              apply_body, r"repriceFromRules\(\)")
    c.present("换主体时先清掉上一份规则（报价串号）", load_body, r"if \(priceRulesShipper != sid\)")
    c.present("主体成了「没有规则的人」（临时货主/清空）也要重算", load_body, r"repriceFromRules\(\)")
    c.present("取数是 suspend（要能被预填 await）", vm, r"private suspend fun fetchPriceRules\(")
    c.present("取数失败**返回 null**（＝「不知道」，不是「没有专属价」）",
              fetch_body, r"catch \(_: Exception\) \{[\s\S]{0,300}?\n\s+null\b")
    c.absent("失败**不许**退化成空 map（那等于宣称「这个货主没有专属价」，会按默认价把单发出去）",
             fetch_body, r"emptyMap\(\)")
    c.present("没拿到（null）就什么都不写：`priceRulesShipper` 保持「未知」",
              apply_body, r"if \(loaded == null\) return")
    c.present("预填等的那一下：join 在飞的请求 + 兜底补一次",
              await_body, r"priceRulesJob\?\.join\(\)[\s\S]{0,200}?if \(priceRulesShipper != subject\)")
    c.present("等完「到底拿到没有」不用返回值往外传：界面看 `priceBasisText`、钱由提交闸门把住",
              await_body, r"applyPriceRules\(subject, fetchPriceRules\(subject\)\)")
    c.present("提交那道**报价闸门**：还没拿到这个主体的价就不许下单",
              submit_body, r"if \(subject != null && priceRulesShipper != subject\)")
    c.present("被闸门挡下时**顺手再拉一次**（用户再点一下就能成，不会永久卡住）",
              submit_body, r"loadPriceRulesFor\(subject\)")
    c.present("提示是中文且说清了怎么办",
              submit_body, r'error = "价格还没拿到（网络慢或断了），请再点一次提交"')
    c.present("没有价的那一行**挡住**（后端 unit_price 是数字，空串只会变成一个看不懂的 422）",
              submit_body, r"noPrice != null -> error = ")
    c.present("报价依据是**状态**（跟着主体与规则实时变），不是写死的一句",
              vm, r"fun priceBasisText\(\)")
    c.present("它真的去看了专属价规则（不是一律说「按商品默认售价」）",
              body_of("fun priceBasisText("), r"priceRules\[it\] != null")
    c.present("没拿到价时说的是「正在核对」，不是「默认价」（两者对钱的后果正好相反）",
              body_of("fun priceBasisText("), r"价格正在核对")
    c.present("拿到专属价时说的是「按「X」的专属价」",
              body_of("fun priceBasisText("), r"价格按「\$who」的专属价")
    screen_src = strip_comments(read(CREATE_SCREEN))
    n_basis_sites = len(re.findall(r"vm\.priceBasisText\(\)", screen_src))
    c.ok(f"界面**真的画了**它，而且只有 {n_basis_sites} 处（不画＝死文案；两处＝同屏两句打架的话）",
         n_basis_sites == 1, "报价依据必须恰好有一个渲染点")
    # ⚠️ 这一条是 2026-09-22 真机 dump 抓到的：`vm.toast` 原来**只有**地址抽屉里那一个渲染点，
    #    于是"已按预设单填好""某件商品已不在商品库"这些话用户**根本看不到**（等于没有反馈）。
    n_toast_sites = len(re.findall(r"vm\.toast\?\.let", screen_src))
    c.ok(f"一次性提示有 {n_toast_sites} 个渲染点（下限 2：地址抽屉 + 页面顶部横幅）",
         n_toast_sites >= 2, "只有一个渲染点 = 大部分提示用户看不见")
    c.present("顶部横幅能收掉（不然预填那句话会一直挂在屏幕上）", vm, r"fun dismissToast\(\)")
    c.present("横幅上的 ✕ 接的就是它", screen_src, r"vm\.dismissToast\(\)")

    # 单测：清单**自己算**（glob 出这个包下的测试，谁调了 `repriceLines` 就认谁）
    tests_dir = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/shipper"
    test_files = sorted(tests_dir.glob("*Test.kt"))
    reprice_tests = [p for p in test_files if "repriceLines(" in strip_comments(read(p))]
    c.ok(f"重算有单测盯着（这个包 {len(test_files)} 份测试里 {len(reprice_tests)} 份调了它，下限 1）",
         len(reprice_tests) >= 1, "没有测试的纯函数 = 下一个人改坏了也没人知道")
    n_cases = sum(len(re.findall(r"@Test", read(p))) for p in reprice_tests)
    c.ok(f"重算的用例 {n_cases} 条（下限 5）", n_cases >= 5, "用例太少等于没测")
    c.absent("旧注释里那句「回退默认价是少赚」必须消失（对谈好价的批发商是多收钱，不是少赚）",
             vm, r"回退到默认价是")

    # ---- ⑫ 预订单＝模板：分类名册 + 页面新建/编辑 + 回收站（2026-09-22 第二轮）----
    # 用户原话：「**怎么不能新建一个预订单呢**？…这个预订单就**相当于一个模板**，
    # 而且这个模板我们是要**做一个分类**的 —— 也是一样的，**左边是分类管理**…**我右边就是订单**，
    # 我们可以**删除**、可以**编辑**、可以**用这个单下单**，还可以**新建一个订单**。」
    for verb in (
        r'@router\.get\(""',
        r'@router\.post\(""',
        r'@router\.patch\("/\{category_id\}"',
        r'@router\.post\("/reorder"',
        r'@router\.delete\("/\{category_id\}"',
    ):
        c.present(f"分类名册端点存在（{verb}）", cat_api, verb)
    c.present("名册表名与字段（与商品分类同一套：name 唯一 + sort_order）",
              cat_model, r'__tablename__ = "order_template_categories"')
    c.present("分类存**名字**在预设单上（不是编号）", model, r"category: Mapped\[str\]")
    c.present("改名**级联**改掉挂着的预设单（同一事务，UPDATE order_templates）",
              cat_api, r"OrderTemplate\.__table__\.update\(\)[\s\S]{0,120}?\.values\(category=body\.name\)")
    c.present("级联**不带 is_deleted 过滤**（回收站里那几张一起改，否则恢复回来挂着一个不存在的分类名）",
              cat_api, r"级联\*\*不带")
    c.present("删除还有预设单挂着 → 拒绝并报数",
              cat_api, r"还有 \{used\} 张预设单挂在这个分类下")
    c.present("排序走五个名册共用的那一份判据", cat_api, r"ordered_ids\(by_id, body\.ids\)")
    c.present("建预设单时名册外的分类名自动补进名册",
              api, r"ensure_category\(db, category\)")
    c.present("预设单改分类时也补名册（键出现就写＝空串能真的移到未分类）",
              api, r'if "category" in sent:[\s\S]{0,160}?ensure_category\(')
    c.present("回收站视图（软删的进得去、能恢复 —— 用户定硬规矩）",
              api, r"deleted_only")
    c.present("分类名册出参带「挂着几张预设单」", cat_schema, r"template_count: int = 0")
    # ⚠️ 回填**必须过滤软删行**（2026-09-22 真机抓到）：一张进了回收站的预设单，它的
    #    `category` 还写着那个名字 —— 不过滤的话"刚删掉的分类、重启一次又回来了"。
    bootstrap = read(ROOT / "backend/app/core/schema_bootstrap.py")
    c.present("回填只收**在用**的分类名（软删行不算）",
              bootstrap, r"FROM order_templates \"\s*\n?\s*\"WHERE category IS NOT NULL AND TRIM\(category\) <> '' AND is_deleted = 0")

    # 界面：左分类 / 右订单 / 底栏三格 / 新建与编辑去同一张表单页 / 回收站
    c.present("左栏用**共用那一份**分类导航条", screen, r"CategoryRail\(")
    c.present("分档判据也是共用的那一份（不自己再写一份）", screen, r"categoryTabsOf\(")
    c.present("卡片上有「编辑」", screen, r'Text\("编辑"\)')
    c.present("卡片上仍然有「用这张下单」", screen, r'Text\("用这张下单"\)')
    c.present("底栏有「分类管理」入口", screen, r'"分类管理"')
    c.present("底栏中间是「新建预订单」（语义色圆钮）", screen, r'"新建预订单"')
    c.present("底栏有「回收站」（snackbar 会飘走，飘走之后得有地方找回来）", screen, r'"回收站"')
    c.present("底栏自己处理底部安全区（它不是 M3 NavigationBar）", screen, r"navigationBarsPadding\(\)")
    c.present("回收站里能恢复", screen, r'Text\("恢复"\)')
    c.present("列表页的分类名册与列表**一起刷**（只刷一半会造出「这个分类下还没有预设单」）",
              screen, r"orderTemplates\(deletedOnly = showTrash\)[\s\S]{0,200}?orderTemplateCategories\(\)")
    c.present("路由常量：表单页", routes, r'DISPATCH_ORDER_TEMPLATE_FORM')
    c.present("路由常量：分类管理页", routes, r'DISPATCH_ORDER_TEMPLATE_CATEGORIES')
    c.present("带参拼法只有一处（路由助手）", routes, r"fun orderTemplateForm\(")
    c.present("NavGraph 注册了表单页", nav, r"composable\(\s*\n?\s*route = Routes\.DISPATCH_ORDER_TEMPLATE_FORM")
    c.present("NavGraph 注册了分类管理页", nav, r"composable\(Routes\.DISPATCH_ORDER_TEMPLATE_CATEGORIES\)")
    c.present("「编辑」与「新建」去的是同一张表单页",
              nav, r"onOpenForm = \{ id -> navController\.navigate\(Routes\.orderTemplateForm\(id\)\) \}")

    # 表单页：共用表单行、**不报价**、不存价
    for row in ("FormGroup(", "FormInputRow(", "FormPickRow(", "FormActionRow(", "FormTextAreaRow("):
        c.present(f"表单页用共用件 {row}", form_src, re.escape(row))
    c.present("表单页的选品**不报价**（预订单里根本没有价，画个价出来会让人以为存下来了）",
              form_src, r"showPrice = false")
    c.present("表单页不自己算专属价（那是下单页唯一那一处 priceFor 的口径）",
              form_src, r"priceFor = \{ it\.defaultUnitPrice \}")
    c.present("表单页不发单价（行里只有商品/名称/单位/数量）",
              form_src, r"OrderTemplateLineDto\(\s*\n?\s*productId = it\.productId")
    c.present("空运费发得出去（＝把参考运费改回「不预设」）", form_src, r"freightFee = feeText")
    c.present("清空货主走显式开关（Android 的 explicitNulls=false 会把 null 丢掉）",
              form_src, r"clearShipper = shipperId == null")
    c.present("编辑时按 id 载入", form_src, r"fun start\(templateId: Long\?\)")
    c.present("分类下拉里**补上当前值**（名册里没有它时也要显示出来，否则一保存就悄悄改了分类）",
              form_src, r"if \(cur\.isNotEmpty\(\) && cur !in opts\) opts \+= cur")
    # 选品页的"不报价"模式：三处都要跟着变，只有一处改=界面上半价半不价
    picker = strip_comments(read(COMMON / "ProductPicker.kt"))
    c.present("选品页有 showPrice 开关", picker, r"showPrice: Boolean = true")
    c.present("不报价时**行上那条价格事实整条不画**（传空串进去会渲染成 ¥0）",
              picker, r"if \(price\.isBlank\(\)\) null else productPriceFact\(")
    c.present("不报价时底部汇总显示件数而不是金额", picker, r'共 " \+ picked\.values\.sumOf \{ it\.qty \} \+ " 件"')

    # 分类管理页（第 5 个名册）：必须继承共用内核、改名要说清级联
    c.present("分类管理页继承共用的名册内核", cats_screen, r":\s*\n?\s*CategoryRosterViewModel<")
    c.present("它真的在调 reorder 那条路（判据：名册页清单自己算得出来）",
              cats_screen, r"repo\.reorderOrderTemplateCategories\(")
    c.present("改名提示要说清「挂着的预设单也跟着改了」（这一套是按名字归属的）",
              cats_screen, r"挂在这个分类下的预设单也跟着改了")

    # ---- ⑬ 卡片要有语义色/图标/加粗；分类排序要**卡片式拖动**（2026-09-22 用户第三轮）----
    # 用户原话①：「卡片的样式不明确，我们需要**加一些语义色和图标**啊，这些**排版**要拍好一点，
    #           **重要信息就稍微加粗**」。
    # 用户原话②：「分类管理的排序**不是点击上上下下这种**」—— 要像商品列表排序那样**可以拖动**。
    c.present("卡片用共用的**事实行**观感（图标 + 标签 + 值各一行）",
              screen, r"TemplateFactRow\(")
    c.present("事实行逐条给了图标与**图标的**语义色", screen, r"TemplateFactRow\(Icons\.Default\.Folder")
    c.present("卡片顶部是语义色圆底图标（不是裸图标）", screen, r"TintedIcon\(Icons\.Default\.BookmarkAdded")
    # ⚠️ 两条是用户 2026-09-22 第二轮**明确纠正**的（别改回去）：
    #   ① 「文字就不需要加颜色了，这样的反而显得太花了」→ 语义色只给图标；
    #   ② 「文字往右边，不要在一起」→ 标签贴左、值贴右（中间 `weight(1f)` 撑开）。
    c.present("值靠右 + 长值能被截断（`weight(1f)` 与 `TextAlign.End` 一起才算对）",
              screen, r"modifier = Modifier\.weight\(1f\),\s*\n\s*textAlign = TextAlign\.End")
    # ⚠️ 判据查代码、不查那句注释：`screen` 是**剥过注释的**源码（`strip_comments`），
    #    写成"找那句 `// ⚠️ 不加颜色`"会永远找不到（第一版就这么写的，当场红了）。
    c.present("值**不上色**（用 onSurface，强调靠加粗）",
              screen, r"value,\s*\n?[\s\S]{0,240}?color = MaterialTheme\.colorScheme\.onSurface")
    c.absent("⛔ 事实行的值不许再染成语义色（那一版被点名「太花」）",
             screen, r"value,[\s\S]{0,80}?color = tint")
    c.present("名字是加粗的主角", screen, r'Text\(\s*\n?\s*t\.name,[\s\S]{0,120}?fontWeight = FontWeight\.Bold')
    c.present("钱的语义色取主题那一份（MoneyOrange），⛔ 不在页面里另写十六进制",
              screen, r"import com\.tapmoay\.sorders\.ui\.theme\.MoneyOrange")
    c.present("货主的语义色同样取主题（ShipperTeal）",
              screen, r"import com\.tapmoay\.sorders\.ui\.theme\.ShipperTeal")
    c.present("分类管理页的计数文字也不上色",
              cats_screen, r"labelMedium,[\s\S]{0,320}?color = MaterialTheme\.colorScheme\.onSurface")
    # 分类排序：拖动那套必须**真的在**（长按手势 + 位移换算 + 稳定 key + 固定行高）
    c.present("分类管理页是**长按拖动**排序（不是上下按钮）",
              cats_screen, r"detectDragGesturesAfterLongPress\(")
    c.present("拖动位移换算走共用那一份", cats_screen, r"dragSteps\(dragOffset, rowPx\)")
    c.present("换位走共用的搬运实现", cats_screen, r"vm\.moveBy\(c\.id, steps\)")
    c.present("拖动时给了稳定 key（不给会被销毁 → 手势被取消，真机踩过）", cats_screen, r"key\(c\.id\)")
    c.present("拖动行是**固定高度**（位移→格数靠它算）", cats_screen, r"height\(CATEGORY_ROW_HEIGHT\)")
    c.present("另给了「置顶↑」快捷键", cats_screen, r'Icon\(Icons\.Default\.VerticalAlignTop')
    c.present("顺序仍是**本地草稿**：点「保存顺序」才提交", cats_screen, r"vm\.saveOrder\(\)")
    c.absent("⛔ 不许再有「上移/下移」按钮（用户点名不要这种）", cats_screen, r"KeyboardArrowUp|onUp\b")
    c.absent("⛔ 也不许再有「位次」输入框（那一版就是被点名换掉的）", cats_screen, r'"位次"')

    total = c.passes + len(c.fails)
    if total < 60:
        print(f"❌ 只跑了 {total} 项（<60）—— 判据在空转，停。")
        return 1
    if c.fails:
        print(f"❌ 预订单红线不通过（{c.passes}/{total}）：")
        for f in c.fails:
            print("   [FAIL] " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：预设单只是「预填模板」—— 下单仍只有一条路，"
          "金额、常用度、撤回都走各自唯一的那份实现。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
