# SOrders 派单送货管理系统

三端（货主 / 司机 / 派单）协作的订单与账本系统。业务与集成约定见仓库内 `docs/` 与 `requirements.md`。

## 环境要求

- **后端**：Python 3.12+，MySQL 8，Redis（可选但推荐）
- **前端**：Node.js 20+（用于构建与开发）

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

### 3. 前端

**方式 A：系统已安装 Node.js 20+**

```bash
cd frontend
npm install
npm run dev
```

**方式 B：便携 Node（无需管理员，已解压到仓库 `.tools/`）**

1. 从 [Node 20 Windows x64 zip](https://nodejs.org/dist/v20.18.1/node-v20.18.1-win-x64.zip) 解压到 `SOrders/.tools/node-v20.18.1-win-x64/`（与 `node.exe` 同级有 `npm.cmd`）。
2. 在 **当前 PowerShell 会话** 先执行（或把该路径永久加入用户 PATH）：

```powershell
# 在仓库根目录执行
. .\scripts\set-dev-path.ps1
cd frontend
npm install
npm run dev
```

若未解压便携包，也可使用 `winget install OpenJS.NodeJS.LTS --source winget`（需 UAC 同意）。

**说明**：`npm install` 时请将 **Node 安装目录放在 PATH 最前**，否则 `esbuild` 等脚本会找不到 `node`（错误：`node 不是内部或外部命令`）。

生产构建（输出静态文件到 `frontend/dist`）：

```bash
npm run build
```

将 `dist` 目录部署到 Nginx 或其它静态托管；生产环境请配置 `VITE_API_BASE_URL` 指向线上 API 根路径（含 `/api/v1`），详见 `.env.example`。

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

生产环境务必通过环境变量或 compose 覆盖 `JWT_SECRET_KEY`、数据库密码等。

前端需先在宿主机执行 `cd frontend && npm run build`，再将 `dist` 交给 Nginx；反向代理示例见 `deploy/nginx.example.conf`（含 `/api/` 与 `/socket.io/`）。

## 仓库结构（摘）

- `backend/` — FastAPI 应用、`scripts/init_tables.py`
- `frontend/` — Vite + Vue 前端
- `deploy/nginx.example.conf` — Nginx 配置示例
- `docker-compose.yml` — MySQL + Redis + API
