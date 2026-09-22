package com.tapmoay.sorders

import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import com.tapmoay.sorders.core.ApiEndpoint
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.NewOrderPlayer
import com.tapmoay.sorders.core.NotifyCenter
import com.tapmoay.sorders.core.PushTrust
import com.tapmoay.sorders.core.Session
import com.tapmoay.sorders.ui.common.LocalHints
import com.tapmoay.sorders.ui.nav.AppRoot
import com.tapmoay.sorders.ui.theme.AutoSunThemeEffect
import com.tapmoay.sorders.ui.theme.SOrdersTheme
import com.tapmoay.sorders.ui.theme.ThemeMode
import kotlinx.coroutines.runBlocking

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // DEBUG 构建：启动即探测后端并打印实际解析地址（验证 DNS 兜底链路）
        if (BuildConfig.DEBUG_LOG) {
            Thread {
                android.util.Log.i("SOrdersProbe", "resolved baseUrl=" + ApiEndpoint.baseUrl)
            }.start()
        }
        val container = (application as SOrdersApp).container
        // 「提示/说明」总开关的**冷启动**那一步：上一轮若是"首次登录那一轮"（见 HintPrefs 的 KDoc），
        // 到这里把它关上 —— 用户要的就是「首次登录开一轮，之后就默认关闭」。
        container.hintPrefs.onAppStart()
        // 通知渠道在**启动时就建**：渠道要存在过，系统设置页里才看得到、用户才能单独调它
        container.notifyCenter.ensureChannels()
        consumeIntent(intent, container, "onCreate")
        // 同步读一次会话，避免启动闪登录页
        val initialSession: Session? = runBlocking { container.tokenStore.current() }
        setContent {
            SOrdersTheme {
                // 「随日落自动切换夜间模式」的定时器。挂在**根**上而不是「我的」页面里：
                // 挂在页面里就只有用户停在那一页时才切，而他真正要它的时刻（晚上看订单）
                // 恰恰不在那一页。开关关着时它立刻返回，什么都不做。
                AutoSunThemeEffect()
                // ⚠️ 根节点**必须自己铺一层主题背景**。不铺的话，凡是"自己没画背景"的页面
                //    （实测：从工作台进的独立「消息中心」，它只有一个 Box）会直接露出
                //    **窗口底色**——那是主题 XML 里的白，夜间模式下就是一整块白板。
                //    底部 Tab 里看着正常，是因为那一层容器自己画了底；
                //    所以这个 bug 只在**独立路由**上露头，很容易漏掉。
                //
                //    修在根上而不是逐个页面补：漏一个页面就白一块，而"哪几个页面没画底"
                //    靠眼睛是数不完的（这一处就是用户报上来的）。
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    // 「提示/说明」的**唯一那一份**开关从这里提供下去（见 `ui/common/Hints.kt`）。
                    // 提供在**根**上而不是各页面自己拿：拨一下开关要立刻影响所有已经打开的页面；
                    // 各页面各拿一份的话，用户会看到"我明明关了它还在"。
                    CompositionLocalProvider(LocalHints provides container.hintPrefs) {
                        AppRoot(container, initialSession)
                    }
                }
            }
        }
    }

    /**
     * 回到前台**立刻对一次表**。
     *
     * 为什么不能只靠定时器：手机在后台放了一夜，进程会被系统冻结，
     * Compose 的 `delay` 在冻结期间根本不会醒——不补这一次，用户早上打开看到的还是夜间模式，
     * 而且没有任何报错（表现就是"自动切换时好时坏"）。
     */
    override fun onResume() {
        super.onResume()
        ThemeMode.refreshAuto(this)
    }

    /** 通知是 SINGLE_TOP 进来的（App 已在前台）不会重建 Activity，必须在这里也接一次 */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        consumeIntent(intent, (application as SOrdersApp).container, "onNewIntent")
    }

    /**
     * 点了通知 = 用户已经看到了那件事，所以：
     * 1. 立刻停止「来单了」播报（还在响会让人以为又来了新单）；
     * 2. 带单号的话交给 AppRoot 直达订单详情，不用用户自己在列表里再找一遍。
     *
     * ⚠️ 打断播报**必须挂在"这一单"上**（2026-09-19 审计 P1-15）：原来这里对**任何** intent
     * 都先 `stop()` 一次，而本 Activity 是 `exported=true` + LAUNCHER——司机正在响新单时，
     * 点一下桌面图标（或任何别的 App 拉起本 App）就把播报打断了，表现是"新单只响了一声"，
     * 而且没有任何报错、日志里也看不出被谁打断。
     *
     * ⛔ 光判 `orderId > 0` 不够（报告 R2-NS-3）：那个 extra 是**外部可伪造**的——
     * 本 Activity 必须能被桌面拉起（`exported` 不能改 false，见 AndroidManifest 的注释），
     * 于是任何 App 发一个 `sorders_order_id=<任意单号>` 的 intent 就能静默打断播报。
     * 所以真正的凭据是 [NotifyCenter.EXTRA_NOTIFY_TOKEN]：本机 [NotifyCenter.openApp]
     * 建 PendingIntent 时才附上的随机串（见 [AlertPrefs.notifyToken]）。
     * 对不上就**整条忽略**——不清会话、不崩溃、不提示（那是别人的 intent，不是我们的会话问题）。
     */
    private fun consumeIntent(intent: Intent?, container: AppContainer, from: String) {
        if (intent == null) return
        val raw = intent.getLongExtra(NotifyCenter.EXTRA_ORDER_ID, -1L)
        val orderId = PushTrust.trustedOrderId(
            orderId = raw,
            token = intent.getStringExtra(NotifyCenter.EXTRA_NOTIFY_TOKEN),
            mine = container.alertPrefs.notifyToken,
        )
        Log.i(NewOrderPlayer.TAG, "通知点击（$from）单号=$raw 采信=${orderId != null}")
        if (orderId != null) {
            container.newOrderPlayer.stop()
            container.pendingOrderId.value = orderId
        }
    }
}
