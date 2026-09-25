"""账本导出产物的**唯一命名与定位规则**（`exports/` 下）。

## 为什么单独一个模块（2026-09-19 审计，R12-A1）
上一轮把产物从公开的 `uploads/` 挪到 `exports/` 之后，留了两个半成品：
1. 生成函数返回的是**下载 URL**（`/api/v1/ledger/export-jobs/{id}/download`），
   任务行把它存进 `file_path`；而下载端点读的是 `job.download_url`（**模型上根本没有这个属性**）
   → `AttributeError` → **每次下载必然 500**（`ledger.py:445`）；
2. 就算把属性名改对，`file_path` 里存的是 URL、最后一段是 `download`，
   端点会拿它当文件名去磁盘上找 → 404。

根因是**"产物叫什么"这件事有三份各写各的**：生成处拼名字、任务行存 URL、下载端点猜文件名。
现在收敛到这里：生成用 [export_file_name]，定位用 [find_export_file]，URL 用 [download_url]。
"""
from __future__ import annotations

import secrets
from pathlib import Path

from app.config import uploads_root

#: 新产物目录（**不在公开的 uploads/ 之下**）
EXPORT_DIR = Path("exports")
#: 历史产物所在（老 job 的 file_path 指向这里）；只用于兼容读取，不再往这里写。
LEGACY_UPLOAD_EXPORTS = uploads_root() / "exports"


def ensure_export_dir() -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def export_file_name(shipper_id: int, job_id: int, fmt: str) -> str:
    """导出产物的文件名。

    ⚠️ 随机段是**安全要求**（2026-09-19 审计）：原来是 `ledger_{shipper_id}_{job_id}.{ext}`，
    两个都是小整数 → 谁都能枚举出"每个货主的账本"。有了随机段，即使路径泄漏也不可猜。
    """
    ext = "xlsx" if fmt == "excel" else "pdf"
    return f"ledger_{shipper_id}_{job_id}_{secrets.token_urlsafe(12)}.{ext}"


def download_url(job_id: int) -> str:
    """给前端/站内信用的下载地址（**带鉴权**，只有本端点能取）。"""
    return f"/api/v1/ledger/export-jobs/{job_id}/download"


def legacy_file_names(shipper_id: int, job_id: int) -> list[str]:
    """老格式（`ledger_{shipper_id}_{job_id}.{ext}`）——兼容上线前留下的产物。"""
    return [f"ledger_{shipper_id}_{job_id}.xlsx", f"ledger_{shipper_id}_{job_id}.pdf"]


def find_export_file(name: str, shipper_id: int, job_id: int) -> Path | None:
    """按存下来的名字找产物；找不到再按**老格式**在新旧两个目录里兜一次。

    只接受**纯文件名**（挡目录穿越）：调用方传进来的应当是 [export_file_name] 的产物，
    但历史数据里可能有整条 URL（老代码存的就是 URL），所以这里对 URL 形态做一次兼容解析。
    """
    candidates: list[str] = []
    if "/" in name or "\\" in name:
        # 老数据：存的是 URL（`/static/uploads/exports/ledger_2_1.xlsx` 或我们自己的 download 端点）
        tail = name.rstrip("/").rsplit("/", 1)[-1]
        if tail and tail != "download":
            candidates.append(tail)
        candidates.extend(legacy_file_names(shipper_id, job_id))
    else:
        candidates.append(name)

    for base in (EXPORT_DIR, LEGACY_UPLOAD_EXPORTS):
        for c in candidates:
            if not c or c.startswith(".") or "/" in c or "\\" in c:
                continue
            p = base / c
            if p.is_file():
                return p
    return None
