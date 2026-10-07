package com.tapmoay.sorders.core

import kotlinx.coroutines.runBlocking
import okhttp3.Call
import okhttp3.Request
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 「这一行审计是 AI 写的」这件事的**发出端**测试（报告 §15 ② 的 `AI_write_confirmed`）。
 *
 * 为什么值得测：这条链路上有两个**不会报错**的失效方式，两种都只会让指标恒为 0 ——
 * 看起来像「最近没人用 AI 写东西」，而不是像 bug：
 *
 * 1. 头挂在 OkHttp 的 `addInterceptor` 上（应用拦截器跑在 dispatcher 线程，
 *    而 [ClientOrigin] 是 ThreadLocal）→ 读到的永远是 null；
 * 2. 用普通全局变量做开关 → 窗口期内**任何别的请求**都被标成 ai，指标被灌水。
 *
 * 所以这里断言的是两件具体的事：**只在作用域里带头**、**出了作用域绝不带**。
 */
class ClientOriginTest {

    /** 只记录请求、不真发出去的假 Call.Factory。 */
    private class RecordingFactory : Call.Factory {
        var last: Request? = null
        override fun newCall(request: Request): Call {
            last = request
            throw UnsupportedOperationException("测试不需要真的发请求")
        }
    }

    private val url = "http://127.0.0.1:8000/api/v1/orders"

    /** 走一遍 newCall 并把「它拿到的请求」捞回来（假工厂会抛，所以必须 try）。 */
    private fun capture(factory: OriginAwareCallFactory): Request? {
        val rec = RecordingFactory()
        val wrapper = OriginAwareCallFactory(rec)
        try {
            wrapper.newCall(Request.Builder().url(url).build())
        } catch (_: UnsupportedOperationException) {
            // 预期：假工厂只记录不发
        }
        return rec.last
    }

    @Test
    fun notInsideAiScopeCarriesNoHeader() {
        assertNull("前提：不在 AI 作用域里", ClientOrigin.current())
        val req = capture(OriginAwareCallFactory(RecordingFactory()))
        assertNull("不在 AI 作用域里就不该带这个头（后端会按 human 记）", req!!.header(ClientOrigin.HEADER))
    }

    @Test
    fun insideAiScopeCarriesTheHeader() = runBlocking {
        var seen: String? = "（没进作用域）"
        ClientOrigin.asAi {
            seen = capture(OriginAwareCallFactory(RecordingFactory()))?.header(ClientOrigin.HEADER)
        }
        assertEquals("在 AI 作用域里发出去的请求必须带 ai", ClientOrigin.AI, seen)
    }

    @Test
    fun scopeIsClosedAfterTheBlock() = runBlocking {
        ClientOrigin.asAi {
            assertEquals("作用域内可见", ClientOrigin.AI, ClientOrigin.current())
        }
        assertNull("出了作用域必须清干净 —— 否则后续请求会被误标成 ai", ClientOrigin.current())
    }

    // ---- 2026-10-08（CHG-0082）新增：动作名那个头 ----

    /**
     * 带了动作 id 时，请求上要同时有「来源」和「动作」两个头。
     *
     * 后端那本「AI 操作流水」靠后者回答「AI 替我干的是哪件事」—— 只记 URL 路径看不出来
     * （`PATCH /api/v1/orders/{}` 是改联系人还是改运费，从路径上读不出）。
     */
    @Test
    fun insideAiScopeCarriesTheActionHeader() = runBlocking {
        var seenOrigin: String? = null
        var seenAction: String? = null
        ClientOrigin.asAi("order.assign") {
            val req = capture(OriginAwareCallFactory(RecordingFactory()))
            seenOrigin = req?.header(ClientOrigin.HEADER)
            seenAction = req?.header(ClientOrigin.ACTION_HEADER)
        }
        assertEquals("来源头照旧", ClientOrigin.AI, seenOrigin)
        assertEquals("动作 id 必须原样带出去", "order.assign", seenAction)
    }

    /** 没给动作 id 时**不许**带一个空头或多一个头（老调用点 `asAi { }` 必须和以前一模一样）。 */
    @Test
    fun withoutActionIdCarriesNoActionHeader() = runBlocking {
        var has = true
        ClientOrigin.asAi {
            has = capture(OriginAwareCallFactory(RecordingFactory()))
                ?.header(ClientOrigin.ACTION_HEADER) != null
        }
        assertEquals("没给动作 id 就不该有这个头（后端存 NULL，不是空串）", false, has)
    }

    @Test
    fun actionScopeIsClosedAfterTheBlock() = runBlocking {
        ClientOrigin.asAi("order.assign") {
            assertEquals("作用域内可见", "order.assign", ClientOrigin.currentAction())
        }
        assertNull("出了作用域必须清干净 —— 否则下一个动作会被记成上一个的名字", ClientOrigin.currentAction())
    }
}