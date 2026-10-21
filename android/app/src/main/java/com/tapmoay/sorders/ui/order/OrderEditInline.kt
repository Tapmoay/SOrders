package com.tapmoay.sorders.ui.order

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Event
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Place
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.Capabilities
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import com.tapmoay.sorders.ui.common.ContactPickerSheet
import com.tapmoay.sorders.ui.common.deliveryDateDisplay
import com.tapmoay.sorders.ui.common.deliveryDateSelectable
import com.tapmoay.sorders.ui.dispatcher.isoDateOfMillis
import com.tapmoay.sorders.ui.dispatcher.isoDateToMillis
import com.tapmoay.sorders.ui.common.FormErrorLine
import com.tapmoay.sorders.ui.common.FormInputRow
import com.tapmoay.sorders.ui.common.FormTextAreaRow
import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.shipper.HereResult
import com.tapmoay.sorders.ui.shipper.hereResultOf
import kotlinx.coroutines.delay

/**
 * 订单详情页「点哪块信息就改哪块」（CHG-0041）。
 *
 * ## 用户要的形态（2026-10-05 口述）
 * > 「我们的编辑页面，他的详订单详情页面不是有那么多信息吗……**点击对应的 ui 信息就
 * >   可以对应进行编辑**啊，是这样子的」
 *
 * ⛔ 所以这里**不是**另一个"编辑订单"界面，也不是弹层：信息还摆在原来的位置上，
 * 点一下就**就地**变成输入框，改完点「保存」再变回信息。
 *
 * ## 为什么把状态收成一个接口（而不是给 `DetailBody` 加二十个参数）
 * 就地编辑要带进组合函数的东西有两类：**六个草稿值**（地址 / 收货人姓名电话 / 下单人
 * 姓名电话 / 备注）与**一组动作**（开、关、存、删一行货）。`DetailBody` 当时的参数表
 * 已经有 30 个（见 `OrderDetailScreen.kt` 里那段签名），再摊平加进去就没人读得懂了。
 * 收成一个 [OrderEditHost] 之后，整套东西进 `DetailBody` 只占**一个参数**。
 *
 * `OrderDetailViewModel` 直接实现这个接口（成员加 `override`），界面侧只认得接口。
 *
 * ## 这一层改的是什么、不是什么
 * - ✅ 收货地址 / 收货人（姓名 + 电话）/ 下单人（姓名 + 电话）/ 备注 / 货物明细（改数量单价、删一件、加一件）
 * - ⛔ **货主归属**不在这一层（那是改账，不是改单）
 * - ⛔ **订单状态**不在这一层（用户没有要状态改写；生命周期的跃迁仍然只走既有那几个动作按钮）
 * - ⛔ 改完**只通知司机**（后端 `orders.update_order` → `outbox "orders.edited"`），
 *   货主端一个字都不出 —— 那是用户 2026-10-05 明确定的口径，界面上的提示语也照这个说。
 */
interface OrderEditHost {

    /** 正在就编辑的那一块（null = 没在编辑）。取值见 [OrderEditField]。 */
    val editingField: String?

    /** 上一次改动失败的原因（就地显示在编辑块下面，**不换整页**）。 */
    val editError: String?

    /** 一次改动进行中：防连点（连点两次会改两遍，司机也会收到两条消息）。 */
    val editBusy: Boolean

    /** 读一个草稿值（键见 [OrderEditField] 的那几个常量）。 */
    fun draft(key: String): String

    /** 改一个草稿值。 */
    fun setDraft(key: String, value: String)

    /** 开始就编辑 [field] 那一块（会先把它那一组的值铺成这一单现在的值）。 */
    fun startEdit(field: String)

    /** 收起编辑块，丢弃草稿。 */
    fun cancelEdit()

    /** 存这一个编辑块（地址/收货人/下单人/备注 一起报，内部备注原样带回）。 */
    fun saveEdit()

    // ---- 改「地点信息」走地点库 / 地图 / 「我就在这里」（CHG-0133）----

    /**
     * 拿容器。
     *
     * 为什么要在接口上开这一格：定位管道（`container.locationManager`）与共用弹层要的东西
     * 只有容器里有，而 [AddressEditBlock] 手上只有这个接口。⛔ 全仓没有 `LocalAppContainer`
     * 这样的 CompositionLocal（唯一的 Local 是 `ui/common/Hints.kt::LocalHints`），
     * 所以"就地编辑"这一层要拿到容器，只能从这里过。
     */
    val appContainer: AppContainer

