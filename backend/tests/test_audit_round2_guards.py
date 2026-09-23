"""2026-09-19 全系统审计第二轮的修复：把"改回去就会出事"的判据钉住。

每一条都对应一个真实缺陷（都有实测/实盘证据），而不是风格约束：

| 判据 | 原来的样子 | 真实后果 |
|---|---|---|
| 手工记账不许伪造 `source=order` | 照抄请求体 | 凭空多一行账，**并顺带改写已送达订单的商品行金额**（绕开状态锁与审计） |
| 客户合并 `keep_id` 不许出现在待合并里 | 无校验 | `{"keep_id":5,"merge_ids":[5,6]}` → **两个客户档案都真删 + 500**，不可逆 |
| `GET /orders` 有缺省上限且如实回报 | 除"派单员+待派单"外全量 | 3 年数据后几万单一次性下发；且界面以为"这就是全部" |
| 资金收支按大小写不敏感判方向 | `f.direction == "IN"` | 枚举是小写 → 导出**流入/流出恒为 0**，且每笔收款印成"支出" |
| 毛利只用"有成本快照的行" | 收入收全部行、成本只有成本行 | 没快照的行以 0 成本 100% 进毛利（实测虚高 2.5 倍） |
| 导出产物不在公开静态目录 | 文件名可枚举 + `/static` 无鉴权 | 谁都能匿名下载别家账本 |
"""
from __future__ import annotations

from tests.conftest import auth_headers


def test_manual_ledger_entry_cannot_forge_order_source(client, token_dispatcher):
    """手工记账只许记「手动」来源；造 `source=order` 必须被拒。"""
    h = auth_headers(token_dispatcher)

    r = client.post(
        "/api/v1/ledger/entries",
        json={
            "shipper_id": 1,
            "entry_date": "2026-09-19",
            "product_name": "伪造订单账",
            "quantity": 1,
            "unit_price": "9999",
            "source": "order",
        },
        headers=h,
    )
    assert r.status_code == 400, r.text
    assert "手动" in r.json()["detail"]

    # 对照：手动记账仍然可用（别把正当需求一起堵死）
    r2 = client.post(
        "/api/v1/ledger/entries",
        json={
            "shipper_id": 1,
            "entry_date": "2026-09-19",
            "product_name": "正常手工账",
            "quantity": 1,
            "unit_price": "1",
            "source": "manual",
        },
        headers=h,
    )
    assert r2.status_code == 201, r2.text
    assert r2.json()["source"] in ("manual", "MANUAL")


def test_customer_merge_rejects_keep_in_merge_ids(client, token_dispatcher):
    """把"要保留的那个客户"也放进待合并列表 → 必须 400，且一个档案都不许少。"""
    h = auth_headers(token_dispatcher)

    r = client.post("/api/v1/customers", json={"name": "审计探针客户A"}, headers=h)
    assert r.status_code in (200, 201), r.text
    cid = r.json()["id"]

    before = {c["id"] for c in client.get("/api/v1/customers", headers=h).json()}

    bad = client.post("/api/v1/customers/merge", json={"keep_id": cid, "merge_ids": [cid]}, headers=h)
    assert bad.status_code == 400, bad.text

    after = {c["id"] for c in client.get("/api/v1/customers", headers=h).json()}
    assert after == before, "被拒的请求不该动任何数据（原来是两个档案都真删 + 500）"


