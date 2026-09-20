"""反向验证 `_tools/qa/_check_endpoint_index_fresh.py`：**把索引改坏，看它真的会红**。

## 为什么这份必须有
这条红线是 2026-09-21 补的，补它的理由本身就是"**它以前不存在，所以没人发现地图过期了**"。
那"它现在存在"也必须被证明：一个只会打印一行 ✅ 的脚本同样什么都拦不住。
两个注入都挑**只有它看得见**的坏法（其它 49 个检查对这两处完全无感，实测过）：
1. 索引里某处行号对不上（＝改完端点没重跑生成器）；
2. 索引里少了一整个端点行（＝新端点没进地图 / 被人手删过）。

用法：python _tools/qa/_reverse_verify_endpoint_index.py    # 全部报红 → 退出码 0
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

#: (说明, 注入函数)。注入必须**真的改动内容**，否则等于什么都没验。
MUTATIONS: list[tuple[str, object]] = [
    (
        "索引里一处行号被改错（改完端点没重跑生成器）",
        # 锚整行形状（`| `backend/app/...:90` |`）而不是"第一个 :数字" ——
        # 后者会命中文档里别的地方（日期、:`xxx` 说明），注入就变成改了个无关的字。
        lambda s: re.sub(
            r"(\| `backend/app/[^`]*?):(\d{2,4})`",
            lambda m: f"{m.group(1)}:{int(m.group(2)) + 1}`",
            s,
            count=1,
        ),
    ),
    (
        "索引里少了一个端点行（新端点没进地图，或被人手删过）",
        lambda s: "\n".join(
            ln for ln in s.splitlines()
            if "`POST /api/v1/expense-categories/reorder`" not in ln
        )
        + "\n",
    ),
]


def run() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    # ⚠️ 一律按**字节**读写：`read_text/write_text` 会做换行转换（LF↔CRLF），
    #    在 Windows 上跑一遍就把整份文档的换行改掉 —— 内容是"还原了"，
    #    `git status` 里却多出一个整文件改动（这个坑仓库里别的反向验证也踩过）。
    raw = DOC.read_bytes()
    original = raw.decode("utf-8")

    code, _ = run()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        return 1
    print("✅ 前提：索引是新的，红线绿")

    bad = 0
    for label, mutate in MUTATIONS:
        mutated = mutate(original)  # type: ignore[operator]
        if mutated == original:
            print(f"  [MISS] {label} —— 注入没生效（替换串过期了，请更新本脚本）")
            bad += 1
            continue
        try:
            DOC.write_bytes(mutated.encode("utf-8"))
            code2, out2 = run()
        finally:
            DOC.write_bytes(raw)
        hit = code2 != 0 and "已经过期" in out2
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {'报红' if hit else '没红（判据空转）'}")
        bad += 0 if hit else 1

    # 还原检查：字节级比对（不是"看起来一样"）
    same = DOC.read_bytes() == raw
    print("  [OK] 还原后与运行前逐字节一致" if same else "  [MISS] 没还原干净")
    bad += 0 if same else 1

    code3, _ = run()
    print("  [OK] 还原后红线全绿" if code3 == 0 else "  [MISS] 还原后红线没恢复")
    bad += 0 if code3 == 0 else 1

    print()
    if bad:
        print(f"❌ {bad} 项不成立")
        return 1
    print(f"✅ {len(MUTATIONS)} 条注入全部成立：索引过期这件事现在真的会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
