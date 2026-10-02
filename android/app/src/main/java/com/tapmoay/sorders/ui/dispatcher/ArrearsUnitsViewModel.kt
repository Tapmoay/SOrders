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

/**
 * 刚被删掉的那一条挂账单位（够画「已删除「X」+ 撤销」这一行用）。
 *
 * 本页只有一种东西可删，所以不像地址页那样再记一个 `kind`。
 */
data class RecentlyDeleted(val id: Long, val name: String)

class ArrearsUnitsViewModel(private val container: AppContainer) : ViewModel() {

    var units by mutableStateOf<List<ArrearsUnitDto>>(emptyList())
    var loading by mutableStateOf(false)

    /**
     * 页面级错误：**只有 [load] 写它**（整页换 `ErrorView` + 重试）。
     *
     * ⛔ 表单的校验 / 保存失败绝不许写这里 —— 2026-09-21 那个坑就是这么来的：
     * 「点保存没有任何反应」和「关掉之后整页列表全没了」是同一句话造出来的两个假象
     * （规范 :458-478）。
     */
    var loadError by mutableStateOf<String?>(null)
    var acting by mutableStateOf(false)
    var actionResult by mutableStateOf<String?>(null)

    /** 表单级错误：跟着抽屉同生共死，画在抽屉里、提交键上方（`FormErrorLine`）。 */
    var formError by mutableStateOf<String?>(null)
    var showSheet by mutableStateOf(false)
    var editing by mutableStateOf<ArrearsUnitDto?>(null)
    var draftName by mutableStateOf("")
    var draftPhone by mutableStateOf("")
    var draftRemark by mutableStateOf("")

    /**
     * 刚删掉的那一条（非空 = 列表头顶画一行「已删除「X」+ 撤销」）。
     *
     * 只记**一条**是有意的：撤回的意思是「我手滑了」，不是"最近删除"文件夹。
     * 后端是真软删（`is_deleted` + 名字改成 `xxx_del{id}` 把唯一名释放出来），
     * 所以这里给的是真能救回来的「撤销」，不是安慰按钮。
     */
    var recentlyDeleted by mutableStateOf<RecentlyDeleted?>(null)

    init {
        load()
    }

    fun load() {
        loading = units.isEmpty()
        loadError = null
        viewModelScope.launch {
            try {
                units = container.repo.arrearsUnits()
            } catch (e: Exception) {
                loadError = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun openCreate() {
        editing = null
        draftName = ""; draftPhone = ""; draftRemark = ""
        // 打开表单要**清掉上一次的表单错误**：否则会看到"我还没填，红字已经说我填错了"。
        formError = null
        showSheet = true
    }

    fun openEdit(u: ArrearsUnitDto) {
        editing = u
        draftName = u.name
        draftPhone = u.phone
        draftRemark = u.remark
        formError = null
        showSheet = true
    }

    /** 关抽屉。保存途中（acting）不关：关掉就看不到结果了。 */
    fun closeSheet() {
        if (acting) return
        showSheet = false
    }

    fun save() {
        if (draftName.isBlank()) {
            formError = "请填写单位名称"
            return
        }
        // 联系电话是可选的，但**填了就得是个能打通的号**（7~12 位数字）。
        // 规则唯一实现在 core/InputRules.kt（输入框那边已经在过滤非数字字符）。
        InputRules.phoneError(draftPhone.trim())?.let {
            formError = it
            return
        }
        acting = true
        formError = null
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
                showSheet = false
                load()
            } catch (e: Exception) {
                // 保存失败留在表单里（抽屉不关），用户改完接着按保存。
                formError = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    fun delete(u: ArrearsUnitDto) {
        if (acting) return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.deleteArrearsUnit(u.id)
                // 撤回要的"那一条"就是刚删的这个（名字用删之前的：后端此刻已经把它改成 `xxx_del{id}`）。
                recentlyDeleted = RecentlyDeleted(u.id, u.name)
                actionResult = "已删除「" + u.name + "」"
                load()
            } catch (e: Exception) {
                // 删不掉是**意料之中**的一种结果（它名下还有没收钱的挂账单 / 有客户档案挂着 /
                // 有收款单记在它名下），后端那三句话就是给用户看的原文 ⇒ 走 snackbar 如实报。
                // ⛔ 不许写 loadError：那会把整页列表顶掉，用户会以为"删一下把整个页面搞没了"。
                actionResult = toApiException(e).message
            } finally {
                acting = false
            }
        }
    }

    /** 撤回上一次删除：真调后端的 restore（不是只把那一行塞回列表）。 */
    fun undoDelete() {
        val rd = recentlyDeleted ?: return
        if (acting) return
        acting = true
        viewModelScope.launch {
            try {
                container.repo.restoreArrearsUnit(rd.id)
                recentlyDeleted = null
                actionResult = "已恢复「" + rd.name + "」"
                load()
            } catch (e: Exception) {
                actionResult = "恢复失败：" + toApiException(e).message
            } finally {
                acting = false
            }
        }
    }
}
