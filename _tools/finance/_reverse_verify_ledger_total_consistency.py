"""反验：账本行的「合计」一致性判据（_check_ledger_total_consistency.py）真的在检查吗。

### 为什么要单独一个脚本

判据本身也会撒谎：锚点打成一句永远为真的话、正则写成匹配一切、或者文件读不到时安静地跳过 ——
这几种判据跑起来也是满屏 [OK]。验证它有没有用的唯一办法是**把修复逐条弄坏**，看它会不会红。
下面每一条都是"有人真心实意改回老样子 / 顺手放宽一点"的样子；哪一条注入后判据还全绿，
就说明那一条判据在空转。最后一行会把注入逐字节还原并读回来核对 ——
源码树不允许留下任何注入痕迹（其余判据/单测跟在这个进程后面跑）。

### 每一条都在破坏什么

1  400 降级成 500：金额对不上被说成服务器故障（客户端不会再提示"改数量/单价"）
2  加一个绕过校验的出口：对不上也照收 given_total（这颗 bug 的原始形状）
3  老算法抄回创建入口：同一行又能有两个答案（POST 那条路）
4  老算法抄回修改入口："显式给了 total 就照收"（这条 bug 被报出来的那一条路）
5  把重算搬出那三个数的闸：只改备注也会重算，历史脏行被"顺手治了"
6  订单来的行也收紧成必须相等：把订单侧的口径一起改了（订单行金额本来可含让价）
7  把已送达闸从"改一行"这条路上摘掉：已送达的单又能从账本侧改钱
8  闸的判据不再与订单侧同源：手写状态清单（第 17 轮漏掉 RETURNED 的那种老毛病）
9  400 文案里"收到的那个数"被删掉：用户看不出自己给的是多少，没法自己改对
10 把"记一整笔金额"的等价写法从文案里删掉：等于把能力悄悄消灭掉
11 把过期注释抄回 schema：口径又说成"要改得先拍板"（注释与行为分叉）
12 把这条用例改名/删掉：红灯不再有人守
13 变更单少一节（§⑨ 被改成别的章节名）
14 台账那一行的编号被改错（TB-10 找不到）
15 登记表把这一单登记了两次（判据要求恰好一行）
16 认领簿里这一单不见了（单号被写错）

用法：
    python -X utf8 _tools/finance/_reverse_verify_ledger_total_consistency.py
    全部达标时末尾打印：✅ 17/17 都红了：这条检查真的在检查。（退出码 0）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ledger_total_consistency.py"
LEDGER = ROOT / "backend/app/api/v1/ledger.py"
SCHEMA = ROOT / "backend/app/schemas/ledger.py"
TEST_FILE = ROOT / "backend/tests/test_ledger_total_consistency.py"
CHANGE = ROOT / "docs/changes/BUG-0025.md"
LEDGER_DOC = ROOT / "docs/TEST_BUG_LEDGER.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), (b"\r\n" in data)


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    out = text.replace("\n", "\r\n") if crlf else text
    data = out.encode("utf-8")
    p.write_bytes(data)
    return data


def restore_src(p: Path, text: str, crlf: bool) -> None:
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check() -> str:
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return r.stdout + r.stderr


MUTATIONS = [
    (
        "400 降级成 500（金额对不上被说成服务器故障）",
        LEDGER,
        "    raise HTTPException(\n        status_code=status.HTTP_400_BAD_REQUEST,\n        detail=(\n            f\"账本行的「合计」必须等于 数量 × 单价",
        "    raise HTTPException(\n        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,\n        detail=(\n            f\"账本行的「合计」必须等于 数量 × 单价",
        "对不上就 400",
    ),
    (
        "加一个绕过校验的出口（对不上也照收 given_total）",
        LEDGER,
        "    if given_total is None or given_total == computed:\n        return computed",
        "    if given_total is not None:\n        return given_total\n    if given_total is None or given_total == computed:\n        return computed",
        "出口只有两个",
    ),
    (
        "老算法抄回创建入口（同一行又能有两个答案）",
        LEDGER,
        "    given_total = None if (body.total is None or body.total == Decimal(\"0\")) else body.total\n    total = resolve_line_total(body.source, body.quantity, body.unit_price, given_total)",
        "    total = body.total\n    if total is None or total == Decimal(\"0\"):\n        total = body.unit_price * body.quantity",
        "老算法不许再长回来（创建入口那份）",
    ),
    (
        "老算法抄回修改入口（显式给了 total 就照收）",
        LEDGER,
        "        given_total = raw[\"total\"] if (\"total\" in raw and raw[\"total\"] is not None) else None\n        if given_total is not None or \"unit_price\" in raw or \"quantity\" in raw:\n            row.total = resolve_line_total(row.source, row.quantity, row.unit_price, given_total)",
        "        if \"total\" in raw and raw[\"total\"] is not None:\n            row.total = raw[\"total\"]\n        elif \"unit_price\" in raw or \"quantity\" in raw:\n            row.total = row.unit_price * row.quantity",
        "「显式给了 total 就照收」的形状不许再出现",
    ),
    (
        "把重算搬出那三个数的闸（只改备注也会重算）",
        LEDGER,
        "        if given_total is not None or \"unit_price\" in raw or \"quantity\" in raw:\n            row.total = resolve_line_total(row.source, row.quantity, row.unit_price, given_total)",
        "        row.total = resolve_line_total(row.source, row.quantity, row.unit_price, given_total)",
        "在 if 之内",
    ),
    (
        "订单来的行也收紧成必须相等（订单侧的口径被一起改了）",
        LEDGER,
        "    if source == LedgerSource.ORDER:\n        return given_total if given_total is not None else computed",
        "    if source == LedgerSource.ORDER:\n        return computed",
        "订单来的行以订单行金额为准",
    ),
    (
        "把已送达闸从「改一行」这条路上摘掉",
        LEDGER,
        "    _reject_if_order_closed(db, row, wants_detail=wants_detail, what=\"改这一行的商品与金额\")\n",
        "",
        "改一行时那道闸还拦在改钱之前",
    ),
    (
        "闸的判据不再与订单侧同源（手写状态清单）",
        LEDGER,
        "    if order.status not in LINE_EDITABLE_STATUSES:",
        "    if order.status not in (OrderStatus.PENDING, OrderStatus.ASSIGNED, OrderStatus.IN_TRANSIT):",
        "闸判的还是订单状态那套",
    ),
    (
        "400 文案里「收到的那个数」被删掉（用户没法自己改对）",
        LEDGER,
        "            f\" = {_money(computed)}，与你给的 合计 {_money(given_total)} 不一致。\"",
        "            f\" = {_money(computed)}，与你给的合计不一致。\"",
        "文案把**两个数**都报出来",
    ),
    (
        "把「记一整笔金额」的等价写法从文案里删掉",
        LEDGER,
        "            f\"（例如 数量 1、单价 {_money(given_total)} —— 记一整笔金额就这么写）。\"",
        "            f\"。\"",
        "文案还给了「记一整笔金额」的写法",
    ),
    (
        "把过期注释抄回 schema（口径又说成「要改得先拍板」）",
        SCHEMA,
        "    #:    ⚠️ 2026-10-10（BUG-0025 / 台账 TB-10）此后**这条也管住了**：`total` 显式给的时候",
        "    #:    ⚠️ 只加下界，**不动**「total 与 unit_price×quantity 是否必须相等」：要改得先拍板。\n    #:    ⚠️ 2026-10-10（BUG-0025 / 台账 TB-10）此后**这条也管住了**：`total` 显式给的时候",
        "过期注释",
    ),
    (
        "把这条用例改名/删掉（红灯不再有人守）",
        TEST_FILE,
        "test_只把合计改成与数量单价不符的值会被拒",
        "test_旧名字_这条用例被删了",
        "单测用例数",
    ),
    (
        "变更单少一节（§⑨ 被改成别的章节名）",
        CHANGE,
        "## ⑨ 关闭（六格）",
        "## ⑩ 关闭（六格）",
        "## ⑨ 关闭",
    ),
    (
        "台账那一行的编号被改错（TB-10 找不到）",
        LEDGER_DOC,
        "TB-10",
        "TB-19",
        "台账里那一行",
    ),
    (
        "登记表把这一单登记了两次",
        README,
        "](BUG-0025.md) |",
        "](BUG-0025.md) |\n| BUG-0025 | BUG | 重复登记（反验注入，跑完就还原） | | [BUG-0025.md](BUG-0025.md) |",
        "登记表里恰好一行",
    ),
    (
        "认领簿里这一单不见了（单号被写错）",
        CLAIM,
        "BUG-0025",
        "BUG-9999",
        "认领簿里有这一单",
    ),
]


def main() -> int:
    print("== 反向验证：把 BUG-0025 的修复逐条弄坏，每条都必须让判据红 ==")
    print("判据：" + str(CHECK.relative_to(ROOT)))
    base = run_check()
    if "项通过" not in base:
        print("⛔ 注入前的基线不是全绿 —— 判据现在自己就红着，反验结论不可信。")
        print("   先跑 python -X utf8 _tools/finance/_check_ledger_total_consistency.py 看差什么。")
        return 2
    print("   [基线] 注入前判据全绿：" + [ln for ln in base.splitlines() if "项通过" in ln][-1].strip())
    print()

    bad = 0
    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) < 1:
            print(f"  [SKIP] {label} —— 原文没找到：{old[:40]}")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            out = run_check()
        finally:
            restore_src(path, src, crlf)
        fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
        hit = any(expect in ln for ln in fails)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → 期望红：{expect}（实际红 {len(fails)} 条）")
        if not hit:
            for ln in fails[:3]:
                print("        " + ln.strip())
            bad += 1

    tail = run_check()
    ok = tail == base
    print("  [OK] 还原后逐字节一致：判据输出与注入前完全相同（全绿）" if ok
          else "  [MISS] 还原后判据的输出与注入前不一致")
    if not ok:
        for ln in tail.splitlines():
            if "[FAIL]" in ln:
                print("        " + ln.strip())
        bad += 1

    total = len(MUTATIONS) + 1
    print()
    print(f"✅ {total}/{total} 都红了：这条检查真的在检查。" if bad == 0 else f"❌ {bad}/{total} 不达标。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
