package com.tapmoay.sorders.ui.dispatcher

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.core.UserSearch
import com.tapmoay.sorders.data.remote.api.PriceRuleDto
import com.tapmoay.sorders.data.remote.dto.LedgerCreateRequest
import com.tapmoay.sorders.data.remote.dto.ProductDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.*
import com.tapmoay.sorders.ui.theme.MoneyOrange
import com.tapmoay.sorders.util.formatMoney
import com.tapmoay.sorders.util.trimMoneyZeros
import java.time.LocalDate
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * 账本「**记一笔账**」= 单独一页（2026-09-20 用户第七轮）。
 *
 * ## 用户当时说的（口述 + 一张旧弹窗的截图）
 *
 * > 「他这个记**手动记账**的逻辑不对 —— **这个商品是可以在现有的商品库进行选择的**。
 * >  一般情况下假如**订单没有走、但是有一笔账是这样存在的**；**未注册的话也可以直接填**，
 * >  它会显示到列表上、**自动帮他注册一个临时账户**，相当于一个普通账户；
 * >  时间备注也是可以填的；**他只要填数量、对应的价格是会有的**，但是单价可能不一样 ——
 * >  **单价是可以改的**，也就是预售价可以单独调整。」
 *
 * ## 于是三个字段各归各家
 *
 * | 字段 | 从哪来 | 为什么 |
 * |---|---|---|
 * | **商品** | **只能从商品库选**（复用 `ui/common/ProductPicker.kt`，唯一那份"商品库浏览"UI） | 商品名手打会打出"红富士苹果 / 红富士 / 苹果"三个名字，库存与报表按名字分组时就成了三行；单价、单位本来也都挂在商品上 |
 * | **货主** | 选已注册货主，**或直接填未注册的名字** | 没建过档的客户是真实业务（"来收一趟货"）。填了名字就是**临时货主**（后端 `temp_shipper_name`，与「代理下单」同一套口径），下次能在同一个选择器的「用过的」里再选到，并出现在**货主账**里 —— 就是用户说的"自动注册一个临时账户、相当于一个普通账户" |
 * | **单价** | 选商品时**自动带出**（有批发商专属价就用专属价），**可以改** | 用户要的"预售价可以单独调整"。⚠️ 用户自己改过之后，**再换货主不许把价拽走**（见 [LedgerCreateViewModel.autoPrice]） |
 *
 * ## 为什么不是原来那个弹窗
 *
 * 商品选择器是**全屏底部弹层**（`ProductPickerSheet`）。把它套进 `AlertDialog` 里就是
 * **两层 modal 窗口**叠着 —— 在 Compose 里谁盖谁不稳，而这里是钱。
 * 而且这一页要填的东西本来就有 7 项（谁 / 什么货 / 数量 / 单价 / 合计 / 日期 / 备注），
 * 铺在一个弹窗里已经顶到屏幕边上了 —— 与「新增开销」选的是同一个形状（单独一页）。
 *
 * ## 与 AI 那条路的关系（故意不动）
 *
 * AI 的 `ledger.create_entry` 也允许"货主查不到 → 按临时客户记"，与这里**同口径**；
 * 它那边的商品是模型给的名字（模型没法浏览商品库），所以那一条**一行都不改**。
 */
class LedgerCreateViewModel(private val container: AppContainer) : ViewModel() {

    // ============================================================ 状态（全部声明在 init 之前）
    //
    // ⛔ `_check_vm_state_before_init.py` 钉着：Kotlin 按书写顺序初始化属性，而
    //    `viewModelScope` 用的是 `Dispatchers.Main.immediate` —— init 里那次 launch
    //    会在赋值点**同步**跑到第一个挂起点，写到声明在后面的状态就是 NPE（这一页直接崩）。

    // ---- 货主名册 ----
    var shippers by mutableStateOf<List<UserDto>>(emptyList())
        private set

    /** 服务端搜索结果（null = 没在搜 → 用整份名册）。 */
    var shipperHits by mutableStateOf<List<UserDto>?>(null)
        private set
    var shipperQuery by mutableStateOf("")
    var shipperSearching by mutableStateOf(false)
        private set

