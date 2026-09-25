#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_test_names.py` 真的抓得住那几类错误。

## 为什么
这条判据守的是一件**编译器会用谜语报错**的事 —— 判据失效时不会有人发现，只会某天编译突然红。
所以它自己必须先被证明"真的会红"。

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
CHECK = ROOT / "_tools/qa/_check_test_names.py"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 反引号名字里带半角引号（Windows 文件名非法 → compileDebugKotlin 崩）",
        "android/app/src/test/java/com/tapmoay/sorders/ai/AiAttachmentTest.kt",
        "fun `没有附件时一个字都不加`() {",
        "fun `没有附件时\"一个字\"都不加`() {",
        "IllegalPathException",
    ),
    (
        "② 名字里带点号（`.` 在 Windows 文件名里合法，是 **JVM 方法名**禁它）",
        "android/app/src/test/java/com/tapmoay/sorders/ai/AiAttachmentTest.kt",
        "fun `没有附件时一个字都不加`() {",
        "fun `1.1 没有附件时一个字都不加`() {",
        "IllegalPathException",
    ),
    (
        "③ 扫描目录写错（一个文件都扫不到 → 反空转下限）",
        "_tools/qa/_check_test_names.py",
        '(ROOT / "android/app/src/test").rglob("*.kt")',
        '(ROOT / "android/app/src/test_typo").rglob("*.kt")',
        "在空转",
    ),
    (
        "④ 反空转下限调到不可能的数（下限自己有没有牙）",
        "_tools/qa/_check_test_names.py",
        "if n < 100:",
        "if n < 100000:",
        "在空转",
    ),
]

#: 字节级注入（文本注入表达不了"少 3 个字节的 BOM"）：这条脚本里没有，占位以便共用同一套 main。
BYTE_CASES: list[tuple[str, str]] = []
BOM_WANT = ""

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