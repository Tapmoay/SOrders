"""反向验证：把「输入被静默改掉 / 一个数两个口径」这条红线逐条弄坏，看它**真的会红**（BUG-0028）。

## 为什么这块必须反向验证
本单收的三条（TA-08 / TA-09 / TA-10）有同一个脾气：**不报错**。
把负数悄悄吃成正数、把 `abc` 悄悄清空、把 `0.005` 印成 `0.01` —— 编译过、测试过、真机上看着也"正常"，
只有用户自己发现。所以判据必须被证明"改坏了会红"，否则它只是一段自我感觉良好的文字。

注入点刻意选在**别的检查不看的地方**（本单自己的新字面量），每条只弄坏一件事。

用法：python _tools/qa/_reverse_verify_basicdata_input_guard.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_basicdata_input_guard.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
TESTD = ROOT / "android/app/src/test/java/com/tapmoay/sorders"
KIT = AND / "ui/common/ProductCardKit.kt"
LIST = AND / "ui/dispatcher/ProductsScreen.kt"
RULES = AND / "core/InputRules.kt"
VM = AND / "ui/shipper/AddressViewModel.kt"
SCR = AND / "ui/shipper/AddressScreen.kt"
KIT_TEST = TESTD / "ui/common/ProductCardKitTest.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "TA-08：商品卡的售价换回 formatMoney（0.005 又被印成 0.01，真值两倍）",
        KIT,
        'trimMoneyZeros(price).takeIf { it.toDoubleOrNull() != null } ?: "0"',
        "formatMoney(price)",
        "商品卡的售价",
    ),
    (
        "TA-08：改价弹窗的预填换成 formatMoney（同一个数又变成两个答案）",
        LIST,
        "trimMoneyZeros(p.defaultUnitPrice)",
        "formatMoney(p.defaultUnitPrice)",
        "预填仍走",
    ),
    (
        "TA-08：把卡片上「为什么不能用 formatMoney」那句理由删掉（下一个人会顺手换回去）",
        KIT,
        "**单价是 `Numeric(14,4)`，显示必须保到四位**",
        "单价显示保到四位",
        "写着为什么不能用",
    ),
    (
        "TA-09：改价框退回那个静默一行（price = InputRules.priceInput(it)）",
        LIST,
        """                    onValueChange = { raw ->
                        val next = InputRules.priceInput(raw)
                        val note = InputRules.priceRewriteNote(raw)
                        priceNote = note
                        price = if (note == null) next else raw
                    },""",
        "                    onValueChange = { price = InputRules.priceInput(it) },",
        "静默一行",
    ),
    (
        "TA-09：确定键不再被说明挡住（负数又能存了）",
        LIST,
        "enabled = !busy && priceNote == null && price.toDoubleOrNull() != null,",
        "enabled = !busy && price.toDoubleOrNull() != null,",
        "确定键被禁用",
    ),
    (
        "TA-09：说明算出来了却不画给用户看（红字那一段被删）",
        LIST,
        "                if (priceNote != null) {",
        "                if (false) {",
        "框下画红字",
    ),
    (
        "TA-09：有说明时当场把框里的字换成另一个数（正是原来那个病）",
        LIST,
        "price = if (note == null) next else raw",
        "price = next",
        "保留用户打的字",
    ),
    (
        "TA-09：把「售价不能是负数」的文案磨成一句没信息量的「不合法」",
        RULES,
        '"售价不能是负数 —— 负号打不进去，照这样存下去会变成正数 $value"',
        '"售价不合法"',
        "note 文案点出了三件事",
    ),
    (
        "TA-10：联系人电话栏退回那个静默一行（abc 又被清空且不说）",
        SCR,
        """                        onValueChange = {
                            vm.contactPhone = InputRules.phoneInput(it)
                            vm.contactPhoneNote = InputRules.phoneInputNote(it)
                        },""",
        "                        onValueChange = { vm.contactPhone = InputRules.phoneInput(it) },",
        "联系人电话栏",
    ),
    (
        "TA-10：saveContact 里丢了字还照样保存（把 return 拿掉，只提示不拦）",
        VM,
        "        contactPhoneNote?.let {\n            formError = it\n            return\n        }",
        "        contactPhoneNote?.let {\n            formError = it\n        }",
        "return 才拦得住保存",
    ),
    (
        "TA-10：空电话又画成一行空白（看不出这条人没有电话）",
        SCR,
        'c.phone.orEmpty().ifBlank { "无电话" }',
        "c.phone.orEmpty()",
        "空电话画成",
    ),
    (
        "TA-10：ViewModel 里的丢字状态整个删掉（界面接不上，又变成哑的）",
        VM,
        "    var contactPhoneNote by mutableStateOf<String?>(null)",
        "    // (状态被删)",
        "contactPhoneNote 状态",
    ),
    (
        "行为的证据被删：子分价那条断言从单测里拿掉",
        KIT_TEST,
        '        assertEquals("¥0.005/箱", productPriceFact("0.005", "箱").value)\n',
        "",
        "行为锚点",
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
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出（"写了还原"不是证明）。
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
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:80] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"[X] 前提不成立：源码完好时这条红线没过\n{out[-1500:]}")
        return 1
    print("[ok] 前提：源码完好时这条红线是绿的")

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
    print("  [OK] 还原后红线全绿" if ok else "[MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print(f"[X] {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"[ok] {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
