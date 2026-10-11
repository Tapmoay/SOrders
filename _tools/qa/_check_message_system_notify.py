#!/usr/bin/env python
"""消息中心的消息在「软件外」也弹系统通知栏 —— FEAT-0027 的机器判据。

## 用户口径（2026-10-11 逐字）
「我们这个消息中心……**它不止只有在这个软件才会有** —— 我们的**手机系统消息它也会弹一个消息窗**，
就像普通的手机那个软件一样。你光在自己软件里谈消息没什么用的，有时候你要**在软件外**谈消息。」

## 盯住六件事（每条都对应一种"真机上完全看不出来"的坏法）
1. **severity → 重要性**：danger ⇒ HIGH、warn ⇒ DEFAULT、info ⇒ LOW。渠道是**一次性**的
   （改 importance 对老机器无效）⇒ 分档只能各用一条新渠道 id；写成同一个渠道 = 分档名存实亡。
2. **按通知 id 去重**：同一条站内信会从 socket 实时与重连回补**两条链**各到一次，
   不去重就弹两格；记录还必须**落盘**（进程重启后 sync 会把那一批再补一遍）。
3. **App 在前台不弹**：界面里本来就会刷新，再弹一条就是重复打扰。
4. **跟随「消息进通知栏」开关**：关掉只掐系统通知 —— ⛔ 消息本身一条都不许丢。
5. **多条合并成一条摘要**：一次每日扫描同时发 N 条，逐条弹就是刷屏；1 条仍单发。
6. **深链复用同一份路由**：点通知去的那一页必须与消息中心里点这张卡**同源**
   （`ui/messages/MessageGrading.kt::noticeRoute`），⛔ 不许在通知这条链上再写一套 `when (type)`。

为什么这些必须由机器盯着：它们全是"顺手改一下"就散、而且**失败完全静默**的形态 ——
少弹一次（用户没看见库存不足）、弹两次、点通知去了空列表或 403、一次来 10 条刷屏，
四种都不报错、日志里也看不出来，只有"用户那头没收到 / 收到了两条"这一种表现。

R4-BOUNDARY-JUSTIFICATION: 本判据**不下沉到任何一层边界**。被查的全是"同一条已经在库里的消息，
在客户端还应该发生什么"：Importance 是 Android 渠道的属性（服务端看不见）、去重记录是本机
SharedPreferences、前台与否是本机进程状态、摘要窗口是客户端聚合策略、深链是客户端路由。
后端契约、领域类型、数据库约束里都没有它们的位置 —— 服务端照样只发一条 `notification`，
客户端弹几次、弹多响、点去哪一页，一个字节都不进库。

用法：python _tools/qa/_check_message_system_notify.py     （--list 打一份人读清单）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 剥 Kotlin 注释只有一份实现（抄一份必踩同一个坑）—— 与 `_check_alert_ringback.py` 同一份
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CORE = AND / "core"
NOTIFY = CORE / "NotifyCenter.kt"
MSG = CORE / "MessageNotify.kt"
PREFS = CORE / "AlertPrefs.kt"
TRUST = CORE / "PushTrust.kt"
FG = CORE / "AppForeground.kt"
HUB = CORE / "RealtimeHub.kt"
ALERT = CORE / "NewOrderAlert.kt"
PLAYER = CORE / "NewOrderPlayer.kt"
ACT = AND / "MainActivity.kt"
APP = AND / "SOrdersApp.kt"
CONTAINER = CORE / "AppContainer.kt"
NAV = AND / "ui/nav/NavGraph.kt"
SETTINGS = AND / "ui/profile/AlertSettingsScreen.kt"
GRADING = AND / "ui/messages/MessageGrading.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/MessageNotifyTest.kt"
DOC = ROOT / "docs/changes/FEAT-0027.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_message_system_notify.py"

#: 全仓至少要有这么多 .kt（防「目录被搬走 → 一个都没扫到 → 全绿」）
MIN_KT = 100
#: 半角双引号：源码里字符串字面量的定界符
DQ = chr(34)
#: postMessage 改过的签名的头一行（判「新参数真的在」）
SIGNATURE = "fun postMessage("
#: 纯判定里必须被单测点名的那些（清单从源码数，见 §9）
REQUIRED_TESTED = [
    "riskOfSeverity", "channelOf", "shouldPost", "isDuplicate", "decodeSeen", "encodeSeen",
    "markSeen", "trimSeen", "plan", "highest", "preview", "routeOf", "payloadOf", "payloadExtras",
    "summaryBody",
]
REQUIRED_FILES = [NOTIFY, MSG, PREFS, TRUST, FG, HUB, ACT, APP, CONTAINER, NAV, SETTINGS, TEST, DOC, REVERSE]


def read(path: Path) -> str:
    """读文本并统一成 LF（判据里有跨行锚点，CRLF 会让它们一处也匹配不上）。"""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").replace(chr(13) + chr(10), chr(10))


def code(path: Path) -> str:
    return strip_comments(read(path))


def between(text: str, a: str, b: str) -> str:
    i = text.find(a)
    if i < 0:
        return ""
    j = text.find(b, i + len(a))
    return text[i: j if j >= 0 else len(text)]


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
            print(f"  [FAIL] {label}")
            if detail:
                print(f"         {detail}")

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


def main() -> int:
    notify = code(NOTIFY)
    msg = code(MSG)
    prefs = code(PREFS)
    trust = code(TRUST)
    fg = code(FG)
    hub = code(HUB)
    act = code(ACT)
    app = code(APP)
    container = code(CONTAINER)
    nav = code(NAV)
    settings = code(SETTINGS)
    grading = code(GRADING)
    test = read(TEST)
    doc = read(DOC)
    readme = read(README)
    claim = read(CLAIM)
    reverse = read(REVERSE)
    kts = sorted(AND.rglob("*.kt"))

    c = Checker()
    print("消息中心的消息在「软件外」也弹系统通知栏（FEAT-0027）")

    c.section("零、反空转（少一个文件，下面每一条都可能是空转）")
    missing = [str(x.relative_to(ROOT)) for x in REQUIRED_FILES if not x.exists()]
    c.ok("该在的文件都在", not missing, "缺：" + str(missing))
    c.ok(f"扫到 ≥{MIN_KT} 个主源码 .kt", len(kts) >= MIN_KT, f"实测 {len(kts)} 个")
    chan = between(notify, "object NotifyChannels {", "const val SERVICE_NOTIFICATION_ID")
    consts = dict(re.findall(r"const val ([A-Z_]+) = " + DQ + "([a-z_]+)" + DQ, chan))
    c.ok("渠道清单是从 object NotifyChannels 里数出来的（≥5 条）", len(consts) >= 5, "n=" + str(len(consts)))

    c.section("一、severity → 重要性：三档各有自己的渠道")
    c.ok(
        "severity 的解析复用唯一那一处（riskOf，不写第二份）",
        "fun riskOfSeverity(severity: String?): MessageRisk = riskOf(severity)" in msg,
    )
    c.ok(
        "severity → 重要性分档：danger/warn/info 各指一条渠道",
        "MessageRisk.DANGER -> NotifyChannels.MESSAGES_ALERT" in msg
        and "MessageRisk.WARN -> NotifyChannels.MESSAGES_WARN" in msg
        and "MessageRisk.INFO -> NotifyChannels.MESSAGES_INFO" in msg,
        "channelOf 的三支没写全 = 有一档会落到别的档上",
    )
    c.ok(
        "三条渠道的 id 互不相同（写成同一个 = 分档名存实亡）",
        len({consts.get("MESSAGES_ALERT"), consts.get("MESSAGES_WARN"), consts.get("MESSAGES_INFO")}) == 3,
        str({k: consts.get(k) for k in ("MESSAGES_ALERT", "MESSAGES_WARN", "MESSAGES_INFO")}),
    )
    c.ok(
        "danger 那一档是 HIGH（沿用「消息」那条，有横幅有提示音）",
        re.search(r"NotificationChannel\(\s*NotifyChannels\.MESSAGES_ALERT[\s\S]{0,140}?IMPORTANCE_HIGH", notify) is not None,
    )
    c.ok(
        "warn 那一档是 DEFAULT",
        re.search(r"NotificationChannel\(\s*NotifyChannels\.MESSAGES_WARN[\s\S]{0,140}?IMPORTANCE_DEFAULT", notify) is not None,
    )
    c.ok(
        "info 那一档是 LOW（安静那一档不许抬成 HIGH）",
        re.search(r"NotificationChannel\(\s*NotifyChannels\.MESSAGES_INFO[\s\S]{0,140}?IMPORTANCE_LOW", notify) is not None,
    )
    c.ok(
        "消息通知的渠道来自唯一映射处（不是写死一条）",
        "NotificationCompat.Builder(context, MessageNotify.channelOf(" in notify,
    )
    c.ok(
        "⛔ 消息不许发到司机新单那条渠道（那一条要语音、要横幅）",
        notify.count("NotificationCompat.Builder(context, NotifyChannels.ORDERS_ALERT)") == 1,
        "n=" + str(notify.count("NotificationCompat.Builder(context, NotifyChannels.ORDERS_ALERT)")),
    )

    c.section("二、按通知 id 去重（两条链各来一次时只弹一条）")
    c.ok(
        "同一条通知（按 id）只弹一次：判定在纯函数里",
        "fun isDuplicate(seen: Map<Long, Long>, id: Long)" in msg
        and "if (isDuplicate(seen, id)) return false" in msg,
    )
    c.ok(
        "弹之前先按 id 查重（去掉这一句就会弹两条）",
        "MessageNotify.shouldPost(" in notify and "seen = seen," in notify,
    )
    c.ok(
        "「已弹过」跨进程落盘（只存内存 = 重启后整批重弹）",
        "var seenMessageIds: String" in prefs
        and "prefs.seenMessageIds = MessageNotify.encodeSeen(seen)" in notify
        and "MessageNotify.decodeSeen(prefs.seenMessageIds, now)" in notify,
        "键名只在 AlertPrefs（别处绕过它直接读盘）",
    )
    c.ok(
        "去重键名只在 AlertPrefs 里出现（Keys.MESSAGE_SEEN 不许外泄）",
        "const val MESSAGE_SEEN = " + DQ + "message_seen_ids" + DQ in prefs
        and "Keys.MESSAGE_SEEN" not in notify and "Keys.MESSAGE_SEEN" not in hub,
    )
    i_dec = notify.find("MessageNotify.decodeSeen(prefs.seenMessageIds, now)")
    i_ded = notify.find("MessageNotify.shouldPost(")
    i_mark = notify.find("MessageNotify.markSeen(seen, notificationId, now)")
    c.ok(
        "顺序：先读盘 → 查重 → 记「弹过了」（倒过来 = 第二条链先写再判，照样弹两条）",
        0 <= i_dec < i_ded < i_mark,
        " ".join(str(x) for x in (i_dec, i_ded, i_mark)),
    )

    c.section("三、App 在前台时不弹")
    c.ok(
        "App 在前台时不弹（前台判定只有一处实现）",
        "foreground = AppForeground.visible" in notify and "if (foreground) return false" in msg,
    )
    c.ok(
        "前台判定就是 Activity 生命周期计数（不需要新依赖）",
        "object AppForeground {" in fg
        and "val visible: Boolean get() = started > 0" in fg
        and "override fun onActivityStarted" in fg
        and "override fun onActivityStopped" in fg
        and "if (started > 0) started -= 1" in fg,
        "减到负数 = 前台判断永远为真（表现只是「消息不弹了」）",
    )
    c.ok("Application 里装一次（冷启动就有）", "AppForeground.install(this)" in app)

    c.section("四、跟随「消息进通知栏」开关（关掉只不弹，消息一条不丢）")
    c.ok(
        "开关默认开、读写只有一处（AlertPrefs）",
        "const val MESSAGE_NOTIFY = " + DQ + "message_notify" + DQ in prefs
        and "var messageNotifyEnabled: Boolean" in prefs
        and "get() = sp.getBoolean(Keys.MESSAGE_NOTIFY, true)" in prefs,
    )
    c.ok(
        "跟随「消息进通知栏」开关：发通知前问它",
        "enabled = prefs.messageNotifyEnabled," in notify,
    )
    c.ok(
        "设置页有这一行，并写清关掉之后消息照收",
        "title = " + DQ + "消息进通知栏" + DQ in settings
        and "关掉后站内消息照常收" in settings
        and "prefs.messageNotifyEnabled = it" in settings,
    )
    c.ok(
        "不弹 ≠ 丢掉：消息本身那条链照旧（未读数与刷新都在）",
        "绝不等于把消息丢掉" in read(MSG)   # ⚠️ 这句在 KDoc 里：strip_comments 会把它剥掉，必须读原文
        and "_newMessages.tryEmit(Unit)" in hub
        and "_unreadCount.value += 1" in hub,
    )

    c.section("五、多条合并成一条摘要（别刷屏）")
    c.ok(
        "多条合并成一条摘要：阈值与文案都是常量",
        "const val SUMMARY_MIN = 2" in msg
        and "const val SUMMARY_WINDOW_MS = 1500L" in msg
        and "fun summaryBody(count: Int): String" in msg
        and "is MessageBatch.Summary -> notify(SUMMARY_NOTIFICATION_ID" in notify
        and "else -> MessageBatch.Summary(count = pending.size, risk = highest(" in msg,
    )
    c.ok(
        "单条仍然单发（不为了一条消息也发摘要）",
        "is MessageBatch.Single -> notify(messageIdOf(" in notify,
    )
    c.ok(
        "摘要点它进消息中心（那一批一条都没少）",
        "putExtra(EXTRA_MESSAGE_ROUTE, Routes.MESSAGES)" in notify,
    )
    c.ok(
        "摘要固定占一格（反复覆盖自己，不刷屏）",
        "const val SUMMARY_NOTIFICATION_ID = 9300" in notify,
    )
    c.ok(
        "窗口从首条起算一次（顺延会把摘要无限往后推）",
        "if (first) {" in notify and "delay(MessageNotify.SUMMARY_WINDOW_MS)" in notify,
    )

    c.section("六、深链：点通知去的那一页与 App 内**同源**")
    c.ok(
        "复用同一份路由：routeOf 的函数体只有一句转发",
        re.search(r"fun routeOf\(roleKey: String\?, type: String, payload: Map<String, JsonElement>\?\): String\? = noticeRoute\(", msg) is not None,
    )
    c.ok(
        "⛔ core 里没有第二套路由映射（不许自己拼页面）",
        "Routes.orderDetail(" not in msg and "Routes.orderDetail(" not in notify and "Routes.orderDetail(" not in hub
        and "Routes.inventory(" not in msg and "Routes.inventory(" not in notify,
    )
    c.ok(
        "深链 extras：route ＋ 通知 id ＋ type ＋ payload 键（order_id / product_id …）",
        "putExtra(EXTRA_MESSAGE_ROUTE, m.route)" in notify
        and "putExtra(EXTRA_MESSAGE_ID, m.id)" in notify
        and "putExtra(EXTRA_MESSAGE_TYPE, m.type)" in notify
        and "MessageNotify.payloadExtras(m.payload).forEach" in notify
        and "const val EXTRA_MESSAGE_ROUTE = " + DQ + "sorders_message_route" + DQ in notify,
    )
    c.ok(
        "深链走与单号**同一道凭据关**（外部可伪造的 extra 不算凭据）",
        "fun trustedRoute(route: String?, token: String?, mine: String?)" in trust
        and "const val MAX_ROUTE_LEN = 200" in trust,
    )
    c.ok(
        "MainActivity 采信后才交给容器（对不上整条忽略）",
        "PushTrust.trustedRoute(" in act and "container.pendingRoute.value = route" in act,
    )
    c.ok(
        "深链先进容器再由 AppRoot 消费（冷启动时 Activity 还没建好）",
        "val pendingRoute = MutableStateFlow<String?>(null)" in container
        and "container.pendingRoute.collectAsState()" in nav
        and "navController.navigate(r)" in nav,
    )

    c.section("七、两条投递链都接上（回补那条最容易漏）")
    c.ok(
        "回补链与实时链都走同一个出口",
        "postNotice(m, id, title, content)" in hub and "postNotice(n, id, title, content)" in hub,
    )
    c.ok(
        "两条链都带上 severity / type / payload / 角色原文",
        "severity = map?.get(" + DQ + "severity" + DQ + ") as? String" in hub
        and "payload = MessageNotify.payloadOf(map?.get(" + DQ + "payload" + DQ + ") as? Map<*, *>)" in hub
        and "roleKey = roleKey," in hub
        and "roleKey = s.role" in hub,
    )
    c.ok(
        "socket 的 payload 先归一（否则点通知算不出与 App 内一致的路由）",
        "fun payloadOf(raw: Map<*, *>?): Map<String, JsonElement>?" in msg,
    )

    c.section("八、与司机新单那条链不打架")
    c.ok(
        "司机那条链不认识消息这一套（一个字节都没被改）",
        "MessageNotify" not in code(ALERT) and "MessageNotify" not in code(PLAYER),
    )
    c.ok(
        "消息出口里不出现司机的渠道与语音",
        "newOrderPlayer" not in notify and "NewOrderAlert" not in notify,
    )
    c.ok(
        "司机新单的红线判据仍在（渠道那条红线没被绕过）",
        (ROOT / "_tools/ai/_check_notify_guardrails.py").exists(),
    )

    c.section("九、单测钉着纯判定的每一件")
    n_tests = test.count("@Test")
    c.ok("单测存在且 ≥8 例", n_tests >= 8, "n=" + str(n_tests))
    fns = re.findall(r"(?<!private )fun (\w+)\(", msg)
    untested = [f for f in fns if f not in test]
    c.ok(
        "纯判定里的每个 public fun 都被单测点到（清单从源码数，不是手写）",
        not untested,
        "没被点到的：" + str(untested),
    )
    c.ok(
        "单测点到了路线一致性（拿 noticeRoute 逐条比对）",
        "noticeRoute(role, type, pl)" in test and "MessageNotify.routeOf(role, type, pl)" in test,
    )
    c.ok(
        "单测点到了四个「不弹」的理由",
        "foreground = true" in test and "enabled = false" in test and "allowed = false" in test
        and "MessageNotify.isDuplicate(seen, 88L)" in test,
    )

    c.section("十、文档与登记")
    c.ok("改动文档在（docs/changes/FEAT-0027.md）", len(doc) > 1500 and "FEAT-0027" in doc)
    c.ok(
        "九节齐全（①–⑨）",
        all(x in doc for x in ("## ① 六问", "## ②", "## ③", "## ④", "## ⑤", "## ⑥", "## ⑦", "## ⑧", "## ⑨")),
    )
    c.ok(
        "文档写清了用户口径（软件外也要收得到）",
        "软件外" in doc and "系统通知" in doc,
    )
    c.ok("改动登记表里有 FEAT-0027 行", "| `FEAT-0027` |" in readme, "docs/changes/README.md")
    c.ok("认领簿里有 FEAT-0027 的块", "FEAT-0027" in claim, "docs/AI_WORK_CLAIM.md")
    c.ok("认领簿写了交叉点（判据改动有理由）", "交叉点" in claim)

    c.section("十一、这份判据真的会红（反向验证）")
    c.ok("反向验证脚本在位（同目录）", REVERSE.exists(), str(REVERSE.relative_to(ROOT)))
    c.ok("反向验证脚本写了 R4 边界说明", "R4-BOUNDARY-JUSTIFICATION" in reverse)
    n_mut = len(re.findall(r"^    \($", reverse, flags=re.M))
    c.ok("反向验证 ≥6 条注入", n_mut >= 6, "n=" + str(n_mut))

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：消息按 severity 分档进系统通知栏 ＋ 按通知 id 去重（跨进程）＋ 前台不弹 ＋ 跟随开关（消息不丢）＋ 多条合并成一条摘要 ＋ 深链与 App 内同源 ＋ 司机那条链没被碰。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（FEAT-0027 消息中心 → 系统通知栏）==")
        print("0. 反空转：该在的文件都在、扫到 ≥100 个 .kt、渠道清单从源码数");
        print("1. severity → 重要性：danger=HIGH / warn=DEFAULT / info=LOW，三档三条渠道，映射只一处；");
        print("2. 按通知 id 去重：先读盘 → 查重 → 记「弹过了」，记录落盘（跨进程）；");
        print("3. App 在前台不弹：前台判定＝Activity 生命周期计数，只有一处；");
        print("4. 跟随「消息进通知栏」开关：默认开，关掉只掐系统通知（消息一条不丢）；");
        print("5. 多条合并成一条摘要（1.5 秒窗口 / ≥2 条），单条仍单发，摘要点进消息中心；");
        print("6. 深链复用 noticeRoute（core 里没有第二套映射），走与单号同一道凭据关；");
        print("7. 两条投递链（实时 / 回补）都带上 severity、payload 与角色原文；");
        print("8. 司机新单那条链一个字节没被碰；");
        print("9. 纯判定里每个 public fun 都被单测点到（清单从源码算）；");
        print("10. 文档九节 + 登记表 + 认领簿（含交叉点）；");
        print("11. 反向验证脚本在位且 ≥6 条注入。");
    else:
        sys.exit(main())
