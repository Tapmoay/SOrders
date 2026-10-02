package com.tapmoay.sorders.ui.common

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import com.amap.api.maps.model.Tile
import com.amap.api.maps.model.TileProvider
import com.tapmoay.sorders.BuildConfig
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/**
 * 地图选点的**自备高清影像层**（FEAT-0006）。
 *
 * ## 为什么要有这一层
 * 高德在鄱阳县一带的卫星影像**原生最高只到 z18**，z19 / z20 返回的是一张 4,235 字节的
 * 灰底占位图「此区域无卫星图」（2026-10-02 实测：z18 = 7,892 B 真实 JPEG，灰度 std ≈ 15；
 * z19 / z20 = 4,235 B PNG，灰度 std = 1.46）。而选点恰恰要靠放大确认"是不是这个门" ——
 * 放到最大反而一片灰。
 *
 * ## 它是怎么工作的（关键就一行）
 * 高德逐格问 [TileProvider.getTile]「这一格给我」。返回 [TileProvider.NO_TILE] 就是
 * 「这一格我没有」—— 地图于是**透出底下的高德瓦片**。所以：
 *
 * ```
 * z <= 18  ->  NO_TILE        （高德自己的影像，它是清晰的，我们不掺和）
 * z == 19  ->  用 z20 的 2x2 四个子格在客户端合成
 * z >= 20  ->  直接取 z20
 * ```
 *
 * ⚠️ **必须直接 implements [TileProvider]，不能继承 `UrlTileProvider`** —— 后者把
 * `getTile` 声明成了 `final`（它只会把 `getTileUrl` 包一层），拿不到 `NO_TILE`
 * （`javap -cp 3dmap-9.8.3.jar com.amap.api.maps.model.UrlTileProvider`）。
 *
 * ## 坐标系：⛔ 一个换算都不要写
 * 自备瓦片的索引与高德**同网格**（都是 GCJ-02 墨卡托）。实测（2026-10-02）：
 * 与高德的互相关峰值落在**位移 (0,0)**，与天地图（CGCS2000/WGS-84）的峰值落在 (+2,-3)
 * ≈ 480 m —— 正好是 GCJ-02 的偏移量；两者 50/50 叠加后田块边界与道路是**单一锐线、无重影**。
 * ⇒ 直接把 `x/y` 拼进 URL 即可。⛔ 任何时候都不要在这里加 WGS-84↔GCJ-02 的换算。
 */
// 文件级常量：本文件里的 HiResTileLayer / HiResTileProvider / TileDiskCache 都要用
private const val TILE_CONNECT_TIMEOUT_MS = 5_000
private const val TILE_READ_TIMEOUT_MS = 8_000

/** 等 4 张 z20 回来的上限。超过就整块放弃（回落高德），绝不让地图卡住。 */
private const val TILE_FETCH_WAIT_SEC = 20L

/** 合成瓦片的 JPEG 质量。z19 只是过渡层（真要找门会放到 z20），不必给太高。 */
private const val TILE_JPEG_QUALITY = 85

internal object HiResTileLayer {

    /** 从这一层起改用自备影像。低层级一律 [TileProvider.NO_TILE]。 */
    const val HI_ZOOM: Int = 19

    /** 服务器上实际存在的层级（`/opt/SOrders/tiles/20/<x>/<y>.jpg`）。z19 由它合成。 */
    const val BASE_ZOOM: Int = 20

    const val TILE_PX: Int = 256

    /**
     * 磁盘缓存上限。
     *
     * 为什么是 1 GB：实测「固定跑一个乡镇的派单员」把 8×8 km 在 z20 上滑一遍约 530 MB，
     * 跑 5 个乡镇约 3.2 GB。1 GB 对绝大多数人**永远碰不到**，但它保证缓存**有界** ——
     * 「只缓存浏览过的」≠「不会涨」：天天跑同几条路，半年后也能把整个片区攒下来。
     */
    private const val CACHE_CAP_BYTES = 1L * 1024 * 1024 * 1024

