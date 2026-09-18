# 打包、发布与应用内更新

<!-- ref-prefix: android/app/src/main/java/com/tapmoay/sorders/ -->

> 面向"要给用户发一个新版本"的场景。本文是 **2026-09-15** 那次排障的产物：
> 用户报「下载非常慢」+「下载完成之后并没有更新」，两个问题都不是"偶发"，
> 而是**代码里写死的**。下面每条都写明"错在哪、怎么发现的、现在怎么保证不再错"。

---

## 0. 这条链有 6 个环节，任何一环错了都表现为"下载完没反应"

| # | 环节 | 文件 | 一句话说明 |
|---|---|---|---|
| ① | 打包配置 | `android/app/build.gradle.kts` | versionCode 方案、ABI 分流（决定包多大、装不装得上） |
| ② | 版本声明 | 服务器 `ackend/uploads/app/version.json` | App「检查更新」读的就是它；**必须带 `versionCode`** |
| ③ | 下载 | `ui/profile/ProfileViewModel.kt::download` | 落到 `cacheDir/updates/`，断点续传 |
| ④ | 交给系统安装 | `ProfileViewModel::installApk` + `res/xml/file_paths.xml` | FileProvider 只肯暴露 `file_paths.xml` 里列出的目录 |
| ⑤ | 系统两道闸 | 安卓自身 | ①「安装未知应用」开关 ②versionCode 必须比已装的大 |
| ⑥ | 静态文件出口 | 生产 nginx + `backend/app/main.py` | `.apk` 的 Content-Type、是否占死 uvicorn worker |

**这 6 处没有任何编译期联系**——改错第 ④ 处不会报错，只会在用户手机上"进度 100% 然后什么都没发生"。
所以有一条红线检查兜底：`python _tools/deploy/_check_update_flow.py`（31 项，改坏立刻红）。

### 0.1 发真机包之前先跑这一条（2026-09-17 差点发错）

```bash
python _tools/deploy/check_phone_apk.py --apk <要发出去的包>
# ✅ 可以发 / ❌ N 项不过，别发
```

它查的是**这个包编译时用的是哪个后端地址**。坑在这里：

- `android/local.properties` 的 `api_base_url` 平时是**模拟器地址** `http://10.0.2.2:8000`；
- `ApiEndpoint` 对 `10.0.2.2` 是**直接用、连探测都不探测**（见 `core/ApiEndpoint.kt` 第一个分支）；
- 于是"忘了改地址"打出来的真机包，**装得上、打得开、看不出哪里不对**，
  只是登录一直转圈——因为它去连一个手机上根本不存在的主机。

正确流程：`api_base_url=http://8.145.40.22` → `assemblePhoneDebug` → **把 local.properties 改回模拟器地址**
（不改回去，以后打模拟器包会连生产）→ 用上面的脚本确认。

⚠️ 包里**另有** `http://10.0.2.2:8000` 是正常的：那是 `ApiEndpoint` 的模拟器兜底常量，
真机上 `isEmulator()=false` 永远走不到。别去删它，也别把它当"打进包里的地址"。

---

## 1. 打包：ABI 分流 + 版本号方案

### 1.1 为什么整包 74.5MB 是不正常的

高德地图 SDK 给**每个 CPU 架构**都塞一份 9~14MB 的原生库（`.so`）。原配置把 5 个架构全打进一个包：

| 目录 | 压缩后 | 说明 |
|---|---|---|
| `lib/arm64-v8a` | 13.94 MB | 2016 年之后的所有手机 |
| `lib/armeabi-v7a` | 8.83 MB | 老机器 |
| `lib/armeabi` | 8.82 MB | ARMv5，**早该淘汰** |
| `lib/x86_64` | 14.14 MB | 只有模拟器用 |
| `lib/x86` | 0.01 MB | 空壳 |
| `classes*.dex` | 20.42 MB | debug 不做 R8 混淆 |
| `assets/` | 3.61 MB | 高德地图资源 |

`lib/` 合计 45.7MB = **整包的 65%**，而一台真机只需要其中一个。

### 1.2 解法：两个 productFlavor

```kotlin
flavorDimensions += "abi"
productFlavors {
    create("phone") { dimension = "abi"; ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") } }
    create("emu")   { dimension = "abi"; ndk { abiFilters += "x86_64" } }
}
```

| 产物 | 体积 | 给谁 |
|---|---|---|
| `app-phone-debug.apk` | **47.4 MB**（原 71.1 MB，−33%） | 真机，也是**推到生产的那一个** |
| `app-emu-debug.apk` | 38.7 MB | x86_64 模拟器 |

