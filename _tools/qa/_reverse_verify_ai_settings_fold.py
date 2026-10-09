"""反向验证：把「AI 设置页能力说明默认折叠」的每条判据逐条弄坏一次，看它真的变红。

## 这个脚本存在的唯一理由
判据脚本（`_check_ai_settings_fold.py`）自己也可能**空转**——正则写松了、锚点飘到别的行上、
或者文件被改名之后"扫不到就算过"。本脚本对每条判据做一次**外科手术式的破坏**，
然后跑判据，要求它**必须变红**；跑完把文件逐字节还原。

## 三种典型失效方式（每一种都在本项目里真实发生过）
1. **判据空转**：正则 `[\s\S]{0,200}` 这类窗口写小了/写大了，注入打到别处，判据照样绿。
2. **只认名字不认形状**：只查"有没有 `capacityExpanded` 这个词"，那么把
   `mutableStateOf(false)` 改成 `mutableStateOf(true)` 也照样绿。
3. **口径被单方面改掉**：把用户原话从 KDoc 里删掉、把台账号删掉 —— 谁都不会报错，
   下一个人就不知道为什么给这一段加了个盖子。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
本脚本**只读写工作区文件、不编译、不跑 UI**（跑一次 gradle 要几十秒，反向验证要跑十几轮）。
它证明的是"判据真的在监控那几处源码结构"，而不是"界面真的折叠了"——
界面那一层由真机截图取证（见变更单 ⑧）。

用法：python _tools/qa/_reverse_verify_ai_settings_fold.py
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_ai_settings_fold.py"
SETTINGS = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiSettingsScreen.kt"
CARD = "android/app/src/main/java/com/tapmoay/sorders/ai/AiCapabilitySummary.kt"
PROMPT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiRolePrompt.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ai/AiCapabilitySummaryTest.kt"
DOC = "docs/changes/CHG-0098.md"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"


def sub(old: str, new: str, idx: int = 0, expect: int | None = None):
    """把 `old` 的第 `idx` 处命中换成 `new`。

    ⚠️ 为什么不用 `str.replace(old, new, 1)`：它认第一处**子串**，而 `old` 常被更长的一行包含
    （CHG-0097 那次实测：注入"改到了 :745"而不是想改的 :1645，判据照样绿）。
    `expect` 用来钉住"这个串在文件里到底有几处"，对不上就当场失败，不许静默跳过。
    """

    def f(t: str) -> str:
        n = t.count(old)
        if n == 0:
            raise AssertionError("注入点不在了：" + repr(old[:80]))
        if expect is not None and n != expect:
            raise AssertionError("注入点命中 %d 处（期望 %d）：%s" % (n, expect, repr(old[:80])))
        pos = -1
        for _ in range(idx + 1):
            pos = t.index(old, pos + 1)
        return t[:pos] + new + t[pos + len(old):]

    return f


#: (说明, 相对路径, 注入函数, 期望在判据输出里出现的关键词)
CASES: list[tuple[str, str, object, str]] = [
    (
        "折叠的默认值被改成展开（用户抱怨的那一屏立刻回来）",
        SETTINGS,
        sub("var capacityExpanded by rememberSaveable { mutableStateOf(false) }",
            "var capacityExpanded by rememberSaveable { mutableStateOf(true) }"),
        "默认不许是展开的",
    ),
    (
        "折叠态退回普通 remember（滚动/转屏一趟就丢）",
        SETTINGS,
        sub("var capacityExpanded by rememberSaveable { mutableStateOf(false) }",
            "var capacityExpanded by remember { mutableStateOf(false) }"),
        "折叠态不许退回普通 remember",
    ),
    (
        "那一行的 clickable 被拿掉（折叠块成了点不动的死块）",
        SETTINGS,
        sub(".clickable { capacityExpanded = !capacityExpanded }\n", ""),
        "整行可点",
    ),
    (
        "`if (capacityExpanded)` 那层壳被删掉（正文又全摊开）",
        SETTINGS,
        sub("if (capacityExpanded) {\n                            Spacer(Modifier.height(2.dp))",
            "if (true) {\n                            Spacer(Modifier.height(2.dp))"),
        "正文只在 if (capacityExpanded) 里画",
    ),
    (
        "标题不再走纯函数（有人手写了一句死文案）",
        SETTINGS,
        sub('capabilitySummaryLabel(\n                                    counts = capabilitySummaryCounts(capacitySummary),\n                                    expanded = capacityExpanded,\n                                ),',
            '"查看能力清单",'),
        "标题来自纯函数",
    ),
    (
        "隐私与费用那句被卷进折叠里（用户最关心的信息要点开才看得到）",
        SETTINGS,
        sub('"API Key 加密存在本机、不上传；费用你自己承担。",\n',
            ""),
        "隐私与费用那句还在",
    ),
    (
        "只读开关那一项被砍掉（那行数字就不会跟着开关动了）",
        SETTINGS,
        sub("readModules = vm.readModules.filter { it.enabled }.map { it.module }.toSet(),",
            "readModules = AiReads.allModules().toSet(),"),
        "仍带 readModules",
    ),
    (
        "能力声明被顺手改窄（模型会跟着否认自己的能力）",
        PROMPT,
        sub('——它只会把改动做成一张确认卡，你点「确认」才会写进系统。',
            '——小改动会直接写进系统。'),
        "“能改”那行结尾仍是那句确认卡说明",
    ),
    (
        "标题退化成光秃秃的「展开」（“有多少东西”一并藏了）",
        CARD,
        sub('expanded -> "收起清单"', 'expanded -> "展开"'),
        "标题不许退化成光秃秃的",
    ),
    (
        "「收起」那档被换成点开看清单（点第二次不知道会发生什么）",
        CARD,
        sub('expanded -> "收起清单"', 'expanded -> "能做什么（点开看清单）"'),
        '收起清单',
    ),
    (
        "四档顺序被调反（认不出角色那档掉到最后）",
        CARD,
        sub('    expanded -> "收起清单"\n    !counts.canWriteKnown -> "能做什么（点开看清单）"\n',
            '    expanded -> "收起清单"\n'),
        "签名与四档逐字",
    ),
    (
        "一项能改的都没有时去报「能改 0 项」（把人吓一跳的假结论）",
        CARD,
        sub('    counts.canWrite <= 0 -> "能查 ${counts.canRead} 项（点开看清单）"\n', ""),
        "能改 0 项",
    ),
    (
        "计数改成手写一张清单（不再数那段话）",
        CARD,
        sub('val line = summary.lineSequence().firstOrNull { it.startsWith("能改") }',
            'val line = "能改：没有。"'),
        "计数是从那段话里数出来的",
    ),
    (
        "兜底话「暂时没有…」被当成清单里的一项",
        CARD,
        sub('if (body.startsWith("暂时没有") || body.startsWith("没有")) return 0', ""),
        "兜底话不算清单里的一项",
    ),
    (
        "单测里「认不出角色不许报数」那一档被删",
        TEST,
        sub("    @Test\n    fun `认不出角色_不许报数_只说点开看清单`() {", "    fun skipped_认不出角色() {"),
        "认不出角色_不许报数_只说点开看清单",
    ),
    (
        "单测里「展开态写收起」那一档被删",
        TEST,
        sub("    @Test\n    fun `展开之后那句要写收起_不然点不动第二次`() {", "    fun skipped_收起() {"),
        "展开之后那句要写收起_不然点不动第二次",
    ),
    (
        "单测「数字跟开关联动」那条反证被删（数字从此没人看着）",
        TEST,
        sub("    @Test\n    fun `数出来的项数跟开关联动_关掉一个少一项`() {", "    fun skipped_联动() {"),
        "数出来的项数跟开关联动_关掉一个少一项",
    ),
    (
        "用户那句原话被从 KDoc 里删掉（下一个人不知道为什么加盖子）",
        CARD,
        lambda t: t.replace("不然太长了很占位子", "太长了"),
        "不然太长了很占位子",
    ),
    (
        "台账号被从 KDoc 里删掉",
        CARD,
        lambda t: t.replace("台账 L-63", "本单"),
        "台账编号 L-63",
    ),
    (
        "设计系统那一节被改名（文书对不上）",
        DESIGN,
        lambda t: t.replace("### 4.25f ", "### 4.25g ", 1),
        "4.25f",
    ),
]


def run_check() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )


def main() -> int:
    if not CHECK.exists():
        raise SystemExit("判据脚本不见了：" + str(CHECK))

    print("== 0. 源码完好时，判据必须是全绿的 ==")
    base = run_check()
    if base.returncode != 0:
        print(base.stdout[-4000:])
        raise SystemExit("❌ 源码现在是坏的 —— 先把判据跑绿再来做反向验证。")
    print("  [OK]   判据现在是绿的（%d 行输出）" % len(base.stdout.splitlines()))

    originals: dict[str, bytes] = {}
    for rel in {c[1] for c in CASES}:
        originals[rel] = (ROOT / rel).read_bytes()

    dirty: list[str] = []
    ok = 0
    try:
        for i, (label, rel, mutate, keyword) in enumerate(CASES, 1):
            raw = originals[rel]
            crlf = b"\r\n" in raw
            text = raw.decode("utf-8")
            if crlf:
                text = text.replace("\r\n", "\n")
            try:
                broken = mutate(text)  # type: ignore[operator]
            except AssertionError as e:
                print("  [FAIL] 第 %d 条注入写错了：%s —— %s" % (i, label, e))
                dirty.append(label)
                continue
            if broken == text:
                print("  [FAIL] 第 %d 条注入**什么都没改**：%s" % (i, label))
                dirty.append(label)
                continue
            blob = broken.encode("utf-8")
            if crlf:
                blob = blob.replace(b"\n", b"\r\n")
            (ROOT / rel).write_bytes(blob)
            dirty.append(rel)
            try:
                r = run_check()
            finally:
                (ROOT / rel).write_bytes(raw)
                dirty.remove(rel)
            hit_red = r.returncode != 0
            hit_kw = keyword in r.stdout
            if hit_red and hit_kw:
                print("  [OK]   第 %d 条：%s ⇒ 判据报红" % (i, label))
                ok += 1
            elif hit_red:
                print("  [WARN] 第 %d 条：%s ⇒ 红了，但不是这一条（关键词没出现）" % (i, label))
            else:
                print("  [FAIL] 第 %d 条：%s ⇒ **判据还是绿的（这条判据是死的）**" % (i, label))
    finally:
        for rel, raw in originals.items():
            (ROOT / rel).write_bytes(raw)

    print("\n== 1. 还原检查 ==")
    for rel, raw in originals.items():
        now = (ROOT / rel).read_bytes()
        if now != raw:
            print("  [FAIL] %s 没有逐字节还原" % rel)
            return 1
    print("  [OK]   %d 个被注入的文件逐字节一致" % len(originals))

    print("\n== 2. 还原之后判据还得是绿的 ==")
    after = run_check()
    if after.returncode != 0:
        print(after.stdout[-4000:])
        print("  [FAIL] 还原之后判据是红的 —— 说明还原不干净")
        return 1
    print("  [OK]   还原之后判据全绿")

    print("\n" + "=" * 60)
    if ok == len(CASES):
        print("✅ %d 条注入都证明这条红线真的在检查。" % ok)
        return 0
    print("❌ 只有 %d/%d 条注入被抓住。" % (ok, len(CASES)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
