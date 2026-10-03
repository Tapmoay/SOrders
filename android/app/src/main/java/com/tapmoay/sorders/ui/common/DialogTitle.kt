package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import com.tapmoay.sorders.util.noBreak

/**
 * 弹层标题：上行是**动作名**（跟着对话框标题的字号走），下行是**单号**（小一号、整块不换行）。
 *
 * 走查 P4：单号是 20 个字符（`SO` + 18 位数字），而 Material3 的 `AlertDialog` 标题是 24sp 的
 * 大字，一行塞不下 20 个字符 ⇒ 换行器只能从数字中间劈开（截图里就是
 * `SO2026100365088830` / `54`），读起来像两个数。这类单号是**报给客户**的，劈开就没法念。
 *
 * 两条一起才成立：
 * - **另起一行**：单号独占一行，不再和动作名抢那点宽度；
 * - **小一号**（bodyMedium ≈ 14sp）＋ [noBreak]（Word Joiner）＋ `maxLines = 1`：20 个字符在
 *   14sp 下一行放得下；万一以后单号更长，也是**带省略号**地显示前半截，⛔ 不会被从中间劈开。
 *
 * ⛔ 单号只用于**显示**：[noBreak] 插进去的 U+2060 是为了换行，不许跟着回传后端或入库
 *    （剪贴板与无障碍树拿到的是原文，见 `util/NoBreak.kt`）。
 *
 * @param action 动作名（如「申请退货」「办理退货」），单独占第一行。
 * @param orderNo 单号；可以为空（调用方常常是 `vm.xxx?.orderNo ?: ""`），空串时这一行不画。
 */
@Composable
fun DialogTitle(action: String, orderNo: String) {
    Column {
        Text(action)
        if (orderNo.isNotBlank()) {
            Text(
                orderNo.noBreak(),
                // 独占一行且铺满：它不与任何兄弟抢宽度（`_check_adaptive_layout.py` 第 5 组要求）。
                modifier = Modifier.fillMaxWidth(),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
