# -*- coding: utf-8 -*-
"""逐步升温并发（参数化BASE）"""
import sys, json, asyncio, random, time, argparse
sys.stdout.reconfigure(encoding='utf-8')
import aiohttp

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--users", type=int, default=30)
args = ap.parse_args()
BASE = args.base

async def login_all(sess, n):
    toks = []
    for i in range(1, n + 1):
        phone = f"1391000{i:04d}"
        try:
            async with sess.post(BASE + "/api/v1/auth/login", json={"phone": phone, "password": "pass12345"}, timeout=10) as r:
                j = await r.json()
                toks.append(j.get("access_token"))
        except Exception:
            toks.append(None)
    return toks

async def do_order(sess, phone, tok):
    if not tok: return ("NO_TOK", "")
    h = {"Authorization": f"Bearer {tok}"}
    body = {"lines": [{"product_id": random.randint(1, 8), "product_name_snapshot": "升温", "quantity": 1, "unit_price": "10.00"}], "address_detail": "升温地址", "contact_boss_phone": phone}
    try:
        async with sess.post(BASE + "/api/v1/orders", headers=h, json=body, timeout=15) as r:
            return (r.status, (await r.text())[:250])
    except Exception as e:
        return ("EXC", str(e)[:120])

async def wave(sess, toks, n, label):
    t0 = time.perf_counter()
    batch = [asyncio.create_task(do_order(sess, f"1391000{(i % len(toks)) + 1:04d}", toks[i % len(toks)])) for i in range(n)]
    res = await asyncio.gather(*batch, return_exceptions=True)
    dur = time.perf_counter() - t0
    from collections import Counter
    cnt = Counter()
    for r in res:
        if isinstance(r, tuple): cnt[r[0]] += 1
        else: cnt["TASK_EXC"] += 1
    print(f"{label} ({n}并发): {dict(cnt)} 耗时{dur:.2f}s", flush=True)

async def main():
    conn = aiohttp.TCPConnector(limit=0, limit_per_host=0, ssl=False)
    async with aiohttp.ClientSession(connector=conn) as sess:
        toks = await login_all(sess, args.users)
        print("预登录:", sum(1 for t in toks if t), "/", args.users, flush=True)
        for n, label in [(5, "W1"), (10, "W2"), (20, "W3"), (30, "W4"), (50, "W5"), (80, "W6")]:
            await wave(sess, toks, n, label)
            await asyncio.sleep(1)

asyncio.run(main())