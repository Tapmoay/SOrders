"""司机"要收现金"但派单没勾选 → 必须**明确拒绝**，不许悄悄记成挂账（2026-09-19 真机 E2E 抓到）。

## 是怎么抓到的
真机三端 E2E 里，货主在模拟器上下了单、派单员用**设备上的 AI 助手**派了单（这些都是真 UI），
接着我用司机身份走 API 送达并传 `payment="cash"` —— 结果订单落成
`payment_method=arrears / paid=False`，接口**200**。

两边对同一件事的理解**相反**：司机以为自己收了现金，系统记的是"还没收"——
这块账会进入催收名单（客户会被追一笔已经付过的钱）。App 侧不会这么发
（「收取现金」按钮只在派单勾选后才出现），但"接口照收却按另一个意思记"正是这个项目
反复在治的那一类：**后端没有的语义要如实拒绝，不许悄悄换掉**。

修法：`_apply_complete_payment` 里明确要 cash 而 `collect_cash=False` → `ValueError`；
两个送达端点把它并进同一个 try（**整单回滚** + 400 带中文原因），避免"送达到一半"。
"""
from __future__ import annotations

from tests.conftest import auth_headers


def _delivered_order(client, h, users, *, collect_cash: bool) -> tuple[int, str]:
    """造一张派给司机、司机已接单的单；返回 (订单 id, 司机 token)。"""
    token_driver = client.post(
        "/api/v1/auth/login", json={"phone": "13800000003", "password": "123321"}
    )
    if token_driver.status_code != 200:
        # conftest 里的司机账号口令是 pass12345
        token_driver = client.post(
            "/api/v1/auth/login", json={"phone": users["driver"].phone, "password": "pass12345"}
        )
    dtok = token_driver.json()["access_token"]

    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [{"product_name_snapshot": "现金探针", "quantity": 1, "unit_price": "10"}],
            "address_detail": "现金探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    assert client.post(
        f"/api/v1/orders/{oid}/assign",
        json={"driver_id": users["driver"].id, "freight_fee": "20", "collect_cash": collect_cash},
        headers=h,
    ).status_code == 200
    assert client.post(f"/api/v1/orders/{oid}/driver-ack", headers=auth_headers(dtok)).status_code == 200
    return oid, dtok


def test_cash_without_dispatch_opt_in_is_rejected(client, db_session, users, token_dispatcher):
    """没勾「收取现金」时传 cash → 400，且**订单状态不许被改**（整单回滚）。"""
    h = auth_headers(token_dispatcher)
    oid, dtok = _delivered_order(client, h, users, collect_cash=False)

    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/cash.jpg"], "payment": "cash"},
        headers=auth_headers(dtok),
    )
    assert r.status_code == 400, f"越权收现金必须被拒：{r.status_code} {r.text}"
    assert "收取现金" in r.json()["detail"]

    # 整单回滚：状态仍是已接单，没有送达时间
    got = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert got["status"] == "ACCEPTED", f"被拒的请求不该把单送达到一半：{got['status']}"
    assert got["delivered_at"] is None


def test_cash_with_dispatch_opt_in_still_works(client, db_session, users, token_dispatcher):
    """对照：派单勾了「收取现金」→ 司机选现金正常落 paid=True（别把正当需求堵死）。"""
    h = auth_headers(token_dispatcher)
    oid, dtok = _delivered_order(client, h, users, collect_cash=True)

    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/cash2.jpg"], "payment": "cash"},
        headers=auth_headers(dtok),
    )
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert got["status"] == "DELIVERED"
    assert got["paid"] is True and got["payment_method"] == "cash"


def test_arrears_without_opt_in_is_still_allowed(client, db_session, users, token_dispatcher):
    """没勾选时按挂账提交（这是默认路径）仍然正常 —— 别把正当需求堵死。"""
    h = auth_headers(token_dispatcher)
    oid, dtok = _delivered_order(client, h, users, collect_cash=False)
    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["/static/uploads/delivery/arr.jpg"], "payment": "arrears"},
        headers=auth_headers(dtok),
    )
    assert r.status_code == 200, r.text
    got = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert got["status"] == "DELIVERED"
    assert got["paid"] is False and got["payment_method"] == "arrears"


def test_delivery_photo_must_be_a_real_upload(client, db_session, users, token_dispatcher):
    """送达照片不许是随手编的字符串（2026-09-19 全项目报告 L-14，低）。

    原来只判"列表非空" —— 传一个字符 `x` 就算履行了拍照义务，而这条义务的意义是
    "送到时留证"。判据改为"必须是本系统上传端点的产物形状"。
    判据刻意只认前缀、不碰文件系统：见 `order_flow.complete_delivery` 里的注释。
    """
    h = auth_headers(token_dispatcher)
    oid, dtok = _delivered_order(client, h, users, collect_cash=False)

    r = client.post(
        f"/api/v1/orders/{oid}/complete",
        json={"delivery_photo_urls": ["x"]},
        headers=auth_headers(dtok),
    )
    assert r.status_code == 400, f"随手编的照片地址必须被拒：{r.status_code} {r.text[:200]}"
    assert "本系统上传" in r.json()["detail"]

    # 整单回滚：被拒的请求不该把单送达到一半
    got = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert got["status"] == "ACCEPTED", f"被拒的请求改了订单状态：{got['status']}"


