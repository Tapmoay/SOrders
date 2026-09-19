package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.*
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ArrearsUnitCreateRequest
import com.tapmoay.sorders.data.remote.dto.ArrearsUnitDto
import com.tapmoay.sorders.data.remote.dto.ArrearsUnitUpdateRequest
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

class ArrearsUnitsViewModel(private val container: AppContainer) : ViewModel() {

    var units by mutableStateOf<List<ArrearsUnitDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    var showDialog by mutableStateOf(false)
    var editing by mutableStateOf<ArrearsUnitDto?>(null)
    var draftName by mutableStateOf("")
    var draftPhone by mutableStateOf("")
    var draftRemark by mutableStateOf("")

    init {
        load()
    }

    fun load() {
        loading = units.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                units = container.repo.arrearsUnits()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun openCreate() {
        editing = null
        draftName = ""; draftPhone = ""; draftRemark = ""
        showDialog = true
    }

    fun openEdit(u: ArrearsUnitDto) {
        editing = u
        draftName = u.name
        draftPhone = u.phone
        draftRemark = u.remark
        showDialog = true
    }

    fun save() {
        if (draftName.isBlank()) {
            error = "请填写单位名称"
            return
        }
        // 联系电话是可选的，但**填了就得是个能打通的号**（7~12 位数字）。
        // 规则唯一实现在 core/InputRules.kt（输入框那边已经在过滤非数字字符）。
        InputRules.phoneError(draftPhone.trim())?.let {
            error = it
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val cur = editing
                if (cur == null) {
                    container.repo.createArrearsUnit(
                        ArrearsUnitCreateRequest(draftName.trim(), draftPhone.trim(), draftRemark.trim())
                    )
                } else {
                    container.repo.updateArrearsUnit(
                        cur.id,
                        ArrearsUnitUpdateRequest(name = draftName.trim(), phone = draftPhone.trim(), remark = draftRemark.trim()),
                    )
                }
                actionResult = if (cur == null) "挂账单位已新增" else "挂账单位已更新"
                showDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun delete(u: ArrearsUnitDto) {
        acting = true
        viewModelScope.launch {
            try {
                container.repo.deleteArrearsUnit(u.id)
                actionResult = "已删除"
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
