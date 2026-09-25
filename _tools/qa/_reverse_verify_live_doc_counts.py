#!/usr/bin/env python3
"""反向验证「活文档里手写的数字」这条检查（整改报告 §13）**真的会红**。

## 为什么这条要反向验证
_check_live_doc_counts.py 是一条**元检查**：它判的不是代码，而是**别的文档里的数字**。
元检查最典型的失效方式是"安静地少查" —— 正则写窄了、LIVE 清单指错了、某处数字根本没被判，
三种都表现为**全绿**。本项目已经栽过 5 次这种空转（见各 _reverse_verify_*.py 的开头）。

所以这里把它的每一种失效方式各注入一次（注入 = 把工作区改成"该报红"的样子，跑完按字节还原）：

  ① 检查脚本数写错（AGENTS.md）        → 必须点名那一页，并写出「实际是 N」；
  ② 端点索引端点数写错（AGENTS.md）    → 同上（只在紧挨着 08A 那个生成物的行上判）；
  ③ 反向验证份数写错（CORE_AND_EXTENSION.md）→ 同上（_reverse_verify 附近 30 字内的「N 份」）；
  ④ orders.py 规模写错（同页）         → 同上（阶段 4 搬迁之后它只剩装配说明）；
  ⑤ 可跑脚本的判据条数写错（backup/README.md 54→53）→ 必须拿那个脚本**自己打印的**总数对账；
  ⑥ _check_all.py 的条数手写           → 必须判「不许手写」（这个脚本在这里跑不动）；
  ⑦ 反向验证脚本的注入条数手写         → 同上（跑它会注入并改工作区）；
  ⑧ LIVE 清单指到一个不存在的活文档    → 必须报「不存在」，不许安静地少判一页；
  ⑩ 给 `_check_all.py` 手写耗时（R3-07c）→ 必须判「不许写耗时」（它自己会打总耗时）；
  ⑨ **负面对照（必须仍然全绿）**：表格行里"数字在前、脚本在后"、又没写「判据」的那种形状 ——
     旧版会把**上一个格子**的括号当成这处的声明，把 _check_backup.py 的条数错记到
     _check_all.py 头上（一条假红，真值还算不出来）。这个形状**故意不判**，所以要钉住它必须全绿。

## ⛔ 已知盲区（不许当成"已覆盖"）
- 超过 200 字符的超长行**整行不判**（定位表那些几百字一行会顺带提到别的数字）；
- 这一族只认「N **条**」，「N **项**」不判 —— docs/CORE_AND_EXTENSION.md 里
  「核心冻结（7 项）」早就该是 39 项，没有任何东西守着它（2026-09-25 靠人眼抓到）。

## ⛔ 它自己踩过的坑（2026-09-26，R3-07c 顺手抓到的）

`Sandbox._mutate()` 里曾经粘着一段**跑不起来**的兜底代码（第二轮 R2-05 加的「报表锚点跟着搬家走」）：
它引用了一个**未定义的 `old`**、又在 `@staticmethod` 里用 `self` —— 一跑就 `NameError`。
也就是说：**这份反向验证从那次编辑起就没跑通过**，而外面没有任何东西发现它（它的形状是对的，
`_check_reverse_verify_restore.py` 只判「有没有按字节还原」，不判「跑不跑得起来」）。
已删掉那段；没有任何用例需要它（没有一个注入锚在报表源码里）。
将来真需要「锚点跟着搬家走」时，写成**模块级的 `sub_anywhere(old, new)` 注入器**，⛔ 别再塞进 `_mutate`。
教训：反向验证脚本自己也是代码，**它坏掉的样子是「安静地什么都不注入」**。

⚠️ 与其它反向验证同一套纪律：注入/还原都按**字节**做，跑完逐文件核对
（本项目栽过"注入把 bug 留在源码里"）。跑之前先上注入锁（lock_reverse_verify）。

用法：python _tools/qa/_reverse_verify_live_doc_counts.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_live_doc_counts.py"

AGENTS = ROOT / "AGENTS.md"
CORE_EXT = ROOT / "docs" / "CORE_AND_EXTENSION.md"
BACKUP_README = ROOT / "_tools" / "backup" / "README.md"
NL = chr(10)


def _lines(text: str) -> list[str]:
    return text.split(NL)


def _one(marker: str, text: str) -> int:
    """锚点要**恰好命中一行**：命中 0 行或 2 行都当场报错，不许悄悄跳过。"""
    hits = [i for i, ln in enumerate(_lines(text)) if marker in ln]
    if len(hits) != 1:
        raise ValueError(f"锚点 {marker!r} 命中 {len(hits)} 行（要恰好一行；锚点变了就改本脚本）")
    return hits[0]


def after_line(marker: str, extra: str):
    """在含 marker 的那一行**后面**插一整行（加法式注入，不碰原文）。"""

    def f(text: str) -> str:
        i = _one(marker, text)
        out = _lines(text)
        out.insert(i + 1, extra)
        return NL.join(out)

    return f


def on_line(marker: str, extra: str):
    """把 extra 追加到含 marker 的那一行**行尾**。"""

    def f(text: str) -> str:
        i = _one(marker, text)
        out = _lines(text)
        out[i] = out[i] + extra
        return NL.join(out)

    return f


def sub_once(old: str, new: str):
    def f(text: str) -> str:
        if text.count(old) != 1:
            raise ValueError(f"注入锚点出现 {text.count(old)} 次（要恰好一次）：{old!r}")
        return text.replace(old, new, 1)

    return f


CRLF_TEXT = chr(13) + chr(10)
CRLF_BYTES = CRLF_TEXT.encode("utf-8")

CASES: list[tuple] = [
    (
        "检查脚本数写错 → 必须点名那一页并写出实际值",
        AGENTS,
        False,
        after_line("_check_all.py --list", "python _tools/qa/_check_all.py  # 共 999 个脚本"),
        True,
        "写着「999 个脚本」",
    ),
    (
        "端点索引端点数写错 → 必须拿端点索引生成器的 collect() 对账",
        AGENTS,
        False,
        on_line("端点条数以文件为准", "，一共 999 个端点"),
        True,
        "写着「999 个端点」",
    ),
    (
        "反向验证份数写错 → 必须拿 _reverse_verify_all.py --list 自己列的对账",
        CORE_EXT,
        False,
        sub_once(
            "python _tools/qa/_reverse_verify_core_freeze.py        "
            "# 证明它真的会红（注入条数以它自己打印的为准）",
            "python _tools/qa/_reverse_verify_core_freeze.py  # 999 份",
        ),
        True,
        "写着「999 份（反向验证）」",
    ),
    (
        "orders.py 的规模写错 → 必须拿文件行数对账（阶段 4 之后它只剩装配说明）",
        CORE_EXT,
        False,
        on_line("_check_ai_guardrails.py", "；orders.py 现在 999 行"),
        True,
        "999 行（orders.py）",
    ),
    (
        "可跑脚本的判据条数写错（54→53）→ 必须拿它自己打印的总数对账",
        BACKUP_README,
        False,
        sub_once("（54 条判据，", "（53 条判据，"),
        True,
        "写着「53 条判据（_check_backup.py）」",
    ),
    (
        "_check_all.py 的条数手写 → 必须判「不许手写」（它在这里跑不动）",
        CORE_EXT,
        False,
        after_line("_check_ai_guardrails.py", "python _tools/qa/_check_all.py  # 100 条判据"),
        True,
        "不许手写",
    ),
    (
        "反向验证脚本的注入条数手写 → 同样判「不许手写」（跑它会注入并改工作区）",
        CORE_EXT,
        False,
        after_line("_check_ai_guardrails.py",
                   "python _tools/qa/_reverse_verify_core_freeze.py  # 9 条注入"),
        True,
        "不许手写",
    ),
    (
        "LIVE 清单指到一个不存在的活文档 → 必须报「不存在」，不许安静地少判一页",
        CHECK,
        True,
        sub_once('    "_tools/backup/README.md",', '    "_tools/backup/README-已经改名的.md",'),
        True,
        "不存在（活文档被删/改名了？",
    ),
    (
        # ⭐ R3-07c：给 `_check_all.py` 写耗时是同一类毛病 —— 写的时候是真的，之后必然过期
        #    （实测 AGENTS.md 写着「约一分钟」而它当时要 171 秒）。那个数现在由它自己打。
        '给 `_check_all.py` 手写耗时 → 必须判「不许写耗时」（它自己会打总耗时）',
        AGENTS,
        False,
        after_line('_check_all.py --list', 'python _tools/qa/_check_all.py  # 约 90 秒'),
        True,
        '手写了耗时',
    ),
    (
        # ⛔ 负面对照：数字在**上一个格子**里、又没写「判据/注入」时，不许把它算到后面那个脚本头上
        #    （旧版会记成「_check_all.py 有 999 条」→ 假红，而且那个真值本来也算不出来）。
        "负面对照：表格行里跨格子的数字不许被误认成后面那个脚本的条数（旧版的假红）",
        BACKUP_README,
        False,
        sub_once("（54 条，进", "（999 条，进"),
        False,
        "",
    ),
]


class Sandbox:
    """按字节记住原样，最后一次性还原（⛔ 不用 git checkout --：那会抹掉未提交的真实改动）。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    @staticmethod
    def _mutate(data: bytes, mutate) -> bytes:
        crlf = CRLF_BYTES in data
        text = data.decode("utf-8")
        if crlf:
            text = text.replace(CRLF_TEXT, chr(10))
        text = mutate(text)
        return (text.replace(chr(10), CRLF_TEXT) if crlf else text).encode("utf-8")

    def apply(self, path: Path, mutate) -> None:
        self.saved.setdefault(path, path.read_bytes())
        path.write_bytes(self._mutate(path.read_bytes(), mutate))

    def mutate_copy(self, path: Path, mutate) -> Path:
        """改一份**副本**：注入目标就是检查脚本自己时用（别让检查在被改的状态下跑自己）。"""
        tmp = path.with_suffix(".py.injected")
        tmp.write_bytes(self._mutate(path.read_bytes(), mutate))
        return tmp

    def restore(self) -> None:
        for path, raw in self.saved.items():
            path.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check(target: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(target or CHECK)],
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

        for label, path, is_check_itself, mutate, expect_red, keyword in CASES:
            sb.restore()
            tmp: Path | None = None
            try:
                if is_check_itself:
                    tmp = sb.mutate_copy(path, mutate)
                    code, out = run_check(tmp)
                else:
                    sb.apply(path, mutate)
                    code, out = run_check()
            finally:
                if tmp is not None and tmp.exists():
                    tmp.unlink()
                sb.restore()
            if expect_red:
                hit = code != 0 and keyword in out
                detail = "报了红" if code != 0 else "仍然全绿（判据没牙）"
                if code != 0 and keyword not in out:
                    detail += "，但没点出「" + keyword + "」"
            else:
                hit = code == 0
                detail = "仍然全绿（这正是要的：那个形状故意不判）" if hit else "被误判成红了（假红回来了）"
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
          + str(len(CASES) - 1) + " 条注入各自让对应的判据报红，负面对照仍然全绿，还原后逐字节一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

