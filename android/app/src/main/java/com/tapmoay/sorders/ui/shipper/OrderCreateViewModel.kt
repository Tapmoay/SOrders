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
import kotlinx.coroutines.Job
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

/**
 * 把清单里每一行的单价**按"现在的价"重算一遍**（**纯函数**，有测试盯着 —— `RepriceLinesTest`）。
 *
 * ## 为什么必须重算（2026-09-22 用户报的错价，真机上量到 20 而谈好的是 10）
 *
 * 下单页的单价**没有任何人能改**（行编辑弹窗只有商品名与数量，见 `LineEditDialog`），
 * 每一行的价都是按"这一单对**这个**货主的价"（`priceFor`）算出来的。而那份价是
 * **异步**取回来的，于是有两个窗口会算错，且**两边都不报错**：
 *
 * · **预订单预填**：`setShipper` 刚发起请求就紧接着算行价 → `priceFor` 那一下
 *   `priceRulesShipper` 还对不上主体 → 走"回退默认价"分支 → 批发商谈好的专属价被跳过；
 * · **先挑商品、后换货主**：行上留着**上一个货主**的专属价（报价串号）。
 *
 * 所以"规则到齐 / 主体换了"时要统一重算一次 —— 而不是只在挑商品那一刻算一次。
 *
 * ⚠️ 只重算**商品还在商品库里**的行（[priceOf] 返回 null = 这件商品已不在库，价留空，
 *    由调用方如实说出来）；数量、单位、名称一律不碰。
 * ⚠️ 这条重算**不会覆盖任何人的输入**：单价在这个页面上根本不可编辑（有红线钉着
 *    `_tools/qa/_check_input_rules.py` 的 `NO_PRICE_EDIT_FILES`）。
 *
 * @return 新清单 + 改动了几行（0 = 一行都没变）
 */
fun repriceLines(
    lines: List<LineDraft>,
    priceOf: (Long) -> String?,
): Pair<List<LineDraft>, Int> {
    var changed = 0
    val out = lines.map { ln ->
        val pid = ln.productId
        val np = if (pid == null) null else priceOf(pid)
        if (np == null || np == ln.price) {
            ln
        } else {
            changed++
            ln.copy(price = np)
        }
    }
    return out to changed
}

class OrderCreateViewModel(private val container: AppContainer) : ViewModel() {

    val lines: SnapshotStateList<LineDraft> = mutableStateListOf()

    var addressDetail by mutableStateOf("")
    var addressLat by mutableStateOf<String?>(null)
    var addressLng by mutableStateOf<String?>(null)
    /**
     * 这一单用的是**库里哪一条**（2026-09-22 统一列表排序规则：常用度要能排出来）。
     *
     * 用户原话：「我在下单的时候经常用到这个联系人或者批发商……**用得越多越往前**」。
     * 后端靠随单带上来的 id 记一次常用度 —— 没有 id 就**计不了分**（而这是静默的：
     * 界面上一切照常，只是那条记录永远不往前）。
     *
     * 三条边界（都在 [applyAddress] / [applyLocation] / [applyPicked] 里落）：
     * · 选了**线路** → 记线路 id（收货人是从这条线路带出来的）；
     * · 选了**我的地点** → 记地点 id；
     * · **地图上自己选点 / 手输地址** → 两个都清空（那不是库里的哪一条）。
     */
    var pickedAddressId by mutableStateOf<Long?>(null)
    var pickedLocationId by mutableStateOf<Long?>(null)
    var dongjiaPhone by mutableStateOf("")
    var bossPhone by mutableStateOf("")
    /**
     * 收货人 / 下单人的**名称**（2026-09-20 用户要求；下单人的来源 2026-09-22 第二轮改过）。
     *
     * 自动填选的两条来源（各一处，别在界面里再判一次）：
     * · **收货人** = 选中的那条线路（`shipper_addresses.receiver_name`）→ [applyAddress]；
     * · **下单人** = **这一单的货主** → 判据只有一处
     *   （`OrdererPrefill.kt::ordererContactFor`，⚠️ 别在这里再写一遍）：
     *   货主 / 批发商自己下单＝他自己（[prefillOrdererFromSelf]，走 `/users/me`）；
     *   **派单员代理下单＝选中的那位货主**（[applyOrdererFromShipper]，⚠️ 选了谁就是谁，
     *   一位都没选时**留空** —— ⛔ 绝不留派单员自己的姓名/电话）。
     * 两个都是**可改**的普通输入框：自动填只是省一次输入，不是锁死。
     */
    var dongjiaName by mutableStateOf("")
    var bossName by mutableStateOf("")
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
    /**
     * 在飞的"专属价"请求（**预订单预填必须等它**，见 [awaitPriceRules]）。
     *
     * 没有它就只能靠"请求比下一行代码快"这个假设，而那个假设在真机上是**不成立**的。
     */
    private var priceRulesJob: Job? = null
    var addresses by mutableStateOf<List<AddressDto>>(emptyList())
    /** 我自己的地点库（纯地点，含坐标）——司机补录过的坐标会进这里，下次下单直接可选 */
    var locations by mutableStateOf<List<LocationDto>>(emptyList())
    /** 共享地点库（全库共用；司机到场补录的坐标在这里） */
    var places by mutableStateOf<List<PlaceDto>>(emptyList())

