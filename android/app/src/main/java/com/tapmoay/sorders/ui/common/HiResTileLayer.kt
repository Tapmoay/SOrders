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
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.Future
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
 * ```text
 * z <= 14  ->  NO_TILE   （高德自己的影像）
 * z == 15  ->  用 z16 的 2x2 合成
 * z == 16  ->  直接取 z16
 * z == 17  ->  用 z18 的 2x2 合成
 * z == 18  ->  直接取 z18
 * z == 19  ->  用 z20 的 2x2 合成
 * z >= 20  ->  直接取 z20
 * ```
 *
 * ⚠️ **服务器上只放了 16 / 18 / 20 三层**（[BASE_ZOOMS]），它们正好隔 2 ⇒
 * 每个奇数层都是相邻偶数层的 **2×2**，**永远只取 4 张**。这不是巧合，是刻意的：
 * 只放偶数层能省掉一半上传量，而"2 倍"是唯一一种**逐像素无损**的降采样比例
 * （4 倍就得先拼 4×4=16 张、还要 1024×1024 的中间位图，内存和请求数都爆）。
 *
 * ⛔ **不要为了少传几层就把 [BASE_ZOOMS] 拉稀**：间距一旦大于 1，[MAX_SPLIT] 就必须跟着放大，
 * 而那是请求数按 4 的幂次增长（间距 2 → 16 张/格）。
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

/** 等 4 张基座瓦片回来的上限。超过就整块放弃（回落高德），绝不让地图卡住。 */
private const val TILE_FETCH_WAIT_SEC = 20L

/** 合成瓦片的 JPEG 质量。奇数层都是过渡层（真要找门会放到最细的那层），不必给太高。 */
private const val TILE_JPEG_QUALITY = 85

/** 「这张确实没有」记多久。数据边界上的洞是**稳定**的（那块地本来就没抓），所以可以记久一点。 */
private const val MISSING_TTL_MS = 10 * 60 * 1000L

/** 负面缓存的上限。到顶就整体清空 —— 简单但有界，⛔ 不要让它无界增长。 */
private const val MISSING_MAX = 8192

internal object HiResTileLayer {

    /** 从这一层起改用自备影像。低层级一律 [TileProvider.NO_TILE] 交回高德。 */
    const val HI_ZOOM: Int = 15

    /**
     * 服务器上**真实存在**的层级（升序，见 `_tools/map/_upload_tiles.py`）。
     * 其余层级由"≥ 它、且差距不超过 [MAX_SPLIT] 的那一层"合成。
     *
     * ⚠️ 实测这三层的**覆盖范围并不一样**（是数据本身决定的，不是缺陷）：
     * ```text
     * z20  817 km²    经 116.75–117.09 / 纬 29.16–29.45
     * z18  2,725 km²  经 116.58–117.19 / 纬 29.09–29.61
     * z16  23,400 km² 经 116.39–118.39 / 纬 27.93–29.58
     * ```
     * ⇒ 越放大覆盖越窄，出了范围就回落高德。这跟真实地图金字塔的行为一致
     * （全球底图 + 城市高清），⛔ 不要试图把它们"对齐"。
     */
    val BASE_ZOOMS: IntArray = intArrayOf(16, 18, 20)

    /**
     * 最多允许"一层顶几层"：2^[MAX_SPLIT] 格合成。
     * `= 1` ⇒ 只做 2×2（4 张）。见类注释里为什么不让它变大。
     */
    private const val MAX_SPLIT = 1

    const val TILE_PX: Int = 256

    /**
     * 磁盘缓存上限。
     *
     * 为什么是 1.5 GB（2026-10-02 从 1 GB 上调）：现在服务的是 **6 个层级**，不是 2 个。
     * 实测「固定跑一个乡镇的派单员」把片区滑一遍大约是：z20 约 300 MB + z19 约 75 MB +
     * z18 约 740 MB（z18 覆盖面积是 z20 的 3.3 倍）+ z15/z16/z17 几 MB ≈ **1.1 GB**。
     * 1 GB 会刚好在门槛上反复淘汰，1.5 GB 留出余量。
     *
     * ⛔ 上限本身不能取消：「只缓存浏览过的」≠「不会涨」—— 天天跑同几条路，半年后也能
     * 把整个片区攒下来。有界是**必需品**，只是界要跟着层级数走。
     */
    private const val CACHE_CAP_BYTES = 1536L * 1024 * 1024   // 1.5 GB

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
     * 奇数层要**并发**取 4 张基座瓦片（串行的话延迟是 4 倍，肉眼可见卡顿）。
     * 池子里的任务**不等待任何东西**，所以 [TileProvider.getTile] 所在的高德瓦片线程
     * 阻塞在这里是安全的（不存在互相等待）。
     *
     * ⚠️ 池子大小要与**服务端的 HTTP/2** 配套看：没开 HTTP/2 时每个并发都要独立 TCP+TLS，
     * 开了一条连接就能多路复用（生产机 2026-10-02 开了）。
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

