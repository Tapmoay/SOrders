"""反向验证「底部导航栏凹口」那几条红线**真的会红**。

为什么这块也必须反向验证：凹口画错了**不会报错、不会崩、界面上也看不出**——
第一版的坑只有 18dp 深而且全被圆钮盖住，量像素才发现缺口内外一模一样。
如果红线只是"文件里出现过 NotchedBarShape"这种字符串匹配，那么把接线删掉它照样绿。

用法：python _tools/ai/_reverse_verify_nav.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_nav_guardrails.py"

UI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui"
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
HOME = UI / "home/RoleHomeScreen.kt"
NAV = UI / "nav/NotchedNavBar.kt"
MODULES = UI / "nav/Modules.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词；None = 只有单测能抓)
MUTATIONS = [
    (
        "导航条不用带凹口的形状了（退回平直方块，圆钮又变成「贴上去的」）",
        HOME,
        "                val barShape = remember { NotchedBarShape() }",
        "                val barShape = androidx.compose.foundation.shape.RoundedCornerShape(0.dp)",
        "有圆钮的角色用带凹口的导航条形状",
    ),
    (
        "凹口背景不再铺在 NavigationBar 下面（凹口被平直白底盖回去）",
        HOME,
        "                            .background(MaterialTheme.colorScheme.surface, barShape),",
        "                            .background(MaterialTheme.colorScheme.surface),",
        "凹口背景画在 NavigationBar",
    ),
    (
        "NavigationBar 又用不透明底色（把凹口彻底盖住，界面上什么都看不见）",
        HOME,
        "                        androidx.compose.ui.graphics.Color.Transparent",
        "                        NavigationBarDefaults.containerColor",
        "有圆钮时 NavigationBar 容器透明",
    ),
    (
        "阴影不吃形状（底色凹了、阴影还是方的，边缘会穿帮）",
        HOME,
        "                            .shadow(8.dp, barShape)",
        "                            .shadow(8.dp)",
        "阴影也用同一个形状",
    ),
    (
        "凹口圆心回到栏上沿之上（第一版的原样：坑又浅又藏在圆钮背后）",
        NAV,
        "        val centerY = radius - buttonTopAboveEdge.toDouble()",
        "        val centerY = -buttonTopAboveEdge.toDouble()",
        None,  # 纯几何：靠单测（圆心必须在栏内 / 太浅了看不见）
    ),
    (
        "凹口半径改成贴着圆钮（没有缝隙，看着像被切了一刀）",
        NAV,
        "        val r = buttonDiameter.toDouble() / 2 + gap.toDouble()",
        "        val r = buttonDiameter.toDouble() / 2",
        None,
    ),
    (
        "几何不再从圆钮尺寸算（写死一个数，改圆钮大小就对不上）",
        NAV,
        "            buttonDiameter = AiNavButton.Size.toPx(),",
        "            buttonDiameter = 58f * density.density,",
        "用的是 AiNavButton 的真实尺寸常量",
    ),
    (
        "弧改成从右交点顺时针画（会补出一条弦横在缺口上）",
        NAV,
        "                    startAngleDegrees = g.leftAngle.toFloat(),",
        "                    startAngleDegrees = g.startAngle.toFloat(),",
        "弧从左边交点逆时针画",
    ),
    (
        "去掉防咬穿的夹取（栏高被改小时缺口会切穿导航栏）",
        NAV,
        "        val fitHeight = if (g.depth > 0) size.height / g.depth else 1.0\n"
        "        val fitWidth = if (g.filletDx > 0) availHalf / g.filletDx else 1.0\n"
        "        val scale = minOf(1.0, fitHeight, fitWidth).toFloat()",
        "        val scale = 1.0f",
        "有防咬穿的夹取",
    ),
    (
        "过渡半径退回一个随手挑的小值 6dp（切点跑回大圆上半圈，留下一小块喙）",
        NAV,
        "        val f = fillet?.toDouble() ?: centerY",
        "        val f = fillet?.toDouble() ?: 6.0",
        "默认过渡半径 = 圆心深度",
    ),
    (
        "过渡半径又变回一个常量（等于给'切点落在哪儿'开了个能改错的旋钮）",
        NAV,
        "    val CornerRadius = 18.dp\n",
        "    val CornerRadius = 18.dp\n    val Fillet = 6.dp\n",
        "过渡半径没有常量",
    ),
    (
        "圆角圆心不再按「与上沿、大圆同时相切」解（随手拿交加点一截当圆心）",
        NAV,
        "        val filletDx = sqrt(halfWidth * halfWidth + 2 * f * (r + centerY))",
        "        val filletDx = halfWidth + f",
        "过渡圆心按",
    ),
    (
        "左圆角弧反着扫（arcTo 会先补一条弦横在缺口上）",
        NAV,
        "                    startAngleDegrees = 270f,\n"
        "                    sweepAngleDegrees = g.filletSweepAngle.toFloat(),",
        "                    startAngleDegrees = 270f,\n"
        "                    sweepAngleDegrees = -g.filletSweepAngle.toFloat(),",
        "左圆角弧从顶点",
    ),
    (
        "右边那段圆角不画了（一边圆一边尖，比不做还难看）",
        NAV,
        "                // 右圆角弧：从大圆上的切点顺时针扫回顶点（270°），对称的另一半\n"
        "                arcTo(\n"
        "                    rect = Rect(left = cx + fx - f, top = 0f, right = cx + fx + f, bottom = 2f * f),\n"
        "                    startAngleDegrees = g.rightFilletStartAngle.toFloat(),\n"
        "                    sweepAngleDegrees = g.filletSweepAngle.toFloat(),\n"
        "                    forceMoveTo = false,\n"
        "                )\n",
        "",
        "两侧各有一段圆角弧",
    ),
    (
        "圆角半径不吃缩放（栏高/宽度被夹取时，圆角与大圆不再相切）",
        NAV,
        "        val f = (g.filletRadius * scale).toFloat()",
        "        val f = g.filletRadius.toFloat()",
        "夹取时三个尺寸",
    ),
    (
        "圆钮改成「整个浮在栏外」（凸出高度＝直径，凹口退化成看不见的小坑）",
        MODULES,
        "    val Protrude = 12.dp",
        "    val Protrude = 58.dp",
        "凹口看得见",
    ),
    (
        "设置页的能力声明退回手写（写窄了用户以为它不会，写宽了用户白试一次）",
        ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiSettingsScreen.kt",
        "                            AiRolePrompt.settingsSummary(",
        "                            (\n",
        "设置页的能力声明调用生成函数",
    ),
    (
        "指路退回「无条件告诉他去哪个页面自己做」（货主会被指去他没有的页面）",
        AI / "AiRolePrompt.kt",
        "            appendLine(\"【问到不归你的事：怎么给下一步】\")",
        "            appendLine(\"   用户问到清单外的事：直说「这个不归我」，并告诉他去哪个页面自己做。\")\n"
        "            appendLine(\"【问到不归你的事：怎么给下一步】\")",
        "不再无条件",
    ),
    (
        "货主身份段不再说明「派单是派单员的活」（用户明确要求的那句）",
        AI / "AiRolePrompt.kt",
        '            "⚠️ 特别记住**派单这件事**：派单是派单员的活，货主自己**没有派单这个操作**" +',
        '            "⚠️ 派单的事别提。" +',
        "货主身份段写明派单是派单员的活",
    ),
    (
        "凹口缝隙调回 2dp（又紧贴着圆钮——用户明确说过「太窄了、不要紧贴」）",
        NAV,
        "    val Gap = 9.dp",
        "    val Gap = 2.dp",
        "凹口不紧贴圆钮",
    ),
    (
        "圆钮又往上飘（用户要求「稍微向下移一点」，这里退回 16dp）",
        MODULES,
        "    val Protrude = 12.dp",
        "    val Protrude = 16.dp",
        None,  # 造型判据：靠单测（圆钮坐得比栏沿低一点）
    ),
    (
        "页面清单改成写死派单员的（货主被告知他有一堆打不开的页面）",
        AI / "AiRolePrompt.kt",
        "        Modules.entriesFor(Role.fromKey(role.key))",
        "        Modules.entriesFor(Role.DISPATCHER)",
        None,  # 页面清单内容靠单测（AiRolePromptTest）
    ),
    (
        "「不归它的」退回手写域名单（能力表加了新域，这句就骗人）",
        AI / "AiRolePrompt.kt",
        "            val notMine = ALL_WRITE_GROUPS.filter { it !in mine }",
        '            val notMine = listOf("派单", "改价", "库存")',
        "「不归它的」是算出来的",
    ),
    (
        "算出来的「不归它的」不再用进提示词（算了没用 = 模型还是不知道自己不能干什么）",
        AI / "AiRolePrompt.kt",
        '                    notMine.joinToString("、"))',
        '                    listOf("派单").joinToString("、"))',
        "真的用进了提示词",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_redline() -> tuple[int, str]:
    return run([sys.executable, str(CHECK)])


def run_tests() -> tuple[int, str]:
    gradle = ROOT / "_agent/gradle/gradle-8.9/bin/gradle.bat"
    r = subprocess.run(
        [str(gradle), "--project-dir", str(ROOT / "android"), ":app:testEmuDebugUnitTest", "--console=plain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    bad = 0
    code, out = run_redline()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时红线没过\n{out[-1500:]}")
        return 1
    print("✅ 前提：源码完好时这一节红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            if expect is None:
                code, out = run_tests()
                hit = code != 0
                detail = "单测报错" if hit else "单测居然还是绿的"
            else:
                code, out = run_redline()
                fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
                hit = code != 0 and any(expect in ln for ln in fails)
                detail = f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:60] for f in fails[:2]]}")
        finally:
            write_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_redline()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    if bad:
        print(f"\n❌ {bad}/{total} 不达标。")
        return 1
    print(f"\n✅ {total}/{total} 都红了：这一节的判据真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
