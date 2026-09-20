package com.tapmoay.sorders.ai

import java.io.File

/**
 * 「一个本地 JSON 文件装一份列表」的**唯一实现** —— 对话历史与长期记忆共用（2026-09-21 精简轮）。
 *
 * ### 为什么必须只有一份
 * 这两个 store 原来是**逐行抄的两份**（各约 120 行），而它们守的是**同一批真实事故**：
 * 1. **先写 `.tmp` 再 `renameTo`**：直接往目标文件写，写一半被杀（低电、闪退）就是半截 JSON，
 *    整段数据全丢；改名在同一文件系统上是原子的 —— **要么旧的完整文件，要么新的完整文件**；
 * 2. **"还没读过盘就不许全量覆盖"**：调用方手上的列表是异步读进来的，读进来之前存一次
 *    就会把盘上原来的东西全部盖掉（**这是已经发生过的丢历史事故**，见 [save]）；
 * 3. **坏文件改名留证**（`*.bad-<时间戳>`）而不是删掉或覆盖 —— 用户的数据可能被别的版本写坏，
 *    留着才有可能救回来；
 * 4. **任何异常都不抛**：存不下不该让聊天功能挂掉。
 *
 * 抄两份的代价在本轮已经露头：[clear] 里"要不要把 `everLoaded` 置 true"两份写得不一样
 * （一个设、一个没设）—— 这类偏差不会报错，只会让"这两份到底哪份更可靠"变成掷骰子。
 *
 * ### 为什么这个类不带 Android 依赖
 * 它只认一个 [File]，于是**能在 JVM 单测里跑**（`AiJsonStoreTest`）—— 上面那四条以前
 * **一条都没有测试**（原来的 store 需要 `Context`，测试碰不到），而它们守的是数据不丢。
 *
 * ⚠️ 本类是**阻塞 IO**：调用方负责放到 `Dispatchers.IO` 上。
 */
internal class AiJsonStore<T>(
    private val file: File,
    private val encode: (List<T>) -> String,
    private val decode: (String) -> List<T>,
    /** 合并"盘上的 + 手上的"（同 id 以手上的为准）—— 只在"还没读过盘"那一次用得到。 */
    private val merge: (List<T>, List<T>) -> List<T>,
) {

    private val tmp = File(file.parentFile, file.name + ".tmp")

    /**
     * 是否**已经读过一次盘**。
     *
     * 这个标记只为一件事存在：[save] 的"防覆盖"兜底。
     * 它守的是一次真实的丢历史事故：ViewModel 的对话列表是异步读进来的，
     * 读进来之前调一次保存，就会把盘上原来的对话全部覆盖掉。
     */
    private var everLoaded = false

    /** 读全部。文件不存在 / 读失败 / 解析失败都返回空列表（**不抛异常**）。 */
    fun load(): List<T> {
        everLoaded = true
        if (!file.exists()) return emptyList()
        val text = try {
            file.readText()
        } catch (e: Exception) {
            return emptyList()
        }
        val list = decode(text)
        // 有内容却解析不出任何条目 = 文件坏了；留证而不是让它被下一次写盘覆盖
        if (list.isEmpty() && text.isNotBlank()) quarantine()
        return list
    }

    /** 只读盘、不改 [everLoaded]、不做隔离（供 [save] 的合并兜底使用）。 */
    private fun readSilently(): List<T> = try {
        if (file.exists()) decode(file.readText()) else emptyList()
    } catch (e: Exception) {
        emptyList()
    }

    /**
     * 全量覆盖写。**任何异常都不抛**（数据存不下不该让聊天功能挂掉）。
     *
     * ⚠️ **在"从未读过盘"时会退化成合并而不是覆盖**：此时调用方手上的列表不可能是全量
     * （它还没看过盘上有什么），直接覆盖等于删数据。这个分支只可能出现在启动后极短的时间窗内，
     * 代价是那一次多读一次文件，换来的是"打开就提问/就教它一句"不会抹掉旧数据。
     */
    fun save(list: List<T>): Boolean = try {
        val effective = if (everLoaded) list else merge(readSilently(), list)
        val payload = encode(effective)
        tmp.writeText(payload)
        if (!tmp.renameTo(file)) {
            // 改名失败（极少数文件系统）→ 退回直接写；此时会短暂失去原子性，但总比不存好
            file.writeText(payload)
            tmp.delete()
        }
        true
    } catch (e: Exception) {
        tmp.delete()
        false
    }

    /** 清空（删除文件）。 */
    fun clear(): Boolean = try {
        // 盘上已经没东西了 → 下次 save 不必再"先读一遍再合并"。
        // ⚠️ 这一行两个 store 原来不一致（一个设、一个没设），收口时统一成设 true：
        //    两条路的结果本来就相同（文件已删 → 静默读出空 → 合并结果 == 手上的列表），
        //    设 true 只是省掉一次多余的读。
        everLoaded = true
        tmp.delete()
        !file.exists() || file.delete()
    } catch (e: Exception) {
        false
    }

    /** 当前占用字节数（设置页显示用）。 */
    fun sizeBytes(): Long = try {
        if (file.exists()) file.length() else 0L
    } catch (e: Exception) {
        0L
    }

    /** 把坏文件改名留证；改不动就删（否则每次启动都会重复报错）。 */
    private fun quarantine() {
        try {
            val bad = File(file.parentFile, "${file.name}.bad-${System.currentTimeMillis()}")
            if (!file.renameTo(bad)) file.delete()
        } catch (e: Exception) {
            // 留证失败不影响主流程
        }
    }
}
