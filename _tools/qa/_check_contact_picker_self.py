#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CHG-0117 · 「选择联系人」弹层里那一行「我自己」（派单员本人也能当收货联系人）App 端红线。

R4-BOUNDARY-JUSTIFICATION:
  本判据管的是**边界**，不是"有没有写"。「我自己」这一行是**凭空造出来的**联系人 ——
  后端根本没有这条记录，所以它做错的每一种样子都不会报错、界面上也都看不出来：
    ① 它必须**只有一处**构造与取数（ui/common/SelfContact.kt）：三个调用方各拼一遍
       ContactDto，改天补一个字段就会三处不一样，而界面上每一处看起来都是"姓名 + 电话"；
    ② **拿不到姓名或电话就不许出现这一行**：少了这一行只是少一个便利，而出现一行
       空姓名/空电话的收货人，是司机照着拨号才发现号码是空的（"填一个打不通的号比空着更糟"）；
    ③ 它必须**固定排在最前、且不去重**：排后面等于藏在名册尾巴里；去重会把用户自己存过的
       那一条（可能叫别的名字）悄悄吞掉，让人以为名册里那条不见了；
    ④ 挑中它**只是把姓名与电话回填给调用方**（⛔ 不写任何后端数据）：它一旦被拿去
       "新建联系人"，每次下单都会在名册里多出一份自己的副本，而多出来的那一条
       没人会觉得是自己建的；
    ⑤ 三个调用方（下单页 / 线路与地点表单 / 订单详情补联系信息）**一个都不能漏** ——
       用户点名的场景正是线路那一条，而漏掉的那一个"就是没有这一项"，不会有人报故障；
    ⑥ 搜索语义**一点都不许变**：那一行也走同一份 core/UserSearch（按姓名/号码参与匹配），
       ⛔ 不给它开后门、也不让它常驻 —— 搜索的意义就是把不相关的行筛掉。

判据分九层：
  1. 零件（ui/common/SelfContact.kt）在位、API 齐全、不是空壳
  2. 合并只有一处（弹层里那一行），名册本身一行不动
  3. 「本人」那枚小标签：只在「我自己」那一行、样式照本页既有标签、不踩挤压基线
  4. 拿不到就不显示（两道闸 + 姓名进姓名、电话进电话）
  5. 三个调用方全部传了 selfContact（清单**自己算**，不是手写的文件名清单）
  6. 挑中它是纯回填：判别只活在弹层里，弹层拿不到容器，猜号那条老口径没被改坏
  7. 搜索语义没变（仍走 UserSearch，唯一一份 matches）
  8. 单测条数与断言（至少 6 例，钉住上面那几件事）
  9. 文书三件套与判据自身（含反向验证脚本）
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_pagination_wiring import strip_comments  # noqa: E402  （Kotlin 剥注释，复用不抄第二份）

ROOT = Path(__file__).resolve().parents[2]
JUDGE_NAME = "_check_contact_picker_self.py"
REVERSE_NAME = "_reverse_verify_contact_picker_self.py"

MAIN = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"
SELF_KT = MAIN / "ui/common/SelfContact.kt"
SHEET = MAIN / "ui/common/ContactPickerSheet.kt"
SEARCH = MAIN / "core/UserSearch.kt"
T_SELF = TEST / "ui/common/SelfContactTest.kt"
DOC = ROOT / "docs/changes/CHG-0117.md"
DOC_README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa" / REVERSE_NAME
SELF = Path(__file__).resolve()

FLOOR = {
    SELF_KT: 2000,
    SHEET: 6500,
    T_SELF: 2500,
    DOC: 2500,
}

# 三个调用方/宿主：只用来"报出名字"，判断靠下面的调用点清单**自己算**。
CALLERS = (
    "ui/shipper/OrderCreateScreen.kt",
    "ui/shipper/AddressScreen.kt",
    "ui/order/OrderEditInline.kt",
)


def read(p):
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8", errors="replace")


def kt(p):
    return strip_comments(read(p))


def count(hay, needle):
    return hay.count(needle)


def one_line(src):
    """把源码压成"单行归一"的样子：只用于比对那种跨行/缩进可能会动的写法。"""
    return re.sub(r"\s+", " ", src)


def main_kt_files():
    """清单自己算：整个 App 主源码树（不手写文件名清单）。"""
    return sorted(MAIN.rglob("*.kt"))


