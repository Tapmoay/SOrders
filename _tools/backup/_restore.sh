#!/usr/bin/env bash
# _restore.sh —— 从备份目录恢复数据库（**恢复路径的唯一入口**）。
#
# 为什么单独成脚本、且**默认拒绝恢复生产库**：
#   报告 §3 的原话是"恢复没有实战演练"，而演练的第一前提是**恢复不能误伤生产**。
#   所以这里的默认目标是**临时库**；要覆盖生产库必须显式给 --target-db sorders --i-know。
#
# 用法：
#   bash _restore.sh --backup /opt/sorders-backup/daily/20260924T193000Z --target-db sorders_drill_20260924
#   bash _restore.sh --backup <dir> --target-db sorders --i-know      # ⛔ 覆盖生产库
#   可选：--no-drop（目标库已存在时报错，不做 DROP）
#
# 它做的三件事：
#   1. 校验备份本身（.FAILED 标记 / SHA256SUMS / gzip -t）——
#      **宁可拒绝恢复，也不要恢复半份**；
#   2. 建库 → 导入 → 当场核对表数与关键表行数（与 manifest 对比）；
#   3. 打印恢复后的核对结果（口令一律不出现在输出里）。
set -euo pipefail

ENV_FILE=/opt/SOrders/.env
BACKUP_ROOT=/opt/sorders-backup
PY=/opt/SOrders/backend/.venv/bin/python
[ -x "$PY" ] || PY=python3

BACKUP_DIR=""; TARGET_DB=""; I_KNOW=0; DROP=1
while [ $# -gt 0 ]; do
  case "$1" in
    --backup) BACKUP_DIR="$2"; shift 2 ;;
    --target-db) TARGET_DB="$2"; shift 2 ;;
    --i-know) I_KNOW=1; shift ;;
    --no-drop) DROP=0; shift ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

[ -n "$BACKUP_DIR" ] || { echo "缺 --backup <备份目录>" >&2; exit 2; }
[ -n "$TARGET_DB" ] || { echo "缺 --target-db <库名>" >&2; exit 2; }
[ -d "$BACKUP_DIR" ] || { echo "备份目录不存在：$BACKUP_DIR" >&2; exit 2; }

# ---------------------------------------------------------------- 0. 生产库保护（顺序很重要：先挡，再干活）
PROD_DB=$("$PY" - "$ENV_FILE" <<'PYEOF'
import sys, urllib.parse as up
for ln in open(sys.argv[1], encoding="utf-8"):
    ln = ln.strip()
    if ln.startswith("DATABASE_URL="):
        print((up.urlparse(ln.split("=", 1)[1].strip().strip(chr(34))).path or "/sorders").lstrip("/"))
PYEOF
)
if [ "$TARGET_DB" = "$PROD_DB" ] && [ "$I_KNOW" != "1" ]; then
  echo "⛔ 目标库就是生产库（$PROD_DB）。真要覆盖生产库请显式加 --i-know，" >&2
  echo "   并且**先**对当前生产库做一次 _backup.sh --kind pre_release（否则覆盖掉就没有退路了）。" >&2
  exit 3
fi
case "$TARGET_DB" in
  ""|*[!A-Za-z0-9_]*) echo "⛔ 库名只允许字母数字下划线：$TARGET_DB" >&2; exit 3 ;;
esac

# ---------------------------------------------------------------- 1. 校验备份可用性
[ ! -f "$BACKUP_DIR/manifest.json" ] && { echo "⛔ 缺 manifest.json（不是本脚本产出的备份）" >&2; exit 4; }
if [ -f "$BACKUP_DIR/.FAILED" ]; then
  echo "⛔ 这份备份带 .FAILED 标记（上次没跑完），拒绝用它恢复：" >&2
  cat "$BACKUP_DIR/.FAILED" >&2; exit 4;
