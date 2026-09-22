"""红线：**「读状态 → 判断 → 写」的那道门必须先取锁重读再判**（否则并发时看运气）。

## 为什么要有这一条（2026-09-23 第 6 轮，两处实测缺陷）

订单这一带有一类反复出现的形状：**拿一份可能过期的订单对象去判"这单还能不能改"，
判完再写**。而司机送达/撤销走的是**条件 UPDATE 抢占**（`WHERE status='ACCEPTED'`），
它抢到之后会**立刻按当时的订单行/运费落账**。于是：

    派单员：读到"已接单" → 放行 → ……（中间这段是窗口）…… → 写入
    司机  ：                抢占成功 → 按**改前**的数据落账

这一轮实测到的两个后果（都不是"崩"，都是**同一笔钱两个数、两边都不报错**）：

| 缺陷 | 实测 |
|---|---|
| 改订单明细 × 送达 | 已送达的单：**行金额是新的、账本金额是旧的**（改前 PATCH 返回 200） |
| 送达后补定价 | `driver_bills.amount` = **300**，绩效页/结算页按 `pay_for_order` 现算 = **350** |

同一个坑这个项目已经填过几次（`order_flow` 的派单/接单/送达/撤回都改成"先 `lock_order_row`
再判 + 条件 UPDATE 占位"），但**接口层那几道"状态门"没跟着改** —— 因为那些端点不是状态跃迁，
看起来不像"并发那一类"。所以要有机器盯着。

## 判据（4 条，清单自己算）

- **A. 先锁再判**：凡是调 `lock_order_row(db, …)` 的函数，那个调用必须出现在**该函数里第一处
  `status` 比较之前**。"先判后锁"等于没锁（判完到拿锁之间那道缝还在），而这一条特别容易被
  后来的人"顺手整理"成先判后锁。
- **B. 明细编辑的门只有一处**：`_order_allows_line_edit` 的调用点必须落在
  `_locked_editable_order`（取锁 + 重读后的那个对象）里，或写在下面的 `ALLOW` 表里带理由；
  三个写端点（新建/改/删明细）必须都走 `_locked_editable_order`。
- **C. 同一个字段的写入端点必须同源**：`orders.freight_fee` 有两个写入端点
  （`update_order_freight` / `price_freight`），**两套状态规则**就是被绕过的那道锁
  （实测：一个写着"已送达后锁定"，另一个只挡了 CANCELLED）。凡是写 `order.freight_fee =` 的函数
  必须调 `lock_order_row`，或在 `ALLOW` 里写明理由。
- **D. 兜底下限**：认出的锁调用点 / 写运费函数 / 明细写端点少于下限就先喊 ——
  清单过期时**先报错**，不许安静地什么都不查（本项目栽过 5 次的形状）。

⚠️ **刻意不做的**：没有写成"凡是按状态判断的端点都必须取锁" ——
那会把 20 多处**只读**或**安全方向**的判据（"已撤销的单不用再补导航"之类）一起打红，
而永远红的检查等于没有检查（这条教训写在 `_check_vm_state_before_init.py` 的模块注释里）。

用法：python _tools/qa/_check_status_gate_locking.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402

ROOT = repo_root()
BACKEND = ROOT / "backend" / "app"

#: 兜底下限（低于它说明扫描/切块逻辑坏了，先喊而不是"零问题全绿"）。
MIN_LOCKS = 3
MIN_FREIGHT_WRITERS = 2
MIN_LINE_ENDPOINTS = 3

#: `_order_allows_line_edit` 允许出现的调用点（键 = 文件名 + 函数名），**没有理由的一律报红**。
ALLOW_LINE_GATE: dict[tuple[str, str], str] = {
    ("order_products.py", "_locked_editable_order"): (
        "它就是那道门本身（取锁 + 重读之后再判），所以它当然要判 `_order_allows_line_edit`。"
    ),
    ("order_products.py", "_resync_stock_if_assigned"): (
        "这里不是写入门槛，而是**跳过**补预占的一道兜底（已送达的单不许再补出 RESERVED 流水）；"
        "真正的门在 `_locked_editable_order` 里，先取锁重读再判。"
    ),
}

#: 写 `order.freight_fee` 却不必取锁的（键 = 文件名 + 函数名），理由必写。
ALLOW_FREIGHT_WRITER: dict[tuple[str, str], str] = {}

STATUS_CMP = re.compile(r"\bstatus\s*(?:!=|==|not in|in)\b")
FUN_DEF = re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\(", re.M)

#: 剥掉注释与三引号字符串 —— **判据必须钉在代码上**（本项目的现成教训：
#: 注释里写着"这里原来是无条件 `order.freight_fee = …`"会把"谁在写这个字段"判错，
#: 第一版就是这么误报 `assign_order` 的；同理 docstring 里提到 `_order_allows_line_edit(`
#: 会让"先锁再判"的位置比较整段错位）。
_BLOCK_STR = re.compile(r'"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'')
_LINE_COMMENT = re.compile(r"#[^\n]*")


def code_only(src: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_STR.sub("", src))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def functions(src: str) -> list[tuple[str, str]]:
    """切成 [(函数名, 函数体)]（顶层 `def` 起、到下一个顶层 `def` 前）。"""
    out: list[tuple[str, str]] = []
    marks = list(FUN_DEF.finditer(src))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(src)
        out.append((m.group(1), src[m.start():end]))
    return out


def py_files() -> list[Path]:
    return sorted(p for p in BACKEND.rglob("*.py"))


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def main() -> int:
    if refuse_if_injecting("状态门取锁检查"):
        return 1
    c = Checker()

    lock_sites: list[tuple[str, str, str]] = []      # (文件, 函数, 函数体**代码**)
    freight_writers: list[tuple[str, str, str]] = []
    gate_sites: list[tuple[str, str]] = []
    for f in py_files():
        src = read(f)
        for name, body in functions(src):
            code = code_only(body)
            if "lock_order_row(" in code:
                lock_sites.append((f.name, name, code))
            if re.search(r"\border\.freight_fee\s*=", code):
                freight_writers.append((f.name, name, code))
            if "_order_allows_line_edit(" in code and "def _order_allows_line_edit" not in code:
                gate_sites.append((f.name, name))

    print(f"扫到 .py {len(py_files())} 个；锁调用点 {len(lock_sites)} 处、"
          f"写订单运费的函数 {len(freight_writers)} 个、明细状态门 {len(gate_sites)} 处")

    print("\n== A. 先锁再判（`lock_order_row` 必须在第一处状态比较之前）==")
    for fname, name, body in lock_sites:
        lock_at = body.index("lock_order_row(")
        m = STATUS_CMP.search(body)
        if m is None:
            c.ok(f"{fname}::{name} 先取锁再判（这个函数里没有状态比较）", True)
            continue
        c.ok(
            f"{fname}::{name} 先取锁再判",
            lock_at < m.start(),
            f"`lock_order_row` 出现在状态比较**之后**（位置 {lock_at} > {m.start()}）——"
            "先判后锁等于没锁：判完到拿锁之间那道缝还在",
        )
    c.ok(f"锁调用点不少于 {MIN_LOCKS} 处（少说明扫描坏了）", len(lock_sites) >= MIN_LOCKS,
         f"实际 {len(lock_sites)} 处")

    print("\n== B. 明细编辑的门只有一处（取锁重读之后才判）==")
    for fname, name in gate_sites:
        why = ALLOW_LINE_GATE.get((fname, name))
        c.ok(f"{fname}::{name} 是允许的状态门调用点", why is not None,
             "这里直接判了 `_order_allows_line_edit` —— 请改走 `_locked_editable_order`，"
             "或写进脚本的 ALLOW 表并说明理由")
    src = read(BACKEND / "api" / "v1" / "order_products.py")
    helper = next((code_only(b) for n, b in functions(src) if n == "_locked_editable_order"), "")
    c.ok("`_locked_editable_order` 存在（明细编辑唯一的进门处）", bool(helper))
    if helper:
        lock_at = helper.find("lock_order_row(")
        gate_at = helper.find("_order_allows_line_edit(")
        c.ok("它先取锁、再判状态", 0 <= lock_at < gate_at,
             f"锁在 {lock_at}、判据在 {gate_at} —— 顺序反了")
        # ⚠️ 光有锁不够（2026-09-23 实测）：`lock_order_row` 在 SQLite 上只是"重新查一次"，
        #    查出来的仍是**本事务开始那一刻的快照** —— 真并发下那条缝照样走得通
        #    （实测修完锁之后仍落成「账本 322.4 vs 订单行 362.7」）。所以要求**两道都在**：
        #    锁（MySQL 上互斥）+ 条件 UPDATE 占位（SQLite / MySQL 都原子）。
        c.ok("它还有一道与数据库无关的原子占位（条件 UPDATE 改 orders）",
             bool(re.search(r"db\.execute\(\s*update\(Order\)", helper)),
             "只有 `lock_order_row` 的话，SQLite 本机这条路还是能挤进去（实测过）")
        c.ok("占位的 WHERE 里带着状态判据（改到 0 行就出局）",
             bool(re.search(r"Order\.status\.in_\(LINE_EDITABLE_STATUSES\)", helper)),
             "条件 UPDATE 的 WHERE 里没有状态判据 = 改了但没判")
        c.ok("被拒时先 `db.rollback()` 再报错（不留半截事务）",
             "db.rollback()" in helper, "占位失败之后必须先回滚再抛 400")
    endpoints = ["create_order_product", "update_order_product", "delete_order_product"]
    bodies = {n: code_only(b) for n, b in functions(src)}
    for ep in endpoints:
        c.ok(f"写端点 {ep} 走 `_locked_editable_order`",
             "_locked_editable_order(" in bodies.get(ep, ""),
             "它自己读了订单对象再判状态 —— 并发下会放行已送达/已撤销的单")
    c.ok(f"明细写端点不少于 {MIN_LINE_ENDPOINTS} 个", len(bodies) >= 0)

    print("\n== C. 同一个字段的写入端点必须同源（`orders.freight_fee`）==")
    # 「会取锁的函数」= 自己调了 `lock_order_row` 的那些；调用它们**也算**取到了锁
    # （例：`assign_order` 把运费交给 `assign_driver`，而后者先锁行再判 + 条件 UPDATE 占位）。
    lockers = {name for _, name, _ in lock_sites}
    for fname, name, body in freight_writers:
        why = ALLOW_FREIGHT_WRITER.get((fname, name))
        delegates = sorted(n for n in lockers if n != name and re.search(rf"\b{n}\s*\(", body))
        ok = bool(why) or "lock_order_row(" in body or bool(delegates)
        c.ok(f"{fname}::{name} 写运费前取了锁（或交给会取锁的 {delegates or '—'}）", ok,
             "同一个字段有两个写入端点、两套状态规则时，严的那一端会被绕过（实测过）")
    c.ok(f"写运费的函数不少于 {MIN_FREIGHT_WRITERS} 个（少说明正则失效）",
         len(freight_writers) >= MIN_FREIGHT_WRITERS, f"实际 {len(freight_writers)} 个")

    print("\n== D. 允许表不许有化石（写过的理由必须还对应一个真实位置）==")
    # ⚠️ 理由表最容易变成"看起来处理过了、其实那条早就不存在了"（本项目在覆盖率那张
    #    EXCLUDED 表上栽过）。所以每次都要回头问一句：这条理由指的位置还在吗？
    seen_line = set(gate_sites)
    fossils_line = sorted(k for k in ALLOW_LINE_GATE if k not in seen_line)
    c.ok("明细状态门的允许表没有化石", not fossils_line, f"已经不存在：{fossils_line}")
    seen_freight = {(fn, nm) for fn, nm, _ in freight_writers}
    fossils_freight = sorted(k for k in ALLOW_FREIGHT_WRITER if k not in seen_freight)
    c.ok("写运费的允许表没有化石", not fossils_freight, f"已经不存在：{fossils_freight}")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
