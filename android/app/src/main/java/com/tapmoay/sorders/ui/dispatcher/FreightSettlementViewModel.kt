package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.FreightSettlementDto
import com.tapmoay.sorders.data.repo.toApiException
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.format.DateTimeFormatter

/**
 * 司机运费结算（两栏：左篮子 / 右详情）。
 *
 * 选中态存的是**字符串 key**（`d|<司机 id>`）而不是 `FreightSettlementGroupDto`：
 * 换月份会整批换掉 `data`，存对象的话选中的那位会指向一个已经被替换掉的旧实例
 * （界面照样亮着，但读出来的单数/金额是上个月的）。
 */
class FreightSettlementViewModel(private val container: AppContainer) : ViewModel() {

    var data by mutableStateOf<FreightSettlementDto?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var month by mutableStateOf(currentMonth())

    /** 左栏的搜索词（姓名 / 手机号 / 后 4 位，规则在 `core/UserSearch`）。 */
    var query by mutableStateOf("")

    /** 右栏正在看哪位司机（`d|<id>`）；空 = 还没点，界面回落到第一位。 */
    var selectedKey by mutableStateOf("")

    init {
        load()
    }

    fun currentMonth(): String = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy-MM"))

    fun shiftMonth(delta: Int) {
        val m = LocalDate.now().plusMonths(delta.toLong()).format(DateTimeFormatter.ofPattern("yyyy-MM"))
        month = m
        load()
    }

    fun selectDriver(key: String) {
        selectedKey = key
    }

    fun load() {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                data = container.repo.freightSettlement(month)
                // 换月份后把选中清掉：那个 key 在这个月可能根本不存在，
                // 而界面会"回落到第一位"—— 留着旧 key 会让左栏高亮和右栏内容对不上。
                selectedKey = ""
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }
}
