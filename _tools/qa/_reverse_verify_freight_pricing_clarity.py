# -*- coding: utf-8 -*-
"""反向验证：把 CHG-0029 那条红线逐条弄坏，证明它真的会红。

为什么要反向验证：一条判据可以永远绿（条件写错、扫到空字符串、路径搬走后 read() 返回空），
那样它就不是红线而是摆设。这里逐条注入「改坏了」的版本，每条都必须让
_tools/qa/_check_freight_pricing_clarity.py 非零退出：

- 形状类：把状态字段 / 共用取数口 / 响应头判读 / 调用点 / 路由绑定删掉（判据靠字面量钉着）；
- 口径类：把「三件事同句说清」那句改短、把截断说成确数、给那一行加金额或 maxLines；
- 规则卡类：把口径标签删掉、把被冻原话改一个字、把追加句删掉、把条件反过来；
- 文档类：把反向脚本从配对表里删掉、把登记表那一行改名。

⚠️ 快照按字节做（CRLF / LF 都要原样还回去），跑完逐字节核对。

用法：python _tools/qa/_reverse_verify_freight_pricing_clarity.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_freight_pricing_clarity.py"

VM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/FreightSettlementViewModel.kt"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/FreightSettlementScreen.kt"
RULES = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt"
NAV = "android/app/src/main/java/com/tapmoay/sorders/ui/nav/NavGraph.kt"
README = "docs/changes/README.md"

CR = bytes((13,))
LF = bytes((10,))
CRLF = CR + LF
BT = chr(96)

#: 判据里那个「配对表」常量（自指注入要锚赋值行，不要锚裸路径）
REVERSE_CONST = 'REVERSE = "_tools/qa/_reverse_verify_freight_pricing_clarity.py"'
#: 结算页那一行的去向（判据按它判两件事：路由接没接、两条路还通不通）
NAV_LINE = "onOpenUnpriced = { navController.navigate(Routes.FREIGHT_UNPRICED) },"
#: 登记表里那一行
README_ROW = "| " + BT + "CHG-0029" + BT + " |"

CASES: list[tuple[str, str, object, str]] = [
    (
        "把 load() 里那一句调用删掉（定义了却没人调）",
        VM,
        lambda s: s.replace("\n            loadUnpriced()\n", "\n", 1),
        "loadUnpriced",
    ),
    (
        "不从共用取数口取（自己换一个查询方法）",
        VM,
        lambda s: s.replace("val page = container.repo.unpricedOrders()",
                            "val page = container.repo.orders(limit = 200)", 1),
        "共用取数口",
    ),
    (
        "截断又改回按条数猜（不认响应头）",
        VM,
        lambda s: s.replace("unpricedMore = page.meta.hasMore",
                            "unpricedMore = page.rows.size >= 200", 1),
        "猜法",
    ),
    (
        "失败时把错误写进页面状态（连带把主表拖红）",
        VM,
        lambda s: s.replace("            unpricedRows = emptyList()\n            unpricedMore = false",
                            "            error = \"取待定价的单失败\"\n            unpricedRows = emptyList()\n            unpricedMore = false", 1),
        "不把主表拖红",
    ),
    (
        "0 单也显示那一行（改成 count < 0 才不显示）",
        SCREEN,
        lambda s: s.replace("if (count <= 0) return null", "if (count < 0) return null", 1),
        "还有 0 单",
    ),
    (
        "被截断时还说确数",
        SCREEN,
        lambda s: s.replace('val n = if (more) "$count 单以上" else "$count 单"',
                            'val n = "$count 单"', 1),
        "截断了还说确数",
    ),
    (
        "那一行少说一件事（拿掉「不分司机」）",
        SCREEN,
        lambda s: s.replace(" —— 不分司机，也不在上面这张表里", " —— 点右边去看看", 1),
        "三件事没同句说清",
    ),
    (
        "文案函数写好了却没人调用",
        SCREEN,
        lambda s: s.replace("                unpricedNotice(vm.unpricedRows.size, vm.unpricedMore)?.let { text ->\n                    UnpricedNoticeRow(text, onOpenUnpriced)\n", "", 1),
        "没人调用",
    ),
    (
        "点那一行没有去处（回调被换成一个空的）",
        SCREEN,
        lambda s: s.replace("UnpricedNoticeRow(text, onOpenUnpriced)",
                            "UnpricedNoticeRow(text, {})", 1),
        "没人调用",
    ),
    (
        "给那一行加上 maxLines = 1（挤压基线只许降）",
        SCREEN,
        lambda s: s.replace('Text("去定价"', 'Text("去定价", maxLines = 1,', 1),
        "自适应挤压基线",
    ),
    (
        "给那一行加上金额（钱数此刻还不存在）",
        SCREEN,
        lambda s: s.replace("private fun UnpricedNoticeRow(text: String, onOpen: () -> Unit) {",
                            "private fun UnpricedNoticeRow(text: String, onOpen: () -> Unit) {\n    val hint = formatMoney(0)", 1),
        "写了金额",
    ),
    (
        "结算页多出第二处选人那一行（会踩掉另一条反验的注入锚点）",
        SCREEN,
        lambda s: s.replace("    onOpenOrder: (Long) -> Unit = {},",
                            "    onOpenOrder: (Long) -> Unit = {},\n                PersonTriggerRow(", 1),
        "多一处会让",
    ),
    (
        "把口径标签「给司机的钱」删掉",
        RULES,
        lambda s: s.replace('        Text("给司机的钱", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)\n', "", 1),
        "标签不在",
    ),
    (
        "把被冻的那句原话改一个字",
        RULES,
        lambda s: s.replace("还没勾价目 —— 派给这个司机的单会进「待定价」",
                            "还没勾价目：派给这个司机的单会进「待定价」", 1),
        "被冻的话",
    ),
    (
        "把追加的那句运费口径解释删掉",
        RULES,
        lambda s: s.replace('                "「给司机的钱」是工资；运费按价目算，没勾价目运费就出不来（点「编辑」勾上）",\n', "", 1),
        "没说清那笔 22 元是工资",
    ),
    (
        "角标的出现条件反过来（勾了价目的才挂缺价目）",
        RULES,
        lambda s: s.replace("rule.templateBriefs.isEmpty()", "rule.templateBriefs.isNotEmpty()", 1),
        "没有角标",
    ),
    (
        "把结算页那一行的路由绑定整条删掉（点了什么都不会发生）",
        NAV,
        lambda s: s.replace(NAV_LINE, "", 2),
        "没接路由",
    ),
    (
        "把反向脚本从配对表里删掉（判据就再也找不到它）",
        "_tools/qa/_check_freight_pricing_clarity.py",
        lambda s: s.replace(REVERSE_CONST,
                            'REVERSE = "_tools/qa/_reverse_verify_freight_pricing_clarityX.py"', 1),
        "找不到",
    ),
    (
        "把登记表里那一行改名（文档与目录不再一一对应）",
        README,
        lambda s: s.replace(README_ROW, "| " + BT + "CHG-0029x" + BT + " |", 1),
        "没有 CHG-0029 那一行",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据就没全绿 —— 先修判据，再谈反验。")
        print(out)
        return 1
    print("✅ 前提成立：源码完好时判据全绿。")
    print()

    touched = sorted({rel for _d, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    misses = 0
    for desc, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = CRLF in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            print(f"⚠️  注入没生效（锚点变了，请更新本脚本）：{desc}")
            misses += 1
            continue
        payload = mutated.replace("\n", "\r\n") if crlf else mutated
        try:
            path.write_bytes(payload.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"✅ {desc}")
        else:
            misses += 1
            print(f"❌ {desc} —— 期望判据变红并说出「{expect}」，实际退出码 {code}")
            print(out[-1500:])

    print()
    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        print("❌ 还原检查失败，这些文件与运行前不一致：" + "、".join(dirty))
        return 1
    print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")
    if misses:
        print(f"❌ {misses} 条注入没证明判据会红。")
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
