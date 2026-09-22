"""界面「提示/说明」全库盘点 —— **清单自己算，不许手写**。

## 为什么要它（用户 2026-09-21 那条新规矩）
三个端（货主/派单员/司机）里所有**解释性**的界面文字，都要走**一个统一接口**、
受「我的 → 提示」那**一个总开关**控制；而**数据/状态/警告**永远显示。
要改多少处、每处在哪、有多长 —— 这个清单**不能手写**。
本项目已经栽过 5 次"清单手写 → 新写的文件漏在清单外"（见 `docs/AI_WORK_CLAIM.md`
第二十轮那条：确认卡检查只扫 3 个手写文件，v3.17 后新增的 4 个处理器全漏）。
所以它从源码里**算**出来：扫所有 `Text(...)` / `HintOnce(...)` 的字符串字面量，逐条打标。

## 三级分类（启发式，用途是"给人一张要逐条过的清单"）
- `WARN`    警告/错误类：含 失败|错误|不能|请勿|必须|注意|超时|异常|⚠ 之类的词 → **永不隐藏**
- `DATA`    数据/状态类：带数字/金额/单位/单号，或纯短标签（≤ [LABEL_MAX] 字且无标点）→ **永不隐藏**
- `EXPLAIN` 解释类：其余够长、像句子的话 → **归总开关**（这一类是要迁移的主体）

⚠️ 分类是**启发式**，它的产物是一张**给人逐条过目**的清单，不是"自动改代码"的依据；
最终归类由人（和用户）拍板，拍板结果落在 `docs/PROJECT_MAP/09A_HINT_CATALOG.md`。

## 反向约束（防"清单空转"）
扫到的文件数 / 字面量数 / 解释句数各自有下限，任何一项过低 → **非零退出**：
判据可以过时，但不能安静地什么都不查。

用法：
    python _tools/qa/_hint_inventory.py            # 汇总 + 最长的解释句
    python _tools/qa/_hint_inventory.py --all      # 列出全部候选
    python _tools/qa/_hint_inventory.py --md       # 生成 docs/PROJECT_MAP/09A_HINT_CATALOG.md
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
CATALOG = ROOT / "docs" / "PROJECT_MAP" / "09A_HINT_CATALOG.md"

# ── 判据参数（都在这里，改口径改这一处）────────────────────────────────────
LABEL_MAX = 8          # ≤ 这个字数、无标点 = 标签（订单号 / 合计 / 撤销）
PAREN_LABEL_MAX = 18   # ≤ 这个字数且带括号补充 = **字段标签**（`起点（可选，从这出发）`）
EXPLAIN_MIN = 16       # ≥ 这个字数才可能是解释句（比它短的一律留着，安全方向）
EXPLAIN_SHORT_MIN = 12 # 带"解释性标记词"时的下限（见 classify 里的注释：精简之后还要认得出来）
LONG = 40              # 超过这个字数就要精简（规范 §3 的两行上限）——目录里标 ⚠️
SCAN_WINDOW = 900      # 从一个 `Text(` 往后最多扫这么多字符去找它的字面量

WARN_WORDS = (
    "失败", "错误", "不能", "不可", "请勿", "必须", "注意", "超时", "异常",
    "无权", "已过期", "⚠", "重试", "危险", "警告", "没拉到", "拉不到",
)
# **破坏性操作的后果**：这些话是用户按下按钮**之前**唯一的防线，⛔ 永远不许被开关藏掉。
# （"改名会连带改掉…""停用后就…""不可恢复"都属于这一类。）
CONSEQUENCE_WORDS = (
    "会连带", "一起改过去", "会一起", "覆盖", "不可恢复", "不能恢复", "找不回",
    "会删", "会被删", "将留痕", "会变成", "会掉回", "会写进", "会扣", "会清零",
    "无法撤销", "撤销不了",
)
# **表单元信息**：必填/选填/只读这些是"怎么填"的说明，但它们是**字段的一部分**，
# 藏掉之后用户不知道这一栏能不能空着 —— 所以归数据。
META_WORDS = ("必填", "选填", "只读", "可选", "（可多选）")
# **状态回执**：这一页在回答"现在是什么状态"（"已确认：锁屏也收得到""系统未限制后台运行"）。
# 它不是解释，而是**用户来这一页就是要看的东西** —— 关掉提示不该把它关掉。
# （2026-09-21 真抓到一次误迁移：`AlertSettingsScreen` 的「已确认：…」被改成了 `Hint`。）
STATE_WORDS = ("已确认", "已开启", "已关闭", "已完成", "系统未限制", "当前状态", "还没允许")
# 空态文案：列表/页面为空时**唯一**显示的那句话。它读起来像解释（"点右上角建一个"），
# 但它同时是"这里不是坏了、只是没有"的唯一证据 —— 藏掉它就是一片空白。
# 所以单独一类，**永不隐藏**（用户拍板的那条是"解释句归开关"，不是"连空态也藏"）。
EMPTY_WORDS = (
    "还没有", "暂无", "没有匹配", "没有更多", "还没有任何", "一个都没", "空空",
    "没有找到", "还没有收到",
)

# `${x}` 与 **`$x`（不带花括号）都算插值** —— 后者最容易漏：
# `已选 $kinds 种` / `他现在的规则：$ruleName` / `给「$driverName」配车` 渲染的都是**活值**，
# 它们长得像句子，被当成解释藏起来就等于"用户看不见自己刚选了什么、这是谁的规则"。
INTERP_RE = re.compile(r"\$\{|\$[A-Za-z_]")
PAREN_RE = re.compile(r"[（(][^）)]{1,14}[）)]")
# **半句话**：量词开头（`个已停用…`、`位司机还没配车…`）或连接词开头（`所以…`、`也才能…`）。
# 它们是上一句/上一个字面量的**尾巴**，而那句的头（常常是一个 `$n` 数字）在**另一次调用**里
# —— 分段看时这一段自己什么特征都没有，会被当解释句藏掉，屏幕上只剩个孤零零的数字。
FRAGMENT_RE = re.compile(r"^\s*([个位辆条件种名笔张台]|所以|因此|也|并|而且|但|而|或|即|然后|再|就|（|\()")
EXPLAIN_MARKERS = (
    "会", "可以", "之后", "如果", "因为", "所以", "自动", "不会", "才能", "表示",
    "说明", "用于", "用来", "指的是", "就", "才", "并且", "但是", "仍", "只",
)
PUNCT = "，。！？；：、··—…（）()「」“”\"'"
DIGIT_UNIT = re.compile(r"[0-9０-９¥￥%]|元|件|单|斤|kg|吨|次|天|月|年|小时|分钟")

# 端（按目录算，不手写文件清单）
END_BY_DIR = (
    ("ui/shipper", "货主"),
    ("ui/dispatcher", "派单员"),
    ("ui/driver", "司机"),
    ("ui/common", "共用"),
    ("ui/order", "共用"),
    ("ui/profile", "共用"),
    ("ui/home", "共用"),
    ("ui/ai", "共用"),
    ("ui/messages", "共用"),
    ("ui/login", "共用"),
    ("ui/nav", "共用"),
    ("ui/theme", "共用"),
)

CALL_RE = re.compile(
    # ⚠️ `Hint`（统一入口）也要在里面：迁移过的地方是 `Hint(...)`，
    #    不认它就等于"改完之后盘点里看不见它们"，覆盖率会永远显示 0。
    #    顺序上较长的写法放前面（`HintOnce` 先于 `Hint`），否则 `Hint` 会先匹配、再回溯失败。
    r"(?<![A-Za-z0-9_])(Text|HintOnce|HintText|HintLine|Hint|Status\w*|Warn\w*)\s*\("
)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def literals_in_call(src: str, open_paren: int) -> tuple[list[tuple[str, int]], int]:
    """从一个 `(` 之后扫到配对的 `)`，收集这一层里出现的字符串字面量。

    返回 `(字面量列表, 配对右括号之后的下标)` —— 后者给 `--aggressive` 用：
    要知道这次调用里有没有 `AnnotatedString`（那种调用改成 `Hint` 会编译不过）。

    只做**文本级**扫描（不建 Kotlin AST）：够用，而且不怕 Kotlin 语法演进。
    """
    i = open_paren + 1
    depth = 1
    out: list[tuple[str, int]] = []
    limit = min(len(src), open_paren + SCAN_WINDOW)
    while i < limit and depth > 0:
        c = src[i]
        if c == "/" and src.startswith("//", i):          # 行注释
            j = src.find("\n", i)
            i = len(src) if j < 0 else j + 1
            continue
        if c == "/" and src.startswith("/*", i):          # 块注释
            j = src.find("*/", i)
            i = len(src) if j < 0 else j + 2
            continue
        if c == '"':
            if src.startswith('"""', i):                  # 原始字符串
                j = src.find('"""', i + 3)
                if j < 0:
                    break
                out.append((src[i + 3:j], i))
                i = j + 3
                continue
            j = i + 1
            buf: list[str] = []
            while j < len(src) and src[j] not in ('"', "\n"):
                if src[j] == "\\":
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                buf.append(src[j])
                j += 1
            out.append(("".join(buf), i))
            i = j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return out, i


