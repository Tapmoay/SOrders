"""反向验证：把 CHG-0081 那条判据逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这条规矩坏掉的方式**全部不报错**——
删掉 `newOrderPlayer.stop()` 只是"接完单了号角还在响"，数据一个字没错；
把 `enabled = !locked` 改成 `enabled = true` 只是"连点两下被后端 400"；
把 `ackErrorOrderId` 那道过滤删掉只是"一张单失败、满屏卡片冒红字"；
把三个状态挪到 `init { }` 之后更是**编译照样过**，要到用户打开这一页才崩。
机器判据本身也有一节是"扫全仓"（`Text("确认接单"` 只许出现在两处），
这种清单不验证，就可能因为"目录扫不到 / 只在两处扫"而永远绿。

用法：python _tools/qa/_reverse_verify_driver_card_ack.py    # 全部报红 → 退出码 0
"""
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_driver_card_ack.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CARD = AND / "ui/common/OrderCard.kt"
SCREEN = AND / "ui/driver/DriverOrdersScreen.kt"
VM = AND / "ui/driver/DriverOrdersViewModel.kt"
COMMON_DIR = AND / "ui/common"

#: 在其它页面上冒出来的第三颗「确认接单」（新建文件用；这两段都是合法 Kotlin 片段）
_LEAK = (
    "package com.tapmoay.sorders.ui.common\n\n"
    "import androidx.compose.material3.Text\n\n"
    "internal fun leakAckButton() {\n"
    '    Text("确认接单", style = androidx.compose.material3.MaterialTheme.typography.titleSmall)\n'
    "}\n"
)

#: 三个状态（含各自的 KDoc）在 VM 里**实际**占的那一段。
#: ⚠️ 不用写死的字符串：三个状态之间夹着两段 KDoc，写死就与源码脱钩（实测第一次这么写时
#:    `count == 0`，注入直接 SKIP）。这里从源码里**现取**，取得不对就在 main 里直接报出来。
_STATES_RE = re.compile(
    r"\n    var ackingOrderId by mutableStateOf[\s\S]*?"
    r"\n    var ackErrorOrderId by mutableStateOf<Long\?>\(null\)\n        private set\n"
)
#: 挪位置那条注入的期望关键词（三个状态名共用一句报错文案）
_MOVE_EXPECT = "声明在 init **之前**"
#: 「卡片里那一句调用位置/数量不对」的期望关键词（插一句、搬一句、删一句都落在这一条上）
_CALL_EXPECT = "恰好一处"
#: 卡片里 `bottomAction()` 调用**前后那两行注释 + 调用本身**的逐字原文。
#: 搬位置那条注入要连注释一起搬，所以它直接复用判据里那份文字（少一个引号就 count==0 → SKIP）。
_CALL_BLOCK = (
    "                extra()\n"
    "            }\n"
    "            // 卡片**最底下**那一整行：留给\"这一张单现在要做的那件事\"（整宽主行动）。\n"
    "            // 默认不画 → 其它列表（派单员待派池 / 订单管理 / 我的订单）与以前**逐像素一样**。\n"
    "            bottomAction()\n"
)

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    # —— 卡片这一侧 ——
    (
        "把 bottomAction() 那句调用删掉（只加参数不调用 = 加了跟没加一样）",
        CARD,
        "            bottomAction()\n",
        "",
        _CALL_EXPECT,
    ),
    (
        "把 bottomAction() 挪到动作行**之前**（那颗按钮跑到左/右图标槽上面去了）",
        CARD,
        "            }\n            // 卡片**最底下**那一整行",
        "            }\n            bottomAction()\n            // 卡片**最底下**那一整行",
        _CALL_EXPECT,
    ),
    # 注：「把调用搬到卡片最上面」那条是**两步注入**（先删原处、再插开头），
    #     放在 main() 里单列，见 `_CALL_BLOCK` 那一段。
    (
        "把签名的默认值改成非空（于是**每个**列表都会被塞一颗按钮）",
        CARD,
        "bottomAction: @Composable ColumnScope.() -> Unit = {}",
        "bottomAction: @Composable ColumnScope.() -> Unit = { Text(\"确认接单\") }",
        "签名里那个默认值**确实**是空的",
    ),
    # —— 司机任务页这一侧 ——
    (
        "状态门换成硬写 DISPATCHED（后端状态改名时两处不再同一把尺）",
        SCREEN,
        "order.status in OrderStatusModel.ACKABLE && !order.isNewForDriver",
        'order.status == "DISPATCHED" && !order.isNewForDriver',
        "状态门取自 OrderStatusModel.ACKABLE",
    ),
    (
        "把状态门整个删掉（已完成那一栏的单也长出一颗接单键）",
        SCREEN,
        "if (vm.ordersTab == 0 && order.status in OrderStatusModel.ACKABLE && !order.isNewForDriver) {\n",
        "if (true) {\n",
        "条件带『进行中那一栏",
    ),
    (
        "把 `vm.ordersTab == 0` 换成 `vm.tab == 0`（切栏那一瞬间画在别人栏上）",
        SCREEN,
        "if (vm.ordersTab == 0 && order.status in OrderStatusModel.ACKABLE",
        "if (vm.tab == 0 && order.status in OrderStatusModel.ACKABLE",
        "用 ordersTab，不是 tab",
    ),
    (
        "删掉『新任务标还在时不给接单键』那道冗余门",
        SCREEN,
        "&& !order.isNewForDriver",
        "",
        "新任务标还在时也不给接单键",
    ),
    (
        "点下去不调 ack（按钮变成装饰）",
        SCREEN,
        "onClick = { vm.ack(order) }",
        "onClick = { }",
        "点它调 vm.ack(order)",
    ),
    (
        "把置灰删掉（连点两下 → 后端 CAS 判 400，司机看到的像系统坏了）",
        SCREEN,
        "enabled = !locked,",
        "enabled = true,",
        "请求在飞时置灰",
    ),
    (
        "把『哪张单在飞』的判断去掉（点哪张都在转圈）",
        SCREEN,
        "val busy = vm.ackingOrderId == order.id",
        "val busy = vm.ackingOrderId != null",
        "在飞的那一张画转圈",
    ),
    (
        "按单号过滤删掉（一张单失败 → 所有卡片底下同时冒同一句红字）",
        SCREEN,
        "if (vm.ackErrorOrderId == order.id) vm.ackError else null",
        "vm.ackError",
        "Screen 按单号过滤再画那句话",
    ),
    (
        "把 56dp 压成 40dp（主行动被压成 §4.2 那排次要动作的高度，与详情页不再同高）",
        SCREEN,
        "modifier = Modifier.fillMaxWidth().padding(top = 10.dp).height(56.dp)",
        "modifier = Modifier.fillMaxWidth().padding(top = 10.dp).height(40.dp)",
        "整宽 + 56dp",
    ),
    (
        "少了 CheckCircle 的 import（编译直接红——上次就是这么红的）",
        SCREEN,
        "import androidx.compose.material.icons.filled.CheckCircle\n",
        "",
        "import 了 CheckCircle",
    ),
    # —— VM 这一侧 ——
    (
        "成功后不停播报（接完单号角还在喊『来单了』，司机会怀疑接上没有）",
        VM,
        "                container.newOrderPlayer.stop()\n",
        "",
        "停掉「来单了」播报",
    ),
    (
        "成功后不通知别的页面（详情页/角标还显示旧状态）",
        VM,
        "                container.realtimeHub.notifyOrdersChanged()\n",
        "",
        "告诉别的页面状态变了",
    ),
    (
        "把并发守卫删掉（两个请求同时在飞，界面说不清谁成了）",
        VM,
        "        if (ackingOrderId != null) return\n",
        "",
        "并发守卫",
    ),
    (
        "换个写法：按下标换那一条（load() 期间列表变了就写到别人头上）",
        VM,
        "orders = orders.map { if (it.id == updated.id) updated else it }",
        "orders = orders.toMutableList().also { it[0] = updated }",
        "按 id",
    ),
    (
        "失败后不重拉列表（把过期状态留在屏幕上，他只会再点一次）",
        VM,
        "                load()\n            } finally {",
        "            } finally {",
        "把列表拉回真相",
    ),
    (
        "失败时不记是**哪一张单**的（一句错挂在所有卡上）",
        VM,
        "                ackErrorOrderId = order.id\n",
        "",
        "哪一张单",
    ),
    (
        "把 ack 的错写进页面级 error（渲染门拿它顶掉整个列表，连单都看不见了）",
        VM,
        "                ackError = toApiException(e).message\n",
        "                error = toApiException(e).message\n",
        "ack() 体内没有任何一句写页面级 error",
    ),
]

