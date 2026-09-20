package com.tapmoay.sorders.core

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 工作台图标的顺序（`WorkbenchOrder`）—— 2026-09-20 用户要求「图标可以随意拖动」。
 *
 * 为什么值得单测：这里的错法全是"**界面上看起来没事，但顺序是错的**"：
 * 越界拖动崩一次、升级后新功能不见了、改版删掉的功能留下一个空洞、
 * 换个角色看到别人的顺序。它们都不会报错，只会在真机上被用户发现"我的顺序又乱了"。
 */
class WorkbenchOrderTest {

    private val list = listOf("a", "b", "c", "d", "e")

    @Test
    fun `往后拖一位`() {
        assertEquals(listOf("b", "a", "c", "d", "e"), WorkbenchOrder.move(list, 0, 1))
    }

    @Test
    fun `往前拖一位`() {
        // 语义是"**抽出来插到那个位置**"（桌面图标就是这么动的），不是"两个人对调"：
        // 对调的话中间那几个的相对顺序会被打乱，用户看到的是"我拖一个，别人也换了位置"。
        assertEquals(listOf("a", "d", "b", "c", "e"), WorkbenchOrder.move(list, 3, 1))
    }

    @Test
    fun `拖到原位不动`() {
        assertEquals(list, WorkbenchOrder.move(list, 2, 2))
    }

    @Test
    fun `越界原样返回（拖着手指划出网格是常事，不许崩也不许自己落位）`() {
        assertEquals(list, WorkbenchOrder.move(list, 0, 9))
        assertEquals(list, WorkbenchOrder.move(list, -1, 2))
        assertEquals(list, WorkbenchOrder.move(list, 9, 0))
    }

    @Test
    fun `没存过顺序就用原来的顺序`() {
        assertEquals(list, WorkbenchOrder.apply(list, emptyList()) { it })
    }

    @Test
    fun `按存下来的顺序排`() {
        val saved = listOf("c", "a", "e", "b", "d")
        assertEquals(saved, WorkbenchOrder.apply(list, saved) { it })
    }

    @Test
    fun `升级后新加的入口排在最后（而不是凭空消失）`() {
        // 用户拖过顺序之后，App 升级又多了一个功能：它必须在，且排在最后。
        val saved = listOf("b", "a")
        assertEquals(listOf("b", "a", "c", "d", "e"), WorkbenchOrder.apply(list, saved) { it })
    }

    @Test
    fun `改版删掉的入口跳过（不留空位）`() {
        val saved = listOf("e", "zzz", "a")
        assertEquals(listOf("e", "a", "b", "c", "d"), WorkbenchOrder.apply(list, saved) { it })
    }

    @Test
    fun `存下来的顺序不会多出一个入口也不会少一个`() {
        val saved = listOf("d", "c", "b", "a", "e")
        val out = WorkbenchOrder.apply(list, saved) { it }
        assertEquals(list.size, out.size)
        assertEquals(list.toSet(), out.toSet())
    }

    @Test
    fun `key 列表就是当前顺序`() {
        assertEquals(listOf("b", "a"), WorkbenchOrder.keys(listOf("b", "a")) { it })
    }
}
