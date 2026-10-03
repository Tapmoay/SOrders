"""账号分类名册（`/user-categories`，2026-10-05）：改名级联、有账号挂着拒绝删、排序整份提交、
回收站不算在用、以及「建号/改号时顺手建分类」。

用户 2026-10-05 原话：

> 「还有我们的账户管理司机管理货主管理批发商管理。车辆管理……在这个位置也加个分类，
>  默认是显示，全部，同样也是左边侧边栏，然后左边侧边栏同样也是可以新增分类的，
>  那个左边侧分栏的底下，凡是跟地点是同样的」

账户 / 司机 / 货主 / 批发商**四个**名册页共用这一份名册（与按人分区的联系人/地点/线路三类
**不同**：账号本来就是全局行，谁建的都一样）。这里盯的是三件不说就会踩的事：
1. **归属那一格是字符串**（`users.category`），不是名册 id —— 名册改名要**级联**；
2. **「在用」不含回收站**：删号时号码/用户名被加了 `_del{id}` 后缀（`services/soft_delete.py`），
   如果把它也算成「挂着这个分类」，就会出现「账号都删了，分类却怎么也删不掉」；
3. **只有派单员能改名册**（门是 `Permission.USER_MANAGE`，rbac 里只有 dispatcher 有），
   但**读**只要登录 —— 司机端也要能显示分组名。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import OperationAction, OperationLog, User
from tests.conftest import auth_headers


def _mk_user(client, headers, *, phone: str, name: str, category: str = "", role: str = "driver"):
    """建一个账号（`POST /api/v1/users`）。"""
    return client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "phone": phone,
            "password": "pw123456",
            "full_name": name,
            "role": role,
            "category": category,
        },
    )


def _roster(client, headers) -> list[dict]:
    return client.get("/api/v1/user-categories", headers=headers).json()


def _find(client, headers, name: str) -> dict | None:
    return next((c for c in _roster(client, headers) if c["name"] == name), None)


def test_建号时顺手建分类并进名册(client, token_dispatcher):
    """名册里没有的分类下建号 → 分类自动进名册（排到最后），条数是 1。

    否则派单员得先建分类、再建账号（两步做完才能用）。
    """
    h = auth_headers(token_dispatcher)
    name = "探针-顺手建账号分类"
    assert _find(client, h, name) is None, "探针名撞上上一轮跑剩下的了，换个名字"

    r = _mk_user(client, h, phone="13700009201", name="顺手建分类甲", category=name)
    assert r.status_code in (200, 201), r.text
    assert r.json()["category"] == name

    row = _find(client, h, name)
    assert row is not None, f"分类没进名册：{[c['name'] for c in _roster(client, h)]}"
    assert row["user_count"] == 1
    others = [c["sort_order"] for c in _roster(client, h) if c["id"] != row["id"]]
    assert not others or row["sort_order"] >= max(others)


def test_改号分类也顺手补名册(client, token_dispatcher):
    """把已有账号改成一个新分类名 → 同样进名册（编辑路径与新建路径同一条规矩）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-改出来账号分类"
    made = _mk_user(client, h, phone="13700009202", name="改分类乙")
    assert made.status_code in (200, 201), made.text
    assert made.json()["category"] == ""

    uid = made.json()["id"]
    patched = client.patch(f"/api/v1/users/{uid}", headers=h, json={"category": name})
    assert patched.status_code == 200, patched.text
    assert patched.json()["category"] == name
    assert _find(client, h, name) is not None


def test_改名级联改掉挂着的账号(client, db_session: Session, token_dispatcher):
    """改分类名 → 同一事务里把那些账号的 category 也改掉（不级联 = 「我的账号全变未分类」）。

    ⚠️ 连**回收站里**那个一起改：软删的账号仍然带着老分类名，只改活着的会让「恢复」之后
    那条掉进一个已经不存在（或已被别人占用）的分类里。
    """
    h = auth_headers(token_dispatcher)
    old = "探针-账号改名前"
    new = "探针-账号改名后"
    a = _mk_user(client, h, phone="13700009203", name="账号改名甲", category=old)
    b = _mk_user(client, h, phone="13700009204", name="账号改名乙", category=old)
    assert a.status_code in (200, 201) and b.status_code in (200, 201), (a.text, b.text)
    assert client.delete(f"/api/v1/users/{b.json()['id']}", headers=h).status_code == 204

    row = _find(client, h, old)
    assert row is not None, _roster(client, h)
    r = client.patch(f"/api/v1/user-categories/{row['id']}", headers=h, json={"name": new})
    assert r.status_code == 200, r.text

    db_session.expire_all()
    live = db_session.get(User, a.json()["id"])
    gone = db_session.get(User, b.json()["id"])
    assert live.category == new, "活着的账号没跟着改名"
    assert gone.category == new, "回收站里那个没跟着改名（恢复后会掉进一个不存在的分类）"
    assert db_session.query(User).filter(User.category == old).count() == 0
    assert _find(client, h, old) is None


