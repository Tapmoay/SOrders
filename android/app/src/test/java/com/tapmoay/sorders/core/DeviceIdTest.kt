package com.tapmoay.sorders.core

import com.tapmoay.sorders.data.remote.api.DeviceApi
import com.tapmoay.sorders.data.remote.dto.DeviceRegisterRequest
import com.tapmoay.sorders.data.remote.dto.DeviceRegisterResponse
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

/**
 * 设备标识（FEAT-0018）：`install_id` 的生成/持久化与 `X-Device-Id` 的拼装。
 *
 * 这一单为什么值得测：`X-Device-Id` 错了不会报错 —— 后端只会把请求当成"没有设备信息"，
 * 表现是"风控像没生效一样"（或者反过来，把正常用户拦在门外）。而 `install_id` 一旦每次启动
 * 重新生成，一台手机在后台眼里就成了**无数台设备**，会把账号的名额吃光 —— 这类缺陷在界面上
 * 完全看不出来，只有把"同一实例稳定 / 清数据才变化"钉成断言才拦得住。
 *
 * ⚠️ 测的是 [DeviceIdStore] 这层接口（不是 DataStore 本体）：`PrefsDeviceIdStore` 落的是
 *    App 私有目录，JVM 单测里没有 Context；"重装 = 换一台设备"用**换一个空 store**来模拟。
 */
class DeviceIdTest {

    /** 内存版盘（语义与 `PrefsDeviceIdStore` 对齐：token 传 null = 不改动已有的 token）。 */
    private class MemStore(var prefs: DevicePrefs = DevicePrefs()) : DeviceIdStore {
        var writes = 0
        override suspend fun read(): DevicePrefs = prefs
        override suspend fun write(installId: String, token: String?) {
            writes++
            prefs = DevicePrefs(installId, token ?: prefs.token)
        }
    }

    /** 假后端：`POST /devices/register`。 */
    private class FakeApi(
        var deviceId: String? = null,
        var token: String = "tok-abc",
        var fail: Boolean = false,
    ) : DeviceApi {
        var calls = 0
        var lastBody: DeviceRegisterRequest? = null
        override suspend fun register(body: DeviceRegisterRequest): DeviceRegisterResponse {
            calls++
            lastBody = body
            if (fail) throw IOException("假装后端不可达")
            return DeviceRegisterResponse(deviceId = deviceId ?: body.installId, token = token)
        }
    }

    @Test
    fun `install_id 生成一次就稳定（同一实例问几次都是同一个）`() = runTest {
        val store = MemStore()
        val dev = DeviceId(store)
        val first = dev.ensureInstallId()
        assertEquals(first, dev.ensureInstallId())
        assertEquals(first, dev.ensureInstallId())
        assertEquals("生成的 install_id 必须落盘（不落盘 = 每次启动换一台设备）", first, store.prefs.installId)
    }

    @Test
    fun `生成的形状是 UUID，长度落在后端接受的 8~64 位里`() = runTest {
        val id = DeviceId(MemStore()).ensureInstallId()
        assertTrue("install_id 不能短于 8 位：$id", DeviceIdentity.isValidInstallId(id))
        assertEquals("必须是标准 UUID 形状", 36, id.length)
    }

    @Test
    fun `关掉 App 再打开：同一个盘拿到同一个 install_id`() = runTest {
        val store = MemStore()
        val first = DeviceId(store).ensureInstallId()
        // 换一个实例 = 进程重启；盘还是那一块
        val second = DeviceId(store).ensureInstallId()
        assertEquals(first, second)
        assertEquals("重启不应该再写一次盘", 1, store.writes)
    }

    @Test
    fun `清掉数据（换一块空盘）之后算另一台设备`() = runTest {
        val first = DeviceId(MemStore()).ensureInstallId()
        val second = DeviceId(MemStore()).ensureInstallId()
        assertNotEquals("清数据后必须换一个新 id（否则名额算不清）", first, second)
    }

    @Test
    fun `没注册成功之前不发 X-Device-Id（半截值不发）`() = runTest {
        val dev = DeviceId(MemStore())
        assertNull("install_id 都还没有", dev.headerValue())
        dev.ensureInstallId()
        assertNull("有 install_id 但还没有 token：半截值不许发出去", dev.headerValue())
    }

