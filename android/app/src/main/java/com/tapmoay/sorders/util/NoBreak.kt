package com.tapmoay.sorders.util

/**
 * 把一串**不能被折行劈开**的短串（订单号 / 电话 / 账号）包成"整块不换行"。
 *
 * ## 为什么需要它
 * Compose 的 `Text` 按 Unicode 换行机会折行，而 20 个字符的订单号（`SO` + 18 位数字）
 * 中间**处处都是换行点**：窄一点的地方（弹层标题、Snackbar）就会从数字中间断开，读起来像两个数。
 * 这里在相邻字符之间插入 U+2060 WORD JOINER —— 它零宽、不可见，只是把"可以在这里换行"改成
 * "不许在这里换行"，于是这一串要么整块留在行尾、要么整体挪到下一行（走查 P4）。
 *
 * ⚠️ 只在**标题 / 单行**这种"折了就读不出来"的地方用；正文段落里别用（长串会顶破窄布局）。
 * ⚠️ ⛔ 不要拿它去拼**要回传后端或存库**的字符串：U+2060 会跟着进去（本函数只服务界面显示）。
 * ⚠️ 粘进剪贴板的原文**不带**这些字符：剪贴板走的是源字符串，与这里渲染的副本无关。
 */
fun String.noBreak(): String {
    if (length < 2 || contains('\u2060')) return this
    val sb = StringBuilder(length * 2)
    forEachIndexed { i, c ->
        if (i > 0) sb.append('\u2060')
        sb.append(c)
    }
    return sb.toString()
}