    /** 名册被服务端截断了没有（`/users` 一页 500）。截断了要**说出来**，见下面那段注释。 */
    var rosterTruncated by mutableStateOf(false)
        private set

    /** 用过的临时货主名字（账本 + 订单里出现过的，与后端 `temp-shipper-names` 同源）。 */
    var tempNames by mutableStateOf<List<String>>(emptyList())
        private set

    // ---- 商品库 ----
    var products by mutableStateOf<List<ProductDto>>(emptyList())
        private set
    var categoryOrder by mutableStateOf<List<String>>(emptyList())
        private set
    var productsLoading by mutableStateOf(false)
        private set
    var productsError by mutableStateOf<String?>(null)
        private set

    /** 当前货主的专属价（批发商价）。拉不到就空着 —— 退回默认售价。 */
    private var priceRules = emptyMap<Long, PriceRuleDto>()
    private var priceRulesShipper: Long? = null

    // ---- 这一笔 ----
    var shipperId by mutableStateOf<Long?>(null)
        private set
    var shipperName by mutableStateOf("")
        private set
    var shipperPhone by mutableStateOf<String?>(null)
        private set

    /** 未注册的名字。填了它 = 选了「临时货主」，与 [shipperId] **互斥**。 */
    var tempName by mutableStateOf("")

    var productId by mutableStateOf<Long?>(null)
        private set
    var productName by mutableStateOf("")
        private set
    var productUnit by mutableStateOf("")
        private set
    var qty by mutableStateOf("1")
    var price by mutableStateOf("")
    var entryDate by mutableStateOf(LocalDate.now().toString())
    var note by mutableStateOf("")

    var showShipperPicker by mutableStateOf(false)
    var showProductPicker by mutableStateOf(false)
    var submitting by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
    var done by mutableStateOf(false)
        private set

    /**
     * 上一次**自动带出**的单价。
     *
     * 用来分开"这个价是系统给的"和"这个价是用户自己报的"：
     * 用户在选完商品之后又改了单价（预售价单独调整），此时再换货主 ——
     * 换过去那一刻系统会重新算一次价。**用户改过的价不许被拽走**，
     * 而"系统刚带出来的那个价"被新货主的专属价覆盖才是对的。
     * 判据就是"当前价是否还等于上一次自动带出的那个"。
     */
    private var autoPrice: String? = null

    private var searchJob: Job? = null

    init {
        loadRoster()
        loadTempNames()
        loadProducts()
    }

    // ============================================================ 取数

    /**
     * 货主名册。
     *
     * ⚠️ 截断位必须留着：`/users` 一页上限 500，名册超过时"列表里没有这个人"会被读成
     *    "这个账号不存在" → 用户就去填一个临时货主 → 同一个人两本账。
     *    （与名册页 `usersPage` 同一条理由，见 `core/UserSearch.kt` 的文件头。）
     */
    fun loadRoster() {
        viewModelScope.launch {
            try {
                val page = container.repo.usersPage(role = "shipper")
                shippers = page.rows
                rosterTruncated = page.meta.hasMore
            } catch (e: Exception) {
                error = toApiException(e).message
            }
        }
    }

    fun loadTempNames() {
        viewModelScope.launch {
            runCatching { tempNames = container.repo.tempShipperNames() }
        }
    }

    /**
     * 搜货主 —— 走**服务端** `?q=`（名册页同一条规矩）。
     *
     * 为什么不在客户端过滤手里这一页：名册上限 500，第 501 个货主在客户端**根本不存在**。
     * 300ms 防抖：每个字一次请求本来就浪费。
     */
    fun searchShippers(kw: String) {
        shipperQuery = kw
        searchJob?.cancel()
        if (kw.isBlank()) {
            shipperHits = null
            shipperSearching = false
            return
        }
        searchJob = viewModelScope.launch {
            delay(300)
            shipperSearching = true
            try {
                shipperHits = container.repo.usersPage(role = "shipper", q = kw).rows
            } catch (e: Exception) {
                // ⚠️ 失败**不许**退回空列表：那等于对用户说"没有这个人"，
                //    而他会去填一个临时货主 —— 同一个人两本账。如实说没搜到。
                error = "搜索失败：" + toApiException(e).message
                shipperHits = null
            } finally {
                shipperSearching = false
            }
        }
    }

