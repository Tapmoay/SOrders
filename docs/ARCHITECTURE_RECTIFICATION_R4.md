SOrders 第四轮整改方案 R4
Core-Stable / Extension-Open
核心稳定，扩展开放

R3 已经完成了一个很重要的跃迁：从“结构上看起来正确”走到了“生产运行时有证据”。R3 的施工纪律也已经明确要求：每个完成项必须有可执行退出条件，不允许只靠文档宣称完成；而且 R3 的过程中已经证明，真正有价值的是让演练去逼出真实缺陷，而不是不断堆检查器。

R4 不再继续追求“把系统拆得更细”。

R4 要解决的是另一个问题：

未来不断新增能力时，新增的复杂度尽可能留在自己的边界内，而不是扩散到 SOrders 核心。

这和“全系统模块化”是两件完全不同的事。

一、R4 的总目标

最终希望 SOrders 形成这样的结构：

                          SOrders
                             │
             ┌───────────────┴───────────────┐
             │                               │
       CORE / KERNEL                  EXTENSION ZONE
         固定核心                         扩展区域
             │                               │
             │                    ┌──────────┼──────────┐
             │                    ↓          ↓          ↓
             │                 Unit       Pricing    Export
             │               Conversion   Rules      Provider
             │
             ├─ Order Lifecycle
             ├─ Money / Ledger Truth
             ├─ Identity
             ├─ Authorization
             ├─ Core Audit
             ├─ Core Transaction Rules
             ├─ Core Persistence Invariants
             ├─ Outbox Reliability
             └─ Core Runtime / Security

核心区域：

固定语义
固定不变量
固定生命周期
固定安全边界
固定事实模型

扩展区域：

可以新增
可以替换
可以升级
可以禁用
可以拆除

核心不能被插件替换。

但核心也不能被写成：

if unit == "kg":
    ...
elif unit == "lb":
    ...
elif unit == "jin":
    ...
elif pricing == "cold_chain":
    ...

所以真正的目标是：

核心固定的是“语义与契约”，而不是每一种可能的实现。

二、先把 R4 最重要的一句话钉死
核心不可插拔，边缘能力可插拔。

更准确一点：

核心负责定义“什么是真的”，扩展负责定义“怎么做”。

例如：

订单核心

核心定义：

订单是什么
订单有哪些核心状态
什么叫接单
什么叫完成
什么叫取消
状态迁移是否合法

这些不是插件。

价格计算

核心定义：

Money
Currency
Rounding
Ledger
Transaction

但是：

怎么算基础运费
怎么算重量附加费
怎么算偏远地区费
怎么算促销折扣

可以放到扩展侧。

于是：

                 Core Money
                     ↑
                     │
              Pricing Contract
                     ↑
       ┌─────────────┼─────────────┐
       │             │             │
 Standard Pricing  Weight Rule  Cold Chain Rule

价格规则可以换，账本事实不能换。

这个原则会贯穿整个 R4。

三、R4 第一件事不是写代码，而是划边界

这是整个 R4 最容易做错的地方。

SOrders 之前已经建立了 15 个领域、47 张表、57 个命令、18 个事件等边界资产。

现在不要看到这些数字就开始：

“那我们是不是给 15 个领域全部做成模块？”

不要。

R4-01 必须先重新分类：

CORE
EXTENSION POINT
EXTENSION IMPLEMENTATION
INFRASTRUCTURE
四、R4-01：Core / Extension Boundary Map
目标

建立一份唯一的：

docs/R4_CORE_EXTENSION_MAP.md

把系统中的能力逐项归类。

建议使用下面这套判断规则。

判断规则 1：它是否定义系统事实？

如果它决定：

订单最终是什么状态
账本最终记了多少钱
谁是谁
谁有没有权限
一笔事务是不是成功
一个事件是否可靠投递

→ Core

判断规则 2：它变化时，系统核心语义是否应该改变？

例如：

“Ledger 应不应该存在”

改变这个问题，整个 SOrders 的核心模型都变了。

→ Core。

但：

“这个订单怎么计算体积重”

改变的是规则实现。

→ Extension。

判断规则 3：这个能力消失以后，核心业务还能不能成立？

比如：

Excel 导出
PDF 导出
AI 助手
某个通知渠道
某种单位
某种特殊计费

