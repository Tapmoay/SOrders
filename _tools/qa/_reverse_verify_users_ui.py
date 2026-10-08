# -*- coding: utf-8 -*-
r"""反向验证「账号管理页卡片动作按规范重做」这条红线真的会红（CHG-0019，2026-10-03）。

## 为什么这条要反向验证
本批改的全是**画法**，四种典型失效方式都不影响编译、也不影响功能：

1. **形态**（规范 §4.2c）：把圈底 CardActionIcon 换回裸 IconButton、把 label 拿掉 —— 界面照常能点，
   只有对照规范才看得出差别；用户 2026-10-03 原话就是「他就是一个笔啊，这个不行啊」。
2. **位置**：把编辑那枚挪回卡头、把危险那枚挪到最右、把 weight(1f) 删掉 —— 三种都是"顺手一改"，
   而误触的代价不对称（右手拇指正好压在编辑上）。
3. **配色语义**：拿 colorScheme.error 或 MoneyOrange（"钱"的语义色，规范 :151 明说不许染按钮）
   去画动作，编译照样过，只有下一个人对账时才发现色不达意。
4. **既有口径**：批发商池卡头的「定价」业务入口、司机池的车辆行、poolAccent 三个深色、
   服务端搜索、只停用不删除 —— 这几条是别的判据的命根子，动一下就是业务的事。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_users_ui.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_users_ui.py"

AND = "android/app/src/main/java/com/tapmoay/sorders"
USERS = AND + "/ui/dispatcher/UsersManageScreen.kt"
COMPONENTS = AND + "/ui/common/Components.kt"
COLOR = AND + "/ui/theme/Color.kt"
DOC = "docs/changes/CHG-0019.md"
REGISTRY = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"

BT = chr(96)  # 反引号
NL = chr(10)

# 动作行的 Row 前面那一行注释是唯一的：文件里还有另外两条 Row(verticalAlignment = ...)，
# 只按 Row 开头找会撞上卡片顶部那一条（那样注入就变成"挪到卡头"了，虽然也会报红，但不是这一条的意思）。
ACTION_ROW_ANCHOR = (
    "        //      别的动作都给字：三个池之间差一层语义就点错人。" + NL
    + "        Row(verticalAlignment = Alignment.CenterVertically) {" + NL
)
WEIGHT_ANCHOR = "            Spacer(Modifier.weight(1f))" + NL
PHONE_ANCHOR = "                Spacer(Modifier.height(4.dp))" + NL
DANGER_START = (
    "            CardActionIcon(" + NL
    + "                icon = if (u.isActive) Icons.Default.Pause"
)
MEMBER_START = (
    "            CardActionIcon(" + NL
    + "                icon = if (u.isMember) Icons.Default.Stars"
)
SWAP_START = (
    "            CardActionIcon(" + NL
    + "                icon = Icons.Default.SwapHoriz"
)
EDIT_START = (
    "            CardActionIcon(" + NL
    + "                icon = Icons.Default.Edit"
)

PENCIL_BLOCK = (
    "            IconButton(onClick = onEdit) {" + NL
    + '                Icon(Icons.Default.Edit, contentDescription = "编辑", '
    + "modifier = Modifier.size(18.dp))" + NL
    + "            }" + NL
)
TEXTBUTTON_BLOCK = (
    "            TextButton(onClick = onSwapRole) { Text(" + chr(34) + "转司机" + chr(34) + ") }" + NL
)
PRICING_BLOCK = (
    "            if (pool == UserPool.MEMBERS) {" + NL
    + "                Button(onClick = onOpenPricing, contentPadding = PaddingValues(horizontal = 12.dp)) {" + NL
    + '                    Text("定价")' + NL
    + "                }" + NL
    + "            }" + NL
)


def drop_line(s: str, needle: str) -> str:
    """整行删掉（表格行、单行声明）。"""
    return NL.join(ln for ln in s.split(NL) if needle not in ln)


def cut_block(s: str, marker: str, tail: str = NL + "            )" + NL) -> tuple[str, str | None]:
    """从含 marker 的那一行起，切出到 tail 结束的一块；返回 (剩下的, 切下的)。"""
    i = s.find(marker)
    if i < 0:
        return s, None
    j = s.find(tail, i)
    if j < 0:
        return s, None
    end = j + len(tail)
    return s[:i] + s[end:], s[i:end]


def paste_after(s: str, anchor: str, block: str) -> str:
    k = s.find(anchor)
    if k < 0:
        return s
    k += len(anchor)
    return s[:k] + block + s[k:]


def paste_before(s: str, anchor: str, block: str) -> str:
    k = s.find(anchor)
    if k < 0:
        return s
    return s[:k] + block + s[k:]


def cut_only(s: str, marker: str) -> str:
    """整块删掉（锚点没了就原样返回，让主流程报 SKIP）。"""
    rest, block = cut_block(s, marker)
    return s if block is None else rest


def move_edit_first(s: str) -> str:
    """把「编辑」那枚挪到动作行最前面（位置判据必须抓到）。"""
    rest, block = cut_block(s, EDIT_START)
    if block is None:
        return s
    return paste_after(rest, ACTION_ROW_ANCHOR, block)


def move_danger_last(s: str) -> str:
    """把「停用 / 启用」挪到 weight(1f) 之后（危险不再最左）。"""
    rest, block = cut_block(s, DANGER_START)
    if block is None:
        return s
    return paste_after(rest, WEIGHT_ANCHOR, block)


def swap_for_textbutton(s: str) -> str:
    """转池那枚退回老画法：一个平铺 TextButton。"""
    rest, block = cut_block(s, SWAP_START)
    if block is None:
        return s
    return paste_after(rest, ACTION_ROW_ANCHOR, TEXTBUTTON_BLOCK)


CASES: list[tuple[str, str, object, str]] = [
    (
        "① 卡头又挂回一个裸 18dp 铅笔（用户点名「这个不行」的画法）",
        USERS,
        lambda s: paste_before(s, PHONE_ANCHOR, PENCIL_BLOCK),
        "裸 IconButton",
    ),
    (
        "② 编辑那枚被挪回动作行最前面（位置判据）",
        USERS,
        move_edit_first,
        "编辑在最右",
    ),
    (
        "③ 危险那枚被挪到最右（提醒色的大键压在右手拇指下）",
        USERS,
        move_danger_last,
        "危险 / 异常放最左",
    ),
    (
        "④ 给停用那枚也配上文字（四个带字的一行在 347dp 里装不下）",
        USERS,
        lambda s: s.replace(
            "                onClick = onToggleActive," + NL,
            "                onClick = onToggleActive," + NL
            + '                label = if (u.isActive) "停用" else "启用",' + NL,
            1,
        ),
        "不带字的就是最左那个",
    ),
    (
        "⑤ 转池那枚的字被拿掉（用户不知道要转到哪去）",
        USERS,
        lambda s: s.replace('                label = if (u.role == "shipper") "转司机" else "转货主",' + NL, "", 1),
        "恰好 3 枚带字",
    ),
    (
        "⑥ 停用改用 MaterialTheme.colorScheme.error（错误色当提醒色）",
        USERS,
        lambda s: s.replace(
            "                tint = if (u.isActive) Color(WarningAmber) else Success," + NL,
            "                tint = MaterialTheme.colorScheme.error," + NL,
            1,
        ),
        "colorScheme.error",
    ),
    (
        "⑦ 编辑改用 MoneyOrange（拿「钱」的语义色染按钮）",
        USERS,
        lambda s: s.replace(
            "                tint = Color(NavBlue)," + NL + "                onClick = onEdit," + NL,
            "                tint = Color(MoneyOrange)," + NL + "                onClick = onEdit," + NL,
            1,
        ),
        "编辑用 NavBlue",
    ),
    (
        "⑧ 转池色写死成 DriverLime（转到货主池也显示司机色）",
        USERS,
        lambda s: s.replace(
            '                tint = if (u.role == "shipper") Color(DriverLime) else Color(InventoryTeal),' + NL,
            "                tint = Color(DriverLime)," + NL,
            1,
        ),
        "转池用目标池的模块色",
    ),
    (
        "⑨ 批发商那枚改用主操作蓝（批发商金被抹掉）",
        USERS,
        lambda s: s.replace("                tint = Color(MemberGold)," + NL, "                tint = Color(NavBlue)," + NL, 1),
        "批发商池的模块色",
    ),
    (
        "⑩ 四枚动作退回默认尺寸（不再与车辆页、账户页同一档）",
        USERS,
        lambda s: s.replace("size = 15.dp," + NL, "", 4),
        "同一档尺寸",
    ),
    (
        "⑪ 动作行与上面内容之间的 8dp 间隔被吃掉",
        USERS,
        lambda s: s.replace(
            "        Spacer(Modifier.height(8.dp))" + NL + "        // ---- 卡片动作（规范 §4.2c）",
            "        // ---- 卡片动作（规范 §4.2c）",
            1,
        ),
        "留 8dp",
    ),
    (
        "⑫ 编辑前面那个 Spacer(weight(1f)) 被删（编辑跑回左边）",
        USERS,
        lambda s: s.replace(WEIGHT_ANCHOR, "", 1),
        "落在 Spacer(Modifier.weight(1f)) 之后",
    ),
    (
        "⑬ 转池那枚退回文字键 TextButton（老画法之一）",
        USERS,
        swap_for_textbutton,
        "卡片区一个 TextButton 都没有",
    ),
    (
        "⑭ 转池动作整块被删（三个池之间不能转了）",
        USERS,
        lambda s: cut_only(s, SWAP_START),
        "恰好 4 枚圈底动作",
    ),
    (
        "⑮ 卡片签名里少了一个回调 onToggleActive（有动作被悄悄删）",
        USERS,
        lambda s: s.replace("    onToggleActive: () -> Unit," + NL, "", 1),
        "四个动作的回调签名都在",
    ),
    (
        "⑯ 司机池车辆行被「精简」成永远显示未配车",
        USERS,
        lambda s: s.replace('                    if (plates.isEmpty()) "未配车" else plates,', '                    "未配车",', 1),
        "车辆行整块没动",
    ),
    (
        "⑰ poolAccent 的货主深蓝被换成主操作蓝",
        USERS,
        lambda s: s.replace("    UserPool.SHIPPERS -> Color(0xFF0A3168)", "    UserPool.SHIPPERS -> Color(0xFF1E6FFF)", 1),
        "poolAccent 三个深色",
    ),
    (
        "⑱ 搜索退回手拼搜框（不再打服务端那一个）",
        USERS,
        lambda s: s.replace(
            "SearchField(value = vm.query, onValueChange = { vm.onQueryChange(it) })",
            "SoTextField(value = vm.query, onValueChange = { vm.onQueryChange(it) })",
            1,
        ),
        "搜索仍是服务端那一个",
    ),
    (
        "⑲ 又冒出删除账号的写法（本页只停用不删除）",
        USERS,
        lambda s: s + NL + "private fun injected(x: Any) { repo.delete(x) }" + NL,
        "只停用、不删除",
    ),
    (
        "⑳ 批发商徽章的底色被改（黄底金字的对应关系丢了）",
        USERS,
        lambda s: s.replace("Surface(color = Color(0xFFFFF1C6)", "Surface(color = Color(0xFFFFE0A3)", 1),
        "批发商徽章与「已停用」徽章都还在",
    ),
    (
        "㉑ 计费 chip 改成界面自己拼的一句话（与账单同源那一条断了）",
        USERS,
        lambda s: s.replace(
            "if (pay.isNotBlank()) MiniChip(pay, Color(MoneyOrange))",
            'if (pay.isNotBlank()) MiniChip("按单计费", Color(MoneyOrange))',
            1,
        ),
        "车型 chip 与计费 chip 没动",
    ),
    (
        "㉒ 批发商池卡头的「定价」入口被删（业务入口被当成旧画法清掉）",
        USERS,
        lambda s: s.replace(PRICING_BLOCK, "", 1),
        "「定价」业务入口还在",
    ),
    (
        "㉓ 整卡可点开编辑被砍（只剩动作行一条通路）",
        USERS,
        lambda s: s.replace("SectionCard(Modifier.clickable { onEdit() }) {", "SectionCard(Modifier) {", 1),
        "动作行之外的那条通路没被砍",
    ),
    (
        "㉔ 停用那枚的内容描述写死（启用时读屏也说「停用」）",
        USERS,
        lambda s: s.replace(
            '                contentDescription = if (u.isActive) "停用" else "启用",',
            '                contentDescription = "停用",',
            1,
        ),
        "停用 / 启用：Pause 与 PlayArrow 二选一",
    ),
    (
        "㉕ 编辑那枚的图标换成别的（Edit 这一个记号丢了）",
        USERS,
        lambda s: s.replace(
            "                icon = Icons.Default.Edit," + NL + '                contentDescription = "编辑",',
            "                icon = Icons.Default.Delete," + NL + '                contentDescription = "编辑",',
            1,
        ),
        "编辑：Edit + label「编辑」",
    ),
    (
        "㉖ KDoc 里的本批口径被写回老编号",
        USERS,
        lambda s: s.replace("v3.46（CHG-0019）", "v3.45", 1),
        "KDoc 写清了这一批的口径",
    ),
    (
        "㉗ 共用件 CardActionIcon 被改名（圈底动作的唯一定义处没了）",
        COMPONENTS,
        lambda s: s.replace("fun CardActionIcon(", "fun CardActionIconX(", 1),
        "共用件 CardActionIcon 还在定义处",
    ),
    (
        "㉘ 共用件不再支持 label（圈底图标 + 文字那一形态没了）",
        COMPONENTS,
        lambda s: s.replace("    label: String? = null," + NL, "", 1),
        "CardActionIcon 仍支持 label",
    ),
    (
        "㉙ 语义色 token 从 Color.kt 里被改名（就地手写 0xFF 的入口）",
        COLOR,
        # ⚠️ 2026-10-09 / CHG-0091：主操作色换绿后这一行成了别名 `val NavBlue = ThemeGreen`
        #    （旧名保留，全仓 16 处调用点不动）。锚点跟着改成现在的真实写法；
        #    ⛔ 只改锚点，断言的意图一个字没变：token 在 Color.kt 里被改名 ⇒ 判据必须报红。
        lambda s: s.replace("val NavBlue = ThemeGreen", "val NavBlueX = ThemeGreen", 1),
        "色常量都在 ui/theme/Color.kt 里有定义",
    ),
    (
        "㉚ 登记簿里 CHG-0019 那一行被撤",
        REGISTRY,
        lambda s: drop_line(s, "| " + BT + "CHG-0019" + BT + " |"),
        "不是一个链接里的字样",
    ),
    (
        "㉛ 文档少一节（九节是 _check_dev_spec 与本判据共同的底线）",
        DOC,
        lambda s: s.replace("## ⑨", "", 1),
        "文档九节齐全",
    ),
    (
        "㉜ 声明页上的 CHG-0019 声明块被撤",
        CLAIM,
        lambda s: s.replace("CHG-0019", "CHG-XXXX"),
        "工作声明页上有",
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
