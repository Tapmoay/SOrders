package com.tapmoay.sorders.core

import android.app.Activity
import android.app.Application
import android.os.Bundle

/**
 * App 现在是不是**在用户眼前**（FEAT-0027）。
 *
 * 为什么需要它：消息到达时要不要弹系统通知，取决于"用户是不是已经在看这个 App 了" ——
 * 在前台还弹一条，就是与界面里刚刚自己刷出来的那条消息**重复打扰**；
 * 而这件事在进程里没有任何现成的答案（全仓没有 ProcessLifecycleOwner，也没有别的前台标记）。
 *
 * 为什么用 Activity 生命周期计数而不是 ProcessLifecycleOwner：那个库要多引一个
 * `androidx.lifecycle:lifecycle-process` 依赖，而这里只需要一个布尔量；
 * Activity 的 onStart/onStop 已经足够表达"有没有界面在用户眼前"（切后台、锁屏都会 onStop）。
 *
 * ⚠️ 计数器只在主线程读写（Activity 回调），读它的可能是 Socket 回调线程 ⇒ 用 @Volatile。
 */
object AppForeground {

    @Volatile
    private var started = 0

    /** 有没有至少一个 Activity 处在"已启动"状态（onStart 之后、onStop 之前）。 */
    val visible: Boolean get() = started > 0

    /** 在 Application.onCreate 里装一次（见 [com.tapmoay.sorders.SOrdersApp]）。幂等由调用方保证。 */
    fun install(app: Application) {
        app.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityStarted(activity: Activity) {
                started += 1
            }

            override fun onActivityStopped(activity: Activity) {
                // ⛔ 不许减到负数：漏配一次 onStart 也会让 visible 永远为真（那等于前台判断失效，
                //    而表现只是"消息不弹了"，谁也不会往这里查）
                if (started > 0) started -= 1
            }

            override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) = Unit
            override fun onActivityResumed(activity: Activity) = Unit
            override fun onActivityPaused(activity: Activity) = Unit
            override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit
            override fun onActivityDestroyed(activity: Activity) = Unit
        })
    }
}
