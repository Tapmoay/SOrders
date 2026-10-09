#!/usr/bin/env python
"""车辆管理页（列表与卡片）按设计规范重做的机器判据 —— CHG-0016 第 1 批。

盯住四件事：

1. **黄绿只有一个定义**：`DriverLime` / `OnDriverLime` 住在 `ui/theme/Color.kt`，规范 §2 模块色表
   那一格指向它；除定义处外，全库不许再手写 `0xFF72863F` / `0xFF33380F`。
2. **卡片动作的形态与位置**（规范 §4.2c）：卡片上的图标动作一律 `CardActionIcon` 圈底图标；
   左＝反向 / 警示（警示放最左）、右＝编辑；⛔ 裸 `IconButton` 不算（用户原话「这个不行」）。
3. **搜索框按人搜只有一份**（规范 §4.4）：本页三个搜索框全走 `SearchField`；搜车牌那个仍然写
   自己的提示语，按人搜那个不写（默认取 `UserSearch.HINT`，这样「后 4 位也行」只有一处说明）。
4. **既有约束没被踩坏**：`capacityText` / `attrsFor` / `VEHICLE_TYPES`（计费口径的文字）/
   三个 MiniChip / 只停用不删除 / 司机搜索走 `UserSearch.filter` 一份口径。

为什么这些必须由机器盯着：

- 色值的「只许一处」是**跨文件**性质：谁都能在任意文件里再写一遍 `Color(0xFF72863F)`，
  编译不报错、界面照样好看，只有下一个人改色时才发现少改了一处；
- 「左＝反向 / 右＝编辑」是个**位置**性质，审代码时最容易被「顺手挪一下」破坏；
- `SearchField` 与 `SoTextField` 的差别（✕ 一键清空、宽高口径）肉眼分不出来，
  规范 §4.4 记的原始抱怨正是「同一件事两种画法」。

R4-BOUNDARY-JUSTIFICATION: 这条判据不下沉到任何一层边界，因为被查的四件事**都是画法**，
  不是行为：颜色写在哪个文件、动作画在卡片左边还是右边、搜索框用哪个控件 —— 后端契约、
  领域类型、权限模型里都没有它们的位置（后端不知道卡片长什么样，也不该知道）。
  反向说：把 DriveLime 塞进 Color.kt 不能让任何一条边界去承担「谁都不许再手写这个色值」，
  因为手写色值不会调用任何一层，边界根本看不见它。

用法：python _tools/qa/_check_vehicle_ui.py  （--list 打一份人读清单）
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
VEHICLE = AND / "ui/dispatcher/VehicleManageScreen.kt"
USERS = AND / "ui/dispatcher/UsersManageScreen.kt"
COLOR = AND / "ui/theme/Color.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_vehicle_ui.py"
DOC = ROOT / "docs/changes/CHG-0016.md"
REGISTRY = ROOT / "docs/changes/README.md"

#: 黄绿与它底上那个字：**定义只有一份**（规范 §2「一个概念一个色」）
RAW_LIME = "0xFF72863F"
RAW_ON_LIME = "0xFF33380F"
#: 目录下 .kt 文件数下限（改坏扫描 / 目录改名时不许安静全绿）
MIN_KT_FILES = 200
MIN_VEHICLE_CHARS = 30000
MIN_USERS_CHARS = 25000
MIN_COLOR_CHARS = 2000
#: 卡片上应该有的三枚圈底动作（解绑 / 停用启用 / 编辑）
CARD_ACTIONS = 3


def fun_span(src: str, sig: str) -> str:
    """抠出一个顶层 `private fun X(` / `internal fun X(` 的函数体（到下一个成员为止）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    j = len(src)
    for marker in ("\nprivate fun ", "\ninternal fun ", "\nfun "):
        k = src.find(marker, i + len(sig))
        if k >= 0:
            j = min(j, k)
    return src[i:j]


def call_args(src: str, start: int) -> str:
    """从 `X(` 的开括号起按括号配平取实参文本。"""
    i = src.find("(", start)
    if i < 0:
        return ""
    depth = 0
    for k in range(i, len(src)):
        ch = src[k]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return src[i : k + 1]
    return ""


