#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_pagination_wiring.py` 的**安卓 + 后端**那一半真的会红（R14-8）。

## 为什么是这一份（而不是 2026-09-19 原来那份）
原来那份共 15 条注入，其中 **5 条打 H5**（`frontend/src/api/orders.ts` 读两个响应头、
货主列表页 / 司机进行中页 / 消息中心的 `truncated` 标记）。2026-09-25 前端 H5 按用户拍板
归档（`frontend/` 已不在仓库里，见计划表 §4.2）→ 那 5 条没有主体，整份脚本被删。
但**安卓与后端那 10 条不能因此失去反向验证** —— 这一份把它们补回来（判据不变）。

## 这一页在防什么
这条红线的判据全是"某处必须有某个接线"，而这类判据最典型的失效方式是**锚点太宽**：
`hasMore` 这个词在四个文件里出现十几次，随便删掉界面那一行，判据照样绿
（本项目已在"卡片 Markdown 检查只扫手写文件"上栽过一次）。所以这里逐段把接线拆掉，
**每一段都必须单独让红线报出对应的那条判据** —— 拆了不红的那一段就等于没被检查。

另外两条专门打"清单"本身：
- 把某个 Kotlin 文件挪走 → 必须报红（不许静默跳过不存在的文件）；
- 后端只留截断位、删掉上限值 → 必须报红。

⚠️ 快照/还原按**字节**做，跑完逐文件核对（本项目栽过"注入把守卫留在源码里"）。
⛔ 全程不碰 `git checkout --`（那会在真有改动时抹掉工作）。

用法：python _tools/qa/_reverse_verify_pagination_wiring.py
      python _tools/qa/_reverse_verify_pagination_wiring.py --list
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_pagination_wiring.py"

API = "android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt"
REPO = "android/app/src/main/java/com/tapmoay/sorders/data/repo/AppRepository.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/messages/MessagesViewModel.kt"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/messages/MessagesScreen.kt"
PAGE_CORE = "backend/app/core/pagination.py"
MAIN = "backend/app/main.py"

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的标签片段)
CASES: list[tuple[str, str, str, str, str]] = [
    (
        "接口层不再声明 before_id 游标（回到『一次 200 条、没有下一页』）",
        API,
        '@Query("before_id") beforeId: Long? = null,',
        "",
        "接口层声明了 before_id 游标",
    ),
    (
        "接口层不再返回 Response（读不到 X-Truncated 响应头）",
        API,
        "    ): Response<List<NotificationDto>>",
        "    ): List<NotificationDto>",
        "接口层返回 Response<...>",
    ),
    (
        # 2026-09-20 更新锚点：截断的判据已经收敛到 `AppRepository.pageMeta()`（唯一一份），
        # 不再有内联的 `resp.headers()["X-Truncated"] == "1"`。
        # 注入的是"不再读服务端说的小于/等于上限"，改成永远说"没有更多"。
        "仓库层改成永远说『没有更多』（猜，而不是读服务端说的）",
        REPO,
        '    parsePageMeta(headers()["X-Truncated"], headers()["X-Result-Limit"])',
        "    PageMeta(hasMore = false, limit = null)",
        "仓库层真的读 X-Truncated",
    ),
    (
        "ViewModel 首屏不回填 hasMore（第一页拿满时界面永远不显示入口）",
        VM,
        "            messages = page.rows\n            hasMore = page.hasMore\n",
        "            messages = page.rows\n",
        "首屏也回填 hasMore",
    ),
    (
        "ViewModel 的 loadMore 不用游标（改回从头发一遍，翻页翻不动）",
        VM,
        "beforeId = messages.last().id",
        "beforeId = null",
        "ViewModel 用游标翻页",
    ),
    (
        "界面上那一行删掉（后端给了截断、客户端没有入口）",
        SCREEN,
        "if (vm.hasMore) {",
        "if (false) {",
        "界面那一行由 vm.hasMore 门控",
    ),
    (
        "界面那一行留着但点不动",
        SCREEN,
        "onClick = { vm.loadMore() }",
        "onClick = { }",
        "界面上真的能点",
    ),
    (
        # 2026-09-20 更新锚点：两个响应头现在只在 `core/pagination.py::finish_page` 一处写
        # （8 个列表端点共用），所以注入目标从 notifications.py 换成它。
        "后端只留截断位、不给上限值（客户端说不出『看到的是多少条』）",
        PAGE_CORE,
        '    response.headers["X-Result-Limit"] = str(limit)\n',
        "",
        "共享出口 `finish_page` 真的写了 X-Result-Limit",
    ),
    # ---- 2026-09-19 审计 H2 新增：CORS 暴露 ----
    (
        "CORS 不再暴露 X-Truncated（跨源时浏览器读不到头，界面永远显示『没有更多』）",
        MAIN,
        '        expose_headers=["X-Truncated", "X-Result-Limit", "Content-Disposition"],\n',
        "",
        "CORSMiddleware 声明了 expose_headers",
    ),
    (
        "CORS 只暴露了一半（X-Result-Limit 掉了）",
        MAIN,
        'expose_headers=["X-Truncated", "X-Result-Limit", "Content-Disposition"]',
        'expose_headers=["X-Truncated"]',
        "客户端读的响应头都在 expose_headers 里",
    ),
]

CRLF = chr(13) + chr(10)


class Sandbox:
    """按**字节**记账的注入沙箱：每次注入前先还原上一轮，跑完再逐字节核对。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, rel: str, old: str, new: str) -> None:
        p = ROOT / rel
        if not p.exists():
            raise ValueError("找不到 " + rel)
        self.saved.setdefault(p, p.read_bytes())
        raw = p.read_bytes()
        crlf = CRLF.encode("utf-8") in raw
        text = raw.decode("utf-8")
        if crlf:
            text = text.replace(CRLF, chr(10))
        if text.count(old) != 1:
            raise ValueError(rel + " 里锚点出现 " + str(text.count(old)) + " 次（要恰好一次）")
        text = text.replace(old, new, 1)
        p.write_bytes((text.replace(chr(10), CRLF) if crlf else text).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(CASES, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条红线就没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时红线是绿的 —— " + last.strip())
        for label, rel, old, new, want in CASES:
            sb.restore()
            try:
                sb.apply(rel, old, new)
                code, out = run_check()
            except ValueError as exc:
                print("  [SKIP] " + label + " —— " + str(exc))
                bad += 1
                continue
            finally:
                sb.restore()
            # ⛔ 必须命中**那一条**判据（这条红线打印的是 `[FAIL] <标签>`）
            hit = code != 0 and ("[FAIL] " + want) in out
            if hit:
                print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
            else:
                bad += 1
                why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("[FAIL]")][:6]:
                    print("       红线实际报的：" + ln)
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    dirty = sb.dirty()
    if dirty:
        bad += 1
        print("⛔ 跑完没逐字节还原：" + "、".join(dirty))
    total = len(CASES) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立：安卓 + 后端那一半的每一段接线被拆掉都会红")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
