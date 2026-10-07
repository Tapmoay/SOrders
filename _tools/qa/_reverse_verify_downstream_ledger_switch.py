# -*- coding: utf-8 -*-
"""反向验证 `_check_downstream_ledger_switch.py` 真的在检查（CHG-0076 / 台账 L-39）。

## 为什么这条反验必须有
那条红线里绝大多数判据是**逐字文本**（闸门那一行、403 文案、端点装饰器、审计字段名……）。
逐字文本最典型的失效方式不是"判错了"，而是**它还在、意思变了**：
把三条件闸门改回两条件、把 `/me` 换成带 `{user_id}` 的路由、把开关顺手写回 `is_member` ——
每一条都能编译、都能跑通，肉眼看 diff 也未必看得出来。所以这里把 18 种"看起来对"的破坏
逐个注入进去，要求判据**按预期变红**（注入完按字节还原，还原后重新读回来逐字节比）。

## 断言方式
判据用的是 `_check_hints.Checker` ⇒ 失败行标记是 `[!!]`（不是同族脚本里那个 `[FAIL]`）。
每条注入都写成 (说明, 文件, 原文, 换成, 期望关键词)，其中期望关键词必须是**某条[!!]行的子串**。

用法：python _tools/qa/_reverse_verify_downstream_ledger_switch.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_downstream_ledger_switch.py"
QA = ROOT / "_tools" / "qa"
BACK = ROOT / "backend"
AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"

MIGRATION = BACK / "app" / "migrations" / "026_user_downstream_ledger.py"
API_LEDGER = BACK / "app" / "api" / "v1" / "shipper_ledger.py"
API_USERS = BACK / "app" / "api" / "v1" / "users.py"
TESTFILE = BACK / "tests" / "test_downstream_ledger_switch.py"
GATE_CHECK = QA / "_check_ledger_pay_block_gate.py"
REPO = AND / "data" / "repo" / "AppRepository.kt"
LVM = AND / "ui" / "shipper" / "ShipperLedgerViewModel.kt"
LSCREEN = AND / "ui" / "shipper" / "ShipperLedgerScreen.kt"
PSCREEN = AND / "ui" / "profile" / "ProfileScreen.kt"
#: 反验注入用的假文件（跑完 unlink；已存在就先喊）
PROBE = BACK / "app" / "api" / "v1" / "_probe_downstream_tmp.py"

DQ = chr(34)
NL = chr(10)

MUTATIONS = [
    (
        "① 迁移的默认值改成 0（上线那一刻所有批发商的下游账突然消失）",
        MIGRATION,
        "ADD COLUMN {COLUMN} BOOLEAN NOT NULL DEFAULT 1",
        "ADD COLUMN {COLUMN} BOOLEAN NOT NULL DEFAULT 0",
        "ALTER 那一句逐字",
    ),
    (
        "② 迁移不再判列在不在（MySQL 上第二次跑就炸 / 半改状态回不去）",
        MIGRATION,
        "    if COLUMN in {c[" + DQ + "name" + DQ + "] for c in insp.get_columns(TABLE)}:",
        "    if False:",
        "可重跑",
    ),
    (
        "③ 收入侧闸门退回一个条件（关掉的人照样看到一段全是 0.00 的收入）",
        API_LEDGER,
        "if is_member and downstream:",
        "if is_member:",
        "收入侧闸门是两个条件",
    ),
    (
        "④ 汇总出参不再带那个标记（客户端分不清「关掉了」还是「本来就没有」）",
        API_LEDGER,
        "        downstream_ledger_enabled=downstream," + NL,
        "",
        "出参带标记",
    ),
    (
        "⑤ 核销列表的早退挪到查库之后（关掉的人照样被查一次库）",
        API_LEDGER,
        "    if not _downstream_enabled(current):" + NL + "        return []" + NL
        + "    effective_limit = limit or DEFAULT_SETTLE_LIMIT",
        "    effective_limit = limit or DEFAULT_SETTLE_LIMIT" + NL
        + "    if not _downstream_enabled(current):" + NL + "        return []",
        "核销列表",
    ),
    (
        "⑥ 读端点上加一道 403（旧 App 会弹错：他明明只是关了一个显示开关）",
        API_LEDGER,
        "    if not _downstream_enabled(current):" + NL + "        return []",
        "    _require_downstream(current)",
        "读路上一道 403 都没有",
    ),
    (
        "⑦ POST 那个写端点少一道闸（界面藏起来的东西就不是关掉了）",
        API_LEDGER,
        "    _require_member(current)" + NL + "    _require_downstream(current)" + NL
        + "    order = _locked_order(db, _own_order(db, current, body.order_id))",
        "    _require_member(current)" + NL
        + "    order = _locked_order(db, _own_order(db, current, body.order_id))",
        "之后紧跟",
    ),
    (
        "⑧ 端点改成能代设（带 user_id 的路由 = 派单员也能拨别人的开关）",
        API_USERS,
        "@router.patch(" + DQ + "/me/downstream-ledger" + DQ + ", response_model=UserOut)",
        "@router.patch(" + DQ + "/users/{user_id}/downstream-ledger" + DQ + ", response_model=UserOut)",
        "端点逐字",
    ),
    (
        "⑨ 关掉这本账顺手把他降成普通货主（两个布尔值互相写）",
        API_USERS,
        "    before = bool(current.downstream_ledger_enabled)",
        "    current.is_member = False" + NL + "    before = bool(current.downstream_ledger_enabled)",
        "从不给 is_member 赋值",
    ),
    (
        "⑩ 幂等那一句被删（审计里全是「开了又开」，真改动被噪声埋掉）",
        API_USERS,
        "    if before == after:",
        "    if False:",
        "幂等：拨到同一档直接 return",
    ),
    (
        "⑪ 审计里那个字段名被换成别的（回查时对不上是谁拨了哪一格）",
        API_USERS,
        "                {" + DQ + "field" + DQ + ": " + DQ + "downstream_ledger_enabled" + DQ
        + ", " + DQ + "from" + DQ + ": before, " + DQ + "to" + DQ + ": after}",
        "                {" + DQ + "field" + DQ + ": " + DQ + "is_member" + DQ
        + ", " + DQ + "from" + DQ + ": before, " + DQ + "to" + DQ + ": after}",
        "真改动写一条审计",
    ),
    (
        "⑫ 审计动作换成新枚举（App 侧没有中文名，动作目录当场红）",
        API_USERS,
        "        order_id=None," + NL + "        action=OperationAction.USER_UPDATE," + NL
        + "        change_payload={" + NL + "            " + DQ + "user_id" + DQ + ": current.id,",
        "        order_id=None," + NL + "        action=OperationAction.DOWNSTREAM_LEDGER_UPDATE," + NL
        + "        change_payload={" + NL + "            " + DQ + "user_id" + DQ + ": current.id,",
        "复用既有动作枚举 USER_UPDATE",
    ),
    (
        "⑬ 客户端 VM 闸门退回只看身份（关掉的人还能点核销，后端 403）",
        LVM,
        "val canManageDownstream: Boolean get() = isMember && downstreamEnabled",
        "val canManageDownstream: Boolean get() = isMember",
        "VM 的界面闸门逐字",
    ),
    (
        "⑭ 收入段那道闸门退回两个条件（界面还在画、服务端已经返 0）",
        LSCREEN,
        "if (vm.isMember && s?.isMember == true && s.downstreamLedgerEnabled) {",
        "if (vm.isMember && s?.isMember == true) {",
        "收入段那道闸门逐字",
    ),
    (
        "⑮ 我的页那个状态回执被挂到「提示」总开关上（关掉提示就看不见自己拨的是哪一档）",
        PSCREEN,
        "if (vm.downstreamLedgerEnabled) " + DQ + "已开启" + DQ + " else " + DQ + "已关闭" + DQ + ",",
        "Hint(if (vm.downstreamLedgerEnabled) " + DQ + "已开启" + DQ + " else " + DQ + "已关闭" + DQ + "),",
        "状态回执常显",
    ),
    (
        "⑯ 那一行不再只给批发商画（普通货主点下去只会拿到 403）",
        PSCREEN,
        "if (vm.user?.isMember == true) {",
        "if (true) {",
        "那一行只给批发商画",
    ),
    (
        "⑰ AppRepository 退回 import 写法（包名/可见性一错就是 Unresolved reference）",
        REPO,
        "import com.tapmoay.sorders.data.remote.dto.AiCallReportDto",
        "import com.tapmoay.sorders.data.remote.dto.AiCallReportDto" + NL
        + "import com.tapmoay.sorders.data.remote.api.DownstreamLedgerRequest",
        "AppRepository 走**全限定名**",
    ),
    (
        "⑱ 既有那条红线不再用同一份闸门文本（两处慢慢长歪 = 两套口径）",
        GATE_CHECK,
        "&& s.downstreamLedgerEnabled) {",
        ") {",
        "既有红线用的是",
    ),
    (
        "⑲ 单测里那个用例被改名（口径① 的读返空从此没人守）",
        TESTFILE,
        "返空但不是403",
        "返空但非403",
        "后端单测六个用例都在",
    ),
]

# (说明, 路径, 内容, 期望关键词) —— 跑完 unlink()
CREATIONS = [
    (
        "⑳ 别的 api 文件也来提这一列（写入口多了一个，「只有 /me」当场失效）",
        PROBE,
        "# ⛔ 反验注入用的假文件：多一个文件提这一列（必须被点名）" + NL
        + "PROBE_COLUMN = " + DQ + "downstream_ledger_enabled" + DQ + NL,
        "只有两个文件提这一列",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    """读源码，返回 (LF 化文本, 是否 CRLF)。"""
    data = p.read_bytes()
    return data.decode("utf-8").replace(chr(13) + NL, NL), (chr(13) + NL) in data.decode("utf-8")


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text
    if crlf:
        data = data.replace(NL, chr(13) + NL)
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out


def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节才是。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    # ⚠️ 这条判据用的是 `_check_hints.Checker` ⇒ 失败行是 `[!!]`（同族脚本里那个是 `[FAIL]`）。
    fails = [ln for ln in out.splitlines() if "[!!]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, "实际红 %d 条" % len(fails) + ("" if hit else "：" + str([f.strip()[:70] for f in fails[:2]]))


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线没过\n" + out[-1500:])
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print("  [SKIP] " + label + " —— 原文出现 %d 次，无法唯一替换" % src.count(old))
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            restore_src(path, src, crlf)
        print("  [%s] %s → %s" % ("OK" if hit else "MISS", label, detail))
        if not hit:
            bad += 1

    for label, path, content, expect in CREATIONS:
        if path.exists():
            print("  [SKIP] " + label + " —— 文件已存在，先手动删掉再跑")
            bad += 1
            continue
        path.write_text(content, encoding="utf-8")
        try:
            hit, detail = verdict(expect)
        finally:
            path.unlink()
        print("  [%s] %s → %s" % ("OK" if hit else "MISS", label, detail))
        if not hit:
            bad += 1

    total = len(MUTATIONS) + len(CREATIONS)
    print()
    if bad:
        print("❌ %d / %d 条注入没有让判据变红（注入本身可能失效了）" % (bad, total))
        return 1
    print("✅ 全部 %d 条注入都让判据按预期变红。" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
