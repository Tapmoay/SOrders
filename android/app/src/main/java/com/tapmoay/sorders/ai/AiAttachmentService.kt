package com.tapmoay.sorders.ai

import com.tapmoay.sorders.data.repo.AppRepository

/**
 * 附件装载：把「手机里选中的文件」变成模型看得懂的 [AiAttachment]。
 *
 * 只有一件事：上传给服务端读成文本表格，再把 DTO 转成本包自己的模型。
 * 之所以单独一层（而不是让聊天页直接调 repo）：
 * - 聊天页不该知道后端 DTO 长什么样（换字段名时只改这里）；
 * - 这一层在纯 JVM 单测里可以塞一个假的 AppRepository 之外的东西来测映射规则。
 */
class AiAttachmentService(private val repo: AppRepository) {

    /**
     * 上传并解析。
     *
     * @param maxRows 每张表最多读几行。500 是给"确实要看长表"的场景留的余量——
     *   再多读没有意义：附件最终要塞进模型的上下文，[AiAttachment.MAX_PROMPT_CHARS] 那道闸
     *   终究会把它砍到一万多字符，用户看到的行数反而更少。
     */
    suspend fun load(
        filename: String,
        mime: String,
        bytes: ByteArray,
        maxRows: Int = 500,
    ): AiAttachment {
        val dto = repo.parseSheet(filename, mime, bytes, maxRows)
        return AiAttachment(
            filename = dto.filename.ifBlank { filename },
            kind = dto.kind,
            tables = dto.tables.map {
                AiAttachment.Table(
                    name = it.name,
                    rows = it.rows,
                    rowCount = it.rowCount,
                    colCount = it.colCount,
                    truncated = it.truncated,
                )
            },
            warnings = dto.warnings,
        )
    }
}
