# SOrders 多用户极端场景安全测试报告

> **测试日期**：2026-09-04
> **测试方案**：全面测试（安全性 + 极端场景 + 并发容量 + 端到端回归）
> **测试组织**：多 agent 协同（3 个子代理调研 + 主代理实测）
> **版本基线**：p 分支 v0.2.0（commit `fffd66c` 沿线）

---

## 0. 测试环境（重要——所有结论的前提）

| 项目 | 实际值 | 说明 |
|---|---|---|
| **主测试机** | Windows 本机（D:\AProjects\ASDH\orders） | 单机环境，无真机 |
| **后端** | FastAPI + uvicorn **单进程** :8000 | 生产部署为 docker-compose（MySQL+Redis+nginx 多进程） |
| **数据库** | **SQLite**（`backend/sorders.db`） | 生产为 MySQL 8（docker-compose） |
| **Android 模拟器** | 3 台（5554 派单员 / 5556 货主 / 5558 司机） | 实际用户为真机+真实网络 |
| **Redis** | 不可用（redis: unavailable） | 生产可用 |
| **网络** | 本机回环 127.0.0.1，模拟器走 10.0.2.2 | 生产为公网/局域网 |
| **并发压测工具** | aiohttp asyncio 自研引擎（110/150/300 并发） | locust 未安装，用同等能力的异步引擎替代 |
| **测试账号** | 1 派单员 + 110 测试用户（60 货主 + 50 司机）+ 20 测试商品 | 全部通过 API/DB 批量创建 |

> 🔴 **本报告标明的"容量结论"全部是「本机 SQLite + 单进程 uvicorn」环境的实测值，不能直接外推到生产 MySQL 环境。**
> 迁移到生产环境后会出现的差异点见 §6。

---

## 1. 总体结论（TL;DR）

| 维度 | 结论 | 评级 |
|---|---|---|
| **核心业务功能** | 下单→派单→接单→完成→账本→报表 端到端 **10/10 PASS** | ✅ 优秀 |
| **对象级权限隔离** | 货主看不到他人订单、司机不能完成他人订单、越权全部 403 | ✅ 优秀 |
| **认证体系** | 无 token 401、伪造 token 401、bcrypt 哈希、JWT 标准 | ✅ 良好 |
| **SQL 注入防护** | 全 ORM 参数化，枚举注入被 422 拦截 | ✅ 优秀 |
| **上传安全** | MIME 白名单 + uuid 文件名 + 10MB 限制 | ✅ 良好 |
| **SMS 防滥用** | 60s 频控 + 5min TTL + 一次性消费 | ✅ 良好 |
| **当前开发环境并发** | **110 并发：48.8% 失败，进程崩溃** | 🔴 **严重** |
| **SQLite 写并发上限** | 纯写 ~100 并发（p50=2.5s），150 并发 99.8% 失败 | 🔴 严重 |
| **配置修复后 110 并发** | **0.08% 失败（2584/2586），RPS 41.7，p95=119ms** | ✅ 达标 |
| **300 并发（升级目标）** | 失败（连接池耗尽，真实混合负载 150 已临界） | ⚠️ 未达标（本环境） |
| **数据一致性** | 完整性 OK、无重复订单号、并发完成幂等 1 条 | ✅ 良好 |

**一句话**：**业务功能与安全隔离做得不错，但「当前开发环境（SQLite 单连接配置）根本扛不住 20+ 并发写」，110 并发必崩；修复数据库池配置后 110 并发轻松通过，但 300 并发仍受 SQLite 写锁物理上限制约（需 MySQL 才能达标）。**

---

## 2. 高严重度问题（必须修复）

### 🔴 S1. 创建用户接口 500（用户管理核心功能不可用）
- **现象**：`POST /api/v1/users` 全部返回 **500 Internal Server Error**
- **根因**：`backend/app/api/v1/users.py:75` `create_user` 函数参数名是 `_`，函数体内引用 `current` → `NameError`
- **更严重**：**数据已 commit 入库但接口 500**。客户端显示失败，重试报"该手机号已存在"——**半成功不一致**。实测 110 个测试用户已写入数据库且可登录，但客户端感知为失败。
- **影响**：管理员无法创建任何新用户（司机/货主）。**上线前必须修复**。
- **验证**：`_test_tools/repro500.py`、`tc_repro.py`

