package com.tapmoay.sorders.core

import android.content.Context

/**
 * 工作台图标的**顺序**（2026-09-20 用户要求）。
 *
 * 用户原话：「以前的图片图标啊，它是**可以随意拖动的**，就像那个桌面图标一样」。
 *
 * ## 为什么顺序要存在本机，而不是给每个账号存一份到后端
 * 它是一台手机上"我习惯先点哪个"的**手感**，不是业务数据：换台手机重新拖一次就好，
 * 而一旦存进后端它就变成一条要同步、要冲突处理、要写审计的账号设置 ——
 * 为一个拖拽动作养一条后端链路，正是"为了修一个需求增加一堆功能"。
 * 但它必须**按角色分开存**：同一台手机上派单端与货主端的图标完全不同，
 * 共用一份顺序的话，切个角色就会看到"顺序全乱"（而且谁也不报错）。
 *
 * ## 为什么纯逻辑单独一个对象
 * "拖到哪儿、存下来的顺序怎么套回当前清单"这两件事有真实的错法
 * （越界、名单变了之后对不上、同名 key），所以它们要能被单测，
 * 不能埋在 Compose 的拖拽回调里（那里只能靠手指试）。
 */
object WorkbenchOrder {

    /** 存 key 的偏好名（与 `HintPrefs` 同一个理由：合成时要**同步**读出来）。 */
    const val PREFS = "workbench_order"

    /**
     * 把第 [from] 个挪到第 [to] 个，返回新列表。
     *
     * ⚠️ 越界**原样返回**，不许抛、也不许"就近落位"：
     *    拖动过程中手指很容易划出网格（这里每一帧都在算落点），
     *    抛异常 = 一划出去就崩；"就近落位" = 图标自己跳到一个用户没指的位置。
     */
    fun <T> move(items: List<T>, from: Int, to: Int): List<T> {
        if (from == to) return items
        if (from !in items.indices || to !in items.indices) return items
        val out = items.toMutableList()
        out.add(to, out.removeAt(from))
        return out
    }

    /**
     * 把存下来的顺序套回**当前**清单。
     *
     * ⚠️ 三条必须成立（图标签到与版本升级都会碰到）：
     * ① 存过但**现在已经没有**的入口（改版删掉的功能）→ 跳过，不留空位；
     * ② **新加的**入口（升级后多出来的功能）→ 排在最后，而不是凭空消失；
     * ③ 没存过任何顺序（第一次装 App）→ 原样返回后端/代码里的默认顺序。
     */
    fun <T> apply(entries: List<T>, saved: List<String>, key: (T) -> String): List<T> {
        if (saved.isEmpty()) return entries
        val byKey = entries.associateBy(key)
        val seen = saved.toHashSet()
        val ordered = saved.mapNotNull { byKey[it] }
        val rest = entries.filter { key(it) !in seen }
        return ordered + rest
    }

    /** 当前顺序 → 要存下来的 key 列表。 */
    fun <T> keys(entries: List<T>, key: (T) -> String): List<String> = entries.map(key)
}

/**
 * 工作台顺序的落盘（`SharedPreferences`）。
 *
 * 为什么不用项目里别处的 DataStore：这一读发生在**合成时**（要先把顺序套好再画第一帧），
 * 而 DataStore 只有挂起读 —— 挂起读会让工作台先按默认顺序画一帧、再跳成用户自己的顺序
 * （每次进工作台都闪一下）。与 `HintPrefs` / `AlertPrefs` 同一条理由。
 */
class WorkbenchOrderStore(context: Context) {

    private val sp = context.applicationContext
        .getSharedPreferences(WorkbenchOrder.PREFS, Context.MODE_PRIVATE)

    /** 某个角色存过的顺序（逗号分隔的路由；空 = 没拖过）。 */
    fun order(roleKey: String): List<String> =
        (sp.getString(roleKey, null) ?: "").split(",").map { it.trim() }.filter { it.isNotEmpty() }

    fun save(roleKey: String, keys: List<String>) {
        sp.edit().putString(roleKey, keys.joinToString(",")).apply()
    }
}
