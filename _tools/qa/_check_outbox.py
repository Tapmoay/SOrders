#!/usr/bin/env python3
"""_check_outbox.py —— 事务发件箱（整改报告 §10）自己的判据。

### 为什么发件箱要自己的检查
报告 §10 要治的病是「**数据库成功 → 后台任务恰好挂了 → 事件永远丢失**」。
而发件箱这套东西的失效方式恰好是**静默**的：

- `enqueue` 里多写一个 `commit` → 事件不再属于业务事务（业务回滚了它还在 / 业务提交了它可能没写进去），
  而"能跑通"的测试一条都不会红；
- 失败分支被改成"标记成功" → 丢事件换了个地方发生，界面上一切正常；
- 表结构与模型写成两样 → 上线当天才发现（列名差一个字）；
- 核心模块 import 了推送链路 → 分层没了，单测也没法在不连 Redis 的情况下跑。

### 判据
1. 迁移 `002_outbox_events.py` 在，且**表结构取自模型**（`OutboxEvent.__table__.create`）—— 两边不可能写成两样；
2. 模型里表名/关键列/索引齐全（缺一列就是"上线当天才发现"那一类）；
3. `enqueue` **不许 commit**（判据锚在代码上，注释不算）；
4. 核心模块不许 import 推送链路（socketio / app.services / app.api）；
5. 失败路径齐全：记 `last_error`、`attempts+1`、退避、用满即放弃；`mark_sent` 只在派发成功之后；
6. worker 真的被应用起起来（`main.py` 的 lifespan）且未登记的事件类型会**抛错**；
7. 这条新边界**自己可见**：`/metrics` 里有待发/放弃两个 gauge；
8. 判据条数下限（防检查空转）；
9. **生产者不许绕开发件箱直接推**（2026-09-25 补）：把「推送出口」那一层列出来
   （`core/socket_io.py` / `services/message_push.py` / `services/message_center.py` /
   `services/push_events.py` / `main.py` 的派发表），其余**任何**模块直接调它们都算绕开。
   ⚠️ 判据判在 `code_only` 上：第一版判原文，被模块说明里那句历史解释
   （"原来它在后台线程里直接 `asyncio.run(emit_notification(n))`"）骗红过。
   另配两条护栏：放行表不许长霉（每条都指得到真实文件）、扫到的模块数 ≥40（防解析失效后空转）；
10. 账本导出完成那条链路**必须是发件箱在推**（`notifications.created`）—— 它是最后一个切完的生产者
   （2026-09-25）：在此之前它 commit 完通知就**直接推**，进程在中间重启 = 用户永远收不到「导出完成」，
   而库里一切正常、没有任何地方报错。

用法：
    python _tools/qa/_check_outbox.py --check   # 非零退出＝有问题
    python _tools/qa/_check_outbox.py           # 打印逐条明细
"""

from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CORE = ROOT / "backend" / "app" / "core" / "outbox.py"
MODEL = ROOT / "backend" / "app" / "models" / "outbox.py"
MIG = ROOT / "backend" / "app" / "migrations" / "002_outbox_events.py"
MAIN = ROOT / "backend" / "app" / "main.py"
METRICS = ROOT / "backend" / "app" / "core" / "metrics.py"
MIN_RULES = 12


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8", errors="replace").read()


