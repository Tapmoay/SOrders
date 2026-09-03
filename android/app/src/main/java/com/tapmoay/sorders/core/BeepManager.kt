package com.tapmoay.sorders.core

import android.media.AudioManager
import android.media.ToneGenerator

/** 新消息提示音（短促哔声，不打扰不刺耳；司机端另有 TTS 语音播报） */
class BeepManager {

    private var tone: ToneGenerator? = null

    init {
        try {
            tone = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 60)
        } catch (_: Exception) {
            tone = null
        }
    }

    fun beep() {
        try {
            tone?.startTone(ToneGenerator.TONE_PROP_BEEP, 180)
        } catch (_: Exception) {
            // 忽略：提示音失败不影响业务
        }
    }

    fun shutdown() {
        try {
            tone?.release()
        } catch (_: Exception) {
        }
        tone = null
    }
}
