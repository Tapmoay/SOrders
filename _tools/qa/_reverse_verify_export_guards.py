#!/usr/bin/env python3
"""反向验证 _tools/qa/_check_export_guards.py（导出产物的隔离 / 清理 / 单点）真的抓得住那几条。

## 为什么这条红线必须有反向验证
它守的是**匿名可下载**：`/static/uploads/` 在生产是 nginx 用 alias **直出磁盘**的（请求根本不到
uvicorn），所以应用层那句 404 拦不住它 —— 历史产物（老文件名可枚举）匿名就能拖走别人的账本。
这类判据全是「某个字符串必须在源码里」，而那正是**注释就能满足**的形状：
本项目已经栽过 4 次「判据被自己的文档满足」（checkfirst / emit_notification / _mysql_session_utc /
一段 SQL 的文档举例）。所以逐条把接线拆掉，看它是不是真的会红。

## 五条注入（每条都必须让红线当场红）
| # | 注入 | 现实里谁会这么干 |
| --- | --- | --- |
| ① | 后端又出现 `makedirs("…/uploads/exports")` | 新写导出时顺手建目录（R12-A3 的原形） |
| ② | 部署脚本里那条 nginx deny 没了 | 重写部署脚本时漏了它 |
| ③ | 保留治理里**函数还在、任务表那行没了** | 重构任务表时把这一行删掉（函数在≠会跑） |
| ④ | `ledger_export_paths.py` 少一个定位函数 | 命名/定位规则又被打散 |
| ⑤ | 扫描器失配（一个后端文件都扫不到） | 路径写错 → 判据空转 |

⚠️ 与仓库里其它反向验证同一套纪律：按**字节**备份/还原、跑完逐文件核对、不碰 git checkout --。

用法：python _tools/qa/_reverse_verify_export_guards.py
      python _tools/qa/_reverse_verify_export_guards.py --list
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
CHECK = ROOT / "_tools/qa/_check_export_guards.py"
API = "backend/app/api/v1/expenses.py"
DEPLOY = "_tools/deploy/_fix_nginx_static.py"
RETENTION = "backend/app/services/data_retention.py"
PATHS = "backend/app/services/ledger_export_paths.py"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 后端又出现「在公开静态目录下建 exports/」的调用",
        API,
        "from fastapi import APIRouter",
        "from fastapi import APIRouter\n\n\ndef _probe_public_exports_dir() -> None:\n"
        "    import os\n    os.makedirs(\"uploads/exports\", exist_ok=True)",
        "仍在创建公开静态目录下的 exports/",
    ),
    (
        "② 部署脚本里那条 nginx deny 没了",
        DEPLOY,
        # 只删**新机器那条路**（NEW_BLOCK）里的 deny —— 老机器那条（re.subn 的 payload）还在。
        # ⚠️ 判据要的就是「两条路都得带」：原来只查「这个字符串在不在这份源码里」，
        #    于是删掉一条、甚至只看文档字符串里那段举例，判据都是绿的（2026-09-25 实测）。
        "    location ^~ /static/uploads/exports/ {\n        return 404;\n    }\n\n"
        "    location /static/uploads/ {",
        "    location /static/uploads/ {",
        "部署脚本没有给 /static/uploads/exports/ 加 deny",
    ),
    (
        "③ 保留治理：函数还在、**任务表那行**没了（函数在 ≠ 会跑）",
        RETENTION,
        "        (\"exports_purged\", purge_old_export_files),",
        "        # (\"exports_purged\", purge_old_export_files),  但没挂进任务表",
        "没有挂进每日任务表",
    ),
    (
        "④ ledger_export_paths.py 少一个定位函数（命名/定位被打散）",
        PATHS,
        "def find_export_file(",
        "def locate_export_file(",
        "缺少 def find_export_file",
    ),
    (
        "⑤ 扫描器失配：一个后端文件都扫不到（判据空转）",
        "_tools/qa/_check_export_guards.py",
        'for f in BACKEND.rglob("*.py"):',
        'for f in BACKEND.rglob("*.py_none"):',
        "判据在空转",
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
    proc = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
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
            hit = code != 0 and (want in out)
            if hit:
                print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
            else:
                bad += 1
                why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("-")][:4]:
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
    print(f"✅ {total}/{total} 全部成立：导出产物的隔离/清理/单点每拆一处都会红")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())