# -*- coding: utf-8 -*-
"""反向验证：`_tools/qa/_check_alert_ringback.py` 的每一条判据都**真的会红** —— 台账 L-26（CHG-0055）。

## 为什么要有这一份
这一刀守的全是**静默失效**：回补那条分支里少调一次 `announce(...)`（编译照过、列表照刷、通知栏照样有条目，
只是人在车上没听见）、「已响过」忘了落盘（每次冷启动重连再响一遍）、渠道只改了定义却没换 id
（老用户机器上一点都不变）。判据脚本写得再细，只要它自己坏了（锚点漂了、正则写宽了、切段切到文件尾），
它**照样全绿** —— 所以这里逐条把源码改坏一次，要求判据必须报红。

## 手法
- 每条：快照原文件（**按字节**）→ 字符串替换一次 → 跑判据 → 期望某条**具体**的判据变红 → 按字节还原。
- 还原之后**重新读回来逐字节比对**；不一致直接 `SystemExit(2)`（一次没还原，后面所有结论都建立在坏代码上）。
- ⛔ 全程不碰 git 的还原命令：那会把工作区里**别人**的改动一起吞掉。
- 锚点是源码片段，会随源码漂：漂了这里打 `[SKIP]`（`exit 1`），**不装成绿**。

用法：python _tools/qa/_reverse_verify_alert_ringback.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_alert_ringback.py"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
HUB = AND / "core/RealtimeHub.kt"
ALERT = AND / "core/NewOrderAlert.kt"
PREFS = AND / "core/AlertPrefs.kt"
NOTIFY = AND / "core/NotifyCenter.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/NewOrderAlertTest.kt"
CHG = ROOT / "docs/changes/CHG-0055.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: (说明, 文件, 原文, 替换成, 期望变红的那条判据里的关键词)
MUTATIONS = [
    (
        "回补那条分支干脆不补响了（用户报的那个 bug 原样回来）",
        HUB,
        "ringback(rungCandidates)",
        "ringbackGone(rungCandidates)",
        "整批之后调用 ringback(...)",
    ),
    (
        "回补里不再收候选（补响判定拿不到任何东西）",
        HUB,
        "rungCandidates += RingItem(ntype, PushTrust.orderIdOf(m), title)",
        "val skipOne = RingItem(ntype, PushTrust.orderIdOf(m), title)",
        "回补里先收候选（整批看完再决定补哪一条）",
    ),
    (
        "候选还没看完就先补响（只补最新一条这条口径失效）",
        HUB,
        "rungCandidates += RingItem(ntype, PushTrust.orderIdOf(m), title)",
        "ringback(rungCandidates)\n                        rungCandidates += RingItem(ntype, PushTrust.orderIdOf(m), title)",
        "候选收集在补响之前（顺序不能倒）",
    ),
    (
        "响过了却不记（冷启动重连会把断线那批单再响一遍）",
        HUB,
        "markRung(ev.dedupeKey, now)",
        "markRungX(ev.dedupeKey, now)",
        "announce 里记下「响过了」",
    ),
    (
        "撤回/接单之后不作废盘上那条（撤离后重派给同一个司机会被吞掉）",
        HUB,
        "forgetRungOnStop(type, orderId)",
        "forgetRungOnStopX(type, orderId)",
        "announce 里同时作废盘上那条（撤回后重派还得响）",
    ),
    (
        "「已响过」读了却不写盘（跨进程那条口径落空）",
        HUB,
        "container.alertPrefs.rungKeys = NewOrderAlert.rungEncode(seen)",
        "container.alertPrefs.rungKeys = seen.toString()",
        "响过一条就落一次盘（写入点两处：响过 / 作废）",
    ),
    (
        "ringback 自己判一遍却不交给唯一入口（两处口径迟早会漂）",
        HUB,
        "val pick = NewOrderAlert.ringbackOf(candidates, role, rung) ?: return",
        "val pick = NewOrderAlert.ringbackOf(candidates, role, rung)",
        "ringback 只试一条、拿到就交给 announce 这个唯一入口",
    ),
    (
        "补响前不读落盘的「已响过」（响过的单还会再响）",
        HUB,
        "NewOrderAlert.rungDecode(container.alertPrefs.rungKeys, now)",
        "emptyMap()",
        "ringback 先读落盘的「已响过」",
    ),
    (
        "补响这条路上多出第二个播放入口（自动响铃不再只有 announce）",
        HUB,
        "private fun ringback(candidates: List<RingItem>) {",
        "private fun ringback(candidates: List<RingItem>) {\n        container.newOrderPlayer.play(",
        "自动响铃只有 announce 一处（设置页那 3 处是用户点的试听）",
    ),
    (
        "已经响过的那一单照样补（违背「响过了就没必要」）",
        ALERT,
        "rung.containsKey(ev.dedupeKey)",
        "false",
        "已经响过的那一单不补（口径②）",
    ),
    (
        "不再认「该闭嘴了」的信号（已经接掉/撤回的单还在喊）",
        ALERT,
        "if (shouldStop(item.type)) {",
        "if (false) {",
        "「该闭嘴了」的信号先记下来",
    ),
    (
        "已经结束的那一单也补响（错过的活没了还在喊）",
        ALERT,
        "if (item.orderId != null && item.orderId in stopped) continue",
        "if (false) continue",
        "已经结束的那一单不补",
    ),
    (
        "从前往后找（补的是最旧那条，不是最新那条）",
        ALERT,
        "for (i in items.indices.reversed()) {",
        "for (i in items.indices) {",
        "从后往前找（列表是时间升序）",
    ),
    (
        "货主也要补响（他根本没有那一句语音）",
        ALERT,
        "val kind = voiceKind(role) ?: return null",
        "val kind = voiceKind(role)",
        "没有角色就没有该响的那一声（货主一句都不补）",
    ),
    (
        "记录里的坏行直接崩（读失败会让新单不响）",
        ALERT,
        "val at = part.substring(cut + 1).toLongOrNull() ?: return@forEach",
        "val at = part.substring(cut + 1).toLong()",
        "坏行只丢不抛（少一条记录 = 多响一声）",
    ),
    (
        "读的时候不按窗口裁（越攒越长）",
        ALERT,
        "        rungTrim(out, now)\n",
        "",
        "读的时候就按窗口裁一次",
    ),
    (
        "超窗的已响过记录不丢（一整天前的单还会被吞掉）",
        ALERT,
        "now - it.value > RUNG_KEEP_MS",
        "false",
        "超窗的丢掉",
    ),
    (
        "条数上限不生效（那份记录会一直长）",
        ALERT,
        "take(RUNG_MAX)",
        "take(RUNG_MAX + 1000)",
        "超量的只留最新那些",
    ),
    (
        "记一条不写时间（窗口判定全废）",
        ALERT,
        "seen[key] = now",
        "seen[key] = 0L",
        "记一条顺手裁一次",
    ),
    (
        "落盘的键名被改掉（旧记录读不回来）",
        PREFS,
        'const val RUNG = "rung_keys"',
        'const val RUNG = "rung_key"',
        "键名逐字",
    ),
    (
        "写盘改成同步 commit（挡住收单这条线程）",
        PREFS,
        "putString(Keys.RUNG, v).apply()",
        "putString(Keys.RUNG, v).commit()",
        "写是 apply（异步，不挡住收单）",
    ),
    (
        "派单通知仍发到旧渠道（老用户机器上还是不振）",
        NOTIFY,
        "NotificationCompat.Builder(context, NotifyChannels.ORDERS_ALERT)",
        "NotificationCompat.Builder(context, NotifyChannels.ORDERS)",
        "派单通知发到新渠道",
    ),
    (
        "消息新渠道的常量值写成旧的（两个 id 撞在一起）",
        NOTIFY,
        'const val MESSAGES_ALERT = "messages_alert"',
        'const val MESSAGES_ALERT = "messages"',
        "渠道常量 MESSAGES_ALERT 逐字",
    ),
    (
        "消息渠道也设成 setSound(null)（「声音太小」反而更小）",
        NOTIFY,
        "NotifyChannels.MESSAGES_ALERT,",
        "NotifyChannels.MESSAGES_ALERT,\n                    setSound(null, null),",
        "消息新渠道：不设 setSound ⇒ 用系统默认提示音",
    ),
    (
        "派单新渠道不震动了（口径④：所有通知都要震动）",
        NOTIFY,
        "                    setSound(null, null)\n                    enableVibration(true)",
        "                    setSound(null, null)",
        "派单新渠道：震动 ＋ 图案",
    ),
    (
        "消息新渠道没抬优先级（用户说的「声音太小」没解决）",
        NOTIFY,
        "                    " + chr(34) + "消息" + chr(34) + ",\n                    NotificationManager.IMPORTANCE_HIGH,",
        "                    " + chr(34) + "消息" + chr(34) + ",\n                    NotificationManager.IMPORTANCE_DEFAULT,",
        "消息新渠道：抬到 HIGH（用户说的「声音太小」）",
    ),
    (
        "判据自己对震动图案写错（这一条本身是假的）",
        CHECK,
        "VIB = " + chr(34) + "vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)" + chr(34),
        "VIB = " + chr(34) + "vibrationPattern = longArrayOf(0, 200, 200)" + chr(34),
        "派单新渠道：震动 ＋ 图案",
    ),
    (
        "新判定函数没有单测（红线判据本来会拦住这一条）",
        TEST,
        "rungTrim",
        "trimRung",
        "单测里测了 rungTrim",
    ),
    (
        "CHG 的 Boundary 结论降级成只写 CORE（平台那条一次性语义被抹掉）",
        CHG,
        "- **结论**：**CORE（回补路径的播报判定）＋ INFRASTRUCTURE（通知渠道 id 的一次性语义）**，Blast Radius **L1**",
        "- **结论**：**CORE**",
        "CHG-0055.md 的 Boundary 结论逐字（CORE ＋ 平台一次性语义）",
    ),
    (
        "CHG 里不提「已响过」这件事（口径②丢了）",
        CHG,
        "已响过",
        "已播过",
        "CHG-0055.md 写了「已响过」",
    ),
    (
        "README 里的链接写死（点进去 404）",
        README,
        "[CHG-0055.md](CHG-0055.md)",
        "[CHG-0055.md](CHG-0055-gone.md)",
        "README 里登记了 CHG-0055",
    ),
    (
        "AI_WORK_CLAIM 里的编号写错（认领不到）",
        CLAIM,
        "CHG-0055",
        "CHG-55",
        "AI_WORK_CLAIM 里认领了 CHG-0055",
    ),
]


def snapshot(p: Path) -> bytes:
    """按**字节**快照（不是按文本：文本层归一过行尾，写回去就变了一次格式）。"""
    return p.read_bytes()


def mutate(p: Path, old: str, new: str) -> int:
    """把 `old` 换成 `new`，返回换了几处（0 = 锚点漂了）。

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
    files = [HUB, ALERT, PREFS, NOTIFY, TEST, CHECK, CHG, README, CLAIM]
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
    print("\n还原：9 个文件都按字节比对一致，判据重新全绿 ✅")
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
