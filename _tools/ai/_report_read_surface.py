import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
"""自审：47 个只读端点里，哪些无法用 (module, action, params) 表达（G5 的可行性边界）。

⚠️ **这是报告，不是检查**（2026-09-21 从 `_check_*` 改名）：一次性回答"这条路走不走得通"，
永远退出 0；放必跑清单里是一格虚绿。读侧的硬判据在 `_read_coverage.py --check`。
⛔ 不要把它改回 `_check_*`：除非给它加一条真会红的判据。

分类：
  simple   纯 query 参数 -> 可直接转发
  path     只有路径参数（如 /{order_id}）-> 可转发（id 当 params）
  export   返回文件流/触发文件生成 -> 需要单独的工具（G4）
  special  返回体复杂或非幂等（有副作用）-> 需要单独判断
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = repo_root()
TM = ROOT / "docs" / "ai" / "ai_toolmap.json"

EXPORT_HINT = ("export",)
SPECIAL = {
    # 有副作用或返回文件/任务的只读端点（名字看着像 GET，但不是"纯查询"）
    ("ledger", "get_export_job"): "异步任务查询",
    ("reports", "export_report"): "导出文件",
}


def classify(mod: str, a: dict) -> str:
    key = (mod, a["action"])
    if key in SPECIAL:
        return "special"
    if any(h in a["action"].lower() for h in EXPORT_HINT):
        return "export"
    if "{" in a["path"]:
        return "path"
    return "simple"


def main() -> int:
    d = json.loads(TM.read_text(encoding="utf-8"))
    buckets: dict[str, list[str]] = {}
    for mod, v in d["modules"].items():
        for a in v["actions"]:
            if a["risk"] != "read":
                continue
            k = classify(mod, a)
            buckets.setdefault(k, []).append(f"{mod}.{a['action']}  ({a['method'].upper()} {a['path']})")

    total = sum(len(v) for v in buckets.values())
    print(f"只读端点 {total} 个，按 G5 可表达性分类：")
    for k in ("simple", "path", "export", "special"):
        items = buckets.get(k, [])
        print(f"\n[{k}] {len(items)} 个")
        for it in items:
            print(f"   {it}")

    simple = len(buckets.get("simple", [])) + len(buckets.get("path", []))
    print(f"\n结论：{simple}/{total} 可用 (module, action, params) 直接转发；"
          f"{total - simple} 个需要特殊处理（导出类 + 异步任务类）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