def test_还有账号挂着的分类不许删(client, token_dispatcher):
    """删除有名下账号的分类 → 400 并告诉他还有几个（不「顺手把它们改成未分类」）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-账号删除保护"
    made = _mk_user(client, h, phone="13700009205", name="删除保护甲", category=name)
    assert made.status_code in (200, 201), made.text
    row = _find(client, h, name)
    assert row is not None and row["user_count"] == 1

    r = client.delete(f"/api/v1/user-categories/{row['id']}", headers=h)
    assert r.status_code == 400, r.text
    assert "1 个账号" in r.json()["detail"], r.json()["detail"]
    assert _find(client, h, name) is not None, "拒绝之后分类必须原样还在"

    # 把账号挪走（清成未分类）之后就能删了
    assert client.patch(
        f"/api/v1/users/{made.json()['id']}", headers=h, json={"category": ""}
    ).status_code == 200
    assert client.delete(f"/api/v1/user-categories/{row['id']}", headers=h).status_code == 204
    assert _find(client, h, name) is None


def test_回收站里的账号不算在用所以能删(client, token_dispatcher):
    """删号之后那个分类应当能删掉（否则会出现「账号都删了，分类却删不掉」）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-回收站不算在用"
    made = _mk_user(client, h, phone="13700009206", name="回收站甲", category=name)
    assert made.status_code in (200, 201), made.text
    assert client.delete(f"/api/v1/users/{made.json()['id']}", headers=h).status_code == 204

    row = _find(client, h, name)
    assert row is not None and row["user_count"] == 0, row
    assert client.delete(f"/api/v1/user-categories/{row['id']}", headers=h).status_code == 204


def test_排序必须整份提交(client, token_dispatcher):
    """只传一部分 → 400 并点名少了几个；整份倒过来 → 真的按这个顺序返回。"""
    h = auth_headers(token_dispatcher)
    _mk_user(client, h, phone="13700009207", name="排序甲", category="探针-账号排序A")
    _mk_user(client, h, phone="13700009208", name="排序乙", category="探针-账号排序B")
    cats = _roster(client, h)
    assert len(cats) >= 2, cats
    ids = [c["id"] for c in cats]

    partial = client.post("/api/v1/user-categories/reorder", headers=h, json={"ids": ids[:1]})
    assert partial.status_code == 400, partial.text
    assert "少了" in partial.json()["detail"], partial.json()["detail"]

    flipped = list(reversed(ids))
    ok = client.post("/api/v1/user-categories/reorder", headers=h, json={"ids": flipped})
    assert ok.status_code == 200, ok.text
    assert [c["id"] for c in ok.json()] == flipped


def test_重名分类被拒绝(client, token_dispatcher):
    """同一份名册里不许两个同名分类（409，且说出名字）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-账号重名"
    first = client.post("/api/v1/user-categories", headers=h, json={"name": name})
    assert first.status_code == 201, first.text
    again = client.post("/api/v1/user-categories", headers=h, json={"name": name})
    assert again.status_code == 409, again.text
    assert name in again.json()["detail"]


def test_空名被拒绝(client, token_dispatcher):
    """纯空格的名字是 422（一句中文校验，不是 500）。"""
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/user-categories", headers=h, json={"name": "   "})
    assert r.status_code == 422, r.text
    assert "不能为空" in r.text


def test_不存在的分类编号是404(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r = client.patch("/api/v1/user-categories/999999", headers=h, json={"name": "不存在"})
    assert r.status_code == 404, r.text
    assert client.delete("/api/v1/user-categories/999999", headers=h).status_code == 404


def test_非派单员改不动名册但读得到(client, token_shipper, token_driver):
    """货主与司机：读 200、写 403（司机端也要能显示分组名）。"""
    sh = auth_headers(token_shipper)
    dr = auth_headers(token_driver)
    assert client.get("/api/v1/user-categories", headers=sh).status_code == 200
    assert client.get("/api/v1/user-categories", headers=dr).status_code == 200
    for h in (sh, dr):
        assert client.post("/api/v1/user-categories", headers=h, json={"name": "越权"}).status_code == 403


def test_非派单员改不了账号分类(client, token_shipper):
    """`category` 与工资/车型同一档：只有派单员改得动（403 且一句话说清）。"""
    sh = auth_headers(token_shipper)
    me = client.get("/api/v1/users/me", headers=sh).json()
    r = client.patch(f"/api/v1/users/{me['id']}", headers=sh, json={"category": "自己挑一组"})
    assert r.status_code == 403, r.text
    assert "账号分类" in r.json()["detail"]


def test_三个写动作都写审计日志(client, db_session: Session, token_dispatcher):
    """建 / 改名 / 删 / 排序都要留痕（名册与商品分类同一套动作码规矩）。"""
    h = auth_headers(token_dispatcher)
    name = "探针-账号审计"
    made = client.post("/api/v1/user-categories", headers=h, json={"name": name})
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    assert client.patch(
        f"/api/v1/user-categories/{cid}", headers=h, json={"name": name + "二"}
    ).status_code == 200
    assert client.delete(f"/api/v1/user-categories/{cid}", headers=h).status_code == 204

    kinds = [
        db_session.query(OperationLog)
        .filter(OperationLog.action == a)
        .filter(OperationLog.change_content.like(f"%{name}%"))
        .count()
        for a in (
            OperationAction.USER_CATEGORY_UPSERT,
            OperationAction.USER_CATEGORY_DELETE,
        )
    ]
    assert all(n >= 1 for n in kinds), kinds
