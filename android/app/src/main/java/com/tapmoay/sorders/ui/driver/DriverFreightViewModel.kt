package com.tapmoay.sorders.ui.driver

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.util.moneyToDouble
import kotlinx.coroutines.launch
import java.time.LocalDate

/** 司机「我的账本」：与货主/派单员账本同模板（按日/按周/按月 + 趋势图 + 明细）。 */
class DriverFreightViewModel(private val container: AppContainer) : ViewModel() {

    /** 明细行（订单维度） */
    data class FreightRow(
        val orderId: Long,
        val orderNo: String,
        val deliveredAt: String?,
        /** **司机应得**（后端 `driver_pay.pay_for_order` 算的，与司机账单同源）。 */
        val payTotal: String,
        /** 货主那头的运费（提成基数）；null = 还没定价。**不等于司机应得**。 */
        val freightFee: String?,
        val desc: String,
        val address: String,
    )

    var rows by mutableStateOf<List<FreightRow>>(emptyList())
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    // 时间导航（按日/按周/按月）+ 趋势图
    var chartMode by mutableStateOf("day")
    var chartAnchor by mutableStateOf(LocalDate.now().toString())
    var chartType by mutableStateOf("line")

    init {
        load()
        viewModelScope.launch {
            container.realtimeHub.refreshLedger.collect { load() }
        }
    }

    // ⚠️ 合计与趋势图都必须用 **payTotal（司机应得）**，不能用 freightFee（货主运费）：
    //    司机挂了"每单 300 + 运费 5%"这类规则时两者差得很远（账单 675 / 旧算法 1500），
    //    而页面标题写的是"当前范围内合计"——用运费求和就等于司机拿一个公司不认的数来对账。
    fun total(): Double = rows.sumOf { moneyToDouble(it.payTotal) }

    val periodStart: String get() = _periodRange().first
    val periodEnd: String get() = _periodRange().second

    private fun _periodRange(): Pair<String, String> {
        val d = LocalDate.parse(chartAnchor)
        return when (chartMode) {
            "week" -> (d.minusDays((d.dayOfWeek.value - 1).toLong()).toString() to d.plusDays((7 - d.dayOfWeek.value).toLong()).toString())
            "month" -> (d.withDayOfMonth(1).toString() to d.withDayOfMonth(d.lengthOfMonth()).toString())
            else -> (d.toString() to d.toString())
        }
    }

    val periodText: String get() = periodStart + " 00:00:00~" + periodEnd + " 23:59:59"

    fun applyMode(mode: String) {
        chartMode = mode
        load()
    }

    fun setAnchor(anchor: String) {
        chartAnchor = anchor
        load()
    }

    /** 按日汇总（趋势图 x 轴） */
    val chartSeries: List<Pair<String, Double>> get() {
        val map = LinkedHashMap<String, Double>()
        rows.forEach { e ->
            val key = (e.deliveredAt ?: "").take(10)
            if (key.isNotBlank()) map[key] = (map[key] ?: 0.0) + moneyToDouble(e.payTotal)
        }
        return map.entries.map { it.key to it.value }
    }

    fun load() {
        loading = rows.isEmpty()
        error = null
        viewModelScope.launch {
            try {
                val dto = container.repo.freightSettlementRange(periodStart + " 00:00:00", periodEnd + " 23:59:59")
                val me = dto.groups.firstOrNull()
                rows = me?.orders?.map {
                    FreightRow(
                        orderId = it.orderId,
                        orderNo = it.orderNo,
                        deliveredAt = it.deliveredAt?.take(16)?.replace("T", " "),
                        payTotal = it.payTotal,
                        freightFee = it.freightFee,
                        desc = it.deliveryDescription,
                        address = it.addressDetail,
                    )
                } ?: emptyList()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                loading = false
            }
        }
    }
}
