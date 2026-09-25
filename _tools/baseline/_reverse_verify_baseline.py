#!/usr/bin/env python3
"""反向验证 `_tools/baseline/_check_baseline.py` 真的抓得住那几类错误。

## 为什么这条判据最需要反向验证
基线快照**唯一的价值**是「改造前的样子」，而它已经被绕过一次（2026-09-24：重采时忘了换标签
加 `--force`，`before/` 被换成了改造后的数据，`docs/BASELINE.md` 还指着它说"快照"）。
**当时没有任何检查说话** —— 也就是说：这条判据如果真的失效，后果是一整套「改了多少」的数字全是假的，
而且不会有第二次提醒。

## 五种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 改动 `before/` 里一个字节（冻结的东西事后被改） | 红：与 HEAD 不一致 |
| ② | 把 `before/` 记的提交换成**改造后**的提交（上次事故的形状） | 红：不是引入本工具那个提交的祖先 |
| ③ | `captured_at` 的日期与所在目录对不上 | 红：captured_at 与目录日期对不上 |
| ④ | 判据条数下限调到不可能的数 | 红：检查可能空转了 |
| ⑤ | 文档指着一份不存在的快照 | 红：但那份快照不存在 |

⚠️ 与仓库里其它 `_reverse_verify_*.py` 同一套纪律：按**字节**备份/还原、跑完逐文件核对、
⛔ 全程不碰 `git checkout --`。

用法：python _tools/baseline/_reverse_verify_baseline.py
      python _tools/baseline/_reverse_verify_baseline.py --list
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
CHECK = ROOT / "_tools/baseline/_check_baseline.py"
BEFORE = "_tools/baseline/before/2026-09-24/baseline.json"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 冻结的 before/ 快照事后被改（多一个空格也算）",
        BEFORE,
        '"git_branch": "p",',
        '"git_branch": "p ",',
        "与 HEAD 不一致",
    ),
    (
        "② 把 before/ 记的提交换成**改造后**的提交（2026-09-24 那次事故的形状）",
        BEFORE,
        '"git_commit": "020d35e8d5a937bca5ff9f341856a3f20eaaea7a",',
        '"git_commit": "5fda79946ee7213aa760c4d8377cee8bffda60a9",',
        "不是引入本工具那个提交",
    ),
    (
        "③ captured_at 的日期与它所在目录对不上（把今天的数塞进昨天的目录）",
        BEFORE,
        '"captured_at": "2026-09-24T19:37:05"',
        '"captured_at": "2026-09-23T19:37:05"',
        "与目录日期（2026-09-24）对不上",
    ),
    (
        "④ 判据条数下限调到不可能的数（下限自己有没有牙）",
        "_tools/baseline/_check_baseline.py",
        "MIN_RULES = 15",
        "MIN_RULES = 99999",
        "检查可能空转",
    ),
    (
        "⑤ 文档指着一份不存在的快照（渲染到一半 / 被删了）",
        "docs/BASELINE.md",
        "_tools/baseline/after/2026-09-24/baseline.json",
        "_tools/baseline/after/2026-09-25/baseline.json",
        "但那份快照不存在",
    ),
]

BYTE_CASES: list[tuple[str, str]] = []
BOM_WANT = ""

CRLF = chr(13) + chr(10)


class Sandbox:
    """按**字节**记账的注入沙箱。"""

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
    proc = subprocess.run([sys.executable, str(CHECK), "--check"], capture_output=True, text=True,
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
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("BAD")][:5]:
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
    print(f"✅ {total}/{total} 全部成立：快照被改 / 塞错数据 / 文档指空 / 下限失效都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())