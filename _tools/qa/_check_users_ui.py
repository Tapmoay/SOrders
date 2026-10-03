#!/usr/bin/env python
"""账号管理页（司机 / 货主 / 批发商三池共用的卡片）动作区按设计规范重做的机器判据 —— CHG-0019。

盯住四件事：

1. **卡片动作的形态**（规范 §4.2c :226-268）：卡片上的图标动作一律 `CardActionIcon` 圈底图标
   （12% 语义色圆底 + 同色图标）；⛔ 裸 `IconButton` 与平铺 `TextButton` 都不算
   （用户 2026-10-03 原话：「他就是一个**笔**啊，**这个不行**啊，他要一个图标啊，**稍微圈一下**」）。
2. **卡片动作的位置**：危险 / 异常放**最左**、编辑放**最右**（用户原话「编辑一定在右边，
   因为我们的**惯用手是右手**」）；编辑必须落在 `Spacer(Modifier.weight(1f))` **之后**。
3. **配色只走语义色 token**：编辑＝`NavBlue`、设/取消批发商＝`MemberGold`、转池＝目标池的模块色
   （`DriverLime` / `InventoryTeal`）、停用·启用＝`WarningAmber` / `Success`；
   ⛔ 不许再用 `colorScheme.error` 画动作、不许拿 `MoneyOrange`（"钱"的语义色）染动作。
4. **既有口径没被踩坏**：四个动作的回调与出现条件（批发商那个只在货主池 / 批发商池）、
   批发商池卡头的「定价」业务入口、司机池车辆行、搜索仍打服务端、`poolAccent` 三个深色、
   停用不删除。

为什么这些必须由机器盯着：

- 「左危险 / 右编辑」是个**位置**性质，审代码时最容易被「顺手挪一下」破坏，而挪错以后
  误触的代价是不对称的（右手拇指正好压在编辑上）；
- 「圈底还是裸图标」是个**形态**性质，两种画法都能编译、都能点，只有对照规范才看得出差别；
- 这一屏是三个池共用的，改一处就等于同时改三个角色看到的界面 —— 回归面比一个页面大。

R4-BOUNDARY-JUSTIFICATION: 这条判据不下沉到任何一层边界，因为被查的四件事**都是画法**，
  不是行为：动作画在左边还是右边、图标有没有圈底、用哪个色常量 —— 后端契约、领域类型、
  权限模型里都没有它们的位置（后端不知道卡片长什么样，也不该知道）。
  反向说：把「危险最左」塞进任何一层边界都无处安放，因为它不调用任何一层，
  边界根本看不见「按钮在左边还是右边」这件事。

用法：python _tools/qa/_check_users_ui.py  （--list 打一份人读清单）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_hints import Checker, read, strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
USERS = AND / "ui/dispatcher/UsersManageScreen.kt"
COMPONENTS = AND / "ui/common/Components.kt"
COLOR = AND / "ui/theme/Color.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_users_ui.py"
DOC = ROOT / "docs/changes/CHG-0019.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 反空转下限（文件被搬走 / 目录改名 / 扫描写坏时不许安静全绿）
MIN_KT_FILES = 200
MIN_USERS_CHARS = 29000
MIN_COLOR_CHARS = 2000
#: 卡片上应该有的圈底动作数（停用启用 / 批发商 / 转池 / 编辑）
CARD_ACTIONS = 4
#: 其中**不带字**的那一枚（只有它可以是纯图标）
UNLABELED = 1


def fun_span(src: str, sig: str, nxt: str) -> str:
    """抠出 [sig, nxt) 这两个顶层声明之间的函数体。"""
    i = src.find(sig)
    if i < 0:
        return ""
    j = src.find(nxt, i + len(sig))
    return src[i:] if j < 0 else src[i:j]


def main() -> int:
    if refuse_if_injecting("账号管理页动作判据"):
        return 1
    c = Checker()

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    c.section("0. 反空转（文件搬走 / 目录改名 / 扫描写坏时先喊）")
    missing = [p.name for p in (USERS, COMPONENTS, COLOR, DESIGN) if not p.exists()]
    c.ok("四个文件都在（UsersManageScreen / Components / Color.kt / 设计规范）",
         not missing, f"缺：{missing}")
    if missing:
        print("\n❌ 文件都不在，后面的判据没有意义")
        return 1
    raw = read(USERS)
    users = strip_comments(raw)
    comp = strip_comments(read(COMPONENTS))
    color = strip_comments(read(COLOR))
    n_kt = len(list(AND.rglob("*.kt")))
    c.ok(f"整棵源码树扫到了 {n_kt} 个 .kt（下限 {MIN_KT_FILES}）", n_kt >= MIN_KT_FILES,
         "目录改名了？那样「一处都没有」和「一处都没扫到」是同一个输出")
    c.ok(f"UsersManageScreen.kt 读到了内容（≥ {MIN_USERS_CHARS} 字符）",
         len(users) >= MIN_USERS_CHARS, f"实际 {len(users)}")
    c.ok(f"ui/theme/Color.kt 读到了内容（≥ {MIN_COLOR_CHARS} 字符）",
         len(color) >= MIN_COLOR_CHARS, f"实际 {len(color)}")
    c.ok("共用件 CardActionIcon 还在定义处（它没被改，只是被用）",
         "fun CardActionIcon(" in comp and "    container: Dp = 36.dp," in comp)
    c.ok("CardActionIcon 仍支持 label（圈底图标 + 文字那一形态）",
         "    label: String? = null," in comp)
    card = fun_span(users, "private fun UserManageCard(", "private fun poolAccent(")
    c.ok("抠出了账号卡片那一块（UserManageCard 函数体）", len(card) > 2000, f"实际 {len(card)} 字符")

    # ── 1. 四枚动作 + 位置 ───────────────────────────────────────────────
    c.section("1. 卡片动作：形态是圈底图标，位置是危险最左 / 编辑最右")
    n_act = card.count("CardActionIcon(")
    c.ok(f"卡片上恰好 {CARD_ACTIONS} 枚圈底动作（停用启用 / 批发商 / 转池 / 编辑）",
         n_act == CARD_ACTIONS, f"实际 {n_act} 枚")
    c.ok("停用 / 启用：Pause 与 PlayArrow 二选一，文案跟着状态走",
         "icon = if (u.isActive) Icons.Default.Pause else Icons.Default.PlayArrow" in card
         and 'contentDescription = if (u.isActive) "停用" else "启用"' in card
         and "onClick = onToggleActive," in card)
    c.ok("设 / 取消批发商：Stars 与 StarOutline 二选一（整块只在货主池与批发商池出现）",
         "icon = if (u.isMember) Icons.Default.Stars else Icons.Default.StarOutline" in card
         and 'contentDescription = if (u.isMember) "取消批发商" else "设为批发商"' in card
         and 'label = if (u.isMember) "取消批发商" else "设为批发商",' in card
         and "onClick = onToggleMember," in card)
    c.ok("转池：SwapHoriz，文案跟着当前角色走",
         "icon = Icons.Default.SwapHoriz," in card
         and 'contentDescription = if (u.role == "shipper") "转司机" else "转货主"' in card
         and 'label = if (u.role == "shipper") "转司机" else "转货主",' in card
         and "onClick = onSwapRole," in card)
    c.ok("编辑：Edit + label「编辑」",
         "icon = Icons.Default.Edit," in card and 'contentDescription = "编辑",' in card
         and 'label = "编辑",' in card and "onClick = onEdit," in card)
    i_danger = card.find("icon = if (u.isActive) Icons.Default.Pause")
    i_member = card.find("Icons.Default.Stars")
    i_swap = card.find("Icons.Default.SwapHoriz")
    i_weight = card.find("Spacer(Modifier.weight(1f))")
    i_edit = card.find("icon = Icons.Default.Edit,")
    c.ok("位置：四枚从左到右＝停用启用 → 批发商 → 转池 → 编辑",
         0 <= i_danger < i_member < i_swap < i_edit,
         f"偏移 danger={i_danger} member={i_member} swap={i_swap} edit={i_edit}")
    c.ok("危险 / 异常放最左（停用启用是第一枚，没有更左的动作）",
         0 <= i_danger == min(x for x in (i_danger, i_member, i_swap, i_edit) if x >= 0))
    c.ok("编辑在最右（落在 Spacer(Modifier.weight(1f)) 之后）—— 右＝惯用手那侧",
         0 < i_weight < i_edit, f"偏移 weight={i_weight} edit={i_edit}")
    c.ok("四枚动作在同一条 Row 里（中间没有被拆成第二行）",
         "Row(verticalAlignment = Alignment.CenterVertically) {" in card[:i_danger]
         and card.count("Spacer(Modifier.weight(1f))") == 1)
    c.ok("动作行与上面那块内容之间留 8dp（圈底圆比文字键高，贴着会像同一块）",
         "Spacer(Modifier.height(8.dp))" in card[:i_danger])
    n_size = card.count("size = 15.dp")
    n_cont = card.count("container = 30.dp")
    c.ok("四枚动作同一档尺寸（size 15 / container 30，与车辆页、账户管理页同一档）",
         n_size == CARD_ACTIONS and n_cont == CARD_ACTIONS,
         f"size {n_size} / container {n_cont}")

    # ── 2. 带字与配色 ────────────────────────────────────────────────────
    c.section("2. 带字与配色：三个动作带字，颜色全走语义色 token")
    n_label = len(re.findall(r"label = ", card))
    c.ok(f"四枚里恰好 {CARD_ACTIONS - UNLABELED} 枚带字（圈底图标 + 文字，不逼人靠猜）",
         n_label == CARD_ACTIONS - UNLABELED, f"实际 {n_label} 处 label")
    c.ok("唯一不带字的就是最左那个停用 / 启用（位置 + 暂停/播放 + 提醒/成功色已经说清）",
         "label = if (u.isActive)" not in card and 'label = "编辑"' in card)
    c.ok("编辑用 NavBlue（主操作色，不是随手一个蓝）", "tint = Color(NavBlue)," in card)
    c.ok("设 / 取消批发商用 MemberGold（批发商池的模块色）", "tint = Color(MemberGold)," in card)
    c.ok("转池用目标池的模块色（转司机＝DriverLime / 转货主＝InventoryTeal）",
         'tint = if (u.role == "shipper") Color(DriverLime) else Color(InventoryTeal),' in card)
    c.ok("停用 / 启用用 WarningAmber / Success（不是 colorScheme.error）",
         "tint = if (u.isActive) Color(WarningAmber) else Success," in card)
    c.ok("卡片动作里不再出现 MaterialTheme.colorScheme.error",
         "colorScheme.error" not in card, "老写法把停用画成了错误色")
    row_start = card.rfind("Spacer(Modifier.height(8.dp))", 0, i_danger)
    action_row = card[row_start:] if row_start >= 0 else ""
    c.ok("动作行里不许出现 MoneyOrange（那是「钱」的语义色，规范 :151 明说不许染按钮）",
         "MoneyOrange" not in action_row)
    c.ok("色常量都在 ui/theme/Color.kt 里有定义（不是就地手写的 0xFF…）",
         all(f"val {t} = 0xFF" in color
             for t in ("NavBlue", "MemberGold", "DriverLime", "InventoryTeal", "WarningAmber")))

    # ── 3. 卡头与老画法归零 ──────────────────────────────────────────────
    c.section("3. 卡头不再挂动作键，老的两种画法归零")
    c.ok("卡片区一个裸 IconButton 都没有（用户点名「这个不行」的就是它）",
         "IconButton(" not in card, f"卡片区还有 {card.count('IconButton(')} 处")
    n_icon_btn = len(re.findall(r"IconButton\(", users))
    c.ok("整个文件只剩返回键那一个 IconButton（它不是卡片动作）",
         n_icon_btn == 1 and "IconButton(onClick = onBack)" in users,
         f"实际 {n_icon_btn} 处")
    c.ok("卡片区一个 TextButton 都没有（三个文字键平铺已整行换掉）",
         "TextButton(" not in card, f"卡片区还有 {card.count('TextButton(')} 处")
    n_text_btn = len(re.findall(r"TextButton\(", users))
    c.ok("剩下的 TextButton 只有页头两个（批量调价 / 车辆）与抽屉里的全选 / 全不选",
         n_text_btn == 4, f"实际 {n_text_btn} 处")
    c.ok("批发商池卡头的「定价」业务入口还在（它不是通用卡片动作，留在卡头）",
         "Button(onClick = onOpenPricing, contentPadding = PaddingValues(horizontal = 12.dp))" in card
         and 'Text("定价")' in card)
    c.ok("卡头不再有第二个动作键：定价之后直接就是动作行（中间没有别的可点键）",
         card.find('Text("定价")') < i_danger)
    c.ok("整张卡仍然可点开编辑（动作行之外的那条通路没被砍）",
         "SectionCard(Modifier.clickable { onEdit() }) {" in card)

    # ── 4. 既有口径没被踩坏 ──────────────────────────────────────────────
    c.section("4. 既有口径没被踩坏（别的判据也钉着这些）")
    # ⚠️ 2026-10-03（BUG-0002 · E2E 报告 P1）：电话行从 `RosterPhoneRow(phone = u.phone,)`
    #    改成传账号的共用件 `RosterPhoneRowOf(u)` —— 软删账号落库的号码是
    #    `13923111638_del62` 这种内部值，卡上不该画它。钉的**意图不变**：卡头仍是
    #    「这个人是谁」（姓氏圆底 + 姓名 + 电话），只是电话那一行换了唯一实现。
    c.ok("卡头仍是「这个人是谁」：姓氏圆底 + 姓名 + 电话",
         "clip(CircleShape).background(accent.copy(alpha = 0.16f))" in card
         and "u.fullName.ifBlank { u.username }" in card and "RosterPhoneRowOf(u)" in card)
    c.ok("批发商徽章与「已停用」徽章都还在",
         "Surface(color = Color(0xFFFFF1C6)" in card and '"已停用"' in card)
    c.ok("司机池的车型 chip 与计费 chip 没动（计费仍优先显示后端算好的那句话）",
         "MiniChip(driverKindLabel(u.vehicleType), Color(NavBlue))" in card
         and "MiniChip(pay, Color(MoneyOrange))" in card and "u.paySummary.ifBlank {" in card)
    c.ok("司机池车辆行整块没动（可点的信息行，不是卡片动作）",
         'if (plates.isEmpty()) "未配车" else plates,' in card
         and 'if (plates.isEmpty()) "配车" else "换车 / 解绑",' in card
         and "onBindVehicle()" in card)
    c.ok("三个池的强调色没动（poolAccent 三个深色）",
         "0xFF5A6B00" in users and "0xFF0A3168" in users and "0xFF7A5900" in users)
    c.ok("搜索仍是服务端那一个（SearchField + vm.onQueryChange）",
         "SearchField(value = vm.query, onValueChange = { vm.onQueryChange(it) })" in users)
    c.ok("账号仍然只停用、不删除（本页不出现 repo.delete）", "repo.delete" not in users)
    c.ok("四个动作的回调签名都在（少一个就是有动作被悄悄删了）",
         all(f"    {n}: () -> Unit," in users
             for n in ("onEdit", "onToggleActive", "onToggleMember", "onSwapRole")))
    c.ok("KDoc 写清了这一批的口径（v3.46 / CHG-0019：为什么危险最左、为什么停用不配字）",
         "v3.46（CHG-0019）" in raw and "惯用手是右手" in raw)

    # ── 5. 接线 ──────────────────────────────────────────────────────────
    c.section("5. 接线：反向验证在、文档九节、登记簿与声明块有 CHG-0019")
    c.ok("反向验证脚本在（_tools/qa/_reverse_verify_users_ui.py）", REVERSE.exists(),
         "没有反向验证的判据＝没人证明它真的会红")
    doc = read(DOC) if DOC.exists() else ""
    c.ok("文档九节齐全（docs/changes/CHG-0019.md，认小节标题而不是字符）",
         all(("## " + s) in doc for s in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")),
         "文档缺节")
    c.ok("登记簿里有 CHG-0019 这一行（整行，不是一个链接里的字样）",
         bool(re.search(r"^\|\s*[\x60]?CHG-0019[\x60]?\s*\|", read(REGISTRY), re.M)),
         "没登记（别人不知道这个 ID 用掉了）")
    c.ok("工作声明页上有 CHG-0019 的声明块",
         "CHG-0019" in (read(CLAIM) if CLAIM.exists() else ""), "没声明就开工了")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：卡片动作四枚圈底图标（危险最左、编辑最右、三个带字）、"
          f"卡头不再挂动作键、配色全走语义色 token、批发商入口与车辆行没被动。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（账号管理页卡片动作 CHG-0019）==")
        print("1. 四枚 CardActionIcon：从左到右＝停用启用 / 批发商 / 转池 / 编辑，")
        print("   编辑在 Spacer(weight(1f)) 之后（右＝惯用手）、危险在最左，同一档 size 15 / container 30")
        print("2. 带字与配色：三枚带 label（停用那个不带）、NavBlue / MemberGold / 目标池模块色 / WarningAmber·Success，")
        print("   动作里不许出现 colorScheme.error 与 MoneyOrange")
        print("3. 老画法归零：卡片区 IconButton 与 TextButton 都是 0；「定价」留在卡头；整卡仍可点开编辑")
        print("4. 既有口径：徽章 / 车型与计费 chip / 车辆行 / poolAccent 三色 / 服务端搜索 / 只停用不删除 / 四个回调")
        print("5. 接线：反向验证脚本在、CHG-0019.md 九节、登记簿整行、声明页有块")
        sys.exit(0)
    sys.exit(main())
