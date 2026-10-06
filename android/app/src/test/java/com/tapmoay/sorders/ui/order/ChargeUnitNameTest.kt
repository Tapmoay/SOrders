package com.tapmoay.sorders.ui.order

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 台账 L-29：挂账时「新建单位」框预填谁的名字，以及"名字很像但不是同一个"要不要提示。
 *
 * 为什么值得单测：预填错了的后果**不是报错，而是欠款挂到别人头上**
 * （用户原话：「如果是按照**下单人**来进行挂账的；如果**没有下单人、只有收货人**，
 * 那就按**收货人**」）；而"相近名"提示宽窄都不行 —— 宽了天天弹（用户就不看了），
 * 窄了等于没有（那正是用户要防的"一个空格变成两个单位"）。
 */
class ChargeUnitNameTest {

    @Test
    fun `预填优先下单人`() {
        assertEquals("下单人甲", defaultArrearsUnitName("下单人甲", "收货人乙"))
    }

    @Test
    fun `没有下单人就用收货人`() {
        assertEquals("收货人乙", defaultArrearsUnitName("", "收货人乙"))
        assertEquals("收货人乙", defaultArrearsUnitName(null, "收货人乙"))
        assertEquals("收货人乙", defaultArrearsUnitName("   ", " 收货人乙 "))
    }

    @Test
    fun `两个都空就留空（不编名字）`() {
        assertEquals("", defaultArrearsUnitName(null, null))
        assertEquals("", defaultArrearsUnitName("  ", ""))
    }

    @Test
    fun `只差空格要提示（后端只 strip 首尾，中间那个空格会变成第二个单位）`() {
        assertEquals("永盛食品", similarArrearsUnitName("永盛 食品", listOf("永盛食品")))
    }

    @Test
    fun `只差一个字要提示（长度相同，长度至少 2）`() {
        assertEquals("文天祥", similarArrearsUnitName("文天翔", listOf("文天祥")))
    }

    @Test
    fun `完全同名不算相近（后端会直接复用）`() {
        assertNull(similarArrearsUnitName("永盛食品", listOf("永盛食品")))
    }

    @Test
    fun `差得多就不提示（前缀相同也不提示：可能是两家）`() {
        assertNull(similarArrearsUnitName("永盛", listOf("永盛食品厂")))
        assertNull(similarArrearsUnitName("永盛食品厂", listOf("永盛")))
        assertNull(similarArrearsUnitName("文天祥", listOf("陈国强")))
        // 差两个字也不提示（⚠️ 别拿"文天强"举例：它与"文天祥"只差一个字，
        // 按上面那条用例的规则本来就该提示）
        assertNull(similarArrearsUnitName("文天祥", listOf("陈国祥")))
    }

    @Test
    fun `空输入不算相近`() {
        assertNull(similarArrearsUnitName("", listOf("永盛食品")))
        assertNull(similarArrearsUnitName("   ", listOf("永盛食品")))
    }
}
