package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put

/**
 * 图片类写动作（FEAT-0024）：把用户**贴在聊天里的那张图**设成商品图 / 地点图 / 地址图。
 *
 * ### 用户口径（2026-10-11，逐字）
 * 「我们的那个 AI 要**支持上传商品图片**的 —— 我给它一个图片，他能帮我上传商品图片，
 * 包括什么**地点图片**啊、什么……图片，他都能帮我上传。」
 *
 * ### 链路（每一类都是「先上传拿 URL、再写进那个字段」）
 * | 这一类 | 上传 | 写进哪 |
 * | --- | --- | --- |
 * | 商品 | POST /products/{id}/image（一个文件，直接写 image_url） | products.image_url |
 * | 地点 | POST /shipper/locations/image（纯落盘，返回 URL） | shipper_locations.image_urls |
 * | 地址（线路） | 同上（手工页也是这条） | shipper_addresses.image_urls |
 *
 * 后两类走的是**与手工页一模一样的两步**（ui/shipper/AddressViewModel.kt:577-579 就是
 * 先 uploadLocationImage 拿 URL、再随对象 PATCH 进 image_urls）——不另造一条上传端点。
 *
 * ### 卡片、payload、参数三样同源
 * [cardFor] 一次产出「摘要 + 明细 + payload」：卡片上写的名字与编号，就是后端真正收到的那条。
 * 图片字节**在预览那一刻**就钉进 payload（[KEY_IMAGE_DATA]），用户点确认时用的是那一张，
 * 不会因为中间他又贴了别的图而串。
 *
 * ### 撤回（用户 2026-09-20 的硬规矩：所有删除一律软删 + 必须有恢复路径）
 * payload 里的 [Kind.imageKey] 是**撤回的锚**：撤回卡按「这个键写回旧值」算出旧图片列表，
 * 而图片的撤回**不需要重新上传**（旧 URL 一直在服务器上、没被删）——所以撤回方向只是
 * 一次普通的字段写回，走的是同一个动作、同一条留痕路径。
 */
internal object AiWriteImage {

    /** 追加：加到原来的图片后面（第 N+1 张）。 */
    const val MODE_APPEND = "APPEND"

    /** 替换：把原来的图片整批换成这一张。 */
    const val MODE_REPLACE = "REPLACE"

    /** payload 里装图片字节的键（**不进读回集**，见 [AiResource.payloadLabels]）。 */
    const val KEY_IMAGE_DATA = "image_data"

    /** payload 里装「加还是换」的键（同上）。 */
    const val KEY_MODE = "mode"

    /** 参数：用第几张图（一次贴了多张时才填）。 */
    const val KEY_IMAGE_INDEX = "image_index"

    /**
     * payload 里那个锚点值 —— 正向卡片上写「（这次新上传的图片）」，撤回卡片上它会换成旧 URL。
     *
     * ⚠️ 用**一句人话**而不是 data URL：撤回卡上那一行是
     * 「商品图片：（这次新上传的图片） → 撤回到 /static/uploads/...」，
     * 把几 MB 的 base64 印在卡片上等于把用户唯一要核对的那一行淹掉。
     */
    const val MARKER = "（这次新上传的图片）"

    /** 多张图片在 payload / 快照里怎么串成一个可读串（URL 里不会出现这个字符）。 */
    const val SEP = "、"

    /**
     * 目标类型：三个动作共用一套代码与文案，差别全在这张表里。
     *
     * @param resource [AiWriteDataSource.snapshot] 的分支键（同时也是资源表的 key）。
     * @param idKey 主键在 payload 里的键名（**必须与资源表的 idKey 一致**）。
     * @param param 模型给的名字参数（商品名 / 地点名 / 地址名）。
     * @param cn 卡片上的对象中文名。
     * @param multi true = 这个对象能挂多张图（地点 / 地址）；false = 只有一张（商品）。
     * @param imageKey 图片字段在 payload 与读回集里的键名。
     */
    enum class Kind(
        val resource: String,
        val idKey: String,
        val param: String,
        val cn: String,
        val multi: Boolean,
        val imageKey: String,
    ) {
        PRODUCT("product", "product_id", "product", "商品", false, "image_url"),
        LOCATION("location", "location_id", "location", "地点", true, "image_urls"),
        ADDRESS("address", "address_id", "address", "地址", true, "image_urls"),
        ;

        /** 读回集里的中文名（撤回卡上那一行：「商品图片：… → 撤回到 …」）。 */
        val imageCn: String get() = if (multi) "图片" else "商品图片"
    }

