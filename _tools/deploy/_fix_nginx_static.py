"""把生产 nginx 的 /static/uploads/ 改成"直接从磁盘发"，并给 .apk 补上正确的 MIME。

为什么改（2026-09-15）：
  ① /static/ 原先 proxy_pass 到 uvicorn:8000，而 uvicorn 只有 2 个 worker。
     一个人下 74MB 安装包 = 一个长期占用的流式长连接 = 占死一个 worker；
     两个人同时下，整个 API（含 Socket.IO）就排队。这是「一下载全体变慢」的机制性原因。
  ② nginx 自带的 mime.types 里没有 apk，alias 直出会退成 octet-stream；
     后端那条路由又会退成 text/plain（Starlette FileResponse 的兜底），
     手机浏览器拿到 text/plain 会去"渲染"几十 MB 二进制而不是存文件。

本脚本幂等：重复跑不会重复插。
"""
import re
import shutil
import time

CONF = "/etc/nginx/conf.d/sorders.conf"
MIME = "/etc/nginx/mime.types"
STAMP = time.strftime("%Y%m%d%H%M%S")

# ── ① /static/uploads/ 直出 ────────────────────────────────────────────────
conf = open(CONF, encoding="utf-8").read()
shutil.copy(CONF, CONF + ".bak-static-" + STAMP)

NEW_BLOCK = """location /static/uploads/ {
        # 直出磁盘，不经 uvicorn——慢客户端不再占住后端 worker
        alias /opt/SOrders/backend/uploads/;
        sendfile on;
        tcp_nopush on;
        # 安装包不缓存（版本号会变，缓存住就会一直下到旧包）
        add_header Cache-Control "no-cache";
    }

    # 其余 /static/ 仍然走后端（保持原行为，不扩大改动面）
    location /static/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }"""

if "/static/uploads/" in conf:
    print("SKIP  conf: /static/uploads/ 已经配过了")
else:
    conf2, n = re.subn(r"location /static/ \{[^}]*\}", NEW_BLOCK, conf)
    if n == 0:
        raise SystemExit("FAIL  conf: 没找到 location /static/ 块，未改动")
    open(CONF, "w", encoding="utf-8").write(conf2)
    print("OK    conf: 替换了 %d 处 location /static/ → 增加 /static/uploads/ 直出" % n)

# ── ② mime.types 补 apk ───────────────────────────────────────────────────
mime = open(MIME, encoding="utf-8").read()
if "package-archive" in mime:
    print("SKIP  mime: apk 类型已存在")
else:
    shutil.copy(MIME, MIME + ".bak-" + STAMP)
    mime2, n = re.subn(
        r"(\n\s*application/pdf\s+pdf;)",
        r"\1\n    application/vnd.android.package-archive      apk;",
        mime,
        count=1,
    )
    if n == 0:
        # 没有 pdf 行就插在 types { 之后
        mime2 = mime.replace("types {", "types {\n    application/vnd.android.package-archive      apk;", 1)
    open(MIME, "w", encoding="utf-8").write(mime2)
    print("OK    mime: 加入 application/vnd.android.package-archive apk")
