"""唯一约束冲突必须回 **409 + 中文**，不是 500（2026-09-19 审计的缺陷 G7）。

## 原来的样子
全库**没有 `IntegrityError` 处理器**。而唯一约束冲突是**正常业务**会遇到的：
同一车牌/同分类名/同挂账单位名/同联系人电话建两次，或者**并发（双击）提交**同一条记录
（"先查再插"在并发下必然撞约束——这正是加唯一约束的目的）。
它们一律变成 `500 Internal Server Error`：用户以为系统坏了，然后**重试**，把冲突刷得更多。

这个文件钉住：**冲突回 409、文案是中文、并且说的是"已经有一条一模一样的"**。
"""
from __future__ import annotations

from tests.conftest import auth_headers


def test_duplicate_vehicle_plate_returns_409(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    body = {"plate_no": "测A12345", "vehicle_type": "small"}
    first = client.post("/api/v1/vehicles", json=body, headers=h)
    assert first.status_code in (200, 201), first.text

    again = client.post("/api/v1/vehicles", json=body, headers=h)
    # 400（端点自己有"车牌已存在"的先查）与 409（撞唯一约束）都算对；**500 不算**。
    # 文案不在这里逐字钉（它属于界面文案，改措辞不该让测试红）。
    assert again.status_code in (400, 409), f"重复车牌不能是 500：{again.status_code} {again.text}"
    assert (again.json().get("detail") or "").strip(), "拒绝时必须给一句能看懂的中文"


def test_duplicate_category_name_returns_409_not_500(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r1 = client.post("/api/v1/product-categories", json={"name": "探针分类"}, headers=h)
    assert r1.status_code in (200, 201), r1.text
    r2 = client.post("/api/v1/product-categories", json={"name": "探针分类"}, headers=h)
    assert r2.status_code in (409, 400), f"重名分类应当被明确拒绝：{r2.status_code} {r2.text}"
    # 400（业务校验先拦）与 409（撞唯一约束）都算对；**500 不算**
    assert r2.status_code != 500


def test_duplicate_arrears_unit_returns_409(client, token_dispatcher):
    h = auth_headers(token_dispatcher)
    r1 = client.post("/api/v1/arrears-units", json={"name": "探针挂账单位"}, headers=h)
    assert r1.status_code in (200, 201), r1.text
    r2 = client.post("/api/v1/arrears-units", json={"name": "探针挂账单位"}, headers=h)
    assert r2.status_code in (409, 400), f"重名挂账单位应当被明确拒绝：{r2.status_code} {r2.text}"


def test_integrity_error_handler_speaks_chinese():
    """处理器本身的形状：接的是 IntegrityError、回的是 409、文案是中文。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "app/main.py").read_text(encoding="utf-8")
    assert "@application.exception_handler(IntegrityError)" in src
    assert "status_code=409" in src
    assert "已经有一条一模一样的记录" in src
