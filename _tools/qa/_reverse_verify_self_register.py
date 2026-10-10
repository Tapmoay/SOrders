#!/usr/bin/env python3
"""FEAT-0017 自助注册反向验证：把「主路 + 五道边界」逐条弄坏，判据必须变红；末尾逐字节还原。

## 为什么这条判据必须有反向验证
`_check_self_register.py` 锚的全是**代码形状**（`role=UserRole.SHIPPER`、
`reject_plaintext_credentials(request)`、`raise HTTPException(...400...)`、`Depends(...)`）。
形状类判据有两种"看着绿、其实废"的死法，只有反向验证抓得住：

1. **锚点写松了**：比如写成 `"SHIPPER" in reg`，那么把默认角色改成 dispatcher、
   而注释里还留着"SHIPPER"四个字母时，判据照样绿。
2. **切片塌了**：取函数体的那段 `region()` 一旦收错边界（本仓库踩过：`strip_comments`
   把 Python 的模块 docstring 当字符串开关，切片变成空白），所有 `not in` 类断言**恒真**。
   所以下面每条注入都要求"**某条特定的**断言变红"，而不只是"退出码非 0"。

## 口径
- 注入点选在**判据真正会看的地方**，每条对应一种真实的退化（用户会吃亏的那种）。
- 每条注入要求：① 判据退出码非 0；② 失败清单里出现**预期的那个关键词**（证明红的是它）。
- 末尾把所有被改过的文件**逐字节还原**并核对 sha256（`read_bytes`/`write_bytes`，
  ⛔ 不用 `read_text`：它会把 CRLF 统一成 LF，锚点就对不上）。

用法：`python _tools/qa/_reverse_verify_self_register.py`
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_self_register.py"

AUTH = ROOT / "backend/app/api/v1/auth.py"
AUTH_SCHEMA = ROOT / "backend/app/schemas/auth.py"
GUARD = ROOT / "backend/app/services/login_guard.py"
SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/login/LoginScreen.kt"

FILES = [AUTH, AUTH_SCHEMA, GUARD, SCREEN]
ORIG = {p: p.read_bytes() for p in FILES}

#: (文件, 名字, 原文锚点, 替换成, 期望在失败清单里出现的关键词)
MUTATIONS: list[tuple[Path, str, str, str, str]] = [
    (AUTH,
     "① 默认角色改成派单员（自助注册出管理员）",
     "role=UserRole.SHIPPER",
     "role=UserRole.DISPATCHER",
     "默认角色不是写死的货主"),
    (AUTH,
     "② 角色改从请求体取（带 role 就能提权）",
     "role=UserRole.SHIPPER,",
     "role=body.role,",
     "从请求体取 role/is_member/is_active/vehicle_type"),
    (AUTH,
     "③ 明文通道拦截拿掉（密码在公网裸奔）",
     "    reject_plaintext_credentials(request)\n    ip = _client_ip(request)",
     "    ip = _client_ip(request)",
     "没有调 reject_plaintext_credentials"),
    (AUTH_SCHEMA,
     "④ 手机号形状校验删掉（第二份规则 / 不再校验）",
     "phone: MobilePhone = Field(..., max_length=11",
     "phone: str = Field(..., max_length=32",
     "用的不是 core/phone.py 的 MobilePhone"),
    (AUTH,
     "⑤ 已有号冲突当成功（不再报 400）",
     '        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该手机号已存在")',
     '        pass',
     "重复手机号没有那条中文 400"),
    (AUTH,
     "⑥ 限流那道门拿掉（同 IP 可无限刷号）",
     "    reason = login_guard.registration_block_reason(ip)\n",
     "",
     "没有查限流"),
    (AUTH,
     "⑦ 注册成功不记计数（阈值永远到不了）",
     "    login_guard.note_registration(ip)\n",
     "",
     "注册成功没有记这次"),
    (GUARD,
     "⑧ 限流函数恒放行（门成了摆设）",
     '    if _hits(_key("reg_ip", client_ip)) >= MAX_REGISTRATIONS_PER_IP:',
     '    if False:',
     "注册计数的键不是 reg_ip"),
    (SCREEN,
     "⑨ App 里的注册入口点了没反应（等于没有入口）",
     'onClick = { showRegister = true }',
     'onClick = { }',
     "没有能点开的注册入口"),
]


def run_check(tree: Path) -> tuple[int, str]:
    """跑判据。**必须传 tree**（判据支持 `<另一棵树>` 参数）——
    不传的话它自己算 ROOT，反向验证期间源码树里带着注入的 bug，红了也说不清是谁红的。"""
    p = subprocess.run(
        [sys.executable, "-X", "utf8", str(CHECK), str(tree)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def restore() -> None:
    for path, blob in ORIG.items():
        path.write_bytes(blob)


def main() -> int:
    # ⓪ 先证明"没注入时判据是绿的"—— 否则下面每条"变红"都可能只是判据本来就在红。
    code, out = run_check(ROOT)
    if code != 0:
        print("❌ 注入之前判据就是红的，反向验证无从谈起：")
        print(out[-2000:])
        return 1
    print("  ✔ ⓪ 基线：未注入时判据是绿的")

    red = 0
    problems: list[str] = []
    for path, name, old, new, expect in MUTATIONS:
        src = path.read_bytes().decode("utf-8")  # ⛔ 不用 read_text（CRLF 会被统一，锚点对不上）
        if src.count(old) != 1:
            problems.append("%s：锚点出现 %d 次（应为 1）—— 判据的锚点写法变了？" % (name, src.count(old)))
            continue
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(src.replace(old, new, 1))
        code, out = run_check(ROOT)
        restore()
        if code == 0:
            problems.append("%s：判据**没有**变红（这条边界是没人管的）" % name)
            continue
        if expect not in out:
            problems.append("%s：变红了，但红的是别的东西（失败清单里没有 %r）" % (name, expect))
            continue
        red += 1
        print("  ✔ %s → 判据变红（命中的是预期那条断言）" % name)

    same = all(
        hashlib.sha256(p.read_bytes()).hexdigest() == hashlib.sha256(b).hexdigest()
        for p, b in ORIG.items()
    )
    print()
    print("注入 %d 条，变红 %d 条；还原后逐字节一致：%s" % (len(MUTATIONS), red, same))
    if problems:
        print("❌ 有问题：")
        for p in problems:
            print("   -", p)
        return 1
    if red != len(MUTATIONS) or not same:
        print("❌ 没做到「每条注入都红 + 命中预期断言 + 逐字节还原」")
        return 1
    print("✅ %d/%d 都红了（且每条命中的都是它该命中的那条断言），文件逐字节还原。" % (red, len(MUTATIONS)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
