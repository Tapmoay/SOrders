"""AI 真机 E2E 的「现场快照」：把 AI 会改到的几张表**原样打出来**。

### 为什么需要它
真机 E2E 是"发一句话 → 点确认 → 库里看结果"，中间隔着三层（模型、App、后端）。
断言只能落在**库里的最终值**上，所以每次跑之前/之后都要能一眼看到那几张表现在长什么样。
凭记忆判断"应该没变"是本项目已经栽过的坑（撤单时把范围记错，查了半小时）。

用法：
    python _tools/ai/_ai_e2e_state.py            # 打快照
    python _tools/ai/_ai_e2e_state.py --save b.json   # 存成 JSON（跑完再比一次）
    python _tools/ai/_ai_e2e_state.py --diff b.json   # 与快照比，只列差异
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

DB = repo_root() / "backend" / "sorders.db"


def snap() -> dict:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cats = [
            {"id": r[0], "name": r[1], "sort": r[2]}
            for r in con.execute("select id,name,sort_order from product_categories order by sort_order,id")
        ]
        scopes = dict(con.execute("select product_scope, count(*) from users group by product_scope"))
        vis = [
            {"user": r[0], "product": r[1]}
            for r in con.execute("select user_id, product_id from user_product_visibility order by user_id, product_id")
        ]
        veh = [
            {"id": r[0], "plate": r[1], "type": r[2], "driver_id": r[3], "active": r[4]}
            for r in con.execute("select id,plate_no,vehicle_type,driver_id,is_active from vehicles order by id")
        ]
        drv = [
            {"id": r[0], "name": r[1], "phone": r[2], "vt": r[3], "rule": r[4], "salary": r[5], "active": r[6]}
            # ⚠️ `users.role` 在库里存的是**枚举名**（`DRIVER`），不是小写字符串。
            # 写 `role='driver'` 会安静地返回 0 行——快照于是"看起来没有司机"，
            # 而真相是查询写错了（第一次跑就踩到）。所以按大小写不敏感匹配。
            for r in con.execute(
                "select id,full_name,phone,vehicle_type,driver_rule_id,salary,is_active"
                " from users where upper(role) like '%DRIVER%' order by id"
            )
        ]
        prod = dict(con.execute("select category, count(*) from products group by category"))
    finally:
        con.close()
    return {"categories": cats, "scopes": scopes, "visibility": vis, "vehicles": veh,
            "drivers": drv, "products_by_category": prod}


def show(s: dict) -> None:
    print("== product_categories（商品分类名册，顺序=界面左栏顺序）")
    for c in s["categories"]:
        print(f"   #{c['id']:<4} {c['name']:<12} sort={c['sort']}")
    print(f"== users.product_scope {s['scopes']}")
    print(f"== user_product_visibility {len(s['visibility'])} 行")
    for v in s["visibility"]:
        print(f"   user={v['user']} product={v['product']}")
    print("== vehicles（车辆台账）")
    for v in s["vehicles"]:
        print(f"   #{v['id']:<4} {v['plate']:<12} {v['type']:<8} driver_id={v['driver_id']} active={v['active']}")
    print(f"== drivers（{len(s['drivers'])} 人，只打前 12 个）")
    for d in s["drivers"][:12]:
        print(f"   #{d['id']:<4} {str(d['name']):<10} {d['phone']:<14} vt={str(d['vt']):<8}"
              f" rule={d['rule']} salary={d['salary']} active={d['active']}")
    print(f"== products.category 分布 {s['products_by_category']}")


def diff(a: dict, b: dict) -> int:
    n = 0
    for k in a:
        if a[k] != b[k]:
            n += 1
            print(f"-- 变了：{k}")
            print(f"   之前: {json.dumps(a[k], ensure_ascii=False)[:600]}")
            print(f"   现在: {json.dumps(b[k], ensure_ascii=False)[:600]}")
    print("✅ 与快照完全一致" if n == 0 else f"⚠️ {n} 处不同")
    return 0 if n == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", help="存快照到该 JSON")
    ap.add_argument("--diff", help="与该 JSON 比差异")
    a = ap.parse_args()
    s = snap()
    if a.save:
        Path(a.save).write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已存快照 -> {a.save}")
        return 0
    if a.diff:
        return diff(json.loads(Path(a.diff).read_text(encoding="utf-8")), s)
    show(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
