package com.tapmoay.sorders.ui.shipper

import com.tapmoay.sorders.data.remote.dto.UserDto
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 「下单人」该填谁（`ordererContactFor`）。
 *
 * ⚠️ 这里钉的是**静态的判据**，真机那一步（选货主之后界面上真的变了）另算 —— 但这两条
 * 缺一不可：判据错了，真机上"看起来对"的那个值也只是碰巧。
 *
 * 最要紧的两条：**派单员一个货主都没选时留空**（不能回落成他自己），
 * 以及**换货主时电话要跟着换**（留着上一位的号 = 打过去是别人）。
 */
class OrdererPrefillTest {

    private fun shipper(
        id: Long = 7,
        name: String = "永盛食品",
        phone: String = "13800000002",
    ) = UserDto(id = id, username = phone, phone = phone, fullName = name, role = "shipper")

    @Test
    fun `货主自己下单 —— 填自己（与 09-20 那条口径一致）`() {
        val c = ordererContactFor(
            ownName = "张三",
            ownPhone = "13900001111",
            proxyMode = false,
            shipper = null,
            tempShipperName = null,
        )
        assertEquals("张三", c.name)
        assertEquals("13900001111", c.phone)
    }

    @Test
    fun `批发商自己下单 —— 同一套规则，不看 is_member`() {
        val c = ordererContactFor(
            ownName = "永盛食品",
            ownPhone = "13800000002",
            proxyMode = false,
            shipper = null,
            tempShipperName = null,
        )
        assertEquals("永盛食品", c.name)
        assertEquals("13800000002", c.phone)
    }

    @Test
    fun `派单员选了货主 —— 填那位货主的姓名与电话`() {
        val c = ordererContactFor(
            ownName = "派单员",
            ownPhone = "15070334563",
            proxyMode = true,
            shipper = shipper(),
            tempShipperName = null,
        )
        assertEquals("永盛食品", c.name)
        assertEquals("13800000002", c.phone)
    }

    @Test
    fun `派单员换了货主 —— 电话跟着换（留着上一位的号就是打到别人那儿去了）`() {
        val c = ordererContactFor(
            ownName = "派单员",
            ownPhone = "15070334563",
            proxyMode = true,
            shipper = shipper(id = 8, name = "大发商行", phone = "13900002222"),
            tempShipperName = null,
        )
        assertEquals("大发商行", c.name)
        assertEquals("13900002222", c.phone)
    }

    @Test
    fun `派单员一个货主都没选 —— 留空，绝不回落成派单员自己`() {
        val c = ordererContactFor(
            ownName = "派单员",
            ownPhone = "15070334563",
            proxyMode = true,
            shipper = null,
            tempShipperName = null,
        )
        assertEquals("代理下单时下单人不是派单员，这里必须是空的", "", c.name)
        assertEquals("", c.phone)
    }

    @Test
    fun `派单员选临时货主 —— 只填姓名，电话留空（库里没有他的号）`() {
        val c = ordererContactFor(
            ownName = "派单员",
            ownPhone = "15070334563",
            proxyMode = true,
            shipper = null,
            tempShipperName = "李四",
        )
        assertEquals("李四", c.name)
        assertEquals("编一个号码比空着危险得多", "", c.phone)
    }

    @Test
    fun `从临时货主换回已注册货主 —— 姓名与电话都跟上`() {
        val c = ordererContactFor(
            ownName = "派单员",
            ownPhone = "15070334563",
            proxyMode = true,
            shipper = shipper(),
            tempShipperName = null,
        )
        assertEquals("永盛食品", c.name)
        assertEquals("13800000002", c.phone)
    }

    @Test
    fun `临时货主与已注册货主同时有值时，临时货主优先（界面上只能选一个）`() {
        val c = ordererContactFor(
            ownName = "派单员",
            ownPhone = "15070334563",
            proxyMode = true,
            shipper = shipper(),
            tempShipperName = "李四",
        )
        assertEquals("李四", c.name)
        assertEquals("", c.phone)
    }

    @Test
    fun `两端空格与 null 都被归一（不能填出一个只有空格的姓名）`() {
        val self = ordererContactFor("  张三 ", null, proxyMode = false, shipper = null, tempShipperName = null)
        assertEquals("张三", self.name)
        assertEquals("", self.phone)
        val proxy = ordererContactFor(
            null, null, proxyMode = true,
            shipper = shipper(name = "  永盛食品  ", phone = " 13800000002 "),
            tempShipperName = null,
        )
        assertEquals("永盛食品", proxy.name)
        assertEquals("13800000002", proxy.phone)
    }

    @Test
    fun `货主账号没填姓名时 —— 姓名留空但电话照填（别把号码塞进姓名栏）`() {
        val c = ordererContactFor(
            ownName = "派单员", ownPhone = "15070334563", proxyMode = true,
            shipper = shipper(name = "", phone = "13800000002"),
            tempShipperName = null,
        )
        assertEquals("", c.name)
        assertEquals("13800000002", c.phone)
    }
}
