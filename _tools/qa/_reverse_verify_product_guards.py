"""反向验证 §23（商品与订单行的金额/引用完整性）。

## 为什么这一节必须配反向验证
这一节守的四件事**坏掉时全是"接口 200、界面正常"**：

- 行金额又变回"客户端给了就用客户端的" → 账本、营业额、毛利按行金额入账，
  而"单价×数量"是另一个数：两张表各说各的，谁也不知道该信哪个；
- 一致性核对形同虚设（容差放到 1 元、或者干脆不抛）→ 上面那条的另一种写法；
- 商品编号不再校验 → 成本快照按 0 记（**毛利虚高且看起来完全正常**）、送达时不扣库存；
- 商品价格/成本又能填负数 → 下单得到负金额订单行，账本入账负数。

所以每条都注入一次，证明检查真的会红。

用法：`python _tools/qa/_reverse_verify_product_guards.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

HERE = Path(__file__).resolve().parent
AI_TOOLS = HERE.parent / "ai"
ROOT = repo_root()
FLOW = ROOT / "backend/app/services/order_flow.py"
LINES = ROOT / "backend/app/api/v1/order_products.py"
PROD_SCHEMA = ROOT / "backend/app/schemas/product.py"
ORDERS_API = ROOT / "backend/app/api/v1/orders.py"
#: 下单的商品护栏（create_order 里那一段）2026-09-24 阶段 4 搬去了 orders_lifecycle.py。
ORDERS_L = ROOT / "backend/app/api/v1/orders_lifecycle.py"
ACCT = ROOT / "backend/app/services/accounting_service.py"

CASES: list[tuple[str, Path, object]] = [
    (
        "行金额又变成「客户端给了就用客户端的」（账本与单价×数量从此分叉）",
        FLOW,
        lambda s: s.replace(
            "    if abs(g - computed) > LINE_TOTAL_TOLERANCE:",
            "    if False:",
            1,
        ),
    ),
    (
        "容差放到 1 元（等于没核对：差 9 毛也算对）",
        FLOW,
        lambda s: s.replace('LINE_TOTAL_TOLERANCE = Decimal("0.01")', 'LINE_TOTAL_TOLERANCE = Decimal("1.00")', 1),
    ),
    (
        "先收单价再乘（把 3.3333×3 算成 9.99，与客户端的 10.00 天天打架）",
        FLOW,
        lambda s: s.replace(
            "    computed = money(Decimal(str(unit_price)) * qty)",
            "    computed = money(up * qty)",
            1,
        ),
    ),
    (
        "已删除的商品又能下单（成本快照按 0 记 → 毛利虚高）",
        FLOW,
        lambda s: s.replace("            if prod.is_deleted:", "            if False:", 1),
    ),
    (
        "商品编号不存在也照收（送达时不扣库存，静默）",
        FLOW,
        lambda s: s.replace(
            "            if prod is None:",
            "            if False:",
            1,
        ),
    ),
    (
        "加行时不再核对行金额（同一份判据被绕开一条路）",
        LINES,
        lambda s: s.replace(
            "        lt = resolve_line_total(body.unit_price, body.quantity, body.line_total)",
            "        lt = body.line_total if body.line_total else body.unit_price * body.quantity",
            1,
        ),
    ),
    (
        "改行时不再重算金额（改数量后金额还是旧的）",
        LINES,
        lambda s: s.replace(
            "            op.line_total = resolve_line_total(new_up, new_qty, body.line_total)",
            "            op.line_total = body.line_total if body.line_total is not None else op.line_total",
            1,
        ),
    ),
    (
        "商品编号校验删掉（不存在/已删除都放行）",
        LINES,
        lambda s: s.replace(
            '        detail=f"商品编号 {product_id} 不在商品库里。请重新选一个商品，或改成不填编号的手输商品行。",',
            '        detail="x",',
            1,
        ),
    ),
    (
        "商品单价又能填负数（下单算出负金额订单行）",
        PROD_SCHEMA,
        lambda s: s.replace(
            'default_unit_price: Decimal = Field(default=Decimal("0"), ge=0)',
            'default_unit_price: Decimal = Field(default=Decimal("0"))',
            1,
        ),
    ),
    (
        "商品名又能是纯空格（列表里一行空白）",
        PROD_SCHEMA,
        lambda s: s.replace(
            '            raise ValueError("商品名不能为空或纯空格")',
            "            pass",
            1,
        ),
    ),
    (
        "同一张单又能被逐单核销两次（账上多出一笔没收到的钱）",
        ACCT,
        lambda s: s.replace(
            # ⚠️ 锚点 2026-09-21 更新：那处守卫后来长成 `if o.paid or m.arrears <= 0:`
            #    （多了一条"欠款为 0 也不许再收"）。**只摘掉 `o.paid` 那一半**才是这条注入的
            #    原意（同一张单被核销两次）——整句换成 `if False` 会把两条判据一起放开，
            #    那验的就不是这一条了。
            "if o.paid or m.arrears <= 0:",
            "if m.arrears <= 0:",
            1,
        ),
    ),
    (
        "拒绝时不再说「补差额改用滚动收款」（用户只知道失败了，不知道下一步怎么做）",
        ACCT,
        lambda s: s.replace(
            '                    "如果是补差额，请改用「滚动收款」。"',
            '                    ""',
            1,
        ),
    ),
    (
        "下单被拒时改回 500（用户/AI 看到的是「服务器错误」而不是「第 2 行对不上」）",
        ORDERS_L,   # 2026-09-24 阶段 4：create_order 搬去了 orders_lifecycle.py
        lambda s: s.replace(
            "    except ValueError as e:\n"
            "        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e\n"
            "    od = ensure_order_date(body.order_date)",
            "    od = ensure_order_date(body.order_date)",
            1,
        ),
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(AI_TOOLS / "_check_ai_guardrails.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section_23(out: str) -> str:
    """只取 §23 那一段（段内失败标记是 `[FAIL]`，不是汇总里的 `❌`）。"""
    if "== 23." not in out:
        return ""
    rest = out.split("== 23.", 1)[1]
    return rest.split("\n" + "=" * 60, 1)[0]


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时检查就没过\n{out[-1200:]}")
        return 1
    if not section_23(out):
        print("❌ 前提不成立：输出里找不到 §23 这一段")
        return 1
    print("✅ 前提：源码完好时检查是绿的，且 §23 存在")

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
        got = section_23(out)
        if code == 0 or "[FAIL]" not in got:
            fails.append(f"{label}：注入后 §23 没有报红（code={code}）——判据是空转的")
        else:
            print(f"✅ 注入「{label}」→ §23 报红")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §23 的 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
