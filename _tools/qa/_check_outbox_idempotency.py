#!/usr/bin/env python3
"""_check_outbox_idempotency.py —— 发件箱的**幂等消费**与事件字段（进 `_check_all.py` 自动跑）。

### 为什么需要它（第二轮 R2-04 · 指南 §七）
指南 §七 对事件边界提了两件事：字段要齐（event_id / event_type / aggregate_id / created_at /
payload / status / retry_count），以及 **幂等消费**：

```text
事件发两次  →  不能导致：记两次账 / 发两次结算 / 退两次库存
```

本系统里事件真正驱动的是**推送与站内信**（钱与库存都在业务事务里同步落），而发件箱的口径是
**至少一次**（失败退避重试、快速通道与 worker 两条路都在跑）—— 所以"同一条事件被派发两次"
是**设计内的正常情况**。

⛔ 判据第一次跑之前先盘了一遍：18 条事件里 **13 条处理器不幂等**，重投一次就多一条站内信，
而且**没有任何地方会报错**。修法不是逐条去改 13 处（那就是 13 份各写各的幂等），
而是在**站内信的唯一创建处**（`message_center.create_message`）加幂等键 —— 边界本身就挡住了。

### 判据（七条）
1. 每一种**被入队的事件类型**都必须在 `AGGREGATE_KEY` 或 `NO_AGGREGATE` 里，且不重复；
2. `NO_AGGREGATE` 的每一条都要写理由与「什么时候删掉这一条」，而且必须**仍然被入队**（防化石）；
3. 映射表指的那个 payload 键必须**真的有人填**（在 `enqueue` 的实参里找得到）；
4. `outbox_events.aggregate_id` 列在模型与迁移里都有，且 `enqueue` 真的写了它；
5. `notifications.idem_key` 列 + **唯一索引**在模型与迁移里都有；
6. `create_message`：有 `idem_key` 参数、**插入前查过**、**撞唯一索引时回查**（三处形状）；
7. `message_center` 里所有 `publish_*`（含派单员广播）里的 `create_message(`
   **必须带 `idem_key=`** —— 那些调用全部由发件箱事件驱动，正是会重投的那一批。

用法：python _tools/qa/_check_outbox_idempotency.py [--check]
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

MIN_EVENTS = 15
MIN_PUBLISH = 10
MIN_KEYED = 12
MIN_REASON = 20

#: 匹配 `outbox.enqueue(db, "type", {扁平字典})`（含跨行）。
ENQUEUE_FULL = re.compile(r"enqueue\(\s*db,\s*\"([^\"]+)\",\s*(\{[^{}]*\})", re.S)


def enqueued() -> dict[str, list[str]]:
    """事件类型 → 该类型的每一条入队实参里那个 payload 字面量。"""
    out: dict[str, list[str]] = {}
    for f in (ROOT / "backend/app").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        for m in ENQUEUE_FULL.finditer(text):
            out.setdefault(m.group(1), []).append(m.group(2))
    return out


def publish_calls() -> tuple[list[tuple[str, bool]], int]:
    """message_center 里每个 `create_message(` 调用 →（所在函数, 有没有带 idem_key）。"""
    path = ROOT / "backend/app/services/message_center.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, bool]] = []
    n_pub = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("publish_") or node.name == "_broadcast_to_dispatchers":
            n_pub += 1
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) \
                    and call.func.id == "create_message":
                has = any(k.arg == "idem_key" for k in call.keywords)
                out.append((node.name, has))
    return out, n_pub


def main() -> int:
    check_mode = "--check" in sys.argv[1:]
    from app.core import outbox  # noqa: PLC0415

    fails: list[str] = []
    passed = 0
    events = enqueued()
    calls, n_pub = publish_calls()
    mc = (ROOT / "backend/app/services/message_center.py").read_text(encoding="utf-8")
    ob = (ROOT / "backend/app/core/outbox.py").read_text(encoding="utf-8")
    model = (ROOT / "backend/app/models/outbox.py").read_text(encoding="utf-8")
    notif = (ROOT / "backend/app/models/notification.py").read_text(encoding="utf-8")
    mig = ROOT / "backend/app/migrations"

    # ---- 反空转 ----------------
    if len(events) < MIN_EVENTS:
        fails.append(f"只盘到 {len(events)} 种被入队的事件类型（<{MIN_EVENTS}）—— 扫描坏了")
    else:
        passed += 1
    if n_pub < MIN_PUBLISH:
        fails.append(f"message_center 里只认出 {n_pub} 个 publish 函数（<{MIN_PUBLISH}）—— AST 解析坏了")
    else:
        passed += 1

    # ---- 1/2. 聚合根映射齐全、例外有解释 ----------------
    both = set(outbox.AGGREGATE_KEY) & set(outbox.NO_AGGREGATE)
    if both:
        fails.append("这些事件类型同时出现在两张表里（一张表说得出聚合根、另一张说没有）：" + "、".join(sorted(both)))
    unregistered = sorted(set(events) - set(outbox.AGGREGATE_KEY) - set(outbox.NO_AGGREGATE))
    if unregistered:
        fails.append("这些事件类型**没有登记聚合根来源**（新加事件时忘了？）：" + "、".join(unregistered))
    fossil = sorted(set(outbox.AGGREGATE_KEY) - set(events))
    if fossil:
        fails.append("映射表里这些事件类型已经没人入队了（化石）：" + "、".join(fossil))
    if not both and not unregistered and not fossil:
        passed += 1
    before = len(fails)
    for ev, why in outbox.NO_AGGREGATE.items():
        if len(why.strip()) < MIN_REASON:
            fails.append(f"NO_AGGREGATE[{ev}] 的理由太短（<{MIN_REASON} 字）")
        if "什么时候删掉这一条" not in why:
            fails.append(f"NO_AGGREGATE[{ev}] 没写「什么时候删掉这一条」")
        if ev not in events:
            fails.append(f"NO_AGGREGATE[{ev}] 明明还在被入队，却不是例外")
    if len(fails) == before:
        passed += 1

    # ---- 3. 映射表指的 payload 键必须真的有人填 ----------------
    before = len(fails)
    for ev, key in outbox.AGGREGATE_KEY.items():
        payloads = events.get(ev, [])
        if not payloads:
            continue
        if not any(re.search(r'["\']' + re.escape(key) + r'["\']\s*:', s) for s in payloads):
            fails.append(f"{ev} 的聚合根映射指向 payload[{key}]，但没有任何一处入队真的填了它")
    if len(fails) == before:
        passed += 1

    # ---- 4. aggregate_id：模型 + 迁移 + enqueue 真的写了 ----------------
    before = len(fails)
    if "aggregate_id" not in model:
        fails.append("outbox 模型里没有 aggregate_id 列")
    if not any("aggregate_id" in f.read_text(encoding="utf-8") for f in mig.glob("*.py")):
        fails.append("没有哪条迁移加过 aggregate_id（新库靠 create_all、老库靠迁移，缺一不可）")
    if "aggregate_id=aggregate_of(" not in ob:
        fails.append("enqueue 没有真的写 aggregate_id（映射表成了摆设）")
    if len(fails) == before:
        passed += 1

    # ---- 5. idem_key：列 + 唯一索引 + 迁移 ----------------
    before = len(fails)
    if "idem_key" not in notif:
        fails.append("notifications 模型里没有 idem_key 列")
    if "uq_notifications_idem_key" not in notif:
        fails.append("notifications 模型里没有 idem_key 的**唯一索引**（幂等靠数据库，不靠先查再插）")
    if not any("idem_key" in f.read_text(encoding="utf-8") for f in mig.glob("*.py")):
        fails.append("没有哪条迁移加过 notifications.idem_key")
    if len(fails) == before:
        passed += 1

    # ---- 6. create_message 的三处形状 ----------------
    before = len(fails)
    if "idem_key: str | None = None," not in mc:
        fails.append("create_message 没有 idem_key 参数")
    # ⚠️ 锚**那个分支**（`if existing is not None:`），不是裸的 `Notification.idem_key == key`：
    #    后者在**撞键回查**那一支里也有一份 —— 反向验证第 ⑥ 条当场证明只锚前者会**永远绿**。
    if "if existing is not None:" not in mc or "Notification.idem_key == key" not in mc:
        fails.append("create_message 插入前没有按 idem_key 查过（会直接撞唯一索引）")
    if "db.begin_nested()" not in mc or "except IntegrityError:" not in mc:
        fails.append("create_message 没有处理并发撞键（要 SAVEPOINT —— 裸 rollback 会把业务写一起丢掉）")
    if len(fails) == before:
        passed += 1

    # ---- 7. publish_* 里的调用必须都带幂等键 ----------------
    keyed = [n for n, has in calls if has]
    missing = [n for n, has in calls if not has and n != "create_message"]
    if len(keyed) < MIN_KEYED:
        fails.append(f"只有 {len(keyed)} 处 create_message 带幂等键（<{MIN_KEYED}）—— 覆盖不全")
    if missing:
        fails.append("这些 publish 函数里的 create_message 没带幂等键（事件重投就会多发一条）："
                     + "、".join(sorted(set(missing))))
    if len(keyed) >= MIN_KEYED and not missing:
        passed += 1

    print(f"发件箱幂等：{len(events)} 种事件 / 聚合根映射 {len(outbox.AGGREGATE_KEY)} 条 + 例外 "
          f"{len(outbox.NO_AGGREGATE)} 条 / create_message 带键 {len(keyed)} 处")
    if fails:
        for f in fails:
            print("  ❌ " + f)
        return 1
    if check_mode:
        print("  ✅ 全部通过")
    else:
        print(f"  ✅ {passed} 组判据全部通过：聚合根从一张声明的映射表取、站内信靠唯一索引幂等、"
              "每个由事件驱动的 publish 都带幂等键。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
