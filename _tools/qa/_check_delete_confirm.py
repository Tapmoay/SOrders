# -*- coding: utf-8 -*-
"""红线：**删除一律先问一句** —— 地址与联系人页的删除入口搬进编辑抽屉 + 二次确认（CHG-0032，2026-10-04）。

## 用户原话（2026-10-04）
> 「有两栋校改第一个就是把地点线路联系人，他那里的**删除键卡片删除键移到编辑界面当中**，
>  并且**做二次确认**啊删除都要做二次确认的，不要点一下就直接删掉了，防止误触啊」

## 这条为什么必须有机器的判据
地址与联系人页原先的删除是**卡片右上角一颗红图标、点一下就落库**（CHG-0012 起的样子）。
2026-10-04 用户点名要挡的是**误触**：入口搬进编辑抽屉，点下去先弹一句确认。
而这一整套在类型系统眼里**什么都不是**：

* `askDelete` 里顺手调一次 `delete(...)`（"只举手"变成"直接落库"）→ 编译过、点上去照旧弹确认，
  区别只是那条**已经没了**；
* `confirmDelete` 不再清 `pendingDelete` → 弹层关不掉，或者抽屉关掉之后弹层还开着；
* `deleteKindLabel` 与 `RecentlyDeleted.label` 两处说法分叉（「地点」对「常用地点」）→
  用户以为删掉的不是同一样东西；
* 标题里那个名字取错了草稿（拿联系人的名字去删线路）→ 弹层问的和删的不是同一条；
* 抽屉里那一行不写 `if (vm.editingXxx != null)` → **新增**的时候也能点删除。

全部**静默**：没有异常、没有类型错误、真机上点下去都"正常"。判据分六层：

1. **反空转**：三个动作函数都在、函数体 ≥ 下限（截空即红）；
2. **一套说法**：`deleteKindLabel` 三档 ↔ 三处 `RecentlyDeleted.label` 字面一致，
   且 `undoDelete` / `confirmDelete` 的 when 分支集合都恰好是三档；
3. **askDelete 只举手不落库**：body 里一处 `delete*` / `repo.delete` 都不许有，必须写
   `deleteKindLabel(kind) ?: return` + `pendingDelete = PendingDelete(`，名字取自**正在编辑的草稿**；
4. **confirmDelete 是唯一落库点**：三个 `delete*` 全库各只出现一次、都在它体内，先清状态再执行；
5. **两句话（纯函数）与单测**：标题点出是哪一条、空名退成「这条 X」不留空引号；正文说清「列表顶上」
   「撤销」「找不回来」；单测真的在调这两个纯函数；
6. **接线**：界面三处只调 `vm.askDelete("…")`、确认走 `vm.confirmDelete()`、页面不直接落库；
   规范 4.2c 写了这条；反向验证在且拿着注入锁；登记簿有 CHG-0032。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界消除不了**。"点删除之前要不要先问一句"不是类型属性：
`askDelete` / `confirmDelete` / `delete*` / `repo.deleteX` 全是普通的挂起函数，返回值与可见性
**都不涉及**它们之间的先后关系 —— 把 `askDelete` 写成直接落库、把确认弹层删掉、把两处档名改成
不一样，编译器一声不响，界面也照常工作，直到用户又一次"点一下就没了"。共用件 `DangerConfirmDialog`
已经把**形态**收成一处，但没有任何机制能强制某一页**用它**、更没法强制"落库前必须经过它"。
所以只能靠一条判据把 VM 的三个动作、两句话、界面三处入口与规范对起来，并在反向验证里把
"askDelete 顺手删""确认改回一点即删""名字不处理空""单测不再调纯函数"这几条真跑一遍。

用法：python _tools/qa/_check_delete_confirm.py
     python _tools/qa/_check_delete_confirm.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
ADDR_SCREEN = AND / "ui/shipper/AddressScreen.kt"
ADDR_VM = AND / "ui/shipper/AddressViewModel.kt"
CONFIRM_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/shipper/AddressDeleteConfirmTest.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
DOC = ROOT / "docs/changes/CHG-0032.md"
REGISTRY = ROOT / "docs/changes/README.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_delete_confirm.py"

#: 三档删除（软件里用 kind 认，界面上一句都不提这两个词）
KINDS = {"line", "place", "contact"}
#: 「什么」→（kind、delete* 的签名、给人看的那档名）
PAIRS = (
    ("line", "fun delete(a: AddressDto) {", "常用线路"),
    ("place", "fun deleteLocation(l: LocationDto) {", "地点"),
    ("contact", "fun deleteContact(c: ContactDto) {", "联系人"),
)
#: VM 源码字符数下限（文件被搬走 / 判据读空即红）
VM_FLOOR = 3000
#: 三个动作的函数体下限（同上：抽取失效比判据腐烂更危险）
BODY_FLOOR = 60
# cancelDelete 是一行动作（pendingDelete = null）：量不出体量，只量"它确实不是一个空壳"
CANCEL_FLOOR = 24
#: 单测条数下限与"真的在调纯函数"的次数下限
TEST_MIN = 4
MIN_TEST_CALLS = 1
#: 一次 when 分支：  "line" ->
BRANCH = re.compile(r'"(\w+)" ->')
#: 设计规范里那一节（位置纪律 + 这次的"删除不在卡上"）
DESIGN_42C = "### 4.2c"


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def fn_body(src: str, sig: str) -> str:
    """sig 那个函数的**函数体**（大括号配对，不按行猜）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[b : j + 1]
    return ""


