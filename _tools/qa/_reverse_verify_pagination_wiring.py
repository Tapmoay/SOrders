"""反向验证「列表截断必须有回报、客户端必须有入口」这条红线**真的会红**（R14-8）。

## 为什么这条要反向验证
它的判据全是"某处必须有某个接线"，而这类判据最典型的失效方式是**锚点太宽**：
`hasMore` 这个词在四个文件里出现了十几次，随便删掉界面那一行，判据照样绿
（本项目已在"卡片 Markdown 检查只扫手写文件"上栽过一次）。所以这里逐段把接线拆掉，
**每一段都必须单独让红线报红** —— 拆了不红的那一段就等于没被检查。

另外两条专门打"清单"本身：
- 把某个 Kotlin 文件挪走 → 必须报红（不许静默跳过不存在的文件）；
- 后端只留截断位、删掉上限值 → 必须报红。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过"注入把守卫留在源码里"）。

用法：python _tools/qa/_reverse_verify_pagination_wiring.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_pagination_wiring.py"

API = "android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt"
REPO = "android/app/src/main/java/com/tapmoay/sorders/data/repo/AppRepository.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/messages/MessagesViewModel.kt"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/messages/MessagesScreen.kt"
BACKEND = "backend/app/api/v1/notifications.py"
MAIN = "backend/app/main.py"
FE_ORDERS = "frontend/src/api/orders.ts"
FE_ORDER_LIST = "frontend/src/views/shipper/OrderList.vue"
FE_DRIVER_OPEN = "frontend/src/views/driver/DriverOpenOrders.vue"
FE_MSG_CENTER = "frontend/src/components/MessageCenterPopup.vue"

CASES: list[tuple[str, str, object]] = [
    (
        "接口层不再声明 before_id 游标（回到『一次 200 条、没有下一页』）",
        API,
        lambda s: s.replace('@Query("before_id") beforeId: Long? = null,', "", 1),
    ),
    (
        "接口层不再返回 Response（读不到 X-Truncated 响应头）",
        API,
        lambda s: s.replace(
            "    ): Response<List<NotificationDto>>", "    ): List<NotificationDto>", 1
        ),
    ),
    (
        # 2026-09-20 更新锚点：截断的判据已经收敛到 `AppRepository.pageMeta()`（唯一一份），
        # 不再有内联的 `resp.headers()["X-Truncated"] == "1"`。
        # 注入的是"不再读服务端说的小于/等于上限"，改成永远说"没有更多"——
        # 红线 `_check_page_truncation_wiring.py` 会红（列表页的『还有更多』再也亮不起来）。
        "仓库层改成永远说『没有更多』（猜，而不是读服务端说的）",
        REPO,
        lambda s: s.replace(
            '    parsePageMeta(headers()["X-Truncated"], headers()["X-Result-Limit"])',
            "    PageMeta(hasMore = false, limit = null)",
            1,
        ),
    ),
    (
        "ViewModel 首屏不回填 hasMore（第一页拿满时界面永远不显示入口）",
        VM,
        lambda s: s.replace(
            "            messages = page.rows\n            hasMore = page.hasMore\n",
            "            messages = page.rows\n",
            1,
        ),
    ),
    (
        "ViewModel 的 loadMore 不用游标（改回从头发一遍，翻页翻不动）",
        VM,
        lambda s: s.replace("beforeId = messages.last().id", "beforeId = null", 1),
    ),
    (
        "界面上那一行删掉（后端给了截断、客户端没有入口）",
        SCREEN,
        lambda s: s.replace("if (vm.hasMore) {", "if (false) {", 1),
    ),
    (
        "界面那一行留着但点不动",
        SCREEN,
        lambda s: s.replace("onClick = { vm.loadMore() }", "onClick = { }", 1),
    ),
    (
        # 2026-09-20 更新锚点：两个响应头现在只在 `core/pagination.py::finish_page`
        # 一处写（8 个列表端点共用），所以注入目标从 notifications.py 换成它。
        "后端只留截断位、不给上限值（客户端说不出『看到的是多少条』）",
        "backend/app/core/pagination.py",
        lambda s: s.replace('    response.headers["X-Result-Limit"] = str(limit)\n', "", 1),
    ),
    # ---- 2026-09-19 审计 H2 新增：CORS 暴露 + H5 列表页 ----
    (
        "CORS 不再暴露 X-Truncated（跨源时浏览器读不到头，界面永远显示『没有更多』）",
        MAIN,
        lambda s: s.replace(
            '        expose_headers=["X-Truncated", "X-Result-Limit", "Content-Disposition"],\n',
            "",
            1,
        ),
    ),
    (
        "CORS 只暴露了一半（X-Result-Limit 掉了）",
        MAIN,
        lambda s: s.replace(
            'expose_headers=["X-Truncated", "X-Result-Limit", "Content-Disposition"]',
            'expose_headers=["X-Truncated"]',
            1,
        ),
    ),
    (
        "CORS 不暴露 Content-Disposition（导出下载只能拿到兜底文件名）",
        MAIN,
        lambda s: s.replace(
            'expose_headers=["X-Truncated", "X-Result-Limit", "Content-Disposition"]',
            'expose_headers=["X-Truncated", "X-Result-Limit"]',
            1,
        ),
    ),
    (
        "H5 接口层不再读 X-Truncated（回到只取 data）",
        FE_ORDERS,
        lambda s: s.replace("const raw = headers['x-truncated']", "const raw = undefined", 1),
    ),
    (
        "H5 接口层不再读 X-Result-Limit（说不出看到的是多少条）",
        FE_ORDERS,
        lambda s: s.replace("const lim = headers['x-result-limit']", "const lim = undefined", 1),
    ),
    (
        "货主列表页把截断说明删掉（后端说了、界面不说）",
        FE_ORDER_LIST,
        lambda s: s.replace('    <van-notice-bar\n      v-if="truncated"', '    <van-notice-bar\n      v-if="false"', 1),
    ),
    (
        "司机进行中页把截断标记丢掉（取回 page.items 但不再记住 truncated）",
        FE_DRIVER_OPEN,
        lambda s: s.replace('    truncated.value = page.truncated\n', '', 1),
    ),
    (
        "消息中心把截断位丢掉（200 条上限之外的消息一个入口都没有）",
        FE_MSG_CENTER,
        lambda s: s.replace('    truncated.value = page.truncated\n', '', 1),
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1200:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        # ⚠️ 按**行尾**归一后再做字符串替换：H5 的 `.vue` 是 CRLF、`.ts`/`.py` 是 LF，
        #    不归一的话锚点永远匹配不上（实测踩过：注入静默不生效，脚本却报 SKIP）。
        #    写回时按原行尾还原，保证跑完逐字节一致。
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated.replace("\r\n", "\n")
            if crlf:
                out_txt = out_txt.replace("\n", "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        if code != 0:
            print(f"  [OK] {label} → 红线报红")
        else:
            fails.append(f"{label}：注入之后红线**仍然全绿**（判据没牙）")
            print(f"  [MISS] {label} → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
