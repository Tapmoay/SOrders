# 真实世界基线（BASELINE）

> **本文件由 `_tools/baseline/_capture_baseline.py` 生成，不要手改**（报告 §13：会变化的数字一律不手写）。
> 重新采：`python _tools/baseline/_capture_baseline.py --tests --prod --out docs/BASELINE.md`

> 本次采集时间：2026-09-24T21:51:33　｜　快照：`_tools/baseline/before/2026-09-24/baseline.json`

> 说明：这一页回答的是「现在到底是什么样」，不回答「应该改成什么样」——后者在 [RECTIFICATION_PLAN.md](RECTIFICATION_PLAN.md)。


## 1. 与报告成文时的对照（漂移一眼可见）

| 项 | 报告成文时 | 本次实测 | 差额 | 来源 |
|---|---:|---:|---:|---|
| 端点数 | 227 | 227 | 0 | L57 / L940 |
| 数据库表数（模型） | — | 45 | — | — |
| service 文件数 | 41 | 41 | 0 | L57 |
| api/v1 行数 | 13724 | 13966 | +242 | L395 |
| services 行数 | 9837 | 9837 | 0 | L396 |
| orders.py 行数 | 2055 | 30 | -2025 | L402 |
| schema_bootstrap.py 行数 | 1697 | 1730 | +33 | L142 / L234 |
| 静态检查数 | 92 | 94 | +2 | L332 / L1454 |
| 反向验证数 | 108 | 109 | +1 | L332 / L1454 |
| 后端用例数 | 820 | _未采集_ | — | L334 / L983 |
| 安卓用例数 | 1126 | 1126 | 0 | L335 / L985（源码 @Test 注解口径） |
| docs 文件数 | 502 | 505 | +3 | L915 |
| _tools Python 文件数 | 325 | 335 | +10 | L1454 |

> 报告的数字**不是错误**，它记录的是报告成文那一刻的快照；这一列留着的目的是让「文档写着 92 个检查、实际 92 个」这种话**有机器可核的依据**。


## 2. 本地基线

| 项 | 值 |
|---|---|
| 分支 | p |
| 提交 | c2a099556af584e49b111d776075eaea59954163 |
| 最后提交时间 | 2026-09-24T21:50:35+08:00 |
| 领先上游 | 109 |
| 落后上游 | 0 |
| 版本号 VERSION | 0.2.4 |
| 版本号 frontend | 0.2.4 |
| 版本号 android | 0.2.4（构建时读 VERSION 文件） |
| 版本号 backend(main.py) | 0.2.4（= 仓库根 VERSION，config.py 运行时读） |
| 端点数（含写） | 227 |
| 其中写端点 | 151 |
| 模型声明表数 | 45 |
| api/v1 总行数 | 13966 |
| services 总行数 | 9837 |
| 静态检查数 | 94 |
| 反向验证脚本数 | 109 |
| 后端用例数 | _未采集_ |
| 安卓用例数（源码 @Test 注解） | 1126 |
| 安卓最近一次跑到的用例数 | 308 |
| 安卓用例失败数（最近一次） | 0 |
| 安卓主源码 .kt 数 | 253 |

### 最大的安卓源文件（报告 §11 点名的「大文件」）

| 行数 | 文件 |
|---:|---|
| 5796 | `android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt` |
| 3040 | `android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt` |
| 2548 | `android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt` |
| 2257 | `android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatScreen.kt` |
| 2065 | `android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt` |
| 1804 | `android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt` |
| 1605 | `android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt` |
| 1532 | `android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteBasicData.kt` |

### 最大的后端文件

| 行数 | 文件 |
|---:|---|
| 1730 | `backend/app/core/schema_bootstrap.py` |
| 853 | `backend/app/api/v1/ledger.py` |
| 836 | `backend/app/services/accounting_service.py` |
| 822 | `backend/app/api/v1/reports.py` |
| 747 | `backend/app/services/place_service.py` |
| 709 | `backend/app/services/order_flow.py` |
| 633 | `backend/app/api/v1/shipper_ledger.py` |
| 630 | `backend/app/services/driver_pay.py` |

