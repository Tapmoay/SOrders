# 报表中心 · 现有 Android UI 面清单（只读盘点）

> 盘点范围：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/`（ReportHome / ReportCenter / ReportPriority / ReportFinance / ReportCenterViewModel）+ 复用组件 `ui/common/`、主题 `ui/theme/`。
> ⛔ 本文件是只读盘点的产物，不代表建议改动；所有行号以本次读取的源码为准。
> 读法约定：**Hint** = `ui/common/Hints.kt` 的全局开关组件（**总开关关掉就整句不显示**）；**常显 Text** = 普通 `Text`，永远显示。二者不是"折叠/展开"，而是"受不受提示总开关管"。

---

## 一、入口页 ReportHome.kt —— 11 张卡

文件：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportHome.kt`（共 62 行）。
版式**不在本文件**：`EntryCardGrid`（`android/app/src/main/java/com/tapmoay/sorders/ui/common/EntryGrid.kt:54-98`），与「账本管理」入口页**共用一份**（`ReportHome.kt:26-30` 的类注释写明"这里只负责有哪 11 件事"）。
点击去向：`onOpen(it.key.toInt())`（`ReportHome.kt:58`）→ key 直接当 `ReportCenterScreen(initialTab=…)` 的页签号。

| # | 顺序 | key | 标题 | 图标（Material filled） | 语义色 | 定义行 |
|---|---|---|---|---|---|---|
| 1 | 第 1 格 | `"0"` | 营业纵览 | `Icons.Default.Payments` | `#FF9500` 橙 | `ReportHome.kt:35` |
| 2 | 第 2 格 | `"1"` | 商品经营 | `Icons.Default.Inventory2` | `#8455E6` 紫 | `ReportHome.kt:36` |
| 3 | 第 3 格 | `"2"` | 司机绩效 | `Icons.Default.LocalShipping` | `#00B578` 绿 | `ReportHome.kt:37` |
| 4 | 第 4 格 | `"3"` | 客户经营 | `Icons.Default.Storefront` | `#00A2C7` 湖蓝 | `ReportHome.kt:38` |
| 5 | 第 5 格 | `"4"` | 资金收支 | `Icons.Default.SwapHoriz` | `#6950F5` 靛紫 | `ReportHome.kt:39` |
| 6 | 第 6 格 | `"5"` | 异常与审计 | `Icons.Default.ReportProblem` | `#FF4D4F` 红 | `ReportHome.kt:40` |
| 7 | 第 7 格 | `"6"` | 经营利润 | `Icons.Default.CurrencyYuan` | `#00B3A4` 青 | `ReportHome.kt:42` |
| 8 | 第 8 格 | `"7"` | 车辆成本 | `Icons.Default.DirectionsCar` | `#546E7A` 蓝灰 | `ReportHome.kt:43` |
| 9 | 第 9 格 | `"8"` | 成本覆盖 | `Icons.Default.BarChart` | `#4CAF50` 绿 | `ReportHome.kt:45` |
| 10 | 第 10 格 | `"9"` | 税账 | `Icons.Default.Receipt` | `#C08A4E` 棕金 | `ReportHome.kt:48` |
| 11 | 第 11 格 | `"10"` | 客户欠款 | `Icons.Default.AccountBalanceWallet` | `#B71C1C` 深红 | `ReportHome.kt:51` |

源码注释里钉着的两条规矩（原文）：

- `ReportHome.kt:41`：「第 7 格只许追加在末尾：key 直接当页签号用（见 ReportFinance.exportKind 的说明）」
- `ReportHome.kt:47`：「新格只许追加在末尾（key 直接当页签号，见 ReportFinance.exportKind 的说明）」
- `ReportHome.kt:50`：「深红 #B71C1C 与「5 异常与审计」的 #FF4D4F 色距约 101（>60），同屏分得开。」

版式（`EntryGrid.kt`）：白卡 `MaterialTheme.shapes.medium` + 1dp 描边 `#ECEFF5`；左侧 40dp 圆角方（`RoundedCornerShape(10.dp)`）语义色底 + 22dp 白色线图标；右侧 `bodyLarge.copy(fontSize = 16.sp)` + `FontWeight.Medium`；网格列数 `maxOf(2, screenWidthDp / 160)`（手机恒 2 列，平板加列），间距 12dp，外层 padding 16dp/12dp（`EntryGrid.kt:63-98`）。

---

## 二、ReportCenter.kt —— 11 个页签的区块顺序（逐页逐块）

文件：`android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt`（共 2021 行）。

### 0. 共用外壳（`ReportCenterScreen`，`ReportCenter.kt:39-159`）

| 位置 | 内容 | 行号 |
|---|---|---|
| 顶栏标题 | `when(vm.tab)`：0 营业纵览 / 1 商品经营 / 2 司机绩效 / 3 客户经营 / 4 资金收支 / 5 异常与审计 / 6 经营利润 / 7 车辆成本 / 8 成本覆盖 / 9 税账 / 10 客户欠款 | `ReportCenter.kt:47` |
| 顶栏右侧① 时间药丸 | `DatePresetPill(label = vm.periodLabel)`，**只在 `vm.tab != 5 && vm.windowSettled` 时画** | `ReportCenter.kt:64-66` |
| 顶栏右侧② 刷新 | `TextButton` + `Icons.Default.Refresh`(18dp) + 文本「刷新」 | `ReportCenter.kt:67-71` |
| 顶栏右侧③ 导出 | `TextButton` + `Icons.Default.FileDownload`(18dp) + 「导出」/导出中；文件名 `title + "-" + f + "_" + t + ".xlsx"` | `ReportCenter.kt:72-88` |
| tab 5 页内说明 | 常显 `Text`：「这个页面固定看近 30 天：上面是待处理异常，下面是最近的操作日志」 | `ReportCenter.kt:98-103` |
| 窗口未定 | `LoadingBox`（整页 loading，连药丸都不画） | `ReportCenter.kt:105-106` |
| tab→组件 | 0 TurnoverTab / 1 ProductTab / 2 DriverTab / 3 CustomerTab / 4 FinanceTab / 6 ProfitTab / 7 VehicleCostTab / 8 CostCoverageTab / 9 TaxTab / 10 CustomerBalanceTab / else FinanceTab | `ReportCenter.kt:108-120` |
| 时间弹层 | `DateFilterDialogs`（档位清单 + 自定义区间，与账本/订单/司机账本同一份实现） | `ReportCenter.kt:128-136` |
| 解决异常弹窗 | `AlertDialog`「解决异常」+ 单号·原因 + `OutlinedTextField`「解决说明（如：已电话联系司机重新派单）」+ 按钮「标记解决」/「取消」 | `ReportCenter.kt:138-158` |

⚠️ 文案与实现已不一致（留给后文问题清单）：`ReportCenter.kt:99` 那句固定说明写的是"上面是待处理异常，下面是最近的操作日志"，而实际已是**三屏分段**（要处理 / 审计 / 已过去，`ReportCenter.kt:798-808`）。

局部可复用件（都定义在本文件内，**private**）：

| 组件 | 形态 | 行号 |
|---|---|---|
| `GroupHeader(title)` | `Surface` 底色 `#F3F0FF` + 4dp×14dp 靛紫竖条 `#6950F5` + `labelLarge` 加粗 `#495057` | `ReportCenter.kt:161-173` |
| `AccentBar(color)` | 4dp×16dp 竖色条（卡片左侧分类色） | `ReportCenter.kt:175-178` |
| `StatBig(label, value, color)` | `SectionCard` 内：`bodySmall` 灰标签 + `headlineSmall` 加粗彩色大数字 | `ReportCenter.kt:180-187` |
| `StatRow(label, value, color)` | 一行：左 `bodyMedium` 灰标签（weight 1）+ 右 `titleSmall` 加粗彩色值 | `ReportCenter.kt:189-195` |
| `money(s)` | `"¥" + formatMoney(s ?: "0")` | `ReportCenter.kt:197` |
| `CoverNote(cov,total,avgLines,snapLines)` | 常显 `bodySmall` 毛利口径 + 覆盖率 | `ReportCenter.kt:272-279`，文案函数 `coverageText` `ReportCenter.kt:261-270` |
| `LevelHeader(lv,count)` | 8dp 圆点 + `titleSmall` 加粗「层级（N）」+ `bodySmall` 为什么先看 | `ReportCenter.kt:932-955` |
| `AuditChip(label,count,selected)` | 胶囊筛选块（选中 `#6950F5` 底白字，未选 surfaceVariant） | `ReportCenter.kt:917-929` |
| `KindBadge(text,color)` | 胶囊徽标（`color.copy(alpha=0.12f)` 底 + `labelSmall` 同色字） | `ReportCenter.kt:1012-1022` |
| `AuditLogCard(log)` | 审计卡：AccentBar(级别色) + 动作中文名 + KindBadge + `changeContent` 人话（maxLines 3）+ 「谁 · 什么时候」+ 右侧单号 `#6950F5` | `ReportCenter.kt:957-990` |
| `ExceptionCard(e,onResolve)` | 异常卡：#单号 + [条件]「已拖 N 天」徽标 + 原因（红 `#E53935`）+ 货主/司机 + 「状态：中文」+ [已解决]「解决：…」+ 右侧「解决」按钮 | `ReportCenter.kt:1215-1255` |
| `levelColor(lv)` | MONEY `#E53935` / STUCK `#FF8A65` / OTHER·PAST `#8A8A8E` / DONE `#00B578` | `ReportCenter.kt:1024-1030` |
| `actionLabel(action)` | 审计动作码 → 中文（约 120 个分支，`else -> action` 兜底） | `ReportCenter.kt:1040-1213` |

