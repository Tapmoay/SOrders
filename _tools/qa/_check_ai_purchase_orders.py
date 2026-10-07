"""开放 AI 写域「采购单」：一张进货单照片 → 读出供应商与每行 → 确认卡 → 建单（CHG-0074 / 台账 L-42）。

## 用户要的（2026-10-07，ref m01700；台账自己标为**大意**，不是逐字）
「我们也要开放关于 AI 相关的功能……我上传一张图片，然后 AI 分析出来数据之后就立马就帮我
新建一个采购单，或者说它可以新建也可以不新建，然后直接帮我搞好库存，该入的入、价格是多少
就该是多少……还有记录的，就相当于采购单嘛，就是那个入库记录」。
口径 m13365 五问（逐字答过）：
① 认图范围 = **只认「进货单 / 送货单」这一类纸质单据**（⛔ 不是「任何写了商品与数量的纸」）；
② 确认卡 = **要**（HIGH 档，这就是那句「可新建可不新建」）；
③ 成本开关 = **不破例**（卡片必须如实说「要打开成本开关才看得到成本」）；
④ 撤回 = **能**（＝冲库存 ＋ 删/撤应付），但建单本身没有一键撤回，完成后要给一句**专门**的
   出路话（「撤掉采购单 #N」）；
⑤「入库记录不用 AI 搞」= **就是那个意思**：AI ⛔ 不写 inventory_movements（落库自然产生记录），
   只负责读。

## 这一条为什么必须有机器的判据
这一条的毛病全是「没报错但也没发生」：
- **只落一处钱事实**：明细进了采购单、却绕开后端那一个入口自己拼（或干脆只写单头）—— 库存没加、
  成本价没重算、供应商欠款没涨，而接口照样 200、卡片照样说「已保存」；
- **卡片说假话**：卡片承诺「库存 +N、成本价按这一单重算、供应商欠款 +合计」，实际一样没发生；
- **成本闸漏在整条动作外面**：进货价藏在 rows 文本里，顶层键那道闸（cost_price / unit_cost）
  看不见它 ⇒ 成本开关关着的人照样能建单、也能从卡片上看到钱；
- **撤单卡片捎带钱**：撤单本来不需要知道价钱，卡片上一写单价与合计，就等于把关着的成本漏出去；
- **参数名把编号机会交给模型**：参数一旦叫 order_id / driver_id，模型就会编一个编号，而编出来的
  编号一定落在某个真人头上（表里本来有那一行）；
- **行参数叫 items**：撞批量装饰器的保留字（BATCH_ITEMS）—— 一次批量回执会把整张单当成一行；
- **给货主开**：货主连 LEDGER_EDIT 都没有，开了也只会得到 403，用户却以为功能可用；
- **撤回走兜底那句**：「可以改 / 停用 / 删掉」对采购单是不准确的 —— 删掉会**一起**回滚库存与应付。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
这一条的红线都不是类型能表达的：「三处钱事实一起落」是**调用次序与唯一入口**（自己拼两处一样
编译得过、测试也照样绿）；「成本开关关着就不许读钱」是**卡片文案里有没有那几个字**（关着的人
看不到后台日志）；「参数里不许出现编号字段」是**参数表的名字**（改成 order_id 一样编译得过，
只有模型会因此编造编号）；「行参数不许叫 items」是**与批量装饰器的保留字冲突**（改了名字也不报错，
只有在批量回执里才变形）；「撤单卡片没有钱」是**卡片字符串的内容**；「AI 不写 inventory_movements」
是**一个方法名不许出现在某个函数体里**。所以判据只能钉在源码结构、唯一入口、次序、参数名与
卡片字面上，外加真机用一张真照片把整条路走一遍（重建库存 / 成本价 / 应付三处，再问 AI 查得到）。
反向破坏用例见 _reverse_verify_ai_purchase_orders.py。

## 判据（每条都能被反向验证弄红）
1. 四个动作登记一处（id 常量、组、要接进 AiWrites.ALL）、风险档与角色逐字，且这一域**只给派单员**；
2. 参数：行参数叫 rows（⛔ 不叫 items）、单号参数不叫 order_id、参数表里没有任何 xxx_id / id，
   单号允许写成「#12」/「采购单 12」；
3. 表格解析器：行号只在唯一一处补、上限引用 AiWriteArgs 那一处出处、认不出列就报错不猜、
   金额与数量的边界话术逐字；
4. 卡片：建单卡片写清「库存 +N / 成本价重算 / 供应商欠款 +合计」三件事、逐行列出、有行数上限；
   改单卡片说明「要改数量或单价请撤单重开」；**撤单卡片里没有单价与合计**；四张卡片没有 Markdown 粗体；
5. 成本闸：create 与 update 都在 COST_BUILT_ACTIONS 里、preview 里真的拦、话术与既有那条同一出处，
   而顶层键那道老闸一个字没改；
6. 撤回：purchase_order 资源整块（readKeys / labels / nullableWritable / paired 成对）、TABLE 收录、
   AiRevertRead.purchaseOrder 的空备注走 JsonNull；建单没有一键撤回但理由**专门**写且点名出路；
7. 数据源：五个方法（接口 ＋ 实现）、建单只调后端一个入口且不碰 inventory_movements、
   改单只改单头（items 故意不传）、快照走单取端点；
8. 覆盖表：四条写端点从 EXCLUDED 里移走、理由改成「起已开」，能力格认领「采购单」；
9. 文档 / 反验 / 防静默空转：变更单九节、登记簿、工作声明、反验脚本、关键文件、行数下限。

用法：python _tools/qa/_check_ai_purchase_orders.py
"""
import re
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
PURCH = AI / "AiWritePurchases.kt"
SVC = AI / "AiWriteService.kt"
SRC = AI / "AiWriteDataSource.kt"
RES = AI / "AiResources.kt"
REVERT = AI / "AiRevert.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"
APIS = AND / "data/remote/api/Apis.kt"

TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"
PROMPT_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWritePromptTest.kt"

BE_API = ROOT / "backend/app/api/v1/purchase_orders.py"
BE_SVC = ROOT / "backend/app/services/purchase_service.py"
BE_SCH = ROOT / "backend/app/schemas/purchase.py"

COVERAGE = ROOT / "_tools/ai/_app_feature_coverage.py"
WRITE_COVERAGE = ROOT / "_tools/ai/_write_coverage.py"
LEDGER = ROOT / "_tmp/USER_BUG_LEDGER_20261006.md"

CHG_ID = "CHG-0074"
CHG_DOC = ROOT / "docs/changes/CHG-0074.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_ai_purchase_orders.py"

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
MIN_PURCH_LINES = 600

#: 参数声明数下限（四个动作的参数表加起来）
MIN_PARAMS = 8

#: 必须真的数到这几个文件（少一个就说明目录结构变了，判据要跟着改）
REQUIRED_FILES = (
    AIWRITE,
    PURCH,
    SVC,
    SRC,
    RES,
    REVERT,
    DTOS,
    APIS,
    TEST,
    CHG_DOC,
    REGISTRY,
    CLAIM,
    BE_API,
    BE_SVC,
    BE_SCH,
)


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def code(p: Path) -> str:
    return strip_comments(read(p))


def subs(text: str, needle: str) -> int:
    """子串出现次数（故意用纯字符串：锚点里全是 ( ) . ? 这类正则元字符）。"""
    return text.count(needle)


def first(text: str, needle: str) -> int:
    """needle 首次出现的位置（取不到返回一个很大的数 —— 让「谁在前」的比较判红）。"""
    i = text.find(needle)
    return i if i >= 0 else 10 ** 9


def fn_body(src: str, sig: str) -> str:
    """sig 那段代码块的花括号体（按大括号配对，不是按行猜）。"""
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


