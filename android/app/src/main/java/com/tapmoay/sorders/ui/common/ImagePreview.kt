package com.tapmoay.sorders.ui.common

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.KeyboardArrowLeft
import androidx.compose.material.icons.filled.KeyboardArrowRight
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil.compose.AsyncImage
import com.tapmoay.sorders.core.NetworkDns
import com.tapmoay.sorders.util.resolveStaticUrl
import com.tapmoay.sorders.util.saveImageToGallery
import kotlin.math.abs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** 缩放下限：1× 就是"整张图刚好放进屏幕"。 */
private const val MIN_SCALE = 1f

/** 缩放上限：5× 够看清门牌号 / 单号那一行小字，再大就是马赛克了。 */
private const val MAX_SCALE = 5f

/** 双击一次放大到 2.5×（1× ↔ 2.5× 来回切）—— 比"双击就一直放到最大"更常用。 */
private const val DOUBLE_TAP_SCALE = 2.5f

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
 * ## 交互（四条都是刻意的）
 * 1. **点任意处关闭**（不用去找那个小 `X`）—— 全屏看图时手指唯一想干的事就是"看完了退出"；
 * 2. **左右箭头翻页 + 横滑翻页**（多张时）+ 底部 `2/3` —— 拍了一串照片要一张张看，关掉再点开太费事。
 *    2026-10-07 用户台账 L-37：「我想看下一张照片就是**左右滑动不行，非要按按钮**。这个不要，
 *    **左右滑动这样更方便**，就是真实的（相册）操作」；顺带钉了两条边界 ——「**不要不要不要循环**啊，
 *    就是**可以有滑到底**的」（到头即停）与「**首章和末章的箭头就是俺藏起来吧**」（首张不画左箭头、
 *    末张不画右箭头）。滑动的**分档**见下面 `detectTransformGestures` 那一段；
 * 3. **黑底**（不是白底、不是卡片）—— 照片自己的颜色才是主角，白底会把浅色照片糊掉；
 * 4. **双指缩放 + 拖动 + 双击放大**（2026-10-06 用户台账 L-03：「点一下确实放大了，但要
 *    **支持双指/双手独立缩放**（有时候拍得比较远，要放大才能看清）」）—— 拍得远的
 *    门牌 / 单号 / 金额，在"刚好铺满"的倍数下仍然看不清，整屏放大是唯一能看清的办法。
 *
 * ## 保存到相册（右上角那个 ⤓）
 * 用户同一句里的后半句：「**并且图片要支持下载**」。取的是服务端那张原图
 * （[resolveStaticUrl] 拼出来的 `/static/…` 是**不带鉴权**的公开静态资源），
 * 落 `Pictures/SOrders`（[saveImageToGallery]）。
 * ⚠️ 只给"服务端上的图"画这个按钮：表单里**刚拍还没上传**的那张是本地 `File`，
 * 它本来就在这台手机上，再"下载"一次没有意义。
 *
 * ⛔ **不要在每个页面各写一个**：这是一个纯 UI 组件（`AsyncImage` + 黑底 + 翻页 + 缩放），
 * 抄三份就会出现"有的页面能翻页、有的不能""有的点空白关不掉""有的能缩放、有的不能"。
 * 订单详情页 2026-10-06 之前就是自己写的一份（只有"点开、再点关闭"），本事项把它收了回来。
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
    // 缩放状态**跟着 index 走**（remember(index)）：翻到下一张就归位。
    // 不归位的话，第二张会继承上一张的放大倍数与拖动位移，人看到的是"这张图自己歪了 / 糊了"。
    var scale by remember(index) { mutableStateOf(MIN_SCALE) }
    var offset by remember(index) { mutableStateOf(Offset.Zero) }
    // 这一次横滑累积了多少「待翻页」的位移（px，向右为正）。**跟着 index 归零**：
    // 翻完一页重新起算，连滑两下不会一下跳两张。
    var swipe by remember(index) { mutableStateOf(0f) }
    var box by remember { mutableStateOf(IntSize.Zero) }
    var saving by remember(index) { mutableStateOf(false) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    // 只有服务端的图（String 路径）能下载；本地 File 不算。
    val currentPath = models.getOrNull(index) as? String

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Color.Black.copy(alpha = 0.96f))
                .onSizeChanged { box = it }
                // ⚠️ 「点任意处关闭」从 `clickable` 换成了 `detectTapGestures`，不是随手改的：
                //    `clickable` 只认"按下再抬起"，而缩放 / 拖动的手势中间**也会抬手** ——
                //    于是"我明明在拖这张图，它却把预览给我关了"。手势自己认得清"这是单击还是拖动"。
                .pointerInput(index) {
                    detectTapGestures(
                        onTap = {
                            // 1× 时单击＝关闭（老行为一个字没变）；放大后单击＝先回到 1×，
                            // 再点一次才关 —— 放大看细节时那一下点击，人想要的是"看全图"。
                            if (scale > MIN_SCALE) {
                                scale = MIN_SCALE
                                offset = Offset.Zero
                            } else {
                                onDismiss()
                            }
                        },
                        onDoubleTap = {
                            if (scale > MIN_SCALE) {
                                scale = MIN_SCALE
                                offset = Offset.Zero
                            } else {
                                scale = DOUBLE_TAP_SCALE
                            }
                        },
                    )
                }
                // 「松手」这一步：`detectTransformGestures` 没有抬手回调，所以在根 Box 上另挂一个
                // **只看不吃**的观察者 —— 全部手指抬起时，拿这一次累积的横滑位移去定夺翻不翻页。
                // ⚠️ 走 `Initial` 通道（在下面的缩放 / 拖动拿到事件**之前**）、且**一次都不 consume**：
                //    所以它不会把事件从子节点那几套手势手里抢走（抢了就是"放大后滑不动"）。
                .pointerInput(index) {
                    awaitEachGesture {
                        awaitFirstDown(requireUnconsumed = false)
                        var event = awaitPointerEvent(PointerEventPass.Initial)
                        while (event.changes.any { it.pressed }) {
                            event = awaitPointerEvent(PointerEventPass.Initial)
                        }
                        // 手指都抬起来了：这一次横滑够不够翻一页、往哪翻（到头即停，判据在 ImageSwipe.kt）。
                        val step = swipePageStep(
                            accumX = swipe,
                            boxWidth = box.width,
                            atFirst = index <= 0,
                            atLast = index >= models.lastIndex,
                        )
                        if (step != 0) {
                            index = (index + step).coerceIn(0, models.lastIndex)
                        } else if (scale <= MIN_SCALE) {
                            // 没过阈值：1× 时跟着手指滑出去的那一点要回正（不能停在半路）
                            offset = Offset.Zero
                        }
                        swipe = 0f
                    }
                },
        ) {
            AsyncImage(
                model = models[index],
                contentDescription = "图片预览",
                contentScale = ContentScale.Fit,
                modifier = Modifier
                    .fillMaxSize()
                    .padding(8.dp)
                    .graphicsLayer {
                        scaleX = scale
                        scaleY = scale
                        translationX = offset.x
                        translationY = offset.y
                    }
                    // 双指缩放 + 放大后拖动（全库唯一一处手势缩放实现）
                    .pointerInput(index) {
                        detectTransformGestures { _, pan, zoom, _ ->
                            val next = (scale * zoom).coerceIn(MIN_SCALE, MAX_SCALE)
                            scale = next
                            // 分档：横向那一份位移到底是「翻页」还是「平移」——
                            //   1× 时＝翻页的预备动作（图跟着手指横移，松手由上面的观察者定夺）；
                            //   放大后＝平移，**只有已经贴到左右边界还继续往外拖**，超出的那一截
                            //   才算待翻页（所以「放大后滑不动、必须先双击回 1×」这件事不存在）。
                            // 竖着拖（abs(pan.x) <= abs(pan.y)）两边都不算：这是在看图，不是翻页。
                            if (next <= MIN_SCALE) {
                                if (abs(pan.x) > abs(pan.y)) swipe += pan.x
                                offset = Offset(swipe.coerceIn(-box.width.toFloat(), box.width.toFloat()), 0f)
                            } else {
                                val moved = clampPan(offset + pan, next, box)
                                if (abs(pan.x) > abs(pan.y)) swipe += (offset + pan).x - moved.x
                                offset = moved
                            }
                        }
                    },
            )
            // 右上角：保存到相册 + 关闭
            Row(
                modifier = Modifier.align(Alignment.TopEnd).padding(8.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                if (currentPath != null) {
                    IconButton(
                        enabled = !saving,
                        onClick = {
                            val full = resolveStaticUrl(currentPath)
                            if (full == null) {
                                Toast.makeText(context, "这张图没有可下载的地址", Toast.LENGTH_SHORT).show()
                            } else {
                                saving = true
                                scope.launch {
                                    val bytes = withContext(Dispatchers.IO) { downloadBytes(full) }
                                    val saved = bytes?.let {
                                        withContext(Dispatchers.IO) {
                                            saveImageToGallery(context, it, photoFileName(full, index))
                                        }
                                    }
                                    saving = false
                                    Toast.makeText(
                                        context,
                                        if (saved != null) "已保存到相册：" + saved.substringAfterLast('/')
                                        else "保存失败，请检查网络后重试",
                                        Toast.LENGTH_LONG,
                                    ).show()
                                }
                            }
                        },
                    ) {
                        if (saving) {
                            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = Color.White)
                        } else {
                            Icon(Icons.Default.Download, contentDescription = "保存到相册", tint = Color.White)
                        }
                    }
                }
                IconButton(onClick = onDismiss) {
                    Icon(Icons.Default.Close, contentDescription = "关闭预览", tint = Color.White)
                }
            }
            // 手势是"藏起来的功能"：不写一句没人知道能缩放、能横滑翻页（用户点名的需求，不能靠猜）。
            // ⚠️ 这是**解释句**（删掉也照样能看图）⇒ 走 Hint（总开关关掉时整句不显示），不许裸 Text。
            Hint(
                "双指缩放 / 双击放大 / 左右滑动翻页",
                style = MaterialTheme.typography.labelSmall,
                color = Color.White.copy(alpha = 0.7f),
                modifier = Modifier.align(Alignment.BottomStart).padding(start = 16.dp, bottom = 28.dp),
            )
            if (models.size > 1) {
                // 到头即停（⛔ 不环绕）：第一张没有「上一张」、最后一张没有「下一张」，那两颗箭头就不画。
                // 用户 m01486：「不要不要不要循环啊，就是可以有滑到底的」；
                // m01517：「首章和末章的箭头就是俺藏起来吧……因为你首张的左边箭头怎么可能会有呢？」
                if (index > 0) {
                    IconButton(
                        onClick = { index -= 1 },
                        modifier = Modifier.align(Alignment.CenterStart).padding(8.dp),
                    ) {
                        Icon(Icons.Default.KeyboardArrowLeft, contentDescription = "上一张", tint = Color.White)
                    }
                }
                if (index < models.lastIndex) {
                    IconButton(
                        onClick = { index += 1 },
                        modifier = Modifier.align(Alignment.CenterEnd).padding(8.dp),
                    ) {
                        Icon(Icons.Default.KeyboardArrowRight, contentDescription = "下一张", tint = Color.White)
                    }
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

/** 取原图字节；任何一步不成就返回 null（调用方只负责说"保存失败"），不抛给界面。 */
private fun downloadBytes(url: String): ByteArray? {
    return try {
        NetworkDns.okHttp.newCall(okhttp3.Request.Builder().url(url).get().build()).execute().use { resp ->
            if (resp.isSuccessful) resp.body?.bytes() else null
        }
    } catch (e: Exception) {
        null
    }
}

/**
 * 拖动别把图拖出屏幕：放大到 n 倍后，每个方向最多能露出 `(n − 1) / 2 × 边长`，
 * 再多就该看见黑边了（那正是"图被拖飞了、怎么都拖不回来"的来源）。
 */
private fun clampPan(raw: Offset, scale: Float, box: IntSize): Offset {
    val maxX = box.width * (scale - 1f) / 2f
    val maxY = box.height * (scale - 1f) / 2f
    return Offset(raw.x.coerceIn(-maxX, maxX), raw.y.coerceIn(-maxY, maxY))
}

/** 文件名优先沿用服务端那个（带时间戳、天然不重名），取不到才自己拼一个。 */
private fun photoFileName(url: String, index: Int): String {
    val name = url.substringBefore('?').substringAfterLast('/')
    return if (name.contains('.')) name else "SOrders_" + (index + 1) + "_" + System.currentTimeMillis() + ".jpg"
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
 * Thumb(…, onClick = { preview.open(models, i) })      // 本地 File：直接给 model
 * Thumb(…, onClick = { preview.openStaticPaths(urls, i) })  // 服务端路径：自己会拼成全地址
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

    /**
     * 打开一组**服务端相对路径**（`/static/…`，订单里的图都是这种）：内部过 [resolveStaticUrl]。
     *
     * 让调用方交路径而不是自己拼地址，是为了"拼法只有一处"；顺带把空白路径剔掉 ——
     * 那种格子点开只会是一张黑图，不如让它不在翻页序列里（会跟着调整 [at] 的落点）。
     */
    fun openStaticPaths(paths: List<String>, at: Int) {
        val usable = paths.withIndex().filter { it.value.isNotBlank() }
        val hit = usable.indexOfFirst { it.index == at }.coerceAtLeast(0)
        open(usable.map { resolveStaticUrl(it.value) ?: it.value }, hit)
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
