# -*- coding: utf-8 -*-
"""反向验证：`_tools/qa/_check_assign_entry.py` 那些判据**真的抓得住**吗（2026-10-03）。

手法与仓库里其它 `_reverse_verify_*.py` 同一套：**按字节备份 → 注入 → 跑红线（期望非零退出且命中
指定判据）→ 按字节还原 → 校验 sha256**。⛔ 全程不碰 `git checkout --`（那会在真有改动时抹掉工作）。

遵守注入锁的规矩（`_tools/ai/_airepo.py`）：`lock_reverse_verify` / `refuse_if_injecting`。

⚠️ 每个注入点都挑**真会有人这么改**的那条路：
   ① 标签写死回「大车司机 / 挂车司机」（挑中小车司机王强，输入框上方还写着大车司机）；
   ② 过滤退回 `pickVehicle` 两档布尔（small 又被算进大车组）；
   ③ 页签写死两档（名册里只有挂车司机时，第一页还是空白的大车档）；
   ④ 运费模板子弹窗塞回池页面（第二份实现开始长出来）；
   ⑤ 弹窗自己的错误行改用裸 Text（没有红圈叹号，用户看不到被挡下来的原因）；
   ⑥ 详情页 import 换成池页面（入口在，实现却是另一份）；
   ⑦ 详情页那份 VM 拉整池（一进详情页就拉几百条待派单）；
   ⑧ `autoLoadPool` 参数删掉（同上，只是改在 VM 里）；
   ⑨ 名册只在 init 里拉（详情页借的那份 VM 弹窗永远是空的）；
   ⑩ 「派单」改成次要按钮（这一页唯一能把单推走的一步被降级）；
   ⑪ 派单闸门改成 CANCELLABLE（两个按钮的状态范围走散）；
   ⑫ 弹窗从详情页摘掉（按钮点了没反应）；
   ⑬ `confirmAssign` 去掉回调（派完池子不刷新）；
   ⑭ 池页面塞回自己那份弹窗体；
   ⑮ 弹窗函数改名（两个入口各调各的名字）；
   ⑯ 线路支路不说话了 / ⑰ 地点支路不说话了；
   ⑱ 覆盖前不留旧值（没法比「换没换」，只能瞎猜）；
   ⑲ 用户动手后不清旧话（对着他喊错话）；
   ⑳ 提示不画了（长列表里塞在末尾等于没有）；
   ㉑ 单测不再盖这句话；
   ㉒ 判据函数改名（`receiverSwapNotice` 走散）；
   ㉓ 谁都能再写一份 `driverKindLabel`；
   ㉔ `driverKindLabel` 本体改名 / ㉕㉖㉗ 三种车型的名字被改错；
   ㉘ 出处那句「手边是个位置」被删；
   ㉙ 登记表那一行被删 / ㉚ 声明块标题被改 / ㉛ 文档少一节 / ㉜ 反验脚本自己不在。

⚠️ 被硬中断（Ctrl+C / 断电）会留下注入的 bug：跑
`python _tools/qa/_check_reverse_verify_anchors.py --restore` 按注入串还原，⛔ 别改锚点。

用法：
    python _tools/qa/_reverse_verify_assign_entry.py          # 全部跑
    python _tools/qa/_reverse_verify_assign_entry.py --list   # 只列注入点
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import (  # noqa: E402
    lock_reverse_verify,
    refuse_if_injecting,
    unlock_reverse_verify,
)

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_assign_entry.py"

DIALOG = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/AssignDriverDialog.kt"
POOL = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherPoolScreen.kt"
PVM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherPoolViewModel.kt"
DETAIL = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"
CONTACT = "android/app/src/main/java/com/tapmoay/sorders/ui/common/ContactFill.kt"
USERS = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/UsersManageScreen.kt"
CSCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
CVM = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateViewModel.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/common/ContactFillTest.kt"
UNDO = "_tools/qa/_check_delete_undo.py"
REGISTRY = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"
DOC = "docs/changes/BUG-0004.md"
CHECKER = "_tools/qa/_check_assign_entry.py"

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的关键字)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 标签写死回「大车司机 / 挂车司机」（挑中小车司机王强，输入框上方还写着大车司机）",
        DIALOG,
        'label = { Text(driverKindLabel(vm.selectedDriver?.vehicleType ?: pick.ifBlank { null })) },',
        'label = { Text(if (pick == "trailer") "挂车司机" else "大车司机") },',
        "标签经唯一一份 driverKindLabel",
    ),
    (
        "② 过滤退回 pickVehicle 两档布尔（small 又被算进大车组）",
        DIALOG,
        'vm.drivers.filter { (it.vehicleType ?: "") == pick }',
        'vm.drivers.filter { (it.vehicleType == "trailer") == pickVehicle }',
        "弹窗按 vehicleType **真值**过滤",
    ),
    (
        "③ 页签写死两档（名册里只有挂车司机时，第一页还是空白的大车档）",
        DIALOG,
        '                        val kindOrder = listOf("small", "large", "trailer")\n'
        '                        val kinds = kindOrder.filter { k -> vm.drivers.any { (it.vehicleType ?: "") == k } } +\n'
        '                            if (vm.drivers.any { (it.vehicleType ?: "") !in kindOrder }) listOf("") else emptyList()',
        '                        val kinds = listOf("large", "trailer")',
        "档位是数据驱动的",
    ),
    (
        "④ 运费模板子弹窗塞回池页面（第二份实现开始长出来）",
        POOL,
        '    AssignDriverDialog(vm)',
        '    AssignDriverDialog(vm)\n'
        '    if (templatePick) {\n'
        '        AlertDialog(onDismissRequest = {}, confirmButton = {}, text = {})\n'
        '    }',
        "池页面那个运费模板子弹窗跟着搬走了",
    ),
    (
        "⑤ 弹窗自己的错误行改用裸 Text（没有红圈叹号，用户看不到被挡下来的原因）",
        DIALOG,
        'FormErrorLine(vm.error)',
        'vm.error?.let { Text(it) }',
        "弹窗自己的错误行用共用件 FormErrorLine",
    ),
    (
        "⑥ 详情页 import 换成池页面（入口在，实现却是另一份）",
        DETAIL,
        'import com.tapmoay.sorders.ui.dispatcher.AssignDriverDialog\n'
        'import com.tapmoay.sorders.ui.dispatcher.DispatcherPoolViewModel',
        'import com.tapmoay.sorders.ui.dispatcher.DispatcherPoolScreen',
        "详情页引入了共用弹窗与那份 VM",
    ),
    (
        "⑦ 详情页那份 VM 拉整池（一进详情页就拉几百条待派单）",
        DETAIL,
        'DispatcherPoolViewModel(container, autoLoadPool = false)',
        'DispatcherPoolViewModel(container)',
        "详情页那份 VM 是 autoLoadPool = false",
    ),
    (
        "⑧ autoLoadPool 参数删掉（闸门跟着没地方挂）",
        PVM,
        '    private val autoLoadPool: Boolean = true,\n',
        '',
        "VM 真的支持 autoLoadPool",
    ),
    (
        "⑨ 名册只在 init 里拉（详情页借的那份 VM 弹窗永远是空的）",
        PVM,
        '        if (drivers.isEmpty()) loadDrivers()',
        '        // 名册在 init 里拉过了',
        "名册按需拉（loadDrivers）",
    ),
    (
        "⑩ 「派单」改成次要按钮（这一页唯一能把单推走的一步被降级）",
        DETAIL,
        '                if (role == Role.DISPATCHER && order.status in OrderStatusModel.ASSIGNABLE) {\n'
        '                    Button(',
        '                if (role == Role.DISPATCHER && order.status in OrderStatusModel.ASSIGNABLE) {\n'
        '                    OutlinedButton(',
        "「派单」是这一页的主色 Button",
    ),
    (
        "⑪ 派单闸门改成 CANCELLABLE（两个按钮的状态范围走散）",
        DETAIL,
        '                if (role == Role.DISPATCHER && order.status in OrderStatusModel.ASSIGNABLE) {\n'
        '                    Button(',
        '                if (role == Role.DISPATCHER && order.status in OrderStatusModel.CANCELLABLE) {\n'
        '                    Button(',
        "两条闸门同源",
    ),
    (
        "⑫ 弹窗从详情页摘掉（按钮点了没反应）",
        DETAIL,
        '    AssignDriverDialog(assignVm) { vm.load() }',
        '    // 派单弹窗先摘掉',
        "详情页把弹窗挂上了",
    ),
    (
        "⑬ confirmAssign 去掉回调（派完池子不刷新）",
        PVM,
        '    fun confirmAssign(onAssigned: () -> Unit = {}) {',
        '    fun confirmAssign() {',
        "派成之后池子那份 VM 会回调",
    ),
    (
        "⑭ 池页面塞回自己那份弹窗体（谁再抄一份，两份规矩一定走散）",
        POOL,
        '    AssignDriverDialog(vm)',
        '    if (vm.showAssignDialog) {\n'
        '        AlertDialog(onDismissRequest = {}, confirmButton = {}, text = { ExposedDropdownMenuBox { } })\n'
        '    }',
        "池页面改用共用弹窗",
    ),
    (
        "⑮ 弹窗函数改名（两个入口各调各的名字）",
        DIALOG,
        'fun AssignDriverDialog(',
        'fun AssignDriverDialogForPool(',
        "两个入口都用同一个可组合函数名",
    ),
    (
        "⑯ 线路那一支不说话了（挑好的人被换掉，页面一声不吭）",
        CVM,
        '        receiverNotice = receiverSwapNotice(before, ReceiverContact(dongjiaName, dongjiaPhone), "这条线路")',
        '        receiverNotice = null',
        "线路那一支会说话",
    ),
    (
        "⑰ 地点那一支不说话了（同上，另一条来源）",
        CVM,
        '        receiverNotice = receiverSwapNotice(before, c, "这个地点")',
        '        receiverNotice = null',
        "地点那一支也会说话",
    ),
    (
        "⑱ 覆盖前不留旧值（没法比「换没换」，只能瞎猜）",
        CVM,
        '        val before = ReceiverContact(dongjiaName, dongjiaPhone)\n'
        '        dongjiaPhone = a.phone',
        '        dongjiaPhone = a.phone',
        "覆盖前先留了一份值",
    ),
    (
        "⑲ 用户动手改完之后不清旧话（等于对着他喊错话）",
        CVM,
        '        // 用户自己动手改了这一栏 → 上面那句「被线路/地点换掉了」已经过期（留着会与他的操作打架）\n'
        '        receiverNotice = null',
        '        // 用户自己动手改了这一栏 → 上面那句已经过期',
        "用户一动手就清掉那句旧话",
    ),
    (
        "⑳ 提示不画了（长列表里塞在末尾等于没有）",
        CSCREEN,
        '                    vm.receiverNotice?.let { msg ->',
        '                    Spacer(Modifier.height(6.dp))',
        "话画在收货人那两栏正下方",
    ),
    (
        "㉑ 单测不再盖这句话（改文案时没人拦得住）",
        TEST,
        '        assertNull(receiverSwapNotice(cur, cur, "这条线路"))',
        '        assertNull(cur)',
        "单测盖着这句话",
    ),
    (
        "㉒ 判据函数改名（receiverSwapNotice 走散）",
        CONTACT,
        'fun receiverSwapNotice(',
        'fun receiverSwapHint(',
        "判据只有一处（receiverSwapNotice 只有这一个定义）",
    ),
    (
        "㉓ 谁都能再写一份 driverKindLabel（两份规矩走散）",
        DIALOG,
        'fun AssignDriverDialog(',
        'private fun driverKindLabel(t: String?) = "大车司机"\n\n'
        '@Composable\n'
        'fun AssignDriverDialog(',
        "整个 ui 里 driverKindLabel 只有一个定义",
    ),
    (
        "㉔ driverKindLabel 本体改名（唯一来源断掉）",
        USERS,
        'internal fun driverKindLabel(',
        'internal fun driverKindTag(',
        "车型标签的唯一来源 driverKindLabel 还在 UsersManageScreen.kt",
    ),
    (
        "㉕ 小车司机被写成大车司机（small 又变成大车）",
        USERS,
        '    "small" -> "小车司机"',
        '    "small" -> "大车司机"',
        "三种车型的名字都还在：小车司机",
    ),
    (
        "㉖ 大车司机的名字被换掉",
        USERS,
        '    "large" -> "大车司机"',
        '    "large" -> "小车司机"',
        "三种车型的名字都还在：大车司机",
    ),
    (
        "㉗ 挂车司机的名字被换掉（三种车型只剩两种）",
        USERS,
        '    "trailer" -> "挂车司机"',
        '    "trailer" -> "大车司机"',
        "三种车型的名字都还在：挂车司机",
    ),
    (
        "㉘ 出处那句「手边是个位置」被删（本判据的根被拔了）",
        UNDO,
        '提示画在列表**上面**',
        '提示画在列表里',
        "「手边」是个位置那条同款判据还在",
    ),
    (
        "㉙ 登记表那一行被删（归档没登记）",
        REGISTRY,
        '| `BUG-0004` |',
        '| `BUG-000X` |',
        "登记表里有 BUG-0004 这一行",
    ),
    (
        "㉚ 声明块标题被改（会话声明查不到）",
        CLAIM,
        '会话：**BUG-0004',
        '会话：**BUG-000X',
        "AI_WORK_CLAIM.md 里有 BUG-0004 声明块",
    ),
    (
        "㉛ 文档少一节（九节模板缺胳膊）",
        DOC,
        '## ①',
        '## 一',
        "docs/changes/BUG-0004.md 存在且九节齐",
    ),
    (
        "㉜ 反验脚本自己不在（判据再也验不了）",
        CHECKER,
        "REVERSE = ROOT / '_tools/qa/_reverse_verify_assign_entry.py'",
        "REVERSE = ROOT / '_tools/qa/_reverse_verify_assign_entry_x.py'",
        "配套反向验证脚本在",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    if refuse_if_injecting("派单入口（P8/P9/P12）反向验证"):
        return 1

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    lock_reverse_verify()
    caught = 0
    problems: list[str] = []
    try:
        for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
            path = ROOT / rel
            if not path.exists():
                problems.append(f"{name}：找不到 {rel}")
                print(f"\n[{i}] {name}\n  ❌ 找不到 {rel}")
                continue
            orig = path.read_bytes()
            orig_sha = sha(path)
            text = orig.decode("utf-8")
            eol = "\r\n" if "\r\n" in text else "\n"
            if eol != "\n":
                old = old.replace("\n", eol)
                new = new.replace("\n", eol)
            pat = old[3:] if old.startswith("re:") else re.escape(old)
            injected, n = re.subn(pat, new, text, count=1)
            if n != 1:
                problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:40]!r}）")
                print(f"\n[{i}] {name}\n  ❌ 锚点没命中，跳过（注入点腐烂了）")
                continue
            inj_bytes = injected.encode("utf-8")
            path.write_bytes(inj_bytes)
            try:
                rc, out = run_check()
            finally:
                now = path.read_bytes()
                if now != inj_bytes:
                    print(f"\n[{i}] {name}\n  🛑 有别的东西改了 {rel} —— **拒绝还原**，请人工处理！")
                    return 2
                path.write_bytes(orig)
            if sha(path) != orig_sha:
                print(f"\n[{i}] {name}\n  🛑 {rel} 还原后哈希对不上，停手")
                return 2

            hit = f"[!!]   {want}" in out
            if rc != 0 and hit:
                caught += 1
                print(f"\n[{i}] {name}\n  ✅ 被抓到（红线非零退出，命中「{want}」）")
            else:
                why = "红线居然还是绿的" if rc == 0 else f"退出了，但输出里没有「[!!]   {want}」"
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
