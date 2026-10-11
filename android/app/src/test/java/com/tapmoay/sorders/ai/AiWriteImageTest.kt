package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * 图片上传类写动作的**纯逻辑**单测（FEAT-0024，2026-10-11）。
 *
 * ### 为什么只测纯函数
 * [ImageWriteHandler] 依赖 [AiWriteDataSource]（一百多个抽象方法），而现成的替身
 * `FakeDs` 是 `AiWriteTest` 的类内 private —— 这里为它造第二份全量替身不划算。
 * 所以卡片的每一句话、payload 的每一个键、多图语义、防呆的三种拒绝**都抽在
 * [AiWriteImage] / [AiImageInbox] 的纯函数里**，处理器只留一层薄 IO（解析名字 → 读快照 → 造卡）。
 *
 * 这一组的重点（每一条都对应一条不许破的规矩）：
 * 1. 三类各自的卡片文案与 payload 键（商品 image_url / 地点地址 image_urls）；
 * 2. **没图必须拒绝**（⛔ 不发空卡）；多张没点名 → 列候选；点名越界 → 如实说有几张；
 * 3. **多图语义**：不传 = 不改 / JsonNull = 清空 / 非空 = 整体替换（照后端 _apply_images）；
 * 4. 图片的类型与 4MB 大小校验（与后端同一个数）。
 */
class AiWriteImageTest {

    /** 一张"够小"的 jpeg：长度只影响"约多少 KB"和大小校验，内容无所谓。 */
    private fun jpeg(chars: Int = 4000): String = "data:image/jpeg;base64," + "A".repeat(chars)

    private fun picked(index: Int, chars: Int = 4000) = AiImageInbox.Picked(index, jpeg(chars))

    @After
    fun tearDown() {
        // 收件箱是进程内的单例：每个用例自己收尾，免得串到下一个用例。
        AiImageInbox.clear()
    }

    private fun refusal(block: () -> Unit): AiWriteArgException {
        try {
            block()
        } catch (e: AiWriteArgException) {
            return e
        }
        fail("这一步本该被拒绝（抛 AiWriteArgException），却通过了")
        error("unreachable")
    }

    // ============================================================ ① 三类卡片与 payload

    @Test
    fun productImageCard_pinsBytesAndOnlyOneImage() {
        val card = AiWriteImage.cardFor(
            kind = AiWriteImage.Kind.PRODUCT,
            id = 41,
            name = "红富士苹果",
            picked = picked(1),
            cur = listOf("/static/uploads/products/41/old.jpg"),
            append = false,
        )

        assertTrue("摘要要说清是给哪个商品换图：" + card.summary, card.summary.contains("红富士苹果"))
        assertTrue("摘要要说清这一张会顶掉原来那张：" + card.summary, card.summary.contains("换成这一张"))
        assertTrue("明细要写用聊天里第几张：" + card.details, card.details.any { it.contains("第 1 张") })
        assertEquals(41L, card.payload["product_id"]!!.jsonPrimitive.content.toLong())
        assertEquals(AiWriteImage.MARKER, card.payload["image_url"]!!.jsonPrimitive.content)
        assertEquals(picked(1).dataUrl, card.payload["image_data"]!!.jsonPrimitive.content)
        assertNull("商品只有一张图，没有「加还是换」这个参数", card.payload["mode"])
    }

    @Test
    fun locationImageCard_appendSaysHowManyAfter() {
        val card = AiWriteImage.cardFor(
            kind = AiWriteImage.Kind.LOCATION,
            id = 7,
            name = "老王家仓库",
            picked = picked(2),
            cur = listOf("/a.jpg", "/b.jpg"),
            append = true,
        )

        assertTrue("摘要要写清加完几张：" + card.summary, card.summary.contains("2 张"))
        assertTrue("明细要说清「加到原来的后面」：" + card.details, card.details.any { it.contains("加") })
        assertEquals(7L, card.payload["location_id"]!!.jsonPrimitive.content.toLong())
        assertEquals(AiWriteImage.MARKER, card.payload["image_urls"]!!.jsonPrimitive.content)
        assertEquals(AiWriteImage.MODE_APPEND, card.payload["mode"]!!.jsonPrimitive.content)
    }

    @Test
    fun locationImageCard_replaceSaysWholeSwap() {
        val card = AiWriteImage.cardFor(
            kind = AiWriteImage.Kind.LOCATION,
            id = 7,
            name = "老王家仓库",
            picked = picked(1),
            cur = listOf("/a.jpg", "/b.jpg", "/c.jpg"),
            append = false,
        )
        assertEquals(AiWriteImage.MODE_REPLACE, card.payload["mode"]!!.jsonPrimitive.content)
        assertTrue("整套换掉必须写在卡上：" + card.details, card.details.any { it.contains("整套换掉") })
    }

    @Test
    fun addressImageCard_usesAddressKeys() {
        val card = AiWriteImage.cardFor(
            kind = AiWriteImage.Kind.ADDRESS,
            id = 12,
            name = "张三 东环路 8 号",
            picked = picked(1),
            cur = emptyList(),
            append = true,
        )
        assertTrue("摘要要提地址：" + card.summary, card.summary.contains("地址"))
        assertEquals(12L, card.payload["address_id"]!!.jsonPrimitive.content.toLong())
        assertEquals(AiWriteImage.MARKER, card.payload["image_urls"]!!.jsonPrimitive.content)
        assertTrue("原来没有图要如实写：" + card.details, card.details.any { it.contains("还没有图") })
    }

