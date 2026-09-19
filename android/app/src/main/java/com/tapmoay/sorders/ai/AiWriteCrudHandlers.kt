package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import java.math.BigDecimal

/**
 * 通用 CRUD 动作的处理器：**校验 → 解析名字 → 造 payload → 渲染摘要**。
 *
 * 一类动作（"改某个既有实体的某几个字段"）的全部差异只在四件事：
 * 先查谁、收哪些字段、摘要怎么写、调哪个接口。这个类把那四件事之外的**全部**做掉：
 * 必填校验、类型校验、金额上限、枚举归一、名字→编号、payload 拼装、卡片登记。
 *
 * ### 为什么必须收敛成一份
 * 26 个动作各写一遍"金额上限"，结果一定是**有一个忘了写**——而那个就是记错钱的那个，
 * 且它不会报错。校验规则只允许有一处实现（[AiWriteArgs]），这里只负责"选哪条"。
 *
 * ### 两条不变量
 * 1. [AiWriteHandler.prepare] 里**不碰后端写接口**（红线 §2f-2 会扫）。
 * 2. [AiWriteCard.payload] 与摘要读的 `refs/values` **同源**，
 *    所以"卡片上写的"和"真正发出去的"不可能分叉。
 */
class CrudWriteHandler(
    private val action: AiWriteAction,
    private val spec: CrudSpec,
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override val actionId: String = action.id

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        // ---- 1. 目标实体：只收名字，编号这里自己找 ----
        val refs = LinkedHashMap<String, AiName?>()
        for (t in spec.targets) {
            val raw = AiWriteArgs.str(params, t.param)
            if (raw == null) {
                if (t.required) throw AiWriteArgException("缺少 ${t.param}：${t.hint}")
                refs[t.param] = null
                continue
            }
            refs[t.param] = AiWriteArgs.strict(
                query = raw,
                pool = t.lookup(ds, raw),
                kind = t.cn,
                code = t.code,
                allowMissing = t.allowMissing,
            )
        }

        // ---- 2. 字段：逐条按类型校验 ----
        val values = LinkedHashMap<String, JsonElement>()
        for (f in spec.fields) {
            validate(f, params)?.let { values[f.name] = it }
        }

        // ---- 2b. 「什么都没改」的空卡直接拒绝 ----
        // 一张什么都不改的卡只会让用户困惑：他点了确认，然后什么都没发生——
        // 而他会以为系统坏了。规则放在这里而不是每个动作里：所有"部分更新"动作都需要它，
        // 漏一个就多一张废卡（26 个动作，手工漏一个几乎是必然的）。
        //
        // ⚠️ 例外只有一类，而且要**显式声明**（[CrudSpec.allowTargetOnly]）：改动本身
        //    落在一个关联对象上（`vehicle.update` 换司机），字段自然全是空的。
        //    用"refs 里有几个目标"去自动判断是不行的：绝大多数动作本来就有目标参数
        //    （"改商品"的目标就是那个商品），那样这条检查就等于没有。
        if (spec.fields.isNotEmpty() && spec.fields.none { it.required } && values.isEmpty() &&
            !spec.allowTargetOnly
        ) {
            throw AiWriteArgException("你没有说要改哪一项。请先问用户到底要改什么，再提交。")
        }

        // ---- 3. 地址类动作：把地址文字换成坐标（高德地理编码，只读，不碰后端）----
        val geo = geocode(spec, ds, values)

        // ---- 4. payload 与摘要同源 ----
        val payload = buildJsonObject {
            for (t in spec.targets) {
                val id = refs[t.param]?.id
                if (id != null) {
                    put(t.key, id)
                } else if (t.param in spec.alwaysIncludeTargets) {
                    // ⚠️ **一定要带上这个键，哪怕它是空的**（v3.44）：`vehicle.set_driver`
                    //    的"解绑"就是"司机那一项不填"，而撤回是**按 payload 里有哪些键**去写回旧值的
                    //    （`AiRevert.patchPlan` 遍历 payload）——payload 里没有 `driver_id`，
                    //    撤回就没有任何东西可写，那张卡上的「撤回」按钮会**永远挂不上**。
                    //    写成 JsonNull 之后语义也对得上：后端"缺省或 null 都 = 解绑"。
                    put(t.key, JsonNull)
                }
            }
            for ((name, v) in values) {
                // 坐标不是"字段"，它是 geocodeFrom 那个字段的派生物，没有对应的 AiFieldSpec
                if (name == GEO_LAT || name == GEO_LNG) put(name, v)
                else put(spec.fields.first { it.name == name }.key, v)
            }
        }
        val card = AiWriteCard(
            refs = refs,
            rawValues = values,
            keyOf = spec.fields.associate { it.name to it.key },
            payload = payload,
        )

        return AiWriteOutcome.NeedConfirm(
            store.offer(
                actionId = action.id,
                title = action.title,
                risk = action.risk,
                summary = spec.headline(card),
                detailLines = spec.details(card) + listOfNotNull(geoNote(spec, geo)),
                payload = payload,
            ),
        )
    }

    /**
     * ⚠️ v3.27 起**这个处理器不再自己实现撤回**：撤回只有一处（[AiRevert] + [AiResources]）。
     * 原来这里有一段 `prepareUndo`，只处理删除类，还在注释里写着"改类动作的撤回需要另一套
     * （before 快照 + 反向 update）"。那"另一套"现在做好了：按资源声明一次读回，
     * 改类动作**全部**自动获得一键撤回。
     */
    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        spec.commit(ds, payload)
    }

    /**
     * 把 [CrudSpec.geocodeFrom] 指的那个字段的文本交给高德换坐标，写进 `values`
     * 的 [GEO_LAT]/[GEO_LNG]（于是**卡片和 payload 都能读到它**，不会分叉）。
     *
     * 三档行为：
     * - 没配 `geocodeFrom` / 这次没填那个字段 → 什么都不做（例如"只改电话"）；
     * - 定位到了 → 坐标进 payload；
     * - 没定位到 → 新建类动作**照常弹卡**（地址本身是真的，只是地图上找不到，
     *   卡片会写明）；改地址类动作（`geocodeRequired`）**当场拒绝**——见那条注释。
     */
    private suspend fun geocode(
        spec: CrudSpec,
        ds: AiWriteDataSource,
        values: LinkedHashMap<String, JsonElement>,
    ): Pair<Double, Double>? {
        val key = spec.geocodeFrom ?: return null
        val param = spec.fields.firstOrNull { it.key == key }?.name ?: return null
        val text = (values[param] as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotBlank() } ?: return null

        val hit = ds.geocode(text)
        if (hit != null) {
            values[GEO_LAT] = JsonPrimitive(hit.first.toString())
            values[GEO_LNG] = JsonPrimitive(hit.second.toString())
            return hit
        }
        if (spec.geocodeRequired) {
            throw AiWriteArgException(
                "「$text」在地图上定位不到，这条地址先不改。" +
                    "照改的话司机点导航会被带到这条地址**上一版**的位置去，而且不会有任何提示。" +
                    "请让用户把地址说得更完整（带上城市和区/路名），或者回 App 用地图选点改一次。",
            )
        }
        return null
    }

    /** 新建类动作定位失败时，把后果**写在卡上**（不写在卡上的后果＝用户不知道的后果）。 */
    private fun geoNote(spec: CrudSpec, geo: Pair<Double, Double>?): String? = when {
        spec.geocodeFrom == null || geo != null -> null
        else -> "⚠️ 这个地址没在地图上定位到，没存坐标：司机点「高德导航」时会落到高德首页，" +
            "得自己再搜一遍地址。想准就回 App 用地图选点改一次。"
    }

    // ------------------------------------------------------------------ 校验

    /** @return null = 没填（且不是必填）。任何不合法都抛 [AiWriteArgException]。 */
    private fun validate(f: AiFieldSpec, params: JsonObject): JsonElement? {
        val raw = AiWriteArgs.str(params, f.name)
        if (raw == null) {
            if (f.required) throw AiWriteArgException("缺少 ${f.name}：${f.hint}")
            return null
        }
        return when (f.type) {
            AiFieldType.TEXT -> JsonPrimitive(AiWriteArgs.text(raw, f.cn, f.maxChars))
            AiFieldType.MONEY ->
                JsonPrimitive(AiWriteArgs.parseMoney(raw, f.cn, mustPositive = f.positive).toPlainString())
            AiFieldType.COUNT -> JsonPrimitive(AiWriteArgs.parseQuantity(raw))
            AiFieldType.DELTA -> JsonPrimitive(parseDelta(raw, f))
            AiFieldType.NON_NEGATIVE -> JsonPrimitive(AiWriteArgs.parseNonNegative(raw, f.cn))
            AiFieldType.DATE -> JsonPrimitive(
                (AiWriteArgs.parseDate(raw, f.cn)
                    ?: throw AiWriteArgException("$f.cn 不能为空")).toString(),
            )
            AiFieldType.BOOL -> JsonPrimitive(
                AiWriteArgs.parseBool(params, f.name)
                    ?: throw AiWriteArgException("${f.cn} 要填 true 或 false（是/否）。"),
            )
            AiFieldType.ENUM -> JsonPrimitive(resolveEnum(raw, f))
        }
    }

    /**
     * 库存增减量：可正可负、**不许是 0**。
     *
     * 为什么单独一种类型：库存动作里"入库 +50"和"出库 -50"是同一个字段，
     * 用 [AiFieldType.COUNT]（≥1）会直接把出库挡掉；用金额规则又会带上"元"的语义。
     * 另外 0 必须拒绝——"调整 0 件"是一次没有任何效果却会留下一条流水的操作。
     */
    private fun parseDelta(raw: String, f: AiFieldSpec): Int {
        val v = raw.trim().removePrefix("+").trim().toIntOrNull()
            ?: throw AiWriteArgException("${f.cn}「$raw」不是整数。入库填正数（如 50），出库填负数（如 -50）。")
        if (v == 0) throw AiWriteArgException("${f.cn} 不能是 0——那不会改变库存，只会留下一条没意义的流水。")
        if (v > MAX_DELTA || v < -MAX_DELTA) {
            throw AiWriteArgException("${f.cn} 是 $v，超过了 ±$MAX_DELTA 的上限，请先核对。")
        }
        return v
    }

    /** 枚举归一：收英文值，也收中文别名（用户说"计件"，模型多半会照抄）。 */
    private fun resolveEnum(raw: String, f: AiFieldSpec): String {
        val v = raw.trim()
        val code = when {
            f.enumValues.any { it.equals(v, ignoreCase = true) } -> f.enumValues.first { it.equals(v, ignoreCase = true) }
            f.aliases.containsKey(v) -> f.aliases.getValue(v)
            else -> f.aliases.entries.firstOrNull { it.value.equals(v, ignoreCase = true) }?.value
        }
        if (code == null) {
            val allowed = f.enumValues.joinToString("、") { ev ->
                val alias = f.aliases.entries.firstOrNull { it.value == ev }?.key
                if (alias == null) ev else "$ev（$alias）"
            }
            throw AiWriteArgException("${f.cn}「$raw」不是有效取值。只能是：$allowed。")
        }
        return code
    }

    companion object {
        /** 库存增减量的绝对值上限（防"多打了几个零"）。 */
        const val MAX_DELTA = 1_000_000

        /** 金额上限复用 [AiWriteArgs.MAX_AMOUNT]，不在这里再写一个数。 */
        val MAX_AMOUNT: BigDecimal get() = AiWriteArgs.MAX_AMOUNT
    }
}