def raw_lime_outside_color() -> dict[str, int]:
    """全库（除 Color.kt）还手写着黄绿 / 黄绿底字色的文件 → 出现次数。"""
    hits: dict[str, int] = {}
    for p in AND.rglob("*.kt"):
        if p == COLOR:
            continue
        src = strip_comments(read(p))
        n = src.count(RAW_LIME) + src.count(RAW_ON_LIME)
        if n:
            hits[str(p.relative_to(AND)).replace("\\", "/")] = n
    return hits


def design_module_rows(text: str) -> list[tuple[str, str, str]]:
    """规范 §2 模块语义色表：(模块, 色, 常量列)。表尾到下一个 `## ` 为止。"""
    i = text.find("模块语义色")
    if i < 0:
        return []
    # ⚠️ 表尾必须停在小节边界上：§2 里紧跟着的「线路语义色」也是一张三列的表，
    #    只截到下一个 `## ` 会把它一起吞进来（它的表头「常量」会被当成一个色号名）。
    ends = [k for k in (text.find("\n### ", i), text.find("\n## ", i)) if k > 0]
    j = min(ends) if ends else len(text)
    body = text[i:j]
    rows: list[tuple[str, str, str]] = []
    for line in body.splitlines():
        m = re.match(r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*" , line)
        if m and "---" not in line and "模块" not in m.group(1) and m.group(3).strip() != "常量":
            rows.append((m.group(1).strip(), m.group(2).strip(), m.group(3).strip()))
    return rows


def main() -> int:
    if refuse_if_injecting("车辆管理页判据"):
        return 1
    c = Checker()

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    c.section("0. 反空转（文件搬走 / 目录改名 / 扫描写坏时先喊）")
    missing = [p.name for p in (VEHICLE, USERS, COLOR, DESIGN) if not p.exists()]
    c.ok("四个文件都在（VehicleManageScreen / UsersManageScreen / Color.kt / 设计规范）",
         not missing, f"缺：{missing}")
    if missing:
        print("\n❌ 文件都不在，后面的判据没有意义")
        return 1
    design = read(DESIGN)
    vehicle = strip_comments(read(VEHICLE))
    users = strip_comments(read(USERS))
    color = strip_comments(read(COLOR))
    n_kt = len(list(AND.rglob("*.kt")))
    c.ok(f"整棵源码树扫到了 {n_kt} 个 .kt（下限 {MIN_KT_FILES}）", n_kt >= MIN_KT_FILES,
         "目录改名了？那样「一个手写色值都没有」和「一个都没扫到」是同一个输出")
    c.ok(f"VehicleManageScreen.kt 读到了内容（≥ {MIN_VEHICLE_CHARS} 字符）",
         len(vehicle) >= MIN_VEHICLE_CHARS, f"实际 {len(vehicle)}")
    c.ok(f"UsersManageScreen.kt 读到了内容（≥ {MIN_USERS_CHARS} 字符）",
         len(users) >= MIN_USERS_CHARS, f"实际 {len(users)}")
    c.ok(f"ui/theme/Color.kt 读到了内容（≥ {MIN_COLOR_CHARS} 字符）",
         len(color) >= MIN_COLOR_CHARS, f"实际 {len(color)}")

    # ── 1. 黄绿只有一个定义 ──────────────────────────────────────────────
    c.section("1. 黄绿只有一个定义（规范 §2「一个概念一个色，定义只有一处」）")
    c.ok("Color.kt 里定义了 val DriverLime（司机管理 / 车辆台账：黄绿）",
         re.search(r"^val DriverLime = 0xFF72863FL", color, re.M) is not None,
         "色值该住在 ui/theme/Color.kt，而不是各页各写一遍")
    c.ok("Color.kt 里定义了 val OnDriverLime（黄绿底上的字）",
         re.search(r"^val OnDriverLime = 0xFF33380FL", color, re.M) is not None,
         "白字压在黄绿上只有 1.4:1，读不出来")
    raw = raw_lime_outside_color()
    c.ok("除 Color.kt 外全库没有再手写 0xFF72863F / 0xFF33380F", not raw,
         f"这些文件还手写着：{raw} —— 换成 Color(DriverLime) / Color(OnDriverLime)")
    c.ok("本文件的模块色常量指向 token（VehicleAccent = Color(DriverLime)）",
         "internal val VehicleAccent = Color(DriverLime)" in vehicle)
    n_raw = vehicle.count("Color(0xFF")
    c.ok("本文件一个手写 0xFF 色值都没有", n_raw == 0, f"还有 {n_raw} 处")
    rows = design_module_rows(design)
    c.ok(f"规范 §2 模块色表读到了 {len(rows)} 行（**算出来的**，不是硬编码）", len(rows) >= 10,
         "表被改名 / 搬家了？那样下面两条会一起失效")
    named = [tok for _mod, _col, tok in rows if tok and tok != "-"]
    undefined = [t for t in named if re.search(r"^val " + re.escape(t) + " =", color, re.M) is None]
    c.ok("表里非「-」的常量名都真在 Color.kt 里有定义（表与代码不许对不上）", not undefined,
         f"Color.kt 里找不到：{undefined}")
    lime_rows = [mod for mod, _col, tok in rows if tok == "DriverLime"]
    c.ok("「司机管理」那一格写的是 DriverLime，而且只此一行", lime_rows == ["司机管理"],
         f"实际：{lime_rows} —— 一个色只归一个模块（⛔ 不许借去第二个语义）")

    # ── 2. 卡片动作：形态与位置 ──────────────────────────────────────────
    c.section("2. 卡片动作：圈底 + 左反向右编辑（规范 §4.2c）")
    card = fun_span(vehicle, "private fun VehicleCard(")
    c.ok("认出了 VehicleCard 这块", len(card) >= 800, f"实际 {len(card)} 字符")
    n_icon_btn = vehicle.count("IconButton(")
    c.ok("本文件不再有裸 IconButton（用户点名「这个不行」的那种）", n_icon_btn == 0,
         f"还有 {n_icon_btn} 处")
    n_text_btn = card.count("TextButton(")
    c.ok("卡片里不再有文字按钮（动作全走圈底图标）", n_text_btn == 0, f"还有 {n_text_btn} 处")
    n_act = len(re.findall(r"CardActionIcon\(", card))
    c.ok(f"卡片上恰好 {CARD_ACTIONS} 枚圈底动作（解绑 / 停用启用 / 编辑）", n_act == CARD_ACTIONS,
         f"实际 {n_act} 枚")
    c.ok("解绑：LinkOff + 「解绑司机」 + label「解绑」",
         "icon = Icons.Default.LinkOff" in card and 'contentDescription = "解绑司机"' in card
         and 'label = "解绑"' in card)
    c.ok("停用 / 启用：Pause 与 PlayArrow 二选一，文案跟着状态走",
         "icon = if (v.isActive) Icons.Default.Pause else Icons.Default.PlayArrow" in card
         and 'label = if (v.isActive) "停用" else "启用"' in card)
    c.ok("编辑：Edit + label「编辑」",
         "icon = Icons.Default.Edit" in card and 'label = "编辑"' in card)
    i_unbind = card.find("icon = Icons.Default.LinkOff")
    i_toggle = card.find("Icons.Default.Pause")
    i_weight = card.find("Spacer(Modifier.weight(1f))")
    i_edit = card.find("icon = Icons.Default.Edit")
    c.ok("位置：编辑在最右（Spacer(weight) 之后）—— 右＝惯用手那侧",
         i_weight > 0 and i_edit > i_weight > i_toggle > i_unbind >= 0,
         f"偏移 unbind={i_unbind} toggle={i_toggle} weight={i_weight} edit={i_edit}")
    c.ok("警示放最左（解绑排在停用之前）", 0 <= i_unbind < i_toggle)
    n_label = len(re.findall(r"label = ", card))
    c.ok("三枚动作都带文字（圈底图标 + label，不逼人靠猜）", n_label >= CARD_ACTIONS,
         f"实际 {n_label} 处 label")
    n_size = card.count("size = 15.dp")
    n_cont = card.count("container = 30.dp")
    c.ok("三枚动作同一档尺寸（size 15 / container 30，跟账户管理学的那一档）",
         n_size == CARD_ACTIONS and n_cont == CARD_ACTIONS, f"size {n_size} / container {n_cont}")
    c.ok("卡片本身仍可点开编辑", "SectionCard(Modifier.clickable { onEdit() })" in card)
    c.ok("解绑仍有二次确认（危险动作不许一点就走）",
         "onUnbind = { vm.confirmUnbind = v }" in vehicle
         and "DangerConfirmDialog(" in vehicle
         and "vm.confirmUnbind?.let { v ->" in vehicle)
    c.ok("司机行尾不再写「换 / 解绑」（入口写着解绑、点下去却只是开弹层）",
         "换 / 解绑" not in vehicle and "换司机" in vehicle)

    # ── 3. 搜索框：按人搜只有一份 ────────────────────────────────────────
    c.section("3. 搜索框：按人搜只有一份（规范 §4.4）")
    n_so = vehicle.count("SoTextField(")
    c.ok("本文件不再有 SoTextField（换成了共用 SearchField）", n_so == 0, f"还有 {n_so} 处")
    n_sf = len(re.findall(r"(?<!fun )SearchField\(", vehicle))
    c.ok("三个搜索框全走 SearchField（列表 / 抽屉司机 / 选车）", n_sf == 3, f"实际 {n_sf} 处")
    c.ok("列表那个仍然搜车牌（placeholder「搜车牌或司机」没丢）",
         'placeholder = "搜车牌或司机"' in vehicle)
    drv_args = ""
    for m_sf in re.finditer(r"(?<!fun )SearchField\(", vehicle):
        seg_sf = call_args(vehicle, m_sf.start())
        if "value = vm.driverQuery" in seg_sf:
            drv_args = seg_sf
            break
    c.ok("按人搜那个不写自己的提示语（默认取 UserSearch.HINT：全 App 只有一处说明）",
         bool(drv_args) and "placeholder" not in drv_args,
         "各页各写一句提示语 = 规范 §4.4 要治的那个病")
    c.ok("匹配仍走 UserSearch.filter（一份口径）",
         "UserSearch.filter(" in vehicle and "vm.driverQuery," in vehicle)

    # ── 4. 配色：不借别的模块的色 ────────────────────────────────────────
    c.section("4. 配色：不借别的模块的色（规范 §2）")
    c.ok("本文件不再出现 MoneyOrange（那是账本模块的金橙）", "MoneyOrange" not in vehicle,
         "借色的后果：同一个金橙在车辆页和账本里是两个含义")
    n_warn = vehicle.count("Color(WarningAmber)")
    c.ok("提醒色改用通用 WarningAmber", n_warn >= 2, f"实际 {n_warn} 处")
    summary = fun_span(vehicle, "private fun VehicleSummary(")
    c.ok("汇总卡里那行「还没绑司机」的提醒色在（VehicleSummary 内）",
         "Color(WarningAmber)" in summary)
    n_users_raw = users.count(RAW_LIME)
    c.ok("司机管理页不再手写黄绿", n_users_raw == 0, f"还有 {n_users_raw} 处")
    n_users_tok = users.count("Color(DriverLime)")
    c.ok("司机管理页也走 token（Color(DriverLime) 至少 2 处）", n_users_tok >= 2,
         f"实际 {n_users_tok} 处")
    c.ok("司机管理页的「车」标签也走 token（Color(NavBlue)）",
         "MiniChip(driverKindLabel(u.vehicleType), Color(NavBlue))" in users)

    # ── 5. 既有约束没被踩坏 ─────────────────────────────────────────────
    c.section("5. 既有约束没被踩坏（别的判据也钉着这些）")
    c.ok("卡片仍用 capacityText(v.attrs) 显示载重 / 容积（不许自己拼）",
         "capacityText(v.attrs)" in card)
    c.ok("属性表仍按 draftBody 取（attrsFor(vm.draftBody)）", "attrsFor(vm.draftBody)" in vehicle)
    # 取值集仍是那三档（一个字不许扩）；顺序与默认值由 CHG-0028 改并由
    # _check_wording_consistency.py 单独钉，所以这里只按集合比对。
    _vt = re.search(r"internal val VEHICLE_TYPES = listOf\(([^)]*)\)", vehicle)
    _vt_pairs = re.findall(r'"([a-z]+)" to "([^"]+)"', _vt.group(1)) if _vt else []
    c.ok("车型取值表仍是计费口径那三档（取值集不许扩，_check_vehicle_attrs.py 钉着）",
         set(_vt_pairs) == {("small", "小货车"), ("large", "大货车"), ("trailer", "挂车")},
         f"实际解出 {_vt_pairs}")
    c.ok("三个信息标签都还在（车型 / 车身型式 / 停用）",
         "MiniChip(vehicleTypeLabel(v.vehicleType)" in card
         and "MiniChip(v.bodyLabel, VehicleAccent)" in card
         and 'MiniChip("停用"' in card)
    c.ok("本页仍然只停用、不删除（不出现 repo.delete）", "repo.delete" not in vehicle)

    # ── 6. 接线 ──────────────────────────────────────────────────────────
    c.section("6. 接线：反向验证在、文档九节、登记簿有 CHG-0016")
    c.ok("反向验证脚本在（_tools/qa/_reverse_verify_vehicle_ui.py）", REVERSE.exists(),
         "没有反向验证的判据＝没人证明它真的会红")
    doc = read(DOC) if DOC.exists() else ""
    # ⚠️ 2026-10-09 复核：这里原来判的是「裸圈码在不在全文里」。但 CHG-0016 的 ⑦ 节表格里
    #    列反向验证条目时也用了圈码（「⑨ 撑开左右两端的 Spacer 被删」），于是
    #    `## ⑨` 那一行被整行删掉之后，⑨ 这个字符在全文里**还在** ⇒ 判据不红、
    #    反验第 ⑲ 条恒 MISS（实测踩到）。九节指的是**小节标题**，所以改成只看标题形式。
    c.ok("文档九节齐全（docs/changes/CHG-0016.md）",
         all(re.search(r"^## " + s, doc, re.M) for s in
             ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")), "文档缺节")
    c.ok("登记簿里有 CHG-0016 这一行（整行，不是一个链接里的字样）",
         bool(re.search(r"^\|\s*[\x60]?CHG-0016[\x60]?\s*\|", read(REGISTRY), re.M)),
         "没登记（别人不知道这个 ID 用掉了）")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：黄绿只有一处定义、卡片动作左反向右编辑且都是圈底图标，"
          f"三个搜索框统一走 SearchField、不借别模块的色、计费口径与属性表没被动。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（车辆管理页列表与卡片 CHG-0016）==")
        print("1. 黄绿只有一个定义：Color.kt 的 DriverLime / OnDriverLime、规范 §2 表那一格指向它、")
        print("   除定义处外全库不许再手写 0xFF72863F / 0xFF33380F（跨文件性质，肉眼审不出来）")
        print("2. 卡片动作：三枚 CardActionIcon、都带 label、size/container 同档、")
        print("   位置＝警示最左 / 编辑最右（Spacer(weight) 之后）、裸 IconButton 归零")
        print("3. 搜索框：三个全走 SearchField、搜车牌那个仍写自己的话、按人搜那个不写（默认 UserSearch.HINT）")
        print("4. 配色不借：MoneyOrange 归零、提醒色走 WarningAmber、司机管理页也走 token")
        print("5. 既有约束：capacityText / attrsFor / VEHICLE_TYPES / 三个 MiniChip / 只停用不删除")
        print("6. 接线：反向验证脚本在、CHG-0016.md 九节、登记簿有 CHG-0016 整行")
        sys.exit(0)
    sys.exit(main())
