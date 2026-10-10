"""钱相关四条（CHG-0087）：定价 / 让价 / 取消让价 / 设挂账额度 —— 机器判据。

## 用户要的（ref m28098，目标① 四单里的第四单；台账 L-56）
「① **AI 覆盖补齐** —— 把「本轮不开放」的那批写端点（**发票台账 6、钱相关 7、订单结构 3**）开给
对应角色……**司机端维持不加 AI。**」本单是四单里的最后一单：把**钱相关四条**接进 AI 动作目录 ——
`orders.price_freight`（给一单定司机运费）/ `orders.discount`（让价）/
`orders.discount_clear`（取消让价）/ `arrears_unit.set_credit_limit`（设挂账单位额度）。

## 这一条为什么必须有机器的判据
这四条每一条都能"没报错、但也没发生"，或者"发生了、但发生了另一件事"：
- **定价**：`category` 的语义是**反的** —— 后端 `category_id` 默认 `None`，「键不在」
  与「发 null」在后端是**同一个结果：清空分类**。所以"不说"必须由 AI **显式把当前分类编号发回去**；
  写错这一层，用户说「改个价」会把分类悄悄抹掉（而两个页面看起来都正常）。
- **定价的状态门**：已送达 / 已退货的单，**定过价的锁死、没定过价的仍然能补**。一律拒 = 用户办不成事；
  一律放 = 事后改运费不动司机账单（后端原话："只会在两个页面上显示两个数"）。
- **让价**：「再让一次」是**整份替换**而不是叠加；每一行的金额**由后端算**（客户端一个乘法都不做）。
  模型要是自己算了那个数，用户只在合计上看得出来。
- **取消让价**：还原是**按当时记下的快照**精确还原（不是单价 × 数量重算）；而且这一条**有**撤回按钮。
- **额度**：「不限额」（显式 `null`）与「额度 0 元」（一分钱都不许赊）是两件事 —— 糊成一个，
  用户以为"给他放开了"，实际是"一分钱都不许赊"。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
代码边界（编译期 / 类型系统 / 后端 400）只能挡住**不合法的取值**，挡不住**语义被换掉**：
"不说分类"发成 `null` 是**合法**的（后端把它读成"清空"）、"不限额"与"0 元"都是**合法**的
`JsonElement`、让价的值域合法但**方向**可以是错的。这四条的错误形态全是"库里一切正常、
用户的意图没实现"，所以只能靠**卡片上逐句写明 ＋ 单测逐条钉住 ＋ 判据盯住字面**。

## 判据（每条都能被反向验证弄红）
1. 四条动作各登记**一处**（id 常量 / 规格 / 总表），⛔ 不在服务文件里再写一份；
2. 标题 / 风险档 / 组逐字（定价 MEDIUM、其余三条 HIGH；定价与让价在「订单」组，额度在「账目」组）；
3. 四条**都不进** `SHIPPER_ACTIONS`（后端权限点分别是 order:dispatch / order:edit / ledger:edit）；
4. 定价：`categoryOf` 的"沿用 = 把当前分类编号发回去"、`LOCKED_AFTER_DELIVERY` 的两句话、
   已撤销单一个字都不许写；
5. 让价：方式 ENUM 二选一、值四种不对都在弹卡前拦下、范围按名字找行（同名多行全要）、
   "整份替换不是叠加"、"金额由后台重算、这里不预演"写在卡片上；
6. 取消让价：本来没有让价的单按**后台原话**拒掉；`AiResources` 里成对动作把四个参数全部搬回；
7. 额度：「不限额」与「0 元」两件事分开写；`AiResource.nullableWritable` 点名 `credit_limit`
   （不点名那个撤回按钮就是假的）；撤回 payload 缺 `credit_limit` 要拒（不能默默当成 0）；
8. 数据层：四条 `ds.` 方法 ＋ repo 转发一处；`_check_ai_guardrails` 白名单把单条读认成读；
9. 覆盖表：四条 `EXCLUDED` 必须删（与新覆盖同时存在就是自相矛盾），来龙去脉留着；
10. 单测 14 条 + 说明书上限 + 变更单九节 + 登记簿 + 工作声明 + 台账 L-56 + 反验脚本在。

用法：
    python _tools/qa/_check_ai_money.py
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402
from _check_product_card_single_source import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AI = AND / "ai"

MONEY = AI / "AiWriteMoney.kt"
AIWRITE = AI / "AiWrite.kt"
SVC = AI / "AiWriteService.kt"
SRC = AI / "AiWriteDataSource.kt"
RES = AI / "AiResources.kt"
REVERT = AI / "AiRevert.kt"
UI_DISCOUNT = AND / "ui/order/OrderDiscount.kt"

BACKEND_ASSIGN = ROOT / "backend/app/api/v1/orders_assignment.py"
BACKEND_DISC = ROOT / "backend/app/api/v1/orders_discount.py"
BACKEND_ARREARS = ROOT / "backend/app/api/v1/arrears.py"

TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"
PROMPT_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWritePromptTest.kt"

WRITE_COVERAGE = ROOT / "_tools/ai/_write_coverage.py"
READ_COVERAGE = ROOT / "_tools/ai/_read_coverage.py"
GUARDRAILS = ROOT / "_tools/ai/_check_ai_guardrails.py"
FEATURE_COVERAGE = ROOT / "_tools/ai/_app_feature_coverage.py"
LEDGER = ROOT / "_tmp/USER_BUG_LEDGER_20261006.md"

CHG_ID = "CHG-0087"
CHG_DOC = ROOT / "docs/changes/CHG-0087.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_ai_money.py"

#: 九节标题（按前缀认：这几节的标题后面还带括号说明）
CHG_SECTIONS = (
    "## ① 六问",
    "## ② Must Change / Must Not Change",
    "## ③ Boundary",
    "## ④ Behavior Contract",
    "## ⑤ Data Contract",
    "## ⑥ CHG 专章",
    "## ⑦ 测试",
    "## ⑧ 证据",
    "## ⑨ 关闭",
)

#: 行数下限（防文件被搬走 / 被截断之后「一个断言都没扫到」也算过）
MIN_MONEY_LINES = 560
MIN_AIWRITE_LINES = 2700
MIN_SVC_LINES = 1250
MIN_SRC_LINES = 2350
MIN_RES_LINES = 1560
MIN_REVERT_LINES = 1090
MIN_TEST_LINES = 7500
MIN_PROMPT_TEST_LINES = 120

LF = chr(10)

#: (id 常量名, 动作 id, 标题, 风险档, 组常量)
ACTIONS = (
    ("ORDERS_PRICE_FREIGHT", "orders.price_freight", "给这一单定司机运费", "MEDIUM", "G_ORDER"),
    ("ORDERS_DISCOUNT", "orders.discount", "给这一单让价", "HIGH", "G_ORDER"),
    ("ORDERS_DISCOUNT_CLEAR", "orders.discount_clear", "取消这一单的让价", "HIGH", "G_ORDER"),
    ("ARREARS_UNIT_SET_CREDIT_LIMIT", "arrears_unit.set_credit_limit", "设挂账单位的额度", "HIGH", "G_LEDGER"),
)

#: 单测里本单的 14 条用例名（判据逐条钉住 —— 少一条就说明有一处口径没人守）
CASE_NAMES = (
    "定价·给没定过价的单定价：金额分类都摆上卡，0 元也是合法的一个数",
    "定价·没说分类＝沿用现在的分类（不是清空），说「不适用」才是清空",
    "定价·已送达的单：定过价的锁死、没定过价的是补定，两种都当场说清",
    "定价·已撤销的单一个字都不许写，卡片也不许弹",
    "让价·整单抹零：方式数值范围写全，第二次让价是整份替换不是叠加",
    "让价·点名的商品：按名字找行、同名多行全都要；找不到就列出这一单的商品名",
    "让价·值不对的四种：空、非数、零、百分比到 100，都在弹卡前拦下",
    "让价·状态门：已送达的单动不了钱，一个字都不许写",
    "取消让价·本来就没有让价：按后台原话拦下；有让价时按快照还原，且这一条能撤回",
    "额度·设一个数：卡片写「原来 → 改成」，payload 就是这两个键",
    "额度·说「不限额」＝把额度清空（不是 0）",
    "额度·原来就是这个数：如实说不用改，一条都不许写",
    "额度·名册里没有这个单位、额度读不到：两种都不许改去设别的单位",
    "钱相关四条·角色与撤回口径：都是派单员档，两条有按钮两条没有",
)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def code(p: Path) -> str:
    return strip_comments(read(p))


def subs(text: str, needle: str) -> int:
    return text.count(needle)


def raw_block(src: str, sig: str) -> str:
    start = src.find(sig)
    if start < 0:
        return ""
    depth = 0
    for i in range(start, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    return src[start:]


def part_of(src: str, start_mark: str, end_mark: str) -> str:
    a = src.find(start_mark)
    if a < 0:
        return ""
    b = src.find(end_mark, a + len(start_mark))
    return src[a:b] if b > 0 else src[a:]


def spec_of(src: str, const: str) -> str:
    start = src.find("id = AiWrites." + const + ",")
    if start < 0:
        return ""
    ends = [p for p in (src.find(LF + "        AiWriteAction(", start), src.find(LF + "    )", start)) if p > 0]
    return src[start:min(ends)] if ends else src[start:]


def run_cmd(args: list) -> tuple:
    try:
        p = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900)
        return (p.stdout or "") + (p.stderr or ""), p.returncode
    except Exception as e:  # noqa: BLE001
        return "跑不起来：" + str(e), -1


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails = 0

    def ok(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + name)
        else:
            self.fails += 1
            print("  [FAIL] " + name + ("  <- " + detail if detail else ""))

    def has(self, name: str, hay: str, needle: str) -> None:
        self.ok(name, needle in hay, "没找到：" + needle)

    def hasnt(self, name: str, hay: str, needle: str) -> None:
        self.ok(name, needle not in hay, "不该出现：" + needle)


def main() -> int:
    if refuse_if_injecting("钱相关四条判据"):
        return 0

    c = Checker()
    money = read(MONEY)
    mc = code(MONEY)
    w = read(AIWRITE)
    wc = code(AIWRITE)
    s = read(SVC)
    sc = code(SVC)
    src = read(SRC)
    srcc = code(SRC)
    rs = read(RES)
    rsc = code(RES)
    rv = read(REVERT)
    t = read(TEST)
    pt = read(PROMPT_TEST)

    print("== 0. 文件在，而且不是空壳 ==")
    for p, floor, nm in (
        (MONEY, MIN_MONEY_LINES, "AiWriteMoney.kt"),
        (AIWRITE, MIN_AIWRITE_LINES, "AiWrite.kt"),
        (SVC, MIN_SVC_LINES, "AiWriteService.kt"),
        (SRC, MIN_SRC_LINES, "AiWriteDataSource.kt"),
        (RES, MIN_RES_LINES, "AiResources.kt"),
        (REVERT, MIN_REVERT_LINES, "AiRevert.kt"),
        (TEST, MIN_TEST_LINES, "AiWriteTest.kt"),
        (PROMPT_TEST, MIN_PROMPT_TEST_LINES, "AiWritePromptTest.kt"),
    ):
        txt = read(p)
        c.ok("文件在：" + str(p.relative_to(ROOT)), p.exists())
        c.ok("行数下限（" + nm + "）", len(txt.splitlines()) >= floor, "实际 " + str(len(txt.splitlines())))
    c.has("钱相关文件头顶写着这一条由哪个判据钉住", money, "_tools/qa/_check_ai_money.py")
    c.has("钱相关文件头顶点名反向验证脚本", money, "_tools/qa/_reverse_verify_ai_money.py")
    c.has("钱相关文件头顶写着台账号", money, "CHG-0087")
    c.has("钱相关文件头顶写着台账条目", money, "台账 L-56")

    print("== 1. 四条动作登记一处（id / 组 / 标题 / 风险档） ==")
    for const, sid, title, risk, group in ACTIONS:
        cn = title
        c.ok(cn + "：id 常量只声明一次", subs(wc, "const val " + const + " = \"" + sid + "\"") == 1)
        c.ok(cn + "：规格只登记一处（id = AiWrites." + const + "）", subs(mc, "id = AiWrites." + const + ",") == 1)
        c.ok(cn + "：规格不在服务文件里偷偷再写一份", subs(sc, "id = AiWrites." + const + ",") == 0)
        spec = spec_of(mc, const)
        c.ok(cn + "：规格块抽得出来（不是空转）", len(spec) > 300, "只抽到 " + str(len(spec)) + " 字符")
        c.has(cn + "：挂在对的组下（" + group + "）", spec, "group = AiWrites." + group + ",")
        c.has(cn + "：标题逐字", spec, "title = \"" + title + "\",")
        c.has(cn + "：风险档逐字（" + risk + "）", spec, "risk = AiWriteRisk." + risk + ",")
    c.ok("「订单」组常量只声明一次", subs(wc, "const val G_ORDER = \"订单\"") == 1)
    c.ok("「账目」组常量只声明一次", subs(wc, "const val G_LEDGER = \"账目\"") == 1)
    c.ok("四条接进了动作总表（ALL 里的 AiWriteMoney.ACTIONS）", subs(wc, "AiWriteMoney.ACTIONS") == 1)
    c.has("总表那一段点名这一批是哪四条", w, "钱相关四条（2026-10-08 CHG-0087：定价 / 让价 / 取消让价 / 挂账额度）")
    c.has("四条都写清「不是新能力」（手工页早就这么干）", w,
          "手工页（订单详情的「运费定价」/「让价」、挂账单位编辑弹窗）早就这么干了")
    c.has("额度为什么不并进「改单位资料」写在常量那块", w, "额度不是\"资料\"，")
    c.ok("定价与让价的规格块各自抽得出来（不是同一个块）", spec_of(mc, "ORDERS_PRICE_FREIGHT") != spec_of(mc, "ORDERS_DISCOUNT"))

    print("== 2. 角色与权限：四条都只有派单员（后端权限点逐条对上） ==")
    block = part_of(wc, "val SHIPPER_ACTIONS: Set<String> = setOf(", LF + "    )")
    c.ok("SHIPPER_ACTIONS 那个清单抽得出来（下面的判断才有意义）", len(block) > 500, "只抽到 " + str(len(block)) + " 字符")
    for const, _sid, title, _risk, _group in ACTIONS:
        c.ok(title + "：不在货主清单里", const not in block)
    c.ok("动作 id 一个都没混进货主清单", "orders.price_freight" not in block and "orders.discount" not in block
         and "arrears_unit.set_credit_limit" not in block)
    c.has("动作数那句话跟着改了（175 里 44 条）", w, "175 个动作里 44 条在清单内")
    c.has("定价：后端端点就是那一条", read(BACKEND_ASSIGN), "@router.post(\"/{order_id}/price-freight\", response_model=OrderOut)")
    c.has("定价端点挂的是 ORDER_DISPATCH", read(BACKEND_ASSIGN),
          "current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),")
    c.has("让价：后端权限点是改单（order:edit）", read(BACKEND_DISC), "Permission.ORDER_EDIT")
    c.ok("让价与取消让价两个端点都在（POST / DELETE）",
         subs(read(BACKEND_DISC), "@router.post(\"/{order_id}/discount\"") == 1
         and subs(read(BACKEND_DISC), "@router.delete(\"/{order_id}/discount\"") == 1)
    c.has("额度：后端权限点是台账编辑（ledger:edit）", read(BACKEND_ARREARS), "Permission.LEDGER_EDIT")

    print("== 3. 定价：沿用分类要显式发回去、已送达两种情形当场分清 ==")
    pf = raw_block(mc, "class PriceFreightHandler(")
    c.ok("定价处理器整块抽得出来", len(pf) > 800, "只抽到 " + str(len(pf)) + " 字符")
    c.has("已送达 / 已退货的锁定集合只此一处", mc, "private val LOCKED_AFTER_DELIVERY = setOf(\"DELIVERED\", \"RETURNED\")")
    c.has("已撤销是一个字都不许写的那一档", mc, "STATUS_CANCELLED = \"CANCELLED\"")
    c.has("定价门：已撤销的单拒掉并说明不要换单", mc,
          "这一单已经撤销了，不用再定价。请如实告诉用户，不要换一张单去操作。")
    c.has("定价门：已送达且定过价 = 锁死", mc, "已送达的单运费是锁定的")
    c.has("定价门：锁死那句连带说出为什么（司机账单 / 两个页面两个数）", mc,
          "（事后改运费不会动司机账单，只会在两个页面上显示两个数）。")
    c.has("定价门：已送达但没定过价 = 可以补定（不一律拒）", mc, "而且已经定过运费了")
    c.has("定价门：其余状态如实说定不了", mc, "这个状态定不了运费。请如实告诉用户。")
    c.has("「不说分类」的判定词表在", mc, "NO_CATEGORY_WORDS")
    c.has("分类：没说 ⇒ 沿用现在的分类", mc, "沿用现在的分类")
    c.has("分类：「不适用」才是清空", mc, "不适用")
    c.has("分类名册读不到要拒，不要去动别的单", mc, "没读到运费分类名册，请稍后再试。")
    c.has("分类名走严格解析（对不上就报错，不猜）", mc, "AiWriteArgs.strict(raw, ds.freightCategories(), \"运费分类\")")
    c.has("payload：订单号", mc, "put(\"order_id\", order.id)")
    c.has("payload：金额按分（字符串），不是 double", mc, "put(\"freight_fee\", AiWriteArgs.money(freight))")
    c.has("payload：分类键名就是撤回快照的键名", mc, "freight_category_id")
    c.has("payload：清空分类用 JsonNull（不是空串）", mc,
          'put("freight_category_id", category.id?.let { JsonPrimitive(it) } ?: JsonNull)')
    c.has("卡片标题：给哪一单定多少钱", mc,
          "\"给 \" + order.orderNo + \" 定运费：\" + AiWriteArgs.moneyText(freight) + \" 元\"")
    c.has("卡片：改前改后那一段", mc, "———— 改成 ————")
    c.has("卡片：司机运费那一行", mc, "司机运费：")
    c.has("卡片：分类沿用要写出来", mc, "（沿用现在的分类）")
    c.has("卡片：已送达补定那一段（含「补定」二字）", mc, "这是补定：")
    c.has("卡片：不顺手沉淀价目（砍掉的那件事不做哑巴砍）", mc, "这一步不顺手沉淀价目 —— 要沉淀请到运费定价页勾一下。")
    c.has("参数：金额可填 0（＝这一单不收运费）", mc, "元。可以填 0（＝这一单不收运费）")
    c.has("参数：分类的提示把三种情形都说全", mc, "分类名（如「市内」）。说「不适用」＝不套分类；不说＝沿用现在的分类")
    c.has("说明书那一段（blurb）也把「不沉淀价目」写给模型", mc, "这一步**不顺手沉淀价目**（要沉淀请到运费定价页勾一下）。")

    print("== 4. 让价：整份替换、四种值不对都拦、按名字找行 ==")
    dh = raw_block(mc, "class DiscountOrderHandler(")
    c.ok("让价处理器整块抽得出来", len(dh) > 1200, "只抽到 " + str(len(dh)) + " 字符")
    c.has("状态门复用界面那一半（canDiscount 一处实现两处消费）", mc, "canDiscount(")
    c.has("状态门：动不了钱时说清哪三种状态能动", mc,
          "，动不了钱（只有待派单 / 派单中 / 已接单的单能让价）。")
    c.has("状态门：驳回之后说明不要换一张单去操作", mc, "请如实告诉用户，不要换一张单去操作。")
    c.has("方式只认两种（抹零 / 减百分比），别的如实拒", mc, "让价方式只认两种：抹零（减一个金额）或减百分比（减几个点）")
    c.has("方式是真 ENUM（说明书里就是二选一）", mc, "enumValues = listOf(\"抹零\", \"减百分比\")")
    c.has("整单的哨兵值是「全部」", mc, "DISCOUNT_ALL_LINES = \"全部\"")
    c.has("一次最多 200 行（有上界）", mc, "MAX_DISCOUNT_LINES = 200")
    c.has("超上界要如实说收到几行", mc, "一次最多只勾 ")
    c.has("超上界那句是把常量拼进话里（不是硬编码 200）", mc, 'MAX_DISCOUNT_LINES + " 行，收到 "')
    c.has("按名字找不到行时列出这一单有什么", mc, "这一单里没有叫「")
    c.has("按名字找不到行时给出路", mc, "请让用户从里面挑。")
    c.has("值不对要拦在弹卡之前（不是让后端 400）", mc, "discountValueError(")
    c.has("值不对的话术逐字", mc, "让价的数值不对：")
    c.has("值不对时说不许改去动别的单", mc, "。请如实告诉用户，不要改去动别的单。")
    c.has("金额按分（字符串）进 payload（客户端不做乘法）", mc, "AiWriteArgs.money(")
    c.has("payload：让价方式键名", mc, "discount_kind")
    c.has("payload：让价数值键名", mc, "discount_value")
    c.has("payload：范围键名（撤回快照同名）", mc, "discount_line_ids")
    c.has("payload：理由键名", mc, "discount_reason")
    c.has("卡片：这次让价那一段", mc, "———— 这次让价 ————")
    c.has("卡片：范围那一行接在「范围：」后面", mc, '"范围：" + if (picked.ids.isEmpty()) {')
    c.has("卡片：范围整单时写清「每一行都按比例让」", mc, "整单（每一行都按比例让）")
    c.has("卡片：第二次让价是整份替换（不是叠加）", mc, "这次会把它整份替换掉，不是叠加。")
    c.has("卡片：第一次让价也要说清现在没有", mc, '?: "没有让价。"')
    c.has("卡片：金额由后台重算、这里不预演（含抹零会被改小那句）", mc,
          "每一行的金额由后台重算（这里不预演：抹零会被「最后一行没那么多钱」改小，")
    c.has("卡片：勾了「不参与打折」的商品会被后端拒（那是规则不是出错）", mc,
          "选中的商品如果在档案上勾了「不参与打折」，后台会拒绝这一单 —— 那是规则，不是出错。")
    c.has("说明书：再让一次是整单替换、不是叠加", mc, "再让一次是**整单替换**、不是叠加。")
    c.has("说明书：退货按折后实付退", mc, "退货按折后实付退。")

    print("== 5. 取消让价：本来没有的按后台原话拒、还原按快照、这一条能撤回 ==")
    dc = raw_block(mc, "class DiscountClearHandler(")
    c.ok("取消让价处理器整块抽得出来", len(dc) > 600, "只抽到 " + str(len(dc)) + " 字符")
    c.has("本来就没有让价：按后台原话拦下", mc, "这一单本来就没有让价（后台的原话：「这一单本来就没有折扣。」）。请如实告诉用户。")
    c.has("卡片：取消掉那一段", mc, "———— 取消掉 ————")
    c.has("卡片：现在这套让价是什么", mc, "现在这套让价：")
    c.has("卡片：还原是按当时记下的快照（不是单价 × 数量重算）", mc, "按当时记下的快照精确还原，不是拿单价 × 数量重算）")
    c.has("卡片：说清这一条有撤回按钮、能整份打回去", mc,
          "（这张卡上的「撤回」能把刚取消的这套让价整份打回去）。")
    c.has("撤回：范围缺席要拒（⛔ 不许默默当成整单）", mc, "discountLineIdsOf(")
    c.has("撤回：范围缺席时的话术逐字", mc,
          "这次写操作没有带上让价范围（payload 缺 discount_line_ids）—— 请重新说一遍要按哪几行让价。")
    c.has("撤回：范围里出现非数要拒（第二种坏法）", mc,
          "不是行号 —— 这次撤回的 payload 坏了，请重新说一遍要按哪几行让价。")
    c.has("资源表：取消让价与让价成对", rsc, "AiWrites.ORDERS_DISCOUNT_CLEAR,")
    c.has("资源表：成对动作是「让价」那条", rsc, "AiWrites.ORDERS_DISCOUNT,")
    c.has("资源表：订单号按 ID 映射", rsc, "\"order_id\" to AiRevert.ID,")
    c.has("资源表：方式映射回去", rsc, "\"discount_kind\" to \"discount_kind\",")
    c.has("资源表：数值映射回去", rsc, "\"discount_value\" to \"discount_value\",")
    c.has("资源表：范围映射回去", rsc, "\"discount_line_ids\" to \"discount_line_ids\",")
    c.has("资源表：理由映射回去", rsc, "\"discount_reason\" to \"discount_reason\",")
    c.has("资源表：idKey 是订单号", rsc, "idKey = \"order_id\",")
    c.has("资源表：撤回那两句第 1 句逐字", rs, "把刚才取消掉的那套让价整份打回去：方式、数值、范围、理由都是取消之前的样子")
    c.has("资源表：撤回那两句第 2 句逐字（同一条路、一样留痕）", rs,
          "后台按当时的快照精确还原每一行的金额（和手工重新让价是同一条路，也一样留痕）")
    c.has("资源表上方注释说清只有一个方向有按钮", rs, "两件事互为反面，但**只有一个方向有撤回按钮**")
    c.has("撤回表：定价那条抽得出来（理由写在表里）", rv, "listOf(AiWrites.ORDERS_PRICE_FREIGHT),")
    c.has("撤回表：定价没有按钮的理由（旧运费是空，撤回拼不出来）", rv, "写之前那一单根本没有旧的运费可以退回去")
    c.has("撤回表：定价那条给出路（说一句话就是同一个动作）", rv, "把 XXX 的运费改成 YYY")
    c.has("撤回表：定价那条说清不顺手沉淀价目", rv, "这一步不会顺手把价沉淀成价目，已经下过的单按当时的价定格")
    c.has("撤回表：让价那条抽得出来", rv, "listOf(AiWrites.ORDERS_DISCOUNT),")
    c.has("撤回表：让价没有按钮的理由（旧值是空的）", rv, "第一次让价时这一单原本没有折扣，旧值是空的")
    c.has("撤回表：让价那条指路到「取消让价」（那个有按钮）", rv, "不想让了就说「取消让价」")
    c.has("撤回表：注释点名这一节是 CHG-0087", rv, "CHG-0087")

    print("== 6. 额度：不限额 ≠ 0 元、撤回要能把「不限额」写回去 ==")
    cl = raw_block(mc, "class CreditLimitWriteHandler(")
    c.ok("额度处理器整块抽得出来", len(cl) > 800, "只抽到 " + str(len(cl)) + " 字符")
    c.has("「不限额」的判定词表在（说清它不是 0）", mc, "NO_LIMIT_WORDS")
    c.has("名册读不到要拒", mc, "没读到挂账单位名册，请稍后再试。")
    c.has("单条读不到（可能刚被删）也不许改别的单位", mc, "」现在的额度（它可能刚被删掉）。")
    c.has("单条读不到：接着说明不许改去设别的单位", mc, "请如实告诉用户，不要改去设别的单位。")
    c.has("额度一样时如实说不用改、一条都不写", mc, "，不用改。请告诉用户已经是这个数了。")
    c.has("卡片：单位那一行", mc, "单位：")
    c.has("卡片：改前改后那一段", mc, "———— 改成 ————")
    c.has("卡片：额度上限 → 新额度", mc, "额度上限：")
    c.has("卡片：不限额与 0 元是两件事（逐字）", mc,
          "「不限额」和「额度 0 元」是两件事：前者这个单位还能赊，后者一分钱都不许赊。")
    c.has("卡片：改动会留一条流水（谁改的、改前改后）", mc, "这次改动会在后台留一条流水（谁改的、改前改后各是多少）。")
    c.has("卡片标题：把哪个单位的额度改成多少", mc, "把挂账单位「")
    c.has("payload：单位按 ID（不是名字）", mc, "put(\"unit_id\", before.id)")
    c.has("payload：额度键名就是撤回快照的键名", mc, "credit_limit")
    #    2026-10-08（CHG-0087 收口）：这一槽的写法从 `limit?.let { JsonPrimitive(AiWriteArgs.money(it)) } ?: JsonNull`
    #    改成显式两分支 —— 因为 `_tools/qa/_check_money_display.py` 只认「`put("<槽>", AiWriteArgs.money(`
    #    是值形态（外面再包一层 lambda 它看不见，会当成印在卡片上的字）。语义一个字没变：清空额度
    #    仍然是 JsonNull（不是 0）；值那一支仍然走两位小数的 `money(`（不是去零的 `moneyText(`）。
    c.ok("payload：清空额度用 JsonNull（后端 null 是合法取值）",
         'put("credit_limit", JsonNull)' in mc and 'put("credit_limit", AiWriteArgs.money(limit))' in mc,
         "缺 JsonNull 那一支，或值那一支不是两位小数的 money( 形态")
    c.has("撤回：额度缺席要拒（⛔ 不许默默当成 0）", mc,
          "这次撤回没有带上额度 —— 请重新说一遍要把额度改成多少（或者说「不限额」）。")
    c.has("读回键含额度", rs, "readKeys = setOf(\"name\", \"phone\", \"remark\", \"credit_limit\"),")
    c.has("额度按钱显示（不是裸数字）", rs, "moneyKeys = setOf(\"credit_limit\"),")
    c.has("nullableWritable 点名额度（不点名那个撤回按钮就是假的）", rs, "nullableWritable = setOf(\"credit_limit\"),")
    c.has("资源表：额度那条动作挂在资源下", rsc, "update(AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT),")
    c.has("资源表：注释说清撤回走通用那条路（不额外声明）", rs, "所以撤回就是通用那条路（把这一个键写回旧值），不用额外声明")
    c.has("资源 key 逐字", rs, "key = \"arrears_unit\",")
    c.has("资源中文名逐字", rs, "cn = \"挂账单位\",")
    c.has("资源 idKey 逐字", rs, "idKey = \"unit_id\",")
    c.has("中文名里额度叫「额度上限」", rs, "\"credit_limit\" to \"额度上限\",")

    print("== 7. 数据层：四个方法 ＋ repo 转发一处 ＋ 红线白名单 ==")
    for sig in (
        "suspend fun priceFreight(orderId: Long, freightFee: String, categoryId: Long?)",
        "suspend fun clearOrderDiscount(orderId: Long)",
        "suspend fun orderLines(orderId: Long): List<AiOrderLine>",
    ):
        c.has("接口里有：" + sig, s, sig)
        c.has("实现里有：override " + sig, src, "override " + sig)
    c.has("接口里有：让价方法（多行签名）", s, "suspend fun applyOrderDiscount(")
    c.has("实现里有：让价方法", src, "override suspend fun applyOrderDiscount(")
    c.has("接口里有：设额度方法", s, "suspend fun setArrearsUnitCreditLimit(")
    c.has("实现里有：设额度方法", src, "override suspend fun setArrearsUnitCreditLimit(")
    c.ok("价格 / 让价 / 撤销三个方法各只声明一次",
         subs(s, "suspend fun priceFreight(") == 1 and subs(s, "suspend fun applyOrderDiscount(") == 1
         and subs(s, "suspend fun clearOrderDiscount(") == 1)
    c.has("定价实现走 repo.priceFreight", srcc, "repo.priceFreight(")
    c.has("让价实现走 repo.applyOrderDiscount", srcc, "repo.applyOrderDiscount(")
    c.has("取消让价实现走 repo.clearOrderDiscount", srcc, "repo.clearOrderDiscount(")
    clw = raw_block(srcc, "override suspend fun setArrearsUnitCreditLimit(")
    c.ok("设额度那一整段抽得出来（下面三条才有意义）", len(clw) > 300, "只抽到 " + str(len(clw)) + " 字符")
    c.has("额度实现走 repo.editArrearsUnit（额度是编辑表单上的一格）", clw, "repo.editArrearsUnit(")
    c.has("额度实现必须用 ArrearsUnitEditRequest（不是 Update）", clw, "ArrearsUnitEditRequest(")
    c.hasnt("⛔ 额度这条路上不许用 ArrearsUnitUpdateRequest（explicitNulls=false 会把 null 键丢掉）", clw, "ArrearsUnitUpdateRequest(")
    c.has("数据层注释写清了为什么必须是 Edit 那个请求体", src, '额度这一项"传字面 null = 清空"是合法的一态')
    c.has("额度读单条走名册里挑那一条（名册不含额度这个字段的说法保留）", srcc, "repo.arrearsUnits().firstOrNull { it.id == id }")
    c.has("单条读那一段写明额度为 null = 不限额（不是 0）", src, "额度为 null = **不限额**（不是 0），要如实往下传。")
    c.has("界面那一半的 canDiscount 与它同一条规矩（复用不是重写）", read(UI_DISCOUNT), "fun canDiscount(")
    c.has("红线白名单把单条读认成读（否则 prepare 里那一次读会被判成写）", read(GUARDRAILS), "\"arrearsUnit\",")
    c.has("红线白名单那段注释说清单数与复数是两个方法", read(GUARDRAILS),
          "与上面那个复数的 `arrearsUnits`（名册列表，按名字定位用）是**两个方法**")

    print("== 8. 覆盖表：四条不再挂在「不做」里、来龙去脉留着 ==")
    wcov = read(WRITE_COVERAGE)
    c.hasnt("POST /orders/{}/price-freight 不再挂在「不做」里", wcov, "(\"POST\", \"orders/{}/price-freight\")")
    c.hasnt("POST /orders/{}/discount 不再挂在「不做」里", wcov, "(\"POST\", \"orders/{}/discount\")")
    c.hasnt("DELETE /orders/{}/discount 不再挂在「不做」里", wcov, "(\"DELETE\", \"orders/{}/discount\")")
    c.hasnt("PATCH /arrears-units/{} 不再挂在「不做」里", wcov, "(\"PATCH\", \"arrears-units/{}\")")
    c.has("覆盖表点名台账 L-56", wcov, "台账 L-56")
    c.has("来龙去脉留着（定价当初关着的理由）", wcov, "手动定价要同时")
    c.has("来龙去脉留着（额度当初关着的理由）", wcov, "额度是「这个单位还能赊多少」")
    c.has("来龙去脉留着（让价当初关着的理由）", wcov, "一轮问一件事")
    c.has("覆盖表写明「沿用分类」这一层为什么必须显式发编号", wcov, "因此\"沿用\"必须把**当前分类的编号**显式发回去")
    c.has("覆盖表写明不限额与 0 元两件事", wcov, "与「额度 0 元」（一分钱都不许赊）在卡片上逐句分清")
    c.has("覆盖表写明 nullableWritable 是撤回按钮的前提", wcov, "那个按钮就是假的")
    c.has("覆盖表写明取消让价按快照还原", wcov, "还原是**按当时记下的快照**精确还原")
    c.has("能力格认领：覆盖表里记了这一批", read(FEATURE_COVERAGE), "CHG-0087")
    grc_out, grc = run_cmd([sys.executable, "_tools/ai/_check_ai_guardrails.py"])
    c.ok("AI 红线脚本实跑通过（exit 0）", grc == 0, "exit " + str(grc))
    wrc_out, wrc = run_cmd([sys.executable, "_tools/ai/_write_coverage.py"])
    c.ok("写覆盖脚本实跑通过（exit 0）", wrc == 0, "exit " + str(wrc))
    c.has("写覆盖表：未覆盖 27 条都有理由、0 条真缺口", wrc_out, "0 条是真缺口")
    #    2026-10-10 随动（BUG-0034 / BUG-0036）：开销挂软删与收款撤销各多两条写端点 ⇒ 未覆盖 19 → 23。
    c.has("写覆盖表：未覆盖是 27（本会话新增四条已进「不做」表）", wrc_out, "未覆盖 27")
    rrc_out, rrc = run_cmd([sys.executable, "_tools/ai/_read_coverage.py", "--check"])
    c.ok("读覆盖脚本 --check 实跑通过（exit 0）", rrc == 0, "exit " + str(rrc))
    c.has("读覆盖：没交代的仍然是 0", rrc_out, "没交代：0")

    print("== 9. 单测 / 文书 / 反验 / 防静默空转 ==")
    n_cases = sum(1 for name in CASE_NAMES if name in t)
    for name in CASE_NAMES:
        c.has("单测里有这一条：" + name, t, name)
    c.ok("单测里数到 14 条本单用例", n_cases == 14, "实际 " + str(n_cases))
    c.ok("单测里钉住了动作总数上界 176", "AiWrites.ALL.size <= 176" in t)
    c.has("单测里数到了本单的动作常量（定价）", t, "AiWrites.ORDERS_PRICE_FREIGHT")
    c.has("单测里数到了本单的动作常量（额度）", t, "AiWrites.ARREARS_UNIT_SET_CREDIT_LIMIT")
    c.has("假数据源把四条写都记下来了（定价一跳）", t, "moneyCalls += \"priceFreight:")
    c.has("假数据源记下了让价那一跳", t, "moneyCalls += \"applyOrderDiscount:")
    c.has("假数据源记下了取消让价那一跳", t, "moneyCalls += \"clearOrderDiscount:")
    c.has("假数据源记下了设额度那一跳", t, "moneyCalls += \"setArrearsUnitCreditLimit:")
    c.has("假数据源把读额度的单条那一跳也记下来了", t, "moneyCalls += \"arrearsUnit:")
    c.has("假数据源有挂账单位名册这个可塞的槽", t, "arrearsUnitRows")
    for sig in (
        "override suspend fun priceFreight(orderId: Long, freightFee: String, categoryId: Long?)",
        "override suspend fun applyOrderDiscount(",
        "override suspend fun clearOrderDiscount(orderId: Long)",
        "override suspend fun setArrearsUnitCreditLimit(id: Long, creditLimit: JsonElement)",
    ):
        c.has("假数据源实现了：" + sig, t, sig)
    c.has("单测文案里点名 CHG-0087", t, "CHG-0087")
    c.has("说明书上限已抬到 29000（动作数涨了）", pt, "上限 29000")
    c.has("说明书那两道闸门（约束项 / 整份）都在", pt, "上限 2600")
    c.ok("变更单九节齐（少一节 _check_dev_spec.py 也会红）", all(x in read(CHG_DOC) for x in CHG_SECTIONS),
         "缺：" + "、".join(x for x in CHG_SECTIONS if x not in read(CHG_DOC)))
    c.has("变更单里写了台账 L-56", read(CHG_DOC), "L-56")
    c.has("变更单里写清这一单是四单里的第四单", read(CHG_DOC), "第四单")
    c.has("登记簿里有这一条", read(REGISTRY), CHG_ID)
    c.has("工作声明里有这一条", read(CLAIM), CHG_ID)
    c.has("台账里有 L-56 那一行", read(LEDGER), "L-56")
    c.ok("反向验证脚本在", (ROOT / REVERSE).exists(), REVERSE)
    c.ok("判据自己数到了足够多的断言（>= 150 条）", c.passes >= 150, "实际 " + str(c.passes))

    if c.fails:
        print("❌ " + str(c.fails) + " 条不通过（共 " + str(c.passes + c.fails) + " 条）：")
        return 1
    print("✅ 全部 " + str(c.passes) + " 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
