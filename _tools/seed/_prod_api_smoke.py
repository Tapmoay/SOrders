"""生产灌数后的**接口冒烟**：三个角色各登录一次，把每个页面依赖的读接口打一遍。

## 为什么要有它（与 `_verify_demo_data.py` 的分工）
`_tools/seed/_verify_demo_data.py` 查的是**库里**的行（派生行日期、口径、唯一键……）；
那个脚本全绿只说明"数据造对了"，**不等于界面能把它端出来**。报表/账本/结算这类接口
在数据量从 9 单变成 2400 单之后最容易暴露的问题恰恰不在数据里：
出参校验被 NULL 毒化（`freight_category` 那次）、除法分母为 0、一次拉太多超时、
金额格式化对负数/四位数不友好 —— 这些**只有真的打一次接口才会响**。

所以两者是接力：造完 → `_verify_demo_data.py`（库）→ **这个脚本（接口）** → 真机看页面。

## 用法
    python _tools/seed/_prod_api_smoke.py                    # 默认打生产 https://8.145.40.22
    python _tools/seed/_prod_api_smoke.py --base http://127.0.0.1:8000
    python _tools/seed/_prod_api_smoke.py --days 120         # 报表窗口（默认近 120 天）

退出码：0 = 全绿；1 = 有接口不是 200（会把状态码与响应体前 200 字打出来）。

⚠️ 它**只读**：全部是 GET。密码走参数（默认开发号那套 123321），不打进日志。
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

#: Windows 控制台默认 GBK，打 ✅/❌ 会 UnicodeEncodeError（仓库里其它脚本同款处理）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

#: 三个验收账号（与 seed / 真机用的是同一批）
ACCOUNTS = {
    "dispatcher": "13800000001",
    "shipper": "13800000002",
    "driver": "13800000003",
}


def call(base: str, path: str, token: str | None = None, body: dict | None = None,
         ctx: ssl.SSLContext | None = None) -> tuple[int, str]:
    req = urllib.request.Request(base + path, method="POST" if body else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body else None
    try:
        with urllib.request.urlopen(req, data, timeout=60, context=ctx) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 —— 连不上也算失败，但要如实说是什么
        return 0, f"{type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://8.145.40.22")
    ap.add_argument("--password", default="123321")
    ap.add_argument("--days", type=int, default=120)
    args = ap.parse_args()

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # 生产是「IP + 项目私有 CA」（App 里钉了那张 CA）

    today = date.today()
    frm = (today - timedelta(days=args.days)).isoformat()
    to = today.isoformat()
    win = f"from={frm}&to={to}"

    tokens: dict[str, str] = {}
    for role, phone in ACCOUNTS.items():
        st, body = call(args.base, "/api/v1/auth/login", body={"phone": phone, "password": args.password}, ctx=ctx)
        if st != 200:
            print(f"❌ 登录失败 {role}（{phone}）：HTTP {st} {body[:160]}")
            return 1
        tokens[role] = json.loads(body)["access_token"]
        print(f"✅ 登录 {role:<11} {phone}")

    # (角色, 路径, 这条接口对应界面上的哪一块)
    checks: list[tuple[str, str, str]] = [
        ("dispatcher", "/api/v1/orders?limit=5", "订单管理"),
        ("dispatcher", "/api/v1/orders?status=PENDING_DISPATCH&limit=5", "待派单池"),
        ("dispatcher", "/api/v1/orders/pending-dispatch-count", "待派单角标"),
        ("dispatcher", f"/api/v1/ledger/entries?{win}", "账本管理·订单账"),
        ("dispatcher", "/api/v1/ledger/accounts?kind=shipper", "账本管理·货主账"),
        ("dispatcher", f"/api/v1/freight-settlement?{win}", "司机运费结算"),
        # ⚠️ 报表那两个端点的参数是 `mode`(day|week|month) + **`date`（锚点日期）**，
        #    不是 from/to；统计那两个才是 `date_from`/`date_to`。
        #    （第一版这里写错了 4 条 —— 冒烟脚本第一次跑就把它们抓出来了，这正是它的用处。）
        ("dispatcher", f"/api/v1/reports/turnover?mode=month&date={to}", "报表中心·营业额"),
        ("dispatcher", f"/api/v1/reports/products?mode=month&date={to}", "报表中心·商品"),
        ("dispatcher", f"/api/v1/stats/driver-performance?date_from={frm}&date_to={to}", "报表中心·司机绩效"),
        ("dispatcher", f"/api/v1/stats/exception-orders?date_from={frm}&date_to={to}", "报表中心·异常与审计"),
        ("dispatcher", "/api/v1/driver-bills", "司机账单"),
        ("dispatcher", "/api/v1/expenses", "开销管理"),
        ("dispatcher", "/api/v1/customers", "客户档案"),
        ("dispatcher", "/api/v1/products", "商品管理"),
        ("dispatcher", "/api/v1/users?role=driver", "司机管理"),
        ("dispatcher", "/api/v1/places", "共享地点库"),
        ("dispatcher", "/api/v1/driver-billing-rules", "计费规则"),
        ("dispatcher", "/api/v1/freight-categories", "运费分类（09-21 新加）"),
        ("dispatcher", "/api/v1/return-requests?status=pending", "退货申请（09-21 新加）"),
        ("dispatcher", "/api/v1/notifications?days=7", "消息中心"),
        ("shipper", "/api/v1/orders?limit=5", "我的订单"),
        ("shipper", "/api/v1/shipper/addresses", "地址与联系人"),
        ("shipper", "/api/v1/return-requests/mine", "我的退货申请"),
        ("shipper", "/api/v1/notifications?days=7", "消息中心"),
        ("driver", "/api/v1/orders?limit=5", "我的任务"),
        ("driver", f"/api/v1/freight-settlement?{win}", "我的账本"),
        ("driver", "/api/v1/notifications?days=7", "消息中心"),
    ]

    bad: list[tuple[str, str, int, str]] = []
    for role, path, where in checks:
        st, body = call(args.base, path, token=tokens[role], ctx=ctx)
        ok = st == 200
        # 空列表也是合法结果（比如刚灌完还没有退货申请）——这里只看"能不能端出来"
        n = ""
        if ok:
            try:
                j = json.loads(body)
                if isinstance(j, list):
                    n = f"  共 {len(j)} 条"
                elif isinstance(j, dict) and isinstance(j.get("items"), list):
                    n = f"  共 {len(j['items'])} 条"
            except Exception:  # noqa: BLE001
                n = "  （非 JSON）"
        print(f"{'✅' if ok else '❌'} {role:<11} {path:<52} {where}{n}")
        if not ok:
            bad.append((role, path, st, body[:200]))

    print()
    if bad:
        print(f"❌ {len(bad)} 条接口不是 200：")
        for role, path, st, body in bad:
            print(f"   HTTP {st}  {role} {path}\n      {body}")
        return 1
    print(f"✅ 全部 {len(checks)} 条接口 200（三端页面依赖的读接口都端得出来）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
