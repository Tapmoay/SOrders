"""反向验证「**机器生成的产物是不是过期了**」这条线（2026-09-21，原名 `_reverse_verify_endpoint_index.py`）。

## 为什么这份必须有
"产物过期"这件事**不会自己喊**：生成器只在你手动跑它的时候才写文件，而谁忘了跑、
或者改了源码没重跑，界面上、测试里**一点征兆都没有**。本仓实测撞过两次：

| 什么时候 | 产物 | 后果 |
| --- | --- | --- |
| 2026-09-21 精简轮（四个分类端点各删十几行）| `08A_ENDPOINT_INDEX.md` | **53 处行号过期**，50 个检查全绿放过 |
| 同一轮（给 `ledger.py` 加日期窗口）| `docs/ai/ai_read_catalog.json` + `AiReadCatalog.kt` | 行号漂移（84→109、149→162），**同样全绿** |

所以要证明三件事各自真的会红（本脚本逐条注入）：
1. **端点索引**过期 → `_check_endpoint_index_fresh.py` 报红；
2. **AI 读目录**（两份产物）过期 → `_gen_ai_read_catalog.py --check` 报红；
3. 这两条能被跑到，靠的是 `_check_all.py` 的**发现规则** —— 规则漏了一种写法就等于没有
   （实测：`_gen_ai_read_catalog.py` 用 `"--check" in sys.argv`，而规则只认 argparse，
   于是它**从来没进过必跑清单**）。所以这里连"发现规则"和"`--only` 的下限判据"一起钉。

用法：python _tools/qa/_reverse_verify_generated_artifacts.py    # 全部报红 → 退出码 0
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_endpoint_index_fresh.py"
DOC = ROOT / "docs" / "PROJECT_MAP" / "08A_ENDPOINT_INDEX.md"
GEN_CATALOG = ROOT / "_tools/ai/_gen_ai_read_catalog.py"
CATALOG_JSON = ROOT / "docs/ai/ai_read_catalog.json"
CATALOG_KT = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiReadCatalog.kt"
CHECK_ALL = ROOT / "_tools/qa/_check_all.py"

#: 跑生成器自己的 `--check`（它就是这两份产物的唯一作者）
def run_catalog() -> tuple[int, str]:
    return _run([sys.executable, str(GEN_CATALOG), "--check"])


#: 跑"端点索引是不是过期"那条红线
def run_index() -> tuple[int, str]:
    return _run([sys.executable, str(CHECK)])


#: 只列清单（不跑任何检查）：用来验"发现规则认出它了吗"
def run_list() -> tuple[int, str]:
    return _run([sys.executable, str(CHECK_ALL), "--list"])


#: 窄子集跑一眼（只跑 1 个检查，几秒）：用来验 `--only` 这个开关是不是坏的
def run_narrow_only() -> tuple[int, str]:
    return _run([sys.executable, str(CHECK_ALL), "--only", "ai/_check_role_parity"])


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _bytes(p: Path) -> bytes:
    return p.read_bytes()


#: (说明, 目标文件, 注入函数, 跑什么, 期望输出里的关键词)
CASES: list[tuple[str, Path, object, object, str]] = [
    (
        "索引里一处行号被改错（改完端点没重跑生成器）",
        DOC,
        # 锚整行形状（`| `backend/app/...:90` |`）而不是"第一个 :数字" ——
        # 后者会命中文档里别的地方（日期、:`xxx` 说明），注入就变成改了个无关的字。
        lambda s: re.sub(
            r"(\| `backend/app/[^`]*?):(\d{2,4})`",
            lambda m: f"{m.group(1)}:{int(m.group(2)) + 1}`",
            s,
            count=1,
        ),
        run_index,
        "已经过期",
    ),
    (
        "索引里少了一个端点行（新端点没进地图，或被人手删过）",
        DOC,
        lambda s: "\n".join(
            ln for ln in s.splitlines() if "`POST /api/v1/expense-categories/reorder`" not in ln
        )
        + "\n",
        run_index,
        "已经过期",
    ),
    (
        "AI 读目录（JSON）里一处行号过期（改完后端没重跑生成器）",
        CATALOG_JSON,
        lambda s: re.sub(r'"at": "backend/app/[^"]*?:(\d+)"',
                         lambda m: m.group(0).replace(f":{m.group(1)}\"", f":{int(m.group(1)) + 1}\""),
                         s, count=1),
        run_catalog,
        "产物已过期",
    ),
    (
        "AI 读目录（Kotlin）里一个字段被手改掉（有人直接编辑生成物）",
        CATALOG_KT,
        lambda s: s.replace('val path: String,', 'val pathX: String,', 1),
        run_catalog,
        "产物已过期",
    ),
    (
        "发现规则退回「只认 argparse 的 --check」（AI 读目录那条检查会掉出必跑清单）",
        CHECK_ALL,
        lambda s: s.replace(
            '    return bool(re.search(r\'"--check"\\s+in\\s+sys\\.argv\', code))',
            "    return False",
            1,
        ),
        run_list,
        None,          # 这一条是"**不许**再出现"：注入后清单里不该有它
    ),
    (
        "下限判据退回「看过滤后的清单」（`--only` 会永远报『清单过期了』）",
        CHECK_ALL,
        lambda s: s.replace("if n_plain_all < 8 or n_flag_all < 3:", "if n_plain < 8 or n_flag < 3:", 1),
        run_narrow_only,
        "<FAIL>",      # 注入后这条命令**必须失败**
    ),
]

#: 这两条用的是"注入后**必须看不到/必须失败**"的判据，单独列出它们要找什么。
MUST_VANISH = {
    "发现规则退回「只认 argparse 的 --check」（AI 读目录那条检查会掉出必跑清单）":
        "_gen_ai_read_catalog.py",
}


def main() -> int:
    # 前提：源码完好时，三件事都成立
    code, out = run_index()
    if code != 0:
        print(f"❌ 前提不成立：完好状态下端点索引那条红线就没过\n{out[-800:]}")
        return 1
    code, out = run_catalog()
    if code != 0:
        print(f"❌ 前提不成立：完好状态下 AI 读目录不是最新的\n{out[-800:]}")
        return 1
    code, out = run_list()
    if code != 0 or "_gen_ai_read_catalog.py" not in out:
        print("❌ 前提不成立：完好状态下 `_check_all.py --list` 里找不到 AI 读目录那条检查")
        return 1
    code, out = run_narrow_only()
    if code != 0:
        print(f"❌ 前提不成立：完好状态下 `--only ai/_check_role_parity` 就没过\n{out[-600:]}")
        return 1
    print("✅ 前提：索引与 AI 读目录都是新的，两条检查都在必跑清单里，`--only` 也能用")

    #: 四份会被注入的文件：开跑前各记一份字节，收尾逐字节复核（不是"看起来一样"）。
    WATCHED = [DOC, CATALOG_JSON, CATALOG_KT, CHECK_ALL]
    snapshot = {p: p.read_bytes() for p in WATCHED}

    bad = 0
    for label, target, mutate, runner, expect in CASES:
        raw = _bytes(target)
        original = raw.decode("utf-8")
        # 注入按**换行归一化**的文本做（CRLF 文件上按 `\n` 写锚点会静默失效），
        # 写回时按原样还原（字节级），免得把文件的换行风格翻掉。
        norm = original.replace("\r\n", "\n")
        mutated = mutate(norm)  # type: ignore[operator]
        if mutated == norm:
            print(f"  [MISS] {label} —— 注入没生效（锚点过期，请更新本脚本）")
            bad += 1
            continue
        try:
            target.write_bytes(mutated.encode("utf-8"))
            code, out = runner()  # type: ignore[operator]
        finally:
            target.write_bytes(raw)

        if expect is None:
            gone = MUST_VANISH[label]
            hit = gone not in out or code != 0
            detail = f"「{gone}」已消失/命令非零（code={code}）" if hit else f"「{gone}」还在，判据空转"
        elif expect == "<FAIL>":
            hit = code != 0
            detail = f"命令失败（code={code}）" if hit else "命令照样通过 —— 那条回归没被抓住"
        else:
            hit = code != 0 and expect in out
            detail = f"报出「{expect}」（code={code}）" if hit else f"没报出「{expect}」（code={code}）"
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        bad += 0 if hit else 1

    # 还原检查：四份被碰过的文件必须逐字节回到原样（不是"看起来一样"）
    dirty = [p.relative_to(ROOT).as_posix() for p, b in snapshot.items() if p.read_bytes() != b]
    if dirty:
        print(f"  [MISS] 没还原干净：{'、'.join(dirty)}")
        bad += 1
    else:
        print("  [OK] 四份被注入过的文件都逐字节还原了")
    code, out = run_index()
    code2, out2 = run_catalog()
    if code != 0 or code2 != 0:
        print("  [MISS] 跑完之后红线没恢复（源码或产物没还原干净）")
        bad += 1
    else:
        print("  [OK] 跑完之后端点索引与 AI 读目录都恢复成最新的")

    print()
    if bad:
        print(f"❌ {bad}/{len(CASES)} 条不成立")
        return 1
    print(f"✅ {len(CASES)} 条注入全部成立：产物过期、发现规则漏写法、`--only` 判据错位，都会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
