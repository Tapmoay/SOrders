// ⛔ 本文件由 _tools/ai/_gen_capability_snapshot.py 生成，**不许手改**。
// 改能力表请改 backend/app/core/{capabilities,role_capabilities,capability_audit_coverage}.py，
// 然后重跑：python _tools/ai/_gen_capability_snapshot.py
//
// source_hash = sha256:768fdd45c24c637a41e7bd4cc4623c52125ad29997f8e3551b56a1ca5df15bf2
//
// 它回答的唯一问题：**这个角色能不能做这件事**（指南 §R3-02：Capability → UI）。
// ⛔ 界面里不要再写 `role == Role.DISPATCHER` 来判断「能不能做某个业务动作」——问这里。
package com.tapmoay.sorders.core

object Capabilities {
    /** 能力表的指纹。判据拿它对账：Kotlin 与后端不一致就是有人手改了。 */
    const val SOURCE_HASH: String = "sha256:768fdd45c24c637a41e7bd4cc4623c52125ad29997f8e3551b56a1ca5df15bf2"

    /** 有没有「绕过角色」（后端 BYPASS_ROLES）：它不受能力表限制。 */
    val BYPASS_ROLES: Set<String> = setOf("dispatcher")

    /** 角色 → 它能做的全部能力键（含没有权限点的角色能力）。 */
    val BY_ROLE: Map<String, Set<String>> = mapOf(
        "dispatcher" to setOf("address:manage", "ledger:edit", "ledger:read_all", "notification:manage", "notification:read", "operation_log:read", "order:cancel_dispatcher", "order:create", "order:delete_cancelled", "order:dispatch", "order:edit", "order:internal_note", "order:read_all", "order:recall", "order:return", "order_product:edit", "place:manage", "price_rule:manage", "product:manage", "stats:read", "unit_conversion:manage", "user:manage", "vehicle:manage"),
        "driver" to setOf("notification:read", "order:complete_driver", "order:internal_note", "order:read_assigned", "order:upload_delivery"),
        "shipper" to setOf("address:manage", "ledger:read_own", "notification:read", "order:cancel_shipper", "order:create", "order:delete_cancelled", "order:read_own", "order:return_request", "place:manage", "shipper_ledger:read_own", "unit_conversion:manage"),
    )

    /** 能力键 → 给人看的一句话（排障/审计页直接显示它，别再各写一份）。 */
    val WHAT: Map<String, String> = mapOf(
        "order:create" to "客户（或代客）下一张新订单",
        "order:read_own" to "看自己名下的订单",
        "order:read_assigned" to "看派给自己的订单",
        "order:read_all" to "看全部订单",
        "order:cancel_shipper" to "撤销自己名下的单",
        "order:cancel_dispatcher" to "撤销任意单（含代客撤销）",
        "order:return" to "执行退货（红冲营收、回补库存、可能退现）",
        "order:return_request" to "给自己的单提退货申请",
        "order:delete_cancelled" to "把订单软删进回收站",
        "order:dispatch" to "把待派单派给某位司机",
        "order:recall" to "撤回派单（把单从司机手里收回来）",
        "order:edit" to "代客改单与拆单",
        "order:complete_driver" to "确认接单与完成配送",
        "order:internal_note" to "在订单上写内部备注",
        "order:upload_delivery" to "上传送达照片",
        "product:manage" to "维护商品目录与库存",
        "price_rule:manage" to "维护批发商专属价",
        "ledger:read_own" to "看自己那本账",
        "ledger:read_all" to "看全部账本",
        "ledger:edit" to "手工记账与核销",
        "notification:read" to "看发给自己的消息",
        "notification:manage" to "群发与管理消息",
        "operation_log:read" to "看审计日志",
        "user:manage" to "维护账号、司机名册、货主名册",
        "order_product:edit" to "增删改订单商品行",
        "stats:read" to "看报表与统计",
        "address:manage" to "地址与联系人：常用线路、联系人、地点（含图片）",
        "place:manage" to "地点库与地点分组（谁都能标自己的常用地点，派单员另有发布/下架）",
        "unit_conversion:manage" to "单位换算（一车=8 方那类），货主与派单员都能自己设",
        "shipper_ledger:read_own" to "货主自己的账（明细与汇总，只读）",
        "vehicle:manage" to "车辆名册与「这辆车归哪个司机」",
    )

    /**
     * 这个角色能不能做这件事。
     *
     * ⛔ 认不出角色 = 一律 false（fail-closed）：新角色上线时宁可少显示一个按钮，
     *    也不要因为「没见过的角色」而把界面全开出来。
     */
    fun can(role: String?, key: String): Boolean {
        val r = role?.trim()?.lowercase() ?: return false
        if (r in BYPASS_ROLES) return true
        return BY_ROLE[r]?.contains(key) ?: false
    }

    /** 这个角色手上的全部能力键（界面要「按能力筛一串入口」时用它）。 */
    fun of(role: String?): Set<String> {
        val r = role?.trim()?.lowercase() ?: return emptySet()
        if (r in BYPASS_ROLES) return BY_ROLE.values.flatten().toSet()
        return BY_ROLE[r] ?: emptySet()
    }
}
