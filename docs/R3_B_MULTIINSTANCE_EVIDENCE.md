# R3 B 段（多实例运行时）原始证据（2026-09-26）

> **这份是什么**：用户 2026-09-26 放行 B（「Redis → 双实例 Socket → Socket 实测 → nginx upstream → 摘机测试」）之后，
> 每一步的**原始输出**。⛔ 结论在 `docs/R3_PROGRESS.md` 的 R3-03 与「写阶段出口」两节；这里只放事实。
> ⛔ **只做 B**：C（五个故障演练）**未放行**，本文件里没有它们的任何动作。

---

## 零、先纠正一条**之前记错的事实**

台账在 A 段之前写过：「生产 Redis 的 `info keyspace` 没有任何 db 行（键空间是空的）⇒ 生产**也没有**在用跨实例适配器」。
⛔ **这条推论是错的**：Socket.IO 的 Redis 适配器用的是 **pub/sub 频道**，而 pub/sub **不落在 keyspace 里** ——
「keyspace 空」只能说明没有**持久化键**，推不出「没在用适配器」。

实测事实：`/opt/SOrders/.env` 里**本来就有** `SOCKET_REDIS_URL`，而且启动日志里**没有**那句
「SOCKET_REDIS_URL 未配置：Socket.IO 走进程内内存模式」的警告 ⇒ **生产的适配器一直是开着的**（`redis://127.0.0.1:6379/0`）。

```text
$ grep -i redis /opt/SOrders/.env | sed 's/=.*/=<redacted>/'
REDIS_URL=<redacted>
SOCKET_REDIS_URL=<redacted>
$ systemctl show sorders-api-a -p Environment   # unit 里不写变量，全靠 EnvironmentFile
$ （A 段日志）grep -c 'SOCKET_REDIS_URL 未配置' → 0
```

⭐ 这条纠正本身也是 B 的收获：**「看起来空」当不了判据** —— 差点让「socket 跨实例」这一格一直挂在「本机没有 Redis」上。

---

## 一、B0：先备料，⛔ 不碰 nginx

```text
$ ls /opt/SOrders/backend/app/migrations   # 代码早就在（A 段落的位）
$ python -c 'from app.config import get_settings; ...'
socket_redis_url set: True | host part: redis://127.0.0.1:6379/0
redis-py 5.3.1 ｜ python-socketio 5.16.1 ｜ python-engineio 4.13.1 ｜ websockets 16.0 ｜ simple-websocket 1.1.0
⚠️ venv 里**没有 aiohttp** —— python-socketio 的 AsyncClient 硬依赖它，所以下面的实测客户端改用 **raw WebSocket** 直接讲协议
（⛔ 不给生产 venv 装一个只为测试用的依赖）。
```

## 二、B1：两个实例 + **跨实例双向实测**（Socket Redis 用 db 1，与线上 db 0 隔离）

```text
$ env SOCKET_REDIS_URL=redis://127.0.0.1:6379/1 ... uvicorn app.main:app --port 8111 --workers 1
$ env SOCKET_REDIS_URL=redis://127.0.0.1:6379/1 ... uvicorn app.main:app --port 8112 --workers 1
A :8111 -> 200  {"status":"ok","version":"0.2.4","redis":"ok"}
B :8112 -> 200  {"status":"ok","version":"0.2.4","redis":"ok"}
grep -c '未配置' /tmp/b_a.log /tmp/b_b.log → 0 / 0   （两个实例都在用 Redis 适配器）
```

### 实测客户端为什么要自己写

python-socketio 的 `AsyncClient` 需要 aiohttp；生产 venv 里没有（也不该为测试装）。
所以实测用 **raw WebSocket 直接讲 Socket.IO 协议**（Engine.IO v4 / Socket.IO v5）：

```text
连 ws://host/socket.io/?EIO=4&transport=websocket → 收 `0{...}`（open）
→ 发 `40{"token":"<jwt>"}`（默认命名空间 CONNECT）→ 收 `40{...}`（ack）
→ 事件是 `42["sync",{...}]` / `42["notification",{...}]`；服务端 `2`=ping，客户端回 `3`
```

⛔ 这样反而**更强**：能看到原始包，也能证明「不是客户端库自己在本地重连成功」。

```text
== B1 Socket.IO 跨实例双向实测（A :8111 / B :8112，Socket Redis db 1）==
  OK   A 上 emit -> 连在 B 上的客户端收到 -> 收到（emit 后 0.1s，通知 id=41724）
  OK   B 上 emit -> 连在 A 上的客户端收到 -> 收到（emit 后 1.5s，通知 id=41725）
结果：A->B OK | B->A OK
```