    /**
     * 瓦片基址。
     *
     * 缺省跟着后端走（生产 = `https://8.145.40.22/tiles`）；本机开发时 API 在
     * `http://10.0.2.2:8000` 而那里**没有**瓦片，所以允许用 `-PtileBaseUrl=` 单独覆盖
     * （见 `android/app/build.gradle.kts`）。
     *
     * ⚠️ 必须是 **https**：本包 `res/xml/network_security_config.xml` 是
     * `cleartextTrafficPermitted="false"`，http 瓦片在真机上会被**静默**拦掉 ——
     * 界面不报错，只是地图上永远不出现自备影像（这种"看起来没坏"的错最难查）。
     */
    val baseUrl: String = run {
        val override = BuildConfig.TILE_BASE_URL
        if (override.isNotBlank()) override.trimEnd('/')
        else BuildConfig.API_BASE_URL.trimEnd('/') + "/tiles"
    }

    /**
     * 取瓦片用的线程池。
     *
     * z19 要并发取 4 张 z20（串行的话延迟是 z20 的 4 倍，肉眼可见卡顿）。
     * 池子里的任务**不等待任何东西**，所以 [TileProvider.getTile] 所在的高德瓦片线程
     * 阻塞在这里是安全的（不存在互相等待）。
     */
    private val POOL = Executors.newFixedThreadPool(8) { r ->
        Thread(r, "sorders-tile").apply { isDaemon = true }
    }

    internal fun executor() = POOL

    /** 每进程一份磁盘缓存（同一个目录）。 */
    @Volatile
    private var cache: TileDiskCache? = null

    fun cacheOf(ctx: Context): TileDiskCache {
        cache?.let { return it }
        return synchronized(this) {
            cache ?: run {
                val base = ctx.externalCacheDir ?: ctx.cacheDir
                TileDiskCache(File(base, "tiles"), CACHE_CAP_BYTES).also { cache = it }
            }
        }
    }

    /** 组装瓦片 URL。⛔ 不做任何坐标换算，见类注释。 */
    fun tileUrl(zoom: Int, x: Int, y: Int): String = "$baseUrl/$zoom/$x/$y.jpg"
}

/**
 * 自备影像的 [TileProvider]。挂在 `AmapMapHolder` 里，`zIndex = 1`
 * （卫星底图之上、路网注记之下 —— 注记层是 2，见 `AmapMapHolder.applyMapType`）。
 */
internal class HiResTileProvider(private val ctx: Context) : TileProvider {

    override fun getTileWidth(): Int = HiResTileLayer.TILE_PX

    override fun getTileHeight(): Int = HiResTileLayer.TILE_PX

    /**
     * ⛔ **这个方法会被高德从多个瓦片线程并发调用**，所以：
     * · 不许在这里持有可变的共享状态（Bitmap 每次新建、用完 recycle）
     * · 它**不在 UI 线程**（既有代码里 `UrlTileProvider` 就在这里面同步做网络 IO，
     *   那已经证明它是后台线程）—— 所以这里的阻塞调用是允许的
     */
    override fun getTile(x: Int, y: Int, zoom: Int): Tile {
        // ★ 这一行就是"缩小时自动换回高德"的全部实现
        if (zoom < HiResTileLayer.HI_ZOOM) return TileProvider.NO_TILE

        val bytes = try {
            if (zoom == HiResTileLayer.HI_ZOOM) composeFromBaseZoom(x, y) else fetchBase(x, y)
        } catch (_: Exception) {
            // 任何异常都只是"这一格没有" —— ⛔ 绝不把异常抛回给地图 SDK
            null
        }

        // 没有就返回 NO_TILE：地图透出高德底图。
        // ⛔ 不要合成/返回"半张灰图"—— 那看起来像"这一片没有影像"，比回落更糟。
        return if (bytes == null) TileProvider.NO_TILE
        else Tile(HiResTileLayer.TILE_PX, HiResTileLayer.TILE_PX, bytes)
    }

