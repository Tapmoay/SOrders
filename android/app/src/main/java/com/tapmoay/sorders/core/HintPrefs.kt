package com.tapmoay.sorders.core

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * 界面「提示/说明」的**唯一开关** —— 本类只做两件事：**落盘**与**对外暴露可观察状态**；
 * 三条行为决定（首次登录开一轮 / 冷启动关 / 手拨过不再自动改）在 [HintRound] 里，
 * 那是纯函数、有单测（`HintRoundTest`）。
 *
 * ## 为什么把旧机制删了
 * 旧规矩（用户 2026-09-20）是：每条解释性的话**最多出现 3 次**，第 4 次起再也不出现
 * （`MAX_TIMES` + 每条一个计数器 + `markSeen`）。用户 2026-09-21 的原话：
 *
 * > 「这个按钮的机制是这样子的：**每三次只展现三次，三次看见之后他就自动消失**。
 * >  **我们取消这个机制**，改成**一个按钮开关** —— 打开就打开**所有的提示相关的内容**，
 * >  关闭就关闭**所有的提示**，就按我们正常的按钮进行显示。」
 *
 * 所以现在**没有"每条各算各的"**这件事了：一个开关管全部。
 * ⛔ 那套 per-key 计数（`seen` / `markSeen` / `hasLeft` / `MAX_TIMES`）**已删除**；
 * `SharedPreferences("hints")` 里遗留的旧计数**不清理、只是不再读**（清数据是另一件事，
 * 而且升级用户不该因为几个残留整数出任何异常）。
 *
 * ## 口径
 * - 开关的默认值：**每台安装一次**（与夜间模式那些偏好同级），不是"每个账号一次"——
 *   同一台设备换账号登录不会又弹一轮；
 * - 读是**本机同步读**（SharedPreferences），与 `AlertPrefs` 同一个理由：这一读发生在**合成时**
 *   （决定一句话画不画），而 DataStore 只有挂起读 —— 为了一句话画不画而起协程读盘，
 *   会出现"先画一帧再消失"；
 * - 状态是 Compose **可观察**的，而且只有**一份**：设置页写它、各页面读它。
 *   分成"设置页一份、页面各一份"的话，用户会看到"我明明关了它还在"。
 */
class HintPrefs(context: Context) {

    private val sp = context.applicationContext.getSharedPreferences("hints", Context.MODE_PRIVATE)

    private var _state by mutableStateOf(load())

    /** 总开关当前状态。**组合里读它会订阅**（开关一拨，所有页面立刻跟着变）。 */
    val visible: Boolean get() = _state.visible

    /** 从盘上还原状态（含老安装的迁移口径，见 [HintRound.fromLegacy]）。 */
    private fun load(): HintRound.State = HintRound.State(
        visible = sp.getBoolean(KEY_VISIBLE, sp.getBoolean(LEGACY_ALWAYS_ON, false)),
        // 老安装（存在旧那个「一直显示」开关的键）＝ 第一轮早就走过了，⛔ 不补一轮
        roundShown = sp.getBoolean(KEY_FIRST_ROUND_DONE, sp.contains(LEGACY_ALWAYS_ON)),
        autoOffPending = sp.getBoolean(KEY_AUTO_OFF_PENDING, false),
    )

    /** 落盘 + 刷新可观察状态。**唯一的写入口**，别处不许直接改 `_state`。 */
    private fun apply(next: HintRound.State) {
        if (next == _state) return
        _state = next
        sp.edit()
            .putBoolean(KEY_VISIBLE, next.visible)
            .putBoolean(KEY_FIRST_ROUND_DONE, next.roundShown)
            .putBoolean(KEY_AUTO_OFF_PENDING, next.autoOffPending)
            .apply()
    }

    /**
     * **第一次登录**时调（`ui/login/LoginViewModel.kt` 登录成功那一步）。
     * 只有这台设备上的第一次会做什么；之后每次登录都是空操作。
     */
    fun onLogin() = apply(HintRound.onLogin(_state))

    /**
     * **每次冷启动**时调（`MainActivity.onCreate`）。上一轮是"首次登录那一轮"的话，
     * 到这里把它关上 —— 这就是用户说的「之后就默认关闭」。
     */
    fun onAppStart() = apply(HintRound.onAppStart(_state))

    /** **用户自己拨了开关**（设置页那一格）。动过之后再也不自动改。 */
    fun setByUser(on: Boolean) = apply(HintRound.setByUser(_state, on))

    // ⛔ 原来这里有个 `@Deprecated var alwaysOn`（兼容壳）：`ProfileScreen` 那一格在用它，
    //    而那个文件当时正被另一会话改（见 `docs/AI_WORK_CLAIM.md` 的「交叉点」）。
    //    2026-09-21 用户拍板「可以你现在就改吧」→ 设置页改用 `visible` / `setByUser()`，
    //    全仓再没有调用点，**壳已删除**（留着它就是"两种写法都行"的开始）。

    companion object {
        /** 总开关：true = 显示所有解释句。 */
        private const val KEY_VISIBLE = "visible"

        /** 「首次登录那一轮」是否已经走过（走过就不再自动打开）。 */
        private const val KEY_FIRST_ROUND_DONE = "first_round_done"

        /** 待自动关：首次登录那一轮开着，下一次冷启动要把它关上。 */
        private const val KEY_AUTO_OFF_PENDING = "auto_off_pending"

        /** 旧机制留下的键（旧那个「一直显示」开关）。**只读一次做迁移，不再写**。 */
        private const val LEGACY_ALWAYS_ON = "always_on"
    }
}