def sheet_call_sites(sources):
    """清单自己算：全 App 里 ContactPickerSheet( 的**调用点**（排除定义那一行）。

    手写"三个调用方"的清单已经过期过好几轮（本仓栽过 5 次），所以这里一律从源码扫。
    """
    out = []
    for p, s in sources.items():
        for m in re.finditer(r"ContactPickerSheet\(", s):
            ls = s.rfind("\n", 0, m.start()) + 1
            line = s[ls: s.find("\n", m.start())]
            if "fun ContactPickerSheet(" in line:
                continue
            out.append((p, m.start()))
    return out


def call_args(src, i):
    """从 ContactPickerSheet( 的位置切出这一对括号里的实参（按括号配对，不吃到下一个调用）。"""
    j = src.find("(", i)
    depth = 0
    for k in range(j, min(len(src), j + 4000)):
        ch = src[k]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return src[j: k + 1]
    return src[j: j + 2000]


def rel(p):
    return p.relative_to(ROOT).as_posix()


class Checker:
    def __init__(self):
        self.n = 0
        self.fails = []

    def ok(self, cond, label):
        self.n += 1
        if not cond:
            self.fails.append(label)
        return bool(cond)

    def present(self, hay, needle, label):
        return self.ok(needle in hay, f"{label}（找不到：{needle[:70]}）")

    def absent(self, hay, needle, label):
        return self.ok(needle not in hay, f"{label}（不该出现：{needle[:70]}）")

    def need(self, n, lo, label):
        return self.ok(n >= lo, f"{label}（实际 {n}，要求至少 {lo}）")

    def equals(self, got, want, label):
        return self.ok(got == want, f"{label}（实际 {got!r}，要求 {want!r}）")

    def report(self, title):
        if self.fails:
            print(f"❌ {title}：失败 {len(self.fails)} / {self.n} 项")
            for f in self.fails:
                print(f"[FAIL] {f}")
            return 1
        print(f"✅ {title}：通过 {self.n} 项，失败 0 项")
        return 0


def check_parts(c, sources):
    """1. 零件在位：构造与取数只有这一份，且不是空壳"""
    print("== 1. 零件（ui/common/SelfContact.kt）在位、API 齐全、不是空壳 ==")
    if not SELF_KT.exists():
        c.ok(False, f"零件在位：{rel(SELF_KT)}")
        return
    s = kt(SELF_KT)
    c.need(len(read(SELF_KT)), FLOOR[SELF_KT], "SelfContact.kt 不是空壳")
    for sig in (
        "const val SELF_ID: Long = -1L",
        "const val LABEL: String = \"本人\"",
        "fun of(name: String?, phone: String?): ContactDto?",
        "fun of(me: UserDto?): ContactDto?",
        "fun isSelf(c: ContactDto): Boolean",
        "fun withSelf(contacts: List<ContactDto>, self: ContactDto?): List<ContactDto>",
        "suspend fun load(container: AppContainer): ContactDto?",
        "suspend fun meOrNull(container: AppContainer): UserDto?",
    ):
        c.present(s, sig, f"零件里那一句：{sig[:52]}")
    # 会话里没有电话：⛔ 不许拿 username 顶替（填一个打不通的号比空着更糟）。
    c.absent(s, "it.username", "⛔ 不许拿 username 顶替电话")
    c.present(s, "container.repo.me()", "取数走 /users/me（唯一一处）")
    c.present(s, "catch (e: CancellationException)", "协程被取消原样抛（不当成取数失败）")
    # 负哨兵不能撞真实主键：只此一处定义，且是负数。
    c.equals(sum(count(ss, "const val SELF_ID") for ss in sources.values()), 1,
             "SELF_ID 整个 App 只有一处定义")


def check_single_merge(c, sources):
    """2. 合并只有一处（弹层里那一行），名册本身一行不动"""
    print("== 2. 合并只有一处（弹层里那一行），名册本身一行不动 ==")
    sheet = kt(SHEET)
    total = sum(count(s, "SelfContact.withSelf(") for s in sources.values())
    c.equals(total, 1, "SelfContact.withSelf( 整个 App 只有一处")
    c.present(sheet, "SelfContact.withSelf(", "合并点就在弹层里")
    # ⛔ 不许在名册来源处就地插一行（那会改到「地址与联系人」页的名册顺序本身）。
    offenders = sorted(rel(p) for p, s in sources.items()
                       if p != SHEET and "SelfContact.withSelf(" in s)
    c.equals(offenders, [], "只有弹层里能合并「我自己」（别处不许自己插一行）")
    c.present(sheet, "val rows = remember(contacts, selfContact)", "合并结果是 rows")
    c.present(sheet, "if (kw.isBlank()) rows else rows.filter { UserSearch.matches(kw, it.displayName, it.phone) }",
              "过滤作用在合并后的 rows 上（不绕开搜索）")


