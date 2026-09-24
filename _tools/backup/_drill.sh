#!/usr/bin/env bash
# _drill.sh —— 恢复演练（报告 §3：「恢复演练必须真的做」，不是"脚本 exit 0"）。
#
# 报告对这件事的原话是：
#   不是 `脚本 exit 0`，而是
#   创建测试数据库 → 恢复 → 启动 → 跑关键 API → 验证订单 / 钱 / 状态 → 删除测试库
# 本脚本就是把这句话逐条做成步骤，**每一步都要留下可读的证据**。
#
# 四个阶段：
#   ① 选一份备份 → 用 _restore.sh 恢复到 sorders_drill_<UTC 时间戳>（**绝不碰生产库**）
#   ② 库内不变式：状态枚举 / 金额非负 / 外键孤儿 / 时间基准 —— 判据取自**生产代码里的枚举定义**
#   ③ 真的把后端起起来（隔离端口 + 隔离 Redis + 隔离工作目录）→ /health → /openapi.json
#   ④ 用真实 token 打三个只读端点（订单 / 商品 / 账本），看是不是 200
#   收尾：无论成败都拆掉演练库、临时 Redis、临时进程（trap）
#
# 为什么必须"隔离"（这三样都是踩过才知道的）：
#   · **隔离端口**：生产 uvicorn 在 8000，演练用 8011 —— 撞端口会把生产顶掉；
#   · **隔离 Redis**：Redis 的 pub/sub 通道是**全库共享**的（db index 不隔离它），
#     演练实例连生产 Redis 就可能往真实客户端推事件 —— 所以临时起一个 6390；
#   · **隔离工作目录**：`data_retention` 用的是相对路径 `Path("uploads")`，
#     在生产目录里跑演练会去压缩**生产的图片文件**。cwd 换成空的演练目录就切断了。
#
# 用法（在生产机上）：
#   bash _drill.sh                            # 用最新一份可用备份
#   bash _drill.sh --backup /opt/sorders-backup/pre_release/20260924T200000Z
#   bash _drill.sh --keep                     # 保留演练库/日志（排查用）
#   bash _drill.sh --skip-boot                # 只验库（快，30 秒）
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
APP_DIR=/opt/SOrders
BACKEND_DIR="$APP_DIR/backend"
ENV_FILE="$APP_DIR/.env"
BACKUP_ROOT=/opt/sorders-backup
RUN_DIR="$BACKUP_ROOT/drill-run"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
PORT=8011
REDIS_PORT=6390
KEEP=0
SKIP_BOOT=0
BACKUP_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --backup) BACKUP_DIR="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --skip-boot) SKIP_BOOT=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

[ -x "$VENV_PY" ] || { echo "⛔ 找不到后端 venv：$VENV_PY" >&2; exit 2; }
# ⚠️ 系统 python3 是 3.6（实测），而 _restore.sh 里的脚本用到 3.7+ 的 subprocess 参数 ——
#    这里显式挡住，免得"回落到系统 python"变成一条谁也看不懂的报错。

if [ -z "$BACKUP_DIR" ]; then
  # ⚠️ 实测踩到：find 一旦用了 -exec 就不再默认打印（默认 -print 只在"没有任何动作"时生效），
  #    所以 `-exec test … \;` 那句会让 find **一个结果都不输出** —— 表现是"明明有备份却说找不到"。
  #    这里改成显式循环：既不看 find 的默认动作，也能顺带要求"必须有 manifest.json"。
  for d in $(find "$BACKUP_ROOT" -maxdepth 2 -mindepth 2 -type d -name "20*" 2>/dev/null | sort -r); do
    [ -f "$d/.FAILED" ] && { echo "（跳过带 .FAILED 的备份：$d）" >&2; continue; }
    [ -f "$d/manifest.json" ] || { echo "（跳过没有清单的目录：$d）" >&2; continue; }
    BACKUP_DIR="$d"; break
  done
fi
[ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ] || { echo "⛔ 找不到可用的备份目录（先跑 _backup.sh）" >&2; exit 2; }

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DRILL_DB="sorders_drill_$STAMP"
DRILL_SECRET=$("$VENV_PY" -c "import secrets;print(secrets.token_urlsafe(48))")

