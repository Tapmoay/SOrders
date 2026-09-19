"""看一眼地址库与基线（真机 E2E 前后各跑一次，逐字段核对）。

用法：python _tools/ai/_addr_dump.py
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
c = sqlite3.connect(ROOT / "backend/sorders.db")

print("== shipper_addresses ==")
for r in c.execute(
    "select id,shipper_id,receiver_name,phone,detail_address,origin_address,"
    "remark,is_deleted,address_lat,address_lng from shipper_addresses order by id"
):
    print(r)

print("\n== 订单（SOTEST*，末 3 条）==")
for r in c.execute(
    "select id,order_no,freight_fee,status from orders where order_no like 'SOTEST%' "
    "order by id desc limit 3"
):
    print(r)

print("\n== 商品（红富士苹果）==")
for r in c.execute("select id,name,default_unit_price,is_active from products where name like '%红富士%'"):
    print(r)
