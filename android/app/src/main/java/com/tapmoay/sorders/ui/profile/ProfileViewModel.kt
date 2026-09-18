package com.tapmoay.sorders.ui.profile

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.FileProvider
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tapmoay.sorders.BuildConfig
import com.tapmoay.sorders.core.ApiClient
import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.AppVersionDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.util.concurrent.TimeUnit

class ProfileViewModel(private val container: AppContainer) : ViewModel() {

    var user by mutableStateOf<UserDto?>(null)
    var loading by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    // 更新检测状态：idle / checking / confirm(有新版) / needInstallPermission / downloading / installing / latest
    var updateState by mutableStateOf("idle")
    var latest by mutableStateOf<AppVersionDto?>(null)
    var updateMessage by mutableStateOf<String?>(null)
    var downloadProgress by mutableStateOf(0)

    /** 下载中的第二行字：速度 / 已下多少 / 还剩多久（见 UpdateProgress）。 */
    var downloadDetail by mutableStateOf("")
    val currentVersion: String get() = BuildConfig.VERSION_NAME

    init {
        loadMe()
    }

    fun loadMe() {
        loading = true
        error = null
        viewModelScope.launch {
            try {
                val me = container.api.userApi.me()
                user = me
                // 同步姓名到会话存储
                container.tokenStore.save(
                    com.tapmoay.sorders.core.Session(
                        token = container.tokenStore.cachedToken() ?: return@launch,
                        role = me.role,
                        userId = me.id,
                        username = me.username,
                        fullName = me.fullName,
                    )
                )
            } catch (e: Exception) {
                error = ApiClient.toApiException(e).message
            } finally {
                loading = false
            }
        }
    }

    fun logout(onDone: () -> Unit) {
        viewModelScope.launch {
            container.socketManager.disconnect()
            container.tokenStore.clear()
            onDone()
        }
    }

    /** 检查更新：对比服务端 version.json 与当前安装版本 */
    fun checkUpdate() {
        if (updateState == "checking" || updateState == "downloading") return
        updateState = "checking"
        updateMessage = null
        viewModelScope.launch {
            try {
                val info = container.repo.checkUpdate()
                if (info.version.isNullOrBlank() || info.url.isNullOrBlank()) {
                    updateMessage = "暂未发布新版本"
                    updateState = "latest"
                    return@launch
                }
                // 有 versionCode 就以它为准（>0 才算有效），没有才退回比版本名。
                // 理由：安卓安装时只认 versionCode。若我们报「有新版本」而它的 versionCode
                // 并不比本机大，用户下完只会看到系统安装失败——那比不提示更伤。
                val theirCode = info.versionCode ?: 0
                val isNewer = if (theirCode > 0) theirCode > BuildConfig.VERSION_CODE
                else info.version != currentVersion
                if (!isNewer) {
                    updateMessage = "当前已是最新版本（v" + currentVersion + "）"
                    updateState = "latest"
                    return@launch
                }
                latest = info
                updateState = "confirm"
            } catch (e: Exception) {
                updateMessage = humanError(e)
                updateState = "latest"
            }
        }
    }

    /** 下载并安装新版 APK（OkHttp 流式 → cacheDir/updates → 触发系统安装器） */
    fun downloadAndInstall(ctx: Context) {
        val info = latest ?: return
        val url = info.url ?: return
        if (!url.startsWith("http")) {
            updateMessage = "下载地址无效"
            updateState = "latest"
            return
        }
        // 先问系统"本 App 能不能装应用"，再决定下不下载。
        // 反过来（先下 50MB 再被系统拦）的代价是：用户在系统弹的英文提示上点 Cancel，
        // 结论就是"下载完了但没更新"——2026-09-15 真机上就是这么发生的。
        if (!canInstallPackages(ctx)) {
            updateState = "needInstallPermission"
            return
        }
        updateState = "downloading"
        downloadProgress = 0
        downloadDetail = "正在连接服务器…"
        viewModelScope.launch {
            try {
                val apk = download(ctx, url, info.version.orEmpty())
                installApk(ctx, apk)
            } catch (e: Exception) {
                updateMessage = humanError(e)
                updateState = "latest"
            }
        }
    }