fi
[ -f "$BACKUP_DIR/db.sql.gz" ] || { echo "⛔ 缺 db.sql.gz" >&2; exit 4; }
(cd "$BACKUP_DIR" && sha256sum -c SHA256SUMS >/dev/null) || { echo "⛔ sha256 校验不通过（产物损坏）" >&2; exit 4; }
gzip -t "$BACKUP_DIR/db.sql.gz" || { echo "⛔ db.sql.gz 不是完好的 gzip" >&2; exit 4; }
echo "✅ 备份校验通过：$BACKUP_DIR"

# ---------------------------------------------------------------- 2. 建库 + 导入
DB_TSV=$("$PY" - "$ENV_FILE" <<'PYEOF'
import sys, urllib.parse as up
for ln in open(sys.argv[1], encoding="utf-8"):
    ln = ln.strip()
    if ln.startswith("DATABASE_URL="):
        u = up.urlparse(ln.split("=", 1)[1].strip().strip(chr(34)))
        print("\t".join([up.unquote(u.username or ""), up.unquote(u.password or ""),
                          u.hostname or "127.0.0.1", str(u.port or 3306)]))
PYEOF
)
IFS=$'\t' read -r DB_USER DB_PASS DB_HOST DB_PORT <<< "$DB_TSV"
export MYSQL_PWD="$DB_PASS"

mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -e "select 1" >/dev/null
# DROP 前再确认一次：库名必须以 sorders_drill_ 开头，或者是生产库且带了 --i-know。
if [ "$DROP" = "1" ]; then
  case "$TARGET_DB" in
    sorders_drill_*|"$PROD_DB") ;;
    *) echo "⛔ 拒绝 DROP 非演练库：$TARGET_DB（要恢复成别的名字请加 --no-drop 并自己建库）" >&2; exit 3 ;;
  esac
  mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -e "drop database if exists \`$TARGET_DB\`"
fi
mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" -e \
  "create database if not exists \`$TARGET_DB\` character set utf8mb4 collate utf8mb4_unicode_ci"
echo "--- 导入中（大库需要几分钟，别中断）---"
gzip -dc "$BACKUP_DIR/db.sql.gz" | mysql -h "$DB_HOST" -P "$DB_PORT" -u "$DB_USER" "$TARGET_DB"

# ---------------------------------------------------------------- 3. 当场核对（与 manifest 比）
"$PY" - "$BACKUP_DIR/manifest.json" "$TARGET_DB" "$DB_HOST" "$DB_PORT" "$DB_USER" "$DB_PASS" <<'PYEOF'
import json, sys
mf, target, host, port, user, pw = sys.argv[1:7]
m = json.load(open(mf, encoding="utf-8"))
import subprocess

def q(sql):
    r = subprocess.run(["mysql", "-h", host, "-P", port, "-u", user, "-N", "-B", "-e", sql],
                       capture_output=True, text=True, env={"MYSQL_PWD": pw, "PATH": "/usr/bin:/bin:/usr/sbin"})
    if r.returncode != 0:
        return None, r.stderr.strip()
    return r.stdout.strip(), None

exp = m["db"]["rows"]
got = {}
for t in ("orders", "ledgers", "users", "products"):
    v, err = q(f"select count(*) from {target}.{t}")
    got[t] = int(v) if v and v.isdigit() else None
v, err = q(f"select count(*) from information_schema.tables where table_schema='{target}'")
got["tables"] = int(v) if v and v.isdigit() else None

print(f"--- 恢复核对（{target}）---")
bad = []
for k in ("orders", "ledgers", "users", "products", "tables"):
    a, b = exp.get(k), got.get(k)
    mark = "✅" if a == b else "⚠️"
    if a != b:
        bad.append(k)
    print(f"  {mark} {k}: 备份时 {a} ｜ 恢复后 {b}")
print("CONCLUSION=" + ("OK" if not bad else "MISMATCH:" + ",".join(bad)))
if bad:
    sys.exit(5)
PYEOF

echo "=== 恢复完成：$TARGET_DB ==="
echo "清理演练库：mysql -e \"drop database \`$TARGET_DB\`\"（或交给 _drill.sh 自动清）"
