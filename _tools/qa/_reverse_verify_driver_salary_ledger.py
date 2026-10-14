#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""反向验证：固定工资司机的工资账只算工资、未核销的跟着新工资走、已核销的一分不动（CHG-0127）—— 12 种破坏方式都得被抓。

判据全绿不等于判据盯着东西：_tools/qa/_check_driver_salary_ledger.py 里每一条断言都可能
写成空转（路径写错、字符串少一个空格、顺序比较反了、条数写法变了）。
这个脚本逐条**真的把代码改坏**，再跑一遍判据：必须由**期望的那一条**报红；改回原样后必须全绿。

## 规矩（照 _tools/qa/_reverse_verify_silent_release.py）
1. 只按字节备份、按字节还原 —— ⛔ 不用 `git checkout --`（工作区里有别人未提交的改动，抹掉就没了）。
2. 还原后 sha256 逐个比对，不符立刻报 2（不许「看起来还原了」）。
3. 注入前先跑一次判据：干净状态必须绿（没有基线就没有对照）。
4. 注入前锚点唯一性预检：原文必须**恰好命中 1 次**（0 次＝注入点腐烂；>1 次＝可能打到别人身上＝假绿）。
5. 任何一条腐烂都要报出来，不许静默跳过。

硬中断（Ctrl+C / 断电）后现场恢复：python _tools/qa/_check_reverse_verify_anchors.py --restore

用法：python _tools/qa/_reverse_verify_driver_salary_ledger.py [--list]
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
CHECK = ROOT / "_tools" / "qa" / "_check_driver_salary_ledger.py"

BE_BILLS = "backend/app/api/v1/driver_bills.py"
BE_SCHEMA = "backend/app/schemas/accounting_v2.py"
SAL_KT = "android/app/src/main/java/com/tapmoay/sorders/ui/driver/DriverSalary.kt"
SAL_SCR = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverSalaryScreen.kt"
FREIGHT_SCR = "android/app/src/main/java/com/tapmoay/sorders/ui/driver/DriverFreightScreen.kt"
PROFILE = "android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileScreen.kt"

