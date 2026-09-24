#!/usr/bin/env bash
# _backup.sh —— 生产机的备份入口（**唯一一条**写备份产物的路径）。
#
# 为什么要有它（报告 §3 / R2）：
#   改造前生产机上只有一堆手敲的 /root/backup-*.sql.gz —— 没有目录结构、没有清单、
#   没有保留期、没有校验，"上次那份备份是什么时候的、恢复出来对不对"全靠记忆。
#   报告的原话是：不能「出问题 → 好像以前有个 mysqldump」。
#
# 三件它必须做到的事：
#   1. **每次都写清单**（manifest.json）：时间、发起人、代码版本、库行数、产物 sha256 ——
#      没有清单的备份在恢复现场等于没有（你无法证明它对应哪一版代码）。
#   2. **当场校验**产物（gzip -t + sha256 + 关键表行数），失败就非零退出。
#      "退出码 0" 不等于"备份可用"，这一点报告专门点了名。
#   3. **只在自己的目录里做保留期清理**，且目录名必须带 kind —— 手滑删错目录的代价太大。
#
# 用法（在生产机上）：
#   bash _backup.sh --kind daily            # 只备库（每天可多次，便宜）
#   bash _backup.sh --kind weekly           # 库 + 上传文件（百 MB 级，别每天做）
#   bash _backup.sh --kind pre_release --note "上线 v0.2.5"
#   参数：--keep-daily N（默认 14）--keep-weekly N（默认 8）--keep-pre N（默认 20）
#
# ⛔ 口令纪律：库口令从 /opt/SOrders/.env 现读，经 MYSQL_PWD 传给客户端，
#    **绝不出现在命令行**（ps 可见）也**绝不写进任何产物**。
set -euo pipefail

APP_DIR=/opt/SOrders
ENV_FILE="$APP_DIR/.env"
UPLOADS_DIR="$APP_DIR/backend/uploads"
BACKUP_ROOT=/opt/sorders-backup
PY=/opt/SOrders/backend/.venv/bin/python
[ -x "$PY" ] || PY=python3

KIND=daily
NOTE=""
KEEP_DAILY=14; KEEP_WEEKLY=8; KEEP_PRE=20

while [ $# -gt 0 ]; do
  case "$1" in
    --kind) KIND="$2"; shift 2 ;;
    --note) NOTE="$2"; shift 2 ;;
    --keep-daily) KEEP_DAILY="$2"; shift 2 ;;
    --keep-weekly) KEEP_WEEKLY="$2"; shift 2 ;;
    --keep-pre) KEEP_PRE="$2"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

case "$KIND" in
  daily|weekly|pre_release|manual) ;;
  *) echo "--kind 只认 daily/weekly/pre_release/manual，收到：$KIND" >&2; exit 2 ;;
esac

# 上传文件只在 weekly / pre_release 里备（187MB 级；每天备会把盘吃光，而上传文件是**不可再生**的，
# 所以它必须有，只是不需要每天有）。
WITH_UPLOADS=0
[ "$KIND" = "weekly" ] && WITH_UPLOADS=1
[ "$KIND" = "pre_release" ] && WITH_UPLOADS=1
[ "$KIND" = "manual" ] && WITH_UPLOADS=1

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST="$BACKUP_ROOT/$KIND/$STAMP"
mkdir -p "$DEST"
# 一句 trap：**任何**中途失败都要留下 .FAILED 标记 —— 半个备份比没有备份更危险
# （恢复的人会以为它是完整的）。
cleanup_fail() {
  local code=$?
  if [ $code -ne 0 ]; then
    echo "{\"status\":\"failed\",\"exit\":$code}" > "$DEST/.FAILED"
    echo "⛔ 备份失败（exit $code），已在 $DEST/.FAILED 留标记；这个目录不要拿去恢复。" >&2
  fi
  exit $code
}
trap cleanup_fail EXIT

echo "=== 备份开始 kind=$KIND -> $DEST ==="

