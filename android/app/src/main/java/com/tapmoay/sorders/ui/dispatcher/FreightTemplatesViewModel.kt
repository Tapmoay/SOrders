package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.FreightTemplateDto
import com.tapmoay.sorders.data.remote.dto.FreightTemplateRequest
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

class FreightTemplatesViewModel(private val container: AppContainer) : ViewModel() {

    var templates by mutableStateOf<List<FreightTemplateDto>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    var showDialog by mutableStateOf(false)
    var editing by mutableStateOf<FreightTemplateDto?>(null)
    var draftName by mutableStateOf("")
    var draftFrom by mutableStateOf("")
    var draftTo by mutableStateOf("")
    var draftFee by mutableStateOf("")
    var draftVehicle by mutableStateOf("")
    var draftRemark by mutableStateOf("")

    var deleteTarget by mutableStateOf<FreightTemplateDto?>(null)

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            try {
                templates = container.repo.freightTemplates()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun openCreate() {
        editing = null
        draftName = ""
        draftFrom = ""
        draftTo = ""
        draftFee = ""
        draftVehicle = ""
        draftRemark = ""
        showDialog = true
    }

    fun openEdit(t: FreightTemplateDto) {
        editing = t
        draftName = t.name
        draftFrom = t.fromPlace
        draftTo = t.toPlace
        draftFee = t.fee
        draftVehicle = t.vehicleType ?: ""
        draftRemark = t.remark
        showDialog = true
    }

    fun save() {
        if (draftName.trim().isEmpty()) {
            error = "请填写模板名称"
            return
        }
        acting = true
        error = null
        viewModelScope.launch {
            try {
                val body = FreightTemplateRequest(
                    name = draftName.trim(),
                    fromPlace = draftFrom.trim(),
                    toPlace = draftTo.trim(),
                    vehicleType = draftVehicle.ifBlank { null },
                    fee = draftFee.trim().ifBlank { "0" },
                    remark = draftRemark.trim(),
                )
                val cur = editing
                if (cur == null) container.repo.createFreightTemplate(body)
                else container.repo.updateFreightTemplate(cur.id, body)
                actionResult = if (cur == null) "模板已创建" else "模板已更新"
                showDialog = false
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun requestDelete(t: FreightTemplateDto) {
        deleteTarget = t
    }

    fun confirmDelete() {
        val t = deleteTarget ?: return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.deleteFreightTemplate(t.id)
                actionResult = "模板已删除"
                deleteTarget = null
                load()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