### 🔴 S2. 司机可自改工资/计费方式/车辆类型（越权自提权）
- **现象**：司机 `PATCH /api/v1/users/{self}` 传 `salary`/`billing_mode`/`vehicle_type` 均返回 200 且**已落库**
- **根因**：`backend/app/api/v1/users.py:118-119` 写 `salary` 时**未校验操作者是否为派单员**（仅校验了目标用户是司机）；`billing_mode`/`vehicle_type` 同理（代码注释说"仅司机角色有意义"但没限制操作者）
- **实测**：司机 13800000003 将自己 `full_name` 改为"被篡改的司机"（已落库）、`billing_mode` PIECE→SALARY（已落库）——**影响运费结算方式**
- **影响**：SALARY 司机月账单按 `salary` 发放（`driver_bills.py:109`），司机可自抬工资；计件司机会私自改计费方式导致运费结算错误
- **验证**：`_test_tools/sec_wave5.py`（已恢复数据）

### 🔴 S3. 负数金额可写入（业务污染）
- **现象**：下单 `unit_price=-1.00`、`line_total=-5.00`、单价 `999999999999.99` 均 **201 成功入库**
- **根因**：`backend/app/schemas/order.py:15-16` `unit_price/line_total` **无 `ge=0` 约束**（对比 `product.py` 有）
- **实测**：数据库已有 2 条负金额订单行（id 30: -1/-1，id 31: 10/-5）
- **影响**：营业额/账本/报表被污染，**可产生负收入数据**
- **验证**：`_test_tools/sec_wave3b.py`

### 🟠 S4. JWT secret 为公开默认值（生产必须覆盖）
- **现象**：`backend/app/config.py:22` `jwt_secret_key` 默认 `change-me-in-production-use-openssl-rand-hex-32`；`docker-compose.yml:41` 也含该值
- **风险**：生产未设置 `JWT_SECRET_KEY` 时任何人可离线下离线伪造任意身份 token
- **说明**：本次实测伪造 token 均 401（因为本机 .env 未覆盖 secret，用的还是默认值——等于任何人可伪造）。**严重依赖生产 env 正确配置**
- **验证**：`_test_tools/sec_wave1.py` FORGED TOKEN 401（当前默认 secret 时伪造签名失败，但知道默认 secret 的第三方可成功）

### 🟠 S5. SMS 验证码明文回显（本地 .env）— ✅ **2026-09-18 已彻底消除**
- **现象**：`backend/.env:3 sms_reveal_code=true`，接口响应带 `code` 明文
- **风险**：此 .env 若被部署到非开发环境，任何匿名用户可调用 `/auth/sms/send` 直接获取验证码 → 注册任意账号
- **实测**：`_test_tools/sec_wave1.py` SMS SEND 200 回应 `code:"220298"`（实测时首调为回显；60s 频控后 400）
- **已有正向缓解**：60s/手机号频控 + 5min TTL + 一次性消费（`sms_code.py` [ignore-ref]——**该文件与整套验证码功能已在后续版本整体删除**）✅
- **最终处置（2026-09-18）**：用户要求「注册接口关掉，不需要用了」→ `POST /auth/register` 与 `POST /auth/sms/send`
  **整体删除**（连同 `sms_code.py` [ignore-ref]、`RegisterRequest`/`SendSmsRequest`、`sms_reveal_code` 配置与本地 `.env` 里那一行）。
  现在这一条不再依赖"记得把开关关掉"：**路径不存在**（实测两条都 404，账号数不变）。
  回归判据：`_tools/fuzz/_fuzz_authz.py::registration_closed` + `tests/test_auth.py::test_self_registration_is_closed`
  + 红线 §28（注入"把注册端点加回来"必须报红）。

---

## 3. 中低严重度问题

