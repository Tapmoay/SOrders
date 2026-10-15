# -*- coding: utf-8 -*-
"""红线：订单详情页改「地点信息」怎么改 —— 地点库（线路 / 我的地点 / 共享地点）、地图选点、
「我就在这里」，以及最关键的一条：**改完这一单要真的落坐标**（CHG-0133，2026-10-15 用户点名）。

## 由来（用户点名）
要的形态是一句话：改地点要能像下单页那样**从地点库里挑**、能**在地图上点一个点**、能说
**「我就在这里」**，而且**订单要落坐标**。这一页原来只有一个手打的多行框 —— 派单员在电话里听到
新地址就照念一遍，而**司机是按坐标走的**：文字换了、坐标没动，司机照旧开去**上一个点**。

## 为什么必须有一条红线盯着它
这一块的每一处都会"坏得没有声音"：

* **只改文字、不动坐标**：界面看起来改成功了（文字确实是新的），司机照坐标开到老地方。
  详情页那张只读地图、司机端导航、后端交付口径全按坐标 —— 没有任何一处会报错。
* **坐标悄悄丢掉**：后端 `PATCH /orders/{id}` 的缺席语义是"不给就不改"，客户端哪天忘了把这两栏
  报上去，文字换了、坐标没了，司机连"照坐标走"都做不到，只能拿地址文字猜一个位置。
* **定位回流不设闸**：「地图选点」那个弹层**一打开就会自己发一次定位**；不认"是不是我发起的那次"，
  用户点开地图、一个点都没点，地址就被悄悄改了 —— 两处都不报错。
* **自己判一遍坐标闸**：高德失败时照常回调 `(0,0)`，界面若不复用全仓唯一那份 `hereResultOf`，
  等于给这一单落一个"几内亚湾"的坐标。
* **另起第二套零件**：地点库抽屉与地图弹层若在这里复制一份，两页从此各修各的（共用件本体只有一份：
  `ui/shipper/OrderCreateScreen.kt::AddressPickerSheet` 与 `ui/common/AmapPicker.kt::AmapPickerDialog`）。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。以上五处都是"少一行 guard / 少报一个字段 /
多抄一份零件"的形状：不会编译失败，也不会让任何单测变红（后端与 DTO 一个字都不用改）。
接口那一半已经先做了（`OrderEditHost` 收口三个入口，界面只经 `edit.appContainer` 拿容器），
但"三颗按钮有没有挂在接口上""坐标有没有随这一单报上去""闸在不在请求之前"只存在于**调用点**，
所以判据只能扫结构。运行时那一头交给 `_tools/qa/_reverse_verify_detail_place_edit.py`（9 种破坏方式全被抓）
与三台模拟器实测（5554 派单员：三个入口 + 保存后坐标真的变了；5556 货主端：这一块根本进不去）。

## 已知边界（本刀**不**管，别以为它管了）
派单员那条路的审计 payload（`DISPATCHER_TRACKED_FIELDS`）仍只有 `delivery_description` /
`address_detail` / `remark` 三项 —— **坐标不在里面**。这是 R2-02 冻结的行为，且被
`_tools/qa/_check_order_contact_edit.py:323` 逐字钉着（"三项…行为冻结"）；改它＝改审计日志的形状，
那是另一次要带正式审查的改动（见 CHG-0133 变更单的 Known Limitations）。
所以本判据**只**断言"坐标真的报上去了"，不断言"审计里留下了坐标"。

## 判据（清单全部自己算；路径写错会先在「读到几个文件」那条报红）
1. 三颗入口（地图选点 / 地址库 / 我就在这里）都挂在 `OrderEditHost` 上，界面只经接口拿容器；
   取点路径全 App 只有一条（`container.locationManager`），界面不重复判坐标闸。
2. 定位回流只认"自己发起的那一次"；两条失败路径（发起不了 / 没有权限）与超时都能收尾，
   不许永远停在「正在定位…」。
3. 坐标摆到脸上：缺坐标当场说（橙），"文字改了、坐标没动"由 `addressCoordNotice` 点名。
4. VM：三份名册一起刷、挑一条只落草稿、共享库五个管理动作与下单页同一批文案、
   反馈一律走 `actionResult`（这一页不许出现弹窗式提示）。
5. **坐标真的落库**：`startEdit` 铺草稿 → `saveEdit` 取草稿 → fail-closed 闸（本来带着坐标、
   草稿却空了就拒存）→ 两个坐标字段随这一单报上去；顺序必须是"先校验、后请求"。
6. 详情页那两个弹层挂在**屏级**（不在 LazyColumn 里），用的是共用件本体，标题是「改收货地址」
   （「选择收货地址」是下单页那一页的话），共享库管理入口喂给抽屉的是**角色门**
   （`place:manage` 货主也有，不能拿它当这道门）。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   python _tools/qa/_reverse_verify_detail_place_edit.py

用法：python _tools/qa/_check_detail_place_edit.py
"""

