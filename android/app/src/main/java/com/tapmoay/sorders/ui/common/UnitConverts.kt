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

    /**
     * 谁能读这张表 —— **后端角色的 key**（`shipper` / `dispatcher`），不是 App 的 `Role`。
     *
     * ⛔ 为什么不能用 `Role` 判：`Role.fromKey` 把不认识的 key 折成 SHIPPER，
     *    而后端确实还有 `wholesaler`（批发商）—— 用折过的枚举判，批发商照样发请求、照样 403。
     * ⛔ 这一份必须与后端 `UnitOwner` 逐字一致（`backend/app/api/v1/unit_conversions.py`）：
     *    两边一起对是判据 `_tools/qa/_check_unit_conv_prefetch_role.py` 的第一组。
     */
    val READ_ROLE_KEYS: Set<String> = setOf("shipper", "dispatcher")

    /** 这个角色能不能读换算表（决定 [ensure] 要不要真的发那次 GET）。 */
    fun canRead(roleKey: String?): Boolean = roleKey != null && roleKey in READ_ROLE_KEYS
    /**
     * 首次使用时拉一次（幂等）。**失败不抛**：调用点在 Compose 的 `LaunchedEffect` 里。
     *
     * ⛔ `roleKey` 是**必填**参数，不是装饰：换算表只有货主与派单员能读
     *    （后端 `require_roles(SHIPPER, DISPATCHER)`）。原来这里不看角色、会话一建立就无条件拉，
     *    司机每次登录/恢复都会换回一条 403 —— 而失败是静默的（见文件头那段），界面上什么都看不到，
     *    只有后端日志一直在响（走查报告 §5.3「unit-conversions 403」）。
     *    设成必填，是让"哪一页能拉"在**编译期**就必须被回答一次。
     */
    suspend fun ensure(repo: AppRepository, roleKey: String?) {
        if (!canRead(roleKey)) return
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
