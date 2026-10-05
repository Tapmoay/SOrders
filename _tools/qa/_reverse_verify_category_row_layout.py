"""反向验证：把 CHG-0046 那条判据（_check_category_row_layout.py）逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这条规矩坏掉的方式**全部不报错**——
- 名字少了 overflow = Ellipsis 只是"硬切半个字"，不崩、不红；
- 名字少了 fillMaxWidth() 只是"去吃兄弟的宽度"（这条恰好是 _check_adaptive_layout.py 的存量基线在管）；
- 把 ↑↓ 两颗 IconButton 加回来只是"又挤了"，界面照样能用；
- 顶栏返回改回 onClick = onBack 甚至**看上去更简单**（少一层）；
- 拖动那套少了 key(c.id) 的表现是"拖了半天只挪一格就自己松手"；
- 提交时不先本地换位、或让旧响应覆盖新顺序，表现只是"拖完跳一下"。

机器判据本身也有一半是"读源码里有没有那一行"，这种判据如果不反向验证，
就可能因为名字改了、文件搬了、正则写松了而**永远绿**。

用法：python _tools/qa/_reverse_verify_category_row_layout.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_category_row_layout.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DISP = AND / "ui/dispatcher"
C = DISP / "ContactCategoriesScreen.kt"
RT = DISP / "RouteCategoriesScreen.kt"
PL = DISP / "PlaceCategoriesScreen.kt"
VMC = DISP / "ContactCategoriesViewModel.kt"
VMR = DISP / "RouteCategoriesViewModel.kt"
VMP = DISP / "PlaceCategoriesViewModel.kt"
ADDR = AND / "ui/shipper/AddressScreen.kt"
CREATE = AND / "ui/shipper/OrderCreateScreen.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "把名字的省略号去掉（退回『硬切半个字』）",
        C,
        "                        overflow = TextOverflow.Ellipsis,\n",
        "",
        "名字**带省略号**",
    ),
    (
        "把名字的 fillMaxWidth 去掉（省略号文本会去吃兄弟的宽度）",
        RT,
        "                        modifier = Modifier.fillMaxWidth(),\n",
        "",
        "名字显式占满这一列",
    ),
    (
        "把 ↑ 上移按钮加回来（用户点名的『不要用那个按钮排序』）",
        PL,
        "                Icon(\n                    Icons.Default.DragHandle,\n",
        "                IconButton(onClick = {}) { Icon(Icons.Default.KeyboardArrowUp, \"上移\") }\n"
        "                Icon(\n                    Icons.Default.DragHandle,\n",
        "行里不再有 ↑↓ 按钮",
    ),
    (
        "拖动时不 consume（父级滚动会跟着一起动）",
        C,
        "                                change.consume()\n",
        "",
        "拖动时 consume",
    ),
    (
        "位移不再换算格数（改成永远挪一格）",
        C,
        "                            val steps = dragSteps(dragOffset, rowHeightPx)\n",
        "                            val steps = 1\n",
        "位移靠 dragSteps 换算",
    ),
    (
        "拖动结果改交给 moveTo（丢掉『挪几格』的语义）",
        C,
        "                                vm.moveBy(c.id, steps)\n",
        "                                vm.moveTo(c.id, 1)\n",
        "拖动结果交给 vm.moveBy",
    ),
    (
        "把每行的稳定 key 去掉（拖动会被手势取消）",
        C,
        "                    key(c.id) {\n",
        "                    run {\n",
        "每行有稳定 key(c.id)",
    ),
    (
        "列表换回 LazyColumn（item 复用 → 位移换算变成靠测量）",
        C,
        "            else -> Column(\n"
        "                Modifier.fillMaxWidth()\n"
        "                    .weight(1f, fill = false)\n"
        "                    .heightIn(max = 460.dp)\n"
        "                    .verticalScroll(rememberScrollState())\n",
        "            else -> LazyColumn(\n"
        "                Modifier.fillMaxWidth()\n"
        "                    .weight(1f, fill = false)\n"
        "                    .heightIn(max = 460.dp)\n",
        "列表**不是** LazyColumn",
    ),
    (
        "面板无条件画自己的返回（又变成两颗返回互相误解）",
        C,
        "            if (onBack != null) {\n",
        "            if (true) {\n",
        "只有宿主点名了才画",
    ),
    (
        "面板 fun 收成 private（判据与文档都点名它是 public 的）",
        C,
        "fun ContactCategoriesPanel(\n",
        "private fun ContactCategoriesPanel(\n",
        "面板 fun ContactCategoriesPanel( 仍是 public",
    ),
    (
        "提交前不先本地换位（手指走了卡片还在原地）",
        VMC,
        "        rows = next\n",
        "",
        "拖动先本地换位",
    ),
    (
        "成功响应无条件覆盖（旧响应盖掉新顺序）",
        VMC,
        "            if (seq == submitSeq) rows = fresh\n",
        "            rows = fresh\n",
        "旧响应不许覆盖新顺序（成功那支）",
    ),
    (
        "失败那支也不看提交编号（旧失败把新顺序整份读回来）",
        VMP,
        "            if (seq == submitSeq) load()\n",
        "            load()\n",
        "旧响应不许覆盖新顺序（失败那支）",
    ),
    (
        "把 moveBy 的签名改掉（拖动没有落点）",
        VMR,
        "    fun moveBy(id: Long, steps: Int) {\n",
        "    fun moveBy(id: Long, steps: Int, unused: Int = 0) {\n",
        "VM 有 moveBy(id, steps)",
    ),
    (
        "把旧的『按格挪』接口加回来（退回 ↑↓ 那一套）",
        VMP,
        "    fun moveBy(id: Long, steps: Int) {\n",
        "    fun move(index: Int, delta: Int) {\n"
        "        if (delta == 0) return\n"
        "        submit(rows)\n"
        "    }\n\n"
        "    fun moveBy(id: Long, steps: Int) {\n",
        "旧的『按格挪』接口已退役",
    ),
    (
        "系统返回键接管条件放宽到『面板开着』（抽屉那一种被抢走）",
        ADDR,
        "    BackHandler(enabled = managingCategory && !drawer.isOpen) { leaveCategoryPanel() }\n",
        "    BackHandler(enabled = managingCategory) { leaveCategoryPanel() }\n",
        "系统返回键只在",
    ),
    (
        "顶栏返回改回直连退页（就是用户报的那个『直接退出了』）",
        ADDR,
        "IconButton(onClick = { backOneLevel() })",
        "IconButton(onClick = onBack)",
        "顶栏那颗返回走 backOneLevel",
    ),
    (
        "backOneLevel 少一层（面板开着时跳过它直接退页）",
        ADDR,
        "        } else if (managingCategory) {\n            leaveCategoryPanel()\n        } else {\n",
        "        } else {\n",
        "backOneLevel：面板开着",
    ),
    (
        "地址页的面板调用点又把 onBack 点上（两颗返回又回来了）",
        ADDR,
        "ContactCategoriesPanel(vm = catVm)",
        "ContactCategoriesPanel(vm = catVm, onBack = leaveCategoryPanel)",
        "地址页的面板调用点不点 onBack",
    ),
    (
        "下单页的地点抽屉不再点名 onBack（那里没有顶栏 → 用户卡在面板里）",
        CREATE,
        "                PlaceCategoriesPanel(\n                    vm = catVm,\n                    onBack = {\n",
        "                PlaceCategoriesPanel(\n                    vm = catVm,\n",
        "下单页的地点抽屉**仍然点名** onBack",
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
