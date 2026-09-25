#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_report_boundary.py` 真的抓得住那几类错误。

## 六种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 报表端点里写回业务状态（本轮的原始缺陷复现） | 红：给对象赋值 |
| ② | 报表 service 里加一句 `db.commit()` | 红：会落库的写法 |
| ③ | 报表模块 import 一个写服务（订单状态机） | 红：import 了写服务 |
| ④ | 清单里写一个不存在的文件 | 红：文件不见了 |
| ⑤ | 例外表里留一条永远不命中的例外 | 红：化石 |
| ⑥ | 反空转下限失守 | 红：只认出 |

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
CHECK = ROOT / "_tools/qa/_check_report_boundary.py"
STATS = "backend/app/api/v1/stats.py"
RSVC = "backend/app/services/reports_service.py"
CHK = "_tools/qa/_check_report_boundary.py"

STATS_ANCHOR = "    rows = stats_service.exception_orders(db, date_from, date_to)"
LOAD_ANCHOR = "def load_delivered("
IMPORT_ANCHOR = "from app.services import stats_service"
FILE_LINE = '    "app/services/stats_export.py",'
ALLOWED_EMPTY = "ALLOWED_WRITES: dict[tuple[str, str], str] = {}"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 报表端点里写回业务状态（本轮修掉的那个缺陷复现）",
        STATS, STATS_ANCHOR, STATS_ANCHOR + chr(10) + "    order.is_exception = False",
        "给对象赋值",
    ),
    (
        "② 报表 service 里加一句 db.commit()",
        RSVC, LOAD_ANCHOR, "def _r205_probe(db):" + chr(10) + "    db.commit()" + chr(10) + chr(10) + chr(10) + LOAD_ANCHOR,
        "会落库的写法",
    ),
    (
        "③ 报表模块 import 一个写服务（订单状态机）",
        STATS, IMPORT_ANCHOR, IMPORT_ANCHOR + chr(10) + "from app.services.order_flow import assign_driver",
        "import 了写服务",
    ),
    (
        "④ 清单里写一个不存在的文件",
        CHK, FILE_LINE, '    "app/services/stats_export_gone.py",',
        "文件不见了",
    ),
    (
        "⑤ 例外表里留一条永远不命中的例外（化石）",
        CHK, ALLOWED_EMPTY,
        ALLOWED_EMPTY[:-1] + '("app/services/nope.py", ".commit("): '
        + '"这条例外早就不用了，只是没人删。什么时候删掉这一条：现在。"}',
        "化石",
    ),
    (
        "⑥ 反空转下限失守（清单被掏空却不喊）",
        CHK, "MIN_FILES = 5", "MIN_FILES = 99",
        "只认出",
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
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：报表层回写业务状态 / 落库 / 依赖写服务 / "
          "清单缺文件 / 例外化石 / 清单空转 都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
