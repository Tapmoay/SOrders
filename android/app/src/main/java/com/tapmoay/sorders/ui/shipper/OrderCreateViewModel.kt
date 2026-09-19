package com.tapmoay.sorders.ui.shipper

import androidx.compose.runtime.*
import androidx.compose.runtime.snapshots.SnapshotStateList
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.api.PriceRuleDto
import com.tapmoay.sorders.data.remote.dto.*
import com.tapmoay.sorders.data.repo.toApiException
import com.tapmoay.sorders.ui.common.PickedLine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

data class LineDraft(
    val productId: Long? = null,
    val name: String = "",
    val quantity: Int = 1,
    val price: String = "",
    val unit: String = "件",
) {
    val lineTotal: Double get() = (price.toDoubleOrNull() ?: 0.0) * quantity
}

/** 一单最多几组商品（后端 `OrderCreate.lines` 也是 `max_length=10`）。 */
const val MAX_ORDER_LINES = 10

/**
 * 把一次挑好的商品并入下单清单（**纯函数**，有测试盯着 —— `ProductPickerTest`）。
 *
 * 两条规则，都是为了不出现"看着加了、其实没加"：
 * 1. **同一件商品已在清单里 → 累加数量**，不新开一行。
 *    外卖 App 就是这个行为，而且清单上限只有 10 行 —— 同一件货占两行会白白吃掉一格。
 * 2. 结果超过 [MAX_ORDER_LINES] → 返回 **null**（整批拒绝），**不做部分成功**。
 *    部分成功最危险：用户核对了 5 件，看不出第 3 件没进去。
 *
 * 抽出成顶层函数是为了能被单测直接调 —— 这段规则藏在 ViewModel 里就只能靠模拟器点。
 */
fun mergePickedIntoLines(existing: List<LineDraft>, picked: List<PickedLine>): List<LineDraft>? {
    val merged = existing.toMutableList()
    picked.forEach { item ->
        val idx = merged.indexOfFirst { it.productId != null && it.productId == item.productId }
        if (idx >= 0) {
            val old = merged[idx]
            merged[idx] = old.copy(quantity = old.quantity + item.qty, price = item.price, unit = item.unit)
        } else {
            merged.add(
                LineDraft(
                    productId = item.productId,
                    name = item.name,
                    quantity = item.qty,
                    price = item.price,
                    unit = item.unit,
                ),
            )
        }
    }
    return if (merged.size > MAX_ORDER_LINES) null else merged
}

class OrderCreateViewModel(private val container: AppContainer) : ViewModel() {

    val lines: SnapshotStateList<LineDraft> = mutableStateListOf()

    var addressDetail by mutableStateOf("")
    var addressLat by mutableStateOf<String?>(null)
    var addressLng by mutableStateOf<String?>(null)
    var dongjiaPhone by mutableStateOf("")
    var bossPhone by mutableStateOf("")
    var remark by mutableStateOf("")
    // 代理下单（派单员代下单）：shipperId=已注册货主；tempShipperName=临时货主（互斥）
    var shipperId by mutableStateOf<Long?>(null)
    var tempShipperName by mutableStateOf<String?>(null)
    var shippers by mutableStateOf<List<UserDto>>(emptyList())

    var products by mutableStateOf<List<ProductDto>>(emptyList())
    /** 分类名册的顺序（派单员在「商品管理 → 分类管理」里排的）；选品页左侧按它排。 */
    var categoryOrder by mutableStateOf<List<String>>(emptyList())
    /** 当前下单人的专属价格规则（productId -> rule）；下单选商品时按此显示/应用实际价 */
    var myShipperId by mutableStateOf<Long?>(null)
    var priceRules by mutableStateOf<Map<Long, PriceRuleDto>>(emptyMap())
    var priceRulesShipper by mutableStateOf<Long?>(null)
    var addresses by mutableStateOf<List<AddressDto>>(emptyList())
    /** 我自己的地点库（纯地点，含坐标）——司机补录过的坐标会进这里，下次下单直接可选 */
    var locations by mutableStateOf<List<LocationDto>>(emptyList())
    /** 共享地点库（全库共用；司机到场补录的坐标在这里） */
    var places by mutableStateOf<List<PlaceDto>>(emptyList())

    /**
     * 共享地点库"这一页不是全部"＝更少用的那些没取到（后端 `le=MAX_LIST`）。
     *
     * 判据是响应头 `X-Truncated`（走 `AppRepository.pageMeta()`）。这张表**只增不减**
     * （没有删除接口）又全库共用，所以"一页 100 条"迟早不等于"全部"——
     * 不说的话用户只会以为"我要的那个地点别人没标过"，于是自己再标一遍（又一条重复记录）。
     */
    var placesTruncated by mutableStateOf(false)
        private set

