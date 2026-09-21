package com.tapmoay.sorders.ai

import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * **本机能力**（不查后端、读的是这台手机自己的东西）的声明处 —— **全库只有这一份**。
 *
 * ### 为什么不进 `AiReadCatalog.kt`（机器生成的那份）
 * 那份目录由 `_tools/ai/_gen_ai_read_catalog.py` 从**后端路由的 AST** 生成，每条都带一个真实
 * `/api/v1/...` 路径，`--check` 会校验它没过期。"手机定位"**没有后端端点** ——
 * 硬塞进去的后果是：① 生成器一跑就被抹掉（或 `--check` 永远红）；②
 * `_probe_read_roles.py` 会拿着一个不存在的 URL 去打真后端。
 *
 * 所以分工是：**后端表**走生成目录，**本机能力**走这个手写文件；两边复用同一个 [ReadAction]
 * 数据类，靠 `path` 是否为空区分（那正是"要不要发 HTTP"的判据，见 [AiReadService]）。
 * ⛔ 不许给 [ReadAction] 加新字段来标记"本机"——生成器一跑就没了，而没了之后
 * `path.isBlank()` 这条判据还在、只是永远为假（静默失效）。
 *
 * ### 声明在这里的能力必须自己扛三件事
 * 1. **角色**：[ReadAction.roles] 用后端那套角色键。AI 只存在于派单端与货主端
 *    （司机端一个入口都没有），所以本机能力给这两个角色。
 * 2. **模块**：[MODULES] 里的键要和后端模块一样出现在设置页的开关列表里 ——
 *    定位是**隐私**，用户必须能关掉它（关掉之后 `AiReads.forRole` 就不再给它，见那里）。
 * 3. **输出里的坐标**：本机能力读的是定位，而**坐标永远不进模型上下文**（本仓第一条硬规矩）。
 *    这里只回**地址文字**；坐标只用于写链路（[AiLocation.requireHere]）。
 */
object AiLocalReads {

    /** 模块键（`模块.动作` 的左边那半段）。 */
    const val MODULE_LOCATION = "location"

    /** 本机能力涉及的模块（设置页的"可读列表"里要出现它们，用户才能关）。 */
    val MODULES: List<String> = listOf(MODULE_LOCATION)

    /** 模块中文名（设置页显示用；后端那些在 `AiReadCatalog.MODULE_CN` 里）。 */
    val MODULE_CN: Map<String, String> = mapOf(MODULE_LOCATION to "手机定位")

    /** 「我现在在哪」——读一次手机定位，**只回地址文字**。 */
    const val CURRENT_LOCATION = "location.current"

    /**
     * 本机读能力（`path` 留空 = 本机能力，不发 HTTP）。
     *
     * `filterHint` 也留空：它没有可筛的参数（模型给什么都只能忽略，如实回一句比装作支持好）。
     */
    val ACTIONS: List<ReadAction> = listOf(
        ReadAction(
            action = CURRENT_LOCATION,
            cn = "我现在在哪（读一次手机定位，只给地址文字）",
            path = "",
            filterHint = "",
            roles = setOf("dispatcher", "shipper"),
            memberOnly = false,
            params = emptyList(),
        ),
    )

    /** 按 action 查本机能力；null = 不是本机能力（调用方继续查后端目录）。 */
    fun find(action: String): ReadAction? = ACTIONS.firstOrNull { it.action == action.trim() }

    /** 某个模块下有哪些本机能力（设置页那句说明用，与 `AiReadCatalog.actionsOf` 同形）。 */
    fun actionsOf(module: String): List<ReadAction> = ACTIONS.filter { it.action.startsWith("$module.") }

    /**
     * 执行一条本机能力，返回**直接能喂给模型**的 JSON（失败是 `{"error":"人话"}`，与其他读工具同形）。
     *
     * ⛔ 这里**只调本机的东西**：不碰 Retrofit、不碰 [com.tapmoay.sorders.data.repo.AppRepository]。
     * 这条不是洁癖 —— "本机能力"这个分类的全部意义就是"它不需要后端"。
     */
    suspend fun run(action: ReadAction, provider: AiLocationProvider?): String =
        when (action.action) {
            CURRENT_LOCATION -> current(provider)
            else -> err("「${action.action}」这个本机能力还没实现。请如实告诉用户，不要换个写法再试。")
        }

    /**
     * 读一次定位，**只把地址文字交给模型**。
     *
     * 三种失败各给一句**能照着改**的中文（文案的唯一出处是 [AiLocation]）：
     * 没能力 / 没授权 / 这次没定位到。⛔ 都不许编一个地址出来。
     */
    private suspend fun current(provider: AiLocationProvider?): String {
        if (provider == null) return err(AiLocation.NO_PROVIDER)
        if (!provider.permitted()) return err(AiLocation.NO_PERMISSION)
        val place = provider.current() ?: return err(AiLocation.NO_FIX)
        return buildJsonObject {
            put("action", CURRENT_LOCATION)
            put("what", "用户手机**此刻**所在的位置（刚取的一次定位，不是历史位置）")
            // ⛔ 只有文字：坐标不进任何模型可见的输出（红线与本文件的单测都盯着这一条）。
            put("address", place.address)
            put(
                "note",
                "这就是用户现在所在的地方。回答里直接说这个地址。" +
                    "⛔ 不要说经纬度、不要说这是「系统给的」；⛔ 也不要把别人的位置当成他的。" +
                    "要把这个位置**写进地址**（建地址/改订单送货地址）时，参数里填「" +
                    AiLocation.HERE + "」四个字就行 —— 精确坐标由 App 自己带上，你不用管。",
            )
        }.toString()
    }

    private fun err(message: String): String =
        buildJsonObject { put("error", message) }.toString()
}
