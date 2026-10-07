#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CHG-0086 反向验证：把「发票台账六条」的判据逐条弄红一次，确认它们不是空转的。

为什么必须有这个脚本
--------------------
静态判据最危险的失效方式不是「报错」，而是**空转**：判据写得再漂亮，只要它盯的那行源码
被挪走、改名、或者换一种写法，它就会永远绿下去，而没有任何人会发现 —— 收口时「跑了一遍
全绿」和「判据其实什么都没在管」从输出上看一模一样。所以这一单的收口不能只跑一次
_tools/qa/_check_ai_invoices.py 看它绿，还要逐条**注入一处真实的破坏**，看判据是否
**恰好红在那一条**上。

为什么「跳过」也算失败
----------------------
每条注入都要求原文在该文件里**恰好出现一次**：
  * 多于一次 = 锚点不唯一：改到哪一处不确定，改完是什么状态也不确定；
  * 零次     = 注入没生效（源码已经不是读到的样子），这条验证等于没做。
两种都记 [SKIP] 并计入失败 —— 宁可这里红，也不要带着「以为验过了」的错觉收工。

为什么文书那四处要单独一组（FILE_MUTATIONS）
-------------------------------------------
「登记簿里有这一条」「工作声明里有这一条」「台账里有 L-55 那一行」这三条判据问的是
**整个文件里有没有这个记号**（读全文做子串判断），而记号在文件里出现不止一次
（工作声明里既在标题里出现、又在「变更单 docs/changes/CHG-0086.md」里出现；台账里
既有章节标题、又有 L-55 那一行）。只改一处**不足以**把这类判据弄红，所以这一组用
「把所有出现都换掉」的口径，dry 里只要求「至少出现 1 次」—— 与上面那组区别对待。

反验顺手逮到的空转（三处，都已修）
----------------------------------
① 第 3 节「实现里定位确实传了 includeDeleted = true」读的是**整个数据源文件**，而
   "includeDeleted = true" 在别的域里出现 6 次 —— 发票这一跳一个字都不写也照样绿（改 INV
   的实参它不红）。⇒ 改成钉**发票处理器那一处实参**，并另加一条钉「数据源把它原样透传给
   repo」；本脚本对应第 22、23 两条注入。
② 测试那一节「假数据源记下了登记那一跳」找的是整个测试文件里的 "createInvoice:" —— 断言里
   的期望串本身还有两次，假数据源那一行改坏也照样绿。⇒ 改成钉 `invoiceCalls += "createInvoice:`
   （第 28 条注入）。
③ 文书那一节「变更单里写了台账 L-55」找的是整份变更单里的 "L-55" —— 文末那行也提到它，出处
   那一处删掉号照样绿。⇒ 改成钉出处那一句 `（**L-55**，台账末尾`（第 33 条注入）。

⚠️ 这三条都是「读的是全集、而不是该钉的那一处」——写成注入才暴露：单看判据全绿，把它该钉的
   那一处改坏也不红。

为什么不用文件的创建/删除（CREATIONS / DELETIONS）来判断
------------------------------------------------------
本脚本的判据全部钉在**显式文件路径**上（_check_ai_invoices.py 自己的常量）。把文件
挪走或删掉只会让检查脚本自己崩掉，而崩掉就没有 [FAIL] 行 —— 本脚本判的恰恰是「期望的
检查名出现在 [FAIL] 行里」，于是「崩了」会被误判成「没红」。所以只认 [FAIL] 行。

注入的破坏分八类（对应判据的八种失效方式）
------------------------------------------
① 定位口径：一个能收窄的都不给 / 找不到 / 撞上多张 / 命中回收站；
② 税额算法：全库唯一的那一式（movePointLeft / DOWN / HALF_UP）；
③ 登记的输入口径与卡片承诺（空票号、唯一占号、未税票、「不是新能力」）；
④ 改票 / 开具 / 作废 / 撤票四张卡与四道门；
⑤ 资源表与撤回表（恢复文案、挂错动作、两条 UNDO_NONE 理由）；
⑥ 数据源那一跳（includeDeleted 默认值与实参、repo.invoices、后端请求体）；
⑦ 工具与单测的钉子（动作数那句话、动作总数上界、假数据源、用例名、说明书上限、覆盖表）；
⑧ 文书四处（变更单九节与台账号、登记簿、工作声明、台账那一行）。

