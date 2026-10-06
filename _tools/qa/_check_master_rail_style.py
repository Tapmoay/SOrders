"""红线：**下单页「地点库」左栏（MasterRail）要与「线路分类」那一列长得一样**（用户 2026-10-07 m12367）。

## 用户原话与要的结果
> 用户把下单页「地点库」左栏与「线路分类」抽屉摆在一起比，结论是"**要跟它一样**"：
> 每一格都要有图标、选中的那一格用同一套强调色；而「管理分组」是"去别的地方"的那一格 ——
> 它前面要有一条线，跟上面的数据格分开（用户 2026-09-19 指着截图里的红框说过这格的位置）。

## 这一块最容易悄悄坏掉的六件事（每条都有判据）
1. **选中态退回白底**：`MasterRail` 原来是 `if (on) surface else transparent`（白底），与分类抽屉的
   `accent.copy(alpha = 0.12f)` 不是一套；退回白底 = 用户说的"不一样"又回来了。
2. **只给某一格加图标**：五格（线路 / 我的地点 / 共享地点 / 自定义分组 / 管理分组）漏一个，
   那一列就会出现"有的格有图标、有的没有"的锯齿 —— 图标列对不齐，人扫不动。
3. **第一格也画分隔线**：`dividerBefore` 必须只在 `index > 0` 时生效（第一格上面本来就是列首）。
4. **对勾抄过来**：分类抽屉那一列有 `Icons.Default.Check`，但这一列只有 112dp 宽，
   图标＋文字＋对勾三样一起上，分类名会被挤成"一个字两行"（`MasterRail` 的注释里钉着这句）。
5. **那条线定位错**：它是"这一格属于另一个去处"的信号，**由这一格自己声明**；
   写成"上一格下面画线"的话，中间插一格/删一格，线就留在原地了。
6. **强调色丢了或换成主题主色**：地址库这一列的语义色是湖蓝 `ShipperTeal`
   （与「管理分组」进去的那一页同一套色）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
COMPONENTS = ANDROID / "ui/common/Components.kt"
CREATE = ANDROID / "ui/shipper/OrderCreateScreen.kt"
DRAWER = ANDROID / "ui/common/CategoryDrawer.kt"
MANAGE = ANDROID / "ui/dispatcher/PlaceCategoriesScreen.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
CHANGE = ROOT / "docs/changes/CHG-0067.md"


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的断言要跟着改）")
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数，好让行号还对得上）。

    ⚠️ `MasterRail` 的注释里**故意**写着 `CategoryDrawerRow` / `不画对勾` / `0.12f` 这些字眼，
    判据要抓的是**代码里**还有没有 —— 不剥注释的话，散文能把红线喂饱（这一类假绿最难发现）。
    """
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def region(text: str, start: str, stop: str) -> str:
    """截出 [start, stop) 那一段；找不到 start 就返回空串（由调用方的判据报红）。"""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(stop, i + len(start))
    return text[i:j] if j >= 0 else text[i:]


class Checker:
    def __init__(self) -> None:
        self.passes = 0
        self.fails: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
        else:
            self.fails.append(f"{label}｜{detail}" if detail else label)

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"命中：{m.group(0)!r}" if m else "")


