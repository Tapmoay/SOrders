# 生产**只读**核对证据（R3-05 前置 · 2026-09-26）

> **这是什么**：用户 2026-09-26 拍板③「**生产只读放行**：只验证，不做业务写入；优先核对：
> 版本 / 依赖 / migration / DB / Redis / nginx / uploads / trace」之后，在生产上跑的**唯一一次**核对。
> ⛔ **全程只读**：没有备份、没有迁移、没有重启、没有一条写 SQL、没有建文件、没有改配置。
> **怎么自己复核**（一条命令，它自己会打印结论与退出码）：
>
> ```
> python _tools/ops/_prod_smoke.py --readonly
> ```
>
> 退出码三档：**0** 现状健康且与这一版代码一致（发布后应当是这个）｜**1** 现状健康但与这一版代码不一致
> （**今天就是这个**：发布还没做）｜**2** 现状本身就出了问题（服务/库/Redis/磁盘/备份那种）。
> 采集口径复用 `_prodssh.prod_facts_script()` 与 `_health_check._facts()`（⛔ 事实只有一处，不各写一份）。

## 一、结论一页纸

| | 结论 |
|---|---|
| 生产**现状** | ✅ 健康：服务 active、`/health` 200、库可达（44 张表 / 11.6 MB）、Redis PONG、磁盘 29%（可用 27G）、上传目录 2115 个文件 / 187M、最近一次备份 1.2 小时前 |
| 生产**跑的是哪一版** | ⛔ **648fbf81**（2026-09-23 09:02，分支 new）—— **落后本仓库 HEAD 286 个提交** |
| 这一次能不能算「生产验过了」 | ⛔ **不能**：只读核对证明的是**现状**，不是「这一版代码在生产上跑过」——那要写操作（备份→迁移→启动），是**另一次许可** |
| 依赖那一格（R3-07d 决策①） | ✅ 已量到：**生产 15/15 运行依赖全部落在声明区间内**，`cryptography` = **43.0.3** ∈ `>=42,<44` |

## 二、八项逐条（用户点名要核的）

### 1) 版本

| 项 | 实测 |
|---|---|
| 生产仓库提交 | `648fbf8134c4ffcae86e698255fdf2427ded71c2`（2026-09-23T09:02:55+08:00，分支 `new`） |
| 落后本仓库 | **286 个提交**（`git rev-list --count 648fbf8..HEAD`，只读 git、不联网） |
| 跟踪文件被手改？ | ⛔ 没有（`git status --porcelain` 里 `M` 行 = 0）；未跟踪 8 个（都是 `.env.bak-*` / `*.py.bak-*` / `backend_src_p.tgz` 这类历史备份文件） |
| 解释器 | Python 3.11.13（⚠️ 本机是 3.12） |
| 接口表 | `/openapi.json` 里 **160** 条路由（仓库最近一次快照 `r2-05-after.json` 是 165 条 —— 它只是**某个时点**的记录，不是「当前代码」） |
| systemd | `sorders-api` active，自 Wed 2026-09-23 08:58:54 CST 起未重启（NRestarts=0） |
| 主机 | Alibaba Cloud Linux 3.2104 U13 (OpenAnolis Edition)，2 核 / 1870 MB 内存 / 已开机 93 天 |

### 2) 依赖（决策① 要的那一格）

生产 venv：`/opt/SOrders/backend/.venv`，**49 个包**，`pip freeze` 的 sha256 前 16 位 `dcfad65fe4b3823f`。

逐条对**声明的运行依赖**（15 条）：

| 包 | 仓库里的声明 | 生产实际装的 |
|---|---|---|
| `fastapi` | `fastapi>=0.110,<1` | **0.135.3** |
| `uvicorn` | `uvicorn[standard]>=0.27,<1` | **0.44.0** |
| `sqlalchemy` | `sqlalchemy>=2.0,<3` | **2.0.49** |
| `pymysql` | `pymysql>=1.1,<2` | **1.1.2** |
| `cryptography` | `cryptography>=42,<44` | **43.0.3** |
| `pydantic-settings` | `pydantic-settings>=2.2,<3` | **2.13.1** |
| `python-jose` | `python-jose[cryptography]>=3.3,<4` | **3.5.0** |
| `passlib` | `passlib[bcrypt]>=1.7,<2` | **1.7.4** |
| `bcrypt` | `bcrypt>=4.0.1,<4.1` | **4.0.1** |
| `python-multipart` | `python-multipart>=0.0.9,<1` | **0.0.26** |
| `redis` | `redis>=5.0,<6` | **5.3.1** |
| `email-validator` | `email-validator>=2.1,<3` | **2.3.0** |
| `openpyxl` | `openpyxl>=3.1,<4` | **3.1.5** |
| `fpdf2` | `fpdf2>=2.7,<3` | **2.8.7** |
| `python-socketio` | `python-socketio>=5.11,<6` | **5.16.1** |

