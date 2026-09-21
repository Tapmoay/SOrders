package com.tapmoay.sorders.ui.ai

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.ai.AiContainer
import com.tapmoay.sorders.ai.AiContext
import com.tapmoay.sorders.ai.AiKeyStore
import com.tapmoay.sorders.ai.AiMemories
import com.tapmoay.sorders.ai.AiMemoryItem
import com.tapmoay.sorders.ai.AiProviders
import com.tapmoay.sorders.ai.AiReads
import com.tapmoay.sorders.ai.AiRolePrompt
import com.tapmoay.sorders.ai.AiTools
import com.tapmoay.sorders.ai.LlmClient
import com.tapmoay.sorders.ai.ThinkingLevel
import com.tapmoay.sorders.ui.common.AppTopBar
import com.tapmoay.sorders.ui.common.DangerConfirmDialog
import com.tapmoay.sorders.ui.common.OneShotSnackbar
import com.tapmoay.sorders.ui.common.PrimaryActionButton
import com.tapmoay.sorders.ui.common.SectionCard
import com.tapmoay.sorders.ui.common.SegmentedPicker
import com.tapmoay.sorders.ui.common.appViewModel
import com.tapmoay.sorders.ui.theme.AiBlue
import com.tapmoay.sorders.ui.theme.Success

