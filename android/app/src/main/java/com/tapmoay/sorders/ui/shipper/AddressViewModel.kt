package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.AddressCreateRequest
import com.tapmoay.sorders.data.remote.dto.AddressDto
import com.tapmoay.sorders.data.remote.dto.ContactCategoryDto
import com.tapmoay.sorders.data.remote.dto.ContactCreateRequest
import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.data.remote.dto.ContactUpdateRequest
import com.tapmoay.sorders.data.remote.dto.LocationCreateRequest
import com.tapmoay.sorders.data.remote.dto.LocationDto
import com.tapmoay.sorders.data.remote.dto.RouteCategoryDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.ContactFillMode
import com.tapmoay.sorders.ui.common.ReceiverContact
import com.tapmoay.sorders.ui.common.fillReceiver
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** 三个列表：常用线路（联系人+地点）/ 联系人 / 地点 */
/**
 * 「刚删掉的那一条」——软删之后允许**当场**撤回（规范 06:1371「删除一律软删 + 手边要有撤回」）。
 *
 * 只记一条是有意的：撤回的含义是「我手滑了」，隔了三条再撤就不是同一个动作了。
 * （同款做法见 `OrderCreateViewModel.recentlyDeletedPlace`。）
 *
 * [kind] 给代码用（[AddressViewModel.undoDelete] 按它挑还原接口），[label] 给人看。
 */
data class RecentlyDeleted(val kind: String, val label: String, val id: Long, val name: String)

/**
 * 三档删除各自叫什么（[AddressViewModel.askDelete] 认的三个 kind 与它们给人看的名字）。
 *
 * ⚠️ 必须与 [RecentlyDeleted.label] 是同一套说法 —— 两处不一致的话，确认弹层说「地点」、
 *    顶上那行撤销说「常用地点」，用户会以为删掉的不是同一样东西。
 */
private fun deleteKindLabel(kind: String): String? = when (kind) {
    "line" -> "常用线路"
    "place" -> "地点"
    "contact" -> "联系人"
    else -> null
}

/**
 * 二次确认的**标题**：点出要删的是**哪一条**。
 *
 * 用户 2026-10-04：「把地点线路联系人，他那里的删除键卡片删除键移到编辑界面当中，
 * 并且做二次确认的，**不要点一下就直接删掉了，防止误触**」。
 *
 * ⚠️ 名字取自**正在编辑的那份草稿**（同一次抽屉里刚改完名字，标题里就是刚敲的那个）；
 *    名字空着时退成「这条 X」，⛔ 不留一对空引号 —— 三张卡长得像的时候，
 *    用户就是靠这个名字确认"弹层上说的是不是我正要删的那一个"。
 * 纯函数，单测见 `AddressDeleteConfirmTest`。
 */
fun deleteConfirmTitle(what: String, name: String): String =
    if (name.isBlank()) "删除这条$what？" else "删除$what「$name」？"

/**
 * 二次确认的**正文**：说清"删完还能不能捞回来"。
 *
 * ⚠️ 这一句不许省：按下「删除」之前用户要知道两件事 —— ① 它是软删（还能恢复）；
 *    ② 恢复入口就在**这一页顶上**（不在这张弹层里）。少了第 ② 句，恢复入口等于不存在。
 * 纯函数，单测见 `AddressDeleteConfirmTest`。
 */
fun deleteConfirmMessage(what: String): String =
    "确认后它就从列表里消失，列表顶上会留一行「已删除$what」，点「撤销」可以恢复；" +
        "离开这一页就找不回来了。"

/** 等着二次确认的那一次删除：[kind] 给代码用（确认后据此挑哪个 delete*），[title] / [message] 直接画给用户看。 */
data class PendingDelete(val kind: String, val title: String, val message: String)

class AddressViewModel(private val container: AppContainer) : ViewModel() {

    var addresses by mutableStateOf<List<AddressDto>>(emptyList())
    var contacts by mutableStateOf<List<ContactDto>>(emptyList())
    var locations by mutableStateOf<List<LocationDto>>(emptyList())
    var loading by mutableStateOf(false)
    /**
     * **页面级**加载失败 —— 只有 [load] 会写它；界面用它把整页换成「一句话 + 重试」。
     *
     * ⛔ **表单的错误不许写这里**（2026-09-19 真机缺陷，用户原话：「我新建了一个地点…
     *    直接点击保存，然后再返回去的时候，它那个地点库的所有列表**全消失了**，
     *    需要重新连接」）。原因就是这个状态原来只有**一个** `error`，三个抽屉的校验失败和
     *    保存失败全往里写，而 `ErrorView` 是**整页**的，于是「新增地点只填了名字就点保存」：
     *    ① 抽屉里一个字都不显示（那句话画在抽屉背后）；
     *    ② 关掉抽屉以后整页变成「请填写地点地址 + 重试」，**三个列表全没了** ——
     *    用户只能理解成"断线了"，而地点一条都没丢。
     */
    var loadError by mutableStateOf<String?>(null)
    /**
     * **表单**里的一句话错误：画在**对应的那个抽屉内部**（新增/编辑线路、联系人、地点、
     * 新建分组四处的任一处）——同一时刻只会开着一个抽屉，所以共用一个状态。
     *
     * 判据很简单：**这句话是给"正在填表的人"看的**，它必须和表单同生共死；抽屉一关，
     * 它就不该再影响任何东西（打开表单时由 `open*` 清掉，见各自的 `formError = null`）。
     */
    var formError by mutableStateOf<String?>(null)
    /**
     * 一次性提示：行上的「删除 / 设为默认」这类**点了就发生、没有表单可挂**的动作，
     * 失败时用它 —— 界面按全 App 的做法用 Snackbar 显示，显示完置回 null。
     */
    var notice by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    /**
     * 刚删掉的那一条（三档列表共用：线路 / 地点 / 联系人）。
     *
     * ⛔ 删完**不能只留一句「已删除」就完了**：恢复入口在别处根本找不到，
     *    所以每次删除都把它记在这里，界面在列表顶上给一行「已删除 X + 撤销」。
     *
     * ⚠️ 2026-10-04（CHG-0032）：删除**已经不是"点一下就发生"**了 —— 卡片上那颗红图标
     *    搬进了各自的编辑抽屉，而且要过 [pendingDelete] 那层二次确认。这一行「撤销」仍是
     *    第二道兜底：确认过不等于想清楚了，软删之后当场还能捞回来（规范 06:1371）。
     */
    var recentlyDeleted by mutableStateOf<RecentlyDeleted?>(null)

