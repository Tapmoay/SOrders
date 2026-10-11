# -*- coding: utf-8 -*-
r"""初始密码默认 123321（CHG-0118）的反向验证：一条判据要能被"真的破坏一次"证明它在检查。

每条注入只改一处，跑一遍 _check_default_password.py，要求它报红、而且报红的就是这条判据；
跑完按**字节**把被碰过的文件还原，再逐字节核对一遍。
锚点一律不写行首缩进：注入结果不需要能编译，只要判据变红。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:  # PowerShell 重定向时 stdout 会退回 GBK，中文与 ✅ 都编不出去
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_default_password.py"

SECURITY = "backend/app/core/security.py"
SCHEMA = "backend/app/schemas/user.py"
USERS_API = "backend/app/api/v1/users.py"
RULES = "android/app/src/main/java/com/tapmoay/sorders/core/AccountRules.kt"
MASTER = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteMasterData.kt"
LOOP = "android/app/src/main/java/com/tapmoay/sorders/ai/AiAgentLoop.kt"
ACC_VM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/AccountManageViewModel.kt"

NL = chr(10)
Q = chr(34)


def kill(s: str, old: str, n: int = 1) -> str:
    """删掉 old（最多 n 处）。"""
    return s.replace(old, "", n)


def gsub(s: str, pat: str, rep: str) -> str:
    r"""按正则换一处（锚点里用 \s* 兜住缩进，不数空格）。"""
    return re.sub(pat, rep, s, count=1)


CASES: list[tuple[str, str, object, str]] = [
    # ── 1. 默认值本身（用户口径里就是这一个数）────────────────────────────
    (
        "后端常量被改成别的值（123321 → 654321）",
        SECURITY,
        lambda s: s.replace('DEFAULT_INITIAL_PASSWORD = "123321"', 'DEFAULT_INITIAL_PASSWORD = "654321"', 1),
        "常量在（security.py",
    ),
    (
        "App 侧常量被改成别的值（两边分叉）",
        RULES,
        lambda s: s.replace('const val DEFAULT_INITIAL_PASSWORD = "123321"',
                            'const val DEFAULT_INITIAL_PASSWORD = "111111"', 1),
        "与后端常量一致",
    ),
    # ── 2. 后端"一处默认"──
    (
        "schema 把 password 改回必填（Field(...)）",
        SCHEMA,
        lambda s: s.replace("password: str = Field(DEFAULT_INITIAL_PASSWORD, min_length=6",
                            "password: str = Field(..., min_length=6", 1),
        "字段默认值",
    ),
    (
        "schema 里又抄了一份字面量（默认值不再引用常量）",
        SCHEMA,
        lambda s: s.replace("password: str = Field(DEFAULT_INITIAL_PASSWORD, min_length=6",
                            'password: str = Field("123321", min_length=6', 1),
        "schemas/user.py 的代码里",
    ),
    # ── 3. AI 那条链 ───────────────────────────────────────────────────────
    (
        "AI 密码参数改回必填（模型会先去问用户）",
        MASTER,
        lambda s: s.replace("不要自己编一个" + Q + ", required = false",
                            "不要自己编一个" + Q + ", required = true", 1),
        "密码字段不再是必填",
    ),
    (
        "卡片里删掉「用默认初始密码」那句说明",
        MASTER,
        lambda s: s.replace('"密码：" + AccountRules.DEFAULT_PASSWORD_NOTE', '"密码：不显示"', 1),
        "卡片正文写明",
    ),
    (
        "执行时不再落默认值（卡片说默认、实际发空）",
        MASTER,
        lambda s: s.replace("password = p.str(" + Q + "password" + Q + ").orEmpty().ifBlank { AccountRules.DEFAULT_INITIAL_PASSWORD }",
                            "password = p.str(" + Q + "password" + Q + ").orEmpty()", 1),
        "执行时没填就用默认",
    ),
    # ── 4. 提示词 ─────────────────────────────────────────────────────────
    (
        "提示词里删掉「不要追问密码」那条",
        LOOP,
        lambda s: kill(s, "用户说「建一个账号」时**不要追问密码**，直接按默认建；"),
        "不要追问密码",
    ),
    # ── 5. App 表单 ───────────────────────────────────────────────────────
    (
        "账户管理新建时不再预填默认值",
        ACC_VM,
        lambda s: s.replace("draftPassword = AccountRules.passwordDraft(isEdit = false)",
                            'draftPassword = ""', 1),
        "账户管理 openCreate() 预填默认值",
    ),
    (
        "编辑账号时也预填默认值（会静默重置别人的密码）",
        ACC_VM,
        lambda s: s.replace("draftPassword = AccountRules.passwordDraft(isEdit = true)",
                            "draftPassword = AccountRules.passwordDraft(isEdit = false)", 1),
        "账户管理 openEdit() 是空串",
    ),
    # ── 6. 既有红线（审计不回显）──────────────────────────────────────────
    (
        "密码被写进审计 payload",
        USERS_API,
        lambda s: s.replace('            "category": u.category,',
                            '            "category": u.category,' + NL + '            "password": body.password,', 1),
        "审计 payload",
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
        print("❌ 前提不成立：源码完好时这条判据就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时判据是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", NL)
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
            continue
        try:
            out_txt = mutated.replace("\r\n", NL)
            if crlf:
                out_txt = out_txt.replace(NL, "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print("  [OK] " + label + " → 判据报红")
        else:
            fails.append(label + f"：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print("  [MISS] " + label + " → 仍然全绿")

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
    print(f"✅ {len(CASES)} 条注入都证明这条判据真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
