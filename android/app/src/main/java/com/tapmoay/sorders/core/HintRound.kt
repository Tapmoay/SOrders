package com.tapmoay.sorders.core

/**
 * 「提示」总开关的**状态机**（纯函数，无 Android 依赖 → **有单测**）。
 *
 * ## 它表达的三条用户决定
 * 用户 2026-09-21：「首次登录打开的之后就默认关闭，当然也可以手动打开」——
 * 实现成三步：
 * 1. [onLogin]：**这台设备的第一次登录**把开关打开（新用户第一轮能看到全部说明）；
 * 2. [onAppStart]：下一轮**冷启动**把它关上（"之后就默认关闭"）；
 * 3. [setByUser]：用户自己拨过之后**永不自动改**。
 *
 * ## 为什么把决策抠成纯函数
 * 这三条是**行为契约**，而它们原来埋在一个需要 `Context` 的类里 → 只能靠真机点开关验证，
 * 而"第一次登录 / 第二次冷启动 / 手动关掉再登录"这三种**顺序**恰恰是自动化最该覆盖、
 * 真机又最难点准的地方。抠出来之后 `HintRoundTest` 直接跑这几种顺序。
 *
 * ⛔ 判据**只许在这里**：`HintPrefs` 负责落盘、`ui/common/Hints.kt` 负责画不画，
 * 谁都不许自己再判一遍（两份判断＝两个答案）。
 */
object HintRound {

    /** 三个开关位的全部状态。 */
    data class State(
        /** 总开关：true = 显示所有解释句。 */
        val visible: Boolean,
        /** 「首次登录那一轮」是否已经走过。 */
        val roundShown: Boolean,
        /** 待自动关：那一轮还开着，下一次冷启动要把它关上。 */
        val autoOffPending: Boolean,
    )

    /** 全新安装：[visible] 默认关（第一次登录时才打开）。 */
    val FRESH = State(visible = false, roundShown = false, autoOffPending = false)

    /**
     * 老安装（用户动过旧那个「一直显示」开关）的初始状态。
     *
     * ⛔ **不补一轮**：他早就见过那些话了，升级之后又给他打开一遍是打扰。
     * 所以 `roundShown` 直接记成 true —— 哪怕旧值是关的。
     */
    fun fromLegacy(legacyAlwaysOn: Boolean): State =
        State(visible = legacyAlwaysOn, roundShown = true, autoOffPending = false)

    /** 登录成功：只有这台设备的第一次登录会打开开关，之后每次都是原样返回。 */
    fun onLogin(s: State): State =
        if (s.roundShown) s
        else s.copy(visible = true, roundShown = true, autoOffPending = true)

    /** 冷启动：上一轮若是"首次登录那一轮"，到这里关上。没有待办就原样返回。 */
    fun onAppStart(s: State): State =
        if (!s.autoOffPending) s
        else s.copy(visible = false, autoOffPending = false)

    /**
     * 用户自己拨了开关。动过之后：
     * - `autoOffPending` 清掉（否则他关掉、退出登录、下次冷启动又被"关"一次，看着像失灵）；
     * - `roundShown` 记成 true（否则他手动关掉再登进来，会被当成新用户又打开一次）。
     */
    fun setByUser(s: State, on: Boolean): State =
        s.copy(visible = on, roundShown = true, autoOffPending = false)
}
