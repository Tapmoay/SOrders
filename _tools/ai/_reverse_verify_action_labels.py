#!/usr/bin/env python3
"""反向验证 _tools/ai/_check_action_labels.py（审计卡片的「动作名 → 中文」）真的会红。

## 为什么这条要反向验证
它守的是一个**用户已经报过**的缺陷：审计卡片最上面那行字是动作名，表里漏一个，那一行就直接显示
原始码 —— 真机上出现过 `USER_RESTORE` / `USER_DELETE` / `PRODUCT_DELETE` / `PRODUCT_RESTORE` 四行英文，
用户的反馈是「用户根本就看不懂」。

而它的判据形状是「**从后端源码扫出动作名 → 逐个要求 Kotlin 那张表里有中文**」——
两侧都是**文本匹配**，所以**注释能满足它**（本项目已经栽过 6 次同一类洞）。这一份就是来量这件事的。

## 五条注入（每条都必须让红线当场红）
| # | 注入 | 现实里谁会这么干 |
| --- | --- | --- |
| ① | 后端新加一个没中文的动作 | 后端加了新动作、App 侧那张表没跟上（这就是缺陷本身） |
| ② | App 侧删掉一条中文 | 重构 when 块时删掉一行 |
| ③ | **把那条中文注释掉** | 「这条暂时不用」→ 卡片上又变回原始码 |
| ④ | actionLabel 被改名/搬走 | 判据自己得硬失败（不许静默放行） |
| ⑤ | 解析器失配（后端一个动作都扫不到） | 正则被改坏 → 判据空转 |

⚠️ 与仓库里其它反向验证同一套纪律：按**字节**备份/还原、跑完逐文件核对、不碰 git checkout --。

用法：python _tools/ai/_reverse_verify_action_labels.py
      python _tools/ai/_reverse_verify_action_labels.py --list
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

#: ⛔ 子进程一律按 UTF-8 读写：本机（Windows）上 pytest/脚本默认按 GBK 写 stdout，
#: 而 `raise SystemExit("中文")` 走的是 **stderr**、**不受 stdout 的 reconfigure 影响** ——
#: 于是断言里的中文匹配不上（2026-09-25 实测：第 ④ 条就是因为这个假 MISS 的）。
RUN_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/ai/_check_action_labels.py"
API = "backend/app/api/v1/expenses.py"
REPORT_CENTER = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 后端新加一个动作，App 侧没有中文",
        API,
        "from fastapi import APIRouter",
        "from fastapi import APIRouter\n\n# 探针：模拟「后端加了新动作，App 那张表没跟上」\n"
        "_ACTION_LABEL_PROBE = OperationAction.ACTION_LABEL_PROBE",
        "没有中文名",
    ),
    (
        "② App 侧删掉一条中文",
        REPORT_CENTER,
        # ⚠️ Kotlin 的 when 分支**不写逗号**（第一版锚点带了逗号 → 一条都没命中）。
        '"ORDER_CREATE" -> "新建订单"',
        '"ORDER_CREATE" -> ""',
        "没有中文名",
    ),
    (
        "③ 把那条中文**注释掉**（注释不该算数）",
        REPORT_CENTER,
        '"ORDER_CREATE" -> "新建订单"',
        '// "ORDER_CREATE" -> "新建订单"',
        "没有中文名",
    ),
    (
        "④ actionLabel 被改名/搬走（判据要硬失败，不许静默放行）",
        REPORT_CENTER,
        "private fun actionLabel(",
        "private fun actionLabelRenamed(",
        "找不到 actionLabel",
    ),
    (
        "⑤ 解析器失配：后端一个动作都扫不到（判据空转）",
        "_tools/ai/_check_action_labels.py",
        'ACTION_IN_CODE = re.compile(r"OperationAction\\.([A-Z][A-Z0-9_]{3,})|',
        'ACTION_IN_CODE = re.compile(r"OperationActionZZZ\\.([A-Z][A-Z0-9_]{3,})|',
        "解析挂了",
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
    print(f"✅ {total}/{total} 全部成立：审计卡片的中文名这条红线真的会红")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())