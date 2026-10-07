"""开放 AI 写域「我的下游价」：批发商给自己卖的商品定下游价（CHG-0084 / 台账 L-53）。

## 用户口径（2026-10-08，目标①）
「把『本轮不开放』的那 15~16 个写端点开给对应角色，并开下游定价两条读动作，保持不漏不越」。
这一域是那批里**唯一同时含读侧解封**的一组：三条写（设 / 删 / 恢复）＋ 两条读（可定价商品、
价目表）一起开，且只给**批发商货主自己的 AI**。

## 这一条为什么必须有机器的判据
这一域的毛病全是「没报错、但把承诺改小了」，编译器一条都拦不住：
- **把两层价混成一团**：派单员给他的专属价（price_rules）与他给下游的价（shipper_prices）
  在卡片上长得像同一件事，用户按卡片说「改成 8 块」时改错的是哪一本账，事后没人分得清；
- **漏了「历史订单永不追改」那句话**：改价 / 删价只在下单那一刻定格到订单行，卡片上不写，
  用户最怕的「我改个价，之前的账跟着变了」就没人回答；
- **删价卡片不说回落口径**：删掉一条价之后那一档按什么算（默认价 / 订单行单价）是后端写死的，
  卡片不写 = 用户要自己试一遍才知道；
- **「再设一次」其实是复活软删那一行**（后端 find_row 故意不过滤 is_deleted）：卡片说「新建一条」
  就是假话；
- **参数里出现编号字段**（product_id / price_id）：模型会照着编一个编号，而编出来的编号一定
  落在某个真人头上（表里本来有那一行）；
- **会员闸只留在清单里**：普通货主与批发商是同一个角色（shipper），角色门分不出来，只有当
  prepare 里真的问一次 isMemberShipper，才会拦住那张点了必然 403 的卡；
- **改价挂了一键撤回**：upsert（有就改、没有就建）在写之前不知道"该撤到哪一条"，挂上去的按钮
  要么撤错人、要么点了没反应 —— 只能走 UNDO_NONE 的显式文案；
- **给派单员开**：后端入参里没有 shipper_id、写的永远是 current.id ⇒ 派单员开了只能得到 403。

## 判据（每条都能被反向验证弄红）
1. 三条动作登记一处（id 常量 / 组 G_MY_PRICE / 接进 AiWrites.ALL / 进 SHIPPER_ACTIONS）；
2. 参数只有商品 / 下游联系人 / 单价三个名字，⛔ 没有 xxx_id，单价是 NUMBER；
3. 处理器：两条都先过会员闸、prepare 一个字都不写后端、commit 只认 payload、卡片没有 Markdown 粗体；
4. 卡片三句话：只影响以后新下的单、删价后的回落口径、再设一次是复活；
5. 数据源五个方法，写路径真的调到 repo 的三个方法（三跳链路的第三跳）；
6. 资源与撤回：只有删 / 恢复成对，改价那条进 UNDO_NONE 且理由点名出路；
7. 覆盖表：三条写端点从 EXCLUDED 移走、两条读端点从"不做"里移走、生成物里有它们；
8. 文档 / 单测 / 反验 / 防静默空转。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事

⚠️ 本判据**不替代**运行时证据，它只保证"承诺没被改小"。真正的证据是：
① 单测里走**真的** AiWriteService（预览 → 确认 → 写库 → 撤回，5 条）；
② 真实模型会话里把「给红富士苹果定个价 9.9」解析成三个参数（留待本批四单做完后的整体真机）。

为什么下沉不到代码边界：
- 后端那三条端点 2026-10-07 就存在且自洽（定价口径 / 回落口径 / 软删 / 复活 / 审计条件各有判据与单测），
  本单**一个字节都没改后端** ⇒ 边界那一层没有"新写错的代码"可拦。
- 会被改坏的东西全在**接线与话术**上：动作有没有进 ALL 与 SHIPPER_ACTIONS（决定模型看不看得见）、
  参数是不是只有三个名字（决定模型会不会自己编编号）、prepare 有没有偷写后端（决定"预览"是不是真的没动）、
  commit 是不是只认 payload（决定确认卡上那一次点击写的是不是用户看到的那一条）、
  卡片那几句话与后端语义对不对得上（决定用户会不会被骗）。这些写法在类型系统里**全都是合法的**。
- 静默空转保护：`read()` 对缺失文件返回空串，所以第 0 节先用"文件在：…"把清单钉住；
  卡片文案是用**引号感知的圆括号配平**抽出来的（不是"引号配对"），抽不出来时断言数会掉下去、直接红；
  结尾还有一条"判据自己数到了足够多的断言（>= 60 条）"。
- 反向破坏用例：`_tools/qa/_reverse_verify_ai_my_prices.py` **51 条注入**逐条让本判据变红并点名
  （id / 组名 / 从 ALL 摘掉 / 参数塞编号 / commit 越权取参 / prepare 偷写后端 / 卡片四句话 /
  资源 idKey / 恢复映射 / 三条端点塞回 EXCLUDED / 读目录改名 / 单测上界退回 159 …），
  逐条按字节还原，收尾还要求判据重新全绿。

用法：python _tools/qa/_check_ai_my_prices.py
"""
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
PRICES = AI / "AiWriteMyPrices.kt"
HANDLERS = AI / "AiWriteMyPriceHandlers.kt"
SVC = AI / "AiWriteService.kt"
SRC = AI / "AiWriteDataSource.kt"
RES = AI / "AiResources.kt"
REVERT = AI / "AiRevert.kt"
APIS = AND / "data/remote/api/Apis.kt"
REPO = AND / "data/repo/AppRepository.kt"
CATALOG = AI / "AiReadCatalog.kt"

TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"

WRITE_COVERAGE = ROOT / "_tools/ai/_write_coverage.py"
READ_COVERAGE = ROOT / "_tools/ai/_read_coverage.py"
GEN_CATALOG = ROOT / "_tools/ai/_gen_ai_read_catalog.py"

LEDGER = ROOT / "_tmp/USER_BUG_LEDGER_20261006.md"

CHG_ID = "CHG-0084"
CHG_DOC = ROOT / "docs/changes/CHG-0084.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_ai_my_prices.py"

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
MIN_HANDLER_LINES = 240
MIN_PRICES_LINES = 120
MIN_SVC_LINES = 1000
MIN_SRC_LINES = 2000
MIN_AIWRITE_LINES = 2500

#: 必须真的数到这几个文件（少一个就说明目录结构变了，判据要跟着改）
REQUIRED_FILES = (
    AIWRITE, PRICES, HANDLERS, SVC, SRC, RES, REVERT, APIS, REPO,
    TEST, CATALOG, CHG_DOC, REGISTRY, CLAIM, LEDGER, WRITE_COVERAGE, READ_COVERAGE, GEN_CATALOG,
)


def read(p: Path) -> str:
    """读文件；**读不到就返回空串**。

    缺文件由第 0 节「文件在：…」那一条报红。⛔ 绝不能在这里抛 FileNotFoundError：脚本一崩就
    没有 [FAIL] 行，反向验证的判据是「期望的检查名出现在 [FAIL] 行里」，崩了等于什么都能过。
    """
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


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


def strings_in(block: str) -> list:
    """块里所有双引号字符串（够用：这些卡片文案里没有转义双引号）。"""
    out = []
    for chunk in block.split('"')[1::2]:
        out.append(chunk)
    return out


def paren_block(src: str, sig: str) -> str:
    """从 sig 起按**圆括号**配平取整块。

    ⛔ 不能用 raw_block：`store.card(...)` 是调用、不是函数体，卡片里第一处 `{` 往往落在
    `${...}` 模板里，大括号配平当场配错，抽出来的块只有几十个字符 —— 那正是「判据空转」的样子：
    抽不到东西，`in` 一律为假，看着像文案缺失，其实是扫描器坏了。引号里的括号一律不计。
    """
    i = src.find(sig)
    if i < 0:
        return ""
    j = src.find("(", i)
    if j < 0:
        return ""
    depth = 0
    in_str = False
    k = j
    while k < len(src):
        ch = src[k]
        if in_str:
            if ch == "\\":
                k += 2
                continue
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return src[j:k + 1]
        k += 1
    return ""


def card_text(part: str) -> str:
    """把 store.card(...) 那一整块里的字符串字面量拼起来（卡片文案红线只扫这里）。"""
    picked = []
    idx = 0
    while True:
        idx = part.find("store.card(", idx)
        if idx < 0:
            break
        picked.append(paren_block(part[idx:], "store.card("))
        idx += 10
    return " | ".join(picked)


