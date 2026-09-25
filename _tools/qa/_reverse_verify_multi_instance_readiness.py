#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_multi_instance_readiness.py` 真的抓得住那几类错误。

## 五种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 把一道「已过」的门改成「没做」却不写理由 | 红：没写（或写得太短） |
| ② | must_contain 里加一个源码里根本没有的形状 | 红：证据源码里找不到 |
| ③ | evidence 指向一个不存在的文件 | 红：证据文件不存在 |
| ④ | status 写成 done / not-done 之外的值 | 红：只能是 done / not-done |
| ⑤ | 门数下限失守（文档被掏空却不喊） | 红：只登记到 |

⚠️ 与仓库里其它 `_reverse_verify_*.py` 同一套纪律：按**字节**备份/还原、跑完逐文件核对、
⛔ 全程不碰 `git checkout --`。
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
CHECK = ROOT / "_tools/qa/_check_multi_instance_readiness.py"
DOC = "docs/MULTI_INSTANCE_READINESS.md"
CHK = "_tools/qa/_check_multi_instance_readiness.py"

REAL_MARK = "def get_request_id"
REAL_EV = "backend/app/core/request_id.py"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 把一道「已过」的门改成「没做」却不写理由",
        DOC, "status: done" + chr(10) + "evidence: " + REAL_EV,
        "status: not-done" + chr(10) + "evidence: " + REAL_EV,
        "没写（或写得太短）",
    ),
    (
        "② must_contain 里加一个源码里根本没有的形状",
        DOC, "must_contain: def get_request_id, request_id",
        "must_contain: def get_request_id, request_id, zzz_nope_marker",
        "证据源码里找不到",
    ),
    (
        "③ evidence 指向一个不存在的文件",
        DOC, "evidence: backend/app/core/request_id.py, backend/app/models/operation_log.py",
        "evidence: backend/app/core/request_id_gone.py, backend/app/models/operation_log.py",
        "证据文件不存在",
    ),
    (
        "④ status 写成 done / not-done 之外的值",
        DOC,
        "中文名: 并发 / 跨主机迁移协调" + chr(10) + "status: done",
        "中文名: 并发 / 跨主机迁移协调" + chr(10) + "status: maybe",
        "只能是 done / not-done",
    ),
    (
        "⑤ 门数下限失守（文档被掏空却不喊）",
        CHK, "MIN_GATES = 10", "MIN_GATES = 99",
        "只登记到",
    ),
]

CRLF = chr(13) + chr(10)


class Sandbox:
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
        if old not in text:
            # 第二轮 R2-05：报表源码搬进了 `services/reports/` —— **锚点跟着搬家走**。
            # 判据读的是「并集」（`_airepo.reports_source`），注入器也必须打在那份含原文的文件上，
            # 否则沙箱找不到原文 → [SKIP] → 而 SKIP 在本仓库是**计为不成立**的。
            # ⛔ 不逐条改锚点、也不改目标路径：以后报表再搬一次，这里自动跟上。
            import sys as _sys
            from pathlib import Path as _P
            _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "ai"))
            from _airepo import reports_files as _rf
            for _c in _rf():
                _t = _c.read_text(encoding="utf-8", errors="replace")
                if _t.count(old) == 1:
                    p = _c
                    raw = p.read_bytes()
                    text = raw.decode("utf-8")
                    if CRLF.encode("utf-8") in raw:
                        text = text.replace(CRLF, chr(10))
                    self.saved.setdefault(p, raw)
                    break
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
            print(str(i) + ". " + name + chr(10) + "      " + rel + "   ← 期望被「" + want + "」抓到")
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
            hit = code != 0 and want in out
            if hit:
                print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
            else:
                bad += 1
                why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("❌")][:5]:
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
        print("❌ " + str(bad) + "/" + str(total) + " 条不成立")
        return 1
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：没解释的 not-done / 假形状 / 假证据文件 / "
          "非法状态值 / 文档被掏空 都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
