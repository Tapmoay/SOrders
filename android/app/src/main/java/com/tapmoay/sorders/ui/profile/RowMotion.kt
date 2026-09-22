package com.tapmoay.sorders.ui.profile

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Velocity
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * 「我的」页列表的**果冻**：整列跟着手指走，松手弹回原位。
 *
 * ## 这是第二版（第一版做错了，值得记下来）
 * 用户 2026-09-21 的原话：「这个动效**就像是一个果冻一样**……整个的列表我就像往下滑，
 * 它可以**跟着我的动作做出反应**啊，**我刚滑了一下没有反应**啊」。
 *
 * ⛔ 第一版把"跟随"挂在**滚动位置**上（`translationY ∝ scrollState.value`），于是：
 * ① 列表**装得下、根本滚不动**的机器上（这台 5554 就是）**一点反应都没有** ——
 *    因为 `scroll.value` 永远是 0；
 * ② 能滚的时候它又会**停在那儿不回弹**（滚到哪儿偏到哪儿，行距都被拉歪了）。
 * 现在改成挂在**手势**上：`scrollable` 每一帧都会把手指的位移报给父级的嵌套滚动链
 * （`NestedScrollConnection`），**与"这一页能不能滚"无关** —— 滑一下就一定有反应 ✓。
 *
 * ## 它怎么动
 * - 手指每移动一段，整列**同方向**再偏移一点点（`RUBBER` 是比例），越靠下的行偏得越多
 *   （用户要的「越往下面偏移量越大」）→ 看起来像被"拽"出去。
 * - 松手（`onPostFling`）→ 用**回弹弹簧**（`DAMPING = 0.4`，偏"Q 弹"那侧）回到 0，
 *   会有一点过冲再收回，就是"果冻"那个手感。
 * - 上限 [MAX_DP]：不做上限的话，快速甩两下整列就飞出屏幕了。
 *
 * ## 工程约束（和第一版一样的两条）
 * - `value` 只在 `graphicsLayer { }` 里读 → 状态读落在**绘制阶段**，滑动时不会触发布局/重组。
 * - 不用 `Modifier.offset`：那会带着命中区一起动，手指按的地方和眼睛看的行会对不上。
 */
@Stable
class JellyState internal constructor(
    private val scope: CoroutineScope,
    private val maxPx: Float,
) {
    private val anim = Animatable(0f)

    /** 当前偏移（px）。**只在 `graphicsLayer` 里读**，别在组合里读。 */
    val value: Float get() = anim.value

    /**
     * 挂到滚动容器上（`Modifier.nestedScroll(jelly.connection)`）。
     *
     * 用 `onPostScroll` 而不是 `onPreScroll`：我们**不消费**任何位移
     * （返回 `Offset.Zero`），只"旁观"这一帧手指一共走了多少（`consumed + available`）——
     * 消费了就等于把列表的滚动抢掉了。
     */
    val connection: NestedScrollConnection = object : NestedScrollConnection {
        override fun onPostScroll(consumed: Offset, available: Offset, source: NestedScrollSource): Offset {
            val raw = consumed.y + available.y
            if (raw != 0f) {
                scope.launch {
                    anim.snapTo((anim.value + raw * RUBBER).coerceIn(-maxPx, maxPx))
                }
            }
            return Offset.Zero
        }

        override suspend fun onPostFling(consumed: Velocity, available: Velocity): Velocity {
            // 松手：弹簧回位。**在这里直接 animateTo**（它本来就是 suspend），不再另起协程
            anim.animateTo(0f, spring(dampingRatio = DAMPING, stiffness = Spring.StiffnessMediumLow))
            return Velocity.Zero
        }
    }
}

/** 建一个果冻状态（记住它 + 拿一个能起协程的作用域）。 */
@Composable
fun rememberJellyState(): JellyState {
    val scope = rememberCoroutineScope()
    val maxPx = with(LocalDensity.current) { MAX_DP.dp.toPx() }
    return remember(scope, maxPx) { JellyState(scope, maxPx) }
}

/**
 * 「我的」页每一行：**只做果冻**（跟着手指、松手弹回）。
 *
 * ## ⚠️ 2026-09-22 用户把"落位"整段砍掉了，别再加回来
 * 用户原话：「…**也不是说点进去一开始**，我要触发那个动效…**点进去就是那样子**，
 * 只是我们在**往下滑**的时候会有那个动效的触发。**如果他不是触发动效的话，那就是 bug**」。
 * 所以：**进页面不播任何入场动画**（原来每行按序号依次"滑上来"，`delay(index * 45ms)`
 * —— 用户看到的是"这一页在刷新/在加载"），动效**只跟滚动走**（`JellyState` 那条路径）。
 *
 * @param index 行在这一列里的序号（0 起）：只用来定果冻的倍数。
 * @param jelly 整列共用的那一个果冻状态（**同一份**：各行动效必须跟着同一次手势走）。
 */
@Composable
fun RowMotion(
    index: Int,
    jelly: JellyState,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Box(
        modifier.graphicsLayer {
            translationY = jelly.value * (JELLY_BASE + index * JELLY_STEP)
        },
    ) { content() }
}

private const val SETTLE_MS = 320
private const val STAGGER_MS = 45L
private const val START_DP = 8f           // 第一行的落位起点
private const val STEP_DP = 5f            // 每往下一行，起点再低这么多
private const val RUBBER = 0.55f          // 手指位移 → 果冻偏移的比例
private const val MAX_DP = 26f            // 果冻上限（"有反应"和"飞出去"的分界）
private const val DAMPING = 0.4f          // 回弹的 Q 弹程度（越小越弹、过冲越多）
private const val JELLY_BASE = 0.30f      // 果冻：第 0 行的倍数
private const val JELLY_STEP = 0.14f      // 每往下一行，果冻再多这么多（用户：「越往下面偏移量越大」）