    val ACTIONS: List<AiWriteAction> = listOf(
        AiWriteAction(
            id = AiWrites.PRODUCTS_IMAGE,
            title = "给商品换一张图",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_PRODUCT,
            blurb = "把用户**刚刚贴在聊天里的那张图**设成这个商品的展示图（一个商品只有一张，" +
                "新的直接把旧的顶掉；旧的那张不会从服务器上删掉，撤回就是把这一项改回旧的 URL）。" +
                "图片字节在发卡那一刻就钉住了 —— 用户之后再贴别的图，不会换掉这张卡要传的那张。",
            params = listOf(
                AiWriteParam(
                    name = "product",
                    cn = "商品",
                    required = true,
                    hint = "商品名册里的名字（要能唯一认出来，别只说「那个苹果」）",
                ),
                AiWriteParam(
                    name = KEY_IMAGE_INDEX,
                    cn = "用第几张图",
                    kind = AiWriteParamKind.NUMBER,
                    hint = "用户一次贴了多张时才填（从 1 数）；只贴了一张就别填",
                ),
            ),
        ),
        AiWriteAction(
            id = AiWrites.LOCATION_IMAGE,
            title = "给地点加/换图片",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "把用户**刚刚贴在聊天里的那张图**加到地点库这条记录的图片里。" +
                "mode 决定是**加**到原来的后面（APPEND）还是把原来的整批**换**掉（REPLACE）。" +
                "图片字节在发卡那一刻就钉住了；旧图不会被删，撤回就是把图片这一项改回原来的列表。",
            params = listOf(
                AiWriteParam(
                    name = "location",
                    cn = "地点",
                    required = true,
                    hint = "地点库（送货地点）里的名字",
                ),
                modeParam(),
                AiWriteParam(
                    name = KEY_IMAGE_INDEX,
                    cn = "用第几张图",
                    kind = AiWriteParamKind.NUMBER,
                    hint = "用户一次贴了多张时才填（从 1 数）；只贴了一张就别填",
                ),
            ),
        ),
        AiWriteAction(
            id = AiWrites.ADDRESS_IMAGE,
            title = "给地址加/换图片",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_ADDRESS,
            blurb = "把用户**刚刚贴在聊天里的那张图**加到线路库这条地址的图片里（收货地址参考图，" +
                "与订单详情里那几张是同一批：画的就是「这个门口长什么样」）。" +
                "mode 决定是**加**到原来的后面（APPEND）还是把原来的整批**换**掉（REPLACE）。" +
                "图片字节在发卡那一刻就钉住了；旧图不会被删，撤回就是把图片这一项改回原来的列表。",
            params = listOf(
                AiWriteParam(
                    name = "address",
                    cn = "地址",
                    required = true,
                    hint = "线路/地址库里的那条：收货人 + 终点地址（说得越全越不容易对上多条）",
                ),
                modeParam(),
                AiWriteParam(
                    name = KEY_IMAGE_INDEX,
                    cn = "用第几张图",
                    kind = AiWriteParamKind.NUMBER,
                    hint = "用户一次贴了多张时才填（从 1 数）；只贴了一张就别填",
                ),
            ),
        ),
    )

    private fun modeParam(): AiWriteParam = AiWriteParam(
        name = KEY_MODE,
        cn = "加到后面还是整套换掉",
        required = true,
        kind = AiWriteParamKind.ENUM,
        enumValues = listOf(MODE_APPEND, MODE_REPLACE),
        hint = "APPEND = 加到原来的图片后面（原来的还在，只是多一张）；" +
            "REPLACE = 把原来的图片整批换成这一张（**问不清就别猜**：这两件事的后果不一样）",
    )

    // ============================================================ 纯逻辑（单测只测这一段）

    /**
     * 单张图片的上限，**与后端同一个数**（backend/app/core/upload_read.py:29 MAX_IMAGE_BYTES = 4MB）。
     *
     * 为什么 App 侧还要再判一次：后端那道门在**传完之后**才拒（或者更糟：先落盘再拒），
     * 而用户贴的常常是手机相册原图（8–12 MB）—— 让他等十几秒上传、再收到一句"图片过大"，
     * 比当场告诉他"先压一下"差得多。⛔ 两个数必须同源，改一个就得改另一个。
     */
    const val MAX_IMAGE_BYTES = 4 * 1024 * 1024

    /**
     * 认这几种图片类型（与后端 products.py 的 ALLOWED_IMAGE_CT 同一套，:33-40）。
     *
     * ⛔ 别在这里"顺手放宽"：后端不认的类型传上去只会拿到 400，
     *    而卡片上写着"已经传好了"。
     */
    val ALLOWED_MIME: Set<String> = setOf(
        "image/jpeg", "image/jpg", "image/pjpeg",
        "image/png", "image/x-png",
        "image/webp",
        "image/bmp", "image/x-ms-bmp",
    )

    /** 一张校验过的图片：MIME + base64 正文（不含 data: 前缀）。 */
    data class ImagePayload(val mime: String, val base64: String)