**页签① 营业纵览 `TurnoverTab`（`ReportCenter.kt:283-401`）** —— 数据源 `turnoverReport` + `ledgerAccounts(shipper/member)` + `exceptionOrders(今天-30天)`（`ReportCenterViewModel.kt:237-250`）

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 1 | KPI 大数字 `StatBig` | 「实际营业金额」`money(totalAmount)` 蓝 `#1E6FFF` | `ReportCenter.kt:292-294` |
| 2 | `SectionCard`「营业指标」 | 订单数 `N 单` / 单均价 / 司机运费支出（`#FF9500`）/ [条件>0] 已撤销订单数（`#8A8A8E`） | `ReportCenter.kt:295-304` |
| 3 | `SectionCard`「待处理异常」（**单列一张卡**） | `StatRow("近 30 天（与本页时间无关）", N 单, #E53935)`；注释理由：窗口与本页不同，混在一张卡里会被读成"今天有 N 单异常" | `ReportCenter.kt:309-315`（理由注释 `:305-308`） |
| 4 | `SectionCard`「盈利概览」 | 商品毛利（`#00B578`）+ **常显** `CoverNote` + 货损金额（`#E53935`）+ [条件] 货损件数 | `ReportCenter.kt:316-326` |
| 5 | `SectionCard`「资金状态」 | 已收（`#00B578`）/ 挂账未收（`#FF6B2C`）/ 收款率（`#1E6FFF`） | `ReportCenter.kt:327-337` |
| 6 | `SectionCard`「客户账汇总」 | 小标题「货主账」`#00A2C7`（take(3)）/「批发商账」`#F5A623`（take(3)）/「挂账未收 TOP5」`#FF6B2C`；空态文字「暂无流水」 | `ReportCenter.kt:338-361` |
| 7 | `SectionCard`「统计图」 | 右上切换按钮「条形图」/「折线图」→ `LineChart`(`#1E6FFF`) / `BarChart`(`#00B578`)；空态 `ChartEmpty("该时段暂无送达数据")` | `ReportCenter.kt:362-379` |
| 8 | `GroupHeader`「每日明细」 | 分组标题条 | `ReportCenter.kt:380-383` |
| 9 | `SectionCard` 每日明细列表 | 每行：靛紫 AccentBar + 日期 + `N 单`（宽 48dp）+ 金额（`titleSmall` 加粗 `#1E6FFF`，宽 84dp）+ HorizontalDivider | `ReportCenter.kt:384-398` |

无 Hint、无口径说明块（覆盖率是常显 `CoverNote`）。

**页签② 商品经营 `ProductTab`（`ReportCenter.kt:405-512`）**

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 1 | 两张并排 `StatBig` | 「商品总金额」`#8455E6` / 「出库总件数」`N 件` `#00A8A8` | `ReportCenter.kt:414-419` |
| 2 | `SectionCard`「盈利与损耗」 | 商品毛利 `#00B578` + **常显** `CoverNote` + 货损金额 `#E53935` | `ReportCenter.kt:420-429` |
| 3 | `SectionCard`「销量 TOP（条形图）」 | `BarChart`(top8, `#8455E6`)；空态「暂无数据」 | `ReportCenter.kt:430-438` |
| 4 | `GroupHeader`「商品明细（N 种）」 | | `ReportCenter.kt:439-442` |
| 5 | `SectionCard` 搜索 + 排序 | `OutlinedTextField` 占位「搜索商品名称」；四个 chip「按金额/按件数/按毛利/按货损」 | `ReportCenter.kt:443-473` |
| 6 | 商品卡 `items`（默认 TOP15） | 紫 AccentBar + 商品名 + 「N 件 · N 单 · 货损 N 件」+ 毛利行：有成本 `毛利 ¥…`（`#00B578`）/ 无成本 `毛利 —（这一行没有成本快照，不进毛利）`（灰）；右侧金额 `titleMedium` 加粗 `#FF9500` | `ReportCenter.kt:474-499` |
| 7 | [条件 过滤后 >15 且未展开] `SectionCard` | 按钮「查看全部 N 个商品（当前显示 TOP15）」 | `ReportCenter.kt:500-508` |
| 8 | 空态 | `ChartEmpty("无匹配商品")` | `ReportCenter.kt:509` |

**页签③ 司机绩效 `DriverTab`（`ReportCenter.kt:516-576`）**

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 1 | `SectionCard`「绩效总览」 | 完成单量 `N 单` / 平均准时率 `N %`(`#00B578`) / 平均拍照率 `N %`(`#00A2C7`) / 计件司机待结运费 `¥…`(`#FF6B2C`) + **常显** `Text`：「待结运费 = 计件（PIECE）司机应结运费 − 已结算金额；工资制司机不计。」 | `ReportCenter.kt:534-542` |
| 2 | `SectionCard`「完成单量 TOP（条形图）」 | `BarChart`(top8, `#00B578`) | `ReportCenter.kt:544-550` |
| 3 | `GroupHeader`「司机绩效（N 人）」 | | `ReportCenter.kt:551-554` |
| 4 | 司机卡 `items` | 绿 AccentBar + 名字（空则「司机 N」）+「准时率 N% · 拍照率 N% · 平均 N 分钟」+ 计费模式行：`SALARY`→「工资制」(`#8A8A8E`) / `PIECE`→「待结运费 ¥…」(`#FF6B2C`)；右侧「N 单」`titleMedium` 加粗 `#00B578` | `ReportCenter.kt:555-573` |
| — | 空态 | `ChartEmpty("该时段暂无司机绩效数据")` | `ReportCenter.kt:524-525` |

**页签④ 客户经营 `CustomerTab`（`ReportCenter.kt:580-688`）**

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 1 | 两张并排 `StatBig` | 「订货总额」`#00A2C7` / 「客户数」`N 家` `#00B578` | `ReportCenter.kt:599-604` |
| 2 | `SectionCard`「经营概览」 | 订货笔数 `N 笔` / **户均订货额** `#1E6FFF` / **每笔订货额** `#1E6FFF` / 临时货主 `N 家`(`#8A8A8E`) | `ReportCenter.kt:605-617`（改名理由注释 `:610-612`） |
| 3 | `SectionCard`「客户账分组」 | 「货主账」take(5) `#00A2C7` / 「批发商账」take(5) `#F5A623`；空态「暂无流水」 | `ReportCenter.kt:618-634` |
| 4 | [条件 非空] `SectionCard`「挂账未收」 | 标题即橙色 `#FF6B2C`，take(8) | `ReportCenter.kt:635-645` |
| 5 | `GroupHeader`「客户明细」 | | `ReportCenter.kt:646-649` |
| 6 | 小标题「货主 · 临时货主」+ `items` | 湖蓝 AccentBar + 名字 + [临时货主] 灰标记 + 右侧「N 笔 · ¥…」`titleSmall` 加粗 `#00A2C7` | `ReportCenter.kt:650-668` |
| 7 | 小标题「批发商」+ `items` | 金 AccentBar + 名字 + 右侧「N 笔 · ¥…」`#F5A623` | `ReportCenter.kt:669-686` |

⚠️ 去重规则（源码注释 `ReportCenter.kt:588-597`）：批发商同时出现在 `kind=shipper` 与 `kind=member` 两个列表，页面按用户 id 去重，"批发商优先算在 members 桶里"，否则订货总额虚高 44.6%（实测 ¥185,121 vs 真值 ¥128,063）。

**页签⑤ 资金收支 `FinanceTab`（`ReportCenter.kt:692-769`）**

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 1 | 两张并排 `StatBig` | 「资金流入」`#00B578` / 「资金流出」`#FF6B2C` | `ReportCenter.kt:710-715` |
| 2 | `SectionCard`「净额」 | `StatRow("净流入", …)`，正绿负红 | `ReportCenter.kt:716-722` |
| 3 | [条件 有开销] `SectionCard`「开销分类汇总」 | 按金额倒序的 `StatRow(分类, money)` `#FF9500` | `ReportCenter.kt:723-733` |
| 4 | `GroupHeader` 资金流水 | 标题「资金流水（本窗口共 N 条[，下面只列最近 100 条]）」+ [条件截断] `TruncationNote(limit, "这一窗口更早的请用上方时间导航切到更早的日期")` | `ReportCenter.kt:734-747` |
| 5 | 空态 | `ChartEmpty("该时段暂无资金流水")` | `ReportCenter.kt:748` |
| 6 | 流水行 `items(take(100))` | 绿/橙 AccentBar + 对方名（空则「收入」/「支出」）+「日期 · 业务类型」中文 + 右侧 `+/-` 金额 `titleMedium` 加粗同色 | `ReportCenter.kt:749-767` |

**页签⑥ 异常与审计 `ExceptionTab`（`ReportCenter.kt:776-915`）** —— 唯一的"分屏"页

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 0 | 页内说明（在外壳里） | 常显 `Text`（近 30 天说明） | `ReportCenter.kt:98-103` |
| 1 | `SegmentedStatusTabs` 三屏 | 「要处理 N」`#E53935` /「审计 N」`#6950F5` /「已过去 N」`#8A8A8E`；`pane` 0/1/2，段控件在 LazyColumn **外面**（放里面负 padding 会崩） | `ReportCenter.kt:798-808`（理由注释 `:795-801`） |
| 2 | pane 0 要处理：并排 `StatBig` | 「要处理」`N 单` `#E53935` /「其中钱货风险」`N 单` `#FF8A65` | `ReportCenter.kt:811-816` |
| 3 | pane 0：`SectionCard`「异常总账（近 30 天）」 | 「总共 N 单 → 要处理 N + 已过去 N + 已解决 N」/ 解决率 `N %`(`#00B578`) / [条件 ≥3 天]「最久已拖 N 天」(`#FF8A65`) | `ReportCenter.kt:817-828` |
| 4 | pane 0：`LevelHeader` 分组 + `ExceptionCard` | 风险层级分组（钱货风险 → 履约卡住 → 一般），组内按拖得久 | `ReportCenter.kt:829-845` |
| 5 | pane 1 审计：`GroupHeader`「敏感操作审计（近 60 条）」+ 5 个 `AuditChip` | 「全部/改钱/删数据/账号权限/改状态」+ **Hint**「排序：改钱/删数据/账号权限 → 改状态 → 其它，同级按时间倒序」+ [条件] `TruncationNote(limit, "更早的没被列出来（不代表没记录），需要更多请点右上角「导出」")` | `ReportCenter.kt:847-875` |
| 6 | pane 1：`AuditLogCard` 列表 + 空态 | 「暂无操作日志」/「这一类里没有操作记录」 | `ReportCenter.kt:876-881` |
| 7 | pane 2 已过去：`GroupHeader`+常显说明 | 「已过去（不用处理，只是留档）· N 单」+「含已送达但迟到过的单…不需要谁去点「解决」。」 | `ReportCenter.kt:885-896` |
| 8 | pane 2：`ExceptionCard(onResolve = null)` | 无「解决」按钮 | `ReportCenter.kt:897-899` |
| 9 | pane 2：[条件] 「已解决（N）」分组 | | `ReportCenter.kt:900-908` |
| 10 | pane 2 空态 | 「没有已经过去的异常」 | `ReportCenter.kt:909-911` |

