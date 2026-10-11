"""红线：批量确认卡**一张卡 + 一张长表格 + 连点幂等**（CHG-0119，2026-10-11）。

R4-BOUNDARY-JUSTIFICATION:
  允许变的是**卡的形状与回执的口气**（一张长表格 / 有效期 / 连点第二下说什么），
  不许变的是**写下去多少条**与**逐行如实汇报**：表格只是渲染，payload 里仍是那 N 条；
  「成功 N / 失败 M + 失败的是哪一条」由 AiWriteHandler.commitNote() 一路带到 Done。
  所以判据钉的是：表与写入同源、三句话分得开、逐行结果不许被「已完成」盖住 ——
  这三件坏起来都**完全静默**（用户看到一张漂亮的表，以为那 40 条都成了）。

## 判据
1. 表从**逐条 prepare 出来的卡**渲染（sheet(items)），且批量卡确实带 table；
2. 表格只影响显示：payload 仍是 _batch 数组，条数与表行数无关；
3. 有效期：批量卡 30 分钟（BATCH_TTL_MS 具名常量）> 单条卡 5 分钟，且真的按 batch 分支取值；
4. 连点/过期/被顶掉**三句话分开说**，且这三条路上不许再出现「没写成」；
5. 被顶掉 ≠ 过期（不许往有效期上引）；
6. 单测清单**自己算**（数 @Test），低于下限就报错（防清单过期空转）。

用法：python _tools/qa/_check_ai_batch_card.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AND_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai"

MIN_KT_TESTS = 15

FAILS: list[str] = []
CHECKS = 0


def ok(cond: bool, msg: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(msg)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def kt_code(src: str) -> str:
    out: list[str] = []
    in_block = False
    for ln in src.splitlines():
        s = ln.strip()
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("/*"):
            if "*/" not in s:
                in_block = True
            continue
        if s.startswith("//"):
            continue
        out.append(ln)
    return "\n".join(out)


def main() -> int:
    table = kt_code(read(AND / "ai/AiCardBatchTable.kt"))
    batch = kt_code(read(AND / "ai/AiWriteBatch.kt"))
    write = kt_code(read(AND / "ai/AiWrite.kt"))
    svc = kt_code(read(AND / "ai/AiWriteService.kt"))
    chat = kt_code(read(AND / "ui/ai/AiChatScreen.kt"))

    # ---- ① 表从逐条卡渲染，批量卡带 table ----
    ok("fun sheet(items: List<AiPendingWrite>)" in table, "AiCardBatchTable.sheet 的入参不再是逐条 prepare 出来的卡")
    ok("AiCardTable.asPair(" in table, "表格不再复用 AiCardTable.asPair（会多出第二套「标签：值」判定）")
    ok("table = AiCardBatchTable.sheet(rows)" in batch, "BatchWriteHandler 造卡时没带长表格（又退回一张张弹）")
    ok("AiCardBatchTableSheet" in write, "AiPendingWrite 上没有 table 字段")

    # ---- ② 表格只影响显示 ----
    ok("putJsonArray(BATCH_PAYLOAD)" in batch, "批量 payload 不再是 _batch 数组（写下去的条数可能与表不一致了）")
    ok("const val BATCH_PAYLOAD = \"_batch\"" in batch, "BATCH_PAYLOAD 的键名被改过（与退货明细的 items 撞名的坑就在这）")

    # ---- ③ 有效期 ----
    ok("const val DEFAULT_TTL_MS: Long = 5 * 60 * 1000L" in write, "单条卡 5 分钟那个具名常量不见了")
    ok("const val BATCH_TTL_MS: Long = 30 * 60 * 1000L" in write, "批量卡 30 分钟那个具名常量不见了")
    ok("if (batch) batchTtlMs else ttlMs" in write, "造卡时没有按 batch 分支取有效期（批量卡会又只有 5 分钟）")
    m = re.search(r"BATCH_TTL_MS: Long = (\d+) \* (\d+) \* (\d+)L", write)
    d = re.search(r"DEFAULT_TTL_MS: Long = (\d+) \* (\d+) \* (\d+)L", write)
    ok(bool(m and d), "两个有效期常量不是「数 * 数 * 数L」的形状（判据没法比大小）")
    if m and d:
        b = int(m.group(1)) * int(m.group(2)) * int(m.group(3))
        s = int(d.group(1)) * int(d.group(2)) * int(d.group(3))
        ok(b > s, "批量卡的有效期不比单条卡长（用户踩过「一堆卡全过期」）")

    # ---- ④ 三句话分开说 ----
    ok("hasWritten(" in svc, "execute() 不再区分「已经写进去了」与「什么都没写」")
    ok("wasDropped(" in svc, "execute() 不再区分「被新卡顶掉」")
    ok("这张卡已经执行过了" in svc, "连点第二下不再承认执行过")
    ok("writtenNote(" in svc, "连点第二下不再带回上一次的逐行结果（失败行又被盖住了）")
    ok("这张卡过期了" in svc, "过期那一支没有说人话")
    ok("重新说一句我就再给你发一张" in svc, "过期那一支没给用户一条出路")
    ok("被新的一张顶掉了" in svc, "被顶掉那一支没说准是哪一种")
    # 「没写成」只许出现在真正的写失败那一支
    # ⚠️ 只锚**确认卡**那一句：AiWriteService 里另有一句「这个撤回入口已经失效了」（撤回窗口到期），
    #    那是另一件事、是正当的 —— 第一版按 "已经失效了" 抓会把它一起判红（假阳性）。
    bad = [ln for ln in svc.splitlines() if "确认卡" in ln and "失效" in ln]
    ok(not bad, "那句「这张确认卡已经失效了」又回来了：" + "；".join(bad)[:120])

    # ---- ⑤ 界面把表画出来 ----
    ok("BatchCardTable(" in chat, "聊天页没有画批量表的分支")
    ok("p.table" in chat, "聊天页不再读卡上的 table")
    ok("busyToken" in chat and "busyToken == p.token" in chat, "卡片上没有「点下即锁」的 busy 标记（连点会重复提交）")

    # ---- ⑥ 单测清单自己算 ----
    tsrc = read(AND_TEST / "AiBatchCardTest.kt")
    n = len(re.findall(r"^\s*@Test", tsrc, re.M))
    ok(n >= MIN_KT_TESTS, "AiBatchCardTest 只有 " + str(n) + " 个 @Test（下限 " + str(MIN_KT_TESTS) + "）")
    ok("AiCardBatchTable.MAX_ROWS" in tsrc, "单测没有再对表格行上限对账")

    ok(CHECKS >= 22, "断言只有 " + str(CHECKS) + " 条（下限 22）")

    if FAILS:
        print("❌ 批量长表格卡 / 连点幂等被破坏：")
        for f in FAILS:
            print("   - " + f)
        return 1
    print("✅ 批量长表格卡（CHG-0119）：" + str(CHECKS) + " 条断言全过 —— "
          "一张卡一张表（" + str(n) + " 例单测）、批量卡 30 分钟、连点/过期/被顶掉三句话分得开。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