用法
----
    python _tools/qa/_reverse_verify_ai_invoices.py          # 真注入：改文件 -> 跑判据 -> 还原
    python _tools/qa/_reverse_verify_ai_invoices.py --dry    # 只验锚点，一个字节都不改
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_ai_invoices.py"

AI = "android/app/src/main/java/com/tapmoay/sorders/ai/"
INV = AI + "AiWriteInvoices.kt"
W = AI + "AiWrite.kt"
S = AI + "AiWriteService.kt"
SRC = AI + "AiWriteDataSource.kt"
RES = AI + "AiResources.kt"
RV = AI + "AiRevert.kt"
T = "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"
PT = "android/app/src/test/java/com/tapmoay/sorders/ai/AiWritePromptTest.kt"
WC = "_tools/ai/_write_coverage.py"
REGISTRY = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"
LEDGER = "_tmp/USER_BUG_LEDGER_20261006.md"
DOC = "docs/changes/CHG-0086.md"

# （说明, 相对路径, 原文, 替换成, 期望变红的检查名关键词）
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    # ---- ① 定位：窗口 / 上限 / 出路 / 多张 / 回收站 ----
    (
        "定位窗口从 31 天缩成 7 天（与账本不再同口径）",
        INV,
        "INVOICE_WINDOW_DAYS = 31L",
        "INVOICE_WINDOW_DAYS = 7L",
        "定位窗口与账本同口径（前后 31 天）",
    ),
    (
        "一次拉取上限从 100 抬到 500（与后端默认分页脱钩）",
        INV,
        "PROBE_LIMIT = 100",
        "PROBE_LIMIT = 500",
        "一次最多拉 100 张（与后端默认分页一致）",
    ),
    (
        "拒绝时不再给「先看一眼台账」这条出路",
        INV,
        "先看一眼发票台账：这张票的票号 / 日期 / 金额 / 对方是谁",
        "找不到就先算了",
        "拒绝时给一条出路（先看一眼台账）",
    ),
    (
        "撞上多张时不再列候选、直接按第一张动手",
        INV,
        "请说清楚是哪一张（票号最准）。",
        "就按第一张来。",
        "撞上多张就列候选、拒绝动手",
    ),
    (
        "命中回收站时说成「没有这张票」",
        INV,
        "先说「恢复这张票」，把它放回台账再改。",
        "这张票不存在。",
        "命中回收站要如实说（不是「没有这张票」）",
    ),
    # ---- ② 税额：全库唯一的那一式 ----
    (
        "税额算法改用 double（把百分数变成浮点除法）",
        INV,
        "BigDecimal.ONE + rate.movePointLeft(2)",
        "BigDecimal.ONE + BigDecimal(rate.toDouble() / 100.0)",
        "算法用 movePointLeft 把百分数变成除数（不用 double）",
    ),
    (
        "中间那一步除法不再向下取（改成四舍五入）",
        INV,
        "RoundingMode.DOWN",
        "RoundingMode.HALF_UP",
        "中间除法向下取（与后端同一式）",
    ),
    # ---- ③ 登记：输入口径与卡片承诺 ----
    (
        "未税票的口径从参数提示里删掉",
        INV,
        "不给 = 未税票（未税票不进税汇）",
        "不给 = 未税票",
        "登记参数把「未税票」的口径写在提示里",
    ),
    (
        "一单或多单的分隔方式不再说清",
        INV,
        "用「、」或「,」分开，例如 12、15",
        "用逗号分开",
        "挂采购单参数写清一单或多单怎么分隔",
    ),
    (
        "空票号那句「先空着」删掉",
        INV,
        "票号：还没拿到，先空着（登记之后可以在台账里补上）",
        "票号：（空）",
        "登记卡：空票号怎么说",
    ),
    (
        "票号唯一占号这句删掉",
        INV,
        "票号一旦登记就唯一占号：同一个方向、同一个票号只能有一张票",
        "票号随便填",
        "登记卡：票号唯一占号",
    ),
    (
        "未税票「照常留在台账里、但不进税汇」这句删掉一半",
        INV,
        "这是一张未税票：它照常留在台账里，但不进税汇",
        "这是一张未税票",
        "登记卡：未税票当场说清它不进税汇",
    ),
    (
        "把「这六个端点不是新能力」改写成新端点",
        INV,
        "后端这六个写端点干的是六件不同的事",
        "这三个接口是新加的端点",
        "六条都不是新能力（免得后人以为是新端点）",
    ),
    # ---- ④ 改票 / 开具 / 作废 / 撤票：门与卡 ----
    (
        "改票的状态门松掉（已开具的也说能改）",
        INV,
        "只有「已登记」状态的票能改；要改就作废重开一张。",
        "什么时候都能改。",
        "改票门：已开具 / 已作废改不动",
    ),
    (
        "开具卡那句「冻结」删掉",
        INV,
        "开具之后这张票就冻结了：一个字都改不动（要改只能作废重开一张）",
        "开具之后还能在页面上改。",
        "开具卡：开具＝冻结",
    ),
    (
        "作废与撤票说成差不多（把两者的区别抹掉）",
        INV,
        "它和「撤票」不是一件事：撤票是进回收站（列表里看不见、可以原样恢复）；作废是留在台账里、不可逆",
        "它和撤票差不多",
        "作废卡：与「撤票」不是一件事",
    ),
    # ---- ⑤ 资源表与撤回表 ----
    (
        "资源里的恢复文案换回默认（默认那句提到图片与坐标）",
        RES,
        "票没有图片也没有坐标",
        "恢复之后一切照旧",
        "恢复那两句换成本表自己的（默认那句提到图片与坐标）",
    ),
    (
        "资源下的改票那条挂成订单的改单动作",
        RES,
        "update(AiWrites.INVOICES_UPDATE),",
        "update(AiWrites.ORDERS_UPDATE),",
        "三条动作挂在资源下（改 / 删 / 成对恢复）",
    ),
    (
        "撤回表里登记那条理由改成「撤得回来」",
        RV,
        "票已经登记进台账了，撤不回来（登记那一刻起它就占着号、进税汇）",
        "登记之后可以撤回来",
        "登记没有逆操作，理由逐条写明",
    ),
    (
        "撤回表里开具那条理由改成「能反悔」",
        RV,
        "开具不能反悔：这张票已经从「已登记」变成「已开具」，票号、金额、日期一个字都改不动了",
        "开具之后还能反悔",
        "开具没有逆操作（冻结）",
    ),
    # ---- ⑥ 数据源那一跳 ----
    (
        "数据源接口的 includeDeleted 默认值改成 true",
        S,
        "includeDeleted: Boolean = false,",
        "includeDeleted: Boolean = true,",
        "接口的 includeDeleted 默认 false",
    ),
    (
        "定位那一跳不传 includeDeleted = true（票在回收站会被判成不存在）",
        INV,
        "includeDeleted = true,",
        "includeDeleted = false,",
        "实现里定位确实传了 includeDeleted = true",
    ),
    (
        "数据源那一跳把 includeDeleted 写死成 false（不再透传调用方的选择）",
        SRC,
        "includeDeleted = includeDeleted,",
        "includeDeleted = false,",
        "数据源把 includeDeleted 原样透传给 repo（不是自己写死）",
    ),
    (
        "定位那一跳不再走 repo.invoices",
        SRC,
        "repo.invoices(",
        "repo.ledgerEntries(",
        "定位实现走 repo.invoices",
    ),
    (
        "登记那一跳不再用后端那个建单请求体",
        SRC,
        "InvoiceCreateRequest(",
        "InvoiceUpdateRequest(",
        "登记实现用的是后端那一个请求体",
    ),
    # ---- ⑦ 工具与单测的钉子 ----
    (
        "动作数那句话不跟着改（171 说成 165）",
        W,
        "171 个动作里 44 条在清单内",
        "165 个动作里 44 条在清单内",
        "动作数那句话跟着改了（171 里 44 条）",
    ),
    (
        "单测里动作总数上界缩回 165",
        T,
        "AiWrites.ALL.size <= 171",
        "AiWrites.ALL.size <= 165",
        "单测里钉住了动作总数上界 171",
    ),
    (
        "假数据源不再记登记那一跳",
        T,
        'invoiceCalls += "createInvoice:',
        'invoiceCalls += "createInvoiceX:',
        "假数据源记下了登记那一跳",
    ),
    (
        "撤票那条用例被改名（判据按用例名逐条钉）",
        T,
        "发票·撤票：进回收站、票号还占着；撤回把它原样放回来",
        "发票·撤票：进回收站、票号还占着",
        "单测里有这一条：发票·撤票",
    ),
    (
        "说明书上限缩回 27000（动作数涨了却没收口）",
        PT,
        "（上限 29000）",
        "（上限 27000）",
        "说明书上限已抬到 29000（动作数涨了）",
    ),
    (
        "覆盖表的来龙去脉把「排期」说成「新缺口」",
        WC,
        "用户 2026-10-08 把这条排期",
        "这条是新的能力缺口",
        "来龙去脉留着（这一单解掉的是排期）",
    ),
    (
        "覆盖表不再写明六条只给派单员",
        WC,
        "六条都只给派单员（后端要 ledger:edit）",
        "六条给派单员和货主",
        "覆盖表写明六条只给派单员",
    ),
    # ---- ⑧ 文书 ----
    (
        "变更单里删掉台账号（收口时要能顺着 L-55 找到台账那一行）",
        DOC,
        "（**L-55**，台账末尾",
        "（台账号见台账末尾",
        "变更单里写了台账 L-55",
    ),
    (
        "变更单少写一节（⑨ 关闭 被改名）",
        DOC,
        "## ⑨ 关闭",
        "## 9. 关闭",
        "变更单九节齐",
    ),
    (
        "登记簿里这一行换个号（文件在、表里没有）",
        REGISTRY,
        "| " + chr(96) + "CHG-0086" + chr(96) + " | CHG |",
        "| " + chr(96) + "CHG-0099" + chr(96) + " | CHG |",
        "登记簿里有这一条",
    ),
]