删除以后：

Order
Money
Auth
Ledger

仍然成立。

→ Extension。

判断规则 4：插件是否应该能够决定核心事实？

只要答案是：

是

就先判 Core。

因为一旦插件可以决定：

Order Complete 是什么
Ledger 是否记账
权限是否合法
审计事实是否成立

那核心实际上已经被插件反向控制。

这会直接破坏 R4 的目标。

五、建议的初始 Core

这里先给一个候选分类，不直接宣布它最终正确。

R4-01 要由你们的代码和已有边界资产最终确认。

Core 候选
Order Lifecycle
Money / Ledger Truth
Identity
Authorization
Core Audit
Core Transaction Rules
Core Persistence Invariants
Outbox Reliability
Request / Command Core Semantics
Security
Business Time
Core Runtime

R3 的生产演练已经证明 socket_io.py 位于可靠投递边界，因此这种“承重核心”不能因为想做插件化就随便拆出去。

六、建议的 Extension 候选

这些才是 R4 第一批真正值得研究的对象：

Unit Conversion
Pricing Rules
Fee Calculation
Tax Calculation
Promotion / Discount Rules
Report Renderer
Import / Export
Notification Provider
AI Provider
Search / Ranking Provider
File Format Provider
External Integration Provider

但是要注意一个非常关键的坑：

“计算”可以扩展，“事实”不能扩展。

例如：

运费计算器           ✅ Extension
司机结算公式         ✅ 可以扩展
Ledger               ❌ Core
Money 类型           ❌ Core
账务最终落账         ❌ Core

这是 R4 必须反复检查的一条线。

七、R4-02：设计 Extension Contract，而不是 Universal Module Interface

这里我特别提醒你：

千万不要设计一个“万能插件接口”。

例如：

class Plugin:
    initialize()
    execute()
    shutdown()

然后所有东西都往里面塞。

这是一个非常典型的“看起来模块化，实际上把复杂度藏起来”的坑。

因为：

UnitConversion
Pricing
AI Provider
Excel Exporter
Notification

这些东西根本不是同一种能力。

所以 R4 应该设计的是：

多种稳定扩展契约

而不是：

一个万能插件基类。
八、第一类：Pure Function Extension

适合：

单位换算
税率计算
数学计算
格式转换
纯规则

特点：

输入明确
输出明确
无副作用
不碰数据库
不碰核心状态

例如：

UnitConversionContract

convert(
    value,
    from_unit,
    to_unit
) -> Quantity

核心只认识：

Quantity
Unit
Dimension

具体：

kg → g
lb → kg
斤 → kg

由扩展提供。

九、第二类：Policy Extension

适合：

定价
折扣
运费
税费
佣金
特殊业务规则

比如：

PricingContract

calculate(
    PricingContext
) -> Money

核心拥有：

Money
Currency
Rounding
Transaction
Ledger

扩展拥有：

PricingAlgorithm

于是：

StandardPricing
WeightPricing
RegionalPricing
ColdChainPricing
PromotionPricing

都可以成为实现。

十、第三类：Provider Extension

适合：

AI
短信
邮件
推送
对象存储
第三方地图
第三方物流

结构：

Core Contract
      ↑
      │
Provider Adapter
      ↑
 ┌────┴────┐
A Provider B Provider

核心不应该知道：

OpenAI
Qwen
某短信平台
某邮件服务商

这些都是实现细节。

十一、第四类：Presentation / Format Extension

例如：

Excel
PDF
CSV
JSON
特殊报表

核心定义：

Report Data

扩展负责：

怎么渲染
怎么导出
怎么排版

这特别适合你的现有架构，因为原始架构中 Excel/PDF 就已经属于明显的外围能力，而不是核心订单事实。

十二、R4-03：建立 Dependency Firewall

这个是 R4 的真正核心工程。

目标不是“模块之间没有依赖”。

而是：

模块可以依赖，但只能依赖稳定契约。

允许：

Pricing
    ↓
Pricing Contract
    ↓
Money Core

不允许：

Pricing
    ↓
ledger.py 私有函数

不允许：

Report
    ↓
直接 UPDATE orders

不允许：

AI
    ↓
绕过 Capability

不允许：

Extension
    ↓
直接修改另一个 Extension 的表
十三、依赖方向要明确

