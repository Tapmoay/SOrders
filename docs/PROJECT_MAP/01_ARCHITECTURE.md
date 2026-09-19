# 01 架构总览

## 1. 这是什么

**SOrders 派单送货管理系统**（小型物流配送）：
- 货主（SHIPPER）下订单 → 派单员（DISPATCHER）派单给司机 → 司机（DRIVER）接单、送货、收款/挂账
- 派单员同时是运营方：管理商品/司机/货主/批发商/库存/账本/挂账单位/报表

## 2. 三端与技术栈

| 端 | 路径 | 技术 | 状态 |
|---|---|---|---|
| 后端 | `backend/` | Python FastAPI + SQLAlchemy 2.0 + Pydantic v2 + python-socketio + openpyxl + fpdf2 | **主服务**（API + Socket.IO 同进程） |
| Android | `android/` | Kotlin + Jetpack Compose (Material3) + Retrofit + OkHttp + 高德地图 9.8.3 | **主客户端** |
| 旧 H5 | `frontend/` | Vue3 + TS + Pinia(?) | 已边缘化，保留兼容 |

- 数据库：本地开发 **SQLite**（`backend/sorders.db`）；生产 MySQL（docker-compose）+
- 消息：Socket.IO（`socket.io` 路径）实时推送（订单状态变更/账本刷新/消息中心）
- Redis：可选（`redis_client.py` `redis_ok()`；本地无 Redis 也降级可用）

## 3. 目录全景

```
orders/
├── backend/                     # FastAPI 服务
│   ├── app/
│   │   ├── main.py              # 入口：create_fastapi_app + socketio.ASGIApp
│   │   ├── config.py            # Settings（env 可覆盖）：api_v1_prefix=/api/v1
│   │   ├── database.py          # engine/SessionLocal；导入即 bootstrap_schema
│   │   ├── deps.py              # CurrentUser / require_permission 等依赖
│   │   ├── redis_client.py      # Redis 健康检查（可选）
│   │   ├── core/                # rbac(权限) / security(jwt/hash) / socket_io / schema_bootstrap（⚠️ `ws_hub.py` 是**死代码**，零引用，别改）
│   │   ├── models/              # SQLAlchemy ORM（order/user/product/ledger/cash_flow/...）
│   │   ├── schemas/             # Pydantic DTO（入参/出参）
│   │   ├── api/v1/              # 路由（按资源分文件，router.py 汇总挂载）
│   │   ├── services/            # 业务逻辑（订单流/账本/统计/导出/推送...）
│   │   └── ...
│   ├── scripts/                 # seed_dev_users / init_tables / backfill_cost_snapshots / reset_dev_passwords
│   ├── tests/                   # pytest（auth/orders/ledger/products/socket…）
│   ├── requirements.txt         # fastapi uvicorn sqlalchemy pymysql openpyxl fpdf2 ...
│   └── .env                     # database_url=sqlite:///./sorders.db 等
├── android/                     # Kotlin Compose App
│   └── app/src/main/java/com/tapmoay/sorders/
│       ├── MainActivity.kt / SOrdersApp.kt
│       ├── core/                # ApiClient ApiEndpoint TokenStore SocketManager RealtimeHub ...
│       ├── data/                # remote/api(Apis.kt) + remote/dto(Dtos.kt) + repo(AppRepository.kt)
│       ├── ui/                  # login/home/nav/dispatcher/shipper/driver/order/messages/profile/common/theme
│       └── util/                # Money TimeFmt AmapUri GeoResolver Watermark ExportUtil
│   └── local.properties         # api_base_url=192.168.x.x（真机用；模拟器走 10.0.2.2）
├── frontend/                    # Vue3 旧 H5（保留）
├── docs/                        # 业务/设计文档（PROJECT_OVERVIEW 等；本目录 PROJECT_MAP 为工程地图）
├── deploy/ docker-compose.yml   # 生产部署（MySQL+Redis+nginx）
├── scripts/                     # 运维脚本
├── _agent/                      # 工作用（gradle 发行版等，不入库关注）
├── dev-build.ps1                # 一键构建+安装到模拟器
├── requirements.md              # 需求原文
└── AGENTS.md                    # 仓库级协作约定
```

## 4. 启动与开发环境

