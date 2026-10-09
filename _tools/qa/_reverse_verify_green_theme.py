# -*- coding: utf-8 -*-
r"""绿主题那条红线（CHG-0091），一条条被真的破坏一次。

一条红线要能被「真的破坏一次」证明它在检查：下面每一条注入都只改一处，然后要求
_tools/qa/_check_green_theme.py 报红，而且报的是**这一条**（关键词比对）。
跑完按字节还原，再逐字节核对 —— 一个字节都不许留在工作区。

这一组破坏方式的来路都是真实会发生的改法：主色悄悄退回蓝、`InfoBlue` 没跟着走、
商品块退回「紫方块 + 紫字」、数量的拼法被顺手"整理"、页面顶那条绿渐变被偷偷加回来
（⛔ 用户当天就撤了它，见 ref m02715）、`Scaffold` 又被铺上背景、顶栏又被刷成浅绿、
页面底那层没跟上来。
⛔ 锚点一律写文件里的真实长相（含前导空格与行尾注释）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_green_theme.py"

COLOR = "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt"
CARD = "android/app/src/main/java/com/tapmoay/sorders/ui/common/OrderCard.kt"
HOME = "android/app/src/main/java/com/tapmoay/sorders/ui/home/RoleHomeScreen.kt"
COMPONENTS = "android/app/src/main/java/com/tapmoay/sorders/ui/common/Components.kt"
LEDGER = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperLedgerScreen.kt"
REPORT = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"

NL = chr(10)

#: 注入：只把**颜色的身份**退回去（换一个同样合法的颜色），类型/编译全都照样通过。
CASES: list[tuple[str, str, object, str]] = [
    (
        "主色退回亮蓝：ThemeGreen 深红棕 #8B4A4A → #1E6FFF",
        COLOR,
        # ⚠️ 锚点必须与 `Color.kt` 里**真实写法**逐字一致：这一行**没有** `L` 后缀
        #    （同一个文件里 ThemeGreenDeep 有、ThemeGreen 没有，历史遗留）。
        #    写成 `...4AL` 会让这条注入恒 SKIP（锚点判据 `_check_reverse_verify_anchors.py` 会报）。
        lambda s: s.replace("val ThemeGreen = 0xFF8B4A4A", "val ThemeGreen = 0xFF1E6FFF", 1),
        "ThemeGreen = #8B4A4A",
    ),
    (
        "NavBlue 的别名断了：全仓 16 处引用不再跟着主色走",
        COLOR,
        lambda s: s.replace("val NavBlue = ThemeGreen", "val NavBlue = 0xFF1E6FFFL", 1),
        "NavBlue 是 ThemeGreen 的别名",
    ),
    (
        "InfoBlue 没跟着走（它只有定义、0 引用，最容易漏）",
        COLOR,
        lambda s: s.replace("val InfoBlue = ThemeGreen", "val InfoBlue = 0xFF1E6FFFL", 1),
        "InfoBlue 也跟着换成 ThemeGreen",
    ),
    (
        "商品块的浅绿底退回近白：ProductRowTint #E6F7EE → #F3F2EF",
        COLOR,
        lambda s: s.replace("val ProductRowTint = 0xFFF0E2DCL", "val ProductRowTint = 0xFFF1EFEAL", 1),
        "ProductRowTint = 0xFFF0E2DCL",
    ),
    (
        "深红棕数量块的底被提亮：ThemeGreenDeep #6E3636 → #8B4A4A",
        COLOR,
        lambda s: s.replace("val ThemeGreenDeep = 0xFF6E3636L",
                            "val ThemeGreenDeep = 0xFF8B4A4AL", 1),
        "ThemeGreenDeep = 0xFF6E3636L",
    ),
    (
        "页面顶那条绿渐变被偷偷加回来（用户当天就撤了它）",
        COLOR,
        lambda s: s.replace("val ThemeGreenDeep = 0xFF6E3636L",
                            "val ThemeGreenDeep = 0xFF6E3636L\n"
                            "val PageGradientGreen = 0xFF0B6644L", 1),
        "Color.kt 里那个起色 token 已删",
    ),
    (
        "token 被写成 Color(0x…)（同一组变成另一种类型，用色处就编译不过）",
        COLOR,
        lambda s: s.replace("val ProductRowTint = 0xFFF0E2DCL", "val ProductRowTint = Color(0xFFF0E2DC)", 1),
        "必须是裸 Long",
    ),
    (
        "页面底那一层没跟上：BackgroundLight 近白 → 暖白",
        COLOR,
        lambda s: s.replace("val BackgroundLight = Color(0xFFF7F6F3)", "val BackgroundLight = Color(0xFFF8F7F4)", 1),
        "BackgroundLight = 0xFFF7F6F3",
    ),
    (
        "品名又穿回紫色（用户定稿原话「商品名称不留紫色」）",
        CARD,
        lambda s: s.replace("color = Color(OnProductRowTint),", "color = Color(ProductPurple),", 1),
        "品名 = SemiBold + OnProductRowTint",
    ),
    (
        "数量的拼法被顺手\"整理\"（§4.20 的唯一实现点被改坏）",
        CARD,
        lambda s: s.replace('"×" + qtyWithUnitConverted(op.quantity, op.unit, conversions),',
                            '"x" + op.quantity,', 1),
        "数量的拼法逐字没动",
    ),
    (
        "只画前三个商品被放开：take(3) → take(5)",
        CARD,
        lambda s: s.replace("order.orderProducts.take(3).forEach { op ->",
                            "order.orderProducts.take(5).forEach { op ->", 1),
        "只画前三个商品",
    ),
    (
        "商品块不再整宽（块与块就分不开了）",
        CARD,
        # ⚠️ 注入必须**对准判据真正盯的那几行**：判据的正则是
        #    `clip(shapes.medium) → background(ProductRowTint) → padding(8,6)` 三行连着，
        #    所以"注入"就删中间那一行（原来我删的是 `.fillMaxWidth()` —— 判据不盯它，
        #    于是实测 0 条红，看起来像"判据不敏感"，其实是注入没打中）。
        lambda s: s.replace("""                            .clip(MaterialTheme.shapes.medium)
                            .background(Color(ProductRowTint))
                            .padding(horizontal = 8.dp, vertical = 6.dp),""",
                            """                            .clip(MaterialTheme.shapes.medium)
                            .padding(horizontal = 8.dp, vertical = 6.dp),""", 1),
        "块底 = 圆角 medium + ProductRowTint",
    ),
    (
        "数量块的白字被换成墨绿（深绿底上就读不清了）",
        CARD,
        # ⚠️ 只改 `Color.White` **那一行**，但锚点必须**长到唯一**：
        #    `color = Color.White,` 这种句子在别处也可能出现（详情页那颗「确认接单」就是），
        #    count=1 会改到**不相干的第一处** ⇒ 判据照样绿 ⇒ 看起来像"判据不敏感"。
        #    所以把锚点串到它下面那行 `ThemeGreenDeep`（那个 token 只此一处）。
        lambda s: s.replace("""                            color = Color.White,
                            maxLines = 1,
                            modifier = Modifier
                                .clip(MaterialTheme.shapes.small)
                                .background(Color(ThemeGreenDeep))""",
                            """                            color = Color(OnProductRowTint),
                            maxLines = 1,
                            modifier = Modifier
                                .clip(MaterialTheme.shapes.small)
                                .background(Color(ThemeGreenDeep))""", 1),
        "数量 = 白字压深绿块",
    ),
    (
        "块间距塌成 0：多商品又挤成一坨",
        CARD,
        lambda s: s.replace("verticalArrangement = Arrangement.spacedBy(6.dp),",
                            "verticalArrangement = Arrangement.spacedBy(0.dp),", 1),
        "块与块之间 spacedBy(6.dp)",
    ),
    (
        # 2026-10-09 真机抓到的回归：改前这块套在 `Row(Alignment.Top)` 里，`weight(1f)` 是横向的；
        # 甲案去掉那层 Row 之后它成了页面级 Column 的直接子节点 ⇒ 纵向权重 ⇒ 0 高 ⇒ 整块不可见。
        # 这条注入就是把当年的写法原样加回去，看判据认不认。
        "商品块那一层又被挂回 weight(1f)（真机抓到的 0 高回归）",
        CARD,
        lambda s: s.replace(
            "            Column(\n"
            "                verticalArrangement = Arrangement.spacedBy(6.dp),\n"
            "            ) {",
            "            Column(\n"
            "                modifier = Modifier.weight(1f),\n"
            "                verticalArrangement = Arrangement.spacedBy(6.dp),\n"
            "            ) {", 1),
        "商品块那一层没有 Modifier.weight(1f)",
    ),
    (
        "又给主界面加回一条绿渐变（Brush 那条 import 会一起回来）",
        HOME,
        lambda s: s.replace("import androidx.compose.ui.platform.LocalContext",
                            "import androidx.compose.ui.graphics.Brush\n"
                            "import androidx.compose.ui.platform.LocalContext", 1),
        "不再 import Brush",
    ),
    (
        "主界面那一层的 Scaffold 又被铺上背景（页面底就再也白不回来了）",
        HOME,
        lambda s: s.replace("    Scaffold(\n        bottomBar = {",
                            "    Scaffold(\n        containerColor = Color.Transparent,\n        bottomBar = {", 1),
        "Scaffold 不再被铺背景 / 不再透明",
    ),
    (
        "顶栏又被刷成浅绿（全 App 每一页的头都跟着变色）",
        COMPONENTS,
        lambda s: s.replace("            containerColor = MaterialTheme.colorScheme.background,",
                            "            containerColor = MaterialTheme.colorScheme.primaryContainer,", 1),
        "顶栏不再读 primaryContainer",
    ),
    (
        "硬编码的旧主色又冒出来一处（本单刚把它收成 token）",
        REPORT,
        lambda s: s.replace('StatBig("这一段卖出去的货", money(data.revenueTotal), Color(ThemeGreen))',
                            'StatBig("这一段卖出去的货", money(data.revenueTotal), Color(0xFF1E6FFF))', 1),
        "没有残留的硬编码 0xFF1E6FFF",
    ),
    (
        "灰蓝又回到页面底：BackgroundLight #FBFBFA → #F2F3F7（旧值必须一处不剩）",
        COLOR,
        lambda s: s.replace("val BackgroundLight = Color(0xFFF7F6F3)",
                            "val BackgroundLight = Color(0xFFF7F6F3)", 1),
        "BackgroundLight = 0xFFF7F6F3",
    ),
]

#: 分两步的注入（一次替换做不出来），在 main() 里单独跑。
LEDGER_OLD = 'tint = Color(if (e.source == "manual") ProductPurple else ThemeGreen),'
LEDGER_NEW = 'tint = Color(if (e.source == "manual") 0xFF8A7BB0 else 0xFF1E6FFF),'


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-2000:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    fails: list[str] = []

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", NL)
        mutated = mutate(plain)
        if mutated == plain:
            print(f"  [SKIP] {label}：注入没生效（锚点变了，请更新本脚本）")
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            continue
        text = mutated.replace(NL, "\r\n") if crlf else mutated
        try:
            path.write_bytes(text.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        if code != 0 and (not expect or expect in out):
            print(f"  [OK]   {label} → 报红")
        else:
            print(f"  [MISS] {label}（退出码 {code}，期望关键词「{expect}」）")
            fails.append(f"{label}（退出码 {code}，期望关键词「{expect}」）")

    # ── 第 19 条：货主账本流水那一行，退回到两处硬编码（这条判据是"全仓扫描"，单独试） ──
    rel = LEDGER
    original_bytes = (ROOT / rel).read_bytes()
    crlf = b"\r\n" in original_bytes
    plain = original_bytes.decode("utf-8").replace("\r\n", NL)
    mutated = plain.replace(LEDGER_OLD, LEDGER_NEW, 1)
    if mutated == plain:
        print("  [SKIP] 货主账本流水那一行退回硬编码：注入没生效（锚点变了，请更新本脚本）")
        fails.append("货主账本流水那一行退回硬编码：注入没生效（锚点变了，请更新本脚本）")
    else:
        try:
            (ROOT / rel).write_bytes((mutated.replace(NL, "\r\n") if crlf else mutated).encode("utf-8"))
            code, out = run_check()
        finally:
            (ROOT / rel).write_bytes(original_bytes)
        expect = "没有残留的硬编码 0xFF1E6FFF"
        if code != 0 and expect in out:
            print("  [OK]   货主账本流水那一行退回硬编码 → 报红")
        else:
            print(f"  [MISS] 货主账本流水那一行退回硬编码（退出码 {code}，期望关键词「{expect}」）")
            fails.append(f"货主账本流水那一行退回硬编码（退出码 {code}，期望关键词「{expect}」）")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if (ROOT / LEDGER).read_bytes() != original_bytes:
        dirty.append(LEDGER)
    for rel in dirty:
        (ROOT / rel).write_bytes(originals.get(rel, original_bytes))
        print(f"  [!!]   {rel} 没还原干净，已强制写回")
        fails.append(f"{rel} 没还原干净")

    print("=" * 60)
    if fails:
        print(f"❌ 反向验证不通过：{len(fails)} 条")
        for f in fails:
            print(f"   - {f}")
        return 1
    print(f"✅ {len(CASES) + 1} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
