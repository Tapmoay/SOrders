package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.*
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.*
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

data class LineDraft(
    val productId: Long? = null,
    val name: String = "",
    val quantity: Int = 1,
    val price: String = "",
    val unit: String = "件",
) {
    val lineTotal: Double get() = (price.toDoubleOrNull() ?: 0.0) * quantity
}

class OrderCreateViewModel(private val container: AppContainer) : ViewModel() {

    val lines: SnapshotStateList<LineDraft> = mutableStateListOf()

    var addressDetail by mutableStateOf("")
    var addressLat by mutableStateOf<String?>(null)
    var addressLng by mutableStateOf<String?>(null)
    var dongjiaPhone by mutableStateOf("")
    var bossPhone by mutableStateOf("")
    var remark by mutableStateOf("")
    // 代理下单（派单员代下单）：shipperId=已注册货主；tempShipperName=临时货主（互斥）
    var shipperId by mutableStateOf<Long?>(null)
    var tempShipperName by mutableStateOf<String?>(null)
    var shippers by mutableStateOf<List<UserDto>>(emptyList())

    var products by mutableStateOf<List<ProductDto>>(emptyList())
    var addresses by mutableStateOf<List<AddressDto>>(emptyList())
    var loadingProducts by mutableStateOf(false)
    var submitting by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var success by mutableStateOf(false)

    var showProductSheet by mutableStateOf(false)
    var showAddressSheet by mutableStateOf(false)
    var showMapPicker by mutableStateOf(false)
    /** 收货地址参考图（本地缓存路径，提交订单成功后逐张上传，最多 9 张） */
    val draftAddressImages: SnapshotStateList<String> = mutableStateListOf()
    var editingLineIndex by mutableStateOf<Int?>(null)

    init {
        // 预加载商品目录与地址库
        viewModelScope.launch {
            try { products = container.repo.products() } catch (_: Exception) {}
        }
        viewModelScope.launch {
            try { addresses = container.repo.addresses() } catch (_: Exception) {}
        }
    }

    fun loadShippers() {
        viewModelScope.launch {
            try { shippers = container.repo.shippers() } catch (_: Exception) {}
        }
    }

    fun setShipper(id: Long?, tempName: String?) {
        shipperId = id
        tempShipperName = tempName?.trim()?.ifBlank { null }
    }

    fun addLine(name: String, price: String, productId: Long?, unit: String = "件") {
        if (lines.size >= 10) {
            error = "最多支持 10 组商品"
            return
        }
        lines.add(LineDraft(productId = productId, name = name, price = price, unit = unit))
    }

    fun updateLine(index: Int, line: LineDraft) {
        if (index in lines.indices) lines[index] = line
    }

    fun removeLine(index: Int) {
        if (index in lines.indices) lines.removeAt(index)
    }

    fun totalAmount(): Double = lines.sumOf { it.lineTotal }

    fun applyPicked(lat: Double, lng: Double, address: String) {
        addressLat = lat.toString()
        addressLng = lng.toString()
        addressDetail = address
        showMapPicker = false
    }

    fun applyAddress(a: AddressDto) {
        addressDetail = a.detailAddress
        addressLat = a.addressLat
        addressLng = a.addressLng
        dongjiaPhone = a.phone
        showAddressSheet = false
    }

    fun addDraftImage(path: String) {
        if (draftAddressImages.size >= 9) {
            error = "位置图片最多 9 张"
            return
        }
        if (path !in draftAddressImages) draftAddressImages.add(path)
    }

    fun removeDraftImage(path: String) {
        draftAddressImages.remove(path)
    }

    fun submit(onDone: () -> Unit) {
        val nameBlank = lines.any { it.name.isBlank() }
        when {
            lines.isEmpty() -> error = "请至少添加一组商品"
            nameBlank -> error = "商品名称不能为空"
            else -> {
                submitting = true
                error = null
                viewModelScope.launch {
                    try {
                        val body = OrderCreateRequest(
                            lines = lines.map {
                                OrderProductLine.create(it.name.trim(), it.quantity, it.price)
                            },
                            deliveryDescription = "",
                            addressDetail = addressDetail.trim(),
                            addressLat = addressLat,
                            addressLng = addressLng,
                            contactDongjiaPhone = dongjiaPhone.trim(),
                            contactBossPhone = bossPhone.trim(),
                            remark = remark.trim(),
                            shipperId = shipperId,
                            tempShipperName = tempShipperName,
                        )
                        val created = container.repo.createOrder(body)
                        draftAddressImages.forEach { path ->
                            runCatching {
                                val f = java.io.File(path)
                                if (f.exists()) container.repo.uploadOrderAddressImage(created.id, f)
                            }
                        }
                        success = true
                        onDone()
                    } catch (e: Exception) {
                        error = toApiException(e).message
                    } finally {
                        submitting = false
                    }
                }
            }
        }
    }
}
