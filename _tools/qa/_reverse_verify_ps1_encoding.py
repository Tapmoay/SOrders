#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_ps1_encoding.py` 真的抓得住那几类错误。

## 为什么
它守的是「含中文的 .ps1 必须存成 UTF-8 with BOM」—— 违反时 PS 5.1 会报
「The string is missing the terminator」并**吃掉换行**，照 README 做的人拿到的是一个语法错误的脚本。
这类错误不会让任何测试红，所以唯一守卫必须先被证明"真的会红"。

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
CHECK = ROOT / "_tools/qa/_check_ps1_encoding.py"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 含中文的 .ps1 数量下限调到不可能的数（反空转）",
        "_tools/qa/_check_ps1_encoding.py",
        "MIN_CJK_PS1 = 4",
        "MIN_CJK_PS1 = 99",
        "判据可能已空转",
    ),
    (
        "② 扫描总数下限调到不可能的数（防「扫错目录了还报绿」）",
        "_tools/qa/_check_ps1_encoding.py",
        "MIN_PS1 = 8",
        "MIN_PS1 = 999",
        "判据可能已空转",
    ),
    (
        "③ AGENTS.md 里那条规矩被删掉（判据成了孤儿）",
        "AGENTS.md",
        "UTF-8 with BOM",
        "UTF-8-BOM",
        "判据成了孤儿",
    ),
]

#: ⛔ 字节级注入：文本替换表达不了「少 3 个字节的 BOM」——必须直接动字节。
#:    值 = (标签, 目标文件)；期望抓到的文案见 BOM_WANT。
BYTE_CASES: list[tuple[str, str]] = [
    ("④ 含中文的 .ps1 被去掉 BOM（PS 5.1 会语法错、吃掉换行）",
     "scripts/local-test-server.ps1"),
]
BOM_WANT = "含中文却没有"

CRLF = chr(13) + chr(10)


class Sandbox:
    """按**字节**记账的注入沙箱。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def keep(self, rel: str) -> Path:
        p = ROOT / rel
        if not p.exists():
            raise ValueError("找不到 " + rel)
        self.saved.setdefault(p, p.read_bytes())
        return p

    def apply(self, rel: str, old: str, new: str) -> None:
        p = self.keep(rel)
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

    def strip_bom(self, rel: str) -> None:
        p = self.keep(rel)
        raw = p.read_bytes()
        if not raw.startswith(b"\xef\xbb\xbf"):
            raise ValueError(rel + " 本来就没有 BOM（那这条注入证明不了什么）")
        p.write_bytes(raw[3:])

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def report(label: str, code: int, out: str, want: str) -> bool:
    hit = code != 0 and want in out
    if hit:
        print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
        return True
    why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
    print("  [MISS] " + label + " → " + why)
    for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("❌")][:5]:
        print("       红线实际报的：" + ln)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(CASES, 1):
            print(f"{i}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        for i, (name, rel) in enumerate(BYTE_CASES, len(CASES) + 1):
            print(f"{i}. {name}\n      {rel}   ← 期望被「{BOM_WANT}」抓到（字节级）")
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
            if not report(label, code, out, want):
                bad += 1
        for label, rel in BYTE_CASES:
            sb.restore()
            try:
                sb.strip_bom(rel)
                code, out = run_check()
            except ValueError as exc:
                print("  [SKIP] " + label + " —— " + str(exc))
                bad += 1
                continue
            finally:
                sb.restore()
            if not report(label, code, out, BOM_WANT):
                bad += 1
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
    total = len(CASES) + len(BYTE_CASES) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())