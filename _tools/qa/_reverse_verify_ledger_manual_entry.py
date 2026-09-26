"""反向验证：把「账本记一笔账」那条红线的判据逐条弄坏，看它**真的会红**。

为什么这块要反向验证：这一整块改的是**输入口径**，坏掉的方式全都"不报错、不崩"：
商品名又能手打、提交时不带 product_id、选品页退回多选、单价改不了（或被换货主时拽走）、
未注册那条路被删掉、名册搜索退回本地过滤（找不到第 501 个人）、客户端自己乘 total、
从记账页回来不重取（用户以为没存上 → 再记一遍）。这些只有机器判据能拦住，
而"判据本身是不是在检查"只能靠注入法证明。

用法：python _tools/qa/_reverse_verify_ledger_manual_entry.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ledger_manual_entry.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
CREATE = AND / "ui/dispatcher/LedgerCreateScreen.kt"
SCREEN = AND / "ui/dispatcher/DispatcherLedgerScreen.kt"
VM = AND / "ui/dispatcher/DispatcherLedgerViewModel.kt"
PICKER = AND / "ui/common/ProductPicker.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "商品名又能手打了（三个名字在库里就是三件货）",
        CREATE,
        "            // ---- 日期 / 备注 ----",
        "            SoTextField(vm.productName, { vm.productName = it }, placeholder = \"商品名称\")\n"
        "            // ---- 日期 / 备注 ----",
        "页面里**没有**写商品名的输入框",
    ),
    (
        "提交时不带 product_id（账本行与商品库脱钩）",
        CREATE,
        "                        productId = productId,\n",
        "",
        "提交体带上 product_id",
    ),
    (
        "选品页退回多选（一笔账只记一件，挑两件看不出来）",
        CREATE,
        "            single = true,",
        "            single = false,",
        "选品页是**单选**",
    ),
    (
        "单价不可改（用户要的「预售价可以单独调整」没了）",
        CREATE,
        "                        onValueChange = { vm.price = InputRules.priceInput(it) },",
        "                        onValueChange = { },",
        "价框可编辑",
    ),
    (
        "换货主把用户手改的价拽走（等于悄悄改了他报的价）",
        CREATE,
        "        if (autoPrice != null && price != autoPrice) return\n",
        "",
        "用户改过的价**不被拽走**",
    ),
    (
        "未注册那条路被删（没建过档的客户记不了账）",
        CREATE,
        "                        tempShipperName = if (shipperId == null) name else null,",
        "                        tempShipperName = name,",
        "两个字段**互斥**",
    ),
    (
        "填了名字不清注册账号（两个都传 → 后端 400）",
        CREATE,
        "        if (name.isNotBlank()) {\n            shipperId = null\n",
        "        if (name.isNotBlank()) {\n",
        "填了名字就清掉注册账号",
    ),
    (
        "名册搜索退回本地过滤（找不到第 501 个货主 → 同一个人两本账）",
        CREATE,
        '                shipperHits = container.repo.usersPage(role = "shipper", q = kw).rows',
        "                shipperHits = shippers.filter { it.fullName.contains(kw) }",
        "名册搜索走**服务端**",
    ),
    (
        "搜索失败退回空列表（等于对用户说「没有这个人」）",
        CREATE,
        '                error = "搜索失败：" + toApiException(e).message\n                shipperHits = null',
        "                shipperHits = emptyList()",
        "搜索失败**不许**退回空列表",
    ),
    (
        "名册截断位被丢掉（没看到就说「这个账号不存在」）",
        CREATE,
        "                rosterTruncated = page.meta.hasMore",
        "                rosterTruncated = false",
        "名册被截断要说出来",
    ),
    (
        "客户端自己乘 total 传上去（Double 尾数进库）",
        CREATE,
        "                        total = null,",
        "                        total = (q * p).toString(),",
        "提交**不传 total**",
    ),
    (
        "自动带入的价没过 trimMoneyZeros（编辑框里显示 12.5000）",
        CREATE,
        "        price = trimMoneyZeros(line.price)",
        "        price = line.price",
        "挑到商品就把价带进输入框",
    ),
    (
        "换成未注册的名字后不重算价（停在上一家的专属价上 = 报错价）",
        CREATE,
        "            priceRules = emptyMap()\n            priceRulesShipper = null\n            repriceIfAuto()\n        }\n    }\n\n    fun clearShipper() {",
        "        }\n    }\n\n    fun clearShipper() {",
        "换成**未注册的名字**也要重算",
    ),
    (
        "专属价优先被拆掉（批发商按默认价记账 = 报错价）",
        CREATE,
        "        return priceRules[p.id]?.specialUnitPrice ?: p.defaultUnitPrice",
        "        return p.defaultUnitPrice",
        "专属价优先、默认售价兜底",
    ),
    (
        "从记账页回来不重取（刚记的那笔看不见 → 用户再记一遍）",
        SCREEN,
        "    LaunchedEffect(Unit) { vm.onEnter() }\n",
        "",
        "账本页回来时重取一次",
    ),
    (
        "记账弹窗又长回账本页（同一件事两份）",
        SCREEN,
        "    val drawer = rememberDrawerState(DrawerValue.Closed)",
        "    val leakCreate = vm.showCreate\n    val drawer = rememberDrawerState(DrawerValue.Closed)",
        "账本页**不再**内嵌记账弹窗",
    ),
    (
        "VM 里又长回第二份 openCreate()",
        VM,
        "    fun confirmDelete() {",
        "    fun openCreate() {}\n\n    fun confirmDelete() {",
        "VM 里**不再**有第二份 create()/openCreate()",
    ),
    (
        "单选模式下再挑一件变成累加（挑了两件、账上只记一件）",
        PICKER,
        "                if (single) picked.clear()\n",
        "",
        "单选模式下再挑一件是**换掉**",
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
    # 还原**当场核对**（R3-07b）：写回后**重新读回来逐字节比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是（L2 要的就是这一句）。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这一节红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            code, out = run_check()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            hit = code != 0 and any(expect in ln for ln in fails)
            detail = f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")
        finally:
            restore_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
