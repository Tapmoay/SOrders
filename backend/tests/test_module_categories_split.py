"""模块自有分类名册 ∥ 账号名册：**拆开**（FEAT-0026，2026-10-12）。

用户 2026-10-12 原话（验收口径）：

> 「我批发商管理他那个分类啊，他那个分类是**跟账号管理不一样**的，**他现在串在一起了**。
>  他那个分类是**可以新建的、另外建的**。只不过我们**账号管理拉取他们的分类的时候是搞 2 级分类**；
>  当然，我们这些**子分类是不会拉取主分类**的。也就如**司机管理**，还有其他的**批发商管理**，
>  **他们是有自己的分类的**，他们的分类基本上就是 **1 级**、不会有 2 级的。
>  然后我们的**账号管理**，他的那个分类他是**有 2 级的**，他是**主动拉取**的，
>  而且我们分类**已经固定好了**的。」

拆之前：批发商管理 / 司机管理 / 货主管理三个名册页与账户页**共用** `user_categories`，
"在批发商管理里加一格"与"给账号名册加一个大类"是**同一个写端点**。拆之后：

- **模块名册** = `module_categories`（平表、**只有一级**），增 / 删 / 改 / 排序走 `/module-categories`；
- **账号名册** = `user_categories`（一级固定六类、**只读**），二级由 `GET /user-categories`
  从模块名册**拉取**（读时投影，编号是负数、`pulled=True`）。

下面每条用例对着一条"不说就会踩"的事：

1. 在批发商管理里新建一格**不写账号册**（`GET` 两次，`user_categories` 一行都不多）；
2. 账号册**不能新建一级**（一级是按身份自动推导的，CHG-0121）；
3. 拉取来的二级**挂在对的一级下面**；司机那一份名册喂三个一级（同一格出现三次、编号互不相同）；
4. 子分类**不会**被拉成一级（模块名册里没有一个名字占着 `parent_id is None` 那一格）；
5. 账号册不能改 / 删 / 排序拉取来的行（写路径在模块那一页），但「派单员」下面的
   **历史遗留二级**照旧能改（⛔ 不许一刀切把 CHG-0112 的行为也堵掉）；
6. 模块册的删除是**软删**（行留着、`deleted_at` 有值）、账号册的拉取里立刻看不见、
   `restore` 原样放回来；还有账号挂着时**拒绝删**（⛔ 不悄悄把账号改成未分类）；
7. 模块册改名**只级联"身份属于自己那几个一级"的账号** —— 两个模块里有同名分类时不许串册；
8. 建号时"顺手补一个分类"那条老规矩**加了守卫**：名字在模块名册里就不补
   （否则同一格分类既是拉取来的二级、又自己占一个一级 —— 又串在一起了）；
9. 035 迁移把老数据（挂在模块一级下面的二级行）**搬**进模块名册：账号那一格一个字节不变、
   同名的活行不重复插、再跑一遍（幂等）什么都不变；
10. 模块名册**只有一级**：出参里根本没有归属字段（⛔ 不是"有但为空"）。
"""

from __future__ import annotations

import importlib.util

import pytest
from sqlalchemy import create_engine, func, inspect, text
from sqlalchemy.orm import Session

from app.api.v1.user_categories import ensure_user_category
from app.core.schema_bootstrap import USER_CATEGORY_DEFAULTS
from app.migrations import MIGRATIONS_DIR
from app.models import ModuleCategory, User, UserCategory
from app.models.base import Base
from app.models.enums import UserRole
from tests.conftest import auth_headers

ACCOUNT = "/api/v1/user-categories"
MODULE = "/api/v1/module-categories"


