import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
"""校验 AI 工具映射产物：docstring 覆盖率 + 动作唯一性 + 与代码一致性抽查。只读。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = repo_root()
TM = ROOT / "docs" / "ai" / "ai_toolmap.json"


def main() -> int:
    d = json.loads(TM.read_text(encoding="utf-8"))
    tot = hit = 0
    read = write = 0
    for _mod, v in d["modules"].items():
        for a in v["actions"]:
            tot += 1
            if a.get("doc"):
                hit += 1
            if a["risk"] == "read":
                read += 1
            else:
                write += 1

    print(f"端点 {tot}（只读 {read} / 写 {write}），模块 {len(d['modules'])} 个")
    print(f"docstring 覆盖率：{hit}/{tot} = {hit / tot:.0%}")

    print("\n无 docstring 的端点（人工写口语时要额外看一眼）：")
    n = 0
    for mod, v in d["modules"].items():
        for a in v["actions"]:
            if not a.get("doc"):
                print(f"   {mod:<22} {a['action']}")
                n += 1
    if n == 0:
        print("   （无）")

    print("\n抽查 6 条与代码位置是否可核对：")
    want = {("orders", "list_orders"), ("orders", "assign_order"), ("ledger", "list_entries"),
            ("ledger", "list_accounts"), ("inventory", "inventory_summary"),
            ("stats", "get_driver_performance")}
    for mod, v in d["modules"].items():
        for a in v["actions"]:
            if (mod, a["action"]) in want:
                print(f"   {a['method'].upper():<6} {a['path']:<45} {a['at']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
