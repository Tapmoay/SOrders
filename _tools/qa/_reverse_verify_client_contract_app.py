#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_client_contract.py` 的**App 那一半**真的会红。

## 为什么单独一份（而不是原来那份）
原来的 `_reverse_verify_client_contract.py` 一半用例打 H5、一半打 App/后端；2026-09-25 前端 H5 按用户拍板
归档（`frontend/` 不在仓库里了）→ 那份脚本的 H5 用例没有主体，逐条摘的成本高于收益，于是整份删掉。
但**App 那一半的红线不能因此失去反向验证** —— 这一份把它补回来（只打 App 与后端）。

## 四种破坏（每一种都必须让红线当场红）
  ① App 的状态集合少一档（`RECALLABLE` 去掉 DISPATCHED）；
  ② App 的状态集合少一档（`CANCELLABLE` 去掉 DISPATCHED）；
  ③ App 全量状态集合里少一档（`ALL` 里的 DISPATCHED 拼错）；
  ④ 撤回按钮写回硬编码（`OrderStatusModel.RECALLABLE` → `== "ACCEPTED"`）。

⚠️ 与其它反向验证同一套纪律：注入/还原都按**字节**做，跑完逐文件核对。
用法：python _tools/qa/_reverse_verify_client_contract_app.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_client_contract.py"
KT = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
MODEL = "android/app/src/main/java/com/tapmoay/sorders/core/OrderStatusModel.kt"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherOrdersScreen.kt"

CASES: list[tuple] = [
    (
        "App 的 RECALLABLE 少一档（派错司机之后撤不回来）",
        MODEL,
        'val RECALLABLE: Set<String> = setOf("DISPATCHED", "ACCEPTED")',
        'val RECALLABLE: Set<String> = setOf("ACCEPTED")',
        "RECALLABLE",
    ),
    (
        "App 的 CANCELLABLE 少一档（货主撤销按钮少一档可撤）",
        MODEL,
        'val CANCELLABLE: Set<String> = setOf("PENDING_DISPATCH", "DISPATCHED")',
        'val CANCELLABLE: Set<String> = setOf("PENDING_DISPATCH")',
        "CANCELLABLE",
    ),
    # ⚠️ 2026-09-25：原来还有一条「ALL 里少一档」的注入，**删掉了** —— 它的锚点（裸的 "DISPATCHED",）
    #    在 OrderStatusModel.kt 里出现 7 次，拿不到「恰好一次」的锚点就只能 SKIP；
    #    与其留一条永远 SKIP 的，不如删掉并把原因写在这里。
    (
        "撤回按钮写回硬编码（少一档就撤不回来 —— 审计 H1 的原形）",
        SCREEN,
        "if (order.status in OrderStatusModel.RECALLABLE) {",
        'if (order.status == "ACCEPTED") {',
        "RECALLABLE",
    ),
]

CRLF = chr(13) + chr(10)
CRLF_B = CRLF.encode("utf-8")


class Sandbox:
    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, rel: str, old: str, new: str) -> None:
        p = ROOT / rel
        self.saved.setdefault(p, p.read_bytes())
        raw = p.read_bytes()
        crlf = CRLF_B in raw
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
        for label, rel, old, new, keyword in CASES:
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
            hit = code != 0 and keyword in out
            detail = "报了红" if code != 0 else "仍然全绿（判据没牙）"
            print("  [" + ("OK" if hit else "MISS") + "] " + label + " → " + detail)
            if not hit:
                bad += 1
                for ln in out.splitlines()[-8:]:
                    print("        " + ln)
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
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：App 那一半的每一种破坏都被抓到了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
