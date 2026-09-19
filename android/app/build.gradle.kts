import java.util.Properties

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// local.properties 不会自动暴露为 Gradle 项目属性，必须显式读取（amap_key / api_base_url 都在这里配）
val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "com.tapmoay.sorders"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.tapmoay.sorders"
        minSdk = 26
        targetSdk = 35
        // 版本号统一「yyyyMMdd * 100 + 当日序号」：2026091501 = 2026-09-15 的第 1 次打包。
        // 当日要打第二个包就显式覆盖 -PappVersionCode=2026091502。
        //
        // ⚠️ 缺省值不要再改回 System.currentTimeMillis()/1000 那种秒级时间戳：
        //    它和日期式**不同量纲**（1789426316 vs 2026091501），两种方案混着打，
        //    后打的包 versionCode 反而更小 → 安卓直接拒绝安装（"应用未安装"），
        //    对外表现就是用户报的「下载完成之后并没有更新」。
        //    2026-09-14 推到生产的那个包正是时间戳式（1789426316）。
        versionCode = (project.findProperty("appVersionCode") as String?)?.toIntOrNull()
            ?: (SimpleDateFormat("yyyyMMdd", Locale.US).format(Date()).toInt() * 100 + 1)
        versionName = (project.findProperty("appVersionName") as String?)
            ?: ("1.0.0." + SimpleDateFormat("yyyyMMdd").format(Date()))

        // 高德 Key：在 android/local.properties 配置 amap_key=xxx（高德开放平台 Android SDK Key）
        val amapKey = localProps.getProperty("amap_key") ?: ""
        manifestPlaceholders["amapKey"] = amapKey
        // search SDK 官方初始化为 ServiceSettings.setApiKey，代码里显式注入
        buildConfigField("String", "AMAP_KEY", "\"" + amapKey + "\"")
        // 后端地址：api_base_url=http://192.168.x.x:8000（模拟器访问宿主机用 http://10.0.2.2:8000）
        // ⚠️ 发版时**不要**去改 `local.properties`（改了就得记得改回来，忘了的话本地调试会直接打生产库），
        //    用 `-PapiBaseUrl=http://8.145.40.22` 覆盖即可（见 `_tools/deploy/publish_apk.py` 的提示）。
        val apiBaseUrl = (project.findProperty("apiBaseUrl") as String?)
            ?: localProps.getProperty("api_base_url") ?: "http://10.0.2.2:8000"
        buildConfigField("String", "API_BASE_URL", "\"" + "$apiBaseUrl" + "\"")
        val apiFallbackIp = localProps.getProperty("api_fallback_ip") ?: ""
        buildConfigField("String", "DNS_FALLBACK_IP", "\"" + "$apiFallbackIp" + "\"")
    }

    // ── ABI 分流：整包瘦身的最大一笔（2026-09-15）────────────────────────────
    // 高德地图 SDK 每个 ABI 各带一份 9~14MB 的原生库，五个 ABI 全塞进一个包，
    // 光 lib/ 就 45.7MB，占整包（74.5MB）的 65%。而一台真机只需要其中一个。
    //
    //   phone → arm64-v8a（2016 年之后的所有手机）+ armeabi-v7a（老机器）  约 51MB
    //   emu   → x86_64（只有模拟器用）                                     约 35MB
    //
    // 为什么用 productFlavor 而不是 splits.abi：AGP 给 ABI 分包的 versionCode 会 **乘 10**，
    // 2026091501 * 10 = 20260915010 直接撑爆 32 位 int（上限 2147483647）。
    // 版本号一乱，安装器又会拒装。flavor 不动 versionCode，两个包平级。
    //
    // 出包命令随之变化（publish 脚本已封装，日常不用手敲）：
    //   手机包  gradle -p android assemblePhoneDebug    → outputs/apk/phone/debug/app-phone-debug.apk
    //   模拟器  gradle -p android assembleEmuDebug      → outputs/apk/emu/debug/app-emu-debug.apk
    //   单测    gradle -p android testPhoneDebugUnitTest
    flavorDimensions += "abi"
    productFlavors {
        create("phone") {
            dimension = "abi"
            ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
        }
        create("emu") {
            dimension = "abi"
            ndk { abiFilters += "x86_64" }
        }
    }

    buildTypes {
        debug {
            // 本地联调打印请求日志
            buildConfigField("Boolean", "DEBUG_LOG", "true")
        }
        release {
            // ⛔ **release 必须签名**（2026-09-19 全项目报告 P0-2，high）：本文件原来没有任何
            //    `signingConfigs` 块，release 也没设 `signingConfig` → release 产物是**未签名的**
            //    （根本装不上）→ 日常只能发 debug 变体 → 生产上跑的是 `debuggable=true` 的包：
            //    一次 USB 连接 + `adb shell run-as com.tapmoay.sorders` 就能直读会话令牌
            //    （DataStore 里的 JWT 是明文），`DEBUG_LOG=true` 还把登录口令与 JWT 打进 logcat。
            //    用**同一把 debug keystore** 签 release：签名指纹不变 → 存量用户可以直接升级，
            //    不需要"换密钥 → 全员卸载重装"（`docs/APP_UPDATE_AND_RELEASE.md` 里那个前提
            //    在"不换密钥"的做法下不成立）。发布脚本另有两道闸：产物不许 debuggable、
            //    证书指纹必须与线上一致（`_tools/deploy/publish_apk.py`）。
            signingConfig = signingConfigs.getByName("debug")
            // ⚠️ R8：release 变体**从来没被发布过**，所以"混淆之后还能不能跑"从没被验证过
            //    （Socket.IO / 反射那类代码最容易在这里出事）。先把"能装、能跑"拿到手，
            //    混淆作为**独立的一次改动**再开——两件事一起改，出问题时无法判断是谁的锅。
            isMinifyEnabled = false
            buildConfigField("Boolean", "DEBUG_LOG", "false")
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
    lint {
        abortOnError = false
    }
    testOptions {
        // 纯逻辑单测里万一碰到 android.util.* 等桩方法，返回默认值而不是抛 "not mocked"
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.datastore.preferences)

    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.retrofit)
    implementation(libs.retrofit.kotlinx.serialization)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation(libs.socketio.client)
    implementation(libs.coil.compose)

    // 高德：定位 + 地图 + 搜索（Key 在 local.properties 经 manifestPlaceholders 注入）
    implementation(libs.amap.map3d)
    implementation(libs.amap.search)

    debugImplementation(platform(libs.androidx.compose.bom))
    debugImplementation(libs.androidx.compose.ui.tooling)

    // 纯 JVM 单元测试（AI agent 循环逻辑；不联网、不依赖 Android 框架）
    testImplementation(libs.junit)
}