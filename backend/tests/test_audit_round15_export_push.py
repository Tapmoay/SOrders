"""第十五轮审计的回归测试：**账本导出任务的推送必须跑在主事件循环上**（R14-7，高危）。

## 缺陷形状（本轮专项 agent 报的「高」，我复核后确认）

`ledger_export_worker.py` 原来是一个**同步** `def` → Starlette 的 `BackgroundTasks`
把它丢进线程池（`starlette/background.py`：同步函数走 `run_in_threadpool`），
而它在后台线程里直接 `asyncio.run(emit_notification(n))` —— **新建了一个事件循环**。

socket.io 的 Redis 连接是在**主事件循环**里建的；跨事件循环复用同一条连接必然抛
`RuntimeError: ... got Future ... attached to a different loop`。后果不是"推送丢了"：

1. 产物文件与「导出完成」通知**都已经 commit 了**（先提交后推送）；
2. 推送抛异常 → 同一个 `except` 把任务翻成 `FAILED`；
3. 用户收到"导出完成"、点进任务页却看到失败；重试只会往 `exports/` 堆随机名孤儿文件。

⛔ **本机跑通不能作为证据**：本机 `SOCKET_REDIS_URL` 未配置（Socket.IO 走进程内内存模式），
所以这条路径在本机恰好不炸 —— 这也是它一直没被发现的原因。
本文件的 `test_export_push_runs_on_the_calling_event_loop` 用一个**绑定事件循环的假连接**
（"只能在建立它的那个循环里用"）把生产条件搬进单测：
只要后台任务再退回同步 `def`（于是被丢进线程池 → 推送发生在另一个循环），这条测试必红。

配套静态红线：`_tools/qa/_check_background_tasks.py`
（机器算出所有 `background_tasks.add_task` 的目标，要求全是 `async def`；
并禁止 `backend/app` 里出现 `asyncio.run(` / `new_event_loop(` / `run_until_complete(`）。
配套反向验证：`_tools/qa/_reverse_verify_background_tasks.py`。
"""
from __future__ import annotations

import asyncio
import ast
import inspect
import textwrap
from datetime import date
from pathlib import Path

import pytest

from tests.conftest import auth_headers


def _make_job(db_session, shipper_id: int):
    from app.models import LedgerExportJob
    from app.models.export_job import ExportFormat, ExportJobStatus

    job = LedgerExportJob(
        created_by_id=shipper_id,
        shipper_id=shipper_id,
        file_format=ExportFormat.EXCEL,
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        status=ExportJobStatus.PENDING,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _cleanup_export(name: str | None) -> None:
    if not name:
        return
    from app.services.ledger_export_paths import EXPORT_DIR

    p = Path(EXPORT_DIR) / name
    if p.exists():
        p.unlink()


# ------------------------------- 结构性判据：后台任务入口必须是协程
def test_export_task_entry_is_a_coroutine_function():
    """`async def` 是这条修复的全部：同步 `def` 会被丢进线程池，用不了主循环的连接。"""
    from app.services import ledger_export_worker as worker

    assert inspect.iscoroutinefunction(worker.run_ledger_export_job_task), (
        "run_ledger_export_job_task 退回同步函数 → Starlette 会把它丢进线程池，"
        "推送就会发生在另一个事件循环上（R14-7）"
    )
    # 重活那一半必须是同步的（它在线程里跑，不碰事件循环）
    assert not inspect.iscoroutinefunction(worker.run_ledger_export_job_sync)
    # ⚠️ 用 AST 判"有没有真的碰 asyncio"，不要用子串判——它的文档里就写着
    #    `asyncio.run(...)` 这个反例（"原来就是这么写的、所以会炸"），子串判会被自己的文档骗红。
    sync_tree = ast.parse(textwrap.dedent(inspect.getsource(worker.run_ledger_export_job_sync)))
    touched: list[str] = []
    for node in ast.walk(sync_tree):
        if isinstance(node, ast.Import):
            touched += [a.name for a in node.names if a.name.split(".")[0] == "asyncio"]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "asyncio":
                touched.append(node.module or "asyncio")
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "asyncio"
        ):
            touched.append(f"asyncio.{node.attr}")
    assert not touched, (
        f"同步部分（在后台线程里跑）不许碰事件循环，但它引用了：{touched} —— R14-7 就是这个形状"
    )


