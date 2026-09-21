"""反向验证：把「司机端不显示金额」那条判据逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这条规矩坏掉的方式**全部不报错**——
把 `if` 加回来只是卡片上多一个 ¥；把 `role != Role.DRIVER` 那道门拆掉只是司机又看到货款；
把后端的门控删掉只是数字重新下发到司机手机上（界面上什么都不显示，因为界面已经不画它了！）。
最后一种最危险：**界面不画了，于是没人会去检查那个数字还在不在往下发**。

用法：python _tools/qa/_reverse_verify_driver_money.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_driver_money.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CARD = AND / "ui/common/OrderCard.kt"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
FREIGHT = AND / "ui/driver/DriverFreightScreen.kt"
PROFILE_SCREEN = AND / "ui/profile/ProfileScreen.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"
DRIVER_DIR = AND / "ui/driver"
ORDER_RESPONSE = ROOT / "backend/app/services/order_response.py"
#: 2026-09-21 补的入口判据（「我的账单」那一格该不该出现）
DRIVER_PAY = ROOT / "backend/app/services/driver_pay.py"
USERS_API = ROOT / "backend/app/api/v1/users.py"
USER_SCHEMA = ROOT / "backend/app/schemas/user.py"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "把「按单计费司机显示运费」加回订单卡片（用户明说过不要）",
        CARD,
        "if (!driverMode) {",
        "if (!driverMode || order.freightFee != null) {",
        "卡片里不再读",
    ),
    (
        "把卡片的金额分支整个关掉（司机不画 ≠ 谁都不画）",
        CARD,
        "if (!driverMode) {",
        "if (false) {",
        "非司机那一支仍在画",
    ),
    (
        "删掉卡片里那句『别加回来』的指路（下一轮没人知道这条规矩）",
        CARD,
        "                //   ⛔ 别在这里\"顺手加回来\"：判据在 `_tools/qa/_check_driver_money.py`（有反向验证）。\n",
        "",
        "注释里点了判据脚本的名字",
    ),
    (
        "把详情页原来的司机运费块整段加回去（含 PIECE + freightVisible 判据）",
        DETAIL,
        "                if (role != Role.DRIVER) {\n                    Row(verticalAlignment = Alignment.CenterVertically) {\n                        Text(\n                            \"合计\",",
        "                if (role == Role.DRIVER) {\n"
        "                    if (order.driverBillingMode == \"PIECE\" && order.freightVisible && order.freightFee != null) {\n"
        "                        Text(\"¥\" + formatMoney(order.freightFee))\n"
        "                    }\n"
        "                }\n"
        "                if (role != Role.DRIVER) {\n                    Row(verticalAlignment = Alignment.CenterVertically) {\n                        Text(\n                            \"合计\",",
        "详情页不再按",
    ),
    (
        "把详情页商品行的『司机看不到货款』那道门拆掉",
        DETAIL,
        "if (role != Role.DRIVER) {\n                            Text(\n                                \"¥\" + formatMoney(line.lineTotal),",
        "if (true) {\n                            Text(\n                                \"¥\" + formatMoney(line.lineTotal),",
        "商品行的小计有",
    ),
    (
        "把「完成流程」那个 freightVisible 分支一起删掉（改坏了流程）",
        DETAIL,
        "                    if (order.freightVisible) {",
        "                    if (false) {",
        "仍被完成流程用着",
    ),
    (
        "后端不按单的单改发 0 而不是不发（数字重新下发到司机手机上）",
        ORDER_RESPONSE,
        'data["freight_fee"] = None',
        'data["freight_fee"] = "0.00"',
        "不按单的单把运费置 None",
    ),
    (
        "后端门控的判据从『这一单的模式』改成恒真",
        ORDER_RESPONSE,
        "    per_order = has_per_order_pay(order)",
        "    per_order = True",
        "门控判据是这一单的模式",
    ),
    (
        "「我的账单」不再画钱（过度执行：司机哪儿都看不到钱了）",
        FREIGHT,
        '"¥" + formatMoney(e.payTotal)',
        "e.payTotal",
        "我的账单逐单显示司机应得",
    ),
    # ---- 入口判据（2026-09-21 真机补的那 12 项）----
    (
        "入口判据退回旧的『只看当前模式』（改规则前攒下的按单钱又看不见了）",
        DRIVER_PAY,
        '    if snapshot_mode(driver) == "PIECE":\n        return True',
        '    if snapshot_mode(driver) == "PIECE":\n        return False',
        "判据的两头都在",
    ),
    (
        "去掉『账上已有按单账单』那一头（只认当前按单）",
        DRIVER_PAY,
        "DriverBill.bill_type",
        "DriverBill.month",
        "另一头：**账上已有按单账单**",
    ),
    (
        "账单类型比大小写不归一（SQLite 上永远查不到 → 本地绿、线上才碰巧对）",
        DRIVER_PAY,
        'func.upper(DriverBill.bill_type) == "PIECE"',
        'DriverBill.bill_type == "PIECE"',
        "大小写归一",
    ),
    (
        "`/users/me` 不再算这个字段（客户端永远拿不到 → 退回旧判据）",
        USERS_API,
        "        out.has_per_order_earnings = has_per_order_earnings(db, current)\n",
        "",
        "`/users/me` 真的把它算出填进出参",
    ),
    (
        "出参 schema 少了这个字段（静默不返回）",
        USER_SCHEMA,
        "    has_per_order_earnings: bool | None = None\n",
        "",
        "出参 schema 里有这个字段",
    ),
    (
        "客户端 DTO 少了这个字段（反序列化永远为 null）",
        DTOS,
        '    @SerialName("has_per_order_earnings") val hasPerOrderEarnings: Boolean? = null,\n',
        "",
        "客户端 DTO 里有这个字段",
    ),
    (
        "客户端入口退回『只看 paysPerOrder』（这一格又消失）",
        PROFILE_SCREEN,
        "vm.user?.paysPerOrder == true || vm.user?.hasPerOrderEarnings == true",
        "vm.user?.paysPerOrder == true",
        "客户端入口是**两个字段的或**",
    ),
    (
        "把两个概念合并（顺手改掉 `pays_per_order` 的语义 → 派单端给工资制司机弹运费框）",
        USERS_API,
        'out.pays_per_order = snapshot_mode(u) == "PIECE"',
        "out.pays_per_order = True",
        "`pays_per_order` 的原语义没被改",
    ),
]

#: 需要**新建文件**的注入（判据 8 的清单是扫目录算出来的，得证明它真的会数到新文件）
CREATIONS = [
    (
        "司机端新增一个画金额的页面（清单自己算 → 必须点名它）",
        DRIVER_DIR / "_LeakScreen.kt",
        "package com.tapmoay.sorders.ui.driver\n\n"
        "import com.tapmoay.sorders.util.formatMoney\n\n"
        "internal fun leak(o: String) = \"¥\" + formatMoney(o)\n",
        "画金额的文件只有",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            write_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    for label, path, content, expect in CREATIONS:
        if path.exists():
            print(f"  [SKIP] {label} —— 路径已存在：{path.name}")
            bad += 1
            continue
        path.write_bytes(content.encode("utf-8"))
        try:
            hit, detail = verdict(expect)
        finally:
            path.unlink(missing_ok=True)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + len(CREATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
