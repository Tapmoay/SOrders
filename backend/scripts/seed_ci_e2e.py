"""给安卓端到端（登录 → 导航 → 下单）准备**最小数据**：几个商品 + 货主的一条收货地址。

## 为什么单独写一个（而不是用 seed_demo_data.py）
`seed_demo_data.py` 造的是**近 4 个月**的完整演示数据（24 个货主 / 22 个司机 / 上千单），
跑一次要几分钟，而且开头会 `reset_business_data` 清业务表。
端到端要的只有两样：**选品页里有一行能点**、**地址库里有一条能选**。

## 为什么走 HTTP 而不是直接写库
字段由 schema（`ProductCreate` / `AddressCreate`）把关，造出来的数据**一定过得了接口的关**。
直接 insert 要自己保证 JSON 列形状、默认值、可见性白名单都对 —— 那样很容易造出
「库里看着有、接口读出来是空的」，而端到端恰恰死在"页面上没有东西可点"。

## 幂等
同名商品已存在就跳过；货主已有地址就跳过。这个脚本会被反复跑（每次 CI、以及本地需要时）。

## 命名
⛔ 按 `seed_demo_data.py` 顶部定的规矩：**不写"测试/验证/演示"字样**，名字要像真商品 ——
否则它们会出现在界面的选品页里，而"这条数据是假的"这件事在界面上看不出来。
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request

TIMEOUT_S = 20

#: （名称, 分类, 单位, 售价）—— 名字像真的，理由见模块 docstring。
PRODUCTS: list[tuple[str, str, str, str]] = [
    ("红富士苹果 80#", "水果", "件", "128.00"),
    ("农夫山泉 550ml", "饮品", "箱", "36.00"),
]

ADDRESS = {
    "receiver_name": "陈志强",
    "phone": "13800000002",
    "detail_address": "解放路 88 号 3 栋 102",
    "is_default": True,
}


def call(base: str, method: str, path: str, token: str | None = None, body=None):
    """发一个请求，返回 (状态码, 解析后的 JSON 或原始文本)。**HTTP 错误不抛**，交给调用方判。"""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def login(base: str, phone: str) -> str:
    status, body = call(base, "POST", "/api/v1/auth/login",
                        body={"phone": phone, "password": "pass12345"})
    if status != 200 or not isinstance(body, dict) or "access_token" not in body:
        raise SystemExit(f"登录失败 {phone}：{status} {body}")
    return str(body["access_token"])


def main() -> int:
    ap = argparse.ArgumentParser(description="给安卓端到端准备最小数据")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    dispatcher = login(base, "13800000001")
    status, existing = call(base, "GET", "/api/v1/products?include_inactive=true", token=dispatcher)
    if status != 200 or not isinstance(existing, list):
        raise SystemExit(f"读商品列表失败：{status} {existing}")
    names = {str(p.get("name")) for p in existing if isinstance(p, dict)}
    made = 0
    for name, category, unit, price in PRODUCTS:
        if name in names:
            print(f"skip (exists): {name}")
            continue
        status, body = call(base, "POST", "/api/v1/products", token=dispatcher, body={
            "name": name, "category": category, "unit": unit,
            "default_unit_price": price, "cost_price": "1.00", "stock": 100,
        })
        if status not in (200, 201):
            raise SystemExit(f"建商品失败 {name}：{status} {body}")
        made += 1
        print(f"created product: {name}")

    shipper = login(base, "13800000002")
    status, addrs = call(base, "GET", "/api/v1/shipper/addresses", token=shipper)
    if status != 200 or not isinstance(addrs, list):
        raise SystemExit(f"读地址库失败：{status} {addrs}")
    if addrs:
        print(f"skip (exists): 地址库已有 {len(addrs)} 条")
    else:
        status, body = call(base, "POST", "/api/v1/shipper/addresses", token=shipper, body=ADDRESS)
        if status not in (200, 201):
            raise SystemExit(f"建地址失败：{status} {body}")
        print("created address")

    print(f"Done.（本次新建商品 {made} 个）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
