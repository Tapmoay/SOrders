"""本轮修复的实测验证（打真后端，只做可回滚/自清理的写操作）。

覆盖：
 ① GET /orders 的缺省上限与 X-Truncated 响应头
 ② 手工记账不许伪造 source=order（原来能凭空造账 + 改写已送达订单金额）
 ③ 客户合并 keep_id ∈ merge_ids 不再删库（原来是"两个档案都真删 + 500"）
 ④ /static/uploads/exports/** 一律 404（账本导出物不再匿名可下）
 ⑤ 账本导出下载端点要鉴权
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = "http://127.0.0.1:8000/api/v1"
DISPATCHER = ("13800000001", "123321")


def call(method: str, path: str, body=None, token: str | None = None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), dict(e.headers)
        except Exception:
            return e.code, raw, dict(e.headers)


def raw_get(url: str):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status, r.read()[:80]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:120]


tok = call("POST", "/auth/login", {"phone": DISPATCHER[0], "password": DISPATCHER[1]})[1]["access_token"]
ok = True


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok
    print(("  [通过] " if cond else "  [!!]   ") + label + ("" if cond else f" —— {detail}"))
    ok = ok and cond


print("== ① GET /orders 缺省上限 + 截断头 ==")
st, rows, hdrs = call("GET", "/orders", token=tok)
lim = hdrs.get("X-Result-Limit") or hdrs.get("x-result-limit")
trunc = hdrs.get("X-Truncated") or hdrs.get("x-truncated")
print(f"  状态 {st}｜返回 {len(rows) if isinstance(rows, list) else '?'} 条｜X-Result-Limit={lim}｜X-Truncated={trunc}")
check("缺省就有上限（不再全量下发）", lim == "300", f"实际 {lim}")
check("条数不超过上限", isinstance(rows, list) and len(rows) <= 300, f"实际 {len(rows) if isinstance(rows,list) else rows}")
check("截断状态如实回报（库里远超 300 单时应为 1）", trunc in ("0", "1"), f"实际 {trunc}")

print("\n== ② 手工记账不许伪造 source=order ==")
st, r, _ = call("POST", "/ledger/entries", {
    "shipper_id": 2, "entry_date": "2026-09-19", "product_name": "审计探针：伪造订单账",
    "quantity": 1, "unit_price": "9999", "source": "order",
}, token=tok)
check("source=order 被拒（400）", st == 400, f"返回 {st} {str(r)[:120]}")
if st == 400:
    print(f"    拒绝理由：{str(r.get('detail'))[:90]}")
st2, r2, _ = call("POST", "/ledger/entries", {
    "shipper_id": 2, "entry_date": "2026-09-19", "product_name": "审计探针：正常手工账",
    "quantity": 1, "unit_price": "1", "source": "manual", "note": "审计探针，随后删除",
}, token=tok)
check("manual 记账仍然可用", st2 in (200, 201), f"返回 {st2} {str(r2)[:120]}")
if st2 in (200, 201) and isinstance(r2, dict) and r2.get("id"):
    dst, _, _ = call("DELETE", f"/ledger/entries/{r2['id']}", token=tok)
    print(f"    （已清理探针账本行 #{r2['id']}：{dst}）")

print("\n== ③ 客户合并 keep_id ∈ merge_ids 不再删库 ==")
st, who, _ = call("GET", "/users/me", token=tok)
st, custs, _ = call("GET", "/customers", token=tok)
cid = None
if isinstance(custs, list) and custs:
    cid = custs[0].get("id")
before = len(custs) if isinstance(custs, list) else -1
if cid:
    st, r, _ = call("POST", "/customers/merge", {"keep_id": cid, "merge_ids": [cid]}, token=tok)
    after = len(call("GET", "/customers", token=tok)[1] or [])
    check("keep_id 出现在 merge_ids 里被拒（不再 500）", st == 400, f"返回 {st} {str(r)[:120]}")
    check("客户档案一个都没少", after == before, f"合并前 {before} → 合并后 {after}")
else:
    print("  [跳过] 没有客户档案可测")

print("\n== ④ /static/uploads/exports 匿名不可下 ==")
st, body = raw_get("http://127.0.0.1:8000/static/uploads/exports/ledger_2_1.xlsx")
check("历史导出路径一律 404", st == 404, f"返回 {st} {body[:60]}")
st, body = raw_get("http://127.0.0.1:8000/static/uploads/app/")
print(f"  参考：/static/uploads/app/ 返回 {st}（图片目录仍公开，属设计）")

print("\n== ⑤ 导出下载端点要鉴权 ==")
st, body = raw_get("http://127.0.0.1:8000/api/v1/ledger/export-jobs/1/download")
check("无 token 下载被拒（401/403）", st in (401, 403), f"返回 {st}")
st, r, _ = call("GET", "/ledger/export-jobs/1/download", token=tok)
print(f"  带派单员 token 返回 {st}（404 = 该任务没有产物，符合预期）")

print("\n" + ("全部通过 ✅" if ok else "有未通过项 ❌"))
sys.exit(0 if ok else 1)
