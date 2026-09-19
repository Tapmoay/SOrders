"""红线：**列表被服务端截断时，客户端必须能看出「还有更多」并且真的有入口**（R14-8）。

## 由来（2026-09-19 审计第十四轮）
`GET /notifications` 一直是一条硬 `.limit(200)`：没有分页、没有游标、也不回报截断。
实测（派单员账号 2336 条、未读 1134）：`?limit=5` / `?limit=1000` 一律返回 200 条，
响应头里什么都没有；而 `GET /orders` 早就有 `X-Truncated` 了。

真实后果不是"少看到几条"：
- 第 201 条以前的旧消息在 App 里**一个入口都没有**，其中包含「账本导出完成」这种
  payload 里带**唯一下载链接**的通知（那条链接过期就再也拿不到）；
- 用户点「全部已读」把 1134 条标掉，其实只看过 200 条；
- 同一个坑还从 AI 侧漏回来：`AiReadCatalog` 没声明 `limit` → `AiReadService` 那个
  "多要一行"的截断探针根本不发出去 → 模型答「你一共有 200 条消息」（真值 2336）。

## 判据（文件清单自己算，不手写）
后端：所有 `api/v1/*.py` 里出现 `X-Truncated` 的模块都要**同时**写 `X-Result-Limit`
（头形状与 `GET /orders` 同源；只有截断位没有上限值，客户端没法说清"看到的是多少条"）。

客户端：由 glob 算出 `MessagesViewModel.kt` / `MessagesScreen.kt` / `Apis.kt` /
`AppRepository.kt` 四个文件（不存在就报错，不做静默跳过），要求整条链路**逐段接通**：
```
Apis.kt         声明 before_id 游标 + 返回 Response<...>（否则读不到响应头）
AppRepository   真的读 X-Truncated → NotificationPage.hasMore
MessagesViewModel  hasMore / loadingMore / loadMore() 用游标翻页
MessagesScreen   「加载更多」这一行由 vm.hasMore 门控，点了调 vm.loadMore()
```
并且四条 `present` 之外还有一条"数量判据"：整条链路上 `hasMore` 至少出现 5 次
（防止有人把界面那一行删掉、判据却因为别处还有这个词而全绿）。

用法：python _tools/qa/_check_pagination_wiring.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用单源红线里的 `code_only`（把注释/文档字符串换成等长空格，保留行号）。
#: ⚠️ 后端那一半**必须**剥掉注释：本文件自己的文档里就写着 `X-Result-Limit` 这个名字
#:    （"响应头形状与 /orders 同源"），不剥的话把真代码删掉、判据照样绿 ——
#:    反向验证第一次就是这样漏掉那条注入的。
from _check_single_source import code_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
BACKEND_API = ROOT / "backend/app/api/v1"
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
FE_SRC = ROOT / "frontend/src"

KOTLIN = {
    "api": ANDROID / "data/remote/api/Apis.kt",
    "repo": ANDROID / "data/repo/AppRepository.kt",
    "vm": ANDROID / "ui/messages/MessagesViewModel.kt",
    "screen": ANDROID / "ui/messages/MessagesScreen.kt",
}

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    src = re.sub(r"//[^\n\"']*$", "", src, flags=re.M)
    return src


def main() -> int:
    print("后端：截断头必须成对出现")
    mods = sorted(BACKEND_API.glob("*.py"))
    ok("api/v1 下模块 >= 20 个（清单自己算，防路径写错后空转）", len(mods) >= 20, f"实际 {len(mods)}")
    with_trunc = []
    for p in mods:
        src = code_only(p.read_text(encoding="utf-8"))
        if "X-Truncated" in src:
            with_trunc.append(p.name)
            ok(
                f"{p.name} 同时给了 X-Result-Limit（只有截断位说不出『看到的是多少条』）",
                "X-Result-Limit" in src,
            )
    ok("至少 2 个列表端点回报截断（notification + orders）", len(with_trunc) >= 2, f"实际 {len(with_trunc)}")

    # ---- 2026-09-19 审计 H2：**浏览器只让脚本读「被显式暴露」的响应头** ----
    # `allow_headers` 管的是请求头；响应头不写进 `expose_headers`，跨源时
    # axios 拿到的 `headers['x-truncated']` 就是 undefined —— 界面永远显示"没有更多了"，
    # 而那正是"派单员以为看到全部订单"这条缺陷的静默版本。
    # 清单**从客户端源码算**：谁读了哪个 X- 头，就必须被暴露出去。
    print("\n后端：客户端读的响应头必须被 CORS 暴露")
    read_headers: set[str] = set()
    for base, exts in ((FE_SRC, (".ts", ".vue")), (ANDROID, (".kt",))):
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix not in exts:
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            # 认三种写法：`headers['x-truncated']`（axios）、`resp.headers()["X-Truncated"]`（OkHttp）、
            # 以及任何 `headers[...]` 里出现的头名 —— **不限 `x-` 前缀**：
            # 导出下载要靠 `Content-Disposition` 取文件名，它同样必须被 expose 出去。
            for m in re.finditer(
                r"""headers?\(?\)?\s*(?:\[\s*|\.get\(\s*)["']([A-Za-z0-9-]+)["']""", src
            ):
                read_headers.add(m.group(1).lower())
    ok("从客户端源码扫到至少 2 个响应头（清单自己算，防解析失效后空转）",
       len(read_headers) >= 2, f"实际 {sorted(read_headers)}")
    cors = code_only((BACKEND / "app/main.py").read_text(encoding="utf-8"))
    m = re.search(r"expose_headers\s*=\s*\[([^\]]*)\]", cors)
    exposed = {h.lower() for h in re.findall(r'"([^"]+)"', m.group(1))} if m else set()
    ok("CORSMiddleware 声明了 expose_headers", m is not None)
    missing_expose = sorted(h for h in read_headers if h not in exposed)
    ok(
        f"客户端读的响应头都在 expose_headers 里（读 {sorted(read_headers)}）",
        not missing_expose,
        "没暴露：" + "、".join(missing_expose) + "（跨源时浏览器读不到 → 客户端只能当成『没截断』）",
    )

    print("\nH5（frontend/）：列表页要看得出「服务端截断了」")
    fe_api = FE_SRC / "api/orders.ts"
    ots = strip_comments(fe_api.read_text(encoding="utf-8"))
    ok("接口层读了 X-Truncated（旧 H5 只取 data，从不看截断头）", "x-truncated" in ots.lower())
    ok("接口层读了 X-Result-Limit（说不出『看到的是多少条』）", "x-result-limit" in ots.lower())
    ok("接口层把两者包成一页返回（OrdersPage）",
       "interface OrdersPage" in ots and "truncated" in ots and "limit" in ots)
    # 逐页对账：凡是**列出订单/消息**的页面或组件，必须把 truncated 渲染出来。
    # 文件名从源码算：调用了分页接口 `.vue` 就是"列表界面"（views 与 components 都算，
    # 消息中心是 `components/MessageCenterPopup.vue` —— 只扫 views 会漏掉它）。
    list_views = [
        p for p in sorted(FE_SRC.rglob("*.vue"))
        if re.search(
            r"fetchOrdersPage\(|fetchOrdersByStatuses\(|fetchNotificationsPage\(",
            p.read_text(encoding="utf-8"),
        )
    ]
    ok("扫到 >=5 个 H5 列表界面（清单自己算，防路径写错后空转）", len(list_views) >= 5, f"实际 {len(list_views)}")
    for p in list_views:
        src = p.read_text(encoding="utf-8")
        rel = p.relative_to(ROOT)
        # ① 真的从 page 取值（只声明一个恒为 false 的 ref = 提示条永远不出现，
        #    而"提到过 truncated 这个词"照样成立 —— 反向验证抓到过一次）
        ok(f"{rel.name} 把服务端的截断位真的取回来（truncated.value = …）",
           re.search(r"truncated\.value\s*=", src) is not None)
        # ② 真的渲染出来，且**有话说**（`truncatedText` 或一条 text=）
        ok(f"{rel.name} 渲染了截断说明（v-if=\"truncated\" + text）",
           re.search(r'v-if="truncated"', src) is not None
           and ("truncatedText" in src or re.search(r':?text="', src) is not None))

    print("\n客户端：消息列表的整条链路")
    body: dict[str, str] = {}
    for key, p in KOTLIN.items():
        if not p.exists():
            fails.append(f"{p.relative_to(ROOT)} 不见了（改名/移动了？判据要跟着改，不许静默跳过）")
            print(f"  [FAIL] 找不到 {p.relative_to(ROOT)}")
            continue
        body[key] = strip_comments(p.read_text(encoding="utf-8"))

    if len(body) == len(KOTLIN):
        ok(
            "接口层声明了 before_id 游标",
            re.search(r'@Query\("before_id"\)', body["api"]) is not None,
        )
        ok(
            "接口层返回 Response<...>（不返回它就读不到 X-Truncated 响应头）",
            re.search(r"suspend fun listNotifications\([\s\S]{0,600}?\): Response<", body["api"]) is not None,
        )
        ok(
            "仓库层真的读 X-Truncated（而不是靠『条数等于上限』去猜）",
            'headers()["X-Truncated"]' in body["repo"],
        )
        ok("仓库层把 hasMore 交给调用方", "NotificationPage" in body["repo"] and "hasMore" in body["repo"])
        ok(
            "ViewModel 有 hasMore 状态",
            re.search(r"var hasMore by mutableStateOf", body["vm"]) is not None,
        )
        ok(
            "ViewModel 用游标翻页（beforeId = 当前最后一条的 id）",
            re.search(r"beforeId\s*=\s*messages\.last\(\)\.id", body["vm"]) is not None,
        )
        ok(
            "首屏也回填 hasMore（否则第一页拿满 100 条时界面永远不显示入口）",
            re.search(r"messages = page\.rows\s*\n\s*hasMore = page\.hasMore", body["vm"]) is not None,
        )
        ok(
            "界面那一行由 vm.hasMore 门控",
            re.search(r"if \(vm\.hasMore\)", body["screen"]) is not None,
        )
        ok(
            "界面上真的能点（调 vm.loadMore()）",
            re.search(r"onClick = \{ vm\.loadMore\(\) \}", body["screen"]) is not None,
        )
        total = sum(b.count("hasMore") for b in body.values())
        ok("链路上 hasMore 至少出现 5 次（防止某一环被删掉而判据仍绿）", total >= 5, f"实际 {total}")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：截断有回报、客户端有入口。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
