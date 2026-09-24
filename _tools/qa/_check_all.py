"""**一条命令跑完所有静态检查**（v3.44）。

### 为什么要有它
这一轮抓到的问题正好说明了缺什么：`_app_feature_coverage.py --check` 已经红了
（三个 AI 能力没被任何 App 模块认领 = "能力白做了"），但**没人跑它** ——
上一轮的收尾清单是手写的四项，而它不在里面。于是那条红线红了一整轮没人知道。

"永远红的检查 = 没有检查"这条教训本项目已经写进红线 §15（`_ai_doc_check.py` 红了 12 轮），
同一个坑换个地方又踩了一次。根因不是"忘了跑"，而是**清单是手写的**。

### 口径（两个清单都是**算出来的**，不手写）
1. `_tools/*/_check_*.py` → 直接跑（无参数）；
2. `_tools/*/*.py` 里**声明了 `--check`** 的 → 用 `--check` 跑。
   第二类的意义：新写一个检查脚本，只要给它加一个 `--check`（几乎所有检查都该有），
   它就**自动进这条命令**，不需要谁记得来改这里。

再配两条数量判据：两类各自的数量低于下限就报错（脚本被改名/搬走时先喊，
而不是安静地少跑一半）。

用法：
    python _tools/qa/_check_all.py            # 全部跑一遍（几分钟）
    python _tools/qa/_check_all.py --list     # 只列清单，不跑
    python _tools/qa/_check_all.py --only ai  # 只跑路径里含 ai 的
"""
import argparse
import io
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402

ROOT = repo_root()
TOOLS = ROOT / "_tools"

# 这两个脚本**自己不跑自己**（会递归），也跑不动别人跑别人。
SKIP = {"_check_all.py", "_reverse_verify_all.py"}
# 反向验证要几分钟，默认不跑（它证明的是"红线真的在检查"，改动红线时才需要）。
DEEP_ONLY = {"_reverse_verify_all.py"}


def _code_only(src: str) -> str:
    """去掉 Python 的注释与文档字符串（判据只看**代码**，不看我们自己的说明文字）。

    ⚠️ 不剥的话，发现规则会被**散文**骗过去：`_reverse_verify_generated_artifacts.py` 的
    docstring 里写了一句"实测：某某脚本用 `"--check" in sys.argv`"（那是在**说明**
    `--check` 的另一种写法），结果它自己被当成"声明了 --check 的脚本"捡进了必跑清单 ——
    52/52 里那一格就是它（实测踩到）。与仓库里"裸子串会被兄弟文案满足"是同一类毛病：
    **判据必须锚在代码上**。
    """
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    return re.sub(r"^[ \t]*#.*$", "", src, flags=re.M)


def declares_check_flag(p: Path) -> bool:
    """这个脚本声明了 `--check` 吗（自己从源码里看，不手写清单）。

    ⚠️ **两种写法都要认**（2026-09-21 修的真实漏洞）：`argparse` 的
    `add_argument("--check")`，以及更省事的 `"--check" in sys.argv`。
    只认前者的后果实测过一次：`_tools/ai/_gen_ai_read_catalog.py` 用的是后者，
    于是它**从来没进过必跑清单** —— 而它生成的两份产物（`docs/ai/ai_read_catalog.json` +
    `AiReadCatalog.kt`）会随源码行号漂移，**50 个检查全绿也发现不了**。
    教训与"清单是手写的"同一个形状：**发现规则本身也是一份判据，它漏了就等于没有**。
    """
    try:
        src = io.open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    code = _code_only(src)
    if re.search(r'add_argument\(\s*"--check"', code):
        return True
    return bool(re.search(r'"--check"\s+in\s+sys\.argv', code))


def needs_positional_arg(p: Path) -> bool:
    """这个脚本要一个**位置参数**吗（`_check_order.py <单号>`）＝ 它是**工具**，不是检查。

    为什么必须排掉：这类脚本不带参数跑只会打印一行"用法：…"然后非零退出，
    混进这条命令里会让"20/21 通过"变成噪音——而**常年带两条噪音红的检查等于没有检查**
    （本项目 §15 的教训）。三种写法都算（从源码算，不手写名单）：
      · `add_argument("名字")` 里不以 `-` 开头的；
      · `if len(sys.argv) < 2: … return 2`（这对脚本就是这么写的）；
      · 直接读 `sys.argv[1]`。
    """
    try:
        src = io.open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    for m in re.finditer(r'add_argument\(\s*"([^"]+)"', src):
        if not m.group(1).startswith("-"):
            return True
    return bool(re.search(r"len\(sys\.argv\)\s*<\s*2", src) or re.search(r"sys\.argv\[1\]", src))


