"""计费规则 ↔ 价目的**引用完整性**：删价目不许把规则卡变成骗人的、也不许把规则锁死。

## 缺陷长什么样（2026-09-24 第 22 轮 F11-1，静态可证）
`DELETE /freight-templates/{id}` 只清了分类绑定（`freight_template_categories`），
**没管计费规则的绑定**（`driver_billing_rule_templates`），于是同一处有三连后果：

| # | 后果 | 证据 |
|---|---|---|
| ① | 规则的卡照旧印着这条价目（`_template_briefs` 不排软删）—— 看着像还算钱 | 卡上「惠州江北 → 东莞樟木头 ¥62」 |
| ② | 而钱早就不按它算了 → **这条路线所有单进「待定价」** | `freight_pricing` 已排除软删价目 |
| ③ | 那条规则**再也保存不了**：`_check_templates` 拒收软删价目，选择器只列活价目 → **没法取消勾选**，报错只有编号 | 400「勾的价目里有对不上的编号：[T]」 |
| ④ | 规则若还挂着司机，规则本身也不许删 → 只能先恢复价目才解得开 | `delete_rule` 挂人时拒绝 |

## 修法（三件事，缺一件都留着死结）
1. **删除侧挡住**：`delete_template` 发现活规则还勾着它 → 400，并**点名是哪份规则**
   （口径与"规则还挂着司机时不许删规则"一致：先说清谁在用，再让用户自己去解开）。
2. **卡片说真话**：`_template_briefs` 对已删价目标「**已删除**，不再算钱」——
   库里**已有的**幽灵链接（本轮之前删的那些）也要看得见。
3. **给出路**：`_check_templates(existing=…)` 放行"本来就在这份规则上"的编号
   （App 草稿整份回传，用户取消不掉它），但**不写进链接表** → 保存那一刻幽灵被清掉。
   新**加**一个已删编号照旧 400。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from app.models import FreightTemplate
from tests.conftest import auth_headers


def _uniq(prefix: str) -> str:
    """规则名/价目名要唯一：测试库跨轮次保留（API 会 commit），写死名字第二轮就 409。"""
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


def _mk_template(client: TestClient, token_dispatcher: str, **kw) -> dict:
    body = {"name": _uniq("价目"), "from_place": "引用完整性-起点", "to_place": "引用完整性-终点",
            "fee": "62.00"}
    body.update(kw)
    r = client.post("/api/v1/freight-templates", headers=auth_headers(token_dispatcher), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_rule(client: TestClient, token_dispatcher: str, **kw) -> dict:
    body = {"name": _uniq("规则"), "piece_amount": "200", "remark": "引用完整性测试"}
    body.update(kw)
    r = client.post("/api/v1/driver-billing-rules", headers=auth_headers(token_dispatcher), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _briefs(client: TestClient, token_dispatcher: str, rule_id: int) -> tuple[list[int], list[str]]:
    rows = client.get(
        "/api/v1/driver-billing-rules", headers=auth_headers(token_dispatcher)
    ).json()
    row = next(r for r in rows if r["id"] == rule_id)
    return row["template_ids"], row["template_briefs"]


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_删掉被规则勾着的价目要被挡住并点名(client: TestClient, token_dispatcher: str) -> None:
    """①②④ 的源头：正被规则勾着的价目不许删 —— 理由要点名是哪份规则。"""
    h = auth_headers(token_dispatcher)
    tpl = _mk_template(client, token_dispatcher)
    rule = _mk_rule(client, token_dispatcher, template_ids=[tpl["id"]])

    r = client.delete(f"/api/v1/freight-templates/{tpl['id']}", headers=h)
    assert r.status_code == 400, (
        f"删一条正被规则勾着的价目居然成功了（{r.status_code}）——"
        "那会让规则卡照旧印着它、却不再按它算钱，而且规则以后再也保存不了"
    )
    detail = r.json()["detail"]
    assert rule["name"] in detail, f"理由要点名是哪份规则在用它：{detail}"
    assert "不能删" in detail

    # 价目还在（列表里看得见），规则也照旧勾着它
    names = [t["name"] for t in client.get("/api/v1/freight-templates", headers=h).json()]
    assert tpl["name"] in names, "被挡住之后价目不该消失"
    ids, briefs = _briefs(client, token_dispatcher, rule["id"])
    assert ids == [tpl["id"]] and any("¥62" in b for b in briefs), briefs


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_规则卡对已删价目要如实标注并能走出去(
    client: TestClient, db_session, token_dispatcher: str
) -> None:
    """库里**已有的**幽灵链接：卡片要如实标注，且这份规则不能因此永远保存不了。

    直接用库把价目标成软删（而不是走 DELETE）——这正是本轮之前那次删除留下的形状。
    """
    h = auth_headers(token_dispatcher)
    tpl = _mk_template(client, token_dispatcher)
    rule = _mk_rule(client, token_dispatcher, template_ids=[tpl["id"]])

    # 造出"历史遗留"的幽灵：价目被软删，链接还在
    row = db_session.get(FreightTemplate, tpl["id"])
    row.is_deleted = True
    db_session.commit()
    db_session.expire_all()

    ids, briefs = _briefs(client, token_dispatcher, rule["id"])
    assert ids == [tpl["id"]], "链接还在（这正是要处理的形状）"
    assert any("已删除" in b and "不再算钱" in b for b in briefs), (
        f"卡片必须说清这条价目已经删了、不再算钱（否则就是'卡上写 62 元、实际进待定价'）：{briefs}"
    )

    # ★ 关键：照 App 草稿那样整份回传 → 必须能保存（原来这里 400，规则永远保存不了）
    r = client.put(
        f"/api/v1/driver-billing-rules/{rule['id']}",
        headers=h,
        json={"template_ids": [tpl["id"]], "remark": "引用完整性测试-只改备注"},
    )
    assert r.status_code == 200, f"只改备注都存不了（幽灵把它锁死了）：{r.text}"
    assert r.json()["template_ids"] == [], (
        "保存时应当把已删价目的链接顺手清掉（幽灵留着没有意义，还会一直显示在卡上）"
    )
    assert r.json()["template_briefs"] == []


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_新加一个已删价目仍然要被拒绝(
    client: TestClient, db_session, token_dispatcher: str
) -> None:
    """放宽的只许是"本来就在这份规则上"的编号 —— **新加**一个已删编号照旧 400。"""
    h = auth_headers(token_dispatcher)
    tpl = _mk_template(client, token_dispatcher)
    rule = _mk_rule(client, token_dispatcher)  # 这条规则**一条价目都没有**

    row = db_session.get(FreightTemplate, tpl["id"])
    row.is_deleted = True
    db_session.commit()

    r = client.put(
        f"/api/v1/driver-billing-rules/{rule['id']}", headers=h, json={"template_ids": [tpl["id"]]}
    )
    assert r.status_code == 400, "把一条已删价目新挂上去必须拒绝（那是真的错）"
    detail = r.json()["detail"]
    assert "已删" in detail or "对不上" in detail, detail
    # 报错要带上**名字**，不能只有一个编号（界面上没有编号可对照）
    assert tpl["name"] in detail, f"理由里要能认出是哪条价目：{detail}"

    remaining = db_session.scalars(
        select(FreightTemplate).where(FreightTemplate.id == tpl["id"])
    ).first()
    assert remaining is not None and remaining.is_deleted is True
