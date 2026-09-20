package com.tapmoay.sorders.core

import android.content.Context

/**
 * 「这条界面提示已经出现过几次」—— 用户 2026-09-20 定的规矩：
 *
 * > 有些功能不需要说太多…大概字数最多是 7 到 8 个字就可以了…
 * > 或者你可以这样子：第一次和第二次的时候它是出现在那里，下次再点击的时候它就不会有了…
 * > 第四次就不会有了。
 *
 * 所以凡是**解释性**的话（"按下去会写哪三处""这个库是怎么来的""删了还能不能恢复"），
 * 都不该永远钉在界面上：前 [MAX_TIMES] 次说清楚，之后让位给功能本身。
 * 常驻的文字只留"几个字"—— 那句话是给**已经会的人**看的，不是每次都重新教一遍。
 *
 * 为什么用 SharedPreferences 而不是项目里别处的 DataStore（与 [AlertPrefs] 同一个理由）：
 * 这一读发生在**合成时**（`HintOnce` 要先知道"画不画"再决定渲染什么），
 * 而 DataStore 只有挂起读 —— 为了决定一句话画不画而起协程读盘，
 * 会出现"先画一帧再消失"（闪一下比不显示更难受）。
 */
class HintPrefs(context: Context) {

    private val sp = context.applicationContext.getSharedPreferences("hints", Context.MODE_PRIVATE)

    /**
     * 内存里的"上一次记账"时刻（只活在本进程里，不进盘）：
     * 用来把**同一次进入**里的重复合成挡掉（见 [markSeen] 的注释）。
     */
    private val lastMarked = mutableMapOf<String, Long>()

    /** 这个提示已经出现过几次（没出现过 = 0）。 */
    fun seen(key: String): Int = sp.getInt(key, 0)

    /**
     * 记一次"真的显示出来了"。
     *
     * ⚠️ **同一次进入里只记一次**（[GUARD_MS] 之内重复调用不算）：Compose 会把
     *    `LazyColumn` 的 item 回收再合成（页面上那几个提示就贴在卡片里），
     *    重新合成会让 `LaunchedEffect` 再跑一遍 —— 不设这道闸的话"第 4 次才消失"
     *    会变成"第 3 次就没了"（**真机实测**：订单详情页里位置图片那条提示在第 3 次进入时
     *    就已经不显示，而同页的补导航提示正常 1/2/3 显示、第 4 次消失 —— 两条唯一的差别
     *    就是它们所在的合成块被回收的时机）。
     *
     * 闸设的是**时间**而不是"页面身份"：`HintOnce` 拿不到"这是第几次进入这一页"
     *    （那是导航层的事），而"同一次进入"在时间上必然挨得很近（毫秒级）。
     */
    fun markSeen(key: String) {
        val now = System.currentTimeMillis()
        if (now - (lastMarked[key] ?: 0L) < GUARD_MS) return
        lastMarked[key] = now
        sp.edit().putInt(key, seen(key) + 1).apply()
    }

    /**
     * 「提示一直显示」—— 打开后**不走**"最多三次"这个机制（用户 2026-09-20：
     * 「有个按钮在我的里面…可以常开，默认是关闭的。常开的意思是就不会走这个机制，就是一直显示」）。
     *
     * 默认 **关**：大多数用户在第三遍之后就不需要再被教了；留这个开关是给
     * "想不起来当初那句话是怎么说的"的人（以及演示/验收时）。
     */
    var alwaysOn: Boolean
        get() = sp.getBoolean(ALWAYS_ON, false)
        set(v) = sp.edit().putBoolean(ALWAYS_ON, v).apply()

    /** 还有没有额度（还有 ⇒ 这一次进入仍然显示）。[alwaysOn] 打开时永远有。 */
    fun hasLeft(key: String): Boolean = alwaysOn || seen(key) < MAX_TIMES

    /**
     * ⛔ 这里**删掉了一个 `resetAll()`**（2026-09-21 精简轮）。
     *
     * 它的 KDoc 写着「全部归零（设置页那个「重置界面提示」）」，而那个入口**从来没有做过** ——
     * 全仓搜 `resetAll` 只有它自己那一行声明（`ProfileScreen` 的「界面提示」块里只有一个
     * 「一直显示」开关，没有重置）。也就是说：一句"给用户看的说明"承诺了一个不存在的按钮，
     * 而**没有任何检查会红**（`_check_dead_code.py` 只查文件内没人用的 private 声明，
     * 这个方法是 public）。
     *
     * 为什么是删方法而不是补按钮：补按钮是**加一个功能**（要不要给用户一个"重置界面提示"的
     * 入口，是用户的决定，已列进待拍板）。删掉之后"想再看一遍那几句话"仍然有两条路：
     * ① 上面的「一直显示」开关；② 清 App 数据（会连登录态一起丢）。
     * 要补入口的话，**在 `ProfileScreen` 的「界面提示」块里加**，别只把方法加回来。
     */

    companion object {
        /** 一条解释性提示最多出现几次（用户给的数字：**第 4 次起不再出现**）。 */
        const val MAX_TIMES = 3

        /**
         * 同一次进入里的重复记账闸（毫秒）。合成是毫秒级的，2 秒足够宽；
         * 而"退出去再进来"通常也要 1~2 秒以上，不会被它吃掉。
         */
        const val GUARD_MS = 2000L

        private const val ALWAYS_ON = "always_on"
    }
}
