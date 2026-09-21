"""反向验证：`_tools/qa/_check_order_list_ui.py` 那些判据**真的抓得住**吗（2026-09-22）。

手法与仓库里其它 `_reverse_verify_*.py` 同一套：**按字节备份 → 注入 → 跑红线（期望非零退出且命中
指定判据）→ 按字节还原 → 校验 sha256**。⛔ 全程不碰 `git checkout --`（那会在真有改动时抹掉工作）。

并遵守注入锁的规矩（`_tools/ai/_airepo.py`）：
· `lock_reverse_verify` —— 上锁期间并发的**检查**会拒绝出结论（源码故意脏着，结论不可信）；
· `refuse_if_injecting` —— 别人的反向验证正在跑时，本脚本也拒绝开跑。

⚠️ 每个注入点都选在**旧判据不看的地方**，否则证明不了判据真的在管这件事：
   ①③ 打在「缺省档怎么写」上（旧写法是字面量 0）；
   ⑤⑥⑦ 打在"控件画在哪"上（顶栏 vs 列表里、第一行 vs 最后一行）；
   ⑧ 打在卡片共用的两个槽**本身**上（不是某一页的调用点）；
   ⑨⑩⑪ 打在详情页单号那一句的**写法**上（同一行 vs 两行、字号、走不走共用实现）。

用法：
    python _tools/qa/_reverse_verify_order_list_ui.py          # 全部跑
    python _tools/qa/_reverse_verify_order_list_ui.py --list   # 只列注入点
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
CHECK = ROOT / "_tools" / "qa" / "_check_order_list_ui.py"
UI = "android/app/src/main/java/com/tapmoay/sorders/ui/"
DISP_VM = UI + "dispatcher/DispatcherOrdersViewModel.kt"
DISP_SCREEN = UI + "dispatcher/DispatcherOrdersScreen.kt"
SHIP_VM = UI + "shipper/ShipperOrdersViewModel.kt"
SHIP_SCREEN = UI + "shipper/ShipperOrdersScreen.kt"
CARD_KT = UI + "common/OrderCard.kt"
DETAIL_KT = UI + "order/OrderDetailScreen.kt"
WINDOW_BASE = UI + "common/OrderWindowViewModel.kt"

DEFAULT_WANT = "DISPATCH_TABS：缺省档 = 「派单中」（第 2 格，下标 1）"
ITEMS_ANCHOR = "                        items(vm.orders, key = { it.id }) { order ->"

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的关键字)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 日期窗口退回「下标判据」（档位一重排就挂到别的档上，两边都不报错）",
        WINDOW_BASE,
        "    val datedTab: Boolean get() = currentTab.dated",
        "    val datedTab: Boolean get() = tab == 3 || tab == 4",
        "全库没有 `tab == 3 || tab == 4` 这种下标判据了",
    ),
    (
        "② 派单员缺省档换成「已接单」（用户明说缺省不进全部、是派单中）",
        DISP_VM,
        'OrderWindowViewModel(container, DISPATCH_TABS, "PENDING_DISPATCH")',
        'OrderWindowViewModel(container, DISPATCH_TABS, "ACCEPTED")',
        DEFAULT_WANT,
    ),
    (
        "③ 缺省档给一个名册里**不存在**的状态名（下标算不出来 → 静默指错档）",
        DISP_VM,
        'OrderWindowViewModel(container, DISPATCH_TABS, "PENDING_DISPATCH")',
        'OrderWindowViewModel(container, DISPATCH_TABS, "ALL")',
        DEFAULT_WANT,
    ),
    (
        "④ 货主的「已接单」挪回第 3 格（默认档就不在第 2 格了）",
        SHIP_VM,
        '    OrderTab("ACCEPTED", "已接单"),\n    OrderTab("PENDING_DISPATCH", "派单中"),',
        '    OrderTab("PENDING_DISPATCH", "派单中"),\n    OrderTab("ACCEPTED", "已接单"),',
        "SHIPPER_TABS：缺省档 = 「已接单」（第 2 格，下标 1）",
    ),
    (
        "⑤ 顶栏的时间药丸被拿掉（空列表时用户换不了档）",
        DISP_SCREEN,
        "                        DatePresetPill(label = vm.periodWord, onClick = { vm.showDatePresets = true })",
        "",
        "派单员「订单管理」：药丸在 `items(` **之前**",
    ),
    (
        "⑥ 旧的横滑胶囊行回来（用户已经否掉的形态）",
        DISP_SCREEN,
        ITEMS_ANCHOR,
        "                        DateRangeFilter(onChange = { _, _ -> })\n" + ITEMS_ANCHOR,
        "派单员「订单管理」：旧的横滑胶囊行",
    ),
    (
        "⑦ 截断提示挪回列表第一行（又把第一张单推下去了）",
        SHIP_SCREEN,
        ITEMS_ANCHOR,
        '                        if (vm.maybeTruncated) { item { TruncationNote(limit = ORDER_LIST_LIMIT, howToSeeMore = "x") } }\n'
        + ITEMS_ANCHOR,
        "货主「我的订单」：提示在 `items(` **之后**",
    ),
    (
        "⑧ 截断上限自己编一个数（界面上的数字不再等于真实上限）",
        SHIP_SCREEN,
        "                                    limit = ORDER_LIST_LIMIT,",
        "                                    limit = 999,",
        "货主「我的订单」：截断时**说出来**",
    ),
    (
        "⑨ 卡片两个槽对调（编辑跑到左边、反向动作跑到右边）",
        CARD_KT,
        "                leading()\n                Spacer(Modifier.weight(1f))\n                extra()",
        "                extra()\n                Spacer(Modifier.weight(1f))\n                leading()",
        "左槽先画、右槽靠边",
    ),
    (
        "⑩ 状态徽章挪回单号那一行（20 个字符挤不下 = 折行，就是用户说的错位）",
        DETAIL_KT,
        '                    if (copied) {\n                        Text(\n                            "已复制",',
        '                    OrderStatusChip(order.status)\n'
        '                    if (copied) {\n                        Text(\n                            "已复制",',
        "单号与状态徽章**不再同一行**",
    ),
    (
        "⑪ 单号缩字号（用户明说「不要缩小」）",
        DETAIL_KT,
        '"#" + order.orderNo,\n                        style = MaterialTheme.typography.titleLarge,',
        '"#" + order.orderNo,\n                        style = MaterialTheme.typography.titleSmall,',
        "单号仍是 `titleLarge`",
    ),
    (
        "⑫ 长按复制自己写一份（不走共用实现 → 迟早两套行为）",
        DETAIL_KT,
        'copyTextToClipboard(ctx, "单号", order.orderNo)',
        'myOwnClipboard(ctx, "单号", order.orderNo)',
        "长按走共用的 `copyTextToClipboard`",
    ),
    (
        "⑬ 空态不再指路（默认「今天」+ 今天没单 = 用户以为这一页坏了）",
        DISP_SCREEN,
        '                                "的订单 —— 点右上角可以换一段时间"',
        '                                "的订单"',
        "派单员「订单管理」：空列表时文案指向右上角那个药丸",
    ),
    (
        "⑭ 「全部」不给了时间筛选（用户明说「全部我们也要有时间的筛选」）",
        DISP_VM,
        '    OrderTab(null, "全部", dated = true),',
        '    OrderTab(null, "全部"),',
        "DISPATCH_TABS：「全部」**也有**时间筛选",
    ),
    (
        "⑮ 给「正在进行」的档也套上日期窗口（积压的老单会静默消失）",
        DISP_VM,
        '    OrderTab("PENDING_DISPATCH", "派单中"),',
        '    OrderTab("PENDING_DISPATCH", "派单中", dated = true),',
        "DISPATCH_TABS：进行中的档（缺省档 = PENDING_DISPATCH）**没有**时间控件",
    ),
    (
        "⑯ 不自动退档了（切进有窗口的档直接取数 = 今天没单就空着）",
        WINDOW_BASE,
        "DatePresets.pickWindow(DatePresets.ORDER_PRESET_LADDER) { label ->",
        "DatePresets.pickWindow(listOf(DatePresets.ALL)) { label ->",
        "自动挡的挑窗口只有一处",
    ),
    (
        "⑰ 手动挑过档位也不再记（下一轮盘点会把用户的选择顶掉）",
        WINDOW_BASE,
        "        userPickedPreset = true\n        windowSettled = true // 用户已经表态 = 窗口就算定下来了",
        "        windowSettled = true // 用户已经表态 = 窗口就算定下来了",
        "手动挑过档位就**永不自动改**",
    ),
    (
        "⑱ 盘点期间不挡屏（先闪一批上一档的单，就是用户报过的「闪两下」）",
        DISP_SCREEN,
        "                    vm.datedTab && !vm.windowSettled -> LoadingBox()\n",
        "",
        "派单员「订单管理」：盘点期间整页 loading",
    ),
    (
        "⑲ 本地再抄一份阶梯（两个页面迟早各退各的档）",
        DISP_VM,
        "class DispatcherOrdersViewModel(container: AppContainer) :",
        "private val ORDER_PRESET_LADDER = listOf(DatePresets.TODAY, DatePresets.YESTERDAY)\n"
        "class DispatcherOrdersViewModel(container: AppContainer) :",
        "共享的长阶梯只有一处定义",
    ),
    (
        "⑳ 自动退档不再看「用户已经手动挑过」（下一次切档就把他的选择顶掉）",
        WINDOW_BASE,
        "if (currentTab.dated && !userPickedPreset) {",
        "if (currentTab.dated) {",
        "**每次**进带窗口的档位都重新找有单的那一段",
    ),
    (
        "㉑ 退回「只挑一次」（真机抓到过：先点全部、再点已送达就停在空窗口上）",
        WINDOW_BASE,
        "if (currentTab.dated && !userPickedPreset) {",
        "if (currentTab.dated && !userPickedPreset && !autoPickedPreset) {",
        "没有「只挑一次」那个开关",
    ),
    (
        "㉒ 子类不再继承共用内核（又要自己养一套档位+窗口状态机）",
        DISP_VM,
        '    OrderWindowViewModel(container, DISPATCH_TABS, "PENDING_DISPATCH") {',
        "    {",
        "两个订单列表都继承了那个内核",
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

    if refuse_if_injecting("订单列表 UI 反向验证"):
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
