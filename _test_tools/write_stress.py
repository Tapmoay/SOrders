# -*- coding: utf-8 -*-
"""SQLite写吞吐量化：纯并发下单，无读干扰"""
import sys, json, asyncio, time, argparse
sys.stdout.reconfigure(encoding='utf-8')
import aiohttp

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8003")
ap.add_argument("--n", type=int, default=50)
ap.add_argument("--rounds", type=int, default=5)
args = ap.parse_args()
BASE = args.base

async def main():
    conn = aiohttp.TCPConnector(limit=0, limit_per_host=0, ssl=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        # 预登录
        phones = [f"1391000{i:04d}" for i in range(1, 31)]
        toks = []
        for p in phones[:min(30, args.n)]:
            async with sess.post(BASE + "/api/v1/auth/login", json={"phone": p, "password": "pass12345"}, timeout=15) as r:
                try: toks.append((await r.json()).get("access_token"))
                except: toks.append(None)
        await asyncio.sleep(2)
        total_ok = total_err = 0
        for rd in range(args.rounds):
            batch = []
            def mk(i):
                phone = phones[i % len(phones)]
                tok = toks[i % len(toks)]
                async def inner():
                    h = {"Authorization": f"Bearer {tok}"}
                    body = {"lines": [{"product_id": (i % 8) + 1, "product_name_snapshot": "写测试", "quantity": 1, "unit_price": "10.00"}], "address_detail": f"写并发{i}", "contact_boss_phone": phone}
                    t0 = time.perf_counter()
                    try:
                        async with sess.post(BASE + "/api/v1/orders", headers=h, json=body, timeout=30) as r:
                            txt = await r.text()
                            return r.status, time.perf_counter() - t0
                    except Exception as e:
                        return -1, time.perf_counter() - t0
                return inner()
            batch = [mk(i) for i in range(args.n)]
            t0 = time.perf_counter()
            res = await asyncio.gather(*batch)
            dur = time.perf_counter() - t0
            ok = sum(1 for st, _ in res if st == 201)
            err = args.n - ok
            total_ok += ok; total_err += err
            lats = sorted(d for st, d in res if st == 201)
            p50 = lats[len(lats)//2]*1000 if lats else 0
            p95 = lats[int(len(lats)*0.95)]*1000 if lats else 0
            print(f"轮{rd+1}: {args.n}并发写 成功{ok} 失败{err} 耗时{dur:.2f}s p50={p50:.0f}ms p95={p95:.0f}ms", flush=True)
        print(f"TOTAL: 成功{total_ok} 失败{total_err} 错误率{total_err/(total_ok+total_err)*100:.1f}%", flush=True)

asyncio.run(main())