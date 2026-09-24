"""红线：**退货申请**（货主申请 → 派单员办理）—— 2026-09-21 用户要求的那条流程。

## 用户原话（这条流程的形状就是它定义的）
「批发商……他要进行退货，他**可以直接在订单上**作退货。然后我们的那个派单员，他会接到一个
**通知**，这个时候派单员就会去帮他进行一个退货的操作。**派单员进行完了之后，整个才进行库存
才会发生一个改变和变动**。也就是说**批发商只是一个申请，派单员才是实际性的操作**。」

两个拍板：**所有货主都能申请**（不只是批发商）、**数量锁死**（申请多少就退多少）。

## 这个脚本钉的是哪几件事（每条后面是"不钉住会怎样"）
| # | 钉住的事 | 不钉住会怎样 |
|---|---|---|
| 1 | `submit()` 只写申请单，账/货/状态一行都不碰 | **"申请即退货"静默复活**：货主按一下就把自己的应收与公司库存改了，而派单员根本不知道 —— 申请制存在的全部意义当场作废（用户那句原话直接反了） |
| 2 | `fulfill()` **必须**调 `order_return.return_order()` | 有人在 fulfill 里"顺手"写一份红冲/回补：钱的实现变成两处，两边一定有一天对不上，而**谁都不报错**（这个项目最贵的一类错） |
| 3 | 办理**没有数量参数**（端点签名 → schema 一条链） | 多一个参数就多一条"派单员改了数量"的路，"谁申请了什么、最后办成了什么"这两句话再也对不上 |
| 4 | 申请权与执行权是**两个权限点**，货主只有前者 | 合成一个 ＝ 货主按一下就能改自己的应收和公司库存（`rbac.py` 当初不给货主退货权的理由原地作废） |
| 5 | 两条消息（提交→派单员、办理/驳回→货主）**真的发出去**了 | 申请提了没人知道（货主只能打电话催，功能白做）；办完了没人告诉货主（他以为没办，再提一遍） |
| 6 | 三个新动作码在 `OperationAction` 里、**真的被 `write_log` 写过**、审计页有中文名 | 审计页上分不出"真的退了货"和"只是提了个申请"；或者那一行直接印 `ORDER_RETURN_REQUEST` 原始码，用户看不懂 |
| 7 | 直连退货（订单管理那条老路）**允许退**，但**必须把那张待处理申请自动关闭**，且必须发生在 `db.commit()` **之前**（AI 那条路仍然 fail-closed） | 同一批货**被退两遍**：库存多补、账本多红冲、可能多退一笔现金，而谁都不报错 —— 直连退完申请还是 pending，再点「办理」时余量够、校验全过 |
| 7b | 自动关闭这件事**留下痕迹**：`CLOSED` 状态 + 中文名 + `ORDER_RETURN_REQUEST_CLOSE` 审计 + 一条直达货主的站内信 | 货主的申请"没了"却没有任何答复（他不知道货已经退了、退了多少），审计页上那一行还是原始码 |
| 8 | 四个 AI 动作的 `roles` 与 `forRole` **两个方向**的过滤 | AI 让货主"自己办理退货"（点了必然 403，而用户以为退成功了），或让派单员去"申请"自己的单 |
| 9 | 脚本自己断言"扫到了 N 个函数 / N 条判据" | 清单被改名/搬走之后判据全绿 —— **空转的检查比没有检查更糟**（本项目 §15 的教训：红了一整轮没人知道） |

## 为什么全是**扫源码的正则**、不 import 后端 app
与仓库其它检查同一条纪律：import 后端会连数据库、读配置、建连接池 ——
检查必须能在任何一台机器上离线跑完。这里只读文件字节。

## 相关（别重复造）
· `backend/tests/test_return_request.py` —— 15 条真跑数据库的回归（这里只钉它还在）；
· `_tools/qa/_probe_return_request.py` —— 打真 HTTP 的探针（动态问题它答，静态问题这里答）；
· `_tools/qa/_check_order_return.py` —— 退货**本身**（红冲/回补/退现）的红线，本文件不重复它。

用法：python _tools/qa/_check_return_request.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 公共机制（**不另造一套**）：
#: · `_airepo.refuse_if_injecting` —— 反向验证跑着的时候源码里带着注入的 bug，
#:   那一刻任何结论都不可信，检查必须先喊停（否则你看到的是"一堆真实但无关的失败"）；
#: · `_check_single_source.code_only` —— 把注释/文档字符串换成等长空格（**保留行号**）。
#:   ⚠️ 后端那一半**必须**剥注释：`order_return_request.py` 的模块头与函数文档里
#:   就写着 `return_order` / `Ledger` 这些名字（"本函数绝不调它"），不剥的话
#:   把真代码删掉、判据照样绿（`_check_pagination_wiring.py` 的反向验证栽过这一次）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import orders_api_source, refuse_if_injecting, repo_root  # noqa: E402
from _check_single_source import code_only  # noqa: E402

ROOT = repo_root()
BACKEND = ROOT / "backend/app"
API = BACKEND / "api/v1"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

SERVICE = BACKEND / "services/order_return_request.py"   # submit / withdraw / reject / fulfill
RETURN_SERVICE = BACKEND / "services/order_return.py"    # return_order = 执行的**唯一**入口
API_FILE = API / "return_requests.py"                    # 6 个端点
ORDERS_API = API / "orders.py"                           # 直连退货 + 待处理申请的 fail-closed
RBAC = BACKEND / "core/rbac.py"
ENUMS = BACKEND / "models/enums.py"
PUSH = BACKEND / "services/push_events.py"
MSG = BACKEND / "services/message_center.py"
SCHEMA = BACKEND / "schemas/return_request.py"
TEST_FILE = ROOT / "backend/tests/test_return_request.py"
AI_RR = ANDROID / "ai/AiWriteReturnRequest.kt"
AI_WRITE = ANDROID / "ai/AiWrite.kt"
AI_ORDER = ANDROID / "ai/AiWriteOrderHandlers.kt"
REPORT_CENTER = ANDROID / "ui/dispatcher/ReportCenter.kt"

#: 反空转下限。判据被删到只剩几条（或函数解析全失配）时必须先报错 ——
#: 一条"扫了 0 个函数却全绿"的检查，比没有检查更危险。
MIN_ASSERTIONS = 25
MIN_FUNCTIONS_SCANNED = 12
MIN_ENDPOINTS = 6
MIN_TESTS = 15

#: 「申请阶段什么都不许动」的六个痕迹。每一个都对应一条独立的后果（见 docstring 表格第 1 行）。
FORBIDDEN_IN_SUBMIT: list[tuple[str, str]] = [
    (r"return_order\s*\(", "调了执行的唯一入口 ＝ **申请即退货**（用户原话直接反了）"),
    (r"restock_returned\s*\(", "回补了库存 ＝ 货还在客户手上，仓库里却多了一批"),
    (r"\bLedger\s*\(", "写了账本 ＝ 货主按一下就把自己的应收改掉了"),
    (r"\bCashFlow\s*\(", "写了现金流水 ＝ 申请阶段就退钱给客户"),
    (r"\bInventoryMovement\s*\(", "写了库存流水 ＝ 仓库里出现一笔没人做过的出入库"),
    (r"returned_quantity\s*[-+]?=", "改了已退数量 ＝ 申请就成了「退过一部分」，上限与报表一起偏"),
    (r"order\.status\s*=[^=]", "改了订单状态（整单申请一下就变「已退货」）"),
    (r"order\.returned_at\s*=", "盖了退货时间 ＝ 平账时以为货那天就回来了"),
]


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改，不许静默跳过）")
    return p.read_text(encoding="utf-8")


def join_lines(src: str) -> str:
    """把 `\\` 续行接起来（判据写的是**语义**，不是行怎么折的）。

    ⚠️ 只影响"这一行里有没有这个东西"的判据；行号/顺序判据一律用原始文本。
    """
    return re.sub(r"\\\s*\n\s*", " ", src)


#: 顶格语句：函数/类/装饰器/赋值 —— 用来切出**一个模块级函数的函数体**。
_TOP_LEVEL = re.compile(r"^(?:async def |def |class |@|[A-Za-z_][\w.]*\s*=|__all__)", re.M)


def func_body(src: str, name: str) -> str:
    """模块级 `def name(...)` 的**函数体**（到下一个顶格语句为止）。

    为什么必须切出函数体（而不是在整文件里搜）：`order_return_request.py` 里
    `return_order(` 与 `Ledger(` 本来就存在（import 行与 `fulfill` 里的调用）——
    在整文件里搜，判据会**永远为红**；而放宽到"这个文件里没有"又会漏掉
    "有人往 `submit` 里加了一行"这件真正要防的事。
    """
    m = re.search(rf"^(?:async )?def {re.escape(name)}\(", src, re.M)
    if m is None:
        return ""
    rest = src[m.start():]
    nxt = _TOP_LEVEL.search(rest, 1)
    return rest[: nxt.start()] if nxt else rest


def func_signature(src: str, name: str) -> str:
    """`def name(...)` 的参数表原文（到配对的右括号为止，支持多行签名）。"""
    m = re.search(rf"^(?:async )?def {re.escape(name)}\(", src, re.M)
    if m is None:
        return ""
    depth = 0
    for i in range(m.end() - 1, len(src)):
        ch = src[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return src[m.start(): i + 1]
    return ""


def class_body_anywhere(cls: str) -> tuple[str, str]:
    """在 `backend/app` 全库里找 `class {cls}(...)`，返回 (相对文件名, 类体)。

    为什么不在**某一个** schema 文件里找：请求体模型一旦被搬到别的文件，
    "找不到类"就变成一条**假的**红 —— 而假红会被下一个人手动删掉，判据真的就没了。
    """
    for p in sorted(BACKEND.rglob("*.py")):
        s = code_only(p.read_text(encoding="utf-8"))
        m = re.search(rf"^class {re.escape(cls)}\([\s\S]*?(?=\nclass |\Z)", s, re.M)
        if m:
            return str(p.relative_to(ROOT)).replace("\\", "/"), m.group(0)
    return "", ""


def kotlin_code_only(src: str) -> str:
    """Kotlin 去注释（块注释 + 行注释）。

    与 Python 那一半同一条理由：`AiWriteReturnRequest.kt` 的文件头就写着
    「前三个动作一行钱、一件货都不许动」这类话，不剥掉的话注释会让判据变绿。
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    src = re.sub(r"//[^\n\"']*$", "", src, flags=re.M)
    return src


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0
        self.scanned: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        #: ⚠️ 一律带 `re.M`：本文件的判据大量用 `^\s+NAME = ...` 去**定位某一行**
        #:    （枚举成员、白名单条目）。不加 `re.M` 时 `^` 只在整段开头成立，
        #:    这类判据会**永远为红**（`OperationAction` 那三条第一次就是这么红的），
        #:    而下一个人很可能用"把判据删掉"来让它变绿。
        m = re.search(pattern, text, re.M)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is None, f"命中：{m.group(0)[:70]!r}" if m else "")

    def body_of(self, src: str, name: str, where: str) -> str:
        """切函数体，并**记一笔"扫到了这个函数"**（末尾的数量判据靠它防静默空转）。"""
        b = func_body(src, name)
        if b:
            self.scanned.append(f"{where}::{name}")
        return b


