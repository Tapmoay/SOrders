package com.tapmoay.sorders.ai

import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/**
 * 撤回这件事的**唯一实现处**（v3.27 重构）。
 *
 * ## 为什么要有这个文件
 * v3.26 的做法是：**每个动作各自实现一遍撤回**。
 * 删除类动作在声明式规格里加一行 `undoAction = …`，手写动作在处理器里 override
 * `prepareUndo`，剩下的三十多个"改类"动作则在 `undoNoneOf` 里共用一句
 * 「卡片上写了改前→改后：说一句「照上面改回去」我就能改回原样（不是一键撤回）」。
 *
 * 结果是：**改类动作一个都没有一键撤回**，而且每加一个动作都要有人记得再补一遍，
 * 漏了不会报错——它只是安静地少一个能退回去的操作。用户的原话是
 * 「每次都一个一个改一个一个找，非常麻烦也非常耗时」。
 *
 * ## 现在的形状：**按「资源」声明一次，挂在它下面的动作全部自动获得撤回**
 * 撤回的形状只有四种，和业务无关：
 *
 * | 这次写的形状 | 撤回＝ |
 * | --- | --- |
 * | **改**（部分更新一条已有的） | 用**同一个动作**，把这次会改的键写回**写之前的值** |
 * | **删**（伪装删除） | 该资源的**恢复**动作（参数从写之前的现场搬） |
 * | **成对动作**（派单↔撤回派单、标记异常↔解除异常） | **另一个动作** + 一份拼好的参数 |
 * | **切换**（换角色：再换一次就换回来） | 同一个动作，只带目标 |
 *
 * 四种都需要同样一件东西：**这条记录写之前长什么样**。所以一个资源的声明就是
 * 「怎么读回它现在的值」（[AiResource.read]）；四种形状都从这一份现场推出来，
 * **不需要任何按动作写的代码**。
 *
 * ```
 *   AiResource("address", read = { ds, q -> ds.snapshot("address", q) },
 *              actions = listOf(update(ADDRESS_UPDATE), delete(ADDRESS_DELETE)),
 *              restore = AiInverse(ADDRESS_RESTORE, mapOf("target_id" to ID)))
 *            │
 *            ├─ 改地址 → 撤回卡：终点地址「新路 1 号 → 撤回到 旧路 1 号」（同一个动作，旧值）
 *            └─ 删地址 → 撤回卡：把刚删的那条恢复回来（逐字段照搬）
 * ```
 *
 * ## 五条不许破的规矩
 * 1. **撤回仍然是"另一个普通动作 + 一份拼好的 payload"**：卡片照弹、角色门照过、
 *    一次性 token 照走。这里**只造方案、不写库**——唯一写库的地方还是
 *    [AiWriteService.execute] → `commit`。所以撤回永远不可能是第二条写入口。
 * 2. **快照必须在 `commit` 之前抓**（删除写下去那条就没了）。
 *    调用点在 [AiWriteService.execute]，顺序由红线 §20 钉着。
 * 3. **读不到旧值的键，不许假装能撤**：它会变成撤回卡上的一行「这一项撤不回来：…」。
 *    静默少写回一个字段，是这里最危险的一种错——用户以为撤回去了。
 * 4. **撤不回来的理由一条一句**，说清后果。见 [UNDO_NONE] 上面那段。
 * 5. **卡片上的承诺必须兑现**：卡片说"会出现撤回"，那执行完就真得有。
 *    [canRevert] 是静态判据（点确认之前就要答上来），所以它**只认声明**；
 *    运行期读不到现场这种意外由 [AiWriteService.execute] 事后如实补一句。
 *
 * ## 顺带成立的一件事：**撤回的撤回**
 * 撤回走的是普通动作，所以撤回执行完会**再挂一个撤回入口**：
 * 「恢复地址」的撤回就是「再删掉它」。这条链不是特意做的，是"撤回＝普通动作"
 * 这个形状白送的——用户来回点几次也不会掉进死角。
 *
 * ## 还没做的（写在这里，免得下次有人以为忘了）
 * 1. **新建类动作的撤回**（"撤回＝把刚建的那条删掉"）需要新建那条的编号，而编号在写之前
 *    不存在。它们现在如实写着「新建出来的那一条撤不掉，但它可以改、可以停用/下架、
 *    也可以删掉——说一句就行」——**不再是**改类那句万能话。
 * 2. **批量调价的撤回**：撤回要把它改过的**每一行**写回旧价（可能上百行），
 *    那正是 v3.21 里"部分成功"最危险的形状（用户核对不过来）。所以它如实写着
 *    "请点名要改回去的批发商"，而不是给一个看起来能一键撤回、实际可能只成功一半的按钮。
 */
object AiRevert {

    /** 「写之前的现场」里表示主键来源的标记（[AiInverse.from] 用）。 */
    const val ID: String = "#id"

    /** [AiInverse.from] 里以它开头的值是**写死的字面量**（不是从现场取）。 */
    const val LITERAL: String = "="

    // ============================================================ 查表

    /** 这个动作挂在哪个资源下；null = 它不是"改一条已有记录"，撤不回来（理由另写）。 */
    fun resourceOf(actionId: String): AiResource? = AiResources.TABLE.firstOrNull { it.action(actionId) != null }

    /** 这个动作的撤回走哪个动作（用于卡片上写清"撤回本身会做什么"）。 */
    fun inverseActionOf(actionId: String): String? {
        val res = resourceOf(actionId) ?: return null
        val entry = res.action(actionId) ?: return null
        return when {
            entry.deletes -> res.restore?.actionId
            else -> entry.inverse?.actionId ?: entry.id
        }
    }

    /**
     * 这个动作**能不能一键撤回**（静态判据）。
     *
     * 卡片最后那一行就是按它写的——所以它必须在**点确认之前**就能答上来。
     * 它只认声明，不试读：试读会引入"有时能撤有时不能"的承诺，
     * 而那种承诺比"明确撤不回来"更糟。
     */
    fun canRevert(actionId: String): Boolean {
        val a = AiWrites.byId(actionId) ?: return false
        val r = resourceOf(actionId) ?: return false
        val entry = r.action(actionId) ?: return false
        // 撤回专用的恢复动作也算（它声明了成对逆操作 = "撤回的撤回"）
        if (a.undoOnly) return entry.inverse != null
        if (entry.deletes) return r.restore != null
        return true
    }

