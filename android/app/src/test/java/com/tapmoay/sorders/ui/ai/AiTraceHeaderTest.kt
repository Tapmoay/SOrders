package com.tapmoay.sorders.ui.ai

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 「执行过程」那一行标题怎么念（台账 L-60 / CHG-0094）。
 *
 * ## 为什么要钉
 * 折叠之后，这一行是用户**唯一**还能看见的信息：写错"几步"就等于把过程藏死
 * （用户不知道里面有没有他要找的那一句）；把"进行中"写丢，用户就分不清屏幕上
 * 跳动的是新回答还是历史记录。所以逐档钉死，包括"一条都没有"和"展开优先"。
 */
class AiTraceHeaderTest {

    @Test
    fun `折叠着跑完了_写查看加条数`() {
        assertEquals("查看执行过程 · 6 条", traceHeaderLabel(lineCount = 6, running = false, expanded = false))
        assertEquals("查看执行过程 · 1 条", traceHeaderLabel(lineCount = 1, running = false, expanded = false))
    }

    @Test
    fun `折叠着还在跑_写进行中_不带条数`() {
        // 进行中不带条数：每一步都会 +1，标题跟着跳字是噪声
        assertEquals("执行过程 · 进行中", traceHeaderLabel(lineCount = 3, running = true, expanded = false))
        assertEquals("执行过程 · 进行中", traceHeaderLabel(lineCount = 99, running = true, expanded = false))
    }

    @Test
    fun `展开着_写的是点下去会发生什么_收起`() {
        assertEquals("收起执行过程", traceHeaderLabel(lineCount = 6, running = false, expanded = true))
        // 展开 > 进行中：已经摊开了就别再喊"进行中"，那句话管的是"点一下"
        assertEquals("收起执行过程", traceHeaderLabel(lineCount = 6, running = true, expanded = true))
    }

    @Test
    fun `一条都没有_也不许留一个空标题`() {
        // 空标题会变成一个点不开也看不懂的灰条
        assertEquals("查看执行过程", traceHeaderLabel(lineCount = 0, running = false, expanded = false))
        assertEquals("执行过程 · 进行中", traceHeaderLabel(lineCount = 0, running = true, expanded = false))
    }
}
