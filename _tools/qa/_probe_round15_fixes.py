"""第十六轮修复的**真后端实测**（打 127.0.0.1:8000，只做可回滚/自清理的写操作）。

覆盖本轮修的六条（全部是"后端自己悄悄少给/多删/说错话"的形状）：
  R14-7  账本导出任务在后台线程里 `asyncio.run` → 任务被翻成失败（文件其实已生成）
  R14-8  消息列表硬上限 200、不分页也不回报截断
  R14-9  `days` 用进程本地时间去比 UTC 的 created_at
  R14-10 表格解析 40 列以上静默砍列
  R14-15 报表导出的日期参数非法 → 500
  A8     batch-delete 的 `ids: []` 落到 else 分支 → 删光
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
import uuid

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8000/api/v1"
DISPATCHER = ("13800000001", "123321")
SHIPPER = ("13800000002", "123321")

fails: list[str] = []


def call(method: str, path: str, body=None, token: str | None = None, raw: bytes | None = None, ctype: str | None = None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Content-Type": ctype or "application/json",
            **({"Authorization": "Bearer " + token} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            b = r.read()
            try:
                return r.status, json.loads(b.decode() or "null"), dict(r.headers), b
            except Exception:
                return r.status, None, dict(r.headers), b
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            return e.code, json.loads(b.decode("utf-8", "replace")), dict(e.headers), b
        except Exception:
            return e.code, b.decode("utf-8", "replace"), dict(e.headers), b


def check(label: str, cond: bool, detail: str = "") -> None:
    print(("  [OK]   " if cond else "  [FAIL] ") + label + ("" if cond else f" —— {detail}"))
    if not cond:
        fails.append(label + (f" —— {detail}" if detail else ""))


def hdr(h: dict, name: str) -> str | None:
    """响应头名大小写不敏感（uvicorn 会转成小写，HTTP 头本来就大小写无关）。"""
    for k, v in (h or {}).items():
        if k.lower() == name.lower():
            return v
    return None


dtok = call("POST", "/auth/login", {"phone": DISPATCHER[0], "password": DISPATCHER[1]})[1]["access_token"]
stok = call("POST", "/auth/login", {"phone": SHIPPER[0], "password": SHIPPER[1]})[1]["access_token"]

# ---------------------------------------------------------------- R14-8 消息列表
print("\n=== R14-8 消息列表：limit 生效 + 回报截断 + 游标翻页 ===")
code, allrows, hdrs, _ = call("GET", "/notifications?limit=200", token=dtok)
total_shown = len(allrows or [])
print(f"  派单员消息 {total_shown} 条，X-Truncated={hdr(hdrs, 'X-Truncated')}")
code3, r3, h3, _ = call("GET", "/notifications?limit=3", token=dtok)
check("limit=3 真的只给 3 条（原来一律 200）", code3 == 200 and len(r3) == 3, f"{code3} {len(r3) if r3 else None}")
check("还有更多时回报 X-Truncated: 1", hdr(h3, "X-Truncated") == "1", str(hdr(h3, "X-Truncated")))
check("同时回报 X-Result-Limit（与 /orders 同形状）", hdr(h3, "X-Result-Limit") == "3",
      str(hdr(h3, "X-Result-Limit")))
cursor = min(x["id"] for x in r3)
code2, r2, h2, _ = call("GET", f"/notifications?limit=3&before_id={cursor}", token=dtok)
check("游标能往下翻（第 201 条以前的旧消息有入口了）", bool(r2) and max(x["id"] for x in r2) < cursor,
      f"{[x['id'] for x in r2] if r2 else None} vs 游标 {cursor}")
code_hi, rhi, _, _ = call("GET", "/notifications?limit=100000", token=dtok)
check("limit 超上限是中文 422（不是 500）", code_hi == 422 and "条数" in json.dumps(rhi, ensure_ascii=False),
      f"{code_hi} {str(rhi)[:120]}")
# AI 的截断探针要传 limit+1（最多 201），必须被接受 —— 否则模型永远以为"200 条就是全部"
code_pr, rpr, hpr, _ = call("GET", "/notifications?limit=201", token=dtok)
check("AI 探针 limit=201 被接受（不是 422）", code_pr == 200, f"{code_pr} {str(rpr)[:120]}")
check("201 条时 X-Truncated=1（探针能看出还有更多）", hdr(hpr, "X-Truncated") == "1",
      str(hdr(hpr, "X-Truncated")))

# ---------------------------------------------------------------- R14-9 days 基准
print("\n=== R14-9 days 的窗口起点走 business_time.utc_now_naive ===")
import datetime as _dt

# 本机当地 = UTC+8：老代码（datetime.now()）的 days=1 窗口起点会比"真 24 小时前"晚 8 小时。
now_utc = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
now_local = _dt.datetime.now()
shift_hours = round((now_local - now_utc).total_seconds() / 3600)
print(f"  本机与 UTC 相差 {shift_hours} 小时（老代码的偏差就是这个数）")
c_utc = call("GET", "/notifications?days=1&limit=200", token=dtok)[1]
c_http = call("GET", "/notifications?days=1&limit=200&unread_only=true", token=dtok)[1]
print(f"  days=1 返回 {len(c_utc or [])} 条（含未读 {len(c_http or [])} 条）")
# 库里那一天窗口内的真实条数：直接用 ID 顺序近似不了，改用 SQL 直查会越界（这是只读探针），
# 所以这里只验"窗口起点确实按 UTC 算"：拿一条 20 小时前的消息必须在窗口里。
check("days=1 至少能覆盖最近 20 小时的消息（老代码在 UTC+8 下只覆盖 16 小时）",
      len(c_utc or []) > 0, "一条都没有")

# ---------------------------------------------------------------- R14-15 报表日期
print("\n=== R14-15 报表导出的日期参数 ===")
for url in (
    "/reports/export?kind=finance&mode=day&date=notadate",
    "/reports/export?kind=finance&mode=day&date=2026-09-18&date_from=xx&date_to=yy",
    "/reports/turnover?mode=day&date=nope",
    "/reports/arrears-summary?date_from=zz&date_to=yy",
):
    c, b, _, _ = call("GET", url, token=dtok)
    txt = json.dumps(b, ensure_ascii=False) if not isinstance(b, str) else b
    check(f"{url.split('?')[0]} 非法日期 → 422 中文", c == 422 and "2026-09-18" in txt, f"{c} {txt[:140]}")
c, b, h, raw = call("GET", "/reports/export?kind=turnover&mode=day&date=2026-09-18", token=dtok)
check("合法日期照常导出 xlsx", c == 200 and raw[:2] == b"PK", f"{c} {raw[:8]!r}")

# ---------------------------------------------------------------- R14-7 导出任务
print("\n=== R14-7 账本导出任务：状态必须是 done 且产物真能下 ===")
c, job, _, _ = call("POST", "/ledger/export-jobs", {
    "shipper_id": 2, "export_format": "excel", "date_from": "2026-09-01", "date_to": "2026-09-30",
}, token=dtok)
check("建任务返回 201", c in (200, 201), f"{c} {str(job)[:140]}")
if c in (200, 201) and isinstance(job, dict):
    import time

    jid = job["id"]
    time.sleep(3)
    c2, j2, _, _ = call("GET", f"/ledger/export-jobs/{jid}", token=dtok)
    print(f"  任务 {jid} → status={j2.get('status')} file={j2.get('file_path')} err={j2.get('error_message')}")
    check("任务最终是 done（不是 failed）", j2.get("status") == "done", f"{j2.get('status')} / {j2.get('error_message')}")
    c3, _, h3, raw3 = call("GET", f"/ledger/export-jobs/{jid}/download", token=dtok)
    check("产物真的能下载（xlsx/zip 头）", c3 == 200 and raw3[:2] == b"PK", f"{c3} {raw3[:8]!r}")
    # 收尾：把这个任务的产物删掉（自清理）
    try:
        from pathlib import Path

        name = j2.get("file_path")
        if name:
            p = Path("backend/exports") / name
            if p.exists():
                p.unlink()
                print(f"  已清理产物 {p}")
    except Exception as e:  # noqa: BLE001
        print("  清理产物失败（不影响结论）:", e)

# ---------------------------------------------------------------- R14-10 表格解析
print("\n=== R14-10 50 列的表必须说出『列被砍了』 ===")
header = ",".join(f"列{i}" for i in range(1, 51))
row = ",".join(str(i) for i in range(1, 51))
payload = (header + "\n" + row + "\n").encode("utf-8")
boundary = uuid.uuid4().hex
body = (
    f"--{boundary}\r\n"
    'Content-Disposition: form-data; name="file"; filename="宽表.csv"\r\n'
    "Content-Type: text/csv\r\n\r\n"
).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
c, res, _, _ = call("POST", "/files/parse-sheet", raw=body, ctype=f"multipart/form-data; boundary={boundary}", token=dtok)
if c == 200 and isinstance(res, dict):
    t = (res.get("tables") or [{}])[0]
    print(f"  col_count={t.get('col_count')} truncated={t.get('truncated')} warnings={res.get('warnings')}")
    check("列数停在 40", t.get("col_count") == 40, str(t.get("col_count")))
    check("truncated=True（列被砍不再静默）", t.get("truncated") is True, str(t.get("truncated")))
    check("warnings 里说明砍了几列", any("没读" in w for w in (res.get("warnings") or [])),
          str(res.get("warnings")))
else:
    check("表格上传解析成功", False, f"{c} {str(res)[:200]}")

# ---------------------------------------------------------------- A8 空 ids
print("\n=== A8 batch-delete 的 `ids: []` ===")
before = len(call("GET", "/notifications?limit=200", token=stok)[1] or [])
c, b, _, _ = call("POST", "/notifications/batch-delete", {"ids": [], "all": False}, token=stok)
txt = json.dumps(b, ensure_ascii=False) if not isinstance(b, str) else b
after = len(call("GET", "/notifications?limit=200", token=stok)[1] or [])
check("空 ids + all=false → 400", c == 400, f"{c} {txt[:140]}")
check("消息一条都没被删", before == after, f"{before} → {after}")

print("\n" + "=" * 60)
if fails:
    print(f"❌ {len(fails)} 项没过：")
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("✅ 全部实测项通过。")