    /** z19(x,y) 覆盖的正是 z20 的 (2x,2y)(2x+1,2y)(2x,2y+1)(2x+1,2y+1) 四格。 */
    private fun composeFromBaseZoom(x: Int, y: Int): ByteArray? {
        val bx = x * 2
        val by = y * 2
        val quads = arrayOf(
            bx to by, (bx + 1) to by,
            bx to (by + 1), (bx + 1) to (by + 1),
        )

        // 并发取四张
        val futures = quads.map { (qx, qy) -> HiResTileLayer.executor().submit<ByteArray?> { fetchBase(qx, qy) } }
        val parts = futures.mapNotNull { f ->
            try {
                f.get(TILE_FETCH_WAIT_SEC, TimeUnit.SECONDS)
            } catch (_: Exception) {
                null
            }
        }

        // ★ 缺一张就整块放弃。四格里有任何一格不在覆盖范围内（多边形边界），
        //   合成出来就是"四分之三有影像、四分之一是黑块"—— 那比直接回落高德更难看。
        if (parts.size != 4) return null

        var big: Bitmap? = null
        var small: Bitmap? = null
        return try {
            big = Bitmap.createBitmap(
                HiResTileLayer.TILE_PX * 2, HiResTileLayer.TILE_PX * 2, Bitmap.Config.ARGB_8888,
            )
            val canvas = Canvas(big)
            val paint = Paint(Paint.FILTER_BITMAP_FLAG)
            val dst = Rect()
            for (i in 0 until 4) {
                val src = parts[i]
                val bmp = BitmapFactory.decodeByteArray(src, 0, src.size) ?: return null
                val dx = (i % 2) * HiResTileLayer.TILE_PX
                val dy = (i / 2) * HiResTileLayer.TILE_PX
                dst.set(dx, dy, dx + HiResTileLayer.TILE_PX, dy + HiResTileLayer.TILE_PX)
                canvas.drawBitmap(bmp, null, dst, paint)
                bmp.recycle()
            }
            // 512 -> 256 用带滤波的整体缩放（比"每格各缩一半再拼"质量好，且只算一次）
            small = Bitmap.createScaledBitmap(big, HiResTileLayer.TILE_PX, HiResTileLayer.TILE_PX, true)
            val out = ByteArrayOutputStream(24 * 1024)
            if (!small.compress(Bitmap.CompressFormat.JPEG, TILE_JPEG_QUALITY, out)) return null
            out.toByteArray()
        } catch (_: Exception) {
            null
        } finally {
            // ⛔ 必须回收：512×512 ARGB = 1 MB/张，来回缩放几次不回收就是 OOM
            big?.recycle()
            small?.recycle()
        }
    }

    /** 取一张 z20：先查磁盘缓存，没有再走网络，拿到就写缓存。 */
    private fun fetchBase(x: Int, y: Int): ByteArray? {
        val cache = HiResTileLayer.cacheOf(ctx)
        cache.read(HiResTileLayer.BASE_ZOOM, x, y)?.let { return it }
        val bytes = httpGet(HiResTileLayer.tileUrl(HiResTileLayer.BASE_ZOOM, x, y)) ?: return null
        cache.write(HiResTileLayer.BASE_ZOOM, x, y, bytes)
        return bytes
    }

    /**
     * ⛔ **不要调 `connection.disconnect()`**。
     *
     * Android 的 `HttpURLConnection` 底下是 OkHttp 的连接池，主动 disconnect 会关掉 socket，
     * 于是**每一张瓦片都要重新做一次 TLS 握手**。生产机实测（2026-10-02）：
     * 复用连接的请求 15 微秒，新建 TLS 连接 1,333 微秒 —— **89 倍**。
     * 正确做法就是"设超时 → 读流 → 关流（`use {}` 会关）→ 什么都不做，让池自己管"。
     */
    private fun httpGet(url: String): ByteArray? = try {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = TILE_CONNECT_TIMEOUT_MS
        conn.readTimeout = TILE_READ_TIMEOUT_MS
        if (conn.responseCode != 200) {
            conn.errorStream?.close()
            null
        } else {
            conn.inputStream.use { it.readBytes() }
        }
    } catch (_: Exception) {
        null
    }
}