def discover() -> tuple[list[tuple[str, Path, list[str]]], list[str]]:
    """返回 (要跑的清单, 备注)。清单 = (组名, 路径, 参数)。"""
    run: list[tuple[str, Path, list[str]]] = []
    notes: list[str] = []
    for d in sorted(p for p in TOOLS.glob("*") if p.is_dir()):
        for p in sorted(d.glob("*.py")):
            if p.name in SKIP:
                notes.append(f"（跳过 {p.name}：会递归）")
                continue
            if p.name in DEEP_ONLY:
                continue
            if p.name.startswith("_check_"):
                if needs_positional_arg(p):
                    notes.append(f"（跳过 {p.name}：要位置参数，它是工具不是检查）")
                    continue
                run.append(("check", p, []))
            elif declares_check_flag(p):
                run.append(("--check", p, ["--check"]))
    return run, notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--deep", action="store_true", help="连反向验证一起跑（几分钟）")
    ap.add_argument("--timeout", type=int, default=300,
                    help="每个检查的超时秒数（默认 300；0 = 不限）—— 报告 §20 第 ⑩ 项")
    a = ap.parse_args()

    # ⚠️ 反向验证跑着的时候，源码树里带着**注入的 bug**，此时跑任何检查都会得到
    # "一堆真实但无关的失败"——而人的第一反应是"我刚改坏了什么"。
    # 实测踩到过一次（红线报「没找到 def test_边长值被接受」，那个文件正被临时改名）。
    if refuse_if_injecting("这轮检查"):
        return 1

    run_all, notes = discover()
    if a.deep:
        rv = TOOLS / "ai" / "_reverse_verify_all.py"
        if rv.exists():
            run_all.append(("deep", rv, []))

    # ⚠️ **下限判据必须看全量清单**（2026-09-21 修）：`--only <子串>` 是"挑着跑"，
    #    而下面那两条 8/3 的下限是"清单是不是过期了"的判据。原来先按 `--only` 过滤、再算数量，
    #    于是**任何**子集都会掉到下限之下 → `--only` 永远报"清单过期了"、等于这个开关是坏的
    #    （实测：`--only gen_ai_read_catalog` 只选中 1 个 → 当场非零退出）。
    #    正确的关系是：**下限管全量，`--only` 只影响这次跑哪些**。
    n_plain_all = sum(1 for g, _, _ in run_all if g == "check")
    n_flag_all = sum(1 for g, _, _ in run_all if g == "--check")
    if n_plain_all < 8 or n_flag_all < 3:
        print(f"\n❌ 只认出 {n_plain_all} 个 `_check_*.py` / {n_flag_all} 个 `--check` 脚本——"
              f"清单过期了（脚本改名或搬走了？）。这条命令的意义就是**不许漏跑**，停。")
        return 1

    run = run_all
    if a.only:
        # ⚠️ 用 `as_posix()`：Windows 上 `str(Path)` 是 `_tools\qa\x.py`，而人写子串时用 `/`
        #    （文档里也是这么写的）→ 不归一化的话 `--only qa/_check_dead_code` 会安静地选中 0 个。
        run = [(g, p, args) for g, p, args in run_all if a.only in p.relative_to(ROOT).as_posix()]
        if not run:
            print(f"❌ `--only {a.only}` 一份都没选中（全量清单里有 {len(run_all)} 份）——子串写错了？")
            return 1

    n_plain = sum(1 for g, _, _ in run if g == "check")
    n_flag = sum(1 for g, _, _ in run if g == "--check")
    scope = f"；`--only {a.only}` 的子集（全量 {len(run_all)} 份）" if a.only else ""
    print(f"共 {len(run)} 个检查脚本（`_check_*.py` {n_plain} 个 + 带 `--check` 的 {n_flag} 个）{scope}")
    for n in notes:
        print("  " + n)
    for g, p, args in run:
        print(f"  [{g}] {p.relative_to(ROOT)}" + (" " + " ".join(args) if args else ""))
    if a.list:
        return 0

    print()
    bad: list[tuple[str, str]] = []
    for g, p, args in run:
        rel = str(p.relative_to(ROOT))
        t0 = time.time()
        # ⛔ **每个检查都要有超时**（报告 §20 第 ⑩ 项）：没有它，任何一个会挂住的检查
        #    （等 stdin、等网络、等锁）都会让这条命令**永远不返回** —— 而它正是「改完必跑」的那条。
        #    超时按**失败**记账、并且继续跑后面的人：一次跑完看全貌，比卡在第一个更有用。
        try:
            r = subprocess.run(
                [sys.executable, str(p), *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
                timeout=(a.timeout or None),
            )
        except subprocess.TimeoutExpired:
            dt = time.time() - t0
            msg = (f"超时（>{a.timeout}s）——这个检查挂住了；先用 python "
                   f"{p.relative_to(ROOT).as_posix()} 单独跑一次看它卡在哪")
            print(f"❌ {rel:52s} {dt:5.1f}s  {msg[:90]}")
            bad.append((rel, msg))
            continue
        dt = time.time() - t0
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        tail = [ln.strip() for ln in out.splitlines() if ln.strip()]
        summary = tail[-1] if tail else "(无输出)"
        mark = "✅" if r.returncode == 0 else "❌"
        print(f"{mark} {rel:52s} {dt:5.1f}s  {summary[:90]}")
        if r.returncode != 0:
            bad.append((rel, out))

    print()
    if bad:
        print(f"❌ {len(bad)}/{len(run)} 个检查没通过：")
        for rel, out in bad:
            print(f"\n===== {rel} =====")
            for ln in out.splitlines()[-25:]:
                print("  " + ln)
        return 1

    # 最后一条：**这条命令自己有没有被人知道**。
    # 检查写得再全，没人跑就等于没有检查——本项目已经栽过一次
    # （`_app_feature_coverage.py --check` 红了一整轮，因为收尾清单是手写的、它不在里面）。
    # 所以把它钉进 AGENTS.md（每个新会话都会自动加载的那个文件）。
    agents = ROOT / "AGENTS.md"
    txt = agents.read_text(encoding="utf-8") if agents.exists() else ""
    if "_check_all.py" not in txt:
        print("❌ AGENTS.md 里没有提到 `_check_all.py` —— 新会话不会知道要跑它，"
              "这条命令就等于不存在（请在 AGENTS.md 里加一行）。")
        return 1
    print(f"✅ {len(run)}/{len(run)} 个检查全部通过（并且 AGENTS.md 里写了要跑它）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
