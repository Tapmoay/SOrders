package com.tapmoay.sorders.ui.common

import androidx.compose.runtime.Composable
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory

/** 简化 ViewModel 构造（手动 DI 容器注入） */
@Composable
inline fun <reified VM : ViewModel> appViewModel(
    noinline create: () -> VM,
): VM = viewModel(factory = viewModelFactory { initializer { create() } })
