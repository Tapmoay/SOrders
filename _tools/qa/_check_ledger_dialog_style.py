"""核销那一族弹窗改成**卡片式**（台账 L-16，2026-10-06）：白底 ＋ 弹层圆角，不再是 M3 那层灰蓝。

## 用户口径（原话）
「核销不要用弹窗啊，用弹窗的样式太难看了。哎还是用弹窗吧，但是我们换个样式，不要那种灰蓝灰蓝的，
我们像那种卡片的弹窗样式一样。这个要改啊，因为太丑了。」（用户 m00354）

## 机制：那层「灰蓝灰蓝的」是从哪来的
M3 的 `AlertDialog` 默认容器色 = `colorScheme.surfaceContainerHigh`；本主题把它设成
`ui/theme/Color.kt:152 = #DDE1EA`（接线在 `ui/theme/Theme.kt:101`）。全仓 68 处
`AlertDialog(` **没有一处**设过 `containerColor` ⇒ 所有弹窗都是那个灰蓝底。用户后来又补了
一句（m00542）：「不一定要是卡片式的，只是现在的弹窗太难看了，**具体样式我们可以之后慢慢定**」，
并要求这套语言要有自己的图标与语义色。

## 这一刀只动「容器那一层」（别顺手多改）
- **动**：`ui/common/Components.kt` 新增共用零件 `CardAlertDialog`（白底 ＋
  `shapes.extraLarge` ＋ `tonalElevation = 0.dp`），把**核销这一族** 5 处调用点迁过去
  （货主账本 3 处 ＋ 派单员账本 2 处）。槽位 / 文案 / 排版 / 交互一个字不动 —— 换的只是那层底。
- **不动**：主题 token（`surfaceContainerHigh` 另有 6 处消费者：AI 聊天 4 ＋ 富文本引用块 1 ＋
  消息未读底色 0（2026-10-11 起消息卡片改用白底+阴影，不再消费这个 token）；改它等于顺手改了那些页面）。
- ⚠️ **后续**：`DangerConfirmDialog` 与「其余 63 处裸 `AlertDialog(`」原本是本事项的边界，后来由
  台账 L-20 / **CHG-0064** 一次性收敛到本件（全库 68 处调用点全走 `CardAlertDialog`，本件体内那
  一行 `AlertDialog(` 成了**全库唯一**剩下的一处；`DangerConfirmDialog` 改成转发本件 ＋
  `tone = DialogTone.DANGER`）。所以下面第 3 / 第 4 组的计数口径已随之更新 —— 一条也没松：
  「少迁一处」照样红，「多出一处裸弹窗」也照样红。

## 判据
1. 零件本身：签名逐字（含 `properties` 透传）、转发给 `AlertDialog`、三行样式
   （`shape` / `containerColor = MaterialTheme.colorScheme.surface` / `tonalElevation = 0.dp`）；
   KDoc 里点了 L-16 与用户原话；
2. 核销这一族 5 处都迁了，且这两个文件里**代码**中再没有裸 `AlertDialog(`；
3. 全仓**代码**里裸 `AlertDialog(` = 1（只剩 `CardAlertDialog` 定义体内那一处；轨迹 68 →
   CHG-0051 的 63 → CHG-0056 的 62 → 台账 L-20 / CHG-0064 的 1），`CardAlertDialog(` ≥ 69
   （1 处定义 ＋ 全库 68 处调用点；这一族是**在扩散的**共用件，所以这里是下限：**少一处**
   （有人把迁移回退）照样红，多一处是本来的方向）；
4. 全库收敛：CHG-0051 当时「别处一处没动」的那几页，CHG-0064 之后也一处不剩
   （OrderDetailScreen 原 8 / DispatcherOrdersScreen 原 5 / OrderCreateScreen 原 4
   / ProfileScreen 原 3，现在都是 0）；
5. 方案 C 的护栏：主题 token 与它的 6 处消费者一个字没动；`DangerConfirmDialog` 与既有判据
   钉它的两行都还在；
6. 文档与随动：`docs/changes/CHG-0051.md` 在、README 有行、AI_WORK_CLAIM 有条目与交叉点行；
7. 防静默空转：扫到的 .kt >= MIN_KT，关键文件都在。

## 为什么这条必须有机器的判据
「换个弹窗样式」是**一层容器的颜色**：把它改回灰蓝不会有任何编译错误、不会有任何用例报红，而界面上
是「一眼就能看出丑」的那种坏。反向破坏用例见 _reverse_verify_ledger_dialog_style.py（零件样式被抽回
默认 / 某个文件少迁一处 / `containerColor` 被删 / 调用点被改回裸 `AlertDialog` / 主题
token 被改（方案 C 回潮）/ `DangerConfirmDialog` 被顺手改掉 / 文档口径被改回去 … ＋ 还原后
逐字节比对）。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
`containerColor: Color` 在类型上就是一个颜色：`#DDE1EA`（灰蓝）与 `surface`（白）
都是合法的 `Color`，「这层底不该是灰蓝」是**用户看到的观感口径**，任何类型都表达不出「卡片式」。
所以判据只能钉在零件的三行样式、迁移清单的计数（68 → 63 → 1）与「谁都不许自己画一层底」上。

用法：python _tools/qa/_check_ledger_dialog_style.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
COMP = AND / "ui/common/Components.kt"
SHIPPER = AND / "ui/shipper/ShipperLedgerScreen.kt"
DISPATCHER = AND / "ui/dispatcher/LedgerPersonScreen.kt"
COLOR = AND / "ui/theme/Color.kt"
THEME = AND / "ui/theme/Theme.kt"
AI_RICH = AND / "ui/ai/AiRichText.kt"
AI_CHAT = AND / "ui/ai/AiChatScreen.kt"
MSGS = AND / "ui/messages/MessagesScreen.kt"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
DISP_ORDERS = AND / "ui/dispatcher/DispatcherOrdersScreen.kt"
ORDER_CREATE = AND / "ui/shipper/OrderCreateScreen.kt"
PROFILE = AND / "ui/profile/ProfileScreen.kt"
GUARDS = ROOT / "_tools/qa/_check_cancel_entry_and_guards.py"
CHG = ROOT / "docs/changes/CHG-0051.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_ledger_dialog_style.py"

#: 全仓至少要有这么多 .kt（防「目录被搬走 → 一个都没扫到 → 全绿」）。
MIN_KT = 100
#: 迁移前全仓裸 `AlertDialog(` 是 68 处；CHG-0051 只迁核销那 5 处（63），CHG-0056 之后 62，
#: 台账 L-20 / CHG-0064 把剩下的全库收敛 ⇒ 只该剩 `CardAlertDialog` **定义体内**那一处。
BARE_AFTER = 1
#: 零件定义 1 处 ＋ 全库 68 处调用点（CHG-0064 迁移完成时实测 69 ＝下限）。
CARD_AFTER = 69
#: 核销这一族的迁移清单（文件 ＋ 迁了几处）。
MIGRATED = [(SHIPPER, 3, "货主账本"), (DISPATCHER, 2, "派单员账本")]
#: CHG-0051 当时刻意没碰的那几页（数字是迁移当时实测的）；CHG-0064 之后它们也一处不剩。
UNTOUCHED = [(DETAIL, 8, "司机端订单详情"), (DISP_ORDERS, 5, "派单员订单列表"),
             (ORDER_CREATE, 4, "货主下单页"), (PROFILE, 3, "我的")]
#: 主题 token 的消费者（本事项明确没碰它们；数字是实测的）。
#: ⚠️ 2026-10-09 复核：`AiChatScreen.kt` 里 `surfaceContainerHigh` 的实测处数已从 4 涨到 **5**
#:     （后来的人又加了一处消费者）。阈值停在 4 的话，反验那条「顺手改了 token 的消费者」
#:     注入只把 5 减到 4、仍在阈值之上 ⇒ 判据不红、反验恒 MISS（实测踩到）。
#:     这里按实测把阈值提到 5，让那条注入重新咬得住；意图一个字没变（消费者一处都不许少）。
#: 2026-10-11 随动（FEAT-0019 后续，用户口径）：消息卡片的**未读底色**被用户否掉了 ——
#:    原话「以前是因为没有搞颜色才搞一个没读就有一层灰的灰尘遮罩；现在已经有颜色做区别了，所以不需要这个灰尘了」，
#:    改成**白底 + 一层阴影**（MessagesScreen.kt 的 MESSAGE_CARD_SHADOW）⇒ MessagesScreen 对
#:    surfaceContainerHigh 的消费从 1 处变成 **0 处**（阈值随之改为 0；token 本身与另外两个消费者一个字没动）。
CONSUMERS = [(AI_RICH, 1, "富文本引用块底"), (AI_CHAT, 5, "AI 聊天 5 处"), (MSGS, 0, "消息未读底色（2026-10-11 起不再消费）")]
REQUIRED_FILES = [COMP, SHIPPER, DISPATCHER, COLOR, THEME, AI_RICH, AI_CHAT, MSGS, CHG, REVERSE]

#: ⛔ 数裸弹窗时必须排除 `Card` 前缀（`CardAlertDialog(` 里含子串 `AlertDialog(`），
#:    否则新零件会被当成"没迁干净"。Python 的 `re` 支持负向后顾，ripgrep 不支持。
BARE = r"(?<!Card)AlertDialog\("
CARD = r"CardAlertDialog\("


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def code_only(text: str) -> str:
    """去掉注释但**保留换行数**（行号才对得上）。

    ⛔ 零件的 KDoc 里**故意**写着「把 `AlertDialog` 调用换成 `CardAlertDialog`」这类话；
    判据要钉的是**代码**里还有几处，不是注释里提没提它。
    """
    text = re.sub(r"/\*[\s\S]*?\*/", lambda m: "\n" * m.group(0).count("\n"), text)
    return re.sub(r"//[^\n]*", "", text)


def count(text: str, pattern: str) -> int:
    return len(re.findall(pattern, text))


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        self.ok(label, re.search(pattern, text) is None, f"不该出现却出现了 {pattern!r}")


def main() -> int:
    c = Checker()
    comp = read(COMP)
    comp_code = code_only(comp)
    ship_code = code_only(read(SHIPPER))
    disp_code = code_only(read(DISPATCHER))

    print("== 1. 零件本身：CardAlertDialog ==")
    c.present("@Composable 的 CardAlertDialog 在", comp_code, r"@Composable\s*\nfun CardAlertDialog\(")
    sig = (
        "fun CardAlertDialog(\n"
        "    onDismissRequest: () -> Unit,\n"
        "    confirmButton: @Composable () -> Unit,\n"
        "    modifier: Modifier = Modifier,\n"
        "    dismissButton: (@Composable () -> Unit)? = null,\n"
        "    icon: (@Composable () -> Unit)? = null,\n"
        "    title: (@Composable () -> Unit)? = null,\n"
        "    text: (@Composable () -> Unit)? = null,\n"
        "    tone: DialogTone = DialogTone.INFO,\n"
        "    properties: DialogProperties = DialogProperties(),\n"
        ") {"
    )
    c.ok("签名与 AlertDialog **逐字对齐**（8 个槽位一个不少；CHG-0064 起多一档 tone，调用点照样不用改排版）", sig in comp_code,
         "签名对不上：多槽 / 少槽都会让调用点被迫改结构")
    body_i = comp_code.find("fun CardAlertDialog(")
    body = comp_code[body_i:body_i + 2000] if body_i >= 0 else ""
    c.present("转发给 AlertDialog（不是自己画一层 Surface）", body, r"\n\s*AlertDialog\(")
    c.present("白底：containerColor = MaterialTheme.colorScheme.surface", body,
              r"containerColor = MaterialTheme\.colorScheme\.surface,")
    c.present("弹层圆角：shape = MaterialTheme.shapes.extraLarge", body,
              r"shape = MaterialTheme\.shapes\.extraLarge,")
    c.present("⛔ tonalElevation = 0.dp（M3 默认那 6dp 会给白底再刷一层主色薄雾）", body,
              r"tonalElevation = 0\.dp,")
    c.present("properties 也透传（调用点传的 DialogProperties 不会丢）", body, r"properties = properties,")
    c.present("DialogProperties 的 import 在", comp_code,
              r"import androidx\.compose\.ui\.window\.DialogProperties")
    c.present("KDoc 点了台账编号 L-16（可追溯到用户原话）", comp, r"台账 L-16")
    c.present("KDoc 里留着用户那句「灰蓝灰蓝」（后来的人知道要躲什么）", comp, r"灰蓝灰蓝")

    print("== 2. 核销这一族 5 处都迁了（两个角色的两个入口，不能只改一半） ==")
    for p, n, who in MIGRATED:
        got = count(code_only(read(p)), CARD)
        c.ok(f"{who}：{n} 处核销弹窗全走 CardAlertDialog", got == n, f"实际 {got} 处")
        c.ok(f"{who}：代码里再没有裸 AlertDialog(", count(code_only(read(p)), BARE) == 0,
             f"还有 {count(code_only(read(p)), BARE)} 处没迁")
    c.ok("货主账本「恢复这笔核销」那一支迁了（vm.restoreTarget 那一处）",
         "vm.restoreTarget?.let { s ->\n        CardAlertDialog(" in ship_code)
    c.ok("货主账本 SettleOrderDialog（核销订单）迁了",
         "private fun SettleOrderDialog(vm: ShipperLedgerViewModel, order: OrderDto) {\n    CardAlertDialog(" in ship_code)
    c.ok("货主账本 OrderSettlementsDialog（订单核销记录）迁了",
         "private fun OrderSettlementsDialog(vm: ShipperLedgerViewModel, order: OrderDto) {\n    val list = vm.settledOfOrder(order.id)\n    CardAlertDialog(" in ship_code)
    c.ok("派单员账本 SettleOrderDialog（核销）迁了",
         "fun SettleOrderDialog(vm: DispatcherLedgerViewModel, onDismiss: () -> Unit) {\n    val order = vm.settleTarget ?: return\n    CardAlertDialog(" in disp_code)
    c.ok("派单员账本 SettleAllDialog（核销全部）迁了",
         "fun SettleAllDialog(vm: DispatcherLedgerViewModel, onDismiss: () -> Unit) {\n    val targets = vm.settleAllTargets()\n    CardAlertDialog(" in disp_code)
    c.present("标题没动：货主「恢复这笔核销？」", ship_code, r'Text\("恢复这笔核销？"\)')
    c.present("标题没动：货主「核销订单 + 单号」", ship_code, r'DialogTitle\("核销订单", "#" \+ order\.orderNo\)')
    c.present("标题没动：货主「订单核销记录」", ship_code, r'DialogTitle\("订单核销记录",')
    c.present("标题没动：派单员「核销 + 单号」", disp_code, r'DialogTitle\("核销", order\.orderNo\)')
    c.present("标题没动：派单员「核销全部（N 单）」", disp_code, r'Text\("核销全部（" \+ targets\.size \+ " 单）"\)')
    c.ok("两颗按钮的槽位照旧（confirmButton 还在，没有把弹窗改成别的形状）",
         count(ship_code, r"confirmButton =") >= 3 and count(disp_code, r"confirmButton =") >= 2)

    print("== 3. 全仓计数：68 → 1（CHG-0064 之后只剩定义自己那一处） ==")
    kts = sorted(AND.rglob("*.kt"))
    bare_total = 0
    card_total = 0
    bare_left: dict[str, int] = {}
    for p in kts:
        t = code_only(read(p))
        b = count(t, BARE)
        bare_total += b
        card_total += count(t, CARD)
        if b:
            bare_left[p.relative_to(AND).as_posix()] = b
    c.ok(f"全仓代码里裸 AlertDialog( = {bare_total} 处（只有 CardAlertDialog 定义体内那一处；"
         f"迁移前 68 → CHG-0051 的 63 → 台账 L-20 / CHG-0064 的 1）", bare_total == BARE_AFTER,
         f"实际 {bare_total}")
    # ⚠️ 这里是**下限**不是等式：CHG-0051 之后别的事项陆续用它（CHG-0056 在首页加了一处），
    #    等式会让每一个后来的正当调用点都变红；但**少**一处（迁回去 / 被删）仍然必须当场红。
    c.ok(f"全仓 CardAlertDialog( = {card_total} 处（≥ {CARD_AFTER}：1 处定义 ＋ 全库 68 处调用点）",
         card_total >= CARD_AFTER,
         f"实际 {card_total}")
    for p, _, who in MIGRATED:
        rel = p.relative_to(AND).as_posix()
        c.ok(f"{who}不在「还有裸 AlertDialog」的名单里", rel not in bare_left,
             f"还在名单里：{bare_left.get(rel)} 处")

    print("== 4. 全库收敛：CHG-0051 当时「别处一处没动」的那几页，现在也一处不剩 ==")
    # ⚠️ 这一组的语义在台账 L-20 / CHG-0064 之后**反过来**了：CHG-0051 那刀刻意留着它们
    #    （「别处一处没动」），CHG-0064 把全库 62 处一次性收敛 ⇒ 现在这些页面里**再冒出一处
    #    裸弹窗就是回潮**。原有的边界精神没丢：依然是「谁都不许自己画一层底」。
    for p, n, why in UNTOUCHED:
        got = count(code_only(read(p)), BARE)
        c.ok(f"{p.name} 一处不剩（CHG-0064 迁掉原来那 {n} 处：{why}）", got == 0, f"现在是 {got} 处")
    c.ok("Components.kt 里只剩定义自己那一处裸 AlertDialog（日期筛选与 DangerConfirmDialog 也都迁了）",
         count(comp_code, BARE) == 1, f"现在是 {count(comp_code, BARE)} 处")

    print("== 5. 方案 C 的护栏：主题 token 与它的消费者一个字没动 ==")
    color = read(COLOR)
    # 台账 L-19 / CHG-0063 起，亮色这四层改成「暖白家族」（页面底与周围那几层一起往暖白走）。
    # 这条断言的原意一个字没变：**弹层那一层不许被刷成纯白来冒充卡片式**。所以口径从
    # 「必须是 #DDE1EA」松成「既不是纯白、也不许亮过 #F0F0F0」；确切值交给
    # _tools/qa/_check_warm_surface_palette.py 去钉（那里还管着分层与抽屉那一层）。
    m = re.search(r"val SurfaceContainerHigh = Color\(0xFF([0-9A-Fa-f]{6})\)", color)
    v = int(m.group(1), 16) if m else None
    too_bright = v is None or v == 0xFFFFFF or max((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF) > 0xF0
    c.ok("Color.kt：SurfaceContainerHigh 仍是那一层灰（不是纯白；台账 L-19 起是暖白那一层）",
         not too_bright,
         "没找到那一行" if v is None else ("现在是 #%06X" % v))
    c.present("Color.kt：暗色那档也还在", color, r"val SurfaceContainerHighDark = Color\(0xFF292A31\)")
    theme = read(THEME)
    c.present("Theme.kt：仍把它接到 colorScheme.surfaceContainerHigh", theme,
              r"surfaceContainerHigh = SurfaceContainerHigh,")
    c.present("Theme.kt：暗色那行也还在", theme, r"surfaceContainerHigh = SurfaceContainerHighDark,")
    for p, n, why in CONSUMERS:
        got = count(read(p), r"surfaceContainerHigh")
        c.ok(f"消费者没被顺手改：{p.name} 仍有 {n} 处（{why}）", got >= n, f"现在只剩 {got} 处")
    c.present("DangerConfirmDialog 还在（全 App 共用的危险确认，本事项明确没碰）", comp_code,
              r"fun DangerConfirmDialog\(")
    guards = read(GUARDS)
    c.ok("既有判据仍在钉 DangerConfirmDialog 的两行（没有为了让新零件好写而松掉它）",
         "enabled: Boolean = true," in guards and "enabled = enabled," in guards)

    print("== 6. 文档与随动 ==")
    c.ok("docs/changes/CHG-0051.md 在（本事项的立项文档）", CHG.exists())
    chg = read(CHG) if CHG.exists() else ""
    c.present("CHG-0051 点得出零件名（后来的人知道改哪里）", chg, r"CardAlertDialog")
    c.present("CHG-0051 点得出台账编号", chg, r"L-16")
    c.present("CHG-0051 写了这一刀的边界（其余弹窗仍是灰蓝）", chg, r"其余")
    c.present("docs/changes/README.md 有 CHG-0051 的登记行（链到文档）", read(README),
              r"\[CHG-0051\.md\]\(CHG-0051\.md\)")
    claim = read(CLAIM)
    c.present("AI_WORK_CLAIM 有本事项的条目（标题行）", claim, r"会话：\*\*CHG-0051")
    c.present("AI_WORK_CLAIM 的交叉点表记了客户端三处（零件 ＋ 两个账本页）", claim,
              r"`ui/common/Components\.kt` ＋ `ui/shipper/ShipperLedgerScreen\.kt` ＋ `ui/dispatcher/LedgerPersonScreen\.kt`")

    print("== 7. 防静默空转 ==")
    c.ok(f"扫到的 .kt 有 {len(kts)} 份（>= {MIN_KT}）", len(kts) >= MIN_KT)
    for p in REQUIRED_FILES:
        c.ok(f"关键文件在：{p.relative_to(ROOT).as_posix()}", p.exists())
    rv = read(REVERSE) if REVERSE.exists() else ""
    c.ok("反验脚本在，且注入表至少 12 条", rv.count("\n    (\n") >= 12, f"实际 {rv.count(chr(10) + '    (' + chr(10))} 条")

    print()
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print(f"  - {f}")
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
