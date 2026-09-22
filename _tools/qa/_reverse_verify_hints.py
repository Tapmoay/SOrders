"""反向验证：`_tools/qa/_check_hints.py` 那些判据**真的抓得住**吗（2026-09-21）。

## 为什么必须有它
一条"永远绿的检查"等于没有检查。本仓库为此栽过好几次（`_ai_doc_check.py` 红了 12 轮没人管；
`_check_backend_fresh.py` 有过"崩了还给绿"）。所以每条新红线都要证明：
**把规矩做坏 → 它当场红**。

## 手法
对每个注入点：**先把文件按字节备份** → 注入 → 跑 `_check_hints.py`（期望非零退出）
→ **按字节还原** → 校验 sha256 与备份一致。
⛔ 全程不碰 `git checkout --`（那会把别的会话未提交的改动一起抹掉，本仓库实测发生过）。

## 安全措施（这个仓库有多个会话同时在改同一批文件）
1. **不注入"别人正在改"的文件**（`docs/AI_WORK_CLAIM.md` 的「进行中」清单）：本脚本的目标
   只有我自己这条线的文件 + 共享但只做追加式的 `MainActivity.kt` / `LoginViewModel.kt`；
   ⛔ `ui/profile/ProfileScreen.kt`（司机线在改）**故意不在清单里** ——
   我对它的判据（`PENDING` 防化石）只能靠人工验收，不能靠注入。
2. 还原前先比对"我刚写进去的那份"还在不在：**别人插了一脚就拒绝还原并报错**，
   绝不当"最后一个写入者"。
3. 任何一处还原后哈希对不上 → 立刻停手，并把文件路径打出来。

用法：
    python _tools/qa/_reverse_verify_hints.py            # 全部跑
    python _tools/qa/_reverse_verify_hints.py --list     # 只列注入点
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
ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
CHECK = ROOT / "_tools" / "qa" / "_check_hints.py"
INV = ROOT / "_tools" / "qa" / "_hint_inventory.py"

A = "android/app/src/main/java/com/tapmoay/sorders/"

# (说明, 相对路径, 锚点, 替换成, 期望哪条判据报红)
#
# ⚠️ 锚点一律是**普通字符串**（脚本内部 `re.escape`），只有以 `re:` 开头的才当正则用 ——
#    第一版把锚点全当正则，`CompositionLocalProvider(LocalHints provides` 那个不平衡的括号
#    直接让脚本崩了（`re.error: missing ), unterminated subpattern`）。
# ⚠️ 「期望」写的是**判据标签的开头**，命中判据是输出里出现 `[!!]   <标签>`——
#    只写标签本身不行：通过时那行也会打出来（`[OK]   <标签>`），等于永远算命中。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    ("① 一处解释句改回裸 Text（关掉开关它还在）",
     A + "ui/shipper/AddressScreen.kt", r"re:\bHint\(", "Text(", "裸露的解释句 = 1"),
    ("② 一处纯状态回执改成 Hint（关掉提示把状态也关了）",
     A + "ui/profile/AlertSettingsScreen.kt",
     'Text(\n                                "已确认：锁屏',
     'Hint(\n                                "已确认：锁屏',
     "「一次 Hint 调用里一段解释句都没有」的 = 1"),
    ("③ Hint 的短路 return 被删（变成永远显示）",
     A + "ui/common/Hints.kt", "if (prefs != null && !prefs.visible) return",
     "// 注入：短路没了", "Hints.kt::Hint 关掉时"),
    ("④ 根上不再提供 LocalHints（开关对全 App 失效）",
     A + "MainActivity.kt", "CompositionLocalProvider(LocalHints provides", "run",
     "MainActivity 提供了 LocalHints"),
    ("⑤ 冷启动不再自动关（「之后就默认关闭」失效）",
     A + "MainActivity.kt", "container.hintPrefs.onAppStart()", "// 注入：没了",
     "MainActivity 冷启动会走"),
    ("⑥ 登录不再开那一轮（新用户看不到说明）",
     A + "ui/login/LoginViewModel.kt", "container.hintPrefs.onLogin()", "// 注入：没了",
     "LoginViewModel 登录成功会走"),
    ("⑦ 旧机制回来了（per-key 计数：每条最多 3 次）",
     A + "core/HintPrefs.kt", "private const val KEY_VISIBLE",
     "const val MAX_TIMES = 3\n        private const val KEY_VISIBLE",
     "旧机制（每条最多 3 次的 per-key 计数）没有回来"),
    ("⑧ 开关不再是可观察状态（拨一下页面不变）",
     A + "core/HintPrefs.kt", "private var _state by mutableStateOf(load())",
     "private var _state = (load())",
     "HintPrefs.kt 里有「总开关」那个可观察状态"),
    ("⑨ 兼容壳的交代被删（下一个人以为两种写法都行）",
     A + "ui/common/Hints.kt", "把这个函数删掉", "保留着",
     "Hints.kt 里那个壳的 KDoc 交代了"),
    ("⑩ 多一处 HintOnce 调用（壳只许减不许增）",
     A + "ui/shipper/ShipperLedgerScreen.kt", r"re:\bHint\(", 'HintOnce(prefs, "k", ',
     "兼容壳 HintOnce 的调用点数"),
    ("⑪ 书写规范里的尺子被改掉（规范与实现脱节）",
     "docs/HINT_STYLE.md", "首次登录", "首次登入", "规范里写了开关的默认值"),
    ("⑫ 分类器被改坏（一条文案都认不出来 → 第 1、2 组会空过）",
     "_tools/qa/_hint_inventory.py", 'CJK_RE = re.compile(r"[\\u4e00-\\u9fff]")',
     'CJK_RE = re.compile(r"(?!)")', "认出 0 条解释句"),
    ("⑬ 扫描根路径改坏（一条文案都扫不到）",
     "_tools/qa/_hint_inventory.py",
     'SRC = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"',
     'SRC = ROOT / "android" / "__nope__"', "扫到 0 个 .kt"),
    ("⑭ 目录文档过期（生成物没人重跑）",
     "docs/PROJECT_MAP/09A_HINT_CATALOG.md", "# 界面提示与说明目录",
     "# 界面提示与说明目录（手改过了）", "目录文档与源码一致"),
    ("⑮ 解释句里混进活值（`$n` 也挂在 Hint 上 → 关掉提示会关掉数据）",
     A + "ui/shipper/AddressScreen.kt", "顺序到地址库左栏的", "顺序$n到地址库左栏的",
     "「一次 Hint 调用里一段解释句都没有」的 = 1"),
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _old, _new, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    print(f"先确认干净状态下是绿的：", end=" ")
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
        # 锚点里写的是 `\n`。目标文件可能是 CRLF（例如 Windows 上 `write_text` 生成的文档），
        # 那种情况下锚点会**静默不命中** —— 所以按文件自己的行尾归一，而不是直接跳过。
        eol = "\r\n" if "\r\n" in text else "\n"
        if eol != "\n":
            old = old.replace("\n", eol)
            new = new.replace("\n", eol)
        pat = old[3:] if old.startswith("re:") else re.escape(old)
        injected, n = re.subn(pat, new, text, count=1)
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
