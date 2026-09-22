# -*- coding: utf-8 -*-
"""反向验证「输入框必须走 InputRules」这条红线**真的会红**（2026-09-19 用户反馈）。

## 为什么这条要反向验证
它的判据是"某个输入框里必须出现 `InputRules.*`"，而这类判据有三种典型失效方式，
每一种都必须被单独证明会红：

1. **锚点太宽 / 只扫一半**：第一版只扫 `onValueChange =` 之后那一段，于是
   `SoTextField(vm.qty, { ... }, placeholder = "数量")` 这种**位置参数**写法整个漏掉
   （`InventoryScreen`/`DispatcherLedgerScreen` 的数量框一个都没被认出来）。本脚本
   专门用位置参数那一条做注入。
2. **被注释骗过去**：写在输入框调用中间的中文注释里会出现
   「规则唯一实现在 core/InputRules.kt」这种字眼。不抠注释的话，一个**根本没接线**的框
   会因为注释里提到了 `InputRules` 而判"已接线" —— 假绿比没有检查更糟。本脚本专门造一个
   "注释里写着 InputRules、实际不过滤"的框，它必须照样报红。
3. **例外表变成化石**：`EXCLUDED` 里那条登录框的例外是**故意**留的（用户名可以是字母）。
   本脚本把这条例外删掉，红线必须报红 —— 证明那个框真的被看见了，
   而不是"碰巧没扫到所以不用排除"。

另外两条专门打"清单"本身：清单里塞一条不存在的排除理由 → 必须报红（防化石）；
解析器被改坏 → 必须自己报"判据空转"，而不是安静地全绿。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过"注入把守卫留在源码里"）。

用法：python _tools/qa/_reverse_verify_input_rules.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_input_rules.py"
CHECK_REL = "_tools/qa/_check_input_rules.py"

ORDER_CREATE = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
USERS_MANAGE = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/UsersManageScreen.kt"
PRODUCTS = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductsScreen.kt"
#: 2026-09-22：商品的"默认售价"这个框**搬家了** —— 商品管理改版第 1 期把编辑抽屉整段删掉、
#: 换来一页 `ProductFormScreen`（那一页用的是共用表单行 `FormInputRow`）。注入点要跟着搬，
#: 否则这条反向验证只会打一句"锚点变了"（它拦不住任何东西，却看着像在拦）。
PRODUCT_FORM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductFormScreen.kt"
INVENTORY = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/InventoryScreen.kt"
ORDER_DETAIL = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"
ARREARS = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ArrearsUnitsScreen.kt"
PRODUCT_PICKER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPicker.kt"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "下单页的收货人电话不再过滤（汉字又能写进电话字段）",
        ORDER_CREATE,
        lambda s: s.replace(
            "onValueChange = { vm.dongjiaPhone = InputRules.phoneInput(it) },",
            "onValueChange = { vm.dongjiaPhone = it },",
            1,
        ),
        "收货人电话",
    ),
    (
        "建账号的手机号不再过滤（字母能进登录账号）",
        USERS_MANAGE,
        lambda s: s.replace(
            "onValueChange = { vm.draftPhone = InputRules.mobileInput(it) },",
            "onValueChange = { vm.draftPhone = it },",
            1,
        ),
        "手机号（登录账号）",
    ),
    (
        "商品售价退回手写的 isDigit + 点号过滤（`1.2.3` 又能敲进来）",
        PRODUCT_FORM,
        lambda s: s.replace(
            "onValueChange = { vm.price = InputRules.priceInput(it) },",
            "onValueChange = { vm.price = it.filter { c -> c.isDigit() || c == '.' } },",
            1,
        ),
        "售价",
    ),
    (
        "数量框退回手写 isDigit 过滤（**位置参数**那条路，第一版检查漏的就是它）",
        INVENTORY,
        lambda s: s.replace(
            "{ vm.movementQty = InputRules.intInput(it, 6) },",
            "{ vm.movementQty = it.filter { c -> c.isDigit() } },",
            1,
        ),
        "手写了数字过滤",
    ),
    (
        "司机运费框什么都不做（回到改之前：连过滤都没有）",
        ORDER_DETAIL,
        lambda s: s.replace(
            "onValueChange = { vm.draftFreight = InputRules.moneyInput(it) },",
            "onValueChange = { vm.draftFreight = it },",
            1,
        ),
        "运费",
    ),
    (
        "注释里写着 InputRules、实际不过滤（注释不许把假绿喂给检查）",
        ARREARS,
        lambda s: s.replace(
            "{ vm.draftPhone = InputRules.phoneInput(it) },",
            "// 规则唯一实现在 core/InputRules.kt 的 phoneInput，只让数字进来\n"
            "                        { vm.draftPhone = it },",
            1,
        ),
        "联系电话",
    ),
    (
        "把登录框那条例外删掉（证明登录框真的被看见，不是碰巧漏扫）",
        CHECK_REL,
        lambda s: s.replace(
            '    "android/app/src/main/java/com/tapmoay/sorders/ui/login/LoginScreen.kt::手机号 / 用户名": (',
            '    "android/app/src/main/java/com/tapmoay/sorders/ui/login/LoginScreen.kt::_disabled_": (',
            1,
        ),
        "手机号 / 用户名",
    ),
    (
        "排除理由表里塞一条不存在的框（化石没被发现 = 这张表没人管）",
        CHECK_REL,
        lambda s: s.replace(
            "EXCLUDED: dict[str, str] = {",
            'EXCLUDED: dict[str, str] = {\n    "android/app/src/main/java/com/tapmoay/sorders/ui/Nowhere.kt::不存在的框": "化石",',
            1,
        ),
        "化石",
    ),
    (
        "解析器被改坏（一个框都扫不到）→ 必须自己报「判据空转」而不是全绿",
        CHECK_REL,
        lambda s: s.replace(
            'FIELD_NAMES = ("OutlinedTextField", "SoTextField", "BasicTextField", "TextField",\n'
            '               "FormInputRow", "FormTextAreaRow")',
            'FIELD_NAMES = ("ZzzNotAComposable",)',
            1,
        ),
        "解析器失配",
    ),
    (
        "下单页的行编辑弹窗又把「单价」输入框加回来（货主又能自己定价）",
        ORDER_CREATE,
        lambda s: s.replace(
            '                FormInputRow(\n'
            '                    label = "商品名称",\n'
            '                    value = name,\n'
            '                    onValueChange = { name = it },',
            '                OutlinedTextField(\n'
            '                    value = initial.price,\n'
            '                    onValueChange = {},\n'
            '                    label = { Text("单价（元）") },\n'
            '                    singleLine = true,\n'
            '                    modifier = Modifier.fillMaxWidth(),\n'
            '                )\n'
            '                FormInputRow(\n'
            '                    label = "商品名称",\n'
            '                    value = name,\n'
            '                    onValueChange = { name = it },',
            1,
        ),
        "不许改价",
    ),
    (
        "选品弹层里冒出一个「价格」输入框（下单链路又能改价）",
        PRODUCT_PICKER,
        lambda s: s.replace(
            '            var qty by remember { mutableStateOf(initialQty.coerceAtLeast(1)) }',
            '            var qty by remember { mutableStateOf(initialQty.coerceAtLeast(1)) }\n'
            '            var p by remember { mutableStateOf(price) }',
            1,
        ).replace(
            '            Column {\n                Row(verticalAlignment = Alignment.CenterVertically) {\n'
            '                    Text("数量"',
            '            Column {\n'
            '                OutlinedTextField(value = p, onValueChange = { p = it },'
            ' label = { Text("单价（元）") })\n'
            '                Row(verticalAlignment = Alignment.CenterVertically) {\n'
            '                    Text("数量"',
            1,
        ),
        "不许改价",
    ),
    (
        "「下单链路不许改价」的文件清单指向了不存在的路径（判据变成空转）",
        CHECK_REL,
        lambda s: s.replace(
            '"android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPicker.kt":',
            '"android/app/src/main/java/com/tapmoay/sorders/ui/common/Nowhere.kt":',
            1,
        ),
        "空转",
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
        # 按行尾归一后再替换（Windows 上 Kotlin 文件可能是 CRLF），写回时按原样还原
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated.replace("\r\n", "\n")
            if crlf:
                out_txt = out_txt.replace("\n", "\r\n")
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