def check_badge(c, sources):
    """3. 「本人」那枚小标签：只在「我自己」那一行、样式照本页既有标签、不踩挤压基线"""
    print("== 3. 「本人」那枚小标签：只在我自己那一行、样式照既有标签、不踩挤压基线 ==")
    sheet = kt(SHEET)
    c.present(sheet, "if (SelfContact.isSelf(c)) {", "只有「我自己」那一行才画「本人」标签")
    c.present(sheet, "SelfContact.LABEL", "标签的字取自零件（唯一一份）")
    c.present(sheet, "private fun SelfTag()", "标签是这一页自己的小零件")
    c.present(sheet, "MaterialTheme.shapes.small", "标签圆角照既有小标签")
    c.present(sheet, "labelSmall", "标签字号照既有小标签（labelSmall）")
    # 样式照「地址与联系人」页卡片上的分类标签。
    c.present(read(MAIN / "ui/shipper/AddressScreen.kt"), "private fun CardTag(",
              "被照抄的那枚既有标签还在（AddressScreen.CardTag）")
    # §5 挤压基线：新加的文本不许是 maxLines = 1 + Ellipsis 且不带宽度的形状。
    for m in re.finditer(r"TextOverflow\.Ellipsis", sheet):
        seg = sheet[max(0, m.start() - 400): m.end() + 60]
        if "maxLines = 1" not in seg:
            continue
        c.ok(("weight(" in seg) or (".width(" in seg) or ("fillMaxWidth" in seg),
             "弹层里每一处可省略文本都显式给了宽度（_check_adaptive_layout.py §5 的基线只许减不许增）")
    c.present(sheet, "modifier = Modifier.weight(1f, fill = false)",
              "姓名那一格用 weight —— 标签才有位置（⛔ fillMaxWidth 会把标签挤成 0 宽）")


def check_missing_hides(c, sources):
    """4. 拿不到就不显示（两道闸 + 姓名进姓名、电话进电话）"""
    print("== 4. 拿不到就不显示（两道闸 + 姓名进姓名、电话进电话） ==")
    s = one_line(kt(SELF_KT))
    c.present(s, "if (n.isEmpty() || p.isEmpty()) return null",
              "「拿不到姓名或电话就不显示」那道闸（|| 不是 &&）")
    c.present(s, "return ContactDto(id = SELF_ID, phone = p, displayName = n)",
              "姓名进姓名、电话进电话")
    c.present(s, "fun of(me: UserDto?): ContactDto? = me?.let { of(it.fullName, it.phone) }",
              "从 /users/me 来的姓名进姓名、电话进电话")
    c.present(s, "val n = name?.trim().orEmpty()", "姓名先 trim")
    c.present(s, "val p = phone?.trim().orEmpty()", "电话先 trim")
    # ⛔ 不许有第二条"补一个默认值"的路（拿不到就编一个"我自己"出来）。
    c.absent(s, '?: ""', "⛔ 没有「拿一个空串顶上」的第二条路")


def check_callers(c, sources):
    """5. 三个调用方全部传了 selfContact（清单自己算）"""
    print("== 5. 三个调用方全部传了 selfContact（清单自己算） ==")
    sites = sheet_call_sites(sources)
    c.need(len(sites), 3, "调用点数量（三个调用方一个都不能少）")
    for p, i in sites:
        args = call_args(sources[p], i)
        c.ok(re.search(r"selfContact\s*=", args) is not None,
             f"{rel(p)} 的调用点传了 selfContact=（每一处都要传，漏掉的那一个界面上就是没这一项）")
    # 宿主接口也要把这一行递下去（订单详情那条走接口）。
    host = kt(MAIN / "ui/order/OrderEditInline.kt")
    c.present(host, "val selfContact: ContactDto?", "OrderEditHost 接口上有 selfContact")
    c.present(host, "selfContact = edit.selfContact", "订单详情那条把 selfContact 递给弹层")
    # 三个 VM 各取各的（都只调零件那一处取数，⛔ 不各自拼 ContactDto）。
    for f, label in (
        ("ui/shipper/OrderCreateViewModel.kt", "下单页"),
        ("ui/shipper/AddressViewModel.kt", "线路/地点表单"),
        ("ui/order/OrderDetailViewModel.kt", "订单详情补联系信息"),
    ):
        vm = kt(MAIN / f)
        c.present(vm, "SelfContact.", f"{label}的 VM 走零件取数")
        c.absent(vm, "ContactDto(id = ", f"{label}的 VM 不许自己拼一条联系人（会在三处漂移）")


