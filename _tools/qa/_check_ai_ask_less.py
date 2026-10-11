#!/usr/bin/env python
"""**AI 少问、按已文档化的默认值直接执行**（CHG-0120）的机器判据。

用户 2026-10-11 的口径（逐字）：
> 「这个 AI 啊**太过繁琐**了 —— 教他执行任务了，他**老是反复确定**，但其实任务其实
>   **也全都已经写好了、基本是已经确认的**。」

真机证据（用户贴的截图）：一张 21 人的表格 ＋「按表格创建批发商账号和商品」，模型分了好几轮
才动手 —— 初始密码（**规定就是 123321**）、默认单价、成本价存哪一格（**口径是进货成本**）、
要不要设专属价（**表格里逐家两栏价 ⇒ 本来就该设**）都被反问了一遍；其中至少三条**早就有答案**。

盯六件事（缺一件这条口径就没落地，而且**每一件坏掉都不报错**）：
1. 默认值清单**真的进了提示词**：`AiDefaults.RULES` 有那六条，且 `AiAgentLoop.systemPrompt` 里拼了它；
2. 三条规则语句都在：能推断就别问 / 假设写在卡上 / 真要问就一次问全；
3. 安全底线**没有被顶掉**：那段文字自己写了「钱 / 身份 / 撤不回来 ＋ 没有默认值 ⇒ 必须问」，
   而且 `AiAgentLoop` 里原来那条「绝不许替他决定」一个字没动；
4. **一个数只有一处**：提示词里那两处初始密码都取自 `AccountRules.DEFAULT_INITIAL_PASSWORD`，
   `AiRolePrompt.kt` 的**代码**里不许出现字面量（抄两处就会分叉，而分叉不报错）；
5. 清单条目**能追到出处**：`docs/AI_DEFAULTS.md` 每条都在，且它点到的仓库路径都真实存在；
6. 单测 >= 6 例、文书三件套（九节变更单 / 登记簿 / 工作声明）与可达性在位。

R4-BOUNDARY-JUSTIFICATION: 本判据**不下沉到任何一层边界**。它查的全是「同一句口径写在哪、谁读它」：
那段文字在哪个 Kotlin 常量里、systemPrompt 有没有把它拼进去、提示词里的数字是不是引用
`AccountRules.DEFAULT_INITIAL_PASSWORD`（而不是手抄）、`docs/AI_DEFAULTS.md` 的出处指向哪些文件。
后端契约、领域类型、权限模型里都没有它们的位置 —— 「AI 要不要先问用户」是**提示词层**的行为，
把它下沉成 API 参数或领域对象既治不了它要防的病（**两处口径分叉**），也会把一句给人读的话
变成谁都不敢改的结构。反向验证：`python _tools/qa/_reverse_verify_ai_ask_less.py`。

用法：python _tools/qa/_check_ai_ask_less.py    （--list 打一份人读清单）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "android" / "app" / "src"
AND = SRC / "main" / "java" / "com" / "tapmoay" / "sorders"
AND_TEST = SRC / "test" / "java" / "com" / "tapmoay" / "sorders"
ROLE = AND / "ai" / "AiRolePrompt.kt"
LOOP = AND / "ai" / "AiAgentLoop.kt"
KT_TEST = AND_TEST / "ai" / "AiAskLessTest.kt"
DOC = ROOT / "docs" / "AI_DEFAULTS.md"
CHG = ROOT / "docs" / "changes" / "CHG-0120.md"
REGISTRY = ROOT / "docs" / "changes" / "README.md"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"
INDEX = ROOT / "docs" / "PROJECT_MAP" / "INDEX.md"
REVERSE = ROOT / "_tools" / "qa" / "_reverse_verify_ai_ask_less.py"

# ── 反空转下限（扫描规则/文件被改坏时先喊，不许安静地全绿）──────────────────
MIN_RULES_CHARS = 800      # 提示词正文（抽不到就说明 AiDefaults 被改名/清空了）
MIN_KT_TESTS = 6           # 单测用例数
MIN_DOC_PATHS = 6          # 文档里点到的仓库路径条数
MIN_DOC_CHARS = 1500       # 文档正文长度
MIN_INJECTIONS = 5         # 反向验证的注入条数

#: 清单里每一句口径：标签 → 提示词里必须逐字出现的那一段 → 文档里必须出现的那一段
ITEMS: list[tuple[str, str, str]] = [
    ("初始密码（所有账号默认那个值）", "**初始密码**：所有账号默认", "初始密码"),
    ("成本价那一格 = 进货成本", "那一格填**进货成本**", "填**进货成本**"),
    ("默认单价取表格里的零售价", "**默认单价**：表格", "默认单价"),
    ("单位沿用同类 / 既有商品", "沿用**同类或既有商品**的单位", "沿用**同类 / 既有商品**"),
    ("表里逐家给了价 ⇒ 直接设专属价", "直接按表格设专属价", "直接按表格设专属价"),
    ("表里没给价的那几行照建、专属价留空", "照建，专属价留空", "照建、专属价留空"),
]

#: 文档里点到的仓库路径（出处列）—— 每一条都必须真实存在，否则「出处」是编的
PATH_RE = re.compile(r"(?:backend|android|docs|_tools|frontend)/[A-Za-z0-9_./-]+\.(?:py|kt|md|txt|json|yml)")

SECTIONS = "①②③④⑤⑥⑦⑧⑨"


def rules_block(src: str) -> str:
    """从 `AiRolePrompt.kt` 里抽出那段提示词正文（`internal object AiDefaults` 起，到文件尾）。"""
    i = src.find("internal object AiDefaults")
    return src[i:] if i >= 0 else ""


def check() -> tuple[Checker, list[str]]:
    """跑一遍全部判据。返回 (Checker, 给人读的清单)。"""
    c = Checker()
    checklist: list[str] = []

    # ── 0. 反空转 ───────────────────────────────────────────────────────
    c.section("0. 反空转（文件/扫描规则被改坏时必须先喊）")
    need = [
        (ROLE, "提示词正文（AiDefaults.RULES）"),
        (LOOP, "systemPrompt"),
        (KT_TEST, "单测"),
        (DOC, "默认值清单文档"),
        (CHG, "变更单"),
        (REGISTRY, "事项登记簿"),
        (CLAIM, "工作声明"),
        (INDEX, "文档地图"),
        (REVERSE, "反向验证脚本"),
    ]
    missing = [p for p, _ in need if not p.exists()]
    c.ok("九份关键文件都在（缺 %d 个）" % len(missing), not missing,
         "修法：先补齐这些文件：" + "、".join(str(p.relative_to(ROOT)) for p in missing))
    if missing:
        print("\n❌ 关键文件缺失 —— 后面的判据全部跳过（不许安静地绿）")
        return c, checklist

    role_src = read(ROLE)
    role_code = strip_comments(role_src)
    loop_code = strip_comments(read(LOOP))
    rules = rules_block(role_src)
    c.ok("从 AiRolePrompt.kt 抽到提示词正文（%d 字符，下限 %d）" % (len(rules), MIN_RULES_CHARS),
         len(rules) >= MIN_RULES_CHARS,
         "修法：`internal object AiDefaults { val RULES ... }` 是不是被改名或清空了？")

    # ── 1. 清单真的进了提示词 ───────────────────────────────────────────
    c.section("1. 默认值清单真的进了提示词")
    for label, frag, _doc_kw in ITEMS:
        checklist.append("清单里有这一条：" + label)
        c.ok("清单里有这一条：" + label, frag in rules,
             "修法：把「" + label + "」这一条加回 `AiRolePrompt.AiDefaults.RULES`（CHG-0120）")
    c.ok("清单指向唯一那份完整版（docs/AI_DEFAULTS.md）", "docs/AI_DEFAULTS.md" in rules,
         "修法：在 `AiDefaults.RULES` 里写明「这张单子的完整版与各条出处：docs/AI_DEFAULTS.md」（CHG-0120）")
    checklist.append("systemPrompt 里 append(AiDefaults.RULES)")
    c.ok("提示词把这段拼进了 systemPrompt（append(AiDefaults.RULES)）",
         "append(AiDefaults.RULES)" in loop_code,
         "修法：在 AiAgentLoop.systemPrompt 里把 `append(AiDefaults.RULES)` 加回去（CHG-0120）")

    # ── 2. 三条规则语句 ────────────────────────────────────────────────
    c.section("2. 三条规则语句都在")
    checklist.append("能推断就别问")
    c.ok("能推断就别问（能按下面这张单子推断出来的，不要问）",
         "能按下面这张单子推断出来的，不要问" in rules,
         "修法：把「能按下面这张单子推断出来的，不要问」加回 AiDefaults.RULES（CHG-0120）")
    checklist.append("假设写在卡上")
    c.ok("假设要写在卡上（用过的假设写在**卡片**上）",
         "用过的假设写在**卡片**上" in rules,
         "修法：把「用过的假设写在**卡片**上」加回 AiDefaults.RULES（CHG-0120）")
    checklist.append("真要问就一次问全")
    c.ok("真要问就一次问全（并禁止一轮问一个）",
         ("真要问，就一次问全" in rules) and ("不许一轮问一个" in rules),
         "修法：把「真要问，就一次问全」加回 AiDefaults.RULES（连同「不许一轮问一个」，CHG-0120）")

    # ── 3. 安全底线 ────────────────────────────────────────────────────
    c.section("3. 安全底线没有被顶掉")
    checklist.append("边界三类（钱 / 身份 / 撤不回来）")
    c.ok("边界三类写全（钱 / 身份 / 撤不回来）",
         all(w in rules for w in ("钱", "身份", "撤不回来")),
         "修法：把「动到钱 / 身份权限 / 撤不回来的操作」三类写回 AiDefaults.RULES（CHG-0120）")
    checklist.append("前提是没有默认值才问")
    c.ok("边界写明前提是「没有默认值」才问",
         ("都没有默认值" in rules) and ("必须先问他" in rules),
         "修法：把「而且这张单子和工具说明里都没有默认值 ⇒ 必须先问他」加回 AiDefaults.RULES（CHG-0120）")
    c.ok("拿不准按没有处理（不许猜一个数字填进钱/身份那一格）",
         ("按没有处理" in rules) and ("不许猜一个数字" in rules),
         "修法：把「拿不准算不算有默认值时按没有处理」加回 AiDefaults.RULES（CHG-0120）")
    c.ok("确认卡没有被这张单子绕过", "跳过确认卡" in rules,
         "修法：把「也不许借这张单子跳过确认卡」加回 AiDefaults.RULES（CHG-0120）")
    checklist.append("原「绝不许替他决定」一个字没动")
    c.ok("AiAgentLoop 里原来那条「绝不许替他决定」还在",
         "绝不许替他决定" in loop_code,
         "修法：原来的「你不知道的事就去问，绝不许替他决定」不许删 —— 只许被新那段收窄（CHG-0120）")

    # ── 4. 一个数只有一处 ──────────────────────────────────────────────
    c.section("4. 一个数只有一处（不许手抄）")
    checklist.append("密码引用 AccountRules 常量")
    c.ok("提示词里两处密码都引用 AccountRules.DEFAULT_INITIAL_PASSWORD",
         role_code.count("AccountRules.DEFAULT_INITIAL_PASSWORD") >= 2,
         "修法：提示词里的密码必须引用 AccountRules.DEFAULT_INITIAL_PASSWORD（清单里一处、卡片例子里一处），"
         "⛔ 不许手抄数字（CHG-0120）")
    c.ok("AiRolePrompt.kt 的代码里没有密码字面量（抄两处就会分叉）",
         "123321" not in role_code,
         "修法：把密码字面量换回 AccountRules.DEFAULT_INITIAL_PASSWORD（CHG-0120）")
    c.ok("同一个常量在 AiAgentLoop 里仍然是引用",
         "AccountRules.DEFAULT_INITIAL_PASSWORD" in loop_code,
         "修法：AiAgentLoop 里那条例外也必须是引用常量（CHG-0120）")

    # ── 5. 清单条目能追到出处 ──────────────────────────────────────────
    c.section("5. 清单条目能追到出处（docs/AI_DEFAULTS.md）")
    doc_src = read(DOC)
    c.ok("文档有实质内容（%d 字符，下限 %d）" % (len(doc_src), MIN_DOC_CHARS),
         len(doc_src) >= MIN_DOC_CHARS, "修法：docs/AI_DEFAULTS.md 是不是被清空了？")
    for label, _frag, doc_kw in ITEMS:
        c.ok("文档里有这一条：" + label, doc_kw in doc_src,
             "修法：把「" + label + "」这一条写回 docs/AI_DEFAULTS.md（CHG-0120）")
    paths = sorted(set(PATH_RE.findall(doc_src)))
    c.ok("文档点到的仓库路径 %d 条（下限 %d）" % (len(paths), MIN_DOC_PATHS),
         len(paths) >= MIN_DOC_PATHS, "修法：出处列要指向具体文件（backend/… 、android/… 、docs/…）")
    bad = [p for p in paths if not (ROOT / p).exists()]
    checklist.append("出处指向的文件都真实存在")
    c.ok("这些路径都真实存在（悬空 %d 条）" % len(bad), not bad,
         "修法：出处那条指向的文件不存在 —— 改成真实存在的文件，或删掉这条出处：" + "、".join(bad[:6]))
    index_src = read(INDEX)
    checklist.append("INDEX 里挂着 AI_DEFAULTS.md")
    c.ok("文档地图里有一行指向它（否则 check_reachability 会说它是孤儿文档）",
         re.search(r"\[[^\]]*AI_DEFAULTS\.md[^\]]*\]\(\.\./AI_DEFAULTS\.md\)", index_src) is not None,
         "修法：把指向 ../AI_DEFAULTS.md 的那一行加回 docs/PROJECT_MAP/INDEX.md（CHG-0120）")

    # ── 6. 单测与文书 ──────────────────────────────────────────────────
    c.section("6. 单测与文书")
    kt = read(KT_TEST)
    # ⚠️ 数的是**代码里**的 @Test（先剥注释）：把用例注释掉 `// @Test` 等于它不再跑，
    #    而"注释掉"正是最容易发生的那种悄悄失效（反向验证第 8 条打的就是这一枪）。
    n_tests = strip_comments(kt).count("@Test")
    checklist.append("单测 >= %d 例" % MIN_KT_TESTS)
    c.ok("单测 >= %d 例（实际 %d）" % (MIN_KT_TESTS, n_tests), n_tests >= MIN_KT_TESTS,
         "修法：单测少于 6 例 —— 把 AiAskLessTest 的用例补回到 6 个以上（CHG-0120）")
    c.ok("单测读的是提示词真正那一份（AiDefaults.RULES）", "AiDefaults.RULES" in kt,
         "修法：单测不许另抄一份文字，必须读 AiDefaults.RULES（CHG-0120）")
    c.ok("单测钉了清单与三条规则（初始密码/进货成本/专属价/一次问全/必须问）",
         all(w in kt for w in ("初始密码", "进货成本", "专属价", "一次问全", "必须问")),
         "修法：单测要覆盖默认值清单、三条规则与安全底线（CHG-0120）")
    chg = read(CHG)
    c.ok("变更单是九节（①~⑨ 齐全）", all(("## " + s) in chg for s in SECTIONS),
         "修法：docs/changes/CHG-0120.md 缺小节 —— 照 docs/changes/_TEMPLATE.md 补齐（CHG-0120）")
    c.ok("事项登记簿里有 CHG-0120 一行", "CHG-0120" in read(REGISTRY),
         "修法：在 docs/changes/README.md 的表里加一行 CHG-0120（否则 _check_dev_spec.py 会红）")
    c.ok("工作声明里有 CHG-0120", "CHG-0120" in read(CLAIM),
         "修法：在 docs/AI_WORK_CLAIM.md 的「进行中」里补一块 CHG-0120 声明")
    rev = read(REVERSE)
    c.ok("反向验证脚本写了 R4 边界说明", "R4-BOUNDARY-JUSTIFICATION:" in rev,
         "修法：反向验证脚本的 docstring 里要有 R4-BOUNDARY-JUSTIFICATION: 那一段")
    n_inj = len(re.findall(r"\n    \(\n", rev))
    checklist.append("反向验证 >= %d 条注入" % MIN_INJECTIONS)
    c.ok("反向验证 >= %d 条注入（实际 %d）" % (MIN_INJECTIONS, n_inj), n_inj >= MIN_INJECTIONS,
         "修法：反向验证至少要有 5 条注入，每条都要让本判据变红（CHG-0120）")
    return c, checklist


def main() -> int:
    if "--list" in sys.argv:
        print("CHG-0120「AI 少问」判据盯的东西：")
        for i, row in enumerate(LIST_ROWS, 1):
            print("  %2d. %s" % (i, row))
        return 0
    c, checklist = check()
    print("\n" + "=" * 60)
    if c.fails:
        print("❌ %d 项未通过（通过 %d 项）：" % (len(c.fails), c.n_ok))
        for label, _detail in c.fails:
            print("   - " + label)
        return 1
    print("✅ 全部 %d 项通过：默认值清单进了提示词、三条规则都在、安全底线没被顶掉、"
          "同一个数只有一处、条目能追到出处、单测与文书在位。" % c.n_ok)
    return 0


#: `--list` 用的人读清单（与 `check()` 一一对应）
LIST_ROWS = [
    "默认值清单六条都在提示词正文里（AiDefaults.RULES）",
    "systemPrompt 里真的拼了这段（append(AiDefaults.RULES)）",
    "能推断就别问 / 假设写在卡上 / 真要问就一次问全",
    "安全底线：钱 / 身份 / 撤不回来 ＋ 没有默认值 ⇒ 必须问（且原那条没被删）",
    "同一个数只有一处：密码引用 AccountRules.DEFAULT_INITIAL_PASSWORD，代码里没有字面量",
    "docs/AI_DEFAULTS.md 每条口径都在，出处指向的文件都真实存在，并从 INDEX 可达",
    "单测 >= 6 例、变更单九节、登记簿与工作声明都在、反向验证 >= 5 条注入",
]


if __name__ == "__main__":
    sys.exit(main())
