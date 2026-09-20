package com.tapmoay.sorders.ui.common

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.MyLocation
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import com.amap.api.maps.AMap
import com.amap.api.maps.CameraUpdateFactory
import com.amap.api.maps.MapView
import com.amap.api.maps.model.CameraPosition
import com.amap.api.maps.model.LatLng
import com.amap.api.services.core.LatLonPoint
import com.amap.api.services.geocoder.GeocodeQuery
import com.amap.api.services.geocoder.GeocodeSearch
import com.amap.api.services.geocoder.RegeocodeQuery
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.core.SunLocation
import com.tapmoay.sorders.util.GeoResolver

/**
 * 高德地图选点弹层：地图可拖动选点（微信式中心图钉）+ 搜索框（POI 联想）+ 定位当前位置 + 逆地理地址。
 * 确认后回调 (lat, lng, address)。
 *
 * 注：高德 9.8.3 在 Android 15+/16 arm64 上 mapView.onDestroy() 触发 native SIGABRT
 * （pointer tag truncated，SDK 未适配新系统）。规避方案：地图实例全程单例复用，
 * 只 onPause/onResume，永不 onDestroy（官方修复版本发布前）。
 */
internal object AmapMapHolder {
    private var mv: MapView? = null

    fun get(context: android.content.Context): MapView {
        mv?.let { return it }
        return try {
            MapView(context.applicationContext).apply { onCreate(null) }.also { mv = it }
        } catch (_: Exception) {
            MapView(context).apply { onCreate(null) }
        }
    }
}
@Composable
fun AmapPickerDialog(
    container: AppContainer,
    initialLat: Double?,
    initialLng: Double?,
    onPicked: (lat: Double, lng: Double, address: String) -> Unit,
    onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var address by remember { mutableStateOf("") }
    var lat by remember { mutableStateOf(initialLat ?: 0.0) }
    var lng by remember { mutableStateOf(initialLng ?: 0.0) }
    var locating by remember { mutableStateOf(false) }
    var searched by remember { mutableStateOf(false) }
    var searchText by remember { mutableStateOf("") }
    var mapReady by remember { mutableStateOf(false) }
    // 弹层存活标记：关闭销毁地图后所有地图操作一律短路，防止定位回流/回调触发闪退
    var alive by remember { mutableStateOf(true) }
    // 坐标不可信时的**就地**提示（2026-09-19 报告 P1-13）：以前这里没有这个状态，
    // 于是坐标是 (0,0) 时也照样确认出去。
    var coordError by remember { mutableStateOf<String?>(null) }

    // 地图载体：全程单例（规避 9.8.3 onDestroy 在 Android 16 arm64 上 native 崩溃）
    val mapView = remember { AmapMapHolder.get(context.applicationContext) }
    val aMap = remember { mapView.map }
    // 每次打开恢复地图渲染
    androidx.compose.runtime.LaunchedEffect(Unit) {
        try { mapView.onResume() } catch (_: Exception) {}
    }

    /** 相机跳转（无动画）：选点以相机中心为准（屏幕中央箭头指示，微信式） */
    fun jumpTo(p: LatLng, zoom: Float = 16f) {
        if (!alive) return
        try { aMap.moveCamera(CameraUpdateFactory.newLatLngZoom(p, zoom)) } catch (_: Exception) {}
    }

    // 逆地理（拖图/点击后填地址）
    val geocode = remember {
        try { GeocodeSearch(context) } catch (_: Exception) { null }
    }
    fun regeo(latV: Double, lngV: Double) {
        try {
            geocode?.getFromLocationAsyn(
                RegeocodeQuery(LatLonPoint(latV, lngV), 200f, GeocodeSearch.AMAP)
            )
        } catch (_: Exception) {}
    }
    geocode?.setOnGeocodeSearchListener(object : GeocodeSearch.OnGeocodeSearchListener {
        override fun onRegeocodeSearched(
            result: com.amap.api.services.geocoder.RegeocodeResult?,
            rCode: Int,
        ) {
            if (rCode == 1000) {
                val a = result?.getRegeocodeAddress()
                if (a != null) {
                    val fmt = a.formatAddress ?: a.pois?.firstOrNull()?.title
                    if (!fmt.isNullOrBlank()) address = fmt
                }
            }
        }

        override fun onGeocodeSearched(
            result: com.amap.api.services.geocoder.GeocodeResult?,
            rCode: Int,
        ) {
            if (rCode == 1000) {
                val a = result?.geocodeAddressList?.firstOrNull()
                if (a != null) {
                    val p = a.latLonPoint
                    if (p != null) {
                        lat = p.latitude
                        lng = p.longitude
                    }
                    val fmt = a.formatAddress
                    if (!fmt.isNullOrBlank()) address = fmt
                    jumpTo(LatLng(lat, lng))
                }
            }
        }
    })

    // 定位权限
    val permLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants.values.any { it }) {
            locating = true
            container.locationManager.requestSingle()
        }
    }

    fun locate() {
        val ok = listOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
            .all { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }
        if (ok) {
            locating = true
            container.locationManager.requestSingle()
        } else {
            permLauncher.launch(
                arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION,
                )
            )
        }
    }

    // 定位结果回流（完成后跳转中心；弹层已关闭则短路——原闪退根因）
    LaunchedEffect(Unit) {
        container.locationManager.locations.collect { pt ->
            locating = false
            if (!alive) return@collect
            if (pt.lat != 0.0 || pt.lng != 0.0) {
                lat = pt.lat
                lng = pt.lng
                if (pt.address.isNotBlank()) address = pt.address else regeo(pt.lat, pt.lng)
                jumpTo(LatLng(pt.lat, pt.lng))
            }
        }
    }

    // 打开即自动定位：避免一进地图就是默认北京；有最近定位立即跳当前位置（无动画），后台再刷新；
    // 无最近定位（如刚装机/冷启动）才走权限+定位流程
    LaunchedEffect(Unit) {
        val lp = container.locationManager.lastPoint
        if (lp != null && (lp.lat != 0.0 || lp.lng != 0.0)) {
            if (lp.address.isNotBlank()) address = lp.address
            jumpTo(LatLng(lp.lat, lp.lng), 16.5f)
            container.locationManager.requestSingle() // 后台刷新最新定位，回来后再微调
        } else {
            locate()
        }
    }

    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize()) {
                // 顶部：搜索 + 确认
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedTextField(
                        value = searchText,
                        onValueChange = { searchText = it },
                        label = { Text("搜索地点") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    IconButton(onClick = {
                        // POI/地址地理编码：按关键词解析坐标与正式地址，成功后地图定位并落标
                        val kw = searchText.trim()
                        if (kw.isNotBlank()) {
                            searched = true
                            try {
                                geocode?.getFromLocationNameAsyn(GeocodeQuery(kw, ""))
                            } catch (_: Exception) {}
                        }
                    }) {
                        Icon(Icons.Default.Search, contentDescription = "搜索")
                    }
                }
                // 地图
                Box(Modifier.weight(1f).fillMaxWidth()) {
                    AndroidView(factory = { mapView }, modifier = Modifier.fillMaxSize())
                    // 屏幕中心固定图钉（微信式）：拖动地图图钉不动，针尖指示中心即所选位置
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Icon(
                            Icons.Default.LocationOn,
                            contentDescription = "中心选点",
                            tint = androidx.compose.ui.graphics.Color(0xFF1E6FFF),
                            modifier = Modifier.size(40.dp).offset(y = (-15).dp),
                        )
                    }
                    LaunchedEffect(mapReady) {
                        if (!mapReady && (lat != 0.0 || lng != 0.0)) {
                            mapReady = true
                            jumpTo(LatLng(lat, lng), 15.5f)
                        }
                    }
                    // 地图点击 → 相机跳至该点（中心箭头即选点，微信式）
                    LaunchedEffect(Unit) {
                        aMap.setOnMapClickListener { p -> jumpTo(p) }
                    }
                    // 相机中心即选点：拖动/跳转结束后取中心坐标 + 逆地理(微信式固定中心箭头)
                    LaunchedEffect(Unit) {
                        aMap.setOnCameraChangeListener(object : AMap.OnCameraChangeListener {
                            override fun onCameraChange(position: CameraPosition?) {}
                            override fun onCameraChangeFinish(position: CameraPosition?) {
                                if (!alive) return
                                position?.let { p ->
                                    lat = p.target.latitude
                                    lng = p.target.longitude
                                    coordError = null   // 重新选了点，把上一次的提示撤掉
                                    regeo(lat, lng)
                                }
                            }
                        })
                    }
                    // 底部居中定位按钮
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.BottomCenter) {
                        FilledTonalButton(
                            onClick = { locate() },
                            enabled = !locating,
                            modifier = Modifier.padding(bottom = 16.dp),
                        ) {
                            Icon(Icons.Default.MyLocation, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(6.dp))
                            Text(if (locating) "定位中…" else "定位到当前位置")
                        }
                    }
                }
                // 地址确认
                Column(Modifier.padding(12.dp)) {
                    Text(
                        address.ifBlank { "拖动地图或点击地图选择位置" },
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (address.isBlank()) MaterialTheme.colorScheme.onSurfaceVariant
                        else MaterialTheme.colorScheme.onSurface,
                        maxLines = 2,
                    )
                    Spacer(Modifier.height(8.dp))
                    coordError?.let { msg ->
                        Text(
                            msg,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                        Spacer(Modifier.height(6.dp))
                    }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = {
                                // ⛔ **坐标不可信时不许确认**（2026-09-19 全项目报告 P1-13，中）：
                                //    高德定位失败回的是 `(0,0)`（不是 null），而这个弹层的初始坐标就是
                                //    `initialLat ?: 0.0` —— 于是"没拿到定位就直接点确认"会把 `(0.0, 0.0)`
                                //    交给调用方：写进订单、也写进**全库共享的地点库**（那个库没有删除接口，
                                //    污染不可逆），导航还会把人指到几内亚湾。
                                //    判据直接复用 `SunLocation.isPlausible` —— 它已经是本仓"这个坐标是不是
                                //    真的"的唯一一份（`core/DeviceLocation.kt` 也用它过滤定位回调，
                                //    注释里写明了"定位失败时高德回的是 (0,0)"）。
                                //    闸放在这**唯一一个确认口**，三个调用方（下单/地址与联系人/导航）一起受保护。
                                if (!SunLocation.isPlausible(lat, lng)) {
                                    coordError = "还没拿到有效坐标：请点「定位到当前位置」，或在图上点一下/拖动地图重新选点。"
                                    return@Button
                                }
                                val a = address.trim()
                                if (a.isNotBlank()) {
                                    onPicked(lat, lng, a)
                                } else {
                                    // 逆地理未回填时兜底：IO 线程同步解析再回传
                                    // （走到这里时坐标一定可信，所以兜底文案可以直接给"已选位置"）
                                    scope.launch(Dispatchers.IO) {
                                        val fallback = GeoResolver.resolveSync(context, lat, lng) ?: "已选位置"
                                        onPicked(lat, lng, fallback)
                                    }
                                }
                            },
                            modifier = Modifier.weight(1f).height(44.dp),
                        ) { Text("确认") }
                        TextButton(onClick = onDismiss, modifier = Modifier.weight(1f).height(44.dp)) {
                            Text("取消")
                        }
                    }
                }
            }
        }
    }

    // 关闭弹层：置 alive 短路后续地图操作 + 仅暂停渲染。
    // 注意：高德 9.8.3 在 Android 15+/16 arm64 上不能调用 onDestroy（native SIGABRT 闪退），
    // 地图实例常驻单例复用，官方修复版发布后再恢复标准生命周期。
    androidx.compose.runtime.DisposableEffect(Unit) {
        onDispose {
            alive = false
            try { mapView.onPause() } catch (_: Exception) {}
        }
    }
}