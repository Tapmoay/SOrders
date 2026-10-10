"""业务多步工作流（对账 / 批量调价）：AI 认出来之后**自己按步骤跑完**（CHG-0096，goal 后半段）。

## 用户要的是什么（2026-10-09 本会话拍板）
- goal 原文：「业务工作流 —— 内置多步流程（对账、批量调价这类），AI 认出来后自己按步骤跑完整件事，
  用户少说几句。」
- 先做哪条：「**两条一起做**」—— 对账 + 批量调价同一单交。
- 跑到要改数据那一步：「**先给结论，再问一句要不要发卡**」—— 先把明细和金额摆出来让他看。

## 为什么这条必须有机器的判据（每一处坏了都不报错、不崩、单测也可能全绿）
1. **窗口口径错了 = 假账**：对账里订单那次读必须走 `extra` 的 `delivered_from/delivered_to`（筛**送达日**）。
   顺手写成 `from/to`，筛的是**下单日** —— 两张表用两种口径对差集，差出来的全是窗口差，
   结论会变成"这个月少记了三万块"这种**看着最像真的**假账。编译、单测、真机都不会喊。
2. **手工记的账被当成"已经进账本"**：`来源 = order` 那个过滤一松，手工那一笔就算这张单记过了 ⇒ **漏报**
   （明明没自动记，看着像记过了）。
3. **没有归属的单被算成"漏记"**：后端的规则是「已送达 **且**有归属才自动记」；不单列说明，
   用户会一直等那几张**永远不会回来**的账。
4. **没查全还照样给数字**：`incomplete` 那条分支被删（或 `missing_amount` 不再受它保护），
   截断后的半份数据会被当成完整的账报出去 —— 本仓最坏的一类错答案。
5. **倒着的窗口被当成空结果**：`from > to` 不拦，查回来是空的 ⇒ 结论变成"账全对"，同样是最坏的假账。
6. **它偷偷开始算价**：调价一旦在 runner 里自己算"改后"，就有了**第二份**涨降实现
   （唯一那份在 `AiWritePricing.kt` 的 BatchPriceHandler）—— 卡片上的数与结论里的数迟早对不上。
7. **写能力多出一条路**：runner 里直接碰写服务 = 「写只有 preview_write 一条路」这条红线破了。
8. **提示词里又抄了一份步骤**：步骤进提示词就会漂移（把 36 张表抄进提示词就是这个坑）。
9. **工具没注册 / 没进白名单**：模型根本不知道有这条工作流 —— **静默失效**，没有报错、没有日志。
10. **判据自己空转**：清单指向不存在的文件、反验脚本失踪、CHG 文档缺节、登记簿 / 工作声明被改名。
11. **账本明细又回到"模型自己按单拼"**（BUG-0019 / 台账 TB-04）：明细不由代码按来源算好、
    口径那句话被掏空、或者没查全也照样把账本明细说出去 —— 模型报的笔数/金额就会与库里的原始数据对不上
    （差的挂在**已进回收站**的单上），看着像**漏账**，其实只是口径没说。编译、单测、真机都不会喊。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
上面这些**没有一条是类型属性**：`"delivered_from"` 与 `"from"` 同型（都是 String），
`adjust` 与 `price` 都是可空 String（"恰好给一个"是**运行时**约束），
"没查全就不给数字"是**分支条件**，`来源 == "order"` 是**数据口径**。
类型系统、编译、单测都拦不住其中任何一条；判据只能落在源码结构上，
再配反向验证 `_reverse_verify_ai_workflow.py`（逐条弄坏一次，看它真的变红）。

静默空转保护：MIN_KT = 100（目录被搬走 / 一个 .kt 都没扫到也必须红）。

## 判据
1. `ai/AiWorkflow.kt`：登记表（两条工作流、id、步骤 action、交棒动作、`forRole` fail-closed）、
   工具说明与第 13 条规则**从登记表拼**、规则里**不许出现步骤**；
2. `ai/AiWorkflowRunner.kt`：窗口口径（送达日 / 账本日）、只认 `order`、无归属单列、
   没查全不给数字、倒窗口拦住、调价恰好一个参数且**一条价都不算**、交棒不写数据；
3. `ai/AiTools.kt`：`run_workflow` 注册齐全（ALL / GROUPS / TITLES / HINTS / DESCRIPTIONS /
   SCHEMAS / execute / 角色门）＋ 护栏白名单里有它；
4. `ai/AiAgentLoop.kt`：第 13 条拼进 systemPrompt（接在 12 之后、工具清单之前）；
5. 提示词体积预算里算上 `AiWorkflow.kt`；
6. 四个步骤 action 在 `AiReadCatalog.kt`（机器生成的目录）里真的存在；
7. 两个单测在，且关键档都在；文书齐（`CHG-0096.md` 九节 ＋ 登记簿 ＋ 工作声明）＋ 反验脚本在；
8. **账本那一侧（BUG-0019 / 台账 TB-04）**：笔数金额由代码按 `来源` 分组算、整单退货由代码判、
   来源中文走全 App 唯一那一份表（执行器里 ⛔ 不许再抄一份）、口径那句话只有一份且**只在查全时**跟着结论走、
   没查全时一个字都不说账本明细；`BUG-0019.md` 九节 ＋ 登记簿 ＋ 工作声明。

用法：python _tools/qa/_check_ai_workflow.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AI = AND / "ai"
WORKFLOW = AI / "AiWorkflow.kt"
RUNNER = AI / "AiWorkflowRunner.kt"
TOOLS = AI / "AiTools.kt"
LOOP = AI / "AiAgentLoop.kt"
CATALOG = AI / "AiReadCatalog.kt"
TEST_REG = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWorkflowTest.kt"
TEST_RUN = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWorkflowRunnerTest.kt"
GUARD = ROOT / "_tools/ai/_check_ai_guardrails.py"
SIZE = ROOT / "_tools/ai/_sysprompt_size.py"
DOC = ROOT / "docs/changes/CHG-0096.md"
REG = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_ai_workflow.py"

#: 全 App 唯一那一份「账本来源 → 中文名」的表（BUG-0019 / 台账 TB-04：执行器里 ⛔ 不许再抄一份）。
LEDGER_SOURCE_LABEL = AND / "core/LedgerSourceLabel.kt"

#: 这条单自己的变更文书（九节 ＋ 登记簿 ＋ 工作声明）。
BUG_DOC = ROOT / "docs/changes/BUG-0019.md"

#: 工具开关的默认集与那条纯函数（BUG-0022：设置页「跑工作流」点开就弹回）。
KEYSTORE = AI / "AiKeyStore.kt"
TEST_ENABLED = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiEnabledToolsTest.kt"
TEST_ENDPOINT = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiEndpointRulesTest.kt"

#: BUG-0022 的变更文书 ＋ 台账（真机抓到的那条「开关看起来有、其实没有」）。
BUG_0022_DOC = ROOT / "docs/changes/BUG-0022.md"
LEDGER = ROOT / "docs/TEST_BUG_LEDGER.md"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 四条步骤 action：两条工作流一共读四张表，**都必须在机器生成的读目录里真的存在**。
STEP_ACTIONS = [
    "orders.list_orders",
    "ledger.list_entries",
    "products.list_products",
    "price_rules.list_price_rules",
]

#: 变更单九节的标题（逐字照 _TEMPLATE.md）。
SECTIONS = [
    "## ① 六问",
    "## ② Must Change / Must Not Change",
    "## ③ Boundary（Core / Extension / Infrastructure / Presentation）",
    "## ④ Behavior Contract",
    "## ⑤ Data Contract",
    "## ⑥ CHG 专章",
    "## ⑦ 测试（四件事都要，缺一件就不算完整）",
    "## ⑧ 证据",
    "## ⑨ 关闭（六格）",
]


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is not None, "没找到 " + repr(pattern))

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is None, "命中：" + repr(m.group(0)) if m else "")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    KDoc 里抄着用户原话与"为什么"，里面也会出现 `from/to`、`order` 这些**看起来像判据**的字样 ——
    判据要抓的是**代码里**还有没有那几件事。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        msg = "找不到文件：" + str(p) + "（被改名/搬走了？这条判据要跟着改）"
        # ⚠️ 先打到 stdout：stderr 在 Windows 上默认走 ANSI 代码页，反验脚本按 utf-8 抓它就成乱码，
        # 于是「文件被改名」这条反验会假绿（2026-10-09 实测：SystemExit 那句话只在 stderr 上）。
        print(msg)
        raise SystemExit(msg)
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def main() -> int:
    c = Checker()
    wf = read(WORKFLOW)
    wf_code = code_only(wf)
    runner = read(RUNNER)
    runner_code = code_only(runner)
    tools = read(TOOLS)
    tools_code = code_only(tools)
    loop = read(LOOP)
    loop_code = code_only(loop)
    catalog = read(CATALOG)

    kt = sorted(AND.rglob("*.kt"))

    print("== 0. 反空转：扫描本身得是活的 ==")
    c.ok("扫到 %d 个 .kt（下限 %d）" % (len(kt), MIN_KT), len(kt) >= MIN_KT)
    c.ok("扫到登记表那个 .kt", WORKFLOW.name in {p.name for p in kt})
    c.ok("扫到执行器那个 .kt", RUNNER.name in {p.name for p in kt})

    print("\n== 1. 登记表：两条工作流、步骤、交棒 ==")
    c.present("两步的形状（标题 ＋ 读目录里的 action，两个字段各自写明用途）", wf,
              r"internal data class AiWorkflowStep\(\s*\n\s*/\*\*[\s\S]*?\*/\s*\n\s*val title: String,\s*\n\s*/\*\*[\s\S]*?\*/\s*\n\s*val action: String,")
              # FEAT-0020：nextAction / ask 改成**可空**（只读工作流两条都是 null）。
    c.present("一条工作流的形状（什么时候用 / 参数 / 步骤 / 交棒 / 要问的那一句）", wf_code,
              r"internal data class AiWorkflow\(\s*\n\s*val id: String,\s*\n\s*val cn: String,[\s\S]{0,400}?val steps: List<AiWorkflowStep>,\s*\n\s*val nextAction: String\?,")
    c.present("只读 = 交棒动作为空（readOnly 由它推出来，不另存一个标记）", wf_code,
              r"val readOnly: Boolean get\(\) = nextAction == null")
    c.present("两条 id 逐字（写进提示词、工具 enum、run(id)）", wf_code,
              r'const val LEDGER_RECONCILE = "ledger\.reconcile"\s*\n\s*const val PRICE_BATCH = "price\.batch"')
    c.present("对账的第 1 步：已送达的订单（送达日窗口）", wf_code,
              r'AiWorkflowStep\("查这段时间已送达的订单", "orders\.list_orders"\)')
    c.present("对账的第 2 步：账本流水", wf_code,
              r'AiWorkflowStep\("查这段时间的账本流水", "ledger\.list_entries"\)')
    c.present("调价的第 1 步：商品与通用价", wf_code,
              r'AiWorkflowStep\("查商品与通用价", "products\.list_products"\)')
    c.present("调价的第 2 步：现有专属价", wf_code,
              r'AiWorkflowStep\("查现有的批发商专属价", "price_rules\.list_price_rules"\)')
    c.present("对账交棒给「补进账本」（写动作的 id，不是自己执行）", wf_code,
              r"nextAction = AiWrites\.LEDGER_SYNC_DELIVERED,")
    c.present("调价交棒给「批量调价」", wf_code, r"nextAction = AiWrites\.PRICE_RULES_BATCH,")
    c.present("enum 从登记表算（加一条不用手改 schema）", wf_code,
              r"val IDS: List<String> = ALL\.map \{ it\.id \}")
              # FEAT-0020：forRole 换成 actor 感知的 forActor（第二维是"是不是批发商货主"）。
    c.present("认不出角色 = 一条都不给（与工具白名单同一条 fail-closed）", wf_code,
              r"val role = actor\?\.role \?: return emptyList\(\)")
    c.present("默认只给派单员（要发的写动作不在货主白名单里的那几条留在这个默认值上）", wf_code,
              r"val roles: Set<AiRole> = setOf\(AiRole\.DISPATCHER\),")
    c.present("memberOnly 那条只给批发商货主（与 AiWriteAction.memberOnly 同一条）", wf_code,
              r"\(!it\.memberOnly \|\| member\)")
    c.present("工具说明**从登记表拼**（手写的清单一定会漏）", wf_code,
              r"val TOOL_DESCRIPTION: String = buildString \{\s*\n[\s\S]{0,300}?ALL\.forEach \{ w ->")
    c.present("工具说明写明它自己不写数据", wf_code, r"它自己一步都不写")
    c.present("工具说明写明默认时间范围", wf_code, r"本月 1 号到今天")
    c.present("工具说明写明先问用户再发卡", wf_code, r"用户没点头\*\*不许\*\*调 preview_write")

    print("\n== 2. 第 13 条规则：目录与纪律都写到，而且**不写步骤** ==")
    c.present("编号 13（接在 12 之后）", wf_code, r'appendLine\("13\. \*\*认出「多步的活」')
    c.present("纪律：结论是查出来的，照原话说、不许自己再算", wf_code, r"照原话说")
    c.present("纪律：steps 是每一步实际条数（不许编中间的查询）", wf_code, r"不要编中间的查询")
    c.present("纪律：先给结论再问那一句、没点头不许发卡", wf_code, r"\*\*先把结论给用户，再问那一句\*\*")
    c.present("纪律：没查全不许当完整的账", wf_code, r"不许把那些数字当完整的账")
    c.present("纪律：不适用时退回自己一步一步查", wf_code, r"退回你自己用 read_data 一步一步查")
    idx = wf.find("val RULES: String = buildString {")
    c.ok("能定位到第 13 条那一块（RULES 在文件最后一个块）", idx > 0)
    rules_block = wf[idx:] if idx > 0 else ""
    for a in STEP_ACTIONS:
        c.ok("⛔ 规则块里不许出现步骤 action（" + a + "）：步骤只在代码里跑，抄一份就会漂移",
             a not in rules_block)

    print("\n== 3. 用户口径留档（下一个人知道为什么要有这一层） ==")
    c.present("写了「两条一起做」", wf, r"两条一起做")
    c.present("写了「先给结论，再问一句要不要发卡」", wf, r"先给结论，再问一句要不要发卡")
    c.present("留了 goal 原话（用户少说几句）", wf, r"用户少说几句")
    c.present("写了为什么不是提示词里的步骤清单（窗口一错就是假账）", wf, r"看着最像真的")
    c.present("留了 goal 编号（对得上路线图那一条）", wf, r"goal-9c29e859-ec5e-444e-9e78-6e330bf0aa07")
    c.present("登记表里写了本单编号", wf, r"CHG-0096")
    c.present("执行器的 KDoc 也写了本单编号", runner, r"CHG-0096")

    print("\n== 4. 执行器：对账的窗口口径（错了就是假账） ==")
    c.present("签名：注入读接口 ＋ 注入今天（判据才钉得住默认窗口）", runner_code,
              r"internal class AiWorkflowRunner\(\s*\n\s*private val read: suspend \(String, JsonObject\) -> String,\s*\n\s*private val today: \(\) -> LocalDate = \{ LocalDate\.now\(\) \},")
    c.present("按 id 分派，认不出/没接上都报错", runner_code,
              r"when \(wf\.id\) \{\s*\n\s*AiWorkflows\.LEDGER_RECONCILE -> reconcile\(wf, args, t, win\.first, win\.second\)\s*\n\s*AiWorkflows\.PRICE_BATCH -> priceBatch\(wf, args, t\)")
    c.present("默认窗口 = 本月 1 号 → 今天", runner_code,
              r'val from = date\(args, "from"\) \?: t\.withDayOfMonth\(1\)\.toString\(\)\s*\n\s*val to = date\(args, "to"\) \?: t\.toString\(\)')
    c.present("倒着的窗口返回 null（不许当成空结果）", runner_code,
              r"return if \(from > to\) null else from to to")
    c.present("倒窗口时直接报错、一个读都不发", runner_code, r"时间范围反了")
    c.present("订单那次读：只取已送达", runner_code, r'put\("status", STATUS_DELIVERED\)')
    c.present("订单那次读：送达日窗口走 extra", runner_code,
              r'put\("extra", buildJsonObject \{\s*\n\s*put\("delivered_from", from\)\s*\n\s*put\("delivered_to", to\)')
    c.present("账本那次读：日期窗口是本表的 from/to", runner_code, r'put\("from", from\)\s*\n\s*put\("to", to\)')
    c.present("只认「订单送达自动记账」的行（来源 = order）", runner_code,
              r"\.filter \{ field\(it, \*SOURCE\)\?\.lowercase\(\) == SOURCE_ORDER \}")
    c.present("手工记账（manual）不算这张单已经进账本 —— KDoc 写明了为什么", runner, r"手工那一笔可能压根不是这张单的")
    c.present("没有归属的单单列（系统不会自动记，不算漏记）", runner_code,
              r"val unowned = withNo\.filterNot \{ hasOwner\(it\) \}")
    c.present("结论里说明无归属要人工处理、不算漏记", runner_code, r"它不算「漏记」")
    c.ok("差集：订单里有、账上（来源=order）没有的才叫漏记",
         "val missing = owned.filter { field(it, *ORDER_NO) !in booked }" in runner_code)
    c.present("账上有、这批订单里没有的也单列", runner_code, r"val ledgerOnly = booked\.filterNot \{ it in seen \}")
    c.present("一刀切的干净判据（缺账/无归属/账上多/无单号 全空才算干净）", runner_code,
              r"val clean = missing\.isEmpty\(\) && unowned\.isEmpty\(\) && ledgerOnly\.isEmpty\(\) && noNo == 0")

    print("\n== 5. 执行器：没查全就不给数字（最坏的一类错答案） ==")
    c.present("没查全 = 任一步被截断", runner_code,
              r"val incomplete = orders\.truncated \|\| ledger\.truncated")
    c.present("没查全时**不给** missing_amount（不是给个 0）", runner_code,
              r'if \(!incomplete\) put\("missing_amount"')
    c.present("没查全的结论：缩小范围重跑", runner_code, r"把时间范围缩小一点（比如按周）再跑一次")
    c.present("痕迹里也标出来", runner_code, r'append\(" · 没查全"\)')
    c.present("金额解析不了不算 0", runner_code,
              r"runCatching \{ BigDecimal\(raw\) \}\.getOrNull\(\)")
    c.present("读接口出错就停下（不拿半份数据下结论）", runner_code,
              r'orders\.error\?\.let \{ return err\(')
    steps_used = re.findall(r"wf\.steps\[(\d)\]", runner_code)
    c.ok("步骤是从登记表取的（" + ",".join(sorted(set(steps_used))) + "），不在执行器里另写一遍文案",
         len(steps_used) >= 2)

    print("\n== 6. 执行器：调价恰好一个改法，而且**一条价都不算** ==")
    c.present("adjust 与 price 恰好给一个", runner_code,
              r"if \(\(adjust == null\) == \(price == null\)\)")
    c.present("两个都给/都不给时把话说清楚", runner_code, r"\*\*恰好\*\*给一个")
    for bad in ("multiply", r"divide\(", "setScale", "RoundingMode"):
        c.absent("⛔ 执行器里不许出现算价的痕迹（" + bad + "）—— 涨降算法只有确认卡上那一份实现",
                 runner_code, bad)
    c.present("名字对不上要单独说（差一个字就是另一个商品）", runner_code, r"差一个字就是另一个商品")
    c.present("两张表都没有可用筛参 ⇒ 整体取回、本地按名字匹配（写明了原因）", runner,
              r"目录里 price_rules 一个参数都没有")
    c.present("「全部 / 所有」= 不过滤", runner_code, r'val ALL_WORDS = setOf\("全部", "所有"')

    print("\n== 7. 执行器：写能力仍然只有一条路 ==")
              # FEAT-0020：nextAction 可空之后，交棒那一段先把它取出来（只读的走到这里就当场抛）。
    c.present("交棒那一段：动作 + 人话名字 + 参数 + 要问的那一句", runner_code,
              r'private fun nextJson\(wf: AiWorkflow, params: JsonObject\): JsonObject \{[\s\S]{0,260}?'
              + r'put\("action", action\)\s*\n\s*'
              + r'put\("action_cn", AiWrites\.titleOf\(action\)\)')
    c.present("⛔ 只读工作流不许走交棒（登记表与执行分支接错时当场抛，别静默发一张空卡）", runner_code,
              r'wf\.nextAction\s*\n\s*\?: error\("只读工作流没有交棒动作')
    c.present("交棒里写明「用户点头之后再调 preview_write」", runner_code, r"用户点头之后再调 preview_write")
    for bad in ("AiWriteService", r"com\.tapmoay\.sorders\.data"):
        c.absent("⛔ 执行器不许碰写服务 / 数据层（" + bad + "）：它只读",
                 runner_code, bad)

    print("\n== 8. 工具注册：run_workflow 一处都不能少 ==")
    c.present("常量", tools_code, r'const val RUN_WORKFLOW = "run_workflow"')
    m = re.search(r"val ALL = listOf\((.*?)\)\s*\n", tools_code, re.S)
    c.ok("ALL 里有它（漏了 = 模型根本不知道有这条工作流：静默失效）",
         bool(m) and "RUN_WORKFLOW" in m.group(1), "ALL = " + (m.group(1).strip() if m else "<没匹配到>"))
    c.present("设置页分组（查询类）", tools_code, r"RUN_WORKFLOW to Group\.QUERY,")
    c.present("设置页标题", tools_code, r'RUN_WORKFLOW to "跑工作流",')
    c.present("设置页一句话（⛔ 不解析 Markdown，所以不许写 **加粗**）", tools_code,
              r'RUN_WORKFLOW to "一句话跑完对账、批量调价这类多步的事')
    c.present("工具说明用登记表生成的那一份", tools_code, r"RUN_WORKFLOW to AiWorkflows\.TOOL_DESCRIPTION,")
    c.present("execute 分派", tools_code, r"RUN_WORKFLOW -> runWorkflow\(args\)")
              # FEAT-0020：schema 改成**动态**的（说明与 enum 都按角色裁）——静态那份已删，
              # 理由是 [readDataSpec] 那条：specs 到不了 specOf，留着就是第二份会走散的清单。
    c.present("schema：workflow 必填 ＋ enum 按角色裁（动态 spec）", tools_code,
              r"private fun runWorkflowSpec\(actor: AiActor\?\): ToolSpec \{")
    c.present("enum/说明只列这个角色能跑的（三处同源：工具说明 ＋ enum ＋ 执行前的门）", tools_code,
              r"AiWorkflows\.forActor\(actor\)")
    c.absent("⛔ 静态 SCHEMAS 里不许再抄一份 RUN_WORKFLOW 的参数定义（会走散）", tools_code,
             r"RUN_WORKFLOW to buildJsonObject \{")
    c.present("认不出工作流时列出能跑的（" + "AiWorkflows.IDS" + "）", tools_code,
              r'\?: return err\("认不出工作流「" \+ id \+ "」。现在能跑的是：" \+ AiWorkflows\.IDS\.joinToString')
    c.present("角色门：与 enum / 说明同一份判据（forActor 那一份）", tools_code,
              r"if \(!AiWorkflows\.allows\(actor\(\), wf\.id\)\) \{")
    c.present("执行器接的是 read_data 走的那条读路径", tools_code,
              r"AiWorkflowRunner\(read = \{ action, a -> reader\.read\(action, a\) \}\)\.run\(id, args\)")
    guard = read(GUARD)
    c.present("护栏白名单里有 run_workflow（加工具必须同时改它）", guard, r'"run_workflow"')

    print("\n== 9. 提示词：第 13 条真的拼进去了，位置也对 ==")
    c.present("拼进 systemPrompt", loop_code, r"append\(AiWorkflows\.RULES\)")
    a1 = loop_code.find("append(AiAnswerStyle.RULES)")
    a2 = loop_code.find("append(AiAnswerSkills.RULES)")
    a3 = loop_code.find("append(AiWorkflows.RULES)")
    c.ok("顺序：Style(10) → Skills(12) → Workflows(13)", a1 >= 0 and a1 < a2 < a3,
         "位置 %d / %d / %d" % (a1, a2, a3))
    tools_line = loop_code.find('当前已启用的工具只有')
    c.ok("位置：在工具清单行**之前**（清单说的是「当前有什么」，规则排在它前面）",
         a3 >= 0 and tools_line > a3, "工作流 %d / 清单 %d" % (a3, tools_line))
    c.present("提示词体积预算里算上了这一块", read(SIZE), r'AiWorkflow\.kt')

    print("\n== 10. 跨文件：四条步骤 action 在机器生成的读目录里真的存在 ==")
    for a in STEP_ACTIONS:
        c.ok("读目录里有 " + a, ('ReadAction("' + a + '"') in catalog)

    print("\n== 11. 单测：登记表与执行器都钉住了 ==")
    t_reg = read(TEST_REG)
    t_run = read(TEST_RUN)
    for name in ["八条工作流都在登记表里", "步骤用的 action 就是这几个", "交棒的动作必须是真实存在的写动作",
                 "认不出角色就一条都不给", "第 13 条", "只读工作流不发卡"]:
        c.present("登记表单测有这一档：" + name, t_reg, re.escape(name))
    c.present("登记表单测查的是真的那两份文案", t_reg, r"AiWorkflows\.RULES")
    c.present("登记表单测钉住交棒动作确实存在", t_reg, r"AiWrites\.byId\(action\) != null")
    c.present("登记表单测钉住「只读的两条不发卡」", t_reg, r"只读工作流不发卡")
    for name in ["漏记的单被列出来", "默认窗口是本月 1 号到今天", "手工记的账不算这张单已经进账本",
                 "没有归属的单不算漏记", "账上有订单里没有的", "行里没有订单号的不算进对账",
                 "没查全就不给数字结论", "窗口反了直接报错", "读接口出错就停下来",
                 "调价的改法必须恰好给一个", "名字能对上时统计会被这张卡覆盖的专属价",
                 "名字对不上要单独说", "调价一条价都不算"]:
        c.present("执行器单测有这一档：" + name, t_run, re.escape(name))
    for lit in ["delivered_from", '"manual"', '"恰好"', "incomplete", "没查全", "不在这里算"]:
        c.present("执行器单测逐字断言 " + lit, t_run, re.escape(lit))
    c.present("执行器单测用的是注入的假读（不出网、不碰后端）", t_run, r"private class FakeRead")

    print("\n== 12. 账本那一侧的明细（TB-04 / BUG-0019）==")
    lsl = read(LEDGER_SOURCE_LABEL)
    # 台账 TB-04：模型原来自己按单拼明细 —— 报「退货红冲 8 笔 −431.50」，库里同窗口 10 笔 −570.70，
    # 差的 2 笔挂在**已进回收站**的单上（账本口径两边都不计）。病灶是「明细让模型自己拼 ＋ 口径没说」，
    # 所以这一节钉的是：明细是不是**代码按来源算好的**、整单退货是不是**代码判的**、
    # 口径那句话是不是**只有一份且只在查全时跟着结论走**、没查全时是不是**一个字都不说**。
    c.present("明细按「来源」分组算（笔数/金额都是代码算的）", runner_code,
              r"ledger\.rows\.groupBy \{ field\(it, \*SOURCE\)")
    c.present("每一行明细都带来源 / 来源说明 / 笔数 / 金额", runner_code,
              r'put\("来源", src\)[\s\S]{0,240}?put\("来源说明", ledgerSourceLabel\(src\)\)'
              r'[\s\S]{0,240}?put\("笔数", rows\.size\)[\s\S]{0,240}?put\("金额", AiWriteArgs\.moneyText\(sumMoney\(rows, \*MONEY\)\)\)')
    c.present("来源的中文名走全 App 唯一那一份表", runner_code, r"ledgerSourceLabel\(src\)")
    c.absent("⛔ 执行器里没有再抄一份来源中文表（按来源 when 出中文）", runner_code, r'"return"\s*->')
    c.present("退货红冲那一档单独拎出来（SOURCE_RETURN）", runner_code, r"bySource\[SOURCE_RETURN\]")
    c.present("退货红冲的合计是代码加出来的（⛔ 不是让模型自己加）", runner_code,
              r"val returnsAmount = sumMoney\(returns, \*MONEY\)")
    c.present("整单退货 / 部分退是代码判的", runner_code,
              r"private fun isWholeOrderReturn\(row: JsonObject, seen: Set<String>\): Boolean")
    c.present("判据是「这张单在不在本次已送达清单里」（⛔ 不重新查一遍）", runner_code, r"return no !in seen")
    c.present("逐行明细给到订单号 / 日期 / 金额 / 商品 / 货主", runner_code,
              r'put\("订单号", field\(row, \*ORDER_NO\)[\s\S]{0,200}?put\("日期", field\(row, \*ENTRY_DATE\)'
              r'[\s\S]{0,400}?put\("金额", money\(row, \*MONEY\)[\s\S]{0,300}?put\("货主", field\(row, \*SHIPPER, \*TEMP_SHIPPER\)')
    c.present("每一行的「整单退货」那一栏也是代码判的", runner_code,
              r'put\("整单退货", wholeReturnCn\(row, seen\)\)')
    c.present("口径那句话写死成常量（只有一份）", runner_code, r"const val SCOPE_NOTE")
    c.present("口径把「没进回收站」讲清楚", runner_code, r"SCOPE_NOTE = [\s\S]{0,300}?没进回收站")
    c.present("口径点明「成对存在、净额 0」", runner_code, r"成对存在、净额 0")
    c.present("口径点明「那不是漏账」", runner_code, r"那不是漏账")
    c.present("结论只在**查全**时才接账本那两句（没查全一个字都不说）", runner_code,
              r"val conclusion = if \(incomplete\) baseConclusion else baseConclusion \+ returnsCn \+ SCOPE_NOTE")
    c.present("退货红冲那几句话里带着「不要自己按单拼明细」", runner_code, r"不要自己按单拼明细")
    for key in ['putJsonArray("ledger_detail")', 'put("returns_count"', 'put("returns_amount"',
                'putJsonArray("returns")', 'put("scope_note", SCOPE_NOTE)']:
        c.present("结果里交了 " + key, runner_code, re.escape(key))
    c.present("整单退货的笔数也单独交出去", runner_code, r'put\("whole_order_returns", wholeReturns\)')
    c.present("明细纪律进提示词（照 ledger_detail / returns 说）", wf_code, r"ledger_detail")
    c.present("明细纪律进提示词（⛔ 不许自己按单去拼明细）", wf_code, r"不许自己按单去拼明细")
    c.present("明细纪律进提示词（先讲 scope_note 那条口径）", wf_code, r"scope_note")
    c.present("来源中文表认得出「退货红冲」", lsl, r'"return" -> "退货红冲"')
    c.present("来源表 KDoc 里点明了这一档（order / manual / refund / return）", lsl,
              r"\`order\` / \`manual\` / \`refund\` / \`return\`")
    for name in ["账本明细是按来源算出来的", "整单退货还是部分退", "口径那句话只有一份",
                 "没查全时一个字都不说账本明细"]:
        c.present("执行器单测有这一档：" + name, t_run, re.escape(name))

    print("\n== 13. 文书与反向验证 ==")
    doc = read(DOC)
    missing = [s for s in SECTIONS if s not in doc]
    c.ok("CHG-0096.md 九节齐全", not missing, "缺：" + " / ".join(missing))
    # ⛔ 光有编号不够：编号被别的单占了（或搬错文件）也会"绿"。这一份得**确实是这两条工作流的单**。
    head = doc.splitlines()[0] if doc.splitlines() else ""
    c.present("标题里能看出是这条单", head, r"工作流")
    c.present("文档正文写的是对账这一条", doc, r"对账")
    c.present("文档正文写的是批量调价这一条", doc, r"批量调价")
    reg_line = ""
    for ln in read(REG).splitlines():
        if "CHG-0096" in ln:
            reg_line = ln
            break
    c.ok("登记簿有 CHG-0096 这一行，而且那一行说的就是这条单",
         ("工作流" in reg_line) and ("对账" in reg_line), "行：" + reg_line[:140])
    claim_line = ""
    for ln in read(CLAIM).splitlines():
        if "CHG-0096" in ln:
            claim_line = ln
            break
    c.ok("工作声明里记了这条活（标题里看得出是哪条单）",
         ("CHG-0096" in claim_line) and ("工作流" in claim_line), "行：" + claim_line[:140])
    bug = read(BUG_DOC)
    missing_bug = [s for s in SECTIONS if s not in bug]
    c.ok("BUG-0019.md 九节齐全", not missing_bug, "缺：" + " / ".join(missing_bug))
    c.present("BUG-0019 写的就是账本口径这一条", bug, r"退货红冲")
    c.present("BUG-0019 点明了回收站那条口径", bug, r"回收站")
    reg_bug = ""
    for ln in read(REG).splitlines():
        if "BUG-0019" in ln:
            reg_bug = ln
            # ⛔ 别的单的登记行里也会提一句 BUG-0019（例如 BUG-0022 那行写着「BUG-0019 真机取证时抓到」）——
            # 取到那种行会误判，所以优先收下**同时含预期关键词**的那一行。
            if "退货红冲" in ln:
                break
    c.ok("登记簿有 BUG-0019 这一行，而且那一行说的就是这条单",
         ("BUG-0019" in reg_bug) and ("退货红冲" in reg_bug), "行：" + reg_bug[:140])
    claim_bug = ""
    for ln in read(CLAIM).splitlines():
        if "BUG-0019" in ln:
            claim_bug = ln
            # 同上：BUG-0022 的声明块里也会提一句 BUG-0019（缺陷出处那一行），它不含「账本」。
            if "账本" in ln:
                break
    c.ok("工作声明里记了这条活", ("BUG-0019" in claim_bug) and ("账本" in claim_bug), "行：" + claim_bug[:140])
    c.ok("反验脚本在：" + REVERSE.name, REVERSE.exists())

    print("\n== 14. 「跑工作流」那条开关真的能打开（BUG-0022）==")
    # 真机取证（2026-10-09，emulator-5554）：设置页 →「AI 能用的能力」里那条「跑工作流」开关
    # **能点开**、prefs 的 `enabled_tools` 里**确实存了** `run_workflow`，可**再进这一页它又变回关的**
    # （抬头永远写着「查询 7/8」），模型的工具表里从来没有它 —— 它只能如实回一句
    # 「对账工作流（ledger.reconcile）在我这边没有启用，我跑不了它」。
    # 根因：`AiKeyStore.DEFAULT_ENABLED_TOOLS` 漏了这一项，而 `resolveEnabledTools` 末尾那句
    # `intersect(DEFAULT_ENABLED_TOOLS)` 会把任何不在其中的名字**静默筛掉**（正是那个常量
    # 自己的 KDoc 警告过的失效形状）。⇒ 工作流在真机上从来没跑起来过，BUG-0019 的明细桥
    # 也就没有一条真机路径能证明 —— 这一节钉的就是"开关必须真的能打开"。
    ks = read(KEYSTORE)
    block = re.search(r"val DEFAULT_ENABLED_TOOLS: Set<String> = linkedSetOf\(([\s\S]*?)\)\s*\n", ks)
    c.ok("能定位到默认工具集", block is not None,
         "正则没匹配到 `val DEFAULT_ENABLED_TOOLS: Set<String> = linkedSetOf(`")
    default_set = block.group(1) if block else ""
    c.present("只读工具 run_workflow 在默认集里（漏了 = 开关点开就弹回）", default_set,
              r"AiTools\.RUN_WORKFLOW")
    c.present("末尾那句 intersect 还在（它才是筛子）", ks, r"intersect\(DEFAULT_ENABLED_TOOLS\)")
    c.present("源码里点明了这一条为什么危险（BUG-0022）", ks, r"BUG-0022")
    c.present("单测钉住「存进 prefs 的 run_workflow 不许被筛掉」", read(TEST_ENABLED),
              re.escape("用户自己点开的 run_workflow 不许被筛掉（存进 prefs 也不生效就是这个 bug）"))
    c.present("单测钉住「默认集里必须有它」", read(TEST_ENDPOINT),
              re.escape("只读工具 run_workflow 必须在默认集里（BUG-0022）"))
    doc22 = read(BUG_0022_DOC)
    missing22 = [s for s in SECTIONS if s not in doc22]
    c.ok("BUG-0022.md 九节齐全", not missing22, "缺：" + " / ".join(missing22))
    c.present("BUG-0022 写的就是这条开关", doc22, r"跑工作流")
    c.present("BUG-0022 点明了真机取证那一份 prefs", doc22, r"enabled_tools")
    reg22 = ""
    for ln in read(REG).splitlines():
        if "BUG-0022" in ln:
            reg22 = ln
            if "工作流" in ln:
                break
    c.ok("登记簿有 BUG-0022 这一行，而且那一行说的就是这条单",
         ("BUG-0022" in reg22) and ("工作流" in reg22), "行：" + reg22[:140])
    claim22 = ""
    for ln in read(CLAIM).splitlines():
        if "BUG-0022" in ln:
            claim22 = ln
            if "工作流" in ln:
                break
    c.ok("工作声明里记了这条活", ("BUG-0022" in claim22) and ("工作流" in claim22), "行：" + claim22[:140])
    c.present("台账里有这一条", read(LEDGER), r"跑工作流")
    c.present("反验脚本里有这一节", read(REVERSE), r"BUG-0022")

    print("\n" + "=" * 60)
    if c.fails:
        print("❌ %d/%d 项没通过：" % (len(c.fails), c.passes + len(c.fails)))
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 %d 项通过：两条工作流（对账 / 批量调价）都是**代码里的编排**，" % c.passes)
    print("   窗口口径、差集规则、没查全不给数字、一条价都不算、写仍只有 preview_write 一条路。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