# ---------------------------------------------------------------- 读库连接（不回显口令）
if [ ! -f "$ENV_FILE" ]; then echo "找不到 $ENV_FILE" >&2; exit 2; fi
DB_TSV=$("$PY" - "$ENV_FILE" <<\PYEOF
import sys, urllib.parse as up
url = ""
for ln in open(sys.argv[1], encoding="utf-8"):
    ln = ln.strip()
    if ln.startswith("DATABASE_URL="):
        url = ln.split("=", 1)[1].strip().strip(chr(34)).strip(chr(39))
u = up.urlparse(url)
# ⚠️ urlparse **不做**百分号解码：口令里有 @ : / % 时必须自己 unquote，
#    否则 MYSQL_PWD 拿到的是 "p%40ss" 这种形态 → Access denied（现场最容易被误判成"口令变了"）。
print("\t".join([up.unquote(u.username or ""), up.unquote(u.password or ""),
                  u.hostname or "127.0.0.1", str(u.port or 3306),
                  (u.path or "/sorders").lstrip("/")]))
PYEOF
)
IFS=$'\t' read -r DB_USER DB_PASS DB_HOST DB_PORT DB_NAME <<< "$DB_TSV"
export MYSQL_PWD="$DB_PASS"        # ⛔ 走环境变量，不走命令行（ps 看不见）

echo "库：$DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -N -B -e "select 1" >/dev/null

# ---------------------------------------------------------------- 备份前的库事实（进清单）
COUNTS_BEFORE=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -N -B -e "
  select concat_ws(',',
    (select count(*) from $DB_NAME.orders),
    (select count(*) from $DB_NAME.ledgers),
    (select count(*) from $DB_NAME.users),
    (select count(*) from $DB_NAME.products),
    (select count(*) from information_schema.tables where table_schema='$DB_NAME'));" )
IFS=',' read -r N_ORDERS N_LEDGERS N_USERS N_PRODUCTS N_TABLES <<< "$COUNTS_BEFORE"
echo "行数：orders=$N_ORDERS ledgers=$N_LEDGERS users=$N_USERS products=$N_PRODUCTS tables=$N_TABLES"

# ---------------------------------------------------------------- 1. 数据库
echo "--- mysqldump ---"
# --single-transaction：InnoDB 一致性快照，**不锁表**（生产在跑，不能锁）
# --set-gtid-purged=OFF：GTID 没开，带上会在恢复时报错（踩过的坑写在这里省得下次再踩）
# --no-tablespaces：应用账号没有 PROCESS 权限时也能导
mysqldump -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" \
  --single-transaction --quick --routines --triggers --events \
  --default-character-set=utf8mb4 --hex-blob --set-gtid-purged=OFF --no-tablespaces \
  "$DB_NAME" | gzip -6 > "$DEST/db.sql.gz"
gzip -t "$DEST/db.sql.gz"
DB_BYTES=$(stat -c %s "$DEST/db.sql.gz")
if [ "$DB_BYTES" -lt 10240 ]; then
  echo "⛔ db.sql.gz 只有 $DB_BYTES 字节 —— 太小了，按失败处理（空库/连错库都会这样）" >&2
  exit 3
fi
echo "db.sql.gz：$DB_BYTES 字节"

# ---------------------------------------------------------------- 2. 上传文件（按需）
UP_BYTES=0; UP_FILES=0
if [ "$WITH_UPLOADS" = "1" ]; then
  if [ -d "$UPLOADS_DIR" ]; then
    echo "--- uploads.tar.gz ---"
    tar -C "$(dirname "$UPLOADS_DIR")" -czf "$DEST/uploads.tar.gz" "$(basename "$UPLOADS_DIR")"
    gzip -t "$DEST/uploads.tar.gz"
    UP_BYTES=$(stat -c %s "$DEST/uploads.tar.gz")
    UP_FILES=$(find "$UPLOADS_DIR" -type f | wc -l)
    echo "uploads.tar.gz：$UP_BYTES 字节 / $UP_FILES 个文件"
  else
    echo "⚠️ $UPLOADS_DIR 不存在 —— 上传文件没备上（这一项在清单里记 null，不记 0）" >&2
    UP_BYTES=null
  fi
fi

# ---------------------------------------------------------------- 3. 代码版本（恢复时对齐用）
GIT_COMMIT=$(cd "$APP_DIR" && git rev-parse HEAD 2>/dev/null || echo unknown)
GIT_BRANCH=$(cd "$APP_DIR" && git branch --show-current 2>/dev/null || echo unknown)
GIT_DIRTY=$(cd "$APP_DIR" && git status --short 2>/dev/null | wc -l)
SCHEMA_VER=$(mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -N -B -e \
  "select coalesce(max(version),0) from $DB_NAME.schema_versions" 2>/dev/null || echo none)