    /**
     * 撤不回来时的理由。null = 能撤。
     *
     * ### 为什么"能给的理由"必须逐条写，不许分类兜底
     * v3.26 把三十多个改类动作塞进同一句话里，理由是"都可以让我照上面改回去"。
     * 那句话看着像交代，其实是**把三十个不同的问题用一句万能答复糊过去**：
     * 钱已经付出去的、密码只存哈希的、消息已经到别人手机上的，性质完全不同。
     * 所以这里只剩**真正撤不回来**的动作，而且一条一句、说清后果
     * （红线 §20 断言：不许出现"照上面改回去"那种批量免责）。
     */
    fun blockedReason(actionId: String): String? {
        if (canRevert(actionId)) return null
        UNDO_NONE[actionId]?.let { return it }
        val a = AiWrites.byId(actionId) ?: return null
        // 撤回专用的恢复动作：它的"反悔"就是再删一次/再改一次（原动作都还在）
        if (a.undoOnly) return "恢复之后想反悔，就是把那条再删一次（每个删除动作都还在）"
        // 新建类：编号在写之前不存在，所以撤不掉——但它可以改/停用/删掉。
        // ⚠️ 兜底**只兜"新建"这一类**；别的必须在上面的表里逐条写，
        //    否则这张表又会退化成"所有没写理由的动作都说这句"，等于没检查。
        if (isCreateLike(actionId)) {
            return "新建出来的那一条撤不掉，但它可以改、可以停用/下架、也可以删掉——说一句就行"
        }
        return null
    }

    /** 卡片最后一行：「这一步误操作了怎么办」。 */
    fun cardLine(actionId: String): String? {
        val a = AiWrites.byId(actionId) ?: return null
        return when {
            a.undoOnly && canRevert(actionId) ->
                "这一步就是撤回本身；执行完那条消息上还会出现一个「撤回」，点它就是把那件事再做一次"
            a.undoOnly -> "这一步就是撤回本身；反悔的话，把那条再删/再改一次就行"
            canRevert(actionId) -> "误操作了不要紧：执行完那条消息上会出现「撤回」，点它就能改回原样"
            else -> blockedReason(actionId)?.let { "⚠️ 这一步撤不回来：$it" }
        }
    }

    /**
     * **撤回卡**上的最后一行：说的是"这次撤回本身还能不能再反悔"（v3.45，真机 E2E 抓到）。
     *
     * ### 为什么必须和 [cardLine] 分开
     * 撤回走的是**另一个已有的写动作**（删专属价 → 撤回走的是"设专属价"）。卡片的最后一行
     * 由暂存区统一按 `actionId` 拼——于是真机上出现了这样一张卡：
     * ```text
     * 撤回：把批发商专属价恢复回来          ← 标题说这是「撤回」
     * 专属价在库里是软删（行还在），这一下会「把原来那一行复活」，不是新建一条
     * ⚠️ 这一步撤不回来：新建出来的那一条撤不掉…   ← 却告诉用户「这一步撤不回来」
     * ```
     * 两句话在互相打架，而用户正在决定要不要点「确认」——这一行必须说的是
     * **"撤回之后如果想再反悔怎么办"**，而不是被撤回的那个动作的性质。
     */
    fun undoCardLine(actionId: String): String? {
        val a = AiWrites.byId(actionId) ?: return null
        return if (canRevert(actionId)) {
            "这次撤回本身也能再撤回：执行完新消息上照样会出现「撤回」"
        } else {
            "⚠️ 这次撤回（走的是「${a.title}」）本身撤不回来；要改回去就再说一句，我重新申请一次"
        }
    }

    /** 全部**能一键撤回**的动作 id（设置页、红线、文档都看这一份）。 */
    val CAPABLE: Set<String> get() = AiWrites.ALL.filter { canRevert(it.id) }.map { it.id }.toSet()

    // ============================================================ 造撤回方案

    /**
     * 写之前问一句：**这条记录现在长什么样，万一用户后悔了怎么退回去。**
     *
     * 返回 null = 这个动作撤不回来（或这一条已经读不到了）。
     * 调用方必须在 `commit` **之前**调它——删除写下去之后就抓不到现场了。
     *
     * @param summary 卡片摘要。撤回按钮上的字直接用它，所以按钮上写的东西
     *   和用户刚看到的那张卡**一定是同一句话**（不会"按钮说删了 A、其实删的是 B"）。
     */
    suspend fun plan(
        ds: AiWriteDataSource,
        actionId: String,
        payload: JsonObject,
        summary: String,
    ): AiUndoPlan? {
        val res = resourceOf(actionId) ?: return null
        val entry = res.action(actionId) ?: return null
        val idKey = entry.keyIn(res)

        // 只有"参数里除了主键还有别的要从现场搬"时才读现场。
        // 这一条让「撤回的撤回」成立：恢复动作的参数只有主键，而那条记录此刻正躺在
        // 回收站里（列表读不到它）——不该读就别读，否则撤回链会在第二跳断掉。
        val inverse = when {
            entry.deletes -> res.restore
            else -> entry.inverse
        }
        val needsRead = when {
            entry.repeat != null -> false
            inverse != null -> inverse.from.values.any { it != ID && !it.startsWith(LITERAL) }
            else -> true
        }
        val before = if (needsRead) {
            val id = AiRevertJson.longOf(payload[idKey]) ?: return null
            try {
                res.read(ds, id)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                null
            } ?: return null
        } else {
            AiBefore(AiRevertJson.longOf(payload[idKey]), JsonObject(emptyMap()))
        }

        return when {
            entry.deletes -> restorePlan(ds, res, actionId, before, summary)
            entry.inverse != null -> pairedPlan(ds, res, entry, entry.inverse, before, summary)
            entry.repeat != null -> repeatPlan(res, entry, payload, summary)
            else -> patchPlan(ds, res, entry, before, payload, summary)
        }
    }

