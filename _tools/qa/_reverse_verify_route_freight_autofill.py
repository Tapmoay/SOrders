#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""反向验证：派单时按路线自动带价（CHG-0129）—— 14 种破坏方式都得被抓。

判据全绿不等于判据盯着东西：_tools/qa/_check_route_freight_autofill.py 里每一条断言都可能
写成空转（路径写错、字符串少一个空格、顺序比较反了、条数写法变了）。
这个脚本逐条**真的把代码改坏**，再跑一遍判据：必须由**期望的那一条**报红；改回原样后必须全绿。

## 规矩（照 _tools/qa/_reverse_verify_module_visibility.py）
1. 只按字节备份、按字节还原 —— ⛔ 不用 git checkout --（工作区里有别人未提交的改动，抹掉就没了）。
2. 还原后 sha256 逐个比对，不符立刻报 2（不许「看起来还原了」）。
3. 注入前先跑一次判据：干净状态必须绿（没有基线就没有对照）。
4. 注入前锚点唯一性预检：原文必须**恰好命中 1 次**（0 次＝注入点腐烂；>1 次＝可能打到别人身上＝假绿）。
5. 任何一条腐烂都要报出来，不许静默跳过。

硬中断（Ctrl+C / 断电）后现场恢复：python _tools/qa/_check_reverse_verify_anchors.py --restore

用法：python _tools/qa/_reverse_verify_route_freight_autofill.py [--list]
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
CHECK = ROOT / "_tools" / "qa" / "_check_route_freight_autofill.py"

SVC = "backend/app/services/freight_route_autofill.py"
API = "backend/app/api/v1/freight_templates.py"
KTP = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/FreightAutofill.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherPoolViewModel.kt"
DIALOG = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/AssignDriverDialog.kt"

