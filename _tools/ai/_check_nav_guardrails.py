"""底部导航栏「凹口」造型的红线自检。

### 为什么单独钉这一块
用户拿星巴克 App 的截图要求「那个圆圈里面要凹一下，参考这个样式」。
第一次实现**画错了但完全看不出来**：凹口的圆心算在了导航栏上沿**之上**，
切出来的坑只有 18dp 深、而且几乎整块被圆钮自己盖住——代码"跑了"、界面"没变"，
唯一能发现的办法是**量像素**（缺口内外上沿的 y 完全一样，落差 0px）。

所以这里钉三件事：
1. 有圆钮时，导航条底色必须用带凹口的形状（而不是 M3 默认的平直方块）；
2. 凹口几何必须**从圆钮尺寸算**（写死数字的话，改圆钮大小就会对不上）；
3. 几何数字本身必须落在"看得见"的区间里（太浅＝白做，太深＝把栏咬穿）。

2026-09-20 加了第四件：凹口两侧的**圆滑过渡**（用户：「它那个圆圈图标它是被 2 个矩形
像是框在一起的…那个角是尖尖，把它做一个曲线过渡」）。过渡的判据不是"像不像"，而是
**相切**——圆角要同时与上沿和大圆相切，少切一个那边就还是尖角。所以这里钉：
过渡常量在 3~10dp、圆心是按相切公式算的（不是随手一个数）、上沿开口因此被撑宽
（撑不宽就说明圆角没生效）、左右两段弧都在、扫角方向是顺时针（反了 arcTo 会补一条弦）。

用法：python _tools/ai/_check_nav_guardrails.py     # 全过 → 退出码 0
"""
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
UI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui"
HOME = UI / "home/RoleHomeScreen.kt"
NAV = UI / "nav/NotchedNavBar.kt"
MODULES = UI / "nav/Modules.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/nav/NotchedBarTest.kt"
MEASURE = ROOT / "_tools/notify/_measure_notch.py"


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    src = re.sub(r"//[^\n\"']*$", "", src, flags=re.M)
    return src


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")