    /**
     * 等着用户点「删除」的那一次（用户 2026-10-04：「删除都要做二次确认的，不要点一下就直接
     * 删掉了，防止误触」）。
     *
     * 为什么放在 VM 而不是界面里 `remember` 一个：标题要写**是哪一条**（名字取自正在编辑的
     * 那份草稿），而"正在编辑哪一条"只有 VM 知道；更要紧的是它必须与抽屉**共用一个真相** ——
     * 删成功 / 关抽屉时这个状态一起清掉，否则会出现"确认弹层还开着，那条已经被删了"。
     */
    var pendingDelete by mutableStateOf<PendingDelete?>(null)

    /** 撤回刚删的那一条（软删 → 还原，走仓库里本来就有的 restore* 接口）。 */
    fun undoDelete() {
        val rd = recentlyDeleted ?: return
        if (acting) return
        acting = true
        viewModelScope.launch {
            try {
                when (rd.kind) {
                    "line" -> container.repo.restoreAddress(rd.id)
                    "place" -> container.repo.restoreLocation(rd.id)
                    "contact" -> container.repo.restoreContact(rd.id)
                }
                recentlyDeleted = null
                load()
            } catch (e: Exception) {
                notice = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /**
     * 举手要删（**不落库**）：抽屉里那颗「删除」只调它。
     *
     * ⛔ 别让界面直接调 [delete] / [deleteContact] / [deleteLocation] —— 那三个是**执行**，
     *    中间少了二次确认就回到"点一下就没了"（用户 2026-10-04 点名要挡的就是这个）。
     */
    fun askDelete(kind: String) {
        val what = deleteKindLabel(kind) ?: return
        val name = when (kind) {
            "line" -> editing?.receiverName
            "place" -> editingLocation?.name
            else -> editingContact?.displayName
        }.orEmpty()
        pendingDelete = PendingDelete(kind, deleteConfirmTitle(what, name), deleteConfirmMessage(what))
    }

    /** 二次确认里点「取消」：什么都不发生（当然也不落库）。 */
    fun cancelDelete() {
        pendingDelete = null
    }

    /**
     * 二次确认里点「删除」：**唯一**会走到那三个 delete* 的地方。
     *
     * 顺手把抽屉一起关掉 —— 编辑的那条已经不在了，抽屉再开着就是"在编辑一个刚删掉的东西"。
     */
    fun confirmDelete() {
        val p = pendingDelete ?: return
        pendingDelete = null
        when (p.kind) {
            "line" -> editing?.let { showCreateDialog = false; delete(it) }
            "place" -> editingLocation?.let { showLocationDialog = false; deleteLocation(it) }
            "contact" -> editingContact?.let { showContactDialog = false; deleteContact(it) }
        }
    }

    // 常用线路（联系人+地点）编辑弹窗状态
    var editing by mutableStateOf<AddressDto?>(null)
    var showCreateDialog by mutableStateOf(false)
    var showMapPicker by mutableStateOf(false)
    var mapTarget by mutableStateOf("dest") // dest=终点 origin=起点 loc=地点
    var showContactDialog by mutableStateOf(false)
    var editingContact by mutableStateOf<ContactDto?>(null)

    // 线路表单草稿
    var draftName by mutableStateOf("")
    var draftPhone by mutableStateOf("")
    var draftContactId by mutableStateOf<Long?>(null)
    var draftDetail by mutableStateOf("")          // 终点（必填）
    var draftLat by mutableStateOf<String?>(null)
    var draftLng by mutableStateOf<String?>(null)
    var draftOrigin by mutableStateOf("")          // 起点（可选）
    var draftOriginLat by mutableStateOf<String?>(null)
    var draftOriginLng by mutableStateOf<String?>(null)
    var draftRemark by mutableStateOf("")
    var draftIsDefault by mutableStateOf(false)
    var draftImageUrls by mutableStateOf<List<String>>(emptyList())
    var draftImageUploading by mutableStateOf(false)

    // 地点（单独地点）表单状态
    var editingLocation by mutableStateOf<LocationDto?>(null)
    var showLocationDialog by mutableStateOf(false)
    var locName by mutableStateOf("")
    var locDetail by mutableStateOf("")
    var locLat by mutableStateOf<String?>(null)
    var locLng by mutableStateOf<String?>(null)
    var locRemark by mutableStateOf("")
    var locImageUrls by mutableStateOf<List<String>>(emptyList())

    /** 这个地点属于哪个分组（空 = 未分类）；表单里可以现敲一个新的（后端会自动补进名册）。 */
    var locCategory by mutableStateOf("")

    /** 地点分组名册（**自己那一份**）：表单里那排候选胶囊。 */
    var placeCategories by mutableStateOf<List<com.tapmoay.sorders.data.remote.dto.PlaceCategoryDto>>(emptyList())

    /**
     * 共享地点库（**全库共用**的一张表，2026-10-06 / 台账 L-09）：起点/终点那个地点库抽屉的
     * 第三段就是它。后端这套接口早就有（下单页一直在用），这一页原来只是**没接上**。
     */
    var places by mutableStateOf<List<com.tapmoay.sorders.data.remote.dto.PlaceDto>>(emptyList())

    /** 共享地点这一页被服务端截断了没有 + 本次上限（判据是响应头 `X-Truncated`/`X-Result-Limit`）。 */
    var placesTruncated by mutableStateOf(false)
    var placesLimit by mutableStateOf<Int?>(null)

    /**
     * 刚删掉的那条共享地点（编号 + 名字）：抽屉拿它在列表顶上画一行「已删除 · 撤销」。
     *
     * 为什么要有它：删除是**软删**（用户 2026-09-19 定的规矩），"能恢复"这件事必须在手边
     * 有个入口 —— 撤回卡只在 AI 那条路上有，人点的那一下也得能撤回来。
     */
    var recentlyDeletedPlace by mutableStateOf<Pair<Long, String>?>(null)

    /** 这个联系人归到哪个分类（空 = 未分类）；表单里可以现敲一个新的（后端会自动补进名册）。 */
    var contactCategory by mutableStateOf("")

    /** 联系人分类名册（**自己那一份**）：联系人段的分类抽屉与表单里的候选用它。 */
    var contactCategories by mutableStateOf<List<ContactCategoryDto>>(emptyList())

    /** 这条线路归到哪个分类（空 = 未分类）；表单里从名册里选一个。 */
    var routeCategory by mutableStateOf("")

    /** 线路分类名册（**自己那一份**）：线路段的分类抽屉与表单里的候选用它。 */
    var routeCategories by mutableStateOf<List<RouteCategoryDto>>(emptyList())

    /**
     * 三个页签「按分类看」抽屉里各自选中的那一格：
     * `""` = 全部 / `"c|分类名"` = 某一类（FEAT-0007 起用）；`"manage"` 留给抽屉末尾那行动作。
     *
     * ⚠️ 三个页签**共用同一个 key 约定**（零件 `ui/common/CategoryDrawer.kt` 只认这一套）：
     *    路线 [routeRailKey] / 联系人 [contactRailKey] / 地点 [locRailKey]。
     *    `"manage"` 不是一格数据 —— 点了就把这一页的内容换成管理面板（见 `AddressScreen.kt`）。
     */
    var routeRailKey by mutableStateOf("")
    var contactRailKey by mutableStateOf("")
    var locRailKey by mutableStateOf("")

    /** 这个地点是不是仓库（**只有派单员**能改，见后端 `api/v1/shipper.py`）。 */
    var locIsWarehouse by mutableStateOf(false)

    /**
     * 地点表单里**绑定的联系人**（用户 2026-09-24：「可以通过地点来绑定联系人，
     * 就大家选择地点之后，自动填入对应的联系人」）。
     *
     * ⚠️ 与线路的 `draftName`/`draftPhone` **同一口径：存快照串、不存联系人 id**
     * （后端 `shipper_locations.contact_name/contact_phone` 也是两个串）。
     * ⛔ 只有「我的地点」能绑人，**共享地点库（`places`）不能** —— 那张表全库共用。
     */
    var locContactName by mutableStateOf("")
    var locContactPhone by mutableStateOf("")

    /**
     * 「选择联系人」弹层正在给谁挑：`"line"` = 线路表单的收货人；`"loc"` = 地点表单绑定的联系人。
     * null = 没开。**一份实现两处消费**（同一个弹层、同一条回填判据）。
     */
    var contactPickTarget by mutableStateOf<String?>(null)

    /** 弹层里那次「新建联系人」的失败原因 / 在飞标记（与表单的 `formError` 分开：它不在抽屉里）。 */
    var pickerError by mutableStateOf<String?>(null)
    var creatingContact by mutableStateOf(false)

    /** 当前登录人能不能标仓库 —— 货主看不到那个开关（后端也会拦，这里只是不给他点一个必然报错的东西）。 */
    var canMarkWarehouse by mutableStateOf(false)

    /** 当前登录人能不能管共享地点库（改名称/撤销/删除都只对派单员开放，后端也会拦）。 */
    var canManageSharedPlaces by mutableStateOf(false)
    var locImageUploading by mutableStateOf(false)
    var pendingSlot by mutableStateOf<String?>(null)   // 行内新增地点回填槽位 start/end
    var lineContactCtx by mutableStateOf(false)        // 从线路抽屉打开的联系人抽屉

    init {
        load()
    }

    fun load() {
        loading = addresses.isEmpty()
        loadError = null
        viewModelScope.launch {
            // 三条列表**各自独立**地拉。原来是一个 try 串下来：**任何一个失败**，
            // 整页就变成「一句话 + 重试」，另外两条明明拿得到的数据也一起看不见了 ——
            // 用户的原话就是「所有列表全消失了」。
            // 这个仓真出过"一行脏数据把某个列表接口打成 500"（见各 schemas 里那些把 None
            // 归一成 [] 的注释），而三条列表在同一屏上，所以这个形状值得挡住。
            val failed = mutableListOf<String>()
            fun boom(e: Exception, what: String): Boolean {
                failed += (toApiException(e).message ?: "$what 加载失败")
                return false
            }
            val okAddresses = try { addresses = container.repo.addresses(); true } catch (e: Exception) { boom(e, "线路") }
            val okContacts = try { contacts = container.repo.contacts(); true } catch (e: Exception) { boom(e, "联系人") }
            val okLocations = try { locations = container.repo.locations(); true } catch (e: Exception) { boom(e, "地点") }
            // 分组名册是**表单里才用到**的边角数据：它挂了不该影响这一页能不能看
            try { placeCategories = container.repo.placeCategories() } catch (_: Exception) {}
            try { contactCategories = container.repo.contactCategories() } catch (_: Exception) {}
            try { routeCategories = container.repo.routeCategories() } catch (_: Exception) {}
            // 共享地点库也顺手拉一份（2026-10-06，CHG-0047）：抽屉一打开第三段就该有内容，
            // 不然会先闪一句"共享地点库还是空的"再自己填上。
            loadPlaces()
            // 三条**全挂**才认定"这一页没加载出来"（整页给「重试」）；
            // 只挂了一部分就照常显示，缺的那条用 Snackbar 说一句 —— 别把好的也收走。
            if (!okAddresses && !okContacts && !okLocations) loadError = failed.firstOrNull() ?: "加载失败"
            else if (failed.isNotEmpty()) notice = failed.first()
            loading = false
        }
        viewModelScope.launch {
            try {
                // 读一次会话按两处用：仓库标记与共享库管理权判的是**同一个角色**，
                // 分两个协程各读一次是白花一次请求（2026-10-06，CHG-0047）。
                val isDispatcher = container.tokenStore.sessionFlow.first()?.role == "dispatcher"
                canMarkWarehouse = isDispatcher
                canManageSharedPlaces = isDispatcher
            } catch (_: Exception) {
            }
        }
    }

    // ===== 常用线路（联系人+地点）=====

    fun openCreate() {
        editing = null
        draftName = ""; draftPhone = ""; draftDetail = ""; draftRemark = ""
        draftLat = null; draftLng = null
        draftOrigin = ""; draftOriginLat = null; draftOriginLng = null
        draftIsDefault = false
        draftImageUrls = emptyList(); draftImageUploading = false
        draftContactId = null
        routeCategory = ""
        formError = null
        showCreateDialog = true
    }

    fun openEdit(a: AddressDto) {
        editing = a
        draftName = a.receiverName
        draftPhone = a.phone
        draftDetail = a.detailAddress
        draftRemark = a.remark
        draftLat = a.addressLat
        draftLng = a.addressLng
        draftOrigin = a.originAddress.orEmpty()
        draftOriginLat = a.originLat
        draftOriginLng = a.originLng
        draftIsDefault = a.isDefault
        draftImageUrls = a.imageUrls.ifEmpty { listOfNotNull(a.imageUrl) }; draftImageUploading = false
        draftContactId = null
        // 分类**必须回填**：线路保存走"整份回传"，不回填就把分类静默清掉了。
        routeCategory = a.category
        formError = null
        showCreateDialog = true
    }

    /** 线路表单选择联系人（快照姓名+电话，换人重选即可） */
    fun selectContact(c: ContactDto) {
        draftContactId = c.id
        // 回填判据只有一份（`ui/common/ContactFill.kt::fillReceiver`）：
        // 挑了一个人 = **整对替换**（只换一半会拼出一个不存在的人）。
        val f = fillReceiver(ReceiverContact(draftName, draftPhone), c.displayName, c.phone, ContactFillMode.PICKED)
        draftName = f.name
        draftPhone = f.phone
        pickerError = null
    }

    /**
     * 打开「选择联系人」弹层，[target] 决定挑完填哪一份（见 [contactPickTarget]）。
     *
     * ⚠️ 先刷一遍名册：用户可能刚在「联系人」那一段加过人，而这里是另一个抽屉。
     */
    fun openContactPickerFor(target: String) {
        contactPickTarget = target
        pickerError = null
        viewModelScope.launch { try { contacts = container.repo.contacts() } catch (_: Exception) {} }
    }

    /** 弹层里挑了一位 → 按 [contactPickTarget] 落到对应那一份草稿上，然后关掉弹层。 */
    fun applyPickedContact(c: ContactDto) {
        when (contactPickTarget) {
            "loc" -> {
                val f = fillReceiver(
                    ReceiverContact(locContactName, locContactPhone),
                    c.displayName,
                    c.phone,
                    ContactFillMode.PICKED,
                )
                locContactName = f.name
                locContactPhone = f.phone
                // L-10：选联系人时把他档案上的**备注**带进地点备注 —— ⛔ 只在地点备注还空着时填：
                // 用户自己写过的那一行是他的，不能被联系人档案上的字盖掉（这与 fillReceiver 的
                // 「有值才覆盖」是**两条不同的纪律**，别混）。
                if (locRemark.isBlank() && c.remark.isNotBlank()) locRemark = c.remark
            }
            else -> selectContact(c)
        }
        contactPickTarget = null
    }

    /**
     * 弹层里**就地新建**一个联系人 → 存完直接用上（不跳回「联系人」那一段重来一遍）。
     *
     * 与 [saveContact] 是同一条电话规则（`core/InputRules.kt::phoneError`）+ 同一个后端端点；
     * 分开一个入口只是因为**落点不同**：那个落进联系人列表，这个落进当前正在填的那份草稿。
     *
     * CHG-0010：电话**选填**（后端 `ContactCreate.phone` 已有默认值），但姓名与电话
     * **至少填一个** —— 两个都空存下来是一条谁也认不出的记录。
     */
    fun createContactAndPick(name: String, phone: String) {
        val p = phone.trim()
        InputRules.phoneError(p, required = false)?.let {
            pickerError = it
            return
        }
        InputRules.contactIdentityError(name, p)?.let {
            pickerError = it
            return
        }
        if (creatingContact) return
        creatingContact = true
        pickerError = null
        viewModelScope.launch {
            try {
                val created = container.repo.createContact(ContactCreateRequest(phone = p, displayName = name.trim()))
                contacts = container.repo.contacts()
                applyPickedContact(created)
                load()
            } catch (e: Exception) {
                // 同号已存在（后端 409）：用户要的是"用这个人"，不是"再建一条"。
                // ⚠️ 只有**真填了号码**才按号码兜底：`p` 是空串时会把一堆"没填号码"的
                //    联系人全都匹配上，随手指一个比老老实实报错更糟（CHG-0010）。
                val existing = if (p.isEmpty()) null else contacts.firstOrNull { it.phone.trim() == p }
                if (existing != null) {
                    applyPickedContact(existing)
                } else {
                    pickerError = toApiException(e).message ?: "联系人没存上，请重试"
                }
            } finally {
                creatingContact = false
            }
        }
    }

    fun openPicker(target: String) {
        mapTarget = target
        showMapPicker = true
    }

    /** 从地点库选择起点（地点已有图片 → 自动带图） */
    fun selectOriginLocation(l: LocationDto) {
        draftOrigin = l.detailAddress
        draftOriginLat = l.addressLat
        draftOriginLng = l.addressLng
        // 地点有图 → 线路图片自动带图（多张全带）
        if (l.imageUrls.isNotEmpty() || !l.imageUrl.isNullOrBlank()) {
            draftImageUrls = l.imageUrls.ifEmpty { listOfNotNull(l.imageUrl) }
        }
    }

    /** 从地点库选择终点（地点已有图片 → 自动带图） */
    fun selectDestLocation(l: LocationDto) {
        draftDetail = l.detailAddress
        draftLat = l.addressLat
        draftLng = l.addressLng
        // 这个地点**绑了联系人** → 顺带把线路的收货人带出来（用户 2026-09-24：
        // 「可以通过地点来绑定联系人」）。**有值才覆盖**：没绑人的地点不许把已经选好的联系人清掉。
        val f = fillReceiver(ReceiverContact(draftName, draftPhone), l.contactName, l.contactPhone, ContactFillMode.BROUGHT)
        draftName = f.name
        draftPhone = f.phone
        // 地点有图 → 线路图片自动带图（多张全带）
        if (l.imageUrls.isNotEmpty() || !l.imageUrl.isNullOrBlank()) {
            draftImageUrls = l.imageUrls.ifEmpty { listOfNotNull(l.imageUrl) }
        }
    }

    /**
     * 从**线路**里挑一条回填（2026-10-06，CHG-0047 / 台账 L-09）：[asOrigin] 决定填起点还是终点。
     *
     * ⚠️ 起点那一侧有个真会发生的坑：线路的起点是**可选**的（`originAddress` 可能是空的 ——
     * 那条线路本身就是"只送到终点"）。这种线路**什么都不填**并把理由说出来，
     * ⛔ 绝不拿它的终点当地起点：那是"悄悄改了用户要去的地方"。
     */
    fun applyPickedRoute(a: AddressDto, asOrigin: Boolean) {
        if (asOrigin) {
            val addr = a.originAddress.orEmpty().trim()
            if (addr.isEmpty()) {
                formError = "这条线路没写起点（只送到终点），改选一个地点，或先编辑这条线路补上起点"
                return
            }
            draftOrigin = addr
            draftOriginLat = a.originLat
            draftOriginLng = a.originLng
            return
        }
        draftDetail = a.detailAddress
        draftLat = a.addressLat
        draftLng = a.addressLng
        // 线路上的收货人两栏是**快照**：照 [selectDestLocation] 的规矩"有值才覆盖" ——
        // 没写收货人的线路不许把用户刚敲好的名字/电话清掉。
        val f = fillReceiver(
            ReceiverContact(draftName, draftPhone),
            a.receiverName,
            a.phone,
            ContactFillMode.BROUGHT,
        )
        draftName = f.name
        draftPhone = f.phone
    }

    /**
     * 从**共享地点库**挑一条回填（2026-10-06，CHG-0047 / 台账 L-09）。
     *
     * ⛔ 共享地点**不带联系人**（也不许带）：`places` 是**全库共用**的一张表 —— 司机补录
     * 的坐标所有人都会选到，往它上面绑一个人的电话等于给所有人换了默认收货人。
     * 那张表根本没有这两个字段，绑定只存在于「我的地点」（`shipper_locations`）。
     */
    fun applyPickedPlace(p: com.tapmoay.sorders.data.remote.dto.PlaceDto, asOrigin: Boolean) {
        val addr = p.detailAddress.ifBlank { p.name }
        if (asOrigin) {
            draftOrigin = addr
            draftOriginLat = p.addressLat
            draftOriginLng = p.addressLng
        } else {
            draftDetail = addr
            draftLat = p.addressLat
            draftLng = p.addressLng
        }
        // 记一次"我用了它"。**同一个人用到第 2 次**时后端会自动把它收进我的地点库，
        // 那时要在界面上说一句 —— 静默改了用户自己的库，他下次看到多出一条来源不明的
        // 记录只能猜。界面语言：说清"发生了什么"，不说"操作成功"。
        viewModelScope.launch {
            try {
                val r = container.repo.usePlace(p.id)
                if (r.autoAdded) {
                    notice = "「${p.name.ifBlank { p.detailAddress }}」你用过几次了，已加进你的「我的地点」"
                    locations = container.repo.locations()
                }
            } catch (_: Exception) {
                // 记账失败不该打断"新建/编辑线路"：它只是"常用地点"的统计，不是必要步骤
            }
        }
    }

    /** 上传线路图片 */
    fun uploadLineImage(file: java.io.File) {
        viewModelScope.launch {
            try {
                draftImageUploading = true
                val url = container.repo.uploadLocationImage(file).url
                draftImageUrls = draftImageUrls + url
            } catch (e: Exception) {
                formError = toApiException(e).message
            } finally {
                draftImageUploading = false
            }
        }
    }

    fun applyPicked(lat: Double, lng: Double, address: String) {
        when (mapTarget) {
            "origin" -> {
                draftOriginLat = lat.toString()
                draftOriginLng = lng.toString()
                draftOrigin = address
            }
            "loc" -> {
                locLat = lat.toString()
                locLng = lng.toString()
                locDetail = address
            }
            else -> {
                draftLat = lat.toString()
                draftLng = lng.toString()
                draftDetail = address
            }
        }
        showMapPicker = false
    }

    fun save() {
        if (draftContactId == null && draftName.isBlank()) {
            formError = "请选择联系人"
            return
        }
        if (draftDetail.isBlank()) {
            formError = "请填写收货地址（终点）"
            return
        }
        acting = true
        formError = null
        viewModelScope.launch {
            try {
                val body = AddressCreateRequest(
                    receiverName = draftName.trim(),
                    phone = draftPhone.trim(),
                    detailAddress = draftDetail.trim(),
                    remark = draftRemark.trim(),
                    addressLat = draftLat,
                    addressLng = draftLng,
                    originAddress = draftOrigin.trim().ifBlank { null },
                    originLat = draftOriginLat,
                    originLng = draftOriginLng,
                    isDefault = draftIsDefault,
                    category = routeCategory.trim(),
                    imageUrls = draftImageUrls,
                )
                val cur = editing
                if (cur == null) {
                    container.repo.createAddress(body)
                } else {
                    container.repo.updateAddress(cur.id, body)
                }
                showCreateDialog = false
                load()
            } catch (e: Exception) {
                formError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun delete(a: AddressDto) {
        viewModelScope.launch {
            try {
                container.repo.deleteAddress(a.id)
                recentlyDeleted = RecentlyDeleted(
                    kind = "line", label = "常用线路", id = a.id, name = a.receiverName,
                )
                load()
            } catch (e: Exception) {
                notice = toApiException(e).message
            }
        }
    }

    fun setDefault(a: AddressDto) {
        viewModelScope.launch {
            try {
                container.repo.setDefaultAddress(a.id)
                load()
            } catch (e: Exception) {
                notice = toApiException(e).message
            }
        }
    }

    // ===== 联系人 =====

    var contactName by mutableStateOf("")
    var contactPhone by mutableStateOf("")

    /**
     * 联系人备注（L-10，用户 2026-10-06：「联系人他也是要有备注的」）。
     *
     * "" = 没写。**只有自己看得见** —— 服务端只把它回给联系人自己的主人；
     * 选这位联系人时它会被带进**地点备注**（那一格随后归用户自己改）。
     */
    var contactRemark by mutableStateOf("")

    fun openContactDialog(c: ContactDto? = null, fromLine: Boolean = false) {
        lineContactCtx = fromLine
        editingContact = c
        contactName = c?.displayName ?: ""
        contactPhone = c?.phone ?: ""
        // 分类**必须回填**：保存走的是"整份回传"（同一个请求体用于新建与编辑），
        // 不回填就等于"改个称呼顺手把分类清掉了"。
        contactCategory = c?.category ?: ""
        // 备注同理**必须回填**：保存走的是「整份回传」（新建与编辑共用同一个请求体），
        // 不回填就等于「改个称呼顺手把备注清掉了」。
        contactRemark = c?.remark ?: ""
        formError = null
        showContactDialog = true
    }

    fun saveContact() {
        // 口径与后端一致（`ContactCreate.phone` / `ContactUpdate.phone` 也走同一条电话规则）：
        // 只数字、7~12 位。原来是"长度 ≥5 就算过" —— 于是 `222`、`12345` 这种打不通的号
        // 也能进库（生产库里真有一条 `222`）。规则唯一实现在 core/InputRules.kt。
        // CHG-0010：电话**选填**，改成姓名与电话**至少填一个**（与后端那句 400 一字不差）。
        InputRules.phoneError(contactPhone.trim(), required = false)?.let {
            formError = it
            return
        }
        InputRules.contactIdentityError(contactName, contactPhone)?.let {
            formError = it
            return
        }
        viewModelScope.launch {
            try {
                val cur = editingContact
                if (cur == null) {
                    val created = container.repo.createContact(
                        ContactCreateRequest(
                            phone = contactPhone.trim(),
                            displayName = contactName.trim(),
                            category = contactCategory.trim(),
                            remark = contactRemark.trim(),
                        )
                    )
                    if (lineContactCtx) {
                        selectContact(created)
                        lineContactCtx = false
                    }
                } else {
                    container.repo.updateContact(
                        cur.id,
                        ContactUpdateRequest(
                            phone = contactPhone.trim(),
                            displayName = contactName.trim(),
                            category = contactCategory.trim(),
                            remark = contactRemark.trim(),
                        )
                    )
                }
                contactName = ""
                contactPhone = ""
                showContactDialog = false
                load()
            } catch (e: Exception) {
                formError = toApiException(e).message
            }
        }
    }

    fun deleteContact(c: ContactDto) {
        viewModelScope.launch {
            try {
                container.repo.deleteContact(c.id)
                recentlyDeleted = RecentlyDeleted(
                    kind = "contact", label = "联系人", id = c.id, name = c.displayName,
                )
                load()
            } catch (e: Exception) {
                notice = toApiException(e).message
            }
        }
    }

    /**
     * 就地新建一个联系人分类并**选中它**（联系人表单的分类下拉里那个「＋ 新建分类…」）。
     *
     * 与地点的 [createPlaceCategoryAndSelect] 逐条同构，连"重名直接选中已有的那个"的理由都一样：
     * 用户要的是"归到这个名字"，不是"再建一个"。
     */
    fun createContactCategoryAndSelect(rawName: String, onDone: () -> Unit) {
        val name = rawName.trim().take(8)
        if (name.isBlank()) {
            formError = "分类名不能为空"
            return
        }
        acting = true
        formError = null
        viewModelScope.launch {
            try {
                try {
                    container.repo.createContactCategory(name)
                } catch (e: Exception) {
                    val msg = toApiException(e).message.orEmpty()
                    if (!msg.contains("已经存在")) throw e
                }
                contactCategories = container.repo.contactCategories()
                contactCategory = name
                onDone()
            } catch (e: Exception) {
                formError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /**
     * 分类管理面板关掉后重新取名册 —— 用户可能在面板里改名 / 删掉一整类，
     * 左栏那一格得跟着变（否则右栏按老名字筛，看起来像"这一类是空的"）。
     */
    fun reloadContactCategories() {
        viewModelScope.launch {
            try { contactCategories = container.repo.contactCategories() } catch (_: Exception) {}
            // 选中的那一类被删掉/改名了 → 落回「全部」，别把用户留在一个筛不出东西的格子上。
            if (contactRailKey.startsWith("c|") &&
                contactCategories.none { "c|" + it.name == contactRailKey }
            ) contactRailKey = ""
        }
    }

    /** 线路段分类抽屉 / 表单的同一件事（理由见 [reloadContactCategories]）。 */
    fun reloadRouteCategories() {
        viewModelScope.launch {
            try { routeCategories = container.repo.routeCategories() } catch (_: Exception) {}
            if (routeRailKey.startsWith("c|") &&
                routeCategories.none { "c|" + it.name == routeRailKey }
            ) routeRailKey = ""
        }
    }

    /** 地点段分类抽屉 / 表单的同一件事（理由见 [reloadContactCategories]）。 */
    fun reloadPlaceCategories() {
        viewModelScope.launch {
            try { placeCategories = container.repo.placeCategories() } catch (_: Exception) {}
            if (locRailKey.startsWith("c|") &&
                placeCategories.none { "c|" + it.name == locRailKey }
            ) locRailKey = ""
        }
    }

    /**
     * 地址库抽屉每次打开都刷一遍**抽屉里显示的那三份**：分组名册 / 线路 / 我的地点。
     * （分组名册是"自己那一份"：货主和派单员各管各的，互相看不到。）
     *
     * 为什么是"三份一起"：抽屉左栏是分组名册、右栏是线路/地点。只刷名册的话，点进那个
     * 刚改名的分组会显示「这个分组下还没有地点」（按新名字一条都筛不到），而数据其实一条没少。
     */
    fun reloadAddressLibrary() {
        viewModelScope.launch { try { placeCategories = container.repo.placeCategories() } catch (_: Exception) {} }
        viewModelScope.launch { try { addresses = container.repo.addresses() } catch (_: Exception) {} }
        viewModelScope.launch { try { locations = container.repo.locations() } catch (_: Exception) {} }
    }

    /** 共享地点库（全库共用）。搜索时由界面调 `loadPlaces(q)`。 */
    fun loadPlaces(q: String? = null) {
        viewModelScope.launch {
            try {
                val page = container.repo.placesPage(q)
                places = page.rows
                placesTruncated = page.meta.hasMore
                placesLimit = page.meta.limit
            } catch (_: Exception) {}
        }
    }

    // ===== 共享库的管理（**只有派单员**，用户 2026-09-19）=====
    //
    // 用户原话：「共享地址的编辑只有派单员可以编辑，其他人都编辑不了。派单员可以改名称，
    // 也可以把一些地点给设置为共享地址，也可以撤销某些共享地址，把它降为普通的地址，
    // 或者直接删掉」。
    //
    // 四个动作都在这里**如实回报**（[notice]），而且**改完立刻重拉两份列表**：
    // 撤销会同时改「共享地点」（少一条）和「我的地点」（多一条），只刷一份的话
    // 抽屉里会出现"刚撤销的地点还在共享库里"这种假象。

    /** 改共享地点的名称/地址。 */
    fun updatePlace(id: Long, name: String?, address: String?) {
        if (name == null && address == null) {
            notice = "没有要改的内容"
            return
        }
        viewModelScope.launch {
            try {
                container.repo.updatePlace(
                    id,
                    com.tapmoay.sorders.data.remote.dto.PlaceUpdateRequest(name = name, detailAddress = address),
                )
                notice = "已改共享地点"
                loadPlaces()
            } catch (e: Exception) {
                notice = toApiException(e).message
            }
        }
    }

    /** 从共享库**删掉**一个地点（软删 → 界面立刻给一次「撤销」的机会）。 */
    fun deletePlace(id: Long) {
        viewModelScope.launch {
            try {
                container.repo.deletePlace(id)
                recentlyDeletedPlace = id to (places.firstOrNull { it.id == id }?.name.orEmpty())
                notice = "已从共享地点库删除（别人的选点列表里也没有它了；删错了可以点「撤销」）"
                loadPlaces()
            } catch (e: Exception) {
                notice = toApiException(e).message
            }
        }
    }

    /** 把刚删掉的那条共享地点放回来（回收站里那一条）。 */
    fun restorePlace(id: Long) {
        viewModelScope.launch {
            try {
                container.repo.restorePlace(id)
                recentlyDeletedPlace = null
                notice = "已恢复这条共享地点"
                loadPlaces()
            } catch (e: Exception) {
                notice = toApiException(e).message
            }
        }
    }

    /** **撤销**共享地址 → 降为**自己**的普通地点。 */
    fun demotePlace(id: Long) {
        viewModelScope.launch {
            try {
                val r = container.repo.demotePlace(id)
                notice = if (r.created) "已撤销，并存进了你的「我的地点」"
                else "已撤销（你本来就有这个地点，没有重复加）"
                locations = container.repo.locations()
                loadPlaces()
            } catch (e: Exception) {
                notice = toApiException(e).message
            }
        }
    }

    /** 把「我的地点」里的一个地点**设为共享地址**。 */
    fun shareLocation(l: LocationDto) {
        viewModelScope.launch {
            try {
                val p = container.repo.shareLocation(l.id)
                // 如实说明"新建"还是"并入"：用户以为库里多了一条、而列表没变，是最容易困惑的地方
                notice = if (p.merged) "已并入共享地点库里的「${p.name}」（坐标相近，没有重复建）"
                else "已设为共享地址，以后大家都能直接选它"
                loadPlaces()
            } catch (e: Exception) {
                notice = toApiException(e).message
            }
        }
    }

    /**
     * 就地新建一个线路分类并**选中它**（线路表单的分类下拉里那个「＋ 新建分类…」）。
     *
     * 与 [createContactCategoryAndSelect] / [createPlaceCategoryAndSelect] 逐字同构，
     * 连"重名（409）时直接选中已有的那个"的理由都一样。
     */
    fun createRouteCategoryAndSelect(rawName: String, onDone: () -> Unit) {
        val name = rawName.trim().take(8)
        if (name.isBlank()) {
            formError = "分类名不能为空"
            return
        }
        acting = true
        formError = null
        viewModelScope.launch {
            try {
                try {
                    container.repo.createRouteCategory(name)
                } catch (e: Exception) {
                    val msg = toApiException(e).message.orEmpty()
                    if (!msg.contains("已经存在")) throw e
                }
                routeCategories = container.repo.routeCategories()
                routeCategory = name
                onDone()
            } catch (e: Exception) {
                formError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    // ===== 单独地点 =====

    fun openLocationCreate(slot: String? = null) {
        editingLocation = null
        pendingSlot = slot
        locName = ""; locDetail = ""; locRemark = ""
        locLat = null; locLng = null
        locImageUrls = emptyList(); locImageUploading = false
        locCategory = ""
        locIsWarehouse = false
        locContactName = ""; locContactPhone = ""
        formError = null
        showLocationDialog = true
    }

    fun openLocationEdit(l: LocationDto) {
        editingLocation = l
        pendingSlot = null
        locName = l.name
        locDetail = l.detailAddress
        locRemark = l.remark
        locLat = l.addressLat
        locLng = l.addressLng
        locImageUrls = l.imageUrls.ifEmpty { listOfNotNull(l.imageUrl) }
        locCategory = l.category
        locIsWarehouse = l.isWarehouse
        // ⚠️ 联系人**必须回填**：地点保存走的是"整份回传"（`LocationCreateRequest` 同时用于
        //    POST 与 PATCH），不回填的话"改个地点名字"就把绑定静默清掉了。
        locContactName = l.contactName
        locContactPhone = l.contactPhone
        locImageUploading = false
        formError = null
        showLocationDialog = true
    }

    /**
     * 就地新建一个分组并**选中它**（地点表单的分组下拉里那个「＋ 新建分组…」）。
     *
     * 与商品编辑页的 `createCategoryAndSelect` 是同一套做法：
     * 独立入口而不是"自由填名字" —— 自由填能造出只差一个空格的两个分组，
     * 地址库左栏因此多出一格，而列表上看不出差别。
     *
     * ⚠️ 重名（后端 409）时**直接选中已有的那个**：用户要的是"归到这个名字"，
     *    不是"再建一个"；报错让他自己回头找，是把后端的一句话变成他的一次往返。
     */
    fun createPlaceCategoryAndSelect(rawName: String, onDone: () -> Unit) {
        val name = rawName.trim().take(8)
        if (name.isBlank()) {
            formError = "分组名不能为空"
            return
        }
        acting = true
        formError = null
        viewModelScope.launch {
            try {
                try {
                    container.repo.createPlaceCategory(name)
                } catch (e: Exception) {
                    val msg = toApiException(e).message.orEmpty()
                    if (!msg.contains("已经存在")) throw e
                }
                placeCategories = container.repo.placeCategories()
                locCategory = name
                onDone()
            } catch (e: Exception) {
                formError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /** 上传地点图片（相册选择后在 IO 线程调用） */
    fun uploadLocationImage(file: java.io.File) {
        viewModelScope.launch {
            try {
                locImageUploading = true
                val url = container.repo.uploadLocationImage(file).url
                locImageUrls = locImageUrls + url
            } catch (e: Exception) {
                formError = toApiException(e).message
            } finally {
                locImageUploading = false
            }
        }
    }

    fun saveLocation() {
        if (locDetail.isBlank()) {
            formError = "请填写地点地址"
            return
        }
        acting = true
        formError = null
        viewModelScope.launch {
            try {
                val body = LocationCreateRequest(
                    name = locName.trim(),
                    detailAddress = locDetail.trim(),
                    remark = locRemark.trim(),
                    addressLat = locLat,
                    addressLng = locLng,
                    // 分组：留空 = 未分类；敲一个新的名字时后端会把它补进名册（顺手建分组）。
                    category = locCategory.trim(),
                    // ⚠️ 仓库标记按表单里的开关走。**货主那一侧开关不显示**，所以传 false ——
                    //    他编辑自己的地点不会影响仓库标记（那些点也不是他的）。
                    //    请求体是"整体替换"语义，不回填就等于"改个地点名顺手取消了仓库标记"。
                    isWarehouse = canMarkWarehouse && locIsWarehouse,
                    // 地点绑定的联系人（2026-09-24）—— 与线路 `receiver_name`/`phone` 同一口径：
                    // 存快照串。空串 = 解绑。**整份回传**，所以打开编辑时必须已回填（见 openLocationEdit）。
                    contactName = locContactName.trim(),
                    contactPhone = locContactPhone.trim(),
                    imageUrls = locImageUrls,
                )
                val cur = editingLocation
                if (cur == null) {
                    container.repo.createLocation(body)
                } else {
                    container.repo.updateLocation(cur.id, body)
                }
                // 行内新增（线路抽屉内）→ 自动回填对应槽位
                val slot = pendingSlot
                if (slot == "start") {
                    draftOrigin = locDetail.trim()
                    draftOriginLat = locLat
                    draftOriginLng = locLng
                    draftImageUrls = locImageUrls.toList()
                } else if (slot == "end") {
                    draftDetail = locDetail.trim()
                    draftLat = locLat
                    draftLng = locLng
                    draftImageUrls = locImageUrls.toList()
                }
                pendingSlot = null
                showLocationDialog = false
                load()
            } catch (e: Exception) {
                formError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun deleteLocation(l: LocationDto) {
        viewModelScope.launch {
            try {
                container.repo.deleteLocation(l.id)
                recentlyDeleted = RecentlyDeleted(
                    kind = "place", label = "地点", id = l.id, name = l.name,
                )
                load()
            } catch (e: Exception) {
                notice = toApiException(e).message
            }
        }
    }

    // ===== 图片（多张）移除 =====

    fun removeLineImage(url: String) {
        draftImageUrls = draftImageUrls.filter { it != url }
    }

    fun removeLocImage(url: String) {
        locImageUrls = locImageUrls.filter { it != url }
    }
}
