"""反向验证：把 BUG-0014 那条判据逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这条规矩坏掉的方式**全部不报错**——
把 `highlight` 改回 `vm.tab` 只是"闪一下错的样式"，数据一个字没错；
把渲染门删掉只是又看得到上一栏的单；把"必须相邻"的注释删掉，下一轮就没人知道为什么这两句要挨着。
机器判据本身也有一半是"扫全仓"（不许再出现 `highlight = vm.tab`），
这种清单如果不验证，就可能因为"目录扫不到"而永远绿。

用法：python _tools/qa/_reverse_verify_driver_tab_highlight.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_driver_tab_highlight.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
VM = AND / "ui/driver/DriverOrdersViewModel.kt"
SCREEN = AND / "ui/driver/DriverOrdersScreen.kt"
CARD = AND / "ui/common/OrderCard.kt"
DRIVER_DIR = AND / "ui/driver"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "把高亮改回『用户想看的 tab』（就是用户报的那个闪）",
        SCREEN,
        "highlight = vm.ordersTab == 0",
        "highlight = vm.tab == 0",
        "没有任何一处按 vm.tab 算高亮",
    ),
    (
        "删掉『数据不是这一栏』那道渲染门（切过去先看到上一栏的单）",
        SCREEN,
        "                vm.ordersTab != vm.tab -> LoadingBox()\n",
        "",
        "渲染门有『不是这一栏",
    ),
    (
        "把那道门挪到 error 之前（取数失败时用户只看到转圈，永远看不到失败）",
        SCREEN,
        "                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })\n",
        "                vm.ordersTab != vm.tab -> LoadingBox()\n"
        "                vm.error != null -> ErrorView(vm.error.orEmpty(), onRetry = { vm.load() })\n",
        "新那一档排在 error",
    ),
    (
        "删掉 Screen 里『这一档为什么必须排在 error 之后』的指路",
        SCREEN,
        "（2026-10-06，BUG-0014）",
        "（2026-10-06）",
        "Screen 也留了",
    ),
    (
        "VM 干脆不记『画的是哪一栏』（只剩用户想看的 tab）",
        VM,
        "    var ordersTab by mutableStateOf(0)\n        private set\n",
        "",
        "有 ordersTab（private set）",
    ),
    (
        "把 ordersTab 放开成可写（谁都能从外面改 → 两半又不同步）",
        VM,
        "    var ordersTab by mutableStateOf(0)\n        private set",
        "    var ordersTab by mutableStateOf(0)",
        "有 ordersTab（private set）",
    ),
    (
        "把 wanted 换成 tab（取数中途切栏 → 拿回来记成新栏）",
        VM,
        "val statuses = if (wanted == 0)",
        "val statuses = if (tab == 0)",
        "状态清单取自 wanted（不是 tab）",
    ),
    (
        "把 val wanted = tab 挪进 launch（捕获发生在挂起点之后）",
        VM,
        "        val wanted = tab\n        loadJob = viewModelScope.launch {\n",
        "        loadJob = viewModelScope.launch {\n            val wanted = tab\n",
        "load() 里在 launch **之前**捕获",
    ),
    (
        "把 orders 与 ordersTab 两句拆开（数据是新的、栏位是旧的）",
        VM,
        "                orders = fetched\n                ordersTab = wanted\n",
        "                ordersTab = wanted\n                orders = fetched\n",
        "orders = fetched 与 ordersTab = wanted **相邻**",
    ),
    (
        "删掉『这两句必须相邻』的理由（下一轮会有人拆开）",
        VM,
        "这两句**必须相邻**",
        "这两句要一起改",
        "注释里点了『必须相邻』的理由",
    ),
    (
        "删掉 KDoc 里『想看哪一栏 vs 画的是哪一栏』的说明（两个状态又要被当成一个）",
        VM,
        "用户**想看**哪一栏",
        "用户当前是哪一栏",
        "注释里说清它与 tab 是两件事",
    ),
    (
        "把卡片的 highlight 呈现改掉（红/大号那档没了）",
        CARD,
        "if (highlight) Color(DangerRed) else Color(ProductPurple)",
        "Color(ProductPurple)",
        "highlight=true → 红；false → 紫",
    ),
    (
        "把字号那一档也压平（这一条与颜色无关，但同一行的呈现一起被验）",
        CARD,
        "if (highlight) MaterialTheme.typography.titleLarge else MaterialTheme.typography.titleMedium",
        "MaterialTheme.typography.titleMedium",
        "highlight=true → 大号",
    ),
]

#: 需要**新建文件**的注入（判据 4 的清单是扫目录算出来的，得证明它真的会数到新文件）
CREATIONS = [
    (
        "司机端新增一个按 vm.tab 算高亮的页面（清单自己算 → 必须点名它）",
        DRIVER_DIR / "_LeakTabScreen.kt",
        "package com.tapmoay.sorders.ui.driver\n\n"
        "internal class LeakVm { var tab = 0 }\n\n"
        "internal fun leak(vm: LeakVm): Boolean {\n"
        "    val highlight = vm.tab == 0\n"
        "    return highlight\n"
        "}\n",
        "没有任何一处按 vm.tab 算高亮",
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

    for label, path, content, expect in CREATIONS:
        if path.exists():
            print(f"  [SKIP] {label} —— 路径已存在：{path.name}")
            bad += 1
            continue
        path.write_bytes(content.encode("utf-8"))
        try:
            hit, detail = verdict(expect)
        finally:
            path.unlink(missing_ok=True)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + len(CREATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
