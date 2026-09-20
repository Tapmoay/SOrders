package com.tapmoay.sorders.ai

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.io.File
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * API Key / 模型配置的本地存储。
 *
 * ### 为什么不用 EncryptedSharedPreferences
 * Jetpack Security Crypto（`androidx.security:security-crypto`）的**全部 API 已被官方标记弃用**，
 * Google 的建议是直接用平台 Keystore API。所以这里：
 * - 用 [KeyGenParameterSpec] + [KeyGenerator] 在 **AndroidKeyStore** 里生成一把 AES-256 密钥
 *   （别名 [ALIAS]，`setUserAuthenticationRequired(false)` —— 用户不需要每次解锁才能用 AI）；
 * - 用 `AES/GCM/NoPadding` 加密 API Key（GCM 自带完整性校验，篡改会直接解密失败）；
 * - **只把密文 + IV（Base64）** 写进 SharedPreferences，明文永远不落盘。
 *
 * ### 非敏感数据
 * Base URL、模型名、工具开关、思考模式开关不是机密，直接明文存 SharedPreferences（方便排障）。
 *
 * ### 优雅降级（重要）
 * 系统清空 Keystore（换机恢复备份、清除凭据、系统升级异常）后，旧密文再也解不开。
 * 此时 [apiKey] **不抛异常**，而是删掉脏数据并返回 null —— 用户重新填一次即可，绝不崩 App。
 *
 * ⚠️ 模拟器注意：AVD 的 AndroidKeyStore 是完整实现（软件 TEE），加解密与真机行为一致；
 * 但「清除数据 / 卸载重装」会连同 Keystore 别名一起删掉，此时必须重新输入 key。
 *
 * ### 【红线】这份数据属于谁 —— 凭据必须按用户分区
 * 这里曾是 [AiScope] 那条账上**唯一漏掉的一份**：同容器的对话/习惯/记忆都按用户分区了，
 * 而凭据用的是固定串 prefs 名 `sorders_ai_prefs`（2026-09-19 审计 P0-6）。
 * 后果不是"设置串了"这么轻：**同一台手机换账号后，下一个登录的人能读出上一个人的明文 LLM Key**
 * （点一下设置页的眼睛图标即是明文；不点也能用——聊天与"测试连接"走的就是它，账单记在上一人头上）。
 *
 * 做法与 [AiHabitStore] 完全一致：**prefs 名带上分区后缀**（[PREFS_NAME] + scope），
 * 而不是在里面加一层 key——旧的无分区文件自然就没人读了。**但不只是"没人读"**：
 * 无分区的旧文件在 [init] 里被**隔离改名**（见 [AiScope.quarantineLegacy]），
 * 因为"我们不知道那把 Key 是谁的"，绝不能把它交给现在登录的这个人。
 */