# ---------------------------------------------------------------- 收尾（无论成败都跑）
API_PID=""; REDIS_PID=""
cleanup() {
  local code=$?
  set +e
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null && echo "（已停演练 API 进程 $API_PID）"
  [ -n "$REDIS_PID" ] && kill "$REDIS_PID" 2>/dev/null && echo "（已停演练 Redis 进程 $REDIS_PID）"
  if [ "$KEEP" != "1" ]; then
    IFS=$'\t' read -r DB_USER DB_PASS DB_HOST DB_PORT <<< "$(drill_conn)"
    MYSQL_PWD="$DB_PASS" mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" \
      -e "drop database if exists \`$DRILL_DB\`" 2>/dev/null && echo "（已删演练库 $DRILL_DB）"
    rm -rf "$RUN_DIR"
  else
    echo "（--keep：演练库 $DRILL_DB 与日志 $RUN_DIR 保留，排查完请手动删）"
  fi
  echo "=== 演练结束（exit $code）==="
  exit $code
}
trap cleanup EXIT

# 读 .env 里的连接（口令只进环境变量，不进输出）
drill_conn() {
  "$VENV_PY" - "$ENV_FILE" <<'PYEOF'
import sys, urllib.parse as up
for ln in open(sys.argv[1], encoding="utf-8"):
    ln = ln.strip()
    if ln.startswith("DATABASE_URL="):
        u = up.urlparse(ln.split("=", 1)[1].strip().strip(chr(34)))
        print("\t".join([up.unquote(u.username or ""), up.unquote(u.password or ""),
                          u.hostname or "127.0.0.1", str(u.port or 3306)]))
PYEOF
}

echo "=== 演练开始 $(date -Is) ==="
echo "备份：$BACKUP_DIR"
echo "演练库：$DRILL_DB"

# ---------------------------------------------------------------- ① 恢复
bash "$SCRIPT_DIR/_restore.sh" --backup "$BACKUP_DIR" --target-db "$DRILL_DB"

IFS=$'\t' read -r DB_USER DB_PASS DB_HOST DB_PORT <<< "$(drill_conn)"
export MYSQL_PWD="$DB_PASS"
DRILL_URL="mysql+pymysql://$DB_USER:$DB_PASS@$DB_HOST:$DB_PORT/$DRILL_DB"

# ---------------------------------------------------------------- ② 库内不变式
# 判据全部取自**生产代码**（app.models.enums / api 层的字段定义），不在这里手写枚举值 ——
# 手写的判据一定会和数据模型漂移，而漂移后的"全绿"比红更危险。
echo "--- ② 库内不变式 ---"
( cd "$BACKEND_DIR" && DATABASE_URL="$DRILL_URL" "$VENV_PY" - <<'PYEOF'
import os, sys, pymysql
from app.models.enums import OrderStatus, UserRole, LedgerSource

return_source = LedgerSource.RETURN.value    # 退货红冲的 source 取值也只有一处（模型）

url = os.environ["DATABASE_URL"]
head, dbname = url.rsplit("/", 1)
creds, hostpart = head.split("://", 1)[1].split("@");
user, _, pw = creds.partition(":");
host, _, port = hostpart.partition(":");
conn = pymysql.connect(host=host or "127.0.0.1", port=int(port or 3306), user=user,
                       password=pw, database=dbname, charset="utf8mb4")

def q(sql):
    with conn.cursor() as c:
        c.execute(sql)
        return c.fetchone()[0]

def in_list(enum_cls):
    return ",".join("'" + m.value + "'" for m in enum_cls)

checks = [
    ("orders.status 全部在枚举内",
     f"select count(*) from orders where status is null or status not in ({in_list(OrderStatus)})"),
    ("orders.shipper_id 无孤儿",
     "select count(*) from orders o left join users u on u.id = o.shipper_id "
     "where o.shipper_id is not null and u.id is null"),
    ("ledgers.order_id 无孤儿",
     "select count(*) from ledgers l left join orders o on o.id = l.order_id "
     "where l.order_id is not null and o.id is null"),
    ("ledgers.source 全部在枚举内",
     f"select count(*) from ledgers where source is null or source not in ({in_list(LedgerSource)})"),
    ("users.role 全部在枚举内",
     f"select count(*) from users where role is null or role not in ({in_list(UserRole)})"),
    ("金额非负：orders.freight_fee", "select count(*) from orders where freight_fee < 0"),
    ("金额非负：order_products.line_total", "select count(*) from order_products where line_total < 0"),
    # ⚠️ 第一次真跑演练抓到的事实（写进判据，别再当"数据脏了"）：
    #    账本里**允许**存在负数 total —— 那是退货红冲行，口径写在
    #    `services/order_return.py:151`（"数量、金额、成本快照全为负"），写入口只有那一处。
    #    真正该守的是"**除 RETURN 之外**不许有负数"，以及"RETURN 必须是红冲（≤0）"。
    ("金额：只有退货红冲允许负数（ledgers.total）",
     f"select count(*) from ledgers where total < 0 and source <> '{return_source}'"),
    ("退货红冲口径：RETURN 行必须是负数（total ≤ 0 且 quantity ≤ 0）",
     f"select count(*) from ledgers where source = '{return_source}' and (total > 0 or quantity > 0)"),
    ("时间基准：没有未来时间戳（容一天）",
     "select count(*) from orders where created_at > utc_timestamp() + interval 1 day"),
]

# 软删一致性：**表清单从库里现算**（同时有 is_deleted 与 deleted_at 的表），不手写 ——
# 手写清单的第一版就引用了一个根本不存在的列（order_products.deleted_at），直接查询报错。
soft_tables = []
with conn.cursor() as c:
    c.execute("select table_name from information_schema.columns "
              "where table_schema = database() and column_name = 'is_deleted'")
    a = {r[0] for r in c.fetchall()}
    c.execute("select table_name from information_schema.columns "
              "where table_schema = database() and column_name = 'deleted_at'")
    b = {r[0] for r in c.fetchall()}
soft_tables = sorted(a & b)
for t in soft_tables:
    checks.append((f"软删一致性：{t} 标了 is_deleted 就该有 deleted_at",
                   f"select count(*) from `{t}` where is_deleted = 1 and deleted_at is null"))
print(f"  （软删一致性覆盖 {len(soft_tables)} 张表：{'、'.join(soft_tables)}）")

bad = []
for name, sql in checks:
    try:
        n = q(sql)
    except Exception as e:                                     # noqa: BLE001
        print(f"  ⚠️ {name}：查询失败（{type(e).__name__}: {str(e)[:80]}）")
        bad.append(name)
        continue
    mark = "✅" if n == 0 else "❌"
    if n:
        bad.append(name)
    print(f"  {mark} {name}：违规 {n} 行")
print("INVARIANTS=" + ("OK" if not bad else "FAIL:" + "|".join(bad)))
sys.exit(0 if not bad else 6)
PYEOF
) || { echo "⛔ 库内不变式不通过 —— 恢复出来的库**不是**可用的生产副本" >&2; exit 6; }

if [ "$SKIP_BOOT" = "1" ]; then
  echo "（--skip-boot：跳过启动与接口验证）"
  echo "DRILL=ok(invariants-only)"; exit 0;
fi

# ---------------------------------------------------------------- ③ 真的把后端起起来
echo "--- ③ 启动演练实例（端口 $PORT，隔离 Redis $REDIS_PORT）---"
rm -rf "$RUN_DIR"; mkdir -p "$RUN_DIR"
# 隔离 Redis：只监听本机、不落盘、不给别人用
redis-server --port "$REDIS_PORT" --bind 127.0.0.1 --save "" --appendonly no \
  --daemonize no --dir "$RUN_DIR" > "$RUN_DIR/redis.log" 2>&1 &
REDIS_PID=$!
for i in $(seq 1 20); do
  redis-cli -p "$REDIS_PORT" ping >/dev/null 2>&1 && break
  sleep 0.5
done
redis-cli -p "$REDIS_PORT" ping >/dev/null 2>&1 || { echo "⛔ 演练 Redis 起不来" >&2; cat "$RUN_DIR/redis.log" >&2; exit 7; }

# 演练用的环境：从生产 .env 逐行抄，然后**覆盖**三样（库 / Redis / JWT 密钥）。
# ⛔ JWT 也要换：沿用生产密钥签出来的 token 对**生产**同样有效，等于演练顺手造了一把真钥匙。
grep -vE "^\s*(#|$)" "$ENV_FILE" | grep -vE "^(DATABASE_URL|REDIS_URL|SOCKET_REDIS_URL|JWT_SECRET_KEY)=" > "$RUN_DIR/drill.env"
{
  echo "DATABASE_URL=$DRILL_URL"
  echo "REDIS_URL=redis://127.0.0.1:$REDIS_PORT/0"
  echo "SOCKET_REDIS_URL=redis://127.0.0.1:$REDIS_PORT/0"
  echo "JWT_SECRET_KEY=$DRILL_SECRET"
} >> "$RUN_DIR/drill.env"
chmod 600 "$RUN_DIR/drill.env"

# cwd 必须在**空目录**：data_retention 用相对路径 uploads/，在生产 cwd 里跑会动真图片。
( cd "$RUN_DIR" && set -a && . ./drill.env && set +a && \
  exec "$VENV_PY" -m uvicorn app.main:app --app-dir "$BACKEND_DIR" \
       --host 127.0.0.1 --port "$PORT" --workers 1 ) > "$RUN_DIR/api.log" 2>&1 &
API_PID=$!

echo "等待 /health（最多 90 秒）…"
OK=0
for i in $(seq 1 90); do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "⛔ 演练实例启动即退出 —— 最后 40 行日志：" >&2; tail -40 "$RUN_DIR/api.log" >&2; exit 7;
  fi
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/health" || true)
  if [ "$code" = "200" ]; then OK=1; break; fi
  sleep 1
done
[ "$OK" = "1" ] || { echo "⛔ 90 秒内 /health 没起来 —— 最后 40 行日志：" >&2; tail -40 "$RUN_DIR/api.log" >&2; exit 7; }
echo "  ✅ /health 200：$(curl -s http://127.0.0.1:$PORT/health | head -c 200)"
PATHS=$(curl -s "http://127.0.0.1:$PORT/openapi.json" | "$VENV_PY" -c \
  "import sys,json;print(len(json.load(sys.stdin).get(chr(112)+chr(97)+chr(116)+chr(104)+chr(115),{})))")
echo "  ✅ openapi 加载了 $PATHS 条路径（路由全导入成功＝模型/依赖没有缺失）"

# ---------------------------------------------------------------- ④ 真 token 打只读端点
echo "--- ④ 只读端点（用真实 token）---"
TOKEN=$( cd "$BACKEND_DIR" && DATABASE_URL="$DRILL_URL" JWT_SECRET_KEY="$DRILL_SECRET" "$VENV_PY" - <<'PYEOF'
"""签一个**只在演练实例上有效**的派单员令牌（密钥是演练时新生成的）。"""
from app.database import SessionLocal
from app.models.user import User
from app.services.auth_service import issue_token
db = SessionLocal()
u = db.query(User).filter(User.role == "DISPATCHER").first()
print(issue_token(u) if u else "")
PYEOF
)
if [ -z "$TOKEN" ]; then
  echo "  ⚠️ 演练库里没有派单员账号 —— 跳过带鉴权的只读检查（**不算通过**，记 skipped）"
  API_RESULT=skipped
else
  API_RESULT=ok
  check_get() {
    local url="$1" want="$2" got
    got=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT$url" || true)
    if [ "$got" = "$want" ]; then echo "  ✅ GET $url → $got"; else echo "  ❌ GET $url → $got（期望 $want）"; API_RESULT=fail; fi
  }
  check_get "/api/v1/orders?limit=1" 200
  check_get "/api/v1/products?limit=1" 200
  check_get "/api/v1/ledger/entries?limit=1" 200
  check_get "/api/v1/users?limit=1" 200
fi

if [ "$API_RESULT" = "fail" ]; then
  echo "⛔ 只读端点有非 200 —— 演练失败"; exit 8;
fi
echo "DRILL=ok（不变式通过 + /health 200 + 只读端点 $API_RESULT）"
