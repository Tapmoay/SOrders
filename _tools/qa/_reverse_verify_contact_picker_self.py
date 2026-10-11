#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CHG-0117 · 「选择联系人」弹层里那一行「我自己」的反向验证（判据 `_check_contact_picker_self.py`）。

判据只证明"今天是对的"，证明不了"错了会被抓住"。这里把每一处断言**真的**弄坏一次，
看它是不是真的会红 —— 每一条注入都对应一种"界面上看不出来"的真实故障：

  ① 把「我自己」整项去掉（合并那一步不做了）：判据若只查"零件文件在不在"，这一条会漏过去，
     而用户看到的正是"线路表单里还是没有我自己"（他这次提的就是这一条）。
  ② 姓名 / 电话取反（`/users/me` 的 fullName 与 phone 倒着传）：两栏都非空、界面上一眼看不出，
     只有司机照着拨号时才发现拨的是名字。
  ③ 拿不到也显示空行（把那道 `||` 闸写松）：冒出一行空的「我自己」，
     挑中它＝把空姓名 / 空电话回填给收货人。
  ④ 漏掉一个调用方不传 selfContact：那一个入口就是"没有这一项"（用户点名的线路那一条
     恰好可能是被漏掉的那一个），而且不会有人报故障。
  ⑤ 挑中它去调后端新建联系人：每次下单都在名册里多出一份自己的副本，没人会觉得那是自己建的。
  ⑥ 「本人」标签不再认自己那一行（条件写死 false）：那一行与一条普通联系人长得一模一样，
     用户不知道挑的是自己 —— 而这正是这一单要表达的事。

每条注入**只改一处**、跑完立刻还原；末尾核对被碰过的文件与运行前**逐字节一致**。
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools/ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = ROOT / "_tools/qa/_check_contact_picker_self.py"

SELF_KT = "android/app/src/main/java/com/tapmoay/sorders/ui/common/SelfContact.kt"
SHEET = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ContactPickerSheet.kt"
ADDRESS_SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/AddressScreen.kt"
OC_VM = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateViewModel.kt"
SELF = "_tools/qa/_reverse_verify_contact_picker_self.py"

# ---- 六条注入：每条只动一处 ----

def _drop_self_row(s: str) -> str:
    """① 合并那一步不做了（「我自己」整项消失）。"""
    return s.replace(
        "val rows = remember(contacts, selfContact) { SelfContact.withSelf(contacts, selfContact) }",
        "val rows = remember(contacts, selfContact) { contacts }", 1)


def _swap_name_phone(s: str) -> str:
    """② 姓名 / 电话取反。"""
    return s.replace("of(it.fullName, it.phone)", "of(it.phone, it.fullName)", 1)


def _always_show(s: str) -> str:
    """③ 拿不到也显示空行（那道闸写松成"两样都没有才不显示"）。"""
    return s.replace("if (n.isEmpty() || p.isEmpty()) return null",
                     "if (n.isEmpty() && p.isEmpty()) return null", 1)


def _drop_one_caller(s: str) -> str:
    """④ 漏掉一个调用方不传（线路表单那一条）。"""
    return s.replace("            selfContact = vm.selfContact," + chr(10), "", 1)


def _create_on_pick(s: str) -> str:
    """⑤ 挑中「我自己」时去后端新建一条联系人。"""
    return s.replace(
        "pickedContactId = c.id",
        "pickedContactId = if (SelfContact.isSelf(c)) "
        "container.repo.createContact(c.displayName, c.phone).id else c.id", 1)


def _no_badge(s: str) -> str:
    """⑥ 「本人」标签不再认自己那一行。"""
    return s.replace("if (SelfContact.isSelf(c)) {", "if (false) {", 1)


CASES = [
    ("① 把「我自己」整项去掉（合并那一步不做了）", SHEET, _drop_self_row, "withSelf("),
    ("② 姓名 / 电话取反", SELF_KT, _swap_name_phone, "姓名进姓名"),
    ("③ 拿不到也显示空行（那道闸写松）", SELF_KT, _always_show, "那道闸"),
    ("④ 漏掉一个调用方不传 selfContact", ADDRESS_SCREEN, _drop_one_caller, "AddressScreen.kt"),
    ("⑤ 选中它去调后端新建联系人", OC_VM, _create_on_pick, "pickedContactId = c.id"),
    ("⑥ 「本人」标签不再认自己那一行", SHEET, _no_badge, "「本人」标签"),
]


def read_src(rel: str) -> str:
    """读源码并记住换行风格（末尾还原时按原样写回去）。"""
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def crlf_of(text: str) -> bool:
    return "\r\n" in text


def write_src(rel: str, text: str, crlf: bool) -> None:
    p = ROOT / rel
    if crlf:
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    p.write_text(text, encoding="utf-8", newline="")


def run_judge() -> str:
    r = subprocess.run([sys.executable, str(JUDGE)], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def hit(out: str, want: str) -> bool:
    """只在带 [FAIL] 的行里找关键词：判据的其它输出（标题、✅ 那些）不算命中。"""
    return any(want in line for line in out.splitlines() if "[FAIL]" in line)


def run_all() -> int:
    print(f"== 反向验证：{Path(SELF).name} ==")
    base = run_judge()
    if "[FAIL]" in base:
        print("❌ 前提不成立：判据现在不是全绿（先把它修绿，反向验证才有意义）")
        print(base[-2000:])
        return 1
    print("· 前提成立：判据当前全绿")

    touched: dict[str, tuple[str, bool]] = {}
    bad = 0
    for desc, rel, fn, want in CASES:
        if rel not in touched:
            src = read_src(rel)
            touched[rel] = (src, crlf_of(src))
        src, crlf = touched[rel]
        broken = fn(src)
        if broken == src:
            print(f"[SKIP] {desc}：注入没生效（锚点变了？）")
            bad += 1
            continue
        write_src(rel, broken, crlf)
        try:
            out = run_judge()
        finally:
            write_src(rel, src, crlf)
        if hit(out, want):
            print(f"[OK] {desc} → 判据变红（命中「{want}」）")
        else:
            print(f"[MISSED] {desc}：判据没抓住（期望 [FAIL] 里出现「{want}」）")
            print("\n".join(l for l in out.splitlines() if "❌" in l or "[FAIL]" in l)[:1200])
            bad += 1

    restored = all((ROOT / rel).read_text(encoding="utf-8", errors="replace") == src
                   for rel, (src, _) in touched.items())
    if restored:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")
    else:
        print("❌ 还原检查失败：有文件没还原回去")
        bad += 1
    print()
    if bad:
        print(f"❌ {Path(SELF).name}：{bad} 条注入没被抓住 / 没生效")
        return 1
    print(f"✅ {Path(SELF).name}：{len(CASES)} 条注入全部被抓住，且逐字节还原")
    return 0


def main() -> int:
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    raise SystemExit(main())
