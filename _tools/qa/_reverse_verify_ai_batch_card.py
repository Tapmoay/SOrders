#!/usr/bin/env python
"""反向验证：把 CHG-0119（一张卡 + 一张长表格 + 连点幂等）一件一件弄坏，
_check_ai_batch_card.py 必须当场报红。

为什么非得有它：这一族**坏起来全是安静的** —— 把表格那一行删掉（又退回一张张弹）、
把批量卡的有效期改回 5 分钟、把「被顶掉」和「过期」合成一句、把连点标记摘掉……
**没有一条会报错**，用户看到的是"卡点不动了"和"我明明点了"。

⚠️ 注入点选在**判据真正读的地方**（那几行代码本身），不是"看起来相关"的地方。
每条注入跑完都**逐字节还原**，末尾再核对一遍。

R4-BOUNDARY-JUSTIFICATION: 这份脚本只改**卡的形状、有效期与回执口气**（Kotlin 的卡片渲染、
暂存区的有效期分支、execute() 那几句话、单测），不碰后端契约、订单/账本字段、权限模型。
它验证的判据本身也在同一层（"这张卡画成什么样、点第二下说什么"）；把这条边界下沉成
后端接口参数治不了它要防的病（病在**界面与回执**上，后端根本看不见）。

用法：python _tools/qa/_reverse_verify_ai_batch_card.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_ai_batch_card.py"

AI = "android/app/src/main/java/com/tapmoay/sorders/ai"
BATCH_REL = AI + "/AiWriteBatch.kt"
WRITE_REL = AI + "/AiWrite.kt"
SVC_REL = AI + "/AiWriteService.kt"
CHAT_REL = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatScreen.kt"
TEST_REL = "android/app/src/test/java/com/tapmoay/sorders/ai/AiBatchCardTest.kt"


def kill(s: str, old: str, n: int = 1) -> str:
    """删掉 old。找不到就当场抛 —— 静默跳过等于这条注入根本不存在。"""
    if s.count(old) < n:
        raise AssertionError("注入锚点找不到：" + old[:80])
    return s.replace(old, "", n)


CASES = [
    (
        "把批量卡上那张长表格删掉（40 条又变成一张张弹）",
        BATCH_REL,
        lambda s: kill(s, "            table = AiCardBatchTable.sheet(rows),\n"),
        "没带长表格",
    ),
    (
        "把批量卡的有效期从 30 分钟改回 3 分钟（用户踩过「卡还没点就过期」）",
        WRITE_REL,
        lambda s: s.replace("BATCH_TTL_MS: Long = 30 * 60 * 1000L", "BATCH_TTL_MS: Long = 3 * 60 * 1000L", 1),
        "批量卡的有效期不比单条卡长",
    ),
    (
        "造卡时不再按 batch 分支取有效期（批量卡会又只有 5 分钟）",
        WRITE_REL,
        lambda s: s.replace("expiresAtMs = at + if (batch) batchTtlMs else ttlMs", "expiresAtMs = at + ttlMs", 1),
        "没有按 batch 分支取有效期",
    ),
    (
        "把「已经写进去了」这个判断摘掉（连点第二下又会说「什么都没写」）",
        SVC_REL,
        lambda s: s.replace("hasWritten(", "wasWrittenBefore("),
        "不再区分「已经写进去了」与「什么都没写」",
    ),
    (
        "把「被新卡顶掉」那一支删掉（它会退化成「过期」，让用户去查一个不存在的有效期）",
        SVC_REL,
        lambda s: s.replace("wasDropped(", "wasDiscarded("),
        "不再区分「被新卡顶掉」",
    ),
    (
        "把过期那句话说回老话术（截图里那 4 条「没写成：这张确认卡已经失效了」）",
        SVC_REL,
        lambda s: s.replace("这张卡过期了", "这张确认卡已经失效了", 1),
        "已经失效了」又回来了",
    ),
    (
        "把卡片上的「点下即锁」标记摘掉（连点会重复提交）",
        CHAT_REL,
        lambda s: s.replace("busy = busyToken == p.token", "busy = false", 1),
        "没有「点下即锁」的 busy 标记",
    ),
    (
        "把批量卡的单测全注释掉（这一族再没有测试钉着）",
        TEST_REL,
        lambda s: s.replace("@Test", "// @Test"),
        "个 @Test（下限",
    ),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    print("== 0. 前提：源码完好时判据必须是绿的 ==")
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据就是红的 —— 先修绿再谈反向验证。")
        print(out[-3000:])
        return 2
    print("✅ 判据在完好源码上全绿")

    originals: dict[str, bytes] = {}
    ok = 0
    print("\n== 注入 %d 条：每条都必须让判据当场变红 ==" % len(CASES))
    try:
        for i, (label, rel, mutate, expect) in enumerate(CASES, 1):
            path = ROOT / rel
            original = originals.setdefault(rel, path.read_bytes())
            crlf = b"\r\n" in original
            text = original.decode("utf-8")
            mutated = mutate(text)
            if mutated == text:
                print("❌ [%d/%d] %s：注入没有改变任何字节（等于没注入）" % (i, len(CASES), label))
                return 1
            data = mutated.encode("utf-8")
            if crlf:
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            path.write_bytes(data)
            try:
                code2, out2 = run_check()
                hit = code2 != 0 and expect in out2
                print(("✅" if hit else "❌") + " [%d/%d] %s —— %s"
                      % (i, len(CASES), label,
                         "判据变红，且命中了那句话" if hit
                         else "判据没红 / 没命中那句话（exit=%d）" % code2))
                if not hit:
                    print(out2[-2500:])
                    return 1
                ok += 1
            finally:
                path.write_bytes(original)
    finally:
        for rel, original in originals.items():
            path = ROOT / rel
            if path.read_bytes() != original:
                path.write_bytes(original)
                print("⚠️  %s 没有逐字节还原，已强制还原" % rel)

    dirty = [rel for rel, original in originals.items() if (ROOT / rel).read_bytes() != original]
    print("\n逐字节还原核对：改了 %d 个文件，脏 = %d" % (len(originals), len(dirty)))
    if dirty or ok != len(CASES):
        print("❌ 反向验证不完整（通过 %d/%d）" % (ok, len(CASES)))
        return 1
    print("✅ 反向验证通过：%d/%d 条注入全部被抓，且源码逐字节还原。" % (ok, len(CASES)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
