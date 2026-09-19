"""生成 AI 助手的「工具白名单」（module/action/risk/路径）。

⚠️ 权威性与边界（第三轮独立审查提出，已采纳）
  * **端点事实的唯一权威是 `docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md`**
    （由 `backend/scripts/gen_endpoint_index.py` 产出：AST 解析、提取 FastAPI alias、
     带授权列、带 `--check`）。**本脚本不是端点清单的替代品**，仅产出一份
     "AI 工具层加载用的白名单"这一单一用途的视图。
  * 本脚本已知局限（不要在它上面重建 08A 的能力）：
      - 不提取 Query 参数与 FastAPI `alias` → **不能**据此生成"参数白名单"
        （本仓库有 5 处 alias 陷阱，如 orders.py:166-170、reports.py:215）；
      - 不提取授权列（08A 有）；
      - 只扫 `app/api/v1/*.py`，**不含** main.py 的 3 个 app 级端点；
      - read/write 按 **HTTP 动词**判定，不是按"是否改变状态"——
        `POST /stats/export`、`POST /ledger/export-jobs` 实为只读，需另行标记。
  * 权威清单另有 UI 入口映射（大白话文档的"位置"列）待建，源在
    `android/.../ui/nav/{Modules,Routes,NavGraph}.kt`。

用法：
  python _gen_ai_toolmap.py --check          # 统计 + 动作唯一性校验
  python _gen_ai_toolmap.py --out-dir docs/ai
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

import argparse
import json
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
try:  # Windows 控制台默认 GBK，emoji/中文会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

ROOT = repo_root()
API_DIR = ROOT / "backend" / "app" / "api" / "v1"

# 模块 -> 中文名（人工维护，用于大白话文档；空的话会提示补）
MODULE_CN: dict[str, str] = {
    "orders": "订单/派单",
    "order_products": "订单商品行",
    "shipper": "地址与联系人",
    # 共享地点库（导航信息）：司机到场补录的坐标，全库共用（2026-09-18）
    "places": "共享地点库",
    "ledger": "账本",
    "products": "商品管理",
    # 商品分类名册：下单页左侧那一列的分组与顺序（2026-09-18 用户要求 AI 也要能建、能排）
    "product_categories": "商品分类",
    # 地点分类名册（2026-09-19）：地址库左侧那一列，**按人分区**（每个人管自己那一份）
    "place_categories": "地点分类",
    "price_rules": "批发商定价",
    "inventory": "库存管理",
    "users": "司机/货主/批发商/账号",
    "vehicles": "车辆管理",
    "customers": "客户",
    "freight_templates": "订单/运费模板",
    "driver_billing_rules": "司机计费规则",
    "arrears": "挂账单位",
    "driver_settlements": "司机结算单",
    "driver_bills": "司机账单",
    "freight_settlement": "司机运费结算",
    "expenses": "费用",
    "cash_flows": "现金流水",
    "stats": "统计口径",
    "reports": "报表中心",
    "notifications": "消息通知",
    "operation_logs": "操作日志",
    # 2026-09-18：自助注册端点已整体删除，这个模块现在只剩登录
    "auth": "登录",
    # 一直在报"缺中文名"的那个模块（AI 附件的表格解析）——补上，否则 --check 永远红，
    # 而"永远红的检查 = 没有检查"（本仓库栽过一次：红了 12 轮没人管）。
    "files": "AI 附件解析",
}

ROUTE_RE = re.compile(
    r'^@router\.(?P<method>get|post|put|patch|delete)\(',
)
DEF_RE = re.compile(r'^(?:async\s+)?def\s+(?P<name>\w+)\s*\(')
# 多行装饰器的续行：如 `@router.get(` 下一行才是 "…" 或 "…" 结尾
PATH_STR_RE = re.compile(r'^\s*(?:"(?P<p1>[^"]*)"|\'(?P<p2>[^\']*)\')')

READ_METHODS = {"get"}
# 纯读但动词是 POST 的端点（第三轮审查指出：按动词判会在首阶段边界上判错）
READ_SEMANTICS_EXTRA: set[tuple[str, str]] = {
    ("stats", "post_stats_export"),        # 出 xlsx，不改状态
    ("ledger", "create_export_job"),       # 建异步导出任务，不改业务状态
}


API_PREFIX = "/api/v1"  # main.py: include_router(api_router, prefix=settings.api_v1_prefix)
PREFIX_RE = re.compile(r'APIRouter\(\s*prefix\s*=\s*"([^"]*)"')


def _router_prefix(text: str) -> str:
    """取该模块 APIRouter 的 prefix（如 ledger.py -> /ledger）。"""
    m = PREFIX_RE.search(text)
    return m.group(1) if m else ""


def scan() -> list[dict]:
    """扫出所有端点。位置 = def 行号（与 08A 口径一致）。

    注意：装饰器可能是多行的（如 `@router.get(` 换行后才写路径），
    所以不能只匹配单行 —— 早期版本漏掉了全部多行装饰器，把 126 个端点全判成"写"。
    """
    out: list[dict] = []
    for f in sorted(API_DIR.glob("*.py")):
        mod = f.stem
        text = f.read_text(encoding="utf-8")
        prefix = _router_prefix(text)
        lines = text.splitlines()
        pending: dict | None = None
        for i, line in enumerate(lines, 1):
            m = ROUTE_RE.match(line)
            if m:
                # 路径可能在同行，也可能在后续行
                rest = line[m.end():]
                pm = re.match(r'[ \t]*"([^"]*)"', rest) or re.match(r"[ \t]*'([^']*)'", rest)
                pending = {
                    "method": m.group("method"),  # 统一小写，与 READ_METHODS 比对（曾因大小写不一致把 47 个 GET 全判成写）
                    "path": pm.group(1) if pm else None,
                    "line_route": i,
                }
                continue
            if pending is not None and pending["path"] is None:
                pm2 = PATH_STR_RE.match(line)
                if pm2:
                    pending["path"] = pm2.group("p1") if pm2.group("p1") is not None else pm2.group("p2")
                    continue
            d = DEF_RE.match(line)
            if d and pending:
                pending["handler"] = d.group("name")
                pending["line"] = i
                pending["module"] = mod
                pending["path"] = pending["path"] or ""
                pending["full_path"] = f'{API_PREFIX}{prefix}{pending["path"]}'
                pending["doc"] = _docstring_after(lines, i)
                out.append(pending)
                pending = None
    return out


def _docstring_after(lines: list[str], def_line: int) -> str:
    """取 def 之后第一个 docstring 的首行（给大白话文档当"这个动作是干什么的"）。

    意义：骨架若只有 `list_entries` 这种函数名，人工要先把 127 个函数名读懂才能改口语；
    带上 docstring 摘要后，人工只需把已有的中文说明改得更口语 —— 省掉一整轮理解成本。
    """
    for line in lines[def_line:def_line + 12]:  # def_line 是 0-based 的下一行
        s = line.strip()
        if not s:
            continue
        if s.startswith(('"""', "'''")):
            body = s.strip('"\'').strip()
            return body[:120]
        if s.startswith((")", "->")) or s.endswith(":") or s == "":
            continue
        if "\"\"\"" in s or "'''" in s:  # docstring 与签名同行
            return s.split('"""')[-1].split("'''")[-1].strip()[:120]
        # 仍是函数签名的一部分（多行形参），继续往下找
    return ""


