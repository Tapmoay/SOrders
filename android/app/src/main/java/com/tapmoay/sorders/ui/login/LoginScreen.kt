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
        }
    }
}
