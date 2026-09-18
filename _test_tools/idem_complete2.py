# -*- coding: utf-8 -*-
"""并发complete幂等v2: 带图完成"""
import sys, asyncio, json, io
sys.stdout.reconfigure(encoding='utf-8')
import aiohttp

BASE = 'http://127.0.0.1:8000'

async def main():
    conn = aiohttp.TCPConnector(limit=0, limit_per_host=0, ssl=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        async def login(phone):
            async with sess.post(BASE + "/api/v1/auth/login", json={"phone": phone, "password": "pass12345"}, timeout=10) as r:
                return (await r.json()).get("access_token")
        tok_d = await login("13800000001")
        tok_s = await login("13800000002")
        tok_drv = await login("13800000003")
        H_D = {"Authorization": f"Bearer {tok_d}"}
        H_S = {"Authorization": f"Bearer {tok_s}"}
        H_DRV = {"Authorization": f"Bearer {tok_drv}"}

        body = {"lines": [{"product_id": 1, "product_name_snapshot": "双写测试2", "quantity": 5, "unit_price": "23.00"}], "address_detail": "双写地址2", "contact_boss_phone": "13800000001"}
        async with sess.post(BASE + "/api/v1/orders", headers=H_S, json=body, timeout=10) as r:
            oid = (await r.json())["id"]
        async with sess.post(BASE + f"/api/v1/orders/{oid}/assign", headers=H_D, json={"driver_id": 3, "freight_fee": "8.00"}, timeout=10) as r:
            print("assign:", r.status)
        async with sess.post(BASE + f"/api/v1/orders/{oid}/driver-ack", headers=H_DRV, timeout=10) as r:
            print("ack:", r.status)

        # 准备图片（png字节）
        png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c63600000020001a4d345580000000049454e44ae426082")
        # 用 complete-with-upload 带图完成（multipart）
        # 先试普通 complete + 先上传照片
        files = [("files", ("p1.png", io.BytesIO(png), "image/png"))]
        async with sess.post(BASE + f"/api/v1/orders/{oid}/delivery-photos", headers=H_DRV, files=files, timeout=15) as r:
            print("upload photo:", r.status, (await r.text())[:100])
        # 然后并发2次complete
        import asyncio.gather
        async def do_complete():
            async with sess.post(BASE + f"/api/v1/orders/{oid}/complete", headers=H_DRV, json={"payment": "cash"}, timeout=15) as r:
                return r.status, (await r.text())[:150]
        results = await asyncio.gather(do_complete(), do_complete())
        print("并发complete结果:", results)

        async with sess.get(BASE + "/api/v1/orders/" + str(oid), headers=H_D, timeout=10) as r:
            od = await r.json()
        print("订单状态:", od.get("status"))

        async with sess.get(BASE + "/api/v1/ledger/entries?shipper_id=2", headers=H_D, timeout=10) as r:
            entries = await r.json()
        gle = [e for e in (entries if isinstance(entries, list) else []) if e.get("order_id") == oid]
        print(f"账本条目: {len(gle)} (期望1) ->", [(e["source"], e["total"]) for e in gle])

        async with sess.get(BASE + "/api/v1/driver-bills?driver_id=3", headers=H_D, timeout=10) as r:
            bills = await r.json()
        gb = [b for b in (bills if isinstance(bills, list) else []) if b.get("order_id") == oid]
        print(f"司机账单: {len(gb)} (期望1) ->", [(b["amount"], b["status"]) for b in gb])

asyncio.run(main())