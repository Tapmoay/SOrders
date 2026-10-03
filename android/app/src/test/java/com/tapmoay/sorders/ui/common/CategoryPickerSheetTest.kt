package com.tapmoay.sorders.ui.common

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 「这个分类下有几个商品」怎么说（CHG-0028 / E2E 走查 P5）。
 *
 * 用户看到的矛盾：同一个事实两种措辞 —— 商品分类管理页写「暂无商品」，
 * 商品分组选择器里写「0 个商品」。这里钉的不是"函数能跑"，是**三种数量各说哪一句话**：
 * 有货就说几个、一个都没有就说「暂无商品」（⛔ 不说「0 个商品」）。
 *
 * 三个调用点（新增 / 编辑商品页、批量操作页、商品分类管理页）都走这一份 ——
 * 谁自己拼一份，判据 _tools/qa/_check_wording_consistency.py 会红。
 */
class CategoryPickerSheetTest {

    @Test
    fun `有商品就说有几个`() {
        assertEquals("1 个商品", categoryCountLabel(1))
        assertEquals("3 个商品", categoryCountLabel(3))
        assertEquals("128 个商品", categoryCountLabel(128))
    }

    @Test
    fun `一个都没有时说「暂无商品」，不说「0 个商品」`() {
        assertEquals("暂无商品", categoryCountLabel(0))
    }
}
