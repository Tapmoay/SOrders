# SOrders 派单送货管理系统

三端（货主 / 司机 / 派单）协作的订单与账本系统。业务与集成约定见仓库内 `docs/` 与 `requirements.md`。

## 环境要求

- **后端**：Python 3.12+，MySQL 8，Redis（可选但推荐）
- ~~**前端**：Node.js 20+~~ 旧版 H5 前端**已归档**（2026-09-25 用户拍板），见下面那一节

## 快速开始（本地开发）

### 1. 数据库与 Redis

创建 MySQL 数据库（例如库名 `sorders`），并启动 Redis。

### 2. 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # Linux / macOS
pip install -r requirements-all.txt
```

（仅生产运行时可用 `pip install -r requirements.txt`；`requirements-all.txt` 包含测试依赖。）

复制环境变量：将仓库根目录 `.env.example` 复制为 `.env` 或 `backend/.env`，至少配置：

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | SQLAlchemy 连接串，如 `mysql+pymysql://user:pass@127.0.0.1:3306/sorders` |
| `JWT_SECRET_KEY` | JWT 签名密钥（生产环境须为长随机串） |
| `REDIS_URL` | 如 `redis://127.0.0.1:6379/0` |
| `AMAP_KEY` | 高德 Web 服务 Key（可选，地图相关功能） |

初始化表结构：

```bash
python scripts/init_tables.py
```

**SQLite 本地快速跑通（无需 MySQL）**：在仓库根 `.env` 中设置 `DATABASE_URL=sqlite+pysqlite:///./sorders.db`（同步引擎；勿用 `sqlite+aiosqlite` 除非已安装 `aiosqlite`）。然后写入与自动化测试一致的开发账号：

```bash
python scripts/seed_dev_users.py
```

| 角色 | 手机号 | 密码 |
|------|--------|------|
| 派单员 | 13800000001 | pass12345 |
| 货主 | 13800000002 | pass12345 |
| 司机 | 13800000003 | pass12345 |

启动 API（含 Socket.IO，与 FastAPI 同一 ASGI 进程）：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. 前端（已归档）

2026-09-25 用户拍板：旧版 H5 前端（frontend/，Vue3 + Vite）**正式归档、已从仓库删除**。
理由：它是三端里最初始的网页版，**没有任何部署引用**（_tools/deploy/ 与 nginx 都搜不到 frontend/dist），
线上没人访问；留着它却继续在 CI 里跑构建，就是报告 §14 说的「旧系统，但又像新系统」。

- 归档副本（本机、不进 git）：_archive/frontend-H5-归档-20260925/
- 代码本体可从 git 历史取回
- 连带改动：gate.yml 的 frontend-build 作业删掉；若干判据里的 H5 那一半停用（见 docs/RECTIFICATION_PLAN.md §4.2）


## API 文档（OpenAPI / Swagger）

后端启动后，在浏览器打开：

- **Swagger UI**：`http://127.0.0.1:8000/docs`
- **ReDoc**：`http://127.0.0.1:8000/redoc`

（路由由 FastAPI 提供；根应用为 Socket.IO 与 FastAPI 组合，上述路径仍由 FastAPI 子应用处理。）

## 自动化测试

后端单元与接口集成测试（SQLite 内存库，无需 MySQL）：

```bash
cd backend
pip install -r requirements-all.txt
pytest -v
```

覆盖范围包括：登录与 RBAC、订单派单/接单/送达/撤回/取消、批量派单与操作日志、账本写入与订单明细同步、Socket.IO 连接侧 JWT 与同步载荷等。

## Docker 部署

在仓库根目录：

```bash
docker compose up -d --build
```

- **API**：`http://127.0.0.1:8000`
- **MySQL**：`localhost:3306`（默认用户/库名见 `docker-compose.yml`）
- **Redis**：`localhost:6379`

生产环境务必通过环境变量或 compose 覆盖 `JWT_SECRET_KEY`、数据库密码等。API 前有 Nginx 时可将 `UVICORN_PROXY_HEADERS=1` 写入 `.env` 或在 compose 中设置，以便后端识别客户端真实地址（须仅允许可信反代）。

前端静态资源：在仓库根目录执行 `bash deploy/build-frontend.sh`（Linux/macOS）或 `.\scripts\build-frontend-for-deploy.ps1`（Windows），产物在 `frontend/dist`，交给 Nginx；反向代理示例见 `deploy/nginx.example.conf`（含 `/api/` 与 `/socket.io/`）。

## 仓库结构（摘）

- `backend/` — FastAPI 应用、`scripts/init_tables.py`
- `frontend/` — Vite + Vue 前端
- `deploy/nginx.example.conf` — Nginx 配置示例
- `docker-compose.yml` — MySQL + Redis + API
