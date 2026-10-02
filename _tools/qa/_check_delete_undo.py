# -*- coding: utf-8 -*-
"""红线：**删了要能当场撤回** —— 软删 + 手边那个「撤销」（CHG-0015，2026-10-03）。

## 规范原文（docs/PROJECT_MAP/06_DESIGN_SYSTEM.md）
* `:1328`「**删除一律软删 + 手边要有撤回**：删完那条 snackbar 上就有「撤回」（用户定的硬规矩）。
  ⚠️ **但只有它不够**：snackbar 会飘走，飘走之后那张单就再也找不回来了 —— 所以还有回收站页。
  两个入口各管一段时间：snackbar 管"手边那一下"，回收站管"过一会儿才想起来的那个"。」
* `:1371`「删除一律软删 + 手边要有撤回：删供应商/应付单有「撤回」+ 回收站页；撤销付款也有「撤回」。」

## 这条为什么必须有机器的判据
这一页（地址与联系人）的三张卡上，删除就是**卡片右上角那个红图标**，点了就发生、**没有二次确认**：
手滑一下，一条常用线路 / 一个联系人 / 一个常用地点就没了。而撤回入口是**另一个调用**：
`repo.deleteX(id)` 和 `repo.restoreX(id)` 是两个各自独立的挂起函数，谁调用、在哪调用都不受约束 ——
把撤回那一行删掉，编译过、真机上也"能删掉"，**没有任何报错**，直到用户点错那一下。
Web 端那套"删除有 undo 栈"在这里也不存在：`OneShotSnackbar`（ui/common/Components.kt）
只有 message/onConsumed、**没有 action 槽**，所以"手边那一下"必须自己画在页面上。

## 判据分五层
1. **调用点清单自己算**：扫 `ui/` 下所有 `repo.deleteX(` 的调用点，按名字配对要求同文件出现 `repo.restoreX(`
   （`deletePlace` → `restorePlace`）—— 清单不手写，新页面加一个删除就自动进清单；
2. **豁免表只能收紧**：还没配撤回的调用点记在 `EXEMPT` 里（每条带理由），**每一条都必须仍然真实存在**
   （那一页修好了 / 文件搬走了 → 红，逼你把这一行删掉，不许留一条空转的豁免）；
3. **本批这一页的撤回链路完整**：三处删除都记「刚删的那条」、记下的 kind 集合 == `undoDelete()` 的
   `when` 分支集合（多一个分支 / 少一个分支都红）、三个还原接口都真的被调到；
4. **"手边"是个位置**：提示画在列表**上面**（`vm.undoDelete()` 在列表容器之前出现），不是塞在页面末尾
   —— 长列表里塞在末尾等于没有（OrderCreateScreen 那份同款做法就是这么来的）；
5. **接线**：仓库层三个 `restore*` 还在、规范里那条规则还在、反向验证脚本在、文档九节、登记簿有 CHG-0015。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。"删除之后还能不能撤回"不是类型属性：
`deleteX` 与 `restoreX` 都是普通的挂起函数，返回值、可见性、分层约束**都不涉及**它们之间的配对关系；
把撤回入口删掉、把记录的那一行删掉、把 kind 的 when 分支改错，三种改法都通过编译、都通过渲染，
真机上删除照样"成功"。而"手边"更是纯位置属性（提示必须在列表上面、不能落在屏幕外的长列表末尾），
编译期看不见、Compose 也没有任何修饰符能表达它。所以只能扫**调用点**与**位置**，
并把「多一个删除没配撤回」这件事用清单自己算的方式挡住（新页面漏了自动红，不靠人记得来加判据）。

用法：python _tools/qa/_check_delete_undo.py
     python _tools/qa/_check_delete_undo.py --list
     python _tools/qa/_reverse_verify_delete_undo.py   （反向验证：每种破法都要被抓）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_hints import Checker, read, strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
UI = AND / "ui"
ADDR_SCREEN = AND / "ui/shipper/AddressScreen.kt"
ADDR_VM = AND / "ui/shipper/AddressViewModel.kt"
REPO = AND / "data/repo/AppRepository.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_delete_undo.py"
DOC = ROOT / "docs/changes/CHG-0015.md"
REGISTRY = ROOT / "docs/changes/README.md"

DELETE_CALL = re.compile(r"repo\.(delete[A-Za-z0-9_]*)\(")
#: 全库删除调用点的下限：扫描本身被改坏时（正则写错 / 目录搬走）必须先喊，
#: 否则"一个违规都没有"和"一个都没扫到"是同一个输出。
MIN_CALLS = 18
#: 目录下 .kt 文件数下限（同上：目录改名后不许安静全绿）
MIN_KT_FILES = 200
#: `undoDelete()` 的 kind 分支必须与三处删除记下的 kind **完全一致**（双向包含）
KINDS = ("line", "place", "contact")
#: 撤回提示必须画在列表容器**之前**（在列表上面 = 永远在第一屏）
LIST_ANCHOR = "Box(Modifier.weight(1f)) {"
#: 豁免条数上限（**只能收紧**：新加一条就会红，逼人先想清楚是不是真要再欠一笔）
#: 2026-10-04 CHG-0020：挂账单位补上了撤回 ⇒ 上限跟着从 12 收到 11（欠账还一笔就收一格）。
EXEMPT_MAX = 11

#: 还没配撤回入口的删除调用点 —— 键 = "相对 android/.../sorders 的路径::方法名"。
#: ⛔ 这张表**只能收紧**：把某一页的撤回补上之后，这一行必须删掉（判据会逼你删，
#: 因为每一条都要求"那个调用点还在、且仍然没有配对的 restore"）。
#: 这不是"已合规"的名单，是**欠账登记**：欠着不等于可以忘。
EXEMPT = {
    "ui/order/OrderDetailViewModel.kt::deleteOrder":
        "订单的撤回走的是状态机（订单卡上那个「撤回」动作），不是软删还原 —— 单独一件事",
    "ui/dispatcher/AccountManageViewModel.kt::deleteUser":
        "删账号＝注销：能不能「撤销注销」没拍板 —— 排在账号管理那一批",
    "ui/dispatcher/DispatcherLedgerViewModel.kt::deleteLedger":
        "派单账本的行删除 —— 撤回排在账本那一批",
    "ui/dispatcher/PriceMatrixViewModel.kt::deletePriceRule":
        "价格矩阵里的规则删除 —— 撤回排在定价那一批（FEAT-0004 会动这块）",
    "ui/dispatcher/FreightTemplatesViewModel.kt::deleteFreightTemplate":
        "运费模板删除 —— 撤回排在模板页那一批",
    "ui/dispatcher/ContactCategoriesViewModel.kt::deleteContactCategory":
        "分类名册页（后端在有人挂靠时直接拒绝删除）—— 撤回等分类名册统一收口那一批",
    "ui/dispatcher/ExpenseCategoriesScreen.kt::deleteExpenseCategory":
        "分类名册页 —— 同上（撤回等分类名册统一收口那一批）",
    "ui/dispatcher/FreightCategoriesScreen.kt::deleteFreightCategory":
        "分类名册页 —— 同上（撤回等分类名册统一收口那一批）",
    "ui/dispatcher/OrderTemplateCategoriesScreen.kt::deleteOrderTemplateCategory":
        "分类名册页 —— 同上（撤回等分类名册统一收口那一批）",
    "ui/dispatcher/PlaceCategoriesViewModel.kt::deletePlaceCategory":
        "分类名册页 —— 同上（撤回等分类名册统一收口那一批）",
    "ui/dispatcher/ProductCategoriesViewModel.kt::deleteProductCategory":
        "分类名册页 —— 同上（撤回等分类名册统一收口那一批）",
}
#: ⚠️ 上面这张表**故意没有** `SupplierDetailScreen.kt::deleteSupplierPayable`：
#: 它删的是应付单（`deleteSupplierPayable`）、还原接口叫 `restoreSupplierPayment`（名字不同、同一件事），
#: 所以它**已经有**撤回入口（ui/dispatcher/SupplierDetailScreen.kt:159），只是名字配不上。
#: 判据按名字配对会把它判红 —— 这正是下面 NAME_MISMATCH 单独列出来的原因。
NAME_MISMATCH = {
    "ui/dispatcher/SupplierDetailScreen.kt::deleteSupplierPayable": "repo.restoreSupplierPayment(",
}


def delete_sites() -> list[tuple[str, str]]:
    """扫 `ui/` 下所有 `repo.deleteX(` 调用点 → [(相对路径, 方法名)]（清单自己算）。"""
    out: list[tuple[str, str]] = []
    for p in sorted(UI.rglob("*.kt")):
        src = strip_comments(read(p))
        rel = str(p.relative_to(AND)).replace("\\", "/")
        for m in DELETE_CALL.finditer(src):
            out.append((rel, m.group(1)))
    return out


def kinds_recorded(vm: str) -> set[str]:
    """从 `RecentlyDeleted(kind = "x"` 里把记下的 kind 抠出来。"""
    return set(re.findall(r"RecentlyDeleted\(\s*kind\s*=\s*\"([a-z]+)\"", vm))


def kinds_branched(vm: str) -> set[str]:
    """`undoDelete()` 里 `when (rd.kind)` 的分支集合。"""
    i = vm.find("fun undoDelete()")
    if i < 0:
        return set()
    j = vm.find("\n    fun ", i + 10)
    body = vm[i : j if j > 0 else len(vm)]
    m = re.search(r"when \(rd\.kind\) \{(.*?)\n\s*\}", body, re.S)
    return set(re.findall(r"\"([a-z]+)\"\s*->", m.group(1))) if m else set()


def main() -> int:
    if refuse_if_injecting("删除撤回检查"):
        return 1
    c = Checker()

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    c.section("0. 反空转（文件搬走 / 目录改名 / 扫描写坏时先喊）")
    missing = [p.name for p in (ADDR_SCREEN, ADDR_VM, REPO, DESIGN) if not p.exists()]
    c.ok("四个文件都在（AddressScreen / AddressViewModel / AppRepository / 设计规范）",
         not missing, f"缺：{missing}")
    if missing:
        print("\n❌ 文件都不在，后面的判据没有意义")
        return 1
    screen = strip_comments(read(ADDR_SCREEN))
    vm = strip_comments(read(ADDR_VM))
    repo = strip_comments(read(REPO))
    design = read(DESIGN)
    n_kt = len(list(AND.rglob("*.kt")))
    c.ok(f"整棵源码树扫到了 {n_kt} 个 .kt（下限 {MIN_KT_FILES}）", n_kt >= MIN_KT_FILES,
         "目录改名了？那样「一个删除都没配撤回」和「一个都没扫到」就是同一个输出")
    c.ok("AddressScreen.kt 读到了内容（≥ 20000 字符）", len(screen) >= 20000, f"实际 {len(screen)}")
    c.ok("AddressViewModel.kt 读到了内容（≥ 8000 字符）", len(vm) >= 8000, f"实际 {len(vm)}")

    # ── 1. 调用点清单自己算 ──────────────────────────────────────────────
    c.section("1. 删除调用点的清单（**算出来的**：扫 ui/ 下所有 repo.deleteX(）")
    sites = delete_sites()
    c.ok(f"扫到 {len(sites)} 个删除调用点（下限 {MIN_CALLS}）", len(sites) >= MIN_CALLS,
         "正则或目录被改坏了？清单缩水之后这一节会安静地全绿")
    unpaired: list[str] = []
    for rel, meth in sites:
        key = f"{rel}::{meth}"
        if key in EXEMPT or key in NAME_MISMATCH:
            continue
        src = strip_comments(read(AND / rel))
        want = "repo.restore" + meth[len("delete") :] + "("
        if want not in src:
            unpaired.append(f"{key} 缺 {want}")
    c.ok("每个删除调用点都有配对的还原调用（deleteX ↔ restoreX，同文件）", not unpaired,
         "这些删了就找不回来：" + "；".join(unpaired[:6]))

    # ── 2. 豁免表只能收紧 + 不许空转 ─────────────────────────────────────
    c.section("2. 豁免表：每条都必须**仍然成立**（修好了就得删行，不许留空转的豁免）")
    c.ok(f"豁免条数 {len(EXEMPT)} ≤ 上限 {EXEMPT_MAX}（这张表只能收紧）",
         len(EXEMPT) <= EXEMPT_MAX,
         "又欠了一笔？先想清楚是不是真要欠 —— 要加就同时把这个上限写下来")
    site_keys = {f"{rel}::{meth}" for rel, meth in sites}
    dead = [k for k in EXEMPT if k not in site_keys]
    c.ok("豁免表里每一条都还指向一个**真实存在**的删除调用点", not dead,
         f"这些已经不存在了：{dead} —— 删掉这些行")
    still_bad = []
    for key in EXEMPT:
        if key not in site_keys:
            continue
        rel, meth = key.split("::")
        src = strip_comments(read(AND / rel))
        if "repo.restore" + meth[len("delete") :] + "(" in src:
            still_bad.append(key)
    c.ok("豁免表里每一条都**仍然没有**配对的还原调用（修好了就该删这一行）", not still_bad,
         f"这些页已经补上撤回了，把行删掉：{still_bad}")
    c.ok("名字配不上的那一个（应付单）单独列出来，而不是塞进豁免表",
         all(k in site_keys for k in NAME_MISMATCH) and len(NAME_MISMATCH) == 1,
         "SupplierDetailScreen 的 deleteSupplierPayable ↔ restoreSupplierPayment 是一件事、两个名字")

    # ── 3. 本批这一页的撤回链路 ──────────────────────────────────────────
    c.section("3. 地址与联系人页：删了必须能当场撤回（本批 CHG-0015）")
    c.ok("AddressViewModel 有「刚删的那条」这个状态（recentlyDeleted）",
         "var recentlyDeleted by mutableStateOf<RecentlyDeleted?>(null)" in vm)
    c.ok("有 undoDelete() 这个动作", "fun undoDelete()" in vm)
    n_rec = len(re.findall(r"recentlyDeleted = RecentlyDeleted\(", vm))
    c.ok("三处删除都记了「刚删的那条」（线路 / 联系人 / 地点各一处）", n_rec == 3,
         f"实际 {n_rec} 处 —— 有一处删完不给人撤回路")
    rec, br = kinds_recorded(vm), kinds_branched(vm)
    c.ok(f"记下的 kind 集合 == undoDelete 的分支集合（各 {sorted(KINDS)}）",
         rec == set(KINDS) and br == set(KINDS),
         f"记下 {sorted(rec)}，分支 {sorted(br)} —— 多一个分支/少一个分支都是「撤不回来」")
    for meth in ("repo.restoreAddress(", "repo.restoreContact(", "repo.restoreLocation("):
        c.ok(f"undoDelete 真的调到 {meth}id)）", meth in vm)
    c.ok("仓库层三个还原接口都在（不是界面上凭空写的）",
         all(f"suspend fun restore{m}(" in repo for m in ("Address", "Contact", "Location")),
         "AppRepository 少了 restoreAddress / restoreContact / restoreLocation")

    # ── 4. 「手边」是个位置 ──────────────────────────────────────────────
    c.section("4. 撤回提示的位置（「手边」＝列表**上面**，不是页面末尾）")
    i_undo = screen.find("vm.undoDelete()")
    i_list = screen.find(LIST_ANCHOR)
    c.ok("页面上画了撤回入口（vm.recentlyDeleted?.let + TextButton(vm.undoDelete())）",
         "vm.recentlyDeleted?.let" in screen and i_undo > 0)
    c.ok("界面上写的是「撤销」（不是「撤回订单」那种另一个动作的词）", "Text(\"撤销\")" in screen)
    c.ok("提示画在列表容器**之前**（长列表里也在第一屏，不在屏幕外的末尾）",
         i_undo > 0 and i_list > 0 and i_undo < i_list,
         f"undoDelete 在 {i_undo}、列表容器在 {i_list} —— 提示跑到列表后面去了？")
    c.ok("提示与列表之间有分隔（它是**贴在内容上**的一行，不是浮在别处）",
         "HorizontalDivider(" in screen[i_undo : i_undo + 400] if i_undo > 0 else False)
    c.ok("规范里那条规矩还在（删除一律软删 + 手边要有撤回）",
         "删除一律软删" in design and "手边要有撤回" in design and "撤回" in design)

    # ── 5. 接线 ──────────────────────────────────────────────────────────
    c.section("5. 接线：反向验证在、文档九节、登记簿有 CHG-0015")
    c.ok("反向验证脚本在（_tools/qa/_reverse_verify_delete_undo.py）", REVERSE.exists(),
         "没有反向验证的判据＝没人证明它真的会红")
    doc = read(DOC) if DOC.exists() else ""
    c.ok("文档九节齐全（docs/changes/CHG-0015.md）",
         all(s in doc for s in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")),
         "文档缺节（_check_dev_spec.py 也会红）")
    c.ok("登记簿里有 CHG-0015 这一行（整行，不是一个链接里的字样）",
         bool(re.search(r"^\|\s*[\x60]?CHG-0015[\x60]?\s*\|", read(REGISTRY), re.M)),
         "没登记（别人不知道这个 ID 用掉了）")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：删除调用点清单是算出来的、豁免表只能收紧且每条都仍然成立、"
          f"地址与联系人页三处删除都能当场撤回、提示画在列表上面。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（删了要能当场撤回 CHG-0015）==")
        print("1. 调用点清单自己算：扫 ui/ 下所有 repo.deleteX(，要求同文件出现 repo.restoreX(")
        print("2. 豁免表 EXEMPT 只能收紧 + 每条都必须仍然存在、仍然没有配对还原（不许空转）")
        print("3. 地址与联系人页：三处删除都记「刚删的那条」、kind 集合 == undoDelete 的 when 分支集合")
        print("4. 「手边」是个位置：提示画在列表容器之前（长列表里也在第一屏）")
        print("5. 接线：反向验证脚本在、仓库层三个 restore* 在、规范那条规矩在、文档九节、登记簿有 CHG-0015")
        sys.exit(0)
    sys.exit(main())