| ID | 问题 | 位置 | 级别 |
|---|---|---|---|
| M1 | **CORS `allow_origins=["*"]` + `allow_credentials=True`** 组合 | `main.py:64-66` | 中 |
| M2 | **nginx 反代示例无 TLS**（HTTP 明文传输 token/密码） | `deploy/` | 中 |
| M3 | **订单创建无幂等键**（双击/重试产生重复单；实测客户端有防抖，API 直接调无） | `orders.py:318` | 中 |
| M4 | **派单员"恒真"权限**（rbac.py 派单员放行所有 require_permission） | `rbac.py:112` | 中（设计取舍） |
| M5 | **上传内容不做嗅探**（MIME 正确即收，PHP 内容可伪装 png 上传） | `orders.py:83` | 低中（filename 已 uuid 化+静态目录，实际危害受限） |
| M6 | **`sync-from-delivered-orders` 接口契约不一致**（文档说无 body，实际需要 body） | `ledger.py:169` | 低 |
| M7 | **schema_bootstrap 只补列不建表**（复制库到新环境缺表风险；新建库靠 create_all，旧库迁移靠 bootstrap 补列） | `core/schema_bootstrap.py` | 低 |
| M8 | **MySQL 5.5 建表兼容**（`timezone=True`+`func.now()` 生成 `DEFAULT now()`，MySQL 5.5 不支持 1067） | `models/base.py:9` | 低（生产 MySQL 8 无此问题） |

---

## 4. 并发容量测试结果（本机 SQLite 环境）

### 4.1 原版配置 110 并发（当前开发环境现状）—— 🔴 不达标
**`stress_v2.py 110 60 baseline110 --base http://127.0.0.1:8000`**

| 指标 | 值 |
|---|---|
| 总请求 | 1479 |
| 成功 | 757（51.2%） |
| **失败** | **722（48.8%）** |
| 失败类型 | 连接重置（-1）~520、500 ~70、401 ~20、超时 999 ~5 |
| RPS | 23.9 |
| p50 / p95 | 11ms / 422ms（成功请求） |
| **进程结局** | **110 并发 60s 后进程死亡**（health 无响应） |

### 4.2 修复配置（WAL+busy_timeout=30s+QueuePool 64）110 并发—— ✅ 达标
**`stress_v2.py 110 60 fixed110 --base http://127.0.0.1:8003`**

| 指标 | 值 |
|---|---|
| 总请求 | 2586 |
| 成功 | 2584（**99.92%**） |
| 失败 | 2（0.08%，均为 assign 400——业务逻辑拒绝，非系统故障） |
| RPS | 41.7 |
| p50 / p95 / p99 | 13ms / 119ms / 747ms |

> 🔑 **决定性结论**：110 并发的瓶颈 **100% 是数据库连接配置**（StaticPool 单连接被多线程共享 → `sqlite3.OperationalError: cannot commit transaction - SQL statements in progress`），**不是业务代码**。修复池配置后 110 并发"很轻松"。

### 4.3 SQLite 写锁物理上限（量化）

| 并发写 | 成功 | p50 | p95 | 结论 |
|---|---|---|---|---|
| 50 | 249/250 (99.6%) | ~1000ms | ~2000ms | 可接受 |
| 100 | 300/300 (100%) | ~2600ms | ~3400ms | 临界（延迟高） |
| **150** | **1/450 (0.2%)** | 60ms | 60ms | **崩**（连接池耗尽 30s 超时） |

### 4.4 升级目标：300 并发—— ⚠️ 本环境不达标
- `stress_v2.py 300 90 --base 8003`：登录全部失败（login_fail 299/300）
- 根因：300 用户涌入 → 写请求在 SQLite 锁上排队 → 连接被长时间占用 → QueuePool 64+64 耗尽 30s 超时 → **连锁拖垮健康检查**
- **真实混合 150 并发（写占比 ~15%）也卡死**（8003 health 超时）

---

## 5. 端到端功能回归（10/10 PASS）

