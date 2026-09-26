"""反向验证：把「分组一律白卡」那条规范逐条弄坏，看它**真的会红**。

## 为什么这条必须反向验证
"又写一个 `OutlinedTextField`"**从来不报错**：编译过、真机上看着"也能用"，
只是那一页又变回"一堆矩形框浮在灰底上"。这条规范是靠**人肉翻页面**才会发现的，
所以每一条判据都要被证明"改坏了会红"，否则它就是一段好听的散文。

用法：python _tools/qa/_reverse_verify_form_panel.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CHECK = HERE / "_check_form_panel_style.py"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"

ROWS = AND / "ui/common/FormRows.kt"
ADDR = AND / "ui/shipper/AddressScreen.kt"
CREATE = AND / "ui/shipper/OrderCreateScreen.kt"
FORM = AND / "ui/dispatcher/ProductFormScreen.kt"
AMAP = AND / "ui/common/AmapPicker.kt"
LEDGER_HOME = AND / "ui/dispatcher/LedgerHomeScreen.kt"
BASELINE = HERE / "_form_panel_baseline.txt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "「新增线路」又写回一个描边输入框（那一屏「乱」的根因）",
        ADDR,
        "                FormGroup(icon = Icons.Default.Route, title = \"起点（可选，从这出发）\", tint = Color(InventoryTeal)) {",
        "                androidx.compose.material3.OutlinedTextField(value = \"\", onValueChange = {})\n"
        "                FormGroup(icon = Icons.Default.Route, title = \"起点（可选，从这出发）\", tint = Color(InventoryTeal)) {",
        "一个描边输入框都没有",
    ),
    (
        "长文本那一行被删掉（地址就只剩「标签在左、值在右」，一行几个字）",
        ROWS,
        "fun FormTextAreaRow(",
        "private fun FormTextAreaRowX(",
        "FormTextAreaRow 只有一处定义",
    ),
    (
        "「点进去做一件事」那一行被抄进页面（第二份实现）",
        CREATE,
        "@Composable\nprivate fun EditPlaceDialog(",
        "private fun FormActionRow(label: String, onClick: () -> Unit) {}\n\n"
        "@Composable\nprivate fun EditPlaceDialog(",
        "FormActionRow 只有一处定义",
    ),
    (
        "页面不再走某一种共用行（把它换成自己写的那一行）",
        FORM,
        "                    FormSwitchRow(\n                        label = \"上架销售\",",
        "                    LeakedOwnSwitch(\n                        label = \"上架销售\",",
        "每一种共用行都还在用",
    ),
    (
        "别处又冒出一个描边输入框（总数涨了 → 基线拦下）",
        LEDGER_HOME,
        "fun LedgerHomeScreen(",
        "private val LeakedField = { androidx.compose.material3.OutlinedTextField() }\n\n"
        "fun LedgerHomeScreen(",
        "总数没有涨",
    ),
    # ⚠️ 原来这里还有一条「悄悄改好了一页却没降基线」的注入。它**被删掉了**：
    #    那个判据从"报红"改成了"只提示"（这个仓库同时有好几个会话在改，别人顺手清理一页
    #    就会让"基线没跟着降"变红 —— 那种红不是任何人的错，红几次大家就把检查关掉了）。
    #    现在硬判据只有"只许减不许增"，它的注入在下面那一条里。
    (
        "把规范从设计系统里删掉（下一个人还会用描边框当分组）",
        DOC,
        "### 5.0 ⛔ **分组一律白卡，不许用描边框当分组**",
        "### 5.0 ⛔ 历史上有人试过用白卡：",
        "设计规范里写着这条",
    ),
]

#: 「文件被搬走」这类注入：把必需文件改名，跑完再改回来（判据里有"文件都在"那一条兜底）
MOVES = [
    (
        "把共用行那个文件整个搬走（判据清单要能发现少了文件）",
        ROWS,
        "只有一处定义",
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


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    # ⚠️ 先把基线**收紧**到当前实数再开跑：基线是个**上限**，
    #    别人刚清理过几处时会留下"余量"，注入一处就顶不破它 ——
    #    那样这条反向验证会假绿（实测踩过：基线 70、实际 67，注入 1 处 = 68 仍然绿）。
    #    跑完**原样还原**（连着文件里的注释一起）。
    base_backup = BASELINE.read_bytes() if BASELINE.exists() else None
    subprocess.run(
        [sys.executable, str(CHECK), "--update"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        return _run(bad)
    finally:
        if base_backup is not None:
            BASELINE.write_bytes(base_backup)


def _run(bad: int) -> int:
    code, out = run_check()
    if code != 0:
        print(f"[X] 前提不成立：源码完好时这条规范是绿的\n{out[-1200:]}")
        return 1
    print("[ok] 前提：源码完好时这条规范是绿的")

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

    for label, path, expect in MOVES:
        src, crlf = read_src(path)
        moved = path.with_suffix(path.suffix + ".rv-moved")
        path.rename(moved)
        try:
            hit, detail = verdict(expect)
        finally:
            moved.rename(path)
            write_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后规范全绿" if ok else "  [MISS] 还原后规范没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + len(MOVES) + 1
    print()
    if bad:
        print(f"[X] {bad}/{total} 条不成立（判据对它们不敏感）")
        return 1
    print(f"[ok] {total}/{total} 全部成立：每条注入都让判据点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
