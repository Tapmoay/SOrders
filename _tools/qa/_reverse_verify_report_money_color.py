#!/usr/bin/env python3
'''反向验证「报表中心金额配色」这条判据**真的会红**（CHG-0037）。

## 为什么这条要反向验证
_check_report_money_color.py 判的是**颜色**，而它自己也是靠字符串匹配活的 —— 这种判据最典型的
失效方式是「锚点跟着实现一起漂了、判据还显示全绿」（本项目已经栽过 5 次这种空转）。
所以这里把每一种失效方式各注入一次（注入 = 把工作区改成「该报红」的样子，跑完按**字节**还原）：

  ① amountTone 的负数分支从红改回橙（上一版口径）        → 必须点名 amountTone；
  ② Palette 的说明把红写回「只给欠钱」专用                → 必须点名这条；
  ③ 税账留抵不再判负（恒蓝）                              → 必须点名 vatPayable；
  ④ 「还能欠多少」的颜色拿 overLimit 决定（不看负号）      → 必须点名还能欠多少；
  ⑤ 逐单欠款只在 > 0 时红（退款那种负数就漏了）            → 必须点名逐单欠款；
  ⑥ 司机待结同理                                          → 必须点名司机待结；
  ⑦ 结构减号行被连坐（「− 商品成本」画红）                 → 必须点名结构减号行；
  ⑧ 老页面两处「商品毛利」改回恒绿                         → 必须点名商品毛利；
  ⑨ 老页面「营业利润」的正负上色被换成恒绿                 → 必须点名 opColor；
  ⑩ 金额渲染点被截空（v2 的 money( 全被改名）              → 必须点名渲染点（反空转要有牙）；
  ⑪ 老页面「经营利润」卡的留抵（带负号）改回恒绿           → 必须点名留抵；
  ⑫ 老页面税账页大数的留抵改回恒绿                         → 必须点名留抵；
  ⑬ 负面对照：给 amountTone 那行加一句行尾注释（等价写法） → 必须仍然全绿。

## ⛔ 已知盲区（不许当成「已覆盖」）
- 它判不了「用户在屏幕上看到的确实是红」—— 那一步只能靠模拟器截图（CHG-0037.md ⑧）；
- 它只注入**源码字符串**：判据与实现被同时改坏（例如两边一起不再叫 Tone.BAD）本脚本覆盖不了；
- 颜色是否够红（对比度）不在这里判。

⚠️ 与其它反向验证同一套纪律：注入/还原都按字节做，跑完逐文件核对（本项目栽过「注入把 bug 留在源码里」）。
跑之前先上注入锁（lock_reverse_verify）。

用法：python _tools/qa/_reverse_verify_report_money_color.py
'''
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_report_money_color.py"
PKG = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/report"
MODEL = PKG / "ReportV2Model.kt"
NODES = PKG / "ReportV2Nodes.kt"
CENTER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"
NL = chr(10)


def swap(old: str, new: str):
    '''把 [old] 换成 [new]（[old] 必须恰好出现一次 —— 锚点变了就当场报错，不许悄悄跳过）。'''

    def g(text: str) -> str:
        if text.count(old) != 1:
            raise ValueError('注入锚点出现 ' + str(text.count(old)) + ' 次（要恰好一次）：' + old)
        return text.replace(old, new, 1)

    return g


def swap_all(old: str, new: str):
    '''把 [old] 全部换掉（至少一次）。'''

    def g(text: str) -> str:
        if text.count(old) < 1:
            raise ValueError('注入锚点一次都没出现：' + old)
        return text.replace(old, new)

    return g


