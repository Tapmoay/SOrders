"""开放 AI 写域「发票台账」六条写端点（CHG-0086 / 台账 L-55）。

## 用户要的（2026-10-08，ref m31054–m31057）
「发票那些也开给 AI」——手工页早就能建 / 改 / 开具 / 作废 / 恢复，_tools/ai/_write_coverage.py
里当初关着的理由是「票面金额直接进税汇、写动作那条线还没收工」⇒ 这一单解掉的是**排期**，
不是补能力缺口（六条端点在覆盖表里从来没有被标成"用不上"）。

## 这一条为什么必须有机器的判据
这一条的毛病全是「没报错但也没发生」：
- **把六件事压成三件**：模型会把「作废」和「撤票」当成同一件事，也会以为「开具＝进税汇」——
  用户点完才发现票还在台账里、或者票号被一直占着；
- **未税票 vs 零税率票**：「有没有税」在登记那一刻就定了（后端 update 改不了它），卡片少写一句，
  用户就会拿一句"加个税率"去改一张未税票；
- **税额两个算法**：卡片按一个算法算、payload 按另一个算 ⇒ 卡片显示 130、库里存 155；
- **定位撞车**：票号是唯一精确键；其余条件（日期 / 金额 / 对方）撞上多张时必须列候选、拒绝动手，
  否则动的是一张跟用户嘴里那张无关的票；
- **回收站里的票被当成"没有这张票"**：定位不带 includeDeleted=true，用户会被劝着重复登记一张新票；
- **prepare 里写数据**：预览一次就动一次库（卡片与落库两条路径就此分叉，而且不报错）；
- **撤回口径自相矛盾**：登记 / 开具 / 作废没有逆操作（UNDO_NONE 逐条写明后果），改票 / 撤票有
  （资源表推导），恢复自己不能被撤回 —— 少一处、多一处，用户问「误操作了怎么办」就会答错。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
这一条的红线都不是类型能表达的：「六件事不许压成三件」是**动作表的条数与标题**；
「未税票不许加税率」是**卡片文案与拒绝文案里有没有那几句话**；「税额只有一个算法」是
**同一条公式被几处引用**；「票号是唯一精确键」是**拒绝分支里有没有列候选**；
「回收站里的票要如实说」是**一次查询的参数**；「prepare 不许写数据」是
**某个方法名出现在哪个函数体里**；「撤回口径」是**两张表（UNDO_NONE 与资源表）之间的分工**。
所以判据只能钉在源码结构、文案字面、调用次序与表白上，外加真机把六条各走一遍。

## 判据（每条都能被反向验证弄红）
1. 六条动作登记一处（id 常量、组、标题、风险档、只给派单员、进 ALL）；
2. 参数：定位五件套（invoice_no / direction / date / amount / party）＋ 登记九样，
   且**没有**以编号为名的输入参数（编号只能从定位结果里来）；
3. 定位：includeDeleted=true、票号唯一精确键、0 条与多条都拒绝并给候选、命中回收站如实说；
4. 税额：全库唯一算法（与后端 tax_service.tax_of_amount 同一式）、只给税率时倒推、
   算出来的数**显式进 payload**；
5. 卡片：六张卡各自把「能不能撤 / 后果是什么」说清（作废 vs 撤票、开具＝冻结、未税票不进税汇）；
6. 撤回：资源表 INVOICE 一整块（六键 / labels / moneyKeys / nullableWritable / paired）、
   UNDO_NONE 只有三条（登记 / 开具 / 作废）、恢复走 undoOnly；
7. 数据层：七个方法（接口 ＋ 实现）、写走 repo 的对应入口、快照走单取端点；
8. 覆盖表：六条不再挂在「不做」里、来龙去脉留着、能力格认领；
9. 文档 / 反验 / 防静默空转：变更单九节、登记簿、工作声明、台账、反验脚本、行数下限。

用法：python _tools/qa/_check_ai_invoices.py
"""
import re
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

AIWRITE = AI / "AiWrite.kt"
INV = AI / "AiWriteInvoices.kt"
SVC = AI / "AiWriteService.kt"
SRC = AI / "AiWriteDataSource.kt"
RES = AI / "AiResources.kt"
REVERT = AI / "AiRevert.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"
REPO = AND / "data/repo/AppRepository.kt"
APIS = AND / "data/remote/api/Apis.kt"
BACKEND_TAX = ROOT / "backend/app/services/tax_service.py"
BACKEND_INV = ROOT / "backend/app/api/v1/invoices.py"
BACKEND_RBAC = ROOT / "backend/app/core/rbac.py"

TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"
PROMPT_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWritePromptTest.kt"

WRITE_COVERAGE = ROOT / "_tools/ai/_write_coverage.py"
READ_COVERAGE = ROOT / "_tools/ai/_read_coverage.py"
GUARDRAILS = ROOT / "_tools/ai/_check_ai_guardrails.py"
LEDGER = ROOT / "_tmp/USER_BUG_LEDGER_20261006.md"

