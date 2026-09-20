package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ExpenseCategoryDto
import com.tapmoay.sorders.data.remote.dto.ExpenseCreateRequest
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import java.time.LocalDate
import kotlinx.coroutines.launch

/**
 * **新增开销 = 单独一页**（2026-09-20 用户第六轮：问答里选的是"按钮 → 进单独一页填"，
 * 「就相当于新增订单一样」）。
 *
 * 为什么单独一页而不是内嵌一张卡：开销要填的东西本来就比"金额 + 备注"多
 * （分类 / 金额 / 日期 / 车辆 / 司机 / 备注），铺在列表页顶部会把记录区挤到屏幕外；
 * 而且字段以后还会长（用户已经在提"挂账单位"这类关联）。
 *
 * ⚠️ 分类是**名册里的名字**（可维护），所以这里只能选、不能现编 —— 要加分类去「分类管理」。
 *    这与商品新增那边"可以就地新建分类"是**故意不同**的：开销分类还决定卡片突出什么，
 *    随手新建会让那一类的卡片形态没人管。
 * ⚠️ **没有"关联订单"输入框**：从订单来的开销是**送达货损自动记的**（`accounting_service`），
 *    手填单号极易填错（单号是 18 位），要看订单来源去开销的「详情」里点。
 */
class ExpenseCreateViewModel(private val container: AppContainer) : ViewModel() {
    var categories by mutableStateOf<List<ExpenseCategoryDto>>(emptyList())
        private set
    var drivers by mutableStateOf<List<UserDto>>(emptyList())
        private set
    var vehicles by mutableStateOf<List<com.tapmoay.sorders.data.remote.dto.VehicleDto>>(emptyList())
        private set

    var category by mutableStateOf("")
    var amount by mutableStateOf("")
    var expDate by mutableStateOf(LocalDate.now().toString())
    var vehicleId by mutableStateOf<Long?>(null)
    var driverId by mutableStateOf<Long?>(null)
    var note by mutableStateOf("")

    var submitting by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
    var done by mutableStateOf(false)
        private set

    init {
        viewModelScope.launch {
            try {
                categories = container.repo.expenseCategories()
                category = categories.firstOrNull()?.name ?: ""
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
        viewModelScope.launch {
            runCatching { drivers = container.repo.drivers() }
            runCatching { vehicles = container.repo.vehicles() }
        }
    }

    fun submit() {
        val amt = amount.toDoubleOrNull() ?: 0.0
        if (category.isBlank()) {
            error = "请选择开销分类"
            return
        }
        if (amt <= 0) {
            error = "请输入金额"
            return
        }
        if (expDate.length != 10) {
            error = "日期要写成 2026-09-20 这样"
            return
        }
        submitting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.createExpense(
                    ExpenseCreateRequest(
                        expDate = expDate,
                        category = category,
                        amount = amount,
                        driverId = driverId,
                        vehicleId = vehicleId,
                        orderId = null,
                        note = note.trim(),
                    )
                )
                done = true
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                submitting = false
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpenseCreateScreen(container: AppContainer, onBack: () -> Unit, onSaved: () -> Unit) {
    val vm: ExpenseCreateViewModel = appViewModel { ExpenseCreateViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    // 记成功就回列表页（并由它刷新）—— 停在这一页只会让用户怀疑"存上了没有"
    LaunchedEffect(vm.done) { if (vm.done) onSaved() }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = { Text("新增开销", style = MaterialTheme.typography.titleLarge) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            SectionCard {
                DropField(
                    label = "开销分类（在「分类管理」里维护）",
                    text = vm.category.ifBlank { "请选择" },
                    options = vm.categories.map { it.name to it.name },
                    onSelect = { vm.category = it },
                )
                Spacer(Modifier.height(8.dp))
                SoTextField(
                    value = vm.amount,
                    onValueChange = { vm.amount = InputRules.moneyInput(it) },
                    placeholder = "金额（元）",
                    keyboardType = KeyboardType.Decimal,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                SoTextField(
                    value = vm.expDate,
                    onValueChange = { vm.expDate = it },
                    placeholder = "日期（2026-09-20）",
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            SectionCard {
                Text("关联（选填）", style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.height(6.dp))
                DropField(
                    label = "车辆",
                    text = vm.vehicles.firstOrNull { it.id == vm.vehicleId }?.let { vehicleText(it) } ?: "不指定",
                    options = listOf("" to "不指定") + vm.vehicles.map { it.id.toString() to vehicleText(it) },
                    onSelect = { vm.vehicleId = it.toLongOrNull() },
                )
                Spacer(Modifier.height(6.dp))
                DropField(
                    label = "司机",
                    text = vm.drivers.firstOrNull { it.id == vm.driverId }?.let { driverText(it) } ?: "不指定",
                    options = listOf("" to "不指定") + vm.drivers.map { it.id.toString() to driverText(it) },
                    onSelect = { vm.driverId = it.toLongOrNull() },
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "从订单来的开销（比如送达货损）由系统自己记，不用在这里填单号 —— " +
                        "要看某一笔是哪张单来的，在开销列表里点「详情」。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            SectionCard {
                SoTextField(
                    value = vm.note,
                    onValueChange = { vm.note = it },
                    placeholder = "备注（选填，比如「仲恺加油站 92#」）",
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            Button(
                onClick = { vm.submit() },
                enabled = !vm.submitting,
                colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange)),
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(if (vm.submitting) "保存中…" else "保存开销")
            }
        }
    }
}
