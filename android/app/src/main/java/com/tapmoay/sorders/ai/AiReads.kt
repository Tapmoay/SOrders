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
 *
 * ### 本机能力也从这里过（2026-09-21）
 * 「读手机定位」这类能力**没有后端端点**，角色是手写的（见 [AiLocalReads]），但**门是同一道**：
 * [forRole] 把它们和后端目录拼在一起，角色、批发商、模块开关三条判据一模一样地生效。
 * 只把本机能力接到"工具说明"而漏掉执行前的门，就是一条**绕过模块开关读定位**的暗道。
 */
object AiReads {

    /** [AiRole] → 后端角色键（读目录里 `roles` 用的就是后端那套键，见生成脚本）。 */
    fun key(role: AiRole?): String? = when (role) {
        AiRole.DISPATCHER -> "dispatcher"
        AiRole.SHIPPER -> "shipper"
        null -> null
    }

    /**
     * **全部**读能力 = 机器生成的后端目录 + 手写的本机能力（见 [AiLocalReads]）。
     *
     * ⚠️ 只有这一处把两边拼起来：角色裁剪、工具说明、enum、执行前的门**必须看同一份**。
     *    任何一处只看后端目录，症状都是"本机能力在某些角色/某些调用点上凭空消失"，
     *    而且不报错（模型只会说"我查不了"）。
     */
    fun allActions(): List<ReadAction> = AiReadCatalog.ACTIONS + AiLocalReads.ACTIONS

    /**
     * 全部模块键（后端模块 + 本机能力的模块）。
     *
     * 为什么必须有它：模块级开关的白名单原来是 `AiReadCatalog.modules()`（只有后端模块），
     * 于是 `location` 这个键**不在任何一份开关集合里** ——
     * ① 用户还没进过设置页时（`enabledModules` 默认全开）它会被静默过滤掉；
     * ② 进过设置页、存过一份白名单之后，更是一辈子都开不回来。
     * 两种都不会报错，只是"AI 说它读不了定位"。
     */
    fun allModules(): List<String> = (AiReadCatalog.modules() + AiLocalReads.MODULES).distinct().sorted()

    /**
     * 模块中文名（后端模块查生成目录，本机模块查 [AiLocalReads]）。
     *
     * 设置页原来直接用 `AiReadCatalog.MODULE_CN[it] ?: it` —— 本机模块不在那张表里，
     * 于是屏幕上会印出一个英文键 `location`（"用户既读不懂也记不住"，与当初
     * 把 `arrears`、`cash_flows` 印给用户看是同一个毛病）。
     */
    fun moduleCn(module: String): String =
        AiReadCatalog.MODULE_CN[module] ?: AiLocalReads.MODULE_CN[module] ?: module

    /** 某个模块下有哪些**读能力**（后端表 + 本机能力）。设置页那句说明用。 */
    fun actionsOf(module: String): List<ReadAction> =
        AiReadCatalog.actionsOf(module) + AiLocalReads.actionsOf(module)

