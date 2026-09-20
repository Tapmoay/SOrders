"""红线：`docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md` **是不是过期的**（2026-09-21 补的一条真判据）。

## 为什么要有它（不是假想，是刚发生的事）
`AGENTS.md` 早就写着「改后端 API 后重跑生成器」，但**没有任何检查看得见这件事**：
2026-09-21 精简轮我给四个分类端点各删了十几行，索引里 **53 处行号立刻过期**，
而 `_check_all.py` **49/49 全绿放过**。实测确认过这个洞：把索引里一处行号故意改成 999，
全套检查照样绿 —— 也就是说「地图过期」这件事当时**没有任何人在看**。

过期的地图比没有地图更糟：没有地图时人会去读代码拿一手真相，有错地图时人会直接照着动手
（仓库自己的原话，见 `AGENTS.md` 的「改动前必做」一节）。

## 判据（不在这里重写比对逻辑）
这份文档的**唯一作者**是 `backend/scripts/gen_endpoint_index.py`，它自己就有 `--check`
（逐行比对 + 不一致就返回 1）。这一条只做两件事：
1. 以 `backend/` 为工作目录跑 `python -m scripts.gen_endpoint_index --check --out <那份文档>`；
2. **把它的退出码原样传出去**，并把「怎么修」写清楚。

⚠️ 反空转：生成器或文档不存在 → 直接红（而不是安静地什么都不查）。
⚠️ 反向验证：`_tools/qa/_reverse_verify_generated_artifacts.py`（把索引改坏 → 必须报红；
  它同时覆盖"AI 读目录过期""发现规则漏写法""`--only` 判据错位"三件事）。

用法：python _tools/qa/_check_endpoint_index_fresh.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
GEN = BACKEND / "scripts" / "gen_endpoint_index.py"
DOC = ROOT / "docs" / "PROJECT_MAP" / "08A_ENDPOINT_INDEX.md"

FIX_HINT = (
    "修法：cd backend && python -m scripts.gen_endpoint_index "
    "--out ../docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md"
)


def main() -> int:
    if not GEN.exists():
        print(f"❌ 找不到生成器 {GEN.relative_to(ROOT)}（改名/搬走了？这一条就没东西可查了）")
        return 1
    if not DOC.exists():
        print(f"❌ 找不到 {DOC.relative_to(ROOT)}（被删了？那就是这份端点地图整个不见了）")
        return 1

    r = subprocess.run(
        [sys.executable, "-m", "scripts.gen_endpoint_index", "--check", "--out", str(DOC)],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    tail = [ln for ln in out.splitlines() if ln.strip()][-12:]
    for ln in tail:
        print("   " + ln)

    if r.returncode == 0:
        print("✅ 端点索引与源码一致（不是过期地图）")
        return 0
    print(f"\n❌ 端点索引**已经过期**：{DOC.relative_to(ROOT)} 与当前后端源码对不上。")
    print(f"   {FIX_HINT}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
