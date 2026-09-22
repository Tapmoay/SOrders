"""红线：**工作台头部**＝一行（左文案 + 右侧描边角色胶囊），三端里只做货主与派单员。

## 由来（用户 2026-09-22，贴了两张截图，两轮口述）

第一轮（POS 的绿色头部 + 我们的工作台浅蓝卡）：
> 「将图二的 ui 形式**参考图一**的 ui 形式进行修改，**淡出一点**，就是**不要照抄图一的**。」

第二轮（看了我出的方案之后定稿）：
> 「这次做的样式它是**比较长，且扁**的，就是**能用一行的概括就概括**。然后我们那个**铃铛**
> 就是信息啊，**未读的那个不需要**吧，因为我们在**导航栏已经有了**。所以他要展出的信息是什么？
> **货主的标签 + 工作台**，也就是说「**工作台 · 订单与账本**」在**左边**，然后**货主的标签
> 放在右边**，并且以他的那个**管理员的形式**……一个圆圈的**虚线进行框住**，但是我们**不需要
> 那个三角**。然后**我们管理员的那一方**也采用这样子的形式做一个改动。」
>
> 拍板：「可以了那就直接开始做吧，但是有 1.1 有一个**单是不需要做的，那就是司机**……
> 也就是说，**只要做派单员和货主**。」

## 这条规则会被写坏成什么样（每一条都"不报错、不崩"）

| 写坏的方式 | 表现 |
|---|---|
| 头部又长回三行（标题一行 + 副标题一行） | 「长而扁」这条要求当场没了，而页面看起来"也挺正常" |
| 把角色名同时写在左文案里和右边胶囊上 | 同一句话在一行里说两遍（用户就是要"一行概括"，重复就是没概括） |
| 抄了图一的铃铛/未读 | **与底部导航「消息」那颗红点重复**；用户明确说"不需要，导航栏已经有了" |
| 抄了图一的扫码图标 | 我们本来就没有扫码（商品管理那轮已明确不抄条码）——一个点了没反应的图标 |
| 给胶囊加回下拉三角（`ArrowDropDown`） | 图一那是"可切换身份"的意思；我们没有（切账号在「我的」里），点了只会让人找有没有菜单 |
| 胶囊又变回**粉彩实底** | 用户要的是"淡出一点"，实底比描边重；而且底色一起变就没人再看得住"角色 → 颜色"这条对应 |
| 角色配色被抄成第二份（头部自己写一套） | 换个角色色要改两处，改漏一处**看不出来**（两个淡色差一点点） |
| 允许截断（`TextOverflow.Ellipsis` / `maxLines = 1`） | 系统字号一调大，「工作台 · 订单与账本」被切成「工作台 · 订…」——设计规范 §4.19 明令不缩字号、不截断 |
| 可伸缩的文本没写 `weight(1f)` | 它会去吃宽度、把右边那颗胶囊挤瘪（§4.19 第二条教训，真机 411dp 就能看见） |
| 顺手给**司机端**也加一个工作台 Tab | 用户第 1.1 条点名"司机不做"——那一端压根没有这个形态 |
| 改了头部文案却不改 `_install_all.py` 的角色强标志 | 装包脚本从此报"没抓到角色标志文字"，而 App 一切正常（最像"工具坏了"的那种坏） |

## 判据
Android：`ui/home/WorkbenchScreen.kt`（`WelcomeBar` 一行 + `workbenchHeaderText` 一处定义）、
`ui/common/Components.kt`（`RoleBadge` 描边形态 + `rolePaletteOf` 唯一色源）；
单测 `WorkbenchHeaderTest`（三端文案 + 司机端没有工作台这一屏）。
配套：`_tools/qa/_install_all.py` 的角色强标志、设计规范 §4.13、定位表「工作台」那一行。

⚠️ 注入式反向验证：`_tools/qa/_reverse_verify_workbench_header.py`（每条都必须能红）。

用法：python _tools/qa/_check_workbench_header.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用兄弟红线里剥注释的实现，不抄第二份。
#: ⚠️ **必须剥注释**：上面那些"⛔ 别抄铃铛"的话本身就写在注释里，不剥的话
#:    "代码里没有铃铛/三角"这几条判据会被自己的注释永远弄红（或被绕过）。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
WORKBENCH = ANDROID / "ui/home/WorkbenchScreen.kt"
COMPONENTS = ANDROID / "ui/common/Components.kt"
MODULES = ANDROID / "ui/nav/Modules.kt"
HEADER_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/home/WorkbenchHeaderTest.kt"
INSTALL = ROOT / "_tools/qa/_install_all.py"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8")


def read_code(p: Path) -> str:
    return strip_comments(read(p))


def k_r_end(src: str, start: int) -> int:
    """从 [start] 处（一个函数定义的开头）取到**下一个顶层函数定义**为止。"""
    nxt = src.find("\nfun ", start + 10)
    if nxt < 0:
        nxt = src.find("\nprivate fun ", start + 10)
    return nxt if nxt > start else start + 1500


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
        self.ok(label, m is None, f"命中：{m.group(0)[:60]!r}" if m else "")


def main() -> int:
    c = Checker()
    workbench = read_code(WORKBENCH)
    components = read_code(COMPONENTS)
    raw_components = read(COMPONENTS)
    raw_workbench = read(WORKBENCH)

    print("== 1. 头部是**一行**（左文案 + 右胶囊），不是三行卡 ==")
    # 取 `WelcomeBar` 自己的函数体（到下一个顶层 `}` + 空行为止）
    i = workbench.find("private fun WelcomeBar(")
    j = workbench.find("\nprivate fun ", i + 10) if i >= 0 else -1
    body = workbench[i:j if j > i else (i + 2500)] if i >= 0 else ""
    c.ok("找得到 `WelcomeBar`（取不到这几条就是空转）", len(body) > 200, f"只有 {len(body)} 字符")
    # ⚠️ 一行 = 只有**一个**行容器（多一个 Row/Column 就是"偷偷又长出一行"）。
    #    与 `_check_order_driver_call.py` 里"按钮与信息同排"同一个判据形状。
    n_row = len(re.findall(r"(?<![\w.])Row\s*[({]", body))
    n_col = len(re.findall(r"(?<![\w.])Column\s*[({]", body))
    c.ok(f"组件里只有 1 个行容器（找到 {n_row} 个 Row / {n_col} 个 Column）",
         n_row == 1 and n_col == 0,
         "多出来的容器就是把三行卡又长回来了")
    c.present("左边那条文案来自唯一那处判据（`workbenchHeaderText`）",
              body, r"workbenchHeaderText\(role\)")
    c.present("右边就是角色胶囊（`RoleBadge`）", body, r"RoleBadge\(role\.key\)")
    c.present("文案吃剩余宽度（`weight(1f)` —— §4.19：不写会把右边的胶囊挤瘪）",
              body, r"Modifier\.weight\(1f\)")
    c.present("垂直内边距**小**（扁：12dp，原来是 20dp 的三行卡）", body, r"vertical = 12\.dp")

    print("\n== 2. 一行放不下时**不缩字号、不截断**（设计规范 §4.19）==")
    c.present("文案最多折到两行（`maxLines = 2`）", body, r"maxLines = 2")
    c.absent("⛔ 没有 `Ellipsis`（截断会把「工作台 · 订单与账本」切成半句）",
             body, r"TextOverflow\.Ellipsis")
    c.absent("⛔ 没有写死 `maxLines = 1`（那等于「放不下就切」）", body, r"maxLines = 1\b")

    print("\n== 3. 图一里**不抄**的那几件一件都不许溜进来 ==")
    c.absent("⛔ 没有铃铛/未读（用户：「导航栏已经有了」）",
             workbench, r"Icons\.Default\.Notifications|unread")
    c.absent("⛔ 没有扫码（我们本来就没有扫码）",
             workbench, r"QrCode|Barcode|扫码")
    # ⚠️ 窗口**只取 RoleBadge 自己的函数体**：`Components.kt` 里别处还有一个真的下拉箭头
    #    （那是另一个组件），拿整份文件判会**假红** —— 假红的下场就是下一个人把这条删掉。
    kr = components.find("fun RoleBadge(")
    kb0 = components[kr: k_r_end(components, kr)] if kr >= 0 else ""
    c.absent("⛔ 胶囊上没有下拉三角（用户：「不需要那个三角」）",
             kb0, r"ArrowDropDown|KeyboardArrowDown")

    print("\n== 4. 三端文案只有一处实现，且与右边胶囊不重复 ==")
    c.present("`workbenchHeaderText` 在**这里**定义（唯一一处）", workbench,
              r"fun workbenchHeaderText\(role: Role\): String = when \(role\)")
    defs = [
        p.relative_to(ROOT).as_posix()
        for p in sorted(ANDROID.rglob("*.kt"))
        if "fun workbenchHeaderText(" in p.read_text(encoding="utf-8")
    ]
    c.ok(f"全源码树里**只有一处定义**（共 {len(defs)} 个文件）",
         defs == ["android/app/src/main/java/com/tapmoay/sorders/ui/home/WorkbenchScreen.kt"],
         f"实际在：{defs}")
    for role_cn, text in (("货主", "工作台 · 订单与账本"), ("派单员", "工作台 · 全量管理")):
        c.present(f"{role_cn}那一支的文案是「{text}」", workbench, re.escape(text))
    # ⛔ 左文案里不许再出现"某端"（角色已经由右边胶囊说了）
    c.absent("⛔ 左文案里不再出现「货主端 / 派单端 / 司机端」",
             workbench, r"货主端|派单端|司机端")

    print("\n== 5. 角色胶囊：**细描边 + 透明底 + 同色字**，配色只有一处 ==")
    k = components.find("fun RoleBadge(")
    kb = components[k: k + 1200] if k >= 0 else ""
    c.present("用的是 `Surface` + `border`（描边），不是实底", kb,
              r"border = BorderStroke\(1\.dp, accent\)")
    c.present("底色透明（透明底＝「淡出一点」的那一半）", kb, r"color = Color\.Transparent")
    c.present("字色取同一个强调色（描边与字同色）", kb, r"color = accent")
    c.present("两端半圆（`CircleShape`）", kb, r"CircleShape")
    c.present("配色只有一处（`rolePaletteOf`）", components,
              r"internal fun rolePaletteOf\(role: String\): RolePalette")
    # ⚠️ 亮/暗两档都得在：暗色页面用亮色（见 badgeColors 的说明），少一档就是"暗色下那个胶囊糊了"。
    #    锚在**每一支都有两个颜色**这个结构上（只锚"出现过 Color"的话，把暗色那个删掉照样绿）。
    #    ⚠️ 兜底那一支的标签是变量（`RolePalette(role, …)`），所以第一格要认两种写法。
    pi = components.find("internal fun rolePaletteOf(")
    palette = components[pi: k_r_end(components, pi)] if pi >= 0 else ""
    pairs = re.findall(
        r'RolePalette\((?:"[^"]*"|\w+),\s*Color\(0xFF[0-9A-Fa-f]{6}\),\s*Color\(0xFF[0-9A-Fa-f]{6}\)\)',
        palette,
    )
    c.ok(f"每一支都给足了亮/暗两档色（找到 {len(pairs)} 支，应有 4 支 = 三种角色 + 兜底）",
         len(pairs) == 4, f"实际 {len(pairs)} 支：{pairs[:2]}")
    defs2 = [
        p.relative_to(ROOT).as_posix()
        for p in sorted(ANDROID.rglob("*.kt"))
        if "fun rolePaletteOf(" in p.read_text(encoding="utf-8")
    ]
    c.ok(f"`rolePaletteOf` 也**只有一处定义**（共 {len(defs2)} 个文件）",
         defs2 == ["android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt"],
         f"实际在：{defs2}")
    c.present("`badgeColors` 没被顺手删掉（`OrderStatusChip` 还在用它）",
              components, r"private fun badgeColors\(")
    c.present("`OrderStatusChip` 仍然在用 `badgeColors`", components,
              r"OrderStatusChip[\s\S]{0,400}?badgeColors\(")

    print("\n== 6. 司机端**不做**（用户第 1.1 条） ==")
    modules = read_code(MODULES)
    driver_tabs = re.search(r"Role\.DRIVER -> listOf\(([\s\S]{0,600}?)\)\n", modules)
    c.ok("取得到司机端的底部导航（取不到这条就是空转）", driver_tabs is not None)
    if driver_tabs:
        c.absent("⛔ 司机端的 Tab 里**没有**工作台（`\"workbench\"`）",
                 driver_tabs.group(1), r'"workbench"')
        c.present("司机端的四个 Tab 还是老样子（进行中 / 已完成 / 消息 / 我的）",
                  driver_tabs.group(1), r'BottomTab\("进行中"[\s\S]{0,200}?BottomTab\("已完成"')
    shipper_tabs = re.search(r"else -> listOf\(([\s\S]{0,400}?)\)\n", modules)
    c.present("货主端的 Tab 里**有**工作台", shipper_tabs.group(1) if shipper_tabs else "",
              r'"workbench"')
    c.present("派单端的 Tab 里**有**工作台", modules,
              r"Role\.DISPATCHER -> listOf\([\s\S]{0,300}?BottomTab\(\"工作台\"")

    print("\n== 7. 单测与配套（改了却没跟上 = 下一轮没人知道） ==")
    c.ok("有单测文件", HEADER_TEST.exists(), f"缺 {HEADER_TEST.name}")
    if HEADER_TEST.exists():
        t = read(HEADER_TEST)
        c.present("单测钉着三端文案", t, r'assertEquals\("工作台 · 订单与账本", workbenchHeaderText\(Role\.SHIPPER\)\)')
        # ⚠️ 锚要**带上 `assertFalse(`**：只锚 `it.content == "workbench"` 的话，货主那一端
        #    也有一模一样的字符串 → 把司机那条断言翻成 assertTrue 照样绿（反向验证抓到的 MISS）。
        c.present("单测钉着「司机端没有工作台这一屏」", t,
                  r'assertFalse\([\s\S]{0,240}?it\.content == "workbench"')
        c.present("单测钉着文案里不再出现「某端」", t, r'text\.contains\("端"\)')
    install = read(INSTALL)
    # ⚠️ 判据**只取那两行常量**（`DEVICES` 的两条 + `STRONG_MARK`），不拿整份文件判：
    #    文件里有一条注释写着"旧文案改成新文案"（那正是改动的记录），拿整份文件判会**假红**。
    #    ⚠️ 也不要用 `strip_comments`：它只剥 `//` 与 `/* */`，**不剥 Python 的 `#`**。
    mark_lines = [ln for ln in install.splitlines()
                  if ln.startswith("STRONG_MARK") or ('"5554"' in ln or '"5556"' in ln)]
    marks = "\n".join(mark_lines)
    c.ok("取到了装包脚本的角色标志那几行（取不到这条就是空转）", len(mark_lines) >= 3,
         f"只有 {len(mark_lines)} 行")
    c.present("强标志换成了新的两句", marks,
              r'"工作台 · 全量管理"[\s\S]{0,80}?"工作台 · 订单与账本"')
    c.absent("⛔ 标志文字里不再留着旧文案「货主端 · 订单与账本」", marks,
             r"货主端 · 订单与账本")
    c.absent("⛔ 标志文字里不再留着旧文案「派单端 · 全量管理」", marks,
             r"派单端 · 全量管理")
    design = read(DESIGN)
    c.present("设计规范 §4.13 那一段写了这个头部形态（「工作台 · 订单与账本」+ 描边胶囊）",
              design, r"工作台 · 订单与账本[\s\S]{0,600}?RoleBadge|RoleBadge[\s\S]{0,600}?工作台 · 订单与账本")
    c.present("并且**指路到本判据**", design, r"_tools/qa/_check_workbench_header\.py")
    loc = read(LOCATOR)
    # ⚠️ 只认「工作台」那一行 + **带 `_tools/qa/` 前缀的完整写法**：这一行里"脚本名"出现过两次
    #    （一次是"判据只有一处，见 xxx"，一次是末尾的"红线 xxx"），拿整份文件判的话，
    #    把末尾那条指路删掉照样绿（反向验证当场抓到的 MISS）。
    rows = [ln for ln in loc.splitlines() if ln.startswith("| **工作台")]
    c.ok("定位表有「工作台」那一行（正好 1 行）", len(rows) == 1, f"命中 {len(rows)} 行")
    c.present("定位表那一行**指路到本判据**（带 `_tools/qa/` 前缀的写法）",
              rows[0] if rows else "", r"红线 `_tools/qa/_check_workbench_header\.py`")
    _ = (raw_components, raw_workbench)  # 原始文本（含注释）只用于"文件读得到"这件事

    print("\n" + "=" * 60)
    total = c.passes + len(c.fails)
    if total < 24:
        print(f"❌ 只跑了 {total} 条判据（< 24）—— 判据在空转，停。")
        return 1
    if c.fails:
        print(f"❌ {len(c.fails)} 项不达标：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过：工作台头部是一行（左文案 + 右描边胶囊），只做货主与派单员。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
