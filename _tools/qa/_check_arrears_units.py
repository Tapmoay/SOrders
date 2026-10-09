#!/usr/bin/env python
"""挂账单位页（派单员 · 工作台「挂账单位」）按设计规范重做的机器判据 —— CHG-0020。

盯住六件事：

1. **表单不再用居中弹窗**（规范 :1266-1269）：「他不要使用弹窗啊，使用底部抽屉，
   并且**底部抽屉是拉到最上面**」⇒ ModalBottomSheet + rememberModalBottomSheetState(skipPartiallyExpanded = true)
   + fillMaxHeight() + verticalScroll。老画法（AlertDialog + 三个 SoTextField）一处都不许留。
2. **抽屉里是白卡分组 + 共用行**（规范 :1253-1263 / §5.0）：一张 FormGroup 白卡、里面四行
   FormInputRow（名称 / 电话 / 信用额度 / 备注）；卡里不许出现描边输入框。
3. **三种错分开**（规范 :458-478）：loadError 只有 load() 写、formError 画在抽屉里（FormErrorLine）、
   删除失败走 snackbar —— 表单校验绝不许写页面级 error（用户 2026-09-21 骂的「所有列表全消失了」就是这么来的）。
4. **卡片动作按 §4.2c**：左删（提示色 MessageRed）、右编（NavBlue）、两枚都是圈底 CardActionIcon；
   别退回卡头那把 18dp 裸铅笔 / 裸垃圾桶。
5. **删除一律软删 + 手边要有撤回**（规范 :1328 / :1371）：刚删掉的那条画在列表头顶、
   点「撤销」真调后端 restore。
6. **卡上要看得见「现在欠着多少」**（2026-10-09 财务方向测试的 TB-01，CHG-0100）：
   「信用额度」说的是**允许欠多少**，用户要知道的是**现在欠了多少 / 还能赊多少**。
   这一行必须来自「客户欠款」那份**时点账**（`mode = day` + 今天），与报表页同一份口径；
   ⛔ 客户端不许自己减 `credit_used - limit` —— 那就是第二份钱算法，两个页面迟早对不上。
   ⛔ 余额取不到也**不许**写成页面级 `loadError`：那会把整页名册换成错误页（单位与额度都还在）。

为什么必须由机器盯着：

- 「在不在最上面」「圈底还是裸图标」「删除键在左还是右」都是**画法**，编译都过、功能都通，
  只有对照规范才看得出差别；
- 「formError 被写成 loadError」是一种**静默**退化：界面照常能保存，但一填错整页列表就消失，
  而它正是用户点名骂过的那个坑；
- 「撤回」最容易被做成安慰按钮（只把行塞回列表、不调后端），那种假撤回比没有更坏。

R4-BOUNDARY-JUSTIFICATION: 这条判据不下沉到任何一层边界，因为被查的五件事**都是画法与错误归属**，
  不是行为：表单画在页里还是抽屉里、图标有没有圈底、错挂在页面级还是表单级 ——
  后端契约、领域类型、权限模型里都没有它们的位置（后端不知道界面把表单画在哪，
  也不知道「已删除…撤销」这一行在不在屏幕第一屏）。反向说：把「表单的错必须画在表单里」
  塞进任何一层边界都无处安放 —— 那一层根本不参与渲染。

用法：python _tools/qa/_check_arrears_units.py  （--list 打一份人读清单）
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
SCREEN = AND / "ui/dispatcher/ArrearsUnitsScreen.kt"
VM = AND / "ui/dispatcher/ArrearsUnitsViewModel.kt"
BALANCE = AND / "ui/dispatcher/ArrearsBalanceLine.kt"
TEST_BALANCE = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/ArrearsBalanceLineTest.kt"
FORMROWS = AND / "ui/common/FormRows.kt"
COMPONENTS = AND / "ui/common/Components.kt"
COLOR = AND / "ui/theme/Color.kt"
REPO = AND / "data/repo/AppRepository.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
BACKEND = ROOT / "backend/app/api/v1/arrears.py"
REVERSE = ROOT / "_tools/qa/_reverse_verify_arrears_units.py"
PANEL = ROOT / "_tools/qa/_check_form_panel_style.py"
SHEET = ROOT / "_tools/qa/_check_sheet_form_pages.py"
DELUNDO = ROOT / "_tools/qa/_check_delete_undo.py"
DOC = ROOT / "docs/changes/CHG-0020.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

NL = chr(10)
CR = chr(13)
BT = chr(96)

#: 反空转下限（文件被搬走 / 目录改名 / 扫描写坏时不许安静全绿）
MIN_KT_FILES = 200
MIN_SCREEN_CHARS = 6500
MIN_COLOR_CHARS = 2000


def norm(path: Path) -> str:
    """读一份文件并把 CRLF 归一成 LF（仓库里两种行尾都有，锚点不该被行尾绊倒）。"""
    return read(path).replace(CR + NL, NL)


def span(src: str, start: str, end: str) -> str:
    """抠出 [start, end) 之间的一块（找不到 start 就返回空串，让判据报红）。"""
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i + len(start))
    return src[i:] if j < 0 else src[i:j]


def main() -> int:
    if refuse_if_injecting("挂账单位页判据"):
        return 1
    c = Checker()

    # ── 0. 反空转 ────────────────────────────────────────────────────────
    c.section("0. 反空转（文件搬走 / 目录改名 / 扫描写坏时先喊）")
    missing = [p.name for p in (SCREEN, VM, FORMROWS, COMPONENTS, COLOR, DESIGN) if not p.exists()]
    c.ok("六个文件都在（挂账单位页 + VM + FormRows + Components + Color.kt + 设计规范）",
         not missing, "缺：" + str(missing))
    if missing:
        print(NL + "❌ 文件都不在，后面的判据没有意义")
        return 1
    raw = norm(SCREEN)
    screen = strip_comments(raw)
    vraw = norm(VM)
    vm = strip_comments(vraw)
    color = strip_comments(norm(COLOR))
    comp = strip_comments(norm(COMPONENTS))
    rows = strip_comments(norm(FORMROWS))
    n_kt = len(list(AND.rglob("*.kt")))
    c.ok("整棵源码树扫到了 " + str(n_kt) + " 个 .kt（下限 " + str(MIN_KT_FILES) + "）",
         n_kt >= MIN_KT_FILES,
         "目录改名了？那样「一处都没有」和「一处都没扫到」是同一个输出")
    c.ok("挂账单位页读到了内容（下限 " + str(MIN_SCREEN_CHARS) + " 字符）",
         len(screen) >= MIN_SCREEN_CHARS, "实际 " + str(len(screen)))
    c.ok("ui/theme/Color.kt 读到了内容（下限 " + str(MIN_COLOR_CHARS) + " 字符）",
         len(color) >= MIN_COLOR_CHARS, "实际 " + str(len(color)))
    c.ok("共用件还在定义处（本页只是用它们，没有各写一套）",
         "fun CardActionIcon(" in comp and "fun FormErrorLine(" in comp and "fun FormInputRow(" in rows)

    # ── 1. 老画法归零 ────────────────────────────────────────────────────
    c.section("1. 老画法一处都不留（居中弹窗 / 自摆输入框 / 页面级 error）")
    c.ok("页面上没有居中弹窗（AlertDialog 归零）", "AlertDialog(" not in screen)
    c.ok("页面不再自己摆输入框（SoTextField 归零，走的是共用行）", "SoTextField(" not in screen)
    c.ok("描边输入框一处都没有（白卡里不许出现 OutlinedTextField）", "OutlinedTextField(" not in screen)
    c.ok("showDialog 这个名字在页面与 VM 里都不剩（改叫 showSheet）",
         "showDialog" not in screen and "showDialog" not in vm)
    c.ok("页面不再读页面级 error（vm.error 归零）", "vm.error" not in screen)
    c.ok("页面上只剩标题栏那一把 IconButton（卡片动作不许退回裸图标）",
         screen.count("IconButton(") == 1 and "Icons.AutoMirrored.Filled.ArrowBack" in screen,
         "实际 " + str(screen.count("IconButton(")) + " 处")
    c.ok("页面上的 TextButton 只剩撤回那一个（没有平铺文字键当动作）",
         screen.count("TextButton(") == 1 and "vm.undoDelete()" in screen,
         "实际 " + str(screen.count("TextButton(")) + " 处")

    sheet = span(screen, "if (vm.showSheet) {", NL + "}" + NL)
    body = span(screen, 'FormGroup(Icons.Default.Business, "挂账单位"', "FormErrorLine(")
    unit = screen[screen.find("private fun UnitCard("):] if "private fun UnitCard(" in screen else ""

    # ── 2. 表单进抽屉、抽屉拉到最上面 ────────────────────────────────────
    c.section("2. 表单进抽屉、抽屉拉到最上面（规范 :1266-1269）")
    c.ok("抽屉整块在（if (vm.showSheet) 里就是 ModalBottomSheet）", bool(sheet))
    c.ok("是拉到最上面的底部抽屉（skipPartiallyExpanded = true）",
         "ModalBottomSheet(onDismissRequest = { vm.closeSheet() }, sheetState = sheetState) {" in sheet
         and "rememberModalBottomSheetState(skipPartiallyExpanded = true)" in sheet)
    c.ok("抽屉内容拉满（fillMaxWidth + fillMaxHeight）",
         ".fillMaxWidth()" in sheet and ".fillMaxHeight()" in sheet)
    c.ok("抽屉内容能滚（verticalScroll(rememberScrollState())）",
         ".verticalScroll(rememberScrollState())," in sheet)
    c.ok("键盘弹起时输入框够得着（imePadding）", ".imePadding()" in sheet)
    c.ok("行距与别的抽屉同一档（Arrangement.spacedBy(14.dp)）", "Arrangement.spacedBy(14.dp)," in sheet)
    c.ok("抽屉有关闭键与标题（SheetCloseButton + 新增/编辑挂账单位）",
         "SheetCloseButton(onClick = { vm.closeSheet() })" in sheet
         and 'if (vm.editing == null) "新增挂账单位" else "编辑挂账单位"' in sheet)

    # ── 3. 白卡分组 + 四行共用行 ────────────────────────────────────────
    c.section("3. 抽屉里是白卡分组 + 四行共用行（规范 :1253-1263 / §5.0）")
    c.ok("只有一张白卡分组，标题是本页的模块（挂账单位）",
         screen.count("FormGroup(") == 1
         and 'FormGroup(Icons.Default.Business, "挂账单位", Color(ArrearsTangerine)) {' in screen)
    c.ok("分组里恰好四行共用输入行（单位名称 / 联系电话 / 信用额度 / 备注）",
         body.count("FormInputRow(") == 4, "实际 " + str(body.count("FormInputRow(")) + " 行")
    c.ok("四行的标签就是这四个（标签里带「电话」「额度」是输入规则判据要认的）",
         '"单位名称",' in body and '"联系电话",' in body and '"信用额度",' in body and '"备注",' in body)
    c.ok("单位名称是必填（required = true），另外两行没挂 required",
         body.count("required = true") == 1)
    c.ok("电话行是数字键盘 + 输入时过滤非数字（InputRules.phoneInput）",
         "keyboardType = KeyboardType.Phone," in body
         and "{ vm.draftPhone = InputRules.phoneInput(it) }," in body)
    c.ok("选填的三行写「选填」，没有一行写「必填」",
         'placeholder = "选填' in body and "必填" not in body)
    c.ok("四行各有自己的图标（Business / Phone / AccountBalanceWallet / Notes）",
         "icon = Icons.Default.Business," in body and "icon = Icons.Default.Phone," in body
         and "icon = Icons.Default.AccountBalanceWallet," in body
         and "icon = Icons.Default.Notes," in body)

    # ── 4. 表单的错画在抽屉里 + 页脚 ────────────────────────────────────
    c.section("4. 表单的错画在抽屉里、页脚是取消 + 保存（规范 :469-478）")
    c.ok("抽屉里有 FormErrorLine(vm.formError) 一行（表单错的唯一去处）",
         sheet.count("FormErrorLine(vm.formError)") == 1)
    c.ok("整个页面只读 formError 这一处（不是页面级 error）", screen.count("vm.formError") == 1,
         "实际 " + str(screen.count("vm.formError")) + " 处")
    c.ok("页脚是两键一行：取消（描边）+ 保存（实心），两枚等宽 48dp",
         'Text("取消")' in sheet and 'Text("保存")' in sheet
         and sheet.count("Modifier.weight(1f).height(48.dp)") == 2)
    c.ok("保存键用的是本页的模块色 + 那个专用字色（CHG-0101 起砖红底压暖白字 ≈ 4.0:1）",
         "containerColor = Color(ArrearsTangerine)," in sheet
         and "contentColor = Color(OnArrearsTangerine)," in sheet)
    c.ok("砖红底上那个字色是 Color.kt 里的 token（不是就地手写 0xFF）",
         "val OnArrearsTangerine = 0xFFFFF3EEL" in color and "0xFF" not in screen)
    c.ok("没有退回页面级主操作键（PrimaryActionButton 归零）", "PrimaryActionButton(" not in screen)
    c.ok("提交途中两枚键都禁用（acting 时点不动，防重复提交）", sheet.count("enabled = !vm.acting,") == 2)

    # ── 5. 卡片动作 ──────────────────────────────────────────────────────
    c.section("5. 卡片动作按 §4.2c：左删右编、两枚都是圈底图标")
    c.ok("卡片动作行上恰好两枚圈底动作（CardActionIcon）", unit.count("CardActionIcon(") == 2,
         "实际 " + str(unit.count("CardActionIcon(")) + " 枚")
    c.ok("删除在最左（相反 / 警示类放最左，不吃右手拇指）",
         unit.find("Icons.Default.Delete") < unit.find("Icons.Default.Edit"))
    c.ok("删除用提示色 MessageRed（不是 colorScheme.error 那种「出错了」的红）",
         'Icons.Default.Delete, "删除", Color(MessageRed), onDelete,' in unit)
    c.ok("编辑在最右（惯用手是右手）：在 Spacer(weight(1f)) 之后",
         "Spacer(Modifier.weight(1f))" in unit
         and unit.find("Spacer(Modifier.weight(1f))") < unit.find("Icons.Default.Edit"))
    c.ok("两枚都带字（这一页的用户是派单员，只留图标会逼人靠猜）",
         'label = "删除"' in unit and 'label = "编辑"' in unit)
    c.ok("编辑用 NavBlue（规范里「编辑」的语义色）",
         'Icons.Default.Edit, "编辑", Color(NavBlue), onEdit,' in unit)
    c.ok("卡片里不再有裸 IconButton（用户 2026-09-22 原话「这个不行」）", "IconButton(" not in unit)
    c.ok("卡头是本页模块色的圆底图标（TintedIcon + ArrearsTangerine），不是 M3 默认蓝",
         "TintedIcon(Icons.Default.Business, Color(ArrearsTangerine), size = 20.dp, container = 38.dp)" in unit
         and "primaryContainer" not in unit)

    # ── 6. 删除软删 + 手边撤回 ──────────────────────────────────────────
    c.section("6. 删除一律软删 + 手边要有撤回（规范 :1328 / :1371）")
    c.ok("撤回行画在列表头顶（在 items( 之前，长列表里也在第一屏）",
         "vm.recentlyDeleted?.let { rd ->" in screen
         and screen.find("vm.recentlyDeleted?.let { rd ->") < screen.find("items(vm.units, key = { it.id })"))
    c.ok("撤回行是 LazyColumn 里包了一层 Column 的 item（item 里没有 ColumnScope）",
         'item(key = "undo") {' in screen)
    c.ok("那一行写的是「已删除「X」」+ 一个「撤销」键",
         '"已删除「" + rd.name + "」",' in screen
         and "TextButton(onClick = { vm.undoDelete() }, enabled = !vm.acting) {" in screen)
    c.ok("撤回行与列表之间有分隔（HorizontalDivider）",
         "HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)" in screen)
    c.ok("删空的时候撤回行还在（空状态多了一个条件：recentlyDeleted == null）",
         "vm.units.isEmpty() && vm.recentlyDeleted == null ->" in screen)
    c.ok("VM 里记着刚删掉的那一条（RecentlyDeleted）",
         "data class RecentlyDeleted(val id: Long, val name: String)" in vm
         and "var recentlyDeleted by mutableStateOf<RecentlyDeleted?>(null)" in vm)
    c.ok("删除成功后记下来 + snackbar 说清删了谁",
         "recentlyDeleted = RecentlyDeleted(u.id, u.name)" in vm
         and 'actionResult = "已删除「" + u.name + "」"' in vm)
    c.ok("撤销是真的调后端（repo.restoreArrearsUnit），不是把行塞回列表就完事",
         "fun undoDelete() {" in vm and "container.repo.restoreArrearsUnit(rd.id)" in vm)
    c.ok("撤销成功后清掉那一行（否则连删两次会不知道自己撤的是哪一个）",
         "recentlyDeleted = null" in vm)
    c.ok("删除失败如实报后端那句话（snackbar），不是页面级 error",
         "actionResult = toApiException(e).message" in vm)
    c.ok("删不掉的三种原因由后端原话给出（这一页只负责照报）",
         ("先改掉再删" in (norm(BACKEND) if BACKEND.exists() else "")))

    # ── 7. 三种错分开 ────────────────────────────────────────────────────
    c.section("7. 三种错分开：loadError / formError / notice（规范 :458-478）")
    c.ok("loadError 只在 load() 里写（进页面清空 + 失败填充，两处）", vm.count("loadError = ") == 2,
         "实际 " + str(vm.count("loadError = ")) + " 处")
    c.ok("formError 有七处写入（打开表单清空 ×2 / 三条校验（名称 / 电话 / 信用额度）/ 提交前清空 / 保存失败）",
         vm.count("formError = ") == 7, "实际 " + str(vm.count("formError = ")) + " 处")
    c.ok("没有裸的 error =（页面级与表单级的名字必须分得清）",
         (NL + "        error = ") not in vm and (NL + "            error = ") not in vm)
    c.ok("打开表单会清掉上一次的表单错误（否则「还没填，红字已经说我填错了」）",
         vm.count("formError = null") == 3, "实际 " + str(vm.count("formError = null")) + " 处")
    c.ok("页面级错误走整页 ErrorView + 重试",
         "vm.loadError != null -> ErrorView(vm.loadError.orEmpty(), onRetry = { vm.load() })" in screen)

    # ── 8. 接线 ──────────────────────────────────────────────────────────
    c.section("8. 接线：后端真能救回来、反向验证在、文档九节、登记簿与声明块有 CHG-0020")
    backend = norm(BACKEND) if BACKEND.exists() else ""
    c.ok("后端有 restore 端点（界面上那个「撤销」不是安慰键）",
         '@router.post("/{unit_id}/restore"' in backend)
    c.ok("仓库层有这条调用（页面 → VM → repo → api 一条线）",
         "fun restoreArrearsUnit(id: Long)" in norm(REPO))
    c.ok("规范里那条硬规矩还在（删除一律软删 + 手边要有撤回）",
         "删除一律软删" in norm(DESIGN) and "手边要有撤回" in norm(DESIGN))
    c.ok("反向验证脚本在（_tools/qa/_reverse_verify_arrears_units.py）", REVERSE.exists(),
         "没有反向验证的判据＝没人证明它真的会红")
    c.ok("本页登记进了「表单行单一来源」的 CONVERTED 表",
         "ui/dispatcher/ArrearsUnitsScreen.kt" in norm(PANEL))
    c.ok("表单抽屉清单里算上了本页（今天 6 个）", "今天 6 个" in norm(SHEET))
    #: ⚠️ 这里的数字是 CHG-0020 当时把上限收到的那个数（同页那一笔欠账销掉 ⇒ 收一格）。
    #: 2026-10-04 FEAT-0009 新开了一张分类名册页 ⇒ 上限放回 12；2026-10-03 BUG-0002 把
    #: 账户管理的「删号」销了账 ⇒ 上限又收到 11。
    #: 2026-10-05 CHG-0040 / CHG-0041：订单详情页与派单池都能**就地删一件货**（同一个后端硬删端点）
    #:   ⇒ 上限从 11 放到 13（理由与销账时机写在 _tools/qa/_check_delete_undo.py:86-89）。
    #: 这一条跟着写上限的当前值，但**本页不许再挂回欠账表**那半句永远不变。
    c.ok("删除/撤回的欠账表里没有本页了，上限也跟着收到 13（BUG-0002 销了账户管理的撤回；"
         "CHG-0040/0041 新增两个就地删货入口又放回 13，欠账待销）",
         "deleteArrearsUnit" not in norm(DELUNDO) and "EXEMPT_MAX = 13" in norm(DELUNDO))
    doc = norm(DOC) if DOC.exists() else ""
    c.ok("文档九节齐全（docs/changes/CHG-0020.md，认小节标题而不是字符）",
         all(("## " + s) in doc for s in ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")),
         "文档缺节")
    c.ok("登记簿里有 CHG-0020 这一行（整行，不是一个链接里的字样）",
         any(ln.startswith("| " + BT + "CHG-0020" + BT + " |") for ln in norm(REGISTRY).split(NL)),
         "没登记（别人不知道这个 ID 用掉了）")
    claim = norm(CLAIM) if CLAIM.exists() else ""
    c.ok("工作声明页上有 CHG-0020 的声明块（整条标题行，不是别处的字样）",
         re.search(r"^### \[[^\]]*\] 会话：\*\*CHG-0020 ", claim, re.M) is not None,
         "没声明就开工了（或者声明块被删了）")

    # ── 9. 卡上那一行余额（TB-01，CHG-0100 补）─────────────────────────
    c.section("9. 卡上那一行余额：欠多少来自客户欠款表，客户端一个减法都不做（TB-01）")
    balance = strip_comments(norm(BALANCE)) if BALANCE.exists() else ""
    c.ok("余额那一行在卡上（额度行之后、两枚动作之前）",
         "val line = arrearsBalanceLine(balance)" in unit
         and -1 < unit.find("信用额度") < unit.find("arrearsBalanceLine(balance)") < unit.find("CardActionIcon("),
         "额度行 / 余额行 / 动作行的相对位置不对")
    c.ok("这一句整句来自纯函数（页面不自己拼金额、不自己判超限）",
         "line.text" in unit and "line.warn" in unit and "balance?.creditUsed" not in unit)
    c.ok("余额取自客户欠款表（时点账：mode = day + 今天；只要余额那一行、不要逐单明细）",
         "container.repo.customerBalancesReport(" in vm and 'mode = "day",' in vm
         and "includeOrders = false," in vm)
    c.ok("只认挂着名册单位的那种行（kind == unit），unit_name 那种名字快照不贴到卡上",
         'private const val UNIT_KIND = "unit"' in vm and "it.kind == UNIT_KIND" in vm)
    c.ok("余额这一路有自己的错（balanceError），⛔ 不写页面级 loadError —— 写了整页名册会消失",
         "balanceError = toApiException(e).message" in vm and vm.count("loadError = ") == 2,
         "loadError 实际 " + str(vm.count("loadError = ")) + " 处")
    c.ok("余额取不到时页面给一次重试，且这一行画在列表里（名册还在）",
         "vm.retryBalances()" in screen and "vm.balanceError?.let" in screen)
    c.ok("四档措辞都在纯函数里（没欠过 / 不限额 / 还能赊 / 已超）",
         all(t in balance for t in ("到目前还没有欠款记录", "额度：不限额", "还能赊 ¥", "（已超）")))
    c.ok("「超了」用后端给的 over_limit，客户端不做 credit_used - limit 那个减法",
         "row.overLimit" in balance
         and re.search(r"creditUsed\s*-\s*|-\s*moneyToDouble", balance) is None)
    c.ok("「还能赊」算不出来时不当成 0（不许出现「还能赊 ¥0」那一档）",
         "if (available == null)" in balance and "还能赊 ¥0" not in balance)
    c.ok("这一行有单测（ArrearsBalanceLineTest.kt）", TEST_BALANCE.exists(),
         "没有单测的纯函数＝没人钉住这四档措辞")

    print(NL + "=" * 60)
    if c.fails:
        print("❌ " + str(len(c.fails)) + " 项未通过（通过 " + str(c.n_ok) + " 项）：")
        for label, _detail in c.fails:
            print("   - " + label)
        return 1
    print("✅ 全部 " + str(c.n_ok) + " 项通过：挂账单位页 —— 表单搬进拉到最上面的抽屉"
          "（白卡分组 + 四行共用行 + 错画在表单里）、卡片动作左删右编都是圈底图标、"
          "删除后手边就有真能救回来的「撤销」。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("挂账单位页（CHG-0020）判据覆盖：")
        print("1. 老画法归零：AlertDialog / SoTextField / OutlinedTextField / showDialog / vm.error 全 0，")
        print("   页面上只剩标题栏那一把 IconButton 与撤回那一个 TextButton")
        print("2. 抽屉三件套：ModalBottomSheet + skipPartiallyExpanded + 拉满 + imePadding + 能滚 + spacedBy(14.dp)")
        print("3. 白卡分组：一张 FormGroup + 四行 FormInputRow（名称必填 / 电话数字键盘 + phoneInput / "
              "信用额度 moneyInput + 留空即不限额 / 备注）")
        print("4. 表单错：FormErrorLine(vm.formError) 在抽屉里、页脚取消 + 保存（模块色 + 深棕字）")
        print("5. 卡片动作：左删（MessageRed）右编（NavBlue）两枚圈底带字、卡头 TintedIcon 模块色、无裸 IconButton")
        print("6. 撤回：列表头顶「已删除「X」+ 撤销」、撤销真调 repo.restoreArrearsUnit、删空时那一行还在")
        print("7. 三种错分开：loadError 只 load() 写、formError 七处、没有裸 error =")
        print("8. 接线：后端 restore 端点 + 仓库层调用 + 反向验证脚本 + 三张工具表 + 文档九节 + 登记簿 + 声明块")
        sys.exit(0)
    sys.exit(main())
