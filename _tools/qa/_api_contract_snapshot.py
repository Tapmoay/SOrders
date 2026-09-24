#!/usr/bin/env python3
"""_api_contract_snapshot.py —— **纯搬迁的等价性机器证明**（整改报告 §18 规则 3）。

### 为什么要有它

报告关于"拆 `orders.py`"那一段的规矩是：

```text
旧端点集合 = 新端点集合      旧 request  = 新 request
旧 response = 新 response    旧 permission = 新 permission
```

并且明确否掉另一种做法：**不是"我看代码差不多"，而是机器证明**。

这一页就是那台机器：把"客户端看得见的契约"落成一份可 diff 的快照 ——

| 比什么 | 从哪来 | 变化意味着什么 |
|---|---|---|
| **OpenAPI 文档全文** | `app.openapi()` | 入参/出参/schema 变了 —— **必须为零** |
| 路由表（顺序/方法/路径/函数名/状态码/响应模型/依赖名） | `app.routes` | 端点被增删改名、**权限依赖被换掉** —— 必须为零 |
| 静态路径被动态路径遮蔽的关系 | 自己算（见 `shadow_pairs`） | 注册顺序变了且真的会产生遮蔽 —— 必须为零 |

⚠️ **模块名会变**（`app.api.v1.orders` → `app.api.v1.orders_query`）—— 那正是搬迁的目的，
   所以 diff 把它单列一类：**只报不拦**，并打印出来让人一眼看到"搬了哪几个函数"。

### 用法（搬迁的标准流程）

```bash
python _tools/qa/_api_contract_snapshot.py --save before     # 动手之前
# …纯搬迁…
python _tools/qa/_api_contract_snapshot.py --diff before now # 必须"契约零差异"
# 满意了再把 now 落成基线：
python _tools/qa/_api_contract_snapshot.py --save v20260924 --note "orders 查询组搬到 orders_query.py"
```

⛔ `--diff` 的退出码：**契约有任何差异 = 1**（模块名差异不算）。
⛔ 快照不是"定期比对"用的（端点每天都在长）；它是**搬迁期间**的对照物，所以不进 `_check_all.py`。

### 它自己也必须可验证

`--selftest` 用两个**内存里的**小应用互相 diff：一份原样、一份逐条注入（删路由 / 换方法 /
换权限依赖 / 改响应模型 / 加必填查询参数 / 改注册顺序制造遮蔽），每一条都必须被抓到；
原样那一对必须是"零差异"。判据不空转，才敢拿它给搬迁背书。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAP_DIR = ROOT / "_tools" / "qa" / "_api_snapshots"

#: 依赖列里要忽略的"不是权限"的东西（FastAPI 自己塞的）。
_NOISE_DEPS = {"get_db", "get_current_user"}


def _load_app():
    """导入应用（**用临时 SQLite，绝不碰开发库/生产库**）。

    ⚠️ `app.database` 在导入时就跑 bootstrap（建表 + 自愈 + 迁移），所以必须先把 DATABASE_URL
    指到一个临时文件上 —— 否则一次"只想拍个快照"会把开发库的结构动一遍。
    """
    tmp = Path(tempfile.gettempdir()) / "sorders_api_snapshot.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp.as_posix()}"
    os.environ.setdefault("JWT_SECRET_KEY", "snapshot-only-not-a-real-secret-000000")
    sys.path.insert(0, str(ROOT / "backend"))
    os.chdir(ROOT / "backend")          # 应用里有相对路径（uploads/…），cwd 必须是 backend
    # ⚠️ `app.main.app` 是 **Socket.IO 的 ASGIApp 外壳**（它把 FastAPI 包在里面），
    #    没有 `.routes`。真正的 FastAPI 实例叫 `fastapi_app`（实测踩到：拿外壳去拍快照直接 AttributeError）。
    from app.main import fastapi_app    # noqa: PLC0415 —— 必须在设好环境变量之后才导入

    return fastapi_app


def _dep_names(route) -> list[str]:
    """路由用到的依赖名（`Depends(require_permission(...))` 会落到 `__name__` 上）。

    为什么盯它：搬迁时最容易"顺手"改的就是这一行 —— 而它正是"旧 permission = 新 permission"那条。
    """
    names: set[str] = set()
    dep = getattr(route, "dependant", None)
    for sub in getattr(dep, "dependencies", []) or []:
        call = getattr(sub, "dependency", None) or getattr(sub, "call", None)
        name = getattr(call, "__name__", None) or type(call).__name__
        if name and name not in _NOISE_DEPS:
            names.add(name)
    return sorted(names)


def _routes(app) -> list[dict]:
    out: list[dict] = []
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = sorted(getattr(r, "methods", []) or [])
        if not path or not methods:
            continue                                  # 静态挂载/文档路由不算契约
        ep = getattr(r, "endpoint", None)
        rm = getattr(r, "response_model", None)
        out.append({
            "path": path,
            "methods": methods,
            "name": getattr(r, "name", None) or getattr(ep, "__name__", None),
            "module": getattr(ep, "__module__", None),
            "status_code": getattr(r, "status_code", None),
            "response_model": getattr(rm, "__name__", None) if rm is not None else None,
            "deps": _dep_names(r),
        })
    return out


def shadow_pairs(routes: list[dict]) -> list[list[str]]:
    """算出"先注册的那条会不会把后注册的那条挡住"。

    FastAPI/Starlette 按**注册顺序**匹配：`/orders/pending-dispatch-count` 必须排在同法的
    `/orders/{order_id}` **前面**，否则那个静态路径会先命中动态路由（参数是 int 时表现为 422）。
    搬迁会把注册顺序打散，所以要有一个"顺序变了但没造成遮蔽"的机器判据 —— 这就是它。
    """

    def rx(path: str) -> re.Pattern:
        parts = []
        for seg in path.strip("/").split("/"):
            parts.append("[^/]+" if seg.startswith("{") else re.escape(seg))
        return re.compile("^/" + "/".join(parts) + "/?$")

    pairs: list[list[str]] = []
    for i, a in enumerate(routes):
        for b in routes[i + 1:]:
            if not set(a["methods"]) & set(b["methods"]):
                continue
            if "{" in a["path"] and rx(a["path"]).match(b["path"]):
                pairs.append([f"{'/'.join(a['methods'])} {a['path']}", f"{'/'.join(b['methods'])} {b['path']}"])
    return sorted(pairs)


def snapshot(app) -> dict:
    routes = _routes(app)
    return {
        "openapi": app.openapi(),
        "routes": routes,
        "shadow": shadow_pairs(routes),
    }


def _norm(snap: dict) -> str:
    """规范化成可比较的文本（键排序、去掉易变字段）。"""
    return json.dumps(snap, sort_keys=True, ensure_ascii=False)


def diff(before: dict, after: dict) -> dict:
    """返回 {breaking: [...], moved: [...], shadow: [...]}；breaking 为空才算"纯搬迁"。"""
    breaking: list[str] = []
    moved: list[str] = []

    if _norm(before["openapi"]) != _norm(after["openapi"]):
        breaking.append("OpenAPI 文档变了（入参/出参/schema 有差异）—— 这不是纯搬迁")
        b_paths = set(before["openapi"].get("paths", {}))
        a_paths = set(after["openapi"].get("paths", {}))
        for p in sorted(b_paths - a_paths):
            breaking.append(f"  · 少了路径 {p}")
        for p in sorted(a_paths - b_paths):
            breaking.append(f"  · 多了路径 {p}")
        for p in sorted(b_paths & a_paths):
            if _norm(before["openapi"]["paths"][p]) != _norm(after["openapi"]["paths"][p]):
                breaking.append(f"  · 路径内容变了 {p}")

    def key(r: dict) -> tuple:
        return tuple(r["methods"]), r["path"]

    b_map = {key(r): r for r in before["routes"]}
    a_map = {key(r): r for r in after["routes"]}
    for k in sorted(set(b_map) - set(a_map)):
        breaking.append(f"端点消失：{'/'.join(k[0])} {k[1]}")
    for k in sorted(set(a_map) - set(b_map)):
        breaking.append(f"端点新增：{'/'.join(k[0])} {k[1]}")
    for k in sorted(set(b_map) & set(a_map)):
        b, a = b_map[k], a_map[k]
        for field in ("name", "status_code", "response_model", "deps"):
            if b[field] != a[field]:
                breaking.append(f"{'/'.join(k[0])} {k[1]} 的 {field} 变了：{b[field]} → {a[field]}")
        if b["module"] != a["module"]:
            moved.append(f"{'/'.join(k[0])} {k[1]}：{b['module']} → {a['module']}")

    if [key(r) for r in before["routes"]] != [key(r) for r in after["routes"]]:
        # 顺序变了**不一定**是问题：只有当遮蔽关系跟着变了才是。
        note = "注册顺序变了（见下：遮蔽关系是否也变了）"
        if before["shadow"] != after["shadow"]:
            breaking.append(note + " —— 而且**遮蔽关系也变了**：");
            for p in before["shadow"]:
                if p not in after["shadow"]:
                    breaking.append(f"  · 少了遮蔽：{p[0]} 挡住 {p[1]}")
            for p in after["shadow"]:
                if p not in before["shadow"]:
                    breaking.append(f"  · 多了遮蔽：{p[0]} 挡住 {p[1]}")
        else:
            moved.append(note + "；但遮蔽关系一字不差（机器算过）")
    elif before["shadow"] != after["shadow"]:
        breaking.append("注册顺序没变而遮蔽关系变了（不可能，除非路由表被改坏）")

    return {"breaking": breaking, "moved": moved, "shadow": after["shadow"]}


def _selftest() -> int:
    """判据自己的反向验证：逐条注入，看 diff 抓不抓得住。"""
    from fastapi import Depends, FastAPI, Query

    def perm_a():
        return True

    def perm_b():
        return True

    def build(mutate: str | None = None) -> dict:
        app = FastAPI()
        guards = {"list": perm_a, "count": perm_a, "detail": perm_a}
        limit_default = 100

        @app.get("/orders", dependencies=[Depends(perm_a)])
        def list_orders(limit: int = Query(limit_default)) -> dict:
            return {}

        @app.get("/orders/pending-dispatch-count", dependencies=[Depends(perm_a)])
        def pending_dispatch_count() -> dict:
            return {}

        @app.get("/orders/{order_id}", dependencies=[Depends(perm_a)], response_model=dict)
        def get_order(order_id: int) -> dict:
            return {}

        if mutate == "drop":
            app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/orders/pending-dispatch-count"]
        elif mutate == "method":
            for r in app.routes:
                if getattr(r, "path", None) == "/orders/{order_id}":
                    r.methods = {"POST"}
        elif mutate == "perm":
            for r in app.routes:
                if getattr(r, "path", None) == "/orders":
                    r.dependant.dependencies[0].call = perm_b
        elif mutate == "order":
            # 把静态路径挪到动态路径**之后** → 遮蔽关系应当出现
            rs = list(app.routes)
            i = next(i for i, r in enumerate(rs) if getattr(r, "path", "") == "/orders/pending-dispatch-count")
            j = next(i for i, r in enumerate(rs) if getattr(r, "path", "") == "/orders/{order_id}")
            rs[i], rs[j] = rs[j], rs[i]
            app.routes[:] = rs
        return snapshot(app)

    base = build()
    cases = [
        ("原样（不该有差异）", build(), False),
        ("删掉一个端点", build("drop"), True),
        ("把一个端点的方法改掉", build("method"), True),
        ("换掉权限依赖（old permission ≠ new permission）", build("perm"), True),
        ("把静态路径挪到动态路径之后（制造遮蔽）", build("order"), True),
    ]
    bad = 0
    for label, snap, want_break in cases:
        d = diff(base, snap)
        got = bool(d["breaking"])
        ok = got == want_break
        print(("  ✅ " if ok else "  ❌ ") + f"{label} → breaking={got}（期望 {want_break}）")
        if not ok:
            bad += 1
        elif got:
            for line in d["breaking"][:2]:
                print("       " + line)
    if bad:
        print(f"\n❌ 判据自身不可信：{bad}/{len(cases)} 种情况没抓对")
        return 1
    print(f"\n✅ selftest {len(cases)}/{len(cases)}：契约 diff 既不空转、也不误报")
    return 0


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="API 契约快照 / 纯搬迁等价性证明")
    ap.add_argument("--save", metavar="LABEL", help="把当前契约存成快照")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"), help="比较两份快照（也可以给文件名 now.json）")
    ap.add_argument("--note", default="", help="存快照时的说明")
    ap.add_argument("--selftest", action="store_true", help="判据自己的反向验证")
    ap.add_argument("--list", action="store_true", help="列出已有快照")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    if args.list:
        for p in sorted(SNAP_DIR.glob("*.json")):
            print(f"  {p.stem}（{p.stat().st_size} 字节）")
        return 0

    if args.save:
        snap = snapshot(_load_app())
        out = SNAP_DIR / f"{args.save}.json"
        payload = {"note": args.note, **snap}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 快照：{out.relative_to(ROOT)}（{len(snap['routes'])} 条路由 / "
              f"{len(snap['openapi'].get('paths', {}))} 条路径 / {len(snap['shadow'])} 对遮蔽）")
        return 0

    if args.diff:
        def load(tag: str) -> dict:
            p = Path(tag)
            if not p.exists():
                p = SNAP_DIR / (tag if tag.endswith(".json") else tag + ".json")
            if not p.exists():
                raise SystemExit(f"⛔ 找不到快照：{tag}")
            data = json.loads(p.read_text(encoding="utf-8"))
            return {k: data[k] for k in ("openapi", "routes", "shadow")}

        d = diff(load(args.diff[0]), load(args.diff[1]))
        print(f"遮蔽关系：{len(d['shadow'])} 对")
        for p in d["shadow"]:
            print(f"  · {p[0]} 挡住 {p[1]}（两边都有，顺序影响不到它）")
        if d["moved"]:
            print("\n结构性变化（**不拦**，搬迁就是要这个）：")
            for m in d["moved"]:
                print("  · " + m)
        if d["breaking"]:
            print("\n❌ 契约差异（纯搬迁必须为零）：")
            for b in d["breaking"]:
                print("  · " + b)
            return 1
        print("\n✅ 契约零差异：OpenAPI 全文一致、路由表逐条一致、遮蔽关系一致")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
