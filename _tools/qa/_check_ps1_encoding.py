"""红线：**含中文的 `.ps1` 必须存成 UTF-8 with BOM**（否则 PS 5.1 按 GBK 读，直接语法错）。

## 由来（2026-09-24 第 22 轮 F6，第 24 轮补判据）
`AGENTS.md` 里早就写着这条规矩（"改文件只用编辑工具：别用 PowerShell 往返"那一节），
但**一个判据都没有**，而现状已经违反了：仓库里 5 个含中文的 `.ps1` 都没有 BOM ——
其中 `scripts/build-frontend-for-deploy.ps1` 是 `README.md` 明确教 Windows 用户跑的那个。

PS 5.1 解析器（只解析、不执行）在无 BOM 的文件上会报：

    line 13 col 55: The string is missing the terminator: "
    line 7 col 60: Missing closing '}'

成因是 `AGENTS.md` 自己描述过的那个模式：UTF-8 汉字的字节被按 GBK 解掉、**吃掉换行**，
于是下一行整行变成未闭合字符串。**照 README 做的人拿到的是一个语法错误的脚本。**

## 判据（清单自己算，不手写）
1. 扫全仓 `*.ps1`（跳过 `.git` / `node_modules` / `build`）；
2. **含中日韩字符**（正则 `[\\u4e00-\\u9fff]`）的文件**必须**以 `EF BB BF` 开头；
3. 任何 `.ps1` 都必须能按 UTF-8 解码（解不出说明它根本不是 UTF-8，PS 5.1 也会读坏）；
4. 反空转：扫到的 `.ps1` 少于 8 个、或"含中文的"少于 4 个 → 报错（判据失效时先喊，不许安静全绿）；
5. 规矩与判据必须互相指认：`AGENTS.md` 里要有那条规矩的原文。

用法：python _tools/qa/_check_ps1_encoding.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "AGENTS.md"
BOM = b"\xef\xbb\xbf"
CJK = re.compile(r"[\u4e00-\u9fff]")
#: 扫描时要跳过的目录名（构建产物与依赖里也有 .ps1，但那些不归我们管）。
SKIP_DIRS = {".git", "node_modules", "build", ".gradle", "__pycache__", ".venv"}
MIN_PS1 = 8
MIN_CJK_PS1 = 4


def scan() -> tuple[list[Path], list[Path]]:
    """返回 (全部 .ps1, 含中文的 .ps1)。"""
    all_ps1: list[Path] = []
    for p in sorted(ROOT.rglob("*.ps1")):
        if SKIP_DIRS & set(p.parts):
            continue
        all_ps1.append(p)
    cjk = [p for p in all_ps1 if CJK.search(p.read_bytes().decode("utf-8", errors="replace"))]
    return all_ps1, cjk


def main() -> int:
    fails: list[str] = []
    all_ps1, cjk = scan()
    print(f"扫到 {len(all_ps1)} 个 .ps1，其中含中文的 {len(cjk)} 个：")
    for p in cjk:
        raw = p.read_bytes()
        mark = "✓ 有 BOM" if raw.startswith(BOM) else "❌ 没有 BOM（PS 5.1 会语法错）"
        print(f"   · {p.relative_to(ROOT).as_posix():45} {mark}")

    # ① 含中文 → 必须有 BOM
    naked = [p.relative_to(ROOT).as_posix() for p in cjk if not p.read_bytes().startswith(BOM)]
    if naked:
        fails.append(
            "这些 .ps1 含中文却没有 UTF-8 BOM（PS 5.1 按 GBK 读会报"
            "「The string is missing the terminator」并吃掉换行）：" + "、".join(naked)
        )

    # ② 全部 .ps1 至少要能按 UTF-8 解码
    broken = []
    for p in all_ps1:
        try:
            p.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            broken.append(p.relative_to(ROOT).as_posix())
    if broken:
        fails.append("这些 .ps1 不是 UTF-8（PS 5.1 下同样会读坏）：" + "、".join(broken))

    # ③ 反空转
    if len(all_ps1) < MIN_PS1:
        fails.append(f"只扫到 {len(all_ps1)} 个 .ps1（<{MIN_PS1}）——判据可能已空转")
    if len(cjk) < MIN_CJK_PS1:
        fails.append(f"只认出 {len(cjk)} 个含中文的 .ps1（<{MIN_CJK_PS1}）——判据可能已空转")

    # ④ 规矩与判据互相指认（文档里删掉那条规矩时，这条会红，提醒你别把判据留在真空里）
    doc = AGENTS.read_text(encoding="utf-8") if AGENTS.exists() else ""
    if "UTF-8 with BOM" not in doc:
        fails.append("AGENTS.md 里那条「含中文的 .ps1 必须 UTF-8 with BOM」不见了 —— 判据成了孤儿")

    if fails:
        print("\n❌ 脚本编码：")
        for f in fails:
            print("   - " + f)
        print("\n（修法：python -c 或编辑工具把它重存成 utf-8-sig —— 只加 3 字节 BOM，正文与换行不动。）")
        return 1
    print(
        f"\n✅ {len(all_ps1)} 个 .ps1 都是 UTF-8；含中文的 {len(cjk)} 个都带 BOM"
        "（PS 5.1 解析器实测通过）。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
