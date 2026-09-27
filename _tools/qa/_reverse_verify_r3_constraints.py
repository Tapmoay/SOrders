#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_r3_constraints.py` 真的抓得住那几类错误。

## 十种破坏 + 两组单元断言
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
| ⑨ | 里程碑语法被改回 v1（`R[3-9]-0\\d`） | 红：新编号（R4-10…）当场不算数 |
| ⑩ | `milestone_tag_of` 退化成一个常量（每条提交都算 R4-09） | 红：**重号** |

⭐ ⑨⑩ 是 **Milestone Tag Grammar v2**（用户 2026-09-27 拍板）带来的两条。
另外这个脚本还跑**两组单元断言**（不是"注入→变红"，而是直接判那个纯函数）：
语法该收的收、该拒的拒（`R4-10` / `R4-27` / `R4-99` 必须合法；
`R4-100` / `R4-A0` / `R10-01` 必须不合法），以及重号判定本身认得出来。
⛔ 为什么这两组必须是单元断言：**"该允许的必须允许"没法用"注入→变红"来证**
—— 一条把所有东西都判红的正则，在注入测试下会全绿，而它把合法编号也一起否掉了。

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _milestone_tag import duplicate_tags, milestone_tag_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_r3_constraints.py"
DOC = "docs/R3_CONSTRAINTS.md"
PROG = "docs/R3_PROGRESS.md"
REQ = "backend/requirements.txt"
CHK = "_tools/qa/_check_r3_constraints.py"
GRAMMAR = "_tools/qa/_milestone_tag.py"
NL = chr(10)

D08 = ("id: R3-D08" + NL + "类别: 禁做" + NL
       + "原文: Migration Lock 和 Scheduler Lock 不是同一个锁：不同名字、不同生命周期" + NL
       + "位置: L461" + NL + "探针: distinct_lock_names" + NL + "判定: 棘轮")
D08_BAD = D08.replace("判定: 棘轮", "判定: 阶段")

CASES: list[tuple[str, str, str, str, str]] = [
    ("① 棘轮条目改成阶段却不写里程碑", DOC, D08, D08_BAD, "阶段判定，必须写合法里程碑"),
    ("② 探针名写成一个不存在的东西", DOC,
     "探针: no_observability_stack", "探针: zzz_nope_probe", "没实现（化石）"),
    ("③ 往手写的 Kotlin 里塞一张权限表（棘轮立刻顶不住）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Modules.kt",
     "data class ModuleEntry(",
     "private val HACK = setOf(" + chr(34) + "order:create" + chr(34) + ", " + chr(34) + "order:edit" + chr(34)
     + ", " + chr(34) + "order:dispatch" + chr(34) + ")" + NL + "data class ModuleEntry(",
     "> 棘轮上限"),
    ("④ 把某条指南原文缩成两个字", DOC,
     "原文: 第三轮不要丢掉 _trace_order.py", "原文: 不要丢", "原文太短"),
    ("⑤ 清单被掏空（条数下限失守）", CHK, "MIN_CONSTRAINTS = 24", "MIN_CONSTRAINTS = 99", "只登记到"),
    ("⑥ 进度台账里删掉一个里程碑小节", PROG,
     "## R3-01 Migration Lifecycle（最高优先级）", "## 迁移生命周期（最高优先级）", "缺里程碑小节"),
    ("⑦ 某条退出条件不再带复现命令", PROG,
     "1219 行）—— 复现：", "1219 行）—— 见：", "没带复现命令"),
    # ---- Milestone Tag Grammar v2（用户 2026-09-27 拍板）----
    # ⚠️ ⑨ 只有在**已经有 R4-10 及以上编号的提交**时才会红。语法一旦退回 v1，
    #    那些提交就"没有可回溯的里程碑"，判据必须当场喊出来。
    ("⑨ 里程碑语法被改回 v1（R[3-9]-0" + chr(92) + "d）", GRAMMAR,
     'MILESTONE_TAG = re.compile(r"(?<![0-9A-Za-z])R[3-9]-[0-9]{2}(?![0-9])")',
     'MILESTONE_TAG = re.compile("R[3-9]-0" + chr(92) + "d")',
     "没有可回溯的里程碑编号"),
    # ⑩ 让编号函数退化成一个常量：每条提交都算 R4-09 ⇒ **重号**必须被抓到。
    #    这一条同时证明了"唯一性那一段真的接在命令行判据上"，不是一个没人调的纯函数。
    ("⑩ 编号函数退化成常量（每条提交都算 R4-09）", GRAMMAR,
     '    m = MILESTONE_TAG.search(subject or "")' + NL + '    return m.group(0) if m else ""',
     '    return "R4-09"',
     "重号"),
    ("⑧ requirements.txt 被顺手锁死一条", REQ,
     # ⛔ 2026-09-26 修期望词**第二次**：判据确实红了，但报的是「依赖决策…，那就**不该**锁 ——
     #    却先锁死 1 条：foo==1.2.3」。⚠️ 期望词取「先锁死」这个**两条决策路径都会用到**的片段：
     #    「还没拍板」与「已拍板为**不锁**」都必须红 —— 用户 2026-09-26 拍板「② 不要 lock」之后，
     #    这条注入**照样**要被抓：⛔ 拍板 ≠ 放行（旧写法「已拍板就直接 hold」会把它变成假绿）。
     "fpdf2>=2.7,<3", "fpdf2>=2.7,<3" + NL + "foo==1.2.3", "先锁死"),
]

