"""反向验证：把「司机「拍照送达」是所有司机一律」这条判据逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这条规矩坏掉的方式**全部不报错** ——
- 把 `if (order.freightVisible)` 那一支加回动作卡，编译通过、界面正常，只是挂车那一档又能在
  不拍照的情况下点一下完成（送达凭证就断了，而账照入、库存照扣）；
- 把服务端那道「空照片列表一律拒」换成「看计费方式」，所有既有用例照样绿（夹具里都带着照片 URL）；
- 最隐蔽的是「顺手多删」：L-15 撤的是**照片豁免**，不是计费方式 —— 把 `has_per_order_pay` /
  `order_mode` 一起删掉，账单与运费提醒会静默失准，而没有任何一条红线是冲着它们去的。
所以下面每一条都对应 `_check_all_drivers_photo.py` 里的一条判据，注入后必须出现**指定那句红**。

用法：python _tools/qa/_reverse_verify_all_drivers_photo.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_all_drivers_photo.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
VM = AND / "ui/order/OrderDetailViewModel.kt"
REPO = AND / "data/repo/AppRepository.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"
FLOW = ROOT / "backend/app/services/order_flow.py"
DELIVERY_API = ROOT / "backend/app/api/v1/orders_delivery.py"
DRIVER_PAY = ROOT / "backend/app/services/driver_pay.py"
BILLS = ROOT / "backend/app/api/v1/driver_bills.py"
MESSAGES = ROOT / "backend/app/services/message_center.py"
DOMAIN_MODEL = ROOT / "docs/DOMAIN_MODEL.md"
MONEY_CHECK = ROOT / "_tools/qa/_check_driver_money.py"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "把「挂车免拍照」那一支加回动作卡（挂车又能不拍照直接完成）",
        DETAIL,
        "                if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {\n"
        "                    // ⛔ 照片在这里读**实时值**（不是外层传进来的列表快照）：这一块是 item 闭包画的，\n",
        "                if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {\n"
        "                    if (order.freightVisible) {\n"
        "                        Button(onClick = { onDirectCompleteClick(null) }) {\n"
        "                            Text(\"完成订单\", style = MaterialTheme.typography.bodyMedium)\n"
        "                        }\n"
        "                    }\n"
        "                    // ⛔ 照片在这里读**实时值**（不是外层传进来的列表快照）：这一块是 item 闭包画的，\n",
        "这条支",
    ),
    (
        "动作卡闸门改成「挂车不画拍照入口」（等于免拍照那一支换个写法回来）",
        DETAIL,
        "                if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {\n"
        "                    // ⛔ 照片在这里读**实时值**",
        "                if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE && !order.freightVisible) {\n"
        "                    // ⛔ 照片在这里读**实时值**",
        "闸门①",
    ),
    (
        "送达凭证块又对挂车整块不画（挂车的单没有凭证这一块）",
        DETAIL,
        "        if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {\n"
        "            item {\n"
        "                // ⛔ 同上：照片在 item 里读实时值 —— 这 item 首帧就注册，照片一到它自己会重跑。\n"
        "                val photos = photosOf()\n"
        "                SectionCard {\n"
        "                    SectionTitle(\n"
        "                        Icons.Default.PhotoCamera,",
        "        if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE && !order.freightVisible) {\n"
        "            item {\n"
        "                // ⛔ 同上：照片在 item 里读实时值 —— 这 item 首帧就注册，照片一到它自己会重跑。\n"
        "                val photos = photosOf()\n"
        "                SectionCard {\n"
        "                    SectionTitle(\n"
        "                        Icons.Default.PhotoCamera,",
        "闸门②",
    ),
    (
        "完成块的闸门又加回计费判据（挂车拍完照反而不给完成）",
        DETAIL,
        "                if (photos.isNotEmpty()) {\n"
        "                    Spacer(Modifier.height(12.dp))\n",
        "                if (!order.freightVisible) {\n"
        "                    Spacer(Modifier.height(12.dp))\n",
        "闸门③",
    ),
    (
        "VM 里那道第二道门拆掉（空照片也往下走，靠服务端兜底）",
        VM,
        "        if (capturedPhotos.isEmpty()) {\n"
        "            error = \"请至少拍摄一张送达照片\"\n"
        "            return\n"
        "        }\n",
        "        if (false) {\n"
        "            error = \"请至少拍摄一张送达照片\"\n"
        "            return\n"
        "        }\n",
        "第二道门",
    ),
    (
        "completeDelivery 改走不带照片的老端点（第二道门被绕过）",
        VM,
        "                order = container.repo.completeWithUpload(\n",
        "                order = container.repo.completeDirect(\n",
        "走的是带照片的上传端点",
    ),
    (
        "VM 的兼容路被删（老版本 APK / 外部调用方那条路没了）",
        VM,
        "    fun completeDirect(onDone: () -> Unit, payment: String? = null) {\n",
        "    fun completeDirectLegacy(onDone: () -> Unit, payment: String? = null) {\n",
        "VM：completeDirect 仍在",
    ),
    (
        "兼容路的语义被偷换（repo.completeDirect 也带上照片）",
        REPO,
        "OrderCompleteBody(emptyList(), remark, payment",
        "OrderCompleteBody(listOf(\"/static/uploads/delivery/x.jpg\"), remark, payment",
        "空照片列表",
    ),
    (
        "freight_visible 出参字段被删（顺手动到「司机端显示运费」那件事）",
        DTOS,
        "    @SerialName(\"freight_visible\") val freightVisible: Boolean = false,\n",
        "",
        "freight_visible 出参",
    ),
    (
        "服务端那道门被拆（空照片列表照样往下走）",
        FLOW,
        "        raise ValueError(\"请至少上传一张送达照片\")\n",
        "        pass  # 老口径：不按单拿钱的单免拍照\n",
        "if not delivery_photo_urls:",
    ),
    (
        "把计费判据接回照片门（工资制 / 挂车又开始免拍照）",
        FLOW,
        "    if not delivery_photo_urls:\n",
        "    if not delivery_photo_urls and not has_per_order_pay(order):\n",
        "不再引用 has_per_order_pay",
    ),
    (
        "L-14 那道凭证形状门删掉（`[\"x\"]` 又算拍照了）",
        FLOW,
        "    bad_photos = [u for u in delivery_photo_urls if not str(u).startswith(\"/static/uploads/delivery/\")]\n",
        "    bad_photos = []\n",
        "凭证形状门还在",
    ),
    (
        "回收站那道门删掉（删过的单又能送达）",
        FLOW,
        "    if order.deleted_at is not None:\n"
        "        raise ValueError(\"这一单已经被删掉了（在回收站里），不能送达。请让派单员确认这一单的归属。\")\n",
        "    if False:\n"
        "        raise ValueError(\"这一单已经被删掉了（在回收站里），不能送达。请让派单员确认这一单的归属。\")\n",
        "软删那条门还在",
    ),
    (
        "老端点被摘掉（老版本 APK 直接 404）",
        DELIVERY_API,
        '@router.post("/{order_id}/complete"',
        '@router.post("/{order_id}/complete-legacy"',
        "老版本 APK 要走它",
    ),
    (
        "计费口径被顺手删掉（模块级 has_per_order_pay 改名 → 账单判据静默失联）",
        DRIVER_PAY,
        "def has_per_order_pay(order) -> bool:",
        "def has_per_order_pay_v2(order) -> bool:",
        "模块级 has_per_order_pay(order) 还在",
    ),
    (
        "order_mode 改名（账单 / 运费提醒的另一个判据静默失联）",
        DRIVER_PAY,
        "def order_mode(order) -> str:",
        "def order_mode_v2(order) -> str:",
        "order_mode(order) 还在",
    ),
    (
        "driver_bills 不再用按单判据（工资制司机的按单账单又长出来）",
        BILLS,
        "    if not has_per_order_pay(o):\n",
        "    if False:\n",
        "driver_bills 仍在用 has_per_order_pay",
    ),
    (
        "message_center 不再用按单判据（运费提醒发错人）",
        MESSAGES,
        "    if not has_per_order_pay(order):\n",
        "    if False:\n",
        "message_center 仍在用 has_per_order_pay",
    ),
    (
        "文档口径改回去（DOMAIN_MODEL 又说挂车按计费规则免照片）",
        DOMAIN_MODEL,
        "司机完成且至少上传一张送达照片（**所有司机一律**；挂车/整车也不再按计费规则免照片 —— 2026-10-06 台账 L-15 收紧）",
        "司机完成（挂车 / 整车按计费规则免照片）",
        "DELIVERED 那格写了",
    ),
    (
        "两条判据之间的交叉引用断了（下一轮没人知道还要跟着改）",
        MONEY_CHECK,
        "_check_all_drivers_photo.py",
        "_check_driver_money.py",
        "指到本判据",
    ),
]

#: 需要**新建文件**的注入（判据 1 是全仓扫 `.kt` 算出来的，得证明它真的会扫到新文件）
CREATIONS = [
    (
        "新建一个还带着免拍照支的页面（全仓扫描必须点名它）",
        AND / "ui/order/_LegacyFreightVisible.kt",
        "package com.tapmoay.sorders.ui.order\n\n"
        "internal fun legacy(p: String) {\n"
        "    if (order.freightVisible) {\n"
        "    }\n"
        "}\n",
        "这条支",
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