# ------------------------------- 反向验证：老实现的形状**真的**会触发这条断言
@pytest.mark.asyncio
async def test_the_old_sync_thread_shape_really_breaks_the_loop_affine_connection():
    """把老实现原样搬进来跑一次，证明上面那条测试的"探针"不是恒绿的摆设。

    老形状 = 同步后台任务（Starlette 丢线程池）+ 后台线程里 `asyncio.run(推送)`。
    这条测试断言：**同一个假连接，在调用方循环里能用，换一个循环就炸**。
    如果哪天有人把 `run_ledger_export_job_task` 退回同步 `def`，
    上面那条测试就会命中这里证明必然发生的那次 RuntimeError。
    """
    owner_loop = asyncio.get_running_loop()
    calls: list[bool] = []

    async def loop_affine_emit() -> None:
        ok = asyncio.get_running_loop() is owner_loop
        calls.append(ok)
        if not ok:
            raise RuntimeError("Task got Future attached to a different loop")

    # ① 同一个循环：正常
    await loop_affine_emit()
    assert calls == [True]

    # ② 老形状：换一个线程 + 新建事件循环 → 必炸
    def old_shape() -> None:
        asyncio.run(loop_affine_emit())

    with pytest.raises(RuntimeError, match="different loop"):
        await asyncio.to_thread(old_shape)
    assert calls == [True, False], f"探针没有区分出两个事件循环：{calls}"


# ------------------------------- 主判据：推送发生在**调用方的**事件循环上
@pytest.mark.asyncio
async def test_export_push_runs_on_the_calling_event_loop(db_session, users, monkeypatch):
    """把生产条件搬进单测：一条「只能在建立它的那个循环里用」的连接。

    真 Redis / socket.io 连接就是这样：谁建的谁才能 await 它。
    """
    from starlette.background import BackgroundTasks

    from app.models import LedgerExportJob, Notification
    from app.models.export_job import ExportJobStatus
    from app.services import ledger_export_worker as worker
    from app.services import message_center

    shipper = users["shipper"]
    job = _make_job(db_session, shipper.id)
    job_id = job.id

    owner_loop = asyncio.get_running_loop()
    seen: list[tuple[str, bool]] = []

    async def loop_affine_emit(user_id: int, event: str, data: dict) -> None:
        """模拟 socket.io 的连接：换一个事件循环就炸（真实报错文本见 R14-7）。"""
        ok = asyncio.get_running_loop() is owner_loop
        seen.append((event, ok))
        if not ok:
            raise RuntimeError(
                "Task got Future attached to a different loop（注入：跨事件循环复用连接）"
            )

    # 推送链路上所有能到 socket 的出口都换成这条假连接
    monkeypatch.setattr(message_center, "emit_to_user", loop_affine_emit, raising=True)
    monkeypatch.setattr(worker, "emit_to_user", loop_affine_emit, raising=True)

    # 走**真实的** Starlette 后台任务调度（同步函数走线程池，协程在主循环 await）
    tasks = BackgroundTasks()
    tasks.add_task(worker.run_ledger_export_job_task, job_id)
    await tasks()

    db_session.expire_all()
    done = db_session.get(LedgerExportJob, job_id)
    name = done.file_path
    try:
        # ① 推送必须发生过（而且是在调用方那个循环上）
        assert seen, "导出完成的推送一次都没发生"
        off_loop = [e for e, ok in seen if not ok]
        assert not off_loop, f"这些推送跑到了别的事件循环上（跨循环用连接，生产必炸）：{off_loop}"
        assert ("notification", True) in seen, f"没有推 notification 事件：{seen}"

        # ② 任务状态必须是「完成」，而且**产物文件名真的落库了**
        assert done.status == ExportJobStatus.DONE, (
            f"导出被翻成了 {done.status}（error={done.error_message!r}）——"
            "推送失败不许改任务状态，文件其实已经生成好了"
        )
        assert name, "任务标成完成却没有产物文件名"
        from app.services.ledger_export_paths import EXPORT_DIR

        assert (Path(EXPORT_DIR) / name).exists(), f"产物文件不存在：{EXPORT_DIR}/{name}"

        # ③ 「导出完成」通知必须落库，且 payload 里带着下载地址
        n = (
            db_session.query(Notification)
            .filter(Notification.recipient_id == shipper.id, Notification.type == "ledger_export")
            .order_by(Notification.id.desc())
            .first()
        )
        assert n is not None, "导出完成的通知没有落库"
        assert n.payload and n.payload.get("download_url"), f"通知里没有下载地址：{n.payload}"
        assert str(job_id) in str(n.payload.get("export_job_id")), n.payload
    finally:
        _cleanup_export(name)


