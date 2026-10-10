#!/usr/bin/env python3
"""FEAT-0018 判据的反向验证：逐条注入，判据**必须变红**，末尾**逐字节还原**。

为什么要有这一份：判据本身也是代码，它同样会"看起来在检查、其实恒真"。
唯一能证明它真的在看东西的办法是**把它该抓的东西一个个做坏**，看它是不是每次都红 ——
而且红的必须是**它该红的那一条**（失败清单里出现预期的那句话），
否则"变红了"可能只是因为注入把文件改到语法都不对了。

覆盖的注入（与判据里的六道闸一一对应）：
  ① 6 个月冷却 → 0（冷却形同虚设，换个手机就换一个号）
  ② 登录侧的测试号豁免去掉（用户明确要求「测试账号除外」）
  ③ 注册侧的测试号豁免去掉（同上，另一个入口）
  ④ 同设备 24h 新增 ≤2 的速率闸去掉（脚本一分钟把 5 个额度刷满）
  ⑤ 注册那条「同设备 24h ≤1 个新号」去掉（挡批量刷号的关键那道）
  ⑥ 一台设备 5 个账号的硬上限改成 1（会误伤一机多号的正常用户 —— 用户 2026-10-11 明说「至少可以绑 5 个」）
  ⑦ 单台解冻不再写 USER_DEVICE_UNBIND 审计（手工放宽风控却不留痕）
  ⑧ 一键全解冻的审计不记 count（"这一下动了几台"事后查不出）
  ⑨ 403 话术里的最早可替换日期去掉（用户要的就是那个日期）
  ⑩ 三个端点的签名级角色门槛拆掉一个（写成体内 if / 换成 CurrentUser）
  ⑪ 审计码在 ReportCenter.kt 的中文名去掉（审计页显示英文码）
  ⑫ auth.register 不再调注册设备闸（端点与判定脱钩）
  ⑬ auth._login 里那条设备路整块拿掉（登录时根本不绑设备）
  ⑭ 设备登记的路由没挂进 api_router（端点存在但访问不到）
  ⑮ 模型的 (user_id, device_id) 唯一索引改掉（"复用那一行"失去数据库保证）
  ⑯ 速率闸的窗口从 24 小时改成 1 小时（口径偷换）

用法（⛔ 直接在主工作树上跑，它自己会还原）：
  python _tools/qa/_reverse_verify_account_device_binding.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_account_device_binding.py"

DEV_SVC = ROOT / "backend/app/services/device_service.py"
DEV_MODEL = ROOT / "backend/app/models/account_device.py"
AUTH = ROOT / "backend/app/api/v1/auth.py"
USERS = ROOT / "backend/app/api/v1/users.py"
ROUTER = ROOT / "backend/app/api/v1/router.py"
REPORT_CENTER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"

FILES = [DEV_SVC, DEV_MODEL, AUTH, USERS, ROUTER, REPORT_CENTER]
ORIG: dict[Path, bytes] = {p: p.read_bytes() for p in FILES}

# users.py 是 CRLF（其余几个文件是 LF）—— 锚点必须把行尾写对，否则 count 会是 0。
MUTATIONS: list[tuple[Path, str, str, str, str]] = [
    (
        DEV_SVC,
        "① 6 个月冷却 → 0",
        "BIND_TTL_MONTHS = 6",
        "BIND_TTL_MONTHS = 0",
        "冷却期不是 6 个月",
    ),
    (
        DEV_SVC,
        "② 登录侧测试号豁免去掉",
        "    if is_test_account(user.phone):\n        return None",
        "    if False:\n        return None",
        "bind_device 没跳过测试号",
    ),
    (
        DEV_SVC,
        "③ 注册侧测试号豁免去掉",
        "    if is_test_account(phone):\n        return",
        "    if False:\n        return",
        "check_device_registration 没跳过测试号",
    ),
    (
        DEV_SVC,
        "④ 同设备 24h 新增 ≤2 的速率闸去掉",
        "    if recent >= MAX_NEW_ACCOUNTS_PER_DEVICE_24H:",
        "    if False:",
        "24 小时内新增账号没有速率闸",
    ),
    (
        DEV_SVC,
        "⑤ 注册「同设备 24h ≤1 个新号」去掉",
        "    if recent >= MAX_NEW_ACCOUNTS_PER_DEVICE_REGISTER_24H:",
        "    if False:",
        "注册那道闸不在 check_device_registration 里",
    ),
    (
        DEV_SVC,
        "⑥ 一台设备 5 个账号 → 1 个",
        "MAX_ACCOUNTS_PER_DEVICE = 5",
        "MAX_ACCOUNTS_PER_DEVICE = 1",
        "一台设备的上限不是 5 个账号",
    ),
    (
        DEV_SVC,
        "⑯ 速率闸窗口 24 小时 → 1 小时",
        "DEVICE_WINDOW = timedelta(hours=24)",
        "DEVICE_WINDOW = timedelta(hours=1)",
        "速率闸的窗口不是 24 小时",
    ),
    (
        DEV_SVC,
        "⑨ 403 话术里的最早可替换日期去掉",
        '        f"{expires_at:%Y-%m-%d} 才能替换；急用请联系派单员在「账户管理 → 编辑」里解冻。"',
        '        "才能替换；急用请联系派单员在「账户管理 → 编辑」里解冻。"',
        "403 话术里没有",
    ),
    (
        USERS,
        "⑦ 单台解冻不再写 USER_DEVICE_UNBIND 审计",
        '        action=OperationAction.USER_DEVICE_UNBIND,\r\n'
        '        change_payload={\r\n'
        '            "user_id": user_id,\r\n'
        '            "binding_id": binding_id,',
        '        action=OperationAction.USER_UPDATE,\r\n'
        '        change_payload={\r\n'
        '            "user_id": user_id,\r\n'
        '            "binding_id": binding_id,',
        "两个解冻端点没有都写 USER_DEVICE_UNBIND 审计",
    ),
    (
        USERS,
        "⑧ 一键全解冻的审计不记 count",
        '            "count": len(rows),',
        '            "rows": len(rows),',
        "一键全解冻的审计里没有 count",
    ),
    (
        USERS,
        "⑩ GET /users/{id}/devices 的角色门槛拆掉",
        "def list_user_devices(\r\n"
        "    user_id: int,\r\n"
        "    current: User = Depends(require_permission(Permission.USER_MANAGE)),",
        "def list_user_devices(\r\n"
        "    user_id: int,\r\n"
        "    current: User = CurrentUser,",
        "三个设备端点的角色门槛不是签名级的",
    ),
    (
        AUTH,
        "⑫ 注册端点不再调注册设备闸",
        "    try:\n"
        "        check_device_registration(db, device_id=device_id, phone=body.phone)\n"
        "    except DeviceBindingError as e:",
        "    try:\n"
        "        _ = None\n"
        "    except DeviceBindingError as e:",
        "auth.register 没有调那道注册设备闸",
    ),
    (
        AUTH,
        "⑬ 登录时根本不绑设备",
        "    try:\n"
        "        bind_device(\n"
        "            db,\n"
        "            user=user,\n"
        "            device_id=device_id_from_header(request.headers.get(DEVICE_HEADER)),\n"
        "            source=SOURCE_LOGIN,\n"
        "        )\n",
        "    try:\n"
        "        _ = None\n",
        "auth._login 里没有设备那条路",
    ),
    (
        ROUTER,
        "⑭ 设备登记路由没挂进 api_router",
        "api_router.include_router(devices.router)",
        "api_router.include_router(devices_router_not_mounted)",
        "设备登记的路由没有挂进 api_router",
    ),
    (
        DEV_MODEL,
        "⑮ 模型唯一索引改掉",
        'UniqueConstraint("user_id", "device_id"',
        'UniqueConstraint("user_id", "user_id"',
        "模型缺 (user_id, device_id) 唯一索引",
    ),
    (
        REPORT_CENTER,
        "⑪ 审计码的中文名去掉",
        '    "USER_DEVICE_UNBIND" -> "解冻设备"',
        '    "USER_DEVICE_UNBIND" -> ""',
        "ReportCenter.kt::actionLabel 里没有 USER_DEVICE_UNBIND",
    ),
]


def run_check(tree: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-X", "utf8", str(CHECK), str(tree)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def restore() -> None:
    for path, blob in ORIG.items():
        path.write_bytes(blob)


def main() -> int:
    problems: list[str] = []

    # ⓪ 先跑未注入的基线：判据自己就是红的时，后面每条都会"变红"，那就什么都没验证到。
    code, out = run_check(ROOT)
    if code != 0:
        print("❌ 注入之前判据就是红的 —— 先把它修绿，反向验证才有意义：")
        print(out[-4000:])
        return 1

    red = 0
    for path, name, old, new, expect in MUTATIONS:
        src = path.read_bytes().decode("utf-8")
        seen = src.count(old)
        if seen != 1:
            problems.append(f"{name}：锚点在 {path.name} 里出现 {seen} 次（应为 1，文件动过了？）")
            restore()
            continue
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(src.replace(old, new, 1))
        code, out = run_check(ROOT)
        restore()
        if code == 0:
            problems.append(f"{name}：注入之后判据**没有变红**（这条闸没有任何东西在管）")
            continue
        if expect not in out:
            problems.append(f"{name}：判据红了，但红的是别的东西（失败清单里找不到「{expect}」）")
            print(out[-1500:])
            continue
        red += 1
        print(f"  ✔ {name} → 判据变红")

    same = all(
        hashlib.sha256(p.read_bytes()).hexdigest() == hashlib.sha256(ORIG[p]).hexdigest()
        for p in FILES
    )
    print(f"注入 {len(MUTATIONS)} 条，变红 {red} 条；还原后逐字节一致：{'是' if same else '否'}")
    if problems:
        print("❌ 以下 %d 条有问题：" % len(problems))
        for p in problems:
            print("   -", p)
        return 1
    if red != len(MUTATIONS) or not same:
        return 1
    print("✅ 每一条注入都让判据按预期变红，且工作树已逐字节还原（FEAT-0018，2026-10-11）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
