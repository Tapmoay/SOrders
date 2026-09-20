package com.tapmoay.sorders.ai

import com.tapmoay.sorders.ui.nav.Modules
import com.tapmoay.sorders.ui.nav.Role

/**
 * **按角色分的身份提示词**：你是谁、你能干什么、哪些**不归你**。
 *
 * ### 为什么必须分开（用户原话）
 * > 「AI 说自己能干好多事情，是因为你那个系统提示词没写好、没有分开。我们要有一个身份系统提示词：
 * >   派单员是派单员的、货主是货主的。货主他只是下单、查看有哪些商品还在卖/价格怎样、
 * >   查看自己的联系人和地址，让 AI 帮忙下单；或者去看一下自己收到的消息；
 * >   或者让 AI 分析一下自己的账本；还有看一下自己订单现在的状态——**他其实就只有这么多功能**。
 * >   像什么管理库存这些，他根本就不需要。」
 *
 * v3.28 之前的提示词第一行写死的是「你是…给**派单员**用的助手」，后面又按派单员的口径
 * 列举了库存/账号/商品/派单/36 张表。货主登录进来读到的还是同一份 —— 于是被问
 * 「你能做什么」时，它就把**派单员的能力**念了一遍（真机实测：它把"司机绩效"列进了"能做"，
 * 还承诺过"我可以把异常审计导出 Excel"）。**它没有撒谎，是提示词告诉它它是派单员。**
 *
 * ### 两条设计约束
 * 1. **能力和"不归你"都必须算出来，不能手写**：手写的清单一定会和
 *    [AiWrites.forModel] / [AiReads.forRole] 走散（这个仓库里栽过 5 次），
 *    而走散的后果是"说得出、做不到"——正是这一条要修的病。
 * 2. **提示词里不许出现清单外的能力名**：货主那份里出现"库存"两个字，它就会去试。
 *    所以"不归你"只写**域**（库存/账号与收费规则/…），不写具体动作名。
 */
object AiRolePrompt {

    /** 派单员（管理员）：整个系统都归他管。 */
    private const val DISPATCHER_IDENTITY =
        "你是「SOrders 派单送货管理系统」里给**派单员（管理员）**用的助手。" +
            "系统里经营管理的每一块都归他管——他把单派给司机、管商品与价格、管账号、看报表与审计。"

    /**
     * 货主：只管自己那一摊事。
     *
     * 这段是**判断题**（用户口述的边界），但下面挂的能力清单是从代码里算出来的，
     * 所以就算这段写得宽了，清单也只列他真能用的。
     */
    private const val SHIPPER_IDENTITY =
        "你是「SOrders 派单送货管理系统」里给**货主**用的助手。" +
            "货主是来发货的商家，他**只管自己那一摊事**：把自己的货发给客户、盯自己单子的进展。" +
            "系统里的经营管理（派单、库存、商品与价格维护、账号、司机结算、报表审计）不归他，" +
            "他也从来不需要——那些页面对他根本不可见。" +
            "⚠️ 特别记住**派单这件事**：派单是派单员的活，货主自己**没有派单这个操作**" +
            "（他的界面上没有派单按钮）。他要发货就**把单下出来**（这是他真能干的事），" +
            "下完之后派单员会从待派单池里看到并派给司机。" +
            "所以被问「帮我派单」时，正确的回答是「派单是派单员做的：你把单下出来，他会接着派；" +
            "要我帮你把这单下了吗？」——**绝不能**让他「去订单页面自己派一下」。"

    /** 认不出角色：什么身份都不给，只给最保守的一句。 */
    private const val UNKNOWN_IDENTITY =
        "你是「SOrders 派单送货管理系统」里的助手。**当前没认出你的角色**，" +
            "所以你现在查不到也改不了任何业务数据；如实告诉用户去「我的」页面重新登录。"

