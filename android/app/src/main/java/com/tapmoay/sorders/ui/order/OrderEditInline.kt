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
import com.tapmoay.sorders.core.InputRules
import com.tapmoay.sorders.data.remote.dto.OrderProductDto
import com.tapmoay.sorders.ui.common.FormErrorLine
import com.tapmoay.sorders.ui.common.FormInputRow
import com.tapmoay.sorders.ui.common.FormTextAreaRow

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