    /**
     * **删**的撤回：走该资源的恢复动作，参数由 [AiInverse.from] 从（主键 / 写之前的现场）搬。
     *
     * 为什么参数要显式列出来（而不是"必然是 target_id"）：删除动作的 payload 用的是
     * `address_id`，而恢复动作读的是 `target_id`——取错不会报错，只会让撤回卡点下去
     * **什么都没发生**（v3.26 单测抓到的就是这个）。显式列出来之后，单测可以断言
     * "恢复动作要的键，`from` 全给了"。
     */
    private fun restorePlan(
        ds: AiWriteDataSource,
        res: AiResource,
        actionId: String,
        before: AiBefore,
        summary: String,
    ): AiUndoPlan? {
        val restore = res.restore ?: return null
        if (restore.actionId == actionId) return null
        val built = AiInverse.build(restore, before) { cnOf(res, restore.actionId, it) } ?: return null
        return AiUndoPlan(
            actionId = restore.actionId,
            summary = "撤回：把${res.cn}恢复回来",
            detailLines = buildList {
                // 这两句说的是"后台是软删、逐字段照搬"。资源声明了 [AiResource.restoreLines]
                // 时换成它自己那两句——那张表的删除是真删（重建一条），照搬默认文案就是假话。
                val how = res.restoreLines ?: listOf(
                    "把刚才删掉的那一条恢复回来（后台是伪装删除：行还在，逐字段照搬）",
                    "恢复之后编号、图片、坐标、备注都和删掉之前一模一样",
                )
                how.forEach { add(it) }
                built.warnings.forEach { add(it) }
                restore.lines.forEach { add(it) }
            },
            payload = built.payload,
            label = labelOf(summary),
            // 不挂探针：那条记录此刻正躺在回收站里，`read` 读不到它是**正常的**（见 probeOf 的说明）。
        )
    }

    /**
     * **成对动作**的撤回：走另一个动作，参数从写之前的现场搬（派单↔撤回派单、
     * 标记异常↔解除异常、软删↔从回收站恢复）。
     *
     * 和 [restorePlan] 是同一种形状，唯一区别是它不由"删除"触发——所以两者共用
     * [AiInverse] 和同一个拼参数函数，不写第二份。
     */
    private fun pairedPlan(
        ds: AiWriteDataSource,
        res: AiResource,
        entry: AiRevertAction,
        inverse: AiInverse,
        before: AiBefore,
        summary: String,
    ): AiUndoPlan? {
        if (inverse.actionId == entry.id) return null
        val built = AiInverse.build(inverse, before) { cnOf(res, inverse.actionId, it) } ?: return null
        return AiUndoPlan(
            actionId = inverse.actionId,
            summary = labelOf(summary),
            detailLines = buildList {
                inverse.lines.forEach { add(it) }
                built.warnings.forEach { add(it) }
                add("撤回走的是「${AiWrites.titleOf(inverse.actionId)}」这个动作本身，所以和手工做一样留痕")
            },
            payload = built.payload,
            label = labelOf(summary),
            // 不挂探针：成对动作的撤回本来就要改掉"当初那个值"，拿它当基准去比会永远误报
            // （见 probeOf 上的说明）。
        )
    }

    /**
     * **「再做一次」型**（换角色：再换一次就换回来）。只认显式声明。
     *
     * 为什么不能默认：默认把"payload 里没有可写字段"当成"再做一次"，会把**派单**
     * 也算进去（"再派一次"绝不是撤回）。宁可多写一行声明。
     */
    private fun repeatPlan(res: AiResource, entry: AiRevertAction, payload: JsonObject, summary: String): AiUndoPlan? {
        val key = entry.keyIn(res)
        val id = payload[key] ?: return null
        return AiUndoPlan(
            actionId = entry.id,
            summary = labelOf(summary),
            detailLines = listOf(
                entry.repeat ?: return null,
                "点确认会把同一件事再做一次，效果和反向操作一样",
            ),
            payload = buildJsonObject { put(key, id) },
            label = labelOf(summary),
        )
    }

