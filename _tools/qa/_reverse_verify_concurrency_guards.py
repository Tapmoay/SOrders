"""反向验证 §25（并发保护：状态跃迁与核销都先锁行）。

## 为什么这一节必须配反向验证
这一节守的缝隙**在本机（SQLite）根本复现不了**——SQLite 写是串行的，
所以"少一行锁"不会让任何测试变红。真出问题是在生产（MySQL + 多 worker）：

- 并发派单：两个请求都读到「待派单」→ 各自往下走 → **同一张单派给两个司机**；
- 并发送达：两个请求都读到「已接单」→ **同一张单生成两条司机账单**（司机拿两份钱）；
- 并发核销：两个请求都读到 `paid=False` → **同一张单两条收款记录**。

所以这一节只能靠"结构判据 + 反向注入"来证明它真的在检查。用法：
`python _tools/qa/_reverse_verify_concurrency_guards.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

AI_TOOLS = Path(__file__).resolve().parent.parent / "ai"
ROOT = repo_root()
FLOW = ROOT / "backend/app/services/order_flow.py"
ACCT = ROOT / "backend/app/services/accounting_service.py"
PROBE = ROOT / "_tools/qa/_probe_core_flows.py"
CONC_TEST = ROOT / "backend/tests/test_concurrent_delivery_money.py"

ASSIGN_GUARD = "    order = lock_order_row(db, order)\n    if order.status != OrderStatus.PENDING_DISPATCH:"
#: ⚠️ 锚点不许跨"后来插进来说明/守卫"的行（2026-09-19 第十四轮修）：
#:    `complete_delivery` 里锁行与状态判断之间现在隔了 10 行 `deleted_at` 守卫 + 说明，
#:    原来那个两行锚点因此**匹配不上**，脚本报"替换串过期"——
#:    也就是说那条注入已经很久没生效过（判据是不是活的，谁也不知道）。
#:    现在只锚**那一行判断本身**（它在整个文件里唯一），注入的语义不变。
COMPLETE_GUARD = "    if order.status != OrderStatus.ACCEPTED:\n        raise ValueError(\"仅「已接单」订单可完成配送\")"
#: 锁行那一行在两处出现（派单 / 送达），用**它上面那句注释**保证唯一
COMPLETE_LOCK = (
    "    # 各自往下走 → **同一张单生成两条司机账单**（钱）。\n"
    "    order = lock_order_row(db, order)\n"
)
#: v3.40 起状态跃迁多了一道"条件 UPDATE 占位"（SQLite 不认行锁，本地实测能生成两条账单）
#: ⚠️ 同样不许跨行锚：`.where(...)` 里后来加了 `Order.deleted_at.is_(None)`（R13-D1），
#:    所以锚点只取"这个 CAS 从哪开始"。两处的起点不同（status 条件不同），各自唯一。
ASSIGN_CAS = (
    "    claimed = db.execute(\n"
    "        update(Order)\n"
    "        .where(\n"
    "            Order.id == order.id,\n"
    "            Order.status == OrderStatus.PENDING_DISPATCH,\n"
)
COMPLETE_CAS = (
    "    claimed = db.execute(\n"
    "        update(Order)\n"
    "        .where(\n"
    "            Order.id == order.id,\n"
    "            Order.status == OrderStatus.ACCEPTED,\n"
)
CAS_FAIL = (
    "    if claimed.rowcount != 1:\n"
    "        db.rollback()"
)

CASES: list[tuple[str, Path, object]] = [
    (
        "派单前不锁行（并发派单会把同一张单派给两个司机）",
        FLOW,
        lambda s: s.replace(ASSIGN_GUARD, "    if order.status != OrderStatus.PENDING_DISPATCH:", 1),
    ),
    (
        "送达前不锁行（并发送达会生成两条司机账单 = 司机拿两份钱）",
        FLOW,
        lambda s: s.replace(
            COMPLETE_LOCK, "    order = db.get(Order, order.id)\n", 1
        ),
    ),
    (
        "锁了但不刷新值（等的锁白等：判据用的还是事务开始时那份旧状态）",
        FLOW,
        lambda s: s.replace("        db.refresh(order, with_for_update=True)",
                            "        db.refresh(order)", 1),
    ),
    (
        "派单少了条件 UPDATE 占位（本地 SQLite 上两个请求都能往下走 → 同一张单派给两个人）",
        FLOW,
        lambda s: s.replace(ASSIGN_CAS, "    claimed = None", 1),
    ),
    (
        "送达少了条件 UPDATE 占位（实测：同一张单生成两条 60 元账单）",
        FLOW,
        lambda s: s.replace(COMPLETE_CAS, "    claimed = None", 1),
    ),
    (
        "占位失败却不回滚就往下走（rowcount=0 也当成功）",
        FLOW,
        # ⚠️ 必须替换**所有**出现（派单与送达各一处）：只换一处的注入证明不了判据是活的
        #    ——反向验证第一版就是 count=1，结果 §25 仍绿（另一处还在），差点把空转当通过。
        lambda s: s.replace(CAS_FAIL, "    if False:\n        db.rollback()"),
    ),
    (
        "锁行取不到时直接抛（并发重复提交又变成 500）",
        FLOW,
        lambda s: s.replace(
            "    except SaInvalidRequest:\n"
            "        fresh = db.scalars(\n"
            "            select(Order).where(Order.id == order.id).with_for_update()\n"
            "        ).first()",
            "    except Exception:\n"
            "        raise\n"
            "        fresh = None  # noqa",
            1,
        ),
    ),
    (
        "逐单核销不锁订单行（两个请求都读到 paid=False → 两条收款记录）",
        ACCT,
        lambda s: s.replace(
            "select(Order)\n"
            "                .options(selectinload(Order.order_products))\n"
            "                .where(Order.id.in_(order_ids))\n"
            "                .with_for_update()",
            "select(Order)\n"
            "                .options(selectinload(Order.order_products))\n"
            "                .where(Order.id.in_(order_ids))",
            1,
        ),
    ),
    (
        "探针里的「并发」那一组被删掉（这类缝隙再也没人盯）",
        PROBE,
        lambda s: s.replace('    "并发": probe_concurrency,\n', "", 1),
    ),
    (
        "并发送达的回归测试被删掉（钱付两次又没人钉了）",
        CONC_TEST,
        lambda s: s.replace("def test_double_complete_sequential_creates_one_bill(",
                            "def _disabled_double_complete(", 1),
    ),
    (
        "条件 UPDATE 占位的机制测试被删掉（「本机数据库上原子」这条没人证明）",
        CONC_TEST,
        lambda s: s.replace("def test_conditional_claim_is_atomic_on_this_db(",
                            "def _disabled_claim(", 1),
    ),
    # ---- v3.41：逐单核销的同一道闸（本机实测复现过「两条收款记录」）----
    (
        "逐单核销少了 paid 的条件 UPDATE 占位（并发下同一张单两条收款记录 = 钱多记一笔）",
        ACCT,
        # 把 `WHERE paid=false` 这个**占位的判据本身**反转掉。
        # ⚠️ 别用"删掉条件"的写法：这段 CAS 现在有**两处**（逐单核销 / 滚动收款绑单），
        #    只替换一处时另一处仍在，红线照样能命中 → 这条注入就变成了假绿
        #    （2026-09-19 实测：正是这么失败的）。语义反转两处都会变，绕不过去。
        lambda s: s.replace("Order.paid.is_(False)", "Order.paid.is_(True)"),
    ),
    (
        "逐单核销占位抢不到也往下走（rowcount 不检查＝没占位）",
        ACCT,
        lambda s: s.replace("        if claimed.rowcount != len(order_ids):", "        if False:"),
    ),
    (
        "逐单核销占位的原子性测试被删掉",
        CONC_TEST,
        lambda s: s.replace("def test_paid_claim_is_atomic_on_this_db(",
                            "def _disabled_paid_claim(", 1),
    ),
    (
        "串行重复核销的回归测试被删掉",
        CONC_TEST,
        lambda s: s.replace("def test_double_itemized_receipt_sequential_records_money_once(",
                            "def _disabled_double_receipt(", 1),
    ),
    (
        "探针不再核对账单唯一索引（唯一约束又变成没人验的声明）",
        PROBE,
        lambda s: s.replace('"uq_driver_bills_order_type" in names', "True", 1),
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(AI_TOOLS / "_check_ai_guardrails.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section_25(out: str) -> str:
    """只取 §25 那一段（段内失败标记是 `[FAIL]`，不是汇总里的 `❌`）。"""
    if "== 25." not in out:
        return ""
    rest = out.split("== 25.", 1)[1]
    return rest.split("\n" + "=" * 60, 1)[0]


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时检查就没过\n{out[-1200:]}")
        return 1
    if not section_25(out):
        print("❌ 前提不成立：输出里找不到 §25 这一段")
        return 1
    print("✅ 前提：源码完好时检查是绿的，且 §25 存在")

    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        got = section_25(out)
        if code == 0 or "[FAIL]" not in got:
            fails.append(f"{label}：注入后 §25 没有报红（code={code}）——判据是空转的")
        else:
            print(f"✅ 注入「{label}」→ §25 报红")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §25 的 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
