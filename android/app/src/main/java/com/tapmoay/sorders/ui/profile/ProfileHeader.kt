package com.tapmoay.sorders.ui.profile

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tapmoay.sorders.R
import com.tapmoay.sorders.data.remote.dto.UserDto
import com.tapmoay.sorders.ui.nav.Role
import com.tapmoay.sorders.ui.theme.MgrGreen
import com.tapmoay.sorders.ui.theme.NavBlue
import com.tapmoay.sorders.ui.theme.ProfileHeaderBottom
import com.tapmoay.sorders.ui.theme.ProfileHeaderTop
import com.tapmoay.sorders.ui.theme.ShipperTeal

/** 深色头部上的白字：分三档（主/次/弱），**只在这里定义**，避免各处各调一个 alpha。 */
private val InkMain = Color.White
private val InkSub = Color.White.copy(alpha = 0.80f)
private val InkFaint = Color.White.copy(alpha = 0.62f)

/**
 * 「我的」页的深色头部（用户 2026-09-21 给的参考图的**背景**部分）。
 *
 * ## 三件事和参考图一致
 * 1. **深色背景直接铺到状态栏下面**（`windowInsetsPadding(statusBars)` 只让**内容**让开，
 *    背景不被推下来）——所以它必须配 `LightStatusBarIcons()`，否则浅色模式下
 *    状态栏的深色图标压在深墨蓝上会**全部看不见**。
 * 2. **背景上有极淡的同心弧纹**（纯 `Canvas` 画，不引图片资源）：参考图那种"深色底上的纹路"。
 *    alpha 只有 0.055 —— 它的作用是让一大块纯色不显得空，**不是**当装饰看。
 * 3. **信息三行**：徽章+姓名 / 计费规则（只有司机有）/ 账号 + 账号类型标签。
 *    ⛔ 参考图的第二行是个**下拉选择器**（「先结账后用餐 ▾」）——我们**没有**那个字段，
 *    所以这一行是**纯展示**、不画箭头、不可点：给一个点不动的东西比不给更糟。
 *
 * ⚠️ [user] 允许为 `null`（资料还在路上）：那样头部照常画出来、值显示 `—`。
 *    不这么写的话，进这一页会先闪一下白屏再变深色（`ProfileScreen` 原来就是先 `LoadingBox()`）。
 */
@Composable
fun ProfileHeader(
    user: UserDto?,
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
) {
    val role = Role.fromKey(user?.role.orEmpty())
    val name = user?.fullName?.ifBlank { user.username } ?: "—"
    Box(
        modifier
            .fillMaxWidth()
            .background(Brush.verticalGradient(listOf(ProfileHeaderTop, ProfileHeaderBottom))),
    ) {
        // 同心弧纹（`res/drawable/bg_profile_header_arcs.xml`）：
        // ⚠️ 它是**矢量资源**、不是在这里用 `Canvas` 画 —— 本仓库有一条守卫
        //    「自己画的图只许在 `ui/common/Charts.kt`」（`_check_ledger_dashboard.py` 扫全树找
        //    `Canvas(`），来历是"账本页自己画折线/条形"那次真事故。一段背景装饰不该去撞它，
        //    更不该把页面文件加进白名单（那等于在这个文件上开了"可以自己画图"的口子）。
        //    `Crop` 而不是拉伸：拉伸会把圆压成椭圆。
        Image(
            painter = painterResource(R.drawable.bg_profile_header_arcs),
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.matchParentSize(),
        )
        Column(
            Modifier
                .fillMaxWidth()
                .windowInsetsPadding(WindowInsets.statusBars)
                // ⚠️ 高度是**调过的**（用户 2026-09-21 看图反馈：「上面做的太窄了导致下面很空，
                //    卡片要下来一点」）：头像 68 + 上下留白 → 头部约占屏高 19%，白卡因此落到
                //    接近参考图的位置。⛔ 不要再压回 56/26：那样白卡提前开始、下面空一大片。
                .padding(start = 20.dp, end = 20.dp, top = 8.dp, bottom = 60.dp),
        ) {
            // 只有"独立路由打开"时才有返回矢头；内嵌在底部 Tab 里时返回键由系统管
            if (onBack != null) {
                IconButton(onClick = onBack, modifier = Modifier.size(36.dp)) {
                    Icon(
                        Icons.AutoMirrored.Filled.ArrowBack,
                        contentDescription = "返回",
                        tint = InkMain,
                    )
                }
                Spacer(Modifier.height(2.dp))
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(68.dp)
                        .clip(CircleShape)
                        .background(Color(0xFFEFF2F8)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = name.take(1),
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                        color = ProfileHeaderBottom,
                    )
                }
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        HeaderTag(role.label, roleColor(role), filled = true)
                        Spacer(Modifier.width(8.dp))
                        Text(
                            text = name,
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.SemiBold,
                            color = InkMain,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f, fill = false),
                        )
                    }
                    // 司机专属：他**按什么算钱**。值来自后端 `pay_summary`（与账单同源），
                    // 界面不许自己按规则/车型拼一句话——拼了就会和账单对不上。
                    val pay = user?.paySummary.orEmpty()
                    if (user?.role == "driver" && pay.isNotBlank()) {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            text = pay,
                            style = MaterialTheme.typography.bodyMedium,
                            color = InkSub,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    Spacer(Modifier.height(6.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = "账号：" + (user?.phone ?: "—"),
                            style = MaterialTheme.typography.bodyMedium,
                            color = InkSub,
                        )
                        Spacer(Modifier.width(8.dp))
                        HeaderTag(role.label + "账号", InkFaint, filled = false)
                    }
                }
            }
        }
    }
}

/** 角色 → 语义色（与全 App 一色一功能同一套；徽章用**实色填充**，见 [HeaderTag]） */
private fun roleColor(role: Role): Color = when (role) {
    Role.SHIPPER -> Color(ShipperTeal)
    Role.DISPATCHER -> Color(NavBlue)
    Role.DRIVER -> Color(MgrGreen)
}

/**
 * 头部小标签，两种形态（都照着参考图来）：
 * - `filled = true`：**实色填充 + 白字**（参考图那个绿色「单店」）→ 用在姓名前的角色徽章上。
 *   ⛔ 不要在这里用 `ui/common/RoleBadge`：那是**浅底深字**的粉彩徽章，为浅色页面设计的，
 *   直接搬到深色头部上就是一块发光的浅色块（`Components.kt::badgeColors` 的注释里记着同类事故）。
 * - `filled = false`：**描边 + 透明底**（参考图那个「单店账号」）→ 用在账号后面的类型标签上。
 */
@Composable
private fun HeaderTag(text: String, color: Color, filled: Boolean) {
    val shape = RoundedCornerShape(6.dp)
    Box(
        Modifier
            .clip(shape)
            .then(if (filled) Modifier.background(color) else Modifier.border(1.dp, color, shape))
            .padding(horizontal = 7.dp, vertical = 2.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelMedium,
            color = if (filled) Color.White else InkSub,
        )
    }
}
