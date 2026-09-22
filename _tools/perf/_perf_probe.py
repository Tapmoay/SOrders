"""量**大库**下热端点的耗时（容量/性能这一空白面的量尺）。

## 为什么要有它

`_archive/audit/HANDOVER.md` 把"性能与容量"列为**一次都没测过**的第一条空白。
本机开发库只有几百张单，量不出任何东西 —— 所以先用 `_perf_seed.py` 造一个 2 万单的副本，
再拿这个脚本对**指向副本的那个后端**逐条量耗时。

它量的是"**一个人用**的时候这一页要等多久"，不是并发压测（并发是另一件事，见文末）。

## 判据（不是"看着快就行"）

- 每条端点跑 N 次（默认 3），取**中位数**，同时记最小值/最大值与响应体大小、返回行数；
- 分档阈值（本机 SQLite 单用户，仅作**回归标尺**，不是 SLA）：
  列表类 800ms 警戒 / 报表类 2000ms 警戒 / 导出创建 1500ms 警戒；
- 超过警戒线 → 退出码非零并点名（这样它能进收尾流程；不超就是绿的）；
- 还记**返回体 > 2MB** 为可疑（单用户手机上解析这么大的 JSON 本身就慢）。

## 怎么用

```
# ① 造库（副本，见 _perf_seed.py 的说明）
python _tools/perf/_perf_seed.py --orders 20000 --force
# ② 另一个后端指向副本（别动正在用的 8000）
cd backend; $env:DATABASE_URL='sqlite:///D:/AProjects/ASDH/orders/_agent/perf/perf.db'; \
    python -m uvicorn app.main:app --port 8001
# ③ 量
python _tools/perf/_perf_probe.py --base http://127.0.0.1:8001
```
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools" / "fuzz"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
from _fuzzlib import Api  # noqa: E402

#: (标签, 角色, 方法, 路径, 参数, 警戒线毫秒, 档位说明)
CASES: list[tuple[str, str, str, str, dict | None, int, str]] = [
    # ---- 订单列表（最常打开的几屏）----
    ("订单列表·全量（缺省 300 条）", "dispatcher", "GET", "/orders", None, 800, "列表"),
    ("待派单池", "dispatcher", "GET", "/orders", {"status": "PENDING_DISPATCH"}, 800, "列表"),
    ("已送达·近 30 天", "dispatcher", "GET", "/orders",
     {"status": "DELIVERED", "date_from": "2026-08-24", "date_to": "2026-09-23"}, 800, "列表"),
    ("待派单池角标（count）", "dispatcher", "GET", "/orders/pending-dispatch-count", None, 800, "列表"),
    ("按单号搜（精确）", "dispatcher", "GET", "/orders", {"q": "20260923"}, 800, "列表"),
    # ---- 账本 ----
    ("账本流水·一个月的窗口", "dispatcher", "GET", "/ledger/entries",
     {"date_from": "2026-09-01", "date_to": "2026-09-30"}, 2000, "报表"),
    ("账本账户卡片（按人聚合）", "dispatcher", "GET", "/ledger/accounts",
     {"date_from": "2026-09-01", "date_to": "2026-09-30", "kind": "shipper"}, 2000, "报表"),
    ("收款单列表", "dispatcher", "GET", "/ledger/receipts", None, 800, "列表"),
    ("资金流水（缺省 200 条）", "dispatcher", "GET", "/cash-flows", None, 800, "列表"),
    ("资金汇总（SQL 侧求和）", "dispatcher", "GET", "/cash-flows/summary",
     {"date_from": "2026-09-01", "date_to": "2026-09-30"}, 2000, "报表"),
    # ---- 报表 ----
    ("报表·营业纵览（整月）", "dispatcher", "GET", "/reports/turnover",
     {"mode": "month", "date": "2026-09-01"}, 2000, "报表"),
    ("报表·商品（整月）", "dispatcher", "GET", "/reports/products",
     {"mode": "month", "date": "2026-09-01"}, 2000, "报表"),
    ("报表·欠款汇总（整月）", "dispatcher", "GET", "/reports/arrears-summary",
     {"date_from": "2026-09-01", "date_to": "2026-09-30"}, 2000, "报表"),
    ("报表·司机绩效（整月）", "dispatcher", "GET", "/stats/driver-performance",
     {"date_from": "2026-09-01", "date_to": "2026-09-30"}, 2000, "报表"),
    # ---- 主数据 / 其他 ----
    ("商品列表", "dispatcher", "GET", "/products", None, 800, "列表"),
    ("库存概览（含在途占用）", "dispatcher", "GET", "/inventory/summary", None, 800, "列表"),
    ("客户名册", "dispatcher", "GET", "/customers", None, 800, "列表"),
    ("开销列表", "dispatcher", "GET", "/expenses", None, 800, "列表"),
    ("供应商应付款", "dispatcher", "GET", "/supplier-payables", None, 800, "列表"),
    ("操作日志（缺省 200 条）", "dispatcher", "GET", "/operation-logs", None, 800, "列表"),
    ("站内信列表", "dispatcher", "GET", "/notifications", None, 800, "列表"),
    # ---- 各端自己的视角 ----
    ("货主：我的订单", "shipper", "GET", "/orders", None, 800, "列表"),
    ("货主：我的账本流水", "shipper", "GET", "/ledger/entries", None, 2000, "报表"),
    ("司机：我的账单", "driver", "GET", "/driver-bills", None, 800, "列表"),
    ("司机：运费结算（整月）", "driver", "GET", "/freight-settlement", {"month": "2026-09"}, 2000, "报表"),
]

BIG_BODY_BYTES = 2 * 1024 * 1024


def rows_of(body: object) -> int | str:
    if isinstance(body, list):
        return len(body)
    if isinstance(body, dict):
        for k in ("items", "rows", "data", "list"):
            v = body.get(k)
            if isinstance(v, list):
                return len(v)
        return "-"
    return "-"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8001/api/v1", help="被测后端（默认 8001 那个副本后端）")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--only", default="", help="只跑标签里含这个词的用例")
    ap.add_argument("--out", type=Path, default=ROOT / "_agent/perf/last-run.json")
    args = ap.parse_args()

    api = Api(base=args.base)
    tokens = api.all_roles()
    cases = [c for c in CASES if not args.only or args.only in c[0]]

    print(f"被测后端：{args.base}    每条跑 {args.repeat} 次取中位数\n")
    print(f"{'用例':34} {'中位':>8} {'最小':>8} {'最大':>8} {'行数':>6} {'响应':>9}  判定")
    print("-" * 108)
    records, over = [], []
    for label, role, method, path, params, limit_ms, tier in cases:
        qs = ""
        if params:
            from urllib.parse import urlencode

            qs = "?" + urlencode(params)
        times, size, rows, status = [], 0, "-", 0
        for _ in range(max(1, args.repeat)):
            r = api.req(method, path + qs, None, tokens[role], allow_denied=True)
            times.append(r.ms)
            size = len(r.text.encode("utf-8", "replace"))
            rows = rows_of(r.body)
            status = r.status
        med, lo, hi = statistics.median(times), min(times), max(times)
        bad = med > limit_ms or size > BIG_BODY_BYTES or status >= 400
        why = []
        if med > limit_ms:
            why.append(f"超警戒线 {limit_ms}ms")
        if size > BIG_BODY_BYTES:
            why.append(f"响应体 {size / 1024 / 1024:.1f}MB")
        if status >= 400:
            why.append(f"HTTP {status}")
        verdict = "❌ " + "；".join(why) if bad else "✓"
        print(f"{label:34} {med:7.0f}ms {lo:7.0f}ms {hi:7.0f}ms {str(rows):>6} "
              f"{size / 1024:8.0f}KB  {verdict}")
        records.append(dict(label=label, role=role, path=path, params=params, status=status,
                            median_ms=round(med, 1), min_ms=round(lo, 1), max_ms=round(hi, 1),
                            bytes=size, rows=rows, tier=tier, limit_ms=limit_ms))
        if bad:
            over.append((label, med, limit_ms, size, status))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    print("-" * 108)
    print(f"明细：{args.out}")
    if over:
        print(f"\n❌ {len(over)}/{len(records)} 条超警戒：")
        for label, med, limit_ms, size, status in over:
            print(f"   - {label}：{med:.0f}ms（线 {limit_ms}ms）"
                  f"{'，响应体 %.1fMB' % (size / 1024 / 1024) if size > BIG_BODY_BYTES else ''}"
                  f"{'，HTTP %d' % status if status >= 400 else ''}")
        print("\n（本机单用户 SQLite 的耗时只作**回归标尺**：生产是 MySQL + nginx，数字会不同；"
              "但「这一条比别的慢一个量级」这种结论是能搬的。）")
        return 1
    print(f"\n✅ {len(records)} 条端点全部在警戒线内（中位数最大 "
          f"{max(r['median_ms'] for r in records):.0f}ms）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
