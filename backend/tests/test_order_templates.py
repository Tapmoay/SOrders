"""预订单（订单模板）：空运费 ≠ 0 运费、部分更新、软删与恢复、审计留痕、权限。

## 为什么这几条必须钉住（每一条都是"不报错但会错"的形状）
1. **`freight_fee` 空与 `0` 是两件事**：前者是"这单不预设运费（下单时按规则算）"，
   后者是"免运费"。把空当 0 的后果是**每一张没填运费的预设单都变成免运费单** ——
   一键下单时钱就少收了，而界面上两个都显示"¥0.00"。
2. **部分更新不许把没提到的键覆盖成默认值**：`PATCH` 只传 `name` 时，
   货主/地址/行货/运费必须原样不动（写回默认值的表现是"改个名字把预设的商品清空了"）。
3. **`shipper_id` 必须能清空**（键出现就按给的值写）：从"固定货主"改回"下单时再选"。
4. **删了一律软删 + 能恢复**（用户定的硬规矩），并且**回收站里的预设单改不了**。
5. **每次写都要留痕**：预设单会变成真订单，"谁改的"必须查得到。

## 一条刻意钉住的**不做**：不校验商品是否存在
预设单只是一张便签 —— 商品可能今天建、明天改名、后天下架，而预设单要一直能存着。
真校验在下单那一刻（`POST /orders` 那条路本来就会校验商品与库存）。
⚠️ 这条行为有测试钉着（`test_预设单不校验商品是否存在`）：哪天要改成"存的时候就校验"，
请连着这条测试一起改，别让它变成"文档说校验、代码不校验"。
"""
from __future__ import annotations

import json

from sqlalchemy import select

from app.models import OperationLog
from tests.conftest import auth_headers

BASE = "/api/v1/order-templates"