from __future__ import annotations

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
#: 截段落只此一份（[start, stop)，找不到 start 给空串）。
from _check_place_picker_shared import region  # noqa: E402
#: 认「同一个缩进上的下一个 fun / @ / }」的取段实现只此一份（复用那条红线的，不抄第二份）。
from _check_detail_inline_edit import kt_section  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

#: CHG-0133 点名的三个 Kotlin 文件（就是这一块的写入口与两个宿主）。
INLINE = ANDROID / "ui/order/OrderEditInline.kt"
DETAIL_VM = ANDROID / "ui/order/OrderDetailViewModel.kt"
DETAIL = ANDROID / "ui/order/OrderDetailScreen.kt"
#: 判据引用的"权威"：DTO、共用件的调用方口径、后端两条边界。
DTOS = ANDROID / "data/remote/dto/Dtos.kt"
CAPS = ANDROID / "core/Capabilities.kt"
SHIPPER_VM = ANDROID / "ui/shipper/OrderCreateViewModel.kt"
CREATE = ANDROID / "ui/shipper/OrderCreateScreen.kt"
ORDER_CMD = BACKEND / "app/commands/order.py"
PLACES_API = BACKEND / "app/api/v1/places.py"

#: 被点名的文件都必须在（少一个就先报红，不静默空转）。
REQUIRED = [INLINE, DETAIL_VM, DETAIL, DTOS, CAPS, SHIPPER_VM, CREATE, ORDER_CMD, PLACES_API]

#: 「改收货人」是另一扇门（saveContactOnly）：从地址库里挑一条线路不该顺手把这一单的收货人换掉。
CONTACT_KEYS = ("contactDongjiaName", "contactBossName", "contactDongjiaPhone", "contactBossPhone")

#: 共享库的五个管理动作与它们的八句文案（与下单页 / 地址页逐字同一批话）。
MANAGE_LINES = (
    'actionResult = "没有要改的内容"',
    "container.repo.updatePlace(id, PlaceUpdateRequest(name = name, detailAddress = address))",
    'actionResult = "已改共享地点"',
    "container.repo.deletePlace(id)",
    "recentlyDeletedPlace = id to (places.firstOrNull { it.id == id }?.name.orEmpty())",
    'actionResult = "已从共享地点库删除（别人的选点列表里也没有它了；删错了可以点「撤销」）"',
    "container.repo.restorePlace(id)",
    "recentlyDeletedPlace = null",
    'actionResult = "已恢复这条共享地点"',
    "container.repo.demotePlace(id)",
    'actionResult = if (r.created) "已撤销，并存进了你的「我的地点」"',
    'else "已撤销（你本来就有这个地点，没有重复加）"',
    "container.repo.shareLocation(l.id)",
    'actionResult = if (p.merged) "已并入共享地点库里的「${p.name}」（坐标相近，没有重复建）"',
    'else "已设为共享地址，以后大家都能直接选它"',
)

#: 反空转：这一块该有的关键锚点（命中数低于此数＝判据自己被改瞎了）。
ANCHORS = (
    "edit.openAddressMap()", "edit.openAddressLibrary()", '"我就在这里"',
    "container.locationManager.requestSingle()", "container.locationManager.locations.collect { pt ->",
    "if (!locatingHere) return@collect", "hereResultOf(pt.lat, pt.lng, pt.address)",
    "edit.applyPickedCoord(r.lat, r.lng, r.address)", "DETAIL_HERE_TIMEOUT_MS", '"还没选坐标"',
    "edit.addressCoordNotice", "editDrafts[OrderEditField.ADDRESS_LAT] = o.addressLat.orEmpty()",
    "val latDraft = draft(OrderEditField.ADDRESS_LAT).trim()", "addressLat = latDraft.ifBlank { null },",
    "container.repo.placesPage(q)", "container.repo.usePlace(p.id)", "container.repo.shareLocation(l.id)",
    "vm.showAddressSheet", "vm.showAddressMap", "vm.applyPickedCoord(lat, lng, address)",
)