# (说明，文件，原文，替换成，期望被哪条判据标签抓到)
# 说明那句话就是「真会有人这么改」的理由。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "「没被结算单锁住」那一半改成恒真：已核销 / 被草稿结算单锁住的单也会被重算 —— 对过的账被改，是这一单最不能出的错",
        BE_BILLS,
        "    return getattr(bill, \"settled_doc_id\", None) is None",
        "    return True",
        "判据 B：还得没被任何结算单锁住（settled_doc_id is None）",
    ),
    (
        "刷新门少一个开关：只要金额变了就刷（不管调用方要不要 refresh_unsettled）—— 旧客户端点一下「生成」，已核销的金额就跟着新工资走了",
        BE_BILLS,
        "                if body.refresh_unsettled and _is_open_unlocked(exists) and exists.amount != sal:",
        "                if _is_open_unlocked(exists) and exists.amount != sal:",
        "刷新门三个条件合在一行（开关 + 未核销 + 金额真的变了）",
    ),
    (
        "缺省改成 True：不传这个字段的老客户端（旧 APK、别的调用方）行为被悄悄改了 —— 只增字段变成只增语义破坏",
        BE_SCHEMA,
        "refresh_unsettled: bool = False",
        "refresh_unsettled: bool = True",
        "开关缺省 False（不传就是老行为，一个字节都不改）",
    ),
    (
        "先记旧数那一行整个删掉：金额改了却没有「改之前是多少」—— 事后解释差额时手里没证据",
        BE_BILLS,
        "                    refreshed.append((exists, exists.amount))\n",
        "",
        "先记旧数再改（审计要拿得到「改之前是多少」）",
    ),
    (
        "老半边只剩角色 + 按单两个（少了按月薪那一档）：固定工资司机进 App 根本看不到「我的账本」，这一单就是白做的",
        PROFILE,
        "vm.user?.hasPerOrderEarnings == true ||\n"
        "                            vm.user?.hasSalary == true)",
        "vm.user?.hasPerOrderEarnings == true ||\n"
        "                            vm.user?.hasSalary == false)",
        "三个字段并列在同一个表达式里（按单两个 + 新的按月薪）",
    ),
    (
        "SALARY 分支只回新建的、把刷新的丢掉：调用方拿到的清单里少了刚刚被重算的那几笔",
        BE_BILLS,
        "        return created + [b for b, _ in refreshed]",
        "        return created",
        "SALARY 分支把「新建的 + 刷新的」都回给调用方",
    ),
    (
        "这个纯逻辑文件里画一次金额（formatMoney / ￥ / ¥）：分账逻辑混进展示 —— 判据 ② 组钉着「一个字金额都不画」",
        SAL_KT,
        "internal fun isSalaryBill(b: DriverBillDto): Boolean = b.billType.equals(\"salary\", ignoreCase = true)",
        "internal fun isSalaryBill(b: DriverBillDto): Boolean = formatMoney(b.amount).isNotEmpty() && b.billType.equals(\"salary\", ignoreCase = true)",
        "⛔ 这个纯逻辑文件一个字金额都不画",
    ),
    (
        "「合计」只给已核销那一半：应发合计少算了未核销的 —— 用户看到的数就是错的",
        SAL_KT,
        "    val all: Double get() = settled + open",
        "    val all: Double get() = settled",
        "合计分两笔给，不混成一个数",
    ),
    (
        "生成 / 重算时不带 refresh_unsettled：点「重算」跟点「生成」一模一样，改过的工资永远刷不出来",
        SAL_SCR,
        "                        refreshUnsettled = true,",
        "                        refreshUnsettled = false,",
        "生成 / 重算：带上 refresh_unsettled",
    ),
    (
        "带薪那一页不画了（if (false)）：月薪司机进「我的账本」只能看到运费那一半",
        FREIGHT_SCR,
        "                    if (showSalary) salaryItems(vm)",
        "                    if (false) salaryItems(vm)",
        "两半页各画各的",
    ),
    (
        "抽屉那份名册不筛（搜索框画着、打字名册不动）：71 位司机里找一个人只能靠滚",
        SAL_SCR,
        "    val visibleDrivers: List<UserDto> get() = UserSearch.filter(drivers, query, { driverText(it) }, { it.phone })",
        "    val visibleDrivers: List<UserDto> get() = drivers",
        "抽屉那份名册真的会筛（走唯一实现 UserSearch，不是画个框）",
    ),
    (
        "结算单那一行数错了对象（数 order_ids —— 工资结算单没有订单，于是「工资单 0 笔」挂在 ¥8000 旁边）",
        SAL_SCR,
        '                        s.paidAt?.let { "已付 " + it.take(10) } ?: "工资单 " + settledBillCountOf(vm.bills, s.id) + " 笔",',
        '                        s.paidAt?.let { "已付 " + it.take(10) } ?: "工资单 " + s.orderIds.orEmpty().size + " 笔",',
        "结算单那一行数的是「被它锁住的工资单」张数（工资结算单没有订单，数 order_ids 必然是 0）",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    """跑判据：返回 (退出码, stdout + stderr)。"""
    proc = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def count_hits(text: str, old: str) -> int:
    pat = old[3:] if old.startswith("re:") else re.escape(old)
    return len(re.findall(pat, text))


def anchor_preflight() -> list[str]:
    """锚点必须唯一命中：0 次＝注入点腐烂；>1 次＝可能打到别人身上（假绿）。"""
    bad: list[str] = []
    for i, (name, rel, old, _new, _want) in enumerate(INJECTIONS, 1):
        p = ROOT / rel
        if not p.is_file():
            bad.append("%2d. %s —— 文件不存在：%s" % (i, name, rel))
            continue
        hits = count_hits(p.read_text(encoding="utf-8"), old)
        if hits != 1:
            bad.append("%2d. %s —— 锚点在 %s 命中 %d 次（必须恰好 1 次）" % (i, name, rel, hits))
    return bad


def caught_by(out: str, want: str) -> bool:
    """判据那一行是不是「这一条」：房规的形状是 `  [!!]   <标签>`。"""
    return ("[!!]   " + want) in out or ("[!!]   ⛔ " + want) in out


_PENDING: dict[str, tuple[bytes, bytes, str]] = {}


def restore_pending() -> None:
    for rel, (orig, wrote, orig_sha) in list(_PENDING.items()):
        p = ROOT / rel
        try:
            cur = p.read_bytes()
        except OSError:
            print("  🛑 %s 读不到了 —— 请人工处理！" % rel)
            continue
        if cur != wrote:
            print("  🛑 %s 内容与注入时不一致（有人在动它）—— **拒绝还原**，请人工处理！" % rel)
            continue
        p.write_bytes(orig)
        if sha(p) != orig_sha:
            print("  🛑 %s 还原后 sha256 不符 —— 请人工处理！" % rel)
        else:
            _PENDING.pop(rel, None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列注入点，不改任何文件")
    args = ap.parse_args()

    if args.list:
        for i, (name, rel, _old, _new, want) in enumerate(INJECTIONS, 1):
            print("%2d. %s" % (i, name))
            print("      %s   ← 期望被「%s」抓到" % (rel, want))
        print("\n共 %d 条注入。" % len(INJECTIONS))
        return 0

    if refuse_if_injecting("固定工资司机的工资账（CHG-0127）反向验证"):
        return 1

    rc, out = run_check()
    if rc != 0:
        print("🛑 干净状态下判据就是红的 —— 先修判据 / 产品代码，反向验证没有意义。")
        print(out[-3000:])
        return 2

    bad = anchor_preflight()
    if bad:
        print("🛑 锚点预检不过（这些注入点会打空或打到别处）—— 一个字节都没改：")
        for line in bad:
            print("   - " + line)
        return 2

    lock_reverse_verify()
    caught = 0
    problems: list[str] = []
    try:
        for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
            path = ROOT / rel
            orig = path.read_bytes()
            orig_sha = sha(path)
            text = orig.decode("utf-8")
            eol = "\r\n" if "\r\n" in text else "\n"
            o = old.replace("\n", eol)
            n = new.replace("\n", eol)
            pat = o[3:] if o.startswith("re:") else re.escape(o)
            text2, hits = re.subn(pat, lambda _m: n, text, count=1)
            if hits != 1:
                problems.append("%d. %s —— 锚点没命中（注入点腐烂了）" % (i, name))
                print("  [%2d/%d] ⚠️  锚点没命中：%s" % (i, len(INJECTIONS), name))
                continue
            wrote = text2.encode("utf-8")
            _PENDING[rel] = (orig, wrote, orig_sha)
            path.write_bytes(wrote)

            rc, out = run_check()

            cur = path.read_bytes()
            if cur != wrote:
                print("  🛑 %s 在验证期间被改动过 —— 拒绝还原，请人工处理！" % rel)
                return 2
            path.write_bytes(orig)
            if sha(path) != orig_sha:
                print("  🛑 %s 还原后 sha256 不符 —— 请人工处理！" % rel)
                return 2
            _PENDING.pop(rel, None)

            if rc != 0 and caught_by(out, want):
                caught += 1
                print("  [%2d/%d] ✅ %s" % (i, len(INJECTIONS), name))
            else:
                why = "判据没红（漏网）" if rc == 0 else "红了但不是这一条（找不到「%s」）" % want
                problems.append("%d. %s —— %s" % (i, name, why))
                print("  [%2d/%d] ❌ %s —— %s" % (i, len(INJECTIONS), name, why))
                for line in out.splitlines():
                    if line.startswith("  [!!]"):
                        print("        " + line.strip())
    finally:
        restore_pending()
        unlock_reverse_verify()

    print()
    if problems:
        print("❌ %d 条注入没被抓住（判据在那些地方是空转的）：" % len(problems))
        for line in problems:
            print("   - " + line)
        return 1
    print(
        "✅ %d/%d 种破坏方式被抓住 —— 判据在这 %d 个点上都不是空转的。"
        % (caught, len(INJECTIONS), len(INJECTIONS))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
