package com.tapmoay.sorders.core

import android.content.Context
import com.tapmoay.sorders.ui.nav.Role

/**
 * 提醒相关的**本机设置**（只存手机，不上传）。
 *
 * 为什么用 SharedPreferences 而不是项目里别处的 DataStore：
 * 这几项要在 **Socket 回调 / 前台服务 onCreate** 里**同步**判断，
 * 而 DataStore 只有挂起读——为了一个开关起协程读盘，会出现
 * "服务已经起来在收单、设置还没读出来"的竞态。
 */
class AlertPrefs(context: Context) {

    private val sp = context.applicationContext.getSharedPreferences("alerts", Context.MODE_PRIVATE)

    private object Keys {
        const val VOICE = "voice_enabled"
        const val REPEAT = "repeat_times"
        const val BACKGROUND = "background_enabled"
        const val BOOST = "boost_volume"
        const val LAST_NOTIFICATION_ID = "last_notification_id"
        const val NOTIFY_TOKEN = "notify_token"
    }

    /** 新单语音总开关。默认开——司机端最要紧的就是听见这一声。 */
    var voiceEnabled: Boolean
        get() = sp.getBoolean(Keys.VOICE, true)
        set(v) = sp.edit().putBoolean(Keys.VOICE, v).apply()

    /** 重复次数（0 = 一直响到接单），见 [NewOrderAlert.REPEAT_CHOICES] */
    var repeatTimes: Int
        get() = sp.getInt(Keys.REPEAT, NewOrderAlert.DEFAULT_REPEAT)
        set(v) = sp.edit().putInt(Keys.REPEAT, v).apply()

    /**
     * 关闭 App 后是否继续接收派单（前台服务常驻）。
     * **没设置过时按角色给缺省**：司机默认开（他的手机是要放在口袋里等活的），
     * 派单员/货主默认关（他们大部分时间在电脑前，多一条常驻通知是骚扰）。
     */
    fun backgroundEnabled(role: Role?): Boolean =
        if (sp.contains(Keys.BACKGROUND)) sp.getBoolean(Keys.BACKGROUND, false)
        else NewOrderAlert.defaultBackground(role)

    fun setBackgroundEnabled(v: Boolean) {
        sp.edit().putBoolean(Keys.BACKGROUND, v).apply()
    }

    /** 响铃时临时把媒体音量抬到 70%（播完还原） */
    var boostVolume: Boolean
        get() = sp.getBoolean(Keys.BOOST, true)
        set(v) = sp.edit().putBoolean(Keys.BOOST, v).apply()

    /**
     * 「我已经收到的最大站内信 id」——重连时回传给后端做断线回补的游标。
     *
     * ⛔ 原来这个游标只活在内存里（`RealtimeHub._lastNotificationId`，初始 0），
     *    进程被杀/重启后归零 → 后端按 id **升序**回补最旧的 200 条（R14-13，2026-09-19 审计）
     *    → 断线期间的消息**永远补不到**，"司机错过新单"的三层提醒在重启这条路径上是空的。
     *    **必须落盘**：它跨进程生命周期，只存内存等于没有。
     */
    var lastNotificationId: Long
        get() = sp.getLong(Keys.LAST_NOTIFICATION_ID, 0L)
        set(v) = sp.edit().putLong(Keys.LAST_NOTIFICATION_ID, v).apply()

    /**
     * 「这条 intent 真的是本机通知发出来的」凭据：每安装一个随机串，只落在本机私有存储。
     *
     * 为什么需要：[MainActivity] 是 LAUNCHER + `exported="true"`（桌面要能拉起它，
     * 不能改成 false，见清单里的注释），所以**任何 App** 都能发一个带
     * `sorders_order_id=<任意单号>` 的 intent 进来打断司机正在响的新单播报，
     * 而代码原来只判 `orderId > 0`——等于把外部可伪造的 extra 当成了凭据（报告 R2-NS-3）。
     * 不能靠"不给它 extra"来区分（Intent 是别人拼的），只能靠一个**猜不到的串**：
     * 随机生成、只在本机、不进源码/日志/网络。
     *
     * `synchronized` + `commit()` 不是保险：通知是从 Socket 回调线程建的，
     * 首次读盘可能与主线程（MainActivity 对照凭据）并发；两个线程各生成一个串的话，
     * 用旧串建出来的那些通知**点一下就失效**（静默，看不出来）。commit 保证落盘后再返回。
     *
     * ⚠️ 副作用（一次性的）：App 升级前就已经躺在通知栏里的那几条旧通知没带这个串，
     * 升级后点它们会落到首页而不是订单详情，再点一条新通知就恢复正常。
     */
    val notifyToken: String
        get() = synchronized(this) {
            sp.getString(Keys.NOTIFY_TOKEN, null) ?: java.util.UUID.randomUUID().toString().also {
                sp.edit().putString(Keys.NOTIFY_TOKEN, it).commit()
            }
        }
}
