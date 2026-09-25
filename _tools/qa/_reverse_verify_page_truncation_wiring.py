#!/usr/bin/env python3
"""反向验证 _tools/qa/_check_page_truncation_wiring.py 真的会红。

## 它守的是什么（代价最大的一类"静默"）
列表被服务端截断时界面**不说**，用户就照着一个错的结论做决定：
现金流水页对"一页 N 条"求和当总额（实测 ¥18,842 vs 真值 ¥48,905.50，**少算 62%**）；
审计页看不到更早的 →「我那次改动没被记下来」；账号列表超过一页 →「没有这个账号」→ 再建一个（撞唯一约束）。

## 这一份为什么值得写（它当场抓到了一条**正在失效**的判据）
这条红线用**数量下限**表达"7 个页面都还接着"：原来下限是 8 / 9（当时的实测值），注释写着
「留余量等于允许某个页面静默退回去」。可是页面一直在加 —— 实测已经 14 / 16，而下限没同步，
于是**中间那几处可以静默退回去而检查照样绿**。现在：下限＝实测值，且**实测 > 下限也报红**
（逼你在增长时同步那一行），本文件第 ⑤ 条注入就是来钉这件事的。

## 五条注入（每条都必须让红线当场红）
| # | 注入 | 现实里谁会这么干 |
| --- | --- | --- |
| ① | 某个 ViewModel 不再读 `page.meta.hasMore` | 重构时把那行删了（那个页面从此静默） |
| ② | 某个界面删掉 `TruncationNote(` | 改版时把那句提示去掉 |
| ③ | 另一处也开始读 `"X-Truncated"` | 有人嫌 pageMeta 绕，自己抄一份（两套判据） |
| ④ | 解析器失配（认不出 paged 端点） | 正则改坏 → 判据空转 |
| ⑤ | 页面加了、**下限没同步**（实测 > 下限） | 新加一个列表页却没管这一行 → 余量又回来了 |

⚠️ 与仓库里其它反向验证同一套纪律：按**字节**备份/还原、跑完逐文件核对、不碰 git checkout --。

用法：python _tools/qa/_reverse_verify_page_truncation_wiring.py
      python _tools/qa/_reverse_verify_page_truncation_wiring.py --list
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_page_truncation_wiring.py"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperLedgerViewModel.kt"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
APIS = "android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt"
#: ⛔ 子进程按 UTF-8 读写（Windows 上默认是 GBK，中文断言会匹配不上）
RUN_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 某个 ViewModel 不再读 page.meta.hasMore（那个页面从此静默）",
        VM,
        "ordersTruncated = page.meta.hasMore",
        "ordersTruncated = false",
        "读 `page.meta.hasMore`",
    ),
    (
        "② 某个界面删掉那条提示（TruncationNote 调用少一处）",
        SCREEN,
        "TruncationNote(",
        "TruncationNoteDisabled(",
        "TruncationNote(...)",
    ),
    (
        "③ 另一处也开始读 X-Truncated（两套判据）",
        APIS,
        "package com.tapmoay.sorders.data.remote.api",
        'package com.tapmoay.sorders.data.remote.api\n\nprivate const val TRUNCATION_PROBE = "X-Truncated"',
        "正好 1 个",
    ),
    (
        "④ 解析器失配：认不出 paged 列表端点（判据空转）",
        "_tools/qa/_check_page_truncation_wiring.py",
        'pieces = re.split(r"(?=@(?:GET|POST|PATCH|PUT|DELETE)\\()", apis_src)',
        'pieces = re.split(r"(?=@(?:GETZZZ)\\()", apis_src)',
        "认出 ≥",
    ),
    (
        "⑤ 页面加了、**下限没同步**（实测 > 下限 → 余量又回来了）",
        VM,
        "ordersTruncated = page.meta.hasMore",
        "ordersTruncated = page.meta.hasMore\n        val _probe = page.meta.hasMore",
        "下限没过期",
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
                          encoding="utf-8", errors="replace", cwd=str(ROOT), env=RUN_ENV)
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
    print(f"✅ {total}/{total} 全部成立：截断接线这条红线的每一处拆掉都会红")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())