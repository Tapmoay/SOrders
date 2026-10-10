"""FEAT-0019 消息分级：严重度（severity）与重点词（payload.emphasis）。

## 这条测试在钉什么
用户口径（2026-10-11，逐字）：「消息（底部 Tab）……要按消息类型做颜色区别，而且**只有未读状态
才有这个样式**」；「文字也要按风险程度着色……按风险程度分红 / 橙 / …（重要程度不同 → 文字颜色
不同）」；追加修正（同日晚）：「你的文字不能全部用颜色给他去搞出来……真正的重心是这几个字……
**全是重点就是没有重点**」。

落地成两件**互相独立**的事，两件都由"发消息这一侧"给出（客户端一个都不猜）：
1. `notifications.severity`（`info` / `warn` / `danger`）—— App 拿它决定**未读**卡正文的颜色，
   已读整条灰调（连高亮一起去掉）；
2. `payload["emphasis"]` —— 这条消息里哪几个字 / 哪个数字是重点；客户端不猜重点词，也不许整行上色。

四类档位都要有例子（任务书要求）：正常流转 = `info`、撤销 / 删单 / 退货一族 = `warn`、
库存低于报警阈值 = `danger`、应付已逾期 = `danger`；再加上"默认是 info"与
"`GET /notifications` 真的把 severity 带出来"。

⚠️ 这里刻意**不写死**判定结果之外的实现细节（比如表放在哪个变量里）：测试认的是
"这条 type 出来是这一档"，改实现不该改测试。
"""

import importlib.util

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.migrations import MIGRATIONS_DIR
from app.models import Notification, User
from app.services import message_center
from tests.conftest import auth_headers


def _mk(db: Session, recipient_id: int, type_: str, title: str = "标题", content: str = "正文") -> Notification:
    n = Notification(recipient_id=recipient_id, category="order", type=type_, title=title, content=content)
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


# ---------------------------------------------------------------- 判定本身（唯一一处）

def test_severity_rule_covers_the_four_classes() -> None:
    """四类各自的档位：正常流转 info、异常 warn、库存不足 danger、应付逾期 danger。"""
    assert message_center.severity_for("order.assigned") == "info"          # 正常派单
    assert message_center.severity_for("order.delivered") == "info"         # 已送达
    assert message_center.severity_for("order.revoked") == "warn"           # 订单被撤销
    assert message_center.severity_for("order.deleted") == "warn"           # 删单
    assert message_center.severity_for("order.returned") == "warn"          # 退货
    assert message_center.severity_for("stock.low") == "danger"             # 库存低于报警阈值
    assert message_center.severity_for("payable.overdue") == "danger"       # 应付已逾期
    assert message_center.severity_for("payable.due_soon") == "warn"        # 应付临期


def test_unknown_type_falls_back_to_info() -> None:
    """没登记的类型 = 普通消息（不是"假装很危险"），默认值就是 info。"""
    assert message_center.severity_for(None) == "info"
    assert message_center.severity_for("") == "info"
    assert message_center.severity_for("brand.new.type") == "info"
    assert Notification.__table__.c.severity.default.arg is not None  # 列默认值确实挂了东西


def test_model_default_computes_severity_for_paths_bypassing_the_factory(
    db_session: Session, users: dict[str, User]
) -> None:
    """**绕过工厂的裸构造**也必须拿到正确的档（这是"判定只有一处"真正的兜底）。

    今天有 6 条这样的路径：`services/data_retention.py` ×3、`services/ledger_export_worker.py`、
    `api/v1/notifications.py` 的 `POST /price-notify` 与 `POST /notifications`。
    列默认值按 `type` 现算 —— 否则"只有一个判定来源"就只是句口号，它们会安静地掉进 info。
    """
    warn = _mk(db_session, users["shipper"].id, "order.deleted", "订单已被删除", "订单 SO1 已被派单员删除。")
    assert warn.severity == "warn"
    info = _mk(db_session, users["shipper"].id, "system", "系统公告", "今晚维护。")
    assert info.severity == "info"


# ---------------------------------------------------------------- 工厂（create_message）

