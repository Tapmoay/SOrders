# -*- coding: utf-8 -*-
"""反向破坏用例：CHG-0052（台账 L-17）——「我的账本」顶上那张卡只在本事项的两处地方做了改动，
本脚本**逐条把改动破坏掉**，证明 `_check_ledger_pay_block_gate.py` 真的会红。

## 为什么要有这个脚本
这一刀改的全是「画不画 / 写什么字」这类**看起来一切正常**的东西：
- 支出段那道 `if (vm.isAllCustomers) {` —— 删掉它，**编译一样过**，后端返回的数一模一样，
  连 `_check_shipper_ledger_stats.py` 那种「数字对不对」的红线也**照样全绿**
  （数字没变，变的是它**在什么时候被画出来**）；
- 两个标签的括号 —— `"支出 · 我该付的"` 与 `"支出 · 我该付的（欠公司）"` 都是**合法字符串**，
  编译器一个字的意见都没有，挂回去只会在页面上多两个灰字；
- 反验自己的锚点 —— 把 `_reverse_verify_report_metrics.py` 第 ⑤ 条又改回钉裸标签，
  那条注入就会**永远 SKIP**（源码里找不到老写法 ⇒ 注入失效 ⇒ 反向证明变成空转）。

所以每一条注入都钉一类**具体的坏法**，而不是笼统地"改坏一点"。

## 注入表怎么读
`MUTATIONS` 每项 = `(说明, 文件, 原文, 替换成, 期望关键词)`：
原文在源码里**必须恰好出现 1 次**（否则 `[SKIP]` 并计失败 —— 锚点漂了就等于注入失效）；
跑完立刻**逐字节写回并核对**（`restore_src`），任何一次对不上就 `SystemExit(2)`。
`CREATIONS` 用于「新建一个文件让全仓扫描撞上」这类注入，跑完 `unlink()`。

## 用法
`python _tools/qa/_reverse_verify_ledger_pay_block_gate.py`
（先跑一遍确认源码完好时红线是绿的；任何一条 `[MISS]` 都说明**判据没钉住那条坏法**，
不是"注入没生效"这么简单 —— 要么判据太松，要么注入选错了地方。）
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_ledger_pay_block_gate.py"
SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperLedgerScreen.kt"
VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperLedgerViewModel.kt"
BACKEND = ROOT / "backend/app/api/v1/shipper_ledger.py"
REPORT_CHECK = ROOT / "_tools/qa/_check_report_metrics.py"
REPORT_REV = ROOT / "_tools/qa/_reverse_verify_report_metrics.py"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
CHG = ROOT / "docs/changes/CHG-0052.md"
NEWPAGE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/_LegacyPayLabel.kt"

NL = chr(10)
DQ = chr(34)
PAY_LABEL = "支出 · 我该付的"
PAY_LABEL_OLD = PAY_LABEL + "（欠公司）"
RECV_LABEL = "收入 · 我该收的"
RECV_LABEL_OLD = RECV_LABEL + "（下游欠我）"

# 支出段那两行（判据逐字钉的就是这两行；拆闸门 / 换判据都从它下手）
PAY_OPEN = "        if (vm.isAllCustomers) {" + NL + "            Spacer(Modifier.height(6.dp))" + NL
DIVIDER_LINE = "            if (vm.isAllCustomers) HorizontalDivider(Modifier.padding(vertical = 10.dp))"
MEMBER_GATE = "        if (s?.isMember == true) {" + NL
VM_GATE = "    val isAllCustomers: Boolean" + NL + "        get() = selectedCustomer == null" + NL
SEL_CUST = (
    "    fun selectCustomer(key: String?) {" + NL
    + "        selectedCustomerKey = if (key != null && key == selectedCustomerKey) null else key" + NL
    + "        load()" + NL
    + "    }" + NL
)
COUNTER_PAREN = DQ + "（" + DQ + " + s.settlements + " + DQ + " 笔核销）" + DQ

# (说明, 文件, 原文, 替换成, 期望关键词)
# ⚠️ 每条原文都必须在文件里**恰好出现 1 次**（判据脚本自己也是这么钉的）。
MUTATIONS = [
    (
        "① 支出段那道闸门整个拆掉（`if (vm.isAllCustomers) {` → `if (true) {`）",
        SCREEN,
        PAY_OPEN,
        "        if (true) {" + NL + "            Spacer(Modifier.height(6.dp))" + NL,
        "支出块的头两行逐字",
    ),
    (
        "② 闸门换了个判据（标题写着某个人、下面却另算一套）",
        SCREEN,
        PAY_OPEN,
        "        if (vm.selectedCustomer != null || vm.isAllCustomers) {" + NL
        + "            Spacer(Modifier.height(6.dp))" + NL,
        "支出块的头两行逐字",
    ),
    (
        "③ 分隔线不再跟闸门走（只剩一段时顶上还横一条线）",
        SCREEN,
        DIVIDER_LINE,
        "            HorizontalDivider(Modifier.padding(vertical = 10.dp))",
        "分隔线也走同一闸门",
    ),
    (
        "④ 收入段那道闸门被换成账号级的 `vm.isMember`（把两件事混成一件）",
        SCREEN,
        MEMBER_GATE,
        "        if (vm.isMember) {" + NL,
        "收入段仍由",
    ),
    (
        "⑤ 支出那个数被换成别的字段（数还在、意思变了）",
        SCREEN,
        "s?.unpaid",
        "s?.payable",
        "未付那个数还是",
    ),
    (
        "⑥ 支出标签后面又把括号挂回去（推翻 CHG-0026 的那半条被还原）",
        SCREEN,
        "                " + DQ + PAY_LABEL + DQ + ",",
        "                " + DQ + PAY_LABEL_OLD + DQ + ",",
        "带括号的老写法全仓代码 0 处",
    ),
    (
        "⑦ 收入标签也把括号挂回去（另一侧）",
        SCREEN,
        "                " + DQ + RECV_LABEL + DQ + ",",
        "                " + DQ + RECV_LABEL_OLD + DQ + ",",
        "带括号的老写法全仓代码 0 处",
    ),
    (
        "⑧ 副行那个**计数**括号被当成标签括号一起删掉",
        SCREEN,
        COUNTER_PAREN,
        "s.settlements.toString() + " + DQ + " 笔核销" + DQ,
        "笔核销）",
    ),
    (
        "⑨ VM 里那个具名判据被删（闸门改读别的表达式）",
        VM,
        VM_GATE,
        "    // isAllCustomers 被删掉了" + NL,
        "VM 里那个具名判据在",
    ),
    (
        "⑩ 换人不再重取统计（`selectCustomer` 里的 `load()` 被拿掉）",
        VM,
        SEL_CUST,
        "    fun selectCustomer(key: String?) {" + NL
        + "        selectedCustomerKey = if (key != null && key == selectedCustomerKey) null else key" + NL
        + "    }" + NL,
        "换人仍会重取统计",
    ),
    (
        "⑪ 后端被塞进展示口径（服务端也来管「这一段画不画」）",
        BACKEND,
        "_customer_filter(stmt, customer_name, customer_phone)",
        "_customer_filter(stmt, customer_name, customer_phone)  # isAllCustomers",
        "后端这次一个字没改",
    ),
    (
        "⑫ 既有红线没随动：括号老写法常量又改回新名字（下一个人会以为老写法才是老写法）",
        REPORT_CHECK,
        "PAY_LABEL_OLD = " + DQ + PAY_LABEL_OLD + DQ,
        "PAY_LABEL_ANCIENT = " + DQ + PAY_LABEL_OLD + DQ,
        "已把括号写法收成",
    ),
    (
        "⑬ 反验第 ⑤ 条又改回钉裸标签（那条注入从此永远 SKIP）",
        REPORT_REV,
        "s.replace('" + DQ + PAY_LABEL + DQ + "', '" + DQ + PAY_LABEL_OLD + DQ + "', 1)",
        "s.replace('" + DQ + PAY_LABEL_OLD + DQ + "', '" + DQ + PAY_LABEL_OLD + DQ + "', 1)",
        "第 ⑤ 条改成",
    ),
    (
        "⑭ README 那一行的链接被拆掉（登记簿链接失效）",
        README,
        "[CHG-0052.md](CHG-0052.md)",
        "[CHG-0052.md](#)",
        "README 登记簿有 CHG-0052 行",
    ),
    (
        "⑮ `AI_WORK_CLAIM` 里那条条目被改名（这一轮的工作痕迹抹了）",
        CLAIM,
        "会话：**CHG-0052 ",
        "会话：**CHG-9999 ",
        "AI_WORK_CLAIM 有本事项条目",
    ),
    (
        "⑯ CHG 文档的 Boundary 结论被改成别的一档",
        CHG,
        "- **结论**：**PRESENTATION（展示层）**",
        "- **结论**：**L1（主，局部行为）**",
        "Boundary 结论逐字",
    ),
    (
        "⑰ 「不回去改旧 CHG、推翻由本文件声明」被改成沿用它的括号修法",
        CHG,
        "（历史快照）**不改** —— 推翻由本文件声明。",
        "（历史快照）**不改** —— 沿用它的括号修法。",
        "推翻 CHG-0026",
    ),
]

# (说明, 路径, 内容, 期望关键词) —— 跑完 unlink()
CREATIONS = [
    (
        "⑱ 新建一个还带着括号标签的页面（全仓扫描必须点名它）",
        NEWPAGE,
        "package com.tapmoay.sorders.ui.shipper" + NL + NL
        + "// ⛔ 反验注入用的假文件：一个还按 P25 老写法带括号的标签（必须被全仓扫描点名）" + NL
        + "internal const val LEGACY_PAY_LABEL = " + DQ + PAY_LABEL_OLD + DQ + NL,
        "带括号的老写法全仓代码 0 处",
    ),
]

def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out


def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**（R3-07b）：写回后重新读回来逐字节比，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是。
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
            restore_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    for label, path, content, expect in CREATIONS:
        if path.exists():
            print(f"  [SKIP] {label} —— 文件已存在，先手动删掉再跑")
            bad += 1
            continue
        path.write_text(content, encoding="utf-8")
        try:
            hit, detail = verdict(expect)
        finally:
            path.unlink()
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    total = len(MUTATIONS) + len(CREATIONS)
    print()
    if bad:
        print(f"❌ {bad} / {total} 条注入没有让判据变红（注入本身可能失效了）")
        return 1
    print(f"✅ 全部 {total} 条注入都让判据按预期变红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
