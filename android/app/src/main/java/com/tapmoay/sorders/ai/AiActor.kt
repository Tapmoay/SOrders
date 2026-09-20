package com.tapmoay.sorders.ai

/**
 * 「这一次对话是谁在用」= **角色 + 他是不是批发商货主**。
 *
 * ### 为什么要多这一维（2026-09-20 用户第七轮）
 * > 「AI 也会分成 2 个：一个是**普通货主**、一个是**批发商货主**的 AI。相应的权限和能力跟
 * >   对应角色的**所有功能和权限进行统一**……他**不能越权**：批发商没有的功能 AI 也做不到；
 * >   普通货主**做不到的事情、也就是他手机做不到的事情，AI 也做不到**。」
 *
 * 手机上这两个货主**长得就不一样**：批发商那本「我的账本」多一段"我的货主欠我多少"，
 * 每一单能**核销**（整单/按商品）、能**撤销**、能**恢复**；普通货主那一页只有
 * 搜索 + 时间 + 订单列表 + 一个「欠总分销商」合计（他给自己下单，没有第二个债务人）。
 *
 * 在那之前，AI 这一侧只有「角色」一个维度：核销那三个动作在**两个人的清单里都出现**，
 * 只在 `prepare` 里问一句 `isMemberShipper()` 才拦。后果不是安全问题（后端一定 403），
 * 而是**普通货主会看见一张点了必然失败的卡** —— 本仓库把"能看见但用不了"
 * 明确列为最坏的一类 bug（模型还会照着这张卡跟用户解释一通）。
 *
 * ### fail-closed
 * 认不出角色 → `null`（一个动作/一张表都不给）；
 * 是不是批发商**没问出来**时按 `false` 算 —— 少给会立刻被发现，多给不会有人发现。
 */
data class AiActor(
    val role: AiRole,
    /** 只对 [AiRole.SHIPPER] 有意义：`users.is_member=1`（批发商）。 */
    val memberShipper: Boolean,
) {
    companion object {
        /**
         * 装配入口。`memberShipper` 只对货主生效（派单员/司机传了也没用），
         * 免得某天有人"顺手"给派单员开了一个货主专属的动作。
         */
        fun of(role: AiRole?, memberShipper: Boolean): AiActor? =
            role?.let { AiActor(it, memberShipper && it == AiRole.SHIPPER) }

        /**
         * **只知道角色**时用的那一个：货主按**普通货主**算（fail-closed）。
         *
         * 给谁用：设置页预览、纯逻辑单测、以及"还没问出 is_member"的那一小段窗口。
         * ⛔ 真正发工具清单/执行写操作的两条路**必须**传真的那个（见 `AiTools.memberProvider`
         *   与 `AiWriteService.actorProvider`），否则批发商会莫名其妙少掉核销能力。
         */
        fun byRole(role: AiRole?): AiActor? = of(role, memberShipper = false)
    }
}