#: 需要**新建文件**的注入（「全仓只有两处画确认接单」这条清单是扫目录算出来的，要证明它真的会数到新文件）
CREATIONS = [
    (
        "其它页面（通用的 ui/common）也冒出一颗「确认接单」（清单自己算 → 必须点名它）",
        COMMON_DIR / "_LeakAckButton.kt",
        _LEAK,
        "只有两处",
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
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出。
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

    # —— 单列一条：把「那一句调用」**搬到卡片最上面**（位置真的错了） ——
    # 为什么不放进 MUTATIONS：要先删掉原处、再在 Column 开头插一句，是两步而不是一次替换。
    # 编译照样过，只有「恰好一处 + 排在动作行之后」那条判据能抓到它。
    card_src, card_crlf = read_src(CARD)
    label = "把 bottomAction() 整句**搬到卡片最上面**（真的只剩一处调用，位置错了）"
    i_body = card_src.find("        Column(Modifier.padding(16.dp)) {\n")
    if card_src.count(_CALL_BLOCK) != 1 or i_body < 0:
        print(f"  [SKIP] {label} —— 锚点对不上（block×{card_src.count(_CALL_BLOCK)} / Column@{i_body}）")
        bad += 1
    else:
        at = i_body + len("        Column(Modifier.padding(16.dp)) {\n")
        mutated = card_src.replace(_CALL_BLOCK, "                extra()\n            }\n", 1)
        mutated = mutated[:at] + "            bottomAction()\n" + mutated[at:]
        write_src(CARD, mutated, card_crlf)
        try:
            hit, detail = verdict(_CALL_EXPECT)
        finally:
            restore_src(CARD, card_src, card_crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    # —— 单列一条：把三个状态**整段挪到 `init { }` 之后** ——
    # 为什么不放进 MUTATIONS：那一段里夹着两段 KDoc，写死会与源码脱钩（实测 count == 0 → SKIP），
    # 所以这里从源码现取那一段。编译照样过，要去打开这一页才崩（属性初始化按书写顺序执行）。
    vm_src, vm_crlf = read_src(VM)
    m = _STATES_RE.search(vm_src)
    label = "三个状态整段挪到 `init { }` **之后**（编译照样过，打开这一页才崩）"
    if m is None:
        print(f"  [SKIP] {label} —— 在源码里没找到那一段（判据与源码脱钩了）")
        bad += 1
    else:
        chunk, i_init = m.group(0), vm_src.find("\n    init {")
        mutated = vm_src.replace(chunk, "\n", 1).replace("\n    init {", "\n    init {" + chunk, 1)
        write_src(VM, mutated, vm_crlf)
        try:
            hit, detail = verdict(_MOVE_EXPECT)
        finally:
            restore_src(VM, vm_src, vm_crlf)
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
