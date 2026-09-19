"""列出「AI 能读的每张表，谁能读」——排查权限类问题时先跑这个。

用法：
    python _tools/ai/_show_read_roles.py            # 全量
    python _tools/ai/_show_read_roles.py shipper    # 只看某个角色能读的

为什么要有它：读目录是按角色裁剪的，而"某张表货主到底能不能读"这个问题
在 Android 侧要跑起来才知道。这里直接摊开生成物（`docs/ai/ai_read_catalog.json`），
一眼能看出某条能力是**没生成**还是**生成了但被角色挡掉**。
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

CAT = repo_root() / "docs/ai/ai_read_catalog.json"


def main() -> int:
    want = sys.argv[1] if len(sys.argv) > 1 else None
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    actions = cat["actions"]
    if want:
        actions = [a for a in actions if want in a["roles"]]
    for a in sorted(actions, key=lambda x: (x["module"], x["action"])):
        name = f"{a['module']}.{a['action']}"
        roles = ",".join(a["roles"]) or "（谁也不给）"
        print(f"{name:45s} {roles:28s} | {a['auth']}")
    if not want:
        print()
        for roles, n in Counter(tuple(a["roles"]) for a in cat["actions"]).most_common():
            print(f"{n:3d} 张 | {','.join(roles) or '（谁也不给）'}")
    print(f"\n共 {len(actions)} 张表" + (f"（角色含 {want}）" if want else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
