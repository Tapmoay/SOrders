# SOrders 服务器生产环境部署 + 并发压测报告

> **测试日期**：2026-09-04
> **测试目标**：将 p 分支后端部署到阿里云 ECS（MySQL 生产环境），验证 110/300 并发容量
> **部署位置**：阿里云 ECS `8.145.40.22`（内网 172.26.6.109）/ `iZ0jlimnshftl47074z0hbZ` / Alibaba Cloud Linux 3 / 2C 1.8G / MySQL 5.7 + Redis + nginx

---

## 1. 部署完成清单

| 项目 | 状态 |
|---|---|
| 后端代码（p 分支最新 27 提交） | ✅ 已部署 `/opt/SOrders/backend` |
| 数据库 | ✅ MySQL `sorders` 库（22 张表，accounting V2 全量） |
| systemd 服务 | ✅ `sorders-api.service`（uvicorn 8000，**2 workers**） |
| nginx | ✅ sorders.top HTTPS 反代 `/api/` `/socket.io/` |
| Redis | ✅ 6379 运行中 |
| Web 前端 | ✅ 已下线（用户要求删除，/var/www/sorders + frontend 源码已清，备份在 /root/backup-web-old/） |

## 2. 部署修复的问题（上线前全部处理）

| # | 问题 | 修复 |
|---|---|---|
| 1 | **schema_bootstrap MySQL 兼容**：TEXT 列不能 DEFAULT（image_urls/tier_prices/damage_note → 1101） | 按方言分支（SQLite 带 DEFAULT / MySQL 不带） |
| 2 | **CREATE INDEX IF NOT EXISTS** MySQL 不支持（1064） | try/except DBAPIError 包裹 |
| 3 | **except OperationalError 漏捕**：MySQL 重复列/语法错映射 ProgrammingError | 全文件改为 `except DBAPIError`（共同父类） |
| 4 | **旧库 schema 漂移 9 列缺失**：orders.payment_method/paid/arrears_unit_*、products.cost_price/stock、shipper_addresses.origin_* | 手动 ALTER 补齐 |
| 5 | **MySQL 连接池默认 5+10 太小** | database.py: pool_size=64 / max_overflow=32 / pool_timeout=30 |
| 6 | **MySQL max_connections=151 打满**（300 并发 1040 Too many connections） | 调至 400 |
| 7 | **订单号 6 位随机数碰撞**（300 并发 1062 Duplicate entry） | new_order_no 改为 10 位随机（碰撞率 10⁻⁶→10⁻¹⁰） |

## 3. 压测结果（服务器本机，预登录真实负载模型）

### 3.1 20 并发（30s）
| 指标 | 值 |
|---|---|
| 成功率 | **100%**（315/315） |
| RPS | 9.6 |
| p50 / p95 / p99 | 6ms / 86ms / 383ms |

### 3.2 50 并发（30s）
| 指标 | 值 |
|---|---|
| 成功率 | **99.85%**（680/681，1 个偶发 500） |
| RPS | 20.9 |
| p50 / p95 / p99 | 7ms / 373ms / 4092ms |

### 3.3 110 并发（45s）—— 🏆 达标（150 人规模）
| 指标 | 值 |
|---|---|
| 成功率 | **100%**（2830/2830） |
| RPS | **59.2** |
| p50 / p95 / p99 | **9ms / 129ms / 499ms** |

> 🔑 **110 并发（对应 150 人使用规模）：0 失败，RPS 59，p95 仅 129ms——非常轻松。**

### 3.4 300 并发（90s）—— ⚠️ 饱和但可恢复
| 轮次 | 成功率 | RPS | p50 | p95 | 主要错误 |
|---|---|---|---|---|---|
| 第 1 轮（修复前） | 99.44%（11325/11389） | 121.7 | 539ms | 1410ms | 订单号碰撞 1062（已修复） |
| 第 2 轮（修复订单号） | 98.15%（9351/9527） | 99.6 | 1000ms | 2292ms | Too many connections（已调 400） |
| 第 3 轮（最终） | 96.05%（7002/7290） | 73.4 | 1182ms | 3338ms | **QueuePool 超时（压测端 -1），无 HTTP 500** |

> ⚠️ **第 3 轮关键事实**：服务器 journalctl 中 **500 Internal Server Error 计数 = 0**——后端不产生错误响应，失败全部是**压测端等待连接超时（-1）**。即：**300 并发时后端进入高延迟饱和，请求排队（30s 超时），但不崩溃、不产生错误数据、可恢复（压测后 health 正常、负载回落）**。

## 4. 结论与建议

### ✅ 结论
1. **150 人规模（110 并发）：生产环境毫无压力**——100% 成功，RPS 59，p95 129ms。**可以放心上线。**
2. **300 人规模（300 并发）：可用但有性能饱和**——后端无 500 无崩溃，但延迟升高（p95 3.3s），超出当前服务器配置（2C/1.8G + 2 worker）的舒适区。
3. **对比本地 SQLite 环境**：生产 MySQL 相比本地 SQLite 提升巨大（110 并发从 48.8% 失败 → 0% 失败），**架构选型 MySQL 正确**。

### ⚠️ 如需支撑 300+ 并发，建议（按优先级）
1. **升级服务器配置**：4C/4G（当前 2C/1.8G 是主要瓶颈——2 worker × 线程池是天花板）
2. **增 worker**：4C 时 `--workers 4`；连接池相应调小（每 worker 64 太多，改 32）
3. **加连接池最大等待**：`pool_timeout` 已 30s，可配合减少 max_overflow 降低争抢
4. **订单号冲突**：已修复为 10 位，**上线前请确认 Android 端显示单号长度兼容**（SO+8日期+10随机=20 字符，原 15 字符；核对 UI 显示宽度）
5. **压测脚本**：300 线程+python urllib 的连接管理较弱，真实吞吐建议用 locust/vegeta 复测

## 5. 环境限制与迁移风险（更新版）

### 本次测试条件
- 服务器本机（127.0.0.1:8000）压测，**无真实网络延迟**
- 单机 2C/1.8G（内存紧张，Swap 372MB 已用）
- MySQL 5.7（生产同款）
- 测试账号 110 个（60 货主 + 50 司机）+ 21 商品（含压测产生订单 4000+）

### 迁移/真机环境注意事项
| 风险 | 说明 |
|---|---|
| **真机网络延迟** | 本机压测未测公网链路；真机经 nginx+sorders.top 实测可能有 100-300ms 额外延迟 |
| **Android 单号长度** | 订单号从 15→20 字符，确认 App 内 UI 显示无截断 |
| **内存** | 1.8G 内存 + 2 worker + MySQL 已接近上限；并发高时注意 OOM |
| **备份** | `/root/backup-web-old/` 有 web 前端 + frontend 源码 + 数据库备份 | 

> 报告完 — 建议将数据库备份与部署脚本固化为 `/opt/SOrders/deploy/` 下的发布流程。