    /**
     * 要求把**地点库抽屉**打开（线路 / 我的地点 / 共享地点）。
     *
     * 弹层本体挂在**屏级**（与下单页、地址页**同一份** `ui/shipper/OrderCreateScreen.kt`
     * 的 `AddressPickerSheet`）；这一层只负责"能要求把它打开"—— 与 [openLinePicker]
     * 对选品弹层是同一条口径（那一份的注释把理由写全了：抽屉要盖住整页，坐进卡片里就成了
     * "弹层里再弹一层"，而且详情页那个 LazyColumn 滚动时会把它连人带框一起回收）。
     */
    fun openAddressLibrary()

    /** 要求把**地图选点**弹层打开（`ui/common/AmapPicker.kt::AmapPickerDialog`，全库同一份）。 */
    fun openAddressMap()

    /**
     * 选好一个点：**坐标与地址一起**落进草稿（保存时才写库）。
     *
     * ⚠️ 落草稿而不是直接写库：这一块的规矩是"改完点保存才生效"（见 [saveEdit]）——
     *    选点选到一半反悔，点「取消」就该什么都不留。
     */
    fun applyPickedCoord(lat: Double, lng: Double, address: String)

    /**
     * 一句"坐标会不会被误读"的话（null = 没什么要说的），画在坐标下面。
     *
     * 要盯的是**最难自查**的那一种：地址文字改了、坐标还是原来那个点 —— 界面上看起来"改好了"，
     * 而司机照坐标走，去的还是**上一个地方**。话由 VM 说（它才同时握着"原来那一单"与草稿），
     * 界面只负责画出来 —— 与 [editError] 同一条分工。
     */
    val addressCoordNotice: String?

    // ---- 改一件货（数量 / 单价 / 删掉）----

    /** 正在就编辑的那一行货（行的 `id`，null = 没在编辑）。 */
    val editingLineId: Long?

    val lineQty: String
    val linePrice: String

    // ⚠️ 这两个**不能叫 `setLineQty` / `setLinePrice`**：上面两个 `val` 在 VM 里是
    //    `override var`，那个属性自带的 JVM setter 正好就叫这两个名字 —— 同名同签名
    //    编译期直接 `Platform declaration clash`（2026-10-05 第一版就是这么红的）。
    fun updateLineQty(value: String)
    fun updateLinePrice(value: String)

    /** 点某一行货 → 就地改它的数量与单价。 */
    fun startLineEdit(line: OrderProductDto)

    fun cancelLineEdit()

    fun saveLine()

    /** 删掉这一行货（后端把它从这一单里去掉，货主那边的账跟着变）。 */
    fun deleteLine()

    // ---- 加一件货 ----

    /**
     * 打开「挑几件货」的选品弹层（挑完由 [addPickedLines] 逐行报给后端）。
     *
     * 弹层本体挂在**屏级**（`OrderDetailScreen`，与派单池、下单页**同一个**
     * `ui/common/ProductPicker.kt`）—— 详情页这一层只需要"能要求把它打开"。
     */
    fun openLinePicker()

    // ---- 补联系信息（L-27 / CHG-0057）—— 货主那一扇门 ----

    /**
     * 「从联系人里选」那个弹层开着吗。
     *
     * 零件与下单页**同一个**（`ui/common/ContactPickerSheet.kt`）：用户 2026-10-06（m01132）
     * 说的就是"他可以去调用他自己的那个收货人列表，也可以新建一个收货人……这些代码是可以复用的"。
     */
    val showContactSheet: Boolean

    /** 自己的联系人名册（弹层里那一列）。 */
    val contacts: List<ContactDto>

    /**
     * 「我自己」那一行（当前登录人；CHG-0117）。
     *
     * 构造与取数都只在一处：`ui/common/SelfContact.kt`。拿不到姓名或电话时是 null
     * ⇒ 弹层里不出现这一项（⛔ 这里不许自己拼一个 `ContactDto`）。
     */
    val selfContact: ContactDto?

    /** 名册拉失败的原因（只写在弹层里，⛔ 不换整页）。 */
    val contactsError: String?

    val loadingContacts: Boolean

    /** 「新建联系人」进行中。 */
    val creatingContact: Boolean

    /** 新建联系人失败的原因（就地写在新建对话框里）。 */
    val contactSaveError: String?

    /** 打开选人弹层（顺手刷新一遍名册）。 */
    fun openContactSheet()

    fun closeContactSheet()

    /** 重新拉一遍名册。 */
    fun loadContacts()

    /** 挑中一位 → 填进**收货人**那一组（换人就是换人，整对替换）。 */
    fun pickContactForDongjia(c: ContactDto)

