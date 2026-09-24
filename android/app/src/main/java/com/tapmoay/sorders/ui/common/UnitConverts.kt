package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.data.remote.api.UnitConversionDto
import com.tapmoay.sorders.data.repo.AppRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 单位换算的**本机缓存**（一车 = 8 方）—— 换算是"全库共用的一份"，全 App 只有一个来源。
 *
 * ## 为什么需要一个持有者，而不是每个页面各自去拉
 * 需要"10 车 ≈ 80 方"的地方有四处（订单卡片 / 订单详情明细 / 账本小卡 / 下单页清单行），
 * 而它们**都不是各自独立的页面**（订单卡片被四张列表共用）。每个页面各拉一次的话：
 * ① 同一屏上可能同时存在"已经拉到"与"还没拉到"的两张卡（同一批货两个显示）；
 * ② 换算表改完（在那个管理页里）之后，别的页面**不会知道**。
 *
 * 所以：一份 `StateFlow` + 三个入口（`ensure` 拉一次 / `refresh` 强制重拉 / `accept` 用刚拿到的
 * 那一份直接替换）。谁都不许自己缓存一份 —— 判据 `_tools/qa/_check_unit_conversion.py` 钉着。
 *
 * ⚠️ 拉失败**不报错也不清空**：换算只是"多显示一个数"，它不该让订单列表变成错误页。
 * 失败时保留上一次的（首次失败就是空表 → 界面照旧只显示原单位）。
 */
object UnitConv {

    private val _rows = MutableStateFlow<List<UnitConversionDto>>(emptyList())

    /** 活着的换算（回收站里的不在这一份里 —— 显示用不上它们）。 */
    val rows: StateFlow<List<UnitConversionDto>> = _rows.asStateFlow()

    /** 拉过一次就不再拉（登录时 [ensure] 会拉）。 */
    private var loaded = false

    /** 首次使用时拉一次（幂等）。**失败不抛**：调用点在 Compose 的 `LaunchedEffect` 里。 */
    suspend fun ensure(repo: AppRepository) {
        if (loaded) return
        refresh(repo)
    }

    /** 强制重拉（管理页改完之后、下拉刷新时）。 */
    suspend fun refresh(repo: AppRepository) {
        runCatching { repo.unitConversions() }.onSuccess { accept(it) }
    }

    /** 用**刚拿到的那一份**直接替换（管理页 CRUD 之后不用再多一次请求）。 */
    fun accept(list: List<UnitConversionDto>) {
        _rows.value = list.filter { it.deletedAt == null }
        loaded = true
    }

    /**
     * 退出登录时清掉。**必须清**：换一个账号登录时沿用上一个人的换算表，
     * 会让"10 车 ≈ 80 方"这种数在别人的单上继续显示（而它是全库共用的，本来也不该按人缓存）。
     */
    fun clear() {
        _rows.value = emptyList()
        loaded = false
    }
}
