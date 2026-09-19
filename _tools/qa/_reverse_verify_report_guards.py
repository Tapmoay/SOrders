"""反向验证 §24（报表口径必须闭合：营业额 = 已收 + 挂账）。

## 为什么这一节必须配反向验证
报表的错法是"**每一列都看起来正常，但加起来不等于总数**"：

- 又写成两条带条件的判据（`cash 且已收` / `arrears 且未收`）→ **挂账结清**（arrears + paid=True）
  两边都不算：营业额 200、已收 100、挂账 0，差出来的 100 在报表上哪一列都不属于；
- 「已收」的含义只在代码里改、出参注释还写着"现金已收" → 下一个人按注释理解又会写错；
- 端到端那条闭合性断言被删掉 → 这类错误再也没有东西拦得住。

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
REPORTS = ROOT / "backend/app/api/v1/reports.py"
REPORT_SCHEMA = ROOT / "backend/app/schemas/reports.py"
RECON_TESTS = ROOT / "backend/tests/test_report_reconciliation.py"

PARTITION = (
    "        if o.paid:\n"
    "            collected += amount\n"
    "        else:\n"
    "            arrears_total += amount\n"
)

CASES: list[tuple[str, Path, object]] = [
    (
        "又写成两条带条件的判据（挂账结清的钱两边都不算 → 报表上凭空消失）",
        REPORTS,
        lambda s: s.replace(
            PARTITION,
            "        if (o.payment_method or \"\") == \"cash\" and o.paid:\n"
            "            collected += amount\n"
            "        elif (o.payment_method or \"\") == \"arrears\" and not o.paid:\n"
            "            arrears_total += amount\n",
            1,
        ),
    ),
    (
        "「已收」不再往上加（只减挂账不加已收 = 钱消失）",
        REPORTS,
        lambda s: s.replace(
            PARTITION,
            "        if o.paid:\n"
            "            pass\n"
            "        else:\n"
            "            arrears_total += amount\n",
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
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
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
