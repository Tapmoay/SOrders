"""SOrders AI 助手 · P0 验证工具（只读，绝不写库）

用途：在**不写任何 App 代码**的前提下，验证"自然语言 → 查询参数"的值不值得做。
它做三件事：
  1) --probe   看本地库的数据分布，为人写真实问题提供依据
  2) --dry     只打印问题集与期望工具（不调模型，零成本）
  3) --run     真调模型（DeepSeek），记录它选了哪个工具/参数，与期望比对
  4) --score   对已有 results.jsonl 打分，输出判据表

设计口径（重要）：
  * 工具语义 1:1 对应真实后端端点（映射见 TOOLS[i]["endpoint"]），
    但执行走**本地 SQLite 只读**，因为本机后端没在跑、也不该拿生产库做实验。
  * 因此本实验**只测"模型选工具/填参数"这一件事**，不测后端行为——那部分靠真实端点自测。
  * 判据见 docs/AI_ASSISTANT_PLAN.md §3.3。

用法：
  python _ai_p0_probe.py --probe
  python _ai_p0_probe.py --dry
  python _ai_p0_probe.py --run            # 需要 DEEPSEEK_API_KEY
  python _ai_p0_probe.py --score
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = repo_root()
DB = ROOT / "backend" / "sorders.db"
OUT = ROOT / "_ai_p0_results.jsonl"
CRED = Path(os.path.expanduser("~")) / ".dsh" / ".credentials.yaml"

API_BASE = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")

# ---------------------------------------------------------------------------
# 工具定义：语义 1:1 对应真实端点
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "list_orders",
        "endpoint": "GET /api/v1/orders",
        "desc": "按状态/日期/关键字/货主筛选订单列表。关键字会同时模糊匹配单号、货主姓名、货主电话、临时货主名、收货地址、司机姓名、司机电话。",
        "params": {
            "status": {"type": "string", "enum": ["PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "DELIVERED", "CANCELLED"], "description": "订单状态，省略=不限"},
            "q": {"type": "string", "description": "关键字（人名/地址/单号）"},
            "date_from": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
            "date_to": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
            "shipper_id": {"type": "integer", "description": "指定货主 id"},
            "limit": {"type": "integer", "description": "最多返回条数"},
        },
        "risk": "read",
    },
    {
        "name": "pending_dispatch_count",
        "endpoint": "GET /api/v1/orders/pending-dispatch-count",
        "desc": "待派单池的订单数量（只返回一个数字）。",
        "params": {},
        "risk": "read",
    },
    {
        "name": "ledger_accounts",
        "endpoint": "GET /api/v1/ledger/accounts",
        "desc": "按货主/批发商聚合的账目：笔数与总额。kind=shipper 为货主，kind=member 为批发商。",
        "params": {
            "kind": {"type": "string", "enum": ["shipper", "member"]},
            "date_from": {"type": "string", "description": "起始日期 YYYY-MM-DD"},
            "date_to": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
        },
        "risk": "read",
    },
    {
        "name": "report_turnover",
        "endpoint": "GET /api/v1/reports/turnover",
        "desc": "营业纵览：营业额、成本、毛利、收款、挂账、货损、撤销单数。毛利只按有成本快照的行计算，必须同时报告覆盖率。",
        "params": {
            "date_from": {"type": "string"},
            "date_to": {"type": "string"},
        },
        "risk": "read",
    },
    {
        "name": "driver_performance",
        "endpoint": "GET /api/v1/stats/driver-performance",
        "desc": "司机表现：完成单数、准时率、待结运费（仅计件司机）。",
        "params": {
            "date_from": {"type": "string"},
            "date_to": {"type": "string"},
        },
        "risk": "read",
    },
    {
        "name": "freight_settlement",
        "endpoint": "GET /api/v1/freight-settlement",
        "desc": "按司机聚合的运费结算：每位司机的单数与运费合计。",
        "params": {
            "date_from": {"type": "string"},
            "date_to": {"type": "string"},
        },
        "risk": "read",
    },
]

TOOL_BY_NAME = {t["name"]: t for t in TOOLS}


def _tool_schema(t: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["desc"],
            "parameters": {
                "type": "object",
                "properties": t["params"],
                "required": [],
                "additionalProperties": False,
            },
        },
    }


# ---------------------------------------------------------------------------
# 本地只读执行器（工具语义 == 真实端点语义）
# ---------------------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    if not DB.exists():
        sys.exit(f"找不到本地库：{DB}")
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def exec_tool(name: str, args: dict) -> dict:
    """按真实端点语义在本地只读库上执行，返回给模型看的结果摘要。"""
    con = _conn()
    cur = con.cursor()
    try:
        if name == "list_orders":
            sql = [
                "SELECT o.status, COUNT(*), ROUND(SUM(COALESCE(o.freight_fee,0)),2) "
                "FROM orders o "
                "LEFT JOIN users s ON s.id=o.shipper_id "
                "LEFT JOIN users d ON d.id=o.driver_id "
                "WHERE o.deleted_at IS NULL"
            ]
            p: list = []
            if args.get("status"):
                sql.append("AND o.status=?")
                p.append(args["status"])
            if args.get("q"):
                term = f"%{args['q']}%"
                sql.append(
                    "AND (o.order_no LIKE ? OR s.full_name LIKE ? OR s.phone LIKE ? "
                    "OR o.temp_shipper_name LIKE ? OR o.address_detail LIKE ? "
                    "OR d.full_name LIKE ? OR d.phone LIKE ?)"
                )
                p += [term] * 7
            if args.get("date_from"):
                sql.append("AND o.order_date >= ?")
                p.append(args["date_from"])
            if args.get("date_to"):
                sql.append("AND o.order_date <= ?")
                p.append(args["date_to"])
            if args.get("shipper_id"):
                sql.append("AND o.shipper_id = ?")
                p.append(args["shipper_id"])
            sql.append("GROUP BY o.status")
            rows = cur.execute(" ".join(sql), p).fetchall()
            return {"groups": [{"status": r[0], "count": r[1], "freight_sum": r[2]} for r in rows],
                    "total": sum(r[1] for r in rows)}

        if name == "pending_dispatch_count":
            n = cur.execute(
                "SELECT COUNT(*) FROM orders WHERE status='PENDING_DISPATCH' AND deleted_at IS NULL"
            ).fetchone()[0]
            return {"pending_dispatch": n}

        if name == "ledger_accounts":
            kind = args.get("kind", "shipper")
            # 与真实实现对齐（backend/app/api/v1/ledger.py:86-136）：
            #   * 用 entry_date 过滤（不是 created_at）
            #   * 金额取 ledgers.total（**不是 amount —— 该列不存在**）
            #   * kind=member 只保留 is_member 用户；shipper_id 为空的行是临时货主，
            #     member 模式下直接跳过
            sql = (
                "SELECT l.shipper_id, l.temp_shipper_name, "
                "COALESCE(u.full_name, u.phone) AS uname, COALESCE(u.is_member,0), "
                "COUNT(l.id), ROUND(SUM(COALESCE(l.total,0)),2) "
                "FROM ledgers l LEFT JOIN users u ON u.id=l.shipper_id WHERE 1=1"
            )
            p2: list = []
            if args.get("date_from"):
                sql += " AND l.entry_date >= ?"
                p2.append(args["date_from"])
            if args.get("date_to"):
                sql += " AND l.entry_date <= ?"
                p2.append(args["date_to"])
            sql += " GROUP BY l.shipper_id, l.temp_shipper_name, uname"
            rows = cur.execute(sql, p2).fetchall()
            buckets: dict[str, dict] = {}
            for sid, tname, uname, is_member, cnt, tot in rows:
                if sid is not None:
                    if kind == "member" and not is_member:
                        continue
                    name = uname or f"货主#{sid}"
                else:
                    if kind == "member":
                        continue
                    name = (tname or "").strip() or "临时货主"
                b = buckets.setdefault(name, {"who": name, "entries": 0, "total": 0.0})
                b["entries"] += cnt
                b["total"] = round(b["total"] + (tot or 0), 2)
            accts = sorted(buckets.values(), key=lambda x: -x["total"])
            return {"kind": kind, "accounts": accts[:50]}

        if name == "report_turnover":
            sql = (
                "SELECT ROUND(SUM(COALESCE(op.line_total,0)),2), COUNT(DISTINCT o.id), "
                "SUM(CASE WHEN op.cost_price_snapshot>0 THEN 1 ELSE 0 END), COUNT(op.id) "
                "FROM orders o JOIN order_products op ON op.order_id=o.id "
                "WHERE o.deleted_at IS NULL"
            )
            p3: list = []
            if args.get("date_from"):
                sql += " AND o.order_date >= ?"
                p3.append(args["date_from"])
            if args.get("date_to"):
                sql += " AND o.order_date <= ?"
                p3.append(args["date_to"])
            r = cur.execute(sql, p3).fetchone()
            cost_cov = f"{r[2]}/{r[3]}" if r[3] else "0/0"
            return {"turnover": r[0], "orders": r[1], "cost_covered_lines": cost_cov,
                    "note": "毛利只按有成本快照的行计算，须同时报告覆盖率"}

        if name == "driver_performance":
            sql = (
                "SELECT COALESCE(u.full_name,'(未知)'), COUNT(o.id), "
                "ROUND(SUM(COALESCE(o.freight_fee,0)),2) "
                "FROM orders o JOIN users u ON u.id=o.driver_id "
                "WHERE o.status='DELIVERED' AND o.deleted_at IS NULL"
            )
            p4: list = []
            if args.get("date_from"):
                sql += " AND o.order_date >= ?"
                p4.append(args["date_from"])
            if args.get("date_to"):
                sql += " AND o.order_date <= ?"
                p4.append(args["date_to"])
            sql += " GROUP BY u.full_name ORDER BY 2 DESC LIMIT 30"
            rows = cur.execute(sql, p4).fetchall()
            return {"drivers": [{"driver": r[0], "delivered": r[1], "freight": r[2]} for r in rows]}

        if name == "freight_settlement":
            sql = (
                "SELECT COALESCE(u.full_name,'(未知)'), COUNT(o.id), "
                "ROUND(SUM(COALESCE(o.freight_fee,0)),2) "
                "FROM orders o JOIN users u ON u.id=o.driver_id "
                "WHERE o.driver_id IS NOT NULL AND o.deleted_at IS NULL"
            )
            p5: list = []
            if args.get("date_from"):
                sql += " AND o.order_date >= ?"
                p5.append(args["date_from"])
            if args.get("date_to"):
                sql += " AND o.order_date <= ?"
                p5.append(args["date_to"])
            sql += " GROUP BY u.full_name ORDER BY 3 DESC LIMIT 30"
            rows = cur.execute(sql, p5).fetchall()
            return {"settlement": [{"driver": r[0], "orders": r[1], "freight_total": r[2]} for r in rows]}

        return {"error": f"未知工具 {name}"}
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 问题集
#   ⚠️ 这 12 条是**候选模板**，必须由真实派单员的原话替换（见方案 §3.4）。
#      expect: 期望工具 + 期望参数（None=不校验）；kind: 该问题属于哪类价值区。
# ---------------------------------------------------------------------------
QUESTIONS: list[dict] = [
    {"id": "Q01", "q": "今天还有几单没派出去？", "expect_tool": "pending_dispatch_count",
     "expect_args": {}, "kind": "单页筛选（现有页面 1 步可达）"},
    {"id": "Q02", "q": "昨天派出去的 3 单司机接了吗？", "expect_tool": "list_orders",
     # 修正（v1 期望值写错）：该问法模型理解为"昨天日期范围"，是合理语义。
     # 只校验日期落在昨天，不强制 status —— 强制 status 属于判分器自身错误。
     "expect_args": {}, "expect_date": "yesterday", "kind": "单页筛选"},
    {"id": "Q03", "q": "老王家最近下过什么单？", "expect_tool": "list_orders",
     "expect_args": {"q": "老王"}, "kind": "实体解析（?q= 已覆盖）"},
    {"id": "Q04", "q": "李四那批货送到哪了？", "expect_tool": "list_orders",
     "expect_args": {"q": "李四"}, "kind": "实体解析（?q= 已覆盖）"},
    {"id": "Q05", "q": "这个月一共做了多少营业额？", "expect_tool": "report_turnover",
     "expect_args": {}, "kind": "跨模块聚合"},
    {"id": "Q06", "q": "上个月毛利多少？成本覆盖了多少行？", "expect_tool": "report_turnover",
     "expect_args": {}, "kind": "跨模块聚合 + 覆盖率"},
    {"id": "Q07", "q": "哪些货主欠账最多？", "expect_tool": "ledger_accounts",
     "expect_args": {"kind": "shipper"}, "kind": "跨模块聚合"},
    {"id": "Q08", "q": "批发商里谁走货最多？", "expect_tool": "ledger_accounts",
     "expect_args": {"kind": "member"}, "kind": "跨模块聚合"},
    {"id": "Q09", "q": "这个月每个司机跑了多少单、该结多少钱？", "expect_tool": "freight_settlement",
     "expect_args": {}, "kind": "跨模块聚合"},
    {"id": "Q10", "q": "司机里谁送货最准时？", "expect_tool": "driver_performance",
     "expect_args": {}, "kind": "跨模块聚合"},
    {"id": "Q11", "q": "已派单但司机三天没接的有几单？", "expect_tool": "list_orders",
     "expect_args": {"status": "DISPATCHED"}, "kind": "多约束组合（?q= 表达不了）"},
    {"id": "Q12", "q": "已送达但运费还没定价的单子有哪些？", "expect_tool": "list_orders",
     "expect_args": {"status": "DELIVERED"}, "kind": "多约束组合"},
]


# ---------------------------------------------------------------------------
# 模型调用
# ---------------------------------------------------------------------------
def _api_key() -> str:
    k = os.environ.get("DEEPSEEK_API_KEY")
    if k:
        return k.strip()
    if CRED.exists():
        txt = CRED.read_text(encoding="utf-8", errors="ignore")
        for line in txt.splitlines():
            if "DEEPSEEK_API_KEY" in line and ":" in line:
                return line.split(":", 1)[1].strip().strip("'\"")
    sys.exit("拿不到 DEEPSEEK_API_KEY（环境变量或 ~/.dsh/.credentials.yaml）")


SYSTEM = (
    "你是 SOrders 派单系统的查询助手。用户是派单员。"
    "你必须调用提供的工具来获取数据，禁止凭记忆猜测数字。"
    "如果用户的问题需要多个工具，先调用最必要的那一个。"
    "只能使用给定工具，不要编造工具名。"
    f"今天是 {date.today().isoformat()}。"
)


def ask_model(question: str) -> dict:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
        ],
        "tools": [_tool_schema(t) for t in TOOLS],
        "tool_choice": "auto",
        "temperature": 0,
    }
    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {_api_key()}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:400]}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}

    msg = (data.get("choices") or [{}])[0].get("message") or {}
    calls = msg.get("tool_calls") or []
    if not calls:
        return {"tool": None, "args": {}, "content": (msg.get("content") or "")[:300],
                "usage": data.get("usage", {})}
    fn = calls[0].get("function") or {}
    try:
        args = json.loads(fn.get("arguments") or "{}")
    except Exception:  # noqa: BLE001
        args = {"__unparsable__": fn.get("arguments")}
    return {"tool": fn.get("name"), "args": args, "n_calls": len(calls),
            "usage": data.get("usage", {})}


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------
def score_one(expect: dict, got: dict) -> tuple[bool, str]:
    if got.get("error"):
        return False, f"调用失败: {got['error'][:80]}"
    if got.get("tool") != expect["expect_tool"]:
        return False, f"工具错: 期望 {expect['expect_tool']} 实得 {got.get('tool')}"
    if expect.get("expect_date"):
        want = (date.today() - timedelta(days=1)).isoformat()
        args = got.get("args", {})
        if want not in {args.get("date_from"), args.get("date_to")}:
            return False, f"日期错: 期望含 {want} 实得 {args.get('date_from')}~{args.get('date_to')}"
    for k, v in (expect.get("expect_args") or {}).items():
        if got.get("args", {}).get(k) != v:
            return False, f"参数 {k} 错: 期望 {v} 实得 {got.get('args', {}).get(k)}"
    return True, "OK"


def cmd_probe() -> None:
    con = _conn()
    cur = con.cursor()
    print(f"库: {DB}")
    print("订单日期范围:", cur.execute("SELECT MIN(order_date), MAX(order_date) FROM orders").fetchone())
    print("按状态:")
    for r in cur.execute(
        "SELECT status, COUNT(*), ROUND(SUM(COALESCE(freight_fee,0)),2) FROM orders "
        "WHERE deleted_at IS NULL GROUP BY status"
    ):
        print(f"   {r[0]:<20} {r[1]:>6} 单  运费合计 {r[2]}")
    print("运费待定价且已派/已接:",
          cur.execute("SELECT COUNT(*) FROM orders WHERE freight_fee IS NULL "
                      "AND status IN ('DISPATCHED','ACCEPTED')").fetchone()[0])
    print("已派单超过3天未接单:",
          cur.execute("SELECT COUNT(*) FROM orders WHERE status='DISPATCHED' "
                      "AND dispatched_at IS NOT NULL "
                      "AND julianday('now')-julianday(dispatched_at)>3").fetchone()[0])
    print("挂账未付单数/金额:",
          cur.execute("SELECT COUNT(*), ROUND(SUM(COALESCE(freight_fee,0)),2) FROM orders "
                      "WHERE paid=0 AND payment_method='arrears'").fetchone())
    print("ledgers 来源分布:", cur.execute("SELECT source, COUNT(*) FROM ledgers GROUP BY source").fetchall())
    con.close()


def cmd_dry() -> None:
    print(f"共 {len(QUESTIONS)} 条问题（模板，需用真实派单员原话替换）")
    print(f"{'id':<5}{'期望工具':<24}{'类别':<28}问题")
    for q in QUESTIONS:
        print(f"{q['id']:<5}{q['expect_tool']:<24}{q['kind']:<28}{q['q']}")
    print("\n工具 -> 真实端点映射：")
    for t in TOOLS:
        print(f"   {t['name']:<24} {t['endpoint']}")


def cmd_run(limit: int | None, only: str | None = None) -> None:
    qs = QUESTIONS
    if only:
        want = {x.strip().upper() for x in only.split(",") if x.strip()}
        qs = [q for q in qs if q["id"].upper() in want]
    if limit:
        qs = qs[:limit]
    OUT.write_text("", encoding="utf-8")
    ok = bad = 0
    with OUT.open("a", encoding="utf-8") as f:
        for q in qs:
            got = ask_model(q["q"])
            passed, why = score_one(q, got)
            ok += passed
            bad += (not passed)
            rec = {**q, "got": got, "pass": passed, "why": why}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            flag = "PASS" if passed else "FAIL"
            print(f"[{flag}] {q['id']} {q['q'][:30]:<32} -> {got.get('tool')} {got.get('args')}  [{why}]")
    print(f"\n合计 {len(qs)} 条：通过 {ok}，未通过 {bad}（准确率 {ok / max(len(qs),1):.0%}）")
    print(f"明细已写 {OUT.name}；跑 python _ai_p0_probe.py --score 看判据表")


def cmd_score() -> None:
    if not OUT.exists():
        sys.exit(f"没有 {OUT.name}，先跑 --run")
    recs = [json.loads(x) for x in OUT.read_text(encoding="utf-8").splitlines() if x.strip()]
    by_kind: dict[str, list[bool]] = {}
    for r in recs:
        by_kind.setdefault(r["kind"], []).append(r["pass"])
    print(f"{'类别':<30}{'通过/总数':<12}通过率")
    for k, v in by_kind.items():
        print(f"{k:<30}{sum(v)}/{len(v):<10}{sum(v) / len(v):.0%}")
    print("\n按方案 §3.3 判据：")
    n = len(recs)
    acc = sum(r["pass"] for r in recs) / max(n, 1)
    hard = [r for r in recs if "现有页面" in r["kind"] or "组合" in r["kind"] or "跨模块" in r["kind"]]
    hard_rate = len(hard) / max(n, 1)
    print(f"  ① 选对率 = {acc:.0%}（通过线 ≥90%）→ {'达标' if acc >= 0.9 else '未达标'}")
    print(f"  ② '现有搜索/页面答不了'的类别占比 = {hard_rate:.0%}（通过线 ≥25%）"
          f"→ {'继续评估' if hard_rate >= 0.25 else '停：不做 AI，只扩查询参数'}")
    for r in recs:
        if not r["pass"]:
            print(f"  未通过 {r['id']}: {r['why']}")


def main() -> int:
    # Windows 控制台默认 GBK，中文/箭头会炸；统一切到 UTF-8 并容错
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--only", type=str, default=None, help="只跑指定题号，逗号分隔，如 Q11,Q12")
    a = ap.parse_args()
    if a.probe:
        cmd_probe()
    elif a.dry:
        cmd_dry()
    elif a.run:
        cmd_run(a.limit, a.only)
    elif a.score:
        cmd_score()
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
