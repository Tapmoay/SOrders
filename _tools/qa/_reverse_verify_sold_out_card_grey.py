#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反向验证：`_tools/qa/_check_sold_out_card_grey.py` 里那些红线**真的在检查**吗？

机器判据最怕的不是写错，是**写得太松**：正则退化成「全文里还有这几个字就行」、
判据被搬到别的脚本之后原地留了个空壳、数值改了但判据还在看旧的那一处 —— 三种情况都
**不报错、不崩溃、照样全绿**，而屏幕上那张卡已经是亮着的了（用户这一轮提的正是"亮着"）。

这个脚本用「把源码改坏 → 判据必须变红」来证明每一条判据都是活的：

  1. **判据空转**：注入之后退出码仍是 0（`✅ 全部 N 项通过`）⇒ 这条判据是死的；
  2. **只认名字不认形状**：把共用件里的常量改名、把灰罩那一层删掉、把「已沽清」角标拿掉，
     判据必须跟着红（不能靠"文件还在"蒙过去）；
  3. **口径被单方面改掉**：把 0.45f / 0.6f 改成 0.95f、把选品弹层那一份改成 0.7、
     把设计系统 §4.25i 里的用户原话删掉、把判据脚本自己的 CASES 改名 ——
     用户画的那条线就没人守了。

## R4-BOUNDARY-JUSTIFICATION: 为什么这条红线只能在这儿守

因为**没有类型可以表达它**。`soldOut` 是 `Boolean`、`Color` 是 `Color`、`0.45f` 与 `0.95f`
在 Kotlin 的类型系统里是同一个类型 —— 编译器、detekt、Kotlin 的检查都不可能说「这个布尔为真时，
那个容器必须换色、整棵子树必须降到 0.6、而且三个按钮里恰好只有一颗要多认一个 `isActive`」。
这是**一棵 composable 树的形状**，只在源码文本上成立；后端也没有、不该有"这张卡灰不灰"这个字段
（那是 `products.is_active` 的画法，多一个字段就是同一件事两处真相）。

所以它只能在两处守：`ui/common/ProductSoldOutScrim.kt`（值本身）与判据脚本（值被谁用、怎么用）。
反向验证则证明这两处**没有一个是摆设**。

本脚本**只读写工作区里的文件**，不编译、不跑 UI、不连设备；每条注入跑完立刻按字节还原。

用法：
    python _tools/qa/_reverse_verify_sold_out_card_grey.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_sold_out_card_grey.py"

SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductsScreen.kt"
SCRIM = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductSoldOutScrim.kt"
PICKER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPicker.kt"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
DOC = "docs/changes/CHG-0103.md"
REG = "docs/changes/README.md"
LOCATOR = "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
ME = "_tools/qa/_reverse_verify_sold_out_card_grey.py"


def sub(old: str, new: str, idx: int = 0, expect: int | None = None):
    """把第 `idx` 处（0 起）`old` 换成 `new`。

    ⚠️ 为什么要 `idx`：`str.replace(old, new, 1)` 认的是第一处**子串**，而 `old` 经常被
    更长的行包含（踩过：另一个脚本里 `Icons.Default.Description,` 是另一行后一段，
    于是"改第 3 处"其实改了第 1 处，判据照样绿 —— 注入就成了自欺）。
    """
    def run(text: str) -> str:
        n = text.count(old)
        if n == 0:
            raise AssertionError("注入点不在了：" + repr(old[:80]))
        if expect is not None and n != expect:
            raise AssertionError("注入点命中 %d 次（期望 %d）：%r" % (n, expect, old[:80]))
        pos = -1
        for _ in range(idx + 1):
            pos = text.find(old, pos + 1)
        if pos < 0:
            raise AssertionError("第 %d 处不存在：%r" % (idx, old[:80]))
        return text[:pos] + new + text[pos + len(old):]
    return run


