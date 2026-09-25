#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_ai_read_limits.py` 真的抓得住那几类错误。

## 为什么这条红线需要反向验证
它守的是一件**没有任何测试会红**的事：AI 判断"后端还有没有更多行"的唯一办法是**多要一行**
（`limit + 1`，`AiTools.MAX_ROWS = 200`），而某个端点的 `limit` 上限只要 ≤ 200，
AI 那条路就整条坏掉（实测：`/places` 一直 422，用户看到的是"这个功能没上线"）。
这条判据**是唯一的守卫**，所以它自己必须被证明"真的会红"。

## 四种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | AI 侧 `MAX_ROWS` 调到比所有端点上限都大 | 红：端点上限 ≤ MAX_ROWS |
| ② | `MAX_ROWS` 改名（判据读不到它） | 红：读不到 MAX_ROWS —— 判据失配 |
| ③ | 把某个端点的 `le=500` 降成 150 | 红：该端点的探针必然 422 |
| ④ | 反空转下限调到不可能的数 | 红：只认出 N 个端点（<8） |

⚠️ 与仓库里其它 `_reverse_verify_*.py` 同一套纪律：按**字节**备份/还原、跑完逐文件核对、
⛔ 全程不碰 `git checkout --`。

用法：python _tools/qa/_reverse_verify_ai_read_limits.py
      python _tools/qa/_reverse_verify_ai_read_limits.py --list
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
CHECK = ROOT / "_tools/qa/_check_ai_read_limits.py"
AI_TOOLS = "android/app/src/main/java/com/tapmoay/sorders/ai/AiTools.kt"
MAX_ROWS_LINE = "const val MAX_ROWS = 200"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① AI 侧 MAX_ROWS 调到比端点上限还大（判据的核心那条）",
        AI_TOOLS,
        MAX_ROWS_LINE,
        "const val MAX_ROWS = 100000",
        "≤ MAX_ROWS",
    ),
    (
        "② MAX_ROWS 改名（判据读不到 → 全是空转）",
        AI_TOOLS,
        MAX_ROWS_LINE,
        "const val MAX_ROWS_RENAMED = 200",
        "读不到",
    ),
    (
        "③ 某个端点的 le 降成 150（这条端点的 AI 读能力整条坏掉）",
        "backend/app/api/v1/products.py",
        "limit: int = Query(200, ge=1, le=500),",
        "limit: int = Query(200, ge=1, le=150),",
        "GET /api/v1/products",
    ),
    (
        "④ 反空转下限调到不可能的数（下限自己有没有牙）",
        "_tools/qa/_check_ai_read_limits.py",
        "MIN_LIMIT_ENDPOINTS = 8",
        "MIN_LIMIT_ENDPOINTS = 99999",
        "扫描失效",
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
            print(f"{i}. {name}\n      {rel}   ← 期望被「{want}」抓到")
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
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith(("❌", "   -"))][:5]:
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
    print(f"✅ {total}/{total} 全部成立：AI 读上限的四类破坏都会被当场抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())