    /** 在弹层里现建一位联系人，建成后直接选中。 */
    fun createContactAndPick(name: String, phone: String)
}

/**
 * 可点改的那几块，以及草稿表的键。
 *
 * 键名**照抄 `OrderUpdateRequest` 的字段名**（`addressDetail` 那几个）：改一处口径时
 * 两边对得上名，比另起一套「addr1 / telA」之类的名字安全得多。
 */
object OrderEditField {
    /** 收货地址（一整块）。 */
    const val ADDRESS = "address"

    /** 收货人那一组（姓名 + 电话一起改）。 */
    const val DONGJIA = "contactDongjia"

    /** 下单人那一组（姓名 + 电话一起改）。 */
    const val BOSS = "contactBoss"

    /** 备注。 */
    const val REMARK = "remark"

    /**
     * 补联系信息那一整块（L-27 / CHG-0057）—— **货主**那一扇门。
     *
     * ⛔ 与上面四块不是同一扇门：这一块只报四个联系字段，走 `PATCH /orders/{id}/contact`
     * （权限点 `order:edit_contact`，只给货主、scope=own）；上面四块归派单员（`canEditInfo`）。
     * 这也是为什么详情页那四颗「改」（[EditHint]）一个字都不用动 —— 既有判据钉死了它们的条数。
     */
    const val CONTACT = "contact"

    const val ADDRESS_DETAIL = "addressDetail"

    /**
     * 收货地址的**坐标**（CHG-0133）。
     *
     * 键名照抄 `OrderUpdateRequest.addressLat / addressLng`（与上面那一串同一条规矩）。
     * ⚠️ 它俩不是"地址的附属品"，而是**司机最终照着走的那个点**：只改文字、没落坐标，
     *    司机手上的还是老坐标 —— 这也是为什么这一块要把它们摆在脸上（见 [AddressEditBlock]）。
     */
    const val ADDRESS_LAT = "addressLat"
    const val ADDRESS_LNG = "addressLng"
    const val DONGJIA_NAME = "contactDongjiaName"
    const val DONGJIA_PHONE = "contactDongjiaPhone"
    const val BOSS_NAME = "contactBossName"
    const val BOSS_PHONE = "contactBossPhone"
    const val REMARK_TEXT = "remark"
    /**
     * 送达日期（CHG-0135）：派单员在订单详情里改"哪天送到"。
     * 走的是同一条 PATCH（[OrderEditHost.saveEdit]），⛔ 不另开一扇门。
     */
    const val DELIVERY_DATE = "deliveryDate"
}

/**
 * 行尾那颗「改」（只给改得动的人画）—— 2026-10-08 用户点名：**换成铅笔图标**。
 *
 * ## 为什么原来是字、现在是图标（CHG-0125）
 * 从前这里用「改」字，理由是「这一页把信息行与动作分得很清：收货人/下单人那两行的点击已经是
 * **拨号**，行尾再摆一个没有文字的图标，用户分不清点哪个是拨号、哪个是改」（CHG-0041 的注释）。
 * 用户看过真机之后仍要铅笔 —— 于是分工改由**位置**承担：行首那条细竖杠（见 [EditRail]）
 * 说的是「这一行改得动」，行尾这支铅笔说的是「点这里开始改」。各有各的记号，不再靠文字区分。
 *
 * ⛔ 签名与四个调用点一个字节都没动：`label` 仍是中文「改」，它现在的角色是**无障碍描述**
 *    （TalkBack 念出来的还是「改」）。
 * ⛔ 点击行为一个字节都没动：还是自己带 `clickable`，热区＝图标＋padding（不是整行）。
 * ⛔ 铅笔用库里既有的 `Icons.Default.Edit`（32 处在用），没有引入任何新图标依赖。
 */
@Composable
fun EditHint(onClick: () -> Unit, label: String = "改") {
    Icon(
        Icons.Default.Edit,
        contentDescription = label,
        tint = MaterialTheme.colorScheme.primary,
        modifier = Modifier
            .clickable(onClick = onClick)
            .padding(horizontal = 8.dp, vertical = 4.dp)
            .size(18.dp),
    )
}

