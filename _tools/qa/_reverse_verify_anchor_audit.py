"""反向验证「反向验证的锚点还找得到吗」这条检查**真的会红**。

## 为什么要单独一份
`_tools/qa/_check_reverse_verify_anchors.py` 是一条**元检查**：它审计另外 96 份反向验证脚本的
注入锚点有没有腐烂。元检查比普通检查更容易变成"永远绿"——它出错时最可能的表现是
**安静地少查**（抽取逻辑认不出那些脚本的写法 → 一条锚点都没核对 → 打印"全部还在"）。

所以这里把它的四种失效方式固化成注入：
  ① 某一份脚本的锚点真的腐烂了 → 必须点名那一份、指出「原文找不到」；
  ② 目标文件被改名/搬走 → 必须报「目标文件不存在」；
  ③ 抽取逻辑自己失效（`GLOBS` 扫不到东西）→ 必须喊「只扫到 N 份脚本」，而不是零问题全绿；
  ④ 条数下限失守（把 `MIN_CASES` 抬到不可能满足）→ 必须喊「只核对到 N 条原文」；
  ⑤ `re:` 前缀那一支被拿掉（正则锚点会被误报成腐烂）→ 必须按正则再看一眼；
  ⑥ 允许表里留下一条化石 → 必须报出来。

⚠️ 快照/还原按**字节**做，跑完逐字节核对（本项目栽过"注入把 bug 留在源码里"）。

用法：python _tools/qa/_reverse_verify_anchor_audit.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = "_tools/qa/_check_reverse_verify_anchors.py"
#: 被注入的"别人的脚本"（这条元检查的审计对象）。
VICTIM = "_tools/qa/_reverse_verify_input_rules.py"

#: (说明, 相对路径, 被替换的原文, 替换成, 期望在 [FAIL]/输出里出现的关键词)
CASES: list[tuple[str, str, str, str, str]] = [
    (
        "某一份脚本的锚点腐烂了（原文已经不在目标文件里）→ 必须点名那一份",
        VICTIM,
        "'    var qty by remember { mutableStateOf(initialQty.coerceAtLeast(1)) }'",
        "'    var qty by remember { mutableStateOf(ZZZ_已经不存在了) }'",
        "原文找不到",
    ),
    (
        "注入目标被改名/搬走（路径解析得到，但文件不在了）→ 必须报「目标文件不存在」",
        VICTIM,
        'PRODUCT_PICKER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPicker.kt"',
        'PRODUCT_PICKER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPickerGone.kt"',
        "目标文件不存在",
    ),
    (
        "抽取逻辑自己失效（一份脚本都扫不到）→ 必须喊出来，而不是零问题全绿",
        CHECK,
        'GLOBS = ("_tools/*/_reverse_verify_*.py",)',
        'GLOBS = ("_tools/*/_reverse_verify_ZZZ_*.py",)',
        "抽取逻辑失效",
    ),
    (
        "条数下限失守（核对到的锚点数远少于下限）→ 必须先喊「抽取失效」",
        CHECK,
        "MIN_CASES = 850",
        "MIN_CASES = 999999",
        "抽取失效比锚点腐烂更危险",
    ),
    (
        "`re:` 前缀那一支被拿掉（正则锚点会被误报成腐烂）→ 必须按正则再看一眼",
        CHECK,
        "            if uses_regex and regex_hit(text, old):",
        "            if False and regex_hit(text, old):",
        "允许 AI 查看成本与毛利",
    ),
    (
        "允许表里留下一条化石（脚本/标签已经不存在）→ 必须报出来",
        CHECK,
        "ALLOW: dict[tuple[str, str], str] = {",
        'ALLOW: dict[tuple[str, str], str] = {\n    ("_reverse_verify_ZZZ_不存在.py", "一条早就删掉的注入"): "化石",',
        "化石",
    ),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, CHECK], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条检查就没过\n{out[-1500:]}")
        return 1
    print("✅ 前提：源码完好时这条检查是绿的")

    touched = sorted({rel for _l, rel, _o, _n, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, old, new, expect in CASES:
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        if plain.count(old) != 1:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）原文出现 {plain.count(old)} 次")
            print(f"  [SKIP] {label}")
            continue
        mutated = plain.replace(old, new, 1)
        try:
            data = mutated.replace("\n", "\r\n") if crlf else mutated
            (ROOT / rel).write_bytes(data.encode("utf-8"))
            code, out = run_check()
        finally:
            (ROOT / rel).write_bytes(original_bytes)
        hit = code != 0 and expect in out
        detail = f"退出码 {code}" + ("" if hit else f"，输出里没有「{expect}」")
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            for ln in out.splitlines()[-12:]:
                print("        " + ln)
            fails.append(f"{label}：没有按预期报红（{detail}）")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    code, out = run_check()
    if code == 0:
        print("  [OK] 还原后检查恢复全绿")
    else:
        fails.append("还原之后这条检查没恢复全绿")
        print("  [MISS] 还原后检查没恢复全绿")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条元检查真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
