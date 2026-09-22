"""反向验证 §35（卡片里那句「先读一次 XXX」必须指向**真的读动作**）。

## 为什么这一节必须配反向验证
它守的是一类**不报错、也不崩**的缺陷：卡片照印「先读一次 X 拿名册」，而 X 是我们自己拼的
一个不存在的读动作 id —— 模型照着调、只拿到"没有这个工具"，然后开始猜名字。
用户看到的是"它怎么老读错"，而**日志里一条异常都没有**。

2026-09-23 就是靠人眼发现的（给三份分类名册补 AI 能力时，`readHint` 写成了
`expense_categories.list_expense_categories`，真名是 `expense_categories.list_categories`）。
当时 1277 项判据里没有一条提过 `readHint` 这个词 —— 所以这一节是**新加的牙**，
必须按本项目铁律配注入实验，否则它自己也会变成"永远绿"。

三种失效方式各一条注入：
  ① 某一处 `readHint` 又变成自己拼的名字 → 必须点名它；
  ② 扫 `readHint` 的正则失效（一处都扫不到）→ 必须红在数量下限，而不是零问题全绿；
  ③ 读目录那一边换了形状（认不出动作）→ 同样必须先喊，而不是"没有对不上的"。

用法：`python _tools/ai/_reverse_verify_read_hints.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
WEXPENSE = AI / "AiWriteCatalogHandlers.kt"
CHECK = HERE / "_check_ai_guardrails.py"

#: (说明, 目标文件, 被替换的原文, 替换成, 期望在 [FAIL] 行里出现的关键词)
CASES: list[tuple[str, Path, str, str, str]] = [
    (
        "某一处 readHint 又变成自己拼的名字（模型照着调一个不存在的读动作）",
        WEXPENSE,
        'readHint = "expense_categories.list_categories"',
        'readHint = "expense_categories.list_expense_categories"',
        "每一处 readHint 都指向目录里真实存在的读动作",
    ),
    (
        "扫 readHint 的正则失效（一处都扫不到）→ 必须红在数量下限",
        CHECK,
        "re.finditer(r'readHint",
        "re.finditer(r'readHintZZZ",
        "处 readHint",
    ),
    (
        "读目录那一侧的下限失守（认不出动作）→ 不许安静地放行",
        CHECK,
        "len(catalog_ids) >= 50",
        "len(catalog_ids) >= 50000",
        "读目录里认得出动作",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section(out: str) -> str:
    """只取 §35 那一段（段内失败标记是 `[FAIL]`）。"""
    if "== 35." not in out:
        return ""
    rest = out.split("== 35.", 1)[1]
    nxt = rest.find("\n== ")
    return rest if nxt < 0 else rest[:nxt]


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0 or "[FAIL]" in out:
        print(f"❌ 前提不成立：源码完好时红线就没过（code={code}）\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({p for _l, p, _o, _n, _e in CASES})
    originals = {p: p.read_bytes() for p in touched}

    for label, path, old, new, expect in CASES:
        original_bytes = originals[path]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        if plain.count(old) != 1:
            fails.append(f"{label}：注入没生效（原文出现 {plain.count(old)} 次，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            data = plain.replace(old, new, 1)
            path.write_bytes((data.replace("\n", "\r\n") if crlf else data).encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        seg = section(out)
        hit = "[FAIL]" in seg and expect in seg
        detail = "报红" if hit else f"没有红在预期那条（§35 段：{seg.strip()[-160:]!r}）"
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            fails.append(f"{label}：{detail}")

    dirty = [p for p in touched if p.read_bytes() != originals[p]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(p.name for p in dirty))
        for p in dirty:
            p.write_bytes(originals[p])
        print("⚠️  已强制还原：" + "、".join(p.name for p in dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    code, out = run_check()
    if code == 0 and "[FAIL]" not in out:
        print("  [OK] 还原后红线恢复全绿")
    else:
        fails.append("还原之后红线没恢复全绿")
        print("  [MISS] 还原后红线没恢复全绿")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明 §35 真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