    // ── 负面缓存（"这张确实没有"）────────────────────────────────────────────
    //
    // 为什么必须有这一层（2026-10-02 实测）：高德对**拿不到**的格子会**反复来问** ——
    // 一次验收里，z17 上两个位于数据边界的洞在 13 秒内被问了 **27 次/格**。
    // 没有这层记忆的话，每次重试都要「查磁盘缓存（miss）→ 发一次 HTTPS → 收 404」，
    // 纯属白烧流量与电；用户沿着覆盖边界拖地图时这个量会更大。
    //
    // ⚠️ **只记 404**（后端明确说"没有"）。超时 / 连不上这类**传输失败不许记** ——
    // 那是暂时的，记下来会让一块本来有数据的瓦片在 10 分钟里一直显示不出。
    private val missing = ConcurrentHashMap<String, Long>()

    /** 这张是不是刚问过、后端说没有。 */
    fun isKnownMissing(key: String): Boolean {
        val until = missing[key] ?: return false
        if (until > System.currentTimeMillis()) return true
        missing.remove(key)
        return false
    }

    /** 记下"后端说这张没有"。 */
    fun rememberMissing(key: String) {
        if (missing.size >= MISSING_MAX) missing.clear()
        missing[key] = System.currentTimeMillis() + MISSING_TTL_MS
    }

    /**
     * 这一层该用哪个基座层 —— 整个层级门控就靠这一个函数。
     *
     * 返回 `null` = 我们不管这一层（调用方返回 `NO_TILE`，地图透出高德瓦片）。
     * 返回 `== zoom` = 服务器上直接有；返回 `> zoom` = 用它的 2^(差) × 2^(差) 合成。
     */
    fun baseFor(zoom: Int): Int? {
        if (zoom < HI_ZOOM) return null
        return BASE_ZOOMS.firstOrNull { it >= zoom && it - zoom <= MAX_SPLIT }
    }
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
        // ★ 这一个函数就是"缩小时自动换回高德"的全部实现（z≤14 或没有基座层时返回 null）
        val base = HiResTileLayer.baseFor(zoom) ?: return TileProvider.NO_TILE

        val bytes = try {
            if (base == zoom) fetchTile(base, x, y) else compose(zoom, x, y, base)
        } catch (_: Exception) {
            // 任何异常都只是"这一格没有" —— ⛔ 绝不把异常抛回给地图 SDK
            null
        }

