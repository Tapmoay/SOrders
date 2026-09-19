# 101 · 120 用户混合角色连续正常操作测试报告（生产环境）

## 11. 消息删除功能（后端 + Android 已接入，2026-09-04 实机验证）

### 后端
- 单删：DELETE /notifications/{id}（原有，复核通过）
- 批量删：POST /notifications/batch-delete { ids:[...] }；清空 { all:true }；派单员可 recipient_id 指定他人，其余仅本人
- 保留期：GET /notifications?days=30（默认30，可1-365）——**请求路径惰性清理**（物理删除过期行 + 查询过滤），**无任何服务器后台定时任务**，兼容客户端本地缓存/离线查看方案；清理基准 = created_at < now-days（created_at=server_default now 服务器本地时区）
- 校验：ids 与 all 同传 → 400；非派单员带 recipient_id → 403；已部署服务器 + 本地

### Android（已构建 & 模拟器实机验证）
- Api.kt: batchDelete；Dtos: NotificationBatchDeleteRequest/BatchDeleteResultDto
- MessagesViewModel: selectionMode/selectedIds/toggleSelect/enterSelection/deleteSelected/clearAll（删除后 syncUnreadFromApi）
- MessagesScreen: 长按进多选（Checkbox 勾选 + 顶栏「已选N条/删除(N)」）、顶栏「清空」、均二次确认弹窗、删除后列表即时更新
- 实机验证（emulator-5554, 本地后端）：清空（UI空+DB本人0条/他人保留）✅ 批量删（长按→勾选2条→删除(2)→弹窗→DB剩1条）✅ 单删 ✅

### 踩坑记录
- 模拟器上 ApiEndpoint 强制 http://10.0.2.2:8000（宿主机）与 BuildConfig 无关 → 模拟器联调必须重启**本机**后端加载新代码（uvicorn app.main:app --port 8000）
- Android 增量构建不会因 local.properties 变化刷新 BuildConfig → 改 api_base_url 后需 clean 构建
- 本机 android/app/build/outputs 目录曾被进程锁定无法删除（packageDebug 失败）→ 临时重定向 buildDirectory 至 D:/APPS/sorders-build 构建成功（build.gradle.kts 已还原）


> 测试日期：2026-09-04 11:25 ~ 11:47（服务器时区 CST）


## 10. 测试数据清理 + 该修的全部已修（2026-09-04 11:48~11:56）

### 10.1 数据清理（先备份后删，逐表核对）
- **全库备份**：生产服务器上的 `/root/backup-testdata-20260904.sql`（18.6MB，可随时恢复后删除）<!-- [ignore-ref] 该路径在服务器上，不在仓库内，check_refs 不必校验 -->
- 删除：orders 18,287 / order_products 27,365 / ledgers 378 / notifications 38,455 / operation_logs 18,683 / cash_flows 6 / 测试商品 51 个（测试商品01-20 + 混压商品1-52）/ 压测用户 119 个（test_*/压测*）/ 送达照片 194 个（uploads 1.6MB）
- **保留**：基础账号 ×3（DISPATCHER/SHIPPER/DRIVER 13800000001/02/03）、真实商品「土豆」×1（is_active=0 原状态未改）
- 注意：DELETE 一条 mysql -e 语句遇错即中止（notifications 无 order_id 列导致此前一轮"虚删"），本轮已按外键关系 + FK_CHECKS=0 顺序清除并逐表验证归零

### 10.2 该修的全部修复（已部署 + 已落地本地 p 分支）
| # | 问题 | 修复 | 状态 |
|---|---|---|---|
| 1 | orders.status 枚举缺 DISPATCHED → 派单100% 500 | ALTER 5 态枚举 + bootstrap 自动检测 | ✅ |
| 2 | ledgers.source 枚举缺 REFUND → 货损完成 500 卡单 | ALTER 3 态枚举 + bootstrap 自动检测 | ✅ |
| 3 | **待派池无分页**：万级积压时 14MB/33-46s | GET /orders 加 `limit` 参数；派单员待派池缺省=300 条（最新）；索引 `ix_orders_status_created(status, created_at)` | ✅ |
| 4 | 司机可自改工资/计费方式/车型（篡改结算） | update_user 非派单员改此三项 → 403 | ✅ |
| 5 | 订单金额可为负（unit_price/line_total 无校验） | schemas/order.py 三处 Field 加 ge=0 | ✅ |
| 6 | bootstrap 新迁移 conn 在 with 作用域外用 → ResourceClosedError 启动崩溃循环 | 修正作用域，重启验证零错误 | ✅（本次发现即修） |