## 3. 生产基线（只读采集）

| 项 | 值 |
|---|---|
| host | `iZ0jlimnshftl47074z0hbZ` |
| date | `2026-09-24T21:51:35+08:00` |
| os | `Alibaba Cloud Linux 3.2104 U13 (OpenAnolis Edition)` |
| kernel | `5.10.134-19.3.al8.x86_64` |
| cpu | `2` |
| mem_mb | `1870` |
| uptime_days | `91` |
| service_state | `active` |
| service_since | `Wed 2026-09-23 08:58:54 CST` |
| service_restarts | `0` |
| service_hash | `2f5734f53645cc18` |
| api_health | `200` |
| api_health_body | `{"status":"ok","version":"0.2.0","redis":"ok"}` |
| api_paths | `160` |
| mysql_version | `mysql  Ver 8.0.44 for Linux on x86_64 (Source distribution)` |
| db_tables | `44` |
| db_size_mb | `11.7` |
| db_orders | `2402` |
| db_ledgers | `4648` |
| db_users | `60` |
| db_products | `37` |
| redis_version | `6.2.20` |
| redis_maxmemory | `0` |
| redis_requirepass_len | `1` |
| nginx_version | `nginx/1.20.1` |
| nginx_config_hash | `2c7355968c4d581249f88177ba2cef38` |
| cert_sorders.top_end | `Jul 11 06:06:48 2026 GMT` |
| cert_sorders.top_days_left | `-75` |
| disk_total | `40G` |
| disk_used | `11G` |
| disk_avail | `27G` |
| disk_pct | `29%` |
| uploads_size | `187M` |
| uploads_files | `2115` |
| backup_root_size | `204M` |
| backup_db_count | `3` |
| repo_commit | `648fbf8134c4ffcae86e698255fdf2427ded71c2` |
| repo_branch | `new` |
| repo_dirty | `8` |
| repo_commit_date | `2026-09-23T09:02:55+08:00` |
| crontab | `0 4,10,16,22 * * * "/root/.acme.sh"/acme.sh --cron --home "/root/.acme.sh" > /dev/null;` |

## 4. 机器判定的风险 / 漂移

| 类别 | 是什么 | 细节 |
|---|---|---|
| 版本漂移 | 版本号多处不一致 | VERSION=0.2.4 ｜ frontend/package.json=0.2.4 ｜ android versionName=0.2.4（构建时读 VERSION 文件） ｜ backend main.py=0.2.4（= 仓库根 VERSION，config.py 运行时读） ｜ 生产 /health=0.2.0 |
| 结构漂移 | 模型声明的表与生产库的表不一致 | 只在模型里：['unit_conversions'] ｜ 只在生产库里：[] |
| 证书 | 域名证书剩余天数 < 30（或已过期） | days_left=-75（end=Jul 11 06:06:48 2026 GMT） |
| 代码漂移 | 生产在跑的代码与本地工作区不是同一份 | 生产 openapi paths=160，本地端点=227；生产 commit=648fbf81，本地 commit=c2a09955 |
| 工作区 | 工作区有未提交改动（结构性改造前必须先确认归属） | M _tools/baseline/_capture_baseline.py ； M _tools/baseline/before/2026-09-24/baseline.json ； M _tools/qa/_reverse_verify_cost_basis.py ； M _tools/qa/_reverse_verify_report_guards.py ； M android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt ； M android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenterViewModel.kt ； M android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportFinance.kt ； M android/app/src/test/java/com/tapmoay/sorders/ui/dispatcher/ReportFinanceTest.kt ； M backend/app/api/v1/inventory.py ； M backend/app/config.py |
| 口径 | 这次没采后端用例数（没加 --tests） | 后端用例数记 None，不要拿 None 当 0 |

