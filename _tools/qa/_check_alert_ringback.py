# -*- coding: utf-8 -*-
"""重连（登录）回补里的新单要**补响**一声；系统通知要有声音、要震动 —— 台账 L-26（2026-10-06）。

## 用户口径（原话）
- m00846：「假如司机登录了账号，这时候有个订单派给他了，他就直接开始响铃……那个铃声要响的，
  不是不响」「系统通知的声音太小了」「我们要走系统的手机通知」「通知来的时候手机要震动一下，
  这个是要有的」。
- **m01132（更晚，冲突以它为准）**：① 登录／上线之后一直到有派单给他，就要响；
  ② 断网要分情况 —— 响过了就没必要、没响的话就要响；③ 「声音小」说的是**普通系统通知**那一条；
  ④ **所有通知都要震动**；⑤ 权限没开时要主动拦住并引导去开（那是 CHG-0056，不在本刀）。

## 机制：这一条的失败全是静默的
`sync` 回补分支里**没有** `announce(...)` 这件事，编译一样过、列表一样刷、通知栏一样有条目 ——
表现只有「人在车上没听见」。渠道那条更隐蔽：安卓的渠道**建过就改不动**
（`createNotificationChannels` 对已存在的 id 只更新名字与描述，声音／震动／importance 归用户在
系统设置里管）⇒ 想给「派单与新单」把震动补上、或让「消息」带上提示音，**只能换新的渠道 id**；
只改定义，在老用户机器上一动不动。

| 写坏的方式 | 表现 |
|---|---|
| 回补分支删掉 `ringback(...)` | 一条都不补响（用户报的那个 bug 原样回来） |
| 「已响过」不落盘 | 每次冷启动重连把断线期间那批单再响一遍 |
| `ringbackOf` 不看 `shouldStop` | 已经接掉 / 已撤回的单还在喊 |
| `ringbackOf` 不看落盘记录 | 响过的单再响（违背口径②） |
| 一次补响改成「全补」 | 十几段语音叠着响 |
| 渠道只改定义、不换 id | 老用户机器上仍然静音不振 |
| 消息渠道也设成 `setSound(null, null)` | 「声音太小」不但没解决，反而更小 |

## 这一刀动什么 / 不动什么
- **动**：`core/RealtimeHub.kt`（回补补响 ＋ 已响过落盘）、`core/NewOrderAlert.kt`（纯判定）、
  `core/AlertPrefs.kt`（`rungKeys`）、`core/NotifyCenter.kt`（两个新渠道 id，并改发到新 id）、
  `android/app/src/test/.../NewOrderAlertTest.kt`（新判定函数的单测）。
- **不动**：App 自己的语音（`NewOrderPlayer` 与它的 `voiceEnabled` 开关）、`BeepManager` 的短哔、
  提醒档位语义、权限引导（CHG-0056）、后端。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
本事项守的是一串**否定式**属性：「回补这条路上不许一声不响」「响过的**不许**再响」「不许把一批
全放出来」「渠道不许只改定义不换 id」。这些在类型系统里没有位置：`announce(...)` 少调一次不影响
编译（`announce` 是 private，没有调用者也不会报错）；`ringbackOf` 返回 `RingItem?`，多补几条
返回类型完全一样；渠道那几条 `apply { }` 全删掉，`ensureChannels()` 依旧编译、依旧被调用；
把 `NotifyChannels.ORDERS_ALERT` 写回 `ORDERS` 更是连一个字符的差别都看不出——
**老用户机器上的表现**才是唯一区别，而那要等真机上的新派单。
正向的边界（接口／分层／数据 Owner）在这里也使不上劲：这一刀不定义任何新的领域事实，也没有
一条写路径能被拦住——能拦住的只有源码结构本身：回补那段里有没有那一次调用、判定是不是只有一份、
渠道 id 是不是新的、发出去的是不是新 id。

用法：python _tools/qa/_check_alert_ringback.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 剥 Kotlin 注释只有一份实现（抄一份必踩同一个坑）
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CORE = AND / "core"
HUB = CORE / "RealtimeHub.kt"
ALERT = CORE / "NewOrderAlert.kt"
PREFS = CORE / "AlertPrefs.kt"
NOTIFY = CORE / "NotifyCenter.kt"
BEEP = CORE / "BeepManager.kt"
PLAYER = CORE / "NewOrderPlayer.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/NewOrderAlertTest.kt"
GUARD = ROOT / "_tools/ai/_check_notify_guardrails.py"
CHG = ROOT / "docs/changes/CHG-0055.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_alert_ringback.py"

#: 全仓至少要有这么多 .kt（防「目录被搬走 → 一个都没扫到 → 全绿」）。
MIN_KT = 100
#: 半角双引号：源码里字符串字面量的定界符。
DQ = chr(34)
#: 纯判定的 5 个新函数 —— 每一个都必须在单测里出现（`_tools/ai/_check_notify_guardrails.py` 第 10 节按源码数它们）。
NEW_FNS = ["rungDecode", "rungEncode", "rungTrim", "markRung", "ringbackOf"]
#: 回补候选（比 AlertEvent 更早一步：里面混着撤回/送达这些不该响的）。
RING_ITEM = "data class RingItem(val type: String, val orderId: Long?, val title: String)"
#: 补响判定（签名逐字）。
RINGBACK_OF = "fun ringbackOf(items: List<RingItem>, role: Role?, rung: Map<String, Long>): RingItem?"
CAND_ADD = "rungCandidates += RingItem(ntype, PushTrust.orderIdOf(m), title)"
BACK_CALL = "ringback(rungCandidates)"
DECODE_CALL = "NewOrderAlert.rungDecode(container.alertPrefs.rungKeys, now)"
ENCODE_WRITE = "container.alertPrefs.rungKeys = NewOrderAlert.rungEncode(seen)"
MARK_CALL = "markRung(ev.dedupeKey, now)"
FORGET_CALL = "forgetRungOnStop(type, orderId)"
VIB = "vibrationPattern = longArrayOf(0, 400, 200, 400, 200, 400)"
SOUND_NULL = "setSound(null, null)"
REQUIRED_FILES = [HUB, ALERT, PREFS, NOTIFY, BEEP, PLAYER, TEST, GUARD, CHG, README, CLAIM, REVERSE]


def read(p: Path) -> str:
    """读文本并**统一成 LF**（判据里有跨行锚点，CRLF 会让它们一处也匹配不上）。"""
    if not p.exists():
        return ""
    return io.open(p, encoding="utf-8", errors="replace", newline="").read().replace(chr(13) + chr(10), chr(10))


def code(p: Path) -> str:
    return strip_comments(read(p))


def between(text: str, a: str, b: str) -> str:
    """`a` 之后、`b` 之前的那一段（用来问「这句在不在这一段里」）。"""
    i = text.find(a)
    if i < 0:
        return ""
    j = text.find(b, i + len(a))
    return text[i : j if j >= 0 else len(text)]


def near(text: str, needle: str, after: int = 400) -> str:
    """`needle` 那一点往后的一段（用来问「紧跟它的是不是那几句」）。"""
    i = text.find(needle)
    if i < 0:
        return ""
    return text[i : i + after]


def hits(needle: str) -> list[tuple[str, int]]:
    """全仓 main 源码里 `needle` 的调用点清单（用来钉「只有这一处」）。"""
    out: list[tuple[str, int]] = []
    for p in sorted(AND.rglob("*.kt")):
        n = read(p).count(needle)
        if n:
            out.append((str(p.relative_to(AND)).replace(chr(92), "/"), n))
    return out


class Checker:
    def __init__(self) -> None:
        self.n_ok = 0
        self.fails: list[tuple[str, str]] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.n_ok += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append((label, detail))
            print(f"  [!!]   {label}")
            if detail:
                print(f"         {detail}")

    def absent(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle not in text, "不该出现却出现了 " + repr(needle))

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


def main() -> int:
    c = Checker()
    hub = code(HUB)
    alert = code(ALERT)
    prefs = code(PREFS)
    notify = code(NOTIFY)
    test = read(TEST)
    chg = read(CHG)
    reverse = read(REVERSE)

    c.section("① RealtimeHub：回补这条路上真的补响了（而且自动响铃只有一条入口）")
    c.ok("回补里先收候选（整批看完再决定补哪一条）", CAND_ADD in hub)
    c.ok("整批之后调用 ringback(...)", BACK_CALL in hub)
    adder = hub.find("rungCandidates += ")
    call = hub.find(BACK_CALL)
    c.ok("候选收集在补响之前（顺序不能倒）", 0 <= adder < call, "adder=" + str(adder) + " call=" + str(call))
    c.ok("回补仍然逐条补系统通知（没被这一刀拆掉）",
         "container.notifyCenter.postOrder(" in hub and "container.notifyCenter.postMessage(" in hub)
    c.ok("回补仍然推进游标（R14-13 不回归）", "bumpCursor(id)" in hub)
    body = near(hub, "private fun ringback(candidates: List<RingItem>) {", 800)
    c.ok("ringback 先读落盘的「已响过」", DECODE_CALL in body)
    c.ok("ringback 只试一条、拿到就交给 announce 这个唯一入口",
         re.search(r"val pick = NewOrderAlert\.ringbackOf\(candidates, role, rung\) \?: return[\s\S]{0,240}?announce\(pick\.type, pick\.orderId, pick\.title\)", body) is not None)
    c.ok("响过一条就落一次盘（写入点两处：响过 / 作废）", hub.count(ENCODE_WRITE) == 2, "n=" + str(hub.count(ENCODE_WRITE)))
    c.ok("announce 里记下「响过了」", MARK_CALL in hub)
    c.ok("announce 里同时作废盘上那条（撤回后重派还得响）", FORGET_CALL in hub)
    c.ok("自动响铃只有 announce 一处（设置页那 3 处是用户点的试听）",
         hits("container.newOrderPlayer.play(") == [("core/RealtimeHub.kt", 1), ("ui/profile/AlertSettingsScreen.kt", 3)],
         str(hits("container.newOrderPlayer.play(")))
    c.ok("ringbackOf 的调用点只有 RealtimeHub 一处",
         hits("NewOrderAlert.ringbackOf(") == [("core/RealtimeHub.kt", 1)], str(hits("NewOrderAlert.ringbackOf(")))

    c.section("② NewOrderAlert：纯判定（三条「不响」的规矩都在这里）")
    c.ok("回补候选的形状逐字", RING_ITEM in alert)
    c.ok("RingItem 全仓只此一处", hits("data class RingItem(") == [("core/NewOrderAlert.kt", 1)])
    c.ok("保留窗口是一天", "const val RUNG_KEEP_MS = 24 * 60 * 60 * 1000L" in alert)
    c.ok("条数上限是 64", "const val RUNG_MAX = 64" in alert)
    c.ok("补响判定的签名逐字", RINGBACK_OF in alert)
    pick = near(alert, RINGBACK_OF, 1800)
    c.ok("没有角色就没有该响的那一声（货主一句都不补）", "val kind = voiceKind(role) ?: return null" in pick)
    c.ok("从后往前找（列表是时间升序）", "items.indices.reversed()" in pick)
    c.ok("「该闭嘴了」的信号先记下来", "if (shouldStop(item.type)) {" in pick and "stopped +=" in pick)
    c.ok("已经结束的那一单不补", "in stopped) continue" in pick)
    c.ok("已经响过的那一单不补（口径②）", "rung.containsKey(ev.dedupeKey)" in pick)
    c.ok("一次只返回一条（其余只进通知栏）", pick.count("return item") == 1, "n=" + str(pick.count("return item")))
    c.ok("认不出的事件跳过（改单／送达这些不该响）", "eventOf(item.type, item.orderId, item.title) ?: continue" in pick)
    dec = near(alert, "fun rungDecode(raw: String?, now: Long)", 900)
    c.ok("坏行只丢不抛（少一条记录 = 多响一声）", "toLongOrNull() ?: return@forEach" in dec and "throw" not in alert)
    c.ok("读的时候就按窗口裁一次", "rungTrim(out, now)" in dec)
    trim = near(alert, "fun rungTrim(seen: MutableMap<String, Long>, now: Long) {", 500)
    c.ok("超窗的丢掉", "now - it.value > RUNG_KEEP_MS" in trim)
    c.ok("超量的只留最新那些", "sortedByDescending" in trim and "take(RUNG_MAX)" in trim)
    mark = near(alert, "fun markRung(seen: MutableMap<String, Long>, key: String, now: Long) {", 300)
    c.ok("记一条顺手裁一次", "seen[key] = now" in mark and "rungTrim(seen, now)" in mark)
    enc = near(alert, "fun rungEncode(seen: Map<String, Long>): String", 300)
    c.ok("写盘按时间升序（人肉看顺序与发生顺序一致）", "sortedBy { it.value }" in enc)

    c.section("③ AlertPrefs：跨进程的「已响过」落盘")
    c.ok("键名逐字", "const val RUNG = " + DQ + "rung_keys" + DQ in prefs)
    c.ok("有一个读写它的属性", "var rungKeys: String" in prefs)
    c.ok("读的默认值是空串（不是 null）", "sp.getString(Keys.RUNG, " + DQ + DQ + ") ?: " + DQ + DQ in prefs)
    c.ok("写是 apply（异步，不挡住收单）", "putString(Keys.RUNG, v).apply()" in prefs)
    c.ok("键名只在 AlertPrefs 里出现（别处不许绕过它直接读盘）",
         "Keys.RUNG" not in hub and "Keys.RUNG" not in notify)

    c.section("④ NotifyCenter：换新渠道 id 才能真正加上声音与震动")
    for name, value in [("ORDERS", "orders"), ("ORDERS_ALERT", "orders_alert"), ("MESSAGES", "messages"), ("MESSAGES_ALERT", "messages_alert"), ("SERVICE", "service")]:
        c.ok("渠道常量 " + name + " 逐字", "const val " + name + " = " + DQ + value + DQ in notify)
    # ⚠️ 只数 `object NotifyChannels { … }` 那一段：同一个文件里还有两个 Intent extra 常量
    #    （`EXTRA_ORDER_ID` / `EXTRA_NOTIFY_TOKEN`），拿整个文件去正则会数出 7 个。
    chan = between(notify, "object NotifyChannels {", "const val SERVICE_NOTIFICATION_ID")
    c.ok("渠道常量名与值都不带数字（红线判据按正则数它们）",
         len(re.findall(r"const val ([A-Z_]+) = " + DQ + "([a-z_]+)" + DQ, chan)) == 5,
         "n=" + str(len(re.findall(r"const val ([A-Z_]+) = " + DQ + "([a-z_]+)" + DQ, chan))))
    c.ok("派单通知发到新渠道", "NotificationCompat.Builder(context, NotifyChannels.ORDERS_ALERT)" in notify)
    c.ok("消息通知发到新渠道", "NotificationCompat.Builder(context, NotifyChannels.MESSAGES_ALERT)" in notify)
    c.absent("不再往旧派单渠道发", notify, "NotificationCompat.Builder(context, NotifyChannels.ORDERS)")
    c.absent("不再往旧消息渠道发", notify, "NotificationCompat.Builder(context, NotifyChannels.MESSAGES)")
    c.ok("五条渠道都还在建（旧的那两条只留定义、改名带（旧））",
         notify.count("NotificationChannel(") == 5, "n=" + str(notify.count("NotificationChannel(")))
    c.ok("旧派单渠道名字里带（旧）", DQ + "派单与新单（旧）" + DQ in notify)
    c.ok("旧消息渠道名字里带（旧）", DQ + "消息（旧）" + DQ in notify)
    ord_block = between(notify, "NotifyChannels.ORDERS_ALERT,", "NotifyChannels.MESSAGES,")
    c.ok("派单新渠道：横幅优先级 HIGH", "NotificationManager.IMPORTANCE_HIGH" in ord_block)
    c.ok("派单新渠道：震动 ＋ 图案", "enableVibration(true)" in ord_block and VIB in ord_block)
    c.ok("派单新渠道：仍然不出系统提示音（声音由 App 自己放，才停得下来）", SOUND_NULL in ord_block)
    msg_block = between(notify, "NotifyChannels.MESSAGES_ALERT,", "NotifyChannels.SERVICE,")
    c.ok("消息新渠道：抬到 HIGH（用户说的「声音太小」）", "NotificationManager.IMPORTANCE_HIGH" in msg_block)
    c.ok("消息新渠道：震动 ＋ 图案（口径④：所有通知都要震动）", "enableVibration(true)" in msg_block and VIB in msg_block)
    c.ok("消息新渠道：不设 setSound ⇒ 用系统默认提示音", "setSound" not in msg_block)
    c.ok("前台服务那条没被碰（名字 ＋ 最低优先级）",
         DQ + "后台接收消息" + DQ in notify and "NotificationManager.IMPORTANCE_MIN" in notify)

    c.section("⑤ 这一刀没碰别人的东西")
    c.ok("App 自己的语音开关还在（补响尊重它）", "prefs.voiceEnabled" in code(PLAYER))
    c.ok("既有的语音判定与去重没被改",
         "NewOrderAlert.speaks(role, ev.kind)" in hub and "NewOrderAlert.isDuplicate(announced, ev.dedupeKey, now)" in hub)
    c.ok("短哔没被顺手改（本刀明确不做：用户说的是普通系统通知，改它要等他点名）",
         "ToneGenerator(AudioManager.STREAM_NOTIFICATION, 60)" in code(BEEP))
    c.ok("提醒档位语义没改（还是那一个 repeatTimes）", "repeatTimes" in hub)

    c.section("⑥ 单测与既有红线随动")
    for fn in NEW_FNS:
        c.ok("单测里测了 " + fn, fn in test)
    c.ok("单测还是测试（@Test 数量 >= 15）", test.count("@Test") >= 15, "n=" + str(test.count("@Test")))
    # ⚠️ 判据脚本里存的是正则转义形式（`canPost\(\)`），按原样找会一条也匹配不上。
    c.ok("notify 红线判据仍在（渠道这条红线没被绕过）", GUARD.exists() and "canPost" in read(GUARD))

    c.section("⑦ 防空转")
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED_FILES if not p.exists()]
    c.ok("该在的文件都在", not missing, "缺：" + str(missing))
    kt = len(list(AND.rglob("*.kt")))
    c.ok(".kt 数量 >= " + str(MIN_KT) + "（路径写错就不会静默全绿）", kt >= MIN_KT, "n=" + str(kt))

    c.section("⑧ 文档（CHG-0055 ／ README ／ CLAIM ／ 反验）")
    c.ok("CHG-0055.md 在且写够了", len(chg) > 500, "len=" + str(len(chg)))
    for token in ["L-26", "m00846", "m01132", "orders_alert", "已响过", "震动"]:
        c.ok("CHG-0055.md 写了「" + token + "」", token in chg)
    c.ok("CHG-0055.md 的 Boundary 结论逐字（CORE ＋ 平台一次性语义）",
         "- **结论**：**CORE（回补路径的播报判定）＋ INFRASTRUCTURE（通知渠道 id 的一次性语义）**，Blast Radius **L1**" in chg)
    c.ok("README 里登记了 CHG-0055", "[CHG-0055.md](CHG-0055.md)" in read(README))
    c.ok("AI_WORK_CLAIM 里认领了 CHG-0055", "CHG-0055" in read(CLAIM))
    c.ok("反验脚本在、注入够多（>=14 条）", REVERSE.exists() and reverse.count(chr(10) + "    (" + chr(10)) >= 14,
         "n=" + str(reverse.count(chr(10) + "    (" + chr(10))))

    print("\n" + "=" * 60)
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项不通过：")
        for label, detail in c.fails:
            print("   - " + label + (" —— " + detail if detail else ""))
        return 1
    print("✅ 全部 " + str(c.n_ok) + " 项通过：重连回补要补响 ＋ 系统通知有声音、有震动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
