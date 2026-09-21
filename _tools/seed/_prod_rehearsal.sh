#!/bin/bash
# 生产造数「彩排」：把 sorders 克隆到 sorders_seedtest，在克隆库上跑种子。
#
# 为什么要有它：造数脚本的 MySQL 方言只被静态审过、**没在 MySQL 上跑过**
# （SQLite 能跑不代表 MySQL 能跑 —— 已修掉一处 datetime() 方言 bug，但没人实测）。
# 在克隆库上先跑一遍小样本，能把"几百单造完才炸"变成"10 秒内就知道"。
#
# ⛔ 绝不碰 sorders 本体：只读它（mysqldump），写的是 sorders_seedtest。
# ⛔ 照片不落进生产 uploads/：cwd 切到 /tmp/rehearsal，脚本里的相对路径
#    （uploads/、static/）就落在临时目录，用完删掉。
# ⛔ 口令一个字节都不打印：从 .env 里取，只回显用户名。
set -e

BACKEND=/opt/SOrders/backend
# systemd 的 `EnvironmentFile=` 指的是**仓库根**这一份，不是 `backend/.env`
# （踩过：写 backend/.env 会 grep 不到 → DBUSER 为空 → GRANT 报
#  "You are not allowed to create a user with GRANT"，看着像权限问题其实是路径错）。
ENVFILE=/opt/SOrders/.env
WORK=/tmp/sorders-rehearsal
DAYS=${DAYS:-20}
ORDERS=${ORDERS:-60}

echo "=== ① 克隆 sorders → sorders_seedtest ==="
mysql -uroot -e "DROP DATABASE IF EXISTS sorders_seedtest; CREATE DATABASE sorders_seedtest CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysqldump -uroot --single-transaction --routines --triggers sorders | mysql -uroot sorders_seedtest
mysql -uroot sorders_seedtest -e "select (select count(*) from orders) as orders, (select count(*) from users) as users, (select count(*) from ledgers) as ledgers, (select count(*) from driver_bills) as bills;"

echo "=== ② 给应用账号授权临时库 ==="
# ⚠️ 键名是**大写** `DATABASE_URL`（pydantic-settings 大小写不敏感，所以 App 读得到；
#    而这里用 grep 就得自己认大小写 —— 踩过一次"取不到库用户"）。
DBURL=$(grep -iE '^database_url=' "$ENVFILE" | head -1 | cut -d= -f2-)
DBUSER=$(echo "$DBURL" | sed -E 's#.*://([^:]+):.*#\1#')
if [ -z "$DBUSER" ] || [ "$DBUSER" = "$DBURL" ]; then
  echo "⛔ 从 $ENVFILE 取不到 database_url 的库用户，中止（不动生产库）"
  exit 1
fi
mysql -uroot -e "GRANT ALL PRIVILEGES ON sorders_seedtest.* TO '$DBUSER'@'%'; FLUSH PRIVILEGES;"
echo "已授权：$DBUSER"

echo "=== ③ 在克隆库上跑种子（${DAYS} 天 / ${ORDERS} 单）==="
# ⚠️ 只替换**路径里的库名**。⛔ 不能用 `s#/sorders#...#` 这种写法：
#    `mysql+pymysql://sorders:pw@host/db` 里 `://sorders` 也含 `/sorders` ——
#    那样会把**用户名**也改掉，报出来的却是 `Access denied for user 'sorders_seedtest'@...`
#    （看着像授权没做，其实是自己把用户名拼坏了）。踩过一次。
SEEDURL=$(echo "$DBURL" | sed -E 's#(://[^/]+/)[^?]*#\1sorders_seedtest#')
echo "目标库：$(echo "$SEEDURL" | sed -E 's#(://[^:]+):[^@]*@#\1:***@#')"
rm -rf "$WORK"; mkdir -p "$WORK"
cd "$WORK"
# `SEED_PY` 给了就用那个文件（本地还没提交的新版：先传 /tmp 再跑，不碰部署树）；
# 没给就用部署树里的 `scripts.seed_demo_data`（正式发版后的跑法）。
if [ -n "${SEED_PY:-}" ]; then
  echo "用指定的脚本文件：$SEED_PY"
  PYTHONPATH="$BACKEND" DATABASE_URL="$SEEDURL" \
    "$BACKEND/.venv/bin/python" "$SEED_PY" --reset --yes --keep 13800000004 --days "$DAYS" --orders "$ORDERS" 2>&1 \
    | tee /tmp/sorders-seed.log | tail -45
else
  PYTHONPATH="$BACKEND" DATABASE_URL="$SEEDURL" \
    "$BACKEND/.venv/bin/python" -m scripts.seed_demo_data --reset --yes --keep 13800000004 --days "$DAYS" --orders "$ORDERS" 2>&1 \
    | tee /tmp/sorders-seed.log | tail -45
fi
echo "（完整日志留在 /tmp/sorders-seed.log）"

echo "=== ④ 克隆库结果 ==="
mysql -uroot sorders_seedtest -e "select (select count(*) from orders) as orders, (select count(*) from ledgers) as ledgers, (select count(*) from notifications) as notifs, (select count(*) from users) as users, (select count(*) from driver_bills) as bills;"

echo "=== ⑤ 清理（临时库 + 临时目录）==="
mysql -uroot -e "DROP DATABASE sorders_seedtest;"
rm -rf "$WORK"
echo "彩排完成，临时库与临时目录都已删除。生产库全程只读。"
