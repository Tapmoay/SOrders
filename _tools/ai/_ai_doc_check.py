"""文档自检：引用完整性（§x.y 是否都存在）+ 过期表述残留 + 关键段落是否保留。

### ⚠️ 这个脚本自己曾经"红了 12 轮没人管"（2026-09-16 修）
它把 `§2d`、`§2e-③c`、`§2f-2b` 这类引用当成**文档小节号**去查，
而它们其实是**红线脚本里的小节编号**（`_check_ai_guardrails.py` 打印的 `== 2e. …`）。
于是它一直报"不存在的引用：['2a','2c','2d','2e','2f','2g','3b']"、一直退出码 1，
而每轮的收尾清单里没有它——**一条永远红的检查等于没有检查**。

现在引用分三类，各自有各自的判据：
1. **文档小节**（`§31.5`）：必须能在 v2/v3 任意一份文档的标题里找到（跨文档引用是合法的，
   v3 里引用 v2 的 `§2.5` 就是这种）；
2. **红线小节**（`§2e`）：必须能在红线脚本里找到 `== 2e. …` 这个打印标题；
3. **红线子条目**（`§2f-2b`、`§2e-③c`）：前缀要是红线小节，**并且**这个编号要出现在
   红线脚本的**标记行**里（`# ---- 2f-2b …`）——只要求"字面量出现在文件里"是不够的：
   脚本里可能恰好有一句"见上面的 §2f-2b"的自引用，那会让一条**已经改名的**子条目继续算通过
   （反向验证抓到的）。改成认标记行之后，改号而文档没跟着改就会红。
4. **文档子条目**（`§0-5`、`§9-2`，即"第 0 节的第 5 条"）：前缀必须是真文档小节。
   这一类**只查前缀**（要数清"第 5 条"需要解析正文结构，代价不成比例），
   所以它单独计数、单独打印——让人一眼看出"这几条是按前缀认的"。

用法：
  python _ai_doc_check.py            # 校验全部相关文档
  python _ai_doc_check.py v3         # 只校验 v3
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
DOCS = {
    "v2": ROOT / "docs" / "AI_ASSISTANT_PLAN.md",
    "v3": ROOT / "docs" / "AI_ASSISTANT_PLAN_V3.md",
}
GUARD = Path(__file__).resolve().parent / "_check_ai_guardrails.py"

# 这些词只允许出现在"修订记录/自我纠正/审查记录"小节里（作为对旧说法的引用）
STALE = ["三步走", "第 2 步做", "第 3 步可选", "已用 14 色", "0 命中"]
RECORD_HEADING = re.compile(r"^#{2,4}\s+.*(审查记录|自我纠正|纠正|修订|v1/v2|已删除|已废)", re.M)

# § 后面的编号：`31.5` / `2e` / `2f-2b` / `2e-③c`（圆圈数字在 \u2460-\u24ff）
REF = re.compile(r"§\s*(\d+(?:\.\d+)?[a-z]?(?:[-\u2460-\u24ff0-9A-Za-z]+)?)")
HEADING = re.compile(r"^#{2,4}\s+(\d+(?:\.\d+)?[a-z]?)", re.M)


def doc_headings() -> set[str]:
    """两份文档的小节号并集：v3 里引用 v2 的小节是合法的。"""
    out: set[str] = set()
    for p in DOCS.values():
        if p.exists():
            out |= set(HEADING.findall(p.read_text(encoding="utf-8")))
    return out


def main() -> int:
    # ⚠️ `--check` 只是为了让 `_tools/qa/_check_all.py` **认领**它：
    # 那个总入口的清单是算出来的（`_check_*.py` + 任何声明了 `--check` 的脚本），
    # 而这个脚本两样都不占——于是它**一直不在"每次都要跑"的那一组里**。
    # 它恰恰是抓到过真问题的那一条（文档 § 引用对不上），所以必须进去。
    # 这里刻意**不用 argparse 的位置参数**：带位置参数的脚本会被总入口当成"工具"排掉。
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="总入口用；这条检查本来就是全量校验")
    ap.parse_args()
    # 位置参数（可选）：只校验某一份文档（v2 / v3）
    rest = [a for a in sys.argv[1:] if not a.startswith("-")]
    want = rest[0] if rest else None
    heads = doc_headings()
    guard_src = GUARD.read_text(encoding="utf-8") if GUARD.exists() else ""
    # 红线脚本自己打印的小节标题：print("\n== 2e. 界面文案…")
    guard_sections = set(re.findall(r"==\s*(\d+[a-z]*)\.", guard_src))
    if not guard_sections:
        print("❌ 没能从红线脚本里读出小节号（正则过期？这条检查会变成空转）")
        return 1
    print(f"文档小节 {len(heads)} 个；红线小节 {len(guard_sections)} 个：{sorted(guard_sections)}")

    rc = 0
    for label, path in DOCS.items():
        if want and want != label:
            continue
        if not path.exists():
            print(f"[{label}] 文件不存在：{path}")
            rc = 1
            continue
        t = path.read_text(encoding="utf-8")
        refs = sorted(set(REF.findall(t)))
        bad: list[tuple[str, str]] = []
        kinds = {"doc": 0, "doc-sub": 0, "guard": 0, "guard-sub": 0}
        for r in refs:
            # 后缀两种写法都收：`2f-2b`（横杠 + 编号）与 `6①②`（直接跟圈码）
            m = re.match(r"^(\d+(?:\.\d+)?[a-z]?)(?:-(.+)|([\u2460-\u24ff]+))?$", r)
            if m is None:
                bad.append((r, "§ 后面不是一个编号"))
                continue
            prefix, sub = m.group(1), m.group(2) or m.group(3)
            # ⚠️ 顺序有讲究：`9` 既是文档小节也是红线小节，所以**先按子条目试红线**
            # （`§9-2` 在红线里找不到，就会落到"文档 §9 的第 2 条"这个解释上），
            # 两边都不成立才算对不上。
            if sub is None:
                if prefix in heads:
                    kinds["doc"] += 1
                elif prefix in guard_sections:
                    kinds["guard"] += 1
                else:
                    bad.append((r, "既不是文档小节，也不是红线小节"))
                continue
            if prefix in guard_sections and re.search(
                rf"^\s*#\s*-{{3,}}\s*{re.escape(prefix + '-' + sub)}\b", guard_src, re.M
            ):
                kinds["guard-sub"] += 1
            elif prefix in heads:
                # 文档子条目（"第 X 节的第 n 条"）：只认前缀，正文结构不解析。
                # ⚠️ 这里**只认文档小节号**：`2g-2b` 这种"数字+字母"的前缀不可能是文档小节，
                #    所以它的后缀对不上时必须算红——否则改号之后文档引用会静默失效
                #    （反向验证抓到的：把 `# ---- 2g-2b` 改成 `2g-2c`，它居然还是绿的）。
                kinds["doc-sub"] += 1
            else:
                bad.append((r, "前缀既不是文档小节，也不是红线小节；或是红线子条目的编号对不上"))

        marks = [m.start() for m in RECORD_HEADING.finditer(t)]
        record_zone = t[marks[0]:] if marks else ""

        print(f"\n=== [{label}] {path.name}：{len(t.splitlines())} 行 / {len(t)} 字符 ===")
        print(f"  引用 {len(refs)} 个：文档小节 {kinds['doc']}、文档子条目 {kinds['doc-sub']}、"
              f"红线小节 {kinds['guard']}、红线子条目 {kinds['guard-sub']}")
        if bad:
            print(f"  ❌ **对不上的引用** {len(bad)} 个：")
            for r, why in bad:
                print(f"     §{r} —— {why}")
            rc = 1
        else:
            print("  ✅ 所有 § 引用都能落到文档小节或红线小节上")
        for s in STALE:
            total = t.count(s)
            in_record = record_zone.count(s)
            real = total - in_record
            tag = "OK" if real == 0 else "**真残留**"
            print(f"  {tag:<8} 「{s}」：总 {total}，其中修订记录内 {in_record}")
            if real:
                rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
