"""电话格式护栏（2026-09-19）：电话列不许再收汉字、字母、符号。

## 这条护栏在防什么（生产库实证，不是"理论上可能"）
用户反馈的原话是「电话号码只能填数字，而且必须填正确的格式，不能填字母和文字」。查生产库：

- `orders.contact_dongjia_phone` 里真的有 `[嘿嘿] [嘻嘻] [问问] [刚刚好]` 这样的**中文**值；
- `shipper_contacts` 里有一条 `[222]`。

后果不是"数据难看"，而是**司机拿着单打不出电话**：派单端把这一列当货主电话显示与拨号，
值不是号码时电话打不出去，而单子已经派出去了。规则实现只有**一处**：`app/core/phone.py`，
本文件不再写第二份规则（只验"接线到底通没通"）。

## 为什么每个用例都写"两个方向"
- **非法值一律断言 422 + 那句中文**：有人把某个 schema 上的校验删掉（或新加一个电话字段
  忘了标注类型别名）时，这里会变成 200/201 而**立刻红** —— 这正是这条测试存在的意义。
  断言"中文原样出现"还有第二个作用：`humanizeValidation` 对含中文的 `msg` 是原样显示的，
  所以出现别的文案（例如 Pydantic 的英文）等于用户看不到能照着改的话。
- **合法值一律断言 201 且原样存回去**：有人把规则收紧（例如给联系电话也加上"必须以 1 开头"）
  时，`01012345678` 这条**座机**会红。座机被挡掉是本轮明确不许发生的事
  （挂账单位、收货人里座机很常见）。

## 本文件**不测**的东西（免得起误会）
- 出参（`OrderOut` / `AddressOut` / `ArrearsUnitOut` / `ContactOut` / `CustomerOut` / `UserOut`）
  一律**不加**校验：生产库里已经躺着 `[嘿嘿]` / `[222]` 这些历史值，
  给出参加校验会让"打开列表"直接 500（旧数据读不出来比脏数据更糟）。历史脏值只能在写入侧拦住。
- `LoginRequest`：它的 `phone` 字段实际是"手机号**或用户名**"（见 `schemas/auth.py` 的
  `model_validator`），绝不能加数字限制 —— 见本文件 ⑤ 那组用例。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from pydantic import AfterValidator
from starlette.testclient import TestClient

from app.core.phone import (
    CONTACT_MAX_DIGITS,
    CONTACT_MIN_DIGITS,
    CONTACT_PHONE_MESSAGE,
    MOBILE_PHONE_MESSAGE,
    validate_contact_phone,
    validate_mobile_phone,
)
from app.schemas.auth import LoginRequest
from tests.conftest import auth_headers

# --------------------------------------------------------------------------
# 用例数据：每条都写明它在防什么
# --------------------------------------------------------------------------

def _uniq(prefix: str) -> str:
    """每次现算一个不重名的名字（唯一约束 + 端点内部 commit，见 CONTACT_ENDPOINTS 的说明）。"""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _uniq_mobile() -> str:
    """现算一个**合法且不重号**的手机号（号段 137 + 8 位随机数）。

    ⚠️ 建号/改号的用例绝不能写死手机号：`users.phone` 有唯一约束，而端点内部会
    `commit()`（conftest 的 rollback 回滚不掉已提交的数据），写死的号第二次就 409/400。
    """
    return "137" + str(uuid.uuid4().int)[:8]


def _order_body() -> dict:
    """派单员代理下单：必须给 `temp_shipper_name`（没给会 400，而且那和电话校验无关）。"""
    return {
        "lines": [
            {"product_name_snapshot": "电话护栏", "quantity": 1, "unit_price": "1", "line_total": "1"}
        ],
        "address_detail": "电话护栏地址",
        "temp_shipper_name": _uniq("电话护栏临时货主"),
    }


def _address_body() -> dict:
    return {"receiver_name": _uniq("电话护栏")}


def _contact_body() -> dict:
    # 联系人的电话是**必填**（`ContactCreate.phone` 没有默认值），所以建之前先给一个合法号；
    # 需要换成被测值的用例会覆盖这个键。
    return {"display_name": _uniq("电话护栏"), "phone": "13800000000"}


def _arrears_body() -> dict:
    return {"name": _uniq("电话护栏单位")}


def _customer_body() -> dict:
    return {"name": _uniq("电话护栏客户"), "kind": "tmp"}


#: (值, 这条在防什么)
BAD_CONTACT_PHONES: list[tuple[str, str]] = [
    ("嘿嘿", "生产库 `orders.contact_dongjia_phone` 里真有的中文值"),
    ("刚刚好", "同一批脏值里的另一个（三字中文）"),
    ("abc1234567", "字母混数字：长度够、看着像号码，拨号盘不认"),
    ("138-0000-0000", "带分隔符：人眼读得懂，拨出去是空号"),
    ("１３８００００００００", "全角数字：Python 的 `\\d` 默认会把它当数字放行（第一版就漏了这条）"),
    ("+8613800000000", "带国际区号前缀：列里没有地方放 `+`，先按不合法处理"),
    ("222", "生产库 `shipper_contacts` 里真有的那一条"),
    ("12345", "5 位：原来 `ContactCreate` 写的是 `min_length=5`，刚好放行"),
    ("1380000000000", "13 位：比手机号还长，多半是多按了一位"),
    ("010-12345678", "座机带分隔符：写法常见，但存进去拨不出去（要用户去掉 `-`）"),
]

#: (值, 这条为什么必须**通过**)
GOOD_CONTACT_PHONES: list[tuple[str, str]] = [
    ("13800000000", "11 位手机号"),
    ("01012345678", "11 位座机（010 + 8 位）—— 不许要求它「以 1 开头」"),
    ("057188888888", "12 位（区号 0571 + 8 位）：上限取 12 就是为了它"),
    ("1234567", "7 位短号：规则的下限"),
]

#: 联系电话落地的每一个入口：(说明, 路径, **每次现算的** body 工厂, 要替换的字段)
#:
#: ⚠️ body 必须每次现算，不能是模块级共享的 dict：
#:   - 挂账单位名、客户名在库里有唯一约束，而端点内部 `commit()` 的数据**回滚不掉**
#:     （conftest 的 db_session 只能回滚没提交的部分），固定名字第二次就会 400「已存在」；
#:   - 派单员**代理下单**必须给 `temp_shipper_name`（否则 400「代理下单请选择货主或填写临时货主姓名」），
#:     货主本人下单则**不能**带 shipper_id。
CONTACT_ENDPOINTS: list[tuple[str, str, "Callable[[], dict]", str]] = [
    ("订单-货主电话", "/api/v1/orders", _order_body, "contact_dongjia_phone"),
    ("订单-老板电话", "/api/v1/orders", _order_body, "contact_boss_phone"),
    ("地址-收货人电话", "/api/v1/shipper/addresses", _address_body, "phone"),
    ("联系人电话", "/api/v1/shipper/contacts", _contact_body, "phone"),
    ("挂账单位电话", "/api/v1/arrears-units", _arrears_body, "phone"),
    ("客户档案电话", "/api/v1/customers", _customer_body, "phone"),
]

_ENDPOINT_IDS = [c[0] for c in CONTACT_ENDPOINTS]


def _post_contact(client: TestClient, token: str, path: str, make_body, field: str, value):
    body = make_body()
    body[field] = value
    return client.post(path, json=body, headers=auth_headers(token))


# --------------------------------------------------------------------------
# ① 非法联系电话：每个入口、每个坏值都必须 422 + 那句中文
# --------------------------------------------------------------------------

@pytest.mark.parametrize(("bad", "why"), BAD_CONTACT_PHONES, ids=[b[0] for b in BAD_CONTACT_PHONES])
@pytest.mark.parametrize(
    ("label", "path", "make_body", "field"), CONTACT_ENDPOINTS, ids=_ENDPOINT_IDS
)
def test_contact_phone_rejects_non_numeric(
    client: TestClient,
    token_dispatcher: str,
    label: str,
    path: str,
    make_body: Callable[[], dict],
    field: str,
    bad: str,
    why: str,
) -> None:
    """防的是：**这个入口的电话校验被删掉/漏加**（删掉就变 201，这条立刻红）。

    `why` 只是给失败信息用的说明，不参与断言。
    """
    r = _post_contact(client, token_dispatcher, path, make_body, field, bad)
    assert r.status_code == 422, (
        f"{label} 收了非法电话 {bad!r}（{why}）：期望 422，实际 {r.status_code}：{r.text[:300]}"
    )
    # 中文原样出现在 body 里 —— App 对含中文的 msg 是**直接显示**的
    assert CONTACT_PHONE_MESSAGE in r.text, (
        f"{label} 的报错必须是 phone.py 那句中文（App 原样显示给用户），实际：{r.text[:300]}"
    )
    # 反向：不许把 Pydantic 的英文甩出来（那会走 Android 的翻译表，翻不到就显示英文）
    assert "String should" not in r.text and "value_error" not in r.json()["detail"], r.text[:300]


# --------------------------------------------------------------------------
# ② 合法联系电话：一个都不许被挡（挡掉座机是本轮明确不许发生的事）
# --------------------------------------------------------------------------

@pytest.mark.parametrize(("good", "why"), GOOD_CONTACT_PHONES, ids=[g[0] for g in GOOD_CONTACT_PHONES])
@pytest.mark.parametrize(
    ("label", "path", "make_body", "field"), CONTACT_ENDPOINTS, ids=_ENDPOINT_IDS
)
def test_contact_phone_accepts_real_numbers(
    client: TestClient,
    token_dispatcher: str,
    label: str,
    path: str,
    make_body: Callable[[], dict],
    field: str,
    good: str,
    why: str,
) -> None:
    """防的是：**规则被收紧**（例如给联系电话加上「11 位必须 1 开头」会把 `01012345678` 挡掉）。"""
    r = _post_contact(client, token_dispatcher, path, make_body, field, good)
    assert r.status_code in (200, 201), (
        f"{label} 把合法电话 {good!r}（{why}）挡掉了：{r.status_code}：{r.text[:300]}"
    )
    # 不只是"收下了"，还必须是**原样**存回去的（别在中间被截断/改写）
    assert r.json()[field] == good, f"{label} 存回来的电话是 {r.json()[field]!r}，不是 {good!r}"


# --------------------------------------------------------------------------
# ③ 可选语义：空串与 null 都算"没填"，不许被当成非法
# --------------------------------------------------------------------------

def test_contact_phone_blank_is_not_filled(
    client: TestClient, token_dispatcher: str
) -> None:
    """防的是：把「没填电话」也当成格式错误 —— 这些字段大多可选，
    逼用户填是在制造假数据（历史上就是这么产生 `[嘿嘿]` 的）。"""
    for label, path, make_body, field in CONTACT_ENDPOINTS:
        r = _post_contact(client, token_dispatcher, path, make_body, field, "")
        assert r.status_code in (200, 201), (
            f"{label} 把空电话当成了非法：{r.status_code}：{r.text[:300]}"
        )
        # 空值原样进去、原样出来（客户档案那边端点自己把空串归一成 NULL：
        # `customers.py` 写的是 `(body.phone or "").strip() or None` —— 那是既有口径，
        # 不是电话规则改的，所以两种"没填"的形状都接受）
        assert r.json()[field] in ("", None), (
            f"{label} 空电话存回来变成了 {r.json()[field]!r}"
        )


def test_contact_phone_patch_none_means_no_change(
    client: TestClient, token_dispatcher: str
) -> None:
    """PATCH 的 `None` = **不改这一项**（不是「清空」）——可选别名必须放行 None，
    否则「只改地址不碰电话」的请求会被 422 挡下。"""
    h = auth_headers(token_dispatcher)
    created = client.post(
        "/api/v1/shipper/addresses",
        json={"receiver_name": _uniq("电话护栏-PATCH"), "phone": "13800000000"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    aid = created.json()["id"]

    r = client.patch(f"/api/v1/shipper/addresses/{aid}", json={"phone": None}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "13800000000", "null 应该是「不改」，不许把电话清掉"

    # 同一入口的非法值仍然要拦（证明上面那次 200 不是"校验整个没了"）
    bad = client.patch(f"/api/v1/shipper/addresses/{aid}", json={"phone": "嘿嘿"}, headers=h)
    assert bad.status_code == 422, bad.text
    assert CONTACT_PHONE_MESSAGE in bad.text


#: 更新路径（PATCH）：(说明, 集合路径, body 工厂, 要替换的字段)
PATCH_ENDPOINTS: list[tuple[str, str, "Callable[[], dict]", str]] = [
    ("地址", "/api/v1/shipper/addresses", _address_body, "phone"),
    ("联系人", "/api/v1/shipper/contacts", _contact_body, "phone"),
    ("挂账单位", "/api/v1/arrears-units", _arrears_body, "phone"),
]


@pytest.mark.parametrize(
    ("label", "path", "make_body", "field"), PATCH_ENDPOINTS, ids=[p[0] for p in PATCH_ENDPOINTS]
)
def test_patch_endpoints_validate_contact_phone(
    client: TestClient,
    token_dispatcher: str,
    label: str,
    path: str,
    make_body: Callable[[], dict],
    field: str,
) -> None:
    """防的是：**只给 Create 加了校验、Update 漏加**。

    这两个 schema 是分开写的（`AddressUpdate` / `ContactUpdate` / `ArrearsUnitUpdate`），
    改单走的是 PATCH —— 漏一个，`POST` 拦得住、`PATCH` 照样能把 `嘿嘿` 写进去。
    """
    h = auth_headers(token_dispatcher)
    created = client.post(path, json=make_body(), headers=h)
    assert created.status_code == 201, created.text
    rid = created.json()["id"]

    bad = client.patch(f"{path}/{rid}", json={field: "嘿嘿"}, headers=h)
    assert bad.status_code == 422, (
        f"{label} 的 PATCH 绕过了电话校验：{bad.status_code}：{bad.text[:300]}"
    )
    assert CONTACT_PHONE_MESSAGE in bad.text, bad.text[:300]

    # 合法值（顺带带空格）仍然要能改，并且存的是去空格后的值。
    # ⚠️ 号码要现算：`shipper_contacts` 上有 (shipper_id, phone) 唯一约束，
    #    写死同一个号会撞 409「同主重复」，那是约束在起作用、与电话格式无关。
    good_phone = _uniq_mobile()
    good = client.patch(f"{path}/{rid}", json={field: f"  {good_phone}  "}, headers=h)
    assert good.status_code == 200, good.text
    assert good.json()[field] == good_phone, good.json()[field]

    # null = 不改这一项（可选别名必须放行 None）
    assert client.patch(f"{path}/{rid}", json={field: None}, headers=h).status_code == 200


def test_order_update_contact_phone_validated(
    client: TestClient, token_dispatcher: str
) -> None:
    """订单改单（PATCH）也是一条写入路径：Create 加了校验、Update 漏加的话，
    `POST` 建单拦得住、`PATCH` 改单照样能把 `嘿嘿` 写进去。"""
    h = auth_headers(token_dispatcher)
    created = client.post(
        "/api/v1/orders",
        json={
            "lines": [
                {"product_name_snapshot": "电话护栏-改单", "quantity": 1, "unit_price": "1", "line_total": "1"}
            ],
            "address_detail": "电话护栏地址",
            "temp_shipper_name": _uniq("电话护栏临时货主"),
            "contact_dongjia_phone": "13800000000",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    oid = created.json()["id"]

    bad = client.patch(f"/api/v1/orders/{oid}", json={"contact_dongjia_phone": "嘿嘿"}, headers=h)
    assert bad.status_code == 422, f"PATCH 绕过了电话校验：{bad.status_code}：{bad.text[:300]}"
    assert CONTACT_PHONE_MESSAGE in bad.text

    # 同一个字段的合法值仍然能改（证明不是"整个 PATCH 坏了"）
    good = client.patch(f"/api/v1/orders/{oid}", json={"contact_dongjia_phone": "01012345678"}, headers=h)
    assert good.status_code == 200, good.text
    assert good.json()["contact_dongjia_phone"] == "01012345678"


def test_contact_phone_strips_surrounding_spaces(
    client: TestClient, token_dispatcher: str
) -> None:
    """复制来的号码常带空格：**去空格后合法就要收下，并且存的是去空格后的值**
    （存着空格等于问题还在：拨号、导出、短信都会带着它）。"""
    r = client.post(
        "/api/v1/shipper/addresses",
        json={"receiver_name": _uniq("电话护栏-空格"), "phone": "  13800000000  "},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 201, r.text
    assert r.json()["phone"] == "13800000000", r.json()["phone"]


# --------------------------------------------------------------------------
# ④ 建账号的手机号：另一条规则（必须 11 位且 1 开头）
# --------------------------------------------------------------------------

def test_user_create_phone_requires_mobile_format(
    client: TestClient, token_dispatcher: str
) -> None:
    """防的是：建号手机号被放宽成自由文本 —— 账号同时是登录名，
    建出一个 10 位或用字母开头的号，等于建出一个**登不进来**的账号。"""
    h = auth_headers(token_dispatcher)
    base = {"password": "pass12345", "full_name": "电话护栏司机", "role": "driver"}

    phone = _uniq_mobile()
    ok = client.post("/api/v1/users", json={**base, "phone": phone}, headers=h)
    assert ok.status_code == 201, ok.text
    assert ok.json()["phone"] == phone
    assert ok.json()["username"] == phone, "没给 username 时账号就该是手机号"

    for bad in ("1380000000", "23800000000"):
        r = client.post("/api/v1/users", json={**base, "phone": bad}, headers=h)
        assert r.status_code == 422, f"建号收了非法手机号 {bad!r}：{r.status_code}：{r.text[:200]}"
        assert MOBILE_PHONE_MESSAGE in r.text, r.text[:300]


def test_user_update_phone_uses_same_mobile_rule(
    client: TestClient, token_dispatcher: str
) -> None:
    """防的是：**建号严格、改号随意**。`UserUpdate.phone` 原来只有 `min_length=5`，
    也就是「建号必须 11 位、改号可以改成任意 5 个字符」—— 改完当事人就登不进来了。

    ⚠️ 改的是**本用例自己建的那个号**，不是 conftest 里的测试司机：
    `users` fixture 靠 `phone="13800000003"` 反查司机，改掉它会让后面所有用例拿不到司机 token。
    """
    h = auth_headers(token_dispatcher)
    created = client.post(
        "/api/v1/users",
        json={"phone": _uniq_mobile(), "password": "pass12345",
              "full_name": "电话护栏-改号", "role": "driver"},
        headers=h,
    )
    assert created.status_code == 201, created.text
    uid = created.json()["id"]

    for bad in ("1380000000", "23800000000", "abcdefghijk"):
        r = client.patch(f"/api/v1/users/{uid}", json={"phone": bad}, headers=h)
        assert r.status_code == 422, f"改号收了非法手机号 {bad!r}：{r.status_code}：{r.text[:200]}"
        assert MOBILE_PHONE_MESSAGE in r.text, r.text[:300]
        assert client.get(f"/api/v1/users/{uid}", headers=h).json()["phone"] != bad

    # null = 不改（可选别名必须放行），改成一个合法号仍要能过
    assert client.patch(f"/api/v1/users/{uid}", json={"phone": None}, headers=h).status_code == 200
    new_phone = _uniq_mobile()
    good = client.patch(f"/api/v1/users/{uid}", json={"phone": new_phone}, headers=h)
    assert good.status_code == 200, good.text
    assert good.json()["phone"] == new_phone


# --------------------------------------------------------------------------
# ⑤ 登录绝不能跟着收紧（phone 字段实际是"手机号或用户名"）
# --------------------------------------------------------------------------

def test_login_request_accepts_letter_username() -> None:
    """防的是：有人图省事给 `LoginRequest.phone` 也标上 `MobilePhone` ——
    那会让**所有用字母用户名的人登不进来**（`schemas/auth.py` 的 `model_validator`
    明确说 phone 是"手机号或用户名"，`username` 可以是字母）。

    这里直接验 schema：字母登录名必须通过校验，且 `phone` 字段上不许挂着手机号规则。
    """
    m = LoginRequest.model_validate({"username": "shipper_alpha", "password": "pass12345"})
    assert m.phone == "shipper_alpha", "登录名要原样落到 phone 上（登录接口按它查账号）"

    for name in ("phone", "username"):
        metas = LoginRequest.model_fields[name].metadata
        assert not any(isinstance(x, AfterValidator) for x in metas), (
            f"LoginRequest.{name} 上挂了校验器 —— 登录是「手机号或用户名」，加数字规则会把人挡在门外"
        )


def test_letter_username_login_is_not_rejected_by_validation(
    client: TestClient,
) -> None:
    """同一条红线的**端到端**版本：用字母登录名登录，必须走到"账号/密码不对"（401），
    而不是被格式校验挡下（422）—— 422 就等于"所有人用用户名都登不进来"。"""
    r = client.post("/api/v1/auth/login", json={"username": "shipper_alpha", "password": "pass12345"})
    assert r.status_code != 422, f"字母登录名被格式校验挡下了：{r.status_code}：{r.text[:300]}"
    assert r.status_code == 401, f"不存在的账号应当是 401（用户名或密码错误），实际 {r.status_code}"


# --------------------------------------------------------------------------
# ⑥ 规则本身（纯函数，不起 HTTP）：边界与"少一次都算 bug"的那几条
# --------------------------------------------------------------------------

def test_contact_rule_boundaries() -> None:
    """位数边界：7 与 12 都算合法，6 与 13 都不算（收紧/放宽都会在这里红）。"""
    assert validate_contact_phone("1" * CONTACT_MIN_DIGITS) == "1" * CONTACT_MIN_DIGITS
    assert validate_contact_phone("1" * CONTACT_MAX_DIGITS) == "1" * CONTACT_MAX_DIGITS
    for bad in ("1" * (CONTACT_MIN_DIGITS - 1), "1" * (CONTACT_MAX_DIGITS + 1)):
        with pytest.raises(ValueError, match="数字"):
            validate_contact_phone(bad)


def test_contact_rule_keeps_landline_shaped_numbers() -> None:
    """`01012345678` 是 11 位但**不以 1 开头**：规则不许对它加"1 开头"（否则座机全废）。"""
    assert validate_contact_phone("01012345678") == "01012345678"


def test_rules_reject_fullwidth_digits() -> None:
    """全角数字：Python 的 `\\d` 默认匹配任何 Unicode 十进制数字，
    少了 `re.ASCII` 时全角号码会被放行（第一版实测漏了这条）。两条规则都必须挡。"""
    for value in ("１３８００００００００", "1３８０００００００"):
        with pytest.raises(ValueError):
            validate_contact_phone(value)
        with pytest.raises(ValueError):
            validate_mobile_phone(value)


def test_mobile_rule_is_exactly_eleven_digits_starting_with_one() -> None:
    assert validate_mobile_phone("13800000000") == "13800000000"
    for bad in ("1380000000", "23800000000", "13800000000 ", "abc", "138000000000"):
        with pytest.raises(ValueError, match="手机号"):
            validate_mobile_phone(bad)


def test_blank_contact_phone_is_kept_blank() -> None:
    """空串 / 纯空格 / None 一律当"没填"（这些字段大多可选）。"""
    assert validate_contact_phone("") == ""
    assert validate_contact_phone("   ") == ""
    assert validate_contact_phone(None) is None