/**
 * 行首那条细竖杠：**这一行改得动**（CHG-0125）。
 *
 * 用户配着详情页截图的原话：「可以改的行，在行首图标前面加一条细竖杠（颜色沿用详情页已有的
 * 语义色/主题色；只显示、不可点击，不能新增可点区域）」。
 *
 * ⛔ 这个组件里**不许出现 clickable / onClick / 任何按钮**：它只显示。有些行本来就整行可点
 *    （地点行＝看地图、收货人/下单人行＝拨号），那是**原来就有的**热区，这里一个像素都不加。
 * ⛔ 颜色与行尾那支铅笔**同一个来源**（主题色 primary）：同一件事的两半，颜色一分叉，
 *    用户会以为它们是两个功能。
 * ⛔ 与行首图标之间的固定间距由**本组件自己带**（padding end 8dp）：调用点只加一行裸调用，
 *    间距不写在调用点上（四处各写一次＝迟早有一处不一样）。
 */
@Composable
fun EditRail(modifier: Modifier = Modifier) {
    Box(
        modifier
            .padding(end = 8.dp)
            .width(3.dp)
            .height(18.dp)
            .background(MaterialTheme.colorScheme.primary),
    )
}

/** [AddressEditBlock] 那颗「我就在这里」的兜底时限（CHG-0133）。 */
private const val DETAIL_HERE_TIMEOUT_MS = 20_000L

/**
 * 收货地址：一个多行框 ＋ 三颗改地点的入口 ＋ 坐标那一行。
 *
 * ## 为什么这一块不再只是「一个多行框」（CHG-0133，2026-10-15 用户点名）
 * 从前这里只能**手打文字**：派单员在电话里听到一个新地址就照念一遍 —— 而**司机是按坐标走的**。
 * 文字换了、坐标没人动，司机照旧开去**上一个点**（详情页那张只读地图与司机端导航都是按坐标）。
 * 用户要的形态：改地点**改走地点库**（线路 / 我的地点 / 共享地点）／**在地图上选一个点**／
 * **「我就在这里」**；并且**订单要落坐标**。
 *
 * ## 与下单页是同一套零件、同一句话（⛔ 不要另起第二套）
 * 三颗按钮的形状、图标与文案逐字照抄 `ui/shipper/OrderCreateScreen.kt:406-440`；两个弹层也是
 * **共用件本体**（`ui/common/AmapPicker.kt::AmapPickerDialog` 与
 * `ui/shipper/OrderCreateScreen.kt::AddressPickerSheet`）—— 它们由**屏级宿主**挂上去
 * （见 [OrderEditHost.openAddressLibrary] / [OrderEditHost.openAddressMap]）：抽屉要盖住整页，
 * 坐进这张卡里就成了"弹层里再弹一层"，而且详情页那个 LazyColumn 滚动时会把它连人带框一起回收。
 *
 * ## 坐标摆到脸上
 * 后端 `PATCH /orders/{id}`（`backend/app/commands/order.py:405-410`）是"**不给就不改**"：
 * 只改文字、坐标原样留在库里 —— 那就成了**错坐标**，比没坐标更糟（`orders_delivery.py` 里
 * 同一句裁定）。所以这一块把坐标画出来："没坐标"当场说（橙），"文字改了、坐标没动"这种
 * **最难自查**的情况由 [OrderEditHost.addressCoordNotice] 那句话点名。
 *
 * ## 定位回流只认**自己发起的那一次**
 * 「地图选点」那个弹层**一打开就会自己发一次定位**（`ui/common/AmapPicker.kt`）。不设闸的话，
 * 用户点开地图、还没点任何地方，地址就被悄悄改了 —— 两处都不报错。所以 collect 第一行就是
 * `if (!locatingHere) return@collect`（与 `ui/shipper/AddressScreen.kt:203-212` 同一道闸）。
 */
