"""反向验证 `_tools/qa/_check_order_row_columns.py`（订单行「数量+单位」与商品明细两列）。

## 为什么必须做

这条判据守的事**坏起来一句报错都没有**：数量又退回「×6」（正是用户点名的那句）、
有人照商品那一侧的写法把空单位兜底成「件」（老单凭空多出一个没人填过的事实）、
「数量+单位」被抄成第二份、两列退回各自自然宽度、货损格改成"有货损才占位"——
这五种改法**都能编译、都能跑、界面都"看着正常"**，只有真机逐行比对才看得出来。

所以逐条**注入真缺陷**，每条都必须让判据报红；跑完按字节还原并再验一次绿。

⚠️ 注入锚点优先用 `re:` 形式（判据文件里的缩进会随风变，写死空格数的锚点迟早腐烂）。

用法：python _tools/qa/_reverse_verify_order_row_columns.py [--list]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import (  # noqa: E402
    lock_reverse_verify,
    refuse_if_injecting,
    unlock_reverse_verify,
)

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_order_row_columns.py"
UI = "android/app/src/main/java/com/tapmoay/sorders/ui/"
UNITS = UI + "common/Units.kt"
CARD = UI + "common/OrderCard.kt"
DETAIL = UI + "order/OrderDetailScreen.kt"
PEEK = UI + "common/OrderPeek.kt"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

#: (说明, 文件, 原文（`re:` 前缀 = 正则锚点）, 替换成, 期望被抓到的判据标签**前缀**)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 卡片商品行退回裸拼数量（用户点名的「商品后面的数字没有单位」当场复发）",
        CARD,
        '"×" + qtyWithUnitConverted(op.quantity, op.unit, conversions),',
        '"×" + op.quantity,',
        "商品行的数量走共用拼法",
    ),
    (
        "② 卡片底部合计不管单位（一单「6 桶」底下写「共 6 件」）",
        CARD,
        "sharedUnitOf(order.orderProducts.map { it.unit }) ?: DEFAULT_UNIT",
        "DEFAULT_UNIT",
        "底部合计的单位走 sharedUnitOf",
    ),
    (
        "③ 照商品那一侧的写法，把空单位兜底成「件」（老单凭空多出一个没人填过的事实）",
        UNITS,
        'return if (u.isEmpty()) quantity.toString() else "$quantity $u"',
        'return if (u.isEmpty()) "$quantity $DEFAULT_UNIT" else "$quantity $u"',
        "⛔ qtyWithUnit 里不许出现 DEFAULT_UNIT",
    ),
    (
        "④ 又在卡片里抄了第二份「数量+单位」的拼法（改一处漏一处）",
        CARD,
        "@Composable\nfun OrderCard(",
        'fun qtyWithUnit(q: Int, u: String?): String = "$q $u"\n\n@Composable\nfun OrderCard(',
        "`fun qtyWithUnit(` 全树只有一处定义",
    ),
    (
        "⑤ 详情页件数那一格不再右对齐（用户：「件与件数做对齐」）",
        DETAIL,
        r"re:\s*textAlign = TextAlign\.End,\s*\n\s*modifier = Modifier\.width\(qtyW\),",
        "modifier = Modifier.width(qtyW),",
        "件数那一格右对齐",
    ),
    (
        "⑥ 详情页金额那一格退回自然宽度（位数一变件数列就跟着漂）",
        DETAIL,
        r"re:\s*textAlign = TextAlign\.End,\s*\n\s*modifier = Modifier\.width\(moneyW\),",
        "modifier = Modifier.width(moneyW),",
        "金额那一格右对齐",
    ),
    (
        "⑦ 货损格改回「这一行有没有货损」决定画不画（没货损的那几行金额错开一列）",
        DETAIL,
        "if (hasDamage) {",
        "if (line.damageQuantity > 0) {",
        "货损格用整单判据 hasDamage 占位",
    ),
    (
        "⑧ 账本小卡的数量退回裸拼（派单员账本与货主账本一起复发）",
        PEEK,
        # ⚠️ 锚点必须**只命中"画出来那一行"**：小卡里 `"×" + qtyWithUnit(lp.quantity, lp.unit),`
        #    这个串出现**两次**（量宽度那次 + 画那次），`count=1` 会命中**量宽度**那一次 ——
        #    而那样注入之后判据照样绿（当时还没查"量的是不是画的那一串"），
        #    这条注入就成了空转的。所以尾部带上 `style = qtyStyle,` 把范围钉死，
        #    行首缩进用捕获组带着走（别写死空格数）。
        r're:(\n\s*)"×" \+ qtyWithUnitConverted\(lp\.quantity, lp\.unit, conversions\),(\s*\n\s*style = qtyStyle,)',
        r'\1"×" + lp.quantity,\2',
        "小卡的数量也走共用拼法",
    ),
    (
        "⑨ 在 map 里调 rememberTextWidth（组合期槽位与列表长度对不上）",
        DETAIL,
        r"re:val qtyW = order\.orderProducts\.fold\(0\.dp\) \{ acc, l ->\s*"
        r"maxOf\(acc, rememberTextWidth\(\"×\" \+ qtyWithUnitConverted\(l\.quantity, l\.unit, conversions\), qtyStyle\)\)\s*\}",
        "val qtyW = order.orderProducts.map { "
        'rememberTextWidth("×" + qtyWithUnit(it.quantity, it.unit), qtyStyle) }.maxOrNull() ?: 0.dp',
        # ⚠️ 期望串要连 `⛔ ` 一起写：判据标签本身以它开头，少写这两个字符就永远匹配不上
        #    （第一次跑就是这么假红了一条）。
        "⛔ 没有人在 map 里调 rememberTextWidth",
    ),
    (
        "⑫ 量宽度时偷偷把单位去掉（那一列会按「×6」的宽度去装「×6 桶」→ 数字被裁掉）",
        DETAIL,
        r're:rememberTextWidth\("×" \+ qtyWithUnitConverted\(l\.quantity, l\.unit, conversions\), qtyStyle\)',
        'rememberTextWidth("×" + l.quantity, qtyStyle)',
        "量宽度用的那串文字与画出来的那串是同一个拼法",
    ),
    (
        "⑩ 设计规范里那一整节被删掉（文档过期比没有文档更糟）",
        DESIGN,
        r"re:### 4\.20[\s\S]*?(?=### 4\.21)",
        "",
        "06_DESIGN_SYSTEM.md 记着「数量带单位 + 分列右对齐」",
    ),
    (
        "⑪ 定位表里那条不再指向唯一的拼法（下一个人又会各写一份）",
        LOCATOR,
        # ⚠️ 锚点要**只在订单卡片那一行**出现的那个写法（`ui/common/…` 前缀）：
        #    光写函数名的话「单位换算」那一行也有它，删掉一处判据照样绿（实测空转过一轮）。
        "`ui/common/Units.kt::qtyWithUnitConverted`",
        "`ui/common/Units.kt::qtyWithUnit`",
        "08_CODE_LOCATOR.md 的订单卡片那一行提到单位与两列",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    if refuse_if_injecting("订单行两列反向验证"):
        return 1

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    lock_reverse_verify()
    caught = 0
    problems: list[str] = []
    try:
        for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
            path = ROOT / rel
            if not path.exists():
                problems.append(f"{name}：找不到 {rel}")
                print(f"\n[{i}] {name}\n  ❌ 找不到 {rel}")
                continue
            orig = path.read_bytes()
            orig_sha = sha(path)
            text = orig.decode("utf-8")
            eol = "\r\n" if "\r\n" in text else "\n"
            if eol != "\n":
                old = old.replace("\n", eol)
                new = new.replace("\n", eol)
            pat = old[3:] if old.startswith("re:") else re.escape(old)
            injected, n = re.subn(pat, new, text, count=1)
            if n != 1:
                problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:50]!r}）")
                print(f"\n[{i}] {name}\n  ❌ 锚点没命中，跳过（注入点腐烂了）")
                continue
            inj_bytes = injected.encode("utf-8")
            path.write_bytes(inj_bytes)
            try:
                rc, out = run_check()
            finally:
                now = path.read_bytes()
                if now != inj_bytes:
                    print(f"\n[{i}] {name}\n  🛑 有别的东西改了 {rel} —— **拒绝还原**，请人工处理！")
                    return 2
                path.write_bytes(orig)
            if sha(path) != orig_sha:
                print(f"\n[{i}] {name}\n  🛑 {rel} 还原后哈希对不上，停手")
                return 2

            hit = f"[!!]   {want}" in out
            if rc != 0 and hit:
                caught += 1
                print(f"\n[{i}] {name}\n  ✅ 被抓到（红线非零退出，命中「{want}」）")
            else:
                why = "红线居然还是绿的" if rc == 0 else f"退出了，但输出里没有「[!!]   {want}」"
                problems.append(f"{name}：{why}")
                print(f"\n[{i}] {name}\n  ❌ {why}")
    finally:
        unlock_reverse_verify()

    print("\n" + "=" * 60)
    print(f"{caught}/{len(INJECTIONS)} 种破坏方式被抓住")
    if problems:
        print("❌ 有漏网的：")
        for p in problems:
            print("   -", p)
        return 1
    print("✅ 全部注入都被抓住，且每个文件都按字节还原")
    return 0


if __name__ == "__main__":
    sys.exit(main())