    fun loadProducts() {
        productsLoading = true
        productsError = null
        viewModelScope.launch {
            try {
                products = container.repo.products()
            } catch (e: Exception) {
                // 商品库拉不到与"真的没有商品"必须分开说（选品页那条注释同一个理由）
                productsError = toApiException(e).message
            } finally {
                productsLoading = false
            }
        }
        viewModelScope.launch {
            runCatching { categoryOrder = container.repo.productCategories().map { it.name } }
        }
    }

    // ============================================================ 选人

    /**
     * 选择**已注册货主**。
     *
     * 选完要重新取他的专属价：批发商的价与默认售价不一样，带错价等于报错价。
     */
    fun pickShipper(u: UserDto) {
        shipperId = u.id
        shipperName = userText(u)
        shipperPhone = u.phone.takeIf { it.isNotBlank() }
        tempName = ""
        showShipperPicker = false
        reloadPriceRules()
    }

    /**
     * 未注册的名字（用户手填，或从「用过的临时货主」里点一个）。
     *
     * 填了就**清掉**已注册账号 —— 一笔账只能记在一个人名下（后端也这么校验：
     * 同时给 `shipper_id` 与 `temp_shipper_name` 直接 400）。
     *
     * ⚠️ 函数名不能叫 `setTempName`：那是 [tempName] 那个属性自动生成的 setter 的 JVM 签名，
     *    两者会「Platform declaration clash」直接编译不过。
     */
    fun pickTempName(name: String) {
        tempName = name
        if (name.isNotBlank()) {
            shipperId = null
            shipperName = ""
            shipperPhone = null
            // 临时货主**没有专属价** —— 必须把上一份规则丢掉并重算价格，否则会停在
            // 上一个货主的专属价上（真机验出来的错价，见 [repriceIfAuto]）
            priceRules = emptyMap()
            priceRulesShipper = null
            repriceIfAuto()
        }
    }

    fun clearShipper() {
        shipperId = null
        shipperName = ""
        shipperPhone = null
        tempName = ""
        priceRules = emptyMap()
        priceRulesShipper = null
        repriceIfAuto()
    }

    /** 这一笔记给谁（显示用）。 */
    fun shipperLabel(): String = when {
        shipperId != null -> shipperName
        tempName.isNotBlank() -> tempName.trim()
        else -> "请选择货主"
    }

    /** 那行小字：已注册的写手机号，未注册的把"会记成临时货主"说清楚。 */
    fun shipperHint(): String = when {
        shipperId != null -> "已注册货主" + (shipperPhone?.let { " · " + it } ?: "")
        tempName.isNotBlank() -> "未注册 —— 会记成一个临时货主（和普通货主一样进账本，下次能直接选到）"
        else -> "未注册的客户可以直接填名字"
    }

    /** 选择器里列谁：搜的时候用搜索结果，没搜用整份名册。 */
    fun visibleShippers(): List<UserDto> = shipperHits ?: shippers

    /** 用过的临时货主（按搜索词过滤；这些人没有手机号）。 */
    fun visibleTempNames(): List<String> =
        UserSearch.filter(tempNames, shipperQuery, { it }, { null })

    // ============================================================ 选商品

    /**
     * 某个商品、**对这个货主**的实际单价：有专属价用专属价，否则默认售价。
     *
     * ⚠️ 只认**当前货主**那份规则：`priceRulesShipper` 对不上就回退默认价
     *    （与下单页同一个取舍：回退默认价是"少赚"，用错人的专属价是"报错价"）。
     */
    fun priceFor(p: ProductDto): String {
        val sid = shipperId
        if (sid == null || priceRulesShipper != sid) return p.defaultUnitPrice
        return priceRules[p.id]?.specialUnitPrice ?: p.defaultUnitPrice
    }

