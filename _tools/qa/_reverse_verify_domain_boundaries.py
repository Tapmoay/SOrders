#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_domain_boundaries.py` 真的抓得住那几类错误。

## 为什么
领域边界地图最容易的退化方式不是"报错"，而是**悄悄变成装饰**：地图还在、格式还好看，
但里面的表名 / 命令 / 事件早就与代码对不上了。那种地图比没有地图更糟 ——
没有地图时你会去读代码拿一手真相，有错地图时你会相信结论直接动手。

## 十二种破坏
| # | 注入 | 期望 |
| --- | --- | --- |
| ① | 从某个域的 owns 里拿掉一张表 | 红：那张表成了孤儿 |
| ② | 把别人的表加进自己的 owns | 红：一张表两个拥有者 |
| ③ | owns 里写一张项目里没有的表 | 红：写错了名字 |
| ④ | 命令写一个不存在的函数 | 红：函数不存在 |
| ⑤ | 事件写一个代码里没人产生过的类型 | 红：代码里没有 enqueue 产生它 |
| ⑥ | 把某个事件从声明里删掉 | 红：代码里产生的事件没有域认领 |
| ⑦ | reads 里写本域自己的表 | 红：reads 只登记跨域读边 |
| ⑧ | reads 把某张表指给错误的域 | 红：读边指错了域 |
| ⑨ | 某个域没有命令，理由缩成三个字 | 红：无命令的理由太短 |
| ⑩ | 某个域不拥有表，却标了 pure_consumer: no | 红：不拥有表却没标纯消费者 |
| ⑪ | 「为什么是它自己的域」缩成三个字 | 红：理由太短 |
| ⑫ | 把一个 domain 块改成 text 块（判据读不出来） | 红：域的个数少了一个、表成了孤儿 |

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
CHECK = ROOT / "_tools/qa/_check_domain_boundaries.py"
DOC = "docs/DOMAIN_BOUNDARIES.md"
#: 三个反引号。用 chr(96) 拼而不是写进源码：本文件里出现裸反引号会把 markdown 弄乱。
FENCE = chr(96) * 3

#: 反复用到的锚点（都取**整行**，保证恰好命中一次）。
IDENTITY_OWNS = "owns: users, usage_counters"
ORDER_OWNS = "owns: orders, order_products, order_templates, order_template_categories"
ORDER_READS = "reads: users@identity, products@catalogue, shipper_addresses@party, driver_billing_rules@settlement"
RETURN_EVENTS = "events: returns.requested, returns.rejected, returns.request_closed, returns.done"
FREIGHT_REASON = "无命令的理由: 这一域的增删改**全部内联在** api/v1/freight_templates.py、api/v1/freight_categories.py、api/v1/vehicles.py 的路由里，还没有应用层函数 —— 如实登记，不假装已经有。"
REPORT_WHY = "为什么是它自己的域: 报表不拥有任何事实 —— 它把别的域的既成事实**读**出来做聚合。所以它是一个纯消费者，这个「什么都不拥有」本身就是它的边界。"
SELF_READ = "reads: orders@order, users@identity, products@catalogue, shipper_addresses@party, driver_billing_rules@settlement"
WRONG_DOMAIN = "reads: users@identity, products@money, shipper_addresses@party, driver_billing_rules@settlement"
NO_REASON = "无命令的理由: 暂无。"
THIN_WHY = "为什么是它自己的域: 报表。"
FEWER_EVENTS = "events: returns.requested, returns.rejected, returns.request_closed"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 从 identity 的 owns 里拿掉一张表（那张表成了孤儿）",
        DOC, IDENTITY_OWNS, "owns: users",
        "没有拥有者",
    ),
    (
        "② 把 ledgers 也塞进 order 的 owns（一张表两个拥有者）",
        DOC, ORDER_OWNS, ORDER_OWNS + ", ledgers",
        "有**两个**拥有者",
    ),
    (
        "③ owns 里写一张项目里没有的表",
        DOC, IDENTITY_OWNS, IDENTITY_OWNS + ", no_such_table",
        "项目里没有这张表",
    ),
    (
        "④ 命令写一个不存在的函数",
        DOC, "services.cost_history:record_cost", "services.cost_history:record_cost_typo",
        "对不上代码",
    ),
    (
        "⑤ 事件写一个代码里没人产生过的类型",
        DOC, "returns.request_closed", "returns.request_closed_typo",
        "声称产生事件",
    ),
    (
        "⑥ 把 returns.done 从声明里删掉（代码里产生的事件没人认领）",
        DOC, RETURN_EVENTS, FEWER_EVENTS,
        "没有域认领",
    ),
    (
        "⑦ reads 里写本域自己的表（orders@order 落在订单域自己头上）",
        DOC, ORDER_READS, SELF_READ,
        "那是**自己的**表",
    ),
    (
        "⑧ reads 把 products 指给 money（读边指错域 = 偷偷读）",
        DOC, ORDER_READS, WRONG_DOMAIN,
        "读边指错了域",
    ),
    (
        "⑨ freight 没有命令，理由缩成三个字",
        DOC, FREIGHT_REASON, NO_REASON,
        "无命令的理由",
    ),
    (
        "⑩ reporting 不拥有表，却把 pure_consumer 改成 no",
        DOC, "events: -" + chr(10) + "pure_consumer: yes", "events: -" + chr(10) + "pure_consumer: no",
        "却没标 pure_consumer: yes",
    ),
    (
        "⑪ 「为什么是它自己的域」缩成三个字",
        DOC, REPORT_WHY, THIN_WHY,
        "太短",
    ),
    (
        "⑫ 把一个 domain 块改成 text 块（判据读不出来）",
        DOC, FENCE + "domain" + chr(10) + "name: identity", FENCE + "text" + chr(10) + "name: identity",
        "个域",
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
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：孤儿表 / 双主表 / 假表名 / 假命令 / 假事件 / "
          "无主事件 / 自读边 / 错域读边 / 敷衍理由 / 逃逸的纯消费者 / 坏掉的围栏 都会被抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
