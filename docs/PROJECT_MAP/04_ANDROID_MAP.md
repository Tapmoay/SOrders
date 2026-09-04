# 04 Android 端地图

> 包：`com.tapmoay.sorders`；源码：`android/app/src/main/java/com/tapmoay/sorders/`

## 1. 分层

```
MainActivity.kt / SOrdersApp.kt       # 入口 / Application（AppContainer 组装）
core/                                  # 基础设施
  ApiEndpoint.kt                       # ★ baseUrl：模拟器=10.0.2.2:8000，真机=BuildConfig.API_BASE_URL
  ApiClient.kt                         # Retrofit 单例（暴露各 Api interface + repo）
  AppContainer.kt                      # 依赖注入容器（api/repo/token/socket/tts...）
  TokenStore.kt                        # DataStore 会话（sessionFlow 是冷流！）
  SocketManager.kt                     # Socket.IO 连接管理
  RealtimeHub.kt                       # 事件→仓库刷新（订单/待派单/消息）
  AmapLocationManager.kt               # 高德定位（单例永不销毁！）
  BeepManager / TtsManager             # 提醒音/语音
data/
  remote/api/Apis.kt                   # ★ 全部 Retrofit 接口（按 domain 分组 interface）
  remote/dto/Dtos.kt                   # ★ 全部 DTO（@Serializable + FlexibleStringSerializer）
  repo/AppRepository.kt                # ★ 唯一数据入口（方法名≈接口）
ui/
  login/ Register/                     # 登录/注册
  home/ RoleHomeScreen / WorkbenchScreen   # 按角色底部 Tab + 工作台模块墙
  nav/ Routes.kt / NavGraph.kt / Modules.kt  # ★ 路由常量/导航图/工作台模块定义
  dispatcher/                          # 派单员 14 模块页 + ViewModel
  shipper/ driver/ order/ messages/ profile/
  common/                              # AppTopBar/SectionCard/Chart/时间导航/页签/订单卡...
  theme/                               # Color(语义色)/Theme/Type
util/
  Money.kt (formatMoney 两位小数) / TimeFmt.kt / AmapUri.kt(导航直拉)
  GeoResolver.kt / Watermark.kt / ExportUtil.kt(导出xlsx存Download)
```

## 2. 网络层关键约定

- **ApiEndpoint.kt**：`baseUrl = if (isEmulator()) "http://10.0.2.2:8000" else BuildConfig.API_BASE_URL`
  - isEmulator()：Build.FINGERPRINT/MODEL/PRODUCT 含 generic|emulator|vbox|sdk
  - 真机地址：`android/local.properties` → `api_base_url=http://<电脑IP>:8000`
- **Repo 方法**：`container.repo.xxx()`（AppRepository 一行委托到 api.xxxApi.xxx）
- **DTO 金额**：都是字符串，序列化走 `FlexibleStringSerializer`（后端 Decimal 可能是 "1104.5000"）
- **格式化**：`formatMoney(s)` → 两位小数文本（util/Money.kt）

## 3. 导航与路由（ui/nav/）

- `Routes.kt`：全部路由常量（如 `REPORT_HOME="report/home"`、`DISPATCH_ORDERS`、`orderDetail(id)` 函数路由）
- `NavGraph.kt`：NavHost 注册（每个 composable 传 `container` + onBack；注意 @OptIn/参数）
- `Modules.kt`：`Modules.dispatcherEntries`（工作台 14 模块：label/route/icon/color/children）；新增模块=这里 + NavGraph 两处

### 派单员工作台模块清单（Modules.kt 顺序）
1 派单作业(蓝)｜2 代理下单(绿)｜3 地址与联系人(湖蓝)｜4 订单管理(黄)｜5 司机管理(黄绿)｜6 货主管理(深青)｜7 批发商管理(金)｜8 商品管理(紫)｜9 库存管理(蓝青)｜10 账本管理(橙)｜11 司机运费结算(珊瑚橙)｜12 挂账单位(橙红)｜13 报表中心(靛紫)｜14 消息中心(红)

## 4. 各页面位置速查