CHG_ID = "CHG-0086"
CHG_DOC = ROOT / "docs/changes/CHG-0086.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_ai_invoices.py"

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
MIN_INV_LINES = 700
MIN_AIWRITE_LINES = 2700
MIN_SVC_LINES = 1100
MIN_SRC_LINES = 2100
MIN_RES_LINES = 1400
MIN_REVERT_LINES = 1000
MIN_TEST_LINES = 6000
MIN_PROMPT_TEST_LINES = 100

REQUIRED_FILES = (
    AIWRITE, INV, SVC, SRC, RES, REVERT, DTOS, REPO, APIS,
    BACKEND_TAX, BACKEND_INV, BACKEND_RBAC,
    TEST, PROMPT_TEST, WRITE_COVERAGE, READ_COVERAGE, GUARDRAILS,
)

LF = chr(10)

#: 五条有规格的动作（中文名, id 常量, 动作 id, 风险档, 标题逐字）
ACTIONS = (
    ("登记", "INVOICES_CREATE", "invoices.create", "HIGH", "登记一张发票"),
    ("改票", "INVOICES_UPDATE", "invoices.update", "MEDIUM", "改一张发票"),
    ("开具", "INVOICES_ISSUE", "invoices.issue", "HIGH", "开具一张发票"),
    ("作废", "INVOICES_VOID", "invoices.void", "HIGH", "作废一张发票"),
    ("撤票", "INVOICES_DELETE", "invoices.delete", "MEDIUM", "撤票（放进回收站）"),
)

#: 恢复那条是撤回专用（restoreAction 造，没有自己的规格）
RESTORE_CONST = "INVOICES_RESTORE"

#: 预览（prepare）里**一个字都不许出现**的写调用：出现即「预览动了数据」。
WRITE_CALLS = (
    "ds.createInvoice(",
    "ds.updateInvoice(",
    "ds.issueInvoice(",
    "ds.voidInvoice(",
    "ds.deleteInvoice(",
    "ds.restoreInvoice(",
)

#: 五个手写处理器（create / update / issue / void / delete）＋ 各自 commit 该调的写方法
HANDLERS = (
    ("CreateInvoiceHandler", "ds.createInvoice("),
    ("UpdateInvoiceHandler", "ds.updateInvoice("),
    ("IssueInvoiceHandler", "ds.issueInvoice("),
    ("VoidInvoiceHandler", "ds.voidInvoice("),
    ("DeleteInvoiceHandler", "ds.deleteInvoice("),
)


def read(p: Path) -> str:
    """读文件；**读不到就返回空串**（缺文件由第 0 节报红，绝不在这里抛：脚本一崩就没有 [FAIL] 行，
    而反向验证的判据正是「期望的检查名出现在 [FAIL] 行里」，崩了等于什么都能过）。"""
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").replace(chr(13) + chr(10), LF)


def code(p: Path) -> str:
    return strip_comments(read(p))


def subs(text: str, needle: str) -> int:
    return text.count(needle)