    /**
     * **改**的撤回：用**同一个动作**，把这次会改的键写回写之前的值。
     *
     * 三件事让它变成机械的（不用按动作写代码）：
     * 1. **改哪几个键，看 payload 就知道**——payload 就是这次要写出去的东西；
     * 2. **旧值从哪来**，资源的 `read` 给（键名与 payload 一致，所以能直接对上）；
     * 3. **写不回去的键**（读不到的、原来是空的、声明不许写回的）逐条写在卡上，
     *    绝不静默丢掉。
     */
    private fun patchPlan(
        ds: AiWriteDataSource,
        res: AiResource,
        entry: AiRevertAction,
        before: AiBefore,
        payload: JsonObject,
        summary: String,
    ): AiUndoPlan? {
        val key = entry.keyIn(res)
        val id = before.id ?: AiRevertJson.longOf(payload[key]) ?: return null
        val stuck = mutableListOf<String>()
        val invert = buildJsonObject {
            for ((k, v) in payload) {
                if (k == key) continue
                // ⚠️ 「不搬旧值」的键**不进这张表**：这张表是"撤回成旧值"，而它们是"这一次写一句新的"
                //    （进 payload 的部分见下面的 `replaced`）。混进来的后果实测过：
                //    卡片上会多一行 `· 原因备注：到货 → 撤回到 撤回：刚才那次库存调整（由撤回入口发起）`
                //    ——"撤回到一句新原因"是句读不通的话（反向验证那次注入把它打出来了）。
                if (k in entry.drop) continue
                if (k in entry.negate) {
                    put(k, AiRevertJson.negate(v))
                    continue
                }
                val old = before.values[k]
                when {
                    // ⚠️ 警告行也要**说人话**：这里以前直接拼 `$k`，单测随即抓到
                    //    「这一项撤不回来——address_lat」这种裸键（真机上就长这样）。
                    //    卡片上出现用户看不懂的字段名，等于没告诉他这一项没撤回来。
                    old == null -> stuck += "${cnOf(res, entry.id, k)}：${res.frozen[k] ?: "读不到它原来的值，这一项只能你自己在页面上改"}"
                    // ⚠️ "原来是空的"有两种：**清不掉**（旧接口把空值忽略掉）与**能清掉**
                    //    （`res.nullableWritable` 点名的那些，如车辆解绑司机）。
                    //    后者以前会得到一句**假话**「这个接口清不掉它」——而它明明可以（v3.44 修）。
                    old is JsonNull && k in res.nullableWritable -> put(k, JsonNull)
                    old is JsonNull -> stuck += "${cnOf(res, entry.id, k)}：${res.frozen[k] ?: "这一项原来就是空的，而这个接口清不掉它——撤回时它会保持现在的值"}"
                    else -> put(k, old)
                }
            }
        }
        /**
         * 「不搬旧值，但要补一句新的」的键（v3.45）：进 payload，但不进"撤回成旧值"那张表。
         *
         * ⚠️ 为什么不能只写进 [invert]：真机 E2E 抓到的空原因流水就是这么来的——
         * 反向那条流水的 note 是 `''`（"入库 +5（原因：真机校验B）"下面躺着"-5（原因：无）"），
         * 因为撤回把 note 整条丢掉了；而库里的流水正是**事后查账唯一的地方**。
         */
        val replaced = buildMap {
            for (k in entry.drop) {
                if (k !in payload) continue
                entry.dropWrite[k]?.let { put(k, it) }
            }
        }
        // 一件都写不回去 = 这次撤回是空转。宁可不给按钮，也不给一个按下去什么都没发生的按钮。
        if (invert.isEmpty() && replaced.isEmpty()) return null

        val lines = buildList {
            // ⚠️ 冒号后面必须有东西（真机 E2E 报告点出来的）：全是静默键时，
            //    "把这几项改回写之前的值（…）：" 后面会**一行明细都没有**，
            //    读起来像内容被吞了。所以先算出能印的行，再决定怎么起头。
            val shown = invert.keys.filterNot { it in res.silent }
            if (shown.isEmpty()) {
                // 只有编号类字段（车辆的关联司机就是这种）——印中文名，但**不印编号**：
                // 「司机：13 → 撤回到 3」这种行用户没法核对，和裸英文键一样没用。
                val names = invert.keys.joinToString("、") { cnOf(res, entry.id, it) }
                add("撤回会把这几项改回写之前的值：$names")
                add("（$names 在库里存的是内部编号，卡片上不显示编号；点确认前会再读一次现状，改过会告诉你）")
            } else {
                add("把这几项改回写之前的值（用的是同一个动作，所以和手工改一样留痕）：")
            }
            for ((k, v) in invert) {
                // ⚠️ 静默键（地址的经纬度、车辆的关联司机）**跟着写回，但不单独占一行**——真机上踩到过：
                //    这条卡上出现了 `address_lat: 39.983342 → 撤回到 40.0119719`，
                //    用户核对的是"终点地址"，两行裸英文键只会让人怀疑是不是改错了。
                //    注意这里是"不占一行"，不是"不写回"——它必须写回，否则司机会被带去旧地址。
                if (k in res.silent) continue
                add("· ${cnOf(res, entry.id, k)}：${AiRevertJson.textOf(payload[k], moneyOf(res, entry.id, k))} → 撤回到 ${AiRevertJson.textOf(v, moneyOf(res, entry.id, k))}")
            }
            for ((k, v) in replaced) {
                add("· ${cnOf(res, entry.id, k)}：不搬原来那句，写成「$v」")
            }
            entry.drop.filter { it in payload && it !in replaced }.forEach { k ->
                add("· 「${cnOf(res, entry.id, k)}」不写回（${entry.note ?: "这一次撤回不动它"}）")
            }
            // 静默键**读不回来**的时候不静默：那时候司机真的会被带去错地方，必须写在卡上。
            stuck.forEach { add("⚠️ 这一项撤不回来——$it") }
            if (entry.negate.any { it in payload }) {
                entry.note?.let { add(it) } ?: add("增减量按「相反方向再记一条」来撤回，原来那条流水留着——流水本来就该留痕。")
            }
            add("点确认前会再读一次现状：如果这几项在这之后又被改过，卡片会告诉你。")
        }
        return AiUndoPlan(
            actionId = entry.id,
            // 摘要**不套娃**：撤回的撤回，标题就是同一句话（原样再改一次）。
            // 不这么判的话，来回点两次会得到「改回原样（改回原样（改商品：红富士苹果））」
            // ——真机上看到的就是这个，用户读不出这次到底要改成什么。
            // 真正区分两次撤回的是下面那行明细（`12.00 → 撤回到 20.00`）。
            summary = if (summary.startsWith("撤回：")) summary else "撤回：${res.cn}改回原样（$summary）",
            detailLines = lines,
            payload = buildJsonObject {
                put(key, JsonPrimitive(id))
                for ((k, v) in invert) put(k, v)
                // 「不搬旧值、补一句新的」的键也在这里进 payload（卡片上单独一行说清了写什么）
                for ((k, v) in replaced) put(k, JsonPrimitive(v))
            },
            label = labelOf(summary),
            // 探针基准是**这次写进去的 payload**（不是旧值）：比较的是
            // "我们刚写的" vs "现在的"，两者不同才说明中间被人改过。
            probe = probeOf(ds, res, entry.id, payload, invert, id),
        )
    }

    /**
     * 这个键是不是金额（决定卡片上写成 `5.00` 还是 `5`）。
     *
     * 类型信息有两个来源，先看规格、再看资源表：
     * - **声明式动作**：字段规格里就写着 [AiFieldType.MONEY]，直接读；
     * - **手写动作**（改订单运费、改账本流水…）：没有字段规格，所以由资源表用
     *   [AiResource.moneyKeys] 点名。
     *
     * 为什么值得判：金额按两位小数显示是**习惯**（`5` 和 `5.00` 是同一笔钱，
     * 但「单价 5」看着像个数，「单价 5.00」一眼是钱）。而且同一张卡上两行写法不同
     * （标题写 `50.00 元`、明细写 `50`）会让用户以为是两件事。
     */
    private fun moneyOf(res: AiResource, actionId: String, key: String): Boolean =
        key in res.moneyKeys ||
            AiWrites.byId(actionId)?.crud?.fields?.firstOrNull { it.key == key }?.type == AiFieldType.MONEY

    /**
     * 一个键**在卡片上叫什么**。
     *
     * ### 为什么中文名要有第二处来源（v3.45，真机 E2E 抓到）
     * 撤回卡上真的印出过这两行：
     * ```text
     * · change：5 → 撤回到 -5
     * · 「note」不写回（…）
     * ```
     * 乍看像"漏写了两条 label"，其实是**来源不对**：[AiResource.labels] 的键集合被单测钉成
     * `readKeys`（那条断言是对的——它管的是"**读回来**的东西叫什么"），而 payload 里还有一批
     * **读不回来的键**：库存调整的 `change` / `note` 从来不在商品快照里（快照读的是商品本身），
     * 于是它们永远查不到中文名，永远以裸英文键印给用户。
     *
     * 这类键的中文名只有一个现成来源：**动作自己声明的字段规格**
     * （[CrudSpec.fields] 的 `key`/`cn`、[CrudSpec.targets] 的 `key`/`cn`）。
     * 它在"给模型看的参数说明""正向卡片的摘要"里已经用了一次，这里用第二次——
     * **声明一次、多处同源**，不会分叉；也不必给每个资源手抄一份 payload 键名。
     *
     * ### 三档顺序
     * 资源中文名 → 动作字段中文名 → 原样返回键名。
     * 最后一档正常**不该出现**：`AiWriteTest` 里那条"撤回卡上的每个 payload 键都要有中文名"
     * 会逐个动作、逐个键算出来对账（清单由脚本自己算，不手写）。
     */
    fun cnOf(res: AiResource, actionId: String, key: String): String =
        res.labels[key] ?: AiWrites.byId(actionId)?.crud?.let { spec ->
            spec.fields.firstOrNull { it.key == key }?.cn
                ?: spec.targets.firstOrNull { it.key == key }?.cn
        } ?: key

