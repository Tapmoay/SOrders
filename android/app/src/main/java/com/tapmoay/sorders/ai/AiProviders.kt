package com.tapmoay.sorders.ai

/**
 * 内置的模型服务商预设。
 *
 * ### 为什么要有预设
 * 让派单员手填 Base URL 是不现实的（他连 App 都不熟，更不会知道"OpenAI 兼容端点"是什么）。
 * 预设把最容易填错的一格（地址）变成**点一下**，剩下的模型名交给「拉取模型列表」去选。
 *
 * ### 为什么预设里**只填地址、不填模型名**
 * 地址是稳定的（域名很少变），模型名不是：同一个厂商的可用模型随时间和账号权限变，
 * 猜一个写进去，用户点完预设第一句话就 400，还以为是 App 坏了。
 * 所以这里的做法是：**点预设 → 自动去拉模型列表 → 从真实候选里选一个**。
 * 唯一给了默认模型名的是 DeepSeek——那个是**实测能用**的（见 [AiKeyStore.DEFAULT_MODEL]）。
 *
 * ### 来源（写清楚，免得以后有人当成"凭印象写的"）
 * - 豆包（火山方舟）：`https://ark.cn-beijing.volces.com/api/v3`
 *   —— 火山引擎官方文档里区分了「普通 API」与「Coding Plan API」两套地址，
 *   两者不能混用（用错地址会走不到订阅额度还会额外计费），这里给的是**普通 API**。
 * - 千问（阿里云百炼）：`https://dashscope.aliyuncs.com/compatible-mode/v1`
 *   —— 官方文档同时说明：**北京地域正在从该域名迁到 `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com`**，
 *   且 **API Key 与地域绑定**（用别的地域的 key 调会被拒绝）。所以拉不到列表时，
 *   第一件事是去百炼控制台确认「当前地域的 base_url 与 key 是否匹配」，而不是怀疑 App。
 *
 * ⚠️ **硬性前提**：所选模型必须支持 **function calling（工具调用）**。
 * 本助手的全部能力都建立在工具调用上，不支持工具调用的模型只能闲聊、查不到任何业务数据。
 */
data class AiProvider(
    val label: String,
    val baseUrl: String,
    /** 设置页上给用户看的一句话（讲清最容易踩的坑）。 */
    val note: String,
) {
    /** 是否就是当前填的这个地址（用来高亮预设按钮）。 */
    fun matches(other: String): Boolean = normalize(other) == normalize(baseUrl)

    private fun normalize(u: String) = u.trim().trimEnd('/').lowercase()
}

object AiProviders {

    val DEEPSEEK = AiProvider(
        label = "DeepSeek",
        baseUrl = "https://api.deepseek.com",
        note = "实测支持思考开关；模型名可直接用 deepseek-flash。",
    )

    val DOUBAO = AiProvider(
        label = "豆包",
        baseUrl = "https://ark.cn-beijing.volces.com/api/v3",
        note = "火山方舟。模型名可能是「接入点 ID」（ep- 开头）也可能是模型名——" +
            "点下面的「拉取模型列表」拉一下再选，别手猜。",
    )

    val QWEN = AiProvider(
        label = "千问",
        baseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        note = "阿里云百炼。注意两点：① API Key 与地域绑定；" +
            "② 北京地域官方已迁到带 WorkspaceId 的新域名，" +
            "拉不到列表就去百炼控制台核对当前地域的 base_url。",
    )

    /** 顺序 = 设置页里预设按钮的顺序。 */
    val ALL: List<AiProvider> = listOf(DEEPSEEK, DOUBAO, QWEN)

    /** 当前地址命中的预设（用于高亮 + 显示该厂商的注意事项）；没命中返回 null = 自定义地址。 */
    fun match(baseUrl: String): AiProvider? = ALL.firstOrNull { it.matches(baseUrl) }

    /**
     * 所有厂商共同的前提，设置页固定展示一行。
     * 单独抽出来是因为它**不是某一个厂商的坑**，漏掉会让用户拿着一个只会闲聊的模型来问"为什么查不到数据"。
     */
    const val TOOL_CALLING_REQUIREMENT =
        "所选模型必须支持「工具调用 / function calling」，否则它只能闲聊、查不到任何业务数据。"
}