    /** 「安装未知应用」是否已对本 App 放行。Android 8.0 起装 APK 必须过这一关。 */
    fun canInstallPackages(ctx: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.O || ctx.packageManager.canRequestPackageInstalls()

    /** 跳到系统的「安装未知应用」开关页（本 App 的那一条），用户打开后返回重试即可。 */
    fun openInstallPermissionSettings(ctx: Context) {
        try {
            ctx.startActivity(
                Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + ctx.packageName),
                ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
        } catch (e: Exception) {
            updateMessage = "打不开系统设置，请手动到「设置 → 应用 → 特殊权限 → 安装未知应用」里允许本应用。"
            updateState = "latest"
            return
        }
        updateState = "idle"
    }

    /**
     * 下载 APK 到 `cacheDir/updates/`。三个刻意的设计：
     *
     * ① **必须落在 `updates/` 子目录**——`res/xml/file_paths.xml` 只把该目录交给了 FileProvider。
     *    放到 cacheDir 根下，`getUriForFile` 会抛 IllegalArgumentException，
     *    表现就是「进度跑到 100% 然后什么都没发生」（用户报的「下载完没更新」）。
     * ② **断点续传**：先写 `.part` 并带 `Range` 续下。40MB 的包在手机网络上下到一半断了，
     *    应该从一半继续，而不是回到 0；`.part` 按版本名区分，换版本不会拿旧字节拼新包。
     * ③ **不在每个分片里切主线程**：循环只累计字节，UI 状态按 0.4 秒节流更新一次。
     */
    private suspend fun download(ctx: Context, url: String, versionTag: String): File =
        withContext(Dispatchers.IO) {
            val dir = File(ctx.cacheDir, UPDATE_DIR)
            if (!dir.isDirectory && !dir.mkdirs()) {
                throw IllegalStateException("无法创建更新缓存目录：" + dir.absolutePath)
            }
            // 清掉别的版本的残包（保留本版本自己的 .part，那是给续传用的）
            val target = File(dir, apkName(versionTag))
            val part = File(dir, partName(versionTag))

            // 这个版本的包已经完整下过一次了（典型场景：上次卡在"允许安装应用"那一步）
            // → 直接复用，不再白下 50MB。文件名带版本名，所以不会拿旧版本的包去装新版本。
            if (target.isFile && target.length() >= MIN_APK_BYTES && looksLikeZip(target)) {
                downloadProgress = 100
                downloadDetail = "安装包已下载好（" + UpdateProgress.humanSize(target.length()) + "），正在打开安装界面"
                return@withContext target
            }

            dir.listFiles()?.forEach { f ->
                if (f.isFile && f.name != part.name && f.name != target.name) f.delete()
            }

            val client = OkHttpClient.Builder()
                .connectTimeout(20, TimeUnit.SECONDS)
                .readTimeout(60, TimeUnit.SECONDS) // 单次读超时（不是整体超时），慢网也能下完
                .build()

            var done = if (part.isFile) part.length() else 0L
            val req = Request.Builder().url(url)
                .apply { if (done > 0) header("Range", "bytes=$done-") }
                .build()

            var total = -1L
            client.newCall(req).execute().use { resp ->
                if (resp.code == 416 && done > 0) {
                    // 服务端认为我们的续传起点非法（多半是它那边的包已经换了）→ 丢掉重来
                    part.delete()
                    throw IllegalStateException("服务器上的安装包已经变了，请再点一次「检查更新」重新下载")
                }
                if (!resp.isSuccessful) {
                    throw IllegalStateException("下载失败（HTTP " + resp.code + "）")
                }
                val body = resp.body ?: throw IllegalStateException("下载失败：服务器没有返回内容")
                // 206 = 服务端接受了续传；200 = 它忽略了 Range，只能从头写
                val append = resp.code == 206 && done > 0
                if (!append) done = 0L
                val bodyLen = body.contentLength()
                total = if (bodyLen > 0) bodyLen + done else -1L

                val startAt = done
                val startNs = System.nanoTime()
                FileOutputStream(part, append).use { os ->
                    body.byteStream().use { ins ->
                        val buf = ByteArray(64 * 1024)
                        var lastTick = 0L
                        while (true) {
                            val n = ins.read(buf)
                            if (n < 0) break
                            os.write(buf, 0, n)
                            done += n
                            val now = System.nanoTime()
                            if (now - lastTick >= UI_TICK_NS) {
                                lastTick = now
                                val secs = (now - startNs) / 1_000_000_000.0
                                // 全程平均速度（不是 0.4 秒瞬时值）——算剩余时间更稳，不会一跳一跳
                                val bps = if (secs > 0.5) (done - startAt) / secs else 0.0
                                publish(done, total, bps)
                            }
                        }
                    }
                }
                publish(done, total, 0.0)
                if (total > 0 && done != total) {
                    throw IllegalStateException(
                        "下载不完整（" + UpdateProgress.humanSize(done) + " / " +
                            UpdateProgress.humanSize(total) + "）：再点一次「检查更新」会从中断处继续"
                    )
                }
            }

            if (!part.renameTo(target)) {
                part.copyTo(target, overwrite = true)
                part.delete()
            }
            if (target.length() < MIN_APK_BYTES) {
                target.delete()
                throw IllegalStateException(
                    "下载到的文件只有 " + UpdateProgress.humanSize(target.length()) + "，不像是安装包，请重试"
                )
            }
            // APK 本质是 zip，头 4 字节固定 PK\x03\x04。
            // 服务器返回错误页/被截断时这里就拦住，否则用户只会看到系统安装器说
            // 「解析软件包时出现问题」，完全不知道是哪一步坏了。
            if (!looksLikeZip(target)) {
                target.delete()
                throw IllegalStateException("下载到的不是安装包（可能是服务器返回的错误页），请把这个情况告诉开发者")
            }
            target
        }

    /** 调起系统安装器。这里以前把 FileProvider 的英文异常原样弹给用户，现在换成一句人话 + 一句补救。 */
    private suspend fun installApk(ctx: Context, apk: File) {
        val authority = BuildConfig.APPLICATION_ID + ".fileprovider"
        val uri = try {
            FileProvider.getUriForFile(ctx, authority, apk)
        } catch (e: Exception) {
            throw IllegalStateException(
                "安装包已经下好了，但系统不认它的存放路径（" + e.message + "）。" +
                    "这是 App 自身的问题，请把这句话发给开发者。",
                e
            )
        }
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        withContext(Dispatchers.Main) {
            try {
                ctx.startActivity(intent)
                updateState = "installing"
                downloadDetail = ""
            } catch (e: Exception) {
                updateMessage = "打不开系统安装器：" + (e.message ?: "未知原因") +
                    "\n安装包已经下载完成，再点一次「检查更新」可以重试。"
                updateState = "latest"
            }
        }
    }

    /** 进度回写。可以从任意线程调用：Compose 的快照状态写入是线程安全的。 */
    private fun publish(done: Long, total: Long, bytesPerSec: Double) {
        if (total > 0) downloadProgress = ((done * 100) / total).toInt().coerceIn(0, 100)
        downloadDetail = UpdateProgress.detailLine(done, total, bytesPerSec)
    }

    private fun looksLikeZip(f: File): Boolean = try {
        val head = ByteArray(4)
        FileInputStream(f).use { it.read(head) }
        head[0] == 0x50.toByte() && head[1] == 0x4B.toByte() &&
            head[2] == 0x03.toByte() && head[3] == 0x04.toByte()
    } catch (e: Exception) {
        false
    }

    /**
     * 错误文案统一出口。我们自己抛的 IllegalStateException 已经是给用户看的中文，
     * 直接用；其余走 ApiClient 的统一转换（网络/超时/HTTP 都有专门措辞）。
     */
    private fun humanError(e: Exception): String {
        if (e is IllegalStateException && !e.message.isNullOrBlank()) return e.message!!
        val m = ApiClient.toApiException(e).message
        return if (m.isNullOrBlank()) "更新失败：" + e.javaClass.simpleName else m
    }

    private fun apkName(tag: String) = "sorders-" + safeTag(tag) + ".apk"
    private fun partName(tag: String) = apkName(tag) + ".part"

    /** 版本名来自服务端，只允许字母数字点横线，防止拼出奇怪的路径。 */
    private fun safeTag(tag: String): String {
        val t = tag.filter { it.isLetterOrDigit() || it == '.' || it == '-' || it == '_' }
        return if (t.isBlank()) "update" else t
    }

    private companion object {
        const val UPDATE_DIR = "updates"

        /** 40MB 起步的包，小于 5MB 一定是错的东西，不必再交给安装器。 */
        const val MIN_APK_BYTES = 5L * 1024 * 1024

        /** UI 刷新节流：0.4 秒一次，而不是每个 64KB 分片一次。 */
        const val UI_TICK_NS = 400_000_000L
    }
}