**为什么不用 `splits.abi`**：AGP 给 ABI 分包的 versionCode 会**乘 10**，
`2026091501 * 10 = 20260915010` 直接超出 32 位 int 上限（2147483647）。
版本号一乱，安装器又会拒装。flavor 不动 versionCode，两个包平级。

> **还能更小吗**：能。真机全是 arm64 的话，`phone` flavor 只留 `arm64-v8a` → **约 38.6 MB**（−48%）。
> 代价是 armeabi-v7a 的老机器会「应用未安装」。**需要先确认团队在用的手机型号再决定。**

### 1.3 版本号：一套量纲，不許混用

```
versionCode = yyyyMMdd * 100 + 当日序号     例：2026091501 = 2026-09-15 的第 1 次打包
```

支持 `-PappVersionCode=2026091502` 覆盖（同日第二个包）。

> ⚠️ **这里出过真事故**：`build.gradle.kts` 原来的缺省值是
> `System.currentTimeMillis() / 1000`（秒级时间戳）。于是线上包是 **1789426316**，
> 而本地一直显式传日期式 **2026091501** —— 两套量纲混着打。
> 后打的包 versionCode 有可能反而更小，**安卓会直接拒绝安装**（"应用未安装"），
> 而且不会有任何日志告诉用户为什么。注释当时还写着"缺省递增日期戳"，
> **注释和代码说的不是一回事**——这也是它藏了这么久的原因。

### 1.4 构建命令

```powershell
$env:JAVA_HOME='D:\APPS\AndroidStudio\jbr'; $env:ANDROID_HOME='D:\APPS\sdk'
# 真机包（要推生产的就是它）
& ".\_agent\gradle\gradle-8.9\bin\gradle.bat" -p android assemblePhoneDebug `
    '-PappVersionName=1.0.0.20260915' '-PappVersionCode=2026091501'
# 模拟器包
& ".\_agent\gradle\gradle-8.9\bin\gradle.bat" -p android assembleEmuDebug '-PappVersionName=...' '-PappVersionCode=...'
# 单测（flavor 之后任务名带 flavor）
& ".\_agent\gradle\gradle-8.9\bin\gradle.bat" -p android testPhoneDebugUnitTest
```

⚠️ **必须用 Gradle 8.9**（`_agent/gradle/`）。Gradle 9.1.0 会报一堆假的 Kotlin 编译错误。
⚠️ `-P` 参数**整个加引号**，否则 PowerShell 会把 `=` 和后面的值拆开。

---

## 2. 推送：用脚本，不要手敲

```powershell
python _tools/deploy/publish_apk.py --note "修好应用内更新"
```

它做的事（前两条是"宁可推不出去，也不推出一个坏包"）：

1. **检查包里的后端地址**（见 §2.2）——是开发地址就直接中止；
2. 解析 APK 的 `versionCode` / `versionName`（aapt2），**和线上 version.json 里的 versionCode 比，不更大就中止**——这道闸门就是为了拦住 §1.3 那个事故；
3. `scp` 上传，写 `version.json`（含 `version` / `versionCode` / `url` / `size` / `note`），清历史包；
4. **回读** version.json 与 APK 响应头（要求 206 + `application/vnd.android.package-archive`）——不验证的发布等于没发布。

可选 `--installed-code <用户手机上的 versionCode>` 再加一道保险。

### 2.1 下载地址为什么要用 80 端口 + IP

`url` 形如 `http://8.145.40.22/static/uploads/app/sorders-<版本名>.apk`：

- **80 而不是 8080**：8080 在部分公司网络/运营商侧会被挡，80 到处都通；
- **IP 而不是域名**：不依赖手机上的 DNS（App 的 API 也是 IP 直连）。

### 2.2 ⚠️ 最容易发出去的一个坏包：后端地址被烧成了 10.0.2.2

`BuildConfig.API_BASE_URL` 来自 `android/local.properties` 的 `api_base_url`，**构建时烧进包里**：

| 文件 | 值 | 用途 |
|---|---|---|
| `android/local.properties`（改造前） | `http://10.0.2.2:8000` | 本机联调 / 模拟器 |
| `android/local.properties.bak` | `http://8.145.40.22:8080` | **生产值**（线上那个包用的就是它） |

而 `android/app/src/main/java/com/tapmoay/sorders/core/ApiEndpoint.kt` 的第一条分支是：

```kotlin
primary.startsWith("http://10.0.2.2") -> primary   // 显式本地配置：**不探测，直接用**
```

