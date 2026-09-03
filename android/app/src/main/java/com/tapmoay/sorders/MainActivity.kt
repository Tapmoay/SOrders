package com.tapmoay.sorders

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.Session
import com.tapmoay.sorders.ui.nav.AppRoot
import com.tapmoay.sorders.ui.theme.SOrdersTheme
import kotlinx.coroutines.runBlocking

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as SOrdersApp).container
        // 同步读一次会话，避免启动闪登录页
        val initialSession: Session? = runBlocking { container.tokenStore.current() }
        setContent {
            SOrdersTheme {
                AppRoot(container, initialSession)
            }
        }
    }

    override fun onDestroy() {
        // 释放 TTS 资源
        (application as? SOrdersApp)?.container?.tts?.shutdown()
        super.onDestroy()
    }
}