| # | 步骤 | 结果 |
|---|---|---|
| 1 | 货主下单（多商品/地址/备注） | ✅ 201 PENDING_DISPATCH |
| 2 | 派单员待派池可见 | ✅ |
| 3 | 派单（运费/计费快照） | ✅ DISPATCHED |
| 4 | 司机接单 | ✅ ACCEPTED |
| 5 | 司机完成（带图+挂账） | ✅ DELIVERED |
| 6 | 账本自动入账（幂等 1 条） | ✅ total=70.50 |
| 7 | 司机运费账单自动生成 | ✅ 8.00 |
| 8 | 报表营业额可查 | ✅ |
| 9 | 消息中心通知（订单状态） | ✅ |
| 10 | 敏感操作审计日志 | ✅ |

**并发的`complete`幂等**：双 `complete-with-upload` → 一个 200、一个 400（状态机拦截），账本 1 条、司机账单 1 条——**无重复入账**。子代理静态分析担心的"无原子 CAS"在实测中未复现（状态检查兜底有效），但**理论上竞态窗口仍存在**，建议补 UNIQUE 约束（低优先）。

---

## 6. 测试环境限制与迁移风险分析（用户重点关注）

### 6.1 本次测试在什么条件下进行

| 因素 | 本次测试 | 真实生产 |
|---|---|---|
| 数据库 | SQLite（单文件） | MySQL 8（多连接+行锁） |
| 服务进程 | 单 uvicorn 进程 | nginx 反代 + 多个 uvicorn worker |
| 网络 | 本机回环 127.0.0.1 | 公网/局域网（延迟+丢包） |
| 客户端 | 3 台模拟器 | 真机（弱网/断网/多型号） |
| Redis | 不可用 | 可用（Socket.IO 跨进程广播） |
| 推送 | 单进程内存房间 | Redis manager 跨进程 |

### 6.2 迁移到生产 MySQL 后**会变好**的项（瓶颈解除）
1. **写并发**：MySQL 行级锁 + 多连接 → 110/300 并发下单不再受"全局写锁"制约（本报告 4.3 的物理上限**仅适用于 SQLite**）
2. **进程崩溃**：StaticPool 单连接问题消失（MySQL 分支用 pool_pre_ping+默认池）
3. **跨进程推送**：Redis manager 支持多 worker 广播（本地单进程实测未覆盖）
4. **数据量**：MySQL 索引+分页能力远强于 SQLite

### 6.3 迁移到生产后**仍然存在/可能恶化**的问题（⚠️ 需重点处置）
1. **🔴 创建用户 500（S1）**：与数据库无关，**上线必坏**（管理员开不了号）
2. **🔴 司机自改工资/计费（S2）**：与数据库无关，上线即暴露（存在真实利益驱动）
3. **🔴 负数金额（S3）**：与数据库无关，上线即污染账本
4. **🟠 JWT 默认 secret（S4）**：**只有生产正确设置 env 才安全**；漏配=全系统可伪造
5. **🟠 无分页列表**（`GET /orders`、`/ledger/entries`）：**300 用户×订单量大 → MySQL 全表扫描 → 内存/响应爆炸**（本机数据量小未暴露；子代理静态分析确认）——比 SQLite 锁**更危险**的生产隐患
6. **🟠 推送路径 async 内同步 DB**（push_events/message_center）：多 worker 下跨进程房间需确认，单 worker 时阻塞事件循环
7. **🟠 报表全表扫描**（`reports.py load_delivered` 拉全部已送达单+Python 聚合）：数据量增长 → 报表接口 OOM 风险（生产比本地更严重）
8. **🟠 SMS 验证码内存存储**：多 worker 下各进程隔离（手机号 A 在 worker1 拿码，注册请求落到 worker2 → 验证码不存在的 400）——**需要 Redis 或粘性会话**（本地单进程未暴露）
9. **🟡 Android Socket 无限重连**（无 reconnectionAttempts 上限 + 401 不处理）：弱网/长断网时耗电与事件风暴
10. **🟡 报表导出主线程**（ReportCenter VM 读全量 bytes+写盘无 IO 调度）：大报表 ANR
11. **🟡 nginx 无 TLS**：令牌/密码明文过网

