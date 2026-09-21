"""校验「日期筛选差 8 小时」的修复：**打真接口**按日期查，数必须等于库里按业务日算出来的那个数。

为什么单独有这个脚本：这个 bug 的判据不能在单测里闭环 —— 单测证明的是"SQL 条件带上了换算后
的区间"，而"接口最终返回的单数 = 业务日口径"只有打一次真接口才能证明。

用法：
    python _tools/seed/_verify_date_window.py --date 2026-09-21
    python _tools/seed/_verify_date_window.py --date 2026-09-21 --base http://127.0.0.1:8000

配套 SQL：`_tools/seed/_verify_date_window.sql`（在服务器上跑，得到"库里应该有多少单"）。
把两边数字对一下：相等 = 修复生效；等于"对照"那行 = 还是旧口径。
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://8.145.40.22")
    ap.add_argument("--date", required=True, help="要查的那一天（北京业务日），YYYY-MM-DD")
    ap.add_argument("--phone", default="13800000001")
    ap.add_argument("--password", default="123321")
    args = ap.parse_args()

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def call(path: str, body: dict | None = None, token: str | None = None) -> tuple[int, str]:
        req = urllib.request.Request(args.base + path, method="POST" if body else "GET")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, json.dumps(body).encode() if body else None,
                                        timeout=60, context=ctx) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    st, body = call("/api/v1/auth/login", {"phone": args.phone, "password": args.password})
    if st != 200:
        print(f"❌ 登录失败：HTTP {st} {body[:160]}")
        return 1
    token = json.loads(body)["access_token"]

    # ① 单日窗口
    st, body = call(f"/api/v1/orders?date_from={args.date}&date_to={args.date}&limit=5000", token=token)
    if st != 200:
        print(f"❌ 查订单失败：HTTP {st} {body[:200]}")
        return 1
    rows = json.loads(body)
    print(f"接口按 {args.date} 单日窗口查到：{len(rows)} 单")

    # ② 打印几单的业务当地时刻，便于肉眼核对是不是都落在这一天
    import datetime as _dt
    shown = 0
    for o in rows[:200]:
        raw = o.get("created_at") or o.get("order_date") or ""
        if not raw:
            continue
        try:
            t = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is not None:
            t = t.astimezone(_dt.timezone(_dt.timedelta(hours=8))).replace(tzinfo=None)
        if shown < 5:
            print(f"   {o.get('order_no')}  存库/返回 {raw}  → 业务当地 {t:%Y-%m-%d %H:%M}")
            shown += 1

    print()
    print("把上面的单数与服务器上 `_tools/seed/_verify_date_window.sql` 的两行比：")
    print("  · 等于「库里按业务日算」那一行  → ✅ 修复生效（取的是北京全天）")
    print("  · 等于「（对照）按 UTC 零点口径」那一行 → ❌ 还是旧口径（差 8 小时）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
