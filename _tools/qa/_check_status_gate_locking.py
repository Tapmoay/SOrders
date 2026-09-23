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
- **C. 同一个字段有多个写入点时，这个字段必须有交代**（2026-09-23 第 8 轮从"只盯运费"泛化）：
  先**盘点** `orders.<字段> =` 的赋值点（剥注释、`=(?!=)`、按 (字段, 文件, 函数) 去重），
  凡是 ≥2 个写入点的字段，要么每个写入点自己取锁 / 有 CAS 占位 / 交给会取锁的函数，
  要么在 `SAME_FIELD_REASONS` 里按**字段**写一句"为什么这些写入点不会分叉"。
  为什么泛化：这一条是从**两次实测缺陷**里长出来的（第 6 轮 `freight_fee` 两个端点两套状态规则 →
  送达后还能定价，账单 300 而结算页 350；第 7 轮 `arrears_unit_id` 三个写入点只有 `pay_order` 清指向 →
  "先挂账 + 按现金送达"落成 `paid=True` 却指着挂账单位 → 那个单位永远删不掉）。
  泛化当轮就抓到**第三处**：`internal_notes` 是"读出来拼一段写回去"的累计文本，
  而 `driver_append_internal_note` 没取锁 → 两个并发追加会吃掉前一段（另一个写入点
  `assign_driver` 早就锁了）。
- **D. 兜底下限 + 理由表防化石**：认出的锁调用点 / 多写入点字段 / 明细写端点少于下限就先喊；
  `ALLOW` 与 `SAME_FIELD_REASONS` 里的键必须还对应着真实位置（本项目在覆盖率那张 EXCLUDED 表上栽过）。

⚠️ **刻意不做的**：没有写成"凡是按状态判断的端点都必须取锁" ——
那会把 20 多处**只读**或**安全方向**的判据（"已撤销的单不用再补导航"之类）一起打红，
而永远红的检查等于没有检查（这条教训写在 `_check_vm_state_before_init.py` 的模块注释里）。
同样地，C 也**不要求**"多写入点必须取锁"：那会把一堆本来就该幂等/同事务的写入点打红；
它要求的是**这个字段有交代**（取锁，或者一句能站得住的理由）。

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
MIN_MULTI_FIELDS = 4
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