#: (标题, 相对路径, 注入函数, 期望在判据输出里看到的关键词)
CASES: list[tuple[str, str, object, str]] = [
    # ---------------- 1. 整卡变灰被去掉 / 只灰了一部分 ----------------
    ("① 灰罩被摘掉（卡片上「看起来」什么都没变，回到这一轮之前）",
     SCREEN, sub("ProductSoldOutCard(soldOut = !p.isActive) {",
                 "ProductSoldOutCard(soldOut = false) {"),
     "卡上真的用了共用件"),
    ("② 灰罩那一层整个删掉，`SectionCard` 又成了卡的根",
     SCRIM, sub("    if (!soldOut) {\n        Column(modifier = modifier, content = content)\n"
                "        return\n    }\n    Surface(",
                "    if (true) {\n        Column(modifier = modifier, content = content)\n"
                "        return\n    }\n    Surface("),
     "在售那一支**原样透传**"),
    ("③ 只灰了一部分：内容变暗挂在 Row 上（图与名称还是亮的）",
     SCRIM, sub("        Box(Modifier.alpha(PRODUCT_SOLD_OUT_CONTENT_ALPHA)) {",
                "        Box(Modifier.padding(0.dp)) {"),
     "内容变暗挂在**容器**上"),
    ("④ 「已沽清」角标被删（灰卡上没有它的来历）",
     SCREEN, sub("val soldOut: (@Composable () -> Unit)? = if (p.isActive) null else "
                 "({ ProductSoldOutBadge() })",
                 "val soldOut: (@Composable () -> Unit)? = null"),
     "角标来自共用件"),
    ("⑤ 未沽清的卡被误灰：灰罩改成无条件的（`soldOut = true`）",
     SCREEN, sub("ProductSoldOutCard(soldOut = !p.isActive) {",
                 "ProductSoldOutCard(soldOut = true) {"),
     "灰罩不是按库存/别的字段触发的"),

    # ---------------- 2. 按钮还能点 / 连"上架""编辑"一起被禁 ----------------
    ("⑥ 按钮仍可点：整卡变暗却把「改价」那道闸拿掉",
     SCRIM, sub("        Box(Modifier.alpha(PRODUCT_SOLD_OUT_CONTENT_ALPHA)) {",
                "        Box(Modifier.alpha(0.95f)) {"),
     "内容变暗挂在**容器**上"),
    ("⑦ 灰卡上还能改价：「改价」的 `&& p.isActive` 被拿掉",
     SCREEN, sub("                enabled = !acting && p.isActive,",
                 "                enabled = !acting,"),
     "多一道 `&& p.isActive` 的按钮正好 1 个"),
    ("⑧ 连「上架」「编辑」一起禁掉（沽清的商品再也回不到在售）",
     SCREEN, sub("                    enabled = !acting,\n                    onClick = onToggle,",
                 "                    enabled = !acting && p.isActive,\n                    onClick = onToggle,"),
     "多一道 `&& p.isActive` 的按钮正好 1 个"),
    ("⑨ 「改价」那颗按钮被改名（文案变了，「多认一个 isActive」落到别处）",
     SCREEN, sub('                label = "改价",', '                label = "调价",'),
     "那一颗是「改价」"),

    # ---------------- 3. 数值被改 / 两份值不一致 ----------------
    ("⑩ 灰底那档被改松（0.45f → 0.95f：字面上「变灰」还在，画出来跟没做一样）",
     SCRIM, sub("const val PRODUCT_SOLD_OUT_SURFACE_ALPHA: Float = 0.45f",
                "const val PRODUCT_SOLD_OUT_SURFACE_ALPHA: Float = 0.95f"),
     "灰底常量"),
    ("⑪ 商品管理页里另写一套透明度（两份真相）",
     SCREEN, sub("    ProductSoldOutCard(soldOut = !p.isActive) {",
                 "    Modifier.alpha(0.45f)\n    ProductSoldOutCard(soldOut = !p.isActive) {"),
     "里没有 `0.45f` 这个字面量"),
    ("⑫ 选品弹层那一份被单独改掉（同一件事在两个页面上是两个灰度）",
     PICKER, sub("surfaceVariant.copy(alpha = 0.45f)", "surfaceVariant.copy(alpha = 0.7f)"),
     "选品弹层的灰底透明度"),

    # ---------------- 4. 共用件 / 角标 / 口径被换掉 ----------------
    ("⑬ 共用夹具被改名（判据不许靠「文件还在」蒙过去）",
     SCRIM, sub("const val PRODUCT_SOLD_OUT_CONTENT_ALPHA: Float = 0.6f",
                "const val PRODUCT_SOLD_OUT_CONTENT_ALPHA_X: Float = 0.6f"),
     "内容常量"),
    ("⑭ 角标被参数化（于是下一页就会传「售罄」「下架」）",
     SCRIM, sub("fun ProductSoldOutCard(\n    soldOut: Boolean,",
                "fun ProductSoldOutCard(\n    soldOut: Boolean,\n    label: String = \"已沽清\","),
     "卡壳 `fun ProductSoldOutCard(`"),
    ("⑮ 设计系统里这一节的用户原话被删（这条口径的来历没人记得了）",
     DESIGN, sub("> 「顺便参考他这个样式啊，我们现在的商品管理。如果估清了。他那个卡片只会有一个沽清的状态，\n"
                 ">  但是并没有整体变灰的样式啊参考。他的样式啊，他当时就有一个整体变灰的变动啊啊，改一下吧。」",
                 "> （参考图里的样式照做。）"),
     "那一节逐字引了这一轮的用户原话"),
    ("⑯ 设计系统里不再说「灰卡与角标是同一件事」（于是会被做成两个状态两个词）",
     DESIGN, sub("同一件事的两种说法", "两件不同的事"),
     "那一节说清了灰卡与角标是同一件事的两种说法"),

    # ---------------- 5. 配套 / 登记 / 判据自己 ----------------
    ("⑰ 变更单里不再逐字引用户原话",
     DOC, sub("> 「顺便参考他这个样式啊，我们现在的商品管理。如果估清了。他那个卡片只会有一个沽清的状态，\n"
              ">  但是并没有整体变灰的样式啊参考。他的样式啊，他当时就有一个整体变灰的变动啊啊，改一下吧。」",
              "> （用户要求参考图里的样式。）"),
     "变更单逐字引了这一轮的用户原话"),
    ("⑱ 登记簿那一行被拿走（配套断了）",
     REG, sub("| `CHG-0103` |", "| `CHG-010X` |"),
     "变更单在登记簿里"),
    ("⑲ 定位表那一行不再提「整卡变灰」",
     LOCATOR, sub("整卡变灰", "卡片外观"),
     "定位表那一行也跟着动了"),
    ("⑳ 反验脚本自己的注入表被换成空壳",
     ME, sub("CASES: list[tuple[str, str, object, str]] = [",
             "CASESX: list[tuple[str, str, object, str]] = ["),
     "反验脚本里有注入表"),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    rc, out = run_check()
    if rc != 0:
        print("⛔ 源码完好时判据就不是全绿 —— 先把 _check_sold_out_card_grey.py 修到全绿再来跑反向验证。")
        print(out[-3000:])
        return 1
    print("✅ 前置：源码完好时判据全绿（%s）" % CHECK.name)

    originals = {rel: (ROOT / rel).read_bytes() for rel in
                 {c[1] for c in CASES} | {ME}}
    bad: list[str] = []
    try:
        for i, (title, rel, mutate, keyword) in enumerate(CASES, 1):
            p = ROOT / rel
            raw = originals[rel]
            crlf = b"\r\n" in raw
            text = raw.decode("utf-8").replace("\r\n", "\n")
            try:
                broken = mutate(text)  # type: ignore[operator]
            except AssertionError as e:
                bad.append("%s —— %s" % (title, e))
                print("  [MISS] %s —— %s" % (title, e))
                continue
            blob = broken.replace("\n", "\r\n").encode("utf-8") if crlf else broken.encode("utf-8")
            p.write_bytes(blob)
            try:
                rc2, out2 = run_check()
            finally:
                p.write_bytes(raw)
            hit_red = rc2 != 0
            hit_kw = keyword in out2
            hit_any_fail = "[FAIL]" in out2
            if hit_red and (hit_kw or hit_any_fail):
                print("  [OK]   %s" % title)
            else:
                why = "判据还是绿的" if not hit_red else "红了但不是这一条"
                bad.append("%s —— %s（期望关键词「%s」）" % (title, why, keyword))
                print("  [FAIL] %s —— %s" % (title, why))
    finally:
        dirty = []
        for rel, raw in originals.items():
            if (ROOT / rel).read_bytes() != raw:
                (ROOT / rel).write_bytes(raw)
                dirty.append(rel)
        if dirty:
            print("⚠️ 有文件没还原干净，已强制还原：%s" % ", ".join(dirty))

    rc3, out3 = run_check()
    if rc3 != 0:
        print("⛔ 还原之后判据不是全绿 —— 注入把源码改坏了。")
        print(out3[-2000:])
        return 1

    print("")
    for rel, raw in originals.items():
        assert (ROOT / rel).read_bytes() == raw, rel
    print("✅ 还原检查：%d 个被注入的文件逐字节一致；还原之后判据全绿。" % len(originals))

    if bad:
        print("❌ %d/%d 条注入没有被判据抓住：" % (len(bad), len(CASES)))
        for b in bad:
            print("   - " + b)
        return 1
    print("✅ %d 条注入都证明这条红线真的在检查。" % len(CASES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
