package com.tapmoay.sorders.data.repo

import okhttp3.Headers
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.Response

/**
 * 列表截断头的**唯一**读数处（[parsePageMeta] / [Response.pageMeta] / [Response.pageRows]）。
 *
 * ### 为什么这几条值得一个测试文件
 * 这个位错了**不会报错、不会崩**，只会让界面说一句错话，而两种错话都有人照它做决定：
 * - 假"还有更多" → 用户白找一圈（空列表里翻半天）；
 * - 假"没有了" → 用户把"没显示"读成"不存在"：现金流水页对一页求和当总额（实测少算 62%）、
 *   审计页判断"这条改动没被记录"、账号列表里没有就去新建一个（撞手机号唯一约束）。
 *
 * ⚠️ 头**缺失**必须是 `hasMore=false, limit=null`，**不是**"这页满了就当作还有更多"：
 *    猜法在刚好整页时说假话，而且这两条链路上说假话的代价不对称。
 * ⚠️ `X-Result-Limit` 只认**正**整数：`0`/负数/乱码一律当"没有这个头"，
 *    否则界面会照着它说"只显示了最近 0 条"。
 */
class PageMetaTest {

    // ------------------------------------------------------------ 纯函数：两个头的原文 → PageMeta

    @Test
    fun `有头且被截断——读出 hasMore 与本次上限`() {
        val meta = parsePageMeta("1", "200")
        assertTrue(meta.hasMore)
        assertEquals(200, meta.limit)
    }

    @Test
    fun `有头且没被截断——hasMore 是 false，上限照样读出来`() {
        // 上限值和"是否截断"是两件事：没截断时界面也要能说"这一页最多 200 条"
        val meta = parsePageMeta("0", "100")
        assertFalse(meta.hasMore)
        assertEquals(100, meta.limit)
    }

    @Test
    fun `两个头都没有（老后端）——既不截断也不给上限，界面不许自己猜一个数`() {
        assertEquals(PageMeta.ABSENT, parsePageMeta(null, null))
        assertFalse(parsePageMeta(null, null).hasMore)
        assertNull(parsePageMeta(null, null).limit)
    }

    @Test
    fun `只有截断位没有上限——截断照样说，条数留空`() {
        val meta = parsePageMeta("1", null)
        assertTrue(meta.hasMore)
        assertNull(meta.limit)
    }

    @Test
    fun `只有上限没有截断位——按没截断算（判据只看 X-Truncated）`() {
        val meta = parsePageMeta(null, "60")
        assertFalse(meta.hasMore)
        assertEquals(60, meta.limit)
    }

    @Test
    fun `上限不是正整数一律当没有——不许让界面说「最近 0 条」`() {
        assertNull(parsePageMeta("1", "0").limit)
        assertNull(parsePageMeta("1", "-5").limit)
        assertNull(parsePageMeta("1", "").limit)
        assertNull(parsePageMeta("1", "abc").limit)
        assertNull(parsePageMeta("1", "100 条").limit)
    }

    @Test
    fun `只有恰好等于 1 才算截断——其余任何取值都不是`() {
        // "true"/"yes"/"2" 都不认：后端写的就是 1/0，多认一种写法就多一种误报
        assertFalse(parsePageMeta("true", "100").hasMore)
        assertFalse(parsePageMeta("yes", "100").hasMore)
        assertFalse(parsePageMeta("2", "100").hasMore)
        assertFalse(parsePageMeta("", "100").hasMore)
    }

    @Test
    fun `两头都容忍首尾空白——代理或手写头时常见`() {
        val meta = parsePageMeta(" 1 ", " 500 ")
        assertTrue(meta.hasMore)
        assertEquals(500, meta.limit)
    }

    // ------------------------------------------------------------ OkHttp 响应 → PageMeta

    @Test
    fun `响应头带 X-Truncated 时 pageMeta 读得到（头名大小写不敏感）`() {
        val resp = Response.success(
            listOf("a"),
            Headers.headersOf("X-Truncated", "1", "X-Result-Limit", "1000"),
        )
        assertEquals(PageMeta(hasMore = true, limit = 1000), resp.pageMeta())
    }

    @Test
    fun `响应头什么都没有时 pageMeta 给 ABSENT（不是猜、也不是崩）`() {
        val resp = Response.success(listOf("a"), Headers.headersOf("Content-Type", "application/json"))
        assertEquals(PageMeta.ABSENT, resp.pageMeta())
    }

    @Test
    fun `pageRows 把行与截断位一起给调用方——body 为 null 时行是空表而不是崩`() {
        val empty = Response.success<List<String>>(null, Headers.headersOf("X-Truncated", "0", "X-Result-Limit", "100"))
        assertEquals(0, empty.pageRows().rows.size)
        assertEquals(100, empty.pageRows().meta.limit)

        val full = Response.success(listOf("a", "b"), Headers.headersOf("X-Truncated", "1", "X-Result-Limit", "2"))
        assertEquals(listOf("a", "b"), full.pageRows().rows)
        assertTrue(full.pageRows().meta.hasMore)
    }
}
