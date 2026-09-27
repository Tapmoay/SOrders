# -*- coding: utf-8 -*-
"""**测试库隔离探针**（R4-47）：两个进程是不是**真的**连在各自的库上。

## ⛔ 为什么不能只比字符串

「get_db_path() 返回一个路径字符串」。最省事的"证明"是：

    进程 A 算出来的路径  !=  进程 B 算出来的路径   ⇒ 判定"隔离了"

**那不是证明。** 字符串不同而**真实连接仍指向同一个文件**的写法多得是
（相对路径 vs 绝对路径、大小写、符号链接、sqlite:/// 前后斜杠、file: URI…）。
一旦落进那种写法，"判据证明了隔离、实际仍在互踩" —— 与本项目反复出现的**假绿**是同一个形状。

所以这个探针让每个子进程**真的连上自己算出来的那个库、写一行、再读回来**，
判据落在**读回来的内容**上：

    每个子进程读回来**只看得见自己那一行**  ⇒  真的各自一份库

## 两种模式

    python _tools/qa/_probe_test_db_isolation.py                 # 用当前 get_db_path()
    python _tools/qa/_probe_test_db_isolation.py --force-shared   # 复现旧命名（所有进程算成同一个）

⚠️ --force-shared 是**阴性对照**：它必须在**同一份判据**下判红。
一条只会判绿的判据等于没有判据 —— 这是本仓库的老规矩。

⛔ 探针跑完**自己把库删掉**（--keep 可留档）—— 否则每跑一次就往 .test_dbs 里多留几份。

用法（父进程自己拉子进程，⛔ 不需要外面再套并发）：
    python _tools/qa/_probe_test_db_isolation.py [--children 3] [--hold 1200]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "backend" / "tests"
SELF = Path(__file__).resolve()

#: 阴性对照模式用的旧名字（复现 R4-45 那次 884 errors 的成因）。
LEGACY_NAME = "sorders_test_master.db"


def _child(tag: str, force_shared: bool, hold_ms: int, keep: bool = False) -> int:
    """子进程：算出路径 → **真的连上去** → 写一行 → 睡一会 → 读回来。"""
    sys.path.insert(0, str(TESTS))
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        import conftest  # noqa: E402  —— 真身：路径就是它算的
        from sqlalchemy import create_engine, text  # noqa: E402
        from app.models.base import Base  # noqa: E402
    except Exception as exc:  # noqa: BLE001
        print("ERROR|" + tag + "|import|" + type(exc).__name__ + ": " + str(exc)[:160])
        return 1

    p = Path(conftest.get_db_path())
    if force_shared:
        p = p.parent / LEGACY_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    print("CHILD|" + tag + "|" + str(os.getpid()) + "|" + str(p))
    sys.stdout.flush()

    try:
        engine = create_engine("sqlite:///" + p.as_posix(),
                               connect_args={"check_same_thread": False})
        # ⚠️ 与 conftest 一样先建**真实结构**：并发撞库就是这样撞起来的
        Base.metadata.create_all(bind=engine)
        with engine.begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS _iso_probe(tag TEXT, pid INTEGER)"))
            c.execute(text("INSERT INTO _iso_probe(tag, pid) VALUES (:t, :p)"),
                      {"t": tag, "p": os.getpid()})
        time.sleep(hold_ms / 1000.0)          # 留出真实的并发窗口
        with engine.connect() as c:
            seen = [r[0] for r in c.execute(text("SELECT tag FROM _iso_probe ORDER BY tag"))]
        print("ROWS|" + tag + "|" + ",".join(seen))
    except Exception as exc:  # noqa: BLE001
        print("ERROR|" + tag + "|db|" + type(exc).__name__ + ": " + str(exc)[:160])
        return 1
    finally:
        # ⛔ 探针**自己收拾干净**（否则每跑一次就往 .test_dbs 里多留几份库）。
        #    ⚠️ 先 dispose 再删：Windows 上 SQLite 占着句柄，直接 unlink 会 PermissionError
        #    —— 这正是 R4-47 在 conftest 那边踩到的同一个坑。
        if not keep:
            try:
                locals().get("engine") is not None and engine.dispose()
            except Exception:  # noqa: BLE001
                pass
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    return 0


def main() -> int:
    if "--child" in sys.argv:
        i = sys.argv.index("--child")
        tag = sys.argv[i + 1]
        hold = int(sys.argv[sys.argv.index("--hold") + 1]) if "--hold" in sys.argv else 1200
        return _child(tag, "--force-shared" in sys.argv, hold, "--keep" in sys.argv)

    n = int(sys.argv[sys.argv.index("--children") + 1]) if "--children" in sys.argv else 3
    hold = int(sys.argv[sys.argv.index("--hold") + 1]) if "--hold" in sys.argv else 1200
    force = "--force-shared" in sys.argv

    print("== 测试库隔离探针 ==" + ("　⛔ 阴性对照：把所有进程都算成同一个旧名字" if force else ""))
    print("")

    # 三个子进程**同时**起（不是 for 循环里挨个跑 —— 那样永远撞不上）
    procs = []
    for k in range(n):
        cmd = [sys.executable, str(SELF), "--child", "p" + str(k), "--hold", str(hold)]
        if force:
            cmd.append("--force-shared")
        if "--keep" in sys.argv:
            cmd.append("--keep")
        procs.append(subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, encoding="utf-8", errors="replace",
                                      cwd=str(ROOT)))
    outs = [p.communicate()[0] or "" for p in procs]

    paths: dict[str, str] = {}
    pids: dict[str, str] = {}
    seen: dict[str, list[str]] = {}
    errors: list[str] = []
    for out in outs:
        for ln in out.splitlines():
            parts = ln.split("|")
            if parts[0] == "CHILD" and len(parts) >= 4:
                pids[parts[1]], paths[parts[1]] = parts[2], parts[3]
            elif parts[0] == "ROWS" and len(parts) >= 3:
                seen[parts[1]] = [x for x in parts[2].split(",") if x]
            elif parts[0] == "ERROR":
                errors.append("|".join(parts[1:4]))

    for tag in sorted(paths):
        print("  " + tag + "  pid=" + pids[tag].ljust(7) + " db=" + paths[tag])
        print("        读回来：" + str(seen.get(tag, ["(没读到)"])))
    for e in errors:
        print("  ⛔ 子进程报错：" + e)
    print("")

    fails: list[str] = []
    if errors:
        fails.append("有子进程直接报错（" + str(len(errors)) + " 个）—— 这正是并发撞库的形状")
    if len(set(paths.values())) != len(paths):
        dup = sorted({p for p in paths.values() if list(paths.values()).count(p) > 1})
        fails.append("两个进程算出了**同一个**库文件：" + str(dup))
    if len(set(pids.values())) != len(pids):
        fails.append("子进程 PID 不该相同（探针本身有问题）")
    for tag, rows in seen.items():
        if rows != [tag]:
            fails.append("⛔ " + tag + " **读到了别人的行**：" + str(rows)
                         + " ⇒ 字符串也许不同，但真实连接指向同一份库（只比字符串会漏掉它）")

    if fails:
        print("❌ 判据不成立（" + str(len(fails)) + " 条）：")
        for f in fails:
            print("   - " + f)
        return 1
    print("✅ 全部成立：" + str(len(paths)) + " 个进程、" + str(len(set(paths.values())))
          + " 份不同的库文件，且**每一个都只读到了自己写的那一行**"
          "（⛔ 判据落在真实连接上，不是路径字符串上）")
    print("   " + json.dumps({"paths": sorted(set(paths.values())), "pids": sorted(pids.values())},
                             ensure_ascii=False)[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