def looks_empty_state(src: str, off: int, text: str) -> bool:
    """这句是不是"列表为空时唯一显示的那句话"（见 [EMPTY_WORDS] 的注释）。"""
    if any(w in text for w in EMPTY_WORDS):
        return True
    window = src[max(0, off - 600):off]
    last = window.rfind("isEmpty()")
    if last < 0:
        return False
    # 有 else 分支就说明"空"只是一种情况，不一定是整页的唯一反馈
    return "} else" not in window[last:]


# ── 逐条复核表（**这条是给人看的，每条都要写理由**）────────────────────────
# 启发式分类器只能给"候选"，判错了的在这里按 `(文件名, 文案里的一个子串)` 改判。
# ⚠️ 匹配用**子串**（不是"前 N 字"）：第一版按 `t[:12]` 取键，而表里有几条键写到 13~14 字，
#    于是它们**静默匹配不上**，两个洞（匹配口径 + 防化石用 startswith）一起把错配藏住了。
# ⛔ 只许往"更不藏"的方向改（EXPLAIN → WARN/DATA），不许拿它把数据偷偷变成提示。
# 反向约束：表里每一条都必须**至少命中一次**，命中 0 次 → 非零退出（防化石：文案改了、
# 文件删了之后，这张表会变成一段谁也不敢删的谎话）。
OVERRIDE: dict[tuple[str, str], tuple[str, str]] = {
    ("AlertSettingsScreen.kt", "手机还没允许 SOrde"): (
        "WARN", "通知权限还没给：这是**当前状态 + 怎么修**，不是解释"),
    ("AlertSettingsScreen.kt", "手机可能在后台把 SOr"): (
        "WARN", "这是一条警告（系统可能掐掉后台），藏了等于把风险藏了"),
    ("AlertSettingsScreen.kt", "已确认：锁屏 / 关掉 A"): (
        "DATA", "这是**设置结果的状态回执**（用户来这一页就是为了看它），不是解释"),
    ("OrderDetailScreen.kt", "没有导航信息 · 司机到场后"): (
        "DATA", "这是**缺数据的现状**（有没有导航信息本身是状态），藏了会让人以为有"),
    ("ReportCenter.kt", "毛利 —（这一行没有成本快照"): (
        "WARN", "「这个数为什么是空的」必须一直看得见，否则用户只会觉得报表坏了"),
    ("UsersManageScreen.kt", "没挂规则 → 按车型的老口径"): (
        "WARN", "钱的兜底口径：这一段是「这单可能一分钱都算不出来」的前提，不能藏"),
    ("UsersManageScreen.kt", "否则他这一趟可能一分钱"): (
        "WARN", "同上：**钱算不出来的后果**"),
    ("OrderDetailScreen.kt", "送达照片 · 自动加水印"): (
        "DATA", "这是**版块标签**（照片区的小标题），只是碰巧带了「自动」这个解释性标记词；"
                "它不是解释句，⛔ 不该被开关藏掉"),
    # ↓ 这两句是「我的 → 消息提醒」那一格的副标题（按角色选一句）。它们是在**说明这一格管什么**，
    #   属解释句 —— 用户 2026-09-21 正是把这一行红框圈出来、要求归总开关管的。
    #   它们被保守地判成 DATA，是因为「新**单**」里的"单"命中了单位词表（见下面的已知偏差）。
    ("ProfileScreen.kt", "语音播报 / 后台接收新单"): (
        "EXPLAIN", "这一格的**说明**（静态、按角色选一句），不是状态数字；"
                   "判成 DATA 是「新单」命中单位词的保守侧误判"),
    ("ProfileScreen.kt", "通知栏提醒 / 后台接收新单"): (
        "EXPLAIN", "同上（货主那一句）"),
    # ↓ 下面两条是 2026-09-21 商品管理改版第 1 期新增的 `Hint(...)` 调用，都是**解释句**
    #   （"关掉这个开关会怎样""成本价怎么算、去哪查"），被判成 DATA/WARN 是已知偏差在作怪：
    #   ① 「下**单**」里的"单"命中单位词表；② 「留空按 **0** 计」里的数字命中 `[0-9]`。
    #   ⚠️ 方向是 DATA → EXPLAIN（**更藏**），与表头那句"只许往更不藏改"相反 ——
    #   例外只给"确实是解释句、只是被单位词/数字误伤"这一种，理由必须写清楚。
    ("ProductFormScreen.kt", "关闭开关则保存后货主下单时看不到它"): (
        "EXPLAIN", "解释句：说明这个开关**会影响别人**（货主看不到）；"
                   "判成 DATA/WARN 是「下**单**」里的「单」命中单位词表"),
    ("ProductFormScreen.kt", "留空按 0 计"): (
        "EXPLAIN", "解释句：说明成本价留空会怎么算、以及去哪查它的历史；"
                   "判成 DATA 是里面的数字 `0` 命中 `[0-9]`"),
    # ⚠️ 同批还有两句**没有**进这张表，因为它们被正确地判成了 `EMPTY`（空态句、永不被开关藏掉）：
    #   `UnitPickerSheet.kt` 与 `CategoryPickerSheet.kt` 里"搜不到"那一段 ——
    #   第一版把它们写成了 `Hint(...)`，是 `_check_hints.py` 抓出来的：
    #   空态句藏掉之后那一屏**一片空白**，"搜不到"和"根本没有"就分不出来了。改回 `Text(` 了。
    # ↓ 2026-09-22：「我的 → 基础设置 → 重置计数」那一格的副标题。它读起来像解释句
    #   （25 个字、带"记录/顺序"这类词），但它是**后果**：清掉之后回不来。
    #   按 `docs/HINT_STYLE.md` §2 属**警告类 → 永不隐藏** —— 把它藏进「提示」开关里，
    #   用户就可能在**不知情的情况下**点下去，而这件事没有撤销。
    ("BasicSettingsScreen.kt", "清掉「用得越多越靠前」的记录"): (
        "WARN", "这是**后果说明**（清掉会怎样 + 不可还原），属警告类；藏了用户可能不知情地点下去"),
}