def py_block(src: str, sig: str) -> str:
    """Python 顶层函数 / 类的那一段（从 sig 起到下一个顶层 def / @ / class 之前）。

    ⛔ 不能用 fn_body 抽 Python：owner: dict[int, int] = {} 里的那对花括号会被当成函数体。
    """
    i = src.find(sig)
    if i < 0:
        return ""
    m = re.search(r"\n(?=(def |@|class ))", src[i + len(sig) :])
    return src[i:] if not m else src[i : i + len(sig) + m.start()]


def paren_block(src: str, sig: str) -> str:
    """sig（以 ( 结尾）那段括号体（setOf( … ) / AiResource( … ) 这种，里面没有花括号）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    depth = 0
    for j in range(i + len(sig) - 1, len(src)):
        ch = src[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
    return ""


def decl_block(src: str, sig: str) -> str:
    """Kotlin 属性 / 表达式体声明的那一段（到下一个同缩进的 override 或顶层 } 为止）。

    ⛔ 不能用 fn_body 抽表达式体（= repo.xxx(...) 这种没有花括号），也⛔ 不能一路抽到文件尾。
    """
    i = src.find(sig)
    if i < 0:
        return ""
    ends = [x for x in (src.find("\n    override ", i + len(sig)), src.find("\n}", i + len(sig))) if x >= 0]
    return src[i : min(ends)] if ends else src[i:]


def card_literals(body: str) -> str:
    """一张卡片真正写给用户看的那些字：details += 那几行（含续行）+ store.card(...) 那一段。

    ⛔ 不能把整个 prepare / payload 都算进来：给模型看的参数话术允许 Markdown，payload 上面那几行
    注释里也带着 ** —— 扫全类会让这条红线被自己的话术 / 自己的注释弄红（第一次就是这么红的）。
    """
    lines = body.splitlines()
    picked = []
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("details +="):
            picked.append(lines[i])
            while lines[i].rstrip().endswith("+") and i + 1 < len(lines):
                i += 1
                picked.append(lines[i])
        i += 1
    return "\n".join(picked) + paren_block(body, "store.card(")


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
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")


def main() -> int:
    if refuse_if_injecting("AI 采购单写域判据"):
        return 0
    c = Checker()

    w = code(AIWRITE)
    p = read(PURCH)
    pc = code(PURCH)
    s = read(SVC)
    d = read(SRC)
    r = read(RES)
    rv = read(REVERT)
    cov = read(COVERAGE)
    wcov = read(WRITE_COVERAGE)

    print("== 1. 四个动作登记在一处，角色与风险档逐字 ==")
    c.ok("文件在（新域就是这一个文件）", PURCH.exists(), str(PURCH))
    c.ok(
        f"行数下限（>={MIN_PURCH_LINES}，防被截断后空转）",
        len(p.splitlines()) >= MIN_PURCH_LINES,
        f"实际 {len(p.splitlines())}",
    )
    c.ok(
        "四个动作 id 只在 AiWrites 里定义一处",
        all(
            x in w
            for x in (
                'PURCHASE_ORDERS_CREATE = "purchase_orders.create"',
                'PURCHASE_ORDERS_UPDATE = "purchase_orders.update"',
                'PURCHASE_ORDERS_DELETE = "purchase_orders.delete"',
                'PURCHASE_ORDERS_RESTORE = "purchase_orders.restore"',
            )
        ),
    )
    c.ok('「采购单」自己有组名（撤回卡分组要用）', 'const val G_PURCHASE = "采购单"' in w)
    c.ok("新域接进了 AiWrites.ALL（否则模型看不到、红线也会断）", "AiWritePurchases.ACTIONS" in w)
    c.ok(
        "三个手写的动作各自声明 id（字面 AiWrites.XXX）",
        subs(p, "override val actionId = AiWrites.PURCHASE_ORDERS_CREATE") == 1
        and subs(p, "override val actionId = AiWrites.PURCHASE_ORDERS_UPDATE") == 1
        and subs(p, "override val actionId = AiWrites.PURCHASE_ORDERS_DELETE") == 1,
        f"实际 {subs(p, 'override val actionId = AiWrites.PURCHASE_ORDERS_')} 处",
    )
    c.ok(
        "恢复动作走 restoreAction（undoOnly，不给模型看）",
        'restoreAction("采购单", AiWrites.PURCHASE_ORDERS_RESTORE, AiWrites.G_PURCHASE)' in p,
    )
    acts = paren_block(p, "val ACTIONS: List<AiWriteAction> = listOf(")
    c.ok("动作表抽得出来（4 个动作）", acts.count("AiWriteAction(") == 3 and "restoreAction(" in acts)
    c.ok("建单与撤单都是 HIGH 档（影响库存与应付）", subs(acts, "AiWriteRisk.HIGH") == 2)
    c.ok("改单头是 MEDIUM 档", subs(acts, "AiWriteRisk.MEDIUM") == 1)
    c.ok("三个动作都挂着同一个角色集合", subs(acts, "roles = ROLES") == 3)
    c.ok(
        "这一域只给派单员（货主连 LEDGER_EDIT 都没有）",
        "private val ROLES: Set<AiRole> = setOf(AiRole.DISPATCHER)" in p and "AiRole.SHIPPER" not in pc,
    )
    c.ok("角色集合在动作表之前就初始化了（先声明后用）", first(p, "private val ROLES: Set<AiRole>") < first(p, "val ACTIONS: List<AiWriteAction>"))
    c.ok("组名挂在三个动作上", subs(acts, "group = AiWrites.G_PURCHASE") == 3)

    print("== 2. 参数：行参数叫 rows，单号不许是编号字段 ==")
    names = re.findall(r'AiWriteParam\(\s*"([^"]+)"', p)
    c.ok(
        f"参数声明数下限（>={MIN_PARAMS}）",
        len(names) >= MIN_PARAMS,
        f"实际 {len(names)}：{'、'.join(names)}",
    )
    bad = [n for n in names if n.endswith("_id") or n == "id"]
    c.ok("参数里没有 xxx_id / id（模型只给名字，App 自己换编号）", not bad, "；".join(bad))
    c.ok("行参数就叫 rows（每个动作只有一个行参数）", names.count("rows") == 1, "；".join(names))
    c.ok(
        "进货单原文那个参数是必填的文本",
        '"rows",' in p and '"进货单原文"' in p and "required = true" in p,
    )
    c.ok(
        "行参数不叫 items（撞批量装饰器的保留字 BATCH_ITEMS）",
        '"items"' not in p,
        f"实际 {subs(p, chr(34) + 'items' + chr(34))} 处",
    )
    c.ok(
        "单号参数也不叫 order_id（改单与撤单各一个）",
        subs(p, '"order",') == 2 and '"采购单编号"' in p,
    )
    c.ok(
        "单号允许写成「#12」/「采购单 12」（数字自己挑出来）",
        "private fun purchaseOrderNo(raw: String): Int? =" in p
        and "raw.filter { it.isDigit() }.toIntOrNull()?.takeIf { it > 0 }" in p,
    )
    c.ok(
        "读不懂的单号要如实报（不许猜）",
        "请给我数字，例如「采购单 #12」" in p,
    )

    print("== 3. 表格解析器：行号、上限、不猜 ==")
    c.ok("解析器与行动作分家（同一个文件里）", "internal object AiPurchaseTable" in p)
    c.ok("按单元格拆（复用 AiTable，不自己写分隔符）", "val lines = AiTable.splitCells(text)" in p)
    c.ok(
        "行数上限是 30（话术里引用的也是同一个常量）",
        "const val MAX_ROWS = 30" in p and "行数据，超过一次 " in p and "行的上限。" in p,
    )
    c.ok(
        "金额与数量的上限只有一处出处（引用 AiWriteArgs）",
        "val MAX_PRICE: BigDecimal = AiWriteArgs.MAX_AMOUNT" in p
        and "val MAX_QUANTITY: Int = AiWriteArgs.MAX_QUANTITY" in p,
    )
    c.ok("金额一律两位小数（HALF_UP，全 App 一个口径）", "setScale(2, RoundingMode.HALF_UP)" in p)
    c.ok(
        "补行号只有一处（错误必须说清是第几行、原文是什么）",
        subs(p, "行读不出来：") == 1 and "那一行原文是「" in p,
    )
    c.ok("空表要如实报（不许当成 0 行建个空单）", "这张单子我一行内容都没读到。" in p)
    c.ok("只有表头也报（不许静默成空单）", "我只读到一行表头" in p)
    c.ok(
        "认不出列就报错、不猜（三个必需列各一条）",
        subs(p, "我认不出哪一列是") == 3 and "不要自己猜" in p,
    )
    c.ok("进货价必须大于 0", "进货价必须大于 0" in p)
    c.ok(
        "单价超上限时说清「超过多少」、并点出像多打了几个零",
        '，超过 " + MAX_PRICE.toPlainString() + " 的上限' in p and "像多打了几个零" in p,
    )
    c.ok("数量不许是 0 / 负数 / 小数", "不是正整数" in p)
    c.ok(
        "数量超上限时先让人核对",
        '，超过 " + MAX_QUANTITY + " 的上限，请先核对' in p,
    )
    c.ok("同一张单同一个商品只许一行", "出现了两次（上一次在第" in p)
    c.ok(
        "单据日期看不懂就报（空的按今天）",
        "我看不懂，请写成 2026-10-07 这样的格式。" in p and "LocalDate.now().toString()" in p,
    )

    print("== 4. 卡片：三件事写清、撤单卡片不写钱 ==")
    cb = fn_body(p, "class CreatePurchaseOrderHandler(")
    ub = fn_body(p, "class UpdatePurchaseOrderHandler(")
    db = fn_body(p, "class DeletePurchaseOrderHandler(")
    c.ok("三个处理器都抽得出来", bool(cb) and bool(ub) and bool(db))
    c.ok("建单卡片写清「保存之后」那一节", "———— 保存之后（三件事一起落）————" in cb)
    c.ok(
        "三件事逐条点名：库存 / 成本价 / 供应商欠款",
        "· 库存：" in cb
        and "· 成本价：这几个商品的成本价按这一单重算" in cb
        and "· 供应商欠款：" in cb
        and "」的应付 +" in cb,
    )
    c.ok("建单卡片逐行列货（商品 × 数量 × 单价 × 金额）", "———— 这一单要进的货 ————" in cb and "lineText(" in cb)
    c.ok(
        "卡片不无限长（逐行列到 12 行为止）",
        "MAX_LISTED" in cb and "const val MAX_LISTED = 12" in p,
    )
    c.ok("建单卡片写清供应商与单据日期", "供应商" in cb and "单据日期" in cb)
    c.ok(
        "建单完成后点名那条唯一的出路（撤掉采购单 #N）",
        "撤掉采购单 #" in cb,
    )
    c.ok(
        "改单卡片说明白：要改数量或单价，先撤单再重开",
        "要改数量或单价，请先撤单再重开一张" in ub,
    )
    c.ok("改单卡片逐项写「旧 → 新」", "旧" in ub and "→" in ub)
    c.ok(
        "撤单卡片里没有单价与合计（成本开关关着的人不该从卡片看到钱）",
        "moneyText(" not in db and "合计" not in db and "单价" not in db,
    )
    c.ok(
        "撤单卡片自己说明为什么不写钱",
        "卡片上不写" in db and "进货价只在成本开关打开时才进 AI 对话" in db,
    )
    c.ok("撤单卡片给了恢复的出路", "撤错了可以让我恢复它" in db)
    c.ok(
        "撤单卡片也写清三件事一起回滚",
        "———— 撤单之后（三件事一起回滚，后端同一个事务）————" in db,
    )
    card_text = card_literals(cb) + card_literals(ub) + card_literals(db)
    c.ok(
        "三张卡片的正文都抽得出来（details 的每一行 + summary 都在里面）",
        all(bool(card_literals(x)) for x in (cb, ub, db)) and "details +=" in card_text,
    )
    c.absent("卡片文案里没有 Markdown 粗体（卡片是纯文本渲染）", card_text, r"\*\*")
    # ⚠️ 这条是 2026-10-07 真机取证抓出来的：卡片上漏出过「系统按**商品档案上的单位**记」——
    # 那句话来自解析器的 ignoredNote()，会被 details 逐条搬上卡片，但字面量不在 store.card(...)
    # 那个括号块里，只扫卡片块扫不到（_check_ai_guardrails.py 的同类红线也是这么漏的）。
    notes_body = fn_body(p, "private fun ignoredNote(")
    notes_bold = [s for s in re.findall(r'"((?:[^"\\]|\\.)*)"', notes_body) if "**" in s]
    c.ok(
        "解析器写给用户的那几句说明也没有 Markdown 粗体（它们会逐条进卡片明细）",
        bool(notes_body) and not notes_bold,
        f"例如 {notes_bold[:1]}",
    )

    print("== 5. 成本闸：整条建立在成本上的动作也要拦 ==")
    c.ok(
        "整条建立在成本上的动作单独列着（create 与 update）",
        "private val COST_BUILT_ACTIONS: Set<String> = setOf(" in s,
    )
    m = re.search(r"COST_BUILT_ACTIONS: Set<String> = setOf\(([^)]*)\)", s)
    c.ok(
        "这个集合只装采购单那两个动作（别的动作不跟着被拦）",
        bool(m) and set(re.findall(r"AiWrites\.(\w+)", m.group(1))) == {"PURCHASE_ORDERS_CREATE", "PURCHASE_ORDERS_UPDATE"},
        (m.group(1).strip() if m else "抽不出来"),
    )
    c.ok(
        "preview 里真的拦（关着就直接拒）",
        "if (action.id in COST_BUILT_ACTIONS && !allowCost()) {" in s
        and 'costGateMessage("进货价")' in s,
    )
    c.ok(
        "话术与既有那条同一处出处（改一处就同时改两处）",
        "costFieldIn(params)?.let" in s
        and "允许 AI 查看成本与毛利" in s
        and "private fun costGateMessage(field: String): String =" in s,
    )
    c.ok(
        "顶层键那道老闸一个字没改（unit_cost / cost_price）",
        'private val COST_PARAMS = listOf("cost_price", "unit_cost")' in s,
    )
    c.ok(
        "三个手写处理器都注册了（否则模型调不到）",
        "CreatePurchaseOrderHandler(ds, store)," in s
        and "UpdatePurchaseOrderHandler(ds, store)," in s
        and "DeletePurchaseOrderHandler(ds, store)," in s,
    )
    c.ok(
        "接口上也声明了这五个方法（实现类才编译得过）",
        "suspend fun purchaseOrder(id: Long): PurchaseOrderDto?" in s
        and "suspend fun createPurchaseOrder(supplierId: Long, docDate: String, remark: String, lines: List<AiPurchaseLine>): Long" in s
        and "suspend fun updatePurchaseOrderHead(orderId: Long, supplierId: Long, docDate: String, remark: String)" in s
        and "suspend fun deletePurchaseOrder(id: Long)" in s
        and "suspend fun restorePurchaseOrder(id: Long)" in s,
    )

    print("== 6. 撤回：快照 / 成对恢复 / 建单那条专门的理由 ==")
    blk = paren_block(r, "private val PURCHASE_ORDER = AiResource(")
    c.ok("purchase_order 资源抽得出来", bool(blk))
    c.ok(
        "资源身份逐字（key / cn / idKey）",
        'key = "purchase_order"' in blk and 'cn = "采购单"' in blk and 'idKey = "order_id"' in blk,
    )
    c.ok(
        "快照读的就是单头三样（与改单动作同一份事实）",
        'readKeys = setOf("supplier_id", "doc_date", "remark")' in blk,
    )
    c.ok(
        "三样都有中文名（撤回卡不许出现裸键）",
        '"supplier_id" to "供应商"' in blk and '"doc_date" to "单据日期"' in blk and '"remark" to "备注"' in blk,
    )
    rk = re.search(r"readKeys = setOf\(([^)]*)\)", blk)
    lb = set(re.findall(r'"(\w+)" to "', blk))
    c.ok(
        "labels 与 readKeys 一一对应（有单测，这里也钉一次）",
        bool(rk) and set(re.findall(r'"(\w+)"', rk.group(1))) == lb,
        f"readKeys={sorted(set(re.findall(chr(34) + r'(\w+)' + chr(34), rk.group(1)))) if rk else '?'} labels={sorted(lb)}",
    )
    c.ok(
        "备注是「可以写回空值」的那一项（清空备注撤回时不说假话）",
        'nullableWritable = setOf("remark")' in blk,
    )
    c.ok(
        "三个动作：改 / 撤 / 成对恢复",
        "update(AiWrites.PURCHASE_ORDERS_UPDATE)" in blk
        and "delete(AiWrites.PURCHASE_ORDERS_DELETE)" in blk
        and "paired(" in blk
        and "AiWrites.PURCHASE_ORDERS_RESTORE," in blk
        and 'AiInverse(AiWrites.PURCHASE_ORDERS_DELETE, mapOf("order_id" to AiRevert.ID))' in blk
        and 'idKey = "target_id"' in blk,
    )
    c.ok(
        "读法走单取端点、恢复成对挂上",
        'read = { ds, id -> ds.snapshot("purchase_order", id) }' in blk
        and 'restore = AiInverse(AiWrites.PURCHASE_ORDERS_RESTORE, mapOf("target_id" to AiRevert.ID))' in blk,
    )
    c.ok("资源进了总表（否则撤回入口找不到它）", "SUPPLIER_PAYABLE, SUPPLIER_PAYMENT, PURCHASE_ORDER," in r)
    c.ok(
        "快照构造器在 AiRevertRead 里（键名就是 payload 键名）",
        "fun purchaseOrder(d: PurchaseOrderDto): JsonObject = buildJsonObject {" in r
        and 'put("supplier_id", d.supplierId)' in r
        and 'put("doc_date", d.docDate)' in r,
    )
    c.ok(
        "空备注用 JsonNull（不是空串：PATCH 传空串才清得掉）",
        'put("remark", if (d.remark.isBlank()) JsonNull else JsonPrimitive(d.remark))' in r,
    )
    c.ok(
        "建单没有一键撤回，理由单独写（不走兜底那句）",
        "listOf(AiWrites.PURCHASE_ORDERS_CREATE)," in rv,
    )
    c.ok(
        "理由里点名那条唯一的出路、也写清撤回会同时回滚三处",
        "撤掉采购单 #N" in rv and "逐行冲回" in rv and "供应商欠款要撤掉" in rv,
    )
    c.ok(
        "理由写在「一批」那一组里（与 products.apply_table 同族）",
        first(rv, "listOf(AiWrites.PURCHASE_ORDERS_CREATE),") < first(rv, "// ---- 状态锁定之后就回不去了 ----"),
    )

    print("== 7. 数据源：只调后端一个入口、不自己拼三处、改单只改单头 ==")
    crb = decl_block(d, "override suspend fun createPurchaseOrder(")
    upb = decl_block(d, "override suspend fun updatePurchaseOrderHead(")
    c.ok("五个实现都在", bool(crb) and bool(upb) and "override suspend fun deletePurchaseOrder(id: Long)" in d and "override suspend fun restorePurchaseOrder(id: Long)" in d)
    c.ok("单取走 GET /purchase-orders/{id}", "override suspend fun purchaseOrder(id: Long): PurchaseOrderDto? = repo.purchaseOrder(id)" in d)
    c.ok("建单只调后端这一个入口（一次调用落三处钱事实）", subs(crb, "repo.createPurchaseOrder(") == 1)
    c.ok(
        "AI 不写 inventory_movements（落库自然产生记录，AI 只负责读）",
        "createMovement" not in crb and "InventoryMovementCreateRequest" not in crb and "inventory_movements" not in crb,
    )
    c.ok(
        "建单请求体只有单头 + 明细（行里没有 id：改行一律撤单重开）",
        "PurchaseOrderCreateRequest(" in crb and "PurchaseItemRequest(productId = it.productId, quantity = it.quantity, unitCost = it.unitCost)" in crb,
    )
    c.ok("建单把新单号交回来（完成后要点名那条出路）", ".id" in crb)
    c.ok(
        "改单只改单头：items 故意不传",
        "items" not in upb
        and "PurchaseOrderUpdateRequest(supplierId = supplierId, docDate = docDate, remark = remark)" in upb,
    )
    c.ok(
        "快照分支能读到那一版（撤回卡的旧值有出处）",
        '"purchase_order" -> repo.purchaseOrder(id)?.let { AiBefore(id, AiRevertRead.purchaseOrder(it)) }' in d,
    )

    print("== 8. 覆盖表：四条写端点从「不做」里移走 ==")
    keys = (
        '("POST", "purchase-orders")',
        '("PATCH", "purchase-orders/{}")',
        '("DELETE", "purchase-orders/{}")',
        '("POST", "purchase-orders/{}/restore")',
    )
    c.ok("四条写端点都不在 EXCLUDED 里了", not any(k in wcov for k in keys), "；".join(k for k in keys if k in wcov))
    c.ok("理由改成了「起已开」的口径（留着旧理由就是化石）", "2026-10-07 CHG-0074（台账 L-42）起已开" in wcov)
    c.ok(
        "覆盖表写清了 AI 侧只调用、不写 inventory_movements",
        "inventory_movements" in wcov,
    )
    c.ok('能力格认领了「采购单」写域', '["库存", "采购单"],' in cov)
    c.ok('读能力仍然并到「库存管理」那一格', '["库存管理", "采购单"],' in cov)

    print("== 9. 文档 / 反验 / 防静默空转 ==")
    doc = read(CHG_DOC)
    c.ok(f"变更单在：docs/changes/{CHG_ID}.md", CHG_DOC.exists())
    for sec in CHG_SECTIONS:
        c.ok(f"变更单有这一节：{sec}", any(ln.startswith(sec) for ln in doc.splitlines()))
    c.ok("变更单引着口径 ref（m13365）", "m13365" in doc)
    c.ok("变更单引着台账那一条（L-42）", "L-42" in doc)
    c.present("这条判据自己写在变更单的判据段里", doc, r"_check_ai_purchase_orders\.py")
    c.ok(f"登记簿里有 {CHG_ID} 那一行（整行，不是一个链接里的字样）", f"[{CHG_ID}.md]({CHG_ID}.md)" in read(REGISTRY))
    c.ok(f"工作声明里有 {CHG_ID} 这一段", f"**{CHG_ID} " in read(CLAIM))
    c.ok("工作声明里记着用户原话的 ref（m01700）", "m01700" in read(CLAIM))
    c.ok(f"反向验证脚本在：{REVERSE}", (ROOT / REVERSE).exists())
    c.ok(
        "台账（本机）里那一条还是 L-42（不在 git 里，缺了不判红）",
        (not LEDGER.exists()) or "L-42" in read(LEDGER),
    )
    test_src = read(TEST)
    c.ok(
        "动作总数上限跟着抬了（并写明理由）",
        "动作数不该多于 159" in test_src and "CHG-0074" in test_src,
    )
    c.ok(
        "假实现跟着接口同步了（否则整个单测模块编译不过）",
        "override suspend fun createPurchaseOrder(" in test_src
        and 'if (resourceKey == "purchase_order")' in test_src,
    )
    c.ok(
        "说明书体积上限跟着抬了（并写明理由）",
        "上限 26000" in read(PROMPT_TEST) and "进货单照片" in read(PROMPT_TEST),
    )
    missing = [pth.relative_to(ROOT).as_posix() for pth in REQUIRED_FILES if not pth.exists()]
    c.ok(f"{len(REQUIRED_FILES)} 个关键文件都在", not missing, "；".join(missing))

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
