package com.tapmoay.sorders.ai

import com.tapmoay.sorders.BuildConfig

/**
 * AI 接口地址（Base URL）的校验 —— **全 App 唯一一处**。
 *
 * ### 为什么发布包必须是 https（2026-09-19 全项目报告 P1-6）
 * 用户在这里填的是「把 API Key 发到哪里」。明文 `http://` 的后果不是"慢一点"：
 * 同网段的人（公共 Wi-Fi、AR P 欺骗）能**直接读走那个 Key**，而且他改掉 base_url 就能让
 * App 把 Key 与全部对话内容发到**他自己的主机**上 —— 用户界面上一点异常都看不出来。
 *
 * ### 为什么不是"只提示一下"
 * 发布包已经 `cleartextTrafficPermitted=false`（见 `res/xml/network_security_config.xml`，
 * 2026-09-19 报告 C-1）：真机上 `http://` 根本连不出去，用户看到的是"网络连接失败"。
 * 与其让他对着一个连不上的地址猜，不如在这里给一句能照着做的中文。
 *
 * ### debug 为什么放行
 * 本地联调就是明文（模拟器 → 宿主机 `http://10.0.2.2:8000`、局域网里的自建模型服务），
 * 而 debug 变体的网络策略是**单独一份**（`src/debug/res/xml/`）——发布包拿不到那份。
 */
object AiEndpointRules {

    /**
     * 返回 null 表示可以保存/使用；否则是**能给用户看的中文**。
     *
     * ⚠️ 判据只有这一处：AI 设置页的三处（拉模型 / 保存 / 测试连接）与 `LlmClient` 的两处
     * 都调它 —— 原来这五处各自抄了一遍 `startsWith("http://") || startsWith("https://")`，
     * 改一次要改五遍，必然漏。
     *
     * `debug` 做成参数（默认取 `BuildConfig.DEBUG`）是为了**能单测**：单测跑在 debug 变体上，
     * 常量恒为 true，那样"发布包必须 https"这条分支就永远测不到。
     */
    fun error(raw: String, debug: Boolean = BuildConfig.DEBUG): String? {
        val url = raw.trim()
        if (url.isEmpty()) return "请填写 Base URL"
        if (url.startsWith("https://")) return null
        if (url.startsWith("http://")) {
            if (debug) return null   // 本地联调：debug 包允许明文
            return "Base URL 必须以 https:// 开头：明文 http 会让同网段的人拿走你的 API Key，" +
                "也能把你的请求改发到别的主机。本地自测请用 debug 包（那边允许明文）。"
        }
        return "Base URL 要以 https:// 开头（当前：$url）"
    }

    /** 需要"必须 https"这句更短的说法时用（卡片/提示条）。 */
    fun isUsable(raw: String): Boolean = error(raw) == null
}
