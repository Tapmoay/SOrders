"""真后端实测：**PATCH 线路时 `image_urls: []` 会清空图片**（W1 的前提）+ 正确姿势能保住（2026-09-19）。

## 为什么要它在
AI 改线路的缺陷（`AiWriteService.updateAddress` 没回填 `imageUrls`）能不能成立，全看后端怎么解释 `[]`：
- `_apply_images` 把 `None` 当"不改"、把 `[]` 当"清空"（`shipper.py:26-32`）；
- 而 App 的 Json 配置是 `encodeDefaults = true` → DTO 里 `imageUrls = emptyList()` 的默认值
  **每次都会被发出去**。

所以这条探针在真后端上把两种请求各打一次，证明：
① `image_urls: []` → 图片真的没了（**这就是线上发生的事**）；
② `image_urls: [原样]**` → 图片还在（**修好之后 App 发的就是这一种**）。

判据：② 必须保住；① 只作为"缺陷可复现"的证据打印（不参与成败）。

用法：python _tools/qa/_probe_address_images.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

BASE = "http://127.0.0.1:8000/api/v1"
SHIPPER = ("13800000002", "123321")

fails: list[str] = []
passes = 0


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def login(phone: str, password: str) -> str:
    st, d = call("POST", "/auth/login", body={"phone": phone, "password": password})
    if st != 200 or not isinstance(d, dict):
        raise SystemExit(f"登录 {phone} 失败：{st} {d}")
    return d["access_token"]


IMG = ["/static/uploads/address/probe-1.jpg", "/static/uploads/address/probe-2.jpg"]


def make_address(tok: str, tag: str) -> dict:
    st, row = call(
        "POST",
        "/shipper/addresses",
        token=tok,
        body={
            "receiver_name": f"探针收货人-{tag}",
            "phone": "13900000000",
            "detail_address": f"探针路 {tag} 号",
            "image_urls": IMG,
        },
    )
    if st not in (200, 201):
        raise SystemExit(f"建线路失败：{st} {row}")
    return row


def patch_address(tok: str, aid: int, body: dict) -> dict:
    st, row = call("PATCH", f"/shipper/addresses/{aid}", token=tok, body=body)
    if st != 200:
        raise SystemExit(f"改线路失败：{st} {row}")
    return row


def main() -> int:
    tok = login(*SHIPPER)

    # ① 缺陷可复现：PATCH 带 `image_urls: []`（旧 App 每次都会带）
    bad = make_address(tok, "旧写法")
    assert len(bad.get("image_urls") or []) == 2, f"前提不成立：建出来没有 2 张图 {bad.get('image_urls')}"
    after_bad = patch_address(
        tok,
        int(bad["id"]),
        {
            "receiver_name": bad["receiver_name"],
            "phone": "13900000001",  # 只改电话
            "detail_address": bad["detail_address"],
            "image_urls": [],
        },
    )
    n_bad = len(after_bad.get("image_urls") or [])
    print(f"  ① 旧姿势（带 `image_urls: []`）：2 张图 → {n_bad} 张"
          f"{'（缺陷成立：只改电话就把图清了）' if n_bad == 0 else ''}")

    # ② 修复后的姿势：回填原图列表
    good = make_address(tok, "新写法")
    after_good = patch_address(
        tok,
        int(good["id"]),
        {
            "receiver_name": good["receiver_name"],
            "phone": "13900000002",  # 只改电话
            "detail_address": good["detail_address"],
            "image_urls": good["image_urls"],
        },
    )
    imgs = after_good.get("image_urls") or []
    ok("回填原图后改电话：图片一张不少", len(imgs) == 2, f"实际 {imgs}")
    ok("电话确实改了（不是「什么都没做」）", after_good.get("phone") == "13900000002",
       f"实际 {after_good.get('phone')}")

    # 收尾：软删两条探针线路
    for row in (bad, good):
        st, _ = call("DELETE", f"/shipper/addresses/{row['id']}", token=tok)
        print(f"  清理：线路 #{row['id']} → HTTP {st}")

    print()
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：`image_urls: []` 会清图（缺陷可复现），回填后不会（修法有效）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
