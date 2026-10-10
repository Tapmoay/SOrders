"""账号分类的**两级**（`parent_id`，2026-10-11 CHG-0112）＋「默认六类」的播种。

用户 2026-10-11 原话：

> 「本来是有分类的，我们这个分类直接拉取关于那个我们对应已经做好的分类，其实我们分类也就这些：
>  派单员、货主、批发商、大车司机、小车司机、挂车司机……假如我的货主和批发商做了分类的话，
>  然后我这个账户管理就会显示 2 级分类，也就会显示他们里面的子分类」

四件不说就会踩的事：
1. **只两级**：父必须自己也是大类。放任第三层的话，界面只画两层 ⇒ 那一层永远看不见
   （账号点不到、也删不掉），所以要在**建的时候就拒**；
2. **`users.category` 仍然是叶子名**：两级没有把账号那一格变成「大类 / 子类」，
   所以改名级联、还有账号挂着不许删，两条都**照旧** —— 这一条是回归；
3. **默认六类必须落在代码里**：名册只靠人手工加的话，清库 / 新装之后左栏又是空的
   （2026-10-10 清零生产时正是这样把 `user_categories` 清掉了，界面上只表现为「左栏只剩全部」）；
4. **只在名册整个为空时播种**：用户删掉**一个**分类，重启不许把它变回来
   （`order_template_categories` 那一段注释里记过的坑）。
"""

from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.schema_bootstrap import (
    USER_CATEGORY_DEFAULTS,
    bootstrap_schema,
    seed_default_user_categories,
)
from app.models import User
from tests.conftest import auth_headers


