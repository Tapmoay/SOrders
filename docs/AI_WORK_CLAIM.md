# AI 改动声明（多会话协作，先读这一页再动手）

> **这个仓库同时有多个 AI 会话在改代码**（用户 2026-09-20 明确要求：谁要改什么，必须先声明，
> 否则会出现"你在这个文件、他在那个文件"最后互相覆盖）。
>
> 规则很简单，三条：
>
> 1. **动手前**：在本文件「进行中」一节追加一行（谁 / 什么时候 / 改什么 / 文件清单）。
> 2. **看到别人正在改的文件**：不要同时改；确实非改不可（比如共享的 `Apis.kt`），
>    改之前**重新读一遍最新内容**、只做**追加式**改动，并在下面「交叉点」一节记一笔。
> 3. **做完**：把这一行从「进行中」移到「已完成」，一句话写清改完的结论。
4. ⚠️ **`python _tools/qa/_check_all.py --deep` 跑着的时候，别改源码**：它会先拍快照，
   跑完把与快照不一致的文件**按快照写回**（`_tools/ai/_airepo.py::restore_snapshot`），
   覆盖范围是 `android/app/src/{main,test}/java`、`backend/app`、`docs`、`_tools/ai`。
   2026-09-20 实测：一次 --deep 跑了 20 分钟，我在它跑的时候做完的一整轮 UI 改动
   **被静默抹掉**（连带把一个已删的文件恢复回来了）。开跑前先确认没人正在改代码；
   跑完先 `git status` 看一眼，再动别的。

---

## 进行中

### [2026-09-22 07:1x →] 会话：**「白卡规范」扫尾第一批：下单页 + `FormGroup` 收进共用零件**（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

用户点头（「剩下的 67 处要不要我按页面扫」→「**y**」）。

**这一批改了什么**
- `ui/common/FormRows.kt`：**`FormGroup`（分组白卡）从 `AddressScreen` 的 private 实现收进共用零件**
  （下单页也要同一个分组形态；各写一份就是"两个页面的组标题字号/间距不一样"）。
  `AddressScreen.kt` 删掉自己那份，改调共用的那个（签名一致，调用点一行没动）。
- `ui/shipper/OrderCreateScreen.kt`（**代理下单 / 货主下单共用的那一页**）：
  「联系信息」5 个描边输入框 → 共用行（4 个 `FormInputRow` + 1 个 `FormTextAreaRow`「备注」）；
  「改共享地点」弹窗 2 个 → 共用行；「商品信息」弹窗的「商品名称」→ 共用行。
  ⛔ **数量步进器中间那个 96dp 小框故意没改**（它是紧凑控件、不是"标签 + 值"的一行；
  全 App 同一个形态，见 `ProductPicker::QtyDialog`）—— 这类控件算进总数、但不在"表单分组"的范围内。
- 基线 `_tools/qa/_form_panel_baseline.txt`：67 → **59 处 / 24 个文件**（`--update` 重写的那一个数字）。

**⚠️ 这一批**故意**没动的（正面撞车，等对方收工）**
- `DispatcherOrdersScreen.kt`(13 处) / `ShipperOrdersScreen.kt` / `OrderDetailScreen.kt`(7 处) / `OrderCard.kt`
  —— `session-faa17a77` 的「订单管理 / 我的订单：默认档位 + 卡片动作分区」正在进行（他们列了这几个文件）；
- `AccountManageScreen.kt`(3 处) / `AccountManageViewModel.kt` / `Color.kt` / `Theme.kt`
  —— `session-83da1ad7` 的「账户管理卡片 + 抽屉去线框 + 底部抽屉底色」正在进行。
- 其余（`DispatcherPoolScreen` 5 / `UsersManageScreen` 5 / `AiSettingsScreen` 4 / `ReportCenter` 2 / …）
  **等这两条线收工再扫**。

### [2026-09-22 06:4x →] 会话：**订单管理 / 我的订单：默认档位 + 右上角时间药丸 + 卡片动作分区（编辑在右、反向在左）+ 单号对齐可长按复制**（DSH `session-faa17a77-515b-4bcb-bd47-fddae0129342`）

**用户需求（原话）**：「派单员和货主批发商…他不是**我的订单**吗或者**订单管理**」
① 「尤其是派单员，他上面写的…**近 30 条**这个提示删掉啊，他**占位置**了」；
② 「他如果点**已送达**的话，他会有一个…那个**时间**，我们就**复用我们那些代码和形式**在**右上角**，那个有**预选也可以自定义时间**」；
③ 「如果是进来的话，**默认是不会进入「全部」**的，默认是进入**「派单中」**；货主就是**已接单**的，货主他是**默认已接单**的，并且将那个**已接单往前一格排第 2 位置**」；
④ 「货主的那个**时间也移到那上面去**」；
⑤ 「他上面还有一个…**新建订单**，新建订单就先**放在下面**吧，放在**底下**」；
⑥ 「假如像我们**派单员编辑**的话，一定是在**右边**的，而且他就是一个**笔**…**他要一个图标**，**稍微圈一下**；然后呢**异常**的话，就放置在**左边**而且**是最左边**。这样做的好区分，包括以后的那个只要涉及到**编辑**和其他的比如说**删除**等等，**编辑一定在右边**（因为我们的**惯用手是右手**，我们好编辑），但是比如说**相反的操作，就在左边**」；
⑦ 「那个订单点击**详情**，那个**订单号**出现了**错位**…不要缩小一点，这样子就好看一点；同时我们那个**长按订单号是可以复制**」

**文件清单**
- **改**：`ui/dispatcher/DispatcherOrdersScreen.kt` + `DispatcherOrdersViewModel.kt`（默认档位 → 派单中；顶部那条截断提示挪到列表**底部**；右上角时间药丸；卡片动作分区）、
  `ui/shipper/ShipperOrdersScreen.kt` + `ShipperOrdersViewModel.kt`（默认 → 已接单 + 已接单挪到第 2 格；时间药丸；「新增订单」从顶栏挪到底部；卡片动作分区）、
  `ui/common/OrderCard.kt`（动作区分**左/右两栏**：新增 `leading` 槽）、
  `ui/common/Components.kt`（新增**圈底图标动作** `CardActionIcon`；`TintedIcon` 补一个可选 `contentDescription`）、
  `ui/order/OrderDetailScreen.kt`（单号独占一行 + **长按复制**）
- **新增**：`ui/common/OrderTabs.kt`（档位模型 `OrderTab` + `dated` 标记 + `ORDER_LIST_LIMIT`，两个角色共用）、
  `ui/common/Clipboard.kt`（`copyTextToClipboard`，全库唯一的剪贴板实现）、
  红线 `_tools/qa/_check_order_list_ui.py`（68 项）+ 反向验证 `_tools/qa/_reverse_verify_order_list_ui.py`（13 种注入）
- **同步**：`docs/PROJECT_MAP/06_DESIGN_SYSTEM.md`（**§4.2c 新规范：卡片动作左＝反向/右＝编辑**、§4.15 第 7 条、§5 三条偏好）、
  `08_CODE_LOCATOR.md`（订单管理 / 我的订单两行重写 + 新增「订单详情页」一行 + 订单卡片那一行）、
  `_tools/qa/_check_order_return.py`（档位表形状变了 → 锚点重钉）、`_tools/qa/_check_order_list_ui.py` 是新文件
- **顺手**：`docs/PROJECT_MAP/09A_HINT_CATALOG.md` 重新生成了一次（它是 `_hint_inventory.py` 的产物，
  唯一作者是脚本；**未提交** —— 那是提示统一化那条线的在途产物，见下面交叉点）

**⚠️ 交叉点（别人未提交的改动，我一律原样保留）**
- `DispatcherOrdersScreen.kt` / `ShipperOrdersScreen.kt` 上**各有 1 行**是「提示统一化」那条线（`83da1ad7`）的未提交改动
  （`Text(` → `Hint(`，mtime 09-21 21:06）—— 我只动这两行**之外**的内容。
- `ui/common/Components.kt` 上也有那条线的**真实未提交改动**（`FormErrorLine` 那一段，−29/+7 行，mtime 09-21）；
  我加 `CardActionIcon` 的位置在 437 行附近、离它很远，属**追加式**改动，一个字都没动它那一段。
- `ui/ai/AiChatScreen.kt`（真实改动 10/9 行）与 `ui/dispatcher/AccountManageScreen.kt`（1/1 行）同样是那条线的在途改动：
  ⚠️ 我**故意没动这两个文件** —— 它们里面各有一份"复制到剪贴板"的旧实现
  （AiChatScreen 的私有 `copyToClipboard`、AccountManage 的 `LocalClipboardManager`），
  这一轮只把**新的家**建在 `ui/common/Clipboard.kt` 并让订单详情页用它；
  **收编那两份留到它们那两轮落地之后**（现在动＝在别人正在改的文件上做非必要改动）。
- `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` 在我编辑期间**被别人改过**（mtime 06:58，+148/−15）：
  我重读了最新内容再插的 §4.2c 与 §4.15 第 7 条，没有覆盖别人的段落。
- `docs/PROJECT_MAP/09A_HINT_CATALOG.md` 是**生成物**（唯一作者 `_hint_inventory.py`）：
  它当时已经过期（其中 `AccountManageScreen.kt` 的**行号在我动手之前**就对不上），
  我按脚本给的修法重新生成了一次；⚠️ **不提交它**（它还是那条线的未提交产物）。
- `ui/common/OrderCard.kt` 与工作区内容**与 HEAD 逐字节相同**（司机线 `ea27fb2` 那轮已提交）；
  `ui/order/OrderDetailScreen.kt` 的 `git diff` 是**整文件换行符差异**（1510/1510），内容无改动。
  ⚠️ 「提示统一化」那条线的声明里把这两个文件写成「别人正在改 —— **要动先问用户**」→ **已问用户并得到点头**（见下）。

**明确不碰**：`ui/common/Hints.kt` / `core/HintRound.kt` / `_tools/qa/_check_hints.py` / `_hint_inventory.py`（提示统一化那条线正在动）、
商品线（`ui/common/ProductCardKit.kt` / `ProductsScreen.kt` / `ProductForm*` / `ProductBatch*` / `ProductSort*`）、
`ui/profile/**`、`ui/driver/**`、`backend/**`、钱的算法（`order_money.py` / `order_pay.py` 一字不动 —— 本轮**不碰任何金额口径**）。

**✅ 用户点头（2026-09-22 06:5x，原话照录）**
- ① 可以动 `ui/common/OrderCard.kt` + `ui/order/OrderDetailScreen.kt`：「可以动这两个文件（推荐）」。
- ② 截断提示：「挪到列表最底部（推荐）」（不静默删掉）。
- ③ 默认档与时间档（**用户纠正了我第三问的默认值**）：「不行，默认的话**不是「全部」**——默认的是：
  **派单员是「派单中」，货主和批发商他们是「已接单」**。而且**时间默认的是今天**」。
  → 所以：默认档 = 派单中 / 已接单；**时间药丸默认档 = 今天**（不是「全部」）。
  ⚠️ 跟着来的两条硬约束（司机端已经栽过一次，见 `08_CODE_LOCATOR.md` 司机任务那一行）：
  **药丸与空态都不许藏在"列表非空"的分支里**（默认今天 + 今天没单 = 列表本来就是空的，
  藏在空态里用户就换不了档了）；空列表时也必须能改档。

> **✅ 做完了（2026-09-22 07:0x）。证据**
>
> **静态**：`_check_all.py` **62/62** · 新红线 `_check_order_list_ui.py` **68 项** ·
> 反向验证 `_reverse_verify_order_list_ui.py` **13/13**（每种破坏各由一条判据抓住、逐字节还原、
> 用时 7.6 秒 —— 远低于 `_reverse_verify_all.py` 的 60 秒上限）· Android 单测 **1032 用例 / 0 失败**。
>
> **真机（模拟器）**：5554 派单员 + 5556 货主，都装的是同一个包（`assembleEmuDebug`，07:00:19 编出，
> 晚于最后一次源码改动 06:58:27）。逐条对照用户那 7 条：
> ① 顶部那条截断提示**不在顶部**了（挪到列表最后一行）；② 点「已送达」→ **右上角出现「今天」药丸**，
> 点开是「全部/今天/昨天/前天/这周/近 7 天/上周/本月/上月/近一年/自定义」（**预选 + 自定义**都在）；
> ③ 派单员默认档 = **派单中**、货主默认档 = **已接单**（且已接单就在**第 2 格**）；
> ④ 药丸在**顶栏**（空列表时也在 —— 真机上今天没已送达的单，空态写着
> 「「今天」没有已送达的订单 —— 点右上角可以换一段时间」）；⑤ 货主「**新增订单**」在**底部一条栏**；
> ⑥ 卡片 **异常（最左）· 撤回 · 退货 在左，编辑在右**，两处都是**圈底图标**；
> ⑦ 详情页**单号独占一行**（20 个字符不再折行）、状态徽章落到第二行，
> **长按单号 → 粘贴键把 `SO202609206660292708` 原样粘进搜索框**（剪贴板内容端到端验过）。
> 截图归档在 `docs/screenshots/order-list-20260922/`（1~5）。
>
> **⚠️ 本轮新发现的一处重复（没动，下一轮收）**：`ui/dispatcher/AccountManageScreen.kt` 里
> **另一个会话今天也实现了同一条左右规则**，自带一个 `private fun AccountAction(label, icon, tint, onClick)`
> （圈底图标 **+ 文字**，也建在 `TintedIcon` 上）。它和本轮新增的 `CardActionIcon`（只有图标）
> 是"同一个东西两份实现" —— 但那个文件正被别人改着（声明页里它有在途改动），
> 所以我**只记录不动**：收编方式是一处小改（给 `CardActionIcon` 加一个可选 `label`，
> 然后 `AccountAction` 的 12 行换成一次调用）。⚠️ 两处的**圆底画法已经是共用的**（都走 `TintedIcon`），
> 所以现在不会出现"两个页面两种圆角"。见设计系统 §4.2c。
>
> **⚠️ 当时没做的那条，用户在第二轮点名要做 —— 见下面「第二轮」**：`§4.15.5` 那条"自动退档"
> （今天没单自动退到昨天…）。第一轮我按"用户只说了默认今天"没做，用户当场把它说全了。

### 第二轮（2026-09-22 07:1x → 07:5x）：用户把"时间筛选适用哪些档位 + 自动挡"说全了

**用户原话（第二轮）**：「那个只针对…像是**全部、已完成**的（才）要选择时间。对，**全部我们也要有
时间的筛选**，他们是有那个**找订单的规则**，也就是**自动挡**，他需要做。但是比如说其他的…
因为**派单中和已接单他属于正在进行**啊，所以他是**不会有选择时间**，他默认就是今天」

**三条落地**（代码 + 判据 + 反向验证 + 真机）：
1. **「全部」也要有日期窗口**（原来只有已送达/已撤销）；「已退货」同属终态，一并给上；
2. **「派单中」「已接单」不给时间控件**（进行中的单本来就该全都在眼前；
   给它们套窗口 = 积压的老单静默消失，界面上一个字都不说）；
3. **自动挡（自动退档）**：进带窗口的档位先只**探测**哪一档有单
   （今天→昨天→前天→这周→上周→近 7 天→本月→上月，都没有则不带日期条件），定下来
   **只取一次数**（`windowSettled` 门挡住"闪两下"）；用户手动挑过**永不自动改**。

**⚠️ 真机当场抓到我写错的一个行为（这条最值钱）**：第一版照司机端抄了"整个页面只挑一次"
（`autoPickedPreset`），于是"先点「全部」（挑到「今天」）→ 再点「已送达」"就**不再挑了**，
「已送达 + 今天没单」**停在空列表上** —— 正是用户要避免的画面。司机端那页能"只挑一次"是因为它
**只有一个**带窗口的档，这两个页面各有 4 个。改成"**每次进带窗口的档位都重新找**"后真机复验：
直接点「已送达」→ 药丸自己选中「昨天」且列表里有已送达的单；切回「全部」→ 自动回到「今天」。
（顺带核过数据：窗口里的 `SO…0919` 那张单 `created_at` 是 UTC 09-19 18:30 = 北京 09-20 02:30，
**业务日就是 09-20**，所以"昨天"挑对了；单号上的 09-19 是修复前的旧数据 —— 正是
`auth_service.new_order_no` 注释里写的那类"凌晨下的单号日期是前一天"。）

**⚠️ 顺手收掉我自己刚造出来的重复**：这两页的时间窗口状态机第一版是**一字不差抄了两遍**，
仓库自己的 `_tools/qa/_scan_dup.py` 当场报出 5 组跨文件重复（两个 VM + 两个页面）。按本轮的目标
（精简）与上一轮的同一套做法（`CategoryRosterViewModel`），收成抽象基类
**`ui/common/OrderWindowViewModel.kt`**：基类持有 `tab` / `preset` / `customFrom` / `customTo` /
`showDatePresets` / `windowSettled` / `userPickedPreset` / `datedTab` / `periodWord` /
`windowRange` / `applyPreset` / `applyCustomRange` / `selectTab`（含自动挡）；两个子类只给
「本角色的档位表 + 缺省档的**状态名** + `reload()` + `probeHasData()`」。
⚠️ 司机端那条长阶梯也**搬进了 common**（`DatePresets.ORDER_PRESET_LADDER`，原来叫
`DRIVER_PRESET_LADDER` 且只服务司机两页）—— 它自己的注释里就写着"真要合并时家应该安在 DatePresets"。
司机任务/司机账单两页改成引用共享的那一条（那两个文件当时是干净的，改动只有一处引用 + 删掉本地那份）。

**第二轮验收**：`_check_all.py` **63/63** · 红线 `_check_order_list_ui.py` **89 项** ·
反向验证 `_reverse_verify_order_list_ui.py` **22/22**（新增 9 种注入：全部档不给窗口、
给进行中的档加窗口、不自动退档、手动挑过不再记、盘点不挡屏、本地抄阶梯、
自动退档不看手动标记、退回只挑一次、子类不继承内核）· Android 单测 **1032/0**（构建 2m5s）。
真机：5554 派单员 + 5556 货主都装了同一个包，逐条复验（默认档、药丸、自动退档、空态指路、
卡片左右分区、新增订单在底部、单号对齐、长按复制）。
提交：`7871853`（行为修复）· 本轮收编 + 文档见下一条。

**第二轮收编 + 文档**：`ui/common/OrderWindowViewModel.kt`（新）+ 两个 VM + 货主页（`vm.tab`）
+ 红线/反向验证重钉 + 设计系统 §4.15 第 7 条 + 定位表两行 + 这一页。
**再收一处**：两页逐字相同的那句截断提示收成 `ui/common/OrderTabs.kt::ORDER_TRUNCATION_HOW`
（`_scan_dup.py` 把那一整块报成跨文件重复），并**顺手修了一条被这次收编误伤的检查**
（`_check_page_truncation_wiring.py` 的「文案必须点名真入口」原来是**按文件**找关键词的，
那句话搬到 common 之后它就假红了 → 改成跟着 `howToSeeMore = X` 去查共用常量；
**当场反向验证**：页面上写死一句不含入口词的话，它照旧红、还原即绿）。
⚠️ 本轮 `_check_all.py` 唯一那条红是 `_check_endpoint_index_fresh.py`（端点索引因**别人**后端
在途改动而过期）—— 我一个后端文件都没动，没去重生成它（那是他们那条线的产物）。

### 第三轮（2026-09-22 08:0x → 08:5x）：药丸"只显示"形态 + 收编账户管理那份圈底动作

**用户原话①（药丸统一）**：「为了美观，而统一的话，你干脆给那个**已接单**和**派单中**也加一个
图标，但是那个图标**无法选择**，他不会有列表，就是只有显示，今天一个图标然后还今天啊，
就是也说这个信息提醒吧，但是他们点的格式**无法进行选择**的」
**用户原话②（账户管理）**：「对账户管理那个你也做了去吧」（＝同意把那份 `AccountAction`
收进 `CardActionIcon`）。

**① 药丸两种形态**：
- **每一档都画**药丸（顶栏形态统一）；**可按日期筛的档可点**（全部/已送达/已撤销/已退货），
  **派单中/已接单"只显示"**：形态/位置/配色/圆角完全一样，但**不可点、也不画 ▾ 箭头**
  （`DatePresetPill` 的 `onClick` 改成可空；在不能点的东西上画"点我"的记号＝把用户引到
  一个点了没反应的地方）。
- ⚠️ **那颗药丸上写的是「不限时间」，不是用户口述的「今天」** —— 这是本轮唯一一处
  **没照字面做**的地方，理由是查过数据：那两档**不按日期筛**，本机实测**派单中 7 单跨
  09-16~09-21、已接单 8 单跨 09-11~09-20（今天一单都没有）**；写「今天」就是屏幕上的一句假话，
  而那颗药丸**点不开**，用户没法点开它去发现。形态统一做到了，词用的是实话。
  ⛔ 判据拿 `DatePresets.ROW` 逐个核这个词（`DatePresets` 里新增的那个日期档位名一律不许用）。

**② 收编账户管理那份圈底动作**：`CardActionIcon` 加可选参数 **`label`**
（传了＝"圈底图标 + 文字"，不传＝卡片上那个纯图标动作），`AccountManageScreen` 里的
`private fun AccountAction(...)` 缩成**一行委托**（`= CardActionIcon(…, label = label, size = 15.dp,
container = 30.dp)`）。真机核对：那一页观感与改前**完全一样**（左＝删除/停用、右＝编辑）。
⚠️ 顺手删的两个"没人用的 import"里有一个是**假阳性**：`androidx.compose.foundation.clickable`
在这个文件里**一处调用都没有**，但删了之后 `Modifier.combinedClickable(...)` 当场编译不过
（`Unresolved reference 'clickable'`，两次构建对照过）—— 给 `_check_dead_code.py` 加了一张
**按文件登记**的例外表（`NEEDED_DESPITE_UNUSED`，逐条写理由；⛔ 不做全局豁免）。

**⚠️ 真机上还核出一处规范反例、但没提交**：`FreightTemplatesScreen.kt` 的价目卡是
「编辑 · 删除」，而规范是「左＝反向/警示、右＝编辑」。那 2 行我改了**又撤回**：
那个文件正被另一个会话大改（对照 HEAD 有 270+ 行在途，且当时那一版直接编译不过），
我的两行会被他们下一次整份写回覆盖，也会把他们的半成品卷进提交。
现状与理由写在该文件那段注释里；等他们收工后再把「对调 + 判据」一起提交。

**第三轮验收**：`_check_all.py` **64/64** · 红线 `_check_order_list_ui.py` **100 项** ·
反向验证 `_reverse_verify_order_list_ui.py` **26/26**（新增：给进行中的档写日期档位名、
给不可点那颗挂 onClick、账户管理又自己画一遍、子类不继承内核、本地抄阶梯…
以及"药丸两种画法"那条 —— 它还当场抓出我自己判据的一个洞：只断言子串
`DatePresetPill(label = word)` 的话，`…, onClick = …)` 也满足，已收紧成"没有 onClick 的那一次调用"）。
真机（5554 派单员）：派单中＝「📅 不限时间」（无 ▾、点了没反应）、已送达＝「📅 前天 ⌄」（可点，
自动挑档正确：模拟器时区跨了零点 → 今天 09-22 / 前天 09-20 正是那两张已送达单的业务日）、
账户管理三张卡观感不变。

### [2026-09-21 22:4x → 24:0x] 会话：**商品管理改版：先出方案 → 落地第 1 期（参考 POS 的排版与组件复用）**（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

> **状态：方案 + 第 1 期（P2 商品卡零件 / P7 新增编辑商品页 / P5 单位选择页）已做完并验证。**
> 红线 32/32 · 反向验证 18/18 · 单测 1023·0 失败 · `_check_all.py` 只剩**别人文件上的一条**。
> **没做完的（排在第 2/3 期）**：底部三格 + 批量操作 + 回收站、商品排序。
> 文件清单见下面「落地那一期」一节；**`ProductsScreen.kt` / `ProductPicker.kt` / `Routes.kt` / `NavGraph.kt`
> 我已改过，别人再动请先重读**。

**用户需求（原话）**：「参考一下他的商品管理是怎么做的…他其实复用了很多的组件…我们参考他的样式和排版，
**不要完全照抄他的所有的功能**，我们要用我们自己的…像这些我们都可以进行一个照抄或者说是一个参考。
然后你给我一个参考的方案…给我看一下，然后我觉得不错了之后，我们再实际进行落地。」
落地时的追加原话：「**底部栅格组排直接照抄**」「单位就是做到我们现在有的（那）档…只是抄他的那个**布局**的样式」
「商品排序需要做…新开一轮」「这是他的新建商品的界面，我们也改一下我们的新建商品的界面——**不是很好看，也太乱了**」。

核心改动：backend/app/core/schema_bootstrap.py —— 为什么必须动核心：给 products 加 sort_order 列（商品排序要用），线上迁移只有这一个入口。

**A. 方案（22:4x）**：`docs/plan-product-management.md`（拍板记录在 §7、实际交付在 §8）。

**B. 落地第 1 期（23:0x–24:0x，零后端零数据库）**
- 新增：`ui/common/ProductCardKit.kt`（缩略图/事实行/名称色/库存色/售价与库存格式化）、
  `ui/common/FormRows.kt`（表单三种行）、`ui/common/Units.kt`、`ui/common/UnitPickerSheet.kt`、
  `ui/common/CategoryPickerSheet.kt`、`ui/dispatcher/ProductFormScreen.kt` + `ProductFormViewModel.kt`
  （纯函数 `productEdits` = **只发改动过的键**）、单测 `ProductFormDiffTest` + `UnitsTest`、
  红线 `_tools/qa/_check_product_card_single_source.py` + 反向验证 `_reverse_verify_product_card.py`
- 改：`ui/dispatcher/ProductsScreen.kt`（**那个编辑抽屉整段删掉**，-462/+52）、`ProductsViewModel.kt`
  （表单状态搬走，-184/+18；加 `start()`）、`ui/common/ProductPicker.kt`、`ui/shipper/OrderCreateScreen.kt`、
  `ui/dispatcher/BatchPriceSheets.kt`、`ui/nav/Routes.kt`、`ui/nav/NavGraph.kt`、
  `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md`（§4.1 指向零件 + **§5 两条例外**）、`08_CODE_LOCATOR.md`（两行新条目）
- 真机（模拟器 5556 借来当派单员，用完已**还给货主账号**）走到：商品管理外观与改前一致 →
  商品新增 = 参考图形态 → 单位 chips 页 → 分组单选页 → 保存成功 → 编辑时**只改名称，别人同时改的售价活下来了**。
- **改前/改后截图对比已经补齐**（`git worktree` 单独编一份 HEAD 的旧包，装到 5556 截改前，再装回改后截同一屏）：
  四张在 `docs/screenshots/product-form-20260921/`（4↔5 表单、6↔7 单位；0–3 是改后各屏）。
- ⚠️ **真机抓到两个我自己的缺陷**（都已修）：① `FormInputRow` 点标签不聚焦（整行可点 + `FocusRequester`）；
  ② 单位/分组选择页的"搜不到"两句写成了 `Hint` —— 那是**空态文案**，被总开关藏掉后整屏空白，
  `_check_hints.py` 抓出来的，已改回 `Text`（并在 `_hint_inventory.OVERRIDE` 里记了一笔）。
- 没做也刻意没做：库存管理页**没有**并进 `ProductCardKit`（它那块是库存状态块、不是商品缩略图）、
  P5 去掉了"最近使用过的单位"（"库里已经在用的"是更好的来源）。

**B2. 第二批（24:1x，用户看完第 1 期之后的反馈）**
- **商品卡重排**（`ProductsScreen`）：图 52→88dp、第一行「图+名称+售价」、第二行「库存」、
  第三行**三个等宽大按钮**（改价 / 沽清(上架) / 编辑）；**卡片上的 ⋮ 整个删掉**。
- **⋮ 的三项搬进编辑页**（`ProductFormScreen` 新增「更多操作」卡：各批发商价格 / 成本价历史 / 删除商品）
  → `ProductsViewModel` 里那套 `costHistory*` 与 `delete` 一起搬进 `ProductFormViewModel`；
  `CostHistoryDialog` / `CostHistoryRow` 改成 `internal` 给编辑页复用。
- **底栏三格**（分类管理 / **商品新增圆钮** / 批量操作）+ 顶栏新增「排序」。
- **新页**：`ProductBatchScreen`（勾商品 + 改分组/沽清/上架/删除，逐条 + 逐条汇报）、
  `ProductSortScreen`（长按拖动 / ↑置顶 / 完成逐条写 `sort_order`）。
- **后端**：`products.sort_order` 列（模型 + schema + `schema_bootstrap` ALTER + `ORDER BY` 的 CASE）
  + 回归测试 `backend/tests/test_product_sort_order.py`（3 例）。
- 验证：`_check_all.py` **59/59** · Android 单测 **1023/0** · 后端 **693 passed** ·
  真机四屏截图在 `docs/screenshots/product-form-20260921/`（8/9/10 三张是这一批的）。
- 抓到并修掉：**`sort_order=0` 会排在 1 前面**（点置顶反而沉底，实测抓到）、
  排序页说明句的位置错（被判成空态句）、`Color(Success)` 写法编译不过。
- ⚠️ **下一批待做**：**回收站**（删除的界面恢复入口 —— 用户的硬规矩要求"手边有"，目前只有 AI 撤回卡）。

**明确不碰**：`backend/**` 除 `products.py` / `product.py` / `schemas/product.py` / `schema_bootstrap.py`（已声明）之外没动；`_tools/ai/**` 没动；`ui/profile/**` 是那位会话的地方。

⚠️ **两件给下一个人的事**：
1. 「提示/说明统一化」那一轮（`session-83da1ad7`）的改动**仍然没有提交**，而它和这一轮改的页面在
   同一个工作区里 —— 提交时**一起提交即可**（两轮在 `ProfileScreen.kt` 等处已经交织）。
2. 我这一轮**没提交**（原因同上：`git add` 我的文件就会把别人未提交的改动一起带进来）。
   落地清单与验证口径都在 `docs/plan-product-management.md §8`，提交时照着写 message 即可。

**交叉点（我实际动过的不属于我的东西）**：`09A_HINT_CATALOG.md`（机器生成，按它自己印的修法重跑过两次）、
`_tools/qa/_hint_inventory.py` 的 `OVERRIDE` 表（**只加了 2 条** ProductFormScreen 的解释句，
带理由；另 2 条我原本以为是误判、后来发现是**空态句**，已撤掉并把代码改回 `Text`）。

### [2026-09-21 20:4x →] 会话：**界面「提示/说明」统一化 —— 取消"说三次就消失"、改成一个总开关 + 统一接口 + 书写规范**（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）

> **状态：✅ 全部完成（2026-09-21 22:3x）**。四个交付 + `ProfileScreen` 那三处都改完并验证过
> （红线 29 项 / 反向验证 15/15 / 单测 1004·0 失败 / `_check_all.py` 57/57 / 真机两端实测）。
> **本会话当前不再有进行中的改动** —— 别人可以放心动下面列出的任何文件。
> 只剩两条「下一轮可做」：单位词表（`DIGIT_UNIT`）收紧、司机端真机复验（见文末）。

**用户需求（原话）**：
「从我们写一些像我用红色框框起来的那种**提示说明**，包括我们有个按钮也叫个「**提示**」按钮 ——
这个按钮的机制是这样子的：**每三次只展现三次，三次看见之后他就自动消失**。我们**取消这个机制**，
改成**一个按钮开关**：打开就打开**所有的提示相关的内容**，关闭就关闭**所有的提示**，就按我们正常的
按钮进行显示。同时你也要写一个**写说明的规范**，然后我们**统一走一个接口**，把所有的都走 ——
所以这个任务比较庞大，因为我们有 3 个端，每个端的很多功能和页面都写了很多的说明。还有一件事：
如果有些说明**过于冗长，你要做一个精简**，但是**不能丢句意还有语义**。包括我们以后写其他的功能和
开发的时候要写说明（提示），都要按照这个规范走统一的接口。」

**现状（已勘明，别重复找）**：
- 机制的唯一实现 = `core/HintPrefs.kt`（`MAX_TIMES = 3` / `seen` / `markSeen` / `hasLeft` / `alwaysOn`）；
  渲染的唯一入口 = `ui/common/Components.kt::HintOnce`，**只有 6 处调用**
  （`OrderDetailScreen` 3、`OrderCreateScreen` 3、`WorkbenchScreen` 1）；
  开关在 `ui/profile/ProfileScreen.kt` 的「提示」那一格（副标题 `一直显示` / `说三次就不说了`）
- ⚠️ **大头不在这 6 处**：用户红框圈的是各页面**各写一遍的说明文字** —— `supportingContent` 7 处，
  以及 `typography.bodySmall` **259 处**里那一部分"解释句"（设置项副标题、表单帮助句、空态指路句…）

**A. 机制改写（我做）**
- `core/HintPrefs.kt`：**删掉 per-key 计数**（`seen`/`markSeen`/`hasLeft`/`MAX_TIMES`/`GUARD_MS`），
  只留一个**总开关**；`HintOnce` 变成"开关开就画、关就一句都不画"
- ⚠️ `SharedPreferences("hints")` 里旧的 per-key 整数**不清理、只是不再读**（升级用户不会因残留脏值异常）
- ⚠️ 语义变化写进注释：**"看三次就消失"这个行为彻底没有了**（不是"换成默认关"）

**B. 「我的 → 提示」变成总开关（我做，**排在最后**）**
- ⚠️ **交叉点（已确认冲突）**：`ui/profile/ProfileScreen.kt` **正被另一会话改**
  （司机线第三轮 A 段：加「我的账单」入口条件，见本文件 line 37）→ 本轮**先不动它**；
  等对方收工或用户点头后再改这一格，且只做**追加式**改动 + 在「交叉点」记一笔

**C. 统一接口 + 全库迁移（我做）**
- **新增** `ui/common/Hints.kt`：**唯一入口**（"画不画" + 统一版式 + 分类），新文件、不与任何人冲突
- **新增** `_tools/qa/_hint_inventory.py`：**清单自己算**（扫源码抽说明文字的字面量 + `文件:行号`，
  按「数据 / 解释 / 警告·安全」分类）→ 生成物 `docs/PROJECT_MAP/09_HINT_CATALOG.md`
- 逐条迁移 + **冗长的做精简**（交付时给「原文 → 精简后」对照表，用户可核对）

**D. 规范 + 机器判据（我做）**
- **新增** `docs/HINT_STYLE.md`：书写规范（长度上限、什么必须常驻、什么算提示、**什么永不隐藏**）
- **新增** `_tools/qa/_check_hints.py`（红线）+ `_tools/qa/_reverse_verify_hints.py`（反向验证）

**⛔ 明确不碰（本轮）**：后端任何代码、`ui/driver/**`、`ui/dispatcher/ExpensesScreen.kt`、
司机账本/运费结算线、`frontend/*`、钱的算法（`order_money.py` / `driver_pay.py`）。
**别人正在改、本轮一律不动**（要动先问用户）：`ui/profile/ProfileScreen.kt`、`ui/common/OrderCard.kt`、
`ui/order/OrderDetailScreen.kt`（司机线第二轮 A 段 + 第三轮 A 段）。
**共享文件**：`ui/common/Components.kt`（多人改过）—— 只做**追加式**改动；动 `HintOnce` 旧签名前
先重读最新内容，并在「交叉点」记一笔。

**进度（2026-09-21 20:5x）—— 机制已落地、解释句已迁移 43 处**：
- **机制**：`core/HintPrefs.kt` 整文件改写（per-key 计数 → **一个总开关** +
  「首次登录那一轮默认开、之后冷启动自动关、手拨过就不再自动改」）；新增
  `ui/common/Hints.kt`（`Hint` = `Text` 的**完全替身**，参数表逐一对齐；`LocalHints` 从根上提供）；
  `HintOnce` 降级成兼容壳（6 个调用点一个字都没动）；`MainActivity`（提供 + 冷启动）、
  `ui/login/LoginViewModel.kt`（登录成功）各追加几行挂钩
- **规范**：新增 `docs/HINT_STYLE.md`（三条判据 / 三类身份 / 长度尺子 20·40 / 精简三手法 + 对照例 /
  开关机制 / 新功能落地清单）
- **清单自己算**：新增 `_tools/qa/_hint_inventory.py`（211 个 .kt → 1271 条文案：
  解释 **51** / 空态 **11** / 数据 **1180** / 警告 **29**），三道反向约束（文件数/文案数/解释句数）+ 复核表防化石
- **迁移**：新增 `_tools/qa/_migrate_hints.py`（默认预演；`--apply` 前把每个文件的**整份**备份到
  `_archive/hint-migration-backup/`；`--aggressive` 才动"首参是字符串表达式"的调用，
  `AnnotatedString` 一律排除）。**已改 43 处 / 24 个文件**，逐字节核对过：每个 `-Text(` 都有配对的
  `+Hint(`，**0 可疑**
- ⚠️ **踩到并修掉的两个坑（都会静默出错）**：① 盘点工具用通用换行读文件 → **CRLF 文件里所有偏移
  都比真实文件小**，迁移按偏移改名会**改到别处**（实测 5 个 CRLF 文件全落在"这里已经不是 Text"被跳过，
  靠那道校验才没出事）；已改成 `newline=""`。② 复核表第一版按"前 12 字"匹配，而表里几条键写到 13~14 字
  → **静默匹配不上**，而"防化石"检查用的是 `startswith`（长键照样成立）→ 两个洞一起把错配藏住了；
  现已统一成子串
- **还没做**：剩余 2 处解释句要人工（调用里带 `AnnotatedString`）；`ProfileScreen` 那一格的副标题
  （等司机线收工）；红线 `_tools/qa/_check_hints.py` + 反向验证；目录
  `docs/PROJECT_MAP/09A_HINT_CATALOG.md`（工具的 `--md` 已能生成）

**追加（2026-09-21 21:1x）—— 红线 / 反向验证 / 精简 都做完了**：
- **红线** `_tools/qa/_check_hints.py`（**28 项**，`_check_all.py` 自动收 → 现在 **57 个检查**）：
  双向判据（该 `Hint` 的裸 `Text` ＝关不掉；不该 `Hint` 的 `Hint` ＝把数据/状态关掉）＋
  机制不许回退（旧 per-key 计数、`Hint` 的短路 return、根上 `LocalHints`、冷启动/登录两个挂钩、
  兼容壳点数只许减不许增）＋ 规范与目录 ＋ 反空转下限。
  ⚠️ **扫源码的断言先剥注释**：新 `HintPrefs` 的 KDoc 里就写着旧机制的名字，
  不剥注释会被自己那段说明误判成红。
- **反向验证** `_tools/qa/_reverse_verify_hints.py`：**15 条注入全部被抓**，每条按字节还原；
  还原前先比对"我刚写进去的那份还在不在"，别人插一脚就**拒绝还原**。
  ⛔ 故意**不注入** `ProfileScreen`（别人的文件）—— 对它的判据只能靠人工验收。
- **生成物新鲜度**：`_hint_inventory.py --check`（与 `_check_endpoint_index_fresh.py` 同一套路：
  委托给文档的作者脚本，不重写比对逻辑）。
- **精简**：8 条 >40 字的解释句全部压过（规范 §3 的口径：一行 ≤20 / 两行 ≤40）——
  现在**最长 40 字、超长 0 条**；「原文 → 精简后」对照例写进 `docs/HINT_STYLE.md` §3。
- **迁移补完**：收紧后的分类器又认出 4 条（新增"状态回执"与"`+` 拼接活值"两条判据，
  后者是货主账本页真抓到的）→ 已全部处理，**裸露解释句 = 0**；`AlertSettingsScreen` 的
  「已确认：…」那处**误迁移已改回 `Text`**（状态回执不该被开关藏掉）。
- **还没做**：`ProfileScreen` 那一格的副标题（等司机线收工；红线的 `PENDING` 表钉着它，
  改好后那条会**变红提醒删除**）。（真机验收已在下面做完。）

**追加（2026-09-21 21:4x）—— 真机验收已做（货主端 emulator-5556，六种场景全过）**：
装 `assembleEmuDebug`（42.9MB，v0.2.2·2026092101）到 5556（货主 13800000002），
用 `_tools/qa/_emu_ui.py` 按文字导航（不写死坐标），六种场景逐条实测：

| # | 场景 | 预期 | 实测 |
|---|---|---|---|
| 1 | 装了新包、**从未登录过**（已登录态直接升级） | 默认关：解释句不显示、数据照旧 | ✅ AI 设置页 `API Key 加密存在本机…`/`OpenAI 兼容地址，例…`/`注：部分模型只支持…`/`关掉哪个…` 全部**不在**；而 `Base URL`/`模型名`/`思考强度`/`拉取模型列表`/`能查：…`/`例如 deepseek-flash…`（带插值）**都在** |
| 2 | 拨开开关 | 解释句回来 | ✅ 上列解释句**全部出现** |
| 3 | 拨回去（**不重启**） | 立刻又隐藏 | ✅ 证明是同一份可观察状态在生效，不是冷启动才读 |
| 4 | `pm clear` + **首次登录** | 自动打开一轮 | ✅ 「我的 → 提示」副标题 `一直显示` |
| 5 | **冷启动**（force-stop 重开） | 自动关上 | ✅ 副标题 `说三次就不说了` |
| 6 | **手动打开 + 冷启动** | 不许被自动改（反悔条款） | ✅ 仍是 `一直显示` |

证据截图：`_archive/hint-e2e-02-A-off.png`（关，AI 设置页）/ `-03-B-on.png`（开）/
`-04-C-off-again.png`（拨回，未重启）/ `-05-profile-switch.png`（我的页那格 `一直显示`）。
⚠️ 5556 最后停在**货主 13800000002**、开关**关**（＝冷启动后的默认样子）。

**派单端也在真机上验过（2026-09-21 21:5x，在同一台 5556 上登录派单员 13800000001 做的，
⛔ 没去动 5554/5558 —— 那两台跑的是别的会话的包）**：
「工作台 → 商品管理 → 商品新增」这一页：
- 开关**开**：「支持相册选图，自动压缩为 jpg 上传」（`Hint`）**在**；
- 开关**关**：这一句**消失**，而同屏的
  「商品名称（必填）」「成本价（选填）」「初始库存（选填）」（字段元信息）、
  「新建默认上架；关闭开关则保存后货主不可见」（**后果警告**）、
  「成本价用于报表计算毛利率，留空按 0 计」**照旧在**。
- 截图 `_archive/hint-e2e-06-dispatcher-on.png` / `-07-dispatcher-off.png`。
- 验完把 5556 **登回货主**（13800000002 永盛食品），开关留在「关」（＝冷启动后的默认样子）。

**✅ 已改（2026-09-21 22:0x）—— 用户拍板「可以你现在就改吧，以为他已经停止活跃了」**：
`ui/profile/ProfileScreen.kt` 按上面那张预登记清单**三处全改完**（改前重读了它 21:39 提交后的最新内容；
对方的提交只动了 VERSION + 两个发版脚本 + 这个文件 14 行的滚动修复，与这三处不重叠）：
1. 「提示」那一格：副标题 → **`显示所有说明` / `不显示说明`**，并把讲"最多 3 次"的注释整段换成新口径；
   `container.hintPrefs.alwaysOn` → **`setByUser(...)`**；顺手**删掉本地镜像**
   （`remember { mutableStateOf(prefs.alwaysOn) }`）—— 总开关本来就是 Compose 可观察状态，
   再镜像一份就是"两处各有一个数"（同时清掉了随之悬空的 `remember`/`mutableStateOf` 两个 import，
   是 `_check_dead_code.py` 抓出来的）。
2. 「消息提醒」副标题（`语音播报 / 后台接收新单`、`通知栏提醒 / 后台接收新单`）→ **`Hint(...)`**，
   并在 `_hint_inventory.OVERRIDE` 各加一条「归 EXPLAIN」的理由（判成 DATA 是"新**单**"命中单位词）。
3. 「随日落自动切换」那一行**按状态分开渲染**：自动切换关着时那是"这个模式怎么工作"的**说明** → `Hint`；
   开着时同一行是**当前状态**（几点转、按定位还是估算） → `Text`。
   两句话都仍来自 `SunClock.summary`（✅ 没在页面里另抄一份文案）。
4. `HintPrefs.alwaysOn` 那个 `@Deprecated` 兼容壳**已删除**（全仓已无调用点）；
   红线里的 `PENDING` 那条也按设计**删掉了**（它命中不到就该红，逼人回来删 —— 现在删了）。
- **真机复验（同一台 5556 货主）**：关 → `提示 · 不显示说明`、「消息提醒」「随日落」两行副标题**都隐藏**、
  `仅前台接收`（运行时状态）**照旧在**；开 → 两行说明 + `显示所有说明` 全部回来。
  截图 `_archive/hint-e2e-08-profile-on.png`。
- 验证：编译 ✓ · 红线 **29 项** ✓ · 反向验证 **15/15** ✓ · `_hint_inventory --check` ✓ · 单测 1004/0 ✓ ·
  `_check_all.py` **57/57**（那两处别人的红也已由他们修好）。

**追加（2026-09-21 21:2x）—— 把行为契约抠成纯函数 + 单测**：
- 新增 `core/HintRound.kt`（**纯函数状态机**，无 Android 依赖）：`onLogin` / `onAppStart` /
  `setByUser` / `fromLegacy` 四条决定集中在这里；`core/HintPrefs.kt` **只落盘 + 暴露可观察状态**
  （`apply(State)` 是唯一的写入口）。
- 新增 `HintRoundTest`（**13 例**）：覆盖"第一次登录开 → 下次冷启动关 → 手拨过不再自动改"的
  三种**顺序**，含两条**反悔条款**（手动打开后冷启动不许关；手动关掉后再登录不许又打开）与老安装迁移口径。
  理由：这些顺序错了的表现是"**开关自己会变**"，真机上极难复现（要点登录、杀进程、再开、再拨）。
- 红线相应加了 2 项（决定在 `HintRound` 里、状态机有单测）→ 现在 **30 项**；反向验证仍 **15/15**。
- 单测总数 **991 → 1004**（0 失败）。

### [2026-09-21 20:xx →] 会话：**安卓模拟器安装白PP并登录司机账号**（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）· 第三轮（新手机真机 + 三条新需求）

**由来**：新手机（PDCM00 / Android 12 / arm64）USB 调试接上后，装了 **0.2.1**（`2026092103`，
已发布：`http://8.145.40.22/apk`），真机跑完一遍。过程中在 prod 上抓到一个"钱看不见"的洞（见 A）。
用户当场定的三件事：①账本入口改成「**有钱要对就显示**」（他选了我推荐的那条）；②给**测试账号**一个
默认 API key（`1380000000X` 命名的那批）；③再补两个测试账号：**4 = 司机（没有固定工资，相当于挂车）**、
**5 = 普通货主**。

**A. 司机「我的账单」入口：有钱要对就显示（我）**
- 现象：prod 司机 13800000003 当前规则是「月薪司机 · 固定 6500」→ 入口不显示；可他账上有
  **92 笔按单账单 ¥2024**（本月 21 单 ¥462，每单 ¥22），`GET /freight-settlement` 直接调是**正常返回**的
  —— 也就是说这笔钱在 App 里没有任何地方看得到（改动前卡片上那个 ¥77 是**货主运费**，不是他应得）。
- 改：`backend/app/schemas/user.py`（出参加一个字段）、`backend/app/api/v1/users.py`（`/users/me` 里算它）、
  `backend/app/services/driver_pay.py`（**判据落在这——它是钱的唯一口径处**，所以这是**核心改动**）、
  `android/.../data/remote/dto/Dtos.kt` + `ui/profile/ProfileScreen.kt`（入口条件 = 当前按单 **或** 账上有按单账单）
- ⛔ **纯固定工资且从来没按单跑过**的司机**仍然没有这一格**（用户 09-20 的规则不变，判据会钉住这条）
- 判据：`_tools/qa/_check_driver_money.py` 追加 + `_reverse_verify_driver_money.py` 追加注入 + 后端单测

**B. 测试账号的默认 AI Key（我）**
- 服务器 `/opt/SOrders/.env` 放 key（**不进仓库**）；后端出参给白名单手机号下发；App 在"用户自己没配过 key"时自动用它
- ⛔ 红线：仓库里不许出现这个 key（`_check_secrets.py` 已有）；端点必须**登录 + 白名单**双门；
  客户端**只**在用户没配过自己的 key 时用默认的（配过就永远用自己的）

**C. 补两个测试账号（我，走真实端点 + 审计日志）**
- `13800000004`：司机、车型挂车（trailer）、**不挂固定工资规则**；`13800000005`：普通货主（非会员）
- 密码与其余测试号一致（123321）；建完逐个登录验一遍（4 要能在 App 里看到「我的账本」）

**明确不碰**：`ui/dispatcher/*`、`ui/shipper/*`、`frontend/*`、钱的算法（`order_money.py` / `order_pay` 本体）。

> **A/B/C ✅ 全部完成（2026-09-21 21:5x）；线上后端已发到 `021543e`、App 已发 0.2.1 → 0.2.2 → 0.2.3**
>
> **A（司机账本入口）**：判据拆成两个字段——`pays_per_order`（以后派的单按不按单算，派单端用，**语义没动**）
> 与新增 `has_per_order_earnings`（他现在有没有按单的账要看），判据落在 `driver_pay.has_per_order_earnings`
> （**核心改动**，已按要求在「进行中」声明）：当前按单 **或** 账上已有按单账单。
> ⚠️ 顺手避开一个跨库陷阱：`DriverBillType.PIECE` 的值是**小写** `piece`，MySQL 的 `=` 不区分大小写（线上照命中）
> 而 SQLite **区分**（本地永远查不到）→ 判据用 `func.upper()` 归一。两个敏感性实验都做过（退回旧判据 1 红、
> 去掉大小写归一 1 红）。判据 `_check_driver_money.py` 23 → **35 项**、反向验证 11 → **19 条**、后端 +2 例测试。
> **prod 实测**：司机 13800000003 `pays_per_order=false` + `has_per_order_earnings=true` ✓。
>
> **B（测试账号默认模型服务）**：key 只在服务器 `/opt/SOrders/.env`（600，**不进仓库、也不进 APK**——仓库是公开的、
> APK 挂在公网）；新增 `GET /api/v1/system/ai-default`，三道门：登录 + 手机号前缀白名单（`AI_TEST_PHONE_PREFIX`，
> 留空=能力关闭）+ 没配 key 时如实 404；App 只在"用户自己没配过 key"时取一次、存进 Keystore 并标记来源。
> 判据：红线 **§33 共 18 项**（含"每个 DTO 都必须 @Serializable"这条**通用**判据）+ 反向验证 **12/12**；
> 读侧覆盖率里写明「模型**不许**读它」（返回的是明文 key）。
> ⚠️ **我自己写出的 bug（真机 E2E 抓到）**：`AiDefaultDto` 少了 `@Serializable` → kotlinx.serialization 在**发请求之前**
> 就失败，而调用点把它当"拿不到"静默吞掉（后端日志里**一条请求都没有**）——已修 + 补通用判据 + 补注入。
>
> **C（测试账号）**：`13800000004`（司机/挂车）**本来就有**（未挂规则 → 按单计费）；`13800000005`（普通货主）
> 已用真实端点创建（201，走审计）。⚠️ `13800000002` 目前是**普通货主**（`is_member=false`），
> 而用户说"他其实更多是批发商"——**要不要改成批发商货主，等用户点头**（改它会多出核销/专属价那套能力）。
>
> **新手机（PDCM00 / Android 12 / arm64）真机测试**（0.2.1 → 0.2.2 → 0.2.3 逐版装）：
> ① 司机端卡片/详情**一个金额都没有**（库里那两张单是 PIECE + ¥77/¥98，改动前必显示）；「我的账本」按 A 出现了，
> 显示 `合计 ¥44.00`、每单 `¥22.00` + 计件/运费明细；版本号/检查更新都对（`已是最新 0.2.3`）。
> ② 派单员测试号登录后**不用填 key** 就能用 AI：模拟器与**真机各跑通一次真模型问答**
> （「待派单池现在还有 4 单」/「还有 26 单没派出去」，都走了真实读工具）。
> ③ ⚠️ **真机抓到一个阻塞缺陷并修掉（0.2.3）**：`ProfileScreen` 那一列是**不可滚动**的 `Column`，
> 内容比屏幕高时最下面的「检查更新」「退出登录」被顶出屏幕且**滚不到**（触发点正是 A 新加的那一格；
> 用户手机字体比模拟器大）——修法是给那一列加 `verticalScroll`，真机复验已能滚到并成功退出登录。
> ④ 顺手修了发布链两处**假红**（`check_phone_apk.py` / `publish_apk.py` 读 BuildConfig 时固定去主检出找，
> 于是 `--apk` 指向 `git worktree` 里打的包时会被判"连的是模拟器地址"而拒绝发布）——为避开另一会话未提交的
> 提示迁移，本轮真机包是在 `git worktree`（干净检出）里打的，打完已移除。
>
> **验收**：`_check_all.py` **57/57**（含另一会话新加的 hints 检查）· 红线 **1227 项** · `pytest -q` **690 passed** ·
> Android **991 用例 / 0 失败** · 反向验证：ai_batch 19/19、default_key 12/12、core_freeze 9/9、driver_money 19/19。
> **发布**：0.2.1（2026092103）→ 0.2.2（2026092104）→ **0.2.3（2026092105）**，短链 `http://8.145.40.22/apk`。


### [2026-09-21 22:xx →] 会话：**安卓模拟器安装白PP并登录司机账号**（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）· 第二轮

**用户需求（原话）**：
①「更改司机的配送规则…按固定工资的话他的卡片不显示任何的钱…**干脆以后就这样子搞：所有的司机都不显示
金钱是多少**，但是按单计费或者按提成的话依然会在**我的账单**里显示——也就是说他只有在我的账单里才能
看到这笔订单是多少钱，正常的订单是不会显示的」；
②「我们采一个核心的准则就是**核心的逻辑代码是不要乱动、核心是不要变**，其他的就以**插件的形式**——
能调方法调方法、能继承就继承、能调 API 就调 API」；
③「给 AI 搞一个捷径：他既可以**批量操作**一些功能和数据，又可以对**单个**进行调整…如果他只能单个调整，
他就要一个一个去调方法，这样也费 token」。
（追问后用户拍板：批量**不设条数上限**、范围由用户自己定；**一张卡列全部行、确认一次**；
核心区准则要**配一条机器判据**。）

**A. 司机端不显示金额（我）**
- 改 `ui/common/OrderCard.kt`（删掉司机分支的运费渲染）、`ui/order/OrderDetailScreen.kt`（删掉详情页司机运费块）
- 新增 `_tools/qa/_check_driver_money.py` + `_tools/qa/_reverse_verify_driver_money.py`
- ⛔ **不改**：钱的算法（`backend/app/services/driver_pay.py`、`order_money.py`）与后端司机视角门控
  （`order_response.py::apply_driver_view_gating` —— 它同时管着"按单计费司机能不能直接完成"那条流程，
  顺手删了会把流程改坏）；`ui/driver/DriverFreightScreen.kt`（我的账单，钱本来就该在这里显示）

**B. 核心冻结 + 插件式扩展（我）**
- 新增 `docs/CORE_AND_EXTENSION.md`（核心区清单 + 扩展点清单）、`_tools/qa/_core_files.txt`、
  `_tools/qa/_check_core_freeze.py`、`_tools/qa/_reverse_verify_core_freeze.py`
- 改 `AGENTS.md`（准则写进自动加载的入口）

**C. AI 批量捷径（我）**
- 新增 `ai/AiWriteBatch.kt`（**装饰器**：现有处理器一行不改）、
  `android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteBatchTest.kt`、
  `_tools/ai/_reverse_verify_ai_batch.py`
- 改 `ai/AiWrite.kt`（动作表加"可批量"标记 + 批量卡最后一行说真话）、
  `ai/AiWriteService.kt`（**唯一接线点**：handlers 外套一层 + 批量不挂单条撤回方案）、
  `ai/AiRolePrompt.kt`（规则：一次说要改多条时必须一次调用）、
  `_tools/ai/_check_ai_guardrails.py`（新增一节）+ AI 文档一节
- ⛔ **不改**：任何一个既有处理器（批量层只**调**它们）、`_write_coverage.py` 覆盖口径（没有新端点）

**明确不碰**：`backend/**`（这三条都不需要动后端）、`ui/dispatcher/*`、`ui/shipper/*`、`frontend/*`。

**本轮唯一的核心改动**（格式见 `docs/CORE_AND_EXTENSION.md`；判据 `_tools/qa/_check_core_freeze.py`）：

- 核心改动：android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt —— 为什么必须动核心：批量要对**所有**动作生效，而"动作 id → 处理器"那张表只在这个文件里建；接线只有两条路，一是把 50 多个处理器各改一遍（正是准则禁止的），二是建表之后**统一套一层装饰器**（本轮选它，多 3 行）。另外 `execute` 里那两处判断要认批量 payload：批量不挂撤回方案（`AiRevert.plan` 只认单条 payload），也不该报"没能挂上撤回"。

> **A/B/C ✅ 全部完成（2026-09-21 19:5x）**。落地的文件与上面那份清单**有两处偏差**：
> ① 批量**没有**做成"动作表加可批量标记"，而是**对所有动作统一可用**（少一张要维护的清单）；
> ② 也没有改 `ai/AiRolePrompt.kt` —— 那条规则放在了 `ai/AiAgentLoop.kt` 的提示词里
> （紧挨着原来那条"批量操作前名单必须当场重查"，两条本来就该在一起）。
>
> **验证**：`_check_all.py` **55/55**（新增 2 个检查）· 红线 `_check_ai_guardrails.py` **1207 项**
> （新增 §32 共 **39 项**，另按新位置改写 2 条旧锚点）· `pytest -q` **688 passed** ·
> Android **991 用例 / 0 失败**（973 → +18：批量单测 15 + 端到端 3）· 反向验证
> **ai_batch 19/19**、**core_freeze 9/9**、**driver_money 11/11**，另跑 `_reverse_verify_all.py --changed`
> **13/13 份全过**。
>
> **真机（模拟器）实跑**：
> ① **司机端不显示金额**：emulator-5558 司机登录后，已完成列表与订单详情**一个 ¥ 都没有**，
> 而库里这两张单是 `PIECE + freight_fee=62/92`（**改动前必然显示 ¥62.00 / ¥92.00**，
> 该司机名下这种单有 16 张）；同一账号的「我的账本」照旧显示 `合计 ¥44.00`、每单 `¥22.00`（计件/运费明细都在）。
> ② **AI 批量**：emulator-5554（deepseek-flash 真模型）说「把这两张单标成异常」→ 模型**只用了一次**
> 调用、弹**一张**卡：标题「标记异常」、摘要「**批量标记异常：2 条**」、逐条列 6 行明细、点一次确认 →
> 结果如实回报「✅ 已完成：批量标记异常：2 条 / **这一批 2 条：成功 2 条，全部成功。**」，
> 库里两张单 `is_exception=1`、`exception_reason='batch-e2e-test'`；随后用同样的方式「解除异常」
> 再跑一遍（**第二个动作也走通了批量**），库里已复原为 `is_exception=0`。
> ⚠️ 一处**已知限制（不是本轮引入的）**：三个 AVD 的 `hw.keyboard=no`，所以**宿主机键盘打不进中文**，
> 真机 E2E 的中文输入只能靠 `_emulator_say.ps1`（需要模拟器开「剪贴板共享」，本机没开）；
> 本轮改用 ASCII 指令（订单号是 ASCII）绕开，机制与语言无关。
> ⚠️ 本地库里那两张单的 `exception_reason` 还留着 `batch-e2e-test` 这行字（`is_exception` 已是 0），
> 属测试残留，下次重置本地库/灌数会一起清掉。


### [2026-09-21 12:2x →] 会话：**安卓模拟器安装白PP并登录司机账号**（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**用户需求（原话）**：「ai它要具备读取手机的地点的能力因为 ai它是要具备所有功能…包括用户不是我们要去
手动选地点吗？它也可以去选地点，这个权限给它开啊」＋「我们的版本号做一个正规化的处理」＋「我们那个线上
的数据做一个真实的处理就是做一个一堆的测试数据…大概是3到4个月的数据而且是每个月，每天每周都是不一样的
是数量是有多有少」。

**A. AI 读定位 + 按当前位置选点（我）**
- 新增 `ai/AiLocalReads.kt`（**本机读能力的唯一声明处**：`location.current` 等；复用机器生成的
  `ReadAction` 数据类，`path` 留空＝本机能力）＋ `ai/AiLocation.kt`（取一次定位 → 逆地理 → **只给地址文字**）
- 新增测试 `android/app/src/test/.../ai/AiLocalReadsTest.kt`
- 改 `ai/AiReads.kt`（本机能力并进 `forRole` / `describeForModel`）、`ai/AiReadService.kt`（本机能力的执行分支）、
  `ai/AiWriteService.kt`（把「当前位置」句柄解析成真实地址+坐标）、`ai/AiWrite.kt`（地址类动作参数说明）、
  `ai/AiContainer.kt`（注入定位提供者）
- ⛔ **不改**机器生成的 `ai/AiReadCatalog.kt` 与 `_tools/ai/_gen_ai_read_catalog.py`（本机能力没有后端端点，
  不进那份生成目录 —— 否则 `--check` 必红）；⛔ **模型全程仍然碰不到经纬度**（坐标只在 App 内部按句柄换）
- 红线：`_tools/ai/_check_ai_guardrails.py` 追加判据；`_tools/ai/_probe_read_roles.py` 排除本机能力

> **A ✅ 已完成**（子会话，2026-09-21 05:0x）。落地的文件与上面那份清单**基本一致**，两处偏差：
> ① 写侧没有走 `AiWriteService.prepare` 手改 payload，而是收在 **`AiWriteDataSource.resolveAddress`**
> 一处（三个地址入口——声明式 `geocodeFrom` 族 / 下单 / 改单——共用它，少一个入口就会把**字面量
> 「当前位置」**写进地址库且不报错）；② 反向验证另开了 **`_tools/ai/_reverse_verify_local_reads.py`**
> （9 条注入全红）。
> **验证**：`_check_all.py` **53/53** · 红线 `_check_ai_guardrails.py` **1163/1163**（新增 33 项，
> 段号 `== 2b-3.`、`== 2b-4.` 与工具那节的"读路径不许写盘"）· 单测 `AiLocalReadsTest` **24 例**
> ＋ `AiEnabledToolsTest` **6 例**（含"输出里没有坐标键/小数坐标串"、"句柄一次地理编码都不走"、
> "三种失败各给一句话且都不编地址"、"角色+模块两道门"、"老白名单补新模块的三条语义"、
> "连着读两次，第二次新工具还在"）· 全量单测 `testEmuDebugUnitTest` **973 用例 / 0 失败** ·
> `_gen_ai_read_catalog.py --check` 与 `_ai_doc_check.py` 绿 · `_write_coverage.py --check` 0 缺口 ·
> 反向验证 `_reverse_verify_local_reads.py` **11/11**。
>
> **同日返工（父会话验收后提的第 4 条）**：用户拍板「**这个权限给它开啊**」→ 老白名单必须自动补上
> 新模块，但**用户明确关掉的要记住是关**。做法与 `AiKeyStore.enabledTools` 那条"见过的清单"同源：
> 保存白名单时把**当时的全部模块**一起记下来（新键 `enabled_read_modules_known`），读的时候
> `saved ∪ (现在全集 − 保存时已知)`；标记缺失（旧数据）只补 `AiLocalReads.MODULES` 这一类。
> 合并规则收成纯函数 **`AiReads.resolveEnabled`**（`AiKeyStore` 那层只有 SharedPreferences，测不动）。
> ⚠️ 一处**刻意保守的偏差**：`saved` 为空时**不补**（老约定"空串 = 主动全关"；拿它当枚举去补
> 等于把用户关掉的又打开，而这次关的是**隐私**）。
> 敏感性实验（先证明测试抓得住）：把标记逻辑去掉 → 单测 `更新之后明确关掉手机定位，必须记住是关的`
> **当场红**（报"他关掉的又自己开了：[…]"），按字节还原即绿。
> ⚠️ 上面那条"顺带发现"**已在同一轮修掉**（父会话验收后提的第 ② 条）：用户原话
> 「ai 它是要具备**所有功能**」，而那个 bug 让新加的工具**只有第一次读是开的** ——
> 读的时候顺手 `markToolsSeen()` 把"见过的清单"刷成当前全集，第二次读就算出"没有新工具"，
> 于是它又变回关的（静默、不报错）＝ AI 悄悄丢能力。改法：合并规则收成纯函数
> **`AiKeyStore.resolveEnabledTools(saved, seenAtSave, role)`**（只读、可单测）；`enabledTools()`
> **只读不写**（两处 `markToolsSeen()` 与那个私有函数都删了）；"见过的清单"只在
> `saveEnabledTools` 保存时刷新（与 `saveEnabledReadModules` 同形）。
> 语义：没配过 → 按角色默认；`seenAtSave` 有值 → 补"保存之后新出现的"（该角色排除的除外）；
> **用户明确关掉的永远不自动开**。
> ⚠️ 与上面"空集不补"同源的**第三处保守偏差**：`seenAtSave == null`（旧数据：那份白名单存于
> "见过的清单"机制之前）时按"他都见过"算 —— 宁可暂时少给新工具（他进一次设置页保存就自愈），
> 也不把用户明确关掉的工具又打开（其中有能改数据的 `preview_write`）。
> 证据：单测 `AiEnabledToolsTest` **6 例**（含"连着读两次，第二次新工具还在"）＋红线 4 项
> （读路径不许写盘 / 合并规则是那处纯函数 / 读侧走它 / 旧数据按"他都见过"算）＋反向验证 **11/11**。
> ⚠️ **留给下一个人一条（与本轮无关，未改）**：`_probe_read_roles.py` 有 **1 条对不上** ——
> `return_requests.list_my_return_requests` 在**派单员**下「实际 200 / 目录声明不可用」。
> 原因是它挂在权限点 `ORDER_RETURN_REQUEST` 上，而 `rbac` 对派单员**一律放行**；目录的角色
> 推导给的是 `['shipper']`。属退货申请那条线，父会话已说**由他单独找用户拍板**（我本轮没动它）。

**B. 版本号正规化（我）**
- `VERSION`（产品版本唯一来源，现 0.2.0）、`android/app/build.gradle.kts`（versionName 取 VERSION；
  versionCode 保持日期式但**同日自动递增**）、`_tools/deploy/publish_apk.py`、`_tools/deploy/check_phone_apk.py`、
  `_tools/deploy/_check_update_flow.py`、`docs/APP_UPDATE_AND_RELEASE.md`

**C. 生产造数：3~4 个月真实感数据（我）**
- `backend/scripts/seed_demo_data.py`（现 90 天 → 3~4 个月；月/周/日数量要有起伏）

**明确不碰**：`ui/dispatcher/*`、`ui/common/*`、`ui/shipper/*`、`ui/driver/*`、`backend/app/*`
（本轮不需要动它们）。另一个会话（`session-faa17a77`）最后提交在 09:03，现在没在写。

### [2026-09-21 03:1x →] 会话：**全库「精简 + 优化 + 修 bug」专项**（DSH `session-faa17a77-515b-4bcb-bd47-fddae0129342`）

**用户需求（原话）**：「删除掉冗余代码或者说是精简代码还有在逻辑方面上，我们是否可以再精简一点，
但是不能让整个项目的整体逻辑发生根本性的改变，就是我们的逻辑是不能大致发生改变。尤其是核心的
业务逻辑以及账本的逻辑，它那个数字是不能出错的，还有一些退货呀，下单啊，一些都是还有消息。
然后你做一个全方面的优化以及修一下 bug」＋「你每做一次改动就提交一遍 git 方便如果你改错的话，
可以回溯版本」。（用户同时确认：**现在只有这一个会话在改这个仓库**。）

**回溯点**：`df5e733`（优化前把多会话累积的全部改动提交成基线快照）；**本轮每处改动各一个提交**。

**本轮自己加的三条纪律**：
1. **钱的算法与口径一个字节都不改** —— 账本 / 退货 / 下单 / 消息的**数字**是验收线，不是"大概对"；
2. 每处改动都要有**机器判据**跟着（红线断言 + 反向验证注入），并且**不许把断言改松**：
   收口之后如果锚点会假红，就把锚点改到**新位置**（更靠近行为），而不是删掉它；
3. 只做"证明得了"的精简，不做"看起来更优雅"的重写（用户：逻辑不能大致改变）。

⚠️ **踩坑（本轮实测，写下来给下一个人）**：`_reverse_verify_*.py` **被中途杀掉会把注入的 bug
留在源码里**（我一次前景运行超时被杀 → `services/place_service.py` 少了角色门槛；
下一次反向验证报「前提不成立」才暴露）。两条规矩：① 这类脚本要跑十几遍红线，单份 3~5 分钟，
**给足超时或放后台**；② 跑完**必须 `git status` 看一眼**再动别的。

| 我改的 | 内容 |
| --- | --- |
| `backend/app/services/category_order.py`（新）| 四个名册共用的「整份顺序」校验 `ordered_ids`（去重/存在/完整三条判据 + 三段中文报错）|
| `backend/app/api/v1/{expense,freight,place,product}_categories.py` | 各自那份 13 行校验副本删掉，改调 `ordered_ids`（**4 份 → 1 份**）|
| `_tools/qa/_check_expense_page.py`、`_tools/ai/_check_ai_guardrails.py §31` | 锚点跟着搬：从"这个文件里有那句文案"改成"**端点真的调用了共用校验** + 判据在那份共用文件里"（老写法在收口之后会**假红**，而假红会被下一个人改成更松的写法）|
| `_tools/qa/_reverse_verify_expense_page.py` | 新增 2 条注入（端点不走共用校验 / 共用校验里「少传了也要拒绝」被删）→ 15/15 |
| `_tools/qa/_reverse_verify_catalog_and_scope.py` | 注入点搬到共用文件 + 新增 1 条；**顺手修掉一条早就过期的注入**（`OneShotSnackbar` 那条替换串早就不匹配源码，等于那一项一直没被证明过）→ 25/25 |
| `_tools/qa/_scan_dup.py`（新，**报告工具**，不进 `_check_all`）| 跨文件重复块扫描（滑窗指纹 + 相邻窗口合并）。为什么要它：`_check_dead_code.py` 只看"没用的 import / 没人调的私有声明"，看不见"同一段逻辑在 4 个文件里各抄一遍"。⛔ 它**不做红线**：重复是一条连续谱，做成红线只会得到一条"永远红"的检查（＝没有检查）；用法是**精简前后各跑一次看组数**（当前基线：**33 组**）|

### 第二轮：修掉退货金额「同一笔钱两个数」（差 1 分）

**这是本轮唯一有可复现数值证据的钱的缺陷**（`order_products.unit_price` 是 `Numeric(14,4)`，
拆单会算出四位单价，所以不是理论值）：

| 用在哪 | 原规则 | 两行各 `12.3456 × 1` |
| --- | --- | --- |
| `ReturnResult.returned_amount`（→ 退现 → 响应体 → 站内信） | 按行先取**两位**再求和 | **24.70** |
| `ledgers(source=RETURN).total`（账本红冲） | 按行落**四位**，汇总再取两位 | **24.69** |

两个数印在**同一个** `POST /orders/{id}/return` 的响应体里（`returned_amount` 与
`order.returned_amount`），而退现（真金白银）按 24.70 付出去、账上只红冲 24.69 —— **两边都不报错**。

| 我改的 | 内容 |
| --- | --- |
| `services/order_return.py` | 新增 `_line_amount`（**这一行的退货货值只算一处**：按行落四位）；`_reversal_row` 改成**收调用方传进来的那个数**、不再自己算一遍；`returned_amount = _q2(returned_raw)` —— **到分只在"整次退货"这一层做一次**。账本的存储值（4 位）与历史数据**一个字节没动**，改的是"另外那份算法" |
| `backend/tests/test_order_return.py` | 新增 `test_return_amount_is_one_number_even_with_four_decimal_prices`：四位单价 + 派单勾了收现金 → 断言 **本次退货金额 = 累计已退（账本出的）= 退现 = 现金流水**，并先把"账本红冲确实是 24.6912"当**前提**钉住 |
| **敏感性实验** | 把 `returned_raw += line_amount` 注入回旧规则（`_q2(line_amount)`）→ 那条测试**当场红**，报 `assert Decimal('24.70') == Decimal('24.69')`；还原即绿。**先证明测试抓得住这个 bug，再说修好了** |
| `_tools/qa/_check_order_return.py` | 新增 6 条判据（只算一处 / 红冲行用传进来的数 / 不许 `_q2(line_amount)` / 到分只做一次 / 红冲行里不许出现第二种货值算法）；**98 项 → 104 项** |
| `_tools/qa/_reverse_verify_order_return.py` | 新增 2 条注入（改回按行取两位、红冲行绕开传入值自己算）＋修掉 2 处因改名而过期的替换串 → **25 条注入全部报红** |

**验证**：`_check_all.py` **54/54** · `cd backend && pytest -q` **672 passed**（含新增那条）· `_reverse_verify_order_return.py` **25/25** · 账本存储值未变（`ledgers` 仍是 4 位列、原位）。

### 第三轮：删掉后端死代码（2 个整文件 + 15 个符号 + 3 个关系）

每条都**自己数过引用数**（全仓词边界计数 = 1 即"只有定义那一行"），不是凭命名猜的：

| 删掉的 | 计数 | 为什么它不该留 |
| --- | --- | --- |
| `core/ws_hub.py`（整文件）| 零导入 | 4 份文档早就把它标成死代码；留着会被下一个人当成"现成的 WebSocket 层" |
| `services/cancelled_order_retention.py`（整文件）| 零导入 | L18 的 10 天常量与现行 **30 天**策略**冲突**（照它答会答错）。⚠️ 生产服务器早已被 `_test_tools/patch_server2.py` 换成 `data_retention`，删它不会断线上 |
| `reports.py::_xlsx_sheet` | 1 | 导出四条分支各写一遍 `ws.append`，这个"公共小助手"从没接线 |
| `order_money.py::OrderMoney.net_collected` | 1 | 四个消费点都直接用 `m.settled/m.refunded` |
| `shipper_settle.py::settled_order_map` / `order_settle_state` | 各 1 | 真正在用的是 `settled_line_map` + `lines_of_order` |
| `accounting_service.py::business_month_now` / `customer_display_name` | 各 1 | 前者 docstring 说"挡住未来的月份"——全仓**没有**这条判据（真的挡在别处）；后者名字口径的入口是 `resolve_customer_for_order` |
| `cost_history.py::SOURCE_BACKFILL` | 1 | 真正的回填写的是 `schema_bootstrap` 里的 SQL 字面量 `'BACKFILL'` |
| `message_center.py::publish_order_cancelled` | 1 | 已被 `publish_order_cancelled_multi` 取代 |
| `place_service.py::RULE_TEXT` | 1 | 注释写"界面/提示词要用同一句"，而这句话在 android/frontend **一次都没出现** |
| `schemas/auth.py::TokenPayload`、`accounting_v2.py::ReceiptItem`、`inventory.py::InventorySummaryOut` | 各 1 | 都不是出参模型（`/inventory/summary` 返回裸 `list[dict]`）|
| `models/export_job.py` 的 `creator` **与 `shipper`**（两个关系）| 各 1 | 代码里只用 `created_by_id`/`shipper_id`。⚠️ 子代理只报了 `creator`，`shipper` 是我复核时补的（**清单要自己再验一遍**）|
| `models/freight_template.py::creator` | 1 | 同上 |
| 随之无用的 import（`relationship` / `TYPE_CHECKING` / `User`）| — | 删完才看得见 |

**收成一处（不是删）**：`schemas/text.py` 自称"文本长度上限的唯一定义处"，可 `MAX_NOTE` 在
`schemas/return_request.py` 里又写了一个 256、`MAX_REASON` 从没人用（`order.py` 硬编码 1024）——
现在 `return_request` **导入**它、`OrderRecallBody` **用它**（**数值不变**，行为一个字节没改）。

**文档跟着改**（过期地图比没有地图更糟）：`01_ARCHITECTURE.md`、`02_BACKEND_API.md`、
`03_BACKEND_DETAILS.md`、`08_CODE_LOCATOR.md` 里 6 处"某某是死代码"改成"已删除"；
其中 `08_CODE_LOCATOR.md` 那条「`orders.py` L546 `delete_order` 是不可达的重复路由」
**本来就是过期的**（今天 `@router.delete` 只有 L466 一处，`delete_order` 这个名字全后端已不存在）——一并改对。

**验证**：`_check_all.py` **54/54** · `pytest -q` **672 passed** · `08A_ENDPOINT_INDEX.md` 重新生成（行号跟着 `reports.py` 的删除对齐）。

### 第四轮：删掉 Android 死代码（3 个整文件 498 行 + 2 条到不了的路由）

判据同样是**自己数的引用数**（`android/app/src` 含测试全扫，0 命中才算死）：

| 删掉的 | 证据 |
| --- | --- |
| `ui/dispatcher/ReportScreens.kt`（333 行）| 零引用。它是 `ReportCenter.kt`（NavGraph 真正在用）的**旧平行实现** |
| `ui/dispatcher/ReportViewModels.kt`（119 行）| 零引用 —— ⚠️ 它是**被上一条牵出来的**：`ReportScreens` 是它唯一的使用者（`ReportViewModel` + 营业额/商品/司机/异常四个子类整套作废）|
| `ui/common/PlaceholderScreen.kt`（46 行）| 零引用（连一句注释/文档都没提它）|
| `Routes.PROFILE` + NavGraph 里那个 composable | `Routes.PROFILE` 只出现 1 次＝它自己的注册；「我的」Tab 是 `RoleHomeScreen` **内嵌** `ProfileScreen(embedded=true)`，没有任何 `navigate(Routes.PROFILE)` |
| `Routes.DISPATCH_POOL` + 对应 composable | 同上：派单首 Tab 是内嵌的 `DispatcherPoolScreen(embedded=true)` |
| 随之孤儿化的 2 个 import（`ProfileScreen` / `DispatcherPoolScreen`）| 删完才看得见 |
| `_tools/qa/_check_input_rules.py` 里那条指向 `ReportScreens.kt` 的豁免 | 它断言"豁免键必须命中真实存在的输入框（防化石）"——文件没了，条目必须同删 |

⛔ **明确不删（这是本轮最重要的判断）**：`Routes.DISPATCH_SETTLEMENTS` + `SettlementsScreen` + `SettlementsViewModel`。
它**确实点不到**（工作台那格「司机运费结算」指的是 `Routes.FREIGHT_SETTLEMENT`，另一页），但它是
**全 UI 里唯一能「新建结算单 / 确认 / 付款 / 作废」的页面** —— 今天这四个动作**只有 AI 助手做得到**
（`AiWriteSettlementHandlers` → `repo.createSettlement/settlementAction`）。
按"引用数 0 就删"的机械判据删掉它，等于**把一个人点不到的能力彻底删掉**，
而不是清理冗余。这是产品决策（补入口 vs 认定只由 AI 做），已列给用户拍板。

**验证**：`:app:compileEmuDebugKotlin` **BUILD SUCCESSFUL** · `:app:testEmuDebugUnitTest` **913 项 / 0 失败 / 2 跳过**（与删除前一致＝这些文件确实没有任何测试依赖）· 装到 emulator-5556 并启动 smoke：`topResumedActivity=com.tapmoay.sorders/.MainActivity`、无崩溃日志 · `_check_all.py` **54/54**。

### 第五轮：把「永远绿的检查」清出必跑清单 + 补一条真能红的判据

**发现**：`54/54 全绿`这句话里有**虚格**。判据＝脚本里有没有一条非零退出的路径
（`return 1` / `sys.exit(1...)` / `raise SystemExit`）：

- 第一遍粗筛点名 9 个，**逐个复核后 4 个是我误判**（`return 1 if args.check else 0`、
  `sys.exit(1 if bad else 0)`、`return rep.finish()` 这些写法我的正则漏了 ——
  **误判比漏判更贵**：它会让人去"修"一个本来正确的检查，所以每条都读了源码才下结论）；
- **真虚格 = 5 个**：`_check_toolmap_vs_08a.py`、`_check_toolmap.py`、`_check_read_surface.py`、
  `_check_ui_strings.py`、`_check_existing_generator.py`。它们都是**一次性探查报告**
  （打印结论后 `return 0`），被 `_check_` 前缀骗进了必跑清单。

| 我改的 | 内容 |
| --- | --- |
| 5 个脚本 `git mv` 成 `_report_*.py` | 名字说实话 → `_check_all.py` 的清单自己算，立刻从 **54 → 49**（覆盖面一点没少：这 5 个本来就不会红）。每个文件的 docstring 里写明**这是报告不是检查**、判据其实在哪、`⛔ 不要改回 _check_*`（否则下一轮又有人为了"提高覆盖率"把它改回去） |
| `docs/AI_ASSISTANT_PLAN_V3.md` | 4 处引用跟着改名 |
| **`_tools/qa/_check_endpoint_index_fresh.py`（新，真能红）** | 补的那一格：`docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` **是不是过期地图** |
| `_tools/qa/_reverse_verify_endpoint_index.py`（新） | 2 条注入（行号改错 / 少一个端点行）→ 都报红 + 字节级还原检查 |

**为什么补的是这一条**（不是随便挑的）：实测把索引里一处行号故意改成 `999`，**49/49 照样全绿** ——
也就是"端点地图过期"这件事**当时没有任何检查在看**。而本轮我自己就撞过一次：
给四个分类端点各删十几行后，索引里 **53 处行号立刻过期**，只有靠记得 AGENTS.md 那句话才发现它。
判据不重写比对逻辑：这份文档的唯一作者 `backend/scripts/gen_endpoint_index.py` 自己就有 `--check`，
这一条只负责把它跑起来、**把退出码原样传出去**。

⚠️ **又踩一个坑并修掉**：反向验证脚本用 `read_text/write_text` 会做换行转换（LF↔CRLF），
跑一遍就把整份文档的换行翻掉 —— 内容"还原了"，`git status` 里却多出一个整文件改动。
新脚本一律**按字节读写**（`read_bytes/write_bytes`），并把"逐字节一致"写成还原判据。

**验证**：`_check_all.py` **50/50**（49 个原有 + 这一条新的）· `_reverse_verify_endpoint_index.py` **2/2 注入报红 + 还原逐字节一致** · 故意改坏索引 → 新判据**当场红**（改回即绿）。

### 第六轮：修两个用户可见的真 bug（都是"界面上说不清"的那一类）

| bug | 后果 | 修法 |
| --- | --- | --- |
| `ui/common/OrderPeek.kt::orderStatusLabel` **少了「已退货」那一档** | 账本展开行把**原始码 `RETURNED`** 直接印给用户（与 2026-09-20 状态徽章漏它同一类，那边补过并写明理由，这一处漏了） | 补一档 + **判据从 `OrderStatusModel.ALL` 逐档核对**（不手写 6 个状态名 —— 当初漏它正是因为没人算过总数；以后后端加状态、客户端忘补中文名也会被点名） |
| `ui/ai/AiSettingsViewModel.recheckThinkingSupport()` 只清了「不支持 thinking」的记忆 | 用户换到一个**支持** `stream_options` 的地址、点了「换地址后重新检测」，App 仍然**永远跳过** `stream_options`：拿不到服务端的 token 用量（上下文压缩只能改用本机估算），而界面上**没有一个字**解释为什么。`AiKeyStore.clearStreamOptionsUnsupported` 一直存在、KDoc 也写着"与 clearThinkingUnsupported 一起用于设置页的重新检测"—— 就是没人调它 | 两种能力记忆一起清 |

**验证**：`_check_order_return.py` **104 → 106 项** · `_reverse_verify_order_return.py` **26/26 条注入报红**（含新增的"删掉 OrderPeek 里那一档"）+ 11 个被碰文件**逐字节还原** · Android `assembleEmuDebug` + **913 单测 0 失败** · 装到 emulator-5556 启动 smoke 通过、无崩溃 · `_check_all.py` **50/50**。

⚠️ **诚实记一笔：第二个修复没有机器判据，原因与原因。** 原因：AI 设置页那一节（`_check_ai_guardrails.py §13`）目前没有反向验证宿主，而 `AiKeyStore` 走 Android `Context`、纯 JVM 单测打不进去。它现在只靠代码注释与这一行记录守着。下一轮二选一：
① 给 §13 建一份 `_reverse_verify_ai_settings.py`；② 做成通用判据「`AiKeyStore` 里每个"清能力记忆"的方法都必须被『重新检测』调用」（这条还能顺手抓住以后新增的同类半接线）。
> ✅ **2026-09-21 已补上（第十轮）**：走了①——`_tools/ai/_reverse_verify_ai_settings.py`（3 条注入全报红），
> 并在 §13 加了 2 条判据钉住"两种能力记忆一起清"。②那条通用判据没做（理由见第十轮）。

⚠️ **同一族的另一半（待你拍板，不是 bug 修复）**：`LlmClient.STREAM_OPTIONS_UNSUPPORTED_NOTE`（"当前地址不接受 stream_options，已自动跳过，不影响回答"）**至今没接到界面上** —— 也就是说用户确实会看到"拿不到服务端用量"这个现象，但 App 不会解释。要不要在设置页给一段解释，是产品决定。

### 第七轮：合并三处重复实现（都是"各写一遍、谁都不会报错"的那一类）

| 收口 | 原来 | 收成 |
| --- | --- | --- |
| `api/v1/ledger.py::_apply_date_window` | `GET /ledger/entries` 与 `GET /ledger/accounts` **各抄一遍**同样的日期窗口（含两句中文报错，共 24 行） | 一处 + 两行调用。⚠️ 注释里写死**不许**换成 `deps.parse_date_range`：它返回 `datetime`，而这里比的是 `Date` 列，带时间的那一端会让闭区间悄悄变半开 |
| `api/v1/orders.py::_reject_if_already_collected` | 内联重抄了一遍 "这张单收过钱没有" 的两条判据（`paid` + inbound 流水） | 改调 `_already_collected`。⚠️ `_already_collected` 的 docstring 一直写着"判据与 `[_reject_if_already_collected]` 同一套"——**注释在承诺一件代码没保证的事**：谁哪天改了 `paid` 与流水的取舍，另一边不会跟着动，而两边都不报错。现在这句话成真了 |
| `services/order_return.py` | 自己定义了一份 `_q2`（与 `order_money.q2` 逐字相同）——**全项目第 5 份"两位小数 + ROUND_HALF_UP"** | 删掉，改用 `order_money.q2`（它本来就是"全项目统一两位小数"的归属处）。红线锚点与 2 条注入跟着改（`_q2(` → `q2(`），**没有改松** |

**验证**：`pytest -q` **672 passed** · `_check_all.py` **50/50** · `_reverse_verify_order_return.py` **26/26 报红 + 11 个被碰文件逐字节还原** · 钱的对账与开工前**逐项一致**（`_fuzz_invariants` 39 项 / 确认缺陷 0 / 可疑 4 / 信息 1）。

✅ **上一轮加的那条判据当场证明了自己**：这一轮我改完后端没重跑索引，`_check_endpoint_index_fresh.py` **立刻报红**（"端点索引已经过期"）——以前这件事没有任何检查在看（这一轮开工前的实测：把行号改成 999 也全绿）。重新生成后 50/50。

### 第八轮：删掉一个"KDoc 承诺了、而从来没做过"的入口（`HintPrefs.resetAll`）

`core/HintPrefs.kt::resetAll()` 的 KDoc 写着「全部归零（**设置页那个「重置界面提示」**）」，
而那个入口**从来没有做过**：全仓搜 `resetAll` 只有它自己那一行声明，`ProfileScreen` 的「界面提示」块里
只有一个「一直显示」开关。也就是一句"给用户看的说明"承诺了一个不存在的按钮。

**为什么删方法而不是补按钮**：补按钮是**加一个功能**（要不要给用户一个"重置界面提示"的入口是你的决定，
已列进待拍板）；而这一轮的目标是精简。删掉之后"想再看一遍那几句话"仍有两条路：
① 上面的「一直显示」开关；② 清 App 数据（会连登录态一起丢）。原地留了一段注释写清来龙去脉，
并写明**要补就补在 `ProfileScreen` 的「界面提示」块里，别只把方法加回来**。

⚠️ 顺手记一个**检查的盲区**：这件事**没有任何检查会红** —— `_check_dead_code.py` 只查
「文件内没人用的 import / **private** 声明」，而 `resetAll` 是 public（它当时正是为了让别的文件能调才 public）。
"跨文件没人用的 public 声明"这一类（本轮与上一轮一共抓到 5 处半接线）目前**只能靠人读**。

**验证**：`:app:compileEmuDebugKotlin` + `:app:testEmuDebugUnitTest` **BUILD SUCCESSFUL** · 装到 emulator-5556 启动 smoke 通过（`topResumedActivity=MainActivity`、无 FATAL）· `_check_all.py` **50/50**。

### 第九轮：把 fuzz 审计里 4 条**永远在喊"可疑"**的判据说明白（可疑 4 → 0，信息 5）

`_tools/fuzz/_fuzz_invariants.py` 长期打印 `可疑 4`：那 4 条判据的 `total_sql` 扫 0 行，
而工具的口径是"**扫了 0 行 = 可疑**"（这条口径本身救过命：5 条订单状态判据写成小写、
库里是大写，于是永远扫 0 行、永远报绿，改对大小写后立刻命中真缺陷）。
问题是本机库长期没有"已确认/已付款的结算单"，于是**输出永远脏着，人就不看了** ——
这正是"永远红的检查＝没有检查"的镜像。

| 我改的 | 内容 |
| --- | --- |
| `_tools/fuzz/_fuzz_invariants.py::_idle_reason`（新） | 把"0 行"分成两种：**能证明是本机没有这类数据** → 信息（并把**库里该列的真实取值**打出来，人一眼能看出是"没数据"还是"字面量写错"）；否则 → 可疑。⛔ 判据是**fail-closed**：SQL 形状认不出、列名不合法、表不存在、字面量**大小写不敏感地命中**任一真实取值 —— 全都返回 None（继续按可疑报）。最后一条正是当年那个坑的形状，**必须**保持告警 |
| `_tools/fuzz/_reverse_verify_fuzz_safety.py` | 新增第 ④ 条轨：**直接测分辨判据的契约**（三个方向：命中真实取值不放行 / 库里没有则说明原因并打出真实取值 / 认不出的形状不放行）。⚠️ 为什么不用注入：注入口只能选在"本机真实存在"的判据上，而本机 5 条空转判据**全都是"数据确实没有"那一类**，没有一条能用来证明"该可疑" |

**结果**：`可疑 4 → 0`、`信息 1 → 5`，每条空转判据都自己说清"库里 `driver_settlements.status` 的真实取值是 `['draft']`"。
**验证**：`_reverse_verify_fuzz_safety.py` **8 项全过**（4 条注入 + 前提 + 3 个方向）· `_check_all.py` **50/50** · 钱的对账仍是 `39 项 / 确认缺陷 0`（**可疑 0**）。

### 第十轮：给 AI 设置页那一节补反向验证宿主（还上一轮欠的那笔）

第一轮修的那个缺陷（「换地址后重新检测」只清了 thinking 记忆、`clearStreamOptionsUnsupported` 从没人调）
当时**没有机器判据**，我在声明页里如实写了"下一轮补"。这一轮补上：

| 我改的 | 内容 |
| --- | --- |
| `_check_ai_guardrails.py §13` | 新增 2 条判据：①「换地址后重新检测」把**两种**能力记忆一起清（正则要求两行相邻出现，少一行就红）；②被清的那个方法真的存在（防止判据锚一个凭空写的符号） |
| `_tools/ai/_reverse_verify_ai_settings.py`（新） | **§13 原来没有反向验证宿主**（其它 `_reverse_verify_*.py` 各盯各自的节）——这也是那个缺陷能长期存在的间接原因。3 条注入：只清 thinking / 只清 stream_options / 把两句都删掉（按钮还在、点了什么都不做）→ 全部证明会让 §13 报红 |

⚠️ **又踩一次换行坑（已写进脚本注释）**：`AiSettingsViewModel.kt` 是 **CRLF**，按 `\n` 写替换串时
注入**静默失效**（三条注入全报"替换串过期了"，其实是换行对不上）。现在脚本按字节读写 + 记住文件的换行风格，
并把"逐字节一致"写成还原判据。

⛔ **没做的那个备选（②"通用判据：每个清能力记忆的方法都必须被调用"）**：它属于"跨文件没人用的 public 声明"
这一类，而这类判据的误报面很大（本轮已知的同类：`AiActor`、若干 `data class` 的字段类型、
以及 Compose 里靠约定使用的声明）——**一条误报多的检查会让人开始无视整个清单**。宁可用"逐个域配宿主"
的办法（本轮 §13），也不做一条会吵的通用判据。这条判断写在这里，免得下一轮有人重开。

**验证**：`_reverse_verify_ai_settings.py` **3/3 注入报红 + 逐字节还原** · `_check_ai_guardrails.py` **1102 项全过** · `_check_all.py` **50/50**。

**顺手修掉一句与后端相反的用户提示**（H5 `OrderDetailBody.vue`）：删除确认框写的是
「**删除后不可恢复**」，而后端 `DELETE /orders/{id}` 是**软删除**（`data_retention.py::SOFT_DELETE_RETENTION_DAYS = 30`：
进隔离区 30 天、用户不可见、**派单员可查可恢复**，到期才物理清理）。按"不可恢复"说，
用户会以为删掉就没了 —— 与数据保留策略当场打架。改成「删除后订单进入回收站（30 天内可由派单员恢复）」。

### 第十一轮：把「时间药丸的两个弹层」收成一份（全库最大的一块重复）

**原来**：派单账本 / 货主账本 / 司机任务 / 司机运费 / 开销——**五个页面各写一遍**同样的两段
（`if (showDatePresets) { DatePresetDialog(…) }` ＋ `if (showCustomRange) { DateRangeDialog(…) }`），
共约 130 行。里面藏着一条最容易写错的规矩：**选中「自定义」要"先关档位清单、再开日期弹层"**
（漏了或反了，表现是"点了自定义什么都没发生"，而只有用户点得到才发现）。五份副本＝这条规矩要改五次。

| 我改的 | 内容 |
| --- | --- |
| `ui/common/Components.kt::DateFilterDialogs`（新） | 两个弹层 **＋ 它们的状态机**：调用方只给「药丸开没开」，第二层（自定义区间）的开关由它自己持有。⚠️ 第一个开关**仍然留在调用方**——账本页那份状态在 ViewModel 里、换档要联动重新查询，替它持有会把那条链切断（注释里写了） |
| 五个页面 | 各删掉那两段（含自己的 `showCustomRange`），换成一次 `DateFilterDialogs(…)` 调用；`ExpensesScreen` 的 VM 里那个 `showCustomRange` 也删了，原地留注释说明"再想加回来先看那个函数" |
| `_check_ledger_dashboard.py` / `_check_expense_page.py` | 锚点跟着搬到新位置，并**加了行为判据**（不放松）：页面必须真的调 `DateFilterDialogs(`；host 里确实开着档位清单；**「自定义」那一档必须接着开区间弹层**（这条是原来五份副本里最容易写错的） |
| 两份反向验证 | 各加注入：页面不再走 host（又抄一遍）/ host 里两个弹层被拿走 / **host 里「自定义」不再开区间弹层** |

**顺手修掉 3 条「从未被证明过」的判据**：`_reverse_verify_ledger_dashboard.py` 报 **30/33** ——
3 条注入的替换串早就对不上源码（静默 SKIP），也就是说
`_check_ledger_dashboard.py` 里「共享阶梯」「不许抢方向盘」这几条断言**一直没有敏感度证据**。
按当前源码把 3 条注入全部重写 → **33/33**。（与第一轮修的 `OneShotSnackbar` 那条同一种病：
**注入锚点会腐烂，而腐烂时它只是安静地跳过**。）

**验证**：`_check_all.py` **50/50** · `_reverse_verify_ledger_dashboard.py` **33/33** · `_reverse_verify_expense_page.py` **17/17** · Android `assembleEmuDebug` + **913 单测 0 失败** · **真机走了一遍**（emulator-5556：工作台 → 账本管理 → 开销管理 → 点时间药丸 → 档位清单 11 档全在 → 点「自定义」→ **区间弹层真的打开了**，截图 `_archive/ui-01-datefilter-custom.png`）· 钱的对账 `39 项 / 确认缺陷 0 / 可疑 0`。

### 第十二轮：修掉 4 处「注入在空转」+ 给"锚点腐烂"配一把廉价的尺

**起因**：上一轮顺手撞见 4 条反向验证的注入替换串早对不上源码（静默 SKIP），于是这一轮先想跑一遍
`_reverse_verify_all.py` 把全部量清 —— **跑到 50 分钟还没完，被我杀掉**。杀它留下三样东西，
每一样都值得写进交接（**这就是"跑反向验证"这件事的真实代价**）：

| 杀掉的后果 | 现场 | 复原办法 |
| --- | --- | --- |
| ① 注入没还原 | 4 个文件带着注入（`AiRolePrompt.kt`/`AiWriteBasicData.kt`/`accounting_service.py`/`ai_read_catalog.json`）| `git status` 一眼看出 → `git checkout --` 还原 |
| ② **注入锁没释放** | `%TEMP%\dsh_reverse_verify.lock` 还在 → **接下来所有检查都拒绝出结论**（"源码是注入状态"），最长卡 30 分钟 | 删掉那个锁文件（或等 30 分钟自动失效） |
| ③ 快照留在临时目录 | `%TEMP%\dsh_rv_snapshot`（**开跑前**的状态）| ⚠️ **不要**直接跑 `_recover_injections.py` 还原：它会按快照写回，把**开跑之后**的改动一起抹掉（本轮就差点抹掉红线自己）。真实状态在 git 里 → **删快照 + 清锁**即可 |

**改进**：`_tools/ai/_recover_injections.py` 现在在"确实发现遗留现场"那条路径上**顺手清锁**
（判据写在注释里：只在发现遗留快照时清，免得误删正在跑的那一次的锁）。

**新增的廉价尺**：`_tools/qa/_scan_stale_anchors.py`（报告工具，不进 `_check_all`，秒级只读）——
用 AST 解出 65 份反向验证里的**注入锚点**（266 个，能核对 247 个），拿去目标文件里核对还在不在；
正则锚点用 `re.search` 判、字面量锚点用 `in` 判（第一版把正则当字面量，会淹掉真问题）。
覆盖不到 150 个时会**主动声明"说服力不足"**（反空转）。

**它一次就抓出 3 处腐烂**（都在别的会话留下的脚本里），逐条修好：

| 脚本 | 腐烂的锚点 | 修法 |
| --- | --- | --- |
| `_reverse_verify_billing.py` | `rate = money(rate_override) … else rule.commission_rate` | 兜底值后来改成了 `base_rate` → 锚点跟进，注入原意（丢掉逐单覆盖）不变 |
| `_reverse_verify_product_guards.py` | `if o.paid:` | 守卫长成 `if o.paid or m.arrears <= 0:` → **只摘掉 `o.paid` 那一半**（整句换成 `if False` 会把"欠款为 0 不许再收"一起放开，那验的就不是这一条了）|
| `_reverse_verify_soft_delete.py` | `.replace("    is_deleted:", …)` | 那一行**在目标文件里根本不存在**（三个模型是 `SoftDeleteMixin` 混入式声明）→ 删掉这句永远不生效的替换 |

**顺带挖出一条"看起来有牙、其实恒绿"的断言**：`_reverse_verify_billing.py` 现在能跑了，报
「校验放行『拿这一单的钱 + 按运费抽成』：注入后 §22 没有报红」。根因不是锚点，而是
`_check_ai_guardrails.py:2937` 那条锚的是**裸子串** `不能同时配` —— 而这句话在**两条**报错里都有
（「…与「按分类定价」不能同时配」/「…和「按运费抽成」不能同时配」），删掉后者它照样被前者满足。
改成两条各钉各的后半句（`（那等于拿 100% 再加提成）` / `（前者本来就逐单不同）`）→
`_reverse_verify_billing.py` **16/16 全过**。
（与 `_check_order_return.py` 里 `ORDER_RETURN\b` 那次同源：**裸子串会被兄弟文案满足**。）

**验证**：`_check_all.py` **50/50** · `_check_ai_guardrails.py` **1103 项** · `_reverse_verify_billing` **16/16** ·
`_reverse_verify_product_guards` **13/13** · `_reverse_verify_soft_delete` **5/5** ·
`_scan_stale_anchors.py` 复跑 **0 处腐烂** · 钱的对账 `39 项 / 确认缺陷 0 / 可疑 0`。

### 第十三轮：让反向验证**能只跑受影响的域**（上一轮那个"没人跑得动"的根因）

上一轮的结论是：全套反向验证 **50 分钟以上**、而且跑的时候**一个字都不能改源码** ——
所以没人会跑它，于是注入锚点腐烂（对不上源码就静默跳过）会攒到几十条才发现。
这一轮给 `_reverse_verify_all.py` 补一条窄路：

| 新参数 | 作用 |
| --- | --- |
| `--list` | 只列会跑哪些（不跑、不注入、不上锁） |
| `--only <域>` | 只跑路径含这个子串的（`ai` / `qa` / `notify` / `fuzz`）|
| `--for <文件…>` | 只跑「**注入目标涉及这些文件**」的 |
| `--changed` | 同上，但改动清单**由 git 现算**（含未跟踪文件）|

判据是**从脚本源码里找目标路径字面量**（那些脚本本来就是靠字面量改文件的，它自己就写着目标路径），
不用另外维护一张映射表。两个防呆：

- ⚠️ `git` 必须带 `-c core.quotepath=false`：不然中文路径会被转义成 `"\346\226\207…"`，
  与脚本里写的路径对不上，`--changed` 会**安静地选中 0 个**（那种失败最难发现）；
- 选中 0 个时：`--changed` 是**合法答案**（改的是文档/新文件）→ 打一行说明后通过；
  `--only/--for` 是**拼错了** → 非零退出。这两种情况必须分开，否则人会去找一个不存在的错。

顺手加：每份脚本跑完打**耗时**（全量时一眼看出是哪几份在拖）。

**验证**：`--list` → 65 份；`--for backend/app/services/order_return.py` → 正好 1 份，
**真跑 5.1s、26/26 注入全红**，跑完工作区干净（快照还原顺手把那处 CRLF 噪音也修好了）。
`--changed`（改动只有这个工具自己）→ 打「本次改动没有涉及任何反向验证的注入目标」并通过。

**同时把 `AGENTS.md` 里那三行过期说明改对**（原来写「34 个脚本 / 48 份反向验证 / 几分钟」，
实际是 50 个检查、66 份反向验证、**50 分钟以上**），并补上：子集模式的用法、
以及「**别硬杀它**」的三样后果（注入残留 / 注入锁没释放 → 所有检查拒绝出结论最长 30 分钟 /
开跑前的快照不能直接还原 —— 会抹掉开跑后的改动）。

### 第十四轮：把上一轮那把尺的**盲区**堵上，又抓出并修好 4 处腐烂 + 1 条恒绿断言

上一轮新增的 `_scan_stale_anchors.py` 一开始只解析出 **266 个锚点**、还报"0 处腐烂"。
这一轮先问了一句"**这尺自己量到了多少**"（仓库的老规矩：反空转），结果三处都是它自己的毛病：

| 尺的病 | 症状 | 修法 |
| --- | --- | --- |
| 丢了**最简单**的锚点形状 | `(说明, 路径, "旧串", "新串", 期望)` 这种直接写字符串的元组没被认 | 第 3 项先按字符串取，再退回注入表达式 |
| 路径常量只认**单层** | 脚本里常是 `SCREEN = ANDROID / "…"` 而 `ANDROID = ROOT / "…"` → 解析不出目标 | 改成**迭代到不动点**的解析 |
| 把 Kotlin 的 `\|\|` 当正则交替 | `if (personKey == null \|\| tab == 1) return` **逐字存在**却被报成"腐烂" | 判据不能收 `\|`；且正则锚点失败时**再按字面量试一次**（两种都试，防假阳性）|

**误报比漏报更贵**（它会让人去"修"一个本来正确的注入）——所以第三条我改了两次才定下来。
修完覆盖率 **266 → 494 个锚点**，真腐烂 **3 → 4 处**（新增的 7 个候选里有 3 个是假阳性）：

| 脚本 | 腐烂原因 | 修法（注入原意不变）|
| --- | --- | --- |
| `_reverse_verify_read_roles.py` | `roleProvider: () -> AiRole?` 长成了 `actorProvider: () -> AiActor?` | 锚点跟进，"默认不认角色 → 默认按派单员跑"的意思不变 |
| 同上（第二条） | 闸门里多了一条 `(!it.memberOnly \|\| member)` | 只锚前半句 `k in it.roles &&` → 注入成 `true &&`（"等于没裁"）|
| `_reverse_verify_role_parity.py` | 派单员那一支长成 `ALL.filter { (it.roles == null \|\| role in it.roles) && !it.memberOnly }` | 摘掉 `&& !it.memberOnly` 那半句 |
| `_reverse_verify_user_search.py` | 那段 Kotlin 被格式化过：`{ it.username } },` 多了一个空格 | 锚点按现状改（**空格差异也会让注入静默失效**）|

**第 4 处修好后暴露出一条恒绿断言**（`_check_role_parity.py`）：它的 docstring 明确写着
"当初加这条判据就是为了抓住 `ALL.filter { !it.memberOnly } → ALL`"，
**但代码演进时只把前半句（`roles`）钉住了，`memberOnly` 那半句被丢在一边** ——
于是"派单员不再被 memberOnly 挡住"这个注入退出码 0、全绿。补上两条（派单员那支必须按
`memberOnly` 过滤、货主那支也是）→ `_reverse_verify_role_parity.py` **5/5**，
红线 15 → **16 项**。

**验证**：`_scan_stale_anchors.py` 复跑 **0 处腐烂**（494 个锚点）· `_reverse_verify_read_roles` **7/7** ·
`_reverse_verify_role_parity` **5/5** · `_reverse_verify_user_search` **25/25** · `_check_all.py` **50/50**。

⚠️ **顺带发现另一处"没有任何人在看"的过期**：`docs/ai/ai_read_catalog.json` 也是**机器生成的**
（每个读端点都记着 `文件:行号`），而我第二轮给 `ledger.py` 加日期窗口时它漂了（`84 → 109`、`149 → 162`）
—— 50 个检查**全绿**，没有一条判据看它（与第三轮补的"端点索引过期"是同一类洞）。
这一轮先把内容刷对：用生成器重跑，并**逐字节确认与干净生成一致**（`sha256` 相同 ——
排除"反向验证时带着注入生成"的可能）。⛔ **判据还没补**：生成器 `_gen_ai_read_catalog.py`
**没有 `--check`**、也不支持改输出路径，所以"哪天又漂了没人知道"这件事下次还会重演。
**下一轮第一件事**：给它加 `--check`，并把 `_check_endpoint_index_fresh.py` 推广成
「**所有机器生成的文档都必须新鲜**」（端点索引 + AI 读目录 + 工具表 + 那几份 `.kt` 生成物）。

### 第十五轮：把所有"机器生成的产物"纳入新鲜度判据（顺带修掉发现规则的两处漏与误）

先盘清生成器清单（4 个），再逐个看"谁在看它"：

| 产物 | 生成器 | 之前的状态 |
| --- | --- | --- |
| `08A_ENDPOINT_INDEX.md` | `backend/scripts/gen_endpoint_index.py --check` | 第三轮已补判据 ✓ |
| `docs/ai/ai_read_catalog.json` + `AiReadCatalog.kt` | `_tools/ai/_gen_ai_read_catalog.py`（**早就有 `--check`**，用 `"--check" in sys.argv` 判断）| ⛔ **从来没被跑过** —— `_check_all.py` 的发现规则只认 `argparse` 那一种写法 |
| `docs/ai/ai_toolmap.json` | `_tools/ai/_gen_ai_toolmap.py --check` | 在清单里 ✓ |
| `res/raw/*.wav` | `_tools/media/_gen_new_order_clip.py` | 二进制素材：由 `_check_notify_guardrails.py` 按 wav 头与常量对账 ✓（**不需要"新鲜度"这个概念**，已写在注释里免得下一轮有人来补一个没意义的判据）|

**修法（修在"发现规则"这一层，而不是只救一个脚本）**：

1. **发现规则加宽**：也认 `"--check" in sys.argv` → 清单 50 → **51**，AI 读目录那条检查进来了。
2. ⚠️ 加宽**当场踩到自己的坑**：我在新脚本的 docstring 里**提到**了那句写法（那是在说明"另一种写法"），
   于是它自己被当成"声明了 `--check` 的脚本"捡进必跑清单 —— 52/52 里那一格就是它。
   修法：**判据只看代码**（`_code_only` 先剥注释与文档字符串）。与仓库里
   "裸子串会被兄弟文案满足"（`ORDER_RETURN\b`、`不能同时配`）是同一类毛病。
3. ⚠️ 顺手撞出 `_check_all.py --only` **一直是坏的**（两个叠加的毛病）：
   · 下限判据（`n_plain < 8`）在**过滤之后**算 → 任何窄子集都报"清单过期了"、非零退出；
   · 过滤用 `str(Path)` 匹配，Windows 上是 `_tools\qa\x.py`，而文档教人写 `--only qa/x` → **静默选 0 个**。
   两处都修好（下限看**全量**清单、路径按 `as_posix()` 归一），并补"选中 0 个"的明确报错。

**反向验证**：把第三轮那份 `_reverse_verify_endpoint_index.py` **改名**为
`_reverse_verify_generated_artifacts.py`（名字要如实：它现在管的是"产物新鲜度"这一整条线）
并扩到 **6 条注入**：索引行号被改错 / 索引少一个端点行 / AI 读目录 JSON 行号过期 /
`AiReadCatalog.kt` 被手改 / 发现规则退回只认 argparse（清单里必须看不到那条检查）/
`--only` 判据退回过滤后（命令必须失败）→ **6/6 报红 + 四份被注入文件逐字节还原**。

**验证**：`_check_all.py` **51/51** · `_reverse_verify_generated_artifacts.py` **6/6** ·
`--only ai/_check_role_parity` 与 `--only qa/_check_dead_code` 都能用（各 1/1 通过）· 钱的对账不变。

### 第十六轮：把确认卡那句「5 分钟内有效」改成**按这张卡自己算**（并删掉两个没人用的辅助方法）

| 改的 | 为什么 |
| --- | --- |
| `ui/ai/AiChatScreen.kt` | 有效期文案原来照抄 `AiWritePreviewStore.DEFAULT_TTL_MS`（store 的**默认值**），而 store 的 TTL 是可配置的（单测就传过别的值）→ 一旦有人配了别的 TTL，卡片上那句"5 分钟内有效"就是**假话**，而用户是拿它当真的看的。现在按**这张卡自己的窗口**（`expiresAtMs - createdAtMs`）算 |
| `ai/AiWrite.kt` | 顺带删掉 `expired(now)` 与 `secondsLeft(now)`：全仓搜**只有它们自己的声明**（界面从来没按"还剩几秒"画过东西；过期与否由 `AiWritePreviewStore.take()` 在数据层保证，那才是唯一权威）。原地留注释写清"要恢复倒计时就加回 `secondsLeft`" |

⚠️ **删完之后红线当场抓到一件事**（这正是它存在的意义）：`AiChatScreen.kt` 里的
`import com.tapmoay.sorders.ai.AiWritePreviewStore` 变成了**没被用到的 import** ——
`_check_dead_code.py` 报红、删掉后 51/51。（顺带说明：这一步**没人会记得手动做**。）

**验证**：`:app:assembleEmuDebug` + `:app:testEmuDebugUnitTest` **BUILD SUCCESSFUL** · 装到
emulator-5556 启动 smoke 通过（`topResumedActivity=MainActivity`、无 FATAL）· `_check_all.py` **51/51**。

### 第十七轮：`price_rules` 两个入口补上「点名的对象必须真的在」（又是静默无效）

| 入口 | 原来的毛病 | 现在 |
| --- | --- | --- |
| `POST /price-rules`（单条设价）| 只查「这个货主+商品的规则是不是已存在」，**完全没查商品/货主本身在不在** → 给一个不存在（或已软删）的商品编号设价：接口 **201**、审计日志写「价格已设置」，而那个商品在选品页/下单页**对谁都不显示**（列表按 `is_deleted=False` 过滤）→ 这条价从写进去那一刻起就**没人用得到**，界面上看不出任何异常 | 先确认商品存在且没在回收站、账号存在，否则 **400 + 中文原因** |
| `POST /price-rules/batch`（批量调价）| `product_ids` 直接 `in_()` 查询、**不过滤 `is_deleted`** → 已软删的商品照样被写价（同样对谁都不生效），而返回里写着「共 N 条」 | 点名里有不存在/在回收站的商品 → **整批拒绝并点名是哪几个**（沿用"批量不做部分成功"的既有纪律）；批发商编号同理 |

新测试 2 条（`backend/tests/test_price_rule_product_scope.py`）：给不存在 / 回收站里的商品设价要 400、
账号不存在要 400；批量里混一个已删商品要**整批** 400 + 报错点名 + **连那个正常商品也不许写价**。

⛔ **这两条守卫由测试守着，不是静态红线**（写下来免得下一个人来找"为什么没有检查"）：
它们是**行为**（该 400 的时候 400），而静态判据只能锚"源码里有没有这一行"——
行为的正确工具是测试。代价是 `_check_all.py` 不跑 pytest，所以我把**全量 pytest 放进每轮的收尾**
（这轮 **674 passed**）。

✅ **顺带又一次证明新鲜度判据是活的**：我在 `price_rules.py` 中间加了约 25 行 → **AI 读目录与端点索引
同时漂了**，两条判据当场报红（「❌ 产物已过期」「`--check`: 与代码一致」失败），重新生成后 51/51。
上一轮接的这两条线，这一轮自己就抓到了第一次真实漂移。

**验证**：`pytest -q` **674 passed**（原 672 + 新 2 条）· `_check_all.py` **51/51** ·
钱的对账 `39 项 / 确认缺陷 0 / 可疑 0` · 两份产物已重新生成并复验新鲜。

**验证**：`_check_all.py` **54/54** · `cd backend && pytest -q` **671 passed** · `_reverse_verify_expense_page.py` **15/15** · `_reverse_verify_catalog_and_scope.py` **25/25** · `08A_ENDPOINT_INDEX.md` 已重新生成（192 端点，行号顺手对齐）。

### 第十八轮：同一张老单，读侧一个答案、钱侧另一个答案（又是"不报错"的那一类）

**形状**：`orders.driver_billing_mode_snapshot` 是 v3.36 才加的列 —— **之前派出去的老单是 NULL**。
钱那一侧对 NULL 的口径**早就定过**：`driver_pay.has_per_order_pay`（有运费就算 PIECE）+
`driver_bills.py` / `freight_settlement.py` 两处筛选 `snapshot == 'PIECE' OR snapshot IS NULL`。
而四个**展示/门控**消费点各自抄了一份兜底 `快照 or resolve_billing_mode(车型, 计费)` ——
那算的是司机**现在**的档案。于是同一张老单可以同时是：

| 消费点 | 原来的兜底 | 后果（两边都不报错） |
| --- | --- | --- |
| `order_response.apply_driver_view_gating`（运费可见性 + `freight_fee`） | 司机档案 | 账单按单给他结，**界面上却把运费藏起来** |
| `order_response.enrich_order_out`（出参 `driver_billing_mode`，客户端照它显示） | 司机档案 | 同上，客户端也跟着一起藏 |
| `message_center.publish_order_freight_updated` | 司机档案 | 运费改了**不提醒他**（他的钱变了，没人告诉他） |
| `order_flow.complete_delivery` 的拍照义务 | 司机档案 | **免了拍照**，却在按单给他结账 |

**修法**：兜底收成 `driver_pay.order_mode(order)` 一处（快照优先；NULL 走"有运费就算 PIECE"），
`has_per_order_pay` 改成 `order_mode(order) == "PIECE"`，四个消费点全部改调它。
顺带：`apply_driver_view_gating` **不再接收司机对象**（判据只该看订单；留个参数在那里等于暗示"司机档案也算"）；
`freight_settlement.py` 里一个没人用的 `apply_driver_view_gating` import 删掉。

⚠️ **这一轮改变了对老单的可见性**（写明，免得以后被当成回归）：快照为 NULL 且有运费的老单，现在**会**显示运费、
**会**要求拍照、运费变更**会**发提醒 —— 与账单一致。受影响面 = v3.36 升级前派出、且仍在途的老单
（生产上只剩历史尾部；而此前"按单结账却不显示运费"本身就是错的）。

**这个字段此前一个测试都没有**（全仓 `freight_visible` **0 处断言**）—— 所以它走散了很久没人知道。
新增 `backend/tests/test_driver_order_mode.py` **9 条**：老单必须看得见运费、工资制快照必须看不见
（防"统一成永远可见"）、门控永远剥离货款、模式只由快照/老单口径决定、以及**走真接口**的端到端
（司机 `GET /orders/{id}`：老单 `freight_visible=true`，改成 SALARY 后立刻藏起来）。

**注入证明（行为层）**：把旧兜底写成**合法 Python** 注回 `apply_driver_view_gating` → 新测试 **2 failed**
（`assert False is True`，正是"账单按单结、界面却把运费藏起来"）→ 还原后 **9 passed**。
静态层：新红线 `_check_single_source.py` **④b**（`resolve_billing_mode(` 只许出现在"问这个人现在怎么算钱"的地方；
碰订单模式的文件必须真的调同源函数）+ `_reverse_verify_single_source.py` **15/15**（新增 2 条注入：
兜底写法回来 / 调了别的写法）。

**红线自己的第一版两个方向都错了（反空转判据当场抓住）**：① 用"源码里出现过 `resolve_billing_mode(`"去查，
把 `models/user.py` 的**函数定义**当成违规；② 按"列名"数消费点，而收口之后**没人再直接读那一列**了 →
只数到 2 个，判据自己报「在空转」。现在按"谁在问这张单的模式"（读列 ∪ 调那两个函数）来数，并用后行断言排除 `def`。

⛔ **踩到的坑（写给下一个做注入实验的人）**：注入之后用 `git checkout -- <file>` 还原，把那个文件**未提交的改动
一起抹掉了**（它回到 HEAD 的旧实现）—— 本轮为此把 `order_response.py` 的改动重做了一遍。
注入实验要用**自己的字节备份**（`Copy-Item` 到 `%TEMP%`）还原；`git checkout --` 只对**已提交**的文件安全。

**验证**：`pytest -q` **683 passed**（674 + 新 9）· `_check_all.py` **51/51**（顺带抓到两份生成产物过期，已重生成）·
`_reverse_verify_single_source.py` **15/15** · 钱的对账 `39 项 / 确认缺陷 0 / 可疑 0`。

### 第十九轮：SQL 侧还各写了一遍模式判据（**空串**上两边答案相反）

承接上一轮。把"这一张单按不按单拿钱"收进 `driver_pay.order_mode` 之后，**SQL 侧那两处各写了一遍**
同样的 `upper(快照) == 'PIECE' OR 快照 IS NULL`（`driver_bills` 的补单、`freight_settlement` 的结算页），
而 Python 侧 `order_mode` 把**空串**也当"没写"（`snapshot or ""` → 落到老单分支）。于是对
「快照 = 空串、有运费」这一行数据：

| 侧 | 答案 | 后果 |
| --- | --- | --- |
| 钱（`has_per_order_pay` → 生成/补账单） | 有按单应付 | 账单**生成了** |
| SQL（结算页） | 不是 PIECE | 结算页**不列它** → 派单员照着这一页付钱，永远付不到它 |

两张表对不上、谁都不报错。这一列的历史数据里已经出现过小写、大写两种写法，空串是第三种。

**收法**：新增 `driver_pay.per_order_pay_filter()`（SQL 版判据，与 `order_mode` 同一处），两处调用点改调它，
`upper()` 比较、"NULL/空串都算没写"的理由全部搬进它的文档。两个文件因此各自少一个 `or_`/`and_`/`func` 导入；
顺带删掉 `driver_bills.py` 里**重复了一行**的 `from app.services.operation_log_service import write_log`。

**合同测试**（新，同一份 `test_driver_order_mode.py`）：一张 9×2 的取值矩阵
（NULL / 空串 / 纯空白 / `PIECE` / `piece` / ` PIECE ` / `SALARY` / `salary` / `??` × 有价 / 无价）
逐行比较 SQL 判据与 Python 判据的答案，**不许有一行不同**；再加一条走真接口的
（`GET /freight-settlement` 必须列出这张空串老单）。注入旧的 SQL 写法（只认 NULL）→ **两条同时红**
（矩阵报 `('', '50.00')`、接口报「结算页却不列它」）→ 还原 **11 passed**。

**红线收紧**（`_check_single_source.py` ④b 重写）：① `resolve_billing_mode(` 只许出现在"问**这个人**"的地方；
② 那一列**读**只许出现在 driver_pay（唯一读处）/ 列定义 / 建列三处；③ 反空转：三个入口函数必须都在 +
消费点 ≥5。`_reverse_verify_single_source.py` **16/16**（新增 SQL 那条注入）。

⚠️ **上一版判据被自己架空了（记下来）**：它要求"碰这一列的文件必须调同源函数"，
而收口之后**没有任何文件再碰这一列**（读侧都去调函数、SQL 侧去调 filter）→ 那条规则恒绿。
所以改成**绝对白名单**："这一列只许出现在这三个文件里" —— 判据要能因为"有人绕开"而红，
而不是因为"没人碰"而绿。同样地，第一版还把派单时的**赋值**当成违规（红线当场误报）：
判据精确到"读"（`column_read` 用 `(?!\s*=(?!=))` 排除赋值左侧）。

### 第二十轮：确认卡的「造卡」原来有 17 份实现（收成一处，并揪出一条一直没被扫到的星号）

**形状**：这一句 —— `NeedConfirm(store.offer(actionId, title = AiWrites.titleOf(actionId), risk = AiWrites.byId(actionId)!!.risk, …))`
—— 在 `android/.../ai/` 下写了 **17 遍**：5 个处理器里**逐字相同**的 `card(...)` 包装（各 12 行）+ 12 处内联
`store.offer(...)`。卡片标题与风险档位（要不要二次确认）是用户唯一看得见的东西，17 份实现里任何一处写歪都不报错。

**收法**：新增 `AiWritePreviewStore.card(actionId, summary, detailLines, payload, title = 登记表, risk = 登记表, isUndo = false)`
**一处**（内部调 `offer`；`title`/`risk` 默认从 `AiWrites` 取）。5 个包装变成 4 行转调、12 处内联改调它；
声明式 CRUD 与「撤回」手里已经有 `AiWriteAction` 对象，把 `action.title`/`action.risk` 作具名参数传进去 —— 与原来一字不差。

**两个坑（写下来，免得下次重踩）**

1. **返回类型必须是 `AiPendingWrite`**（暂存区那张卡），不是 `AiWriteOutcome`：内联调用点外面本来就包着
   `return AiWriteOutcome.NeedConfirm(...)`，多包一层 ⇒ Kotlin 编译器当场报 **13 处**
   `Argument type mismatch: actual type is 'AiWriteOutcome'`。
   👉 这正是"机械化改写必须过编译器"的地方 —— 静态红线只做文本匹配，**看不出类型错误**。
2. **参数名不能叫 `details`**：本想叫得更顺口，结果撞上另一条红线 ——「`details = ` 的声明都定位到了」
   会把**调用点的具名实参**也数成一次声明（分母变大 → 4 个文件误报）。
   定名 `detailLines`（= `AiPendingWrite.detailLines`），与数据类字段一致，也省掉一次全局改名。

**顺手揪出的真缺陷（一直印在屏幕上）**：核销卡里那句
`add("（没有点名商品 = **整单核销**：这一单还欠的全收）")` 会**原样显示星号**。
它之所以从来没被扫到：卡片文案的区间是「`summary = ` 到 `payload = `」，而**明细里只要有一个多行表达式
（以"单独成行的 `)`"收尾），区间就在那里提前收尾** —— 这一行之后的明细从未被扫过。
修法：明细块按**花括号配对**再收一遍（与 2e-③b 同一份配对器），并把那句星号去掉；
反向验证新增一条注入钉住它（旧扫描认不出、新扫描必须红）。

**红线同步（换锚 + 新判据）**

- 卡片锚从 `store.offer(` 换成 `store.card(`（**不**写成"两者都算"：都算就看不出"有人绕开出口"）；
- 新增「每个文件里自己拼 `store.offer(` 的次数必须是 0」→ 14 条断言，红线 **1103 → 1117 项**；
- 「撤回走的是造卡」那条断言随之改成 `store.card(`，`_reverse_verify_undo.py` 的注入锚点同步
  （不同步的话它会**静默失效**：替换串匹配不上）；`_show_card_markdown.py` 注释与
  `docs/AI_ASSISTANT_PLAN_V3.md` 的两处流程/判据说明同步。

**验证**：`_check_ai_guardrails.py` **1117 项全绿** · `_reverse_verify_card_markdown.py` **15/15**（新增 2 条注入）·
`_reverse_verify_undo.py` **13/13**（锚点同步后仍然会红）· `compileEmuDebugKotlin` **BUILD SUCCESSFUL**
（第一版在这一点上失败，见坑 1）· Android 单测 **913 用例 / 0 失败** · `_check_all.py` **51/51**
（⚠️ 其中真模型探针第一次跑是**外部网络** DNS 失败，重试即过 —— 不是代码问题，但结论要如实标注）。

**净行数**：`android/.../ai/` 13 个文件 **+73 / −85（净 −12 行）**。⚠️ 行数不是这次的重点：17 处实现收成 1 处的
价值在「**不可能各自走散**」，而这 17 处本来彼此只差两三行（所以别拿"省了多少行"当这类改动的理由）。

**真机**（emulator-5556 派单员，装的是本轮构建的 APK）：在 AI 页说「荷兰豆改价 15 元」的拼音
（`input text` 打不了中文），真机上弹出确认卡「**中风险 / 改商品：荷兰豆 / 默认单价改成 15.00 元**」
+「5 分钟内有效…」+「误操作了不要紧…」—— 标题、风险档位、有效期、撤回说明全在，说明收口后的
`store.card(...)` 在真机上确实造得出卡；点「取消」→ 消息变成「已取消：改商品：荷兰豆」，
库里 `products.default_unit_price` 仍是 **14.8**（卡片从未被确认，数据一字未动）。

⚠️ **这台模拟器没开剪贴板共享**：`_tools/ai/_emulator_say.ps1` 的中文粘贴进不去（它**如实报错**
「粘贴没进输入框」，没有假装已发送 —— 这个"失败要吵"的设计这次救了场）。绕法：`adb shell input text`
打 ASCII（拼音），再手点输入框右边那个**蓝色圆箭头**发送键（回车只会插入换行）。
已把这条写进脚本头部注释，免得下一个人再摸一遍。

### 第二十一轮：`read_data` 的参数定义有两份，而其中一份**从来没人读**

**形状**：`AiTools.kt` 里那 7 个公共筛选参数（name / q / from / to / status / limit / extra）**逐字抄了两遍**
（各 43 行）：实例侧的 `readDataSpec(actor)`（action 清单按角色裁）+ companion 里的静态表 `SCHEMAS`
（action 清单来自全量目录）。2026-09-19 那次「`status` 不许举例子（PAID 不是订单状态）」的修法，
就是在两边**各改一遍**才对上的 —— 漏一边的后果不是报错，是模型看到两套参数说明。

**但真正的答案是"删掉死的那一份"**（读代码得出的，不是猜）：

- `specs` 里 `READ_DATA -> readDataSpec(actor)` 是**显式分支**；
- `specOf(name)`（唯一读 `SCHEMAS` 的地方）只在 `else ->` 上被调用 → `specOf(READ_DATA)` **不可达**；
- `SCHEMAS` / `schemas()` / `specOf` 全是 private，测试也没有引用。

所以静态那份**一个读者都没有**。而 `readDataSpec` 的注释还写着「参数部分与静态那份一致」——
**当年是"以为它还在用"才留着两份的**。删掉它：**−58 / +7 行**（含按全量目录生成的 action enum），
`AiReadCatalog.ACTIONS` 在 `AiTools.kt` 里从 2 处变 **0** 处。

⚠️ 我一开始走的是**收口方案**（把 7 个参数抽成 `putCommonReadFilters()`、两处调用），写完才发现
静态那份根本没人读 —— 那等于**继续养着一份死定义**。已改回"删"。教训写在这儿：
**先问"这两份各有几个读者"，再决定是收口还是删**；重复不总是"两处都在用"。

**顺手修的一处注释**：解释「模型无法确认自己的申请」的那段 KDoc 原来挂在 `roleProvider` 头上
（它属于 `requestWrite`）—— 注释挂错位置和写错内容一样会骗人。

**红线（3 条，新增 6 项：1117 → 1124）**：① 静态表里不许再有 `read_data` 的条目
（用 `block_between("private val SCHEMAS", "private val DESCRIPTIONS")` 圈定范围）；
② 5 条特征描述在全文件里**各只许出现 1 次**（2 = 又抄一遍；0 = 被删了）；
③ 它们必须**在 `readDataSpec` 里**（光数"只有一份"证明不了那一份在能用的地方）。
反向验证 `_reverse_verify_read_roles.py` 新增 2 条注入（把死的那份加回静态表 / 改掉唯一的 `status` 键名）。

**验证**：红线 **1125 项全绿**（新增 7 条）· `_reverse_verify_read_roles.py` **9/9** ·
Android 单测 **913 用例 / 0 失败** · `_check_all.py` **51/51**
（真模型探针第一次跑又是**外部网络** DNS 失败，重试即过 —— 本轮第二次遇到，如实标注）。

⚠️ **反向验证当场抓到一条空转判据**：我原来只钉「描述串出现 1 次」，把键名 `status` 改成 `statusX`
判据**照样绿**（描述串还在、计数还是 1）—— 而模型拿到的参数名已经错了。于是补了
「7 个键名都必须在 `readDataSpec` 里」。**这条注入留着**：它钉的是"键名也是模型照抄的东西"。

**真机**（emulator-5556 派单员，装本轮 APK）：在 AI 页发一条读请求（拼音 —— 这台模拟器剪贴板共享没开）
→ 模型真的调了 `read_data`：聊天页渲染出商品表格（麒麟西瓜 9.40 / 红富士苹果 12.30 / 海南香蕉 20.00 …）
+ 一句「已跌破报警线、该补货的：橙汁饮料 1、玉米胚芽油 2、罐装凉茶 6 …」，还顺带确认了上一轮那张改价卡
「荷兰豆还是 14.80 元——上次那张改到 15.00 的卡取消了，没生效」。

⛔ **这一步是必须的**，不是走过场：**没有任何单测构造过 `AiTools` 或读过 `.specs`**
（它要一个真的 `AppRepository`，测试里构造不出来），所以"删掉 `SCHEMAS` 里那份定义之后，
工具清单还装不装得出来"只有真机能证明 —— 万一 `specs` 真会走到 `specOf(READ_DATA)`，
那里是 `getValue` 会**直接抛**，表现就是整个 AI 不可用。

### 第二十二轮：订单商品行合计在 Android 里写了三遍（其中一遍是**收款页的判据**）

**形状**：Σ 订单行 `line_total`（定点）这段求和，在 Android 里有**三份**：

| 位置 | 用途 |
| --- | --- |
| `ai/AiWriteService.kt::findOrders` | AI 确认卡上的「订单金额」（`AiOrderRef.amount`） |
| `ai/AiWriteService.kt::findDeletedOrders` | 同上（回收站那条路） |
| `ui/dispatcher/AccountToolsScreens.kt::orderTotal` | 收款页明细行的 ¥ 与「合计 ¥」，**以及收款页的判据** |

收款页那处的 KDoc 自己就写着「写法与本仓库既有实现同源（`ai/AiWriteService.kt:473`）」——
**作者知道有多份**，只是没地方收。而这三份必须给出同一个数：判据那一处要求用户照抄填进去的金额
与后端 `Decimal` 算出的数**完全相等**，差一分就 400，表现是**多行/多单时永久收不了款**
（2026-09-19 报告 P0-4：原来判据用 `Double` 顺序累加，20 万次随机试验失配率 2 行 22.72% / 5 行 37.68%）。

**收法**：`util/Money.kt` 加 **`OrderDto.goodsTotal()`**（定点 `BigDecimal` 求和）与
**`goodsTotalText()`**（两位小数 `HALF_UP` 字符串，AI 卡片要字面量时用）；三处改调它。
`AccountToolsScreens.orderTotal` 保留原名但变成一行转调（本屏两个调用点不动）。
⛔ 它的 KDoc 写清「**不许**拿 `formatMoney`/`Double` 算钱」：`formatMoney` 是**显示**口径。

**顺手**：把「算钱 vs 显示」的区别钉进单测（`util/MoneyTest.kt` 新增 5 条）：
① `0.1 + 0.2` 定点是 `0.30`；② 行金额为空当 0；③ `1.005` 按 `HALF_UP` 是 `1.01`；
④ **P0-4 原型**：三行 `1063.56` 定点正好 `3190.68`（`Double` 顺序累加是 `3190.6799999999994`）；
⑤ 只相加、不重算（行金额是后端算好的）。

⚠️ 写测试时踩了一个坑，记下来：我原想钉「`formatMoney("1.005")` 会给出 1.00」来对比两种口径，
**结果它是 1.01**（Java 的 `%.2f` 按最短十进制表示做 HALF_UP，不是按二进制精确值）。
断言错在"我以为的 JDK 行为"上 —— 换成上面那个真正能体现差别的用例（`Double` 累加的长尾）。

**红线**：`_tools/qa/_check_single_source.py` 新增 **④c**：Android 侧折点求和（`lineTotal?.toBigDecimalOrNull()`）
全仓只许出现 **1** 处且必须在 `util/Money.kt`；调 `goodsTotal`/`goodsTotalText` 的文件 ≥2。
反向验证 `_reverse_verify_single_source.py` **17/17**（新增一条注入：AI 卡片又自己折点求和）。
定位表「金额格式化」那一行同步扩成「金额格式化**与算钱**」。

**验证**：红线 ④c 绿（折点求和 **1** 处、消费点 **2** 个文件）· 反向验证 **17/17** ·
Android 单测 **918 用例 / 0 失败**（新增 5 条）· `compileEmuDebugKotlin` 成功 · `_check_all.py` **51/51**
（⚠️ 真模型探针本轮**连续两次**瞬时外部网络故障（`getaddrinfo failed` / `RemoteDisconnected`），
第三次才过 —— 这个波动是检查依赖外部 LLM 端点带来的，不是代码问题，如实标注）。

**真机**（emulator-5556 派单员，装本轮 APK）：在 AI 页让它「把 SO202609178874649541 标记异常」
→ 它先按"缺信息就问"要了原因 → 补一句「商品破损」后弹出确认卡，卡片信息区是
「订单号 / 货主 周秀英 / 当前状态 待派单 / 送货地址 / **订单金额 74.00 元**」——
而库里那一单的 `sum(line_total)` 也是 **74.00**：卡片上的数与库里的数**逐分一致**
（这正是这一轮收口的那个数，收口前它由 `AiWriteService` 里那份拷贝算出来）。
点「取消」→ 库里 `is_exception=0`、状态仍是「待派单」（卡片从未被确认，一个字节没写）。

### 第二十三轮：两个本地文件存储各抄了同样的 ~120 行（收成 `AiJsonStore`，并给它补上**从来没有过**的测试）

**形状**：`AiConversationStore`（对话历史）与 `AiMemoryStore`（长期记忆）是**逐行抄的两份**：
`load()` / `readSilently()` / `save()`（原子写 + 防覆盖兜底）/ `clear()` / `sizeBytes()` / `quarantine()` / `everLoaded`。
它们守的是**同一批真实事故**：

1. 直接往目标文件写、写一半被杀（低电/闪退）→ 半截 JSON、整段数据丢；
2. **"还没读过盘就全量保存"** → 把盘上原来的东西全部盖掉（**真发生过的丢历史事故**）；
3. 坏文件被下一次写盘盖掉（留着才有可能救回来）；
4. 任何异常都不许让聊天功能挂掉。

⛔ 而这两份**已经走散了一处**：`clear()` 里"要不要把 `everLoaded` 置 true"一份设、一份没设。
这类偏差不会报错，只会让"到底哪一份更可靠"变成掷骰子。

**收法**：新增 `ai/AiJsonStore.kt`（**只认一个 `File`**、不带 Android 依赖；`encode/decode/merge` 由调用方注入）。
两个 store 各自瘦成「存哪个文件 + 怎么编解码 + 按 id 怎么合并」（约 40 行），各自的 KDoc（数据用途、隐私边界）保留。
`clear()` 的 `everLoaded` 统一成设 `true` —— 两条路结果本来就相同（文件已删 → 静默读出空 → 合并结果 == 手上的列表），
设 `true` 只是省掉一次多余的读。

**新测试（这一轮真正的收益）**：`AiJsonStoreTest` **7 条** —— 那四条行为**以前一条测试都没有**
（原类需要 `Context`，JVM 单测碰不到）：往返读写、文件不存在、**没读过盘就存 → 合并而不是覆盖**、
读过盘之后再存是全量覆盖（删掉的条目真的没了）、坏文件改名留证且原文件不留在原地、
`clear` 之后文件没了且下一次是覆盖、原子写的 `.tmp` 用完不留。

**红线跟着实现挪（它如实报红了 5 条）**：三条原来钉在 `AiMemoryStore.kt` 的实现体上
（`renameTo(file)` / `quarantine()` / `fun save(...) = try`），两条钉在 `AiConversationStore.kt` 上
（`renameTo(file)` / `AiConversations.mergeById(readSilently()`）→ 全部改钉 `AiJsonStore`，
并**新增两条**"两个 store 都真的把合并函数接上了"。
⚠️ 只钉"某个文件里出现过某段字符串"会退化：实现搬走之后判据仍绿，而那条兜底可能**压根没接上** ——
这正是它当年守的那次事故的形状。红线 1125 → **1128 项**。

**真机**（emulator-5556 派单员，装本轮 APK）：`files/ai_conversations_u1.json`
**100298 → 100999 字节**（发一句话之后），拉下来是**合法 JSON**（`{version, conversations[14]}`），
盘上**没有 `.tmp` 残留** —— 读（AI 页照常显示上一段对话）与写（文件真的更新）两条路都走通了。

### 第二十四轮：逐行退货编辑器在两个角色页面里各抄了一遍（收成 `OrderReturnLines` 一处）

**形状**：派单员端（**执行**退货）与货主端（**申请**退货）的弹层里，那段「逐行填退货数量」**逐字相同**
（各约 31 行）：每行显示「下单 / 货损 / 已退 / 可退」、`−`/`+` 调数量、`+` 的上限是 `vm.maxReturnable(line)`。
而它是**退货金额的入口**：能退几件算错一件，红冲金额与补回库存就跟着错（用户点名不许出错的那几块之一）。
只改一份的后果**不会报错** —— 两个角色对同一张单会给出**不同的可退数量**。

**收法**：抽成 `OrderReturnLines(lines, returnQty, maxReturnable, onSetQty)`
（放 `ui/common/Components.kt`，与 `FormErrorLine` / `SearchField` 同处）。
⚠️ **刻意不抽走的**：引导语、两个按钮的措辞（「整单全退」vs「全部勾满」）、以及下面的汇总行
（派单员看「退货金额 ¥142.00」，货主看「一共申请退 9 件，派单员只能按这个数量退，不能改」）——
那些本来就**应该**不同：共用的是**逐行编辑器本身**（同一个操作、同一套上限），不是整张弹层。

**红线（`_check_order_return.py` 如实报红了 2 条）**：两条旧断言钉在被搬走的代码上
（`vm.setReturnQty(line.id` 与 `vm.maxReturnable(line)`）→ 改钉**调用点**，并**新增**：
① 编辑器只此一处；② 上限由调用方传入（编辑器自己不重算）；
③ **消费点从源码算**（谁的页面上有 `vm.returnQty`，谁就必须用共用组件 —— 本轮算到 **2** 个页面）；
④「`· 可退`」那一行只许出现在一个文件里（再抄一份立刻红）。
红线 105 → **110 项**；反向验证 `_reverse_verify_order_return.py` **27/27**
（新增一条注入：把货主端那份抄回去 → 报红）。

**顺手**：`Components.kt` 里 `import androidx.compose.runtime.setValue` **重复了一行**（删掉）；
搬走编辑器后 `ShipperOrdersScreen.kt` 的 `Icons.filled.Remove` 成了死 import ——
**`_check_dead_code.py` 当场抓到**（这正是它存在的意义）。

**真机（两个角色都验了，装本轮 APK）**：

- 派单员（5556）订单管理 → 已送达 →「退货」：弹层里「东北木耳 下单 4 · 可退 4」「荷兰豆 下单 6 ·
  **已退 1** · 可退 5」+「退货金额 ¥142.00」+ 备注框 +「确认退货」✅ 与改动前一字不差；
- 货主（5554）我的订单 →「申请退货」：同一套逐行编辑器（「花生油 下单 1 · 已退 1 · **可退 0**」
  「荷兰豆 下单 10 · 已退 2 · 可退 8」）+「一共申请退 9 件」+「提交申请」✅；
- 两边都点「取消」→ 库里那两张单的 `returned_at` 仍是旧时间戳（**没有写入任何退货**）。

### 第二十五轮：退货申请两端的 VM 各抄了约 90 行（收进共用内核）+ 修掉一条「崩了还给绿」的检查

**这一轮抓的两件事，都是「同一个判断有两处」的形状。**

#### ① 退货申请两端共用一个列表内核

`DispatcherReturnRequestsViewModel`（244 行）与 `ShipperReturnRequestsViewModel`（180 行）里有约 90 行
**逐字相同**：档位状态、`load()`、`applyFocus`、`selectTab`、"另一端动过之后自动重拉"。
它们**不是样式，是规则**：

1. 带 `?focus=` 进来必须**先切到「全部」档**再拉 —— 否则"已经办完的那一条"在「待处理」里必然找不到，
   界面就说「没找到那条申请」，而它明明在；
2. 定位不到时必须给一行说明（不白屏、也不假装定位成功）；
3. 找到的那一条**排到最前并打标记**（`focusReturnRequestFirst`，两端做法必须一样）；
4. 实时刷新（另一端提了 / 办完之后列表自己冒出来）。

抄两份的后果很具体：**四条里有一条没跟上，就只有一个角色会遇到那个毛病**，另一个不会。

**收法**：新增 `ui/common/ReturnRequestsViewModel.kt`（抽象基类；档位表 / 拉哪个接口 / 能做什么动作留给子类）。
⚠️ 如实说：净行数 **424 → 418（−6）**，几乎不省行 —— 这类收口买的是「**规则只有一处**」
（`focusReturnRequestFirst` 的调用者从 2 个变 1 个）。这与仓库既有的 `services/category_order.py`
是同一个判例：**重复本身不致命，致命的是它守的那条规矩要改两处**。

**红线**（`_check_return_request.py` 新增 §8b，共 5 条 → **128 项**）：内核只此一处；构造时与 `applyFocus`
都要切到「全部」档；**定位规则只许内核调**（两个子类不许自己再排一次）；**消费点从源码算**（两个 VM
必须真的继承它）。
⚠️ 第一版把**函数定义**那一行也当成"调用者"、当场误报（同一个坑 `_check_single_source.py` 栽过一次）
→ 用后行断言排除 `fun `。
反向验证 `_reverse_verify_return_request.py` **15/15**（新增两条：子类自己又排一次定位 / 内核不再切「全部」档）。

#### ② 顺手修掉一条「崩了还给绿」的检查（`_check_backend_fresh.py`）

收尾时它报 `AttributeError: 'NoneType' object has no attribute 'strip'` —— `subprocess.run(...).stdout`
拿到过 `None`。更要紧的是它的失败路径**是 fail-open**：读不到进程表时会落进"本机没有在跑的后端 → 通过"
那一支，也就是**拿一次失败的测量给出绿结论**；而我的收尾流程每次都是"重启后端 + 立刻跑检查"，
正好撞在这个窗口上。现在两条路分开说：真的没有后端 → 绿（不变）；**读不到 → 红**，
并明说「这不是『后端没在跑』，是这次没读成」。两条路都现场验过（正常 → 绿；把 `powershell`
换成不存在的命令 → 红 + 退出码 1 + 零残留）。

**真机**（两个角色，装本轮 APK）：派单员（5556）工作台 → 退货申请：「待处理 / 全部」两档，切「全部」
拉出真实申请（状态中文名来自后端：`已关闭（派单员已直接退货）` / `已办理（退货已完成）`）；
货主（5554）同一页：「我的退货申请」+ 档位顺序相反（待处理在前）✅ —— 两端走的是同一个内核。

### 第二十六轮：退货申请两端的**页面**也各抄了一遍（收进 `common/ReturnRequestsUi.kt`）

上一轮收的是 VM 内核；这一轮把**页面上**三段逐字相同的块收掉。

| 块 | 原来 | 抄错的后果（都不报错） |
| --- | --- | --- |
| 档位标签（待处理那一档带张数） | 两页各写 `mapIndexed { i, t -> if (i == 1 …) }` / `if (i == 0 …) }` | 两页的档位顺序**相反**，那句魔法下标只在各自那一页是对的；抄错就把张数挂到**另一档**（用户看到「全部 3」，点进去不是那三张） |
| 定位失败那一行说明 | 两页各写 10 行 | 改一处另一处就分叉（文案本身另有唯一出处 `RETURN_REQUEST_FOCUS_MISS`） |
| 行首（定位徽章 + 订单号 + 状态徽章） | 两页各写约 25 行 | 徽章是「点通知进来确认就是这一条」的唯一依据 —— 只有一边有，那个角色就永远看不到 |

**收法**：新增 `ui/common/ReturnRequestsUi.kt`：
`returnTabLabels(tabs, pendingCount)`（**纯函数**，而且顺手把"魔法下标"换成**按 key 判**）、
`ReturnRequestsFocusNotice(notice)`、`ReturnRequestsHeading(req, focused)`。
两页只留下各自真正不同的东西（页标题、空态文案、行里各自的按钮）。

**新测试**：`ReturnTabLabelsTest` **4 条** —— 张数挂在 `pending` 那一档（与档位顺序无关）、
没有待处理时不加那个 `0`、名册里没有 `pending` 时不硬塞、其它档永远不带数字。
单测 925 → **929**。

**红线**（`_check_return_request.py` §8c，6 条 → **134 项**）：三段各只有一处；**消费点从源码算**
（谁的行里画 `req.linesSummary`，谁就必须用共用行首）；两页**不许自己算档位标签、也不许自己画那一行说明**；
定位徽章的文案只许出现在一个文件里。
反向验证 `_reverse_verify_return_request.py` **17/17**（新增两条：把徽章抄回派单端 / 货主端又按下标算标签）。

**顺手**：搬走那两段之后，两页各留了没用的 import（`RoundedCornerShape` ×2、`FontWeight` ×1）——
`_check_dead_code.py` 当场抓到，已删。

**真机**（两个角色，装本轮 APK）：货主端「我的退货申请」（待处理在前 + 空态）；
派单端「退货申请」切「全部」拉出真实申请（订单号 + 后端给的状态中文名 + 申请人 + 商品×件数 + 时间）✅
与改动前一致。

### 第二十七轮：四个「分类名册」页面各抄了一遍同样的三条判断（收进 `common/CategoryRoster.kt`）

分类名册（开销 / 运费 / 商品 / 地点）四个页面各有一份「把行排成一份名册」的逻辑，
其中开销、运费、商品三页还各有一份**本地草稿顺序**（拖一下不提交，点「保存顺序」才发整份）。
结果同样的三条判断被抄了四遍，而且**四份写法各不相同**。

| 判断 | 原来 | 抄错/写歪的后果（都不报错） |
| --- | --- | --- |
| ① 提交时只带名册内的行 | 各页 `rows.map { it.id }` | 名册末尾有一行**合成的「新建」占位**（`id = 0`），提交时把 `0` 也发上去 |
| ② 「未保存」= 当前名册 ≠ 已保存顺序 | 各页自己比 | 合成行的 `id=0` 永远不在已保存顺序里 → **存完了「未保存」还亮着**（三个页面全中，本轮实测发现） |
| ③ 撤销 = 回到已保存顺序，但**保存之后新建的行不许丢** | 各页自己重建 | 运费那页重建时**把新建的分类直接丢了**（用户看到刚建好的分类消失） |

**收法**：新增纯函数 `ui/common/CategoryRoster.kt` —— `submittableIds(rows, idOf)`（只留 `id > 0`）、
`orderChanged(rows, savedOrder, idOf)`、`revertedOrder(rows, savedOrder, idOf)`（**保住 `id <= 0` 的新行**）。
四个页面（`ExpenseCategoriesScreen` / `FreightCategoriesScreen` / `ProductCategoriesViewModel` /
`PlaceCategoriesViewModel`）改成调用它们；商品页 `saveOrder` 从"直接 map"改成 `submittableIds` + 空则不提交。

**行为变化（都是防御性的，写在这里备案）**：商品/运费「保存顺序」不再发送 `id=0`；
运费「撤销改动」不再丢新建项；三页保存成功后「未保存」正确熄灭。

**新测试**：`CategoryRosterTest` **5 条**（合成行不进提交、顺序相同不算脏、撤销保住新行、
撤销后不算脏、只有新行时也算脏）。单测 929 → **934**。

**新红线**：`_tools/qa/_check_category_roster.py`。**清单自己算**——扫 UI 层 `repo.reorder\w+Categories(`
的命中文件（4 个），再断言：`CategoryRoster.kt` 里三个函数各只此一处、4 个页面都必须用
`submittableIds`、3 个有草稿的页面必须用 `orderChanged` / `revertedOrder`，并且**原来的三种内联写法
一行都不许再出现**。反向验证 `_tools/qa/_reverse_verify_category_roster.py` **3/3**
（把运费撤销改回丢新行 / 商品提交改回不过滤 / 开销脏判据改回内联，三个都能被抓住）。

**顺手**：`_check_expense_page.py` 的锚点随实现搬到 `submittableIds(categories)` 重新钉住；
`_check_test_names.py` 抓到一条测试名里带 ASCII 引号，改名。检查总数 51 → **52 个脚本，全绿**。

**真机**（模拟器 5556 货主端，本轮 APK）：工作台 → 账本管理 → 开销管理 → 分类管理，名册 1~8 行渲染正常
（「共 N 笔 · 卡片突出：X」都对得上）；点第 4 行**下移** → 「撤销改动 / 保存顺序」出现（= 脏）；
点「撤销改动」→ 顺序回到 4/5/6/7/8 且两个按钮**消失**。
⚠️ 全程**没有点「保存顺序」**——真机上验证的是本地草稿与撤销这条路径，**一次写库都没发生**。

### 第二十八轮：两个声明式工厂各抄了一遍「给模型看的参数表」（收进 `AiWrite.kt::crudParams`）

`AiWriteBasicData.crud(...)` 与 `AiWriteMasterData.crud(...)` 各自把「目标实体 + 字段」两份规格
推成**参数表**，并且各写了一份 `AiFieldSpec.paramKind()`（8 个字段类型 → 4 种参数类型）。
两处推导**逐字相同**（不是"看着像"，是去空白后比对过），那份映射也逐字相同 —— 只有那些
额外旋钮（`geocodeFrom` / `allowTargetOnly` / `undoOnly` …）是 BasicData 那份多出来的。

**为什么它不只是"内部管道"**：`AiWriteAction.params` 全库**只有一个消费点** ——
`describeForModel` 里那句 `${p.kind.cn}`，也就是**贴给模型的说明书**
（「fee=运费（元）（必填，数字）」）。（`AiReadService` 里那几处 `action.params` 是**读**动作的
另一套参数类，带 `isId`，不是同一个东西。）
两份走散 = 同一种字段类型在两组动作里**两种说法**：模型按一处写、另一处不认，
而**两边都不报错**（表现只是"参数传得不对"）。

**收法**：`AiWrite.kt` 贴着 `CrudSpec` 新增 `crudParams(targets, fields)` 与
`AiFieldSpec.paramKind()`，两个工厂改成 `params = crudParams(targets, fields)`，各自那份私有映射删掉。
⛔ **撤回工厂 `AiWriteRestore.kt` 是合法例外**：它刻意 `params = emptyList()`（模型不该看到撤回动作的
参数）——红线里专门认这一条，不许被"统一"掉。

**等价性取证（不靠我说）**：临时脚本把 HEAD 里两份旧代码与现在唯一的一份**空白归一后逐字比对**
→ **4/4 相同**（推导 ×2、映射 ×2）；`git diff -U0` 净差异 72 行，**没有任何一个调用点被动过**
（`fields = listOf(...)` 一行都没变）。⇒ 每个动作的参数表、进而说明书里那句话，**一个字都没变**。
取证脚本用完即删（`_archive/_tmp_param_identity.py`）。

**新测试**：`AiWriteParamsTest` **4 条**（929… 现 **938 用例 / 0 失败**）——
8 个字段类型逐个钉住（新增类型必须一起改期望表）、参数表先目标后字段且**目标恒为文本**
（进 payload 的键名不许进参数表）、必填/提示/枚举取值原样带过、以及**说明书里那三句真实文本**
（`fee=运费（元）（必填，数字）` / `vehicle=车型（可选，枚举，取值 small/large/trailer）` /
`default=设为默认（可选，文本）`）。

**新红线**：`_tools/ai/_check_ai_write_params.py`。**清单自己算**——凡"造 `CrudSpec` 的文件"
就是声明式工厂（现 3 个，含撤回工厂）；每个必须走 `crudParams`（撤回那一份必须 `emptyList()`）；
「字段类型 → 参数类型」映射**全库只有一处**且把 `AiFieldType` 的 8 个取值**全部**映射到
（取值从 `enum class AiFieldType` 自己数）；两条内联旧写法不许再出现在别的文件；
`crudParams` 不许只推导一半；`describeForModel` 里那句 `${p.kind.cn}` 必须在（否则这份判断**没有读者**）。
反向验证 `_tools/ai/_reverse_verify_ai_write_params.py` **5/5**：内联退回 / 别处又抄一份映射
（没人调用、编译照过）/ 只推 targets / 漏 `DELTA` 并用 `else` 让编译器闭嘴 / 工厂参数成空表。

**真机**（模拟器 5556，本轮 APK）：AI 助手用 ASCII 说 `create place category named ABCD`
→ 模型**按说明书正确填参**（`分组名=ABCD`、`顺序=排在最后`）并弹出中风险确认卡
「新建地点分组：ABCD」→ **点取消，零写库**。
⚠️ 顺带纠正一条旧记忆：**5556 实测是派单员、5554 是货主**（与「5554=派单员」相反，以实测为准）。
⚠️ 未执行确认按钮：确认后的写入走的是 `CrudWriteHandler`（本轮没动），
所以真机验的是"提示词 → 模型 → 预览卡"这条链，**写入路径没有重复验一遍**。

**顺手**：`AiWrite.kt` 里那句注释举例原来写成「金额：必填，数字」（与真实渲染不符），改成真实文本。

静态检查 52 → **53 个脚本，53/53 全绿**。

### 第二十九轮：三个名册页各抄了一遍「草稿排序状态机」（收进 `common/CategoryRosterViewModel.kt`）

上一轮收的是那三条**纯规则**；这一轮收**用它们的那套状态机**。开销 / 运费 / 商品三页各自
写过一遍（每页约 45 行、共约 135 行）：`categories` 列表 + `loading/busy/loadError/error/notice/
editing/deleting/dirty` + `load()` + `moveTo/moveBy/revertOrder/saveOrder` + `submit` +
`askDelete/confirmDelete`。

**为什么它不只是"重复的样板"**：三份**已经走散过**——商品页的「建 / 改名 / 删除」之后是
**就地重刷**（自己 `clear`/`addAll`/`savedOrder`/`dirty`），另两页走 `load()`。就地那版
**不清 `loadError`**：之前加载失败过一次的页面，成功建完一条之后仍然整页停在错误页上，
用户看不到新建的东西。同一件事两种写法，谁都没报错。

**收法**：新增 `ui/common/CategoryRosterViewModel.kt`（`abstract class CategoryRosterViewModel<T>`）——
状态、`load/saveOrder/revertOrder/moveTo/moveBy/submit/askDelete/confirmDelete` 全在这里；
子类只交代「这一页是什么」（`idOf` / `nameOf` / `fetchAll` / `reorder` / `create` / `rename` /
`delete`，改名提示可用 `renamedNotice` 覆盖）。三页从 ~45 行降到 ~40 行**声明**（没有逻辑）。
顺带把 `moveItemTo`（四个页面在用、却住在商品页文件里）搬进 `ui/common/CategoryRoster.kt`，
并删掉只剩"换个参数写法"的商品专用包装 `moveCategoryTo`（它的唯一调用点已并入共用内核）。

**两个必须写下来的坑**：
1. ⚠️ **基类不在 `init` 里调 `load()`**，由子类写 `init { load() }`：基类 `init` 早于子类属性
   初始化，而 `viewModelScope` 是 `Dispatchers.Main.immediate` —— `launch` 的协程体会
   **同步**跑到第一个挂起点，那一刻子类还没准备好（本仓库在"语音播报只播一次"上踩过同一个坑）。
2. ⚠️ `notice / error / loadError / editing / deleting` **必须保持公开可写**：UI 会写它们
   （`OneShotSnackbar(onConsumed = { vm.notice = null })`、弹窗 `onDismiss = { vm.editing = null }`）。
   只有 `dirty` 收成 `private set`（只有共用内核能算它）。

**行为变化（一处，防御性的）**：商品页建/改名/删成功之后改走 `load()`（与另两页一致）——
它会清掉之前的 `loadError` 并沿用 `loading` 判据。原来的就地重刷会把"上一次加载失败"的红页
一直留着，看不到刚建好的分类。

**新测试**：`ProductCategoriesOrderTest` 补一条「按哪个字段认同一条由 `idOf` 决定」（证明这份搬运
与字段名无关，四个页面才敢共用）；原有 7 处断言从 `moveCategoryTo` 改为直接测泛化版
`moveItemTo`。单测 938 → **939 / 0 失败**。

**红线重钉**（`_tools/qa/_check_category_roster.py`）：判据现在算两件事——① 名册页 4 个（自己算：
调 `repo.reorder*Categories(` 的 UI 文件），其中**草稿页 3 个**（继承 `CategoryRosterViewModel`）；
② 草稿页里**不许**再出现那三条规则、共用内核里**三条必须都在**；③ 原来的三种内联写法扫描面从
"名册页"放大到**整棵 `ui/`**（只排除规则本体文件）；④ 反空转下限 + 共用内核的三个抽象口子都在。
反向验证 `_reverse_verify_category_roster.py` 改成 **4/4**：共用内核的撤销退回旧版 / 提交退回
`categories.map { it.id }` / `dirty` 退回内联比较 / 某一页不再继承内核（各由不同判据抓住）。

**顺手重钉的两条别人的锚点**（实现搬家后它们如实变红）：
`_check_ai_guardrails.py` 的「排序是本地草稿」锚点移到共用内核；
`_check_expense_page.py` 的两条断言从"这一页里有 `moveItemTo(` / `submittableIds(categories)`"
改成"这一页真的继承共用内核 + 规则在共用文件里"（并写明为什么不能改松）。
`_check_dead_code.py` 抓到两个文件里 5 条没用的 import（状态机搬走之后空出来的），已删。

**真机**（模拟器 5556 = 派单员，本轮 APK）：开销管理 → 分类管理 → 点某行「下移」→
「撤销改动 / 保存顺序」出现 → 点「保存顺序」→ 两个按钮消失（`dirty` 归零）→
**到库里核对：`expense_categories` 的顺序真的翻了**（货损=0、其他=1，原来是反的）→
再「上移」回去并保存一次 → **库里恢复原样**（其他=0、货损=1）。
这条走的正是被收进共用内核的 `moveTo`/`moveBy` + `saveOrder`（本轮唯一需要写库的一条路），
而且**顺序复原**，没有留下数据变化。

**顺手修掉发布闸门的一个假红**（`_tools/deploy/check_phone_apk.py`）：它读 BuildConfig 时
**写死** `phone/debug`，于是 `--apk` 指向 `phone/release` 时，拿 debug 变体的
`http://10.0.2.2:8000` 去判 release 包 → **一个完全正确的真机包被判「连的是模拟器地址，重打」**，
紧接着那句"dex 里找不到 10.0.2.2"又自相矛盾。现在变体**从包路径推**，两个方向都验过：
release 包 ✅ 可以发、旧的 debug 包照样 ❌（真红还在）。

静态检查 53/53 全绿。

### [2026-09-21 01:0x →] 会话：**退货申请（货主申请 → 派单员实际执行）**（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）

**用户需求（原话）**：「批发商……他要进行退货，他**可以直接在订单上**作退货。然后我们的那个派单员，
他会接到一个**通知**，这个时候派单员就会去帮他进行一个退货的操作。**派单员进行完了之后，整个才进行
库存才会发生一个改变和变动**。也就是说**批发商只是一个申请，派单员才是实际性的操作**。」
＋「同时**货主的 AI 可以代替货主进行申请退货**」。
两个拍板：**所有货主都能申请**（不只批发商）、**数量锁死**（申请多少就退多少，派单员不能改）。

**⛔ 不变量（这个功能的全部意义）**：申请阶段**只写一张申请单**——账本、库存、`order_products.returned_quantity`、
订单状态、现金流水**一个都不动**（`rbac.py` 当初不给货主退货权的理由原样成立：那份账要有第二个人核对）。
执行的唯一入口仍然是 `services/order_return.py::return_order`（⛔ 没有第二条退货路径）。

| 我改的 | 内容 |
| --- | --- |
| `backend/app/models/order_return_request.py`（新）| `order_return_requests` + `_lines`（软删、明细跟父走）|
| `backend/app/models/enums.py` | `ReturnRequestStatus` + 三个审计动作码（申请/驳回/撤回；办理那条复用 `ORDER_RETURN`）|
| `backend/app/core/rbac.py` | 新增权限点 `ORDER_RETURN_REQUEST`（**只申请**）；⛔ 与 `ORDER_RETURN`（**只派单员**）分开是本轮的核心 |
| `backend/app/services/order_return_request.py`（新）| submit / withdraw / reject / fulfill（fulfill **必须**调 `return_order`，数量取自申请单）|
| `backend/app/api/v1/return_requests.py`（新）| 6 个端点（货主 3 + 派单员 3，**分开两个权限点**，读目录才能正确反推角色）|
| `backend/app/schemas/return_request.py`（新）、`models/__init__.py`、`api/v1/router.py` | 出参/注册（`status_label` 中文名由**后端**给）|
| `backend/app/services/message_center.py`、`push_events.py` | 三个消息发布者：提交→**全体派单员**；办理/驳回→**那一个货主**（带理由/金额）|
| `backend/tests/test_return_request.py`（新，14 项）| ★「申请什么都不动」前后快照对比、越权 403、撤回后办不了、余量变小拒绝且**申请仍是待处理** |
| `_tools/qa/_probe_return_request.py`（新）| **打真后端**走全流程（申请不动货 → 通知到位 → 办理后库存/账本才变）|
| AI 侧（同一条线）| `AiWriteReturnRequest.kt`（4 个动作）+ `AiWriteReturnRequestHandlers.kt`（4 个处理器）+ 数据源 6 方法；货主 `apply/withdraw`、派单员 `reject/fulfill` |
| `AiWrite.kt` | 新字段 **`AiWriteAction.roles`**：`memberOnly` 不够用（派单员拿的是"全表减会员专属"，会把货主那两条一起拿走 → **两张点了必然失败的卡**）|
| `_tools/ai/_check_role_parity.py` / `_check_ai_guardrails.py` | 角色规则字面量跟着改（`roles` 两个方向都过），并新增"解析源码里的 `roles`"作为第二实现 |

**跨线记录（我动了别人的东西，都在这里交代）**：
- `_tools/ai/_gen_ai_toolmap.py`：新增「`_read_coverage.EXCLUDED` 写了不做的端点**不进工具表**」。
  ⚠️ 起因：我重跑一次生成器，把工具表从 **161 端点刷到 189**，顺带把**别的会话刚加的 3 个 GET**
  （`expense_categories.list_categories` / `freight_categories.list_categories` / `freight_templates.quote_freight`）
  塞进了 AI 读能力清单，而 `_read_coverage` 里已经写着"这三个不给模型读" → 两个检查直接互相打脸。
  现在出处只有一个（那张理由表），生成器读它、照它过滤。
- `docs/ai/ai_toolmap.json`：**重跑生成器**（186 端点）＋手工补 `return_requests` 模块的 2 条读动作说明；
  `docs/ai/ai_read_catalog.json` / `AiReadCatalog.kt` 一并重生成（`return_requests` 只读 2 条：货主看自己的、派单员看待办）。
- `_tools/qa/_check_order_return.py`：那条「货主矩阵里没有退货权限」的判据原来是**裸子串** `ORDER_RETURN`，
  被新的 `ORDER_RETURN_REQUEST` 命中 → 改成 `ORDER_RETURN\b`（并写明为什么不能删货主那条正确的申请权）。
  ⚠️ 同时：`rbac.py` 货主那一段的注释里**不写**那个权限点的完整名字（判据就在这一段里搜）。
- `_tools/qa/_check_audit_coverage.py`：新增 `return_requests.py` 的豁免条目（**不是不记日志**，
  是日志写在服务层同一个事务里；在端点再写一次就是双重记账）。
- `ui/dispatcher/ReportCenter.kt`：补三个动作码的中文名（申请退货 / 驳回退货申请 / 撤回退货申请）。
- `ui/**`：货主端「申请退货」入口 + 我的退货申请页、派单端待办页、`Modules.kt`/`Routes.kt`/`NavGraph.kt`
  各加一格（**由子代理 `82d9d112` 按规格实现，本会话验收**）。

**子代理交付：退货申请 UI（子代理）**（DSH `82d9d112-d2e9-4365-a63b-a9574399cc6a`，2026-09-21 01:2x 起）

只做**界面**，不新增 API 层代码（`AppRepository` 那 6 个方法直接用）；共享文件只做**追加**：

| 我改的 | 内容 |
| --- | --- |
| `ui/shipper/ShipperOrdersViewModel.kt` + `ShipperOrdersScreen.kt` | 订单卡片上的「申请退货」（只在**已送达 + 还有可退量 + 没有待处理申请**时出现）+ 同形弹层（逐行勾数量 / 全部勾满 / 备注选填）；已有待处理申请时按钮变「退货申请中」**不可点** + 「撤回申请」 |
| `ui/shipper/ShipperReturnRequestsScreen.kt` + `ShipperReturnRequestsViewModel.kt`（新） | 「我的退货申请」页：待处理/全部两档、驳回原因、办理人与时间、撤回（二次确认写清"撤回不是删除"） |
| `ui/dispatcher/DispatcherReturnRequestsScreen.kt` + `DispatcherReturnRequestsViewModel.kt`（新） | 派单端待办页：全部/待处理、办理退货（二次确认写清"这一刻库存账本才变 + 数量锁死"）、驳回（理由必填） |
| `ui/common/ReturnRequestChip.kt`（新） | 申请单状态胶囊：**中文名一律用后端 `statusLabel`**，本地只管颜色（两端共用一份，避免两处各写一套映射） |
| `ui/nav/Routes.kt` / `NavGraph.kt` / `Modules.kt` | 追加两条路由 + 两个 composable + 两端工作台各一格「退货申请」（`0xFFB3492F`） |

⚠️ **跨线核对（`_tools/**` 我不碰，只读跑了一次）**：`_tools/ai/_app_feature_coverage.py` 的 `MAP`
里**已经有** `"退货申请"` 那一行（本会话补的），所以新模块与 AI 能力对得上；
复跑 `--check` = "App 模块 29 个 / 读能力 27 组 / 写能力 13 个域，映射自洽"，**不需要再动**。

**子代理自验结果（2026-09-21 01:2x）**：
- `compileEmuDebugKotlin` → **BUILD SUCCESSFUL**（只有 `Icons.Filled.*` 的 deprecation 警告，
  与仓库既有的 `ReceiptLong`/`ListAlt` 同一类）；
- `testEmuDebugUnitTest --tests "*ModulesEntryTest*"` → **13 tests / 0 failures / 0 errors**；
- 只读复跑（不改任何文件）：`_check_ai_guardrails.py` 1098 项通过、`_check_ledger_dashboard.py`
  138 项通过、`_check_order_return.py` 98 项通过、`_check_client_contract.py` 49 项通过；
- 新色 `#B3492F` 自己算过：派单端全网格最小 RGB 距离 **74**、货主端 **83**（判据 ≥60），
  最亮通道 70.2%（在 `_check_ledger_dashboard.py` 的 66~100 色带内）。

**明确不碰**：`ui/driver/**`、`ui/dispatcher/ExpensesScreen.kt`、派单员账本页、`freight_*` 那一线
（`_gen_ai_toolmap.py` 只加了上面那一段过滤，别的没动）。
（子代理延续同一条「不碰」清单 ＋ 不碰 `backend/**`、`_tools/**`、`android/**/ai/AiWrite*.kt`、
`AiReadCatalog.kt`、`docs/ai/**`、`android/app/src/test/**`。）

**UI 交付之后我又补的三件（本会话，2026-09-21 01:4x）**：
1. ⛔ **堵掉"同一批货被退两遍"**（`backend/app/api/v1/orders.py::return_order_endpoint`）：
   申请还挂着时**不许**在订单管理里走那条直连退货。理由：货主申请退 2 件（共 5 件）→ 派单员手工退了 2 件
   → 申请仍是待处理 → 他再点「办理」时余量 3 ≥ 2、**校验全部通过** → 库存多补、账本多红冲、可能多退一笔现金，
   而**谁都不报错**。取 fail-closed + 给出路（"请到「退货申请」里按它办理，或先驳回"），
   ⛔ **不是**"悄悄把申请标成已办"（那会把"申请 2 件、实退 3 件"的真实差异盖掉）。
   AI 侧同步：`ReturnOrderHandler.prepare` 先读一次待处理申请，避免发一张点了必然失败的卡。
   新增回归 `test_return_request.py::test_direct_return_is_blocked_while_a_request_is_pending`。
   ⚠️ 顺带改了一条老用例：`test_fulfill_refuses_when_cap_shrank_and_stays_pending` 原来靠"先手工退一批"
   造出"余量变小"，那条路现在堵了 → 改成**直接在库里**把那几件记成已退（模拟并发/别的路径改过），
   验的仍是同一条不变量（办失败 → 申请必须留在待处理）。
2. **误操作的答案**（`android/.../ai/AiRevert.kt`）：四个新动作逐条写进 `UNDO_NONE`
   ——申请/撤回/驳回/办理**四句各不相同**（申请阶段什么都没动、撤回后要重新申请、驳回已推给货主、
   办理撤不回来），照 `MY_LEDGER_SETTLE` 那个先例；⛔ 文案里不许有 Markdown 星号（红线）。
3. **单测**（`android/app/src/test/.../AiWriteTest.kt`）：7 条新用例（申请卡片必须写"现在都不动"、
   提交只调申请接口不调退货、已有待办时拒绝、撤回、办理数量锁死且不带 quantity、驳回必填理由、
   越权双向 + 所有货主都能申请），并修了两条被 `roles` 改动影响的老断言
   （`新动作默认只给派单员` 的算式 + 反向钉住"点名不给派单员的只有退货申请那两条"）。
   新增真机/真后端工具：`_tools/qa/_probe_return_request.py`（打真 HTTP 走全流程）、
   `_tools/qa/_order_facts.py`（打印一张单的账实：库存/账本/已退/申请单/流水）。
4. ⛔ **跨线修了一个全 App 的 bug：一次性提示条根本不显示**（`ui/common/Components.kt::OneShotSnackbar`，   **47 处调用**）。真机 E2E 连拍 30+ 帧（逐帧 MD5 相同）实证：操作成功、但界面上从来没有提示条 ——
   本功能的「已提交退货申请…现在库存和账本还没有变化」也因此在真机上抄不到。
   根因（读源码确认）：2026-09-18 为修"切页回来又冒一次"把**消费挪到显示之前**，
   而 `message` 正是 `LaunchedEffect(message)` 的 **key** —— `onConsumed()` 把它置空 → key 变 → 协程被取消
   → 紧接着那句 `showSnackbar` 要么没跑、要么刚注册就被撤掉。**两个旧 bug 是一对**：
   显示在前＝重放、消费在前＝不显示；只做一件必然回到另一个。
   修法：**先消费**（保住"不重放"）＋ **显示交给 `rememberCoroutineScope()`**（生命周期是 Composable 本身，
   不随 key 变化取消，离开页面自然取消）。已 `assembleEmuDebug` + 905 条单测通过，正在真机复验。
   ⚠️ 这条**不是本功能引入的**（2026-09-18 那次改动起就存在，只是没人逐帧看过界面），
   按仓库"谁发现谁声明"的规矩记在这里，动的是 `ui/common/Components.kt`。

**规则反了一次（2026-09-21 02:1x，用户拍板，以本条为准）**：
用户原话：「**把规则改成派单员退货之后，自动取消申请**，然后它对应的数据发生改变，状态变成已退货多少多少」
＋「如果是派单员的话，就不需要去修改这个按钮。**除了派单员之外的所有人，他想退货只能申请退货**」
＋「（通知）到消息中心……其实**本来就要做到直达的**」。

| 改动 | 内容 |
| --- | --- |
| `backend/app/models/enums.py` | 新增 `ReturnRequestStatus.CLOSED`（中文「已关闭（派单员已直接退货）」）＋审计码 `ORDER_RETURN_REQUEST_CLOSE` |
| `backend/app/services/order_return_request.py` | 新增 `close_by_direct_return()`：把待处理申请转 `CLOSED`，并算出**「申请了什么 / 实退什么」的对照说明**（一致/不一致都要如实写） |
| `backend/app/api/v1/orders.py::return_order_endpoint` | ⛔ **那次 400 fail-closed 已删除**：直连退货照旧允许，退完**自动关闭**那张申请（在 `db.commit()` **之前**，删掉就等于"同一批货退两遍"复活）＋给货主发消息 |
| `message_center.py` / `push_events.py` | 新 `publish/push_return_request_closed`（标题「退货申请已关闭（派单员直接退了货）」，含金额与对照说明） |
| AI `ReturnOrderHandler` | 由"拒绝"改成**卡片上写一行**：这一单有张待处理申请，退完会自动关闭并通知货主 |
| `ReportCenter.kt` | 补 `ORDER_RETURN_REQUEST_CLOSE` 的中文名 |
| `backend/tests/test_return_request.py` | 旧用例 `test_direct_return_is_blocked_while_a_request_is_pending` **换成** `test_direct_return_closes_the_pending_request`（直连必须成功 + 申请必须转 closed + 库存/金额变了 + 货主收到消息 + **再点办理必须 400**）；新增 `test_direct_return_notes_the_difference_from_the_request`（件数不一致时差异必须出现在消息里）。⛔ 两条用例的存在意义就是"钉住现在跑的是哪一条规则"，别再翻回去 |

⚠️ **顺序上的一条硬约束**（写在这里因为它是这次改动最容易改坏的地方）：
"直连退货 + 自动关单"之所以**不会**退两遍，靠的就是**关单**这一步 —— 申请一旦不是 `pending`，
`fulfill` 会被 `_check_pending` 拒。所以 `close_by_direct_return(...)` 必须留在 `db.commit()` **之前**
（红线与其反向验证钉着这一条）。

**追加（2026-09-21 02:3x，本会话的子代理 `e279eb51-777a-485a-9100-456e168c70cf`）：消息中心「直达」退货申请 ＋ 红线与审计工具同步**：

三件互不相干的小活。⛔ 后端、AI、`ReportCenter.kt`、`backend/tests/**` 一个字节都没动（上面那条"规则反了一次"是主会话做的）：

| 我改的 | 内容 |
| --- | --- |
| `ui/messages/NoticeRouting.kt`（新） | **唯一一处**按通知 `type` 决定去哪一页的纯函数：派单员收 `order.return_request` → 派单端待办页；货主收 `.done` / `.rejected` / **`.closed`** → 货主端「我的退货申请」；都带 `?focus=<申请单号>`（payload 的 `request_id`）。⚠️ 必须**同时**判角色：派单员的消息列表是全局视图（里面混着发给货主的消息），照 `type` 跳会把他送进货主那一页 → 必 403（"点了必然失败"）。角色用 `cachedRole()` 的**原文**比较，⛔ 不过 `Role.fromKey`（它对空串回落成 SHIPPER） |
| `ui/messages/MessagesScreen.kt`（只追加一个参数 + 一处分支） | 点通知：认得出类型就直达（`onOpenReturnRequest(route)`），认不出**退回老行为**（有 `order_id` 就开订单详情）—— 不留"点了没反应"的位置 |
| `ui/nav/Routes.kt`（追加两个函数）、`NavGraph.kt`（两条路由加可选 `?focus={focusId}`） | `Routes.shipperReturnRequests(id)` / `dispatcherReturnRequests(id)`；工作台网格那种不带 focus 的入口照旧走原来的常量（`defaultValue = 0L`） |
| `ui/common/ReturnRequestFocus.kt`（新） | 「把要定位的那一条排到最前」的纯函数 + `found` 标志（到底有没有找到） |
| 两页 Screen + VM（各追加参数与状态） | `focusRequestId` / `focusNotice`：**排到最前 ＋ 一枚「消息里点进来的这一条」胶囊 ＋ 列表滚到它**；带 focus 进来**先切「全部」档**（办完/驳回/关闭之后那条已经不在「待处理」里，在待处理档里找必然落空 → 会假报"没找到"）；列表里**没有**它时**照常显示全部**并加一行「没找到那条退货申请（可能已经被处理掉了），下面是全部。」—— ⛔ 不白屏、不假装定位到了 |
| `_tools/qa/_check_return_request.py` | §7 整组改成**新规则**：① 直连退货**允许**（旧的 400 拦截必须已不在）；② 必须真的调 `close_by_direct_return(...)`，且**在 `db.commit()` 之前**（顺序判据）；另加 `CLOSED` 状态与中文名、`ORDER_RETURN_REQUEST_CLOSE` 审计与审计页中文名、`publish_return_request_closed` 三跳接通。§0 钉的用例名跟着改成 `test_direct_return_closes_the_pending_request`（旧名字在测试文件里只剩一句注释，钉它等于钉一个不存在的用例）。123 项全绿 |
| `_tools/qa/_reverse_verify_return_request.py` | 注入⑥ 由"删掉 400 那一段"改成"删掉 `close_by_direct_return(` 这一次调用"；**新增注入⑥b**"把它挪到 `db.commit()` 之后"（证明顺序判据真的在看顺序）。13/13 全被抓到 ＋ 逐字节还原 |
| `_tools/fuzz/_fuzz_invariants.py` | 修掉那条**长期红**的库存判据：`inventory_movements` 上挂着**两条线**（`source='ORDER'` 订单实扣 = 负数、`source='WAREHOUSE'` 到仓入库 = 正数，见 `services/warehouse.py` 与 `models/inventory.py` 那句「正数入库 / 负数出库」），旧判据没有 `source` 过滤，把 +20 与 −20 加在一起 → "相等"永远不成立。现在按 source **拆成两条**硬的（各自 == 该单商品数量合计）。本地校准：出库线 2/2、入库线 39/39 一致，跑出 0 缺陷 |

⛔ 这次**没有**跑真机/模拟器（只到 编译 + 单测 + 静态检查）："点通知直达"这条链路的端到端复验还没做。




### [2026-09-21 1:2x →] 会话：**"闪两下"——账本类页面改成「先盘点、再取数」**（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）

**用户报的毛病**：「我在点击**我的账本**的时候，它会**闪两下**再跳到「前天」……我在点击账本之前，
它就已经**提前盘点好了**：今天有账就直接出今天，今天没账再换前天。其他派单员那些账本界面
基本上也是这个逻辑，**闪两下已经不行了**，不美观，且占用性能。」

**根因（老写法本身）**：`init` 里 `switchPreset(TODAY)` 先**取一次数**（今天多半是空的 → 画一版空态），
再异步退档到「前天」→ 最坏画三帧（今天·加载 → 今天·空态 → 前天·有数据），还白发一次注定被丢掉的请求。
**"占用性能"就是那个请求。**

**改法（一份共享实现 + 每页三行）**：
- `ui/common/DatePresets.kt` 新增 **`suspend fun pickWindow(ladder, hasData)`**：只**探测**（每档 `limit=1`），
  返回"真有数的那一档"（都没有 → 全部）；
- 每个页面加一个 **`windowSettled`** 门：定下来之前整页 `LoadingBox()`，药丸上的字先写「…」
  （这时写任何档位都是假话），**一次都不画错窗口**；
- ⚠️ 探测是网络请求（来回一秒），所以 `if (!userPickedPreset)` 这道门**必须留着** ——
  用户在探测期间自己挑了档位，再按阶梯结果 `switchPreset` 就是抢方向盘；
  用户一表态就把 `windowSettled` 也置真（免得他挑完还要再 loading 一下）。

**改到哪几页**（⚠️ **跨了两条线**，按用户"其他派单员那些界面也一样"的要求一并改了）：

| 文件 | 谁的活 | 改法 |
| --- | --- | --- |
| `ui/shipper/ShipperLedgerViewModel.kt` + `ShipperLedgerScreen.kt` | **我** | 用 `pickWindow` + `windowSettled`；删掉本地那份 `pickDefaultPreset` |
| `ui/dispatcher/DispatcherLedgerViewModel.kt` + `DispatcherLedgerScreen.kt` | 派单员账本线 | 同上（四个账本档位共用这一个 VM） |
| `ui/dispatcher/ExpensesScreen.kt` | 开销管理线 | `start()` 不再先 `load()`；同样加门 |
| `ui/driver/DriverFreightViewModel.kt` + `DriverFreightScreen.kt` | 司机账本线 | 同上（用司机自己那条更长的阶梯） |
| `ui/driver/DriverOrdersViewModel.kt` + `DriverOrdersScreen.kt` | 司机任务线 | 用户点头后补的：它**没有**"先按今天拉一次"那一步（盘点发生在切到「已完成」那一栏），所以不闪两个窗口；**但它缺一个门** —— 切过去那一瞬屏幕上还挂着上一栏（进行中）的单。现在 `selectTab(1)` 先 `windowSettled=false`，盘点+取数完再开闸，药丸同样先写「…」 |
| `ui/common/DatePresets.kt` | 共享 | **只加** `pickWindow`，已有档位/区间一个字没动 |

**红线与反向约束一起改了**：`_tools/qa/_check_ledger_dashboard.py` 原来钉的是**旧的（会闪的）写法**
（`switchPreset(TODAY)` + `launch { pickDefaultPreset() }`）——现在改成钉新不变量：
① **不许**再出现"先按今天拉一次"（`c.absent`）；② 必须走 `pickWindow`；
③ 盘点期间页面挡住不画（`!vm.windowSettled -> LoadingBox()`）；④ 用户表态后不许被拽走。

**真机验收（5554）**：重装后进「我的账本」，logcat 里的请求序列是
`limit=1`（今天）→ `limit=1`（昨天）→ `limit=1`（前天）→ **`limit=500`（只此一次，09-18）** → settlements。
**旧写法在第一步之后还有一次 `limit=500`（今天）** —— 那一次就是"闪两下"和白花的性能。
截图 `_archive/ledger554-v4-qiantian.png`：一进去就是「前天」带数据，没有中间那一帧。
收尾：`_check_all.py` **53/53 绿**、单测通过、APK 编译通过。

**⚠️ 没改的一处（登记一下）**：无 —— `ui/driver/DriverOrdersViewModel.kt`（司机「已完成」）最初没动，
后来用户点头补上了（见上表最后一行）。它的门写成 `vm.tab == 1 && !vm.windowSettled`
（第 0 栏「进行中」不涉及日期窗口，一进来就该画）。

---

### [2026-09-21 0:4x →] 会话：**AI 能力 = 角色能力**（两个货主 AI 拆开 + 真模型审查）（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）

**任务**（用户 2026-09-21 第七轮）：「AI 也要增加相应的功能。现在 AI 也会分成 2 个：一个是**普通货主**、
一个是**批发商货主**的 AI。相应的权限和能力跟对应角色的**所有功能和权限进行统一** —— 这个角色能做什么
功能、做什么事情，AI 要赋予相应的能力……但是他**不能越权**：批发商没有的功能 AI 也做不到；
**普通货主他做不到的事情、也就是他手机做不到的事情，AI 也做不到**。API key 已经写下来了，
全都用那个进行审查」（＝`~/.dsh/.credentials.yaml` 的 `DEEPSEEK_API_KEY`）。

**交付物（都已落地并跑绿）**

| # | 东西 | 说明 |
| --- | --- | --- |
| ① | `_tools/ai/_check_role_parity.py`（新，16 项） | **三方对账**：角色 ×（后端授权 / App 界面在调 / AI 给了）× **双向**断言。三份清单全部**现算**（`gen_endpoint_index.collect` + `ROLE_PERMISSIONS` / `Apis.kt→AppRepository→ui/**` / `AiWrite.kt→处理器→repo→端点`），不读任何签入的表 |
| ② | `_tools/ai/_reverse_verify_role_parity.py`（新，5/5） | 反向验证：注入越权 / 缺能力 / 拆注释判据等 5 种破坏，逐条变红 + **逐字节还原** |
| ③ | `_tools/ai/_audit_role_ai.py`（新，13 条探针） | **真 DeepSeek key** 驱动的双向审查：正问（该办的必须去申请）+ 反问（不该办的必须拒绝、不许换说法再试）。已进 `_check_all.py`（53/53 全绿） |
| ④ | `ai/AiActor.kt`（新）+ `AiWrite.kt` / `AiReads.kt` / `AiTools.kt` / `AiWriteService.kt` / `AiRolePrompt.kt` / `AiContainer.kt` | 「**这一次是谁在用**」＝角色 + 是不是批发商货主。`AiWriteAction.memberOnly` 把「核销/撤销/恢复」只给批发商货主（**派单员也拿不到** —— 那本账后端只认货主角色）；读侧目录新增 `memberOnly`（生成器算） |

**这一轮查实并修掉的真问题（每条都有证据）**

1. **货主的 AI「帮我下一单」根本用不了**（高）：`CreateOrderHandler` 无条件走 `ds.searchShippers()`
   → `GET /users`，而那个端点对货主是 **403**（角色门 `USER_MANAGE`＝派单员）——
   **真后端实测**：`{"detail":"无操作权限…"}`。现在按 `ds.currentRoleKey()` 分叉：货主走"给自己下单"，
   连 `shipper_id` 都不传（后端对货主是 `target_shipper_id = current.id`，传了反而 400）。
2. **货主点自己那张删除卡的「撤回」会被自己的权限门挡掉**：`address/location/contact.restore`
   三条（`AiWriteService` 早就实现了）**不在** `SHIPPER_ACTIONS` 里，而 `allows()` 是 preview 与
   撤回**两条路共用的门** → 违反用户 2026-09-19 定的「软删 + 必须有恢复路径」。
3. **手机上能做、AI 不能做的三条**：删自己终态的单（`orders.soft_delete`，与订单详情页同一判据
   `OrderStatusModel.SHIPPER_DELETABLE`）、删自己的消息（`notifications.delete`）、单条消息标已读
   （`notifications.mark_read`）。⚠️ `_show_role_caps.py` / `_check_ai_guardrails.py` 里原来把
   `notifications.delete` 写成"删除别人的消息"——**那条理由本身是错的**（后端只允许动自己的，动别人 404）。
4. **派单员能看见货主自己那本账的动作**（一类"能看见但一定失败"的卡）：`forRole(DISPATCHER) = ALL`
   从不排除 `memberOnly`。
5. **13 条真模型探针**：普通货主拒绝派单/核销/改价且能下单建地址；批发商货主能核销+撤销核销、
   拒绝派单/改价 —— 两个货主 AI 的行为差异与手机上的界面差异**逐条对上**。

**⚠️ 给别的会话的两件事**

- 我**没有**碰你们在建的 `freight-categories` / `price-freight`（`_check_role_parity.py` 与
  `_write_coverage.py` 都会报它们"还没有 AI 动作"）；`_check_all.py` 现在 53/53 绿，是因为
  那两个端点**还没有界面在调**（我的判据是"后端允许 ∩ 界面在调"），你们接上界面之后它会红，
  那时按规矩补动作或写"不做"的理由即可。
- 我改了这几个共享文件的**行数**（都在 `ai/` 包内、且是我这条线）：`AiWrite.kt`（`memberOnly` 字段 +
  白名单 +6 条）、`AiWriteService.kt`（`actorProvider` + `currentRoleKey`）、`AiTools.kt`（`actor`
  取代 `role`：`AiToolset` 的成员属性改名了）、`AiRolePrompt.kt`（`brief/settingsSummary` 收 `AiActor?`）。
  **`AiToolset.role` → `AiToolset.actor` 是一次破坏性改名**，谁的测试替身实现了 `role` 要跟着改
  （我已改 `AiAgentLoopTest.FakeTools`）。你们说的「等收工再摘 `billing_mode`/`salary`」那条不受影响。

**⚠️ 本轮自己踩的坑（写下来免得别人再踩）**

- **`Get-Content -Raw | Set-Content` 往返改 `.kt` 会把中文写坏**：实测 `AiSettingsViewModel.kt`
  被改成混合编码，**228 处中文被替换成 `?`、还吃掉一批换行**（文件从 576 行变成 530 行）。
  已 `git checkout` 还原并重做改动。**改带中文的源码只用 edit/write 工具或 Python（显式 utf-8）**。
- **Python 改写源码要注意换行**：`read_text()` 走通用换行（`\r\n`→`\n`），而 `write_text()` 默认按
  `os.linesep` 翻译 —— 两者叠加会把 LF 文件变 CRLF。反向验证脚本第一版就是这么"还原不一致"的，
  现在显式按原文件的换行写（`newline="\r\n" if crlf else "\n"`）。

**⚠️ 模拟器 5554 一度被我搞挂，已冷启动恢复（给下一个用 5554 的人）**：重装 APK 后我跑了
`adb shell cmd package compile -m speed -f com.tapmoay.sorders`，随后 5554（AVD 名 **`SOrdersAI`**，
启动参数 `-avd SOrdersAI -port 5554 -no-snapshot-load`）的 system server 起不来了
（`cmd: Can't find service: activity`、截图 "Transport endpoint is not connected"，
而 `getprop sys.boot_completed` 又是 1 —— 半启动状态）。**修法（已用过，15 秒恢复）**：
`adb -s emulator-5554 emu kill` → `D:\APPS\sdk\emulator\emulator.exe -avd SOrdersAI -port 5554 -no-snapshot-load`。
⚠️ 结论：**别在内存吃紧的模拟器上跑 `cmd package compile`**（后端/单测/静态检查都不需要它）。

**真机验收（5554 冷启动之后）**：AI 助手 → 设置 顶上那段**能力声明**逐条对上两个货主 ——
`is_member=1` 时**能查、能改里都有「我的账本」**（截图 `_archive/ai554-settings-member.png`）；
临时置 0（`update users set is_member=0 where phone='13800000002'`）重启 App 之后
**两边都没有「我的账本」**了（截图 `_archive/ai554-settings-plain.png`）；**已恢复 `is_member=1`**。
—— 这就是用户要的"两个货主 AI"在手机上看得见的那一面。

**⚠️ 1:0x 追加（用户当场拍板的一条收紧）**：用户说「**他不能删他的订单**……凡事有关订单信息，
他的 AI 是不能做的。**货主和批发商都一样，除非是那个已撤销的订单信息，这个是可以删的**」。
所以 AI 侧新增 `OrderStatusModel.SHIPPER_AI_DELETABLE = {CANCELLED}`（**只认已撤销**），
`SoftDeleteOrderHandler` 对货主改用这一条，拒绝话术与卡面都写清"为什么只有这一种能删"
（已送达是**已经发生过的一趟生意**，账本流水/司机账单/库存都挂在它上面）。
⚠️ **界面上那个「删除订单」按钮仍然保留**（已送达也能删）—— 那是 2026-09-04 定的数据保留策略，
且是用户自己点、看得见上下文；**"AI 比界面严一档"是用户明确要的**，所以两处**不能合成一个常量**
（`OrderStatusModel` 里两段注释互相指路）。
派单员那条路**一个字没动**（任意状态都能删）。单测：
`货主的 AI 只删已撤销的单，已送达的单不替他删`（两个货主身份各断言一次 + 派单员对照）。
收尾：`_check_all.py` **53/53 绿**、单测 **898 项 0 失败**、APK 编译通过。

---

### [2026-09-21 0:3x →] 会话：运费模板分类 + 计费规则按分类 + 运价自动匹配/待定价（DSH `session-faa17a77-515b-4bcb-bd47-fddae0129342`）

**任务**（用户 2026-09-21 口述六件事 + 三个确认问题的回答）：

1. **司机管理编辑页与计费规则冲突**：「司机管理他现在有固定工资和按单计费，但是后面又加了一个计费规则，
   其实**计费规则就已经包括他们上面的这个**」→ 那两个老字段要去掉；
2. **运费模板加一套自己的分类**（用户答复：「复用商品管理的那样子的形式……**他那个运费模板是有自己的一套分类的**，
   只是我们复用他那个代码和方法」）+「一个模板可以有多个分类」；
3. **运费模板按地点库的路线定价**（本来就是 `route_id → shipper_addresses` 线路，这一轮把"拉取路线"做扎实）；
4. **计费规则的按单计费两种**：① 所有单统一价/统一提成；② **按分类匹配**
   （用户答复选的是「**给司机算钱**：计费规则里多一张「分类 → 每单金额/比例」表」）；
5. **没匹配到运价不算异常单**（用户答复选的是「只标**运费待定价** + 自动进一个待定价列表，**不改异常标记**」）
   → 派单员手动定价 → **自动沉淀**出对应的路线/地点 + 运费模板并绑定那个分类；
6. **运费模板卡片与计费规则卡片的信息更明确**。

**预计新增文件**（谁也别先建）：

| 文件 | 作用 |
| --- | --- |
| `backend/app/models/freight_category.py` | 运费分类名册（name + sort_order，照 `product_categories`） |
| `backend/app/models/freight_template_category.py` | 模板 ↔ 分类（m:n，一条价目可挂多个分类） |
| `backend/app/schemas/freight_category.py`、`backend/app/api/v1/freight_categories.py` | 增/改/删/排序（照 `product_categories` 那一套） |
| `backend/app/services/freight_pricing.py` | **运价匹配的唯一实现**（路线 + 分类 + 司机 → 价目，含"没匹配到"） |
| `backend/app/models/driver_billing_rule_category.py` | 计费规则的「分类 → 每单金额/比例」 |
| `android/.../ui/dispatcher/FreightCategoriesScreen.kt` | 运费分类管理（照 `ProductCategoriesScreen`） |
| `android/.../ui/dispatcher/FreightPricingScreens.kt` | 待定价列表 + 手动定价（沉淀） |
| `backend/tests/test_freight_pricing.py` | 后端测试 |

**改动的共享文件**（⚠️ = 别人也可能在看，一律追加式 + 记「交叉点」）：
`backend/app/models/order.py`（加运费分类两列）、`schemas/order.py`、`api/v1/orders.py`（派单带分类 + 定价端点）、
`api/v1/freight_templates.py`、`services/driver_pay.py`、`models/driver_billing_rule.py`、`schemas/driver_billing_rule.py`、
`api/v1/driver_billing_rules.py`、`core/schema_bootstrap.py`、`models/enums.py`（新审计码）、`api/v1/router.py`、`models/__init__.py`、
`android/.../ui/dispatcher/FreightTemplatesScreen.kt|ViewModel.kt`、`DriverBillingRulesScreen.kt|ViewModel.kt`、
`UsersManageScreen.kt|ViewModel.kt`、`DispatcherPoolScreen.kt|ViewModel.kt`、
`data/remote/api/Apis.kt`、`dto/Dtos.kt`、`repo/AppRepository.kt`、`ui/nav/Routes.kt`、`NavGraph.kt`、
`_tools/ai/_write_coverage.py`、`_app_feature_coverage.py`、`_gen_ai_toolmap.py`、`ReportCenter.kt`（审计码中文名）、
`docs/PROJECT_MAP/08_CODE_LOCATOR.md`、`06_DESIGN_SYSTEM.md`。

**明确不碰**：
- 别人那条线：`shipper_ledger` / `ShipperLedger*` / `shipper_settle*`、司机端 `ui/driver/*`；
- ⚠️ **AI 侧那两个老字段（`billing_mode` / `salary`）本轮不动** —— 另一会话（`session-83da1ad7`，
  「AI 能力与角色能力对齐」）**正在整片重写 AI 写动作与角色能力**，`ai/AiWriteMasterData.kt` 是他们的在建文件。
  我这一轮只改 **App 界面**（司机编辑页不再给这两个框）；等他们收工我再把 AI 那两个字段摘掉，
  否则两个人同时在那个文件里改字段表，谁后写谁赢、而且是**静默**的。

**结论（已做完，2026-09-21 1:0x）**：六件事全部落地，**没有新增 AI 写动作**（新端点在 `_write_coverage.py` 里
写了「不做」的理由）。真机（emulator-5556 派单员）逐屏看过：

1. **司机编辑页**：只剩「计费规则（他怎么算钱就看这一项）」+ 一句兜底说明
   （「没挂规则 → 按车型的老口径兜底（大车司机）。要给他固定工资/计件/提成，请到工作台「计费规则」建一份再挂上」）；
   「固定工资」「计费方式」两个框**已删**，VM 也不再发 `billing_mode`/`salary`；
2. **运费分类**：真机上建了「蔬菜」，分类管理页显示「价目 N 条 · 计费规则 N 份」，运费模板页左边立刻多一格；
3. **运费模板页**：左分类栏 + 卡片（分类标签 + 车型 / **路线大字** / 价目名 / **¥ 大字** / 可用司机 / 备注）；
4. **计费规则的按分类**：弹窗里「每单金额怎么定 = 所有单统一 | 按分类」，选按分类后逐类填「每单 ¥ / 提成 %」；
5. **待定价**：运费模板页右上角入口 → 「没有待定价的单 / 已经派出去的单都有运费了……」；
6. 后端：`GET /freight-templates/quote`、`POST /orders/{id}/price-freight`、`GET /orders?unpriced=true`、
   `/freight-categories`（5 个）—— **匹配的唯一实现**在 `services/freight_pricing.py`。

⚠️ **测试抓到两个真 bug（都在匹配里，都是「不报错但算错钱」）**，值得记：
① `rank()` 原来把 `-t.id` 混进排序键 → 「同样优先」**永远不成立**，那段「多条候选 → 不猜」的分支是死代码
（配了两条同类价目照样挑一条，且挑得毫无理由）；② 「不知道司机是谁」时，绑了司机的价目被算成**不可用** →
待定价页会把「明明有价」报成「没有价目」。两条都已修，测试留在 `tests/test_freight_pricing.py`。

⚠️ **真机截图抓到一处字面星号**（分类管理页与待定价页的说明文字里写了 `**`，界面上原样显示）——
`_check_ai_guardrails` 的「界面层文案」那一条其实**报了**，是我只看了汇总行最后一条。已全部改成「」。

**第二轮（用户看完真机又点名两件，2026-09-21 00:0x）**：

1. **「价目归计费规则」**：「运费模板不会去匹配车型也不会匹配司机，匹配车型和匹配司机在计费规则中……
   这一目录就归这个计费规则，而这个规则在匹配对应的司机」+「勾选价值目就像商品界面，**可以全选本分类**，
   也可以单独勾」→ 新增 `driver_billing_rule_templates`（规则 ↔ 价目 多对多）；**价目表不再有车型/司机
   两段**（旧列留着但匹配不看它）；匹配改成**先按"这个司机的规则勾了哪几条价目"过滤**，再按路线 + 分类挑；
   规则编辑页多一段「用哪些运费价目」→ 打开**选品页那种选择器**（左分类栏 + 全选本分类 + 单独勾）；
   沉淀出来的价目**自动勾进这一单司机的规则**（否则"下次自动带价"是假的）。
   ⚠️ 顺带清掉了匹配里"司机/车型"那一维（候选集已经按规则过滤过，留着就是死代码）。
2. **卡片按钮靠左 + 信息区拉长**（用户：「删除和编辑的按钮不要放在右边放在左边，而且那个名字就是
   信息栏拉长一点往右拉一点」）→ 两张卡片（运费模板 / 计费规则）的按钮行都 `fillMaxWidth()` +
   `Arrangement.Start`，信息行也 `fillMaxWidth()`（不再由内容宽度决定）。

**第三轮（用户「你重启一下……我感觉你的那个卡片怎么还是跟原来一样的计费规则里的那些卡片」，2026-09-21 00:1x）**：

他看到的**确实还是旧界面** —— 模拟器上装的包是 15:59 构建的那一份，我上一轮改完只
`assembleEmuDebug` 而**没 `install`**（`lastUpdateTime` 15:59 vs APK 23:59 对不上）。重装 + 重启后新界面在。
但顺着这条线查出一个**真的没做完**的地方，记下来：

1. **勾了价目只留在界面上，没进库**：`driver_billing_rule_templates` 当时是 **0 行** —— 我在选择器里
   "全选本分类 8 条"只截了图，**没点保存**。所以卡片上那行价目永远不显示，看起来和改之前一模一样。
   重做一次「勾 8 条 → 保存 → 查库」确认链路通（`rule 7 → template 1..8`，8 行落库）。
   ⚠️ 教训：**界面看起来对 ≠ 数据落地了**；凡是"改了要能看见"的验证，必须**回库里核对一次**。
2. **卡片把价目全名全列**（8 条 → 占 4 行、卡片被撑高一倍，而且**一个价格都看不到**，勾 20 条更没边）
   → 收敛成 `价目 8 条：惠州江北 → 东莞樟木头 ¥62.00、惠州仲恺 → 深圳龙岗 ¥88.00 等`
   （**条数 + 前两条 + 价格**，`maxLines = 2`）。价格由出参 `template_briefs` 一起给
   （`_template_briefs` 本来就在查那批价目行，**零额外查询**）；`template_names` **已删**——
   全仓只有规则卡一处用它，属于**替换不是新增字段**（DTO 仍是 `= emptyList()` 默认值，没惊动 DTO 默认值检查）。
3. **没勾价目的规则原来在卡片上什么都不显示** → 现在一行红字「还没勾价目 —— 派给这个司机的单会进
   「待定价」」。⛔ **空状态必须有人说话**：沉默等于让用户以为自己已经配好了（这条进了 §4.18 第 6 条）。

**第四轮（用户：「我说的是这个卡片的那个编辑和删除移到**最右边**去……卡片**高度变窄**一点」+ 定价的两级兜底，2026-09-21 00:4x）**：

1. **卡片版式按最新口径重做**：上一轮我照「按钮不要放在右边放在左边」改成了**靠左单独占一行** ——
   这一轮他说的是**移到最右边 + 卡片变矮**。现在两张卡都是「信息 `weight(1f)` + 按钮跟在同一 `Row`」：
   按钮贴最右、卡片少一行（真机 1080 宽：编辑 x≈692、删除 x≈886，卡片右边缘 996；一屏从 3 张变 4 张）。
   ⛔ 判据一起改：红线 ⑦ 从「按钮靠左」改成「同排 + `weight(1f)` + **不许**再出现 `Arrangement.Start`」，
   反向验证的注入点也换成"又单独占一行"。
2. **定价弹层两级兜底**（用户：「他在带定价的时候**要么直接沿用司机已有规则**进行定价，要么假如以前
   没有规则的话，那就走**普通的定价规则**，就是这个模板的规则，它规一个分类」）：打开弹层先按
   `driver_id = 这一单的司机` 问一次报价，没有再退回 `driver_id = null`（只看路线 + 分类）。
   **复用已有的 `/freight-templates/quote`**（一行后端都没新增），把"这个价是哪来的"写在运费框下面；
   同样优先多于一条时**不猜**，列出来让人点一条。
   真机验证（379 / 司机詹建国）：带出「他的规则里没勾到这条路线 —— 用运费模板里的价目：
   惠州惠阳 → 东莞塘厦 ¥74.00（按车结算）（已带出，可改）」，运费框预填 74.00。
3. ⚠️⚠️ **顺手抓到一个我自己上一轮埋的静默 bug**：`GET /orders?unpriced=true` **根本没生效** ——
   `list_orders` 有**两条互不相干**的查询构造路径（派单员+搜索词走 `stmt`、普通列表走 `q`），
   我把 `unpriced` 只加在前者上。后果：待定价页（不带 `q`）返回**全部订单**（420/419/418 这些有运费、
   甚至有已撤销的单全在里面），而页面上写着"这些单已经派出去了、但还没有运费"。
   ⛔ 红线当时为什么没抓到：静态检查只断言「参数存在 / 这段文本在」，**两处只坏一处时它照样绿**。
   现在四样一起上：① 两条路径都加；② 红线改成**数两条路径**（4 个片段各须出现 ≥2 次）；
   ③ 新增**行为测试** `test_待定价过滤在两条查询路径上都生效`（真打端点，两条路径都测）；
   ④ 反证 `_archive/_prove_unpriced_test.py`：把修复注掉 → 那条测试立刻红（`1 failed / 12 passed`）。
   📌 教训一句话：**"源码文本里有"不等于"行为对"** —— 凡是过滤/口径，最终必须有一条打到端点的测试。
4. ⚠️ **口径现状（要用户拍板，我没动钱）**：`quote_for` 目前**只被 `/freight-templates/quote` 调用**，
   **派单/下单流程都没接它** —— 也就是说运费一直是"下单时人工填"，"选司机自动带价"这条链子
   **还没接到业务流上**。另外全库 0 条 `freight_fee is null` 的存量单，所以待定价页平时是空的。
   要不要接、以及"货主填的价"与"价目表的标准价"谁优先，等用户定（这动的是客户付的钱）。

**验证**：`_check_all.py` **53/53 全绿**；红线 `_check_freight_pricing.py` **66 项** + 反向验证 **23/23**
（判据两次改动后都重跑过）；后端 `pytest` **655 passed**（642 → 654 → 655，含新增行为测试 1 例 +
`tests/test_freight_pricing.py` 12 例）；Android 单测 `--rerun-tasks` **897 项 / 0 失败 / 2 跳过**。

截图：`_archive/freight-01-categories.png`、`-02-templates.png`、`-03-driver-edit.png`、`-04-unpriced.png`、
`-05-rule-by-category.png`、`-06-rules-list.png`、`-07-price-picker.png`、`-08-picker-checked.png`、
`-09-templates-final.png`、`-10-rules-card-price.png`（第三轮：卡片带价格的价目摘要 + 没勾价目的红字提示）、
`-11-card-buttons-right.png`（第四轮：按钮贴最右、卡片矮一行）、`-12-pricing-autofill.png`（定价自动带价）。

---

### [2026-09-20 23:1x →] 会话：**AI 能力与角色能力对齐 + 货主 AI 拆成两套**（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`，同一条线继续）

**任务**（用户 2026-09-20 第七轮口述）：「AI 也要增加相应的功能，现在 AI 也会分成 2 个：一个是普通货主、
一个是批发商货主的 AI。相应的权限和能力跟对应角色的**所有功能和权限进行统一** —— 这个角色能做什么功能、
做什么事情，AI 要赋予相应的能力……但是他**不能越权**，批发商没有的功能 AI 也做不到；
**普通货主他做不到的事情，也就是他手机做不到的事情，AI 也做不到**。API key 已经写下来了，
全都用那个进行审查」（＝`~/.dsh/.credentials.yaml` 里的 `DEEPSEEK_API_KEY`，
用法见 `_tools/ai/_probe_chat_e2e_userkey.py`）。

**要交付的东西**

| # | 交付物 | 是什么 |
| --- | --- | --- |
| ① | `_tools/ai/_check_role_parity.py`（新） | **自动算差异**的双向检查：角色 × (后端端点允许 / App 有入口 / AI 有动作)。清单全部从源码解析，不手写；两头都断言（少了＝能力缺失，多了＝越权） |
| ② | `ai/AiWrite.kt` + `ai/AiWriteService.kt` + `ai/AiReads*` | 货主 AI 拆成**普通货主 / 批发商货主**两套：批发商独有的动作（核销/撤销/恢复）与只属于他的读表，在**普通货主**那里连清单都不出现 |
| ③ | 同上 | 补齐已确认的缺失（见下"已查实的差异"） |
| ④ | `_tools/ai/_ai_e2e_role_audit.py`（新） | **真 DeepSeek key** 驱动的双向审查：正问（该办的要办成）+ 反问（不该办的必须拒绝），两个货主账号各跑一遍 |
| ⑤ | 单测 / 红线 / 反向验证 / 文档 | 与既有那套（`_check_ai_guardrails` / `_show_role_caps --check` / `_reverse_verify_*`）接上 |

**已查实的差异（读源码 + 端点索引 + 真机 UI 判据得出，动手前先列出来）**

| 差异 | 证据 | 结论 |
| --- | --- | --- |
| 货主手机能**删自己的单**（终态：已送达/已撤销），AI 没有这个动作 | `ui/order/OrderDetailScreen.kt:828`（`canDelete` = SHIPPER && CANCELLED\|DELIVERED）↔ `DELETE /orders/{id}` 授权「体内仅允许：派单员\|货主」；AI 侧 `orders.soft_delete` **不在** `SHIPPER_ACTIONS` | **缺能力**（要补，且只放终态、与界面同一判据） |
| 货主手机能**删自己的消息**，AI 不能 | `MessagesScreen` 三端共用（删/清空）↔ `POST /notifications/batch-delete`「仅登录」（后端只允许动自己的）；AI 侧 `notifications.delete` 不在白名单，且 `_show_role_caps.py` 的 `SHIPPER_FORBIDDEN_HINTS` 把它写成"删除别人的消息"（**这条理由本身是错的**：同一个动作只动自己的） | **缺能力 + 一条错误的禁令牌** |
| 货主的**软删撤回路径走不通** | `address.restore` / `location.restore` / `contact.restore`（`redoOnly`，由 `AiWriteService.kt:1785/1789/1793` 实现）都**不在** `SHIPPER_ACTIONS`；而 `allows()` 是 preview 与撤回**两条路共用的门** → 货主点了自己那张删除卡的「撤回」会被自己的权限门挡掉 | **缺能力（红线级）** |
| `my_ledger.restore` **没有交代撤回怎么走** | `_show_undo_status.py` 表里唯一那条 `?`「没有交代」 | **红线**（我上一轮留下的） |
| 批发商独有的能力，**普通货主的 AI 现在也看得到**（发卡时才用 403 拦） | `AiWriteService.isMemberShipper` 只在 prepare 里当门，动作清单本身不分 | **与用户"两个 AI"的要求不符** |

**明确不碰**：`ui/dispatcher/*`（派单员账本那条线）、`ui/driver/*`（司机端）、任何后端鉴权
（这一轮**先不动后端** —— 若发现"后端允许但手机根本没有入口"的项，先按用户的规则**从 AI 侧收掉**，
并在声明里登记，等用户拍板要不要改后端）。

---

### [2026-09-20 23:4x →] 会话：账本「记一笔账」改成两个选择器（DSH `session-faa17a77-515b-4bcb-bd47-fddae0129342`）

**任务**（用户 2026-09-20 口述 + 截图 `记一笔账` 弹窗）：
「记手动记账的逻辑不对 —— **这个商品是可以在现有的商品库进行选择的**。一般情况下假如订单没有走，
但是有一笔账是这样存在的；**未注册的话也可以直接填**，它会显示到列表上、**自动帮他注册一个临时账户**，
相当于一个普通账户；时间备注也是可以填的；**他只要填数量、对应的价格是会有的**，
但是单价可能不一样 —— **单价是可以改的**，也就是预售价可以单独调整。」

逐条落成（**不新增后端端点**：[`POST /ledger/entries`](backend/app/api/v1/ledger.py) 本来就收
`shipper_id | temp_shipper_name` + `product_id` + `product_name` + `quantity` + `unit_price` + `total` + `note`）：

1. **商品 = 从商品库选** → 复用 `ui/common/ProductPicker.kt`（唯一那份"商品库浏览"UI：分类栏 + 搜索 + 数量小窗），
   选中即带出 `product_id` / 名称 / 数量 / **单价**；单价**可改**（预售价单独调整）；
2. **货主 = 选已注册的，或直接填未注册的名字** → 填了就是**临时货主账户**（后端 `temp_shipper_name`，
   与「代理下单」同一套口径），下次能在**同一个选择器的「用过的临时货主」段**里再选到，
   并出现在货主账里（相当于一个普通账户）；
3. 数量 × 单价 = 合计（当场看得见）；日期、备注照旧可填。

**形态**：原来的 `AlertDialog` 装不下两个选择器（商品选择器是全屏底部弹层，套在弹窗里就是两层 modal 窗口，
叠窗在 Compose 上不稳），所以**改成单独一页**（与「新增开销」同一形状、同一返回即刷新的接法）。

| 文件 | 改什么 |
| --- | --- |
| **新增** `android/.../ui/dispatcher/LedgerCreateScreen.kt` | 「记一笔账」页（货主选择器 + 商品选择器 + 数量/单价/合计 + 日期/备注） |
| `android/.../ui/dispatcher/DispatcherLedgerScreen.kt` | 删掉那个弹窗（**同一件事不留两份**）；「记账」按钮改成去新页；回来那一下重取一次 |
| `android/.../ui/dispatcher/DispatcherLedgerViewModel.kt` | 删掉弹窗的草稿状态与 `create()`（都搬进新页的 VM） |
| ⚠️ `android/.../ui/common/ProductPicker.kt` | **追加**一个 `single` 参数（默认 false = 下单那边一个字不变）：一笔账只记一件商品，单选模式下再挑一件是**换掉**而不是累加 |
| `android/.../ui/nav/Routes.kt`、`NavGraph.kt` | 新增一条路由 |
| `_tools/qa/_check_ledger_manual_entry.py` + 反向验证 | 新红线（单据规矩：商品必须来自商品库、单价可改、货主二选一、临时货主口径） |
| `docs/PROJECT_MAP/08_CODE_LOCATOR.md`、`06_DESIGN_SYSTEM.md` | 「账本管理」那一行 + 设计规矩 |

**明确不碰**：另一个会话的 `shipper_ledger` / `ShipperLedger*` / `shipper_settle*` / 司机端那几页；
AI 侧的 `ledger.create_entry`（它本来就允许"货主查不到 → 按临时客户记"，与这一轮同口径，**一行不改**）。

**结论（已做完，2026-09-21 0:0x）**：新页 + 删旧弹窗 + 路由 + 新红线，**后端一个字节没动**。
真机（emulator-5556，派单员）逐步验过：选品页是**单选**（按钮「用这件」）→ 选「顺鑫蔬菜批发」时
荷兰豆带出**专属价 13.2**（默认 14.8）、金禾米业带出 **13** → 手改 20 后再换货主**停在 20**（没被拽走）→
换成未注册的「陈老板（临时）」后**重算回默认 14.8**（⚠️ 这一条是**真机验出来的错价**：原来的写法只对
"换注册货主"重算，换成临时货主会停在上一家的专属价上；已抽成 `repriceIfAuto()` 三处共用 + 补红线）→
数量 2、合计 ¥29.60 → 保存后回到订单账，合计 809.30→**838.90**、15→**16 笔**，新行
「陈老板（临时）/ 荷兰豆 ×2 · 2026-09-20 / ¥29.60」**没有单号**（手工账的正确形状）→ 货主账里多出
「陈老板（临时）· 未注册账号 · 1 笔 · ¥29.60」→ 再进记账页，选择器的「用过的临时货主（未注册）」里
**列得出这个名字**（用户要的"它会显示到列表上"）。库里那一行：`shipper_id=NULL` + `temp_shipper_name=陈老板（临时）`
+ `product_id=9` + `qty=2/单价 14.8/**total 29.6**`（后端 Decimal 算的，没有 Double 尾数）+ `source=MANUAL` + `order_id=NULL`。

截图：`_archive/ledger-manual-01-shipper-sheet.png`（货主选择器）、`-02-form.png`（表单）、
`-03-list.png`（订单账里那一行）、`-04-owner-account.png`（货主账里的临时账户）、`-05-used-temp-names.png`（用过的临时货主）、
`-06-shipper-sheet-final.png`（最终形态）。

**收尾时照真机截图补的一处**：数量/单价两个框原来只有 placeholder，**填上值以后（截图里是「2」「14.8」）
就分不出哪个是数量、哪个是单价** —— 而右边那个是钱。已各加一行小标题（`FieldLabel`），
placeholder 去掉（有标题就不需要第二遍）。顺带把结论里的截图编号补齐。
静态检查 `_check_all.py` **51/51 全绿**；新红线 `_check_ledger_manual_entry.py` **48 项** + 反向验证 **19/19**；
Android 单测见当轮结果。

⚠️ 本机演示库里留了一条**示例手工账**（陈老板（临时） / 荷兰豆 ×2 / ¥29.60，ledger id=808）：
故意留着当验收用；不想要就从账本列表那一行右边的垃圾桶删掉（软删）。

⚠️ **给下一个写 `_check_*.py` 的人**：脚本里（**包括文档字符串**）别写 `\s` `\d` 这类无效转义。
Python 会发 `SyntaxWarning`，而 `_check_all.py` 的摘要是**取子进程输出的最后一行** ——
那条 warning 会把源码行原样打到 stderr（且是 **GBK** 编码），于是那一行在汇总里变成乱码、
看起来像"这个检查没输出"。更阴的是：`.pyc` 缓存之后**本地直接跑看不到它**（只有第一次编译时报），
所以"我本地跑是好的"证明不了没问题。

---

### [2026-09-20 21:1x →] 会话：开销管理重写（DSH `session-faa17a77-515b-4bcb-bd47-fddae0129342`）

**任务**（用户 2026-09-20 第六轮口述 + 两个确认问题的回答）：

1. **新增开销 = 单独一页**（像「新增订单」那样，从按钮进）——用户选的是"按钮 → 进单独一页填"；
2. **开销记录照「商品管理」那套**：**左边开销分类、右边该分类的记录** + 一个**开销分类管理**页
   （建/改名级联/删除有挂账时拒绝/排序——与商品分类名册同一套规矩）；
3. **时间筛选 = 右上角时间药丸**（复用 `ui/common/Components.kt::DatePresetPill` / `DatePresetDialog`）；
4. **开销卡片按"分类"决定突出什么**，不许一刀切（用户原话：「燃油或者说维修这些主要是车辆，
   所以关联的是车辆，首要突出的是车辆；如果是其他的成本的话，可能关联的就是其他的……
   **要具体问题具体判断，不能一刀切**」）→ 分类名册多一列「主要关联」（车辆/司机/订单/不关联），
   卡片按它突出那一项；**订单来源放"详情"里看**（「我们点击详情进行查看的时候，
   还是可以查看证明订单到底是哪里来的」）。

**新增文件（谁也别先建）**

| 文件 | 作用 |
| --- | --- |
| `backend/app/models/expense_category.py` | 开销分类名册（name + sort_order + link_kind） |
| `backend/app/schemas/expense_category.py` | 入参/出参 |
| `backend/app/api/v1/expense_categories.py` | `/expense-categories`（增/改/删/reorder/ensure_category） |
| `backend/tests/test_expense_categories.py` | 后端测试 |
| `android/.../ui/dispatcher/ExpensesScreen.kt` / `ExpensesViewModel.kt` | 开销管理主体（分类栏 + 时间药丸 + 卡片 + 详情） |
| `android/.../ui/dispatcher/ExpenseCreateScreen.kt` | 新增开销（单独一页） |
| `android/.../ui/dispatcher/ExpenseCategoriesScreen.kt` / `ExpenseCategoriesViewModel.kt` | 开销分类管理 |
| `android/.../core/ExpenseLink.kt` + 单测 | 纯函数：分类 → 该突出哪一项关联（有兜底规则） |

**改动的共享文件**（⚠️ = 另一个会话也在改，一律**追加式**改动并记在「交叉点」）：

| 文件 | 改什么 |
| --- | --- |
| `backend/app/services/accounting_service.py`、`schemas/accounting_v2.py` | `create_expense` 自动补名册；`category` 从枚举放开成**自由字符串**（否则新建的分类一存就读不出来） |
| ⚠️ `backend/app/api/v1/router.py`、`models/__init__.py` | 注册新路由/新模型（各一行） |
| ⚠️ `backend/app/core/schema_bootstrap.py` | 建表 + 存量分类回填（**写在 `with engine.begin()` 里**） |
| ⚠️ `backend/app/models/enums.py` | 新增 3 个审计码（分类增/删/排序） |
| ⚠️ `android/.../ui/dispatcher/ReportCenter.kt` | `actionLabel` 追加 3 个中文名 |
| ⚠️ `android/.../data/remote/api/Apis.kt`、`dto/Dtos.kt`、`repo/AppRepository.kt` | 追加开销分类接口/DTO/仓库方法 + `ExpenseDto.vehicleId` 等字段 |
| ⚠️ `_tools/ai/_write_coverage.py`、`_app_feature_coverage.py` | 新写端点的「不做」理由 / 新能力登记 |
| `android/.../ui/nav/Routes.kt`、`NavGraph.kt`、`ui/dispatcher/AccountToolsScreens.kt` | 新路由两页；旧的开销屏从 AccountTools 里移走（不留第二份） |
| `docs/PROJECT_MAP/08_CODE_LOCATOR.md` | 「费用」那一行更新 + 新增「开销分类名册」一行 |
| `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` | 卡片"按分类突出主关联"的规矩 |

**明确不碰**：另一个会话的 `shipper_ledger` / `ShipperLedger*` / `shipper_settle*` / `test_shipper_settlement.py`。

**结论（已做完）**：四件事全部落地并在真机上验过；静态检查 48/48 绿，新红线 `_check_expense_page.py` 38 项 + 反向验证 13/13；新增的后端 6 个测试在 `tests/test_expense_categories.py`（642 → 见当轮 pytest 结果）。
本次追加改动的**共享文件**（都只追加、都已重读）：`enums.py`（3 个审计码 + 删 `ExpenseCategory` 枚举）、`ReportCenter.kt`（3 个中文名）、`router.py` / `models/__init__.py` / `schema_bootstrap.py`（注册 + 建表 + 迁移）、`Apis.kt` / `Dtos.kt` / `AppRepository.kt`（开销分类的接口/DTO/仓库各一段）、`_tools/ai/_write_coverage.py`（4 条「不做」理由）、`_read_coverage.py`（1 条理由）、`_gen_ai_toolmap.py`（一行中文模块名）、`ExpenseCategoriesScreen` 用到的 `AccountToolsScreens.kt::DropField`（加了 modifier 参数）。

### [2026-09-20 19:2x] 会话：模拟器554货主账本改造（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）

**任务**：把**货主端**的「我的账本」改成**以订单为基础**（模拟器 5554 上验收）。
用户 2026-09-20 已拍板的口径（照这个做，别自行发挥）：

1. 顶部**搜索框**（批发商搜联系人/货主；普通货主搜订单）；
2. **时间档位**（今天/昨天/前天/这周/上个月/自定义）→ **按【送达日】筛**
   （与派单员账本同口径，走 `GET /orders?delivered_from&delivered_to`）；
3. **批发商**（`users.is_member=1`）分两段：`① 我欠总分销商多少钱`（汇总）
   + `② 我的货主（联系人）欠我多少钱`：**先联系人总计、再他名下的订单明细**；
   核销粒度＝**整单 / 按商品行（部分商品）**两种，**可撤销**；
   核销**只记在他自己账上**（新表 `shipper_settlements`），绝不写 `orders.paid` /
   `cash_flows` / `ledgers`，对派单员完全不可见；
4. **普通货主**：**只有**订单搜索 + 日期筛选 + 自己的订单列表（点进详情）+
   「欠总分销商」合计。**没有核销**（他给自己下单，不需要核销）；
5. 撤销/删除一律**软删 + 有恢复路径**（用户原话：「我们的操作都是走软删除这个你要注意一下」）；
6. **AI 本轮一起做**：帮他核销 / 帮他管账本 / 帮他撤回核销（撤回同样走软删/恢复）。

**预计新增文件**（这些文件现在还不存在，谁也别先建）：

| 文件 | 作用 |
| --- | --- |
| `backend/app/models/shipper_settlement.py` | 新表 `shipper_settlements`（批发商自记账核销，独立于派单员的收款） |
| `backend/app/schemas/shipper_settlement.py` | 出参/入参 |
| `backend/app/api/v1/shipper_ledger.py` | 新路由 `/shipper-ledger`（读核销记录 + 建核销 + 撤销 + 恢复） |
| `backend/tests/test_shipper_settlement.py` | 后端测试 |
| `android/.../ui/shipper/ShipperLedgerOrders.kt` | 账本页新主体（搜索 + 档位 + 汇总卡 + 订单/货主明细 + 核销弹层） |
| `android/.../ui/shipper/ShipperLedgerGrouping.kt` | 纯函数：按收货人（货主）聚合、搜索过滤、金额合计 |
| `android/.../test/java/.../shipper/ShipperLedgerGroupingTest.kt` | 上面那份纯函数的单测 |

**预计修改的文件**（改之前会先重读；下面标 ⚠️ 的是**别人也在改**的共享文件，只做追加式改动）：

| 文件 | 改什么 |
| --- | --- |
| `android/.../ui/shipper/ShipperLedgerScreen.kt` | 改成新版（旧「账目流水」保留为二级入口，不删能力） |
| `android/.../ui/shipper/ShipperLedgerViewModel.kt` | 取数换成 订单 + 核销记录 + `users/me` 的 `is_member` |
| ⚠️ `android/.../data/remote/api/Apis.kt` | **追加**一个 `ShipperLedgerApi` 接口 |
| ⚠️ `android/.../data/remote/dto/Dtos.kt` | **追加**核销 DTO |
| ⚠️ `android/.../data/repo/AppRepository.kt` | **追加**三四个转发方法 |
| ⚠️ `android/.../ui/dispatcher/ReportCenter.kt` | `actionLabel` **追加**新审计码的中文名（不删不改别人的） |
| `backend/app/models/__init__.py`、`backend/app/api/v1/router.py` | 注册新模型与新路由（各一行） |
| `backend/app/core/schema_bootstrap.py` | 建表迁移（写在 `with engine.begin()` 作用域内，历史事故区） |
| `backend/app/models/enums.py` | 新增 1~2 个 `OperationAction` 审计码 |
| `_tools/ai/_app_feature_coverage.py` | 「我的账本」不再是纯只读（`MAP` + `EXEMPT` 两处） |
| `_tools/ai/_write_coverage.py` | 新写端点要么配 AI 动作，要么写「不做」的理由 |
| `docs/PROJECT_MAP/08_CODE_LOCATOR.md`、`08A_ENDPOINT_INDEX.md` | 同步自己那一行 / 重跑生成器 |
| `docs/ai/ai_read_catalog.json`、`android/.../ai/AiReadCatalog.kt` | 重跑生成器（新读端点） |

**明确不碰**（这些是你这两轮正在改的，我一行都不动）：

- `backend/app/services/order_money.py`、`order_return.py`（只**调用**，不改）
- `android/.../ui/dispatcher/LedgerPersonScreen.kt`、`LedgerPersonStats.kt`
- `android/.../core/ReturnRules.kt`、`core/WorkbenchOrder.kt`
- `android/.../ui/dispatcher/LedgerHomeScreen.kt`、`LedgerPersistence*.kt`、`WorkbenchScreen.kt`
- `_tools/qa/_check_order_return.py`、`_check_dead_code.py` 及其反向验证

**状态：已完成（2026-09-20 21:0x）；21:3x 追加了一轮「照派单员账本的形式改」** —— 用户可以验收了。

**21:3x 追加的那一轮（用户第二次点名）**：把货主账本对齐派单员那套形态 ——
① 时间改成**顶栏药丸**（`DatePresetPill` + `DatePresetDialog`，那两份是第五轮做的，我直接复用，没写第二份）；
② 默认档位**自动退档**（今天 → 昨天 → 前天 → 近 7 天 → 全部），手动挑过就不再自动改；
③ 批发商账加**人员那一行 + 侧边抽屉选货主**（与派单员账本同一形状，抽屉里的搜索**只筛名单**）；
④ 订单行按"扫一眼就够"重排：**第一行左=送达状态徽章 + 送达时刻、右=这单多少钱（大字）**，
   第二行单号 + 核销/欠款，第三行收货人与商品摘要，行尾 `›` 表明整行可点进详情
   （真机点过：进的是订单详情页）。
⑤ 选定某个货主之后**合计卡跟着他走**（否则屏幕上会出现"人员行写着柯志强、合计却是全部 2 单的 222.20"——
   两个数各自都对，摆在一起就是假的）。
⑥ **`ui/common/DatePresets.kt`**：加了「近一年」一档（`LAST_YEAR`，用户点名要的预设）**和** `AUTO_LADDER`
   （今天/昨天/前天/近 7 天，给"一打开就该有数"的页面用；已有 9 档的区间一个字没动）。
   ⚠️ `AUTO_LADDER` 是**为了让模块能编译**加的：当时 `ExpensesScreen.kt` 已经在引用
   `DatePresets.AUTO_LADDER` 而它还不存在 → 整个 `assembleEmuDebug` 红着，谁都装不了机。
   现在货主账本 / 开销管理共用这一份；司机端那两页用更长的 `DRIVER_PRESET_LADDER`（显式自己的那份）。

**真机截图（新形态）**：`_archive/ledger554-v2-{member,presets,drawer,plain}.png`
—— 药丸默认落在「前天」（今天/昨天都没单 → 自动退档真的生效）、档位清单里能看到「近一年」、
抽屉里是「全部（N 人）+ 每人欠我多少」、普通货主那一页**没有人员行**（他没有人可挑）但保留订单搜索框。

**⚠️ 21:2x 的一次互相解围（记下来免得下次重复踩）**：对方在建的
`ExpenseCategoriesScreen.kt` 少一行 `import ...core.InputRules` → 整个模块编译不过。
我先补了一行，对方几乎同时补了同一行 → 出现 `Conflicting import`；我把**我那行撤了**
（现在只有对方那一行，他们自己带注释）。**教训：模块级编译不过时先等半分钟再动手补对方文件**——
两个会话同时补同一处，结果是"谁都补对了、编译反而更红"。

- **后端**：两张新表 + `services/shipper_settle.py`（口径唯一处）+ `api/v1/shipper_ledger.py` 四端点 + 3 个审计码；
  `tests/test_shipper_settlement.py` **10/10**；端点索引 / 工具表 / AI 读能力目录已重跑（读端点角色已收窄成 `shipper`）。
- **真后端 + 真库链路**：整单核销 201 → 重复 400 → 撤销 204（列表消失、含已撤销可见）→ 又能核销 → 恢复 200
  → 按商品核销（只覆盖 1 行）→ 超收 400 → 普通货主写 403 / 派单员读 403；
  **公司账逐项没动**：`cash_flows` 34→34、`ledgers` 807→807、`paid=1` 20→20、该单 `arrears_amount` 不变。
- **模拟器 5554 真机**（截图 `_archive/ledger554-{member-list,settle-sheet,after-settle,plain-shipper}.png`）：
  批发商 → 搜索/档位/「我欠总分销商 ¥1935.70」/「我的货主欠我」/按联系人分组/「核销」；
  核销后「我的货主欠我」1911.60→1565.40、已收 24.10→370.30，而**「我欠总分销商」一动不动**；
  按手机号搜索命中 1 人；「已记 1 笔」→ 撤销 → 「已撤销的核销」→ 恢复（库内 `is_deleted` 1→0）；
  普通货主（临时置 `is_member=0` 再置回）→ 只有搜索 + 档位 + 订单列表 + 「欠总分销商」，**无核销、无分组**。
- **AI**：`my_ledger.settle / revoke / restore` + 两个手写处理器 + 撤回声明；`AiWriteTest.FakeDs` 那 6 个实现已补齐。
- **`python _tools/qa/_check_all.py` 48/48 全绿**。

**⚠️ 给下一个跑 `--deep` 的人**：反向验证会**把快照之后写进文件的内容一起还原掉**（我这四个文件中过招：
`AiWrite.kt` / `AiWriteService.kt` / `AiResources.kt` / `AiRevert.kt`）。跑之前说一声，跑完各自 `grep` 一下自己的标记。

**⚠️ `08_CODE_LOCATOR.md` 里那两行也被还原过**（「货主 | 账本」与「批发商自记账核销」）：21:1x 已重新写回。
谁重写这份文档时**请只改自己那几行**——整段替换会把别人的行一起带走（这已经是第二次了）。

**⚠️ 21:1x 那次 `_check_all.py` 剩下的 5~6 条红不是这条线的**（`_check_action_labels` / `_gen_ai_toolmap --check` /
`_read_coverage` / `_write_coverage` / `_check_dead_code` / `_check_backend_fresh`）：它们全是
**新建的 `expense_categories`（开销分类）那条线**的在建状态（3 个 `EXPENSE_CATEGORY_*` 审计码缺中文名、
新模块缺 `MODULE_CN`、`GET /expense-categories` 没进读能力目录、`ui/common/OrderCard.kt` 有个没用到的 import、
后端进程又比源码旧）。谁在做谁收口，我没碰。本线的所有检查在那之前是 **48/48 全绿**。

**22:5x 第三轮追加（用户第三次点名）—— 已完成**：「你这个**账目流水**为什么也不做对应的那个右上角的
时间图标？他还是那个滑动型的」—— 货主账本里那个二级视图（顶栏 `ReceiptLong` 图标切进去、
标题写「账目流水」）**还在用 `DatePresetRow` 那条横滑胶囊行**，而且切进去之后顶栏药丸还会消失
（`if (!vm.showFlow)` 那个门）。用户要的是"整页一个药丸、任何视图都看得到"。

改成：**一个页面一个窗口**（照派单员账本 `DispatcherLedgerScreen` 的模型：它的订单账 tab 与别的 tab
共用顶上那一个药丸、共用 `vm.rangeFrom/rangeTo`）。

| 文件 | 改什么 |
| --- | --- |
| `android/.../ui/shipper/ShipperLedgerScreen.kt` | ① 顶栏药丸**去掉 `if (!vm.showFlow)` 的门**（流水视图也常驻）；② 删掉 `FlowView` 里那行 `DatePresetRow`；③ 截断提示的指路文案改成与派单员账本同一句（"更早的请点右上角的**日期档位**缩小范围"——`_check_page_truncation_wiring.py` 要求文案点名页面上真有的入口，原来那句"上方时间导航"现在指不到东西了） |
| `android/.../ui/shipper/ShipperLedgerViewModel.kt` | ① 删掉流水自己的 `flowFrom/flowTo`，`loadFlow()` 改用页面的 `rangeFrom/rangeTo`；② 顺带删掉**已经没人调的**日/周/月翻页残留（`chartMode` / `chartAnchor` / `applyFlowMode` / `setFlowAnchor` / `flowPeriodText` / `applyFlowRange` —— 全项目 grep 只命中它们自己）；③ 新增 `reloadWindow()`：换档 / 实时推送时**两个视图一起重取**（只刷新一个的话，切回另一个会看到上一个窗口的数）；④ 打开流水视图时**总是重取**一次（原来 `if (entries.isEmpty())` 会在换过窗口后留下陈旧数据）；⑤ 退档阶梯改用共享的 `DatePresets.AUTO_LADDER`（本文件里那份 private list 删掉） |
| `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` | §4.15 **新增第 6 条**（药丸是"页面级"的：切视图不许藏、页面里不许再冒出一条胶囊行）；顺手把上面 §4.12 里"账本页共用胶囊行"那句过期描述改对（只改了一句，别的行没动） |
| `docs/PROJECT_MAP/08_CODE_LOCATOR.md` | 只在自己那一行（**货主 \| 账本**）尾部**追加**两条 |

**口径依据（不是"顺手统一"，是本来就同源）**：`backend/app/services/ledger_sync.py:27`
`entry_date = business_date(order.delivered_at) or order.order_date`，而 `api/v1/orders.py:204`
的注释写明"按送达日筛订单，**口径与账本行的 `entry_date` 对齐**"—— 所以订单账的窗口与流水的窗口
本来就是同一段时间，共用一个药丸不会让任何一边少算。

**⚠️ 顺手抓到并修掉的一个真 bug（logcat 实证，不是猜的）**：`init` 里原来直接调 `load()`，
而 `preset` 初值是「今天」、`rangeFrom/rangeTo` 初值是 **null（＝后端不加日期条件）** ——
于是打开这一页**先拉一整份"全部"**（`GET /orders?limit=500`，无日期），药丸上写着「今天」、
屏幕上却是全部 12 单 ¥1935.70，一秒后才被退档窗口替换；大货主那份"全部"还会撞 500 行截断闪提示。
改成 `switchPreset(DatePresets.TODAY)`（"档位 → 区间 → 取数"锁在一条路上）。修后 logcat：
第一条就是 `delivered_from=2026-09-20&delivered_to=2026-09-20&limit=500`，全表无日期的那条再也没出现。

**真机验收（模拟器 5554，截图 `_archive/ledger554-v3-*.png`）**：
· 切进「账目流水」→ **顶栏药丸还在**（写「前天」）、**横滑胶囊行没了**，
  请求 `GET /ledger/entries?date_from=2026-09-18&date_to=2026-09-18`；
· 与订单账**同一个窗口对上账**：两边都是 ¥192.60（1 单）；
· 在流水页里把药丸换成「近一年」→ **一次点击两个请求同时发出**
  （`/ledger/entries?date_from=2025-09-21…` 与 `/orders?delivered_from=2025-09-21…`）→ 切回订单账，
  药丸仍是「近一年」、列表也是那 12 单 —— 一个页面一个窗口成立；
· `python _tools/qa/_check_all.py` **50/50 全绿**。

**明确不碰**：`ui/common/Components.kt`（药丸/档位弹层的定义，第五轮做的，我只调用）、
`DatePresets.kt`（本轮只在 VM 里引用它，没改它）、`ui/dispatcher/*`（派单员账本那条线）、
任何后端文件（这一轮一个字节都不动后端）。

⚠️ **留给用户拍板的一件**（我没擅自改）：流水页里那张**「账单趋势」图 + 折线/条形切换**要不要按
派单员账本那样删掉？§4.15 第 4 条说"账本页不画图、图归报表中心"，但**货主端没有报表中心**
（`Modules.shipperEntries` 就 6 格，没有那一项），而 `DispatcherLedgerScreen.kt:533` 的注释也写着
"图在 `ui/common/Charts.kt`（报表中心/**货主账本**/司机端在用）"—— 所以这一轮**保留**了它。

---

### [2026-09-21 03:0x → 03:5x] 会话：**派单员也有「新单语音播报」**【已完成】（DSH `session-faa17a77-515b-4bcb-bd47-fddae0129342`）

**用户需求（原话）**：「你在给派单员加一个功能，就是**派单员收到订单的时候**，他就是**有订单需要派的时候**，
他会有个**语音播报**，就跟我们的司机是一样的。」＋「上面说的就不要管了」（＝运费自动带价那条线**暂停**，
不接派单流了，保持现在人工填写）。

**两个拍板（本轮问过用户，都按推荐）**：① 播报词**新录一句派单员专用的**（不复用司机那句）；
② 派单员**后台常驻默认开**（关掉 App / 锁屏也听得到，设置里随时可关）。

**零后端改动**：派单员本来就收得到 `order.created` 站内信（`publish_new_order_to_dispatchers` →
`emit_notification`，标题「新订单待派单」），只是 App 侧没认这个 type、也没给这个角色开语音。

| 我改的 | 内容 |
| --- | --- |
| `core/NewOrderAlert.kt` | 新增 `AlertKind.PENDING_ORDER`（待派单）；`eventOf` 认 `order.created`；**按 (角色 × 类型) 判**（`speaks`：新派单只给司机、待派单只给派单员）+ `hasVoice`；`clipMs(kind)`（两段素材两个常量）；`repeatLabel(setting, role)`（「一直响到我接单」/「一直响到我派完单」）；`defaultBackground(派单员)=true`；`shouldStop` 补三个 `*_dispatcher` 事件；`forgetOnStop` 同时作废 `pending:` 键 |
| `core/NewOrderPlayer.kt` | 按 kind 选素材（`R.raw.new_order` / `R.raw.pending_order`）、按 kind 取时长、TTS 兜底话术分角色 |
| `core/RealtimeHub.kt` | 播报门从 `isSpoken(role)` 改成 `speaks(role, ev.kind)` |
| `res/raw/pending_order.wav`（新） | 号角 + 神经语音「来订单了，有新订单待派单，请及时处理」，由 `_tools/media/_gen_new_order_clip.py --kind dispatcher` 生成 |
| `_tools/media/_gen_new_order_clip.py` | 新增 `--kind {driver,dispatcher}`（各自的文案与输出路径） |
| `ui/profile/AlertSettingsScreen.kt` | 语音开关、档位、试听对派单员也出现（文案按角色：「有新订单待派单时大声念…」） |
| `ui/profile/ProfileScreen.kt` | 「消息提醒」入口的图标/副标题改用 `hasVoice` |
| `ui/dispatcher/DispatcherPoolViewModel.kt` | **派单成功后立刻闭嘴**（等价于司机接单那一下）——他派完了还在喊"待派单"就是错的信息 |
| `android/app/src/test/.../NewOrderAlertTest.kt` | 角色×类型的双向断言（司机不播派单员的、派单员不播司机的、货主两个都不播）+ 两个素材常量 |
| `_tools/ai/_check_notify_guardrails.py` + `_reverse_verify_notify.py` | 判据改成"按角色×类型"，两段素材与两个常量一起对账；补注入 |
| `docs/INTEGRATIONS.md §5`、`08_CODE_LOCATOR.md`（通知那一行） | 同步 |

**⚠️ 已知行为（不是 bug，先记下来）**：派单员**自己代理下单 / 拆单**时，后端也会给他推 `order.created`，
所以那一下他自己的手机会念一遍。要不要"自己下的单不念"等他拍板（现在不动）。

**结论（已做完，真机验过）**：

| 验证 | 结果 |
| --- | --- |
| 真机 E2E（**emulator-5556 派单员**） | `POST /orders`（货主身份下一单）→ 日志 `开始播报 kind=PENDING_ORDER 次数=3` → `播报结束：完整播了 3 次`（18:51:49→18:52:06，16.6 秒 = 3×5210ms + 2×350ms）；通知栏同时有「新订单待派单」 |
| 司机那条**没被改坏** | 把同一单派给司机 3 → **5558** 日志 `开始播报 kind=NEW_ORDER 次数=3`；5556 一声不响（`speaks` 两维判成立） |
| 设置页（截图 `_archive/notify-01-dispatcher-alert-settings.png`） | 「我的」那一行右侧 = **语音 3 次·后台接收**；设置页 = 「有订单需要派时大声念「有新订单待派单」」/ 档位含 **一直响到我派完单** / 试听（约 5 秒）/ 80% 音量 / **关掉 App 也收单＝正在后台接收**（派单员新默认生效）/ 底部一句「语音按角色分工：司机听「有新派单」，派单员听「有新订单待派单」」 |
| 装机包里的素材 | APK 内 `res/raw/{new_order,pending_order}.wav` 与源文件 **sha256 逐字节一致**（确认装的是新音色那份） |
| 静态检查 | `_check_all.py` **54/54 全绿**；红线 `_check_notify_guardrails.py` **116 项**；反向验证 **44/44**；Android 单测 **913 项 / 0 失败 / 2 跳过** |

**⚠️⚠️ 本轮我自己踩的最实的一个坑（用户当场听出来的）**：派单员那句第一版**音色是错的**——
生成脚本的 `DEFAULT_VOICE` 当时是**云健（男声）**，我生成时没传 `--voice`，于是素材成了男声，
而用户 2026-09-17 指定的是**晓晓（女声）**（代码注释里就这么写着，脚本默认值却一直没跟着改）。
用户原话：「我记得我选了音色的啊。是一个女生的音色……很像人机感」。
- 量化证据（`_tools/media/_probe_clip_voice.py`，量语音段中位基频）：司机那份 **244.9Hz**（女声，对）、
  我做的派单员那份 **116.5Hz**（男声，错）→ 重做后 **260.9Hz**。
- 修法：① 默认音色改成用户选的那个（`DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"`，并写明"别拿风格当理由改它"）；
  ② 新增常驻工具 `_tools/media/_probe_clip_voice.py`（女声 ≥165Hz，退出码非 0 就是错）；
  ③ **红线拿基频对账**（静态断言默认音色 + 实测两份素材），反向验证补 2 种注入（改默认音色 / 把阈值改坏）。
- 教训一句话：**"换错音色"是那种不报任何错的错**——文件能播、时长也对，只有用户听得出来。

**明确不碰**：其他会话在建的退货申请 UI（`ui/shipper/ShipperReturnRequests*`、`ui/dispatcher/DispatcherReturnRequests*`、
`ui/common/ReturnRequestChip.kt`、`Modules.kt`/`Routes.kt`/`NavGraph.kt` 里他们的那几格）、`ui/common/Components.kt`、
`backend/**`（本轮一个字节不动）、`ai/**`。

⚠️ **给别人的一条**：本轮跑反向验证时撞上一次 **Kotlin 增量缓存损坏**
（`Could not close incremental caches … Storage … is already registered`）——两个会话同时跑 gradle 构建就会这样，
表现是**单测任务假绿/假红**（我的反向验证因此一度给出两套互相矛盾的结论）。
修法：删 `android/app/build/kotlin` 再跑。**结论：别和别人同时构建，看到这个报错先清缓存再下结论。**

**明确不碰**：其他会话在建的退货申请 UI（`ui/shipper/ShipperReturnRequests*`、`ui/dispatcher/DispatcherReturnRequests*`、
`ui/common/ReturnRequestChip.kt`、`Modules.kt`/`Routes.kt`/`NavGraph.kt` 里他们的那几格）、`ui/common/Components.kt`、
`backend/**`（本轮一个字节不动）、`ai/**`。

---

## 交叉点（共享文件的实际改动记录）

| 时间 | 会话 | 文件 | 改了什么（一句话） |
| --- | --- | --- | --- |
| 2026-09-22 03:0x | **商品外观做深**（我） | `docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md`、`docs/ai/ai_read_catalog.json`、`docs/PROJECT_MAP/09A_HINT_CATALOG.md` | ⚠️ **三份机器生成的产物重跑了一遍**（不是我改的东西坏了，是**别人未提交的后端改动**让它们过期：`shipper.py` 挪了行号、`products.py` 挪了行号）：`08A` 与 `ai_read_catalog.json` 的差异**只有行号位移**（端点数 193 不变、角色不变，已逐行确认）；`09A` 是 `.kt` 文案条数变了。⛔ **没有手写这三个文件**，全部是脚本重生成的。另：本机后端已重启（`_check_backend_fresh` 转绿） |
| 2026-09-22 03:0x | **商品外观做深**（我） | `ui/common/ProductCardKit.kt`、`ui/dispatcher/ProductsScreen.kt`、`ProductBatchScreen.kt`、`ProductSortScreen.kt`、`InventoryScreen.kt`、`BatchPriceSheets.kt`、`PriceMatrixScreen.kt`、`ui/common/ProductPicker.kt` | 都是商品管理这一条线**我自己**的文件（`ProductPicker.kt` 上次动它是 2026-09-20 的账本「记一笔账」那一轮，已收工；声明页上那一轮**没有**写"明确不碰"）。`ProductPicker.kt` 只改 `ProductRow` 一个函数 + 加一个私有事实构造器，其余一行未动 |
| 2026-09-21 23:5x | **「我的」页改版**（我） | `ui/nav/Routes.kt`、`ui/nav/NavGraph.kt`、`ui/home/RoleHomeScreen.kt`、`ui/theme/Color.kt` | **追加式/单点**改动：① `Routes.kt` +1 常量 `BASIC_SETTINGS`；② `NavGraph.kt` +1 个 `composable`；③ `RoleHomeScreen.kt` 两处 —— profile 那一 Tab 不吃 Scaffold 的**顶部** inset（否则深色头部画不到状态栏下面；其余 Tab 一行未动）、去掉已无处可用的 `onOpenMessages` 接线（「消息中心」那一行按用户要求删了）；④ `Color.kt` **只追加**两个头部颜色常量。四处改前都重读了最新内容 |
| 2026-09-21 23:5x | **「我的」页改版**（我） | `_tools/ai/_check_ai_guardrails.py`、`_tools/ai/_check_notify_guardrails.py`、`_tools/ai/_reverse_verify_sun_theme.py`、`_tools/ai/_reverse_verify_notify.py` | ⚠️ **改的是别人功能线的红线/反向验证**（随日落 §21、消息提醒 §9）。**只把锚点搬到代码真正所在的位置，没有放宽任何判据**：`_check_ai_guardrails` 那两处 `profile` 变量改成"`ProfileScreen.kt` + `BasicSettingsScreen.kt` 拼起来"（随日落那一行搬进了「基础设置」子页）、`_check_notify_guardrails` 把"消息提醒点得进去"拆成两段（页面接 `onOpenAlerts` **且** 行组件真的把 `onClick` 接到 `clickable`，合起来不比原来那条单文件正则弱）、`_reverse_verify_sun_theme` 4 条注入改指新文件、`_reverse_verify_notify` 换锚点并**新增 1 条**注入（"行组件把 onClick 收下就丢"） |
| 2026-09-21 22:2x | **提示/说明统一化**（我） | `AGENTS.md` | ⚠️ **共享入口文件**：只**插入一节**「给三台模拟器装包：用共享工具」（新工具 `_tools/qa/_install_all.py` 怎么用 + 用户定的前提"有人在干活就各装各的"），没有改动任何原有章节 |
| 2026-09-21 22:0x | **提示/说明统一化**（我） | `ui/profile/ProfileScreen.kt` | ⚠️ **动了别人的文件**（司机线在改，用户 22:0x 拍板「可以你现在就改吧」）。改前重读了它 21:39 提交后的最新内容；**只改三处**：①「提示」那一格的副标题与注释（旧机制口径 → 总开关口径）、`alwaysOn` → `setByUser()`、删掉本地镜像；②「消息提醒」副标题 → `Hint`；③「随日落」那一行按 `autoBySun` 分 `Hint`/`Text`。另清掉随之悬空的 2 个 import（`_check_dead_code.py` 抓的）。**没动**它的滚动修复与其它任何一行 |
| 2026-09-21 20:5x | **提示/说明统一化**（我） | `ui/common/Components.kt` | **摘掉** `HintOnce`（连同它那句"最多出现 3 次"的 KDoc），在原地留一段指路注释；顺手删掉随之失效的 `import ...core.HintPrefs`。函数搬进新文件 `ui/common/Hints.kt`（**同一个包**，所以 6 个调用点一行都没动）。这个文件别人也在改（药丸/弹层），我**只动了这一段**、改前已重读 |
| 2026-09-21 20:5x | **提示/说明统一化**（我） | `core/HintPrefs.kt` | 整文件改写（"每条最多 3 次"的 per-key 计数 → 一个总开关 + 首次登录那一轮的状态机）。**没有别的会话在改它**（上一次动它的是「全库精简」第八轮，已收工） |
| 2026-09-21 20:5x | **提示/说明统一化**（我） | `MainActivity.kt`、`ui/login/LoginViewModel.kt` | 各**追加**几行：根上提供 `LocalHints`、冷启动 `onAppStart()`、登录成功 `onLogin()`。没有动这两处原有的任何逻辑 |
| 2026-09-21 3:0x | **派单员语音播报**（我） | `ui/dispatcher/DispatcherPoolViewModel.kt` | `confirmAssign()` 成功分支**追加两行**（`container.newOrderPlayer.stop()` + 注释）：派完立刻闭嘴。没有动它的取数/批量派单逻辑 |
| 2026-09-21 3:0x | **派单员语音播报**（我） | `_tools/media/_gen_new_order_clip.py` | 加 `--kind {driver,dispatcher}`（两句文案/两个输出路径）+ **`DEFAULT_VOICE` 由云健改成晓晓**（用户选的音色；旧默认值是"素材变男声"的根因） |
| 2026-09-21 3:0x | **派单员语音播报**（我） | `ui/profile/ProfileScreen.kt`、`ui/profile/AlertSettingsScreen.kt` | 「有没有语音」从 `isSpoken` 改用 `hasVoice`/`voiceKind`（司机+派单员）；试听改成播**当前角色**那一句；顺手把两处过期文案（70%→80%、约 3 秒→约 5 秒）改对 |
| 2026-09-20 | 货主账本改造 | `AGENTS.md` | 只加了一段指向本文件的说明 |
| 2026-09-20 20:5x | 派单员账本第五轮 | `android/.../ai/AiWriteService.kt` | **只追加两行 import**（`buildJsonObject` / `put`）：货主账本那 5 个新数据源方法用到它们而文件里没导，**整个 App 编译不过**；已重读最新内容后追加，未动任何逻辑 |
| 2026-09-20 20:5x | 派单员账本第五轮 | `android/.../test/.../ai/AiWriteTest.kt` | ⚠️ 我**临时**给 `FakeDs` 补了 6 个空实现（`mySettleOrder`/`mySettlements`/`createMySettlement`/`revokeMySettlement`/`restoreMySettlement`/`isMemberShipper`）跑了一次单测，**跑完按 sha256 逐字节还原**（还原后 `d7f63d0bd38b` 一致）。你们那边这 6 个方法还缺实现，测试源集现在编译不过（885 个单测跑不出来）——那是你们的活，我没替你们写 |
| 2026-09-20 20:5x | 派单员账本第五轮 | `docs/AI_WORK_CLAIM.md` | 本节（追加式） |
| 2026-09-20 20:xx | 派单员账本改版 | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` | 只改 §4.13 三处 + 新增 §4.14（筛选三段） |
| 2026-09-20 20:xx | 派单员账本改版 | `docs/ACCOUNTING_V2_DESIGN.md` | 只改 §4.5 里那段核销规则的注释 |
| 2026-09-20 20:xx | 派单员账本改版 | `docs/PROJECT_MAP/08_CODE_LOCATOR.md` | 只重写「账本管理」那一行（另一会话改的是货主账本/我的账本那几行，互不重叠；改前已重读） |
| 2026-09-20 20:3x | 司机端已完成页修复 | `docs/PROJECT_MAP/08_CODE_LOCATOR.md` | 只重写「司机 | 任务列表」那一行（另一会话改的是账本那几行，互不重叠；改前已重读） |
| 2026-09-20 21:0x | **货主账本改造**（我） | `android/.../test/.../ai/AiWriteTest.kt` | **补上 `FakeDs` 缺的 6 个实现**（`isMemberShipper` / `mySettleOrder` / `mySettlements` / `createMySettlement` / `revokeMySettlement` / `restoreMySettlement`，外加三个可设的替身字段与 `myLedgerCalls` 调用记录）。这是"接口新增方法时必须补的另一半"——缺了它整个测试源集编译不过。**已按对方要求由我来做**（他们的临时补丁已按 sha256 还原）。 |
| 2026-09-20 21:0x | **货主账本改造**（我） | `android/.../ui/shipper/ShipperLedger*.kt`、`ai/AiWriteShipperLedger*.kt` | 搜索加了 **350ms 防抖**（每个字一次请求本来就浪费；真机上 `adb shell input text` 一次灌 11 位时输入框只落进去 2 位，虽然后者经慢速逐字输入证实是 adb 的假象，防抖仍然留着） |
| 2026-09-20 20:1x | **货主账本改造**（我） | 本机后端（uvicorn :8000） | **重启过一次**：`_check_backend_fresh.py` 红着（进程跑的是旧代码，我新加的 `/shipper-ledger` 端点根本不存在）。⚠️ 20:18 之后那个进程是**别人**起的（我只 kill 了自己起的那个）——反正重启即加载新代码，两边都受益 |
| 2026-09-20 21:3x | **货主账本改造**（我） | `android/.../ui/common/DatePresets.kt` | **只加一档「近一年」**（`LAST_YEAR` + `ROW` 末尾 + `rangeOf` 一行），已有 9 档的区间**一个字都没动**（用户点名要"近一年"这个预设） |
| 2026-09-20 22:5x | **货主账本改造**（我） | `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` | §4.15 **追加第 6 条**（药丸是页面级的：切视图不许藏、页面里不许再冒出胶囊行）；另把 §4.12 里"账本页共用胶囊行"那**一句**过期描述改对（改前已重读该段，没动别人的行） |
| 2026-09-20 22:5x | **货主账本改造**（我） | `docs/PROJECT_MAP/08_CODE_LOCATOR.md` | 只在**自己那一行**（「货主 \| 账本」）尾部追加两条（共用窗口 + init 必须先 switchPreset）。⚠️ 这条线**已被 `--deep` 还原过两次**，谁重写这份文档请只改自己那几行 |
| 2026-09-20 22:5x | **货主账本改造**（我） | `android/.../ui/common/Components.kt` | **一个字符都没改**（`DatePresetPill`/`DatePresetDialog`/`DatePresetRow` 都是第五轮做的，我只调用）——登记在这里是为了让人知道"我碰过这个文件"是误读 |
| 2026-09-20 23:5x | **账本记一笔账**（我） | `android/.../ui/common/ProductPicker.kt` | **只追加**一个 `single: Boolean = false` 参数（选品页的**单选**模式：再挑一件是**换掉**而不是累加）+ 单选时按钮写「用这件」、提示语写「只挑一件」。**默认 false = 下单页一个字都没变**（下单页那次调用没传它）；改前已重读最新内容 |
| 2026-09-20 23:5x | **账本记一笔账**（我） | `android/.../ui/nav/Routes.kt`、`NavGraph.kt` | 追加一条路由 `LEDGER_CREATE` + 一个 import + 账本页多一个 `onCreateEntry` 回调（都是追加，没动别人的路由） |
| 2026-09-21 1:0x | **运费模板/计费规则**（我） | `_tools/ai/_check_ai_guardrails.py` | **只改两条判据**（① `driver_pay` 里那行改成 `else base_rate` —— 按分类定价把基价拆成了 `base_piece/base_rate`，判据的意思没变；② 主数据删除那条从「整段不许出现 `db.delete(`」改成「不许物理删**你刚查出来的那一行**」—— 运费模板删除时要顺手清掉关联表，整段扫会把它判成违规）。改前已重读最新内容 |
| 2026-09-21 1:0x | **运费模板/计费规则**（我） | `_tools/qa/_check_input_rules.py` | 只在 `EXCLUDED` 里**追加一条**理由（司机编辑页那个只读下拉框的标题里有「费」字，被误认成金额输入框） |
| 2026-09-21 1:0x | **运费模板/计费规则**（我） | `_tools/ai/_gen_ai_toolmap.py`、`_read_coverage.py`、`_write_coverage.py` | 追加：模块中文名一行、两个新读端点的理由、五条新写端点的「不做」理由（都是追加） |
| 2026-09-21 1:0x | **运费模板/计费规则**（我） | `ui/dispatcher/UsersManageScreen.kt` / `UsersManageViewModel.kt` | 删掉司机编辑页的「固定工资」「计费方式」两个老字段（VM 也不再发这两个字段）—— 用户点名「计费规则就已经包括他们上面的」 |
| 2026-09-20 23:5x | **账本记一笔账**（我） | `ui/dispatcher/DispatcherLedgerScreen.kt` / `DispatcherLedgerViewModel.kt` | 删掉记账弹窗与它的草稿状态（**同一件事不留两份**），换成 `LaunchedEffect(Unit) { vm.onEnter() }`。`_check_user_search` 钉的锚点（`KpiBlock(` / `SearchField(` / `UserSearch.filter(accountRows()` / `LedgerAccountRow(` 恰好两处）一个没动；账本页的版式（药丸 + 抽屉 + 无图）也没动 |

---

## 已完成

### [2026-09-22 08:0x → 09:0x] 会话：**运费模板「新建」从弹窗改成底部抽屉（拉满到最上面）+ 表单走白卡无边框行**＋**顺手抓到并修掉 4 处端点 500**【已完成】（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）

**用户需求（原话）**：「把那个**运费模板**给搞一下 —— 运费模板**右上角**不是有 3 个（按钮）…是那个**新增模板**啊，
**新增模板也按照我们的样式**进行来，但是他**不要使用弹窗**啊，**使用底部抽屉**，并且**底部抽屉是拉到最上面**。」
（做完之后他又补了一句「地点库的卡片也要信息明确」→ **当场改口**：「哦我搞错了地点库，你不需要搞啊，
接着搞你的就行了，**地点库是别人的工作**」→ 地点库那条**不在本轮**。）

**结果**
- 改：`ui/dispatcher/FreightTemplatesScreen.kt`：`FreightTemplateDialog`（`AlertDialog` + 1 个 `OutlinedTextField`
  + 4 个 `SoTextField`）→ `ModalBottomSheet`（`skipPartiallyExpanded = true` ＋ 内容 `fillMaxHeight()`
  ＝ 一打开就**拉满到最上面**）＋ `FormGroup` 三张白卡（线路与价格 / 算哪几类货 / 备注）＋
  `FormInputRow` / `FormPickRow` 无边框行；错误落在抽屉里（`FormErrorLine`）
- 改：同页 `ViewModel`：`showDialog` → `showSheet`；新增 `formError` —— 原来校验/保存失败写的是**页面级
  `error`**，那是**抽屉背后的 snackbar**（抽屉是另一个窗口，正好盖住它）＝"点保存没反应"
- **真机（emulator-5558 借来当派单员，验完已登回司机 13800000003）**：抽屉一打开**占满整屏**、
  底色 `#F0F0F0` 中性灰 + 三张 `#FFFFFF` 白卡（`_px_probe.py` 沿列量出来的）；
  空表单保存 → 抽屉里出「请填写价目名称…」；线路下拉从线路库选了 13 条里的一条；
  **保存 → 库里有这一条**（`GET /freight-templates` 数到它，id=9）；卡片「删除」→ 确认 → 库里 8 条、
  E2E 那条 0 条（软删）。截图 `_archive/freight-01-sheet.png`
- 新增：红线 `_tools/qa/_check_sheet_form_pages.py`（**43 项**，名字从 `_check_account_manage_ui.py` 改过来
  —— 它现在管**一类页面**：账户管理 + 运费模板 + 全 App 抽屉底色）＋ 反向验证 **24/24**

**⚠️⚠️ 本轮抓到的真事故（不是这一轮的活儿，是我上一轮留下的）：4 个端点每次调用都 500**
- 现象：真机上点「保存」→「网络连接失败：unexpected end of stream」，**列表永远是空的**
- 根因：上一轮"挑东西的列表按常用度排"把 `with_popularity(stmt, Model, kind, <当前用户>)` 加到 12 个端点，
  而 **4 个端点的用户参数叫 `_`（`_: User = Depends(...)`，"只要鉴权不要值"的老写法）或 `user`**，
  复制粘贴过去就成了 `NameError: name 'current' is not defined`
  → `arrears` / `driver_billing_rules` / `freight_templates` / `price_rules`
- ⛔ **编译期看不出来、单测也没盖到**（`compileall` 只查语法；pytest 没打那几个端点）
- 修法：3 处把形参改回 `current:`、`price_rules` 改用它的形参 `user`；
  **真打四个端点验证：全部 HTTP 200**（原来是 500）
- **新增红线 `_tools/qa/_check_usage_call_args.py`（37 项）**：`usage_service.*` 每一次调用的**裸标识符实参**
  必须在所在函数里有定义（形参 / import / 模块级 / 前面赋过），＋ 两条防空转（调用数 ≥12、后端文件 ≥30）。
  配套反向验证 `_reverse_verify_usage_call_args.py` **4/4**（含"把参数名改回 `_`"这一条原样复发）
  - ⚠️ 判据第一版把**多行 import**（`from app.models.x import (\n    DriverBillingRule,\n)`）漏了 →
    当场把 `DriverBillingRule` 判成"没定义"（**假阳性**）；假阳性比漏报更耗人，已修
  - ⛔ 为什么不做成通用 linter：本机没装 `pyflakes`/`ruff`/`flake8`（实测 No module named ruff），
    给项目加新依赖要用户拍板 —— 所以只钉这一类，并在脚本里写明

**⚠️ 交叉点（都是"我的改动波及了别人的东西"，已同步）**
1. `backend/tests/test_auth.py` + `test_product_sort_order.py` —— 上一轮的排序规则让这两条测试**红了**
   （它们写的是老口径"没排过就按 id 倒序"）。按用户定的规则（常用度 → **先创建的在前**）改**测试**，
   **没有改代码**；`test_auth` 那条把"id 倒序"的断言换成它自己的题目（q 为空时行为完全一致），
   排序本身钉在 `_check_list_order.py`（53 项）与 `test_audit_round16_counters.py`。pytest **693 passed**
2. `docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` **重生成**（我改的参数名 + 别人新加的一个端点 → 193→194）
3. `_tools/qa/_check_input_rules.py`：`FIELD_NAMES` 追加 `FormInputRow`/`FormTextAreaRow` ＋ `_titles` 认
   共用行的纯字符串 `label = "…"`。**这是真缺口**：全 App 正把表单逐页搬到共用行，而共用行不在扫描名单里
   → 那些框**从判据里直接消失**（换过去时顺手漏掉 `InputRules` 也不会报）。追加后 110→**132** 个框、
   25→**32** 个认得出类别，全过；新冒出的 1 条假阳性（下单页自由文本**备注**框，placeholder 里写了
   「到了先打电话」）按脚本自己的规矩写进 `EXCLUDED` 并给了理由
4. `_tools/qa/_reverse_verify_input_rules.py`：修 **3 条陈旧锚点**（`FIELD_NAMES` 那行是我改的；另两条是
   **别人改文件后留在那儿的** —— 商品售价的注入点随商品改版搬到了 `ProductFormScreen`、下单页那条的锚点
   从 `OutlinedTextField` 变成了 `FormInputRow`）。这条反向验证只在 `--deep` 里跑所以一直没人发现。现 **12/12**
5. ⚠️ **别人改了我这一页**（好事）：`AccountManageScreen.kt::AccountAction` 与订单卡的 `CardActionIcon`
   被 `session-faa17a77` 收成了一个共用控件 → 我那条"圈底图标 + 文字"的判据原本钉的是实现名 `TintedIcon`，
   **当场假红**。已改成钉**意图**（共用控件里必须有圈底图标 **且文字要真的传下去** `label = …`），
   并补了注入 ㉔（把文字丢掉必须报红）—— 现在 **24/24**

**⚠️ 追加（用户看到第一版之后：「你这个没改啊」）—— 他圈的是**列表页**，不是抽屉**
- 他发来的截图把**右上角那三个按钮**（待定价 / 分类管理 / 新建）圈住、画箭头指到左下角三个空框
- ⚠️ 起因之一：我上一轮**只改了「新建」里面那张表单**，列表页外观一点没动 —— 他不点「新建」就看不到变化；
  而他截的那台（5554，标题被挤成「运费…」正是旧版三个按钮占位的样子）装的是我**更早一版**的包
- 拍板（问他两问，都选了）：**「挪到底部做成三格，照抄商品管理」**
  （左「分类管理」· 中「新建价目」语义色圆钮 · 右「待定价」），**左边分类栏本身不动**
- 改：`FreightTemplatesScreen.kt` —— 顶栏 `actions` 整段删掉（只留标题与返回），
  新增 `bottomBar = { FreightBottomBar(...) }`：`Surface(shadowElevation = 8.dp)` ＋
  `navigationBarsPadding()` ＋ 左右 `FreightBottomCell`（**无边框**图标+文字）＋
  中间 `FilledIconButton(52dp)` 用**运费模板的语义色深靛 `0xFF283593`**
  （一色一功能：工作台那一格、卡片上的车图标同色；⛔ 不用钱的橙——同屏价格已是橙的）
- ⚠️ **没有**去动 `ProductsScreen.kt` 那份（`ProductsBottomBar` / `BottomCell` 都是 private，
  而且**别人的反向验证钉着这两个函数名**，动它就得连他们的注入锚点一起改）→ 先在这一页照抄一份，
  注释里写明"**同一套形态的第二处**，第三页再提成 `ui/common/` 共用件（与 `FormGroup` 那次一样）"
- **真机验证**：5558 与 **5554** 都装了新包，底栏三格都在；5554 的截图沿 y=2205 一行量到
  **`#283593`**（中间那枚圆钮）✓。截图 `_archive/freight-02-bottombar.png`（5558）、
  `freight-03-bottombar-5554.png`（5554）
- 判据加到同一节（§6）：底栏三格在、顶栏没有 `actions`、中间是语义色圆钮、左右无边框格 →
  `_check_sheet_form_pages.py` **47 项**；反向验证 **26/26**（新增 ㉕ 摘掉底栏、㉖ 圆钮换成描边按钮）

**明确不碰**：`ui/shipper/OrderCreateScreen.kt`（`session-78ebd95c` 正在改）、`ui/common/FormRows.kt`
（`FormGroup` / 那几种行**只调不改**）、订单两页、`ui/common/OrderCard.kt`、**地点库那一块**
（用户当场确认那是别人的活）、钱的算法。

### [2026-09-22 07:5x → 08:0x] 会话：**线路卡主次倒过来（线路大、联系人小）+ 共享地点卡片去掉照片**【已完成】（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**用户需求（原话）**
> 「那个**共享地点**的那个有一个不好的点就是，上完那个图片就**不要显示**了。还有那个 UI，
>  也就是那个卡片吧，**不是很好**啊，**很多信息由于显示图片导致了他那个地点的信息被丢失了**。
>  以前，他那个**线路的卡片也不要这样子**啊 —— 线路卡片重要的信息是什么？**重要的信息是线路啊**，
>  像什么**联系人和电话都是次要信息**，都可以**非常小**、都可以小一点，
>  而且这个线路的卡片**可以拉大一点、拉长也没关系**，因为线路本身信息量有点多」

**落地**
- **线路卡（`AddressScreen::AddressCard`）主次倒过来了**：
  · 起点/终点地址 `bodyMedium` → **`titleMedium` 加粗**、**不再限制行数**（卡片可以拉长）；
  · 联系人那一行 `titleMedium 加粗 + 圆头像块 30dp` → **`bodySmall` 灰字 + 22dp 小块**
    （上一版它比"起点/终点"还大，正好把主次说反了）。
- **共享地点卡（`OrderCreateScreen::SheetRow`）去掉左边那张 56dp 照片**（连带 `onPhotoClick`
  与那一份预览状态一起删掉，不留空线），地址行数上限 2 → **3** —— 地点信息重新占满整行。
  ⚠️ 照片**不是**彻底没了：表单里的图片条（线路/地点图片、下单页位置图片）点开看大图还在。

- **地址库（选收货地址抽屉）的「线路」那一段是同一个毛病，一起改了**（用户第三轮，指着那一屏）：
  「这个地点库…这个**线路**也做个改变啊，这样子不好啊，主要我们的（重要）信息是**线路**，
  其次**联系人什么的都可以在下面放小一点**。而且他这个卡片是**可以做大一点**的」。
  → `OrderCreateScreen::SheetRow` 多了一个 `origin`（只有线路有）：有起点时这一行主角变成
  **起点 ○ → ↓ → 终点 📍（`titleMedium` 加粗、最多 3 行）**，**联系人 + 电话退到下面 `bodySmall` 灰字**；
  右侧「有导航 + ⋮」抽成共用的 `SheetRowTrailing`（两种主体各抄一份迟早有一边忘了接）。
  ⚠️ 上一版这一行的主角是**收货人姓名 + 电话**（大字）—— 和线路卡犯的是同一个错。

**验收**：`_check_all.py` **64/64** · `_check_form_panel_style.py` **18/18** ·
`_check_product_card_single_source.py` **53/53** · 死代码 **0** · 编译 + `assembleEmuDebug` +
装到 5554 成功 · 真机截图 `21-改后-线路卡(线路大-联系人小)`、`22-改后-地址库线路(A到B大-联系人小)`。
`_check_all.py` 现在有 **3 条红，全部是别人的在飞改动**（`_check_backend_fresh` 本机后端比他们的
后端源码旧 · `08A` 端点索引过期 · `_check_page_truncation_wiring` 卡在**他们的** `ShipperOrdersScreen.kt`
少了"出路关键词"）—— 我**没有**替他们重启后端/重生成索引（那几个文件他们正在改，动了会打断他们）。

⚠️ 这一轮被别人的半成品挡过 **3 次**（`FreightTemplatesScreen.kt` 两次语法/未解析错误、一次
Gradle 抢占），都按规矩**等**而不是去改他们的文件。


### [2026-09-22 07:2x → 07:5x] 会话：**共用表单行补「图标 + 内嵌卡」、共享库改卡片、图片点开看大图**【已完成】（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**用户需求（原话，四件事）**
> ① 「现在的新卡片样式对应的**图标和（语）义色不能去掉**啊。**该有的还是得有的**」
> ② 「你卡片是加出来的，但是里面的**线框**还是搞一下吧。也不说搞线框吧，而是说，在**内嵌卡片**——
>   就是**卡片内嵌卡片**，就是每个选择就相当于一个、**每个输入相当于卡片**」
> ③ 「那个**共享库**没有改…它属于跟**商品管理**类似的：**左边是分类选择**，右边是共享库…
>   那个**不要用列表的形式**，也使用**卡片**的形式，就是**类似商品一样**…**重要的信息要优先显示**」
> ④ 「**图片**啊，他要支持**预览**，点击图片支持预览…他那个照片，**他不知道他自己拍的怎么样**」

**落地**
- ① + ② 都在 `ui/common/FormRows.kt`：`FormRow` 及五个变体加 `icon` / `iconTint`
  （原来 `OutlinedTextField(leadingIcon = …)` 里的图标与语义色**跟着搬过来**，一行都没省）；
  **每一行自己就是一张内嵌卡**（`surfaceContainerLow` + 圆角 12、**不画边框**），分组仍是白卡
  → 就是他要的"卡片内嵌卡片"。图标已补回 `AddressScreen`（16 行）与 `OrderCreateScreen`（8 行）。
- ③ `OrderCreateScreen::SheetRow`（地址库抽屉三段**共用**的那一行）从平铺行 + 分隔线改成**白卡**；
  照片 40 → **56dp**、标题升到 `titleMedium` 加粗（"重要信息优先"落在"照片更大、名字更重"上）。
  ⛔ 三段一起改：只改共享地点会让同一个抽屉里三段长得不一样。
- ④ 新增 `ui/common/ImagePreview.kt`（**全库唯一一处**）：全屏黑底 + 点任意处关闭 + 多张左右翻页 +
  `n/N` 计数；收的是 **Coil 的 model（`Any`）**，所以**刚拍的本地 `File` 和已上传的 URL 都能预览**
  —— 只收 URL 的话，"刚拍的那张"恰好成了唯一看不了的。已接：线路/地点图片条、下单页位置图片、共享库卡片图。
- ⚠️ 顺带修掉一个**真机上才看得出的坑**：`AsyncImage` 加载中/失败时是透明的，而它在共享库卡片最左边
  占着 56dp —— 没加载出来时整列卡片像"标题被居中"（其实左边空了一块）。现在那块加了浅底。

**验收**：`_check_form_panel_style.py` 18/18 · `_reverse_verify_form_panel.py` 8/8 · 死代码 0 ·
`_check_all.py` **62/63**（唯一那条红是**别人的** `FreightTemplatesScreen.kt:334`，
那条线正在改那个文件，我一个字没碰）· 真机 5554 两屏
（`19-改后-新增线路(图标回+内嵌卡)`、`20-改后-共享地点(卡片+大图)`）。
⚠️ 中途被别人的半成品挡过一次编译（`FreightTemplatesScreen.kt` 的 `showSheet` 未解析，约 10 秒后他们自己修好）。

**仍然没做**：白卡规范扫尾剩下的页面（`DispatcherPoolScreen` 5 / `UsersManageScreen` 5 /
`AiSettingsScreen` 4 / …，基线 59 处）—— 等订单线与账户线收工再扫。


### [2026-09-22 07:0x → 07:4x] 会话：**账户管理卡片改版 + 新增/编辑抽屉去线框 + 全 App 底部抽屉底色"去灰蓝"**【已完成】（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）

**用户需求（原话）**：「那你**更改一下账户管理的卡片样式**按照要求进行更改，同时他那个**新增的那个弹窗**也就
**底部抽屉**呃也采用**不要使用那个线框**而是**用卡片的形式**；还有一点，为什么**每次底部抽屉弹出来那个颜色
都是灰蓝灰蓝的**，不要啊，**改成底部灰（色）没关系，卡片一定要是白色的**，这样子就产生一个对比上去的，让人知道。」

**根因（反编译证实，不是猜）**：「每次抽屉都是灰蓝」是 **M3 的默认值**，不是谁写错了一个颜色 ——
`ModalBottomSheet` 的容器色默认 = `BottomSheetDefaults.ContainerColor` →
`SheetBottomTokens.DockedContainerColor` → `ColorSchemeKeyTokens.SurfaceContainerLow`
（material3 **1.3.2** 的 `classes.jar` 里 `javap -c` 看到的常量池），
而本项目那个 token 是 `#EDEFF4`（B 通道比 R 高 7 → 就是那个"灰蓝"）。
→ **改这一个 token ＝ 改全 App 19 个抽屉**，不必去动那 19 个调用点（其中一半正是别人在改的文件）。

**结果**
- 改：`ui/theme/Color.kt`（新增 `SheetSurface = #F0F0F0` 中性灰，并写清它管着哪件事）、
  `ui/theme/Theme.kt`（亮色 `surfaceContainerLow = SheetSurface`；**暗色刻意不动** —— 亮暗的分层方向是反的）、
  `ui/dispatcher/AccountManageScreen.kt`（列表卡重排 + 动作左/右分区 + 抽屉改成白卡表单）、
  `ui/dispatcher/AccountManageViewModel.kt`（抽屉内那一行红字 + 保存失败不再顶掉整页）
- 新增：红线 `_tools/qa/_check_sheet_form_pages.py`（**27 项**）+ 反向验证
  `_tools/qa/_reverse_verify_sheet_form_pages.py`（**16/16**）+ 量像素工具 `_tools/qa/_px_probe.py`
  （⚠️ 这两个脚本**当天晚些时候改了名**：原名 `_check_account_manage_ui.py` / `_reverse_verify_account_manage.py`；
  运费模板的「新建」也搬进抽屉之后，它们管的是**一类页面**，名字得跟着走）
- **真机（emulator-5558 借来当派单员，验完已登回司机 13800000003）**：
  抽屉底色实测 **#F0F0F0**（B==R，中性）、卡片 **#FFFFFF** —— 同一条列扫描里一起量到的；
  **对照 = 改前**：另一位会话今天早些时候截的「新增线路」抽屉
  （`docs/screenshots/product-form-20260921/17-*.png`），同一条扫描量到的是 **#EDEFF4**。
  ⛔ **我没碰过的页面也一样**：库存管理 → 出入库流水那个抽屉同样是 `#F0F0F0`（证明是"一处说了算"）。
  功能：角色下拉（6 个角色、当前项带 ✓）✓ · 空表单保存 → 抽屉里出「请填写姓名」✓ ·
  **手机号重复 → 抽屉里出「该手机号已存在」而列表原封不动**（改前会把整页顶成错误页）✓ ·
  长按手机号 → 粘贴到搜索框得到 `13800000001`（剪贴板真的写进去了）✓ · 编辑回填姓名/手机号/角色 ✓
- 验证：红线 **27/27** · 反向验证 **16/16** · `_check_all.py` **63/63** · Android 单测 **1032 / 0 失败**
- 截图：`_archive/acct-01-list.png`（列表卡）/ `acct-03-sheet.png`（抽屉）/ `acct-04-dup-error.png`（重复手机号）/
  `acct-05-longpress.png` / `acct-06-edit.png` / `acct-07-other-sheet.png`（**别的页面**的抽屉）
- ⚠️ **交叉点**：`_tools/qa/_form_panel_baseline.txt` —— 这一页的描边输入框少了 3 处，
  而 `session-78ebd95c` 的 `_check_form_panel_style.py` 有一条"总数降下来就必须把基线降下来"的反向约束；
  他们随后自己跑了 `--update`（现在基线 67、总数也是 67）→ **已一致，我没有动那个文件**。
- ⚠️ 给下一个人的话：`ui/common/FormRows.kt` 里**没有** `visualTransformation` 参数，
  所以密码那一行是 `AccountManageScreen.kt` 里的私有 `AccountSecretRow`（底下仍然是共用的 `FormRow`，
  形态不会长出第二种）。**第三处**再要密码行时把它提进 `FormRows.kt`（那时和那一轮的人对齐）。

### [2026-09-22 03:1x → 07:0x] 会话：**「分组一律白卡」定成规范（先落「新增线路」）+ 线路卡改成 A→B 主角**【已完成】（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**用户需求（原话）**：「…只是用**线框**框起来的话太不美观了，而且也不够**醒目对比**，
所以把他们改进这种**白色的卡片样式**…**这就是个设计规范，包括以后也是这样子啊，所有都要这样子去改**」
「还有一点就是**线路的这个卡片这个样式不好**…**联系人啊，可以放在下面**，
但是**线必须放在从 A 到 B**，然后那个**编辑和删除稍微放在左边**…**一上一下**的关系，
**上面是删除、下面就是编辑**」
→ ⚠️ 后半句他**当场改口**：「**啊说错了，说错了，那个编辑和删除不要在左边是在右边了**」
（动作收在**右边**，仍然一上一下、上删除下编辑；左边那一条留给 A→B 轨道）

**文件清单**
- 改：`ui/shipper/AddressScreen.kt`（新增/编辑**线路**的抽屉改成 4 张白卡 + 共用表单行；
  线路卡重排为「左：删除/编辑一上一下 · 右：起点→终点轨道 + 联系人在下面」）、
  `ui/common/FormRows.kt`（+ `FormActionRow`「点进去做一件事」/ `FormTextAreaRow`「长文本上下排」）
- 新增：红线 `_tools/qa/_check_form_panel_style.py` + 基线 `_tools/qa/_form_panel_baseline.txt`
  + 反向验证 `_tools/qa/_reverse_verify_form_panel.py`
- 同步：`docs/PROJECT_MAP/06_DESIGN_SYSTEM.md`（新规范）、`08_CODE_LOCATOR.md`（地址与联系人那一行）

**⚠️ 交叉点**：`AddressScreen.kt` 里**别人有一处未提交的改动**（`Text` → `Hint`，提示统一化那条线，
mtime 22:09）—— 我**原样保留**了它，只改我这两块；该文件没有任何会话在「进行中」里声明。

**⚠️ 明确不碰**
- 全库其余描边输入框（28 个文件）：这一轮**只落这一页** + 定规范 + 立**只许减不许增**的基线，
  扫尾按页面分批（待改清单由红线脚本自己算，不手写）。
- `backend/`、`ui/common/Hints.kt`、`core/HintRound.kt`、`_tools/qa/_check_hints.py`、
  `_tools/qa/_hint_inventory.py`（提示统一化那条线正在动）。

**结果**
- **「新增线路」抽屉改成 4 张白卡 + 共用表单行**（联系人 / 起点 / 终点 / 线路图片+设为默认）；
  同一页的**联系人**、**地点**两个抽屉一并改 → `AddressScreen.kt` 的描边输入框 **9 → 0**。
- `ui/common/FormRows.kt` 补两种行：`FormTextAreaRow`（长文本：标签在上、值在下占满整宽 ——
  地址塞不进右半栏）、`FormActionRow`（点进去做一件事，右边只有一个 `>`）。
- **线路卡重排**：左边一整条 **起点 →（连线 + ↓）→ 终点** 轨道（终点加粗），联系人退到下面；
  右侧一列 **上删除、下编辑**（⚠️ 用户先说了"放左边"、几分钟后当场改口"不要在左边、是在右边了"）。
- **定成规范**：`06_DESIGN_SYSTEM.md` 新增 **§5.0「分组一律白卡，不许用描边框当分组」**；
  另把用户对另一个会话说的「**编辑一定在右边、相反的操作在最左边**（惯用手是右手）」
  也记进 §5（**横排**适用；竖排的一上一下不受它管 —— 两条规则管不同的轴）。
- 判据 `_check_form_panel_style.py`（17 项：已改页面描边输入框必须 0 + 每种点名的共用行都还在用 +
  **全库总数只许减不许增**，基线 `_form_panel_baseline.txt`）+ 反向验证 `_reverse_verify_form_panel.py` **8/8**。
  ⚠️ 反向验证自己抓到两个**假绿**并已修：① 判据原写"用到两种以上共用行"→ 把其中一种换成自己写的照样绿，
  改成"每一种点名的行都必须出现"；② 基线是**上限**，别人刚清理过就留下余量、注入一处顶不破它
  → 反向验证开跑前先把基线收紧（跑完原样还原）。另：那条"改好了要降基线"从**报红**改成**只提示**
  （多会话仓库里别人顺手清理一页就会红，红几次大家就把检查关掉 —— 本仓库踩过"永远红的检查=没有检查"）。
- **验收**：`_check_all.py` **63/63** · 真机 5554 两屏（`16-` 线路卡 A→B + 右下删除/编辑、
  `17-` 新增线路白卡分组）；并实测换成共用行之后**「收货联系人」那一行点开仍是原来的下拉**（菜单锚点没坏）。
- ⚠️ **待改清单（脚本自己算的）**：全库还剩 **67 处**描边输入框 / 25 个文件（最重：
  `DispatcherOrdersScreen.kt` 13、`OrderCreateScreen.kt` 9、`OrderDetailScreen.kt` 7…）。
  规范从今天起对**新页面**生效，老页面按页面分批改（改完一页 `--update` 降基线）。
- ⚠️ **交叉点**：另一个会话（`faa17a77`，订单管理那一轮，06:4x 起）**正在改** `DispatcherOrdersScreen.kt`，
  我跑检查时被它的注入锁拦过一次（等它跑完即恢复）—— 我一个字节都没碰它的文件。


### [2026-09-22 01:1x → 07:0x] 会话：**统一列表排序规则：常用度优先 + 先创建在前（跨端 / 跨模块）**（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）【已完成】

**用户需求（原话）**：「我们那个**隐性规则**，它是**优先级第一**的，它的规则是**大于基础排序**的……
**新建的在最前面只有第一天的时候有效**，第二天的时候它就会被优先级第一的规则给覆盖……
**技术是按人来搞**……看请求吧，他请求要拉哪个列表……**所有的列表，包括列表的抓取以及列表的排序**，
全按照我们这样的规则进行。」＋「机制你可以复用，但是得适配（看它完不完善；不完善就看能不能**两边都完全兼容**）」
＋「**撞车的部分**（商品）你暂时就不要去搞了，等它做完你再**记牢**」。

**规则（定案）**：挑东西的列表 = **① 常用度降序（按人）→ ② 先创建的在前（`id` 升序）**；
⛔ **看记录的列表**（订单/账本/现金流/消息/审计/库存流水/账单/结算/退货申请）**必须最新在前**；
分类类仍按用户手工 `sort_order`。商品**另加一层**：手工置顶/拖动排在常用度**前面**
（手动拖是更硬的意愿；用户未反对，若要改一行即可）。

**机制（复用 + 泛化，不另发明）**
- 新表 `usage_counters(user_id, kind, target_id, use_count, last_used_at)`（`kind` 常量只有一处：
  `services/usage_service.py`），旧表 `place_user_usage` 的数据由 `schema_bootstrap` **一次性迁入**
  （表本身由 `create_all` 建；只在"新表为空"时搬，防重复翻倍），旧表保留为备份、不再读写；
- `usage_service.record_usage()`：计数**由数据库自增**（照地点那套的规矩，防两部手机同时点丢一次）；
- `usage_service.with_popularity()`：**排序的唯一实现**（`coalesce` 不能省 —— 漏了会让"没用过的行"
  因为 NULL 沉到最后，与"先创建的在前"正好相反，而界面上只像"顺序有点怪"）。

**12 个列表接上**：联系人 / 线路（默认优先→常用度→先创建）/ 我的地点 / **共享地点库（改成按我自己
用过的次数，不再是全库次数）** / 商品 / 人（货主·批发商·司机）/ 客户 / 挂靠单位 / 车辆 / 司机计费规则 /
批发商专属价 / 运费模板。

**触发点（"真的用上了"才算，不是"点开看看"）**
- 下单接口新增**可选** `contact_id / address_id / location_id` → 下单成功即记：联系人/线路/地点/每个商品；
  代理下单时还记这位货主（⛔ 货主自己给自己下单**不记** —— 那是"我挑了我自己"，实测抓到的多余一行）；
- 派单接口记一次「这个派单员常用这位司机」（记在**派单员**名下）；
- App 侧：`OrderCreateRequest` 带这三个字段，VM 在**选线路/选我的地点**时记住 id、
  **地图自己选点**时清掉（不许把上一次选的线路记到这一单头上）。

**验证**：`_check_all.py` **60/60 全绿** ✓ · 新红线 `_tools/qa/_check_list_order.py` **46 项** ✓ ·
反向验证 `_reverse_verify_list_order.py` **10/10 被抓** ✓ · **服务端 E2E**（真接口 + 真下单）：
联系人 `37,38,39` → 用 39 下单 → **`39,37,38`** ✓、用量表出现 `contact 39 / product 1` ✓。

⚠️ **反向验证当场抓到我红线里的一个洞**（值得记）：`model.id.asc()` 在 `usage_service.py` 里出现两次
（"认不出人"的兜底分支 + 主排序分支），注入只改第一处 → 判据照样绿。已把判据收紧成
"降序 + 升序必须**连在一起**"。**这就是"给新功能开一条后路"的价值**。

**追加（2026-09-22 07:2x）：用户在「我的 → 基础设置」要了一个「重置计数」入口**（原话：
「在我的基础设置里加一个**重置计数**」）。
- 新增 `POST /usage/reset`（`backend/app/api/v1/usage.py` + `schemas/usage.py`）：**只清自己那几行**
  （`user_id == current.id`），返回清掉的行数；**硬删**（派生统计、不做软删 —— 与"用户数据一律软删"
  不冲突，但代价是**不可还原**，所以界面必须先说明再确认）。
- App：`ui/profile/BasicSettingsScreen.kt` 第三格「重置计数」（黄色提醒语义 + 后果说明走 `Text`
  **永不隐藏**）+ 复用 `DangerConfirmDialog` 确认框 + Snackbar 回执（**0 条也如实说**）。
- 登记：`_write_coverage.EXCLUDED`（不做 AI 动作的理由）、`_gen_ai_toolmap.MODULE_CN`（中文名）、
  `_check_audit_coverage.REASONS`（不写审计日志的理由）、`_hint_inventory.OVERRIDE`（那句副标题
  属**警告类**，不许被「提示」开关藏掉）。
- **真机验证（5554）**：那一格样式 ✓、确认框说清"只清你自己 + 没法还原" ✓、
  **点完 `user=1` 的计数 0 行、`user=2` 的 3 行原样保留**（证明只清自己 ✓✓）、
  回执弹出「本来就没有常用记录（列表一直是按创建顺序）」（0 条时的话术 ✓）。
- 红线扩到 **53 项** + 反向验证 **13 条**（新增：重置改成清全表 / 去掉确认框 / 那一格被删）。

**还剩一件（不影响使用）**
1. ✅ **真机全链路已验**（2026-09-22 07:1x，**用户手点一单**）：订单 `#427` 与用量行
   `user=1 kind=location target=2` **同一秒落库**（`22:30:30.751` / `.765`）→ 证明 App 真的把
   "这一单用的是库里哪一条"送上来了；同单还记了 `kind=user target=2`（代下单挑的货主）与
   `kind=product target=3`。随后派单员的「我的地点」顺序变成 **`2,1,3,4,5,6`**（刚用过的排第一、
   其余按"先创建的在前"），他没用到过的联系人仍是 `1,2,3,4,5` ✓ —— **规则在界面上生效**。
2. `place_user_usage` 与新表**暂时并存**（一个管"常用就自动进我的地点库"的阈值、一个管排序）——
   合一那一刀要连着 3 条判据一起搬（`_check_counter_updates.py` / 两份 `_reverse_verify_*` 都指着它的代码形状）。

**核心改动**：`backend/app/core/schema_bootstrap.py`（新表迁移；已在「进行中」写过那一行）。


### [2026-09-22 02:0x → 03:0x] 会话：**商品外观做深：库存挪到售价下面 + 五处商品渲染收成一套零件**【已完成】（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**用户需求（原话）**：「你还是把**库存**给移到**现在的那个售价的下面**啊，这样子**美观一点**」
「像我们这样子的形式——比如说**右边是分类、它是个条**的，那个**商品**啊，它其实是**有点区别的**…
你也**全部做深**吧，包括我们很多其他也是会**复用这些代码**的，或者说**继承**吧，
我们也就是说**其他地方你也得改**，最好是采用（通）用的继承，**上次你改一个地方，它就其他跟着改了**。」

**这一轮要做的两件事**
1. **商品卡**：库存从"图片下面横跨整卡"改成**售价的正下方**（图右边那一列 = 名称 / 售价 / 库存）。
2. **做深**：把"商品长什么样"收成**一套零件 + 一个事实构造器**，让**五处**渲染同一件商品的页面
   （商品管理卡 / 库存页卡 / 批量操作行 / 商品排序行 / 选品行）都从**同一处**取
   —— 下次再改"显示哪两个数字、什么顺序、什么颜色"，**只改一个地方**。
   ⚠️ 这一条**推翻**了 `ProductCardKit.kt` 顶上原先写的「刻意不抽一张通用卡」：用户这一轮明确要求
   抽（原文见上），所以改成"**零件 + 事实构造器共用、外壳各自组装**"，并把理由原地改写。

**文件清单**
- 改：`ui/common/ProductCardKit.kt`（+ `productFacts()` 事实构造器、+ `ProductLine` 行主体、
  + 库存文案/配色归一）、`ui/dispatcher/ProductsScreen.kt`（卡片改版）、
  `ui/dispatcher/ProductBatchScreen.kt`、`ui/dispatcher/ProductSortScreen.kt`、
  `ui/common/ProductPicker.kt`、`ui/dispatcher/InventoryScreen.kt`（库存配色判据归一）、
  `ui/dispatcher/PriceMatrixScreen.kt`（`parseColor` 换 `productNameColor`）
- 改：红线 `_tools/qa/_check_product_card_single_source.py`（新增"五处必须走零件"判据）、
  反向验证 `_tools/qa/_reverse_verify_product_card.py`
- 同步：`docs/PROJECT_MAP/06_DESIGN_SYSTEM.md`（§4.1/§4.2b）、
  `docs/PROJECT_MAP/08_CODE_LOCATOR.md`、`docs/plan-product-management.md`（§10）

**⚠️ 明确不碰（别人正在动）**
- `backend/app/core/schema_bootstrap.py`、`backend/app/api/v1/shipper.py`、`backend/app/models/usage.py`、
  `backend/app/services/usage_service.py`、`app/services/place_service.py`（`session-83da1ad7` 的
  「统一列表排序规则 / usage_counters」正在进行）→ 这一轮**零后端改动**。
- 提示体系：`ui/common/Hints.kt`、`core/HintRound.kt`、`_tools/qa/_check_hints.py`、`_hint_inventory.py`。
- `ProductsScreen.kt` 的 List 排序口径（`session-83da1ad7` 已声明"等我这期收工后再纳入"）。

**结果**
- **库存已挪到售价的正下方**（卡片右列 = 名称 / 售价 / 库存），真机看过：
  `docs/screenshots/product-form-20260921/11-改后-商品卡(库存挪到售价下面).png`。
- **"做深"落地**：新增 `ProductLine`（行/卡主体，槽位式）+ `productFacts()`（**唯一一处**定
  "显示哪两个数字、谁在前"）；**五个渲染商品的页面**（商品管理 / 批量操作 / 商品排序 / 选品 / 库存管理）
  全部同源。顺带收掉三份第二实现：批量页与排序页各自手拼的 `"¥… · 库存 …"`、
  库存页自己那一套**与商品卡不同**的库存配色（低库存红/缺货灰 vs 到报警线黄/断货红）、
  `PriceMatrixScreen` 里第二份 `parseColor`、`BatchPriceSheets` 手拼且**不带单位**的售价。
- 红线 `_check_product_card_single_source.py` **32 → 53 项**；反向验证 `_reverse_verify_product_card.py`
  **18 → 26 种注入**（新增：某页改回本地实现、`productFacts` 里两条事实调个个儿、
  排序行高度写回 64dp 把事实行裁掉、`parseColor` 长回来 —— 都必须红）。
- ⚠️ **排序页行高 64 → 96dp**：行里多了一条事实行，64dp（减掉 `SectionCard` 两侧 16dp 内边距）
  会**静默裁掉**库存那一行 —— 已加一条红线判据盯着这个数字。
- ⚠️ **单测里抓到我自己的两处错**：① `parseColor("blue")` **不是坏值**（它能认颜色名，
  会解析成纯蓝），我原来的注释拿它当"脏数据"的例子，错了；② 本工程开了
  `unitTests.isReturnDefaultValues = true`，所以 `parseColor` 在 JVM 里是**返回 0 的桩**
  —— "名称色"写不出有意义的断言单测（第一版单测红了，红的原因是桩不是代码）。
  两条都写进了代码注释，并新增 `ProductCardKitTest`（9 例，盯库存配色/角标/事实顺序）。
- **验收**：`_check_all.py` **59/59** · Android 单测 **1032 / 0 失败** · 真机 5554 五屏（`11-`…`15-`），
  并在排序页真的长按拖动过一次（第 3 位拖到第 1 位，证明手势搬到 `bodyModifier` 后仍有效），
  拖完**没点完成**、直接返回丢弃草稿，列表顺序未变（没给演示数据留痕）。
- ⚠️ **顺手重生成的两份产物**（我自己零后端改动，是别人的未提交后端改动导致过期）：
  `docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md`、`docs/ai/ai_read_catalog.json` —— 差异**只有行号位移**，
  没有权限/端点变化；另重跑了 `_hint_inventory.py --md`。**本机后端已重启**（`_check_backend_fresh` 转绿）。



### [2026-09-21 翌 00:4x → 01:0x] 会话：**「我的」页改版 · 第三版（动效改成手势果冻 + 短状态挪到右边）**（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）【已完成】

**用户反馈（原话）**：「**压根就没有动效**，这个动效**就像是一个果冻一样**……整个的列表我就像往下滑，
它可以**跟着我的动作做出反应**啊，**我刚滑了一下没有反应**啊」＋「那个『不显示说明』能不能**放在提示的后面**，
**就不要做两排**……**基础设置**它下面那个说明也**改成放右边**，跟那个**版本号**一样，放在那边；
**如果是详细说明的话，则就出现在下面**。」

**两条改动**
1. **果冻（`ui/profile/RowMotion.kt` 重写）**：⛔ 第一版把"跟随"挂在**滚动位置**上，两个后果 ——
   ① 列表**装得下、滚不动**的机器上（5554 就是）**一点反应都没有**（用户实测的那个"没反应"就是这个）；
   ② 能滚时又**停在那儿不回弹**。现在挂在**手势**上（`NestedScrollConnection.onPostScroll`，
   只旁观不消费），松手由 `onPostFling` 用回弹弹簧（`dampingRatio = 0.4`）弹回 0。
   **真机量像素**（按住拖 1000px）：首行 +30 / 第三行 +49 / 第四行 +59 / 末行 +68，
   **头部 +0**（只有列表动），松手全部回 0 ✓ —— 就是用户要的「越往下面偏移量越大」。
2. **排版规则**：**短状态靠右、与标题同一行；只有详细说明才另起一行**。
   → 「提示」的「显示/不显示说明」挪到右边（和开关同一行）、「基础设置」的「外观 · 夜间模式」挪到右边；
   「消息提醒」那句 `Hint`（详细说明）**仍留在下面**。红线把这条**双向**钉住了。

**⚠️ 本轮抓到的第三个"静默失效"（值得全员知道）**
`Modifier` 链**顺序反了**：`.verticalScroll(listScroll).nestedScroll(jelly.connection)` 等于把连接挂在
滚动节点的**子级**上 —— **一个事件都收不到**。表现是"按住拖 1000px、量像素发现每行位移都是 +0"，
**不报错、不崩溃、日志里什么都没有**。正确写法是 `.nestedScroll(...)` 在 `.verticalScroll(...)` **之前**。
（判据已进红线 + 反向验证第 ⑯ 条。这也是为什么这一轮坚持"量像素"而不是"看截图觉得差不多"：
前两版我都以为动效生效了。）

**验证凭据**：编译 ✓ · 红线 `_check_profile_page.py` **51 项** ✓（新增：果冻必须挂手势、
`nestedScroll` 必须在 `verticalScroll` 之前、短状态在右/详细说明在下**双向**、退出登录只弹框、
确认框复用共用弹层）· 反向验证 `_reverse_verify_profile_page.py` **16/16 被抓** ✓ ·
真机（5554）**像素级实测**果冻位移与回弹（无视频：用户说不用录）。


### [2026-09-21 23:5x → 翌 00:4x] 会话：**「我的」页改版 · 第二版（按用户看图后的四条反馈）**（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）【已完成】

**用户反馈（原话）**：「上面做的太窄了导致下面很空，**卡片要下来一点**；**退出登录不要放到中间**，
做成跟其他形式一样——一色加图标然后加文字；**基础设置有个要移出来叫做提示提醒，那个不能放在里面**；
还有一个就是整个消息列表**往下滑的时候越往下面偏移量越大**，稍微好看点的动效，往下滑他们有点反应，
显得有趣，**不过（别）会太过呆板**。」随后补充：「他那个退出登录**不是点一下就直接退出**，
为了防止误碰，会**弹出一个框**，四周圆角并且是长方形的，问是否确认，一个确认退出一个取消。」

**四条改动**
1. **头部加高**（`ProfileHeader.kt`：头像 56→68dp、下留白 26→60dp）：白卡因此落到接近参考图的位置，
   下面那一大片空白明显收窄。数值旁边写了「⛔ 不要再压回 56/26」的原因。
2. **退出登录改成与其它行同形的行**（语义色圆底图标 + 红字 + 左对齐，`showChevron = false` ——
   它是**动作**不是"进下一页"，箭头会承诺一个不存在的页面），点一下**先弹确认框**
   （复用 `ui/common/Components.kt::DangerConfirmDialog`，M3 弹窗本身就是四周圆角长方形；
   ⛔ 没自己拼 AlertDialog）。文案里顺带说明"订单账本在服务器上不会丢"——这是个"看着危险其实不危险"的动作。
3. **「提示」搬回第一层**（第一层因此变成**六行**）；`BasicSettingsScreen.kt` 只剩两个开关。
4. **行动效** `ui/profile/RowMotion.kt`（新）：进页面时按序号**依次落位**（起点 6dp + 序号×4dp、
   45ms 一档），滚动时**稍微落后**于内容（越往下越明显，上限 12dp）——正好是用户说的
   「越往下面偏移量越大」+「有点反应但别太呆板」。三条工程约束写在文件注释里：
   状态读只在 `graphicsLayer{}` 里（不触发滚动时重组）、**不用 `Modifier.offset`**（那会带着命中区
   一起动、点击区域与眼睛对不上）、用标准 `animateFloatAsState`（系统动画倍率为 0 时直接跳终态）。

**⚠️ 本轮踩到一个值得全员知道的坑（PowerShell 把源码写坏）**
我用 `(Get-Content -Raw) -replace ... | Set-Content` 改了一个变量名，结果**整个文件被写坏**：
PS 5.1 的 `Get-Content` 对**没有 BOM 的 UTF-8 文件按系统 ANSI(GBK) 解码**，
中文全变乱码、并且有 **103 个换行被吃掉**（477 行 → 374 行，因为 UTF-8 三字节的尾字节与 `\n`
被 GBK 当成一对无效双字节吞掉）。**这种损伤不可逆推**（丢的是字符的第三个字节，猜不回来）。
→ 该文件已按我自己的编辑记录**整份重写**并重新编译通过；结论一个字没丢，但白花了十几分钟。
⛔ **规矩**：这个仓库的源码一律用编辑工具改，**别用 PowerShell 的 `Get-Content`/`Set-Content` 往返**。

**验证凭据（第二版）**：编译 ✓ · 新红线 `_check_profile_page.py` **43 项** ✓（新增：六行、行动效数量
与行数一致、行数不能随手加减、「提示」不许在基础设置里、退出登录必须只弹框、确认框必须复用共用弹层）·
反向验证 `_reverse_verify_profile_page.py` **12/12 被抓** ✓ · 真机（5554）：新版整页、
**退出确认框**、以及**录了一段动效视频**（`_archive/profile-v2-motion.mp4`，
临时 `wm size 1080x1500` 让它真的能滚，看完已 `wm size reset`）。


### [2026-09-21 23:0x → 23:5x] 会话：**「我的」页改版：照参考图重做布局（深色头部 + 大圆角卡片列表 + 新增「基础设置」子页）**（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）【已完成】

**用户需求（原话）**：「把我的按到他的这个样式进行修改，布局是抄他的…他有个叫什么基础设置，我们也要有基础设置，
因为**我们按钮太多了，哪些是不怎么重要的，我们就放到基础设置当中**。然后**语言设置这个我们不需要**…
**账号信息**这个可以有，但是没必要因为我们那个上面就会显示…**结算账户我们也不需要**…**关于我们的就是我们的那个版本更新**…
然后还有我们**加一个退出登录**…**消息中心去掉**，因为我们已经在导航栏里有一个消息中心了，**这属于重复设计**。
…（布局样式）**尤其（参考）他那个背景以及那个卡片的样式**。」

**结果**：9 行 → **4 行 + 退出登录** + 1 个子页。
- 头部 `ui/profile/ProfileHeader.kt`：深墨蓝渐变 + 同心弧纹（**矢量资源** `res/drawable/bg_profile_header_arcs.xml`，不是代码里 `Canvas` 画的）、
  白圈头像、角色徽章（**实色填充 + 白字**，与参考图的「单店」同一形态）、姓名、`账号：…` + 描边标签；司机多一行计费规则（后端 `pay_summary`）
- 列表：一张**大圆角白卡**（顶部 24dp），行 = 语义色圆角图标 + 标题 + 右侧当前值 + `>`；**不再用分隔线**（靠留白分行）
- 第一层：我的账本〔仅司机·条件一字未改〕/ 消息提醒 / **基础设置**(新) / 关于与更新(点一下＝直接检查更新，两行合一) / 退出登录(红字居中)
- 第二层 `ui/profile/BasicSettingsScreen.kt`（`Routes.BASIC_SETTINGS`）：随日落 / 夜间模式 / 提示 —— 三个开关**原样搬过去，逻辑一行未改**
- ⛔ **删掉「消息中心」行**（用户明确：与底部导航重复）；⛔ **不做**语言设置 / 账号信息 / 结算账户

**四个坑（都是本轮真机上抓到的，值得下一位先看）**
1. **深色头部铺到状态栏下面 → 状态栏图标会全看不见**：主题按明暗设 `isAppearanceLightStatusBars = !darkTheme`，
   浅色模式下把**深色**图标压在深墨蓝上（不报错！）。修法 = `ui/common/StatusBarIcons.kt::LightStatusBarIcons()`
   （`DisposableEffect` 进来设白、**离开还原成主题口径**）。⚠️ 一开始我**只写了 import 没调用**，是 `_check_dead_code.py` 抓出来的。
2. **头部必须固定不滚**：滚走之后状态栏又变浅、白图标照样看不见。所以是"头部固定 + 列表滚"（`weight(1f)`）。
3. **行里"标题+右侧状态"要用 `Text(weight(1f))` + 非加权挂件**：我第一版写成
   `Text(weight(1f, fill = false)) + Spacer(weight(1f))` → 两个加权项平分空间 → 右侧贴不到最右，
   副标题被挤成两行（真机截图看出来的）。⚠️ 副标题因此挪到**标题行之下**，能独占整行宽度。
4. **注释里写「Hint + 左括号」会让盘点脚本认出一个假调用**：`_hint_inventory.py` 按括号配对切调用点，
   注释里一个不配平的左括号会把**后面**那一行的文案算到它头上 → 红线报"有一处 Hint 调用里没有解释句"，
   而代码是对的（本轮就这样白查了一次）。已在 `ProfileScreen.kt` 原地写明。

**验证凭据**：编译 ✓ · 单测 **1004 / 0 失败**（2 skipped）· 新红线 `_tools/qa/_check_profile_page.py` **33 项** ✓ ·
反向验证 `_tools/qa/_reverse_verify_profile_page.py` **10/10 被抓** ✓ · `_check_all.py` **57/58 绿**
（唯一红的 `_tools/ai/_audit_role_ai.py` 是**网络**：Clash 代理 `127.0.0.1:7899` 没开、`api.deepseek.com` 超时，与本轮无关）·
真机（5554 派单员）：浅色/深色两张 + 子页一张 + **拨「提示」开关看副标题出现/消失**（证明开关从新家照样生效）。

⚠️ **司机端（5558）与货主端（5556）本轮没装**：装包工具预检发现 `session-78ebd95c` 正在干活 →
按用户定的规矩「他在干活就各装各的」，只装了 5554。司机那两处新增（头部计费规则行、我的账本行）**尚未真机复验**，
等 5558 空出来补一眼（`python _tools/qa/_install_all.py --only 5558`）。

**顺手修的工具缺陷**：`_install_all.py` 原来**自相矛盾** —— 预检在有人干活时打印"照规矩各装各的（--only）"，
却仍然拒绝 `--only`。现在 `--only` 就是"各装各的"：**别人在干活只提醒不拦**（"有构建在跑"那条仍然拦，物理冲突），
并把"进行中"门禁降级为提醒（它积压历史条目，当门禁会天天误报）。

**交叉点**（改共享文件前都重读过最新内容，只做追加式/单点改动）：`ui/nav/Routes.kt`（+1 常量）、`ui/nav/NavGraph.kt`（+1 路由）、
`ui/home/RoleHomeScreen.kt`（profile Tab 的 inset 一处；去掉已无用的 `onOpenMessages` 接线）、`ui/theme/Color.kt`（+2 颜色常量）。
**别人的红线脚本我只搬锚点、没放宽判据**：`_tools/ai/_check_ai_guardrails.py`（§20/§21 两处 `profile` 改成"两个文件拼起来"）、
`_tools/ai/_check_notify_guardrails.py`（"消息提醒点得进去"拆成两段：页面接 `onOpenAlerts` + 行组件真的装 `clickable`，
**不比原来弱**）、`_tools/ai/_reverse_verify_sun_theme.py`（4 条注入改指 `BasicSettingsScreen.kt`）、
`_tools/ai/_reverse_verify_notify.py`（注入锚点跟着接线走，并**新增 1 条**"行组件把 onClick 收下就丢"）。


### [2026-09-21 22:2x] 会话：**给三台模拟器装包 + 登录 —— 抽成一个共享工具**（DSH `session-83da1ad7-e539-4d60-9412-b46a9a9dc48e`）【已完成】

**用户需求（原话）**：「3 个模拟器一起重装 apk 并且登录的那个脚本……如果没有的话你写一个，
然后**声明一下通知其他的工作人员**，也有一个工具大家以后都用这个工具更新 apk。
但是有个前提：**假如某个人他正在干活的话，则就不需要调用这个脚本了，就各装各就行了**。」

**查过：仓库里原先没有这个脚本**（`_tools/` 里没有任何 `adb install` 的调用）。

**新增**：`_tools/qa/_install_all.py`（**共享工具**，一行命令跑完）：
```
python _tools/qa/_install_all.py            # 预检 → 构建一次 → 装三台 → 各自登录 → 汇报
python _tools/qa/_install_all.py --precheck # 只看能不能用
python _tools/qa/_install_all.py --only 5556 --no-build
```
它替掉四件手工最容易出错的事：**只构建一次**（三台装同一个包）、按端口对角色装
（5554 派单员 / 5556 货主 / 5558 司机，**不是按端口排的**）、在登录页就自动登录
（复用 `_emu_ui.py` 的按文字定位 —— 键盘弹出会改 y，坐标不能写死）、
并核对**"这台登的是不是它该有的角色"**。

**「有人在干活就别用」这个前提怎么落地（预检，`--force` 可强装）**：
1. **别人正在跑 Gradle 构建** → 拒绝。判据用 `gradle --status` 看 `BUSY`。
   ⚠️ 第一版是扫进程表里含 `gradle-8.9` 的命令行 —— **天天误报**（Gradle 守护进程常驻，
   空闲时也在），这个工具就永远用不了。
2. **别的 DSH 会话最近 6 分钟还在干活** → 拒绝。判据是**会话日志的 mtime**
   （`~/.dsh/sessions/*/*/session.v2.jsonl.zstd`，正在跑的会话它就是"现在"）。
   ⚠️ 为什么**不**拿声明页当判据：那里「进行中」积压了历史条目，实测一口气命中 7~10 条
   （大半是早就做完的轮次），拿它做门禁等于天天拦路 —— 现在只当**参考**打印。
   已知盲区：**人手工改代码**时这个信号看不出来（那没有会话日志）。

**声明/通知**：`AGENTS.md` 新插入一节（每个会话启动都会读到），本文件「交叉点」也记了一笔。

**实测（2026-09-21 22:2x，预检通过后真跑）**：构建一次 ✓ → **3/3 台就绪**：
5554 当时停在登录页 → 自动登成派单员并核对通过（看到「派单作业」）；5556 已在登录态、
角色对（「货主端 · 订单与账本」）；5558 已在登录态、角色对（「已完成」）。
⚠️ 已知：**强装会把那台上正在被别人调试的包换掉** —— 所以才有上面那两条预检。


### [2026-09-21 12:1x → 12:2x] 会话：把后端发到生产（补上落后 72 个提交）【已完成】

**用户授权原话**：「我连接了手机调试你可以截图看一下什么问题」＋拍板「**发，先备份库再发**」。

**问题（已查实）**：手机上派单员「退货申请」页显示红字 `Not Found`（截图
`D:\AProjects\ppppppppppppp\logs\手机-现状.png`）。手机 App 连的是**生产 `https://8.145.40.22`**
（logcat `SOrdersSock: CONNECTED to https://8.145.40.22`），而生产后端停在 `810cec9`
（部署时间 **2026-09-19 16:32**），落后本地 `p` **72 个提交**：`GET /api/v1/return-requests`、
`GET /api/v1/freight-categories` 在生产上都是 **404**，而 `orders` / `notifications` /
`driver-billing-rules` 是 **401**（端点存在、只是没带 token）。App 把 404 的 `detail` 原样显示
（`core/ApiClient.kt::parseDetail`），所以屏幕上就是那行英文 `Not Found` —— 用户读成"连接失败/没找到"。
模拟器连的是本机后端 `10.0.2.2:8000`（`/proc/net/tcp` 证实），本机有这些端点 → **同一页在模拟器上完全正常**。
**结论：代码没问题，是「App 发了新版、后端没发版」。**

**做了什么（一行源码都没改）**：
1. 前置闸门：`_check_secrets.py` 绿（跟踪文件无凭据）；`cd backend && pytest -q` → **685 passed**；
   `git rev-list --count origin/new..p` = 36 且 `origin/new` 是 `p` 的祖先 → 可 fast-forward。
2. 备份（在 `/root`）：`backup-sorders-deploy-20260921-1215.sql.gz`（gzip 校验通过、1082 行、14 条 INSERT）
   ＋ `SOrders-backend-20260921-1215.tgz`（1.4M）。
3. `git push origin p:new`（本地 `p` → 远端 `new`，`be84921..5794deb`）；
   服务器 `git -C /opt/SOrders fetch && git merge --ff-only origin/new` → 到 `5794deb`。
4. `systemctl restart sorders-api`：启动期 `schema_bootstrap` 迁移**全部成功**
   （places.image_urls/image_url、order_products.returned_quantity、orders.returned_at、
   `orders.status` 补 RETURNED、`ledgers.source` 补 RETURN、expenses.category 放宽到 32、
   开销分类中文化并回填、orders.freight_category(_id)、driver_billing_rules.piece_mode），
   `NRestarts=0`、`ActiveState=active`，**没有崩**。
5. 验收：新端点全部从 404 变 **401**（存在）；真实派单员登录后
   `return-requests?status=pending|all` → **200**、`freight-categories` → **200**、`orders` → **200**；
   表 27 → **39**（order_return_requests/_lines、freight_categories、expense_categories、
   place_categories、shipper_settlements、product_cost_history 都建出来了）；
   原有数据一条没少（orders 9 / ledgers 7 / users 4）。
6. **手机端实地验收**：`工作台 → 退货申请` → 「没有待处理的退货申请。」（不再是 `Not Found`），
   截图 `logs/手机-退货申请-发版后.png`。

**回滚路径（没用到）**：代码 `git -C /opt/SOrders checkout 810cec9` + `systemctl restart sorders-api`；
数据用 `/root/backup-sorders-deploy-20260921-1215.sql.gz` 还原。

**生产上没碰**：`.env`、`backend/.venv/`、`backend/uploads/`、`/etc/nginx/`（前三个 `.gitignore` 已忽略，
`git merge` 不会动；nginx 这次不需要改）。

**给下一个人的两条**：① ⚠️ **发版之后「生产 = `5794deb`」** —— 之后任何人在本地改的后端**都不会自动上线**，
要再发一次（后端没有自动发布脚本，`_tools/deploy/` 只有 APK 那条链）。② 生产**只有 4 个账号 / 9 张单**，
是演示冒烟实例，不是真实业务数据 —— 所以这次发版风险低，但也别拿它当"数据没问题"的证据。

**交叉点**：本轮不改任何共享源码文件，无交叉。仅动了本文件（追加＋归档）。

### [2026-09-21 00:3x → 00:5x] 会话：修「订单列表 500」（freight_category NULL 毒化）【已完成】

**用户授权原话**：「已完成订单还是显示网络连接失败，要重新看一下。**如果是哪里出现问题就修一下**。」

**问题**：App「已完成」显示"网络连接失败"，实际是后端 `GET /orders` **500**（App 把 500 说成网络失败，
排查方向被带偏）。实测：`?status=DELIVERED` 与**不分状态**都 500；`?status=DISPATCHED` 看着正常
只是因为那次查出的是**空列表**（空列表不走出参校验）→ **只要列表里有数据就挂**，
影响全端所有订单列表（司机「已完成」/ 派单员订单列表 / 货主「我的订单」）。

**根因（traceback 已抓到）**：
```
app/schemas/order.py  OrderOut.model_validate(order)
pydantic ValidationError: freight_category
  Input should be a valid string [input_value=None, input_type=NoneType]
```
- 新增列 `orders.freight_category` 在**存量行上全是 NULL**（实测 **418/418 全部 NULL**，含 356 条已送达）；
- 而出参声明是 `freight_category: str = ""` —— `default` 只在**字段缺失**时生效，
  **字段存在、值是 None** 时照样走 `string_type` 校验 → 整页 500。
- 引入方：**运费分类 / 开销管理那条线**的未提交改动（`schemas/order.py` / `api/v1/orders.py` /
  `services/order_response.py`），与司机端那几轮改动无关。

**⚠️ 本轮动了别人的文件（无法回避：阻塞级，用户已授权）—— 只做追加式改动**：

| 文件 | 改什么 |
| --- | --- |
| ⚠️ `backend/app/schemas/order.py` | 在 `OrderOut` 里**追加**一个 `@field_validator("freight_category", mode="before")`，把 `None` 归一成 `""`（**照抄同文件里 `image_urls` 那个现成 validator 的写法**，一行逻辑）。**没有改任何现有行**、没有改类型 |

**另外做了两件（本轮特有，记在这里）**：

1. **回填数据**：`UPDATE orders SET freight_category = '' WHERE freight_category IS NULL`
   （本地开发库；只把 NULL 补成空串，与 `models/order.py:67` 的 `default=""` 同义）。
   不补的话界面能打开但"分类"永远是空。
2. **重启了本机后端**（本机 uvicorn 没有 `--reload`，不重启代码不生效）。
   ⚠️ 该进程**不是我起的**（发现它在 00:08、00:27 被那条线重启过两次）—— 重启会让他们的在途调试断一下，
   但这是修阻塞 bug 的必经步骤；重启命令与原来完全一致（`uvicorn app.main:app --host 127.0.0.1 --port 8000`）。

**明确不碰**：`api/v1/orders.py`、`services/order_response.py`、`services/order_money.py`
（都是那条线正在改的；本轮只动 schema 里那一处归一，其余靠回填数据解决）。

---

**结论（修完，三处都验过）**：

| 验证 | 结果 |
| --- | --- |
| 回填 | `UPDATE orders SET freight_category='' WHERE freight_category IS NULL` → **420 行**，剩余 NULL = **0** |
| 接口 | `GET /orders?status=DELIVERED` → **200**；不分状态 → **200**；`PENDING_DISPATCH` → **200** |
| App（5558 司机端） | 「已完成」**不再出现"网络连接失败"**，两单正常显示（截图 `logs\已完成-修复后.png`）；药丸显示「上周」（今天已是 09-21，这周没单 → 自动退档，顺带证明退档在真实时间推进后仍正常） |

**给那条线（运费分类/开销管理）的三点交接**：

1. 我在 `schemas/order.py` 的 `OrderOut` 里**追加**了 `_none_freight_category_to_empty`（`mode="before"`，`None → ""`），
   与同文件 `image_urls` 那个 validator 是同一条规矩。**如果你们重写这个文件，请把这一处带上** ——
   否则"库里 NULL → 整页 500"会立刻复发。
2. **根上还有两件事值得做**（我没做，属你们的改动范围）：① 建列时的迁移要**回填**存量行
   （这次是我手工补的 420 行）；② 新加的非空出参字段，最好在建的时候就配一个"库里 NULL 也认"的 validator。
3. 本机后端我**重启过一次**（没有 `--reload`，改 schema 必须重启）。发现它在 00:08、00:27 已被你们重启过两次；
   现在这个进程的日志我重定向到了 `D:\AProjects\ppppppppppppp\logs\backend.log`（原来没落文件，出 500 时无法取证 ——
   这次是靠"另起一个 8011 端口复现"才拿到 traceback 的）。

**另外建议**（未改，属 App 侧）：`ApiClient.toApiException` 把 HTTP 500 说成「网络连接失败」，
这次直接把排查方向带偏了（用户第一反应是"断网了"）。建议区分"连不上"与"服务器 5xx"两种文案。

---


### [2026-09-20 23:0x → 23:2x] 会话：司机「我的账本」入口按计费模式显示【已完成】 + 明细露出计件/提成

**任务**（用户 2026-09-20）：「再创建一个账号，这个账号是**大车司机**也就是**拿固定工资**的司机 ——
拿固定工资的司机**不需要「我的账本」**，所以他是没有的。但是有一点：如果他是**拿固定工资加抽成**的话，
他就按他那个「我的账本」**就有了**；而且每个订单会显示他**每个单抽成多少**或者每个商品抽成多少（按规则来搞）。
而且如果当派单员**切换他的计费规则**（从固定工资切到按单算 / 按抽成算），他这个都会**跟着变**。」

**先做的事（数据）**：新建大车司机账号 —— `13800000006` / 密码 `123321` / `王大力` /
`vehicle_type=large` / `salary=8000` / **不挂计费规则**（`resolve_billing_mode("large", None)` = **SALARY**，
正是"纯固定工资"那种）。已用派单员 token 建好（`POST /users` → id=58）并验证可登录。

**关键结论：后端不用改**（省掉一轮）：

- `api/v1/users.py::_to_out` 第 49 行**已经**出了 `out.pays_per_order = snapshot_mode(u) == "PIECE"`，
  注释写明它"**必须与账单同源**"（原来是客户端按 `billing_mode ?: 车型` 猜，少一层"规则优先"，
  挂着运费提成的大车司机被判成工资制 → 运费框不显示 → 提成恒为 0 → 送达时连账单都不生成）；
- 客户端 `UserDto.paysPerOrder` 也已存在，`DispatcherPoolViewModel` 已在用它决定运费框。
- `snapshot_mode` 对"固定工资 **+** 抽成"的判定是 `rule.has_per_order_pay`（计件或有提成）→ **PIECE** ✓
  正好是用户说的"工资+抽成 → 账本就有了"。

**改什么（三个文件，后端一行不动）**：

| 文件 | 改什么 |
| --- | --- |
| `android/.../ui/profile/ProfileScreen.kt` | 「我的账本」入口的显示条件从 `role == "driver"` 改成 `role == "driver" && paysPerOrder == true` —— 纯固定工资司机**看不到这一格**，工资+抽成/按单计费的司机看得到 |
| `android/.../ui/driver/DriverFreightViewModel.kt` | `FreightRow` 追加 `payPiece` / `payCommission`（后端 `FreightSettlementOrderDto` 里本来就有，只是没往页面上带） |
| `android/.../ui/driver/DriverFreightScreen.kt` | 明细右侧小字多一行：**`计件 ¥x + 提成 ¥y`**（只列非 0 的那几项，与派单员结算页 `FreightSettlementScreen.kt:319` 同一套说法）—— 用户要的"每个单抽成多少" |

**"跟着变"怎么成立**：入口读的是 `/users/me` 的 `pays_per_order`，派单员一改规则（attach / 改规则），
这个值就跟着变；页面每次拉 `user` 就重算 —— 不需要客户端自己判断规则。

**明确不碰**：`backend/app/api/v1/users.py`、`backend/app/services/driver_pay.py`（口径唯一，本来就是对的）、
`ui/dispatcher/DispatcherPoolViewModel.kt`（已在用同一字段）、账本线正在改的文件。

---

**结论（做完）**：改动落在 **4 个文件**（声明里少写了一个 —— 见下），已编译 + 装 5558 真机逐步验过。

**新建的账号**：`13800000006` / 密码 `123321` / **王大力** / `vehicle_type=large` / `salary=8000` / **不挂规则**
（`resolve_billing_mode("large", None)` = SALARY，就是"纯固定工资"那种）。id=58。

**三条真机结果**：

| 场景 | 结果 |
| --- | --- |
| 纯固定工资（未挂规则，`pays_per_order=false`） | 「我的」页**没有**「我的账本」✅ |
| 挂上「运费提成 5%」→ 没有重启 App，**只切 Tab** | 入口**自己出现了** ✅ |
| 再解挂规则 → 照样**只切 Tab** | 入口**自己消失了** ✅ |
| 明细（李伟明那两单，规则=每单计件 22） | `¥22.00`（司机应得）+ **`计件 ¥22.00`** + `运费 ¥62.00` ✅ |

**声明里漏写的一个文件（补记）**：`ui/profile/ProfileViewModel.kt` ——
`loadMe()` 加了 `silent: Boolean = false`（静默刷新，不整页转圈），配合 `ProfileScreen` 里的
`LaunchedEffect(Unit) { vm.loadMe(silent = true) }`。**为什么必须要它**：VM 是 App 级缓存的、
原来只在 `init` 拉一次 `/users/me`，实测"挂完规则切 Tab 没反应、**必须杀进程重启**才出现"——
那样用户会以为"没生效"，你要的"跟着变"就不成立。加完之后上表那两行才对得上。

**顺带发现（本轮没改，交给你拍板）**：现有规则里 `id=5「运费提成 8%」`、`id=6「运费提成 12%」` 的
`commission_base` 是 **`none`**（只有费率、没有基数）。按 `driver_pay` 的 `has_per_order_pay`
判据（`base in (freight, goods) and rate > 0`），**这两条规则的抽成根本不生效** ——
挂着它们的 3 个司机实际被判成**纯工资制**（现在连「我的账本」都不会有）。
要么是老数据缺 `base`，要么是建规则时那一栏丢了；**不是本轮引入的**，但会让"挂了提成却没反应"。

---


### [2026-09-20 22:2x] 会话：司机账本趋势图 X 轴粒度跟着档位走【已完成】（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**任务**（用户 2026-09-20）：「他这个运费趋势表要弄得好（一点）：如果是**今天**的话，X 轴就是按**时段**；
如果是**昨天**也是按时段；如果是**这周 / 上周**这种一周的，X 轴就变成为**这一周的天**。」

**为什么现在不对**：`DriverFreightViewModel.chartSeries` 一直按 `deliveredAt.take(10)`（**日期**）分桶 ——
选「今天」时整张图只有**一个点**（今天只有一个日期），趋势图等于没用。

**改什么（两个文件）**：

| 文件 | 改什么 |
| --- | --- |
| `android/.../ui/driver/DriverFreightViewModel.kt` | `chartSeries` 改成**粒度跟着窗口走**：`periodStart == periodEnd`（单日档）→ 按**小时**分桶（key `2026-09-15 18`）；跨日档 → 按**天**分桶（key `2026-09-15`）。x 轴标签也在 VM 里生成好（单日 `18时` / 跨日 `09/15`），并顺手**按 key 排序**（原来是按 rows 的返回顺序塞进 `LinkedHashMap`，后端倒序时图就是倒的） |
| `android/.../ui/driver/DriverFreightScreen.kt` | 标签直接用 VM 给的那一份（原来在页面里 `substring(5).replace("-", "/")` —— 那个写法只对日期 key 成立，按小时分桶后会切错） |

**明确不碰**：`ui/common/Charts.kt`（`LineChart`/`BarChart` 的接口不动）、`ui/common/DatePresets.kt`、
`ReportTimeNav.kt`（报表中心在用）、后端 `/freight-settlement`（口径不变）。

---
### [2026-09-20 22:4x] 会话：司机账本运费卡片重排【已完成】（从哪到哪 + 运费突出，订单号退居次要）

**任务**（用户 2026-09-20）：「运费卡片一些信息也要表明出来，尤其是**从哪里到哪里**；订单号都不是非常重要
（点进去看详情时能看到），主要是**从哪到哪里**，然后那个**运费是多少**。」

**用户对"从哪"的裁决**（原话）：「如果订单没有起点的话，则就**没必要加**；意思就是说，它有起点和终点
（也就是路线）的时候就**自动显示**，没有路线的话就自动显示终点。」

**已查清的事实（决定了这一轮能做到哪）**：

- `orders` 表**没有起点列**（`backend/app/models/order.py` 只有 `address_detail` / `address_lat/lng`）；
  `OrderCreateRequest` 里也**没有起点字段** —— 下单选线路只带走了终点 + 联系人，**起点从来没进过订单**，
  所以"部分单有起点"这个情况目前**不存在**（一律只有终点）；
- `origin_address` 只活在**线路**（`shipper_addresses`）上，界面里只有「地址与联系人」的线路卡显示它
  （`AddressScreen.kt`：`"从 " + a.originAddress`）；
- `/freight-settlement` 的出参只有 `delivery_description` + `address_detail`。

**改什么（三个文件，后端一行不动）**：

| 文件 | 改什么 |
| --- | --- |
| ⚠️ `android/.../data/remote/dto/Dtos.kt` | `FreightSettlementOrderDto` **追加**一个可空字段 `origin_address`（**只追加，不动任何现有字段**）。⚠️ 后端**目前不出**这个字段 —— 这样写是为了"后端哪天补上起点，App 不用再改"（用户要的"有就自动显示"）；不出时它恒为 null |
| `android/.../ui/driver/DriverFreightViewModel.kt` | `FreightRow` 追加 `origin: String?`，从上面那个字段读 |
| `android/.../ui/driver/DriverFreightScreen.kt` | 明细卡片重排：**主行 = 「起点 → 终点」（没有起点时只显示终点）**、次行 = 时间 · 配送说明、**订单号降为一行小字淡色**；右侧金额仍是大字「司机应得」+ 小字「货主运费 / 待定价」 |

**明确不碰**：`orders` 表 / `schema_bootstrap` / `OrderCreateRequest` / `/freight-settlement`（按用户裁决**不做**起点迁移）；
`ui/dispatcher/FreightSettlementScreen.kt`（派单员端结算页，本轮不在范围内）；`Charts.kt`、`DatePresets.kt`。

**附带**：本条与上一条（趋势图 X 轴粒度）一起编译验证。

---
### [2026-09-20 22:5x] 会话：司机账本趋势图/明细的时间口径修正【已完成】（UTC → 设备时区）

**怎么发现的**：验证"自定义单日 → X 轴按小时"时，选 `09-15~09-15` 只回了 1 单，
而后端同一窗口**确实只有 1 单** —— 另一条单的 `delivered_at` 是 `2026-09-15T18:18:00`（**UTC**），
换算到当地（东八区）是 **09-16 02:18**，不属于当地 09-15。**后端是对的**
（`freight_settlement.py:57-61` 明确把客户端的当地墙上时间 `to_utc_naive` 再比）。

**真正的缺陷在客户端**：`DriverFreightViewModel` 把 UTC 原样当当地显示
（`it.deliveredAt?.take(16)?.replace("T", " ")`）—— 于是
「X 轴写着 `12时`，其实是当地 20:57」「明细写着 09-15 18:18，筛 09-15 却没有它」，
而两边都不报错。项目里**本来就有**正确的工具：`util/TimeFmt.kt::formatDateTime`
（naive 串按 UTC 解释 → 换算到设备时区；它自己的注释还警告"**模拟器时区恰是 UTC，
所以这个缺陷在模拟器上永远看不见**"）。

**全项目同类写法（`take(16)` 直接印 UTC）共 5 处，本轮只修自己这一处**：

| 位置 | 谁的 |
| --- | --- |
| `ui/driver/DriverFreightViewModel.kt:212` | ✅ **本会话修** |
| `ui/dispatcher/DispatcherLedgerScreen.kt:622` | ⚠️ 账本线（别人在改）—— **不碰**，仅在此登记 |
| `ui/dispatcher/LedgerPersonScreen.kt:313` | ⚠️ 同上 —— **不碰**，仅登记 |
| `ai/AiWrite.kt:560`、`ai/AiWriteService.kt:807` | AI 域 —— **不碰**，仅登记 |

**改什么（一个文件）**：`android/.../ui/driver/DriverFreightViewModel.kt`

1. `deliveredAt = formatDateTime(it.deliveredAt)`（原来是 `take(16)` 拿 UTC）；
2. `chartSeries` 的分桶跟着改成适配新格式（`MM-dd HH:mm` 不含年份）：单日取 `take(8)` → 标签 `20时`，
   跨日取 `take(5)` → 标签 `09/15`。

**明确不碰**：上表那 4 处、后端 `freight_settlement.py`（它是对的）、`util/TimeFmt.kt`（工具本身没问题）。

**验证方式说明**：模拟器默认时区是 **UTC**，改与不改**看不出差别** ——
所以验证时会把 5558 的设备时区改成 `Asia/Shanghai`（更接近真机；只影响这台测试机，可随时改回）。

---

**结论（三条一起做完）**：改动落在两个文件 + DTO 追加一个字段，已编译 + 装 5558 真机验过
（**设备时区改成了 `Asia/Shanghai`** —— 模拟器默认 UTC，时间口径的差别在那里看不见）。

1. **X 轴粒度跟着窗口走** ✅：跨日档 → `09/15 | 09/16`（按**天**）；自定义单日 `09-16~09-16` → **`02时`**（按**小时**）；
2. **运费卡片重排** ✅：主行 = **地址**（有起点时「起点 → 终点」；后端现在不出起点，所以只显示终点）、
   次行 = 时间 · 配送说明、**订单号降为一行小字**，右侧 = 司机应得（大字）+ 货主运费 / 待定价（小字）；
3. **时间口径修正** ✅（验证时顺带抓到的真问题）：明细与趋势图原来把 **UTC** 当当地印（`take(16)`），
   改成 `formatDateTime`（换算到设备时区）—— 现在明细写 `09-16 02:18`（当地），
   拿 09-16 去筛就能查到它，与后端按**当地日**（`BUSINESS_TZ = 东八区`）筛选的口径终于一致。

**过程中修掉一个自己引入的 bug**：`windowOf(CUSTOM)` 最初没接 `customFrom/customTo`，
表现是"药丸写 `09-15~09-15`、请求却发 `2000-01-01~今天`（全部）"—— 口径词与实际窗口不符，两边都不报错。已修并复验。

**顺带登记的遗留（本轮没动）**：`ui/dispatcher/DispatcherLedgerScreen.kt:622`、`ui/dispatcher/LedgerPersonScreen.kt:313`、
`ai/AiWrite.kt:560`、`ai/AiWriteService.kt:807` 仍是 `take(16)` 直接印 UTC —— 同样会在真机上早 8 小时；
但两处账本是别人正在改的、AI 两处属 AI 域，按约定只登记不碰。

---


### [2026-09-20 21:5x → 22:1x] 会话：司机端「我的账本」换时间控件 + 自动退档【已完成】（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**任务**（用户 2026-09-20）：「把司机的**我的账本**也做一个改动……时间也按那个（药丸）进行，预设**默认是今天**的，
如果今天没有单则也按老规则**一直推到有单为止**。他那个订单也是可以点击进详情查看的，这个不需要改太多。」

**改什么（两个文件）**：

| 文件 | 改什么 |
| --- | --- |
| `android/.../ui/driver/DriverFreightViewModel.kt` | ① 时间从「按日/周/月 + anchor 翻页」换成**档位**（`preset` 初值 = 今天、`customFrom/customTo`、`periodWord`）；② 新增 `pickDefaultPreset()` 自动退档（今天→昨天→前天→这周→上周→近 7 天→本月→上月→全部，**首次进页面只跑一次**，用户手动挑过就永不再自动改）；③ **取数口径不变**，仍走 `repo.freightSettlementRange(起 00:00:00, 止 23:59:59)`，只是窗口改由档位算；④ 删掉 `chartMode` / `chartAnchor` / `applyMode` / `setAnchor`（趋势图本来就按 `deliveredAt` 的日期分桶，与它们无关） |
| `android/.../ui/driver/DriverFreightScreen.kt` | ① 顶栏右侧加 `DatePresetPill`（点开 `DatePresetDialog`；选「自定义」再开 `DateRangeDialog`）—— 与货主账/司机任务页同一个控件；② 删掉列表里那行 `ReportTimeNav`；③ 空态文案指到**右上角**；④ **明细行点进详情保持不变**（`clickable { onOpenOrder(e.orderId) }`，一个字符没动） |

**明确不碰**：

- `android/.../ui/common/ReportTimeNav.kt` —— **报表中心还在用**（`ReportCenter.kt:81`），一行不动；
- `android/.../ui/common/DatePresets.kt`（档位与区间的唯一实现）、`ui/common/Components.kt`（药丸的定义，别人在改）；
- 后端 `/freight-settlement`（司机应得的口径只有 `services/driver_pay.py` 一处，本轮不碰）。

---

**结论（做完）**：三个文件，已编译 + 装 5558 真机验过，与本次相关的静态检查全绿
（`_check_dead_code` ✅、`_check_ledger_dashboard` 133/133 ✅、`_check_single_source` ✅、`_check_vm_state_before_init` ✅）。

1. **药丸** ✅：顶栏 = `← 我的账本` + 右侧 📅 药丸（截图 `logs\司机账本-药丸.png`）；
2. **默认今天 + 自动退档** ✅：logcat 把阶梯记下来了 ——
   `freight-settlement?from=2026-09-20`（今天）空 → `09-19`（昨天）空 → `09-18`（前天）空 → **这周有单，停**，
   药丸显示「这周」，合计 ¥44.00（= 22+22，**司机应得**；旁边小字 ¥62/¥92 是货主运费，两套口径没有混）；
3. **明细点进详情** ✅ 没被改坏：点第一单 → 订单详情页正常打开（`#SO202609159053749345`）。

**顺手做的一件事（值得记）**：退档阶梯**提成了共用一份** `DRIVER_PRESET_LADDER`（`DriverOrdersViewModel.kt` 文件级 `internal`），
司机任务页与「我的账本」共用 —— 否则两处各写一份，日后改一处忘一处、两边都"看着对"。

**过程中的一个插曲**：第一次编译被 `core/ExpenseLink.kt`（**别人新写、当时还是未跟踪文件**）挡住，
6 个错误全在那个文件、我的 4 个文件 0 错误。**没有去动别人的文件**（哪怕临时移走），
而是后台每 75 秒重试一次，第 2 次（21:09）对方修好后编过并装机。

---


### [2026-09-20 21:3x → 21:4x] 会话：消息中心「全部已读」改常显【已完成】（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**任务**（用户 2026-09-20）：「为什么他的消息中心（导航栏的消息）没有全部已读的功能了？这功能也加上去啊，其他 2 个都有。」

**根因（已实测，不是功能缺失，是"按需隐藏"）**：

- 「全部已读」按钮的显示条件是 `if (unread > 0 || listUnread > 0)`（`MessagesScreen.kt:82-85`）；
- 实测三端：司机 13800000003 = **8 条消息、未读 0 条** → 按钮被隐藏；派单员 13800000001 = 167 条、未读 12 → 看得到
  （货主 13800000002 未读也是 0，同样看不到）。同一个页面三端共用（`RoleHomeScreen.kt:248`），差别只在数据。
- ⚠️ 这已经是**同一个问题第二次**：代码注释里记着 2026-09-17 用户就报过「还加一个全部已读的功能」，
  当时的修法（补 `listUnread` 判据）只放宽了触发条件，**没解决"看起来没有"** —— 只要恰好没有未读，功能就又"消失"。

**改什么（一个文件、一处）**：

| 文件 | 改什么 |
| --- | --- |
| `android/.../ui/messages/MessagesScreen.kt` | 把「全部已读」从"有未读才画"改成**一直画出来**，没有未读时置灰：`enabled = !vm.busy && (unread > 0 || listUnread > 0)`。灰 = 现在没什么可标的，而不是"没这功能" |

**明确不碰**：

- `ui/messages/MessagesViewModel.kt` —— `markAllRead()` 本身是健全的（走 `POST /notifications/read-all`，
  用服务端回包的 `updated` 条数说话，不拿本地列表数编数），没有要改的地方；
- `backend/app/api/v1/notifications.py`（`/read-all` 端点正常）；
- 货主账本 / 派单员账本两条线正在动的任何文件。

---

**结论（做完）**：一处改动，已编译 + 装 5558 真机验过。

- 顶栏现在是：`消息中心 | 全部已读 | 清空 | 刷新` —— **「全部已读」一直画得出来**，
  没有未读时**置灰**（截图 `D:\AProjects\ppppppppppppp\logs\消息中心-全部已读-灰.png`：
  它比旁边红色的「清空」明显浅一档，正是"没什么可标的"那个状态）。
- 后端核对：点过之后司机仍是 8 条 / 未读 0 —— 本来就没有未读，所以数不变（不是没生效）。
- 静态检查：`_check_notify_guardrails` 86/86 ✅、`_check_dead_code` ✅、`_check_ledger_dashboard` 133/133 ✅。

**顺带记录一个观察（没改）**：`uiautomator dump` 把这个 Compose `TextButton` 的 `enabled` 报成 `true`，
而截图里它明明是灰的 —— 判断 Compose 控件的禁用态**不要信 dump 的 enabled 属性，要看截图**。

---


### [2026-09-20 21:0x → 21:2x] 会话：司机端「已完成」默认退档 + 卡片多商品虚线【已完成】（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**任务**（用户 2026-09-20 口述三件）：

1. 「这个时间默认是看今天的，然后其次再往上推昨天、前天、这周，然后上周依次类推」
   → 默认档位不只是"今天"，还要**自动退档到真有单的那一档**；
2. 「你要注意的就是这个司机……按固定工资计费的话，他的卡片是**不能有任何订单金额**的」
   → 核对这条口径（**结论：已经是对的，本轮不改代码**，见下）；
3. 「卡片的多个商品……中间做**虚线横杠**稍微区分一下，省的看错位」
   → 商品行之间加虚线分隔。

**改什么（两个文件）**：

| 文件 | 改什么 |
| --- | --- |
| `android/.../ui/driver/DriverOrdersViewModel.kt` | ① 加 `userPickedPreset` / `autoPickedPreset` + `pickDefaultPreset()`（今天→昨天→前天→这周→上周→近 7 天→本月→上月→全部，**首次进「已完成」只跑一次**）；② 手动换档标记成 `userPickedPreset`（挑过就**永不自动改**）；③ `switchPreset()` 收成一条路（自动退档与手动换档共用） |
| ⚠️ `android/.../ui/common/OrderCard.kt` | 商品行（`orderProducts.take(3)`）改成 `forEachIndexed`，**行与行之间加一条虚线**（新增私有 `DashedLine()`，项目里原先没有虚线画法）；**只加不减**，其它一行不动 |

**关于第 2 件（固定工资零金额）——核对结论：已经是做对的，不改**：

- 后端 `backend/app/services/order_response.py::apply_driver_view_gating`：
  `data["freight_visible"] = mode == "PIECE"`，且 `mode != "PIECE"` 时连 `freight_fee` 一起置 `None`；
  明细的 `unit_price` / `line_total` 对**所有**司机一律置 `None`（司机看不到货款）；
- 客户端 `OrderCard` 司机视图只在 `order.freightVisible && order.freightFee != null` 时画金额；
- 实测司机 13800000003 = **PIECE**，所以卡片上出现 ¥62.00 是**正确的**（不是漏挡）。

**明确不碰**：

- `android/.../ui/common/DatePresets.kt`（档位与区间的唯一实现 —— 不新增档位、不改区间口径）；
- `backend/app/services/order_response.py`（门控已正确）；
- `android/.../ui/common/Components.kt`（别人第五轮在改）；
- 货主账本 / 派单员账本两条线正在动的文件。

**交叉点预登记**：本轮动 `OrderCard.kt`（共享文件，见下表一行）。

---

**结论（做完）**：三件事的落地情况 ——

1. **默认退档** ✅：`DriverOrdersViewModel.pickDefaultPreset()` + `DEFAULT_LADDER`（今天→昨天→前天→这周→上周→近 7 天→本月→上月→全部）。
   真机 logcat 把阶梯一行行记下来了：今天(09-20)空 → 昨天(09-19)空 → 前天(09-18)空 → **这周(09-14~09-20)有单，停在这里**，
   药丸显示「这周」、16 条单全在。手动点过药丸（`userPickedPreset`）之后不再自动改。
2. **固定工资零金额** ✅ **本来就是对的，本轮没改代码**：后端 `order_response.py::apply_driver_view_gating`
   是 `freight_visible = mode == "PIECE"`，且 `mode != "PIECE"` 时连 `freight_fee` 一起置 `None`；
   明细的 `unit_price`/`line_total` 对**所有**司机一律置 `None`。客户端 `OrderCard` 只在
   `freightVisible && freightFee != null` 时画金额。实测 13800000003 = PIECE，所以卡片上的 ¥62.00 是**对的**。
3. **多商品虚线** ✅：`OrderCard.kt` 的 `orderProducts.take(3)` 改 `forEachIndexed`，行间插 `DashedLine()`
   （截图 `logs\商品虚线-最终-放大2倍.png`）。

**过程中踩到并已修正的两件事（留给下一轮的人）**：

- 虚线第一版是 `Canvas` + `PathEffect.dashPathEffect` 画的 → **踩中红线「自己画的图只许在 Charts.kt」**
  （`_check_ledger_dashboard.py` 第 438 行：文件里出现 `Canvas(` 就红，白名单只有 `Charts.kt`/`util/Watermark.kt`）。
  已改成**纯布局**（一串小 `Box` 按可用宽度算段数），红线恢复 133/133 全过。**不钻空子用 drawBehind 绕**。
- ⚠️ 用 PowerShell 做多行字符串替换时，`'A' + $nl + 'B'` 这种拼接**丢掉了后半段**（两次：import 丢失、`if (idx > 0) DashedLine()`
  调用丢失 —— 第二次被 `_check_dead_code.py` 抓出"没人调用的私有声明"）。**改 .kt 的多行插入请用 edit 工具**，别用 pwsh 拼字符串。

**收尾状态**：`_check_all.py` 里**与本次改动相关的检查全绿**（dead_code ✅、ledger_dashboard 133/133 ✅）。
剩下的 6 个 ❌ 全部来自**另一条线的后端在途改动**（新增端点/动作码没跟上 AI 能力表、本机后端跑的是旧代码），
与司机端这次改动无关 —— 那些不是我能替他们决定的收尾动作。

---


### [2026-09-20 20:4x → 20:5x] 会话：司机端「已完成」时间控件换形态【已完成】（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**任务**（用户 2026-09-20 口述，附货主账截图作参考）：

> 「参考一下这个的时间排版……先是左边是刷新键，然后右边就是这个时间排版，**不然这个太长了，它有个滑动**，
> 然后**默认是今天的默认值查看今天的订单**，然后它可以点击那里查看我们已经有所有好的预设以及自定义。」
> 「**只需要参考它的右上角那个时间是怎么搞的，其他的不需要参考**。」

也就是：司机端「已完成」页那一行 **9 个胶囊（要横向滑动、右边被切掉）** 换成**顶栏右上角的紧凑时间药丸**
（`DatePresetPill`）+ 点开档位清单（`DatePresetDialog`），**默认档位从「全部」改成「今天」**。
账本页的其他形态（人员行、汇总卡、核销、表格）**一律不搬**。

**改什么（两个文件）**：

| 文件 | 改什么 |
| --- | --- |
| `android/.../ui/driver/DriverOrdersViewModel.kt` | ① 新增 `preset` / `customFrom` / `customTo` 状态（**声明在 `init` 之前**）；② `init` 先按默认档位「今天」算区间再 `load()`；③ `applyPreset(label)` / `applyCustomRange(from,to)` / `periodWord`（照 `DispatcherLedgerViewModel` 同一套语义）；④ 删掉只给胶囊行用的 `applyRange` |
| `android/.../ui/driver/DriverOrdersScreen.kt` | ① 删掉列表里那行 `DateRangeFilter`；② 顶栏改成「**左＝刷新、右＝时间药丸**」（药丸只在「已完成」页出现）；③ 挂 `DatePresetDialog`（选「自定义」再开 `DateRangeDialog`）；④ 空态文案从"点上面的「全部」"改成"点右上角换一段时间" |

**明确不碰**：

- ⚠️ `android/.../ui/common/Components.kt` —— `DatePresetPill`/`DatePresetDialog`/`DateRangeDialog` 是
  「派单员账本第五轮」刚加进去的，**我一个字符都不改**，只从司机页调用；
- `DatePresets.kt`（档位与区间的唯一实现：不新增档位、不改区间口径）；
- 货主账本 / 派单员账本两条线正在动的任何文件。

**红线注意**：`_tools/qa/_check_vm_state_before_init.py` —— 新增的 `preset` 等状态**必须写在 `init` 之前**，
否则 `init` 里那次赋值会在属性初始化前执行 → **打开这一页直接崩**（账本页 2026-09-20 真机栽过一次）。

---

**结论（做完）**：两个文件，已编译（`assembleEmuDebug` exit=0）+ 装 5558 真机验过，静态检查 **48/48 全绿**：

1. 顶栏 = **左刷新 + 右时间药丸**（截图：`D:\AProjects\ppppppppppppp\logs\司机端-时间药丸-点开清单.png`）；
2. 药丸点开是「看哪一段时间」：全部 / **今天（✓）** / 昨天 / 前天 / 这周 / 近 7 天 / 上周 / 本月 / 上月 / **自定义**；
3. 默认档位 = 今天：进「已完成」发的就是 `?status=DELIVERED&date_from=<今天>&date_to=<今天>`；
   点「全部」后请求变成 `?status=DELIVERED`，16 条已送达单全部回来（logcat okhttp 两行并排可对）。

---


### [2026-09-20 20:2x → 20:35] 会话：司机端「已完成」筛空后没有出路【已完成】（DSH `session-78ebd95c-b8c9-4a44-8f7a-270d17e7c918`）

**任务**：用户报「已完成订单一点『今天』就什么都拿不到了」。已在模拟器 5558（司机 13800000003）复现并定位：

- `DriverOrdersScreen.kt` 把 `DateRangeFilter`（那行日期档位）写在 `LazyColumn` 的 **`else ->`**
  分支里 —— 也就是**只有 `vm.orders` 非空时才渲染**；
- 复现链：切「已完成」→ 16 条正常（`全部 | 今天 | 昨天 | 前天 | 这周 | 近 7 天 …`）→ 点「今天」→
  请求变 `GET /api/v1/orders?status=DELIVERED&date_from=2026-09-20&date_to=2026-09-20` → 后端回 `[]`
  （今天的单还没送达）→ 走 `vm.orders.isEmpty()` 分支 → **档位条整条消失**；
- 后果：用户**再也点不到「全部」**，界面永久停在「暂无已完成任务」，只能杀进程重启
  （重启后 `dateFrom/dateTo` 复位为 null，已实测恢复）。
- ⚠️ **不是闪退**：`adb logcat -b crash` 为空、进程没死、前台仍是 `MainActivity` ——
  是"筛空 + 自救入口一起消失"，用户感知成"崩溃"。

**改什么（只动一个文件）**：

| 文件 | 改什么 |
| --- | --- |
| `android/.../ui/driver/DriverOrdersScreen.kt` | ① `DateRangeFilter` 抬出 `else` 分支 → **列表为空也渲染**（仍只在 `tab==1` 显示）；② 空态文案改成会指路的一句：「这个时间段里没有已完成的订单 —— 点上面的「全部」可以看所有」 |

**明确不碰**：

- ⚠️ `android/.../ui/common/Components.kt` —— `DateRangeFilter`/`DatePresetRow` 的**定义**就在这个文件里，
  而它正是「派单员账本第五轮」刚加 `DatePresetPill`/`DatePresetDialog` 的同一个文件：**我一行都不改**，
  只从 `DriverOrdersScreen` 调用它；
- `DriverOrdersViewModel.kt` —— 它默认 `dateFrom/dateTo = null` 本来就是对的，不动
  （"记住用户选的筛选"本身是合理功能，缺的是**退回去的路**）；
- 货主账本 / 派单员账本两条线正在动的任何文件。

**编译状态**：动手前实测 `assembleEmuDebug` **已能编过**（20:28 exit=0，那个会话把缺的 import 补上了）。
改完会重编 + 装 5558 真机验。

---

**结论（做完）**：修复只动一个文件，已编译（`assembleEmuDebug` exit=0）+ 装 5558 真机三步验过：

1. 切「已完成」→ 档位条 + 16 条数据正常；
2. 点「今天」→ 列表空，但**档位条仍在**（`全部 | 今天 | 昨天 | 前天 | 这周 | 近 7 天`），
   空态文案指路：「这个时间段里没有已完成的订单 —— 点上面的「全部」可以看所有」；
3. 点「全部」→ **数据全部回来**（用户自己能自救，不必再杀进程）。

截图：`D:\AProjects\ppppppppppppp\logs\fix-今天-空态但档位还在.png`。

---

### [2026-09-20 20:1x → 21:0x] 会话：派单员账本页第五轮【已完成】（DSH `session-faa17a77-515b-4bcb-bd47-fddae0129342`）

**任务**（用户第五轮口述，逐条对着做）：

1. **三张图全删**：「那个折线图条形图还有扇形图，我们直接去掉就行了啊，其他的都也去掉……
   到时候在报表中心看就可以了」→ 账本页一张图都不画（订单账/司机账/货主账/批发商账都一样）；
2. **时间换形态**：「那个时间也太复杂了，换一种崭新形式」→ 顶栏一个紧凑药丸
   （`DatePresetPill` + `DatePresetDialog`），页面不再铺那一行 9 个胶囊；
3. **选人换形态**：「选择司机那一行，假如司机多的话，那我要选该怎么去选呢？……选择人物，
   我们使用那种侧边栏抽屉」→ `ModalNavigationDrawer` + 抽屉里带搜索的名单；
4. **两者不许一个样**：「时间和选择人物不要选择一样的展现形式」。
5. **默认档位落在有单的那一天**：「这些时间默认是今天的，如果今天没有任何订单的话，然后再是昨天，以此类推」→ 今天→昨天→前天→近 7 天→全部；用户自己挑过之后不再自动改。

**改动清单**：

| 文件 | 改什么 |
| --- | --- |
| `android/.../ui/dispatcher/DispatcherLedgerScreen.kt` | 删图表卡/切换条/搜索那一行；顶栏加时间药丸；新增 `PersonTriggerRow` + `PersonDrawer`（抽屉） |
| `android/.../ui/dispatcher/DispatcherLedgerViewModel.kt` | 删 `chartType` 与全部图表取数；`dashboard()` 改接 `accountRows()`（抽屉搜索不改合计）；`drawerPersons()` |
| `android/.../ui/common/Components.kt` | **新增** `DatePresetPill` / `DatePresetDialog`（时间控件那一份实现） |
| `android/.../ui/common/Charts.kt`、`ui/theme/Color.kt` | 删扇形图与 `ChartPalette`（全项目只剩账本页在用）；**折线/条形留着**（报表中心在用） |
| `android/.../ui/dispatcher/LedgerCharts.kt` + 两个单测 | **删除**（没人调了） |
| `_tools/qa/_check_ledger_dashboard.py`、`_reverse_verify_ledger_dashboard.py` | 判据按第五轮重写（+2 条注入，共 25 条全部成立） |
| `_tools/qa/_check_user_search.py` | 账本那两条跟着抽屉改（31 项） |
| `docs/PROJECT_MAP/06_DESIGN_SYSTEM.md` | §4.14 更新 + **新增 §4.15**（两个筛选控件不许一个样） |
| `docs/PROJECT_MAP/08_CODE_LOCATOR.md` | 只更新「账本管理」那一行 |

**明确不碰**：另一个会话的 `shipper_ledger` / `ShipperLedger*` / `Apis.kt` / `Dtos.kt` /
`AppRepository.kt` / `ReportCenter.kt` / `enums.py` / `schema_bootstrap.py` / `_app_feature_coverage.py` /
`_write_coverage.py`（这一轮我**没有新增端点**，那些表都不用重跑）。

**结论**：用户第五轮那 4 条全部落地，模拟器 5556 真机逐条验过：

- 「货主账」页：顶栏 货主账 + 时间药丸 近 7 天 ▾；正文第一行「人员 全部（25 人）… 选择 ›」；
  下面直接是合计卡（货主账合计（近 7 天）· 25 个账户 · 共 91 笔）——**一屏没有图**；
- 药丸 → 「看哪一段时间」清单（全部/今天/昨天/前天/这周/近 7 天/上周/本月/上月/自定义 + 打勾 + 关闭）：
  点「近 7 天」后合计与账户数（32→25）当场跟着变；
- 「选择」→ 侧边抽屉：「选择货主」+ 搜索框 + 「全部（25 人）」+ 名单（名字 / 手机号，选中那行打勾）；
  在抽屉里输 1942 → 只剩「百味居客家菜馆 13613619429」（后 4 位匹配），而「全部（25 人）」仍是 25（搜索只筛名单）；
- 点那个人 → 抽屉自动关，进他的账：应收 ¥807.90 / 已收 ¥0.00 / 欠款 ¥807.90 +
  「核销全部（2 单 · ¥807.90）」+ 「这些货（近 7 天）」表；
- 静态检查 48/48 全绿；反向验证 _reverse_verify_ledger_dashboard 25/25、_reverse_verify_user_search 25/25；
  演示数据 _verify_demo_data.py 69/69。

⚠️ 两件跨会话的事记在下面「交叉点」里（AiWriteService.kt 缺 import、AiWriteTest.kt 的 FakeDs 缺 6 个实现）。

---

### [2026-09-20 20:xx → 20:5x] 会话：派单员账本管理改版（DSH `session-faa17a77-515b-4bcb-bd47-fddae0129342`）

**结论：用户第四轮那 5 件事全部落地，模拟器 5556（派单员）真机逐条验过，静态检查与反向验证全绿。**

改了什么（与「进行中」那张表一致，这里只记结论）：

1. **4 页签导航删掉**：账本页 = 一类账一页（档位由入口页那一格定，构造参数 `private set`），
   顶栏标题写这一类账的名字；
2. **排版**：搜索 → 日期档位 → **人员（默认「全部」）** → 图 → 数据；图与明细都跟着选的人走
   （选中货主后折线有了，选中司机后图是"他每天应得多少"）；
3. **司机结算单入口从账本页删掉**（功能还在：工作台那一格）；司机那一层显示"应得运费 + 他跑的单"，
   **没有核销**（那笔钱不是应收）；
4. **批量核销**：某个人的「合计」下面一键收清这一段所有未结清的单（一张收款单绑全部订单，
   逐单各一条流水）；「全部人」那一层不给（红线钉着）；
5. **整单核销的金额改成"还欠的钱"**（`m.receivable` → `m.arrears`）：原来按商品核销过一部分的单
   两边金额对不上、从此收不动；凑巧对上就是多收。已用注入法证明新测试真的能抓到它。

真机证据（模拟器 5556）：

- 货主账：`搜姓名/手机号 → 全部/今天/…/近 7 天 → 人员 全部（32 人）+ 三个 chip → 条形/扇形 +
  「账户排行 · 本月」→ 货主账合计 ¥22494.10（32 个账户 · 共 220 笔）`；
- 选中「新叶生鲜配送」：图变成折线（09/01…09/16）、标题「新叶生鲜配送 · 本月」、
  应收 ¥2332.20 / 已收 ¥0.00 / 欠款 ¥2332.20、按钮「核销全部（6 单 · ¥2332.20）」；
- 弹层逐单列出 6 张（874.80 / 52.30 / 934.30 / 137.00 / 107.00 / 226.80 = ¥2332.20）；
  确认后库内：**收款单 #13（2332.2，itemized，6 个 order_ids）+ 6 条逐单流水（合计 2332.2）+
  6 张单 paid=1**，而这一段之外的 7 张未收单没被顺手收掉（验证后已精确回滚，演示数据回到原状）；
- 司机账：`人员 全部（16 人）`、「司机应得 · 本月」图、合计 ¥2776.00；点「赖俊杰」→
  「应得运费 ¥468.00 / 6 单」+ 他跑的单（每行 **应得 ¥78.00** + 小字「运费 ¥74.00」，
  6×78=468 与合计对得上）；**没有「司机结算单」入口**。

顺手修的（都属于"同一个数两处算法"这一类）：

- `DriverOrderLines` 那一行原来显示**货主运费**（`freight_fee`），与组头合计/图（`pay_total`）对不上；
  这一列现在抬进了"某个人"那一层的合计底下，会一眼看见 → 改成显示**司机应得**，
  货主运费用小字另标注（与 `FreightSettlementScreen` 同一套写法）。
- `_tools/seed/_verify_demo_data.py` 的商品两条判据只看**没被软删**的商品：模糊测试留下的
  `fuzz-xxxx`（软删、0 价、无分类）会让这两条**永远红**（永远红的检查 = 没有检查）。

**没做**：没有新增后端端点，所以 `08A_ENDPOINT_INDEX.md` 与 AI 读/写能力表都不需要重跑。

---
