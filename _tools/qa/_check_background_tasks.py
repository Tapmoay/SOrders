"""红线：**后台任务不许自建事件循环**（R14-7，2026-09-19 审计）。

## 由来（这是一个"功能整个不可用"级别的高危缺陷）

`backend/app/services/ledger_export_worker.py` 原来是一个**同步** `def`，
于是 Starlette 的 `BackgroundTasks` 把它丢进线程池跑（`starlette/background.py`：
同步函数走 `run_in_threadpool`），而它在**后台线程**里直接
`asyncio.run(emit_notification(n))` —— 那是新建一个事件循环。

socket.io 的 Redis 连接是在**主事件循环**里建的，跨事件循环复用同一条连接必然抛
`RuntimeError: ... got Future ... attached to a different loop`。真实后果不是"推送丢了"：

1. 产物文件与「导出完成」通知**都已经 commit 了**（先提交、后推送）；
2. 紧接着的推送抛异常 → 同一个 `except` 把任务翻成 `FAILED`；
3. 用户收到"导出完成"，点进任务页却看到"失败"；重试只会往 `exports/` 堆随机名孤儿文件
   （30 天后才被 `purge_old_export_files` 清掉）。

生产配了 Redis（`SOCKET_REDIS_URL`）→ **每一次导出都会这样**，等于这个功能不可用。
本机没配 Redis 时恰好不炸（走进程内 AsyncServer），所以本地"跑通了"完全不能作为证据 ——
这正是这条红线必须**静态**立在这里的原因。

## 判据（清单全部自己算，不手写）
1. 扫 `backend/app/**/*.py` 里所有 `background_tasks.add_task(NAME, …)`，
   **机器算出**目标函数清单；
2. 每个目标必须能在源码里解析到定义，且必须是 **`async def`**
   —— 同步目标＝被丢进线程池＝不许再 await 主循环里的连接；
3. `backend/app/**/*.py` 里**任何地方**都不许出现 `asyncio.run(` / `asyncio.new_event_loop(` /
   `asyncio.set_event_loop(` / `.run_until_complete(`：应用的事件循环由 FastAPI / Socket.IO 托管，
   自己建一个只会在跨循环使用共享连接时炸（而且是"炸在后台，用户只看到失败状态"这种形状）；
4. 数量判据：目标调用点 ≥ 25、去重后的目标函数 ≥ 12（解析失效/清单过期时先喊，
   而不是安静地什么都不查）。

用法：python _tools/qa/_check_background_tasks.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用单源红线里的 `code_only`（把注释/文档字符串换成等长空格，保留行号）。
#: 为什么必须剥掉：**本文件自己的文档**里就写着 `asyncio.run(emit_notification(n))` 这个反例
#: （"原来就是这么写的、所以会炸"）。不剥的话判据会被自己的文档骗红，
#: 而"改文档去迎合判据"比红更糟。
from _check_single_source import code_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend/app"

#: `background_tasks.add_task(` 后面跟的第一个标识符（允许中间换行）。
ADD_TASK = re.compile(r"background_tasks\.add_task\(\s*([A-Za-z_][A-Za-z0-9_]*)")

#: 事务发件箱的入队点（整改报告 §10）：与后台任务合起来算「派发点总数」，见判据 4。
OUTBOX_ENQUEUE = re.compile(r"outbox\.enqueue\(")

#: 自建事件循环的四种写法。全部禁止。
LOOP_BUILDERS = (
    "asyncio.run(",
    "asyncio.new_event_loop(",
    "asyncio.set_event_loop(",
    ".run_until_complete(",
)

#: 只扫应用代码；`backend/tests/` 下自己起 loop 是**测试**用（例如给 socket 握手造一个）,
#: 与应用运行时的事件循环无关，明确排除并在这里写明理由。
EXCLUDE_DIRS = {"__pycache__"}


def app_files() -> list[Path]:
    return [
        p
        for p in sorted(APP.rglob("*.py"))
        if not any(part in EXCLUDE_DIRS for part in p.parts)
    ]


def defs_in(src: str) -> dict[str, str]:
    """本文件里 `def NAME(` / `async def NAME(` → "async"/"sync"。"""
    out: dict[str, str] = {}
    for m in re.finditer(r"^(async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", src, re.M):
        out[m.group(2)] = "async" if m.group(1) else "sync"
    return out


def main() -> int:
    fails: list[str] = []

    files = app_files()
    global_defs: dict[str, list[tuple[str, str]]] = {}
    raw: dict[Path, str] = {}
    code: dict[Path, str] = {}
    for p in files:
        src = p.read_text(encoding="utf-8")
        raw[p] = src
        code[p] = code_only(src)
        for name, kind in defs_in(code[p]).items():
            global_defs.setdefault(name, []).append((str(p.relative_to(ROOT)), kind))

    # ---- 判据 1+2：每个 add_task 的目标必须是 async def ----
    sites: list[tuple[Path, str]] = []
    for p, src in code.items():
        for m in ADD_TASK.finditer(src):
            sites.append((p, m.group(1)))

    targets = sorted({name for _, name in sites})
    print(f"后台任务注册点 {len(sites)} 处，去重后目标函数 {len(targets)} 个")
    for name in targets:
        where = global_defs.get(name)
        if not where:
            fails.append(f"后台任务目标 `{name}` 在 backend/app 里找不到定义（拼错？已删？）")
            continue
        kinds = {k for _, k in where}
        marks = "async ✅" if kinds == {"async"} else f"❌ {kinds}"
        print(f"   · {name:34} {marks:12} {where[0][0]}")

    # ---- 判据 1b（2026-09-25 新增）：**派发表里的处理器也必须是 async def** ----
    # 整改报告 §10 把推送从"后台任务"搬进了事务发件箱：后台任务目标从 31 个降到 1 个，
    # 但"把一个 async 函数当同步用"那类事故换了个地方长 —— 现在它会出现在**派发表**里
    # （`main.py::_outbox_deliver` 直接 `await push_events.X(...)`）。判据得跟着搬，
    # 否则旧判据会因为"目标函数变少"而变成空转（这正是它自己防的那件事）。
    main_src = (APP / "main.py").read_text(encoding="utf-8")
    handler_calls = sorted(set(re.findall(r"await\s+push_events\.(\w+)\(", main_src)))
    print(f"派发表里 await 的处理器 {len(handler_calls)} 个")
    for name in handler_calls:
        where = global_defs.get(name)
        if not where:
            fails.append(f"派发表调用的 `{name}` 在 backend/app 里找不到定义（拼错？已删？）")
            continue
        kinds = {k for _, k in where}
        if "sync" in kinds:
            fails.append(
                f"派发表调用的 `{name}` 里有**同步**定义（{sorted(kinds)}）—— "
                "await 一个同步函数会当场 TypeError，而事件会被记成失败重试到放弃"
            )

    sync_targets = sorted(
        {
            name
            for name in targets
            if global_defs.get(name) and all(k == "sync" for _, k in global_defs[name])
        }
    )
    if sync_targets:
        fails.append(
            "这些后台任务目标是**同步**函数（会被 Starlette 丢进线程池，"
            "因此绝不允许在里面 await / 自建事件循环，见 R14-7）：" + "、".join(sync_targets)
        )

    # ---- 判据 3：应用代码里不许自建事件循环 ----
    print("\n自建事件循环扫描（已剥掉注释与文档字符串）：")
    hits = 0
    for p, src in code.items():
        for i, line in enumerate(src.splitlines(), 1):
            for pat in LOOP_BUILDERS:
                if pat in line:
                    hits += 1
                    print(f"   ❌ {p.relative_to(ROOT)}:{i}  {raw[p].splitlines()[i - 1].strip()[:100]}")
                    fails.append(
                        f"{p.relative_to(ROOT)}:{i} 出现 `{pat}` —— "
                        "应用的事件循环由 FastAPI/Socket.IO 托管，自建一个会在跨循环复用 "
                        "Redis/socket 连接时抛 RuntimeError（R14-7）"
                    )
    if not hits:
        print(f"   ✅ {len(files)} 个文件里没有任何自建事件循环")

    # ---- 判据 4：数量判据（防解析失效后安静地空转）----
    # ⚠️ 2026-09-24 改口径：整改报告 §10 正在把「推送类」的后台任务**逐条搬进事务发件箱** ——
    #    于是 `background_tasks.add_task` 的数量会**合法地下降**（切完第一条链路就从 31 降到 23）。
    #    数量判据因此改成「**派发点总数** = background task + `outbox.enqueue`」：
    #    照样抓得住「扫描器瞎了」（两类一起塌也会红），但不会把「按计划搬家」判成事故。
    outbox_sites = sum(len(OUTBOX_ENQUEUE.findall(code[p])) for p in files)
    total_sites = len(sites) + outbox_sites
    print(f"  派发点总数 {total_sites} 处 = background task {len(sites)} + 发件箱入队 {outbox_sites}")
    if total_sites < 25:
        fails.append(
            f"只认出 {total_sites} 个派发点（background task {len(sites)} + 发件箱 {outbox_sites}，<25）"
            " —— 判据可能已空转"
        )
    # 目标函数那一格同理（同上那段"改口径"的注释）：发件箱的**派发表**也是"派发目标"，
    # 一起算才既能防"defs 解析瞎了"，又不会把"按计划搬家"判成事故。
    main_src = (APP / "main.py").read_text(encoding="utf-8")
    outbox_handlers = len(re.findall(r'event\.event_type\s*==\s*"', main_src))
    total_targets = len(targets) + outbox_handlers
    print(f"  派发目标总数 {total_targets} 个 = 后台任务目标 {len(targets)} + 派发表处理器 {outbox_handlers}")
    if total_targets < 12:
        fails.append(
            f"只认出 {total_targets} 个派发目标（后台任务 {len(targets)} + 派发表 {outbox_handlers}，<12）"
            " —— 判据可能已空转"
        )

    if fails:
        print("\n❌ 后台任务事件循环纪律被破坏：")
        for f in fails:
            print("   - " + f)
        return 1
    print("\n✅ 所有后台任务目标都是 async def，且应用代码里没有自建事件循环。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