# (说明，文件，原文，替换成，期望被哪条判据标签抓到)
# 说明那句话就是「真会有人这么改」的理由。
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    # ---- ① 按 route_id 匹配：绑定的路线一旦不再优先，界面照样带得出钱，只是带错那一条 ----
    (
        "把「绑了这条路线」降级成「只有终点文字对得上」：价目明明绑了路线，"
        "排序时却和别的价目平起平坐 —— 同一条路线上有价格一价格二价格三时就开始乱挑",
        SVC,
        "return ROUTE_BOUND",
        "return ROUTE_TEXT",
        "价目绑的就是这条路线",
    ),
    (
        "这一单的路线编号不再来自「地址与联系人」（改成空元组）：route_id 那一维永远命中不了，"
        "整条功能静默退化成按终点文字比对",
        SVC,
        "route_ids=tuple(sorted(route_ids_of(db, addr)))",
        "route_ids=()",
        "这一单的路线编号来自「地址与联系人」",
    ),
    (
        "接口上 closest 这个开关写反：老的报价调用（不传 closest）被静默换到新语义上，"
        "待定价页那句「为什么算不出来」跟着变 —— 谁都不会报错",
        API,
        "if not closest:",
        "if closest:",
        "不传 closest 时走老路",
    ),
    # ---- ② 手改优先：自动值盖掉人填的数，用户当场就炸，但代码不报错 ----
    (
        "手改优先那行改成恒 true（永远允许覆盖）：派单员填完运费、换一下司机，"
        "自动带价回来就把人填的数盖掉了 —— 用户 2026-10-15 明确不许",
        KTP,
        "fun shouldOverwriteFreight(touchedByHand: Boolean): Boolean = !touchedByHand",
        "fun shouldOverwriteFreight(touchedByHand: Boolean): Boolean = true",
        "手改优先就一行",
    ),
    (
        "在途响应回来时不再复查手改：网络慢的时候用户已经手填了，"
        "迟到的响应照样把 assignFreight 改回自动值（界面上一闪，人根本反应不过来）",
        VM,
        "if (!shouldOverwriteFreight(freightTouchedByHand)) return@launch",
        "if (false) return@launch",
        "在途响应回来时",
    ),
    # ---- ③ 取最贴近：车型从「只排序」偷偷变成「筛子」，或者干脆不筛分类 ----
    (
        "别的分类的价目不再出局（CAT_OTHER 当 CAT_ANY 用）：这条路线没写过这类货的价，"
        "界面却拿另一类货的价顶上 —— 钱错得静悄悄",
        SVC,
        "return CAT_OTHER",
        "return CAT_ANY",
        "别的分类的价目直接出局",
    ),
    (
        "参选名单里加一个车型条件（拿车型当筛子）：大车司机遇上只写了小车价的路线，"
        "一毛钱都带不出来，还告诉他「这条路线没有价目」",
        SVC,
        "usable = [s for s in on_route if s.category_hit != CAT_OTHER]",
        "usable = [s for s in on_route if s.category_hit != CAT_OTHER and s.vehicle_hit != VEH_OTHER]",
        "车型只参与排序、不参与筛",
    ),
    (
        "平手那句说明再也不会出现（门槛抬到 1000）：同一条路线上有两条一样贴近时静默挑一条，"
        "用户看不见「为什么是这个价」",
        SVC,
        "if best.ties > 1:",
        "if best.ties > 1000:",
        "平手多于一条时必须说出来",
    ),
    # ---- ④ 显示「选了谁」：一句话掉了，界面就只剩一个光秃秃的数 ----
    (
        "接口不再把 why 回给界面（改成空串）：钱照带，但用户看不到选了哪一条、为什么是它",
        API,
        "why=why_text(best),",
        'why="",',
        "接口把 why 回给界面",
    ),
    (
        "带出价之后不再写提示（autoFreightHint 清空）：钱带出来了，界面上一句解释都没有",
        VM,
        "autoFreightHint = autoHint(a)",
        'autoFreightHint = ""',
        "带出价之后把这句话写进提示",
    ),
    (
        "抽屉里那一行干脆不画（条件写死 false）：VM 里算好的说明一个字都到不了用户眼前，"
        "而判据如果只看 VM 就会以为显示出来了",
        DIALOG,
        "if (vm.autoFreightHint.isNotBlank()) {",
        "if (false) {",
        "抽屉里真的把这一行画出来",
    ),
    # ---- ⑤ 匹配不上就什么也不填：拿 0 或兜底值顶上 ----
    (
        "后端没挑到价目时拿 0 顶上（下面那三句「什么都不带」的理由就成了摆设）："
        "用户以为这单运费 0 元，实际上是没有匹配上",
        KTP,
        "val m = q?.matched ?: return null",
        'val m = q?.matched ?: return AutoFreight(fee = "0", templateId = 0L, templateName = "", why = "")',
        "Kotlin：没 matched / 金额空白都是 null",
    ),
    # ---- ⑥ 只读与「钱只算一处」：悄悄多一个写入口 / 把司机的钱混进来 ----
    (
        "自动带价这一路顺手写一次库（挑完价目 db.commit()）：查询接口变成写接口，"
        "只读承诺（R4-25）当场作废，而且没人会注意到",
        SVC,
        "return Best(",
        "db.commit()\n        return Best(",
        "自动带价这一路只读",
    ),
    (
        "服务层 import 司机的计费（from app.services import driver_pay）："
        "货主运费和司机应得混进同一条链路，以后谁改哪边都怕动到另一边",
        SVC,
        "from __future__ import annotations",
        "from __future__ import annotations\nfrom app.services import driver_pay",
        "新服务不碰司机的钱",
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
    """判据那一行是不是「这一条」：房规的形状是  [!!]   <标签>。"""
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
        print()
        print("共 %d 条注入。" % len(INJECTIONS))
        return 0

    if refuse_if_injecting("派单时按路线自动带价（CHG-0129）反向验证"):
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
