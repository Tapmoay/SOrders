package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * 图片类写动作的处理器（FEAT-0024）：三个动作共用这一个类，差别全在 [AiWriteImage.Kind]。
 *
 * ### 为什么手写（而不用声明式 CRUD 规格）
 * 声明式的 [CrudWriteHandler] 只做一件事：**把一个字段换成另一个值**。
 * 这件事比它多两步，而且两步都在"值"之外：
 * 1. **要一个文件**：真正的值（URL）是**先把图片字节传上去**才存在的，
 *    而字节来自用户这一轮贴在聊天里的图（[AiImageInbox]）——模型给不出，也不该给；
 * 2. **要先读现状才知道写什么**：追加模式下最终那个列表 = 现在的列表 + 新的 URL
 *    （撤回方向同理：payload 里带的是旧列表）。
 *
 * ⛔ 所以本类的动作在 [AiWrites] 里 **crud = null**：带 crud 规格的动作会被
 *    AiWriteService 那段声明式注册**无条件覆盖**成 CrudWriteHandler（见那段注释）。
 *
 * ### 两条不许破的规矩（[AiWriteHandler] 的接口注释）
 * 1. [prepare] 里**绝对不许写后端**：它只造卡。上传发生在 [commit]，即用户点确认之后。
 * 2. [commit] 只认 [prepare] 造出来的 payload —— 图片字节就在里面（[AiWriteImage.KEY_IMAGE_DATA]），
 *    所以"用户看到的那张图"与"真正传上去的那张"一定是同一张。
 */
internal class ImageWriteHandler(
    override val actionId: String,
    private val kind: AiWriteImage.Kind,
    private val ds: AiWriteDataSource,
    private val store: AiWritePreviewStore,
) : AiWriteHandler {

    override suspend fun prepare(params: JsonObject): AiWriteOutcome {
        // ① 名字 → 编号。唯一一处解析：对不上就**列候选**，⛔ 不许猜（AiWriteArgs.strict 的口径）。
        val raw = AiWriteArgs.required(params, kind.param, kind.cn)
        val hit = AiWriteArgs.strict(raw, pool(), kind.cn)
            ?: throw AiWriteArgException("请把${kind.cn}的名字说全（名字是空的，名册里对不上任何一条）。")

        // ② 防呆：**没有图就当场拒绝**（⛔ 不发一张没有图的空卡）；
        //    贴了多张而没说清第几张 → 把这几张列出来（candidates 结构化带出去）。
        val picked = AiWriteImage.pickOrReject(params)

        // ③ 加到后面还是整套换掉。商品只有一张图，问都不问。
        //    ⛔ 问不清就拒绝：这两件事的后果不一样（前者旧的还在，后者把旧的从这条记录上摘掉）。
        val append = if (!kind.multi) {
            false
        } else {
            AiWriteImage.parseMode(AiWriteArgs.str(params, AiWriteImage.KEY_MODE))
                ?: throw AiWriteArgException(
                    "缺少 mode：这一次是把图**加到原来的后面**（${AiWriteImage.MODE_APPEND}），" +
                        "还是把原来的**整套换掉**（${AiWriteImage.MODE_REPLACE}）？" +
                        "这两件事的后果不一样，问清了再发卡。",
                )
        }

        // ④ 读这条记录**现在**的图片：撤回卡那一行的锚就是它（读不到 = 撤不回来，如实说、不假装）。
        val before = ds.snapshot(kind.resource, hit.id)
            ?: throw AiWriteArgException(
                "读不到这条${kind.cn}现在的图片（可能刚刚被删了）。请刷新页面后再试一次。",
            )
        val cur = AiWriteImage.urlsOf(before.values[kind.imageKey])

        // ⑤ 卡片与 payload **同一次产出**：卡片上写的名字，就是后端真正收到的那条。
        val card = AiWriteImage.cardFor(kind, hit.id, hit.label, picked, cur, append)
        return AiWriteOutcome.NeedConfirm(
            store.card(
                actionId,
                summary = card.summary,
                detailLines = card.details,
                payload = card.payload,
            ),
        )
    }

    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {
        val id = payload.reqLong(kind.idKey)
        val dataUrl = payload.str(AiWriteImage.KEY_IMAGE_DATA)

        // 商品：上传端点**自己就把 image_url 写了**（POST /products/{id}/image 的语义），
        // 所以正向只上传一次；撤回方向没有字节，走下面的普通字段写回。
        if (kind == AiWriteImage.Kind.PRODUCT && dataUrl != null) {
            ds.uploadProductImage(id, dataUrl)
            return
        }

        // 正向：先把图传上去拿到 URL（纯落盘，不碰任何行），再算这条记录最终该挂哪几张。
        // 撤回：payload 里就是这个键的旧值（JsonNull = 原来没有图 ⇒ 空表 ⇒ 清空），一次上传都不发。
        val urls: List<String> = if (dataUrl != null) {
            val url = ds.uploadLocationImage(dataUrl)
            val append = AiWriteImage.parseMode(payload.str(AiWriteImage.KEY_MODE)) ?: false
            // 追加要按**提交那一刻**的现状算（发卡到点确认之间，别人可能也加了一张）
            val now = AiWriteImage.urlsOf(ds.snapshot(kind.resource, id)?.values?.get(kind.imageKey))
            AiWriteImage.imagesAfter(now, url, append)
        } else {
            AiWriteImage.urlsOf(payload[kind.imageKey])
        }
        writeImages(id, urls)
    }

    /**
     * 把"这条记录最终该挂哪几张图"写回去。
     *
     * ⚠️ 空表写成 **JsonNull** 而不是空串：后端那三个接口的语义是
     * **不传 = 不改 / 空表 [] = 清空 / 非空 = 整体替换**（shipper.py 的 _apply_images），
     * 而"撤回成原来没有图"要的正是**清空**。写成空串会被数据源那层当成"没给"，
     * 结果是撤回了但图片还在 —— 卡片上却写着"已改回原样"。
     */
    private suspend fun writeImages(id: Long, urls: List<String>) {
        val field = buildJsonObject {
            put(
                kind.imageKey,
                if (urls.isEmpty()) JsonNull else JsonPrimitive(AiWriteImage.joinUrls(urls)),
            )
        }
        when (kind) {
            AiWriteImage.Kind.PRODUCT -> ds.updateProduct(id, field)
            AiWriteImage.Kind.LOCATION -> ds.updateLocation(id, field)
            AiWriteImage.Kind.ADDRESS -> ds.updateAddress(id, field)
        }
    }

    /** 名字名册：三类各一张（货主只看得到自己名下的那些，与手工页同一份数据）。 */
    private suspend fun pool(): List<AiName> = when (kind) {
        AiWriteImage.Kind.PRODUCT -> ds.products()
        AiWriteImage.Kind.LOCATION -> ds.locations()
        AiWriteImage.Kind.ADDRESS -> ds.addresses()
    }
}