def raw_block(src: str, sig: str) -> str:
    """从 sig 起按大括号配平取整块（取不到返回空串，让断言自己去红）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    j = src.find("{", i)
    if j < 0:
        return ""
    depth = 0
    for k in range(j, len(src)):
        ch = src[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[j:k + 1]
    return ""


def part_of(src: str, start: str, end: str) -> str:
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i)
    return src[i:j] if j > i else src[i:]


def class_block(src: str, cls: str) -> str:
    """一个处理器类整块（取不到返回空串）。"""
    return raw_block(src, "class " + cls + "(")


def spec_of(src: str, const: str) -> str:
    """抓 「id = AiWrites.<const>,」那一条 AiWriteAction 规格（到下一个规格为止）。

    窗口必须**短**：钉在全文件会让「参数里没有编号」这类否定断言变成空转
    （别处的 invoice_id 会让它永远为假，而它看上去还像在管这件事）。
    """
    i = src.find("id = AiWrites." + const + ",")
    if i < 0:
        return ""
    j = src.find(LF + "        AiWriteAction(", i)
    return src[i:j] if j > i else src[i:i + 2200]


def run_cmd(args: list) -> tuple:
    """实跑一个脚本，返回（输出, 退出码）。跑不起来也不抛（抛了就没有 [FAIL] 行）。"""
    try:
        p = subprocess.run(
            args, cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=600,
        )
        return (p.stdout or "") + (p.stderr or ""), p.returncode
    except Exception as e:  # noqa: BLE001
        return "跑不起来：" + str(e), -1


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails: list = []

    def ok(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + name)
        else:
            self.fails.append(name)
            print("  [FAIL] " + name + ("  <- " + detail if detail else ""))

    def has(self, name: str, hay: str, needle: str) -> None:
        self.ok(name, needle in hay, "没找到：" + needle)

    def hasnt(self, name: str, hay: str, needle: str) -> None:
        self.ok(name, needle not in hay, "不该出现：" + needle)


def main() -> int:
    if refuse_if_injecting("发票台账六条（CHG-0086）判据"):
        return 0

    c = Checker()
    w = read(AIWRITE)
    wc = code(AIWRITE)
    inv = read(INV)
    invc = code(INV)
    s = read(SVC)
    sc = code(SVC)
    src = read(SRC)
    srcc = code(SRC)
    rs = read(RES)
    rv = read(REVERT)
    apis = read(APIS)
    repo = read(REPO)
    t = read(TEST)
    pt = read(PROMPT_TEST)

    print("== 0. 文件在，而且不是空壳 ==")
    for p in REQUIRED_FILES:
        c.ok("文件在：" + str(p.relative_to(ROOT)), p.exists())
    c.ok("行数下限（AiWriteInvoices.kt）", len(inv.splitlines()) >= MIN_INV_LINES, "实际 " + str(len(inv.splitlines())))
    c.ok("行数下限（AiWrite.kt）", len(w.splitlines()) >= MIN_AIWRITE_LINES, "实际 " + str(len(w.splitlines())))
    c.ok("行数下限（AiWriteService.kt）", len(s.splitlines()) >= MIN_SVC_LINES, "实际 " + str(len(s.splitlines())))
    c.ok("行数下限（AiWriteDataSource.kt）", len(src.splitlines()) >= MIN_SRC_LINES, "实际 " + str(len(src.splitlines())))
    c.ok("行数下限（AiResources.kt）", len(rs.splitlines()) >= MIN_RES_LINES, "实际 " + str(len(rs.splitlines())))
    c.ok("行数下限（AiRevert.kt）", len(rv.splitlines()) >= MIN_REVERT_LINES, "实际 " + str(len(rv.splitlines())))
    c.ok("行数下限（AiWriteTest.kt）", len(t.splitlines()) >= MIN_TEST_LINES, "实际 " + str(len(t.splitlines())))
    c.ok("行数下限（AiWritePromptTest.kt）", len(pt.splitlines()) >= MIN_PROMPT_TEST_LINES, "实际 " + str(len(pt.splitlines())))
    c.has("发票文件头顶写着这一条由哪个判据钉住", inv, "_tools/qa/_check_ai_invoices.py")
    c.has("发票文件头顶点名反向验证脚本", inv, "_tools/qa/_reverse_verify_ai_invoices.py")

    print("== 1. 六条动作登记一处（id / 组 / 标题 / 风险档 / 只给派单员） ==")
    for cn, const, sid, risk, title in ACTIONS:
        c.ok(cn + "：id 常量只声明一次", subs(wc, "const val " + const + " = \"" + sid + "\"") == 1)
        c.ok(cn + "：规格只登记一处（id = AiWrites." + const + "）", subs(inv, "id = AiWrites." + const + ",") == 1)
        c.ok(cn + "：规格不在服务文件里偷偷再写一份", subs(sc, "id = AiWrites." + const + ",") == 0)
        spec = spec_of(inv, const)
        c.ok(cn + "：规格块抽得出来（不是空转）", len(spec) > 300, "只抽到 " + str(len(spec)) + " 字符")
        c.has(cn + "：挂在「发票」组下", spec, "group = AiWrites.G_INVOICE,")
        c.has(cn + "：标题逐字", spec, "title = \"" + title + "\",")
        c.has(cn + "：风险档逐字（" + risk + "）", spec, "risk = AiWriteRisk." + risk + ",")
    c.ok("「发票」组常量只声明一次", subs(wc, "const val G_INVOICE = \"发票\"") == 1)
    c.ok("六条接进了动作总表（ALL 里的 AiWriteInvoices.ACTIONS）", subs(wc, "AiWriteInvoices.ACTIONS") == 1)
    rspec = spec_of(inv, RESTORE_CONST)
    c.has("恢复那条是撤回专用：规格由 restoreAction 造（自带 undoOnly）", inv, "restoreAction(")
    c.has("恢复那条的 commit 走数据源的恢复方法", inv, "call = { ds, id -> ds.restoreInvoice(id) },")
    c.has("恢复那条也挂在「发票」组下", rspec, "group = AiWrites.G_INVOICE,")
    c.has("六条都不是新能力（免得后人以为是新端点）", inv, "后端这六个写端点干的是六件不同的事")
    c.has("发票那一段的注释点名写闸门是 LEDGER_EDIT", w, "Permission.LEDGER_EDIT")
    # ⛔ 不能用 raw_block：SHIPPER_ACTIONS 是 setOf(...) 以 ")" 收尾，花括号配平会抽到后面某个函数体
    block = part_of(wc, "val SHIPPER_ACTIONS: Set<String> = setOf(", LF + "    )")
    c.ok("SHIPPER_ACTIONS 那个清单抽得出来（下面的判断才有意义）", len(block) > 500, "只抽到 " + str(len(block)) + " 字符")
    c.ok("六条一条都不在货主清单里（后端要 ledger:edit）", "INVOICES_" not in block and "invoices." not in block)
    c.has("动作数那句话跟着改了（175 里 44 条）", w, "175 个动作里 44 条在清单内")

    print("== 2. 参数：定位五件套 ＋ 登记九样，没有以编号为名的输入 ==")
    loc = part_of(inv, "private fun locateParams(", LF + "val ACTIONS")
    c.ok("定位参数那一块抽得出来", len(loc) > 300, "只抽到 " + str(len(loc)) + " 字符")
    for nm in ("invoice_no", "direction", "date", "amount", "party"):
        c.has("定位参数里有 " + nm, loc, "name = \"" + nm + "\"")
    c.has("票号参数说清它是最准的定位方式", inv, "最准的定位方式。票号还没拿到就用 date + amount，或者对方的名字")
    c.has("日期参数说清比对窗口含前后 31 天", inv, "比对时含前后 31 天")
    cs = spec_of(inv, "INVOICES_CREATE")
    for nm in ("direction", "invoice_no", "date", "amount", "tax_rate", "tax_amount", "supplier", "customer", "purchase_orders", "note"):
        c.has("登记参数里有 " + nm, cs, "name = \"" + nm + "\"")
    c.has("登记参数把「未税票」的口径写在提示里", cs, "不给 = 未税票（未税票不进税汇）")
    c.has("登记参数把「只给税率时倒推」写在提示里", cs, "只给税率时按「合计 ÷ (1 + 税率)」倒推")
    c.has("挂采购单参数写清一单或多单怎么分隔", cs, "用「、」或「,」分开，例如 12、15")
    us = spec_of(inv, "INVOICES_UPDATE")
    for nm in ("new_invoice_no", "new_date", "new_amount", "new_tax_rate", "new_tax_amount", "note"):
        c.has("改票参数里有 " + nm, us, "name = \"" + nm + "\"")
    c.hasnt("参数表里没有以编号为名的输入（编号只能从定位结果来）", inv, "name = \"invoice_id\"")
    c.ok("MAX_INVOICE_NO_CHARS 与后端那次 64 对齐", subs(inv, "MAX_INVOICE_NO_CHARS = 64") == 1)

    print("== 3. 定位：回收站要带上、票号最准、撞车就列候选 ==")
    c.has("数据源注释写明定位时必须传 true（否则票在回收站里会被判成不存在）", s, "**定位时必须传 true**")
    c.has("接口的 includeDeleted 默认 false", s, "includeDeleted: Boolean = false,")
    # ⚠️ 2026-10-08（CHG-0086 反验时逮到的空转）：原来这一条读的是**整个数据源文件**里的
    #    "includeDeleted = true" —— 而那句话在别的域里出现 6 次（结算 / 供应商快照…），
    #    发票这一跳一个字都不写也照样绿。改成钉**发票处理器那一处实参**，并另加一条钉
    #    「数据源把它原样透传给 repo」（写死成 false 的话回收站里的票会被判成不存在）。
    c.has("实现里定位确实传了 includeDeleted = true", invc, "includeDeleted = true,")
    c.has("数据源把 includeDeleted 原样透传给 repo（不是自己写死）", srcc, "includeDeleted = includeDeleted,")
    c.has("定位窗口与账本同口径（前后 31 天）", inv, "INVOICE_WINDOW_DAYS = 31L")
    c.has("一次最多拉 100 张（与后端默认分页一致）", inv, "PROBE_LIMIT = 100")
    c.has("一个能收窄的都不给就拒绝，并教用户怎么给", inv, "要动的是哪一张票？给我票号（最准），或者开票日期 + 价税合计，或者对方的名字。")
    c.has("拒绝时给一条出路（先看一眼台账）", inv, "先看一眼发票台账：这张票的票号 / 日期 / 金额 / 对方是谁")
    c.has("找不到票时不许动别的票", inv, "不要凭空动别的票 —— 把票号或者日期说准一点。")
    c.has("撞上多张就列候选、拒绝动手", inv, "请说清楚是哪一张（票号最准）。")
    c.has("命中回收站要如实说（不是「没有这张票」）", inv, "先到「发票台账」页顶部切到")
    # ⛔ 2026-10-09（台账 L-57 收口）：这句以前是「先说「恢复这张票」，把它放回台账再改。」——
    #    可恢复动作 `INVOICES_RESTORE` 是 **undoOnly**（不进模型的动作清单，见 AiWriteInvoices.kt:217-225），
    #    真机上照卡片说只会被回「我这边没有「恢复发票」这个操作」。
    #    用户口径：「恢复发票和撤回是一个意思，直接改文案，写明点「撤回」」——
    #    所以指路必须落在**真人走得通**的那条路上（台账页顶部的回收站）。
    c.has("命中回收站时指路到台账的回收站（真人走得通的那条路）", inv, "「回收站」，把它恢复回来再来改。")

    print("== 4. 税额：全库唯一算法，算出来的数显式进 payload ==")
    c.ok("税额算法只有一处定义", subs(inv, "fun taxOf(") == 1)
    tax = raw_block(invc, "fun taxOf(")
    c.ok("税额算法那一块抽得出来", len(tax) > 100, "只抽到 " + str(len(tax)) + " 字符")
    c.has("算法用 movePointLeft 把百分数变成除数（不用 double）", tax, "movePointLeft(2)")
    c.has("中间除法向下取（与后端同一式）", tax, "RoundingMode.DOWN")
    c.has("最后到分四舍五入", tax, "RoundingMode.HALF_UP")
    c.has("注释点名后端那一个出处", inv, "tax_service")
    c.ok("登记与改票都用同一个算法", subs(invc, "taxOf(") >= 3)
    c.has("登记时算出来的税额显式进 payload", inv, "put(\"tax_amount\"")
    c.has("卡片上那句话说清卡片与库里是同一个数", inv, "按「合计 ÷ (1 + 税率)」倒推，与后端同一个算法")

    print("== 5. 六张卡片：能不能撤、后果是什么，逐句说清 ==")
    create = class_block(inv, "CreateInvoiceHandler")
    c.ok("登记处理器整块抽得出来", len(create) > 800, "只抽到 " + str(len(create)) + " 字符")
    c.has("登记卡：方向", create, "方向：")
    c.has("登记卡：空票号怎么说", create, "票号：还没拿到，先空着（登记之后可以在台账里补上）")
    c.has("登记卡：未税票当场说清它不进税汇", create, "这是一张未税票：它照常留在台账里，但不进税汇")
    c.has("登记卡：有税票写明税率与税额", create, "税额：")
    c.has("登记卡：不含税金额也算出来", create, "不含税金额：")
    c.has("登记卡：挂的采购单逐张列出", create, "挂的采购单：")
    c.has("登记卡：票号唯一占号", create, "票号一旦登记就唯一占号：同一个方向、同一个票号只能有一张票")
    c.has("登记卡：有没有税在登记那一刻定了", create, "票的「有没有税」在登记这一刻就定了：以后改不动税率 —— 要改只能作废重开一张")
    c.has("登记卡：空票号不参与查重", create, "空票号不参与查重")
    upd = class_block(inv, "UpdateInvoiceHandler")
    c.ok("改票处理器整块抽得出来", len(upd) > 800, "只抽到 " + str(len(upd)) + " 字符")
    c.has("改票卡：这张票现在是什么样", upd, "这张票现在是：")
    c.has("改票卡：逐字段写改前改后", upd, "这一下改什么")
    c.has("改票卡：改完还是「已登记」", upd, "改完这张票还是「已登记」：还能接着改，也可以开具它")
    c.has("改票卡：旧票号会空出来", upd, "票号换了之后旧号就空出来了（别的票可以再用它）")
    c.has("改票卡：有没有税改不了", upd, "票的「有没有税」改不了：含税的票一直是含税的，未税票也一直是未税票")
    c.has("改票门：已开具 / 已作废改不动", upd, "只有「已登记」状态的票能改；要改就作废重开一张。")
    c.has("改票门：未税票加不上税率", upd, "这张票是未税票（登记时没填税率），现在加不上税率")
    c.has("改票门：没说要改什么与说的一样是两句话", upd, "你还没说要改成什么。这张票能改：票号（new_invoice_no）、开票日期（new_date）、")
    c.has("改票门：给的新值和现在一样也要拒", upd, "你给的新值和现在一模一样，没什么可改的")
    iss = class_block(inv, "IssueInvoiceHandler")
    c.has("开具卡：真实世界那一下对应什么", iss, "真实世界里这一下对应的是：票已经开出去、寄给对方了")
    c.has("开具卡：开具＝冻结", iss, "开具之后这张票就冻结了：一个字都改不动（要改只能作废重开一张）")
    c.has("开具卡：未税票与税汇无关", iss, "它进不进税汇和「开没开」无关：这张是未税票，一直不进税汇")
    c.has("开具卡：有税票登记那天起就在税汇里", iss, "它进不进税汇和「开没开」无关：这张有税率，登记那天起就已经在税汇里了")
    c.has("开具门：已开具不能再开具", iss, "这张票已经开具过了（")
    c.has("开具门：已作废不能再开具", iss, "作废的票不能再开具；要重开就新登记一张。")
    vo = class_block(inv, "VoidInvoiceHandler")
    c.has("作废卡：票留在台账里、票号还占着、退出税汇", vo, "作废之后：票还留在台账里（作废是一个状态，不是删掉）、票号一直占着、退出税汇")
    c.has("作废卡：与「撤票」不是一件事", vo, "它和「撤票」不是一件事：撤票是进回收站（列表里看不见、可以原样恢复）；作废是留在台账里、不可逆")
    c.has("作废卡：税账上的变化说清", vo, "税账上的变化：销项 / 进项合计里不再算它，它的税额也不再算")
    c.has("作废卡：未税票作废只影响一件事", vo, "所以作废只影响一件事：这张票从此不能再开具")
    c.has("作废卡：已开具的票唯一出路是作废", vo, "作废是已开具的票唯一的出路")
    c.has("作废门：已作废不能再作废", vo, "这张票已经作废过了（")
    c.has("作废门：回收站里的票先恢复再作废", vo, "作废一个已经在回收站里的票没有意义 —— 要留痕就先恢复它、再作废。")
    de = class_block(inv, "DeleteInvoiceHandler")
    c.has("撤票卡：撤票＝进回收站", de, "撤票 = 放进回收站：台账列表里默认看不见它了")
    c.has("撤票卡：票号仍然占着", de, "但票号仍然占着 —— 同一张票再登记一次会被后端拒掉（号没释放）")
    c.has("撤票卡：放回去随时可以（写明点聊天里那个「撤回」）", de, "放回去随时可以：聊天里那条结果消息上会有一个「撤回」")
    c.has("撤票卡：恢复之后六样字段全在", de, "票号、日期、金额、税额、备注都会原样回来")
    c.has("撤票卡：与「作废」不是一件事", de, "它和「作废」不是一件事：作废留在台账里、不可逆；撤票进回收站、可原样恢复")
    c.has("撤票门：已经在回收站里了", de, "这张票已经在回收站里了（")
    # ⛔ 红线（台账 L-57）：全库代码里不许再出现「说「恢复这张票」」这种**做不到的指路** ——
    #    那是 undoOnly 的恢复动作（不进模型的动作清单），用户照念一遍就是白说（真机实证见 L-57）。
    #    ⚠️ 读的是 code(INV)（去注释）：注释里可以讲这段历史，**代码**里一个字都不许留。
    c.hasnt("代码里不再出现「说「恢复这张票」」这种做不到的指路", invc, "说「恢复这张票」")
    c.has("撤票卡写明撤回要点确认（撤回不是一下就成）", de, "点它、再确认一次就恢复")

    print("== 6. 撤回：资源表一整块 ＋ UNDO_NONE 只有三条 ==")
    c.has("资源 key", rs, 'key = "invoice",')
    c.has("资源中文名", rs, 'cn = "发票",')
    c.has("资源 idKey", rs, 'idKey = "invoice_id",')
    c.has("读回键＝改票能改的六样", rs, 'readKeys = setOf("invoice_no", "invoice_date", "amount", "tax_rate", "tax_amount", "note"),')
    c.has("金额键（税汇那三样也按钱显示）", rs, 'moneyKeys = setOf("amount", "tax_amount", "tax_rate"),')
    c.has("可写回的空值只有票号与备注", rs, 'nullableWritable = setOf("invoice_no", "note"),')
    c.has("三条动作挂在资源下（改 / 删 / 成对恢复）", rs, "update(AiWrites.INVOICES_UPDATE),")
    c.has("删那条", rs, "delete(AiWrites.INVOICES_DELETE),")
    c.has("恢复与删成对，撤回时写回 target_id", rs, "AiInverse(AiWrites.INVOICES_DELETE, mapOf(\"invoice_id\" to AiRevert.ID)),")
    c.has("快照走单取端点", rs, 'read = { ds, id -> ds.snapshot("invoice", id) },')
    c.has("恢复成对动作", rs, "restore = AiInverse(AiWrites.INVOICES_RESTORE, mapOf(\"target_id\" to AiRevert.ID)),")
    c.has("恢复那两句换成本表自己的（默认那句提到图片与坐标）", rs, "票没有图片也没有坐标")
    c.has("恢复第 1 句", rs, "把刚才撤掉的那张票放回来")
    c.has("恢复第 2 句（六样字段全在）", rs, "放回来之后票号、开票日期、价税合计、税率、税额、备注都和撤掉之前一模一样")
    c.has("资源收进了总表", rs, "INVOICE,")
    c.has("发票那一段在总表里有注释（建·开具·作废走 UNDO_NONE）", rs, "改 / 删 / 恢复三条挂在这，建·开具·作废走 UNDO_NONE")
    # ⛔ 抽的是 buildUndoNone：undoNoneTable()（AiRevert.kt:575-583）只负责建表 + 调它，条目全在 buildUndoNone(:585) 里
    undo = raw_block(rv, "private fun buildUndoNone(")
    c.ok("UNDO_NONE 那张表抽得出来", len(undo) > 2000, "只抽到 " + str(len(undo)) + " 字符")
    c.has("登记没有逆操作，理由逐条写明", undo, "票已经登记进台账了，撤不回来（登记那一刻起它就占着号、进税汇）")
    c.has("开具没有逆操作（冻结）", undo, "开具不能反悔：这张票已经从「已登记」变成「已开具」，票号、金额、日期一个字都改不动了")
    c.has("作废没有逆操作（票还占着号）", undo, "作废也撤不回来（票一直留在台账里、还占着那个号、只是退出了税汇）")
    c.ok("改票不写在 UNDO_NONE 里（它挂在资源表下）", "INVOICES_UPDATE" not in undo)
    c.ok("撤票不写在 UNDO_NONE 里（它自己在资源表下）", "INVOICES_DELETE" not in undo)
    c.ok("恢复不写在 UNDO_NONE 里（撤回路径专用）", "INVOICES_RESTORE" not in undo)
    c.has("注释说明为什么这三条不重复声明（两边都写＝自相矛盾）", rv, "改票、删票、恢复三条挂在资源表 INVOICE 下（框架推导）")

    print("== 7. 数据层：七个方法 ＋ 写走 repo 那一个入口 ==")
    for sig in ("suspend fun invoices(", "suspend fun createInvoice(draft: AiInvoiceDraft): Long",
                "suspend fun updateInvoice(id: Long, changes: JsonObject)", "suspend fun issueInvoice(id: Long)",
                "suspend fun voidInvoice(id: Long)", "suspend fun deleteInvoice(id: Long)",
                "suspend fun restoreInvoice(id: Long)"):
        c.has("接口里有：" + sig, s, sig)
        c.has("实现里有：" + sig, src, "override " + sig)
    c.ok("接口里方法只声明一次（不是两份）", subs(s, "suspend fun invoices(") == 1 and subs(s, "suspend fun restoreInvoice(id: Long)") == 1)
    c.has("定位实现走 repo.invoices", srcc, "repo.invoices(")
    c.has("登记实现走后端唯一那个建单入口（InvoiceCreateRequest）", srcc, "repo.createInvoice(")
    c.has("登记实现用的是后端那一个请求体", srcc, "InvoiceCreateRequest(")
    c.has("改票实现用的是后端那一个请求体", srcc, "InvoiceUpdateRequest(")
    c.has("改票实现走 repo.updateInvoice", srcc, "repo.updateInvoice(")
    for m in ("issueInvoice", "voidInvoice", "deleteInvoice", "restoreInvoice"):
        c.has("实现里的 " + m + " 直接转发 repo", src, "repo." + m + "(id)")
    c.has("快照那一跳挂上了 invoice", srcc, '"invoice" -> AiBefore(id, AiRevertRead.invoice(repo.invoice(id)))')
    c.has("发票 mapper 在", rs, "fun invoice(d: InvoiceDto): JsonObject")

    print("== 8. 覆盖表：六条不再挂在「不做」里 ==")
    wcov = read(WRITE_COVERAGE)
    c.hasnt("POST /invoices 不再挂在「不做」里", wcov, '("POST", "invoices")')
    c.hasnt("POST /invoices/{}/issue 不再挂在「不做」里", wcov, '("POST", "invoices/{}/issue")')
    c.hasnt("POST /invoices/{}/void 不再挂在「不做」里", wcov, '("POST", "invoices/{}/void")')
    c.hasnt("DELETE /invoices/{} 不再挂在「不做」里", wcov, '("DELETE", "invoices/{}")')
    c.has("来龙去脉留着（当初关着的理由是哪一类）", wcov, "票面金额直接进税汇、写动作那条线还没收工")
    c.has("来龙去脉留着（这一单解掉的是排期）", wcov, "用户 2026-10-08 把这条排期")
    c.has("覆盖表点名台账 L-55", wcov, "台账 L-55")
    c.has("覆盖表点名作废与撤票必须逐句分清", wcov, "在卡片上逐句分清")
    c.has("覆盖表写明税额只有一个算法", wcov, "税额只有一个算法")
    c.has("覆盖表写明六条只给派单员", wcov, "六条都只给派单员（后端要 ledger:edit）")
    gout, grc = run_cmd([sys.executable, str(GUARDRAILS)])
    c.ok("AI 红线脚本实跑通过（exit 0）", grc == 0, "exit " + str(grc))
    c.has("红线白名单把 invoices 认成读（否则 prepare 里的定位会被判成写）", read(GUARDRAILS), '"invoices",')
    wout, wrc = run_cmd([sys.executable, str(WRITE_COVERAGE)])
    c.ok("写覆盖脚本实跑通过（exit 0）", wrc == 0, "exit " + str(wrc))
    c.has("写覆盖表：未覆盖的都有理由、0 条真缺口", wout, "0 条是真缺口")
    rout, rrc = run_cmd([sys.executable, str(READ_COVERAGE), "--check"])
    c.ok("读覆盖脚本 --check 实跑通过（exit 0）", rrc == 0, "exit " + str(rrc))
    c.has("读覆盖：没交代的仍然是 0", rout, "没交代：0")

    print("== 9. 单测 / 文书 / 反验 / 防静默空转 ==")
    for name in ("发票·登记进项票：名册查名、采购单逐张核，卡片把五件事写全",
                 "发票·登记销项票：没给税率就是未税票（卡片当场说清它不进税汇）",
                 "发票·登记参数门：方向、对方、采购单一处不对就当场说清，一条都不许写",
                 "发票·税额：只给税率时按后端同一算法倒推，并把算出来的数写进 payload",
                 "发票·定位门：一个能收窄的都不给、找不到、撞上多张，都不许动手",
                 "发票·回收站里的票：找得到，但要如实说它在回收站里（不是「没有这张票」）",
                 "发票·改票的三道门：已开具、已作废、未税票，三种都改不动",
                 "发票·改票：逐字段写改前改后、税额跟着重算；「没说要改什么」与「说的和现在一样」是两句话",
                 "发票·开具：卡片要把「冻结」与「和进不进税汇无关」两件事说清",
                 "发票·作废：票留在台账里、票号一直占着、退出税汇，且与「撤票」不是一件事",
                 "发票·撤票：进回收站、票号还占着；撤回把它原样放回来",
                 "发票·撤回改票：把改动过的字段按原值写回去",
                 "发票·六条动作的角色门：只有派单员，货主一条都看不到",
                 "发票·撤回口径：登记、开具、作废三条撤不回来，改票与撤票能撤回，恢复自己不能被撤回"):
        c.has("单测里有这一条：" + name, t, name)
    n_cases = subs(t, "fun " + chr(96) + "发票·")
    c.ok("单测里数到 14 条本单用例", n_cases == 14, "实际 " + str(n_cases))
    c.ok("单测里钉住了动作总数上界 176", "AiWrites.ALL.size <= 176" in t)
    # ⚠️ 2026-10-08（反验逮到的第二处空转）：原来这一条找的是整个测试文件里的 "createInvoice:" ——
    #    那句在断言里还出现两次（期望串本身），把假数据源那一行改坏它照样绿。改成钉**假数据源那一行**。
    c.has("假数据源记下了登记那一跳", t, 'invoiceCalls += "createInvoice:')
    c.has("假数据源把定位也记下来了（对照「拒绝时一个字都不许写」）", t, "invoices:")
    for sig in ("override suspend fun invoices(", "override suspend fun createInvoice(draft: AiInvoiceDraft): Long",
                "override suspend fun updateInvoice(id: Long, changes: JsonObject)", "override suspend fun issueInvoice(id: Long)",
                "override suspend fun voidInvoice(id: Long)", "override suspend fun deleteInvoice(id: Long)",
                "override suspend fun restoreInvoice(id: Long)"):
        c.has("假数据源实现了：" + sig, t, sig)
    c.has("说明书上限已抬到 29000（动作数涨了）", pt, "上限 29000")
    c.ok("变更单九节齐（少一节 _check_dev_spec.py 也会红）", all(x in read(CHG_DOC) for x in CHG_SECTIONS))
    # ⚠️ 2026-10-08（反验逮到的第三处空转）：原来找的是整份变更单里的 "L-55" —— 文末「读什么」那行也提到它，
    #    出处那一处删掉号它照样绿。改成钉**出处那一句的写法**（收口时要顺着它回台账 :2873 那一行）。
    # ⚠️ 2026-10-09（反验 --dry 又逮到的空转）：那之后变更单自己在「教训」那段里**引用了这句写法**
    #    （那串字在文里成了第二处），短锚点又不唯一了。⇒ 连出处整行一起钉 ——
    #    引用它讲道理不再影响判据（引用可以留，出处那一行改坏才红）。
    c.has("变更单里写了台账 L-55", read(CHG_DOC), "> 出处：台账 `_tmp/USER_BUG_LEDGER_20261006.md:2873`（**L-55**，台账末尾")
    c.has("登记簿里有这一条", read(REGISTRY), CHG_ID)
    c.has("工作声明里有这一条", read(CLAIM), CHG_ID)
    c.has("台账里有 L-55 那一行", read(LEDGER), "L-55")
    c.ok("反向验证脚本在", (ROOT / REVERSE).exists(), REVERSE)
    c.ok("判据自己数到了足够多的断言（>= 130 条）", c.passes >= 130, "实际 " + str(c.passes))

    print()
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 条不通过（共 " + str(c.passes + len(c.fails)) + " 条）：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 " + str(c.passes) + " 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