建议 R4 钉死：

CORE
 ↑
 │
EXTENSION
 ↑
INFRASTRUCTURE

更准确地说：

Core Contract
      ↑
Extension Implementation
      ↑
Infrastructure Adapter

Core 不能反向依赖具体 Extension。

例如：

Core → PricingContract       ✅
Pricing → MoneyCore          ✅

Core → ColdChainPricing      ❌
Money → SpecificAIProvider   ❌

这是非常重要的单向性。

十四、R4-04：Data Ownership 必须继续强化

这里是最危险的坑之一。

很多系统表面模块化：

pricing/
notification/
report/

但是：

pricing
直接改 orders

report
直接改 ledgers

notification
直接改 users

那模块化就是假的。

建议继续沿用 R2 已经形成的：

一个数据实体 / 表只有一个 Owner。

其他模块：

读取 → Query

请求变化 → Command

被动获知 → Event

这样：

Pricing

不能：

UPDATE ledger

它只能：

calculate → Money

然后把最终事实交给 Core。

十五、R4-05：建立 Extension Registry

到这里才真正开始做：

Extension Registry

注意，不是动态插件市场。

而是：

系统启动时，知道当前有哪些合法扩展。

例如：

extension:
  id: unit-conversion
  version: 1.0
  kind: calculator

requires:
  - quantity.core

provides:
  - unit.convert

config:
  - UNIT_SYSTEM

这里的 Manifest（扩展清单）非常有价值。

它至少应该声明：

id
version
kind
requires
provides
consumes
emits
config
compatibility

如果涉及数据库，再增加：

owns_tables
十六、但是不要马上做“动态安装/热插拔”

这是我最想提前阻止你的坑。

你的“插块”应该先意味着：

代码层
部署层
系统架构层

可以：

添加
升级
禁用
删除

而不是：

生产服务器运行中
↓
上传 Python 文件
↓
立即热加载

后者会突然产生：

版本兼容
状态迁移
热加载
进程状态
安全边界
插件来源可信度
回滚
依赖冲突

复杂度瞬间爆炸。

R4 第一阶段：

可安装的模块化单体。

不是：

动态插件运行时。

十七、R4-06：兼容性设计

这是你刚才说：

“模块不能写得太死。”

真正对应的地方。

每个扩展接口必须有：

Contract Version

例如：

PricingContract v1

未来：

PricingContract v2

不要直接：

v1 → 删除

可以：

v1
↓
Adapter
↓
v2

这样：

旧 Pricing Module

还可以运行。

十八、但这里又有一个坑：不要过度做版本系统

不要一开始就搞：

API v1
API v2
API v3
v1 adapter
v2 adapter
v3 compatibility matrix

整个系统还没有稳定扩展点之前，这会变成另一种过度设计。

R4 的原则：

先证明“这个契约真的会被多个实现使用”，再为它设计长期版本兼容。

所以第一个版本的 Contract 可以非常简单：

Interface
Input Schema
Output Schema
Error Semantics
Compatibility Rule

够了。

十九、R4-07：第一个真实模块 —— Unit Conversion

我建议 R4 第一个真实实验就拿：

Unit Conversion

原因非常好：

业务重要性适中
边界清晰
低副作用
非常容易测试
非常容易增加实现
非常容易删除

先做：

Unit
Dimension
Quantity
ConversionContract

然后实现：

SI

再增加：

Imperial

然后：

China-traditional

整个过程中：

Core 不应该为了新增一种单位而不断修改。

这就是第一次真实证明。

二十、R4-08：第二个真实模块 —— Pricing

Unit Conversion 成功之后，再做：

Pricing / Fee Calculation

这一次复杂很多。

因为它会触及：

Order
Money
Quantity
Region
Rules
Ledger

因此它能验证：

扩展边界是否真的能承受复杂业务规则。

结构应该是：

Order
 │
 ↓
PricingContext
 │
 ↓
PricingContract
 │
 ├─ StandardPricing
 ├─ WeightPricing
 ├─ RegionPricing
 └─ SpecialPricing
 │
 ↓
Money
 │
 ↓
Core Settlement / Ledger

核心只接受：

Money

不能接受：

某个插件自己的对象

这点非常重要。

二十一、R4-09：真正验证“插块”

