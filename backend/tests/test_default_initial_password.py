"""CHG-0118 · **所有账号的初始密码默认是 123321**（用户 2026-10-11 定的规定）。

规定原文：「我们的所有账号初始密码默认是 123321，这是**规定死的**。AI 也要知道 ——
比如说我叫它创建一个账号，它**直接帮我创建好、不要问我密码是什么**。」

所以这里钉的**不是**"某个默认参数"，而是四件事（缺一件这条规定就没落地）：

1. **不给密码也建得出来** —— 而且是"能用默认密码登录"的那种建出来（有人能登才算账号建成）；
2. **给了密码就按给的** —— 默认值不许覆盖用户明确给出的密码（这是同一条规定的另一半）；
3. **密码不进返回体**（`UserOut` 里根本没有这个字段）；
4. **密码不进审计**（`operation_logs.change_content` 连哈希都不许有）——既有规矩，见
   `api/v1/users.py::create_user` 里那句「⛔ 绝不记密码」。

⛔ 与"本机开发库那三个测试号的口令恰好也是 123321"是两件事：那是环境事实
（`docs/PROJECT_MAP/05_TESTING.md`），这是产品规定。两边别互相复用。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import DEFAULT_INITIAL_PASSWORD, verify_password
from app.models import OperationLog, User
from app.schemas.user import UserCreate
from tests.conftest import auth_headers

# 手机号取值刻意与本套件其它用例错开（同一个 worker 的库是复用的）。
PHONE_NO_PASSWORD = "13500118118"
PHONE_OWN_PASSWORD = "13500118119"
PHONE_AUDIT = "13500118120"
OWN_PASSWORD = "Zx9-Qw2-By7"  #: 刻意不是任何"默认值"形状


def _create(client: TestClient, headers: dict[str, str], phone: str, **extra: object):
    body: dict[str, object] = {"phone": phone, "role": "shipper", "full_name": "默认口令用例"}
    body.update(extra)
    return client.post("/api/v1/users", json=body, headers=headers)


def test_不给密码也能建号_且默认密码真的能登录(
    client: TestClient, token_dispatcher: str
) -> None:
    """① 规定的主干：**不要问密码**。少了中间那句"用默认密码登录成功"，这条只证明了"没报错"。"""
    r = _create(client, auth_headers(token_dispatcher), PHONE_NO_PASSWORD)
    assert r.status_code == 201, r.text
    assert r.json()["phone"] == PHONE_NO_PASSWORD

    login = client.post(
        "/api/v1/auth/login",
        json={"phone": PHONE_NO_PASSWORD, "password": DEFAULT_INITIAL_PASSWORD},
    )
    assert login.status_code == 200, f"默认初始密码登不进去，账号等于白建：{login.text[:300]}"
    assert login.json().get("access_token")


def test_给了密码就按给的_默认密码登不进去(
    client: TestClient, token_dispatcher: str
) -> None:
    """② 同一条规定的另一半：用户明确给了密码时，**默认值不许盖掉他给的那个**。"""
    r = _create(
        client, auth_headers(token_dispatcher), PHONE_OWN_PASSWORD, password=OWN_PASSWORD
    )
    assert r.status_code == 201, r.text

    mine = client.post(
        "/api/v1/auth/login",
        json={"phone": PHONE_OWN_PASSWORD, "password": OWN_PASSWORD},
    )
    assert mine.status_code == 200, f"用户给的密码登不进去：{mine.text[:200]}"

    default = client.post(
        "/api/v1/auth/login",
        json={"phone": PHONE_OWN_PASSWORD, "password": DEFAULT_INITIAL_PASSWORD},
    )
    assert default.status_code != 200, "默认密码不该能登进一个「用户指定了密码」的账号"


def test_默认值只有一处_schema_直接引用常量() -> None:
    """③ 判"只有一处默认"：schema 的默认值**就是**那个常量本身，而不是抄了一份字面量。"""
    assert DEFAULT_INITIAL_PASSWORD == "123321"
    assert UserCreate.model_fields["password"].default == DEFAULT_INITIAL_PASSWORD
    # 不给密码也能构造出请求体（"可选"这件事在 schema 层就成立，不必等到 HTTP 层）
    body = UserCreate(phone="13500118121", role="driver")
    assert body.password == DEFAULT_INITIAL_PASSWORD
    # 给了就留着
    given = UserCreate(phone="13500118122", role="driver", password=OWN_PASSWORD)
    assert given.password == OWN_PASSWORD


def test_太短的密码仍然被拒() -> None:
    """④ 边界：默认值不等于"校验放宽"。5 位密码照样 422（默认值 6 位是**下限**，不是特例）。"""
    try:
        UserCreate(phone="13500118123", role="shipper", password="12345")
    except Exception as exc:  # pydantic ValidationError
        assert "at least 6 characters" in str(exc) or "min_length" in str(exc), str(exc)
    else:
        raise AssertionError("5 位密码不该通过（min_length=6 是既有规矩，不许被这次改动碰掉）")


def test_建号时密码不进审计日志(
    client: TestClient, token_dispatcher: str, db_session: Session
) -> None:
    """⑤ 既有规矩：`operation_logs` 是**给人看的审计页，不是凭据库** —— 明文与哈希都不许进。"""
    r = _create(
        client, auth_headers(token_dispatcher), PHONE_AUDIT, password=OWN_PASSWORD
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]

    row = (
        db_session.query(OperationLog)
        .filter(OperationLog.action == "USER_CREATE")
        .order_by(OperationLog.id.desc())
        .first()
    )
    assert row is not None, "建号必须留一条审计（既有的 USER_CREATE 日志）"
    payload = row.change_content or ""
    assert str(new_id) in payload, f"审计里要能认出是哪条账号：{payload[:200]}"
    assert OWN_PASSWORD not in payload, f"审计里出现了密码明文：{payload[:200]}"
    user = db_session.get(User, new_id)
    assert user is not None
    assert user.password_hash not in payload, "审计里出现了口令哈希（同样不许）"
    assert verify_password(OWN_PASSWORD, user.password_hash) is True


def test_返回体里没有密码字段(client: TestClient, token_dispatcher: str) -> None:
    """⑥ 出参口径：`UserOut` 里没有 password —— 建号响应也是这一份。"""
    r = _create(client, auth_headers(token_dispatcher), "13500118124")
    assert r.status_code == 201, r.text
    assert "password" not in r.json()
    assert DEFAULT_INITIAL_PASSWORD not in r.text