def _mk(client, h, name: str, **over):
    body = {
        "name": name,
        "address": "惠风东三路40号",
        "receiver_name": "小张",
        "receiver_phone": "13512345678",
        "lines": [
            {"product_id": 9001, "name": "红富士苹果", "unit": "件", "qty": 6},
            {"product_id": 9002, "name": "赣南脐橙", "unit": "箱", "qty": 2},
        ],
    }
    body.update(over)
    r = client.post(BASE, json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _logs(db, action: str) -> list[dict]:
    rows = db.scalars(select(OperationLog).where(OperationLog.action == action)).all()
    return [json.loads(r.change_content or "{}") for r in rows]


def _ids(client, h) -> list[int]:
    """当前列表里的 id 顺序（⚠️ 测试库在**同一次运行里是累积的**：别的用例建的预设单还在，
    所以任何"整张列表等于什么"的断言都会假红 —— 一律用"相对顺序/在不在"来判）。"""
    return [r["id"] for r in client.get(BASE, headers=h).json()]


def test_建一张预设单_行货与字段都对(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "永盛食品每周单")
    assert t["name"] == "永盛食品每周单"
    assert [ln["name"] for ln in t["lines"]] == ["红富士苹果", "赣南脐橙"]
    assert [ln["qty"] for ln in t["lines"]] == [6, 2]
    assert t["shipper_id"] is None and t["shipper_name"] is None
    # ⚠️ 没填运费 = **不预设**（None），不是 "0.00"
    assert t["freight_fee"] is None
    # 列表里立刻能看到（内容从列表那条路回来也要一模一样）
    row = next(r for r in client.get(BASE, headers=h).json() if r["id"] == t["id"])
    assert row["lines"] == t["lines"] and row["address"] == "惠风东三路40号"


def test_免运费与不预设是两件事(client, token_dispatcher):
    """`freight_fee="0"` → `"0.00"`（就是免运费）；不传/传空 → `None`（不预设）。"""
    h = auth_headers(token_dispatcher)
    free = _mk(client, h, "免运费单", freight_fee="0")
    none = _mk(client, h, "不预设运费单")
    blank = _mk(client, h, "空字符串运费单", freight_fee="")
    assert free["freight_fee"] == "0.00"
    assert none["freight_fee"] is None
    assert blank["freight_fee"] is None, "空字符串也要当成「不预设」，不能悄悄变成 0"
    preset = _mk(client, h, "预设 38.5 的单", freight_fee="38.5")
    assert preset["freight_fee"] == "38.50", "金额出参一律两位小数"


def test_部分更新不许把没提到的键覆盖成默认值(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "原始名", freight_fee="12.00", remark="留着")
    r = client.patch(f"{BASE}/{t['id']}", json={"name": "改过的名"}, headers=h)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["name"] == "改过的名"
    assert got["remark"] == "留着", "只改名不该把备注清掉"
    assert got["freight_fee"] == "12.00", "只改名不该把预设运费清掉"
    assert len(got["lines"]) == 2, "只改名不该把预设的商品行清掉"


def test_货主可以清空_也可以重新指定(client, token_dispatcher, token_shipper, db_session):
    """`shipper_id` 走 `model_fields_set`：**键出现就按给的值写**（null = 清空）。"""
    h = auth_headers(token_dispatcher)
    me = client.get("/api/v1/users/me", headers=auth_headers(token_shipper)).json()
    t = _mk(client, h, "指定货主", shipper_id=me["id"])
    assert t["shipper_id"] == me["id"] and t["shipper_name"]
    cleared = client.patch(f"{BASE}/{t['id']}", json={"shipper_id": None}, headers=h).json()
    assert cleared["shipper_id"] is None, "显式传 null 必须能把货主清掉（改回「下单时再选」）"
    again = client.patch(f"{BASE}/{t['id']}", json={"shipper_id": me["id"]}, headers=h).json()
    assert again["shipper_id"] == me["id"]


def test_不给货主时不许乱塞一个编号(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    bad = client.post(BASE, json={"name": "x", "shipper_id": 999999}, headers=h)
    assert bad.status_code == 400 and "货主" in bad.json()["detail"]


def test_同一个商品两行要拒绝_没有商品的行也要拒绝(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    dup = client.post(
        BASE,
        json={"name": "重复行", "lines": [
            {"product_id": 7, "name": "苹果", "qty": 1},
            {"product_id": 7, "name": "苹果", "qty": 2},
        ]},
        headers=h,
    )
    assert dup.status_code == 400 and "又出现了一次" in dup.json()["detail"]
    empty = client.post(BASE, json={"name": "空行", "lines": [{"qty": 3}]}, headers=h)
    # ⛔ 不许静默丢掉这一行：少一行货会在下单时变成"少订了一样"，两边都不报错
    assert empty.status_code == 400 and "没有选商品" in empty.json()["detail"]


def test_列表按常用度_用过的排前面(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    a = _mk(client, h, "先建的")
    b = _mk(client, h, "后建的")
    before = _ids(client, h)
    assert before.index(a["id"]) < before.index(b["id"]), "都没用过时：先建的在前"
    r = client.post(f"{BASE}/{b['id']}/use", headers=h)
    assert r.status_code == 200, r.text
    after = _ids(client, h)
    assert after.index(b["id"]) < after.index(a["id"]), "用过的那张要排到前面（2026-09-22 统一列表规则）"


def test_删除是软删_能恢复_回收站里改不了(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "要删的预设单")
    assert client.delete(f"{BASE}/{t['id']}", headers=h).status_code == 204
    assert t["id"] not in _ids(client, h), "删掉的不该还出现在列表里"
    # 名字加了可见后缀（全项目软删同一形状），恢复时去掉
    from app.models import OrderTemplate

    row = db_session.get(OrderTemplate, t["id"])
    db_session.refresh(row)
    assert row.is_deleted and row.name.endswith(f"_del{t['id']}")
    # ⚠️ 回收站里的改不了：改了只会让用户以为改的是"现在在用的那一张"
    blocked = client.patch(f"{BASE}/{t['id']}", json={"name": "偷偷改"}, headers=h)
    assert blocked.status_code == 400 and "恢复" in blocked.json()["detail"]
    back = client.post(f"{BASE}/{t['id']}/restore", headers=h)
    assert back.status_code == 200, back.text
    assert back.json()["name"] == "要删的预设单", "恢复要还原原来的名字"
    assert t["id"] in _ids(client, h)


def test_预设单不校验商品是否存在(client, token_dispatcher):
    """**刻意不校验**（见文件头最后一条）：预设单是便签，真校验在下单那一刻。

    这条测试钉的是"行为与文档一致"。要改成存的时候就校验，请连着改这里与文件头。
    """
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "引用了不存在的商品", lines=[{"product_id": 424242, "name": "还没建的商品", "qty": 1}])
    assert t["lines"][0]["product_id"] == 424242


def test_每个写动作都留痕(client, token_dispatcher, db_session):
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "留痕探针")
    client.patch(f"{BASE}/{t['id']}", json={"remark": "改一下"}, headers=h)
    client.delete(f"{BASE}/{t['id']}", headers=h)
    client.post(f"{BASE}/{t['id']}/restore", headers=h)
    upserts = [x for x in _logs(db_session, "ORDER_TEMPLATE_UPSERT") if x.get("template_id") == t["id"]]
    assert [x["scope"] for x in upserts] == ["create", "update"], "建与改各要一条"
    assert _logs(db_session, "ORDER_TEMPLATE_DELETE"), "删要留痕"
    assert _logs(db_session, "ORDER_TEMPLATE_RESTORE"), "恢复要留痕"


def test_只有派单员能管预设单(client, token_shipper, token_driver):
    """用户：「这些功能**主要是给派单员做的**」—— 权限点 `ORDER_EDIT` 只在派单员那一格。"""
    for tok in (token_shipper, token_driver):
        h = auth_headers(tok)
        assert client.get(BASE, headers=h).status_code == 403
        assert client.post(BASE, json={"name": "越权"}, headers=h).status_code == 403


# ============================================================ 分类名册（2026-09-22 用户要求）
#
# 用户原话：「这个模板我们是要**做一个分类**的 —— 也是一样的，**左边是分类管理**，
# 就是**复用**嘛，复用那些**商品管理**的形式；**我右边就是订单**」。
#
# 四条判据，每条都是"不报错但会错"的形状（与商品分类那份一字不差）：
# ① 改名**必须级联**（不级联＝那些预设单全变未分类，而两边都不报错）；
# ② 删除还有预设单挂着 → **拒绝**（不"顺手改成未分类"：那是悄悄改数据）；
# ③ 排序**整份**提交（少传的排哪儿没有答案）；
# ④ 建预设单时带了一个名册外的分类名 → **自动补进名册**（不然要先建分类再建单）。

CATS = "/api/v1/order-template-categories"


def _cat_names(client, h) -> list[str]:
    return [c["name"] for c in client.get(CATS, headers=h).json()]


def test_预设单带分类_名册里没有就自动补进去(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "带分类的预设单", category="每周固定单")
    assert t["category"] == "每周固定单"
    assert "每周固定单" in _cat_names(client, h), "名册里没有的分类名要自动补进名册（排到最后）"
    # 列表那条路回来也要一样
    row = next(r for r in client.get(BASE, headers=h).json() if r["id"] == t["id"])
    assert row["category"] == "每周固定单"


def test_分类改名会级联改掉挂着的预设单_连回收站里那几张也改(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    alive = _mk(client, h, "在用的预设单", category="旧分类名")
    dead = _mk(client, h, "要进回收站的预设单", category="旧分类名")
    assert client.delete(f"{BASE}/{dead['id']}", headers=h).status_code == 204
    cid = next(c["id"] for c in client.get(CATS, headers=h).json() if c["name"] == "旧分类名")

    r = client.patch(f"{CATS}/{cid}", json={"name": "新分类名"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["template_count"] == 1, "计数只数**没进回收站**的（软删那张不该拦住删分类）"

    def cat_of(tid: int) -> str:
        return next(x["category"] for x in client.get(BASE, headers=h).json() if x["id"] == tid)

    assert cat_of(alive["id"]) == "新分类名", "改名必须级联改掉挂着的预设单（不级联＝全变未分类且不报错）"
    # ⚠️ 回收站里那张也要改：不然恢复回来时它挂的是一个名册里已经没有的分类名
    from app.models import OrderTemplate

    assert client.post(f"{BASE}/{dead['id']}/restore", headers=h).status_code == 200
    assert cat_of(dead["id"]) == "新分类名"


def test_删除还有预设单挂着的分类_被拒绝并报数(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "挂着分类的预设单", category="不能删的分类")
    cid = next(c["id"] for c in client.get(CATS, headers=h).json() if c["name"] == "不能删的分类")
    r = client.delete(f"{CATS}/{cid}", headers=h)
    assert r.status_code == 400, r.text
    assert "1 张预设单" in r.json()["detail"], "要说清还有几张挂着（用户照着改）"
    assert "不能删的分类" in _cat_names(client, h), "被拒之后分类要还在"
    # 把那张预设单挪走（移到未分类）之后就能删了
    assert client.patch(f"{BASE}/{t['id']}", json={"category": ""}, headers=h).status_code == 200
    assert client.delete(f"{CATS}/{cid}", headers=h).status_code == 204
    assert "不能删的分类" not in _cat_names(client, h)


def test_分类移动到未分类_空串是一个真实操作(client, token_dispatcher):
    """⚠️ 空串 = 未分类。它必须**发得出去**（用 `is not None` 判的话会被当成"没传"，
    而界面上看不出来 —— 与 `freight_fee`、`shipper_id` 同一条理由）。"""
    h = auth_headers(token_dispatcher)
    t = _mk(client, h, "要挪出分类的预设单", category="临时分类")
    r = client.patch(f"{BASE}/{t['id']}", json={"category": ""}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["category"] == "", "空串要真的写进去（＝未分类）"


def test_分类排序必须整份提交(client, token_dispatcher):
    """只传一部分的话，"没提到的那些排哪儿"没有答案 —— 后端明确拒绝并点名少了哪些。

    ⚠️ 测试库在同一次运行里是**累积的**（别的用例也建过分类），所以这里一律按
    "当前这一份名册"整份提交（把两张换个位置），⛔ 不能手写一个只有两条的 ids。
    """
    h = auth_headers(token_dispatcher)
    _mk(client, h, "排序用预设单", category="排序A")
    _mk(client, h, "排序用预设单2", category="排序B")
    all_cats = client.get(CATS, headers=h).json()
    ids = [c["id"] for c in all_cats]
    mine = [c for c in all_cats if c["name"] in ("排序A", "排序B")]
    assert len(mine) == 2
    partial = client.post(f"{CATS}/reorder", json={"ids": [mine[0]["id"]]}, headers=h)
    assert partial.status_code == 400, "少传的必须被拒（不猜它们排哪儿）"
    assert "少了" in partial.json()["detail"]
    swapped = list(ids)
    i, j = swapped.index(mine[0]["id"]), swapped.index(mine[1]["id"])
    swapped[i], swapped[j] = swapped[j], swapped[i]
    full = client.post(f"{CATS}/reorder", json={"ids": swapped}, headers=h)
    assert full.status_code == 200, full.text
    got = _cat_names(client, h)
    assert got.index("排序B") < got.index("排序A"), "整份提交之后顺序要真的换过来"


def test_分类是只有派单员能管的内部口径(client, token_shipper, token_driver):
    for tok in (token_shipper, token_driver):
        h = auth_headers(tok)
        assert client.get(CATS, headers=h).status_code == 403, "货主/司机那一侧连预订单页都没有"
        assert client.post(CATS, json={"name": "越权分类"}, headers=h).status_code == 403


def test_回收站列表只看得到删掉的那几张(client, token_dispatcher):
    """用户定的硬规矩：删除一律软删 + **界面上要有一个手边的恢复入口**。

    ⚠️ 只有删完那一下的 snackbar「撤回」是不够的：手一滑点掉、或者过一会儿才想起来，
    就再也找不回来了（这一页的「回收站」就是这个入口）。
    """
    h = auth_headers(token_dispatcher)
    alive = _mk(client, h, "还在用的预设单")
    dead = _mk(client, h, "进回收站的预设单")
    assert client.delete(f"{BASE}/{dead['id']}", headers=h).status_code == 204
    bin_ids = [r["id"] for r in client.get(f"{BASE}?deleted_only=true", headers=h).json()]
    assert dead["id"] in bin_ids and alive["id"] not in bin_ids
    # 恢复之后它从回收站消失、回到正常列表
    assert client.post(f"{BASE}/{dead['id']}/restore", headers=h).status_code == 200
    assert dead["id"] not in [r["id"] for r in client.get(f"{BASE}?deleted_only=true", headers=h).json()]
    assert dead["id"] in _ids(client, h)
