"""反向验证 `_check_ai_workflow.py`（CHG-0096）：逐条把红线弄坏一次，看判据**真的报红**。

判据自己也会说谎 —— 锚点写歪、文件读错、清单指向不存在的路径，都会让它"永远绿"。
这个脚本把判据里每一条**关键断言**对应的源码各改坏一次（一次只改一处），
改完立刻跑判据，要求它**非零退出**且输出里出现**那一条的标签文字**，跑完逐字节还原。

三条失效方式（写这个脚本时最该防的）：
1. **注入没生效**（锚点行被重排/改字了）⇒ 判据当然还是绿的，看着像"判据没抓到"。
   这里对每一处都先比对新旧文本，一样就报"锚点变了，请更新本脚本"。
2. **还原不干净** ⇒ 工作树里留半截改动。跑完按字节核对，不一致就强制写回并报红。
3. **判据整体塌了**（比如某个文件被改名 ⇒ 判据一开始就 SystemExit）⇒ 那也算"报红"，
   但它没证明**那一条**在检查。所以每一条都要求输出里出现**该条的标签关键词**。

R4-BOUNDARY-JUSTIFICATION: 只读 12 个文件、只**临时**改其中被注入的那一个（跑完立刻按字节还原），
不碰数据库、不碰网络、不跑 gradle。改动全部落在工作树里，且每一处都在 finally 语义里还原。

用法：python _tools/qa/_reverse_verify_ai_workflow.py
"""
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_ai_workflow.py"
AND = "android/app/src/main/java/com/tapmoay/sorders/"
WORKFLOW = AND + "ai/AiWorkflow.kt"
RUNNER = AND + "ai/AiWorkflowRunner.kt"
TOOLS = AND + "ai/AiTools.kt"
LOOP = AND + "ai/AiAgentLoop.kt"
CATALOG = AND + "ai/AiReadCatalog.kt"
LABEL = AND + "core/LedgerSourceLabel.kt"
BUG_DOC = "docs/changes/BUG-0019.md"
GUARD = "_tools/ai/_check_ai_guardrails.py"
SIZE = "_tools/ai/_sysprompt_size.py"
TEST_RUN = "android/app/src/test/java/com/tapmoay/sorders/ai/AiWorkflowRunnerTest.kt"
DOC = "docs/changes/CHG-0096.md"
REG = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"
#: BUG-0022（「跑工作流」开关点开就弹回）：默认集、单测、文书、台账。
KEYSTORE = AND + "ai/AiKeyStore.kt"
TEST_ENABLED = "android/app/src/test/java/com/tapmoay/sorders/ai/AiEnabledToolsTest.kt"
TEST_ENDPOINT = "android/app/src/test/java/com/tapmoay/sorders/ai/AiEndpointRulesTest.kt"
DOC22 = "docs/changes/BUG-0022.md"
LEDGER = "docs/TEST_BUG_LEDGER.md"


def sub(old: str, new: str) -> Callable[[str], str]:
    """把出现的 old 换成 new（出现 0 次时由主流程报"锚点变了"）。"""

    def fn(text: str) -> str:
        return text.replace(old, new)

    return fn


def drop_line(needle: str) -> Callable[[str], str]:
    """删掉含 need 的那一行（连行尾换行一起删）。"""

    def fn(text: str) -> str:
        out = []
        for ln in text.split("\n"):
            if needle in ln:
                continue
            out.append(ln)
        return "\n".join(out)

    return fn


