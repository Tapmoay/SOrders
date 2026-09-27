# -*- coding: utf-8 -*-
"""**双实例 effective config 一致性 —— 本地真起两个进程演一遍**（R4-31）。

## 它回答的问题

⑧-a 出口条件 ② 要的是「两个实例 effective canary config 一致」。
在此之前，那条机制只被证到两个地方：
  · 判据里 `import app.main` **一个**进程，看指纹字段在不在；
  · 发布器里 `fingerprint_verdict` 这个**纯函数**，喂的是**手写的**元组。

⛔ 也就是说：**从来没有两个真实进程同时报过各自的指纹，然后再比对过。**
而这两件事各有一个只有真跑才暴露的坏法：
  · 指纹读的是**进程自己**的环境变量，还是某个全局/别处缓存的值？（读错了两边永远一样，判据全绿）
  · `/health` 上的 `pricing` 字段在**真实 HTTP 响应**里到底长什么样？

所以这个演练起**两个真的 uvicorn**，让它们各自报一次，再拿**发布器里同一个纯函数**判。

## ⛔ 它跑在本机、用 SQLite、用端口 18111/18112

⛔ 不碰生产、不碰 8000（本机可能正跑着开发后端）、不写仓库里的库（临时目录）。
⛔ 演练结束**两个进程都会被杀掉**（`finally` 里 kill + wait）。

## 用法

    python _tools/ops/_dual_instance_drill.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(ROOT / "_tools" / "ops"))
sys.path.insert(0, str(ROOT / "_tools" / "deploy"))
from _release import fingerprint_verdict  # noqa: E402  —— ⭐ 用发布器**同一个**纯函数，不另抄一份

PORTS = (18111, 18112)


def _prepare_db(db_url: str) -> bool:
    """先把迁移跑上（⛔ 与生产同一个顺序：先迁移、再起服务）。

    ⚠️ 为什么必须：应用是 **fail-closed** 的 —— 库里没有 `schema_versions` 时
       它**拒绝启动**（"数据库结构没准备好"）。第一版演练就是栽在这上面：
       两个实例 45 秒内一次都没起来，而我把它们的输出丢进了 DEVNULL，
       于是屏幕上只剩一句"起不来"，看不出为什么。
    """
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    r = subprocess.run([sys.executable, "-m", "app.migrations", "upgrade"],
                       cwd=str(BACKEND), env=env, capture_output=True, text=True,
                       # ⚠️ Windows 上不写 encoding 会按 GBK 解，中文日志当场 UnicodeDecodeError
                       #    （第一版就是这样：迁移其实成功了，屏幕上却写「没有输出」）。
                       encoding="utf-8", errors="replace")
    tail = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    print("    迁移：" + (tail[-1] if tail else "（没有输出）"))
    if r.returncode != 0:
        print("    ⛔ 迁移失败：\n" + (r.stdout or "")[-600:] + (r.stderr or "")[-600:])
    return r.returncode == 0


def _spawn(port: int, percent: int, db_url: str, logdir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    env["FREIGHT_PRICING_CANARY_PERCENT"] = str(percent)
    env.pop("SOCKET_REDIS_URL", None)
    log = open(logdir / ("instance_" + str(port) + ".log"), "w", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=str(BACKEND), env=env, stdout=log, stderr=subprocess.STDOUT,
    )


def _log_tail(logdir: Path, port: int) -> str:
    p = logdir / ("instance_" + str(port) + ".log")
    if not p.exists():
        return "（没有日志文件）"
    lines = [ln for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    return " ⏐ ".join(lines[-3:])[-500:]


def _wait_health(port: int, seconds: float = 45.0) -> dict | None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:" + str(port) + "/health", timeout=4) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001 —— 没起来就是没起来，继续等
            time.sleep(0.6)
    return None


def _round(label: str, values: list[int], target: str, db_url: str, logdir: Path,
           want_ok: bool) -> bool:
    """起两个实例（各自一个比例）→ 各自报一次 → 用发布器那个纯函数判。"""
    procs: list[subprocess.Popen] = []
    ok = False
    try:
        for port, pct in zip(PORTS, values):
            procs.append(_spawn(port, pct, db_url, logdir))
        fps: list[tuple[str, str]] = []
        for port, pct in zip(PORTS, values):
            body = _wait_health(port)
            if body is None:
                print("    ⛔ :" + str(port) + " 起不来（45 秒内 /health 没通）")
                print("       它的日志尾巴：" + _log_tail(logdir, port))
                return False
            pr = body.get("pricing") or {}
            got = pr.get("canary_percent")
            print("    :" + str(port) + "  env 给的是 " + str(pct)
                  + " ｜ /health 实际报的是 " + str(got)
                  + " ｜ resolver=" + str(pr.get("resolver")))
            fps.append(("127.0.0.1:" + str(port), str(got) if got is not None else ""))
        got_ok, why = fingerprint_verdict(fps, target)
        print("    " + ("✅ " if got_ok else "⛔ ") + label + " ⇒ " + ("过" if got_ok else "不过") + "：" + why)
        ok = (got_ok == want_ok)
        if not ok:
            print("    ⛔ 期望" + ("过" if want_ok else "不过") + "，实际相反")
    finally:
        for p in procs:
            p.kill()
            try:
                p.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass
    return ok


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    db_url = "sqlite:///" + (tmp / "dual.db").as_posix()
    print("== 双实例演练（本机，SQLite " + db_url + "）==")
    if not _prepare_db(db_url):
        return 1
    results: list[bool] = []

    print("")
    print("[1] 两个实例**比例不同**（A=30 / B=0）—— 这正是要拦的状态")
    results.append(_round("A=30 / B=0", [30, 0], "30", db_url, tmp, want_ok=False))

    print("")
    print("[2] 两个实例**比例相同、且与目标一致**（A=30 / B=30 / .env=30）")
    results.append(_round("A=30 / B=30", [30, 30], "30", db_url, tmp, want_ok=True))

    print("")
    print("[3] 两个实例一致、但**与目标对不上**（都 30，目标 50）")
    results.append(_round("都 30 / 目标 50", [30, 30], "50", db_url, tmp, want_ok=False))

    print("")
    print("=" * 60)
    bad = results.count(False)
    print("演练：" + str(len(results) - bad) + "/" + str(len(results)) + " 条符合预期")
    print("⭐ 注意：这证明的是**机制**（每个进程报自己的、比对拿得住坏状态），")
    print("   ⛔ 不是「生产上两个实例一致」—— 那要等发布之后由发布器自己核。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())