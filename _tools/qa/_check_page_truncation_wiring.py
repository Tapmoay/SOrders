"""红线：**列表被服务端截断时，App 必须把「还有更多」说出来**（2026-09-19，本轮 7 个页面）。

## 由来
后端 `app/core/pagination.py::finish_page()` 是列表端点的**唯一出口**：谁声明了 `limit`，
谁就回 `X-Truncated: 1|0` 与 `X-Result-Limit: <本次上限>`。但在这之前有 7 个页面读的端点
什么都不说，界面于是把"一页"当成"全部"。

后果不是"少看到几条"，而是用户照着一个**错的结论**去做决定：
- 现金流水页对"一页 N 条"求和当总额 —— 实测 ¥18,842 vs 真值 ¥48,905.50（**少算 62%**）；
- 审计页看不到更早的 → "我那次改动没被记下来"；
- 账号列表超过一页 → "没有这个账号" → 再建一个（撞手机号唯一约束）；
- 账本页的「当前范围内合计」只加了看得见的那一页（那个数是在客户端 sum 出来的）。

## 判据（清单**全部自己算**，不手写页码）
1. **读头只有一处**：整个 Android 源码里 `X-Truncated` 的读取恰好出现 **1 次**，且必须在
   `data/repo/AppRepository.kt` 的 `pageMeta()` 里。抄第二遍就有两套判据，改一处漏一处
   —— 那 7 个端点静默漏报的成因就是"只有消息列表抄了一份"。
2. **端点到仓库这一段**：从 `Apis.kt` 自己算出所有返回 `Response<List<...>>` 的列表方法，
   每一个都必须被仓库层消费（`.pageRows()` 或 `.pageMeta()`）——返回 `Response` 却不读头，
   等于白改签名。
3. **仓库到界面这一段**：从源码算出"接线"的数量
   （`= page.meta.hasMore` 的读取处、界面上的 `TruncationNote(` 调用处），
   每一处都必须在 ≥ 下限。**少一处就红** —— 这就是"某个页面又静默了"的判据。
4. 反空转：端点数 < 6 或接线数 < 下限时先报错，而不是安静地什么都不查。

⚠️ 注入式反向验证（改坏 → 本脚本必须红，改回 → 绿）：
   把任一 ViewModel 的 `page.meta.hasMore` 改成 `false` → 第 3 条数量掉下来；
   把任一界面的 `TruncationNote(` 删掉 → 同样红。

用法：python _tools/qa/_check_page_truncation_wiring.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用兄弟红线里剥 Kotlin 注释/块注释的实现（保留行号），不抄第二份。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
REPO = ANDROID / "data/repo/AppRepository.kt"
APIS = ANDROID / "data/remote/api/Apis.kt"

#: 接线数量的下限＝**本轮的实测值**（`>=`：多加页面不用改这里，少一个就红）。
#: 为什么用实测值当阈值：这几个数字就是"7 个页面都还接着"的判据本身，
#: 留余量等于允许某个页面静默退回去。
MIN_META_READS = 8      # ViewModel 里读 `page.meta.hasMore` 的处数
MIN_NOTES = 9           # 界面里 `TruncationNote(` 的调用处数
MIN_ENDPOINTS = 6       # 返回 `Response<List<...>>` 的列表端点方法数

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


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的判据要跟着改，不许静默跳过）")
    return p.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    # ---- 1. 读头只有一处 ----
    print("读头：整个 App 只有一处解析截断头")
    repo_src = strip_comments(read(REPO))
    ok(
        "仓库层有唯一读头 pageMeta()，且两个头名都在里面",
        re.search(r"fun Response<\*?>\.pageMeta\(\)", repo_src) is not None
        and '"X-Truncated"' in repo_src
        and '"X-Result-Limit"' in repo_src,
        "少了它，7 个页面就只能各自去猜「这页满了没有」",
    )
    readers = []
    for p in sorted(ANDROID.rglob("*.kt")):
        if '"X-Truncated"' in strip_comments(p.read_text(encoding="utf-8", errors="replace")):
            readers.append(p)
    ok(
        "全树读 X-Truncated 的地方正好 1 个（就是 pageMeta）",
        len(readers) == 1 and readers[0] == REPO,
        f"实际 {[str(p.relative_to(ROOT)) for p in readers]}",
    )

    # ---- 2. 端点到仓库：返回 Response 的列表方法必须被消费 ----
    print("\n端点到仓库：返回 Response<...> 的列表方法必须真的读头")
    apis_src = strip_comments(read(APIS))
    # 只认"一页列表"那类：签名是 `suspend fun x(...): Response<List<...>>`。
    # ⚠️ 必须先按**注解**切块再匹配：直接对全文用懒惰 `[\s\S]*?` 会跨过函数边界
    #    （`login(...): Response<LoginResponse>` 会一路吃到后面某个 `): Response<List<`），
    #    实测那样认出来的 6 个"端点"里有 6 个是写端点 —— 判据就成了噪音。
    pieces = re.split(r"(?=@(?:GET|POST|PATCH|PUT|DELETE)\()", apis_src)
    paged: list[str] = []
    for piece in pieces:
        m = re.search(r"suspend fun (\w+)\([\s\S]*?\)\s*:\s*Response<\s*List<", piece)
        if m:
            paged.append(m.group(1))
    ok(
        f"认出 ≥{MIN_ENDPOINTS} 个 paged 列表端点（清单自己算，防正则失配后空转）",
        len(paged) >= MIN_ENDPOINTS,
        f"实际 {len(paged)}：{paged}",
    )
    for name in paged:
        m = re.search(rf"\.{name}\(", repo_src)
        tail = repo_src[m.start():m.start() + 600] if m else ""
        ok(
            f"仓库层消费了 {name} 的响应头（pageRows 或 pageMeta）",
            m is not None and (".pageRows()" in tail or ".pageMeta()" in tail),
            "返回 Response 却不读头 = 白改签名（界面照样把一页当全部）",
        )

    # ---- 3. 仓库到界面：接线数量 ----
    print("\n仓库到界面：截断位必须一路走到界面上的一句提示")
    kts = {p: strip_comments(p.read_text(encoding="utf-8", errors="replace")) for p in sorted(ANDROID.rglob("*.kt"))}
    meta_reads = sum(len(re.findall(r"\.meta\.hasMore", s)) for s in kts.values())
    ok(
        f"ViewModel 读 `page.meta.hasMore` ≥ {MIN_META_READS} 处（少一处＝某个列表页又静默了）",
        meta_reads >= MIN_META_READS,
        f"实际 {meta_reads}",
    )
    # `TruncationNote(` 的**调用**处（排掉 `fun TruncationNote(` 那个定义本身）。
    note_sites = sum(len(re.findall(r"(?<!fun )TruncationNote\(", s)) for s in kts.values())
    ok(
        f"界面渲染 TruncationNote(...) ≥ {MIN_NOTES} 处",
        note_sites >= MIN_NOTES,
        f"实际 {note_sites}",
    )
    note_files = [p for p, s in kts.items() if re.search(r"(?<!fun )TruncationNote\(", s)]
    ok(
        "每一处提示都在**被截断时**才显示（同文件里有截断位门控）",
        all(re.search(r"if \((?:\w+\.)?\w*[Tt]runcated|if \(meta\?\.hasMore", s) for p, s in kts.items() if p in note_files),
        "无条件显示的提示等于没判据",
    )
    ok(
        "文案不说做不到的话：提示必须点名一个**页面上真实存在**的入口",
        all(
            any(k in s for k in ("时间导航", "日期筛选", "搜索框", "导出", "别直接新建"))
            for p, s in kts.items()
            if p in note_files
        ),
        "这 7 个页面的出路是已有的筛选（有的页面没有日期筛选，只能指向搜索/导出，或只说别下错结论）",
    )
    ok(
        "上限读不到时不编数字（TruncationNote 的 limit 允许为 null，由文案兜底）",
        "服务器没回报条数" in read(ANDROID / "ui/common/Components.kt"),
    )

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：截断有回报，7 个页面都会说出来。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
