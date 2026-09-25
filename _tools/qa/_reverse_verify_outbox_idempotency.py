#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_outbox_idempotency.py` 真的抓得住那几类错误。

## 为什么
这一条守的是「事件重投不会多发一条站内信」。它最危险的退化方式是**看起来还在查、其实查不动**：
映射表被掏空、唯一索引被删掉（"先查再插就够了"）、publish 里漏一个幂等键 ——
三种都不会让任何用例失败，只会让「幂等消费」变成一句口号。

## 八种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 事件类型从两张映射表里拿掉（新加事件忘了登记） | 红：没有登记聚合根来源 |
| ② | 映射表指向一个没人填的 payload 键 | 红：没有任何一处入队真的填了它 |
| ③ | 把 NOTIFICATIONS 的唯一索引删掉（退回"先查再插"） | 红：没有 idem_key 的唯一索引 |
| ④ | enqueue 不再写 aggregate_id（映射表成摆设） | 红：没有真的写 aggregate_id |
| ⑤ | 某个 publish 的 create_message 去掉幂等键 | 红：没带幂等键 |
| ⑥ | create_message 去掉插入前的按键查（直接撞唯一索引） | 红：插入前没有按 idem_key 查过 |
| ⑦ | 例外表里的理由删掉「什么时候删掉这一条」 | 红：没写「什么时候删掉这一条」 |
| ⑧ | 反空转下限失守（扫描坏了却不喊） | 红：扫描坏了 |

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
CHECK = ROOT / "_tools/qa/_check_outbox_idempotency.py"
OB = "backend/app/core/outbox.py"
NOTIF = "backend/app/models/notification.py"
MC = "backend/app/services/message_center.py"

ASSIGN_LINE = '    "orders.assigned": "order_id",'
EVENTS_LINE = '    "orders.navigated": "order_id",' + chr(10) + ASSIGN_LINE
RETURNED_LINE = '    "returns.requested": "request_id",'
UNIQ_LINE = '    __table_args__ = (Index("uq_notifications_idem_key", "idem_key", unique=True),)'
AGG_WRITE = "            aggregate_id=aggregate_of(event_type, payload),"
#: ⚠️ 这一行在文件里出现**两次**（插入前的预查 + 撞键后的回查），所以锚点带上后面两行 ——
#:    两处后面的分支正好相反（`is not None: return` vs `is None: raise`），带上就不可能撞。
PREQUERY = ("        existing = db.scalars(select(Notification).where(Notification.idem_key == key)).first()"
            + chr(10) + "        if existing is not None:"
            + chr(10) + "            return existing")
NOAGG_WHY = '"**什么时候删掉这一条**：哪天待派池的推送改成按单发（而不是变了就整体刷一遍）时。"'
KEYED_CALL = '            idem_key="order.assigned" + ":" + str(order_id),'

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 一个事件类型从两张映射表里拿掉（新加事件忘了登记聚合根）",
        OB, ASSIGN_LINE, "",
        "没有登记聚合根来源",
    ),
    (
        "② 映射表指向一个没人填的 payload 键",
        OB, ASSIGN_LINE, '    "orders.assigned": "order_no_nobody_sets",',
        "没有任何一处入队真的填了它",
    ),
    (
        "③ 把站内信幂等键的唯一索引删掉（退回先查再插）",
        NOTIF, UNIQ_LINE, "",
        "唯一索引",
    ),
    (
        "④ enqueue 不再写 aggregate_id（映射表成了摆设）",
        OB, AGG_WRITE, "",
        "没有真的写 aggregate_id",
    ),
    (
        "⑤ 某个由事件驱动的 publish 去掉幂等键",
        MC, KEYED_CALL, "",
        "没带幂等键",
    ),
    (
        "⑥ create_message 去掉插入前的按键查",
        MC, PREQUERY, "        pass",
        "插入前没有按 idem_key 查过",
    ),
    (
        "⑦ 例外表里的理由删掉「什么时候删掉这一条」",
        OB, NOAGG_WHY, '"待派池变了就整体刷一遍，没有具体哪一张单。"',
        "没写「什么时候删掉这一条」",
    ),
    (
        "⑧ 反空转下限失守（扫描坏了却不喊）",
        "_tools/qa/_check_outbox_idempotency.py",
        "MIN_KEYED = 12",
        "MIN_KEYED = 999",
        "覆盖不全",
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
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：漏登记 / 假 payload 键 / 删唯一索引 / "
          "不写聚合根 / 漏幂等键 / 不做插入前查 / 敷衍例外 / 扫描空转 都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