# ⚠️ **已知的系统性偏差（先记下来，别顺手改）**：`DIGIT_UNIT` 里的单位词
#   （单 / 件 / 元 / 天 / 月 / 年 / 次 …）是**按子串**匹配的，于是
#   「账**单**」「派**单**」「清**单**」「今**天**」「**月**结」「次**数**」这些词也会命中，
#   把一批本该算解释句的文案保守地判成 DATA。
#   往"更不藏"的方向偏 = 界面更啰嗦但**不会藏错东西**，所以先不动它：
#   真要把判据收紧成"单位词必须紧跟数字"（`\d\s*单`），会**冒出一批新的裸露解释句**，
#   那要连带做一轮迁移 —— 属于下一轮的事，不要在没有迁移预算时单独改这一行。
DIGIT_UNIT_KNOWN_BIAS = True


def classify(text: str, file_name: str = "") -> str:
    """一句话归哪一类。**顺序就是判据**（先判"绝不能藏"的，最后才轮到 EXPLAIN）。

    每一次"宁可留在 DATA/WARN 一边"都是在防同一个后果：**用户看不见自己的状态**。
    所以这里的默认是"不藏"，只有一条明确的解释句才进 EXPLAIN。
    复核表 [OVERRIDE] 在最后盖一层（只许往"更不藏"改）。
    """
    t = text.strip()
    if not CJK_RE.search(t):
        return "SKIP"                     # 键名/路由/纯 ASCII，不是给人看的文案
    # 复核表**先判**：它是人逐条看过的结论，只许往"更不藏"的方向改。
    # ⚠️ 用**子串**匹配，不要用"前 N 字"：2026-09-21 第一版按 `t[:12]` 取键，
    #    而表里有几条键写到 13~14 字 → 静默匹配不上，而"防化石"检查用的是 `startswith`
    #    （长键仍然 startswith 成立）→ **两个洞一起把错配藏住了**。
    for (fname, frag), (newcat, _why) in OVERRIDE.items():
        if fname == file_name and frag in t:
            return newcat
    if FRAGMENT_RE.match(t) and len(t) <= 40:
        # 半句话：量词/连接词开头（见 FRAGMENT_RE 的注释）。宁可留着 ——
        # 藏掉半句的后果比留下它糟得多（屏幕上会出现"只有数字没有名词"的怪句）。
        return "DATA"
    if any(w in t for w in WARN_WORDS):
        cat = "WARN"
    elif INTERP_RE.search(t):
        return "DATA"                     # 渲染活值/活名字（`$x` 与 `${x}` 都算）
    elif DIGIT_UNIT.search(t):
        return "DATA"
    elif len(t) <= LABEL_MAX and not any(p in t for p in PUNCT):
        return "DATA"                     # 短标签：订单号 / 合计 / 撤销 …
    elif PAREN_RE.search(t) and len(t) <= PAREN_LABEL_MAX:
        return "DATA"                     # 字段标签的括号补充：`起点（可选，从这出发）`
    elif any(w in t for w in META_WORDS):
        return "DATA"                     # 必填/选填/只读：字段的一部分，藏了就没法填
    elif any(w in t for w in STATE_WORDS):
        return "DATA"                     # 状态回执（见 STATE_WORDS 的注释）
    elif any(w in t for w in CONSEQUENCE_WORDS):
        cat = "WARN"                      # 破坏性后果：按下按钮前的唯一防线
    elif len(t) >= EXPLAIN_MIN or (len(t) >= EXPLAIN_SHORT_MIN
                                   and any(m in t for m in EXPLAIN_MARKERS)):
        # ⚠️ 长度**不是唯一判据**：用户要求"过于冗长的说明要精简"，而一句解释被压到 14 字
        #    仍然是解释（`会自动并成一个` 这类带着标记词）。只按长度判，精简之后它会被
        #    改判成"数据"，于是 `_check_hints.py` 第 2 组会**误报**成"这次 Hint 调用里
        #    没有解释句" —— 所以"标记词"这条路必须一起留着。
        cat = "EXPLAIN"
    else:
        return "DATA"
    return cat


