"""「批发价档位」这个概念被删掉之后的两条守卫（2026-09-19 用户拍板）。

## 为什么删
`products.tier_prices` 存的是多档"批发价一/二/三"，但**下单时一个字节都不照它走** ——
下单只认 `price_rules` 里按（批发商 × 商品）存的专属价，没有专属价才用商品默认售价。
它此前只在两处当过"预设值"：`POST /price-rules/batch` 的 `mode="tier"`、
App「批发商定价」页那个能把档位价填进特价框的下拉。
"看着像批发价、实际谁都不照它成交"正是用户说的「操作与逻辑不匹配」，所以整套删掉。

⚠️ **数据不删**：`products.tier_prices` 这一列与历史数据保留在库里（不写迁移、不清数据），
只是不再被任何接口读写 —— 理由写在 `app/models/product.py` 的注释里。

## 这个文件守两件事
1. `GET /price-rules?product_id=` 能只回**这一个商品**的专属价。
   App 新增的「按商品看各批发商价」页要用它：以前只能按 `shipper_id` 筛，
   客户端要凑出"这一个商品的所有专属价"就只能**拉全表再自己过滤**——正是本轮刚修掉的毛病。
2. 档位模式**真的没了**：`mode="tier"` 现在是 422（硬拒），不是"接受但静默无效"。
"""
from __future__ import annotations

import random
from typing import get_args

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _uniq(prefix: str) -> str:
    return f"{prefix}-{random.randint(1000, 9999)}"