    /**
     * 拼出这一轮的身份段，追加在通用规则之前。
     *
     * @param actor 当前登录角色 + **他是不是批发商货主**（null = 还没加载出来 → fail-closed）。
     *   第二维必须传真的那一个：普通货主与批发商货主的**移动端界面就不一样**
     *   （批发商多一本自己的账），身份段里那份"你实际能干的事"是照它生成的。
     * @param readModules 用户在设置里打开的只读模块（和工具说明同一份，保证两边一致）
     */
    fun brief(
        actor: AiActor?,
        readModules: Set<String> = AiReadCatalog.modules().toSet(),
    ): String {
        val role = actor?.role
        val identity = when (role) {
            AiRole.DISPATCHER -> DISPATCHER_IDENTITY
            AiRole.SHIPPER -> SHIPPER_IDENTITY
            null -> return UNKNOWN_IDENTITY
        }
        // 批发商货主多一句话：他手机上还多一本自己的账（下游货主欠他多少）。
        // 不写这句的后果：模型从清单里看到「我的账本」那一组，却按普通货主的身份解释它。
        val identityFull = if (actor.memberShipper) {
            identity + "\n你还是**批发商货主**：除了给自己下单，你还管着下游货主 —— " +
                "「我的账本」上有一段\"我的货主欠我多少\"，可以在那一单上核销（记的是**你自己**这一本账）。"
        } else {
            identity
        }
        val writes = AiWrites.forModel(actor)
        val reads = AiReads.forRole(actor, readModules)
        val pages = pagesOf(role)

        return buildString {
            appendLine(identityFull)
            appendLine()
            appendLine("【你实际能干的事——这份清单是从代码里生成的，永远和真实能力一致】")
            if (writes.isEmpty()) {
                appendLine("· 改数据：一个都没有")
            } else {
                appendLine("· 改数据（每一件都要用户点确认才生效）：")
                writes.groupBy { it.group }.forEach { (group, list) ->
                    appendLine("  - $group：" + list.joinToString("、") { it.title })
                }
            }
            if (reads.isEmpty()) {
                appendLine("· 查数据：一张表都没有")
            } else {
                // 按**模块键**去重（`orders.list_orders` → `orders`）：中文名是一句话，
                // 几行连起来会把提示词撑长，而这里只需要让模型知道"能碰哪几块"。
                appendLine(
                    "· 查数据（只读）：" + reads.map { it.action.substringBefore('.') }.distinct()
                        .joinToString("、"),
                )
            }
            // 「他有哪些页面」也从界面配置里取（见 pagesOf）：指路只能指这些，多一个都不行。
            appendLine("· 他界面上有的页面（**只有这些**）：" + pages.joinToString("、"))
            // 「不归你」只写**域**：写具体动作名等于把不该有的能力名字摆到它眼前。
            val mine = writes.map { it.group }.toSet()
            val notMine = ALL_WRITE_GROUPS.filter { it !in mine }
            if (notMine.isNotEmpty()) {
                appendLine("· ⛔ 不归你的（被问到就说做不了，**不要去试、也不要换个说法再试**）：" +
                    notMine.joinToString("、"))
            }
            appendLine()
            appendLine("【被问到「你能帮我做哪些事」时怎么办】")
            appendLine("照**上面这份清单**念，一件不多一件不少。")
            appendLine("⛔ 不许凭印象归纳、不许提清单以外的任何能力（哪怕是你在别处见过的功能名），")
            appendLine("   也不许承诺清单外的动作（例如「帮你导出一份 Excel」）。")
            appendLine()
            appendLine("【问到不归你的事：怎么给下一步】")
            appendLine("先一句「这个不归我」，然后**按对方有没有那个页面**分两种说法：")
            appendLine("· 他有那个页面 → 说「去「页面名」自己做」（页面名只能取上面那份页面清单）；")
            appendLine("· 他**没有**那个页面 → ⛔ **不要指任何页面**，改成说清这件事归谁做。")
            appendLine("  例：货主问「帮我派单」→「派单是派单员做的：你把单下出来，他会从待派单池里接着派。」")
            appendLine("  例：货主问「把商品价格改了 / 把库存清零」→「商品和库存是派单员管的，你这边看不到也不该改。」")
        }.trimEnd()
    }

