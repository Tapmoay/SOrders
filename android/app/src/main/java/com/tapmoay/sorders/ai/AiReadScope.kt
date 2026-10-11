package com.tapmoay.sorders.ai

/**
 * **读权限的「范围声明」** —— 把「你只能读这几块」写成提示词里的一句硬规矩。
 *
 * ### 这文件在补哪个洞（2026-10-11 用户点名的第七次）
 * 用户原话：「AI 以为货主能读挂账单位、计费规则、开支分类啊……这个**从根源上后端做了一个拦截**，
 * 但是我们要**从 AI 那也做个拦截** —— 就是 AI **明确地知道**：我作为货主，**只能读货主的那些东西**，
 * 其他的他**根本读不了**，他**压根就不会去想**去读这些他**能力范围之外**的事情。」
 *
 * 后端那道门（[AiReads.allows]）拦的是**动作**：模型试着去读就会拿到一句「没这个权限」。
 * 但它拦不住**想法** —— 模型会先去想、再去试、拿到失败再换一种问法，用户看到的就是一串
 * 「查不到」。范围声明是第二道门，形状不同：它**事先**把范围说死，让「想」这一步就不发生。
 *
 * ### 三条纪律（每一条都有它挡住的具体故障）
 * 1. **范围只能从 [AiReads.forRole] 算**（见 [modulesOf]）：另算一份 = 两道门的边界不一样 ——
 *    声明里说了「不能读」而门放行的，是**白白丢掉一条真有权限的能力**；反过来（声明说能读、
 *    门拦住）就是用户在提示词里被承诺了一件做不到的事。
 * 2. **⛔ 一个字都不许把表名 / 端点名 / 模块清单手抄进这段文案**：抄的那一刻它就开始过期，
 *    而过期的读权限表**不报错** —— 模型只是越来越不会用（本仓栽过 5 次，见 [AiReads] 的类注释）。
 * 3. **中文名走 [AiReads.moduleCn]**（没有就用模块键），本机能力也在这条路上（[AiLocalReads]）：
 *    否则设置页里开着「手机定位」、提示词里却不提它，模型就想不到自己还能看定位。
 *
 * ⚠️ 判据：`_tools/qa/_check_ai_role_read_scope.py`（逐字钉住 [SCOPE_RULE] 与 [NO_PERMISSION]，
 * 并把这里的模块集合与目录里*这个角色*能读到的行**逐条对账**）。
 */
internal object AiReadScope {

    /**
     * 为什么这段话要写这么长 —— 三种「客气」的说法都不能用：
     * · 只说「尽量别读范围外的东西」→ 模型当建议，试一次没成再换写法（实测就是这个形态）；
     * · 只说「你没有权限」→ 模型解释成「这张表现在查不到」，然后告诉用户「系统里没有」；
     * · 不说「后台会拦住」→ 模型以为试一下没代价，「猜一个试试」就成了它的默认策略。
     */
    const val SCOPE_RULE: String =
        "你只能读上面这几块里的东西。范围外的一律不要尝试、也不要猜（后台会直接拦住，换一种问法也一样）。"

    /** 说清「读不了」与「没有数据」的区别 —— 混在一起，用户会以为系统里真的没这笔账。 */
    const val NO_PERMISSION: String =
        "读不了的东西 = **没有授权给你**，不是「系统里没有」；被问到就直说这件事不归你看，别绕。"

    /**
     * 这个角色实际能读的**模块键**（`orders` / `products` / `location` …）。
     *
     * ⚠️ 与提示词、工具说明、执行前的门**同源**：走的是同一个 [AiReads.forRole]（角色 + 批发商
     * 两个维度 + 用户关掉的模块），所以旁边那些「读了什么」的判据全都落在同一条链上。
     */
    fun modulesOf(actions: List<ReadAction>): List<String> =
        actions.map { it.action.substringBefore('.') }.distinct()

    /** 模块键 → 中文名（设置页里用户看到的那套名字，不另起一套）。 */
    fun cnOf(modules: List<String>): List<String> = modules.map { AiReads.moduleCn(it) }

    /**
     * 拼成一行（表张数也写进去）—— 建议紧跟在「· 查数据（只读）：…」后面一行。
     *
     * @param modules 能读的模块键（见 [modulesOf]）；空 = 一张表都没有，这时**不提范围**
     *   （「你只能读：（空）」读起来像故障，而「一张表都没有」上一行已经说过了）。
     * @param tableCount 能读的**表**数（提示词里那份清单的行数），与模块数一起把范围量出来。
     */
    fun rule(modules: List<String>, tableCount: Int): String? {
        if (modules.isEmpty() || tableCount <= 0) return null
        return buildString {
            append("· ⛔ ").append(SCOPE_RULE)
            append("· 范围就是这几块：").append(cnOf(modules).joinToString("、"))
            append("（共 ").append(tableCount).append(" 张表）。")
            append("· ").append(NO_PERMISSION)
        }
    }
}
