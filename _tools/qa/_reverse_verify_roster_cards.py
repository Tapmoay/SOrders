"""反向验证：`_tools/qa/_check_roster_cards.py` 那些判据**真的抓得住**吗（2026-10-05）。

## 为什么必须有它
用户 2026-10-05 点名的那两件事（「侧边栏…半展开」「名称和电话号码…要有对应的语义色和图标」）
**改坏了都不会有任何报错**：把 240dp 改回满宽、把电话那行退回灰字、把 `combinedClickable` 换成 `clickable`、
把面板里写死的湖蓝搬回来 —— 全都能编译过、真机上「看着也能用」，只有翻页面才看得出来。
所以这一批的判据必须配一份反向验证：一条「永远绿的检查」等于没有检查。

## 手法（与 `_reverse_verify_sheet_form_pages.py` 同一套，不另立一套）
对每个注入点：**先把文件按字节备份** → 注入 → 跑判据（期望非零退出**且**命中指定的判据标签）
→ **按字节还原** → 校验 sha256 与备份一致。
⛔ 全程不碰 `git checkout --`（那会把别的会话未提交的改动一起抹掉，实测发生过）。

⛔ 跑这一份的时候**不要并发跑别的判据**：注入是临时写进源码的。

## 三条特别挑出来的注入
- **⑩ 把号码退回 `onSurfaceVariant`**：判据那一条同时要求「前景色在」与「灰字不在」，只判一半的写法会漏掉它。
- **⑮ 账户页又借湖蓝**：账户页原本就有 4 处 `Color(AccountBrown)`，改掉 1 处还剩 3 处，
  判据如果写成「出现过就算」就抓不住 —— 它必须同时要求「`ShipperTeal` 不在这一页」。
- **㊱ 宫格那一格与 token 不同值**：宫格那行是**故意保留的裸字面量**（`_check_ledger_dashboard.py` 的 `BAND_EXEMPT` 按裸值扫），
  所以「两处同值」必须真的被判据对上账。

用法：
    python _tools/qa/_reverse_verify_roster_cards.py          # 全部跑
    python _tools/qa/_reverse_verify_roster_cards.py --list   # 只列注入点

配套：python _tools/qa/_check_roster_cards.py（53 项）；本脚本 **47 条注入**。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_roster_cards.py"
A = "android/app/src/main/java/com/tapmoay/sorders/"

P_ROSTER = A + "ui/common/RosterCard.kt"
P_DRAWER = A + "ui/common/CategoryDrawer.kt"
P_ACCT = A + "ui/dispatcher/AccountManageScreen.kt"
P_USERS = A + "ui/dispatcher/UsersManageScreen.kt"
P_VEH = A + "ui/dispatcher/VehicleManageScreen.kt"
P_PANEL = A + "ui/dispatcher/CategoryRostersPanel.kt"
P_ADDR = A + "ui/shipper/AddressScreen.kt"
P_COLOR = A + "ui/theme/Color.kt"
P_MODS = A + "ui/nav/Modules.kt"
SPEC = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
DOC = "docs/changes/CHG-0023.md"
README = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"

# (说明, 相对路径, 锚点, 替换成, 期望哪条判据报红)
#
# ⚠️ 「期望」写的是**判据标签的开头**，命中判据是输出里出现 `[!!]   <标签>`——
#    只写标签本身不行：通过时那行也会打出来（`[OK]   <标签>`），等于永远算命中。
#    带 `~` 前缀 = 只要任意一条失败行里包含这段子串（抽屉那四条标签前面拼了页名）。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 名称行的 16sp 退回 13sp（跟电话一样小，「凸显」就没了）",
        P_ROSTER,
        "fontSize = 16.sp,",
        "fontSize = 13.sp,",
        "名册卡名称行：16sp 加粗（与车辆卡车牌同号）",
    ),
    (
        "② 名称不加粗",
        P_ROSTER,
        "fontWeight = FontWeight.Bold,",
        "fontWeight = FontWeight.Normal,",
        "名册卡名称行：16sp 加粗（与车辆卡车牌同号）",
    ),
    (
        "③ 圈底图标退回裸图标（规范 §4.2c 那套没了）",
        P_ROSTER,
        "TintedIcon(icon, accent, size = 18.dp, container = 34.dp)",
        "Icon(icon, null, tint = accent)",
        "名册卡名称行：本页模块色的圈底图标（34dp 底 / 18dp 图标）",
    ),
    (
        "④ 名称行那个零件改名（别的页面就调不到了）",
        P_ROSTER,
        "fun RosterNameRow(",
        "fun RosterNameRowX(",
        "共用件 RosterCard.kt 在，名称行与电话行两个零件都导出",
    ),
    (
        "⑤ 电话行那个零件改名",
        P_ROSTER,
        "fun RosterPhoneRow(",
        "fun RosterPhoneRowX(",
        "名册卡电话行：Phone 图标 + PhoneGreen",
    ),
    (
        "⑥ 电话那个绿不再是 token（随手一个绿）",
        P_ROSTER,
        "val PhoneGreen: Color = Color(MgrGreen)",
        "val PhoneGreenX: Color = Color(MgrGreen)",
        "电话那个绿是全库一个 token（PhoneGreen = MgrGreen，不是随手一个绿）",
    ),
    (
        "⑦ 电话图标换成另一个（不是既有的 Phone）",
        P_ROSTER,
        "Icons.Default.Phone,",
        "Icons.Default.Call,",
        "名册卡电话行：Phone 图标 + PhoneGreen",
    ),
    (
        "⑧ 电话图标不染绿（退回主题灰）",
        P_ROSTER,
        "tint = PhoneGreen,",
        "tint = MaterialTheme.colorScheme.onSurfaceVariant,",
        "名册卡电话行：Phone 图标 + PhoneGreen",
    ),
    (
        "⑨ 长按复制退回单击（用户要的复制没了）",
        P_ROSTER,
        "modifier = Modifier.combinedClickable(",
        "modifier = Modifier.clickable(",
        "名册卡电话行：整行长按复制（combinedClickable + onLongClickLabel + copyTextToClipboard）",
    ),
    (
        "⑩ 号码退回灰字（用户点名的「一眼看不到」）",
        P_ROSTER,
        "color = MaterialTheme.colorScheme.onSurface,",
        "color = MaterialTheme.colorScheme.onSurfaceVariant,",
        "名册卡电话行：15sp 前景色，⛔ 不是灰字（onSurfaceVariant）",
    ),
    (
        "⑪ 账户卡的电话行退回自己写",
        P_ACCT,
        "RosterPhoneRow(phone = u.phone)",
        "Text(u.phone)",
        "账户卡：名称行走 RosterNameRow、电话行走 RosterPhoneRow",
    ),
    (
        "⑫ 账户卡名称行退回自己写",
        P_ACCT,
        "RosterNameRow(",
        "RosterNameRowX(",
        "账户卡：名称行走 RosterNameRow、电话行走 RosterPhoneRow",
    ),
    (
        "⑬ 名称前的图标不是人形",
        P_ACCT,
        "Icons.Default.Person",
        "Icons.Default.AccountCircle",
        "账户卡名称前的图标是人形（Icons.Default.Person）",
    ),
    (
        "⑭ 账户页 FAB 退回裸的（照车辆页那套没了）",
        P_ACCT,
        "ExtendedFloatingActionButton(",
        "FloatingActionButton(",
        "账户页的 FAB 是带字的 Extended FAB（照车辆页那套），⛔ 不是裸 FloatingActionButton",
    ),
    (
        "⑮ 账户页又借地址页的湖蓝",
        P_ACCT,
        "containerColor = Color(AccountBrown),",
        "containerColor = Color(ShipperTeal),",
        "账户页的胶囊 / 名称圈底图标 / FAB 都用这个棕（⛔ 不再借地址页的湖蓝）",
    ),
    (
        "⑯ 电话没原样传（被 trim 过）",
        P_USERS,
        "phone = u.phone,",
        "phone = u.phone.trim(),",
        "司机 / 货主 / 批发商卡：电话行走共用件，u.phone 原样传进去",
    ),
    (
        "⑰ FAB 字色退回白色（黄绿上压白字过不了 AA）",
        P_USERS,
        "contentColor = poolOnColor(pool),",
        "contentColor = Color.White,",
        "FAB 的底色与压在上面的字色各有一套（亮色上压深字，过 AA）",
    ),
    (
        "⑱ 司机 / 货主 / 批发商页抽屉退回满宽",
        P_USERS,
        "ModalDrawerSheet(modifier = Modifier.width(CategoryDrawerWidth)) {",
        "ModalDrawerSheet {",
        "~：抽屉是半展开",
    ),
    (
        "⑲ 这一页 FAB 也退回裸的",
        P_USERS,
        "ExtendedFloatingActionButton(",
        "FloatingActionButton(",
        "司机页的 FAB 也是带字的 Extended FAB",
    ),
    (
        "⑳ 连返回那颗 IconButton 也不是 IconButton 了（数量对不上）",
        P_USERS,
        "IconButton(",
        "IconButtonX(",
        "整个文件只剩返回那一颗 IconButton（判据 _check_users_ui.py 钉着）",
    ),
    (
        "㉑ 卡片上那个深橄榄被顺手调了一格",
        P_USERS,
        "Color(0xFF5A6B00)",
        "Color(0xFF5A6B01)",
        "⛔ 卡片上那三个深色（姓氏圆底 / 徽章）一个字没动",
    ),
    (
        "㉒ 姓氏圆底丢了自己的 16% 透明底",
        P_USERS,
        "clip(CircleShape).background(accent.copy(alpha = 0.16f))",
        "clip(CircleShape).background(accent)",
        "司机 / 货主 / 批发商卡：姓氏圆底与池子强调色没被改掉",
    ),
    (
        "㉓ 货主池的模块色不是深青",
        P_USERS,
        "UserPool.SHIPPERS -> Color(InventoryTeal)",
        "UserPool.SHIPPERS -> Color(ShipperTeal)",
        "三池的模块色映射在（司机 = 黄绿 / 货主 = 深青 / 批发商 = 金）",
    ),
    (
        "㉔ 车辆页抽屉退回满宽",
        P_VEH,
        "ModalDrawerSheet(modifier = Modifier.width(CategoryDrawerWidth)) {",
        "ModalDrawerSheet {",
        "~：抽屉是半展开",
    ),
    (
        "㉕ 车牌那行的圈底图标被换成裸图标",
        P_VEH,
        "TintedIcon(Icons.Default.LocalShipping, VehicleAccent, size = 18.dp, container = 34.dp)",
        "Icon(Icons.Default.LocalShipping, null, tint = VehicleAccent)",
        "车辆卡：车牌那行的圈底图标 + 模块色还在（黄绿，没跟着换成棕）",
    ),
    (
        "㉖ 地址页抽屉退回满宽",
        P_ADDR,
        "ModalDrawerSheet(modifier = Modifier.width(CategoryDrawerWidth)) {",
        "ModalDrawerSheet {",
        "~：抽屉是半展开",
    ),
    (
        "㉗ 顺手把地址页的电话也改成共用件（用户 2026-09-22 说过电话是次要信息）",
        P_ADDR,
        "Icon(Icons.Default.Phone,",
        "RosterPhoneRow(",
        "⛔ 地址页的线路卡没被顺手改（那一页电话仍是很小很灰的次要信息）",
    ),
    (
        "㉘ 面板里少一颗圈底图标动作（退回裸 IconButton 那套）",
        P_PANEL,
        "CardActionIcon(",
        "CardActionIconX(",
        "面板一行里的四个动作都走 CardActionIcon（⛔ 不是裸 IconButton）",
    ),
    (
        "㉙ 删除那颗又写成裸十六进制",
        P_PANEL,
        "tint = Color(MessageRed),",
        "tint = Color(0xFFFF4D4F),",
        "删除那颗用 MessageRed（⛔ 不是裸色值）",
    ),
    (
        "㉚ 撤销条又装回中性灰底（规范 §5.0：抽屉里的卡片必须纯白）",
        P_PANEL,
        "SectionCard(Modifier.padding(horizontal = 20.dp, vertical = 6.dp))",
        "Surface(color = MaterialTheme.colorScheme.surfaceContainerHigh)",
        "条数与撤销条装在纯白卡上（规范 §5.0：抽屉里的卡片必须纯白）",
    ),
    (
        "㉛ 账号名册面板又借湖蓝",
        P_PANEL,
        "accent: Color = Color(AccountBrown),",
        "accent: Color = Color(ShipperTeal),",
        "面板强调色是形参：账号名册默认账户棕、车辆名册默认车辆黄绿",
    ),
    (
        "㉜ 车辆名册面板的默认色不是车辆黄绿",
        P_PANEL,
        "accent: Color = VehicleAccent,",
        "accent: Color = Color(ProductPurple),",
        "面板强调色是形参：账号名册默认账户棕、车辆名册默认车辆黄绿",
    ),
    (
        "㉝ 上移那颗写死湖蓝（不再跟宿主页走）",
        P_PANEL,
        r"re:tint = if \(first\)[^\n]*else accent",
        "tint = if (first) MaterialTheme.colorScheme.outlineVariant else Color(ShipperTeal)",
        "上移 / 下移用宿主页模块色，⛔ 不再写死地址页的湖蓝",
    ),
    (
        "㉞ 账户棕不再是 token",
        P_COLOR,
        "val AccountBrown = 0xFF8D6E63L",
        "val AccountBrownX = 0xFF8D6E63L",
        "主题 token 里有 AccountBrown（账户管理：棕）",
    ),
    (
        "㉟ 棕底上的字没有 token",
        P_COLOR,
        "val OnAccountBrown = 0xFFFFFFFFL",
        "val OnAccountBrownX = 0xFFFFFFFFL",
        "棕底上的字也有 token（OnAccountBrown）",
    ),
    (
        "㊱ 宫格那一格与 token 不同值了",
        P_MODS,
        "color = 0xFF8D6E63L",
        "color = 0xFF8D6E64L",
        "工作台宫格那一格与 token 同值（一处定义、一处对账）",
    ),
    (
        "㊲ 抽屉宽度改回「太旷」那一档",
        P_DRAWER,
        "val CategoryDrawerWidth = 240.dp",
        "val CategoryDrawerWidth = 340.dp",
        "共用常量 CategoryDrawerWidth = 240.dp（用户嫌默认宽度「太旷」）",
    ),
    (
        "㊳ 「全部」那格没有图标（跟真分类一样）",
        P_DRAWER,
        "if (item.key.isEmpty()) Icons.Default.Apps else Icons.Default.Folder",
        "Icons.Default.Folder",
        "每一格左边有图标：全部 = Apps / 分类 = Folder / 管理分类 = Settings",
    ),
    (
        "㊴ 选中态只剩字变色（没有底色）",
        P_DRAWER,
        "if (selected) accent.copy(alpha = 0.12f) else Color.Transparent",
        "if (selected) Color.Transparent else Color.Transparent",
        "选中那一格有 accent 底（⛔ 不只是字变色）",
    ),
    (
        "㊵ 常驻说明又写成 16 字",
        P_DRAWER,
        "选一类只看这一类",
        "选一类只看这一类；不选就是全部。",
        "那行常驻说明 ≤ 8 字（用户口径：常驻就几个字）",
    ),
    (
        "㊶ 规范里没有名册卡那一节",
        SPEC,
        "### 4.24",
        "### 4.24X",
        "规范 §4.24 在（名册卡两条事实 + 抽屉半展开）",
    ),
    (
        "㊷ 规范 §2 表里账户管理那一行的常量格空了",
        SPEC,
        "| 账户管理 | 棕 #8D6E63 | AccountBrown |",
        "| 账户管理 | 棕 #8D6E63 | - |",
        "规范 §2 表里有账户管理那一行（棕 #8D6E63 / AccountBrown）",
    ),
    (
        "㊸ 规范里写的抽屉宽度不是 240",
        SPEC,
        "CategoryDrawerWidth = 240.dp",
        "CategoryDrawerWidth = 300.dp",
        "规范里写着抽屉宽度 240dp、为什么是它、以及哪三个抽屉不收窄",
    ),
    (
        "㊹ 文档九节少一节",
        DOC,
        "## ⑨",
        "## 九",
        "docs/changes/CHG-0023.md 存在且九节齐",
    ),
    (
        "㊺ 文档里半径写成 L3",
        DOC,
        "- **Blast Radius**：**L0** ——",
        "- **Blast Radius**：**L3** ——",
        "文档里写着半径是 L0（纯展示层：不动后端、不动 DTO、不动权限）",
    ),
    (
        "㊻ 登记表里这一行的 ID 换了",
        README,
        "`CHG-0023` | CHG |",
        "`CHG-002X` | CHG |",
        "变更登记表里有 CHG-0023 这一行（行首 ID 格 + 链接那一格）",
    ),
    (
        "㊼ CLAIM 里那块声明的 ID 换了",
        CLAIM,
        "**CHG-0023",
        "**CHG-002X",
        "AI_WORK_CLAIM.md 里有 CHG-0023 声明块（进行中 / 已完成都算）",
    ),
    (
        "㊽ 车辆页那颗胶囊不再与卡片右缘对齐（漏掉那 12dp）",
        P_VEH,
        "modifier = Modifier.padding(end = 12.dp),",
        "modifier = Modifier,",
        "车辆页：胶囊挂在 actions 上，右缘与卡片对齐",
    ),
    (
        "㊾ 账户页那颗胶囊也跟着丢了对齐（它本该在 actions 里贴右侧）",
        P_ACCT,
        "modifier = Modifier.padding(end = 12.dp),",
        "modifier = Modifier,",
        "账户页：胶囊搬进 actions（右边空着 → 贴右侧），也补 12dp",
    ),
    (
        "㊿ 司机 / 批发商池也把胶囊挪到右边（顶栏右边有按钮，用户说保持原样）",
        P_USERS,
        "val chipBesideTitle = pool == UserPool.MEMBERS || vm.isDriverPool",
        "val chipBesideTitle = false",
        "司机 / 批发商池：顶栏右边有按钮 → 胶囊保持原样贴在标题后面",
    ),
    (
        "51 货主池那颗胶囊不贴右侧了（右边空着却不放右边）",
        P_USERS,
        "if (!chipBesideTitle) chip(Modifier.padding(end = 12.dp))",
        "if (false) chip(Modifier.padding(end = 12.dp))",
        "货主池（右边空）：同一颗胶囊落在 actions 里、右缘与卡片对齐",
    ),
    (
        "52 地址页也塞进第四颗胶囊（那一页右边都有「新增」按钮，三颗保持原样）",
        P_ADDR,
        "CategoryTriggerChip(",
        "CategoryTriggerChip(\n            CategoryTriggerChip(",
        "⛔ 地址页那三颗保持原样（右边都有「新增」按钮 —— 右边有东西就别动）",
    ),
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _old, _new, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    caught = 0
    problems: list[str] = []
    for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
        path = ROOT / rel
        if not path.exists():
            problems.append(f"{name}：找不到 {rel}")
            print(f"\n[{i}] {name}\n  ❌ 找不到 {rel}")
            continue
        orig = path.read_bytes()
        orig_sha = sha(orig)
        text = orig.decode("utf-8")
        # 锚点里写的是 `\n`。目标文件可能是 CRLF —— 那种情况下锚点会**静默不命中**，
        # 所以按文件自己的行尾归一，而不是直接跳过。
        eol = "\r\n" if "\r\n" in text else "\n"
        if eol != "\n":
            old = old.replace("\n", eol)
            new = new.replace("\n", eol)
        pat = old[3:] if old.startswith("re:") else re.escape(old)
        injected, n = re.subn(pat, new, text, count=1)
        if n != 1:
            problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:40]!r}）")
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
        if sha(path.read_bytes()) != orig_sha:
            print(f"\n[{i}] {name}\n  🛑 {rel} 还原后哈希对不上，停手「")
            return 2

        # 期望值两种写法：
        #   普通字符串 —— 必须原样命中「[!!]   <标签>」（标签是**写死**的判据）；
        #   `~` 前缀    —— 只要**任意一条** [!!] 失败行里包含这段子串即可（抽屉那四条
        #                  标签前面拼了页名，写死了就会因为页名漂移而漏网）。
        if want.startswith("~"):
            hit = any(want[1:] in ln for ln in out.splitlines() if ln.lstrip().startswith("[!!]"))
        else:
            hit = f"[!!]   {want}" in out
        if rc != 0 and hit:
            caught += 1
            print(f"\n[{i}] {name}\n  ✅ 被抓到（判据非零退出，命中「{want}」）")
        else:
            why = "红线居然还是绿的" if rc == 0 else f"退出了，但输出里没有「[!!]   {want}」"
            problems.append(f"{name}：{why}")
            print(f"\n[{i}] {name}\n  ❌ {why}")

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