@Composable
fun AddressEditBlock(edit: OrderEditHost, modifier: Modifier = Modifier) {
    val container = edit.appContainer
    val context = LocalContext.current
    var locatingHere by remember { mutableStateOf(false) }
    var locateHereError by remember { mutableStateOf<String?>(null) }

    /**
     * 发起一次单次定位。
     *
     * `requestSingle()` 返回 false = **连发起都没成功**（权限缺失 / SDK 起不来）—— 那种情况
     * **一个回调都不会有**，必须当场收尾，否则按钮永远停在「正在定位…」
     * （下单页那颗没接这个返回值，是它的已知形状；这与地址页那颗一样，不重复那个坑）。
     */
    fun requestHere() {
        locatingHere = true
        if (!container.locationManager.requestSingle()) {
            locatingHere = false
            locateHereError = "定位没启动起来：请检查定位权限，或改用「在地图上选点」。"
        }
    }

    val herePermLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants.values.any { it }) {
            requestHere()
        } else {
            locatingHere = false
            locateHereError = "没有定位权限，拿不到当前位置。"
        }
    }

    /** ⛔ 取点路径**全 App 只有一条**：`container.locationManager`；⛔ 不许退到 `DeviceLocation`（WGS84，国内偏几百米）。 */
    fun locateHereNow() {
        val perms = arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        if (!perms.all { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }) {
            herePermLauncher.launch(perms)
            return
        }
        requestHere()
    }

    LaunchedEffect(Unit) {
        container.locationManager.locations.collect { pt ->
            if (!locatingHere) return@collect
            locatingHere = false
            // ⛔ 高德**失败时照常回调**，给的是 `(0,0)` —— 那不是"就在几内亚湾"，是"没拿到"。
            //    闸与话都在全仓唯一那份 `hereResultOf` 里（`ui/shipper/AddressViewModel.kt:105`，
            //    内含 `SunLocation.isPlausible`）：界面**不重复判一遍**，也不许自己填一个假地址。
            when (val r = hereResultOf(pt.lat, pt.lng, pt.address)) {
                is HereResult.Fill -> {
                    locateHereError = null
                    edit.applyPickedCoord(r.lat, r.lng, r.address)
                }
                is HereResult.Say -> locateHereError = r.message
            }
        }
    }

    // 兜底：等不到任何回调就自己收尾 —— 「拿不到就如实说一句中文」**不包括**"永远停在正在定位…"。
    LaunchedEffect(locatingHere) {
        if (!locatingHere) return@LaunchedEffect
        delay(DETAIL_HERE_TIMEOUT_MS)
        if (locatingHere) {
            locatingHere = false
            locateHereError = "定位超时，没拿到当前位置：请重试，或改用「在地图上选点」。"
        }
    }

    val latDraft = edit.draft(OrderEditField.ADDRESS_LAT).trim()
    val lngDraft = edit.draft(OrderEditField.ADDRESS_LNG).trim()

    Column(modifier.fillMaxWidth()) {
        EditBox(
            label = "收货地址",
            value = edit.draft(OrderEditField.ADDRESS_DETAIL),
            onValue = { edit.setDraft(OrderEditField.ADDRESS_DETAIL, it) },
            minLines = 2,
            singleLine = false,
        )
        // 下面三颗＝同一层的三个选择（手动选点 / 从库里挑 / 就在这儿），
        // 与下单页那张「收货地址」卡逐字一致（`OrderCreateScreen.kt:406-440`）。
        Spacer(Modifier.height(10.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(
                onClick = { locateHereError = null; edit.openAddressMap() },
                enabled = !edit.editBusy,
                modifier = Modifier.weight(1f),
            ) {
                Icon(Icons.Default.Place, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("地图选点")
            }
            OutlinedButton(
                onClick = { locateHereError = null; edit.openAddressLibrary() },
                enabled = !edit.editBusy,
                modifier = Modifier.weight(1f),
            ) {
                Icon(Icons.Default.List, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
                Text("地址库")
            }
        }
        Spacer(Modifier.height(10.dp))
        OutlinedButton(
            onClick = { locateHereError = null; locateHereNow() },
            enabled = !locatingHere && !edit.editBusy,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Icon(Icons.Default.Place, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text(if (locatingHere) "正在定位…" else "我就在这里")
        }
        locateHereError?.let { msg ->
            Spacer(Modifier.height(6.dp))
            Text(
                msg,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
        Spacer(Modifier.height(8.dp))
        if (latDraft.isBlank() || lngDraft.isBlank()) {
            // 与下单页同一句、同一个橙（"这里还缺一样东西"）。
            Text(
                "还没选坐标",
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFFF59C00),
            )
        } else {
            Text(
                "坐标：$latDraft，$lngDraft",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        edit.addressCoordNotice?.let { msg ->
            Spacer(Modifier.height(6.dp))
            Text(
                msg,
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFFF59C00),
            )
        }
        EditActions(
            error = edit.editError,
            busy = edit.editBusy,
            saveLabel = "保存地址",
            onSave = { edit.saveEdit() },
            onCancel = { edit.cancelEdit() },
        )
    }
}

/**
 * 收货人 / 下单人：**姓名与电话一起改**。
 *
 * 为什么成组：收货人那一行显示的是「姓名 + 电话」拼起来的一串（`contactWho`），
 * 只改电话会让那一行半新半旧；而后端本来就是一条 `PATCH` 收这两个字段。
 */
@Composable
fun ContactEditBlock(
    edit: OrderEditHost,
    title: String,
    nameKey: String,
    phoneKey: String,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        Text(title, style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.height(6.dp))
        EditBox(
            label = title + "姓名",
            value = edit.draft(nameKey),
            onValue = { edit.setDraft(nameKey, it) },
        )
        Spacer(Modifier.height(8.dp))
        EditBox(
            label = title + "电话",
            value = edit.draft(phoneKey),
            // 电话只让数字进来（规则唯一实现在 core/InputRules.kt，⛔ 别在界面里另写一遍过滤）
            onValue = { edit.setDraft(phoneKey, InputRules.phoneInput(it)) },
            keyboard = KeyboardType.Phone,
        )
        EditActions(
            error = edit.editError,
            busy = edit.editBusy,
            saveLabel = "保存" + title,
            onSave = { edit.saveEdit() },
            onCancel = { edit.cancelEdit() },
        )
    }
}

/**
 * 补联系信息（L-27 / L-28 / CHG-0057）—— 货主那一扇门。
 *
 * ## 为什么单独摆一块，而不是复用上面那两颗「改」
 * 上面那些块归**派单员**（详情页里的 `canEditInfo`），而且收货人 / 下单人那两行在两个名字
 * **都空**的时候根本不画（`dongjiaWho != null || canEditInfo`）—— 偏偏"两个名字都空"正是
 * 这一块要修的那种单。所以货主这一扇门得自己有一块看得见的界面。
 *
 * ## 它报什么、走哪条路
 * 只报**四个联系字段**（收货人姓名/电话、下单人姓名/电话），走 `PATCH /orders/{id}/contact`
 * （权限点 `order:edit_contact`，只给货主、scope=own）。地址 / 备注 / 内部备注一个字都不报，
 * 多报一个别的字段后端会退回（403）—— 那扇门不是拿来改单的，是拿来把"账上认不出人"补齐的。
 *
 * ⛔ **两个名字至少填一个**：后端算「账上认不出人」看的就是这两个**姓名**（只填电话不算），
 * 只填电话再保存，那条红标还会在。
 */
@Composable
fun ContactFillPanel(edit: OrderEditHost, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth()) {
        Text("补联系信息", style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.height(6.dp))
        Text(
            "这单账上认不出人：收货人与下单人都没填名字，核销时不能归到谁头上（会变成无主账）。" +
                "两个名字至少填一个 —— 收货人是到场接货的人，下单人是下这一单的人。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        TextButton(onClick = { edit.openContactSheet() }, enabled = !edit.editBusy) {
            Text("从联系人里选收货人")
        }
        Spacer(Modifier.height(4.dp))
        EditBox(
            label = "收货人姓名",
            value = edit.draft(OrderEditField.DONGJIA_NAME),
            onValue = { edit.setDraft(OrderEditField.DONGJIA_NAME, it) },
        )
        Spacer(Modifier.height(8.dp))
        EditBox(
            label = "收货人电话",
            value = edit.draft(OrderEditField.DONGJIA_PHONE),
            // 电话只让数字进来（规则唯一实现在 core/InputRules.kt，⛔ 别在界面里另写一遍过滤）
            onValue = { edit.setDraft(OrderEditField.DONGJIA_PHONE, InputRules.phoneInput(it)) },
            keyboard = KeyboardType.Phone,
        )
        Spacer(Modifier.height(8.dp))
        EditBox(
            label = "下单人姓名",
            value = edit.draft(OrderEditField.BOSS_NAME),
            onValue = { edit.setDraft(OrderEditField.BOSS_NAME, it) },
        )
        Spacer(Modifier.height(8.dp))
        EditBox(
            label = "下单人电话",
            value = edit.draft(OrderEditField.BOSS_PHONE),
            onValue = { edit.setDraft(OrderEditField.BOSS_PHONE, InputRules.phoneInput(it)) },
            keyboard = KeyboardType.Phone,
        )
        EditActions(
            error = edit.editError,
            busy = edit.editBusy,
            saveLabel = "保存联系信息",
            onSave = { edit.saveEdit() },
            onCancel = { edit.cancelEdit() },
        )
    }
    // 选人弹层挂在这一块里：它只在这块打开时才有意义。
    if (edit.showContactSheet) {
        ContactPickerSheet(
            contacts = edit.contacts,
            selfContact = edit.selfContact,
            onPick = { edit.pickContactForDongjia(it) },
            onDismiss = { edit.closeContactSheet() },
            loading = edit.loadingContacts,
            error = edit.contactsError,
            onRetry = { edit.loadContacts() },
            onCreate = { name, phone -> edit.createContactAndPick(name, phone) },
            creating = edit.creatingContact,
            createError = edit.contactSaveError,
        )
    }
}

/**
 * 改送达日期（CHG-0135）：派单员在订单详情里改"哪天送到"。
 *
 * 用户 2026-10-22：「我们的**派单员是可以修改**这个信息的」。
 *
 * ⚠️ 只有一个入口（M3 日历），选择层就**封顶今天**（与下单页同一条规则：
 *    `deliveryDateSelectable` 来自 `ui/common/DeliveryDate.kt`，⛔ 不在这里另写一份）。
 * ⚠️ 报的是同一条 PATCH（`saveEdit`）：⛔ 不新开端点、不新开字段表。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DeliveryDateEditBlock(edit: OrderEditHost, modifier: Modifier = Modifier) {
    var picking by remember { mutableStateOf(false) }
    Column(modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Default.Event, contentDescription = null, tint = Color(0xFF00A4CE), modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text("送达日期", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            Text(
                deliveryDateDisplay(edit.draft(OrderEditField.DELIVERY_DATE), ""),
                style = MaterialTheme.typography.bodyMedium,
            )
            TextButton(onClick = { picking = true }) { Text("选日期") }
        }
        EditActions(
            error = edit.editError,
            busy = edit.editBusy,
            saveLabel = "保存送达日期",
            onSave = { edit.saveEdit() },
            onCancel = { edit.cancelEdit() },
        )
    }
    if (picking) {
        val dpState = rememberDatePickerState(
            initialSelectedDateMillis = isoDateToMillis(edit.draft(OrderEditField.DELIVERY_DATE)),
            selectableDates = object : SelectableDates {
                override fun isSelectableDate(utcTimeMillis: Long): Boolean = deliveryDateSelectable(utcTimeMillis)
            },
        )
        DatePickerDialog(
            onDismissRequest = { picking = false },
            confirmButton = {
                TextButton(onClick = {
                    val picked = dpState.selectedDateMillis
                    // 兜底：草稿里本来就有一个过期日子时它是选中态、选择层拦不住 —— 那种值不许写回。
                    if (picked != null && deliveryDateSelectable(picked)) {
                        edit.setDraft(OrderEditField.DELIVERY_DATE, isoDateOfMillis(picked))
                    }
                    picking = false
                }) { Text("就用这天") }
            },
            dismissButton = { TextButton(onClick = { picking = false }) { Text("取消") } },
        ) {
            DatePicker(state = dpState)
        }
    }
}

/** 备注：多行（备注本来就是一句话）。 */
@Composable
fun RemarkEditBlock(edit: OrderEditHost, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth()) {
        EditBox(
            label = "备注",
            value = edit.draft(OrderEditField.REMARK_TEXT),
            onValue = { edit.setDraft(OrderEditField.REMARK_TEXT, it) },
            minLines = 2,
            singleLine = false,
        )
        EditActions(
            error = edit.editError,
            busy = edit.editBusy,
            saveLabel = "保存备注",
            onSave = { edit.saveEdit() },
            onCancel = { edit.cancelEdit() },
        )
    }
}

/**
 * 改一件货：数量 + 单价，外加「删掉这件货」。
 *
 * ⚠️ 单价与数量**必须一起报**（[OrderEditHost.saveLine]）：后端是把两个值合起来重算行金额的，
 * 只报单价它会按旧数量算，出现「改了价、总额没动」这种没人看得懂的结果。
 */
@Composable
fun ProductLineEditBlock(
    edit: OrderEditHost,
    line: OrderProductDto,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Text("改这一件货", style = MaterialTheme.typography.titleSmall)
        Text(
            line.productNameSnapshot,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            EditBox(
                label = "数量",
                value = edit.lineQty,
                onValue = { edit.updateLineQty(it) },
                keyboard = KeyboardType.Number,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(10.dp))
            // 金额过滤的唯一实现在 core/InputRules.kt：单价列 Numeric(14,4) ⇒ 走 priceInput（四位）
            EditBox(
                label = "单价（元）",
                value = edit.linePrice,
                onValue = { edit.updateLinePrice(InputRules.priceInput(it)) },
                keyboard = KeyboardType.Decimal,
                modifier = Modifier.weight(1f),
            )
        }
        EditActions(
            error = edit.editError,
            busy = edit.editBusy,
            saveLabel = "保存",
            onSave = { edit.saveLine() },
            onCancel = { edit.cancelLineEdit() },
            destructiveLabel = "删掉这件货",
            onDestructive = { edit.deleteLine() },
        )
    }
}

/**
 * 一个输入框。
 *
 * ⚠️ 金额框的预填值是 `trimMoneyZeros` 算好的（见 `OrderDetailViewModel.startLineEdit`）：
 * 后端单价列是 `Numeric(14,4)`，直接填进去是 `60.0000` 这种，用户得先删掉四个 0 才能改价；
 * 而 `formatMoney` 只留两位，会把 `12.3456` 的价**预填**成 `12.35`（＝用户没改价、价却变了）。
 */
@Composable
private fun EditBox(
    label: String,
    value: String,
    onValue: (String) -> Unit,
    modifier: Modifier = Modifier.fillMaxWidth(),
    keyboard: KeyboardType? = null,
    minLines: Int = 1,
    singleLine: Boolean = true,
) {
    // 房规（「分组一律白卡 + 共用行」）：输入一律走 ui/common/FormRows.kt 那套共用行，
    // ⛔ 卡里不许出现描边输入框（_check_form_panel_style.py 的全库总数只许减不许增）。
    // 这里**包一层**而不是把共用行摊到每个调用点：数量/单价那一对是按 weight(1f) 并排摆的，
    // 摊开就得把同一个修饰符与键盘类型写两遍。
    if (singleLine) {
        FormInputRow(
            label = label,
            value = value,
            onValueChange = onValue,
            modifier = modifier,
            keyboardType = keyboard ?: KeyboardType.Text,
        )
    } else {
        FormTextAreaRow(
            label = label,
            value = value,
            onValueChange = onValue,
            modifier = modifier,
            minLines = minLines,
        )
    }
}

/**
 * 一个编辑块底下的「取消 / 保存」（外加可选的警示动作）。
 *
 * 警示动作**在左**（与订单卡片上「退回池子」「撤销」同一条规矩：左＝反向/警示，右＝主操作）。
 * 保存与取消**由调用方传进来**（不是这里写死 `saveEdit`）：一行货的保存走的是
 * `saveLine` 那一条，两者混用就会"改完一行货、地址框里那半句也一起报上去"。
 */
@Composable
private fun EditActions(
    error: String?,
    busy: Boolean,
    saveLabel: String,
    onSave: () -> Unit,
    onCancel: () -> Unit,
    destructiveLabel: String? = null,
    onDestructive: (() -> Unit)? = null,
) {
    FormErrorLine(error)
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (destructiveLabel == null) Arrangement.End else Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (destructiveLabel != null && onDestructive != null) {
            TextButton(onClick = onDestructive) {
                Text(destructiveLabel, color = MaterialTheme.colorScheme.error)
            }
        }
        Row {
            TextButton(onClick = onCancel) { Text("取消") }
            TextButton(onClick = onSave) {
                // 防连点：一次网络往返期间再点一次会改两遍，司机也会收到两条。
                Text(if (busy) "保存中…" else saveLabel)
            }
        }
    }
}
// ============================================================== 权限门（「谁能做这件事」）

