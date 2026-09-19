# -*- coding: utf-8 -*-
"""并发下单复现500并抓取错误消息"""
import sys, json, asyncio, random
sys.stdout.reconfigure(encoding='utf-8')
import aiohttp

BASE = "http://127.0.0.1:8000"

async def main():
    conn = aiohttp.TCPConnector(limit=0, limit_per_host=0, ssl=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        # 预登录 20 个货主账号
        toks = []
        for i in range(1, 21):
            phone = f"1391000{i:04d}"
            async with sess.post(BASE + "/api/v1/auth/login", json={"phone": phone, "password": "pass12345"}, timeout=10) as r:
                try:
                    toks.append((phone, (await r.json()).get("access_token")))
                except:
                    toks.append((phone, None))
        print("预登录完成:", sum(1 for _, t in toks if t), "/", len(toks))

        async def do_order(phone, tok):
            h = {"Authorization": f"Bearer {tok}"}
            body = {"lines": [{"product_id": random.randint(1, 8), "product_name_snapshot": "并发复现", "quantity": 1, "unit_price": "10.00"}], "address_detail": "并发复现地址", "contact_boss_phone": phone}
            async with sess.post(BASE + "/api/v1/orders", headers=h, json=body, timeout=15) as r:
                txt = await r.text()
                return r.status, txt[:300]

        # 波次并发：20 并发同时下单，重复 5 轮
        results = []
        for wave in range(5):
            batch = [asyncio.create_task(do_order(p, t)) for p, t in toks]
            res = await asyncio.gather(*batch)
            for st, txt in res:
                results.append((st, txt))
            await asyncio.sleep(0.5)
        # 汇总
        from collections import Counter
        cnt = Counter(st for st, _ in results)
        print("状态分布:", dict(cnt))
        errs = [(st, txt) for st, txt in results if st not in (200, 201)]
        print(f"错误数: {len(errs)}")
        for st, txt in errs[:8]:
            print(f"--- {st}: {txt}")

asyncio.run(main())