/**
 * 「派单员 AI 助手」设置页。
 *
 * 只做四件事：填模型配置（Base URL / 模型名 / API Key / 思考开关）、拉取模型列表、
 * 测连接、开关工具（6 个只读 + 1 个「记住」），外加**长期记忆的查看/修改/删除**。
 * 路由与入口由聊天页那边加（本文件不碰 ui/nav）。
 *
 * ⚠️ 无任何「仅 debug 可用」的写法：本页面 release 构建同样正常工作。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AiSettingsScreen(
    ai: AiContainer,
    onBack: () -> Unit,
) {
    val vm: AiSettingsViewModel = appViewModel { AiSettingsViewModel(ai) }
    val snackbar = remember { SnackbarHostState() }
    val accent = Color(AiBlue)

    // 能力开关（查询类 / 操作类 / 可读的列表）收在底部抽屉里，见文件中间那段注释。
    var showCapabilitySheet by remember { mutableStateOf(false) }
    if (showCapabilitySheet) {
        CapabilitySheet(
            vm = vm,
            onDismiss = { showCapabilitySheet = false },
        )
    }

    OneShotSnackbar(snackbar, vm.actionResult, onConsumed = { vm.actionResult = null })

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            AppTopBar(
                title = "AI 助手设置",
                subtitle = "模型配置与工具开关",
                onBack = onBack,
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp)
                .padding(bottom = 32.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // ---------------- 隐私说明（用户最关心的一件事，放最上面） ----------------
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = MaterialTheme.shapes.medium,
                color = accent.copy(alpha = 0.08f),
            ) {
                Row(Modifier.padding(14.dp)) {
                    Icon(Icons.Default.Lock, contentDescription = null, tint = accent)
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Text(
                            "API Key 只保存在你这台手机上（系统级加密），不会上传到服务器；模型费用由你的 key 承担。",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Spacer(Modifier.height(6.dp))
                        // ⚠️ 这段是**能力声明**，不是宣传语。写错了的后果是双面的：
                        // 写宽了，用户以为 AI 能下单/派单，试一次就失去信任；
                        // 写窄了（v3.7 之前那句「它不能下单、派单、改价或删数据」就是），
                        // 模型读到会跟着一起否认自己的能力——实测已经踩过一次（见 §19.6）。
                        // 所以它**从代码里生成**（AiRolePrompt.settingsSummary），
                        // 和提示词同源；手写的那一版已经和真实能力走散过一次
                        // （批量调价 v3.21 就上线了，这页却还写着「改价做不了」）。
                        Text(
                            AiRolePrompt.settingsSummary(
                                // ⚠️ 必须传 **actor**（角色 + 是不是批发商货主）：这段是能力声明，
                                //    而两个货主的能力不一样（批发商多一本自己的账）。
                                actor = ai.currentActor,
                                readModules = vm.readModules.filter { it.enabled }.map { it.module }.toSet(),
                            ),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }

            // ---------------- 模型配置 ----------------
            SectionCard {
                Text("模型配置", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(4.dp))
                Text(
                    "先点一个服务商，地址会自动填好并去拉模型列表；拉到之后点一个模型名，再保存。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(8.dp))

                // 厂商预设：把最容易填错的一格（地址）变成点一下。
                // 模型名刻意不由预设填（会随时间/账号权限变，猜错就 400），改为拉真实候选。
                Row(
                    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    AiProviders.ALL.forEach { p ->
                        FilterChip(
                            selected = p.matches(vm.baseUrl),
                            onClick = { vm.applyPreset(p) },
                            label = { Text(p.label, fontSize = 16.sp) },
                            leadingIcon = if (p.matches(vm.baseUrl)) {
                                { Icon(Icons.Default.Check, contentDescription = null, modifier = Modifier.size(18.dp)) }
                            } else {
                                null
                            },
                        )
                    }
                }

                // 命中预设 → 显示该厂商最容易踩的坑；没命中 → 说明是自定义地址
                val provider = vm.currentProvider()
                Spacer(Modifier.height(4.dp))
                Text(
                    provider?.note
                        ?: "自定义地址：请确认它是 OpenAI 兼容的 /chat/completions 接口。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    AiProviders.TOOL_CALLING_REQUIREMENT,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))

                OutlinedTextField(
                    value = vm.baseUrl,
                    onValueChange = { vm.onBaseUrlChange(it) },
                    label = { Text("Base URL") },
                    supportingText = { Text("OpenAI 兼容接口地址，例如 https://api.deepseek.com") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))

                OutlinedTextField(
                    value = vm.model,
                    onValueChange = { vm.model = it },
                    label = { Text("模型名") },
                    supportingText = {
                        Text("例如 ${AiKeyStore.DEFAULT_MODEL}；不确定就点「拉取模型列表」直接选。")
                    },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(6.dp))

                // 「拉取模型列表」：按钮放在输入框**正下方**而不是同一行——
                // 窄屏（360dp）+ 大字号下，同一行会把输入框挤到只剩一半宽，模型名一长就看不见了。
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedButton(
                        onClick = { vm.fetchModels() },
                        enabled = !vm.fetchingModels,
                    ) {
                        if (vm.fetchingModels) {
                            CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(8.dp))
                            Text("拉取中…")
                        } else {
                            Icon(Icons.Default.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("拉取模型列表")
                        }
                    }
                    if (vm.availableModels.isNotEmpty()) {
                        Spacer(Modifier.width(4.dp))
                        TextButton(onClick = { vm.clearModelCandidates() }) { Text("收起") }
                    }
                }

                // 候选列表：点一项即填入上面的模型名。
                // 刻意**不用 ExposedDropdownMenuBox**——它得锚在输入框上、浮层会盖住下面的
                // API Key/开关，窄屏和大字号下很难点；这里就是一个老老实实的可滚动列表。
                if (vm.availableModels.isNotEmpty()) {
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "共 ${vm.availableModels.size} 个模型，点一项即填入上面的输入框（记得再点「保存」）",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(4.dp))
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = MaterialTheme.shapes.small,
                        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
                    ) {
                        Column(
                            Modifier
                                .heightIn(max = 200.dp)
                                .verticalScroll(rememberScrollState()),
                        ) {
                            vm.availableModels.forEachIndexed { index, name ->
                                if (index > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                                val selected = name == vm.model.trim()
                                Row(
                                    Modifier
                                        .fillMaxWidth()
                                        .clickable { vm.pickModel(name) }
                                        .padding(horizontal = 12.dp, vertical = 12.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        name,
                                        style = MaterialTheme.typography.bodyLarge,
                                        fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                                        color = if (selected) accent else MaterialTheme.colorScheme.onSurface,
                                        modifier = Modifier.weight(1f),
                                    )
                                    if (selected) {
                                        Icon(
                                            Icons.Default.Check,
                                            contentDescription = "当前填的就是这个",
                                            tint = accent,
                                            modifier = Modifier.size(18.dp),
                                        )
                                    }
                                }
                            }
                        }
                    }
                }

                // 拉取失败：红底人话提示。**不挡路**——模型名本来就能手输，页面照常能用。
                vm.modelsError?.let { msg ->
                    Spacer(Modifier.height(8.dp))
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = MaterialTheme.shapes.small,
                        color = MaterialTheme.colorScheme.error.copy(alpha = 0.10f),
                    ) {
                        Text(
                            msg,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.padding(10.dp),
                        )
                    }
                }
                Spacer(Modifier.height(10.dp))

                OutlinedTextField(
                    value = vm.apiKeyInput,
                    onValueChange = { vm.apiKeyInput = it },
                    label = { Text("API Key") },
                    singleLine = true,
                    visualTransformation = if (vm.showKey) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    trailingIcon = {
                        IconButton(onClick = { vm.showKey = !vm.showKey }) {
                            Icon(
                                if (vm.showKey) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                contentDescription = if (vm.showKey) "隐藏" else "显示",
                            )
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
                if (vm.hasStoredKey) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        if (vm.usingDefaultKey) {
                            // 如实说清这把 key 是哪来的（用户 2026-09-21：测试账号默认就跑）。
                            // 不写的话他会以为是自己配过的；而且清掉之后 App 下次自检还会拿回来。
                            "正在使用「测试账号默认 Key」（服务端下发，不是你自己填的）。" +
                                "清掉它下次进这一页会自动拿回来；填上你自己的 Key 就会改用自己的。"
                        } else {
                            "已保存一个 Key（加密存在本机）。直接改上面的内容再点保存即可替换。"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                Spacer(Modifier.height(12.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                // 思考强度：关 / 低 / 中 / 高（原来是一个开关，现在分档）
                Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                    Text("思考强度", style = MaterialTheme.typography.bodyLarge)
                    Text(
                        "关：直接答，最快最省（实测同一问题 token 约为开的一半）；" +
                            "低/中/高：越往上越想得全，也越慢越贵。默认「中」。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(8.dp))
                    SegmentedPicker(
                        labels = ThinkingLevel.entries.map { it.label },
                        selected = ThinkingLevel.entries.indexOf(vm.thinkingLevel).coerceAtLeast(0),
                        onSelect = { i -> vm.thinkingLevel = ThinkingLevel.entries[i] },
                        // 与聊天页的切换面板同色：同一个 App 里同一个控件的强调色不能两样
                        accent = Color(AiBlue),
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        vm.thinkingLevel.hint,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    // 如实标注：分级在部分端点上会被静默忽略（本项目实测过）
                    Text(
                        "注：部分模型只支持「开/关」、会把强度分档当没看见；「关」是确定生效的。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                // 上下文窗口：**没有选项**，只有一句说明（用户口径：不要让用户选那么多）
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                    Text("上下文", style = MaterialTheme.typography.bodyLarge)
                    Text(
                        // 用户 2026-09-17：「能用一两句话解决的事情就不要说那么多话。」
                        // 保留的**必要信息**只有两个：当前按多大算、什么时候会压缩。
                        // 原来还写了「原对话仍留在历史里」——那句是安慰，不是信息，删掉。
                        "按模型上限自动使用（当前 ${AiContext.windowLabel(vm.contextWindow)}）；" +
                            "用到 ${(AiContext.COMPACT_AT * 100).toInt()}% 会把较早的对话压成摘要。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        // 「这个数是猜的还是实测的」是**用户要判断可信度时唯一需要的**，必须留。
                        if (vm.learnedWindow) {
                            "这个上限是实测出来的（撞过一次超长，已自动调准并记住）。"
                        } else {
                            "上限是接口不返回的，这里按模型名查表；装不下会自动缩小重试并记住。"
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    TextButton(
                        onClick = { vm.relearnWindow() },
                        contentPadding = PaddingValues(horizontal = 0.dp),
                    ) {
                        Text("重新按模型名识别一次", fontSize = 15.sp)
                    }
                }

                // 该地址不认 thinking 参数：必须解释清楚"已自动跳过"，否则用户会以为开关坏了
                if (vm.thinkingUnsupported) {
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = MaterialTheme.shapes.small,
                        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
                    ) {
                        Column(Modifier.padding(10.dp)) {
                            Text(
                                LlmClient.THINKING_UNSUPPORTED_NOTE,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            TextButton(
                                onClick = { vm.recheckThinkingSupport() },
                                contentPadding = PaddingValues(horizontal = 0.dp),
                            ) {
                                Text("换地址后重新检测", fontSize = 15.sp)
                            }
                        }
                    }
                }

                Spacer(Modifier.height(10.dp))

                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedButton(
                        onClick = { vm.testConnection() },
                        enabled = !vm.testing,
                        modifier = Modifier.height(56.dp),
                    ) {
                        if (vm.testing) {
                            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                            Spacer(Modifier.width(8.dp))
                            Text("测试中…")
                        } else {
                            Icon(Icons.Default.Build, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("测试连接")
                        }
                    }
                    Spacer(Modifier.width(10.dp))
                    PrimaryActionButton(
                        text = "保存",
                        icon = Icons.Default.Save,
                        onClick = { vm.save() },
                        containerColor = accent,
                        modifier = Modifier.weight(1f),
                    )
                }

                // 测试结果：成功绿 / 失败红 + 技术细节（区分「key 错」和「网络不通」）
                vm.testMessage?.let { msg ->
                    Spacer(Modifier.height(12.dp))
                    Surface(
                        modifier = Modifier.fillMaxWidth(),
                        shape = MaterialTheme.shapes.small,
                        color = (if (vm.testOk) Success else MaterialTheme.colorScheme.error).copy(alpha = 0.10f),
                    ) {
                        Text(
                            msg,
                            style = MaterialTheme.typography.bodySmall,
                            color = if (vm.testOk) Success else MaterialTheme.colorScheme.error,
                            modifier = Modifier.padding(10.dp),
                        )
                    }
                }

                vm.error?.let { msg ->
                    Spacer(Modifier.height(8.dp))
                    Text(msg, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                }
            }

            // ---------------- 能力开关：收进一张卡 + 一个底部抽屉（v3.34e） ----------------
            // 用户 2026-09-17：「可读列表、可操作，那些开关太长了，能不能做一个折叠？
            // 但最好不要给它开一个新的页面……侧边抽屉、底部抽屉都可以。」
            //
            // 为什么不是新页面：这一页的开关是**调参**，不是"进入另一个功能"。
            // 跳走再跳回来会丢掉滚动位置和输入框里没保存的内容——这一页恰好有 key / 模型名 /
            // 地址三个未保存输入框。抽屉盖在上面就没有这个问题。
            //
            // 为什么用底部抽屉而不是侧边：开关是**逐个上下扫**的动作，底部抽屉在单手可及范围内，
            // 而且这个 App 里 ModalBottomSheet 已经是成熟做法（商品/地址/库存都在用）。
            SectionCard {
                Row(
                    Modifier.fillMaxWidth().clickable { showCapabilitySheet = true }.padding(vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text("AI 能用的能力", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(2.dp))
                        Text(
                            capabilitySummary(vm),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Icon(
                        Icons.Default.ChevronRight,
                        contentDescription = "打开能力开关",
                        tint = MaterialTheme.colorScheme.outline,
                    )
                }
            }

            // ---------------- 使用习惯（本机学习；要摊开给用户看，不能只给开关） ----------------
            SectionCard {
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text("按我的使用习惯优化", style = MaterialTheme.typography.bodyLarge)
                        Text(
                            // ⚠️ 这里是普通 Text，不渲染 Markdown——写 **粗体** 会把星号原样显示出来
                            // （实测踩过）。要强调就用中文引号。
                            "记下你常问什么、常用哪个时间范围，在「你没说清楚时」当作默认值。" +
                                "全程只存在这台手机上，不上传。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.width(12.dp))
                    Switch(checked = vm.habitEnabled, onCheckedChange = { vm.updateHabitEnabled(it) })
                }
                Spacer(Modifier.height(8.dp))
                // 学到的内容必须看得见：它会改变模型的默认行为，用户有权知道"记住我什么"
                Text(
                    vm.habitSummary ?: "还没有记录。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (vm.habitEnabled && (vm.habitSummary?.contains("已记录") == true)) {
                    TextButton(
                        onClick = { vm.clearHabits() },
                        contentPadding = PaddingValues(horizontal = 0.dp),
                    ) {
                        Icon(Icons.Default.DeleteOutline, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("清除习惯记录", fontSize = 15.sp)
                    }
                }
            }

            // ---------------- 长期记忆（用户教的事实；必须能看、能改、能删） ----------------
            SectionCard {
                Row(
                    Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text("记住我教给你的事", style = MaterialTheme.typography.bodyLarge)
                        Text(
                            // ⚠️ 这里是普通 Text，不渲染 Markdown——别写 **粗体**（会原样显示星号）
                            "你对它说「记住：城东水果批发是月结」，它就存下来，下次问到时直接用。" +
                                "全程只存在这台手机上，不上传。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.width(12.dp))
                    Switch(checked = vm.memoryEnabled, onCheckedChange = { vm.updateMemoryEnabled(it) })
                }
                Spacer(Modifier.height(8.dp))

                // 「允许 AI 查看成本与毛利」——**默认关**。
                // ⚠️ 这一条必须让用户**自己**开：成本价进了模型上下文就会留在聊天记录里、
                //    可能被截图外发，那是数据外发决定，不该由一次 App 升级替他做。
                //    说明里要写清"打开之后能做什么"，否则用户不知道它值不值得开。
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("允许 AI 查看成本与毛利", style = MaterialTheme.typography.bodyLarge)
                        Text(
                            // ⚠️ 这里是普通 Text，不渲染 Markdown——别写 **粗体**（会原样显示星号）
                            "打开后：它才能答「这个商品成本多少、这个月毛利多少、这货成本怎么变的」，" +
                                "也才能帮你改成本价、记进货价。关着时这些数不会发给模型。",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.width(12.dp))
                    Switch(checked = vm.costVisible, onCheckedChange = { vm.updateCostVisible(it) })
                }
                Spacer(Modifier.height(8.dp))

                if (vm.memories.isEmpty()) {
                    Text(
                        "还没有记住任何事。想教它点什么，直接在聊天里说「记住：…」就行。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    // 按主体分组摊开——**这是这个功能能被信任的前提**：
                    // 它会改变模型下次的回答，用户必须看得见它到底记住了什么。
                    AiMemories.grouped(vm.memories).forEach { (subject, facts) ->
                        Text(
                            if (subject == AiMemories.SUBJECT_GLOBAL) "全局偏好" else subject,
                            style = MaterialTheme.typography.bodyMedium,
                            fontWeight = FontWeight.Medium,
                        )
                        facts.sortedByDescending { it.updatedAt }.forEach { m ->
                            MemoryRow(
                                item = m,
                                editing = vm.editingMemoryId == m.id,
                                editingFact = vm.editingFact,
                                onEditingFactChange = { vm.onEditingFactChange(it) },
                                onBeginEdit = { vm.beginEditMemory(m) },
                                onCancelEdit = { vm.cancelEditMemory() },
                                onSaveEdit = { vm.saveEditedMemory() },
                                onDelete = { vm.deleteMemory(m.id) },
                            )
                        }
                    }
                    Spacer(Modifier.height(4.dp))
                    TextButton(
                        onClick = { vm.askClearMemories() },
                        contentPadding = PaddingValues(horizontal = 0.dp),
                    ) {
                        Icon(Icons.Default.DeleteOutline, contentDescription = null, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("清空全部记忆", fontSize = 15.sp)
                    }
                }
            }

            // ---------------- 清除 API Key ----------------
            SectionCard {
                Text("清除 API Key", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(6.dp))
                Text(
                    "清除后 AI 助手立即不可用，模型配置（Base URL / 模型名）保留。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                OutlinedButton(
                    onClick = { vm.askClearKey() },
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
                    modifier = Modifier.fillMaxWidth().height(52.dp),
                ) {
                    Icon(Icons.Default.DeleteOutline, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("清除 API Key")
                }
            }

            Text(
                "提示：填完记得点「保存」（思考强度与上下文窗口也靠保存生效），再点「测试连接」确认 key 可用。" +
                    "测试只发一句「你好」，开启思考时会多花一点额度。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }

    if (vm.showClearConfirm) {
        DangerConfirmDialog(
            title = "清除 API Key？",
            message = "清除后 AI 助手会立刻不可用，直到你重新填入 key。Base URL 和模型名不受影响。",
            confirmText = "清除",
            onConfirm = { vm.confirmClearKey() },
            onDismiss = { vm.showClearConfirm = false },
        )
    }

    if (vm.showClearMemoriesConfirm) {
        DangerConfirmDialog(
            title = "清空全部记忆？",
            message = "助手会忘掉你教过的所有事（共 ${vm.memories.size} 条）。" +
                "这一步不能撤销——如果只想改一条，用每条右边的「改」更稳妥。",
            confirmText = "清空",
            onConfirm = { vm.confirmClearMemories() },
            onDismiss = { vm.showClearMemoriesConfirm = false },
        )
    }
}

/**
 * 一行说清"AI 现在能用什么"，点进去才是那一长串开关。
 *
 * 刻意**只报数量、不列名字**：这一行的作用是让用户知道"这里有一堆可调的东西、当前是开的"，
 * 真要看名字就点进去看（用户原话是嫌开关列表太长，不是嫌它不详细）。
 */
