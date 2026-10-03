# -*- coding: utf-8 -*-
"""反向验证「沽清 / 上架二次确认」这条红线**真的会红**（CHG-0025 / P29）。

## 为什么这条要反向验证
它的判据大多是"某个文件里必须出现某个零件 / 某句话"与"某个入口不许直接改"，
这类判据有三种典型失效方式，每一种都必须被单独证明会红：

1. **判据变成空转**：弹层被改名 / 搬走之后，判据会安静地全绿 —— 本脚本把定义改名，
   必须报红（**0 处也红**）。
2. **只认"有人用"、不认"入口在哪"**：弹层还在，但页面又留了一条一点即改的入口
   （onToggle = { vm.toggleActive(p) }）。整个文件扫的话照样绿，而用户点一下就已经改完了。
3. **文案复制**：同一个后果在单卡与批量各写一句 —— 判据只扫一个文件的话永远看不出这件事。

另外几条打判据自己：确认钮文案不再跟着方向走、沽清那支的后果被删掉、
批量页的勾选闸被拿掉，以及**判据自己的 REVERSE 常量被改名**（自指用例）。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_product_active_confirm.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_product_active_confirm.py"
CHECK_REL = "_tools/qa/_check_product_active_confirm.py"

#: Windows 上 Kotlin 文件可能是 CRLF：按字节快照、归一后再替换、写回时按原样还原
CR = bytes((13,))
LF = bytes((10,))
CRLF = CR + LF

#: 弹层的名字（与判据里的 DIALOG 同名；改名这条红线就该红）
DIALOG_NAME = "ProductActiveConfirmDialog"

KIT = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductCardKit.kt"
LIST = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductsScreen.kt"
BATCH = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductBatchScreen.kt"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 商品管理页：卡片入口改回一点即改 onToggle = { vm.toggleActive(p) }（P29 原样复发）",
        LIST,
        lambda s: s.replace(
            "onToggle = { toggleFor = p },",
            "onToggle = { vm.toggleActive(p) },",
            1,
        ),
        "一点即改",
    ),
    (
        "② 商品管理页：弹层还在 KIT 里，但这一页不叫它了（定义在、没人用）",
        LIST,
        lambda s: s.replace(f"{DIALOG_NAME}(", f"{DIALOG_NAME}Old(", 1),
        "这一页没用共用弹层",
    ),
    (
        "③ 批量操作页：沽清胶囊绕开弹层直接改（vm.setActive( 又跑回动作区）",
        BATCH,
        lambda s: s.replace(
            'ActionChip("沽清（下架）", vm.acting) { if (vm.canAct()) confirmingActive = false }',
            'ActionChip("沽清（下架）", vm.acting) { vm.setActive(false) }',
            1,
        ),
        "canAct()",
    ),
    (
        "④ 弹层被改名（判据不许因为零件改名而空转：0 处也红）",
        KIT,
        lambda s: s.replace(f"fun {DIALOG_NAME}(", f"fun {DIALOG_NAME}Old(", 1),
        "只有一处定义",
    ),
    (
        "⑤ 后果那句话被抄进商品管理页（单卡与批量各写一句，下次改口径必漏一页）",
        LIST,
        lambda s: s.replace(
            'subject = "「" + p.name + "」",',
            'subject = "「" + p.name + "」" + "库存、订单、账本都不动",',
            1,
        ),
        "全库只有一份",
    ),
    (
        "⑥ 沽清那支的后果被删掉（弹层还在问，但没告诉用户会发生什么）",
        KIT,
        lambda s: s.replace("；库存、订单、账本都不动，", "。", 1),
        "全库只有一份",
    ),
    (
        "⑦ 批量操作页：勾选闸被拿掉（一个都没勾也能弹层，还写成「选中的 0 个商品」）",
        BATCH,
        lambda s: s.replace(
            "{ if (vm.canAct()) confirmingActive = false }",
            "{ confirmingActive = false }",
            1,
        ),
        "canAct()",
    ),
    (
        "⑧ 确认钮文案不再跟着方向走（两个方向共用一个「沽清」）",
        KIT,
        lambda s: s.replace('if (toActive) "上架" else "沽清"', '"沽清"', 1),
        "确认钮文案",
    ),
    (
        "⑨ 判据自己的 REVERSE 常量被改名（防它指向一个不存在的脚本还照样绿）",
        CHECK_REL,
        lambda s: s.replace(
            'REVERSE = "_tools/qa/_reverse_verify_product_active_confirm.py"',
            'REVERSE = "_tools/qa/_reverse_verify_product_active_confirm_gone.py"',
            1,
        ),
        "反向验证",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = CRLF in original_bytes
        plain = original_bytes.decode("utf-8").replace(CRLF.decode(), LF.decode())
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated
            if crlf:
                out_txt = out_txt.replace(LF.decode(), CRLF.decode())
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"  [OK] {label} → 报红")
        else:
            fails.append(f"{label}：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print(f"  [MISS] {label} → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
