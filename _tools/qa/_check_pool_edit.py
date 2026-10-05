"""红线：派单员在「已完成派单」里改单 / 选司机时，**改完只通知司机、货主端一个字都不出**（CHG-0040）。

## 由来（用户 2026-10-05 逐字，语音转写）
「在这个阶段可以对订单进行更改，不管是货主、商品，全部都可以更改」
「如果更改的话，对应的司机是会收到消息的，说这个信息已经更改了」；
另有「司机一旦多起来、订单一旦多起来就是很容易找不到」⇒
「上面改一个可以选择司机的方式」「同样也是左边侧边栏」。

## 为什么必须有一条红线盯着它
两件事都是「坏了不报错」的形状：

1. **改单通知司机这条链路原本是静默失效的**：商品行的三个写端点（增 / 改 / 删）连 `outbox` 都没 import，
   改地址那条虽然发 `orders.edited`，但下游 `push_events.push_order_edited_to_driver`
   只发实时信号、**不落站内信**，而 Android `RealtimeHub.kt` 的 `when (e.type)` 里
   **根本没有 `order.updated` 这一支** ⇒ 司机列表不刷新、不响、消息中心也没有一条。
   这三处缺任何一处，用户提的需求都等于没做，而且没有任何东西会红。
2. **「只通知司机」是一条边界**：改单与「静默退回派单池」（CHG-0039）同一口径 —— 货主看得到的金额与件数
   会跟着变，但不该多出一条「你的单被改了」的消息。顺手给货主补一条推送，是这条边界最常见的破法。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。它的两个靶子都是「少一处、写反一处」的形状：
① 通知司机这条链路要**四处**同时成立（三个写端点各自 enqueue、下游落站内信、Android 认事件、
RealtimeHub 刷新列表），少任何一处都不报错 —— 用户提的需求等于没做，而编译、单测、
接口契约全绿；② 「只通知司机」是一条**否定式**边界（不许出货主事件），类型系统表达不了
"这里不许调那个函数"。所以判据只能扫结构：三个写端点里的事件名与调用顺序、下游两条腿、
Android 两个事件常量与分支。运行时那一头交给 _tools/qa/_reverse_verify_pool_edit.py
（按条注入破坏）与模拟器 5554 改备注后查库的端到端证据（发件箱行 + 站内信各一条）。

## 判据（清单全部自己算；路径写错会先在「读到几个文件」那条报红）
1. 明细三个写端点：都在 `db.commit()` 之前、`_resync_stock_if_assigned` 之后通知司机，且不发任何货主事件。
2. 司机收到的是**站内信**（`message_center.publish_order_edited_driver`）+ 实时信号（`order.updated`），
   幂等键带发件箱行号（否则同一张单第二次改动会被当成重复吞掉）；改地址那条老路径发同一个事件。
3. Android 认识这两个事件：`PushTrust.ORDER_TYPES` 含 `order.edited`、
   `RealtimeHub` 有 `order.updated` 分支（只刷新、不播报）。
4. 「已完成派单」的选司机：VM 侧筛 visibleGroups、界面侧左侧抽屉（MasterRail + PersonDrawer）、
   默认「全部司机」，且筛空与真空说的是两句不同的话。
5. 改单：收货信息 + 货物明细（增 / 改 / 删）都能改，明细一律重拉服务端权威值、
   加货按**这一单货主**的专属价报价；卡片上编辑在右、退回池子在左。
6. ⛔ 全仓不存在「改单通知货主」的路径（`publish_order_edited_shipper` 零命中）。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   python _tools/qa/_reverse_verify_pool_edit.py

用法：python _tools/qa/_check_pool_edit.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 剥 Kotlin 注释的实现只此一份（复用兄弟红线，不抄第二份）。
from _check_pagination_wiring import strip_comments  # noqa: E402
#: 剥 Python 注释 / 文档字符串（换成等长空格、保留行号）。
from _check_single_source import code_only  # noqa: E402
#: 失败行 / 章节标题的形状只此一份（房规）：失败行是 "  [!!]   <标题>" ——
#: _reverse_verify_*.py 正是拿这个前缀去认「这一条被判据抓住了」。
from _check_hints import Checker  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

PRODS = BACKEND / "app/api/v1/order_products.py"
MSG = BACKEND / "app/services/message_center.py"
PUSH = BACKEND / "app/services/push_events.py"
MAIN = BACKEND / "app/main.py"
CMD = BACKEND / "app/commands/order.py"

APIS = ANDROID / "data/remote/api/Apis.kt"
REPO = ANDROID / "data/repo/AppRepository.kt"
DTO = ANDROID / "data/remote/dto/Dtos.kt"
TRUST = ANDROID / "core/PushTrust.kt"
HUB = ANDROID / "core/RealtimeHub.kt"
PVM = ANDROID / "ui/dispatcher/DispatcherPoolViewModel.kt"
PSCR = ANDROID / "ui/dispatcher/DispatcherPoolScreen.kt"

#: 被点名的文件都必须在（少一个就先报红，不静默空转）。
REQUIRED = [PRODS, MSG, PUSH, MAIN, CMD, APIS, REPO, DTO, TRUST, HUB, PVM, PSCR]

C = Checker()


def ok(label: str, cond: bool, detail: str = "") -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def py(path: Path) -> str:
    """后端文件：注释与文档字符串已剥（保留行号）。"""
    return code_only(path.read_text(encoding="utf-8")) if path.is_file() else ""


def kt(path: Path) -> str:
    """Kotlin 文件：注释已剥。"""
    return strip_comments(path.read_text(encoding="utf-8")) if path.is_file() else ""


def py_section(path: Path, name: str) -> str:
    """后端某个**顶层函数**的源码段（到下一个顶层 def/class 为止）。空串 = 找不到。"""
    src = py(path)
    m = re.search(rf"(?m)^(?:async )?def {re.escape(name)}\(", src)
    if not m:
        return ""
    tail = src[m.end():]
    nxt = re.search(r"(?m)^(?:async )?def |^class ", tail)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(tail))]


#: Kotlin 函数的修饰符可以堆叠（private suspend fun …），且顶层 composable 缩进是 0 而不是 4 ⇒
#: 认「同一缩进上的下一个 fun / @ / }」才既收得到成员函数、也收得到文件末尾那批顶层 composable。
_KT_MODS = r"(?:(?:private|internal|public|protected|override|suspend|inline|operator|open|tailrec)\s+)*"
_KT_FUN = _KT_MODS + "fun "


def kt_section(path: Path, name: str) -> str:
    """Kotlin 某个函数的源码段（到同一缩进上的下一个 fun / @ / } 为止）。空串 = 找不到。"""
    src = kt(path)
    m = re.search(rf"(?m)^([ \t]*){_KT_FUN}{re.escape(name)}\(", src)
    if not m:
        return ""
    pad = re.escape(m.group(1))
    tail = src[m.end():]
    nxt = re.search(rf"(?m)^{pad}(?:{_KT_FUN}|@|\}})", tail)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(tail))]


def endpoint_positions(prods: str) -> list[int]:
    """三个明细写端点的起点（按出现顺序）；-1 = 找不到。"""
    out = []
    for name in ("create_order_product", "update_order_product", "delete_order_product"):
        m = re.search(rf"(?m)^def {name}\(", prods)
        out.append(m.start() if m else -1)
    return out


def main() -> int:
    section("0. 反空转：读到几个文件")
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED if not p.is_file()]
    ok("CHG-0040 点名的文件全在（12 个）", not missing, "缺：" + ", ".join(missing))
    api_mods = sorted((BACKEND / "app/api/v1").glob("*.py"))
    ok("api/v1 下模块 >= 20 个（防路径写错后空转）", len(api_mods) >= 20, f"实际 {len(api_mods)}")

    prods = py(PRODS)
    msg = py(MSG)
    push = py(PUSH)
    main_py = py(MAIN)
    helper = py_section(PRODS, "_notify_driver_lines_changed")
    evt = 'outbox.enqueue(db, "orders.edited", {"driver_id": order.driver_id, "order_id": order.id})'

    section("① 明细改动必须让经手那张单的司机知道（api/v1/order_products.py）")
    ok("_notify_driver_lines_changed 存在（明细改动的通知只此一处）", bool(helper))
    ok(
        "没派出去的单不发（order.driver_id is None 直接返回）",
        "if order.driver_id is None:" in helper,
        "待派单池里的单没有司机，发出去就是一条指向空气的消息",
    )
    ok("按订单聚合发 orders.edited（载荷只带 driver_id + order_id）", evt in helper)
    ok(
        "事件不背负「改了哪一处」（客户端重拉权威数据）",
        "delivery_description" not in helper and "quantity" not in helper,
    )
    ok("⛔ 不 commit（与本次业务写同一个事务 —— 发件箱的承诺）", "commit" not in helper)
    ok("⛔ 载荷里没有 shipper_id（这条事件只对司机说）", "shipper" not in helper)
    calls = prods.count("_notify_driver_lines_changed(db, order)")
    ok("三个写端点各通知一次（增 / 改 / 删）", calls == 3, f"实际 {calls} 处")
    pos = endpoint_positions(prods)
    ok("三个端点函数都找得到（防改名后位置比较空转）", all(i >= 0 for i in pos), f"位置 {pos}")
    for i, label in enumerate(("增", "改", "删")):
        seg = prods[pos[i]: pos[i + 1] if i + 1 < len(pos) else len(prods)]
        r = seg.find("_resync_stock_if_assigned")
        n = seg.find("_notify_driver_lines_changed(db, order)")
        c = seg.find("db.commit()")
        ok(
            label + "：通知在预占对账之后、commit 之前（先对账、再通知、最后提交）",
            -1 < r < n < c,
            f"resync={r} notify={n} commit={c}",
        )
    ok('⛔ 明细路径里没有「撤回 / 召回」那种会惊动货主的事件', '"orders.recalled"' not in prods)

    section("② 司机收到的是站内信 + 实时信号（message_center.py / push_events.py / main.py）")
    fn = py_section(MSG, "publish_order_edited_driver")
    ok("publish_order_edited_driver 存在（司机那条消息的唯一定义处）", bool(fn))
    ok("收件人是司机本人（recipient_id=driver_id）", "recipient_id=driver_id" in fn)
    ok('消息类型是 order.edited（客户端按前缀 order. 刷新列表）', 'type="order.edited"' in fn)
    ok('标题写「订单信息有修改」', 'title="订单信息有修改"' in fn)
    ok(
        "值得念出来（司机正在跑这一单，speech_important=True）",
        "speech_important=True" in fn,
        "改的是「送到哪、送给谁、送几件」",
    )
    ok("正文不猜改了哪一处，只让他去详情核对（说错一处比不说更坏）", "打开订单详情核对" in fn)
    ok(
        "幂等键带发件箱行号（同一张单第二次改动不能被当成重复吞掉）",
        "str(event_id)" in fn and "order.edited" in fn,
    )
    ok(
        '实时信号是 order.updated（界面据此重拉）',
        'emit_realtime(driver_id, {"type": "order.updated", "order_id": order_id})' in fn,
    )
    ok("⛔ 这条消息里没有任何给货主的投递", "shipper" not in fn)
    pf = py_section(PUSH, "push_order_edited_to_driver")
    ok("push_order_edited_to_driver 存在", bool(pf))
    ok(
        "它调的是刚才那条站内信（不是只发一句实时信号）",
        "publish_order_edited_driver(db, driver_id, order_id, event_id=event_id)" in pf,
        "只发实时信号 = 司机消息中心里什么都没有，而列表刷不刷新没人看得出",
    )
    ok("event_id 一路传到幂等键（default 0 只是给老调用点留的）", "event_id: int = 0" in pf)
    branch = ""
    m = re.search(r'if event\.event_type == "orders\.edited":\n(?:.*\n){1,6}', main_py)
    if m:
        branch = m.group(0)
    ok("main.py 有 orders.edited 的处理支", bool(branch))
    ok(
        "main.py 把发件箱行号一起传下去（event_id=event.id）",
        "event_id=int(event.id or 0)" in branch,
        "不传的话第二次改单的站内信会被幂等键吞掉",
    )
    ok("改地址那条老路径仍然发同一个事件（两条路合成一条消息口径）", evt in py(CMD))

    section("③ Android 认识这两个事件（core/PushTrust.kt / core/RealtimeHub.kt）")
    ok('PushTrust 的订单事件清单里有 "order.edited"', '"order.edited",' in kt(TRUST))
    hub = kt(HUB)
    ok(
        'RealtimeHub 有 "order.updated" 分支（以前一支都没有 ⇒ 后端发了没人认）',
        '"order.updated" -> _refreshOrders.tryEmit(Unit)' in hub,
    )
    upd = ""
    for line in hub.splitlines():
        if '"order.updated" ->' in line:
            upd = line
    ok(
        "⛔ 这一支只刷新、不播报（改单不是新任务，别半夜念出来）",
        bool(upd) and "announce(" not in upd,
    )

    section("④ 「已完成派单」的选司机（DispatcherPoolViewModel.kt / DispatcherPoolScreen.kt）")
    pvm = kt(PVM)
    pscr = kt(PSCR)
    ok("VM 有筛选状态 driverFilterId", "var driverFilterId by mutableStateOf" in pvm)
    ok(
        "筛选只筛「已完成派单」的组，不动分组本身",
        "dispatchedGroups.filter { driverFilterId == null || it.driverId == driverFilterId }" in pvm,
    )
    ok("触发行文案取自 VM（driverFilterLabel）", "val driverFilterLabel: String" in pvm)
    ok(
        "名册没拉到时不许编数字（「全部司机」/「全部司机（N 位）」两种说法）",
        '"全部司机"' in pvm and "drivers.size" in pvm,
    )
    ok("选人有唯一入口 pickDriver(driverId: Long?)", "fun pickDriver(driverId: Long?)" in pvm)
    ok("拉已完成档时顺手把名册补上（详情页借的 VM 名册是空的）", "if (drivers.isEmpty()) loadDrivers()" in pvm)
    ok(
        "那句话在 loadDispatched 里（不是别处）",
        "if (drivers.isEmpty()) loadDrivers()" in kt_section(PVM, "loadDispatched"),
    )
    ok(
        "触发行只在已完成那一档出现，标签写「司机」",
        re.search(
            r"if \(vm\.tab == DispatcherPoolViewModel\.TAB_COMPLETED\) \{\n\s*PersonTriggerRow\(",
            pscr,
        )
        is not None
        and 'label = "司机",' in pscr,
        "⛔ 只判「那个判断在不在」会漏：标题那行也用同一个判断 ⇒ 触发行改成分档照样绿（反向验证第 29 条实测）",
    )
    ok("触发行用的是共用件 PersonTriggerRow", "PersonTriggerRow(" in pscr)
    drawer = kt_section(PSCR, "PoolDriverFilterDrawer")
    ok("抽屉存在（PoolDriverFilterDrawer）", bool(drawer))
    ok(
        "是左侧抽屉（ModalNavigationDrawer + ModalDrawerSheet）",
        "ModalNavigationDrawer(" in drawer and "ModalDrawerSheet {" in drawer,
    )
    ok("左栏车型分档用共用件 MasterRail", "MasterRail(" in drawer)
    ok(
        "抽屉默认落在「真的有人」的档（空档当默认 = 点开就是空名单）",
        'vm.drivers.any { (it.vehicleType ?: "") == k }' in drawer and "shownKinds.firstOrNull()" in drawer,
    )
    ok("右栏名单用共用件 PersonDrawer + PersonOption", "PersonDrawer(" in drawer and "PersonOption(" in drawer)
    ok("搜索认名字与手机号（唯一实现 core/UserSearch.kt）", "UserSearch.matches(" in drawer)
    ok('默认「全部司机」一颗（allLabel）', 'allLabel = "全部司机"' in drawer)
    ok(
        "抽屉滑回去时状态跟着收（否则下次点触发行打不开）",
        "DrawerValue.Closed && vm.showDriverPicker" in drawer,
    )
    dl = kt_section(PSCR, "DispatchedList")
    ok("列表画的是筛过的组 vm.visibleGroups", "vm.visibleGroups.forEach" in dl)
    ok("⛔ 不再直接画全部组（筛了人还画全部 = 筛选假生效）", "vm.dispatchedGroups.forEach" not in pscr)
    ok(
        "筛空与真空说两句不同的话",
        '"这位司机现在没有在途的单"' in dl and '"还没有派给司机的单"' in pscr,
        "筛空被读成「这些天白干了」是这条功能最容易出的错",
    )
    ok("池页面里 AssignDriverDialog( 仍只出现 1 次（共用弹窗，别写第二份）", pscr.count("AssignDriverDialog(") == 1)
    ok("⛔ 池页面不许出现 ExposedDropdownMenuBox（形态判据）", "ExposedDropdownMenuBox" not in pscr)

    section("⑤ 改单：收货信息 + 货物明细（VM / 屏幕）")
    ok("VM 有打开改单 openEdit(order: OrderDto)", "fun openEdit(order: OrderDto)" in pvm)
    ok("VM 有清状态 closeEdit()", "fun closeEdit()" in pvm)
    save = kt_section(PVM, "saveEdit")
    ok("saveEdit 存在", bool(save))
    ok("两个电话各挡一道格式（规则唯一实现 core/InputRules.kt）", save.count("InputRules.phoneError(") == 2)
    ok("走既有改单端点 updateOrder + OrderUpdateRequest", "container.repo.updateOrder(" in save and "OrderUpdateRequest(" in save)
    ok(
        "内部备注原样带回去（这一层不改它）",
        "internalNotes = o.internalNotes" in save,
        "漏了它会把司机可见的内部备注一起清空",
    )
    ok("成功提示点名司机（用户要的就是「司机会收到消息」）", "司机那边会收到一条消息" in save)
    ok("防连点（一次改动进行中不再发第二次）", "if (editBusy) return" in save)
    ok(
        "明细从服务端重拉（fetchEditLines + orderProductLines）",
        "container.repo.orderProductLines(orderId)" in kt_section(PVM, "fetchEditLines"),
    )
    ok(
        "⛔ 不拿订单详情里那份明细当编辑值（不是同一个类型，也拿不到行 id）",
        "orderProducts" not in pvm,
    )
    ok("空列表与正在拉分得开（editLinesLoading）", "var editLinesLoading" in pvm)
    saveline = kt_section(PVM, "saveLine")
    ok(
        "数量与单价一起报（只报单价会按旧数量重算行金额）",
        "OrderProductUpdateRequest(quantity = qty, unitPrice = price)" in saveline,
    )
    ok("数量必须是大于 0 的整数（本地先挡一道）", "qty <= 0" in saveline)
    ok("单价必须是数字（本地先挡一道）", "toDoubleOrNull() == null" in saveline)
    ok("删行走 deleteOrderProduct", "container.repo.deleteOrderProduct(line.id)" in kt_section(PVM, "deleteLine"))
    addp = kt_section(PVM, "addPickedLines")
    ok("加行走 addOrderProduct + OrderProductCreateRequest", "OrderProductCreateRequest(" in addp)
    ok("加行成功件数如实报（加了两件就说两件）", "added" in addp and "件货" in addp)
    ok(
        "一件都没加上时原因留在弹层里（选品页留着让他重试）",
        "firstError" in addp,
        "静默吞掉 = 他以为加上了",
    )
    pf2 = kt_section(PVM, "priceFor")
    ok(
        "专属价的守卫：这份规则不属于这一单货主就回退默认价",
        "priceRulesShipper != sid" in pf2 and "p.defaultUnitPrice" in pf2,
        "专属价规则没到 ≠ 这个货主没有专属价；按默认价报价就是多收他的钱",
    )
    lp = kt_section(PVM, "loadPriceRules")
    ok(
        "拉专属价失败时不假装「没有专属价」（清空 + 置 null）",
        "priceRules = emptyMap()" in lp and "priceRulesShipper = null" in lp,
    )
    ok("选品件的报价回调走 VM（priceFor = { vm.priceFor(it) }）", "priceFor = { vm.priceFor(it) }" in pscr)
    edit = kt_section(PSCR, "PoolEditSheet")
    ok("改单抽屉存在（PoolEditSheet）", bool(edit))
    ok("用底部抽屉（ModalBottomSheet），不是居中弹窗", "ModalBottomSheet(" in edit)
    ok(
        "六个字段都在（地址 / 收货人 / 收货人电话 / 下单人 / 下单人电话 / 备注）",
        all(t in edit for t in ('"收货地址"', '"收货人"', '"收货人电话"', '"下单人"', '"下单人电话"', '"备注"')),
    )
    ok("失败原因画在弹层里（FormErrorLine，不是整页 ErrorView）", "FormErrorLine(vm.editError)" in edit)
    ok(
        "逐字承诺货主无感（与「退回池子」同一个口径）",
        "改完只通知司机，货主端不会有任何提醒。" in edit,
        "用户明确要求：改单只让司机知道",
    )
    ok("有「加一件货」入口（拉选品件）", 'Text("加一件货")' in edit and "vm.showLinePicker = true" in edit)
    ok("明细逐行可改（openLineEdit）", "vm.openLineEdit(line)" in edit)
    line = kt_section(PSCR, "PoolLineSheet")
    ok("行编辑弹层存在（PoolLineSheet）", bool(line))
    ok("数量与单价都能改", '"数量"' in line and '"单价（元）"' in line)
    ok(
        "删这件货在左边且是警示色（与卡片上「退回池子」同一个规矩）",
        'Text("删掉这件货", color = MaterialTheme.colorScheme.error)' in line,
    )
    ok("删这件货走 vm.deleteLine()", "vm.deleteLine()" in line)
    ok(
        "明细行的单价过了金额显示漏斗（⛔ 直接印后端 60.0000 正是 _check_money_display.py §3 抓的形态）",
        '" · ¥" + trimMoneyZeros(line.unitPrice)' in edit,
        "2026-10-05 实机看到「×2件 · ¥60.0000」；显示口径见 util/Money.kt",
    )
    ok(
        "价框预填走 trimMoneyZeros（60.0000 要填成 60；⛔ 不用 formatMoney，会把 12.3456 填成 12.35）",
        "linePrice = trimMoneyZeros(line.unitPrice)" in pvm,
        "可编辑金额框的预填规矩：去尾零但保四位精度",
    )
    ok("卡片右侧「编辑」（编辑类动作在右：用户 2026-09-22 定的惯用手规矩）", 'Text("编辑")' in dl and "extra = {" in dl)
    ok(
        "左侧仍是「退回池子」（反向动作在左）",
        '"退回池子"' in dl and 'Text("编辑")' in dl and dl.index('"退回池子"') < dl.index('Text("编辑")'),
    )

    section("⑥ 反过来：全仓不存在「改单通知货主」的路径")
    hits = []
    for p in sorted((BACKEND / "app").rglob("*.py")):
        if "publish_order_edited_shipper" in p.read_text(encoding="utf-8"):
            hits.append(str(p.relative_to(ROOT)))
    ok("⛔ 没有 publish_order_edited_shipper（改单不许给货主发消息）", not hits, "命中：" + ", ".join(hits))
    hits2 = []
    pat = re.compile(r'outbox\.enqueue\(\s*db,\s*"orders\.edited"[^)]*shipper_id')
    for p in sorted((BACKEND / "app").rglob("*.py")):
        if pat.search(p.read_text(encoding="utf-8")):
            hits2.append(str(p.relative_to(ROOT)))
    ok("⛔ orders.edited 的载荷里从不带 shipper_id", not hits2, "命中：" + ", ".join(hits2))

    print("\n" + "=" * 60)
    if C.fails:
        print(f"❌ {len(C.fails)} 项不通过（通过 {C.n_ok} 项）：")
        for label, _ in C.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {C.n_ok} 项通过：改单只通知司机、货主端零提醒；选司机筛的是真列表。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