    /** 撤回按钮上的字：摘要前面已经有「撤回：」的话不再叠一层。 */
    private fun labelOf(summary: String): String = "撤回：" + summary.removePrefix("撤回：")

    // ============================================================ 点撤回时再读一次现状

    /**
     * 撤回卡**弹出来的那一刻**再读一次现场，用于一件事：
     * **这几项在执行之后又被别人改过**就如实说出来——否则用户点一下撤回，
     * 会把别人（或他自个儿）后来的改动**一起抹掉**，而他完全不知道。
     *
     * ### 为什么只给「改类」用（真机踩出来的）
     * 这个比较的语义是「**我们刚写进去的值** vs 现在的值」，只有改类动作成立：
     * - **删除类**：那条记录此刻正躺在回收站里，`read` 按定义读不到它
     *   ——"读不到"在这条路径上是**正常的**，照报就是狼来了；
     * - **成对动作**（撤回派单 ↔ 再派一次）：撤回本来就是要改掉当初那个值，
     *   拿"当初的值"当基准去比，**永远**报"被改过"。
     *
     * 所以宁可只在说得准的地方说：**错报一次，用户就学会无视所有警告**。
     *
     * @param wrote 这次实际写进去的值（比较基准）
     * @param willWrite 撤回会写成的值（警告里给用户看的）
     */
    private fun probeOf(
        ds: AiWriteDataSource,
        res: AiResource,
        actionId: String,
        wrote: JsonObject,
        willWrite: JsonObject,
        id: Long?,
    ): (suspend () -> List<String>)? {
        if (id == null) return null
        return {
            val now = try {
                res.read(ds, id)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                null
            }
            if (now == null) {
                listOf("⚠️ 现在读不到这一条了（可能已经被删掉），撤回可能失败——失败时我会如实告诉你。")
            } else {
                val changed = wrote.entries.filter { (k, v) ->
                    k != res.idKey && now.values.containsKey(k) && !AiRevertJson.same(now.values[k], v)
                }
                if (changed.isEmpty()) {
                    emptyList()
                } else {
                    listOf(
                        "⚠️ 这几项在你操作之后又被改过，撤回会把它们盖掉：" +
                            changed.joinToString("；") { (k, _) ->
                                // 金额按两位小数写——和上面那一行"撤回到 X"保持同一种写法，
                                // 同一张卡上两种写法会让用户以为说的是两件事。
                                "${cnOf(res, actionId, k)} 现在是 ${AiRevertJson.textOf(now.values[k], moneyOf(res, actionId, k))}" +
                                    "（撤回会写成 ${AiRevertJson.textOf(willWrite[k], moneyOf(res, actionId, k))}）"
                            },
                    )
                }
            }
        }
    }

    // ============================================================ 撤不回来的（逐条写清后果）

    /**
     * **撤不回来**的动作 → 为什么。
     *
     * ### 和 [AiWriteRisk] 不是一回事
     * 风险档说的是"要不要先问用户"，这张表说的是"问完之后还能不能退"。
     * 两个维度独立：**派单是 MEDIUM（要确认）但可撤回；付款给司机是 HIGH 且撤不回来**。
     * 混成一个的话，用户会以为"高风险 = 撤不回来"，于是在真正能撤的地方也不敢操作。
     *
     * ### 一条一句，不许分类兜底
     * 这里每一条都要说清**后果**（"钱已经付给司机了"），而不是"这一类都不行"。
     * 用户看完要能自己判断"那我该怎么做"。红线 §20 会拦住批量免责的写法。
     */
    private val UNDO_NONE: Map<String, String> = undoNoneTable()

    private fun undoNoneTable(): Map<String, String> {
        val m = LinkedHashMap<String, String>()
        /** 一组同类动作共用同一条理由（**最多两个**，红线会拦住"一类都不行"那种写法）。 */
        fun none(ids: List<String>, reason: String) {
            ids.forEach { m[it] = reason }
        }
        buildUndoNone(::none)
        return m
    }

