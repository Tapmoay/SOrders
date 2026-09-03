package com.tapmoay.sorders.ui.login

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.Session
import com.tapmoay.sorders.ui.common.AppTopBar
import com.tapmoay.sorders.ui.common.appViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RegisterScreen(
    container: AppContainer,
    onBack: () -> Unit,
    onRegisterSuccess: (Session) -> Unit,
) {
    val vm: RegisterViewModel = appViewModel { RegisterViewModel(container) }

    Column(Modifier.fillMaxSize()) {
        AppTopBar(title = "注册货主账号", onBack = onBack)
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(16.dp))
            Text(
                "司机与派单员账号由管理员创建，这里仅支持货主自助注册",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(20.dp))

            OutlinedTextField(
                value = vm.phone,
                onValueChange = { vm.phone = it },
                label = { Text("手机号") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = vm.username,
                onValueChange = { vm.username = it },
                label = { Text("用户名（3-32 位，可中文）") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = vm.code,
                    onValueChange = { vm.code = it },
                    label = { Text("验证码") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(12.dp))
                OutlinedButton(
                    onClick = { vm.sendSms() },
                    enabled = !vm.sending && vm.countdown == 0,
                ) {
                    Text(if (vm.countdown > 0) "重新发送(" + vm.countdown + "s)" else "获取验证码")
                }
            }
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = vm.password,
                onValueChange = { vm.password = it },
                label = { Text("密码（至少 6 位）") },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                modifier = Modifier.fillMaxWidth(),
            )

            if (vm.error != null) {
                Spacer(Modifier.height(10.dp))
                Text(vm.error.orEmpty(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }
            if (vm.tip != null) {
                Spacer(Modifier.height(10.dp))
                Text(vm.tip.orEmpty(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.tertiary)
            }

            Spacer(Modifier.height(24.dp))
            Button(
                onClick = { vm.register(onRegisterSuccess) },
                enabled = !vm.loading,
                modifier = Modifier.fillMaxWidth().height(50.dp),
            ) {
                Text(if (vm.loading) "注册中…" else "注 册")
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}