def const_text(src: str) -> str:
    """本文件里 `private const val` 那些**卡片片段常量**的字面量。

    卡片正文里有几句是常量（两张卡共用同一句，免得各说各的）；只扫 store.card(...) 里的字面量
    会把它们整句漏掉 —— 漏掉的后果是判据报「文案缺失」，而文案其实在。只认声明行：注释里的
    引号不会混进来（`**` 那条红线扫的是同一个集合，混进来会误报）。
    """
    lines = src.splitlines()
    out = []
    i = 0
    while i < len(lines):
        t = lines[i].strip()
        if t.startswith("private const val ") or t.startswith("private val "):
            buf = [lines[i]]
            # 声明换行写（`= ` 之后下一行才是字符串）时把续行一起吃掉：只要最后一行里
            # 还没有出现引号，或者整段引号还没配平，就继续往下吃（最多 6 行，防止吃穿文件）。
            while i + 1 < len(lines) and len(buf) < 6:
                joined = "\n".join(buf)
                if '"' in buf[-1] and joined.count('"') % 2 == 0:
                    break
                i += 1
                buf.append(lines[i])
            for line in buf:
                out.extend(strings_in(line))
        i += 1
    return " | ".join(out)


class Checker:
    def __init__(self) -> None:
        self.fails: list = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))

    def has(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle in text, "没找到 " + repr(needle))

    def hasnt(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle not in text, "命中：" + repr(needle))


