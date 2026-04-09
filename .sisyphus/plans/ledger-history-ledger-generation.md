## Plan: Ledger generation from historical orders (shipper + dispatcher viewing, dispatcher editing)

## TL;DR
- 目标：基于历史订单数据，为每个货主(shipper)创建账本条目（Ledger），账本可被货主和派单员查看；仅派单员具备编辑权限。账本字段包括：商品名称、数量、单价、总价、订单号等，订单号可点击跳转查看相关订单。
- 实现方式：后端提供历史数据提取服务与 Ledger 相关 REST API；前端提供 Ledger 列表视图与权限控制，本地化跳转到订单详情页。
- 验收：创建成功后 ledger 条目正确反映历史订单信息；货主/派单员可查看；派单员可编辑笔记/备注；订单号可跳转到订单详情；所有变更有审计记录。

## 背景与目标
- 系统需要读取历史订单数据并为货主创建 Ledger 记录，以便后续对账和查看历史交易。
- Ledger 模型已存在，字段包括 shipper_id, entry_date, product_name, quantity, unit_price, total, order_id, order_product_id, product_id, source, note。
- Ledger 的 source 枚举包含 ORDER 与 MANUAL，默认从历史订单生成时设为 ORDER。
- 访问控制：货主和派单员都能查看账本；仅派单员具有编辑 Ledger 的权限。

## 要求（确认点）
- 触发方式：系统自动触发或管理员/派单员触发（UI 按钮、后台任务、或计划任务）
- 输入范围：可选日期范围和/或按最近 N 天生成；默认按最近 12 个月的历史订单生成
- 输出字段：每条 Ledger 记录包含 product_name、quantity、unit_price、total、order_id、entry_date、shipper_id、source
- 关系：Ledger 与 Order、OrderProduct、Product、User(shipper) 存在外键关系，保留历史订单快照
- 编辑范围：仅 dispatcher 可以编辑 Ledger 的 note 字段，其他字段（金额、商品、数量等）不可编辑
- 展现：前端 Ledger 列表展示字段包含商品名、数量、单价、总价、订单号、日期、备注，订单号可跳转到订单详情页面
- 审计：所有创建/编辑操作附带时间戳与操作者标识

## 端点设计（REST API 提案）
- POST /api/v1/ledgers/generate-history
  - Payload: { shipper_id: number, date_from?: string, date_to?: string, max_count?: number }
  - 功能：基于历史 Orders 及 OrderProducts 生成 Ledger 条目，若存在则跳过重复条目（幂等性）
  - 返回值：生成的 Ledger 条目列表或生成数量

- GET /api/v1/ledgers
  - Query: shipper_id?: number, order_id?: number, from?: string, to?: string, page?: number, pageSize?: number
  - 权限：shipper/dispatcher 均可访问，返回该货主的 Ledger；若未提供 shipper_id，仅返回当前用户能查看的 Ledger（依据角色筛选）

- GET /api/v1/ledgers/{ledger_id}
  - 取得单条 Ledger 详情

- PATCH /api/v1/ledgers/{ledger_id}
  - Payload: { note?: string }
  - 权限：仅 dispatcher 可编辑 note
  - 功能：更新备注字段，维护审计记录

- PATCH /api/v1/ledgers/batch-update-note
  - Payload: { ledgers: [{ ledger_id: number, note: string }] }
  - 权限：仅 dispatcher

- GET /api/v1/ledgers/{ledger_id}/orders
  - 关联的订单历史数据跳转入口，前端可直接跳转到 /orders/{order_id}

## 数据模型变更（后端）
- Ledger 表格保持现有结构；新增约束/索引以支持生成幂等性
- 新增服务：LedgerHistoryService（从 Orders/OrderProducts 查询历史数据并生成 Ledger）
- 审计字段：在 Ledger 创建/更新时填充 created_by_id / updated_by_id 以及 timestamp

## 业务规则要点
- 账本条目来自历史订单快照：product_name、quantity、unit_price 来自 OrderProduct 及 Product，total = quantity * unit_price
- shipper_id 指向货主，entry_date 取订单日期，order_id 绑定到相关订单
- source = LedgerSource.ORDER
- 账本可供货主查看，派单员可编辑备注；编辑仅限 note 字段以避免破坏性修改

## 迭代计划（Wave）
- Wave 1：后端实现
  - 实现 /ledgers/generate-history，读取 Orders/OrderProducts，生成 Ledger 条目
  - 实现 /ledgers 与单 Ledger 的读取接口，以及 /ledgers/{id} 的详情
  - 实现 dispatcher 权限控制，确保只有派单员能 PATCH/UPDATE notes
  - 添加单元测试：生成历史账本、只读、只编辑备注

- Wave 2：前端实现
  - LedgerList 视图：展示 ledger => product_name, quantity, unit_price, total, order_id(可跳转), entry_date, note
  - 增加“生成历史账本”按钮（仅调度端可见）及日期范围选择
  - 编辑备注的 UI 与权限控制：仅 Dispatcher 可编辑备注
  - 点击订单号跳转到订单详情页 /orders/{order_id}

- Wave 3：集成测试与回归
  - 验证历史数据生成的幂等性
  - 验证权限控制（shipper vs dispatcher）
  - 验证 UI 的无障碍与性能

## 验收标准（DONE）
- 后端能基于历史订单生成 Ledger，且条目字段正确填充
- Ledger 对应的 shipper 能查看，dispatcher 也能查看；dispatcher 能编辑 note
- Ledger 列表中包含 product_name、quantity、unit_price、total、order_id、entry_date、note、source
- 点击订单号可跳转到对应订单详情页
- 审计日志记录创建/编辑行为

## 风险与回退
- 若历史订单数据量巨大，需分页/分批生成，并可中断/继续
- 需要确保数据一致性（多点写入时的幂等处理）

## 执行者与依赖
- 依赖现有 Ledger/Order/OrderProduct 模型与权限控制
- 需要前端路由 /orders/{order_id} 的存在与对应页面

### 交付物
- API Contract 文档（OpenAPI/Swagger 草案）
- Ledgers API 实现代码变更计划
- Frontend LedgerList 组件及相关路由/页面变更
- 测试用例与测试数据

-----
如需，我可以把此 Plan 转成可直接导入的 OpenAPI 草案、以及对应的前后端实现模板（包括 DTO 结构、权限校验示例与测试用例）来推进实现。请确认是否启用自动化生成与部署。