也就是说——**拿 `local.properties` 的当前值直接打包推到生产，所有真机都会去连 `10.0.2.2`
（那是模拟器指代宿主机的别名），整个 App 打不开。** 它的表现是"白屏/一直转圈"，
跟"更新失败"完全不像同一回事，排查会绕很远。

**所以 `publish_apk.py` 加了硬闸**：读 AGP 生成的
`android/app/build/generated/source/buildConfig/phone/debug/com/tapmoay/sorders/BuildConfig.java`，
命中 `10.0.2.2` / `127.0.0.1` / `localhost` / `192.168.` / `:8000` 等任一模式就**拒绝上传**。

> 为什么不读 `local.properties`：那份文件在构建之后随时可能被改，而包是几分钟前打的，
> 两者可以不一致。**要拦就拦真正编进包里的那个值。**

发版前的正确顺序：

```powershell
# 1) 换成生产地址（先备份开发用的那份，否则模拟器就连不上本机后端了）
Copy-Item android\local.properties android\local.properties.dev -Force
Copy-Item android\local.properties.bak android\local.properties -Force
# 2) 打包（versionCode 必须 > 线上）
gradle -p android assemblePhoneDebug '-PappVersionName=...' '-PappVersionCode=...'
# 3) 推送（脚本会自己再验一遍）
python _tools/deploy/publish_apk.py --note "..."
# 4) 换回开发地址
Copy-Item android\local.properties.dev android\local.properties -Force
```

---

## 3. 用户报的两个问题：根因与修法

### 3.1 「下载完成之后并没有更新」= FileProvider 根目录没覆盖 APK

**根因**（`res/xml/file_paths.xml`）：

```xml
<paths>
    <cache-path name="photos" path="photos/" />   <!-- 只有这一个 -->
</paths>
```

而 `ProfileViewModel` 把 APK 下到 **`cacheDir/sorders-update.apk`**（cacheDir 根下）。
`FileProvider.getUriForFile()` 要求文件必须落在声明的根底下，否则抛：

```
java.lang.IllegalArgumentException: Failed to find configured root that contains
    /data/user/0/com.tapmoay.sorders/cache/sorders-update.apk
```

（已用 `javap -c` 反编译 `androidx.core.content.FileProvider$SimplePathStrategy` 核实：
字节码 136~162 处就是这条 `IllegalArgumentException`。）

异常被外层 `catch` 吞掉 → 弹一个英文技术提示 → **系统安装器从来没被拉起过**。
用户看到的就是"进度跑到 100%，然后什么都没发生"。

**修法**：`file_paths.xml` 加 `<cache-path name="updates" path="updates/" />`，
下载目录改成 `cacheDir/updates/`。**两处必须同时改**——这也是红线检查第 1 条。

> 这个 bug 从基线 commit 起就在，也就是说：**应用内更新从来没成功过一次**。
> 历史版本都是靠浏览器手动下载安装的。

### 3.2 「下载非常慢」= 包太大 + 网页把它当文本 + 服务端被占死

三个独立原因叠在一起：

1. **包 74.5MB**（见 §1.1）→ 已降到 47.4MB；
2. **`Content-Type: text/plain`**：`main.py` 的静态路由只映射了图片/PDF，
   `.apk` 落到 Starlette `FileResponse` 的兜底分支，而那个兜底是 **`text/plain`**。
   手机浏览器拿到 `text/plain` 会去"渲染"几十 MB 二进制，而不是存成文件。
   → 后端显式声明 `application/vnd.android.package-archive` + `Content-Disposition`；
   → nginx 的 `mime.types` 也补了 apk 类型；
3. **下载占死 uvicorn worker**：`/static/` 原先 `proxy_pass` 到 uvicorn，而后端只有 **2 个 worker**。
   一个人下 74MB 就是一个长期占用的流式长连接 = 占死一个 worker；
   两个人同时下，整个 API（含 Socket.IO）都要排队。
   → 生产 nginx 改成 `location /static/uploads/ { alias /opt/SOrders/backend/uploads/; }` **直出磁盘**。
   （脚本：`_tools/deploy/_fix_nginx_static.py`，幂等，改完 `nginx -t && systemctl reload nginx`。）

顺带修掉的两个体验问题：

- 下载循环**每读 64KB 就 `withContext(Dispatchers.Main)` 往主线程跑一趟**（40MB ≈ 600 次往返，
  主线程还在同时重组进度条）。改成按 0.4 秒节流，且写 Compose 快照状态本身线程安全，不需要切线程；
- 界面上**只有百分比**，用户无法判断是"快好了"还是"卡住了"。
  现在显示 `1.2 MB/s · 已下 18.4 MB / 51.2 MB · 还剩 28 秒`（纯逻辑在 `UpdateProgress.kt`，有单测）。