    /** 地点分类名册（**自己那一份**）：地址库左栏自定义分类那一截按它排。 */
    var placeCategories by mutableStateOf<List<com.tapmoay.sorders.data.remote.dto.PlaceCategoryDto>>(emptyList())

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

    /**
     * 收掉那条一次性提示（界面右上角的 ✕）。
     *
     * 为什么要有它：`toast` 是**一个槽位**、写进去就一直在，直到下一句话把它替换掉。
     * 页面顶部那条横幅要是不能关，预填那句话就会一直挂在屏幕上（用户改完商品它还挂在那儿）。
     */
    fun dismissToast() {
        toast = null
    }
    /**
     * 我能不能管共享库（改/撤销/删除共享地址、把我的地点设为共享）。
     *
     * 判据只有一个：**登录角色是派单员**（与后端 `require_roles(DISPATCHER)` 同一件事）。
     * 界面上不给他画那几个按钮，省得点了才吃一个 403 —— 但真正的门在后端，
     * 这个标记只决定"画不画入口"。
     */
    var canManageSharedPlaces by mutableStateOf(false)
        private set

    /**
     * 这一页是不是**代理下单**（登录角色是派单员）。
     *
     * 它只决定一件事，但那件事很要紧：**「下单人」不许填成派单员自己**
     * （用户 2026-09-22：「派单员，他是代理下单啊，所以他不能填写自己的名称和电话号码，
     * 他要填的是自动填选的是货主的」）。判据只有一处（`OrdererPrefill.kt`），
     * 这个标记只是"该走哪一支"。界面也用它换一句占位文案。
     */
    var proxyMode by mutableStateOf(false)
        private set

