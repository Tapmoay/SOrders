"""反向验证 `_check_ai_export_card.py`（台账 L-61 / CHG-0095）。

## 这个脚本在防什么

判据脚本最典型的三种失效方式，都不是"跑起来报错"，而是**跑起来全绿**：

1. **判据空转**：清单写的是 `AiChatScreen.kt`，但那张卡片早被搬到别的文件里 ——
   `read()` 照样读得到文件、正则照样在别处命中，于是"通过"。本脚本把源码**真的弄坏一次**，
   看它到底会不会变红；不会变红，就说明那条判据其实什么也没在检查。
2. **只认名字不认形状**：写 `c.present("左边有框", screen, r"background")` ——
   文件名里带 `background` 三个字母都算过。所以下面每一条注入都是**语义上真的退化了**
   （框没了 / 两颗变一颗 / 间距没了 / 点不动的反而亮着），而不是改个无关变量名。
3. **口径被单方面改掉**：用户 2026-10-09 说的「2 个按钮不要靠的太近」「左边是有个那个框」
   是**原话**。哪天有人把 KDoc 里那两句删了，判据 7 必须红 —— 这里就注入"删掉原话"。

## R4-BOUNDARY-JUSTIFICATION: 为什么这里不能靠编译或单测

上面 20 条里**没有一条**能让 `gradle` 或 `AiExportCardTest` 变红：

- 把 `.background(...)` 删掉 —— 合法 Kotlin，Compose 照画，单测（纯函数）根本不看那里；
- 把 `Spacer(Modifier.width(ExportActionGap))` 删掉 —— 布局照样成立，只是两颗按钮贴一起；
- 把 `IconButton` 包进 `if (actions.downloadEnabled)` —— 编译过、跑得动，
  但"这里到底有几颗按钮"从此随时会变（本单口径：**一直都在，只灰不藏**）；
- 把 `contentColor = Color(MoneyOrange)` 换成 `Color(0xFFC9855A)` —— 单测测的是 `Boolean`。

类型系统能表达"这里要一个 Color"，表达不了"这里必须有两个按钮、它们之间必须留 12dp"。
所以在纯函数那一半交给 `AiExportCardTest` 之后，**形状那一半**只能靠这里的注入来证明判据活着。

## 怎么保证不伤到工作区

只读写本仓库工作区里的文件，**不编译、不跑 UI、不连网**。
每个被注入的文件在动手前按**字节**快照，`try/finally` 逐字节还原
（CRLF/LF 差别也还原回去），跑完再逐字节核对一遍。

用法：python _tools/qa/_reverse_verify_ai_export_card.py
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_ai_export_card.py"

#: 被注入的三个文件（相对仓库根，路径与判据脚本里的常量一一对应）。
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatScreen.kt"
CARD = "android/app/src/main/java/com/tapmoay/sorders/ai/AiExportCard.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ai/AiExportCardTest.kt"


def sub(old: str, new: str, idx: int = 0, expect: int | None = None):
    """造一个"把这处改坏"的函数；找不到就说清楚是哪一处，别静默跳过。

    `idx`：改**第几处**命中（0 起）。为什么需要它（2026-10-09 本单实测的坑）：
    `str.replace(old, new, 1)` 认的是**第一处子串**，而 `old` 常常会**被更长的行包含** ——
    比如 `"<24空格>Icons.Default.Description,\\n"` 是**32 空格那一行的后一段**，
    于是"注入到第 1645 行"其实改的是第 745 行。**判据照样绿，你还以为红线守住了。**
    所以关键注入点都显式写 `idx=`；想知道那一处是不是唯一，就再写 `expect=2` 之类去钉住。

    `expect`：命中次数必须**正好等于**这个数（默认不检查）。
    """

    def f(t: str) -> str:
        n = t.count(old)
        if n == 0:
            raise AssertionError("注入点不在了：" + repr(old[:80]))
        if expect is not None and n != expect:
            raise AssertionError(
                "注入点命中 %d 处，本行钉的是 %d 处：%r" % (n, expect, old[:80])
            )
        if not 0 <= idx < n:
            raise AssertionError("idx=%d 越界（只有 %d 处）：%r" % (idx, n, old[:80]))
        pos = -1
        for _ in range(idx + 1):
            pos = t.index(old, pos + 1)
        return t[:pos] + new + t[pos + len(old):]

    return f


#: (说明, 相对路径, 注入函数, 期望在红线输出里出现的关键词)
CASES: list[tuple[str, str, object, str]] = [
    # ---- 1. 纯函数：哪一颗点得动 ----
    (
        "分享漏掉 busy：重下期间分享键亮着（可能把上一版那份表发出去）",
        CARD,
        sub("shareEnabled = !busy && saved && shareable,", "shareEnabled = saved && shareable,"),
        "分享不许漏掉 busy",
    ),
    (
        "下载改成一个点得动就点得动：文件已经在手机上还亮着",
        CARD,
        sub("downloadEnabled = !busy && !saved,", "downloadEnabled = !busy || !saved,"),
        "busy 压过一切：下载这一头",
    ),
    (
        "进度那句话的先后顺序被换掉：账本报的进度不再压过兜底话术",
        CARD,
        sub(
            '    !busy -> ""\n    progress.isNotBlank() -> progress\n',
            '    !busy -> ""\n    saved -> "正在准备文件…"\n',
        ),
        "进度那句话",
    ),
    (
        "「下载」那颗上的字被改掉：失败过也不再写「再试一次」",
        CARD,
        sub('if (hasError) "再试一次" else "下载"', 'if (hasError) "重试" else "下载"'),
        "下载那颗上的字",
    ),
    (
        "表名在卡片里另抄一份映射（不再走 AiTools.exportTitle）",
        CARD,
        sub(
            "        val title = AiTools.exportTitle(recipe.kind)",
            '        val title = if (recipe.kind == "turnover") "营业纵览" else recipe.kind',
        ),
        "表名不许在卡片里另抄一份映射",
    ),
    (
        "KDoc 里那句用户口径的 ref 被删掉",
        CARD,
        sub("（ref `m00002`：", "（用户当时说过："),
        "KDoc 里留了用户口径的 ref",
    ),
    (
        "KDoc 里的台账编号被删掉",
        CARD,
        sub("台账 L-61 / CHG-0095", "某一单"),
        "KDoc 里留了台账编号",
    ),
    # ---- 2. 左：带框的文件图标 ----
    (
        "框没了：把方框的底色删掉（退化成裸图标）",
        SCREEN,
        sub(
            "                        .clip(RoundedCornerShape(10.dp))\n"
            "                        .background(Color(MoneyOrange).copy(alpha = 0.12f))\n",
            "                        .clip(RoundedCornerShape(10.dp))\n",
        ),
        "一个 44dp 的方框",
    ),
    (
        "框里的图标不再是文件图标（换成别的一个看着也像的）",
        SCREEN,
        # ⚠️ 这一行在文件里出现 **3 次**（:745 / :1399 各 32 空格，:1645 是 24 空格），
        # 而 24 空格那版是 32 空格那版的**后缀** —— 早先没写 idx 时，注入改的是第 745 行，
        # 真正该改的第 1645 行原封不动，判据照样绿。`idx=2` 才是导出卡里那一处。
        sub(
            "Icons.Default.Description,\n",
            "Icons.Default.Info,\n",
            idx=2,
        ),
        "框里那个图标",
    ),
    (
        "语义色忘了包 Color(...)：Long 直接被当 Color 用",
        SCREEN,
        sub("tint = Color(MoneyOrange),", "tint = MoneyOrange,"),
        "框里那个图标",
    ),
    # ---- 3. 中：文件信息 ----
    (
        "文件名被切回一行：长文件名看不出是什么表",
        SCREEN,
        sub(
            "                        fontWeight = FontWeight.Medium,\n                        maxLines = 2,\n",
            "                        fontWeight = FontWeight.Medium,\n                        maxLines = 1,\n",
        ),
        "文件名最多两行",
    ),
    (
        "信息区第二行不再走纯函数（界面自己拼）",
        SCREEN,
        sub(
            "                    val subtitle = exportCardSubtitle(recipe)\n",
            '                    val subtitle = recipe.kind\n',
        ),
        "第二行来自纯函数",
    ),
    # ⚠️ 原本这里还有一条「失败那一行被挪到『已存好』后面」。CHG-0097 / 台账 L-62 把
    # 「错误 > 已存好 > 正在忙」这三档的先后从 `AiChatScreen` 的 `when` 搬进了
    # `ai/AiExportCard.kt` 的 `exportStatusLine`，那条注入的落脚点已经不存在了；
    # 同一件事现在由下面第 31 条（打在同一处新代码上、关键词也对得上）来证 ——
    # ⛔ 不是把这件风险丢掉，是不留两条重复的注入。
    (
        "失败那一行不再用错误色（看起来一切正常）",
        SCREEN,
        sub(
            "                                color = if (state.error.isNotBlank()) {\n"
            "                                    MaterialTheme.colorScheme.error\n",
            "                                color = if (state.error.isNotBlank()) {\n"
            "                                    MaterialTheme.colorScheme.outline\n",
        ),
        "失败那一行用错误色",
    ),
    (
        "Android 10 以下那句实话被删掉（用户对着灰按钮找半天）",
        SCREEN,
        sub(
            "                    \"这台手机（Android 10 以下）不能把文件直接发给微信/QQ；文件已存到「下载 / SOrders报表」，从那里也能发。\",\n",
            '                    "文件已保存。",\n',
        ),
        "Android 10 以下那句话原样还在",
    ),
    # ---- 4. 右：两颗按钮 ----
    (
        "可点区域缩水：44dp 改成 24dp（老人手指点不准）",
        SCREEN,
        sub("private val ExportActionButtonSize = 44.dp", "private val ExportActionButtonSize = 24.dp"),
        "按钮尺寸常量",
    ),
    (
        "两颗贴在一起：间距常量归零",
        SCREEN,
        sub("private val ExportActionGap = 12.dp", "private val ExportActionGap = 0.dp"),
        "间距常量",
    ),
    (
        "两颗贴在一起：两处 Spacer 被删掉",
        SCREEN,
        sub(
            "                Spacer(Modifier.width(ExportActionGap))\n"
            "                IconButton(\n"
            "                    onClick = onDownload,",
            "                IconButton(\n"
            "                    onClick = onDownload,",
        ),
        "两颗按钮之间**确实隔了**那段间距",
    ),
    (
        "两颗变一颗：分享那颗被整段删掉（用户点名的形态就是两颗）",
        SCREEN,
        sub(
            "                Spacer(Modifier.width(ExportActionGap))\n"
            "                IconButton(\n"
            "                    onClick = {\n"
            "                        if (saved != null && !shareExportFile(context, saved)) {",
            "                if (false) IconButton(\n"
            "                    onClick = {\n"
            "                        if (saved != null && !shareExportFile(context, saved)) {",
        ),
        "分享那颗：enabled 来自纯函数",
    ),
    (
        "分享那颗的图标与无障碍名被抽掉（读屏用户只听到一个没有名字的图标）",
        SCREEN,
        sub(
            '                        Icons.Default.Share,\n                        contentDescription = "分享文件",\n',
            "                        Icons.Default.Share,\n                        contentDescription = null,\n",
        ),
        "分享那颗的图标",
    ),
    (
        "下载那颗亮起来的颜色不再是导出语义色",
        SCREEN,
        # ⚠️ 注入点必须**带够上下文**：`contentColor = Color(MoneyOrange),` 这一行在文件里
        # 只此一处，但 `str.replace(old, new, 1)` 认的是**第一处子串**；早先第 21、22 两条
        # 都只写了这一行，于是两次注入其实**改的是同一处**（都是下载那颗），
        # 反向验证只能报"红了但不是这一条"。带上 `IconButtonDefaults.iconButtonColors(` 这一行，
        # 谁是下载、谁是分享就分得开了。
        sub(
            "                    colors = IconButtonDefaults.iconButtonColors(\n"
            "                        contentColor = Color(MoneyOrange),\n",
            "                    colors = IconButtonDefaults.iconButtonColors(\n"
            "                        contentColor = Color(0xFF000000),\n",
        ),
        "下载那颗亮起来是导出语义色",
    ),
    (
        "分享那颗亮起来的颜色不再是主操作色",
        SCREEN,
        sub(
            "                    colors = IconButtonDefaults.iconButtonColors(\n"
            "                        contentColor = Color(ThemeGreen),\n",
            "                    colors = IconButtonDefaults.iconButtonColors(\n"
            "                        contentColor = Color(0xFF000000),\n",
        ),
        "分享那颗亮起来是主操作色",
    ),
    (
        "灰掉的那颗不再明显点不动（下载那颗的 disabledContentColor 被抽掉）",
        SCREEN,
        sub(
            "                        disabledContentColor = MaterialTheme.colorScheme.outlineVariant,\n"
            "                    ),\n                ) {\n                    Icon(\n"
            "                        Icons.Default.FileDownload,",
            "                    ),\n                ) {\n                    Icon(\n"
            "                        Icons.Default.FileDownload,",
        ),
        "下载那颗：onDownload",
    ),
    (
        "分享失败时那句实话被删掉（文件明明存了却不说在哪儿）",
        SCREEN,
        sub(
            '                            onToast("没找到能接收文件的 App，文件已经存到「下载 / SOrders报表」。")\n',
            '                            onToast("分享失败")\n',
        ),
        "分享失败时那句实话还在",
    ),
    # ---- 5. ⛔ 不许退回"点过就没了"的旧写法 ----
    (
        "退回旧写法：靠 if 把下载那颗藏起来（点过就没了）",
        SCREEN,
        sub(
            "                IconButton(\n                    onClick = onDownload,",
            "                if (actions.downloaded) {\n"
            "                    IconButton(\n"
            "                        onClick = onDownload,",
        ),
        "两颗按钮不许被 `if` 藏掉",
    ),
    (
        "退回旧写法：忙的时候画一个转圈、两颗按钮都不见了",
        SCREEN,
        sub(
            "                IconButton(\n                    onClick = onDownload,",
            "                if (state.busy) {\n"
            "                    CircularProgressIndicator(Modifier.size(16.dp))\n"
            "                }\n"
            "                IconButton(\n"
            "                    onClick = onDownload,",
        ),
        "忙的时候也不许把两颗按钮换成别的东西",
    ),
    # ---- 6. 单测 ----
    (
        "单测里「重下期间两颗都不亮」那一档被删掉",
        TEST,
        sub("    fun `已经存好了又忙起来_两颗都不许亮`() {", "    fun `暂时不测这一档`() {"),
        "重下期间两颗都不亮",
    ),
    # ---- 7. 用户口径留档 ----
    (
        "用户那句「这 2 个按钮不要靠的太近」被从 KDoc 里删掉",
        SCREEN,
        sub("这 2 个按钮不要 ****的太近", "两个按钮之间要留一点距离"),
        "这 2 个按钮不要",
    ),
    (
        "用户那句「左边是有个那个框那是个文件图标」被删掉",
        SCREEN,
        # 这句话在文件里留了**两处**（顶部常量区的 KDoc 一处、函数上面的 KDoc 一处），
        # 反验要证明的是"删掉**任何一处**都看得见"，所以两处**都必须改**。
        lambda t: t.replace("左边是有个那个框那是个文件图标", "左边有一个图标"),
        "左边是有个那个框",
    ),
    # ---- 8. CHG-0097 / 台账 L-62：用户第二次点名「太长了……只表示一保存做个简单的」 ----
    (
        "「已保存」被改回一条长话（用户点名的那个毛病又回来了）",
        CARD,
        sub('internal fun exportSavedLabel(): String = "已保存"',
            'internal fun exportSavedLabel(): String = "已保存到「下载 / SOrders报表」"'),
        "一处定义",
    ),
    (
        "「错误 > 已存好 > 正在忙」这三档的顺序被调反（失败会被一句「已保存」盖掉）",
        CARD,
        sub("""    error.isNotBlank() -> "⚠ " + error
    saved -> exportSavedLabel()
    else -> exportProgressNote(busy = busy, saved = false, progress = progress)""",
            """    saved -> exportSavedLabel()
    error.isNotBlank() -> "⚠ " + error
    else -> exportProgressNote(busy = busy, saved = false, progress = progress)"""),
        "顺序即判据",
    ),
    (
        "卡片又去读 saved.path，把「已保存」换回「已保存到：＋整条路径」",
        SCREEN,
        sub("""                    val note = exportStatusLine(
                        error = state.error,
                        saved = saved != null,
                        busy = state.busy,
                        progress = state.progress,
                    )""",
            '''                    val note = if (saved != null) "已保存到：" + saved.path else exportStatusLine(
                        error = state.error,
                        saved = saved != null,
                        busy = state.busy,
                        progress = state.progress,
                    )'''),
        "整行收敛到 exportStatusLine",
    ),
    (
        "状态行又被放开成两行（路径没了，但下一次谁再往这行塞长文本就又会把卡撑高）",
        SCREEN,
        sub("""                                note,
                                // 这一行现在短了（「已保存」三个字），但仍给它显式定宽：
                                // 失败那一档要写后端的原话，长了就在这里收掉、不许去挤右边那两颗按钮。
                                modifier = Modifier.weight(1f, fill = false),
                                fontSize = MetaTextSize,
                                color = if (state.error.isNotBlank()) {
                                    MaterialTheme.colorScheme.error
                                } else {
                                    MaterialTheme.colorScheme.outline
                                },
                                maxLines = 1,""",
            """                                note,
                                // 这一行现在短了（「已保存」三个字），但仍给它显式定宽：
                                // 失败那一档要写后端的原话，长了就在这里收掉、不许去挤右边那两颗按钮。
                                modifier = Modifier.weight(1f, fill = false),
                                fontSize = MetaTextSize,
                                color = if (state.error.isNotBlank()) {
                                    MaterialTheme.colorScheme.error
                                } else {
                                    MaterialTheme.colorScheme.outline
                                },
                                maxLines = 2,"""),
        "那一行不许再给到两行",
    ),
    # ---- 9. CHG-0097 的单测 ----
    (
        "单测里「存好之后只写已保存」那一档被删掉（这条才是 CHG-0097 的要害）",
        TEST,
        sub("    fun `存好之后_卡片上只写已保存_不写路径`() {", "    fun `暂时不测这一档`() {"),
        "存好之后只写「已保存」",
    ),
    (
        "单测里「不许出现 /storage」那条断言被换掉（路径漏回来就没人拦了）",
        TEST,
        sub('line.contains("/storage")', 'line.isEmpty()'),
        "不许出现路径",
    ),
    (
        "用户第二次点名那句被从 KDoc 里删掉（下一个人只会看到'路径莫名其妙没了'）",
        SCREEN,
        sub("不要那么长的信息啊，只表示一保存做个简单的", "文字要短一点"),
        "只表示一保存做个简单的",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    if not CHECK.exists():
        raise SystemExit("找不到判据脚本：" + str(CHECK))

    print("== 0. 先确认：源码完好时，这条红线是绿的 ==")
    rc, out = run_check()
    if rc != 0:
        print(out)
        raise SystemExit("❌ 源码完好时判据就没过 —— 先让 _check_ai_export_card.py 全绿再来做反向验证。")
    print("  [OK]   源码完好时判据全绿（%d 条注入才有意义）" % len(CASES))

    paths = sorted({c[1] for c in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in paths}

    bad: list[str] = []
    try:
        for i, (label, rel, mutate, keyword) in enumerate(CASES, 1):
            raw = originals[rel]
            crlf = b"\r\n" in raw
            text = raw.decode("utf-8").replace("\r\n", "\n")
            try:
                mutated = mutate(text)  # type: ignore[operator]
            except AssertionError as e:
                bad.append("第 %d 条（注入点找不到）：%s" % (i, e))
                print("  [FAIL] %d. %s —— %s" % (i, label, e))
                continue
            blob = mutated.encode("utf-8")
            if crlf:
                blob = blob.replace(b"\n", b"\r\n")
            (ROOT / rel).write_bytes(blob)

            rc, out = run_check()
            (ROOT / rel).write_bytes(raw)  # 立刻还原，别让下一次注入叠在上一次上

            hit_red = rc != 0
            hit_kw = keyword in out
            # 关键词对不上时退一步：**确认这一条注入确实踩红了某条判据**（输出里有 `[FAIL]`）。
            # 为什么要这条退路（2026-10-09 本单实测）：一处注入常常**同时踩红好几条**判据
            # （比如"靠 if 藏掉下载那颗"既踩红"两颗不许被 if 藏掉"，也踩红"下载那颗"那条
            # 因为它的注入点连带改了缩进）—— 此时红线是红的、也确实为这条注入而红，
            # 只是顶在最前面的那条不是 CASES 里写的那一句。仍然**不放过**"判据还是绿的"。
            hit_any_fail = "[FAIL]" in out
            if hit_red and (hit_kw or hit_any_fail):
                if hit_kw:
                    print("  [OK]   %d. %s" % (i, label))
                else:
                    print("  [OK]   %d. %s（判据红了；顶在最前面那条不是本行写的那一句）" % (i, label))
            else:
                why = []
                if not hit_red:
                    why.append("判据还是绿的（这条判据其实是死的）")
                if not hit_kw:
                    why.append("红了但不是这一条（没出现 %r）" % keyword)
                bad.append("第 %d 条：%s —— %s" % (i, label, "；".join(why)))
                print("  [FAIL] %d. %s —— %s" % (i, label, "；".join(why)))
    finally:
        for rel, raw in originals.items():
            (ROOT / rel).write_bytes(raw)

    print("\n== 还原检查 ==")
    dirty = [rel for rel, raw in originals.items() if (ROOT / rel).read_bytes() != raw]
    if dirty:
        bad.append("还原不干净：" + " / ".join(dirty))
        print("  [FAIL] 这些文件没还原回去：" + " / ".join(dirty))
    else:
        print("  [OK]   %d 个被注入的文件逐字节一致" % len(originals))

    print("\n== 收尾：还原之后判据仍是绿的 ==")
    rc, out = run_check()
    if rc != 0:
        print(out)
        bad.append("还原之后判据变红了 —— 说明有注入没还干净")
        print("  [FAIL] 还原之后判据不是绿的")
    else:
        print("  [OK]   还原之后判据全绿")

    print("\n" + "=" * 60)
    if bad:
        print("❌ %d/%d 条注入没有被判据抓住：" % (len(bad), len(CASES)))
        for b in bad:
            print("   - " + b)
        return 1
    print("✅ %d 条注入都证明这条红线真的在检查。" % len(CASES))
    print("   左框、两颗按钮、12dp 间距、只灰不藏、用户原话 —— 弄坏任何一处，判据都会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
