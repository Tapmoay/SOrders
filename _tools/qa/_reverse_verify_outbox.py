#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_outbox.py`（事务发件箱，整改报告 §10）真的抓得住那几条。

## 为什么这条红线特别需要反向验证
发件箱的失效方式**全是静默的**：`enqueue` 里多一个 `commit`（事件不再属于业务事务）、
失败分支被改成"标记成功"（丢事件换了个地方发生）、派发表漏登记一个事件类型
（事件被重试到放弃，业务侧一点异常都没有）—— 这些**都不会让任何功能报错**。
所以这条红线的价值全在"它真的会红"上，而它此前**一条反向验证都没有**（2026-09-25 补）。

## 六种破坏（每一种都必须让红线当场红，且报出**对应**那条判据）
| # | 注入 | 现实里谁会这么干 |
| --- | --- | --- |
| ① | `enqueue` 里加一个 `commit` | 「入队完顺手提交一下」→ 业务回滚了事件还在 |
| ② | `mark_sent` 挪到 `deliver` 之前 | 「先把状态改了再发」→ 没发出去也被标成功 |
| ③ | 导出完成那条链路又加回直接推 | 老代码的形状（本轮刚切掉的那一个） |
| ④ | 派发表里改掉一个事件类型名 | 改名时只改了入队那一侧 |
| ⑤ | 模型里少一列（`next_attempt_at` 改名） | 加字段时只改了模型、没改迁移 |
| ⑥ | 迁移不再 `checkfirst` | 「表已经建过了，去掉这个参数」→ 重跑就炸 |

⚠️ 与仓库里其它 `_reverse_verify_*.py` 同一套纪律：按**字节**备份/还原、跑完逐文件核对、
⛔ 全程不碰 `git checkout --`（那会在真有改动时抹掉工作）。

用法：python _tools/qa/_reverse_verify_outbox.py
      python _tools/qa/_reverse_verify_outbox.py --list
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_outbox.py"
CORE = "backend/app/core/outbox.py"
MODEL = "backend/app/models/outbox.py"
MIG = "backend/app/migrations/002_outbox_events.py"
EXPORT = "backend/app/services/ledger_export_worker.py"
MAIN = "backend/app/main.py"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① enqueue 里加一个 commit（事件不再属于业务事务）",
        CORE,
        "    db.add(\n        OutboxEvent(\n            event_type=event_type,",
        "    db.commit()\n    db.add(\n        OutboxEvent(\n            event_type=event_type,",
        "enqueue 里出现了 commit",
    ),
    (
        "② mark_sent 挪到 deliver 之前（没发出去也被标成功）",
        CORE,
        "    for row in claim(db, limit=limit):\n        try:\n            deliver(to_event(row))",
        "    for row in claim(db, limit=limit):\n        mark_sent(db, row)\n        try:\n            deliver(to_event(row))",
        "dispatch 里 mark_sent 出现在 except 之前",
    ),
    (
        "③ 导出完成那条链路又加回直接推（老代码的形状）",
        EXPORT,
        '        outbox.enqueue(db, "notifications.created", {"notification_id": n.id})',
        '        await emit_to_user(n.recipient_id, "notification", {})\n'
        '        outbox.enqueue(db, "notifications.created", {"notification_id": n.id})',
        "绕开发件箱直接推",
    ),
    (
        "④ 派发表里改掉一个事件类型名（改名时只改了入队那一侧）",
        MAIN,
        '    if event.event_type == "notifications.created":',
        '    if event.event_type == "notifications.created_v2":',
        "这些事件类型有人入队、没人处理",
    ),
    (
        "⑤ 模型里少一列（next_attempt_at 改名，退避就写不进去）",
        MODEL,
        "    next_attempt_at: Mapped[datetime] = mapped_column(",
        "    next_try_at: Mapped[datetime] = mapped_column(",
        "模型少了这些列",
    ),
    (
        "⑥ 迁移不再 checkfirst（重跑建表就炸）",
        MIG,
        "OutboxEvent.__table__.create(bind=engine, checkfirst=True)",
        "OutboxEvent.__table__.create(bind=engine, checkfirst=False)",
        "迁移没有从模型建表",
    ),
]

CRLF = chr(13) + chr(10)


class Sandbox:
    """按**字节**记账的注入沙箱：每次注入前先还原上一轮，跑完再逐字节核对。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, rel: str, old: str, new: str) -> None:
        p = ROOT / rel
        if not p.exists():
            raise ValueError("找不到 " + rel)
        self.saved.setdefault(p, p.read_bytes())
        raw = p.read_bytes()
        crlf = CRLF.encode("utf-8") in raw
        text = raw.decode("utf-8")
        if crlf:
            text = text.replace(CRLF, chr(10))
        if text.count(old) != 1:
            raise ValueError(rel + " 里锚点出现 " + str(text.count(old)) + " 次（要恰好一次）")
        text = text.replace(old, new, 1)
        p.write_bytes((text.replace(chr(10), CRLF) if crlf else text).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(CHECK), "--check"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(CASES, 1):
            print(str(i) + ". " + name + "\n      " + rel + "   ← 期望被「" + want + "」抓到")
        return 0

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条红线就没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时红线是绿的 —— " + last.strip())
        for label, rel, old, new, want in CASES:
            sb.restore()
            try:
                sb.apply(rel, old, new)
                code, out = run_check()
            except ValueError as exc:
                print("  [SKIP] " + label + " —— " + str(exc))
                bad += 1
                continue
            finally:
                sb.restore()
            hit = code != 0 and ("BAD " in out) and (want in out)
            if hit:
                print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
            else:
                bad += 1
                why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("BAD")][:5]:
                    print("       红线实际报的：" + ln)
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    dirty = sb.dirty()
    if dirty:
        bad += 1
        print("⛔ 跑完没逐字节还原：" + "、".join(dirty))
    total = len(CASES) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立：发件箱的每一类静默失效都会被对应的判据抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
