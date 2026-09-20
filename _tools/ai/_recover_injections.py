"""把反向验证"没跑完就死掉"留下的现场还原回去。

### 什么时候需要跑它
`_reverse_verify_*.py` 的工作方式是**改源码 → 跑红线 → 把源码改回来**。
被杀在半路（Ctrl+C / 超时 / 后台任务被 kill）时，"改回来"那一步不会执行，
于是**注入的 bug 就留在源码树里**——下一次跑红线会报出一堆真实的失败，
看起来像"我刚改坏了"。2026-09-16 实测踩到过一次：`Modules.kt` 里多了两个 AI 入口。

`_reverse_verify_all.py` 现在会在开跑前把会被注入的目录快照到临时目录，
跑完自动比对还原。快照还在 = 上一次没跑完 → 这个脚本就是干这个的。

用法：
    python _tools/ai/_recover_injections.py            # 还原（没有快照就什么都不做）
    python _tools/ai/_recover_injections.py --status    # 只看有没有遗留现场
"""
import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import extra_files, restore_snapshot, snapshot_dir, unlock_reverse_verify  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="只看有没有遗留现场，不改动")
    args = ap.parse_args()

    snap = snapshot_dir()
    if not snap.is_dir():
        print("✅ 没有遗留现场（临时快照不存在 = 上一次反向验证跑完了）")
        return 0
    print(f"⚠️ 发现遗留现场：{snap}")
    print("   意思是上一次反向验证**没跑完**（被杀/超时），源码里可能还留着注入的 bug。")

    if args.status:
        extra = extra_files()
        if extra:
            print(f"   现场比快照多的文件（{len(extra)}）：{'、'.join(extra)}")
        return 1

    # ⚠️ **还要清掉那把注入锁**（2026-09-21 实测踩到）：反向验证开跑时会写一把锁
    #    （`_airepo.LOCK`），被 kill 时 `finally` 里的 `unlock_reverse_verify()` **不会执行** ——
    #    于是接下来**所有检查都会拒绝出结论**（"源码是注入状态，给不出可信结论"），
    #    最长卡 30 分钟（`LOCK_STALE_SECONDS`）。我那次的实际现场是：
    #    **文件都已经还原干净了，锁还在**，于是 `_check_all.py` 一直报"拒绝出结论"。
    #    判据：只有在"确实发现了遗留快照"这条路径上才清（＝上一次真的没跑完），
    #    免得把**正在跑**的那一次反向验证的锁误删（那会让并发的检查去读注入过的源码）。
    unlock_reverse_verify()
    print("   已清掉注入锁（否则接下来最长 30 分钟内所有检查都会拒绝出结论）。")

    # ⚠️ 顺序要紧：**先**看"多出来的文件"（还原会把快照删掉，之后就比不了了）
    extra = extra_files()
    fixed = restore_snapshot()
    if fixed:
        print(f"\n已还原 {len(fixed)} 个被改动的文件：")
        for f in fixed:
            print(f"  {f}")
    else:
        print("\n没有文件内容不一致（快照与现场相同），只清掉了快照。")
    if extra:
        print(
            f"\n⚠️ 现场还有 {len(extra)} 个快照里没有的文件（**没有自动删**——"
            "万一是你刚加的，删了就找不回来了，请自己看一眼）："
        )
        for f in extra:
            print(f"  {f}")
    print("\n接下来重跑一遍：python _tools/ai/_check_ai_guardrails.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
