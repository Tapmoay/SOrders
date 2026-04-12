#!/bin/sh
set -e
# 等待 MySQL 端口可连（compose healthcheck 通过后仍可能有短暂时序问题）
python - <<'PY'
import os, socket, time
host = os.environ.get("MYSQL_HOST", "mysql")
port = int(os.environ.get("MYSQL_PORT", "3306"))
for i in range(60):
    try:
        s = socket.socket()
        s.settimeout(2)
        s.connect((host, port))
        s.close()
        break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit("Could not reach MySQL at %s:%s" % (host, port))
PY
python scripts/init_tables.py

# 置于 Nginx/Ingress 后时设置 UVICORN_PROXY_HEADERS=1，便于识别 X-Forwarded-*（须仅信任上游代理）
UVICORN_EXTRA=""
if [ "${UVICORN_PROXY_HEADERS:-}" = "1" ]; then
  UVICORN_EXTRA="--proxy-headers --forwarded-allow-ips=*"
fi

# shellcheck disable=SC2086
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 ${UVICORN_EXTRA}
