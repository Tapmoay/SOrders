# -*- coding: utf-8 -*-
"""反向验证：把「钱路 provenance」那条判据逐条弄坏，看它**真的会红**。

为什么必须反向验证（本项目的规矩）：判据最容易的坏法不是"报错"，而是**悄悄什么都不看** ——
比如分类表写成手写的、模型换了名字它也照样绿；或者"化石棘轮"那条被删掉之后，
缺口补上了没人知道、没补也没人知道。所以这里逐条制造**具体的破坏**。

⭐ 第 4 组（契约版本）与第 6 条注入是**棘轮**的证明：把事实记录**补上**也必须报红 ——
因为补上之后文档里那句"三处都没有"就不成立了。棘轮的意义正是"不许安静地过期"。

用法：python _tools/qa/_reverse_verify_pricing_provenance.py   # 全部成立 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_pricing_provenance.py"

ORDER_MODEL = ROOT / "backend/app/models/order.py"
BILL_MODEL = ROOT / "backend/app/models/driver_bill.py"
LEDGER_MODEL = ROOT / "backend/app/models/ledger.py"
DRIVER_PAY = ROOT / "backend/app/services/driver_pay.py"

ANCHOR_RULE_SNAP = '    driver_rule_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)\n'
ANCHOR_BILL_RULE_ID = '    rule_id: Mapped[int | None] = mapped_column(nullable=True, index=True)\n'
ANCHOR_LEDGER_COST = '    cost_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))\n'
ANCHOR_FROM_SNAP = '    return PayRule(\n        rule_id=d.get("rule_id"),'
ANCHOR_ORDER_PAY_SIG = "    category_id=None,\n) -> OrderPay:"


class Sandbox:
    """按字节记住原样，最后一次性还原（⛔ 不用 git checkout --：那会抹掉未提交的真实改动）。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def _keep(self, p: Path) -> None:
        if p not in self.saved:
            self.saved[p] = p.read_bytes()

    def replace(self, p: Path, old: str, new: str) -> None:
        self._keep(p)
        text = p.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"{p.name}: 原文出现 {text.count(old)} 次，无法唯一替换"
        p.write_bytes(text.replace(old, new).encode("utf-8"))

    def add_column(self, p: Path, anchor: str, line: str) -> None:
        self.replace(p, anchor, anchor + line)

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)
            if p.read_bytes() != raw:
                print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        self.saved.clear()


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ---------------------------------------------------------------- 注入场景

def s_order_template_id(sb: Sandbox) -> None:
    """给订单加一列"这条承运价出自哪条价目" —— 缺口被补上了，棘轮必须响。"""
    sb.add_column(ORDER_MODEL, ANCHOR_RULE_SNAP,
                  "    freight_template_id: Mapped[int | None] = mapped_column(nullable=True)\n")


def s_order_pricing_kind(sb: Sandbox) -> None:
    """给订单加一列记录计价契约版本 —— 第 4 组那句"三处都没有"不再成立。"""
    sb.add_column(ORDER_MODEL, ANCHOR_RULE_SNAP,
                  '    pricing_kind: Mapped[str | None] = mapped_column(String(16), nullable=True)\n')


def s_drop_bill_rule_id(sb: Sandbox) -> None:
    """把账单上的 rule_id 拿掉 —— 账单再也无法独立复核"按什么算的"。"""
    sb.replace(BILL_MODEL, ANCHOR_BILL_RULE_ID, "")


def s_snapshot_read_unknown_key(sb: Sandbox) -> None:
    """让快照的**读**多读一个**写**不进去的键 —— 历史金额就重建不出来了（静默错）。"""
    sb.replace(DRIVER_PAY, ANCHOR_FROM_SNAP,
               '    _kind = d.get("pricing_kind")  # rv-injection\n' + ANCHOR_FROM_SNAP)


def s_order_pay_takes_user(sb: Sandbox) -> None:
    """让算钱那一步能拿到活用户 —— "按当时的规则算"这个承诺就没了。"""
    sb.replace(DRIVER_PAY, ANCHOR_ORDER_PAY_SIG,
               "    category_id=None,\n    user=None,  # rv-injection\n) -> OrderPay:")


def s_unclassified_money_column(sb: Sandbox) -> None:
    """给账本加一个没人归类的钱列 —— 第 1 组必须拦住（"给 AI 开一条后路"那条规矩）。"""
    sb.add_column(LEDGER_MODEL, ANCHOR_LEDGER_COST,
                  "    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal('0'))\n")


# (说明, 场景, 期望) ；期望 = ("red", 关键字) 或 ("green", "")
SCENARIOS = [
    ("给订单补上「这条承运价出自哪条价目」的列（棘轮必须响）",
     s_order_template_id, ("red", "orders 上仍然")),
    ("给订单加一列记录计价契约版本（第 4 组必须响）",
     s_order_pricing_kind, ("red", "没有任何**列**记录")),
    ("把账单上的 rule_id 拿掉（账单没法独立复核了）",
     s_drop_bill_rule_id, ("red", "rule_id / rule_name")),
    ("快照读一个写不进去的键（历史金额重建不出来）",
     s_snapshot_read_unknown_key, ("red", "快照写出的键")),
    ("算钱那一步改成能拿活用户（不再只认快照）",
     s_order_pay_takes_user, ("red", "收的是 PayRule")),
    ("加一个没人归类的钱列（未归类必须当场红）",
     s_unclassified_money_column, ("red", "未归类")),
]


def main() -> int:
    if not CHECK.exists():
        print(f"❌ 找不到 {CHECK}")
        return 1

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print(f"❌ 前提不成立：源码完好时这条判据没过\n{out[-1500:]}")
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print(f"✅ 前提：源码完好时判据是绿的 —— {last.strip()}")

        for label, setup, expect in SCENARIOS:
            sb.restore()
            setup(sb)
            try:
                code, out = run_check()
            finally:
                sb.restore()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            kind, keyword = expect
            if kind == "green":
                hit = code == 0
                detail = "通过（这正是要的）" if hit else "按格式写了以后仍报红"
            else:
                hit = code != 0 and any(keyword in ln for ln in fails)
                detail = (f"实际红 {len(fails)} 条"
                          + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}"))
            print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
            if not hit:
                bad += 1

        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后判据全绿" if ok else "  [MISS] 还原后判据没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    total = len(SCENARIOS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立：每一种破坏都被点出来了，还原后判据恢复")
    return 0


if __name__ == "__main__":
    sys.exit(main())
