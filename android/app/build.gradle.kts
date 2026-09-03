import java.util.Properties

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
        versionCode = 1
        versionName = "1.0.0"

        // 高德 Key：在 android/local.properties 配置 amap_key=xxx（高德开放平台 Android SDK Key）
        val amapKey = localProps.getProperty("amap_key") ?: ""
        manifestPlaceholders["amapKey"] = amapKey
        // search SDK 官方初始化为 ServiceSettings.setApiKey，代码里显式注入
        buildConfigField("String", "AMAP_KEY", "\"" + amapKey + "\"")
        // 后端地址：api_base_url=http://192.168.x.x:8000（模拟器访问宿主机用 http://10.0.2.2:8000）
        val apiBaseUrl = localProps.getProperty("api_base_url") ?: "http://10.0.2.2:8000"
        buildConfigField("String", "API_BASE_URL", "\"" + "$apiBaseUrl" + "\"")
    }

    buildTypes {
        debug {
            // 本地联调打印请求日志
            buildConfigField("Boolean", "DEBUG_LOG", "true")
        }
        release {
            isMinifyEnabled = true
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
}