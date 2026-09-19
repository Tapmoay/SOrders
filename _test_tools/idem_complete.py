# -*- coding: utf-8 -*-
"""并发complete幂等验证：同一单并行2次complete"""
import sys, asyncio, json, time
sys.stdout.reconfigure(encoding='utf-8')
import aiohttp

BASE = 'http://127.0.0.1:8000'

async def main():
    conn = aiohttp.TCPConnector(limit=0, limit_per_host=0, ssl=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        # 登录
        async def login(phone):
            async with sess.post(BASE + "/api/v1/auth/login", json={"phone": phone, "password": "pass12345"}, timeout=10) as r:
                return (await r.json()).get("access_token")
        tok_d = await login("13800000001")
        tok_s = await login("13800000002")
        tok_drv = await login("13800000003")
        H_D = {"Authorization": f"Bearer {tok_d}"}
        H_S = {"Authorization": f"Bearer {tok_s}"}
        H_DRV = {"Authorization": f"Bearer {tok_drv}"}

        # 造单：下单→派单→接单
        body = {"lines": [{"product_id": 1, "product_name_snapshot": "双写测试", "quantity": 5, "unit_price": "23.00"}], "address_detail": "双写地址", "contact_boss_phone": "13800000001"}
        async with sess.post(BASE + "/api/v1/orders", headers=H_S, json=body, timeout=10) as r:
            oid = (await r.json())["id"]
        print("订单:", oid)
        async with sess.post(BASE + f"/api/v1/orders/{oid}/assign", headers=H_D, json={"driver_id": 3, "freight_fee": "8.00"}, timeout=10) as r:
            print("assign:", r.status)
        async with sess.post(BASE + f"/api/v1/orders/{oid}/driver-ack", headers=H_DRV, timeout=10) as r:
            print("ack:", r.status)

        # 并发 2 次 complete
        results = []
        for _ in range(2):
            async with sess.post(BASE + f"/api/v1/orders/{oid}/complete", headers=H_DRV, json={"payment": "cash"}, timeout=10) as r:
                results.append((r.status, (await r.text())[:100]))
        print("并发complete:", results)

        # 验证账本（是否重复入账）
        async with sess.get(BASE + "/api/v1/ledger/entries?shipper_id=2", headers=H_D, timeout=10) as r:
            entries = await r.json()
        gle = [e for e in entries if isinstance(entries, list) and e.get("order_id") == oid]
        print(f"账本条目: {len(gle)} (期望1) -> ", [(e["source"], e["total"]) for e in gle])

        # 验证司机账单
        async with sess.get(BASE + "/api/v1/driver-bills?driver_id=3", headers=H_D, timeout=10) as r:
            bills = await r.json()
        gb = [b for b in (bills if isinstance(bills, list) else []) if b.get("order_id") == oid]
        print(f"司机账单: {len(gb)} (期望1) -> ", [(b["amount"], b["status"]) for b in gb])

asyncio.run(main())