这里开始做三个 Architecture Drills。

Drill M1：Add

加入一个全新扩展。

例如：

UnitConversion v1

要求：

Core 修改数量尽可能为 0
Core 数据模型不增加扩展专用字段
Core 不出现 extension-specific if/else
既有模块无需修改
二十二、Drill M2：Replace

把：

Pricing A

替换成：

Pricing B

核心不变。

如果：

Order
Money
Ledger

跟着一起修改很多地方。

说明契约设计还不够好。

二十三、Drill M3：Remove

这是整个 R4 最重要的演练。

完整删除一个扩展：

安装
↓
运行
↓
停用
↓
卸载
↓
删除

然后验证：

Core 启动
Order
Money
Auth
Audit
Outbox
Reports Core

依然正常。

二十四、这里有一个非常大的坑：Remove ≠ Delete Historical Data

比如：

Pricing Module

曾经生成了历史账单。

然后你把模块删除。

历史账单不能因此消失。

所以 R4 的“拆除”必须区分：

Disable
Uninstall
Code Removal
Data Removal

四件不同的事情。

尤其：

扩展被删除，不代表它创造的历史事实可以删除。

这是涉及 Money / Audit / Order History 时必须钉死的。

二十五、R4 的数据应该分三类
A. 核心事实
Order
Ledger
Identity
Audit

不能随着 Extension 删除。

B. Extension-owned operational data

例如：

pricing_rules
unit_definitions
provider_config

可以随着模块生命周期处理。

C. Historical Projection

例如：

某次订单当时使用了什么计费规则

可能必须保存快照。

否则未来：

Pricing Module v1

删掉以后：

历史订单

都解释不了了。

这就是很多插件系统最后踩死的大坑。

二十六、R4-10：配置也要模块化

经常被忽略。

新增一个模块之后，如果还要手动：

settings.py
.env
main.py
config.py

改四五个地方。

那它就还不是很好插。

所以：

Extension Manifest
        ↓
Config Declaration
        ↓
统一 Config Loader

但是这里要注意：

核心配置和扩展配置分离。

不要让一个扩展的环境变量污染整个系统：

CORE_DATABASE_URL
CORE_SECRET
...

与：

EXT_PRICING_*
EXT_AI_*
EXT_EXPORT_*

分开。

二十七、R4-11：API 也要避免“插一个功能改主路由总表”

这是非常容易出现的。

不要最后又变成：

if module_enabled:
    include_router(...)

到处都是。

更合理的是：

Extension
   ↓
declare routes
   ↓
registry
   ↓
application composition

但是要注意：

路由可以由 Extension 提供，但认证、权限、核心安全策略不能被 Extension 自己定义成另一套体系。

继续使用你 R3 已经建立的 Capability / Permission 体系。

也就是说：

Extension declares capability
        ↓
Core authorization
        ↓
route

而不是：

Extension 自己写一套权限

R2 已经证明“能力必须有真正执行点，而不是漂亮声明”这一点，因此 R4 也应该继承这个原则。

二十八、R4-12：事件系统要非常小心

Event 是一个很容易让模块化走向“蜘蛛网”的东西。

错误：

A → event
B → event
C → event
D → event
E → event

最后：

OrderChanged

所有模块都在监听。

谁也不知道：

删掉 B 会不会把 D 搞坏

所以 R4 对 Event 的规则应该是：

Event 是事实通知，不是隐藏调用。

不能：

OrderCompleted
→ 15 个模块悄悄依赖
→ 其实其中 8 个是核心业务必需

如果它是必需业务流程：

Command

通常比：

Event

更合适。

Event 适合：

“事情已经发生了。”

Command 适合：

“请做这件事。”

这会是 R4 很重要的一条防腐规则。

二十九、R4-13：建立模块依赖图

完成前面以后，系统应该可以自动生成：

Order Core
   ↑
Pricing Extension
   ↑
Tax Extension

Notification
   ↑
SMS Provider

然后系统可以回答：

谁依赖谁？
谁依赖这个模块？
谁拥有这个表？
谁提供这个 capability？
谁监听这个 event？

这个图非常重要。

因为真正的模块化不是“目录结构看起来漂亮”。

而是：

依赖关系是有限的、可解释的、可验证的。

三十、R4 的 Static Checker 不要再像 R3 那样不断增长

