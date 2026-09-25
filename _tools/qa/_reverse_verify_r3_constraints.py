#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_r3_constraints.py` 真的抓得住那几类错误。

## 八种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 把一条棘轮条目改成「阶段」却不写里程碑 | 红：阶段判定，必须写合法里程碑 |
| ② | 探针名写成一个根本不存在的东西 | 红：没实现（化石） |
| ③ | 棘轮上限调到低于当下未守住的条数 | 红：> 棘轮上限 |
| ④ | 把某条指南原文缩成两个字 | 红：原文太短 |
| ⑤ | 清单被掏空（条数下限失守） | 红：只登记到 |
| ⑥ | 进度台账里删掉一个里程碑小节 | 红：缺里程碑小节 |
| ⑦ | 某条退出条件不再带复现命令 | 红：没带复现命令 |
| ⑧ | requirements.txt 被「顺手锁死」一条 | 红：还没写依赖决策就先锁死 |

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
CHECK = ROOT / "_tools/qa/_check_r3_constraints.py"
DOC = "docs/R3_CONSTRAINTS.md"
PROG = "docs/R3_PROGRESS.md"
REQ = "backend/requirements.txt"
CHK = "_tools/qa/_check_r3_constraints.py"
NL = chr(10)

D08 = ("id: R3-D08" + NL + "类别: 禁做" + NL
       + "原文: Migration Lock 和 Scheduler Lock 不是同一个锁：不同名字、不同生命周期" + NL
       + "位置: L461" + NL + "探针: distinct_lock_names" + NL + "判定: 棘轮")
D08_BAD = D08.replace("判定: 棘轮", "判定: 阶段")

CASES: list[tuple[str, str, str, str, str]] = [
    ("① 棘轮条目改成阶段却不写里程碑", DOC, D08, D08_BAD, "阶段判定，必须写合法里程碑"),
    ("② 探针名写成一个不存在的东西", DOC,
     "探针: no_observability_stack", "探针: zzz_nope_probe", "没实现（化石）"),
    ("③ 棘轮上限调到低于当下未守住的条数", DOC,
     "`棘轮上限: 1`　`不判定上限: 13`", "`棘轮上限: 0`　`不判定上限: 13`", "> 棘轮上限"),
    ("④ 把某条指南原文缩成两个字", DOC,
     "原文: 第三轮不要丢掉 _trace_order.py", "原文: 不要丢", "原文太短"),
    ("⑤ 清单被掏空（条数下限失守）", CHK, "MIN_CONSTRAINTS = 24", "MIN_CONSTRAINTS = 99", "只登记到"),
    ("⑥ 进度台账里删掉一个里程碑小节", PROG,
     "## R3-01 Migration Lifecycle（最高优先级）", "## 迁移生命周期（最高优先级）", "缺里程碑小节"),
    ("⑦ 某条退出条件不再带复现命令", PROG,
     "1219 行）—— 复现：", "1219 行）—— 见：", "没带复现命令"),
    ("⑧ requirements.txt 被顺手锁死一条", REQ,
     "fpdf2>=2.7,<3", "fpdf2>=2.7,<3" + NL + "foo==1.2.3", "还没写依赖决策就先锁死"),
]

CRLF = chr(13) + chr(10)


class Sandbox:
    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, rel: str, old: str, new: str) -> None:
        path = ROOT / rel
        if not path.exists():
            raise ValueError("找不到 " + rel)
        self.saved.setdefault(path, path.read_bytes())
        raw = path.read_bytes()
        crlf = CRLF.encode("utf-8") in raw
        text = raw.decode("utf-8")
        if crlf:
            text = text.replace(CRLF, NL)
        if text.count(old) != 1:
            raise ValueError(rel + " 里锚点出现 " + str(text.count(old)) + " 次（要恰好一次）")
        text = text.replace(old, new, 1)
        path.write_bytes((text.replace(NL, CRLF) if crlf else text).encode("utf-8"))

    def restore(self) -> None:
        for path, raw in self.saved.items():
            path.write_bytes(raw)

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
            print(str(i) + ". " + name + NL + "      " + rel + "   ← 期望被「" + want + "」抓到")
        return 0

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条判据就没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时判据是绿的 —— " + last.strip())
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
                print("  [OK] " + label + " → 判据报红并命中「" + want + "」")
            else:
                bad += 1
                why = "判据居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("❌")][:5]:
                    print("       判据实际报的：" + ln)
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后判据全绿" if ok else "  [MISS] 还原后判据没恢复")
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
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：棘轮被绕过 / 探针化石 / 上限被调松 / 原文抄不全 / "
          "清单被掏空 / 里程碑小节缺失 / 退出条件不带复现命令 / 依赖被顺手锁死 都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