#: 单元断言条数（6 条语法样例 + 2 条重号判定）—— 只用来算总数，⛔ 不影响任何判定。
UNIT_CHECKS = 8

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

        # ---- 单元断言：里程碑语法 **该允许的必须允许** ------------------------
        # ⛔ 用户 2026-09-27 点名要的六个样例：R4-10 / R4-27 / R4-99 必须合法，
        #    R4-100 / R4-A0 / R10-01 必须不合法。
        # ⚠️ 为什么这一组**不能**写成"注入→变红"：一条把所有东西都判红的正则，
        #    在注入测试下是**全绿**的 —— 而它把合法编号也一起否掉了。
        #    "不该拒的别拒"只能靠直接判这个纯函数。
        for probe in ("R4-10 x", "R4-27 x", "R4-99 x"):
            got = milestone_tag_of(probe)
            hit = got == probe.split(" ")[0]
            print("  [" + ("OK" if hit else "MISS") + "] 语法应**接受** " + probe.split(" ")[0]
                  + " → " + (got or "（拒了）"))
            bad += 0 if hit else 1
        for probe in ("R4-100 x", "R4-A0 x", "R10-01 x"):
            got = milestone_tag_of(probe)
            hit = got == ""
            print("  [" + ("OK" if hit else "MISS") + "] 语法应**拒绝** " + probe.split(" ")[0]
                  + " → " + (got or "（拒了，正确）"))
            bad += 0 if hit else 1
        dup_hit = duplicate_tags([("a", "R4-10 x"), ("b", "R4-11 y"), ("c", "R4-10 z"),
                                  ("d", "no tag")]) == ["R4-10"]
        clean_hit = duplicate_tags([("a", "R4-10 x"), ("b", "R4-11 y")]) == []
        print("  [" + ("OK" if dup_hit else "MISS") + "] 重号判定：同号两行 → 报 R4-10")
        print("  [" + ("OK" if clean_hit else "MISS") + "] 重号判定：不重号 → 空（不许乱报）")
        bad += (0 if dup_hit else 1) + (0 if clean_hit else 1)

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
    total = len(CASES) + UNIT_CHECKS + 1
    print()
    if bad:
        print("❌ " + str(bad) + "/" + str(total) + " 条不成立")
        return 1
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：棘轮被绕过 / 探针化石 / 上限被调松 / 原文抄不全 / "
          "清单被掏空 / 里程碑小节缺失 / 退出条件不带复现命令 / 依赖被顺手锁死 都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
