package com.tapmoay.sorders.ui.common

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Build

/**
 * 把纯文本写进**系统剪贴板**，并告诉调用方"还要不要自己弹一句提示"。
 *
 * ## 为什么用系统 `ClipboardManager` 而不是 Compose 的 `LocalClipboardManager`
 * 后者在 Android 13+ 之后已被标记为"只在 Compose 内部用"，跨版本行为不一致；
 * 而这里要的行为很明确 —— 把纯文本放进系统剪贴板，让用户能粘到微信里。
 * （这条理由是 2026-09-15 在 AI 聊天页踩出来的，现在收进这一处，别再各写各的。）
 *
 * ## 返回值 = **还要不要自己弹提示**
 * Android 13（API 33）起系统自己会弹一个"已复制"浮层 —— 我们再弹一句就是两条提示叠在一起。
 * 所以：`true` 才弹（老系统），`false` 什么都不用做（新系统已经告诉用户了）。
 *
 * ## 空文本
 * 空/空白一律**不写剪贴板**（会把用户原先复制的东西冲掉，而他什么也没得到），返回 `false`。
 *
 * @param label 剪贴板条目的标签（`ClipData.newPlainText` 的 label），一般写"单号"/"地址"
 */
fun copyTextToClipboard(context: Context, label: String, text: String): Boolean {
    if (text.isBlank()) return false
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return false
    cm.setPrimaryClip(ClipData.newPlainText(label, text))
    return Build.VERSION.SDK_INT < 33
}