    init {
        viewModelScope.launch {
            val s = container.tokenStore.sessionFlow.first()
            myShipperId = s?.userId
            proxyMode = s?.role == "dispatcher"
            canManageSharedPlaces = proxyMode
            // 代理下单**不预填自己**：等 `setShipper` 选了货主再填那位货主的（见 [applyOrdererFromShipper]）。
            if (!proxyMode) {
                // 货主 / 批发商自己下单：下单人＝他自己，取**账号资料**（`/users/me`）的姓名与电话。
                // ⛔ 不能用会话里的 `username` 当电话（种子/老数据里可能是人名 → 填一个打不通的号）。
                try {
                    val me = container.repo.me()
                    prefillOrdererFromSelf(me.fullName.ifBlank { s?.fullName }, me.phone)
                } catch (_: Exception) {
                    prefillOrdererFromSelf(s?.fullName, null)
                }
            }
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
        viewModelScope.launch {
            try { placeCategories = container.repo.placeCategories() } catch (_: Exception) {}
        }
        loadPlaces()
    }

    /**
     * 地址库抽屉每次打开都刷一遍**抽屉里显示的那三份**：分组名册 / 线路 / 我的地点。
     * （分组名册是"自己那一份"：货主和派单员各管各的，互相看不到。）
     *
     * ⚠️ 为什么必须刷：VM 挂在路由上随页面复用，而这四份数据只在 `init` 里各拉过一次。
     * 用户去「地址与联系人」新建了一个地点、再回来下单 —— 抽屉里**还是进来时那一份**，
     * 表现是"我刚建的地方这里选不到"（只能退出重进，而退出重进看起来跟"就是没有"一样）。
     *
     * ⚠️ 三份必须**一起**刷，所以只留这一个入口（原来只有 `reloadPlaceCategories`）：
     * 分组**改名会在后端级联改掉挂着的地点的 `category`**，而本地的 `locations` 还带着旧名字 ——
     * 只刷名册的话，点进那个刚改名的分组会显示「这个分组下还没有地点」（按新名字一条都筛不到），
     * 而数据其实一条没少。这正是"只刷其中一段"会造出来的假象。
     */
    fun reloadAddressLibrary() {
        viewModelScope.launch { try { placeCategories = container.repo.placeCategories() } catch (_: Exception) {} }
        viewModelScope.launch { try { addresses = container.repo.addresses() } catch (_: Exception) {} }
        viewModelScope.launch { try { locations = container.repo.locations() } catch (_: Exception) {} }
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

    // ===== 共享库的管理（**只有派单员**，用户 2026-09-19）=====
    //
    // 用户原话：「共享地址的编辑只有派单员可以编辑，其他人都编辑不了。派单员可以改名称，
    // 也可以把一些地点给设置为共享地址，也可以撤销某些共享地址，把它降为普通的地址，
    // 或者直接删掉」。
    //
    // 四个动作都在这里**如实回报**（`toast`），而且**改完立刻重拉两份列表**：
    // 撤销会同时改「共享地点」（少一条）和「我的地点」（多一条），只刷一份的话
    // 抽屉里会出现"刚撤销的地点还在共享库里"这种假象。

    /** 改共享地点的名称/地址。 */
    fun updatePlace(id: Long, name: String?, address: String?) {
        if (name == null && address == null) {
            toast = "没有要改的内容"
            return
        }
        viewModelScope.launch {
            try {
                container.repo.updatePlace(
                    id,
                    com.tapmoay.sorders.data.remote.dto.PlaceUpdateRequest(name = name, detailAddress = address),
                )
                toast = "已改共享地点"
                loadPlaces()
            } catch (e: Exception) {
                toast = toApiException(e).message
            }
        }
    }

    /** 从共享库**删掉**一个地点（软删 → 进回收站，界面立刻给一次「撤销」的机会）。 */
    fun deletePlace(id: Long) {
        viewModelScope.launch {
            try {
                container.repo.deletePlace(id)
                recentlyDeletedPlace = id to (places.firstOrNull { it.id == id }?.name.orEmpty())
                toast = "已从共享地点库删除（别人的选点列表里也没有它了；删错了可以点「撤销」）"
                loadPlaces()
            } catch (e: Exception) {
                toast = toApiException(e).message
            }
        }
    }

    /**
     * 刚删掉的那条（编号 + 名字）：界面拿它在列表顶上画一行「已删除 · 撤销」。
     *
     * 为什么要有它：删除是**软删**（用户 2026-09-19 定的规矩），"能恢复"这件事
     * 必须在**手边**有个入口 —— 撤回卡只在 AI 那条路上有，人点的那一下也得能撤回来。
     */
    var recentlyDeletedPlace by mutableStateOf<Pair<Long, String>?>(null)

    /** 把刚删掉的那条共享地点放回来（回收站里那一条）。 */
    fun restorePlace(id: Long) {
        viewModelScope.launch {
            try {
                container.repo.restorePlace(id)
                recentlyDeletedPlace = null
                toast = "已恢复这条共享地点"
                loadPlaces()
            } catch (e: Exception) {
                toast = toApiException(e).message
            }
        }
    }

    /** **撤销**共享地址 → 降为**自己**的普通地点。 */
    fun demotePlace(id: Long) {
        viewModelScope.launch {
            try {
                val r = container.repo.demotePlace(id)
                toast = if (r.created) "已撤销，并存进了你的「我的地点」"
                else "已撤销（你本来就有这个地点，没有重复加）"
                locations = container.repo.locations()
                loadPlaces()
            } catch (e: Exception) {
                toast = toApiException(e).message
            }
        }
    }

    /** 把「我的地点」里的一个地点**设为共享地址**。 */
    fun shareLocation(l: LocationDto) {
        viewModelScope.launch {
            try {
                val p = container.repo.shareLocation(l.id)
                // 如实说明"新建"还是"并入"：用户以为库里多了一条、而列表没变，是最容易困惑的地方
                toast = if (p.merged) "已并入共享地点库里的「${p.name}」（坐标相近，没有重复建）"
                else "已设为共享地址，以后大家都能直接选它"
                loadPlaces()
            } catch (e: Exception) {
                toast = toApiException(e).message
            }
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
        // 「下单人」跟着货主走（用户 2026-09-22：「他选择货主之后，他写的货主的信息就会
        // 自动地填入进去，也就是名称和电话号码」）—— 代理下单这一路上这是**唯一**的填法。
        if (proxyMode) applyOrdererFromShipper(id)
        loadPriceRulesFor(id ?: myShipperId)
    }

    /**
     * 把「下单人」换成 [id] 这位货主（**代理下单专用**）。
     *
     * ⚠️ 名册里查不到就**去后端单取一个**：`shippers` 只在打开"选择货主"弹窗时才拉
     *    （[loadShippers]），而「用预订单下单」是**带参直达**这一页的（[prefillFromTemplate]）
     *    —— 那条路上名册可能还是空的，静默不填的表现就是"下单人又空了"，而这一轮要修的正是它。
     * ⚠️ 先按**手上有的**写一次（查不到就写空）：宁可空着，也绝不能留着**上一位**货主的电话
     *    —— 那是一串看起来很正常的号码，司机到了现场打过去是**别人**。
     */
    private fun applyOrdererFromShipper(id: Long?) {
        if (id == null) {
            // 临时货主那一支（或什么都没选）：名字从临时货主来，电话留空。
            writeOrderer(ordererContactFor(null, null, proxyMode = true, shipper = null, tempShipperName = tempShipperName))
            return
        }
        val cached = shippers.firstOrNull { it.id == id }
        writeOrderer(ordererContactFor(null, null, proxyMode = true, shipper = cached, tempShipperName = null))
        if (cached != null) return
        viewModelScope.launch {
            val u = runCatching { container.repo.userById(id) }.getOrNull() ?: return@launch
            // 这期间用户可能又换了货主 / 改成临时货主了 —— 只认"还是这一个 id"的回包（防串号）
            if (proxyMode && shipperId == id && tempShipperName == null) {
                writeOrderer(ordererContactFor(null, null, proxyMode = true, shipper = u, tempShipperName = null))
            }
        }
    }

    // ============================================================ 预订单（预设单）预填

    /**
     * 这一单是从哪张预设单预填来的（0 / null = 不是）。
     *
     * 只有两个用途：① 下单成功后记一次常用度（见 [submit]）；② 界面据此说一句"已按预设单填好"。
     * ⛔ 它**不参与下单请求**：预设单只是一个"预填模板"，下单参数就是屏幕上那些值
     * （用户改了什么就以什么为准 —— 这正是用户说的"参数没有变直接下单"的反面：
     * 参数**可以**变，改了照新值下）。
     */
    var appliedTemplateId by mutableStateOf<Long?>(null)
        private set

    /**
     * 按预设单 `id` 预填这一单（「预订单」页点「用这张下单」时调一次）。
     *
     * ### 三件事必须按这个顺序做
     * 1. **先把商品库拉回来**：预设单里**没有单价**（价格会变，存旧价＝几个月后按旧价下单），
     *    价格要按"这一单对这个货主的实际价"现算 —— 那一份口径只有一处（[priceFor]）。
     *    商品库没到就填行，价格栏会一片空白（而用户会以为预设单没存价格，其实是我们没算）。
     * 2. **商品行整份替换**（不是追加）：从预设单进来就是"照这张单来"，
     *    追加会让上一次没提交干净的行混在里面（多订一样货，而界面上看不出来）。
     * 3. **货主先设**：`setShipper` 会去拉这个货主的专属价，顺序反了会先按默认价算一遍。
     *
     * @param onDone 失败时给一句中文原因（界面用一次性提示显示）；成功给 null。
     */
    fun prefillFromTemplate(id: Long, onDone: (String?) -> Unit = {}) {
        viewModelScope.launch {
            try {
                if (products.isEmpty()) {
                    products = container.repo.products()
                }
                val t = container.repo.orderTemplates().firstOrNull { it.id == id }
                if (t == null) {
                    onDone("这张预设单已经不在了（可能刚被删掉）")
                    return@launch
                }
                if (t.shipperId != null) setShipper(t.shipperId, null)
                if (t.address.isNotBlank()) {
                    addressDetail = t.address
                    // 预设单里存的是**地址文字**，不是库里哪一条 → 两个 id 都清掉
                    // （留着上一次的 id 会让后端把常用度记到别的地址头上）
                    pickedAddressId = null
                    pickedLocationId = null
                }
                if (t.receiverName.isNotBlank()) dongjiaName = t.receiverName
                if (t.receiverPhone.isNotBlank()) dongjiaPhone = t.receiverPhone
                if (t.remark.isNotBlank()) remark = t.remark

                // ⚠️ **等这个货主的专属价到齐再填行**（2026-09-22 用户报的错价就出在这一步）：
                //    `setShipper` 只是**发起**取数，紧接着去算行价必定命中"规则还没到"的回退分支
                //    —— 批发商谈好的 10 元被跳过、按默认价 20 元填上，而**已经填好的行不会**
                //    因为规则随后到达而重算。所以这不是优化，是这条链路成立的前提。
                awaitPriceRules()

                val missing = ArrayList<String>()
                lines.clear()
                t.lines.forEach { ln ->
                    val p = products.firstOrNull { it.id == ln.productId }
                    if (p == null) missing += ln.name.ifBlank { "（未命名商品）" }
                    lines.add(
                        LineDraft(
                            productId = ln.productId,
                            // 商品还在库里就用**当前**名字（预设单里那份是显示用快照）
                            name = p?.name ?: ln.name,
                            quantity = ln.qty,
                            price = p?.let { priceFor(it) } ?: "",
                            unit = p?.unit?.ifBlank { null } ?: ln.unit.ifBlank { "件" },
                        ),
                    )
                }
                appliedTemplateId = t.id
                toast = buildString {
                    append("已按预设单「").append(t.name).append("」填好商品与数量，请核对后再提交")
                    if (missing.isNotEmpty()) {
                        // ⛔ 不静默：商品下架/删掉的那几行**没有价**，必须说出来。
                        // ⛔ 而且**不许**写成"价格要自己填"（2026-09-22 修）：下单页根本没有单价输入框
                        //    （红线 `_check_input_rules.py::NO_PRICE_EDIT_FILES`），那是一条用户
                        //    照做不了的假话 —— 他能做的只有删掉这一行，或让派单员把商品恢复回来。
                        append("（").append(missing.joinToString("、"))
                            .append(" 已不在商品库，这一行删掉才能下单）")
                    }
                    // ⛔ **报价依据不写在这里**（2026-09-22 真机抓到）：横幅是一句话的**回执**，
                    //    写完就定住了，而"按谁的价算"是**实时状态**（换了货主就变）。
                    //    两处都写 → 同屏会同时出现"按商品默认售价"与"按「永盛食品」的专属价"
                    //    两句互相打架的话。它只有一处：商品明细下面那行（[priceBasisText]）。
                }
                onDone(null)
            } catch (e: Exception) {
                onDone(toApiException(e).message)
            }
        }
    }

    /**
     * 这一批商品的**报价依据**（一句话；商品明细那里常驻显示，预填提示也复用这一句）。
     *
     * 为什么要有它（2026-09-22 用户报的错价）：价**算错了界面上看不出来** ——
     * 20 和 10 都只是一个"看起来正常的价"。把依据写在用户正在看的那个位置，
     * 他在按提交之前就能看出这次走的是默认价还是谈好的专属价，不必去比对记忆里的数字。
     * （原来这句只挂在预填的 `toast` 上，而那个 toast 的**唯一渲染点在地址抽屉的
     *  "已存进共享库"那一小块里** —— 也就是说用户实际上从来没看见过它。）
     *
     * ⛔ 它是**数据/状态**（跟着当前主体与规则实时变），所以界面用 `Text` 显示、
     *    不走 `Hint` 那个总开关 —— 关掉提示不该把"这批货按谁的价算"一起关掉。
     */
    fun priceBasisText(): String {
        if (lines.isEmpty()) return ""
        val who = shippers.firstOrNull { it.id == shipperId }?.fullName ?: "这个货主"
        val subject = shipperId ?: myShipperId
        if (subject != null && priceRulesShipper != subject) {
            // 还没拿到 ≠ 没有专属价：这一句是"正在进行"，不是结论（提交那道闸门也在等它）
            return if (shipperId != null) "价格正在核对（还没拿到「$who」的专属价）" else "价格正在核对…"
        }
        if (shipperId == null) return "价格按商品默认售价"
        val special = lines.count { ln -> ln.productId?.let { priceRules[it] != null } == true }
        return when {
            special == 0 -> "价格按商品默认售价"
            special == lines.size -> "价格按「$who」的专属价"
            else -> "其中 $special 行按「$who」的专属价，其余按默认售价"
        }
    }

    /**
     * 按下单主体（选择的货主，否则当前登录人）加载其专属价格规则。
     *
     * ⚠️ **拿到规则之后必须重算清单里已有的行**（[repriceFromRules]）：单价只在"挑商品的那一刻"
     *    算一次的话，先挑后换货主会把**上一个货主**的价留在行上（2026-09-22 用户报的那类错价）。
     */
    fun loadPriceRulesFor(sid: Long?) {
        if (sid == null) {
            priceRulesJob = null
            priceRules = emptyMap()
            priceRulesShipper = null
            // 主体成了"没有价规则的人"（临时货主 / 会话还没读到）→ 行上留着的专属价必须放掉
            repriceFromRules()
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
        priceRulesJob = viewModelScope.launch {
            // 只取**这个下单主体**的专属价（服务端筛，不是拉全表再 filter —— 2026-09-19 修）：
            // 原来这里每换一次主体就要下载所有批发商 × 所有商品的价格。
            applyPriceRules(sid, fetchPriceRules(sid))
        }
    }

    /**
     * 拉某个下单主体的专属价 —— **唯一一份取数**（[loadPriceRulesFor] 与预订单预填共用）。
     *
     * @return **null = 没拿到**（网络失败）。⛔ 失败**不许**退化成"空 map"：那等于对外宣称
     *   "这个货主没有专属价"，而真相是"我们还不知道" —— 两者在钱上的后果完全相反
     *   （前者按默认价下单＝对谈好价的批发商**多收钱**）。
     */
    private suspend fun fetchPriceRules(sid: Long): Map<Long, PriceRuleDto>? = try {
        container.repo.priceRules(sid).associateBy { it.productId }
    } catch (_: Exception) {
        loadingProducts = false   // 失败也要收尾，别让界面永远停在"加载中"
        null
    }

    /**
     * 把拉到的那份规则落到状态上（**唯一写入点**）。
     *
     * @param loaded null = 没拿到 → **什么都不写**（`priceRulesShipper` 保持"未知"，
     *   提交那道闸门就会拦住这一单，而不是按默认价把单发出去）。
     */
    private fun applyPriceRules(sid: Long, loaded: Map<Long, PriceRuleDto>?) {
        // 请求回来时主体又被换过就别写了（`priceRulesShipper` 已经指到新主体）
        if (shipperId != sid && !(shipperId == null && myShipperId == sid)) return
        if (loaded == null) return
        priceRules = loaded
        priceRulesShipper = sid
        repriceFromRules()
    }

    /**
     * 等"当前下单主体的专属价"**到齐**——预订单预填必须在填行之前等它。
     *
     * 不等的话就是在赌"请求比这一行代码快"：`setShipper` 只是**发起**取数，
     * 紧接着读 `priceFor` 拿到的必然是"规则还没到"的回退价（默认价），
     * 而已经填好的行**不会**因为规则随后到达而重新算 —— 这就是用户量到的那个错价。
     *
     * 等完"是不是真的拿到了"不用返回值往外传：界面看 [priceBasisText]（它会如实说"正在核对"），
     * 钱则由 [submit] 那道闸门把住。
     */
    private suspend fun awaitPriceRules() {
        priceRulesJob?.join()
        val subject = shipperId ?: myShipperId ?: return
        if (priceRulesShipper != subject) applyPriceRules(subject, fetchPriceRules(subject))
    }

    /**
     * 把清单里已有的行按**当前主体的价**重算一遍（唯一实现是纯函数 [repriceLines]）。
     *
     * 两处调用它：① 规则到齐 / 主体换了（[applyPriceRules]）；② 主体成了没有规则的人
     * （临时货主、清空选择 —— 与账本记账页同一条教训：不重算就会停在上一个货主的价上）。
     */
    private fun repriceFromRules() {
        val (next, changed) = repriceLines(lines) { pid ->
            products.firstOrNull { it.id == pid }?.let { priceFor(it) }
        }
        if (changed == 0) return
        lines.clear()
        lines.addAll(next)
    }

    /**
     * 选择商品时的实际单价：有批发商专属价用特价，否则默认售价。
     *
     * ⚠️ 只认**当前下单主体**那份规则：`priceRulesShipper` 对不上就回退默认价。
     *    ⛔ 但要说清这个回退的**真实含义**（2026-09-22 改口，旧注释写的是"少赚"，那是错的）：
     *    `priceRulesShipper` 对不上**不等于**"这个货主没有专属价"，而是"**我们还不知道**"。
     *    对谈好了专属价的批发商按默认价报价，是**多收他的钱** —— 不是少赚。
     *    所以这个回退只在"规则在路上"的窗口里出现，并且有两道兜底：
     *    ① 规则到齐时 [repriceFromRules] 把已填好的行重算回来；
     *    ② 一直没到（网络失败）时 [submit] 的报价闸门**拒绝下单**。
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
        // 地图上自己选的点**不是**库里的哪一条 → 两个 id 都清掉（不许把上一次选的线路
        // 记到这一次头上：那会把"常用度"记到一条这次根本没用过的记录上）
        pickedAddressId = null
        pickedLocationId = null
        showMapPicker = false
        placeSaved = false
    }

    fun applyAddress(a: AddressDto) {
        addressDetail = a.detailAddress
        addressLat = a.addressLat
        addressLng = a.addressLng
        dongjiaPhone = a.phone
        // ⚠️ 名字只在**这条线路真的填了收货人**时才覆盖：`receiver_name` 在老线路上可能是空的，
        //    那种时候把用户刚敲进去的名字清掉，比"不自动填"更糟。电话沿用原来的行为不动。
        if (a.receiverName.isNotBlank()) dongjiaName = a.receiverName
        // 记下"这一单用的是哪条线路"：下单时随单交给后端记一次常用度
        // （用户 2026-09-22：「下单时经常用到的联系人……用得越多越往前」）。
        // ⚠️ 手输地址 / 地图选点不会走到这里 —— 那种情况 `picked*Id` 保持为空，后端就不计分。
        pickedAddressId = a.id
        pickedLocationId = null
        showAddressSheet = false
        placeSaved = false
    }

    /**
     * 把「下单人」自动填成 [fullName] / [phone]（＝**当前登录账号本人**）。
     *
     * ⚠️ 只有**货主自己下单**那一支会走到这里（代理下单走 [applyOrdererFromShipper]：
     *    派单员不许把自己的姓名/电话留在这一单上）。
     * ⚠️ 两个"不覆盖"：字段已经有人填过就不动（`sessionFlow` 是 DataStore 冷流，
     *    这个回填是**异步**落到界面上的，落下时用户可能已经在打字了）。
     */
    fun prefillOrdererFromSelf(fullName: String?, phone: String?) {
        writeOrderer(
            ordererContactFor(fullName, phone, proxyMode = false, shipper = null, tempShipperName = null),
            onlyWhenBlank = true,
        )
    }

    /**
     * 写「下单人」两栏 —— **唯一**的落笔点（[prefillOrdererFromSelf] 与 [applyOrdererFromShipper] 都走它）。
     *
     * @param onlyWhenBlank 只在空栏时填。账号预填那一支要它（异步回包别盖掉用户刚打的字）；
     *   换货主那一支**不要**它 —— 换了货主还留着上一位的姓名/电话，就是一张归属错人的单。
     */
    private fun writeOrderer(c: OrdererContact, onlyWhenBlank: Boolean = false) {
        if (!onlyWhenBlank || bossName.isBlank()) bossName = c.name
        if (!onlyWhenBlank || bossPhone.isBlank()) bossPhone = c.phone
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
        // 记下"这一单用的是我地点库里的哪一条"（下单时交给后端记常用度）
        pickedLocationId = l.id
        pickedAddressId = null
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
        /**
         * 没有价的那一行（商品已不在商品库 = 预设单里那件货后来下架/删掉了）。
         *
         * ⛔ 不能让这种行发出去：后端 `unit_price` 是数字，空字符串会变成一个**用户看不懂的
         *    422 结构体**；而且页面上根本没有填价的地方（见 [priceSourceNote] 那段注释）。
         */
        val noPrice = lines.firstOrNull { it.price.isBlank() }
        // 电话格式先在这一侧挡一道：这两个框现在只让数字进来（`InputRules.phoneInput`），
        // 但"位数不够"过滤挡不住（用户可能刚输了一半就点提交）。在这里拦下来，
        // 用户看到的是**立刻**的中文提示，而不是等服务端 422 转一圈。
        // ⚠️ 两个电话都是**可选**的（不要顺手把它们改成必填 —— 那是产品决定，不是修 bug）。
        val phoneError = InputRules.phoneError(dongjiaPhone.trim())
            ?: InputRules.phoneError(bossPhone.trim())
        when {
            lines.isEmpty() -> error = "请至少添加一组商品"
            nameBlank -> error = "商品名称不能为空"
            noPrice != null -> error = "「${noPrice.name}」没有价格（这件商品已不在商品库），先删掉这一行再提交"
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
                        // ⚠️ **报价闸门**：还没拿到"这个下单主体的价"就不许下单（2026-09-22）。
                        //    回退到默认价对"谈好了专属价的批发商"＝**多收他的钱**，而且订单/小票/
                        //    账本三处会一致地错（事后无从发现）—— 静默错钱比挡一下严重得多。
                        //    挡的同时**再拉一次**，用户再点一下就成了（失败时 `priceRulesShipper`
                        //    停在"未知"，所以这一条不会因为一次网络抖动永久卡住）。
                        val subject = shipperId ?: myShipperId ?: s?.userId
                        if (subject != null && priceRulesShipper != subject) {
                            loadPriceRulesFor(subject)
                            error = "价格还没拿到（网络慢或断了），请再点一次提交"
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
                            contactDongjiaName = dongjiaName.trim(),
                            contactBossName = bossName.trim(),
                            remark = remark.trim(),
                            shipperId = shipperId,
                            tempShipperName = tempShipperName,
                            // 「这一单用的是库里哪一条」→ 后端据此记常用度（列表排序用）
                            addressId = pickedAddressId,
                            locationId = pickedLocationId,
                        )
                        val created = container.repo.createOrder(body)
                        draftAddressImages.forEach { path ->
                            runCatching {
                                val f = java.io.File(path)
                                if (f.exists()) container.repo.uploadOrderAddressImage(created.id, f)
                            }
                        }
                        success = true
                        // 「用这张预设单下了单」→ 记一次常用度（列表按它往前排）。
                        // ⚠️ 记在**下单成功之后**、不是点「用这张下单」的时候：点了又退出去的不算，
                        //    否则列表会按"谁点开过"排序（而用户要的是"我常用哪一张"）。
                        appliedTemplateId?.let { tid ->
                            runCatching { container.repo.useOrderTemplate(tid) }
                        }
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