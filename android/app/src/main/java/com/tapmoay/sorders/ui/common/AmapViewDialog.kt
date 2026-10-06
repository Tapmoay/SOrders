package com.tapmoay.sorders.ui.common

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.Map
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.amap.api.maps.CameraUpdateFactory
import com.amap.api.maps.model.LatLng
import com.amap.api.maps.model.Marker
import com.amap.api.maps.model.MarkerOptions

/**
 * 只读看位置弹层（2026-10-06 台账 **L-18**）。
 *
 * 用户口径（**m00542**，比 m00481 那条"调用高德"更晚、以它为准）：「点击订单详情就直接打开一个地图，
 * 就是我们直接定位的那个地图……只是看一些详细……不会产生任何返回结果」⇒ **不跳高德 App**，
 * 复用自家地图载体打开一张**只读**的图。
 *
 * ## 它和 `AmapPickerDialog` 是两件事，别合并
 * - `AmapPickerDialog`（`ui/common/AmapPicker.kt`）：**选点** —— 搜索、定位、中心图钉、确认口，
 *   `onPicked(lat, lng, address)` 把坐标交给调用方，三个页面靠它**写**坐标。
 * - `AmapViewDialog`（本文件）：**看一眼** —— 没有 `onPicked`、没有确认口，也不注册
 *   `setOnMapClickListener` / `setOnCameraChangeListener`。
 *   台账给的另一条路是给 `AmapPickerDialog` 加一个 `readOnly: Boolean = false` 分支；这里**没有**走它：
 *   「不能选点」不是靠一个布尔量切出来的，而是**没有地方能把坐标交出去**（签名里就没有出口），
 *   而那个共用文件已经被 `_tools/qa/_check_map_picker.py` 与 `_tools/qa/_reverse_verify_map_picker.py`
 *   逐条钉死（含「`AmapMapHolder.applyMapType(` 恰好 2 处」），往里塞分支只会让两条契约互相打结。
 *
 * ## 复用的就是那份"载体"（能复用就复用）
 * 地图实例是进程内单例 `AmapMapHolder.get`：高德 **9.8.3** 在 Android 15+/16 arm64 上 `mapView.onDestroy()`
 * 会 native SIGABRT，所以载体常驻、关闭只 `onPause`（同 `AmapPicker.kt` 那段注释）。
 * 图层记忆也在它身上（`AmapMapHolder.satellite`），于是在这里切的图层与在选点弹层里切的是**同一个开关**。
 *
 * ## 目标点那颗 marker 必须自己收拾
 * 地图是单例 ⇒ marker 活在**地图**上、不活在这一次组合里：连看三张单会叠三枚，还会跟着出现在后面打开的
 * **选点**弹层里。所以每次打开先清一次、`onDispose` 再清一次（`placeMarker` 因此是**文件级**变量）。
 *
 * ## 只读的边界（这一层能保证的那一半）
 * 这个弹层不碰 `vm` / `repo` / 后端，也不写任何状态；它唯一的出口是 `onDismiss`。
 * 仓库那一半（订单、地点库）仍然只有一个写入方：订单详情里那颗「改」与地点库自己的编辑入口。
 *
 * ⛔ **永不 `mapView.onDestroy()`**（`_check_map_picker.py` 第 5 组：9.8.3 在 Android 15+/16 arm64 上闪退）。
 *
 * @param lat 目标点纬度（调用方先判过 `addressLat` 非空，解析失败就别开这个弹层）
 * @param lng 目标点经度
 * @param title 顶部那行字（订单详情传收货地址）；空白时退化成「位置」
 * @param onDismiss 关闭：点「关闭」、按返回键、点弹层外面都会走到这里
 */
@Composable
fun AmapViewDialog(
    lat: Double,
    lng: Double,
    title: String,
    onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    // 地图载体：与选点弹层**同一个**单例（理由见文件头：onDestroy 会闪退，所以常驻复用）
    val mapView = remember { AmapMapHolder.get(context.applicationContext) }
    val aMap = remember { mapView.map }
    // 图层起步值取单例上的记忆（用户在选点弹层里切过就跟着变）；用户在这里切完也写回同一处
    var satellite by remember { mutableStateOf(AmapMapHolder.satellite) }

    LaunchedEffect(Unit) {
        try { mapView.onResume() } catch (_: Exception) {}
        AmapMapHolder.applyMapType(aMap, satellite)
        // 打开即落到目标点（无动画）：这是**唯一**一次相机移动，之后不再注册任何相机监听
        try { aMap.moveCamera(CameraUpdateFactory.newLatLngZoom(LatLng(lat, lng), 16f)) } catch (_: Exception) {}
        // 先把上一次留下的摘掉（地图是单例，marker 会跨弹层活着），再挂这一单的目标点
        clearPlaceMarker()
        try {
            val opts = MarkerOptions().position(LatLng(lat, lng))
            if (title.isNotBlank()) opts.title(title)
            placeMarker = aMap.addMarker(opts)
        } catch (_: Exception) {
            // 地图还没就绪时静默：这一层只是"看一眼"，失败不该崩
        }
    }

    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize()) {
                // 顶栏：只有标题与「关闭」—— 没有确认口（这是与选点弹层最大的区别）
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        title.ifBlank { "位置" },
                        style = MaterialTheme.typography.titleMedium,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = onDismiss) { Text("关闭") }
                }
                Box(Modifier.weight(1f).fillMaxWidth()) {
                    AndroidView(factory = { mapView }, modifier = Modifier.fillMaxSize())
                    // 图层切换：与选点弹层共用同一份记忆；文案写**将要切到的那个**（与高德/微信一致）
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopEnd) {
                        Surface(
                            onClick = {
                                satellite = !satellite
                                AmapMapHolder.satellite = satellite
                                AmapMapHolder.applyMapType(aMap, satellite)
                            },
                            shape = MaterialTheme.shapes.small,
                            color = MaterialTheme.colorScheme.surface.copy(alpha = 0.92f),
                            shadowElevation = 2.dp,
                            modifier = Modifier.padding(10.dp),
                        ) {
                            Row(
                                Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(
                                    if (satellite) Icons.Default.Map else Icons.Default.Layers,
                                    contentDescription = null,
                                    modifier = Modifier.size(15.dp),
                                )
                                Spacer(Modifier.width(4.dp))
                                Text(
                                    if (satellite) "标准" else "卫星",
                                    style = MaterialTheme.typography.labelMedium,
                                )
                            }
                        }
                    }
                }
                // 底部：把这一单记录在案的坐标写全（"看一些详细"就是看这个）
                Column(Modifier.padding(12.dp)) {
                    Text(
                        "经纬度 " + lat + ", " + lng,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }

    // 关闭弹层：仅暂停渲染 + 摘掉自己那枚 marker。
    // ⛔ 不调 onDestroy（高德 9.8.3 在 Android 15+/16 arm64 上 native SIGABRT）。
    DisposableEffect(Unit) {
        onDispose {
            clearPlaceMarker()
            try { mapView.onPause() } catch (_: Exception) {}
        }
    }
}

/**
 * 目标点 marker 的句柄。
 *
 * 它是**文件级**而不是 `remember`：地图实例是进程内单例，marker 长在**地图**上、不长在这一次组合里 ——
 * 写成局部变量就没人能在下一次打开时把它摘掉了。
 */
private var placeMarker: Marker? = null

/** 摘掉上一次留下的目标点（幂等；没有就什么都不做）。 */
private fun clearPlaceMarker() {
    try { placeMarker?.remove() } catch (_: Exception) {}
    placeMarker = null
}
