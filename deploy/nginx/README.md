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
