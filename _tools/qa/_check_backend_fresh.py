"""检查：本机跑着的后端进程是不是**比源码旧**（旧的话，所有实测结论都作废）。

## 为什么需要这条（2026-09-19 真实踩坑）
本机开发后端是 `uvicorn app.main:app --port 8000`（**没有 `--reload`**）。有一次进程在 22:33 启动，
之后 30 个后端文件在 23:26–23:46 被改（上一轮的车辆/司机绑定等），没人重启它。于是：
`_probe_core_flows.py` 打的是**旧代码**，报出 4 条"缺陷"（已派单还能再派一次、已送达还能撤回……），
我按它去读源码，读到的却是**已经修好的**新代码 —— 两边对不上，花了很久才意识到是"测的对象不对"。
假缺陷比漏缺陷更贵：它会把人引去改一段本来正确的代码。

## 判据（机器算，不写死任何路径/时间）
1. 从进程命令行里找出跑 `uvicorn` 且命令行含 `app.main` 的进程（Windows: CIM；Linux: /proc）；
2. 比较"进程启动时间"与 `backend/app/**/*.py` 里**最新的 mtime**；
3. 源码更新 → **红**（附上更新的那几个文件，便于判断是不是要紧）；
4. 后端没在跑 → 通过 + 说明（这不是缺陷，只是"这条判据这次没东西可查"）；
5. ⛔ **读不到进程表**（PowerShell 起不来 / 返回非零 / 拿不到输出）→ **红**，并说清"这是没读成，不是没有后端"。
   2026-09-21：原来这条会**崩**（`subprocess.run(...).stdout` 可能是 `None` → `AttributeError`），
   而崩之前它会先落进第 4 条 —— 也就是**拿一次失败的测量给出绿结论**（收尾流程每次都是
   "重启后端 + 立刻跑检查"，正好撞在这个窗口上）。现在两条路分开说。

退出码：0=一致（或后端确实没跑）；1=后端比源码旧，或没读成。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND_APP = ROOT / "backend" / "app"


class ProcessListUnreadable(RuntimeError):
    """读不到进程表 —— **这不是"没有后端在跑"**，所以不许给绿结论（fail-closed）。"""


def _python_files() -> list[Path]:
    return [p for p in BACKEND_APP.rglob("*.py") if "__pycache__" not in p.parts]


def _uvicorn_processes() -> list[tuple[int, datetime, str]]:
    """返回本机在跑的 uvicorn(app.main) 进程 [(pid, 启动时间, 命令行)]。

    ⛔ 读不到进程表时**抛 [ProcessListUnreadable]**，不许返回空表 ——
       空表在这条判据里的含义是"后端没在跑"（green），而"没读成"与"没在跑"是两件事。
    """
    out: list[tuple[int, datetime, str]] = []
    if sys.platform == "win32":
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise ProcessListUnreadable(f"起不了 PowerShell：{type(e).__name__}: {e}") from e
        # ⚠️ 这里**曾经**直接写 `.stdout.strip()`：实测拿到过 None（2026-09-21 收尾时崩了一次），
        #    于是整个检查以 AttributeError 结束 —— 那不是结论，收尾清单上只看到一行报错。
        if proc.stdout is None:
            raise ProcessListUnreadable("PowerShell 没有输出（stdout 为空对象，不是空字符串）")
        if proc.returncode != 0:
            raise ProcessListUnreadable(
                f"PowerShell 退出码 {proc.returncode}：{(proc.stderr or '').strip()[:200]}"
            )
        raw = proc.stdout.strip()
        import json
        try:
            # ⚠️ 管道为空（本机没有 python.exe）时 `ConvertTo-Json` 什么都不打印 → 空串 → [] ✅
            data = json.loads(raw) if raw else []
        except ValueError as e:
            raise ProcessListUnreadable(f"进程表不是合法 JSON：{e}；原样输出：{raw[:200]}") from e
        if isinstance(data, dict):
            data = [data]
        for it in data:
            cmd = (it.get("CommandLine") or "")
            if "uvicorn" not in cmd or "app.main" not in cmd:
                continue
            # CreationDate 形如 /Date(1758...)/ 或 ISO 串
            cd = it.get("CreationDate")
            when = None
            if isinstance(cd, str):
                if cd.startswith("/Date(") and cd.endswith(")/"):
                    when = datetime.fromtimestamp(int(cd[6:-2][:13]) / 1000)
                else:
                    try:
                        when = datetime.fromisoformat(cd.replace("Z", "+00:00")).replace(tzinfo=None)
                    except ValueError:
                        when = None
            if when is not None:
                out.append((int(it.get("ProcessId") or 0), when, cmd))
    else:  # 为了在服务器上也能直接跑
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            try:
                cmd = (pid_dir / "cmdline").read_bytes().decode("utf-8", "replace").replace("\x00", " ")
                if "uvicorn" not in cmd or "app.main" not in cmd:
                    continue
                start = int((pid_dir / "stat").read_text().split()[21])
                boot = float(Path("/proc/uptime").read_text().split()[0])
                when = datetime.fromtimestamp(datetime.now().timestamp() - (boot - start / 100.0))
                out.append((int(pid_dir.name), when, cmd))
            except (OSError, ValueError, IndexError):
                continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="检查模式（同默认行为）")
    ap.parse_args()

    files = _python_files()
    if not files:
        print(f"？ 找不到后端源码目录：{BACKEND_APP}")
        return 0
    newest = max(files, key=lambda p: p.stat().st_mtime)
    newest_at = datetime.fromtimestamp(newest.stat().st_mtime)

    try:
        procs = _uvicorn_processes()
    except ProcessListUnreadable as e:
        # ⛔ fail-closed：读不到就给红，并说清"这是没读成，不是没有后端"
        print("❌ 读不到本机进程表 —— **这不是「后端没在跑」，是这次没读成**，所以不敢给结论：")
        print(f"   {e}")
        print("   修法：重跑一次这条检查；持续失败时手工看一眼进程：")
        print("     Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -like '*uvicorn*' }")
        return 1
    if not procs:
        print("✅ 本机没有在跑的后端（uvicorn app.main）—— 这条判据这次没东西可查。")
        print("   要跑实测探针（_tools/qa/_probe_*.py、真机联调）之前，请先起后端。")
        return 0

    stale: list[str] = []
    for pid, started, cmd in procs:
        if newest_at > started:
            stale.append(
                f"PID {pid}：{started:%Y-%m-%d %H:%M:%S} 启动，而源码在 {newest_at:%Y-%m-%d %H:%M:%S} 还被改过"
            )

    if not stale:
        pid, started, _ = procs[0]
        print(f"✅ 后端进程比源码新（PID {pid} 启动于 {started:%Y-%m-%d %H:%M:%S}，"
              f"最新源码 {newest_at:%Y-%m-%d %H:%M:%S}）。")
        return 0

    print("❌ 本机后端跑的是**旧代码** —— 现在拿它做的任何实测结论都不作数：")
    for line in stale:
        print("   -", line)
    changed = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:8]
    print("   最近改过的后端文件：")
    for p in changed:
        print(f"     {datetime.fromtimestamp(p.stat().st_mtime):%H:%M:%S}  {p.relative_to(ROOT)}")
    print("   修法：重启后端（本机开发没有 --reload）：")
    print("     Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -like '*uvicorn*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    print("     cd backend; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
    print("   ┆ 注：跑过 `_reverse_verify_all.py` 之后**必然**报这条（它逐个注入再还原，"
          "还原会把文件的 mtime 全部刷新，而内容其实没变）。那不是误报不了——")
    print("   ┆    反过来说，「跑完反向验证就重启后端」本来就该做：那些文件在被注入的那一刻是坏的。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