// ============================================================== 规格小工具
//
// 下面这几行是为了让"一个动作"读起来像一句话，而不是一堆嵌套构造。
// 它们**只做参数收集**，任何校验都不许在这里发生（否则校验又变成两份）。

internal fun targetProduct() = AiTargetSpec(
    param = "product", cn = "商品", key = "product_id",
    hint = "商品名（用用户平时叫的名字）",
    lookup = { ds, _ -> ds.products() },
)

internal fun targetShipper() = AiTargetSpec(
    param = "shipper", cn = "批发商/货主", key = "shipper_id",
    hint = "批发商或货主的名字",
    lookup = { ds, q -> ds.searchShippers(q, 20) },
)

internal fun targetUser(cn: String, role: String? = null) = AiTargetSpec(
    param = "user", cn = cn, key = "user_id",
    hint = "$cn 的姓名（或手机号）",
    // ⚠️ 只对**这个角色有意义**的动作必须传 `role`（2026-09-19 审计）：
    //    不传就是全角色名册，而"给货主改司机计费方式"在后端是**静默空转**（200、零改动、无日志）。
    lookup = { ds, q -> if (role == null) ds.users(q) else ds.usersOfRole(q, role) },
)

internal fun targetAddress() = AiTargetSpec(
    param = "address", cn = "地址/线路", key = "address_id",
    hint = "地址的收货人 + 地址（如「张三 测试路 1 号」），或者只写其中一段",
    lookup = { ds, _ -> ds.addresses() },
)

