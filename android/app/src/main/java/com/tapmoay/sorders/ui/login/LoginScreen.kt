package com.tapmoay.sorders.ui.login

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LocalShipping
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.core.Session
import com.tapmoay.sorders.ui.common.appViewModel
import com.tapmoay.sorders.ui.theme.PrimaryContainer

@Composable
fun LoginScreen(
    container: AppContainer,
    onLoginSuccess: (Session) -> Unit,
) {
    val vm: LoginViewModel = appViewModel { LoginViewModel(container) }
    val scroll = rememberScrollState()
    // 注册小表单的开合（FEAT-0017）。默认为 false —— 登录页第一眼仍然只有登录。
    var showRegister by remember { mutableStateOf(false) }

    // 整块内容**垂直居中**（用户 2026-09-18：注册入口与开发账号提示去掉之后，
    // 内容全挤在顶部、下面一大片空，看着像没画完）。
    //
    // ⚠️ 为什么不能直接给 Column 加 `verticalArrangement = Center`：
    //    `verticalScroll` 会以"内容高度"测量 Column，Column 的高度就等于内容高度、
    //    没有多余空间可分配，Center 自然不生效（照样贴顶）。
    //    所以用 BoxWithConstraints 拿到**视口高度**，再用 `heightIn(min = 视口高)` 把
    //    Column 撑到至少一屏高——这样 Center 才有空间居中，内容超过一屏时仍然能滚动。
    //
    // ⚠️ 让位（inset）必须加在**这一层 Box 上**，不能加在里面那个 Column 上：
    //    加在 Column 上时 `imePadding` 只影响 Column 自己的内部布局，
    //    `BoxWithConstraints.maxHeight` 仍是**整屏高度**——于是内容按整屏居中，
    //    「登录」按钮正好落在键盘底下（真机实测就是这样，用户反馈"挡到了"）。
    //    加在 Box 上之后 maxHeight 会随键盘变小，内容整体上移并重新居中：
    //    输入密码时一整块（含登录按钮）都在键盘上方，既不被挡、看着也齐。
    BoxWithConstraints(
        modifier = Modifier
            .fillMaxSize()
            .safeDrawingPadding()   // 状态栏/手势条
            .imePadding(),          // 键盘：让 maxHeight 反映剩下的高度
    ) {
        val viewportHeight = maxHeight
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(scroll)
                .heightIn(min = viewportHeight)
                .padding(horizontal = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            Surface(color = PrimaryContainer, shape = MaterialTheme.shapes.extraLarge) {
                Icon(
                    Icons.Default.LocalShipping,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.padding(18.dp).size(44.dp),
                )
            }
            Spacer(Modifier.height(16.dp))
            Text("SOrders 派单送货", style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.height(6.dp))
            Text(
                "货主 · 司机 · 派单 三端协作",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(40.dp))

            OutlinedTextField(
                value = vm.phone,
                onValueChange = { vm.phone = it },
                label = { Text("手机号 / 用户名") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(14.dp))
            OutlinedTextField(
                value = vm.password,
                onValueChange = { vm.password = it },
                label = { Text("密码") },
                singleLine = true,
                visualTransformation = if (vm.showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                trailingIcon = {
                    IconButton(onClick = { vm.showPassword = !vm.showPassword }) {
                        Icon(
                            if (vm.showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                            contentDescription = if (vm.showPassword) "隐藏密码" else "显示密码",
                        )
                    }
                },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                // 键盘上的「完成/✓」直接登录：居中的布局在键盘弹起时会被顶上去，
                // 按钮可能正好在键盘下面——没有这个的话用户得先收键盘再点按钮。
                keyboardActions = KeyboardActions(onDone = { vm.login(onLoginSuccess) }),
                modifier = Modifier.fillMaxWidth(),
            )

            if (vm.error != null) {
                Spacer(Modifier.height(10.dp))
                Text(
                    vm.error.orEmpty(),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            Spacer(Modifier.height(24.dp))
            Button(
                onClick = { vm.login(onLoginSuccess) },
                enabled = !vm.loading,
                modifier = Modifier.fillMaxWidth().height(50.dp),
                shape = MaterialTheme.shapes.medium,
            ) {
                if (vm.loading) {
                    CircularProgressIndicator(Modifier.size(22.dp), color = MaterialTheme.colorScheme.onPrimary, strokeWidth = 2.dp)
                } else {
                    Text("登 录", style = MaterialTheme.typography.labelLarge)
                }
            }

            // 注册入口：**一行文字链**，不是第二个按钮/第二张卡。
            // 用户 2026-10-11（FEAT-0017）：「我们登录界面它其实可以注册账号的」——而登录页的
            // 主角是登录，两个同样大的按钮会让人第一眼分不清该点哪个（仓库里早有同类口径：
            // "两个入口一实一虚"、主操作只有一个）。放在登录按钮**下面**是因为这里的读者是
            // **还没有账号的人**（老用户根本不需要往下看）。
            //
            // ⚠️ 这一行加在这里会改变整块的垂直高度；外面那套"居中"是靠
            //    `heightIn(min = viewportHeight)` + `Arrangement.Center` 撑出来的，
            //    所以内容变高之后仍然居中，**不要**为此去掉 heightIn（去掉就贴顶了，见 :33-47）。
            Spacer(Modifier.height(6.dp))
            TextButton(
                onClick = { showRegister = true },
                enabled = !vm.loading,
                colors = ButtonDefaults.textButtonColors(
                    contentColor = MaterialTheme.colorScheme.onSurfaceVariant, // 不抢眼
                ),
            ) {
                Text("注册新账号", style = MaterialTheme.typography.bodyMedium)
            }
        }
    }

    // 小表单：手机号 + 密码（+ 姓名可选）。⛔ 不做成单独一整页 —— 注册是低频动作，
    // 为一个三字段的表单离开登录页、回来还要重新输手机号（用户会骂）。
    if (showRegister) {
        RegisterDialog(
            container = container,
            onDismiss = { showRegister = false },
            onRegistered = onLoginSuccess,
        )
    }
}

/**
 * 注册小表单（手机号 + 密码 + 姓名可选）。
 *
 * ## 为什么是 Dialog 而不是登录页里的第二组输入框
 * 登录与注册的**第一件输入**相同（手机号）但**后果**不同：注册会真的建一个账号。
 * 两套输入框并排摆着，用户很容易在"想登录"时把密码填进注册那一栏 —— 于是凭空多一个号。
 * 弹层把这个区别摆在明面上（要主动点开），也不需要为它做路由。
 *
 * ## 说人话的错误
 * [RegisterViewModel.register] 里失败时取的是 `ApiClient.toApiException(e).message`：
 * 后端**中文原话原样透出**（"该手机号已存在"、426 那句升级提示、429 那句限流提示），
 * 英文的校验错误走 `humanizeValidation` 的中文兜底。所以这里**不要**再翻译一遍。
 */
@Composable
private fun RegisterDialog(
    container: AppContainer,
    onDismiss: () -> Unit,
    onRegistered: (Session) -> Unit,
) {
    val rvm: RegisterViewModel = appViewModel { RegisterViewModel(container) }

    AlertDialog(
        onDismissRequest = { if (!rvm.loading) onDismiss() },
        title = { Text("注册新账号") },
        text = {
            Column(modifier = Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
                Text(
                    "用手机号注册，注册后就是货主，可以直接下单。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(14.dp))
                OutlinedTextField(
                    value = rvm.phone,
                    // 输入即规整：只留 ASCII 数字、剥掉 86 前缀、截到 11 位（与后端同一口径）。
                    // 顺手清掉上一次的错误提示 —— 让红字停在屏幕上、用户改完还看着它，会以为没改对。
                    onValueChange = { rvm.phone = InputRules.mobileInput(it); rvm.error = null },
                    label = { Text("手机号") },
                    placeholder = { Text("11 位，例如 13800000000") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = rvm.password,
                    onValueChange = { rvm.password = it; rvm.error = null },
                    label = { Text("密码") },
                    placeholder = { Text("至少 " + RegisterViewModel.MIN_PASSWORD + " 位") },
                    singleLine = true,
                    visualTransformation = if (rvm.showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        IconButton(onClick = { rvm.showPassword = !rvm.showPassword }) {
                            Icon(
                                if (rvm.showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                contentDescription = if (rvm.showPassword) "隐藏密码" else "显示密码",
                            )
                        }
                    },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = rvm.fullName,
                    onValueChange = { rvm.fullName = it },
                    label = { Text("姓名（可不填）") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )

                if (rvm.error != null) {
                    Spacer(Modifier.height(10.dp))
                    Text(
                        rvm.error.orEmpty(),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
                // 注册成功**不弹任何解释**：直接进 App（用户要的是"注册完就能用"）。
            }
        },
        confirmButton = {
            TextButton(
                onClick = { rvm.register(onRegistered) },
                enabled = !rvm.loading,
            ) {
                if (rvm.loading) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                } else {
                    Text("注册并进入")
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !rvm.loading) { Text("取消") }
        },
    )
}
