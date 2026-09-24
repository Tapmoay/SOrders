package com.tapmoay.sorders.ui.common

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.api.UnitConversionCreateRequest
import com.tapmoay.sorders.data.remote.api.UnitConversionDto
import com.tapmoay.sorders.data.remote.api.UnitConversionUpdateRequest
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch

/**
 * 「单位换算」页的状态（一车 = 8 方）。
 *
 * ⚠️ **判据一条都不在这里**：空单位 / 两边同名 / 换算率 ≤ 0 / 一个源单位只能一条 / 反向对不许并存
 * 全在后端 `services/unit_conversion.py`。这里只负责取数、把后端那句中文**原样**显示出来
 * （它写得能照着改），以及把刚拿到的那一份同步给全 App 的 [UnitConv]。
 *
 * ⚠️ **每次改动都同步 [UnitConv]**：不同步的话，这个页面改完 8 → 10，
 * 订单卡片上还印着"10 车 ≈ 80 方"（而库里已经是 100 方）—— 两个数都不报错。
 */
class UnitConversionsViewModel(private val container: AppContainer) : ViewModel() {

    /** 活着的换算（显示用）。 */
    var rows by mutableStateOf<List<UnitConversionDto>>(emptyList())

    /** 回收站里的（用户 2026-09-20 的硬规矩：删除一律软删 + 界面上要有恢复入口）。 */
    var deleted by mutableStateOf<List<UnitConversionDto>>(emptyList())

    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    /** 一次性提示（Snackbar）；显示完置回 null。 */
    var notice by mutableStateOf<String?>(null)

    var showDialog by mutableStateOf(false)
    var editing by mutableStateOf<UnitConversionDto?>(null)

    /** 表单里那句话（后端的拒绝原样显示在弹窗里，见 [UnitConversionDialog]）。 */
    var formError by mutableStateOf<String?>(null)
    var saving by mutableStateOf(false)

    fun load() {
        if (loading) return
        loading = true
        error = null
        viewModelScope.launch {
            try {
                val alive = container.repo.unitConversions()
                rows = alive
                // 全 App 的那一份跟着刷新（订单卡片/明细/账本都读它）
                UnitConv.accept(alive)
                deleted = container.repo.unitConversions(deletedOnly = true)
            } catch (e: Exception) {
                error = toApiException(e).message ?: "换算表加载失败"
            } finally {
                loading = false
            }
        }
    }

    fun openCreate() {
        editing = null
        formError = null
        showDialog = true
    }

    fun openEdit(row: UnitConversionDto) {
        editing = row
        formError = null
        showDialog = true
    }

    /**
     * 保存（新增或编辑）。成功时关弹窗并刷新列表；
     * 失败时**只把后端那句话放进弹窗**（不关窗、不清空用户填的内容 —— 他要照着改）。
     */
    fun save(body: UnitConversionCreateRequest) {
        if (saving) return
        saving = true
        formError = null
        viewModelScope.launch {
            try {
                val cur = editing
                if (cur == null) {
                    container.repo.createUnitConversion(body)
                    notice = "已添加：1 ${body.fromUnit} = ${body.factor} ${body.toUnit}"
                } else {
                    container.repo.updateUnitConversion(
                        cur.id,
                        UnitConversionUpdateRequest(
                            fromUnit = body.fromUnit,
                            toUnit = body.toUnit,
                            factor = body.factor,
                            remark = body.remark,
                        ),
                    )
                    notice = "已改成：1 ${body.fromUnit} = ${body.factor} ${body.toUnit}"
                }
                showDialog = false
                load()
            } catch (e: Exception) {
                formError = toApiException(e).message ?: "没保存上，请重试"
            } finally {
                saving = false
            }
        }
    }

    fun delete(row: UnitConversionDto) {
        viewModelScope.launch {
            try {
                container.repo.deleteUnitConversion(row.id)
                // 说清"去哪儿找回来"：界面上那个「已删除」区就在下面几行
                notice = "已删除 1 ${row.fromUnit} = ${row.factor} ${row.toUnit}（下面「已删除」里可以恢复）"
                load()
            } catch (e: Exception) {
                notice = toApiException(e).message
            }
        }
    }

    fun restore(row: UnitConversionDto) {
        viewModelScope.launch {
            try {
                container.repo.restoreUnitConversion(row.id)
                notice = "已恢复 1 ${row.fromUnit} = ${row.factor} ${row.toUnit}"
                load()
            } catch (e: Exception) {
                // 冲突时后端会说清挡住它的是哪一条（这句要原样显示）
                notice = toApiException(e).message
            }
        }
    }
}
