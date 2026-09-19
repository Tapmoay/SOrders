# SOrders 生产 nginx 配置（2026-09-19 起，与服务器 `/etc/nginx/conf.d/sorders.conf` 一致）

> **为什么把它放进仓库**：这份配置原来只活在服务器上，改了什么、为什么这么改，谁都不知道 ——
> 而它恰好是"App 能不能连上"的唯一入口。放进来之后：改动可评审、可回滚、可复现。
> **改完服务器上的这份，请同步回来**（两边不一致时以本文件为准，因为它能被 review）。

## 部署方式（服务器上）

```bash
# 1) 配置本体
cp deploy/nginx/sorders.conf /etc/nginx/conf.d/sorders.conf
# 2) 公共 location（四块共用一处，见文件里的 include）
cp deploy/nginx/snippets/sorders-api-locations.conf /etc/nginx/snippets/sorders-api-locations.conf
# 3) 证书（私有 CA + IP 叶子；私钥不进仓库）
nginx -t && nginx -s reload
```

## 当前的传输层事实（2026-09-19 实测，别照旧文档猜）

| 事实 | 说明 |
|---|---|
| **`sorders.top` 未备案** | 阿里云按 Host/SNI 拦截：带 `Host: sorders.top` 请求本机 IP 的 80 会拿到他们那张「Non-compliance ICP Filing」403 页，443 也被按 SNI 打断 |
| Let's Encrypt 证书**已过期**（2026-07-11） | 因为 HTTP-01 挑战走 80 端口，被上面那条拦成 403 → `certbot-renew.timer` 从 7 月起**一直失败**且无人发现。域名块保留但**备案完成前不可用** |
| App 实际走 `https://8.145.40.22` | 证书由项目**私有 CA** 签（`/etc/nginx/ssl/`，SAN 含 `IP:8.145.40.22` + 域名），App 把这个 CA 当信任锚（`android/app/src/main/res/raw/sorders_ca.crt`） |
| 明文 80 端口**保留** | 迁移期：老版本 App（不认这张 CA）还要能下载更新包。等所有客户端都升级后，可在服务端按 `X-Forwarded-Proto` 硬拒非 TLS 请求 |

## 换证书的两条路

1. **换叶子证书（不用发版）**：只要仍由同一张私有 CA 签、SAN 仍含 `IP:8.145.40.22`，直接替换
   `/etc/nginx/ssl/sorders-ip-chain.crt` 与 `.key` 即可。叶子有效期 3 年（到 2029-09-18）。
2. **备案完成后切域名（要发版）**：域名证书是公开 CA 签的，但**老 App 的 base_url 写的是 IP** ——
   切域名等于换地址，必须发新版 App。届时 HTTPS 白名单里的私有 CA 可以留着（无害）。
   ⛔ 换掉私有 CA 本身**必须发版**（老包只认旧 CA）。

## 访问日志格式（2026-09-19 修）—— 它同时是"什么时候能关明文"的依据

`/etc/nginx/nginx.conf` 里的 `log_format main` 原来写成 `\%remote_addr ...`（**反斜杠把 `$` 转义了**），
于是 `access.log` 每行都是**字面量** `%remote_addr - %remote_user ...`：没有 IP、没有路径、没有状态码，
2651 行日志一条都用不上（排查"谁在探测 8000/什么接口"时完全瞎）。已修成真正的变量，并在末尾加了两个字段：

```nginx
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    'scheme=$scheme proto=$server_protocol';
```

**为什么要 `scheme=`**：它区分明文与 TLS，而**老版本 App 只会说 http**（它们的 base_url 编译进去就是
`http://8.145.40.22`，且那一版还允许明文）—— 所以 `scheme=http` 的请求量**就是"还没升级的客户端"的量**，
不需要让 App 上报版本号。统计口径：

```bash
grep -c 'scheme=https' /var/log/nginx/access.log      # 新客户端
grep -c 'scheme=http'  /var/log/nginx/access.log      # 老客户端（也是"明文可被窃听"的量）
```

等到 http 连续几天接近 0（只剩扫描器/健康检查），就可以做下一步：

## 下一步：服务端硬拒非 TLS —— **已开（只对登录端点）**，全站仍待观察

**2026-09-19 用户拍板"现在就开"**：`app/core/transport.py` 的判据已上线，
`POST /auth/login` 与 `POST /auth/token`（OAuth2 表单，同样带口令）在**明文下一律 426**。
公网实测：

| 请求 | 结果 |
|---|---|
| `POST http://8.145.40.22/api/v1/auth/login` | **426** + 中文 + 短链 |
| 同上，但客户端自己带 `X-Forwarded-Proto: https` | **照样 426**（→ nginx 覆盖该头是**端到端实证**，判据不可伪造） |
| `POST https://8.145.40.22/api/v1/auth/login` | 401（走到真正的校验） |
| 更新清单 / `/health` / `/apk`（明文） | 仍然 200/302 —— **故意不拦**，老客户端要能下包 |

**为什么只拦登录**：老包只会说明文，全站一开它们当场用不了；而登录这一条是"明文口令"的唯一入口，
关掉它就切断了报告里那条利用路径。全站硬拒的口径见上面（等 `scheme=http` 接近 0）。

**回滚**：把 `auth.py::_login` 里的 `reject_plaintext_credentials(request)` 那一行去掉即可
（判据本体在 `core/transport.py`，不动它就只是不再调用）。

### 老用户怎么升级（这条不能不设计）
被拒的老用户**卡在登录页**，而"检查更新"在登录**之后**的页面里 —— 他们够不到。
所以 426 报文里直接给短链：**`http://8.145.40.22/apk`** →
`publish_apk.py` 每次发布都会写一份 `sorders-latest.apk`（并把它排除在"清历史包"之外，
否则最新包会被当成最旧的删掉）。删掉 `location = /apk` 就等于删掉老用户唯一的出路。

## 下一步（全站）：服务端硬拒非 TLS（**还没做**）

报告修法第 5 步的全站版本。开启前请确认两件事：

1. `grep -c 'scheme=http' access.log` 里剩下的都是扫描器（看 user-agent / 路径）；
2. 建议**先只拒绝携带凭据的写请求**（`POST /auth/login` 等），观察一天再全量。

**判据不会被客户端伪造**（这一条是这道闸成立的前提）：
- `X-Forwarded-Proto` 由 nginx 用**连接的真实协议**（`$scheme`）覆盖后转发 —— 实测：明文请求里
  自己带 `X-Forwarded-Proto: https`，nginx 日志照样记 `scheme=http`；
- `proxy_set_header` 是"设置/替换"语义（`X-Forwarded-For` 要用 `$proxy_add_x_forwarded_for` 才追加，
  正说明裸写法会覆盖）；
- 后端 8000 端口**对外不通**（实测 000），所以没人能绕过 nginx 直接跟 uvicorn 说话。
- ⛔ 实现时必须按仓库纪律补一次**注入式验证**：带伪造头的明文请求必须被拒。

