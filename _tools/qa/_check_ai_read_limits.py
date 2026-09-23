"""红线：后端 `limit` 的**运行期**上限必须大于 AI 的 `MAX_ROWS`（否则截断探针必 422）。

## 由来（2026-09-24 第 25 轮；第 24 轮 04 区 P1 抓到第一例）
`AiReadService` 判断"后端还有没有更多行"的唯一办法是**多要一行**（`limit + 1`），
而上限是 `AiTools.MAX_ROWS = 200`。所以只要某个端点的 `limit` 上限 **≤ 200**：

    GET /places?limit=201  →  422 {"detail":"条数：不能大于 200","ctx":{"le":"200"}}

—— "地点"这张读表在 AI 那条路上**整条坏掉**（模型一问地点先吃一个 422，
用户看到的是"这个功能没上线"）。实测（修之前）三个角色全部 422。

## ⛔ 为什么必须看**运行期** OpenAPI，不能读 AST 字面量
`places.py` 写的是 `limit: int = Query(100, ge=1, le=MAX_LIST)` —— 上限是个**常量名**。
`_gen_ai_read_catalog.py:334` 那套 `ast.literal_eval` 遇到 `Name` 只会得到 `None`，
于是"上限是多少"在静态那一侧**根本读不出来**（这正是这一处骗过所有人的原因，
第 25 轮 09 区的审计员专门提醒了这一点）。
所以这里 `import app.main` 之后取 **`app.openapi()`**，读它算出来的 `maximum`。

## 判据
1. 取运行期 OpenAPI，找出所有带 `limit` 查询参数的 **GET** 端点；
2. 每个的 `maximum` 必须 **> MAX_ROWS**（= 至少能接住 `MAX_ROWS + 1` 那个探针）；
3. 反空转：带 `limit` 的端点少于 8 个 → 报错（扫描失效时先喊，不许安静全绿）；
4. `AiTools.kt` 里 `MAX_ROWS` 必须读得到（读不到就说明它改了名字，判据得跟着改）。

用法：python _tools/qa/_check_ai_read_limits.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
AI_TOOLS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiTools.kt"
MIN_LIMIT_ENDPOINTS = 8


def ai_max_rows() -> int | None:
    """AI 侧 `AiTools.MAX_ROWS`（探针的基数）。"""
    if not AI_TOOLS.exists():
        return None
    src = AI_TOOLS.read_text(encoding="utf-8")
    m = re.search(r"const val MAX_ROWS\s*=\s*(\d+)", src)
    return int(m.group(1)) if m else None


def limit_endpoints() -> list[tuple[str, int | None]]:
    """[(路径, 运行期 maximum)] —— 只取带 `limit` 查询参数的 GET 端点。

    ⚠️ 必须在 import `app.main` **之前**把 `DATABASE_URL` 指到一个 %TEMP% 的一次性库：
    本机环境下它默认指向 MySQL，而这里**不需要任何数据**（只读路由表算出来的 OpenAPI），
    连不上就整条判据空转（第一版就是那么红的 —— 报"只认出 0 个端点"）。
    与 `tests/conftest.py` 同一个套路（它也先在 import app 之前设 DATABASE_URL）。
    """
    import os  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    probe_db = Path(tempfile.gettempdir()) / "sorders_openapi_probe.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{probe_db.as_posix()}"
    sys.path.insert(0, str(BACKEND))
    try:
        from app.main import fastapi_app  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 起不来 FastAPI 应用（读不到运行期 schema）：{type(exc).__name__}: {exc}")
        return []
    spec = fastapi_app.openapi()
    out: list[tuple[str, int | None]] = []
    for path, ops in (spec.get("paths") or {}).items():
        for method, op in (ops or {}).items():
            if method.lower() != "get":
                continue
            for prm in op.get("parameters") or []:
                if prm.get("name") != "limit" or prm.get("in") != "query":
                    continue
                schema = prm.get("schema") or {}
                out.append((f"GET {path}", schema.get("maximum")))
    return out


def main() -> int:
    fails: list[str] = []
    max_rows = ai_max_rows()
    if max_rows is None:
        fails.append("读不到 `AiTools.kt` 里的 `MAX_ROWS` —— 判据失配（它改名了就同步改这里）")
        max_rows = 200  # 兜底：仍按 200 判，避免因为读不到就整条空转

    eps = limit_endpoints()
    print(f"AI 侧 MAX_ROWS = {max_rows}；运行期带 `limit` 的 GET 端点 {len(eps)} 个：")
    bad: list[str] = []
    for path, maximum in sorted(eps):
        if maximum is None:
            # 没有上限 = 一定能接住探针，安全（但要在打印里看得见）
            print(f"   · {path:45} maximum=无上限 ✓")
            continue
        ok = maximum > max_rows
        print(f"   · {path:45} maximum={maximum}{' ✓' if ok else '  ❌ ≤ MAX_ROWS，探针必然 422'}")
        if not ok:
            bad.append(f"{path}（maximum={maximum}）")

    if bad:
        fails.append(
            "这些端点的 `limit` 上限 ≤ AI 的 MAX_ROWS —— AI 的截断探针会发 `limit + 1`，"
            "它们会直接 422，对应的读能力整条坏掉（`/places` 就是这么坏的，第 24 轮 04 区 P1）："
            + "、".join(bad)
        )
    if len(eps) < MIN_LIMIT_ENDPOINTS:
        fails.append(
            f"只认出 {len(eps)} 个带 limit 的 GET 端点（<{MIN_LIMIT_ENDPOINTS}）——"
            "扫描失效了，这条判据此刻证明不了什么"
        )

    if fails:
        print("\n❌ AI 读上限：")
        for f in fails:
            print("   - " + f)
        print("\n（修法：把该端点的 `le` 提到 >200（与 /users、/products 一样 500 即可）。）")
        return 1
    print(f"\n✅ {len(eps)} 个带 limit 的 GET 端点都能接住 AI 的 `MAX_ROWS + 1` 探针。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
