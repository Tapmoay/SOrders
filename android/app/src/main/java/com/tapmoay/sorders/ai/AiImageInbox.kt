package com.tapmoay.sorders.ai

/**
 * **这一轮提问里用户贴在聊天里的图片**（会话级收件箱）。
 *
 * ### 为什么需要它（FEAT-0024，2026-10-11）
 * 用户给 AI 一张图，让它「把这张图设成商品图 / 地点图 / 线路图」——图片本身早就能进
 * 多模态消息（[AiAttachment.imageDataUrl]），但**写路径看不到它**：
 * [AiTools] 手里只有模型给的名字与参数，[AiWriteDataSource] 手里只有后端接口，
 * 而「用户刚贴的那张图」这件事只有聊天页知道（AiChatViewModel.attachments）。
 *
 * 写动作的确认卡必须在**预览那一刻**就把图片字节钉进 payload（见 [AiWriteImage]），
 * 否则用户点确认时图可能已经被换掉/清掉，而卡片上写的还是那一张 ——「用户看到的」
 * 与「真正写进去的」分叉，正是本仓库反复栽的那类坑。
 *
 * ### 为什么是「收件箱」而不是给写动作加参数
 * 模型只能通过 preview_write **申请**，它给不出字节（也不该给）。图片的来源只有一个：
 * 用户这一轮发出去的那几张。所以由 [AiAgentLoop.run] 在**跑这一轮之前**把它记下来
 * （入口唯一：run(images = ...)），写动作再来取 —— 与 [AiLocation] 的「当前位置」句柄
 * 同一种形状：**模型只报意图，真实数据由 App 侧取一次换上**。
 *
 * ### 三条口径
 * 1. **一次性覆盖，不是累加**：每次 run 都整份替换。上一轮贴的图不会留到这一轮
 *    （否则用户会说「我没贴图啊，它怎么拿上次那张改了」）。
 * 2. **只记图片**：表格附件（Excel）不在这里 —— 它走的是另一条路（随消息给模型看正文）。
 * 3. **不落盘、不进历史**：data URL 只在内存里活这一轮。
 */
internal object AiImageInbox {

    /**
     * 一张可用的图。
     *
     * @param index 第几张（**从 1 开始**，卡片上写「第 2 张」用的就是它）。
     * @param dataUrl data:image/jpeg;base64,...（与 [AiAttachment.imageDataUrl] 同一个形状）。
     */
    data class Picked(val index: Int, val dataUrl: String) {
        /** 大约多少 KB（base64 每 4 个字符 3 字节；只用于卡片上给用户一个规模感）。 */
        val approxKb: Int get() = (dataUrl.substringAfter(',', "").length * 3L / 4 / 1024).toInt()

        /** 卡片上的说法：「第 1 张（约 180 KB）」。 */
        fun label(): String = "第 $index 张（约 $approxKb KB）"
    }

    @Volatile
    private var items: List<Picked> = emptyList()

    /** 这一轮提问带了哪几张图（[AiAgentLoop.run] 入口调用；空表 = 把上一轮清掉）。 */
    fun set(dataUrls: List<String>) {
        items = dataUrls.mapIndexed { i, url -> Picked(i + 1, url) }
    }

    fun all(): List<Picked> = items

    /**
     * 取出要用的那一张。
     *
     * @param index 模型说的「第几张」（1 开始）。null = 它没点名。
     * @return 没图 → null（调用方按 [AiWriteImage.pickOrReject] 那样**拒绝**，不发空卡）；
     *         只有一张且没点名 → 就那一张；点名了但越界 → null。
     */
    fun pick(index: Int?): Picked? {
        val list = items
        if (list.isEmpty()) return null
        if (index == null) return list.singleOrNull()
        return list.firstOrNull { it.index == index }
    }

    /** 只给单测/退出用。 */
    fun clear() {
        items = emptyList()
    }
}
