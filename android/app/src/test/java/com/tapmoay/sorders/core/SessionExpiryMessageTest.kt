package com.tapmoay.sorders.core

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「登录被作废之后说得出是哪一种」（2026-10-03 E2E 走查 BUG-0006）。
 *
 * ### 为什么这条值得钉住
 * 走查里 5554 被弹回登录页，屏幕上只有一句写死的「登录已失效，请重新登录」——
 * 而被顶号 / 被停用 / 改了密码 / 令牌过期，用户该做的事完全不同。服务端在 401 的正文里
 * 写了原因，缺的就是把它带出来（[ApiClient.unauthorizedDetail]）并把 403 那句话拆开
 * （[ApiClient.httpMessage]）。
 *
 * ⛔ 最隐蔽的一条在下面 `读原因不许把正文吃掉`：用 `string()` 读一次，
 *    后面 Retrofit 就再也读不到 body 了 —— **不报错**，只是那句错误信息凭空消失。
 */
class SessionExpiryMessageTest {

    private fun resp(code: Int, body: String): Response = Response.Builder()
        .request(Request.Builder().url("http://127.0.0.1/api/v1/users/me").build())
        .protocol(Protocol.HTTP_1_1)
        .code(code)
        .message("msg")
        .body(body.toResponseBody("application/json".toMediaType()))
        .build()

    @Test
    fun `401 里的后端原因原样透出`() {
        val r = resp(401, """{"detail":"登录已结束：账号在另一台设备登录（10-03 21:40）"}""")
        assertEquals("登录已结束：账号在另一台设备登录（10-03 21:40）", ApiClient.unauthorizedDetail(r))
    }

    @Test
    fun `读原因不许把正文吃掉`() {
        val r = resp(401, """{"detail":"登录已结束：账号被停用"}""")
        assertEquals("登录已结束：账号被停用", ApiClient.unauthorizedDetail(r))
        // ⛔ 这里改成 string() 就会读到空串（且不报错）——正是这条用例要防的坏法
        assertTrue("正文被读走了，后面那个错误就再也拿不到内容", r.body!!.string().contains("账号被停用"))
    }

    @Test
    fun `英文原因不许甩给用户`() {
        assertNull(ApiClient.unauthorizedDetail(resp(401, """{"detail":"Unauthorized"}""")))
    }

    @Test
    fun `没有正文也不炸`() {
        assertNull(ApiClient.unauthorizedDetail(resp(401, "")))
        assertNull(ApiClient.unauthorizedDetail(resp(401, "not json at all")))
    }

    @Test
    fun `401 与 403 的兜底不是同一句话`() {
        val a = ApiClient.httpMessage(401, null)
        val b = ApiClient.httpMessage(403, null)
        assertFalse("401 不许说权限：$a", a.contains("没有这个权限"))
        assertTrue("403 要说清是没有权限：$b", b.contains("没有这个权限"))
        assertFalse("403 与登录无关，不许提登录失效：$b", b.contains("登录已失效"))
        assertFalse("更不许劝人重新登录（他会一直重登）：$b", b.contains("重新登录"))
    }

    @Test
    fun `403 仍然带后端写的中文说明`() {
        assertEquals("当前角色无权执行此操作", ApiClient.httpMessage(403, "当前角色无权执行此操作"))
    }
}