def test_photo_delivery_refuses_before_writing_any_file(
    client, db_session, users, token_dispatcher, token_driver
):
    """拍照送达：**权限/存在性判完之前不许落盘**（2026-09-19 全项目报告 P1-11，中）。

    这个端点原来取到单就直接 `_save_delivery_uploads`，把"是不是你的单 / 单在不在"
    留给后面的 `complete_delivery`：于是任意司机的令牌都能对任意 `order_id` 把文件写进
    **匿名可读的公开静态目录**（拒绝发生在文件落盘之后），而单号不存在时抛的是
    `AttributeError`（`except ValueError` 接不住）→ 500。
    这条用例钉两件事：状态码是 404/403（不是 500），以及**磁盘上什么都没多**。
    """
    from pathlib import Path

    h = auth_headers(token_dispatcher)
    drv = auth_headers(token_driver)

    def files_in(order_id: int) -> set[str]:
        """这一单的上传目录里现在有哪些文件。

        ⚠️ 判据是"**前后文件集合不变**"，不是"目录不存在"：`backend/uploads/` 里躺着
        7~9 月开发期留下的目录（`/2`、`/3`、`/172`…），而测试库里新建订单的 id 会正好撞上它们，
        `exists()` 这种断言会在**与本次改动无关**的情况下红掉。
        """
        d = Path("uploads") / "delivery" / str(order_id)
        return {p.name for p in d.iterdir() if p.is_file()} if d.is_dir() else set()

    # ① 不存在的单号 → 404（不是 500），且不许写文件
    ghost = 999_123
    before = files_in(ghost)
    r = client.post(
        f"/api/v1/orders/{ghost}/complete-with-upload",
        files={"files": ("x.jpg", b"\xff\xd8\xff\xe0x", "image/jpeg")},
        data={"payment": "arrears"},
        headers=drv,
    )
    assert r.status_code == 404, (
        f"单号不存在应当是 404（原来是 AttributeError → 500）：{r.status_code} {r.text[:200]}"
    )
    assert files_in(ghost) == before, "权限/存在性还没判完就把文件写到磁盘上了"

    # ② 存在、但不是他的单（派单员刚下、还没派司机）→ 403，同样不许写文件
    r = client.post(
        "/api/v1/orders",
        json={
            "shipper_id": users["shipper"].id,
            "lines": [{"product_name_snapshot": "越权落盘探针", "quantity": 1, "unit_price": "10"}],
            "address_detail": "越权落盘探针地址",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    oid = int(r.json()["id"])
    before = files_in(oid)
    r = client.post(
        f"/api/v1/orders/{oid}/complete-with-upload",
        files={"files": ("y.jpg", b"\xff\xd8\xff\xe0y", "image/jpeg")},
        data={"payment": "arrears"},
        headers=drv,
    )
    assert r.status_code == 403, f"不是他的单应当是 403：{r.status_code} {r.text[:200]}"
    assert files_in(oid) == before, "别人的单也被写进公开静态目录了（P1-11）"


def test_photo_delivery_path_also_completes_and_logs_payment(
    client, db_session, users, token_dispatcher
):
    """**拍照送达**（`/complete-with-upload`，司机端主力路径）必须能送达，且收款处理照旧留痕。

    为什么单独立这条（2026-09-19 全项目 bug 报告 P1-10，实测恒 500）：
    这个端点调用收款处理时**漏传了第一个位置参数** → `TypeError` —— 而它是
    `except ValueError` **接不住**的异常类型，于是必然 500。上面三条用例全走
    `/complete`（JSON），所以 100% 绿也照不出这个洞：**契约只覆盖了两条送达路径里的一条**。
    后果不是"少记一笔"而是整笔回滚：`complete_delivery` 已经改状态/扣库存/入账/生成司机账单，
    只有 `db.commit()` 没跑，而**照片已经落盘**（司机以为没送到，实际上传成功过一次）。

    这条用例只钉两件事：①这条路能送达；②收款处理的留痕在两条路径上都写（F1 要求的
    「钱的状态变过必须能回查」不能只有一条路径做到）。
    """
    h = auth_headers(token_dispatcher)
    oid, dtok = _delivered_order(client, h, users, collect_cash=False)

    r = client.post(
        f"/api/v1/orders/{oid}/complete-with-upload",
        files={"files": ("proof.jpg", b"\xff\xd8\xff\xe0photo-bytes", "image/jpeg")},
        data={"payment": "arrears", "driver_remark": "拍照送达契约"},
        headers=auth_headers(dtok),
    )
    assert r.status_code == 200, f"拍照送达这条路径必须能走通：{r.status_code} {r.text[:300]}"

    got = client.get(f"/api/v1/orders/{oid}", headers=h).json()
    assert got["status"] == "DELIVERED"
    assert got["delivery_photo_urls"], "上传成功的照片 URL 要落进订单"

    from app.models import OperationLog

    logs = (
        db_session.query(OperationLog)
        .filter(OperationLog.order_id == oid, OperationLog.action == "ORDER_COMPLETE")
        .all()
    )
    assert any("payment" in (x.change_content or "") for x in logs), (
        f"拍照送达这一侧没有把收款处理留痕：{[x.change_content for x in logs]}"
    )
