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

class FreightSettlementViewModel(private val container: AppContainer) : ViewModel() {

    var data by mutableStateOf<FreightSettlementDto?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var month by mutableStateOf(currentMonth())

    init {
        load()
    }

    fun currentMonth(): String = LocalDate.now().format(DateTimeFormatter.ofPattern("yyyy-MM"))

    fun shiftMonth(delta: Int) {
        val m = LocalDate.now().plusMonths(delta.toLong()).format(DateTimeFormatter.ofPattern("yyyy-MM"))
        month = m
        load()
    }

    fun load() {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                data = container.repo.freightSettlement(month)
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }
}
