package com.tapmoay.sorders.ai

import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * **AI 读手机定位 + 按当前位置选点**（2026-09-21 用户要求）。
 *
 * 用户原话：「ai 它要具备读取手机的地点的能力，因为 ai 它是要具备所有功能…包括用户不是我们要去
 * 手动选地点吗？它也可以去选地点，**这个权限给它开啊**」。
 *
 * 这一族最容易坏掉的地方**都不会报错**，所以每条都钉住：
 * 1. **坐标泄漏进模型上下文**（本仓第一条硬规矩）——只能回地址文字；
 * 2. **拿不到定位时编一个地址出来** —— 三种失败各有一句话，且都不许有 `address`；
 * 3. **句柄「当前位置」落到地理编码那条路上** —— 地址文字是逆地理出来的，
 *    再正向查一次会**漂点**，而用户要的是"和手动选点一样准"；这条用"地理编码一次都没被调"来证；
 * 4. **本机能力绕过角色/模块那两道门** —— 它是隐私，用户必须关得掉；
 * 5. **参数说明里承诺了句柄、动作却不解析它** —— 那样会把字面量「当前位置」写进地址库。
 */
class AiLocalReadsTest {

    private val json = Json { ignoreUnknownKeys = true }

    // ------------------------------------------------------------------ 替身

    /** 假定位：给一个**一眼能认出来**的坐标，用来证明它没出现在输出里。 */
    private class FakeLocation(
        private val permitted: Boolean = true,
        private val place: AiPlace? = HUIZHOU,
    ) : AiLocationProvider {
        var calls = 0
        override fun permitted(): Boolean = permitted
        override suspend fun current(): AiPlace? {
            calls++
            return place
        }
    }

    /** 没授权：**连要都不该去要**（高德在没权限时一个回调都不会有 → 白等 8 秒）。 */
    private class DeniedLocation : AiLocationProvider {
        override fun permitted(): Boolean = false
        override suspend fun current(): AiPlace? = error("没授权就不该发起定位")
    }

    private fun action(): ReadAction = AiLocalReads.find(AiLocalReads.CURRENT_LOCATION)!!

    private fun parse(s: String): JsonObject = json.parseToJsonElement(s) as JsonObject

    // ------------------------------------------------- ① 句柄的字面量

    @Test
    fun `句柄认的就是那四个字（前后空白也算，别的都不算）`() {
        assertTrue(AiLocation.isHere("当前位置"))
        assertTrue("模型可能带空白", AiLocation.isHere("  当前位置 "))
        assertFalse(AiLocation.isHere("惠州市惠城区麦地路 11 号"))
        assertFalse("少一个字不算", AiLocation.isHere("位置"))
        assertFalse(AiLocation.isHere(null))
        assertFalse(AiLocation.isHere(""))
    }

    @Test
    fun `参数提示里那句「当前位置」与哨兵是同一个字面量（改了一处必须另一处跟着）`() {
        // 提示是拼给模型看的，哨兵是 App 认的 —— 两边走散的症状是"模型照说明填了，
        // App 不认，于是把四个字当地址写进去"，而且**不报错**。
        assertTrue("HERE_HINT 里没带上哨兵：$HERE_HINT", HERE_HINT.contains(AiLocation.HERE))
    }

    // ------------------------------------------------- ② 只回文字、坐标不外泄

    @Test
    fun `读到位置时只回地址文字，坐标一个都不进模型可见的输出`() = runBlocking {
        val out = AiLocalReads.run(action(), FakeLocation())
        val obj = parse(out)
        assertEquals(HUIZHOU.address, (obj["address"] as JsonPrimitive).content)

        // ① 不许有坐标键（换任何名字都不行）
        listOf("lat", "lng", "latitude", "longitude", "address_lat", "address_lng", "coord", "坐标")
            .forEach { key -> assertNull("输出里出现了坐标键「$key」：$out", obj[key]) }
        // ② 不许有**小数形式的坐标串**（换个键名塞进去也会被这条抓住）
        assertFalse("输出里出现了小数形式的坐标：$out", DECIMAL_COORD.containsMatchIn(out))
        // ③ 也不许把数字塞进别的字段里
        assertFalse("纬度漏进输出了：$out", out.contains("23.1"))
        assertFalse("经度漏进输出了：$out", out.contains("114.1"))
    }

