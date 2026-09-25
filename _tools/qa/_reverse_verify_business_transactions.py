#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_business_transactions.py` 真的抓得住那几类错误。

## 为什么
这一条判据的价值**全在"可达性"上**：如果调用图解析坏了（或者干脆没解析），
它就退化成"把文档里的名字与源码里的 def 对一遍"—— 而那种检查挡不住最危险的一种错：
**地图上写着一个"看起来应该有"的参与者，代码里其实没有调它**。

## 九种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 把一个参与者换成"看起来应该有"的函数 | 红：走不到它 |
| ② | 入口函数名写错 | 红：入口函数不存在 |
| ③ | 判据自己不再检查"入口有没有提交点" | 红：谁提交的？ |
| ④ | failure 缩成两个字 | 红：太短 |
| ⑤ | 声明一个可达代码里没有的守卫 | 红：找不到对应形状 |
| ⑥ | 守卫名不在词表里 | 红：不在词表里 |
| ⑦ | 事务条数下限失守 | 红：地图缩水了 |
| ⑧ | **不再解开钱契约的转发**（调用图停在契约那一层） | 红：走不到它 |
| ⑨ | **import 时不记符号名**（裸名调用全部落空） | 红：走不到它 |

⚠️ ⑧⑨ 是这一份特有的两条：它们证明"调用图真的在用"，而不是装饰。
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
CHECK = ROOT / "_tools/qa/_check_business_transactions.py"
DOC = "docs/BUSINESS_TRANSACTION_MAP.md"
CHK = "_tools/qa/_check_business_transactions.py"

ACCEPT_PARTS = "participants: services.order_flow:accept_order, core.outbox:enqueue"
ACCEPT_ENTRY = "entry: api.v1.orders_delivery:driver_ack_view"
ACCEPT_FAIL = "failure: 状态不是「已派单」/ 不是派给这个人 → ValueError → 400；CAS 抢先则报「刚刚被改过，请刷新」"
#: ⚠️ 守卫那一行**不唯一**（好几条事务写法一样），所以锚点取「守卫行 + 紧跟的 failure 行」两行。
CREATE_FAIL = "failure: 命令层抛 CommandError（默认 400 + 一句人话）→ 路由翻成 HTTPException → 事务整体回滚：订单、地点、常用度计数、事件一条都不落"
CREATE_GUARDS = "guards: outbox_same_txn" + chr(10) + CREATE_FAIL
ACCEPT_GUARDS = "guards: cas, outbox_same_txn" + chr(10) + ACCEPT_FAIL
#: 结算那条链上**没有发件箱**（accounting_service 不 import outbox）—— 用它测"假守卫"。
PAY_GUARDS = ("guards: cas" + chr(10)
              + "failure: 金额与明细合计不等 / 状态不对 → 400；CAS 抢不到 → 拒绝（两个人在同一天确认同一张结算单）")
CREATE_ENTRY = "entry: api.v1.orders_lifecycle:create_order"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 把一个参与者换成「看起来应该有」的函数（代码里其实没调它）",
        DOC, ACCEPT_PARTS,
        "participants: services.place_service:haversine_m, core.outbox:enqueue",
        "走不到它",
    ),
    (
        "② 入口函数名写错",
        DOC, ACCEPT_ENTRY,
        "entry: api.v1.orders_delivery:driver_ack_view_typo",
        "入口函数不存在",
    ),
    (
        "③ 判据自己不再检查「入口有没有提交点」",
        CHK,
        'if t["same_db"] == "yes" and "db.commit()" not in entry_src:',
        'if t["same_db"] == "yes" and "db.commit_NOPE()" not in entry_src:',
        "谁提交的？",
    ),
    (
        "④ failure 缩成两个字",
        DOC, ACCEPT_FAIL, "failure: 报错",
        "太短",
    ),
    (
        "⑤ 声明一个可达代码里没有的守卫（结算那条链上根本没有发件箱）",
        DOC, PAY_GUARDS, "guards: cas, outbox_same_txn" + chr(10) + PAY_GUARDS.split(chr(10))[1],
        "找不到对应形状",
    ),
    (
        "⑥ 守卫名不在词表里",
        DOC, CREATE_GUARDS, "guards: magic_guard" + chr(10) + CREATE_FAIL,
        "不在词表里",
    ),
    (
        "⑦ 事务条数下限失守（地图被掏空却不喊）",
        CHK, "MIN_TXNS = 10", "MIN_TXNS = 99",
        "地图缩水了",
    ),
    (
        "⑧ 不再解开钱契约的转发（调用图停在契约那一层）",
        CHK, "    n_fwd = _forward_contract(graph)", "    n_fwd = 0",
        "走不到它",
    ),
    (
        "⑨ 「from app.core import outbox; outbox.enqueue()」这种属性调用解析不出方法名",
        CHK,
        '                        callees.add(hit[0] + ":" + fn.attr)',
        '                        callees.add(hit[0])',
        "走不到它",
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
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：假参与者 / 假入口 / 没有提交点 / "
          "敷衍的失败说明 / 假守卫 / 词表外的守卫 / 空地图 / 不解开契约转发 / import 丢符号名 都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