def test_orders_list_has_default_limit_and_reports_truncation(client, token_dispatcher, token_shipper):
    """`GET /orders` 缺省必须有上限，并用响应头如实说明有没有被截断。"""
    h = auth_headers(token_shipper)
    r = client.get("/api/v1/orders", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Result-Limit") == "300"
    assert r.headers.get("X-Truncated") in ("0", "1")
    assert len(r.json()) <= 300


def test_finance_export_uses_case_insensitive_direction():
    """资金收支的方向判断必须大小写不敏感（枚举值是小写 in/out）。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app/api/v1/reports.py").read_text(encoding="utf-8")
    assert 'str(f.direction).lower() == "in"' in src
    assert 'str(f.direction).lower() == "out"' in src
    # 反例：写死大写就永远是 0（这条断言的作用就是拦住"顺手改回大写"）
    assert 'f.direction == "IN"' not in src
    assert 'f.direction == "OUT"' not in src


def test_gross_profit_only_counts_rows_with_cost_snapshot():
    """毛利 = 有成本快照那批行的收入 − 那批行的成本；两侧必须同一批行。

    ⚠️ 2026-09-23（第 17 轮）改过这条断言：原来钉的是 `cost_covered_amount += lp.line_total`
    （**毛额**），而营业纵览那一侧一直用的是净额（`line_receivable`，扣掉退货）——
    两处相差 ¥19.90 那一类缺陷正是被这条断言"钉住"的（它把错的那一侧写进了判据）。
    现在两侧同源：商品经营也走 `net_amount = line_receivable(lp)` 与 `max(0, net_qty)`，
    逐项相等的**行为**判据在 `tests/test_report_gross_profit_one_source.py`。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    reports = (root / "app/api/v1/reports.py").read_text(encoding="utf-8")
    schema = (root / "app/schemas/reports.py").read_text(encoding="utf-8")

    assert "cost_covered_amount" in schema
    assert "cost_covered_amount += net_amount" in reports
    assert "net_amount = line_receivable(lp)" in reports, (
        "收入侧必须是净额（行金额 − 退掉那部分），与营业纵览同源"
    )
    # 反例：不许再退回"毛额进毛利"（那是被治掉的那个缺陷的形状）
    assert "cost_covered_amount += lp.line_total" not in reports
    assert "cost_total += cost * Decimal(lp.quantity)" not in reports, (
        "成本必须按净件数算，不能按原数量"
    )
    # 导出里的毛利必须用"参与计算的收入"，不能用全部营业额
    assert 'data["cost_covered_amount"] - data["cost_total"]' in reports
    assert 'data["total_amount"] - data["cost_total"]' not in reports


def test_ledger_export_is_not_in_public_static_dir():
    """导出产物不许落在公开静态目录，且静态路由要明确拒绝 exports/。

    ⚠️ 2026-09-19 审计 R12-A1 之后改名与定位规则收敛到了 `ledger_export_paths.py`
    （原来"生成处拼名字、任务行存 URL、下载端点猜文件名"三份各写各的，
    结果是下载端点读了一个**不存在的属性** → 每次下载 500）。断言跟着挪过去。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    paths_src = (root / "app/services/ledger_export_paths.py").read_text(encoding="utf-8")
    export_src = (root / "app/services/ledger_export.py").read_text(encoding="utf-8")
    main_src = (root / "app/main.py").read_text(encoding="utf-8")

    assert 'EXPORT_DIR = Path("exports")' in paths_src
    assert "uploads" in paths_src  # 历史产物目录只用于兼容读取
    assert '== "exports"' in main_src  # 静态路由对 exports/ 一律 404
    # 下载地址只有一处实现（`download_url`），且端点确实用它
    assert "def download_url(" in paths_src
    assert "export-jobs/{job_id}/download" in paths_src
    # 生成函数返回的是**文件名**（数据库里存"产物叫什么"），不再返回 URL
    assert "return fname" in export_src


def test_pay_settlement_uses_conditional_claim():
    """司机结算付款必须是原子占位（并发付款会写出两条支出流水 = 同一笔钱扣两次）。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app/services/accounting_service.py").read_text(encoding="utf-8")
    assert "update(DriverSettlement)" in src
    assert "DriverSettlement.status == SettlementStatus.CONFIRMED" in src
    assert "claimed.rowcount != 1" in src


def test_assign_driver_checks_is_active():
    """派单给已停用/已删除的司机会让订单静默卡死，唯一写路径必须有这道闸。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app/services/order_flow.py").read_text(encoding="utf-8")
    assert 'getattr(driver, "is_active", True)' in src
    assert "账号已停用" in src
