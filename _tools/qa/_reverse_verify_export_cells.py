"""反向验证 `backend/tests/test_export_cells_match_api.py`（导出 xlsx 逐格 == 接口 JSON）。

## 为什么这条判据也要做反向验证

它守的是"导出给外部看的那份凭证"，而**坏起来的每一种方式都不会让任何接口报错**：
标签顺序写反、毛利两侧不是同一批行、文件名按锚点日、算不出成本的行印成 0、金额写成文本、
商品行少一列（后面所有列跟着错位）…… 这些改法都能编译、都能跑、导出的表看着也"像那么回事"。

判据是 pytest 用例（不是静态脚本），所以这里注入真缺陷后跑**那个用例文件**，
要求它必须失败 —— 证明它不是空转。跑完逐字节还原，并再验一次绿。

⚠️ 只接受"**跑出来有 failed**"当通过：如果注入把用例弄成**收集期错误**（import 挂了），
那证明不了判据在看东西，所以那种情况算没通过。

用法：python _tools/qa/_reverse_verify_export_cells.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
TEST_REL = "tests/test_export_cells_match_api.py"
REPORTS = BACKEND / "app/api/v1/reports.py"

CASES: list[tuple[str, Path, object]] = [
    (
        "营业纵览第 3 行两个标签写反（「金额」那一列其实是运费 —— 数看着都合理）",
        REPORTS,
        lambda s: s.replace(
            '            "司机运费支出(按计费规则应付)", _money(data["total_freight"]),\n'
            '            "商品毛利(仅算得出成本的行)",',
            '            "商品毛利(仅算得出成本的行)", _money(data["total_freight"]),\n'
            '            "司机运费支出(按计费规则应付)",',
            1,
        ),
    ),
    (
        "毛利两侧不是同一批行（用总营业额减成本 —— 2026-09-19 第十七轮那个虚高口径）",
        REPORTS,
        lambda s: s.replace(
            '_money(data["cost_covered_amount"] - data["cost_total"]),\n            _cost_basis_note(data),',
            '_money(data["total_amount"] - data["cost_total"]),\n            _cost_basis_note(data),',
            1,
        ),
    ),
    (
        "文件名按**锚点日**命名（内容整月、名字一天 —— 拿文件名找回来的凭证对不上）",
        REPORTS,
        lambda s: s.replace(
            'range_label = f"{s}_{e}" if s != e else str(s)',
            'range_label = str(d)',
            1,
        ),
    ),
    (
        "算不出成本的行印成数字（那一格看着像「没成本、毛利全额」）",
        REPORTS,
        lambda s: s.replace(
            'gross = _money(cov - it.cost) if (it.covered_lines or 0) > 0 else "—"',
            "gross = _money(cov - it.cost)",
            1,
        ),
    ),
    (
        "金额列写成文本（用户在 Excel 里 SUM 得 0）",
        REPORTS,
        lambda s: s.replace(
            'ws.append([it.product_name, it.qty, it.order_count, _money(it.amount),',
            'ws.append([it.product_name, it.qty, it.order_count, str(it.amount),',
            1,
        ),
    ),
    (
        "商品行少写最后一格（货损金额没了，列也整体错位）",
        REPORTS,
        lambda s: s.replace(
            "gross, it.damage_qty, _money(it.damage_amount)])",
            "gross, it.damage_qty])",
            1,
        ),
    ),
    (
        "营业纵览的曲线只写第一行（区间报表少一大截，行数对不上）",
        REPORTS,
        lambda s: s.replace('for pt in data["series"]:', 'for pt in data["series"][:1]:', 1),
    ),
]


def run_test() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_REL, "-q", "--no-header", "-p", "no:cacheprovider"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(BACKEND),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    before = {str(p): p.read_text(encoding="utf-8") for _, p, _ in CASES}

    code, out = run_test()
    if code != 0 or not re.search(r"\d+ passed", out):
        print("❌ 前提不成立：源码完好时这条判据就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时判据是绿的（2 passed）")

    fails: list[str] = []
    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_test()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        if re.search(r"\d+ failed", out):
            print(f"✅ 注入「{label}」→ 用例失败（判据抓到了）")
        elif code != 0:
            fails.append(f"{label}：用例没跑起来（收集期错误不算抓到）\n{out[-600:]}")
            print(f"❌ 注入「{label}」→ 用例根本没跑起来（不算通过）")
        else:
            fails.append(f"{label}：注入之后用例**照样全绿** —— 这条判据是空转的")
            print(f"❌ 注入「{label}」→ 用例还是绿的")

    for k, v in before.items():
        if Path(k).read_text(encoding="utf-8") != v:
            fails.append(f"收尾没还原：{k}")
    code, out = run_test()
    if code != 0:
        fails.append("还原之后判据仍然红（有文件没被改回来）")

    if fails:
        print("\n❌ 反向验证没通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(CASES)}/{len(CASES)} 种破坏方式全部被用例抓到，且源码已还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
