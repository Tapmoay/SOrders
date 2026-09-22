"""反向验证「init 调用链会写到的状态必须声明在 init 之前」这条红线**真的会红**。

## 为什么要单独一份
这条红线的判据是"解析 init 块 → 找它调用的函数 → 收集函数体里的赋值 → 比对声明位置"，
它有三种典型失效方式，每一种都要单独证明会红：

1. **状态被挪回 init 之后**（真机崩过的那个形状）：判据必须报出"这一页打开就崩"；
2. **init 里新写一个声明在后面的状态**（新加代码时最容易犯的那个）：同上；
3. **判据自己空转**：把"扫到的文件数下限"抬到不可能满足时，脚本必须**自己喊**
   （而不是安静地 0 个问题 → 全绿）。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_vm_init_order.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_vm_state_before_init.py"
CHECK_REL = "_tools/qa/_check_vm_state_before_init.py"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiSettingsViewModel.kt"
LEDGER_VM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherLedgerViewModel.kt"

INIT_BLOCK = "    init {\n        load()\n    }\n"

#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "把 costVisible 挪回 init 之后（真机崩过的那个形状：打开设置页必崩）",
        VM,
        lambda s: re.sub(
            r"\n    /\*\*\n     \* 「允许 AI 查看成本与毛利」.*?\n    var costVisible by mutableStateOf\(false\)\n",
            "\n",
            s,
            count=1,
            flags=re.S,
        ).replace(
            INIT_BLOCK,
            INIT_BLOCK + "\n    var costVisible by mutableStateOf(false)\n",
            1,
        ),
        "costVisible",
    ),
    (
        "init 里新写一个声明在后面的状态（以后加代码时最容易犯的）",
        VM,
        lambda s: s.replace(
            INIT_BLOCK,
            INIT_BLOCK + "\n    var probeFlag by mutableStateOf(false)\n",
            1,
        ).replace(
            "    fun load() {\n",
            "    fun load() {\n        probeFlag = true\n",
            1,
        ),
        "probeFlag",
    ),
    (
        "判据自己空转：把「扫到的文件数下限」抬到不可能满足（脚本必须自己喊，而不是 0 问题全绿）",
        CHECK_REL,
        lambda s: s.replace("MIN_FILES = 60", "MIN_FILES = 100000", 1),
        "太少",
    ),
    (
        "init 调一个**带参数**的方法，而那个方法（隔一层）写到声明在后面的状态"
        "—— 老判据只跟无参调用、只看直接调用的那一个函数体，这就漏了（2026-09-20 真机又崩一次）",
        LEDGER_VM,
        # ⚠️ 锚点跟着实现走（2026-09-23 静态审计抓到它已腐烂）：账本 VM 的 init 后来改成
        #    "先盘点、再取数"（`switchPreset(DatePresets.pickWindow(...))` 包在 launch 里），
        #    原来那句 `applyPreset(DatePresets.THIS_MONTH)` 已经不在 init 里了 →
        #    注入的第一格静默不生效 → 这条注入只做了一半，判据当然不红（实测 [MISS]）。
        #    现在锚在 init 块里那个**带参数**的调用上（`_probeLate(1)` 就插在它后面）。
        lambda s: s.replace(
            "            if (!userPickedPreset) {\n"
            "                switchPreset(DatePresets.pickWindow(DatePresets.AUTO_LADDER) { periodHasData(it) })\n"
            "            }\n",
            "            if (!userPickedPreset) {\n"
            "                switchPreset(DatePresets.pickWindow(DatePresets.AUTO_LADDER) { periodHasData(it) })\n"
            "            }\n"
            "            _probeLate(1)\n",
            1,
        )
        .replace(
            "    fun applyPreset(label: String) {",
            "    private fun _probeLate(n: Int) {\n        _probeDeeper(n)\n    }\n\n"
            "    private fun _probeDeeper(n: Int) {\n        probeLate = n\n    }\n\n"
            "    fun applyPreset(label: String) {",
            1,
        )
        .replace(
            "    fun total(): Double =",
            "    var probeLate by mutableStateOf(0)\n\n    fun total(): Double =",
            1,
        ),
        "probeLate",
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
        print(out[-1200:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            out_txt = mutated.replace("\r\n", "\n")
            if crlf:
                out_txt = out_txt.replace("\n", "\r\n")
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
