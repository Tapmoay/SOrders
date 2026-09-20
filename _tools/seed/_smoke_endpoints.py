# -*- coding: utf-8 -*-
"""冒烟：拿三个开发账号把**只读接口**各打一遍，只认一件事 —— **有没有 5xx**。

## 为什么必须有它（不是"顺手写的"）

这一轮我在种子里把三处**词表**写错了（`vehicle_type` 写中文、`expenses.category` 写中文、
`driver_settlements.settle_type` 写大写），每一次的表现都是同一个形状：

> **写库一声不响，读接口 500**（Pydantic 校验枚举失败），而且只有**那个**端点挂，
> 别的页面照样能用 —— 打开 App 看一眼是发现不了的（第一版就是这么漏掉的：
> 账本页正常，派单作业页整个打不开）。

`_verify_demo_data.py` 查的是**库**，它管不了"读接口会不会炸"；这份脚本查的是**接口**。
两者一起跑，才算把"这份数据能不能用"验完。

## 清单从哪来（**自己算**，不手写）

`docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` 是机器生成的（`backend/scripts/gen_endpoint_index.py`），
所以这里直接**解析它**：所有 **GET**、且路径里**没有 `{参数}`** 的端点，三端各打一遍。
新加一个无参 GET 不需要谁来登记，自动就在覆盖里。

少数几个**必须带查询参数**的端点（账本日期窗口、报表周期…）写在 [WITH_PARAMS] 里，
每一条都写了理由 —— 这些恰恰是最容易 500 的地方（金额/枚举都在这儿）。

判定：**只把 5xx 当失败**。403/401（角色不行）、404（没有这条）、422（后端说你没给必填参数）
都不是数据的问题，分别计入报告。用法（后端要在跑）：

    python _tools/seed/_smoke_endpoints.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md"
BASE = "http://127.0.0.1:8000"
ACCOUNTS = {"派单员": "13800000001", "货主": "13800000002", "司机": "13800000003"}

#: 必须带查询参数才打得通的端点（自动清单覆盖不到）。**每一条都要有理由。**
WITH_PARAMS = {
    "派单员": [
        ("/api/v1/orders?status=PENDING_DISPATCH", "派单作业页的首屏：待派池"),
        ("/api/v1/orders?deleted_only=true", "回收站（软删隔离区）"),
        ("/api/v1/ledger/entries?date_from=2026-09-01&date_to=2026-09-30", "账本流水要日期窗口"),
        ("/api/v1/ledger/accounts?kind=shipper&date_from=2026-06-01&date_to=2026-09-30", "货主账聚合"),
        ("/api/v1/ledger/accounts?kind=member&date_from=2026-06-01&date_to=2026-09-30", "批发商账聚合"),
        ("/api/v1/freight-settlement?from=2026-06-01&to=2026-09-30", "司机账（按司机聚合）"),
        ("/api/v1/inventory/movements?date_from=2026-08-01&date_to=2026-08-31", "库存流水按月份过滤"),
        ("/api/v1/reports/turnover?date=2026-09-01", "营业额报表（按日）"),
        ("/api/v1/stats/driver-performance?date_from=2026-06-01&date_to=2026-09-30", "司机绩效"),
        ("/api/v1/expenses?category=fuel", "开销按分类过滤（分类词表就在这里）"),
        ("/api/v1/notifications?limit=20&days=30", "消息中心（默认保留期 30 天）"),
    ],
    "货主": [("/api/v1/orders?limit=20", "我的订单首屏")],
    "司机": [("/api/v1/orders?limit=20", "我的任务首屏")],
}

#: 明确不打的（**每条都要有理由**，否则"没打"和"打了但没问题"分不清）
SKIP = {
    "/static/{file_path:path}": "要一个真实存在的文件路径，冒烟给不出",
    "/api/v1/ledger/export/{job_id}/download": "导出产物是文件流，且要真实 job_id",
}


def endpoints_from_index() -> tuple[list[str], list[str]]:
    """解析机器生成的端点索引 → (无参 GET 路径, 解析失败的说明)。"""
    text = INDEX.read_text(encoding="utf-8")
    # 表行形如：`| 1 | \`GET /api/v1/orders\` | \`list_orders\` | 文件:行 | 授权 |`
    # （最前面那一列的序号可有可无：app 级路由那张表就没有序号，所以写成可选）
    rows = re.findall(r"^\|(?:\s*\d+\s*\|)?\s*`(GET|POST|PUT|PATCH|DELETE)\s+([^`]+)`\s*\|", text, re.M)
    if not rows:
        return [], [f"索引里一行都没解析出来（{INDEX}）"]
    out: list[str] = []
    notes: list[str] = []
    for method, path in rows:
        if method != "GET" or "{" in path:
            continue
        if path in SKIP:
            notes.append(f"跳过 {path}：{SKIP[path]}")
            continue
        if path not in out:
            out.append(path)
    return out, notes


def main() -> int:
    auto, notes = endpoints_from_index()
    for n in notes:
        print(f"（{n}）")
    if len(auto) < 40:
        print(f"✗ 从索引里只解析出 {len(auto)} 个无参 GET —— 清单失效了（不许静默通过）")
        return 1
    print(f"从端点索引解析出 {len(auto)} 个无参 GET，三端各打一遍（后端要在 127.0.0.1:8000 跑着）\n")

    fails: list[str] = []
    for who, phone in ACCOUNTS.items():
        r = requests.post(f"{BASE}/api/v1/auth/login",
                          json={"phone": phone, "password": "123321"}, timeout=10)
        if r.status_code != 200:
            fails.append(f"{who} 登录失败 {r.status_code} {r.text[:120]}")
            continue
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        tally = {"200": 0, "403": 0, "404": 0, "422": 0, "5xx": 0, "其它": 0}
        for path in auto + [p for p, _ in WITH_PARAMS.get(who, [])]:
            try:
                rr = requests.get(BASE + path, headers=h, timeout=25)
            except Exception as e:                                     # noqa: BLE001
                fails.append(f"{who} {path} 连不上：{e}")
                tally["5xx"] += 1
                continue
            if rr.status_code == 200:
                tally["200"] += 1
            elif rr.status_code in (401, 403):
                tally["403"] += 1
            elif rr.status_code == 404:
                tally["404"] += 1
            elif rr.status_code in (400, 422):
                # 后端说"你没给必填参数"（400 带人话、422 带字段名）—— 这份冒烟给不出全部参数，
                # 那是**合法响应**，不是数据问题（实测 `/freight-settlement` 不带范围就是 400）。
                tally["422"] += 1
            elif rr.status_code >= 500:
                tally["5xx"] += 1
                fails.append(f"{who} {path} → {rr.status_code} {rr.text[:120]}")
            else:
                tally["其它"] += 1
                fails.append(f"{who} {path} → {rr.status_code} {rr.text[:120]}")
        print(f"  {who}：200×{tally['200']} / 403×{tally['403']} / 404×{tally['404']} / "
              f"422×{tally['422']}（缺参数）/ **5xx×{tally['5xx']}** / 其它×{tally['其它']}")

    print()
    if fails:
        print(f"❌ {len(fails)} 个端点有问题：")
        for f in fails:
            print("   - " + f)
        return 1
    print("✅ 三端只读接口全部没有 5xx（403/404/422 属于账号权限或参数，不是数据问题）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