### 3.3 还有第三道闸：安卓的「安装未知应用」开关

修完 3.1 之后，模拟器上安装器**成功弹出来了**，但立刻被系统拦下：

> "For your security, your phone currently isn't allowed to install unknown apps from this source."

这是一句英文系统提示，绝大多数人的下一步是点 Cancel，然后得出**和 3.1 一模一样的结论**。
而 `AndroidManifest.xml` 里的 `REQUEST_INSTALL_PACKAGES` 只声明了能力，**开关默认是关的**。

**修法**：
- `downloadAndInstall` **先检查** `packageManager.canRequestPackageInstalls()`，
  没放行就弹 App 自己的对话框「还差一步：允许安装应用」+「去设置」按钮
  （`Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES` 直达本 App 那一条），**并且不开始下载**（别白下 47MB）；
- 安装包按版本名落盘（`sorders-<版本名>.apk`），已经下好过一次就不再重下——
  用户去开完开关回来点「检查更新」是秒进的。

---

## 4. 怎么验证（模拟器，不用真机）

```powershell
# ① 造一个"假的新版本"给模拟器发现（versionCode 故意比本机大）
python _tools/deploy/_stage_local_update.py --apk <某个 apk> --version 1.0.0.20260918 --version-code 2026091801
# ② 本机后端必须在跑（模拟器走 10.0.2.2:8000）
cd backend; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# ③ App 里：我的 → 检查更新 → 下载并更新 → 看系统安装器是否被拉起、装完版本号变没变
# ④ 验「安装未知应用」分支
adb shell appops set com.tapmoay.sorders REQUEST_INSTALL_PACKAGES deny
#    → 此时点「下载并更新」应弹 App 自己的引导框，且**不开始下载**
# ⑤ 收尾
python _tools/deploy/_stage_local_update.py --clear
```

**2026-09-15 实测结果**（模拟器 `SOrdersAI`，Android 15 x86_64）：

| 步骤 | 结果 |
|---|---|
| 检查更新 | 弹「发现新版本 v1.0.0.20260918 / 当前版本 v1.0.0.20260917」 |
| 权限未开时点「下载并更新」 | ✅ 弹 App 引导框，**未开始下载**（top activity 仍是本 App） |
| 点「去设置」 | ✅ 直接打开「安装未知应用 → SOrders 派单送货」页 |
| 授权后重试 | ✅ 下载 → `com.android.packageinstaller.PackageInstallerActivity` 被拉起 |
| 点「更新」 | ✅ `InstallSuccess`；`dumpsys package` 显示 versionName=1.0.0.20260918 |
| 落盘位置 | ✅ `run-as ... ls cache/updates` → `sorders-1.0.0.20260918.apk`（40,627,695 B） |

证据截图：`_emu_need_perm.png`（引导框）、`_emu_settings_install_perm.png`（设置深链）、
`_emu_installer_update.png`（系统安装器）、`_emu_download_progress.png`（下载中显示
`8.5 MB/s · 已下 6.8 MB / 38.7 MB · 还剩 3 秒`）、`_emu_dl_9.png`（**未修之前**的英文拦截提示）。

---

## 5. 仍没做、需要决策的事

| # | 事项 | 收益 | 代价 / 风险 |
|---|---|---|---|
| 1 | **换成真正的 release 签名 + R8 混淆** | 包再小 ~14MB（dex 20.4→约 7MB），且去掉 `android:debuggable=true` | **签名变了，所有人必须卸载重装**（本地数据丢失：登录态、AI key、对话历史）。R8 还可能压坏 Socket.IO 的反射 |
| 2 | **只保留 arm64-v8a** | 47.4 → 约 38.6 MB | armeabi-v7a 的老机器会装不上；需先确认团队手机型号 |
| 3 | **提高 ECS 公网带宽** | 直接决定下载速度上限 | 要花钱；当前 EIP 是 `8.145.40.22`，带宽值只能到阿里云控制台看（实例元数据只给实例规格上限 200Mbps，给不出实际购买值）；从本机测不出——本机自己的下行只有 ~530 KB/s，成了瓶颈 |
| 4 | HTTP Range 断点续传已做；**分片下载**没做 | 多连接并行能再快一点 | 服务端与 CDN 都要配合，收益不确定 |

> 现状：生产上跑的是 **debug 构建**（`isMinifyEnabled=false`、`debuggable=true`、用公共 debug keystore 签名）。
> 对一个存着用户 API key 的业务 App 来说不理想，但**改成 release 签名会让所有已装用户装不上新版本**，
> 所以必须先安排一次"卸载重装"的窗口，不能随手改。

