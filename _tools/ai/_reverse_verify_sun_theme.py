"""反向验证 §21（「随日落自动切换夜间模式」）。

## 为什么这一节必须配反向验证
这一节守的四条性质**坏掉时不报错、不崩、界面上也看不出来**：

- 开关默认改成开 → 所有老用户升级后界面外观被悄悄改掉，没人会想到是主题的锅；
- 界线从"民用暮光"悄悄改成"日落那一刻"（96° → 90°）→ 天还亮着就切夜间，
  表现是"这功能好像早了一点"，而这种"软错误"没有任何测试会红；
- 「几点算天黑」被写死成某一天的常数（`date.dayOfYear` 被替换成 172）→
  开发当天测是对的，换个季节就全错；
- 自动模式下手动开关不再被忽略 / 不再置灰 → 用户点一下、过一会儿自己弹回来；
- 定时器从根节点搬到「我的」页面 / 回前台不补一次对表 → 只有停在那一页才切、
  后台过夜后早上打开还是夜间模式（**这是这一节里最像"时好时坏"的一条**）；
- 睡眠上限被当成"多余的判断"删掉 → 用户改了系统时间或换时区后，最长要等十几个小时才自愈；
- 判定里混进 Android 依赖 / 定位 SDK → 前者让单测跑不起来（于是"算得对不对"永远没人管），
  后者让功能在用户拒绝权限后**静默失效**。

所以每条都注入一次，证明检查真的会红。

用法：`python _reverse_verify_sun_theme.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = repo_root()
SUN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/SunClock.kt"
THEME = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Theme.kt"
AUTO_UI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/AutoSunTheme.kt"
PROFILE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileScreen.kt"
MAIN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/MainActivity.kt"
SUN_LOC = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/SunLocation.kt"
AMAP = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/AmapLocationManager.kt"
HOME = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/home/RoleHomeScreen.kt"
DEV_LOC = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/DeviceLocation.kt"
PICKER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/AmapPicker.kt"

# 会被反复用到的原文（改名了这里必须跟着改，否则注入静默失效 → 变成假绿灯）
LOAD_LINE = "val dark = if (autoBySun) SunClock.stateHere().dark else p.getBoolean(KEY_DARK, false)"

CASES: list[tuple[str, Path, object]] = [
    (
        "开关默认改成开（老用户升级后外观被悄悄改掉）",
        THEME,
        lambda s: s.replace("getBoolean(KEY_AUTO, false)", "getBoolean(KEY_AUTO, true)", 1),
    ),
    (
        "界线改成日落那一刻（天还亮着就切夜间）",
        SUN,
        lambda s: s.replace("const val CIVIL_ZENITH = 96.0", "const val CIVIL_ZENITH = 90.0", 1),
    ),
    (
        "界线只在常量里、不进公式（检查空转的经典形态）",
        SUN,
        lambda s: s.replace("cos(Math.toRadians(CIVIL_ZENITH))", "cos(Math.toRadians(96.0))", 1),
    ),
    (
        "日期被写死成常数（开发当天对、换季全错）",
        SUN,
        lambda s: s.replace("val n = date.dayOfYear", "val n = 172", 1),
    ),
    (
        "启动时不按自动算（首帧先按上次手动那套渲染）",
        THEME,
        lambda s: s.replace(LOAD_LINE, "val dark = p.getBoolean(KEY_DARK, false)", 1),
    ),
    (
        "自动模式下手动开关不再被忽略（点一下又自己弹回来）",
        THEME,
        lambda s: s.replace("        if (autoBySun) return\n", "", 1),
    ),
    (
        "开关不落盘（杀掉 App 就回到默认关）",
        THEME,
        lambda s: s.replace("prefs(context).edit().putBoolean(KEY_AUTO, on).apply()", "", 1),
    ),
    (
        "打开自动后不对表（要等最长 15 分钟才生效）",
        THEME,
        lambda s: s.replace("        if (on) refreshAuto(context)\n", "", 1),
    ),
    (
        "定时器挂到页面上、从根节点摘掉（只有停在那页才切）",
        MAIN,
        lambda s: s.replace("                AutoSunThemeEffect()", "                // AutoSunThemeEffect()", 1),
    ),
    (
        "回前台不补对表（后台过夜后早上打开还是夜间）",
        MAIN,
        lambda s: s.replace("        ThemeMode.refreshAuto(this)\n", "", 1),
    ),
    (
        "定时器 key 写成整个状态（每次切完主题定时器就重启）",
        AUTO_UI,
        lambda s: s.replace("LaunchedEffect(auto)", "LaunchedEffect(auto, ThemeMode.isDark)", 1),
    ),
    (
        "睡眠上限被删掉（改系统时间/换时区后几小时才自愈）",
        AUTO_UI,
        lambda s: s.replace("coerceIn(MIN_SLEEP_MS, MAX_SLEEP_MS)", "coerceAtLeast(MIN_SLEEP_MS)", 1),
    ),
    (
        "坐标不校验（0,0 是高德定位失败的哨兵：拿它算日落会错 8 小时且不报错）",
        SUN_LOC,
        lambda s: s.replace(
            "if (!isPlausible(lat, lng)) return false",
            "if (lat == null || lng == null) return false",
            1,
        ),
    ),
    (
        "定位失败也写坐标（把上一次可用的值清成 0,0 = 时好时坏）",
        AMAP,
        # ⚠️ 注入点必须锚**代码**不能锚注释：第一版锚的是那句"定位失败：不要动 SunLocation"，
        #    而这一轮按用户要求把注释删了 → 注入静默失效（脚本会报"注入没生效"）。
        lambda s: s.replace(
            "                        _locations.tryEmit(pt)\n                    } else {\n",
            "                        _locations.tryEmit(pt)\n                    } else {\n"
            "                        SunLocation.update(0.0, 0.0)\n",
            1,
        ),
    ),
    (
        "拿不到坐标就崩/不退回（定位变成前置条件 = 用户一拒权限功能就死）",
        SUN,
        lambda s: s.replace(
            "val p = SunLocation.coords() ?: return stateAt(now, zone)",
            "val p = SunLocation.coords()!!",
            1,
        ),
    ),
    (
        "界面不传 located（按定位和按时区估算说成一样 = 骗人）",
        PROFILE,
        lambda s: s.replace("located = SunLocation.hasFix(),", "located = true,", 1),
    ),
    (
        "定位到手不重算（要等最长 15 分钟才纠正，期间按估算的主题在跑）",
        HOME,
        lambda s: s.replace(
            "            if (SunLocation.update(it.lat, it.lng)) {\n"
            "                ThemeMode.refreshAuto(permContext)\n",
            "            if (SunLocation.update(it.lat, it.lng)) {\n",
            1,
        ),
    ),
    (
        "判定里混进 Android 依赖（单测跑不起来 = 没人管算得对不对）",
        SUN,
        lambda s: s.replace("import java.time.Instant", "import android.os.Build\nimport java.time.Instant", 1),
    ),
    (
        "自动模式下那个开关不再置灰（用户以为能手动改）",
        PROFILE,
        lambda s: s.replace("enabled = !ThemeMode.autoBySun", "enabled = true"),
    ),
    (
        "「我的」页面那一行被拿掉（三端都没有入口）",
        PROFILE,
        lambda s: s.replace('Text("随日落自动切换")', 'Text("日落自动")', 1),
    ),
    (
        "右侧那行字不再走纯函数（自己拼时间 = 没单测）",
        PROFILE,
        lambda s: s.replace(
            "SunClock.summary(\n"
            "                                    ThemeMode.autoBySun,\n"
            "                                    SunClock.stateHere(),\n"
            "                                    located = SunLocation.hasFix(),\n"
            "                                )",
            '"天黑切夜间，天亮切回白天"',
            1,
        ),
    ),
    (
        "高德失败后不再退系统定位兜底（定位一坏就永远是时区估算）",
        HOME,
        # 两处都要掐掉（预热那次 + 回调失败那次）：只掐一处的话，另一处还留着
        # 同一个字符串，判据照样绿——第一版就是这么假绿的。
        lambda s: s.replace(
            "if (DeviceLocation.requestSingle(permContext) != null) ThemeMode.refreshAuto(permContext)",
            "if (false) ThemeMode.refreshAuto(permContext)",
        ),
    ),
    (
        "高德连发起都没成功也不退兜底（那种失败一个回调都不会来）",
        HOME,
        lambda s: s.replace("if (!container.locationManager.requestSingle()) {", "if (false) {", 1),
    ),
    (
        "兜底去冒充「带地址的高德点」（坐标系不同，地址/水印会错几百米）",
        DEV_LOC,
        lambda s: s.replace(
            "        return if (SunLocation.update(best.lat, best.lng)) best else null",
            "        val fake: AmapLocationPoint? = null\n"
            "        return if (SunLocation.update(best.lat, best.lng)) best else null",
            1,
        ),
    ),
    (
        "挑坐标不再挑（拿第一条就用：可能是几小时前、也可能在别的城市）",
        DEV_LOC,
        lambda s: s.replace(
            "        .sortedWith(compareByDescending<LocationFix> { it.atMs }.thenBy { it.accuracyM })\n"
            "        .firstOrNull()",
            "        .firstOrNull()",
            1,
        ),
    ),
    (
        "陈旧缓存不再过滤（手机在郑州、算的是三天前北京的日落）",
        DEV_LOC,
        lambda s: s.replace("        .filter { it.atMs <= 0 || nowMs - it.atMs <= maxAgeMs }\n", "", 1),
    ),
    (
        "把日落用的坐标拿去填地址（两套坐标系混用）",
        PICKER,
        lambda s: s.replace(
            "            container.locationManager.requestSingle()",
            "            com.tapmoay.sorders.core.SunLocation.coords()?.let { }\n"
            "            container.locationManager.requestSingle()",
            1,
        ),
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(HERE / "_check_ai_guardrails.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section_21(out: str) -> str:
    """只取 §21 那一段。

    ⚠️ 两个坑都在上一轮踩过：
    ① 段内的失败标记是 `[FAIL]`，**不是** `❌`（`❌` 只在最后的汇总里）；
    ② §21 是**最后一节**，后面紧跟汇总——不切掉汇总，任何一条注入都会"看起来变红了"。
    """
    if "== 21." not in out:
        return ""
    rest = out.split("== 21.", 1)[1]
    return rest.split("\n" + "=" * 60, 1)[0]


def main() -> int:
    fails: list[str] = []

    code, out = run_check()
    if code != 0:
        fails.append(f"前提不成立：源码完好时检查就没过\n{out[-1500:]}")
        print("\n".join(fails))
        return 1
    if not section_21(out):
        fails.append("前提不成立：输出里找不到 §21 这一段（红线脚本被改过？）")
        print("\n".join(fails))
        return 1
    print("✅ 前提：源码完好时检查是绿的，且 §21 存在")

    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（源码里那段已经变了，请更新本脚本的替换串）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        got = section_21(out)
        if code == 0 or "[FAIL]" not in got:
            fails.append(f"{label}：注入后 §21 没有报红（code={code}）——判据是空转的")
        else:
            print(f"✅ 注入「{label}」→ §21 报红")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §21 的 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
