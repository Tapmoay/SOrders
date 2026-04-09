# Plan: Product Listing UI & Backend Visibility Sync

## TL;DR
- 目标：修复商品卡片的图片渲染、商品名同步、上架开关行为、全卡灰度处理、右上角红色“已下架”标记，以及将下架逻辑改为非破坏性（保留历史，软删除或状态变更）。前后端 API 契约需要明确，确保 UI 与服务端保持一致性。
- 采用阶段化波次执行（Wave 1~Wave 3），确保最小可用价值尽快落地，并在后续阶段完善测试与回归。

## Context
- Original Request: 调整商品列表页的显示逻辑与上架、灰度、下架标签行为，替换现有删除逻辑。
- Downstream: 以计划文档落地实现任务、测试和验收标准。
- Metis Review: 待后续评估以确保 guardrails 与边界条件。

## Work Objectives
- Core Objective: 实现前端卡片的正确图片渲染、动态商品名、全卡灰度、右上角“已下架”标记，以及上架开关的稳定行为；后端提供必要的字段与 API 路由，支持上述 UI 变化，并将删除逻辑改为软删除/状态变更。
- Deliverables:
  - Frontend: ProductCard、ProductList、Image 组件修改，灰度覆盖整卡、已下架 badge、排序调整
  - Backend: API 套件包含 GET /api/products、PATCH /api/products/{id}、软删除/状态变更处理、DTO 设计
  - 数据迁移/回滚计划与审计字段
  - 测试用例（单元、集成、端到端）
  - 验收标准清单

## Definition of Done (DoD)
- [ ] 图片加载正确显示，缺失时有占位
- [ ] 商品名随数据变化动态更新
- [ ] 上架开关能生效，前端渲染与后端数据一致
- [ ] 未上架商品整卡呈现灰度，且卡片右上角显示红色的“已下架”标签
- [ ] 已下架商品排序靠后，且不干扰其他商品的展示
- [ ] 删除逻辑替换为软删除/状态变更，旧数据保留档案并可审计
- [ ] API Contract 明确，DTO 设计与响应结构清晰
- [ ] 覆盖的测试用例通过并具备可重复性
- [ ] Plan 已经提交并等待执行

## Technical Decisions
- Frontend: React + TypeScript；修改 ProductCard 与 ProductList，统一对整卡应用 grayscale
- Backend: NestJS/Express 风格路由（待确认），新增/调整路由以支持 onShelf、grayscale、status、软删除
- Data Model 扩展：onShelf:boolean, grayscale:boolean, status: 'ACTIVE'|'INACTIVE'|'DELETED'
- Soft Delete：通过 status = 'DELETED' 实现，不真实删除
- 权限与审计：所有状态变更写审计字段
- 设计图和 UI/UX：红色已下架 badge 层级优先级高，排在卡片右上角，排序规则放在前端排序逻辑中

## Scope Boundaries
- IN：商品列表 UI、商品详情、前端交互、API 最小契约、数据变更的接口契约
- EXCLUDE：涉及支付、库存与复杂库存逻辑、深层后台运维界面实现

## Execution Strategy (Waves)
- Wave 1 (Foundation): UI 组件改造与视觉效果
  - ProductCard 更新：图片渲染、灰度覆盖整卡、右上角“已下架”徽标、标题区域绑定数据
  - ProductList: 按 onShelf、status、grayscale 排序与过滤
  - Image 子组件：提供兜底占位与缓存策略
  - 测试用例初版（UI层）

- Wave 2 (API Contracts): Backend 端契约与实现
  - API 路由：GET /api/products、PATCH /api/products/{id}
  - DTO：ProductDTO、UpdateProductDTO、ListProductsResponseDTO、BulkUpdateDTO
  - Soft Delete 实现与审计字段
  - 单元/集成测试用例设计

- Wave 3 (Migration & QA): 数据迁移、端到端验证、回滚方案
  - 数据迁移脚本与回滚策略
  - E2E 场景覆盖：UI-API-数据库的一致性
  - UI/UX 的无障碍及性能测试

## Parallelization & Agent Roles
- Wave 1: 前端变更 - 2-3 名 agent 并行执行（组件实现、样式、排序逻辑）
- Wave 2: 服务端契约 - 2 名 agent 并行设计 API Contract 与 DTO
- Wave 3: 测试与 QA - 2 名 agent 同步执行自动化测试和人工回归

## QA Scenarios (Mandatory)
- Scenario 1: 显示与占位
  - 步骤: 商品图片为空时，列表应显示占位图片，且标题可见
  - 断言: DOM 中存在 img 的 src 指向占位资源或占位 div
+ Scenario 2: 名称同步
  - 步骤: 商品名称字段变化，列表中的标题及时更新
  - 断言: 文本内容与数据源一致
- Scenario 3: 上架开关
  - 步骤: 点击开关，PATCH 更新并即时刷新
  - 断言: onShelf 字段更新，列表过滤/排序更新
- Scenario 4: 下架灰度与 Badge
  - 步骤: onShelf = false，整卡灰度，右上角出现红色“已下架”
  - 断言: 栅格排序靠后，徽标显示正确
- Scenario 5: 软删除
  - 步骤: 执行删除 -> status = 'DELETED'
  - 断言: 列表中不再出现该商品，但数据库仍保留记录
- Scenario 6: 并发更新
  - 步骤: 两个请求同时修改同一商品
  - 断言: 以乐观锁/版本控制处理冲突，并给出明确错误或版本更新
- Scenario 7: 无障碍
  - 步骤: 验证“已下架”徽标对屏幕阅读器可访问性
- Scenario 8: 端到端
  - 步骤: 从 UI 操作 -> API -> 数据刷新 -> 界面表现
  - 断言: UX 连贯且数据一致

## Final Verification Wave (All Agents)
- F1: Plan Compliance Audit — oracle
- F2: Code Quality Review — unspecified-high
- F3: Real Manual QA — unspecified-high (+ Playwright if UI)
- F4: Scope Fidelity Check — deep

## Acceptance Criteria (Consolidated)
- 前端和后端契约完全吻合，UI 交互符合需求，灰度策略正确应用，已下架徽标正确显示并排序，软删除完成且数据可追溯。
- 全量测试通过且可重复执行。

## Deliverables
- 1 x Draft: product-listing-ui-backend-plan.md (已经生成，以供进一步修订)
- 1 x Plan: product-listing-ui-backend-plan.md（完整执行计划）
- 参考后续迁移脚本与测试用例文档。

*** 注：计划以当前探索结果为基础，若你愿意，我可以将具体的 API 路径和 DTO 结构化为最终契约文本（如 OpenAPI/Swagger 风格）并附带样例请求/响应。***
