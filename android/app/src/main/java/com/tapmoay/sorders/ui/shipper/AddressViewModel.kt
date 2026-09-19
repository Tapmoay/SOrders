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
import com.tapmoay.sorders.data.remote.dto.ContactCreateRequest
import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.data.remote.dto.ContactUpdateRequest
import com.tapmoay.sorders.data.remote.dto.LocationCreateRequest
import com.tapmoay.sorders.data.remote.dto.LocationDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** 三个列表：常用线路（联系人+地点）/ 联系人 / 地点 */
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

    /** 这个地点是不是仓库（**只有派单员**能改，见后端 `api/v1/shipper.py`）。 */
    var locIsWarehouse by mutableStateOf(false)

    /** 当前登录人能不能标仓库 —— 货主看不到那个开关（后端也会拦，这里只是不给他点一个必然报错的东西）。 */
    var canMarkWarehouse by mutableStateOf(false)
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
            // 三条**全挂**才认定"这一页没加载出来"（整页给「重试」）；
            // 只挂了一部分就照常显示，缺的那条用 Snackbar 说一句 —— 别把好的也收走。
            if (!okAddresses && !okContacts && !okLocations) loadError = failed.firstOrNull() ?: "加载失败"
            else if (failed.isNotEmpty()) notice = failed.first()
            loading = false
        }
        viewModelScope.launch {
            try {
                canMarkWarehouse = container.tokenStore.sessionFlow.first()?.role == "dispatcher"
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
        formError = null
        showCreateDialog = true
    }

    /** 线路表单选择联系人（快照姓名+电话，换人重选即可） */
    fun selectContact(c: ContactDto) {
        draftContactId = c.id
        draftName = c.displayName
        draftPhone = c.phone
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
        // 地点有图 → 线路图片自动带图（多张全带）
        if (l.imageUrls.isNotEmpty() || !l.imageUrl.isNullOrBlank()) {
            draftImageUrls = l.imageUrls.ifEmpty { listOfNotNull(l.imageUrl) }
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

    fun openContactDialog(c: ContactDto? = null, fromLine: Boolean = false) {
        lineContactCtx = fromLine
        editingContact = c
        contactName = c?.displayName ?: ""
        contactPhone = c?.phone ?: ""
        formError = null
        showContactDialog = true
    }

    fun saveContact() {
        // 口径与后端一致（`ContactCreate.phone` 也走同一条电话规则）：只数字、7~12 位。
        // 原来是"长度 ≥5 就算过" —— 于是 `222`、`12345` 这种打不通的号也能进库
        // （生产库里真有一条 `222`）。规则唯一实现在 core/InputRules.kt。
        InputRules.phoneError(contactPhone.trim(), required = true)?.let {
            formError = it
            return
        }
        viewModelScope.launch {
            try {
                val cur = editingContact
                if (cur == null) {
                    val created = container.repo.createContact(
                        ContactCreateRequest(phone = contactPhone.trim(), displayName = contactName.trim())
                    )
                    if (lineContactCtx) {
                        selectContact(created)
                        lineContactCtx = false
                    }
                } else {
                    container.repo.updateContact(
                        cur.id,
                        ContactUpdateRequest(phone = contactPhone.trim(), displayName = contactName.trim())
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
                load()
            } catch (e: Exception) {
                notice = toApiException(e).message
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