    @Test
    fun `读到的地址必须是这一次的（不许拿历史位置糊弄）`() = runBlocking {
        val fake = FakeLocation()
        AiLocalReads.run(action(), fake)
        assertEquals("每次问都要现取一次（不许缓存上一轮的位置）", 1, fake.calls)
    }

    // ------------------------------------------------- ③ 三种失败：各有各的话，且都不许编地址

    @Test
    fun `没授权时说清去哪儿开权限（并明说没有地址）`() = runBlocking {
        val out = AiLocalReads.run(action(), DeniedLocation())
        val obj = parse(out)
        assertNull("没授权却回了地址：$out", obj["address"])
        val err = (obj["error"] as JsonPrimitive).content
        assertTrue("要告诉他去哪开：$err", err.contains("设置"))
        assertTrue("要告诉他开哪个权限：$err", err.contains("权限"))
    }

    @Test
    fun `这次没定位到时如实说，不编地址`() = runBlocking {
        val out = AiLocalReads.run(action(), FakeLocation(place = null))
        val obj = parse(out)
        assertNull("没定位到却回了地址：$out", obj["address"])
        assertTrue((obj["error"] as JsonPrimitive).content.contains("没拿到定位"))
        assertFalse("没有地址时不许出现小数坐标：$out", DECIMAL_COORD.containsMatchIn(out))
    }

    @Test
    fun `没有定位能力时（单测或没接 Context）也如实说`() = runBlocking {
        val out = AiLocalReads.run(action(), null)
        val obj = parse(out)
        assertNull(obj["address"])
        assertTrue((obj["error"] as JsonPrimitive).content.contains("读不到"))
    }

    // ------------------------------------------------- ④ 与后端表同一道门（角色 + 模块）

    @Test
    fun `本机能力按角色给：派单员和货主都有，认不出角色一个都不给`() {
        val dispatcher = AiActor.byRole(AiRole.DISPATCHER)!!
        val shipper = AiActor.byRole(AiRole.SHIPPER)!!
        assertTrue(AiReads.allows(dispatcher, AiLocalReads.CURRENT_LOCATION))
        assertTrue("货主也要能问「我在哪」", AiReads.allows(shipper, AiLocalReads.CURRENT_LOCATION))
        assertFalse("认不出角色＝一张表都不给（fail-closed）", AiReads.allows(null, AiLocalReads.CURRENT_LOCATION))
    }

    @Test
    fun `关掉定位模块之后，读侧的门和工具说明一起收掉`() {
        val dispatcher = AiActor.byRole(AiRole.DISPATCHER)!!
        val onlyOrders = setOf("orders")
        assertFalse(
            "模块关了却还能调 = 用户以为关掉了（这是隐私）",
            AiReads.allows(dispatcher, AiLocalReads.CURRENT_LOCATION, onlyOrders),
        )
        assertFalse(AiReads.forRole(dispatcher, onlyOrders).any { it.path.isBlank() })
        assertTrue(AiReads.forRole(dispatcher, onlyOrders).isNotEmpty())
    }

    @Test
    fun `模块清单里必须有 location（否则这个开关根本不存在）`() {
        // 白名单是从 `AiReads.allModules()` 算的：少了这个键，本机能力会被**静默过滤掉**
        // （用户没配过开关时默认全开、配过一次就永远开不回来），两种都不报错。
        assertTrue("location 不在模块清单里", AiReads.allModules().contains(AiLocalReads.MODULE_LOCATION))
        assertEquals("手机定位", AiReads.moduleCn(AiLocalReads.MODULE_LOCATION))
    }

    @Test
    fun `工具说明里标出这是本机能力（否则模型会拿它当一张地址表）`() {
        val d = AiReads.describeForModel(AiActor.byRole(AiRole.DISPATCHER)!!)
        assertTrue(d.contains(AiLocalReads.CURRENT_LOCATION))
        assertTrue("没标「本机」：$d", d.contains("〔本机"))
    }

    @Test
    fun `本机能力的执行不查后端（它的 path 是空的）`() {
        assertTrue("path 必须为空，否则执行侧会去发一个不存在的请求", action().path.isBlank())
        assertTrue(action().params.isEmpty())
        assertTrue(AiLocalReads.find("location.current") != null)
        assertNull(AiLocalReads.find("orders.list_orders"))
    }

    // ------------------------------------------------- ⑤ 写侧：句柄走定位，绝不落到地理编码