    private fun buildUndoNone(none: (List<String>, String) -> Unit) {
        // ---- 钱已经出去了：不是「改一个字段」，是对方手里真的多了这笔钱 ----
        none(
            listOf(AiWrites.SETTLEMENTS_PAY),
            "钱已经付给司机了，撤不回来；付错了只能在结算单里另做一张冲的",
        )
        none(
            listOf(AiWrites.LEDGER_CREATE_RECEIPT),
            "收款一旦入账，撤回来等于把账抹掉；要改请在账本里改那一笔",
        )
        none(
            listOf(AiWrites.LEDGER_SYNC_DELIVERED),
            "补账是「一次性把一批已送达的单入账」，撤回要逐单冲、做不到一键；请在账本里改要改的那几笔",
        )
        // ---- 一批：撤回是一张几十上百行的表，用户核对不过来 ----
        none(
            listOf(AiWrites.SETTLEMENTS_GENERATE_BILLS),
            "一次生成了整月的司机账单，撤回要把这一批逐张删掉——请按月逐张作废",
        )
        none(
            listOf(AiWrites.PRICE_RULES_BATCH, AiWrites.PRICE_RULES_APPLY_TABLE),
            "一次改了「一批价」，撤回要把它改过的每一行写回旧价（可能上百行、核对不过来）；请把要改回去的批发商点名给我，我逐条改回去",
        )
        none(
            listOf(AiWrites.PRODUCTS_APPLY_TABLE),
            "一次建了「一批商品」，撤回要逐个删（而且删之前得先确认哪一个都不是你原来就有的）；" +
                "请点名要删的那几个，我逐个删给你",
        )
        // ---- 状态锁定之后就回不去了 ----
        none(
            listOf(AiWrites.SETTLEMENTS_CONFIRM),
            "结算单确认之后就锁定了（金额不能再改），撤不回来；确认错了只能先作废再重开一张",
        )
        none(
            listOf(AiWrites.SETTLEMENTS_CANCEL),
            "作废之后这张结算单就锁定了，撤不回来；重开一张就行（作废的那张会一直在账上留痕）",
        )
        // ---- 凭据：我们自己也看不到 ----
        none(
            listOf(AiWrites.USERS_SET_PASSWORD),
            "密码只存哈希，连你自己都看不到，撤不回来；忘了就让用户走「重置密码」",
        )
        // ---- 结构：一动就是好几张单 ----
        none(
            listOf(AiWrites.ORDERS_SPLIT),
            "拆单已经新建了子单并撤销了原单，撤回来要先把子单逐张删掉——请让我一步步来",
        )
        none(
            listOf(AiWrites.ORDERS_BATCH_ASSIGN),
            "一次派了一批单，撤回要逐单退回「待派单」——请按单号逐单撤回（一次说一张单）",
        )
        // ---- 发出去就到别人手机上了 ----
        none(
            listOf(AiWrites.NOTIFICATIONS_SEND, AiWrites.NOTIFICATIONS_PRICE_CHANGE),
            "消息发出去就已经到对方手机上了，撤不回来（可以在消息中心删掉自己这边的记录）",
        )
        // ---- 删掉的是自己这边的记录，没有「重建」的意义 ----
        none(
            listOf(AiWrites.NOTIFICATIONS_DELETE),
            "删掉的是自己这边的消息记录，撤不回来（原始消息在对方那里）",
        )
        // ---- 硬删：后端没有恢复入口 ----
        none(
            listOf(AiWrites.LEDGER_DELETE_ENTRY),
            "账本流水删掉之后就撤不回来了；要修请在账本里重新记一笔（金额、日期写清楚）",
        )
        // ---- 收款/挂账/撤销：后端只有「往前」的动作 ----
        none(
            listOf(AiWrites.ORDERS_PAY),
            "收款状态只能往前走：记成已收现金之后，后端没有「退回挂账」这个动作——请在订单详情里核对收款方式",
        )
        none(
            listOf(AiWrites.ORDERS_CHARGE),
            "挂账一旦记到某个挂账单位名下，撤回来等于把账从人家头上抹掉；要改请在账本里改那一笔",
        )
        none(
            listOf(AiWrites.ORDERS_CANCEL),
            "订单撤销是终态，后端没有「取消撤销」这个动作；撤错了只能重新下一张单",
        )
        // ---- 默认地址：换一条设为默认就回去了，但那要用户指定另一条 ----
        none(
            listOf(AiWrites.ADDRESS_SET_DEFAULT),
            "默认地址不是改一个字段，而是换一条当默认——请点名另一条地址，我把它设成默认就回去了",
        )
        // ---- 这两件本身不改变业务数据，只是「状态/记录」 ----
        none(
            listOf(AiWrites.NOTIFICATIONS_READ_ALL, AiWrites.NOTIFICATIONS_MARK_READ),
            "已读标记不会变回未读——但它不改变任何业务数据，只是图标变了一下",
        )
        // ---- 计费规则：换的是"以后怎么算钱"，不是某个字段的值 ----
        none(
            listOf(AiWrites.DRIVER_RULE_ATTACH),
            "换计费规则改的是「他以后每一单怎么算钱」，一键撤回做不到（要挂回原来那一份）；" +
                "告诉我挂回哪一份规则，我照做；他原来没挂规则的话，说一句「解挂」就回去了",
        )
        // ---- 一次换掉一整张表的顺序：撤回的粒度对不上 ----
        none(
            listOf(AiWrites.PRODUCT_CATEGORY_REORDER, AiWrites.PLACE_CATEGORY_REORDER),
            "重排改的是「整份名册的顺序」（不是某一条记录的一个字段），撤回要把原来那一份顺序" +
                "整份再提交一遍——而撤回入口只认「一条记录写回旧值」这一种形状。" +
                "要改回去，把想要的完整顺序再说一遍（例如「水果、冻品、干货」），我照着重排",
        )
        // ---- 共享库的撤销/发布：改的是"这个点还在不在共享库里"，撤不回来 ----
        // （⚠️ 删除**不在这里**：2026-09-19 用户要求"删除一律软删"之后 `place.delete`
        //   已经能撤回了 —— 资源表里挂着 `restore`，撤回卡会把同一条原样放回来。）
        none(
            listOf(AiWrites.PLACE_DEMOTE),
            "撤销是把那一条从共享库里移走（存进操作人自己的「我的地点」），共享库里那一行已经没了——" +
                "要让所有人都能再用它，就再「设为共享地点」一次（坐标还在，不会丢）",
        )
        none(
            listOf(AiWrites.PLACE_PUBLISH),
            "「设为共享地点」是新建类：它把一条私有地点复制进共享库，撤不回来（那条私有地点还在，没被动过）；" +
                "要收回就用「删除共享地点」（谁都选不到了）或「撤销共享地点」（收进你自己的地点库）",
        )
    }

    /** 名字不叫 `.create` 但语义是"新建一条"的动作（[blockedReason] 的兜底对它们同样成立）。 */
    private val CREATE_LIKE: Set<String> = setOf(
        AiWrites.CONTACT_UPSERT,
        AiWrites.PRICE_RULES_SET,
        AiWrites.ORDERS_ADD_LINE,
        AiWrites.LEDGER_CREATE_ENTRY,
    )

    /**
     * [blockedReason] 里那句新建类兜底是否用在了这个动作上。
     *
     * 单测要用它把"新建类"那一类和其它理由分开数：
     * 新建这一类的后果**确实是同一句话**（建错了就改/停用/删），
     * 而"改类"当初那句万能话之所以是错的，是因为它把**后果完全不同**的动作
     * （钱付了、密码改了、消息发出去了）糊在了一起。这两件事不能一起禁。
     */
    fun isCreateLikeForTest(actionId: String): Boolean = isCreateLike(actionId)

    private fun isCreateLike(actionId: String): Boolean = actionId.endsWith(".create") || actionId in CREATE_LIKE
}

