"""红线：**软删 / 恢复一张在途单必须发实时事件，且司机端不许静默**（BUG-0027 → 测试台账 TA-05 / TA-06）。

## 病灶（2026-10-10 凌晨，隔离栈实测；报告 `_tmp/test_round3/trackA2_order_driver_report.md` 第四节）
派单员把一张**在途**单软删（只写 `orders.deleted_at`，不动 `status`）或从回收站恢复时，
后端**不发任何实时推送** —— 而派单 / 送达 / 撤回都发。后果全在司机那一侧：

| 时刻 | 司机端「进行中」列表 |
|---|---|
| 推送前 | 毫无变化（后端发了 no 事件，客户端无从刷新） |
| 手动下拉后 | 被删的单**静默消失**、恢复的单**静默回归** —— 全程没有一句话 |
| 点开那张旧卡片 | 只看到「订单不存在」+「重试」，既不知道是派单员删的，也没有出路 |

第二条（TA-06）单独看也够呛：单子几分钟前还在，点开却说"不存在"，而"重试"是一个**永远不会成功**的动作。

## 判据（分三段，静态锚点 + 行为；Kotlin 侧一律**先剥注释**再匹配）
1. **后端发得出**：`orders_lifecycle.py` 的删除/恢复两个端点各自 `outbox.enqueue(...)`（且**在 commit 之前**，
   与业务同一事务）；两个事件登记进 `AGGREGATE_KEY`（聚合根 = `order_id`）；`_outbox_deliver` 里各有一支，
   而且那支**真的调了** `push_events.push_order_deleted/restored`（不许登记一个空壳分支）；
   `message_center` 的发布器里**既有站内信也有 `emit_realtime`**（少了后者 = TA-05 原样）。
2. **文案说人话、且不泄漏**：软删 404 的 `detail` 走 `_deleted_order_notice`，**状态码仍是 404**（不许改成 403/200）；
   当事人拿到「…已被派单员删除，如需找回请联系派单员从回收站恢复。」，**非当事人仍然只拿到「订单不存在」**；
   并且安卓那份 `OrderDeleted.HINTS` 与后端 `DELETED_ORDER_NOTICES` **一字不差**（两边各钉一半，谁改都要一起改）。
3. **司机端认得出、且不许静默**：`PushTrust.ORDER_TYPES` 认这两个类型（否则降级成普通消息）；
   `NewOrderAlert.eventOf("order.deleted")` 归到 `REVOKED` 且与撤回/取消**共用去重键**（同一单不喊两遍）；
   `shouldStop` 认它（活没了要立刻闭嘴）；`RealtimeHub` 的 realtime 分支：删除 = 刷新 + 播报，恢复 = 只刷新；
   `OrderDetailScreen` 的 `when` 里 `OrderDeleted.isDeletedNotice(vm.error)` 那一支必须在 `ErrorView`（重试）**之前**。

⚠️ 本判据**只管"接得通、说得对"**；软删的状态机与 `deleted_at` 语义、已送达撤单 422 的闸、钱/账本一律不碰
（那是 `_check_soft_delete_guards.py` 与后端测试的活）。

用法：
    python _tools/qa/_check_soft_delete_realtime.py            # 直接跑（_check_all.py 会带上它）
    python _tools/qa/_check_soft_delete_realtime.py --list      # 只列每条判据的结果
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"
LIFECYCLE = BACKEND / "api/v1/orders_lifecycle.py"
COMMON = BACKEND / "api/v1/orders_common.py"
OUTBOX = BACKEND / "core/outbox.py"
MAIN = BACKEND / "main.py"
PUSH = BACKEND / "services/push_events.py"
CENTER = BACKEND / "services/message_center.py"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
PUSHTRUST = AND / "core/PushTrust.kt"
ALERT = AND / "core/NewOrderAlert.kt"
HUB = AND / "core/RealtimeHub.kt"
DELETED_KT = AND / "ui/order/OrderDeleted.kt"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"

#: 判据条数下限：判据自己写错/锚点失效时先喊，而不是安静地什么都不查（防空转）。
MIN_RULES = 30


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def code_only(text: str) -> str:
    """把 Kotlin 的注释抹成空格、**保留行号**。

    ⚠️ 本项目反复栽在"注释满足判据"上：一段写着 `// "order.deleted" -> 刷新` 的注释
    能让纯文本判据变绿，而代码里根本没有那一支。所以 Kotlin 侧一律先过这里。
    """
    out = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    return re.sub(r"//[^\n]*", lambda m: " " * len(m.group(0)), out)


def parse(p: Path) -> ast.Module:
    return ast.parse(read(p))


def func_of(mod: ast.Module, name: str) -> ast.AST | None:
    for node in ast.walk(mod):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def calls(node: ast.AST, attr: str) -> list[ast.Call]:
    """按**短名**收调用：`x.attr(...)` 与 `attr(...)` 都算。

    ⚠️ 两种情况都必须收：跨模块的是 `push_events.push_order_deleted(`，而 message_center
    里那些是**同模块裸调用**（`create_message(` / `emit_realtime(`）—— 只认 Attribute 的话
    会得到"发布器里没有 emit_realtime"这种**假红**（第一版就是这样）。
    """
    out = []
    for n in ast.walk(node):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and f.attr == attr:
            out.append(n)
        elif isinstance(f, ast.Name) and f.id == attr:
            out.append(n)
    return out


def str_arg(call: ast.Call, idx: int) -> str | None:
    if len(call.args) > idx and isinstance(call.args[idx], ast.Constant) and isinstance(call.args[idx].value, str):
        return call.args[idx].value
    return None


def assigned_value(node: ast.AST, var: str) -> ast.AST | None:
    """`var = ...` 与带注解的 `var: T = ...`（AnnAssign）都算 —— 本项目两种写法都有。

    ⚠️ 只认 `Assign` 的话，`AGGREGATE_KEY: dict[str, str] = {...}` 这种带注解的常量会
    被完全看不见（第一版就是这么空的）。
    """
    for n in ast.walk(node):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == var for t in n.targets):
            return n.value
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == var:
            return n.value
    return None


def dict_literal(node: ast.AST, var: str) -> dict[str, str]:
    for n in ast.walk(node):
        if True:
            value = assigned_value(node, var)
            if isinstance(value, ast.Dict):
                out = {}
                for k, v in zip(value.keys, value.values):
                    if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                        out[str(k.value)] = str(v.value)
                return out
            return {}


def kt_block(text: str, head: str, opener: str, closer: str) -> str:
    """从含 [head] 的那一行开始，取第一个 [opener] 到它配对的 [closer] 之间的原文。"""
    i = text.find(head)
    if i < 0:
        return ""
    j = text.find(opener, i)
    if j < 0:
        return ""
    k = text.find(closer, j)
    return text[j : (k if k > 0 else len(text))]


def kt_strings(block: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r'"([^"\n]*)"', block)]


def kt_branch_body(lines: list[str], idx: int) -> str:
    """从 when 分支那一行起取**整支**：带 { 的按花括号配平，单表达式分支只取这一行。

    ⚠️ 不能用固定窗口（lines[idx:idx+4]）：窗口会吃进后面那一支的代码 ——
    「删掉本支的 announce」这种注入就可能被下一支里的同名代码救活（假绿）。
    """
    if "{" not in lines[idx]:
        return lines[idx]
    depth = 0
    out: list[str] = []
    for ln in lines[idx:]:
        out.append(ln)
        depth += ln.count("{") - ln.count("}")
        if depth <= 0:
            break
    return "\n".join(out)


def main() -> int:
    listing = "--list" in sys.argv
    rules: list[tuple[str, bool, str]] = []

    def want(ok: bool, good: str, bad: str) -> None:
        rules.append((good if ok else bad, bool(ok), "" if ok else bad))

    # ---- A. 后端发得出（TA-05 的一半：事件真的进发件箱、真的被派发） ----
    life = parse(LIFECYCLE)
    for fname, etype in (("delete_cancelled_order", "orders.deleted"), ("restore_order", "orders.restored")):
        fn = func_of(life, fname)
        if fn is None:
            want(False, "", f"{LIFECYCLE.name} 里找不到函数 {fname}（锚点失效）")
            continue
        enq = [c for c in calls(fn, "enqueue") if str_arg(c, 1) == etype]
        want(bool(enq), f"{fname}：软删/恢复时真的往发件箱写了 {etype}", f"{fname} 没有 outbox.enqueue(..., \"{etype}\")：司机端根本收不到信号（TA-05 原样）")
        payload_ok = False
        for c in enq:
            if len(c.args) > 2 and isinstance(c.args[2], ast.Dict):
                keys = {k.value for k in c.args[2].keys if isinstance(k, ast.Constant)}
                payload_ok = {"order_id", "user_ids"} <= keys
        want(payload_ok, f"{fname} 的 {etype} 载荷带 order_id 与 user_ids", f"{fname} 的 {etype} 载荷缺 order_id / user_ids：发布器不知道该发给谁")
        commits = calls(fn, "commit")
        if enq and commits:
            last_commit = max(c.lineno for c in commits)
            want(max(c.lineno for c in enq) < last_commit, f"{fname}：enqueue 在 commit 之前（与业务同一事务，回滚时事件一并消失）", f"{fname}：enqueue 在 commit 之后 —— 业务回滚了事件却还在发件箱里（会把一张没被删的单说成被删了）")
        else:
            want(False, "", f"{fname}：找不到 enqueue 或 db.commit（锚点失效）")

    agg = dict_literal(parse(OUTBOX), "AGGREGATE_KEY")
    for etype in ("orders.deleted", "orders.restored"):
        want(agg.get(etype) == "order_id", f"AGGREGATE_KEY[{etype}] = order_id", f"outbox.AGGREGATE_KEY 里 {etype} 不是 order_id（发件箱的聚合根键对不上的话幂等/去重会失效）")

    # ---- 行为：真的把 outbox 模块导入，跑一次 aggregate_of ----
    try:
        sys.path.insert(0, str(ROOT / "backend"))
        from app.core import outbox as _outbox  # type: ignore[import-not-found]

        got = _outbox.aggregate_of("orders.deleted", {"order_id": 7})
        got2 = _outbox.aggregate_of("orders.restored", {"order_id": 7})
        empty = _outbox.aggregate_of("orders.deleted", {})
        # ⚠️ 用 str() 比：aggregate_of 回的是 payload 里的原值（可能是 int，也可能是 JSON 里的 "7"），
        #    这里只关心"解出来的是这张单的 id"。
        want(str(got) == "7" and str(got2) == "7", "行为：aggregate_of 把两个新事件都解成那张单的 id", f"行为：aggregate_of(orders.deleted/restored) 解不出 7（拿到 {got!r} / {got2!r}）")
        want(empty is None, "行为：载荷缺 order_id 时 aggregate_of 回 None 而不是抛错", f"行为：载荷缺 order_id 时 aggregate_of 抛错/回 {empty!r}（发件箱写行会直接炸）")
    except Exception as exc:  # noqa: BLE001
        want(False, "", f"行为：导入 backend/app/core/outbox.py 失败（{type(exc).__name__}: {exc}）")

    main_src = read(MAIN)
    deliver = func_of(parse(MAIN), "_outbox_deliver")
    for etype, handler in (("orders.deleted", "push_order_deleted"), ("orders.restored", "push_order_restored")):
        branches = [
            n
            for n in ast.walk(deliver)
            if isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare)
            and isinstance(n.test.comparators[0], ast.Constant)
            and n.test.comparators[0].value == etype
        ] if deliver else []
        want(bool(branches), f"_outbox_deliver 登记了 {etype}", f"_outbox_deliver 没有 {etype} 的分支 → worker 会抛「发件箱没有登记处理器」（事件永远发不出去）")
        called = [c for b in branches for c in calls(b, handler)]
        want(bool(called), f"_outbox_deliver 的 {etype} 分支真的调了 {handler}(", f"_outbox_deliver 的 {etype} 分支是空壳（没调 {handler}）—— 登记了却什么都不发")
        if branches:
            seg = "".join(main_src.splitlines(keepends=True)[branches[0].lineno - 1 : branches[0].end_lineno])
            want("payload" in seg and "int(" in seg, f"{etype} 分支把载荷里的 id 转成了 int", f"{etype} 分支没把载荷里的 user_ids/order_id 转成 int（JSON 里是字符串，发布器会拿它当 uid 找不到人）")

    push = parse(PUSH)
    for fname, pub in (("push_order_deleted", "publish_order_deleted"), ("push_order_restored", "publish_order_restored")):
        fn = func_of(push, fname)
        want(fn is not None, f"push_events.{fname} 存在", f"push_events.py 缺 {fname}（薄包装那一层断了）")
        if fn is not None:
            want(bool(calls(fn, pub)), f"{fname} 转调 message_center.{pub}", f"{fname} 没调 message_center.{pub}")

    center = read(CENTER)
    center_mod = parse(CENTER)
    for fname, etype, realtime_required in (
        ("publish_order_deleted", "order.deleted", True),
        ("publish_order_restored", "order.restored", True),
    ):
        fn = func_of(center_mod, fname)
        if fn is None:
            want(False, "", f"message_center.py 缺 {fname}")
            continue
        seg = "".join(center.splitlines(keepends=True)[fn.lineno - 1 : fn.end_lineno])
        typed = [c for c in calls(fn, "create_message")]
        types = {kw.value.value for c in typed for kw in c.keywords if kw.arg == "type" and isinstance(kw.value, ast.Constant)}
        want(etype in types, f"{fname} 发的站内信 type = {etype}", f"{fname} 的站内信 type 不是 {etype}（拿到 {sorted(types)}）：安卓的白名单与播报判定认的就是这个名字")
        want(bool(calls(fn, "emit_realtime")), f"{fname} 里既有站内信也有 emit_realtime（实时那一腿）", f"{fname} 没有 emit_realtime —— 只有站内信的话司机端列表不会自动更新，正是 TA-05")
        want(bool(calls(fn, "emit_notification")), f"{fname} 里有 emit_notification（系统通知那一腿）", f"{fname} 没有 emit_notification")
        want("idem_key" in seg, f"{fname} 带幂等键（重试不会重复发）", f"{fname} 没写 idem_key —— worker 重试会给同一个人发第二条")
        if realtime_required:
            want("order_id" in seg and "order_no" in seg, f"{fname} 的实时载荷带 order_id 与 order_no", f"{fname} 的实时载荷缺 order_id/order_no（安卓那边认不出是哪张单）")

    # ---- B. 文案：说人话、但不许泄漏（TA-06 的后端一半） ----
    common_src = read(COMMON)
    common = parse(COMMON)
    _notices_node = assigned_value(common, "DELETED_ORDER_NOTICES")
    notices: tuple[str, ...] = tuple(
        e.value for e in getattr(_notices_node, "elts", []) if isinstance(e, ast.Constant)
    )
    plain = str(getattr(assigned_value(common, "PLAIN_NOT_FOUND_NOTICE"), "value", ""))
    want(len(notices) == 2, "后端有两条删除说明（在途 / 非在途）", f"DELETED_ORDER_NOTICES 不是两条（拿到 {len(notices)} 条）")
    want(all("回收站" in s for s in notices) and notices, "两条删除说明都告诉司机去哪找回来（回收站）", "删除说明没给出路（缺「回收站」）—— 那和「订单不存在」一样没用")
    want(plain == "订单不存在", "非当事人仍然只拿到「订单不存在」", f"PLAIN_NOT_FOUND_NOTICE 被改成了 {plain!r}")
    notice_fn = func_of(common, "_deleted_order_notice")
    if notice_fn is None:
        want(False, "", "orders_common.py 缺 _deleted_order_notice（文案选择器）")
    else:
        seg = "".join(common_src.splitlines(keepends=True)[notice_fn.lineno - 1 : notice_fn.end_lineno])
        want("current.id" in seg and "driver_id" in seg and "shipper_id" in seg, "_deleted_order_notice 按「是不是当事人」分岔", "_deleted_order_notice 没有按当事人分岔 —— 会把「有一张你看不见的单被删了」漏给不相干的人")
        want("PLAIN_NOT_FOUND_NOTICE" in seg, "非当事人那条路回「订单不存在」", "非当事人也拿到了删除文案（泄漏：能从文案反推有一张自己看不见的单）")
        # ⚠️ 只查"这段里有 PLAIN_NOT_FOUND_NOTICE" 是不够的：把门写成 `if False:`，
        #    那句 return 还在文本里、却永远轮不到 —— 反验的注入正是这么干的。
        #    所以要求它是**活的**：有一个 if，条件里真的读 mine，体内真的 return 它。
        guarded = any(
            isinstance(n, ast.If)
            and "mine" in ast.dump(n.test)
            and any(
                isinstance(st, ast.Return) and "PLAIN_NOT_FOUND_NOTICE" in ast.dump(st)
                for st in ast.walk(n)
            )
            for n in ast.walk(notice_fn)
        )
        want(
            guarded,
            "「非当事人」那道门是活的（if … mine … 守着 return PLAIN_NOT_FOUND_NOTICE）",
            "「非当事人」那道门是死代码（例如 if False:）—— 删除文案会发给不相干的人，等于泄漏「有一张你看不见的单被删了」",
        )
        want("DISPATCHED" in seg and "ACCEPTED" in seg, "在途（DISPATCHED/ACCEPTED）用「已被派单员删除」那句", "在途单没有单独措辞（司机拿到的句子与「已送达到一半被删」混在一起）")
    scoped = func_of(common, "_get_order_scoped")
    scoped_found = False
    if scoped is not None:
        seg = "".join(common_src.splitlines(keepends=True)[scoped.lineno - 1 : scoped.end_lineno])
        scoped_found = "_deleted_order_notice(" in seg
    want(scoped_found, "_get_order_scoped 的软删分支走 _deleted_order_notice", "_get_order_scoped 的软删分支没走 _deleted_order_notice（TA-06 的病根就在这一行）")
    want("HTTP_404_NOT_FOUND" in common_src, "软删仍然回 404（不是 403/200）", "orders_common.py 里看不到 HTTP_404_NOT_FOUND")

    # ---- C. 安卓：认得出、不许静默（先剥注释） ----
    trust = code_only(read(PUSHTRUST))
    order_types = kt_block(trust, "val ORDER_TYPES", "setOf(", ")")
    for t in ("order.deleted", "order.restored"):
        want(f'"{t}"' in order_types, f"PushTrust.ORDER_TYPES 认 {t}", f"PushTrust.ORDER_TYPES 不认 {t}（那条站内信会降级成普通消息，列表也不会跟着刷）")

    alert = code_only(read(ALERT))
    lines = alert.splitlines()
    ev = next((i for i, ln in enumerate(lines) if '"order.deleted"' in ln and "AlertEvent(" in ln), -1)
    want(ev >= 0, "NewOrderAlert.eventOf 有 order.deleted 分支", "NewOrderAlert.eventOf 没有 order.deleted 分支 —— 事件到了也没人喊一声")
    if ev >= 0:
        same_line = lines[ev]
        want('"order.revoked"' in same_line and '"order.cancelled"' in same_line, "删除与撤回/取消是同一支（共用去重键）", "order.deleted 没有与撤回/取消共用分支 —— 同一单先撤回后被删会喊两遍")
        body = "\n".join(lines[ev : ev + 6])
        want("AlertKind.REVOKED" in body, "被删归到 AlertKind.REVOKED（语音说「有任务被撤回」）", "被删没归到 REVOKED（司机听不到那句短语）")
        want('dedupeKey = "revoked:"' in body, "去重键与撤回/取消同族", "去重键不是 revoked: 家族 —— 同一张单会被喊两次")
    stop = kt_block(alert, "fun shouldStop(", "{", "}")
    want('"order.deleted"' in stop, "shouldStop 认 order.deleted（活没了立刻闭嘴）", "shouldStop 不认 order.deleted —— 单子被删了还在喊「来订单了」")

    hub = code_only(read(HUB))
    hub_lines = hub.splitlines()
    di = next((i for i, ln in enumerate(hub_lines) if '"order.deleted" ->' in ln), -1)
    want(di >= 0, "RealtimeHub 的 realtime 分支认 order.deleted", "RealtimeHub 没有 order.deleted 分支 —— 后端发了没人认，正是 CHG-0040 栽过的形状")
    if di >= 0:
        body = kt_branch_body(hub_lines, di)
        want("_refreshOrders.tryEmit(Unit)" in body, "order.deleted 会让列表立刻重拉", "order.deleted 分支没有刷新列表 —— 卡片会一直留在「进行中」里")
        want("announce(" in body, "order.deleted 会播报一句", "order.deleted 分支不播报 —— 卡片静默消失，司机不知道发生了什么（TA-05 原样）")
    ri = next((i for i, ln in enumerate(hub_lines) if '"order.restored" ->' in ln), -1)
    want(ri >= 0, "RealtimeHub 认 order.restored", "RealtimeHub 没有 order.restored 分支 —— 恢复之后那张卡不会自己回来")
    if ri >= 0:
        body = kt_branch_body(hub_lines, ri)
        want("_refreshOrders.tryEmit(Unit)" in body, "order.restored 会让列表重拉（卡片自己回来）", "order.restored 分支没有刷新列表")
        want("announce(" not in body, "恢复不播报（不做打断司机的那一声）", "order.restored 也播报了 —— 恢复不是「该司机动手」的事，不该打断他")

    deleted_kt = code_only(read(DELETED_KT)) if DELETED_KT.exists() else ""
    want("object OrderDeleted" in deleted_kt, "OrderDeleted.kt 存在（认删除文案的唯一实现）", "android/.../ui/order/OrderDeleted.kt 不存在")
    want("HINTS.any { message.contains(it) }" in deleted_kt, "isDeletedNotice 只认后端那两句原文", "isDeletedNotice 不是按原文匹配的 —— 会把网络故障说成「订单被删了」，比不说还坏")
    hints: list[str] = []
    block = kt_block(deleted_kt, "val HINTS", "listOf(", ")")
    hints = kt_strings(block)
    want(sorted(hints) == sorted(notices), "安卓认的两句与后端发的两句一字不差", f"安卓 HINTS {hints!r} 与后端 DELETED_ORDER_NOTICES {list(notices)!r} 对不上（两边各钉一半，必须同时改）")
    if hints:
        probes = [("订单不存在", False), ("", False), (None, False), ("网络连接失败，请检查网络后重试", False), ("读取失败：" + hints[-1], True)]
        bad_probes = [p for p, exp in probes if (p is not None and any(h in p for h in hints)) is not exp]
        want(not bad_probes, "行为（复刻 contains 语义）：其它报错不会被误判成「订单被删了」", f"这些输入会被误判：{bad_probes!r}")
    want("OutlinedButton" in deleted_kt and '"返回"' in deleted_kt, "删除面板给的是「返回」而不是「重试」", "删除面板没有「返回」按钮（重试永远不会成功）")

    detail = code_only(read(DETAIL))
    w = detail.find("when {")
    seg = detail[w : detail.find("else -> Column(", w)] if w >= 0 else ""
    i_del = seg.find("OrderDeleted.isDeletedNotice(")
    i_err = seg.find("ErrorView(")
    want(i_del >= 0, "详情页 when 里有 OrderDeleted.isDeletedNotice 那一支", "OrderDetailScreen 的 when 块里没有 isDeletedNotice 分支 —— 旧卡片点开还是「订单不存在」")
    want(i_del >= 0 and i_err >= 0 and i_del < i_err, "那一支排在 ErrorView（重试）之前", "isDeletedNotice 支排在 ErrorView 之后 —— 永远轮不到它，TA-06 原样")
    want("OrderDeletedPanel(" in seg, "那一支渲染 OrderDeletedPanel", "isDeletedNotice 分支没有渲染 OrderDeletedPanel")

    # ---- 结果 ----
    print(f"BUG-0027 软删/恢复实时信号判据：{len(rules)} 条")
    for label, ok, _ in rules:
        print(f"  [{'OK' if ok else '!!'}] {label}")
    if listing:
        return 0
    if len(rules) < MIN_RULES:
        print(f"\n❌ 只跑了 {len(rules)} 条判据（应 ≥{MIN_RULES}）——判据在空转，停。")
        return 1
    bad = [b for _, ok, b in rules if not ok]
    if bad:
        print("\n❌ 软删 / 恢复这条链上有洞：")
        for b in bad:
            print("   - " + b)
        return 1
    print("\n✅ 后端发得出、文案说人话、司机端认得出且不静默。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