这是一个很重要的 R4 防腐原则。

R3 已经暴露了：

checker self-reference
checker 被弱化
file existence 伪通过
报告数字漂移

所以 R4 不应该：

每发现一个坏结构，再增加一个 500 行 checker。

建议只做几个真正稳定的检查：

_check_core_extension_boundary
_check_extension_dependencies
_check_data_ownership
_check_extension_manifest
_check_extension_contracts

然后每个检查器必须有：

为什么代码边界无法解决
反向破坏用例
静默空转保护

没有这些，不准进入 R4 核心工具。

三十一、R4 最容易踩的 15 个坑

这里我给你直接列成“施工禁区”。

坑 1：为了模块化拆核心

看到 order/ 很大，就开始拆。

禁止。

核心复杂 ≠ 应该插件化。

坑 2：万能 Plugin Base
Plugin.execute()

什么都往里面塞。

禁止。

按能力类型设计 Contract。

坑 3：Core 反向依赖 Extension
Core → ColdChainPricing

一旦出现，R4 就开始倒退。

坑 4：Extension 直接改 Core 表

例如：

UPDATE orders

禁止。

必须走 Core Command。

坑 5：Extension 直接写 Ledger

这是最高危的一类。

应该：

calculate → Money → Core transaction

而不是：

calculate → UPDATE ledger
坑 6：为了“通用”提前抽象

比如：

AbstractBusinessRuleFactoryFactory

这种东西。

不要。

先有两个真实实现，再决定抽象。

坑 7：过早做动态加载

先做：

deploy-time modularity

不要马上做：

runtime hot plugin
坑 8：配置散落

安装一个模块要改十个配置文件。

说明模块边界没有闭合。

坑 9：删除模块导致历史数据无法解释

这是 Money / Audit 特别危险的坑。

坑 10：事件变成隐形 RPC

如果业务离不开它，却通过 Event 偷偷完成。

模块依赖会变得不可见。

坑 11：权限被插件私有化

Extension 可以声明能力。

但是不能出现：

extension_permission.py

然后另起一套授权世界。

坑 12：Extension 专属字段进入 Core Model

例如：

orders.cold_chain_fee
orders.special_pricing_type
orders.ai_score

这样核心会不断膨胀。

更适合：

Extension-owned data

或者稳定契约产生的结果。

坑 13：为了兼容性保留 10 代接口

这会变成历史垃圾场。

只为真正存在的旧实现提供兼容层。

坑 14：模块数量本身成为 KPI

不要追求：

100 modules

模块数量越多完全不代表架构越好。

坑 15：把“能拆”误认为“值得拆”

有些东西技术上能拆。

但拆完之后：

依赖更多
理解成本更高
测试更复杂
事务更困难

这种就不要拆。

三十二、R4 的核心判断法

以后每碰到一个新功能，只问这五个问题：

① 它是否定义核心事实？
② 它是否改变核心不变量？
③ 它是否必须永久存在？
④ 它是否可能出现多个实现？
⑤ 删除它后 Core 是否仍然成立？

大致：

1/2/3 = 是
→ Core 候选

4/5 = 是
→ Extension 候选

真正模糊的地方：

先不要抽象。

等第二个实现出现，再重新判断。

三十三、R4 的实际施工顺序

我建议你严格按照下面走。

R4-00：冻结基线

记录：

当前 commit
R3 report v2.6
R3_PROGRESS
119 static checks
1020 backend tests
Production Runtime 10/10

并且将：

socket_io.py

正式加入：

_core_files.txt

但同时把规则写进去：

核心区不是永久禁止修改，而是只能通过证据触发的例外机制修改。

这样 R3 的经验也被纳入 R4。

三十四、R4-01：Core / Extension Map

不改代码。

交付：

docs/R4_CORE_EXTENSION_MAP.md

内容：

Core
Extension Point
Extension
Infrastructure
Unclassified

最后必须：

Unclassified = 0

或者每一项明确：

Pending decision
Reason
三十五、R4-02：Contract Design

选择两个最值得扩展的领域：

Unit Conversion
Pricing

设计：

UnitConversionContract v1
PricingContract v1

先写：

输入
输出
错误
不变量
兼容要求
生命周期

不马上做插件框架。

