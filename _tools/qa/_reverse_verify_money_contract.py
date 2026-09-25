#!/usr/bin/env python3
"""反向验证「钱只有一个实现」的**契约判据**（_check_money_contract.py）真的会红。

## 为什么这条要反向验证
报告 §7 要的是「Domain Contract → 接口 → 唯一实现 → 所有消费方依赖接口」。
这条判据守的东西**坏起来一声不响**：契约表还在、判据还绿，而实际上
① 消费方又绕回去直接 import 实现、② 契约里"又抄了一份实现"（接口变第二个实现点）、
③ 某个"消费方"其实什么也没用（假消费方）、④ 契约模块自己长出算式。
四种都**不会让任何测试变红** —— 只会让「钱只有一处实现」从代码退回成一份文档。

所以四种各注入一次（注入＝把工作区改成"该报红"的样子，跑完按字节还原）：

  ① 消费方绕回实现模块（`services/message_center.py` 改回从 `driver_pay` import）→ 必须红；
  ② 契约里转出的符号不是那条实现（把 `money_of` 指到契约自己新加的一个同名函数）→ 必须红（`__module__` 对不上）；
  ③ 塞一个**假消费方**（`api/v1/order_templates.py` 只 import 了 `q2`，却声明成 order_money 的消费方）→ 必须红；
  ④ 契约模块里加一行钱算式 → 必须红（接口里藏实现）。

⚠️ 与其它反向验证同一套纪律：注入/还原都按**字节**做，跑完逐文件核对。
用法：python _tools/qa/_reverse_verify_money_contract.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_money_contract.py"
CONTRACT = "backend/app/services/money_contract.py"
MESSAGE = "backend/app/services/message_center.py"
NL = chr(10)


def sub_once(old: str, new: str):
    def f(text: str) -> str:
        if text.count(old) != 1:
            raise ValueError("注入锚点出现 " + str(text.count(old)) + " 次（要恰好一次）：" + repr(old))
        return text.replace(old, new, 1)

    return f


def both(*fns):
    """一个文件上做两处改动（顺序执行）。"""

    def f(text: str) -> str:
        for fn in fns:
            text = fn(text)
        return text

    return f


CASES: list[tuple[str, str, object, str]] = [
    (
        "消费方绕回实现模块（不再依赖接口）",
        MESSAGE,
        sub_once("from app.services.money_contract import has_per_order_pay",
                 "from app.services.driver_pay import has_per_order_pay"),
        "绕过了契约",
    ),
    (
        "契约里转出的不是那条实现（又抄了一份）",
        CONTRACT,
        sub_once("def __getattr__(name: str):",
                 "def money_of(*_a, **_k):" + NL + "    return None" + NL + NL + NL
                 + "def __getattr__(name: str):"),
        "转出的符号与声明对不上",
    ),
    (
        "塞一个假消费方（声明了却什么都没用）",
        CONTRACT,
        sub_once('            "api/v1/shipper_ledger.py",',
                 '            "api/v1/shipper_ledger.py",' + NL + '            "api/v1/order_templates.py",'),
        "假消费方",
    ),
    (
        "契约模块自己长出钱算式（接口里藏实现）",
        CONTRACT,
        sub_once("def __getattr__(name: str):",
                 "def _zzz_probe():" + NL + "    return line_total - 1" + NL + NL + NL
                 + "def __getattr__(name: str):"),
        "契约模块里出现了算术",
    ),
]

CRLF = chr(13) + chr(10)
CRLF_B = CRLF.encode("utf-8")


class Sandbox:
    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, path: Path, mutate) -> None:
        self.saved.setdefault(path, path.read_bytes())
        data = path.read_bytes()
        crlf = CRLF_B in data
        text = data.decode("utf-8")
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
        text = mutate(text)
        path.write_bytes((text.replace(chr(10), CRLF) if crlf else text).encode("utf-8"))

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
    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条判据就没过")
            print(out[-1200:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时判据全绿 —— " + last.strip())

        for label, rel, mutate, keyword in CASES:
            sb.restore()
            try:
                sb.apply(ROOT / rel, mutate)
                code, out = run_check()
            finally:
                sb.restore()
            hit = code != 0 and keyword in out
            detail = "报了红" if code != 0 else "仍然全绿（判据没牙）"
            if code != 0 and keyword not in out:
                detail += "，但没点出「" + keyword + "」"
            print("  [" + ("OK" if hit else "MISS") + "] " + label + " → " + detail)
            if not hit:
                bad += 1
                for ln in out.splitlines()[-8:]:
                    print("        " + ln)

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
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：" + str(len(CASES))
          + " 种破坏方式都被判据点名，还原后逐字节一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
