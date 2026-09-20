"""一次跑完所有「反向验证」脚本：证明红线检查**真的在检查**，而不是一排恒真的断言。

### 为什么要有这个总入口
红线脚本（`_check_ai_guardrails.py`）现在是 300+ 项，全绿很容易让人放心。
但**全绿本身不说明任何事**——如果某条断言的判据写错了（正则没匹配上、
扫的文件不在列表里、名单过期），它也会"通过"。
这个仓库里已经踩过 5 次这种空转（详见各 `_reverse_verify_*.py` 的开头）。

规矩：**新增一条红线断言，就要有对应的反向验证**（注入 bug → 必须变红）。
这个脚本把散着的几份反向验证合成一条命令，让"我验证过了"有个统一的出口。

用法：
    python _tools/ai/_reverse_verify_all.py                  # 全部（**50 分钟以上**，改红线时才跑）
    python _tools/ai/_reverse_verify_all.py --list            # 只列会跑哪些
    python _tools/ai/_reverse_verify_all.py --only qa         # 只跑某个域（ai / qa / notify / fuzz）
    python _tools/ai/_reverse_verify_all.py --changed         # 只跑「注入目标涉及本次改动文件」的
    python _tools/ai/_reverse_verify_all.py --for backend/app/services/order_return.py

## 为什么要能只跑一部分（2026-09-21）
全量一遍 50 分钟以上，而且跑的时候**一个字都不能改源码**（注入 + 快照 + 还原）。
于是没人跑它 → 注入锚点腐烂（对不上源码就静默跳过）会攒到几十条才发现 ——
本仓实测：随手一撞就是 4 条（见 `_scan_stale_anchors.py` 的说明）。
所以补一条窄路：改哪个域只跑那个域。⚠️ 被杀的三样后果（注入残留 / 注入锁没释放 /
开跑前的快照）写在声明页 §第十二轮，别硬杀。
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import (  # noqa: E402
    extra_files,
    lock_reverse_verify,
    repo_root,
    restore_snapshot,
    take_snapshot,
    unlock_reverse_verify,
)

ROOT = repo_root()
HERE = Path(__file__).resolve().parent

# 反向验证脚本散在多个 `_tools/<域>/` 目录里（ai / qa / notify ...），
# 所以清单**按目录算**而不是只 glob 本目录：只扫 `_tools/ai` 的话，
# 新域里写的反向验证会**永远不跑**（那等于没有）。
def _discover() -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for d in sorted(ROOT.glob("_tools/*/")):
        for p in sorted(d.glob("_reverse_verify_*.py")):
            # ⚠️ 必须排掉**自己**：`_reverse_verify_all.py` 也匹配这个 glob，
            #    收进来就是无限递归（表现为"脚本跑了一小时还没输出"，实测踩到过一次）。
            if p.resolve() == Path(__file__).resolve():
                continue
            found.append((d, p.name))
    return found


SCRIPTS = _discover()
# 清单**自己算**，不手写：手写清单一定会漏（这个仓库栽过 5 次，v3.20 §三.1）。
# 但"自己算"必须配一条数量判据，否则目录被改坏时它会安静地一个都不跑。
# v3.40：新增 `_tools/fuzz/_reverse_verify_fuzz_safety.py`（fuzz 工具自己的安全轨）→ 25
# v3.41：新增 `_tools/qa/_reverse_verify_input_guards.py`（账号/文本上限/中文报错/司机钱完整性）→ 26
# v3.42：新增 `_tools/qa/_reverse_verify_place_and_picker.py`（选品页分类/订单行单位/共享地点库）→ 27
# v3.43：新增 `_tools/qa/_reverse_verify_catalog_and_scope.py`（分类名册/可见白名单/常用地点/提示条）→ 28
# v3.44：新增 `_tools/ai/_reverse_verify_check_blindspots.py`（**检查自己的写法盲区**：跨行字段/单行 lambda）→ 29
# 2026-09-20：新增 `_tools/qa/_reverse_verify_vm_init_order.py`（`init {}` 调用链会写到的状态
#    必须声明在 init 之前 —— 真机崩过：打开「AI 助手 → 设置」NPE）→ 30
MIN_SCRIPTS = 30


def _changed_paths() -> list[str]:
    """本次工作区改动的文件（含未跟踪的），仓库相对路径、用 `/` 分隔。

    `core.quotepath=false` 是必需的：不然中文路径会被 git 转义成 `"\\346\\226\\207..."`，
    与脚本里写的路径对不上，`--changed` 会**安静地选中 0 个**（那种失败最难发现）。
    """
    import subprocess

    out: list[str] = []
    for args in (
        ["git", "-c", "core.quotepath=false", "diff", "--name-only", "HEAD"],
        ["git", "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard"],
    ):
        try:
            r = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            continue
        out += [ln.strip().replace("\\", "/") for ln in (r.stdout or "").splitlines() if ln.strip()]
    return sorted(set(out))


def _select(scripts: list[tuple[Path, str]], *, only: str | None, paths: list[str]) -> list[tuple[Path, str]]:
    """按 `--only` / `--for` / `--changed` 选子集。

    ## 为什么要有它（2026-09-21）
    全量跑一遍要 **50 分钟以上**，而且跑的时候**一个字都不能改源码**（注入 + 快照 + 还原）。
    后果是没人会去跑它 → 注入锚点腐烂（对不上源码就静默跳过）会**攒到几十条**才发现。
    所以给一条窄路：改哪个域就只跑那个域的反向验证（秒级到分钟级），全量留给"改红线时"。

    判据是**从脚本源码里找目标路径字面量**（`--for` / `--changed`）——
    那些脚本本来就是靠字面量改文件的，所以它自己就写着目标路径，不用另外维护映射表。
    """
    if only:
        return [(d, n) for d, n in scripts if only in f"{d.name}/{n}"]
    if paths:
        picked: list[tuple[Path, str]] = []
        for d, n in scripts:
            try:
                src = (d / n).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(p and p in src for p in paths):
                picked.append((d, n))
        return picked
    return list(scripts)


def main() -> int:
    ap = argparse.ArgumentParser(description="一次跑完所有反向验证（可用 --only/--for/--changed 只跑受影响的）")
    ap.add_argument("--only", default=None, help="只跑路径含这个子串的（如 ai / qa / notify / fuzz）")
    ap.add_argument("--for", dest="paths", nargs="*", default=[],
                    help="只跑「注入目标涉及这些文件」的（仓库相对路径，可给多个）")
    ap.add_argument("--changed", action="store_true",
                    help="只跑「注入目标涉及本次改动文件」的（改动清单由 git 现算）")
    ap.add_argument("--list", action="store_true", help="只列会跑哪些，不跑")
    a = ap.parse_args()

    bad = 0
    if any(name == Path(__file__).name for _, name in SCRIPTS):
        # 兜一道：万一上面的过滤被"简化"掉了，这里必须立刻停下来，
        # 而不是开始一场自己跑自己的递归（跑一小时也不会有输出）。
        print(f"❌ 清单里包含自己（{Path(__file__).name}）——会无限递归，停。")
        return 1

    # 选了子集就不套"至少 30 份"那条下限（那是给全量跑用的）；但**子集不能为空** ——
    # 空集意味着"这次什么都没验"，必须当场说清楚，而不是打印一行 ✅。
    filtered = bool(a.only or a.paths or a.changed)
    paths = a.paths
    if a.changed:
        paths = _changed_paths()
        if not paths:
            print("✅ 工作区没有改动（`--changed` 选中 0 个文件）—— 没东西要验，直接通过。")
            return 0
        if not a.paths:
            print(f"本次改动 {len(paths)} 个文件：{'、'.join(paths[:6])}{'…' if len(paths) > 6 else ''}")
    run_list = _select(SCRIPTS, only=a.only, paths=paths if (a.paths or a.changed) else [])
    if filtered and not run_list:
        if a.changed:
            # `--changed` 选中 0 个是**合法答案**（比如只改了文档、或改的文件没有任何反向验证盯着）——
            # 别把它报成"过滤器写错了"，否则人一看到红就去找一个不存在的错。
            print("✅ 本次改动没有涉及任何反向验证的注入目标 —— 没有要验的（这不算失败）。")
            return 0
        print("❌ 选中了 0 份反向验证 —— 过滤器写错了？（`--only` 的子串、`--for` 的路径要")
        print("   与脚本里写的**字面量**一致；改动的是新文件时也可能确实一份都不涉及）。")
        return 1
    if not filtered and len(SCRIPTS) < MIN_SCRIPTS:
        print(f"❌ 只找到 {len(SCRIPTS)} 份反向验证（至少应有 {MIN_SCRIPTS} 份）——目录被动过？")
        return 1

    if a.list or filtered:
        scope = f"（子集：{len(run_list)}/{len(SCRIPTS)} 份）" if filtered else f"（全部 {len(run_list)} 份）"
        print(f"会跑这些反向验证{scope}：")
        for d, n in run_list:
            print(f"   {d.name}/{n}")
        if a.list:
            return 0
        print()

    return _run(run_list)


def _run(scripts: list[tuple[Path, str]]) -> int:

    # 每次注入都是"改源码 → 跑检查 → 改回来"。被杀在半路就会把注入的 bug 留在树里，
    # 下一次红线会报出一堆**真实的**失败，看起来像"我刚改坏了"。
    # 所以在开始之前先拍快照：跑完比对还原，被杀也有 `_recover_injections.py` 兜底。
    n = take_snapshot()
    # 再上一把锁，并且**在这里把话说清楚**：
    #   · 并发的检查会拒绝出结论（`_airepo.refuse_if_injecting`）；
    #   · ⚠️ 但**没有任何机制能拦住"人一边跑它一边改源码"**——跑完 `restore_snapshot()`
    #     会按**开跑前的快照**把那些改动一起写回去，并发做的修改就静默没了
    #     （2026-09-19 实测被抹掉 15 个文件，包括刚写好的红线与新注入）。
    #     所以：跑这个的时候，手离开编辑器。
    lock_reverse_verify()
    print(f"（已快照 {n} 个文件；若这次跑被中断，事后用 _recover_injections.py 还原现场）")
    print("⚠️ 跑这个的时候**不要改源码**：跑完会按开跑前的快照写回，并发改动会被一起抹掉。\n")

    try:
        return _run_all(scripts)
    finally:
        unlock_reverse_verify()


def _run_all(scripts: list[tuple[Path, str]]) -> int:
    bad = 0
    for d, name in scripts:
        p = d / name
        if not p.exists():
            # ⚠️ 不许静默跳过：脚本被删/改名时，这一行必须报出来
            print(f"❌ 找不到 {name}（反向验证不见了？）")
            bad += 1
            continue
        t0 = time.monotonic()
        r = subprocess.run(
            [sys.executable, str(p)], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        spent = time.monotonic() - t0
        out = (r.stdout or "") + (r.stderr or "")
        tail = [ln.strip() for ln in out.splitlines() if ln.strip().startswith(("✅", "❌"))]
        mark = "✅" if r.returncode == 0 else "❌"
        summary = tail[-1] if tail else (out.strip().splitlines() or ["(无输出)"])[-1]
        print(f"{mark} {name}（{spent:.1f}s）: {summary}")
        if r.returncode != 0:
            bad += 1
            for ln in out.splitlines():
                if "[MISS]" in ln or "[SKIP]" in ln:
                    print("     " + ln.strip())

    # 收尾：把快照与现场对一遍（正常情况下一个都不差）。
    fixed = restore_snapshot()
    extra = extra_files()
    if fixed:
        print(f"\n⚠️ 有 {len(fixed)} 个文件没还原干净，已按快照写回：{'、'.join(fixed)}")
    if extra:
        print(f"⚠️ 现场多了这些文件（可能是注入留下的，请自己看一眼）：{'、'.join(extra)}")
    print()
    n = len(scripts)
    if bad:
        print(f"❌ {bad}/{n} 份反向验证不达标——那些红线现在是**恒真的**，不算检查。")
        return 1
    print(f"✅ {n}/{n} 份反向验证全部达标：每条红线都证明过「注入 bug 会变红」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
