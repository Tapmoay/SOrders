# -*- coding: utf-8 -*-
"""CHG-0131 反向验证：「下游定价」甲案的判据真的抓得住破坏吗？

为什么必须反向验证：`_check_downstream_price_cards.py` 断言的全是「某段文本里有什么 / 没有什么」——
「默认价在卡片上改」「一人一行」「删除这条价」「钱的焦糖」「抽屉能滚」。
这些话最容易坏的方式不是"判据写错了"，而是"判据还在，源码悄悄变成另一套写法它照样绿"。
下面每一条都选在**看起来更省事 / 更眼熟**的那条路上：

  ① 大字价不过显示漏斗（直接拼字符串）—— 钱的每一位数都必须过 formatMoney
  ② 保存键底色换成主色绿 —— 这一页的"钱"是焦糖，换成绿就跟别处的主按钮混在一起
  ③ 抽屉里的滚动去掉（人一多就滚不动；错误行也跟表单不同屏）
  ④ 按人行的删除改回旧文案「删除」—— 分不清删的是哪一条价（用户就靠这句话）
  ⑤ 「一人一行」改成「有价才有一行」—— 没单独定过价的人整行消失（用户以为不能给他定价）
  ⑥ 软删那条也算价 —— 回收站里的价又被算进钱里（这是最贵的一种错）
  ⑦ 主色写成派单文书里的旧值 #009663 —— 全仓现值是 ThemeGreen = 0xFF006C43
  ⑧ 把顺手修掉的那条旧红改回去（抽屉去掉 fillMaxHeight）—— 旧判据必须立刻变红

每条都必须被**期望的那一条**判据抓住（判据失败行是 `  [!!]   <标题>`，这里逐字比对标题）。
逐字节备份 + 逐字节还原 + sha256 自证：反验期间源码不许被别的进程动过。
锚点预检不过（命中 0 次或 >1 次）时**一个字节都不改**，直接非零退出。

用法：
    python _tools/qa/_reverse_verify_downstream_price_cards.py          # 全部注入 → 每条都被抓 → 退出码 0
    python _tools/qa/_reverse_verify_downstream_price_cards.py --list   # 只列注入点，不动文件
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, refuse_if_injecting, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_downstream_price_cards.py"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperPricesScreen.kt"
PURE = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/DownstreamPriceCards.kt"
OLD_SHEET = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductCostPriceSheet.kt"

INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 卡片上的大字价不过显示漏斗（直接拼字符串）",
        SCREEN,
        '"¥" + formatMoney(fallback)',
        '"¥" + (fallback ?: "—")',
        "大字价 = ¥ + formatMoney(...)（钱必须过显示漏斗）",
    ),
    (
        "② 保存键的底色从钱的焦糖换成主色绿",
        SCREEN,
        "colors = ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange)),",
        "colors = ButtonDefaults.buttonColors(containerColor = Color(ThemeGreen)),",
        "主按钮底色是钱的焦糖（ButtonDefaults.buttonColors(containerColor = Color(MoneyOrange))）",
    ),
    (
        "③ 抽屉里去掉滚动（人一多就滚不动，错误行也不同屏）",
        SCREEN,
        ".verticalScroll(rememberScrollState())",
        ".padding(bottom = 0.dp)",
        "抽屉体 verticalScroll(rememberScrollState())：人多了能滚",
    ),
    (
        "④ 按人行的删除改回旧文案「删除」（分不清删的是哪条价）",
        SCREEN,
        'TextButton(onClick = { vm.askDelete(own) }, enabled = !vm.acting) { Text("删除这条价") }',
        'TextButton(onClick = { vm.askDelete(own) }, enabled = !vm.acting) { Text("删除") }',
        "按人行里那颗按钮逐字是「删除这条价」",
    ),
    (
        "⑤ 一人一行改成「有价才有一行」（没定过价的人整行消失）",
        PURE,
        "val rows = contacts.map { contact ->",
        "val rows = contacts.filter { c -> personPrice(prices, c.id) != null }.map { contact ->",
        "一人一行的行序跟联系人表一致（contacts.map）",
    ),
    (
        "⑥ 软删的那条也算价（回收站里的价又被算进钱里）",
        PURE,
        "if (own != null && !own.isDeleted) return own.unitPrice",
        "if (own != null) return own.unitPrice",
        "软删的那条不算价（effectiveUnitPrice 先看 !own.isDeleted）",
    ),
    (
        "⑦ 主色写回派单文书里的旧值 #009663",
        SCREEN,
        "accent = Color(ThemeGreen),",
        "accent = Color(0xFF009663),",
        "全仓 ui/ 下没有 #009663（现算 glob：一个文件都不许有）",
    ),
    (
        "⑧ 把顺手修掉的那条旧红改回去（抽屉去掉 fillMaxHeight）",
        OLD_SHEET,
        "Modifier.fillMaxWidth().fillMaxHeight(0.9f).padding(horizontal = 20.dp).padding(bottom = 24.dp),",
        "Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 24.dp),",
        "_check_sheet_form_pages.py 变绿（EXIT 0）",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-X", "utf8", str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def count_hits(text: str, old: str) -> int:
    pat = old[3:] if old.startswith("re:") else re.escape(old)
    return len(re.findall(pat, text))


def anchor_preflight() -> list[str]:
    """每个注入点必须**恰好命中 1 次**：0 次＝锚点腐烂；>1 次＝可能打到别处（假绿）。"""
    bad: list[str] = []
    for name, rel, old, _new, _want in INJECTIONS:
        path = ROOT / rel
        if not path.exists():
            bad.append(f"{name}：找不到 {rel}")
            continue
        # ⚠️ 不能用 Path.read_text(newline=...)：那个参数 Python 3.13 才有；
        #    这里要的是"字节进、不翻译行尾"，所以直接读 bytes 再解码。
        text = path.read_bytes().decode("utf-8", errors="replace")
        hits = count_hits(text, old)
        if hits != 1:
            bad.append(f"{name}：锚点在 {rel} 里命中 {hits} 次（要求恰好 1 次）")
    return bad


def caught_by(out: str, want: str) -> bool:
    return (f"[!!]   {want}" in out) or (f"[!!]   ⛔ {want}" in out)


_PENDING: dict[str, tuple[bytes, bytes, str]] = {}


def restore_pending() -> None:
    """硬中断（Ctrl+C / 断电）后把还挂着的注入按字节还原。"""
    for rel, (orig, _wrote, _sha) in list(_PENDING.items()):
        (ROOT / rel).write_bytes(orig)
        _PENDING.pop(rel, None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    if refuse_if_injecting("下游定价甲案反向验证"):
        return 1

    print("先确认干净状态下是绿的：", end=" ")
    rc, out = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        print(out.strip().splitlines()[-1] if out.strip() else "")
        return 2
    print("✅ 绿")

    bad = anchor_preflight()
    if bad:
        print("🛑 锚点预检不过（这些注入点会打空或打到别处）—— 一个字节都没改：")
        for b in bad:
            print("   -", b)
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
            o = old.replace("\n", eol) if eol != "\n" else old
            n = new.replace("\n", eol) if eol != "\n" else new
            pat = o[3:] if o.startswith("re:") else re.escape(o)
            injected, hits = re.subn(pat, lambda _m: n, text, count=1)
            if hits != 1:
                problems.append(f"{name}：锚点没命中（注入点腐烂）")
                print(f"\n[{i}] {name}\n  ❌ 锚点没命中，跳过")
                continue
            wrote = injected.encode("utf-8")
            _PENDING[rel] = (orig, wrote, orig_sha)
            path.write_bytes(wrote)
            try:
                rc, out = run_check()
            finally:
                cur = path.read_bytes()
                if cur != wrote:
                    print(f"\n[{i}] {name}\n  🛑 有别的东西改了 {rel} —— 拒绝还原，请人工处理！")
                    return 2
                path.write_bytes(orig)
                _PENDING.pop(rel, None)
            if sha(path) != orig_sha:
                print(f"\n[{i}] {name}\n  🛑 {rel} 还原后 sha256 对不上，停手")
                return 2

            if rc != 0 and caught_by(out, want):
                caught += 1
                print(f"\n[{i}] {name}\n  ✅ 被抓到（判据非零退出，命中「{want}」）")
            else:
                why = "判据居然还是绿的（漏网）" if rc == 0 else f"判据红了，但不是这一条（找不到「{want}」）"
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
