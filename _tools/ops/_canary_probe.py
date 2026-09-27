# -*- coding: utf-8 -*-
"""Canary 观察用的**有限写**探针（R4-21 起；按 docs/PRODUCTION_ACCEPTANCE.md §三 的纪律）。

⛔ 纪律（那份文档自己写的，逐条照做）：
  1. **不用生产做"完整写操作测试"**：只做有限写 —— 建 1 张测试单、派 1 次、撤 1 次；
  2. 每一步都留痕：操作前后的行数、单号、金额；
  3. 测试数据**当场撤掉**（撤销而不是删除）；
  4. 任何一条不符合判据 → 停手。

⛔ 它只做那三件事：**不碰任何真实订单**（只新建自己那一张）。
"""
from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# ⛔ 生产主机**只从 _prodssh 那一处来**（本仓库的硬规矩：写两遍的那一份迟早在半夜暴露）。
#    第一版这里直接写了 IP，`_check_ops.py` 当场报「这些脚本里又写了一遍生产主机」。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prodssh import PROD_HOST  # noqa: E402

BASE = "https://" + PROD_HOST
PHONE, PASSWORD = "13800000001", "123321"
ADDRESS = "惠城区演达大道59号"     # 取自一条**真实的**已派单记录（这样价目一定能匹配上）
DRIVER_ID = 167                    # 同上那条单的司机
MARK = "R4-21 Canary 观察用（勿派送）"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE    # 生产是「IP + 项目私有 CA」（与 _prod_api_smoke.py 同一处理）


def call(path: str, token: str | None = None, body: dict | None = None) -> tuple[int, str]:
    req = urllib.request.Request(BASE + path, method="POST" if body is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data, timeout=60, context=CTX) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, type(e).__name__ + ": " + str(e)


def main() -> int:
    st, body = call("/api/v1/auth/login", body={"phone": PHONE, "password": PASSWORD})
    print("① 登录派单员：" + str(st))
    if st != 200:
        print("   " + body[:200])
        return 1
    tok = json.loads(body)["access_token"]
    print("   token 已拿到（⛔ 不打印）")

    st, body = call("/api/v1/orders", tok, {
        "shipper_id": 2,
        "lines": [{"product_name_snapshot": MARK, "quantity": 1,
                   "unit_price": "100", "line_total": "100"}],
        "address_detail": ADDRESS,
        "remark": MARK,
    })
    print("② 建测试单：" + str(st))
    if st not in (200, 201):
        print("   " + body[:300])
        return 1
    oid = json.loads(body)["id"]
    print("   订单 id = " + str(oid) + "（号码桶 id%100 = " + str(oid % 100) + "）")

    st, body = call("/api/v1/orders/" + str(oid) + "/assign", tok,
                    {"driver_id": DRIVER_ID, "freight_fee": FEE})
    print("③ 派单（带运费 " + FEE + "）：" + str(st))
    if st not in (200, 201):
        print("   " + body[:300])
        call(f"/api/v1/orders/{oid}/cancel", tok, {})
        return 1
    print("   订单号 = " + str(json.loads(body).get("order_no")))

    print("ORDER_ID=" + str(oid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