def decl_body(src: str, sig: str) -> str:
    """sig 那个函数的**声明 + 函数体**（KDoc 之后的那个 private fun）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = fn_body(src, sig)
    if not b:
        return ""
    j = src.find(b, i)
    return src[i : j + len(b)]


def stmt(src: str, sig: str, span: int = 500) -> str:
    """sig 那个**表达式体**函数（没有大括号那两种）到下一个空行为止的源码。

    ⚠️ 两个纯函数是 `= if (...) ... else ...` 的形状，大括号抽取在它们身上取到空串，
    而"空串里找不到那两句话"会被读成"文案没了"—— 抽取方式必须按代码形状挑。
    """
    i = src.find(sig)
    if i < 0:
        return ""
    j = src.find("\n\n", i)
    return src[i : j if j > 0 else i + span]


def section(text: str, heading: str) -> str:
    """文档里某一节（从 heading 那一行到下一个同级 ### 之前）。"""
    i = text.find(heading)
    if i < 0:
        return ""
    j = text.find("\n### ", i + len(heading))
    return text[i:] if j < 0 else text[i:j]


def branches(body: str) -> set:
    return set(BRANCH.findall(body))


class Checker:
    def __init__(self) -> None:
        self.fails: list = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    if refuse_if_injecting("删除二次确认检查"):
        return 1

    c = Checker()
    print("删除先问一句：抽屉里那颗删除只举手，确认才落库（CHG-0032，2026-10-04）")

    vm = read(ADDR_VM)
    vmc = code(ADDR_VM)
    c.ok("AddressViewModel.kt 存在", ADDR_VM.exists(), str(ADDR_VM))
    c.ok(f"VM 源码 ≥ {VM_FLOOR} 字符（文件被搬走 / 读空即红）", len(vmc) >= VM_FLOOR, f"只有 {len(vmc)} 字符")

    # ---- 0. 反空转：三个动作都在，函数体不为空 ----
    sigs = ("fun askDelete(kind: String) {", "fun cancelDelete() {", "fun confirmDelete() {")
    # ⛔ 下限**分档**：cancelDelete 本来就是一行（pendingDelete = null），拿 60 去量它等于量了个寂寞 ——
    #    它的"内容"不靠体量证明，靠下面第 273 行那条（只清状态、一个落库调用都没有）。另两个动作照旧 60。
    FLOORS = {
        "fun askDelete(kind: String) {": BODY_FLOOR,
        "fun cancelDelete() {": CANCEL_FLOOR,
        "fun confirmDelete() {": BODY_FLOOR,
    }
    bodies = {}
    for sig in sigs:
        bodies[sig] = fn_body(vmc, sig)
        c.ok(
            f"{sig} 的函数体 ≥ {FLOORS[sig]} 字符（抽取失效即红）",
            len(bodies[sig]) >= FLOORS[sig],
            f"只有 {len(bodies[sig])} 字符",
        )

    # ---- 1. 一套说法：deleteKindLabel ↔ RecentlyDeleted.label ----
    dk = decl_body(vmc, "fun deleteKindLabel(kind: String): String? =")
    for kind, what in (("line", "常用线路"), ("place", "地点"), ("contact", "联系人")):
        c.ok(
            f"deleteKindLabel 里 {kind} 那档给用户看的是「{what}」",
            f'"{kind}" -> "{what}"' in dk,
            f"找不到 {kind} -> {what}",
        )
    c.ok("deleteKindLabel 认不出的 kind 返回 null（不猜一个名字出来）", "else -> null" in dk, "else 分支不是 null")
    for kind, sig, what in PAIRS:
        b = fn_body(vmc, sig)
        c.ok(
            f"「{what}」这档在 delete* 里记的 label 与 deleteKindLabel 是同一套说法",
            f'label = "{what}"' in b,
            f"找不到 label = {what}",
        )
    nk = set(re.findall(r'kind = "(\w+)"', vmc))
    c.ok(f"三处 RecentlyDeleted 记的 kind 恰好是三档（实测 {sorted(nk)}）", nk == KINDS, f"实际 {sorted(nk)}")
    for sig, why in (
        ("fun undoDelete() {", "撤回按 kind 挑还原接口"),
        ("fun confirmDelete() {", "确认按 kind 挑 delete*"),
    ):
        b = branches(fn_body(vmc, sig))
        c.ok(f"「{why}」的分支恰好是三档（多一个少一个都红）", b == KINDS, f"实际 {sorted(b)}")

    # ---- 2. askDelete：只举手，不落库 ----
    ask = bodies["fun askDelete(kind: String) {"]
    bad = [x for x in ("delete(", "deleteContact(", "deleteLocation(", "repo.delete") if x in ask]
    c.ok("askDelete 只举手不落库（body 里一处 delete* / repo.delete 都没有）", not bad, "它自己就把人删了：" + "、".join(bad))
    c.ok(
        "askDelete 认不出 kind 就直接不举手（deleteKindLabel(kind) ?: return）",
        "deleteKindLabel(kind) ?: return" in ask,
        "不认的 kind 也走进来了",
    )
    c.ok(
        "askDelete 把待确认那一笔记进 pendingDelete（不是界面里 remember 的）",
        "pendingDelete = PendingDelete(" in ask,
        "找不到 pendingDelete = PendingDelete(",
    )
    for what, needle in (
        ("线路", "editing?.receiverName"),
        ("地点", "editingLocation?.name"),
        ("联系人", "editingContact?.displayName"),
    ):
        c.ok(f"{what}那一档的名字取自正在编辑的那份草稿（{needle}）", needle in ask, f"找不到 {needle}")
    c.ok(
        "两句话都是从纯函数来的（askDelete 里现拼文案 = 单测白写）",
        "deleteConfirmTitle(" in ask and "deleteConfirmMessage(" in ask,
        "askDelete 没调那两个纯函数",
    )

    # ---- 3. confirmDelete：唯一落库点 ----
    cf = bodies["fun confirmDelete() {"]
    for call in ("delete(it)", "deleteLocation(it)", "deleteContact(it)"):
        n = vmc.count(call)
        c.ok(f"全 VM 里 {call} 恰好出现一次（唯一落库点在 confirmDelete）", n == 1, f"实际 {n} 次")
    c.ok(
        "三个落库调用都在 confirmDelete 的函数体里",
        all(x in cf for x in ("delete(it)", "deleteLocation(it)", "deleteContact(it)")),
        "有落库调用跑到别的函数里了",
    )
    i_clear, i_run = cf.find("pendingDelete = null"), cf.find("when (p.kind)")
    c.ok(
        "confirmDelete 先清掉 pendingDelete 再执行（它已经不在了，别把弹层留着）",
        0 <= i_clear < i_run,
        f"清状态在 {i_clear}、执行在 {i_run}",
    )
    c.ok(
        "confirmDelete 顺手把抽屉关掉（抽屉里编辑的东西刚被删了）",
        cf.count("= false") == 3,
        f"只有 {cf.count(chr(61) + chr(32) + chr(102) + chr(97) + chr(108) + chr(115) + chr(101))} 处关抽屉",
    )
    cc = bodies["fun cancelDelete() {"]
    c.ok(
        "cancelDelete 只清状态、不落库（取消 = 什么都不发生）",
        "pendingDelete = null" in cc and "delete(" not in cc,
        "取消那条路也落库了",
    )

    # ---- 4. 两句话（纯函数） ----
    t_stmt = stmt(vmc, "fun deleteConfirmTitle(what: String, name: String): String =")
    m_stmt = stmt(vmc, "fun deleteConfirmMessage(what: String): String =")
    c.ok("标题那个纯函数在（deleteConfirmTitle）", bool(t_stmt), "找不到 deleteConfirmTitle")
    c.ok("正文那个纯函数在（deleteConfirmMessage）", bool(m_stmt), "找不到 deleteConfirmMessage")
    c.ok(
        "标题在名字空着时退成「删除这条 X？」（不留一对空引号）",
        "if (name.isBlank())" in t_stmt,
        "名字空着时没退路 —— 会出现「」两个空引号",
    )
    c.ok(
        "标题两种写法都点名是哪一档（$what）并且把名字带进去（$name）",
        "删除这条$what？" in t_stmt and "删除$what「$name」？" in t_stmt,
        "标题里拼串漏了变量",
    )
    for needle, why in (
        ("列表顶上", "恢复入口在**这一页顶上**（不在这张弹层里）"),
        ("撤销", "那颗按钮叫「撤销」"),
        ("已删除$what", "删完列表顶上留一行「已删除 X」"),
        ("找不回来", "什么时候就真找不回来了"),
    ):
        c.ok(f"正文说清还能捞回来：{why}", needle in m_stmt, f"正文里找不到「{needle}」")

    # ---- 5. 单测 ----
    t = read(CONFIRM_TEST)
    c.ok("单测文件在（android/app/src/test/.../AddressDeleteConfirmTest.kt）", CONFIRM_TEST.exists(), str(CONFIRM_TEST))
    n_test = t.count("@Test")
    c.ok(f"单测条数 ≥ {TEST_MIN}（实测 {n_test} 条）", n_test >= TEST_MIN, f"只有 {n_test} 条")
    c.ok(
        "单测真的在调这两个纯函数（不是只测了个壳）",
        t.count("deleteConfirmTitle(") >= MIN_TEST_CALLS and t.count("deleteConfirmMessage(") >= MIN_TEST_CALLS,
        "单测里找不到这两个纯函数",
    )
    c.ok(
        "单测盖了「空名字」那一支（空串 / 空格都试过）",
        "删除这条" in t and "   " in t,
        "空名字那一支没人测",
    )

    # ---- 6. 接线：界面 / 规范 / 反验 / 登记 ----
    sc = code(ADDR_SCREEN)
    asks = re.findall(r'vm\.askDelete\("(\w+)"\)', sc)
    c.ok(
        f"界面三处删除入口只调 vm.askDelete（恰好三处、三档齐，实测 {sorted(asks)}）",
        sorted(asks) == ["contact", "line", "place"],
        f"抽到 {sorted(asks)}",
    )
    direct = [x for x in ("vm.delete(", "vm.deleteContact(", "vm.deleteLocation(") if x in sc]
    c.ok("页面没有绕过确认直接落库（vm.delete* 一次都不许出现）", not direct, "直接落库的调用还在：" + "、".join(direct))
    c.ok("确认弹层的确认钮走 vm.confirmDelete()", sc.count("vm.confirmDelete()") == 1, f"出现 {sc.count('vm.confirmDelete()')} 次")
    c.ok("取消 / 点空白走 vm.cancelDelete()", sc.count("vm.cancelDelete()") == 1, f"出现 {sc.count('vm.cancelDelete()')} 次")
    sec = section(read(DESIGN), DESIGN_42C)
    c.ok(
        "规范 4.2c 里写了这次的新规矩（删除不在卡上 + 二次确认）",
        "删除不在卡上" in sec and "二次确认" in sec,
        "规范里找不到这两句（规范是这条纪律唯一的文字出处）",
    )
    c.ok("反向验证脚本在", REVERSE.exists(), str(REVERSE))
    rev = read(REVERSE)
    c.ok(
        "反验脚本拿着注入锁（lock_reverse_verify）",
        "lock_reverse_verify" in rev,
        "没上锁：注入期间别的检查会给出不可信的结论",
    )
    c.ok("文档在（docs/changes/CHG-0032.md）", DOC.exists(), str(DOC))
    c.ok(
        "登记簿里有 CHG-0032 这一行（整行，不是一个链接里的字样）",
        bool(re.search(r"^\|\s*[\x60]?CHG-0032[\x60]?\s*\|", read(REGISTRY), re.M)),
        "没登记（别人不知道这个 ID 用掉了）",
    )
    c.ok(
        "本批没顺手换掉落库接口（deleteAddress / deleteContact / deleteLocation 都还在）",
        all(x in vmc for x in ("repo.deleteAddress(", "repo.deleteContact(", "repo.deleteLocation(")),
        "仓库接口被换了 —— 撤回那条链路会跟着断",
    )

    return c.report("删除先问一句（CHG-0032）")


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("这一页的删除先问一句，分六层：")
        print("  0. 反空转：三个动作函数都在、函数体不空；")
        print("  1. 一套说法：deleteKindLabel ↔ RecentlyDeleted.label ↔ when 分支集合；")
        print("  2. askDelete 只举手不落库（认不出 kind 就不举手、名字取自草稿）；")
        print("  3. confirmDelete 是唯一落库点（先清状态、顺手关抽屉）；");
        print("  4. 两句话的纯函数（空名退成「这条 X」、正文说清撤销）；")
        print("  5. 单测真的在调这两个纯函数；")
        print("  6. 接线：界面 / 规范 4.2c / 反向验证（拿着注入锁）/ 登记簿。")
        sys.exit(0)
    sys.exit(main())