    /**
     * 校验一张 data URL，**不合格就当场拒绝**（不发卡、不上传）。三类不合格各有各的说法：
     * 不是图片 / 是图片但后端不认这个格式 / 太大。
     *
     * 判据钉在 _tools/qa/_check_ai_image_upload.py：把类型白名单或大小上限删掉，判据必须变红
     * —— 少了它们，用户会在传了几十兆之后才收到一句后端 400（而卡片上写着"已完成"）。
     */
    fun parseImageDataUrl(dataUrl: String): ImagePayload {
        val head = dataUrl.substringBefore(',', "")
        val body = dataUrl.substringAfter(',', "")
        if (!head.startsWith("data:") || body.isEmpty()) {
            throw AiWriteArgException("这张图没读到图片数据（不是一张能上传的图片），请在聊天里重新贴一次。")
        }
        val mime = head.removePrefix("data:").substringBefore(';').trim().lowercase()
        if (mime !in ALLOWED_MIME) {
            throw AiWriteArgException(
                "这张图的格式后端不收（只收 JPG / PNG / WebP / BMP，这张是「${mime.ifEmpty { "认不出" }}」）。" +
                    "请换一张再试。",
            )
        }
        // base64 长度 → 字节数（每 4 个字符 3 字节，减去末尾的 = 补齐）
        val approx = body.length * 3L / 4 - body.takeLast(2).count { it == '=' }
        if (approx > MAX_IMAGE_BYTES) {
            throw AiWriteArgException(
                "这张图太大了（约 ${approx / 1024 / 1024} MB），最大 $MAX_IMAGE_BYTES 字节（4 MB）。" +
                    "请先在相册里压一下、或者截个图再发。",
            )
        }
        if (approx <= 0L) {
            throw AiWriteArgException("这张图是空的（没读到图片数据），请重新贴一张。")
        }
        return ImagePayload(mime, body)
    }

    /**
     * 这次写完，这条记录上的图片列表应该是哪几张。
     *
     * ### 多图语义（照仓库既有口径，⛔ 一个字符都不许反）
     * 后端 _apply_images（backend/app/api/v1/shipper.py:49-55）与
     * AddressCreateRequest.imageUrls / LocationCreateRequest.imageUrls 走的是
     * **同一套三档语义**：
     * - **不传**（字段缺省 / null）= **不改**（AI 改电话、改备注时图片必须原样留着）；
     * - **空表 [] = 清空**（撤回「原来没有图」那条路要的正是它）；
     * - **非空 = 整体替换**。
     *
     * ⛔ 所以「追加」在**协议层**也是「非空 = 整体替换」——只是我们算出来的那个列表
     * 恰好 = 旧列表 + 新的一张。把它写成「传空表表示追加」之类的花样，
     * 后果是**地点上原有的图片全没了**（2026-09-19 审计抓过一次同形状的事故）。
     *
     * @param append true = 追加（[MODE_APPEND]），false = 整套替换（[MODE_REPLACE]）。
     */
    fun imagesAfter(cur: List<String>, newUrl: String, append: Boolean): List<String> =
        if (append) cur + newUrl else listOf(newUrl)

    /** 模型给的 mode 认不认得出。true = 追加，false = 替换，null = 没给 / 认不出（调用方必须**拒绝**，不许猜）。 */
    fun parseMode(raw: String?): Boolean? = when (raw?.trim()?.uppercase()) {
        MODE_APPEND, "追加", "加", "加上去", "加到后面" -> true
        MODE_REPLACE, "替换", "换", "换掉", "整套换掉", "覆盖" -> false
        else -> null
    }

    /** 参数里的「第几张图」（1 开始）。不是正整数 = 没点名。 */
    fun indexOf(params: JsonObject): Int? =
        (params[KEY_IMAGE_INDEX] as? JsonPrimitive)?.contentOrNull?.trim()?.toIntOrNull()?.takeIf { it >= 1 }

    /**
     * **防呆第一道**：取出这次要传的那张图，取不到就**拒绝并发不出一张空卡**。
     *
     * 三种拒绝各有各的说法（模型照着这句去问用户，而不是自己编一张图）：
     * 1. 一张图都没有 → 告诉他**先去聊天框贴图**；
     * 2. 贴了好几张而它没点名 → 把这几张**列出来**让它问用户要哪一张（候选走 [AiWriteArgException.candidates]）；
     * 3. 点了一个不存在的序号 → 如实说现在只有几张。
     */
    fun pickOrReject(params: JsonObject): AiImageInbox.Picked {
        val all = AiImageInbox.all()
        if (all.isEmpty()) {
            throw AiWriteArgException(
                "这次聊天里没有图片，所以做不了这件事：**请先在聊天框里贴一张图**" +
                    "（输入框左边那颗「+」→ 相册 / 拍照 / 最近照片），再让我设置。" +
                    "不要凭商品名去猜一张图，也不要发一张没有图的卡。",
            )
        }
        val labels = all.map { it.label() }
        val idx = indexOf(params)
        AiImageInbox.pick(idx)?.let { return checked(it) }
        if (idx == null) {
            throw AiWriteArgException(
                "聊天里有 ${all.size} 张图，要设的是哪一张？现有：${labels.joinToString(SEP)}。" +
                    "请让用户说一声（例如「第 2 张」），**不要自己挑一张**。",
                labels,
            )
        }
        throw AiWriteArgException(
            "聊天里只有 ${all.size} 张图，没有第 $idx 张。现有：${labels.joinToString(SEP)}。",
            labels,
        )
    }

