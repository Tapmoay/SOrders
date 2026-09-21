package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「规格 → 给模型看的参数表」这件事**只有一份实现**（`AiWrite.kt` 的 [crudParams] 与
 * [AiFieldSpec.paramKind]）。
 *
 * ### 为什么要专门给它写测试
 * 两个声明式工厂（`AiWriteMasterData` / `AiWriteBasicData` 的 `crud`）原来**各自抄了一遍**
 * 这段推导。它不是纯内部管道——产物会**贴给模型看**（[AiWrites.describeForModel] 里那句
 * `${p.kind.cn}`）。两份走散之后，同一种字段类型在两组动作里就是两种说法：模型按一处写、
 * 另一处不认，而**两边都不报错**（表现只是"参数传得不对"）。
 *
 * 所以这里钉三件事：
 * ① 八个字段类型的映射逐个钉住（改它必须是有意的，不许有"默认落文本"这种静默兜底）；
 * ② 参数表的构成（先目标、后字段；**目标恒为文本**，进 payload 的键名不许出现在参数表里）；
 * ③ **模型真正看到的那句话**就是这份映射渲染出来的，不是另有一条渲染路径。
 */
class AiWriteParamsTest {

    private fun field(type: AiFieldType, name: String = "x", cn: String = "某字段") =
        AiFieldSpec(name, cn, type, "说明")

    @Test
    fun `八个字段类型给模型看的类型逐个钉住`() {
        val expected = mapOf(
            AiFieldType.TEXT to AiWriteParamKind.TEXT,
            AiFieldType.MONEY to AiWriteParamKind.NUMBER,
            AiFieldType.COUNT to AiWriteParamKind.NUMBER,
            AiFieldType.DELTA to AiWriteParamKind.NUMBER,
            AiFieldType.NON_NEGATIVE to AiWriteParamKind.NUMBER,
            AiFieldType.DATE to AiWriteParamKind.DATE,
            // 是/否走**文本**：模型传的是 "true"/"false" 字符串，不是 JSON 布尔
            AiFieldType.BOOL to AiWriteParamKind.TEXT,
            AiFieldType.ENUM to AiWriteParamKind.ENUM,
        )
        assertEquals("字段类型表变了，期望表要一起改", AiFieldType.entries.toSet(), expected.keys)
        expected.forEach { (type, kind) ->
            assertEquals("$type 映射给模型的类型不对", kind, field(type).paramKind())
        }
    }

    @Test
    fun `参数表先目标后字段，目标恒为文本`() {
        val params = crudParams(
            targets = listOf(
                AiTargetSpec(
                    param = "product", cn = "商品", key = "product_id",
                    hint = "商品名，如「红富士苹果」", lookup = { _, _ -> emptyList() },
                ),
            ),
            fields = listOf(
                field(AiFieldType.MONEY, "price", "售价"),
                field(AiFieldType.DATE, "day", "日期"),
            ),
        )
        assertEquals(listOf("product", "price", "day"), params.map { it.name })
        // 模型给的是**名字**，编号由 App 解析；写成数字它会直接吐一个编号过来
        assertEquals(AiWriteParamKind.TEXT, params[0].kind)
        assertTrue("目标默认必填", params[0].required)
        assertEquals("商品名，如「红富士苹果」", params[0].hint)
        // 进 payload 的键名（product_id）不许出现在参数表里：那是 App 内部的事
        assertTrue("进 payload 的键名不该进参数表", params.none { it.name == "product_id" })
        assertEquals(listOf(AiWriteParamKind.NUMBER, AiWriteParamKind.DATE), params.drop(1).map { it.kind })
    }

    @Test
    fun `必填 提示 与枚举取值原样带过去`() {
        val f = AiFieldSpec(
            "vehicle", "车型", AiFieldType.ENUM, "可选",
            required = true,
            enumValues = listOf("small", "large"),
            aliases = mapOf("小货" to "small"),
        )
        val p = crudParams(emptyList(), listOf(f)).single()
        assertEquals(AiWriteParamKind.ENUM, p.kind)
        assertTrue(p.required)
        assertEquals("可选", p.hint)
        assertEquals(listOf("small", "large"), p.enumValues)
    }

    /**
     * 端到端那一步：说明书里印出来的就是这份映射的产物。
     *
     * 三句各代表一类：**金额 → 数字**（`freight_template.create` 的运费）、
     * **枚举 → 枚举 + 取值**（同一动作的车型）、**是/否 → 文本**（`address.create` 的设为默认）。
     * 这两条动作一个走 `AiWriteBasicData` 的工厂、一个也走它，但映射一旦被搬回文件里各写一份，
     * 只要有一份改了，这里就会红。
     */
    @Test
    fun `模型看到的那句话就是这份映射渲染出来的`() {
        val text = AiWrites.describeForModel()
        assertTrue("金额字段在提示词里该写成「数字」", text.contains("fee=运费（元）（必填，数字）"))
        assertTrue(
            "枚举字段该把取值一起印出来",
            text.contains("vehicle=车型（可选，枚举，取值 small/large/trailer）"),
        )
        assertTrue("是/否字段该写成「文本」", text.contains("default=设为默认（可选，文本）"))
    }
}