**9 条开发依赖**（pytest / pytest-asyncio / httpx / pytest-xdist / pytest-html / pytest-metadata /
pytest-pretty / pytest-cov / numpy）生产**没装** —— 生产不装开发依赖是正常的。

⛔ **这一格推翻了「本机 48 就是真相」的猜测**：生产是 **43.0.3**，正落在声明区间 `>=42,<44` 里。
也就是说 —— 声明**没有错**，偏差在**本机**。若按本机去把声明放宽，等于拿本机的偏差去改一件
生产上本来正确的事（用户决策①「不凭本机猜生产」拦的正是这个）。全量 `pip freeze` 见 §六。

### 3) migration

| 项 | 实测 |
|---|---|
| 生产代码里有 `app.migrations` 吗 | ⛔ **没有**（`ModuleNotFoundError: No module named 'app.migrations'`） |
| 生产库有 `schema_versions` 表吗 | ⛔ **没有**（information_schema 查到 0 张） |

结论：**R3-01 的版本化迁移还没上生产**。所以「生产库结构 = 仓库最新版本 N」这件事**今天无法成立**，
也不能靠「库里看着有表」推断 —— 那 44 张表是**旧代码自愈**建的（`schema_bootstrap` 时代）。

### 4) DB

| 项 | 实测 |
|---|---|
| 可达性 | ✅ `select 1` → 1 |
| 版本 | mysql  Ver 8.0.44 for Linux on x86_64 (Source distribution) |
| 表数 / 体积 | 44 张 / 11.6 MB |
| 规模 | orders / ledgers / users / products 都读得到；最近一单 SO202609222864904837|DELIVERED|2026-09-22 01:25:09（它的审计行 SO202609222864904837|5） |
| 时区口径 | ⚠️ `time_zone = SYSTEM|SYSTEM` —— **不是 UTC**（那是「代码里把会话时区钉成 UTC」那一段还没上生产的直接后果） |
| outbox | ⛔ 没有 `outbox_events` 表（发件箱还没上生产） |

### 5) Redis

| 项 | 实测 |
|---|---|
| 存活 | ✅ `PING` → PONG（6.2.20） |
| keyspace | （空 —— 没有任何 key） |
| 口令 | ⚠️ **空**（requirepass 长度 1）—— 既知缺口；它只监听 127.0.0.1 且安全组只放行 80/22，所以不是「网上直接可打的洞」 |

⛔ Redis 现在**没有被业务用到**（keyspace 是空的）—— 这也说明**Socket.IO 跨实例推送这一格**
（R3-03 的那条 ❌）在生产上同样**没有证据**，不是「验过了」。

### 6) nginx

| 项 | 实测 |
|---|---|
| 版本 / 配置 | nginx/1.20.1，`nginx -T` 247 行（配置 sha 前 32 位 `06d8f1504a2381b81a4d05cbff78252a`） |
| 反代 | `proxy_pass http://127.0.0.1:8000;;` —— **单后端 proxy_pass**，没有 `upstream` 块 |
| 失败摘除 | ⛔ 没有 `max_fails` / `fail_timeout` / `proxy_next_upstream` 任何一条 |
| WebSocket | ✅ `location /socket.io/` 带 `Upgrade`/`Connection` 头转发到 `127.0.0.1:8000` |
| 静态 | ✅ `location /static/uploads/` |

这一格把 R3-03「nginx upstream + 失败摘除」那条 ❌ 的**事实**补齐了：**现在这套部署形态里根本没有
upstream**（后端是**一个** systemd 服务里的 2 个 uvicorn worker，nginx 直接 proxy_pass 单端口）。
要让那一格成立，需要**同时**改部署形态（多实例/多端口）与 nginx 配置 —— 那是发布变更，属写阶段。

### 7) uploads

| 项 | 实测 |
|---|---|
| 目录 | `/opt/SOrders/backend/uploads` ✅ 可读 |
| 规模 | 2115 个文件 / 187M |
| ⛔ 没做的事 | **没有**做写入探测（那会往生产上传目录里放垃圾文件）—— 「能不能写」这件事本轮**没有验** |

### 8) trace（request_id / command_id）

| 项 | 实测 |
|---|---|
| `operation_logs` 有 `request_id` / `command_id` 列吗 | ⛔ **没有**（information_schema 查到 0 / 2 列） |
| `app/core/request_id.py` 在生产代码里吗 | ⛔ **没有** |
| 带 `X-Request-ID: r3smoke-…` 打 `http://127.0.0.1:8000/health` | 200，但**响应头里没有这个 id**（生产这一版代码根本没有那个中间件） |
| 经 nginx 打 `/api/v1/orders` 同一个 id | 401（未带 token，符合预期），响应头同样没有它 |

