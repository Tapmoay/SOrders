"""反向验证：把「开销管理」那条红线的判据逐条弄坏，看它**真的会红**。

为什么这块要反向验证：这一整块改的是**版式与"突出什么"的口径**，坏掉的方式全都"不报错、不崩"：
新增表单又内嵌回列表、左栏自己画一遍、时间控件变回胶囊、**卡片按分类名硬判**（用户新加分类就失效）、
卡片上金额出现两次、订单来源在详情里看不到、改名不级联。这些只有机器判据能拦住，
而"判据本身是不是在检查"只能靠注入法证明。

用法：python _tools/qa/_reverse_verify_expense_page.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_expense_page.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND / "ui/dispatcher/ExpensesScreen.kt"
CREATE = AND / "ui/dispatcher/ExpenseCreateScreen.kt"
CATS = AND / "ui/dispatcher/ExpenseCategoriesScreen.kt"
LINK = AND / "core/ExpenseLink.kt"
NAVGRAPH = AND / "ui/nav/NavGraph.kt"
API = ROOT / "backend/app/api/v1/expense_categories.py"
CAT_ORDER = ROOT / "backend/app/services/category_order.py"
MODEL = ROOT / "backend/app/models/expense.py"
#: 共用组件（`DateFilterDialogs` 那份"两个弹层 + 状态机"住在它里面）
COMPONENTS = AND / "ui/common/Components.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "新增表单又内嵌回列表页（用户选的是单独一页）",
        SCREEN,
        "    val snackbar = remember { SnackbarHostState() }\n    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })",
        "    val snackbar = remember { SnackbarHostState() }\n"
        "    val leak = ExpenseCreateRequest(\"2026-09-20\", \"加油\", \"1\")\n"
        "    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })",
        "列表页**不再内嵌**新增表单",
    ),
    (
        "左栏自己画一遍（不用共用的 CategoryRail）",
        SCREEN,
        "            CategoryRail(\n",
        "            androidx.compose.foundation.lazy.LazyColumn { }\n",
        "左栏走**共用**的分类栏",
    ),
    (
        "时间控件变回那一行胶囊（用户点名要药丸）",
        SCREEN,
        "                    DatePresetPill(label = vm.periodWord(), onClick = { vm.showDatePresets = true })",
        "                    DatePresetRow(selected = vm.preset, customFrom = null, customTo = null, onPick = { })",
        "右上角是**时间药丸**",
    ),
    (
        "卡片按分类名硬判该突出什么（用户新加一个分类就失效）",
        SCREEN,
        "    val primary = ExpenseLink.primary(e)",
        "    val primary = if (e.category == \"加油\") ExpenseLink.primary(e) else null",
        "**不许**按分类名硬判",
    ),
    (
        "卡片上金额又出现两次（同一屏两个数）",
        SCREEN,
        "        Spacer(Modifier.height(6.dp))\n        Row(verticalAlignment = Alignment.CenterVertically) {",
        "        Text(\"¥\" + formatMoney(e.amount))\n"
        "        Spacer(Modifier.height(6.dp))\n        Row(verticalAlignment = Alignment.CenterVertically) {",
        "卡片上金额只渲染一次",
    ),
    (
        "详情里看不到订单来源（用户要求点详情能看这笔从哪一单来）",
        SCREEN,
        '                DetailRow("关联订单", e.orderNo?.ifBlank { null } ?: "（不是从订单来的）")',
        "",
        "详情里能看到**订单来源**",
    ),
    (
        "突出项的兜底顺序被拆掉（分类说车辆但没填车就什么都不显示）",
        LINK,
        "            VEHICLE -> listOf(VEHICLE, DRIVER, ORDER)",
        "            VEHICLE -> listOf(VEHICLE)",
        "突出项有兜底顺序",
    ),
    (
        "改名不再级联（挂着的开销变成孤儿）",
        API,
        "        moved = db.execute(\n"
        "            Expense.__table__.update().where(Expense.category == old_name).values(category=body.name)\n"
        "        ).rowcount",
        "        moved = 0",
        "改名会级联",
    ),
    (
        "还有开销挂着的分类也能删（悄悄把那些开销丢出名册）",
        API,
        "    if used:\n"
        "        raise HTTPException(\n"
        "            status_code=400,\n"
        '            detail=f"还有 {used} 笔开销挂在这个分类下，先把它们改成别的分类（或改个名）再删",\n'
        "        )\n",
        "",
        "删除还有开销挂着的分类",
    ),
    (
        "分类改回枚举列（写一个新分类进去，读接口 500）",
        MODEL,
        "    category: Mapped[str] = mapped_column(String(32), index=True)",
        "    category: Mapped[str] = mapped_column(String(16), index=True)",
        "是自由字符串",
    ),
    (
        "新增页的入口没接线（点了没反应）",
        NAVGRAPH,
        "                onCreate = { navController.navigate(Routes.EXPENSE_CREATE) },\n",
        "",
        "列表页的按钮去新增页",
    ),
    (
        # ⚠️ 2026-09-23 静态审计抓到这条**两头都腐烂了**（锚点 + 期望文案）：
        #    排序的草稿状态机后来收进了 `ui/common/CategoryRosterViewModel.kt`，
        #    这一页里那句 `val next = moveItemTo(...)` 早就不在页面上了 ——
        #    而判据也跟着改成了「这一页真的用了共用内核」（不再钉页面里的写法）。
        #    所以注入改成"不再继承共用内核、自己写第二套状态机"，期望文案同步成现在那条。
        "分类管理页不再复用共用内核（自己写第二套状态机）",
        CATS,
        "class ExpenseCategoriesViewModel(container: AppContainer) :\n"
        "    CategoryRosterViewModel<ExpenseCategoryDto>(container) {",
        "class ExpenseCategoriesViewModel(container: AppContainer) :\n"
        "    ViewModel() {",
        "排序与提交都交给共用内核",
    ),
    (
        "排序不再走共用校验（端点自己拼一遍 ids，收口白做）",
        API,
        "    ids = ordered_ids(by_id, body.ids)",
        "    ids = list(body.ids)",
        "排序走共用的「整份顺序」校验",
    ),
    (
        "共用校验里「少传了也要拒绝」这一条被删掉（只传一部分就静默错位）",
        CAT_ORDER,
        "    missing = [i for i in by_id if i not in set(ids)]\n"
        "    if missing:\n"
        '        names = "、".join(by_id[i].name for i in missing[:5])\n'
        "        raise HTTPException(\n"
        "            status_code=400,\n"
        '            detail=f"顺序里少了 {len(missing)} 个分类（{names}…）。请提交**完整**的分类顺序。",\n'
        "        )\n",
        "",
        "「整份顺序」的判据只有一份",
    ),
    # ---- 2026-09-21 精简轮：两个弹层的接线收进共用 host 之后，锚点搬到那儿 ----
    (
        "开销页不再走共用的 DateFilterDialogs（自己又抄一遍两个弹层）",
        SCREEN,
        "    DateFilterDialogs(\n",
        "    DatePresetDialog(\n",
        "药丸点开是档位清单（走共用的 DateFilterDialogs）",
    ),
    (
        "共用的 host 里两个弹层被拿走（页面调了它，但它什么都不画）",
        COMPONENTS,
        "fun DateFilterDialogs(\n",
        "fun DateFilterDialogsRenamed(\n",
        "那份 host 里确实开着档位清单",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out



def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**（R3-07b）：写回后**重新读回来逐字节比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是（L2 要的就是这一句）。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这一节红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            code, out = run_check()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            hit = code != 0 and any(expect in ln for ln in fails)
            detail = f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")
        finally:
            restore_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