三十六、R4-03：Dependency Firewall

实现：

Core cannot import concrete Extension
Extension cannot mutate Core-owned data directly
Extension cannot bypass Capability
Extension cannot direct-import private internals

做最小静态检查。

三十七、R4-04：实现 Unit Conversion

要求：

Core unchanged
Extension self-contained
Contract tested
Add implementation tested
Remove tested

完成第一个：

“插块”

证明。

三十八、R4-05：实现 Pricing

比 Unit Conversion 更复杂。

验证：

Order → Pricing → Money Core

能够成立。

然后替换两种 Pricing implementation。

验证：

Core 不动
三十九、R4-06：Remove Drill

完整删除 Unit Conversion。

然后：

full static checks
backend tests
core smoke
API smoke

确认：

没有 orphan route
没有 orphan capability
没有 orphan config
没有 orphan import
没有破坏核心数据
四十、R4-07：Compatibility Drill

故意：

PricingContract v1
→ v2 implementation

验证：

旧实现还能工作
新实现可以加入
核心无需修改
四十一、R4-08：最终架构验收

最终不是看：

“模块数量增加了多少”

而看下面五条：

1. 新增扩展不会污染 Core
2. 替换扩展不会修改 Core
3. 删除扩展不会破坏 Core
4. 扩展依赖全部可见
5. 历史核心事实不会因为扩展删除而失效
四十二、R4 的最终验收矩阵

建议最终做成：

能力	Code	CI	Runtime	Add	Replace	Remove
Core Boundary	✅	✅	✅	—	—	—
Unit Conversion	✅	✅	✅	✅	✅	✅
Pricing	✅	✅	✅	✅	✅	✅
Dependency Firewall	✅	✅	✅	✅	✅	✅
Data Ownership	✅	✅	✅	✅	✅	✅
Compatibility	✅	✅	✅	—	✅	✅

这里最重要的是：

Add / Replace / Remove 不再是静态概念，而是实际演练。

四十三、R4 完成之后，你的开发方式会发生什么变化

未来新增：

“单位换算”
新增 Extension
        ↓
注册 Contract
        ↓
完成测试
        ↓
安装

核心不用乱。

未来新增：

“新的计费规则”
Pricing Extension
        ↓
PricingContract
        ↓
Money Core

核心仍然稳定。

未来删除：

“某种 AI 服务”
Disable Provider
        ↓
Core fallback
        ↓
AI 功能消失
        ↓
Order / Money / Auth 正常

这才是你真正想达到的：

“插块式开发”

但我要把一句话再强调一次：

插块的不是 SOrders 的核心业务；插块的是围绕核心稳定语义不断变化的能力。

四十四、我给 R4 的最终北极星

我建议把这一句直接写进：

docs/ARCHITECTURE_RECTIFICATION_R4.md

SOrders 的核心业务负责稳定系统语义；扩展模块负责承载变化。任何变化如果会迫使核心不断认识具体实现，就说明扩展边界设计失败。

再进一步：

好的模块化，不是让所有东西都可以拔掉；而是让不应该影响核心的变化，真的不会影响核心。

最后给你一个非常重要的施工原则

R4 千万不要一开始就大重构。

你现在最容易犯的错误，反而是：

R3 完成
↓
觉得架构已经成熟
↓
开始大规模拆 15 个领域
↓
建立 Plugin Registry
↓
建立统一 Module Base
↓
建立动态加载
↓
建立版本系统
↓
两周以后又需要 R4.1 救火

这条路不要走。

R4 应该是：

Boundary
   ↓
Contract
   ↓
一个小扩展
   ↓
Add Drill
   ↓
Replace Drill
   ↓
Remove Drill
   ↓
第二个复杂扩展
   ↓
Compatibility
   ↓
才总结成框架

也就是：

先用两个真实模块证明架构，再把成功的模式抽象成基础设施。

这是 R4 和前几轮最大的不同。

R3 的问题是“系统有没有真的运行”；R4 的问题则变成了：

“系统能不能在持续演化的同时，保持自己的核心不被侵蚀。”

---

# 附录 A（⛔ 不是指南原文）：R4 的北极星与验收矩阵