（触发方式是 `POST /api/v1/notifications` 给**测试账号**发一条站内信 —— 它在 A 上 emit、客户端连在 B 上；反向同理。
⛔ 只动 13800000002 / 13800000003 两个测试账号，不碰真实客户数据。）

---

## 三、B2：把两个实例做成常驻服务，最后才动 nginx

### 3.1 两个 unit（各 1 worker；老服务先留着当安全网）

```ini
# /etc/systemd/system/sorders-api-a.service（b 同，端口 8112）
ExecStart=/opt/SOrders/backend/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8111 --workers 1
EnvironmentFile=/opt/SOrders/.env      # ⇒ SOCKET_REDIS_URL 用的是 **db 0**（与线上客户端同一个频道）
Restart=always
```

```text
$ systemctl is-active sorders-api-a sorders-api-b → active active
$ systemctl is-enabled sorders-api-a sorders-api-b → enabled enabled
$ curl :8111/health → 200 {"status":"ok","version":"0.2.4","redis":"ok"}
$ curl :8112/health → 200 {"status":"ok","version":"0.2.4","redis":"ok"}
```

⚠️ 第一次起 unit 时**失败了**：端口被 B1 的临时实例占着（`[Errno 98] address already in use`）——
先停临时实例、再起 unit，如实记着（这也是「每一步都要看结论、不能只看命令返回」的一个例子）。

### 3.2 nginx：单后端 → upstream（⛔ 最后才做，且先备份 + `nginx -t`）

```nginx
upstream sorders_backend {
    ip_hash;                                   # Socket.IO 先 polling 再升级 websocket，这一串必须落同一个后端
    server 127.0.0.1:8111 max_fails=2 fail_timeout=10s;
    server 127.0.0.1:8112 max_fails=2 fail_timeout=10s;
}

location /api/ {
    proxy_pass http://sorders_backend;
    proxy_next_upstream error timeout http_502 http_503 http_504;
    ...
}
```

```text
备份：/opt/sorders-backup/b2-nginx-20260926-223624（含改前的两个文件 + 改前 nginx -T 全文）
nginx -t：syntax is ok / test is successful          ← 不过就直接回滚，不 reload
systemctl reload nginx → reload ok
经 nginx:80  GET /api/v1/orders ×3 → 401 401 401      （401 = 应用答了、只是没带 token）
```

### 3.3 摘机测试（⭐ 这才是「失败摘除真的触发了」的那一步）

```text
① 基线：3 次请求 → 401 401 401 ｜ 近 4 秒命中：A=6 次 B=0 次
② 摘掉 A（ip_hash 把 127.0.0.1 钉在 A 上 ⇒ 摘的正是**正在服务的那台**）
   探针 → 401 401 401 ｜ 命中：A=6 B=6      ← 前几次打到已死的 A 计失败，之后**全改投 B**
   A=inactive B=active
③ 恢复 A，**等 15 秒**（让 fail_timeout=10s 的窗口过去）：探针 → 401 401 401 ｜ 命中：A=6 B=0
④ 再摘掉 B：探针 → 401 401 401 ｜ 命中：A=12 B=0   ← **A 继续服务**
⑤ 恢复 B、再等窗口：探针 → 401 401 401 ｜ A 接
⑥ 直连两台：200 / 200
```

原文（`/var/log/nginx/error.log`）—— 「失败摘除」不是「配置文件里看起来有」：

```text
2026/09/26 22:36:39 [error] connect() failed (111: Connection refused) while connecting to upstream,
                            upstream: "http://127.0.0.1:8111/api/v1/orders"
2026/09/26 22:36:46 [error] connect() failed (111: Connection refused) ... "http://127.0.0.1:8112/..."
2026/09/26 22:36:46 [error] **no live upstreams** while connecting to upstream,
                            upstream: "http://sorders_backend/api/v1/orders"
2026/09/26 22:37:09 [error] connect() failed (111: Connection refused) ... "http://127.0.0.1:8111/..."
```

⚠️ **第一次跑摘机测试时第三步出过 502**，原因是我自己的时序：摘掉第二台时，第一台的 `fail_timeout=10s` 窗口还没过完
（nginx 仍认为它也挂着）⇒ `no live upstreams`。这正是被动健康检查的**正确**行为，不是配置缺陷；
把窗口等过去重跑就全绿了。⛔ 如实记着，不把「我踩的时序坑」写成「nginx 的问题」。

### 3.4 真拓扑上复验 Socket（db 0）+ 经 nginx 的升级路径

