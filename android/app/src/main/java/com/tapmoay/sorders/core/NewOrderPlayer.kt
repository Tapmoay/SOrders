package com.tapmoay.sorders.core

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.util.Log
import com.tapmoay.sorders.R
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * 「来单了」的播放器（**司机听新派单、派单员听待派单**，见 [NewOrderAlert.speaks]）：
 * 放固定音频素材、按设置的次数重复、能被"活已经被人接走/派完"打断。
 *
 * 三个刻意的选择：
 * 1. **用音频素材而不是系统 TTS**：「来单了」是这套系统里最不能哑的一句话，
 *    而中文 TTS 语音包在国产 ROM 上经常不存在（放不出来时才退回 TTS 兜底）。
 * 2. **自己控制循环，而不是让通知渠道响铃**：渠道的声音一旦响起就停不下来，
 *    而司机接单后必须立刻闭嘴（否则司机会怀疑到底接上没有）。
 * 3. **响的时候把媒体音量抬到八成**（播完还原，见 [NewOrderAlert.BOOST_RATIO]）：
 *    手机常常是静音/低音量，"响过了但没听见"等于没响。这一条可以在设置里关掉。
 */
class NewOrderPlayer(
    private val context: Context,
    private val tts: TtsManager,
    private val prefs: AlertPrefs,
) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private var job: Job? = null
    private var player: MediaPlayer? = null
    private var savedVolume: Int? = null

    val isPlaying: Boolean get() = job?.isActive == true

    /** 开始播报（已经在播则先掐掉，重新开始：新单比旧单要紧） */
    fun play(kind: AlertKind, plan: AlertPlan) {
        stop()
        if (!prefs.voiceEnabled) {
            Log.i(TAG, "不播报：语音提醒被用户关掉了")
            return
        }
        Log.i(TAG, "开始播报 kind=$kind 次数=${if (plan.forever) "一直响" else plan.repeats.toString()}")
        job = scope.launch { loop(kind, plan) }
    }

    /** 立刻闭嘴：司机接单、任务撤回、用户点了通知，都要走这里 */
    fun stop() {
        val j = job
        // 只在**真的在播**时打这条：否则日志会天天喊"被打断"，真出事时没人信它
        if (j?.isActive == true) Log.i(TAG, "播报被打断（接单/撤回/点了通知）")
        j?.cancel()
        job = null
        releasePlayer()
        restoreVolume()
    }

    private suspend fun loop(kind: AlertKind, plan: AlertPlan) {
        boostVolumeIfNeeded()
        var done = 0
        var ttsBroken = false
        try {
            // ⚠️ 判活必须用**协程自己的** context，不能用 `job?.isActive`：
            //    play() 是从 UI 线程调用的（设置页「试听一声」），而 scope 用的是
            //    Dispatchers.Main.immediate —— 协程体会在 `job = scope.launch{}` 赋值**之前**
            //    就同步跑起来，那一刻 `job` 还是 null，循环一次都不进，表现是
            //    「点了试听什么都没播，日志却写着共播了 0 次」。
            //    从 Socket 回调（后台线程）调时不会有这个问题——所以只在真机上点按钮才暴露。
            while (currentCoroutineContext().isActive) {
                if (!plan.forever && done >= plan.repeats) break
                // 「一直响」的止损：没人接的单不能响一整夜
                if (plan.forever && done * (NewOrderAlert.clipMs(kind) + plan.gapMs) > NewOrderAlert.FOREVER_MAX_MS) break

                // 素材放不出来（机型解码问题/资源被裁）→ 退回 TTS 并一直用它：
                // 有声音永远好过"以为响了其实什么都没播"。
                if (ttsBroken || !playOnce(kind)) {
                    // 已经被叫停（司机接单/点了通知）就别再补一嗓子——
                    // 这是"接单后还在喊"的另一种形态，来源是取消被当成播放失败
                    currentCoroutineContext().ensureActive()
                    ttsBroken = true
                    Log.w(TAG, "音频素材放不出来，退回系统 TTS")
                    tts.speak(voiceText(kind))
                    delay(NewOrderAlert.clipMs(kind))
                }
                done++
                if (!plan.forever && done >= plan.repeats) break
                delay(plan.gapMs)
            }
        } finally {
            Log.i(TAG, "播报结束：完整播了 $done 次")
            releasePlayer()
            restoreVolume()
        }
    }

    private fun voiceText(kind: AlertKind): String = when (kind) {
        AlertKind.NEW_ORDER -> "来单了"
        AlertKind.PENDING_ORDER -> "有新订单待派单"
        AlertKind.REVOKED -> "有任务被撤回"
    }

    /**
     * 这一类播报用哪份素材。
     *
     * ⚠️ 「撤回」跟着司机那句走（本来是给"来单了"用的）：它只有喇叭、没有对应的语音素材，
     *    真机上听起来就是「来订单了」——**这是一处已知的老毛病**（见声明页），
     *    不要照它推断"撤回应该喊来单了"。
     */
    private fun clipRes(kind: AlertKind): Int = when (kind) {
        AlertKind.PENDING_ORDER -> R.raw.pending_order
        else -> R.raw.new_order
    }

    /** 放一遍素材；失败返回 false（由调用方决定要不要退回 TTS） */
    private suspend fun playOnce(kind: AlertKind): Boolean {
        val attrs = AudioAttributes.Builder()
            // USAGE_MEDIA：跟着媒体音量走（司机开车时媒体音量通常开着导航）
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()
        val mp = try {
            MediaPlayer.create(context, clipRes(kind), attrs, AudioManager.AUDIO_SESSION_ID_GENERATE)
        } catch (_: Exception) {
            null
        } ?: return false
        player = mp
        return try {
            mp.start()
            // 素材时长 = NewOrderAlert.clipMs(kind)（红线拿 wav 文件头对账，改素材不改常量会报红）
            delay(NewOrderAlert.clipMs(kind))
            true
        } catch (e: CancellationException) {
            // ⚠️ 取消必须原样抛出，**不能**被下面那个 catch(Exception) 吞掉：
            // 吞掉的话调用方会认为"播放失败了"，于是退回 TTS 再喊一句「来单了」——
            // 司机刚按了接单，手机却又喊了一嗓子。真机验证时抓到过这一条。
            throw e
        } catch (_: Exception) {
            false
        } finally {
            releasePlayer()
        }
    }

    private fun releasePlayer() {
        val mp = player ?: return
        player = null
        try {
            if (mp.isPlaying) mp.stop()
        } catch (_: Exception) {
        }
        try {
            mp.release()
        } catch (_: Exception) {
        }
    }

    private fun boostVolumeIfNeeded() {
        if (!prefs.boostVolume) return
        val am = context.getSystemService(AudioManager::class.java) ?: return
        val max = am.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
        val cur = am.getStreamVolume(AudioManager.STREAM_MUSIC)
        val target = NewOrderAlert.boostTarget(max, cur) ?: return
        try {
            am.setStreamVolume(AudioManager.STREAM_MUSIC, target, 0)
            savedVolume = cur
        } catch (_: Exception) {
            // 勿扰/被系统策略挡下：不改变行为，照常尝试播报
        }
    }

    private fun restoreVolume() {
        val back = savedVolume ?: return
        savedVolume = null
        val am = context.getSystemService(AudioManager::class.java) ?: return
        try {
            am.setStreamVolume(AudioManager.STREAM_MUSIC, back, 0)
        } catch (_: Exception) {
        }
    }

    companion object {
        /**
         * 排障用日志标签：司机说「没响」时，`adb logcat -s SOrdersAlert`
         * 能直接看出是"根本没收到事件"还是"收到了但没播出来"——
         * 这两种情况在界面上完全一样（都是一片安静）。
         */
        const val TAG = "SOrdersAlert"
    }
}