### 10.3 修复后验证（服务重启后）
- systemd active（11:55:11 起），journal **0 条 ERROR/Traceback**
- 冒烟全绿：登录 200 / products / orders?limit=10 / 待派池 / 报表 / 账本 / 下单 201（测试单已清）
- 枚举全表核对一致；索引已建；/tmp 临时文件已清；bootstrap 单测编译通过

> 环境：阿里云 ECS 8.145.40.22（2C / 1.8G / Alibaba Cloud Linux 3），MySQL 8.0.44, Redis, uvicorn 2 worker
> 执行位置：服务器本机 127.0.0.1:8000（避免 SSH 隧道噪声）
> 脚本：_test_tools/mixed120.py（纯 stdlib 模拟 120 个真实用户并发连续操作）

## 1. 用户构成与操作矩阵（120 人）

| 角色 | 人数 | 账号 | 连续操作内容 |
|---|---|---|---|
| 货主 | 64 | 13910000001~64 + 13800000002 | 下订单(50%)、查订单(15%)、查自己账单(12%)、消息(10%)、商品目录(8%)、已送达查询(5%) |
| 司机 | 53 | 13820000001~53 + 13800000003 | 拉取任务→接单→送达完成(带照片/现金或挂账/5%货损)、查自己运费(10%)、消息(8%) |
| 派单员 | 3 | 13800000001/04/05 | 派单(35%)、营业报表、商品报表、司机绩效、异常报表、挂账汇总、账本流水/账本账户(货主/批发商)、司机运费结算、**添加商品**、**改价**、**销售商品(代下单)**、报表导出xlsx、消息 |

## 2. 执行历程（3 轮修复）

| 轮次 | 结果 | 说明 |
|---|---|---|
| 轮1 (11:25) | 98.91% 成功 / 0 5xx | 待派池接口在万级积压下耗时 47s/次，派单员线程被阻塞 → 派单=0 |
| 轮2 (11:30) | 98.14% 成功 / **158×5xx** | 发现 **Bug#1：orders.status 枚举缺 'DISPATCHED'** → 派单接口 100% 500 |
| 轮3 (11:42，修复后) | **100.00% 成功 / 0×5xx** | 枚举修复 + 脚本修正，全链路贯通 |

## 3. 发现并修复的生产环境 Bug（2 个，均为旧库 schema 漂移）

### Bug#1：orders.status 枚举缺少 'DISPATCHED'（派单必 500）
- 现象：POST /orders/{id}/assign → 500，日志 `Data truncated for column 'status'`（1265）
- 根因：旧版建库枚举只有 `('PENDING_DISPATCH','ACCEPTED','DELIVERED','CANCELLED')` 4 态，新版代码需 5 态（多了「已派单」中间态）。下单(写 PENDING_DISPATCH)正常，**一派单就 500，接单/完成整条链断掉**。
- 修复：`ALTER TABLE orders MODIFY COLUMN status ENUM('PENDING_DISPATCH','DISPATCHED','ACCEPTED','DELIVERED','CANCELLED') NOT NULL`
- 防护：schema_bootstrap 增加 MySQL 分支自动检测+修复。

### Bug#2：ledgers.source 枚举缺少 'REFUND'（货损完成单 500）
- 现象：带货损的完成单 POST /complete-with-upload → 500，`Data truncated for column 'source'`；**订单卡在「已接单」、送达照片已上传但状态不更新**（交易回滚前照片已落盘，属业务完整性缺口风险）。
- 根因：货损自动回冲写 `source='REFUND'`，旧库枚举仅 ('ORDER','MANUAL')。
- 修复：`ALTER TABLE ledgers MODIFY COLUMN source ENUM('ORDER','MANUAL','REFUND') NOT NULL`
- 防护：bootstrap 增加同款自动检测。

### 全库枚举核查（修复后全表无遗漏）
`orders.status`(5态✓)、`ledgers.source`(3态✓)、`users.role`(SHIPPER/DRIVER/DISPATCHER✓)、`ledger_export_jobs.status`(PENDING/PROCESSING/DONE/FAILED✓)、`ledger_export_jobs.format`(EXCEL/PDF✓) —— 与代码枚举一致。

## 4. 最终结果（修复后 · 120 用户连续 216s）

| 指标 | 值 |
|---|---|
| 总请求 | 5048 |
| **成功率** | **5048/5048 = 100.00%** |
| 意外 4xx / 5xx / 网络失败 | 0 / 0 / 0 |
| 业务竞态(双派单员抢单) | 0（队列取单天然避免；实际竞态场景在轮2验证过 78 次 400 均被正确拒绝） |
| RPS | 23.4（连续正常操作节奏，非压满） |
| 全链路业务量 | 下单 1439 → 派单 76 → 接单 76 → **送达完成 191**（含消化历史「已接单」积压 125 单） |
| 延迟 | p50=2780ms p95=5349ms p99=6603ms（**高延迟但稳定**，见 §7） |