C = Checker()


def ok(label: str, cond: bool, detail: str = "") -> None:
    C.ok(label, cond, detail)


def section(title: str) -> None:
    C.section(title)


def kt(path: Path) -> str:
    """Kotlin 文件：注释已剥（注释里写"这里必须落坐标"是不算数的）。"""
    return strip_comments(path.read_text(encoding="utf-8")) if path.is_file() else ""


def py(path: Path) -> str:
    """后端文件：注释与文档字符串已剥（保留行号）。"""
    return code_only(path.read_text(encoding="utf-8")) if path.is_file() else ""


def flat(text: str) -> list:
    return text.splitlines()


def main() -> int:
    # ---- ⓪ 反空转 --------------------------------------------------------
    section("⓪ 反空转：被点名的文件都在，关键锚点读得到")
    for p in REQUIRED:
        ok(f"{p.name} 在且非空", p.is_file() and p.stat().st_size > 0, str(p))
    inline = kt(INLINE)
    vm = kt(DETAIL_VM)
    detail = kt(DETAIL)
    dto = kt(DTOS)
    cmd = py(ORDER_CMD)
    places = py(PLACES_API)
    hits = sum(1 for a in ANCHORS if a in inline + vm + detail)
    ok("关键锚点命中数有下限（判据没瞎）", hits >= 16, f"命中 {hits}/{len(ANCHORS)}")

    # ---- ① 内联块：三颗入口 + 唯一取点路径 --------------------------------
    section("① 「地点信息」这一块：三个入口都挂在接口上，取点路径只有一条")
    block = kt_section(INLINE, "AddressEditBlock")
    ok("AddressEditBlock 段找得到", bool(block))
    ok(
        "签名逐字（宿主只收一个 edit；界面拿不到别的东西）",
        "fun AddressEditBlock(edit: OrderEditHost, modifier: Modifier = Modifier) {" in inline,
    )
    ok("界面只经接口拿容器（全仓唯一一条路）", "val container = edit.appContainer" in block)
    ok("⛔ 界面层不直接调仓库（要数据就经接口）", ".repo." not in inline)
    ok("「地图选点」那颗走接口", "edit.openAddressMap()" in block)
    ok("「地址库」那颗走接口", "edit.openAddressLibrary()" in block)
    ok("「我就在这里」那颗走本块（同一次定位）", "locateHereNow()" in block)
    ok("三颗按钮的文案逐字（与下单页同一批）",
       'Text("地图选点")' in block and 'Text("地址库")' in block
       and 'Text(if (locatingHere) "正在定位…" else "我就在这里")' in block)
    ok("定位只有一条路：container.locationManager（全 App 唯一取点路径）",
       "container.locationManager.requestSingle()" in block
       and "container.locationManager.locations.collect { pt ->" in block)
    ok("⛔ 不许退到 DeviceLocation（WGS84，国内偏几百米）", "DeviceLocation" not in inline)
    ok("⛔ 坐标闸只有一份：本文件不许再搬一遍 SunLocation（闸在 hereResultOf 里）",
       "SunLocation" not in inline)
    ok("回流只认自己发起的那一次（地图弹层一开就自己定位，不设闸会静默改地址）",
       "if (!locatingHere) return@collect" in block)
    ok("回流走全仓唯一那份 hereResultOf，且两支都接住",
       "hereResultOf(pt.lat, pt.lng, pt.address)" in block
       and "is HereResult.Fill ->" in block and "is HereResult.Say ->" in block)
    ok("定到的点落进草稿（不直接写库）", "edit.applyPickedCoord(r.lat, r.lng, r.address)" in block)
    ok("发起不了（requestSingle 返回 false）就当场收尾",
       "if (!container.locationManager.requestSingle()) {" in block
       and 'locateHereError = "定位没启动起来：请检查定位权限，或改用「在地图上选点」。"' in block)
    ok("没有权限也要收尾（不许永远停在「正在定位…」）",
       '"没有定位权限，拿不到当前位置。"' in block)
    ok("兜底时限是自己那一份常量（地址页那个是 private，跨文件用不了）",
       "private const val DETAIL_HERE_TIMEOUT_MS = 20_000L" in inline)
    ok("⛔ 不许去引用地址页的 HERE_LOCATE_TIMEOUT_MS（那是另一个文件的私有常量）",
       "HERE_LOCATE_TIMEOUT_MS" not in inline)
    ok("超时也收尾，并给出另一条出路",
       "delay(DETAIL_HERE_TIMEOUT_MS)" in block
       and '"定位超时，没拿到当前位置：请重试，或改用「在地图上选点」。"' in block)
    ok("坐标摆到脸上：缺坐标当场说（橙，与下单页同一个色）",
       "if (latDraft.isBlank() || lngDraft.isBlank()) {" in block
       and '"还没选坐标"' in block and "Color(0xFFF59C00)" in block)
    ok("有坐标就画出来（司机最终照着走的那个点）", '"坐标：$latDraft，$lngDraft"' in block)
    ok("「文字改了、坐标没动」由接口那句话点名", "edit.addressCoordNotice?.let { msg ->" in block)
    ok("这一块只有一个输入框（地址文字那一个，且是多行）",
       block.count("EditBox(") == 1 and "minLines = 2," in block and "singleLine = false," in block)
    ok("保存仍走同一个 saveEdit（坐标与文字一起提交）",
       'saveLabel = "保存地址",' in block and "onSave = { edit.saveEdit() }," in block
       and "onCancel = { edit.cancelEdit() }," in block)

    # ---- ② 接口收口 -------------------------------------------------------
    section("② 接口收口：新入口都开在 OrderEditHost 上（详情页那处调用不加参数）")
    host = region(inline, "interface OrderEditHost {", "object OrderEditField {")
    ok("OrderEditHost 段找得到", bool(host))
    ok("接口交出容器（界面拿容器的唯一一条路）", "val appContainer: AppContainer" in host)
    ok("接口有 openAddressLibrary()", "fun openAddressLibrary()" in host)
    ok("接口有 openAddressMap()", "fun openAddressMap()" in host)
    ok("接口有 applyPickedCoord(lat, lng, address)（选点与定位的同一条回流）",
       "fun applyPickedCoord(lat: Double, lng: Double, address: String)" in host)
    ok("接口有 addressCoordNotice（「文字改了、坐标没动」那句话）", "val addressCoordNotice: String?" in host)
    ok("详情页那处调用逐字 AddressEditBlock(edit)（加参数＝绕过接口，也踩内联那条红线）",
       "AddressEditBlock(edit)" in detail and "AddressEditBlock(edit," not in detail)
    ok("⛔ 详情页不许自己拿容器喂给这一块（容器只能从接口上取）",
       "appContainer = " not in detail)

    # ---- ③ VM：名册 / 挑一条 / 管理动作 -----------------------------------
    section("③ VM：三份名册一起刷、挑一条只落草稿、管理动作照抄下单页的话")
    ok("VM 就是宿主（容器只交给接口这一条路）",
       "override val appContainer: AppContainer get() = container" in vm)
    ok("共享库管理那道门是角色门（与下单页 / 地址页同一口径）",
       'container.tokenStore.cachedRole() == "dispatcher"' in vm)
    open_lib = kt_section(DETAIL_VM, "openAddressLibrary")
    ok("开抽屉之前先刷名册（这个 VM 从进页面起一直活着）",
       -1 < open_lib.find("reloadAddressLibrary()") < open_lib.find("loadPlaces()")
       < open_lib.find("showAddressSheet = true"))
    reload_lib = kt_section(DETAIL_VM, "reloadAddressLibrary")
    ok("三份名册一起刷（分组改名会在后端级联改地点的 category）",
       "placeCategories = container.repo.placeCategories()" in reload_lib
       and "addresses = container.repo.addresses()" in reload_lib
       and "locations = container.repo.locations()" in reload_lib)
    load_places = kt_section(DETAIL_VM, "loadPlaces")
    ok("共享地点走分页那一页（不分页拉＝列表迟早被截断）",
       "container.repo.placesPage(q)" in load_places and "places = page.rows" in load_places
       and "placesTruncated = page.meta.hasMore" in load_places
       and "placesLimit = page.meta.limit" in load_places)
    picked = kt_section(DETAIL_VM, "applyPickedCoord")
    ok("地图点选 / 定位的回流：三条 setDraft 一起落（地址文字与坐标是一个整体）",
       "setDraft(OrderEditField.ADDRESS_LAT, coordDraft(lat))" in picked
       and "setDraft(OrderEditField.ADDRESS_LNG, coordDraft(lng))" in picked
       and "setDraft(OrderEditField.ADDRESS_DETAIL, address)" in picked)
    ok("坐标落草稿前先归一成 6 位小数（⛔ Double.toString() 会把 23.021498 印成 23.021498000000005；"
       "屏上与报上去的都是这一份草稿）",
       'private fun coordDraft(v: Double): String = String.format(java.util.Locale.US, "%.6f", v)' in vm
       and "lat.toString()" not in picked and "lng.toString()" not in picked)
    ok("落完就关弹层（选点是「选完就走」，不叠在屏上）",
       "showAddressMap = false" in picked and "showAddressSheet = false" in picked)
    ok("从线路里挑一条：文字与坐标一起落草稿",
       "setDraft(OrderEditField.ADDRESS_DETAIL, a.detailAddress)" in kt_section(DETAIL_VM, "pickAddressDraft")
       and "setDraft(OrderEditField.ADDRESS_LAT, a.addressLat.orEmpty())" in kt_section(DETAIL_VM, "pickAddressDraft"))
    ok("从我的地点 / 共享地点挑：地址为空时回落到名字（与下单页同一条回落）",
       "l.detailAddress.ifBlank { l.name }" in kt_section(DETAIL_VM, "pickLocationDraft")
       and "p.detailAddress.ifBlank { p.name }" in kt_section(DETAIL_VM, "pickPlaceDraft"))
    place_draft = kt_section(DETAIL_VM, "pickPlaceDraft")
    ok("挑过共享地点就记一次用量（第 2 次后端自动收进「我的地点」）",
       "container.repo.usePlace(p.id)" in place_draft and "if (r.autoAdded) {" in place_draft)
    ok("自动加库要如实说一句（静默改用户的库，他下次只能猜）",
       '已加进你的「我的地点」' in place_draft
       and "locations = container.repo.locations()" in place_draft)
    ok("记账失败静默（那只是常用度统计，不该打断改单）", "catch (_: Exception) {" in place_draft)
    for name in ("applyPickedCoord", "pickAddressDraft", "pickLocationDraft", "pickPlaceDraft"):
        seg = kt_section(DETAIL_VM, name)
        ok(f"{name} 段找得到", bool(seg))
        ok(f"⛔ {name} 不碰收货人 / 下单人（改收货人是另一扇门 saveContactOnly）",
           not any(k in seg for k in CONTACT_KEYS))
    ok("共享库的五个管理动作与八句文案逐字（与下单页 / 地址页同一批话）",
       all(s in vm for s in MANAGE_LINES),
       "缺：" + " / ".join(s[:24] for s in MANAGE_LINES if s not in vm))
    for name in ("updatePlace", "deletePlace", "restorePlace", "demotePlace", "shareLocation"):
        seg = kt_section(DETAIL_VM, name)
        ok(f"{name} 段找得到", bool(seg))
        ok(f"{name} 的反馈走 actionResult（这一页不许出现弹窗式提示）", "actionResult = " in seg)
    ok("⛔ VM 里不许出现 Toast（判据 _check_detail_inline_edit.py:302 同一条纪律）", "Toast" not in vm)
    notice = region(vm, "override val addressCoordNotice: String?", "fun pickAddressDraft(")
    ok("「文字改了、坐标没动」那句话逐字（并点名两条出路）",
       '"地址文字改了，坐标还是原来那个点 —— 司机照坐标走，会开到老地方。"' in notice
       and '"要换地点就再选一次（地图选点 / 地址库 / 我就在这里）。"' in notice)
    ok("那句话只在改地址这一块、且坐标没变时才说（别的时候不吵）",
       "if (editingField != OrderEditField.ADDRESS) return null" in notice
       and "if (lat.isBlank() || lng.isBlank()) return null" in notice
       and "if (lat != o.addressLat.orEmpty() || lng != o.addressLng.orEmpty()) return null" in notice
       and "if (draft(OrderEditField.ADDRESS_DETAIL).trim() == o.addressDetail.trim()) return null" in notice)

    # ---- ④ 坐标真的落库（本刀的核心不变量） -------------------------------
    section("④ 坐标真的落库：铺草稿 → 取草稿 → fail-closed 闸 → 随这一单报上去")
    start = kt_section(DETAIL_VM, "startEdit")
    ok("改地址时坐标与文字**一起**铺草稿（坐标不是地址文字的附属品）",
       "editDrafts[OrderEditField.ADDRESS_LAT] = o.addressLat.orEmpty()" in start
       and "editDrafts[OrderEditField.ADDRESS_LNG] = o.addressLng.orEmpty()" in start)
    cancel = kt_section(DETAIL_VM, "cancelEdit")
    ok("取消＝什么都不留：两个弹层也一起收",
       "showAddressSheet = false" in cancel and "showAddressMap = false" in cancel)
    save = kt_section(DETAIL_VM, "saveEdit")
    ok("saveEdit 段找得到", bool(save))
    ok("坐标草稿像电话草稿一样先取出来（trim）",
       "val latDraft = draft(OrderEditField.ADDRESS_LAT).trim()" in save
       and "val lngDraft = draft(OrderEditField.ADDRESS_LNG).trim()" in save)
    gate = "if (!o.addressLat.isNullOrBlank() && (latDraft.isBlank() || lngDraft.isBlank())) {"
    ok("fail-closed：这一单本来带着坐标、草稿里却空了 ⇒ 当场拒存（不许悄悄丢掉司机照着走的那个点）",
       gate in save, "少了这道闸：界面说「改好了」，司机只能拿地址文字猜")
    ok("拒存的措辞给出两条出路（地图选点 / 地址库）",
       "地图选点" in region(save, gate, "if (editBusy) return") and "地址库" in save)
    i_gate = save.find(gate)
    i_req = save.find("container.repo.updateOrder(")
    ok("先校验、后请求（闸必须在发请求之前）", -1 < i_gate < i_req, f"闸={i_gate} 请求={i_req}")
    ok("两个坐标字段随这一单一起报（后端缺席语义＝不给就不改）",
       "addressLat = latDraft.ifBlank { null }," in save
       and "addressLng = lngDraft.ifBlank { null }," in save)
    args = region(save, "OrderUpdateRequest(", "internalNotes = o.internalNotes,")
    ok("两个坐标字段在 OrderUpdateRequest 的实参里（不是写去了别处）",
       "addressLat = latDraft.ifBlank { null }," in args
       and "addressLng = lngDraft.ifBlank { null }," in args)
    ok("内部备注仍原样带回（缺了它会不会被清掉取决于后端的缺席语义）",
       "internalNotes = o.internalNotes," in save)
    ok("DTO 两个坐标字段逐字（String?，不是 Double；与后端没动过的形状一致）",
       '@SerialName("address_lat") val addressLat: String? = null' in dto
       and '@SerialName("address_lng") val addressLng: String? = null' in dto)
    ok("后端仍是「不给就不改」（这一刀零后端改动）",
       "if body.address_lat is not None:" in cmd and "order.address_lat = body.address_lat" in cmd
       and "if body.address_lng is not None:" in cmd and "order.address_lng = body.address_lng" in cmd)
    ok("后端仍挡终态（已送达 / 已撤销 / 已退货的单改不了）",
       "elif order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED, OrderStatus.RETURNED):" in cmd)

    # ---- ⑤ 详情页的两个屏级宿主 -------------------------------------------
    section("⑤ 详情页：两个弹层挂在屏级，用的是共用件本体")
    body = flat(detail)
    ok("两个弹层各只有一处屏级宿主（4 空格缩进＝挂在这一页上，不在 LazyColumn 里）",
       body.count("    if (vm.showAddressSheet) {") == 1
       and body.count("    if (vm.showAddressMap) {") == 1,
       f"抽屉 {body.count('    if (vm.showAddressSheet) {')} 处 / 地图 {body.count('    if (vm.showAddressMap) {')} 处")
    ok("地点库抽屉是共用件本体（不新抄一份）", detail.count("AddressPickerSheet(") == 1)
    ok("地图弹层：导航那颗 + 改地址这颗，共两处（零件本体全库只有一份）",
       detail.count("AmapPickerDialog(") == 2, f"实际 {detail.count('AmapPickerDialog(')} 处")
    ok("抽屉标题是「改收货地址」（「选择收货地址」是下单页那一页的话）",
       'title = "改收货地址",' in detail and '"选择收货地址"' not in detail)
    sheet = region(detail, "    if (vm.showAddressSheet) {", "    if (vm.showAddressMap) {")
    amap = region(detail, "    if (vm.showAddressMap) {", "preview.Show()")
    ok("抽屉段 / 地图段都找得到", bool(sheet) and bool(amap))
    ok("抽屉拿到的是这一页的容器", "container = container," in sheet)
    ok("抽屉喂的是这一单的那六份数据（少一份＝那个分组永远空着）",
       all(s in sheet for s in ("addresses = vm.addresses,", "locations = vm.locations,",
                                "places = vm.places,", "categories = vm.placeCategories,",
                                "placesTruncated = vm.placesTruncated,", "placesLimit = vm.placesLimit,")))
    ok("三条挑选回调都落进这一单的草稿",
       "onPickAddress = { vm.pickAddressDraft(it) }," in sheet
       and "onPickLocation = { vm.pickLocationDraft(it) }," in sheet
       and "onPickPlace = { vm.pickPlaceDraft(it) }," in sheet)
    ok("搜索与分组改名后的重刷都接上了",
       "onSearchPlaces = { vm.loadPlaces(it) }," in sheet
       and "onCategoriesChanged = { vm.reloadAddressLibrary() }," in sheet)
    ok("共享库管理入口喂的是角色门（place:manage 货主也有，拿它当门＝货主也能改别人的地点）",
       "canManagePlaces = vm.canManageSharedPlaces," in sheet and "place:manage" not in detail)
    ok("管理五个回调都接上",
       all(s in sheet for s in ("onUpdatePlace = { id, name, addr -> vm.updatePlace(id, name, addr) },",
                                "onDeletePlace = { vm.deletePlace(it) },", "onDemotePlace = { vm.demotePlace(it) },",
                                "onRestorePlace = { vm.restorePlace(it) },", "onShareLocation = { vm.shareLocation(it) },")))
    ok("⛔ 不传 onAddLocation（这一页没有「新建地点」那条流）", "onAddLocation" not in sheet)
    ok("两个弹层的开关都只有 VM 一份（屏幕自己不藏状态）",
       "onDismiss = { vm.closeAddressSheet() }," in sheet
       and "onDismiss = { vm.closeAddressMap() }," in amap)
    ok("地图的初始位置取草稿里已有的坐标（改到一半再点开地图，不会跳回原点）",
       "initialLat = vm.draft(OrderEditField.ADDRESS_LAT).toDoubleOrNull()," in amap
       and "initialLng = vm.draft(OrderEditField.ADDRESS_LNG).toDoubleOrNull()," in amap)
    ok("地图选完直接落草稿（与「我就在这里」同一个回流）",
       "onPicked = { lat, lng, address -> vm.applyPickedCoord(lat, lng, address) }," in amap)
    ok("两个宿主都挂在 preview.Show() 之前（屏级位置）",
       detail.find("if (vm.showAddressSheet) {") < detail.find("preview.Show()")
       and detail.find("if (vm.showAddressMap) {") < detail.find("preview.Show()"))
    ok("这一页不许出现匿名 Dialog（图片预览那条红线的同一条纪律）",
       body.count("    Dialog(") == 0)

    # ---- ⑥ 与后端权限边界一致 ---------------------------------------------
    section("⑥ 与后端一致：共享库的写入口只有派单员（界面那颗管理入口对得上）")
    ok("四个写端点的门都是 DispatcherOnly",
       "DispatcherOnly = Annotated[User, Depends(require_roles(UserRole.DISPATCHER))]" in places
       and places.count("current: DispatcherOnly") == 4,
       f"实际 {places.count('current: DispatcherOnly')} 处")
    caps = kt(CAPS)
    ok("能力表里 place:manage 货主也有 ⇒ 它不是共享库管理那道门（界面用角色门是对的）",
       '"place:manage"' in caps, "这条断言是给下一个想把门放宽的人看的")
    ok("下单页那一边也是角色门（两页口径一致，不是这一页自创）",
       "canManageSharedPlaces" in kt(SHIPPER_VM), "照抄源就在那里")

    print("=" * 60)
    if C.fails:
        print(f"❌ {len(C.fails)} 项不通过（通过 {C.n_ok} 项）：")
        for label, _ in C.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {C.n_ok} 项通过：改地点走地点库 / 地图 / 「我就在这里」，这一单真的落坐标。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