#: **同一个字段的多个写入点**按字段写的理由（键 = `orders` 上的字段名）：回答
#: 「这些写入点为什么不会分叉」。⛔ 写不出理由的，就该像第 6·7 轮那两处一样去修，
#: 而不是在这里补一句"没事"。
SAME_FIELD_REASONS: dict[str, str] = {
    # ---- 收款状态那一组：三个写入点（送达 / 现场收款确认 / 挂账）----
    "paid": (
        "三个写入点写的是**同一个事实**（这笔钱收到没有），而且只有两种终态：收了 / 挂着。"
        "送达那一路由调用方 `complete_delivery` 的 CAS（ACCEPTED→DELIVERED）把住，"
        "`pay_order` 与 `charge_order` 各自走 `_payment_scoped_order` + `_reject_if_already_collected`；"
        "并发点相反的两个按钮时终态必是二者之一（不会有半截），且**都不写金额**"
        "（收款单与现金流水在 `create_receipt` 那条路上）—— 所以这里不存在'两个数'。"
    ),
    "payment_method": (
        "与 `paid` 同一次赋值、同一组终态（`cash` / `arrears`），没有第三个写入点能只改其中一个："
        "三个函数都是把 `paid` 与 `payment_method` 一起写的（第 7 轮把送达那一路也统一了）。"
    ),
    "arrears_unit_id": (
        "第 7 轮刚统一过：**收到钱就清掉、挂账就设上**（`_apply_complete_payment` / `pay_order` / "
        "`charge_order` 三处同源）。它不是「钱收没收到」的判据（那看 `paid`），而是「这笔账归哪个单位」"
        "的指向，所以只要与 `paid` 一致就不会分叉 —— 而这一致性有**库级不变式**兜着："
        "`_fuzz_invariants.py` 的「已收款却还指着挂账单位 = 0 行」。"
    ),
    "arrears_unit_name": (
        "与 `arrears_unit_id` 同一组：名字是**下单那一刻的快照**（报表按名字分组，不 join 名册），"
        "三处写入点都与 id 一起写、一起清（同上一条）。"
    ),
    # ---- 异常标记那一组：标记 / 解除 ----
    "is_exception": (
        "标记与解除是**同一个标记的两个方向**，两处都走 `ORDER_EXCEPTION` 审计，"
        "并发时终态是「标着」或「解除了」之一。这一组字段（含下面三条）在两侧都是**成组维护**的："
        "重新登记异常时会把上一次的解决说明与解决时间一起清掉（2026-09-19 审计修过），"
        "所以不会出现「标着异常、却带着旧的解决时间」那种半截状态"
        "（那会让异常单永远不出现在待处理里）。"
    ),
    "exception_reason": (
        "与 `is_exception` 同一次写入：标记时写原因、解除时保留原因为「异常订单」，见上一条。"
    ),
    "exception_resolution": (
        "解除那一路用 `note or 原值`（**只在给了说明时覆盖**），标记那一路把它清空 —— "
        "两条路径都保证「有说明 ⟺ 已解除」，见 `is_exception` 那条。"
    ),
    "exception_resolved_at": (
        "只在「解除」那条路径写时间、在「重新标记」时清空（`patch_order_exception` 里那一句），"
        "两处合起来保证「非空 ⟺ 这条异常已经解决」。"
    ),
    # ---- 软删 ----
    "deleted_at": (
        "订单的隔离状态**只有这一列**（没有独立的 `is_deleted`）：软删写时间戳、恢复写 NULL，"
        "两个动作互逆、终态只有两种；恢复那道门还要求 `deleted_at is not None`（不在隔离区就 404）。"
        "所以并发时后写者胜也只会得到「删了」或「恢复了」之一，不存在半截标记 —— 无需取锁。"
    ),
}

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
    gate_sites: list[tuple[str, str]] = []
    for f in py_files():
        src = read(f)
        for name, body in functions(src):
            code = code_only(body)
            if "lock_order_row(" in code:
                lock_sites.append((f.name, name, code))
            if "_order_allows_line_edit(" in code and "def _order_allows_line_edit" not in code:
                gate_sites.append((f.name, name))

    print(f"扫到 .py {len(py_files())} 个；锁调用点 {len(lock_sites)} 处、明细状态门 {len(gate_sites)} 处")

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

    print("\n== C. 同一个字段有多个写入点时，这个字段必须有交代（取锁 / 或者书面理由）==")
    # 「会取锁的函数」= 自己调了 `lock_order_row` 的那些；调用它们**也算**取到了锁
    # （例：`assign_order` 把运费交给 `assign_driver`，而后者先锁行再判 + 条件 UPDATE 占位）。
    lockers = {name for _, name, _ in lock_sites}
    # 盘点：`orders.<字段> =`（已剥注释、`=(?!=)` 排除 `==`），**按 (字段, 文件, 函数) 去重**。
    # ⚠️ 这一条是从**两次实测缺陷**里长出来的（第 6 轮 `freight_fee`：两个端点两套状态规则 →
    #    送达后还能定价，账单 300 而结算页 350；第 7 轮 `arrears_unit_id`：三个写入点只有
    #    `pay_order` 清指向 → "先挂账 + 按现金送达"落成 paid=True 却指着挂账单位 →
    #    `delete_unit` 永远删不掉那个单位）。两次都是"同一个字段、不同的人各写各的"。
    #
    # 判据刻意**不**要求"多写入点必须取锁"：那会把一堆本来就该幂等/同事务的写入点打红，
    # 而永远红的检查等于没有检查。要求的是**这个字段有交代**：
    #   (a) 每个写入点自己取锁 / 条件是「有 CAS 占位」/ 或者把活交给会取锁的函数；**或**
    #   (b) 在下面 `SAME_FIELD_REASONS` 里按**字段**写一句"为什么这些写入点不会分叉"。
    # 没有 (a) 也没有 (b) → 报红（并且理由表要防化石）。
    field_writers: dict[str, list[tuple[str, str, str]]] = {}
    for f in py_files():
        for name, body in functions(read(f)):
            code = code_only(body)
            if not re.search(r"\border\.[a-z_]+\s*=(?!=)", code):
                continue
            for m in re.finditer(r"\border\.([a-z_]+)\s*=(?!=)", code):
                sites = field_writers.setdefault(m.group(1), [])
                if not any(fn == f.name and nm == name for fn, nm, _ in sites):
                    sites.append((f.name, name, code))
    multi = {k: v for k, v in sorted(field_writers.items()) if len(v) >= 2}
    print(f"  盘出 orders 上 {len(field_writers)} 个字段有赋值点，其中**多写入点** {len(multi)} 个：")
    for field, sites in multi.items():
        tag = "（已交代）" if field in SAME_FIELD_REASONS else ""
        print(f"    · orders.{field}{tag}：{'、'.join(f'{fn}::{nm}' for fn, nm, _ in sites)}")
    c.ok(f"多写入点字段不少于 {MIN_MULTI_FIELDS} 个（少说明盘点失效）",
         len(multi) >= MIN_MULTI_FIELDS, f"实际 {len(multi)} 个")
    for field, sites in multi.items():
        reason = SAME_FIELD_REASONS.get(field)
        if reason:
            c.ok(f"orders.{field} 有交代：{reason[:34]}…", len(reason) >= 20,
                 "理由太短，等于没写（要能回答『这些写入点为什么不会分叉』）")
            continue
        for fn, nm, body in sites:
            delegates = sorted(n for n in lockers if n != nm and re.search(rf"\b{n}\s*\(", body))
            has_cas = bool(re.search(r"db\.execute\(\s*update\(", body))
            c.ok(
                f"orders.{field} ← {fn}::{nm} 取锁 / 有 CAS / 或在理由表里",
                "lock_order_row(" in body or has_cas or bool(delegates),
                f"这个写入点既没取锁、也没有条件 UPDATE 占位（也没交给会取锁的 {delegates or '—'}），"
                f"字段 `{field}` 又没在 `SAME_FIELD_REASONS` 里写理由 —— 同一个字段的多个写入点"
                f"不同源时，口径宽的那一个就是漏洞（第 6·7 轮各栽过一次）",
            )

    print("\n== D. 允许表不许有化石（写过的理由必须还对应一个真实位置）==")
    # ⚠️ 理由表最容易变成"看起来处理过了、其实那条早就不存在了"（本项目在覆盖率那张
    #    EXCLUDED 表上栽过）。所以每次都要回头问一句：这条理由指的位置还在吗？
    seen_line = set(gate_sites)
    fossils_line = sorted(k for k in ALLOW_LINE_GATE if k not in seen_line)
    c.ok("明细状态门的允许表没有化石", not fossils_line, f"已经不存在：{fossils_line}")
    fossils_same = sorted(k for k in SAME_FIELD_REASONS if k not in multi)
    c.ok("同源理由表没有化石（那个字段已经不是多写入点了）", not fossils_same,
         f"已经不存在：{fossils_same}")

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
