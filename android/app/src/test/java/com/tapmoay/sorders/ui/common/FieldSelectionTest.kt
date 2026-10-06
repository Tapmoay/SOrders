package com.tapmoay.sorders.ui.common

import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * 「聚焦即全选」（`FieldSelection.kt`）的 JVM 单测 —— 台账 L-25 / CHG-0059。
 *
 * 这里不渲染界面，只把**真机上那两下**用纯函数摆出来：框里放着 `1`（光标在末尾），
 * 点进去（[selectedAll]）⇒ 敲 `1`、敲 `5`。模拟输入法的是 [type]：把**选中区**换成
 * 刚敲的那个字符 —— 真机上 Compose 的 `CoreTextField` 就是这么干的。
 *
 * ⚠️ 为什么这条单测有价值：`typedQty` 那 8 条用例（`QtyStepperTest`）**全绿也照样有这个 bug** ——
 * 它们是纯函数，看不到"框里原来还剩着什么"。这个 bug 只活在"既有内容 ＋ 光标位置"里，
 * 所以这里钉的正是那一层。
 */
class FieldSelectionTest {

    /** 模拟输入法敲一个字符：选中区被替换掉，光标落在新字符之后。 */
    private fun type(v: TextFieldValue, s: String): TextFieldValue {
        val a = v.selection.min
        val b = v.selection.max
        return v.copy(
            text = v.text.replaceRange(a, b, s),
            selection = TextRange(a + s.length),
        )
    }

    @Test
    fun `点进去直接打 15 得到 15（不再是 115）`() {
        var field = fieldAtEnd("1")     // 框里原来那个 1（用户没改过 ⇒ 提交上去还是 1）
        field = selectedAll(field)      // 点进去 ⇒ 整串选中
        field = type(field, "1")        // 敲 1 ⇒ 把原来那个 1 换掉
        field = type(field, "5")        // 敲 5
        assertEquals("15", field.text)
        assertEquals(15, typedQty(field.text))
    }

    @Test
    fun `没去改就还是 1（默认值一个字没动）`() {
        val field = fieldAtEnd("1")
        assertEquals("1", field.text)
        assertEquals(1, typedQty(field.text))
    }

    @Test
    fun `旧病的样子被钉住：没选中时 1 再接 15 就是 115`() {
        // 这是修之前的现场（框里留着 1、光标在末尾，用户接着敲 1、5）——
        // 把它钉在这里：谁把"聚焦即全选"拿掉，这条与上面那条会一起说话。
        var field = fieldAtEnd("1")
        for (ch in "15") field = type(field, ch.toString())
        assertEquals("115", field.text)
        assertEquals(115, typedQty(field.text))
    }

    @Test
    fun `回填整串时光标放末尾`() {
        val field = fieldAtEnd("115")
        assertEquals("115", field.text)
        assertEquals(3, field.selection.min)
        assertEquals(3, field.selection.max)
    }

    @Test
    fun `全选覆盖整串（长度为 0 的空框也不炸）`() {
        val three = selectedAll(TextFieldValue("115", selection = TextRange(3)))
        assertEquals("115", three.text)
        assertEquals(0, three.selection.min)
        assertEquals(3, three.selection.max)
        assertEquals(0, selectedAll(TextFieldValue("")).selection.min)
    }

    @Test
    fun `全选幂等（已经全选再全选还是整串）`() {
        val once = selectedAll(fieldAtEnd("1234"))
        val twice = selectedAll(once)
        assertEquals(once.selection.min, twice.selection.min)
        assertEquals(once.selection.max, twice.selection.max)
    }

    @Test
    fun `夹好之后框里显示的与递出去的是同一个数`() {
        // 就是 QtyStepper 里那句归一：`typedQty` 的结果与框里的文本必须一致，
        // 否则会出现"框里写着 0、值却是 1"那种两处不一致。
        val raw = fieldAtEnd("0")   // 用户敲了个 0（下限是 1）
        val n = typedQty(raw.text)
        val shown = if (n.toString() == raw.text) raw else fieldAtEnd(n.toString())
        assertEquals(1, n)
        assertEquals("1", shown.text)
    }
}
