"""对账脚本：把「接口返回」与「库里直查」并排打出来，用于给 AI 的答案当标尺。

为什么要两列：AI 答错数字时，可能是**模型算错**，也可能是**接口本身算错**。
先把这两个分开，才不会花半天去调提示词，结果发现是后端口径的问题。

用法：
  python _check_agg_after_seed.py                 # 本月 + 上月
  python _check_agg_after_seed.py --month 2026-08 # 指定某个月
  python _check_agg_after_seed.py --days 7        # 最近 7 天
"""
import argparse
import calendar
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"
DB = repo_root() / "backend" / "sorders.db"
TAG = "SOTEST"


def call(path: str, token: str):
    req = urllib.request.Request(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return {"__error__": f"HTTP {e.code} {e.read().decode('utf-8','ignore')[:160]}"}
    except Exception as e:  # noqa: BLE001
        return {"__error__": str(e)}


def login() -> str:
    for phone, pwd in (("13800000001", "123321"), ("13900000001", "test1234")):
        req = urllib.request.Request(
            f"{BASE}/auth/login",
            data=json.dumps({"phone": phone, "password": pwd}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
            if d.get("access_token"):
                print(f"  已登录：{phone}")
                return d["access_token"]
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit("登录失败：本地后端没起，或账号密码被改过")


def month_range(ym: str) -> tuple[date, date]:
    y, m = (int(x) for x in ym.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM；不给就同时看本月与上月")
    ap.add_argument("--days", type=int, help="最近 N 天（与 --month 互斥，优先）")
    a = ap.parse_args()

    today = date.today()
    if a.days:
        periods = [(f"最近 {a.days} 天", today - timedelta(days=a.days - 1), today)]
    elif a.month:
        f, t = month_range(a.month)
        periods = [(a.month, f, t)]
    else:
        this_first = today.replace(day=1)
        last_end = this_first - timedelta(days=1)
        periods = [
            ("本月", this_first, today),
            ("上月", last_end.replace(day=1), last_end),
        ]

    token = login()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    for label, f, t in periods:
        print(f"\n{'=' * 66}\n== {label}  {f} ~ {t}\n{'=' * 66}")

        # ---------- 货主下单排行 ----------
        print("\n[货主下单排行]  接口 / 库直查（只算已送达）")
        api = call(f"/stats/shipper-performance?date_from={f}&date_to={t}", token)
        api_rows = (api.get("shippers") or []) if isinstance(api, dict) else []
        if "__error__" in api:
            print("   接口报错：", api["__error__"])
        db_rows = cur.execute(
            "SELECT COALESCE(u.full_name, o.temp_shipper_name, '未命名') AS nm,"
            " COUNT(DISTINCT o.id), COALESCE(SUM(op.line_total), 0)"
            " FROM orders o LEFT JOIN users u ON u.id = o.shipper_id"
            " LEFT JOIN order_products op ON op.order_id = o.id"
            " WHERE o.status='DELIVERED' AND o.order_date>=? AND o.order_date<=?"
            " GROUP BY COALESCE(u.id, o.temp_shipper_name)"
            " ORDER BY 2 DESC, 1 LIMIT 8",
            (f.isoformat(), t.isoformat()),
        ).fetchall()
        db_map = {str(r[0]): (r[1], float(r[2])) for r in db_rows}
        # 同名同单量的并列很常见（本月就有两组），所以**按名字比对**，不比位置
        print("   {:<24}{:>6}  {:>12}   {}".format("接口", "单数", "金额", "库直查"))
        for i, r in enumerate(api_rows[:8]):
            nm = str(r.get("shipper_name"))
            cnt, amt = r.get("order_count"), float(r.get("total_amount") or 0)
            if nm in db_map:
                dcnt, damt = db_map[nm]
                mark = "OK" if (dcnt == cnt and abs(damt - amt) < 0.01) else f"*** 不一致 库={dcnt}单 {damt:.2f} ***"
            else:
                mark = "（不在库直查前 8，属正常）"
            print("   {:<24}{:>6}  {:>12}   {}".format(nm[:22], cnt, f"{amt:.2f}", mark))

        # ---------- 司机跑货 ----------
        print("\n[司机跑货]  接口按 delivered_at 统计；库直查同口径")
        print("   注意：接口给的是**待结**运费 = 区间应结 - 历史已付(PAID 结算单)，所以两边要减一下才可比")
        api = call(f"/stats/driver-performance?date_from={f}&date_to={t}", token)
        api_rows = (api.get("drivers") or []) if isinstance(api, dict) else []
        if "__error__" in api:
            print("   接口报错：", api["__error__"])
        db_rows = cur.execute(
            "SELECT u.full_name, u.billing_mode, COUNT(*), COALESCE(SUM(o.freight_fee),0), o.driver_id"
            " FROM orders o JOIN users u ON u.id = o.driver_id"
            " WHERE o.status='DELIVERED' AND o.delivered_at IS NOT NULL"
            "   AND o.delivered_at >= ? AND o.delivered_at <= ?"
            " GROUP BY o.driver_id ORDER BY 3 DESC, 1 LIMIT 8",
            (f"{f} 00:00:00", f"{t} 23:59:59"),
        ).fetchall()
        api_map = {str(r.get("driver_name")): r for r in api_rows}
        for i, (name, mode, cnt, fee, did) in enumerate(db_rows):
            settled = cur.execute(
                "SELECT COALESCE(SUM(amount),0) FROM driver_settlements"
                " WHERE driver_id=? AND status='paid'", (did,),
            ).fetchone()[0]
            should_owe = None if (mode or "").upper() != "PIECE" else max(float(fee) - float(settled), 0.0)
            ar = api_map.get(str(name))
            got = ar.get("freight_owed") if ar else None
            got_cnt = ar.get("completed_count") if ar else None
            if should_owe is None:
                mark = "OK（工资制不该有待结）" if got is None else f"*** 工资制却给了待结={got} ***"
            else:
                mark = "OK" if got is not None and abs(float(got) - should_owe) < 0.01 else \
                    f"*** 接口={got} 应为={should_owe:.2f} ***"
            print("   {:<14}{:>4} 单  {:<7} 应结={:>8.2f} 已付={:>7.2f} 待结={:>8}   {}".format(
                str(name)[:12], cnt, mode or "-", float(fee), float(settled),
                "—" if should_owe is None else f"{should_owe:.2f}", mark))
            if got_cnt is not None and got_cnt != cnt:
                print(f"      *** 单量不一致：接口 {got_cnt} vs 库 {cnt} ***")

        # ---------- 口径核对 ----------
        total_delivered = cur.execute(
            "SELECT COUNT(*) FROM orders WHERE status='DELIVERED' AND order_date>=? AND order_date<=?",
            (f.isoformat(), t.isoformat()),
        ).fetchone()[0]
        other = cur.execute(
            "SELECT status, COUNT(*) FROM orders WHERE order_date>=? AND order_date<=? AND status<>'DELIVERED'"
            " GROUP BY status", (f.isoformat(), t.isoformat()),
        ).fetchall()
        print(f"\n[口径] 区间内已送达 {total_delivered} 单；未送达/撤销：{dict(other) or '无'}"
              f"（后一类**不该**出现在任何排行里）")

    print("\n[库存预警]  应触发报警的商品（阈值>0 且 库存<=阈值）")
    for name, stock, alert in cur.execute(
        "SELECT name, stock, low_stock_alert FROM products"
        " WHERE low_stock_alert>0 AND stock<=low_stock_alert ORDER BY stock"
    ):
        print(f"   {name:<32} 库存={stock:<5} 阈值={alert}")
    print("   边界对照（应当**不**报警）：")
    for name, stock, alert in cur.execute(
        "SELECT name, stock, low_stock_alert FROM products"
        " WHERE low_stock_alert>0 AND stock=low_stock_alert+1 ORDER BY stock"
    ):
        print(f"   {name:<32} 库存={stock:<5} 阈值={alert}  ← 只多 1，不该报")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