    /**
     * 这个角色**界面上真的有**的页面名（从工作台/底部导航配置里取，不手写）。
     *
     * 为什么要它：第一版只写了「并告诉他去哪个页面自己做」——对派单员没问题（他什么页面都有），
     * 对货主就成了**把人指到墙上**。真机实测：货主问「帮我把这单派给司机」，
     * 回答是「去订单页面自己派一下」，而货主那边根本没有派单按钮；
     * 问「改商品价」「把库存改成 0」也一样，被指去了他打不开的页面。
     * 用户原话：「货主没有派单的权限，他只有下单——他的提醒应该说可以通知派单员进行派单。」
     */
    private fun pagesOf(role: AiRole): List<String> =
        Modules.entriesFor(Role.fromKey(role.key))
            .map { it.label }
            .filter { it != "AI 助手" }
            .distinct()

    /**
     * 设置页顶上那段**能力声明**（给用户看的，不是给模型看的）。
     *
     * 为什么也让它算出来：那段话是一句**承诺**，写宽了用户会去试、写窄了用户以为它不会。
     * 它已经走散过一次——批量化调价 v3.21 就上线了，设置页却一直写着「改价…它做不了」，
     * 而同一段代码的注释里恰好警告过这件事（"写窄了模型会跟着否认自己的能力"）。
     * 和提示词同源之后，两边不可能再各说一套。
     *
     * @param actor 当前登录角色 + 是不是批发商货主（null → 按"什么都做不了"说，fail-closed）
     * @param readModules 用户在下面打开的只读模块
     */
    fun settingsSummary(
        actor: AiActor?,
        readModules: Set<String> = AiReadCatalog.modules().toSet(),
    ): String {
        if (actor == null) {
            return "当前没认出你的角色，AI 现在查不到也改不了任何业务数据——去「我的」页面重新登录一次。"
        }
        // ⚠️ 必须翻成中文名（`AiReadCatalog.MODULE_CN`）。这里原来是 `action.substringBefore('.')`，
        //    也就是把 `arrears`、`cash_flows`、`driver_settlements` 这些**内部模块码**整段印给用户看——
        //    21 个英文词堆成一段，用户既读不懂也记不住。这和「回答里不许出现内部编号」是同一条规矩，
        //    只是当时漏在了设置页上。
        val reads = AiReads.forRole(actor, readModules)
            .map { a -> a.action.substringBefore('.').let { AiReadCatalog.MODULE_CN[it] ?: it } }
            .distinct()
        val groups = AiWrites.forModel(actor).map { it.group }.distinct()
        // 用户 2026-09-17：「能用一两句话解决的事情就不要说那么多话。」
        // 所以这里从"能查 + 能改 + 不归它的 + 从代码生成"四段压成两句，
        // **必要信息一条没少**：能查什么、能改什么、以及"改"这一步必须他确认。
        return buildString {
            append("能查：")
            append(if (reads.isEmpty()) "暂时没有（下面的只读开关都被关掉了）" else reads.joinToString("、"))
            appendLine()
            append(
                if (groups.isEmpty()) {
                    "能改：没有。"
                } else {
                    "能改：${groups.joinToString("、")}——它只会把改动做成一张确认卡，你点「确认」才会写进系统。"
                },
            )
        }
    }

    /**
     * 全部写能力域（**自己从动作表算**，不手写）。
     *
     * 手写一份域名的后果：加了新域而这里没跟上，「不归你」那段就会漏掉它，
     * 货主读到的提示词里也就不会被告知那个域不归他。
     */
    private val ALL_WRITE_GROUPS: List<String> =
        AiWrites.ALL.map { it.group }.distinct()
}
