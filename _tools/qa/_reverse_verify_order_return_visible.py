# -*- coding: utf-8 -*-
"""反向验证：`_tools/qa/_check_order_return_visible.py` 的每一条判据都**真的会红** —— 台账 L-21（CHG-0054）。

## 为什么要有这一份
这一条守的是「用户没说就看不见」的那类退化：净数算式改回原数量、小字不画、那块只读的退货申请被换成
跳转、取数失败改成写页面级 error、件数与金额退回原价……每一条**都不会有编译错误、不会有任何用例报红**
（商品明细照旧四格、钱按原价显示也"看着对"、`_check_order_row_columns.py` 照样绿）。判据脚本写得再细，只要它自己坏了
（锚点漂了、正则写宽了、切段一路切到文件尾），它**照样全绿** —— 所以这里逐条把源码改坏一次，
要求判据必须报红。

## 手法
- 每条：快照原文件（**按字节**）→ 字符串替换一次 → 跑判据 → 期望某条**具体**的判据变红 → 按字节还原。
- 还原之后**重新读回来逐字节比对**；不一致直接 `SystemExit(2)`（一次没还原，后面所有结论都建立在坏代码上）。
- ⛔ 全程不碰 git 的还原命令：那会把工作区里**别人**的改动一起吞掉。
- 锚点是源码片段，会随源码漂：漂了这里打 `[SKIP]`（`exit 1`），**不装成绿**。

用法：python _tools/qa/_reverse_verify_order_return_visible.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_order_return_visible.py"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND / "ui/order/OrderDetailScreen.kt"
VM = AND / "ui/order/OrderDetailViewModel.kt"
ROWCOL = HERE / "_check_order_row_columns.py"
CHG = ROOT / "docs/changes/CHG-0054.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: (说明, 文件, 原文, 替换成, 期望变红的那条判据里的关键词)
MUTATIONS = [
    (
        "净数算式改回原数量（没退过货的单子照样对，退过货的悄悄多画几件）",
        SCREEN,
        "private fun netQty(l: OrderProductDto): Int = (l.quantity - l.returnedQuantity).coerceAtLeast(0)",
        "private fun netQty(l: OrderProductDto): Int = l.quantity",
        "净数算式全仓只有这一份",
    ),
    (
        "只改画出来那处、量宽度仍按原数量（列宽按 ×12 量、数字画 ×9，右边被裁掉）",
        SCREEN,
        'rememberTextWidth("×" + qtyWithUnitConverted(netQty(l)',
        'rememberTextWidth("×" + qtyWithUnitConverted(l.quantity',
        "量宽度与画出来那串都走 netQty",
    ),
    (
        "「已退 N」改成无条件画（每一行都多一句「已退 0」，信号被淹掉）",
        SCREEN,
        "if (line.returnedQuantity > 0) {",
        "if (true) {",
        "「已退 N」紧跟净数",
    ),
    (
        "小字干脆不画（件数变小了没人解释 —— 用户报的就是这一条）",
        SCREEN,
        '"已退 " + line.returnedQuantity',
        '"已退 " + 0',
        "「已退 N」紧跟净数",
    ),
    (
        "那块退货申请改成**跳转**（焦点徽章会变成假话）",
        SCREEN,
        "if (returnRequests.isNotEmpty()) {",
        "if (returnRequests.isNotEmpty()) {\n                    val jump = Routes.shipperReturnRequests()",
        "整块里一次都没有出现 Routes",
    ),
    (
        "那块里加一颗按键（它本来只许看）",
        SCREEN,
        "if (returnRequests.isNotEmpty()) {",
        'if (returnRequests.isNotEmpty()) {\n                    TextButton(onClick = { }) { Text("去处理") }',
        "这一块里没有任何按键",
    ),
    (
        "状态胶囊换掉、自己画状态（中文名会与其它页面分叉）",
        SCREEN,
        "ReturnRequestStatusChip(status = req.status, label = req.statusLabel)",
        "Text(req.status)",
        "状态胶囊走共用件",
    ),
    (
        "要退的东西不再照登（自己拼一份摘要）",
        SCREEN,
        '"要退 " + req.linesSummary',
        '"要退 " + req.lines.size.toString() + " 项"',
        "要退的东西原文照登",
    ),
    (
        "被驳回的原因不画（货主拿不到答复）",
        SCREEN,
        'if (req.status == "rejected") {',
        "if (false) {",
        "被驳回的要把原因画出来",
    ),
    (
        "被驳回 / 已办结的分支改成恒假（答复与办理人一起消失）",
        SCREEN,
        'if (req.status == "done") {',
        "if (false) {",
        "已办结的要说清是谁办的",
    ),
    (
        "申请时间不画",
        SCREEN,
        '"申请时间 " + formatDateTimeFull(req.createdAt),',
        '"",',
        "申请时间画出来",
    ),
    (
        "那块里偷偷去调仓库（只读边界没了）",
        SCREEN,
        "if (returnRequests.isNotEmpty()) {",
        "if (returnRequests.isNotEmpty()) {\n                    val leak = container.repo",
        "没有直接调仓库",
    ),
    (
        "行金额退回原价（用户 2026-10-07 的报障当场复发：件数是净数、钱是原价）",
        SCREEN,
        "netLineMoneyText(line),",
        '"¥" + formatMoney(line.lineTotal),',
        "行金额画的是**退货后**的净额",
    ),
    (
        "合计退回原价（Σ lineTotal）——退过货的单上下两个数又说两件事",
        SCREEN,
        "val netTotal = netOrderMoneyText(order)",
        'val netTotal = "¥" + formatMoney(order.orderProducts.sumOf { moneyToDouble(it.lineTotal) }.toString())',
        "合计同样画净额",
    ),
    (
        "「已退 ¥X」改成恒不画（钱退了多少，页面上没人说）",
        SCREEN,
        "if (returnedAmount > 0.0) {",
        "if (false) {",
        "合计同样画净额",
    ),
    (
        "角色不再看登录缓存（自己猜一个）",
        VM,
        "container.tokenStore.cachedRole()",
        '"shipper"',
        "角色用的是登录缓存里那一份",
    ),
    (
        "取数函数没人调了（打开详情不再拉）",
        VM,
        "private fun loadReturnRequests() {",
        "private fun loadReturnRequestsGone() {",
        "loadReturnRequests() 恰两处",
    ),
    (
        "档位改成只拉待办（已通过的退货就看不见了）",
        VM,
        "status = RETURN_STATUS_ALL",
        'status = "pending"',
        "两个接口都按 RETURN_STATUS_ALL",
    ),
    (
        "非关键取数失败改成写页面级 error（整页被顶成 ErrorView）",
        VM,
        ".getOrDefault(emptyList())",
        '.getOrElse {\n                    error = "退货申请加载失败"\n                    emptyList()\n                }',
        "这一块自己不许写页面级 error",
    ),
    (
        "状态量改回可写（外面谁都能改）",
        VM,
        "var returnRequests by mutableStateOf<List<ReturnRequestDto>>(emptyList())\n        private set",
        "var returnRequests by mutableStateOf<List<ReturnRequestDto>>(emptyList())",
        "returnRequests 是 mutableStateOf",
    ),
    (
        "列宽判据被改回原数量（它会重新去盯一句不存在的源码）",
        ROWCOL,
        "netQty",
        "qtyNet",
        "列宽判据已改成净数",
    ),
    (
        "CHG 的 Boundary 结论改成 CORE（分层就错了）",
        CHG,
        "- **结论**：**PRESENTATION（展示层）**",
        "- **结论**：**CORE（核心）**",
        "CHG-0054.md 的 Boundary 结论逐字",
    ),
    (
        "CHG 里不再写用户要的那句「已退 3」",
        CHG,
        "已退 3",
        "已退 N",
        "CHG-0054.md 写了「已退 3」",
    ),
    (
        "CHG 里不再写净数算式（看的人不知道要认哪一句）",
        CHG,
        "netQty",
        "qtyNet",
        "CHG-0054.md 写了「netQty」",
    ),
    (
        "README 的登记行改成死链",
        README,
        "[CHG-0054.md](CHG-0054.md)",
        "[CHG-0054.md](CHG-54.md)",
        "README 里登记了 CHG-0054",
    ),
    (
        "AI_WORK_CLAIM 里的条目被改号",
        CLAIM,
        "CHG-0054",
        "CHG-54",
        "AI_WORK_CLAIM 里认领了 CHG-0054",
    ),
]


def snapshot(p: Path) -> bytes:
    """按**字节**取快照（注释里的换行、BOM、CRLF 都要原样还原）。"""
    return p.read_bytes()


def mutate(p: Path, old: str, new: str) -> int:
    """把 `old` 换成 `new`，返回替换了几处（0 ＝ 锚点漂了）。

    ⚠️ 行尾：读到 CRLF 就先归一成 LF 再替换，写回时**按原来的行尾风格**还原 —— 否则一棵 CRLF 的
    Kotlin 文件会被写成 LF（`git status` 里看不出来，但字节确实变了）。
    """
    raw = p.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8")
    if crlf:
        text = text.replace("\r\n", "\n")
    n = text.count(old)
    if n == 0:
        return 0
    text = text.replace(old, new)
    p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    return n


def restore(p: Path, original: bytes) -> None:
    """按字节写回（不是「把替换反着做一遍」—— 那要求替换是可逆的，而它不必是）。"""
    p.write_bytes(original)


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def hit(out: str, want: str) -> bool:
    """判据的失败行必须是 `  [!!]   {label}` 这个形状（反向验证只认它）。"""
    return ("[!!]   " + want) in out


def main() -> int:
    files = [SCREEN, VM, ROWCOL, CHG, README, CLAIM]
    missing = [str(p) for p in files if not p.exists()]
    if missing:
        print("❌ 前提不成立：这些文件还不存在 —— " + "、".join(missing))
        return 2
    snaps = {str(p): snapshot(p) for p in files}
    code0, out0 = run_check()
    if code0 != 0:
        print("❌ 前提不成立：判据现在不是全绿，先让它全绿再来跑反向验证。尾部输出：")
        print(out0[-2000:])
        return 2
    print("前提：判据 " + str(out0.count("[OK]")) + " 项全绿 ✅；开始逐条注入坏代码。\n")
    ok = 0
    bad: list[str] = []
    skipped: list[str] = []
    try:
        for i, (why, path, old, new, want) in enumerate(MUTATIONS, 1):
            n = mutate(path, old, new)
            if n == 0:
                print("[SKIP] " + f"{i:2d}. " + why + " —— 锚点在这个文件里出现 0 次，无法注入")
                skipped.append(why)
                continue
            try:
                code, out = run_check()
            finally:
                restore(path, snaps[str(path)])
            if code != 0 and hit(out, want):
                print("  [OK] " + f"{i:2d}. " + why + " —— 「" + want + "」报红了")
                ok += 1
            else:
                print("  [!!] " + f"{i:2d}. " + why + " —— 期望「" + want + "」报红，实际 "
                      + ("判据仍然全绿（这一条是**假的**）" if code == 0 else "报红的是别的一条"))
                bad.append(why)
    finally:
        for k, v in snaps.items():
            restore(Path(k), v)

    dirty = [k for k, v in snaps.items() if Path(k).read_bytes() != v]
    if dirty:
        print("❌ 还原不干净（重新读回来与快照字节不一致）：" + "、".join(dirty))
        return 2
    code1, out1 = run_check()
    if code1 != 0:
        print("❌ 还原之后判据不是全绿（说明有文件被写坏了）：")
        print(out1[-2000:])
        return 2
    print("\n还原：6 个文件都按字节比对一致，判据重新全绿 ✅")
    print("=" * 60)
    if bad or skipped:
        print("❌ " + str(len(bad)) + " 条没被抓到、" + str(len(skipped)) + " 条锚点漂了（共 "
              + str(len(MUTATIONS)) + " 条）")
        return 1
    print("✅ " + str(ok) + "/" + str(len(MUTATIONS)) + " 全部成立：每条注入都被对应判据抓到，"
          + "且源码按字节还原。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
