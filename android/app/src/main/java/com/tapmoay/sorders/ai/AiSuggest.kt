package com.tapmoay.sorders.ai

/**
 * 「推荐问题」的**内容**（纯数据 + 纯函数，没有 Android 依赖，可直接单测）。
 *
 * ### 它解决什么（用户 2026-10-11 第十一轮）
 * > 「我们 ai 那个**我是货主助手**要随着角色而发生改变啊。而目前只有 3 个派单员呃货主还有批发商
 * >   这 3 个就够了，然后我们对应的下面不是有预设的一些问题吗？这些问题要跟着角色来进行变的
 * >   比如说假如这个角色是第一次来那他应该会涉及到哪些问题啊，那像有些人他一开始连订单什么都没有
 * >   肯定不会有这些问题啦，比如说呃帮我下单啊创建联系人啊创建地址肯定是这些问题……
 * >   我们还有一点就是我们随着他的使用习惯，他经常问什么问题会提前的呃把它显示出来。
 * >   当然，他也可以去固定啊，我这个问题就固定在这里，这也是可以的」
 *
 * 三件事分别落在：
 * 1. **[whoOf] 把一个登录账号折成三类**（派单员 / 货主 / 批发商）；
 * 2. **[firstDefaults] 与 [categories]** 让问题跟着角色走，并且**分两档**：
 *    从没用过这一页的人先看到「怎么开始」（下单、建地址、建联系人），
 *    用过的人看到「常做的事」（查单、查账、导表）；
 * 3. **[rank] 把「固定」与「常用」排到前面**。
 *
 * ### ⚠️ 为什么角色是**三**类而不是 `AiRole` 那两个
 * 后端只有 `dispatcher` / `shipper` / `driver` 三个 role key，**没有 `wholesaler`**：
 * 「批发商」是 `shipper` 且 `users.is_member=1`（见 [AiActor]）。手机端这两位货主
 * 界面都不一样（批发商那本账本多一段「我的货主欠我多少」、能核销），
 * 所以推荐问题也必须分开——给普通货主看「这个月还有哪些单没核销」和给他看
 * 「哪个司机跑得最多」是同一类错误：**教他做他做不到的事**。
 *
 * 司机端**没有 AI 入口**（`RoleHomeScreen` 只给派单员画那颗圆钮，货主是 v3.13 才开的），
 * 所以这里没有 `DRIVER` 分支；真开了再加，[whoOf] 对认不出的角色返回 `null`（fail-closed）。
 */
enum class AiSuggestWho(
    /** 存 prefs 用的键。⛔ 改动 = 老用户的固定/常用全丢，非必要不改。 */
    val key: String,
    /** 中文短名，给设置页的标题用（「首次问题预设 · 货主」）。 */
    val cn: String,
    /** 空状态的第一行大字。⛔ 用户点名要它随角色变。 */
    val title: String,
) {
    DISPATCHER("dispatcher", "派单员", "我是派单助手"),
    SHIPPER("shipper", "货主", "我是货主助手"),
    MEMBER("member", "批发商", "我是批发商助手"),
    ;

    companion object {
        fun fromKey(key: String?): AiSuggestWho? =
            entries.firstOrNull { it.key.equals(key?.trim(), ignoreCase = true) }
    }
}

/**
 * 一个**类别**下的一组推荐问题（「典型问题」面板按它分组）。
 *
 * @param cn 类别名，面板上的分组标题
 * @param questions 这一组的问题原文（点了直接发送）
 */
data class AiSuggestCategory(val cn: String, val questions: List<String>)

/**
 * 一整套推荐问题：**首次档** + **常规档**。
 *
 * @param first 从没用过这一页的人看到的 4 条（「怎么开始」）
 * @param categories 用过之后看到的分类问题库
 */
data class AiSuggestPack(val first: List<String>, val categories: List<AiSuggestCategory>) {
    /** 常规档摊平成一个列表（空状态按 [AiSuggests.rank] 挑前几条）。 */
    val flat: List<String> get() = categories.flatMap { it.questions }
}

/**
 * 「典型问题」面板右栏里的**一条操作** —— 让 AI 去干活，不是问它问题。
 *
 * ### 文案为什么不在这里写死
 * [title] 直接取动作自己的 [AiWriteAction.title]。抄一份到自己表里的下场很具体：
 * AI 加了个动作 ⇒ 面板里没有；AI 改了个名字 ⇒ 面板里还是旧的。
 * **这两件事都不会报错**，只会让用户点了按钮之后 AI 说「我不太明白」。
 * 所以这一整张表由 [AiSuggests.opsSections] 从注册表现算。
 */
