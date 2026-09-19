"""反向验证「后台任务不许自建事件循环」这条红线**真的会红**（R14-7）。

## 为什么这条要反向验证
它的判据有两种"看起来在查、其实没查"的失效方式：
- 判据只钉了 `run_ledger_export_job_task` 一个名字（今天绿，明天新加一个同步任务照样绿）；
- 扫描目录指错 / 正则不匹配实际写法 → 数量判据之前就空转了。

所以四种破坏各注入一次：**目标退回同步 def**（真缺陷的形状）、**在别处自建事件循环**、
**目标函数改名**（解析不到）、**扫描目录指错**（清单空转）。

⚠️ 与 `_reverse_verify_round12.py` 同一套纪律：快照/还原都按**字节**做，
跑完逐个文件核对逐字节一致（曾经有一次注入把 `order_flow.py` 的守卫留在源码里）。

用法：python _tools/qa/_reverse_verify_background_tasks.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_background_tasks.py"

WORKER = "backend/app/services/ledger_export_worker.py"
NOTIFY = "backend/app/api/v1/notifications.py"
LEDGER = "backend/app/api/v1/ledger.py"
CHECKREL = "_tools/qa/_check_background_tasks.py"

CASES: list[tuple[str, str, object]] = [
    (
        "账本导出任务退回同步 def（R14-7 的真实形状：被丢进线程池 → 跨事件循环用 Redis）",
        WORKER,
        lambda s: s.replace(
            "async def run_ledger_export_job_task(job_id: int) -> None:",
            "def run_ledger_export_job_task(job_id: int) -> None:",
            1,
        ),
    ),
    (
        "另一个后台任务也退回同步 def（证明不是只钉了一个名字）",
        NOTIFY,
        lambda s: s.replace("async def _bg_emit_unread(", "def _bg_emit_unread(", 1),
    ),
    (
        "在别处（ledger.py）自建事件循环",
        LEDGER,
        lambda s: s.replace(
            "async def _bg_push_ledger_shipper(shipper_id: int) -> None:",
            "async def _bg_push_ledger_shipper(shipper_id: int) -> None:\n"
            "    import asyncio\n"
            "    asyncio.new_event_loop()  # 注入：自建事件循环\n",
            1,
        ),
    ),
    (
        "注册点用另一个名字自建事件循环（run_until_complete 变体）",
        NOTIFY,
        lambda s: s.replace(
            "async def _bg_emit_unread(",
            "def _loop_smuggler():\n    asyncio.get_event_loop().run_until_complete(None)\n\n\n"
            "async def _bg_emit_unread(",
            1,
        ),
    ),
    (
        "后台任务目标改名（检查解析不到定义 → 必须报红，不能当没看见）",
        NOTIFY,
        lambda s: s.replace("async def _bg_emit_unread(", "async def _bg_emit_unread_renamed(", 1),
    ),
    (
        "扫描目录指错（一个文件都扫不到 → 判据空转）",
        CHECKREL,
        lambda s: s.replace('APP = ROOT / "backend/app"', 'APP = ROOT / "backend/app/nope"', 1),
    ),
]


def run_check(target: Path) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(target)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    touched = sorted({rel for _l, rel, _m in CASES})
    originals: dict[str, bytes] = {}
    for rel in touched:
        originals[rel] = (ROOT / rel).read_bytes()

    code, out = run_check(CHECK)
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    for label, rel, mutate in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        original = original_bytes.decode("utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（锚点变了）")
            print(f"  [SKIP] {label}")
            continue
        # 目标文件就是红线脚本自己时，写一份副本跑，避免"检查自己在被改的状态下运行"。
        run_target = CHECK
        tmp: Path | None = None
        try:
            if rel == CHECKREL:
                tmp = path.with_suffix(".py.injected")
                tmp.write_bytes(mutated.encode("utf-8"))
                run_target = tmp
            else:
                path.write_bytes(mutated.encode("utf-8"))
            code, out = run_check(run_target)
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()
            path.write_bytes(original_bytes)
        if code != 0:
            print(f"  [OK] {label} → 红线报红")
        else:
            fails.append(f"{label}：注入之后红线**仍然全绿**（判据没牙）")
            print(f"  [MISS] {label} → 仍然全绿")

    # ---- 还原检查：逐字节 ----
    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
