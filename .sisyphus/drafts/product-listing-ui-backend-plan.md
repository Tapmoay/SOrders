# Draft: Product Listing UI + Backend Visibility Plan

## Requirements (confirmed)
- Frontend product cards must render images correctly (fallback when image missing)
- 商品名称需要随商品信息变化而更新
- 在商品卡片上显示一个“上架/下架”开关，能切换状态
- 全局将未上架商品应用灰度显示效果，覆盖整张卡片，而非局部局部元素
- 商品右上角显示红色的已下架文字“已下架”；文本应位于列表中靠后的位置，不影响已存在的删除逻辑
- 以非破坏性方式处理下架/删除：关闭商品上架不是删除数据，而是变更状态并隐藏在普通列表中，保留历史记录
- API 需要支持前端变更所需的字段（onShelf、grayscale、status），并走软删除逻辑或标记状态

## Technical Decisions
- 前端：React + TypeScript；修改 ProductCard、ProductList、Image 组件，应用全卡片灰度过滤和右上角徽标
- 后端：Node/NestJS/Express 风格路由（待确认具体栈），新增/调整路由以支持列表获取、单条更新、以及软删除
- 数据模型扩展：新增字段 onShelf: boolean, grayscale: boolean, status: 'ACTIVE'|'INACTIVE'|'DELETED'
- 认证与审计：变更操作写审计字段 updatedAt、 updatedBy（若有鉴权中台则走现有中台鉴权机制）
- 删除逻辑：提供软删除路径，避免物理删除，保持历史可追溯
- 灰度策略：前端渲染层实现 grayscale 变量，服务端也应能返回 grayscale，便于 UI 统一呈现
- 兼容性：新字段若不存在于历史数据，需提供默认值或回填脚本，且逐步迁移

## Research Findings (Backend/DTOs & Routes)
- Endpoints 概念化候选：
  - GET /api/products  清单，支持分页、过滤 onShelf= true/false、grayscale、status
  - GET /api/products/{id} 详情
  - PATCH /api/products/{id}  更新字段：{ onShelf, grayscale, status }
  - PATCH /api/products/bulk-update  批量更新
  - DELETE /api/products/{id}  Soft/Delete 取决于策略
- DTO（示例名）：ProductDTO, UpdateProductDTO, ListProductsResponseDTO, BulkUpdateDTO
- 设计原则：响应中携带 onShelf、grayscale、status，前端按该字段渲染 UI；下架文本应为“已下架”且定位在卡片右上；灰度应覆盖整个卡片区域

## Open Questions
- 具体后端栈与路由前缀（NestJS/Express、/api/v1 或 /api）
- 灰度字段的实际渲染位置，是仅前端 CSS 还是需服务端返回灰度图资源
- 软删除的标记字段名与默认策略（默认是否可见）
- 授权策略：哪些角色可以变更 onShelf/grayscale/status

## Scope Boundaries
- IN：产品列表页、单品详情页、商品卡片及其状态、前端渲染逻辑、基础后端路由契约
- EXCLUDE：复杂的商品分类/筛选逻辑、与支付、库存的深度业务耦合、后台运维界面实现

## Acceptance Criteria (Draft Verifiable DONE)
- [ ] Frontend 商品卡片在图片缺失时显示兜底图片/占位符
- [ ] 商品名称随后端数据变化实时更新
- [ ] 上架开关能正确改变 onShelf，其结果能在列表中即时过滤/排序
- [ ] 整个商品卡片应用 grayscale，未上架时整卡呈现灰度效果
- [ ] 右上角出现红色文本“已下架”并且该卡片排列在列表末尾或单独排序规则中
- [ ] 删除逻辑改为软删除，删除动作改为 status = 'DELETED'，该商品从普通列表中消失
- [ ] 后端 API 能返回 onShelf/grayscale/status 字段，前端能应用渲染逻辑
- [ ] 关键业务变更具原子性（单条更新原子性），并记录审计字段

## QA / Test Scenarios (Draft)
- 场景1：图片缺失，确保图片区域显示默认占位
- 场景2：商品名更新时，卡片标题随数据变动更新
- 场景3：点击上架/下架开关，调用 PATCH 更新，列表即时反映状态
- 场景4：未上架商品应用全卡片灰度，且卡片右上角出现“已下架”标签，且在列表中排序靠后
- 场景5：软删除：执行删除后，商品不再出现在普通列表但数据仍保留，且不可逆的误删通过状态控制
- 场景6：并发修改：两并发 PATCH 应对同一商品时的乐观锁/版本控制行为
- 场景7：UI 无障碍性验证：对“已下架”标签的可读性与对比度测试
- 场景8：端到端：从点击上架到列表刷新，数据一致性测试

## Draft Deliverables
- Draft: product-listing-ui-backend-plan.md
- Draft: (后续衔接) .sisyphus/plans/product-listing-ui-backend-plan.md

*** 结束 Draft 备注 ***