结论：**R3-04 的那一层（request_id 贯穿 + command_id）在生产上还不存在** —— 「生产上能按一次请求串起
整条链」这句话今天**没有证据**，如实记着，不拿本机的绿灯替代。

## 三、生产现状里**好**的那些（也都记着，免得只看见缺口）

| 项 | 实测 |
|---|---|
| 服务 | `sorders-api` active，`/health` → 200（`{"status":"ok","version":"0.2.0","redis":"ok"}`） |
| 数据库 | 可达 / 44 张表 / 11.6 MB |
| Redis | PONG |
| 磁盘 | 已用 29%（可用 27G） |
| 上传 | 2115 个文件 / 187M |
| 备份 | 10 份库备份 / 208M，最近一次 1.2 小时前（≤36h 阈值内） |

## 四、本轮**记下来但没动**的风险（逐条，不悄悄忽略）

1. **落后 286 个提交**：生产是 2026-09-23 的代码，R2/R3 的东西基本都不在上面（这也是 §二 里那些「没有」的根因）；
2. **Redis 无口令**（既有事实，`_health_check.py` 每天盯；本机网络不可达故不是公网洞）；
3. **MySQL `time_zone = SYSTEM`**：库里存的是 UTC 还是本地时间，取决于代码有没有钉会话时区 —— 新代码钉了，
   而新代码没上生产 ⇒ 这一条要**在发布后重新量一次**；
4. **生产上有 8 个未跟踪的历史备份文件**（`.env.bak-*` / `*.py.bak-*` / `backend_src_p.tgz`）：跟踪文件没被改过，
   但 `.env.bak-*` 里是**旧口令**（已失效）—— 发布时顺手清掉；
5. **`sorders.top` 证书未备案导致的续期失败**：已在 `_health_check.py` 的「已知/已接受」表里逐条写明理由与退出条件。

## 五、⛔ 这一次**证不了**什么（别把它当护身符）

1. ⛔ **不证明「这一版代码在生产上跑得起来」** —— 只读核对的对象是**旧代码**；
2. ⛔ **不证明写路径** —— 全程没有一条写操作（这正是它的安全来源，也是它的边界）；
3. ⛔ **不证明备份可用**：备份**在跑**（年龄 1.1 小时）不等于**恢复成功过** —— 恢复演练是另一件事；
4. ⛔ **不证明迁移能过**：生产库还是旧结构、没有版本表，第一次 `upgrade` 会发生什么，本轮的只读证据答不了；
5. ⛔ **没有验 uploads 可写、没有验 Socket.IO 跨实例、没有验 nginx 失败摘除** —— 这三件都需要写阶段。

## 六、原始事实（机器产物，⛔ 不是手抄的）

取证命令（写 JSON 到临时目录；仓库里不留产物）：

```
python _tools/ops/_prod_smoke.py --readonly --json "%TEMP%\r3_prod_smoke.json"
```

`pip freeze` 全量清单（生产 `/opt/SOrders/backend/.venv`，49 个包）：

```
  annotated-doc==0.0.4
  annotated-types==0.7.0
  anyio==4.13.0
  bcrypt==4.0.1
  bidict==0.23.1
  cffi==2.0.0
  click==8.3.2
  cryptography==43.0.3
  defusedxml==0.7.1
  dnspython==2.8.0
  ecdsa==0.19.2
  email-validator==2.3.0
  et_xmlfile==2.0.0
  fastapi==0.135.3
  fonttools==4.62.1
  fpdf2==2.8.7
  greenlet==3.4.0
  h11==0.16.0
  httptools==0.7.1
  idna==3.11
  openpyxl==3.1.5
  passlib==1.7.4
  pillow==12.2.0
  pyasn1==0.6.3
  pycparser==3.0
  pydantic==2.12.5
  pydantic-settings==2.13.1
  pydantic_core==2.41.5
  PyJWT==2.12.1
  PyMySQL==1.1.2
  python-dotenv==1.2.2
  python-engineio==4.13.1
  python-jose==3.5.0
  python-multipart==0.0.26
  python-socketio==5.16.1
  PyYAML==6.0.3
  redis==5.3.1
  rsa==4.9.1
  simple-websocket==1.1.0
  six==1.17.0
  SQLAlchemy==2.0.49
  starlette==1.0.0
  typing-inspection==0.4.2
  typing_extensions==4.15.0
  uvicorn==0.44.0
  uvloop==0.22.1
  watchfiles==1.1.1
  websockets==16.0
  wsproto==1.3.2
```

`_health_check.py` 的四项（服务/证书/磁盘/数据库 + 发件箱）与 `prod_facts_script()` 的其余字段
（证书剩余天数、备份年龄、crontab、服务哈希…）在同一份 JSON 里，需要时直接读它。