def code_only(src: str) -> str:
    """剥掉字符串与注释，**保留行号**（判据要报真位置；本项目栽过"注释满足判据"）。"""
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    starts: list[int] = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))

    def char_col(lineno: int, byte_col: int) -> int:
        raw = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        return len(raw.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))

    chars = list(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            end_line = node.end_lineno or node.lineno
            a = starts[node.lineno - 1] + char_col(node.lineno, node.col_offset)
            b = starts[end_line - 1] + char_col(end_line, node.end_col_offset or 0)
            for i in range(a, min(b, len(chars))):
                if chars[i] != "\n":
                    chars[i] = " "
    return re.sub(r"(?m)#.*$", "", "".join(chars))


def imports_of(src: str) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def body_of(src: str, name: str) -> str:
    """取某个顶层函数的源码（含缩进体）。"""
    m = re.search(r"^(?:async )?def " + re.escape(name) + r"\(", src, re.M)
    if m is None:
        return ""
    nxt = re.search(r"^(?:async )?def |^class ", src[m.end():], re.M)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(src) - m.end())]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    check_mode = "--check" in sys.argv[1:]
    passed: list[str] = []
    failures: list[str] = []

    def want(ok: bool, good: str, bad: str) -> bool:
        (passed if ok else failures).append(("OK  " if ok else "BAD ") + (good if ok else bad))
        return ok

    for p in (CORE, MODEL, MIG, MAIN, METRICS):
        want(p.exists(), "存在 " + p.name, "⛔ 找不到 " + str(p.relative_to(ROOT)) + "（发件箱被判据掏空了？）")
    if failures:
        for f in failures:
            print("  " + f)
        return 1

    core_src = read(CORE)
    core_code = code_only(core_src)
    model_src = read(MODEL)
    mig_src = read(MIG)
    main_src = read(MAIN)
    metrics_src = read(METRICS)

    # ---- 1. 迁移：表结构取自模型 ----
    # ⚠️ 这两条**必须**判在 code_only 上：第一版判的是原文，于是迁移的**模块说明**里那句
    #    "`checkfirst=True` → 可以重跑" 把判据自己满足了 —— 把代码里的 checkfirst 改成 False
    #    红线照样全绿。2026-09-25 反向验证第 ⑥ 条实测抓到（"注释满足判据"的第 N 次复发）。
    mig_code = code_only(mig_src)
    want("VERSION = 2" in mig_code, "迁移版本号 = 2", "⛔ 002 迁移没有 VERSION = 2")
    want("__table__.create" in mig_code and "checkfirst=True" in mig_code,
         "迁移用模型的 __table__.create(checkfirst=True)（两边不可能写成两样，且可重跑）",
         "⛔ 迁移没有从模型建表（或没写 checkfirst=True）—— 手写 DDL 的话，模型与迁移迟早写成两样"
         "（列名差一个字，上线当天才发现）；少了 checkfirst 则这条迁移重跑就炸")

    # ---- 2. 模型：表名 / 列 / 索引 ----
    want("__tablename__ = \"outbox_events\"" in model_src, "表名 outbox_events", "⛔ 表名不是 outbox_events")
    cols = ["event_type", "payload", "dedupe_key", "status", "attempts", "last_error",
            "next_attempt_at", "sent_at"]
    missing = [c for c in cols if (c + ":") not in model_src]
    want(not missing, "模型列齐全（" + str(len(cols)) + " 列）", "⛔ 模型少了这些列：" + str(missing))
    want("unique=True" in model_src and "Index(\"ix_outbox_status_next\"" in model_src,
         "去重键唯一 + 派发索引 (status, next_attempt_at)",
         "⛔ 少了去重唯一索引或派发索引 —— 前者让重复入队插进去，后者让 worker 每轮全表扫")

    # ---- 3. enqueue 不许 commit ----
    enq = code_only(body_of(core_src, "enqueue"))
    want(bool(enq), "找到 enqueue（判据自身有效）", "⛔ 找不到 enqueue —— 判据失效")
    want("commit(" not in enq, "enqueue 里没有 commit（与业务同一个事务）",
         "⛔ enqueue 里出现了 commit —— 事件不再属于业务事务：业务回滚了它还在，业务提交了它可能没写进去")

    # ---- 4. 核心模块不认识推送链路 ----
    bad_imports = sorted(m for m in imports_of(core_src)
                         if "socketio" in m or m.startswith("app.services") or m.startswith("app.api"))
    want(not bad_imports, "核心模块没有 import 推送链路（分层还在）",
         "⛔ core/outbox.py 直接 import 了 " + str(bad_imports)
         + " —— 派发必须是注入进去的回调，否则核心层被拖进整条推送链路，单测也没法裸跑")

    # ---- 5. 失败路径齐全 ----
    fail = code_only(body_of(core_src, "mark_failed"))
    want(bool(re.search(r"attempts\s*=\s*[^=\n]*\+\s*1", fail)), "失败会累加 attempts",
         "⛔ mark_failed 没有累加 attempts —— 放弃判据永远不成立，会一直重试")
    want("FAILED" in fail, "尝试用满 → FAILED（放弃）",
         "⛔ mark_failed 里没有放弃分支 —— 一条发不出去的事件会把队头堵死")
    want("next_attempt_at" in fail and "backoff_seconds" in fail, "失败按退避安排下一次",
         "⛔ 失败之后不安排下一次（或没退避）—— 会把日志刷满、还会打爆下游")
    dispatch = code_only(body_of(core_src, "dispatch_sync"))
    i_except = dispatch.find("except")
    i_sent = dispatch.find("mark_sent")
    want(i_except > 0 and i_sent > i_except, "mark_sent 只在派发成功之后（顺序对）",
         "⛔ dispatch 里 mark_sent 出现在 except 之前 —— 没发出去也可能被标成功")

    # ---- 6. worker 起得来 + 未登记要抛错 ----
    want("_outbox_loop" in main_src and "run_forever" in main_src,
         "main.py 起了发件箱循环",
         "⛔ main.py 里没有起 worker —— 表里的事件永远不会被发出去")
    want("asyncio.create_task(_outbox_loop())" in main_src, "循环挂在 lifespan 里",
         "⛔ 循环没有挂在 lifespan（重启后没人拉起）")
    want("raise RuntimeError" in main_src and "没有登记处理器" in main_src,
         "未登记的事件类型会抛错（不许静默丢）",
         "⛔ 未登记的事件类型没有抛错 —— 静默丢事件正是这套东西要治的病")

    # ---- 7. 边界自己可见 ----
    want("sorders_outbox_pending" in metrics_src and "sorders_outbox_failed" in metrics_src,
         "/metrics 里有待发与放弃两个 gauge",
         "⛔ 指标里看不到发件箱 —— 新的事件边界不可见，等于换个地方丢事件")
    want("outbox_stats" in metrics_src, "指标取自 outbox_stats（口径一处）",
         "⛔ 指标没走 outbox_stats —— 又出现了第二处统计口径")

    # ---- 8. 生产者与处理器必须对得上（★ 这条是"切生产者"那一步的护栏） ----
    #    从源码里收集所有 `outbox.enqueue(db, "事件类型"`，每个类型都必须在派发表里登记。
    #    漏登记的后果不是报错而是**那条事件被 worker 一直标记失败**（重试 5 次后放弃），
    #    而业务侧一切正常 —— 正是发件箱要治的那类"静默"。
    APP = ROOT / "backend" / "app"
    enqueued: dict[str, list[str]] = {}
    for p in sorted(APP.rglob("*.py")):
        if "__pycache__" in str(p):
            continue
        src = read(p)
        for m in re.finditer(r"outbox\.enqueue\(\s*[^,]+,\s*\"([^\"]+)\"", src):
            enqueued.setdefault(m.group(1), []).append(p.relative_to(APP).as_posix())
    want(bool(enqueued), "盘到 " + str(len(enqueued)) + " 种被入队的事件类型（"
         + "、".join(sorted(enqueued)) + "）",
         "一处 outbox.enqueue 都没有 —— 边界立了但没人用（生产者还没切）")
    deliver_src = body_of(main_src, "_outbox_deliver")
    unhandled = sorted(t for t in enqueued if ("event_type == \"" + t + "\"") not in deliver_src)
    want(not unhandled, "每种入队的事件类型都在派发表里登记了处理器",
         "⛔ 这些事件类型有人入队、没人处理：" + str(unhandled)
         + " —— worker 会把它们一次次标记失败（重试到放弃），而业务侧一点异常都看不到")
    want("orders.assigned" in enqueued, "派单那条链路已经切成发件箱（orders.assigned）",
         "⛔ 没有任何地方入队 orders.assigned —— 派单推送还挂在 background task 上")
    want("_bg_push_assigned" not in read(ROOT / "backend" / "app" / "api" / "v1" / "orders_assignment.py"),
         "派单端点里不再直接推（后台任务那条路已撤）",
         "⛔ orders_assignment 里还留着 _bg_push_assigned —— 一条链路两套投递（发件箱 + 后台任务）")

    # ---- 9. 生产者不许**绕开发件箱**直接推（★ 2026-09-25 补：最后一条后台任务也切完了） ----
    #    这批绕开点的形状全都一样：**不会报错**，只在"进程恰好在 commit 与推送之间重启"时
    #    静默丢一条事件 —— 正是 §10 要治的病。抓它的办法不是"逐个文件点名单"（点名单会烂），
    #    而是**把推送出口那一层列出来**，其余任何模块直接调它们都算绕开。
    #    ⚠️ 实测抓到的第一个违规就是本轮修的 `services/ledger_export_worker.py`
    #    （导出完成的通知 commit 之后直接 `emit_to_user` + `emit_unread_count` + `push_ledger_updated`）。
    PUSH_LAYER = {
        "core/socket_io.py": "推送的**最底层原语**（sio.emit 只在这里）",
        "services/message_push.py": "emit_to_user 的门面（一层转发，不带业务）",
        "services/message_center.py": "消息中心自己就是推送出口（站内信 + 未读数）",
        "services/push_events.py": "派发表处理器所在的那一层（push_events.X 就是它的出口）",
        "main.py": "发件箱的**派发表**就在这儿（它的处理器必须 await 它们）",
    }
    EMIT_CALL = re.compile(
        r"\b(?:emit_to_user|emit_unread_count|emit_notification|emit_realtime)\s*\("
        r"|\bpush_events\.\w+\s*\("
    )
    bypass: list[str] = []
    scanned = 0
    for p in sorted(APP.rglob("*.py")):
        rel = p.relative_to(APP).as_posix()
        if "__pycache__" in rel or rel in PUSH_LAYER:
            continue
        scanned += 1
        # ⚠️ 必须扫 **code_only**（剥掉字符串与注释、保留行号）：第一版扫的是原文，
        #    于是 `ledger_export_worker.py` 的**模块说明**里那句历史解释
        #    （"原来它在后台线程里直接 `asyncio.run(emit_notification(n))`"）被当成了违规 ——
        #    判据被自己的文档骗红，而"改文档去迎合判据"比红更糟（本仓库栽过同款）。
        for i, line in enumerate(code_only(read(p)).splitlines(), 1):
            if EMIT_CALL.search(line):
                bypass.append(rel + ":" + str(i) + " → " + line.strip()[:90])
    want(scanned >= 40, "扫了 " + str(scanned) + " 个模块找绕开发件箱的推送",
         "⛔ 只扫到 " + str(scanned) + " 个模块（<40）—— 判据在空转")
    want(not bypass, "没有模块绕开发件箱直接推（推送出口只有 " + str(len(PUSH_LAYER)) + " 处）",
         "⛔ 这些地方绕开发件箱直接推：" + "；".join(bypass[:6]) +
         "（进程在 commit 与推送之间重启，这条事件就永远丢了，而库里一切正常）")
    # 放行表不许长霉：里面每一条都必须还是**真实存在**的文件（改名/搬走后要跟着改）。
    stale_layer = sorted(k for k in PUSH_LAYER if not (APP / k).exists())
    want(not stale_layer, "推送出口放行表里每条都指得到真实文件",
         "⛔ 放行表里有已经不存在的文件：" + "、".join(stale_layer) + "（化石，改完记得删）")
    # 反面再正面钉一次：导出完成那条链路必须是**发件箱**在推（本轮最后一个切完的生产者）。
    export_src = read(APP / "services" / "ledger_export_worker.py")
    want('outbox.enqueue(db, "notifications.created"' in export_src,
         "账本导出完成的通知走发件箱（notifications.created）",
         "⛔ 导出完成那条链路没有入队通知事件 —— 推送又回到了「commit 之后直接推」，"
         "进程在中间重启 = 用户永远收不到「导出完成」")

    total = len(passed) + len(failures)
    want(total >= MIN_RULES, "判据条数 " + str(total) + " ≥ " + str(MIN_RULES),
         "只跑了 " + str(total) + " 条判据（< " + str(MIN_RULES) + "）—— 检查可能空转了")

    print("发件箱判据：" + str(len(passed)) + " 通过 / " + str(len(failures)) + " 失败")
    if not check_mode:
        for n in passed:
            print("  ✅ " + n[4:])
    for f in failures:
        print("  " + f)
    if failures:
        return 1
    print("  ✅ 全部通过（入队同事务 / 失败可重试 / 表结构同源 / 边界可见）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
