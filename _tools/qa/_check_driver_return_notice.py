# -*- coding: utf-8 -*-
"""红线：退货办完必须让经手那张单的司机知道（BUG-0005 / E2E 走查 P27，2026-10-03）。

## 这条是怎么来的
2026-10-03 的 E2E 走查（`_tmp/E2E测试报告.md:98-101`）逐字写着：
「货主端与派单员端都收到了「退货已办理」消息；**司机端一条都没有**。
司机端订单详情仍是 已送达，流转记录里没有退货/红冲一行。」

## 为什么必须有机器的判据
这一条修的是「一条消息 + 一行时间 + 一档状态」，没有任何类型能拦住它被改回去：
- 事件类型 `returns.order_returned` 少一处登记，发件箱那一支就永远不会命中 —— 而代码照样编译、
  全量单测照样全绿（谁也没有断言「司机收到了」）。
- 幂等键去掉 `event_id` 之后**编译通过、第一条消息也发得出去**，只有「同一张单退第二次」
  才会静默吞掉（部分退货累加是常态，走查里那种单就退了两次）。
- 正文那句口径（「账单不会被退货改动」）换成「这一单的运费照结」同样能编译 —— 而后端
  `backend/app/api/v1/driver_bills.py:66-67` 把「整单退货的单司机还算不算」明确挂在**待拍板**上，
  ⛔ 不许由一条消息替它下结论。
- 司机端那两处更隐蔽：整单退完的单状态是 `RETURNED`，「已完成」那一档只查 `DELIVERED` 时
  这张单**从列表里凭空消失** —— 页面不报错、列表也不空（其它单还在），只有当事人翻不到那张单。

所以判据只能盯**结构**：事件在唯一入口里恰好一份、发件箱有聚合根映射、派发表有那一支、
推送函数带 `event_id`、消息发布者的幂等键含事件编号、正文里不许出现替代产品决策的说法、
司机端「已完成」的取数与探测**同源**、退货那一行夹在「送达」与「撤销」之间、
司机列表用的共享卡片认识 `RETURNED`（否则行上直接印原始码）。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。它全是「少一行 / 换一句话 / 换一个状态字面量」：
`Notification` 表结构没变、`OrderCard` 没变、`TimeRow` 没变、`return_order` 的回参也没变，
所以 Pydantic 出参、Kotlin 类型、既有单测在这几处**完全一样**，编译器与单测都不会有一句反对。
只能扫源码结构与文档登记 —— 运行时那一头交给
`_tools/qa/_reverse_verify_driver_return_notice.py`（11 条按条注入破坏）与 2026-10-03 模拟器 5558
（司机端 消息中心 / 订单详情·流转记录 / 已完成列表）的实测。
本判据只读源码与文档（read / code），不连库、不 import 后端、不跑迁移、不调用模型。

用法：python _tools/qa/_check_driver_return_notice.py
     python _tools/qa/_check_driver_return_notice.py --list   # 只列它到底在查什么
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
# 注释剥离**只有一份实现**（那个状态机是为 "image/*" 这种字符串写的，抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

#: 事件链路五处后端生产文件
RETURN = ROOT / "backend/app/services/order_return.py"
OUTBOX = ROOT / "backend/app/core/outbox.py"
MAIN = ROOT / "backend/app/main.py"
PUSH = ROOT / "backend/app/services/push_events.py"
CENTER = ROOT / "backend/app/services/message_center.py"
#: 两条后端用例（一条直连退货、一条申请办完退两次）
T_RETURN = ROOT / "backend/tests/test_order_return.py"
T_REQUEST = ROOT / "backend/tests/test_return_request.py"
#: 客户端两处 + 共享徽章 + 两份治理文档
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
DRIVER_VM = AND / "ui/driver/DriverOrdersViewModel.kt"
DRIVER_SCREEN = AND / "ui/driver/DriverOrdersScreen.kt"
CHIP = AND / "ui/common/Components.kt"
R4_MAP = ROOT / "docs/R4_CORE_EXTENSION_MAP.md"
DOMAINS = ROOT / "docs/DOMAIN_BOUNDARIES.md"

REVERSE = "_tools/qa/_reverse_verify_driver_return_notice.py"

#: 扫到的界面文件数下限（防目录改名 / 搬走之后「一个文件都没扫到」也算过）
MIN_UI_FILES = 100
#: 扫到的后端模块数下限
MIN_BACKEND_FILES = 100

#: 半角双引号：源码里的字符串字面量定界符（**不能写成反斜杠转义**，见 _reverse_verify 的同类注释）
DQ = chr(34)

#: 新事件类型：退货**执行完了**
EVENT = "returns.order_returned"
#: 事件字面量在退货服务里的出现次数（入队那一行恰好一次）
ENQUEUE = DQ + EVENT + DQ
#: 入队调用的函数名（发件箱入口，唯一入口里恰好一次）
ENQ_CALL = "outbox.enqueue("
#: 发件箱派发表里那一支
BRANCH = "if event.event_type == " + DQ + EVENT + DQ
#: 聚合根映射
MAPPING = DQ + EVENT + DQ + ": " + DQ + "order_id" + DQ
#: 两个函数名
PUSH_FN = "push_order_returned_to_driver"
PUBLISH_FN = "publish_order_returned_to_driver"
#: 正文里那句成文口径（全库生产代码恰好一份）
TRUTH = "账单不会被退货改动"
#: ⛔ 不许替产品决策下结论的两种说法
FORBIDDEN = ("照结", "一定会结")
#: 司机端「已完成」那一档
FINISHED = "private val FINISHED_STATUSES: List<String> = listOf(" + DQ + "DELIVERED" + DQ + ", " + DQ + "RETURNED" + DQ + ")"
OLD_ELSE = "else listOf(" + DQ + "DELIVERED" + DQ + ")"
OLD_PROBE = "status = " + DQ + "DELIVERED" + DQ


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def code(p: Path) -> str:
    return strip_comments(read(p))


def hits(needle: str, sources: list[tuple[str, str]]) -> list[str]:
    """哪些文件里出现了这个字符串（用来问「全库是不是只有一份」）。"""
    return [name for name, src in sources if needle in src]


def window(src: str, needle: str, before: int, after: int) -> str:
    i = src.find(needle)
    if i < 0:
        return ""
    return src[max(0, i - before) : i + len(needle) + after]


def backend_sources() -> list[tuple[str, str]]:
    """生产代码全库（backend/app 下所有模块）—— 用来问「这句话/这个类型全库只有一份吗」。"""
    return [
        (q.relative_to(ROOT).as_posix(), q.read_text(encoding="utf-8", errors="replace"))
        for q in sorted((ROOT / "backend/app").rglob("*.py"))
    ]


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

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0

def main() -> int:
    if refuse_if_injecting("司机退货通知检查"):
        return 1

    c = Checker()
    print("退货要告诉经手那张单的司机（BUG-0005 / P27）：2026-10-03")

    kt_files = sorted(AND.rglob("*.kt"))
    ui_sources = [(q.relative_to(AND).as_posix(), code(q)) for q in kt_files]
    n_kt = len(kt_files)
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        n_kt >= MIN_UI_FILES,
        f"实际 {n_kt}",
    )
    be = backend_sources()
    n_be = len(be)
    c.ok(
        f"扫到的后端模块数 ≥ {MIN_BACKEND_FILES}（防 backend/app 改名后判据空转）",
        n_be >= MIN_BACKEND_FILES,
        f"实际 {n_be}",
    )

    # ---- 0. 这一条链路碰到的文件都在 ----
    miss_be = [
        q.relative_to(ROOT).as_posix()
        for q in (RETURN, OUTBOX, MAIN, PUSH, CENTER, T_RETURN, T_REQUEST)
        if not q.exists()
    ]
    c.ok("五处后端生产文件与两条用例都在（事件从入口到消息一条不缺）", not miss_be, "缺：" + "、".join(miss_be))
    miss_kt = [
        q.relative_to(ROOT).as_posix()
        for q in (DETAIL, DRIVER_VM, DRIVER_SCREEN, CHIP, R4_MAP, DOMAINS)
        if not q.exists()
    ]
    c.ok("两处客户端文件 + 共享徽章组件 + 两份治理文档都在", not miss_kt, "缺：" + "、".join(miss_kt))

    ret = read(RETURN)
    box = read(OUTBOX)
    mn = read(MAIN)
    ps = read(PUSH)
    ce = read(CENTER)

    # ---- 1. 事件落在唯一入口里 ----
    print()
    print("== 1. 事件落在退货的唯一入口里 ==")
    n_enq = ret.count(ENQUEUE)
    c.ok(
        f"事件在唯一入口 return_order 里恰好入队一次（{DQ}{EVENT}{DQ}）",
        n_enq == 1,
        f"实际 {n_enq} 处",
    )
    n_call = ret.count(ENQ_CALL)
    c.ok(
        "入队走的是发件箱那一个入口（outbox.enqueue 恰好一次）",
        n_call == 1,
        f"实际 {n_call} 处",
    )
    i_fn = ret.find("def return_order(")
    i_enq = ret.find(ENQUEUE)
    c.ok(
        "入队那一行**在 return_order 函数体里**（搬到模块顶层或别的函数就不再是唯一入口）",
        0 <= i_fn < i_enq,
        f"def 下标 {i_fn} / 入队下标 {i_enq}",
    )
    # before 要够长：调用点写成多行（outbox.enqueue( / db, / 事件名, / {...}），事件名前面的调用要一起看
    w_enq = window(ret, ENQUEUE, 400, 480)
    c.ok(
        "事件名是交给 outbox.enqueue 的那一个参数（不是躺在注释里的一句话）",
        ENQ_CALL in w_enq,
        "事件名前后 400 字里找不到 outbox.enqueue(",
    )
    keys = ("order_id", "returned_amount", "refund_amount", "fully_returned", "items")
    miss_k = [k for k in keys if k not in w_enq]
    c.ok("负载带的是一次退货自己的既成事实（五个键一个不缺）", not miss_k, "缺：" + "、".join(miss_k))
    i_log = ret.find("write_log(", i_fn)
    c.ok(
        "入队与业务写在同一个函数、同一段顺序里（入队排在 write_log 之前）",
        0 < i_enq < i_log,
        f"入队 {i_enq} / write_log {i_log}",
    )
    c.ok(
        "退货服务自己不直接推消息（推送出口只有发件箱派发表那一处）",
        "emit_notification(" not in ret and "emit_realtime(" not in ret and "push_events." not in ret,
        "order_return.py 里出现了 emit_notification / emit_realtime / push_events.",
    )

    # ---- 2. 发件箱：聚合根映射 ----
    print()
    print("== 2. 发件箱里的聚合根映射 ==")
    n_map = box.count(MAPPING)
    c.ok(
        "发件箱声明了这个事件的聚合根映射（聚合根是那张订单 —— 直连退货没有申请单）",
        n_map == 1,
        f"实际 {n_map} 处",
    )
    i_tab = box.find("AGGREGATE_KEY")
    i_map = box.find(MAPPING)
    c.ok(
        "这条映射写在 AGGREGATE_KEY 表里（写在表外等于没登记）",
        0 <= i_tab < i_map,
        f"表下标 {i_tab} / 映射下标 {i_map}",
    )

    # ---- 3. 派发表里的那一支 ----
    print()
    print("== 3. 发件箱派发表里的那一支 ==")
    n_br = mn.count(BRANCH)
    c.ok(f"派发表里有 {DQ}{EVENT}{DQ} 那一支", n_br == 1, f"实际 {n_br} 处")
    w_br = window(mn, BRANCH, 0, 700)
    c.ok(
        "那一支调用推送函数（事件驱动，不在端点里顺手发）",
        "push_events." + PUSH_FN + "(" in w_br,
        "支线里找不到 push_events." + PUSH_FN + "(",
    )
    c.ok(
        "那一支把发件箱那一行的编号传下去（幂等的来源）",
        "event_id=int(event.id" in w_br,
        "支线里没有 event_id=int(event.id ...)",
    )
    c.ok(
        "那一支写完就 return（不落到后面支线，一条退货不发两条消息）",
        "return" in w_br,
        "支线里没有 return",
    )
    c.ok(
        "邻居支线还在（别为了加一支把 notifications.created 顶掉）",
        "notifications.created" in mn,
        "main.py 里找不到 notifications.created",
    )

    # ---- 4. 推送函数 ----
    print()
    print("== 4. 推送函数（事件 → 消息层） ==")
    n_def = ps.count("async def " + PUSH_FN + "(")
    c.ok(f"推送函数 {PUSH_FN} 恰好定义一次", n_def == 1, f"实际 {n_def} 处")
    w_push = window(ps, "async def " + PUSH_FN, 0, 1400)
    c.ok(
        "参数表里 event_id 是**关键字参数**（调用点传错位置会当场报错）",
        "*," in w_push and "event_id: int" in w_push,
        "参数表里没有 *, / event_id: int",
    )
    c.ok(
        "自己开关会话（SessionLocal + finally close）",
        "SessionLocal()" in w_push and "finally:" in w_push and ".close()" in w_push,
        "函数体里没有 SessionLocal() / finally / close()",
    )
    c.ok(
        "只把既成事实转交给消息层（不在这一层重算金额）",
        "message_center." + PUBLISH_FN + "(" in w_push,
        "函数体里找不到 message_center." + PUBLISH_FN + "(",
    )
    callers = sorted(hits(PUSH_FN + "(", be))
    want = sorted(["backend/app/main.py", "backend/app/services/push_events.py"])
    c.ok(
        "这个推送函数只被发件箱派发表调用（定义 + 调用，两处）",
        callers == want,
        "实际出现在：" + "、".join(callers),
    )

    # ---- 5. 消息发布者 ----
    print()
    print("== 5. 消息发布者（幂等 / 口径 / 出口） ==")
    n_pub = ce.count("async def " + PUBLISH_FN + "(")
    c.ok(f"消息发布者 {PUBLISH_FN} 恰好定义一次", n_pub == 1, f"实际 {n_pub} 处")
    w_c = window(ce, "async def " + PUBLISH_FN + "(", 0, 3600)
    c.ok(
        "收件人是那台单的司机，司机或账号不存在时安静退出（不给不存在的收件人写信）",
        "order.driver_id is None" in w_c and "db.get(User, order.driver_id) is None" in w_c,
        "函数里没有 driver_id is None / User 存在性那两道闸",
    )
    c.ok(
        "幂等键带**发件箱那一行的编号**（同一张单退第二次不会被吞掉）",
        "str(event_id)" in w_c and "idem_key" in w_c,
        "幂等键里没有 str(event_id)",
    )
    c.ok(
        "幂等键前缀是 order.returned（与按单一次的消息区分开）",
        DQ + "order.returned" + DQ in w_c,
        "函数里找不到 order.returned 这个 type",
    )
    # ⚠️ 只看整个函数窗口是不够的：这句口径在**它的 docstring 里**也出现（说明为什么要这么写），
    #    于是把正文那句换掉之后，扫全函数的写法照样绿 —— 必须钉在 content=( 那一段上。
    w_txt = window(w_c, "content=(", 0, 520)
    c.ok(
        "正文里那句成文口径在（不是只写在 docstring 里）",
        TRUTH in w_txt,
        "content=( 那一段里找不到「" + TRUTH + "」",
    )
    n_truth = len(hits(TRUTH, be))
    c.ok(
        "那句口径在生产代码里**只有一份**（抄到第二处迟早两边说法不一样）",
        hits(TRUTH, be) == ["backend/app/services/message_center.py"],
        "实际出现在：" + "、".join(hits(TRUTH, be)) + f"（{n_truth} 处）",
    )
    bad = [x for x in FORBIDDEN if x in w_txt]
    c.ok(
        "⛔ 正文里不许出现「运费照结」这类替产品决策下结论的说法",
        not bad,
        "正文出现了：" + "、".join(bad),
    )
    c.ok(
        "两个方向都说得清（整单退完 / 部分退货）",
        "整单退完" in w_c and "部分退货" in w_c,
        "函数里缺「整单退完」或「部分退货」",
    )
    c.ok(
        "消息真的走到两个出口（站内信 + 实时推送）",
        "emit_notification(" in w_c and "emit_realtime(" in w_c,
        "函数里缺 emit_notification / emit_realtime",
    )
    c.ok("标题在（司机端消息中心按 type + 标题展示）", "订单被退货了" in w_c, "函数里找不到标题")

    # ---- 6. 两条用例 ----
    print()
    print("== 6. 两条后端用例（直连 / 退两次） ==")
    t1 = read(T_RETURN)
    t2 = read(T_REQUEST)
    c.ok(
        "直连退货那条用例在（POST /orders/{id}/return 这条链路）",
        "def test_direct_return_tells_the_driver(" in t1,
        "找不到那条用例",
    )
    c.ok(
        "它断言司机收到的类型与那句口径",
        DQ + "order.returned" + DQ in t1 and TRUTH in t1,
        "用例里缺 order.returned / 口径那句",
    )
    c.ok(
        "申请办完退两次那条用例在（钉住每条退货都发一条）",
        "def test_return_notice_reaches_the_driver_and_repeats_per_return(" in t2,
        "找不到那条用例",
    )
    c.ok(
        "它用**增量计数**断言两次各一条（测试库共享，绝对计数必红）",
        ("before + 1" in t2 or "before + 2" in t2) and "部分退货" in t2 and "整单退完" in t2,
        "用例里缺增量计数 / 两个方向的断言",
    )
    c.ok(
        "payload 也断言了（结构化字段不能只写在正文里）",
        ".payload or {}" in t1 and ".payload or {}" in t2 and "fully_returned" in t2,
        "用例里没有 payload 断言",
    )

    # ---- 7. 客户端两处 ----
    print()
    print("== 7. 客户端：流转记录那一行 + 已完成那一档 ==")
    detail = code(DETAIL)
    vm = code(DRIVER_VM)
    screen = code(DRIVER_SCREEN)
    chip = code(CHIP)
    row = "order.returnedAt?.let { TimeRow(" + DQ + "退货" + DQ + ", it) }"
    n_row = detail.count(row)
    c.ok(
        f"订单详情 · 流转记录里「退货」那一行在（时间行恰好一份）",
        n_row == 1,
        f"实际 {n_row} 处",
    )
    i_del = detail.find("TimeRow(" + DQ + "送达" + DQ)
    i_row = detail.find("TimeRow(" + DQ + "退货" + DQ)
    i_can = detail.find("TimeRow(" + DQ + "撤销" + DQ)
    c.ok(
        "那一行夹在「送达」与「撤销」之间（按时间读下来才是流水）",
        0 < i_del < i_row < i_can,
        f"下标 送达 {i_del} / 退货 {i_row} / 撤销 {i_can}",
    )
    c.ok(
        "它就在「流转记录」那张卡里（另起一节等于没人看）",
        "流转记录" in detail,
        "OrderDetailScreen.kt 里找不到「流转记录」",
    )
    n_fin = vm.count(FINISHED)
    c.ok(
        "「已完成这一档」= 已送达 + 已退货（常量恰好一份）",
        n_fin == 1,
        f"实际 {n_fin} 处",
    )
    c.ok(
        "「已完成」的探测与取数**同源**（同一个 FINISHED_STATUSES）",
        "FINISHED_STATUSES.any" in vm and "else FINISHED_STATUSES" in vm,
        "探测或取数里没有用 FINISHED_STATUSES",
    )
    old = [x for x in (OLD_ELSE, OLD_PROBE) if x in vm]
    c.ok(
        "老的两处写法全清（只查 DELIVERED 的话整单退货的单从列表里消失）",
        not old,
        "还在：" + "、".join(old),
    )
    c.ok(
        "司机列表用的共享卡片认识 RETURNED（否则行上直接印出原始码）",
        (DQ + "RETURNED" + DQ) in chip and "已退货" in window(chip, DQ + "RETURNED" + DQ, 0, 400),
        "Components.kt 里 RETURNED 没有中文名",
    )
    c.ok(
        "司机列表确实用共享卡片画行（徽章那一格才有人用）",
        "OrderCard(" in screen and "driverMode = true" in screen,
        "DriverOrdersScreen.kt 里没有 OrderCard / driverMode",
    )

    # ---- 8. 两份治理文档 ----
    print()
    print("== 8. 治理文档登记 ==")
    r4 = read(R4_MAP)
    dom = read(DOMAINS)
    c.ok(
        "docs/R4_CORE_EXTENSION_MAP.md 登记了第 19 个事件",
        EVENT in r4 and "19 个事件" in r4,
        "文档里没有这个事件 / 事件数没改成 19",
    )
    # ⚠️ 不能用「源码里有这个子串」判：在事件名后面接个后缀（returns.order_returned_GONE）
    #    子串照样在，登记其实已经废了 —— 必须看**退货域 events 那一行以它结尾**。
    i_ev = dom.find("events: returns.requested")
    ev_line = dom[i_ev:].splitlines()[0] if i_ev >= 0 else ""
    c.ok(
        "docs/DOMAIN_BOUNDARIES.md 的退货域 events 那一行以这个事件结尾",
        ev_line.rstrip().endswith(", " + EVENT),
        "实际那一行：" + ev_line.strip()[:220],
    )

    # ---- 9. 配对：反向验证 + 本文自己的边界理由 ----
    print()
    print("== 9. 配对 ==")
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), "找不到 " + REVERSE)
    c.ok(
        "本判据写了边界理由（_check_r3_constraints.py 的检查器预算闸要求 R4-BOUNDARY-JUSTIFICATION）",
        "R4-BOUNDARY-JUSTIFICATION:" in read(Path(__file__)),
        "模块 docstring 里没有 R4-BOUNDARY-JUSTIFICATION 段",
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · 事件落在退货的唯一入口 return_order 里，负载只带既成事实（五个键）");
        print("     · 发件箱有聚合根映射（order_id）+ 派发表有那一支，且传 event_id 下去");
        print("     · 推送函数带关键字 event_id、自己开关会话、只被派发表调用");
        print("     · 消息发布者：司机不存在就退出、幂等键含 event_id、正文两个方向都说得清");
        print("     · ⛔ 正文不许出现「运费照结」这类替待拍板决策下结论的说法；口径句全库一份");
        print("     · 两条用例：直连退货 + 申请办完退两次（增量计数）");
        print("     · 客户端：订单详情流转记录有「退货」一行（夹在送达与撤销之间）");
        print("     · 客户端：司机「已完成」那一档 = 已送达 + 已退货，探测与取数同源");
        print("     · 两份治理文档登记 + 反向验证脚本在 + 本文自己的边界理由在");

    return c.report("退货要告诉经手那张单的司机（BUG-0005 / P27）")


if __name__ == "__main__":
    sys.exit(main())


