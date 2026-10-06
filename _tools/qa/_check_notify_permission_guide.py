#!/usr/bin/env python
"""通知权限「进首页就得给个说法」的机器判据 —— CHG-0056（台账 L-26 第 ⑤ 条）。

盯住六件事：

1. 读状态与跳设置页**只有一处实现**（core/NotifyPermission.kt）：全 App 不许再出现第二份
   areNotificationsEnabled() 或 ACTION_APP_NOTIFICATION_SETTINGS —— 抄出来的第二份一旦漏了
   「只拦一次」的口径，两个入口迟早在"到底开没开"上互相矛盾。
2. 首页**真的会拦**：进门的轮询结束时判一次、判之前先记「这一轮拦过了」（不然每次进首页都弹）、
   刚点完系统弹窗的"允许"不许再拦、API 33 以下或已被拒的那一支也走同一道判定。
3. 提示是**硬提示**而不是静默降级：走那套弹窗语言的唯一落点（CardAlertDialog，不是裸
   AlertDialog）、带语义色图标、「去开启」真把用户送到系统设置页、用户能自己关掉。
4. 两个入口**一个口径**：首页弹层与「我的 → 消息提醒」那张卡片里"不做会怎样"那句话逐字相同；
   设置页自己那份读法 / 跳转 / startFirstResolvable 已删、只剩省电那一项、两张卡不再顶同一个图标。
5. 「只拦一次」只记在**进程内**：⛔ 不许落盘（落成"一辈子只拦一次"就等于替用户决定"他不想开"，
   而这条权限的后果是漏单 → 账错 —— 用户原话「账会乱掉」）。
6. 单测钉着纯函数 shouldPrompt：四组合逐条断言，恒真（每次进首页都弹）与恒假（功能等于不存在）
   两个方向都要被抓住。

为什么这些必须由机器盯着：它们全是"顺手改一下"就散的形态 —— 把 shouldPrompt 换成一句
if (!enabled)、把 markPrompted 抄到两个分支、把弹层换回裸 AlertDialog、把跳转再写一遍、
把"只拦一次"存进 SharedPreferences、把四组合断言删成一格 …… 每一处都能编译、都跑得起来，
只在"用户被派了单却什么都没弹"这种真机症状里才现形，而那时候账已经错了。

R4-BOUNDARY-JUSTIFICATION: 这条判据不下沉到任何一层边界。被查的全是"谁读这个状态、谁弹这个提示、
两处文案是不是同一句"这类界面形态，后端契约、领域类型、权限模型里都没有它们的位置 ——
通知权限是 Android 系统级的 App 总开关，服务端根本看不见它。

用法：python _tools/qa/_check_notify_permission_guide.py  （--list 打一份人读清单）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
TEST = ROOT / "android" / "app" / "src" / "test" / "java" / "com" / "tapmoay" / "sorders" / "core" / "NotifyPermissionTest.kt"
PERM = AND / "core" / "NotifyPermission.kt"
HOME = AND / "ui" / "home" / "RoleHomeScreen.kt"
SETTINGS = AND / "ui" / "profile" / "AlertSettingsScreen.kt"
CENTER = AND / "core" / "NotifyCenter.kt"
REVERSE = ROOT / "_tools" / "qa" / "_reverse_verify_notify_permission_guide.py"

# 两处入口**逐字相同**的那句（首页弹层 / 消息提醒那页的卡片）
SENTENCE = "不开这个权限，派单来了手机上不会弹任何东西——只有打开 App 才看得到。"
MIN_CHARS = 1500


def calls(src: str, name: str) -> int:
    """数调用点（fun 定义不算）—— 判「是不是真被用上了」。"""
    return len(re.findall(r"(?<!fun )" + re.escape(name) + r"\(", src))


def main() -> int:
    c = Checker()
    perm = read(PERM)
    home = read(HOME)
    settings = read(SETTINGS)
    center = read(CENTER)
    test = read(TEST) if TEST.exists() else ""
    perm_c = strip_comments(perm)
    home_c = strip_comments(home)
    settings_c = strip_comments(settings)
    center_c = strip_comments(center)

    # 全 App 扫一遍：读法/跳转的"第二份"可能被抄进任何一个新文件里
    main_files = {str(p.relative_to(ROOT)).replace("\\", "/"): strip_comments(read(p)) for p in AND.rglob("*.kt")}
    readers = [rel for rel, src in main_files.items() if "areNotificationsEnabled(" in src]
    jumpers = [rel for rel, src in main_files.items() if "ACTION_APP_NOTIFICATION_SETTINGS" in src]

    c.section("0. 反空转 ＋ 唯一落点（core/NotifyPermission.kt）")
    c.ok("core/NotifyPermission.kt 就是那一份（读法 / 判定 / 跳转三件事都在这）",
         len(perm) >= MIN_CHARS
         and "object NotifyPermission {" in perm_c
         and "fun enabled(context: Context): Boolean =" in perm_c
         and "fun shouldPrompt(enabled: Boolean, promptedThisLaunch: Boolean): Boolean =" in perm_c
         and "fun openSettings(context: Context)" in perm_c,
         "零件被掏空/搬走 → 下面每一条都可能是空转")
    c.ok("读通知开关全 App 只有一处实现（谁都不许抄第二份）",
         readers == ["android/app/src/main/java/com/tapmoay/sorders/core/NotifyPermission.kt"],
         "还有别处自己读开关：" + (", ".join(readers) if readers else "（一处都没有）")
         + " —— 第二份读法迟早与这一份判得不一样")
    c.ok("跳通知设置页也只有这一处（页面里不再自己拼 ACTION_APP_NOTIFICATION_SETTINGS）",
         jumpers == ["android/app/src/main/java/com/tapmoay/sorders/core/NotifyPermission.kt"],
         "还有别处自己拼跳转：" + (", ".join(jumpers) if jumpers else "（一处都没有）"))
    c.ok("读法的消费者都转发到这一份（发通知前 / 首页进门 / 那一页的卡片）",
         "NotifyPermission.enabled(context)" in center_c
         and "NotifyPermission.enabled(permContext)" in home_c
         and "NotifyPermission.enabled(context)" in settings_c,
         "有人绕开共用件自己读 → 三个入口对「开没开」的判断会分叉")
    c.ok("搬到 core 的兜底跳转还在（首选页不存在就退应用详情页）",
         "internal fun startFirstResolvable(" in perm_c
         and "resolveActivity" in perm_c
         and "ACTION_APPLICATION_DETAILS_SETTINGS" in perm_c,
         "个别 ROM 上没有通知设置页 → 少了兜底，用户点「去开启」会没反应")
    c.ok("反向验证脚本在位（同目录同名）", REVERSE.exists(),
         "少了反验 → 上面这些红线没人证明它们真的有牙")

    c.section("1. 首页真的会拦（不是又申请一次权限就完事）")
    c.ok("首页进了门就判一次（不是只申请权限就完事）",
         calls(home_c, "guideNotifyPermission") >= 2 and "NotifyPermission.shouldPrompt(" in home_c,
         "申请完就没了下文 = 又回到「静默降级」，不进设置页的用户永远看不到")
    c.ok("拦之前先记「这一轮拦过了」（否则每次进首页都弹）",
         re.search(r"if \(NotifyPermission\.shouldPrompt\([^)]*\)\) \{[\s\S]{0,240}?"
                   r"NotifyPermission\.markPrompted\(\)[\s\S]{0,240}?showNotifyGuide = true", home_c) is not None,
         "记与显示不在同一支里 → 要么每次进首页都弹，要么什么都不弹")
    c.ok("刚点完系统弹窗的「允许」不再拦（那一下的授予结果当开着看）",
         "guideNotifyPermission(grants[Manifest.permission.POST_NOTIFICATIONS] == true)" in home_c,
         "系统弹窗刚被允许就再拦一张 → 用户以为「没生效」，去把权限又关一遍")
    c.ok("没有可申请的权限时也走同一道判定（API 33 以下 / 已被拒）",
         "guideNotifyPermission(false)" in home_c,
         "那一档恰恰是「用户在系统设置里关掉了通知」，最需要这张硬提示")
    c.ok("提示只叠在页面上（不是拦路页：showNotifyGuide 不 return、页面照常进出）",
         home_c.find("Scaffold(") != -1
         and home_c.rfind("if (showNotifyGuide)") > home_c.find("Scaffold(")
         and re.search(r"if\s*\(\s*showNotifyGuide\s*\)\s*(return|\{[^}]*return)", home_c) is None,
         "把它写成一道前置闸门（通知没开就 return 掉首页）→ 用户连页面都进不去，那是另一件事")

    c.section("2. 硬提示长什么样（那套弹窗语言）")
    c.ok("弹的是那套弹窗语言的唯一落点（CardAlertDialog，不是裸 AlertDialog）",
         "CardAlertDialog(" in home_c and re.search(r"(?<!Card)AlertDialog\(", home_c) is None,
         "裸 AlertDialog 是灰蓝那一套 → 与「以后弹窗都长这样」的口径分叉（CHG-0051 立的共用件）")
    c.ok("提示带图标（语义色橙，不与正文混在一起）",
         "Icons.Default.NotificationsOff" in home_c and "Color(0xFFFF9500)" in home_c,
         "没有图标就只是一句话，用户不会当成「必须处理的事」")
    c.ok("「去开启」真的把用户送到系统设置页",
         "NotifyPermission.openSettings(permContext)" in home_c,
         "点了不跳 → 用户以为 App 坏了，权限还是没开")
    c.ok("用户能自己关掉这个提示（有「以后再说」的出口）",
         'Text("以后再说")' in home_c and "onDismissRequest" in home_c,
         "没有出口 = 每次进首页都被顶一张挡不住的弹层")
    c.ok("两处入口那句「不做会怎样」逐字相同（首页弹层 / 消息提醒那页的卡片）",
         home.count(SENTENCE) == 1 and settings.count(SENTENCE) == 1,
         "一个入口说一句 → 用户拿两个说法互相印证，最后谁都不信")

    c.section("3. 设置页不再有第二份（那一页只剩省电这一项读取）")
    c.ok("设置页自己那份读法与跳转已删（现在都走 core）",
         "areNotificationsEnabled" not in settings_c
         and "ACTION_APP_NOTIFICATION_SETTINGS" not in settings_c
         and "fun notificationsAllowed" not in settings_c,
         "页面里留了第二份读法 → 与首页的判定会分叉")
    c.ok("设置页现在转发到共用那一份",
         "NotifyPermission.enabled(context)" in settings_c and "NotifyPermission.openSettings(context)" in settings_c,
         "转发断线 → 这一页读的是别的东西")
    c.ok("设置页里那份私有的 startFirstResolvable 已删（用的是 core 的）",
         "fun startFirstResolvable" not in settings_c and "startFirstResolvable(context" in settings_c,
         "两份同名兜底 → 改一处漏一处，某个 ROM 上「去开启」又没反应")
    c.ok("通知那张卡还在（进「我的 → 消息提醒」仍能看到状态与去开启）",
         "WarnCard(" in settings_c and "Icons.Default.NotificationsOff" in settings_c,
         "卡片没了 → 已经进到这一页的用户反而看不到自己没开通知")
    c.ok("两张卡不再顶同一个图标（通知卡显式传自己的，默认值仍是电池）",
         re.search(r"icon:\s*(?:androidx\.compose\.ui\.graphics\.vector\.)?ImageVector\s*=\s*"
                   r"Icons\.Default\.BatteryAlert", settings_c) is not None
         and "icon = Icons.Default.NotificationsOff" in settings_c,
         "省电那一张与通知那一张长一样 → 用户第一眼读到的是「电池的事」")

    c.section("4. 「只拦一次」只记在进程内")
    c.ok("「拦一次」只记在进程内（⛔ 不许落盘成一辈子只拦一次）",
         "var promptedThisLaunch: Boolean = false" in perm_c
         and "private set" in perm_c
         and "SharedPreferences" not in perm_c
         and "getSharedPreferences" not in perm_c,
         "落了盘就等于替用户做了「他不想开」的决定 —— 而漏通知的后果是账错")
    c.ok("这个标记只有一个写入口（markPrompted）",
         perm_c.count("promptedThisLaunch = true") == 1 and "fun markPrompted()" in perm_c,
         "第二个写入口 = 某条路径静默把「这一轮」改掉，硬提示再也不出现")
    c.ok("KDoc 留着「为什么」（用户原话：账会乱掉 ＋ ref m01132）",
         "账会乱掉" in perm and "m01132" in perm,
         "理由删了，下一个人就会觉得「少响一声而已」，顺手把这功能删掉")
    c.ok("KDoc 说清为什么读 areNotificationsEnabled 而不是 POST_NOTIFICATIONS",
         "NotificationManagerCompat.areNotificationsEnabled()" in perm
         and "**不是**" in perm and "POST_NOTIFICATIONS" in perm,
         "只查那个运行时权限 → API 33 以下（和「在设置里关掉」的用户）永远判成「开着」")

    c.section("5. 单测钉着 shouldPrompt（两个方向都不许写错）")
    c.ok("单测钉着 shouldPrompt（四组合逐条在）",
         test != ""
         and "shouldPrompt" in test
         and "(true to false) to false" in test
         and "(true to true) to false" in test
         and "(false to false) to true" in test
         and "(false to true) to false" in test,
         "少一格 → 那个组合写错了没人知道")
    c.ok("单测两个方向都断言（恒真 / 恒假都要被抓住）",
         "assertTrue(" in test and "assertFalse(" in test and test.count("@Test") >= 4,
         "只断言「要拦」 → 写成恒真就变成每次进首页都弹")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：通知权限那套（读法/跳转唯一一份 ＋ 首页进门真的拦 ＋ 走共用弹层"
          f"＋ 两个入口一句文案 ＋ 只记在进程内 ＋ 单测钉四组合）。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（通知权限进首页硬提示 CHG-0056 / 台账 L-26 第 ⑤ 条）==")
        print("0. 反空转 ＋ 唯一落点：core/NotifyPermission.kt 是那一份；全 App 没有第二份读法/跳转")
        print("1. 首页真的会拦：进门判一次、判前先记、刚允许不再拦、没有可申请权限时也判；只叠不拦路")
        print("2. 硬提示：共用弹层 CardAlertDialog ＋ 语义色图标 ＋ 「去开启」真跳 ＋ 用户能关掉")
        print("3. 设置页不再有第二份：读法/跳转/startFirstResolvable 都转发 core，两张卡图标不同")
        print("4. 「只拦一次」只记在进程内（⛔ 不落盘）＋ 唯一写入口 ＋ KDoc 留着用户原话")
        print("5. 单测钉着 shouldPrompt 的四种组合（恒真/恒假都要被抓住）")
    else:
        sys.exit(main())
