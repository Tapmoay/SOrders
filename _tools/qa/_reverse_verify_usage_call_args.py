"""反向验证：`_tools/qa/_check_usage_call_args.py` 真的抓得住吗（2026-09-22）。

## 为什么必须有它
那条红线是**为了一个真事故**写的：`with_popularity(..., current)` 复制粘贴到 4 个
"用户参数叫 `_`/`user`"的端点上 → 那 4 个端点每次调用都 `NameError`（500），
而编译期、单测、`_check_all.py` **全都看不出来**（真打到端点才炸）。
"永远绿的检查等于没有检查" —— 所以这里证明：把参数名改回 `_`，它当场红。

## 手法（与 `_reverse_verify_sheet_form_pages.py` 同一套，不另立一套）
对每个注入点：**先把文件按字节备份** → 注入 → 跑红线（期望非零退出**且**命中指定的判据标签）
→ **按字节还原** → 校验 sha256 与备份一致。
⛔ 全程不碰 `git checkout --`（那会把别的会话未提交的改动一起抹掉，实测发生过）。

用法：
    python _tools/qa/_reverse_verify_usage_call_args.py          # 全部跑
    python _tools/qa/_reverse_verify_usage_call_args.py --list   # 只列注入点
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_usage_call_args.py"
CHECK_REL = "_tools/qa/_check_usage_call_args.py"
FT = "backend/app/api/v1/freight_templates.py"
PR = "backend/app/api/v1/price_rules.py"

# (说明, 相对路径, 锚点, 替换成, 期望哪条判据报红)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    ("① 运费模板的用户参数又被写成 `_`（＝当初那 4 处 500 的原样复发）",
     FT,
     "    current: User = Depends(require_permission(Permission.ORDER_DISPATCH)),",
     "    _: User = Depends(require_permission(Permission.ORDER_DISPATCH)),",
     # ⚠️ 期望串必须是**判据标签的开头**（harness 匹配的是 `[!!]   <want>`）——
     #    只写中间那句「实参 'current' 有定义」永远匹配不上（第一版就是这么假红的）。
     "backend/app/api/v1/freight_templates.py:list_templates() 里 "
     "usage_service.with_popularity(…) 的实参 'current' 有定义"),
    ("② 专属价那个端点把 `PriceRule` 的 import 删掉（实参名没定义，同样 500）",
     PR,
     "from app.models import PriceRule, Product, User",
     "from app.models import Product, User",
     "backend/app/api/v1/price_rules.py:list_price_rules() 里 "
     "usage_service.with_popularity(…) 的实参 'PriceRule' 有定义"),
    ("③ 判据自己的调用正则被改坏（一个调用都扫不到）→ 必须报「空转」而不是全绿",
     CHECK_REL,
     r'CALL = re.compile(r"\busage_service\.(\w+)\s*\(")',
     r'CALL = re.compile(r"\bZZZusage_service\.(\w+)\s*\(")',
     "扫到的 usage_service 调用"),
    ("④ 后端目录扫不到文件（路径写错/目录改名）→ 同样必须先喊",
     CHECK_REL,
     'files = sorted((BACKEND / "api" / "v1").glob("*.py")) + sorted((BACKEND / "services").glob("*.py"))',
     'files = sorted((BACKEND / "api" / "v1").glob("*.pyx")) + sorted((BACKEND / "services").glob("*.pyx"))',
     "扫到后端文件"),
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _old, _new, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    caught = 0
    problems: list[str] = []
    for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
        path = ROOT / rel
        if not path.exists():
            problems.append(f"{name}：找不到 {rel}")
            print(f"\n[{i}] {name}\n  ❌ 找不到 {rel}")
            continue
        orig = path.read_bytes()
        orig_sha = sha(orig)
        text = orig.decode("utf-8")
        eol = "\r\n" if "\r\n" in text else "\n"
        if eol != "\n":
            old = old.replace("\n", eol)
            new = new.replace("\n", eol)
        pat = old[3:] if old.startswith("re:") else re.escape(old)
        # ⚠️ `re.subn` 会把**替换文本**当模板解析（`\w` / `\b` 都会被判成 bad escape）——
        #    这一份里有几条注入恰好是改判据自己的正则（替换文本含 `\w`），所以必须自己转义。
        injected, n = re.subn(pat, new.replace("\\", "\\\\"), text, count=1)
        if n != 1:
            problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:40]!r}）")
            print(f"\n[{i}] {name}\n  ❌ 锚点没命中，跳过（注入点腐烂了）")
            continue
        inj_bytes = injected.encode("utf-8")
        path.write_bytes(inj_bytes)
        try:
            rc, out = run_check()
        finally:
            now = path.read_bytes()
            if now != inj_bytes:
                print(f"\n[{i}] {name}\n  🛑 有别的东西改了 {rel} —— **拒绝还原**，请人工处理！")
                return 2
            path.write_bytes(orig)
        if sha(path.read_bytes()) != orig_sha:
            print(f"\n[{i}] {name}\n  🛑 {rel} 还原后哈希对不上，停手")
            return 2

        hit = f"[!!]   {want}" in out
        if rc != 0 and hit:
            caught += 1
            print(f"\n[{i}] {name}\n  ✅ 被抓到（红线非零退出，命中「{want}」）")
        else:
            why = "红线居然还是绿的" if rc == 0 else f"退出了，但输出里没有「[!!]   {want}」"
            problems.append(f"{name}：{why}")
            print(f"\n[{i}] {name}\n  ❌ {why}")

    print("\n" + "=" * 60)
    print(f"{caught}/{len(INJECTIONS)} 种破坏方式被抓住")
    if problems:
        print("❌ 有漏网的：")
        for p in problems:
            print("   -", p)
        return 1
    print("✅ 全部注入都被抓住，且每个文件都按字节还原")
    return 0


if __name__ == "__main__":
    sys.exit(main())
