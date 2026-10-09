"""主操作色与商品块的配色：一次改了一大片（CHG-0091 立、CHG-0101 换过值）。

## 用户要的是什么
**CHG-0091（2026-10-09，ref m01501 ＋定稿 m01927 ＋当天追加口径 m02715）** —— 那一轮定的是**绿**：
原话：「**整体的颜色**……从蓝色变成绿色，**像微信那样**」「订单卡片的**商品的样式**……以图一的那个样式」
「如果是多个商品的话，他就是**多个样式**」「**包括订单详情**进去也是这个样式」；
定稿：「就选**甲方案**」「颜色的话就选**深绿色**吧……**因为太亮了不好，因为我们的核心要求是低饱和嘛**」
「商品名称**不留紫色**」；当天下午追加撤回（ref m02715）：「算了，算了，那个**背景的渐变，就去掉吧**……
**就是白色的默认色**」。

**CHG-0101（2026-10-09 晚）** —— 用户给了三张整体配色图，把上面那套绿**整片换掉**：
「按照它的配色方案进行一下修改以及我给你的那个照片」（m02474）、
「这是新任务吼也就是改我途中给你发的那些样式」（m02545），
并专门叮嘱「继续继续，但**我不希望整体太过于灰**啊」（m02683）。
图三点名的七个语义色：主操作（确认接单）#8B4A4A / 商品订单 #B5726B / 成功完成 #59A570 /
提醒重要 #C8A56A / 普通信息 #6B7F99 / 禁用辅助 #9B8F88 / 背景 #F7F6F3。
⇒ 所以本判据**同时钉两个方向**：该是新那套的（主操作色 / 商品胶囊 / 数量块）必须是新值；
**不该留的（绿主色、页面背景上那条渐变、顶栏被刷色）必须一处都不留**。
⚠️ 本文件的**形状**（钉哪些 token、哪一行、哪一种结构）在 CHG-0101 里没变，
   换的只是被钉住的**值** —— 所以它保留原名与九节结构，只在值上随动。

## 为什么这条必须有机器的判据（这里每一处坏了都不报错、不崩、测试也不会红）
1. **主操作色悄悄退回绿或蓝**：`NavBlue = ThemeGreen` 这行别名一断，全仓 16 处引用（底部两个 Tab、
   账户/挂账/用户/车辆管理页、`ModuleEntry.color` 的默认值）**逐处都还能编译**，
   只是界面又变回旧色 —— 没有一行测试会红。
2. **`InfoBlue` 没跟着走**：它是「信息」语义色，只有定义、0 引用，最容易被漏。
   漏了以后 §2 表里就出现"同一个色叫两个名 + 一个孤儿蓝"。
3. **商品块退回"紫方块 + 紫字"**：`ProductPurple` 仍在文件里（合计行还在用），
   谁把品名那行 `color = Color(OnProductRowTint)` 改回 `Color(ProductPurple)`，
   编译、跑测试、看列表**全都正常** —— 只是用户点名"不留紫色"那条被推翻。
4. **数量的拼法被顺手"整理"**：`"×" + qtyWithUnitConverted(op.quantity, op.unit, conversions)`
   是 §4.20 那一条（用户 2026-09-22「商品后面的数字没有单位啊……这是要有单位的」）的**唯一实现点**，
   而 `_check_order_row_columns.py` 就钉在这句正则上 —— 谁把它换成 `"x" + op.quantity`，
   这一页看着还是"有个数量"，另一条判据才红，而那时人已经在改别的东西了。
5. **商品块那一层又被挂回 `Modifier.weight(1f)`**（2026-10-09 **真机抓到的回归**，本判据第 3 节
   那两条就是为它加的）：改前这一块套在 `Row(verticalAlignment = Alignment.Top)` 里，`weight(1f)`
   是**横向**权重（占满宽度）；甲案把外面那层 Row 去掉之后，它成了页面级
   `Column(Modifier.padding(16.dp))` 的**直接子节点** —— 在 ColumnScope 里 `weight(1f)` 是
   **纵向**权重，而外层高度是 wrap content ⇒ 这一块拿到 **0 高**，整块商品区**一个像素都不画**。
   真机现象：`共 16 筐` 照常显示（那是同一列后面的另一行），两个商品名一个都不见。
   ⚠️ **编译绿、单测全绿、所有只看源码文本的判据全绿** —— 只有真机走查能看出来。
6. **页面顶上那条渐变被偷偷加回来**：用户当天就撤了它（ref m02715），`TopGreenFade` 与它的起色
   token 都已经删掉；谁"觉得好看"再加一条 `Brush.verticalGradient`，页面照常显示、不报错，
   只是把用户当天否掉的东西又摆了回来。同一族还有 `Scaffold` 又被铺上背景 / 顶栏又被刷成浅色。
7. **顶栏又被刷成浅色**：`AppTopBar` 是全 App 二级页共用的一条（52 个 `Scaffold` 都吃它），
   在这里换一次色＝**每一页的头都换**，而且编译测试全绿。
8. **暖砂白家族没跟上**：页面底若退回旧值，与新主色的浅底同屏会发脏。
   这一条由 `_check_warm_surface_palette.py` 正面盯着（本判据只做交叉引用，不重复实现）。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
上面 8 条**没有一条是类型属性**：`Color` 与 `Color` 之间没有类型差（`#8B4A4A` 与 `#00A870` 同型），
`Float` 与 `Float` 之间也没有，第 5 条那个 `weight(1f)` 更是一个**合法的 composable 修饰符**
（类型上完全正确，只是量出来是 0 高）—— 编译器、类型系统、单测都拦不住。
所以判据只能落在**源码结构**上："哪个 token 等于哪个值""那一句还在不在""这一层挂没挂 modifier"，
再配反向验证 `_reverse_verify_green_theme.py`（把每一条分别弄坏一次，看它真的变红）。

静默空转保护：`MIN_KT = 100`（目录被搬走 / 一个 .kt 都没扫到就红，不许"扫了 0 个也全绿"）。

## 判据
1. `Color.kt`：`ThemeGreen = 0xFF8B4A4A`、`NavBlue = ThemeGreen`、`InfoBlue = ThemeGreen`；
   Primary 四件套是同一族红棕；商品块四个 token（浅底 / 深字 / 深色块 / 块首图标）都在且是**裸 ARGB**；
2. 页面底四层是**暖砂白**（并交叉要求 `_check_warm_surface_palette.py` 认得这四个值）；
3. `OrderCard`：商品块是一块一行的圆角胶囊（`shapes.medium` ＋ `ProductRowTint` ＋ 8/6 内边距），
   品名 `OnProductRowTint`、数量白字压 `ThemeGreenDeep`，块间距 `spacedBy(6.dp)`，
   ⛔ 商品块那一层**只许有 `verticalArrangement`**（挂回 `weight(1f)` 就是第 5 条那个 0 高回归），
   ⛔ 品名那行**不再出现 `ProductPurple`**；
4. **数量的拼法与单位一个字没动**（`"×" + qtyWithUnitConverted(op.quantity, op.unit, conversions)`），
   `order.orderProducts.take(3)` 也逐字还在；
5. `RoleHomeScreen`：**不许**再出现 `TopGreenFade` / `Brush` / `PageGradientGreen`，
   `Scaffold` 也不再被铺背景、不再透明（页面底就跟着 `colorScheme.background` 走）；
6. `Components.kt` 的 `AppTopBar` 读 `background`（跟页面底同一档），**不再**读 `primaryContainer`；
7. 全仓不再有任何**硬编码的** `0xFF1E6FFF`（`Color.kt` 的 `SeedBlue` 那一行是唯一豁免）。

用法：python _tools/qa/_check_green_theme.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
COLOR = AND / "ui/theme/Color.kt"
CARD = AND / "ui/common/OrderCard.kt"
HOME = AND / "ui/home/RoleHomeScreen.kt"
COMPONENTS = AND / "ui/common/Components.kt"
PALETTE_CHECK = ROOT / "_tools/qa/_check_warm_surface_palette.py"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 主操作色那几个语义 token。
#: ⚠️ 本表在 **CHG-0101（2026-10-09 晚）** 随用户第三套整体配色图整体换过一次：
#:    原来是绿主题（#00A870 系），现在是用户画的**低饱和红棕**（#8B4A4A 系）。
#:    判据的形状没变 —— 还是"哪个 token 等于哪个值、必须是裸 Long"，
#:    换的只是被钉住的那个值。为什么换、换成什么，见 CHG-0101 的 ⑥。
GREEN_TOKENS = {
    "ThemeGreen": "0xFF8B4A4A",
    "ThemeGreenDeep": "0xFF6E3636",
    "ProductRowTint": "0xFFF0E2DC",
    "OnProductRowTint": "0xFF3A2420",
}

#: 亮色四件套（Primary 家族）。
PRIMARY_KIT = {
    "Primary": "Color(0xFF8B4A4A)",
    "PrimaryContainer": "Color(0xFFF0E2DC)",
    "OnPrimaryContainer": "Color(0xFF3A2420)",
}

#: 商品块里那句"数量的拼法"——§4.20 的唯一实现点，⛔ 一个字符都不许动。
QTY_EXPR = '"×" + qtyWithUnitConverted(op.quantity, op.unit, conversions)'


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

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    为什么要这样：本单的"用户原话/为什么"全写在注释里，其中就抄着
    `#1E6FFF`、`ProductPurple` 这些**看起来像代码**的字样 ——
    判据抓的是**代码里**还有没有人在用它。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def main() -> int:
    c = Checker()
    color = read(COLOR)
    card = read(CARD)
    home = read(HOME)
    components = read(COMPONENTS)
    palette = read(PALETTE_CHECK)

    kt = sorted(AND.rglob("*.kt"))

    print("== 0. 反空转：扫描本身得是活的 ==")
    c.ok(f"扫到 {len(kt)} 个 .kt（下限 {MIN_KT}）", len(kt) >= MIN_KT)

    print("\n== 1. Color.kt：主操作色是用户画的那套，旧名保留成别名 ==")
    # ⚠️ 这一行**没有** `L` 后缀（作者写的是 `0xFF8B4A4A`，不是 `0xFF8B4A4AL`）——
    #    所以收尾用 `[^\n]*$`，别去钉 `\b`（`A` 之后就是行尾注释，`\b` 会匹配不上）。
    c.present("ThemeGreen = #8B4A4A（用户图三的「主操作色（确认接单）」，CHG-0101）", color,
              r"^val ThemeGreen = 0xFF8B4A4A[^\n]*$")
    c.present("NavBlue 是 ThemeGreen 的别名（16 处引用不改调用点）", color,
              r"^val NavBlue = ThemeGreen\b")
    c.present("InfoBlue 也跟着换成 ThemeGreen", color,
              r"^val InfoBlue = ThemeGreen\b")
    # ⚠️ 这些 token 行尾**带对齐注释**（`val ThemeGreen = 0xFF8B4A4AL  // 主操作…`），
    #    所以收尾必须是 `[^\n]*$` 而不是 `\s*$`（`\s*` 遇到行尾注释就匹配不上）。
    for name, want in GREEN_TOKENS.items():
        c.present(f"{name} = {want}", color,
                  r"^val " + name + r" = " + re.escape(want) + r"[^\n]*$")
    for name, want in PRIMARY_KIT.items():
        c.present(f"{name} = {want}", color,
                  r"^val " + name + r" = " + re.escape(want) + r"[^\n]*$")
    # 这几个 token 必须是**裸 ARGB Long**：写成 Color(0x…) 会让用色处的类型对不上（实测编译不过）
    c.absent("商品块那几个 token 不是 Color(0x…)（必须是裸 Long）", color,
             r"^val (?:ThemeGreen|ThemeGreenDeep|ProductRowTint|OnProductRowTint) = Color\(")
    c.absent("没有留下没人用的 OnThemeGreen（白字直接写 Color.White，别供着一个死 token）", color,
             r"^val OnThemeGreen\b")

    print("\n== 2. 页面底那一层是暖砂白（口径改在 _check_warm_surface_palette.py） ==")
    for name, want in (("BackgroundLight", "0xFFF7F6F3"),
                       ("SurfaceVariantLight", "0xFFF1EFEA"),
                       ("SurfaceContainer", "0xFFEFECE6"),
                       ("SurfaceContainerHigh", "0xFFE4E0D9")):
        c.present(f"{name} = {want}", color,
                  r"^val " + name + r" = Color\(" + re.escape(want) + r"\)")
    c.present("隔壁那条判据的收入是近白家族（NEAR_WHITE）", palette, r"^NEAR_WHITE = \{")
    c.present("隔壁那条判据不再叫旧名（WARM）", palette, r"^NEAR_WHITE = \{")
    c.absent("隔壁那条判据里没有残留的 WARM 字典", palette, r"^WARM = \{")

    print("\n== 3. OrderCard：商品块 = 一块一个商品的圆角浅绿胶囊 ==")
    c.present("块与块之间 spacedBy(6.dp)", card, r"verticalArrangement = Arrangement\.spacedBy\(6\.dp\),")
    c.present("只画前三个商品（take(3) 逐字没动）", card, r"order\.orderProducts\.take\(3\)\.forEach \{ op ->")
    # ⛔ 2026-10-09 真机抓到的回归（这一节唯一一条"代码在、像素不在"的判据）：
    #    改前这一块套在 `Row(verticalAlignment = Alignment.Top)` 里，`weight(1f)` 是**横向**权重（占满宽度）；
    #    甲案把外面那层 Row 去掉后，它成了页面级 `Column(Modifier.padding(16.dp))` 的**直接子节点** ——
    #    在 ColumnScope 里 `weight(1f)` 是**纵向**权重，而外层高度是 wrap content ⇒ 这一块拿到 **0 高**，
    #    整块商品区一个像素都不画（真机现象：「共 16 筐」照常显示、两个商品名一个都不见）。
    #    ⇒ 从两头钉住这个形状：这一层**只许有** verticalArrangement，⛔ 不许挂任何 modifier。
    c.present("商品块那一层只有 spacedBy、没有别的修饰符", code_only(card),
              r"Column\(\s*\n\s*verticalArrangement = Arrangement\.spacedBy\(6\.dp\),\s*\n\s*\) \{")
    c.absent("商品块那一层没有 Modifier.weight(1f)（ColumnScope 里那是纵向权重 → 0 高）", code_only(card),
             r"Column\(\s*\n\s*modifier = Modifier\.weight\(1f\),\s*\n\s*verticalArrangement = Arrangement\.spacedBy\(6\.dp\),")
    c.present("块底 = 圆角 medium + ProductRowTint", card,
              r"\.clip\(MaterialTheme\.shapes\.medium\)\s*\n\s*\.background\(Color\(ProductRowTint\)\)\s*\n\s*\.padding\(horizontal = 8\.dp, vertical = 6\.dp\),")
    c.present("块首 = 圆底 tint 图标（ThemeGreen，13dp / 22dp）", card,
              r"TintedIcon\(Icons\.Default\.Inventory2, Color\(ThemeGreen\), size = 13\.dp, container = 22\.dp\)")
    c.present("品名 = SemiBold + OnProductRowTint（不留紫）", card,
              r"fontWeight = FontWeight\.SemiBold,\s*\n\s*color = Color\(OnProductRowTint\),")
    # ⚠️ 这条正则必须**一路串到颜色那一行**：`.clip(shapes.small)` 这种三行连排在本文件里
    #    有**两处**（另一处是别的小控件），只盯 `clip → background → padding` 的话，
    #    谁把数量文字从白字改成墨绿，正则仍会在**那另一处**命中 ⇒ 判据假绿。
    #    （这是实测踩到的：反验第 13 条一开始就是这么"注入没打中"的。）
    c.present("数量 = 白字压深绿块（shapes.small + ThemeGreenDeep）", card,
              r"fontWeight = FontWeight\.Bold,\s*\n\s*color = Color\.White,\s*\n\s*maxLines = 1,\s*\n\s*modifier = Modifier\s*\n\s*\.clip\(MaterialTheme\.shapes\.small\)\s*\n\s*\.background\(Color\(ThemeGreenDeep\)\)\s*\n\s*\.padding\(horizontal = 8\.dp, vertical = 3\.dp\),")
    c.present("数量的拼法逐字没动（§4.20 的唯一实现点）", card, re.escape(QTY_EXPR))
    # ⛔ 品名那一行不再穿紫色：ProductPurple 只许还留在合计行
    c.absent("商品块里没有 Color(ProductPurple) 了", code_only(card),
             r"color = Color\(ProductPurple\)")
    c.present("ProductPurple 仍在（合计行还在用，没被误删）", code_only(card),
              r"color = if \(highlight\) Color\(DangerRed\) else Color\(ProductPurple\)")

    print("\n== 4. RoleHomeScreen：页面背景**不留绿**（那条渐变当天就撤了） ==")
    # 2026-10-09 上午按 m01501 铺过"深绿→白"的渐变（TopGreenFade），下午被 m02715 撤掉：
    # 「算了，算了，那个背景的渐变，就去掉吧……就是白色的默认色」。
    # ⇒ 这一节从"渐变必须长这样"反过来变成"渐变必须不在了"：主界面那一层什么背景都不铺。
    c.absent("主界面不再自造渐变（TopGreenFade 已删）", code_only(home), r"TopGreenFade")
    c.absent("不再 import Brush（那层渐变是它唯一的用处）", home,
             r"import androidx\.compose\.ui\.graphics\.Brush")
    c.absent("不再 import PageGradientGreen（那个 token 已删）", home,
             r"import com\.tapmoay\.sorders\.ui\.theme\.PageGradientGreen")
    c.absent("Scaffold 不再被铺背景 / 不再透明", home,
             r"Scaffold\(\s*\n\s*modifier = Modifier\.background\(|containerColor = Color\.Transparent,")
    c.absent("Color.kt 里那个起色 token 已删（别留死 token）", code_only(color),
             r"\bPageGradientGreen\b")

    print("\n== 5. AppTopBar：顶栏回到页面底那一档（白的，不是浅绿） ==")
    c.present("顶栏底 = background（跟着页面底走）", components,
              r"containerColor = MaterialTheme\.colorScheme\.background,")
    c.absent("顶栏不再读 primaryContainer（那条浅绿当天撤了）", components,
             r"containerColor = MaterialTheme\.colorScheme\.primaryContainer,")

    print("\n== 6. 硬编码的旧主色：全仓清干净（Color.kt 的 SeedBlue 是唯一豁免） ==")
    # SeedBlue 留着是给暗色主题的；除此之外一处都不许剩。
    hits: list[str] = []
    for p in kt:
        for i, line in enumerate(code_only(read(p)).splitlines(), 1):
            if "1E6FFF" not in line:
                continue
            if "SeedBlue" in line:
                continue
            hits.append(f"{p.relative_to(ROOT)}:{i}")
    c.ok(f"全仓没有残留的硬编码 0xFF1E6FFF（豁免 SeedBlue）", not hits,
         "还在：" + ", ".join(hits[:6]) + ("…" if len(hits) > 6 else ""))
    c.present("SeedBlue 那一行还在（暗色主题还在用）", color, r"^val SeedBlue = Color\(0xFF1E6FFF\)")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)}/{c.passes + len(c.fails)} 项没通过：")
        for f in c.fails:
            print(f"   - {f}")
        return 1
    print(f"✅ 全部 {c.passes} 项通过：主操作色是用户画的低饱和红棕 #8B4A4A、"
          f"商品行是一块一块的胶囊、页面背景是暖砂白与顶栏同档（那条绿渐变早已撤掉）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