def test_create_message_stamps_severity_and_emphasis(db_session: Session, users: dict[str, User]) -> None:
    """工厂出口同时给两件事：severity 现算；重点词写进 payload（老字段一个都不动）。"""
    n = message_center.create_message(
        db_session,
        recipient_id=users["shipper"].id,
        category="order",
        type="order.revoked",
        title="订单已撤回",
        content="订单 SO2026 已被撤回：客户临时取消。",
        payload={"order_id": 1, "order_no": "SO2026"},
        emphasis=("客户临时取消",),
    )
    db_session.commit()
    db_session.refresh(n)

    assert n.severity == "warn"
    assert n.payload is not None
    # 顺序：这一类的"新闻词" → 调用方给的具体值 → payload 里的单号
    assert n.payload["emphasis"] == ["已被撤回", "客户临时取消", "SO2026"]
    assert n.payload["order_id"] == 1 and n.payload["order_no"] == "SO2026"


def test_payload_without_emphasis_stays_none() -> None:
    """没有 payload、也没有重点词 → 保持 None。

    ⛔ 别凭空造一个 `{}`：「没有 payload 就只读」是客户端的既有口径（FEAT-0019 契约第 3 条），
    塞个空对象会把它的判断改掉。
    """
    assert message_center.emphasis_payload(None, "system", "系统公告", "今晚维护。") is None
    # payload 本来就有、但没有重点词 → 明确写 `[]`（与"后端忘了填"区分开）
    assert message_center.emphasis_payload({"order_id": 1}, "system", "系统公告", "今晚维护。") == {
        "order_id": 1,
        "emphasis": [],
    }


def test_emphasis_never_marks_absent_or_whole_line_words() -> None:
    """⛔ 三条不许（用户否掉的"整行上色"就钉在这里）。"""
    # 正文里没有的词一个都不标（宁可没有重点，也不许标错重点）
    assert message_center.emphasis_for("order.revoked", "订单已撤回", "订单 SO1 已被撤回。", ("没出现的话",)) == [
        "已被撤回"
    ]
    # 整条标题 / 整段正文不许当重点词
    assert message_center.emphasis_for(None, "标题", "正文", ("正文", "标题")) == []
    # 一句整话不是"重点词"（超长直接丢）
    long_sentence = "这" * (message_center.MAX_EMPHASIS_CHARS + 6)
    assert message_center.emphasis_for(None, "标题", "正文" + long_sentence, (long_sentence,)) == []
    # 「全是重点就是没有重点」：最多 MAX_EMPHASIS 处
    words = tuple(f"w{i}" for i in range(message_center.MAX_EMPHASIS + 3))
    assert message_center.emphasis_for(None, "标题", " ".join(words), words) == list(
        words[: message_center.MAX_EMPHASIS]
    )


# ---------------------------------------------------------------- 出参（GET /notifications）

@pytest.mark.dispatcher
def test_get_notifications_exposes_severity(
    client: TestClient, token_dispatcher: str, users: dict[str, User], db_session: Session
) -> None:
    """severity 必须真的出现在 `GET /notifications` 的出参上（任务书契约第 1 条）。"""
    for type_ in ("system", "order.revoked", "stock.low"):
        _mk(db_session, users["shipper"].id, type_, f"标题 {type_}", "正文")

    r = client.get(
        "/api/v1/notifications",
        params={"recipient_id": users["shipper"].id},
        headers=auth_headers(token_dispatcher),
    )
    assert r.status_code == 200, r.text
    got = {row["type"]: row.get("severity") for row in r.json()}
    assert got.get("system") == "info"
    assert got.get("order.revoked") == "warn"
    assert got.get("stock.low") == "danger"


# ---------------------------------------------------------------- 迁移 032

def test_migration_032_is_rerunnable_and_defaults_to_info(tmp_path) -> None:
    """032：加列 + 建索引；**可重跑**；存量行一律 info（不回填成今天的判断）。"""
    path = MIGRATIONS_DIR / "032_notification_severity.py"
    spec = importlib.util.spec_from_file_location("mig032_for_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    engine = create_engine(f"sqlite:///{(tmp_path / 'mig032.db').as_posix()}")
    with engine.begin() as conn:
        # 升级前的样子：只有旧列
        conn.execute(text("CREATE TABLE notifications (id INTEGER PRIMARY KEY, type VARCHAR(64))"))
        conn.execute(text("INSERT INTO notifications (id, type) VALUES (1, 'order.revoked')"))

    mod.upgrade(engine)
    mod.upgrade(engine)  # 第二遍必须什么都不做（"可重跑"是迁移 README 的硬要求）

    assert "severity" in {c["name"] for c in inspect(engine).get_columns("notifications")}
    assert "ix_notifications_severity" in {i["name"] for i in inspect(engine).get_indexes("notifications")}
    with engine.begin() as conn:
        row = conn.execute(text("SELECT severity FROM notifications WHERE id = 1")).scalar()
    assert row == "info"
