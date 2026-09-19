# -*- coding: utf-8 -*-
"""并发登录接口测试 (300并发)"""
import sys, json, asyncio, time, argparse
sys.stdout.reconfigure(encoding='utf-8')
import aiohttp

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8003")
ap.add_argument("--n", type=int, default=110)
args = ap.parse_args()
BASE = args.base

async def login_one(sess, phone):
    t0 = time.perf_counter()
    try:
        async with sess.post(BASE + "/api/v1/auth/login", json={"phone": phone, "password": "pass12345"}, timeout=15) as r:
            txt = await r.text()
            return r.status, time.perf_counter() - t0, txt[:80]
    except Exception as e:
        return -1, time.perf_counter() - t0, str(e)[:80]

async def main():
    conn = aiohttp.TCPConnector(limit=0, limit_per_host=0, ssl=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        phones = [f"1391000{i:04d}" for i in range(1, 61)] + [f"1382000{i:04d}" for i in range(1, 51)]
        # 混入重复登录（同一账号多设备）
        targets = [phones[i % len(phones)] for i in range(args.n)]
        t0 = time.perf_counter()
        res = await asyncio.gather(*[login_one(sess, p) for p in targets])
        dur = time.perf_counter() - t0
        ok = sum(1 for st, _, _ in res if st == 200)
        print(f"并发登录 {args.n}: 成功{ok} 失败{args.n-ok} 耗时{dur:.2f}s", flush=True)
        for st, d, txt in res[:10]:
            if st != 200: print(f"  {st}: {txt} {d*1000:.0f}ms", flush=True)

asyncio.run(main())