CASES: list[tuple[str, str, Callable[[str], str], str]] = [
    # ---- 登记表（第 1 节）----
    ("① 对账交棒的动作换成不存在的一条", WORKFLOW,
     sub("nextAction = AiWrites.LEDGER_SYNC_DELIVERED,", 'nextAction = "ledger.sync",'),
     "对账交棒给"),
    ("② 两步的 KDoc 删掉（那两行是「这一步在读什么」的唯一出处）", WORKFLOW,
     sub("    /** 这一步在读什么。**回话与痕迹里那一行就是它**，⛔ 不许在 runner 里另写一遍文案（会漂移）。 */\n", ""),
     "两步的形状"),
    ("③ 工具说明改成手写循环（不再从登记表拼）", WORKFLOW,
     sub("        ALL.forEach { w ->", "        listOf(RECONCILE).forEach { w ->"),
     "工具说明**从登记表拼**"),
    # FEAT-0020：forRole 换成 actor 感知的 forActor（第二维是"是不是批发商货主"），锚点跟着换。
    ("④ forActor 对认不出的角色改成「给派单员那批」（fail-open）", WORKFLOW,
     sub("val role = actor?.role ?: return emptyList()",
         "val role = actor?.role ?: AiRole.DISPATCHER"),
     "认不出角色 = 一条都不给"),
    ("⑤ 默认角色那一行改了（不给 roles 的也发给货主）", WORKFLOW,
     sub("val roles: Set<AiRole> = setOf(AiRole.DISPATCHER),",
         "val roles: Set<AiRole> = setOf(AiRole.SHIPPER),"),
     "默认只给派单员"),
    ("⑥ 步骤 action 抄进第 13 条规则块（提示词里又出现一份步骤）", WORKFLOW,
     sub("    appendLine()\n}\n", "    appendLine()\n}\n") if False else
     lambda s: s.replace("val RULES: String = buildString {", "val RULES: String = buildString {\n    appendLine(\"orders.list_orders\")", 1),
     "规则块里不许出现步骤 action"),
    # ---- 用户口径（第 3 节）----
    ("⑦ 用户口径那两行删掉（下一个人不知道为什么要有这一层）", WORKFLOW,
     sub("- 先做哪条：「**两条一起做**」—— 对账 + 批量调价同一单交。", "- 先做哪条：两条。"),
     "写了「两条一起做」"),
    ("⑧ goal 编号删掉（对不上路线图）", WORKFLOW,
     sub("（`goal-9c29e859-ec5e-444e-9e78-6e330bf0aa07`）", ""),
     "留了 goal 编号"),
    # ---- 执行器：窗口口径（第 4 节）----
    ("⑨ 订单那次读走 from/to（筛下单日 —— 两张表两种口径，差出来的是假账）", RUNNER,
     sub('put("delivered_from", from)', 'put("from", from)'),
     "送达日窗口走 extra"),
    ("⑩ 「来源 = order」那道过滤去掉（手工记的账被当成已经进账本）", RUNNER,
     sub(".filter { field(it, *SOURCE)?.lowercase() == SOURCE_ORDER }", ".filter { true }"),
     "来源 = order"),
    ("⑪ 没有归属的单不再单列（用户等永远不会回来的账）", RUNNER,
     sub("val unowned = withNo.filterNot { hasOwner(it) }", "val unowned = emptyList<JsonObject>()"),
     "没有归属的单单列"),
    ("⑫ 干净判据里去掉 unowned（有没归属的单也说「账全对」）", RUNNER,
     sub("val clean = missing.isEmpty() && unowned.isEmpty() && ledgerOnly.isEmpty() && noNo == 0",
         "val clean = missing.isEmpty() && ledgerOnly.isEmpty() && noNo == 0"),
     "一刀切的干净判据"),
    # ---- 执行器：没查全（第 5 节）----
    ("⑬ 没查全的定义删掉（默认当查全了）", RUNNER,
     sub("val incomplete = orders.truncated || ledger.truncated", "val incomplete = false"),
     "没查全 = 任一步被截断"),
    ("⑭ 没查全也照样给 missing_amount（半份数据当完整的账报）", RUNNER,
     sub('if (!incomplete) put("missing_amount"', 'put("missing_amount"'),
     "没查全时**不给** missing_amount"),
    ("⑮ 金额解析不了当 0（报出来的和账上对不上）", RUNNER,
     sub("runCatching { BigDecimal(raw) }.getOrNull()", "BigDecimal(raw)"),
     "金额解析不了不算 0"),
    ("⑯ 读接口出错不停下（拿半份数据下结论）", RUNNER,
     sub('orders.error?.let { return err(', 'orders.error?.let { println('),
     "读接口出错就停下"),
    # ---- 执行器：调价（第 6 节）----
    ("⑰ 调价不再要求「恰好一个」改法", RUNNER,
     sub("if ((adjust == null) == (price == null))", "if (adjust == null)"),
     "adjust 与 price 恰好给一个"),
    ("⑱ 执行器里开始自己算价（出现第二份涨降实现）", RUNNER,
     sub("    private fun nextJson(", "    private fun priceOf(v: String) = BigDecimal(v).multiply(BigDecimal(\"1.05\"))\n\n    private fun nextJson("),
     "不许出现算价的痕迹"),
    ("⑲ 执行器里碰写服务（写能力多出一条路）", RUNNER,
     sub("    private fun nextJson(", "    private val svc = AiWriteService()\n\n    private fun nextJson("),
     "不许碰写服务"),
    # ---- 交棒（第 7 节）----
    ("⑳ 交棒那段不再写「用户点头之后再调 preview_write」", RUNNER,
     sub('用户点头之后再调 preview_write', '到时候就知道了'),
     "交棒里写明「用户点头之后再调 preview_write」"),
    # ---- 工具注册（第 8 节）----
    ("㉑ 工具没进 ALL（模型根本不知道有这条工作流：静默失效）", TOOLS,
     drop_line("            RUN_WORKFLOW,"),
     "ALL 里有它"),
    ("㉒ 设置页那一行被删（用户在设置里看不到它）", TOOLS,
     drop_line('RUN_WORKFLOW to "跑工作流",'),
     "设置页标题"),
    # FEAT-0020：schema 从静态表挪进了动态 spec（enum 按角色裁），锚点跟着换。
    ("㉓ 工具 schema 不再按角色裁（货主会看到派单员那两条）", TOOLS,
     sub("AiWorkflows.forActor(actor)", "AiWorkflows.ALL"),
     "enum/说明只列这个角色能跑的"),
    ("㉔ 护栏白名单里漏掉 run_workflow", GUARD,
     sub('"run_workflow"', '"run_workflow_gone"'),
     "护栏白名单里有 run_workflow"),
    # ---- 提示词（第 9 节）----
    ("㉕ 第 13 条没拼进 systemPrompt（规则写了但没人读）", LOOP,
     drop_line("        append(AiWorkflows.RULES)"),
     "拼进 systemPrompt"),
    ("㉖ 第 13 条挪到 12 之前（顺序反了，与登记表里的编号对不上）", LOOP,
     lambda s: s.replace("        append(AiAnswerSkills.RULES)\n", "", 1).replace(
         "        append(AiAnswerStyle.RULES)\n", "        append(AiWorkflows.RULES)\n        append(AiAnswerStyle.RULES)\n", 1),
     "顺序：Style(10)"),
    ("㉗ 提示词体积预算里漏掉这一块（体积悄悄涨）", SIZE,
     drop_line("AiWorkflow.kt"),
     "提示词体积预算里算上了这一块"),
    # ---- 跨文件（第 10 节）----
    ("㉘ 步骤用的 action 在读目录里不存在（模型会照着一个查不到的名字去查）", CATALOG,
     sub('ReadAction("orders.list_orders"', 'ReadAction("orders.list_order"'),
     "读目录里有 orders.list_orders"),
    # ---- 单测（第 11 节）----
    ("㉙ 执行器单测里「没查全就不给数字」那一档被改名改没了", TEST_RUN,
     sub("没查全就不给数字结论", "查全了就给数字结论"),
     "执行器单测有这一档：没查全就不给数字结论"),
    ("㉚ 单测里「手工记账不算已进账本」的逐字断言改了", TEST_RUN,
     sub('"manual"', '"auto"'),
     '逐字断言 "manual"'),
    # ---- 判据自己（第 12 节）----
    ("㉛ 判据指向的工作流文件改了名", CHECK,
     sub('WORKFLOW = AI / "AiWorkflow.kt"', 'WORKFLOW = AI / "AiWorkflowGone.kt"'),
     "找不到文件"),
    ("㉜ 反验脚本自己失踪", CHECK,
     sub('REVERSE = ROOT / "_tools/qa/_reverse_verify_ai_workflow.py"',
         'REVERSE = ROOT / "_tools/qa/_reverse_verify_ai_workflow_gone.py"'),
     "反验脚本在"),
    ("㉝ 变更单缺一节（九节不全）", DOC,
     sub("## ⑨ 关闭（六格）", "## ⑨ 关闭"),
     "九节齐全"),
    ("㉞ 登记簿那一行被改成别的单号", REG,
     lambda s: s.replace("CHG-0096", "CHG-0097"),
     "登记簿有 CHG-0096 这一行"),
    ("㉟ 工作声明那一条被改成别的单号", CLAIM,
     lambda s: s.replace("CHG-0096", "CHG-0097"),
     "工作声明里记了这条活"),
    # ---- 账本那一侧的明细（第 12 节 · TB-04 / BUG-0019）----
    ("㊱ 明细不再按来源分组（又回到让模型自己按单拼）", RUNNER,
     sub('val bySource = ledger.rows.groupBy { field(it, *SOURCE)?.lowercase() ?: "" }',
         'val bySource = ledger.rows.groupBy { "" }'),
     "明细按「来源」分组算"),
    ("㊲ 来源的中文名在执行器里另抄一份（第二份表）", RUNNER,
     sub('put("来源说明", ledgerSourceLabel(src))',
         'put("来源说明", if (src == "return") "退货红冲" else src)'),
     "来源的中文名走全 App 唯一那一份表"),
    ("㊳ 退货红冲不再单拎出来（returns 永远是空的）", RUNNER,
     sub("val returns = bySource[SOURCE_RETURN].orEmpty()", "val returns = emptyList<JsonObject>()"),
     "退货红冲那一档单独拎出来"),
    ("㊴ 整单退货改成猜的（不再看本次已送达清单）", RUNNER,
     sub("return no !in seen", "return true"),
     "判据是「这张单在不在本次已送达清单里」"),
    ("㊵ 口径那句话被掏空（回收站那一层没了）", RUNNER,
     sub('const val SCOPE_NOTE = "账本这一侧的口径：只算**没进回收站**的单的账。进了回收站（已删除）的单，"',
         'const val SCOPE_NOTE = "账本口径。"'),
     "口径把「没进回收站」讲清楚"),
    ("㊶ 口径里「那不是漏账」那句删掉（下一个人会去查漏账）", RUNNER,
     sub('"拿库里的原始数据核对时笔数会对不上，那不是漏账，是这一条口径。"',
         '"拿库里的原始数据核对时笔数会对不上。"'),
     "口径点明「那不是漏账」"),
    ("㊷ 没查全也照样把账本明细说出去", RUNNER,
     sub("val conclusion = if (incomplete) baseConclusion else baseConclusion + returnsCn + SCOPE_NOTE",
         "val conclusion = baseConclusion + returnsCn + SCOPE_NOTE"),
     "结论只在**查全**时才接账本那两句"),
    ("㊸ 结果里不再交 ledger_detail（模型手里没有明细）", RUNNER,
     sub('putJsonArray("ledger_detail") { sourceDetail.forEach { add(it) } }',
         'putJsonArray("ledger_rows") { sourceDetail.forEach { add(it) } }'),
     '结果里交了 putJsonArray("ledger_detail")'),
    ("㊹ 口径那句话不再交给模型", RUNNER,
     sub('put("scope_note", SCOPE_NOTE)', 'put("scope_note", "")'),
     '结果里交了 put("scope_note", SCOPE_NOTE)'),
    ("㊺ 提示词里「不许自己按单去拼明细」那条纪律删掉", WORKFLOW,
     drop_line("不许自己按单去拼明细"),
     "明细纪律进提示词（⛔ 不许自己按单去拼明细）"),
    ("㊻ 来源表里删掉 return 那一档（界面上露出英文 return）", LABEL,
     sub('"return" -> "退货红冲"', '"ret" -> "退货红冲"'),
     "来源中文表认得出「退货红冲」"),
    ("㊼ BUG-0019.md 缺一节（九节不全）", BUG_DOC,
     sub("## ⑨ 关闭（六格）", "## ⑨ 关闭"),
     "BUG-0019.md 九节齐全"),
    ("㊽ 登记簿里 BUG-0019 那一行被改成别的单号", REG,
     lambda s: s.replace("BUG-0019", "BUG-0099"),
     "登记簿有 BUG-0019 这一行"),
    ("㊾ 工作声明里那条被改成别的单号", CLAIM,
     lambda s: s.replace("BUG-0019", "BUG-0099"),
     "工作声明里记了这条活"),
    # ---- BUG-0022（第 14 节）：开关真的能打开 ----
    ("㊿ 默认工具集里把 run_workflow 那一行删掉（开关点开就弹回）", KEYSTORE,
     drop_line("AiTools.RUN_WORKFLOW,"),
     "只读工具 run_workflow 在默认集里"),
    ("51 末尾那句 intersect 换成别的集合（筛子没了 —— 这条反着证明它才是筛子）", KEYSTORE,
     sub("intersect(DEFAULT_ENABLED_TOOLS)", "intersect(emptySet())"),
     "末尾那句 intersect 还在"),
    ("52 源码里那条 BUG-0022 的来历注释删掉（下一个人又要重新踩）", KEYSTORE,
     drop_line("BUG-0022"),
     "源码里点明了这一条为什么危险（BUG-0022）"),
    ("53 单测里「存进 prefs 的 run_workflow 不许被筛掉」那一档改名", TEST_ENABLED,
     sub("用户自己点开的 run_workflow 不许被筛掉（存进 prefs 也不生效就是这个 bug）", "run_workflow 开关要能开"),
     "单测钉住「存进 prefs 的 run_workflow 不许被筛掉」"),
    ("54 另一档「默认集里必须有它」改名", TEST_ENDPOINT,
     sub("只读工具 run_workflow 必须在默认集里（BUG-0022）", "默认集要够全"),
     "单测钉住「默认集里必须有它」"),
    ("55 BUG-0022.md 缺一节（九节不全）", DOC22,
     sub("## ⑨ 关闭（六格）", "## ⑨ 关闭"),
     "BUG-0022.md 九节齐全"),
    ("56 文书里那份真机 prefs 证据删掉", DOC22,
     drop_line("enabled_tools"),
     "BUG-0022 点明了真机取证那一份 prefs"),
    ("57 登记簿里 BUG-0022 那一行被改成别的单号", REG,
     lambda s: s.replace("BUG-0022", "BUG-0099"),
     "登记簿有 BUG-0022 这一行"),
    ("58 工作声明里那条被改成别的单号", CLAIM,
     lambda s: s.replace("BUG-0022", "BUG-0099"),
     "工作声明里记了这条活"),
    ("59 台账里那条被改成别的说法", LEDGER,
     sub("跑工作流", "批量调价"),
     "台账里有这一条"),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("⛔ 源码一处没改，判据就是红的 —— 先把它修绿再来做反验：")
        print(out[-4000:])
        return 1
    print("✅ 前置：源码完好时判据是绿的（" + str(len(out.splitlines())) + " 行输出）")

    files = sorted({str(c[1]) for c in CASES})
    before = {rel: (ROOT / rel).read_bytes() for rel in files}
    print("📸 快照 " + str(len(files)) + " 个文件（按字节）")

    bad: list[str] = []
    for i, (label, rel, fn, expect) in enumerate(CASES, 1):
        path = ROOT / rel
        raw = path.read_bytes()
        crlf = b"\r\n" in raw
        text = raw.decode("utf-8").replace("\r\n", "\n")
        new = fn(text)
        if new == text:
            bad.append(label + "（注入没生效：锚点变了，请更新本脚本）")
            print("  [" + str(i) + "] ⛔ " + label + " —— 注入没生效（锚点变了，请更新本脚本）")
            continue
        try:
            path.write_bytes((new.replace("\n", "\r\n") if crlf else new).encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(raw)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print("  [" + str(i) + "] ✅ " + label + " → 判据报红（含「" + expect + "」）")
        else:
            bad.append(label)
            print("  [" + str(i) + "] ❌ " + label + " → 判据没抓到（退出码 " + str(code) + "）"
                  + ("；输出里也没有「" + expect + "」" if expect else ""))
            tail = [ln for ln in out.splitlines() if "[FAIL]" in ln][:3]
            for t in tail:
                print("        " + t.strip())

    dirty = []
    for rel, blob in before.items():
        if (ROOT / rel).read_bytes() != blob:
            dirty.append(rel)
            (ROOT / rel).write_bytes(blob)
    if dirty:
        print("⛔ 还原不干净（已强制写回）：" + " / ".join(dirty))
        bad.append("还原不干净")

    print("")
    if bad:
        print("❌ " + str(len(bad)) + " 条没证明：" + " \u00b7 ".join(bad))
        return 1
    print("✅ " + str(len(CASES)) + " 条注入都证明这条红线真的在检查。")
    print("✅ 还原检查：" + str(len(files)) + " 个被碰过的文件与运行前逐字节一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