    private fun reloadPriceRules() {
        val sid = shipperId
        viewModelScope.launch {
            val loaded = try {
                if (sid == null) emptyMap() else container.repo.priceRules(sid).associateBy { it.productId }
            } catch (_: Exception) {
                emptyMap()
            }
            if (shipperId != sid) return@launch          // 请求回来时又换过人了，别写
            priceRules = loaded
            priceRulesShipper = sid
            repriceIfAuto()
        }
    }

    /**
     * 换了**记账对象**之后，把"系统带出来的那个价"按新对象重算一次。
     *
     * ⚠️ 这一条是真机验出来的（2026-09-20）：先选「顺鑫蔬菜批发」（荷兰豆有专属价 13.2）→ 带出 13.2，
     *    再把对象改成**未注册的名字** —— 价**停在 13.2**，而临时货主根本没有专属价，
     *    正确价是默认的 14.8。**两边都不报错**，只是报了错价。
     *    所以"换对象"（含换成临时货主、清空）都必须重算，而不是只有"换注册货主"才重算。
     * ⚠️ 用户**手改过**的价不许被拽走：判据是"当前价是否还等于上一次自动带出的那个"（[autoPrice]）。
     */
    private fun repriceIfAuto() {
        val pid = productId ?: return
        if (autoPrice != null && price != autoPrice) return
        val p = products.firstOrNull { it.id == pid } ?: return
        price = trimMoneyZeros(priceFor(p))
        autoPrice = price
    }

    /** 从商品库挑了一件（数量在选品页的小窗里填）。 */
    fun pickProduct(line: PickedLine) {
        productId = line.productId
        productName = line.name
        productUnit = line.unit
        qty = line.qty.toString()
        price = trimMoneyZeros(line.price)
        autoPrice = price
        showProductPicker = false
    }

    fun total(): Double = (qty.toIntOrNull() ?: 0) * (price.toDoubleOrNull() ?: 0.0)

    // ============================================================ 保存