```text
== B2 复验：真拓扑（A :8111 / B :8112，Socket Redis db 0）==
  OK   A 上 emit -> 连在 B 上的客户端收到 -> 收到（1.7s，通知 id=41726）
  OK   B 上 emit -> 连在 A 上的客户端收到 -> 收到（0.0s，通知 id=41727）
  OK   经 nginx:443 登录 + /socket.io/ WebSocket 升级 -> 收到 CONNECT ack
```

⚠️ 顺带量到一条**设计使然**的行为：经 nginx 的**明文 80** 发 `POST /api/v1/auth/login` 会拿到
**426 Upgrade Required** —— 那是应用「拒绝明文登录」的策略（老客户端走 `http://…/apk` 那条短链），
⛔ 不是 B 造成的；走 443 就正常。

### 3.5 老服务退场（nginx 已经不再指向它）

```text
$ systemctl stop sorders-api && systemctl disable sorders-api
$ systemctl is-active sorders-api → inactive ｜ is-enabled → disabled
$ curl :8000/health → 000（连不上 = 已退场）
$ 经 nginx:80 GET /api/v1/orders ×3 → 401 401 401 ；/health → ok
内存：used 1258 MB → **911 MB**；available 612 MB → **959 MB**（两个单 worker 反而比原来一个 unit 里 2 worker 省）
进程：8111 → 143 MB ／ 8112 → 143 MB
```

⛔ **unit 文件保留**（只是 disable）：回滚 B2 = `systemctl enable --now sorders-api` + 把 nginx 那两个文件从
`/opt/sorders-backup/b2-nginx-20260926-223624/` 拷回去 + `nginx -t && systemctl reload nginx`。

---

## 四、B 之后的整体验收（同一套工具，认的是**新拓扑**）

```text
python _tools/ops/_health_check.py        → 6 项正常 / 2 告警 / 0 失败
    服务 / 健康检查：units=sorders-api-a.service sorders-api-b.service ｜ systemd=active,
                     ｜ /health=200（8111=200 8112=200）
python _tools/ops/_prod_smoke.py --readonly → **32 通过 / 2 已批准告警 / 0 不一致**
    ✅ 两个后端实例都活着（A :8111 / B :8112）—— A=200 B=200
    ✅ nginx 反代到后端 —— proxy_pass http://sorders_backend;
    ✅ nginx 的 upstream 形态 —— upstream sorders_backend { ip_hash; server …8111 max_fails=2 …; server …8112 …; }
    ✅ request_id 直连应用 / 经 nginx 都原样回来
python _tools/seed/_prod_api_smoke.py      → 全部 27 条接口 200（三端页面依赖的读接口）
python _tools/deploy/_release.py --step smoke --go → ✅ ERROR 0 条、未批准告警 0 条；已批准告警 2 条
```

⭐ 工具侧同步做的三件事（⛔ 都是「把写死的旧形态改成认拓扑」，不是放水）：
1. `_prodssh.prod_facts_script()`：`service_state` 认**所有 enabled 的 `sorders-api*` unit**（单实例/双实例都采得到，
   以后再加实例也自动被采到）；后端端口从**正在跑的 uvicorn 进程**里取，不再写死 8000；新增 `api_health_each`（逐端口）。
2. `_prod_smoke.py`：新增一行 **「两个后端实例都活着」**（⛔ 单后端时代它够不着这个风险：一台悄悄死了、
   nginx 还在往它转，每次只多花一次失败重试，**看不出来**）；「反代到后端」接受 upstream 形态；trace 探针不再写死 8000。
3. `_health_check.py`：`systemd=active,` 这种多 unit 形态也判「全活」。

---

## 五、⛔ 这份证据**证不了**什么

- ⛔ **不证多主机**：A 与 B 是**同一台机器上的两个进程**，共享本机 MySQL / Redis / uploads。
  跨主机（多机部署）会多出「共享存储 / 网络分区 / Redis 也变成远端」这些变量，**没验**；
- ⛔ **不证真实 App 端**：跨实例是用 raw WebSocket 客户端验的；真机在 nginx 后面的长连接行为没验（App 这一轮没连生产）；
- ⛔ **不证粘性对所有客户端都成立**：`ip_hash` 按客户端 IP 粘 —— 同一出口 NAT 后的一群客户端会都落到同一台（能用，但负载不均），
  而「按会话粘」要 `hash $cookie_…` 或 `sticky` 模块（**没做**）；
- ⛔ **不证故障演练**：五个演练（C 段）一条没跑；「备份能不能真的恢复」也**还没验**（那是 C 的前置）；
- ⛔ **不证性能/容量**：两个单 worker 能不能扛住现有流量没做压测；这里只证「两个实例能同时正确地服务、且一台挂了另一台能接」。