data class AiSuggestOp(val id: String, val title: String, val risk: AiWriteRisk) {
    /**
     * 点一下**替用户说出去**的那句话。
     *
     * ⚠️ 它只是把话说出来，**没有执行任何东西**：AI 照旧要缺参数就问、动手前弹确认卡，
     * 用户不点确认卡，什么都不会发生（[AiPendingWrite] 的三条不变量）。
     * 高风险动作因此可以放心摆出来 —— 摆上去和点得动是两回事。
     */
    val say: String get() = if (title.startsWith("帮")) title else "帮我$title"
}

/** 面板左栏的一格。 */
enum class AiSuggestKind {
    /** 我常问的（点过两次以上才进来）。 */
    USED,

    /** 问 AI 一个问题。 */
    ASK,

    /** 让 AI 去干一件事。 */
    DO,

    /** 一格两面：上面是能问的，下面是能让他干的（名字撞了就并成一格）。 */
    MIXED,
}

/**
 * 面板左栏的一格：一个类别，底下一批问题 / 一批操作。
 *
 * 分开列而不是混在一起：用户点进「订单」这一格时，**问一句**和**干一件**
 * 是两种完全不同的预期（一个马上有答案，一个会反过来问他问题）。
 */
data class AiSuggestSection(
    val cn: String,
    val kind: AiSuggestKind,
    val questions: List<String> = emptyList(),
    val ops: List<AiSuggestOp> = emptyList(),
) {
    val size: Int get() = questions.size + ops.size
}

object AiSuggests {

    /** 空状态上最多摆几条（多了要滚动，第一印象反而散）。 */
    const val HOME_LIMIT = 4

    /** 「常用」区最多几条。 */
    const val USED_LIMIT = 4

    /** 同一个问题至少被点过这么多次才算「常用」（一次是手滑，不是习惯）。 */
    const val USED_MIN_TAPS = 2

    /**
     * 一个登录账号 → 三类身份之一。
     *
     * `null`（认不出角色）⇒ 返回 `null`，调用方**照旧画老的空状态**：
     * 猜错角色比不推荐更糟——那是「教他做他做不到的事」。
     */
    fun whoOf(actor: AiActor?): AiSuggestWho? = when {
        actor == null -> null
        actor.role == AiRole.DISPATCHER -> AiSuggestWho.DISPATCHER
        actor.memberShipper -> AiSuggestWho.MEMBER
        else -> AiSuggestWho.SHIPPER
    }

    /** 三类角色各自的一整套。 */
    fun packFor(who: AiSuggestWho): AiSuggestPack = when (who) {
        AiSuggestWho.DISPATCHER -> DISPATCHER_PACK
        AiSuggestWho.SHIPPER -> SHIPPER_PACK
        AiSuggestWho.MEMBER -> MEMBER_PACK
    }

    /**
     * 这一页该摆哪几条。
     *
     * @param firstTimer 他是不是**还没开始用**（见 `AiChatViewModel.suggestFirstTimer`）
     * @param customFirst 用户在设置里自己编辑过的首次预设（`null` = 用默认那套）
     * @param pinned 他固定住的问题（顺序有意义，排最前）
     * @param taps 点过的次数（问题原文 → 次数），用来排「常用」
     */
    fun home(
        who: AiSuggestWho,
        firstTimer: Boolean,
        customFirst: List<String>? = null,
        pinned: List<String> = emptyList(),
        taps: Map<String, Int> = emptyMap(),
    ): List<String> {
        val pack = packFor(who)
        val base = if (firstTimer) (customFirst ?: pack.first) else pack.flat
        return rank(base, pinned, taps).take(HOME_LIMIT)
    }

