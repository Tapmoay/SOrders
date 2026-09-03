package com.tapmoay.sorders.ui.login

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
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
import com.tapmoay.sorders.BuildConfig
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.Session
import com.tapmoay.sorders.ui.common.appViewModel
import com.tapmoay.sorders.ui.theme.PrimaryContainer

@Composable
fun LoginScreen(
    container: AppContainer,
    onLoginSuccess: (Session) -> Unit,
    onGoRegister: () -> Unit,
) {
    val vm: LoginViewModel = appViewModel { LoginViewModel(container) }
    val scroll = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scroll)
            .padding(horizontal = 28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(72.dp))
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
        Spacer(Modifier.height(10.dp))
        TextButton(onClick = onGoRegister) { Text("没有账号？注册货主账号") }

        if (BuildConfig.DEBUG) {
            Spacer(Modifier.height(28.dp))
            Text(
                "开发账号：派单 13800000001 / 货主 13800000002 / 司机 13800000003，密码 pass12345",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.outline,
            )
        }
        Spacer(Modifier.height(24.dp))
    }
}