def main() -> int:
    if refuse_if_injecting("AI 下游价写域判据"):
        return 0
    c = Checker()

    for p in REQUIRED_FILES:
        c.ok("文件在：" + str(p.relative_to(ROOT)), p.exists())

    w = read(AIWRITE)
    wc = code(AIWRITE)
    p = read(PRICES)
    pc = code(PRICES)
    h = read(HANDLERS)
    s = read(SVC)
    d = read(SRC)
    r = read(RES)
    rv = read(REVERT)
    t = read(TEST)
    wcov = read(WRITE_COVERAGE)
    rcov = read(READ_COVERAGE)
    gen = read(GEN_CATALOG)
    cat = read(CATALOG)

    print("== 1. 三条动作登记在一处，角色与风险档逐字 ==")
    c.ok(
        "行数下限（新域就是这一个文件）",
        len(p.splitlines()) >= MIN_PRICES_LINES,
        "实际 " + str(len(p.splitlines())),
    )
    c.ok(
        "三个动作 id 只在 AiWrites 里定义一处",
        all(
            x in wc
            for x in (
                'SHIPPER_PRICE_SET = "shipper_price.set"',
                'SHIPPER_PRICE_DELETE = "shipper_price.delete"',
                'SHIPPER_PRICE_RESTORE = "shipper_price.restore"',
            )
        ),
    )
    c.has("「我的下游价」自己有组名（与派单员给的专属价 G_PRICE 是两层价）", wc, 'const val G_MY_PRICE = "我的下游价"')
    c.has("新域接进了 AiWrites.ALL（否则模型看不到、红线也会断）", wc, "AiWriteMyPrices.ACTIONS")
    c.ok(
        "两条手写动作各自声明 id（字面 AiWrites.XXX）",
        subs(h, "override val actionId = AiWrites.SHIPPER_PRICE_SET") == 1
        and subs(h, "override val actionId = AiWrites.SHIPPER_PRICE_DELETE") == 1,
    )
    c.has("恢复动作走 restoreAction（undoOnly，不给模型看）", p, "id = AiWrites.SHIPPER_PRICE_RESTORE,")
    c.has("恢复动作真的调数据源的 restoreMyPrice", p, "call = { ds, id -> ds.restoreMyPrice(id) },")
    acts = part_of(p, "val ACTIONS: List<AiWriteAction> = listOf(", "data class AiMyPriceProduct")
    c.ok("动作表抽得出来（2 个 AiWriteAction ＋ 1 个 restoreAction）",
         subs(acts, "AiWriteAction(") == 2 and subs(acts, "restoreAction(") == 1)
    c.ok("两条都是 MEDIUM 档（写错了说一句就能改回去 / 删掉）", subs(acts, "AiWriteRisk.MEDIUM") == 2)
    c.ok("三条都标了 memberOnly（只有批发商货主有这本账）", subs(acts, "memberOnly = true") == 3)
    c.ok("组名挂在三条动作上（两条手写 ＋ 撤回那条 restoreAction）", subs(acts, "group = AiWrites.G_MY_PRICE") == 3)
    c.has(
        "三条都进了 SHIPPER_ACTIONS（allows() 是 preview 与 execute 共用的门）",
        wc,
        "        SHIPPER_PRICE_SET,\n        SHIPPER_PRICE_DELETE,\n        SHIPPER_PRICE_RESTORE,",
    )

    print("== 2. 参数：只有商品 / 下游联系人 / 单价三个名字，⛔ 没有 xxx_id ==")
    c.ok("商品参数两条动作各一个", subs(acts, 'name = "product"') == 2)
    c.ok("下游联系人参数两条动作各一个（留空 = 默认价那一档）", subs(acts, 'name = "contact"') == 2)
    c.ok("单价参数两条动作各一个（删价那条是选填，用来指认多条价）", subs(acts, 'name = "price"') == 2)
    c.ok("单价是 NUMBER（模型给的是数，不是随手一段文本）", 'kind = AiWriteParamKind.NUMBER' in acts)
    c.ok("必填参数三个（两条的商品 ＋ 定价的单价）", subs(acts, "required = true") == 3)
    c.ok(
        "⛔ 参数里没有 xxx_id / id（模型只给名字，App 自己换编号）",
        'name = "product_id"' not in acts and 'name = "price_id"' not in acts and 'name = "id"' not in acts,
    )
    c.ok("每个参数都有中文名与提示", subs(acts, "cn = ") >= 6 and subs(acts, "hint = ") >= 6)

    print("== 3. 两条处理器：会员闸 / prepare 不写后端 / commit 只认 payload ==")
    c.ok("行数下限（防被截断后空转）", len(h.splitlines()) >= MIN_HANDLER_LINES, "实际 " + str(len(h.splitlines())))
    c.has("定价处理器在", h, "class SetMyPriceHandler(")
    c.has("删价处理器在", h, "class DeleteMyPriceHandler(")
    c.ok("两条 prepare 里都问了一次会员身份（角色门分不出两种货主）", subs(h, "requireMemberShipper(ds)") == 2)
    c.has("会员闸真的读了 isMemberShipper（不是只写在注释里）", h, "if (!ds.isMemberShipper())")
    c.has("被拦下时给出路（怎么变成批发商货主）", h, "在「货主管理」里把你设成批发商")
    set_part = part_of(h, "class SetMyPriceHandler(", "class DeleteMyPriceHandler(")
    del_part = part_of(h, "class DeleteMyPriceHandler(", "// -------")
    set_prepare = raw_block(set_part, "override suspend fun prepare(params: JsonObject): AiWriteOutcome {")
    del_prepare = raw_block(del_part, "override suspend fun prepare(params: JsonObject): AiWriteOutcome {")
    c.ok("定价的 prepare 抽得出来", len(set_prepare) > 200)
    c.ok("删价的 prepare 抽得出来", len(del_prepare) > 200)
    c.ok(
        "⛔ prepare 里一个字都不许写后端（两条都只读）",
        "ds.setMyPrice(" not in set_prepare and "ds.deleteMyPrice(" not in del_prepare,
    )
    c.ok("定价的 prepare 先读回可定价商品", "ds.myPriceProducts()" in set_prepare)
    c.ok("定价的 prepare 连回收站一起读（后端是复活软删那行）", "ds.myPrices(includeDeleted = true)" in set_prepare)
    c.ok("删价的 prepare 只读没被删掉的行（回收站里那些再删一次会命中 0 行）", "ds.myPrices()" in del_prepare)
    c.has("commit 只认 payload 里的编号（定价）", h, "productId = payload.reqLong(\"product_id\")")
    c.has("commit 只认 payload 里的编号（删价）", h, "ds.deleteMyPrice(payload.reqLong(\"price_id\"))")
    c.has("下游联系人是可空编号（默认价那一档没有联系人）", h, 'payload["contact_id"]?.jsonPrimitive?.longOrNull')
    c.has("多条价时用单价指认（⛔ 不许替他挑一条）", h, "要删哪一条？说单价我就知道是哪条")
    c.has("「所有下游」「默认价」这一类说法不当人名册查", h, "private val ALL_DOWNSTREAM_WORDS: Set<String> = setOf(")
    c.has("价格比较走数字（后端可能下发 8.5000）", h, "private fun sameMoney(raw: String?, want: BigDecimal): Boolean")

    print("== 4. 卡片文案：只影响以后新下的单 / 回落口径 / 复活 ==")
    cards = card_text(set_part) + " | " + card_text(del_part) + " | " + const_text(h)
    c.ok("两张卡片抽得出来", len(cards) > 400, "实际 " + str(len(cards)))
    c.ok("卡片是纯文本渲染（没有 Markdown 粗体）", "**" not in cards and "__" not in cards)
    c.has("两张卡都写明「只影响以后新下的单」", cards, "只影响以后新下的单")
    c.has("两张卡都说清这本账是他自己的（公司那边不受影响）", cards, "公司（派单员）那边的账一个数字都不会变")
    c.has("定价卡如实说「再设一次是复活软删那一行」", cards, "复活")
    c.has("删价卡写明回落口径（默认价 / 订单行单价）", cards, "回落")
    c.has("删价卡说清后台是伪装删除、能放回来", cards, "伪装删除")

    print("== 5. 数据源五条，写路径真的落到 repo 的三个方法 ==")
    c.ok("行数下限（接口那一份）", len(s.splitlines()) >= MIN_SVC_LINES, "实际 " + str(len(s.splitlines())))
    c.ok("行数下限（实现那一份）", len(d.splitlines()) >= MIN_SRC_LINES, "实际 " + str(len(d.splitlines())))
    c.ok(
        "接口里五个方法都在",
        all(
            x in s
            for x in (
                "suspend fun myPriceProducts(): List<AiMyPriceProduct>",
                "suspend fun myPrices(includeDeleted: Boolean = false): List<AiMyPriceRef>",
                "suspend fun setMyPrice(productId: Long, contactId: Long?, unitPrice: String)",
                "suspend fun deleteMyPrice(id: Long)",
                "suspend fun restoreMyPrice(id: Long)",
            )
        ),
    )
    c.ok(
        "实现里五个方法各一处",
        all(
            subs(d, x) == 1
            for x in (
                "override suspend fun myPriceProducts(): List<AiMyPriceProduct>",
                "override suspend fun myPrices(includeDeleted: Boolean): List<AiMyPriceRef>",
                "override suspend fun setMyPrice(productId: Long, contactId: Long?, unitPrice: String)",
                "override suspend fun deleteMyPrice(id: Long)",
                "override suspend fun restoreMyPrice(id: Long)",
            )
        ),
    )
    c.ok("恢复那条是块体（表达式体编译不过：repo 的返回类型不是 Unit）",
         "override suspend fun restoreMyPrice(id: Long) {" in d)
    c.ok(
        "三跳链路的第三跳：写路径真的调到 repo 那三个方法",
        "repo.setShipperPrice(" in d and "repo.deleteShipperPrice(id)" in d and "repo.restoreShipperPrice(id)" in d,
    )
    c.ok(
        "读路径也走既有 repo 方法",
        "repo.priceableProducts()" in d and "repo.shipperPrices(null, null, includeDeleted)" in d,
    )
    c.ok("快照里有 shipper_price 分支（红线逐个资源对账，缺一个就红）", '"shipper_price" -> null' in d)
    c.ok("⛔ 入参里没有 shipper_id（写的永远是 current.id，派单员不代设）", "shipper_id" not in pc and "shipper_id" not in h)

    print("== 6. 资源与撤回：只有删 / 恢复成对，改价走 UNDO_NONE ==")
    c.has("资源块在 AiResources 里", r, "private val SHIPPER_PRICE = AiResource(")
    c.has("资源 idKey 是 price_id", r, 'idKey = "price_id",')
    c.has("读回字段三个（商品 / 下游联系人 / 单价）", r, 'readKeys = setOf("product_id", "contact_id", "unit_price"),')
    c.has("单价的键是钱（钱相关字段要按钱渲染）", r, 'moneyKeys = setOf("unit_price"),')
    res_block = part_of(r, "private val SHIPPER_PRICE = AiResource(", "/** 全部资源")
    c.ok("资源里有删除动作", "delete(AiWrites.SHIPPER_PRICE_DELETE)" in res_block)
    c.ok("删除与恢复是一对", "paired(" in res_block and "AiWrites.SHIPPER_PRICE_RESTORE" in res_block)
    c.ok("成对动作不读现场（撤回只用编号）", "read = { _, _ -> null }," in res_block)
    c.has("恢复动作的映射用的是恢复动作自己的参数名 target_id", res_block, 'AiInverse(AiWrites.SHIPPER_PRICE_RESTORE, mapOf("target_id" to AiRevert.ID))')
    c.has("恢复明细两句（放回来之后与删掉之前一模一样）", res_block, "放回来之后编号、商品、给谁、单价都和删掉之前一模一样")
    c.ok("⛔ 改价那条**不进**资源（upsert 在写之前不知道撤到哪一条）", "SHIPPER_PRICE_SET" not in r)
    c.has("资源收录进 TABLE", r, "        SHIPPER_PRICE,\n    )")
    c.has("改价那条在 UNDO_NONE 里有一条专门理由", rv, "listOf(AiWrites.SHIPPER_PRICE_SET),")
    c.has("理由里点名出路（说一句改回去 / 删掉）", rv, "把 XXX 的价改成 YYY")
    c.has("理由里点明删价那条有撤回按钮", rv, "删价是有「撤回」按钮的")
    c.has("先例那条（核销）还在（UNDO_NONE 的写法没被改坏）", rv, "listOf(AiWrites.MY_LEDGER_SETTLE),")

    print("== 7. 覆盖表与生成物：三条写端点开了、两条读端点不再写「不做」 ==")
    c.hasnt("POST /shipper-prices 不再挂在 EXCLUDED 里", wcov, '("POST", "shipper-prices")')
    c.hasnt("DELETE /shipper-prices/{id} 不再挂在 EXCLUDED 里", wcov, '("DELETE", "shipper-prices/{}")')
    c.hasnt("POST /shipper-prices/{id}/restore 不再挂在 EXCLUDED 里", wcov, '("POST", "shipper-prices/{}/restore")')
    c.has("覆盖表里留着这次改口径的来龙去脉（谁在什么时候开的）", wcov, "CHG-0084 开给 AI")
    c.hasnt("读覆盖表里那条「不做」的注释块已删", rcov, "shipper_prices.list_priceable_products")
    c.hasnt("读覆盖表里第二条「不做」也没了", rcov, "shipper_prices.list_shipper_prices")
    c.has("读目录生成器里有可定价商品的中文说明", gen, "shipper_prices.list_priceable_products")
    c.ok(
        "两条读动作都标了「只有批发商货主有」",
        '"shipper_prices.list_shipper_prices":' in gen and '"shipper_prices.list_priceable_products":' in gen,
    )
    c.ok(
        "生成物（Android 侧读动作目录）里两条都在",
        "shipper_prices.list_priceable_products" in cat and "shipper_prices.list_shipper_prices" in cat,
    )

    print("== 8. 单测 / 文书 / 反验 / 防静默空转 ==")
    c.ok("行数下限（AiWrite.kt）", len(w.splitlines()) >= MIN_AIWRITE_LINES, "实际 " + str(len(w.splitlines())))
    c.has("单测里有这一域的调用记录器（断言点确认之后真的写了一次）", t, "myPriceCalls")
    c.has("单测里有可定价商品的夹具", t, "var myPriceProductRows: MutableList<AiMyPriceProduct>")
    c.ok("单测摸到三条动作（>= 5 处）", subs(t, "SHIPPER_PRICE_") >= 5, "实际 " + str(subs(t, "SHIPPER_PRICE_")))
    c.has("动作数上界抬到了 165（每加一批动作都要抬一次）", t, "AiWrites.ALL.size <= 165")
    c.ok("变更单九节齐（少一节 _check_dev_spec.py 也会红）", all(x in read(CHG_DOC) for x in CHG_SECTIONS))
    c.has("变更单里写了台账号 L-53", read(CHG_DOC), "L-53")
    c.has("登记簿里有这一条", read(REGISTRY), CHG_ID)
    c.has("工作声明里有这一条", read(CLAIM), CHG_ID)
    c.has("台账里有 L-53 那一行", read(LEDGER), "L-53")
    c.ok("反向验证脚本在", (ROOT / REVERSE).exists(), REVERSE)
    c.ok("判据自己数到了足够多的断言（>= 60 条）", c.passes >= 60, "实际 " + str(c.passes))

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
