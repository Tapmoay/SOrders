package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowLeft
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil.compose.AsyncImage

/**
 * # 点开看大图（全屏预览）—— 全库唯一一处
 *
 * 用户 2026-09-22：「还有一个是就是**图片**啊，他要支持**预览**，点击图片支持预览…
 * 他那个照片，**他不知道他自己拍的怎么样**，这是一个不好的点，改一下」。
 *
 * ## 为什么这条不是"锦上添花"
 * 表单里的缩略图是 **72dp** 的小方块：拍歪了、拍糊了、拍到了别的门牌，在那个尺寸上
 * **看不出来**。而这一张图是要拿去找货、送货的 —— 拍错了当场不知道，等司机拿着它找不到地方
 * 才发现，那时候人已经不在现场了。所以"能点开看"是这条链路的**必要一环**，不是体验优化。
 *
 * ## 交互（三条都是刻意的）
 * 1. **点任意处关闭**（不用去找那个小 `X`）—— 全屏看图时手指唯一想干的事就是"看完了退出"；
 * 2. **左右箭头翻页**（多张时）+ 底部 `2/3` —— 拍了一串照片要一张张看，关掉再点开太费事；
 * 3. **黑底**（不是白底、不是卡片）—— 照片自己的颜色才是主角，白底会把浅色照片糊掉。
 *
 * ⛔ **不要在每个页面各写一个**：这是一个纯 UI 组件（`AsyncImage` + 黑底 + 翻页），
 * 抄三份就会出现"有的页面能翻页、有的不能""有的点空白关不掉"。
 */
@Composable
fun ImagePreviewDialog(
    models: List<Any>,
    startIndex: Int = 0,
    onDismiss: () -> Unit,
) {
    if (models.isEmpty()) return
    var index by remember(startIndex, models) {
        mutableStateOf(startIndex.coerceIn(0, models.lastIndex))
    }
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.96f))
                // 点任意处关闭（见类文档第 1 条）
                .clickable(onClick = onDismiss),
        ) {
            AsyncImage(
                model = models[index],
                contentDescription = "图片预览",
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize().padding(8.dp),
            )
            // 右上角关闭
            IconButton(
                onClick = onDismiss,
                modifier = Modifier.align(Alignment.TopEnd).padding(8.dp),
            ) {
                Icon(Icons.Default.Close, contentDescription = "关闭预览", tint = Color.White)
            }
            if (models.size > 1) {
                IconButton(
                    onClick = { index = (index - 1 + models.size) % models.size },
                    modifier = Modifier.align(Alignment.CenterStart).padding(8.dp),
                ) {
                    Icon(Icons.Default.KeyboardArrowLeft, contentDescription = "上一张", tint = Color.White)
                }
                IconButton(
                    onClick = { index = (index + 1) % models.size },
                    modifier = Modifier.align(Alignment.CenterEnd).padding(8.dp),
                ) {
                    Icon(Icons.Default.KeyboardArrowRight, contentDescription = "下一张", tint = Color.White)
                }
                Text(
                    "${index + 1} / ${models.size}",
                    style = MaterialTheme.typography.labelLarge,
                    color = Color.White,
                    modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 28.dp),
                )
            }
        }
    }
}

/**
 * 一份"正在预览哪几张图"的状态。
 *
 * ⚠️ 参数是 **Coil 的 model（`Any`）** 而不是 `List<String>`：本 App 的图有两种来源 ——
 * 表单里**刚拍还没上传**的是本地 `File`（`OrderCreateScreen` 的位置图片就是），
 * 已经存到服务端的是 URL（要过 [resolveStaticUrl]）。收成 `Any` 之后**两种都能预览**，
 * 否则就会出现"已上传的能看大图、刚拍的看不了"——而那恰恰是最需要看的那一张。
 *
 * 用法：
 * ```
 * val preview = rememberImagePreview()
 * …
 * Thumb(…, onClick = { preview.open(models, i) })
 * preview.Show()
 * ```
 * 把它收成一个小盒子，是为了让每个页面都**不用**自己写 `var previewUrls by remember{…}`
 * 那三行状态（写三遍就会出现"有的页面点开了但关不掉"这种状态没接全的毛病）。
 */
class ImagePreviewState internal constructor() {
    internal var models by mutableStateOf<List<Any>>(emptyList())
    internal var index by mutableStateOf(0)

    /** 打开：给**整组**图 + 点的是第几张（多张时才能左右翻）。 */
    fun open(all: List<Any>, at: Int) {
        if (all.isEmpty()) return
        models = all
        index = at.coerceIn(0, all.lastIndex)
    }

    /** 在 Composable 里调一次，负责把弹层画出来。 */
    @Composable
    internal fun Show() {
        if (models.isNotEmpty()) {
            ImagePreviewDialog(models = models, startIndex = index) { models = emptyList() }
        }
    }
}

/** 见 [ImagePreviewState] 的用法。 */
@Composable
fun rememberImagePreview(): ImagePreviewState = remember { ImagePreviewState() }