/**
 * 瓦片磁盘缓存：**只缓存浏览过的**（浏览驱动，没有任何预先下载），LRU 淘汰，有上限。
 *
 * 为什么落在 `externalCacheDir/tiles`：
 * · 它是 App 私有目录 —— Android 10+ **不会**被 MediaStore 扫描。⚠️ 90 万个 `.jpg` 放公共存储
 *   会被系统媒体库爬（手机发热耗电、相册里冒出几十万张卫星图）。
 * · `cacheDir` 语义正确：系统设置里显示为「缓存」，用户能一键清、系统也能回收。
 * · ⛔ 不用 `filesDir`：那会计入"应用数据"，用户看到"这个 App 占了我 1 个 G"会直接卸载。
 */
internal class TileDiskCache(private val root: File, private val capBytes: Long) {

    private val approxSize = AtomicLong(-1L)
    private val trimming = AtomicBoolean(false)

    private fun file(zoom: Int, x: Int, y: Int): File = File(root, "$zoom/$x/$y.jpg")

    fun read(zoom: Int, x: Int, y: Int): ByteArray? {
        val f = file(zoom, x, y)
        if (!f.isFile) return null
        return try {
            val b = f.readBytes()
            touch(f)
            b
        } catch (_: Exception) {
            null
        }
    }

    fun write(zoom: Int, x: Int, y: Int, bytes: ByteArray) {
        try {
            val f = file(zoom, x, y)
            f.parentFile?.mkdirs()
            // 先写 .part 再改名：中途被杀不会留下半张能被读到的瓦片
            val tmp = File(f.parentFile, f.name + ".part")
            tmp.writeBytes(bytes)
            if (!tmp.renameTo(f)) {
                tmp.delete()
                return
            }
            val n = approxSize.get()
            if (n >= 0) approxSize.addAndGet(bytes.size.toLong())
            trimIfNeeded()
        } catch (_: Exception) {
            // 缓存写失败不是错误：下次重新下载就是
        }
    }

    /**
     * 超过上限就**在后台**淘汰。⛔ 不能在这里同步扫目录 ——
     * 这个函数是从瓦片线程调的，扫 9 万个文件要一两秒，会把这一格瓦片卡住。
     */
    private fun trimIfNeeded() {
        val sz = approxSize.get()
        if (sz in 0..(capBytes - 1)) return
        if (!trimming.compareAndSet(false, true)) return
        HiResTileLayer.executor().execute {
            try {
                trim()
            } catch (_: Exception) {
            } finally {
                trimming.set(false)
            }
        }
    }

    private fun trim() {
        val entries = ArrayList<Pair<File, Long>>()
        var total = 0L
        root.walkTopDown().forEach { f ->
            if (f.isFile) {
                entries.add(f to f.lastModified())
                total += f.length()
            }
        }
        approxSize.set(total)
        if (total <= capBytes) return
        entries.sortBy { it.second }                       // 最旧的先删
        val target = capBytes / 10 * 9                     // 删到 90%，避免刚删完又超
        var cur = total
        for ((f, _) in entries) {
            if (cur <= target) break
            val len = f.length()
            if (f.delete()) cur -= len
        }
        approxSize.set(cur)
    }

    /** 读一次就更新一次 mtime 会让"写"变成每张瓦片都有的开销，所以**六小时内只碰一次**。 */
    private fun touch(f: File) {
        val now = System.currentTimeMillis()
        if (now - f.lastModified() > 6L * 3600 * 1000) f.setLastModified(now)
    }

    /** 当前占用（字节）。⚠️ 首次调用要扫一遍目录，**别在 UI 线程上调**。 */
    fun sizeBytes(): Long {
        val v = approxSize.get()
        if (v >= 0) return v
        val total = root.walkTopDown().filter { it.isFile }.sumOf { it.length() }
        approxSize.set(total)
        return total
    }

    /** 清空缓存（给设置页的「清理离线地图缓存」用）。 */
    fun clear() {
        try {
            root.deleteRecursively()
            approxSize.set(0L)
        } catch (_: Exception) {
        }
    }
}
