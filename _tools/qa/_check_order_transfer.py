# -*- coding: utf-8 -*-
"""红线：派单期的**跨货主转货**（CHG-0042）—— 货归谁变了，状态机 / 钱 / 审计三件事一件都不许跟着乱。

## 由来（用户 2026-10-05 逐字，语音转写）
「假如 A 老板下了 50 单货、B 老板下了 40 单货，然后一起由一个司机直接发车，
但 B 老板非常着急，所以派单员决定将 A 的 50 单货中的 30 单货和 40 单货合并在一起变成 70 单货给 B 老板，
有时候可能是全部货都直接给这个老板；也有时候会把 A 的 50 单货拆成 20 单和 30 单，另外 30 单给另一个老板 C。」

## 为什么必须有一条红线盯着它
「转货」在界面上只是把几行货挪给另一个货主，但它同时动五件**各自都对、合起来会错**的事：
1. **货归谁**：账本行按 order.shipper_id 落账（accounting_service）、通知按货主发、送货单写货主名 ——
   挪错一步，这三处会**一致地**错下去，谁都不会报错；
2. **状态机**：源单被搬空时必须像被撤销一样消失（CANCELLED），而状态写入**只许**发生在 services/order_flow.py。
   图省事在命令层写一句 order.status = CANCELLED，界面、单测、日志全绿，状态机却从此有了第二个入口；
3. **钱**：转货不该碰钱（没结账的单钱还没落账，源单的钱跟着明细走）。顺手把 payment_method / 挂账单位抄过去，
   两边的账都会多出一个谁也没要求过的结论；
4. **在途语义**：司机已接单 = 他认下的是「这一单」，把货全搬走等于撤单，而 cancel_pending 的门里没有 ACCEPTED。
   这条路必须关掉（先撤回派单再转），否则司机手机上那张单会莫名其妙地空掉。
5. **库存预占**：派过单的单已经替这批货占着库存（auto_stock_out 写 RESERVED 流水），货挪走之后那笔占用
   必须跟着走或放掉。留着就是「一张单永久占着已经不存在的货」，**总账还是平的**，所以对账看不出来 ——
   只有按单一条一条看预占才会发现（真实库探针 _tmp/_probe_chg0042_transfer.py 实测就是这个形状）。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。被查的形状全是「少一句 / 抄一格 / 挪一行」：
状态写在命令层、钱字段顺手抄、整单转空对已接单放行、并单前不锁目标单、挡板少列一个终态 ——
它们在类型上全都合法，跑起来也全都成功（没有一个会抛异常），只有库里的结果不同。
边界那一半已经先做了（状态写入收在 order_flow、金额只由后端算、客户端只报行 id + 数量），
但「这一处有没有绕过去」只存在于**调用点与字面量**，所以判据只能扫结构与取值。
运行时那一头交给 _tools/qa/_reverse_verify_order_transfer.py（逐条注入破坏，改坏 → 必须红）。

## 判据（清单全部自己算；路径写错会先在「读到几个文件」那条报红）
1. 命令注册表：order.transfer 一条，域=order、实现=commands.order:transfer_lines、能力点=ORDER_EDIT、
   from_states=在途三态、to_state 空串、事件与副作用与实现里真发的一致。
2. 实现：挡板逐字挡掉三个终态、from_states 恰好是全集减它、锁早于第一处状态比较、整单搬空借 cancel_pending、
   已接单不许整单转空、不写 order.status、不碰钱、只 commit 一次、并单前给目标单加锁、
   两行 ORDER_TRANSFER 审计、四个发件箱事件、预占各重算一次、
   且对账之前**先落盘 + 让明细集合失效**（autoflush=False 的会话读的是内存缓存）、
   内部备注写在 cancel_pending / 重算**之后**、_put_line 的调用与定义同口径。
3. 端点：POST /orders/{id}/transfer、权限点 ORDER_DISPATCH（不新建）、CommandError 原样透出、
   order_flow 的 ValueError 翻 400、路由自己不 commit。
4. 词汇表与地图：ORDER_TRANSFER 动作码、工具链认领、领域地图里有这条命令、生成物已带上它。
5. Android：端点 / DTO 逐字段、TRANSFERABLE 与后端挡板互补、入口只有一处且挂在门上、
   数量控件是共用的那一份且上限夹在本行现有数量、VM 先校验后请求、成功后按回参重拉。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   python _tools/qa/_reverse_verify_order_transfer.py

用法：python _tools/qa/_check_order_transfer.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 剥 Kotlin 注释的实现只此一份（复用兄弟红线，不抄第二份）。
from _check_pagination_wiring import strip_comments  # noqa: E402
#: 剥 Python 注释 / 文档字符串（换成等长空格、保留行号）—— 下面有几处**顺序**比较要靠它。
from _check_single_source import code_only  # noqa: E402
#: 失败行 / 章节标题的形状只此一份（房规）：失败行是   [!!]   <标题> ——
#: _reverse_verify_*.py 正是拿这个前缀去认「这一条被判据抓住了」，自己另写一种就等于反向验证静默空过。
from _check_hints import Checker  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

CMD = BACKEND / "app/commands/order.py"
REG = BACKEND / "app/commands/registry.py"
API = BACKEND / "app/api/v1/orders_assignment.py"
ENUMS = BACKEND / "app/models/enums.py"
COV = BACKEND / "app/core/capability_audit_coverage.py"
SCHEMA = BACKEND / "app/schemas/order.py"
MAP = ROOT / "docs/DOMAIN_BOUNDARIES.md"
SNAP = ROOT / "docs/CAPABILITY_SNAPSHOT.json"
COVMD = ROOT / "docs/CAPABILITY_AUDIT_COVERAGE.md"
APIS = ANDROID / "data/remote/api/Apis.kt"
DTO = ANDROID / "data/remote/dto/Dtos.kt"
REPO = ANDROID / "data/repo/AppRepository.kt"
STATUS = ANDROID / "core/OrderStatusModel.kt"
VM = ANDROID / "ui/order/OrderDetailViewModel.kt"
SCREEN = ANDROID / "ui/order/OrderDetailScreen.kt"
SHEET = ANDROID / "ui/order/OrderTransferSheet.kt"

#: 被点名的文件都必须在（少一个就先喊，不静默空转）。
REQUIRED = [CMD, REG, API, ENUMS, COV, SCHEMA, MAP, SNAP, COVMD, APIS, DTO, REPO, STATUS, VM, SCREEN, SHEET]

#: 在途三态：转货只在这三个状态上开放（＝挡板的补集）。
IN_TRAFFIC = ["PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"]
#: 挡板挡掉的三个终态。
BLOCKED = ["DELIVERED", "CANCELLED", "RETURNED"]
#: 实现里真发的四个事件（与注册表声明的逐字比）。
FOUR_EVENTS = ["orders.created", "orders.edited", "orders.cancelled", "orders.pending_pool_changed"]
#: 转货不许碰的钱字段（一眼能看出「这一处有没有顺手抄一格」）。
MONEY_FIELDS = ["payment_method", "arrears_unit", "collect_cash"]

Q = chr(34)
NL = chr(10)

C = Checker()


def ok(label: str, cond: bool, detail: str = "") -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def py(path: Path) -> str:
    """后端文件：注释与文档字符串已剥（保留行号）。"""
    return code_only(path.read_text(encoding="utf-8")) if path.is_file() else ""


def kt(path: Path) -> str:
    """Kotlin 文件：注释已剥。"""
    return strip_comments(path.read_text(encoding="utf-8")) if path.is_file() else ""


def raw(path: Path) -> str:
    """原文（判据要看着注释里的原话时用）。"""
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def norm(src: str) -> str:
    """空白折叠成单空格 —— 注入式反向验证要按**字面量**认锚点，比较前先归一。"""
    return " ".join(src.split())


def items(text: str) -> list[str]:
    """(A, B, C) 里的名字，按原顺序取出来。"""
    return [p.strip().strip(Q) for p in text.split(",") if p.strip()]


def field(spec: str, key: str) -> str:
    """CommandSpec 里某一格的值（元组取括号里，字符串取引号里）。"""
    i = spec.find(key + "=(")
    if i >= 0:
        j = spec.find(")", i)
        return spec[i + len(key) + 2 : (j if j > 0 else len(spec))]
    i = spec.find(key + "=" + Q)
    if i >= 0:
        j = spec.find(Q, i + len(key) + 2)
        return spec[i + len(key) + 2 : (j if j > 0 else len(spec))]
    return ""


def enqueued(src: str) -> set[str]:
    """源码里真发出去的事件名（只认 outbox.enqueue(db, 后面那个字面量）。"""
    out: set[str] = set()
    for part in src.split("outbox.enqueue(db, ")[1:]:
        p = part.lstrip()
        if p.startswith(Q):
            out.add(p[1:].split(Q)[0])
    return out


def enum_members(src: str, cls: str) -> list[str]:
    """某个枚举类的成员名（按声明顺序）。"""
    i = src.find("class " + cls)
    if i < 0:
        return []
    j = src.find(NL + "class ", i + 5)
    block = src[i : (j if j > 0 else len(src))]
    out: list[str] = []
    for line in block.splitlines():
        t = line.strip()
        if t.startswith("#") or "=" not in t:
            continue
        name = t.split("=")[0].strip()
        if name.isupper() and name.replace("_", "").isalpha():
            out.append(name)
    return out


def kt_member(src: str, name: str) -> str:
    """Kotlin 某个成员函数的源码段（到下一个成员为止）。空串 = 找不到。"""
    i = src.find("fun " + name + "(")
    if i < 0:
        return ""
    best = len(src)
    for marker in (NL + "    fun ", NL + "    private fun ", NL + "    override fun ", NL + "    init {"):
        j = src.find(marker, i + 5)
        if j > 0:
            best = min(best, j)
    return src[i:best]


def main() -> int:
    cmd = py(CMD)
    cmdraw = raw(CMD)
    reg = py(REG)
    api = py(API)
    enums = py(ENUMS)
    cov = py(COV)
    schema = py(SCHEMA)
    mp = raw(MAP)
    snap = raw(SNAP) + raw(COVMD)
    apis = kt(APIS)
    dto = kt(DTO)
    repo = kt(REPO)
    status = kt(STATUS)
    vm = kt(VM)
    screen = kt(SCREEN)
    sheet = kt(SHEET)

    tc = "@traced_command(" + Q + "order.transfer" + Q + ")"
    ti = cmd.find(tc)
    transfer = cmd[ti:] if ti >= 0 else ""
    #: 转货那一整块（助手 + 命令函数）：构造期状态、单号、钱字段这些**只出现在助手里**的东西要在这一层看。
    blk = cmd[cmd.find("IN_TRAFFIC_STATUSES") :] if "IN_TRAFFIC_STATUSES" in cmd else ""
    i = reg.find("name=" + Q + "order.transfer" + Q)
    spec = ""
    if i >= 0:
        j = reg.find(NL + "    ),", i)
        spec = reg[i : (j if j > 0 else i + 2000)]
    ep = ""
    if api:
        i = api.find("@router.post(" + Q + "/{order_id}/transfer" + Q)
        if i >= 0:
            j = api.find("@router.", i + 10)
            ep = api[i : (j if j > 0 else len(api))]

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    section("0. 反空转（扫描规则被改坏时必须先喊）")
    missing = [p for p in REQUIRED if not p.is_file()]
    miss_txt = ", ".join(str(p) for p in missing)
    ok(f"被点名的 {len(REQUIRED)} 个文件都在", not missing, "缺：" + miss_txt)
    n_cmds = reg.count("CommandSpec(")
    ok(f"注册表里认到 {n_cmds} 条命令（下限 9）", n_cmds >= 9, "注册表是不是被搬走了？")
    ok(f"transfer_lines 段落 {len(transfer)} 字符（下限 3000）", len(transfer) > 3000, "锚点 " + tc + " 找不到了？")
    ok(f"转货代码块（助手 + 命令）{len(blk)} 字符（下限 4000）", len(blk) > 4000, "IN_TRAFFIC_STATUSES 这个常量找不到了？")
    ok(f"转货抽屉 {len(sheet)} 字符（下限 1500）", len(sheet) > 1500, "OrderTransferSheet.kt 是不是被删了？")
    ok(f"端点段落 {len(ep)} 字符（下限 200）", len(ep) > 200, "端点锚点 @router.post(/{order_id}/transfer) 找不到了？")

    # ── 1. 命令注册表 ────────────────────────────────────────────────────
    section("1. 命令注册表（order.transfer 一条，域=order）")
    ok("注册表里有 order.transfer，且只声明了一条", reg.count("name=" + Q + "order.transfer" + Q) == 1)
    ok("实现落在 commands.order:transfer_lines（订单域命令只许落 order_flow 或 commands.order）", field(spec, "impl") == "commands.order:transfer_lines", "impl=" + field(spec, "impl"))
    ok("域是 order", field(spec, "domain") == "order")
    ok("能力点是 ORDER_EDIT（与 order.edit / order.split 同一颗，不新建权限点）", items(field(spec, "capabilities")) == ["ORDER_EDIT"], "capabilities=" + field(spec, "capabilities"))
    ok("from_states 逐字是「待派单 / 已派单 / 已接单」", items(field(spec, "from_states")) == IN_TRAFFIC, "from_states=" + field(spec, "from_states"))
    ok("to_state 是空串（转货本身不改源单的状态）", ("to_state=" + Q + Q) in spec)
    ok("声明的四个事件与实现里真的 enqueue 的四个逐字一致", set(items(field(spec, "events"))) == enqueued(transfer) and len(enqueued(transfer)) == 4, "声明=" + str(sorted(items(field(spec, "events")))) + " 代码=" + str(sorted(enqueued(transfer))))
    ok("声明的副作用是 operation_logs + inventory_movements", items(field(spec, "effects")) == ["operation_logs", "inventory_movements"], "effects=" + field(spec, "effects"))
    ok("why 里点名「借 cancel_pending 作废」（读者要能一眼看出状态写入仍在 order_flow）", "cancel_pending" in spec and "order_flow" in spec)

    # ── 2. 实现 ──────────────────────────────────────────────────────────
    section("2. 实现（commands/order.py::transfer_lines）")
    ok("transfer_lines 带 @traced_command(order.transfer)（命令层自己的 command_id）", ti >= 0 and transfer.find("def transfer_lines(") > 0)
    ok("挡板逐字挡掉「已送达 / 已撤销 / 已退货」三个终态", "if order.status in ( OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED, ):" in norm(transfer), "挡板字面量变了？")
    ok("挡板在 transfer_lines 里恰好一处", transfer.count("order.status in (") == 1, "本函数里出现了 " + str(transfer.count("order.status in (")) + " 处")
    statuses = enum_members(enums, "OrderStatus")
    expect_from = [s for s in statuses if s not in BLOCKED]
    ok("from_states == OrderStatus 全集 − 挡板挡掉的那三个", expect_from == items(field(spec, "from_states")), "应有=" + str(expect_from) + " 声明=" + field(spec, "from_states"))
    lock_i = transfer.find("lock_order_row(db, source)")
    cmp_i = transfer.find("order.status in (")
    ok("先锁再判：lock_order_row 出现在第一处状态比较之前", 0 <= lock_i < cmp_i, "锁=" + str(lock_i) + " 比较=" + str(cmp_i))
    ok("取单取不到给 404「未找到对应记录」", "未找到对应记录" in transfer and "404" in transfer)
    ok("回收站里的单不能转货", "这一单在回收站里，不能转货" in transfer)
    ok("整单搬空借既有 cancel_pending 作废源单（不自己写 CANCELLED）", "cancel_pending(db, order, actor)" in transfer and "values(status=" not in transfer)
    stray = re.findall(r"order\.status\s*=(?!=)", transfer)
    ok("命令层不写 order.status / 不做 update(Order).values(status=…)", not stray and "update(Order" not in transfer, "状态机只许 services/order_flow.py 一个入口；发现 " + str(len(stray)) + " 处赋值")
    ok("「已接单」不许整单转空（先撤回派单再转）", "if empties_source and order.status == OrderStatus.ACCEPTED:" in transfer and "司机已经接单了，整单转空要走「撤回派单」再转" in transfer)
    leak = [f for f in MONEY_FIELDS if f in blk]
    ok("转货不碰钱：实现里不出现 payment_method / 挂账单位 / 现场收现", not leak, "抄了这些钱字段：" + ", ".join(leak))
    ok("目标单构造期状态是 PENDING_DISPATCH，且只此一处", blk.count("status=OrderStatus.PENDING_DISPATCH") == 1, "本块里 " + str(blk.count("status=OrderStatus.PENDING_DISPATCH")) + " 处")
    ok("目标单号走 new_order_no()（不自己拼单号）", "new_order_no()" in blk)
    ok("行按库里现在值改：转满删行、转一部分改数量并把行金额按单价重算", "db.delete(op)" in transfer and "op.quantity = have - int(qty)" in transfer and "op.line_total = money(" in transfer)
    ok("两行 ORDER_TRANSFER 审计（一出一进）", transfer.count("action=OperationAction.ORDER_TRANSFER") == 2)
    ok("审计的 change_payload 里金额是 str（Decimal 直接塞会抛）", (Q + "direction" + Q + ": " + Q + "out" + Q) in transfer and (Q + "direction" + Q + ": " + Q + "in" + Q) in transfer and (Q + "unit_price" + Q + ": str(price)") in transfer)
    ok("并进既有单前给目标单加锁（锁序恒为源单 → 目标单）", transfer.count("with_for_update()") == 2, "加锁点=" + str(transfer.count("with_for_update()")))
    ok("预占各重算一次：源单没作废就重算它，目标单总是重算", "_resync_stock_if_assigned(db, order, actor.id)" in transfer and "_resync_stock_if_assigned(db, target, actor.id)" in transfer)
    # ⛔ 下面四条是**真实库探针**（_tmp/_probe_chg0042_transfer.py）在真库副本上跑出来的：
    #    前三处形状静态判据全绿、跑起来也不抛异常，但库里的结果不同（源单永久占着不存在的货、备注静默消失）。
    ok("_put_line 的调用与定义同口径（少一个 db 针脚 ⇒ 第一次转货就 TypeError 500）",
       "def _put_line(db: Session, target: Order, op: OrderProduct, qty: int) -> None:" in norm(blk)
       and blk.count("_put_line(db, target, op, int(qty))") == 1 and "_put_line(target," not in blk,
       "定义=" + str("def _put_line(db: Session" in norm(blk)) + " 调用点=" + str(blk.count("_put_line(db, target, op, int(qty))")))
    i_move = transfer.find("op.quantity = have - int(qty)")
    i_flush = transfer.find("db.flush()")
    i_exp = transfer.find("db.expire(order, [" + Q + "order_products" + Q + "])")
    i_res = transfer.find("_resync_stock_if_assigned(db, order, actor.id)")
    ok("行搬完先落盘 + 让明细集合失效，再让预占对账（否则整行搬走时差额算成 0，源单永久占着不存在的货）",
       0 <= i_move < i_flush < i_exp < i_res,
       "搬行=" + str(i_move) + " flush=" + str(i_flush) + " expire=" + str(i_exp) + " 重算=" + str(i_res))
    ok("这条落盘的理由逐字写在代码里（autoflush=False 的会话读的是内存缓存）",
       "autoflush=False" in cmdraw and "内存缓存" in cmdraw)
    i_cancel = transfer.rfind("cancel_pending(db, order, actor)")
    i_note_src = transfer.find("order.internal_notes = _note_with(")
    i_note_dst = transfer.find("target.internal_notes = _note_with(")
    i_log = transfer.find("write_log(")
    ok("两处内部备注写在最后（cancel_pending 里的 db.refresh 会把没落盘的备注整段丢掉）",
       0 <= i_cancel < i_note_src < i_note_dst < i_log,
       "作废=" + str(i_cancel) + " 源备注=" + str(i_note_src) + " 目标备注=" + str(i_note_dst) + " 审计=" + str(i_log))
    ok("四个发件箱事件都真的发了（池子 / 新建 / 源单作废 / 司机在手上）", all((Q + e + Q) in transfer for e in FOUR_EVENTS))
    ok("命令层只 commit 一次（业务写与发件箱同一个事务）", transfer.count("db.commit()") == 1, "commit=" + str(transfer.count("db.commit()")))

    # ── 3. 端点 ──────────────────────────────────────────────────────────
    section("3. 端点（api/v1/orders_assignment.py）")
    ok("端点存在，权限点 ORDER_DISPATCH（与派单同一颗，不新建）", "require_permission(Permission.ORDER_DISPATCH)" in ep)
    ok("路由只负责 HTTP：CommandError 原样透出", "except order_commands.CommandError as e:" in ep and "HTTPException(status_code=e.status_code, detail=e.detail)" in ep)
    ok("order_flow 的 ValueError 翻成 400", "except ValueError as e:" in ep and "HTTPException(status_code=400, detail=str(e))" in ep)
    ok("路由自己不 commit（事务收尾在命令层）", "db.commit()" not in ep)

    # ── 4. 词汇表 / 地图 / 生成物 ────────────────────────────────────────
    section("4. 词汇表 / 领域地图 / 生成物")
    ok("ORDER_TRANSFER 动作码在 models/enums.py 里，且只定义一次", enums.count("ORDER_TRANSFER = " + Q + "ORDER_TRANSFER" + Q) == 1)
    ok("它与 ORDER_SPLIT 并存（拆单拆的是同一货主的货，转货动的是货归谁）", "ORDER_SPLIT = " + Q + "ORDER_SPLIT" + Q in enums)
    ci = cov.find("order:edit")
    cblock = cov[ci : cov.find(")", ci)] if ci >= 0 else ""
    ok("审计覆盖表把 ORDER_TRANSFER 认领给 order:edit", "ORDER_TRANSFER" in cblock, "order:edit 这一格=" + norm(cblock)[:120])
    ok("领域地图的订单域 commands 行里有 commands.order:transfer_lines", mp.count("commands.order:transfer_lines") == 1, "地图里出现 " + str(mp.count("commands.order:transfer_lines")) + " 次")
    ok("能力快照 / 审计覆盖文档已带上 ORDER_TRANSFER（生成器跑过）", "ORDER_TRANSFER" in snap)

    # ── 5. Android ───────────────────────────────────────────────────────
    section("5. Android（端点 / DTO / 状态集合 / 入口 / 抽屉）")
    ok("Apis.kt 的端点逐字是 @POST(orders/{orderId}/transfer)", "@POST(" + Q + "orders/{orderId}/transfer" + Q + ")" in apis)
    ok("仓库层转发到同一个端点名", "api.orderApi.transferOrderLines(orderId, body)" in repo)
    ok("请求 DTO 的线上名与后端 schema 逐字一致", ("@SerialName(" + Q + "line_id" + Q + ") val lineId: Long") in dto and ("@SerialName(" + Q + "shipper_id" + Q + ") val shipperId: Long? = null") in dto and ("@SerialName(" + Q + "temp_shipper_name" + Q + ") val tempShipperName: String? = null") in dto and ("@SerialName(" + Q + "merge_into_order_id" + Q + ") val mergeIntoOrderId: Long? = null") in dto and "val lines: List<OrderTransferLineBody>" in dto)
    ok("结果 DTO 与后端 OrderTransferOut 逐字段一致", ("@SerialName(" + Q + "source_order" + Q + ") val sourceOrder: OrderDto") in dto and ("@SerialName(" + Q + "created_target" + Q + ") val createdTarget: Boolean") in dto and ("@SerialName(" + Q + "source_cancelled" + Q + ") val sourceCancelled: Boolean") in dto and ("@SerialName(" + Q + "moved_lines" + Q + ") val movedLines: Int") in dto)
    ok("后端 schema：行 id + 数量（>=1）+ 至少一行（上限 100）", "line_id: int" in schema and "ge=1" in schema and "min_length=1, max_length=100" in schema)
    ti2 = status.find("val TRANSFERABLE")
    tline = status[ti2 : status.find(NL, ti2)] if ti2 >= 0 else ""
    transferable = [p.strip().split(Q)[1] for p in tline.split("setOf(")[-1].split(",") if Q in p]
    ok("客户端 TRANSFERABLE 与后端挡板的补集逐值一致（在途三态）", transferable == IN_TRAFFIC, "客户端=" + str(transferable) + " 后端=" + str(expect_from))
    gate = "if (role == Role.DISPATCHER && order.status in OrderStatusModel.TRANSFERABLE) {"
    ok("转货入口恰好一处，且挂在「派单员 + 在途三态」门上", screen.count(gate) == 1 and screen.count("onTransferClick = { vm.openTransfer() }") == 1, "门=" + str(screen.count(gate)) + " 接线=" + str(screen.count("onTransferClick = { vm.openTransfer() }")))
    ok("两处弹层都接上了（先选人，再填数量）", screen.count("if (vm.showTransferPicker)") == 1 and screen.count("if (vm.showTransferSheet)") == 1)
    ok("抽屉里的数量控件是共用的那一份（QtyStepper），上限夹在本行现有数量内", bool(re.search(r"(?<![A-Za-z_])QtyStepper\(", sheet)) and "coerceIn(0, line.quantity)" in sheet, "不许自己写加减器（⛔ 整词匹配，LocalQtyStepper 这种换名字的写法混不过去），也不许放开上限")
    ok("抽屉不自己算钱（只显示服务端给的单价，不做乘法）", "lineTotal =" not in sheet and "* line.unitPrice" not in sheet and "line.unitPrice *" not in sheet)
    ok("抽屉不传 containerColor（底色由主题一处说了算）", "containerColor" not in sheet)
    save = kt_member(vm, "saveTransfer")
    ok("saveTransfer 存在", bool(save))
    ok("没选人 / 没填行都不发请求（本地校验先于请求）", "transferError = " + Q + "请先选一位货主（或填临时货主）" + Q in save and "transferError = " + Q + "请至少填一件要转出去的货" + Q in save and save.find("viewModelScope.launch {") > save.find("请至少填一件要转出去的货"))
    ok("客户端也把上限夹在现有数量内（后端会拒，但不该让他先跑一趟网络）", "q.coerceAtMost(line.quantity)" in save)
    ok("成功后按回参重拉，不复算金额", "actionResult = transferResultText(r)" in save and "load()" in save and "showTransferSheet = false" in save)
    ok("结果文案点名「源单已撤销」（搬空必须让派单员看见）", "源单已撤销（货全转走了）" in vm)

    print(NL + "=" * 60)
    if C.fails:
        print(f"❌ {len(C.fails)} 项不通过（通过 {C.n_ok} 项）：")
        for label, _ in C.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {C.n_ok} 项通过：转货只动货归谁，状态机 / 钱 / 审计三件事都没有跟着乱。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
