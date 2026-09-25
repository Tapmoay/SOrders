#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_order_commands.py` 真的抓得住那几类错误。

## 为什么
这一条判据守的是第二轮 R2-02 的核心主张：**订单状态的写入只有一个入口**。
它最容易的退化方式不是"报错"，而是**对账变成两张各说各话的表**：
注册表改了、代码没改（或者反过来），两边都不报错，而"唯一写入口"这句话从此只是口号。

## 十二种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 把一条命令的 to_state 清空（那处跃迁没人声明了） | 红：代码里有一处条件 UPDATE 没被任何命令声明 |
| ② | 把一条命令的前置状态写错 | 红：注册表声明了一处代码里不存在的跃迁 |
| ③ | 把一条命令的目标状态写错 | 红：代码里有一处条件 UPDATE 没被任何命令声明 |
| ④ | 命令的实现写一个不存在的函数名 | 红：实现对不上代码 |
| ⑤ | 命令的权限点改成不存在的名字 | 红：不是 Permission 的成员 |
| ⑥ | 命令声称发一个代码里没人产生过的事件 | 红：没有任何 enqueue 产生它 |
| ⑦ | 把**本域**的表写进 effects | 红：effects 只登记跨域写 |
| ⑧ | 在 api/ 层直接构造订单并写状态（退回到 R2-02 之前的样子） | 红：api/ 层直接构造订单并写状态 |
| ⑨ | 在 order_flow 里偷偷多加一处条件 UPDATE | 红：代码里有一处条件 UPDATE 没被任何命令声明 |
| ⑩ | 不改状态的命令，前置状态少写一个 | 红：前置状态与实现不符 |
| ⑪ | 命令的归属域改成一个地图上没有的域 | 红：归属域不在地图上 |
| ⑫ | 「为什么它是一条独立命令」缩成两个字 | 红：没写「为什么它是一条独立命令」 |
| ⑬ | 从地图的订单域里拿掉一条命令（归属与形状对不上） | 红：不在地图的订单域 commands 行里 |

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
CHECK = ROOT / "_tools/qa/_check_order_commands.py"
REG = "backend/app/commands/registry.py"
FLOW = "backend/app/services/order_flow.py"
API = "backend/app/api/v1/orders_lifecycle.py"
MAP = "docs/DOMAIN_BOUNDARIES.md"

CAS_ACCEPT = 'to_state="ACCEPTED",'
CAS_DELIVERED = 'to_state="DELIVERED",'
FROM_ACCEPT = 'from_states=("DISPATCHED",),'
IMPL_ASSIGN = 'impl="services.order_flow:assign_driver",'
CAP_CREATE = 'capabilities=("ORDER_CREATE",),'
EV_ASSIGN = 'events=("orders.assigned", "orders.pending_pool_changed"),'
EFF_CREATE = 'effects=("operation_logs", "places", "usage_counters", "shipper_contacts"),'
FROM_EDIT = 'from_states=("PENDING_DISPATCH", "DISPATCHED", "ACCEPTED"),'
NAME_CREATE = 'name="order.create",' + chr(10) + '        domain="order",'
WHY_ACCEPT = 'why="司机确认接单：唯一一条**由司机本人**发起、且要求「必须是派给我的那一张」的跃迁。",'
DELETE_LINE = "    order.deleted_at = None"
MARK_RETURNED = "def mark_returned(db: Session, order: Order) -> None:"
EXTRA_CAS = (chr(10) + "    db.execute(update(Order).where(Order.id == order.id, "
             "Order.status == OrderStatus.RETURNED).values(status=OrderStatus.DELIVERED))")

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 把 order.accept 的 to_state 清空（那处跃迁没人声明了）",
        REG, CAS_ACCEPT, 'to_state="",',
        "没被任何命令声明",
    ),
    (
        "② 把 order.accept 的前置状态写成待派单",
        REG, FROM_ACCEPT, 'from_states=("PENDING_DISPATCH",),',
        "注册表声明了一处代码里不存在的跃迁",
    ),
    (
        "③ 把 order.complete 的目标状态写成 CANCELLED",
        REG, CAS_DELIVERED, 'to_state="CANCELLED",',
        "没被任何命令声明",
    ),
    (
        "④ 命令的实现写一个不存在的函数名",
        REG, IMPL_ASSIGN, 'impl="services.order_flow:assign_driver_typo",',
        "对不上代码",
    ),
    (
        "⑤ 命令的权限点改成不存在的名字",
        REG, CAP_CREATE, 'capabilities=("ORDER_CREATE_TYPO",),',
        "不是 Permission 的成员",
    ),
    (
        "⑥ 命令声称发一个代码里没人产生过的事件",
        REG, EV_ASSIGN, 'events=("orders.assigned_typo", "orders.pending_pool_changed"),',
        "没有任何 enqueue 产生它",
    ),
    (
        "⑦ 把**本域**的表写进 effects",
        REG, EFF_CREATE, EFF_CREATE.replace('"shipper_contacts"),', '"shipper_contacts", "orders"),'),
        "只登记跨域写",
    ),
    (
        "⑧ 在 api/ 层直接构造订单并写状态（退回 R2-02 之前的样子）",
        API, DELETE_LINE, DELETE_LINE + chr(10) + "    _probe = Order(status=OrderStatus.PENDING_DISPATCH)",
        "api/ 层直接构造订单并写状态",
    ),
    (
        "⑨ 在 order_flow 里偷偷多加一处条件 UPDATE",
        FLOW, MARK_RETURNED, MARK_RETURNED + EXTRA_CAS,
        "没被任何命令声明",
    ),
    (
        "⑩ order.edit 的前置状态少写一个（ACCEPTED）",
        REG, FROM_EDIT, 'from_states=("PENDING_DISPATCH", "DISPATCHED"),',
        "前置状态与实现不符",
    ),
    (
        "⑪ 命令的归属域改成一个地图上没有的域",
        REG, NAME_CREATE, 'name="order.create",' + chr(10) + '        domain="nowhere",',
        "归属域",
    ),
    (
        "⑫ 「为什么它是一条独立命令」缩成两个字",
        REG, WHY_ACCEPT, 'why="接单",',
        "为什么它是一条独立命令",
    ),
    (
        "⑬ 从地图的订单域里拿掉一条命令（归属与形状对不上）",
        MAP,
        "commands: commands.order:create_order, commands.order:update_order, services.order_flow:assign_driver, services.order_flow:accept_order, services.order_flow:complete_delivery, services.order_flow:cancel_pending, services.order_flow:recall_dispatch, services.order_flow:mark_returned, services.order_flow:split_order",
        "commands: commands.order:update_order, services.order_flow:assign_driver, services.order_flow:accept_order, services.order_flow:complete_delivery, services.order_flow:cancel_pending, services.order_flow:recall_dispatch, services.order_flow:mark_returned, services.order_flow:split_order",
        "不在地图的订单域 commands 行里",
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
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：跃迁多一条/少一条/前置写错、假实现、"
          "假权限点、假事件、本域副作用、API 层回写状态、敷衍理由 都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