    @Test
    fun `句柄走定位：真实地址与精确坐标一起拿到，且地理编码一次都没被调`() = runBlocking {
        var geocoded = 0
        val fix = AiLocation.resolveAddress(AiLocation.HERE, FakeLocation()) { geocoded++; null }
        assertEquals("句柄不许落到地理编码那条路（那会漂点）", 0, geocoded)
        assertNotNull(fix)
        assertEquals(HUIZHOU.address, fix!!.address)
        assertEquals(HUIZHOU.lat, fix.lat, 1e-9)
        assertEquals(HUIZHOU.lng, fix.lng, 1e-9)
    }

    @Test
    fun `普通地址仍然走高德地理编码（文字原样，坐标来自高德）`() = runBlocking {
        val fix = AiLocation.resolveAddress("惠州市惠城区麦地路 11 号", FakeLocation()) { 23.5 to 114.5 }
        assertEquals("写进地址栏的还是用户说的那句话", "惠州市惠城区麦地路 11 号", fix!!.address)
        assertEquals(23.5, fix.lat, 1e-9)
        assertEquals(114.5, fix.lng, 1e-9)
    }

    @Test
    fun `拿不到定位时句柄被拒（不弹卡），而且给的是「去开权限」不是「地址说完整点」`() {
        val e = assertThrows(AiWriteArgException::class.java) {
            runBlocking { AiLocation.resolveAddress(AiLocation.HERE, DeniedLocation()) { 1.0 to 2.0 } }
        }
        val m = e.message.orEmpty()
        assertTrue("要指到系统设置：$m", m.contains("设置"))
        assertFalse("这两句话不能混：$m", m.contains("说得更完整"))
    }

    @Test
    fun `没有定位提供者时句柄也被拒（宁可说读不到，也不写四个字进去）`() {
        val e = assertThrows(AiWriteArgException::class.java) {
            runBlocking { AiLocation.resolveAddress(AiLocation.HERE, null) { 1.0 to 2.0 } }
        }
        assertTrue(e.message.orEmpty().contains("读不到"))
    }

    @Test
    fun `数据源的默认实现也认这个句柄（单测替身不会把四个字当地址存下去）`() = runBlocking {
        // 替身只实现 `geocode`、没有定位提供者 —— 默认实现必须把句柄**拒掉**，
        // 而不是原样当成一个地址返回（那正是"四个字写进地址库"那条路）。
        // ⚠️ 这条靠的是 [AiLocation.resolveAddress] 被默认实现调用，红线里另有一条钉住源码形状。
        assertNull("默认实现不该认字面量", AiLocation.resolveAddress("惠州市麦地路 1 号", null) { null })
        val e = assertThrows(AiWriteArgException::class.java) {
            runBlocking { AiLocation.resolveAddress(AiLocation.HERE, null) { 1.0 to 2.0 } }
        }
        assertTrue("默认实现必须把句柄拒掉：${e.message}", e.message.orEmpty().contains("读不到"))
    }

    // ------------------------------------------------- ⑥ 说明里承诺了句柄，就必须真的解析它

    @Test
    fun `参数说明里让模型填「当前位置」的动作，必须真的会解析这个句柄`() {
        // 反例的后果：模型照说明填了四个字，动作不认 → **字面量「当前位置」被写进地址库**，
        // 不报错，而司机导航到一个叫"当前位置"的地方。
        val handled = setOf(AiWrites.ORDERS_CREATE, AiWrites.ORDERS_UPDATE)
        val promised = AiWrites.ALL.filter { a -> a.params.any { it.hint.contains(AiLocation.HERE) } }
        assertTrue("一个都没承诺？那说明提示没加上（这条检查会空转）", promised.isNotEmpty())
        promised.forEach { a ->
            assertTrue(
                "「${a.title}」的参数说明里让模型填「${AiLocation.HERE}」，但它既不 geocodeFrom 也不是手写解析地址的动作",
                a.crud?.geocodeFrom != null || a.id in handled,
            )
        }
    }

    // ------------------------------------------------- ⑦ 老白名单必须补上新模块

