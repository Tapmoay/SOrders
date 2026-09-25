"""回归测试：**截断头必须真的能被浏览器读到**（2026-09-19 审计 H2）。

## 缺陷形状
`GET /orders` 对所有角色都有 300 条缺省上限，把"这次被截断了"写在响应头
`X-Truncated` / `X-Result-Limit` 里（响应体是裸数组，加不了元数据）。
而**浏览器只让脚本读「被显式暴露」的响应头** —— `allow_headers` 管的是**请求**头，
响应头必须写进 `expose_headers`：

- 同源部署（nginx 反代 / Vite 代理）读得到 → 本机测不出来；
- 一旦 H5 放到别的源上（`VITE_API_BASE_URL` 指到 API 域名），
  axios 拿到的 `headers['x-truncated']` 就是 `undefined` → **界面永远显示"没有更多了"**。

后者正是"派单员以为看到全部订单"这条缺陷的静默版本：接口说了、浏览器没让客户端看见。
所以这条测试**带 `Origin` 发请求**（不带 Origin 时 CORS 中间件根本不加这个头，
测试会假绿——这正是它必须端到端发一次真请求的原因）。
"""
from __future__ import annotations

from tests.conftest import auth_headers

#: 客户端**发出去**的请求头（不是「读到的响应头」）—— 下面的扫描器只按 `x-...` 字面量抓，
#: **分不清方向**，所以这一小撮要写在这里，⛔ 每条都要说清为什么它不是响应头。
#:
#: ⚠️ 为什么不干脆把扫描放宽（比如只认 `headers["x-..."]` 那种读法）：这条判据的价值就在于
#:    「客户端读了却没暴露 = 跨源时读不到，而界面永远显示『没有更多了』」那类**静默失败**；
#:    放宽正则等于把它变成摆设。用它自己的形状（带理由 + 化石检测）收口更稳：
#:    既能放行请求头，又不会把真正的响应头一起放过去。
#: 三条纪律与仓库里其它例外表同：① 每条写理由；② 理由里写什么时候删；
#: ③ 没命中、或者它其实**已经**在 expose_headers 里了 = 化石，报红。
REQUEST_ONLY: dict[str, str] = {
    "x-sorders-origin": (
        "**请求**头（App → 后端）：AI 确认卡写库时标注来源，后端据此把审计行记成 origin=ai"
        "（android 的 core/ClientOrigin.kt ↔ 后端的 core/client_origin.py）。它只在请求方向上出现，"
        "浏览器读不到也不需要读它。**哪天客户端开始读这个响应头（比如后端回显它），删掉这一条、"
        "并把它加进 expose_headers。**"
    ),
}


def test_truncation_headers_are_exposed_to_browsers(client, token_dispatcher):
    r = client.get(
        "/api/v1/orders",
        headers={**auth_headers(token_dispatcher), "Origin": "http://h5.example.com"},
    )
    assert r.status_code == 200, r.text

    # ① 后端确实在回报截断状态（没有它，暴露不暴露都无从谈起）
    assert "X-Truncated" in r.headers, "列表接口没有回报截断位"
    assert "X-Result-Limit" in r.headers, "列表接口没有回报本次上限"

    # ② 浏览器侧：这两个头必须在 `Access-Control-Expose-Headers` 里
    exposed = r.headers.get("access-control-expose-headers", "")
    low = exposed.lower()
    assert "x-truncated" in low, (
        f"跨源时浏览器读不到 X-Truncated（expose_headers = {exposed!r}）——"
        "界面会永远显示『没有更多了』"
    )
    assert "x-result-limit" in low, f"跨源时浏览器读不到 X-Result-Limit（expose_headers = {exposed!r}）"


def test_expose_headers_covers_every_header_the_clients_read():
    """清单不手写：客户端源码里读了哪些 `X-...` 头，就必须暴露哪些。"""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    read: set[str] = set()
    for base, exts in (
        (root / "frontend/src", (".ts", ".vue")),
        (root / "android/app/src/main/java/com/tapmoay/sorders", (".kt",)),
    ):
        for p in sorted(base.rglob("*")):
            if p.is_file() and p.suffix in exts:
                src = p.read_text(encoding="utf-8", errors="replace")
                for m in re.finditer(r"""["'\[\s](x-[a-z-]+)["'\]]""", src, re.I):
                    read.add(m.group(1).lower())
    assert read, "一个 X- 响应头都没扫到——解析失效了，这条断言等于没查"

    cors = (root / "backend/app/main.py").read_text(encoding="utf-8")
    m = re.search(r"expose_headers\s*=\s*\[([^\]]*)\]", cors)
    assert m, "CORSMiddleware 没有写 expose_headers"
    exposed = {h.lower() for h in re.findall(r'"([^"]+)"', m.group(1))}
    # ---- 例外表自己的纪律：写在表里却**没被扫到**＝化石；已经暴露了＝这条例外多余 ----
    fossils = sorted(k for k in REQUEST_ONLY if k not in read or k in exposed)
    assert not fossils, (
        f"REQUEST_ONLY 里这些条目已经没用了（扫不到它、或它已经在 expose_headers 里）：{fossils} ——"
        "清掉那一行，别让例外表长霉"
    )
    missing = sorted(read - exposed - set(REQUEST_ONLY))
    assert not missing, f"客户端读了但没暴露的响应头：{missing}（跨源时读不到）"
