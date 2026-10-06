# -*- coding: utf-8 -*-
r"""通知权限进首页硬提示（CHG-0056）的反向验证：一条红线要能被「真的破坏一次」证明它在检查。

每条注入只改一处，跑一遍 _check_notify_permission_guide.py，要求它报红、而且报红的就是这条红线；
跑完按**字节**把被碰过的文件还原，再逐字节核对一遍。
锚点一律不写行首缩进：注入结果不需要能编译，只要判据变红。

被碰的文件不只有那个共用件：首页、设置页、发通知前的那一处转发、以及单测都在注入范围里 ——
「一个口径」这件事只有跨文件才证得动。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:  # PowerShell 重定向时 stdout 会退回 GBK，中文与 ✅ 都编不出去
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_notify_permission_guide.py"

PERM = "android/app/src/main/java/com/tapmoay/sorders/core/NotifyPermission.kt"
HOME = "android/app/src/main/java/com/tapmoay/sorders/ui/home/RoleHomeScreen.kt"
SETTINGS = "android/app/src/main/java/com/tapmoay/sorders/ui/profile/AlertSettingsScreen.kt"
CENTER = "android/app/src/main/java/com/tapmoay/sorders/core/NotifyCenter.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/core/NotifyPermissionTest.kt"

NL = chr(10)
Q = chr(34)
SENTENCE = "不开这个权限，派单来了手机上不会弹任何东西——只有打开 App 才看得到。"


def gsub(s: str, pat: str, rep: str) -> str:
    r"""按正则换一处（锚点里用 \s* 兜住缩进，不数空格）。"""
    return re.sub(pat, rep, s, count=1)


CASES: list[tuple[str, str, object, str]] = [
    # ── 0. 唯一落点：谁都不许抄第二份 ─────────────────────────────────────
    ("设置页又自己读了一次开关（第二份读法）",
     SETTINGS,
     lambda s: s.replace("NotifyPermission.enabled(context)",
                         "NotificationManagerCompat.from(context).areNotificationsEnabled()", 1),
     "读通知开关全 App 只有一处实现"),
    ("设置页又自己拼了一份跳转（第二份 ACTION_APP_NOTIFICATION_SETTINGS）",
     SETTINGS,
     lambda s: s.replace("NotifyPermission.openSettings(context)",
                         "context.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS))", 1),
     "跳通知设置页也只有这一处"),
    ("发通知前绕过共用件（自己读开关）",
     CENTER,
     lambda s: s.replace("fun canPost(): Boolean = NotifyPermission.enabled(context)",
                         "fun canPost(): Boolean = manager.areNotificationsEnabled()", 1),
     "读法的消费者都转发到这一份"),
    ("首页不再问共用件（那一下直接当开着）",
     HOME,
     lambda s: s.replace("val ok = grantedNow || NotifyPermission.enabled(permContext)",
                         "val ok = true", 1),
     "读法的消费者都转发到这一份"),
    ("搬到 core 的兜底跳转没了（首选页不存在就什么都不做）",
     PERM,
     lambda s: s.replace("internal fun startFirstResolvable(",
                         "private fun startFirstResolvableHere(", 1),
     "搬到 core 的兜底跳转还在"),

    # ── 1. 首页真的会拦 ──────────────────────────────────────────────────
    ("首页不判了（进了门也不看权限）",
     HOME,
     lambda s: s.replace("if (NotifyPermission.shouldPrompt(ok, NotifyPermission.promptedThisLaunch)) {",
                         "if (false) {", 1),
     "首页进了门就判一次"),
    ("拦了不记（每次进首页都弹）",
     HOME,
     lambda s: s.replace("NotifyPermission.markPrompted()", "Unit", 1),
     "拦之前先记"),
    ("刚点完系统弹窗的「允许」也要再拦一张",
     HOME,
     lambda s: s.replace("guideNotifyPermission(grants[Manifest.permission.POST_NOTIFICATIONS] == true)",
                         "guideNotifyPermission(false)", 1),
     "刚点完系统弹窗的「允许」不再拦"),
    ("没有可申请的权限时静默跳过（恰恰是设置里关掉的那一档）",
     HOME,
     lambda s: s.replace("guideNotifyPermission(false)", "Unit", 1),
     "没有可申请的权限时也走同一道判定"),
    ("硬提示变前置闸门（通知没开就 return 掉整个首页）",
     HOME,
     lambda s: s.replace("if (showNotifyGuide) {", "if (showNotifyGuide) { return }", 1),
     "提示只叠在页面上"),

    # ── 2. 硬提示长什么样 ────────────────────────────────────────────────
    ("提示换回裸 AlertDialog（不走那套弹窗语言）",
     HOME,
     lambda s: s.replace("CardAlertDialog(", "AlertDialog(", 1),
     "弹的是那套弹窗语言的唯一落点"),
    ("提示不带图标了（只剩一句话）",
     HOME,
     lambda s: s.replace("Icons.Default.NotificationsOff", "Icons.Default.BatteryAlert", 1),
     "提示带图标"),
    ("「去开启」不跳设置（点了没反应）",
     HOME,
     lambda s: s.replace("NotifyPermission.openSettings(permContext)", "Unit", 1),
     "「去开启」真的把用户送到系统设置页"),
    ("用户关不掉这张弹层（没有「以后再说」）",
     HOME,
     lambda s: s.replace("Text(" + Q + "以后再说" + Q + ")", "Text(" + Q + "知道了" + Q + ")", 1),
     "用户能自己关掉这个提示"),

    # ── 3. 两个入口一个口径 ──────────────────────────────────────────────
    ("两处文案不再同一句（设置页换了个说法）",
     SETTINGS,
     lambda s: s.replace(SENTENCE, "请到系统设置里打开通知权限。", 1),
     "逐字相同"),
    ("设置页又把那份私有的 startFirstResolvable 长回来（第二份兜底）",
     SETTINGS,
     lambda s: s.replace("private fun WarnCard(",
                         "private fun startFirstResolvable(context: Context, preferred: Intent, "
                         "fallback: () -> Intent) {}" + NL + NL + "private fun WarnCard(", 1),
     "设置页里那份私有的 startFirstResolvable 已删"),
    ("通知那张卡没了（图标退回电池那个）",
     SETTINGS,
     lambda s: s.replace("icon = Icons.Default.NotificationsOff,", "icon = Icons.Default.BatteryAlert,", 1),
     "通知那张卡还在"),
    ("两张卡又顶同一个图标（默认值被改成通知那个）",
     SETTINGS,
     lambda s: gsub(s, r"=\s*Icons\.Default\.BatteryAlert", "= Icons.Default.NotificationsOff"),
     "两张卡不再顶同一个图标"),

    # ── 4. 「只拦一次」只记在进程内 ──────────────────────────────────────
    ("「拦一次」落到磁盘（变成一辈子只拦一次）",
     PERM,
     lambda s: s.replace("fun markPrompted() {",
                         "fun prefs(context: Context) = context.getSharedPreferences(" + Q + "sorders" + Q + ", 0)"
                         + NL + "fun markPrompted() {", 1),
     "「拦一次」只记在进程内"),
    ("又开了一个写入口（某条路径静默把「这一轮」改掉）",
     PERM,
     lambda s: s.replace("fun markPrompted() {", "fun markPromptedAgain() { promptedThisLaunch = true }" + NL
                         + "fun markPrompted() {", 1),
     "这个标记只有一个写入口"),
    ("KDoc 里「为什么」被删（用户原话没了）",
     PERM,
     lambda s: s.replace("账会乱掉", "会出问题", 1),
     "KDoc 留着「为什么」"),

    # ── 5. 单测钉着 shouldPrompt ────────────────────────────────────────
    ("单测少了那一格（false to true）",
     TEST,
     lambda s: s.replace("(false to true) to false", "(false to true) to true", 1),
     "单测钉着 shouldPrompt"),
    ("单测只剩恒真的写法（不再断言不许拦的那两格）",
     TEST,
     lambda s: s.replace("assertFalse(", "assertTrue("),
     "单测两个方向都断言"),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", NL)
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
            continue
        try:
            out_txt = mutated.replace("\r\n", NL)
            if crlf:
                out_txt = out_txt.replace(NL, "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print("  [OK] " + label + " → 报红")
        else:
            fails.append(label + f"：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print("  [MISS] " + label + " → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