# ---------------------------------------------------------------- 4. 清单（sha256 必须有）
"$PY" - "$DEST" "$KIND" "$NOTE" "$GIT_COMMIT" "$GIT_BRANCH" "$GIT_DIRTY" \
        "$N_ORDERS" "$N_LEDGERS" "$N_USERS" "$N_PRODUCTS" "$N_TABLES" \
        "$UP_FILES" "$UP_BYTES" "$SCHEMA_VER" "$DB_USER" "$DB_HOST" "$DB_PORT" "$DB_NAME" <<\PYEOF
import hashlib, json, os, platform, socket, sys, datetime
(dest, kind, note, commit, branch, dirty, n_orders, n_ledgers, n_users, n_products,
 n_tables, up_files, up_bytes, schema_ver, db_user, db_host, db_port, db_name) = sys.argv[1:19]

def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

arts = {}
for name in ("db.sql.gz", "uploads.tar.gz"):
    p = os.path.join(dest, name)
    if os.path.exists(p):
        arts[name] = {"bytes": os.path.getsize(p), "sha256": sha256(p)}
m = {
    "kind": kind, "note": note, "created_utc": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
    "host": socket.gethostname(), "backup_dir": dest,
    "code": {"commit": commit, "branch": branch, "dirty_files": int(dirty or 0)},
    "db": {"user": db_user, "host": db_host, "port": int(db_port), "name": db_name,
           "schema_version": (None if schema_ver == "none" else int(schema_ver or 0)),
           "rows": {"orders": int(n_orders), "ledgers": int(n_ledgers),
                    "users": int(n_users), "products": int(n_products), "tables": int(n_tables)}},
    "uploads": (None if up_bytes == "null" else {"bytes": int(up_bytes), "files": int(up_files)}),
    "artifacts": arts,
    "server": {"python": platform.python_version(), "uname": platform.platform()},
}
with open(os.path.join(dest, "manifest.json"), "w", encoding="utf-8") as f:
    json.dump(m, f, ensure_ascii=False, indent=2)
with open(os.path.join(dest, "SHA256SUMS"), "w", encoding="utf-8") as f:
    for name, a in arts.items():
        f.write(f"{a['sha256']}  {name}\n")
print(json.dumps({"status": "ok", "dir": dest, "artifacts": {k: v["bytes"] for k, v in arts.items()}},
                 ensure_ascii=False))
PYEOF

# 最后把清单也纳入校验（清单本身是恢复现场唯一的路标）
(cd "$DEST" && sha256sum -c SHA256SUMS >/dev/null) && echo "✅ sha256 校验通过"

# ---------------------------------------------------------------- 5. 保留期（只动自己的目录）
case "$BACKUP_ROOT" in
  /opt/*) ;;
  *) echo "⛔ BACKUP_ROOT=$BACKUP_ROOT 不在 /opt 下，拒绝做保留期清理" >&2; exit 4 ;;
esac
prune() {
  local kind="$1" keep="$2"
  local dirs
  mkdir -p "$BACKUP_ROOT/$kind"
  # ⚠️ 实测踩到（第一次真跑备份就撞上）：目录不存在时 find 返回非零，而 dirs=$(find …) 的
  #    退出码就是 find 的 —— 在 set -e 下这会**把一次已经成功的备份判成失败**，
  #    trap 再打上 .FAILED，于是那份完好的备份反而恢复不了。所以结尾必须 || true。
  dirs=$(find "$BACKUP_ROOT/$kind" -maxdepth 1 -mindepth 1 -type d -name "20*" \
         2>/dev/null | sort -r || true)
  local i=0
  while IFS= read -r d; do
    [ -z "$d" ] && continue
    i=$((i + 1))
    if [ "$i" -gt "$keep" ]; then
      case "$d" in
        "$BACKUP_ROOT"/*) rm -rf -- "$d"; echo "保留期清理：$d" ;;
        *) echo "⛔ 拒绝删除不在备份根下的路径：$d" >&2 ;;
      esac
    fi
  done <<< "$dirs"
}
prune daily "$KEEP_DAILY"
prune weekly "$KEEP_WEEKLY"
prune pre_release "$KEEP_PRE"

echo "=== 备份完成：$DEST ==="
du -sh "$DEST"
trap - EXIT
