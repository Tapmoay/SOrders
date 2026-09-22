"""AI 助手的「红线」静态自检。

### 为什么需要这个脚本
AI 助手有几条性质**靠注释是守不住的**——它们不是"写的时候对"，而是"以后每次改都得还对"：
- 出参里不能出现内部编号（用户看不懂，模型拿到就会写进回答）；
- 工具集必须是**纯只读**的 5 个（多注册一个写工具，等于把改数据的口子开到聊天框里）；
- 最终答复必须过净化器（少接一处，编号就会漏出去）；
- 聊天历史必须有上限（否则手机存储被聊天记录撑爆）。

这些性质一旦被后续改动破坏，**功能测试是发现不了的**（要等到用户截图里出现 `user_id 122`才会暴露）。
所以做成断言，改坏了立刻红。

用法：python _check_ai_guardrails.py     # 全过 → 退出码 0
"""
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402

ROOT = repo_root()
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
UIAI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/ai"
UI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui"

# 只读工具白名单：多一个都算越界
ALLOWED_TOOLS = {
    "search_shipper", "inventory_alerts", "driver_performance",
    "shipper_performance", "export_sheet", "read_data",
}

# 唯一允许存在的「非只读」工具：它**只写本机记忆**，不碰后端一个字节。
# v3.6 新增。加它的理由见 AiTools.REMEMBER 的注释——首阶段红线防的是"改业务数据"，
# 而它改的是"AI 自己的笔记本"：写在 App 私有目录、用户能逐条看见/改/删、不出手机。
# ⚠️ 这个集合**只许有一个元素**：任何"能改业务数据"的工具都必须走方案 §2.5 的
# 风险分级 + 两段式确认，不许从这里开口子。
LOCAL_ONLY_TOOLS = {"remember"}

# v3.7 新增：唯一允许存在的「会改业务数据」的工具。
#
# ⚠️ 这不是给红线开的口子，是**把红线换成了更硬的一种**。
# 原来的红线是"物理上无写能力"——它靠"没有这条路径"来成立，代价是 AI 永远帮不上忙。
# 从用户视角看，那等于把「零摩擦」这个目标直接划掉（他仍然得自己去页面上一格格填表）。
# 现在改成：**写能力只有一条路径，而且那条路径的闸门在 App 侧的界面上**：
#   · 模型调 preview_write 只能**申请**，拿到的是「已把确认卡给用户了」；
#   · 真正落库的 AiWriteService.execute 只被聊天页的确认按钮调用；
#   · token 由 App 生成、从不进入提示词与工具返回值 → 模型没有任何可乘之机。
#   （反面教材：Operit 用 `!rawText.contains("deny_tool")` 判权限，模型改句话就绕过去了。）
# 下面 §2b 逐条断言这条路径**没有旁门**，比原来的"什么都没有"检查得更细。
GATED_WRITE_TOOLS = {"preview_write"}

# `AiWriteDataSource` 里的**读方法**白名单（其余一律当"写"，见 §2f-2b）。
#
# 为什么是"读的白名单"而不是"写的黑名单"：漏写一个读方法，后果是这条检查把那一次
# 读取当成写入报红——**吵但安全**；反过来漏写一个写方法，后果是"在 prepare 里写库"
# 这条最要命的 bug 从此无人拦——**安静且危险**。两边的代价不对称，所以往安全那边倒。
# 新增数据源方法时：读方法记得加进来，写方法什么都不用做（默认受约束）。
READ_METHODS = {
    # 名册
    "drivers", "vehicles", "searchShippers", "products", "arrearsUnits",
    "users", "addresses", "locations", "contacts", "priceRules",
    "freightTemplates", "customers", "members", "salaryDrivers",
    # 三张配置名册的列表读（2026-09-23）：`GET /expense-categories` / `GET /freight-categories` /
    # `GET /order-template-categories` 都是**读**（真正写库的是 create/update/delete/reorder
    # 那四个方法，它们不在白名单里，默认受"prepare 里不许写"的约束）。
    # ⚠️ 与 `productCategories` / `placeCategories` 是同一种情况：重排要整份名册、
    #    "改名/删除前报出影响面"也要先把名册读回来，所以它们**必须**能在 prepare 里调。
    "expenseCategories", "freightCategories", "orderTemplateCategories",
    # 预订单名册（2026-09-22）：改/删预设单之前要按**名字**把它读回来（`GET /order-templates`）。
    # 它是读 —— 真正写库的是 createOrderTemplate / updateOrderTemplate / deleteOrderTemplate
    # （那三个不在白名单里，默认受"prepare 里不许写"的约束）。
    "orderTemplates",
    # 供应商 / 厂商 + 应付款 + 付款记录（2026-09-22）：三个都是**读**。
    # ⚠️ `supplierPayables` 尤其重要：付款那张卡的**全部价值**就是预览时算出
    #    "这张单还差多少 → 付完还差多少"，而那两个数只有把应付单读回来才拿得到 ——
    #    判成"写"就只能把它挪出 prepare，那样卡片上印的会是"付款：永盛食品"这种
    #    用户核对不了的标题（而钱付出去撤不回来）。
    #    真正写库的是 createSupplier / updateSupplier / deleteSupplier / createSupplierPayable /
    #    updateSupplierPayable / deleteSupplierPayable / paySupplierPayable /
    #    cancelSupplierPayment / restoreSupplier*（那九个不在白名单里，默认受约束）。
    "suppliers", "supplierPayables", "supplierPayments",
    # 商品分类名册 / 商品可见范围（v3.43）：改分类、设白名单之前都要先把现状读回来
    "productCategories", "productVisibility",
    # 地点分组名册（2026-09-19）：**按人分区**的那一份，建/改/删/重排之前先读回来，
    # 也是"把某个地点归到哪一组"的候选来源。它是读（`GET /place-categories`）。
    "placeCategories",
    # 查单/查行/查流水/查消息（"先找到那一条"用的都是读）
    "findOrders", "orderLines", "findDeletedOrders", "ledgerEntries",
    "myNotifications", "productPrices", "priceRuleRows",
    # 司机账单与结算（生成/结算之前先看现状）
    "driverBills", "driverSettlements", "monthlyFreight",
    # 地理编码：查的是**高德**，不碰 SOrders 后端，所以是读（v3.24）
    "geocode",
    # 「当前位置」句柄（2026-09-21）：认的也是**本机定位 + 高德**，一个后端请求都不发。
    # ⚠️ 为什么必须在这一组里：`prepare` 里调它才拿得到真实地址与精确坐标（写进 payload 和卡片）；
    #    判成"写"就只能把它挪出 prepare —— 那样卡片上印的会是字面量「当前位置」，
    #    而司机导航到一个叫"当前位置"的地方（详见 `AiLocation`）。
    #    真正写库的是各动作自己的 commit（那一条完全不受影响）。
    "resolveAddress",
    # 共享地点（2026-09-20「补导航」用）：`places` 是那张全库共用的地点名册（`GET /places`），
    # `placeById` 是在它里面按编号取一条（拿坐标）。两个都是读 —— 补导航那个动作
    # **写**的是 `fillOrderNavigation`（不在白名单里，默认受"prepare 里不许写"的约束）。
    "places", "placeById",
    # 退货（2026-09-20）：发卡之前必须把"这一单每一行还能退几件"读回来
    # （`quantity − damage_quantity − returned_quantity`），所以它是读 ——
    # 真正写库的是 `returnOrder`（不在白名单里，默认受"prepare 里不许写"的约束）。
    "returnableLines",
    # 货主自己那一本账（2026-09-20）：核销/撤销之前先读回"这一单还欠多少、记过哪几笔"。
    # ⚠️ 这两个是**读**（`GET /orders` + `GET /shipper-ledger/settlements`）；
    #    真正写库的是 `createMySettlement` / `revokeMySettlement` / `restoreMySettlement`
    #    —— 那三个**不在**白名单里，默认受"prepare 里不许写"的约束。
    "mySettleOrder", "mySettlements",
    # 「这一次是谁在用」——`GET /users/me`，纯读（2026-09-20）。
    # ⚠️ 为什么要它：下单那条路**按角色分叉**（派单员代理下单要先查货主名册，
    #    货主是给自己下单、不查）。不把这句读放进白名单的话，"prepare 里不许写"
    #    这条会把它误报成写调用；而真按"写"处理，就只能把角色分叉挪走 ——
    #    那会让货主的 AI 下单重新去调 `GET /users`（对他是 403，实测过）。
    "currentRoleKey",
    # 「这一次是谁在用」的**编号**——同样只发 `GET /users/me`，纯读（2026-09-22）。
    # ⚠️ 为什么要它、为什么必须在 prepare 里读：**货主给自己下单**时后端不收 `shipper_id`，
    #    而专属价挂在**他本人**这个编号下（界面那条同源口径是 `subject = shipperId ?: myShipperId`）。
    #    不读它就只能按商品默认价报价 → 批发商自己下单时，他谈好的整套专属价被静默跳过。
    #    真正写库的一个都不在这里（下单是 `createOrder`，不在白名单里，默认受约束）。
    "currentUserId",
    # 退货申请（2026-09-21）：三个处理器都要在**发卡之前**把"这一单有没有待处理的申请"读回来
    # （`GET /return-requests?order_id=` / `GET /return-requests/mine`），判据与后端
    # "一张单同时只允许一条待处理申请"同源。它是**读**；
    # ⚠️ 为什么这一读是必需的、不是可选的优化：不读就会发一张**点了必然失败**的卡
    #    （申请`submit` 会以「已经有一张待处理的退货申请」拒绝），
    #    而 `orders.return` 那边不读则会漏掉"手工退 + 申请还挂着 = 同一批货退两遍"那个洞。
    #    真正写库的是 apply / withdraw / reject / fulfill 四个（都不在白名单里）。
    "myReturnRequests", "pendingReturnRequests",
}


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（是否被改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def string_literals(src: str) -> list[str]:
    """提取 Kotlin 源码里的字符串字面量内容（跳过注释）。

    用途单一：检查**用户会看到的文案**里有没有 Markdown 记号。
    所以不追求完整解析 Kotlin，只要不漏掉会渲染到屏幕上的那部分就够了。

    为什么需要它（v3.7 真机实测抓到的两个 bug）：设置页的工具说明和聊天页的确认卡
    都是普通 `Text()`，**不解析 Markdown**。文案里写 `**申请**`，屏幕上就原样显示
    `**申请**` ——两处都犯了，而单测、编译、红线全都没拦住（它们只管逻辑，不管字面量）。
    """
    out: list[str] = []
    buf: list[str] = []
    in_str = in_line = in_block = esc = False
    i = 0
    while i < len(src):
        ch = src[i]
        nxt = src[i + 1] if i + 1 < len(src) else ""
        if in_line:
            if ch == "\n":
                in_line = False
        elif in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 1
        elif in_str:
            if esc:
                buf.append(ch)
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
                out.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
        else:
            if ch == "/" and nxt == "/":
                in_line = True
                i += 1
            elif ch == "/" and nxt == "*":
                in_block = True
                i += 1
            elif ch == '"':
                in_str = True
        i += 1
    return out


def strip_comments(src: str) -> str:
    """把 Kotlin 源码里的注释**换成等长空格**（保留换行、保留字符串字面量）。

    为什么需要它：静态检查如果连注释一起看，就会出现两种坏情况——
    ① 假阳性：注释里引用了一句代码（"字段规格写的是 `key = "full_name"`"），检查把它当成真的；
    ② 假阴性：注释里写着一句本来该被拦住的代码，检查以为它存在（或反之）。
    换成空格而不是删掉，是为了**行号与列位置不变**，出错时还能指回原文件。
    """
    out = list(src)
    in_str = in_line = in_block = esc = False
    i = 0
    while i < len(src):
        ch = src[i]
        nxt = src[i + 1] if i + 1 < len(src) else ""
        if in_line:
            if ch == "\n":
                in_line = False
            else:
                out[i] = " "
        elif in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                out[i] = out[i + 1] = " "
                i += 1
            elif ch != "\n":
                out[i] = " "
        elif in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == "/" and nxt == "/":
                in_line = True
                out[i] = " "
                i += 1
                out[i] = " "
            elif ch == "/" and nxt == "*":
                in_block = True
                out[i] = " "
                i += 1
                out[i] = " "
            elif ch == '"':
                in_str = True
        i += 1
    return "".join(out)


def fn_body(text: str, signature: str) -> str:
    """取出一个顶层函数的源码块（从签名到第一个顶格的 `}`）。

    为什么需要它：同一个文件里既有「模型栏」也有「切换面板」，
    而这两处的视觉要求恰好相反（模型栏**不许**有底色、面板里选中行**必须**有底色）。
    不把断言限定到具体函数，就只能写出自相矛盾的检查，最后只能删掉。
    """
    i = text.find(signature)
    if i < 0:
        raise SystemExit(f"找不到函数：{signature}（改名了？本脚本的断言要跟着改）")
    j = text.find("\n}", i)
    return text[i:] if j < 0 else text[i:j]


def balanced_inside(src: str, i: int) -> str:
    """取 `src[i]`（一个 `(` / `{` / `[`）配对到的那段**内部文本**（不含首尾括号）。

    为什么不继续用正则找收尾：本脚本有两条检查栽在**同一个根因**上——
    "区间的边界靠正则猜写法"：
      · §2g-2b 的字段名认 `enumField("x"`（名字必须紧跟左括号），
        而实际代码里有 **11 处跨行写法**（`enumField(` 换行后再写名字）→ 全部落在盲区里；
      · §2e-③b 的卡片文案区间认 `\\n    },` 收尾，而实际有 **8 处单行 lambda**
        （`headline = { c -> "…" },`）→ 区间一路吃到**后面那块**去。
    括号配对对"写成几行"完全不敏感，这才是这两条检查真正想要的判据。

    ⚠️ 必须自己跳字符串：`strip_comments` 只清注释，**字符串字面量原样保留**，
    而文案里出现 `「」`/`（`/`}` 都很正常——不跳字符串的话，`"共 (3) 个"` 就能让配对提前结束。
    """
    pairs = {"(": ")", "{": "}", "[": "]"}
    if i >= len(src) or src[i] not in pairs:
        raise SystemExit(f"balanced_inside 的起点不是括号：{src[max(0, i - 40):i + 40]!r}")
    open_ch, close_ch = src[i], pairs[src[i]]
    depth = 0
    in_str = esc = False
    j = i
    while j < len(src):
        ch = src[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return src[i + 1:j]
        j += 1
    raise SystemExit(f"括号没配对到（源码被截断？）：{src[i:i + 80]!r}")


def bare_calls(src: str, call: str) -> list[str]:
    """把 `call(` 的每一次调用的**参数表内部文本**取出来（花括号配对，不认写法）。"""
    return [balanced_inside(src, m.end() - 1) for m in re.finditer(rf"\b{re.escape(call)}\(", src)]


def field_ctors() -> list[str]:
    """**算出来**的「构造一个字段规格的函数名」清单（不是手写的）。

    判据：`AiWrite*.kt` 里，参数表之后紧跟 `= AiFieldSpec(...)`（含跨行）的函数；
    再迭代一轮，把"转调另一个字段构造"的包装函数也收进来。

    为什么必须算：这张清单原来在 §2g-2b 里手写了 5 个名字，
    而 `AiWriteBasicData.positionField` **不在里面**——用它写的两个字段
    （改商品分类的"排到第几位"）从来没进过重名检查。
    手写清单的下场在本项目已经出现过 5 次（见 §2e-③c 的教训），这是第 6 次。
    """
    out = {"AiFieldSpec"}
    bodies: list[tuple[str, str]] = []
    for p in sorted(AI.glob("AiWrite*.kt")):
        src = strip_comments(read(p))
        for m in re.finditer(r"\bfun (\w+)\(", src):
            params = balanced_inside(src, m.end() - 1)
            after = src[m.end() - 1 + len(params) + 2:][:200]
            after = after.split("{")[0]          # 表达式体没有 `{`；遇到 `{` 就是块体，别往函数体里看
            bodies.append((m.group(1), after))
    for _ in range(3):                            # 包装函数（`= otherField(...)`）也要认出来
        grew = False
        for name, after in bodies:
            if name in out:
                continue
            if re.search(r"=\s*(?:\w+\.)?AiFieldSpec\(", after) or any(
                re.search(rf"=\s*{re.escape(k)}\(", after) for k in out
            ):
                out.add(name)
                grew = True
        if not grew:
            break
    return sorted(out)


def field_names(block: str) -> set[str]:
    """字段规格块里每个字段的**参数名**（构造函数的第一个字符串参数）。

    ⚠️ `\\(\\s*"` 里的 `\\s*` 是关键：它让**跨行写法**（名字写在下一行）也算数。
    这里少写一次 `\\s*`，11 个字段就整批消失，而检查照样全绿。
    """
    return set(re.findall(r"\b(?:" + "|".join(field_ctors()) + r')\(\s*"(\w+)"', block))


def md_lambda_files() -> list[str]:
    """**哪些文件里有声明式的卡片文案**（`headline = { }` / `details = { }`）——自己算。

    ⚠️ 这张清单原来是**手写的 3 个文件**。手写清单在本项目已经烂过 6 次
    （见 §2e-③c 的教训），所以这里连"要检查哪些文件"都不许手写：
    凡是出现 `\\n    <kind> = ` 的 `AiWrite*.kt` 都算，再加一条数量判据。
    （`AiWritePricing.kt` 就是这么暴露出来的：它在这个手写清单里，
    却一个 `headline/details` 都没有——那条断言过去三年一直在扫空集合并报 OK。）
    """
    return sorted(
        p.name for p in AI.glob("AiWrite*.kt")
        if re.search(r"\n\s+(?:headline|details) = ", read(p))
    )


def block_between(text: str, start: str, end: str) -> str:
    """取出 start 标记到下一个 end 标记之间的源码块。

    为什么要它：`Modules.kt` 里每个角色的工作台入口是一个 listOf(...)，不是函数，
    `fn_body`（找顶格 `}`）会把后面几个角色的入口一起吞进来——那样断言就分不清
    "货主有 AI 入口"和"司机也有"。少写一层限定，检查就会变成永远通过。
    """
    i = text.find(start)
    if i < 0:
        raise SystemExit(f"找不到块起点：{start}（改名了？本脚本的断言要跟着改）")
    j = text.find(end, i + len(start))
    if j < 0:
        raise SystemExit(f"找不到块终点：{end}（改名了？本脚本的断言要跟着改）")
    return text[i:j]


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

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")


def main() -> int:
    # 反向验证正在跑时**拒绝出结论**：那一刻源码树里带着注入的 bug，
    # 任何失败都可能与你的改动无关（实测踩到过，见 `_airepo.refuse_if_injecting`）。
    if refuse_if_injecting("红线检查"):
        return 1
    c = Checker()
    tools = read(AI / "AiTools.kt")
    loop = read(AI / "AiAgentLoop.kt")
    sanitizer = read(AI / "AiAnswerSanitizer.kt")
    conv = read(AI / "AiConversation.kt")
    store = read(AI / "AiConversationStore.kt")
    jsonstore = read(AI / "AiJsonStore.kt")   # 两个本地文件存储共用的唯一实现（2026-09-21 收口）
    md = read(AI / "AiMarkdown.kt")
    client = read(AI / "LlmClient.kt")
    keystore = read(AI / "AiKeyStore.kt")
    vm = read(UIAI / "AiChatViewModel.kt")
    screen = read(UIAI / "AiChatScreen.kt")
    settings = read(UIAI / "AiSettingsScreen.kt")
    settings_vm = read(UIAI / "AiSettingsViewModel.kt")
    AI_join = lambda name: read(AI / name)  # noqa: E731

    print("\n== 1. 工具出参里不能有内部编号 ==")
    shaper = read(AI / "AiRowShaper.kt")
    c.absent("AiTools 出参不含 *_id 字段", tools, r'put\(\s*"[a-z_]*_id"')
    # 加工工序已经统一到 AiRowShaper（单一出处）；AiTools 只许转发，不许自己再实现一份
    c.present("isHiddenField 里确实拦了 _id", shaper, r'k\.endsWith\("_id"\)')
    c.present("名字缺失时回落成中性称呼而不是编号", shaper, r'const val UNNAMED')
    c.present("通用读工具也走同一套加工（Shape 是唯一出口）", AI_join("AiReadService.kt"), r"AiRowShaper\.shape\(")
    c.absent("AiTools 里不许再抄一份剔字段的逻辑", tools, r"private fun stripSensitive\(")
    c.ok(
        "工具体系只有一个变量入口（AiRowShaper）",
        len(re.findall(r"fun shape\(", shaper)) == 1,
        "AiRowShaper 里应当只有一处 shape()",
    )
    # 行数组的判据必须是**机器认**，不能只认一张手写键名表（2026-09-19 审计）：
    # 只认表的话 `{"drivers": […179 行…]}` / `{"groups": […175 组…]}` 整包认不出，
    # 会退化成 `drivers_count: 179` —— 模型拿到"有 179 个司机"而不是那 179 行，且**没有任何标志**。
    # ⚠️ 钉**接线**而不是"函数存在"（2026-09-19 反向验证自己抓出来的恒真判据）：
    #    第一版只断言 `private fun firstObjectArray(` 出现过，于是把调用点去掉之后判据照样绿
    #    —— 函数还在、兜底没了。
    c.present("行数组有「任意对象数组」兜底，且真的接在 rowsOf 上（不再只认手写键名表）",
              shaper, r"knownRows\(root\) \?: firstObjectArray\(root\)")
    c.present("兜底只认「元素全是对象」的数组（纯标量数组不算行数据）",
              shaper, r"it\.size == arr\.size")

    print("\n== 2. 工具集必须纯只读（白名单精确匹配）==")
    m = re.search(r"val ALL = listOf\((.*?)\)\s*\n", tools, re.S)
    if m is None:
        c.ok("能定位到 ALL 工具清单", False, "正则没匹配到 `val ALL = listOf(`")
    else:
        names = set(re.findall(r"\b([A-Z_]{3,})\b", m.group(1)))
        # 这一块里用的是常量名（SEARCH_SHIPPER 等），换算成字符串值再比
        consts = dict(re.findall(r'const val ([A-Z_]+) = "([a-z_]+)"', tools))
        resolved = {consts.get(n, n) for n in names}
        c.ok(
            "工具集 = 6 个只读 + 至多 1 个「只写本机」 + 至多 1 个「受控写数据」，没有别的",
            resolved == ALLOWED_TOOLS | LOCAL_ONLY_TOOLS | GATED_WRITE_TOOLS,
            f"实际={sorted(resolved)}",
        )
        c.ok(
            "「只写本机」的工具只许有一个（多一个都要走两段式确认，见方案 §2.5）",
            len(LOCAL_ONLY_TOOLS) <= 1,
            f"实际={sorted(LOCAL_ONLY_TOOLS)}",
        )
        c.ok(
            "「受控写数据」的工具只许有一个（写入口越少越好审）",
            len(GATED_WRITE_TOOLS) <= 1,
            f"实际={sorted(GATED_WRITE_TOOLS)}",
        )

    print("\n== 2a. 「只写本机」工具的红线（它只能碰记忆文件，不许碰后端）==")
    c.present("remember 走的是本机记忆写入，不是 HTTP", tools, r"REMEMBER -> remember\(args\)")
    c.present("它的落点是一个回调（装配层决定写哪儿，工具层无法自作主张）", tools, r"rememberFact: suspend \(subject: String, fact: String\) -> String\?")
    c.absent("它不许出现在只读目录里（出现就等于有了一个能带编号的通道）", AI_join("AiReadCatalog.kt"), r"remember")
    c.present(
        "只在用户明确要求时才许调用（抗膨胀第一道闸）",
        tools,
        r"只在用户明确说了",
    )
    c.present("严禁自己判断「有用」就记（否则库会被模型塞满）", tools, r"严禁自己判断")
    c.present("严禁把查得到的结果存进去（金额/单量会过期）", tools, r"严禁把金额、单量、订单号、库存数")
    c.present("写入失败必须如实说没记住，不许假装", tools, r"不要假装记住了")
    c.present("长度上限在工具层就拦（超长要报错让它压缩，不是默默截断）", tools, r"fact 太长了")

    # ⚠️ 这一组来自一次**真机实测抓到的 bug**：提醒词里原本写着「你只有只读能力」，
    # 结果用户说「记住…」时，模型引用那句话**拒绝了**，回答"我没有写入/记忆的能力"。
    # 光加工具不够——提示词不把"业务数据只读"和"本机记忆可写"分开，模型就会自己判定不能写。
    # 这类问题单测发现不了（它只测逻辑），只有真机跑一遍才会暴露。
    c.present("提示词把「业务数据你只能申请」说清楚（不是笼统的「只能读」）", loop, r"\*\*业务数据你能改，但只能「申请」\*\*")
    c.present("提示词明确告诉它「记忆是你能直接写的」", loop, r"另有一件事你能\*\*直接\*\*写")
    c.present("提示词告诉它写操作只是「申请」，不许说已经办好", loop, r"永远不要说「已经改好了」")
    # v3.9：动作涨到 27 个之后，提示词里**逐个列能力**必然过期（这一轮就过期了一次）。
    # 所以改成"以工具清单为唯一依据"，并明确要求它对清单外的操作如实说做不到。
    c.present("提示词把「能做哪些操作」指向工具清单，而不是自己列一份", loop, r"以 `preview_write` 的 action 参数说明为唯一依据")
    c.present("提示词要求它：清单里没有的就是做不了，不许假装", loop, r"清单里\*\*没有\*\*的操作就是做不了")
    c.present("提示词列出永远不做的三类（凭据/上传/司机端）", loop, r"登录/注册（凭据不归你管）")
    c.present("提示词里的成本能力**跟着开关变**（写死成「没权限」会让用户以为开关坏了）",
              loop, r"if \(tools\.allowCost\)")
    c.present("开关关着时提示词给出**怎么打开**的路径", loop, r"允许 AI 查看成本与毛利")
    # v3.11：模型凭对话历史里的「我发过卡」拒绝重发，而卡是**内存态**（几分钟/重启即失效）
    # → 用户被指着一张不存在的卡，卡死。实测踩过两次。
    # 规矩改成：每次都申请，去重交给系统（AiWritePreviewStore.offer 会复用同一张卡）。
    c.present("提示词要求「每次要求都申请一次」，不凭记忆判断发没发过", loop, r"每次用户要求做某件事，你就申请一次")
    c.present("并且写明「重复申请是安全的，系统会自动复用同一张卡」", loop, r"系统会自动复用同一张卡")
    # 这一条是 2026-09-15 用户口径的直接落地：「他可以询问用户……他不能随随便便做决定」。
    # 光有确认卡不够——卡片只能拦住"模型想做但用户看出来了"，
    # 拦不住"模型自己挑了一个派单对象、然后拿一张看起来很合理的卡让用户点"。
    c.present("提示词明确要求「不知道就去问、绝不许替他决定」", loop, r"绝不许替他决定")
    c.present("并且点名了最容易猜错的那几样（派给谁/哪一单/什么货/多少钱）", loop, r"派给谁、操作哪一单")
    c.present("提示词要求它别主动记（抗膨胀的第二道闸）", loop, r"用户没让你记时\*\*不要主动记\*\*")

    # ⚠️ 又一组来自真机实测的静默失效：工具加了、提示词也写了，但**没进默认启用集**，
    # 于是模型说"我这个会话没有开启记忆工具"——功能装了却毫无反应，而用户不知道为什么。
    # 这类问题任何单测都发现不了（逻辑全对），只有真跑一遍才暴露。
    ks = AI_join("AiKeyStore.kt")
    c.present("新工具必须进「默认启用」集（否则等于没加）", ks, r"val DEFAULT_ENABLED_TOOLS: Set<String> = linkedSetOf\(")
    c.present("默认启用集包含 remember", ks, r"AiTools\.REMEMBER,")
    c.present(
        "「上次保存后新增的工具」按默认开处理（老用户升级后新功能不能静默失效）",
        ks,
        r"brandNew = DEFAULT_ENABLED_TOOLS - seen - optInExclusion\(role\)",
    )
    c.present("保存时刷新「见过的工具」清单", ks, r"KEY_TOOLS_SEEN, DEFAULT_ENABLED_TOOLS\.joinToString")

    # ---- 2c-1 工具开关的读路径不许写盘（2026-09-21 修的静默丢能力）----
    #
    # `enabledTools()` 原来在**读**的时候顺手 `markToolsSeen()` 把"见过的清单"刷成当前全集：
    # 新加的工具**只有第一次读是开的**，第二次读就算出"没有新工具"→ 又变回关的。
    # 静默、不报错、日志里什么都没有 —— 而用户这一轮的原话正是
    # 「ai 它是要具备**所有功能**」，那个 bug 恰好让 AI 悄悄丢能力。
    # 判据两条：① 读路径那一段里**不许出现任何写盘**；② 合并规则收成一处纯函数（它也不写盘）。
    c.absent(
        "工具开关的读路径不许写盘（这就是「新加的工具过一会儿自己变回关的」的根因）",
        block_between(ks, "fun enabledTools(", "fun saveEnabledTools("),
        r"prefs\.edit\(|markToolsSeen\(",
    )
    c.present("白名单的合并规则收成一处纯函数（只读、可单测）",
              ks, r"fun resolveEnabledTools\(saved: Set<String>, seenAtSave: Set<String>\?, role: AiRole\?\)")
    c.present("读侧走那条纯函数（而不是在 enabledTools 里再算一遍）", ks, r"return resolveEnabledTools\(")
    c.present(
        "旧数据（认不出他见过什么）按「他都见过」算，不把他明确关掉的又打开",
        ks,
        r"val seen = seenAtSave \?: DEFAULT_ENABLED_TOOLS",
    )

    # ============================================================== 2b/2e 写操作
    print("\n== 2d. 写数据：模型只能申请，落库必须由用户在界面上点 ==")
    wr = AI_join("AiWrite.kt")
    wsvc = AI_join("AiWriteService.kt")
    wargs = AI_join("AiWriteArgs.kt")
    wbasic = AI_join("AiWriteBasicHandlers.kt")
    worder = AI_join("AiWriteOrderHandlers.kt")
    vm = AI_join("../ui/ai/AiChatViewModel.kt")
    screen = AI_join("../ui/ai/AiChatScreen.kt")

    # ---- 2d-1 模型侧没有执行路径（这是整套设计的承重点）----
    # 不是"我们约定了模型不许执行"，是"从模型出发的调用链里根本没有那个函数"。
    # 一旦有人在 AiTools 里补一个 execute 分支（"顺手把确认也做了"），这里必须红。
    c.absent("工具层不许出现任何执行写操作的调用", tools, r"writeService\.execute|\.execute\(token")
    c.present("工具层拿到的只是一个「申请」回调", tools, r"requestWrite: suspend \(String, JsonObject\) -> AiWriteOutcome")
    c.present("申请完之后明确告诉模型「你什么都还没写成」", tools, r"awaiting_user_confirmation")
    c.present("并且禁止它说「已经记好了」", tools, r"不要跟用户说「已经记好了」")

    # ---- 2d-2 执行入口只在界面上 ----
    c.present("聊天页有确认按钮（真正落库的触发点）", screen, r"onConfirm = \{ vm\.confirmWrite\(it\) \}")
    c.present("确认卡钉在输入框上方（不会被长对话划过去）", screen, r"WriteConfirmCard\(")
    c.present("ViewModel 里的确认入口会调 execute", vm, r"ai\.writeService\.execute\(token\)")
    c.present("确认卡上写的是动作本身，不是没信息量的「确定」", screen, r'"确认：" \+ p\.title')

    # ---- 2d-3 一次性 + 去重（连点两下不许写两笔）----
    c.present("暂存区的取用是「取走并删除」", wr, r"fun take\(token: String\): AiPendingWrite\?")
    c.present("参数完全相同的重复申请复用同一张卡（消灭重复写入路径）", wr, r"it\.actionId == actionId && it\.payload == payload")
    c.present("确认卡有过期时间", wr, r"const val DEFAULT_TTL_MS")

    # ---- 2d-4 token 与 payload：模型碰不到 ----
    c.present("token 由 App 生成", wr, r"private fun randomToken\(\): String")
    c.present(
        "token 绝不进工具返回值（模型拿不到就没有可乘之机）",
        tools,
        r'put\("status", CARD_OFFERED_STATUS\)\s*\n\s*put\("summary", out\.pending\.summary\)',
    )
    # ⚠️ 比上面那条更狠：直接把 pending 的**任何**字段读出来都可能带出 token，
    #    所以工具层只允许读 summary（卡片的标题行），不许碰 pending.token。
    c.absent("工具层不许读 pending 的 token", tools, r"pending\.token")
    c.absent("工具返回值里不许出现 token", tools, r'put\("token"')
    c.present("payload 在预览时就拼好，确认后原样发出（卡片=实际写入）", wr, r"val payload: JsonObject")

    # ---- 2d-5 风险分级：只有 LOW 能自动执行 ----
    c.present("有风险档位", wr, r"enum class AiWriteRisk")
    c.present("只有 LOW 允许自动执行", wr, r"val AUTO_EXECUTABLE: AiWriteRisk = LOW")
    c.present("自动执行的判据写在代码里（不是靠注释记得小心）", wr, r"val autoExecutable: List<String>")

    # ---- 2d-6 严格解析：名字对不上/对上多个都不许猜 ----
    # v3.8 起这些规则搬到了 AiWriteArgs.kt（所有动作共用的**唯一**一份），
    # 断言跟着搬——留在原地会变成"检查一个已经不存在的实现"。
    args = AI_join("AiWriteArgs.kt")
    c.present("查不到就拒绝（默认），不静默丢参数", args, r"allowMissing: Boolean = false")
    c.present("只有货主允许「查不到」→ 按临时客户记", wbasic, r"allowMissing = true")
    c.absent("司机/车辆不许允许「查不到」（丢一个参数就是把账记错人）", wbasic, r'"(driver|vehicle)"\)\?\.let \{\s*AiWriteArgs\.strict\([^)]*allowMissing')
    c.present("对上多个一律拒绝，绝不自己挑一个", args, r"不要自己挑一个")
    c.present("先精确匹配再前缀匹配（顺序反了会让说清楚的人被要求消歧义）", args, r"val exact = pool\.filter")

    # ---- 2d-7 金额闸门（防"多打了三个零"）----
    c.present("金额有上限", args, r'val MAX_AMOUNT: BigDecimal = BigDecimal\("1000000"\)')
    c.present("超上限的报错明确说「像多打了几个零」", args, r"像多打了几个零")
    c.present(
        "金额校验只有一处实现（各动作各写一遍＝迟早有一个忘了上限）",
        wbasic,
        r"AiWriteArgs\.parseMoney\(",
    )
    for rel in ("AiWriteBasicHandlers.kt", "AiWriteOrderHandlers.kt"):
        c.absent(f"{rel} 里没有自己再写一遍金额上限", read(AI / rel), r'"1000000"')

    # ---- 2d-8 默认值：**按角色**（2026-09-20 用户改的口径）----
    #
    # 用户原话：「**派单员所有 AI 功能全都是默认开启**」。
    # 所以原来那两条"一律默认关"的判据换成了按角色的判据，而**安全边界没变**：
    #   · 写工具仍然只能通过 `preview_write` **申请**，落库要用户点确认卡；
    #   · 非派单员（货主）仍然默认关——他升级后不该凭空多出一个会记账的 AI；
    #   · 开关仍然在设置页里，随时能关。
    c.present("写工具仍然走「主动申请」这一档（不是直接执行）", ks,
              r"val OPT_IN_TOOLS: Set<String> = setOf\(AiTools\.PREVIEW_WRITE\)")
    c.present("非派单员首装时写工具仍然是关的",
              ks, r"else DEFAULT_ENABLED_TOOLS - OPT_IN_TOOLS")
    c.present("**派单员首装全开**（用户 2026-09-20：「派单员所有 AI 功能全都是默认开启」）",
              ks, r"if \(role == AiRole\.DISPATCHER\) DEFAULT_ENABLED_TOOLS")
    c.present("「新增默认开」这条规矩：非派单员把写工具排除在外",
              ks, r"DEFAULT_ENABLED_TOOLS - seen - optInExclusion\(role\)")
    c.present("派单员对新增工具也不排除（否则新加的写动作对他装了没用）",
              ks, r"if \(role == AiRole\.DISPATCHER\) emptySet\(\) else OPT_IN_TOOLS")
    c.present("两个调用点都把角色传进去了（默认值按角色，不能只在一处生效）",
              read(AI / "AiContainer.kt") + read(UI / "ai/AiSettingsViewModel.kt"),
              r"enabledTools\(role\(\)\)|enabledTools\(ai\.currentRole\)")
    c.present("但它必须在默认集里（否则用户按了开关也不生效）", ks, r"AiTools\.PREVIEW_WRITE,")

    # ---- 2d-9 设置页要把「哪些会改数据」摊开 ----
    c.present("工具按查询/操作分栏", tools, r"enum class Group\(val label: String, val hint: String\)")
    c.present("操作类那一栏有独立说明", tools, r'OPERATE\("操作类"')
    # ⚠️ 这里原来钉的是**一整句话**（`真正写进系统必须由你在卡片上点「确认」`），
    #    所以 2026-09-17 把设置页文案精简掉一半时它就红了——而那句话的**意思一个字没变**。
    #    改成钉**不变量**：确认这一步必须存在、而且是用户点出来的。
    #    同时钉两处（能力摘要 + 抽屉里操作类那段），因为它们分别在两个地方承载这个承诺。
    settings = AI_join("../ui/ai/AiSettingsScreen.kt")
    roleprompt = read(AI / "AiRolePrompt.kt")
    c.present("能力摘要里写明「改」要用户点确认", roleprompt, r"你点「确认」才会写进系统")
    c.present("抽屉里「操作类」也写明只发确认卡", settings, r"AI 也只是把一张确认卡发到聊天页，写进系统要你点「确认」")

    # ---- 2d-10 界面文案不许写 Markdown ----
    # 这一组来自 v3.7 真机实测抓到的两个 bug：设置页的工具说明和聊天页的确认卡
    # 都写了 `**申请**`，而两处都是普通 Text()，屏幕上原样显示了一堆星号。
    # 编译、单测、其它红线全都拦不住（它们管逻辑，不管字面量），只有真机看得见。
    #
    # ⚠️ 判据必须**只覆盖会渲染到屏幕上的字符串**，不能按文件一刀切：
    # AiTools.kt / AiWrite.kt 里绝大多数文案是**给模型看的**（工具描述、报错话术），
    # 那里 `**` 是有意义的——模型读 Markdown 没问题，加粗还能提高它照做的概率。
    # 一刀切会逼着以后把模型侧文案也写平，那是拿错换错。
    print("\n== 2e. 界面文案不许写 Markdown（普通 Text 不渲染，会原样显示星号）==")

    def no_md(label: str, src: str) -> None:
        bad = [s for s in string_literals(src) if "**" in s or "__" in s]
        c.ok(label, not bad, f"例如 {bad[:1]}")

    # ① 纯界面文件：整份都不该出现 Markdown
    for rel in ("../ui/ai/AiChatScreen.kt", "../ui/ai/AiSettingsScreen.kt", "../ui/ai/AiSettingsViewModel.kt"):
        no_md(f"{rel.split('/')[-1]} 的文案里没有 Markdown 记号", read(AI / rel))

    # ①b **所有 Compose 界面文件**（清单自己算，不手写）。
    #    2026-09-19 审计 R13-R1 又栽了一次同一类：报表页的毛利说明写成了
    #    `**不进毛利**`，真机截图上原样印着一堆星号——而上面那三条只管 AI 那几个文件。
    #    UI 层的 `Text()` 一律不渲染 Markdown，所以这一整层的字符串都不许带 `**` / `__`。
    #    （`ui/` 之下不会出现"给模型看的文案"，所以这里可以按目录一刀切。）
    ui_files = sorted((AI / "../ui").rglob("*.kt"))
    c.ok("扫到的 Compose 界面文件不少于 20 个（太少说明清单过期）", len(ui_files) >= 20, f"实际 {len(ui_files)}")
    ui_bad: list[str] = []
    for f in ui_files:
        src = read(f)
        for s in string_literals(strip_comments(src)):
            if "**" in s or "__" in s:
                ui_bad.append(f"{f.name}: {s[:40]}")
    c.ok("界面层（ui/**）的文案里没有 Markdown 记号", not ui_bad, f"例如 {ui_bad[:2]}")

    # ② 设置页读的那两张表（TITLES/HINTS 只给界面用，模型看不到）
    for name in ("TITLES", "HINTS"):
        m = re.search(rf"private val {name} = mapOf\((.*?)\n\s*\)\n", tools, re.S)
        c.ok(f"AiTools 的 {name} 表定位到了", m is not None)
        if m:
            no_md(f"AiTools.{name}（设置页文案）里没有 Markdown", m.group(1))

    # ③ 风险档位的 blurb：它同时进模型描述**和**确认卡，所以两边都得干净
    risk_body = fn_body(wr, "enum class AiWriteRisk(")
    no_md("AiWriteRisk 的 label/blurb 里没有 Markdown（它会出现在确认卡上）", risk_body)

    # ③b 动作清单里的 **卡片文案**：headline / details 两个 lambda 的内容会原样渲染到卡上。
    # 同一个动作里还有 blurb / hint——那些是**给模型看的**，那里 `**` 是有意义的，
    # 所以只能按 lambda 切块，不能整个文件一刀切（v3.9 实测：批量调价的"范围"那行
    # 写了 `**16 条价格**`，屏幕上就是一堆星号）。
    #
    # ⚠️⚠️ v3.44：区间边界**不再用正则猜**，改成花括号配对（[balanced_inside]）。
    #    旧写法是 `\n\s+{kind} = \{{(.*?)\n\s+\}},`——它假定 lambda 一定以"单独一行的 `},`"收尾。
    #    而这两个文件里实际有 **8 处单行写法**：
    #        `headline = { c -> "新增商品：${c.str("name")}" },`
    #    这时正则匹配到的是**后面那块**的收尾，扫描区间一路吃到下一块里去（实测：
    #    第 57 行的 headline 区间一直吃到第 68 行 details 的 `},`）。
    #    后果不是"漏检"，而是**报错指到错的卡片上**——"headline 里有星号"，
    #    而星号其实在 details 里。误报与真报在输出里长得一模一样，
    #    这正是让人学会无视红线的路径（本项目已经有过一次"永远红的检查＝没有检查"）。
    # ---- 2e-③b 声明式动作清单里的卡片文案（headline / details 两块 lambda）----
    # 这个标记行的另一个用途：文档里引用 `§2e-③b` 时，`_ai_doc_check.py` 就是按
    # `# ---- <id>` 这个形状去核对的——没有标记行，文档引用会被判成"对不上"。
    #
    # ⚠️ v3.44 修掉了这条判据的两个盲区（都是"靠正则猜写法"）：
    #    ① 区间边界认「单独一行的 `},` 收尾」，而实际有 **8 处单行 lambda**
    #       （`headline = { c -> "…" },`）→ 区间一路吃到后面那块去（实测 1299 字符 vs 58 字符），
    #       报错于是**指到错的卡片上**——误报与真报长得一样，这是让人学会无视红线的路径。
    #       修法：花括号配对（[balanced_inside]）。
    #    ② 文件清单是**手写的 3 个**，而 `AiWritePricing.kt` 在里面却一个 headline/details 都没有
    #       ——那条断言一直在扫空集合并报 OK。修法：清单自己算（[md_lambda_files]）。
    for cat in md_lambda_files():
        src = strip_comments(read(AI / cat))
        # headline = { ... } , details = { ... }  两块分别取
        for kind in ("headline", "details"):
            decls = list(re.finditer(rf"\n\s+{kind} = [^\n{{]*?\{{", src))
            blocks = [balanced_inside(src, m.end() - 1) for m in decls]
            # 数量锚：**写这个键的地方都得定位到**。形状一变（例如 lambda 的 `{` 挪到下一行）
            # 就先在这里报错，而不是安静地少扫几块。
            n_decl = len(re.findall(rf"\n\s+{kind}\s*=", src))
            if n_decl:
                c.ok(
                    f"{cat}: {kind} 的块都定位到了（声明 {n_decl} 处 / 配对 {len(blocks)} 处）",
                    n_decl == len(blocks),
                    f"声明 {n_decl} 处、配对到 {len(blocks)} 处——有 lambda 的写法没被认出来",
                )
            bad = [s for b in blocks for s in string_literals(b) if "**" in s]
            c.ok(f"{cat} 的 {kind}（会渲染到确认卡上）里没有 Markdown 星号", not bad, f"例如 {bad[:1]}")

    # 配对器自检：**判据本身**也要有证据，否则"改回正则"这种改动会安静地通过。
    c.ok(
        "卡片文案的文件清单是算出来的（不是手写的 3 个）",
        len(md_lambda_files()) >= 2,
        f"实际 {md_lambda_files()}",
    )
    c.ok(
        "花括号配对器认得单行 lambda（区间不许吃到后面那块）",
        balanced_inside('details = { listOf("a") }, blurb = "b"', 10) == ' listOf("a") ',
        f"实际 {balanced_inside(chr(100) + 'etails = { listOf(\"a\") }, blurb = \"b\"', 10)!r}",
    )
    c.ok(
        "配对器跳过字符串里的括号（文案里有「」括号是常态）",
        balanced_inside('x = { "}" }, y', 4) == ' "}" ',
        "字符串里的 } 让配对提前结束的话，区间会一切两半",
    )

    # ---- 2e-③c 手写处理器的**卡片文案**（文档里按这个编号引用它；编号必须写成
    # `# ---- <id>` 这种"标记行"，因为 _ai_doc_check.py 就是按这个形状去核对文档引用的）----
    #
    # ⚠️ 这一段是 v3.16 真机实测补的：拆单卡片上出现了字面的 `**撤不回来**`。
    #    ③b 只扫了声明式那三个文件（`headline = { }` / `details = { }` 两块 lambda），
    #    而手写处理器是 `card(summary = ..., details = buildList { add("…") })`——
    #    形状完全不同，于是那些文案**从来没被检查过**。检查漏了一整类文件，
    #    表现却是全绿：这正是"假检查"最典型的样子。
    #
    # ⚠️⚠️ v3.20 又栽了同一个坑：这一段的文件清单是**手写的 3 个文件**，
    #    而 v3.17 之后的账本 / 商品行 / 消息 / 结算处理器分别在别的文件里——
    #    于是它们 4 个域的新卡片文案**一次都没被检查过**，
    #    真机上就出现了「司机账单生成后**没有删除入口**」这种字面星号（截图抓到的）。
    #    现在文件清单**自己算**（凡是含 `summary = ` 的 AiWrite*.kt 都算），
    #    再加两条"检查真的在看东西"的数量判据：
    #    · summary 参数个数 == 正则定位到的块数（形状一改就先失败，而不是安静地不过滤）；
    #    · details 参数个数 == summary 块数（每个 summary 都必须配上一个 details，且都被定位到）。
    #
    #    只查 `summary` 与 `details` 两块：同一个文件里还有 AiWriteArgException 的话术，
    #    那是**给模型看的**（"请让用户给**完整订单号**"），星号在那里是有意义的。
    md_files = []
    for p in sorted(AI.glob("AiWrite*.kt")):
        src = read(p)
        # ⚠️ 预筛必须与下面**数数的那个正则同形**（都是 `\n\s+summary = `）：
        #    用宽松的 `"summary = " in src` 预筛，会把"只在 KDoc/正文里提了一句
        #    `summary = …`、自己一张卡都没有"的文件也拉进来 —— 于是它 n_summary=0，
        #    被报成"卡片文案块没定位到"（**假红**）。2026-09-22 实测撞到：
        #    `AiWriteArgs.kt` 的 KDoc 里写了一句 `summary = …`，那条检查当场红，
        #    而它跟卡片文案一个字的关系都没有。假红的下场是这个检查被无视。
        if not re.search(r"\n\s+summary = ", src):
            continue
        # ⚠️⚠️ v3.32 第三次栽在同一个坑上：这一次的清单不是"文件"而是**形状**。
        #    这条检查原来是按"details 长什么样"去正则匹配的（`buildList { }` 一种），
        #    而实际代码里至少四种形状：
        #      ① details = buildList { … }                      ② detailLines = <变量>,
        #      ③ detailLines = <表达式> + listOfNotNull(…)      ④ detailLines = spec.details(card) + …
        #    只认 ① 的结果是：**八个卡片的文案从来没被扫过**，而检查照样全绿。
        #    实测代价：按表格调价的卡片在真机上一直印着字面的 `**仍然会执行**`（v3.21 就写进去了）。
        #
        #    所以现在**不再按形状去认**：`summary = ` 到 `payload = `（或参数表结束）之间
        #    就是这张卡片的全部文案，无论中间写成什么样都在这一段里。
        #    判据也跟着改成"定位到的卡片数 == summary 出现的次数"——形状再变也不会静默漏检。
        intervals = re.findall(r"\n\s+summary = ([\s\S]{0,3000}?)(?=\n\s+payload =|\n\s+\))", src)
        cards = list(intervals)
        # 还有一处**区间抓不到**的地方：`detailLines = <变量>` 时，那个变量的构造
        # 在 `offer(...)` **之前**（`val details = ArrayList<String>(…); details += "…"`）。
        # 只抓 summary→payload 这一段会漏掉它的全部内容——所以变量形态单独再抓一遍，
        # 从它的定义一直抓到 `store.offer(` / `return AiWriteOutcome`。
        #
        # ⚠️ 必须 `finditer`（一个文件里可以有**多处** `val details = …`；
        #    用 `search` 只会拿到第一处，后面的整块漏检——第一版就是这么写的，注入验证当场抓到）。
        for var in sorted(set(re.findall(r"\n\s+(?:details|detailLines) = (\w+),", src))):
            for m in re.finditer(
                rf"\n\s+(?:val )?{re.escape(var)} = [^\n]*\n([\s\S]*?)\n\s+(?:return AiWriteOutcome|store\.(?:offer|card)\()",
                src,
            ):
                cards.append(m.group(1))
        # ⚠️ 2026-09-21：`summary = ` 到 `payload = ` 的区间会**提前收尾**——明细里只要有一个多行
        #    表达式（它以"单独成行的 `)`"收尾），区间就在那儿断开，**后面整段明细从来没被扫过**。
        #    实测：核销卡上 `add("（没有点名商品 = **整单核销**：这一单还欠的全收）")` 一直原样印在
        #    屏幕上，而这条检查全程是绿的（这一轮把造卡收口时才撞出来）。
        #    所以明细块按**花括号配对**再单独收一遍（配对器与 2e-③b 是同一份 [balanced_inside]）。
        for m in re.finditer(r"\n\s+(?:details|detailLines) = buildList \{", src):
            cards.append(balanced_inside(src, m.end() - 1))
        n_summary = len(re.findall(r"\n\s+summary = ", src))
        # ⚠️ 光比 `summary = ` 的个数是不够的：**改名会让分子分母一起变小**
        #    （2 张卡改名 1 张 → summary 1 个、区间 1 个，"相等"于是照样通过，
        #      而那一张卡的文案已经不再被扫了）。所以再拿**造卡的出口**当锚：
        #    每张卡都必须经过 `store.card(...)`，区间数不得少于它。
        #    ⚠️ 2026-09-21：那 17 处各写一遍的造卡收成了 `AiWritePreviewStore.card(...)` **一处**，
        #       所以锚从 `store.offer(` 换成 `store.card(`——**不**写成"两者都算"：
        #       都算的话，"有人绕开出口自己拼 offer"在计数里就看不出来了（下面第 4 条专门盯它）。
        #    ⚠️ 数它必须在**去掉注释**的源码上数：注释里引用一句 `store.offer(...)`
        #       就会被算成一次调用，于是这条判据会莫名其妙地红（实测栽过**两次**：
        #       2026-09-19 一次，2026-09-21 在一次性改写脚本里又栽了一次）。
        src_nc = strip_comments(src)
        n_offers = len(re.findall(r"store\.card\(", src_nc))
        md_files.append((p.name, len(cards), n_summary))
        c.ok(
            f"{p.name}: 卡片文案块都定位到了（区间 {len(intervals)}/{n_summary}，造卡出口 {n_offers} 个）",
            n_summary > 0 and len(intervals) == n_summary and len(intervals) >= n_offers,
            f"summary 参数 {n_summary} 个、区间定位 {len(intervals)} 个、store.card 调用 {n_offers} 个"
            f"（另有 {len(cards) - len(intervals)} 块来自「先攒变量」/「明细块配对」那种写法）",
        )
        # ④ 造卡只有一处实现：谁都不许再自己拼 `store.offer(...)`
        #    （标题与风险档位必须走 `AiWritePreviewStore.card` 的默认值，也就是动作登记表）。
        raw_offer = len(re.findall(r"store\.offer\(", src_nc))
        c.ok(
            f"{p.name} 没有绕过造卡出口（自己拼 store.offer）",
            raw_offer == 0,
            f"发现 {raw_offer} 处自己拼的 store.offer —— 改用 store.card(actionId, summary, details, payload)",
        )
        bad = [s for blk in cards for s in string_literals(blk) if "**" in s or "__" in s]
        c.ok(f"{p.name} 的卡片文案里没有 Markdown 星号", not bad, f"例如 {bad[:1]}")

    c.ok(
        "扫到的卡片文件数合理（清单是算出来的，不是手写的）",
        len(md_files) >= 6,
        f"实际={[n for n, _, _ in md_files]}",
    )
    c.ok(
        "扫到的卡片块总数合理（正则过期会让它变成 0，那样这条检查就空了）",
        sum(n for _, n, _ in md_files) >= 30,
        f"实际 {sum(n for _, n, _ in md_files)} 块：{md_files}",
    )

    # ---- 2e-③d-2 卡片「信息区」用表格显示（用户 2026-09-20）----
    #
    # 用户截了一张确认卡、把信息区框出来说：
    # > 所有卡片只要是那里显示的信息，尽量都使用表格的形式…核心目标是**将信息正确且明显地展示出来**。
    # > 如果只是文字的信息的话太看不清了。
    #
    # 那一块原来是 `p.detailLines.forEach { Text(it) }` —— 一列同样的灰字，
    # 标签和值只能一行行读。现在**解析成「标签 / 值」两列表格**（`AiCardTable`），
    # 好处是**一次改动覆盖全部 ~50 个处理器**（不用改它们一个字）。
    #
    # 钉三件事：① 信息区走表格；② 解析只有一处实现；③ **不许退回去逐行画纯文本**
    # （那正是用户说"看不清"的形态）。反向验证：`_reverse_verify_card_markdown.py`。
    c.present("卡片信息区走表格渲染",
              read(UI / "ai/AiChatScreen.kt"), r"CardInfoTable\(p\.detailLines\)")
    c.present("「标签 / 值」的解析只有一处实现",
              read(AI / "AiCardTable.kt"), r"fun rows\(lines: List<String>\): List<Row>")
    c.absent("卡片信息区不许退回「逐行画纯文本」",
             read(UI / "ai/AiChatScreen.kt"), r"p\.detailLines\.forEach \{ line ->")
    c.present("表格只有一处渲染（`CardInfoTable` 只被调用一次）",
              read(UI / "ai/AiChatScreen.kt"), r"private fun CardInfoTable\(")

    # ---- 2e-③e 撤回卡与「撤不回来」的理由（`AiRevert*.kt`）也不许有 Markdown ----    #
    # ⚠️⚠️ v3.44 真机实测抓到的**第 4 次**同一类事故：重排商品分类的确认卡最后一行
    #    印着字面的 `**整份名册的顺序**`（截图 `_archive/ai-e2e-v343/t3-02-card.png`），
    #    而这一段的所有检查**全是绿的**——因为它们的文件清单写的是
    #    `AI.glob("AiWrite*.kt")`，**`AiRevert.kt` 不匹配这个前缀**。
    #    于是它整整一类文案（撤回明细 / 「撤不回来」的理由 / 资源标签）从来没被扫过。
    #    这正是 ③c 上面注释里警告过的"检查漏了一整类文件，表现却是全绿"。
    #
    # 判据刻意**不按形状挑**（不去找 `note = ` / `none(` / `add("` …）：
    # 那一整份文件里出现的字符串只有两种——**要上卡的字**（理由/明细/标签）
    # 和**内部键名**（`"vehicle_id"`、`"changes"`），而内部键名里不可能有 `**`。
    # 所以整份扫描不会误报，却能盖住以后新加的每一种写法（直引号、`+` 拼出来的都算）。
    #    第一次修的时候只把清单从"手写 3 个"换成"glob `AiRevert*.kt`"——**又漏了
    #    `AiResources.kt`**（同一个坑的第 5 次：那里面还有 7 处字面星号，是真机 E2E 报告点出来的）。
    #    所以现在的清单**按内容算**：凡是声明了撤回/卡片结构的文件
    #    （`AiResource(` / `AiUndoPlan(` / `AiInverse(` / `AiRevertAction(`）统统都扫，
    #    以后新加一个同类文件**自动**被覆盖，不需要谁记得来登记。
    CARD_MARKERS = ("AiResource(", "AiUndoPlan(", "AiInverse(", "AiRevertAction(")
    revert_files = sorted(p.name for p in AI.glob("*.kt") if any(k in read(p) for k in CARD_MARKERS))
    c.ok(
        "撤回/卡片结构所在的文件都认出来了（改名或换写法会让下面的扫描空转）",
        len(revert_files) >= 2,
        f"实际 {revert_files}",
    )
    n_revert_lits = 0
    for name in revert_files:
        lits = string_literals(read(AI / name))
        n_revert_lits += len(lits)
        bad = [s for s in lits if "**" in s or "__" in s]
        c.ok(f"{name}（撤回卡 / 撤不回来的理由）里没有 Markdown 星号", not bad, f"例如 {bad[:1]}")
    c.ok(
        "这些文件里的字符串扫得够多（正则过期会让它掉到 0）",
        n_revert_lits >= 40,
        f"实际扫到 {n_revert_lits} 个字面量：{revert_files}",
    )

    # ---- 2e-③f 「逆操作 = 自己」这种声明一定造不出撤回（真机抓到的） ----
    # `AiRevert.pairedPlan` 的第一行就是 `if (inverse.actionId == entry.id) return null`。
    # 于是"自己配自己"的资源声明会让撤回方案**永远造不出来**，而 `canRevert()` 照样返回 true
    # ——卡片敢印「会出现『撤回』」，用户点完确认却只收到一句"这次没能挂上撤回"。
    # 比"根本没有撤回"更糟：他以为自己能退回去。
    res_src = read(AI / "AiResources.kt")
    self_inv: list[str] = []
    for m in re.finditer(r"paired\(\s*(AiWrites\.\w+),\s*AiInverse\(\s*(AiWrites\.\w+)", res_src):
        if m.group(1) == m.group(2):
            self_inv.append(m.group(1))
    c.ok("没有任何动作把逆操作声明成它自己", not self_inv, f"自逆：{self_inv}")
    n_paired = len(re.findall(r"paired\(", res_src))
    c.ok("真的扫到了成对动作（全改掉的话上面那条就恒真了）", n_paired >= 10, f"实际 {n_paired} 处 paired(")

    # ---- 2e-③d **结果文案**（用户点完确认之后看到的那句话）----
    #
    # 为什么还要单独一段：卡片文案查过了，但"执行完之后那句反馈"是**另一个出口**——
    # `AiWriteService.execute` 拼的 Done 消息、以及各处理器的 `commitNote()`（逐行结果）。
    # 它们同样是 `Text()` 直接渲染，写 `**` 就会原样印出来。
    # 实测抓到过：「⚠️ 这次**没能挂上「撤回」**…」（真机上真的带着星号）。
    result_sinks = 0
    result_bad: list[str] = []
    for p in sorted(AI.glob("AiWrite*.kt")):
        src = read(p)
        regions: list[str] = []
        # ① 各处理器的 commitNote（逐行/批量执行结果）
        for m in re.finditer(r"\n\s+pendingNote = ([\s\S]{0,2500}?)\n\s*\}", src):
            regions.append(m.group(1))
        # ② AiWriteService 里拼 Done 消息的那些字面量。
        #    ⚠️ 注意写法：`buildString { append(…) }` 里是**裸调用**（前面没有点），
        #    只匹配 `.append(` 会一处都抓不到——第一版就是那么写的，判据 "0 个文件里有"
        #    看着全绿，其实什么都没查（"永远绿的检查 = 没有检查"）。
        for m in re.finditer(r"\b(?:append|appendLine)\(([\s\S]{0,400}?)\)\n", src):
            regions.append(m.group(1))
        # ⚠️ 计的是"扫到几个区块"，不是"几个区块里有星号"。
        #    后者在修好之后恒为 0——那这条检查就又变成永远绿的了（本项目栽过 12 轮）。
        result_sinks += len(regions)
        result_bad += [s for blk in regions for s in string_literals(blk) if "**" in s or "__" in s]
    c.ok(
        f"结果文案（扫到 {result_sinks} 个区块）里没有 Markdown 星号",
        not result_bad and result_sinks >= 5,
        f"扫到 {result_sinks} 个区块（少于此数说明正则过期了）；星号例如 {result_bad[:2]}",
    )

    # ==================================================== 2f 处理器架构
    # v3.8：动作从 3 个长到 10 个，实现按域拆成了 handler 文件。
    # 拆文件本身不产生风险，**但"拆完之后规矩还在不在"会产生**——下面守的就是那几条规矩。
    print("\n== 2f. 写动作的处理器：声明与实现不许走散，prepare 不许写库 ==")

    # ---- 2f-1 声明与实现一一对应 ----
    # AiWrites.ALL 是**给模型看的清单**，handlers 是**真能跑的**。
    # 两边一旦不相等，最坏的那种 bug 就出现了：模型看得见某个动作、调了却报"暂未实现"。
    # 运行时也有单测兜（AiWriteTest.每个声明了的动作都真的实现了），这里是第二道。
    declared = set(re.findall(r'const val ([A-Z_]+) = "([a-z_]+\.[a-z_]+)"', wr))
    declared_ids = {v for _, v in declared}
    registered = set(re.findall(r"(\w+Handler)\(ds", wsvc))
    c.ok("服务层注册了处理器（不是空表）", len(registered) >= 10, f"实际={sorted(registered)}")
    c.present("注册表把处理器按 actionId 收进 map（键就是动作 id，不会错位）", wsvc, r"put\(it\.actionId, it\)")
    c.present("声明式动作统一交给通用处理器（不是每个都手写一遍）", wsvc, r"put\(a\.id, CrudWriteHandler\(a, spec, ds, store\)\)")
    c.present("有一处能读出「实现了哪些」供检查用", wsvc, r"val implementedActionIds: Set<String>")

    # ---- 2f-2 prepare 里绝对不许写后端 ----
    # 这是整套设计最容易被"顺手优化"掉的一条：有人会觉得"反正就一步，直接在 prepare 里写掉算了"。
    # 写掉之后确认卡就变成了一张**事后通知**——用户点不点都已经写进去了。
    #
    # ⚠️ 唯一的例外是 `readAllNotifications`，而且它是**规则本身规定的**：
    # LOW 档动作（不留业务记录、不影响别人）就是要在 prepare 里直接执行完、不弹卡。
    # 所以这里把它排除掉，同时**单独锁死"LOW 档只能有一个动作"**——
    # 没有后面那条，"例外"就会随着新动作一个一个长出来，最后这条检查等于没有。
    c.ok(
        "LOW 档动作只有 1 个（自动执行的例外不许变长）",
        len(re.findall(r"risk = AiWriteRisk\.LOW,", wr)) == 1,
        f"实际 {len(re.findall(r'risk = AiWriteRisk.LOW,', wr))} 个",
    )
    c.present("唯一那个 LOW 档动作就是「消息全标已读」", wbasic, r"class NotificationsReadAllHandler")
    c.present(
        "并且写明了「不要把它挪到 commit 去」的理由",
        wbasic,
        r"不要\*\*把\"执行\"挪到这里来",
    )

    # ---- 2f-2b 这一条必须扫**所有**处理器文件，而且"写方法"要自己算出来 ----
    #
    # ⚠️ v3.20 修掉的两个空转（都是"检查还在、但已经不看任何东西"）：
    # ① 原来只扫 `AiWriteBasicHandlers.kt` + `AiWriteOrderHandlers.kt` 两个文件——
    #    而账本、商品行、消息、批量调价、结算这些处理器**分别在别的文件里**，
    #    "在 prepare 里顺手写掉"这种 bug 落在那几个文件里是**无声无息**的。
    # ② 原来用一张手写的写方法名单（`createExpense|assignOrder|…` 9 个）——
    #    数据源接口现在有 50 多个方法，新增的写方法一个都不在名单里，等于没查。
    #
    # 现在的判据：**从 `AiWriteDataSource` 接口自己解析出全部方法**，
    # 减掉一份显式的"读方法白名单"，剩下的**一律当写**（fail-closed：
    # 以后新增的数据源方法默认受这条约束，不会因为"忘了加进名单"而漏检）。
    handler_files = sorted(p for p in AI.glob("AiWrite*.kt") if "override suspend fun prepare(" in read(p))
    c.ok(
        "扫到的处理器文件数合理（漏文件＝漏检）",
        len(handler_files) >= 6,
        f"实际={[p.name for p in handler_files]}",
    )
    iface = block_between(wsvc, "interface AiWriteDataSource {", "\n}")
    ds_methods = set(re.findall(r"suspend fun (\w+)\(", iface))
    c.ok("解析到了数据源接口的方法（正则没过期）", len(ds_methods) >= 40, f"实际 {len(ds_methods)} 个")
    c.ok(
        "读方法白名单没有过期（写进白名单的名字必须真的存在）",
        READ_METHODS <= ds_methods,
        f"对不上的：{sorted(READ_METHODS - ds_methods)}",
    )
    write_methods = ds_methods - READ_METHODS
    c.ok(
        "算出来的写方法不是空集（否则这条检查在空转）",
        len(write_methods) >= 30,
        f"实际 {len(write_methods)} 个",
    )

    write_call = re.compile(r"\b(\w+)\.(" + "|".join(sorted(write_methods)) + r")\s*\(")
    scanned_blocks = 0
    for f in handler_files:
        src = read(f)
        # 按 "override suspend fun prepare" / "...commit" 切块，逐块看
        blocks = re.split(r"override suspend fun (prepare|commit)\(", src)
        # blocks = [前缀, 'prepare', body, 'commit', body, 'prepare', body, ...]
        offenders = []
        for i in range(1, len(blocks) - 1, 2):
            kind, body = blocks[i], blocks[i + 1]
            if kind != "prepare":
                continue
            scanned_blocks += 1
            for m in write_call.finditer(body):
                # 唯一例外：LOW 档动作在 prepare 里直接执行（规则本身要求如此）。
                if m.group(2) == "readAllNotifications":
                    continue
                offenders.append(f"{m.group(1)}.{m.group(2)}()")
        c.ok(f"{f.name}: prepare 里没有写后端的调用", not offenders, f"例如 {offenders[:2]}")
    c.ok(
        "真的扫到了 prepare 块（不是文件都没匹配上）",
        scanned_blocks >= 20,
        f"实际扫到 {scanned_blocks} 个 prepare",
    )
    # 每个动作都必须**同时**有 prepare 和 commit：只有 prepare ＝ 那张卡点下去什么都没发生。
    # ⚠️ v3.20：这一条原来只查"这个文件里有没有 commit"——一个文件里有 5 个处理器时，
    # 删掉其中**一个** commit 是查不出来的（文件里还有 4 个）。现在按**数量相等**查：
    # 声明了几个 actionId，就必须有几个 prepare、几个 commit（三份数一一相等）。
    for f in handler_files:
        src = read(f)
        n_action = len(re.findall(r"override val actionId", src))
        n_prepare = len(re.findall(r"override suspend fun prepare\(", src))
        n_commit = len(re.findall(r"override suspend fun commit\(", src))
        c.ok(
            f"{f.name}: 动作数 == prepare 数 == commit 数（点确认真的会写）",
            n_action >= 1 and n_action == n_prepare == n_commit,
            f"actionId={n_action} prepare={n_prepare} commit={n_commit}",
        )

    # ---- 2f-3 订单动作必须先核对状态，再弹卡 ----
    c.present("订单处理器有共用的状态核对入口", worder, r"protected fun requireStatus\(")
    c.present("状态不满足时给的是**人话**（用户看不懂 PENDING_DISPATCH）", worder, r"请如实告诉用户，不要换一张单去操作")
    c.present("每个订单动作都调了 requireStatus", worder, r"requireStatus\(order,")
    c.present("订单卡片必须带「这单是谁」那几行", worder, r"protected fun orderLines\(")
    c.present("订单号太短直接拒绝（q 是全量模糊匹配，没有分页兜底）", worder, r"MIN_REF_CHARS")

    # ==================================================== 2g 声明式 CRUD 层
    # v3.9：用户口径是「整个 App 的功能它都能做」——后端 72 个写接口。
    # 这个量级下每个动作手写一个处理器必然出错（26 个各写一遍金额上限，一定有一个忘），
    # 所以有了 [CrudWriteHandler]。下面守的是"收敛之后那几条规矩还在不在"。
    print("\n== 2g. 声明式 CRUD：校验只有一份，key 不许写错，凭据不许回显 ==")
    wcrud = AI_join("AiWriteCrudHandlers.kt")
    wmaster = AI_join("AiWriteMasterData.kt")

    # ---- 2g-1 prepare 不许写后端（声明式这一路也要守）----
    # ⚠️ 上面 §2f-2b 已经**逐个文件**扫过一遍（包括这个文件）；这里保留一条更具体的：
    # 声明式的落库动作只能出现在 commit 里，且只能由 `spec.commit(ds, payload)` 触发。
    c.ok(
        "AiWriteCrudHandlers.kt: prepare 里没有写后端的调用",
        not write_call.search(re.split(r"override suspend fun commit\(", wcrud)[0]),
        "提交调用混进了 prepare",
    )
    c.present("通用处理器只在 commit 里调规格给的落库动作", wcrud, r"spec\.commit\(ds, payload\)")

    # ---- 2g-2 规格里的 key 必须和后端字段名一致 ----
    # 写错的表现**是静默的**：pick() 认不出这个键 → payload 空 → PATCH 什么都不改，
    # 而卡片上明明写着"改成 X"。写这一轮时真的写错过一次（改资料的 name→full_name），
    # 是单测抓到的；这条静态检查是第二道。
    bad_keys = []
    c.present("目标实体的 payload 键统一以 _id 结尾（编号字段的命名约定）", wcrud, r'key = "product_id"')
    c.present("部分更新只挑白名单键（没说的字段绝不补默认值）", wmaster, r"fun JsonObject\.pick\(keys: Set<String>\)")
    c.present("空的部分更新体会炸出来（否则就是「卡片说改了、实际没改」）", wsvc, r"部分更新体是空的")

    # ---- 2g-2b 目标参数与字段参数**不许重名** ----
    # 单测抓到过一次：`address.update` 的目标参数叫 `address`（"用哪条地址去搜"），
    # 而它的一个字段也叫 `address`（新地址）。两者读同一个键，
    # 于是**拿搜索词当新地址写了进去**——卡片上显示的还是"改地址：王五 测试路 1 号"，
    # 看不出任何异常。这类撞名只能靠静态检查拦。
    #
    # ⚠️ 判据必须先把「辅助函数名 → param」解开：动作里写的是 `targets = listOf(targetAddress())`，
    # 而 `param = "address"` 定义在另一个文件的辅助函数里。直接扫动作块**什么都扫不到**——
    # 第一版就是这么写的，结果它永远通过（一条不会失败的检查比没有检查更糟）。
    #
    # ⚠️⚠️ v3.44 修掉三处**同一根因**的盲区（"清单/边界靠正则猜写法"）：
    #    ① 字段名只认 `enumField("x"` —— 名字必须紧跟左括号。而代码里实际有
    #       **11 处跨行写法**（`enumField(` 换行后才是名字），它们全部落在盲区里
    #       （`AiWriteBasicData.kt` 里甚至留着一句注释承认"红线的重名检查只认单行写法"）。
    #       修法：`\(\s*"`，并给提取器本身加一条自检。
    #    ② 字段构造函数的名单是**手写的 5 个名字**，漏了 `positionField`
    #       （`AiWriteBasicData.kt` 里的私有包装，用它写的字段从没被查过）。
    #       修法：名单由 [field_ctors] 从源码里**算出来**。
    #    ③ 目标参数只认 `targetXxx()`（**空括号**），而 `targetUser(cn)` 与
    #       `targetDriverRule(required)` 是**带参数**的辅助函数 → 用它们的
    #       **7 个动作**（改账号/改货主/设批发商/3 个计费规则动作）连目标名都没解出来，
    #       撞名检查对它们是空转。修法：改成 `target\w+\(` 并断言
    #       "用到的目标辅助函数**全部**能解析出参数名"（解不出就报错，不是安静跳过）。
    #    块边界也跟着改成花括号配对（`crud(` / `targets = listOf(` / `fields = listOf(`），
    #    不再假定"块的收尾是 8 空格缩进的 `),`"。
    tgt_map: dict[str, str] = {}
    for p in sorted(AI.glob("*.kt")):
        s = strip_comments(read(p))
        for m in re.finditer(r"\bfun (target\w+)\(", s):
            ins = balanced_inside(s, m.end() - 1)
            tail = s[m.end() - 1 + len(ins) + 2:][:400]
            hit = re.search(r'=\s*AiTargetSpec\(\s*param = "(\w+)"', tail)
            if hit:
                tgt_map[m.group(1)] = hit.group(1)
    c.ok(
        "能解析出「目标辅助函数 → 参数名」表（否则下面的重名检查是空转）",
        len(tgt_map) >= 10,
        f"实际 {len(tgt_map)} 个：{sorted(tgt_map)}",
    )
    c.ok(
        "带参数的辅助函数也能解析（targetUser(cn) / targetDriverRule(required) 曾经解不出）",
        "targetUser" in tgt_map and "targetDriverRule" in tgt_map,
        f"实际 {sorted(tgt_map)}",
    )
    ctors = field_ctors()
    c.ok(
        "字段构造函数清单是**算出来**的，不是手写的 5 个名字",
        len(ctors) >= 6,
        f"实际 {ctors}",
    )
    c.ok(
        "自定义字段构造（positionField）也在清单里（手写清单漏过它）",
        "positionField" in ctors,
        f"实际 {ctors}",
    )
    c.ok(
        "字段名提取器认得**跨行**写法（旧判据只认 `enumField(\"x\"`，11 处调用在盲区里）",
        field_names('listOf(\n    enumField(\n        "vehicle_type", "新车型",\n    ),\n)') == {"vehicle_type"},
        f"实际 {field_names(chr(101) + 'numField(' + chr(10) + '    "x",' + chr(10) + ')')}",
    )

    for name in ("AiWriteMasterData.kt", "AiWriteBasicData.kt"):
        src = strip_comments(read(AI / name))
        # ⚠️ `(?<!fun )`：`crud(` 在同一个文件里**既是调用也是声明**
        #    （`private fun crud(...)` 定义在文件末尾），不排掉的话会多出一个
        #    "没有动作 id 的块"，而那条断言正是用来发现块切错了的——它不能被自己误伤。
        blocks = [balanced_inside(src, m.end() - 1) for m in re.finditer(r"(?<!fun )\bcrud\(", src)]
        with_targets = 0
        n_targets = n_fields = 0
        bad_slices: list[str] = []
        unresolved: set[str] = set()
        clashes = []
        for blk in blocks:
            ids = re.findall(r"id = AiWrites\.(\w+)", blk)
            if len(ids) != 1:
                # 块切错了的**唯一可靠信号**：一个块里认不出动作 id（0 个），
                # 或者一个块里有两个（区间把下一块也吃进来了）。
                bad_slices.append(f"{ids or '无 id'}（块首：{blk.strip()[:40]}…）")
                continue
            tnames: set[str] = set()
            for tm in re.finditer(r"targets = listOf\(", blk):
                for n in re.findall(r"\b(target\w+)\(", balanced_inside(blk, tm.end() - 1)):
                    if n not in tgt_map:
                        unresolved.add(n)   # 解不出参数名 = 这个动作的重名检查是空转
                    tnames.add(tgt_map.get(n, n))
            fnames: set[str] = set()
            for fm in re.finditer(r"fields = listOf\(", blk):
                fnames |= field_names(balanced_inside(blk, fm.end() - 1))
            if tnames:
                with_targets += 1
            n_targets += len(tnames)
            n_fields += len(fnames)
            clashes += [f"{t} == {f}" for t in tnames for f in fnames if t == f]
        c.ok(f"{name}: crud 块都切对了（每块恰好认出一个动作 id）", not bad_slices, f"异常块 {bad_slices}")
        c.ok(f"{name}: 用到的目标辅助函数都能解析出参数名", not unresolved, f"解不出：{sorted(unresolved)}")
        c.ok(f"{name}: 目标参数与字段参数没有重名", not clashes, f"撞名 {clashes}")
        c.ok(
            f"{name}: 扫到的目标/字段数量合理（正则过期会让它掉到 0）",
            n_targets >= 15 and n_fields >= 25,
            f"目标参数 {n_targets} 个、字段 {n_fields} 个（{len(blocks)} 个 crud 块）",
        )
        c.ok(f"{name}: 至少扫到了几个带目标的动作（否则上面那条是空转）", with_targets >= 5, f"扫到 {with_targets} 个")

    # ---- 2g-3 成本：**在开关后面**（2026-09-19 用户推翻"从来不许"）----
    #
    # 原来的规则是"成本不许进参数、也不许由模型设"。用户后来的要求是：
    # 「只要是我们改过、比如说新加了一些功能，AI 它都要具备操纵这些功能的能力」——
    # 而"进货时录成本价""改成本价"正是那一轮刚加的功能。
    #
    # 两个要求都成立，所以规则从「**从来不许**」改成「**必须在开关后面**」：
    #   · 成本价一旦进模型上下文就会留在聊天记录里、可能被截图外发 →
    #     所以它必须是一个**用户能关的开关**（`AiKeyStore::costVisible`）；
    #   · 开关关着的时候，**数据源那一层**必须真的把它滤掉 ——
    #     只靠"动作清单里不列它"是不够的（模型仍能从提示词知道它存在，也能被越权调用）。
    #   ⚠️ 判据要盯着**这两头**：一头是"有开关"，另一头是"开关关着时真的传不出去"。
    #
    # ⚠️ 2026-09-20 用户改了**默认值**（「对那个默认也要开起来」，接着上一句
    #    「派单员所有 AI 功能全都是默认开启」）→ 原来的"一律默认关"换成"按角色"：
    #    派单员默认开、其余角色默认关。开关本身与"关着必滤"这两条**都没动**。
    c.present("成本开关的默认值按角色（派单员默认开，其余角色默认关）",
              keystore, r"fun defaultCostVisible\(role: AiRole\?\): Boolean = role == AiRole\.DISPATCHER")
    c.present("没设置过时才用默认值（用户关过就听用户的）",
              keystore, r"if \(prefs\.contains\(KEY_COST_VISIBLE\)\) return prefs\.getBoolean\(KEY_COST_VISIBLE, false\)")
    c.present("两个读侧调用点都把角色传进去了（否则派单员的默认值不生效）",
              read(AI / "AiContainer.kt") + read(UI / "ai/AiSettingsViewModel.kt"),
              r"costVisible\(role\(\)\)|costVisible\(ai\.currentRole\)")
    c.present("成本价与进货价**在动作参数表里**（否则 AI 操作不了这两个功能）",
              wmaster, r'key = "cost_price"')
    c.present("进货价同样在参数表里", wmaster, r'key = "unit_cost"')
    c.present("门开在写服务的唯一入口（preview），不是散在各 handler 里",
              wsvc, r"costFieldIn\(params\)\?\.let")
    c.present("被拒时告诉用户**怎么打开**（否则他只会觉得「AI 又说它不能」）",
              wsvc, r"允许 AI 查看成本与毛利")
    # 端到端那条（关着必拒 / 打开才落库）在 `AiWriteTest` 里，见那 4 条 `成本开关…` 用例。
    c.present("读侧也过同一道门（只给一条路开口 = 另一条成了后门）",
              read(AI / "AiReadService.kt"), r"AiRowShaper\.shape\(it, allowCost\(\)\)")
    c.present("读侧的栏截面在 AiRowShaper（判据同时给两条路用）",
              shaper, r"allowCost: Boolean = false")

    # ---- 2g-4 凭据不许回显 ----
    # 判据要精确到"**把密码的值插进文案里**"，而不是"文案里出现『密码』两个字"：
    # 「改密码：张三」是正当的卡片标题，`密码：${c.str("password")}` 才是泄露。
    c.present("密码字段的说明里写明「不要自己编一个」", wmaster, r"不要自己编一个")
    leaky = re.findall(r'\$\{[^}]*c\.(?:str|line)\("password"\)[^}]*\}', read(AI / "AiWriteMasterData.kt"))
    c.ok("卡片文案里没有插入密码值", not leaky, f"例如 {leaky[:1]}")
    c.present("密码一律写成「已设置，不显示」", wmaster, r"密码：已设置，不显示")
    # 光靠"写摘要的人记得别写"是不够的：card 文案是手写的，而"顺手把填的值列出来"
    # 是最自然的冲动。所以凭据字段在规格里是**一等标志**，单测对全部动作统一断言。
    c.ok(
        "每个密码字段都标了 secret = true（值进 payload，但不许上卡片）",
        read(AI / "AiWriteMasterData.kt").count("secret = true")
        == len(re.findall(r'textField\("password"', read(AI / "AiWriteMasterData.kt"))),
        f"password 字段 {len(re.findall(chr(34) + 'password' + chr(34), read(AI / 'AiWriteMasterData.kt')))} 个，"
        f"secret 标记 {read(AI / 'AiWriteMasterData.kt').count('secret = true')} 个",
    )
    c.present("secret 是一等规格字段（不是靠命名约定）", wr, r"val secret: Boolean = false")
    # ---- 2g-6 角色权限阶梯（派单员 > 货主 > 司机）----
    # 用户口径：货主只该有他工作台里那几件；司机不开放。
    # 关键是**裁剪必须发生在服务层**——界面藏起来的动作，模型仍然能从提示词里知道它存在。
    c.present("有角色枚举，且不含司机（司机不开放）", wr, r"enum class AiRole")
    c.absent("司机没有资格（AiRole 里不许有 DRIVER）", fn_body(wr, "enum class AiRole("), r"DRIVER\(")
    c.present("货主动作是**白名单**（漏标=少给能力，不会多给）", wr, r"val SHIPPER_ACTIONS: Set<String> = setOf\(")
    c.present("forRole 认不出角色就返回空（fail-closed）", wr, r"actor\?.role \?: return emptyList\(\)")
    c.present("服务层 preview 会再查一次角色", wsvc, r"if \(!AiWrites\.allows\(actor, action\.id\)\)")
    c.present("执行时再查一次（两次之间角色可能变了）", wsvc, r"if \(!AiWrites\.allows\(actorProvider\(\), p\.actionId\)\)")
    c.present("工具说明按角色裁剪（不是只裁执行）", tools, r"AiWrites\.describeForModel\(actor\)")
    c.present("preview_write 的工具定义是现拼的（静态表看不到角色）", tools, r"private fun previewWriteSpec\(actor: AiActor\?\)")
    c.present(
        "AI 入口对货主开放、司机不给",
        AI_join("../ui/home/RoleHomeScreen.kt"),
        r"val showAiButton = role == Role\.DISPATCHER",
    )
    # ---- 白名单里**不许出现**的东西（"裁少了"那一侧）----
    # 上面那条只证明"货主走白名单"，证明不了白名单本身没写错。
    # 用户的口径是「货主好多权限根本不需要操作，它只需要知道自己该干的事」——
    # 所以主数据/派单/账本写入/账号管理这些**一个都不许**混进去。
    # 判据按**常量名**匹配（`ORDERS_`、`PRODUCTS_`…）：加进来一个新动作时会自动被这条逮到。
    whitelist = block_between(wr, "val SHIPPER_ACTIONS: Set<String> = setOf(", "\n    )")
    shipper_n = len(re.findall(r"\b[A-Z][A-Z0-9_]+\b", strip_comments(whitelist)))
    # 「全量」按**动作常量**数（`const val X = "动作.id"`）—— 那是这份文件里动作的唯一定义处，
    # 与 `AiWrites.ALL` 里挂了几份清单无关（ALL 是拼出来的，数不出常量）。
    all_n = len(re.findall(r'\n    const val [A-Z][A-Z0-9_]* = "', strip_comments(wr))) or 1
    forbidden_prefixes = (
        "ORDERS_ASSIGN", "ORDERS_RECALL", "ORDERS_SPLIT", "ORDERS_UPDATE", "ORDERS_FREIGHT",
        "ORDERS_EXCEPTION", "ORDERS_RESOLVE", "ORDERS_DELETE", "ORDERS_RESTORE", "ORDERS_LINE_",
        "PRODUCTS_", "PRICE_RULES_", "INVENTORY_", "USERS_", "LEDGER_", "SETTLEMENTS_",
        "DRIVER_BILLS_", "NOTIFICATIONS_SEND", "NOTIFICATIONS_UPDATE",
        "ARREARS_", "VEHICLES_", "CUSTOMERS_", "FREIGHT_TEMPLATE", "ORDERS_MARK",
        # ⚠️ 2026-09-20 从这里**拿掉**了 `NOTIFICATIONS_DELETE`：那条禁令的理由写的是
        #    "删除别人的消息"，而后端根本没有"删别人的消息"这条能力 ——
        #    `POST /notifications/batch-delete` 与 `DELETE /notifications/{id}` 都是
        #    "仅登录 + 只动自己的"（动别人的直接 404）。手机上消息页三端共用、货主能删自己的，
        #    所以 AI 也要能删（用户第七轮：「他手机做不到的事情 AI 也做不到」，
        #    反过来同样成立）。留下的两条（发消息 / 改消息）仍然是派单员的。
    )
    leaked = sorted({p for p in forbidden_prefixes if re.search(rf"\b{p}", whitelist)})
    c.ok(
        "货主白名单里没有主数据/派单/账本写入/账号管理（裁少了 = 越权）",
        not leaked,
        f"混进去了：{'、'.join(leaked)}",
    )
    c.ok(
        "白名单非空且远小于全量（空=货主没得用；接近全量=等于没裁）",
        # ⚠️ 判据从"绝对值 ≤25"改成**相对全量**的比例（2026-09-20 第七轮）：
        #    白名单这一轮按用户要求补了 6 条（消息标已读 / 删自己的消息 / 删自己终态的单 /
        #    地址·联系人·地点的恢复），26 个 —— 而绝对值那条会因此变红，
        #    逼着人要么删能力、要么改数字。真正要防的是"等于没裁"（接近全量），
        #    不是"数字变大"，所以判据写比例：**白名单不得超过全量的 35%**。
        #    比例条自己算（`ALL` 的常量从同一个文件里数），动作表长大时它会跟着长。
        5 <= shipper_n <= max(8, int(0.35 * all_n)),
        f"白名单 {shipper_n} 个 / 全部 {all_n} 个（上限 {max(8, int(0.35 * all_n))}）",
    )
    c.present(
        "角色能力账有脚本（派单员/货主/司机各给多少，一条命令看全）",
        read(Path(__file__).resolve().parent / "_show_role_caps.py"),
        r"SHIPPER_FORBIDDEN_HINTS",
    )
    # ⚠️ 这两条是反向验证抓出来的洞：上面那些只证明"白名单存在"，
    #    证明不了**它是被用上的**，也证明不了"派单员仍然是全量"。
    #    （注入 `AiRole.DISPATCHER -> ALL.take(3)` 和 `AiRole.SHIPPER -> ALL` 当时全绿。）
    #    ⚠️ 末尾必须锚住：`-> ALL\b` 会漏掉 `-> ALL.take(3)`（`ALL` 和 `.` 之间正好是词边界），
    #    反向验证就是这么抓到这条判据原本是空转的。
    # ⚠️ 2026-09-21：这条判据从 `ALL.filter { !it.memberOnly }` 变成"再叠一层 `roles`"。
    #    起因是退货申请那一组里申请/撤回归货主、办理/驳回归派单员，而 `memberOnly` 只区分
    #    "批发商货主"，派单员会把货主那两条一起拿走 → **两张点了必然失败的卡**。
    #    仍然要求末尾锚住 `.filter {`（见上一条注释：不能退化成 `-> ALL` 这种更宽的东西）。
    c.present(
        "派单员确实是全量（减掉 memberOnly，再按 roles 点名）",
        strip_comments(wr),
        r"AiRole\.DISPATCHER -> ALL\.filter \{",
    )
    c.present(
        "派单员那一条真的过了 roles（只过滤 memberOnly 的话货主动作会漏给他）",
        strip_comments(wr),
        r"AiRole\.DISPATCHER -> ALL\.filter \{[\s\S]{0,160}?it\.roles == null \|\| role in it\.roles",
    )
    c.present(
        "货主确实按白名单 + member 过滤（白名单只是摆设的话等于没裁）",
        strip_comments(wr),
        r"AiRole\.SHIPPER -> ALL\.filter \{[\s\S]{0,200}?it\.id in SHIPPER_ACTIONS",
    )
    c.present(
        "这条判据有反向验证（往白名单里塞一个派单动作会红）",
        read(Path(__file__).resolve().parent / "_reverse_verify_write_roles.py"),
        r"SHIPPER_ACTIONS",
    )

    # ---- 2g-7 身份提示词也按角色分（v3.28）----
    # 用户原话：「AI 说自己能干好多事情，是因为你那个系统提示词没写好、没有分开。」
    # 事实就是：提示词第一行写死「你是…给**派单员**用的助手」，货主读到的还是它。
    role_prompt = AI_join("AiRolePrompt.kt")
    role_prompt_test = read(ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiRolePromptTest.kt")
    loop_code = strip_comments(loop)
    c.absent("提示词不再写死「给派单员用的助手」", loop_code, r"给派单员用的助手")
    c.present("身份段按角色生成", loop_code, r"AiRolePrompt\.brief\(tools\.actor")
    c.present("有按角色分的身份提示词（[AiRolePrompt]）", role_prompt, r"object AiRolePrompt")
    c.present("货主有独立的身份段", role_prompt, r"SHIPPER_IDENTITY")
    c.present("派单员的身份段写明他是管理员", role_prompt, r"派单员（管理员）")
    c.present("认不出角色时 fail-closed（只说没认出，不列能力）", role_prompt, r"UNKNOWN_IDENTITY")
    c.present("「你能改的域」按角色算", loop_code, r"writeGroupsHint\(\)")
    c.present("「你能读几张表」按角色算", loop_code, r"readTableCount\(\)")
    c.absent("提示词里不再写死派单员口径的 36 张表", loop_code, r"地址与联系人等 36 张")
    c.absent("提示词里不再写死派单员的七个域", loop_code, r"【批发商定价】【库存】")
    c.present("「不知道就问」的例子也按角色给", loop_code, r"decideExamples\(\)")
    c.present(
        "[AiRolePrompt] 有单测（货主那段不许出现派单员能力名）",
        role_prompt_test,
        r"货主那份不许出现派单员的能力名",
    )
    c.present(
        "身份提示词这一节也有反向验证",
        read(Path(__file__).resolve().parent / "_reverse_verify_write_roles.py"),
        r"身份提示词",
    )

    # ---- 2g-8 工具本身也按角色裁（v3.28 真机实测抓到的**根因**）----
    # 提示词只是"照着工具清单说话"。清单里躺着「库存预警/司机跑车统计/出表格」，
    # 货主问"你能做什么"时它就会照着念，然后真去调 → 后端 403 → 只能回一句"没权限"。
    # 只裁说明不裁工具，等于没裁。
    tools_kt = AI_join("AiTools.kt")
    c.present("有按角色的工具白名单（只此一处）", tools_kt, r"val ROLE_TOOLS: Map<AiRole, Set<String>>")
    c.present("工具清单按角色过滤（不是只裁说明）", strip_comments(tools_kt), r"it in on && it in mine")
    c.present("设置页开关也按角色裁（否则给货主一个永远不生效的开关）", tools_kt, r"fun settingsItems\(actor: AiActor\?")
    c.present(
        "货主那份工具白名单是显式写出来的（能审计）",
        strip_comments(tools_kt),
        r"AiRole\.SHIPPER to setOf\(READ_DATA, REMEMBER, PREVIEW_WRITE\)",
    )
    c.present(
        "[工具角色白名单] 有单测（货主不许拿到库存预警/司机跑车统计/出表格）",
        role_prompt_test,
        r"工具本身也按角色裁",
    )

    # ---- 2g-9 只给用户要的（v3.28，用户一次说了三个方面）----
    # 原话：「AI 回答的时候没必要说的就不要说——不要说返回了什么什么，用户只要知道结果」/
    #      「权限不够的话不用说那么多，直接返回权限不够」/
    #      「大量商品或人员尽量用表格展示，全是文字用户根本没法看」。
    style = AI_join("AiAnswerStyle.kt")
    c.present("输出规则抽成单独一处（提示词和单测读同一份）", style, r"internal object AiAnswerStyle")
    c.present("规则：只讲结果、不讲过程", style, r"只讲结果，不讲过程")
    c.present("规则：不许复述字段/结构/返回条数", style, r"「返回了 N 条」")
    c.present("规则：权限不够只说一句", style, r"权限不够时\*\*只回一句\*\*")
    c.present("规则：权限不够时不给替代方案", style, r"不许列「我还能给你什么替代数据」")
    c.present("规则：条目超过 3 项优先用表格", style, r"\*\*超过 3 项\*\*")
    c.present("提示词拼的是这一份（不是另抄一遍）", strip_comments(loop), r"append\(AiAnswerStyle\.RULES\)")
    c.present(
        "读服务的角色门措辞短（不再长篇解释）",
        strip_comments(AI_join("AiReadService.kt")),
        r"权限不够。告诉用户这个查不了",
    )
    c.present(
        "403 映射措辞短（不再让模型照着念）",
        strip_comments(AI_join("AiTools.kt")),
        r"权限不够。一句话告诉用户这项他看不了",
    )
    c.present(
        "异常卡片的状态写中文（不再印后端枚举名）",
        strip_comments(ROOT.joinpath("android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt").read_text(encoding="utf-8")),
        r"statusLabel\(e\.status\)",
    )
    c.present(
        "「谁的异常」缺谁不显示谁（不用空壳占位）",
        strip_comments(ROOT.joinpath("android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt").read_text(encoding="utf-8")),
        r"val who = listOfNotNull\(",
    )
    c.present(
        "[输出规则] 有单测（只讲结果 / 权限一句 / 多条用表格）",
        read(ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiAnswerStyleTest.kt"),
        r"只讲结果",
    )
    # ⚠️ 结尾再钉一次：用户实机反馈「规则写在第 8.1 条里，模型照样解释一大段」。
    #    模型对提示词的**开头和结尾**最敏感，中间那 80 行它会读过去。
    c.present("提示词结尾再钉一次那两条", strip_comments(loop), r"【最后再确认两件事】")
    c.present(
        "结尾钉的是「一句话说完就停」和「超过 3 条用表格」",
        strip_comments(loop),
        r"不要解释原因、不要列你还能给什么、不要分点",
    )

    c.present("角色有同步缓存（工具清单是同步路径）", AI_join("../core/TokenStore.kt"), r"fun cachedRole\(\): String\?")
    # ==================================================== 2h 「这份数据属于谁」
    #
    # v3.13 真机 E2E 抓到的隐私问题：AI 的三份本机数据（对话/习惯/记忆）用固定文件名，
    # 同一台手机上换账号能读到上一个人的全部聊天内容。
    #
    # ⚠️ **它不是任何一条既有红线的违例**——当时 281 条检查全过，
    # 因为**没有一条在问"这份数据属于谁"**。所以这一节补的就是那个问题本身。
    print("\n== 2h. 本机数据必须按用户分区（同机换账号不许串）==")
    c.present("有分区规则", AI_join("AiScope.kt"), r"internal object AiScope")
    c.present("读不到用户时落到 anon，**绝不回落到公共区**", AI_join("AiScope.kt"), r"const val ANON")
    c.present("旧的无分区文件是**隔离**而不是被继承", AI_join("AiScope.kt"), r"fun quarantineLegacy\(")
    for n in ("AiConversationStore", "AiMemoryStore", "AiHabitStore"):
        # ⚠️ 这个模式必须用**单引号**的 Python 字符串：r"..." 会在第一个 " 处结束，
        # 于是模式实际变成 `scope: String = `（丢了引号）——一条永远匹配得上的检查。
        # 第一版就是这么写的，是反向验证时发现它"永远通过"才改过来的。
        c.present(f"{n} 接受分区参数", AI_join(f"{n}.kt"), r'scope: String = "",')
    c.present("对话文件按分区命名", AI_join("AiConversationStore.kt"), r"AiScope\.fileName\(FILE_NAME, scope\)")
    c.present("记忆文件按分区命名", AI_join("AiMemoryStore.kt"), r"AiScope\.fileName\(FILE_NAME, scope\)")
    c.present("习惯用分区后的 prefs 名", AI_join("AiHabitStore.kt"), r"PREFS_NAME \+ scope")
    c.present("容器按分区**重建**三个 store", AI_join("AiContainer.kt"), r"private fun ensureScoped\(\)")
    # ⚠️ 这一条守的是一个具体的写法陷阱：by lazy 会把 store 连同**首次访问时的分区**
    # 一起缓存住，而容器是 remember 出来的（一次会话只建一次）——
    # 于是换账号后仍然返回上一个人的 store，等于没修。实测正是这么踩的。
    c.absent("三个 store 不许再用 by lazy（会把首次访问的分区缓存住）", AI_join("AiContainer.kt"), r"by lazy \{ Ai(ConversationStore|HabitStore|MemoryStore)\(")
    c.present("用户 id 有同步缓存（分区名是同步路径）", AI_join("../core/TokenStore.kt"), r"fun cachedUserId\(\): Long\?")
    c.present("导航层把 userId 传进容器", AI_join("../ui/nav/NavGraph.kt"), r"userIdKey = \{ container\.tokenStore\.cachedUserId\(\) \}")
    # ⚠️ 上面那三份查得很全，**唯独漏了凭据那份**（2026-09-19 审计 P0-6）：
    #    `AiKeyStore` 用固定串 prefs 名、容器里还是 `by lazy`，于是同机换账号后
    #    下一个登录的人能读出上一个人的**明文 LLM Key**（可计费活凭据），账单也记在上一人头上。
    #    这是本项目第 6 次栽在「要检查哪些文件的清单是手写的」——所以这四条不是补充说明，
    #    它们是这一节**唯一能挡住"凭据不分区"的东西**（凭据是最贵的那份数据）。
    c.present("凭据 store 也用分区后的 prefs 名", AI_join("AiKeyStore.kt"), r"PREFS_NAME \+ scope")
    # 用单引号的 Python 串：r"..." 会在模式里的第一个 " 处结束（同上面 1253 行那条教训）
    c.absent("凭据不许再用固定串 prefs 名", AI_join("AiKeyStore.kt"), r'getSharedPreferences\("sorders_ai_prefs"')
    c.present("旧的无分区凭据文件是**隔离**而不是被继承", AI_join("AiKeyStore.kt"), r"AiScope\.quarantineLegacy\(")
    c.present("凭据 store 纳入分区重建（构造时拿到 scope）", AI_join("AiContainer.kt"), r"AiKeyStore\(appContext, s\)")
    c.absent("凭据 store 不许再用 by lazy（与那三个 store 同理）", AI_join("AiContainer.kt"), r"by lazy \{ AiKeyStore\(")

    # ---- 2g-5 批量调价：范围不能全空 ----
    # 这是这条链路上最危险的一种误用：一句「全部涨价」就把整张价格表改了。
    # 幅度写错是**全面的偏差**（一眼能看出来）；范围写错是**一部分人价格变了、另一部分没变**，
    # 而这两拨人自己不会知道。所以范围必须被强制收窄，且卡片上要能一眼看出范围。
    wpricing = AI_join("AiWritePricing.kt")
    c.present(
        "批量调价必须拒绝「批发商和商品都留空」（防全表调价）",
        wpricing,
        r"范围太大了：批发商和商品都没指定",
    )
    c.present("调价前把 before→after 算出来摆到卡片上", wpricing, r"c\.before.*c\.after|before.*→.*after")
    c.present("卡片写明会覆盖已有专属价", wpricing, r"这会覆盖这些批发商")
    c.present("adjust 与 price 二选一（同时给要拒绝）", wpricing, r"只能给一个")
    c.present("百分比有自己的解析器（不复用金额上限那条规则）", wpricing, r"private fun parsePercent\(")
    # 用户说的是「在现有价基础上涨/降」，而后端 percent 模式算的是「默认价×百分比」——
    # 这两种搞混了不会报任何错，只会静默算错钱。所以两边都得写明这条区别。
    c.present(
        "后端 adjust 模式按当前生效价算（不是默认价）",
        read(ROOT / "backend" / "app" / "api" / "v1" / "price_rules.py"),
        r"pr\.special_unit_price if pr is not None else",
    )
    c.present(
        "客户端 DTO 也写明了两种模式的区别",
        AI_join("../data/remote/api/Apis.kt"),
        r"只会静默算错钱",
    )

    print("\n== 2c. 记忆必须可查看、可编辑、可删除 ==")
    mem = AI_join("AiMemory.kt")
    mem_store = AI_join("AiMemoryStore.kt")
    c.present("有独立的记忆数据模型", mem, r"data class AiMemoryItem")
    c.present("记忆与使用习惯分开（前者用户教的、后者机器数的）", mem, r"AiHabit")
    c.present("单条可改", mem, r"fun updateFact\(")
    c.present("单条可删", mem, r"fun remove\(")
    c.present("可按主体分组展示（设置页摊开给用户看）", mem, r"fun grouped\(")
    c.present("有总开关，且默认开", AI_join("AiKeyStore.kt"), r"fun memoryEnabled\(\): Boolean = prefs\.getBoolean\(KEY_MEMORY_ENABLED, true\)")
    c.present("落盘在 App 私有目录（不是外部存储）", mem_store, r"filesDir")
    # ⚠️ 2026-09-21：下面三条原来钉在 `AiMemoryStore.kt` 的实现体上，而那份实现已经和
    #    `AiConversationStore` 一起收进了 `AiJsonStore`（两份各抄了一遍约 120 行）。
    #    判据现在钉**共用的那一处**，并额外要求记忆存储**确实接到了它**——
    #    否则"实现搬走了、记忆这边没接上"会变成一句静默失效（用户教的东西照样丢）。
    c.present("记忆走的是共用的文件仓储（不是自己又写一遍）", mem_store, r"private val store = AiJsonStore\(")
    c.present("写盘是「先写临时文件再改名」（半截文件会丢掉用户教的东西）", jsonstore, r"tmp\.renameTo\(file\)")
    c.present("坏文件改名留证，不静默覆盖", jsonstore, r"\.bad-\$\{System\.currentTimeMillis\(\)\}")
    c.present(
        "任何异常都不抛（记忆存不下不该让聊天挂掉）",
        jsonstore,
        r"fun save\(list: List<T>\): Boolean = try \{",
    )
    c.present("与对话历史同一条隐私边界（不上传）", mem_store, r"绝不上传服务器")
    c.present("注入必须写明「以用户这次说的为准」（记忆会过期）", mem, r"以用户这次说的为准")
    c.present("注入必须要求不要复述（用户知道自己教过什么）", mem, r"不要把这些内容念出来")
    c.present("注入有条数上限", mem, r"MAX_HINT_ITEMS")
    c.present("注入有字符预算", mem, r"MAX_HINT_CHARS")
    c.present("全库有条数上限（没有上限的记忆系统必然烂掉）", mem, r"MAX_ITEMS = \d+")
    c.present("单主体有条数上限", mem, r"MAX_FACTS_PER_SUBJECT")
    c.present("重复说同一件事不新增条目", mem, r"normalizeFact\(it\.fact\) == normalizeFact\(f\)")
    c.present("记忆注入排在摘要之后、习惯之前（越靠前越硬）", AI_join("AiContainer.kt"), r"fun systemExtra\(memoryHint: String\?, habitHint: String\?, summary: String\?\)")

    print("\n== 2b. 通用读工具（读所有列表）的红线 ==")
    reader = read(AI / "AiReadService.kt")
    catalog_kt = read(AI / "AiReadCatalog.kt")
    c.present("目录是机器生成的（写了生成脚本与 --check）", catalog_kt, r"_gen_ai_read_catalog\.py")
    c.present("路径只能从编译期白名单里查（不接受任意 URL）", reader, r"AiReadCatalog\.find\(")
    c.absent("读服务里不许拼任意 URL / 不许自己 new Retrofit", reader, r"Retrofit\.Builder")
    c.present("模型给的 action 查不到就报错（不许回落到猜）", reader, r"没有名为「")
    c.present("编号按**名字**在 App 侧解析，模型全程拿不到编号", reader, r"private suspend fun resolveId\(")
    c.present("extra 里塞编号是硬错误（不是忽略）", reader, r"是编号类筛选条件，你不能填编号")
    c.present("不支持的筛选条件要如实回报", reader, r"ignored_filters")
    c.present("替模型补的必填项要如实回报", reader, r"assumed_filters")
    c.present("两层开关：工具级 + 模块级", keystore, r"fun enabledReadModules\(")
    c.present("提示词里写了「先去查，不要直接说查不了」", loop, r"先去查，不要直接说")
    c.present("路径必须是完整路径（踩过：相对路由前缀导致 404）", AI_join("AiReadCatalog.kt"), r'"/api/v1/')

    # ---- 2b-2 读能力也按角色裁剪（v3.15）----
    #
    # 起因：36 张表原来是**派单员视角**的整份目录，货主拿到的是同一份。实测（对真后端逐条打）
    # 货主调 users / operation-logs / reports / stats / inventory / order-products 全是 403——
    # 他问一句，模型去查一张查不了的表，只能回"查不到"。写侧早有白名单，读侧一直漏着。
    print("\n== 2b-2. 读数据也按角色裁剪（写有白名单，读也有）==")
    reads = read(AI / "AiReads.kt")
    c.present("有读侧角色闸门", reads, r"object AiReads")
    c.present("角色映射到后端角色名（目录里的 roles 用的就是后端那套键）", reads, r'AiRole\.DISPATCHER -> "dispatcher"')
    c.present("按 roles 过滤（不是「全给」）", reads, r"k in it\.roles")
    c.present("认不出角色就返回空（fail-closed）", reads, r"val k = key\(actor\?\.role\) \?: return emptyList\(\)")
    c.present("服务侧默认不认角色（刻意不默认成派单员，免得忘了传还静悄悄放行）", reader, r"private val actorProvider: \(\) -> AiActor\? = \{ null \}")
    # ⚠️ 2026-09-23：读侧这条默认值早就是 fail-closed（上面那条），而**写侧与工具清单**
    #    两处还是 `{ AiRole.DISPATCHER }` —— 同一个仓库里同一条纪律只落了一半。
    #    后果不是"少给能力"，而是"**多给**"：新加一个装配点忘了传 provider，拿到的是
    #    权限最大的那个角色的清单与动作集，不报错、也没人会发现（fail-open 的经典形状）。
    c.present("写侧默认也不认角色（与读侧同一条纪律）", wsvc, r"private val actorProvider: \(\) -> AiActor\? = \{ null \}")
    c.present("工具清单默认也不认角色（忘了传时给空清单，不是给派单员的）", tools, r"private val roleProvider: \(\) -> AiRole\? = \{ null \}")
    c.present("读之前先问角色闸门", reader, r"if \(!AiReads\.allows\(role, action\.action, enabledModules\(\)\)\)")
    c.ok(
        "**角色检查排在发请求之前**（排在后面等于查完了才告诉他没权限）",
        reader.find("AiReads.allows(") >= 0
        and reader.find("AiReads.allows(") < reader.find("repo.rawGet("),
        f"allows@{reader.find('AiReads.allows(')} / rawGet@{reader.find('repo.rawGet(')}",
    )
    c.present("read_data 的说明按角色现拼", tools, r"private fun readDataSpec\(actor: AiActor\?\)")
    c.present("说明清单来自 AiReads", tools, r"AiReads\.describeForModel\(actor, readModules\(\)\)")
    c.present("enum 也按角色裁（只裁说明=模型照抄一个它调不了的动作）", tools, r"AiReads\.forRole\(actor, readModules\(\)\)")
    # ⚠️ 上面那条只证明"文件里出现过 forRole"，证明不了 enum 用的是它。
    #    第一版就是这么写的，反向验证时把 enum 改回全量目录**居然还是绿的**——所以补这条：
    #    工具定义里不许回落到全量目录（说明与 enum 必须同源）。
    #    也不能用 fn_body()：它是给**顶层函数**写的（找顶格的 `}`），而这里是类成员函数，
    #    它会一路吃到类的结尾，把下面静态 SCHEMAS 里的 AiReadCatalog.ACTIONS 也算进来——那样这条永远红。
    c.absent(
        "read_data 的 enum 不许回落到全量目录",
        block_between(tools, "private fun readDataSpec(", "private fun previewWriteSpec("),
        r"AiReadCatalog\.ACTIONS",
    )
    # ---- read_data 的公共筛选项只许有一份（2026-09-21 精简轮）----
    # 那 7 个参数（name/q/from/to/status/limit/extra）原来在 `AiTools.kt` 里**逐字抄了两遍**：
    # 实例侧的动态 spec + companion 的静态表 `SCHEMAS`（各 43 行）。而 `specs` 里
    # `READ_DATA -> readDataSpec(actor)` 是**显式分支**、`specOf`（唯一读 SCHEMAS 的地方）只在
    # `else ->` 上 —— 也就是静态那份**一个读者都没有**（`readDataSpec` 那句注释还写着
    # "参数部分与静态那份一致"，说明当年是**以为它还在用**才留着两份的）。已删。
    # 判据三条（少一条都不够）：
    #   ① 静态表里不许再有 read_data 的条目（否则又是一份没人读的定义）；
    #   ② 那几条特征描述在全文件里**各只出现 1 次**（== 2 就是又抄了一遍；== 0 就是被删了）；
    #   ③ 它们必须在 `readDataSpec` 里 —— 光数"只有一份"证明不了那一份**在能用的地方**。
    c.absent(
        "静态 SCHEMAS 里不许再有 read_data 的第二份定义（那份没人读）",
        block_between(tools, "private val SCHEMAS", "private val DESCRIPTIONS"),
        r"READ_DATA to buildJsonObject",
    )
    c.present(
        "READ_DATA 走动态 spec（静态那份就是因此才没人读的）",
        tools,
        r"READ_DATA -> readDataSpec\(actor\)",
    )
    read_spec_body = block_between(tools, "private fun readDataSpec(", "private fun previewWriteSpec(")
    common_filters = (
        "要筛的具体",
        "通用关键词（这个接口支持 q 时生效）",
        "起始日期 YYYY-MM-DD（接口用",
        "状态筛选（接口支持 status 时生效）",
        "其它筛选条件的 JSON 字符串",
    )
    for s in common_filters:
        c.ok(
            f"read_data 的筛选项「{s[:12]}…」全文件只 1 处且在 readDataSpec 里",
            tools.count(s) == 1 and s in read_spec_body,
            f"全文件 {tools.count(s)} 次（2 = 又抄了一遍；0 = 被删了）、"
            f"在 readDataSpec 里={s in read_spec_body}",
        )
    # ⚠️ 只钉描述串不够（2026-09-21 反向验证当场抓到）：把**键名**改掉（`status` → `statusX`）
    #    描述串还在、计数还是 1，判据照样绿 —— 而模型拿到的参数名已经错了（它会照着 schema 拼参数）。
    #    所以 7 个键名也逐个钉在 `readDataSpec` 里。
    filter_keys = ("name", "q", "from", "to", "status", "limit", "extra")
    missing_keys = [k for k in filter_keys if f'putJsonObject("{k}")' not in read_spec_body]
    c.ok(
        "read_data 的 7 个筛选参数键都在 readDataSpec 里（键名也是模型照抄的东西）",
        not missing_keys,
        f"缺：{missing_keys}",
    )
    c.present("目录里每张表都带 roles", catalog_kt, r"val roles: Set<String>")
    c.present(
        "角色是从后端授权推导的（不是手抄）",
        read(Path(__file__).resolve().parent / "_gen_ai_read_catalog.py"),
        r"def endpoint_roles\(\)",
    )
    c.present(
        "有实测对账脚本（改后端鉴权后先跑它）",
        read(Path(__file__).resolve().parent / "_probe_read_roles.py"),
        r"每个角色的读权限都与实测一致",
    )
    # 反向验证脚本必须把「探针没跑成」和「检查没红」区分开：本机后端没开时探针非零退出，
    # 旧版把这种环境故障显示成「实测对账居然全过」——正是本仓库反复栽的"假绿灯"。
    c.present(
        "反向验证区分「没验成」与「检查没红」（后端没开时不许显示成通过）",
        read(Path(__file__).resolve().parent / "_reverse_verify_read_roles.py"),
        r"没验成：探针退出码",
    )

    # ---- 2b-3 本机能力：读手机定位 + 按当前位置选点（2026-09-21）----
    #
    # 用户原话：「ai 它要具备读取手机的地点的能力，因为 ai 它是要具备所有功能…包括用户不是我们
    # 要去手动选地点吗？它也可以去选地点，**这个权限给它开啊**」。
    #
    # 这一族坏掉的五种方式**一种都不会报错**，所以逐条钉（每条都想清楚了"哪种改法会让它红"）：
    #   ① 坐标泄漏进模型上下文（本仓第一条硬规矩）；
    #   ② 本机能力混进机器生成的目录（生成器一跑就抹掉；`_probe_read_roles.py` 还会拿空路径打后端）；
    #   ③ 它绕开角色或模块那两道门（定位是隐私，用户必须关得掉）；
    #   ④ 句柄「当前位置」落到地理编码那条路（地址文字是逆地理出来的，再正向查一次会漂点）；
    #   ⑤ 参数说明里承诺了句柄、动作却不解析它（字面量被写进地址库）。
    print("\n== 2b-3. 本机能力（读手机定位）==")
    local_reads = read(AI / "AiLocalReads.kt")
    loc_kt = read(AI / "AiLocation.kt")
    wcrud = read(AI / "AiWriteCrudHandlers.kt")
    wbdata = read(AI / "AiWriteBasicData.kt")
    c.present("本机能力有一处手写声明（不进机器生成的那份）", local_reads, r"object AiLocalReads")
    c.present("靠 path 为空区分本机能力（不给 ReadAction 加字段：生成器一跑就没了）",
              local_reads, r'path = "",')
    c.absent("机器生成的目录里不许出现本机能力", catalog_kt, r"location\.current")
    c.absent(
        "生成器里也不许塞本机能力（它没有后端端点，`--check` 必红）",
        read(Path(__file__).resolve().parent / "_gen_ai_read_catalog.py"),
        r"location\.current",
    )
    c.present(
        "实测对账脚本会挡掉「本机能力混进生成目录」（那种条目没有后端端点可打）",
        read(Path(__file__).resolve().parent / "_probe_read_roles.py"),
        r"本机能力不该出现在这份生成目录里",
    )
    # ① 坐标绝不进模型可见的输出
    # ⚠️ 这三条走 `strip_comments`：判据是**代码**形状的，而这些文件的注释里恰好要写清
    #    "为什么不用系统定位 / 为什么坐标不外泄"（连注释一起扫就会假红，假红迟早被人改松）。
    c.absent("本机读能力那一份里不许出现经纬度（只回地址文字）",
             strip_comments(local_reads), r"\blat\b|\blng\b|latitude|longitude")
    c.present("执行侧认「path 为空」走本机分支（不拼 URL、不碰 Retrofit）",
              reader, r"if \(action\.path\.isBlank\(\)\) return AiLocalReads\.run\(")
    # ② 与后端表同一道门（角色 + 模块）
    c.present("角色与模块的过滤只看合起来的那一份清单", reads, r"return allActions\(\)\.filter \{")
    c.present("模块白名单含本机模块（否则开关根本不存在、能力被静默过滤掉）",
              keystore, r"val all = AiReads\.allModules\(\)\.toSet\(\)")
    c.present("设置页按同一份模块清单列开关", settings_vm, r"AiReads\.allModules\(\)\.filter \{ it in mine \}")
    c.present("说明里标出「本机」（不标模型会拿它当一张地址表）", reads, r"〔本机")
    # ③ 写侧：句柄的解析只有一处，且两条路都不许漂点
    c.present("句柄的解析只有一处（三个地址入口共用同一条分叉）",
              wsvc, r"AiLocation\.resolveAddress\(text, provider = null, geocode = \{ geocode\(it\) \}\)")
    c.present("生产实现把定位提供者接进去",
              wsvc, r"AiLocation\.resolveAddress\(text, locationProvider\(\), geocode = \{ geocode\(it\) \}\)")
    c.present("先问权限再发起定位（没授权时高德一个回调都不会有）",
              loc_kt, r"if \(!provider\.permitted\(\)\) throw AiWriteArgException\(NO_PERMISSION\)")
    c.present("高德失败值 (0,0) 复用全仓唯一那份判据挡掉", loc_kt, r"SunLocation\.isPlausible\(p\.lat, p\.lng\)")
    c.absent("导航坐标不许退到系统定位（WGS84 在国内差几百米，界面上看不出来）",
             strip_comments(loc_kt), r"DeviceLocation")
    c.present("一定有超时（高德回调不保证回来，卡住＝用户以为 AI 死了）",
              loc_kt, r"withTimeoutOrNull\(TIMEOUT_MS\)")
    c.present("串行：同一时刻只允许一次定位在飞", loc_kt, r"lock\.withLock")
    c.present("先订阅再发起（SharedFlow 无 replay，反了就是每次都超时且不报错）",
              loc_kt, r"CoroutineStart\.UNDISPATCHED")
    c.absent("定位那一份不打日志（坐标不进日志）", strip_comments(loc_kt), r"Log\.[diwe]\(")
    c.ok(
        "地址类参数的提示里给了句柄（不写的话模型只会编一个地址）",
        wbdata.count("+ HERE_HINT") >= 4,
        f"实际 {wbdata.count('+ HERE_HINT')} 处",
    )
    # ④ 地址栏写的是解析后的那一份文字
    c.present("句柄解析出来的真实地址要写在卡上（用户核对不了就等于没核对）",
              wcrud, r"private fun hereNote\(")

    # ---- 2b-4 老白名单要补上"他保存时还不存在的模块"（2026-09-21 用户拍板）----
    #
    # 用户原话：「ai 它要具备读取手机的地点的能力……**这个权限给它开啊**」——
    # 更新完就该能用，⛔ 不许让老用户自己去设置页里翻出那个新开关。
    # 三条语义由单测逐条钉着（`AiLocalReadsTest` ⑦ 那一节：默认开 / 老数据补上 / 明确关掉要记住）；
    # 这里钉**源码形状** —— 少任何一条，"老用户装了没反应"就会静默复发
    # （本仓在 `enabledTools` 上已经栽过一次：记忆功能就这样哑了）。
    print("\n== 2b-4. 老白名单补新模块 ==")
    c.present("合并规则收在一处纯函数（`AiKeyStore` 那层只有 SharedPreferences，测不动）",
              reads, r"fun resolveEnabled\(saved: Set<String>, knownAtSave: Set<String>\?\)")
    c.present("『保存之后新出现的模块』由标记算出来（= 现在全集 − 保存时已知）",
              reads, r"knownAtSave\?\.let \{ all - it \}")
    c.present("旧数据（没有标记）只补本机能力这一类（后端模块分不出关掉的与当时还没有的）",
              reads, r"\?: AiLocalReads\.MODULES\.toSet\(\)")
    c.present("空集按老约定当『全关』，不许被当成枚举去补新模块（否则是把用户关掉的又打开）",
              reads, r"if \(saved\.isEmpty\(\)\) return emptySet\(\)")
    c.present("保存白名单时记下『当时的全部模块』",
              keystore, r'putString\(KEY_READ_MODULES_KNOWN, AiReads\.allModules\(\)\.joinToString\(","\)\)')
    c.present("读白名单时把标记一起读出来（旧数据没有它 → null）",
              keystore, r"knownAtSave = if \(prefs\.contains\(KEY_READ_MODULES_KNOWN\)\)")
    c.present("读侧走那条纯函数（而不是自己 intersect 一份）", keystore, r"AiReads\.resolveEnabled\(")


    print("\n== 3. 最终答复必须过净化器 ==")
    c.present("思考过程过净化器", loop, r"AiEvent\.Reasoning\(AiAnswerSanitizer\.clean")
    c.present("提示词里有编号禁令", loop, r"绝不允许出现任何内部编号")
    c.present("净化器认得 *_id 形状", sanitizer, r"_\?id")
    c.present("净化器认得「货主#122」形状", sanitizer, r"HASH_ID")
    # 顺着「最终答复那个变量」往回追。为什么盯 Success 而不是盯 TextDelta：
    # 界面的权威文本取的是 `AiRunResult.Success.text`（TextDelta 只是先渲染出来），
    # 所以**只要它没净化，编号就一定会显示**；反过来只净化 TextDelta 是没用的。
    # 另外 TextDelta 在"超过最大步骤数"那条分支里也出现，那是我们自己写的固定文案，
    # 所以不能简单断言"第一处 TextDelta 必须净化"。
    #
    # ⚠️ v3.5 流式改造后这里放宽了正则（允许带额外参数），但**同时加严了断言**：
    # 流式下正文会先一段段渲染出来，所以权威文本必须用 `replace = true` 送出去，
    # 否则屏幕上会 ① 同一段回答出现两遍；② 残留过程预览里净化前的片段。
    # ⚠️ v3.33 又踩了同一类坑（第三次）：这条正则原来只认**位置参数**
    # `AiRunResult.Success(finalText, …)`。有人（我）把返回值改写成**具名参数**
    # `Success(text = finalText, …)` 之后，正则抓到的第一个标识符变成了**参数名** `text`，
    # 于是三条判据全红——**而代码其实完全正确**。
    # 所以这里吃掉可选的 `名字 = ` 前缀：两种写法都认，判据仍然盯"那个变量"。
    succ = re.search(
        r"AiRunResult\.Success\(\s*(?:[A-Za-z_][A-Za-z0-9_]*\s*=\s*)?([A-Za-z_][A-Za-z0-9_]*)",
        loop,
    )
    delta_calls = re.findall(r"AiEvent\.TextDelta\(\s*([A-Za-z_][A-Za-z0-9_]*)([^)]*)\)", loop)
    delta_vars = [name for name, _ in delta_calls]
    if succ is None:
        c.ok("能定位到最终答复的返回点", False, "没匹配到 `AiRunResult.Success(<变量>)`")
    else:
        v = succ.group(1)
        c.ok(
            f"权威答复 `{v}` 来自 AiAnswerSanitizer.clean",
            re.search(rf"(?:val|var)\s+{v}\s*=\s*AiAnswerSanitizer\.clean\(", loop) is not None,
        )
        c.ok(
            f"送到界面的也是同一份 `{v}`（不能净化一份、送另一份）",
            v in delta_vars,
            f"TextDelta 实际传的是 {delta_vars}",
        )
        tails = [tail for name, tail in delta_calls if name == v]
        c.ok(
            f"权威答复 `{v}` 必须以替换语义送出（流式下追加会让回答出现两遍）",
            any("replace" in t and "true" in t for t in tails),
            f"实际参数尾={tails}",
        )

    print("\n== 3b. 流式（SSE）必须自己解析且可脱网单测 ==")
    stream = AI_join("AiStream.kt")
    c.present("流式解析抽成纯类（不碰 Android，能 JVM 单测）", stream, r"class ChatStreamAccumulator")
    c.present("工具调用按 index 归并（漏了会少执行工具）", stream, r"sortedMapOf<Int, ToolCallBuilder>")
    c.present("arguments 按顺序拼接而非覆盖", stream, r"args\.append\(")
    c.present("认 [DONE] 哨兵", stream, r"DONE_SENTINEL")
    c.present("留尾净化（防止编号短语跨分片漏出）", stream, r"class AiStreamingText")
    c.present("流结束后把留尾交出去（否则结尾缺字）", loop, r"streaming\.finish\(\)")
    c.present("流式有降级路径：端点不认 stream_options 就去掉重试", client, r"streamOptionsRejected")
    c.present("流式重试有上限（不能对不认字段的端点无限重试）", client, r"MAX_STREAM_ATTEMPTS")
    c.present("已吐字就不许重试（否则回答会出现两遍）", client, r"emittedChars > 0")
    c.present("端点无视 stream 时回退按非流式解析", client, r"!acc\.sawSseData")
    c.present("非流式**不许**下发 stream_options（自选字段多一个多一分被拒风险）", client, r"if \(stream && includeStreamOptions\)")
    c.present("思考过程仍然只按轮交付（逐片发会变成几百条分隔线）", stream, r"reasoningContent")
    c.present("StreamOptions 走非模型可控的默认值（include_usage=true）", stream, r"includeUsage: Boolean = true")

    print("\n== 4. 聊天历史必须有硬上限 ==")
    c.present("有对话条数上限", conv, r"const val MAX_CONVERSATIONS")
    c.present("有单对话消息数上限", conv, r"const val MAX_MESSAGES_PER_CONVERSATION")
    c.present("有盘上字节预算", conv, r"const val MAX_FILE_BYTES")
    c.present("encode 自带预算闸（走 fitToBudget）", conv, r"conversations = fitToBudget\(list\)")
    c.present("写盘是「先写临时文件再改名」（唯一实现在 AiJsonStore）", jsonstore, r"tmp\.renameTo\(file\)")

    print("\n== 5. 落盘链路确实接上了 ==")
    c.present("ViewModel 会调 store.save", vm, r"ai\.conversations\.save")
    c.present("ViewModel 启动时读历史", vm, r"ai\.conversations\.load")
    c.present("存盘串行化（避免旧快照盖新快照）", vm, r"saveMutex\.withLock")
    # 这一条是一次真实丢历史事故的回归：
    # ViewModel 的 all 是异步读进来的，读进来之前落盘会把盘上原有对话覆盖成"只有当前这一段"。
    c.present("读盘完成前不落盘（防覆盖丢历史）", vm, r"if \(!loaded\)")
    # ⚠️ 2026-09-21：这条兜底与"先写临时文件再改名"原来钉在 `AiConversationStore.kt` 上，
    #    而那份实现已经和 `AiMemoryStore` 一起收进了 `AiJsonStore`（两个 store 各抄了一遍
    #    同样的约 120 行）。判据跟着挪，并**加了两条**"两个 store 都真的把合并函数接上了"——
    #    只钉"某个文件里出现过某段字符串"会退化：实现改名/搬家之后判据仍绿，而那条兜底
    #    可能压根没接上（这正是它当年守的那次丢历史事故的形状）。
    c.present(
        "存储层也没读过盘时改合并（唯一实现在 AiJsonStore）",
        jsonstore,
        r"if \(everLoaded\) list else merge\(readSilently\(\), list\)",
    )
    c.present("对话存储把合并函数接上了", store, r"merge = AiConversations::mergeById")
    c.present(
        "记忆存储把合并函数接上了",
        AI_join("AiMemoryStore.kt"),
        r"merge = \{ disk, mine -> mergeById\(disk, mine\) \}",
    )
    c.present("合并函数存在且是纯逻辑", conv, r"fun mergeById\(")

    print("\n== 6. 界面上用户明确提过的几件事 ==")
    c.present("发送键是向上箭头", screen, r"Icons\.Default\.ArrowUpward")
    c.absent("发送键不再用纸飞机", screen, r"Icons\.AutoMirrored\.Filled\.Send")
    c.present("输入行垂直居中", screen, r"verticalAlignment = Alignment\.CenterVertically")
    c.present("左侧历史抽屉", screen, r"ModalNavigationDrawer")
    c.present("抽屉里有历史列表", screen, r"private fun HistoryDrawer")
    c.present("顶栏有独立的新对话按钮", screen, r'contentDescription = "新对话"')
    c.absent("顶栏不再有「更多」二级菜单", screen, r'Text\("更多"\)')
    c.present("消息上直接有「复制」图标按钮", screen, r'MessageAction\("复制"')
    c.present("消息上直接有「分支」图标按钮", screen, r'MessageAction\("分支", Icons\.AutoMirrored\.Filled\.CallSplit\)')
    # ⚠️ 用户消息上**不许有**「重问」：原话「不要有重问这个选项，因为再充一遍也没有意义」。
    # 取而代之的是「编辑」——改完重发会撤掉原来的回答（改写历史），见 AiChatViewModel.applyPendingEdit。
    c.absent("用户消息上没有「重问」（用户明确否掉）", screen, r'"重问"')
    c.present("用户消息上给的是「编辑」", screen, r'MessageAction\("编辑", Icons\.Default\.Edit\)')
    c.present("编辑发送时先撤掉这条之后的对话", vm, r"messages = messages\.take\(idx\)")
    c.present("编辑态有显式提示条（撤对话这件事必须提前说）", screen, r"正在编辑这条消息")
    c.absent("长按菜单里也没有「重新问」", screen, r"从这里重新问")
    c.present("分支有横杠标记", screen, r"private fun BranchBar")
    c.present("抽屉行显示用量", screen, r"item\.tokenLabel")
    c.present("抽屉行标出分支", screen, r'" · 分支"')

    print("\n== 7. 模型答复的表格要画成真表格 ==")
    richtext = read(UIAI / "AiRichText.kt")
    c.present("答复走富文本渲染（不再是纯 Text）", screen, r"AiRichText\(")
    c.present("富文本里有表格渲染", richtext, r"private fun MdTable")
    c.present("表格列宽按内容分配", md, r"fun columnWeights\(")
    c.present("解析器认表格块", md, r"data class Table\(")
    c.present("会丢掉 Markdown 分隔行（|---|---|）", md, r"fun isSeparatorRow\(")
    c.present("加粗**解析", md, r"fun inline\(")

    print("\n== 8. AI 入口的落位（角色不同位置不同；每个非司机角色恰好一个）==")
    # v3.14（用户 2026-09-15 反馈）：货主端底部只有 3 个 Tab（工作台/消息/我的），
    # 中间插一个占位后凸起圆钮落在 **1/4 处**（偏左的第二个槽位）——不对称，看着像排错了。
    # 于是货主端改成工作台网格里的一个图标（排第一格），颜色从品红改成蓝。
    # 派单端是 4 Tab + 圆钮 = 5 槽正中，保持不变。
    # 这一节守的是三件事：**位置各自成立**、**每个角色恰好一个入口**、**司机一个都没有**。
    modules = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Modules.kt")
    home = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/home/RoleHomeScreen.kt")
    workbench = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/home/WorkbenchScreen.kt")
    color = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt")
    brand = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/AiBrand.kt")

    # ---- 夜间模式：暗色下**必须还能分层** ----
    # ⚠️ 这里守的是一个已经发生过的错误：`BackgroundDark` 和 `SurfaceDark` 原来都是 `#111318`，
    #    而全 App 的卡片（`SectionCard`）用的就是 `surface` —— 于是暗色下**卡片和背景同色**，
    #    卡片看不出边界、分组看不出分界（用户 2026-09-18：「有些卡片都不是很明显，信息丢失」）。
    #    亮色能分层靠的是"白卡 + 灰底"，暗色只能靠"亮一档的灰 + 更黑的黑"。
    def _hex(name: str) -> str | None:
        m = re.search(rf"val {name} = Color\(0xFF([0-9A-Fa-f]{{6}})\)", color)
        return m.group(1).upper() if m else None

    bg_d, surf_d = _hex("BackgroundDark"), _hex("SurfaceDark")
    c.ok(
        "暗色的 surface 必须**亮于** background（否则卡片和底同色 = 没有分层）",
        bool(bg_d and surf_d) and int(surf_d, 16) != int(bg_d, 16) and int(surf_d[:2], 16) > int(bg_d[:2], 16),
        f"background=#{bg_d} surface=#{surf_d}",
    )
    # 暗色里 shadowElevation 几乎看不见，分层只能靠色差 → 卡片要补淡描边
    components = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt")
    c.present("暗色下卡片补一条描边（黑影看不见）", components, r"border = if \(ThemeMode\.isDark\)")
    c.present("徽章配色按明暗两套（浅底直接搬过去会刺眼）", components, r"fun badgeColors\(")
    c.absent(
        "状态的浅粉彩底不许直接写进 Surface（暗色下会变成发光色块）",
        components,
        r'Triple\("(已派单|派单中|已接单|已送达|已撤销)", Color\(0xFFF',
    )
    # ---- 根节点必须自己铺背景 + 外观模式必须持久化 ----
    # ⚠️ 两条都是用户 2026-09-18 报上来的**真 bug**：
    #   ① 根节点只有 `SOrdersTheme { AppRoot(...) }`，没铺背景 → 凡是"自己没画底"的页面
    #      （实测：从工作台进的独立「消息中心」）会露出**窗口底色（白）**，夜间模式下是一块白板。
    #      底部 Tab 里正常，所以只有**独立路由**会露头，最容易漏。
    #   ② `ThemeMode.isDark` 原来只在内存里，切了夜间模式**杀掉 App 就变回白天**。
    main_act = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/MainActivity.kt")
    theme = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Theme.kt")
    # ⚠️ 2026-09-21：白天/夜间那两个开关搬进了「我的 → 基础设置」子页（`BasicSettingsScreen.kt`），
    #    所以这一组"设置页"判据也**同时看两个文件**（否则会变成"永远找不到"）。
    profile = (read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileScreen.kt")
               + "\n"
               + read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/BasicSettingsScreen.kt"))
    app = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/SOrdersApp.kt")
    c.present("根节点铺主题背景（否则没画底的页面露出窗口白）",
              main_act, r"color = MaterialTheme\.colorScheme\.background")
    c.present("外观模式有落盘入口", theme, r"fun set\(context: android\.content\.Context, dark: Boolean\)")
    c.present("启动时把外观读回来（否则首帧闪一下白天）", app, r"ThemeMode\.load\(this\)")
    c.present("设置页走落盘入口", profile, r"ThemeMode\.set\(context, it\)")
    c.absent("设置页不许直接写内存里的开关（那样杀 App 就丢）",
             profile, r"onCheckedChange = \{ ThemeMode\.isDark = ")
    disp_block = block_between(modules, "val dispatcherEntries", "val shipperEntries")
    ship_block = block_between(modules, "val shipperEntries", "val driverEntries")
    drv_block = block_between(modules, "val driverEntries", "fun entriesFor(")
    c.present(
        "派单端圆钮只给派单员（3 Tab 的角色给了会落在 1/4 处）",
        home,
        r"val showAiButton = role == Role\.DISPATCHER",
    )
    c.present(
        "货主端 AI 入口 = 工作台网格里的图标",
        ship_block,
        r'label = "AI 助手",\s*route = Routes\.AI_CHAT',
    )
    c.ok(
        "货主工作台里 AI **恰好一个**入口（两个入口=用户以为是两个功能）",
        ship_block.count("Routes.AI_CHAT") == 1,
        f"命中 {ship_block.count('Routes.AI_CHAT')} 次",
    )
    c.absent("派单端网格里不重复放 AI（圆钮已经是入口）", disp_block, r"Routes\.AI_CHAT")
    c.absent("司机端工作台没有 AI 入口", drv_block, r"Routes\.AI_CHAT")

    # ---- 8b AI 的外观 = Google AI 智能体那套（用户 2026-09-15 定的）----
    # 用户原话："颜色改成谷歌的 AI 智能体的配色方法，它里面的颜色也要按这个方法进行配色"。
    # Google 的做法是三件套：三段品牌渐变（蓝#4285F4→紫#9B72CB→粉#D96570）、
    # 渐变圆角块 + 白色四角星的图标形态、单色强调取渐变起点那个蓝。
    # 为什么要断言：渐变只要有一处颜色顺序写反或退化成单色，**没有任何功能测试会报错**，
    # 只会"看起来不像 AI 了"——这种偏差只能靠断言 + 只有一处定义来守。
    c.present("品牌三色：Google 蓝 #4285F4", color, r"val AiBlue = 0xFF4285F4L")
    c.present("品牌三色：Google 紫 #9B72CB", color, r"val AiPurple = 0xFF9B72CBL")
    c.present("品牌三色：Google 粉 #D96570", color, r"val AiPink = 0xFFD96570L")
    c.absent("品红已退役（AI 不再有第二个颜色）", color, r"AiMagenta")
    c.present(
        "渐变只有一处定义，顺序写死（各处自己写 Brush 迟早会写反）",
        brand,
        r"val AiBrandColors: List<Color> = listOf\(Color\(AiBlue\), Color\(AiPurple\), Color\(AiPink\)\)",
    )
    c.present("渐变画刷从这一处出", brand, r"fun aiBrandBrush\(\): Brush = Brush\.linearGradient\(AiBrandColors\)")
    c.present(
        "货主工作台那块 AI 图标用渐变（不是单色方块）",
        ship_block,
        r"gradient = listOf\(AiBlue, AiPurple, AiPink\)",
    )
    c.present("工作台按渐变渲染（Surface 只吃单色，必须自己铺画刷）", workbench, r"Brush\.linearGradient\(entry\.gradient")
    c.present("聊天页空状态的星标用同一个渐变", screen, r"\.background\(aiBrandBrush\(\), RoundedCornerShape")
    # v3.32：发送键多了一档"没字没附件 → 灰"，所以判据不能再钉死 `error else 渐变` 那一种写法，
    # 拆成两条各自成立的断言：**渐变仍然是正常态的画刷**，且**停止态仍然是单色红**。
    #
    # ⚠️ v3.34f 改成钉用户真正在意的那件事。原判据是「正常态要用 aiBrandBrush()」，
    #    而 2026-09-18 用户明确要求发送键改成蓝色（「灰色的话不是很明显、很不容易看清」），
    #    于是把它换成钉**可见性**：两档都必须是品牌蓝家族，**任何一档都不许退回灰色**。
    #    钉"用了哪个画刷"会随设计调整反复红；钉"不许是灰的"才是这条红线真正守的东西。
    c.present("发送键有内容时是品牌蓝", screen, r"else -> SolidColor\(AiAccent\)")
    c.present("发送键空格子时是**淡蓝**而不是灰", screen, r"!canSend -> SolidColor\(AiAccent\.copy\(alpha = 0\.45f\)\)")
    c.absent(
        "发送键任何一档都不许用 surfaceVariant/outline 这类灰（用户报过「看不清」）",
        screen,
        r"!canSend -> [^\n]*colorScheme\.(surfaceVariant|outline)",
    )
    c.present("发送键停止态仍用单色红（不跟 AI 蓝混）", screen, r"SolidColor\(MaterialTheme\.colorScheme\.error\)")
    c.present("单色强调 = Google 蓝", screen, r"private val AiAccent = Color\(AiBlue\)")
    c.present("设置页强调色同源", settings, r"val accent = Color\(AiBlue\)")
    c.present("派单端圆钮也用同一个渐变（同一个 AI 不该有两种外观）", home, r"\.background\(aiBrandBrush\(\), CircleShape\)")
    # 输入框提示语：举一个用户自己做不到的例子，等于教错（他照着敲一句，得到的
    # 只会是"你没这个权限"，然后不会再敲第二句）。空状态与提示语都必须按角色给。
    c.present(
        "输入框提示语按角色给",
        screen,
        r"hint = if \(ai\.currentRole == AiRole\.SHIPPER\) HINT_SHIPPER else HINT_DISPATCHER",
    )
    # v3.32：读文件时提示语要让位给"正在读文件…"，所以判据放宽成"placeholder 里必须用到 hint"。
    c.present("输入框用的是传进来的提示语", screen, r"placeholder = \{ Text\((if \(attaching\).*?else )?hint")
    c.absent("输入框里不许再把派单员的例子写死", fn_body(screen, "private fun InputBar("), r"例如：")
    c.absent(
        "货主端的提示语不许举例货主没有的能力（库存/司机/导出）",
        block_between(screen, "private const val HINT_SHIPPER", "\n"),
        r"库存|司机|导出",
    )
    c.present("导航栏有凸起圆钮（派单端）", home, r"AiNavButton\.Protrude")
    c.present("圆钮点进 AI 聊天页", home, r"onNavigate\(Routes\.AI_CHAT\)")
    c.present("圆钮有内容描述（无障碍 + 自动化找得到）", home, r'contentDescription = "AI 助手"')

    print("\n== 9. 支持第三方厂商（豆包/千问）==")
    providers = read(AI / "AiProviders.kt")
    c.present("有豆包预设地址", providers, r"ark\.cn-beijing\.volces\.com/api/v3")
    c.present("有千问预设地址", providers, r"dashscope\.aliyuncs\.com/compatible-mode/v1")
    c.present("提示了「必须支持工具调用」这个前提", providers, r"TOOL_CALLING_REQUIREMENT")
    c.present("thinking 参数可整体不发（端点不认时）", client, r"thinking = if \(includeThinking\)")
    c.present("遇到不认 thinking 的端点会自动降级重试", client, r"first\.thinkingRejected && !knownUnsupported")
    c.present("降级结果会被记住", keystore, r"fun markThinkingUnsupported\(")

    print("\n== 10. 思考强度（不是开关，是分档）==")
    level = read(AI / "ThinkingLevel.kt")
    c.present("有四档（关/低/中/高）", level, r'OFF\("off"')
    c.present("关的时候不发 effort", level, r'OFF\("off", "关", "[^"]*", null\)')
    c.present("强度映射到 reasoning_effort", client, r'reasoningEffort = if \(includeThinking\)')
    c.present("老版本布尔开关有迁移（不能悄悄把花费翻倍）", level, r"fun migrate\(legacyThinking")
    c.present("如实标注「分级可能被静默忽略」", screen, r"会把强度当没看见")

    print("\n== 11. 上下文：自动用满窗口 + 到 40% 自动压缩 ==")
    ctx = read(AI / "AiContext.kt")
    c.present("压缩阈值 40%（v3.4 用户口径）", ctx, r"const val COMPACT_AT = 0\.40")
    c.present("有硬兜底比例（压缩失败也不能超窗口）", ctx, r"const val HARD_LIMIT")
    c.present("硬裁从最早的丢、至少留几条", ctx, r"fun trimToFit\(")
    c.present("窗口按模型名自动推断（不给用户选）", ctx, r"fun inferWindow\(model: String\)")
    c.present("推断只认名字里写明的/公认的，其余保守兜底", ctx, r"const val FALLBACK_WINDOW")
    c.present("撞上限后按端点声明的上限/实证值自动改窗口", ctx, r"fun shrinkOnOverflow\(window: Int, lastGoodTokens: Int")
    c.present("端点报的上限要能直接读出来（唯一不用猜的数）", ctx, r"fun parseStatedLimit\(body: String\?\)")
    c.present("猜小了也要能长大（否则认不出的模型永远停在保守值）", ctx, r"fun growOnEvidence\(window: Int, lastGoodTokens: Int\)")
    c.present("deepseek 家族窗口用的是实测值 1048576（不是印象里的 128k）", ctx, r'"deepseek" to 1_048_576')
    c.absent("不再有「用户自选窗口档位」这种东西", ctx, r"WINDOW_CHOICES")
    c.absent("删掉用量读数（用户明确不要看）", ctx, r"fun usageLabel")
    c.present("压缩器独立成类（可用假传输层单测）", AI_join("AiCompactor.kt"), r"class AiCompactor")
    c.present("摘要失败要如实降级，不能假装压过", AI_join("AiCompactor.kt"), r"degraded = true")
    c.present("摘要请求关掉思考（省 token 是初衷）", AI_join("AiCompactor.kt"), r"thinkingLevel = ThinkingLevel\.OFF")
    c.present("上下文用量取本轮最大 prompt_tokens", vm, r"if \(ev\.promptTokens > runContextTokens\)")
    c.absent("不再固定只带最近 10 条历史（边界改由预算管，见 11c）", vm, r"const val HISTORY_LIMIT")

    print("\n== 11c. 上下文预算：触发点必须是「固定预算」而不是「窗口百分比」（v3.34）==")
    # ⚠️ 这一节守的是**一个已经发生过的设计错误**：
    # 旧口径「窗口 × 40% 才压缩」在 deepseek-flash（1M）上等于 419,430 token——
    # 折合四百多轮问答，实际永不触发，于是"整段对话原样发出去"成了唯一会执行的路径。
    # 谁要把触发点改回窗口百分比，这一节必须红。
    c.present("预算是常量字面量（**不许由窗口换算**）", ctx, r"const val HISTORY_BUDGET_TOKENS = [\d_]+")
    c.present("预算判据独立成函数（可单测）", ctx, r"fun overBudget\(")
    c.present("历史用量单独计量（不能把系统提示词算进预算）", ctx, r"fun estimateHistoryTokens\(")
    c.present("分级保真：先降级、再丢弃", ctx, r"fun fitToBudget\(")
    c.present("降级必须留痕（否则模型把半截当全部）", ctx, r"const val ELIDED_TAIL")
    # ⚠️ 只断言"常量存在"是不够的：定义了不用它，检查照样绿（反向验证抓到过一次）。
    #    所以这里钉**使用点**——降级处必须真的把这个后缀贴上。
    c.present("留痕要真的贴上，不是定义了不用", ctx, r"clip\(head, DEGRADED_ANSWER_CHARS\) \+ ELIDED_TAIL")
    # 「最近 N 条不许动」要钉两个点：原样拼回去 + 没被降级。
    # 只写 `val recent = history.takeLast(...)` 是**恒真的**——反向验证证明过：
    # 注入 `.map { degrade(it) }` 之后那行仍以原样开头，正则照样命中，检查空转。
    c.present("最近 N 条原样拼回去（不许被降级）", ctx, r"return kept \+ recent")
    c.absent("最近 N 条不许被降级（只降 older）", ctx, r"takeLast\(keepRecent\)[^\n]*degrade")
    # 顺序 + 唯一入口：发送路径必须"先预算、后窗口硬裁"，且两条发送路径都走同一个函数
    c.present(
        "发送前先按预算收口、再按窗口硬裁（顺序不能反）",
        vm,
        r"AiContext\.trimToFit\(\"\", AiContext\.fitToBudget\(historyForModel\(\)\), window\)",
    )
    c.present("收口只有一个入口（改名时这条要跟着改）", vm, r"private fun shrunkHistory\(window: Int\)")
    n_shrink = len(re.findall(r"shrunkHistory\(", vm))
    c.ok("所有发送路径都走同一个收口入口（≥2 处调用）", n_shrink >= 2, f"只找到 {n_shrink} 处")
    c.absent("发送路径不许绕过预算直接硬裁整段历史", vm, r"trimToFit\(\"\", historyForModel\(\)")
    c.present("压缩改到回答落地后后台跑（不再挡用户这一轮）", vm, r"private fun scheduleCompaction\(")
    c.present("后台压缩前比对代号（防止摘要落进别的对话）", vm, r"if \(generation != myGen\) return@launch")
    c.present("发送状态优先于整理状态（否则查询中会显示成在整理）", vm, r"sending -> \"查询中…\"[\s\S]{0,80}compacting ->")

    print("\n== 11d. 名单要拉得全（用户 2026-09-17：「他很多名单没有拉全没拉够」）==")
    # ⚠️ 这一节守的是一个**真 bug**：`MAX_ROWS` 原来是 50，而库里实测有 97 个货主 / 62 个司机 /
    #    161 个账号——"列出全部名单"在物理上做不到；更糟的是**后端已经把全量返回了，
    #    我们在 App 侧 `rows.take(limit)` 把它丢掉**，还告诉模型"被截断了"。
    #    于是模型只能答「只看了前 20 个，剩下的跟我说一声」——而用户没有"继续"这个按钮。
    readsvc = read(AI / "AiReadService.kt")
    m = re.search(r"const val MAX_ROWS = (\d+)", tools)
    c.ok("MAX_ROWS 要装得下真实名单（实测最大 161 行 → 至少 200）",
         bool(m) and int(m.group(1)) >= 200, f"现在是 {m.group(1) if m else '找不到'}")
    m2 = re.search(r"const val DEFAULT_ROWS = (\d+)", tools)
    c.ok("DEFAULT_ROWS 仍要小（默认查询别一上来就拖几百行）",
         bool(m2) and int(m2.group(1)) <= 50, f"现在是 {m2.group(1) if m2 else '找不到'}")
    c.present("limit 必须传给后端（不传的话后端按自己的默认截，永远拿不到 100 以上）",
              readsvc, r"if \(declared\.containsKey\(A_LIMIT\)\) query\[A_LIMIT\] = \(limit \+ 1\)\.toString\(\)")
    # 多要一行是"后面还有没有"的唯一探针：传原值 → 后端先截到 limit 且返回裸数组（无 total）
    # → `rows.size > capped.size` 永远为假 → 模型把 limit 条当全量（本机真量 790 却答"共 200 单"）。
    c.present("向后端多要一行，否则截断检测永久失灵（模型会把 limit 当全量）",
              readsvc, r"query\[A_LIMIT\] = \(limit \+ 1\)\.toString\(\)")
    c.present("截断要带一句给模型的实话（别当全部、别让用户说继续）",
              readsvc, r'"truncated_note"')
    c.present("提示词要求「要全部就一次取够」", loop, r"用户要「全部/所有/名单」时，一次就取够")
    c.present("提示词禁止把「继续看」推给用户", loop, r"不要只给前几条然后让他「跟我说一声再看」")
    # ⛔ 用户 2026-09-17：「不要为了省 token 核心数据就直接省掉了…本来要操作 60 个却只拿到 20 个的名单，
    #    那剩下 40 个他就没办法操作了，这是会影响核心功能的，绝对不可以。」
    c.present("批量操作前必须当场重查名单（不许凭历史里的名单去操作）",
              loop, r"要做批量操作（改价/派单/建商品/记账…）时，名单必须当场重新查一次")
    c.present("条数对不上要停下来问（少做一半比做错更糟）",
              loop, r"对不上就停下来问用户")
    c.absent("旧文案要删掉（它只教说实话、没教去取全）",
             loop, r"工具返回的行可能被截断（`truncated`），那就说明「只看")
    # 「不啰嗦」不许被过度执行——用户明确补过这条边界
    style = read(AI / "AiAnswerStyle.kt")
    c.present("提示词写明「不啰嗦≠什么都不说」", style, r"「不啰嗦」不等于「什么都不说」")
    c.present("判断标准是「会不会改变用户下一步」（可执行、不含糊）",
              style, r"这句话会不会改变用户下一步怎么做？会，就必须说")
    c.present("明确「被省掉的只有过程话」", style, r"被省掉的\*\*只有过程话\*\*")

    print("\n== 11b. 猜大了能自己修（「不给用户选择」能成立的前提）==")
    c.present("超长错误被单独识别", client, r"fun mentionsContextOverflow\(body: String\?\)")
    c.absent('不许把裸 "exceed" 当超长信号（限流/欠费里也有它）', client, r'"exceed",')
    c.absent('不许把 "token limit" 当超长信号（限流是按 token/分钟算的）', client, r'"token limit",')
    c.present("失败结果带 contextOverflow 标记", client, r"val contextOverflow: Boolean = false")
    c.present("端点声明的上限也带上去", client, r"val contextLimit: Int\? = null")
    c.present("循环把标记透传给上层", read(AI / "AiAgentLoop.kt"), r"contextLimit = result\.contextLimit")
    c.present("上层据此自动改窗口重试", vm, r"result\.contextOverflow && shrinks < MAX_OVERFLOW_SHRINKS")
    c.present("实测结论按模型记下来（换模型不串味）", keystore, r"fun rememberWindow\(model: String, window: Int\)")
    c.present("成功发过大用量后按证据放大窗口", vm, r"AiContext\.growOnEvidence\(contextWindow, runContextTokens\)")
    c.present("换模型时重算窗口", vm, r"val w = ai\.keyStore\.windowFor\(m\)")
    c.present("设置页能看到「这个数是猜的还是实测的」", settings_vm, r"fun relearnWindow\(\)")
    c.present(
        "实测脚本在仓库里（改窗口表之前先跑它）",
        read(Path(__file__).resolve().parent / "_probe_context_overflow.py"),
        r"maximum context",
    )

    print("\n== 12. 使用习惯：本机学习，且不许越权 ==")
    habit = read(AI / "AiHabit.kt")
    c.present("样本不够就不注入（拿偶发当习惯更糟）", habit, r"MIN_SAMPLES")
    c.present("注入时必须写明「只在用户没说清时当默认」", habit, r"没说清楚")
    c.present("注入时必须要求模型说明用了什么范围", habit, r"写明你按什么范围")
    c.present("默认开、可关", AI_join("AiHabitStore.kt"), r'getBoolean\(KEY_ENABLED, true\)')
    c.present("设置页要把「学到了什么」摊开给用户看", settings, r"habitSummary")
    c.present("用户可清除习惯记录", settings, r"清除习惯记录")

    print("\n== 13. 模型栏（只有模型 + 思考强度，点开就能换）==")
    model_bar = fn_body(screen, "private fun ModelChip(")
    c.present("模型栏在标题行上（跟标题同一行、垂直居中）", screen, r"subtitleTrailing = \{")
    c.absent("顶栏不再有「问数据」这类标语副标题（用户要求去掉）", screen, r'"问数据"')
    c.present("忙碌状态由芯片文案承担（不再另占一行）", vm, r'compacting -> "整理上下文…"')
    c.present("顶栏支持「无副标题时单行居中」的形态", read(UI / "common" / "Components.kt"), r"if \(subtitle\.isNullOrBlank\(\)\)")
    c.present("模型栏显示 模型·强度", model_bar, r"vm\.modelChipLabel|label")
    c.absent("模型栏不许显示上下文用量", model_bar, r"usageLabel")
    c.absent("模型栏不许有底色（用户：太难看了太突出了）", model_bar, r"\.copy\(alpha = 0\.12f\)")
    c.present("模型栏字号比次要信息还小（不占位子）", screen, r"private val ModelBarTextSize = 12\.sp")
    c.present("点开是切换面板", screen, r"private fun ModelSwitchSheet")
    c.present("面板里能换思考强度", screen, r"vm\.switchThinkingLevel")
    c.absent("面板里不再有窗口选项（用户：不要让用户选那么多）", screen, r"switchContextWindow")
    c.present("换模型立刻落盘（不用再点保存）", vm, r"saveConfig\(ai\.currentConfig\(\)\.copy\(model = m, contextWindow = w\)\)")
    c.present("拉到的模型候选会存起来给顶栏用", settings_vm, r"saveModelCandidates")
    c.present("分段选择器是全 App 共用组件", read(UI / "common" / "Components.kt"), r"fun SegmentedPicker\(")
    # ⚠️ 2026-09-21 修的真实缺陷，这一节原来**没有任何判据盯着它**：
    #    设置页的「换地址后重新检测」原来只清了「不支持思考开关」那条记忆，而
    #    `AiKeyStore.clearStreamOptionsUnsupported` 声明了却**从没人调**（它的 KDoc 还写着
    #    "与 clearThinkingUnsupported 一起用于设置页的重新检测"）。后果是用户换到一个
    #    **支持** `stream_options` 的地址、点了这个按钮，App 仍然永远跳过该参数 ——
    #    拿不到服务端的 token 用量（上下文压缩只能改用本机估算），而界面上没有一个字解释。
    c.present("「换地址后重新检测」把**两种**能力记忆一起清（thinking + stream_options）",
              settings_vm,
              r"clearThinkingUnsupported\(baseUrl\)\s*\n\s*ai\.keyStore\.clearStreamOptionsUnsupported\(baseUrl\)")
    c.present("被清的那个方法真的存在（判据锚的符号不是凭空写的）",
              read(AI / "AiKeyStore.kt"), r"fun clearStreamOptionsUnsupported\(")

    print("\n== 14. 写能力覆盖率：剩下的端点必须每一条都说得出「为什么不做」==")
    # 为什么要有这一节：覆盖率脚本自己是会跑的，但**没人会记得跑它**。
    # 「还剩 14 个写端点」这句话会随着时间变成"待办清单"，
    # 而其中一半是**决定不做**的（上传类模型给不出文件、司机端不开放、客户合并不做）。
    # 所以把它的结论钉进红线：有真缺口、或者理由表成了化石/空转，这里就红。
    coverage = Path(__file__).resolve().parent / "_write_coverage.py"
    cover_src = read(coverage)
    c.present("覆盖率脚本在仓库里（红线会调它）", cover_src, r"EXCLUDED")
    c.present("每一条「不做」的理由都写在表里（不是散在注释里）", cover_src, r"EXCLUDED: dict\[tuple\[str, str\], str\]")
    r = subprocess.run(
        [sys.executable, str(coverage), "--check"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    c.ok(
        "未覆盖的写端点 100% 有「不做」的理由（没有真缺口）",
        r.returncode == 0 and "0 条是真缺口" in out,
        out.strip().splitlines()[0] if out.strip() else "（没有输出）",
    )
    # 反向验证脚本本身必须在仓库里，否则上面这条"真的会红"没有任何证据。
    c.present(
        "这条判据有反向验证（注入 bug 会红）",
        read(Path(__file__).resolve().parent / "_reverse_verify_coverage.py"),
        r"mutation_all_covered",
    )

    print("\n== 15. 文档自检必须真的在跑（它曾经红了 12 轮没人管）==")
    # 为什么把"另一个脚本的结果"钉进红线：`_ai_doc_check.py` 因为把红线小节号
    # （`§2e` / `§2f-2b`）当成文档小节号去查，**一直报错、一直退出码 1**，
    # 而每轮的收尾清单里没有它——一条永远红的检查等于没有检查（没人会去看总是红的输出）。
    # 修好之后把它的结论收进红线，从此它不可能再"默默地红着"。
    doc_check = Path(__file__).resolve().parent / "_ai_doc_check.py"
    c.present("文档自检脚本在仓库里、且会把引用分类核对", read(doc_check), r"红线子条目")
    r2 = subprocess.run(
        [sys.executable, str(doc_check)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    doc_out = (r2.stdout or "") + (r2.stderr or "")
    c.ok(
        "文档里的 § 引用全部能对上（v2 + v3 两份都查）",
        r2.returncode == 0 and doc_out.count("✅ 所有 § 引用") == 2,
        "；".join(ln.strip() for ln in doc_out.splitlines() if "❌" in ln) or "（没有输出）",
    )
    c.present(
        "这条判据有反向验证（注入假引用 / 改红线编号会红）",
        read(Path(__file__).resolve().parent / "_reverse_verify_doc_refs.py"),
        r"99z",
    )

    print("\n== 16. 按表格调价（目标①的第四种用法）+ 调价必须留痕 ==")
    # 这一节守两件事，两件都属于"看起来做完了、其实没有"：
    # ① 表格是**逐行**发请求的，所以一定会出现"部分成功"——汇报里少了逐行结果，
    #    用户就会以为整张表都写进去了（而失败的那几行就这么被"已完成"盖住）；
    # ② 用户明确要求"每条改动在操作日志里可回查"，而 `price_rules.py` 在 v3.21 之前
    #    **一条日志都不写**（枚举里有 PRICE_RULE_UPSERT，但从来没人用过）——
    #    价改了，谁改的、改前改后全查不到。
    price_table = read(AI / "AiPriceTable.kt")
    pricing = read(AI / "AiWritePricing.kt")
    price_api = read(ROOT / "backend/app/api/v1/price_rules.py")
    c.present("表格解析器是**纯函数**（不碰网络、不 suspend，所以能单测）", price_table, r"internal object AiPriceTable")
    c.absent("解析器里没有数据源依赖（有了就没法脱网单测）", price_table, r"AiWriteDataSource|suspend fun")
    c.present("表头与内容两种认列方式都在", price_table, r"detectHeader")
    c.present("读不出来的行必须报**第几行**（否则模型只能干瞪眼）", price_table, r"表格第 \$\{?r\.lineNo")
    c.present("行数有上限（一张表不能无限长）", price_table, r"const val MAX_ROWS = \d+")
    c.present("表格动作逐行调后端（一行一个请求）", pricing, r"rows\.forEachIndexed")
    # ⚠️ 必须钉在 catch 里：只查 "failed += " 会被别处的同类语句救活
    #    （反向验证抓到的：把 catch 里那行注释掉，检查竟然还是绿的）。
    c.present(
        "逐行失败被收集起来（不许静默跳过）",
        pricing,
        r"catch \(e: Exception\) \{\s*\n\s*failed \+= ",
    )
    c.present("执行结果如实汇报（commitNote）", pricing, r"override fun commitNote\(\): String\? = pendingNote")
    c.present("服务层把逐行结果拼进最终答复", wsvc, r"handler\.commitNote\(\)")
    c.present("commitNote 有默认实现（否则 50 多个处理器都要跟着改）", wr, r"fun commitNote\(\): String\? = null")

    # ---- 「一次确认 → 多个请求」的动作**全都**要逐条汇报（2026-09-19 审计，清单机器算）----
    #
    # 为什么机器算：上面那两条只钉住了**调价**那一个处理器，而"哪些动作算多请求"这份清单
    # 是**手写**的 —— 这个仓库已经因为手写清单栽过 6 次（卡片 Markdown、prepare 只读、
    # 写方法名单……）。实测抓到的漏网之鱼：「标记消息已读」的 commit 就是
    # `ids.forEach { ds.markNotificationRead(it) }`，中途一条失败会把"已标 N-1 条"
    # 整体报成失败（与"已完成盖住失败行"是同一个病的两面）。
    #
    # 判据（**形状**，且必须精确到位）：`commit` 体里某个 **forEach/for 的循环体内部**
    # 出现了 `ds.xxx(` → 那就是"一次确认发多个请求" → 必须有 `commitNote()`。
    #   ⚠️ 第一版写成"commit 里有循环、又有 ds. 调用"，当场把 `UpdateOrderHandler` 报成缺陷——
    #   它的 `forEach` 只是**拼 payload**（循环里没有请求），全函数只有一个 `ds.updateOrder`。
    #   判据松一格就会制造假缺陷，而假缺陷会让人开始无视红线。
    def _ds_calls_inside_loops(commit_src: str) -> int:
        """数一数"**在迭代里**发出去的请求"有几个。

        ⚠️ 迭代形式要写全（2026-09-19 踩到）：第一版只认 `forEach {`，而"
        标记消息已读"用的是 `forEachIndexed { i, id -> … }` —— 扫出 0 个动作、
        判据直接空转（幸好我给它配了"扫到 0 个就报错"的锚点，否则这条检查会**看起来是绿的**）。
        """
        total = 0
        for m in re.finditer(r"\b\w*[Ff]orEach\w*\s*\{|\bfor\s*\([^)]*\)\s*\{|\b(?:map|mapNotNull|flatMap|onEach|repeat)\s*\{", commit_src):
            brace = m.end() - 1
            if commit_src[brace] != "{":
                continue
            inner = balanced_inside(commit_src, brace)
            total += len(re.findall(r"\bds\.\w+\(", inner))
        return total

    multi_req_classes: list[str] = []
    missing_note: list[str] = []
    for f in sorted(AI.glob("AiWrite*.kt")):
        src = strip_comments(f.read_text(encoding="utf-8"))
        for m in re.finditer(r"override suspend fun commit\(", src):
            brace = src.find("{", m.end())
            if brace < 0:
                continue
            body = balanced_inside(src, brace)
            if _ds_calls_inside_loops(body) < 1:
                continue
            head = src[: m.start()]
            cls = None
            for cm in re.finditer(r"\nclass (\w+)", head):
                cls = cm.group(1)
            cls = cls or f.name
            # 这个类里有没有实现 commitNote（在它之后、下一个 class 之前）
            tail = src[m.start():]
            nxt = re.search(r"\nclass \w+", tail)
            scope = tail if nxt is None else tail[: nxt.start()]
            # 往前也要看：commitNote 常写在 commit 之前
            prev = head[head.rfind("\nclass "):] if "\nclass " in head else head
            multi_req_classes.append(cls)
            if "override fun commitNote(" not in scope and "override fun commitNote(" not in prev:
                missing_note.append(cls)
    c.ok(
        "「一次确认发多个请求」的动作都实现了 commitNote（逐条如实汇报）",
        not missing_note,
        "这些处理器的循环体里直接发了 `ds.*` 请求（= 一次确认发多个请求），却没有 commitNote："
        f"{missing_note}。要么逐条 try/catch 后如实汇报，要么在检查里写明为什么不需要。"
        f"（本次扫描到 {len(multi_req_classes)} 个多请求动作：{multi_req_classes}）",
    )
    c.ok(
        "扫描到的多请求动作数不为 0（否则上面那条判据在空转）",
        len(multi_req_classes) > 0,
        f"扫到 {len(multi_req_classes)} 个 —— 判据形状可能过期了（class/commit 的写法变了？）",
    )
    c.ok(
        "调价类动作都不在货主白名单里（调价是派单员的权限）",
        "PRICE_RULES" not in wr.split("val SHIPPER_ACTIONS")[1].split(")")[0],
        "货主白名单里出现了 PRICE_RULES 开头的动作",
    )
    # ---- 后端：调价必须写操作日志 ----
    c.present("批量调价写审计日志", price_api, r"write_log\(")
    c.present("用的是 PRICE_RULE_UPSERT 这个动作码", price_api, r"OperationAction\.PRICE_RULE_UPSERT")
    c.present("逐条改动都记（不是只记一条汇总）", price_api, r"for c in changes\[:MAX_LOGGED_CHANGES\]")
    # ⚠️ 用 "\n    " 前缀把**函数定义**排除掉：只查 `_log_price_changes(` 的话，
    #    把调用点删掉、只留定义，检查照样是绿的（反向验证抓到的）。
    c.present(
        "日志与写价在同一个事务里（不然会出现改了价却查不到）",
        price_api,
        r"\n    _log_price_changes\(",
    )
    c.ok(
        "单条改价 / 重新设价（复活）/ 删专属价也留痕（都是一次价格变动）",
        price_api.count("OperationAction.PRICE_RULE_UPSERT") >= 6,
        f"实际出现 {price_api.count('OperationAction.PRICE_RULE_UPSERT')} 次"
        "（批量逐条 + 批量汇总 + 新建 + 复活重新设价 + 改 + 删 应为 6）",
    )
    # ⚠️ 2026-09-23 复核抓到：`create_price_rule` 的**复活分支**（给一个软删过的货主重新设价）
    #    原来改完价直接 `db.commit()` 就 return 了 —— 一条日志都没有，而它同时做了
    #    "把那一行从回收站复活" 和 "改价" 两件事。上面那条计数判据当时写的是"应为 5"，
    #    也就是说**判据自己也不知道还有第 6 条路**。改成 6 之外，再钉一条只看代码的断言：
    c.present("复活分支把旧价取出来当 before（不然日志里看不出改前是多少）",
              price_api, r"before = exists\.special_unit_price")
    c.present("批量调价的范围排除回收站里的商品（否则写出来的价对谁都不生效）",
              price_api, r"select\(Product\)\.where\(Product\.is_deleted\.is_\(False\)\)")

    print("\n== 17. 声明式字段的 key 覆盖：commit 不许按「参数名」去 payload 里取 ==")
    # ⚠️ 这一条来自真机实测抓到的**静默丢数据** bug：
    #   `users.create` 的字段规格写的是 `textField("name", …).copy(key = "full_name")`，
    #   也就是 payload 里存的是 `full_name`；而 commit lambda 读的是 `p.str("name")` ——
    #   **永远是空的**。表现：卡片写着「姓名：AI测试账号」、执行完还回
    #   「已完成：新建货主账号：AI测试账号」，而库里那条账号的 full_name 是空的
    #   （用户只会在名册里看到一个「未命名」）。
    #   这一整类的判据很简单：**字段声明了 key 覆盖（key != 参数名）时，
    #   commit 里按参数名去 payload 取值一定是错的。**
    #   （同类错误以前被单测抓到过一次——`users.update_profile` 的 name vs full_name——
    #    所以这里把它变成静态检查，覆盖全部声明式动作。）
    key_checked = 0
    for rel in ("AiWriteMasterData.kt", "AiWriteBasicData.kt"):
        src = strip_comments(read(AI / rel))
        blocks = re.split(r"\n        crud\(", src)[1:]   # 每个动作 = 一个 crud( 块
        for blk in blocks:
            action_id = re.search(r"id = AiWrites\.(\w+)", blk)
            name = action_id.group(1) if action_id else "(未知动作)"
            # 字段的参数名 = 字段构造函数的**第一个**字符串参数（比"最近的一对引号"可靠得多：
            # 后者会把 `aliases = mapOf("工资" to "salary", "固定工资" to "salary")` 里的
            # `"salary", "固定工资"` 误当成一对「参数名, 中文名」——反向验证前先踩过这个假阳性）。
            ctors = [
                (m.end(), m.group(1))
                for m in re.finditer(
                    r'(?:textField|moneyField|enumField|boolField|AiFieldSpec)\(\s*"(\w+)"', blk
                )
            ]
            for m in re.finditer(r'key = "(\w+)"', blk):
                prev = [c for c in ctors if c[0] < m.start()]
                if not prev:
                    continue
                param = prev[-1][1]
                if param == m.group(1):
                    continue
                key_checked += 1
                bad = re.search(rf'p\.\w+\("{re.escape(param)}"\)', blk)
                c.ok(
                    f"{name}: 字段 {param}→{m.group(1)} 的 commit 不许按参数名取",
                    bad is None,
                    f'块里出现了 p.*("{param}")，而 payload 里存的是 "{m.group(1)}"',
                )
    c.ok("真的扫到了带 key 覆盖的字段（否则这一条是空转）", key_checked >= 6, f"实际扫到 {key_checked} 个")

    print("\n== 18. 地址类动作必须把地址换成坐标（否则司机导航没有目的地） ==")
    # ⚠️ 这一节的来源是真机实测（v3.24）：AI 建的地址 `address_lat/address_lng` 全是 NULL，
    #   而 App 自己建的每一条都有值。原因不是 bug，是**设计缝隙**：
    #   App 的页面里坐标是用户在地图上点出来的（AmapPicker），AI 没有人点地图，只有一句话。
    #   后果不是"少存一个字段"，是**司机端「高德导航」直接失灵**——
    #   `openAmapNavigation` 拿到空坐标会退化成"打开高德首页"，目的地没了，司机得自己再搜一遍。
    #
    # 这一节守四件事，每一件都能单独坏掉：
    #   ① 地址/地点/订单这三个域**真的**接了地理编码（按动作数钉死，防"改了一个忘了另一个"）；
    #   ② 坐标必须进 `pick` 白名单——不进的话 payload 里查得到、递给数据源时被**悄悄丢掉**，
    #      症状与"压根没查"一模一样且不报错（单测抓到过一次）；
    #   ③ "改了地址却没定位到"必须**拒绝**：后端 PATCH 是 `if address_lat is not None` 语义，
    #      传 null 清不掉旧坐标 → 库里留着**上一条地址的坐标**，司机被导航到旧地址且无任何提示；
    #   ④ 新建类动作定位失败时后果要**写在卡上**（不写在卡上的后果＝用户不知道的后果）。
    geo = read(AI / "AiGeocode.kt")
    basic = read(AI / "AiWriteBasicData.kt")
    crud_h = read(AI / "AiWriteCrudHandlers.kt")
    c.present("地理编码封装存在且是只读的（不写后端）", geo, r"internal object AiGeocode")
    c.present("一定有超时（高德回调不保证回来，卡住＝用户以为 AI 死了）", geo, r"withTimeoutOrNull\(TIMEOUT_MS\)")
    c.present("串行 + 序号校验（否则并发时 A 的地址会拿到 B 的坐标）", geo, r"if \(seq != issued\) return")
    c.ok(
        "地址/地点两类四个动作都声明了 geocodeFrom",
        len(re.findall(r'geocodeFrom = "detail_address"', basic)) >= 4,
        f"实际 {len(re.findall(chr(34) + 'detail_address' + chr(34), basic))} 处",
    )
    c.ok(
        "改类动作同时是 geocodeRequired（定位不到就不改，绝不留下旧坐标）",
        len(re.findall(r"geocodeRequired = true", basic)) >= 2,
        f"实际 {len(re.findall('geocodeRequired = true', basic))} 处",
    )
    # ② 坐标必须能被 pick 递下去
    for keys in ("ADDRESS_KEYS", "LOCATION_KEYS"):
        m = re.search(rf"private val {keys} = setOf\(([^)]*)\)", basic, re.S)
        c.ok(
            f"{keys} 里包含坐标（不在里面会被 pick 悄悄丢掉）",
            m is not None and "GEO_LAT" in m.group(1) and "GEO_LNG" in m.group(1),
            f"{keys} = {m.group(1).strip() if m else '(没匹配到)'}",
        )
    # ③ 卡片摘要与 payload 同源：坐标要写进 values，才会同时出现在两边
    c.present("坐标写进 values（卡片与 payload 同源，不会分叉）", crud_h, r"values\[GEO_LAT\] = JsonPrimitive")
    c.present("定位不到时拒绝改类动作", crud_h, r"if \(spec\.geocodeRequired\) \{")
    c.present("拒绝的话必须说清会被带到上一版的位置去", crud_h, r"上一版")
    # ④ 新建类：定位失败写在卡上
    c.present("新建类定位失败时后果写在卡片上", crud_h, r"private fun geoNote\(")
    # ⚠️ 2026-09-21 **锚点搬到新位置**（原判据找的是 `ds.geocode(address)`）：
    #    订单的送货地址现在走 `resolveAddress` —— 它多认一个句柄「当前位置」（取手机定位，
    #    真实地址 + 精确坐标一起回来，见 `AiLocation`）。判据的**原意不变**（"订单的送货地址也换坐标"），
    #    只是换到了新的调用名上；⛔ 不是删掉它，删了这条就再没人守。
    c.present("订单的送货地址也换坐标", worder, r"val geo = if \(address\.isNotBlank\(\)\) ds\.resolveAddress\(address\)")
    c.present("订单卡片写明导航会落到高德首页", worder, r"高德首页")
    # 订单 create 的坐标必须进 payload（漏了就是"查了但没发出去"）
    # ⚠️ 同上：`it.first` → `it.lat`（解析结果从 `Pair` 换成了带地址的 `AiPlace`）。
    c.present("订单 create 把坐标放进 payload", worder, r"put\(GEO_LAT, it\.lat\.toString\(\)\)")
    # 新增（2026-09-21）：地址栏写的必须是**解析后**的文字 —— 句柄那四个字写进订单
    # 等于把收货地址废了（而且不报错：库里、单上、司机看到的都是「当前位置」）。
    c.present("订单 create 写的是解析后的地址（不是「当前位置」四个字）",
              worder, r'put\("address_detail", addressText\)')
    c.absent("订单 create 不许把模型给的原文直接写进地址栏", worder, r'put\("address_detail", address\)')
    # 反向验证：改红线编号会红
    c.present(
        "这一节有反向验证脚本",
        read(Path(__file__).resolve().parent / "_reverse_verify_geocode.py"),
        r"geocodeFrom",
    )

    print("\n== 19. 「确认卡已发」这句话必须由代码兜底，不能只靠提示词 ==")
    # ⚠️ 来源：真机实测**两次**同一种情况——用户说「新增挂账单位 X，再登记一辆车 Y」，
    #   模型只调了两次**只读**工具，然后回「两张确认卡发给你了……各点一下确认才生效」。
    #   屏幕上没有卡：用户会去找一张不存在的卡，然后卡死（不知道该说什么）。
    #   第一次之后加过提示词（「这句话只能在你真的调用过 preview_write 之后说」），**第二次照犯**。
    #   所以这里守的是"判据必须是事实、不是话术"：
    #     · 数卡只能数**工具返回里的结构化 status**，不许去匹配返回里的说明文字；
    #     · 那个 status 常量只允许有一份定义（两处字面量 = 改一处就静默失效）；
    #     · 说了卡却没有卡 → 不接受这句答复、当场重做，且重做次数有上限；
    #     · 重做前先把屏幕上流出去的谎话盖掉（不盖，用户还是先看到"卡已发"）。
    claim = read(AI / "AiCardClaim.kt")
    loop = read(AI / "AiAgentLoop.kt")
    tools = read(AI / "AiTools.kt")
    c.present("「说了卡却没有卡」有专门的判据对象", claim, r"internal object AiCardClaim")
    c.present("判据是「卡的字样 ＋ 已经发出去了的字样」两个信号", claim, r"CARD_WORD\.containsMatchIn\(line\) && CARD_SENT")
    c.present(
        "它挂了工具返回里的**结构化状态**，不是返回里的说明文字",
        loop,
        r'\(o\?\.get\("status"\) as\? JsonPrimitive\)\?\.contentOrNull == CARD_OFFERED_STATUS',
    )
    c.present(
        "数卡发生在工具执行之后（而不是在模型答复里找关键词）",
        loop,
        r"if \(fnName == AiTools\.PREVIEW_WRITE && isCardOffered\(output\)\) cardsOffered\+\+",
    )
    c.present(
        "说了卡却没有卡时**不接受**这句答复（把话记回去 + continue 重做）",
        loop,
        r"messages \+= ChatMessage\.user\(AiCardClaim\.NUDGE\)\s*\n\s*continue",
    )
    c.present("重做次数有上限（否则会一直烧 token）", loop, r"const val MAX_CARD_CLAIM_RETRIES = \d+")
    c.present("重做前把屏幕上流出去的谎话盖掉（replace）", loop, r"AiEvent\.TextDelta\(AiCardClaim\.CORRECTION, replace = true\)")
    c.present("次数用尽后换成如实说明 ＋ 下一步（而不是原样交付谎话）", loop, r"finalText = AiCardClaim\.EXHAUSTED")
    c.present("重做时喂回去的话摆出**事实**（你一次都没调用过）", claim, r"一次 preview_write 都没调用过")
    # 那个 status 常量只许有一份定义：两处字面量 = 改一处就静默失效
    bare = [
        (p.name, ln.strip())
        for p in sorted(AI.glob("Ai*.kt"))
        for ln in strip_comments(read(p)).splitlines()
        if '"awaiting_user_confirmation"' in ln and "const val CARD_OFFERED_STATUS" not in ln
    ]
    c.ok(
        "确认卡的 status 字面量只出现在常量定义那一行（改一处不会静默失效）",
        not bare,
        f"这些地方写了裸字面量：{bare[:3]}",
    )
    c.present(
        "常量由**产出方**定义（AiTools 造这个 JSON）",
        tools,
        r'const val CARD_OFFERED_STATUS = "awaiting_user_confirmation"',
    )
    c.present("消费方引用常量而不是抄一份", loop, r"const val CARD_OFFERED_STATUS = AiTools\.CARD_OFFERED_STATUS")
    c.ok(
        "工具痕迹也认这个常量（否则痕迹会说「完成」，用户以为已经写进去了）",
        tools.count("CARD_OFFERED_STATUS") >= 2,
        f"实际出现 {tools.count('CARD_OFFERED_STATUS')} 次（定义 1 + 使用应 ≥ 1）",
    )
    c.present(
        "这一节有反向验证脚本",
        read(Path(__file__).resolve().parent / "_reverse_verify_card_claim.py"),
        r"looksLikeClaim",
    )

    print("\n== 20. 撤回底线：确认之后发现做错了，要能退回去 ==")
    # ⚠️ 用户的原话：「不要删了就搞不回来了」「确认之后用户意识到操作错了，要有可以撤回的权限」。
    #    这一节守的不是"有没有做一个撤回按钮"，而是**这条路不能变成第二条写入口**：
    #    · 撤回也必须造卡、也要用户点确认（否则它绕过了角色门、风险档和一次性 token）；
    #    · 撤回快照必须在 commit **之前**抓（删掉之后就抓不到了）；
    #    · 每个动作都必须回答"误操作了怎么办"，而且那句话要印在**点确认之前**的卡上；
    #    · 后端要真的能恢复（软删 + restore），否则撤回按钮只是把用户骗一遍。
    undo = read(AI / "AiUndo.kt")
    revert = read(AI / "AiRevert.kt")
    resources = read(AI / "AiResources.kt")
    # ⚠️ 2026-09-22（预订单那一轮）：这两行原来是**写死的两个文件名**，于是新加的域文件
    #    （`AiWriteOrderTemplates.kt`）里的动作与 `restoreAction(...)` **一个都扫不到** ——
    #    表现是「资源挂了不存在的动作 / 恢复动作没注册」这类**假红**，
    #    而真正漏注册的那个动作会被它一起放过（这比红更糟）。
    #    本仓库栽过 6 次同类问题，规矩是：**"要检查哪些文件"的清单一律让脚本自己算**。
    #    所以这里改成 glob：所有声明过 `AiWriteAction(` 的 `AiWrite*.kt`。
    #    ⛔ 别再往这里手写文件名。
    _domain_files = sorted(p for p in AI.glob("AiWrite*.kt") if "AiWriteAction(" in read(p))
    basic20 = "\n".join(read(p) for p in _domain_files)
    master20 = ""
    c.present("撤回方案有专门的类型与暂存区", undo, r"data class AiUndoPlan")
    c.present(
        "撤回 token 一次性（取走即删）",
        undo,
        r"fun take\(token: String\): AiUndoPlan\? \{[\s\S]{0,200}items\.remove\(token\)",
    )
    c.present("撤回有过期时间（不是永远挂着一个按钮）", undo, r"DEFAULT_TTL_MS: Long = \d+ \* 60 \* 1000L")
    c.present("撤回有条数上限", undo, r"MAX_ENTRIES: Int = \d+")

    # ---- 唯一写入口：撤回也得造卡、也得用户点确认 ----
    i_offer = wsvc.find("suspend fun offerUndo(")
    c.ok("服务层有撤回入口 offerUndo", i_offer > 0, "没找到 offerUndo")
    if i_offer > 0:
        body = wsvc[i_offer : i_offer + 2500]
        c.ok(
            "撤回走的是**造卡**（store.card），不是直接 commit/execute",
            "store.card(" in body and "handler.commit(" not in body and ".execute(" not in body,
            "撤回入口里出现了直接写库的调用——那就成了第二条写入口",
        )
        c.present("撤回也过角色门", body, r"if \(!AiWrites\.allows\(actorProvider\(\), plan\.actionId\)\)")
        c.present(
            "撤回卡弹出之前**再读一次现状**（否则会把别人后来的改动一起盖掉而用户不知道）",
            body,
            r"plan\.probe\?\.invoke\(\)",
        )

    # ---- 快照必须在 commit 之前抓 ----
    i_exec = wsvc.find("suspend fun execute(token: String)")
    seg = wsvc[i_exec : i_exec + 3500]
    i_pre = seg.find("AiRevert.plan(")
    i_com = seg.find("handler.commit(")
    c.ok(
        "撤回快照在 commit **之前**抓（删掉之后就抓不到了）",
        0 < i_pre < i_com,
        f"AiRevert.plan@{i_pre} commit@{i_com}",
    )
    c.present("只有写成功了才挂撤回按钮", seg, r"undoToken = undo\?\.let \{ undos\.offer\(it\) \}")
    c.present(
        "卡片答应过撤回却没挂上时必须**如实说**（空承诺比没有撤回更糟）",
        seg,
        r"AiRevert\.canRevert\(p\.actionId\) && undo == null",
    )

    # ---- 撤回只有一个实现处（v3.27 的结构性底线） ----
    # 这一条是这次重构的全部意义：v3.26 的实现散在四处，用户的原话是
    # 「每次都一个一个改一个一个找，非常麻烦也非常耗时」。
    #
    # ⚠️ 下面凡是判"代码长什么样"的，一律先 `strip_comments`：这两个文件的文档注释里
    #    大量**引用**这些写法（解释为什么禁它、当初错在哪），不剥注释就会出现
    #    "检查被一句注释满足"——反向验证抓到的正是这个（往注释里改写一句，检查照样绿）。
    revert_code = strip_comments(revert)
    resources_code = strip_comments(resources)
    c.present("撤回的统一实现处存在（[AiRevert]）", revert_code, r"object AiRevert")
    c.present("资源表存在（声明一次、下面所有动作自动获得撤回）", resources_code, r"internal object AiResources")
    c.present("资源表有一份可枚举的总表（红线与单测按它逐个核对）", resources_code, r"val TABLE: List<AiResource> = listOf\(")
    n_res = len(re.findall(r"\n    private val \w+ = AiResource\(", resources_code))
    c.ok("资源不少于 12 个（太少说明有东西没接进来）", n_res >= 12, f"实际 {n_res} 个")
    c.present(
        "「改类」的撤回就是同一个动作写回旧值（不再需要按动作写代码）",
        revert,
        r"actionId = entry\.id,[\s\S]{0,400}?res\.cn\}改回原样",
    )
    c.present("撤回卡写的是「现在是 X → 撤回到 Y」，不是一句「改回原样」", revert_code, r"→ 撤回到 ")
    # 静默键（地址/订单的经纬度）**跟着写回，但不单独占一行**。真机上踩到过：
    # 卡片上出现 `address_lat: 39.983342 → 撤回到 40.0119719`——用户核对的是「终点地址」。
    # 声明了 `silent` 却没有一处读它，就是"声明了但没接线"，这条钉子钉住那个过滤。
    c.present(
        "静默键跟着写回、但不单独占卡片一行（真机踩到过裸键 address_lat）",
        revert_code,
        r"if \(k in res\.silent\) continue",
    )
    c.present(
        "读不到旧值的键**不许静默丢掉**，要写在卡上",
        # ⚠️ 必须读**剥过注释**的源码：这条串在 AiRevert 的注释里也被引用过（解释当初错在哪），
        #    读原文会让"把这行代码删掉"的注入照样绿——反向验证当场抓到过这一次。
        revert_code,
        r"这一项撤不回来——",
    )
    # 同上，但管的是"怎么说"：警告行里必须是中文名，不许把 payload 的裸键（address_lat）摆给用户。
    # 真机上出现过「这一项撤不回来——address_lat」，单测也钉了一条。
    c.present(
        "警告行里说人话（用中文名，不是 payload 裸键）",
        revert_code,
        r'stuck \+= "\$\{cnOf\(res, entry\.id, k\)\}：',
    )
    # 中文名必须有**第二处来源**（v3.45，真机 E2E 抓到的两行裸键）：
    # 资源表的 labels 被单测钉成 `readKeys`（那条是对的——它管的是"**读回来**的东西叫什么"），
    # 而 payload 里还有一批**读不回来的键**（库存调整的 change/note 从来不在商品快照里），
    # 于是它们查不到中文名，在 5554 真机上的撤回卡里长成了
    # 「· change：5 → 撤回到 -5」和「· 「note」不写回（…）」。
    c.present(
        "卡片上的字段中文名还有第二处来源：动作声明的字段/目标规格（payload 专用键才不会印裸键）",
        revert_code,
        r"fun cnOf\(res: AiResource, actionId: String, key: String\): String ="
        r"[\s\S]{0,200}?spec\.fields\.firstOrNull \{ it\.key == key \}\?\.cn",
    )
    c.absent(
        "卡片文案不许绕开解析器直接查资源表（漏一个键就是把裸英文键摆给用户）",
        revert_code,
        r"res\.labels\[(?:k|it)\] \?: (?:k|it)",
    )
    # 「不搬旧值」不等于「什么都不写」（v3.45，真机抓到的空原因流水）：
    # 库存撤回的反向流水 note 曾经是 `''`——"入库 +5（原因：真机校验B）"下面躺着一条"-5（原因：无）"。
    c.present(
        "撤回时「故意不写回旧值」的键可以声明补写一句（不然审计流水上会留一条没有原因的记录）",
        revert_code,
        r"entry\.dropWrite\[k\]\?\.let \{ put\(k, it\) \}",
    )
    c.present(
        "库存调整的撤回给反向那条流水补了原因（真机上它曾经是空的）",
        resources_code,
        r'dropWrite = mapOf\("note" to "撤回：',
    )
    c.present("每个动作都要回答「误操作了怎么办」", revert_code, r"fun cardLine\(actionId: String\)")
    c.present("撤不回来的理由逐条写清后果", revert_code, r"private fun buildUndoNone")
    c.absent(
        "处理器不再自己实现撤回（v3.26 那种「每个人各写一遍」已经删掉）",
        AI_join("AiWrite.kt") + AI_join("AiWriteCrudHandlers.kt") + worder + AI_join("AiWriteOrderLineHandlers.kt"),
        r"override suspend fun prepareUndo",
    )
    c.absent(
        "声明式规格里不再各自声明 undoAction（接线收敛到资源表）",
        basic20 + master20 + AI_join("AiWrite.kt"),
        r"undoAction = AiWrites\.",
    )
    c.present(
        "撤回方案里的每个方案都带「点撤回时再读一次」的探针字段",
        undo,
        r"val probe: \(suspend \(\) -> List<String>\)\? = null",
    )

    # ---- 每个动作都要回答"误操作了怎么办"，而且要在卡上 ----
    # ⚠️ v3.45：最后一行改成"按这张卡是不是撤回卡"二选一（真机上出现过**撤回卡**印着
    #    「这一步撤不回来」的自相矛盾）。判据跟着钉**两件事**：
    #    ① 这一行仍然由暂存区统一加（所有卡片的必经之路）；
    #    ② 撤回卡走的是 `undoCardLine`，不是被撤回那个动作的 `undoLineOf`。
    c.present(
        "卡片最后一行由**暂存区**统一加（所有卡片唯一的必经之路，漏不了）",
        wr,
        r"detailLines = detailLines \+ listOfNotNull\(lastLine\)",
    )
    c.present(
        "最后一行按「撤回卡 / 批量卡 / 普通卡」三选一（撤回卡不许说「这一步撤不回来」，批量卡不许答应撤回）",
        wr,
        r"val lastLine = when \{\s*\n\s*batch -> AiWrites\.BATCH_UNDO_NOTE\s*\n"
        r"\s*isUndo -> AiRevert\.undoCardLine\(actionId\)\s*\n\s*else -> AiWrites\.undoLineOf\(actionId\)",
    )
    c.present("能撤回的动作会告诉用户执行完会出现「撤回」", revert_code, r"执行完那条消息上会出现「撤回」")
    c.present("撤不回来的动作会写明为什么", revert_code, r"⚠️ 这一步撤不回来：")
    c.present("兜底只兜「新建」这一类（否则这张表会退化成一句万能话）", revert_code, r"private val CREATE_LIKE: Set<String>")
    c.absent(
        "「说一句照上面改回去」那种批量免责的写法不许再出现",
        # ⚠️ 要**去掉注释**再查：这几个文件的文档注释里大量引用被禁掉的那句话
        #    （解释"为什么当初那么做是错的"），不去注释就会把解释当成犯了。
        strip_comments(revert) + strip_comments(resources) + strip_comments(read(AI / "AiWrite.kt")),
        r"照上面改回去",
    )
    c.present(
        "派单的撤回由资源表推导（派单 ↔ 撤回派单）",
        resources_code,
        r"paired\(\s*AiWrites\.ORDERS_ASSIGN\s*,",
    )
    c.present(
        "撤回派单的撤回 = 照原样再派一次（成对动作两边都要声明）",
        resources_code,
        r"paired\(\s*AiWrites\.ORDERS_RECALL\s*,",
    )
    c.present(
        "软删的订单能从回收站恢复（撤回的落点）",
        resources_code,
        r"delete\(AiWrites\.ORDERS_SOFT_DELETE\)",
    )
    c.present(
        "「撤回的撤回」也在（恢复动作自己声明了逆操作）",
        resources_code,
        r"paired\(\s*AiWrites\.ORDERS_RESTORE\s*,",
    )

    # ---- 撤回动作必须有实现、而且不进模型清单 ----
    # ⚠️ 这里**不再扫源码里的 `undoAction = …`**（那个字段已经删了）。
    #    从资源表里把"恢复动作"读出来，再逐个核对它真的注册过——
    #    这比扫一行声明强：它同时保证了"每个可删的资源都配了恢复动作"。
    n_restore_reg = len(re.findall(r"restoreAction\(", basic20 + master20))
    restore_ids = set(re.findall(r"restore = AiInverse\(\s*\n?\s*AiWrites\.(\w+)", resources))
    delete_ids = set(re.findall(r"delete\(AiWrites\.(\w+)\)", resources))
    c.ok("注册了足够多的恢复动作（≥7）", n_restore_reg >= 7, f"实际 {n_restore_reg} 个")
    c.ok("资源表里声明了恢复动作的不少于 8 个资源", len(restore_ids) >= 8, f"实际 {len(restore_ids)} 个")
    registered_actions = set(
        re.findall(r"restoreAction\([^)]*?AiWrites\.(\w+)", basic20 + master20)
    ) | set(re.findall(r"id = (?:AiWrites\.)?(\w+)", basic20 + master20 + AI_join("AiWrite.kt")))
    c.ok(
        "每个恢复动作都真的注册了（不然撤回按钮点下去报「没有执行入口」）",
        restore_ids <= registered_actions,
        f"指向了没注册的：{sorted(restore_ids - registered_actions)}",
    )
    c.ok(
        "每个「声明了恢复动作的资源」都真的有一个删除动作（否则那个恢复动作没人用）",
        len(delete_ids) >= len(restore_ids) - 1,
        f"恢复 {len(restore_ids)} 个 / 删除 {len(delete_ids)} 个",
    )

    # ⚠️ 反向的那一半：**删除类动作必须真的交代过**。
    #    只查"恢复动作存在"是不够的——把某一行 `delete(AiWrites.XXX_DELETE)` 删掉，
    #    上面那些照样绿，而那个动作的撤回就没了（反向验证抓到的就是这个空转）。
    #
    # ⚠️ 2026-09-19 放宽了**交代的方式**（共享地点那一组逼出来的）：
    #    原来只认"挂在资源表上（有恢复动作）"，可共享库那张表是**物理删除、后端没有恢复接口**
    #    （删掉重新录一个点就有，见 `place_service.delete_place` 的注释）。
    #    给它硬凑一个 `delete(...)` 会让撤回表以为"这一步能恢复"，而 `AiRevert` 里
    #    又必须写一句"撤不回来"——两条红线互相打架（`_show_undo_status` 当场报了
    #    「既能撤回、又写了撤不回来的理由（自相矛盾）」）。
    #    所以现在的判据是：**要么有恢复动作，要么在 `none(...)` 里写清了为什么撤不回来**。
    #    两种都是"交代过"，而"什么都没写"照样红。
    decl_delete = set(re.findall(r"id = AiWrites\.(\w*_DELETE)", basic20 + master20 + AI_join("AiWrite.kt")))
    hooked = set(re.findall(r"(?:delete|paired)\(AiWrites\.(\w+)", resources))
    # 「撤不回来」那一桶：`none(listOf(AiWrites.X, ...), "理由")` 里的那些 id
    explained_none = set(
        re.findall(r"AiWrites\.(\w+)", "".join(re.findall(r"none\(\s*listOf\([^)]*\)", AI_join("AiRevert.kt"))))
    )
    missing_undo = sorted(decl_delete - hooked - explained_none)
    c.ok(
        "声明式的删除动作都交代过（挂资源表 / 或在 none 里写清为什么撤不回来）",
        not missing_undo,
        f"这些删除动作既没接撤回、也没写理由：{missing_undo}",
    )

    # ---- 生产实现必须真的会读回现场（默认实现返回 null 是 fail-closed，但不能是唯一实现）----
    c.present(
        "生产数据源覆盖了 snapshot（否则所有撤回会一起静默消失）",
        wsvc,
        r"override suspend fun snapshot\(resourceKey: String, id: Long\)",
    )
    c.present(
        "接口上的 snapshot 默认返回 null（fail-closed：读不到就不给撤回按钮）",
        wsvc,
        r"suspend fun snapshot\(resourceKey: String, id: Long\): AiBefore\? = null",
    )
    res_keys = re.findall(r'key = "([a-z_]+)"', resources)
    missing_branch = [k for k in res_keys if f'"{k}" ->' not in wsvc]
    c.ok(
        "每个资源在数据源的 snapshot 里都有分支（少一个 = 那个资源的撤回全都点不动）",
        not missing_branch,
        f"没有分支的：{missing_branch}",
    )
    c.present("撤回专用动作不进模型清单（能看见但一定失败是最坏的一类 bug）", tools, r"AiWrites\.forModel\(actor\)")
    c.present(
        "forModel 的定义就是「去掉 undoOnly」",
        wr,
        r"fun forModel\(actor: AiActor\?\): List<AiWriteAction> = forRole\(actor\)\.filter \{ !it\.undoOnly \}",
    )

    # ---- 后端：删除必须是"伪装删除"，而且真的能恢复 ----
    soft_files = ["shipper.py", "arrears.py", "freight_templates.py", "price_rules.py", "products.py", "users.py",
                  "driver_billing_rules.py"]
    n_restore_route = 0
    for f in soft_files:
        src = read(ROOT / "backend/app/api/v1" / f)
        n_restore_route += len(re.findall(r'@router\.post\("[^"]*/restore"', src))
        # ⚠️ 判据锚在**删这一行的那段代码**上，不是整个文件（2026-09-19 收紧）：
        #    原来扫的是"整个文件里不许出现 `db.delete(`"，可是
        #    `freight_templates.py` 里现在还有一张**绑定表**（`freight_template_drivers`）——
        #    解绑就是删那一行，它本来就该物理删（绑定关系没有"历史价值"，
        #    要查"这单当时按哪一档算"看的是订单快照）。整文件扫会把这件事判成违规，
        #    而"假违规"的代价是有人开始无视这条红线。
        #    真正要守住的是：**这些主数据自己的删除必须打标记**（`is_deleted = True`）+ 有恢复端点。
        m = re.search(r"def delete_\w+\(.*?(?=\n@router|\Z)", src, re.S)
        # ⚠️ 2026-09-21：判据从「整段里不许出现 `db.delete(`」收紧成「**不许物理删这张主数据的行**」——
        #    运费模板那一轮加了"删除时顺手清掉它的分类绑定"（`freight_template_categories` 是一张
        #    **不软删的关联表**，留着就会让那个分类永远删不掉）。整段扫会把这件事判成违规，
        #    而"假违规"的代价是有人开始无视这条红线。
        #    真正要守住的还是那一句：**这张主数据自己那一行不许被物理删掉**。
        #    ⚠️ 判据不能写成"整段里出现 `db.delete(` 就红"（那会把"顺手清掉关联表的行"判成违规，
        #       而账号那边的删除用的是另一套标记：`is_active = False` + 手机号加后缀）。
        #       所以判据锚在**"删掉你刚查出来的那一行"**：`x = db.get(...)` 之后又 `db.delete(x)`。
        seg = m.group(0) if m else src
        fetched = re.findall(r"(\w+)\s*=\s*db\.get\(", seg)
        physical = [v for v in fetched if f"db.delete({v})" in seg]
        c.ok(f"{f}: 这个模块的删除不是把那一行物理删掉（打标记 / 改名隔离）",
             not physical, f"物理删了查出来的那一行：{physical}")
    c.ok("后端有 ≥7 个恢复端点（每张可撤的表一个）", n_restore_route >= 7, f"实际 {n_restore_route} 个")
    pmodel = read(ROOT / "backend/app/models/product.py")
    c.absent(
        "商品与库存流水之间不再级联删除（否则删商品会抹掉流水）",
        pmodel,
        r"relationship\([\s\S]{0,120}cascade=\"all, delete-orphan\"",
    )
    c.present(
        "商品改动写操作日志（以前一条都不写）",
        read(ROOT / "backend/app/api/v1/products.py"),
        r"OperationAction\.PRODUCT_UPDATE",
    )
    c.present(
        "账号恢复端点会把 `_del{id}` 后缀去掉",
        read(ROOT / "backend/app/api/v1/users.py"),
        r'suffix = f"_del\{u\.id\}"',
    )
    c.present(
        "这一节有反向验证脚本",
        read(Path(__file__).resolve().parent / "_reverse_verify_undo.py"),
        r"AiRevert|resources",
    )
    c.present(
        "有一份「撤回状态总览」脚本（回答「到底改完了没有」，不用一条条读代码去数）",
        read(Path(__file__).resolve().parent / "_show_undo_status.py"),
        r"def main\(\) -> int:",
    )

    # ---- 仓库根目录不许再堆临时产物（用户提的第四条，2026-09-16） ----
    # 原话是「根目录堆了几百个 _*.png / _*.py」。清理那一次是打包进 `_archive/`（**不是删**，
    # 他的要求是「不要删了就搞不回来了」），但清完不钉一条，下一轮就会堆回来——
    # 这一轮我自己就又在根目录留了 8 个 `_tmp_*.png`。
    #
    # 清单**自己算**（glob 根目录的 `_*` 普通文件），白名单只有一条且写了理由。
    root_scratch = sorted(
        p.name
        for p in ROOT.glob("_*")
        if p.is_file() and p.name != "_verify_ast.json"  # 文档正文引用它
    )
    c.ok(
        "根目录没有临时产物（收起来用 _tools/ai/_archive_root_scratch.py）",
        not root_scratch,
        f"还在的有：{'、'.join(root_scratch)}",
    )
    c.present(
        "清理脚本存在（收进 _archive/ 而不是删掉——「不要删了就搞不回来了」）",
        read(Path(__file__).resolve().parent / "_archive_root_scratch.py"),
        r"root-scratch-",
    )
    c.present(
        "这条判据有反向验证（往根目录放一个文件会红）",
        read(Path(__file__).resolve().parent / "_reverse_verify_root_clean.py"),
        r"_zz_reverse_verify_probe\.log",
    )

    # ---- 「异常与审计」的分级/排序只有一处实现（v3.28） ----
    # 用户原话：「上百条审计也翻不到，就该主动做一个分类——按危险层级或紧急层级排序」。
    # 判据钉两件事：①页面必须**调用**那些纯函数（而不是自己 filter/sort，那样单测就管不到
    # 页面真正跑的那条路径）；②纯函数必须真的有单测。
    report_kt = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt")
    priority_kt = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportPriority.kt")
    priority_test = read(
        ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/ReportPriorityTest.kt"
    )
    c.present("异常分级的唯一实现处存在（[ReportPriority]）", priority_kt, r"enum class RiskLevel")
    c.present("页面用的是分级函数，不是自己 filter/sort", strip_comments(report_kt), r"pendingExceptions\(vm\.exceptions\)")
    c.present("已过去的单单独分开（不让它们淹没要处理的那几条）", strip_comments(report_kt), r"pastExceptions\(vm\.exceptions\)")
    c.present("审计排序走同一个函数", strip_comments(report_kt), r"sortedAudits\(vm\.operationLogs")
    c.present("审计内容翻成人话（真机上是直接把 JSON 摆出来）", strip_comments(report_kt), r"auditChangeText\(it\)")
    # ⚠️ 第二遍真机才抓全：第一版只认两种 JSON 形状，其余**原样返回**——
    #    于是 `user_id`、`role: shipper`、`"conflicts": []` 直接躺在审计页上。
    c.present("审计内容按结构渲染（不许把 JSON 兜底摆出去）", strip_comments(priority_kt), r"Json\.parseToJsonElement\(c\)")
    c.present("认不出来的形状也不摆 JSON（明说没有可读明细）", strip_comments(priority_kt), r"这条日志没有可读的明细")
    c.present("清掉说明里的接口路径（用户不需要知道是哪个接口）", strip_comments(priority_kt), r"internal fun stripApiSpeak")
    c.present(
        "[审计说人话] 覆盖库里全部真实形状",
        read(ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/ReportPriorityTest.kt"),
        r"其余的 JSON 形状也要说人话",
    )
    # ⚠️ 审计卡片的**标题**也必须是中文：真机上出现过 `USER_RESTORE`/`PRODUCT_DELETE`
    #    四行英文（表里漏了）。判据**从后端源码扫动作名**，逐个要求 App 侧有中文——
    #    清单自己算，后端加新动作时这里会立刻红。
    label_run = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "_check_action_labels.py"), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    c.ok(
        "审计里每个动作名都有中文（后端源码扫出来逐个对，不是手写清单）",
        label_run.returncode == 0,
        (label_run.stdout or "").strip()[-200:],
    )
    c.present("审计卡片刻「谁 · 什么时候」", strip_comments(report_kt), r"auditWhoWhen\(log\.operatorName")
    c.present("审计卡片写**单号**（不是内部编号）", strip_comments(report_kt), r"log\.orderNo\?\.takeIf")
    c.absent("卡片不许再印「单 #内部编号」", strip_comments(report_kt), r'"单 #" \+')
    c.present("后端出参带操作人姓名", read(ROOT / "backend/app/schemas/operation_log.py"), r"operator_name")
    c.present("后端出参带单号", read(ROOT / "backend/app/schemas/operation_log.py"), r"order_no")
    c.present(
        "库存调整留痕（以前一条都不写）",
        read(ROOT / "backend/app/api/v1/inventory.py"),
        r"OperationAction\.INVENTORY_ADJUST",
    )
    c.present(
        "[谁·什么时候] 有单测",
        read(ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/ReportPriorityTest.kt"),
        r"审计卡片要写清",
    )
    c.present("这条判据有反向验证（页面改回自己 filter 会红）", strip_comments(report_kt), r"var pane by remember")
    for fn in ("exceptionRisk", "exceptionNeedsAction", "pendingExceptions", "pastExceptions", "auditKind", "sortedAudits", "auditChangeText"):
        c.present(f"[{fn}] 有单测", priority_test, rf"{fn}\(|`[^`]*{fn}")

    # ==================================================================================
    print("\n== 21. 随日落自动切换夜间模式（默认关；判定必须在纯函数里）==")
    # 用户 2026-09-17 原话：「在我的里面 3 个端都要有……随时间自动开启夜间模式……
    # 类似于高德的那样子判断……他这个开关默认是关闭着的」。
    #
    # 这一节守的是四条**坏了也不报错**的性质（没有一条能靠功能测试发现）：
    #  ① 开关默认必须是关的 —— 变成默认开，等于不请自来地改掉所有老用户的界面外观；
    #  ② 「几点算天黑」必须在纯函数里 —— 算错的表现是"半夜亮着 / 中午黑着"，
    #     而且**只在特定日期和特定地区出现**（今天在上海试是对的，冬至的哈尔滨就错），
    #     人工在真机上看不全，只能靠单测按季节/纬度/经度/边界逐条钉；
    #  ③ 自动模式下必须禁掉手动开关 —— 否则下一次对表会把它改回去，
    #     用户看到的是"开关自己弹回来了"；
    #  ④ 定时器必须挂在**根节点**、并且回前台要补一次 —— 挂在「我的」页面里就只有
    #     停在那页时才切（而他真正要它的时刻恰恰不在那一页）；后台过夜进程被冻结，
    #     定时器不会醒。
    sun = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/SunClock.kt")
    sun_test = read(ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/SunClockTest.kt")
    auto_ui = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/AutoSunTheme.kt")
    theme = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Theme.kt")
    # ⚠️ 2026-09-21：「随日落」这一行搬进了「我的 → 基础设置」子页（`ui/profile/BasicSettingsScreen.kt`，
    #    用户要求"按钮太多、不重要的放进基础设置"）。所以这一组判据要**同时看两个文件** ——
    #    只盯 `ProfileScreen.kt` 的话下面 5 条会从"在检查"变成"永远找不到"。
    #    （用户没让删的东西，判据也不许悄悄失效：位置变了、判据就得跟着搬。）
    profile = (read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileScreen.kt")
               + "\n"
               + read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/BasicSettingsScreen.kt"))
    main_act = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/MainActivity.kt")

    c.absent("判定里不许出现 Android 依赖（否则单测跑不起来）", sun, r"import android\.")
    c.present("判定在纯函数里（object SunClock）", sun, r"object SunClock \{")
    c.present("界线是太阳高度角 −6°（既不取日落那一刻，也不写死钟点）",
              sun, r"const val CIVIL_ZENITH = 96\.0")
    # ⚠️ 只断言"常量被声明"是空转的（上一轮踩过：常量在、没人用，检查照样绿）。
    #    所以锚到它真的进了公式。
    c.present("这个界线真的用进了公式（不是声明了没人用）", sun, r"cos\(Math\.toRadians\(CIVIL_ZENITH\)\)")
    c.present("按**日期**算（夏至和冬至必须不一样）", sun, r"date\.dayOfYear")
    c.present("经度按时区中央经线推（不申请定位也能用）", sun, r"totalSeconds / 240\.0")
    # ---- 定位（v3.36 把这条红线**反过来**了）----
    # ⚠️ v3.35 这里写的是 `absent("自动切换不许引用定位")`——当时的理由是"为切个夜间模式弹权限框，
    #    用户一拒功能就静默失效了"。用户 2026-09-18 明确要求按手机定位算：
    #    「根据手机的定位算他是在中国大陆哪个区域，然后再根据时间和月份判断太阳几点落山」。
    #    所以现在的红线**换成了三条**（不是删掉）：①能用定位；②拿不到必须退回估算、不能挡住功能；
    #    ③是哪种必须如实告诉用户。原来那条"不许引用定位"留着就是与新需求对着干。
    sun_loc = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/SunLocation.kt")
    amap_loc = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/AmapLocationManager.kt")
    home_ui = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/home/RoleHomeScreen.kt")
    c.present("有定位就按真实经纬度算（用户 2026-09-18 的要求）", sun, r"fun stateHere\(")
    c.present("拿不到坐标必须退回时区估算（定位是精度增强，不是前置条件）",
              sun, r"SunLocation\.coords\(\) \?: return stateAt\(now, zone\)")
    c.present("坐标要校验（0,0 是高德定位失败的哨兵值：拿它算日落会错 8 小时且不报错）",
              sun_loc, r"fun isPlausible\(")
    c.present("(0,0) 判据真的在（±0.01° 以内都当哨兵）",
              sun_loc, r"abs\(lat\) < 0\.01 && abs\(lng\) < 0\.01")
    c.present("校验不过就不收（不许覆盖上一次可用坐标）", sun_loc, r"if \(!isPlausible\(lat, lng\)\) return false")
    c.present("定位成功就喂给自动切换用", amap_loc, r"SunLocation\.update\(pt\.lat, pt\.lng\)")
    # ⚠️ 判据锚在**失败分支的结构**（else 块里不许出现 SunLocation.update），不要锚在那句注释上：
    #    第一版就是锚注释的，结果"把注释删掉换成一行 update"这种注入它照样绿（反向验证抓到的）。
    c.absent("定位**失败**那条分支不许动坐标（失败一次就把可用值清掉 = 时好时坏）",
             amap_loc, r"else \{[\s\S]{0,400}?SunLocation\.update")
    c.present("模拟位置开关只在 debug 放开（否则本机根本验不了按定位算日落）",
              amap_loc, r"isMockEnable = BuildConfig\.DEBUG")
    c.present("定位一到就重算一次外观（不等下一个定时周期）",
              home_ui, r"locations\.collect \{[\s\S]{0,240}?ThemeMode\.refreshAuto")
    c.present("界面如实说明是按定位还是按时区估算（两个精度差很多）",
              profile, r"located = SunLocation\.hasFix\(\)")
    c.present("坐标来源有单测（含 0,0 哨兵与「失败不清值」）",
              read(ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/SunLocationTest.kt"),
              r"一次失败不该把上一次可用坐标清掉")

    # ---- 系统定位兜底（v3.38）----
    # 真机教训：高德这条路上任何一环出问题（Key 没绑当前签名 / 设备上没有高德服务 / 网络到不了
    # 高德服务器 / 清单缺 APSService），坐标就永远是空的 —— 表现是**一直**显示"时区估算"，
    # 而用户以为定位开着。日落只关心经纬度，所以必须有第二条来源。
    dev_loc = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/DeviceLocation.kt")
    c.present("有系统定位兜底（日落不该被高德的鉴权卡死）", dev_loc, r"object DeviceLocation \{")
    c.present("挑坐标的判据在纯函数里（可单测）", dev_loc, r"fun pickBest\(")
    # ⚠️ 只钉 `fun pickBest(` 是不够的（反向验证当场抓到）：把里面"挑新的、挡旧的"整段删掉，
    #    函数还在、检查还绿。所以判据锚在**真的在挑**与**真的在挡**这两句上。
    c.present("真的在挑新的（不是拿第一条就用：可能是几小时前、也可能在别的城市）",
              dev_loc, r"compareByDescending<LocationFix> \{ it\.atMs \}")
    c.present("太旧的缓存要挡掉（手机几天没开过定位时，缓存是上一个城市的）",
              dev_loc, r"nowMs - it\.atMs <= maxAgeMs")
    c.present("高德回调失败时真的会去退兜底",
              home_ui,
              r"if \(DeviceLocation\.requestSingle\(permContext\) != null\) ThemeMode\.refreshAuto\(permContext\)")
    c.present("高德连发起都没成功时也会退兜底（否则一个回调都不会来）",
              home_ui, r"if \(!container\.locationManager\.requestSingle\(\)\)")
    c.present("高德发起结果要能区分成败", amap_loc, r"fun requestSingle\(\): Boolean")
    c.present("兜底拿到坐标也重算一次外观", home_ui, r"DeviceLocation\.requestSingle\(permContext\) != null\) ThemeMode\.refreshAuto")
    # 坐标系不同（高德 GCJ-02 / 系统 WGS-84，国内差几百米）：日落无所谓，地址/水印不行。
    c.absent("兜底不许冒充「带地址的高德点」（不往 locations 流里发）",
             strip_comments(dev_loc), r"AmapLocationPoint|_locations")
    # 清单自己算（glob Android 主源码树）：`SunLocation.coords()` 的消费点必须只有日落那一处
    android_root = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
    coords_users = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in android_root.rglob("*.kt")
        if "SunLocation.coords(" in read(p)
    )
    c.ok(
        "坐标只喂日落（不许被地址/水印拿去用——那是另一套坐标系）",
        coords_users == ["android/app/src/main/java/com/tapmoay/sorders/core/SunClock.kt"],
        f"实际消费点：{coords_users}",
    )
    c.present("兜底也有单测（挑错坐标不会报错，只会天黑得有点晚）",
              read(ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/DeviceLocationTest.kt"),
              r"太旧的缓存不要")

    load_body = fn_body(theme, "fun load(context: android.content.Context)")
    c.present("开关默认关（老用户升级后第一屏必须和以前一样）", load_body, r"getBoolean\(KEY_AUTO, false\)")
    c.present("启动时自动优先（不是只读手动那套）", load_body, r"if \(autoBySun\) SunClock\.stateHere\(\)\.dark else")
    set_body = fn_body(theme, "fun set(context: android.content.Context, dark: Boolean)")
    c.present("自动模式下手动开关被忽略（防「点了一下又自己弹回来」）", set_body, r"if \(autoBySun\) return")
    set_auto_body = fn_body(theme, "fun setAuto(context: android.content.Context, on: Boolean)")
    c.present("开关自己落盘", set_auto_body, r"putBoolean\(KEY_AUTO, on\)")
    c.present("打开的那一刻立刻对一次表（不等下一次定时）", set_auto_body, r"refreshAuto\(context\)")

    # ⚠️ `^` 在这个脚本里不是多行锚（c.present 用的是 re.search 且没开 re.M），
    #    所以锚"独立一行"要写成 `\n\s+…`；写成 `^\s+…$` 会永远找不到（本轮实测踩到）。
    c.present("定时器挂在根节点（挂页面里就只有停在那页才切）", main_act, r"\n\s+AutoSunThemeEffect\(\)")
    resume_body = fn_body(main_act, "override fun onResume()")
    c.present("回前台补一次对表（后台过夜时定时器不会醒）", resume_body, r"ThemeMode\.refreshAuto\(this\)")
    # ⚠️ key 写成整个状态（含 isDark）的话，每次切完主题 key 就变 → 协程取消重启 → 定时器永远从头算。
    c.present("定时器的 key 只能是开关本身", auto_ui, r"LaunchedEffect\(auto\)")
    c.present("睡眠有上限（改了系统时间/换了时区能自愈）", auto_ui, r"coerceIn\(MIN_SLEEP_MS, MAX_SLEEP_MS\)")

    c.present("「我的」页面有这一行（三端共用同一个页面，所以三端都有）",
              profile, r'"随日落自动切换"')
    c.present("那一行右侧的字由纯函数给出（有单测）",
              profile, r"SunClock\.summary\([\s\S]{0,400}?located = SunLocation\.hasFix\(\)")
    c.present("走落盘入口，不直接写内存", profile, r"ThemeMode\.setAuto\(context,")
    c.absent("页面里不许直接写 autoBySun", strip_comments(profile), r"autoBySun\s*=[^=]")
    # 「自动开着时手动开关必须失效」这一条，现在是**两处各管一半**：
    #   ① 开关自己：`enabled = !ThemeMode.autoBySun`；
    #   ② 整行：`onClick = if (ThemeMode.autoBySun) null else { … }`（共用行组件 `ProfileRow`
    #      收到 `onClick = null` 就**不装** clickable，所以"整行点不动"这件事仍然成立）。
    # 两种写法表达的是同一件事，判据按**两处都得有**来数（换写法可以，少一处不行）。
    manual_hits = (profile.count("enabled = !ThemeMode.autoBySun")
                   + profile.count("onClick = if (ThemeMode.autoBySun) null"))
    c.ok("自动模式下那个开关是禁用的（开关 + 整行，两处都要）", manual_hits >= 2, f"命中 {manual_hits} 次")

    n_tests = len(re.findall(r"@Test", sun_test))
    c.ok("判定逻辑有单测（至少 8 条）", n_tests >= 8, f"实际 {n_tests} 条")
    # 四个方向各要有一条：少一个方向，那一类错误就没人拦（清单自己算，不手写）
    for kw in ("夏至", "纬度", "经度", "时区", "极昼", "前后一分钟"):
        c.present(f"单测覆盖了「{kw}」这个方向", sun_test, kw)
    c.ok(
        "这条红线配了反向验证（注入 bug 必须变红）",
        (ROOT / "_tools/ai/_reverse_verify_sun_theme.py").exists(),
        "缺 _tools/ai/_reverse_verify_sun_theme.py",
    )

    # ==================================================================================
    print("\n== 22. 司机计费规则：钱只算一处、历史不可追溯（v3.36）==")
    # 用户 2026-09-18 要的是「一类司机 × 好几种给钱方式」的规则模板，而且要让 AI 帮它配置、挂载。
    #
    # 这一节守的核心只有一句：**"这个司机这单拿多少"必须只有一处实现**。
    # 改造前它散在四处，只是恰好都等于"订单运费"所以看不出问题；一旦规则能配成
    # "固定工资 + 运费 5% 提成"，四处里少改一处就会出现"账单 120、结算页 500"——
    # 两张表对不上、两边都不报错（这个仓库在 billing_mode 的大小写上已经栽过一次）。
    # 所以下面**逐个消费点**断言它调的是 `driver_pay`，而不是自己抄一遍 freight_fee。
    pay_py = read(ROOT / "backend/app/services/driver_pay.py")
    rule_model = read(ROOT / "backend/app/models/driver_billing_rule.py")
    rule_api = read(ROOT / "backend/app/api/v1/driver_billing_rules.py")
    rule_schema = read(ROOT / "backend/app/schemas/driver_billing_rule.py")
    acct = read(ROOT / "backend/app/services/accounting_service.py")
    bills_api = read(ROOT / "backend/app/api/v1/driver_bills.py")
    settle = read(ROOT / "backend/app/api/v1/freight_settlement.py")
    stats_svc = read(ROOT / "backend/app/services/stats_service.py")
    reports_py = read(ROOT / "backend/app/api/v1/reports.py")
    flow = read(ROOT / "backend/app/services/order_flow.py")

    c.present("算法只有一处（[driver_pay.order_pay]）", pay_py, r"def order_pay\(")
    c.present("老口径一字不变（rule=None → 全额运费）", pay_py, r"return OrderPay\(piece=fee, commission=ZERO")
    c.present("按订单上的**规则快照**算（不是司机当前的规则）", pay_py, r"def pay_for_order\(order\)")
    # 逐个消费点：必须调 driver_pay，不许自己抄 freight_fee
    c.present("送达生成账单走 driver_pay", acct, r"pay = pay_for_order\(order\)")
    # ⚠️ 只断言"调了 pay_for_order"是不够的：账单金额那一行仍可能抄订单字段（那样调用就成了摆设）。
    #    所以**逐个消费点**还要断言"金额用的是算出来的 total"。
    c.present("送达账单的金额用的是算出来的应得（不是订单上的运费）", acct, r"amount=pay\.total")
    c.absent("送达生成账单不许再抄运费", strip_comments(acct), r"amount=Decimal\(fee\)")
    c.present("手工补单也走 driver_pay", bills_api, r"pay = pay_for_order\(o\)")
    c.present("补单金额也用算出来的应得", bills_api, r"amount=pay\.total")
    c.absent("补单不许再抄运费", strip_comments(bills_api), r"amount=o\.freight_fee")
    c.present("运费结算页的应得走 driver_pay", settle, r"pay = pay_for_order\(o\)")
    c.present("结算页的合计用的是算出来的应得", settle, r"g\[\"total\"\] = round\(g\[\"total\"\] \+ float\(pay\.total\)")
    c.absent("结算页不许再拿运费当应得", strip_comments(settle), r"fee = float\(o\.freight_fee or 0\)")
    c.present("司机绩效的待结走 driver_pay", stats_svc, r"pay_for_order\(ode\)\.total")
    c.absent("绩效不许再 Σ freight_fee", strip_comments(stats_svc), r"sum\(\(ode\.freight_fee or Decimal")
    # ⚠️ v3.46（2026-09-19 审计 R13-R5）：司机绩效**导出**原来是手写的第三份算法
    #    （平均送达分钟恒空、准时率分母与页面不同、工资制司机印 0），
    #    现在直接调页面用的那个服务——判据跟着改成"调同一个服务"，
    #    而不是"导出里出现过 pay_for_order"（那种锚在手写实现上，越锚越偏）。
    c.present("司机绩效导出与页面**同一个服务**（不再自己写第三份算法）",
              reports_py, r"from app\.services\.stats_service import driver_performance")
    c.absent("司机绩效导出不许再自己算准时率/待结运费",
             strip_comments(reports_py), r"ot_valid = \[1 for x in os")

    # ⚠️ 这两条原来钉的是"orders.py 里那两行赋值"。v3.37 把逐单覆盖值**收进 assign_driver**
    #    （模式快照、规则快照、覆盖值本来就是同一件事的三个字段，分开写会留下半截状态），
    #    所以判据跟着改成"快照 + 覆盖值都由那一个函数写、并且写的是解析出来的 rule"。
    #    仍然钉的是**效果**：快照来源必须是派单那一刻解析的规则，不是司机现在的规则。
    c.present("派单时把规则**快照**到订单上（否则改规则会追溯历史账单）",
              flow, r"order\.driver_rule_snapshot = rule_to_snapshot\(rule\)")
    c.present("派单那一刻才解析规则（快照的来源）", flow, r"rule = rule_of_user\(driver\)")
    c.present("快照坏掉时退回老口径、不许抛异常（不能卡住司机交单）",
              pay_py, r"except Exception:\s*\n\s*return None")
    # 三件参数齐不齐（模型层）
    for col in ("salary", "piece_amount", "piece_unit", "commission_base", "commission_rate", "vehicle_type"):
        c.present(f"规则表有 [{col}] 这一列", rule_model, rf"{col}: Mapped\[")
    c.present("新表在 models/__init__ 里注册过（不注册 create_all 就不建表=线上直接 500）",
              read(ROOT / "backend/app/models/__init__.py"), r"DriverBillingRule")

    # 校验只有一份：Create/Update 不许再写一遍范围约束（写了两份必然走散）
    c.present("参数校验只有一份（[validate_rule_params]）", rule_schema, r"def validate_rule_params\(")
    c.absent("schema 里不许重复写范围约束（否则越界返回英文 422 而不是中文原因）",
             rule_schema, r"le=100|ge=0")
    # 三条拦截
    c.present("还挂着司机时不许删（删了那批人会静默退回老算法）", rule_api, r"个司机挂着这份规则")
    c.present("车型对不上要拦（挂错车型=每一单都算错钱）", rule_api, r"车型对不上")
    c.present("挂载是**唯一**写路径（PATCH /users 不许也能改）",
              rule_api, r'prefix="/driver-billing-rules"')
    c.absent("users.py 里不许出现第二条挂载写路径（给模型字段赋值不算）",
             strip_comments(read(ROOT / "backend/app/api/v1/users.py")), r"\bu\.driver_rule_id\s*=")
    c.present("司机端看不到规则里的工资金额（沿用「工资仅派单员可见」）",
              read(ROOT / "backend/app/api/v1/users.py"), r"include_money=is_dispatcher")
    c.present("两个新动作在审计页有中文", read(UI / "dispatcher/ReportCenter.kt"), r'"DRIVER_RULE_UPSERT" -> "改司机计费规则"')

    # AI 侧：五个动作 + 撤回接线
    aw = read(AI / "AiWrite.kt")
    for name in ("DRIVER_RULE_CREATE", "DRIVER_RULE_UPDATE", "DRIVER_RULE_DELETE",
                 "DRIVER_RULE_ATTACH", "DRIVER_RULE_RESTORE"):
        c.present(f"AI 动作 {name} 声明了", aw, rf'const val {name} = "driver_rule\.')
    basic22 = read(AI / "AiWriteBasicData.kt")
    c.present("AI 能建规则（带中文卡片）", basic22, r"id = AiWrites\.DRIVER_RULE_CREATE")
    c.present("AI 能挂规则给司机（用户点名要的）", basic22, r"id = AiWrites\.DRIVER_RULE_ATTACH")
    c.present("挂载的卡片写清「只管以后」", basic22, r"只管以后")
    c.present("解挂的语义写清楚了（不带规则名=解除，不是查不到）", basic22, r"不带就是解除他的计费规则")
    c.present("删除动作挂上了撤回资源", read(AI / "AiResources.kt"), r"delete\(AiWrites\.DRIVER_RULE_DELETE\)")
    c.present("挂载回答了「误操作了怎么办」（撤不回来 + 手工怎么退）",
              read(AI / "AiRevert.kt"), r"none\(\s*\n\s*listOf\(AiWrites\.DRIVER_RULE_ATTACH\)")
    c.present("AI 能读到规则名册（按名字挂载的前提）",
              read(AI / "AiWriteService.kt"), r"override suspend fun driverRules\(\)")
    c.present("撤回现场读得回来（资源快照有 driver_rule 分支）",
              read(AI / "AiWriteService.kt"), r'"driver_rule" ->')

    # 测试：钱必须被端到端钉住（纯函数单测证明不了"送达那一刻真调了它"）
    c.present("纯函数单测存在（三件怎么组合、快照、校验）",
              read(ROOT / "backend/tests/test_driver_pay.py"), r"def test_固定工资加提成加每单_三件可以同时给")
    c.present("端到端单测断言了手算金额（250.00）",
              read(ROOT / "backend/tests/test_driver_billing_api.py"), r'Decimal\("250\.00"\)')
    c.present("端到端单测钉住「改规则不追溯已派单」",
              read(ROOT / "backend/tests/test_driver_billing_api.py"), r"test_改规则不动已经派出去的单")

    # ---- 抽成范围 + 逐单参数（用户 2026-09-18 补的两条）----
    rule_py = read(ROOT / "backend/app/schemas/driver_billing_rule.py")
    order_model = read(ROOT / "backend/app/models/order.py")
    orders_api = read(ROOT / "backend/app/api/v1/orders.py")
    wsvc22 = read(AI / "AiWriteService.kt")
    # AI 侧这三条只钉"逐单参数真的走完了全程"：声明（模型看得到）→ 卡片（用户看得到）
    # → payload/实参（真的传给了后端）。只钉声明的话，参数会变成"卡片上写着、请求里没有"。
    c.present("AI 派单声明了逐单金额参数（模型看得到）", read(AI / "AiWrite.kt"), r'"piece_amount"')
    c.present("AI 派单声明了逐单提成参数（模型看得到）", read(AI / "AiWrite.kt"), r'"commission_rate"')
    c.present("派单卡片写出「他现在的计费规则」（看不见规则=闭着眼睛点确认）",
              read(AI / "AiWriteOrderHandlers.kt"), r"他现在的计费规则：")
    c.present("AI 把逐单金额真的传给了后端（不是只在卡片上写着）",
              read(AI / "AiWriteOrderHandlers.kt"), r'pieceAmount = payload\.str\("driver_piece_amount"\)')
    c.present("AI 把逐单比例真的传给了后端",
              read(AI / "AiWriteOrderHandlers.kt"), r'commissionRate = payload\.str\("driver_commission_rate"\)')
    c.present("司机名册带着「他现在怎么算钱」（卡片那行字的来源）", wsvc22, r"note = it\.paySummary")
    c.present("撤回→反悔时逐单覆盖值照原样搬回来（否则反悔后钱悄悄变回默认值）",
              read(AI / "AiResources.kt"), r'"driver_piece_amount" to "driver_piece_amount"')
    # 名单字段的形状必须和"写"的时候一样（写法是"名字、名字"）：给编号列表会被当成商品名去匹配 → 撤回失败。
    c.present("抽成范围读得回来（撤回改规则时不丢范围）",
              read(AI / "AiResources.kt"),
              r'put\("commission_products", d\.commissionProductNames\.joinToString\("、"\)\)')
    c.present("计件可以是「拿这一单的钱」（每单不固定，派单员定）",
              pay_py, r'piece_unit == "order_price"')
    c.ok("order_price 是合法取值", '"order_price"' in pay_py)
    c.present("抽成能限定「哪些商品」（只在商品金额抽成时算）",
              pay_py, r"def order_goods_amount\(order, product_ids")
    # ⚠️ 判据必须锚**决定包含哪几行**的那一句，不能锚 `scope = ...` 那种"接线"：
    #    第一版锚的就是接线，结果把 `if product_ids:` 改成 `if False:`（范围彻底失效、
    #    按整单多给钱）它照样绿——反向验证当场抓到（见 _reverse_verify_billing.py）。
    c.present("范围真的决定了算哪几行（不是声明了没人用）",
              pay_py, r"if pid is None or int\(pid\) not in product_ids:")
    # 开关本身也要钉：把 `if product_ids:` 改成 `if False:`（范围彻底失效）时，
    # 上面那条"决定算哪几行"还在原地，只有这一条能拦住它。
    c.present("范围生效的开关在（product_ids 非空才按范围算）", pay_py, r"if product_ids:")
    # ⚠️ 2026-09-21：`else` 那一支从 `rule.commission_rate` 变成 `base_rate` ——
    #    因为"每单金额/比例"现在有两种形态（所有单统一 / 按运费分类），
    #    基价先由 `piece_mode` 解析成 `base_piece` / `base_rate`，逐单覆盖仍然**优先**。
    #    判据的**意思一个字没变**（覆盖值优先），改的只是右边那个来源。
    c.present("算钱时优先用逐单覆盖的比例（否则派单员定的比例会被规则默认值盖掉）",
              pay_py, r"rate = money\(rate_override\) if rate_override is not None else base_rate")
    c.present("规则表有抽成范围这一列", rule_model, r"commission_product_ids: Mapped\[")
    c.present("抽成范围只在商品金额抽成上合法（按运费抽时没有这回事）",
              rule_py, r"只能配在按商品金额抽成上")
    # ⚠️ 2026-09-21：这条原来锚的是**裸子串** `不能同时配`，而这句话在**两条**报错里都有
    #    （「…与「按分类定价」不能同时配」/「…和「按运费抽成」不能同时配」）—— 把后者删掉，
    #    它照样被前者满足 → 断言永远绿。反向验证 `_reverse_verify_billing.py` 当场报了
    #    「注入后 §22 没有报红 —— 判据是空转的」，就是这一条。
    #    （与 `_check_order_return.py` 里 `ORDER_RETURN\b` 那次是同一类：**裸子串会被兄弟文案满足**。）
    #    现在两条各钉各的：谁被删掉，对应的那条就红。
    c.present("「拿这一单的钱」不许再叠按运费抽成（那等于 100%+X%）",
              rule_py, r"不能同时配（那等于拿 100% 再加提成）")
    c.present("「拿这一单的钱」也不许和「按分类定价」同时配（前者本来就逐单不同）",
              rule_py, r"不能同时配（前者本来就逐单不同）")
    c.present("抽成范围里的商品必须真的存在（对不上就 400）",
              rule_api, r"抽成范围里有对不上的商品编号")
    c.present("逐单覆盖：订单上有这一单单独的金额/比例",
              order_model, r"driver_piece_amount: Mapped\[Decimal \| None\]")
    c.present("派单时真的会写这两个覆盖值", flow, r"order\.driver_piece_amount = piece_override")
    c.present("派单时真的会写这两个覆盖值", flow, r"order\.driver_commission_rate = rate_override")
    # 逐单覆盖"填了不生效"是最坏的一种失败（界面有数字、账单也有数字，只有对账才发现两个数没关系）：
    # 判据放在 driver_pay 一处，派单入口先验再做。
    c.present("覆盖值不生效时先验（司机没挂规则 / 规则里没有提成项）",
              pay_py, r"def override_problem\(")
    c.present("派单入口先验再做（失败时订单一个字段都没动过）",
              flow, r"problem = override_problem\(rule,")
    # ⚠️ 上面那条只钉住了"算了一次 problem"——把后面那个 raise 删掉它照样绿（第一版就是这样，
    #    反向验证当场抓到：注入"不做先验"之后 §22 一声不响）。判据必须锚在**真的会抛**那一句上。
    c.present("先验的结果真的会拦住这次派单（不是算完就扔）",
              flow, r"if problem:\s*\n\s*raise ValueError\(problem\)")
    c.present("逐单定额会写成「这张单按单付钱」（否则那笔钱掉进工资制不生成账单的缝里）",
              pay_py, r"def dispatch_mode\(")
    # 同上：只钉调用点等于没钉——把 dispatch_mode 内部那个分支改成 `if False:`，
    # 调用点一字未动、钱静默消失。所以判据锚在**那个分支本体**上。
    c.present("模式快照真的把逐单覆盖算成按单付钱（不是声明了没人用）",
              pay_py, r"if piece_override is not None or rate_override is not None:\s*\n\s*return \"PIECE\"")
    c.present("模式快照是派单那一刻写的", flow, r"order\.driver_billing_mode_snapshot = dispatch_mode\(")
    c.present("算钱时优先用逐单覆盖值", pay_py, r"rate_override=getattr\(order, \"driver_commission_rate\"")
    c.present("账单能写出「这一单是单独定的」", pay_py, r"rate_overridden")
    # 账单说明里的比例必须是**这一次实际用的**（`rate_used`），不是规则里的默认值——
    # 用默认值会印出一句算术上不成立的话（真机 E2E 抓到过「运费的 5.00% = 80.00」）。
    c.present("账单说明印的是实际用的比例（不是规则默认值）",
              acct, r'rate = getattr\(pay, "rate_used", None\)')
    c.present("逐单覆盖在账单说明里被标出来", acct, r"这一单单独定的")
    c.present("AI 能配抽成范围（名单字段）", read(AI / "AiWriteBasicData.kt"), r'"commission_products"')
    c.present("名单解析仍走唯一那份严格匹配（认不出来就给候选，不自己挑）",
              wsvc22, r"AiWriteArgs\.strict\(it, pool, \"商品\"\)")
    api_tests = read(ROOT / "backend/tests/test_driver_billing_api.py")
    c.present("端到端钉住抽成范围（范围外不提）", api_tests, r"test_按商品金额提成_可以只对指定商品抽")
    c.present("端到端钉住逐单提成覆盖", api_tests, r"test_派单时能给这一单单独定提成比例")
    c.present("端到端钉住「各司机互不干扰」", api_tests, r"test_两个司机各挂各的规则_算钱互不干扰")
    c.present("端到端钉住「覆盖值不生效要拒绝」",
              api_tests, r"test_逐单覆盖值不生效时要拒绝_不能收了不算")
    c.present("端到端钉住「工资制司机被逐单定额后这单按单付钱」",
              api_tests, r"test_工资制司机被逐单定额_这张单就按单付钱")

    # ---- 23. 商品/订单行/收款 的金额完整性（v3.39 缺陷挖掘的产物）----
    print("\n== 23. 金额与收款：只认服务端算的、商品引用要真实、一张单只能核销一次 ==")
    prod_schema = read(ROOT / "backend/app/schemas/product.py")
    lines_api = read(ROOT / "backend/app/api/v1/order_products.py")
    guard_tests = read(ROOT / "backend/tests/test_product_order_guards.py")
    c.present("行金额的判据只有一处（resolve_line_total）", flow, r"def resolve_line_total\(")
    # ⚠️ 锚在**真的会抛**那一句上：只钉函数存在的话，把 raise 删掉照样绿（§22 已经栽过一次）。
    c.present("对不上的行金额真的会被拒（不是算完就扔）",
              flow, r'if abs\(g - computed\) > LINE_TOTAL_TOLERANCE:\s*\n\s*where = ')
    c.present("容差是「吸收四舍五入」级别的一分钱，不是「随便差一点」",
              flow, r'LINE_TOTAL_TOLERANCE = Decimal\("0\.01"\)')
    c.present("先乘再按分四舍五入（先收单价会把误差放大）",
              flow, r"computed = money\(Decimal\(str\(unit_price\)\) \* qty\)")
    c.absent("下单不再「客户端给了就用客户端的」", strip_comments(flow), r"lt = getattr\(line, \"line_total\", None\)")
    c.present("下单被拒时是 400 + 中文原因（不是 500）",
              orders_api, r"except ValueError as e:\s*\n\s*raise HTTPException\(status_code=status\.HTTP_400_BAD_REQUEST")
    c.present("加行也走同一份判据", lines_api, r"resolve_line_total\(body\.unit_price, body\.quantity, body\.line_total\)")
    c.present("改行也走同一份判据（改数量要重算金额）",
              lines_api, r"op\.line_total = resolve_line_total\(new_up, new_qty, body\.line_total\)")
    c.absent("改行不许再直接收客户端金额", strip_comments(lines_api), r"if body\.line_total is not None:\s*\n\s+op\.line_total = body\.line_total")
    # ⚠️ 这三条的第一版锚的是「函数在不在 / 签名在不在」——反向验证当场证明它是空转的：
    #    把 raise 换成 pass、把 detail 换成 "x"，函数和签名都还在。判据必须锚**拒绝本身**
    #    （那句中文原因只出现在 raise 里）。
    c.present("商品编号必须真的在库里（不是只声明了个函数）",
              lines_api, r"不在商品库里")
    c.present("已删除的商品要单独说清", lines_api, r"已经删除了")
    # ⚠️ 判据不能锚"那句中文原因在不在"——把 `if prod is None:` 改成 `if False:`，字符串还在文件里，
    #    检查照样绿（反向验证第二次抓到这个）。要锚**判断 + 紧接着就抛**这个结构。
    c.present("下单时也校验商品编号：不存在要拒（否则成本快照按 0 记、毛利虚高）",
              flow, r"if prod is None:[\s\S]{0,200}?raise ValueError\(")
    c.present("下单时也校验商品编号：已删除要拒（否则送达时不扣库存）",
              flow, r"if prod\.is_deleted:[\s\S]{0,200}?raise ValueError\(")
    # 商品的价格/成本：这两个字段原来是**没有下限**的，能建出负价商品
    c.present("商品单价不许为负（create）", prod_schema, r"default_unit_price: Decimal = Field\(default=Decimal\(\"0\"\), ge=0\)")
    c.present("商品成本不许为负（create）", prod_schema, r"cost_price: Decimal = Field\(default=Decimal\(\"0\"\), ge=0\)")
    c.present("商品单价不许为负（update）", prod_schema, r"default_unit_price: Decimal \| None = Field\(None, ge=0\)")
    blank_guards = prod_schema.count('raise ValueError("商品名不能为空或纯空格")')
    c.ok("商品名去空格后不能为空（建/改两条路都要拦）", blank_guards >= 2, f"实际 {blank_guards} 处")
    c.present("端到端钉住上面每一条",
              guard_tests, r"test_行金额由服务端算_客户端给了对不上的数要拒绝")
    for kw in ("test_已删除的商品不许下单", "test_手输的自定义商品行仍然可以下单", "test_改数量时行金额跟着重算"):
        c.present(f"端到端钉住「{kw}」", guard_tests, kw)

    # ---- 收款：一张单只能核销一次（v3.39 探针实测：原来可以核销两次）----
    pay_tests = read(ROOT / "backend/tests/test_payment_inventory_arrears.py")
    acct = read(ROOT / "backend/app/services/accounting_service.py")
    # 同 §23 前面那条：锚"判断 + 紧接着就抛"，不锚"这句中文在不在文件里"。
    c.present("已经收过款的单不能再逐单核销（否则同一张单两条收款记录、两条现金流水）",
              acct, r"if o\.paid or m\.arrears <= 0:[\s\S]{0,400}?raise ValueError\(")
    # v3.44（2026-09-20 按商品核销）：**核销金额不许超过这一单的欠款**。
    # 判据是"判断 + 紧接着就抛"（与上面同一条理由）；它挡的是"退过货的单被按原价全额收钱"
    # 和"并发两次各收一遍"这两件都会把钱收多的事。
    c.present("核销金额不许超过欠款（退过货的单上 line_total 之和已经不是欠款了）",
              acct, r"if part > m\.arrears:[\s\S]{0,400}?raise ValueError\(")
    # v3.45（2026-09-20 账本页「点合计批量核销」）：**整单核销收的是还欠的钱**。
    # 这条是上面那条的另一半：`arrears` 才是"这一单还能收多少"，而"当时卖了多少"（`receivable`）
    # 在一张**按商品核销过一部分**的单上偏大 —— 客户端按欠款发、后端按应收算，两边金额对不上
    # （这种单从此再也收不动）；金额要是凑巧对上了，就是**多收**。
    c.present("整单核销收的是**还欠的钱**（部分核销过的单要能收剩下那部分）",
              acct, r"else m\.arrears\b")
    c.absent("整单核销不许按「应收」算（会多收，或让收过一半的单再也收不动）",
             strip_comments(acct), r"else m\.receivable\b")
    c.present("按商品核销的金额按行算（与整单核销同一份行级算法，不许各算一遍）",
              acct, r"line_receivable\(op\) for op in picked\[oid\]")
    c.present("只有「这次收完就结清」的单才翻 paid（部分核销必须留在未收）",
              acct, r"settling = \[oid for oid in order_ids if per_order\[oid\] >= money\[oid\]\.arrears\]")
    c.present("并发下的欠款判定走加锁读（REPEATABLE READ 的快照会让两个请求都读到旧值）",
              acct, r"money_map\(db, list\(locked\.values\(\)\), lock=True\)")
    c.present("拒绝时要说清怎么办（补差额改用滚动收款）", acct, r"如果是补差额，请改用「滚动收款」")
    c.present("端到端钉住「同一张单不能被逐单核销两次」",
              pay_tests, r"test_同一张单不能被逐单核销两次")
    c.present("端到端钉住「补差额仍可走滚动收款」（拦住重复核销不能把正当需求也堵死）",
              pay_tests, r"test_逐单核销仍然可以滚动作补差额")

    # ---- 24. 报表口径必须闭合（v3.39 缺陷挖掘第二轮：挂账结清的钱凭空消失）----
    print("\n== 24. 报表口径：营业额 = 已收 + 挂账（一笔钱只有两个去处）==")
    reports_py = read(ROOT / "backend/app/api/v1/reports.py")
    report_schema = read(ROOT / "backend/app/schemas/reports.py")
    recon_tests = read(ROOT / "backend/tests/test_report_reconciliation.py")
    # ⚠️ 判据锚在**完整划分**这个结构上：两条带条件的判据（cash 且已收 / arrears 且未收）
    #    会让"挂账结清"（arrears + paid=True）这种组合两边都不算——钱在报表上凭空消失。
    #
    # 2026-09-20（按商品核销 + 退货）之后，划分从"营业额 = 已收 + 挂账"变成
    # **"应收 = 净已收 + 欠款"**，而三个数都改由 `services/order_money.py` 一处算
    # （`paid` 一个布尔表达不了"收了一半"或"退掉一部分"）。所以判据改成两条：
    # ① 报表**必须**用那一处的数（三句都在）；② 报表**不许**再自己把订单行加起来。
    c.present("营业额取自唯一口径（应收＝卖的 − 退的）",
              reports_py, r"amount = mm\.receivable")
    c.absent("不许在报表里自己把订单行加起来当营业额（退货红冲会整个漏掉）",
             strip_comments(reports_py), r"amount = sum\(\(lp\.line_total")
    c.present("已收按**净额**入账（含现场收的现金，减掉退给客户的现金）",
              reports_py, r"collected \+= mm\.settled - mm\.refunded")
    c.present("挂账入账用的是这一单的**欠款**（不是当时卖了多少）",
              reports_py, r"arrears_total \+= mm\.arrears")
    c.present("一批订单的钱一次算完（不在循环里逐单查）",
              reports_py, r"money = money_map\(db, orders\)")
    c.present("挂账单位报表也用欠款口径（同一份钱，两个页面不许各算一遍）",
              reports_py, r"g\[\"amount\"\] \+= mm\.arrears")
    c.absent("不许再用「cash 且已收 / arrears 且未收」这种带条件的判据",
             strip_comments(reports_py), r'\) == "cash" and o\.paid')
    c.present("出参写清「已收」的含义（含挂账结清，不再是现金已收）",
              report_schema, r"paid=True 即算，含挂账结清")
    c.present("端到端钉住闭合性（挂账结清：已收 +100 / 挂账 -100）",
              recon_tests, r"test_挂账结清之后钱要从挂账挪到已收_不能凭空消失")
    c.present("端到端钉住「删掉的单不再算进营业额」",
              recon_tests, r"test_删掉的单不再算进营业额")
    # 口径变了名字不改 = 下一颗雷：App 报表页那一行也必须从「现金已收」改成「已收」
    report_ui = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt")
    c.absent("报表页不许再写「现金已收」（口径已含挂账结清）", report_ui, r"现金已收")
    c.present("报表页那一行写的是「已收」", report_ui, r'StatRow\("已收", money\(data\.collected\)')

    # ---- 25. 并发保护：状态跃迁与核销都是"读-判断-写"，先锁行（v3.39 第三轮）----
    print("\n== 25. 并发：同一张单被两个请求同时写（派单/送达/核销）==")
    probe_tool = read(ROOT / "_tools/qa/_probe_core_flows.py")
    c.present("有一个「锁住订单行再判状态」的入口（唯一一处）", flow, r"def lock_order_row\(")
    # ⚠️ 锚"锁 + **很快**判状态"这个结构：只钉函数存在的话，把调用删掉照样绿（§23/§24 都栽过）。
    #    中间允许夹着别的守卫（2026-09-19 审计 R13-D1 在"锁"和"判状态"之间插了
    #    「隔离区（软删除）的单不许派/不许送达」——那是同一个位置的另一道闸，不该让判据变红，
    #    所以窗口放宽到 400 字符，而不是把新守卫挪到别处去迎合正则）。
    c.present("派单前真的先锁再判状态",
              flow, r"order = lock_order_row\(db, order\)[\s\S]{0,400}?if order\.status != OrderStatus\.PENDING_DISPATCH")
    c.present("送达前真的先锁再判状态",
              flow, r"order = lock_order_row\(db, order\)[\s\S]{0,900}?if order\.status != OrderStatus\.ACCEPTED")
    # ⚠️ 判据必须锚**代码行**（`try:` 之后的 refresh），不能只写 `db.refresh(order, with_for_update=True)`：
    #    `lock_order_row` 的 docstring 里也写着这句话，只按那句话找的话，
    #    把代码行改成不刷新（`db.refresh(order)`）检查照样绿——反向验证当场抓到了这个空转。
    c.present("锁要连值一起刷新（否则等的锁白等，仍是事务开始时那份旧状态）",
              flow, r"try:\s*\n\s*db\.refresh\(order, with_for_update=True\)\s*\n\s*return order")
    # v3.40：**光有行锁不够** —— SQLite 不支持 `SELECT … FOR UPDATE`（SQLAlchemy 直接忽略），
    # 本地两个并发 complete 各自通过状态检查，实测把同一张单生成两条 60 元账单。
    # 所以状态跃迁必须再有一道**条件 UPDATE 占位**（改到 1 行的人继续），这条在两种库上都原子。
    # 判据放宽成"在这个 CAS 的 where 里"，不锚单行写法：2026-09-19 审计 R13-D1 给两个 CAS
    # 各加了一条 `Order.deleted_at.is_(None)`（隔离区的单不许派/不许送达），
    # `.where(` 于是变成多行——**判据锚的是"这条条件在不在"，不是"它写在第几行"**。
    c.present("派单是条件 UPDATE 占位（SQLite 也生效，不靠行锁）",
              flow, r"update\(Order\)[\s\S]{0,300}?Order\.status == OrderStatus\.PENDING_DISPATCH[\s\S]{0,300}?\.values\(status=OrderStatus\.DISPATCHED, driver_id=driver\.id")
    c.present("送达是条件 UPDATE 占位（SQLite 也生效，不靠行锁）",
              flow, r"\.where\([\s\S]{0,200}?Order\.status == OrderStatus\.ACCEPTED")
    # 隔离区的单不许被这两个跃迁碰到（R13-D1：读侧 404、写侧也必须拒绝）
    c.present("派单/送达的 CAS 都带「隔离区的单不算」（deleted_at is None）",
              flow, r"Order\.status == OrderStatus\.ACCEPTED,[\s\S]{0,200}?Order\.deleted_at\.is_\(None\)")
    # ⚠️ 拆单也是状态跃迁（待派单 → 撤销 + 建 N 张子单），它原来是本文件里**最后一处**
    #    "先读状态、再无条件赋值"的跃迁（2026-09-23 并发实测抓到）：
    #    3 个线程同时点拆单时，第二个人之所以没拆成，靠的是子单 `order_no` 的**唯一约束**兜底，
    #    报出来的是「已经有一条一模一样的记录了…请换一个再试」——用户只是双击了一下。
    #    现在抢占发生在**建子单之前**（抢不到就报"已被派单/撤销/拆分"）。
    c.present("拆单也是条件 UPDATE 占位（抢占要在建子单之前）",
              flow, r"Order\.status == OrderStatus\.PENDING_DISPATCH,[\s\S]{0,200}?\.values\(status=OrderStatus\.CANCELLED, cancelled_at=_now\(\)\)")
    c.present("拆单占位抢不到要回滚 + 中文原因（不是靠子单号唯一约束兜底）",
              flow, r"if claimed\.rowcount != 1:\s*\n\s*db\.rollback\(\)\s*\n\s*raise ValueError\(\"这张单刚刚被别的操作改过（可能已被派单/撤销/拆分）")
    c.absent("拆单里不再有「无条件写状态」那一行（多一处赋值就多一条绕过占位的路）",
             flow, r"order\.status = OrderStatus\.CANCELLED")
    c.present("占位失败（rowcount≠1）要回滚并给出中文原因，不能继续往下走",
              flow, r"if claimed\.rowcount != 1:\s*\n\s*db\.rollback\(\)")
    # 锁不住 ≠ 崩：并发下 refresh 会抛 InvalidRequestError，必须退化成"重新查一次"
    c.present("锁行取不到时要退化成重新查（否则并发重复提交拿到 500）",
              flow, r"except SaInvalidRequest:[\s\S]{0,200}?select\(Order\)\.where\(Order\.id == order\.id\)\.with_for_update\(\)")
    c.present("条件 UPDATE 占位用的是 update(Order)（不是手写 SQL 字符串）",
              flow, r"update\(Order\)")
    # ⚠️ 同样锚"形状"不锚变量名（见下面同组注释）：改名 `ids` → `order_ids` 不该让红线变红。
    c.present("逐单核销也要锁订单行（否则两个请求都读到 paid=False）",
              acct, r"select\(Order\)[\s\S]{0,120}?\.where\(Order\.id\.in_\(\w+\)\)[\s\S]{0,80}?\.with_for_update\(\)")
    c.present("探针里有「并发」这一组（不然这类缝隙没人盯）",
              probe_tool, r'"并发": probe_concurrency')
    # v3.40：并发送达的**钱**不变式要有回归测试（本地能复现的那条）
    conc_tests = read(ROOT / "backend/tests/test_concurrent_delivery_money.py")
    c.present("并发送达只许生成一条账单（钱付两次的回归测试）",
              conc_tests, r"def test_double_complete_sequential_creates_one_bill")
    c.present("条件 UPDATE 占位在本机数据库上确实「只有一个赢家」（有测试钉着）",
              conc_tests, r"def test_conditional_claim_is_atomic_on_this_db")
    # v3.41：**逐单核销**是同一道缝的另一面 —— 探针在本机实测复现过
    #        「两个请求都 200、同一张单两条收款记录」（钱多记一笔）。
    #        只靠 `with_for_update()` 不行：SQLite 直接忽略它（生产 MySQL 才有行锁），
    #        所以这里也补了条件 UPDATE 占位，判据同样锚在**那个 UPDATE 的形状**上。
    #
    # ⚠️ 判据锚"形状"，不锚变量名（2026-09-19）：原来正则写死了局部变量 `ids`，
    #    审计后把那段校验提出来给两种 settle_mode 共用、变量改名 `order_ids`，四条断言立刻全红——
    #    而那四条**钉的是并发保护，不是变量名**。红线的价值在于"保护还在不在"，
    #    所以这里一律用 `\(\w+\)` 匹配列表变量名。
    c.present("逐单核销也用条件 UPDATE 占位（SQLite 也生效，不靠行锁）",
              acct, r"\.where\(Order\.id\.in_\(\w+\), Order\.paid\.is_\(False\)\)")
    # 只钉"有个 UPDATE"不够：抢不到行（rowcount 少）却继续往下走等于没占位。
    # ⚠️ 这里必须**把 rowcount 检查钉在逐单核销那一处**（2026-09-23 反向验证抓到空转）：
    #    原来只写 `if claimed.rowcount != len\(\w+\):` —— 而滚动收款那一支的形状一模一样
    #    （`!= len(settling)`），于是把**逐单核销**的 rowcount 检查改成 `if False:` 之后，
    #    判据被另一处的 `len(settling)` 喂饱，照样绿。
    c.present("逐单核销占位抢不到（rowcount 少）要回滚并给中文原因",
              acct, r"Order\.id\.in_\(order_ids\), Order\.paid\.is_\(False\)\)[\s\S]{0,300}?if claimed\.rowcount != len\(order_ids\):\s*\n\s*db\.rollback\(\)")
    # 收款流水必须"逐单写自己那一份"：写 None 会 500（NOT NULL），
    # 写全额则 N 张单就是 N 倍钱（滚动收款曾经就是这样）。
    c.present("逐单核销按每张单各自那部分写流水（不是每张都写全额）",
              acct, r"for oid, part in per_order\.items\(\)")
    c.present("滚动收款的流水是**一笔**（不绑单、金额=实收）",
              acct, r"db\.add\(CashFlow\(order_id=None, amount=body\.amount")
    c.present("逐单核销占位在本机数据库上有原子性测试",
              conc_tests, r"def test_paid_claim_is_atomic_on_this_db")
    # ---- 25b. 结算单的状态跃迁也是"读-判断-写"（2026-09-19 审计第十七轮）----
    # 付款（`pay_settlement`）从第十二轮起就有条件 UPDATE 占位，但**确认与作废没有**：
    # `confirm × cancel` 并发时两个请求都读到 DRAFT、各自往下走 → 终态可能是
    # 「结算单 CANCELLED + 明细已 SETTLED」：那批账单既不 OPEN（结算单不再收）也不可付
    # （付款要 CONFIRMED）→ **司机这笔钱永远结不掉，只能改库**。
    # 判据锚"那段 UPDATE 的形状"（`update(DriverSettlement)` + `status ==` 条件 + rowcount 校验），
    # 不锚函数名与行号。
    # ⚠️ 判据必须锚到**确认**那一个（`.values(status=CONFIRMED)`）：只写
    #    "有个 update(DriverSettlement) + DRAFT 条件"的话，`cancel_settlement` 里那段
    #    形状一模一样 → 把确认的 CAS 整段删掉，判据照样绿（反向验证当场抓到）。
    c.present("确认结算单是条件 UPDATE 占位（不是读 DRAFT 后无条件赋值）",
              acct, r"update\(DriverSettlement\)[\s\S]{0,240}?DriverSettlement\.status == SettlementStatus\.DRAFT\)\s*\n\s*\.values\(status=SettlementStatus\.CONFIRMED\)")
    c.present("确认/作废抢不到行要回滚并给中文原因",
              acct, r"if claimed\.rowcount != 1:\s*\n\s*db\.rollback\(\)[\s\S]{0,200}?结算单")
    c.present("作废结算单也要占位（cancel × confirm 并发不许两个都成立）",
              acct, r"SettlementStatus\.CANCELLED\)\s*\n\s*\)\s*\n\s*if claimed\.rowcount != 1")
    # 月薪单："先查再插"没有唯一索引兜底（`(order_id, bill_type)` 里的 order_id 是 NULL，
    # NULL 在唯一索引里互不相等）→ 并发生成两张月薪单，结算单把两行一起 sum（¥4500 → ¥9000），
    # 而确认时的"金额与明细合计一致"校验**会通过**。所以生成前必须锁住司机行。
    bills_src = read(ROOT / "backend/app/api/v1/driver_bills.py")
    c.present("月薪单生成前锁住司机行（先查再插 + NULL 不参与唯一索引 = 付两次月薪）",
              bills_src, r"with_for_update\(\)[\s\S]{0,400}?DriverBillType\.SALARY")
    c.present("串行重复核销只落一条收款记录（钱的回归测试）",
              conc_tests, r"def test_double_itemized_receipt_sequential_records_money_once")
    c.present("探针会核对「账单唯一索引真的在库里」（不再是「没有唯一约束」的信息）",
              probe_tool, r"uq_driver_bills_order_type")

    # ---- 26. 司机钱的三方对账与结算语义（v3.39 第五轮：这两处"没问题"要钉住）----
    print("\n== 26. 司机钱：账单 / 绩效待结 / 结算页支出 三方对账 ==")
    money_tests = read(ROOT / "backend/tests/test_driver_money_reconciliation.py")
    c.present("端到端钉住三方对账（规则算的钱，不是运费）",
              money_tests, r"test_司机钱三方对账与结算语义")
    # ⚠️ 这两条语义最容易被人"顺手改成一样"：确认只是锁定明细、钱还没出去；
    #    结算页那个数是"本月支出"，不是"还欠多少"。
    c.present("钉住「确认 ≠ 付钱」（只确认时待结不该变）",
              money_tests, r"只确认没付款时，「待结」不该变")
    c.present("钉住「付款后归零」", money_tests, r"付款之后不该还算欠他")
    c.present("探针里有「司机钱」这一组", probe_tool, r'"司机钱": probe_driver_money')
    c.present("导出与接口同一份聚合（不许导出自己再算一套）",
              read(ROOT / "backend/app/api/v1/reports.py"), r"def build_turnover\(")

    # ---- 27. 输入边界：脏输入只许"被拒"，不许 500 / 不许落库（v3.40 模糊测试那一轮）----
    print("\n== 27. 输入边界：超出数据库能存的范围、月份/坐标/枚举乱填 ==")
    money_schema = read(ROOT / "backend/app/schemas/money.py")
    geo_schema = read(ROOT / "backend/app/schemas/geo.py")
    main_py = read(ROOT / "backend/app/main.py")
    acct_schema = read(ROOT / "backend/app/schemas/accounting_v2.py")
    boundary_tests = read(ROOT / "backend/tests/test_input_boundary_guards.py")
    audit_tool = read(ROOT / "_tools/qa/_audit_money_fields.py")

    c.present("金额入参有统一上限基线（MoneyInput + MONEY_MAX）", money_schema, r"class MoneyInput\(")
    c.present("上限值写在判据里（Numeric(12,2)/(14,4) 能存的最大值）",
              money_schema, r'MONEY_MAX = Decimal\("9999999999\.99"\)')
    # 关键模型必须真的继承它（只定义不继承 = 判据空转）
    for rel, label in (
        ("backend/app/schemas/product.py", "商品单价/成本"),
        ("backend/app/schemas/ledger.py", "账本行金额"),
        ("backend/app/schemas/user.py", "司机工资"),
        ("backend/app/schemas/price_rule.py", "专属价/批量调价"),
        ("backend/app/schemas/accounting_v2.py", "收款/开销/结算金额"),
    ):
        c.present(f"金额上限接在{label}上", read(ROOT / rel), r"\(MoneyInput\)")
    c.present("业务范围（比例≤100%）**不**被平台基线抢走（否则中文 400 变英文 422）",
              money_schema, r'RATE_FIELDS = \("commission_rate",\)')
    c.present("经纬度有范围校验（坐标不是普通数字）", geo_schema, r"class GeoInput\(")
    c.present("地址/订单的 lat/lng 都接上了", read(ROOT / "backend/app/schemas/shipper.py"), r"\(GeoInput\)")
    c.present("月份必须是 YYYY-MM（自由字符串会造出结不掉的幽灵工资单）",
              acct_schema, r"def validate_month\(")
    c.present("生成工资单与建结算单都用同一份月份校验",
              acct_schema, r'@field_validator\("month", mode="before"\)')
    # ⚠️ 必须是 `mode="before"`：写成 after 时 `month=202609`（数字）会先被 Pydantic 拦成
    #    `string_type`（英文结构体），用户看不到"月份要写成 YYYY-MM"那句中文（本轮实测）。
    # ⚠️ 窗口放宽到 700 字符：2026-09-19 审计 R13-D3 在中间加了"月份不能晚于本月"那条上界
    #    （它同样必须在**核心校验之前**跑，否则数字月份会先被 Pydantic 拦成英文 422）。
    c.present("月份校验在核心校验之前跑（数字月份也要看到中文提示）",
              acct_schema, r"def validate_month\(v: str\) -> str:[\s\S]{0,700}?str\(v\)\.strip\(\) if v is not None")
    c.present("月份有上界：不能晚于本月（否则能造出未来月份的应付工资单）",
              acct_schema, r"if s > now_month:")
    c.present("超出数据库范围的整数映射成 400 中文（不是 500）",
              main_py, r"@application\.exception_handler\(OverflowError\)")
    c.present("写库被数据库拒绝（超范围/超长）也映射成 400 中文",
              main_py, r"@application\.exception_handler\(DataError\)")
    c.present("客户 kind 只能是已知枚举（乱填会被静默当成散客）",
              acct_schema, r"kind: CustomerKind = CustomerKind\.TMP")
    c.present("边界测试钉住月份/金额/坐标/枚举四类", boundary_tests, r"def test_money_above_storable_range_rejected")
    c.present("批量调价被拒后「一条专属价都不许变」（效果断言）",
              boundary_tests, r"def test_price_batch_absurd_value_changes_nothing")

    # 审计工具的判据必须**从后端 import**，不许自己再抄一份正则
    c.present("金额字段审计的判据与后端同源（不另抄一份清单）",
              audit_tool, r"from app\.schemas\.money import MONEY_RE, NOT_MONEY, MoneyInput")
    c.present("审计工具本身有「清单是算出来的」断言（模型由 pydantic 枚举）",
              audit_tool, r"BaseModel\.__subclasses__\(\)")

    # ---- fuzz 工具集：安全轨 + 自检 + 反向验证
    fuzz_lib = read(ROOT / "_tools/fuzz/_fuzzlib.py")
    contract_tool = read(ROOT / "_tools/fuzz/_fuzz_contract.py")
    c.present("批量/全量端点**按类**禁止（不是只拉黑出事的那一个）",
              fuzz_lib, r"BULK_PATTERN = re\.compile")
    c.present("白名单判定对「填好数字的路径」生效（模板判不出来）",
              fuzz_lib, r'denied\(m, re\.sub\(r"\\\{\[\^\}\]\+\\\}", "1", path\)\)')
    c.present("工具自检失败要**非零退出**（空转比报错危险）", fuzz_lib, r"def guard\(")
    c.present("契约测试会自检「批量端点已被拦」，而不是假设拦住了",
              contract_tool, r"白名单拦得住\{label\}")
    c.present("契约测试只在**不存在**的 id 上做路径参数（不碰真实数据）",
              contract_tool, r"路径参数一律换成不存在的 id")
    c.present("鉴权测试的判据来自源码 collect()（不是过期的手写表）",
              read(ROOT / "_tools/fuzz/_fuzz_authz.py"), r"def declared_roles\(")
    c.present("不变式审计复用 driver_pay 重算账单（钱只算一处）",
              read(ROOT / "_tools/fuzz/_fuzz_invariants.py"), r"from app\.services\.driver_pay import pay_for_order")
    c.present("重复提交测试比较的是**库里的行数**（效果），不是返回码",
              read(ROOT / "_tools/fuzz/_fuzz_replay.py"), r"def counts\(order_id: int\)")
    c.present("工具安全轨有反向验证（改坏一处必须报红）",
              read(ROOT / "_tools/fuzz/_reverse_verify_fuzz_safety.py"), r"def main\(\)")
    c.present("事故修复脚本留档（含还原依据表）",
              read(ROOT / "_tools/fuzz/_repair_price_rules_batch.py"), r"operation_logs")

    # ---- 28. 账号只能由派单员创建 + 文本入参有上界 + 报错是中文（v3.41 用户要求）----
    #
    # 用户 2026-09-18 三句话：「后端的注册接口关掉因为不需要用了」「文本长度做一个限制」
    # 「把这些查清楚全修好」。这一节把这三件事钉成可检查的判据。
    print("\n== 28. 账号唯一的创建路径 / 文本上限 / 中文报错（v3.41）==")
    auth_api = read(ROOT / "backend/app/api/v1/auth.py")
    auth_svc = read(ROOT / "backend/app/services/auth_service.py")
    users_api = read(ROOT / "backend/app/api/v1/users.py")
    text_schema = read(ROOT / "backend/app/schemas/text.py")
    order_schema = read(ROOT / "backend/app/schemas/order.py")
    shipper_schema = read(ROOT / "backend/app/schemas/shipper.py")
    val_err = read(ROOT / "backend/app/core/validation_errors.py")
    text_audit = read(ROOT / "_tools/qa/_audit_text_fields.py")
    text_tests = read(ROOT / "backend/tests/test_text_length_guards.py")

    # ⚠️ 判据锚**源码里的路由装饰器**（不是注释、也不是"文件里还有没有 register 这个词"：
    #    auth.py 的模块 docstring 里就写着这件事，锚词会恒真）。
    c.absent("自助注册端点不许回来（`POST /auth/register`）",
             strip_comments(auth_api), r'@router\.post\(\s*"/register"')
    c.absent("注册验证码端点不许回来（`POST /auth/sms/send`）",
             strip_comments(auth_api), r'@router\.post\(\s*"/sms')
    c.absent("auth_service 里不许再有自助建号（create_user）",
             strip_comments(auth_svc), r"def create_user\(")
    c.ok("注册验证码的实现文件已删除（不留死代码）",
         not (ROOT / "backend/app/services/sms_code.py").exists(),
         "app/services/sms_code.py 还在")
    c.absent("Auth 相关入参 DTO 里的注册/验证码模型不许回来",
             strip_comments(read(ROOT / "backend/app/schemas/auth.py")),
             r"class (RegisterRequest|SendSmsRequest)\(")
    c.present("建账号只剩一条路：派单员 POST /users（要权限点）",
              users_api, r"require_permission\(Permission\.USER_MANAGE\)")
    c.present("登录仍然可用（关掉的是注册，不是登录）",
              auth_api, r'@router\.post\("/login"')

    # 文本上限：唯一定义处 + 关键字段真的接上了
    c.present("文本上限有唯一定义处（不在十几个 schema 里各写一遍数字）",
              text_schema, r"MAX_URL = 512")
    c.present("多图用同一个 Annotated 类型（条数与单张长度都要有界）",
              text_schema, r"Url = Annotated\[str, StringConstraints\(max_length=MAX_URL\)\]")
    c.present("订单的送货说明接了列宽上限", order_schema, r'delivery_description: str = Field\("", max_length=512\)')
    c.present("订单备注接的是 TEXT 列的**业务**上限", order_schema, r'remark: str = Field\("", max_length=MAX_TEXT\)')
    c.present("送达照片：条数有界", order_schema, r"delivery_photo_urls: list\[Url\] = Field\(default_factory=list, max_length=MAX_IMAGES\)")
    c.present("地址/地点的多图同样有界", shipper_schema, r"image_urls: list\[Url\] = Field\(default_factory=list, max_length=MAX_IMAGES\)")
    c.present("送达收款方式只认现金/挂账两档（乱填不许静默变挂账）",
              order_schema, r'payment: str \| None = Field\(None, pattern="\^\(cash\|arrears\)\$"\)')
    # 审计工具：清单自己算 + 有反空转断言
    c.present("文本上限审计工具存在（判据取自模型列宽）", text_audit, r"def table_columns\(")
    c.present("目标表由字段重合度算出来（不维护手写映射）", text_audit, r"def target_table\(")
    c.present("审计工具有「判据空转」自检（扫不到字段就非零退出）",
              text_audit, r"判据空转：只扫到")
    c.present("列表元素自身的长度也在审（只限条数不够）", text_audit, r"def item_bound\(")

    # 中文报错（422 的 body 换人话，状态码不变）
    c.present("校验失败统一翻成中文（装在 app 上）",
              read(ROOT / "backend/app/main.py"), r"install_validation_errors\(application\)")
    c.present("认不出来的错误类型也有中文兜底（绝不甩英文原文）",
              val_err, r'FALLBACK = "填写的内容不符合要求，请检查后重试"')
    c.present("原始错误数组做了 JSON 清洗（异常对象直接塞会 500）",
              val_err, r"def safe_errors\(")
    c.present("端到端钉住「超长要拒 + 中文 + 不落库 + 边长能过」",
              text_tests, r"def test_超长输入一条都不许落库")
    c.present("端到端钉住「刚好到上限的值必须能过」（反向对照）",
              text_tests, r"def test_边长值被接受")
    c.ok("这条红线配了反向验证（注入 bug 必须变红）",
         (ROOT / "_tools/qa/_reverse_verify_input_guards.py").exists(),
         "缺 _tools/qa/_reverse_verify_input_guards.py")

    # ---- 29. 司机钱的账目完整性：账单唯一 + 结算明细必须在（v3.41 缺陷挖掘第 4 轮）----
    #
    # 库里真出现过一张「已付款、0 条明细」的结算单（352 元），而 API 三条路都堵着
    # ——它是造数工具直接写库造出来的。这一节钉住"以后谁都造不出来"。
    print("\n== 29. 司机钱：账单唯一（数据库级）+ 付款前复核明细（v3.41）==")
    bill_model = read(ROOT / "backend/app/models/driver_bill.py")
    bootstrap = read(ROOT / "backend/app/core/schema_bootstrap.py")
    acct29 = read(ROOT / "backend/app/services/accounting_service.py")
    unique_tests = read(ROOT / "backend/tests/test_driver_bill_unique.py")
    recon_tests = read(ROOT / "backend/tests/test_driver_money_reconciliation.py")
    seed_tool = read(ROOT / "_tools/ai/_seed_test_data.py")

    c.present("同一单同一类型只能有一张账单，是**数据库级**约束",
              bill_model, r'Index\("uq_driver_bills_order_type", "order_id", "bill_type", unique=True\)')
    c.present("旧库启动时会补这个唯一索引",
              bootstrap, r"CREATE UNIQUE INDEX IF NOT EXISTS uq_driver_bills_order_type")
    # ⚠️ 有重复行时**不建索引**：建了会让启动直接崩（这个仓库出过启动崩溃循环），
    #    比脏数据严重得多。判据必须锚在**那个分支的结构**上（`if dups:` + 紧跟着的警告）——
    #    只锚那句中文的话，把 `if dups:` 改成 `if False:`（照建不误）它照样绿（反向验证抓到）。
    c.present("旧库已有重复行时只警告、不建索引（不许让启动崩）",
              bootstrap, r"if dups:\s*\n\s*logger\.warning\([\s\S]{0,300}?暂不创建唯一索引")
    c.present("月薪单（不绑单）不会被这条索引误拦", bill_model, r"NULL 不参与唯一性比较")
    c.present("付款前复核「明细还在不在」", acct29, r"这张结算单已经没有任何明细")
    # 同上：锚"比较 + 紧接着就抛"这个结构，不锚那句中文（否则 `if False:` 照样绿）
    c.present("付款前复核「明细金额对不对得上」",
              acct29, r"if Decimal\(s\.amount\) != live_total:\s*\n\s*raise ValueError\(")
    c.present("端到端钉住「明细被删掉之后不许付款」",
              recon_tests, r"def test_明细被删掉之后不许付款")
    c.present("端到端钉住「正常付款仍然能付」（否则那条可能只是「一律拒绝」）",
              recon_tests, r"正常付款必须写出付款流水")
    c.present("唯一约束有测试（含月薪单不被误拦的反向对照）",
              unique_tests, r"def test_salary_bills_without_order_are_not_blocked")
    c.present("唯一约束的迁移有反向对照（没有重复时索引必须建出来）",
              unique_tests, r"没有重复行时索引没建出来")
    c.present("造数工具不再造无明细的已付结算单",
              seed_tool, r"明细 \+ 结算单 \+ 付款流水三者一致")
    c.present("造数工具自己会自查（造出不自洽的账就直接失败）",
              seed_tool, r"自检失败：本次造的结算单里有")
    c.present("造数清理**不删**别人已结算的单（宁可留下也不毁账）",
              seed_tool, r"保留了别人已结算的 SOTEST 单|留下.*张 SOTEST 单")
    c.present("不变式审计仍盯着「已确认/已付款却无明细」（再出现就报缺陷）",
              read(ROOT / "_tools/fuzz/_fuzz_invariants.py"),
              r"已确认/已付款结算单在库里没有任何关联明细")
    c.present("有处置脚本（只删「没有付款流水」的那种，其余留给人决定）",
              read(ROOT / "_tools/qa/_repair_orphan_settlement.py"),
              r"有付款流水，\*\*不删\*\*")

    print("\n== 30. 选品页分类 / 订单行单位 / 共享地点库（v3.42）==")
    picker = read(UI / "common/ProductPicker.kt")
    ocm = read(UI / "shipper/OrderCreateViewModel.kt")
    ocs = read(UI / "shipper/OrderCreateScreen.kt")
    pick_test = read(ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/shipper/ProductPickerTest.kt")
    place_svc = read(ROOT / "backend/app/services/place_service.py")
    place_api = read(ROOT / "backend/app/api/v1/places.py")
    place_model = read(ROOT / "backend/app/models/place.py")
    place_schema = read(ROOT / "backend/app/schemas/place.py")
    order_model30 = read(ROOT / "backend/app/models/order.py")
    order_flow30 = read(ROOT / "backend/app/services/order_flow.py")
    prod_model = read(ROOT / "backend/app/models/product.py")
    place_test = read(ROOT / "backend/tests/test_place_library.py")
    merge_probe = read(ROOT / "_tools/qa/_probe_place_merge.py")

    # ---- 分类：由商品算出来，不是手写枚举（手写清单必然过期）----
    # ⚠️ 锚在**计数那一句**上，不锚函数签名：只锚 `fun categoryTabs(...)` 的话，
    #    在函数第一行塞一个 `return listOf("全部","饮料")` 它照样绿（反向验证抓到）。
    # ⚠️ 2026-09-19 这个锚点跟着实现搬过一次：库存页也改成"左边分类"之后，判据被拆成
    #    `categoryOf`（商品→档位）与 `categoryNameOf`（名字→档位）两层，
    #    计数那一句从 `products.forEach { p -> ... }` 变成 `names.forEach { n -> ... }`
    #    （原来那一句所在的 `categoryTabs` 现在只是把商品映射成分类名再转交）。
    #    **规则没变**（逐个商品数出来、不是写死的枚举），所以这里跟着改锚点，
    #    而不是把规则放宽 —— 下面那条"只有一份实现"就是防止有人在新位置重写一份。
    c.present("分类清单**逐个商品数出来**（不是写死的枚举，商品管理加一类就多一格）",
              picker, r"names\.forEach \{ n -> counts\[categoryNameOf\(n\)\]")
    c.present("分类清单**只有一份实现**（商品管理/库存/选品三页共用 categoryTabsOf）",
              picker, r"categoryTabsOf\(products\.map \{ it\.category \}, ordered\)")
    c.present("分类栏是**独立滚动**的（换分类不会把右侧商品列表一起带走）",
              picker, r"fun CategoryRail\(")
    c.present("「未分类」只在真有正经分类时才出现（全是未分类时它是纯噪音）",
              picker, r"counts\.containsKey\(NO_CATEGORY\) && out\.size > 1\) out \+= NO_CATEGORY")
    c.present("选品页用的是**调用方给的商品目录**（不是自己再拉一份）",
              picker, r"val cats = remember\(products, categoryOrder\) \{ categoryTabs\(products, categoryOrder\) \}")
    c.present("单测盯着分类顺序（未分类排最后）", pick_test, r"未分类永远排最后")
    c.present("单测盯着「全是未分类时只剩全部」", pick_test, r"全部商品都没分类时只剩全部一个分类")

    # ---- 一次挑多件：同行累加 + 超 10 组整批拒绝 ----
    c.present("「一次挑多件怎么并入清单」是**纯函数**（能被单测直接调）",
              ocm, r"fun mergePickedIntoLines\(existing: List<LineDraft>, picked: List<PickedLine>\)")
    c.present("上限是常量、不是散落的字面量 10", ocm, r"const val MAX_ORDER_LINES = 10")
    c.present("同一件商品重复挑 = 累加数量，不新开一行",
              ocm, r"it\.productId != null && it\.productId == item\.productId")
    # ⚠️ 锚在**结构**上（超限就返回 null），不锚那句中文提示 —— 只锚中文的话
    #    把 `return null` 改成 `return merged` 它照样绿。
    c.present("超过 10 组返回 null（整批拒绝，不做部分成功）",
              ocm, r"return if \(merged\.size > MAX_ORDER_LINES\) null else merged")
    c.present("单测盯着「加满后再挑就整批拒绝」", pick_test, r"加满 10 行后再挑新商品就整批拒绝")
    c.present("单测盯着反向对照（已在清单里的只累加、不被上限挡）",
              pick_test, r"同一件商品即使清单已满也只累加不占新行")

    # ---- 单位：跟着行走，且真的传给了后端 ----
    c.present("订单行有独立的单位快照列", order_model30, r"unit_snapshot: Mapped\[str\]")
    c.present("不传单位时回退**商品库里的单位**（不是默认写死「件」）",
              order_flow30, r"if not unit:\s*\n\s*unit = \(prod\.unit or \"件\"\)\.strip\(\)")
    c.present("拆单时单位跟着拆（漏了子单就变「3 件」而父单是「3 箱」）",
              order_flow30, r"unit_snapshot=\(lp\.unit_snapshot or \"\"\)\[:32\]")
    # 出参名 unit ≠ 列名 unit_snapshot，必须显式 AliasChoices ——
    # 不写它 from_attributes 会**静默落默认值**（unit 恒为空串、不报错）。
    c.present("出参 unit 真的从 unit_snapshot 取（否则静默恒为空串）",
              read(ROOT / "backend/app/schemas/order.py"),
              r'unit: str = Field\("", validation_alias=AliasChoices\("unit", "unit_snapshot"\)\)')
    c.present("下单页把界面选的单位真的发给了后端", ocm,
              r"OrderProductLine\.create\(it\.name\.trim\(\), it\.quantity, it\.price, it\.productId, it\.unit\)")
    c.present("端到端钉住「选了 3 箱订单上就是 3 箱」", place_test,
              r"def test_order_line_unit_is_snapshotted")
    c.present("端到端钉住「不传单位时回退商品库的桶」", place_test,
              r"def test_order_line_unit_falls_back_to_product_unit")
    c.present("商品分类有长度上限（与列宽一致）",
              read(ROOT / "backend/app/schemas/product.py"), r"category: str \| None = Field\(None, max_length=MAX_SHORT_NAME")
    c.present("分类在写入时 strip（否则「饮料」与「饮料  」是左侧两格）",
              read(ROOT / "backend/app/api/v1/products.py"), r"for short_field in \(\"category\", \"unit\"\)")

    # ---- 共享地点库：三种角色都看得到（这是需求本身，不是漏配权限）----
    c.present("共享库接口用的是「仅登录」（三种角色都能查）", place_api, r"current: CurrentUser")
    # ⚠️ 「三种角色都看得到」的**可注入判据是"没有按人过滤"**：
    #    只锚 `current: CurrentUser` 的话，在查询里加一句 `where(created_by == current.id)`
    #    它照样绿 —— 而那句话正好把"相同位置直接拉过来"变成不成立（反向验证抓到）。
    c.absent("共享库列表**不按人分区**（分区了别人的坐标就拉不过来）",
             place_api, r"Place\.created_by == current\.id")
    c.absent("共享库列表不按人分区（也不许用 created_by 当过滤条件）",
             place_api, r"\.where\([^)]*created_by")
    # ⚠️ 2026-09-22 用户定的规则改了这里的口径：「**技术是按人来搞**」——
    #    原来排的是 `places.use_count`（**全库**次数 =「大家都去过这儿」），
    #    现在走全项目共用的那一个排序入口（`services/usage_service.with_popularity`），
    #    读的是**我自己**用过几次（`usage_counters`，kind=place）。
    #    判据是**双向**的：既要有新写法，也不许再回到全库次数（那条仍然是"别人常去"的意思）。
    c.present("列表按「我自己用过多少次」排（常用的排前面）",
              place_api, r"with_popularity\(stmt, Place, usage_service\.KIND_PLACE, current\)")
    c.absent("不许再用全库次数排序（那是「大家都去过」，不是「我常用」）",
             strip_comments(place_api), r"order_by\(Place\.use_count\.desc\(\)")
    c.present("合并判据**只有一处**（1 米常量 + 同名 30 米常量都在服务里）",
              place_svc, r"MERGE_METERS = 1\.0")
    c.present("同名漂移常量也在同一处", place_svc, r"SAME_NAME_METERS = 30\.0")
    # ⚠️ 两条规则必须都真的被用上：只写常量不判等于没合并。
    c.present("两条规则都真的参与判定",
              place_svc, r"if d <= meters or \(d <= SAME_NAME_METERS and _same_place_name\(row\.name, name\)\)")
    c.present("共用一个只增窗口做粗筛（共享库会一直长，不能全表算 haversine）",
              place_svc, r"def _bbox\(")

    # ---- 补导航：只补不改 + 三处写入 + 留痕 ----
    c.present("已有坐标的订单**拒绝**补录（错坐标比没坐标更危险）",
              read(ROOT / "backend/app/api/v1/orders.py"), r"这张订单已经有导航信息了，不需要补录")
    c.present("补导航只允许司机或派单员", read(ROOT / "backend/app/api/v1/orders.py"),
              r"仅司机或派单员可以补导航信息")
    # ⚠️ 锚"**真的会执行**"这个结构（`if order.shipper_id is not None:` 紧跟着赋值调用），
    #    只锚 `place_service.ensure_shipper_location(` 的话，把调用塞进 `if False:` 里
    #    它照样绿 —— 而用户在货主端看到的就是"下次下单没带出坐标"（反向验证抓到）。
    c.present("补录会写进**货主自己的**地点库（且这行真的会执行）",
              read(ROOT / "backend/app/api/v1/orders.py"),
              r"if order\.shipper_id is not None:\s*\n\s*_, shipper_location_created = "
              r"place_service\.ensure_shipper_location\(")
    c.present("补录会往操作日志留痕（单独的动作码）",
              read(ROOT / "backend/app/models/enums.py"), r"ORDER_NAVIGATION_FILL")
    c.present("导航来源落库（货主看到的那句「司机帮你补的」必须是真的）",
              order_model30, r"nav_source: Mapped\[str \| None\]")
    c.present("端到端钉住「补完三处都发生」", place_test,
              r"def test_driver_fills_navigation_for_order_without_coords")
    c.present("端到端钉住反向对照（已有坐标不许覆盖）", place_test,
              r"def test_navigation_cannot_overwrite_existing_coords")
    c.present("端到端钉住「不是这单的司机不能补」", place_test,
              r"def test_navigation_rejects_other_drivers_order")
    c.present("真后端探针覆盖合并的两条规则**两侧**", merge_probe,
              r"异名 \+ 6\.7 米：不许并（否则吃掉隔壁那家）")
    c.present("真后端探针也验「同坐标异名仍并入」（坐标规则优先于名字）", merge_probe,
              r"同坐标（0\.89 米）异名：仍并入")
    # ⚠️ 2026-09-20 起锚的是**新的短文案**：用户要求界面上"最多 7~8 个字"，
    #    那一大段解释搬进了 `HintOnce`（只出现 3 次）。但**规矩没变** ——
    #    用户按下去之前要知道发生什么，所以这句"会写哪三处"必须还在卡片/弹层上。
    c.present("补导航的说明写清「会写哪三处」（用户按下去之前要知道发生什么）",
              read(UI / "order/OrderDetailScreen.kt"), r"存三处：这单 / 货主库 / 共享库")
    # ⚠️ 2026-09-20 这条**换了判据、没放宽**：以前是"AI 不做补导航"，现在是
    #    "AI 可以补，但坐标只能从库里取"。锚两处：参数说明里"不要自己编坐标"，
    #    以及 handler 里坐标来自 `ds.placeById(...)` 那一条（不是从模型参数里取）。
    #    反向验证 `_reverse_verify_place_and_picker.py` 注入的正是后一处
    #    （把 payload 的坐标改成 `AiWriteArgs.str(params, "lat")`）——
    #    只锚"placeById 出现过"是拦不住它的：那句话可以留着、坐标从别处拿。
    c.present("AI 补导航只能引用库里已有的坐标（模型不许编坐标）",
              read(AI / "AiWrite.kt"), r"不要自己编坐标")
    c.present("AI 补导航的坐标来自库里那一条（不是从模型参数里取）",
              read(AI / "AiWriteOrderHandlers.kt"),
              r'put\("address_lat", point\.addressLat\.orEmpty\(\)\)')
    c.present("共享地点库进了 AI 读目录的模块名册（否则生成器报「缺中文名」）",
              read(ROOT / "_tools/ai/_gen_ai_toolmap.py"), r'"places": "共享地点库"')

    # ---- 无主记录护栏（这张表全库共享）----
    # 一条没有名字的记录是**所有人的列表里**都显示成「未命名地点」+ 空地址的记录。
    # 开发库里真出现过（合同模糊测试往 POST /places 打了空名请求）。
    #
    # ⚠️ 判据在 2026-09-19 挪过一次位置：加了"改共享地址"之后，同一句话要用在
    #    **改完之后的整行**上，而 Pydantic 校验器只看得到入参、看不到那一行 ——
    #    于是规则搬到 `services/place_service.identify_error`（唯一一份），schema 反过来引它。
    #    所以这里锚**两件事**：规则本体在服务层、新建入口真的在引它。
    #    只锚其中一处的话，"把校验删掉"或"把两边各写一份"都能溜过去。
    c.present("`POST /places` 拦住「无名无址」的点（规则本体在 place_service）",
              place_svc,
              r'def identify_error\(name: str \| None, detail_address: str \| None\) -> str \| None:')
    c.present("新建/改共享地点都引**同一处**判据（不许各写一份）",
              place_schema, r"err = place_service\.identify_error\(self\.name, self\.detail_address\)")
    c.present("`PATCH /places/{id}` 拒绝把名字与地址都清空（判据看的是改完之后的整行）",
              read(ROOT / "backend/app/services/place_service.py"),
              r"err = identify_error\(new_name, new_detail\)\s*\n\s*if err is not None:\s*\n\s*raise ValueError\(err\)")
    c.present("补导航也拦住「名字与地址都空」（否则一样往共享库塞无名记录）",
              read(ROOT / "backend/app/api/v1/orders.py"), r"if not place_name and not detail:")
    # ⚠️ 锚"strip 之后才判空"这个结构：只锚函数名的话，把 strip 去掉照样绿 ——
    #    而 "   " 在 Python 里是真值，`if not value` 拦不住它（反向验证抓到）。
    c.present("补名字时先 strip 再判空（否则一串空格会被写进库）",
              place_svc, r'text = \(value or ""\)\.strip\(\)\s*\n\s*if not text:\s*\n\s*return False')
    # ⚠️ "已有值不动"也要有一条：并进已有地点时**只补空字段**，
    #    否则后一个请求会把前一个人确认过的名字/地址覆盖掉（而且两条记录看起来都对）。
    c.present("并进已有地点时**只补空字段**，不覆盖别人已确认的信息",
              place_svc,
              r'current = \(getattr\(row, field, ""\) or ""\)\.strip\(\)\s*\n\s*if current:\s*\n\s*return False')
    c.present("清洗顺序是**先 strip 再截断**（反了会存下 128 个空格、把真名字截掉）",
              place_svc, r'return \(value or ""\)\.strip\(\)\[:limit\]')
    c.present("端到端钉住「无名无址的点进不了共享库」（并验二选一都放行）", place_test,
              r"def test_anonymous_place_is_rejected")
    c.present("端到端钉住「纯空格的名字不许写进库」（含反向对照）", place_test,
              r"def test_blank_name_is_not_stored_when_merging")
    # 货主侧也必须能贡献坐标（否则共享库只会从司机那条路长），而且**必须手动一点**：
    # 这张表没有删除接口，自动写 = 探索性选点也会被永久记下来。
    c.present("货主端也能把坐标存进共享库（不是只有司机那条路）",
              ocs, r"vm\.saveCurrentPlaceToSharedLibrary\(\)")
    c.present("存入必须**手动一点**（全库共享且没有删除接口，不许自动写）",
              ocm, r"fun saveCurrentPlaceToSharedLibrary\(\)")
    c.present("存入后如实说明「新建」还是「并入」（否则用户以为多了一条、列表却没变）",
              ocm, r"已并入共享地点库里的")

    print("\n== 31. 商品分类名册 / 商品可见白名单 / 常用地点 / 一次性提示（v3.43）==")
    pcat_api = read(ROOT / "backend/app/api/v1/product_categories.py")
    #: 四个名册（商品/地点/开销/运费）共用的「整份顺序」校验（2026-09-21 从四个端点收成一份）
    cat_order_api = read(ROOT / "backend/app/services/category_order.py")
    pcat_model = read(ROOT / "backend/app/models/product_category.py")
    vis_schema = read(ROOT / "backend/app/schemas/product_visibility.py")
    vis_model = read(ROOT / "backend/app/models/product_visibility.py")
    user_model31 = read(ROOT / "backend/app/models/user.py")
    products_api31 = read(ROOT / "backend/app/api/v1/products.py")
    orders_api31 = read(ROOT / "backend/app/api/v1/orders.py")
    users_api31 = read(ROOT / "backend/app/api/v1/users.py")
    psvc31 = read(ROOT / "backend/app/services/place_service.py")
    places_api31 = read(ROOT / "backend/app/api/v1/places.py")
    boot31 = read(ROOT / "backend/app/core/schema_bootstrap.py")
    picker31 = read(UI / "common/ProductPicker.kt")
    cat_screen = read(UI / "dispatcher/ProductCategoriesScreen.kt")
    cat_vm = read(UI / "dispatcher/ProductCategoriesViewModel.kt")
    # 2026-09-21 第二轮：草稿状态机收进了共用内核（三个名册页共用），
    # 所以「本地草稿」这条判据的锚点跟着实现搬到这里（而不是留在商品页那个已经变薄的文件里）。
    cat_vm_base = read(UI / "common/CategoryRosterViewModel.kt")
    comp31 = read(UI / "common/Components.kt")
    addr_screen = read(UI / "shipper/AddressScreen.kt")
    ocs31 = read(UI / "shipper/OrderCreateScreen.kt")
    ocm31 = read(UI / "shipper/OrderCreateViewModel.kt")
    um_vm = read(UI / "dispatcher/UsersManageViewModel.kt")
    pcat_test = read(ROOT / "backend/tests/test_product_catalog.py")

    # ---- ① 商品分类名册：顺序由人定，且改名必须级联 ----
    c.present("分类名册有独立的顺序列（顺序不再靠商品数推）",
              pcat_model, r"sort_order: Mapped\[int\] = mapped_column\(Integer")
    c.present("名册接口按 sort_order 排序", pcat_api,
              r"order_by\(ProductCategory\.sort_order, ProductCategory\.id\)")
    # ⚠️ 锚"改名时真的去 UPDATE products"这个结构：只锚函数名的话，
    #    把那条 update 删掉照样绿 —— 而后果是"改完名商品全变成未分类，而且不报错"。
    c.present("改名**级联**改掉挂在它下面的商品（同一事务）",
              pcat_api, r"Product\.__table__\.update\(\)\.where\(Product\.category == old_name\)")
    # ⚠️ 锚"数完之后**真的抛**"这个结构，不锚那句中文：只锚中文的话，
    #    把 `if used:` 改成 `if False:`（照删不误）它照样绿（反向验证抓到）。
    c.present("删除前先数「还有几个商品挂着」，有就**拒绝**（拒绝时把数字说给用户）",
              pcat_api,
              r"if used:\s*\n\s*raise HTTPException\(\s*\n\s*status_code=400")
    # ⚠️ 锚"少了就拒绝"这个结构：不锚的话，reorder 可以只传一部分、
    #    没提到的那些静默保持原序 —— 两端各错一次而且看不出来。
    # 2026-09-21：这段校验原来是四个名册端点各抄一遍，已收成 `services/category_order.py` 一份，
    #    所以锚点分两处：①端点**真的调用**了那份共用校验（自己再拼一遍 ids 就红）；
    #    ②判据本体（少了就拒绝并点名）在那份共用文件里。
    c.present("reorder 要求**整份**顺序（商品分类端点调用共用校验，不自己再抄一遍）",
              pcat_api, r"ids = ordered_ids\(by_id, body\.ids\)")
    c.present("「整份顺序」的判据只有一份（少了就拒绝并点名）",
              cat_order_api, r"if missing:\s*\n\s*names = ")
    c.present("新建商品时名册里没有的分类名**自动补进去**",
              products_api31, r"ensure_category\(db, body\.category or \"\"\)")
    # ⚠️ 锚"真的把名册顺序拼进去了"那一句：只锚函数签名的话，把消费 `ordered` 的那行删掉
    #    （顺序退回按商品数推）它照样绿（反向验证抓到）。
    c.present("选品页分类顺序**来自名册**（真的把名册顺序拼进去了，不是只留个参数）",
              picker31,
              r"ordered\.map \{ it\.trim\(\) \}\.filter \{ it\.isNotEmpty\(\) && it in inRail \}"
              r"\.distinct\(\)\.forEach \{ out \+= it \}")
    # ⚠️ 名册外的分类**必须保留**：藏起来的话，"名册管理"就变成了一个静默的商品过滤器。
    c.present("名册外的分类名仍然出现（不许因为不在名册里就把商品藏起来）",
              picker31, r"filter \{ it\.key != NO_CATEGORY && it\.key !in out \}")
    c.present("下单页把名册顺序传给了选品页", ocs31, r"categoryOrder = vm\.categoryOrder")
    c.present("派单端能新建分类", cat_screen, r"onClick = \{ vm\.openCreate\(\) \}")
    c.present("排序是**本地草稿**、点「保存顺序」才提交（不每点一次发一次请求）",
              cat_vm_base, r"dirty = orderChanged\(categories, savedOrder, ::idOf\)")
    c.present("分类管理的失败提示走一次性提示条（不重放）",
              cat_screen, r"OneShotSnackbar\(snackbar, vm\.notice, onConsumed = \{ vm\.notice = null \}\)")

    # ---- ② 商品可见白名单 ----
    c.present("可见范围开关在 users 上，默认 all",
              user_model31, r'product_scope: Mapped\[str\] = mapped_column\(String\(16\), default="all"\)')
    # ⚠️ 迁移必须回填 all：回填成 custom 的话，上线那一刻所有老货主的选品页会当场变空。
    c.present("旧库补列时**回填 all**（白名单默认关闭）", boot31,
              r"ADD COLUMN product_scope VARCHAR\(16\) NOT NULL DEFAULT 'all'")
    c.present("白名单明细表存在且有唯一约束", vis_model,
              r'UniqueConstraint\("user_id", "product_id", name="uq_user_product_visibility"\)')
    c.present("可见判据**只有一处**（列表/详情/下单校验都调它）",
              vis_schema, r"def visible_product_ids\(db: Session, user: User \| None\) -> set\[int\] \| None:")
    # ⚠️ 锚**返回 None 的那两行**，不锚文档里那句解释：解释永远在，改成 `return set()`
    #    也不会动它 —— 而那正是"默认把所有人挡在外面"的事故写法（反向验证抓到）。
    c.present("不受限用 None 表示（不是空集合）—— 两者语义绝不相同",
              vis_schema,
              r"if not visibility_applies_to\(user\):\s*\n\s*return None[\s\S]{0,240}?"
              r"!= SCOPE_CUSTOM:\s*\n\s*return None")
    c.present("可见性只对货主生效（派单员不受限，否则改错了没人能改回来）",
              vis_schema, r"return role_key\.lower\(\) == UserRole\.SHIPPER\.value")
    c.present("商品列表按白名单过滤", products_api31,
              r"ids = visible_product_ids\(db, current\)\s*\n\s*if ids is not None:")
    c.present("白名单外的商品详情**按不存在回**（403 等于告诉他有个看不到的商品）",
              products_api31,
              r"if not product_visible_to\(db, current, p\.id\):\s*\n\s*raise HTTPException\(status_code=404")
    # ⚠️ 只在选品页藏起来不够：接口照收 = 看起来限制了、其实没有。
    c.present("下单时也校验（否则藏起来的商品照样能塞进单里）", orders_api31,
              r"if not product_visible_to\(db, current, ln\.product_id\)")
    # ⚠️ 这两条锚"**真的抛 / 真的写日志**"这个结构，不锚那句中文/那行 action=
    #    （把整块塞进 `if False:` 之后，中文和 action= 都还在文件里，照样绿 —— 反向验证抓到）
    c.present("`custom` 但一个都没勾 → **拒绝**（那等于让他什么都看不到）", users_api31,
              r"if not body\.product_ids:\s*\n\s*raise HTTPException\(\s*\n\s*status_code=400")
    c.present("可见范围只给货主/批发商设（对派单员设没有意义）", users_api31,
              r"商品可见范围只对货主/批发商有意义")
    c.present("改动留痕（本质是授权）", users_api31,
              r"write_log\(\s*\n\s*db,\s*\n\s*operator_id=current\.id,\s*\n\s*order_id=None,\s*\n"
              r"\s*action=OperationAction\.PRODUCT_VISIBILITY_SET")
    c.present("端到端钉住白名单（含「别的货主不受影响」的反向对照）", pcat_test,
              r"def test_visibility_whitelist_hides_other_products")
    c.present("端到端钉住「默认不限制」", pcat_test, r"def test_visibility_defaults_to_all")
    c.present("端到端钉住「custom 但空 → 拒绝」", pcat_test,
              r"def test_custom_scope_without_products_is_rejected")
    c.present("端到端钉住「下单时也拦隐藏商品」", pcat_test, r"def test_order_rejects_hidden_product")

    # ---- ③ 常用共享地点自动进「我的地点」 ----
    c.present("阈值常量只有一处", psvc31, r"AUTO_ADD_AFTER = 2")
    # ⚠️ 按 (user, place) 计数，不是用 places.use_count（那是"大家都去过这儿"）
    c.present("按**人 + 地点**计数（不是全库次数）", psvc31,
              r"PlaceUserUsage\.user_id == user\.id, PlaceUserUsage\.place_id == place\.id")
    c.present("只自动加一次（auto_added 只置一次）", psvc31,
              r"if row\.auto_added or row\.use_count < AUTO_ADD_AFTER:")
    c.present("只给有自己地点库的角色加（司机没有这个概念）", psvc31,
              r'if role_key not in \("shipper", "dispatcher"\):')
    c.present("自动加进用户自己的库要**留痕**（否则他只能猜是谁加的）", places_api31,
              r"action=OperationAction\.PLACE_AUTO_ADDED")
    c.present("App 选中共享地点时会记一次用量", ocm31, r"container\.repo\.usePlace\(p\.id\)")
    c.present("跨过阈值那次要对用户**说一句**（不许静默改他自己的库）", ocm31, r"已加进你的「我的地点」")
    c.present("端到端钉住「第 2 次才自动进库」", pcat_test, r"def test_second_use_auto_adds_shared_place")

    # ---- ④ 只要是选地点的地方都能搜 ----
    c.present("下单页地址弹层：三段都有搜索框（不是只有共享地点那段）",
              ocs31, r'sel == "a" -> "搜收货人、电话或地址"')
    c.present("地址与联系人页也有搜索框（线路/联系人/地点三段共用）",
              addr_screen, r'0 -> "搜线路：收货人 / 电话 / 地址"')
    c.present("本地过滤 + 共享地点段同时打后端（全库那部分本地没有）",
              ocs31, r"if \(sel == \"p\"\) onSearchPlaces\(it\.ifBlank \{ null \}\)")
    # ⚠️ 2026-09-20 补：上面那两条只钉了"有搜索框"和"共享地点段打后端"，
    #    **本地那两段有没有真的过滤**一直没人管 —— 反向验证
    #    `_reverse_verify_catalog_and_scope.py` 把它照出来了（把过滤改成原样返回，
    #    三条判据全绿）：于是用户搜"老王仓库"搜不到（而它就在「我的地点」里），
    #    很自然地读成"没有这个地点"→ 再建一条重复的。
    c.present("下单页地址库：本地两段（线路 / 我的地点）真的按关键词过滤",
              ocs31,
              r"val shownAddresses = remember\(addresses, kw\) \{\s*\n\s*if \(kw\.isBlank\(\)\) addresses\s*\n\s*else addresses\.filter \{")
    c.present("下单页地址库：我的地点段也按关键词过滤（含分类段）",
              ocs31,
              r"val shownLocations = remember\(locations, sel, kw\) \{")

    # ---- ⑤ 一次性提示：先消费、再显示 ----
    c.present("一次性提示只有一处实现（OneShotSnackbar）", comp31, r"fun OneShotSnackbar\(")
    # ⚠️ 这条红线的要点是**两件事同时成立**（2026-09-21 补第二件）：
    #    ① **先消费**（`onConsumed()` 在显示之前）—— 顺序反了，切页时协程被取消、
    #       那一行"置空"永远不执行，用户切回来提示条**又冒一次**（用户 2026-09-18 报的 bug）；
    #    ② **显示不能挂在会随 key 取消的作用域上** —— 这是①的**代价**，也是真机逐帧拍出来的：
    #       `message` 正是 `LaunchedEffect(message)` 的 key，`onConsumed()` 把它置空 → key 变 →
    #       协程被取消 → 紧接着那句 `showSnackbar` 没跑，**提示条全 App 都不显示**（47 处调用）。
    #       所以显示必须放进 `scope.launch { … }`（`rememberCoroutineScope()` 的生命周期是
    #       Composable 本身，不随 key 变化取消）。
    #    ⛔ 只断言①会把代码按回"不显示"，只断言②会把代码按回"会重放" —— 两个旧 bug 是一对。
    c.present(
        "**先消费**（顺序反了切页就会重放）",
        comp31,
        r"LaunchedEffect\(message\)\s*\{[\s\S]{0,400}?onConsumed\(\)[\s\S]{0,200}?showSnackbar",
    )
    c.present(
        "**显示不随 key 取消**（不然提示条根本不显示）",
        comp31,
        r"rememberCoroutineScope\(\)[\s\S]{0,400}?scope\.launch\s*\{\s*hostState\.showSnackbar",
    )
    ui_files = sorted((UI).rglob("*.kt"))
    risky = [
        f.name
        for f in ui_files
        if re.search(r"showSnackbar\([^)]*\)\s*\n\s*[A-Za-z0-9_.]+\s*=\s*null", read(f))
    ]
    c.ok(
        "全库没有「先 showSnackbar 再清状态」的写法（那会在切页返回时重放）"
        + (f"——还有：{risky}" if risky else ""),
        not risky,
    )
    c.ok(
        f"一次性提示的调用点 {sum(1 for f in ui_files if 'OneShotSnackbar(' in read(f))} 个（清单可能过期，应 ≥18）",
        sum(1 for f in ui_files if "OneShotSnackbar(" in read(f)) >= 18,
    )
    c.present("消息页（用户报的那一处）用的是 OneShotSnackbar",
              read(UI / "messages/MessagesScreen.kt"),
              r"OneShotSnackbar\(snackbar, vm\.notice, onConsumed = \{ vm\.notice = null \}\)")
    # 两个页面把"加载错误"和"动作错误"拆成了两个字段（否则提示条会把整页 ErrorView 清掉）
    # ⚠️ 2026-09-19：这个文件原来叫 `WholesalePricingViewModel.kt`，本轮定价页泛化成
    #    「价格矩阵」（按批发商 / 按商品两个方向）后改名 `PriceMatrixViewModel.kt`。
    #    路径写死在这里正是为了"文件被改名时这条判据要报红"—— 它确实报了（红在"找不到文件"）。
    c.present("加载错误与动作错误**分开**（否则提示条一消费，整页 ErrorView 就没了）",
              read(UI / "dispatcher/PriceMatrixViewModel.kt"),
              r"var loadError by mutableStateOf<String\?>\(null\)")
    c.present("账本管理页同样拆开了",
              read(UI / "dispatcher/DispatcherLedgerViewModel.kt"),
              r"var loadError by mutableStateOf<String\?>\(null\)")

    # ================================================================ 32. 批量捷径
    print("\n== 32. 批量捷径：一次改多条（一张卡、确认一次、逐条如实汇报）（v3.46）==")
    batch_src = read(AI / "AiWriteBatch.kt")
    svc32 = read(AI / "AiWriteService.kt")
    w32 = read(AI / "AiWrite.kt")
    tools32 = read(AI / "AiTools.kt")
    loop32 = read(AI / "AiAgentLoop.kt")

    # ---- ① 它是「装饰器」，不是一个另起的执行器（用户 2026-09-21 的插件式准则）----
    c.present("批量层实现的是**同一个接口**（既有处理器一行都不用改）",
              batch_src, r"class BatchWriteHandler\([\s\S]{0,300}?\) : AiWriteHandler")
    c.present("接线只有一处：建表之后统一套一层", svc32, r"rawHandlers\.mapValues \{ \(id, h\) ->")
    c.present("套的就是它", svc32, r"BatchWriteHandler\(a, h, store\)")
    dup32 = [
        p.name
        for p in sorted(AI.glob("AiWrite*.kt"))
        # ⚠️ 只看**代码**（注释里提一句"参数名见批量层"是好事，不该被这条判据当成第二处实现）
        if p.name != "AiWriteBatch.kt" and "BATCH_ITEMS" in strip_comments(read(p))
    ]
    c.ok("批量参数名只在批量层里出现（不是每个处理器各认一遍）", not dup32, f"还有：{dup32}")

    # ---- ② 批量**永远要确认** ----
    # 自动执行档的处理器在 `prepare` 里就已经写库了（消息全标已读），放进批量＝预览阶段就写库
    c.present("自动执行档在**调用内层之前**就被挡掉",
              batch_src,
              r"if \(action\.risk == AiWriteRisk\.AUTO_EXECUTABLE\) \{[\s\S]{0,300}?throw AiWriteArgException")
    auto_pos = strip_comments(batch_src).find("AUTO_EXECUTABLE")
    first_inner = strip_comments(batch_src).find("inner.prepare(item)")
    c.ok(
        "挡的位置在**第一次调用内层之前**（顺序错了这条判据就没意义）",
        0 <= auto_pos < first_inner,
        f"档位判断在 {auto_pos}、第一次调内层在 {first_inner}",
    )
    c.present("批量的卡照动作本身的档位（不偷偷降档）", batch_src, r"risk = action\.risk,")

    # ---- ③ 参数与条数 ----
    c.present("`items` 不是数组 → 拒绝", batch_src, r"`items` 要是一个数组")
    c.present("空数组 → 拒绝", batch_src, r"`items` 是空的")
    # ⛔ 用户 2026-09-21 拍板：「批量是没有上限的，批量是根据用户的范围来定的，他自己去定范围」
    c.absent("**不设条数上限**（范围由用户自己定）",
             batch_src, r"items\.size\s*>\s*[A-Za-z_]*MAX|MAX_BATCH_ITEMS")
    c.present("摘要要写清**真实条数**", batch_src, r'summary = "批量\$\{action\.title\}：\$\{rows\.size\} 条"')

    # ---- ④ 任何一条不合法 → 整批不发，并且指出第几条 ----
    # 处理器按契约是**抛**的，批量层必须自己接住（否则用户不知道那是 20 条里的哪一条）
    c.present("处理器抛的错补上「第几条」",
              batch_src, r'throw AiWriteArgException\("第 \$\{i \+ 1\} 条：\$\{e\.message')
    c.present("处理器返回 Rejected 的也补上",
              batch_src, r'throw AiWriteArgException\("第 \$\{i \+ 1\} 条：\$\{out\.reason\}')

    # ---- ⑤ 逐条执行、逐条汇报（都不许被"已完成"盖住）----
    c.present("逐条执行，且每条一个幂等键", batch_src, r'inner\.commit\(item, "\$idempotencyKey-\$i"\)')
    # ⚠️ 单条那条路也得把内层那句 `commitNote` 带出去：它是"按表格调价"报「10 行成功、2 行失败」
    #    用的机制，装饰器不转发就等于把失败行又盖住了（两条既有单测当场抓到过这个漏转发）。
    c.present("单条那条路转发内层的 commitNote（不许把失败行盖住）",
              batch_src, r"note = inner\.commitNote\(\)")
    c.present("失败的那几条要逐条记下来", batch_src, r'failed \+= "#\$\{i \+ 1\} " \+ brief\(e\)')
    c.present("结果交给服务层拼进最终答复",
              batch_src, r"override fun commitNote\(\): String\? = note\.also \{ note = null \}")
    c.present("成功/失败条数都要说", batch_src, r"这一批 \$\{items\.size\} 条：成功 \$ok 条")
    # ⚠️ 判据要**分别锚在两段代码里**：只写一句正则在整份文件里搜"取消原样抛"，
    #    另一段里那一句就会满足它（反向验证实测：把 `commit` 里那段删掉，判据照样绿）。
    prep_blk = block_between(batch_src, "override suspend fun prepare(", "override suspend fun commit(")
    commit_blk = block_between(batch_src, "override suspend fun commit(", "override fun commitNote(")
    for where, blk in (("预览", prep_blk), ("执行", commit_blk)):
        c.present(f"{where}里取消原样抛（不当成「失败」吞掉）",
                  blk, r"catch \(e: CancellationException\) \{\s*\n\s*throw e")
    user_note = strip_comments(block_between(batch_src, "note = buildString {", "override fun commitNote"))
    c.ok("逐条汇报是**给用户看的**（不许带 Markdown 星号）", bool(user_note.strip()) and "**" not in user_note)

    # ---- ⑥ 卡片不许说假话：批量不挂撤回 ----
    c.present("批量卡最后一行走批量专属那句", w32, r"batch -> AiWrites\.BATCH_UNDO_NOTE")
    c.present("那句定义在动作表里（唯一一处）", w32, r"const val BATCH_UNDO_NOTE: String =")
    m32 = re.search(r'const val BATCH_UNDO_NOTE: String =\s*\n?\s*"([^"]+)"', w32)
    c.ok("那句是给用户看的（不许带 Markdown 星号）", bool(m32) and "**" not in m32.group(1),
         f"实际：{m32.group(1)[:40] if m32 else '没找到'}")
    c.present("批量卡最后一行**不是**单条那句「会出现撤回」",
              w32, r"batch -> AiWrites\.BATCH_UNDO_NOTE\s*\n\s*isUndo ->")
    rows_fn = strip_comments(block_between(batch_src, "private fun detailLines(", "private fun brief("))
    c.ok("卡片明细是**给用户看的**（不许带 Markdown 星号）", bool(rows_fn.strip()) and "**" not in rows_fn)

    # ---- ⑦ 一张卡列全部行（用户选的形态）----
    c.present("条数不多时逐条一个小节", batch_src, r'"———— 第 \$\{i \+ 1\} 条 ————"')
    c.present("条数多时每条压成一行（**不是**只列前 N 条）",
              batch_src, r'rows\.mapIndexed \{ i, r -> "\$\{i \+ 1\}\. "')
    c.present("压缩模式也要写清总条数", batch_src, r"共 \$\{rows\.size\} 条")
    c.present("明细行用的是没被追加过的那份（不然「撤不回来」会被复制 N 遍）",
              batch_src, r"r\.bodyLines")

    # ---- ⑧ 不许偷走用户手里的卡；批量标记与退货明细不同名 ----
    c.present("只取**这一次新登记**的卡（去重命中的那张是用户的）", batch_src, r"it\.token !in known")
    c.present("批量标记是保留字（不是 `items`）", batch_src, r'const val BATCH_PAYLOAD = "_batch"')
    c.present("执行侧认的是批量标记", batch_src, r"payload\[BatchWriteHandler\.BATCH_PAYLOAD\] is JsonArray")
    params32 = "".join(read(p) for p in sorted(AI.glob("AiWrite*.kt")))
    c.absent("没有任何写动作声明名为 `items` 的参数（那个名字归批量层）",
             params32, r'AiWriteParam\(\s*"items"|param\s*=\s*"items"')

    # ---- ⑨ 服务层那两处（批量不挂撤回、也不报"没挂上"）----
    c.present("execute 认出批量 payload", svc32, r"val batched = isBatchPayload\(p\.payload\)")
    c.present("批量不建撤回方案（`AiRevert.plan` 只认单条 payload）", svc32, r"val undo = if \(batched\) \{")
    c.present("批量也不报「没能挂上撤回」", svc32, r"val broken = !batched &&")

    # ---- ⑩ 模型得知道有这条路（不知道就等于没做）----
    c.present("参数说明里教了 `items`", tools32, r"一次改多条（批量捷径）")
    c.present("提示词里有一条「一次提交，不要一条条调」",
              loop32, r"一次要改/要建好几条时，用「批量」一次提交")
    c.present("提示词里也写明「范围由用户定、没有条数上限」", loop32, r"没有条数上限")

    # ================================================================ 33. 测试账号默认模型服务
    print("\n== 33. 测试账号的默认模型服务：key 只在服务端、三道门、用户自己配过就永远用自己的（v3.47）==")
    sys_src = read(ROOT / "backend/app/api/v1/system.py")
    cfg_src = read(ROOT / "backend/app/config.py")
    router_src = read(ROOT / "backend/app/api/v1/router.py")
    cont_src = read(AI / "AiContainer.kt")
    ks_src = read(AI / "AiKeyStore.kt")
    set_screen = read(UIAI / "AiSettingsScreen.kt")

    # ---- ① key 的来源：只许来自服务端配置 ----
    c.present("默认 key 由**配置**提供（`ai_default_api_key`），不是写死在代码里",
              sys_src, r"settings\.ai_default_api_key")
    # ⛔ 这个文件里**不许出现任何 key 字面量**，也不许把它拼出来。
    #    三种形状一起拦：`"sk-…"`、`"sk-" + "…"`、以及任何 24 位以上的字母数字长串。
    #    （外面还有 `_check_secrets.py` 扫全仓的凭据形状 —— 那一条已经因为本文件里的
    #      假 key 报过一次红，所以反向验证的注入改成"拼出来的 32 位串"：两道判据各管一段，
    #      谁也不去踩另一条红线。）
    c.absent("那个文件里没有任何 key 字面量（也不许拼出来）",
             sys_src, r'"sk-|\'sk-|"[A-Za-z0-9]{24,}"')
    for field in ("ai_default_api_key", "ai_default_base_url", "ai_default_model", "ai_test_phone_prefix"):
        c.present(f"`config.py` 里有 `{field}`", cfg_src, rf"{field}: str = ")

    # ---- ② 三道门 ----
    c.present("端点要求**登录**（CurrentUser）", sys_src, r"def read_ai_default\(current: CurrentUser\)")
    c.present("新模块挂上了路由（没挂 = 404）", router_src, r"api_router\.include_router\(system\.router\)")
    c.present("**白名单**前缀匹配，且留空 = 这个能力整体关闭",
              sys_src, r"if not prefix or not phone\.startswith\(prefix\):")
    c.present("非白名单 → 403（如实说「不是测试账号」）", sys_src, r"status_code=403")
    c.present("服务端没配 key → **404**（不许返回空串让客户端去猜）", sys_src, r"status_code=404")

    # ---- ③ 客户端：只在用户自己没配过 key 时才用 ----
    c.present("用户已配过 key → 直接返回，绝不用默认的",
              cont_src, r"if \(keyStore\.hasKey\(\)\) return false")
    c.present("拿不到就**静默**当没有（403/404/断网都不是「错误」）",
              cont_src, r"return false // 403/404/断网都走这里")
    # `saveApiKey` 会清掉那个标记 → 自动写入那条路必须在**它之后**再置 true（顺序反了就白写）
    save_pos = cont_src.find("keyStore.saveApiKey(key)")
    mark_call = cont_src.find("keyStore.markUsingDefaultKey(true)")
    c.ok("先 `saveApiKey` 再 `markUsingDefaultKey(true)`（顺序反了标记会立刻被清掉）",
         0 <= save_pos < mark_call, f"saveApiKey@{save_pos} mark@{mark_call}")
    c.present("用户自己保存 key 时清掉「来自服务端」这个标记",
              ks_src, r"markUsingDefaultKey\(false\)")
    c.present("界面如实说明这把 key 是哪来的",
              set_screen, r"正在使用「测试账号默认 Key」")
    # 与 §2e 同一条纪律：设置页是普通 Text()，写 Markdown 星号会原样显示
    no_md("设置页那句说明没有 Markdown 记号", set_screen)

    # ---- ④ 每个 DTO 都必须 @Serializable（2026-09-21 真机实测踩到的）----
    # 漏了它：kotlinx.serialization 在**发请求之前**就失败（converter 找不到序列化器），
    # 于是 HTTP 请求根本没发出去 —— 而调用点在 `catch (_: Exception)` 里当"拿不到"吞掉，
    # 表现是"功能全对、就是不生效"，日志里一个字都没有（本轮就是这么被真机 E2E 抓到的）。
    dto_src = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt")
    dto_lines = dto_src.splitlines()
    no_ann = [
        dto_lines[i].strip()[:50]
        for i in range(1, len(dto_lines))
        if dto_lines[i].lstrip().startswith("data class ") and dto_lines[i - 1].strip() != "@Serializable"
    ]
    # 例外只有"手工解析、不经 kotlinx.serialization"的那几个（键必须还在——防化石）
    ALLOW_NO_ANN = {"data class SocketEvent(": "Socket 事件是手工解析的，不走 kotlinx.serialization"}
    unexpected = [x for x in no_ann if x not in ALLOW_NO_ANN]
    c.ok(f"Dtos.kt 里每个 data class 都有 @Serializable（漏了它 = 请求根本不发出去，且静默）"
         f"—— {len(dto_lines)} 行里只有 {len(no_ann)} 个例外",
         not unexpected, f"缺注解：{unexpected[:3]}")
    for k in ALLOW_NO_ANN:
        c.ok(f"例外仍在（{k.strip()[:30]}…）", k in no_ann, "那条已经加了注解 → 该把它从例外里删掉")

    # ---- 34. AI 的报价必须绑「这个货主的价」（2026-09-22 查出来的真缺陷）----
    #
    # 用户定的规则只有一条：「只要是商品的价格都跟他货主配置的价格进行绑定……没有绑定就走默认的价格。」
    # 而后端**不重算价**（`order_products.py` 直接收 `body.unit_price`），所以绑价全是客户端责任。
    # 界面那一半在 569a23d 修过（`OrderCreateViewModel.priceFor`），**AI 这一半一直没人管**：
    # 建单/账本逼着模型自己编一个价、加行直接取"商品库默认价"（连这单的货主都不看）——
    # 后果就是用户上次报的那个 bug：批发商谈好 10 元，AI 建出来的单按 20 元。
    print("\n== 34. AI 报价必须绑「这个货主的价」：建单 / 加行 / 账本记一笔（v3.48）==")
    price_kt = strip_comments(read(AI / "AiEffectivePrice.kt"))
    wline = strip_comments(read(AI / "AiWriteOrderLineHandlers.kt"))
    worder_c = strip_comments(worder)
    wbasic_c = strip_comments(wbasic)
    wsvc_c = strip_comments(wsvc)
    wr_c = strip_comments(wr)

    # ① 口径只有一处：专属价优先、否则商品默认价
    c.present("报价口径只有一处（AiPriceBasis）", price_kt, r"internal class AiPriceBasis")
    c.present(
        "生效价＝**这个货主的专属价**优先",
        price_kt,
        r"special\[shipperId to productId\]\?\.let \{ return Price\(it, fromSpecial = true\) \}",
    )
    c.present(
        "没有专属价才退回商品默认价",
        price_kt,
        r"return defaults\[productId\]\?\.let \{ Price\(it, fromSpecial = false\) \}",
    )
    c.present(
        "价读不出来算「不知道价」而不是 0（0 会被当成「这件货不要钱」）",
        price_kt,
        r"raw\.trim\(\)\.takeIf \{ it\.isNotEmpty\(\) \}",
    )

    # ② 三条路都真的接上了（口径存在但没人用 = 白写）
    c.present(
        "建单按**这个货主**的价补（代理下单＝他；货主自下单＝他自己）",
        worder_c,
        r"parseLines\(params, shipperId = if \(selfOrder\) ds\.currentUserId\(\) else shipper\?\.id\)",
    )
    c.present(
        "建单的 unit_price 变成可选（不再逼模型自己编一个价）",
        worder_c,
        r"val typedRaw = AiWriteArgs\.str\(obj, \"unit_price\"\)",
    )
    c.present("建单没给价就用生效价", worder_c, r"system != null -> system\.value")
    c.present("加行按**这个订单货主**的价补", wline, r"basis\.of\(order\.shipperId, it\)")
    c.absent(
        "加行不再拿「商品库默认价」当兜底（就是这次修掉的那个缺陷）",
        wline,
        r"known\.defaultPrice",
    )
    c.present("账本记一笔也绑货主", wbasic_c, r"basis\.of\(shipper\?\.id, it\)")
    c.ok(
        "三条路都真的 load 了这个口径（少一条 = 那条路又回去自己算价）",
        worder_c.count("AiPriceBasis.load(") + wline.count("AiPriceBasis.load(")
        + wbasic_c.count("AiPriceBasis.load(") >= 3,
        f"建单={worder_c.count('AiPriceBasis.load(')} 加行={wline.count('AiPriceBasis.load(')} "
        f"账本={wbasic_c.count('AiPriceBasis.load(')}",
    )

    # ③ 给了价但与系统价不一致：卡片必须把两个数都摆出来（**只提示不拦**：
    #    派单员当场改价是真实业务；但模型也可能只是没查专属价就照着默认价填了一个数）
    c.present(
        "不一致的提示口径只有一处（mismatchNote）",
        price_kt,
        r"fun mismatchNote\(typed: BigDecimal, system: Price\?\): String\?",
    )
    c.ok(
        "三个消费点都接了它（少一个 = 那条路上用户看不出来价不对）",
        worder_c.count(".mismatchNote(") >= 1 and wline.count(".mismatchNote(") >= 1
        and wbasic_c.count(".mismatchNote(") >= 1,
        f"建单={worder_c.count('.mismatchNote(')} 加行={wline.count('.mismatchNote(')} "
        f"账本={wbasic_c.count('.mismatchNote(')}",
    )
    c.present(
        "提示里写着「先跟用户核对按哪个」（模型据此回去问一句，而不是默默按自己填的数建单）",
        price_kt,
        r"先跟用户核对按哪个",
    )
    c.ok(
        "提示**两行以内**（明细区上限 200dp，第一版 3 行时真机上被裁掉半行）",
        "note.length <= 52" in read(
            ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiPriceBasisTest.kt"
        ),
        "单测里那条长度预算不见了 —— 文案一长又会被裁，而界面上只表现为「卡片坏了」",
    )
    c.present(
        "工具说明书写明「用户没报过价就别自己填」",
        wr_c,
        r"用户没报过价就别自己填",
    )

    # ④ 「我是谁」与「这单是谁的」—— 报价绑货主的两块地基
    c.present(
        "数据源能回答「我是谁」（货主自下单要按他自己那份专属价，界面同源口径 subject=…）",
        wsvc_c,
        r"suspend fun currentUserId\(\): Long\?",
    )
    c.present("卡片视图带上了这单的货主编号", wr_c, r"val shipperId: Long\? = null,")
    c.ok(
        "**两个**构造点都填了它（漏一个就有一种查单方式绑不到价）",
        wsvc_c.count("shipperId = d.shipperId") >= 2,
        f"实际 {wsvc_c.count('shipperId = d.shipperId')} 处",
    )

    # ---- 35. 卡片叫模型「先读一次 XXX」时，那个 XXX 必须是**真的读动作**（2026-09-23）----
    #
    # 缘起：给三份分类名册补 AI 能力时，重排卡的 `readHint` 我写成了
    # `expense_categories.list_expense_categories` —— 而目录里真名是
    # `expense_categories.list_categories`（**不许自己拼**）。后果很隐蔽：
    # 卡片上那句「先读一次 X 拿名册」照样印出来，模型照着调一个**不存在的读动作**，
    # 只拿到一句工具不存在，然后开始猜名字 —— 用户看到的是"它怎么老读错"。
    # 当时**一条检查都没拦**（`readHint` 这个词在 1277 项判据里一次都没出现过）。
    #
    # 判据：`readHint = "…"` 那一格必须能在机器生成的读目录里逐字找到，
    # 而且那份目录里得**真的有这个动作**（不是"模块名 + 我自己拼的后缀"）。
    print("\n== 35. 卡片里的「先读一次 XXX」必须指向真的读动作（v3.49）==")
    catalog_kt = read(AI / "AiReadCatalog.kt")
    local_kt = read(AI / "AiLocalReads.kt")
    hint_files = sorted(AI.glob("AiWrite*.kt"))
    hints: list[tuple[str, str]] = []
    for f in hint_files:
        for m in re.finditer(r'readHint\s*=\s*"([^"]+)"', strip_comments(read(f))):
            hints.append((f.name, m.group(1)))
    catalog_ids = set(re.findall(r'ReadAction\(\s*"([^"]+)"', catalog_kt))
    catalog_ids |= set(re.findall(r'ReadAction\(\s*"([^"]+)"', local_kt))
    c.ok(
        f"扫到 {len(hint_files)} 份写处理器、{len(hints)} 处 readHint（少说明正则失效了）",
        len(hint_files) >= 8 and len(hints) >= 5,
        f"文件 {len(hint_files)} 份 / readHint {len(hints)} 处",
    )
    c.ok(
        "读目录里认得出动作（认不出说明目录生成器换了形状）",
        len(catalog_ids) >= 50,
        f"只认出 {len(catalog_ids)} 个读动作",
    )
    bad_hints = [(f, h) for f, h in hints if h not in catalog_ids]
    c.ok(
        "每一处 readHint 都指向目录里真实存在的读动作（不许自己拼名字）",
        not bad_hints,
        f"对不上的：{bad_hints[:4]}",
    )

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
