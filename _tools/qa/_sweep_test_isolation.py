#!/usr/bin/env python3
"""_sweep_test_isolation.py —— 逐个测试文件单独跑，量「用例之间有没有偷偷互相依赖」。

## 为什么要这个工具（2026-09-25 的教训，花了整整几轮 CI 盲猜）
本套件是「每个 xdist worker 一个 SQLite 库」，而**同一个文件里的用例会共享那个库的状态**。
于是有两种**假绿**，它们既不红也不报错，只在换了执行顺序/分发方式之后才现形：

1. **靠别的文件的数据通过**：某个用例断言「库里有一条 X 动作的日志」，而那个取日志的助手是全库
   按动作码查的 —— 它自己那一步其实被端点**正确地拒绝了**，喂饱断言的是别的用例留下的同码日志。
2. **靠同文件里前一个用例通过**：前一个用例建好的地点/供应商/单据，被后一个用例当成既有条件。

CI 上那两个 job 红了整整几轮、而本地一直绿，根子就是这两类（已修掉两处，见计划表第 42/43 轮）。
这个工具把这两类**量出来**：每个文件**单独**跑（= 断掉跨文件依赖），--reverse 再把用例**倒序**跑
（= 断掉「前一个用例先跑」这个前提）。

## 口径
· 每个文件跑之前**把该 worker 的测试库挪走**（tests/.test_dbs/*.db → 归档目录），
  所以每个文件都从空库开始 —— 否则前一个文件的残留会让后一个文件「看起来没问题」；
· 挪走而不是原地删除（本仓库规矩：删除要可恢复）；
· 超时 / 收集不到用例 → 算**失败**（算不出真值就是红），不许悄悄跳过；
· 非零退出＝有文件单独跑不过。

用法：
    python _tools/qa/_sweep_test_isolation.py                # 每个文件单独跑（约 10~15 分钟）
    python _tools/qa/_sweep_test_isolation.py --reverse      # 再把用例倒序跑一遍
    python _tools/qa/_sweep_test_isolation.py --only place   # 只跑文件名含 place 的
    python _tools/qa/_sweep_test_isolation.py --json out.json
⛔ 不要声明 --check：那会被 _check_all.py 自动收进必跑组，而它一次要十几分钟。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

#: ⛔ 本机（Windows）上 pytest 默认按 GBK 写 stdout，而我们用 encoding="utf-8" 去解 ——
#: 于是**中文用例名会变成乱码**，倒序模式再把那些乱码当 node id 传回去，pytest 只回一句
#: 「no tests ran」。2026-09-25 实测踩到（第一个文件就有中文用例名）。
#: 所以子进程一律带上这两个变量，让 pytest 自己按 UTF-8 写。
RUN_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "backend"
TESTS = BACKEND / "tests"
DBDIR = TESTS / ".test_dbs"


def _park_dbs(run_index: int, archive: Path) -> None:
    """把这一轮的测试库挪去归档（⛔ 不原地删 —— 本仓库规矩：删除要可恢复）。"""
    if not DBDIR.exists():
        return
    archive.mkdir(parents=True, exist_ok=True)
    for p in DBDIR.glob("*.db"):
        try:
            shutil.move(str(p), str(archive / (str(run_index) + "_" + p.name)))
        except OSError:
            pass


def _run(args: list[str], timeout: int) -> tuple[int, str]:
    try:
        r = subprocess.run(args, cwd=str(BACKEND), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=RUN_ENV)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 99, "TIMEOUT"


def _last_line(out: str) -> str:
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    return lines[-1] if lines else "（没有输出）"


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description="测试隔离度扫描（每个文件单独跑）")
    ap.add_argument("--reverse", action="store_true",
                    help="再把每个文件里的用例**倒序**跑一遍（断掉「前一个用例先跑」这个前提）")
    ap.add_argument("--only", default="", help="只跑文件名含这个片段的")
    ap.add_argument("--json", dest="json_out", default="", help="把结果写成 JSON")
    ap.add_argument("--max-cmd", type=int, default=25000,
                    help="倒序模式的命令行长度上限（超过就跳过并如实记下来，不假装通过）")
    args = ap.parse_args(argv)

    files = sorted(p.name for p in TESTS.glob("test_*.py") if args.only in p.name)
    if not files:
        print("⛔ 一个测试文件都没匹配到（--only " + args.only + "）—— 判据会空转，停。")
        return 1
    archive = ROOT / "_archive" / "_sweep_test_dbs"
    print("要跑 " + str(len(files)) + " 个测试文件"
          + ("（每个再倒序跑一遍）" if args.reverse else "") + "；测试库归档到 " + str(archive))
    print("")

    rows: list[dict] = []
    for i, name in enumerate(files, 1):
        _park_dbs(i, archive)
        rc, out = _run([sys.executable, "-m", "pytest", "tests/" + name, "-q", "--tb=no",
                        "-p", "no:cacheprovider"], timeout=900)
        rows.append({"file": name, "mode": "alone", "rc": rc, "tail": _last_line(out)})
        print(("OK   " if rc == 0 else "FAIL ") + name.ljust(52) + _last_line(out)[:70], flush=True)

        if not args.reverse:
            continue
        crc, cout = _run([sys.executable, "-m", "pytest", "tests/" + name, "--collect-only", "-q",
                          "-p", "no:cacheprovider"], timeout=300)
        ids = [x.strip() for x in cout.splitlines() if "::" in x]
        if crc != 0 or not ids:
            rows.append({"file": name, "mode": "reverse", "rc": 1,
                         "tail": "收集不到用例（算失败：算不出真值就是红）"})
            print("FAIL " + name.ljust(52) + "倒序：收集不到用例")
            continue
        ids.reverse()
        if sum(len(x) + 1 for x in ids) > args.max_cmd:
            rows.append({"file": name, "mode": "reverse", "rc": 2,
                         "tail": "跳过：命令行太长（" + str(len(ids)) + " 个用例）"})
            print("SKIP " + name.ljust(52) + "倒序：命令行太长（" + str(len(ids)) + " 个用例）")
            continue
        _park_dbs(i, archive)
        rrc, rout = _run([sys.executable, "-m", "pytest", *ids, "-q", "--tb=no",
                          "-p", "no:cacheprovider"], timeout=900)
        rows.append({"file": name, "mode": "reverse", "rc": rrc, "tail": _last_line(rout)})
        print(("OK   " if rrc == 0 else "FAIL ") + name.ljust(52) + "倒序：" + _last_line(rout)[:60],
              flush=True)

    bad = [r for r in rows if r["rc"] != 0 and r["rc"] != 2]
    skipped = [r for r in rows if r["rc"] == 2]
    print("")
    print("单跑不过的：" + str(len(bad)) + " / " + str(len(rows)) + "（跳过 " + str(len(skipped)) + "）")
    for r in bad:
        print("   " + r["file"] + " [" + r["mode"] + "] " + r["tail"][:100])
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print("结果已写入 " + args.json_out)
    if bad:
        return 1
    print("✅ 每个文件单独跑（含倒序）都通过：用例之间没有互相依赖")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())