    /**
     * 排序：**固定 → 常用 → 默认顺序**。
     *
     * 两条纪律：
     * - 固定与常用里出现、但**不在 [base] 里**的问题**不硬塞进来**（除非它在 pinned 里）：
     *   `base` 是"这个角色此刻该看到什么"的唯一来源，允许任意旧问题长期占位，
     *   等于把这一页交给历史。
     * - 排序**稳定**（同分保持原顺序）：否则每次重组都跳一下，看着像 bug。
     */
    fun rank(base: List<String>, pinned: List<String>, taps: Map<String, Int>): List<String> {
        val head = pinned.filter { it.isNotBlank() }.distinct()
        val rest = base.filter { it.isNotBlank() && it !in head }.distinct()
        // 只有"在 base 里"的问题才吃"常用"加权——理由同上。
        val used = rest.filter { (taps[it] ?: 0) >= USED_MIN_TAPS }
            .sortedByDescending { taps[it] ?: 0 }
        val tail = rest.filter { it !in used }
        return head + used + tail
    }

    /**
     * 「常用」区（面板顶部那一栏）：**从 [taps] 里挑**，不看类别。
     *
     * 与 [rank] 里的加权不同，这里允许出现 `base` 里没有的问题——用户自己敲过、
     * 反复问过的原话，比任何预设都准。⛔ 但只认**问过 2 次以上**的（[USED_MIN_TAPS]）。
     */
    fun usedQuestions(taps: Map<String, Int>, base: List<String>, limit: Int = USED_LIMIT): List<String> {
        val fromTaps = taps.entries
            .filter { (k, n) -> n >= USED_MIN_TAPS && k.isNotBlank() }
            .sortedWith(compareByDescending<Map.Entry<String, Int>> { it.value }.thenBy { it.key })
            .map { it.key }
        // base 里已有的一定排前面（它们是"这个角色确实该问的"），其余才是纯自定义
        val inBase = fromTaps.filter { it in base }
        val others = fromTaps.filter { it !in base }
        return (inBase + others).take(limit)
    }

    /**
     * 设置页的「恢复默认」要写回的默认首次预设。
     *
     * 单独开一个函数而不是让界面去读 [packFor]：将来首次档改成按角色再分叉时，
     * 只有这里要改。
     */
    fun defaultFirst(who: AiSuggestWho): List<String> = packFor(who).first

    // ------------------------------------------------------------ 操作（DO）

    /**
     * [whoOf] 的反函数：三类身份 → 一个能喂给 [AiWrites.forModel] 的 actor。
     *
     * ⛔ 批发商**仍然是 `AiRole.SHIPPER`**，靠 `memberShipper = true` 分叉 ——
     * 后端只有两个角色，为界面造第三个枚举值会连带把权限与写操作闸门一起改坏。
     */
    fun actorOf(who: AiSuggestWho): AiActor? = when (who) {
        AiSuggestWho.DISPATCHER -> AiActor.of(AiRole.DISPATCHER, false)
        AiSuggestWho.SHIPPER -> AiActor.of(AiRole.SHIPPER, false)
        AiSuggestWho.MEMBER -> AiActor.of(AiRole.SHIPPER, true)
    }

    /** 这个角色能叫 AI 干的活（注册表现算，⛔ 不另抄一份）。 */
    fun opsFor(who: AiSuggestWho): List<AiWriteAction> = AiWrites.forModel(actorOf(who))


    /**
     * 把 AI 真正能干的活按**它自己的域**分组，供面板左栏用。
     *
     * @param actions 传 [AiWrites.forModel] 的结果。⛔ **不要另抄一份动作清单** ——
     *   抄一份的那天起，注册表加了动作而面板不知道，而这件事不会报错。
     *
     * 域的顺序用注册表自己的声明顺序（`groupBy` 保序），不按条数排：
     * 注册表是按业务顺序写的（订单 → 账目 → 账号 → 地址…），那个顺序就是用户翻的时候的顺序。
     */
    fun opsSections(actions: List<AiWriteAction>): List<AiSuggestSection> =
        actions.groupBy { it.group }.map { (cn, list) ->
            AiSuggestSection(
                cn = cn,
                kind = AiSuggestKind.DO,
                ops = list.map { AiSuggestOp(it.id, it.title, it.risk) },
            )
        }