# 这一组问的是「整个文件里有没有这个记号」，记号本身出现不止一次 ⇒ 用「全部换掉」的口径。
# （说明, 相对路径, 原文, 替换成, 期望变红的检查名关键词）
FILE_MUTATIONS: list[tuple[str, str, str, str, str]] = [
    (
        "工作声明里 CHG-0086 全部改号（文件在、声明里没有）",
        CLAIM,
        "CHG-0086",
        "CHG-0099",
        "工作声明里有这一条",
    ),
    (
        "台账里 L-55 全部改号（行还在、编号不对）",
        LEDGER,
        "L-55",
        "L-99",
        "台账里有 L-55 那一行",
    ),
]


def read_src(rel: str) -> tuple[str, bool]:
    raw = (ROOT / rel).read_bytes()
    crlf = b"\r\n" in raw
    return raw.decode("utf-8").replace("\r\n", "\n"), crlf


def write_src(rel: str, text: str, crlf: bool) -> None:
    data = text.replace("\n", "\r\n") if crlf else text
    (ROOT / rel).write_bytes(data.encode("utf-8"))


def restore_src(rel: str, text: str, crlf: bool, expect: bytes) -> None:
    write_src(rel, text, crlf)
    back = (ROOT / rel).read_bytes()
    if back != expect:
        print("  [FATAL] 还原后字节不一致：{}".format(rel))
        raise SystemExit(2)


