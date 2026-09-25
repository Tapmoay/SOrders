#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_money_dependency.py` 真的抓得住那几类错误。

## 为什么
这条判据守的是**依赖方向**。它最容易的退化方式是「扫描坏了但照样绿」：
AST 解析失败、白名单写成点分名（第一版就是）、名单里的文件被搬走后仍留着旧路径 ——
三种都不会让任何业务用例失败，只会让「钱只有一个依赖方向」变成一句口号。

## 八种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 服务层反向 import 一个 HTTP 路由 | 红：反向 import 了 HTTP 路由层 |
| ② | 钱模块 import 报表层 | 红：钱模块依赖了**报表层** |
| ③ | 口径层 import 落库层 | 红：口径层依赖了落库层 |
| ④ | 口径层 import 一个普通服务（白名单外） | 红：白名单之外 |
| ⑤ | 契约把一个符号转出到非钱模块 | 红：不是钱模块 |
| ⑥ | 钱模块名单里写一个不存在的文件 | 红：名单里的 … 不存在 |
| ⑦ | 反空转下限失守（扫描坏了却不喊） | 红：只扫到 N 个模块 |
| ⑧ | 例外表里留一条早就没用的例外 | 红：已经不再命中（化石） |

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
CHECK = ROOT / "_tools/qa/_check_money_dependency.py"
ACCT = "backend/app/services/accounting_service.py"
OMONEY = "backend/app/services/order_money.py"
CONTRACT = "backend/app/services/money_contract.py"

ACCT_ANCHOR = "from app.services.money_text import money_text"
OMONEY_ANCHOR = "from app.models import CashFlow, Ledger, Order, OrderProduct"
REEXPORT_LINE = '"money_of": ("app.services.order_money", "money_of"),'
TIER1_TAIL = '    "app/services/ledger_response.py",' + chr(10) + ")"
ALLOWED_EMPTY = "ALLOWED: dict[tuple[str, str], str] = {}"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 服务层反向 import 一个 HTTP 路由（依赖方向倒置回来）",
        ACCT,
        ACCT_ANCHOR,
        "import app.api.v1.router  # probe" + chr(10) + ACCT_ANCHOR,
        "反向 import 了 HTTP 路由层",
    ),
    (
        "② 钱模块 import 报表层（事实消费者反过来被生产者依赖）",
        OMONEY,
        OMONEY_ANCHOR,
        "import app.services.reports_service  # probe" + chr(10) + OMONEY_ANCHOR,
        "报表层",
    ),
    (
        "③ 口径层 import 落库层（纯算术依赖会改状态的东西）",
        OMONEY,
        OMONEY_ANCHOR,
        "import app.services.accounting_service  # probe" + chr(10) + OMONEY_ANCHOR,
        "落库层",
    ),
    (
        "④ 口径层 import 一个白名单之外的服务",
        OMONEY,
        OMONEY_ANCHOR,
        "import app.services.place_service  # probe" + chr(10) + OMONEY_ANCHOR,
        "白名单之外",
    ),
    (
        "⑤ 契约把一个符号转出到**非钱模块**（契约变成别人的门面）",
        CONTRACT,
        REEXPORT_LINE,
        '"money_of": ("app.services.place_service", "money_of"),',
        "不是钱模块",
    ),
    (
        "⑥ 钱模块名单里写一个不存在的文件（名单留旧路径）",
        "_tools/qa/_check_money_dependency.py",
        TIER1_TAIL,
        '    "app/services/ledger_response.py",' + chr(10) + '    "app/services/nope.py",' + chr(10) + ")",
        "不存在",
    ),
    (
        "⑦ 反空转下限失守（扫描坏了却不喊）",
        "_tools/qa/_check_money_dependency.py",
        "MIN_MODULES = 180",
        "MIN_MODULES = 9999",
        "只扫到",
    ),
    (
        "⑧ 例外表里留一条早就没用的例外（化石）",
        "_tools/qa/_check_money_dependency.py",
        ALLOWED_EMPTY,
        ALLOWED_EMPTY[:-1] + '("app/services/nope.py", "app/api/x.py"): '
        + '"这条例外早就不用了，只是没人删。什么时候删掉这一条：现在。"}',
        "化石",
    ),
]

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
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：方向倒置 / 依赖报表 / 跨层 / 白名单外 / "
          "契约乱转出 / 名单留旧路径 / 扫描空转 / 例外化石 都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