/**
 * 这一单能不能补联系信息（收货人 / 下单人的姓名与电话那四格，台账 L-27 / L-28 / L-31，CHG-0057）？
 *
 * ## 为什么这件事要单独有个名字，而不是在详情页上再写一遍
 * 「谁能做这件事」的唯一真相在后端 `backend/app/core/rbac.py`（由
 * `_tools/ai/_gen_capability_snapshot.py` 生成到 `core/Capabilities.kt`）——
 * 这里只是把那一格**问出口**，没有第二份授权矩阵：权限键是 `"order:edit_contact"`，
 * 谁有它由生成物回答。
 *
 * ⚠️ 为什么不在详情页上直接写 `Capabilities.can(role.key, "order:edit_contact")`（原来的写法）：
 *    那个文件里已经有 `"order:cancel_shipper"` 与 `"order:cancel_dispatcher"` 两个字面量，
 *    再加一个就凑够 3 个 —— `_tools/qa/_check_capability_unification.py` 与
 *    `_tools/qa/_check_r3_constraints.py` 的 R3-D04 都把「一个 Kotlin 文件里 ≥3 个互异的
 *    权限键字面量」判成**手抄的第二份权限词表**（R3-02-B：授权只该有一个来源）。
 *    键放在这一处、问题也只在这一处回答，两边就都只有一个来源。
 *
 * ⚠️ 为什么不是 `role == Role.SHIPPER`：能力表里这一格以后可能开给别的角色
 *    （派单员那条路合并过来、或者开给别的岗位），写成角色判断就会出现
 *    「能力表说能、界面说不能」这种两边走散的局面。
 */
fun canEditOrderContact(role: Role): Boolean = Capabilities.can(role.key, "order:edit_contact")