### 后端
```powershell
cd D:\AProjects\ASDH\orders\backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 健康检查
curl http://127.0.0.1:8000/health
# 换库/初始化
python scripts/seed_dev_users.py      # 写入 1380000000x 测试账号
python scripts/reset_dev_passwords.py # 重置密码为 pass12345
```
- 表结构：`app/core/schema_bootstrap.py` 在 **导入 database 时自动 ALTER 补列**（旧库迁移靠它）
- 上传目录：`uploads/delivery|products|exports`（启动时自动创建）

### Android 构建
```powershell
# 方式1：一键脚本（构建+装到所有在线模拟器）
D:AProjectsASDHordersdev-build.ps1 -NoRun        # 只构建安装不开APP
D:AProjectsASDHordersdev-build.ps1 -NoBuild      # 只装现有APK
D:AProjectsASDHordersdev-build.ps1 -CleanBuild   # clean 后构建

# 方式2：命令行（2026-09-15 起按 ABI 分 flavor：emu=模拟器 x86_64，phone=真机 arm64+v7a）
$env:JAVA_HOME='D:/APPS/AndroidStudio/jbr'
D:/AProjects/ASDH/orders/_agent/gradle/gradle-8.9/bin/gradle.bat -p D:/AProjects/ASDH/orders/android :app:assembleEmuDebug
# APK 输出：android/app/build/outputs/apk/emu/debug/app-emu-debug.apk
# 真机包：:app:assemblePhoneDebug → outputs/apk/phone/debug/app-phone-debug.apk
# 发版请用 `_tools/deploy/publish_apk.py`，别手敲（见 docs/APP_UPDATE_AND_RELEASE.md）
```

### 静态 APK 分发（真机下载）
```powershell
python -m http.server 8001 --bind 0.0.0.0   # workdir=android/app/build/outputs/apk/phone/debug
# 真机访问 http://<电脑IP>:8001/app-phone-debug.apk
```

## 5. 角色与登录

- 用户表 `users`：`role`（dispatcher/shipper/driver）+ `is_member`（批发商=高级货主）+ `billing_mode`（司机计费 PIECE/SALARY）+ `vehicle_type`
- 登录：`POST /api/v1/auth/login`（手机号+密码，JWT `access_token`，24h）——**没有自助注册**：`/auth/register`、`/auth/sms/send` 已于 2026-09-18 按用户要求整体删除，建账号只有派单员 `POST /users` 一条路
- 角色权限：`app/core/rbac.py`（ROLE_PERMISSIONS 表；派单员=最高业务权限）

## 6. 业务主流程

```
货主下单(可选批发价/地址/联系人/图片)
  → 订单 PENDING_DISPATCH（待派单池，Socket.IO 推送派单员）
  → 派单员指派司机（选车辆/运费/collect_cash）→ DISPATCHED（已派单，待司机确认）
  → 司机接单(driver-ack) → ACCEPTED → 送达(complete / complete-with-upload / 拍照)
      · 按 collect_cash 决定：现场收现金(cash, paid) 或 挂账(arrears, 未付→挂账单位)
  → DELIVERED → 自动进账本(ledger sync) + 司机账(运费结算) + 报表
异常：is_exception / 超时自动异常 / 撤销 cancel / 拆分 split / 召回 recall
```

## 7. 数据流关键约定

- **订单金额 = Σ order_products.line_total**；`freight_fee` = 司机运费（与货款分离）
- `order_products.cost_price_snapshot`：商品成本快照（报表毛利/货损金额用；老数据可能为 0）
- `damage_quantity`：货损件数（≤quantity）
- `collect_cash`：派单时勾选；`payment_method` = cash|arrears；`paid` = 是否结清
- `ledger`：账本总账（订单自动同步 + 手动记账），`source` = ORDER / MANUAL / **REFUND**（⚠️ 漏掉 REFUND 会 500——货损退款单写的就是这个值，`schema_bootstrap.py` 有专门修复）
- `cash_flows`：**所有实际收付的唯一写入点**（客户收款/司机付款/开销/退款/调账）
- `price_rules`：批发商专属价（批发商+商品+special_unit_price），**下单报价的唯一依据**（没有专属价才用商品默认售价）；⛔ 商品上的 `tier_prices`（多档批发价）已于 2026-09-19 废弃：它看着像批发价、下单却谁都不照它走，列与历史数据保留但不再被任何接口读写
