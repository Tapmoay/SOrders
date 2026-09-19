# 06 UI 设计与语义色体系

<!-- ref-prefix: android/app/src/main/java/com/tapmoay/sorders/ -->

> 标准：**苹果结构 × 日本配色**（japanese-street-color-system）：Apple HIG 结构/层级 + 日本街头广告式一色一功能高饱和语义色（面向老年/低视力用户，亮色高对比）。

## 1. 核心设计原则

- **一色一功能**：每个功能/模块有唯一语义色，跨端同功能同色（下单绿/账本橙/消息红/地址湖蓝）
- **背景分层**：页面底 `BackgroundLight=#F2F3F7`，卡片白底圆角（`MaterialTheme.shapes`），信息用 SectionCard
- **低调卡片**：白底 + 浅描边（#ECEFF5）或极浅阴影；不要重边框/大圆/浓渐变
- **文字层级**：关键是重要的数字/名称用色加粗，次要说明用灰色 `onSurfaceVariant` 小字
- **按钮风格**：默认 Material3 样式（用户否决过大圆圈/胶囊大按钮）；加减等主操作色可自定义淡蓝底
- **弹窗**：选择/确认类用 `AlertDialog`；表单类用 Drawer/ModalBottomSheet 由场景决定

## 2. 语义色总表（Color.kt / ui/theme/Color.kt）

### 模块语义色（一色一功能，14 色全部互异）

| 模块 | 色值 | 常量 |
|---|---|---|
| 派单作业 / 主操作 | 蓝 #1E6FFF | NavBlue |
| 代理下单 / 已完成 | 青绿 #00B578 | MgrGreen |
| 地址与联系人 | 湖蓝 #00A2C7 | ShipperTeal |
| 订单管理 | 黄 #FFB300 | ProgressYellow |
| 司机管理 | 黄绿 #CDDC39 | - |
| 货主管理 | 深青 #00A8A8 | InventoryTeal |
| 批发商管理 | 金 #F5A623 | MemberGold |
| 商品管理 | 紫 #8455E6 | ProductPurple |
| 库存管理 | 蓝青 #00BCD4 | - |
| 账本管理 | 金橙 #FF9500 | MoneyOrange |
| 司机运费结算 | 珊瑚橙 #FF8A65 | - |
| 挂账单位 | 橙红 #FF6B2C | ArrearsTangerine |
| 报表中心 | 靛紫 #6950F5 | ReportIndigo |
| 消息中心 | 红 #FF4D4F | MessageRed |

### 报表四色（SegmentedStatusTabs 约定）

营业 #FF9500 橙｜商品 #8455E6 紫｜司机 #00B578 绿｜异常 #FF4D4F 红（+报表中心入口靛紫）

### 语义状态色

成功/正常 #00B578｜进行中/提醒 #FFB300/#FF9F1C｜危险/异常 #FF4D4F/#FF5252｜信息 #1E6FFF｜挂账警示 #FF6B2C

### 订单状态五色（ORDER_TAB_COLORS）

全部 #1E6FFF｜派单中 #FFB300｜已接单 #00A2C7｜已送达 #00B578｜已撤销 #8A8A8E

## 3. 组件风格速查（ui/common/）

| 组件 | 文件 | 说明 |
|---|---|---|
| AppTopBar | Components.kt | iOS 大标题风格，与页面同灰底；onBack 可空 |
| SectionCard | Components.kt | 白底圆角卡片（报表/列表通用容器） |
| StatBig/StatRow | ReportCenter.kt | 指标大数字卡/键值行 |
| SegmentedStatusTabs | SegmentedStatusTabs.kt | 顶部状态导航（语义色+无图标+段间竖分隔线+选段淡色底） |
| ReportTimeNav | ReportTimeNav.kt | 报表时间导航（完整时段标题点击换日期+按日/周/月胶囊） |
| LineChart/BarChart/ChartEmpty | Charts.kt | 简易图表 |
| OrderCard | OrderCard.kt | 订单卡（状态徽标/地址/货主/商品行/操作） |
| TintedIcon | Components.kt | 圆底 tint 图标（36dp 常用） |

## 4. 具体业务用色约定（报表/订单页）

- 金额（钱）：橙 #FF9500；小计/合计 同理
- 数量：蓝 #1E6FFF（如 "· 数量 5"）
- 商品名：紫 #8455E6（SemiBold）
- 货损/异常：红 #FF4D4F/#E53935
- 毛利/成功：绿 #00B578
- 加减按钮淡蓝：底 #E8F2FF / 图标 #1E6FFF（**用户明确要求保留，勿改回青绿**）
- 工资制司机：灰 #8A8A8E 标注「工资制」；计件司机待结运费：橙红 #FF6B2C

### 4.1 商品卡上那四个数字（2026-09-19 用户要求"用对应的语义色和图标"）