    fun submit() {
        val q = qty.toIntOrNull()
        val p = price.toDoubleOrNull()
        val name = tempName.trim()
        if (shipperId == null && name.isEmpty()) {
            error = "请选择货主；未注册的客户可以直接填名字"
            return
        }
        if (productId == null) {
            error = "请从商品库里选商品"
            return
        }
        if (q == null || q <= 0) {
            error = "请填写正确的数量"
            return
        }
        if (p == null || p < 0) {
            error = "请填写正确的单价"
            return
        }
        if (entryDate.trim().length != 10) {
            error = "日期要写成 2026-09-20 这样"
            return
        }
        submitting = true
        error = null
        viewModelScope.launch {
            try {
                container.repo.createLedger(
                    LedgerCreateRequest(
                        shipperId = shipperId,
                        tempShipperName = if (shipperId == null) name else null,
                        entryDate = entryDate.trim(),
                        productName = productName,
                        productId = productId,
                        quantity = q,
                        unitPrice = price.trim(),
                        // ⛔ **不传 total**：后端的金额是 `unit_price × quantity`（Decimal）算出来的，
                        //    客户端用 Double 乘一遍再传上去，会出现 `36.900000000000006` 这种尾数
                        //    （"同一个数两处算法"，见 `_check_single_source.py` 的教训）。
                        total = null,
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

/** 这个人在界面上叫什么（与项目里那条兜底链一致：姓名 → 手机号 → 用户名）。 */
private fun userText(u: UserDto): String = u.fullName.ifBlank { u.phone.ifBlank { u.username } }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LedgerCreateScreen(container: AppContainer, onBack: () -> Unit, onSaved: () -> Unit) {
    val vm: LedgerCreateViewModel = appViewModel { LedgerCreateViewModel(container) }
    val snackbar = remember { SnackbarHostState() }
    OneShotSnackbar(snackbar, vm.error, onConsumed = { vm.error = null })

    // 记成功就回账本页（由它重新拉一次）—— 停在这一页只会让用户怀疑"存上了没有"
    LaunchedEffect(vm.done) { if (vm.done) onSaved() }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.background,
                ),
                title = { Text("记一笔账", style = MaterialTheme.typography.titleLarge) },
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
            // ---- 这一笔记给谁 ----
            SectionCard {
                Text("这一笔记给谁", style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.height(6.dp))
                Row(
                    Modifier.fillMaxWidth().clickable { vm.showShipperPicker = true },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TintedIcon(Icons.Default.Person, Color(0xFF00A2C7), size = 18.dp, container = 36.dp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            vm.shipperLabel(),
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            maxLines = 1,
                        )
                        Text(
                            vm.shipperHint(),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    TextButton(onClick = { vm.showShipperPicker = true }) { Text("选择") }
                }
            }

            // ---- 记什么商品 ----
            SectionCard {
                Text("记什么货", style = MaterialTheme.typography.titleSmall)
                Spacer(Modifier.height(6.dp))
                Row(
                    Modifier.fillMaxWidth().clickable { vm.showProductPicker = true },
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TintedIcon(Icons.Default.Inventory2, Color(MoneyOrange), size = 18.dp, container = 36.dp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            if (vm.productId == null) "从商品库里选" else vm.productName,
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.Bold,
                            maxLines = 1,
                        )
                        Text(
                            if (vm.productId == null) "商品、单位、单价都跟着商品库走（不是手打名字）"
                            else "单位：" + vm.productUnit + " · 数量与单价可以改",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    TextButton(onClick = { vm.showProductPicker = true }) {
                        Text(if (vm.productId == null) "选择" else "换一个")
                    }
                }
                Spacer(Modifier.height(8.dp))
                // ⚠️ 两个框**各自带一行小标题**：只靠 placeholder 的话，一旦填上值
                //    （真机截图里就是「2」和「14.8」）就分不出哪个是数量、哪个是单价 ——
                //    而右边那个是钱，填错就是报错价。
                Row {
                    FieldLabel("数量", Modifier.weight(1f))
                    Spacer(Modifier.width(8.dp))
                    FieldLabel("单价（元，可改）", Modifier.weight(1f))
                }
                Spacer(Modifier.height(6.dp))
                Row {
                    SoTextField(
                        value = vm.qty,
                        onValueChange = { vm.qty = InputRules.intInput(it, 6) },
                        keyboardType = KeyboardType.Number,
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(8.dp))
                    SoTextField(
                        value = vm.price,
                        onValueChange = { vm.price = InputRules.priceInput(it) },
                        keyboardType = KeyboardType.Decimal,
                        modifier = Modifier.weight(1f),
                    )
                }
                Spacer(Modifier.height(8.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        "合计",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.weight(1f))
                    Text(
                        "¥" + formatMoney(vm.total().toString()),
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                        color = Color(MoneyOrange),
                    )
                }
            }

            // ---- 日期 / 备注 ----
            SectionCard {
                SoTextField(
                    value = vm.entryDate,
                    onValueChange = { vm.entryDate = it },
                    placeholder = "日期（2026-09-20）",
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                SoTextField(
                    value = vm.note,
                    onValueChange = { vm.note = it },
                    placeholder = "备注（选填）",
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            Button(
                onClick = { vm.submit() },
                enabled = !vm.submitting,
                colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange)),
                modifier = Modifier.fillMaxWidth().height(48.dp),
            ) {
                Text(if (vm.submitting) "保存中…" else "记上这一笔")
            }
        }
    }

    // 选货主：已注册的 + 用过的临时货主 + 直接填名字
    if (vm.showShipperPicker) {
        ShipperPickerSheet(vm)
    }
    // 选商品：**商品库那一份 UI**（分类栏 + 搜索 + 数量小窗），单选
    if (vm.showProductPicker) {
        ProductPickerSheet(
            products = vm.products,
            loading = vm.productsLoading,
            priceFor = { vm.priceFor(it) },
            onConfirm = { lines -> lines.firstOrNull()?.let { vm.pickProduct(it) } },
            onDismiss = { vm.showProductPicker = false },
            categoryOrder = vm.categoryOrder,
            error = vm.productsError,
            onRetry = { vm.loadProducts() },
            single = true,
        )
    }
}

/**
 * 选货主（底部弹层）。
 *
 * 三段，从上到下就是用户那句话的顺序：
 * 1. **未注册**：一个输入框，填了就是临时货主（「也是可以直接填」）；
 * 2. **已注册货主**：名册（搜索走服务端 `?q=`）；
 * 3. **用过的临时货主**：以前记过的名字 —— 用户说的「它会显示到列表上」就是这一段，
 *    没有它，同一个没注册的客户会被写出「张老板 / 张老板（欠）」两个账户。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ShipperPickerSheet(vm: LedgerCreateViewModel) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(
        onDismissRequest = { vm.showShipperPicker = false },
        sheetState = sheetState,
        dragHandle = { BottomSheetDefaults.DragHandle() },
    ) {
        Column(Modifier.fillMaxWidth().fillMaxHeight(0.88f).padding(horizontal = 20.dp)) {
            Text("这一笔记给谁", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(10.dp))
            SoTextField(
                value = vm.tempName,
                onValueChange = { vm.pickTempName(it) },
                placeholder = "未注册的客户：直接填名字",
                modifier = Modifier.fillMaxWidth(),
            )
            Text(
                "填了名字就按临时货主记 —— 他会和普通货主一样出现在货主账里，下次直接从这个名单里选。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(10.dp))
            SearchField(value = vm.shipperQuery, onValueChange = { vm.searchShippers(it) })
            Spacer(Modifier.height(8.dp))

            val registered = vm.visibleShippers()
            val temps = vm.visibleTempNames()
            if (vm.shipperSearching) {
                Box(Modifier.fillMaxWidth().height(120.dp)) { LoadingBox() }
            } else {
                LazyColumn(Modifier.weight(1f)) {
                    item {
                        Text(
                            if (vm.shipperQuery.isBlank()) "已注册货主（" + registered.size + "）"
                            else "搜索结果（" + registered.size + "）",
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (registered.isEmpty()) {
                        item {
                            Text(
                                UserSearch.noMatchText(vm.shipperQuery) + "已注册货主",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(vertical = 8.dp),
                            )
                        }
                    }
                    items(registered, key = { it.id }) { u ->
                        PersonRow(
                            name = userText(u),
                            sub = u.phone.ifBlank { "未填手机号" },
                            selected = vm.shipperId == u.id,
                            onClick = { vm.pickShipper(u) },
                        )
                    }
                    if (temps.isNotEmpty()) {
                        item {
                            Spacer(Modifier.height(10.dp))
                            Text(
                                "用过的临时货主（未注册）",
                                style = MaterialTheme.typography.labelLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        items(temps, key = { "t|" + it }) { n ->
                            PersonRow(
                                name = n,
                                sub = "未注册（记在这个名字下）",
                                selected = vm.tempName.trim() == n,
                                onClick = { vm.pickTempName(n); vm.showShipperPicker = false },
                            )
                        }
                    }
                    if (vm.rosterTruncated && vm.shipperQuery.isBlank()) {
                        item {
                            Text(
                                "名册太长，这里只列了最近 500 个 —— 搜名字或手机号可以找到其他人。",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(vertical = 8.dp),
                            )
                        }
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = { vm.clearShipper() }) { Text("清空") }
                Spacer(Modifier.width(8.dp))
                Button(onClick = { vm.showShipperPicker = false }) { Text("完成") }
            }
            Spacer(Modifier.height(12.dp))
        }
    }
}

/** 输入框上面那行小标题（填上值以后，光靠 placeholder 分不出哪个框是什么）。 */
@Composable
private fun FieldLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = modifier,
    )
}

/** 名单里的一行（点一下 = 选他）。 */
@Composable
private fun PersonRow(name: String, sub: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = onClick)
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f)) {
            Text(name, style = MaterialTheme.typography.bodyLarge, maxLines = 1)
            Text(
                sub,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
            )
        }
    }
}