class AiKeyStore(
    context: Context,
    /**
     * 用户分区后缀（见 [AiScope]）。**刻意不给默认值**：留一个默认空串，
     * 下一个调用点就会写出"忘了传分区"的凭据 store——而那正是本类要修的那个 bug。
     */
    scope: String,
) {

    private val prefs = context.applicationContext
        .getSharedPreferences(PREFS_NAME + scope, Context.MODE_PRIVATE)

    init {
        // 无分区的旧凭据文件（`sorders_ai_prefs.xml`）隔离改名：
        // 改完是 `sorders_ai_prefs.xml.legacy-<时间戳>`，系统再也不会把它当 prefs 读。
        // 不删（可人工找回），但**绝不归给现在登录的人**——理由见类注释。
        AiScope.quarantineLegacy(
            File(context.applicationContext.filesDir.parentFile, "shared_prefs"),
            PREFS_NAME + ".xml",
        )
    }

    // ---------------------------------------------------------------- API Key

    /**
     * 加密保存 API Key。传空白字符串等价于 [clearApiKey]。
     * @return true = 已保存；false = 加密失败（此时**不会**退化成明文存储，key 保持原值不变）
     */
    fun saveApiKey(key: String): Boolean {
        val plain = key.trim()
        if (plain.isEmpty()) {
            clearApiKey()
            return true
        }
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, secretKey())
            val cipherText = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
            prefs.edit()
                .putString(KEY_CIPHER, base64(cipherText))
                .putString(KEY_IV, base64(cipher.iv))
                .apply()
            true
        } catch (e: Exception) {
            // 加密不可用（极少数设备/被 root 改坏）：不清除用户输入，让上层提示
            false
        }
    }

    /** 解密读取 API Key。任何异常（密钥被清、密文损坏）→ 清掉脏数据并返回 null。 */
    fun apiKey(): String? {
        val ct = prefs.getString(KEY_CIPHER, null) ?: return null
        val iv = prefs.getString(KEY_IV, null) ?: run { clearApiKey(); return null }
        return try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(GCM_TAG_BITS, unBase64(iv)))
            String(cipher.doFinal(unBase64(ct)), Charsets.UTF_8).takeIf { it.isNotBlank() }
        } catch (e: Exception) {
            // KeyPermanentlyInvalidatedException / AEADBadTagException / UnrecoverableKeyException …
            // 统一按「解不开」处理：清掉脏数据，当作用户没配过
            clearApiKey()
            null
        }
    }

    /** 只删密文，不动 Keystore 别名（下次保存会自动复用/重建）。 */
    fun clearApiKey() {
        prefs.edit().remove(KEY_CIPHER).remove(KEY_IV).apply()
    }

    fun hasKey(): Boolean = apiKey()?.isNotBlank() == true

    // ------------------------------------------------------------ 模型配置

    /** 保存 Base URL + 模型名 + 思考强度（**不含 key**；key 走 [saveApiKey] 单独加密存）。 */
    fun saveConfig(cfg: LlmConfig) {
        prefs.edit()
            .putString(KEY_BASE_URL, cfg.baseUrl.trim())
            .putString(KEY_MODEL, cfg.model.trim())
            .putString(KEY_THINKING_LEVEL, cfg.thinkingLevel.key)
            .apply()
    }

    /**
     * 读取模型配置。Base URL / 模型名任一为空时用默认值补齐；
     * 返回 null 表示**用户从未保存过配置**（全新装机），此时 [apiKey] 也一定没配。
     *
     * 思考强度没存过时用 [DEFAULT_THINKING_LEVEL]（= 中）；老版本存的是布尔
     * `thinking`，会在这里**就地迁移**（见 [readThinkingLevel]）。
     *
     * 上下文窗口**不由用户决定**（用户口径：不要让他选），所以这里只按模型名推断 +
     * 用撞过上限的真实结论覆盖（见 [windowFor]）。
     */
    fun config(): LlmConfig? {
        val base = prefs.getString(KEY_BASE_URL, null)?.trim().orEmpty()
        val model = prefs.getString(KEY_MODEL, null)?.trim().orEmpty()
        if (base.isEmpty() && model.isEmpty()) return null
        val m = model.ifEmpty { DEFAULT_MODEL }
        return LlmConfig(
            baseUrl = base.ifEmpty { DEFAULT_BASE_URL },
            apiKey = apiKey().orEmpty(),
            model = m,
            thinkingLevel = readThinkingLevel(),
            contextWindow = windowFor(m),
        )
    }

    /** 没保存过配置时的默认值（供设置页与 agent 循环兜底）。key 由调用方补。 */
    fun defaultConfig(key: String? = apiKey()): LlmConfig =
        LlmConfig(
            baseUrl = DEFAULT_BASE_URL,
            apiKey = key.orEmpty(),
            model = DEFAULT_MODEL,
            thinkingLevel = DEFAULT_THINKING_LEVEL,
            contextWindow = windowFor(DEFAULT_MODEL),
        )

    /**
     * 读思考强度，并把老版本的布尔开关**迁移**成强度。
     *
     * 为什么迁移而不是直接丢弃：老用户原来设的是"关"，升级后如果默认回落成"中"，
     * 就等于**背着他把花费翻倍**（实测开/关 completion_tokens 24→6）——这比"设置丢了"更糟。
     * 迁移只写一次（写完就把新键存上），之后都走新键。
     */
    private fun readThinkingLevel(): ThinkingLevel {
        prefs.getString(KEY_THINKING_LEVEL, null)?.let { return ThinkingLevel.fromKey(it) }
        val legacy = if (prefs.contains(KEY_THINKING)) prefs.getBoolean(KEY_THINKING, false) else null
        val level = ThinkingLevel.migrate(legacy)
        prefs.edit().putString(KEY_THINKING_LEVEL, level.key).apply()
        return level
    }

    // --------------------------------------------------- 模型候选（顶栏切换用）

    /**
     * 记住上次「拉取模型列表」的结果，让顶栏的模型切换**不用每次重新拉**。
     * 拉取动作是用户主动触发的，候选过期（模型下线）时切换会报错，错误提示已经很明确，
     * 所以这里不做过期校验——多存一份候选的价值远大于那点风险。
     */
    fun saveModelCandidates(models: List<String>) {
        prefs.edit().putString(KEY_MODEL_CANDIDATES, models.joinToString("\n").take(MAX_CANDIDATES_CHARS)).apply()
    }

    fun modelCandidates(): List<String> =
        prefs.getString(KEY_MODEL_CANDIDATES, "").orEmpty()
            .split("\n").map { it.trim() }.filter { it.isNotEmpty() }.distinct()

    // ------------------------------------------------------------- 工具开关

    /**
     * 用户启用的工具名集合。
     *
     * 关键区分：**prefs 里没有这个 key** = 用户从没配过 → 默认全开；
     * **有这个 key 但是空串** = 用户主动把 5 个开关全关了 → 必须返回空集。
     * （曾经这里用 `ifEmpty { 默认全开 }`，会把「全关」这件事悄悄变成「全开」。）
     */
    fun enabledTools(role: AiRole? = null): Set<String> {
        if (!prefs.contains(KEY_TOOLS)) {
            markToolsSeen()
            // 首装：按**角色**给默认值 —— 派单员全开，其余角色除写工具外全开。
            // （2026-09-20 用户：「派单员所有 AI 功能全都是默认开启」。）
            return defaultEnabledTools(role)
        }
        val saved = splitNames(prefs.getString(KEY_TOOLS, ""))
        // ⚠️ 「上次保存之后**新加**的工具」要按默认开处理。
        // 不做这一步的后果是静默的：老用户的 prefs 里没有新工具的名字，
        // 下面的 intersect 会把它筛掉 → 升级后新功能**装了却没有任何反应**，
        // 而用户完全不知道为什么（实测踩过：记忆功能就这样哑了一次）。
        // 判据用"用户见过哪些工具"，而不是"当前集合里有没有"——后者区分不了
        // "新增的" 和 "用户主动关掉的"。
        //
        // ⚠️ [OPT_IN_TOOLS] 是这条规矩的**唯一例外**，而且必须是例外：
        // 「新增默认开」对只读工具是对的（多了个查询能力，最坏是答得不全），
        // 对**能改业务数据**的工具是错的（老用户升级后不该凭空多出一个会记账的 AI）。
        // 这一条一旦漏掉，`preview_write` 会绕过设置页开关直接可用——
        // 静默、无报错、也没有任何界面提示，正是最坏的那种 bug。
        val seen = splitNames(prefs.getString(KEY_TOOLS_SEEN, ""))
        val brandNew = DEFAULT_ENABLED_TOOLS - seen - optInExclusion(role)
        val effective = (saved + brandNew).intersect(DEFAULT_ENABLED_TOOLS)
        markToolsSeen()
        return effective
    }

    private fun splitNames(raw: String?): Set<String> =
        raw.orEmpty().split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()

    /** 记下"当前版本有哪些工具"——下次判断"哪些是新加的"就靠它。 */
    private fun markToolsSeen() {
        prefs.edit().putString(KEY_TOOLS_SEEN, DEFAULT_ENABLED_TOOLS.joinToString(",")).apply()
    }

    fun saveEnabledTools(names: Set<String>) {
        // 保存时同步刷新"见过的清单"：用户既然在设置页看到了全部开关，
        // 那"没勾的"就是他主动关的，不该在下次被当成新增工具又打开。
        prefs.edit()
            .putString(KEY_TOOLS, names.joinToString(","))
            .putString(KEY_TOOLS_SEEN, DEFAULT_ENABLED_TOOLS.joinToString(","))
            .apply()
    }

    // --------------------------------------------- 通用读工具：允许读哪些模块

    /**
     * 允许 AI 读的模块（`read_data` 工具的二级开关，见 [AiReadCatalog.modules]）。
     *
     * 与 [enabledTools] 同一套约定：**没有这个键** = 用户从没配过 → 默认全开；
     * **有键但是空串** = 用户主动全关 → 必须返回空集（不能悄悄变回全开）。
     */
    fun enabledReadModules(): Set<String> {
        val all = AiReadCatalog.modules().toSet()
        if (!prefs.contains(KEY_READ_MODULES)) return all
        val raw = prefs.getString(KEY_READ_MODULES, "").orEmpty()
        val set = raw.split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()
        // 过滤掉不认识的模块名（模型/后端改过名），但允许合法地「一个都不开」
        return set.intersect(all)
    }

    fun saveEnabledReadModules(names: Set<String>) {
        prefs.edit().putString(KEY_READ_MODULES, names.joinToString(",")).apply()
    }

    // ------------------------------------------------------------- 长期记忆

    /**
     * 是否启用「长期记忆」（把用户教过的事实注入提示词 + 允许 `remember` 工具写进去）。**默认开**。
     *
     * ### 为什么必须有这个开关（不是可有可无的礼貌）
     * 记忆会**改变模型的默认行为**——它下次会直接用"城东水果批发月结"这个结论，
     * 而不再问一遍。凡是会改变行为的功能，用户都必须能关掉它；
     * 而比开关更重要的是**能看见内容**（设置页把每条记忆摊开、可逐条删），
     * 只给一个总开关、不给内容，等于让用户闭眼授权（这条纪律见 `AiHabits` 的同类设计）。
     *
     * 默认开：它全程在本机、且只有用户主动说"记住"才会写进去，收益直接、风险可控。
     */
    fun memoryEnabled(): Boolean = prefs.getBoolean(KEY_MEMORY_ENABLED, true)

    fun setMemoryEnabled(on: Boolean) {
        prefs.edit().putBoolean(KEY_MEMORY_ENABLED, on).apply()
    }

    /**
     * **允许 AI 查看成本与毛利吗**（默认 `false`）。
     *
     * 成本价一旦进模型上下文，它就出现在聊天记录里、可能被截图外发 ——
     * 所以这是**用户的数据外发决定**，不该由一次 App 升级替他做（所以默认关）。
     * 用户 2026-09-19 要求「我们改过、新加的功能 AI 都要能操作」，成本这块就靠这个开关放行：
     * 打开之后 AI 能读成本/毛利、查成本价历史、申请改成本价与录进货价。
     *
     * ⚠️ 与 [OPT_IN_TOOLS] 同一套纪律：默认关、用户主动开；关着的时候
     * `AiRowShaper.isHiddenField` 会把 `cost*` / `profit` / `margin` 全部拦掉。
     */
    fun costVisible(): Boolean = prefs.getBoolean(KEY_COST_VISIBLE, false)

    fun setCostVisible(on: Boolean) {
        prefs.edit().putBoolean(KEY_COST_VISIBLE, on).apply()
    }

    // ------------------------------------------------- 上下文窗口（自动，不给用户选）

    /**
     * 这个模型该用多大的上下文窗口。
     *
     * 优先级：**撞过上限学到的真实结论** > **按模型名推断** > [AiContext.FALLBACK_WINDOW]。
     *
     * 为什么把"学到的"单独存一份而不是覆盖推断值：用户换模型时（顶栏切换）要立刻用新模型的能力，
     * 而不是把上一个模型学到的 32k 带过去——那会让新模型平白少用一大截上下文。
     */
    fun windowFor(model: String): Int {
        val m = model.trim()
        if (m.isEmpty()) return AiContext.FALLBACK_WINDOW
        learnedWindows()[m]?.let { return it }
        return AiContext.inferWindow(m)
    }

    /**
     * 记下这个模型的**实测**窗口（来源只有两个，都是真实往返里得来的，不是猜的）：
     * - 撞上限时端点自己报的上限 / 按实证值收缩后的值（[AiContext.shrinkOnOverflow]）；
     * - 成功发出过更大的量级后按证据放大（[AiContext.growOnEvidence]）。
     *
     * 存下来而不是每次现算：这两个结论都是**花了一次真实请求换来的**，丢了就得再撞一次。
     */
    fun rememberWindow(model: String, window: Int) {
        val m = model.trim()
        if (m.isEmpty() || window <= 0) return
        if (window == AiContext.inferWindow(m) && learnedWindows()[m] == null) return
        val map = learnedWindows().toMutableMap()
        map[m] = window
        prefs.edit()
            .putString(
                KEY_LEARNED_WINDOWS,
                map.entries.take(MAX_LEARNED_WINDOWS).joinToString("\n") { "${it.key}\t${it.value}" },
            )
            .apply()
    }

    /** 忘掉学到的结论（设置页「重新识别」用），回到按模型名推断。 */
    fun forgetWindow(model: String) {
        val m = model.trim()
        val map = learnedWindows().toMutableMap()
        if (map.remove(m) == null) return
        prefs.edit()
            .putString(KEY_LEARNED_WINDOWS, map.entries.joinToString("\n") { "${it.key}\t${it.value}" })
            .apply()
    }

    /** 是否已经为这个模型学到过真实窗口（设置页据此说明"是按模型名猜的还是实测的"）。 */
    fun learnedWindow(model: String): Int? = learnedWindows()[model.trim()]

    private fun learnedWindows(): Map<String, Int> =
        prefs.getString(KEY_LEARNED_WINDOWS, "").orEmpty()
            .split("\n")
            .mapNotNull { line ->
                val i = line.indexOf('\t')
                if (i <= 0) return@mapNotNull null
                val name = line.substring(0, i).trim()
                val v = line.substring(i + 1).trim().toIntOrNull() ?: return@mapNotNull null
                if (name.isEmpty() || v <= 0) null else name to v
            }
            .toMap()

    // ------------------------------------------------- 「不支持 thinking 参数」的能力记忆

    /**
     * 该 Base URL 是否已被确认**不接受 `thinking` 参数**（豆包/千问等第三方兼容端点常见）。
     *
     * 为什么要**记下来**而不是每次都试：本 App 刻意永远显式下发 `thinking`（理由见
     * [LlmClient.buildChatRequest]），遇到不认这个字段的端点会 400。
     * 靠"报错→去掉参数重试"能救回来，但**每次提问都要多打一次注定失败的请求**——
     * 既慢又可能被计费。所以第一次发现后就记住，之后直接不发这个字段。
     *
     * 键用**归一化后的完整地址**（不是域名）：同一个域名下不同路径可能是不同的服务/代理，
     * 一个路径不认不代表另一个也不认。
     */
    fun thinkingUnsupported(baseUrl: String): Boolean {
        val key = normalizeBase(baseUrl) ?: return false
        return unsupportedHosts().contains(key)
    }

    /** 记下「这个地址不接受 thinking 参数」。 */
    fun markThinkingUnsupported(baseUrl: String) {
        val key = normalizeBase(baseUrl) ?: return
        val set = unsupportedHosts() + key
        // 上限保护：正常用户不会填几十个地址；真填了也只留最近 12 个，避免 prefs 无限增长
        prefs.edit().putString(KEY_NO_THINKING, set.toList().takeLast(MAX_UNSUPPORTED).joinToString(",")).apply()
    }

    /** 清掉能力记忆（用户在设置页点「重新检测」时用）。 */
    fun clearThinkingUnsupported(baseUrl: String) {
        val key = normalizeBase(baseUrl) ?: return
        val set = unsupportedHosts() - key
        prefs.edit().putString(KEY_NO_THINKING, set.joinToString(",")).apply()
    }

    private fun unsupportedHosts(): Set<String> = hostSet(KEY_NO_THINKING)

    /** 读一个「地址集合」型的 prefs 键（存的是 `a,b,c` 形状）。 */
    private fun hostSet(key: String): Set<String> =
        prefs.getString(key, "").orEmpty()
            .split(",").map { it.trim() }.filter { it.isNotEmpty() }.toSet()

    // ------------------------------------------- 「不支持 stream_options」的能力记忆

    /**
     * 该 Base URL 是否已被确认**不接受 `stream_options` 参数**。
     *
     * ### 为什么与 `thinking` 是同一类问题
     * 开了流式以后，**端点默认不回 `usage`**（DeepSeek 实测），而本项目的"到 40% 自动压缩"
     * 建立在服务端真实回报的 `prompt_tokens` 上（见 [AiContext]）。所以要显式发
     * `stream_options:{"include_usage":true}` 去要它。但它是**OpenAI 协议的自选字段**，
     * 和 `thinking` 一样，总有兼容端点不认 → 400。
     *
     * 处理方式也与 `thinking` 完全对称：先自动去掉重试一次救回来，然后把结果记在这里，
     * 之后**直接不发**——否则每次提问都要多打一次注定失败的请求，既慢又可能被计费。
     *
     * 键同样用**归一化后的完整地址**（理由见 [thinkingUnsupported]）。
     */
    fun streamOptionsUnsupported(baseUrl: String): Boolean {
        val key = normalizeBase(baseUrl) ?: return false
        return hostSet(KEY_NO_STREAM_OPTIONS).contains(key)
    }

    /** 记下「这个地址不接受 stream_options」。 */
    fun markStreamOptionsUnsupported(baseUrl: String) {
        val key = normalizeBase(baseUrl) ?: return
        val set = hostSet(KEY_NO_STREAM_OPTIONS) + key
        prefs.edit()
            .putString(KEY_NO_STREAM_OPTIONS, set.toList().takeLast(MAX_UNSUPPORTED).joinToString(","))
            .apply()
    }

    /** 清掉该能力记忆（与 [clearThinkingUnsupported] 一起用于设置页的「重新检测」）。 */
    fun clearStreamOptionsUnsupported(baseUrl: String) {
        val key = normalizeBase(baseUrl) ?: return
        val set = hostSet(KEY_NO_STREAM_OPTIONS) - key
        prefs.edit().putString(KEY_NO_STREAM_OPTIONS, set.joinToString(",")).apply()
    }

    /** 归一化：去空白、去末尾斜杠、小写。空地址返回 null（不记也不查）。 */
    private fun normalizeBase(baseUrl: String): String? =
        baseUrl.trim().trimEnd('/').lowercase().takeIf { it.isNotEmpty() }

    // ------------------------------------------------------------- Keystore

    private fun secretKey(): SecretKey {
        val ks = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (ks.getEntry(ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                // 用户不需要指纹/锁屏才能调用 AI（否则后台跑 agent 会失败）
                .setUserAuthenticationRequired(false)
                .build(),
        )
        return generator.generateKey()
    }

    private fun base64(bytes: ByteArray): String = Base64.getEncoder().encodeToString(bytes)
    private fun unBase64(s: String): ByteArray = Base64.getDecoder().decode(s)

    companion object {
        /** 默认 Base URL（用户可改）。DeepSeek 官方 OpenAI 兼容入口。 */
        const val DEFAULT_BASE_URL = "https://api.deepseek.com"

        /**
         * 默认模型名（**只是默认值**，用户可在设置页改，也可以点「拉取模型列表」从
         * `GET {baseUrl}/models` 拉到的候选里点选）。
         *
         * 为什么是 `deepseek-flash`：实测这把 key 上 `deepseek-chat` **根本不可用**（会 404/400），
         * 而 `GET {baseUrl}/models` 实际返回的是 `deepseek-flash`、`deepseek-v4-pro`。
         * 猜一个不存在的模型名会让用户第一句话就直接失败，所以默认值取实测可用的这个。
         */
        const val DEFAULT_MODEL = "deepseek-flash"

        /**
         * 思考强度默认值：**中**（= [ThinkingLevel.MEDIUM]）。
         *
         * 取舍（实测：开/关 completion_tokens 24→6，**约一倍 token 成本**）：
         * - 这个助手的活是「回答派单员关于订单/司机/库存/账目的问题」，答案要落到具体数字、
         *   日期区间、筛选条件上。少想一步就可能算错时间段或漏条件，
         *   而**答错的代价（按错数字去派单/对账）远大于多花的那点 token**。
         * - 但又不必默认顶格：用户嫌不准可以调「高」，嫌贵可以调「低/关」，默认落在中间。
         *
         * ⚠️ 升级影响：老用户 prefs 里的布尔开关会被 [readThinkingLevel] 迁移
         * （true→中 / false→关），不会出现"背着他把花费翻倍"。
         */
        val DEFAULT_THINKING_LEVEL: ThinkingLevel = ThinkingLevel.DEFAULT

        /**
         * prefs 名的**前缀**——真正的名字是它 + 用户分区后缀（见类注释）。
         * 直接用固定串就等于"大家共用一份凭据"，那是 P0-6。
         */
        private const val PREFS_NAME = "sorders_ai_prefs"
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val ALIAS = "sorders_ai_key_v1"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val GCM_TAG_BITS = 128

        private const val KEY_CIPHER = "api_key_cipher"
        private const val KEY_IV = "api_key_iv"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_MODEL = "model"
        private const val KEY_TOOLS = "enabled_tools"

        /** 通用读工具允许的模块（见 [enabledReadModules]）。 */
        private const val KEY_READ_MODULES = "enabled_read_modules"

        /** 思考强度（字符串键，明文存；不是机密）。 */
        private const val KEY_THINKING_LEVEL = "thinking_level"

        /**
         * 撞过「上下文超长」之后学到的真实窗口（`模型名\t窗口` 换行分隔）。
         *
         * ⚠️ 老版本有一个 `context_window`（用户手选的档位），v3.4 起**不再使用**：
         * 用户明确说「不要让用户选择那么多，直接给最高的」。留着它只会造出
         * "prefs 里有一个谁都不看的数"这种烂账，所以键名换成新的，老值自然失效。
         */
        private const val KEY_LEARNED_WINDOWS = "learned_windows"

        /** 学到的窗口最多记几个模型（够用即可，防止无限增长）。 */
        private const val MAX_LEARNED_WINDOWS = 20

        /** 上次拉到的模型候选（换行分隔）。 */
        private const val KEY_MODEL_CANDIDATES = "model_candidates"

        /** 候选清单的存储上限（防止某个端点返回几千个模型把 prefs 撑爆）。 */
        private const val MAX_CANDIDATES_CHARS = 4000

        /** ⚠️ 老版本的布尔思考开关键。**只用于迁移，不要再往里写**（见 [readThinkingLevel]）。 */
        private const val KEY_THINKING = "thinking"

        /** 「不接受 thinking 参数」的地址清单（明文存；不是机密，只是能力缓存）。 */
        private const val KEY_NO_THINKING = "no_thinking_hosts"

        /** 「不接受 stream_options 参数」的地址清单（同上；流式拿 usage 要用它）。 */
        private const val KEY_NO_STREAM_OPTIONS = "no_stream_options_hosts"

        /** 长期记忆总开关（默认开，见 [memoryEnabled]）。 */
        private const val KEY_MEMORY_ENABLED = "memory_enabled"
        /** 「允许 AI 查看成本与毛利」——默认关，见 [costVisible]。 */
        private const val KEY_COST_VISIBLE = "cost_visible"

        /**
         * 「用户见过哪些工具」的清单——用来判断**上次保存之后新加了哪些工具**。
         * 新增工具必须按"默认开"处理，否则老用户升级后新功能会静默不可用（见 [enabledTools]）。
         */
        private const val KEY_TOOLS_SEEN = "tools_seen"

        /** 能力缓存最多记几个地址。 */
        private const val MAX_UNSUPPORTED = 12

        /**
         * 默认全开的工具。
         *
         * **6 个只读工具**：没有任何写操作，默认全开是安全的。
         * 外加 **`remember`**：它只写本机记忆文件（App 私有目录、用户能逐条看见/改/删、
         * 不出手机），不碰任何业务数据，所以同样可以默认开
         * （理由与红线见 [AiTools.REMEMBER] 与 `_check_ai_guardrails.py` 的 §2）。
         *
         * ⚠️ **往这里加工具必须同时确认两件事**：
         * ① 它不改业务数据（否则要走风险分级 + 两段式确认，不能靠"默认开"溜进来）；
         * ② 红线检查 §2 的 `ALLOWED_TOOLS` / `LOCAL_ONLY_TOOLS` 要一起更新，否则构建检查会红。
         */
        val DEFAULT_ENABLED_TOOLS: Set<String> = linkedSetOf(
            AiTools.SEARCH_SHIPPER,
            AiTools.INVENTORY_ALERTS,
            AiTools.DRIVER_PERFORMANCE,
            AiTools.SHIPPER_PERFORMANCE,
            AiTools.READ_DATA,
            AiTools.EXPORT_SHEET,
            AiTools.REMEMBER,
            AiTools.PREVIEW_WRITE,
        )

        /**
         * **必须由用户主动打开**的工具（即使它是"新增的工具"，也不自动开）。
         *
         * ### 为什么需要这么一个集合
         * [enabledTools] 的规矩是"新增工具默认开"——那条规矩是为了修
         * "记忆功能装了却没有任何反应"那个 bug（老用户的 prefs 里没有新工具名，
         * 一 intersect 就被筛掉了）。但那条规矩对**能改业务数据**的工具是错的：
         * 老用户升级后不该突然多出一个"能替你记账"的能力，哪怕它会弹确认。
         *
         * ### 它必须同时在 [DEFAULT_ENABLED_TOOLS] 里
         * 这两个集合的分工容易搞反，写下来免得下次又踩：
         * - [DEFAULT_ENABLED_TOOLS] 是**白名单**：不在里面的工具，连"被打开"的资格都没有
         *   （`enabledTools()` 最后那个 `intersect` 会把它筛掉，用户按了开关也不生效）。
         * - [OPT_IN_TOOLS] 只决定**默认值是开还是关**：首装和"新出现的工具"都不自动开，
         *   但用户在设置页打开后能存下来、下次仍然生效。
         */
        val OPT_IN_TOOLS: Set<String> = setOf(AiTools.PREVIEW_WRITE)

        /**
         * 这个角色**首次使用**时默认开哪些工具（用户 2026-09-20 的决定）。
         *
         * 用户原话：「**派单员所有 AI 功能全都是默认开启**」。
         * 所以派单员 = **全开**（含 [OPT_IN_TOOLS] 里的写工具）；其余角色仍按老规矩
         * （除写工具外全开）。
         *
         * ### 为什么派单员可以默认全开（这不是把安全闸拆了）
         * - 他本来就是**唯一**有写权限的角色：货主的动作白名单是
         *   `AiWrites.SHIPPER_ACTIONS`（fail-closed），司机端连 AI 入口都没有；
         * - "能改数据"这条路上还有**确认卡**：`preview_write` 只是**申请**，
         *   真正落库要他本人在卡上点一下（`AiWriteService.execute` 的唯一调用点就是那个按钮）；
         * - 开关仍然在设置页里，随时能关；关掉之后这一层照旧立刻生效。
         *
         * 判据写成**纯函数**是为了能被单测钉住（`AiToolsTest`）——
         * 以前这段逻辑埋在 `enabledTools()` 里，只有真机能验。
         */
        fun defaultEnabledTools(role: AiRole?): Set<String> =
            if (role == AiRole.DISPATCHER) DEFAULT_ENABLED_TOOLS
            else DEFAULT_ENABLED_TOOLS - OPT_IN_TOOLS

        /**
         * 「新增的工具」自动开时，**要不要把它排除**。
         *
         * 非派单员：写工具不自动开（老用户升级后不该凭空多出一个会记账的 AI）。
         * 派单员：什么都不排除 —— 用户要的就是"派单员所有 AI 功能全都默认开启"，
         * 新加的写动作对他也应该装上就能用（仍然要过确认卡）。
         */
        fun optInExclusion(role: AiRole?): Set<String> =
            if (role == AiRole.DISPATCHER) emptySet() else OPT_IN_TOOLS
    }
}