        // 没有就返回 NO_TILE：地图透出高德底图。
        // ⛔ 不要合成/返回"半张灰图"—— 那看起来像"这一片没有影像"，比回落更糟。
        return if (bytes == null) TileProvider.NO_TILE
        else Tile(HiResTileLayer.TILE_PX, HiResTileLayer.TILE_PX, bytes)
    }

    /**
     * 用 [base] 层的 2^n × 2^n 格合成 [zoom] 层的一张瓦片（n = base - zoom）。
     *
     * ⚠️ 当前配置下 **n 恒为 1**（基座层隔 2 排布），但代码按通用写 ——
     * 万一以后加了间距更大的基座层，这里不用改（只要 [HiResTileLayer.MAX_SPLIT] 允许）。
     *
     * 内存：**每张小图先缩到自己的格位再贴**，不建 2^n × 2^n 的大中间位图。
     * n=1 时峰值约 256KB(输出) + 256KB(解码) + 64KB(缩放) ≈ 576 KB；
     * 若按"先拼 512×512 再整体缩"是 1.3 MB，而 n=2 时那种写法要 4 MB/张 × 8 并发 = 32 MB，
     * **够 OOM 了** —— 所以这个写法不是微优化，是必须的。
     *
     * 质量：2:1 是逐像素无损的（每个输出像素正好平均 2×2 源像素，且瓦片边界与输出像素边界对齐），
     * 所以"每张小图各缩一半再拼"与"整体缩一半"结果**完全一样**。
     *
     * ⚠️ **合成结果刻意不写磁盘缓存**（只写它用到的 4 张基座瓦片）：
     * 光是 z19 一层的合成结果就有约 18.5 万张 ≈ 1.5 GB，写下去会把整个缓存预算吃光，
     * 而**基座瓦片本来就要缓存**（不写的话每次都要重新下载）。重复访问靠高德 SDK 自己的
     * 内存缓存（`TileOverlayOptions.memCacheSize`）兜住 —— 实测连续 12 次取同一批 z19
     * 只触发 12 次合成，SDK 没有重复来问。
     */
    private fun compose(zoom: Int, x: Int, y: Int, base: Int): ByteArray? {
        val shift = base - zoom
        val n = 1 shl shift
        val cell = HiResTileLayer.TILE_PX shr shift
        val bx = x shl shift
        val by = y shl shift

        // 并发取 n*n 张
        val futures = ArrayList<Future<ByteArray?>>(n * n)
        for (dy in 0 until n) {
            for (dx in 0 until n) {
                val qx = bx + dx
                val qy = by + dy
                futures.add(HiResTileLayer.executor().submit<ByteArray?> { fetchTile(base, qx, qy) })
            }
        }
        val parts = futures.mapNotNull { f ->
            try {
                f.get(TILE_FETCH_WAIT_SEC, TimeUnit.SECONDS)
            } catch (_: Exception) {
                null
            }
        }

        // ★ 缺一张就整块放弃。四格里有任何一格不在覆盖范围内（多边形边界），
        //   合成出来就是"四分之三有影像、四分之一是黑块"—— 那比直接回落高德更难看。
        if (parts.size != n * n) return null

        var out: Bitmap? = null
        return try {
            out = Bitmap.createBitmap(
                HiResTileLayer.TILE_PX, HiResTileLayer.TILE_PX, Bitmap.Config.ARGB_8888,
            )
            val canvas = Canvas(out)
            val paint = Paint(Paint.FILTER_BITMAP_FLAG)
            val dst = Rect()
            for (i in parts.indices) {
                val src = parts[i]
                val bmp = BitmapFactory.decodeByteArray(src, 0, src.size) ?: return null
                // 每张先缩到自己的格位（n=1 时 cell=128）
                val s = if (cell == HiResTileLayer.TILE_PX) bmp
                else Bitmap.createScaledBitmap(bmp, cell, cell, true)
                if (s !== bmp) bmp.recycle()
                val dx = (i % n) * cell
                val dy = (i / n) * cell
                dst.set(dx, dy, dx + cell, dy + cell)
                canvas.drawBitmap(s, null, dst, paint)
                s.recycle()
            }
            val bytes = ByteArrayOutputStream(24 * 1024)
            if (!out.compress(Bitmap.CompressFormat.JPEG, TILE_JPEG_QUALITY, bytes)) return null
            bytes.toByteArray()
        } catch (_: Exception) {
            null
        } finally {
            // ⛔ 必须回收：256×256 ARGB = 256 KB/张，来回缩放几次不回收就是 OOM
            out?.recycle()
        }
    }

    /** 取一张 [zoom] 层的瓦片：先查磁盘缓存，再查负面缓存，最后走网络；拿到就写缓存。 */
    private fun fetchTile(zoom: Int, x: Int, y: Int): ByteArray? {
        val cache = HiResTileLayer.cacheOf(ctx)
        cache.read(zoom, x, y)?.let { return it }

        val key = "$zoom/$x/$y"
        if (HiResTileLayer.isKnownMissing(key)) return null

        val (code, bytes) = httpGet(HiResTileLayer.tileUrl(zoom, x, y))
        if (bytes != null) {
            cache.write(zoom, x, y, bytes)
            return bytes
        }
        // ⚠️ **只有后端明确说"没有"才记负面缓存**；超时 / 断网不记（那是暂时的，
        //    记下来会让一块本来有数据的瓦片在 10 分钟里一直显示不出来）。
        if (code == 404) HiResTileLayer.rememberMissing(key)
        return null
    }

    /**
     * ⛔ **不要调 `connection.disconnect()`**。
     *
     * Android 的 `HttpURLConnection` 底下是 OkHttp 的连接池，主动 disconnect 会关掉 socket，
     * 于是**每一张瓦片都要重新做一次 TLS 握手**。生产机实测（2026-10-02）：
     * 复用连接的请求 15 微秒，新建 TLS 连接 1,333 微秒 —— **89 倍**。
     * 正确做法就是"设超时 → 读流 → 关流（`use {}` 会关）→ 什么都不做，让池自己管"。
     *
     * @return `(HTTP 状态码, 字节)`；异常时状态码为 **-1**。
     *   ⚠️ 调用方必须区分 **404（后端确实没有）** 与 **-1（传输失败）** ——
     *   只有前者能进负面缓存，见 [HiResTileLayer.rememberMissing]。
     */
    private fun httpGet(url: String): Pair<Int, ByteArray?> = try {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = TILE_CONNECT_TIMEOUT_MS
        conn.readTimeout = TILE_READ_TIMEOUT_MS
        val code = conn.responseCode
        if (code != 200) {
            conn.errorStream?.close()
            code to null
        } else {
            code to conn.inputStream.use { it.readBytes() }
        }
    } catch (_: Exception) {
        -1 to null
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
