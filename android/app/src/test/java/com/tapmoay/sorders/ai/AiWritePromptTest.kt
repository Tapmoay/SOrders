package com.tapmoay.sorders.ai

import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 贴给模型的 `preview_write` 说明书：**哪些参数约束真的进了上下文**。
 *
 * ## 为什么单独有一组用例（2026-09-24 第 22 轮 F1-D3）
 * `AiWriteParam.hint` 里写着参数的**真话** —— 但 `describeForModel` 只渲染
 * `name=cn（必填/可选，类型）`，**hint 一句都不进上下文**。169 条约束（≈1241 token）
 * 的唯一出口是"模型已经做错、系统拒了一次"之后的报错回显。
 *
 * 最危险的一条是钱的语义：`order_templates.create` 的 `freight_fee` 明写
 * 「**不填＝不预设**；填 0 才是免运费」，而模型只看到"（可选，数字）" ——
 * 用户说"不用预设运费"，它传 `0`，**这张预设单就真的变成免运费**。
 * 同族还有 `orders.assign.commission_rate`：「规则里没有提成项后端会拒绝」看不到，
 * 于是模型发出一张**必然失败**的卡。
 *
 * ## 判据为什么"能红"
 * ① 钱的约束必须在**那个动作自己的段落里**（不是全文任意位置）——
 *    把 hint 渲染到别处、或渲染了但与动作错位，这条都会红；
 * ② 可选的纯文本参数**不许**进上下文（省 token 的那一半也要钉住，
 *    否则"全带上"也能让 ① 变绿，而说明书会白白胖一倍）；
 * ③ 整份说明书有体积上限（打印实测值）—— 这条挡的是"下次谁顺手把全部 hint 都带上"。
 */
class AiWritePromptTest {

    private fun text(): String = AiWrites.describeForModel(AiActor.byRole(AiRole.DISPATCHER))

    /** 取某个动作在说明书里的那一小段（到下一个 `- 动作` 为止）。 */
    private fun block(full: String, actionId: String): String {
        val start = full.indexOf("- $actionId")
        assertTrue("说明书里找不到动作 $actionId", start >= 0)
        val next = full.indexOf("\n- ", start + 1)
        return if (next < 0) full.substring(start) else full.substring(start, next)
    }

    @Test
    fun `钱的语义必须进模型上下文（不填不等于填 0）`() {
        val full = text()
        val block = block(full, AiWrites.ORDER_TEMPLATE_CREATE)
        assertTrue(
            "预设运费的「不填＝不预设、填 0＝免运费」必须写在**这个动作自己的段落里**" +
                "（否则模型只看到「可选，数字」，会把用户说的「不用预设运费」写成 0 = 真的免运费）：\n$block",
            block.contains("不填＝不预设"),
        )
        assertTrue("运费的 hint 里还要写清 0 是什么意思：\n$block", block.contains("免运费"))
    }

    @Test
    fun `必填项的前置条件也必须进模型上下文`() {
        val full = text()
        val block = block(full, AiWrites.ORDERS_ASSIGN)
        assertTrue(
            "派单的提成比例有前置条件（规则里没有提成项后端会拒绝），必须让模型看到，" +
                "否则它会发一张必然失败的卡：\n$block",
            block.contains("提成") && block.contains("规则"),
        )
    }

    @Test
    fun `可选的纯文本参数不占上下文（省 token 的那一半）`() {
        val full = text()
        // `order_templates.create.remark` 的 hint 是「可选，一句话」——它没有任何歧义，
        // 不该占模型的上下文（带上它只说明"全带上"是默认行为，那会把说明书翻倍）。
        assertTrue(
            "可选的纯文本 hint 不该进上下文：\n${block(full, AiWrites.ORDER_TEMPLATE_CREATE)}",
            !full.contains("可选，一句话"),
        )
    }

    @Test
    fun `说明书体积有上限（防下次顺手全带上）`() {
        val actor = AiActor.byRole(AiRole.DISPATCHER)
        // 带进上下文的那些约束一共占多少字符（≈ 这次新增的固定开销）
        val added = AiWrites.forModel(actor).sumOf { a ->
            a.params
                .filter { it.hint.isNotBlank() && it.kind == AiWriteParamKind.NUMBER }
                .sumOf { it.name.length + minOf(it.hint.length, AiWrites.HINT_IN_PROMPT) + 3 } // `name：hint；`
        }
        val n = text().length
        // 打印实测值：这条判据的用途就是"变长时要有人解释"，所以数字要看得见。
        println("AI 说明书（派单员，全部工具开启）：整份 $n 字符；带进上下文的参数约束 $added 字符")
        assertTrue(
            "带进上下文的参数约束共 $added 字符（上限 2500；实测 1846。" +
                "必填 ∪ 钱的项要 7255 —— 差近 4 倍，所以闸门只认钱的项）；整份说明书 $n 字符",
            added in 1_000..2_500,
        )
        // 上限不是"越短越好"，是让**变长变成一个需要解释的动作**（实测 20766）。
        assertTrue("说明书太大：$n 字符（上限 23000）", n in 8_000..23_000)
        assertTrue("加上约束之后剩下的主体不该被挤没：$n - $added", n - added >= 8_000)
    }
}
