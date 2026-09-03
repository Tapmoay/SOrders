package com.tapmoay.sorders.core

import android.content.Context
import android.speech.tts.TextToSpeech
import java.util.Locale

/** Android TTS 封装：新单/撤销等关键事件语音播报 */
class TtsManager(context: Context) {

    private var tts: TextToSpeech? = null

    init {
        tts = TextToSpeech(context.applicationContext) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale.CHINA
            }
        }
    }

    fun speak(text: String) {
        val t = tts ?: return
        t.speak(text, TextToSpeech.QUEUE_ADD, null, "sorders_tts")
    }

    fun shutdown() {
        tts?.stop()
        tts?.shutdown()
        tts = null
    }
}
