"""看一眼生成好的目录里有哪些动作、哪些参数、哪些枚举取值（调试用，不参与校验）。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

cat = json.loads((repo_root() / "docs/ai/ai_read_catalog.json").read_text(encoding="utf-8"))
print(f"共 {cat['counts']['listed']} 个动作\n")
for a in cat["actions"]:
    ps = ", ".join(
        ("*" if p["is_id"] else "") + p["name"] + (":" + p["type"] if p["type"] else "")
        for p in a["params"]
    )
    print(f"{a['module']}.{a['action']:<36} {a['path']:<42} {ps}")
print("\n带 * 的是编号类参数（AI 不许看到编号 → 由工具按名字解析）")

print("\n枚举类参数（模型可选的值）：")
for a in cat["actions"]:
    for p in a["params"]:
        if p["enum"]:
            print(f"  {a['action']:<38} {p['name']:<18} {'/'.join(p['enum'])[:80]}")

print("\n被跳过的参数（不在白名单类型里的）：")
any_skipped = False
for a in cat["actions"]:
    if a["skipped_params"]:
        any_skipped = True
        print(f"  {a['action']:<38} {a['skipped_params']}")
if not any_skipped:
    print("  （无）")
