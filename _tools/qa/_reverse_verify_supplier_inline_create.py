# -*- coding: utf-8 -*-
"""反向验证「选供应商的弹层里能就地新建一家」这条红线**真的会红**（L-40 / CHG-0068）。

## 为什么这条要反向验证
它的判据几乎全是"某个文件里必须出现某个零件 / 某句话 / 某两行的顺序"，这类判据有三种典型失效方式，
每一种都必须被单独证明会红：

1. **入口看着像有、其实点了没反应**：弹层底部那颗按钮还在，但 `onCreate` 传的是 null（或者渲染那一段被 `if (false)` 关掉）——
   界面上按钮照样画、点下去什么都不发生；档案页那份共用件被改名之后"两处调用"也会少一处，
   而共用件本身还在，判据如果只数"函数在不在"就永远绿。
2. **建完没选中**：`pickSupplier(s)` 被删掉 / 被挪到 `onCreated(s)` 之后 —— 供应商建出来了，但栏里还是空的，
   用户以为白建了；单看"有没有这颗按钮"完全看不出来。
3. **进项票那条早退守卫**：`createSupplierInline` 里图省事调 `loadSuppliers()`（它头一句是
   `if (suppliers.isNotEmpty()) return`）—— 名册不刷新、新供应商不在列表里，而弹层已经关掉了。
4. 还有一条是**代价**：`OneShotSnackbar` 的新参数是可选的，但全库唯一用尾随 lambda 的调用点会**静默改绑**到新参数上
   （Kotlin 尾随 lambda 绑最后一个参数）—— 这正是本轮编译红过一次的原因，必须能被抓回来。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_supplier_inline_create.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_supplier_inline_create.py"

#: Windows 上 Kotlin 文件是 CRLF：按字节快照、归一后再替换、写回时按原样还原
CR = bytes((13,))
LF = bytes((10,))
CRLF = CR + LF

DIALOG = "android/app/src/main/java/com/tapmoay/sorders/ui/common/SupplierEditorDialog.kt"
COMPONENTS = "android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt"
SUPPLIERS = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/SuppliersScreen.kt"
PO_FORM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/PurchaseOrderFormScreen.kt"
INVOICE = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/InvoiceFormScreen.kt"
BASIC = "android/app/src/main/java/com/tapmoay/sorders/ui/profile/BasicSettingsScreen.kt"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 共用弹窗：`minimal` 的默认值被改成 true（档案页那两处也被砍成「只问名称 ＋ 电话」）",
        DIALOG,
        lambda s: s.replace("minimal: Boolean = false,", "minimal: Boolean = true,", 1),
        "签名带",
    ),
    (
        "② 共用弹窗：口径 ③ 那句提示没了（建完不告诉用户「以后去哪儿补地址、备注」）",
        DIALOG,
        lambda s: s.replace('text = "地址、备注以后可以在「供应商 / 厂商」页补",', 'text = "",', 1),
        "口径 ③",
    ),
    (
        "③ 采购单弹层：底部那颗按钮被关掉（入口看着在、其实不画了）",
        PO_FORM,
        lambda s: s.replace("if (onCreate != null) {", "if (false) {", 1),
        "弹层底部那颗按钮真的画出来了",
    ),
    (
        "④ 采购单：调用点把 onCreate 传成 null（按钮照画、点下去什么都不发生）",
        PO_FORM,
        lambda s: s.replace("onCreate = { creatingSupplier = true },", "onCreate = null,", 1),
        "调用点把 onCreate 接上",
    ),
    (
        "⑤ 采购单 VM：建完不选中（供应商建出来了，栏里还是空的 —— 用户以为白建了）",
        PO_FORM,
        lambda s: s.replace("                pickSupplier(s)\n", "", 1),
        "采购单 VM 的 createSupplierInline",
    ),
    (
        "⑥ 采购单弹层：空态句改回「先去别的页面建一个」（名册空的时候又把人支使走）",
        PO_FORM,
        lambda s: s.replace(
            'EmptyView("还没有供应商 —— 现在就建一家")',
            'EmptyView("还没有供应商档案，先去「供应商 / 厂商」建一个")',
            1,
        ),
        "不再是支使人去别的页面",
    ),
    (
        "⑦ 采购单：保存那句引导与提示条上那颗按钮的约定被拆掉（按钮永远不出现）",
        PO_FORM,
        lambda s: s.replace(
            'actionLabel = if (vm.actionResult == NEED_SUPPLIER) "现在就建一家" else null,',
            "actionLabel = null,",
            1,
        ),
        "提示条上那颗按钮",
    ),
    (
        "⑧ 进项票：供应商那处调用点不传 createLabel（第二个入口被拆掉）",
        INVOICE,
        lambda s: s.replace('createLabel = "新建供应商",', "createLabel = null,", 1),
        "供应商那处调用点把三样都接上了",
    ),
    (
        "⑨ 进项票 VM：刷新名册走回 loadSuppliers()（早退守卫 ⇒ 新供应商不在名册里）",
        INVOICE,
        lambda s: s.replace("suppliers = container.repo.suppliers()", "loadSuppliers()", 1),
        "进项票 VM 刷新名册",
    ),
    (
        "⑩ 供应商页：两处调用被改名（共用件不再被档案页复用 —— 等于又抄了一份私有的）",
        SUPPLIERS,
        lambda s: s.replace("SupplierEditorDialog(", "SupplierEditorDialogOld(", 1),
        "供应商页仍有两处调用",
    ),
    (
        "⑪ 共用提示条：那颗按钮没交给原生 Snackbar（画了按钮也点不出回调）",
        COMPONENTS,
        lambda s: s.replace("actionLabel = actionLabel,", "actionLabel = null,", 1),
        "提示条把按钮交给原生 Snackbar",
    ),
    (
        "⑫ 尾随 lambda 复发：唯一那处调用点改回 `{ … }`（新参数被静默改绑，编译报错在别的文件里）",
        BASIC,
        lambda s: s.replace(
            "OneShotSnackbar(snackbar, resetMessage, onConsumed = { resetMessage = null })",
            "OneShotSnackbar(snackbar, resetMessage) { resetMessage = null }",
            1,
        ),
        "唯一用尾随 lambda 的那处已改成显式",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = CRLF in original_bytes
        plain = original_bytes.decode("utf-8").replace(CRLF.decode(), LF.decode())
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated
            if crlf:
                out_txt = out_txt.replace(LF.decode(), CRLF.decode())
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"  [OK] {label} → 报红")
        else:
            fails.append(f"{label}：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print(f"  [MISS] {label} → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
