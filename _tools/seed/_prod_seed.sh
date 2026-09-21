#!/bin/bash
# 在生产上**正式**灌数（不是彩排）。用法：bash /root/sorders-seed.sh
#
# ⛔ 为什么必须 source `/opt/SOrders/.env`（这一步漏了会出最危险的一类事故）：
#    服务是 systemd 起的，DB 地址来自 `EnvironmentFile=/opt/SOrders/.env`；
#    而**手动跑**这个脚本时没有那份环境 → pydantic 会退回 `config.py` 的默认值（sqlite 文件），
#    于是"灌数"灌进一个本机 sqlite、生产一点没动，而屏幕上一切正常。所以：
#    ① 先 source 环境；② 再断言 DATABASE_URL 是 mysql，不是就直接中止。
set -e
cd /opt/SOrders/backend

set -a; . /opt/SOrders/.env; set +a

case "${DATABASE_URL:-}" in
  mysql*) ;;
  *) echo "⛔ DATABASE_URL 不是 MySQL（当前前缀：$(echo "${DATABASE_URL:-<空>}" | cut -c1-24)…）——中止，绝不往错的库灌数"; exit 1 ;;
esac
echo "目标库 : …$(echo "$DATABASE_URL" | sed -E 's#.*@##')"   # 只打 @ 之后，不打印口令

DAYS=${DAYS:-120}
echo "开始灌数：近 ${DAYS} 天（订单数用脚本默认）"
.venv/bin/python -m scripts.seed_demo_data --reset --yes --keep 13800000004 --days "$DAYS" --report 2>&1 \
  | tee /tmp/prod-seed.log | tail -60
echo "（完整日志：/tmp/prod-seed.log）"