    // ============================================================ ② 防呆

    @Test
    fun pickOrReject_withoutImage_refusesInsteadOfBlankCard() {
        AiImageInbox.clear()
        val e = refusal { AiWriteImage.pickOrReject(buildJsonObject { put("product", "红富士苹果") }) }
        assertTrue("要说清怎么办（先去贴图）：" + e.message, e.message!!.contains("贴一张图"))
        assertTrue("候选为空（这不是「选一个」，是「还没图」）", e.candidates.isEmpty())
    }

    @Test
    fun pickOrReject_multipleImagesWithoutIndex_listsCandidates() {
        AiImageInbox.set(listOf(jpeg(), jpeg(2000)))
        val e = refusal { AiWriteImage.pickOrReject(buildJsonObject { }) }
        assertEquals("两张都列出来让用户挑", 2, e.candidates.size)
        assertTrue("要说清有几张：" + e.message, e.message!!.contains("2 张"))
    }

    @Test
    fun pickOrReject_outOfRange_saysHowManyExist() {
        AiImageInbox.set(listOf(jpeg()))
        val e = refusal {
            AiWriteImage.pickOrReject(buildJsonObject { put(AiWriteImage.KEY_IMAGE_INDEX, 5) })
        }
        assertTrue("要如实说只有几张：" + e.message, e.message!!.contains("只有 1 张"))
    }

    @Test
    fun pickOrReject_singleImageWithoutIndex_usesIt() {
        AiImageInbox.set(listOf(jpeg()))
        assertEquals(1, AiWriteImage.pickOrReject(buildJsonObject { }).index)
    }

    // ============================================================ ③ 多图语义（三档）

    @Test
    fun imagesAfter_appendKeepsOld_replaceDropsThem() {
        val cur = listOf("/a.jpg", "/b.jpg")
        assertEquals(listOf("/a.jpg", "/b.jpg", "/new.jpg"), AiWriteImage.imagesAfter(cur, "/new.jpg", append = true))
        assertEquals(listOf("/new.jpg"), AiWriteImage.imagesAfter(cur, "/new.jpg", append = false))
    }

    @Test
    fun urlsOf_nullMeansClearNotEmptyList_butMissingKeyMeansNoChange() {
        // 快照/payload 里的 JsonNull = 「原来没有图」⇒ 撤回就是**清空**（空表），不是"不改"。
        assertEquals(emptyList<String>(), AiWriteImage.urlsOf(JsonNull))
        // 「、」串 = 整体替换
        assertEquals(listOf("/a.jpg", "/b.jpg"), AiWriteImage.urlsOf(JsonPrimitive("/a.jpg、/b.jpg")))
        // 正向 payload 里那个锚点不是图，解码成空表（它只用于卡片显示）
        assertEquals(emptyList<String>(), AiWriteImage.urlsOf(JsonPrimitive(AiWriteImage.MARKER)))
        // 往返：joinUrls → urlsOf
        assertEquals(listOf("/a.jpg", "/b.jpg"), AiWriteImage.urlsOf(JsonPrimitive(AiWriteImage.joinUrls(listOf("/a.jpg", "/b.jpg")))))
    }

    @Test
    fun parseMode_acceptsBothSpellingsAndRefusesToGuess() {
        assertEquals(true, AiWriteImage.parseMode(AiWriteImage.MODE_APPEND))
        assertEquals(true, AiWriteImage.parseMode("追加"))
        assertEquals(false, AiWriteImage.parseMode(AiWriteImage.MODE_REPLACE))
        assertEquals(false, AiWriteImage.parseMode("替换"))
        assertNull("认不出就必须是 null（调用方据此拒绝，不许猜）", AiWriteImage.parseMode("随便吧"))
        assertNull(AiWriteImage.parseMode(null))
    }

    // ============================================================ ④ 类型与大小校验

    @Test
    fun parseImageDataUrl_rejectsNonImageAndOversize() {
        val ok = AiWriteImage.parseImageDataUrl(jpeg())
        assertEquals("image/jpeg", ok.mime)
        assertTrue(ok.base64.isNotEmpty())

        val bad = refusal { AiWriteImage.parseImageDataUrl("data:text/plain;base64,AAAA") }
        assertTrue("要说清只收哪几种格式：" + bad.message, bad.message!!.contains("格式"))

        val huge = refusal {
            AiWriteImage.parseImageDataUrl("data:image/jpeg;base64," + "A".repeat(6_000_000))
        }
        assertTrue("太大要说清上限：" + huge.message, huge.message!!.contains("太大"))
    }

    @Test
    fun inbox_setReplacesInsteadOfAppending() {
        AiImageInbox.set(listOf(jpeg(), jpeg(2000)))
        assertEquals(2, AiImageInbox.all().size)
        assertNull("两张都没点名 = 没得挑", AiImageInbox.pick(null))
        assertEquals(2, AiImageInbox.pick(2)!!.index)
        // 下一轮没带图 ⇒ 整份清掉（不能留着上一轮那几张）
        AiImageInbox.set(emptyList())
        assertTrue(AiImageInbox.all().isEmpty())
        assertNull(AiImageInbox.pick(1))
    }
}
