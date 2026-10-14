package com.tapmoay.sorders.ui.dispatcher

import com.tapmoay.sorders.data.remote.dto.FreightQuoteDto

/**
 * 派单抽屉里「按路线自动带出运费」的**三条纯规则**（CHG-0129）。
 *
 * 用户 2026-10-15 口述：「运费模板已经绑定了路线，派单时路线匹配就直接带出钱。」
 *
 * 后端已经把「这一单的地点路线 ↔ 模板绑的那条路线」算完了
 * （`GET /freight-templates/quote?closest=true` 回 `matched` = 他挑中的那一条价目、
 * `why` = 凭什么挑它），这一份只管界面上那三条规矩：
 *
 * ① 自动带出来的是**默认值**：派单员手一改就以他改的为准 ——
 *    ⛔ 谁也不许在他改完之后再把它覆盖回去（[shouldOverwriteFreight]）；
 * ② **匹配不上就什么也不填**（[autoFreightOf] 返回 null）—— 不许猜一个价填进去，界面维持原样；
 * ③ 带了哪一条、凭什么，要**显示出来**（[autoHint]）—— 用户要看得见他为什么看到这个价。
 *
 * ⛔ 这里不算钱、也不挑价目：挑哪一条、那条多少钱，唯一实现在后端
 *    `backend/app/services/freight_route_autofill.py`（「多条命中取最贴近」就在那里）。
 *    界面再算一份的后果是「同一单两个价」，而两边都不报错。
 * ⛔ [AutoFreight.fee] 是**值**不是给人看的字：它直接进**可编辑**的运费框，
 *    所以不过 `formatMoney`（那会把 `12.3456` 显示成 `12.35` —— 用户没改价、价却真的变了，
 *    见 `android/app/src/main/java/com/tapmoay/sorders/util/Money.kt` 那段「显示 vs 值」）。
 */
data class AutoFreight(
    /** 这一条价目的钱 —— **后端 `Decimal` 出来的原样字符串**，直接进输入框。 */
    val fee: String,
    /** 价目编号（同一条路线上有多条时，用户要对得上号）。 */
    val templateId: Long,
    /** 价目名：界面上「选了谁」就是它（没名字时给一个对得上号的兜底）。 */
    val templateName: String,
    /** 后端给的一句话：凭什么挑它（可能为空）。 */
    val why: String,
)

/**
 * 后端 `closest=true` 的报价 → 要带进运费那一格的钱；**匹配不上 = `null`**。
 *
 * ⛔ 「什么也不填」的三种情形：后端没给 `matched`（这条路线没有价目 / 都不是这类货的）、
 *    钱那一栏是空白、或者压根没问出结果（`q` 为 null）。三种都**不许拿 0 顶上** ——
 *    填一个 0 就是替用户定了一次价（而真正的价可能只是一时问不出来）。
 */
fun autoFreightOf(q: FreightQuoteDto?): AutoFreight? {
    val m = q?.matched ?: return null
    val fee = m.fee.trim()
    if (fee.isEmpty()) return null
    return AutoFreight(
        fee = fee,
        templateId = m.templateId,
        templateName = m.name.trim().ifBlank { "价目 #" + m.templateId },
        why = q.why.trim(),
    )
}

/**
 * **手改优先**：这一格被派单员自己动过之后，自动带价再也不许覆盖它。
 *
 * 用户口径（2026-10-15）：自动带出的只是默认值，改过就以改过的为准。
 * 单独抽成函数是为了让这条规则**只有一处**：界面、VM、以及在途请求回来的时候都问它 ——
 * 各写一遍 `if (!touched)` 迟早会有一处写反，而写反的表现正是「把人填的数盖回去」。
 */
fun shouldOverwriteFreight(touchedByHand: Boolean): Boolean = !touchedByHand

/** 自动带出之后那一行说明（说了选了谁、凭什么，以及「可改」）。 */
fun autoHint(a: AutoFreight): String =
    "已按路线自动带出「" + a.templateName + "」—— 可改，改过之后不再自动覆盖" +
        (if (a.why.isBlank()) "" else "；" + a.why)

/** 这一格被派单员手改（或亲手套了模板）之后那一行说明。 */
fun manualHint(): String = "运费是你自己填的 —— 自动带价不会再改它"

/** 匹配不上：**什么也不填**，但把「为什么没匹配上」如实说清（后端给的话原样显示）。 */
fun noMatchHint(reason: String): String =
    (if (reason.isBlank()) "这条路线没有匹配的价目" else reason.trim()) + " —— 运费留空，自己填"

/** 后端没问出来（断网/超时）：同样什么也不填，且不许假装「这条路线没有价目」。 */
fun failedHint(message: String?): String {
    val m = message?.trim().orEmpty()
    return "自动带价没问出来（" + m.ifEmpty { "网络错误" } + "）—— 运费留空，自己填"
}

/**
 * 这辆车能不能给后端当「最贴近」的排序参考：只认后端认的那三个值（`small/large/trailer`），
 * 别的（没设置车型、老数据里的中文）一律当**没填**。
 *
 * 为什么不原样透传：后端 `_validate_vehicle` 对不认识的值是 **400**，
 * 而 400 的后果不是「少一条排序线索」，是**这次自动带价整个没了**（连匹配得上的价都不带）。
 */
fun vehicleForAutofill(raw: String?): String? {
    val v = raw?.trim().orEmpty()
    return if (v in AUTOFILL_VEHICLES) v else null
}

/** 后端 `freight_templates.vehicle_type` 的取值（与 `api/v1/freight_templates.py::_VALID_VEHICLE` 同源）。 */
val AUTOFILL_VEHICLES = setOf("small", "large", "trailer")
