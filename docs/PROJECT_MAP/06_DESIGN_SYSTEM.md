# 06 UI 设计与语义色体系

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
