# -*- coding: utf-8 -*-
"""端到端功能回归: 下单→派单→接单→完成→账本→报表 (完整链路)"""
import sys, asyncio, io, json, time
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

        step_results = []
        def ok(name, cond, info=""):
            step_results.append((name, "PASS" if cond else "FAIL", info))

        # Step1: 货主下单
        body = {"lines": [{"product_id": 1, "product_name_snapshot": "端到端商品", "quantity": 3, "unit_price": "23.50"}], "address_detail": "端到端地址", "contact_boss_phone": "13800000001", "remark": "端到端回归"}
        async with sess.post(BASE + "/api/v1/orders", headers=H_S, json=body, timeout=10) as r:
            od = await r.json()
            oid = od.get("id")
        ok("1 货主下单", r.status == 201 and od.get("status") == "PENDING_DISPATCH", f"st={r.status} oid={oid}")

        # Step2: 派单员待派池可见
        async with sess.get(BASE + "/api/v1/orders?status=PENDING_DISPATCH&shipper_id=2", headers=H_D, timeout=10) as r:
            pend = await r.json()
        ok("2 派单员待派池", any(o.get("id") == oid for o in (pend if isinstance(pend, list) else [])), f"pool={len(pend) if isinstance(pend, list) else pend}")

        # Step3: 派单
        async with sess.post(BASE + f"/api/v1/orders/{oid}/assign", headers=H_D, json={"driver_id": 3, "freight_fee": "8.00", "collect_cash": False}, timeout=10) as r:
            od2 = await r.json()
        ok("3 派单", r.status == 200 and od2.get("status") == "DISPATCHED", f"st={r.status}")

        # Step4: 司机接单
        async with sess.post(BASE + f"/api/v1/orders/{oid}/driver-ack", headers=H_DRV, timeout=10) as r:
            od3 = await r.json()
        ok("4 司机接单", r.status == 200 and od3.get("status") == "ACCEPTED", f"st={r.status}")

        # Step5: 司机完成（带图）
        png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c63600000020001a4d345580000000049454e44ae426082")
        form = aiohttp.FormData()
        form.add_field("files", io.BytesIO(png), filename="p.png", content_type="image/png")
        form.add_field("payment", "arrears")
        async with sess.post(BASE + f"/api/v1/orders/{oid}/complete-with-upload", headers=H_DRV, data=form, timeout=20) as r:
            od4 = await r.json()
        ok("5 司机完成(挂账)", r.status == 200 and od4.get("status") == "DELIVERED", f"st={r.status}")

        # Step6: 账本自动同步
        async with sess.get(BASE + "/api/v1/ledger/entries?shipper_id=2", headers=H_D, timeout=10) as r:
            entries = await r.json()
        gle = [e for e in (entries if isinstance(entries, list) else []) if e.get("order_id") == oid]
        ok("6 账本入账", len(gle) == 1 and gle[0].get("total") == "70.5000", f"entries={len(gle)} total={gle[0].get("total") if gle else None}")

        # Step7: 司机账单
        async with sess.get(BASE + "/api/v1/driver-bills?driver_id=3", headers=H_D, timeout=10) as r:
            bills = await r.json()
        gb = [b for b in (bills if isinstance(bills, list) else []) if b.get("order_id") == oid]
        ok("7 司机账单", len(gb) == 1 and gb[0].get("amount") == "8.00", f"bills={len(gb)}")

        # Step8: 报表营业额
        async with sess.get(BASE + "/api/v1/reports/turnover?mode=day&date=2026-09-04", headers=H_D, timeout=10) as r:
            rep = await r.json()
        ok("8 报表(有数据)", r.status == 200 and rep.get("total_amount") != None, f"st={r.status}")

        # Step9: 货主消息通知
        async with sess.get(BASE + "/api/v1/notifications", headers=H_S, timeout=10) as r:
            notifs = await r.json()
        cnt = len(notifs) if isinstance(notifs, list) else 0
        ok("9 消息中心", cnt > 0, f"notifs={cnt}")

        # Step10: 操作日志
        async with sess.get(BASE + "/api/v1/operation-logs?limit=10", headers=H_D, timeout=10) as r:
            logs = await r.json()
        ok("10 操作日志", r.status == 200 and isinstance(logs, list), f"st={r.status}")

        for name, result, info in step_results:
            print(f"[{result}] {name} {info}")
        fails = [s for s in step_results if s[1] == "FAIL"]
        print(f"\n结果: {len(step_results) - len(fails)}/{len(step_results)} PASS")

asyncio.run(main())