@Composable
private fun capabilitySummary(vm: AiSettingsViewModel): String {
    val queryOn = vm.tools.count { it.group == AiTools.Group.QUERY && it.enabled }
    val queryAll = vm.tools.count { it.group == AiTools.Group.QUERY }
    val opOn = vm.tools.count { it.group == AiTools.Group.OPERATE && it.enabled }
    val opAll = vm.tools.count { it.group == AiTools.Group.OPERATE }
    val readOn = vm.readModules.count { it.enabled }
    return "查询 $queryOn/$queryAll · 可读列表 $readOn/${vm.readModules.size} · " +
        "改数据 $opOn/$opAll（每次都要你点确认）"
}

/**
 * 能力开关的底部抽屉：查询类 / 操作类 / 可读的列表。
 *
 * 用户 2026-09-17：「那些开关太长了，能不能做一个折叠？但最好不要给它开一个新的页面……
 * 侧边抽屉、底部抽屉都可以，有更好的就用更好的。」
 *
 * 三个选择，说明一下为什么是现在这个：
 * - **不用新页面**：这一页有三个未保存的输入框（key / 模型名 / 地址），跳走再回来会丢；
 * - **不用侧边抽屉**：开关是"从上往下逐个扫"的动作，底部抽屉在单手可及范围内；
 * - **用 ModalBottomSheet**：这个 App 里已经是成熟做法（商品、地址、库存都在用同一套）。
 *
 * ⚠️ 内容整体可滚动：三个分组加起来有几十行，不给滚动的话底下的分组永远够不着。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CapabilitySheet(vm: AiSettingsViewModel, onDismiss: () -> Unit) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
                .padding(bottom = 32.dp),
        ) {
            Text("AI 能用的能力", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(4.dp))
            Text(
                "关掉哪个，它就查不到或做不了那一类事。默认全开。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            // 工具开关按"会不会改数据"分组：`preview_write` 一上，同一列里就同时躺着
            // "只看"和"会改"两类。混排的话用户扫一眼**根本分不出哪个会动数据**——
            // 而这一栏恰恰是他最该一眼看明白的地方。
            AiTools.Group.entries.forEach { group ->
                val items = vm.tools.filter { it.group == group }
                if (items.isEmpty()) return@forEach
                Spacer(Modifier.height(16.dp))
                Text(group.label, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(2.dp))
                Text(
                    group.hint,
                    style = MaterialTheme.typography.bodySmall,
                    color = if (group == AiTools.Group.OPERATE) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
                items.forEachIndexed { index, t ->
                    if (index > 0) HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
                    SwitchRow(t.title, t.hint, t.enabled) { vm.toggleTool(t.name, it) }
                }
                // 「操作类」必须补这一句：用户看到"AI 能改数据"时的第一反应就是
                // "它会不会自己就把账改了"。答案要写在开关旁边，而不是等他去试。
                if (group == AiTools.Group.OPERATE) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "打开后 AI 也只是把一张确认卡发到聊天页，写进系统要你点「确认」。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            // 通用读取：`read_data` 把只读列表全开了（用户要求"所有列表都能读"），
            // 但那不等于"用户希望 AI 什么都能看"。给一份**按模块**的清单，让他随时收窄。
            // ⚠️ 数量取 `AiReads.allActions()`（后端表 + **本机能力**）：写死目录那一份的话，
            //    「读手机定位」这类本机能力不会算进去，而这行字正是用户对"它能看多少"的唯一印象。
            Spacer(Modifier.height(16.dp))
            Text("可读的列表", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(2.dp))
            Text(
                "共 ${AiReads.allActions().size} 张只读列表，按模块开关。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            vm.readModules.forEachIndexed { index, m ->
                if (index > 0) HorizontalDivider(color = MaterialTheme.colorScheme.surfaceVariant)
                SwitchRow(m.title, m.hint, m.enabled) { vm.toggleReadModule(m.module, it) }
            }
        }
    }
}

/** 抽屉里的一行开关（标题 + 一句说明 + 右边开关）。三处列表共用，避免各写一遍走形。 */
@Composable
private fun SwitchRow(title: String, hint: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(hint, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Spacer(Modifier.width(12.dp))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

/**
 * 一条记忆：默认显示一行事实 + 「改」「删」；点「改」就地变成输入框。
 *
 * ### 为什么做"就地编辑"而不是弹窗
 * 记忆是**短文本**（上限 140 字），弹窗要多两次点击、还要模态遮住上下文；
 * 而用户往往是"看到这条写得不对，顺手改两个字"。就地编辑正好匹配这个动作。
 */
@Composable
private fun MemoryRow(
    item: AiMemoryItem,
    editing: Boolean,
    editingFact: String,
    onEditingFactChange: (String) -> Unit,
    onBeginEdit: () -> Unit,
    onCancelEdit: () -> Unit,
    onSaveEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    if (editing) {
        Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
            OutlinedTextField(
                value = editingFact,
                onValueChange = onEditingFactChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("这条事实") },
                supportingText = { Text("${editingFact.length} / ${AiMemories.MAX_FACT_CHARS}") },
                singleLine = false,
                maxLines = 3,
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = onCancelEdit) { Text("取消") }
                TextButton(onClick = onSaveEdit) { Text("保存") }
            }
        }
        return
    }

    Row(
        Modifier.fillMaxWidth().padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "• " + item.fact,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.weight(1f),
        )
        IconButton(onClick = onBeginEdit, modifier = Modifier.size(36.dp)) {
            Icon(
                Icons.Default.Edit,
                contentDescription = "修改这条记忆",
                modifier = Modifier.size(17.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        IconButton(onClick = onDelete, modifier = Modifier.size(36.dp)) {
            Icon(
                Icons.Default.DeleteOutline,
                contentDescription = "删除这条记忆",
                modifier = Modifier.size(17.dp),
                tint = MaterialTheme.colorScheme.error,
            )
        }
    }
}