**页签⑦ 经营利润 `ProfitTab`（`ReportCenter.kt:1271-1430`）**

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 1 | `StatBig` | 「营业利润」`money(operatingProfit)`，正 `#00B578` / 负 `#E53935` | `ReportCenter.kt:1282-1284` |
| 2 | `SectionCard`「利润构成」 | 营业收入(应收)`#1E6FFF` → − 算不出成本的收入`#8A8A8E` → = 参与毛利的收入`#1E6FFF` → − 商品成本 → = 商品毛利`#00B578` → − 配送成本(司机应得)`#FF9500` → − 期间费用`#FF6B2C` → − 车辆折旧`#8A8A8E` → − 税金及附加`#8A8A8E` → Divider → = 营业利润 | `ReportCenter.kt:1285-1306` |
| 3 | `SectionCard`「增值税（价外税，不进上面的营业利润）」 | 销项税额`#1E6FFF` / 进项税额`#00B578` / Divider / = 该交的增值税（负绿正橙）+ **Hint**「增值税是价外税…负数 = 进项比销项多…票在「税账」那一页。」 | `ReportCenter.kt:1309-1330` |
| 4 | [条件 算不出成本的收入≠0] `SectionCard`「算不出成本的收入」 | `StatRow("这段营业额里", …)` + 常显 `Text`「这笔钱在营业额里，但那些行没有成本数据…把进货价补录进去之后，它才会进毛利。」 | `ReportCenter.kt:1331-1346` |
| 5 | [条件 折旧未覆盖>0] `SectionCard`「折旧未覆盖的车」 | 逐台 `StatRow(车牌, 原因)` + **Hint**「在「车辆管理」里把这些车的购置价、购置日期、使用年限补上…」 | `ReportCenter.kt:1347-1371` |
| 6 | `SectionCard`「口径说明（这几件事今天算不进这张表）」 | `CoverNote` + `data.notes` 逐条**常显** `Text` | `ReportCenter.kt:1372-1382` |
| 7 | [条件] `SectionCard`「期间费用明细」 | 分类 `#FF6B2C` + Divider + 合计 | `ReportCenter.kt:1383-1395` |
| 8 | [条件] `SectionCard`「税金及附加明细」 | 分类 `#8A8A8E` + Divider + 合计 | `ReportCenter.kt:1396-1408` |
| 9 | `SectionCard`「资金状态」 | 已收`#00B578` / 挂账未收`#FF6B2C` / [条件] 已撤销订单数 / [条件] 货损件数·「货损金额（已含在期间费用里）」+ 常显 `Text`「「已收 / 挂账未收」说的是这一段收回多少钱，与上面的利润不是一回事：赚了不等于收到了。」 | `ReportCenter.kt:1409-1427` |

**页签⑧ 车辆成本 `VehicleCostTab`（`ReportCenter.kt:1443-1542`）**

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 1 | `StatBig` | 「车辆成本合计」`#E53935` | `ReportCenter.kt:1454-1456` |
| 2 | `SectionCard`「这一段的三笔成本」 | 车辆折旧`#8A8A8E` / 车辆开销（燃油/维修/保险…）`#FF6B2C` / 挂靠司机配送成本`#FF9500` / Divider / = 成本合计 + 常显覆盖率句「覆盖 N / N 台车算得出折旧；每月折旧合计 ¥…（月额，与这一段窗口无关）。」 | `ReportCenter.kt:1457-1474` |
| 3 | [条件 未覆盖>0] `SectionCard`「折旧未覆盖的车」 | 逐台 **车牌与原因各占一行**（`bodyLarge` + `bodySmall`）+ **Hint**「这几台车没录全购置信息…在「车辆管理」里补上缺的那一格…」 | `ReportCenter.kt:1475-1502`（真机裁切教训注释 `:1481-1483`） |
| 4 | 逐车卡 `items` | 标题「车牌（在用/停用）」+ 挂靠司机（空则「未绑定」）+ [覆盖] 每月折旧 + 车辆折旧（这一段）+ 这台车的开销 + 配送成本 + Divider + = 成本合计 + 明细 `· 分类` + [未覆盖]「折旧算不出来：…。」 | `ReportCenter.kt:1503-1529` |
| 5 | `SectionCard`「口径说明（这几笔钱是怎么算的）」 | `notes` 逐条常显 | `ReportCenter.kt:1530-1539` |
| — | 空态 | `ChartEmpty("该时段暂无车辆成本数据")` | `ReportCenter.kt:1451-1452` |

⛔ 本页**没有收入/毛利/利润率**（`ReportCenter.kt:1438-1439`：订单不带车，按车摊收入就是编一个比例）。

**页签⑨ 成本覆盖 `CostCoverageTab`（`ReportCenter.kt:1557-1640`）**

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 1 | `StatBig` | 「这一段卖出去的货」`money(revenueTotal)` `#1E6FFF` | `ReportCenter.kt:1568-1570` |
| 2 | `SectionCard`「收入里有多少带着成本出处」 | 收入合计 / 有成本出处的收入`#00B578` / 没有成本出处的收入`#E53935` / Divider + 常显行数句「按明细行数：N / N 行算得出成本；其中 N 行用这一段自己的平均进货价、N 行用商品当前的成本价快照…」 + **Hint**「「没有成本出处」不是成本 0，是不知道成本…给这个商品带价进一次货（「采购单」）…」 | `ReportCenter.kt:1571-1594` |
| 3 | [条件 有从来没带价进货的商品] `SectionCard`「从来没带价进过货的商品（N 个）」 | 逐行"名字（单位）"与"成本价：没有进过货 · 库存 N"**各占一行** + **Hint**「这些商品卖出去的收入，成本这边只能记成「不知道」…」 | `ReportCenter.kt:1595-1627` |
| 4 | `SectionCard`「口径说明（这几笔钱是怎么算的）」 | `notes` 常显 | `ReportCenter.kt:1628-1637` |

**页签⑩ 税账 `TaxTab`（`ReportCenter.kt:1655-1805`）**

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 1 | `StatBig` | 「该交的增值税」`money(vatPayable)`，负 `#00B578` / 正 `#FF6B2C` | `ReportCenter.kt:1668-1670` |
| 2 | `SectionCard`「销项与进项」 | 小标题 bodyLarge「销项（这一段开出去的票）」+ 张数/价税合计/不含税/税额`#1E6FFF` + [条件]「其中未税票」`#8A8A8E` → Divider → 进项同构（税额`#00B578`）→ Divider → = 该交的增值税 + **Hint**「销项税额减进项税额。负数 = 进项比销项多…「未税票」是建票时没填税率的票…」 | `ReportCenter.kt:1672-1711` |
| 3 | [条件 有作废/未税票] `SectionCard`「不算进税汇的票」 | 已作废`#E53935` / 销项未税票 / 进项未税票（灰）+ **Hint**「作废的票留在台账里、只是退出这一段税汇…」 | `ReportCenter.kt:1712-1744` |
| 4 | [条件] `SectionCard`「按税率分档」 | `StatRow(方向 + N%, "N 张 · ¥…")` | `ReportCenter.kt:1745-1758` |
| 5 | `SectionCard`「明细（这一段一共 N 张票）」 | 空态文字「这一段没有票。去「发票台账」建一张，或者把窗口换成有票的那一段。」；逐票两行：日期·票号（`bodyLarge`）+ 方向·状态·对方·价税合计·[未税/税额]·[不算进税汇]（`bodySmall`） | `ReportCenter.kt:1759-1792` |
| 6 | `SectionCard`「口径说明（这几种票不算数）」 | `notes` 常显 | `ReportCenter.kt:1793-1802` |

**页签⑪ 客户欠款 `CustomerBalanceTab`（`ReportCenter.kt:1819-2021`）**

| 序 | 块 | 关键文案锚点 | 行号 |
|---|---|---|---|
| 1 | `SectionCard`「该收的钱」（**不用 StatBig**，自己排：`bodySmall` 标签 + `headlineSmall` 加粗 `#FF6B2C` 大数字） | 金额 + 「截止 {asOf}」+「有欠款的 N 人 · N 张单」+ [条件]「没挂到名册单位上的 N 人 · ¥…」 | `ReportCenter.kt:1834-1854` |
| 2 | `SectionCard`「账龄」 | 四桶（顺序取 `data.bucketKeys`）→ [条件]「减：预收（客户先打的钱）」→ Divider →「= 该收的钱」`#FF6B2C` + **常显** `Text`「这里一个加减法都不做：四桶、合计、额度全是接口给的数。」 | `ReportCenter.kt:1855-1880`（⛔ 不许用 Hint 的理由注释 `:1870-1873`） |
| 3 | [条件 有超额行] `SectionCard`「有额度的行超限」 | 标题红 `#E53935` + 常显「有 N 行的欠款已经超过它自己的信用额度（下面标红的那几行）。」 | `ReportCenter.kt:1881-1894` |
| 4 | `SectionCard`「欠款人（按欠款从多到少，N 行）」 | 空态「这一段没有人欠钱。把窗口换成有已送达单的那一段再看看。」；逐行**可点展开**（key = `kind + "|" + (unitId ?: name)`）：名字 + 金额（超限红）/ 类型·电话·名下客户 / 「最老 N 天 · N 张单 · [预收 ¥…]」/ [kind==unit] 信用额度（null→「不限额」）·已经用了·[条件]还能赊·[条件]「超了 ¥…」；展开后逐单三行（单号·送达日 / 应收·已收·欠款 / 账龄 N 天（桶：…）· 从 X 起算）；未展开提示「点这一行看逐单明细（这一行一共 N 张单）」`#6950F5` | `ReportCenter.kt:1895-2007` |
| 5 | `SectionCard`「口径说明」 | `notes` **原文照印** | `ReportCenter.kt:2008-2018` |

## 三、已有的视觉表达手法与可复用组件清单

> 本节路径前缀 **`⟨src⟩` = `android/app/src/main/java/com/tapmoay/sorders/`**（例：`⟨src⟩ui/common/Components.kt:288`）。
> 术语：**常显 Text** = 普通 `Text`；**Hint** = 走全局开关的说明句（见 3.6）。带 ⛔ 的是源码注释里写死的禁用项。

### 3.1 卡片与分组容器