用户原话：「那些信息是在商品管理中非常重要的，不一定非要等编辑才能看得到，
我们要用对应的语义色和图标在它的名字的下面进行显示，让人一眼就能看出来」。
实现是 `ui/dispatcher/ProductsScreen.kt::ProductFacts`，**配色只有那一处**：

| 信息 | 颜色 | 图标 | 为什么是这个色 |
|---|---|---|---|
| 售价 | 金橙 `MoneyOrange` | `Sell` | 系统里"钱"的语义色（与账本/报表/小计同色） |
| 成本 | 中性灰 `#8A8A8E` | `Payments` | 它**也是钱**，但颜色在这里的作用是区分"对外的价"和"对内的成本"：两个都染橙的话，用户得读完字才知道哪个是卖价。成本不参与报价，中性灰最不容易看错 |
| 库存 | 蓝青 `#00BCD4` | `Inventory2` | **库存管理模块的语义色**（跨端同功能同色：这个数字属于库存管理） |
| 分类 | 紫 `ProductPurple` | `Category` | 商品管理的模块色；**未分类**改提醒黄 #FFB300 —— 它是个待办（会让选品页多出一格） |

⚠️ **库存还会按状态变色**：`stock <= 0` → 红 #E53935（断货）、`<= lowStockAlert` → 黄 #FFB300。
这两个颜色不是装饰，是"这一行要你处理"的信号 —— 派单员扫列表时靠它决定先看哪几个。

### 4.2 卡片上的动作：三个以上就收进「⋮」

用户 2026-09-19：「右边 3 个按钮太占位置了，把在保证按钮性的同时，又让他不占位子」。
商品卡与分类行都改成 **右上角一个 `MoreVert` + `DropdownMenu`**（动作一个不少，
可发现性靠标准「⋮」），腾出来的整条右边还给信息。
**判断依据**：横排的 `IconButton` 每个约 48dp，三个就是 144dp —— 那正好是商品名+数字被挤成
两行灰字的宽度。反过来说，**只有一个主操作时仍用显式按钮**（不要为了统一把所有东西塞进菜单）。

## 5. 用户明确偏好（改 UI 前必看）

- ✅ 下拉一律 `ExposedDropdownMenuBox` readOnly 点选回填（不要点选 chips 替代下拉）
- ✅ 选择/确认弹窗用 `AlertDialog`（如选图：拍照/相册）
- ✅ 添加类表单用抽屉（如商品添加 Drawer）
- ✅ chips 用 `FlowRow` 防竖排换行（如批价档/定价方式）
- ✅ 低调卡片（白底浅描边），容器色"只比白稍深"（#F6F6F8 档）
- ✅ 弹窗按钮简洁 = Material3 默认 TextButton；用户否决 大圆圈/胶囊 样式
- ✅ 语义色一色一功能
- ✅ 参考图只抄布局形式（两列图标+黑字），内容按业务自定
- ✅ 报表毛利必须带覆盖率说明；待结运费仅计件司机展示

## 6. 主题

`ui/theme/`：Color.kt（上表）＋ Theme.kt（Light/Dark，亮色为主）＋ Type.kt
- 品牌种子蓝 SeedBlue=#1E6FFF（明快物流蓝，参考日式街头招牌：饱和/明亮/高对比）
- 图片/图标白线样式统一用 `Material Icons (filled)` —— 依赖 `material-icons-extended`

### 6.1 外观模式（白天 / 夜间 / 随日落自动）

「我的」页两行（三端共用同一个页面，所以三端都有）：

| 行 | 行为 |
| --- | --- |
| **随日落自动切换**（默认**关**） | 打开后按当天日出日落自动切：天黑（太阳高度角 −6°，民用暮光）切夜间、天亮切回白天。右侧写清"下一次什么时候切" |
| **夜间模式 / 白天模式** | 手动开关。**自动打开时这一行置灰**并写明「已交给自动切换」——否则会出现"点了一下又自己弹回来" |

- 判定在 `core/SunClock.kt`（纯函数）：界线 = 民用暮光（太阳高度角 −6°）；**有手机定位就用真实经纬度**（`core/SunLocation.kt`，拿不到就退回"时区中央经线 + 35°N"估算）；定时器 `ui/theme/AutoSunTheme.kt` 挂根节点；状态在 `ui/theme/Theme.kt` 的 `ThemeMode`（明暗与自动开关都落盘）。
- 那一行右侧会**如实写明依据**：「按定位」还是「时区估算，开定位更准」——两个精度差很多（新疆约 2 小时），含糊过去等于骗人。
- ⚠️ 定位失败时高德会回调 `(0,0)`（不是 null）：不校验就会算出错 8 小时的日落**且不报错**，所以坐标必须过 `SunLocation.isPlausible`。
- 自动开关是**设备级**的（跟账号无关，换账号不变），和系统"深色模式"的直觉一致。
- ⛔ 暗色下必须还能分层：`SurfaceDark` 必须亮于 `BackgroundDark`，卡片补淡描边（阴影在暗色下看不见）。
- 详见 `AI_ASSISTANT_PLAN_V3.md` §51 与红线 §21。