### 6.4 本次测试已覆盖 vs 未覆盖

**已覆盖**：
- ✅ 三端安全隔离（货主/司机/派单员 16 组越权组合）
- ✅ 认证全链路（无 token/伪造/弱口令/过期）
- ✅ 注入（SQL/路径/上传）
- ✅ 完整业务主流程（API 级模拟器等价）
- ✅ 110 并发混合负载（原版+修复版对照）
- ✅ 写并发物理上限（50/100/150）
- ✅ 并发幂等（complete 双写）
- ✅ 服务中断恢复（kill→重启→health ok→数据无损）
- ✅ 数据一致性（integrity_check、重复单号、负金额）

**未覆盖（需在迁移后补测）**：
- ❌ **MySQL 8 真实压测**（本机只有 MySQL 5.5，DDL 不兼容）——**300 并发的最终答案只能由生产环境给出**
- ❌ 真机弱网/断网/蜂窝网络（模拟器是局域网回环）
- ❌ 多进程 Socket.IO 跨 worker 推送
- ❌ 大批量数据（5000+ 订单）下的列表/报表性能
- ❌ Android 端全 UI 回归（本次为 API 级验证；UI 层子代理已静态审查）

---

## 7. 修复优先级建议（Top 6）

| 优先级 | 问题 | 建议 |
|---|---|---|
| **P0** | S1 创建用户 500 | `users.py:75` 参数名 `_` → `current`（一行修复） |
| **P0** | S2 司机自改工资/计费 | `update_user` 中 `salary/billing_mode/vehicle_type` 写入加 `is_dispatcher` 校验 |
| **P0** | S3 负数金额 | `order.py` `unit_price/line_total` 加 `ge=0` |
| **P1** | S5 SMS 回显 | 生产 `.env` 必须 `sms_reveal_code=false`（`.env.example` 加警告） |
| **P1** | S4 JWT secret | 生产强制注入 `JWT_SECRET_KEY`（docker-compose 用 env 占位，启动校验） |
| **P1** | 数据库配置 | 本地开发启用 WAL+busy_timeout（`database.py` 加 PRAGMA）；生产确认 MySQL 池配置（`pool_size/max_overflow` 建议 20/40） |
| **P2** | 无分页 | `GET /orders`、`/ledger/entries` 补 limit/offset 分页 |
| **P2** | 报表全表扫描 | `load_delivered` 改 SQL 聚合（GROUP BY + 窗口函数） |
| **P2** | M1 CORS | 生产改用白名单 |

---

## 8. 附录

### 8.1 测试产物清单（`_test_tools/`）
- `sec_wave1.py ~ sec_wave6.py`（安全实测 6 波）
- `stress_v2.py`（混合负载压测引擎，支持 BASE/users/duration 参数）
- `warmup2.py`（逐步升温并发）
- `write_stress.py`（纯写吞吐量化）
- `login_stress.py`（并发登录测试）
- `e2e_check.py`（端到端回归 10 步）
- `idem_complete*.py`（并发幂等验证）
- `consistency*.py`（数据一致性检查）
- `repro500*.py`（S1 复现）

### 8.2 后端进程状态（测试结束时）
- 8000 原版：已重启（测试中崩溃 2 次后恢复）
- 8003 修复版：测试结束时卡死（300 并发压垮，数据无损坏）
- `sorders.db`：完整性 OK，168 订单/120 用户/28 商品（含测试数据）

### 8.3 测试数据说明
- 已创建 110 测试用户（60 货主+50 司机，手机号 1391000xxxx/1382000xxxx）+ 20 测试商品
- 测试期间产生大量 PENDING 订单（压测下单），**建议正式运行前清理测试数据或用种子库**
- 司机 13800000003 的 `full_name` 已在测试后恢复为 "Driver"，`billing_mode` 恢复 "piece"

> 报告完 — 如需对 P0 问题出一份修复补丁或清理测试数据脚本，请直接告知。