def check_no_backend_write(c, sources):
    """6. 挑中它是纯回填：判别只活在弹层里，弹层拿不到容器，猜号那条老口径没被改坏"""
    print("== 6. 挑中它是纯回填：判别只活在弹层里、弹层拿不到容器 ==")
    owners = sorted(rel(p) for p, s in sources.items() if "SelfContact.isSelf(" in s)
    c.equals(owners, ["android/app/src/main/java/com/tapmoay/sorders/ui/common/ContactPickerSheet.kt"],
             "SelfContact.isSelf( 只允许出现在弹层里（判别只在画不画标签那一行）")
    sheet = kt(SHEET)
    c.absent(sheet, "container", "弹层里根本拿不到容器 ⇒ 不可能写后端")
    c.absent(sheet, "repo.", "弹层里没有任何仓库调用")
    # 负哨兵不许流到"写"的路径上：三个 VM 里都不许出现 SELF_ID。
    for f in ("ui/shipper/OrderCreateViewModel.kt", "ui/shipper/AddressViewModel.kt",
              "ui/order/OrderDetailViewModel.kt"):
        c.absent(kt(MAIN / f), "SelfContact.SELF_ID", f"{rel(MAIN / f)} 里不许碰那枚哨兵")
    # 老口径：挑人记下的号只用来在名册里找人（合成的 -1 查不到 → 什么都不做），别被改坏。
    ocvm = kt(MAIN / "ui/shipper/OrderCreateViewModel.kt")
    c.equals(count(ocvm, "pickedContactId = c.id"), 1, "pickedContactId = c.id 在 OrderCreateViewModel 里只有一处")
    c.present(ocvm, "pickedContactId ?: return", "写回号码前先看有没有挑过（沿用既有口径）")
    avm = kt(MAIN / "ui/shipper/AddressViewModel.kt")
    c.equals(count(avm, "draftContactId = c.id"), 1, "draftContactId = c.id 只有一处（只当「有没有选」的闸）")


def check_search(c, sources):
    """7. 搜索语义没变（仍走 UserSearch，唯一一份 matches）"""
    print("== 7. 搜索语义没变（仍走 UserSearch，唯一一份 matches） ==")
    sheet = kt(SHEET)
    c.present(sheet, "UserSearch.matches(kw, it.displayName, it.phone)", "弹层仍走那唯一一份 UserSearch")
    c.present(sheet, "\"搜索姓名或手机号\"", "占位语一字未改（另一份判据按它认这个框）")
    definers = []
    for p, s in sources.items():
        for m in re.finditer(r"\bfun matches\(", s):
            # ⚠️ 不能只按名字认：`ai/AiProviders.kt` 里也有一个 `fun matches(other: String)`
            #    （比 baseUrl 的），把它算进来这条判据就永远红（永远红的检查 = 没有检查）。
            if ".contains(" in s[m.end(): m.end() + 400]:
                definers.append(rel(p))
    c.equals(definers, ["android/app/src/main/java/com/tapmoay/sorders/core/UserSearch.kt"],
             "全树「按人匹配」的函数只在 UserSearch.kt 定义一次")
    c.present(kt(SEARCH), "fun matches(query: String, name: String?, phone: String?): Boolean",
              "那一处就是 core/UserSearch.kt（按人匹配的那份）")