def run_check():
    # 子进程强制 UTF-8：Windows 控制台默认是 GBK，判据里的中文标签一旦被按 GBK 编码，
    # 这一侧按 UTF-8 解出来就是乱码，expect 关键词会永远匹配不上（全部误报 MISS）。
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(CHECK)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def fails_of(out: str) -> list[str]:
    return [line.strip() for line in out.splitlines() if line.strip().startswith("[FAIL]")]


def verdict(expect: str, proc) -> tuple[bool, str]:
    lines = fails_of(proc.stdout + proc.stderr)
    if proc.returncode == 0:
        return False, "判据**没红**（退出码 0）—— 这条检查是空转的"
    hit = [line for line in lines if expect in line]
    if hit:
        return True, hit[0]
    return False, "红了但不是这条（实际红 {} 条）：{}".format(len(lines), " | ".join(lines[:3]))


def dry_run() -> int:
    print("== 只验锚点（--dry）：一个字节都不改 ==")
    bad = 0
    for idx, (why, rel, old, _new, expect) in enumerate(MUTATIONS, start=1):
        text, _crlf = read_src(rel)
        n = text.count(old)
        if n == 1:
            print("  [OK]   {}. {} :: {}".format(idx, rel, why))
        else:
            bad += 1
            print("  [BAD]  {}. {} :: {} —— 原文出现 {} 次（期望 1 次）；期望判据：{}".format(idx, rel, why, n, expect))
    base = len(MUTATIONS)
    for idx, (why, rel, old, _new, expect) in enumerate(FILE_MUTATIONS, start=1):
        text, _crlf = read_src(rel)
        n = text.count(old)
        if n >= 1:
            print("  [OK]   {}. {} :: {}（全文换掉 {} 处）".format(base + idx, rel, why, n))
        else:
            bad += 1
            print("  [BAD]  {}. {} :: {} —— 出现 0 次；期望判据：{}".format(base + idx, rel, why, expect))
    print()
    if bad:
        print("❌ {} 条锚点不唯一 / 找不到。".format(bad))
        return 1
    print("✅ {} 条锚点全部命中（{} 条单点 ＋ {} 条全文）。".format(len(MUTATIONS) + len(FILE_MUTATIONS), len(MUTATIONS), len(FILE_MUTATIONS)))
    return 0