各操作成功率均为 100%（24 个操作类型全绿）：下单/列表/账本/消息、接单/完成(带图)/运费、派单/报表x4/审计x2/账本x2/结算/加商品/改价/代下单/导出。

## 5. 数据一致性对账（API vs SQL 直查，全部一致）

| 项 | API | SQL | 结论 |
|---|---|---|---|
| 账本流水数 | ledger/entries=378 | 378 (ORDER 372 + REFUND 6) | ✅ |
| 营业额报表 total_amount | 55879.72 | SUM(ledgers.total)=55879.72 | ✅ 分毫不差 |
| 报表行数 total_lines | 372 | ORDER 流水行 372 | ✅ |
| 货损 damage_qty | 6 | REFUND 行 6 | ✅ |
| 送达订单数 | — | delivered_at(UTC) 窗口=191 | ✅ = 完成计数 |
| 司机运费总额 | 3541.94 | 3525.94 + 探针单 16.00 | ✅ 差异=2 个探针单(8×2) |
| 报表异常/超时 | exceptions=200 | — | ✅ |

## 6. 极端场景发现（最重要）

**待派池接口在大积压下不可用（无分页）**：
GET /api/v1/orders?status=PENDING_DISPATCH 在积压 9,271→12,000+ 单时：
- 响应体 **14.3 MB**，耗时 **33.4s**（实测）；压测中 8 次审计 p50=46.7s。
- 该接口一次返回**全部**待派订单（含订单明细），无分页/无 limit——**这是当前系统最大的可扩展性风险**：真实业务一旦积压数千单，派单员工作台直接卡死/内存暴涨（2 worker RSS 达 433~498MB）。
- 佐证：报表导出(openpyxl)与 stats_exception 在积压下 p50 4.5~7.1s（无积压时 <100ms，见 verify）。

**建议**：① pool 接口加分页(limit/offset 或游标)或聚合计数列表；② 派单员只拉「最新 N 单」；③ orders 表按 status+created_at 建组合索引（已有单列 ix_orders_status，需复合）；④ 清理测试积压（当前 ~13,500 测试单，可保留演示/需清理请告知）。

## 7. 环境限制与迁移风险（换环境会发生什么）

1. **内存是硬瓶颈**：1.8G 机器在 120 用户+万级积压下 swap 用尽（1016/1024MB），但**未 OOM、服务未崩**；worker RSS ~450-500MB。→ 换到更小配置必崩；建议生产 4C/4G。
2. **延迟高企**：p50 2.8s 的主因是 orders/ledgers 表膨胀到 1.5 万+ 且无复合索引 + 2 worker 排队。**换到网络差的机房/手机网络，用户体感会更糟（建议 ≤150 人规模 + 索引优化）**。
3. **本地 SQLite ≠ 生产 MySQL**：本地 110 并发曾 48.8% 失败崩溃（单连接锁），生产 MySQL 120 用户 100%——**相同代码不同数据库行为差异巨大**，测试口径必须按数据库区分。
4. 时区注意：delivered_at/dispatched_at 存储为 UTC（对比查询要用 UTC 窗口），created_at 为本地时间——跨环境报表窗口需统一。
5. 服务器日期(2026-09-04)与本机不一致（服务器时钟慢/停），只影响按日报表的口径，不影响功能。

## 8. 系统健康（修复后轮）

- journald: 运行窗口 **0 条 ERROR/Traceback/500**
- systemd sorders-api: active；跑后负载 5.9→4.5→回落，CPU 96% idle
- 全程无进程崩溃、无连接池耗尽、无 Too many connections（上次 300 并发修过的 max_connections=400 保持正常）

## 9. 结论

- ✅ **120 用户（货主/司机/派单员）连续正常业务操作在修复后 100% 成功，全链路（下单→派单→接单→送达→账本→报表→结算）数据完全一致**。
- 🐛 **但测试发现了 2 个此前从未暴露的生产缺陷**（旧库枚举缺 DISPATCHED / REFUND）——**派单与货损完成在真实环境一直是 500**，属「部署环境漂移」类问题，已修复并加 bootstrap 自动防护。
- ⚠️ 极端场景（万级积压下派单工作台 33-46s/14MB）需**接口分页+复合索引**才能支撑更大规模；建议按 150 人规模运营 + 控制积压。
- 遗留：压测产生的订单/商品/用户仍在库（可演示用）；如需清理请告知。