def action_of(handler: str) -> str:
    """动作名 = 后端函数名（去掉动词前缀的过度归约）。

    教训：早期版本把 list_entries/list_receipts/list_accounts 都归约成 `list`，
    结果同一模块出现 4 个同名动作 —— AI 无法区分，工具层直接不可用。
    保留全名后，动作名与后端函数名一一对应，开发者能一眼对上，也不会撞。
    """
    return handler


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out-dir", type=str, default=None)
    a = ap.parse_args()

    eps = scan()

    # 动作名与 risk 标注
    for e in eps:
        e["action"] = action_of(e["handler"])
        # risk 按"是否改变状态"判，不单看动词（见文件头局限说明）
        pure_read = e["method"] in READ_METHODS or (e["module"], e["handler"]) in READ_SEMANTICS_EXTRA
        e["risk"] = "read" if pure_read else "write"

    reads = [e for e in eps if e["risk"] == "read"]
    writes = [e for e in eps if e["risk"] == "write"]

    by_mod: dict[str, list[dict]] = {}
    for e in eps:
        by_mod.setdefault(e["module"], []).append(e)

    dupes: list[str] = []
    for mod, items in by_mod.items():
        seen: dict[str, int] = {}
        for it in items:
            k = f'{it["action"]}:{it["risk"]}'
            seen[k] = seen.get(k, 0) + 1
        for k, n in seen.items():
            if n > 1:
                dupes.append(f"{mod} 的 {k} 出现 {n} 次（AI 无法区分动作）")

    # (method, path) 唯一性 —— 抓"同方法同路径重复注册"（FastAPI 先注册者胜，后者永不生效）
    route_seen: dict[tuple[str, str], list[str]] = {}
    for e in eps:
        route_seen.setdefault((e["method"], e["full_path"]), []).append(
            f'{e["handler"]} @ {e["module"]}.py:{e["line"]}'
        )
    shadowed = {k: v for k, v in route_seen.items() if len(v) > 1}
    # 唯一路径数（同路径多方法算 1 条）
    uniq_paths = len({e["full_path"] for e in eps})

    print(f"端点总数 {len(eps)}（只读 {len(reads)} / 写 {len(writes)}），模块 {len(by_mod)} 个")
    print(f"唯一路径 {uniq_paths} 条，唯一 (方法,路径) {len(route_seen)} 条")
    print("  ⚠️ 注意：本脚本只扫 app/api/v1/*.py，**不含** main.py 的 3 个 app 级端点；")
    print("     端点事实以 docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md 为准。")
    print(f"{'模块':<22}{'中文名':<20}{'只读':<6}{'写':<6}")
    for mod in sorted(by_mod):
        r = sum(1 for x in by_mod[mod] if x["risk"] == "read")
        w = len(by_mod[mod]) - r
        cn = MODULE_CN.get(mod, "**缺中文名**")
        print(f"{mod:<22}{cn:<20}{r:<6}{w:<6}")

    missing_cn = [m for m in by_mod if m not in MODULE_CN]
    if missing_cn:
        print(f"\n⚠️ 缺中文名的模块：{missing_cn}")
    if dupes:
        print("\n⚠️ 动作名冲突：")
        for d in dupes:
            print("   " + d)
    else:
        print("\n✅ 动作名无冲突（每个 module+risk 内动作唯一）")

    if shadowed:
        print("\n⚠️ 同方法同路径重复注册（FastAPI 先注册者胜，后者永不生效）：")
        for (mth, p), who in shadowed.items():
            print(f"   {mth} {p}")
            for w in who:
                print(f"      - {w}")
    else:
        print("✅ 无重复路由")

    exit_code = 0
    if a.check and (dupes or missing_cn):
        exit_code = 1
        print("\n--check 失败（存在冲突或缺中文名）")

    if a.out_dir:
        out = ROOT / a.out_dir
        out.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_by": "_gen_ai_toolmap.py",
            "authority_note": (
                "端点事实以 docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md 为准"
                "（gen_endpoint_index.py：AST + alias + 授权列）。"
                "本文件仅作 AI 工具白名单使用，不含 Query 参数与 alias，"
                "**不可**据此生成参数白名单；只扫 api/v1/*.py，不含 main.py 的 3 个 app 级端点。"
            ),
            "counts": {
                "endpoints": len(eps),
                "read": len(reads),
                "write": len(writes),
                "unique_paths": uniq_paths,
                "unique_method_path": len(route_seen),
                "shadowed_routes": [f"{m} {p}" for (m, p) in shadowed],
            },
            "modules": {
                mod: {
                    "cn": MODULE_CN.get(mod, mod),
                    "actions": [
                        {
                            "action": x["action"],
                            "risk": x["risk"],
                            "method": x["method"],
                            "path": x["full_path"],
                            "handler": x["handler"],
                            "doc": x.get("doc", ""),
                            "at": f'backend/app/api/v1/{x["module"]}.py:{x["line"]}',
                        }
                        for x in sorted(by_mod[mod], key=lambda y: (y["risk"] != "read", y["action"]))
                    ],
                }
                for mod in sorted(by_mod)
            },
        }
        (out / "ai_toolmap.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        md = ["# 工具白名单骨架（自动生成）", "",
              "> ⚠️ **这不是「大白话文档」，也不能直接给用户看。**",
              "> 零基础用户需要的是「**UI 入口路径**」列（工作台 → 账本管理 → 手工记账），",
              "> 而本文件生成自后端代码，**拿不到 UI 入口**——后端没有中文功能名",
              "> （handler docstring 覆盖 24%、`summary=` 0 个、`APIRouter(tags=)` 全是英文 slug）。",
              "> 正确做法：从 `android/.../ui/nav/{Modules,Routes,NavGraph}.kt` 生成入口映射，与本表对齐。",
              ">",
              "> 端点事实以 `docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` 为准。", ""]
        for mod in sorted(by_mod):
            cn = MODULE_CN.get(mod, mod)
            md.append(f"## {cn}（`{mod}`）")
            md.append("")
            md.append("| 动作 | 读/写 | 接口 | 它做什么（代码里的说明） | 用户可能这么说（← 人工填写） |")
            md.append("|---|---|---|---|---|")
            for x in by_mod[mod]:
                doc = (x.get("doc") or "").replace("|", "/")
                md.append(f'| `{x["action"]}` | {"只读" if x["risk"] == "read" else "写"} | '
                          f'`{x["method"].upper()} {x["full_path"]}` | {doc} |  |')
            md.append("")
        (out / "kb_skeleton.md").write_text("\n".join(md), encoding="utf-8")
        print(f"\n已写出：{out / 'ai_toolmap.json'}、{out / 'kb_skeleton.md'}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
