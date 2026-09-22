"""红线：「我的」页（三端共用）不许退回改版前的样子（2026-09-21）。

## 这一页为什么值得一条红线
1. **它是三端共用的唯一一页**（货主/派单员/司机都从底部 Tab 进）——改坏一次，三个角色一起坏。
2. 它这一轮**整体重写了布局**（用户给的参考图：深墨蓝头部 + 大圆角卡片列表 + 「基础设置」子页），
   而旧结构里有几处是**用真机事故换来的**：
   - 列表**必须能滚**：2026-09-21 真机抓到不可滚的 `Column` 把「退出登录」顶出屏幕且够不着
     （表现是"退不了登录、也没法检查更新"，还不是崩溃）；
   - 深色头部铺到状态栏下面 → **必须**同步把状态栏图标改成浅色，否则浅色模式下
     时间/电量/信号压在深墨蓝上**一个都看不见**（不报错，只有截图缩小看才发现）。
3. 有几条是**用户明确拍板的取舍**，最容易被后来的会话"顺手改回去"：
   - 「消息中心」那一行**删掉**（用户原话：「已经在导航栏里有一个消息中心了，这属于重复设计」）；
   - 「语言设置 / 账号信息 / 结算账户」**不做**（参考图里有，我们没有对应业务）；
   - 不重要的设置搬进**「基础设置」**第二层（「我们按钮太多了」）——但**「提示」当天又被要求搬回第一层**
     （用户：「基础设置有个要移出来，叫做提示提醒，那个不能放在里面」）；
   - 「退出登录」要与其它行**同形**（图标+文字，不居中），点一下**先弹确认框**（防误碰）。

## 判据怎么来的（行数自己算，锚点各写各的理由）
第一层的**行数**是从源码数出来的（`ProfileRow(` 的出现次数），**恰好等于 6**：
我的账本〔仅司机·条件显示〕/ 消息提醒 / 提示 / 基础设置 / 关于与更新 / 退出登录。
少一行是丢了功能，多一行就是"按钮又多起来了"（正是这一轮要解决的问题），两种都该红。
⛔ 不按标题字面量对齐成一个集合：其中「关于与更新」的标题是个 `when` 表达式
（下载中/安装中要换文案），按标题解析会把 `"checking"` 这类内部键也当成一行。
所以每行各给一个**锚点字符串**，并说明它为什么长这样。

用法：python _tools/qa/_check_profile_page.py
配套：python _tools/qa/_reverse_verify_profile_page.py（12 种破坏方式全被抓）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
# 剥注释的规则**只有一份**（在 `_check_hints.py` 里）：这里不另写一个近似版，
# 否则两处会慢慢长歪（比如一个认字符串字面量、一个不认），红线的结论就不可信了。
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
PROFILE = ANDROID / "ui" / "profile" / "ProfileScreen.kt"
ROW = ANDROID / "ui" / "profile" / "ProfileRow.kt"
HEADER = ANDROID / "ui" / "profile" / "ProfileHeader.kt"
MOTION = ANDROID / "ui" / "profile" / "RowMotion.kt"
BASIC = ANDROID / "ui" / "profile" / "BasicSettingsScreen.kt"
STATUS = ANDROID / "ui" / "common" / "StatusBarIcons.kt"
HOME = ANDROID / "ui" / "home" / "RoleHomeScreen.kt"
MODULES = ANDROID / "ui" / "nav" / "Modules.kt"
ROUTES = ANDROID / "ui" / "nav" / "Routes.kt"
NAV = ANDROID / "ui" / "nav" / "NavGraph.kt"

# 第一层就是这六行（用户 2026-09-21 逐条过过）。`我的账本` 只对"有按单的钱要对"的司机显示，
# 但它的字面量一直在源码里；显示条件另有判据（`_check_driver_money.py`）。
N_ROWS = 6
WANT_ROW_ANCHORS: list[tuple[str, str, str]] = [
    ("我的账本", 'title = "我的账本"', "司机那一行（条件显示）"),
    ("消息提醒", 'title = "消息提醒"', "来单会不会响"),
    ("提示", 'title = "提示"', "总开关；用户当天要求从「基础设置」**搬回第一层**"),
    ("基础设置", 'title = "基础设置"', "第二层的入口"),
    ("关于与更新", "关于与更新", "标题是 `when`（下载中/安装中要换文案），所以锚它休息态那支"),
    ("退出登录", 'title = "退出登录"', "与其它行同形；点一下只弹确认框"),
]

# 参考图里有、**用户明确说不要**的三项（⛔ 别照抄进来）
FORBIDDEN_ITEMS = ["语言设置", "账号信息", "结算账户"]


def main() -> int:
    c = Checker()

    # ── 0. 反空转：文件都在、而且真的读到了内容 ──────────────────────────
    c.section("0. 反空转（文件搬走/被清空时要先喊，不许安静地全绿）")
    missing = [p.name for p in (PROFILE, ROW, HEADER, MOTION, BASIC, STATUS) if not p.exists()]
    c.ok("六个文件都在（ProfileScreen / ProfileRow / ProfileHeader / RowMotion / "
         "BasicSettingsScreen / StatusBarIcons）", not missing, f"缺：{missing}")
    if missing:
        print("\n❌ 文件都不在，后面的判据没有意义")
        return 1
    profile = strip_comments(read(PROFILE))
    row = strip_comments(read(ROW))
    header = strip_comments(read(HEADER))
    motion = strip_comments(read(MOTION))
    basic = strip_comments(read(BASIC))
    status = strip_comments(read(STATUS))
    home = strip_comments(read(HOME))
    modules = read(MODULES)
    routes = strip_comments(read(ROUTES))
    nav = strip_comments(read(NAV))
    c.ok("ProfileScreen.kt 读到了内容（≥ 3000 字符）", len(profile) >= 3000, f"实际 {len(profile)}")

    # ── 1. 三端共用同一页 + 第一层的行（行数自己算）───────────────────────
    c.section("1. 三端共用同一页 + 第一层有哪几行（行数从源码算）")
    # ⚠️ 要排掉**定义**那一处（`fun ProfileScreen(` 本身也含 `ProfileScreen(`）——
    #    第一版没排，于是"调用点"里混进了 ProfileScreen.kt 自己，这条判据当场假红。
    callers = []
    for p in ANDROID.rglob("*.kt"):
        src = strip_comments(read(p))
        if "ProfileScreen(" in src and "fun ProfileScreen(" not in src:
            callers.append(p)
    c.ok("ProfileScreen( 的调用点只有 1 处（三端共用同一页；多一处就有两套「我的」）",
         len(callers) == 1, "调用点：" + "、".join(p.name for p in callers))
    c.ok("那个调用点传 embedded = true（底部 Tab 内嵌，不再有独立路由）",
         "embedded = true" in home and "ProfileScreen(" in home)

    n_rows = profile.count("ProfileRow(")
    n_motion = profile.count("RowMotion(")
    c.ok(f"第一层恰好 {N_ROWS} 行（实际 {n_rows}）—— 少一行是丢功能，多一行就是"
         f"「按钮又太多了」（这一轮要解决的问题）", n_rows == N_ROWS,
         "要加/减行：先改这份红线并写清为什么（用户 2026-09-21 拍板的清单）")
    for name, anchor, why in WANT_ROW_ANCHORS:
        c.ok(f"第一层有「{name}」（{why}）", anchor in profile)
    c.ok("每一行都套了行动效（RowMotion 数 == 行数）", n_motion == n_rows,
         f"行 {n_rows} / 动效 {n_motion} —— 少套一行它就会「啪」地出现，与旁边的行不一致")
    # ⚠️ 锚点认两种写法：2026-09-22 起那一行改成 `indication = null` 的 clickable
    #    （用户：「点击圈那个…有一种刷新的感觉，那个不要有」），**本意没变**：
    #    行组件自己装 clickable、`onClick = null` 就不装（整行点不动这件事靠它）。
    c.ok("行组件自己装 clickable（`onClick = null` 就不装：整行点不动这件事靠它）",
         ("clickable(onClick = onClick)" in row) or ("indication = null" in row and "onClick = onClick" in row))

    # ── 2. 用户拍板的两条：不重复、不照抄 ────────────────────────────────
    c.section("2. 用户拍板：删掉重复入口、不照抄那三项")
    c.ok("「我的」里没有「消息中心」这一行（用户：与底部导航重复，属重复设计）",
         "消息中心" not in profile,
         "用户 2026-09-21 原话：「已经在导航栏里有一个消息中心了，这属于重复设计」")
    c.ok("底部导航**仍然**有消息 Tab（删掉那一行不丢入口）",
         '"messages"' in modules, "去 Modules.kt 的 bottomTabs 里找")
    c.ok("消息 Tab 上仍然挂着未读角标（删掉那一行不丢信息）",
         "BadgedBox" in home, 'RoleHomeScreen 里按 tab.content == "messages" + unread > 0 画的')
    hit = [w for w in FORBIDDEN_ITEMS if w in profile or w in basic]
    c.ok(f"没有照抄参考图的 {FORBIDDEN_ITEMS}（用户明确说不要）", not hit, f"混进来了：{hit}")

    # ── 3. 深色头部 + 状态栏（本轮最容易翻车的地方）──────────────────────
    c.section("3. 深色头部铺到状态栏下面 —— 图标颜色必须跟着改")
    c.ok("ProfileScreen.kt 里画了头部（ProfileHeader）", "ProfileHeader(" in profile)
    c.ok("ProfileScreen.kt 里调了 LightStatusBarIcons()（少了它：浅色模式下状态栏图标在深墨蓝上全看不见）",
         "LightStatusBarIcons()" in profile)
    c.ok("StatusBarIcons.kt 离开这一页时**还原成主题该有的值**（没有它，子页会一直是白图标）",
         "onDispose" in status
         and "controller?.isAppearanceLightStatusBars = !ThemeMode.isDark" in status,
         "还原那一行必须与 SOrdersTheme 同一口径（`!ThemeMode.isDark`），不许写成固定的 false")
    c.ok("ProfileHeader.kt 用 WindowInsets.statusBars 让背景铺到状态栏下面（只让内容让开）",
         "windowInsetsPadding(WindowInsets.statusBars)" in header)
    c.ok("RoleHomeScreen.kt：profile 这一 Tab 不吃 Scaffold 的**顶部** inset（否则头部上面留一条浅灰带）",
         'if (tabs[tabIdx].content == "profile")' in home and "top = 0.dp" in home,
         "判据锚在那一行判断上（不是只找 contentPad 这个名字）")
    i_head, i_scroll = profile.find("ProfileHeader("), profile.find(".verticalScroll(")
    # 代理判据（老实说）：头部在源码里必须排在滚动容器**之前**。
    # 真出问题时的表现是"头部跟着一起滚走"→ 状态栏又变浅、白图标看不见。
    c.ok("头部排在滚动容器之前（头部固定、只有列表滚）", 0 <= i_head < i_scroll,
         f"ProfileHeader 位置 {i_head} / verticalScroll 位置 {i_scroll}")
    c.ok("列表那一片吃剩余高度（weight(1f)）", ".weight(1f)" in profile)
    c.ok("列表能滚（2026-09-21 真机：不可滚时「退出登录」被顶出屏幕且够不着）",
         ".verticalScroll(" in profile)

    # ── 4. 行动效（用户要"跟着手指走、松手弹回"，像果冻）──────────────────
    c.section("4. 行动效：落位 + 果冻（跟着手指、松手弹回）")
    # ⚠️ 2026-09-22 用户把"落位（进页面每行依次滑上来）"整段砍掉了，原话：
    #    「…**也不是说点进去一开始**，我要触发那个动效…**点进去就是那样子**，
    #      只是我们在**往下滑**的时候会有那个动效的触发。**如果他不是触发动效的话，那就是 bug**」。
    #    所以这条判据**反过来钉**：果冻在、**入场动画不许回来**
    #    （入场那段要靠 `LaunchedEffect` + 按序号依次 `delay` 才播得出来，两个都不许有）。
    # ⚠️ 本条的**反向验证暂时欠着**：`RowMotion.kt` 此刻正被另一个会话改（改的就是这件事），
    #    往别人正在写的文件里注入会让"按字节还原"可能失败（harness 会拒绝还原，把人家的文件留在注入态）。
    #    等那个文件安静下来再补一条注入。
    c.ok("RowMotion.kt 只跟滚动走（果冻在；进页面不播入场动画）",
         "jelly.value" in motion and "LaunchedEffect" not in motion and "delay(" not in motion)
    # ⚠️ 这条是**用真机反馈换来的**：第一版把"跟随"挂在滚动位置（`scroll.value`）上，
    #    于是列表装得下、滚不动的机器上**一点反应都没有**（用户：「我刚滑了一下没有反应」）。
    c.ok("果冻挂在**手势**上（NestedScrollConnection / onPostScroll），不是挂在滚动位置上",
         "NestedScrollConnection" in motion and "onPostScroll" in motion
         and "scroll.value" not in motion and "ScrollState" not in motion,
         "⛔ 挂回滚动位置 = 列表滚不动时完全没反应（第一版就是这么错的）")
    c.ok("只旁观、不消费位移（返回 Offset.Zero，否则等于把列表的滚动抢掉）",
         "return Offset.Zero" in motion)
    c.ok("松手会弹回原位（onPostFling 里 animateTo(0f) + 回弹弹簧）",
         "onPostFling" in motion and "animateTo(0f" in motion and "dampingRatio" in motion)
    c.ok("果冻有上限（「有反应」和「飞出去」的分界）", "coerceIn(-maxPx, maxPx)" in motion)
    c.ok("越往下的行偏移越大（用户原话：「越往下面偏移量越大」）",
         "JELLY_BASE + index * JELLY_STEP" in motion)
    c.ok("状态读在**绘制阶段**（`jelly.value` 只在 graphicsLayer 里读，不触发布局/重组）",
         "graphicsLayer {" in motion and "jelly.value" in motion)
    c.ok("不用 `Modifier.offset`（那会带着命中区一起动、点击区域与眼睛对不上）",
         "Modifier.offset" not in motion and ".offset(" not in motion)
    # ⚠️ 这一条是 2026-09-21 真机量像素才发现的：Modifier 链里靠前的在**外层**，
    #    连接必须挂在滚动节点的**外面**才收得到事件。写成 `.verticalScroll(..).nestedScroll(..)`
    #    时挨着拖 1000px、每一行都还在原位（实测：位移全是 +0）。
    i_ns = profile.find(".nestedScroll(jelly.connection)")
    i_vs = profile.find(".verticalScroll(listScroll)")
    c.ok("嵌套滚动写在**滚动容器外面**（Modifier 链：`nestedScroll` 必须在 `verticalScroll` 之前）",
         0 <= i_ns < i_vs,
         "⛔ 顺序反了＝连接挂在滚动节点的**子级**上、一个事件都收不到"
         "（实测：按住拖 1000px，整列纹丝不动）")

    # ── 5. 「基础设置」子页 与 搬回第一层的「提示」───────────────────────
    c.section("5. 「基础设置」子页 + 「提示」搬回第一层（用户当天的第二个要求）")
    for t in ("随日落自动切换", "夜间模式"):
        c.ok(f"基础设置里有「{t}」", t in basic)
    c.ok("基础设置里只有这两个开关（Switch( == 2）", basic.count("Switch(") == 2,
         f"实际 {basic.count('Switch(')} 个")
    c.ok("「提示」**不在**基础设置里（用户：「那个不能放在里面」）",
         'title = "提示"' not in basic)
    c.ok("「提示」那一格仍走**唯一写入口** setByUser(",
         "container.hintPrefs.setByUser(" in profile,
         "⛔ 直接写 HintPrefs 的字段＝第二份写入路径（见 docs/HINT_STYLE.md §5）")
    # ── 5b. 文字摆哪儿（用户 2026-09-21 第二次反馈定的一条规则）────────────
    # **短状态靠右、和标题同一行；只有详细说明才另起一行。**
    # 每行切块的方式：按 `ProfileRow(` 切，一块恰好就是一行（行与行之间不会串）。
    chunks = profile.split("ProfileRow(")[1:]

    def row_chunk(title: str) -> str:
        for ch in chunks:
            if f'title = "{title}"' in ch:
                return ch
        return ""

    hint_row = row_chunk("提示")
    basic_row = row_chunk("基础设置")
    alert_row = row_chunk("消息提醒")
    c.ok("「提示」的状态文字在**右边同一行**（不再另起一行）",
         bool(hint_row) and "subtitle" not in hint_row and "显示所有说明" in hint_row,
         "用户：「那个不显示说明能不能放在提示的后面，就不要做两排」")
    c.ok("「基础设置」的说明也在**右边同一行**（跟版本号一样）",
         bool(basic_row) and "subtitle" not in basic_row and "外观 · 夜间模式" in basic_row,
         "用户：「基础设置那个说明也改成放右边，就跟那个版本号一样」")
    c.ok("**详细说明**仍然另起一行（消息提醒那句 Hint 还在 subtitle 里）",
         "subtitle" in alert_row and "Hint(" in alert_row,
         "用户：「如果是详细说明的话，则就出现在下面」—— 这条是双向的，别为了统一把长句也搬到右边")
    c.ok("路由三处齐全：Routes 声明 + NavGraph 注册 + 「我的」有入口",
         "BASIC_SETTINGS" in routes and "Routes.BASIC_SETTINGS" in nav
         and "onOpenBasicSettings" in profile and "Routes.BASIC_SETTINGS" in home,
         "缺一处就是「点了没反应」或「找不到这一页」")

    # ── 6. 关于与更新 / 退出登录（防误碰）────────────────────────────────
    c.section("6. 「关于」＝版本更新；退出登录要确认（防误碰）")
    c.ok("「关于与更新」那一行点一下就是检查更新（两行合一的那个决定）",
         "关于与更新" in profile and "vm.checkUpdate()" in profile)
    c.ok("右侧显示当前版本（用户想知道自己装的是哪一版）", "vm.currentVersion" in profile)
    c.ok("「退出登录」用 error 色（红）",
         re.search(r'title = "退出登录",[\s\S]{0,300}?titleColor = MaterialTheme\.colorScheme\.error',
                   profile) is not None)
    logout_row = re.search(r'title = "退出登录",[\s\S]{0,400}?\n\s*\)\n', profile)
    c.ok("那一行**只弹确认框**、不直接退（用户：「不是点一下就直接退出，为了防止误碰」）",
         logout_row is not None and "vm.logout" not in logout_row.group(0),
         "行自己的 onClick 里出现 vm.logout ＝ 误碰一下就退出去了")
    c.ok("确认框复用全 App 那一个危险操作弹层（不自己拼 AlertDialog）",
         "DangerConfirmDialog(" in profile, "ui/common/Components.kt::DangerConfirmDialog")
    c.ok("确认框问「是否确认退出」+ 两个键（确认退出 / 取消）",
         "确认退出" in profile and "确认退出登录" in profile)
    c.ok("真正退出只在确认框的确认键里发生（`vm.logout` 还在）", "vm.logout { }" in profile)
    i_out = profile.find("退出登录")
    c.ok("「退出登录」在**可滚区域之内**（小屏才够得着）", i_out > i_scroll,
         f"退出登录位置 {i_out} / verticalScroll 位置 {i_scroll}")

    # ── 汇总 ───────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：「我的」页三端共用、行数就是拍板的那六行、"
          f"深色头部与状态栏配套、行动效有上限、基础设置与路由齐全、退出登录要确认。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
