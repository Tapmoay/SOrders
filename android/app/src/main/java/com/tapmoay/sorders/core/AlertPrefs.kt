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
}
