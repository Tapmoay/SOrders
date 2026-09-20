package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.ui.theme.Success
import com.tapmoay.sorders.ui.theme.SuccessDark
import com.tapmoay.sorders.ui.theme.ThemeMode

/**
 * 退货申请的状态胶囊（货主端「我的退货申请」与派单端待办页**共用这一份**）。
 *
 * ## 中文名**只能**来自后端的 `statusLabel`
 * [label] 是故意做成**必传参数**的：它必须由调用方从 `ReturnRequestDto.statusLabel` 传进来。
 * ⛔ 这个文件里**没有**「pending → 待派单员处理」这种映射，也不许有人加 ——
 *    后端加一档状态时，前端自己写的那套映射会**原样显示原始码**（`withdrawn` 这种），
 *    而这一页上正是货主唯一能看到"我的申请怎么样了"的地方。
 *    （判据：`docs/PROJECT_MAP/08_CODE_LOCATOR.md` 与 `backend/app/api/v1/return_requests.py`
 *      的 `_STATUS_LABEL` —— 中文名的唯一出处。）
 *
 * ## 颜色按机器码分档（这部分不是"文案"）
 * 颜色只是"一眼看出哪张还没办"，写在这里不会与后端的词表打架；
 * 认不出的新状态**退回中性灰**并照旧显示后端给的中文名（不猜、不隐藏）。
 *
 * ⚠️ 暗色模式必须换一套底色：浅粉彩底直接搬到深色页面上会变成一块发光色块
 *   （与 `Components.kt::OrderStatusChip` 同一条理由，判据是 [ThemeMode.isDark]）。
 */
@Composable
fun ReturnRequestStatusChip(status: String, label: String, modifier: Modifier = Modifier) {
    val (bg, fg) = chipColors(status)
    Surface(color = bg, shape = RoundedCornerShape(50), modifier = modifier) {
        Text(
            // 后端没给中文名时（老后端/异常数据）显示原始码：宁可难看，也不许编一个中文名出来
            text = label.ifBlank { status },
            color = fg,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        )
    }
}

/** `[亮底, 亮字, 暗底, 暗字]` —— 同一套色相两种底色，与 `OrderStatusChip` 同一手法。 */
private fun chipColors(status: String): Pair<Color, Color> {
    val p: List<Color> = when (status) {
        // 待派单员处理：黄（与订单列表「派单中」同色）
        "pending" -> listOf(Color(0xFFFFF1C6), Color(0xFF7A5900), Color(0xFF463800), Color(0xFFFFE08A))
        // 已办理：绿（钱货已经动过了）
        "done" -> listOf(Color(0xFFD9F0DA), Success, Color(0xFF0E3A28), SuccessDark)
        // 已驳回：红（这是货主唯一能拿到的答复，必须一眼看见）
        "rejected" -> listOf(Color(0xFFFFE1E1), Color(0xFF9C2B2B), Color(0xFF44201F), Color(0xFFFFB4AB))
        // 已撤回：灰（申请人不打算办了；记录仍在）
        "withdrawn" -> listOf(Color(0xFFE1E2EC), Color(0xFF44464F), Color(0xFF2A2C33), Color(0xFFC7C9D1))
        // 认不出的新状态：跟「已撤回」同一档中性灰，**中文名照旧用后端给的**
        else -> listOf(Color(0xFFE1E2EC), Color(0xFF44464F), Color(0xFF2A2C33), Color(0xFFC7C9D1))
    }
    return if (ThemeMode.isDark) p[2] to p[3] else p[0] to p[1]
}