/**
 * 一个**可撤回的资源**：够读出"这条记录写之前长什么样"。
 *
 * ### 声明一次，下面所有动作自动获得撤回
 * 这是这次重构的核心：撤回能力**挂在资源上，不挂在动作上**。
 * 商品这个资源声明一次读回，那么"改商品名""改单价""改报警阈值""上下架"
 * **四个动作一起有了撤回**——因为它们改的都是同一条商品。
 *
 * @param key 资源标识（同时也是 [AiWriteDataSource.snapshot] 的分支键）。
 * @param idKey 主键在 payload 里的键名（`address_id` / `product_id` …）。
 * @param actions 挂在它下面的动作（[update] / [delete] / [paired] / [switcher]）。
 * @param readKeys 读回时会给出的键（**键名与各动作 payload 一致**，所以能直接写回去）。
 * @param labels 键 → 中文名。撤回卡上写「默认单价：12.00 → 撤回到 10.00」用它。
 * @param silent 跟着写回但**不单独占一行**的派生键（如地址的经纬度——它跟着地址文字走）。
 *   `labels.keys + silent` 必须正好等于 [readKeys]（单测钉着），否则就有键在静默地进/出。
 * @param frozen 写下去就回不来的键 → 为什么。它会变成撤回卡上的一行警告。
 * @param moneyKeys 这个资源里是**金额**的键（撤回卡上按两位小数写）。
 *   只对手写动作有意义——声明式动作的字段规格里已经有 [AiFieldType.MONEY] 了。
 * @param read 读回现场：给一个主键，把这条记录现在的值读回来（键名与各动作 payload 一致）。
 *   读不到（已经删了 / 没权限）返回 null = 这一条撤不回来，**如实说，不假装**。
 * @param restore 删除之后怎么恢复；null = 这个资源的删除撤不回来。
 * @param restoreLines 删除撤回卡上那两句固定文案的**替换**；null = 用默认那两句
 *   （"后台是伪装删除，行还在，逐字段照搬"）。什么时候必须换：这个资源的删除**不是**软删
 *   （例如商品分类名册，后端就是 `db.delete`），恢复是"按原样重建一条"——
 *   照搬默认文案就是在卡上写假话（"行还在" / "编号一模一样"），而卡片上写的必须是真的。
 */
class AiResource(
    val key: String,
    val cn: String,
    val idKey: String,
    val actions: List<AiRevertAction>,
    val readKeys: Set<String>,
    val labels: Map<String, String>,
    val silent: Set<String> = emptySet(),
    val frozen: Map<String, String> = emptyMap(),
    val moneyKeys: Set<String> = emptySet(),
    /**
     * **写回 `null` 是合法取值**的键（v3.44）。
     *
     * 撤回的逻辑是"把这个键写回写之前的值"，而"写之前是空的"有两种命运：
     * 大多数接口是 `if x is not None` 语义 —— **传空值等于不改**，所以撤回只能停手，
     * 并在卡上如实说一句「这一项原来就是空的，而这个接口清不掉它」。
     * 但有些接口**能把值清掉**（车辆解绑司机：`POST /vehicles/{id}/driver` 缺省/null 都 = 解绑）。
     * 那类键必须在这里点名，否则那句警告就是**假话**，用户会以为撤不回来。
     */
    val nullableWritable: Set<String> = emptySet(),
    val read: suspend (AiWriteDataSource, Long) -> AiBefore?,
    val restore: AiInverse? = null,
    val restoreLines: List<String>? = null,
) {
    fun action(id: String): AiRevertAction? = actions.firstOrNull { it.id == id }
}

/** 资源下面的一个动作：**撤回怎么算**随它声明（默认＝把旧值写回）。 */
class AiRevertAction(
    val id: String,
    /** true = 这是"删掉一条"，撤回走资源的 [AiResource.restore]。 */
    val deletes: Boolean = false,
    /** 这个动作自己读哪个键当主键（默认用资源的 [AiResource.idKey]）。 */
    val idKey: String? = null,
    /** 逆运算是"取负"的键（库存增减量：撤回＝记一条反向流水，不是把库存改回去）。 */
    val negate: Set<String> = emptySet(),
    /** 撤回**故意不写回旧值**的键（配合 [note] 在卡上说明为什么）。 */
    val drop: Set<String> = emptySet(),
    /**
     * [drop] 里那些键**改成写什么**（v3.45）。
     *
     * ### 为什么"不搬旧值"不能顺手变成"什么都不写"（真机 E2E 抓到的空原因流水）
     * 库存调整的撤回是"再记一条反向流水"，它的 `note` 被 [drop] 掉了——理由是充分的：
     * 旧那句写的是"上一次为什么入库"，搬到反向流水上会被读成"这一次为什么出库"。
     * 但**丢掉之后没有任何东西补上来**，于是真机上出现了这样一对流水：
     * ```text
     * id=297  change=+5  note='真机校验B'      ← 用户写的
     * id=298  change=-5  note=''              ← 撤回写下的，原因空着
     * ```
     * 而"原因备注"这个字段存在的唯一目的就是**事后回查**（字段说明里写着"事后查流水全靠它"）。
     * 所以这里补一个声明：不搬旧值，但写一句**说得清这一次是什么**的固定值。
     * 卡片上也会照实写「不搬原来那句，写成「…」」——用户点确认前就知道流水上会留什么字。
     */
    val dropWrite: Map<String, String> = emptyMap(),
    /** 撤回走**另一个动作**（派单↔撤回派单、标记异常↔解除异常）。 */
    val inverse: AiInverse? = null,
    /**
     * 这个动作的撤回就是**再做一次**（换角色 = 再换回来）。
     *
     * 为什么必须显式声明：默认把"payload 里没有可写字段"当成"再做一次"，
     * 会把**派单**也算进去（"再派一次"绝不是撤回）。宁可多写一行。
     */
    val repeat: String? = null,
    /** 撤回卡上补一句（这个资源的通用规则说不清的那部分）。 */
    val note: String? = null,
) {
    /** 这个动作读哪个键当主键。 */
    fun keyIn(res: AiResource): String = idKey ?: res.idKey

    override fun toString(): String = id
}

/** 改一条已有记录（撤回＝把旧值写回）。 */
internal fun update(
    id: String,
    negate: Set<String> = emptySet(),
    drop: Set<String> = emptySet(),
    dropWrite: Map<String, String> = emptyMap(),
    note: String? = null,
): AiRevertAction = AiRevertAction(id, negate = negate, drop = drop, dropWrite = dropWrite, note = note)

/** 删一条（撤回＝按资源的 [AiResource.restore] 恢复）。 */
internal fun delete(id: String, idKey: String? = null): AiRevertAction =
    AiRevertAction(id, deletes = true, idKey = idKey)

/** 撤回走另一个动作（`inverse` 里写明是哪个、参数从哪来）。 */
internal fun paired(id: String, inverse: AiInverse, idKey: String? = null): AiRevertAction =
    AiRevertAction(id, inverse = inverse, idKey = idKey)

/** 切换型（撤回＝再做一次，如"再对调一次角色"）。 */
internal fun switcher(id: String, repeat: String): AiRevertAction = AiRevertAction(id, repeat = repeat)