internal fun targetLocation() = AiTargetSpec(
    param = "location", cn = "地点", key = "location_id",
    hint = "地点的名字",
    lookup = { ds, _ -> ds.locations() },
)

/**
 * 共享地点（**全库共用**那一张表里的点）。
 *
 * ⛔ 与 [targetLocation] 完全是两回事，卡片上的名字必须区分开：
 * 那个是"**你自己**的地点库"，这个是"**所有人都看得到**的共享库"。
 * 用户分不清这两个的话，「删掉这个地点」会被理解成"删我自己的"，而实际影响的是所有人。
 */
internal fun targetPlace() = AiTargetSpec(
    param = "place", cn = "共享地点", key = "place_id",
    hint = "共享地点库里那个地点的名字（或它那一整条地址）",
    lookup = { ds, _ -> ds.places() },
)

internal fun targetContact() = AiTargetSpec(
    param = "contact", cn = "联系人", key = "contact_id",
    hint = "联系人姓名或手机号",
    lookup = { ds, _ -> ds.contacts() },
)

internal fun textField(name: String, cn: String, hint: String, required: Boolean = false, maxChars: Int = 200) =
    AiFieldSpec(name, cn, AiFieldType.TEXT, hint, required, maxChars = maxChars)

internal fun moneyField(
    name: String,
    cn: String,
    hint: String,
    required: Boolean = false,
    positive: Boolean = true,
    key: String = name,
) = AiFieldSpec(name, cn, AiFieldType.MONEY, hint, required, positive = positive, key = key)

internal fun boolField(name: String, cn: String, hint: String) =
    AiFieldSpec(name, cn, AiFieldType.BOOL, hint)

internal fun enumField(
    name: String,
    cn: String,
    hint: String,
    values: List<String>,
    aliases: Map<String, String> = emptyMap(),
    key: String = name,
) = AiFieldSpec(name, cn, AiFieldType.ENUM, hint, required = true, enumValues = values, aliases = aliases, key = key)

internal fun dateField(name: String, cn: String, hint: String) =
    AiFieldSpec(name, cn, AiFieldType.DATE, hint)
