package com.tapmoay.sorders.ui.driver

import android.content.Context
import android.content.ContextWrapper
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.OrderDto
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withContext
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * BUG-0026 的回归：**司机端「进行中」列表被实时推送打断后，整页报
 * 「StandaloneCoroutine was cancelled」**（测试台账 TA-04；真机 dump 见
 * `_tmp/test_round3/evidence_ta04_before.txt`）。
 *
 * 病灶：`DriverOrdersViewModel.load()` 里 `loadJob?.cancel()` 之后，**被取消的那一趟还会跑完它的
 * `catch (e: Exception)`** —— `CancellationException` 是 `Exception` 的子类，于是「取消」被当成
 * 业务失败写进了页面级 `error`，而渲染门（`DriverOrdersScreen.kt` 的 `vm.error != null`）
 * 拿它把整个列表顶掉了。
 *
 * ⚠️ 为什么这几条用例里取数要 `withContext(io)` 绕一跳：真机上取数不在主线程上返回（OkHttp 的回调
 * 从网络线程续回主线程），取消也要沿同一条路走回来 —— 于是**被取消的那一趟的 catch 会排在新一趟
 * `error = null` 之后**。交错探针 `_tmp/test_round3/probe_out.txt` 里 P1/P3/P4/P5（取数挂在同一个
 * 调度器上）都看不见这个现象，只有 P2（跨调度器挂起）能摆出来 —— 与真机现象一致。
 *
 * 真机配方（改前的复现由父会话在隔离测试栈上跑）：司机端停在「进行中」→ 点顶部刷新 → 0.25 秒内用
 * 派单员 token `POST /orders/{id}/assign`（driver_id=128）——推送插进来，正是打断在飞的那一趟取数。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class DriverOrdersLoadCancelTest {

    private val main = StandardTestDispatcher()

    @Before fun setUp() { Dispatchers.setMain(main) }

    @After fun tearDown() { Dispatchers.resetMain() }

    /**
     * JVM 单测里没有真 Context（本模块没有 Robolectric）：容器只是把它存下来
     * （`appContext` 读的是 `getApplicationContext`，返回自己就够），
     * 真正会被这份用例碰到的两个依赖（取数、推送）都由构造接缝换掉了。
     */
    private class FakeContext : ContextWrapper(null) {
        override fun getApplicationContext(): Context = this
    }

    private fun newViewModel(
        pushes: Flow<Unit> = emptyFlow(),
        fetch: suspend (wanted: Int, from: String?, to: String?) -> List<OrderDto>,
    ) = DriverOrdersViewModel(AppContainer(FakeContext()), fetch, pushes)

    private fun order(id: Long) = OrderDto(
        id = id,
        orderNo = "SO20261010000000" + id,
        status = "DISPATCHED",
        createdAt = "2026-10-10 03:0" + id + ":00",
    )

    /**
     * 病灶本身：推送打断正在飞的那一趟取数时，**取消不是失败**。
     *
     * 改前：第一趟被取消后，它的 `catch (e: Exception)` 把 `StandaloneCoroutine was cancelled`
     * 写进 `error`（落在第二趟 `error = null` 之后），并且它的 `finally` 把第二趟的 `loading`
     * 一起收成了 false —— 屏幕上就是「整页错误串 ＋ 重试」，列表被顶掉。
     */
    @Test
    fun `推送打断：被取消的取数不写错误页也不收加载态`() = runTest(main) {
        val io = StandardTestDispatcher(testScheduler)
        val pushes = MutableSharedFlow<Unit>(extraBufferCapacity = 8)
        val first = CompletableDeferred<List<OrderDto>>()
        val second = CompletableDeferred<List<OrderDto>>()
        var calls = 0
        val vm = newViewModel(pushes) { _, _, _ ->
            val gate = if (++calls == 1) first else second
            withContext(io) { gate.await() }
        }

        runCurrent() // init 那一趟已经挂在第一道闸上（这一页正在取数）
        assertTrue(vm.loading)
        assertNull(vm.error)

        pushes.emit(Unit) // 派单员派单 → 推送插进来 → 第二趟取数取消第一趟
        runCurrent()
        // ⚠️ 取消是**沿取数那条路走回来**的（真机：网络线程 → 主线程），所以被取消那趟的 catch
        //    不会在 runCurrent() 里跑掉，要等那一侧的调度器被推进才落到页面上 —— 这也正是真机上
        //    那句异常串没人盖回去的原因（交错探针 P2，`_tmp/test_round3/probe_out.txt`）。
        advanceUntilIdle()
        assertNull("被取消的取数把取消写成了页面级错误", vm.error)
        assertTrue("过期的那一趟把新一趟的加载态收掉了", vm.loading)

        second.complete(listOf(order(2))) // 新一趟先成功
        advanceUntilIdle()
        assertEquals(listOf(2L), vm.orders.map { it.id })

        first.complete(listOf(order(1))) // 过期那趟的数据**在成功之后**才到
        advanceUntilIdle()
        assertNull(vm.error)
        assertEquals("过期的那一趟把新一趟的结果顶掉了", listOf(2L), vm.orders.map { it.id })
        assertEquals(0, vm.ordersTab)
        assertFalse(vm.loading)
    }

    /** 真正的失败（网络/HTTP）照旧显示错误页 —— 本单不许把这条行为改差。 */
    @Test
    fun `真失败仍然显示错误页`() = runTest(main) {
        val vm = newViewModel { _, _, _ -> throw RuntimeException("网络断了") }
        runCurrent()
        assertEquals("网络断了", vm.error)
        assertFalse(vm.loading)
        assertFalse(vm.refreshing)
    }

    /** 错误页上的「重试」照旧能救回来：新一趟成功之后，错误串让位给列表。 */
    @Test
    fun `失败之后重试成功错误页让位给列表`() = runTest(main) {
        var fail = true
        val vm = newViewModel { _, _, _ -> if (fail) throw RuntimeException("网络断了") else listOf(order(7)) }
        runCurrent()
        assertNotNull(vm.error)

        fail = false
        vm.refresh() // ErrorView 的「重试」走的就是这条路（vm.load()）；顺带把 refreshing 也走一遍
        advanceUntilIdle()
        assertNull(vm.error)
        assertEquals(listOf(7L), vm.orders.map { it.id })
        assertFalse(vm.refreshing)
        assertFalse(vm.loading)
    }
}
