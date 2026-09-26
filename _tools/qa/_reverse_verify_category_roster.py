"""反向验证 `_check_category_roster.py` 那条判据**真的会红**。

## 为什么要配反向验证
这条判据守的是"名册页的规则与状态机各只有一处"。它的坏法有两种：**判据自己写歪**
（清单写死成几个文件名、正则匹配不上真实写法）→ 恒绿；**只钉住了一半**
（只查"页面里有没有自己写"，不查"搬到的那个共用文件里到底有没有"）→ 页面确实不写了，
而共用文件里那三条规则**一条都不在**，检查照样绿。

| 破坏 | 静默后果 |
|---|---|
| 共用内核的「撤销」退回"只按 `savedOrder` 重建" | 保存之后新建的分类从列表里消失（后端还在，用户以为被删了）——**三页一起坏** |
| 共用内核的提交退回 `categories.map { it.id }` | 名册外的合成行（`id == 0`）被一起发过去 → 后端整批拒绝，而顺序明明是对的 |
| 共用内核的 `dirty` 退回内联比较 | 合成行永远在列表最后 → **保存成功后仍显示"未保存"** |
| 某一页不再继承共用内核（自己拿回那套状态机） | 又会长出第二份状态机（商品页当年那份"就地重刷"就是这么来的） |

## 现场保护（复用公共机制，不另造一套）
· `_airepo.refuse_if_injecting` —— 别人的反向验证正在跑时拒绝出结论；
· `_airepo.lock_reverse_verify` —— 上锁期间并发的**检查**会拒绝出结论；
· `_airepo.take_snapshot` / `restore_snapshot` —— 被杀在半路时的整目录兜底；
· 每个文件另做**逐字节**还原，跑完自检 sha256（一个字节都不能变，换行风格原样带回）。

用法：python _tools/qa/_reverse_verify_category_roster.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import (  # noqa: E402
    lock_reverse_verify,
    refuse_if_injecting,
    repo_root,
    restore_snapshot,
    snapshot_dir,
    take_snapshot,
    unlock_reverse_verify,
)

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_category_roster.py"
UI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui"

BASE = UI / "common/CategoryRosterViewModel.kt"
PRODUCT_VM = UI / "dispatcher/ProductCategoriesViewModel.kt"

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的关键字)
MUTATIONS: list[tuple[str, Path, str, str, str]] = [
    (
        "① 共用内核的「撤销」退回当年那一版（只按 savedOrder 重建 → 三页一起丢新建项）",
        BASE,
        "        val back = revertedOrder(categories, savedOrder, ::idOf)",
        "        val byId = categories.associateBy { idOf(it) }\n"
        "        val back = savedOrder.mapNotNull { byId[it] }",
        "少了「撤销回到已保存顺序且保住新建项」",
    ),
    (
        "② 共用内核的提交退回自己拼编号（名册外的合成行会被一起发过去）",
        BASE,
        "        val ids = submittableIds(categories, ::idOf)",
        "        val ids = categories.map { it.id }",
        "少了「提交只带名册内的行",
    ),
    (
        "③ 共用内核的「改过没有」退回内联比较（保存成功后仍显示未保存）",
        BASE,
        "        dirty = orderChanged(categories, savedOrder, ::idOf)",
        "        dirty = categories.map { it.id } != savedOrder",
        "少了「「改过没有」的判据",
    ),
    (
        "④ 商品页不再继承共用内核（自己拿回那套状态机 → 又会长出第二份）",
        PRODUCT_VM,
        "    CategoryRosterViewModel<ProductCategoryDto>(container) {",
        "    ViewModel() {",
        "继承共用内核的名册页只有",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    if refuse_if_injecting("分类名册反向验证"):
        return 1
    if not CHECK.exists():
        print(f"❌ 找不到 {CHECK}（红线被改名/搬走了？）")
        return 1

    touched = sorted({m[1] for m in MUTATIONS})
    missing = [str(p) for p in touched if not p.exists()]
    if missing:
        print(f"❌ 注入点文件不存在：{missing}")
        return 1
    before = {p: sha(p) for p in touched}

    bad = 0
    lock_reverse_verify()
    try:
        n = take_snapshot()
        print(f"✅ 已上锁并拍快照（{n} 个文件）：这期间不要改源码")

        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条红线就没过\n" + out[-1200:])
            return 1
        print("✅ 前提：源码完好时红线是绿的")

        for label, path, old, new, expect in MUTATIONS:
            raw = path.read_bytes()
            src = raw.decode("utf-8")
            if src.count(old) != 1:
                print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次（判据该更新了）")
                bad += 1
                continue
            path.write_text(src.replace(old, new), encoding="utf-8", newline="")
            try:
                code, out = run_check()
            finally:
                path.write_bytes(raw)          # ★ 逐字节还原（含换行风格）
            fails = [ln.strip() for ln in out.splitlines() if "被破坏" in ln or ln.strip().startswith("- ")]
            got = next((ln for ln in fails if expect in ln), None)
            hit = code != 0 and got is not None
            print(f"  [{'OK' if hit else 'MISS'}] 注入：{label}")
            print(f"         抓它的判据：{got.strip('- ').strip() if got else '（没有任何判据承认这条注入）'}")
            print(f"         退出码 {code}")
            if not hit:
                for f in fails[:4]:
                    print(f"            · {f.strip()}")
                bad += 1

        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        if not ok:
            print(out[-600:])
            bad += 1
    finally:
        unlock_reverse_verify()
        dirty = [str(p.relative_to(ROOT)) for p, h in before.items() if sha(p) != h]
        if dirty:
            print(f"⚠️ 逐字节还原自检失败：{dirty} —— 尝试按快照还原")
            restore_snapshot()
            bad += 1
        else:
            print(f"✅ 逐字节还原自检：{len(before)}/{len(touched)} 个注入点文件与跑之前完全一致")

    print()
    if bad:
        print(f"❌ {bad} 条不成立（红线对它们不敏感，或者现场没还干净）")
        return 1
    print(f"✅ 全部 {len(MUTATIONS)} 种注入都被抓到 + 源码已还原（sha256 一致）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
