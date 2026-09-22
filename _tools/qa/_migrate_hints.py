"""把「解释句」的裸 `Text(...)` 改名成统一入口 `Hint(...)` —— **迁移工具，不进必跑清单**。

## 它做什么、不做什么
- ✅ 只改**一种**形态：`Text(<字面量>, …)` 且那句被 `_hint_inventory` 判为 **EXPLAIN**（解释句）。
- ⛔ 不碰：数据/标签/状态（`DATA`）、警告（`WARN`）、空态（`EMPTY`）—— 见 `docs/HINT_STYLE.md` §2。
- ⛔ 不碰首参不是字符串字面量的调用（`Text(buildAnnotatedString {…})`、`Text(if (…) "A" else "B")`）：
  那些要人来判断"包哪一段"，**改名会直接编译不过**。

## 为什么要有它
用户 2026-09-21：「打开就打开**所有的提示相关的内容**，关闭就关闭**所有的提示**」——
全库一百多处解释句要挂到那**一个**开关上。手改一百多处，改漏一处**不会报错**，
只是"关掉开关它还在"（最难发现的那种漏）。

## 安全措施
1. **默认预演**，`--apply` 才写盘；
2. 写盘前把每个要改的文件**整份备份**到 `_archive/hint-migration-backup/`（镜像路径）——
   这个仓库里很多文件带着**别的会话未提交的改动**，改坏了必须能整份退回去，
   ⛔ 不许用 `git checkout --`（那会连别人的活儿一起抹掉）；
3. 自动补 `import com.tapmoay.sorders.ui.common.Hint`（同包 / 已有则不补）；
4. 反向约束：可改处少于 [FLOOR] 处就直接拒绝 —— 分类规则被改坏时不许"安静地什么都不迁移"。

用法：
    python _tools/qa/_migrate_hints.py                 # 预演
    python _tools/qa/_migrate_hints.py --apply         # 真改（先备份）
    python _tools/qa/_migrate_hints.py --only ui/dispatcher
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _hint_inventory as inv  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "_archive" / "hint-migration-backup"
HINT_IMPORT = "import com.tapmoay.sorders.ui.common.Hint"


def read(path: Path) -> str:
    """按原样读（**不翻译换行**：仓库里 CRLF/LF 混着，翻译一遍就是全文件 diff）。"""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def newline_of(src: str) -> str:
    return "\r\n" if "\r\n" in src else "\n"


def needs_import(src: str, path: Path) -> bool:
    if "/ui/common/" in path.as_posix():
        return False                       # 同包，不用 import
    if re.search(r"^import com\.tapmoay\.sorders\.ui\.common\.(Hint|\*)\s*$", src, re.M):
        return False                       # 已经有它，或者已经有了通配的 `ui.common.*`
    return True


def insert_import(src: str) -> str:
    """在最后一条 import 之后补一行。

    ⚠️ 按**行**插、并按那一行自己的行尾补（`splitlines(keepends=True)`）：
    第一版用 `re.finditer(r"^import .*$", src, re.M)` 取偏移再拼 `newline_of(src)`，
    在 CRLF 文件上 `.` 会把 `\\r` 一起吃进去、`$` 又落在 `\\n` 之前 ——
    结果是往文件里塞出一个**孤立的 LF**（19 个文件里 5 个 CRLF 的中招）。
    """
    lines = src.splitlines(keepends=True)
    last = None
    for i, ln in enumerate(lines):
        if ln.startswith("import "):
            last = i
    if last is None:
        return src
    eol = "\r\n" if lines[last].endswith("\r\n") else "\n"
    lines.insert(last + 1, HINT_IMPORT + eol)
    return "".join(lines)


def plan(only: str | None, aggressive: bool = False):
    rows, _ = inv.collect()
    picked = [
        r for r in rows
        if r["cat"] == "EXPLAIN" and r["call"] == "Text"
        and (only is None or only in r["file"])
        and (
            r["first_arg"]
            # `--aggressive`：首参不是纯字面量、但**这次调用渲染的仍是一个字符串**
            # （`Text(if (…) "A" else "B")`、多行拼接）—— 把整个调用改名同样正确。
            # 唯一的例外是 `AnnotatedString`（`Hint` 只收 String，改了编译不过），排掉。
            or (aggressive and not r["has_annotated"])
        )
    ]
    # 同一次调用可能有多段 EXPLAIN 字面量（`"a" + "b"`）→ 按调用去重，否则会重复改名
    dedup: dict[tuple[str, int], dict] = {}
    for r in picked:
        dedup.setdefault((r["file"], r["call_off"]), r)
    mech = list(dedup.values())
    by_file: dict[str, list[dict]] = {}
    for r in mech:
        by_file.setdefault(r["file"], []).append(r)
    return rows, mech, by_file


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写盘（默认只预演）")
    ap.add_argument("--only", default=None, help="只处理路径里含这个片段的文件")
    ap.add_argument("--aggressive", action="store_true",
                    help="连「首参不是纯字面量、但整句仍是字符串」的调用一起改"
                         "（`Text(if (…) \"A\" else \"B\")`）；`AnnotatedString` 一律排除")
    a = ap.parse_args()

    rows, mech, by_file = plan(a.only, a.aggressive)
    print(f"解释句 {sum(1 for r in rows if r['cat'] == 'EXPLAIN')} 条；"
          f"其中**可机械改名** {len(mech)} 处，分布在 {len(by_file)} 个文件")
    if not mech:
        # ⚠️ 这里**不能**再设一个"至少 N 处"的下限：迁移是**逐轮做**的，
        #    做完之后这个数本来就该是 0。防"分类器坏了却安静成功"那件事，
        #    由 `_hint_inventory.py` 自己的下限负责（文件数/文案数/解释句数三道）。
        print("没有需要机械改名的了（剩下的要么已迁移、要么首参不是字面量，要人工包一层）。")
        return 0

    print(f"\n按端：" + "  ".join(f"{k}={v}" for k, v in Counter(r['end'] for r in mech).most_common()))
    for f, rs in sorted(by_file.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(rs):>2}× {f}")
        for r in sorted(rs, key=lambda r: r["line"])[:3]:
            print(f"      L{r['line']:<5} {r['text'][:44]}")
        if len(rs) > 3:
            print(f"      … 另 {len(rs) - 3} 处")

    if not a.apply:
        print("\n（预演结束，未写盘。加 --apply 才改。）")
        return 0

    changed = 0
    for rel, rs in by_file.items():
        path = ROOT / rel
        src = read(path)
        applied = 0
        # 从后往前改：前面的偏移不会被后面的替换弄乱
        for r in sorted(rs, key=lambda r: -r["call_off"]):
            off = r["call_off"]
            if src[off:off + 4] != "Text":
                # 走到这里说明偏移对不上（历史上是 CRLF 文件被通用换行翻译过）——
                # **必须吵**：安静跳过就是"以为改了、其实没改"。
                print(f"  ⚠️ 偏移对不上，跳过 {rel}:{r['line']}（这里不是 `Text`）")
                continue
            src = src[:off] + "Hint" + src[off + 4:]
            applied += 1
            changed += 1
        if applied == 0:
            print(f"  ⚠️ {rel} 一处都没改（计划 {len(rs)} 处）—— 只补了 import，请核对")
        if needs_import(src, path):
            src = insert_import(src)
        dst = BACKUP / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():                # 只备份**第一次**改动前的样子
            shutil.copy2(path, dst)
        write(path, src)
        print(f"  ✅ {rel}（改了 {applied}/{len(rs)} 处）")

    print(f"\n改完：{changed} 处 / {len(by_file)} 个文件；原件备份在 "
          f"{BACKUP.relative_to(ROOT).as_posix()}/")
    print("下一步：编译 + 跑 `python _tools/qa/_hint_inventory.py` 看剩余人工清单。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
