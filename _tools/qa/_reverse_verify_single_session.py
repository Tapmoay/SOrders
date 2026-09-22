"""反向验证 `_tools/qa/_check_single_session.py`（同一账号不许两台手机同时登 / 测试号段豁免）。

## 为什么必须做

这条判据守的事**坏起来一句报错都没有**：登录时不撤销、撤销了忘 commit（新令牌自己就失效）、
只推进版本号不断长连接（旧那台推送照收）、豁免判据放宽成 `startswith`（真实号被悄悄放行）、
失败分支也撤销（别人打错密码就能把你踢下线）—— 这五种改法**都能编译、都能跑、
单测里那个"真实账号会被顶掉"的用例甚至还能过**（因为最要命的那条是"两种账号都要对"）。

所以逐条**注入真缺陷**，每条都必须让判据报红；跑完按字节还原并再验一次绿。

⚠️ 锚点优先用 `re:`（缩进/空行随重构会变，写死空格的锚点迟早腐烂）。

用法：python _tools/qa/_reverse_verify_single_session.py [--list]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import (  # noqa: E402
    lock_reverse_verify,
    refuse_if_injecting,
    unlock_reverse_verify,
)

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_single_session.py"
AUTH = "backend/app/api/v1/auth.py"
SVC = "backend/app/services/auth_service.py"
DEPS = "backend/app/deps.py"
LOCATOR = "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

REVOKE_LINE = 'revoke_tokens_and_sockets(db, user, background_tasks, "账号在另一台设备登录")'
BLOCK = (
    r"re:if not is_test_account\(user\.phone\):\s*\n\s*"
    r"revoke_tokens_and_sockets\(db, user, background_tasks, \"账号在另一台设备登录\"\)\s*\n\s*db\.commit\(\)"
)

#: (说明, 文件, 原文（`re:` = 正则锚点）, 替换成, 期望被抓到的判据标签**前缀**)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 登录时**不再撤销**旧会话（两台手机从此可以同时在线，界面上完全正常）",
        AUTH,
        BLOCK,
        "    pass",
        "登录时真的撤销了",
    ),
    (
        "② 撤销了但 **commit 排在签发之后**（新令牌带着库里没生效的 tv → 刚登录就失效）",
        AUTH,
        BLOCK,
        "    if not is_test_account(user.phone):\n"
        "        revoke_tokens_and_sockets(db, user, background_tasks, \"账号在另一台设备登录\")\n"
        "    _tok = build_token_response(user)\n"
        "    db.commit()\n"
        "    return _tok",
        "⛔ 顺序：撤销",
    ),
    (
        "③ 只推版本号、不走 revocation 入口（旧那台 HTTP 401 但**推送照收**，外部检查 C-3）",
        AUTH,
        REVOKE_LINE,
        'bump_token_version(db, user, "账号在另一台设备登录")',
        "撤销走的是 revoke_tokens_and_sockets",
    ),
    (
        "④ 豁免判据放宽成 `startswith(前缀)`（`13800000001234` 这种真实号被悄悄放行）",
        SVC,
        r"re:    p = \(phone or \"\"\)\.strip\(\)\s*\n\s*if len\(p\)[\s\S]*?return tail\.isdigit\(\) and 1 <= int\(tail\) <= TEST_ACCOUNT_TAIL_MAX",
        "    p = (phone or \"\").strip()\n    return p.startswith(TEST_ACCOUNT_PHONE_PREFIX)",
        "边界①：长度必须等于",
    ),
    (
        "⑤ 豁免判据被**抄成第二份**（某个端把真实账号也放行，而两边都不报错）",
        AUTH,
        "def _login(",
        "def is_test_account(phone):\n    return False\n\n\ndef _login(",
        "`def is_test_account(` 全树只有一处",
    ),
    (
        "⑥ 认证**失败**那条分支里也撤销（别人拿你手机号打错几次密码就能把你踢下线）",
        AUTH,
        "        login_guard.note_failure(login_id, ip)",
        "        login_guard.note_failure(login_id, ip)\n        revoke_tokens_and_sockets(db, user, background_tasks, \"x\")",
        "⛔ 认证**失败**那条分支里没有撤销",
    ),
    (
        "⑦ 把 `deps.py` 的 tv 校验删掉（改密码/登出/单设备限制**全部失去立足点**）",
        DEPS,
        # ⚠️ 缩进用捕获组带着走：这一行在 `deps.py` 里是**4 个空格**（函数体内），
        #    第一版锚点写了 8 个空格 → 锚点没命中、这条注入空转（反向验证自己抓出来的）。
        r're:(\n\s*)if int\(payload\.get\("tv", 0\) or 0\) != int\(getattr\(user, "token_version", 0\) or 0\):',
        r"\1if False:",
        "deps.py 里比库里的 token_version",
    ),
    (
        "⑧ 拿 `ai_test_phone_prefix` 当豁免判据（打开 AI 默认 key 会顺手放宽登录限制）",
        SVC,
        r"re:    p = \(phone or \"\"\)\.strip\(\)",
        "    p = (phone or \"\").strip()\n    from app.config import get_settings\n"
        "    if get_settings().ai_test_phone_prefix:\n        return True",
        "⛔ 没有拿 `ai_test_phone_prefix` 当豁免判据",
    ),
    (
        "⑨ 定位表里把方向写反（先登的顶掉后来者）—— 下一个人就照这句实现",
        LOCATOR,
        "后来者顶掉先登的",
        "先登的顶掉后来者",
        "08_CODE_LOCATOR.md 写明「后来者顶掉先登的」",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    if refuse_if_injecting("单设备登录反向验证"):
        return 1

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    lock_reverse_verify()
    caught = 0
    problems: list[str] = []
    try:
        for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
            path = ROOT / rel
            if not path.exists():
                problems.append(f"{name}：找不到 {rel}")
                print(f"\n[{i}] {name}\n  ❌ 找不到 {rel}")
                continue
            orig = path.read_bytes()
            orig_sha = sha(path)
            text = orig.decode("utf-8")
            eol = "\r\n" if "\r\n" in text else "\n"
            if eol != "\n":
                old = old.replace("\n", eol)
                new = new.replace("\n", eol)
            pat = old[3:] if old.startswith("re:") else re.escape(old)
            injected, n = re.subn(pat, new, text, count=1)
            if n != 1:
                problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:50]!r}）")
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
            if sha(path) != orig_sha:
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
    finally:
        unlock_reverse_verify()

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