# ------------------------------- 安全性判据：推送炸了不许把成功的导出改成失败
@pytest.mark.asyncio
async def test_push_failure_does_not_flip_a_successful_export_to_failed(
    db_session, users, monkeypatch
):
    """R14-7 的第二半：通知已经落库、文件已经生成，推送失败只是"少推一次"。"""
    from starlette.background import BackgroundTasks

    from app.models import LedgerExportJob
    from app.models.export_job import ExportJobStatus
    from app.services import ledger_export_worker as worker
    from app.services import message_center

    shipper = users["shipper"]
    job = _make_job(db_session, shipper.id)
    job_id = job.id

    async def always_explode(*_a, **_kw) -> None:
        raise RuntimeError("推送链路整个挂了")

    monkeypatch.setattr(message_center, "emit_to_user", always_explode, raising=True)
    monkeypatch.setattr(worker, "emit_to_user", always_explode, raising=True)

    tasks = BackgroundTasks()
    tasks.add_task(worker.run_ledger_export_job_task, job_id)
    await tasks()  # 不许把异常抛给调用方（后台任务的异常会污染响应）

    db_session.expire_all()
    done = db_session.get(LedgerExportJob, job_id)
    name = done.file_path
    try:
        assert done.status == ExportJobStatus.DONE, (
            f"推送失败把成功的导出翻成了 {done.status}：{done.error_message!r}"
        )
        assert done.error_message in (None, ""), "推送失败不该写进 error_message"
    finally:
        _cleanup_export(name)


# ------------------------------- 端到端：真的走一次 POST 建任务
def test_export_job_endpoint_creates_a_downloadable_file(client, token_shipper, users, db_session):
    """这条端点以前就是修过一轮的（R12-A1 下载 500）；这里钉住"建完真能下"。"""
    from app.models import LedgerExportJob
    from app.models.export_job import ExportJobStatus

    h = auth_headers(token_shipper)
    r = client.post(
        "/api/v1/ledger/export-jobs",
        json={
            "shipper_id": users["shipper"].id,
            "export_format": "excel",
            "date_from": str(date(2026, 9, 1)),
            "date_to": str(date(2026, 9, 30)),
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    job_id = r.json()["id"]

    db_session.expire_all()
    job = db_session.get(LedgerExportJob, job_id)
    name = job.file_path
    try:
        assert job.status == ExportJobStatus.DONE, (
            f"后台任务没有跑完：status={job.status} error={job.error_message!r}"
        )
        d = client.get(f"/api/v1/ledger/export-jobs/{job_id}/download", headers=h)
        assert d.status_code == 200, f"产物下载不了：{d.status_code} {d.text}"
        assert d.content[:2] == b"PK", "下载到的不是 xlsx（zip）内容"
    finally:
        _cleanup_export(name)