| 组件 / 常量 | 文件:行号 | 怎么用（要点） |
|---|---|---|
| `SectionCard` | `⟨src⟩ui/common/Components.kt:288-303` | **全 App 分组容器的唯一实现**：`shapes.medium`(16dp) 白卡 + `tonalElevation=0` + `shadowElevation=1dp` + 内 `padding(16dp)`；亮色靠「白卡 vs 灰底(#F2F3F7)」分层，**暗色必须补 1dp `outlineVariant.copy(alpha=0.55f)` 描边**（暗色阴影看不见）。报表 11 页每个分块都用它。 |
| 组标题写在**卡外** | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1362-1388`（§5.0 第②条） | ⛔ 不许用描边框/一堆 `Outlined*` 拼分组；组标题＝卡外一行小字（可带语义色小图标）；卡里只放共用行。 |
| `GroupHeader`（报表页内 private） | `⟨src⟩ui/dispatcher/ReportCenter.kt:161-173` | 报表页「小节标题」样式：`#F3F0FF` 底 + `#6950F5` 竖条 + `labelLarge` 加粗 `#495057`。⚠️ 是 private，只能在 ReportCenter.kt 用。 |
| `AccentBar`（private） | `⟨src⟩ui/dispatcher/ReportCenter.kt:175-178` | 4×16dp 语义色竖条，贴在卡标题左侧做「这一块是什么色」的记号。 |
| `EntryCardGrid` / `EntryCard(key,label,icon,color)` | `⟨src⟩ui/common/EntryGrid.kt:38-43 / :54-98` | 入口页标准版式：白卡 12dp 圆角 + 1dp 描边 `#ECEFF5`；图标＝40dp 圆角方(10dp) 语义色底 + 22dp 白线 icon；文字 `bodyLarge.copy(fontSize=16.sp)` + Medium；列数 `maxOf(2, 屏宽dp/160)`(`:63`)。**报表中心 11 格与账本管理入口页共用同一份**（`:45-52` 注释：本组件不认识路由，只认 key）。 |
| `WelcomeBar`（工作台 private） | `⟨src⟩ui/home/WorkbenchScreen.kt:158-177` | 一行约 50dp 的头部：`primaryContainer` 底 + `shapes.large`；左标题 `titleMedium` `maxLines=2` + `weight(1f)`，右 `RoleBadge`。 |

### 3.2 金额与数字排版（钱这一类的唯一口径）

| 组件 / 常量 | 文件:行号 | 怎么用（要点） |
|---|---|---|
| `MoneyText(raw, style=bodyMedium, prefix="¥")` | `⟨src⟩ui/common/Components.kt:150-152` | **全 App 金额显示的唯一入口**：`Text(prefix + formatMoney(raw))`。报表页多数地方用它旁边的页面内 `money()`（`ReportCenter.kt:197`，内部同样走 formatMoney）。 |
| `formatMoney(raw: String?)` | `⟨src⟩util/Money.kt:27-33` | **显示口径**：`"%.2f"` → `trimEnd('0')` → `trimEnd('.')`，`Locale.US`，`"-0"` 摆正成 `"0"`。即 `56.70 → 56.7`、`87.00 → 87`（用户 2026-09-22「有零的全省」）。⛔ 只用于「给人看的字」。 |
| `trimMoneyZeros(raw)` | `⟨src⟩util/Money.kt:52-56` | 可编辑价框预填用：去尾零但**保 4 位精度**（`12.3456` 不许变成 `12.35`）。⛔ 与 formatMoney 不许互换（`:17-22 / :44-48`：「混一次就是『没改价、价却变了』」）。 |
| `goodsTotal()` / `lineTotalValue()` / `goodsTotalText()` / `settleArrears()` / `settleTotal()` | `⟨src⟩util/Money.kt:75-76 / :89-90 / :101-102 / :126-129 / :137-138` | 算钱一律 `BigDecimal` 定点、**全 App 只有一处**；`goodsTotalText()` 是「值」（两位小数、HALF_UP），不是「显示」。报表页展示历史金额时直接印后端字符串，不重算。 |
| `StatBig(label, value, color, extra)`（private） | `⟨src⟩ui/dispatcher/ReportCenter.kt:180-187` | **KPI 大数字的唯一实现**：`bodySmall` 灰标签 + `headlineSmall`(26sp Bold) 彩色值。tab①②③④⑤⑦⑧⑨ 都用它（可 `Modifier.weight(1f)` 两联排）。 |
| `StatRow(label, value[, color])`（private） | `⟨src⟩ui/dispatcher/ReportCenter.kt:189-195` | 页内键值行。⚠️ 源码三处注释（`:1481-1483`、`:1603-1604`、`:1771`）写了同一个坑：**长名字与说明必须各占一行**，否则 `StatRow` 会把长 label 挤成竖排（真机把「粤SEQ4705」挤成三行）。 |
| 自排大数字（不用 `StatBig` 的例外） | `⟨src⟩ui/dispatcher/ReportCenter.kt:1834-1854` | 客户欠款页「该收的钱」自己排：`bodySmall` 标签 + `headlineSmall` 加粗 `#FF6B2C` 大数字 + 「截止 {asOf}」+ 行数。**与 `StatBig` 是第二套大数字写法**（见 §六）。 |
| `InfoRow(label, value, valueColor?)` | `⟨src⟩ui/common/Components.kt:263-278` | 通用键值行：label 固定 92dp `bodyMedium` `onSurfaceVariant`，value `weight(1f)`。 |

### 3.3 颜色语义（一色一功能；同屏两两 RGB 欧氏距离 ≥60）

| 语义 | 色值 / 常量 | 文件:行号 | 用在哪 |
|---|---|---|---|
| 报表中心入口 | `ReportIndigo #6950F5` | `⟨src⟩ui/theme/Color.kt:19` | 报表中心入口卡、底部导航「工作台」Tab（派单端） |
| 钱 / 账本 / 收款 | `MoneyOrange #FF9500` | `⟨src⟩ui/theme/Color.kt:17` | 账本页、报表「营业」四色之一 |
| 挂账 / 欠款警示 / 超限 | `ArrearsTangerine #FF6B2C` | `⟨src⟩ui/theme/Color.kt:18` | 客户欠款大数字（`ReportCenter.kt:1834-1854`）、资金流出（`:713`） |
| 商品 / 数量紫 | `ProductPurple #8455E6` | `⟨src⟩ui/theme/Color.kt:15` | 商品经营页 StatBig（`ReportCenter.kt:416`） |
| 司机 / 成功 / 已完成 / 流入 | `MgrGreen #00B578`（= `SuccessGreen`） | `⟨src⟩ui/theme/Color.kt:11`、`:129` | 司机绩效、营业利润为正（`ReportCenter.kt:1281-1283`）、资金流入（`:712`） |
| 货主 | `ShipperTeal #00A2C7` | `⟨src⟩ui/theme/Color.kt:13` | 客户经营 StatBig（`ReportCenter.kt:601`） |
| 危险 / 异常 / **负值** | `DangerRed #FF5252`、`WarningAmber #FF9F1C`；页面内多用 `#E53935` | `⟨src⟩ui/theme/Color.kt:130-131` | 异常页与审计（`ReportCenter.kt:805/813/935/1025`）、货损金额（`:323/427/1416-1418`）、营业利润为负（`:1281`）、净流入为负（`:720`） |
| 库存深青 / 件数 | `InventoryTeal #00A8A8` | `⟨src⟩ui/theme/Color.kt:16` | 出库总件数（`ReportCenter.kt:417`） |
| 信息 / 数量蓝 | `InfoBlue #1E6FFF` | `⟨src⟩ui/theme/Color.kt:132` | 实际营业金额（`ReportCenter.kt:293`）、成本覆盖页（`:1569`） |
| 收支蓝 | `CashOut #1565C0`（支出）、`CashIn = MgrGreen` | `⟨src⟩ui/theme/Color.kt:82-83` | 资金收支页（`ReportCenter.kt:712-713`） |
| 工资制（中性灰） | `#8A8A8E`；计件司机待结运费 `#FF6B2C` | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:88-94`（§4） | 工资制司机标「工资制」 |
| 亮 / 暗底色 | `BackgroundLight #F2F3F7`、`SurfaceLight #FFFFFF`、`SurfaceVariantLight #ECEFF5`；`SurfaceDark #1B1D23` 必须亮于 `BackgroundDark #0E1014` | `⟨src⟩ui/theme/Color.kt:144-148 / :197-212` | ⛔ 暗色下卡片与背景同色＝信息丢失 |

补充：**订单状态五色**（`⟨src⟩ui/common/SegmentedStatusTabs.kt:36-44` ORDER_TAB_COLORS：全部 #1E6FFF / 派单中 #FFB300 / 已接单 #00A2C7 / 已送达 #00B578 / 已撤销 #8A8A8E / 已退货 #BF5B00 / 已派单 #7C4DFF，**新档只能往末尾加**，因为按位置取色）；**报表四色**（`docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:52-54`：营业橙 / 商品紫 / 司机绿 / 异常红）。

### 3.4 表格行与「逐单明细」已有排版手法

| 手法 | 文件:行号 | 怎么用 |
|---|---|---|
| 纯文字明细（现报表主用法） | `⟨src⟩ui/dispatcher/ReportCenter.kt:1759-1792`（税票逐张两行）、`:1895-2007`（欠款人逐单三行：单号·送达日 / 应收·已收·欠款 / 账龄…起算） | 用 `bodyLarge` 一行 + `bodySmall` 一行拼出来；**列不对齐**（见 §六）。 |
| 可展开行 | `⟨src⟩ui/dispatcher/ReportCenter.kt:1895-2007` | `key = kind + "|" + (unitId ?: name)`；收起时给「点这一行看逐单明细（这一行一共 N 张单）」`#6950F5`。 |
| `OrderCard` / `TintedIcon` | `⟨src⟩ui/common/OrderCard.kt:97-342 / :74-95` | 订单卡（虚线分隔 `:343`）与圆底 tint 图标；报表若要「点进订单」，这是现成的行样式。 |
| `ProductCardKit`（`ProductFact`、`productFacts`、`ProductFacts`、`ProductStockBadge`、`ProductLine`…） | `⟨src⟩ui/common/ProductCardKit.kt:108 / :139 / :146-161 / :162-201 / :250 / :269-309` | 商品事实行「价格 · 库存 · 预留」的取色与文案全在这里；要显示商品名/库存别自己拼串。 |
| 数量必须带单位 | `⟨src⟩ui/common/Units.kt:59`（`qtyWithUnit`）、`:81`（`damageLabel`）、`:153`（`qtyWithUnitConverted`） | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1070-1077` §4.20：数量带单位、件数与金额分列右对齐。 |
| **真表格**（Excel 观感，AI 侧已有） | `⟨src⟩ui/ai/AiRichText.kt:152-271` | 约定表在 `:43-50`：**每格网格线 / 表头底纹+加粗 / 数字右对齐 / 等宽数字(tnum) / 隔行浅底 / 合计行加粗**；列宽用 `TextMeasurer` 实测并夹在 52~168dp（`:129-131 / :140-143`）；装不下就整表横向滚**并写一句「← 这张表有 N 列，左右滑动可以看全 →」**（`:226-233`）。 |
| **标签-值两列表**（确认卡） | `⟨src⟩ui/ai/AiChatScreen.kt:1939-2000`（注释 `:1919-1937`） | 永远两列、值列 `weight(1f)` **换行不横滚**；标签列宽实测夹在 `LabelMin/LabelMax`。用户原话（`:1920-1922`）：「所有卡片只要是那里显示的信息，尽量都使用表格的形式…核心目标是**将信息正确且明显地展示出来**」。 |
| 表格文本解析纯函数 | `⟨src⟩ai/AiCardTable.kt:31`（`AiCardTable`，有单测 `AiCardTableTest`） | 想给报表加「标签/值」或「分段」表格时，先看它能不能直接吃现成字符串。 |

### 3.5 空态 / 加载态 / 错误态 / 截断提示

| 组件 | 文件:行号 | 怎么用 |
|---|---|---|
| `EmptyView(text, icon={Inbox 56dp 灰})` | `⟨src⟩ui/common/Components.kt:155-166` | 通用空态：56dp 灰图标 + 12dp 间距 + `bodyMedium onSurfaceVariant` 居中，上下 padding 48dp。 |
| `ChartEmpty(message="暂无数据")` | `⟨src⟩ui/common/Charts.kt:107-111` | 图表位空态（180dp 居中灰字）。车辆成本页用的是「该时段暂无车辆成本数据」。 |
| `LoadingBox()` | `⟨src⟩ui/common/Components.kt:169-173` | 居中 `CircularProgressIndicator`。报表外壳在 `windowSettled=false` 时整页只画它（`ReportCenter.kt:105-106`）。 |
| `ErrorView(message, onRetry)` | `⟨src⟩ui/common/Components.kt:176-187` | 页面级「这一页没加载出来」专用 + 「重试」。 |
| `FormErrorLine(text)` | `⟨src⟩ui/common/Components.kt:1091-1105` | 表单内的错画在表单里；页面级错误只留给「这一页没加载出来」（`docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1536-1552` §5 偏好）。 |
| `truncationHint(limit, howToSeeMore)` / `TruncationNote(...)` | `⟨src⟩ui/common/Components.kt:1058-1071` | 6 个只回一页的列表页共用**唯一一份措辞**：「只显示了最近 N 条（服务器上限），」+ howToSeeMore；limit 读不到时写「服务器没回报条数」，⛔ 不编数。报表审计屏（`ReportCenter.kt:1180-1186` 附近）用的是「更早的没被列出来（不代表没记录），需要更多请点右上角「导出」」。 |
| `OneShotSnackbar(hostState, message, onConsumed)` | `⟨src⟩ui/common/Components.kt:1034-1045` | 一次性提示（先 `onConsumed()` 再 `showSnackbar`）。 |
| 空态文案的写法（约定） | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1550` | 「默认档是『今天』时，空态文案必须指到那颗药丸」（否则用户以为这一页坏了）；报表现有空态多写成「换成有数据的那一段再看看」（`ReportCenter.kt:1760 / :1896`）。 |

### 3.6 Hint（提示与说明）—— 使用规则与不可犯的错

| 事实 | 文件:行号 |
|---|---|
| `LocalHints = staticCompositionLocalOf<HintPrefs?>` | `⟨src⟩ui/common/Hints.kt:55` |
| `Hint(text, modifier, color, …)`：参数与 material3 `Text(String)` **逐一对齐** | `⟨src⟩ui/common/Hints.kt:68-108` |
| 总开关关掉 → **整句不显示**（`if (prefs != null && !prefs.visible) return`） | `⟨src⟩ui/common/Hints.kt:88` |
| 类注释：Hint 是「提示/说明的唯一入口」；**唯一不可犯的错＝把数据写成 Hint** | `⟨src⟩ui/common/Hints.kt:20-54` |
| `HintOnce(prefs,key,text)` 是 **@Deprecated 兼容壳**（调用点只许减不许增；工作台还在用） | `⟨src⟩ui/common/Hints.kt:124-127`、`⟨src⟩ui/home/WorkbenchScreen.kt:92-98` |
| 「解释句 → Hint；数据/状态/标签/警告/空态/状态回执/口径说明 → 常显 Text」三类身份表 | `docs/HINT_STYLE.md:30-40` |
| **关键解释句四族一律常显**：钱的口径 / 不可逆的后果 / 隐私与费用 / 当前状态的含义（词表 `_hint_inventory.KEY_FAMILIES`） | `docs/HINT_STYLE.md:47-64` |
| 拆句：同一句里教法句留 Hint、关键句单独写常显 Text，两条并排 | `docs/HINT_STYLE.md:66-71` |
| ⛔ 把数据/警告写成 Hint ＝ 关掉提示顺手把金额、数量、单号、失败原因一起关掉（双向红线） | `docs/HINT_STYLE.md:73-78` |
| 长度：默认一行 ≤20 字，带条件/后果 ≤40 字 | `docs/HINT_STYLE.md:80-101` |
| 「常驻的数/标签/按钮/行内说明 ≤ 8 字；解释『按下去会发生什么/这个数是哪来的』走 Hint」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:558-591`（§4.10，用户原话 `:560-564`） |
| 报表页内现有 Hint 用例（审计排序说明、增值税/税汇解释、折旧未覆盖、成本覆盖等） | `⟨src⟩ui/dispatcher/ReportCenter.kt`（见 §二逐页表）；客户欠款页的「不做加减法」是**故意用常显 Text**，理由注释在 `:1870-1873` |

### 3.7 字号 / 字体常量

| 名称 | 值 | 文件:行号 |
|---|---|---|
| `headlineSmall` | 26sp **Bold** | `⟨src⟩ui/theme/Type.kt:11-16` |
| `titleLarge` | 22sp SemiBold | `⟨src⟩ui/theme/Type.kt:17-21` |
| `titleMedium` | 18sp SemiBold | `⟨src⟩ui/theme/Type.kt:23-27` |
| `titleSmall` | 16sp Medium | `⟨src⟩ui/theme/Type.kt:29-33` |
| `bodyLarge` | 16sp Normal | `⟨src⟩ui/theme/Type.kt:35-39` |
| `bodyMedium` | 15sp Normal | `⟨src⟩ui/theme/Type.kt:41-45` |
| `bodySmall` | 13sp Normal | `⟨src⟩ui/theme/Type.kt:47-51` |
| `labelLarge` | 15sp Medium | `⟨src⟩ui/theme/Type.kt:53-57` |
| `labelMedium` | 13sp Medium | `⟨src⟩ui/theme/Type.kt:59-63` |
| 表格字号 `TableFontSize` | 14sp 固定（比正文小一号塞 4~5 列） | `⟨src⟩ui/ai/AiRichText.kt:76-77` |
| ⛔ 不缩小字号 / 不截断 / 不按屏宽缩放 | 一行放不下 → **换行 或 整条滑动**；全 App 只有一把尺 `rememberTextWidth()` | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1018-1068`；`⟨src⟩ui/common/Adaptive.kt:55-56` |

### 3.8 间距 / 圆角 / 网格

| 项 | 值 | 文件:行号 |
|---|---|---|
| 圆角 token `AppShapes` | extraSmall 8 / small 10 / medium **16（卡片）** / large 20 / extraLarge 28 | `⟨src⟩ui/theme/Theme.kt:71-76` |
| `SectionCard` 内边距 | 16dp | `⟨src⟩ui/common/Components.kt:288-303` |
| 页面列表节奏（工作台/入口页范式） | `contentPadding=16dp` + `verticalArrangement=spacedBy(14dp)` | `⟨src⟩ui/home/WorkbenchScreen.kt:85-89` |
| 组间距 / 组标题与卡 | 14dp / 6dp | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1362-1388`（§5.0 第④条） |
| 入口网格列数 | `maxOf(2, 屏宽dp/160)`；工作台固定 4 列（`GRID_COLUMNS=4`，末行补空位） | `⟨src⟩ui/common/EntryGrid.kt:63`；`⟨src⟩ui/home/WorkbenchScreen.kt:180 / :199-272` |
| 图表尺寸与网格 | 高 180dp、4 条网格 `#E5E5EA`、线宽 3f、点半径 4f、标签最多 6 个 10sp；BarChart 圆角 6f / alpha .85 | `⟨src⟩ui/common/Charts.kt:22-65 / :69-103` |
| 状态药丸 `TabPill` | `RoundedCornerShape(12dp)`、选中 `accent.copy(alpha=.14f)` + 1dp 描边(.6) + 加粗同色字、高 40dp、`labelMedium`；⛔ 宁可横滑也不截断 | `⟨src⟩ui/common/SegmentedStatusTabs.kt:109-137 / :61-106` |
| 顶栏时间药丸 `DatePresetPill` | `CircleShape` 高 36dp + `surface` 底 + 1dp 阴影 + `CalendarMonth` 16dp + `labelLarge`；`onClick=null` 时**不画 ▾**（只显示不可点） | `⟨src⟩ui/common/Components.kt:696-731` |

### 3.9 图标与入口

| 规则 / 实现 | 文件:行号 |
|---|---|
| **图标一律 Material Icons (filled)**（白线样式统一） | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1554-1558`（§6） |
| `ModuleEntry(label, route, icon, color=NavBlue, gradient=emptyList())` | `⟨src⟩ui/nav/Modules.kt:39-45` |
| 工作台图标格 `WorkbenchTile`：`shapes.large` 语义色底 + 32dp 白 icon（padding 13dp）+ 8dp 间距 + `labelMedium` 单行；有 gradient 的走 `Brush.linearGradient` | `⟨src⟩ui/home/WorkbenchScreen.kt:276-320` |
| AI 品牌渐变（唯一定义处 `AiBrandColors` / `aiBrandBrush()`） | `⟨src⟩ui/theme/AiBrand.kt`；色值 `⟨src⟩ui/theme/Color.kt:125-127` |
| 入口页图标卡与工作台图标格**各只有一份实现**，⛔ 不许照抄第二份 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:618-709`（§4.13） |
| 选人 / 分类抽屉 / 搜索框（报表若加筛选可直接复用） | `ProductCardKit` 无关；见 `⟨src⟩ui/common/PersonPicker.kt:85 / :140`、`⟨src⟩ui/common/CategoryDrawer.kt:70 / :120`、`⟨src⟩ui/common/Components.kt:1225`（`SearchField`） |

---

## 四、工作台（`ui/dispatcher/Workbench*`）现在的区块结构与它显示的信息

> 说明：仓库里**没有** `ui/dispatcher/Workbench*.kt` 这个文件族 —— 工作台实现在 `⟨src⟩ui/home/WorkbenchScreen.kt`（320 行），入口清单在同目录 `⟨src⟩ui/home/RoleHomeScreen.kt`（258 行）+ `⟨src⟩ui/nav/Modules.kt`（395 行）。下面按实际文件盘。

### 4.1 谁看得到

| 端 | 有没有工作台 | 底栏形态 | 出处 |
|---|---|---|---|
| 派单员 | ✅ 有，且是**第 2 个 Tab**（色 `ReportIndigo #6950F5`） | 派单作业 / **工作台** / 消息 / 我的 | `⟨src⟩ui/nav/Modules.kt:376-382` |
| 货主（含批发商） | ✅ 有，是**第 1 个 Tab**（`NavBlue`） | **工作台** / 消息 / 我的 | `⟨src⟩ui/nav/Modules.kt:389-393` |
| 司机 | ⛔ **根本没有工作台 Tab** | 进行中 / 已完成 / 消息 / 我的 | `⟨src⟩ui/nav/Modules.kt:383-388`、`⟨src⟩ui/home/WorkbenchScreen.kt:121-124`（「别为了它给司机加一个工作台 Tab」） |

工作台**显示哪些图标 = 能力筛，不是角色写死**：`canSee(role, entry)` 查 `ENTRY_CAPABILITY[entry.route]` → `Capabilities.can(role.key, cap)`；`entriesFor(role)` 再 `.filter{ canSee }`（`⟨src⟩ui/nav/Modules.kt:291-302`，判据 `_tools/qa/_check_capability_unification.py`）。

### 4.2 页面区块（从上到下只有三项）

| 序 | 区块 | 内容 | 行号 |
|---|---|---|---|
| 1 | `WelcomeBar` | 一行约 50dp：左 `workbenchHeaderText(role)`（货主「工作台 · 订单与账本」/ 派单员「工作台 · 全量管理」/ 司机「工作台 · 任务与送达」，`⟨src⟩ui/home/WorkbenchScreen.kt:126-130`）+ 右 `RoleBadge(role.key, memberShipper)`；批发商身份由 `container.repo.me().isMember` 问一次，**问不到当普通货主**（fail-closed，`:74-77`） | `⟨src⟩ui/home/WorkbenchScreen.kt:90 / :158-177` |
| 2 | `HintOnce(container.hintPrefs, "workbench.drag", "长按图标可以拖动排序")` | **全项目唯一还在用已废弃 `HintOnce` 的地方** | `⟨src⟩ui/home/WorkbenchScreen.kt:91-98`、`⟨src⟩ui/common/Hints.kt:124-127` |
| 3 | `EntryGrid`（4 列图标网格，长按 300ms 拖动排序） | 图标格 `WorkbenchTile`；末行补空位；顺序按角色存本机（`WorkbenchOrderStore`，松手才落盘） | `⟨src⟩ui/home/WorkbenchScreen.kt:99-106 / :180 / :199-272 / :276-320` |

`LazyColumn` 容器参数：`contentPadding=16dp`、`Arrangement.spacedBy(14dp)`（`:85-89`）。

### 4.3 它显示哪些数？—— **一个数都没有**

- 工作台是**纯入口页**：没有任何 KPI、金额、单数、图表、列表。页面上唯一的"信息"是角色胶囊 + 图标文字 + 那条拖动提示。
- ⛔ 类注释写死（`⟨src⟩ui/home/WorkbenchScreen.kt:37-55`）：2026-09-20 用户要求**去掉卡片**（「以前是没有卡片的，就是底部卡片是没有样式的」，图标直接铺在背景上）；「**只有一张卡片都不该有**」，曾经做过"派单端两张卡片"当天被否，改为「账本管理」入口页（`LedgerHomeScreen`，报表中心那种形式）收进网格一格（`⟨src⟩ui/nav/Modules.kt:113-117`）。「⛔ 别再往这里加第二张卡片」。
- 工作台**头部自己不取数**（`:155` 注释），避免出现第二个网络调用点。
- 派单端网格 = `Modules.dispatcherEntries`（`⟨src⟩ui/nav/Modules.kt:88-199`，**22 格**：代理下单 :89 / 预订单 :93 / 地址与联系人 :94 / 订单管理 :95 / 退货申请 :99 / 账户管理 :100 / 司机管理 :101 / 货主管理 :102 / 批发商管理 :103 / 商品管理 :104 / 采购单 :105 / 发票台账 :106 / 库存管理 :107 / 单位换算 :112 / 账本管理（→ 入口页）:117 / 车辆管理 :119 / 运费模板 :184 / 计费规则 :185 / 司机运费结算 :186 / 挂账单位 :187 / **报表中心 :189-194** / 消息中心 :195）；货主端 = `shipperEntries`（`:247-260`，我的订单 / 下单 / 地址与联系人 / 我的账本 / 消息中心 / 退货申请 + AI 助手最后一格）；司机端 = `driverEntries`（`:285-287`，我的任务 / 我的账本）。
- **与「报表中心」的关系（补全）**：派单端工作台网格里**有**一格「报表中心」（`⟨src⟩ui/nav/Modules.kt:189-194`：`label="报表中心"`、`route=Routes.REPORT_HOME`、`icon=Icons.Default.BarChart`、`color=ReportIndigo`，注释 `:188` 还写着旧文案「直达营业额报表界面（顶部 4 页签：营业/商品/司机/异常）」——**描述已过期**，现在进去是 11 格入口页）；能力键 `Routes.REPORT_HOME to "stats:read"`（`:343`）。
- 路由：`Routes.REPORT_HOME = "report/home"`（`⟨src⟩ui/nav/Routes.kt:242`）；`⟨src⟩ui/nav/NavGraph.kt:621-622` 挂 `ReportHomeScreen`，`:643-653` 挂 **11 条** `ReportCenterScreen(initialTab=…)`（营业/商品/司机/客户/资金/异常/利润/车辆成本/成本覆盖/税账/客户欠款）。**没有"任意页签"路由**：`initialTab` 由进入的那条路由决定，所以从入口卡进入某页后，页内**不能换页签**（见 §六）。

## 五、设计 / 规范文档里与「信息表达」相关的硬规矩（原文 + `文件路径:行号`）

> 取证范围：`AGENTS.md`（仓库根）、`docs/HINT_STYLE.md`（界面提示与说明书写规范，151 行）、`docs/PROJECT_MAP/06_DESIGN_SYSTEM.md`（设计规范本体，1575 行）、`docs/DEVELOPMENT_SPEC.md`（开发流程规范，1478 行）。另有一条来自代码注释里的用户原话（`ui/ai/AiChatScreen.kt`），单列 5.9。
> `docs/DEVELOPMENT_SPEC.md` 是**开发流程**规范（38 节：零、…、三十八），**不含**版式/文案细则；与「信息表达」有关的只有两处可引用：§2.2 第④条必须写成 Must Change / Must Not Change 两块（`docs/DEVELOPMENT_SPEC.md:172-195`）与 §21 证据记录规范（`docs/DEVELOPMENT_SPEC.md:891-929`）。UI 细则全部在 `06_DESIGN_SYSTEM.md`。
> 长句已截取关键分句，其余为原文。

### 5.1 总原则（`docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` §1 核心设计原则）

| 原文 | 出处 | 对报表中心意味着什么 |
|---|---|---|
| 「**一色一功能**：每个功能/模块有唯一语义色，跨端同功能同色（下单绿/账本橙/消息红/地址湖蓝）」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:9` | 报表页里的每个色都要能回答「它在这页代表什么」，不能只因为好看就借模块色 |
| 「**文字层级**：关键是重要的数字/名称用色加粗，次要说明用灰色 `onSurfaceVariant` 小字」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:12` | 报表页所有 `StatBig`/`StatRow` 都在执行这一条；反过来，**该大的数字没大**就是违反它 |
| 「**背景分层**：页面底 `BackgroundLight=#F2F3F7`，卡片白底圆角（`MaterialTheme.shapes`），信息用 SectionCard」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:10` | 报表页的分组一律 `SectionCard`（见 5.5） |
| 「**低调卡片**：白底 + 浅描边（#ECEFF5）或极浅阴影；不要重边框/大圆/浓渐变」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:11` | 入口页 `EntryCardGrid` 的 1dp 描边就是这个（`ui/common/EntryGrid.kt:72-74`） |
| 「**弹窗**：选择/确认类用 `AlertDialog`」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:14` | 报表页只有「解决异常」一个弹窗（`ReportCenter.kt:138-158`），形态正确 |

### 5.2 文案：常驻几个字，解释句走统一入口 `Hint`（`docs/HINT_STYLE.md` + 06 §4.10）

| 原文 | 出处 |
|---|---|
| 「**把它删掉，用户还能不能把这件事做完？** 能 → 它是**解释**，走 `Hint(...)`。不能（它是个数字、状态、报错、按钮点下去的后果）→ 留 `Text(...)`。」 | `docs/HINT_STYLE.md:19-20` |
| 「**它是在「教」还是在「报」？** 教 → `Hint(...)`；报（"共 3 条""已送达""¥44.00"）→ `Text(...)`。」 | `docs/HINT_STYLE.md:21-22` |
| 「**它带 `$` 插值吗？** 带 → **一律算数据**，留 `Text(...)`。⛔ 绝不因为"它读起来像解释"就把带插值的句子挂到开关上。」＋「⚠️ **不只 `$`**：拿 `+` 把运行时值拼进来的同样算数据」 | `docs/HINT_STYLE.md:23-28` |
| 「⛔ **唯一不可犯的错**：把数据/警告写成 `Hint(...)`。那等于"关掉提示"顺手把用户的**金额、数量、单号、失败原因**一起关掉」 | `docs/HINT_STYLE.md:73-75` |
| 「**只有「不重要的 / 繁琐的」信息才隐藏或简化**」＋四族一律常显：**钱的口径 / 不可逆的后果 / 隐私与费用 / 当前状态的含义** | `docs/HINT_STYLE.md:49-58` |
| 「同一句话里既有教法句、又有关键句怎么办？——**拆句**：教法句留在 `Hint(...)`，关键那一句单独写一条 `Text(...)`，两条并排。⛔ **不许**把整条改成 `Text(...)`」 | `docs/HINT_STYLE.md:66-68` |
| 长度：「默认 **一行，≤ 20 字**」「带条件/后果 **两行，≤ 40 字**…前提与后果都要在」「超过 40 字 → **拆**：常驻只留一句，细节放到二级页 / 详情页 / AI 问答」 | `docs/HINT_STYLE.md:84-86` |
| 写法细则：「**说后果，不说功能名**」「**不重复标题**」「**给数字就要给单位**（金额去掉末尾多余的 0，与 `formatMoney` 同源）」「**不写"请注意"**：警告一律用 `⚠️` 开头」「**不写实现细节**」「**动词开头，主语是"你"**」 | `docs/HINT_STYLE.md:117-123` |
| 开关只有一份 `HintPrefs.visible`，根上经 `LocalHints` 提供；默认「**首次登录那一轮默认开，之后自动变关，可手动打开**」 | `docs/HINT_STYLE.md:127-131` |
| 用户原话：常驻说明「大概字数最多是 7 到 8 个字就可以了…比如说共享库，本来就写了一大堆话在下面，没必要」；表格规矩「**常驻的数 / 标签 / 按钮 / 行内说明 ≤ 8 字**」「解释"按下去会发生什么 / 这个数是哪来的"→ 走 `Hint`」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:561-571` |
| ⛔ 不放宽的部分：「**错误/校验信息与数字的口径说明照旧要写清** —— 它们不是教学，是"这次到底发生了什么"」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:589-591` |

### 5.3 数字与口径

| 原文 | 出处 |
|---|---|
| 「**数字的口径词必须跟着实际窗口走**…写它口径的那几个字就必须来自那个窗口本身」＋「⚠️ 自定义区间时**把那段日期显示出来**（药丸上就写 `09-01~09-20`，不是"自定义"三个字）：**一页上至少要有一个地方写着"这些数字是哪一段的"**」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:542,551-552` |
| 「**数量必须带单位**」「**件数与金额分列右对齐**」＋用户原话「就是**件与件数做对齐、价格与价格做个对齐**，他们都**放在右边的**」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1070,1075-1077` |
| ✅「**报表毛利必须带覆盖率说明**；待结运费仅计件司机展示」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1539` |
| 「**给数字就要给单位**：金额去掉末尾多余的 0（与 `formatMoney` 同源）、数量带件/斤、时间带区间」 | `docs/HINT_STYLE.md:119` |

### 5.4 颜色语义（`06_DESIGN_SYSTEM.md` §2 / §4 / §4.12）

| 原文 | 出处 |
|---|---|
| 「**报表四色**（SegmentedStatusTabs 约定）：营业 #FF9500 橙｜商品 #8455E6 紫｜司机 #00B578 绿｜异常 #FF4D4F 红（+报表中心入口靛紫）」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:52-54` |
| 「**语义状态色**：成功/正常 #00B578｜进行中/提醒 #FFB300/#FF9F1C｜危险/异常 #FF4D4F/#FF5252｜信息 #1E6FFF｜挂账警示 #FF6B2C」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:56-58` |
| 「**订单状态五色**：全部 #1E6FFF｜派单中 #FFB300｜已接单 #00A2C7｜已送达 #00B578｜已撤销 #8A8A8E」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:60-62` |
| §4 业务用色：金额（钱）橙 `#FF9500`；数量蓝 `#1E6FFF`；商品名紫 `#8455E6` SemiBold；货损/异常红 `#FF4D4F`/`#E53935`；毛利/成功绿 `#00B578`；工资制司机灰 `#8A8A8E` 标注「工资制」、计件司机待结运费橙红 `#FF6B2C` | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:86-95` |
| 图表配色「取 `ChartPalette`，判据是**两两 RGB 距离 ≥60** —— 两块颜色接近就只能靠图例反查，图等于白画」；入口页 6 格同样「两两距离 ≥60」（`ModulesEntryTest`） | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:609,705-707` |
| 语义色在代码里的唯一出处：`ui/theme/Color.kt:6-20`（SeedBlue/NavBlue/MgrGreen/ProgressYellow/ShipperTeal #00A2C7/MemberGold/ProductPurple/InventoryTeal #00A8A8/MoneyOrange/ArrearsTangerine #FF6B2C/ReportIndigo #6950F5/MessageRed）+ `:129-132`（SuccessGreen/WarningAmber #FF9F1C/DangerRed #FF5252/InfoBlue）；收支专用 `CashIn=MgrGreen`/`CashOut=#1565C0`（`ui/theme/Color.kt:82-83`） | `ui/theme/Color.kt:6-20,82-83,129-132` |

### 5.5 分组、卡片与否决清单（06 §5.0 全局规范）

| 原文 | 出处 |
|---|---|
| 「⛔ **分组一律白卡，不许用描边框当分组**」＋用户原话「只是用**线框**框起来的话太不美观了，而且也不够**醒目对比**…**这就是个设计规范，包括以后也是这样子**」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1362-1367` |
| 「**分组容器 = `SectionCard`**（白卡：圆角 16、极轻阴影、**无边框**，靠灰底分层）」「**组标题在卡外**（一行小字，可带一个语义色小图标）」「卡里只放共用行…**一个描边输入框都不许有**」「分组之间的间距 **14dp**、组标题与卡 **6dp**」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1370-1376` |
| 判据 `_tools/qa/_check_form_panel_style.py`（+ `_reverse_verify_form_panel.py`）：「全库总数只许减不许增，基线在 `_tools/qa/_form_panel_baseline.txt`」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1383-1386` |
| ✅「搜索框一律 `SearchField`」；✅「账本类页面用仪表盘…⛔ 不做"先勾选再看"」；✅「**表单的错画在表单里**（`FormErrorLine`）；页面级错误状态只留给"这一页没加载出来"」；✅「**卡片动作：左＝反向/警示、右＝编辑**」；✅「**列表的时间窗口一律走右上角药丸**（`DatePresetPill`），⛔ 不在列表里铺横滑胶囊行」；✅「**默认档是「今天」时，空态文案必须指到那颗药丸**（否则用户以为这一页坏了）」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1536-1551` |
| 「下拉一律 `ExposedDropdownMenuBox` readOnly 点选回填（⛔ 不要点选 chips 替代下拉）；唯一登记例外=单位选择页」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1516-1522` |

### 5.6 图表（06 §4.12）

| 原文 | 出处 |
|---|---|
| 「**三种图共用一件事**：`ui/common/Charts.kt`（`LineChart` / `BarChart` / `PieChart`）。⛔ **别处不许自己 `Canvas(` 画图**（红线 `_tools/qa/_check_ledger_dashboard.py` 会红；白名单只有 `util/Watermark.kt`）」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:598-600` |
| 「**图上的数必须与屏幕上那个合计同源**…页面自己再 `sumOf` 一遍就是第二份口径 —— 表现是「上面写 ¥3,200、扇形加起来 ¥2,800」，两个数都不报错」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:601-603` |
| 「**数据支持不了就不给那一档**…硬凑一条按天曲线，会在明细被截断时画出**比合计小**的线」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:604-606` |
| 「**扇形的两条硬规矩**：环心那个数 = **切片之和**…切片跟着搜索走、超过 6 块合并成「其他」但**绝不丢**」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:607-608` |
| 日期档位口径写死：「**本月 = 本月 1 日 ~ 今天**（未来的日子没有账）、**上周 = 上周一 ~ 上周日**…第一格是**「全部」＝不带日期条件**」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:615-616` |

### 5.7 一行放不下怎么办（06 §4.19，全局规范）

| 原文 | 出处 |
|---|---|
| 「### 4.19 「一行放不下怎么办」：**换行 或 整条滑动**（⛔ 不缩字号、不截断）」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1018` |
| 「⛔ **不做"按屏宽等比缩放字号/间距"**（把 dp/sp 乘 `屏宽/设计稿宽`，社区叫 AutoSize）…**手机之间本来就不该做两套版式**」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1027-1030` |
| 「**可伸缩的文本必须显式 `weight(1f)`**：不给 weight 时它会去吃宽度、把**后面的兄弟**挤瘪。真机证据（**411dp 下就能看见**）：开销卡的「关联订单 SO2026…」把右边的日期挤成…**四行**」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1061-1063` |
| 「**大屏（≥600dp）怎么办**：只做一件已经落地的事 —— 入口网格列数按宽度算（`ui/common/EntryGrid.kt`，`maxOf(2, 屏宽/160)`）：**手机恒 2 列（外观零变化）**，平板才 3 列以上」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1066-1067` |

### 5.8 图标与主题

| 原文 | 出处 |
|---|---|
| 「图片/图标白线样式统一用 `Material Icons (filled)` —— 依赖 `material-icons-extended`」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1558` |
| 「品牌种子蓝 SeedBlue=#1E6FFF（明快物流蓝，参考日式街头招牌：饱和/明亮/高对比）」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1557` |
| §6.1：随日落自动切换（默认关）；那一行右侧**如实写明依据**「按定位」还是「时区估算，开定位更准」；⛔「暗色下 `SurfaceDark` 必须亮于 `BackgroundDark`」 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1560-1571`、`ui/theme/Color.kt:197,212` |

### 5.9 「信息要明显」——表格化的用户原话（代码注释，不是 docs）

| 原文 | 出处 |
|---|---|
| 用户原话「所有卡片只要是那里显示的信息，尽量都使用表格的形式…核心目标是**将信息正确且明显地展示出来**」 | `android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatScreen.kt:1920-1922` |
| 表格渲染约定（Excel 风格）：每格网格线 / 表头底纹 + 加粗 / 数字右对齐 / 等宽数字 `tnum` / 隔行浅底 / 合计行加粗 | `android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiRichText.kt:43-50` |
| 装不下就整表横滚，并写出来：「← 这张表有 N 列，左右滑动可以看全 →」 | `android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiRichText.kt:226-233` |

### 5.10 改动流程与机器判据（`AGENTS.md`）

| 原文 | 出处 |
|---|---|
| 「L0 展示层（颜色 / 文案 / 排版） ← 最低审查」 | `AGENTS.md:50` |
| 「动手前在「进行中」追加一行（谁 / 什么时候 / 改什么 / 文件清单）；做完移到「已完成」★」 | `AGENTS.md:81` |
| 「非改不可的共享文件（`Apis.kt` / `Dtos.kt` / `AppRepository.kt` / `enums.py` / **`ReportCenter.kt`** …）先重读最新内容、**只做追加式改动**，并在「交叉点」记一笔」 | `AGENTS.md:82` |
| 「新增**审计动作码**（`OperationAction`）→ `_tools/ai/_check_action_labels.py` 会红，除非 `ui/dispatcher/ReportCenter.kt::actionLabel` 里有中文名（否则审计卡片上直接显示原始码）」 | `AGENTS.md:228` |
| UI/文案相关红线（收工必跑）：`python _tools/qa/_check_all.py`；专项：`_check_hints.py`、`_check_hint_key_explain.py`、`_hint_inventory.py --md`（生成 `docs/PROJECT_MAP/09A_HINT_CATALOG.md`）、`_check_form_panel_style.py`、`_check_ledger_dashboard.py`、`_check_sheet_form_pages.py`、`_check_capability_unification.py` | `docs/HINT_STYLE.md:7-11`、`docs/PROJECT_MAP/06_DESIGN_SYSTEM.md:1383` |

---

## 六、人类视角的表达问题清单（现状 → 为什么难读 → 用哪个现成东西改）

> 只列**表达**问题（颜色语义 / 层级 / 对齐 / 文案落点 / 导航），不列数据错误。每条都给现状坐标与可复用件；改法属 L0 展示层（`AGENTS.md:50`），但仍要先写 ID 声明（`AGENTS.md:81`），且 `ReportCenter.kt` 是共享文件、**只能追加式改**（`AGENTS.md:82`）。

### 6.1 颜色语义（同一页里同一个色代表两种意思）

| # | 现状（`文件:行号`） | 为什么人类读起来别扭 | 建议（现成件） |
|---|---|---|---|
| A1 | 入口卡「营业纵览」是橙 `#FF9500`（`ReportHome.kt:35`，与 06 §2「报表四色：营业 #FF9500」一致），点进去页内最大那个数却是蓝 `#1E6FFF`（`ReportCenter.kt:293`） | 用户刚在入口页学会「营业＝橙」，翻页后同一个概念换了颜色，色卡白学；违反「一色一功能」（`06_DESIGN_SYSTEM.md:9`） | 大数字随模块色走：营业页用 `#FF9500`，或入口卡改蓝 —— 二者选一，别各走各的 |
| A2 | 车辆成本合计用危险红 `#E53935`（`ReportCenter.kt:1455`） | 成本是正常经营事实，不是异常；红在本项目专指货损/异常（`06_DESIGN_SYSTEM.md:58,88-95`），用户会以为出事了 | 换金额橙 `#FF9500`（账本/金额色）或中性加粗；红只留给真正的异常 |
| A3 | 资金流出用橙红 `#FF6B2C`（`ReportCenter.kt:713`），而这个色是规范里的「挂账警示」色（`06_DESIGN_SYSTEM.md:58`、`ui/theme/Color.kt:18`） | 「支出」被画成「警示」，与欠款/挂账的色撞车；项目另有专用支出色 `CashOut=#1565C0`（`ui/theme/Color.kt:83`）没人用 | 支出用 `#1565C0`，橙红还给挂账/欠款 |
| A4 | 该交的增值税「负绿正橙」（`ReportCenter.kt:1319`） | 绿在本项目＝成功/收入，这里表示「进项多、留抵」；橙又是账本色。一个负号换来相反的色，靠猜 | 正数（要交）用 `WarningAmber #FF9F1C` 或深灰、负数（留抵）用 `InfoBlue #1E6FFF`；并把「负数 = 留抵、不是退税」从 `Hint`（`:1322`）改成常显一句 |
| A5 | 异常页同时出现两个红：`#E53935`（`:813`）与 `#FF8A65`（`:814`，模块色表里是「司机运费结算」的珊瑚橙） | 同一屏两个红加一个珊瑚橙，用户分不出哪个更急；规范里的危险色只有 `#FF4D4F`/`#FF5252` | 要处理＝`DangerRed #FF5252`，其中钱货风险＝次级档 `WarningAmber #FF9F1C` |
| A6 | 商品经营两个数字借模块色（`ReportCenter.kt:416` 紫 `#8455E6`＝商品管理、`:417` 青 `#00A8A8`＝库存管理 `ui/theme/Color.kt:15-16`）；客户经营用 `#00A2C7`（`:601`＝货主/地址湖蓝 `ui/theme/Color.kt:13`） | 模块色被搬到报表页当「数字色」，跨页后同一个色指的功能变了（一色一功能失效） | 报表页统一一套：金额＝`#FF9500`、数量＝`#1E6FFF`、结果好＝`#00B578 `、结果差＝`#FF5252` |

### 6.2 数字的层级与排版（该大的不大、该对齐的没对齐）

| # | 现状（`文件:行号`） | 为什么人类读起来别扭 | 建议（现成件） |
|---|---|---|---|
| B1 | **司机绩效页一个大数字都没有**：`DriverTab`（`ReportCenter.kt:517-579`）里 `StatBig` 出现 0 次，整页是逐司机的 `StatRow` | 派单员打开这一页的第一问是「这期一共要付多少、多少人是工资制」，现在必须先自己在心里把一列数加起来 | 首屏加 2~3 个 `StatBig`（本期应付合计 / 计件司机 N 人 / 工资制 N 人），并排写法直接抄 `:416-417`（`Modifier.weight(1f)`） |
| B2 | 营业纵览只有 1 个大数字（`ReportCenter.kt:293`），其余十余项平铺成 `StatRow`（`:189-195`） | 主次不分：营业额和「已撤销 N 单」一样大；用户抱怨过「信息太多看不出重点」类问题 | 把「营业额 / 订单数 / 货损金额 / 待处理异常」四个提成大数字，两两一行 |
| B3 | 大数字有**两套实现**：`StatBig`（`ReportCenter.kt:180-187`，private 函数）与客户欠款页自排的 `Text(headlineSmall + Bold + #FF6B2C)`（`:1839`） | 两处的字号/间距/标签灰字各自维护，改一处另一处不动；且 `StatBig` 是 private，别的文件想用只能复制 | 把 `StatBig`/`StatRow` 提到 `ui/common/`（与 `SectionCard`/`MoneyText` 同处），欠款页改用它 |
| B4 | 明细是字符串拼接、列不对齐：税票逐张两行（`ReportCenter.kt:1759-1792`）、欠款人逐单三行（`:1895-2007`） | 数字不右对齐、件数不带单位，用户没法竖着比大小；这正是规范点名的毛病（`06_DESIGN_SYSTEM.md:1070-1077`「件与件数做对齐、价格与价格做个对齐，他们都放在右边的」） | 抄 AI 侧的表格约定：网格线 / 表头底纹加粗 / 数字右对齐 / `tnum` 等宽 / 合计行加粗（`ui/ai/AiRichText.kt:43-50`） |
| B5 | `StatRow` 长 label 被挤成竖排（源码三处注释：`ReportCenter.kt:1481-1483`、`:1603-1604`、`:1771`） | 真机把「粤SEQ4705」挤成三行，一行数变成一列字 | 已定的规避写法：长名字与说明**各占一行**；新加行时不要省这一行 |

### 6.3 文案与口径（该常显的藏了、该在数字旁边的在页尾）

| # | 现状（`文件:行号`） | 为什么人类读起来别扭 | 建议（现成件） |
|---|---|---|---|
| C1 | 审计列表的排序规则挂在 `Hint`（`ReportCenter.kt:859`「排序：改钱/删数据/账号权限 → 改状态 → 其它，同级按时间倒序」） | 「这一页现在是什么状态」属关键解释句四族（`docs/HINT_STYLE.md:58`）；关掉提示后列表顺序无从解释，用户会以为最新改动没被记 | 改成常显 `Text`（同参数，改名即可，`06_DESIGN_SYSTEM.md:573`） |
| C2 | 口径说明 `notes` 全在页尾（`ReportCenter.kt:1377 / 1534 / 1632 / 1797 / 2013`） | 数字在顶、解释在最底，中间隔着十几屏；用户看到毛利时不知道它只覆盖了一部分单 | 与首屏大数字直接相关的那一句提到大数字下方（其余仍留页尾）；判据见 `06_DESIGN_SYSTEM.md:551-552`「一页上至少要有一个地方写着这些数字是哪一段的」 |
| C3 | 异常页页内常显说明是**过期文案**：`ReportCenter.kt:98-103`「这个页面固定看近 30 天：上面是待处理异常，下面是最近的操作日志」，实际已改成三屏（`:798-808` 要处理 / 审计 / 已过去） | 文案指着一个不存在的布局，用户按它去找会找不到 | 改写成三屏的说法（`docs/HINT_STYLE.md:117`「说后果，不说功能名」） |
| C4 | Hint 分布极不均：只有 4 页有 `Hint`（利润 `:1322/:1363`、车辆 `:1494`、成本覆盖 `:1587/:1619`、税账 `:1704/:1736`，另加审计 `:859`）；营业 / 商品 / 司机 / 客户 / 资金 / 异常 六页一个都没有 | 有的页把该常显的塞进了可关闭的提示（C1、C5），有的页该给一句解释却一句没有 | 不是「都得加」：逐条对四族复核（`docs/HINT_STYLE.md:137-139`），属四族的落常显 `Text`，纯教法句才 `Hint` |
| C5 | 税账页一条 `Hint` 90+ 字（`ReportCenter.kt:1322-1325`，含三个分句） | 规范是「两行 ≤ 40 字，超 40 字要拆」（`docs/HINT_STYLE.md:84-86`）；长提示还会被总开关一次性关掉，关掉后「负数不是退税」这个关键点也没了 | 拆句：常驻一句（负数＝留抵，不是退税），细节留 `Hint` 或二级页 |

### 6.4 结构与导航（想对比两张报表要退回入口页）

| # | 现状（`文件:行号`） | 为什么人类读起来别扭 | 建议（现成件） |
|---|---|---|---|
| D1 | **页内不能换页签**：`NavGraph.kt:643-653` 是 11 条独立路由，页签号由 `initialTab` 定死；报表中心的「中心」只在入口页存在 | 看完「营业纵览」想看「商品经营」，必须返回到 11 卡入口页再点一次；来回对比两个数（营业 vs 商品毛利）操作成本极高 | 顶栏加一排页签：`ui/common/SegmentedStatusTabs.kt:61`（放不下会整条横滑，正好装 11 个）或页内「上一页 / 下一页」 |
| D2 | 入口页 11 张卡顺序＝页签号，源码注释写明「只许追加在末尾：key 直接当页签号用」（`ReportHome.kt:41`、`:47`） | 想按业务重要性排序就得动 key（牵动路由），所以现在只能「先有的在前」 | 保持现状即可；本次盘点只是记录这条约束（见 §一） |
| D3 | 只有商品经营页有搜索 / 排序 / 显示全部（VM `ReportCenterViewModel.kt:113-115`），其余 10 页都没有 | 司机绩效（逐司机）、客户欠款（逐客户/单位）这类长名单页，找一个人要滚很久 | 至少给这两页加 `SearchField`（`ui/common/Components.kt:1225`），排序复用 VM 里现成的 `productSort` 三档写法 |
| D4 | 非「异常」页在窗口未定时整页 `LoadingBox`（`ReportCenter.kt:105-106`），用户抱怨过「它会闪两下」（VM `:45` 注释），切页签会再触发一次 | 数据还没到时整页空白 + 转圈，药丸也不画，用户以为点错了 | 保持现状（这是刻意的），但**新加的大数字/图表都要等 `windowSettled` 之后再画**，别再引入第二次闪 |

### 6.5 一句话总结（给人看的）

- 这一套报表页的**骨架是对的**：时间药丸 + 分组白卡 + 大数字 + 口径说明四件都在，组件也齐（`SectionCard`/`StatBig`/`MoneyText`/`ChartEmpty`/`SegmentedStatusTabs`）。
- 最容易让用户读错的不是缺东西，而是**颜色与层级不一致**：同一个概念在三页三种色（A1/A6）、正常数披危险色（A2）、该大的数没大（B1/B2）、明细不对齐（B4）。
- 其次是把「当前状态的含义 / 钱的口径」这类**关键句塞进了可关闭的 Hint**（C1/C5），或者放在用户看不到的页尾（C2）—— 这两条正好是 `docs/HINT_STYLE.md` 四族明文要常显的。

<!-- END -->
