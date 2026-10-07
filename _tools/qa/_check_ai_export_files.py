# -*- coding: utf-8 -*-
"""AI 要的表格，AI 自己递到聊天里：能下载、能分享（2026-10-07，台账 L-43 / CHG-0078）。

## 用户原话（m01794）
> 「还有一个就是我让 AI 去把这个月的货主的账导成表格，这个 AI 啊，他直接让我去报表中心查看或下载啊。
>   这肯定不行啊。他首先第一点，他要自己做表格先给我看，然后……他会输出一个下载按钮，
>   直接点击下载按钮，直接给下载了。这个功能是要具备的，在聊天框中。不然还要自己跑过去看，那要 AI 干嘛。」

## 病长在哪（三处，缺一处用户看到的病就回来一部分）
1. **指路**：export_sheet 从前自己打一次后端、立刻 body.close()，回一句
   「已生成，请到「报表中心」查看/下载」—— 用户被支使去别处找一个**还没生成**的产物。
2. **产物递不到聊天里**：手机端连 ledger/export-jobs 那三个端点都没有封装（本单才加上），
   报表那条也只是把字节流关掉。口径（m01850）定的是「**点按钮当场重新生成**」。
3. **分享**：ExportUtil 从前把 content:// 那个 Uri **扔掉**、并且存进了应用私有目录
   （不是系统「下载」目录），微信/QQ 两方面都拿不到文件。

## 为什么必须是机器判据
这三条坏起来**都不报错**：
- 指路的话术照旧 200，接口照旧有响应；
- 把 recipe 手拼成 snake_case 键（date_from）而字段名是 camelCase，解析侧开着
  ignoreUnknownKeys ⇒ 每个字段**静默回落成默认值**，症状只是「文件行点了没反应」；
- 把 export_ledger 漏出 DEFAULT_ENABLED_TOOLS ⇒ 末尾的 intersect 把新工具**静默筛掉**，
  升级上来的用户什么都点不到（本单真踩过这两条）。
所以判据钉的是**接线**（少一根就红），而不只是「文件能生成」。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。「文件行画在谁的下面、点了之后谁去取件」
是纯客户端编排：后端只知道有人 POST 了一个导出任务（它甚至分不清是谁点的），reports/export
更是无状态现算。模型侧同样拦不住 —— 模型只产出一段 JSON，「这段 JSON 变成一颗按钮」
这一步只存在于界面里。判据同时守三件跨文件的口径：**生成发生在用户点按钮之后**（配额是用户的）、
**配方只有一处键名定义**、**两个入口同一段分享实现**；任意少一件，用户看到的病就回来一部分。

用法：
    python _tools/qa/_check_ai_export_files.py
    python _tools/qa/_check_ai_export_files.py --list
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402
from _check_product_card_single_source import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
BACKEND = ROOT / "backend"
TESTDIR = ROOT / "android/app/src/test/java/com/tapmoay/sorders"

AI = AND / "ai"
TOOLS = AI / "AiTools.kt"
LOOP = AI / "AiAgentLoop.kt"
CONV = AI / "AiConversation.kt"
KEYSTORE = AI / "AiKeyStore.kt"
SERVICE = AI / "AiExportService.kt"
CONTAINER = AI / "AiContainer.kt"
CHAT = AND / "ui/ai/AiChatScreen.kt"
CHATVM = AND / "ui/ai/AiChatViewModel.kt"
EXPORTUTIL = AND / "util/ExportUtil.kt"
REPORTCENTER = AND / "ui/dispatcher/ReportCenter.kt"
APIS = AND / "data/remote/api/Apis.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"
REPO = AND / "data/repo/AppRepository.kt"

LEDGER_API = BACKEND / "app/api/v1/ledger.py"
RPT_COMMON = BACKEND / "app/services/reports/_common.py"
RPT_API = BACKEND / "app/api/v1/reports.py"
ENABLED_TEST = TESTDIR / "ai/AiEnabledToolsTest.kt"

REVERSE = "_tools/qa/_reverse_verify_ai_export_files.py"

#: 扫到的界面文件数下限（防目录改名/搬走之后「一个文件都没扫到」也算过）—— 实际 305
MIN_KT_FILES = 250

#: 抽出来的函数体字符数下限（**抽取失效比判据腐烂更危险** —— 那会变成一条永远绿的检查）
BODY_FLOOR = 300

# ---- 关键锚点（**只写一处**：判据与报红详情共用同一个字面量，改的时候不会只改一边）----
A_CONST = 'const val EXPORT_LEDGER = "export_ledger"'
A_DISPATCH = "EXPORT_LEDGER -> exportLedger(args)"
A_TITLE = 'EXPORT_LEDGER to "导出账本"'
A_HINT = 'EXPORT_LEDGER to "按货主与起止日期导出一本账（Excel），文件直接出现在聊天里",'
A_SHIPPER_ROLE = "AiRole.SHIPPER to setOf(READ_DATA, REMEMBER, PREVIEW_WRITE),"
A_SHEET_SIG = "private fun exportSheet(args: JsonObject): String"
A_LEDGER_SIG = "fun exportLedger(args: JsonObject)"
A_SHEET_BODY = "private fun exportSheet("
A_ACCOUNTS = "repo.ledgerAccounts("
A_RECIPE_PUT = 'put("recipe", recipeJson(recipe))'
A_BAD_PUT = 'putJsonObject("recipe")'
A_SERIALIZER = "encodeToJsonElement(StoredExportRecipe.serializer()"
A_MSG_FIELD = "val exportRecipe: StoredExportRecipe? = null,"
A_SPLIT_CALL = "val (forModel, recipeJson) = AiTools.splitRecipe(output)"
A_FOR_MODEL = "ChatMessage.tool(call.id, forModel)"
A_RAW_MODEL = "ChatMessage.tool(call.id, output)"
A_OFFERED = "AiEvent.FileOffered(fnName, recipeJson)"
A_FILE_ROW = "private fun ExportFileRow("
A_DOWNLOAD = "fun downloadExport(index: Int)"
A_BUSY = "if (msg.exportState.busy) return"
A_DELIVER = "ai.exports.deliver("
A_SHARE_IMPL = "shareExportFile("
A_SAVE_URI = "saveExportFileWithUri("
A_POLL_JOB = "val jobId = recipe.jobId.takeIf { it > 0 } ?: run {"
A_CODE_CHECK = "put("


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def subs(text: str, needle: str) -> int:
    """子串出现次数。

    ⚠️ 这里**故意用纯字符串**而不是正则：这些锚点里全是 ( ) . * 「」 这类正则元字符
    （如 put("recipe", recipeJson(recipe)) ），当正则用会直接报 unterminated subpattern ——
    或者更糟：静默匹配到别的东西，判据就成了假的。
    """
    return text.count(needle)


def after(text: str, needle: str, span: int) -> str:
    i = text.find(needle)
    return text[i : i + span] if i >= 0 else ""


def between(text: str, start: str, end: str) -> str:
    """start 与 end 之间那一段（取不到返回空串，交给判据报红）。"""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:j] if j > 0 else ""


def fn_body(src: str, sig: str) -> str:
    """sig（如 private fun exportSheet( ）那个函数的**函数体**（按大括号配对，不是按行猜）。"""
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


def hits(needle: str) -> dict:
    """全树 .kt **代码**里含 needle 的文件 → 出现次数（注释先剥掉）。"""
    out = {}
    for p in AND.rglob("*.kt"):
        n = code(p).count(needle)
        if n:
            out[p.name] = n
    return dict(sorted(out.items()))


class Checker:
    def __init__(self) -> None:
        self.fails = []
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
    if refuse_if_injecting("AI 出表格与聊天内下载/分享检查"):
        return 1

    c = Checker()
    print("AI 把表格递进聊天、点了能下载能分享：2026-10-07（台账 L-43 / CHG-0078）")

    kt = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_KT_FILES}（防目录搬走 → 判据空转）",
        len(kt) >= MIN_KT_FILES,
        f"实际 {len(kt)}",
    )

    # ---- 1. 该在的文件都在 ----
    for p, why in (
        (TOOLS, "两个导出工具 + 配方编码"),
        (LOOP, "把配方摘下来、换成文件行事件"),
        (CONV, "配方存在聊天记录里"),
        (KEYSTORE, "默认开启的工具集（漏了就静默筛掉）"),
        (SERVICE, "交付层（唯一会花掉用户配额的地方）"),
        (CONTAINER, "交付层挂上容器"),
        (CHAT, "聊天里的文件行"),
        (CHATVM, "点「下载」的入口"),
        (EXPORTUTIL, "存盘 + 分享"),
        (REPORTCENTER, "报表中心那颗「分享」"),
        (APIS, "账本导出的三个端点"),
        (DTOS, "账本导出的出入参"),
        (REPO, "仓储封装"),
        (LEDGER_API, "后端三道闸"),
        (RPT_COMMON, "后端区间算法（客户端要跟它同一条）"),
        (RPT_API, "报表导出端点"),
        (ENABLED_TEST, "默认工具集的单测"),
    ):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 存在（{why}）", p.exists(), "文件被搬走/改名了")

    tools_src = code(TOOLS)

    # ---- 2. 工具层接线：少一根用户就点不到（本单真踩过「静默筛掉」）----
    print()
    print("  -- 工具层接线 --")
    n = subs(tools_src, A_CONST)
    c.ok("工具名常量只有一处：EXPORT_LEDGER = export_ledger", n == 1, f"找到 {n} 处")
    c.ok("模型真能调到它：分发处 EXPORT_LEDGER -> exportLedger(args)", subs(tools_src, A_DISPATCH) == 1)
    all_block = between(tools_src, "val ALL = listOf(", ")")
    c.ok("ALL 里有 export_ledger（设置页开关与白名单的总入口）", "EXPORT_LEDGER," in all_block, "不在 ALL 里 = 哪个角色都拿不到")
    tail_after_sheet = all_block.split("EXPORT_SHEET,")[-1] if "EXPORT_SHEET," in all_block else ""
    c.ok(
        "它紧跟在 export_sheet 后面（顺序＝设置页显示顺序，两个导出挨着）",
        tail_after_sheet.lstrip().startswith("EXPORT_LEDGER,"),
        tail_after_sheet.strip()[:60],
    )
    groups = between(tools_src, "private val GROUPS", ")")
    c.ok("分组表里明写了它是「查询」档（不加只是靠兜底，不是声明）", "EXPORT_LEDGER to Group.QUERY" in groups)
    c.ok("派单员仍是「全部」（ALL.toSet()）", "AiRole.DISPATCHER to ALL.toSet()," in tools_src)
    n = subs(tools_src, A_SHIPPER_ROLE)
    c.ok("货主的白名单逐字不变（两个导出工具都不给他，L-43 口径）", n == 1, f"找到 {n} 处")
    shipper_zone = after(tools_src, "AiRole.SHIPPER to setOf(", 80)
    c.ok(
        "货主那一行里没有偷偷塞进 export_sheet / export_ledger",
        "EXPORT_SHEET" not in shipper_zone and "EXPORT_LEDGER" not in shipper_zone,
        "货主拿到导出工具＝他能导别人的账",
    )
    c.ok("认不出角色 = 一个都不给（fail-closed 还在）", "val allowed = ROLE_TOOLS[role] ?: return emptyList()" in tools_src)
    c.ok("设置页标题：EXPORT_LEDGER to 导出账本", A_TITLE in tools_src)
    c.ok("设置页说明写清了它干什么（文件直接出现在聊天里）", A_HINT in tools_src)

    ks = code(KEYSTORE)
    n = subs(ks, "AiTools.EXPORT_LEDGER,")
    c.ok("默认开启的工具集里有它（⛔ 漏了会被末尾的 intersect 静默筛掉）", n == 1, f"找到 {n} 处")
    c.ok("默认集里 export_sheet 也在（两个导出要么都开、要么都别开）", subs(ks, "AiTools.EXPORT_SHEET,") == 1)

    schema = fn_body(tools_src, "EXPORT_LEDGER to buildJsonObject {")
    c.ok("schema 抽出来了", len(schema) >= 200, f"实际 {len(schema)} 字符")
    c.ok(
        "schema 三个参数都在（shipper / date_from / date_to）",
        all(x in schema for x in ('putJsonObject("shipper")', 'putJsonObject("date_from")', 'putJsonObject("date_to")')),
    )
    for k in ("shipper", "date_from", "date_to"):
        c.ok(f"schema 把 {k} 标成必填", f'add(JsonPrimitive("{k}"))' in schema)
    c.ok("schema 明说 shipper 填姓名、不要编号（姓名是用户说的，编号是库里的）", "不要填编号" in schema)
    c.ok("工具说明里说清了它只回配方（真正的生成发生在他点下载按钮之后）", "真正的生成发生在他点下载按钮之后" in tools_src)
    c.ok("export_sheet 的说明里是明文禁令：不要让他去报表中心（不靠模型自觉）", "不要**告诉用户「去报表中心查看/下载」" in tools_src)
    c.ok("系统提示词结尾也钉着同一句（两条路都堵上）", "绝对不要**让他「去报表中心查看/下载」" in code(LOOP))

    # ---- 3. 工具回合**不**生成文件：配额是用户的，不是模型的 ----
    print()
    print("  -- 工具回合不生成文件 --")
    c.ok("export_sheet 不是 suspend（它一个网络都不发）", subs(tools_src, A_SHEET_SIG) == 1)
    sheet = fn_body(tools_src, A_SHEET_BODY)
    c.ok(f"exportSheet 函数体抽出来了（≥{BODY_FLOOR} 字符，防抽取失效）", len(sheet) >= BODY_FLOOR, f"实际 {len(sheet)}")
    c.ok("export_sheet 体内一次后端都不碰（没有 repo. 调用）", subs(sheet, "repo.") == 0)
    c.ok("export_sheet 体内也不再关响应流（旧版 body.close() ＝ 不下载，那就是病根）", "body.close()" not in sheet)
    c.ok("export_sheet 回了配方（不是只回一句话）", A_RECIPE_PUT in sheet)
    n = subs(tools_src, "private suspend fun exportLedger(args: JsonObject): String {")
    c.ok("export_ledger 是 suspend（它要发一次只读请求去认人）", n == 1, f"找到 {n} 处")
    led = fn_body(tools_src, A_LEDGER_SIG)
    c.ok(f"exportLedger 函数体抽出来了（≥{BODY_FLOOR} 字符）", len(led) >= BODY_FLOOR, f"实际 {len(led)}")
    n = subs(led, A_ACCOUNTS)
    c.ok("export_ledger 只发一次只读请求（GET /ledger/accounts 认人）", n == 1, f"找到 {n} 处")
    c.ok("export_ledger 体内没有「建任务」这一步", "createLedgerExportJob" not in led)
    c.ok("export_ledger 也回了配方", A_RECIPE_PUT in led)
    c.ok("临时货主如实拒绝（账本里没有他的正式账号）",
         "是临时货主，账本里没有他的正式账号，导不了。" in led)
    c.ok("同名多个回 candidates 让模型反问（不许自己猜一个）",
         'putJsonArray("candidates")' in led)
    h = hits("createLedgerExportJob")
    c.ok("全树只有两处能建导出任务（仓储 ＋ 交付层），工具层一处都没有", h == {"AiExportService.kt": 1, "AppRepository.kt": 1}, f"实际 {h}")
    h = hits("ledgerExportJob")
    c.ok("全树只有两处能查任务状态（仓储 ＋ 交付层）", h == {"AiExportService.kt": 1, "AppRepository.kt": 1}, f"实际 {h}")

    # ---- 4. 配方：键名只有一处定义，而且到不了模型眼前 ----
    print()
    print("  -- 配方（按钮带的是配方，不是产物）--")
    n = subs(tools_src, A_SERIALIZER)
    c.ok("配方只有一个编码出口（走数据类自己的序列化器，不手拼键名）", n == 1, f"找到 {n} 处")
    n = subs(tools_src, A_RECIPE_PUT)
    c.ok("两个工具都从那个出口走（⛔ 手拼一次就是静默丢字段）", n == 2, f"找到 {n} 处")
    h = hits(A_BAD_PUT)
    c.ok("⛔ 全树没有一处手拼 recipe 的 JSON 键（对不上字段名会静默回落成默认值）", h == {}, f"实际 {h}")
    c.ok(
        "报表那支把来源、页签、区间、文件名都装进配方",
        "source = StoredExportRecipe.SOURCE_REPORT," in tools_src
        and "dateFrom = spanFrom.toString()," in tools_src
        and "dateTo = spanTo.toString()," in tools_src,
    )
    c.ok(
        "账本那支把货主与起止日装进配方",
        "source = StoredExportRecipe.SOURCE_LEDGER," in tools_src
        and "shipperId = id," in tools_src
        and "shipperName = target.name," in tools_src,
    )

    conv = code(CONV)
    n = subs(conv, A_MSG_FIELD)
    c.ok("配方跟着聊天记录一起存（StoredMessage.exportRecipe）", n == 1, f"找到 {n} 处")
    for field in (
        "val source: String = SOURCE_REPORT,",
        'val kind: String = "",',
        'val mode: String = "",',
        'val date: String = "",',
        'val dateFrom: String = "",',
        'val dateTo: String = "",',
        "val shipperId: Long = 0L,",
        'val shipperName: String = "",',
        'val fileName: String = "",',
        "val jobId: Long = 0L,",
    ):
        c.ok(f"配方字段带默认值、老记录照样能读：{field}", field in conv)
    c.ok(
        "两个来源各有一个常量（报表现算 / 账本异步）",
        'const val SOURCE_REPORT = "report"' in conv and 'const val SOURCE_LEDGER = "ledger"' in conv,
    )
    c.ok(
        "解析失败当「没有配方」（不让半条配方变成一颗坏按钮）",
        "fun parse(raw: String): StoredExportRecipe? = try {" in conv and "json.decodeFromString(serializer(), raw)" in conv,
    )

    loop = code(LOOP)
    c.ok("工具回合把整段配方摘出来（模型看到的是摘掉之后那份）", subs(loop, A_SPLIT_CALL) == 1)
    c.ok("文件行事件带上配方（界面靠它画那颗按钮）", A_OFFERED in loop)
    c.ok("喂给模型的是摘掉之后那份（⛔ 不是原样那条）", A_FOR_MODEL in loop)
    c.ok("⚠ 上面那条是「货主编号不进提示词」的全部保障", A_RAW_MODEL not in loop)
    c.ok("splitRecipe 只此一份实现", subs(tools_src, "fun splitRecipe(") == 1)
    c.ok("摘的是 recipe 这一个键，其余字段原样保留", 'obj["recipe"] as? JsonObject ?: return output to null' in tools_src)

    # ---- 5. 文件名与区间：客户端算的必须跟后端同一条 ----
    print()
    print("  -- 文件名与统计区间 --")
    titles = between(tools_src, "val EXPORT_TITLES", ")")
    c.ok("六个页签的中文名只有一处定义（导出文件名要用它）", len(titles) >= 100, f"实际 {len(titles)} 字符")
    for k, cn in (
        ("turnover", "营业纵览"),
        ("products", "商品经营"),
        ("drivers", "司机绩效"),
        ("customers", "客户经营"),
        ("finance", "资金收支"),
        ("audit", "异常与审计"),
    ):
        c.ok(f"页签名 {k} ＝「{cn}」", f'"{k}" to "{cn}"' in titles)
    rc = code(REPORTCENTER)
    for cn in ("营业纵览", "商品经营", "司机绩效", "客户经营", "资金收支", "异常与审计"):
        c.ok(f"报表中心那一页也叫「{cn}」（同一份中文名，不许各叫各的）", f'-> "{cn}"' in rc)
    c.ok("报表现算的文件名 = 中文页签名-起_止.xlsx", 'exportTitle(kind) + "-" + label + ".xlsx"' in tools_src)
    c.ok("账本的文件名 = 账本-货主姓名-起_止.xlsx", '"账本-" + target.name + "-" + label + ".xlsx"' in tools_src)
    c.ok(
        "同一天不带重复日期（spanLabel 那条规则）",
        'if (from == to) from.toString() else "' in tools_src and '_$to"' in tools_src,
    )
    span = fn_body(tools_src, "fun reportSpan(")
    c.ok("reportSpan 函数体抽出来了（≥200 字符）", len(span) >= 200, f"实际 {len(span)}")
    c.ok("只给一头就报错（不许猜一段区间 —— 猜错就是算错账）", "date_from 与 date_to 要一起给" in span)
    c.ok("起晚于止直接报错", "开始日期不能晚于结束日期" in span)
    c.ok(
        "week = 周一~周日",
        "val start = anchor.minusDays((anchor.dayOfWeek.value - 1).toLong())" in span and "start to start.plusDays(6)" in span,
    )
    c.ok(
        "month = 1 号~月末",
        "val first = anchor.withDayOfMonth(1)" in span and "first to first.plusDays(32).withDayOfMonth(1).minusDays(1)" in span,
    )
    common = read(RPT_COMMON)  # ⚠️ .py 不能过 strip_comments（那是给 Kotlin 写的，会把 Python 削掉大半）
    c.ok(
        "后端 week 也是周一~周日（两条算法必须是同一条）",
        "start = d - timedelta(days=d.weekday())" in common and "return start, start + timedelta(days=6)" in common,
    )
    c.ok(
        "后端 month 也是 1 号~月末",
        "first = d.replace(day=1)" in common and "(first + timedelta(days=32)).replace(day=1) - timedelta(days=1)" in common,
    )
    c.ok("后端也拒「只给一头」（400）", "date_from 与 date_to 必须同时给" in common)
    c.ok("报表导出真的走后端那条区间算法（s, e = _span(...)）", "s, e = _span(mode, d, date_from, date_to)" in read(RPT_API))

    # ---- 6. 交付层：全 App 唯一会花掉用户配额的地方 ----
    print()
    print("  -- 交付层（点按钮之后才动）--")
    svc = code(SERVICE)
    c.ok("按配方来源分两支（报表现算 / 账本异步）", "if (recipe.source == StoredExportRecipe.SOURCE_LEDGER)" in svc)
    c.ok("报表就一次 GET 现算，不再先落临时文件", "repo.exportReport(" in svc and ".use { it.bytes() }" in svc)
    n = subs(svc, "repo.createLedgerExportJob(")
    c.ok("账本第一下就是建任务 —— 这里是全 App 唯一会花掉用户当天配额的地方", n == 1, f"找到 {n} 处")
    c.ok("已经建过的任务不重复建（配方里存了 jobId 就复用）", A_POLL_JOB in svc)
    c.ok("任务号立刻写回配方（退出去再进来不会白花一次配额）", "onJobId(job.id)" in svc)
    c.ok(
        "每 2 秒问一次、最多 60 次（两分钟）",
        "POLL_INTERVAL_MS = 2_000L" in svc and "POLL_TIMES = 60" in svc and "delay(POLL_INTERVAL_MS)" in svc,
    )
    c.ok("好了就下载（DONE → download）", "LedgerExportJobDto.DONE" in svc and "repo.downloadLedgerExportJob(jobId).use { it.bytes() }" in svc)
    c.ok("失败时把后端那句话原样给用户（不吞掉原因）", "LedgerExportJobDto.FAILED" in svc and "errorMessage" in svc)
    c.ok("超时话术说清「任务还在，不用重新排队」", "两分钟还没生成好，稍后再点一次（任务还在，不用重新排队）。" in svc)
    c.ok("存盘走带 Uri 的那一个（分享要靠它）", "saveExportFileWithUri(context, bytes, recipe.fileName)" in svc)
    c.ok("进度如实上报（生成要几十秒，不能让界面干等）", '"正在生成…（已等 "' in svc and '"正在下载…"' in svc)
    c.ok("交付层挂在容器上（聊天 VM 用 ai.exports）", "val exports: AiExportService by lazy" in code(CONTAINER))

    # ---- 7. 界面：下载与分享 ----
    print()
    print("  -- 界面（文件行、下载、分享）--")
    vm = code(CHATVM)
    c.ok(
        "文件行的状态挂在消息上（配方 ＋ 生成/存下状态）",
        A_MSG_FIELD in vm and "val file: ExportedFile? = null" in vm,
    )
    c.ok("AI 事件到达时把配方放进消息", "is AiEvent.FileOffered ->" in vm and "StoredExportRecipe.parse(ev.recipeJson)" in vm)
    n = subs(vm, A_DOWNLOAD)
    c.ok("点「下载」的入口唯一", n == 1, f"找到 {n} 处")
    body = fn_body(vm, "fun downloadExport(")
    c.ok(f"downloadExport 函数体抽出来了（≥{BODY_FLOOR} 字符）", len(body) >= BODY_FLOOR, f"实际 {len(body)}")
    c.ok("生成中再点不算（busy 守卫）", A_BUSY in body)
    c.ok("真的去取件（ai.exports.deliver）", A_DELIVER in body)
    c.ok("任务号写回配方并落盘（下次点不再排队）", "it.exportRecipe?.copy(jobId = id)" in body and "persist()" in body)
    c.ok("离开页面（取消）不算失败", "catch (e: CancellationException)" in body)
    c.ok(
        "失败时如实说、并且能再点一次",
        "api.message?.takeIf { it.isNotBlank() }" in body and "这次没成功，再点一次试试。" in body,
    )
    c.ok(
        "产物被后端清理（404）时清掉作废的任务号 ⇒ 那颗按钮再点一次会重新生成",
        "if (api.code == 404) {" in body
        and "it.exportRecipe?.copy(jobId = 0)" in body
        and "，再点一次会重新生成。" in body,
    )

    chat = code(CHAT)
    c.ok("文件行只在有配方的消息下面画", subs(chat, "val recipe = m.exportRecipe") == 1)
    n = subs(chat, A_FILE_ROW)
    c.ok("文件行只有一个实现（两个入口不许各画一份）", n == 1, f"找到 {n} 处")
    row = fn_body(chat, A_FILE_ROW)
    c.ok(f"文件行函数体抽出来了（≥{BODY_FLOOR} 字符）", len(row) >= BODY_FLOOR, f"实际 {len(row)}")
    c.ok("生成中：转圈（不是再给一颗能点的按钮）", "state.busy ->" in row)
    c.ok("存下之后按钮变成「分享」", 'Text("分享"' in row and "shareExportFile(context, saved)" in row)
    c.ok("存下但这台手机分享不了时什么都不显示（不骗他有分享）", "saved != null -> Unit" in row)
    c.ok("没存下时是「下载」；失败过就写「再试一次」", 'if (state.error.isBlank()) "下载" else "再试一次"' in row)
    c.ok("失败原因照原话说出来", '"⚠ " + state.error' in row)
    c.ok("存到哪了要说出来（用户得找得到）", '"已保存到：" + saved.path' in row)
    c.ok("一个接收方都没有时给一句实话", "没找到能接收文件的 App，文件已经存到「下载 / SOrders报表」。" in row)
    h = hits(A_SHARE_IMPL)
    c.ok(
        "分享实现只有一处，两个入口都用它（聊天文件行 ＋ 报表中心）",
        h == {"ExportUtil.kt": 1, "AiChatScreen.kt": 1, "ReportCenter.kt": 1},
        f"实际 {h}",
    )
    h = hits(A_SAVE_URI)
    c.ok(
        "带 Uri 的存盘只有一个实现（报表中心也走它，⛔ 不许再写一份）",
        h == {"ExportUtil.kt": 2, "AiExportService.kt": 1, "ReportCenter.kt": 1},
        f"实际 {h}",
    )
    c.ok(
        "报表中心那颗按钮也是「导完就问要不要分享」",
        "saveExportFileWithUri(context, bytes, fn)" in rc and 'actionLabel = "分享"' in rc and "shareExportFile(context, saved)" in rc,
    )
    c.ok("报表中心对「分享不了」也说了实话（Q 以下）", "这台手机不能直接分享，从「下载 / SOrders报表」里发" in rc)

    util = code(EXPORTUTIL)
    c.ok("存下来的东西带着 Uri（分享的钥匙）", "data class ExportedFile(" in util and "val uri: Uri?," in util)
    c.ok("能不能分享由 Uri 说了算", "val shareable: Boolean get() = uri != null" in util)
    c.ok(
        "Q+ 走系统「下载」目录（微信/QQ 只认这个可见路径）",
        "MediaStore.Downloads.EXTERNAL_CONTENT_URI" in util and "IS_PENDING" in util,
    )
    n = subs(util, "IS_PENDING")
    c.ok("写进 MediaStore 时先挂 pending、写完再摘（否则分享方读到半截文件）", n >= 2, f"IS_PENDING 出现 {n} 次")
    c.ok("目录名与 MIME 常量都在", '"SOrders报表"' in util and "spreadsheetml.sheet" in util)
    c.ok(
        "分享是标准 SEND ＋ 授读权限 ＋ 选择器（微信/QQ 都是这样收文件的）",
        "Intent.ACTION_SEND" in util
        and "Intent.EXTRA_STREAM" in util
        and "Intent.FLAG_GRANT_READ_URI_PERMISSION" in util
        and 'Intent.createChooser(send, "分享到")' in util,
    )
    c.ok("没有 Uri 就说分享不了（Q 以下如实说，不假装能发）", "val uri = file.uri ?: return false" in util)

    # ---- 8. 远端层与后端原样 ----
    print()
    print("  -- 远端层与后端原样 --")
    apis = code(APIS)
    n = apis.count("ledger/export-jobs")
    c.ok("账本导出的三个端点都封装了（建任务 / 查状态 / 下载）", n >= 3, f"找到 {n} 处")
    dtos = code(DTOS)
    c.ok(
        "出入参都在，且状态常量与后端一致",
        "LedgerExportJobDto" in dtos and "LedgerExportJobCreateDto" in dtos and 'DONE = "done"' in dtos and 'FAILED = "failed"' in dtos,
    )
    repo = code(REPO)
    c.ok(
        "仓储把三个端点都接出来",
        all(x in repo for x in ("createLedgerExportJob", "ledgerExportJob", "downloadLedgerExportJob")),
    )
    ledapi = read(LEDGER_API)  # ⚠️ 同上：后端文件一律读原文
    quota_gate = "if recent_jobs >= EXPORT_DAILY_QUOTA:"
    c.ok(
        "「今天已经导出 N 次」那道闸还在（配额真的挡得住，不只是留了句提示）",
        subs(ledapi, quota_gate) == 1,
        f"找到 {subs(ledapi, quota_gate)} 处",
    )
    slot_gate = "slot = acquire_export_slot(current.id)"
    c.ok(
        "占槽位那一步还在（同一账号同时只能有一本账在跑）",
        subs(ledapi, slot_gate) == 1 and subs(ledapi, "if slot is None:") == 1,
        f"占槽位 {subs(ledapi, slot_gate)} 处 / 判空闸 {subs(ledapi, 'if slot is None:')} 处",
    )
    c.ok(
        "后端三道闸原样都在：单飞闸 / 每天 20 次配额 / 20000 行上限",
        "acquire_export_slot" in ledapi and "今天已经导出" in ledapi and "一次最多导出" in ledapi,
    )
    c.ok("上一次还在生成时也不重复排队（后端那句原样）", "上一次导出还在生成中" in ledapi)
    c.ok("PDF 导出的实话也原样（服务器没有内嵌中文字体）", "PDF 导出暂时关闭" in ledapi)
    c.ok("本单没碰后端：三处端点只是被客户端用起来", "export-jobs" in ledapi and "/download" in ledapi)

    # ---- 9. 单测与反向验证 ----
    print()
    print("  -- 单测与反向验证 --")
    t = read(ENABLED_TEST)
    c.ok(
        "默认工具集的单测钉着 export_ledger（⛔ 漏进 DEFAULT_ENABLED_TOOLS 会被静默筛掉）",
        "AiTools.EXPORT_LEDGER in effective" in t
        and "AiTools.EXPORT_LEDGER in first" in t
        and "AiTools.EXPORT_LEDGER in second" in t,
    )
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")
    rev = read(ROOT / REVERSE)
    c.ok(
        "反验脚本拿着注入锁（lock_reverse_verify）",
        "lock_reverse_verify" in rev,
        "没上锁：注入期间别的检查会给出不可信的结论",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 工具层接线：常量 / 分发 / ALL / 分组 / 标题 / 说明 / schema / 默认开启集，少一根就红")
        print("     · 货主拿不到两个导出工具（连角色白名单那一行也只许有一个写法）")
        print("     · 工具回合不生成文件：export_sheet 不发网络、export_ledger 只发一次只读请求")
        print("     · 全树只有交付层 ＋ 仓储两处能建任务、能查任务（配额只由用户点出来）")
        print("     · 配方只有一处键名定义；整段在喂给模型之前被摘掉（摘的是 forModel 那份）")
        print("     · 文件名与统计区间：六个中文页签名与报表中心逐字同名、与后端 _window 同一条算法")
        print("     · 交付层：jobId 复用、2 秒 ×60 轮询、DONE/FAILED/超时三句话术、存盘走带 Uri 那一个")
        print("     · 界面：busy 守卫、失败可再点、存下才有「分享」、失败原因照原话说")
        print("     · 分享只有一处实现、两个入口都用它；Q+ 走系统下载目录并带 Uri 授读权限")
        print("     · 后端三道闸与 PDF 那句原样；单测与反向验证脚本都在")

    return c.report("AI 把表格递进聊天、点了能下载能分享（L-43 / CHG-0078）")


if __name__ == "__main__":
    sys.exit(main())
