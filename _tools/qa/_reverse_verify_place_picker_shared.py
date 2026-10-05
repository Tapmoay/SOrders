"""反向验证：把 CHG-0047 那条判据（_check_place_picker_shared.py）逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这条规矩坏掉的方式**全部不报错**——
- 把弹层收成 private、或者再复制一份改改，编译照样过、两个入口照样能用（只是从此要改两处）；
- 标题写死回「选择收货地址」只是"起点 / 终点那两处标题变成错的"，界面不崩；
- onAddLocation 画到共享地点段、或者下单页也传上它，只是"给全库共用的一张表开了个行内新增口"；
- 宿主挪进表单抽屉里，只是"两层弹层叠在一起，点空白处关哪个说不清"；
- 面板少了 SnackbarHost / OneShotSnackbar 就退回改动前那副样子：建了 / 改了 / 删了分类界面
  一点回声都没有（这正是台账 L-11 报的现象）；
- 壳与体合并、或者壳里又留一份布局，也只是"多一层 / 多一份"，不会红。

机器判据本身几乎全是"读源码里有没有那一行"，这种判据如果不反向验证，就可能因为名字改了、
文件搬了、正则写松了而**永远绿**。

用法：python _tools/qa/_reverse_verify_place_picker_shared.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_place_picker_shared.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CREATE = AND / "ui/shipper/OrderCreateScreen.kt"
ADDR = AND / "ui/shipper/AddressScreen.kt"
VM = AND / "ui/shipper/AddressViewModel.kt"
CP = AND / "ui/dispatcher/ContactCategoriesScreen.kt"
RP = AND / "ui/dispatcher/RouteCategoriesScreen.kt"
PP = AND / "ui/dispatcher/PlaceCategoriesScreen.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "把共用的弹层收成 private（另一页就跨文件用不到了）",
        CREATE,
        "fun AddressPickerSheet(\n",
        "private fun AddressPickerSheet(\n",
        "弹层不再是 private",
    ),
    (
        "给 title 加个默认值（调用方就能忘了点名，界面悄悄退回旧标题）",
        CREATE,
        '    title: String,\n    addresses: List<AddressDto>,\n',
        '    title: String = "选择收货地址",\n    addresses: List<AddressDto>,\n',
        "title 没有默认值",
    ),
    (
        "抽屉体里把标题写死回「选择收货地址」（起点 / 终点那两处就都成了错标题）",
        CREATE,
        '            Text(\n                title,\n                style = MaterialTheme.typography.titleLarge,\n',
        '            Text(\n                "选择收货地址",\n                style = MaterialTheme.typography.titleLarge,\n',
        "抽屉体里不再出现写死的旧标题",
    ),
    (
        "「＋ 新增地点」不再判 null（下单页也会长出一格它没有的新增入口）",
        CREATE,
        "            if (onAddLocation != null) {\n",
        "            if (true) {\n",
        "null 时整格不画",
    ),
    (
        "共享地点段里也用上 onAddLocation（全库共用的一张表被开了行内新增口）",
        CREATE,
        '                        else -> if (places.isEmpty()) {\n',
        '                        else -> if (places.isEmpty()) {\n                            onAddLocation?.invoke()\n',
        "共享地点段里一个 onAddLocation 都没有",
    ),
    (
        "下单页也传上 onAddLocation（它那条路不存在，等于凭空多个入口）",
        CREATE,
        '            title = "选择收货地址",\n',
        '            title = "选择收货地址",\n            onAddLocation = {},\n',
        "下单页**没传** onAddLocation",
    ),
    (
        "起点入口不再先拉共享地点（抽屉里那一页永远是空的）",
        ADDR,
        'onClick = { vm.loadPlaces(); locPickerTarget = "origin" },\n',
        'onClick = { locPickerTarget = "origin" },\n',
        "起点入口：先拉一次共享地点",
    ),
    (
        "终点入口换了另一个目标值（与宿主的 asOrigin 判定对不上）",
        ADDR,
        'locPickerTarget = "dest"',
        'locPickerTarget = "destination"',
        "终点入口：同一条路",
    ),
    (
        "把宿主缩进进去（画进表单抽屉里：两层弹层叠一起）",
        ADDR,
        "    locPickerTarget?.let { target ->\n",
        "        locPickerTarget?.let { target ->\n",
        "宿主画在页面顶层",
    ),
    (
        "旧的「从地点库选」下拉菜单又回来了（startLocMenu）",
        ADDR,
        "var locPickerTarget by remember { mutableStateOf<String?>(null) }\n",
        "var startLocMenu by remember { mutableStateOf(false) }\n"
        "    var locPickerTarget by remember { mutableStateOf<String?>(null) }\n",
        "startLocMenu",
    ),
    (
        "起点 / 终点各开一个宿主（第二处 AddressPickerSheet 调用）",
        ADDR,
        "            onDismiss = { locPickerTarget = null },\n",
        "            onDismiss = { locPickerTarget = null },\n        )\n        AddressPickerSheet(\n",
        "这一页只有一处 AddressPickerSheet 调用",
    ),
    (
        "点「＋ 新增地点」时先开新建、后关弹层（两层叠在一起）",
        ADDR,
        '            onAddLocation = {\n                locPickerTarget = null\n'
        '                vm.openLocationCreate(if (asOrigin) "start" else "end")\n            },\n',
        '            onAddLocation = {\n                vm.openLocationCreate(if (asOrigin) "start" else "end")\n'
        '                locPickerTarget = null\n            },\n',
        "关弹层是这一支的**第一句**",
    ),
    (
        "loadPlaces 不再读截断标记（共享库一页装不下时界面不说）",
        VM,
        "                placesTruncated = page.meta.hasMore\n",
        "",
        "截断标记来自响应头",
    ),
    (
        "线路没写起点时也不吭声（悄悄什么都不填，用户不知道点了没反应）",
        VM,
        '                formError = "这条线路没写起点（只送到终点），改选一个地点，或先编辑这条线路补上起点"\n',
        "                formError = null\n",
        "线路没写起点时说清理由",
    ),
    (
        "挑共享地点不再记账（后端收进「我的地点」那一步永远不触发）",
        VM,
        "container.repo.usePlace(p.id)",
        "container.repo.usePlace(p.name.hashCode().toLong())",
        "用过的共享地点要记一次账",
    ),
    (
        "管理权不再看角色（人人是派单员：全库共用的一张表人人可改）",
        VM,
        "                canManageSharedPlaces = isDispatcher\n",
        "                canManageSharedPlaces = true\n",
        "canManageSharedPlaces 用的就是它",
    ),
    (
        "reloadAddressLibrary 少拉一份名册（改过分组回来那一格还是旧的）",
        VM,
        "        viewModelScope.launch { try { addresses = container.repo.addresses() } catch (_: Exception) {} }\n",
        "",
        "它重拉线路名册",
    ),
    (
        "联系人面板不再接 VM 的回执（L-11 报的就是这个：建了分类一点提示都没有）",
        CP,
        "    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })\n",
        "",
        "联系人：把 VM 的回执接上",
    ),
    (
        "线路面板不再画 SnackbarHost（回执接了却没地方显示）",
        RP,
        "        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter))\n",
        "",
        "线路：提示条沉在底部",
    ),
    (
        "地点面板的 onBack 改成必填（宿主不点名就编译不过 = 面板又变成自己画返回）",
        PP,
        "    onBack: (() -> Unit)? = null,\n",
        "    onBack: (() -> Unit)?,\n",
        "地点：宿主不点名时仍可不传 onBack",
    ),
    (
        "面板壳里又留一份布局（说是抽壳，其实函数体没搬走）",
        CP,
        "fun ContactCategoriesPanel(\n    vm: ContactCategoriesViewModel,\n",
        "fun ContactCategoriesPanel(\n    vm: ContactCategoriesViewModel,\n    unusedPlaceholder: Any? = CATEGORY_ROW_HEIGHT,\n",
        "联系人：壳里**没有**原来的布局",
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
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
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