    /** 取到了图还要**先验一遍**：不是图片、或超过 4MB → 当场拒绝（不发卡、不上传）。 */
    private fun checked(picked: AiImageInbox.Picked): AiImageInbox.Picked {
        parseImageDataUrl(picked.dataUrl)
        return picked
    }

    /**
     * payload / 快照里的图片值 → URL 列表。
     *
     * 三种形状都要认（写回方向会遇到后两种）：
     * - **缺省 / JsonNull** → 空表 =「原来没有图」（撤回时走 nullableWritable，
     *   后端收到 [] 就是「清空」，这正是我们要的——⛔ 不是「不改」）；
     * - **一句人话/锚点**（[MARKER]）→ 空表（正向 payload 里那个锚点只用于卡片显示）；
     * - **「、」串起来的 URL** → 列表。
     */
    fun urlsOf(e: JsonElement?): List<String> {
        val raw = (e as? JsonPrimitive)?.contentOrNull?.trim().orEmpty()
        if (raw.isEmpty() || raw == MARKER) return emptyList()
        return raw.split(SEP).map { it.trim() }.filter { it.isNotEmpty() }
    }

    /** 列表 → 卡片上（以及 payload 里）那个可读串。 */
    fun joinUrls(urls: List<String>): String = urls.joinToString(SEP)

    /**
     * 卡片正文里的「原来是哪几张」。
     *
     * 卡片的读者是用户：URL 一长串只会把行撑爆，所以只给**张数**，逐张的 URL 交回给
     * 撤回卡（那里才是「改前 → 改后」该出现的地方）。
     */
    fun currentText(cur: List<String>): String =
        if (cur.isEmpty()) "还没有图" else "已有 ${cur.size} 张"

    /**
     * 一次产出「摘要 + 明细 + payload」——三样**同源**，卡片上写的名字就是真正写进去的那条。
     *
     * @param id 已解析出来的编号（模型给的是名字，换编号只有一处：[AiWriteArgs.strict]）。
     * @param cur 这条记录**现在**的图片（撤回卡的锚就是这个键的旧值）。
     * @param append 追加还是整套替换（[Kind.multi] 为 false 时忽略，商品只有一张）。
     */
    fun cardFor(
        kind: Kind,
        id: Long,
        name: String,
        picked: AiImageInbox.Picked,
        cur: List<String>,
        append: Boolean,
    ): Card {
        val what = "${kind.cn}「$name」的${kind.imageCn}"
        val summary = when {
            !kind.multi -> "把${what}换成这一张"
            append -> "给${what}再加一张（原来 ${currentText(cur)}）"
            else -> "把${what}换成这一张（原来 ${currentText(cur)}）"
        }

        val details = mutableListOf<String>()
        details += "用哪张图：聊天里${picked.label()}"
        details += if (!kind.multi) {
            "怎么改：这一张**顶掉**原来那张（一个${kind.cn}只有一张图）"
        } else if (append) {
            "怎么改：**加**到原来的后面 —— ${currentText(cur)} → ${cur.size + 1} 张"
        } else {
            "怎么改：**整套换掉** —— ${currentText(cur)} → 1 张（原来那几张不再挂在这条记录上）"
        }
        details += "原来那几张：${currentText(cur)}（服务器上的文件不会被删：撤回就是把这一项改回旧 URL）"
        details += "点确认之后：先把这张图上传到服务器，再把${kind.cn}的${kind.imageCn}改成它"

        val payload = buildJsonObject {
            put(kind.idKey, id)
            // 撤回的锚：撤回卡按「这个键写回旧值」算，而它的旧值就是上面那份 cur
            put(kind.imageKey, MARKER)
            if (kind.multi) put(KEY_MODE, if (append) MODE_APPEND else MODE_REPLACE)
            // 图片字节**在预览这一刻**就钉住（用户点确认时用的就是这一张）
            put(KEY_IMAGE_DATA, picked.dataUrl)
        }
        return Card(summary, details, payload)
    }

    /** [cardFor] 的产物：卡片正文 + 真正发出去的请求体。 */
    data class Card(val summary: String, val details: List<String>, val payload: JsonObject)
}
