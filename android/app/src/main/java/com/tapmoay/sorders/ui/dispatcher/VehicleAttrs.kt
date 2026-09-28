package com.tapmoay.sorders.ui.dispatcher

/**
 * 车辆属性的**界面侧镜像**（真源在后端 `backend/app/services/vehicle_attrs.py`）。
 *
 * ## 为什么要有一份镜像
 * 界面要**离线**画出"这辆车该填哪些项"（打开抽屉时不能等一个网络往返才知道表单长什么样），
 * 所以这张表必须编译进 App。⛔ 但它是**镜像**，不是第二份真相：
 * 后端那份说了算（校验、错误文案、出参的 `body_label` 都从它来）。
 * 两份不一致时 `_tools/qa/_check_vehicle_attrs.py` 会**报红**（它逐项比对键 / 叫法 / 量纲 /
 * 适用型式），所以别只改一边。
 *
 * ## 车型与车身型式是两件事（用户 2026-09-27 要的「车辆属性」）
 * * **车型**（`vehicles.vehicle_type`：小货车 / 大货车 / 挂车）＝ **这辆车按什么算钱**。
 *   它被司机计费规则 / 运费模板 / 司机应付共用，其中「挂车→按单计费、其余→固定工资」**是钱**
 *   ⇒ ⛔ 界面上那几个 chips（[VEHICLE_TYPES]）**一个取值都不许加**。
 * * **车身型式**（`vehicles.body_type`：箱式车 / 平板车 / 自卸车 / 挂车 / 未设置）＝
 *   **这辆车能填哪些属性**，只有这张台账在用。
 *
 * ## 吨 / 方 是通用项
 * 需求方原话：「主要的是**吨和方**这种即便（计量）单位」—— 它们是**任何一辆货车都有**的
 * 容量事实（缺了它"一车 = 多少方 / 多少吨"就没有依据），所以对每一种型式都开放；
 * 其余（车厢 / 台面 / 车斗的尺寸、轴数）严格按型式区分。
 * ⛔ 本文件**只描述表单**，一个字节的金额都不算（换算的接法见 FEAT-0005）。
 */

/** 所有型式都能填的属性（含"未设置"）。 */
private val ALL_BODIES = setOf("", "box", "flat", "dump", "trailer")

/** 有货厢（车厢 / 台面 / 车斗）的型式。 */
private val HAS_BED = setOf("box", "flat", "dump")

/** 货厢有**高度**的型式 —— ⛔ 平板车没有「台面高」（需求方给的清单里就没有这一项）。 */
private val HAS_BED_HEIGHT = setOf("box", "dump")

/** 只有挂车有的一项。 */
private val TRAILER_ONLY = setOf("trailer")

/**
 * 车身型式的 chips（**顺序即界面顺序**：常见车型在前，「未设置」垫底）。
 *
 * ⚠️ 这里的中文名与后端 `BODY_LABELS` **逐字相同**（判据会比对）——
 * 但**显示一辆已存的车**时要用后端回的 `VehicleDto.bodyLabel`，不要拿这张表去查：
 * 后端将来多一个取值时，老客户端查不到会显示原始码。
 */
internal val BODY_CHOICES: List<Pair<String, String>> = listOf(
    "box" to "箱式车",
    "flat" to "平板车",
    "dump" to "自卸车",
    "trailer" to "挂车",
    "" to "未设置",
)

/**
 * 一项车辆属性。
 *
 * @param key 接口与库里的键（**一列一个事实**）
 * @param label 通用中文名（自卸车的"容积"另有叫法，见 [perBody]）
 * @param unit 量纲 —— ⛔ 必须画在输入框标题上：车高不带单位时，4 与 400 在界面上都像是对的
 * @param bodies 哪些型式能填它
 * @param perBody 按型式换叫法（车厢长 / 台面长 / 车斗长是**同一个事实**）
 * @param integer 必须填整数（目前只有轴数）
 */