def main() -> int:
    if refuse_if_injecting("退货申请检查"):
        return 1

    c = Checker()

    svc = read(SERVICE)
    api = read(API_FILE)
    orders_api = orders_api_source(ROOT)
    rbac = read(RBAC)
    enums = read(ENUMS)
    push = read(PUSH)
    msg = read(MSG)
    schema = read(SCHEMA)
    ret_svc = read(RETURN_SERVICE)
    tests = read(TEST_FILE)
    ai_rr = read(AI_RR)
    ai_write = read(AI_WRITE)
    ai_order = read(AI_ORDER)
    report = read(REPORT_CENTER)
    #: 派发表住在 `main.py`（整改报告 §10 之后，站内信那条链子多了一跳：入队 → 派发表 → push_events → 消息中心）。
    main_src = read(BACKEND / "main.py")

    # 后端一律只看代码（注释/文档字符串换成空格，**行号不变**）。
    svc_c = code_only(svc)
    api_c = code_only(api)
    orders_c = code_only(orders_api)
    rbac_c = code_only(rbac)
    enums_c = code_only(enums)
    push_c = code_only(push)
    msg_c = code_only(msg)
    main_body = code_only(main_src)
    schema_c = code_only(schema)
    ret_c = code_only(ret_svc)
    ai_rr_c = kotlin_code_only(ai_rr)
    ai_write_c = kotlin_code_only(ai_write)
    ai_order_c = kotlin_code_only(ai_order)
    report_c = kotlin_code_only(report)

    # ---------------------------------------------------------------- 0. 前提
    print("== 0. 前提与反空转（判据自己先证明它在看东西）==")
    n_tests = len(re.findall(r"^def test_", tests, re.M))
    c.ok(
        f"回归测试还在（{n_tests} 条，下限 {MIN_TESTS}）——这批真跑数据库的用例是这些结构判据的地基",
        n_tests >= MIN_TESTS,
        f"实际 {n_tests}",
    )
    # 不钉住会怎样：结构判据全绿而把真跑库的回归删了 ＝ "看着有人管，其实没人验"。
    for star in (
        "test_apply_touches_nothing",
        "test_fulfill_returns_exactly_what_was_applied",
        # ⚠️ 这条用例的**名字跟着规则换过一次**（2026-09-21 用户把直连退货从"400 拦住"
        #    改成"允许退 + 自动关申请"）。⛔ 别把它改回旧名字：
        #    `test_direct_return_is_blocked_while_a_request_is_pending` 在测试文件里
        #    只剩一句历史注释（另一个用例的 docstring 里提到它），`present` 照样找得到 ——
        #    那样这条判据就在"钉住"一个**已经不存在的用例**，而它永远是绿的。
        "test_direct_return_closes_the_pending_request",
        "test_apply_does_not_check_membership",
    ):
        # 不钉住会怎样：这四条分别对应「申请不动」「办理恰好退申请的量」「两条路都堵」「所有货主都能申请」，
        # 删掉任何一条，本文件守的那条线就只剩静态形状、没有一次真实执行验证。
        c.present(f"端到端钉住「{star}」", tests, re.escape(star))

    endpoints = (
        "create_return_request",
        "list_my_return_requests",
        "withdraw_return_request",
        "list_return_requests",
        "reject_return_request",
        "fulfill_return_request",
    )
    sigs = {name: func_signature(api_c, name) for name in endpoints}
    missing_ep = [n for n, s in sigs.items() if not s]
    c.ok(
        f"从源码解析到 {len(endpoints) - len(missing_ep)}/{len(endpoints)} 个端点（清单自己算，防路径写错后空转）",
        not missing_ep,
        f"没解析到：{missing_ep}",
    )
    for name in endpoints:
        if sigs[name]:
            c.scanned.append(f"return_requests.py::{name}")

    # ---------------------------------------------------------------- 1. 申请什么都不动
    print("\n== 1. submit() 只写申请单：账/货/状态一行都不碰（用户原话的那条线）==")
    submit_body = c.body_of(svc_c, "submit", "order_return_request.py")
    c.ok("解析到了 submit() 的函数体", bool(submit_body), "解析不到就等于这一整节在空转")
    if submit_body:
        for pat, why in FORBIDDEN_IN_SUBMIT:
            # 不钉住会怎样：见 why。每一条都是"申请阶段偷偷把既成事实改了"的一个独立入口。
            c.absent(f"submit() 里没有 {pat}（{why}）", submit_body, pat)
        c.present(
            "submit() 写的是申请单本身（OrderReturnRequest + 明细行）—— 它**该**做的事",
            submit_body,
            r"OrderReturnRequest\(",
        )

    # ---------------------------------------------------------------- 2. 执行只有一条路
    print("\n== 2. fulfill() 必须走 order_return.return_order（执行的唯一入口）==")
    fulfill_body = c.body_of(svc_c, "fulfill", "order_return_request.py")
    c.ok("解析到了 fulfill() 的函数体", bool(fulfill_body))
    if fulfill_body:
        # 不钉住会怎样：这是与第 1 节**方向相反**的一条 ——
        # submit 里出现 return_order 是 bug，fulfill 里不出现它同样是 bug
        # （那样"办理"就会变成"只把申请标成已办"，货主以为退了、库存没回来，最坏的一种结果）。
        c.present(
            "fulfill() 真的调了 order_return.return_order（唯一入口；缺了它＝办理什么都没发生）",
            fulfill_body,
            r"return_order\s*\(\s*db\s*,\s*order\s*,\s*items",
        )
        for pat, why in (
            (r"\bLedger\s*\(", "自己写红冲 ＝ 钱的实现变成两处"),
            (r"\bCashFlow\s*\(", "自己写退现 ＝ 两边金额迟早不一致"),
            (r"\bInventoryMovement\s*\(", "自己写库存流水 ＝ 与 restock_returned 的判断分叉"),
            (r"restock_returned\s*\(", "自己回补库存 ＝ 绕过 return_order 里的那道库存门"),
            (r"returned_quantity\s*[-+]?=", "自己改已退数量 ＝ 绕过 SQL 表达式自增（并发下会丢一次）"),
        ):
            # 不钉住会怎样：fulfill 里多一份实现，就是"同一笔钱两处算"，
            # 而这两处**谁都不报错**，只在月底对账时被客户发现。
            c.absent(f"fulfill() 不自己写 {pat}（{why}）", fulfill_body, pat)

    n_def = len(re.findall(r"^def return_order\(", ret_c, re.M))
    # 不钉住会怎样：出现第二份 `def return_order(`，fulfill 调哪一份就变成看 import 顺序的事。
    c.ok(f"全后端只有一处 `def return_order(`（实测 {n_def} 处）", n_def == 1, f"实际 {n_def}")
    c.present("fulfill 用的就是 order_return 里那一个（import 行在）", svc_c, r"from app\.services\.order_return import")
    n_cap = len(re.findall(r"^def max_returnable\(", "\n".join(
        p.read_text(encoding="utf-8") for p in sorted(BACKEND.rglob("*.py"))
    ), re.M))
    # 不钉住会怎样：上限被算成两份（申请侧一份、执行侧一份）→ 一边让填 3、一边只认 2，
    # 用户不知道该信谁（`_check_order_return.py` 对客户端已经钉了同一条）。
    c.ok(f"可退上限只有 `order_return.max_returnable` 一处实现（实测 {n_cap} 处）", n_cap == 1, f"实际 {n_cap}")

    # ---------------------------------------------------------------- 3. 数量锁死
    print("\n== 3. 数量锁死：办理没有数量参数（端点签名 → schema 一条链）==")
    fulfill_sig = sigs["fulfill_return_request"]
    # 不钉住会怎样：多一个参数就多一条"派单员改了数量"的路 ——
    # 而这条流程的产出物恰恰是"谁申请了什么、最后办成了什么"这两句话必须对得上。
    c.absent("fulfil 端点的函数签名里没有数量参数 quantity", fulfill_sig, r"quantity")
    c.absent("fulfil 端点的函数签名里没有 items（明细也不许由调用方给）", fulfill_sig, r"\bitems\b")
    body_param = re.search(r"^\s{4}(\w+)\s*:\s*(\w+Body)\b", fulfill_sig, re.M)
    if body_param is None:
        c.ok(
            "fulfil 端点**连请求体都没有**（比「没有数量字段」更强的一条：压根没有可传数量的入口）",
            True,
        )
    else:
        # 链式证明：签名里出现了请求体 → 必须去**那个 schema 类**里证明它没有数量字段。
        # ⚠️ 类**不限定在 `schemas/return_request.py` 里找**：一旦有人把请求体放到别的
        #    schema 文件，"找不到类"会变成一条**假的**红（而假红会被下一个人手动删掉，
        #    于是判据真的没了）。所以在 backend/app 全库找。
        cls = body_param.group(2)
        where, fields = class_body_anywhere(cls)
        c.ok(f"链到请求体模型 {cls}（签名里有 body 就必须能追到它，在 {where or '找不到'}）", bool(fields))
        c.absent(f"请求体模型 {cls} 里没有数量字段（有的话「锁死」当场作废）", fields, r"quantity|\bitems\b")

    fulfil_svc_sig = func_signature(svc_c, "fulfill")
    # 不钉住会怎样：服务层多一个数量参数，端点"现在"不传不等于以后不传 ——
    # 而服务层是唯一能挡住"从别处调进来"的地方（比如以后的批量办理）。
    c.absent("fulfill() 服务签名里没有 items 参数（数量不许由调用方给）", fulfil_svc_sig, r"\bitems\b")
    c.absent("fulfill() 服务签名里没有 quantity 参数", fulfil_svc_sig, r"quantity")
    c.present(
        "fulfill() 的数量**取自申请单**（ReturnItem(...) for ln in req.lines）",
        join_lines(fulfill_body),
        r"ReturnItem\(order_product_id=ln\.order_product_id,\s*quantity=ln\.quantity\)\s*for ln in req\.lines",
    )
    # 不钉住会怎样：申请之后余量可能变小（别的退货先办了 / 司机补报了货损），
    # 不重算就会退出去超过下单量的货（这一条与 `_check_order_return.py` 的上限判据互补）。
    c.present(
        "办理前**重算上限**（申请之后余量可能变小 → 直接执行会退超）",
        join_lines(fulfill_body),
        r"cap = max_returnable\(op\)[\s\S]{0,200}?ln\.quantity > cap",
    )
    # 全后端扫一遍"办理请求体"这个形状：现在一个都不该有；一旦出现，必须不含数量字段。
    bodies = []
    for p in sorted(BACKEND.rglob("*.py")):
        s = code_only(p.read_text(encoding="utf-8"))
        for m in re.finditer(r"class (\w*Fulfill\w*Body)\([\s\S]*?(?=\nclass |\Z)", s):
            bodies.append((p.name, m.group(1), m.group(0)))
    for fname, cls, text in bodies:
        # 不钉住会怎样：有人图省事加一个 `ReturnRequestFulfillBody(quantity=...)`，
        # 端点签名那一节照样绿（它自己没写 quantity），而数量锁死已经在 schema 里破了。
        c.absent(f"{fname}::{cls} 里没有数量字段（防「签名干净、schema 破口」）", text, r"quantity|\bitems\b")
    print(f"         （附注：扫到 {len(bodies)} 个 *Fulfill*Body 模型 —— 0 个是当前状态，"
          f"≥1 个就必须过上面那条判据，这条附注不参与计分）")
    # 不钉住会怎样：出参只回一个状态、不回那笔退货的结果 → 派单员看不到"退了多少、退了多少钱"，
    # 只能靠刷新订单列表去猜（而这页客户端本来就要求它刷新，两者一旦不一致没人知道信谁）。
    c.present(
        "办理出参同时带申请单与那次真实退货的回参（request + returned）",
        schema_c,
        r"request: ReturnRequestOut[\s\S]{0,120}?returned: OrderReturnOut",
    )
    c.ok(f"扫到的 *Fulfill*Body 模型 {len(bodies)} 个（0 个也是通过，但**一旦出现**就必须过上面那条）", True)

    # ---------------------------------------------------------------- 4. 两个权限点
    print("\n== 4. 申请权与执行权是两个权限点（合起来＝货主能改自己的应收）==")
    c.present("rbac 里声明了 ORDER_RETURN_REQUEST", rbac_c, r'ORDER_RETURN_REQUEST = "order:return_request"')
    c.present("rbac 里声明了 ORDER_RETURN", rbac_c, r'ORDER_RETURN = "order:return"')
    shipper_block = re.search(r'"shipper": frozenset\(([\s\S]*?)\n    \),', rbac_c)
    # 不钉住会怎样：解析失效时下面两条会**安静地通过**（空字符串里当然没有退货权）。
    c.ok("解析到了货主权限矩阵那一段", shipper_block is not None)
    shipper = shipper_block.group(1) if shipper_block else ""
    c.present("货主矩阵里有 ORDER_RETURN_REQUEST（申请权 —— 用户拍板「所有货主都能申请」）", shipper, r"ORDER_RETURN_REQUEST\b")
    c.absent(
        "货主矩阵里没有 ORDER_RETURN（执行权）",
        shipper,
        # ⚠️ 必须带 `\b`（`_check_order_return.py` 里已有同一条注释，照抄它的写法）：
        #    `ORDER_RETURN_REQUEST` 以 `ORDER_RETURN` 开头，裸子串匹配会把"申请权"
        #    当成"执行权"，这条断言当场变红 —— 而下一个人为了让检查变绿，
        #    很可能去删掉货主那条**正确**的申请权限（把正确的东西改坏来迎合判据）。
        #    `_` 是词字符，所以 `ORDER_RETURN\b` 匹配 `Permission.ORDER_RETURN,`、
        #    不匹配 `Permission.ORDER_RETURN_REQUEST` —— 这正是要区分的那条线。
        r"ORDER_RETURN\b",
    )
    dispatcher_block = re.search(r'"dispatcher": frozenset\(([\s\S]*?)\n    \),', rbac_c)
    c.ok("解析到了派单员权限矩阵那一段", dispatcher_block is not None)
    c.present(
        "派单员矩阵里有 ORDER_RETURN（执行权只在他那一格）",
        dispatcher_block.group(1) if dispatcher_block else "",
        r"ORDER_RETURN\b",
    )

    # 扫**整个 api/v1**（不是只看这一个文件）：判据问的是"这个权限点到底有没有被用上"，
    # 只在自家文件里数的话，端点被搬到别的模块时这条会变成假的红。
    all_api = "\n".join(code_only(p.read_text(encoding="utf-8")) for p in sorted(API.glob("*.py")))
    used = {
        pt: len(re.findall(rf"require_permission\(Permission\.{pt}\)", all_api))
        for pt in ("ORDER_RETURN", "ORDER_RETURN_REQUEST")
    }
    # 不钉住会怎样：权限点**只是声明**（`rbac.py` 头部的注释就在讲这件事：
    # 5 个读权限点声明了却没有任何端点用）→ 改矩阵不改变任何行为，
    # 而端点索引与 AI 读能力目录又是从矩阵推导的：文档说"没权限了"、接口照样能用。
    c.ok(f"ORDER_RETURN 真被 require_permission 用上（{used['ORDER_RETURN']} 处）", used["ORDER_RETURN"] >= 1)
    c.ok(
        f"ORDER_RETURN_REQUEST 真被 require_permission 用上（{used['ORDER_RETURN_REQUEST']} 处）",
        used["ORDER_RETURN_REQUEST"] >= 1,
    )
    expect_perm = {
        "create_return_request": "ORDER_RETURN_REQUEST",
        "list_my_return_requests": "ORDER_RETURN_REQUEST",
        "withdraw_return_request": "ORDER_RETURN_REQUEST",
        "list_return_requests": "ORDER_RETURN",
        "reject_return_request": "ORDER_RETURN",
        "fulfill_return_request": "ORDER_RETURN",
    }
    for name, perm in expect_perm.items():
        sig = sigs.get(name, "")
        # 不钉住会怎样：某一个端点挂错权限点（比如 fulfill 挂成申请权）＝
        # 货主那一侧凭空多出一个"真的退货"的入口，而端点数、权限点数全都还是对的。
        c.ok(
            f"端点 {name}() 用的是 {perm}",
            bool(sig) and f"Permission.{perm}" in sig,
            "签名里没找到" if sig else "没解析到签名",
        )

    # ---------------------------------------------------------------- 4c. 货主那一半必须**显式卡角色**
    #
    # ⚠️ 为什么权限点不够（2026-09-22 实测）：`require_permission` 对派单员**一律放行**
    #    （`core/rbac.py::role_has_permission` 头一句），于是这三个"货主自己那一半"的端点
    #    派单员实际调得到 —— `GET /mine` 返回 `200 + 空列表`（他名下没有申请）。
    #    后果不是"泄露"也不是"错数"，而是**声明与实现分叉**：
    #    `_tools/ai/_probe_read_roles.py` 永远红着一条，而下一个人为了让检查变绿，
    #    最省事的做法是把 AI 读目录改成"派单员可用" —— 那会给派单员的 AI 一个
    #    **必然没用**的读动作（他从没当过货主，永远答"没有"）。
    #    所以三个端点都必须挂 `ShipperOnly`（`Annotated[User, Depends(require_roles(SHIPPER))]`）。
    c.present("模块里定义了货主专用的角色门 ShipperOnly",
              api, r"ShipperOnly = Annotated\[\s*\n?\s*User,\s*Depends\(require_roles\(UserRole\.SHIPPER\)\)\s*\n?\s*\]")
    for name in ("create_return_request", "list_my_return_requests", "withdraw_return_request"):
        sig = sigs.get(name, "")
        c.ok(
            f"端点 {name}() 显式挂着货主专用角色门（光有权限点挡不住派单员）",
            "ShipperOnly" in sig,
            "签名里没找到 ShipperOnly" if sig else "没解析到签名",
        )
    for name in ("list_return_requests", "reject_return_request", "fulfill_return_request"):
        sig = sigs.get(name, "")
        c.ok(
            f"派单端端点 {name}() **不挂**货主门（他自己那一半要能干活）",
            bool(sig) and "ShipperOnly" not in sig,
            "派单端端点被挂上了货主门 —— 派单员会按不了" if sig else "没解析到签名",
        )

    # ---------------------------------------------------------------- 5. 消息双向（四跳：入队 → 派发表 → push_events → message_center）
    print("\n== 5. 消息双向：endpoint → 发件箱 → 派发表 → push_events → message_center 逐跳接通 ==")
    # ⚠️ 2026-09-25 换过形状（整改报告 §10）：原来第一跳是 `background_tasks.add_task(_bg_notify_X)`，
    #    §10 把那批后台任务搬进了事务发件箱 —— 链子变成**四跳**，判据也跟着走：
    #      端点 enqueue("returns.x") → main.py 派发表 → push_events.push_x → message_center.publish_x
    #    ⛔ 不放宽：少任何一跳，通知都不落库（申请提了没人知道 / 办完了没人告诉货主）。
    enqueued = sorted(set(re.findall(r"outbox\.enqueue\(\s*db,\s*\"(returns\.\w+)\"", api)))
    c.ok(f"三个写动作都入队了（实测 {len(enqueued)} 个：{enqueued}）", len(enqueued) >= 3, f"实际 {enqueued}")
    publish_used: list[str] = []
    for ev in enqueued:
        branch = re.search(
            r'event\.event_type == "' + re.escape(ev) + r'"([\s\S]{0,500}?)(?=\n    if event\.event_type|\Z)',
            main_src,
        )
        m1 = re.search(r"await\s+push_events\.(\w+)\(", branch.group(1)) if branch else None
        c.ok(
            f"第 1 跳：派发表里为 {ev} 登记了处理器（没登记＝事件会被反复标记失败、通知永远不发）",
            m1 is not None,
        )
        if m1 is None:
            continue
        push_name = m1.group(1)
        hop2 = c.body_of(push_c, push_name, "push_events.py")
        c.ok(f"第 2 跳：{push_name}() 在 push_events 里存在且非空", bool(hop2))
        m2 = re.search(r"message_center\.(publish_\w+)\(", hop2)
        c.ok(f"第 2 跳：{push_name}() 真的调了 message_center 的发布者（断了＝消息不落库、离线的人永远收不到）", m2 is not None)
        if m2 is None:
            continue
        publish_name = m2.group(1)
        publish_used.append(publish_name)
        hop3 = c.body_of(msg_c, publish_name, "message_center.py")
        c.ok(f"第 3 跳：{publish_name}() 在 message_center 里存在且非空", bool(hop3))
        c.present(
            f"第 3 跳：{publish_name}() 真的落了站内信（create_message）",
            hop3,
            r"create_message\(",
        )
    c.ok(
        f"两条方向各自的发布者都接上了（实测 {sorted(set(publish_used))}）",
        len(set(publish_used)) >= 3,
        "提交→派单员 / 驳回→货主 / 办理→货主 三条少任何一条都是单向哑巴",
    )
    to_dispatchers = c.body_of(msg_c, "publish_return_request_to_dispatchers", "message_center.py")
    # 不钉住会怎样：收件人写错（发给某个固定的人 / 发给自己）→
    # 在线的那个派单员收不到，而"谁在线谁办"正是这条流程的排班前提。
    c.ok(
        "提交 → 派单员：广播给**全体在职派单员**（UserRole.DISPATCHER + is_active）",
        bool(re.search(r"UserRole\.DISPATCHER", to_dispatchers)) and "is_active" in to_dispatchers,
    )
    c.present("提交 → 派单员：收件人是那个派单员本人（recipient_id=d.id）", to_dispatchers, r"recipient_id=d\.id")
    for fn, label in (
        ("publish_return_request_rejected", "驳回"),
        ("publish_return_request_done", "办理"),
    ):
        body = c.body_of(msg_c, fn, "message_center.py")
        # 不钉住会怎样：驳回/办理的消息发错人（发到派单员自己那儿）→
        # 货主永远不知道结果，只能反复重提，而每次派单员都要重新看一遍。
        c.present(f"{fn} 发给**货主**（req.shipper_id）：{label}的结果必须回到申请人手里", body, r"recipient_id=req\.shipper_id")
    c.present(
        "payload 里带 request_id（不带的话派单员点开消息找不到是哪一张申请）",
        msg_c,
        r'"request_id":\s*req\.id',
    )
    # 不钉住会怎样：只 `emit_realtime` 不落库 → App 没开着的那一刻，这条消息就永久丢了。
    c.present("消息落库后才实时推送（离线的人下次打开还能看到）", to_dispatchers, r"emit_notification\(")

    # ---------------------------------------------------------------- 6. 审计留痕
    print("\n== 6. 审计留痕：三个新动作码都要在枚举里、真的被写过、审计页有中文名 ==")
    enum_block_m = re.search(r"class OperationAction\([\s\S]*?(?=\nclass |\Z)", enums_c)
    enum_block = enum_block_m.group(0) if enum_block_m else ""
    c.ok("解析到了 OperationAction 这个枚举体", bool(enum_block))
    audit = {
        "ORDER_RETURN_REQUEST": "submit",
        "ORDER_RETURN_REQUEST_REJECT": "reject",
        "ORDER_RETURN_REQUEST_WITHDRAW": "withdraw",
    }
    for code in audit:
        # 不钉住会怎样：码没进枚举 → 写日志时 `OperationAction.X` 直接 AttributeError（500），
        # 或者更常见：有人改用裸字符串，审计页从此对不上这张表。
        c.present(f"OperationAction 里有 {code}", enum_block, rf'^\s+{code} = "{code}"')
    for code, fn in audit.items():
        body = c.body_of(svc_c, fn, "order_return_request.py")
        # 不钉住会怎样：申请/驳回/撤回**一条日志都不写** → 出问题时第一个要问的
        # "这是谁决定的"（派单员驳回 vs 货主自己撤回）事后无法回答。
        # ⚠️ 用 `(?<![\w.])write_log\(`：写成 `_write_log(` 也不算数（`_` 是词字符，
        #    裸 `write_log\(` 会在它里面匹配上 —— 反向验证正是这样抓到过一次）。
        c.ok(
            f"{fn}() 写了 {code} 审计（且真的调了 write_log）",
            code in body and re.search(r"(?<![\w.])write_log\(", body) is not None,
            "函数体里缺这个动作码或没调 write_log",
        )
    label_block_m = re.search(r"private fun actionLabel\([\s\S]*?\n\}", report_c)
    labels = dict(
        re.findall(r'"([A-Z][A-Z0-9_]{3,})"\s*->\s*"([^"]+)"', label_block_m.group(0) if label_block_m else "")
    )
    c.ok("解析到了 ReportCenter.kt 的 actionLabel 表", len(labels) >= 10, f"只解析出 {len(labels)} 条")
    for code in audit:
        # 不钉住会怎样：审计卡片那一行的标题**直接显示原始码**（`ORDER_RETURN_REQUEST`），
        # 用户看不懂 —— 这个项目已经栽过一次（USER_RESTORE 那四行英文）。
        c.ok(
            f"审计动作码 {code} 在 ReportCenter 里有中文名（否则卡片上印原始码）",
            code in labels and bool(labels[code].strip()),
            "表里没有这一条",
        )

    # ---------------------------------------------------------------- 7. 直连退货 = 自动关闭申请
    #
    # ⚠️ 这一节的规则在 2026-09-21 **反过一次方向**，两个方向都记在这里，免得下一个人再翻回去：
    #   ① 最初这里是「挂着待处理申请时，直连退货必须被 400 挡住」（fail-closed）；
    #   ② 用户当天拍板改成「**允许直连退货 + 自动取消申请**」——
    #      原话：「把规则改成派单员退货之后，自动取消申请，然后它对应的数据发生改变，
    #      状态变成已退货多少多少」。
    #    所以"同一批货退两遍"那个洞**不是消失了，而是换了堵法**：申请被自动关掉之后
    #    `fulfill` 会被 `_check_pending` 拒（"已经由派单员直接退了货（自动关闭）"）。
    # ⛔ 因此这一节**不能只是把旧的 400 判据删掉** —— 删掉就等于那个洞重新敞开，
    #    而"申请还是 pending、余量还够、校验全过"正是它最贵的形态（谁都不报错）。
    print("\n== 7. 直连退货：**允许退**，但必须把那张待处理申请自动关闭（2026-09-21 新规则）==")
    ro_body = c.body_of(orders_c, "return_order_endpoint", "orders.py")
    c.ok("解析到了 orders.py 的 order_return_endpoint", bool(ro_body))
    # 不钉住会怎样：货主申请退 2 件、派单员在手边这张单上手工退 2 件、申请**仍然待处理** →
    # 他（或另一个派单员）再点「办理」时余量仍然够 → 同一批货被退第二次：库存多补、
    # 账本多红冲、可能多退一笔现金，而**谁都不报错**。
    c.present(
        "orders.py 的退货端点会**查这张单有没有待处理申请**（pending_for_order —— 关掉它的前提）",
        ro_body,
        r"pending_for_order\(",
    )
    # 新规则①：直连退货**照旧允许**（那段 400 拦截必须已经不在了）。
    # 不钉住会怎样：有人"顺手"把旧的 fail-closed 加回来 —— 那是**另一个方向**的错：
    # 用户拍板的规则是"派单员退货之后自动取消申请"，退不了货就等于那条规则没落地。
    c.absent(
        "不再有那段「有待处理申请就 400 拦住」的旧规则（2026-09-21 已改成允许直连 + 自动关闭）",
        ro_body,
        r"status_code=400[\s\S]{0,300}?待处理的退货申请",
    )
    c.present(
        "直连退货照旧走唯一入口 return_order(（不是自己写一份红冲/回补）",
        ro_body,
        r"return_order\(\s*db\s*,\s*order\s*,",
    )
    # 新规则②：必须真的把那张申请关掉。
    # 不钉住会怎样（这是整节的核心）：漏掉这一次调用 → 申请还停在 pending →
    # 「办理」那条路余量够、校验全过 → 同一批货被退第二遍，且没有任何报错。
    c.present(
        "直连退货里真的调了 close_by_direct_return(...)（漏掉它＝「同一批货退两遍」复活）",
        ro_body,
        r"close_by_direct_return\(",
    )
    i_close = ro_body.find("close_by_direct_return(")
    i_commit = ro_body.find("db.commit()")
    # 不钉住会怎样：**顺序**是这条规则的全部意义所在 —— 提交之后再关申请，
    # "有没有这一次调用"照样成立，而那一瞬间申请还是 pending（并发点「办理」就穿过去了），
    # 更别说关申请自己抛错时货已经落库（申请永远关不掉）。所以必须要求 close 在 commit 之前。
    c.ok(
        "关申请发生在 db.commit() **之前**（顺序：close_by_direct_return → db.commit）",
        -1 < i_close < i_commit,
        f"下标 close={i_close} commit={i_commit}",
    )
    # 这一节剩下的三条：**这件事留下的痕迹**（状态码 / 中文名 / 审计 / 那条站内信）。
    # 不钉住会怎样：货主的申请"没了"却没有任何解释；审计页上那一行直接印原始码；
    # 或者最隐蔽的一种：关了申请但**没发消息** —— 货主永远不知道货已经退了。
    c.present(
        "ReturnRequestStatus 里有 CLOSED（自动关闭用的是它，而不是偷偷复用 done）",
        enums_c,
        r'^\s+CLOSED = "closed"',
    )
    c.present(
        "CLOSED 在 _STATUS_LABEL 里有中文名（客户端一律显示后端给的名字）",
        api_c,
        r"ReturnRequestStatus\.CLOSED\.value:\s*\"[^\"]+\"",
    )
    c.present(
        "OperationAction 里有 ORDER_RETURN_REQUEST_CLOSE（没进枚举＝写日志时直接 AttributeError）",
        enum_block,
        r'^\s+ORDER_RETURN_REQUEST_CLOSE = "ORDER_RETURN_REQUEST_CLOSE"',
    )
    close_body = c.body_of(svc_c, "close_by_direct_return", "order_return_request.py")
    c.ok("解析到了 close_by_direct_return() 的函数体", bool(close_body), "解析不到则下面两条在空转")
    # 不钉住会怎样："申请自动关闭"是一次**别人做的决定**，没有日志就再也答不出
    # "这张申请为什么没被办理就结束了"（用户拍板那条规则的落地证据就是它）。
    c.ok(
        "close_by_direct_return() 写了 ORDER_RETURN_REQUEST_CLOSE 审计（且真的调了 write_log）",
        "ORDER_RETURN_REQUEST_CLOSE" in close_body
        and re.search(r"(?<![\w.])write_log\(", close_body) is not None,
        "函数体里缺这个动作码或没调 write_log",
    )
    c.ok(
        "审计动作码 ORDER_RETURN_REQUEST_CLOSE 在 ReportCenter 里有中文名",
        "ORDER_RETURN_REQUEST_CLOSE" in labels and bool(labels["ORDER_RETURN_REQUEST_CLOSE"].strip()),
        "表里没有这一条（卡片上会直接印原始码）",
    )
    # 站内信：**四跳**逐跳接通（整改报告 §10 之后链子加了一跳：多了"事务发件箱"）。
    # ⚠️ 2026-09-25 换过形状：原来是「orders.py 的后台任务 `_bg_notify_return_request_closed` → push_* →
    #    message_center」；§10 把那批后台任务搬进了发件箱，于是链子是：
    #      orders_return.py 入队 `returns.request_closed` → main.py 派发表 → push_events → message_center
    #    ⛔ 判据**不许**因此放宽：少任何一跳，站内信都不落库（货主连"申请被关了"都不知道）。
    c.present(
        "orders_return.py 的退货端点真的入队了「申请已关闭」那条事件",
        ro_body,
        r"outbox\.enqueue\(\s*db,\s*\"returns\.request_closed\"",
    )
    c.present(
        "第 1 跳：派发表里为 `returns.request_closed` 登记了处理器（没登记＝事件被反复标记失败）",
        main_src,
        r'event\.event_type == "returns\.request_closed"[\s\S]{0,400}?push_events\.push_return_request_closed',
    )
    push_closed_name = "push_return_request_closed"
    if push_closed_name:
        hop2c = c.body_of(push_c, push_closed_name, "push_events.py")
        m2c = re.search(r"message_center\.(publish_\w+)\(", hop2c)
        c.ok(f"第 2 跳：{push_closed_name}() 真的调了 message_center 的发布者", m2c is not None)
        if m2c:
            pub_c = m2c.group(1)
            hop3c = c.body_of(msg_c, pub_c, "message_center.py")
            c.ok(f"第 3 跳：{pub_c}() 存在且真的落了站内信（create_message）",
                 bool(hop3c) and "create_message(" in hop3c)
            c.present(f"第 3 跳：{pub_c}() 发给**货主**（req.shipper_id）", hop3c, r"recipient_id=req\.shipper_id")
            # 不钉住会怎样：payload 里没有 request_id → 货主点那条消息到不了那张申请
            # （本页 §5 已钉了申请侧那一条，这里是自动关闭那条消息的同一条要求）。
            c.present(f"第 3 跳：{pub_c}() 的 payload 里带 request_id（点消息要能直达那张申请）",
                      hop3c, r"_return_request_payload\(")

    handler_m = re.search(r"^class ReturnOrderHandler\(", ai_order_c, re.M)
    if handler_m:
        rest = ai_order_c[handler_m.end():]
        nxt = re.search(r"^class ", rest, re.M)
        handler = ai_order_c[handler_m.start(): handler_m.end() + (nxt.start() if nxt else len(rest))]
        c.scanned.append("AiWriteOrderHandlers.kt::ReturnOrderHandler")
    else:
        handler = ""
    c.ok("解析到了 AiWriteOrderHandlers.kt 的 ReturnOrderHandler", bool(handler))
    # 不钉住会怎样：后端堵住了、AI 那条路没堵 → 用户对助手说"帮我退这张单"，
    # 卡片弹得出来、点了确认才拿到 400（"能看见但一定失败"的另一半：
    # 更糟的是模型可能改口说"那就当办过了"）。
    c.present(
        "AI 侧 ReturnOrderHandler.prepare 也查了待处理申请（ds.pendingReturnRequests + isPending）",
        handler,
        r"pendingReturnRequests\([\s\S]{0,120}?isPending",
    )
    c.present("AI 侧查到就直接拒绝（throw，而不是弹一张必然失败的卡）", handler, r"throw AiWriteArgException\(")
    i_ai_pre = handler.find("pendingReturnRequests(")
    i_ai_lines = handler.find("ds.returnableLines(")
    # 不钉住会怎样：预检放在取可退余量之后，卡片会先按"能退多少"算出一个数再报错 ——
    # 用户看到的是"系统算过了，只是不让点"，而真实原因是"这张申请还没办"。
    c.ok(
        "AI 侧那条预检在取可退余量之前（顺序：查申请 → 拒绝 → 再算余量）",
        -1 < i_ai_pre < i_ai_lines,
        f"下标 pending={i_ai_pre} returnable={i_ai_lines}",
    )

    # ---------------------------------------------------------------- 8. AI 角色不越权
    print("\n== 8. AI 四个动作的角色（货主两个、派单员两个，且 forRole 两个方向都过滤）==")
    actions = ai_rr_c.split("AiWriteAction(")[1:]
    c.ok(f"解析到 {len(actions)} 个 AiWriteAction 块（期望 4）", len(actions) >= 4, f"实际 {len(actions)}")
    role_expect = {
        "AiWrites.RETURN_REQUEST_APPLY": "AiRole.SHIPPER",
        "AiWrites.RETURN_REQUEST_WITHDRAW": "AiRole.SHIPPER",
        "AiWrites.RETURN_REQUEST_REJECT": "AiRole.DISPATCHER",
        "AiWrites.RETURN_REQUEST_FULFILL": "AiRole.DISPATCHER",
    }
    for action_id, want in role_expect.items():
        block = next((b for b in actions if f"id = {action_id}" in b), "")
        who = "货主" if want.endswith("SHIPPER") else "派单员"
        # 不钉住会怎样：roles 删掉或写反 → AI 清单里多出/少掉一整类卡。
        # · 少标的后果是"能看见但一定失败"（货主点"办理退货申请"必然 403，
        #   而界面弹过确认卡，用户会以为退成功了）；
        # · 多标的后果是"派单员去申请自己的单"（后端以「这不是你的订单」拒绝）。
        c.ok(
            f"{action_id} 只给{who}（roles = setOf({want})）",
            bool(block) and re.search(rf"roles = setOf\(\s*{re.escape(want)}\s*\)", block) is not None,
            "块里没找到那一行" if block else "没解析到这个动作块",
        )
    for_role_m = re.search(r"\n    fun forRole\(", ai_write_c)
    for_role = ""
    if for_role_m:
        end = ai_write_c.find("\n    }", for_role_m.start())
        for_role = ai_write_c[for_role_m.start(): end if end > 0 else len(ai_write_c)]
        c.scanned.append("AiWrite.kt::forRole")
    c.ok("解析到了 AiWrite.kt 的 forRole（单条过滤只在一处）", bool(for_role))
    n_filter = len(re.findall(r"role in it\.roles", for_role))
    # 不钉住会怎样：`forRole` 只过滤**一边**（比如只给货主那支加了 roles 判断）——
    # 于是 `roles = setOf(AiRole.SHIPPER)` 对派单员那一侧形同虚设，
    # 而单测/红线看动作块时全是对的（"声明对了、门没关"）。
    c.ok(f"forRole 的**两个方向**都按 roles 过滤（实测 {n_filter} 处，应为 2）", n_filter == 2, f"实际 {n_filter}")
    c.present("forRole 认得出派单员这一支", for_role, r"AiRole\.DISPATCHER ->")
    c.present("forRole 认得出货主这一支（走白名单）", for_role, r"AiRole\.SHIPPER ->[\s\S]{0,200}?SHIPPER_ACTIONS")
    whitelist_m = re.search(r"SHIPPER_ACTIONS[^\n]*=\s*setOf\(([\s\S]*?)\n    \)", ai_write_c)
    whitelist = whitelist_m.group(1) if whitelist_m else ""
    c.ok("解析到了 AiWrites.SHIPPER_ACTIONS 白名单（解析失效时下面四条会全绿）", bool(whitelist))
    for const, in_list in (
        ("RETURN_REQUEST_APPLY", True),
        ("RETURN_REQUEST_WITHDRAW", True),
        ("RETURN_REQUEST_REJECT", False),
        ("RETURN_REQUEST_FULFILL", False),
    ):
        # 不钉住会怎样：`SHIPPER_ACTIONS` 是"加进去才有"的白名单（fail-closed 的那一半）。
        # 把派单员那两条加进去 ＝ 货主 AI 里冒出两个必然 403 的动作；
        # 把货主那两条漏掉 ＝ 用户拍板的"货主的 AI 可以代替货主申请退货"没落地
        # （apply 与 withdraw 必须成对：数量是锁死的，"改数量"的唯一路径就是撤回重提）。
        in_whitelist = re.search(rf"^\s+{const},\s*$", whitelist, re.M) is not None
        c.ok(
            f"货主白名单{'包含' if in_list else '不包含'} {const}",
            in_whitelist == in_list,
            "看 `AiWrites.SHIPPER_ACTIONS`",
        )

    # ---------------------------------------------------------------- 8b. 客户端列表内核
    print("\n== 8b. 客户端：两端（派单员待办 / 货主我的申请）共用一个列表内核 ==")
    # 两个页面原来各写了约 90 行**逐字相同**的东西（档位 / 加载 / 定位 / 实时刷新）。
    # 它们不是样式而是**规则**，抄两份的后果很具体：四条里有一条没跟上，就只有一个角色会犯，
    # 另一个不会 —— 而"点消息进来定位不到那一条"这种毛病，用户只会觉得"这个 App 时灵时不灵"。
    core_vm = read(ANDROID / "ui/common/ReturnRequestsViewModel.kt")
    c.present("列表内核只有一处（抽象基类）", core_vm, r"abstract class ReturnRequestsViewModel\(")
    c.present(
        "带定位进来先用「全部」档拉（构造时）—— 否则已办完的那条在「待处理」里必然找不到",
        core_vm,
        r"if \(initialFocusRequestId > 0L\) tab = tabAllIndex",
    )
    c.present(
        "VM 被复用时再次定位也切到「全部」档（applyFocus）",
        core_vm,
        r"if \(requestId > 0L\) tab = tabAllIndex",
    )
    # 定位规则（排到最前 + found 判据）只许内核调 —— 两个子类各调一次就是两份实现。
    # ⚠️ 用后行断言排除**函数定义**那一行（`fun focusReturnRequestFirst(`）：
    #    第一版把定义文件也算成"调用者"，当场误报（同一个坑在 `_check_single_source.py` 栽过一次）。
    focus_callers = sorted(
        p.relative_to(ANDROID).as_posix()
        for p in (ANDROID / "ui").rglob("*.kt")
        if re.search(r"(?<!fun )focusReturnRequestFirst\(", read(p))
    )
    c.ok(
        "定位规则只有内核在调（两个子类不许自己再排一次）",
        focus_callers == ["ui/common/ReturnRequestsViewModel.kt"],
        f"实际调用它的文件：{focus_callers}",
    )
    # 消费点**从源码算**：两个角色的 VM 必须真的继承它（只钉"基类存在"会被绕开）
    subclasses = sorted(
        p.relative_to(ANDROID).as_posix()
        for p in (ANDROID / "ui").rglob("*.kt")
        if ": ReturnRequestsViewModel(" in read(p)
    )
    c.ok(
        f"两个角色的 VM 都继承同一个内核（从源码算到 {len(subclasses)} 个）",
        len(subclasses) >= 2,
        f"子类：{subclasses}",
    )

    # ---------------------------------------------------------------- 8c. 客户端的页面也共用
    print("\n== 8c. 客户端：两端页面上重复的那三小块也只许一处 ==")
    # 上一轮收的是 VM 内核；这一轮收的是页面上的三段**逐字相同**的块：
    # 档位标签、定位失败那一行说明、行首（定位徽章 + 订单号 + 状态）。
    # 它们各自都有"必须两端一致"的理由，而且抄错的后果都很安静（标错档、徽章只有一边有）。
    rr_ui = read(ANDROID / "ui/common/ReturnRequestsUi.kt")
    c.present(
        "档位标签只有一处，且按 **key** 判而不是按下标（两页档位顺序相反）",
        rr_ui,
        r'if \(t\.key == "pending" && pendingCount > 0\)',
    )
    c.present("定位失败的说明只有一处", rr_ui, r"fun ReturnRequestsFocusNotice\(")
    c.present("行首（定位徽章 + 订单号 + 状态徽章）只有一处", rr_ui, r"fun ReturnRequestsHeading\(")
    # 消费点**从源码算**：谁的行里画 `req.linesSummary`（两条退货申请列表），谁就必须用共用行首
    rr_screens = sorted(
        p.relative_to(ANDROID).as_posix()
        for p in (ANDROID / "ui").rglob("*ReturnRequestsScreen.kt")
        if "req.linesSummary" in read(p)
    )
    c.ok(
        f"两端的行首都用共用组件（从源码算到 {len(rr_screens)} 个页面）",
        len(rr_screens) >= 2
        and all("ReturnRequestsHeading(" in read(ANDROID / s) for s in rr_screens),
        f"页面={rr_screens}，"
        f"没用的={[s for s in rr_screens if 'ReturnRequestsHeading(' not in read(ANDROID / s)]}",
    )
    own = [
        s
        for s in rr_screens
        if "pendingCount > 0" in read(ANDROID / s) or "vm.focusNotice?.let" in read(ANDROID / s)
    ]
    c.ok("两端页面不许自己算档位标签、也不许自己画那一行定位说明", not own, f"自己写了的：{own}")
    badge_dup = [
        p.relative_to(ANDROID).as_posix()
        for p in (ANDROID / "ui").rglob("*.kt")
        if "消息里点进来的这一条" in read(p)
    ]
    c.ok(
        "定位徽章的文案只许在一个文件里（抄一份就会两边各说各的）",
        badge_dup == ["ui/common/ReturnRequestsUi.kt"],
        f"出现在 {badge_dup}",
    )

    # ---------------------------------------------------------------- 9. 反空转
    print("\n== 9. 反空转（清单被改坏时必须先喊，不许安静地全绿）==")
    c.ok(
        f"扫到了 {len(c.scanned)} 个函数/块（下限 {MIN_FUNCTIONS_SCANNED}）",
        len(c.scanned) >= MIN_FUNCTIONS_SCANNED,
        f"实际 {len(c.scanned)}：{c.scanned}",
    )
    c.ok(f"解析到的端点 {len([n for n in endpoints if sigs[n]])} 个（下限 {MIN_ENDPOINTS}）",
         len([n for n in endpoints if sigs[n]]) >= MIN_ENDPOINTS)
    total = c.passes + len(c.fails) + 1  # +1 = 本条自己
    c.ok(f"判据总数 {total} 条（下限 {MIN_ASSERTIONS}）", total >= MIN_ASSERTIONS, f"实际 {total}")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(
        f"✅ 全部 {c.passes} 项通过：退货申请只动申请单、执行只走一个入口、"
        f"数量锁死、两种权限分开、消息双向、直连退货自动关闭那张申请（顺序在 commit 之前）。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