    /**
     * 用户拍板：「ai 它要具备读取手机的地点的能力……**这个权限给它开啊**」——
     * 更新完就该能用，不许让老用户自己去设置页里翻出那个新开关。
     *
     * 三条语义（本节前三条）+ 三条边界，每一条都能单独坏掉。
     * 规则本身是纯函数 [AiReads.resolveEnabled]：`AiKeyStore` 那一层只有 SharedPreferences，测不动。
     */
    @Test
    fun `从没配过模块开关的设备，定位默认是开的`() {
        // 对应 `AiKeyStore.enabledReadModules()` 里"没有这个键 → 返回全集"那个分支
        // （那一层读的是 SharedPreferences，纯 JVM 单测起不来）。这里钉的是它**算出来的结果**：
        // 全集含 location，而 forRole 的默认参数就是全集 → 定位真的在可读清单里。
        assertTrue(AiLocalReads.MODULE_LOCATION in AiReads.allModules())
        assertTrue(
            AiReads.forRole(AiActor.byRole(AiRole.DISPATCHER)!!).any { it.action == AiLocalReads.CURRENT_LOCATION },
        )
    }

    @Test
    fun `更新前配过白名单的设备，定位要自动补上（用户：这个权限给它开啊）`() {
        // 他保存那份白名单时 location **还不存在**，谈不上"他把它关了"。
        val saved = setOf("orders", "products")
        val effective = AiReads.resolveEnabled(saved, knownAtSave = null)
        assertTrue("更新完就该能用：$effective", AiLocalReads.MODULE_LOCATION in effective)
        assertEquals("别的模块一个都不许多给", saved + AiLocalReads.MODULE_LOCATION, effective)
    }

    @Test
    fun `更新之后明确关掉手机定位，必须记住是关的`() {
        // 语义 3：这一刻 location 已经在"保存时已知"里了，所以它**不是**新出现的。
        val knownNow = AiReads.allModules().toSet()
        val saved = knownNow - AiLocalReads.MODULE_LOCATION
        val effective = AiReads.resolveEnabled(saved, knownAtSave = knownNow)
        assertFalse("他关掉的又自己开了：$effective", AiLocalReads.MODULE_LOCATION in effective)
        assertEquals(saved, effective)
    }

    @Test
    fun `保存之后新加的模块都会自动补上（不是只救 location 这一次）`() {
        // 泛化：标记存的是**全集**，所以以后再加模块不用重复踩这个坑。
        val knownAtSave = setOf("orders", "products", "customers")
        val saved = setOf("orders")            // products / customers 是他明确关掉的
        val effective = AiReads.resolveEnabled(saved, knownAtSave = knownAtSave)
        assertTrue("orders 还开着", "orders" in effective)
        assertFalse("他明确关掉的 products 不许补回来：$effective", "products" in effective)
        assertFalse("他明确关掉的 customers 不许补回来：$effective", "customers" in effective)
        assertTrue("保存之后出现的 location 要补上", AiLocalReads.MODULE_LOCATION in effective)
    }

    @Test
    fun `老数据里把模块全关了的，不会因为这次更新又被打开`() {
        // ⚠️ 刻意的一处"往保守那头倒"：老约定里**空串 = 用户主动全关**（不是"我列的这些关掉"）。
        //    把空集当"枚举"去补新模块，等于把用户明确关掉的东西又打开 —— 而这次关的是**隐私**。
        //    用户那三条语义说的是"配过一份白名单"的设备；"一条都不留"是另一回事。
        assertTrue(
            "空集被补了新模块：${AiReads.resolveEnabled(emptySet(), knownAtSave = null)}",
            AiReads.resolveEnabled(emptySet(), knownAtSave = null).isEmpty(),
        )
        // 带标记的空集同理（他刚在设置页把最后一个开关也关了）
        assertTrue(AiReads.resolveEnabled(emptySet(), knownAtSave = AiReads.allModules().toSet()).isEmpty())
    }

    @Test
    fun `老数据不补后端模块（没有标记就分不出他关掉的与当时还不存在的）`() {
        // 没有标记时**只能**确定"本机能力"这一类是后加的；后端模块乱补就是上一条那个错。
        val saved = setOf("orders")
        val effective = AiReads.resolveEnabled(saved, knownAtSave = null)
        assertEquals(setOf("orders", AiLocalReads.MODULE_LOCATION), effective)
    }

    private companion object {
        val HUIZHOU = AiPlace("广东省惠州市惠城区麦地路 11 号", 23.1234567, 114.1234567)

        /** 小数形式的坐标串（`23.1234567` 这种）。地址里不会出现 3 位以上的小数。 */
        val DECIMAL_COORD = Regex("""\d{1,3}\.\d{3,}""")
    }
}