def _mk_member(client: TestClient, h: dict[str, str], name: str = "按商品筛价批发商") -> int:
    """建一个批发商（`is_member=True`）——批量调价那条路只认批发商。"""
    phone = "139" + "".join(random.choice("0123456789") for _ in range(8))
    r = client.post(
        "/api/v1/users",
        json={
            "phone": phone,
            "password": "pass12345",
            "full_name": name,
            "role": "shipper",
            "is_member": True,
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _mk_product(client: TestClient, h: dict[str, str], name: str, price: str = "20") -> dict:
    r = client.post(
        "/api/v1/products",
        json={"name": _uniq(name), "default_unit_price": price, "unit": "件"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _mk_rule(client: TestClient, h: dict[str, str], sid: int, pid: int, price: str) -> int:
    r = client.post(
        "/api/v1/price-rules",
        json={"shipper_id": sid, "product_id": pid, "special_unit_price": price},
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_按商品筛选只回这个商品的专属价(client: TestClient, token_dispatcher: str) -> None:
    """`?product_id=` 的判据：命中的一条不少、别的商品的一条都不许混进来。"""
    h = auth_headers(token_dispatcher)
    a = _mk_member(client, h, "按商品筛价甲")
    b = _mk_member(client, h, "按商品筛价乙")
    pa_body = _mk_product(client, h, "按商品筛价商品甲")
    pb_body = _mk_product(client, h, "按商品筛价商品乙")
    pa, pb = int(pa_body["id"]), int(pb_body["id"])

    # 出参里不该再有档位价（概念删了，字段也要从契约里消失）
    assert "tier_prices" not in pa_body, f"商品出参里还有 tier_prices：{pa_body}"

    ra = _mk_rule(client, h, a, pa, "12")          # 命中：甲批发商 × 甲商品
    rb = _mk_rule(client, h, b, pa, "13")          # 命中：乙批发商 × 甲商品（同商品、不同批发商）
    ra_other = _mk_rule(client, h, a, pb, "14")    # **不许出现**：甲批发商 × 乙商品
    assert len({ra, rb, ra_other}) == 3

    r = client.get(f"/api/v1/price-rules?product_id={pa}", headers=h)
    assert r.status_code == 200, r.text
    got = {int(x["id"]) for x in r.json()}
    assert got == {ra, rb}, (
        f"按商品筛应当**正好**回这个商品的两条，实际 {sorted(got)}"
        f"（多出来的多半是别的商品；少了的那条说明筛选把命中项也滤掉了）"
    )

    # 两个筛选是并列 AND：同时给 = "这个批发商的这个商品"
    r = client.get(f"/api/v1/price-rules?shipper_id={a}&product_id={pa}", headers=h)
    assert r.status_code == 200, r.text
    assert {int(x["id"]) for x in r.json()} == {ra}, r.text

    # 只给商品、这个商品没有价 → 空列表（不是"退化成全部"）
    empty_pid = _mk_product(client, h, "按商品筛价商品丙")["id"]
    r = client.get(f"/api/v1/price-rules?product_id={empty_pid}", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == [], f"没设过价的商品应当回空列表，实际 {r.text[:200]}"


@pytest.mark.shipper
@pytest.mark.fast
@pytest.mark.regression
def test_货主带别人的批发商编号只会拿到空列表(
    client: TestClient, token_dispatcher: str, token_shipper: str
) -> None:
    """角色那一层**先**把自己锁死，再叠加筛选条件 —— 顺序反了就是"报价串号"。

    `GET /price-rules` 对货主是"只读自己的专属价，用于下单时展示实际价格"。
    如果 `shipper_id` 在角色过滤**之前/之上**生效，货主随手换一个编号就能读到别人的价，
    而下单页正是拿这份价报价的（读得到就会照着报）。所以判据是：**必须空**，不是"别人那份"。
    """
    h = auth_headers(token_dispatcher)
    other = _mk_member(client, h, "别人的批发商")
    pid = int(_mk_product(client, h, "货主越权筛价商品")["id"])
    mine = _mk_rule(client, h, other, pid, "9")

    hs = auth_headers(token_shipper)
    r = client.get(f"/api/v1/price-rules?shipper_id={other}", headers=hs)
    assert r.status_code == 200, r.text
    assert r.json() == [], (
        f"货主带别人的 shipper_id 必须拿到空列表，实际拿到 {r.text[:200]}"
        f"（第 {mine} 条是别人的专属价——泄露了就会照着它报价）"
    )


@pytest.mark.dispatcher
@pytest.mark.fast
@pytest.mark.regression
def test_批量调价的档位模式现在被422拒掉且什么都没写(
    client: TestClient, token_dispatcher: str
) -> None:
    """**硬断言**：`mode="tier"` 必须 422，且不许留下任何价格。

    为什么不能只写"不再支持"：`Literal` 换掉之后如果哪天有人给它加个兜底分支，
    "传了 tier 但价格没动"会退化成一句"已完成"——用户以为改了价，实际一个字没变。
    """
    h = auth_headers(token_dispatcher)
    sid = _mk_member(client, h, "档位模式批发商")
    pid = int(_mk_product(client, h, "档位模式商品", price="20")["id"])

    r = client.post(
        "/api/v1/price-rules/batch",
        json={"shipper_ids": [sid], "product_ids": [pid], "mode": "tier", "value": "8"},
        headers=h,
    )
    assert r.status_code == 422, (
        f"mode=tier 应当被 schema 拒掉（422），实际 {r.status_code} {r.text[:200]}"
        "—— 档位这个概念已经删了，接受它就等于「接受但静默无效」"
    )
    detail = str(r.json().get("detail", ""))
    # 中文 + 能照着改：报错必须把允许的三档列出来（只写"取值不在允许范围内"等于没说）
    for allowed in ("fixed", "percent", "adjust"):
        assert allowed in detail, f"422 的中文报错里没列全允许的取值：{detail}"

    # 概念真的没了：这条请求不许留下任何价格
    after = client.get(f"/api/v1/price-rules?shipper_id={sid}&product_id={pid}", headers=h)
    assert after.status_code == 200, after.text
    assert after.json() == [], f"被拒的请求竟然写进了价格：{after.text[:200]}"


@pytest.mark.unit
@pytest.mark.fast
def test_档位字段从入参出参里消失但数据库列保留() -> None:
    """字段/模式全删；**列留着**（用户明确要求不写迁移、不清数据）。"""
    from app.models.product import Product
    from app.schemas.price_rule import PriceRuleBatchBody
    from app.schemas.product import ProductCreate, ProductOut, ProductUpdate

    for model in (ProductCreate, ProductUpdate, ProductOut):
        assert "tier_prices" not in model.model_fields, f"{model.__name__} 里还有 tier_prices"
    assert "tier_index" not in PriceRuleBatchBody.model_fields, "批量调价里还有 tier_index"

    modes = set(get_args(PriceRuleBatchBody.model_fields["mode"].annotation))
    assert modes == {"fixed", "percent", "adjust"}, f"mode 允许的取值不对：{sorted(modes)}"
    assert "tier" not in modes, "tier 又回到了 mode 的取值里"

    # ⚠️ 这条防的是"顺手把列也 drop 掉"：列与历史数据是**有意保留**的
    assert "tier_prices" in Product.__table__.columns, (
        "products.tier_prices 列被删了 —— 用户明确要求保留（不写迁移、不清数据）"
    )
