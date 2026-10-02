# -*- coding: utf-8 -*-
r"""反向验证「地址与联系人页三张卡的圈底动作 + 左删右编」这条红线**真的会红**（CHG-0012，2026-10-03）。

## 为什么这条要反向验证
它的判据几乎全是**正向存在性**判据（某段代码里必须有某个零件、某种顺序），这类判据有三种典型失效方式，
每一种都要单独证明会红：

1. **判据空转**：卡片被改名、动作被换回裸图标之后判据静默全绿。本脚本把删除换成裸 IconButton、
   把两个动作对调、把线路卡改成横排，逐条改坏。
2. **抽取失效 → 函数体取到空串**：「有没有 IconButton」「谁在前」在空串上全部恒真（没有 IconButton、
   index 都是 -1）。本脚本往这一页塞一张没有动作的新卡片，逼判据在"新卡片"上出声。
3. **只扫整个文件、不扫函数体**：三张卡的写法互相顶包 —— 联系人卡改坏了、地点卡还对，整文件
   count 看不出来。本脚本专挑一张卡改。

另外还有「共用件退化」那条：CardActionIcon 的默认圆底被改小、内部不再走 TintedIcon、
或者别处又冒出一份同名实现 —— 这三条都**不影响编译**，但卡片形态会一点点走样。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

用法：python _tools/qa/_reverse_verify_address_cards.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_address_cards.py"

AND = "android/app/src/main/java/com/tapmoay/sorders"
ADDR = AND + "/ui/shipper/AddressScreen.kt"
COMPONENTS = AND + "/ui/common/Components.kt"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
DOC = "docs/changes/CHG-0012.md"
REGISTRY = "docs/changes/README.md"

BT = chr(96)  # 反引号（本文件里出现反引号会把外面的模板串截断，一律用这个拼）

CARD_NAMES = ("AddressCard", "ContactCard", "LocationCard")
CARD_START = "private fun "
MARKERS = ("\n/**", "\n@Composable", "\nprivate fun ")


def card_span(s: str, name: str) -> tuple[int, int]:
    """一张卡（声明 + 函数体）在文件里的区间：从 private fun XxxCard( 到下一个顶层声明之前。"""
    i = s.find(CARD_START + name + "(")
    if i < 0:
        return (-1, -1)
    j = len(s)
    for marker in MARKERS:
        k = s.find(marker, i + 1)
        if k > 0:
            j = min(j, k)
    return (i, j)


def in_card(s: str, name: str, old: str, new: str, n: int = 1) -> str:
    """只在某一张卡的区间里做替换（其余两张卡写法一样，不许被顺手改到）。"""
    i, j = card_span(s, name)
    if i < 0:
        return s
    seg = s[i:j]
    if old not in seg:
        return s
    return s[:i] + seg.replace(old, new, n) + s[j:]


def call_end(s: str, i: int) -> int:
    """从 s[i] 开始的那个圆括号调用结束的下标（含行尾换行）。"""
    o = s.find("(", i)
    depth = 0
    for k in range(o, len(s)):
        if s[k] == "(":
            depth += 1
        elif s[k] == ")":
            depth -= 1
            if depth == 0:
                e = k + 1
                while e < len(s) and s[e] == " ":
                    e += 1
                if e < len(s) and s[e] == "\n":
                    e += 1
                return e
    return -1


def swap_actions(s: str, name: str) -> str:
    """把某个卡里的前两个 CardActionIcon 调用整块**对调**（位置纪律坏了、界面却完全正常）。"""
    i, j = card_span(s, name)
    if i < 0:
        return s
    seg = s[i:j]
    k1 = seg.find("CardActionIcon(")
    if k1 < 0:
        return s
    e1 = call_end(seg, k1)
    k2 = seg.find("CardActionIcon(", e1)
    if k2 < 0:
        return s
    e2 = call_end(seg, k2)
    a, b, gap = seg[k1:e1], seg[k2:e2], seg[e1:k2]
    return s[:i] + seg[:k1] + b + gap + a + seg[e2:] + s[j:]


def drop_line(s: str, needle: str) -> str:
    """整行删掉（登记簿那种一行一条的表格）。"""
    return "\n".join(ln for ln in s.split("\n") if needle not in ln)


def drop_section(s: str, heading: str) -> str:
    """整节删掉（从 heading 那一行到下一个同级 ### 之前）。"""
    i = s.find(heading)
    if i < 0:
        return s
    j = s.find("\n### ", i + len(heading))
    return s[:i] if j < 0 else s[:i] + s[j + 1:]


def in_decl(s: str, sig: str, old: str, new: str, n: int = 1) -> str:
    """只在某个函数的**声明 + 函数体**里替换（默认值写在参数表里，必须连声明一起要）。"""
    i = s.find(sig)
    if i < 0:
        return s
    b = s.find("{", i)
    depth = 0
    end = -1
    for k in range(b, len(s)):
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
            if depth == 0:
                end = k + 1
                break
    if end < 0:
        return s
    seg = s[i:end]
    if old not in seg:
        return s
    return s[:i] + seg.replace(old, new, n) + s[end:]


#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 联系人卡的删除换回裸 IconButton（用户：这个不行，他要一个图标，稍微圈一下）",
        ADDR,
        lambda s: in_card(s, "ContactCard", "CardActionIcon(", "IconButton(", 1),
        "裸图标按钮",
    ),
    (
        "② 线路卡的两个动作一起换回裸图标",
        ADDR,
        lambda s: in_card(s, "AddressCard", "CardActionIcon(", "IconButton(", 2),
        "裸图标按钮",
    ),
    (
        "③ 联系人卡两个动作对调（右＝编辑变成左＝编辑，界面上看不出来）",
        ADDR,
        lambda s: swap_actions(s, "ContactCard"),
        "顺序反了",
    ),
    (
        "④ 地点卡两个动作对调",
        ADDR,
        lambda s: swap_actions(s, "LocationCard"),
        "LocationCard 是横排左＝删除",
    ),
    (
        "⑤ 线路卡竖排对调（危险的那个跑到下面去 —— 用户点名两遍的顺序）",
        ADDR,
        lambda s: swap_actions(s, "AddressCard"),
        "竖排顺序反了",
    ),
    (
        "⑥ 联系人卡改成竖排（竖排是线路卡的特例，不许扩散）",
        ADDR,
        lambda s: in_card(
            s,
            "ContactCard",
            "Row(verticalAlignment = Alignment.CenterVertically) {",
            "Column(horizontalAlignment = Alignment.CenterHorizontally) {",
            1,
        ),
        "被改成竖排了",
    ),
    (
        "⑦ 线路卡那个删除不再是红的（危险动作失去颜色）",
        ADDR,
        lambda s: in_card(s, "AddressCard", "tint = MaterialTheme.colorScheme.error,", "tint = MaterialTheme.colorScheme.primary,", 1),
        "删除不是 error",
    ),
    (
        "⑧ 往这一页塞一张没有动作的新卡片（清点自己算 —— 新卡片必须被管住，先登记再谈纪律）",
        ADDR,
        lambda s: s + "\nprivate fun PreviewCard(x: Int) { Text(x.toString()) }\n",
        "PreviewCard",
    ),
    (
        "⑨ 卡片动作区自己再写一份控件（那个 36dp 圆底就会有两份画法）",
        ADDR,
        lambda s: s + "\nprivate fun ContactAction() { }\n",
        "又自己写了一份动作控件",
    ),
    (
        "⑩ 三张卡的回调签名被改（onDelete → onRemove）",
        ADDR,
        lambda s: in_card(s, "ContactCard", "onDelete: () -> Unit) {", "onRemove: () -> Unit) {", 1),
        "回调签名一个字没动",
    ),
    (
        "⑪ 顺手把联系人抽屉的调用点改名（本批说好一个字不动）",
        ADDR,
        lambda s: s.replace("ContactPickerSheet(", "ContactSheet("),
        "找不到 ContactPickerSheet(",
    ),
    (
        "⑫ 别处又冒出一份 CardActionIcon 实现（圈底动作不再只有一处实现）",
        ADDR,
        lambda s: s + "\nfun CardActionIcon(icon: Int) { }\n",
        "又出现第二份 CardActionIcon 定义",
    ),
    (
        "⑬ 圈底件的默认圆底被改小（36dp 不再是「圈一下」的那个圈）",
        COMPONENTS,
        lambda s: in_decl(s, "fun CardActionIcon(", "container: Dp = 36.dp", "container: Dp = 12.dp", 1),
        "默认尺寸被改了",
    ),
    (
        "⑭ 圈底件内部不再走 TintedIcon（一半描边一半实心，像两个人拼的）",
        COMPONENTS,
        lambda s: in_decl(s, "fun CardActionIcon(", "TintedIcon(", "Icon(", 1),
        "CardActionIcon 里没有 TintedIcon",
    ),
    (
        "⑮ 线路卡那条竖排来历注释被删（下一个人会顺手改成横排）",
        ADDR,
        lambda s: s.replace("删除在上、编辑在下", "删除和编辑随便排", 1),
        "来历被删了",
    ),
    (
        "⑯ 设计规范 4.2c 整节被删（规范是这条纪律唯一的文字出处）",
        DESIGN,
        lambda s: drop_section(s, "### 4.2c"),
        "规范那一段被删了",
    ),
    (
        "⑰ 登记簿里 CHG-0012 那一行被撤",
        REGISTRY,
        lambda s: drop_line(s, "| " + BT + "CHG-0012" + BT + " |"),
        "没登记",
    ),
    (
        "⑱ 文档少一节（九节是 _check_dev_spec 与本判据共同的底线）",
        DOC,
        lambda s: s.replace("## ⑨", "", 1),
        "文档缺节",
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
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
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
            print("  [OK] " + label + " → 报红")
        else:
            fails.append(label + f"：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print("  [MISS] " + label + " → 仍然全绿")

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
