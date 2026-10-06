package com.tapmoay.sorders.ui.order

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.core.Capabilities
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import com.tapmoay.sorders.ui.common.ContactPickerSheet
import com.tapmoay.sorders.ui.common.FormErrorLine
import com.tapmoay.sorders.ui.common.FormInputRow
import com.tapmoay.sorders.ui.common.FormTextAreaRow
import com.tapmoay.sorders.ui.nav.Role

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
    const val DONGJIA_NAME = "contactDongjiaName"
    const val DONGJIA_PHONE = "contactDongjiaPhone"
    const val BOSS_NAME = "contactBossName"
    const val BOSS_PHONE = "contactBossPhone"
    const val REMARK_TEXT = "remark"
}

/**
 * 行尾那颗「改」（只给改得动的人画）。
 *
 * ⛔ 不用铅笔图标：这一页把「信息行」与「动作」分得很清，收货人/下单人那两行的点击
 * 已经是**拨号**（2026-09-20/22 定的），行尾再摆一个没有文字的图标，用户分不清
 * 点哪个是拨号、哪个是改。一个「改」字最省事，也与派单池那张卡片上的那颗一致。
 */
@Composable
fun EditHint(onClick: () -> Unit, label: String = "改") {
    Text(
        label,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier
            .clickable(onClick = onClick)
            .padding(horizontal = 8.dp, vertical = 4.dp),
    )
}

/** 收货地址：一个多行框（地址常常一行放不下）。 */
@Composable
fun AddressEditBlock(edit: OrderEditHost, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxWidth()) {
        EditBox(
            label = "收货地址",
            value = edit.draft(OrderEditField.ADDRESS_DETAIL),
            onValue = { edit.setDraft(OrderEditField.ADDRESS_DETAIL, it) },
            minLines = 2,
            singleLine = false,
        )
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