CASES: list[tuple] = [
    (
        'amountTone 的负数分支从红改回橙 → 必须点名 amountTone',
        MODEL, False,
        swap("if (v < 0) Tone.BAD else Tone.GOOD", "if (v < 0) Tone.WARN else Tone.GOOD"),
        True, "amountTone",
    ),
    (
        'Palette 的说明把红写回「只给欠钱」专用 → 必须点名这条',
        MODEL, False,
        swap_all("带负号的金额", "只给「欠钱」"),
        True, "只给「欠钱」",
    ),
    (
        '税账留抵不再判负（恒蓝）→ 必须点名 vatPayable',
        NODES, False,
        swap("if (num(t.vatPayable) < 0) Tone.BAD else Tone.INFO", "Tone.INFO"),
        True, "vatPayable",
    ),
    (
        '「还能欠多少」的颜色拿 overLimit 决定（不看负号）→ 必须点名还能欠多少',
        NODES, False,
        swap("if (canStillOwe < 0) Tone.BAD else Tone.GOOD",
             "if (row.overLimit) Tone.BAD else Tone.GOOD"),
        True, "还能欠多少",
    ),
    (
        '逐单欠款只在 > 0 时红（退款那种负数就漏了）→ 必须点名逐单欠款',
        NODES, False,
        swap("toneColor(if (num(o.arrears) != 0.0) Tone.BAD else Tone.PLAIN)",
             "toneColor(if (num(o.arrears) > 0) Tone.BAD else Tone.PLAIN)"),
        True, "逐单欠款",
    ),
    (
        '司机待结同理（只看 > 0）→ 必须点名司机待结',
        NODES, False,
        swap("toneColor(if (num(r.freightOwed) != 0.0) Tone.BAD else Tone.PLAIN)",
             "toneColor(if (num(r.freightOwed) > 0) Tone.BAD else Tone.PLAIN)"),
        True, "司机待结",
    ),
    (
        '结构减号行被连坐（「− 商品成本」画红）→ 必须点名结构减号行',
        NODES, False,
        swap('"−" + money(p.costTotal), Color.Unspecified', '"−" + money(p.costTotal), Palette.bad'),
        True, "结构减号行",
    ),
    (
        '老页面两处「商品毛利」改回恒绿 → 必须点名商品毛利',
        CENTER, False,
        swap_all("if (profit >= 0) Color(0xFF49A67A) else Color(0xFFE53935)", "Color(0xFF49A67A)"),
        True, "商品毛利",
    ),
    (
        '老页面「营业利润」的正负上色被换成恒绿 → 必须点名 opColor',
        CENTER, False,
        swap("val opColor = if (op >= 0) Color(0xFF49A67A) else Color(0xFFE53935)",
             "val opColor = Color(0xFF49A67A)"),
        True, "opColor",
    ),
    (
        '金额渲染点被截空（v2 的 money( 全被改名）→ 必须点名渲染点',
        NODES, False,
        swap_all("money(", "MONEY("),
        True, "渲染点",
    ),
    (
        '老页面「经营利润」卡的留抵（带负号）改回恒绿 → 必须点名留抵',
        CENTER, False,
        swap("if ((data.vatPayable.toDoubleOrNull() ?: 0.0) < 0.0) 0xFFE53935 else 0xFFBA6947",
             "if ((data.vatPayable.toDoubleOrNull() ?: 0.0) < 0.0) 0xFF49A67A else 0xFFBA6947"),
        True, "留抵",
    ),
    (
        '老页面税账页大数的留抵改回恒绿 → 必须点名留抵',
        CENTER, False,
        swap("if (payable < 0.0) Color(0xFFE53935) else Color(0xFFBA6947)",
             "if (payable < 0.0) Color(0xFF49A67A) else Color(0xFFBA6947)"),
        True, "留抵",
    ),
    (
        '负面对照：给 amountTone 那行加一句行尾注释（等价写法）→ 必须仍然全绿',
        MODEL, False,
        swap("internal fun amountTone(v: Double): Tone = if (v < 0) Tone.BAD else Tone.GOOD",
             "internal fun amountTone(v: Double): Tone = if (v < 0) Tone.BAD else Tone.GOOD // 口径：带负号的金额一律红"),
        False, "",
    ),
]


class Sandbox:
    '''按字节记住原样，最后一次性还原（⛔ 不用 git checkout --：那会抹掉未提交的真实改动）。'''

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    @staticmethod
    def _mutate(data: bytes, mutate) -> bytes:
        crlf = (chr(13) + chr(10)).encode("utf-8") in data
        text = data.decode("utf-8")
        if crlf:
            text = text.replace(chr(13) + chr(10), NL)
        text = mutate(text)
        return (text.replace(NL, chr(13) + NL) if crlf else text).encode("utf-8")

    def apply(self, path: Path, mutate) -> None:
        self.saved.setdefault(path, path.read_bytes())
        path.write_bytes(self._mutate(path.read_bytes(), mutate))

    def restore(self) -> None:
        for path, raw in self.saved.items():
            path.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    if not CHECK.exists():
        print("❌ 找不到 " + str(CHECK))
        return 1

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条检查就没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时这条检查是绿的 —— " + last.strip())

        for label, path, _unused, mutate, expect_red, keyword in CASES:
            sb.restore()
            try:
                sb.apply(path, mutate)
                code, out = run_check()
            except ValueError as exc:
                print("  [MISS] " + label + " → 注入没做成（锚点变了就改本脚本）：" + str(exc))
                bad += 1
                continue
            finally:
                sb.restore()
            if expect_red:
                hit = code != 0 and keyword in out
                detail = "报了红" if code != 0 else "仍然全绿（判据没牙）"
                if code != 0 and keyword not in out:
                    detail += "，但没点出「" + keyword + "」"
            else:
                hit = code == 0
                detail = "仍然全绿（这正是要的）" if hit else "被误判成红了（假红）"
            print("  [" + ("OK" if hit else "MISS") + "] " + label + " → " + detail)
            if not hit:
                bad += 1
                for ln in out.splitlines()[-10:]:
                    print("        " + ln)

        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后这条检查全绿" if ok else "  [MISS] 还原后这条检查没恢复")
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
    print("✅ " + str(total) + "/" + str(total) + " 全部成立："
          + str(len(CASES) - 1) + " 条注入各自让判据报红，负面对照仍然全绿，还原后逐字节一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
