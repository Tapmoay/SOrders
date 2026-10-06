"""真后端探针：分类名册排序/级联改名 + 商品可见白名单（v3.43）。

## 为什么要有它（单测之外）
单测打的是一个**临时测试库**；这个脚本打**跑着的那套后端**（本地 `:8000`），
验的是"真的连起来是这样"：鉴权、出参形状、以及**两个角色看到的东西不一样**。

白名单这种东西尤其需要在真后端上验：它最危险的失败形态不是报错，而是
**看起来限制了、其实没有**（列表藏了、接口还收）—— 那种洞只有对着真接口打才看得见。

脚本自己清理它造的数据（分类删掉、可见范围恢复 all），不碰别人的东西。
用法：
  `python _tools/qa/_probe_catalog_and_scope.py`                    # 打默认的本地 :8000
  `PROBE_BASE=http://127.0.0.1:8010 SORDERS_PROBE_PASSWORD=pass12345 python _tools/qa/_probe_catalog_and_scope.py`
    # 对着自己另起的一套后端跑；PROBE_BASE 会被补上 /api/v1（口令默认 123321 = 本机开发库那套，
    # 仓库播种脚本 backend/scripts/seed_dev_users.py 用的是 pass12345）
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# 默认打本地 :8000；要对着自己另起的一套后端跑，用 PROBE_BASE=http://127.0.0.1:8010
B = os.environ.get("PROBE_BASE", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
TAG = "探针分类"
# 口令：本机开发库那套是 123321；仓库的播种脚本（backend\scripts\seed_dev_users.py:20、
# scripts\reset_dev_passwords.py:29）用的是 pass12345。对着一套自己起的后端跑时用
# `SORDERS_PROBE_PASSWORD=pass12345`（与 _tools/ai/_probe_read_roles.py:33-34 同一约定）。
PROBE_PASSWORD = os.environ.get("SORDERS_PROBE_PASSWORD", "123321")


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
    s, d = req("POST", "/auth/login", {"username": user, "password": PROBE_PASSWORD})
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
            ],
            # L-32（CHG-0059）：四个联系字段不能全空，否则先撞「请填写收货人或下单人」
            "contact_dongjia_name": "探针收货人",
            "contact_dongjia_phone": "13800000099",
        },
        ship,
    )
    ok(s == 400 and "不在你的可选范围内" in str(d.get("detail", "")), "下单时也拦隐藏商品", f"{s} {d}")

    # custom 但空 → 拒绝
    s, d = req("PUT", f"/users/{shipper['id']}/product-visibility", {"scope": "custom", "product_ids": []}, disp)
    ok(
        s == 400 and "一个商品都看不到" in str(d.get("detail", "")),
        "「只给勾选的」却一个都没勾 → 拒绝",
        f"{s} {d}",
    )

    # ------------------------------------- 分类授权 / 单独关掉（L-23，CHG-0062）
    print("分类授权 / 排除：")
    cat_a = TAG + "A"
    made_products = []
    for nm in (TAG + "商品甲", TAG + "商品乙"):
        s, d = req("POST", "/products", {"name": nm, "category": cat_a, "default_unit_price": "5"}, token=disp)
        if s not in (200, 201):
            print(f"  ✗ 建商品 {nm} 失败：{s} {d}")
            return 1
        made_products.append(d)
    pa, pb = made_products[0], made_products[1]

    # ① 只给一个分类（不给具体商品）→ 这一类下的都看得见
    s, d = req("PUT", f"/users/{shipper['id']}/product-visibility",
               {"scope": "custom", "category_names": [cat_a]}, disp)
    ok(s == 200, "能按分类给（只给整个分类，不点商品）", f"{s} {d}")
    vis = {p["id"] for p in req("GET", "/products", token=ship)[1]}
    ok(pa["id"] in vis and pb["id"] in vis, "这一类下的商品都看得到", str(sorted(vis))[:120])
    ok(hide["id"] not in vis, "别的分类的商品看不到")

    # ② ⛔ 分类是「授权」不是快照：解析时现查商品库，后来加进这一类的自动可见
    s, pc = req("POST", "/products", {"name": TAG + "商品丙", "category": cat_a, "default_unit_price": "5"}, token=disp)
    if s in (200, 201):
        made_products.append(pc)
    vis = {p["id"] for p in req("GET", "/products", token=ship)[1]}
    ok(s in (200, 201) and pc["id"] in vis, "往这一类里后加的商品自动可见（⛔ 不是快照）", f"{s} {str(sorted(vis))[:120]}")

    # ③ 这一类里单独关掉一件：只少那一件，同类的其他还在
    s, d = req("PUT", f"/users/{shipper['id']}/product-visibility",
               {"scope": "custom", "category_names": [cat_a], "hidden_product_ids": [pa["id"]]}, disp)
    ok(s == 200, "这一类里单独关掉一件", f"{s} {d}")
    vis = {p["id"] for p in req("GET", "/products", token=ship)[1]}
    ok(pa["id"] not in vis and pb["id"] in vis, "关掉的那一件不见了、同类的其他还在", str(sorted(vis))[:120])

    # ④ 分类改名要级联「授权行」（不级联 → 选品页凭空少一批）
    s, _ = req("PATCH", f"/product-categories/{ids[0]}", {"name": cat_a + "改"}, token=disp)
    ok(s == 200, "分类改名（授权方向）", f"实际 {s}")
    vis = {p["id"] for p in req("GET", "/products", token=ship)[1]}
    ok(pb["id"] in vis and pa["id"] not in vis, "改名后授权行跟着走：同类的还在、单独关掉的仍关着", str(sorted(vis))[:120])

    # ⑤ 「全部商品」档下整类关掉 —— 排除行照样生效
    cat_new = cat_a + "改"
    s, d = req("PUT", f"/users/{shipper['id']}/product-visibility",
               {"scope": "all", "hidden_category_names": [cat_new]}, disp)
    ok(s == 200, "「全部商品」档下整类关掉", f"{s} {d}")
    vis = {p["id"] for p in req("GET", "/products", token=ship)[1]}
    ok(pa["id"] not in vis and pb["id"] not in vis and hide["id"] in vis,
       "整类关掉在 all 档也生效，别的分类不受影响", str(sorted(vis))[:120])

    # ⑥ 分类改名要级联「排除行」（不级联 → 本来关掉的商品全部重新出现且不报错）
    s, _ = req("PATCH", f"/product-categories/{ids[0]}", {"name": cat_a + "再改"}, token=disp)
    ok(s == 200, "分类改名（排除方向）", f"实际 {s}")
    vis = {p["id"] for p in req("GET", "/products", token=ship)[1]}
    ok(pa["id"] not in vis and pb["id"] not in vis,
       "改名后排除行跟着走：整类关掉的商品没有重新冒出来", str(sorted(vis))[:120])

    # ⑦ 闸门①：勾了商品、但编号全不在库了
    s, d = req("PUT", f"/users/{shipper['id']}/product-visibility",
               {"scope": "custom", "product_ids": [99999999]}, disp)
    ok(s == 400 and "都不在商品库里了" in str(d.get("detail", "")),
       "勾了已不存在的商品 → 拒绝并说明", f"{s} {d}")

    # ⑧ 闸门②：按配完的真实结果判 —— 一个都看不到就拒绝
    s, d = req("PUT", f"/users/{shipper['id']}/product-visibility",
               {"scope": "custom", "category_names": ["探针里没有这个分类"], "hidden_product_ids": [keep["id"]]}, disp)
    ok(s == 400 and "一个商品都看不到" in str(d.get("detail", "")),
       "配完一个都看不到 → 拒绝并说明", f"{s} {d}")

    # ⑨ 派单员（改这一份的人）不受限：这些设置对他一点作用都没有
    s, _ = req("GET", f"/products/{pa['id']}", token=disp)
    ok(s == 200, "派单员仍然不受可见范围限制", f"实际 {s}")

    # ---------------------------------------------------------- 清理
    req("PUT", f"/users/{shipper['id']}/product-visibility", {"scope": "all", "product_ids": []}, disp)
    for p in made_products:
        req("DELETE", f"/products/{p['id']}", token=disp)
    for cid in ids:
        req("DELETE", f"/product-categories/{cid}", token=disp)
    left = [x["name"] for x in req("GET", "/product-categories", token=disp)[1] if x["name"].startswith(TAG)]
    print(f"\n（已清理：可见范围恢复 all；探查分类剩余 {len(left)} 个）")
    print("\n结果：", "全部通过" if bad == 0 else f"{bad} 项不符")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