def main() -> int:
    c = Checker()
    home = strip_comments(read(HOME))
    nav = strip_comments(read(NAV))
    modules = strip_comments(read(MODULES))
    test = read(TEST)

    # ---- §1 界面接线：有圆钮就必须有凹口 ----
    c.present("有圆钮的角色用带凹口的导航条形状", home, r"NotchedBarShape\(\)")
    c.present(
        "凹口背景画在 NavigationBar **下面**（声明在前 + matchParentSize）",
        home,
        r"matchParentSize\(\)[\s\S]{0,200}?background\(MaterialTheme\.colorScheme\.surface,\s*barShape\)",
    )
    c.present(
        "有圆钮时 NavigationBar 容器透明（否则平直的白底会把凹口盖回去）",
        home,
        r"containerColor = if \(showAiButton\)[\s\S]{0,200}?Color\.Transparent",
    )
    c.present("无圆钮的角色仍走 M3 默认底色（不折腾没圆钮的栏）", home, r"NavigationBarDefaults\.containerColor")
    c.present("阴影也用同一个形状（底色凹了、阴影还是方的会穿帮）", home, r"shadow\(8\.dp,\s*barShape\)")

    # ---- §2 几何必须从圆钮尺寸算，不许写死 ----
    c.present("几何由圆钮尺寸算出（geometryForButton）", nav, r"fun geometryForButton\(density: Density\)")
    c.present("用的是 AiNavButton 的真实尺寸常量", nav, r"AiNavButton\.Size")
    c.present("凸出高度也取同一个常量（两处必须一致）", nav, r"AiNavButton\.Protrude")
    c.present("圆心取「半径 − 凸出」＝在栏内侧，而不是在栏外", nav, r"val centerY = radius - buttonTopAboveEdge\.toDouble\(\)")
    c.present("有防咬穿的夹取（栏高被改小时不会切穿）", nav, r"size\.height / g\.depth")
    c.present(
        "夹取时三个尺寸**同比例**缩放（半径/圆心/圆角分开夹取=圆角不再与大圆相切）",
        nav,
        r"g\.filletRadius \* scale",
    )
    c.present("弧从左边交点逆时针画（顺时针会补一条弦把缺口盖住）", nav, r"startAngleDegrees = g\.leftAngle")
    c.present("凹口有可见缝隙常量", nav, r"val Gap = \d+\.dp")
    c.present("外角有圆角（参照图那块白是圆角的）", nav, r"val CornerRadius = \d+\.dp")

    # ---- §2b 圆滑过渡：几何必须是"相切"算出来的，两段弧都要在 ----
    c.absent(
        "过渡半径没有常量（它由两个相切条件解出来；写成常量 = 给'切点落在哪儿'开了个能改错的旋钮）",
        nav,
        r"val Fillet = \d",
    )
    c.present(
        "默认过渡半径 = 圆心深度（圆角圆心与大圆圆心等高 ⇒ 切点落在大圆最宽处，旧方角整块消失）",
        nav,
        r"val f = fillet\?\.toDouble\(\) \?: centerY",
    )
    c.present(
        "过渡圆心按「与上沿相切 + 与大圆相切」两个条件解出来（halfWidth² + 2f(r + centerY)）",
        nav,
        r"2 \* f \* \(r \+ centerY\)",
    )
    c.present("大圆弧的起点换成与圆角的切点（不再是上沿交点）", nav, r"val startAngle = -toCenterDeg")
    c.present(
        "左圆角弧从顶点（270°）顺时针扫到切点",
        nav,
        r"startAngleDegrees = 270f,\s*sweepAngleDegrees = g\.filletSweepAngle",
    )
    c.present("右圆角弧从切点扫回顶点", nav, r"startAngleDegrees = g\.rightFilletStartAngle")
    n_fillet = len(re.findall(r"sweepAngleDegrees = g\.filletSweepAngle", nav))
    c.ok(
        f"两侧各有一段圆角弧（实测 {n_fillet} 处，只做一边＝一边圆一边尖）",
        n_fillet == 2,
        f"实际 {n_fillet} 处",
    )
    c.present("缺口用同一个 scale 缩放（三个 fit 取最小）", nav, r"minOf\(1\.0, fitHeight, fitWidth\)")

    # ---- §3 几何数字落在"看得见"的区间（真机量过：缺口深 57dp、半宽 34dp） ----
    size = re.search(r"val Size = (\d+)\.dp", modules)
    protrude = re.search(r"val Protrude = (\d+)\.dp", modules)
    gap = re.search(r"val Gap = (\d+)\.dp", nav)
    c.ok("圆钮尺寸/凸出/缝隙三个常量都能取到", all((size, protrude, gap)))
    if size and protrude and gap:
        d, p, g = float(size.group(1)), float(protrude.group(1)), float(gap.group(1))
        radius, center = d / 2, d / 2 - p
        depth = center + radius + g
        half = (radius + g) ** 2 - center**2
        half = half ** 0.5 if half > 0 else 0
        c.ok(f"圆心在栏内侧（{center:.0f}dp > 0）", center > 0, f"实际 {center}")
        # 用户两轮反馈都冲着这两个数来：
        # 「太窄了、紧贴着这个按钮，不要紧贴，稍微扩大一点」→ 缝 ≥6dp
        # 「把那个原先按钮稍微向下移一点」→ 圆心进栏 ≥15dp
        c.ok(f"凹口不紧贴圆钮：缝 {g:.0f}dp ≥ 6dp", g >= 6, f"实际 {g}dp（会被判「紧贴」）")
        c.ok(f"圆钮坐进栏里（圆心进栏 {center:.0f}dp ≥ 15dp）", center >= 15, f"实际 {center}dp（看着还飘在栏上）")
        c.ok(f"凹口看得见：深 {depth:.0f}dp > 30dp", depth > 30, f"实际 {depth}")
        c.ok(f"凹口不咬穿：深 {depth:.0f}dp < 栏高 80dp", depth < 80, f"实际 {depth}")
        c.ok(
            f"凹口比圆钮宽（半宽 {half:.0f}dp > 钮半径 {radius:.0f}dp）",
            half > radius,
            f"实际 {half:.1f} vs {radius}",
        )

        # ---- 圆滑过渡（两侧的圆角）：这几个数是"过渡到底做没做对"的判据 ----
        # 过渡半径**不是常量**，而是"圆心深度"（= 钮半径 − 凸出）：只有取这个值，切点才
        # 落在大圆最宽处，旧形状那块"方角"才会整块消失；取小了切点退回大圆上半圈、
        # 留下一小块"喙"加一条缝（6dp 时喙宽 1.2dp——真机看不出来，量尺量得出来）。
        f = center
        # 切点在最宽处的必然结果：上沿开口半宽 = 半径 + 缝 + 圆心深度
        xf = radius + g + f
        c.ok(f"过渡半径 = 圆心深度（{f:.0f}dp ≥ 8dp，太小就没有过渡的样子）", f >= 8.0, f"实际 {f}dp")
        c.ok(
            f"过渡真的把上沿开口撑宽了（{xf:.0f}dp > 交点 {half:.0f}dp）＝不是尖角",
            xf > half,
            f"实际 {xf:.1f} vs {half:.1f}（相等 ⇒ 圆角没生效）",
        )
        # 5 槽各 72dp（360dp 宽的屏），左右两个 Tab 的图标内沿在 ±60dp：
        # 开口半宽超过 58dp 就缺到图标脸上了
        c.ok(f"开口没啃到左右两个 Tab：半宽 {xf:.0f}dp < 58dp", xf < 58.0, f"实际 {xf:.1f}dp")
        # 切点在大圆最宽处 ⇒ 与大圆圆心等高（= 圆心深度），且落在栏内（0 < 切点 < 缺口底）
        c.ok(
            f"切点与大圆圆心等高（{f:.0f}dp）且落在栏内（< 深 {depth:.0f}dp）",
            0.0 < f < depth,
            f"实际 {f:.1f}dp",
        )

    # ---- §4 单测与量尺（这块形状画错了不会报错，只能靠这两个） ----
    for fn in (
        "centerY",
        "radius",
        "halfWidth",
        "depth",
        "startAngle",
        "sweepAngle",
        "leftAngle",
        "filletRadius",
        "filletDx",
        "filletSweepAngle",
        "rightFilletStartAngle",
    ):
        c.present(f"几何字段 [{fn}] 有单测", test, rf"{fn}")
    c.present("测试里钉住「圆心必须在栏内」（第一版就错在这）", test, r"圆心必须在栏内")
    c.present("测试里钉住「太浅了看不见」", test, r"太浅了看不见")
    # 过渡的判据必须落在"相切"上，而不是"看起来圆了"——相切是唯一能算的东西
    c.present("测试钉住「圆角与上沿和大圆同时相切」", test, r"圆滑过渡与上沿和大圆同时相切")
    c.present("测试钉住「开口被撑宽＝圆角真的生效了」", test, r"过渡把上沿的开口撑宽")
    c.present("测试钉住「过渡半径 = 0 时逐位退回尖角」（对照组）", test, r"fillet = 0\.0")
    c.present("测试钉住「圆角弧的扫角方向」（反了会补一条弦）", test, r"圆角弧的扫角是顺时针的")
    c.ok("有真机像素量尺（截图上量缺口深浅）", MEASURE.exists(), str(MEASURE))
    if MEASURE.exists():
        measure = read(MEASURE)
        c.present("量尺有判据（太浅就报失败，不靠肉眼）", measure, r"凹口太浅/没画出来")
        c.present("量尺有「过渡不是尖角」的像素判据", measure, r"两侧还是尖角")
    # 判据本身也要有"已知答案"的对照：同一套公式画两张图（带过渡/尖角），
    # 要求量尺前者过、后者挂。**造不出对照图 = 那把尺子可能只是永远绿**。
    render = ROOT / "_tools/notify/_notch_render.py"
    c.ok("量尺有已知答案的对照图（_notch_render.py --check）", render.exists(), str(render))
    if render.exists():
        src = read(render)
        c.present("对照图用的是同一套几何公式", src, r"def geometry\(fillet: float\)")
        c.present(
            "对照图有判据（分不开就报失败）",
            src,
            r"量尺的判据分不开这两张图",
        )

    # ---- §5 能力声明必须算出来（这块最容易烂：手写的能力承诺会和真实能力走散） ----
    settings = strip_comments(read(UI / "ai/AiSettingsScreen.kt"))
    role_prompt = strip_comments(read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiRolePrompt.kt"))
    c.present("设置页的能力声明调用生成函数", settings, r"AiRolePrompt\.settingsSummary\(")
    c.absent(
        "设置页不再手写能力承诺（写窄了会让用户以为它不会，写宽了会让用户白试一次）",
        settings,
        r"这五件事它做不了",
    )
    # ⚠️ 2026-09-20：这里的形参名从 `role` 换成 `actor`（角色 + 是不是批发商货主，见 `AiActor`）——
    #    两个货主的能力不一样，身份段/能力声明必须按 (角色 + member) 算。
    c.present("生成函数从写动作表算「能改什么」", role_prompt, r"fun settingsSummary[\s\S]{0,900}?AiWrites\.forModel\(actor\)")
    c.present("生成函数从读能力表算「能查什么」", role_prompt, r"fun settingsSummary[\s\S]{0,900}?AiReads\.forRole\(actor")
    # ⚠️ 这一条**曾经红着没人管**（2026-09-17 跑全套反向验证时才发现）：
    #    它把判据锚在一个**局部变量名**上（`it !in groups`），后来那个变量改名成 `mine`，
    #    于是断言永远找不到——而"永远红的检查等于没有检查"（这个仓库栽过 6 次）。
    #    现在锚的是**不变量**：这份"不归它的"必须由 `ALL_WRITE_GROUPS` 过滤出来
    #    （变量叫什么无所谓），并且**真的用进了提示词**（防"算了但没接线"）。
    c.present("「不归它的」是算出来的（不是手写域名单）",
              role_prompt, r"ALL_WRITE_GROUPS\.filter \{ it !in \w+ \}")
    c.present("这份算出来的清单真的用进了提示词（不是算了没用）",
              role_prompt, r"notMine\.joinToString")
    c.present("认不出角色时 fail-closed（说它什么都做不了）", role_prompt, r"if \(actor == null\)[\s\S]{0,200}?查不到也改不了")

    # ---- §6 指路只能用他真有的页面（用户 2026-09-17 抓到的 bug） ----
    ai_role_prompt = read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiRolePrompt.kt")
    modules = read(UI / "nav/Modules.kt")
    c.present("页面清单从界面配置算出来（不手写）", role_prompt, r"Modules\.entriesFor\(Role\.fromKey\(role\.key\)\)")
    c.present("提示词里带上了「他界面上有的页面」这一行", role_prompt, r"他界面上有的页面")
    c.present(
        "指路规则按「有没有那个页面」分两种说法",
        role_prompt,
        r"他\*\*没有\*\*那个页面[\s\S]{0,120}?不要指任何页面",
    )
    c.absent(
        "不再无条件「告诉他去哪个页面自己做」（货主没有派单/商品/库存页，会被指到墙上）",
        role_prompt,
        r"并告诉他去哪个页面自己做。",
    )
    c.present("货主身份段写明派单是派单员的活", role_prompt, r"派单是派单员的活")
    c.present("货主身份段写明他自己没有派单这个操作", role_prompt, r"没有派单这个操作")
    c.present(
        "货主的写能力白名单里**有**下单（指路指的就是它）",
        read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt"),
        r"SHIPPER_ACTIONS[\s\S]{0,600}?ORDERS_CREATE",
    )
    # ⚠️ 下面这条要先确认**真的取到了**那段白名单：取不到时传空串进去，
    #    `absent` 会永远通过——那就是"永远绿的检查"，比没有检查更糟。
    m_ship = re.search(
        r"SHIPPER_ACTIONS: Set<String> = setOf\(([\s\S]*?)\n    \)",
        read(ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt"),
    )
    c.ok("取到货主动作白名单（取不到这条检查就是空转）", m_ship is not None and len(m_ship.group(1)) > 50)
    if m_ship:
        c.absent(
            "货主白名单里不许出现派单动作（他被问派单只能指向派单员）",
            m_ship.group(1),
            r"ORDERS_ASSIGN|orders\.assign|ORDER_DISPATCH|ASSIGN",
        )
    c.present("界面配置里货主确实有「下单」入口（指路指的就是它）", modules, r'ModuleEntry\("下单"')

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