# --------------------------------------------------------------------- 抓手
def _account(client, headers) -> list[dict]:
    r = client.get(ACCOUNT, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _module(client, headers, module: str) -> list[dict]:
    r = client.get(MODULE, headers=headers, params={"module": module})
    assert r.status_code == 200, r.text
    return r.json()


def _top(client, headers, name: str) -> dict:
    row = next(
        (c for c in _account(client, headers) if c["name"] == name and c["parent_id"] is None), None
    )
    assert row is not None, f"账号册里没有一级分类「{name}」"
    assert row["fixed"] is True, row
    return row


def _pulled(client, headers, name: str, module: str | None = None) -> list[dict]:
    """账号册里**拉取**来的那几行（不是库里的行）。"""
    rows = [c for c in _account(client, headers) if c["name"] == name and c["pulled"]]
    return [c for c in rows if module is None or c["module"] == module]


def _mk_module(client, headers, module: str, name: str, sort_order: int | None = None) -> dict:
    body: dict = {"module": module, "name": name}
    if sort_order is not None:
        body["sort_order"] = sort_order
    r = client.post(MODULE, headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _mk_user(
    client,
    headers,
    *,
    phone: str,
    name: str,
    category: str = "",
    role: str = "driver",
    is_member: bool = False,
    vehicle_type: str | None = None,
) -> dict:
    body: dict = {
        "phone": phone,
        "password": "pw123456",
        "full_name": name,
        "role": role,
        # ⚠️ 服务端**不看**这一格（CHG-0121：分类是身份的投影）——照发是为了把
        #    "传了也不写账号册"这件事留在请求里；要铺存量数据用 `_set_cat`。
        "category": category,
    }
    if is_member:
        body["is_member"] = True
    if vehicle_type:
        body["vehicle_type"] = vehicle_type
    r = client.post("/api/v1/users", headers=headers, json=body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _cat_of(db, user_id: int) -> str:
    db.expire_all()
    return db.query(User).filter_by(id=user_id).one().category


def _set_cat(db, user_id: int, name: str) -> None:
    """把账号那一格**直接**写成叶子分类名 —— 这是**存量数据**的样子。

    ⚠️ CHG-0121 之后 `users.category` 一律按身份自动推导（建号 / 改号都忽略传进来的分类名，
    见 `api/v1/users.py` 那句"分类是身份的投影"）⇒ 界面上再也造不出"账号挂在某个叶子分类下"
    这种状态，而它**真实存在于老库**。本文件里"占用拒删 / 改名级联 / 拉取计数"三条判据
    本来判的就是这批老数据，所以夹具照老库那个形状直接写这一格。
    """
    db.expire_all()
    u = db.query(User).filter_by(id=user_id).one()
    u.category = name
    db.commit()


# ------------------------------------------------------------------ 夹具
@pytest.fixture(autouse=True)
def _six_level_ones(db_session):
    """账号册的一级**固定六类**（`USER_CATEGORY_DEFAULTS`）：测试库里先把缺的补齐。

    ⚠️ 测试库是**共用**的（`tests/conftest.py` 直接 ORM 建账号、从不调
    `seed_default_user_categories`）⇒ 一级那几格不一定在，而
    `pull_module_categories` 的口径是「一级行找不到就少拉一格、绝不凭空造一级」
    ⇒ 不补的话拉取"一格都不出"，用例会红在一个与拆分无关的原因上。

    只补**缺的那几格**：⛔ 不删、不改已有的行与顺序（同文件其他用例也在这张表上跑）。
    """
    have = {
        r.name
        for r in db_session.query(UserCategory).filter(UserCategory.parent_id.is_(None)).all()
    }
    missing = [n for n in USER_CATEGORY_DEFAULTS if n not in have]
    if missing:
        base = db_session.query(func.max(UserCategory.sort_order)).scalar() or 0
        for i, name in enumerate(missing, start=1):
            db_session.add(UserCategory(name=name, sort_order=int(base) + i))
        db_session.commit()
    yield


# ------------------------------------------------- ① 两份名册互不影响（写不串）
def test_模块名册新建一格不写账号册(client, token_dispatcher, db_session):
    """「批发商管理里新建一格」只落 `module_categories`：账号册那边是**读时拉取**。

    ⛔ 反过来的"写"（往 `user_categories` 塞一行）会让同一格分类有两个身份：
       一个真实的二级行 + 一个拉取来的二级行，界面上出现两次（用户说的"串在一起"）。
    """
    h = auth_headers(token_dispatcher)
    before = len(_account(client, h))

    row = _mk_module(client, h, "members", "探针-拆分-食堂客户")
    assert row["module"] == "members" and row["name"] == "探针-拆分-食堂客户"
    assert [x["name"] for x in _module(client, h, "members")] == ["探针-拆分-食堂客户"]

    # 账号册里看得见它 —— 但是**拉取行**（负数编号、带 parent_id、pulled=True）
    hit = _pulled(client, h, "探针-拆分-食堂客户", "members")
    assert len(hit) == 1, hit
    assert hit[0]["id"] < 0 and hit[0]["parent_id"] == _top(client, h, "批发商")["id"]

    # 库里一个字节都没多写（GET 两次也一样）
    assert db_session.query(UserCategory).filter_by(name="探针-拆分-食堂客户").first() is None
    assert len(_account(client, h)) == before + 1, "账号册只多了拉取来的那一行"


def test_账号册不能新建一级(client, token_dispatcher):
    """一级 = 固定六类：账号挂的分类名是按身份推导的（CHG-0121），凭空多一个没人会被挂上去。"""
    h = auth_headers(token_dispatcher)
    r = client.post(ACCOUNT, headers=h, json={"name": "探针-拆分-新一级"})
    assert r.status_code == 400, r.text
    assert "固定的六类" in r.json()["detail"], r.json()["detail"]
    assert [c for c in _account(client, h) if c["name"] == "探针-拆分-新一级"] == []


def test_账号册不能给模块的一级挂子分类(client, token_dispatcher):
    """「批发商」下面的子分类跟着**批发商管理**自己的名册走 ⇒ 在这边建被拒，并指路那一页。"""
    h = auth_headers(token_dispatcher)
    top = _top(client, h, "批发商")
    r = client.post(ACCOUNT, headers=h, json={"name": "探针-拆分-手建子", "parent_id": top["id"]})
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "批发商管理" in detail and "管理分类" in detail, detail
    assert _pulled(client, h, "探针-拆分-手建子") == []


def test_账号册不能改删排序拉取来的行(client, token_dispatcher):
    """那些写路径都在模块那一页（软删 + 撤销也在那边）。"""
    h = auth_headers(token_dispatcher)
    _mk_module(client, h, "shippers", "探针-拆分-只读")
    got = _pulled(client, h, "探针-拆分-只读", "shippers")
    assert len(got) == 1, got
    cid = got[0]["id"]

    p = client.patch(f"{ACCOUNT}/{cid}", headers=h, json={"name": "探针-拆分-偷改"})
    assert p.status_code == 400, p.text
    assert "拉取" in p.json()["detail"], p.json()["detail"]

    d = client.delete(f"{ACCOUNT}/{cid}", headers=h)
    assert d.status_code == 400, d.text
    assert "拉取" in d.json()["detail"], d.json()["detail"]

    o = client.post(f"{ACCOUNT}/reorder", headers=h, json={"ids": [cid]})
    assert o.status_code == 400, o.text

    # 模块那一页原样还在，名字没被偷改
    assert [x["name"] for x in _module(client, h, "shippers") if x["name"] == "探针-拆分-只读"]
    assert _pulled(client, h, "探针-拆分-偷改") == []


def test_派单员下面的历史遗留二级照旧能改(client, token_dispatcher):
    """⛔ 不是"账号册整页只读"：派单员**没有**模块名册，它下面那几格沿用 CHG-0112 的老行为。"""
    h = auth_headers(token_dispatcher)
    top = _top(client, h, "派单员")
    made = client.post(ACCOUNT, headers=h, json={"name": "探针-拆分-派单子", "parent_id": top["id"]})
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    assert made.json()["parent_id"] == top["id"] and made.json()["fixed"] is False

    renamed = client.patch(f"{ACCOUNT}/{cid}", headers=h, json={"name": "探针-拆分-派单子改"})
    assert renamed.status_code == 200, renamed.text
    # reorder 交的是**完整**顺序（ordered_ids 的口径）⇒ 把「派单员」下面现存的历史子分类全带上
    # （同一个测试库是共用的，别的用例会往这里攒探针行），cid 排最前。
    kids = [r for r in _account(client, h) if r["parent_id"] == top["id"]]
    ids = [cid] + [r["id"] for r in kids if r["id"] != cid]
    reordered = client.post(f"{ACCOUNT}/reorder", headers=h, json={"ids": ids})
    assert reordered.status_code == 200, reordered.text
    assert [r["id"] for r in reordered.json()][0] == cid, "cid 应该排最前"
    assert client.delete(f"{ACCOUNT}/{cid}", headers=h).status_code == 204


# ------------------------------- ② 拉取：挂对一级 / 子分类不变一级 / 司机一对三
def test_拉取来的二级挂在对的一级下面(client, token_dispatcher):
    """账号册「批发商」那一格下面出现批发商管理建的分类（用户说的就是这一句）。"""
    h = auth_headers(token_dispatcher)
    _mk_module(client, h, "members", "探针-拆分-挂对")
    hit = _pulled(client, h, "探针-拆分-挂对", "members")
    assert len(hit) == 1, hit
    assert hit[0]["parent_id"] == _top(client, h, "批发商")["id"]
    assert hit[0]["user_count"] == 0


def test_子分类不会被拉成一级(client, token_dispatcher):
    """一级那几格**恰好**还是固定六类：模块名册里没有一个名字占着 `parent_id is None`。"""
    h = auth_headers(token_dispatcher)
    _mk_module(client, h, "members", "探针-拆分-甲")
    _mk_module(client, h, "shippers", "探针-拆分-乙")
    _mk_module(client, h, "drivers", "探针-拆分-丙")

    rows = _account(client, h)
    tops = {c["name"] for c in rows if c["parent_id"] is None}
    assert set(USER_CATEGORY_DEFAULTS) <= tops, tops
    for name in ("探针-拆分-甲", "探针-拆分-乙", "探针-拆分-丙"):
        assert name not in tops, f"「{name}」被拉成了一级：{sorted(tops)}"
        assert all(c["parent_id"] is not None for c in _pulled(client, h, name))
    assert all(c["fixed"] for c in rows if c["parent_id"] is None)
    assert all(c["pulled"] for c in rows if c["id"] < 0)


def test_司机一份名册喂三个一级(client, token_dispatcher, db_session):
    """司机管理只有一份名册，账号册里对应**三个**一级（小车 / 大车 / 挂车）—— 各挂各的。

    三个账号的**身份**分别是小 / 大 / 挂车（拉取按身份挑一级），而账号那一格写的都是
    同一个叶子名（存量数据）—— 所以三行的 `user_count` 各是 1。
    """
    h = auth_headers(token_dispatcher)
    _mk_module(client, h, "drivers", "探针-拆分-三型")
    for vt, phone in (("small", "13700009701"), ("large", "13700009702"), ("trailer", "13700009703")):
        u = _mk_user(client, h, phone=phone, name=f"拆分司机-{vt}", vehicle_type=vt)
        _set_cat(db_session, u["id"], "探针-拆分-三型")

    hit = _pulled(client, h, "探针-拆分-三型", "drivers")
    assert len(hit) == 3, hit
    assert sorted(c["parent_id"] for c in hit) == sorted(
        _top(client, h, n)["id"] for n in ("小车司机", "大车司机", "挂车司机")
    )
    assert len({c["id"] for c in hit}) == 3, "三个一级下面必须是三个不同编号（否则界面 key 会撞）"
    assert all(c["user_count"] == 1 for c in hit), hit


def test_模块名册只有一级_出参没有归属字段(client, token_dispatcher):
    """⛔ 不是"有 parent_id 但为空"：模块名册是平表，多态字段本身就不该存在。"""
    h = auth_headers(token_dispatcher)
    row = _mk_module(client, h, "members", "探针-拆分-平表")
    assert "parent_id" not in row, row
    assert "fixed" not in row and "pulled" not in row, row
    assert all("parent_id" not in x for x in _module(client, h, "members"))


# ------------------------------------------------------------ ③ 软删 / 恢复 / 占用
def test_模块册删除是软删_拉取里立刻看不见_恢复原样回来(client, token_dispatcher, db_session):
    """用户 2026-09-20 的硬规矩：所有删除一律软删 + 必须有恢复路径。"""
    h = auth_headers(token_dispatcher)
    row = _mk_module(client, h, "members", "探针-拆分-软删")
    assert client.delete(f"{MODULE}/{row['id']}", headers=h).status_code == 204

    assert [x for x in _module(client, h, "members") if x["name"] == "探针-拆分-软删"] == []
    assert _pulled(client, h, "探针-拆分-软删", "members") == []

    gone = db_session.query(ModuleCategory).filter_by(id=row["id"]).one()
    assert gone.is_deleted is True and gone.deleted_at is not None, "⛔ 必须是软删（行还在）"

    back = client.post(MODULE + "/restore", headers=h, json={"module": "members", "name": "探针-拆分-软删"})
    assert back.status_code == 200, back.text
    assert back.json()["id"] == row["id"], "撤销要把原来那一行放回来，不是新建一行"
    assert len(_pulled(client, h, "探针-拆分-软删", "members")) == 1


def test_模块册还有账号挂着时拒绝删(client, token_dispatcher, db_session):
    """⛔ 不"顺手把那些账号改成未分类"（那是悄悄改数据，界面上看不出来）。"""
    h = auth_headers(token_dispatcher)
    row = _mk_module(client, h, "members", "探针-拆分-占用")
    u = _mk_user(client, h, phone="13700009711", name="拆分占用", role="shipper", is_member=True)
    _set_cat(db_session, u["id"], "探针-拆分-占用")  # 老库：这个批发商账号挂在这一格下面

    r = client.delete(f"{MODULE}/{row['id']}", headers=h)
    assert r.status_code == 400, r.text
    assert "1 个账号" in r.json()["detail"], r.json()["detail"]
    assert len(_pulled(client, h, "探针-拆分-占用", "members")) == 1, "拒绝之后那一格必须原样还在"


# ------------------------------------------------------------ ④ 改名级联（不串册）
def test_模块册改名只级联自己那份名册下面的账号(client, token_dispatcher, db_session):
    """两个模块里可以有**同名**分类；改名只改"身份属于自己那几个一级"的账号（⛔ 不串册）。"""
    h = auth_headers(token_dispatcher)
    a = _mk_module(client, h, "members", "探针-拆分-同名")
    _mk_module(client, h, "shippers", "探针-拆分-同名")

    member = _mk_user(client, h, phone="13700009721", name="拆分同名批", role="shipper", is_member=True)
    shipper = _mk_user(client, h, phone="13700009722", name="拆分同名货", role="shipper")
    for u in (member, shipper):  # 两边都挂着同名分类：批发商那个挂 members，货主那个挂 shippers
        _set_cat(db_session, u["id"], "探针-拆分-同名")

    r = client.patch(f"{MODULE}/{a['id']}", headers=h, json={"name": "探针-拆分-改名后"})
    assert r.status_code == 200, r.text
    assert _cat_of(db_session, member["id"]) == "探针-拆分-改名后", "批发商那份名册改名要级联"
    assert _cat_of(db_session, shipper["id"]) == "探针-拆分-同名", "⛔ 货主那一份不许被带着改"


# ------------------------------------------------- ⑤ 建号补分类：不把模块分类补成一级
def test_建号补分类时不把模块分类补成一级(client, token_dispatcher, db_session):
    """老规矩（建号时名册里没有就补一格）照旧，但**模块名册里的名字不补** ——
    它已经会以拉取的方式出现；补一行等于给同一格分类再安一个"一级"的身份。"""
    h = auth_headers(token_dispatcher)
    _mk_module(client, h, "drivers", "探针-拆分-自有车")
    _mk_user(client, h, phone="13700009731", name="拆分自有车", vehicle_type="small")

    assert ensure_user_category(db_session, "探针-拆分-自有车") is None, "模块名册里的名字不许补进账号册"
    db_session.commit()
    assert db_session.query(UserCategory).filter_by(name="探针-拆分-自有车").first() is None
    assert len(_pulled(client, h, "探针-拆分-自有车", "drivers")) == 3
    assert "探针-拆分-自有车" not in {c["name"] for c in _account(client, h) if c["parent_id"] is None}


def test_建号补分类的老规矩照旧(client, token_dispatcher, db_session):
    """回归：名字**不在**任何模块名册里时，照旧补进账号名册（CHG-0112 钉住的行为）。"""
    h = auth_headers(token_dispatcher)
    u = _mk_user(client, h, phone="13700009741", name="拆分新分类", vehicle_type="small")
    assert _cat_of(db_session, u["id"]) == "小车司机", "建号那一刻的分类是**身份推出来的**（CHG-0121）"

    assert ensure_user_category(db_session, "探针-拆分-自建") is not None, "不在任何模块名册里 ⇒ 照旧补"
    db_session.commit()
    row = db_session.query(UserCategory).filter_by(name="探针-拆分-自建").one()
    assert row.parent_id is None, "建号顺手补的分类仍然是大类"


# ------------------------------------------------------------------ ⑥ 迁移 035
def _load_035() -> object:
    path = MIGRATIONS_DIR / "035_module_categories.py"
    spec = importlib.util.spec_from_file_location("mig035_for_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _names_in(engine, table: str, module: str | None = None) -> list[str]:
    sql = f"SELECT name FROM {table}"
    args: dict = {}
    if module is not None:
        sql += " WHERE module = :m AND is_deleted = 0"
        args = {"m": module}
    sql += " ORDER BY sort_order, id"
    with engine.connect() as conn:
        return [r[0] for r in conn.execute(text(sql), args).fetchall()]


def test_迁移035把老二级搬进模块名册_账号一格不变_且幂等(tmp_path):
    """老数据（CHG-0112 之后在「批发商」下面建的"食堂客户"）怎么过去：

    · **搬**：名字 / 顺序 / 归属一个字节不变，只是换到了模块那一份名册；
    · 旧行**撤掉**（留着的话账号册里同一格会出现两次）；
    · `派单员` 下面的子分类**不动**（没有派单员管理这一页）；
    · 账号上写的分类名（`users.category`）**一个字节都不改**；
    · 再跑一遍什么都不变（迁移 README 的硬要求）。
    """
    mod = _load_035()
    engine = create_engine(f"sqlite:///{(tmp_path / 'mig035.db').as_posix()}")
    Base.metadata.create_all(bind=engine)

    # 老数据用 ORM 写（`user_categories` **没有软删列** —— CHG-0112 那份名册是硬删；
    # 裸 SQL 还得自己凑 `users` 的 NOT NULL 列，不如让模型给默认值）
    with Session(engine) as s:
        tops: dict[str, UserCategory] = {}
        for i, top in enumerate(("派单员", "货主", "批发商", "小车司机")):
            row = UserCategory(name=top, sort_order=i)
            s.add(row)
            s.flush()
            tops[top] = row
        for top in ("派单员", "货主", "批发商", "小车司机"):
            s.add(UserCategory(name=f"老二级-{top}", sort_order=9, parent_id=tops[top].id))
        s.add(
            User(
                phone="13700009751",
                username="13700009751",
                password_hash="x",
                full_name="老账号",
                role=UserRole.SHIPPER,
                category="老二级-批发商",
            )
        )
        s.commit()

    # 已经在模块名册里的同名活行：迁移**不许**再插一行（只撤旧行）
    ModuleCategory.__table__.create(bind=engine, checkfirst=True)
    with Session(engine) as s:
        s.add(ModuleCategory(module="members", name="老二级-批发商", sort_order=3))
        s.commit()

    mod.upgrade(engine)
    mod.upgrade(engine)  # 幂等：第二遍什么都不做

    assert _names_in(engine, "module_categories", "members") == ["老二级-批发商"]
    assert _names_in(engine, "module_categories", "shippers") == ["老二级-货主"]
    assert _names_in(engine, "module_categories", "drivers") == ["老二级-小车司机"]
    assert "老二级-派单员" not in {r for m in ("members", "shippers", "drivers") for r in _names_in(engine, "module_categories", m)}

    left = _names_in(engine, "user_categories")
    assert left == ["派单员", "货主", "批发商", "小车司机", "老二级-派单员"], left
    with engine.connect() as conn:
        cat = conn.execute(text("SELECT category FROM users WHERE phone = '13700009751'")).scalar()
    assert cat == "老二级-批发商", "账号那一格必须一个字节都不改"
    assert "module" in {c["name"] for c in inspect(engine).get_columns("module_categories")}
