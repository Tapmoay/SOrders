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
import kotlinx.coroutines.launch

/** 三个列表：常用线路（联系人+地点）/ 联系人 / 地点 */
class AddressViewModel(private val container: AppContainer) : ViewModel() {

    var addresses by mutableStateOf<List<AddressDto>>(emptyList())
    var contacts by mutableStateOf<List<ContactDto>>(emptyList())
    var locations by mutableStateOf<List<LocationDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
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
    var locImageUploading by mutableStateOf(false)
    var pendingSlot by mutableStateOf<String?>(null)   // 行内新增地点回填槽位 start/end
    var lineContactCtx by mutableStateOf(false)        // 从线路抽屉打开的联系人抽屉

    init {
        load()
    }

    fun load() {
        loading = addresses.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                addresses = container.repo.addresses()
                contacts = container.repo.contacts()
                locations = container.repo.locations()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
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
                error = toApiException(e).message
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
            error = "请选择联系人"
            return
        }
        if (draftDetail.isBlank()) {
            error = "请填写收货地址（终点）"
            return
        }
        acting = true
        error = null
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
                error = toApiException(e).message
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
                error = toApiException(e).message
            }
        }
    }

    fun setDefault(a: AddressDto) {
        viewModelScope.launch {
            try {
                container.repo.setDefaultAddress(a.id)
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
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
        showContactDialog = true
    }

    fun saveContact() {
        // 口径与后端一致（`ContactCreate.phone` 也走同一条电话规则）：只数字、7~12 位。
        // 原来是"长度 ≥5 就算过" —— 于是 `222`、`12345` 这种打不通的号也能进库
        // （生产库里真有一条 `222`）。规则唯一实现在 core/InputRules.kt。
        InputRules.phoneError(contactPhone.trim(), required = true)?.let {
            error = it
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
                error = toApiException(e).message
            }
        }
    }

    fun deleteContact(c: ContactDto) {
        viewModelScope.launch {
            try {
                container.repo.deleteContact(c.id)
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
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
        locImageUploading = false
        showLocationDialog = true
    }

    /** 上传地点图片（相册选择后在 IO 线程调用） */
    fun uploadLocationImage(file: java.io.File) {
        viewModelScope.launch {
            try {
                locImageUploading = true
                val url = container.repo.uploadLocationImage(file).url
                locImageUrls = locImageUrls + url
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                locImageUploading = false
            }
        }
    }

    fun saveLocation() {
        if (locDetail.isBlank()) {
            error = "请填写地点地址"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val body = LocationCreateRequest(
                    name = locName.trim(),
                    detailAddress = locDetail.trim(),
                    remark = locRemark.trim(),
                    addressLat = locLat,
                    addressLng = locLng,
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
                error = toApiException(e).message
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
                error = toApiException(e).message
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
