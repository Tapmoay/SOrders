"""AI 助手那一页的单色强调由 Google 蓝改成绿（CHG-0093；CHG-0104 起是 AI 页自己的绿）—— 一处定义、三处被框住的地方。

## ⚠️ CHG-0104（2026-10-10）改的是「绿的来源」，不是「绿这件事」
用户 2026-10-10 说「它的主颜色还是绿色……它就像微信一样……因为我希望让使用，用人跟微信一样
亲切啊」（ref `m04856`）。CHG-0093 当年把 `AiAccent` 绑到全 App 的 `ThemeGreen` 上，
CHG-0101 换主操作色时这一页就**隔着文件跟着一起**变成了红棕。
CHG-0104 给它解绑：`AiChatGreen`（强调档）/ `AiChatGreenDeep`（实心档＋白字）是 AI 这一片
**自己的**两个 token。
⇒ 下面每条判据的**意图一个字没改**，只把锚点从 `ThemeGreen` / `ThemeGreenDeep` 换成
`AiChatGreen` / `AiChatGreenDeep`，并补了一条「⛔ 不许再绑回 `ThemeGreen`」。

## 用户要的是什么（2026-10-09，ref m03583）
用户发来「AI 助手」聊天页的截图，**红框圈了三处**：顶栏右侧那三颗图标（历史 / 新对话 / 设置）、
输入行左边那颗 **⊕**、右下那颗**圆形发送键**。原话：「这个也改成就是我框起来的，也改成类似的绿色
就是**统一主题**哦，颜色，**可以做一些稍微的区别**，然后就是给所有的模拟器都改完之后，给所有模有的
模拟器都装上。」
⇒ 本判据钉两件事：① 这一页的**单色强调**（`AiAccent`，一处定义、25 个消费点）必须是**绿**；
② 发送键作为"主行动"**深一档**（CHG-0104 起是 `AiChatGreenDeep`）—— 用户明确给了"可以做一些稍微的区别"这句话。

## 为什么这条必须有机器的判据（这里每一处坏了都不报错、不崩、测试也不会红）
1. **强调色退回蓝**：`private val AiAccent = Color(AiBlue)` 换回去，这一页 25 个消费点
   （三颗图标、⊕、会话选中态、侧栏、抽屉、块引、代码块描边）**逐处都还能编译**，
   只是整页又变成 Google 蓝 —— 没有一行测试会红。
2. **设置页没跟上**：`AiSettingsScreen` 的 `accent` 是**另一处**定义（不是同一个常量），
   谁只改了聊天页，齿轮点进去那一页还是蓝的 —— 同一片表面一半绿一半蓝，照样没人报错。
3. **发送键退回"跟图标同色"**：用户给的是"可以做一些稍微的区别"，
   把 `else -> SolidColor(Color(AiChatGreenDeep))` 改回 `SolidColor(AiAccent)` 编译、运行全正常，
   只是主行动与入口一样重了 —— 这是**用户点名要的差别**，只有判据能守。
4. **两档区别被抹平**：`!canSend -> SolidColor(AiAccent.copy(alpha = 0.45f))`（浅绿 = 还没东西可发）
   若被改成实心深绿，"可发 / 不可发"就彻底看不出来了（用户 2026-09-18 报过「看不清」）。
5. **改色顺手改坏了别的**：这一页的图标名、`onClick`、`enabled`、52dp 尺寸、发送键三态语义
   与文案，任何一处被"顺手整理"，功能都会变（比如 `onClick` 里那个 `onStop()` 没了 = 发送中按不动）。
6. **品牌三段渐变被误伤**：`AiBrand.kt` 的蓝→紫→粉是"AI 品牌徽章"（工作台圆钮、空状态星标），
   本单**刻意不动**；`android/app/src/test/java/com/tapmoay/sorders/ui/nav/ModulesEntryTest.kt`
   还断言着 `ai.gradient == listOf(AiBlue, AiPurple, AiPink)` 与 `ai.color == AiBlue` ——
   谁把品牌三色一起刷绿，那条单测会红，但"该不该绿"这件事单测说不清，所以这里正面钉住"它没被动过"。
7. **别人家的页面**：`ui/ai/AiOperationsScreen.kt`（AI 操作日志）里原来还有两处
   `Color(AiBlue)` —— CHG-0104 已经把它们一起收敛了（齿轮点进去的上一级就是设置页，
   两页同一个控件不能一个绿一个蓝），所以第 6 节的**豁免名单已经清空**，
   现在整目录一处 `AiBlue` 都不许剩。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
上面 7 条**没有一条是类型属性**：`Color` 与 `Color` 之间没有类型差（`#4285F4` 与 `#00A870` 同型），
`SolidColor(A)` 与 `SolidColor(B)` 也是同一个类型；第 5 条那些"顺手改坏"的写法（`onClick` 少一个分支、
`enabled` 写成 true）更是**完全合法的 Kotlin**—— 编译器、类型系统、单测都拦不住。
所以判据只能落在**源码结构**上："哪个常量等于哪个值""那一句还在不在""这个名字还是不是那个名字"，
再配反向验证 `_reverse_verify_ai_accent_green.py`（把每一条分别弄坏一次，看它真的变红）。

静默空转保护：`MIN_KT = 100`（目录被搬走 / 一个 .kt 都没扫到就红，不许"扫了 0 个也全绿"）。

## 判据
1. `ui/ai/AiChatScreen.kt`：`AiAccent = Color(AiChatGreen)`（不再是 `Color(AiBlue)`，
   ⛔ 也不再是 `Color(ThemeGreen)`）；import 了 `AiChatGreen` / `AiChatGreenDeep`、
   不再 import `AiBlue`；KDoc 里留了用户口径与 ref；
2. 顶栏三颗图标（`History` / `AddComment` / `Settings`）＋ 输入行 ⊕ 全都读 `AiAccent`，
   且图标名 / `contentDescription` / `onClick` / `TapTarget` 逐字未动；
3. 发送键：`else -> SolidColor(Color(AiChatGreenDeep))`、`!canSend -> SolidColor(AiAccent.copy(alpha = 0.45f))`、
   `sending -> SolidColor(MaterialTheme.colorScheme.error)` 三态齐全，`onClick` / 52dp / `CircleShape` /
   `Stop ↔ ArrowUpward` 逐字未动，⛔ 不再退回单色强调；
4. `ui/ai/AiSettingsScreen.kt`：`val accent = Color(AiChatGreen)` ＋ 分段控件 `Color(AiChatGreenDeep)`，
   没有 `Color(AiBlue)` 残留；
5. **品牌三段渐变没被动过**（正面证据）：`AiBrand.kt` 的三色定义、`Color.kt` 的三个 token、
   两个消费者（工作台圆钮、空状态星标）都还在；
6. 全仓 `ui/ai/*.kt` 里**一处 `AiBlue` 都不剩**（CHG-0104 起豁免名单为空）。

用法：python _tools/qa/_check_ai_accent_green.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AI_DIR = AND / "ui/ai"
SCREEN = AI_DIR / "AiChatScreen.kt"
SETTINGS = AI_DIR / "AiSettingsScreen.kt"
BRAND = AND / "ui/theme/AiBrand.kt"
COLOR = AND / "ui/theme/Color.kt"
HOME = AND / "ui/home/RoleHomeScreen.kt"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 仍在读 AiBlue 的例外文件。⚠️ 这个名单只许变短。
#: CHG-0104（2026-10-10）把最后的 `AiOperationsScreen.kt` 也收掉了 ⇒ 现在是**空的**，
#: 第 6 节因此升级成「整目录一处都不剩」。以后再加回任何名字，都必须先说明理由。
AI_BLUE_EXEMPT: set[str] = set()


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
        m = re.search(pattern, text, re.M)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    为什么要这样：本单的"用户原话 / 历史"全写在注释里，其中就抄着 `Color(AiBlue)`、
    `AiBlue` 这些**看起来像代码**的字样 —— 判据抓的是**代码里**还有没有人在用它。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def main() -> int:
    c = Checker()
    screen = read(SCREEN)
    settings = read(SETTINGS)
    brand = read(BRAND)
    color = read(COLOR)
    home = read(HOME)
    screen_code = code_only(screen)
    settings_code = code_only(settings)
    brand_code = code_only(brand)

    kt = sorted(AND.rglob("*.kt"))

    print("== 0. 反空转：扫描本身得是活的 ==")
    c.ok(f"扫到 {len(kt)} 个 .kt（下限 {MIN_KT}）", len(kt) >= MIN_KT)

    print("\n== 1. 聊天页：单色强调由 Google 蓝换成 AI 页自己的绿（CHG-0104 起） ==")
    c.present("AiAccent = AI 页自己的绿（CHG-0104 起与主操作色解绑）", screen_code,
              r"private val AiAccent = Color\(AiChatGreen\)")
    c.absent("AiAccent 不再是 Google 蓝", screen_code,
             r"private val AiAccent = Color\(AiBlue\)")
    # ⚠️ CHG-0104：绿的来源从全 App 主操作色 ThemeGreen 换成 AiChatGreen 之后，
    #    「绑回主操作色」**重新**成了一种看上去很合理的改法 —— CHG-0101 换主色时
    #    这一页就是因为当初写成 `Color(ThemeGreen)` 才跟着一起变红棕的。这条盯住它。
    c.absent("AiAccent 没有再绑回 ThemeGreen（那正是 CHG-0104 的病根）", screen_code,
             r"private val AiAccent = Color\(ThemeGreen\)")
    c.present("import 了 AiChatGreen", screen, r"^import com\.tapmoay\.sorders\.ui\.theme\.AiChatGreen$")
    c.present("import 了 AiChatGreenDeep（发送键那一档要用）", screen,
              r"^import com\.tapmoay\.sorders\.ui\.theme\.AiChatGreenDeep$")
    c.absent("不再 import AiBlue（用途没了，留着就是死 import）", screen,
             r"^import com\.tapmoay\.sorders\.ui\.theme\.AiBlue$")
    # 这一条查的是**注释**（用户口径留档），所以喂原文、不喂 code_only。
    c.present("KDoc 里留了用户口径与 ref m03583（换色的根据）", screen, r"ref `m03583`")
    c.present("KDoc 写明品牌渐变不在这里（免得下次有人顺手把它也刷绿）", screen,
              r"品牌三段渐变（\[aiBrandBrush\] 的蓝→紫→粉）\*\*不在这里\*\*")

    print("\n== 2. 顶栏三颗图标 ＋ 输入行 ⊕：都读 AiAccent，形状一个字符没动 ==")
    c.present("顶栏：历史（History + 抽屉）", screen_code,
              r"Icons\.Default\.History,\s*\n\s*contentDescription = \"历史对话\",\s*\n\s*tint = AiAccent,")
    c.present("顶栏：新对话（AddComment + vm.newChat()）", screen_code,
              r"Icons\.Default\.AddComment,\s*\n\s*contentDescription = \"新对话\",\s*\n\s*tint = AiAccent,")
    c.present("顶栏：设置（Settings + onOpenSettings）", screen_code,
              r"Icons\.Default\.Settings,\s*\n\s*contentDescription = \"设置\",\s*\n\s*tint = AiAccent,")
    c.present("历史那颗仍是开抽屉（onClick 未动）", screen_code,
              r"onClick = \{ scope\.launch \{ drawerState\.open\(\) \} \},")
    c.present("新对话那颗仍是 vm.newChat()（onClick 未动）", screen_code,
              r"onClick = \{ vm\.newChat\(\) \},")
    c.present("设置那颗仍是 onOpenSettings（onClick 未动）", screen_code,
              r"IconButton\(onClick = onOpenSettings, modifier = Modifier\.size\(TapTarget\)\)")
    c.present("三颗图标仍是 24dp（尺寸未动）", screen_code,
              r"tint = AiAccent,\s*\n\s*modifier = Modifier\.size\(24\.dp\),")
    c.present("⊕ 仍是「展开则 Close、否则 Add」", screen_code,
              r"if \(panelOpen\) Icons\.Default\.Close else Icons\.Default\.Add,")
    c.present("⊕ 的着色：发送中退成 outline、否则 AiAccent", screen_code,
              r"tint = if \(sending\) MaterialTheme\.colorScheme\.outline else AiAccent,")
    c.present("⊕ 仍是「发送中不可点」", screen_code,
              r"IconButton\(onClick = onTogglePanel, enabled = !sending\)")

    print("\n== 3. 发送键：主行动深一档，三态与语义逐字未动 ==")
    c.present("可发送 = 深一档（用户说的「稍微的区别」）", screen_code,
              r"else -> SolidColor\(Color\(AiChatGreenDeep\)\)")
    c.absent("⛔ 可发送不再与三颗图标同色（退回单色强调就是抹掉主次）", screen_code,
             r"else -> SolidColor\(AiAccent\)")
    c.present("不可发送 = 淡绿（看得见按钮、但看得出还不能发）", screen_code,
              r"!canSend -> SolidColor\(AiAccent\.copy\(alpha = 0\.45f\)\)")
    c.present("发送中 = 单色红（危险动作，不跟主题绿混）", screen_code,
              r"sending -> SolidColor\(MaterialTheme\.colorScheme\.error\)")
    c.present("onClick：发送中＝停止、否则能发才发（一个字没动）", screen_code,
              r"onClick = \{ if \(sending\) onStop\(\) else if \(canSend\) onSend\(\) \},")
    c.present("仍是 52dp 圆形", screen_code,
              r"modifier = Modifier\.size\(52\.dp\),\s*\n\s*shape = CircleShape,")
    c.present("图标仍是 Stop ↔ ArrowUpward", screen_code,
              r"imageVector = if \(sending\) Icons\.Default\.Stop else Icons\.Default\.ArrowUpward,")
    c.present("无障碍描述仍是「停止 / 发送」", screen_code,
              r"contentDescription = if \(sending\) \"停止\" else \"发送\",")

    print("\n== 4. 设置页：同一片表面的另一半也得是绿的 ==")
    c.present("accent = AI 页自己的绿（思考档位那一行的强调色）", settings_code,
              r"val accent = Color\(AiChatGreen\)")
    c.present("SegmentedPicker 的 accent 同源", settings_code,
              r"accent = Color\(AiChatGreenDeep\),")
    c.absent("设置页里没有 Color(AiBlue) 残留", settings_code, r"Color\(AiBlue\)")
    c.absent("设置页不再 import AiBlue", settings, r"^import com\.tapmoay\.sorders\.ui\.theme\.AiBlue$")
    c.present("设置页 import 了 AiChatGreen", settings,
              r"^import com\.tapmoay\.sorders\.ui\.theme\.AiChatGreen$")

    print("\n== 5. 品牌三段渐变：本单刻意没动它（正面证据） ==")
    c.present("AiBrand：三色顺序仍是 蓝→紫→粉", brand_code,
              r"val AiBrandColors: List<Color> = listOf\(Color\(AiBlue\), Color\(AiPurple\), Color\(AiPink\)\)")
    c.present("AiBrand：画刷仍从这一处出", brand_code,
              r"fun aiBrandBrush\(\): Brush = Brush\.linearGradient\(AiBrandColors\)")
    c.present("Color.kt：AiBlue 这个 token 还在（品牌色没被删）", color,
              r"^val AiBlue = 0xFF4285F4L")
    c.present("Color.kt：AiPurple 还在", color, r"^val AiPurple = ")
    c.present("Color.kt：AiPink 还在", color, r"^val AiPink = ")
    c.present("消费者①：工作台 AI 圆钮仍用渐变", home,
              r"\.background\(aiBrandBrush\(\), CircleShape\)")
    c.present("消费者②：聊天页空状态星标仍用渐变", screen,
              r"\.background\(aiBrandBrush\(\), RoundedCornerShape")

    print("\n== 6. 全仓 ui/ai：一处 AiBlue 都不剩（CHG-0104 把豁免名单清空了） ==")
    strays: list[str] = []
    for p in sorted(AI_DIR.rglob("*.kt")):
        for i, line in enumerate(code_only(read(p)).splitlines(), 1):
            if "AiBlue" not in line:
                continue
            if p.name in AI_BLUE_EXEMPT:
                continue
            strays.append(f"{p.relative_to(ROOT)}:{i} {line.strip()[:60]}")
    c.ok("ui/ai 整目录一处 AiBlue 都不剩", not strays,
         "还在：" + " / ".join(strays[:5]))

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)}/{c.passes + len(c.fails)} 项没通过：")
        for f in c.fails:
            print(f"   - {f}")
        return 1
    print(f"✅ 全部 {c.passes} 项通过：AI 助手那一页的单色强调已是主题绿、发送键深一档，"
          f"品牌三段渐变与这一页的文案 / 图标 / 尺寸 / 语义一处未动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