def _roster(client, headers) -> list[dict]:
    r = client.get("/api/v1/user-categories", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _find(client, headers, name: str) -> dict | None:
    return next((c for c in _roster(client, headers) if c["name"] == name), None)


def _mk(client, headers, name: str, parent_id: int | None = None) -> dict:
    body: dict = {"name": name}
    if parent_id is not None:
        body["parent_id"] = parent_id
    r = client.post("/api/v1/user-categories", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_user(client, headers, *, phone: str, name: str, category: str = "", role: str = "driver"):
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


# ----------------------------------------------------------------- 两级：写入路径
def test_建子分类时出参带上层编号(client, token_dispatcher):
    """子类是一行、大类也是一行，区别只在 `parent_id`（界面靠它画缩进）。"""
    h = auth_headers(token_dispatcher)
    p = _mk(client, h, "探针-两级大类")
    assert p["parent_id"] is None, "大类没有上层"
    c = _mk(client, h, "探针-两级子类", p["id"])
    assert c["parent_id"] == p["id"]
    assert _find(client, h, "探针-两级子类")["parent_id"] == p["id"], "GET 也要带归属"


def test_上层分类不存在时被拒(client, token_dispatcher):
    """父编号是空的（并发删掉了）→ 400 并说清，⛔ 不许悄悄建成一个大类。"""
    h = auth_headers(token_dispatcher)
    r = client.post("/api/v1/user-categories", headers=h, json={"name": "探针-孤儿", "parent_id": 999999})
    assert r.status_code == 400, r.text
    assert "上层分类不存在" in r.json()["detail"], r.json()["detail"]
    assert _find(client, h, "探针-孤儿") is None, "拒绝之后不许留下半成品"


def test_子类的子类被拒(client, token_dispatcher):
    """**只两级**：第三层界面画不出来 ⇒ 建的时候就拒（不然它是个看不见的孤儿）。"""
    h = auth_headers(token_dispatcher)
    a = _mk(client, h, "探针-三级甲")
    b = _mk(client, h, "探针-三级乙", a["id"])
    r = client.post(
        "/api/v1/user-categories", headers=h, json={"name": "探针-三级丙", "parent_id": b["id"]}
    )
    assert r.status_code == 400, r.text
    assert "只能做两级" in r.json()["detail"], r.json()["detail"]
    assert _find(client, h, "探针-三级丙") is None


def test_大类下面还有子类时不许删(client, token_dispatcher):
    """删掉大类会让子类变成没有父的孤儿 —— 先拒，且说清有几个、叫什么。"""
    h = auth_headers(token_dispatcher)
    p = _mk(client, h, "探针-有子类的大类")
    c = _mk(client, h, "探针-有子类的大类-甲", p["id"])
    r = client.delete(f"/api/v1/user-categories/{p['id']}", headers=h)
    assert r.status_code == 400, r.text
    assert "子分类" in r.json()["detail"] and "探针-有子类的大类-甲" in r.json()["detail"], r.json()["detail"]
    assert _find(client, h, "探针-有子类的大类") is not None, "拒绝之后大类必须原样还在"
    assert client.delete(f"/api/v1/user-categories/{c['id']}", headers=h).status_code == 204
    assert client.delete(f"/api/v1/user-categories/{p['id']}", headers=h).status_code == 204


# ----------------------------------------------------------------- 回归：账号那一格没变
def test_账号那一格仍然是叶子名_改名级联照旧(client, token_dispatcher):
    """两级**没有**把账号的分类变成「大类 / 子类」：它还是一个字符串，两条老规矩都不动。"""
    h = auth_headers(token_dispatcher)
    p = _mk(client, h, "探针-叶子大类")
    _mk(client, h, "探针-叶子子类", p["id"])
    made = _mk_user(client, h, phone="13700009301", name="叶子甲", category="探针-叶子子类")
    assert made.status_code in (200, 201), made.text
    assert made.json()["category"] == "探针-叶子子类", "账号那一格必须还是叶子名"

    assert _find(client, h, "探针-叶子子类")["user_count"] == 1
    assert _find(client, h, "探针-叶子大类")["user_count"] == 0, "大类的条数只数直接挂在它上面的"

    # 改名级联照旧（改完账号跟着走 —— 条数还在这一格上就证明它跟过去了）
    kid = _find(client, h, "探针-叶子子类")
    renamed = client.patch(
        f"/api/v1/user-categories/{kid['id']}", headers=h, json={"name": "探针-叶子子类改"}
    )
    assert renamed.status_code == 200, renamed.text
    assert _find(client, h, "探针-叶子子类改")["user_count"] == 1, "改名没级联到账号"

    # 还有账号挂着不许删（照旧），挪走之后能删
    assert client.delete(f"/api/v1/user-categories/{kid['id']}", headers=h).status_code == 400
    assert client.patch(
        f"/api/v1/users/{made.json()['id']}", headers=h, json={"category": ""}
    ).status_code == 200
    assert client.delete(f"/api/v1/user-categories/{kid['id']}", headers=h).status_code == 204


def test_名册出参仍是一列平铺且带归属(client, token_dispatcher):
    """四个名册页共用这一份：形状没变成树（仍是 sort_order, id 平铺），只是多了一格归属。"""
    h = auth_headers(token_dispatcher)
    rows = _roster(client, h)
    assert rows, rows
    assert all("parent_id" in r for r in rows)
    keys = [(r["sort_order"], r["id"]) for r in rows]
    assert keys == sorted(keys), keys


# ----------------------------------------------------------------- 默认六类：播种
def _fresh_engine(tmp_path) -> Engine:
    """一个干净的库 —— 走真实的启动路径（`bootstrap_schema` 就是服务启动时那一步）。"""
    eng = create_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    bootstrap_schema(eng)
    return eng


def _names(eng: Engine) -> list[str]:
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM user_categories ORDER BY sort_order, id")
        ).fetchall()
    return [r[0] for r in rows]


def test_默认六类按点名的顺序播种(tmp_path):
    """新装的库、被清空的库：左栏一开始就有那六类（顺序 = 用户点名的顺序）。"""
    eng = _fresh_engine(tmp_path)
    assert _names(eng) == list(USER_CATEGORY_DEFAULTS)


def test_播种幂等且不复活被删掉的单个分类(tmp_path):
    """每启动一次不会再插一遍；用户删掉**一个**分类，重启不许把它变回来。"""
    eng = _fresh_engine(tmp_path)
    assert seed_default_user_categories(eng) == 0, "名册已经有六类，不该再插一遍"
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM user_categories WHERE name = '批发商'"))
    assert seed_default_user_categories(eng) == 0, "名册不是空的 → 一个都不许复活"
    assert "批发商" not in _names(eng)
    assert len(_names(eng)) == len(USER_CATEGORY_DEFAULTS) - 1


def test_名册被清空后下次启动自己长回来(tmp_path):
    """2026-10-10 清零生产时把名册一起清掉了 —— 这一条就是那一次的恢复路径。"""
    eng = _fresh_engine(tmp_path)
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM user_categories"))
    assert _names(eng) == []
    assert seed_default_user_categories(eng) == len(USER_CATEGORY_DEFAULTS)
    assert _names(eng) == list(USER_CATEGORY_DEFAULTS)


def test_已在用的分类名排在六个默认名之后_回收站里的不算(tmp_path):
    """账号上写着、名册里没有的名字要收进来（否则那些账号在左栏里点不到）；
    但**回收站里**的账号不算（与 `/user-categories` 的「在用条数」同一条口径）。"""
    eng = _fresh_engine(tmp_path)
    with Session(eng) as s:
        live = User(
            phone="13700009302",
            username="13700009302",
            password_hash="x",
            full_name="在用甲",
            role="driver",
            category="自有车",
        )
        gone = User(
            phone="13700009303",
            username="13700009303",
            password_hash="x",
            full_name="回收站乙",
            role="driver",
            category="只在回收站里",
        )
        s.add(live)
        s.add(gone)
        s.commit()
        s.refresh(gone)
        # 软删 = 号码/用户名带本行的 `_del{id}` 后缀（`services/soft_delete.py`）
        gone.phone = f"13700009303_del{gone.id}"
        s.commit()
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM user_categories"))

    assert seed_default_user_categories(eng) == len(USER_CATEGORY_DEFAULTS) + 1
    names = _names(eng)
    assert names[: len(USER_CATEGORY_DEFAULTS)] == list(USER_CATEGORY_DEFAULTS), names
    assert names[len(USER_CATEGORY_DEFAULTS):] == ["自有车"], names
    assert "只在回收站里" not in names, "回收站里的账号不算在用"
