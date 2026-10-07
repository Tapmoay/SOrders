package com.tapmoay.sorders.ai

import android.content.Context
import com.tapmoay.sorders.data.remote.dto.LedgerExportJobDto
import com.tapmoay.sorders.data.repo.AppRepository
import com.tapmoay.sorders.util.ExportedFile
import com.tapmoay.sorders.util.saveExportFileWithUri
import kotlinx.coroutines.delay
import java.io.IOException

/**
 * 「点一下按钮，把文件拿到手」这一段路（v3.34，CHG-0078）。
 *
 * ### 为什么它不在 [AiTools] 里
 * 工具回合**刻意不生成文件**：
 * - 账本导出要 POST 一个异步任务，而**配额是用户的**（每天 20 次）—— 模型替他花掉一次，
 *   他就少一次；口径 m01850 明确说配额保留，那就只能是"他自己点一下才算"。
 * - 报表导出在后端是现算（`reports.py` 一次要跑几秒到几十秒），用户只是问问的时候不该先等它跑完。
 *
 * 所以工具只回一条**配方**（导出什么、哪段时间、给谁），真正的取件发生在**用户点了下载之后**，
 * 由界面驱动 —— 模型既看不见、也插不上手。这就是本类存在的理由。
 */
class AiExportService(
    private val repo: AppRepository,
    private val context: Context,
) {

    /**
     * 取件并落盘。返回落盘结果（路径 + 可分享的 Uri）。
     *
     * @param onProgress 给界面的一行人话（"正在生成…"）——**只有账本那条路会用到**，
     *   因为只有它要等（报表那条路是当场流式返回的）。
     * @param onJobId 账本任务号一拿到就回调出去：调用方要把它写回配方，
     *   这样用户再点一次**只重新下载**，不再建任务、不再吃配额。
     */
    suspend fun deliver(
        recipe: StoredExportRecipe,
        onProgress: suspend (String) -> Unit = {},
        onJobId: suspend (Long) -> Unit = {},
    ): ExportedFile {
        val bytes = if (recipe.source == StoredExportRecipe.SOURCE_LEDGER) {
            ledgerBytes(recipe, onProgress, onJobId)
        } else {
            onProgress("正在生成…")
            reportBytes(recipe)
        }
        return saveExportFileWithUri(context, bytes, recipe.fileName)
            ?: throw IOException("文件没能存到「下载 / SOrders报表」，看一下存储空间再试一次。")
    }

    /**
     * 报表：`GET /reports/export` 现算现返（服务器**不留**文件，见 CHG-0078 的口径 m01850 ②）。
     *
     * `use { }` 不能省：不关这条响应流，OkHttp 的连接就回不到池子里，连着导几张表之后
     * 后面的请求会开始等连接（现象是"导出越来越慢"，而不是报错）。
     */
    private suspend fun reportBytes(recipe: StoredExportRecipe): ByteArray =
        repo.exportReport(
            kind = recipe.kind,
            mode = recipe.mode,
            date = recipe.date,
            dateFrom = recipe.dateFrom.takeIf { it.isNotBlank() },
            dateTo = recipe.dateTo.takeIf { it.isNotBlank() },
        ).use { it.bytes() }

    /**
     * 账本：申请任务（没有任务号时）→ 每 2 秒问一次 → 好了就取文件。
     *
     * 两个数都来自后端实测：单任务约 40 秒（`ledger.py` 那段注释记着 39.77 秒 / 峰值 469MB），
     * 所以 2 秒一次、最多 60 次（= 两分钟）足够；等超了就如实说"还没生成好"，
     * 而**不是**一直转圈 —— 用户手上还有那个任务号，再点一次是继续等它，不是重新排队。
     */
    private suspend fun ledgerBytes(
        recipe: StoredExportRecipe,
        onProgress: suspend (String) -> Unit,
        onJobId: suspend (Long) -> Unit,
    ): ByteArray {
        val jobId = recipe.jobId.takeIf { it > 0 } ?: run {
            onProgress("正在生成…")
            val job = repo.createLedgerExportJob(
                shipperId = recipe.shipperId,
                dateFrom = recipe.dateFrom,
                dateTo = recipe.dateTo,
            )
            onJobId(job.id)
            job.id
        }
        repeat(POLL_TIMES) { i ->
            val job = repo.ledgerExportJob(jobId)
            when (job.status) {
                LedgerExportJobDto.DONE -> {
                    onProgress("正在下载…")
                    return repo.downloadLedgerExportJob(jobId).use { it.bytes() }
                }
                LedgerExportJobDto.FAILED -> throw IOException(
                    job.errorMessage?.takeIf { it.isNotBlank() } ?: "这次生成失败了，再点一次试试。",
                )
                else -> {
                    onProgress("正在生成…（已等 " + (i + 1) * 2 + " 秒）")
                    delay(POLL_INTERVAL_MS)
                }
            }
        }
        throw IOException("两分钟还没生成好，稍后再点一次（任务还在，不用重新排队）。")
    }

    private companion object {
        const val POLL_INTERVAL_MS = 2_000L
        const val POLL_TIMES = 60
    }
}
