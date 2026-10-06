package com.tapmoay.sorders.ui.common

/**
 * # 下单时「收货人 / 下单人」四个联系字段**不能全空** —— 客户端唯一一份判据（台账 L-32）
 *
 * 用户原话（m01132）：
 * > 「这个**是不可能存在**的 —— **无主账是不可能存在的**……我们在**下单的时候也会做个限制：
 * >  两个必须选一个，必须要有一个是有信息的**。」
 *
 * 定稿判定式（m01199）：收货人名字 / 收货人电话 / 下单人名字 / 下单人电话 四个字段里
 * **任意一个非空**即合格（名字或电话任选其一就够）。
 *
 * ## 为什么单独一个文件
 * 同一件事在**三处**说：这一份（下单页）、后端命令层
 * （`backend/app/services/order_contact.py::CONTACT_INFO_REQUIRED`，用户 m01242 要求"干脆后端也拦一下"）、
 * AI 的核心规范（`ai/AiAnswerStyle.kt` 第 10 条）。三处各写一遍的后果是**判定式会走散**——
 * "到底能不能只填电话"变成三个答案，而用户看到的提示字也不一样。
 * 所以客户端只有这个文件里的一个常量 + 一个纯函数，别处一律引用它。
 *
 * ## 两条刻意的边界
 * - ⛔ **不自造信息**：不替用户编一个名字或电话（编出来的电话打不通，编出来的名字会把账记到别人头上）。
 *   后端"下单人＝货主"的兜底走的是**账号资料**（`backend/app/commands/order.py::create_order`），
 *   与客户端无关；货主自己下单那条路后端**不兜底**，所以这里必须留空就拦。
 * - 只做**提交前**这一道（用户体验），真正的保险是后端那道硬拦 —— 两边判的是同一件事。
 */

/** 四个联系字段全空时对用户说的那一句话（后端那条同源文案的客户端副本，字面一致）。 */
const val CONTACT_REQUIRED_MESSAGE = "请填写收货人或下单人（名字或电话，至少一个）"

/**
 * 四个联系字段**全空** ⇒ `true`（这一单在账上认不出人，不许提交）。
 *
 * ⚠️ 纯空格算空：与后端 `order_contact.contact_info_missing` 的 `strip()`、
 * 账本 SQL 的 `nullif(trim(…))` 同一口径。
 */
fun contactInfoMissing(
    dongjiaName: String?,
    dongjiaPhone: String?,
    bossName: String?,
    bossPhone: String?,
): Boolean = listOf(dongjiaName, dongjiaPhone, bossName, bossPhone).all { it.isNullOrBlank() }
