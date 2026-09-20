package com.tapmoay.sorders.ai

/**
 * 读能力的**角色裁剪**——和写侧的 [AiWrites.forRole] 对称，但依据不同：
 *
 * 写侧的白名单是 App 自己定的策略（"货主只该有他工作台里那几件"）；
 * 读侧这里用的是**后端自己的授权**——每条只读端点的准入角色由
 * `_tools/ai/_gen_ai_read_catalog.py` 从后端源码解析出来（权限点 → 角色、体内 raise 403 的
 * 硬门槛），落进 [AiReadCatalog] 的 `roles`。两边都有实测对账：`_tools/ai/_probe_read_roles.py`
 * 会对三个角色逐条打真后端，角色表与实测不一致就报错。
 *
 * ### 为什么要裁（而"让后端挡"不行）
 * 不裁的后果不是安全问题（后端一定会 403），而是**用户被自己看不懂的失败卡住**：
 * 他问"我最近的订单有哪些"，模型却去查了只有派单员能看的操作日志，拿到 403 之后
 * 只能回一句"查不到"——**能力写了等于没写**。反过来裁多了更糟：明明能查的表，
 * AI 会说"我没这个权限"，用户永远不知道有这功能。
 *
 * ### fail-closed
 * 认不出角色（[AiActor] 为 null，例如角色还没加载出来）→ **一张表都不给**。
 * 少给是"等一下再问"，多给是"问了也白问"。
 *
 * ### 两个货主读的东西也不一样（2026-09-20 用户第七轮）
 * 「AI 也会分成 2 个：一个是普通货主、一个是批发商货主的 AI……普通货主**手机做不到的事情，
 * AI 也做不到**」。所以除了角色，还要看**他是不是批发商**（[AiActor.memberShipper]）：
 * 目录里标了 `memberOnly` 的那几张表（现在只有"我记下的核销"）只给批发商货主。
 */
object AiReads {

    /** [AiRole] → 后端角色键（读目录里 `roles` 用的就是后端那套键，见生成脚本）。 */
    fun key(role: AiRole?): String? = when (role) {
        AiRole.DISPATCHER -> "dispatcher"
        AiRole.SHIPPER -> "shipper"
        null -> null
    }

    /** 这个角色（+ 是不是批发商货主）能读的表（已叠加"用户在设置里关掉的模块"）。 */
    fun forRole(
        actor: AiActor?,
        enabledModules: Set<String> = AiReadCatalog.modules().toSet(),
    ): List<ReadAction> {
        val k = key(actor?.role) ?: return emptyList()
        val member = actor?.memberShipper ?: false
        return AiReadCatalog.ACTIONS.filter {
            k in it.roles &&
                (!it.memberOnly || member) &&
                it.action.substringBefore('.') in enabledModules
        }
    }

    /** 执行侧的门（工具说明里看不到 ≠ 调不到：模型可以凭记忆写一个 action 出来）。 */
    fun allows(
        actor: AiActor?,
        action: String,
        enabledModules: Set<String> = AiReadCatalog.modules().toSet(),
    ): Boolean = forRole(actor, enabledModules).any { it.action == action }

    /**
     * 渲染成"给模型看的可读清单"，拼进 `read_data` 的 description。
     *
     * 一行一张表：`模块.动作（中文名）〔可筛：…〕`。把**可筛字段**摆在它眼前，
     * 是因为实测它最爱猜的就是"能不能按状态/日期筛"——目录里有、说明里没写，等于没有。
     */
    fun describeForModel(
        actor: AiActor?,
        enabledModules: Set<String> = AiReadCatalog.modules().toSet(),
    ): String = forRole(actor, enabledModules).joinToString("\n") {
        buildString {
            append("- ").append(it.action).append("（").append(it.cn).append("）")
            if (it.filterHint.isNotBlank()) append("〔可筛：").append(it.filterHint).append("〕")
        }
    }
}