def main() -> int:
    c = Checker()
    comp = read(COMPONENTS)
    create = read(CREATE)
    drawer = read(DRAWER)
    manage = read(MANAGE)

    comp_code = code_only(comp)
    create_code = code_only(create)
    drawer_code = code_only(drawer)

    rail_body = region(comp_code, "fun MasterRail(", "\n@Composable")
    sheet = region(create_code, "fun AddressPickerSheet(", "\n@Composable")
    row_body = region(drawer_code, "private fun CategoryDrawerRow(", "\n@Composable")

    print("== 1. RailItem：这一列现在能带图标、能声明一条分隔线 ==")
    c.present("RailItem 有 icon（null = 这一列不画图标，左边不留空档）", comp_code,
              r"val icon: ImageVector\? = null,")
    c.present("RailItem 有 iconTint（null = 跟着选中态走）", comp_code,
              r"val iconTint: Color\? = null,")
    c.present("RailItem 有 dividerBefore，默认 false", comp_code,
              r"val dividerBefore: Boolean = false,")
    c.present("这条参数的来历点名了用户那一次（m12367）", comp, r"m12367")
    c.present("注释写清「第一格给 true 没有意义」（免得下一个人以为画在列首也行）", comp,
              r"第一格给 true 没有意义")

    print("== 2. MasterRail：选中态与线路分类同一套口径 ==")
    c.ok("取到了 MasterRail 函数体", len(rail_body) > 500, f"只有 {len(rail_body)} 字符")
    c.present("选中底色是浅强调色底（不是白底）", rail_body,
              r"if \(on\) accent\.copy\(alpha = 0\.12f\) else Color\.Transparent")
    c.absent("⛔ 选中态不再是白底 surface", rail_body,
             r"if \(on\) MaterialTheme\.colorScheme\.surface else")
    c.present("选中那格左侧仍有 4dp 语义色竖条", rail_body,
              r"Box\(Modifier\.fillMaxHeight\(\)\.width\(4\.dp\)\.background\(accent\)\)")
    c.present("图标 16dp（与抽屉那一列同尺寸）", rail_body, r"Modifier\.size\(16\.dp\)")
    c.present("图标 tint 跟着选中态走（选中染强调色）", rail_body,
              r"\?: if \(on\) accent else MaterialTheme\.colorScheme\.onSurfaceVariant")
    c.present("图标与文字之间留 8dp", rail_body, r"Spacer\(Modifier\.width\(8\.dp\)\)")
    c.present("icon 为 null 时整块不画（不留空档）", rail_body, r"if \(item\.icon != null\) \{")
    c.absent("⛔ 这一列不画对勾（112dp 放不下图标＋文字＋对勾）", rail_body,
             r"Icons\.Default\.Check")
    c.present("分隔线只在不是第一格时画", rail_body,
              r"if \(item\.dividerBefore && index > 0\) \{")
    c.present("分隔线用的是 HorizontalDivider ＋ 上下 4dp", rail_body,
              r"HorizontalDivider\(Modifier\.padding\(vertical = 4\.dp\)\)")
    c.present("index 真的被取出来用了（不是 items(...) 的旧写法）", rail_body,
              r"\{ index, item ->")
    c.present("行高规则没被动（有副标题 60dp）", rail_body,
              r"val rowHeight = if \(twoLine\) 60\.dp else 52\.dp")
    c.present("整列底色没被动（半透明灰）", rail_body, r"surfaceVariant\.copy\(alpha = 0\.45f\)")
    c.present("文字选中染强调色", rail_body,
              r"color = if \(on\) accent else MaterialTheme\.colorScheme\.onSurfaceVariant")
    c.present("副标题选中的口径没被动（选中染强调色）", rail_body,
              r"color = if \(on\) accent else MaterialTheme\.colorScheme\.outline")
    c.present("accent 仍是可传的形参、默认主题主色（别的两栏页不受影响）",
              comp_code, r"accent: Color = MaterialTheme\.colorScheme\.primary,")
    c.present("注释把「与哪一列同口径」写明了", comp, r"CategoryDrawerRow")

    print("== 3. 与分类抽屉（用户要「跟它一样」的那一列）同源 ==")
    c.present("分类抽屉那一列仍是同一套浅底", row_body,
              r"if \(selected\) accent\.copy\(alpha = 0\.12f\) else Color\.Transparent")
    c.present("抽屉那一列的图标也是 16dp", row_body, r"Modifier\.size\(16\.dp\)")
    c.ok("两处的浅底 alpha 是同一个值（分叉了就是「不一样」）",
         "0.12f" in rail_body and "0.12f" in row_body,
         f"rail={'0.12f' in rail_body} drawer={'0.12f' in row_body}")
    c.ok("对勾只属于抽屉那一列（左栏没有，差异是有意的）",
         "Icons.Default.Check" in row_body and "Icons.Default.Check" not in rail_body)

    print("== 4. 下单页「地点库」那一列：五格都有图标，只有「管理分组」有线 ==")
    c.ok("取到了 AddressPickerSheet 函数体", len(sheet) > 800, f"只有 {len(sheet)} 字符")
    c.present("railItems 那段还在（没有另起一份左栏）", sheet, r"railItems")
    c.present("线路 = Route", sheet, r'RailItem\("a", "线路", icon = Icons\.Default\.Route\)')
    c.present("我的地点 = Home", sheet, r'RailItem\("l", "我的地点", icon = Icons\.Default\.Home\)')
    c.present("共享地点 = Groups", sheet,
              r'RailItem\("p", "共享地点", icon = Icons\.Default\.Groups\)')
    c.present("自定义分组 = Folder", sheet, r"icon = Icons\.Default\.Folder")
    c.present("管理分组 = Settings ＋ dividerBefore = true", sheet,
              r'RailItem\("manage", "管理分组", icon = Icons\.Default\.Settings, dividerBefore = true\)')
    c.ok("⭐ 只有「管理分组」这一格声明了分隔线（数据格之间不许有线）",
         sheet.count("dividerBefore = true") == 1,
         f"出现 {sheet.count('dividerBefore = true')} 次")
    c.present("这一列的强调色 = 地址湖蓝 ShipperTeal", sheet, r"accent = Color\(ShipperTeal\)")
    c.present("ShipperTeal 有 import", create_code,
              r"import com\.tapmoay\.sorders\.ui\.theme\.ShipperTeal")
    c.present("图标语义表留在注释里（下一个人知道为什么是这几个图标）", create, r"线路=Route")
    c.present("点「管理分组」仍走原路（不是切右栏）", sheet, r'if \(key == "manage"\)')
    c.ok("「管理分组」进去那一页用的是同一个色（不是两套绿）",
         manage.count("ShipperTeal") >= 2, f"只出现 {manage.count('ShipperTeal')} 次")
    c.absent("⛔ 旧写法（只有字、没图标的线路格）不许回来", sheet,
             r'add\(RailItem\("a", "线路"\)\)')
    c.ok("五格的图标一个不少（Route/Home/Groups/Folder/Settings）",
         sheet.count("icon = Icons.Default.") == 5,
         f"数到 {sheet.count('icon = Icons.Default.')} 个")

    print("== 5. 文档与变更台账（这条规矩得有出处） ==")
    c.ok("变更台账里有 CHG-0067", CHANGE.exists(), str(CHANGE))
    design = read(DESIGN)
    locator = read(LOCATOR)
    c.present("设计文档写了左栏的长相并点名判据", design, r"_check_master_rail_style\.py")
    c.present("设计文档写清「不画对勾」这个决定（免得后人「补齐」）", design, r"对勾")
    c.present("设计文档点名湖蓝 ShipperTeal 这个语义色", design, r"ShipperTeal")
    c.present("代码定位表点名判据", locator, r"_check_master_rail_style\.py")

    total = c.passes + len(c.fails)
    print()
    if total < 40:
        print(f"❌ 只跑了 {total} 项（<40）—— 判据在空转，停。")
        return 1
    if c.fails:
        print(f"[FAIL] {len(c.fails)} 项不成立：")
        for f in c.fails:
            print("  · " + f)
        return 1
    print(f"✅ 地点库左栏与线路分类同一套长相：{c.passes} 项全部成立（含「与抽屉同口径」与「不画对勾」两条反向判据）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