def main() -> int:
    if "--dry" in sys.argv:
        return dry_run()

    total = len(MUTATIONS) + len(FILE_MUTATIONS) + 1
    print("== 0. 前提：源码完好时判据必须全绿 ==")
    proc = run_check()
    if proc.returncode != 0:
        print("  [FATAL] 起点判据就是红的，没法做反向验证（先修好再加注入）。")
        for line in fails_of(proc.stdout + proc.stderr)[:10]:
            print("    " + line)
        return 2
    for line in (proc.stdout + proc.stderr).splitlines():
        if "全部" in line and "通过" in line:
            print("  [OK]  " + line.strip())
            break
    else:
        print("  [OK]  判据退出码 0")

    print()
    print("== 1. 逐条注入 -> 跑判据 -> 还原 ==")
    bad = 0
    for idx, (why, rel, old, new, expect) in enumerate(MUTATIONS, start=1):
        text, crlf = read_src(rel)
        n = text.count(old)
        if n != 1:
            bad += 1
            print("  [SKIP] {}. {} :: {} —— 原文出现 {} 次（期望 1 次）".format(idx, rel, why, n))
            continue
        before = (ROOT / rel).read_bytes()
        try:
            write_src(rel, text.replace(old, new), crlf)
            got = run_check()
            ok, detail = verdict(expect, got)
        finally:
            restore_src(rel, text, crlf, before)
        if ok:
            print("  [OK]   {}. {} :: {} -> 判据红在「{}」".format(idx, rel, why, expect))
        else:
            bad += 1
            print("  [MISS] {}. {} :: {} -> {}".format(idx, rel, why, detail))

    base = len(MUTATIONS)
    for idx, (why, rel, old, new, expect) in enumerate(FILE_MUTATIONS, start=1):
        seq = base + idx
        text, crlf = read_src(rel)
        n = text.count(old)
        if n < 1:
            bad += 1
            print("  [SKIP] {}. {} :: {} —— 原文出现 0 次".format(seq, rel, why))
            continue
        before = (ROOT / rel).read_bytes()
        try:
            write_src(rel, text.replace(old, new), crlf)
            got = run_check()
            ok, detail = verdict(expect, got)
        finally:
            restore_src(rel, text, crlf, before)
        if ok:
            print("  [OK]   {}. {} :: {}（{} 处）-> 判据红在「{}」".format(seq, rel, why, n, expect))
        else:
            bad += 1
            print("  [MISS] {}. {} :: {} -> {}".format(seq, rel, why, detail))

    print()
    print("== 2. 收尾：文件都还原之后，判据必须重新全绿 ==")
    proc = run_check()
    if proc.returncode == 0:
        print("  [OK]  判据重新全绿（没有文件被留在改坏的状态）")
    else:
        bad += 1
        print("  [MISS] 还原之后判据仍然是红的 —— 有文件没还原干净")
        for line in fails_of(proc.stdout + proc.stderr)[:10]:
            print("    " + line)

    print()
    if bad:
        print("❌ {}/{} 条不成立。".format(bad, total))
        return 1
    print("✅ {}/{} 全部成立：每条判据都被单独弄红过一次，而且只在它自己身上红。".format(total, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