    /** 本次服务器上限（`X-Result-Limit`）；null = 老后端没回报，界面不许自己编一个数。 */
    var placesLimit by mutableStateOf<Int?>(null)
        private set
    var loadingProducts by mutableStateOf(false)
    /**
     * 商品目录**加载失败**的原因（2026-09-19 审计）。
     *
     * 原来这里只有一个从没被赋过 true 的 `loadingProducts`，而商品请求是
     * `catch (_: Exception) {}` 静默吞掉 → 选品页对"还在加载"和"加载失败"都会显示
     * 「**暂无可用商品**\n请联系派单员先在「商品管理」中添加商品后再下单」。
     * 那是**断言式假话**：货主弱网/服务重启时打开下单页就会看到它，然后去质问派单员"你们没配商品"，
     * 而派单员那边一切正常。失败必须有个能重试的出口。
     */
    var productsError by mutableStateOf<String?>(null)
    var submitting by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)
    var success by mutableStateOf(false)

    /** 外卖式全屏选品页（替代原来的小列表弹窗） */
    var showProductPicker by mutableStateOf(false)
    /** 收货地址选择页（线路 / 我的地点 / 共享地点 三段） */
    var showAddressSheet by mutableStateOf(false)
    var showMapPicker by mutableStateOf(false)
    /** 收货地址参考图（本地缓存路径，提交订单成功后逐张上传，最多 9 张） */
    val draftAddressImages: SnapshotStateList<String> = mutableStateListOf()
    var editingLineIndex by mutableStateOf<Int?>(null)
    /** 当前这个地址的坐标是否已经存进共享地点库（换地址要重置成 false） */
    var placeSaved by mutableStateOf(false)
    var savingPlace by mutableStateOf(false)
    /** 一次性提示（"已存进共享地点库"这类）；界面显示完自己清掉 */
    var toast by mutableStateOf<String?>(null)

    init {
        viewModelScope.launch {
            val s = container.tokenStore.sessionFlow.first()
            myShipperId = s?.userId
            loadPriceRulesFor(s?.userId)
        }
        // 预加载商品目录与地址库
        loadProducts()
        // 分类名册的顺序（派单员排的）。拉不到就退回"按商品数倒序"——
        // 顺序不理想，但**商品一件都不会少**（选品页不依赖它做过滤）。
        viewModelScope.launch {
            try { categoryOrder = container.repo.productCategories().map { it.name } } catch (_: Exception) {}
        }
        viewModelScope.launch {
            try { addresses = container.repo.addresses() } catch (_: Exception) {}
        }
        viewModelScope.launch {
            try { locations = container.repo.locations() } catch (_: Exception) {}
        }
        loadPlaces()
    }

    /** 共享地点库（全库共用）。搜索时由界面调 `loadPlaces(q)`。 */
    /**
     * 拉商品目录（失败要有出口：见 [productsError] 的注释）。
     * 界面在失败时显示"加载失败 + 重试"，而不是"暂无可用商品，请联系派单员添加"。
     */
    fun loadProducts() {
        if (loadingProducts) return
        loadingProducts = true
        productsError = null
        viewModelScope.launch {
            try {
                products = container.repo.products()
            } catch (e: Exception) {
                productsError = toApiException(e).message ?: "商品目录加载失败"
            } finally {
                loadingProducts = false
            }
        }
    }

    fun loadPlaces(q: String? = null) {
        viewModelScope.launch {
            try {
                val page = container.repo.placesPage(q)
                places = page.rows
                placesTruncated = page.meta.hasMore
                placesLimit = page.meta.limit
            } catch (_: Exception) {}
        }
    }

    fun loadShippers() {
        viewModelScope.launch {
            try { shippers = container.repo.shippers() } catch (_: Exception) {}
        }
    }

    fun setShipper(id: Long?, tempName: String?) {
        shipperId = id
        tempShipperName = tempName?.trim()?.ifBlank { null }
        loadPriceRulesFor(id ?: myShipperId)
    }

    /** 按下单主体（选择的货主，否则当前登录人）加载其专属价格规则 */
    fun loadPriceRulesFor(sid: Long?) {
        if (sid == null) {
            priceRules = emptyMap()
            priceRulesShipper = null
            return
        }
        // ⚠️ 换主体时**先把上一次的规则清掉**（2026-09-19 审计）：`priceRules` 是异步加载的，
        //    不清就会在"派单员代理下单：选货主 A（有专属价）→ 改选 B → 立刻打开选品页"这段窗口里
        //    继续用 A 的价（`priceFor` 读的是这个 map）。后果是**报价串号**：把甲谈下来的专属价
        //    按在乙头上、或按默认价报给本该有专属价的批发商——订单/小票/账本三处一致（都错），
        //    事后无从发现。`priceRulesShipper` 本来就该是"这份 map 属于谁"的守卫，之前只写不读。
        if (priceRulesShipper != sid) {
            priceRules = emptyMap()
            priceRulesShipper = null
        }
        viewModelScope.launch {
            try {
                val loaded = container.repo.priceRules().filter { it.shipperId == sid }.associateBy { it.productId }
                // 请求回来时主体又被换过就别写了（`priceRulesShipper` 已经指到新主体）
                if (shipperId == sid || (shipperId == null && myShipperId == sid)) {
                    priceRules = loaded
                    priceRulesShipper = sid
                }
            } catch (_: Exception) {
                loadingProducts = false   // 失败也要收尾，别让界面永远停在"加载中"
            }
        }
    }

    /**
     * 选择商品时的实际单价：有批发商专属价用特价，否则默认售价。
     *
     * ⚠️ 只认**当前下单主体**那份规则：`priceRulesShipper` 对不上就回退默认价
     * （回退到默认价是"少赚"，用错人的专属价是"报错价"，两害相权）。
     */
    fun priceFor(p: ProductDto): String {
        val subject = shipperId ?: myShipperId
        if (priceRulesShipper != subject) return p.defaultUnitPrice
        return priceRules[p.id]?.specialUnitPrice ?: p.defaultUnitPrice
    }

    /**
     * 选品页一次挑多件 → 一次性加入清单。
     *
     * 规则只有一处实现（`mergePickedIntoLines`，纯函数、有单测）：
     * 同件累加数量；超过 10 组**整批拒绝**并把还差多少说清楚。
     */
    fun addPickedLines(picked: List<PickedLine>): Boolean {
        if (picked.isEmpty()) return false
        val merged = mergePickedIntoLines(lines, picked)
        if (merged == null) {
            val room = (MAX_ORDER_LINES - lines.size).coerceAtLeast(0)
            error = "最多支持 $MAX_ORDER_LINES 组商品，这次挑了 ${picked.size} 件、还能放 $room 组，请少选几件"
            return false
        }
        lines.clear()
        lines.addAll(merged)
        error = null
        return true
    }

    fun updateLine(index: Int, line: LineDraft) {
        if (index in lines.indices) lines[index] = line
    }

    fun removeLine(index: Int) {
        if (index in lines.indices) lines.removeAt(index)
    }

    fun totalAmount(): Double = lines.sumOf { it.lineTotal }

    fun applyPicked(lat: Double, lng: Double, address: String) {
        addressLat = lat.toString()
        addressLng = lng.toString()
        addressDetail = address
        showMapPicker = false
        placeSaved = false
    }

    fun applyAddress(a: AddressDto) {
        addressDetail = a.detailAddress
        addressLat = a.addressLat
        addressLng = a.addressLng
        dongjiaPhone = a.phone
        showAddressSheet = false
        placeSaved = false
    }

    /**
     * 把当前坐标存进**共享地点库**（用户 2026-09-18 要的"共同的库…省的每个人都要手动上传一次"）。
     *
     * 为什么做成**手动一点**而不是"选了地图点就自动存"：
     * `places` 是**全库共享、而且没有删除接口**的一张表 —— 一次误操作留下的记录是永久的，
     * 所有人都会看到。所以写入必须由人明确点一下，而且点之前界面上写清楚会发生什么。
     * 乘车/选点是探索，这一下才是"我知道这个位置，贡献出来"。
     */
    fun saveCurrentPlaceToSharedLibrary() {
        val lat = addressLat
        val lng = addressLng
        if (lat.isNullOrBlank() || lng.isNullOrBlank()) {
            error = "还没有坐标，先用「地图选点」定位一下"
            return
        }
        // 名字与地址不能都是空（后端也挡，这里先说清楚，省一次往返）
        val name = addressDetail.trim()
        if (name.isBlank()) {
            error = "先填一下地址（共享库里只有坐标的话，别人认不出是哪儿）"
            return
        }
        savingPlace = true
        error = null
        viewModelScope.launch {
            try {
                val place = container.repo.createPlace(
                    com.tapmoay.sorders.data.remote.dto.PlaceCreateRequest(
                        name = name,
                        detailAddress = name,
                        addressLat = lat,
                        addressLng = lng,
                    ),
                )
                placeSaved = true
                // 如实说明"新建"还是"并入"：用户以为库里多了一条、而列表没变，是最容易困惑的地方
                toast = if (place.merged) "已并入共享地点库里的「${place.name}」（坐标相近，没有重复建）"
                else "已存进共享地点库，以后同样的位置大家都能直接选"
                loadPlaces()
            } catch (e: Exception) {
                error = toApiException(e).message
            } finally {
                savingPlace = false
            }
        }
    }

    /** 从「我的地点库」选终点（B 点）：带坐标时一并填上，这才叫"导航信息"。 */
    fun applyLocation(l: LocationDto) {
        addressDetail = l.detailAddress.ifBlank { l.name }
        addressLat = l.addressLat
        addressLng = l.addressLng
        showAddressSheet = false
        placeSaved = false
    }

    /** 从**共享地点库**选（别人/司机标过的坐标，直接拉过来）。 */
    fun applyPlace(p: PlaceDto) {
        addressDetail = p.detailAddress.ifBlank { p.name }
        addressLat = p.addressLat
        addressLng = p.addressLng
        showAddressSheet = false
        // 本来就是从共享库拉的，不用再存一次
        placeSaved = true
        // 记一次"我用了它"。**同一个人用到第 2 次**时后端会自动把它收进我的地点库，
        // 那时要在界面上说一句 —— 静默改了用户自己的库，他下次看到多出一条
        // 来源不明的记录只能猜。界面语言：说清"发生了什么"，不说"操作成功"。
        viewModelScope.launch {
            try {
                val r = container.repo.usePlace(p.id)
                if (r.autoAdded) {
                    toast = "「${p.name.ifBlank { p.detailAddress }}」你用过几次了，已加进你的「我的地点」"
                    locations = container.repo.locations()
                }
            } catch (_: Exception) {
                // 记账失败不该打断下单：它只是"常用地点"的统计，不是这单的必要条件
            }
        }
    }

    fun addDraftImage(path: String) {
        if (draftAddressImages.size >= 9) {
            error = "位置图片最多 9 张"
            return
        }
        if (path !in draftAddressImages) draftAddressImages.add(path)
    }

    fun removeDraftImage(path: String) {
        draftAddressImages.remove(path)
    }

    fun submit(onDone: () -> Unit) {
        val nameBlank = lines.any { it.name.isBlank() }
        // 电话格式先在这一侧挡一道：这两个框现在只让数字进来（`InputRules.phoneInput`），
        // 但"位数不够"过滤挡不住（用户可能刚输了一半就点提交）。在这里拦下来，
        // 用户看到的是**立刻**的中文提示，而不是等服务端 422 转一圈。
        // ⚠️ 两个电话都是**可选**的（不要顺手把它们改成必填 —— 那是产品决定，不是修 bug）。
        val phoneError = InputRules.phoneError(dongjiaPhone.trim())
            ?: InputRules.phoneError(bossPhone.trim())
        when {
            lines.isEmpty() -> error = "请至少添加一组商品"
            nameBlank -> error = "商品名称不能为空"
            phoneError != null -> error = phoneError
            else -> {
                submitting = true
                error = null
                viewModelScope.launch {
                    try {
                        val s = container.tokenStore.sessionFlow.first()
                        if (s?.role == "dispatcher" && shipperId == null && tempShipperName.isNullOrBlank()) {
                            error = "请选择货主或填写临时货主姓名"
                            submitting = false
                            return@launch
                        }
                        val body = OrderCreateRequest(
                            lines = lines.map {
                                // ⚠️ productId 必须带上：后端靠它写成本快照与扣库存
                                // （漏了它 = 毛利虚高 + 库存静默不扣，见 OrderProductLine.create 的注释）。
                                // 手输的自定义商品行本来就是 null，照传即可。
                                // unit 同理：不传就回商品库的单位，界面上选的「箱」会被丢掉。
                                OrderProductLine.create(it.name.trim(), it.quantity, it.price, it.productId, it.unit)
                            },
                            deliveryDescription = "",
                            addressDetail = addressDetail.trim(),
                            addressLat = addressLat,
                            addressLng = addressLng,
                            contactDongjiaPhone = dongjiaPhone.trim(),
                            contactBossPhone = bossPhone.trim(),
                            remark = remark.trim(),
                            shipperId = shipperId,
                            tempShipperName = tempShipperName,
                        )
                        val created = container.repo.createOrder(body)
                        draftAddressImages.forEach { path ->
                            runCatching {
                                val f = java.io.File(path)
                                if (f.exists()) container.repo.uploadOrderAddressImage(created.id, f)
                            }
                        }
                        success = true
                        onDone()
                    } catch (e: Exception) {
                        error = toApiException(e).message
                    } finally {
                        submitting = false
                    }
                }
            }
        }
    }
}