    /**
     * **用户保存过的那份模块白名单**要怎么算成"这次实际生效的模块"。
     *
     * ### 为什么需要这一步（2026-09-21 用户拍板，原话）
     * 「ai 它要具备读取手机的地点的能力……**这个权限给它开啊**」—— 更新完就该能用，
     * ⛔ 不许让老用户自己去设置页里翻出那个新开关。而白名单是一份**枚举**：他保存的那份里
     * 不可能有当时还不存在的模块，直接照它过滤的后果是"新能力装了却没有任何反应"，
     * 而且**不报错**（本仓在 `AiKeyStore.enabledTools` 上已经栽过一次：记忆功能就这样哑了）。
     *
     * ### 三条语义（单测逐条钉着）
     * 1. `saved` 为空 → **空**。老约定：空串 = 用户主动"**全关**"，不是"我列出来的这些关掉"。
     *    ⛔ 拿它当枚举去补新模块，等于把用户明确关掉的东西又打开 —— 而这次关的是**隐私**；
     * 2. `knownAtSave == null`（**旧数据**：那时还没记"当时有哪些模块"）→ 只补 [AiLocalReads.MODULES]
     *    这一类。理由：本机能力是**今天才出现的**，任何一份旧白名单里都不可能有它；
     *    而后端模块**不补** —— 没有标记就分不出"他当时关掉的"和"当时还不存在的"，
     *    乱补就是第 1 条刚否掉的那个错；
     * 3. `knownAtSave` 有值 → 补 `现在全集 − 保存时已知`（= **保存之后新出现的**模块）。
     *    于是"更新之后用户明确关掉手机定位"会**记住是关**：那一刻它已经在 `knownAtSave` 里，
     *    不再是"新出现的"。
     *
     * ⚠️ 与 `AiKeyStore.enabledTools` 那条"见过的清单"是同一套路，但这里**刻意不在读的时候
     * 顺手刷新标记**：那个做法在工具那条路上会让"新加的按默认开"只生效一次
     * （读时把标记刷成全集 → 下一次就算出"没有新工具"）。这里两个分支都是**只读**的，结果稳定。
     *
     * @param saved 用户保存的那份（已 trim；**空集 = 他主动全关**）
     * @param knownAtSave 保存那一刻一共有哪些模块；**null = 旧数据**（保存时还没有这个标记）
     */
    fun resolveEnabled(saved: Set<String>, knownAtSave: Set<String>?): Set<String> {
        val all = allModules().toSet()
        if (saved.isEmpty()) return emptySet()
        val appeared = knownAtSave?.let { all - it } ?: AiLocalReads.MODULES.toSet()
        // 末尾的 intersect 顺手把"改过名的模块"筛掉（旧数据里可能留着已经不存在的键），
        // 但**允许合法地一个都不开**（见上面第 1 条）。
        return (saved + appeared).intersect(all)
    }

    /** 这个角色（+ 是不是批发商货主）能读的表（已叠加"用户在设置里关掉的模块"）。 */
    fun forRole(
        actor: AiActor?,
        enabledModules: Set<String> = allModules().toSet(),
    ): List<ReadAction> {
        val k = key(actor?.role) ?: return emptyList()
        val member = actor?.memberShipper ?: false
        return allActions().filter {
            k in it.roles &&
                (!it.memberOnly || member) &&
                it.action.substringBefore('.') in enabledModules
        }
    }

    /** 执行侧的门（工具说明里看不到 ≠ 调不到：模型可以凭记忆写一个 action 出来）。 */
    fun allows(
        actor: AiActor?,
        action: String,
        enabledModules: Set<String> = allModules().toSet(),
    ): Boolean = forRole(actor, enabledModules).any { it.action == action }

    /**
     * 渲染成"给模型看的可读清单"，拼进 `read_data` 的 description。
     *
     * 一行一张表：`模块.动作（中文名）〔可筛：…〕`。把**可筛字段**摆在它眼前，
     * 是因为实测它最爱猜的就是"能不能按状态/日期筛"——目录里有、说明里没写，等于没有。
     *
     * `path` 为空的那几条后面标〔本机〕：它们查的是**这台手机**（不是后端），
     * 而且**没有可筛参数**。不标的话模型会拿它当地址表用（例如以为能按城市筛）。
     */
    fun describeForModel(
        actor: AiActor?,
        enabledModules: Set<String> = allModules().toSet(),
    ): String = forRole(actor, enabledModules).joinToString("\n") {
        buildString {
            append("- ").append(it.action).append("（").append(it.cn).append("）")
            if (it.path.isBlank()) append("〔本机：查的是这台手机，不是后端；没有可筛参数〕")
            if (it.filterHint.isNotBlank()) append("〔可筛：").append(it.filterHint).append("〕")
        }
    }
}
