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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
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
import com.amap.api.maps.model.BitmapDescriptorFactory
import com.amap.api.maps.model.LatLng
import com.amap.api.maps.model.MarkerOptions
import com.amap.api.maps.model.MyLocationStyle
import com.amap.api.services.core.LatLonPoint
import com.amap.api.services.geocoder.GeocodeQuery
import com.amap.api.services.geocoder.GeocodeSearch
import com.amap.api.services.geocoder.RegeocodeQuery
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.util.GeoResolver
import kotlinx.coroutines.delay

/**
 * 高德地图选点弹层：地图可拖动选点 + 搜索框（POI 联想）+ 定位当前位置 + 逆地理地址。
 * 确认后回调 (lat, lng, address)。
 */
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

    // 地图载体
    val mapView = remember {
        MapView(context).apply {
            onCreate(null)
        }
    }
    val aMap = remember { mapView.map }

    fun setMarker(p: LatLng, moveCamera: Boolean = true) {
        aMap.clear()
        aMap.addMarker(
            MarkerOptions()
                .position(p)
                .icon(BitmapDescriptorFactory.defaultMarker(BitmapDescriptorFactory.HUE_AZURE))
                .title("")
        )
        if (moveCamera) aMap.animateCamera(CameraUpdateFactory.newLatLngZoom(p, 16f))
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
                    setMarker(LatLng(lat, lng))
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

    // 定位结果回流
    LaunchedEffect(Unit) {
        container.locationManager.locations.collect { pt ->
            locating = false
            if (pt.lat != 0.0 || pt.lng != 0.0) {
                lat = pt.lat
                lng = pt.lng
                if (pt.address.isNotBlank()) address = pt.address else regeo(pt.lat, pt.lng)
                setMarker(LatLng(pt.lat, pt.lng))
            }
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
                    LaunchedEffect(mapReady) {
                        if (!mapReady && (lat != 0.0 || lng != 0.0)) {
                            mapReady = true
                            aMap.moveCamera(CameraUpdateFactory.newLatLngZoom(LatLng(lat, lng), 15.5f))
                        }
                    }
                    // 地图点击选点
                    LaunchedEffect(Unit) {
                        aMap.setOnMapClickListener { p ->
                            lat = p.latitude
                            lng = p.longitude
                            regeo(p.latitude, p.longitude)
                            setMarker(p, moveCamera = false)
                        }
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
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = {
                                val a = address.trim()
                                if (a.isNotBlank()) {
                                    onPicked(lat, lng, a)
                                } else {
                                    // 逆地理未回填时兜底：IO 线程同步解析再回传
                                    scope.launch(Dispatchers.IO) {
                                        val fallback = GeoResolver.resolveSync(context, lat, lng)
                                            ?: (if (lat != 0.0 || lng != 0.0) "已选位置" else "")
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

    // 关闭时销毁地图资源
    androidx.compose.runtime.DisposableEffect(Unit) {
        onDispose {
            try { mapView.onDestroy() } catch (_: Exception) {}
        }
    }
}