internal data class VehicleAttrField(
    val key: String,
    val label: String,
    val unit: String,
    val bodies: Set<String>,
    val perBody: Map<String, String> = emptyMap(),
    val integer: Boolean = false,
)

/**
 * ⭐ **属性表的唯一一份（界面侧）** —— 改这里就是改"一辆车能填哪些属性"，
 * 那是一条要重新拍板的事（需求方 2026-09-27 逐条批准过），不是顺手加一行。
 *
 * ⚠️ 写法要与 `_tools/qa/_check_vehicle_attrs.py` 的解析对齐（一行一项、参数按上面的顺序）。
 */
internal val VEHICLE_ATTR_FIELDS: List<VehicleAttrField> = listOf(
    VehicleAttrField("height_m", "车高", "米", ALL_BODIES),
    VehicleAttrField("width_m", "车宽", "米", ALL_BODIES),
    VehicleAttrField("curb_weight_t", "净重", "吨", ALL_BODIES),
    VehicleAttrField("load_tons", "载重", "吨", ALL_BODIES),
    VehicleAttrField("volume_cubic", "容积", "方", ALL_BODIES, mapOf("dump" to "斗容")),
    VehicleAttrField("cargo_length_m", "货厢长", "米", HAS_BED, mapOf("box" to "车厢长", "flat" to "台面长", "dump" to "车斗长")),
    VehicleAttrField("cargo_width_m", "货厢宽", "米", HAS_BED, mapOf("box" to "车厢宽", "flat" to "台面宽", "dump" to "车斗宽")),
    VehicleAttrField("cargo_height_m", "货厢高", "米", HAS_BED_HEIGHT, mapOf("box" to "车厢高", "dump" to "车斗高")),
    VehicleAttrField("axle_count", "轴数", "个", TRAILER_ONLY, integer = true),
)

/** 这一项在**这种车**上叫什么（箱式车的 `cargo_length_m` 叫「车厢长」）。 */
internal fun attrLabel(f: VehicleAttrField, body: String?): String =
    f.perBody[body?.trim().orEmpty()] ?: f.label

/** 带量纲的完整叫法：「载重(吨)」—— 输入框标题与校验提示共用这一处。 */
internal fun attrTitle(f: VehicleAttrField, body: String?): String = attrLabel(f, body) + "(" + f.unit + ")"

/** 这种型式**能填**哪些属性（顺序即界面顺序）。 */
internal fun attrsFor(body: String?): List<VehicleAttrField> {
    val b = body?.trim().orEmpty()
    return VEHICLE_ATTR_FIELDS.filter { it.bodies.contains(b) }
}

/** 车身型式 → 中文名（**只给 chips 用**；已存的车请用后端回的 `bodyLabel`）。 */
internal fun bodyLabelOf(raw: String?): String {
    val b = raw?.trim().orEmpty()
    return BODY_CHOICES.firstOrNull { it.first == b }?.second ?: b
}

/**
 * 卡片上那一行"这车能装多少"（`载重 12 吨 / 容积 8 方`）；一项都没填时返回空串。
 *
 * ⚠️ 只读 [com.tapmoay.sorders.data.remote.dto.VehicleDto.attrs] 里的 `load_tons` / `volume_cubic`
 * —— 那两项才是"要参与换算"的（需求方：「主要的是吨和方」）。
 * ⛔ 空串表示**没量过**，不许兜成 0：界面上"0 吨"与"没量过"是两件事。
 */
internal fun capacityText(attrs: Map<String, String>?): String {
    val parts = mutableListOf<String>()
    attrs?.get("load_tons")?.trim()?.takeIf { it.isNotEmpty() }?.let { parts += "载重 " + it + " 吨" }
    attrs?.get("volume_cubic")?.trim()?.takeIf { it.isNotEmpty() }?.let { parts += "容积 " + it + " 方" }
    return parts.joinToString(" / ")
}