/**
 * 写之前的现场。
 *
 * @param id 这一条的主键（删除/成对动作的撤回要用它；null = 认不出是哪一条）。
 * @param values 逐字段的现值，**键名与动作 payload 一致**——撤回就是把这里的值原样写回去。
 */
data class AiBefore(val id: Long?, val values: JsonObject)

/**
 * 逆操作：走哪个动作、参数从哪来。
 *
 * @param from 逆操作的 payload 键 → 从哪取：
 *   [AiRevert.ID] = 主键；以 [AiRevert.LITERAL]（`=`）开头 = 写死的字面量；
 *   否则是 [AiBefore.values] 里的键。
 *   显式列出来的理由：删除动作的 payload 用 `address_id`，恢复动作读 `target_id`——
 *   取错不会报错，只会让撤回卡点下去什么都没发生。
 * @param lines 撤回卡上固定要写的几行（这个逆操作在做什么）。
 */
class AiInverse(
    val actionId: String,
    val from: Map<String, String>,
    val lines: List<String> = emptyList(),
) {
    internal class Built(val payload: JsonObject, val warnings: List<String>)

    companion object {
        /**
         * 拼逆操作的 payload。
         *
         * **取不到的值分两种，处理不一样**：
         * - [from] 里点名的键在写之前的现场里没有（例如这一单本来就没填运费）→
         *   **这一项就不带**（逆操作自己会按"没填=不动"处理），并在卡上写一行警告；
         * - 主键取不到 → 整个撤回作废（返回 null）。认不出是哪一条就写不对地方。
         *
         * @param cn 键 → 中文名（[AiRevert.cnOf]）。**警告行必须说人话**：
         *   之前这里直接拼 `$k`，真机上就长成「⚠️ 「driver_id」读不到写之前的值」——
         *   和 patchPlan 里那条"不许出现裸键"是同一条教训（那边修过，这边漏了）。
         *   传的是**解析函数**而不是 `res.labels` 这一张表：payload 键里有一批不在 labels 里
         *   （它们不是"读回来的键"，见 [AiRevert.cnOf]），只传表的话这里又会印裸键。
         */
        internal fun build(inv: AiInverse, before: AiBefore, cn: (String) -> String = { it }): Built? {
            val warnings = mutableListOf<String>()
            val out = buildJsonObject {
                for ((k, src) in inv.from) {
                    if (src.startsWith(AiRevert.LITERAL)) {
                        put(k, JsonPrimitive(src.removePrefix(AiRevert.LITERAL)))
                        continue
                    }
                    val v = if (src == AiRevert.ID) before.id?.let { JsonPrimitive(it) } else before.values[src]
                    if (v == null || v is JsonNull) {
                        if (src == AiRevert.ID) return null
                        val name = cn(k)
                        warnings += if (v is JsonNull) {
                            "⚠️ 「$name」写之前本来就是空的 —— 这次撤回「不带这一项」" +
                                "（走的是同一个动作，按它「不填」的语义处理）"
                        } else {
                            "⚠️ 「$name」读不到写之前的值，这次撤回不会带上它"
                        }
                        continue
                    }
                    put(k, v)
                }
            }
            // 什么都没拼出来 = 这次撤回会打到空处。
            if (out.isEmpty()) return null
            return Built(out, warnings)
        }
    }
}

/**
 * 撤回卡上怎么把一个 JSON 值写成**给人看的字**，以及"取负"这一种逆运算。
 *
 * ### 为什么单独一个对象（而不是散在几处）
 * 这些规则只有一处实现：卡片上写的是 `12.00 → 撤回到 10.00`，如果两个地方各写一份
 * `textOf`，迟早出现一个地方把 `JsonPrimitive("true")` 印成 `"true"`（带引号）。
 * ⚠️ 名字不能叫 `AiJson`——读路径那边已经有一个同名对象（[AiReadService.kt] 里，
 * 负责宽松解析模型返回的 JSON），两个都叫 `AiJson` 是编译期的重复声明。
 */
internal object AiRevertJson {
    /**
     * 值 → 卡片上给人看的字（去掉 JSON 引号）。
     *
     * @param money true = 按两位小数显示。
     *
     * ### 为什么数字要"规整"一下（真机踩出来的）
     * 后端把 `Decimal` 列读出来是 `12.0000` 这种带四位小数的字符串，而 App 写进去的是
     * `12.00`。直接 print 到卡片上，用户看到的是「撤回到 5.0000」——难看，而且会让人
     * 以为系统记了个奇怪的值。所以数字一律规整（去尾零；金额补足两位）。
     */
    fun textOf(e: JsonElement?, money: Boolean = false): String {
        if (e == null || e is JsonNull) return "（空）"
        val p = e as? JsonPrimitive ?: return e.toString()
        val raw = p.contentOrNull ?: return "（空）"
        if (p.isString && raw.toBigDecimalOrNull() == null) return raw
        val n = raw.toBigDecimalOrNull() ?: return raw
        return if (money) {
            n.setScale(2, java.math.RoundingMode.HALF_UP).toPlainString()
        } else {
            n.stripTrailingZeros().let { if (it.scale() < 0) it.setScale(0) else it }.toPlainString()
        }
    }

    /**
     * 两个值是不是**同一个值**（比较用，不是显示用）。
     *
     * ### 为什么不能直接比字符串（真机踩出来的）
     * 撤回卡的"又被改过"提醒拿的是「我们写进去的 12.00」和「后端现在返回的 12.0000」。
     * 按字符串比，这两个永远不相等 → **每一次撤回卡都会报"被改过"** →
     * 用户很快就学会无视这条警告，而那正是这行提示存在的唯一理由。
     * 所以两边都能当数字读时按**数值**比（`BigDecimal.compareTo`）。
     */
    fun same(a: JsonElement?, b: JsonElement?): Boolean {
        val na = (a as? JsonPrimitive)?.contentOrNull?.toBigDecimalOrNull()
        val nb = (b as? JsonPrimitive)?.contentOrNull?.toBigDecimalOrNull()
        if (na != null && nb != null) return na.compareTo(nb) == 0
        return textOf(a) == textOf(b)
    }

    fun longOf(e: JsonElement?): Long? = (e as? JsonPrimitive)?.contentOrNull?.toLongOrNull()

    /** 数值取负（库存增减量）；不是数字就原样还回去。 */
    fun negate(e: JsonElement): JsonElement {
        val p = e as? JsonPrimitive ?: return e
        val n = p.contentOrNull?.toIntOrNull() ?: return e
        return JsonPrimitive(-n)
    }
}