    /**
     * 面板左栏的完整一格一格：我常问的 → 问题分类 → 操作分类。
     *
     * 一个入口（输入框上方那颗按钮）弹出左抽屉，用户按类别挑 —— 这样"预设"才铺得下：
     * 光问题就有三四十条，加上操作是**两百多条**，摊平了没法看；
     * 分类之后每一格都只有几条，翻两下就到。
     */
    fun shelf(
        pack: AiSuggestPack,
        taps: Map<String, Int>,
        actions: List<AiWriteAction>,
    ): List<AiSuggestSection> {
        val out = LinkedHashMap<String, AiSuggestSection>()
        val used = usedQuestions(taps, pack.flat)
        if (used.isNotEmpty()) {
            out["我常问的"] = AiSuggestSection("我常问的", AiSuggestKind.USED, questions = used)
        }
        pack.categories.forEach {
            out[it.cn] = AiSuggestSection(it.cn, AiSuggestKind.ASK, questions = it.questions)
        }
        // ⛔ 问题分类与操作域的**名字必然撞**（「订单」「账目」「地址与联系人」两边都这么叫）——
        //    左栏是按名字排的，撞了就是两格一模一样、点进去一个只有问、一个只有活。
        //    同名并成一格：上面列能问的，下面列能让他干的。
        opsSections(actions).forEach { s ->
            val had = out[s.cn]
            out[s.cn] = if (had == null) s
            else had.copy(kind = AiSuggestKind.MIXED, ops = s.ops)
        }
        return out.values.toList()
    }

    // ---------------------------------------------------------------- 问题库

    private val DISPATCHER_PACK = AiSuggestPack(
        first = listOf(
            "怎么给一单派司机？",
            "帮我建一个货主账号",
            "怎么加一个商品？",
            "这个月谁下单最多？",
        ),
        categories = listOf(
            AiSuggestCategory(
                "订单",
                listOf(
                    "今天有哪些单还没派出去？",
                    "某个货主这个月下了多少单？",
                    "把这周已完成的订单导成表格",
                ),
            ),
            AiSuggestCategory(
                "司机与车辆",
                listOf(
                    "哪个司机这个月跑得最多？",
                    "哪些车这个月还没出过车？",
                    "司机这个月的运费结了吗？",
                ),
            ),
            AiSuggestCategory(
                "账目",
                listOf(
                    "把这个月的货主账单导成表格",
                    "哪个货主欠得最多？",
                    "这个月收了多少、支出多少？",
                ),
            ),
            AiSuggestCategory(
                "商品与库存",
                listOf(
                    "有哪些商品库存到红线了？",
                    "帮我加一个商品",
                    "这个月哪些商品卖得最多？",
                ),
            ),
            AiSuggestCategory(
                "客户",
                listOf(
                    "帮我建一个货主账号",
                    "有哪些货主这个月一单没下？",
                ),
            ),
        ),
    )

    private val SHIPPER_PACK = AiSuggestPack(
        first = listOf(
            "帮我下一单",
            "帮我加一个常用地址",
            "帮我加一个常用联系人",
            "有哪些商品能下单？",
        ),
        categories = listOf(
            AiSuggestCategory(
                "下单",
                listOf(
                    "帮我下一单",
                    "有哪些商品能下单？",
                    "上次那单照原样再来一单",
                ),
            ),
            AiSuggestCategory(
                "地址与联系人",
                listOf(
                    "帮我加一个常用地址",
                    "我有几个常用地址？",
                    "帮我加一个常用联系人",
                ),
            ),
            AiSuggestCategory(
                "我的订单",
                listOf(
                    "我最近的订单有哪些？",
                    "上个月那单送到哪了？",
                    "帮我撤掉还没派的单",
                ),
            ),
            AiSuggestCategory(
                "账本",
                listOf(
                    "我这个月的账结了吗？",
                    "我还欠多少钱？",
                ),
            ),
        ),
    )

    private val MEMBER_PACK = AiSuggestPack(
        first = listOf(
            "帮我下一批货",
            "帮我建一个下级货主",
            "帮我加一个常用地址",
            "有哪些商品能下单？",
        ),
        categories = listOf(
            AiSuggestCategory(
                "下单与核销",
                listOf(
                    "帮我下一批货",
                    "这个月还有哪些单没核销？",
                    "有哪几单被撤了我还能恢复？",
                ),
            ),
            AiSuggestCategory(
                "下游货主",
                listOf(
                    "我下面有几个货主？",
                    "帮我建一个下级货主",
                    "哪个下级货主欠我最多？",
                ),
            ),
            AiSuggestCategory(
                "账本",
                listOf(
                    "我的货主欠我多少？",
                    "我这个月收了多少？",
                    "把上个月的账导成表格",
                ),
            ),
            AiSuggestCategory(
                "商品",
                listOf(
                    "有哪些商品能下单？",
                    "哪些商品库存到红线了？",
                ),
            ),
        ),
    )
}