> 上面 **26669 字节**（SHA256 `E45A6CAF01143418BDB5F20D36401382456754C267367424B3FAE91D9DA230E0`）
> 是用户 2026-09-27 交来的 R4 指南**逐字节原文**（`C:\Users\Optimistic\Desktop\ppkk.md`）。
> 这一节是**施工方**加的 —— ⛔ 不要把它读成指南的一部分。

## A.1 北极星（指南 §44 建议写在这里的那一句）

> **SOrders 的核心业务负责稳定系统语义；扩展模块负责承载变化。
> 任何变化如果会迫使核心不断认识具体实现，就说明扩展边界设计失败。**

指南紧接着还有一句，本轮把它当成了施工判据而不是口号：

> 好的模块化，不是让所有东西都可以拔掉；而是让**不应该影响核心的变化，真的不会影响核心**。

## A.2 验收矩阵（指南 §42）

⛔ 一行的意义是**这一格被真跑证明过**，不是「代码里有」。
⛔ 这三列（Add / Replace / Remove）在本轮**都是实际演练**，不是静态概念 ——
每一条都能用 `python _tools/ops/_r4_acceptance.py --check` 现场复现。

| 能力 | Code | CI | Runtime | Add | Replace | Remove | 依据 / 出口 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Core Boundary | ✅ | ⏳ | ✅ | — | — | — | `docs/R4_CORE_EXTENSION_MAP.md`（52 条能力 / Unclassified=0）+ `_check_core_extension_boundary.py` |
| Unit Conversion | ✅ | ⏳ | ✅ | ✅ | ✅ | ✅ | R4-04；Add 出口 `_r4_add_drill.py`（Core 0 行）、Remove 出口 `_r4_remove_drill.py`（12/12 步） |
| Pricing | ✅ | ⏳ | ✅ | ✅ | ✅ | ✅ | R4-05；Replace 出口 `_r4_replace_drill.py`（换数据就换算法，Core 0 行） |
| Dependency Firewall | ✅ | ⏳ | ✅ | ✅ | ✅ | ✅ | R4-03；四条规则各有判据，`_check_extension_dependencies.py` + `_check_data_ownership.py` |
| Data Ownership | ✅ | ⏳ | ✅ | ✅ | ✅ | ✅ | R4-03；扩展不认领核心表 + 历史快照列在 + 删除演练 47 张表逐名一致 |
| Compatibility | ✅ | ⏳ | — | ✅ | ✅ | ✅ | R4-07；`_r4_compat_drill.py`（v1 实现经适配器照常跑、v2 实现给 2 行原生明细） |

**读表须知**

- `Code ✅` = 有判据在每次全量静态检查里核它（本机 **124/124**）；
- `Runtime ✅` = **在本机真跑过**（起进程 / 真库 / 真演练记录）；
- `—` = 这一轮不适用；
- ⚠️ `CI` 一列的口径严格来说是两句：判据**在全量检查里**（✅），**并且**这条提交被推到
  `origin/new` 之后 CI 跑绿过（⏳ 待定）。⛔ 在推送并确认之前，这一列**不许**写成 ✅ ——
  写上去就是"文档语义超过代码事实"，而 R3 为这条栽过四轮。

## A.3 ⛔ 这一轮**证不了**什么（如实列着，不粉饰）

1. **扩展没有被接进生产业务链路**：`Order → PricingContext → PricingContract → Money` 这条链
   在**测试里**是真的（用一张真实 `Order` 实例走完整链路），但**生产订单计价仍然走既有的核心实现**
   （`services/freight_pricing.py` / `services/driver_pay.py`）。接线会改钱的口径，
   与本轮「Core 修改数 = 0」冲突，需要单独一轮 + 单独发布 + 单独演练。
2. **两个扩展都是「纯计算」型**：`owns_tables` 都是空的。所以「扩展拥有自己的表、
   拆掉它之后那些表怎么办」这条**没有被本轮证过** —— 它是 Remove 演练里「没有数据要删」的原因，
   也正是它没被证到的原因。真出现「拥有表的扩展」时，这条要补演练。
3. **没有动态安装 / 热插拔**，而且这是**刻意的**（指南 §16）。本轮证的是「可安装的模块化单体」。
4. **生产没有跟着变**：本轮**一次都没有发布**。R4 改的是代码结构与边界，
   生产上跑的仍是 R3-06 那一版（`bb67156` 之后没有新发布）。