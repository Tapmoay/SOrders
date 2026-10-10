"""红线：**「表单放在底部抽屉里」的那几页** ＋ **全 App 底部抽屉的底色**（2026-09-22）。

> 这个脚本原名 `_check_account_manage_ui.py`（起家时只管账户管理一页）。
> 2026-09-22 运费模板的「新建」也搬进抽屉之后，它管的是**一类页面**，所以按规矩改名 ——
> 文件名叫 `account_manage` 的话，下一个人把第三页搬成抽屉时**找不到该往哪儿加判据**，
> 那正是"清单过期 → 判据空转"的老路。
> ⛔ 新增这类页面时，在 `FREIGHT` 旁边照着加一组常量与一节判据（**清单就在本脚本里，不散在别处**）。

## 被管的页面 + 用户原话
| 页面 | 原话 |
|---|---|
| 账户管理 | 「**更改一下账户管理的卡片样式**…那个新增的弹窗（底部抽屉）**不要使用那个线框**，而是用**卡片**的形式」 |
| 运费模板 | 「**新增模板**也按照我们的样式进行来，但是他**不要使用弹窗**啊，**使用底部抽屉**，并且**底部抽屉是拉到最上面**」 |

## 为什么这些都得有机器判据（每一条都"改坏了不报错"）
1. **"底部抽屉是灰蓝的"根本不是谁写错了一个颜色**，而是 M3 的默认值：
   `ModalBottomSheet` 的容器色默认 = `BottomSheetDefaults.ContainerColor` →
   `SheetBottomTokens.DockedContainerColor` → `ColorSchemeKeyTokens.SurfaceContainerLow`
   （反编译 material3 **1.3.2** 的 `classes.jar` 看到的链），而本项目那个 token 是 `#EDEFF4`
   （B 比 R 高 7）。→ 改回去只要**一个字符**，表现却是"全 App 19 个抽屉又变回灰蓝"。
2. **"又写一个描边输入框"从来没报错过**：编译过、真机上"也能用"，只是那一页又变回
   "一堆矩形框浮在灰底上"（这个病已经犯过四次：新增商品 / 新增线路 / 账户管理 / 运费模板）。
   `FilterChip` 未选中时也带描边，是同一个坑的变体。
3. **"用弹窗还是用抽屉"是用户在意的形态**，换回 `AlertDialog` 同样不报错 ——
   表单立刻变成"小框里滚"。
4. **"拉到最上面"只是一行修饰符**（`fillMaxHeight()`）：删掉它抽屉就变回半截，
   而这几页字段不少，半截抽屉等于要滚着填。
5. **错误落在哪儿是踩过的坑**：写进页面级错误 = 抽屉**背后**的一句 snackbar = "点保存没反应"
   （抽屉是另一个窗口，正好把它盖住）。
6. **动作的左/右位置是用户定的规则**（「编辑一定在右边…因为我们的惯用手是右手…
   相反的操作就在左边」）—— 只是两行的先后顺序，谁顺手一挪就没了。

## 判据怎么保证不空转
- 每个被检查的文件都先查存在 + 读到的字符数下限（搬走/清空时先喊，不许安静全绿）；
- 底色那条**直接解析十六进制**算 R/G/B（不看注释、不看名字），并且**同时**卡上下界：
  带蓝要红、纯白也要红（刷成白，里面的白卡就糊了，用户要的"对比"就没了）；
- "谁在管这个颜色"那条要求 `Theme.kt` 里是**指向 token**（`= SheetSurface`），不是又抄一遍字面量；
- 全局那条（没有哪个抽屉自己传 `containerColor`）的清单是**算出来的**，不手写；

用法：python _tools/qa/_check_sheet_form_pages.py
配套：python _tools/qa/_reverse_verify_sheet_form_pages.py（**29** 种破坏方式全被抓）

## §8 是另一种形态（2026-10-04 · CHG-0021）
ui/dispatcher/LedgerCreateScreen.kt 的「这一笔记给谁」**不是表单**（它是"挑一条"的抽屉），
所以不进 §7 那张 FORM_ROWS 清单；它单点的是**「抽屉体只允许有一个滚动容器」**：
头段（标题 / 直接填名字 / 搜索框 / 底栏）也必须是列表的 item ——
原来那版是「头段钉死 + 只让名单滚」，小屏或键盘弹起时名单被压到几乎没有，
而头段自己又滚不动（名单本来是 LazyColumn，套上 verticalScroll 会直接崩）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
# 报告器与注释剥离都**不另立一套**（注释剥离是个状态机，为了 `"image/*"` 这种字符串写的，抄一份必踩坑）
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
COLOR = AND / "ui/theme/Color.kt"
THEME = AND / "ui/theme/Theme.kt"
SCREEN = AND / "ui/dispatcher/AccountManageScreen.kt"
VM = AND / "ui/dispatcher/AccountManageViewModel.kt"
#: 名册卡的两个共用零件（2026-10-05 名册卡返工）：账户卡的电话行搬到了这里，
#: 所以"长按复制手机号"这条判据必须**同时**接受"本页自己写"和"共用件里有"两种落点。
ROSTER = AND / "ui/common/RosterCard.kt"
#: 第二个搬进抽屉的页面（2026-09-22）：运费模板的「新建」。
FREIGHT = AND / "ui/dispatcher/FreightTemplatesScreen.kt"
FREIGHT_VM = AND / "ui/dispatcher/FreightTemplatesViewModel.kt"
#: §8 单点的那个抽屉（2026-10-04 · CHG-0021）：记账页「这一笔记给谁」——
#: 它不是表单（是"挑一条"的抽屉），所以不进 §7 的 FORM_ROWS 清单，单点"只允许一个滚动容器"。
LEDGER = AND / "ui/dispatcher/LedgerCreateScreen.kt"
DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

TOKEN = "SheetSurface"

#: 抽屉的面必须落在这个区间里（**浅灰**：比白低一档，但别深到像贴纸）。
#: `#EDEFF4`（旧的灰蓝）就是**从这里出去的** —— 它 R=237 也在区间内，所以区间不是唯一判据，
#: 真正拦它的是"B ≤ R"那条。区间拦的是另一个方向：有人为了"对比更强"一路刷到 #DDDDDD。
LIGHT_MIN, LIGHT_MAX = 0xE6, 0xF8


def hexes(src: str, name: str) -> list[tuple[int, int, int]]:
    """把一个 token 的所有 `0xFFRRGGBB` 取值解析成 (R,G,B)（解析不出来就给空）。"""
    out: list[tuple[int, int, int]] = []
    for m in re.finditer(rf"\bval {name}\s*=\s*Color\(0xFF([0-9A-Fa-f]{{6}})\)", src):
        v = int(m.group(1), 16)
        out.append(((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF))
    return out


def slice_fun(src: str, header: str) -> str:
    """抠出一个函数的正文（到**同一层**的下一个函数 / 文档注释为止）。

    ⚠️ 不按行号写死：这一页还会被改，写死行号的判据第二次就指到别处去了。
    ⚠️ 也不能"一路切到文件尾"：那样 `save()` 会把后面 `toggleActive()` 的
    `error = …` 一起算进来，于是"保存失败没写页面级 error"这条**自己把自己判红**。
    所以按 header 自己的缩进找下一个同层成员（顶层函数缩进 0、VM 里的方法缩进 4）。
    """
    i = src.find(header)
    if i < 0:
        return ""
    # 缩进取**整行**的行首空白（不是 header 在行内的偏移）：
    # `private fun AccountCard(` 的 header 从 "fun" 开始，按行内偏移算会得到 8，
    # 于是"下一个同层成员"一个都匹配不上、切片一路跑到文件尾 —— 第一版就是这么错的。
    line_start = src.rfind("\n", 0, i) + 1
    indent = len(re.match(r"[ \t]*", src[line_start:]).group(0))
    pat = re.compile(r"\n {" + str(indent) + r"}(?:@Composable|/\*\*|(?:private |internal |suspend )*fun )")
    m = pat.search(src, i + len(header))
    return src[i:m.start()] if m else src[i:]


def call_args(src: str, start: int) -> str:
    """从 [start] 处那个 `名字(` 的左括号起，按**括号配平**取出整段实参。

    ⚠️ 不能写成 `ModalBottomSheet\\s*\\([^)]*containerColor`：`[^)]*` 撞到实参里第一个
    `)`（`rememberModalBottomSheetState(...)` 就有一个）就停了 —— 于是"传在后面的
    containerColor"**静默逃过判据**，而这正是最容易发生的那种写法（参数按习惯往后面加）。
    """
    i = src.find("(", start)
    if i < 0:
        return ""
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                return src[i:j]
    return src[i:]


def sheet_overrides() -> dict[str, int]:
    """**算出来的**：全库哪些 `ModalBottomSheet` 自己传了 `containerColor`（不手写清单）。"""
    out: dict[str, int] = {}
    for p in AND.rglob("*.kt"):
        src = strip_comments(read(p))
        n = sum(1 for m in re.finditer(r"\bModalBottomSheet\s*\(", src)
                if "containerColor" in call_args(src, m.start()))
        if n:
            out[str(p.relative_to(AND)).replace("\\", "/")] = n
    return out


# ── 表单抽屉的清单：**算出来的**（2026-10-03 · CHG-0015）────────────────────
#: 抽屉体里出现这些「表单行」＝ 这一页的表单已经搬进抽屉并换成了白卡形态。
#: ⛔ 别拿 `SoTextField(` 当判据：全库把它同时当**搜索框**用（挑一条的抽屉里到处都是），
#: 那样「表单抽屉」会从 4 个涨到 15 个、把挑一条的抽屉全判红。
FORM_ROWS = ("FormGroup(", "FormInputRow(", "FormPickRow(", "FormSwitchRow(", "FormErrorLine(")
#: 「三件套」里那两条（拉满 + 能滚）。`fillMaxHeight(` 收 `()` 与 `(0.88f)` 两种写法：
#: 用户要的是「拉到最上面」，`.fillMaxHeight(0.9f)` 是**有意**留一截（前面那页的先例）。
TRIO = ("fillMaxHeight(", "verticalScroll(")
#: ⛔ 还没搬三件套的**抽屉**（只能收紧：搬好一个就删一行；每一行都必须仍然成立）。
#: **现在是空的** —— 最后一行（记账页「这一笔记给谁」）已在 2026-10-04（CHG-0021）按 §8
#: 改成「整段一个滚动容器」，欠账清零。表本身留着：下一个"搬进来一半"的抽屉往这里记一行。
#: 为什么要有这张表：`FORM_ROWS` 只认「已经换成白卡表单行」的页，而下面这几个抽屉本身也是
#: 要往里填字的（只是还没按规范重做）—— 不记下来的话，「又一个抽屉没拉满」
#: 永远不会有人喊（它编译得过、真机上也能用，只是半截）。
#:
#: 每一项 = (相对路径, **抽屉体里必须还能找到的一段原文**, 人话说明)。
#: ⚠️ 为什么锚在"一段原文"上（2026-10-03 · CHG-0017 修的一个**空转豁免**）：
#:    判据原来是"这个文件里还有没有没搬三件套的抽屉"。车辆管理页有**两个**抽屉
#:    （编辑表单 + 选车弹层），把表单那个修好之后，"还有没搬三件套的抽屉"**依然成立**
#:    —— 选车弹层是个"挑一条"的抽屉，它永远不需要三件套。于是这条豁免变成空转：
#:    欠账已经还清，判据还在替它喊（反向验证 ㉘ 就是拿这一页做实验时发现的）。
#:    锚在那段原文上之后，抽屉真修好了 → 锚在"缺三件套"的那堆里找不到 → 当场红，
#:    逼人把这一行删掉。
#: ⚠️ 这张表的**源码文本**还被两个脚本读（_check_users_form.py：从表名切到第一个右花括号；
#:    _reverse_verify_users_form.py：往赋值那一行后面插一行做注入）—— 赋值那一行别改写法。
PENDING_FORMS = {
}


def call_end(src: str, start: int) -> int:
    """[start] 处那个 `(` 的配平收尾位置（`call_args` 的位置版）。"""
    i = src.find("(", start)
    if i < 0:
        return -1
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                return j
    return -1


def trailing_body(src: str, start: int) -> str:
    """`ModalBottomSheet(...)` 后面那段 **trailing lambda** 的正文（大括号配平）。

    ⚠️ 不能用 `call_args` 的结果当抽屉体：实参里就有 lambda（`onDismissRequest = { … }`），
    而**内容**在调用之后那个大括号里 —— 只看实参的话，「抽屉里有没有表单行」全看不见。
    """
    e = call_end(src, start)
    if e < 0:
        return ""
    b = src.find("{", e)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return src[b:]


def sheet_bodies() -> list[tuple[str, int, str]]:
    """全库每一个 `ModalBottomSheet` → (相对路径, 行号, 抽屉体)。清单不手写。"""
    out: list[tuple[str, int, str]] = []
    for p in sorted(AND.rglob("*.kt")):
        src = strip_comments(read(p))
        rel = str(p.relative_to(AND)).replace("\\", "/")
        for m in re.finditer(r"\bModalBottomSheet\s*\(", src):
            out.append((rel, src[: m.start()].count("\n") + 1, trailing_body(src, m.start())))
    return out


def main() -> int:
    c = Checker()

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    c.section("0. 反空转（文件搬走/被清空时要先喊，不许安静地全绿）")
    missing = [p.name for p in (COLOR, THEME, SCREEN, VM, DOC) if not p.exists()]
    c.ok("五个文件都在（Color / Theme / AccountManageScreen / AccountManageViewModel / 设计规范）",
         not missing, f"缺：{missing}")
    if missing:
        print("\n❌ 文件都不在，后面的判据没有意义")
        return 1
    color_raw = read(COLOR)
    theme_raw = read(THEME)
    screen = strip_comments(read(SCREEN))
    vm = strip_comments(read(VM))
    theme = strip_comments(theme_raw)
    c.ok("AccountManageScreen.kt 读到了内容（≥ 4000 字符）", len(screen) >= 4000, f"实际 {len(screen)}")
    c.ok("AccountManageViewModel.kt 读到了内容（≥ 3000 字符）", len(vm) >= 3000, f"实际 {len(vm)}")

    # ── 1. 抽屉底色：中性灰（这是"每次都是灰蓝"的唯一开关）────────────────
    c.section("1. 底部抽屉的底色（`SheetSurface` —— 全 App 19 个抽屉一起变）")
    vals = hexes(color_raw, TOKEN)
    c.ok(f"Color.kt 里有 {TOKEN}（且是 0xFFRRGGBB 字面量）", len(vals) == 1, f"解析到 {len(vals)} 个")
    if len(vals) == 1:
        r, g, b = vals[0]
        c.ok(f"{TOKEN} 是中性灰（不许带蓝：现在是 R={r} G={g} B={b}）", b <= r,
             f"B 比 R 高 {b - r} —— 那正是用户说的「灰蓝灰蓝」，M3 的抽屉默认读它")
        c.ok(f"{TOKEN} 不是纯白（抽屉刷成白，里面的白卡就糊了，用户要的「对比」就没了）",
             not (r == g == b == 0xFF), "现在是 #FFFFFF")
        c.ok(f"{TOKEN} 落在浅灰这一档（{LIGHT_MIN:#04x}~{LIGHT_MAX:#04x}）",
             LIGHT_MIN <= r <= LIGHT_MAX and LIGHT_MIN <= g <= LIGHT_MAX and LIGHT_MIN <= b <= LIGHT_MAX,
             f"实际 R={r:#04x}")
    # ⚠️ 别写成"文件里出现这几个词就算数"：第一版就是这么写的，而 `ModalBottomSheet`
    #    在文件第一行的标题里就有一个 → 把"M3 的默认链"整段删掉照样绿（反向验证 ④ 抓出来的）。
    #    要钉的是**那条链本身**（它才是"为什么改这个 token 就等于改 19 个抽屉"的证据）。
    c.ok("Color.kt 里写着它管的是哪件事（M3 那条默认链）—— 下一个人否则不知道能不能改",
         "BottomSheetDefaults" in color_raw and "surfaceContainerLow" in color_raw
         and TOKEN in color_raw,
         "注释里至少要留下 BottomSheetDefaults / surfaceContainerLow 这两个名字")
    c.ok("Theme.kt 亮色方案把 surfaceContainerLow **指向** SheetSurface（不是又抄一遍字面量）",
         re.search(rf"surfaceContainerLow\s*=\s*{TOKEN}\b", theme) is not None,
         "脱钩之后这一个 token 就管不到抽屉了（而且不会有任何报错）")
    dark = theme[theme.find("private val DarkColors"):] if "private val DarkColors" in theme else ""
    c.ok("Theme.kt 暗色方案**没有**跟着换成 SheetSurface（亮暗的分层方向是反的）",
         f"surfaceContainerLow = {TOKEN}" not in dark,
         "暗色下抽屉要的是「比背景亮一档的深灰」，照搬亮色那个值会把暗色的分层弄没")

    # ── 2. 抽屉表单：去线框、改白卡 ───────────────────────────────────────
    c.section("2. 新增/编辑抽屉：不许有线框，分组用白卡")
    n_outlined = len(re.findall(r"\bOutlinedTextField\s*\(", screen))
    c.ok("AccountManageScreen.kt 里一个描边输入框都没有", n_outlined == 0, f"实际 {n_outlined} 处")
    need_rows = ["FormInputRow", "FormPickRow"]
    gone = [k for k in need_rows if not re.search(rf"{k}\(", screen)]
    c.ok("抽屉用的是共用表单行（FormInputRow / FormPickRow 都在），没自己写一套",
         not gone, f"不见了：{gone}")
    # ⚠️ 只数整个文件里的 SectionCard 是不够的：**列表卡**自己也是一张 SectionCard，
    #    于是"抽屉里少一张白卡"照样能凑够数（反向验证 ⑯ 抓出来的）。
    #    所以数的是**抽屉那一段**里的白卡。
    # ⚠️ 2026-10-09 复核：抽屉里的白卡实测已从 2 张涨到 **3** 张（后来又加了一组）。
    #    下限停在 2 的话，反验第 ⑯ 条注入只把 3 减到 2、仍在阈值之上 ⇒ 判据不红、
    #    那条反验恒 MISS（实测踩到）。这里按实测把下限提到 3，让注入重新咬得住；
    #    意图一个字没变（抽屉里的分组必须是白卡，不许退回裸 Column）。
    sheet = slice_fun(screen, "fun AccountFormSheet(")
    n_cards = len(re.findall(r"\bSectionCard\s*[({]", sheet))
    c.ok("抽屉的分组是白卡（抽屉里 SectionCard ≥ 3：账号、角色、分类各一张）", n_cards >= 3,
         f"抽屉里实际 {n_cards} 处")
    c.ok("没有 FilterChip（未选中带描边＝线框；角色改成下拉点选）",
         "FilterChip" not in screen,
         "chips 会把「标签在左、值在右」的节奏打断，未选中时它自己也是描边的")
    c.ok("ModalBottomSheet 没有自己传 containerColor（19 个抽屉只许有一处说了算）",
         not re.search(r"\bModalBottomSheet\s*\(", screen)
         or "containerColor" not in call_args(screen, screen.find("ModalBottomSheet(")),
         "在这一页传一个自己的颜色，就成了「每个抽屉各说各的」的起点")
    over = sheet_overrides()
    c.ok("全库没有任何一个 ModalBottomSheet 自己传 containerColor（清单是算出来的，不手写）",
         not over,
         f"自己传了底色的抽屉：{over} —— 真有需要就在这里写一条理由，"
         f"别让 19 个抽屉各说各的")

    # ── 3. 列表卡：动作的左/右位置 ───────────────────────────────────────
    c.section("3. 列表卡：动作的左右分区（编辑在右、相反操作在左）")
    card = slice_fun(screen, "fun AccountCard(")
    c.ok("AccountCard 还在（列表卡没被拆掉）", bool(card), "找不到 fun AccountCard(")
    if card:
        acts = [m.start() for m in re.finditer(r"AccountAction\(", card)]
        del_i = card.find('AccountAction("删除"')
        edit_i = card.find('AccountAction("编辑"')
        # ⚠️ 判据是「**第一个**动作是删除、**最后一个**动作是编辑」，不是"删除的下标小于编辑"：
        #    后者只要左栏还留着一个删除就永远成立（把编辑再复制一份到左栏都拦不住），
        #    等于把这条规则写成了一句没有信息量的话。
        c.ok("动作行里第一个动作是「删除」（相反/警示在最左）",
             bool(acts) and del_i == acts[0], f"第一个动作在 {acts[0] if acts else -1}，删除在 {del_i}")
        c.ok("「编辑」是动作行里最后一个动作（右＝惯用手那一侧）",
             bool(acts) and edit_i == acts[-1], f"最后一个动作在 {acts[-1] if acts else -1}，编辑在 {edit_i}")
        mid = card[del_i:edit_i] if (del_i >= 0 and edit_i > del_i) else ""
        c.ok("左右两栏之间有 Spacer(weight 1f)（是两栏，不是一排）",
             re.search(r"Spacer\(Modifier\.weight\(1f\)\)", mid) is not None)
        # ⚠️ 钉的是**意图**（"圈底图标 **+ 文字**"），不是某个实现名：
        #    2026-09-22 另一个会话把这一页的 `AccountAction` 与订单卡的 `CardActionIcon`
        #    **收成了一个共用控件**（圆底照旧走 `TintedIcon`），本判据第一版钉的是
        #    `TintedIcon(` 这个名字 —— 那次合并让它当场假红。两种写法都接受，但**文字不许丢**：
        #    这一页的用户是派单员，只留一个图标就是逼人靠猜（这正是当初加文字的理由）。
        act = slice_fun(screen, "fun AccountAction(")
        # ⚠️ "文字没丢"必须判**有没有把它传下去**（`label = …`），不能只判 `"label" in body`：
        #    函数签名里本来就有个 `label: String,` —— 那样写的话，把 `label = label,` 整行删掉
        #    （图标型动作，文字真没了）判据照样绿（反向验证 ㉔ 抓出来的）。
        c.ok("卡片上的动作是「圈底图标 + 文字」（用户：「他要一个图标，稍微圈一下」）",
             ("CardActionIcon(" in act or "TintedIcon(" in act)
             and re.search(r"\blabel\s*=", act) is not None,
             f"共用控件里没有圈底图标，或文字没传下去：{act[:80]!r}")
    # ⚠️ 2026-10-05（名册卡返工）：这一条**锚点搬家**了，不是放宽 —— 账户卡的电话行搬进了
    #    共用件 `ui/common/RosterCard.kt::RosterPhoneRow`（四张名册卡原来只有账户卡能长按复制，
    #    用户这一轮要求电话行统一：青绿 Phone 图标 + 前景色号码）。
    #    判据仍要求那三样**在同一处**出现（不是"全库某处有就行"）：本页自己写，或共用件里有，
    #    二选一 —— 两处都有就是又长出一份会长歪的实现。
    roster = read(ROSTER) if ROSTER.exists() else ""
    where = screen if "combinedClickable(" in screen else roster
    c.ok("手机号长按可复制（combinedClickable + onLongClickLabel）",
         all(t in where for t in ("combinedClickable(", "onLongClickLabel", "copyTextToClipboard(")),
         f"本页与共用件 {ROSTER.name} 里都没凑齐长按复制那三样")

    # ── 4. 错误落在抽屉里 ────────────────────────────────────────────────
    c.section("4. 错误与表单同生共死（不许顶掉整页列表）")
    c.ok("抽屉里画了 FormErrorLine(vm.formError)",
         "FormErrorLine(vm.formError)" in screen)
    c.ok("VM 的 formError 是四段合成，顺序 = 用户从上往下填的顺序",
         re.search(r"val formError: String\? get\(\) =\s*nameError \?: phoneError \?: passwordError \?: saveError",
                   vm) is not None)
    save = slice_fun(vm, "fun save(")
    c.ok("保存失败写的是 saveError（**不是**页面级 error：那会把整页账号顶成错误页）",
         "saveError = toApiException(e).message" in save and "error = toApiException(e).message" not in save,
         "这一条就是 2026-09-21「新增地点」那个坑的同一个形状")
    c.ok("校验文案能独立读懂（抽屉里只有一行红字，不再写「必填信息」）",
         "必填信息" not in vm and "请填写姓名" in vm and "请设置密码" in vm)

    # ── 5. 规范文档 ──────────────────────────────────────────────────────
    c.section("5. 规范文档同步")
    doc = read(DOC)
    c.ok("设计规范里写着「抽屉底色」这条（否则下一个人还会以为是某一页写错了颜色）",
         TOKEN in doc and "抽屉" in doc)

    # ── 6. 运费模板：新建从弹窗改成抽屉（2026-09-22）──────────────────────
    c.section("6. 运费模板的「新建」＝抽屉（不是弹窗）＋ 拉满到最上面 ＋ 白卡表单")
    missing2 = [p.name for p in (FREIGHT, FREIGHT_VM) if not p.exists()]
    c.ok("两个文件都在（FreightTemplatesScreen / FreightTemplatesViewModel）", not missing2,
         f"缺：{missing2}")
    if not missing2:
        fr = strip_comments(read(FREIGHT))
        fvm = strip_comments(read(FREIGHT_VM))
        c.ok("FreightTemplatesScreen.kt 读到了内容（≥ 6000 字符）", len(fr) >= 6000, f"实际 {len(fr)}")
        c.ok("FreightTemplatesViewModel.kt 读到了内容（≥ 3000 字符）", len(fvm) >= 3000, f"实际 {len(fvm)}")

        # 形态：抽屉、不是弹窗
        c.ok("新建/编辑走的是 ModalBottomSheet（不是 AlertDialog —— 用户：「不要使用弹窗啊」）",
             "ModalBottomSheet(" in fr and "AlertDialog(" not in fr,
             "这一页又出现 AlertDialog 了？表单要留在抽屉里")
        c.ok("抽屉一打开就展开到底（skipPartiallyExpanded = true）",
             "rememberModalBottomSheetState(skipPartiallyExpanded = true)" in fr)
        # 「拉到最上面」＝ 抽屉内容占满可用高度（只有一行修饰符，删掉不报错、却退回半截）
        sheet = slice_fun(fr, "fun FreightTemplateSheet(")
        c.ok("抽屉内容是 fillMaxHeight()（用户：「底部抽屉是**拉到最上面**」）",
             "fillMaxHeight()" in sheet, "少了这一行，抽屉就退回「半截」，字段多的时候要滚着填")
        c.ok("抽屉能滚（字段比屏幕高时够得着保存）",
             "verticalScroll(" in sheet)

        # 表单形态：无边框 + 白卡
        n_out2 = len(re.findall(r"\bOutlinedTextField\s*\(", fr))
        c.ok("FreightTemplatesScreen.kt 里一个描边输入框都没有", n_out2 == 0, f"实际 {n_out2} 处")
        c.ok("也没有退回 SoTextField（这一页原来就是 4 个它堆出来的）",
             "SoTextField(" not in fr)
        gone2 = [k for k in ("FormInputRow", "FormPickRow") if not re.search(rf"{k}\(", fr)]
        c.ok("用的是一套共用表单行（FormInputRow / FormPickRow 都在）", not gone2, f"不见了：{gone2}")
        n_groups = len(re.findall(r"\bFormGroup\s*\(", sheet))
        c.ok("分组是白卡（抽屉里 FormGroup ≥ 3：线路与价格 / 算哪几类货 / 备注）",
             n_groups >= 3, f"抽屉里实际 {n_groups} 处")
        c.ok("金额框走 InputRules（「一车价格」是钱）", "InputRules.moneyInput(" in fr)
        c.ok("没有 FilterChip（未选中带描边＝线框；分类用的是无边框色块）",
             "FilterChip" not in fr)

        # 错误落在抽屉里
        c.ok("运费模板抽屉里画了 FormErrorLine(vm.formError)", "FormErrorLine(vm.formError)" in fr)
        c.ok("VM 的校验/保存失败写的是 formError（不是页面级 error：那是抽屉背后的 snackbar）",
             "formError = " in fvm and 'formError = "请填写价目名称' in fvm
             and "formError = toApiException(e).message" in fvm)
        c.ok("抽屉的状态叫 showSheet（改回 showDialog 就说明又变回弹窗了）",
             "showSheet" in fvm and "showDialog" not in fvm and "showSheet" in fr)

        # 三个动作在**底栏三格**里（2026-09-22 第二轮：用户圈着右上角那三个说「你这个没改啊」，
        # 拍板「挪到底部做成三格，照抄商品管理」）
        scr = slice_fun(fr, "fun FreightTemplatesScreen(")
        c.ok("三个动作在底栏三格里（Screen 里调用了 FreightBottomBar）",
             "FreightBottomBar(" in scr, "三个动作又回到右上角了？")
        c.ok("顶栏不再挂那三个动作（AppTopBar 没有 actions）", "actions = {" not in fr,
             "顶栏又有动作了 —— 待定价 / 分类管理 / 新建 都该在底栏")
        bbar = slice_fun(fr, "fun FreightBottomBar(")
        c.ok("中间是**语义色圆钮**（FilledIconButton + 运费模板的深靛 0xFF0030BB）",
             "FilledIconButton(" in bbar and "0xFF0030BB" in bbar,
             "主操作要居中、且用这一块的语义色（一色一功能）")
        c.ok("左右两格是「图标 + 文字」的无边框格（不是描边按钮）",
             "FreightBottomCell(" in bbar and "OutlinedButton" not in bbar)

    # ── 7. 表单抽屉的「三件套」：清单自己算（2026-10-03 · CHG-0015）──────
    # ⚠️ 为什么要有这一节：上面 §6 是**手写**的两页（账户管理、运费模板）。下一个把表单
    #    搬进抽屉的人**不知道该往哪儿加判据** —— 于是"又一页半截抽屉"没有任何人喊。
    #    这一节把清单改成**算出来的**：多一个表单抽屉，它自动进清单。
    c.section("7. 表单抽屉的形态三件套（拉满 + 能滚）—— 清单是**算出来的**")
    sheets = sheet_bodies()
    c.ok("全库扫到了抽屉（ModalBottomSheet ≥ 15）", len(sheets) >= 15,
         f"实际扫到 {len(sheets)} 个 —— 扫描本身被改坏了？（那样下面全是空转）")
    forms = [(rel, ln, b) for rel, ln, b in sheets if any(k in b for k in FORM_ROWS)]
    c.ok("认得出「表单抽屉」（体内有共用表单行；今天 6 个：地址与联系人那三个 + 车辆编辑 + 账号编辑 + 挂账单位）",
         len(forms) >= 2,
         f"实际 {len(forms)} 个 —— 表单行改名 / 被换掉的话，这一节会**安静地**缩成 0")
    n_addr = sum(1 for rel, _, _ in forms if rel.endswith("shipper/AddressScreen.kt"))
    c.ok("本批这一页三个抽屉都在清单里（AddressScreen × 3）", n_addr == 3,
         f"只认出 {n_addr} 个 —— 这一页从清单里掉出去了")
    for rel, ln, b in forms:
        c.ok(f"{rel}:{ln} 抽屉内容 fillMaxHeight(（用户：「底部抽屉是**拉到最上面**」）",
             "fillMaxHeight(" in b,
             "少了这一行抽屉就退回「半截」，而表单页字段多，等于要滚着填")
        c.ok(f"{rel}:{ln} 抽屉能滚（verticalScroll：字段比一屏高时够得着保存）",
             "verticalScroll(" in b)
    for rel, (anchor, why) in PENDING_FORMS.items():
        still = [b for r2, _, b in sheets
                 if r2 == rel and anchor in b and not all(k in b for k in TRIO)]
        c.ok(f"「还没搬三件套」这条仍然成立：{rel} —— {why}",
             (AND / rel).exists() and bool(still),
             "这一个抽屉已经搬好了（或文件/锚点没了）—— 把 PENDING_FORMS 里这一行删掉，"
             "别让它变成空转的豁免")
    c.ok("「还没搬三件套」的欠账表是空的（最后一条＝记账页，2026-10-04 · CHG-0021 已还清）",
         not PENDING_FORMS,
         "又往这张表里记了一行？那说明有一页抽屉只搬了一半 —— 记下来是对的，"
         "但它是一笔**欠账**，搬完就要删掉")
    # 表空着的时候上面那个循环一条都不会报 —— 所以空本身也要有判据兜着（"零条检查"最会骗人）。

    # ── 8. 记账抽屉（「这一笔记给谁」）：整段一个滚动容器（2026-10-04 · CHG-0021）──
    # ⚠️ 这一节的前身是上面那张欠账表里最后一行，原来的记法是「有 fillMaxHeight(0.88f)，
    #    缺 verticalScroll」—— 那个归因**是错的**：那页没有 verticalScroll，是因为它的名单
    #    本来就是 LazyColumn，而 LazyColumn 套在 verticalScroll 里会**直接崩**。
    #    真正该钉的是**形态**：头段钉在上面、只让名单滚 → 小屏 / 键盘弹起时名单被压到几乎
    #    没有，而头段自己又滚不动。改成"头段也是 item"之后，判据钉死两件事：
    #    抽屉体的**第一句就是 LazyColumn**（不再是那个钉死的 Column），以及头段那几样
    #    都落在滚动区**里面**（位置断言：都出现在 LazyColumn( 之后）。
    c.section("8. 记账抽屉（「这一笔记给谁」）：头段也是列表的 item，整段一起滚")
    heads = [b for rel, _, b in sheets
             if rel.endswith("dispatcher/LedgerCreateScreen.kt") and "这一笔记给谁" in b]
    c.ok("认出了「这一笔记给谁」抽屉（扫描被改坏的话下面全是空转）", len(heads) == 1,
         f"实际认出 {len(heads)} 个 —— 这一页的抽屉改叫别的了？")
    if heads:
        body = heads[0]
        n_lz = body.count("LazyColumn(")
        c.ok("抽屉体的第一句就是 LazyColumn（不是钉在上面的 Column 头段）",
             re.search(r"\{\s*LazyColumn\(", body) is not None,
             "又变回「头段钉死、只让名单滚」了？那一坨在小屏 / 键盘弹起时会把名单压没")
        c.ok("抽屉体里只有一个滚动容器（LazyColumn 恰好一处）", n_lz == 1,
             f"实际 {n_lz} 处 —— 多一个就是两个容器抢高度")
        c.ok("抽屉体里没有 verticalScroll（LazyColumn 外面再套一层会直接崩）",
             "verticalScroll(" not in body)
        i = body.find("LazyColumn(")
        pins = {
            "标题「这一笔记给谁」": "这一笔记给谁",
            "直接填名字的框": "未注册的客户：直接填名字",
            "搜索框": "SearchField(",
            "底栏（清空 / 完成）": "vm.clearShipper()",
        }
        out_of_scroll = [k for k, s in pins.items() if not (0 <= i < body.find(s))]
        c.ok("标题 / 直接填名字 / 搜索框 / 底栏都在抽屉的滚动区里（不是钉在上面的头段）",
             not out_of_scroll,
             "这几样又跑到列表外面去了：" + "、".join(out_of_scroll))
    # 信息行（不是判据）：体内有输入框、但还没换成白卡表单行的抽屉。它们多半是**挑一条**的
    # 抽屉（框是搜索框），列出来只为下一个人判断"这一页算不算表单"。
    maybe = sorted({rel for rel, _, b in sheets
                    if not any(k in b for k in FORM_ROWS)
                    and ("SoTextField(" in b or "OutlinedTextField(" in b)})
    print(f"  [信息] 体内有输入框但还没换成表单行的抽屉（{len(maybe)} 个文件）：{maybe}")
    # ── 汇总 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：抽屉底色是全 App 一处说了算的中性灰、"
          f"两页表单都是抽屉里拉满的白卡无边框行、错误与表单同生共死、"
          f"记账抽屉整段只有一个滚动容器。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
