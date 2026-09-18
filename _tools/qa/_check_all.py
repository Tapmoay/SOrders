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


def declares_check_flag(p: Path) -> bool:
    """这个脚本声明了 `--check` 吗（自己从源码里看，不手写清单）。"""
    try:
        src = io.open(p, encoding="utf-8", errors="replace").read()
    except OSError:
        return False
    return bool(re.search(r'add_argument\(\s*"--check"', src))


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
    a = ap.parse_args()

    # ⚠️ 反向验证跑着的时候，源码树里带着**注入的 bug**，此时跑任何检查都会得到
    # "一堆真实但无关的失败"——而人的第一反应是"我刚改坏了什么"。
    # 实测踩到过一次（红线报「没找到 def test_边长值被接受」，那个文件正被临时改名）。
    if refuse_if_injecting("这轮检查"):
        return 1

    run, notes = discover()
    if a.deep:
        rv = TOOLS / "ai" / "_reverse_verify_all.py"
        if rv.exists():
            run.append(("deep", rv, []))
    if a.only:
        run = [(g, p, args) for g, p, args in run if a.only in str(p.relative_to(ROOT))]

    n_plain = sum(1 for g, _, _ in run if g == "check")
    n_flag = sum(1 for g, _, _ in run if g == "--check")
    print(f"共 {len(run)} 个检查脚本（`_check_*.py` {n_plain} 个 + 带 `--check` 的 {n_flag} 个）")
    for n in notes:
        print("  " + n)
    for g, p, args in run:
        print(f"  [{g}] {p.relative_to(ROOT)}" + (" " + " ".join(args) if args else ""))
    if a.list:
        return 0

    # 数量判据：清单过期（改名/搬目录）时先喊，而不是安静地少跑一半。
    if n_plain < 8 or n_flag < 3:
        print(f"\n❌ 只认出 {n_plain} 个 `_check_*.py` / {n_flag} 个 `--check` 脚本——"
              f"清单过期了（脚本改名或搬走了？）。这条命令的意义就是**不许漏跑**，停。")
        return 1

    print()
    bad: list[tuple[str, str]] = []
    for g, p, args in run:
        rel = str(p.relative_to(ROOT))
        t0 = time.time()
        r = subprocess.run(
            [sys.executable, str(p), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
        )
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
