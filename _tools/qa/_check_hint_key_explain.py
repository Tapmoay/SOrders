# -*- coding: utf-8 -*-
"""关键解释句不许被「说明」开关藏掉（2026-10-04 CHG-0031）—— 机器判据。

## 这条是怎么来的

用户点名（goal 第 ⑤ 件，逐字）：
> 吃透「说明（Hint）」机制的取舍规则（**不重要的/繁琐的信息才隐藏或简化**），
> 把被误判为可隐藏的关键解释句找出来。

规矩写在 docs/HINT_STYLE.md：Hint 是「可以关掉的说明」，Text 是「永远显示的数据/状态/警告」。
病灶不在开关上，在**判断**上：有一批句子长得像解释（看起来像在教用户怎么用），删掉之后
用户会**做错决定** —— 算错账、以为数据被上传了、按下一个撤不回来的按钮、看不出这一页现在
是什么状态。它们被当成解释句，于是提示开关一关就跟着消失了。

## 四族（这就是「取舍规则」的可复算形式）

- **甲 钱的口径**：两个数为什么一样大 / 这个数算的是谁 / 这笔钱不走本系统；
- **乙 不可逆的后果**：按下去就发生、撤不回来的事（钱出去、账红冲、库存回补、对话被撤掉）；
- **丙 隐私与费用**：数据去哪了（本机 / 不上传 / 加密存在）、这一下花不花钱（额度 / 谁承担）；
- **丁 当前状态的含义**：这一页现在是什么状态、这把 key 是哪来的。

## 为什么必须有机器的判据

上一版只靠 _hint_inventory.OVERRIDE **逐句**记录「这一句必须常显」。逐句记录的病是
**只有被点过名的那一句受保护**：2026-10-03 的 E2E 走查 P25 把账本口径那句改成常显之后，
**紧挨着的同族句子**（ui/shipper/ShipperLedgerScreen.kt 的「两段互不影响」「只记在你自己
这一本账上」）照样挂在一个 Hint 上 —— 没有任何一条红线会红，因为分类器把它们当解释句。
四族是**词表**：新写的同类句子自动进保护范围（谁再把它挂到开关上，这条判据当场红）。

R4-BOUNDARY-JUSTIFICATION: **为什么代码边界解决不了这件事。**
（⛔ 标记里必须是**ASCII 冒号**：_check_r3_constraints.py::probe_checker_budget 认的是
R3-BOUNDARY-JUSTIFICATION: / R4-BOUNDARY-JUSTIFICATION: 这两个**逐字**字符串。）

把一个 Hint( 改成 Text( 是**一个词的改动** —— Kotlin 编译器、Compose 预览、
Android 单测全都不会响：界面看起来一模一样，只有**关掉提示开关的用户**会少看到一句
决定他怎么做的话。类型系统里没有任何东西能表达「这句话删掉用户会做错决定」。

**反向破坏用例**：_tools/qa/_reverse_verify_hint_key_explain.py 逐条把修复撤回
（清空一族词表、key_family 恒返回 None、删掉 classify 里那一支、把关键句改回 Hint(、
删掉 _check_hints.py 的 §2b、把下限改成 0、规范里删掉一族 / 删掉「拆句」那句、
删文档 / 删登记行 / 删认领块……），每条都要求本判据或 _check_hints.py 报红，
跑完把被碰过的文件**逐字节**还原。

**静默空转保护**：每一组都配下限（文案数 / 关键词条数 / 每族至少一条 / 二十条句子逐条点名），
锚点少一个就当场红 —— **不做**「找不到就跳过」的软处理。只读源码，不改任何文件。

用法：
    python _tools/qa/_check_hint_key_explain.py
    python _tools/qa/_check_hint_key_explain.py --list
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402
import _hint_inventory as inv  # noqa: E402   —— 词表**只有一份**，这里不另写

ROOT = Path(__file__).resolve().parents[2]
HINTS_CHECK = ROOT / "_tools/qa/_check_hints.py"
INVENTORY = ROOT / "_tools/qa/_hint_inventory.py"
REVERSE = ROOT / "_tools/qa/_reverse_verify_hint_key_explain.py"
STYLE_DOC = ROOT / "docs/HINT_STYLE.md"
DOC = ROOT / "docs/changes/CHG-0031.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 四族（与 _hint_inventory.KEY_FAMILIES 逐字一致；少一族就红）
FAMILIES = ("钱的口径", "不可逆的后果", "隐私与费用", "当前状态的含义")

#: 反空转下限
MIN_KT = 60           # 扫到的主源码 kotlin 文件
MIN_TEXTS = 300       # 抽到的界面文案
MIN_KEY = 15          # 认出来的关键解释句（实测 20）
MIN_PER_FAMILY = 1    # 每一族至少一条
MIN_WORDS = 4         # 每一族的词表至少几个词
MIN_INJECTIONS = 12   # 反验脚本至少几条注入

#: 四族的合成例句：key_family 必须认出来，classify 必须**不**判成 EXPLAIN。
#: （用合成句而不是现场句：现场句会随文案改写而变，合成句只依赖词表本身。）
SAMPLES: dict[str, str] = {
    "钱的口径": "这里只有你欠公司的这一边：你自己卖货收回来的钱不经过本系统。",
    "不可逆的后果": "钱真的出去了：账本「收支」里会写一行资金流水。",
    "隐私与费用": "API Key 加密存在本机、不上传。",
    "当前状态的含义": "正在使用「测试账号默认 Key」。",
}

#: 二十条句子 / 十九个锚点：这一句必须**常显**（Text），挂在 Hint 上就红。
#: (相对路径, 句子片段)；片段一律取**能唯一认出那一句**的最短子串。
SITES: list[tuple[str, str]] = [
    ("ui/ai/AiChatScreen.kt", "这条之后的对话会被撤掉"),
    ("ui/ai/AiChatScreen.kt", "Key 只存在本机"),
    ("ui/ai/AiSettingsScreen.kt", "API Key 加密存在本机、不上传"),
    ("ui/ai/AiSettingsScreen.kt", "正在使用「测试账号默认 Key」"),
    ("ui/ai/AiSettingsScreen.kt", "已保存一个 Key（加密存在本机）"),
    ("ui/ai/AiSettingsScreen.kt", "全程只存在这台手机上，不上传"),
    ("ui/ai/AiSettingsScreen.kt", "测试只发一句"),
    ("ui/dispatcher/DispatcherOrdersScreen.kt", "退回来的货会补回库存"),
    ("ui/dispatcher/DispatcherOrdersScreen.kt", "会自动记一笔退给客户的现金"),
    ("ui/dispatcher/DispatcherReturnRequestsScreen.kt", "库存和账本在这一刻才变"),
    # 2026-10-07 CHG-0075：司机那一档从账本页并进「司机账 · 运费结算」，这一句跟着搬家（同一句话，常显不变）。
    ("ui/dispatcher/FreightSettlementScreen.kt", "司机那笔钱的口径"),
    ("ui/dispatcher/SupplierDetailScreen.kt", "钱真的出去了"),
    ("ui/dispatcher/SuppliersScreen.kt", "每付一次都会写一行资金流水"),
    ("ui/dispatcher/UsersManageScreen.kt", "按车型的老口径兜底"),
    ("ui/shipper/ShipperLedgerScreen.kt", "不会重复收钱"),
    ("ui/shipper/ShipperLedgerScreen.kt", "两段互不影响"),
    ("ui/shipper/ShipperLedgerScreen.kt", "公司那边的账不会跟着变"),
    ("ui/shipper/ShipperLedgerScreen.kt", "只有你欠公司的这一边"),
    ("ui/shipper/ShipperLedgerScreen.kt", "只记在你自己这一本账上"),
]

#: 改动文档的九节（_check_dev_spec.py 对 docs/changes/*.md 提的是同一件事）。
REQUIRED_PARTS = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨"]


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def int_after(src: str, key: str) -> int:
    """取 key 后面紧跟的整数（取不到 = -1）。⛔ 不用正则：少一层转义就少一类假红。"""
    i = src.find(key)
    if i < 0:
        return -1
    j = i + len(key)
    digits = ""
    while j < len(src) and src[j].isdigit():
        digits += src[j]
        j += 1
    return int(digits) if digits else -1


def site_of(r: dict) -> str:
    """一行现场：路径:行号 挂在哪条调用上 句子。"""
    fam = inv.key_family(r["text"]) or "-"
    return r["file"] + ":" + str(r["line"]) + " [" + fam + "] " + r["call"] + " " + r["text"][:34]


class Checker:
    def __init__(self) -> None:
        self.fails = 0
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails += 1
            print("  [FAIL] " + label + ("  → " + detail if detail else ""))

    def report(self, title: str) -> int:
        print()
        print("===== " + title + " =====")
        print("  通过 " + str(self.passes) + " 项，失败 " + str(self.fails) + " 项")
        return 1 if self.fails else 0


def section(title: str) -> None:
    print()
    print("-- " + title + " --")


def main() -> int:
    if refuse_if_injecting("关键解释句不许被说明开关藏掉（CHG-0031）"):
        return 1

    if "--list" in sys.argv:
        print("二十条必须常显的关键解释句（四族）：")
        for rel, frag in SITES:
            print("  " + rel + "  ←  " + frag)
        print("四族：" + " / ".join(FAMILIES))
        return 0

    rows, n_files = inv.collect()
    inv_src = read(INVENTORY)
    hints_src = read(HINTS_CHECK)
    style = read(STYLE_DOC)
    doc = read(DOC)
    registry = read(REGISTRY)
    claim = read(CLAIM)
    reverse = read(REVERSE)

    c = Checker()
    print("关键解释句（四族）不许被说明开关藏掉（CHG-0031，2026-10-04）")

    section("零、现场：扫描是活的")
    c.ok("扫到 ≥" + str(MIN_KT) + " 个主源码 .kt（实测 " + str(n_files) + "）",
         n_files >= MIN_KT, "扫描根路径或抽取规则坏了？")
    c.ok("抽到 ≥" + str(MIN_TEXTS) + " 条界面文案（实测 " + str(len(rows)) + "）",
         len(rows) >= MIN_TEXTS, "抽取规则坏了的话，下面每一条都会空过")
    keys = [r for r in rows if inv.key_family(r["text"]) is not None]
    c.ok("认出 ≥" + str(MIN_KEY) + " 条关键解释句（实测 " + str(len(keys)) + "）",
         len(keys) >= MIN_KEY, "四族词表被改名/清空了？第 2b 组与第 3 组的唯一输入就是它")
    for fam in FAMILIES:
        n_fam = len([r for r in rows if inv.key_family(r["text"]) == fam])
        c.ok("「" + fam + "」这一族至少 " + str(MIN_PER_FAMILY) + " 条（实测 " + str(n_fam) + "）",
             n_fam >= MIN_PER_FAMILY, "这一族的词表是不是被清空了？")

    section("一、四族词表本身")
    for fam in FAMILIES:
        words = inv.KEY_FAMILIES.get(fam, ())
        c.ok("「" + fam + "」词表 ≥" + str(MIN_WORDS) + " 个词（实测 " + str(len(words)) + "）",
             len(words) >= MIN_WORDS, "词表是这条红线的全部依据，短到没有词就等于没有这一族")
    for fam, sample in SAMPLES.items():
        got = inv.key_family(sample)
        c.ok("key_family() 认得出「" + fam + "」的合成例句（判成 " + str(got) + "）", got == fam,
             "合成句都认不出来，现场句更认不出来")
    for fam, sample in SAMPLES.items():
        cat = inv.classify(sample, "")
        c.ok("classify() 不把「" + fam + "」的合成例句判成 EXPLAIN（判成 " + str(cat) + "）",
             cat in ("DATA", "WARN"), "词表进了 KEY_FAMILIES，但没接进 classify 的判定链")
    c.ok("classify() 里有 key_family(t) 那一支（源码级）",
         "elif key_family(t) is not None:" in inv_src,
         "那一支被删掉的话，四族的句子会一路走到 EXPLAIN（又变成可隐藏）")
    c.ok("乙、丁两族是并进原表的（不是另开一条路）",
         "CONSEQUENCE_WORDS = CONSEQUENCE_WORDS + CONSEQUENCE_EXTRA_WORDS" in inv_src
         and "STATE_WORDS = STATE_WORDS + STATE_EXTRA_WORDS" in inv_src,
         "并进去之后，原有的 20/40 字与标记词规则也一起管它们")

    section("二、判据侧（_check_hints.py 的 2b 组）")
    c.ok("_check_hints.py 里有 2b 那一组",
         "2b. 关键解释句（四族）不许走 Hint" in hints_src,
         "这一组是「关掉开关会不会连关键句一起关掉」的唯一机器判据")
    c.ok("那一组点名了「被挂到开关上的关键解释句 = …」（必须为 0）",
         "被挂到开关上的关键解释句 = " in hints_src)
    floor = int_after(hints_src, "MIN_KEY_SENTENCES = ")
    c.ok("下限 MIN_KEY_SENTENCES = " + str(floor) + "（必须 ≥10）", floor >= 10,
         "下限改成 0 等于把这一组关掉（词表被清空也全绿）")
    c.ok("那一组用的是同一份词表（inv.key_family）",
         "rows if inv.key_family(" in hints_src,
         "锚住的是「从词表算输入」那一行；只看 inv.key_family( 会被修法提示串骗过去")
    c.ok("修法里交代了拆句（同一调用里还有教法句时不许整条改）", "拆句" in hints_src,
         "整条改 Text 会让第 1 组（裸露的解释句）报红 —— 先把两句拆开")

    section("三、现场：二十条句子一条都不许挂在开关上")
    hidden = [r for r in keys if r["call"] == "Hint"]
    c.ok("被挂到开关上的关键解释句 = " + str(len(hidden)) + "（必须为 0）", not hidden,
         "；".join(site_of(r) for r in sorted(hidden, key=lambda x: (x["file"], x["line"]))[:8]))
    for rel, frag in SITES:
        hits = [r for r in rows if rel in r["file"] and frag in r["text"]]
        if not hits:
            c.ok("落点在（" + rel + "：" + frag + "）", False,
                 "源码里找不到这一句了 —— 是句子被改写（那就更新本判据的锚点），还是被删了？")
            continue
        bad = [r for r in hits if r["call"] != "Text"]
        c.ok("常显（" + rel + "：" + frag + "）", not bad,
             "；".join(site_of(r) for r in bad))

    section("四、规范：四族写进了书写规范")
    for fam in FAMILIES:
        c.ok("docs/HINT_STYLE.md 里写了「" + fam + "」", fam in style,
             "下一个写页面的人只读规范 —— 规范不写，他还会把这类句子挂成 Hint")
    c.ok("规范里交代了拆句的做法（教法句留 Hint、关键句单独 Text）", "拆句" in style,
         "不交代的话，第二个人的做法会是「整条改成 Text」，然后撞上第 1 组")
    c.ok("规范仍然写着三类身份（解释 / 数据 / 警告）",
         all(w in style for w in ("解释", "数据", "警告")))
    c.ok("规范仍然写着长度尺子（20 / 40 字）", "20" in style and "40" in style)

    section("五、文档与登记（三件）")
    c.ok("docs/changes/CHG-0031.md 存在", bool(doc),
         "改动文档是这次交付的一半：没有它，判据与反验也没有出处")
    c.ok("九节齐全（① … ⑨）", all(x in doc for x in REQUIRED_PARTS),
         "缺哪一节 _check_dev_spec.py 也会红")
    c.ok("登记表 docs/changes/README.md 里有 CHG-0031 那一行", "CHG-0031" in registry)
    c.ok("认领簿 docs/AI_WORK_CLAIM.md 里有 CHG-0031 的块", "CHG-0031" in claim)

    section("六、反向验证脚本在，且条数够")
    n_inj = reverse.count(chr(34) + "HINTS:") + reverse.count(chr(34) + "JUDGE:")
    c.ok("注入 ≥" + str(MIN_INJECTIONS) + " 条（实测 " + str(n_inj) + "）", n_inj >= MIN_INJECTIONS,
         "反验脚本被删/被削短？永远绿的检查等于没有检查")
    c.ok("反验脚本拿着注入锁（lock_reverse_verify）", "lock_reverse_verify" in reverse)

    return c.report("CHG-0031：关键解释句（四族）不许被说明开关藏掉")


if __name__ == "__main__":
    sys.exit(main())
