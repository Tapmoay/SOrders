"""反向验证 §24（报表口径必须闭合：营业额 = 已收 + 挂账）。

## 为什么这一节必须配反向验证
报表的错法是"**每一列都看起来正常，但加起来不等于总数**"：

- 又写成两条带条件的判据（`cash 且已收` / `arrears 且未收`）→ **挂账结清**（arrears + paid=True）
  两边都不算：营业额 200、已收 100、挂账 0，差出来的 100 在报表上哪一列都不属于；
- 报表自己拿 `line_total` 求和当营业额 → **退货红冲整个漏掉**（退了货还照记收入）；
- 「已收」的含义只在代码里改、出参注释还写着"现金已收" → 下一个人按注释理解又会写错；
- 端到端那条闭合性断言被删掉 → 这类错误再也没有东西拦得住。

⚠️ 2026-09-20：三个数（应收/净已收/欠款）改由 `services/order_money.py` 一处算，
   所以这几条注入也换成了"**把那一处的口径绕开**"的形状 —— 绕开它的每一种写法都必须报红。

用法：`python _tools/qa/_reverse_verify_report_guards.py`
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
#: ⚠️ 2026-09-25 第 21 轮：报表聚合下沉到 service 层，这一族的三条注入（营业额 / 已收 / 挂账的算法）
#: 现在住在 `services/reports_service.py`。注入要打在原文真正住着的文件上，否则静默 SKIP。
REPORTS = ROOT / "backend/app/services/reports_service.py"
REPORT_SCHEMA = ROOT / "backend/app/schemas/reports.py"
RECON_TESTS = ROOT / "backend/tests/test_report_reconciliation.py"

PARTITION = "        collected += mm.settled - mm.refunded\n"

CASES: list[tuple[str, Path, object]] = [
    (
        "又写成两条带条件的判据（挂账结清 / 部分核销的钱两边都不算 → 报表上凭空消失）",
        REPORTS,
        lambda s: s.replace(
            PARTITION,
            "        if o.paid:\n"
            "            collected += amount\n"
            "        else:\n"
            "            arrears_total += amount\n",
            1,
        ),
    ),
    (
        "「已收」不再往上加（只减挂账不加已收 = 钱消失）",
        REPORTS,
        lambda s: s.replace(PARTITION, "        pass\n", 1),
    ),
    (
        "报表里自己把订单行加起来当营业额（退货红冲整个漏掉）",
        REPORTS,
        lambda s: s.replace(
            "        amount = mm.receivable",
            "        amount = sum((lp.line_total or Decimal(\"0\")) for lp in o.order_products)",
            1,
        ),
    ),
    (
        "出参注释退回「现金已收」（下一个人按注释理解又会写错）",
        REPORT_SCHEMA,
        lambda s: s.replace("paid=True 即算，含挂账结清", "现金已收", 1),
    ),
    (
        "闭合性那条端到端断言被删掉（这类错误再也没人拦）",
        RECON_TESTS,
        lambda s: s.replace("def test_挂账结清之后钱要从挂账挪到已收_不能凭空消失(", "def _removed_("),
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(AI_TOOLS / "_check_ai_guardrails.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section_24(out: str) -> str:
    """只取 §24 那一段（段内失败标记是 `[FAIL]`，不是汇总里的 `❌`）。"""
    if "== 24." not in out:
        return ""
    rest = out.split("== 24.", 1)[1]
    return rest.split("\n" + "=" * 60, 1)[0]


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时检查就没过\n{out[-1200:]}")
        return 1
    if not section_24(out):
        print("❌ 前提不成立：输出里找不到 §24 这一段")
        return 1
    print("✅ 前提：源码完好时检查是绿的，且 §24 存在")

    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        # 第二轮 R2-05：报表源码搬进了 `services/reports/` —— 目标路径可能已经过期。
        # 判据读的是**并集**，注入器也照着并集找：哪一份真的被 mutate 改了，就打在哪一份上。
        # ⛔ 不逐条改 CASES 里的路径常量：那几条锚点跨多个新文件，改常量改不干净。
        if mutate(original) == original:
            import sys as _sys
            from pathlib import Path as _P
            _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "ai"))
            from _airepo import reports_files as _rf
            for _c in _rf():
                _t = _c.read_text(encoding="utf-8")
                if mutate(_t) != _t:
                    path, original = _c, _t
                    break
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        # R3-07b：还原**当场核对**（不是「看起来还原了」）—— 对不上就记账，别让坏代码留在树里
        if path.read_text(encoding="utf-8") != original:
            fails.append("还原后与快照不一致（注入污染了源码树）：" + str(path))
        got = section_24(out)
        if code == 0 or "[FAIL]" not in got:
            fails.append(f"{label}：注入后 §24 没有报红（code={code}）——判据是空转的")
        else:
            print(f"✅ 注入「{label}」→ §24 报红")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §24 的 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