def end_of(path: Path) -> str:
    p = path.as_posix()
    for frag, name in END_BY_DIR:
        if f"/{frag}/" in p:
            return name
    return "其他"


def collect() -> tuple[list[dict], int]:
    files = sorted(SRC.rglob("*.kt"))
    rows: list[dict] = []
    for f in files:
        # ⚠️ **必须 `newline=""`（保留 CRLF）**：`Path.read_text()` 走通用换行，会把 `\r\n`
        #    翻成 `\n` —— 于是这个文件里所有字符偏移**都比真实文件小**（每个 CRLF 少 1）。
        #    偏移错了，`_migrate_hints.py` 按偏移去改名就会改到**别的地方**。
        #    2026-09-21 实测踩到：19 个文件里 5 个（恰好是 CRLF 那几个）全部落到
        #    "这里已经不是 Text" 被跳过 —— 靠那道校验才没改错，但那是运气，不是设计。
        with open(f, "r", encoding="utf-8", errors="replace", newline="") as fh:
            src = fh.read()
        lines = src.splitlines()
        for m in CALL_RE.finditer(src):
            open_paren = m.end() - 1
            lits, call_end = literals_in_call(src, open_paren)
            # `AnnotatedString` 那一支不能改名（`Hint` 只收 String）—— 记下来给迁移工具用
            has_annotated = "AnnotatedString" in src[open_paren:call_end]
            # ⚠️ **同一次调用里只要有一段带插值，整句都算数据**。
            #    一句话常被拆成几段字面量拼起来（`"$n" + " 位司机还没配车 —— …"`），
            #    逐段看时那一段自己没有 `$`，会被判成"解释句"——于是总开关一关，
            #    屏幕上就只剩一个**孤零零的数字**（"3"），比不显示还糟。
            call_has_interp = any(INTERP_RE.search(t) for t, _ in lits)
            # ⚠️ **首参之前出现 `+` ⇒ 整句是拿运行时值拼出来的**，例如
            #    `Text(t.orders.toString() + " 单里已结清 " + t.clearedOrders + " 单 …")`。
            #    这种句子里 `$` 一个都没有（值是 `+` 拼进来的），只看插值会把它当成"解释句"
            #    —— 关掉开关屏幕上就只剩半句话 + 数字。2026-09-21 在货主账本页真抓到一处。
            head0 = src[open_paren + 1: lits[0][1]] if lits else ""
            call_has_runtime = "+" in head0
            for text, off in lits:
                # 「这个字面量就是这个调用的**第一个参数**吗」——迁移工具只敢改名这一种
                # （`Text(buildAnnotatedString { append("…") })` 那种首参不是字符串，改了就编译不过）
                first_arg = bool(re.fullmatch(r"\s*(text\s*=\s*)?", src[open_paren + 1:off]))
                cat = classify(text, f.name)
                if cat == "SKIP":
                    continue
                if cat == "EXPLAIN" and (call_has_interp or call_has_runtime):
                    cat = "DATA"
                if cat == "EXPLAIN" and looks_empty_state(src, m.start(), text):
                    cat = "EMPTY"
                line_no = src.count("\n", 0, off) + 1
                rows.append({
                    "file": f.relative_to(ROOT).as_posix(),
                    "line": line_no,
                    "end": end_of(f),
                    "call": m.group(1),
                    "call_off": m.start(),
                    "text": text,
                    "cat": cat,
                    "len": len(text.strip()),
                    "first_arg": first_arg,
                    "has_annotated": has_annotated,
                    "src_line": lines[line_no - 1].strip() if line_no <= len(lines) else "",
                })
    # 同一行同一句只留一条（`Text(` 可能被同时算进外层 lambda）
    seen = set()
    uniq: list[dict] = []
    for r in rows:
        k = (r["file"], r["line"], r["text"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq, len(files)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="列出全部候选（默认只列最长的解释句）")
    ap.add_argument("--md", action="store_true", help="生成目录文档")
    ap.add_argument("--check", action="store_true",
                    help="只校验目录文档是不是过期（`_check_all.py` 会自动收集这一支）")
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args()

    rows, n_files = collect()

    if a.check:
        # 生成物新鲜度：文档的**唯一作者**就是本脚本，所以这里逐字比对即可。
        # ⚠️ 反空转：文档不存在 → 直接红（而不是"没有可比的"就绿）。
        if not CATALOG.exists():
            print(f"❌ 找不到 {CATALOG.relative_to(ROOT).as_posix()} —— 目录整个不见了。")
            print("   修法：python _tools/qa/_hint_inventory.py --md")
            return 1
        want = render_md(rows, n_files)
        have = CATALOG.read_text(encoding="utf-8")
        if want == have:
            print(f"✅ {CATALOG.relative_to(ROOT).as_posix()} 与源码一致（{len(rows)} 条文案，不是过期目录）")
            return 0
        wl, hl = want.splitlines(), have.splitlines()
        diff = [f"      第 {i + 1} 行：应有 {w[:60]!r} / 实际 {h[:60]!r}"
                for i, (w, h) in enumerate(zip(wl, hl)) if w != h][:5]
        print(f"❌ {CATALOG.relative_to(ROOT).as_posix()} **已经过期**"
              f"（应有 {len(wl)} 行 / 实际 {len(hl)} 行）")
        for d in diff:
            print(d)
        print("   修法：python _tools/qa/_hint_inventory.py --md")
        return 1

    by_cat = Counter(r["cat"] for r in rows)
    explain = [r for r in rows if r["cat"] == "EXPLAIN"]
    routed = sum(1 for r in rows if r["call"] != "Text")

    print(f"扫了 {n_files} 个 .kt 文件，抽到 {len(rows)} 条界面文案")
    print(f"  解释类 EXPLAIN = {by_cat['EXPLAIN']}（要迁移的主体）")
    print(f"  空态类 EMPTY   = {by_cat['EMPTY']}（永不隐藏：藏掉页面就一片空白）")
    print(f"  数据/标签 DATA = {by_cat['DATA']}（永不隐藏）")
    print(f"  警告类 WARN    = {by_cat['WARN']}（永不隐藏）")
    print(f"  已走统一入口（非裸 Text）的 = {routed}")
    print()
    per_end = Counter(r["end"] for r in explain)
    print("解释类按端分布：" + "  ".join(f"{k}={v}" for k, v in per_end.most_common()))

    # ── 反向约束：清单被改坏时必须先喊，不许安静地全绿 ──
    problems = []
    # 复核表防化石：每一条都必须**至少命中一次**（文案改了/文件删了，这条就成了谎话）。
    # ⚠️ 判据与 `classify` 里**必须同构**（都用子串）—— 第一版这里用 `startswith`、
    #    那边用 `t[:12]`，两个口径不一致，于是"键写长了"这种错配两边都不报。
    for (fname, frag), (_cat, why) in OVERRIDE.items():
        if not any(r["file"].endswith("/" + fname) and frag in r["text"] for r in rows):
            problems.append(
                f"复核表这条已经命中不到了：{fname}「{frag}」（理由：{why}）"
                " —— 文案或文件名变了，请重核后删掉这条")
    if n_files < 60:
        problems.append(f"扫到的文件数 {n_files} 太少（下限 60）—— 源码根路径是不是写错了？")
    if len(rows) < 300:
        problems.append(f"抽到的文案 {len(rows)} 太少（下限 300）—— 扫描规则是不是失效了？")
    if len(explain) < 30:
        problems.append(f"解释类只有 {len(explain)} 条（下限 30）—— 分类规则是不是被改坏了？")

    print()
    show = rows if a.all else sorted(explain, key=lambda r: -r["len"])[: a.top]
    for r in show:
        print(f"  [{r['cat']:<7}] {r['len']:>3}字  {r['file'].split('/')[-1]}:{r['line']}  {r['text'][:60]}")

    if a.md:
        write_md(rows, n_files)
        print(f"\n已写出 {CATALOG.relative_to(ROOT).as_posix()}")

    if problems:
        print("\n❌ 判据空转：")
        for p in problems:
            print("   -", p)
        return 1
    print("\n✅ 盘点完成（分类是启发式，逐条归类由人拍板）")
    return 0


def render_md(rows: list[dict], n_files: int) -> str:
    by_cat = Counter(r["cat"] for r in rows)
    explain = sorted((r for r in rows if r["cat"] == "EXPLAIN"), key=lambda r: (-r["len"], r["file"]))
    out: list[str] = []
    out.append("# 界面提示与说明目录（**机器生成，不要手改**）")
    out.append("")
    out.append("> 生成命令：`python _tools/qa/_hint_inventory.py --md`")
    out.append("> 这份文件是**产物**：改了源码就重跑，别在它上面手写（手写的内容下一次生成就没了）。")
    out.append("")
    out.append("## 1. 口径")
    out.append("")
    out.append("| 类别 | 含义 | 归总开关管吗 |")
    out.append("|---|---|---|")
    out.append("| `EXPLAIN` | 解释句（「按下去会怎样」「为什么这样」） | ✅ 关掉就不显示 |")
    out.append("| `DATA` | 数据/状态/标签（金额、数量、单号、档位摘要） | ⛔ 永远显示 |")
    out.append("| `WARN` | 警告/错误/安全 | ⛔ 永远显示 |")
    out.append("")
    out.append(f"扫了 **{n_files}** 个 `.kt` 文件，抽到 **{len(rows)}** 条文案："
               f"解释 **{by_cat['EXPLAIN']}** / 数据 **{by_cat['DATA']}** / 警告 **{by_cat['WARN']}**。")
    out.append("")
    out.append("## 2. 解释类逐条清单（**归总开关管的那一批**）")
    out.append("")
    out.append("> ⚠️ 这份文档是**生成物**：手写内容下一次生成就没了 —— 所以这里**没有**"
               "「精简后 / 归类」那种留给人填的列。精简结论写进 `docs/HINT_STYLE.md`，"
               "要留理由的例外写进 `_hint_inventory.py` 的 `OVERRIDE` 表。")
    out.append("")
    out.append("| # | 端 | 字数 | 位置 | 文案 |")
    out.append("|---|---|---|---|---|")
    for i, r in enumerate(explain, 1):
        loc = f"`{r['file'].split('/')[-1]}:{r['line']}`"
        txt = r["text"].replace("|", "\\|")
        flag = " ⚠️" if r["len"] > LONG else ""
        out.append(f"| {i} | {r['end']} | {r['len']}{flag} | {loc} | {txt} |")
    out.append("")
    n_long = sum(1 for r in explain if r["len"] > LONG)
    out.append(f"> 「⚠️」= 超过 [{LONG}] 字（规范 `docs/HINT_STYLE.md` §3 的上限），共 **{n_long}** 条 ——"
               "这些是要精简的：压到一行 ≤20 字，或两行 ≤40 字（**前提与后果都要留住**）。")
    return "\n".join(out) + "\n"


def write_md(rows: list[dict], n_files: int) -> None:
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(render_md(rows, n_files), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