| 功能 | Screen | ViewModel |
|---|---|---|
| 登录 | ui/login/LoginScreen.kt | LoginViewModel.kt |
| 角色主页/工作台 | ui/home/RoleHomeScreen.kt（★session==null 必须 Loading，防 AIOOBE） | WorkbenchScreen.kt |
| 待派单池 | ui/dispatcher/DispatcherPoolScreen.kt | DispatcherPoolViewModel.kt |
| 全部订单 | ui/dispatcher/DispatcherOrdersScreen.kt | DispatcherOrdersViewModel.kt |
| 代理下单 | ui/shipper/OrderCreateScreen.kt | OrderCreateViewModel.kt |
| 地址与联系人 | ui/shipper/AddressScreen.kt（线路/联系人/地点+抽屉） | AddressViewModel.kt |
| 订单管理 | 同 DispatcherOrdersScreen | |
| 司机管理/货主管理/批发商管理 | ui/dispatcher/UsersManageScreen.kt（pool=DRIVERS/SHIPPERS/MEMBERS） | UsersManageViewModel.kt |
| 批发商定价 | ui/dispatcher/WholesalePricingScreen.kt | WholesalePricingViewModel.kt |
| 批量调价 | ui/dispatcher/BatchPriceSheets.kt（通用 sheet） | —（VM.batchPrice） |
| 商品管理 | ui/dispatcher/ProductsScreen.kt | ProductsViewModel.kt |
| 库存管理 | ui/dispatcher/InventoryScreen.kt | InventoryViewModel.kt |
| 账本管理 | ui/dispatcher/DispatcherLedgerScreen.kt（订单账/司机账/货主账/批发商账+工具） | DispatcherLedgerViewModel.kt |
| 账本工具（收款/开销/结算/车辆） | ui/dispatcher/AccountToolsScreens.kt | （复用） |
| 司机运费结算 | ui/dispatcher/FreightSettlementScreen.kt | FreightSettlementViewModel.kt |
| 挂账单位 | ui/dispatcher/ArrearsUnitsScreen.kt | ArrearsUnitsViewModel.kt |
| 报表中心入口 | ui/dispatcher/ReportHome.kt（2x3 六卡） | — |
| 报表页 | ui/dispatcher/ReportCenter.kt（6 Tab 内容） | ReportCenterViewModel.kt |
| 订单模板 | ui/dispatcher/FreightTemplatesScreen.kt | FreightTemplatesViewModel.kt |
| 订单详情 | ui/order/OrderDetailScreen.kt（派单员/货主/司机共用） | OrderDetailViewModel.kt |
| 货主下单 | ui/shipper/OrderCreateScreen.kt | OrderCreateViewModel.kt |
| 货主我的订单 | ui/shipper/ShipperOrdersScreen.kt | ShipperOrdersViewModel.kt |
| 货主账本 | ui/shipper/ShipperLedgerScreen.kt | ShipperLedgerViewModel.kt |
| 司机任务 | ui/driver/DriverOrdersScreen.kt | DriverOrdersViewModel.kt |
| 司机账本 | ui/driver/DriverFreightScreen.kt | DriverFreightViewModel.kt |
| 消息中心 | ui/messages/MessagesScreen.kt | MessagesViewModel.kt |
| 我的 | ui/profile/ProfileScreen.kt | ProfileViewModel.kt |

## 5. 构建与运行

```powershell
# 构建（JAVA_HOME 必须设置）
$env:JAVA_HOME='D:/APPS/AndroidStudio/jbr'
D:/AProjects/ASDH/orders/_agent/gradle/gradle-8.9/bin/gradle.bat -p D:/AProjects/ASDH/orders/android :app:assembleDebug
# APK：android/app/build/outputs/apk/debug/app-debug.apk
# 一键：dev-build.ps1 [-NoBuild|-NoRun|-CleanBuild]
```

- Gradle：项目自带 `_agent/gradle/gradle-8.9`（不依赖系统 gradle）
- SDK：D:/APPS/sdk；JDK：D:/APPS/AndroidStudio/jbr
- Manifest：ui 权限、高德 key、queries（androidamap 包可见性）在 `app/src/main/AndroidManifest.xml`

## 6. 真机连接（重要）

- 手机与电脑同网段 Wi-Fi，开启无线调试
- `adb connect <电脑IP>:<端口>`（端口可能变：44263 等）
- **电脑重启/换网后 IP 会变** → 更新 `android/local.properties` 的 api_base_url 并重装 APK
- 安装：`adb install -r app-debug.apk`；下载：`http://<电脑IP>:8001/app-debug.apk`（python http.server 8001）

## 7. 高德地图（坑多）

- 依赖：3dmap 9.8.3 / search 9.7.0 / location 6.4.9（10.x 不可升级：maven.amap.com 不通）
- **onDestroy 在 Android16 arm64 必崩** → AmapLocationManager 单例永不 destroy
- 导航：`util/AmapUri.kt` `openAmapNavigation()`：setPackage("com.autonavi.minimap") 直拉原生导航，失败回退 H5
- Android11+ 包可见性：Manifest queries 必须声明 `androidamap` scheme + `com.autonavi.minimap` package

## 8. 关键 UI 约定（实现细节参考 06）

- 弹窗：设置类用 `AlertDialog`（非 ModalBottomSheet）；添加类抽屉/底部 sheet 用于表单
- 下拉：`ExposedDropdownMenuBox` + readOnly + 回填（勿用点选 chips 代替下拉）
- 顶部状态导航：`ui/common/SegmentedStatusTabs.kt`（段间分隔线+选段淡色底）
- 金额：橙色 `0xFFFF9500`（钱橙），数量：蓝色 `0xFF1E6FFF`，商品名：`0xFF8455E6`（紫）
