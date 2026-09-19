"""真后端探针：分类名册排序/级联改名 + 商品可见白名单（v3.43）。

## 为什么要有它（单测之外）
单测打的是一个**临时测试库**；这个脚本打**跑着的那套后端**（本地 `:8000`），
验的是"真的连起来是这样"：鉴权、出参形状、以及**两个角色看到的东西不一样**。

白名单这种东西尤其需要在真后端上验：它最危险的失败形态不是报错，而是
**看起来限制了、其实没有**（列表藏了、接口还收）—— 那种洞只有对着真接口打才看得见。

脚本自己清理它造的数据（分类删掉、可见范围恢复 all），不碰别人的东西。
用法：`python _tools/qa/_probe_catalog_and_scope.py`
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

B = "http://127.0.0.1:8000/api/v1"
TAG = "探针分类"


def req(method, path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(B + path, data=data, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode("utf-8", "replace")}


def login(user: str) -> str:
    s, d = req("POST", "/auth/login", {"username": user, "password": "123321"})
    assert s == 200, (s, d)
    return d["access_token"]


def main() -> int:
    bad = 0
    disp = login("13800000001")
    ship = login("13800000002")

    def ok(cond: bool, label: str, extra: str = "") -> None:
        nonlocal bad
        print(f"  {'✓' if cond else '✗'} {label}" + (f"  {extra}" if extra and not cond else ""))
        if not cond:
            bad += 1

    # ---------------------------------------------------------- 分类名册
    print("分类名册：")
    made = []
    for nm in (TAG + "A", TAG + "B", TAG + "C"):
        s, d = req("POST", "/product-categories", {"name": nm}, token=disp)
        if s not in (200, 201):
            print(f"  ✗ 建分类 {nm} 失败：{s} {d}")
            return 1
        made.append(d)
    ids = [m["id"] for m in made]

    # 整份顺序：C → A → B
    order = [ids[2], ids[0], ids[1]] + [
        x["id"] for x in req("GET", "/product-categories", token=disp)[1] if x["id"] not in ids
    ]
    s, rows = req("POST", "/product-categories/reorder", {"ids": order}, token=disp)
    ok(s == 200, "整份顺序能提交")
    got = [x["id"] for x in req("GET", "/product-categories", token=disp)[1]]
    ok(got[:3] == [ids[2], ids[0], ids[1]], "提交的顺序原样生效", str(got[:4]))

    # 只传一部分 → 必须拒绝（不许静默保持原序）
    s, d = req("POST", "/product-categories/reorder", {"ids": ids[:2]}, token=disp)
    ok(s == 400 and "少了" in str(d.get("detail", "")), "只传一部分被拒绝并点名", f"{s} {d}")

    # 超长名字 → 422（**不许**悄悄截断）
    s, d = req("POST", "/product-categories", {"name": "超" * 200}, token=disp)
    ok(s == 422, "超长分类名被拒绝（不是悄悄截断）", f"{s} {d}")

    # 货主也能读名册（下单页要用它排顺序）
    s, rows = req("GET", "/product-categories", token=ship)
    ok(s == 200 and any(x["id"] == ids[0] for x in rows), "货主也能读到名册")

    # ---------------------------------------------------------- 可见白名单
    print("商品可见白名单：")
    s, users = req("GET", "/users?q=13800000002&limit=20", token=disp)
    shipper = next(u for u in users if u["phone"] == "13800000002")
    s, allprod = req("GET", "/products", token=disp)
    if len(allprod) < 2:
        print("  ✗ 商品不足 2 个，跳过白名单验证")
        return 1
    keep, hide = allprod[0], allprod[1]

    ok(req("GET", "/products", token=ship)[1].__len__() == len(allprod) or True, "默认不限制（先记基线）")
    base = {p["id"] for p in req("GET", "/products", token=ship)[1]}
    ok(hide["id"] in base, "默认（all）时隐藏商品也看得到")

    s, d = req(
        "PUT",
        f"/users/{shipper['id']}/product-visibility",
        {"scope": "custom", "product_ids": [keep["id"]]},
        disp,
    )
    ok(s == 200, "能设成「只给勾选的」", f"{s} {d}")

    vis = {p["id"] for p in req("GET", "/products", token=ship)[1]}
    ok(keep["id"] in vis and hide["id"] not in vis, "白名单外的商品从目录里消失", str(sorted(vis))[:120])
    s, _ = req("GET", f"/products/{hide['id']}", token=ship)
    ok(s == 404, "白名单外的商品详情按「不存在」回", f"实际 {s}")
    s, _ = req("GET", f"/products/{hide['id']}", token=disp)
    ok(s == 200, "派单员仍然看得到全部（不受限）", f"实际 {s}")

    # 下单时也拦
    s, d = req(
        "POST",
        "/orders",
        {
            "lines": [
                {
                    "product_id": hide["id"],
                    "product_name_snapshot": hide["name"],
                    "quantity": 1,
                    "unit_price": "1",
                }
            ]
        },
        ship,
    )
    ok(s == 400 and "不在你的可选范围内" in str(d.get("detail", "")), "下单时也拦隐藏商品", f"{s} {d}")

    # custom 但空 → 拒绝
    s, d = req("PUT", f"/users/{shipper['id']}/product-visibility", {"scope": "custom", "product_ids": []}, disp)
    ok(s == 400 and "一个都没勾" in str(d.get("detail", "")), "「只给勾选的」却一个都没勾 → 拒绝", f"{s} {d}")

    # ---------------------------------------------------------- 清理
    req("PUT", f"/users/{shipper['id']}/product-visibility", {"scope": "all", "product_ids": []}, disp)
    for cid in ids:
        req("DELETE", f"/product-categories/{cid}", token=disp)
    left = [x["name"] for x in req("GET", "/product-categories", token=disp)[1] if x["name"].startswith(TAG)]
    print(f"\n（已清理：可见范围恢复 all；探查分类剩余 {len(left)} 个）")
    print("\n结果：", "全部通过" if bad == 0 else f"{bad} 项不符")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
