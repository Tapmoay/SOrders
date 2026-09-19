"""软删（在回收站里）的行**不许还能被改**（2026-09-19 审计的缺陷 R11-F4）。

## 原来的样子（真机/接口都能复现）
"删除"在本项目是**打标记**（`SoftDeleteMixin`）。每张这样的表都必须在三处尊重标记：
列表查询（有）、删除与恢复（有）、**改（漏了）**：

| 端点 | 漏了会怎样 |
|---|---|
| `PUT /freight-templates/{id}` | 改一条列表里看不见的模板 → 200「已完成」，界面上永远找不到它 |
| `PATCH /arrears-units/{id}` | 同上，而它名下的旧欠款还挂在账上（用户以为改的是"现在用的那一个"） |
| `PATCH /price-rules/{id}` | 改一条看不见的专属价 → 200，**还写一条"旧价→新价"的审计日志**，而批发商看到的价格一个字没变（审计追出来的是一次没发生过的调价） |
| `POST /shipper/addresses/{id}/set-default` | 把"默认地址"落在看不见的行上——`delete_address` 特意 `is_default=False` 防的就是这个，这里一句话能做回去 |

## 这个文件钉住什么
1. 四条路**都要 4xx**，而且原因里要能看出"已删除、先恢复"（不是"未找到"，那会让人以为编号错了）；
2. **库里那一行一个字都没变**（不能"报错但已经改了"）；
3. `price_rules` 那条**不许留下调价日志**（假审计比没有审计更糟）；
4. **反向对照**：没删的行照样能改（守卫不能把正常功能一起挡住）。
"""
from __future__ import annotations

from tests.conftest import auth_headers


def _create_template(client, h) -> int:
    r = client.post(
        "/api/v1/freight-templates",
        json={"name": "软删探针模板", "from_place": "甲地", "to_place": "乙地", "fee": 100},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_deleted_freight_template_cannot_be_updated(client, token_dispatcher, db_session):
    from app.models import FreightTemplate

    h = auth_headers(token_dispatcher)
    tid = _create_template(client, h)
    assert client.delete(f"/api/v1/freight-templates/{tid}", headers=h).status_code in (200, 204)

    r = client.put(
        f"/api/v1/freight-templates/{tid}",
        json={"name": "改个名试试", "fee": 999},
        headers=h,
    )
    assert r.status_code == 400, f"软删的模板不该能改：{r.status_code} {r.text}"
    assert "删除" in r.json()["detail"] and "恢复" in r.json()["detail"], r.json()

    # 库里那一行必须原样（"报错但其实改了"是最坏的一种）
    db_session.expire_all()
    row = db_session.get(FreightTemplate, tid)
    assert row is not None and row.is_deleted is True, row
    assert row.name == "软删探针模板" and float(row.fee) == 100.0, (row.name, row.fee)


def test_deleted_arrears_unit_cannot_be_updated(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/arrears-units", json={"name": "软删探针单位"}, headers=h)
    assert r.status_code in (200, 201), r.text
    uid = r.json()["id"]
    assert client.delete(f"/api/v1/arrears-units/{uid}", headers=h).status_code in (200, 204)

    r = client.patch(f"/api/v1/arrears-units/{uid}", json={"remark": "改了"}, headers=h)
    assert r.status_code == 400, f"软删的挂账单位不该能改：{r.status_code} {r.text}"
    assert "恢复" in r.json()["detail"], r.json()


def test_deleted_price_rule_cannot_be_updated_and_writes_no_price_log(client, token_dispatcher, db_session):
    """专属价这条最要紧：改它**会写一条调价审计日志**，而价格其实没变。"""
    from app.models import OperationAction, OperationLog, PriceRule, Product, User
    from decimal import Decimal

    h = auth_headers(token_dispatcher)
    product = Product(name="软删探针商品", default_unit_price=Decimal("10"), stock=0)
    db_session.add(product)
    db_session.flush()
    shipper = db_session.query(User).filter_by(phone="13800000002").first()
    rule = PriceRule(shipper_id=shipper.id, product_id=product.id, special_unit_price=Decimal("8.00"))
    db_session.add(rule)
    db_session.flush()
    rid = rule.id
    db_session.commit()

    assert client.delete(f"/api/v1/price-rules/{rid}", headers=h).status_code in (200, 204)
    before_logs = db_session.query(OperationLog).filter_by(action=OperationAction.PRICE_RULE_UPSERT).count()

    r = client.patch(f"/api/v1/price-rules/{rid}", json={"special_unit_price": 5.5}, headers=h)
    assert r.status_code == 400, f"软删的专属价不该能改：{r.status_code} {r.text}"
    after_logs = db_session.query(OperationLog).filter_by(action=OperationAction.PRICE_RULE_UPSERT).count()
    assert after_logs == before_logs, "被拒绝的改动不许留下『调价』审计日志（假审计比没有审计更糟）"
    db_session.refresh(rule)
    assert rule.special_unit_price == Decimal("8.00"), rule.special_unit_price


def test_deleted_address_cannot_be_set_default(client, token_dispatcher, db_session):
    from app.models import ShipperAddress, User

    h = auth_headers(token_dispatcher)
    me = db_session.query(User).filter_by(phone="13800000001").first()
    r = client.post(
        "/api/v1/shipper/addresses",
        json={"receiver_name": "软删探针", "phone": "13900000001", "detail_address": "探针路 1 号"},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    aid = r.json()["id"]
    assert client.delete(f"/api/v1/shipper/addresses/{aid}", headers=h).status_code in (200, 204)

    r = client.post(f"/api/v1/shipper/addresses/{aid}/set-default", headers=h)
    assert r.status_code == 400, f"软删的地址不该能设成默认：{r.status_code} {r.text}"
    assert "恢复" in r.json()["detail"], r.json()

    # 关键不变量：**默认标记不许落在看不见的行上**
    db_session.expire_all()
    stuck = (
        db_session.query(ShipperAddress)
        .filter(
            ShipperAddress.shipper_id == me.id,
            ShipperAddress.is_default.is_(True),
            ShipperAddress.is_deleted.is_(True),
        )
        .count()
    )
    assert stuck == 0, "「默认地址」落在了一条已删除、界面上看不见的地址上"


def test_live_rows_still_updatable(client, token_dispatcher):
    """反向对照：守卫只针对软删的行，没删的照常能改（否则这次修复会挡住正常功能）。"""
    h = auth_headers(token_dispatcher)
    tid = _create_template(client, h)
    r = client.put(f"/api/v1/freight-templates/{tid}", json={"fee": 250}, headers=h)
    assert r.status_code == 200, r.text
    assert float(r.json()["fee"]) == 250.0

    r = client.post("/api/v1/arrears-units", json={"name": "没删的探针单位"}, headers=h)
    uid = r.json()["id"]
    r = client.patch(f"/api/v1/arrears-units/{uid}", json={"remark": "还是能改"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["remark"] == "还是能改"