def check_tests(c, sources):
    """8. 单测条数与断言（至少 6 例）"""
    print("== 8. 单测条数与断言（至少 6 例） ==")
    if not T_SELF.exists():
        c.ok(False, f"单测在位：{rel(T_SELF)}")
        return
    t = read(T_SELF)
    c.need(len(t), FLOOR[T_SELF], "SelfContactTest.kt 不是空壳")
    c.need(count(t, "@Test"), 6, "单测条数")
    for needle, label in (
        ("assertNull(SelfContact.of(null, ", "断言：姓名拿不到就不显示"),
        ("assertNull(SelfContact.of(\"王老板\", null)", "断言：电话拿不到就不显示"),
        ("assertNull(SelfContact.of(me(fullName = \"   \")))", "断言：姓名只有空白也不显示"),
        ("assertNull(SelfContact.of(me(phone = \"\")))", "断言：测试号那种没电话的也不显示"),
        ("assertEquals(SelfContact.SELF_ID, self?.id)", "断言：id 是那枚负哨兵"),
        ("assertEquals(listOf(self, a, b), rows)", "断言：固定排在最前且名册顺序不动"),
        ("assertSame(list, SelfContact.withSelf(list, null))", "断言：拿不到时名册一行都不多"),
        ("assertEquals(2, rows.size)", "断言：不去重（同号那条也留着）"),
        ("assertTrue(SelfContact.isSelf(self))", "断言：认得自己那一行"),
        ("assertFalse(SelfContact.isSelf(c(1L, ", "断言：真实联系人不会被当成自己"),
    ):
        c.present(t, needle, label)


def check_docs(c, sources):
    """9. 文书三件套与判据自身（含反向验证脚本）"""
    print("== 9. 文书三件套与判据自身（含反向验证脚本） ==")
    if DOC.exists():
        d = read(DOC)
        c.need(len(d), FLOOR[DOC], "CHG-0117.md 不是空壳")
        for sec in ("## ① 六问", "## ② Must Change", "## ③ Boundary", "## ④ Behavior Contract",
                    "## ⑤ Data Contract", "## ⑥ CHG 专章", "## ⑦ 测试", "## ⑧ 证据", "## ⑨ 关闭"):
            c.present(d, sec, f"九节里的「{sec}」")
        c.present(d, "CHG-0117", "文书首部带号")
    else:
        c.ok(False, f"文书在位：{rel(DOC)}")
    c.present(read(DOC_README), "CHG-0117.md", "README 台账里有一行指向本文书")
    claim = read(CLAIM)
    c.ok(re.search(r"(?m)^### \[[^\]]*\].*CHG-0117", claim) is not None,
         "AI_WORK_CLAIM.md 里有一个首行带 CHG-0117 的块")
    me = read(SELF)
    c.present(me, "R4-BOUNDARY-JUSTIFICATION:", "本判据写了边界理由")
    c.present(me, 'sys.stdout.reconfigure(encoding="utf-8", errors="replace")', "输出按 UTF-8")
    c.present(me, 'if "--list" in sys.argv:', "有 --list")
    c.ok(REVERSE.exists(), f"反向验证脚本在位：{REVERSE_NAME}")
    if REVERSE.exists():
        rev = read(REVERSE)
        c.present(rev, "lock_reverse_verify", "反向验证先上锁")
        c.present(rev, "unlock_reverse_verify", "反向验证收尾解锁")
        cases = re.findall(r'(?m)^    \("', rev[rev.find("CASES = ["):])
        c.need(len(cases), 5, "注入条数至少 5")
        for theme in ("整项去掉", "取反", "空行", "漏掉", "新建联系人"):
            c.present(rev, theme, f"注入覆盖「{theme}」那一条")
        c.present(rev, "逐字节一致", "反向验证末尾逐字节还原")


def main():
    sources = {p: kt(p) for p in main_kt_files()}
    layers = []
    for fn in (
        check_parts,
        check_single_merge,
        check_badge,
        check_missing_hides,
        check_callers,
        check_no_backend_write,
        check_search,
        check_tests,
        check_docs,
    ):
        c = Checker()
        fn(c, sources)
        layers.append(c.report(fn.__doc__ or fn.__name__))
    bad = sum(layers)
    print()
    if bad:
        print(f"❌ {JUDGE_NAME}：{bad} 层有失败项（共 9 层）")
        return 1
    print(f"✅ {JUDGE_NAME}：9 层全部通过")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        for p in sorted(FLOOR):
            print(f"· {p.relative_to(ROOT)}")
        print(f"· 反向验证：_tools/qa/{REVERSE_NAME}")
        raise SystemExit(0)
    raise SystemExit(main())
