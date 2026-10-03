package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Phone
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tapmoay.sorders.ui.theme.MgrGreen
import kotlinx.coroutines.delay

/**
 * 名册卡片的两条"事实"（账户 / 司机 / 货主 / 批发商 / 车辆 共用）。
 *
 * ## 为什么要有这个文件
 * 用户 2026-10-05 的原话：「我们重要的有有些还有什么信息啊，就是名称和电话号码吧，
 * **我们要有对应的语义色和图标**。让信息明确」—— 而当时四张名册卡各写各的：
 * 名称有的 16sp、有的 14sp，电话一律是灰字（`onSurfaceVariant`）且没有图标，
 * 同一种"这个人是谁"的卡在不同页面上长得不一样。这里把这两行收成一处，
 * 四张卡只填值，不再各自决定字号和颜色。
 *
 * ## 两条口径（写死在 `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md`）
 * · **名称行**：本页模块色的圈底图标（`TintedIcon`，34dp 底 / 18dp 图标）+ 16sp 加粗名称；
 * · **电话行**：`Icons.Default.Phone` + [PhoneGreen]（青绿）+ 15sp **前景色**（不是灰字）。
 *
 * ⚠️ 电话用青绿不是随手挑的：`ui/shipper/AddressScreen.kt:1210` 早就用 `Color(MgrGreen)` 画电话图标，
 * 这里只是把它从地址页那一处提升成全库口径 —— 同一件事（能打的那个号码）在哪儿都是一个颜色。
 * ⛔ 地址页卡片的**主次层级**不许跟着变（用户 2026-09-22 裁定：线路卡片重要的是线路，
 * 联系人和电话都是次要信息、可以非常小），所以那两个零件是**名册卡**用的，不是通用行。
 */

/** 电话的语义色：能拨出去的那个号码，全库统一青绿（`MgrGreen`，同地址页既有先例）。 */
val PhoneGreen: Color = Color(MgrGreen)

/**
 * 名册卡片的电话行：图标 + 号码 + （老系统上）长按复制回执。
 *
 * 长按复制本身没变（还是共用的 `copyTextToClipboard`），只是从账户页那一处搬到这里，
 * 让司机 / 货主 / 批发商的卡也能长按复制 —— 少写一份，也少一处会长歪的地方。
 * 「已复制」只在 API 33 以下画（新系统自己会弹浮层，见 `Clipboard.kt` 的说明）。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun RosterPhoneRow(
    phone: String,
    modifier: Modifier = Modifier,
    fontSize: TextUnit = 15.sp,
    copyLabel: String = "手机号",
) {
    val ctx = LocalContext.current
    var copied by remember { mutableStateOf(false) }
    LaunchedEffect(copied) {
        if (copied) {
            delay(2000)
            copied = false
        }
    }
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        Icon(
            Icons.Default.Phone,
            contentDescription = "电话",
            tint = PhoneGreen,
            modifier = Modifier.size(13.dp),
        )
        Spacer(Modifier.width(5.dp))
        Text(
            phone,
            fontSize = fontSize,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.combinedClickable(
                onClick = {},
                onLongClickLabel = "复制" + copyLabel,
                onLongClick = {
                    if (copyTextToClipboard(ctx, copyLabel, phone)) copied = true
                },
            ),
        )
        if (copied) {
            Spacer(Modifier.width(8.dp))
            Text("已复制", fontSize = 12.sp, color = MaterialTheme.colorScheme.primary)
        }
    }
}

/**
 * 名册卡片的名称行：本页模块色的圈底图标 + 名称 + 右侧徽章（角色 / 状态）。
 *
 * [accent] 传**本页模块色**（账户页 `ShipperTeal`、车辆页 `VehicleAccent`、司机页池色…），
 * 不传主题色 —— 卡片一眼要能看出"这是哪一类人"，颜色就是那条线索（规范 §2 模块语义色表）。
 * [trailing] 是行尾的徽章位（`RowScope`，调用方自己塞几个都行）。
 */
@Composable
fun RosterNameRow(
    name: String,
    icon: ImageVector,
    accent: Color,
    modifier: Modifier = Modifier,
    trailing: @Composable RowScope.() -> Unit = {},
) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        TintedIcon(icon, accent, size = 18.dp, container = 34.dp)
        Spacer(Modifier.width(10.dp))
        Text(
            name,
            fontWeight = FontWeight.Bold,
            fontSize = 16.sp,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        trailing()
    }
}