    @Test
    fun `注册成功后请求头就是 install_id 冒号 token`() = runTest {
        val store = MemStore()
        val api = FakeApi()
        val dev = DeviceId(store)
        assertTrue(dev.ensureRegistered(api))
        val id = dev.ensureInstallId()
        assertEquals("发给后端的必须是这一台自己的 install_id", id, api.lastBody?.installId)
        assertEquals(id + ":" + api.token, dev.headerValue())
        assertEquals("token 必须落盘（否则每次启动都重新注册一台设备）", api.token, store.prefs.token)
    }

    @Test
    fun `重启后带着盘里的 token 直接发头，不再打注册接口`() = runTest {
        val store = MemStore()
        val api = FakeApi()
        assertTrue(DeviceId(store).ensureRegistered(api))
        assertEquals(1, api.calls)

        val restarted = DeviceId(store)
        restarted.warmCache()
        assertTrue("已经有 token 就不该再注册", restarted.ensureRegistered(api))
        assertEquals("重启后又打了一次注册接口", 1, api.calls)
        assertEquals(store.prefs.installId + ":" + api.token, restarted.headerValue())
    }

    @Test
    fun `后端回的 device_id 与本地不一致时以后端为准`() = runTest {
        val store = MemStore()
        // 后端可能把 install_id 归一化/改写成它自己发的号 —— 之后所有请求都要跟它一致，
        // 否则"注册时说 A、请求时说 B"，后端按 B 查不到设备，风控就静默失效了。
        val api = FakeApi(deviceId = "server-assigned-device-id")
        val dev = DeviceId(store)
        assertTrue(dev.ensureRegistered(api))
        assertEquals("server-assigned-device-id:tok-abc", dev.headerValue())
        assertEquals("server-assigned-device-id", store.prefs.installId)
    }

    @Test
    fun `注册失败不许抛异常、也不许阻塞使用（返回 false，下次再来）`() = runTest {
        val store = MemStore()
        val api = FakeApi(fail = true)
        val dev = DeviceId(store)
        assertFalse("离线/后端不可达时要安静地 false", dev.ensureRegistered(api))
        assertNull("失败了就不发头（宁可不带，也不发半截值）", dev.headerValue())
        assertEquals("install_id 仍然要留下来，下次直接用", 1, store.writes)
    }

    @Test
    fun `冷却期内不重复打接口，过了冷却才重试`() = runTest {
        var now = 1_000_000L
        val api = FakeApi(fail = true)
        val dev = DeviceId(MemStore()) { now }
        assertFalse(dev.ensureRegistered(api))
        assertEquals(1, api.calls)
        assertFalse(dev.ensureRegistered(api))
        assertEquals("冷却期内不该再打（拦截器每次请求都会来问一次）", 1, api.calls)
        now += DeviceId.RETRY_COOLDOWN_MS + 1
        assertFalse(dev.ensureRegistered(api))
        assertEquals("过了冷却才允许重试", 2, api.calls)
    }

    @Test
    fun `落盘失败也不崩（内存里记住，下次再说）`() = runTest {
        val store = object : DeviceIdStore {
            override suspend fun read(): DevicePrefs = DevicePrefs()
            override suspend fun write(installId: String, token: String?) = throw IOException("盘写不进去")
        }
        val dev = DeviceId(store)
        val id = dev.ensureInstallId()
        assertTrue(DeviceIdentity.isValidInstallId(id))
    }

    @Test
    fun `请求头取值的边界：太少太长或没 token 都不发`() {
        assertEquals("abcdefgh:tok", DeviceIdentity.headerValue("abcdefgh", "tok"))
        assertEquals("64 位也要收", "a".repeat(64) + ":tok", DeviceIdentity.headerValue("a".repeat(64), "tok"))
        assertNull("7 位太短", DeviceIdentity.headerValue("a".repeat(7), "tok"))
        assertNull("65 位太长", DeviceIdentity.headerValue("a".repeat(65), "tok"))
        assertNull("没有 install_id", DeviceIdentity.headerValue(null, "tok"))
        assertNull("没有 token", DeviceIdentity.headerValue("abcdefgh", null))
        assertNull("空 token", DeviceIdentity.headerValue("abcdefgh", ""))
    }

    @Test
    fun `头名字是后端契约里的那一个`() {
        assertEquals("X-Device-Id", DeviceIdentity.HEADER)
    }
}