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
API = ROOT / "backend/app/api/v1/order_templates.py"
MODEL = ROOT / "backend/app/models/order_template.py"
SCHEMA = ROOT / "backend/app/schemas/order_template.py"
TEST = ROOT / "backend/tests/test_order_templates.py"
SCREEN = ANDROID / "ui/dispatcher/OrderTemplatesScreen.kt"
CREATE_VM = ANDROID / "ui/shipper/OrderCreateViewModel.kt"
CREATE_SCREEN = ANDROID / "ui/shipper/OrderCreateScreen.kt"
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
              AI_DECL, AI_HANDLER, AI_RES, AI_SVC, COVERAGE, ENDPOINTS, DESIGN, LOCATOR):
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
    c.present("删除二次确认（危险操作）", screen, r"AlertDialog\(")
    c.present("删完给「撤回」（用户定的硬规矩：手边要有撤销入口）",
              screen, r'actionLabel = "撤回"')
    c.present("撤回走 restore 那条路", screen, r"fun restoreLastDeleted\(")
    c.present("说明卡里如实写了「不含单价」", screen, r"预设单不含单价")
    c.present("说明卡里如实写了「运费只是参考」（下单接口根本不收运费）",
              screen, r"预设运费只是参考值")

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
    c.present("商品已不在库里时**说出来**（不静默留空价）", prefill, r"已不在商品库，价格要自己填")
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
    c.present("读能力被 App 模块认领（否则用户在界面上看不到它）",
              read(COVERAGE), r'"预订单": \(\["预订单"\]')
    c.present("端点索引里有它（文档不许过期）",
              read(ENDPOINTS), r"GET /api/v1/order-templates")
    c.absent("AI 那边**没有**「从预设单下单」的动作（下单走已有的 orders.create）",
             ai_decl, r'id = "order_templates\.create_order"')

    # ---- ⑩ 文档指针 ----
    c.ok("设计规范里写了预订单那一条规矩（并指路本判据）",
         "预订单" in read(DESIGN) and "_check_order_templates.py" in read(DESIGN),
         "缺一条：预订单的规矩 + 指路到本文件")
    loc = read(LOCATOR)
    c.ok("定位表里指到了预订单（并点名本判据）",
         "预订单" in loc and "_check_order_templates.py" in loc,
         "改这一块的人应当能从定位表找到本文件")

    total = c.passes + len(c.fails)
    if total < 45:
        print(f"❌ 只跑了 {total} 项（<45）—— 判据在空转，停。")
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
