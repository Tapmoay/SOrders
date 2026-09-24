"""卡住的导出任务必须被收敛成 FAILED（2026-09-24 第 32 轮；第 25 轮 08 区缺陷 1）。

## 缺陷长什么样
`run_ledger_export_job_sync` 先写 `status = PROCESSING` + **commit**，然后再干活。
进程在两步之间被重启/杀掉（或异常路径绕过它的 FAILED 分支），这一行就**永远停在 PROCESSING**
—— 全后端**没有任何收割者**（`PROCESSING` 的唯一写入点就是那个 worker）。
客户端轮询 60 次 × 2 秒之后**静默放弃**：用户看到的是"一直在导出中"，而它永远不会完成。

## 判据
读任务（`GET /export-jobs/{id}`）时顺手收敛：
- `created_at` 超过 `STALE_AFTER_MINUTES` 且状态仍是 PENDING/PROCESSING → 改成 **FAILED**
  并写一句能照做的原因；
- **终态不动**（DONE 永远不会被收敛，FAILED 不用再动）；
- **刚建的任务不动**（不能把正在跑的判成失败）—— 这一条是本用例的反空转。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from starlette.testclient import TestClient

from tests.conftest import auth_headers


def _mk_job(db_session, *, created_by: int, shipper_id: int, status: str, age_minutes: int) -> int:
    """直接插一条导出任务行（这里只关心"读的时候怎么判"）。

    `status` 用**出参那套小写**（`pending`/`processing`/`done`/`failed`）——
    与 `reap_stale_job` 的 WHERE 条件同源。
    """
    from app.core.business_time import utc_now_naive
    from app.models import LedgerExportJob

    job = LedgerExportJob(
        created_by_id=created_by,
        shipper_id=shipper_id,
        # ⚠️ 枚举按**出参**取值（`ExportFormat` 是 `EXCEL`/`PDF`，而状态出参是小写 —
        #    第 32 轮实测：`status` 回 `failed`/`processing`/`done` 不是大写）。
        #    本项目已经第三次踩 `.name` 与 `.value` 的差别（台账 D5-⑤ 记过）。
        file_format="EXCEL",
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        status=status,
    )
    db_session.add(job)
    db_session.flush()
    # `created_at` 由 TimestampMixin 写；这里把它推回过去，模拟"卡了很久"
    job.created_at = utc_now_naive() - timedelta(minutes=age_minutes)
    db_session.commit()
    return int(job.id)


@pytest.mark.dispatcher
@pytest.mark.regression
def test_卡住的导出任务读一次就变失败(
    client: TestClient, db_session, users: dict, token_dispatcher: str
) -> None:
    h = auth_headers(token_dispatcher)
    stale = _mk_job(
        db_session, created_by=users["dispatcher"].id, shipper_id=users["shipper"].id,
        status="PROCESSING", age_minutes=60,
    )
    r = client.get(f"/api/v1/ledger/export-jobs/{stale}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "failed", (
        f"卡了 60 分钟的导出任务读出来还是 {body['status']} —— 全后端没有收割者，"
        "它会永远停在导出中（客户端轮询 60×2s 后静默放弃）"
    )
    assert body["error_message"], "收敛成失败时必须说清原因（要能照着改）"
    assert "重新发起" in body["error_message"], body["error_message"]


@pytest.mark.dispatcher
@pytest.mark.regression
def test_正在跑和已完成的任务不许被误判(
    client: TestClient, db_session, users: dict, token_dispatcher: str
) -> None:
    """**反空转**：刚建的任务、以及已经 DONE 的任务都不能被这条规则碰到。"""
    h = auth_headers(token_dispatcher)
    fresh = _mk_job(
        db_session, created_by=users["dispatcher"].id, shipper_id=users["shipper"].id,
        status="PROCESSING", age_minutes=1,
    )
    done = _mk_job(
        db_session, created_by=users["dispatcher"].id, shipper_id=users["shipper"].id,
        status="DONE", age_minutes=600,
    )
    assert client.get(f"/api/v1/ledger/export-jobs/{fresh}", headers=h).json()["status"] == "processing", (
        "刚建 1 分钟的任务被误判成失败了 —— 那会把正在跑的导出判死"
    )
    assert client.get(f"/api/v1/ledger/export-jobs/{done}", headers=h).json()["status"] == "done", (
        "已经完成的任务被收敛了 —— 收敛只该动**非终态**的行"
    )
