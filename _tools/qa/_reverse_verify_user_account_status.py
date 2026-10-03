"""反向验证：`_check_user_account_status.py` 的每一条判据是不是**真的会红**。

### 为什么必须反向验证
检查脚本自己也会骗人：锚点写错、判据写宽、期望文案对不上，都会让它**恒绿**。
这一份把 BUG-0002 的 13 种「会悄悄坏掉」的写法逐个注入源码，跑一次判据，确认它
红在**预期那一条**，再还原 —— 全部报红才算通过（退出码 0）。

### 每条注入对应哪一种坏法
· 后端不再下发 `phone_display` / 不再下发 `is_deleted` → 界面退回画内部值；
· 回收站判据丢掉「已停用」那一半 → 「恢复时撞号」的账号被误算进回收站；
· 展示层不再对 `_del` 后缀兜底 → `13923111638_del62` 原样端给用户（P1 复现）；
· 姓名回落绕开 `rosterPhoneOf` → 乱码从姓名行漏出来；
· 「已停用」档不排掉回收站 / 默认档改回「全部」 → P2 原样搬了个地方；
· 列表不再按档过滤 → 档位行成了摆设；
· 回收站判据改由界面自己拿 `phone.contains("_del")` 猜 → 撞号账号被误判；
· 绑车候选只过滤 `!isActive` → 已删除账号照样能选（P10 复现）；
· 回收站账号又挂上「删除」按钮 → 按下去就是 400；
· `restore` 端点被改名 → Android 调的还是老地址；
· 空态又套回固定高度 → 文案被量成 0 高、屏幕上只剩一个图标（「空态看得见」那两条红）。

⚠️ 这份脚本会**临时改写**源码再还原（还原后逐字节核对）。被硬中断（工具调用被取消）
会留下注入的 bug —— 那时跑 `python _tools/qa/_check_reverse_verify_anchors.py --restore`
按注入串还原，⛔ 不要去改锚点（那会把 bug 永久钉进源码）。

用法：python _tools/qa/_reverse_verify_user_account_status.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_user_account_status.py"
AND = "android/app/src/main/java/com/tapmoay/sorders"
Q = chr(34)

#: (说明, 目标文件, 被替换的原文, 替换成, 期望变红的判据名关键词)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    (
        "后端不再下发可拨号码（界面只好画内部值）",
        "backend/app/api/v1/users.py",
        "out.phone_display = dialable_phone(u)",
        "out.phone_display = None",
        "手机号：_to_out 下发 phone_display",
    ),
    (
        "DTO 不再收 phone_display（界面退回画 phone）",
        AND + "/data/remote/dto/Dtos.kt",
        "@SerialName(" + Q + "phone_display" + Q + ") val phoneDisplay: String? = null,",
        "val phoneDisplay: String? = null,",
        "DTO：phone_display 与后端同名",
    ),
    (
        "回收站判据丢掉「已停用」那一半（撞号账号被误算进回收站）",
        "backend/app/api/v1/users.py",
        "return _is_deleted_account(u) and not u.is_active",
        "return _is_deleted_account(u)",
        "回收站判据：带后缀且已停用",
    ),
    (
        "恢复端点被改名（Android 调的还是老地址）",
        "backend/app/api/v1/users.py",
        "@router.post(" + Q + "/{user_id}/restore" + Q,
        "@router.post(" + Q + "/{user_id}/undelete" + Q,
        "恢复：有 restore 端点",
    ),
    (
        "展示层不再对 _del 后缀兜底（内部值原样端给用户）",
        AND + "/ui/common/RosterCard.kt",
        "return if (u.phone.contains(" + Q + "_del" + Q + ")) null else u.phone",
        "return u.phone",
        "口径：没有可拨号时回 null",
    ),
    (
        "姓名回落绕开展示口径（乱码从姓名行漏出来）",
        AND + "/ui/dispatcher/AccountManageScreen.kt",
        "name = u.fullName.ifBlank { rosterPhoneOf(u) ?: ROSTER_PHONE_TAKEN },",
        "name = u.fullName.ifBlank { u.phone },",
        "账户卡：姓名空时回落到显示号码",
    ),
    (
        "「已停用」档不排掉回收站（P2 原样搬了个地方）",
        AND + "/ui/dispatcher/AccountManageViewModel.kt",
        "2 -> !u.isActive && !u.isDeleted",
        "2 -> !u.isActive",
        "状态档判据：「已停用」排掉回收站",
    ),
    (
        "「已删除」档改由界面自己拿后缀猜",
        AND + "/ui/dispatcher/AccountManageViewModel.kt",
        "3 -> u.isDeleted",
        "3 -> u.phone.contains(" + Q + "_del" + Q + ")",
        "状态档判据：「已删除」= 回收站",
    ),
    (
        "默认档改回「全部」（一进来又是满屏旧账号）",
        AND + "/ui/dispatcher/AccountManageViewModel.kt",
        "var statusTab by mutableStateOf(1)",
        "var statusTab by mutableStateOf(0)",
        "状态档：默认停在「在用」",
    ),
    (
        "列表不再按档过滤（档位行成了摆设）",
        AND + "/ui/dispatcher/AccountManageViewModel.kt",
        "inRail(shown, railKey) { it.category }.filter { matchesStatus(it, statusTab) }",
        "inRail(shown, railKey) { it.category }",
        "状态档：列表按档过滤",
    ),
    (
        "绑车候选只过滤「未启用」，没排掉已删除（P10 复现）",
        AND + "/ui/dispatcher/VehicleManageScreen.kt",
        "val eligible = hits.filter { it.isActive && !it.isDeleted }",
        "val eligible = hits.filter { it.isActive }",
        "绑车候选：先排掉停用/已删",
    ),
    (
        "回收站账号又挂上「删除」按钮（按下去就是 400）",
        AND + "/ui/dispatcher/AccountManageScreen.kt",
        "AccountAction(" + Q + "恢复" + Q + ", Icons.Default.RestoreFromTrash, Color(MgrGreen), onRestore)",
        "AccountAction(" + Q + "删除" + Q + ", Icons.Default.DeleteOutline, Color(MessageRed), onDelete)",
        "回收站只给恢复：动作只有「恢复」一个",
    ),
    (
        "空态又套回固定高度（文案被量成 0 高，屏幕上只剩一个图标）",
        AND + "/ui/dispatcher/UsersManageScreen.kt",
        "EmptyView(" + Q + "没有匹配「${vm.query}」的账号" + Q + ", Modifier.fillMaxWidth())",
        "EmptyView(" + Q + "没有匹配「${vm.query}」的账号" + Q + ", Modifier.fillMaxWidth().height(140.dp))",
        "空态看得见：UsersManageScreen.kt 的空态不带固定高度",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def verdict(expect: str, code: int, out: str) -> str:
    if code == 0:
        return "注入之后判据还是绿的"
    if expect not in out:
        return "红了，但不是预期那一条（没看到 " + expect + "）"
    return ""


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("⚠️ 源码完好时判据就是红的 —— 先把判据修绿再来反向验证：")
        print(out)
        return 2
    print("基线：源码完好 → 判据全绿；下面逐个注入 " + str(len(MUTATIONS)) + " 条")
    bad = 0
    for i, (why, rel, old, new, expect) in enumerate(MUTATIONS, 1):
        p = ROOT / rel
        data = p.read_bytes()
        crlf = b"\r\n" in data
        src = data.decode("utf-8")
        if crlf:
            old = old.replace("\n", "\r\n")
            new = new.replace("\n", "\r\n")
        if src.count(old) != 1:
            print("[SKIP] " + str(i) + " " + why + " —— 锚点在 " + rel + " 里出现 " + str(src.count(old)) + " 次（锚点腐烂，去脚本里改锚点）")
            bad += 1
            continue
        try:
            p.write_bytes(src.replace(old, new, 1).encode("utf-8"))
            mcode, mout = run_check()
        finally:
            p.write_bytes(data)
            if p.read_bytes() != data:
                raise SystemExit("还原失败：" + rel + " —— 手工核对这个文件！")
        problem = verdict(expect, mcode, mout)
        print(("[OK] " if not problem else "[BAD] ") + str(i) + " " + why + ("" if not problem else " —— " + problem))
        if problem:
            bad += 1
    print()
    if bad:
        print("❌ " + str(len(MUTATIONS) - bad) + "/" + str(len(MUTATIONS)) + " 条成立")
        return 1
    print("✅ " + str(len(MUTATIONS)) + "/" + str(len(MUTATIONS)) + " 条全部成立：每条注入都被判据抓到，并红在预期那一条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())