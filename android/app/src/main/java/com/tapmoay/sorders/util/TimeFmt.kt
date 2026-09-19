package com.tapmoay.sorders.util

import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** ISO8601（后端 created_at 等）转本地 "MM-dd HH:mm" */
fun formatDateTime(iso: String?): String {
    if (iso.isNullOrBlank()) return ""
    return runCatching {
        val t = OffsetDateTime.parse(iso)
        DateTimeFormatter.ofPattern("MM-dd HH:mm")
            .format(t.atZoneSameInstant(ZoneId.systemDefault()))
    }.getOrElse {
        // 后端部分字段无时区（date 型），退化为截断显示
        iso.take(16).replace('T', ' ')
    }
}

fun formatDateCN(iso: String?): String = iso?.take(10) ?: ""

fun today(): String = LocalDate.now().toString()
