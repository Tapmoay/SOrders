package com.tapmoay.sorders.core

import kotlinx.coroutines.asContextElement
import kotlinx.coroutines.withContext

/**
 * 「这一次请求是谁发起的」—— 整条链路只为了让后端知道「这一行审计是 AI 写的」。
 *
 * 后端侧：`X-SOrders-Origin: ai` → `operation_logs.origin` →
 * `sorders_ai_write_confirmed_today`（见 backend `core/client_origin.py`）。
 *
 * ## ⛔ 为什么必须是 ThreadLocal + asContextElement，而不是一个普通全局变量
 * 最直觉的写法是「执行 AI 写入前把一个 `var aiWriting = true` 打开，写完关掉」。
 * 那是**错的**，而且错得很隐蔽：这个窗口里**同一个进程里任何别的请求**（后台刷新、
 * 用户同时点的另一个按钮）都会被标成 `ai` —— 指标被悄悄灌水，而且没人看得出来。
 *
 * 用 ThreadLocal 就没这个问题：它只对**当前线程**可见。但协程会在挂起点之后**换线程**，
 * 所以单纯 `ThreadLocal.set` 也不可靠 —— 必须用 `asContextElement`：
 * 它让协程在**每一次恢复**时把 ThreadLocal 重新设到它实际运行的那条线程上。
 *
 * ⚠️ 光有 ThreadLocal 还不够，**读的位置**也在这次修复里：见 `ApiClient` 的
 * `OriginAwareCallFactory` —— 那个头必须挂在 `callFactory` 上，**不能**写成 OkHttp 的
 * `addInterceptor`：应用拦截器跑在 OkHttp 的 dispatcher 线程上，而 `newCall()` 是在
 * **协程当前线程**上同步调用的，只有后者才看得到这个 ThreadLocal。
 */
object ClientOrigin {

    /** 与后端 `core/client_origin.HEADER` 对齐（那边只认白名单，认不出的一律 human）。 */
    const val HEADER = "X-SOrders-Origin"
    const val AI = "ai"

    private val holder = ThreadLocal<String?>()

    /** 当前线程上的来源；不在 [asAi] 里就是 null（＝后端按 human 记）。 */
    fun current(): String? = holder.get()

    /**
     * 在这段代码里发出去的请求都带上 `X-SOrders-Origin: ai`。
     *
     * ⚠️ 只在**用户点了确认卡之后真正写库**那一段用它 —— 预览（`preview_write`）不写库，
     * 套上去只会让后端多记一堆没发生的事。
     */
    suspend fun <T> asAi(block: suspend () -> T): T =
        withContext(holder.asContextElement(AI)) { block() }
}