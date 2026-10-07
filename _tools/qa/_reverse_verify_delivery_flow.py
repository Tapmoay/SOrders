"""反向验证：把 CHG-0045 那 62 条判据逐组弄坏，看它们**真的会红**。

顺序那一组按 2026-10-07 台账 L-50 / CHG-0080 的新口径（照片预览 → 拍照 → 高德导航 → 完成按钮 →
送达备注 → 内部备注最后）验证：把预览挪到拍照下面、把备注抄到完成上面、把导航与完成之间那道
16dp 抽掉、把带标题的「送达凭证」白卡抄回来，判据都必须点出来。

为什么这块必须反向验证：司机「拍照送达」这一条几乎全是"没报错但也没发生"的毛病 ——
把入口改回 `onCaptureClick = { vm.showDeliverySheet = true }` 编译通过、点一下也确实能拍照（只是要多点一次）；
把 `photos.isNotEmpty()` 从完成块的门里去掉，界面照样渲染，只是"一张没拍也能点提交"（后端会挡，用户看到的是白跑一趟）；
把内部备注改回 AlertDialog、把 `noteText` 回填成送货备注、再抄一份 `DamageCard` —— 全都不会有任何编译错误。
判据里还有"扫全仓"那几条（任何 .kt 里都不许再有 `fun DeliverySheet(`），清单如果不验证，
就可能因为"目录扫不到"而永远绿。所以每一条都要有对应的破坏用例。

用法：python _tools/qa/_reverse_verify_delivery_flow.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_delivery_flow.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
VM = AND / "ui/order/OrderDetailViewModel.kt"
ORDER_DIR = AND / "ui/order"
API = ROOT / "backend/app/api/v1/orders_delivery.py"
RESPONSE = ROOT / "backend/app/services/order_response.py"

#: (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    # ---- 1. 点一下直接拍照（用户第 ① 条的题眼）----
    (
        "入口改回「先开抽屉再去点相机」（要两步才能拍照）",
        DETAIL,
        "                onCaptureClick = { capture() },\n",
        "                onCaptureClick = { vm.showDeliverySheet = true },\n",
        "入口不再开抽屉",
    ),
    (
        "内部备注弹窗回来（用户第 ⑥ 条：不要弹窗）",
        DETAIL,
        "    preview.Show()\n",
        '    AlertDialog(onDismissRequest = { }, title = { Text("内部备注") }, text = { })\n'
        "    preview.Show()\n",
        "内部备注不再走 AlertDialog",
    ),
    # ---- 2. 照片就长在订单页里 ----
    (
        "缩略图不再可点（拍完看不到大图）",
        DETAIL,
        "                                            .clickable { onCapturedPhotoClick(i) },\n",
        "",
        "点缩略图开大图",
    ),
    (
        "点开只看这一张（丢掉同组翻页，多张照片一次只能看一张）",
        DETAIL,
        "preview.open(vm.capturedPhotos.map { File(it) }, i)",
        "preview.open(listOf(File(vm.capturedPhotos[i])), 0)",
        "传的是整组 + 序号",
    ),
    (
        "拍完那颗按钮还写着「拍照送达」（用户第 ② 条要的「继续拍照」没了）",
        DETAIL,
        'Text(if (photos.isEmpty()) "拍照送达" else "继续拍照（" + photos.size + " 张）")',
        'Text("拍照送达")',
        "继续拍照",
    ),
    (
        "拍糊的那张在页面上删不掉（右上角 ⊗ 没了）",
        DETAIL,
        "                                        onClick = { onRemovePhoto(i) },\n",
        "                                        onClick = { },\n",
        "右上角可以删掉这一张",
    ),
    # ---- 3. 顺序（2026-10-07 台账 L-50 / CHG-0080 定稿）：照片预览 -> 拍照 -> 导航 -> 完成按钮 -> 送达备注 -> 内部备注 ----
    (
        "送达备注那一格被删掉（用户第 ⑤ 条那几块少一块）",
        DETAIL,
        "                    OutlinedTextField(\n"
        "                        value = remark,\n"
        "                        onValueChange = onRemarkChange,\n"
        '                        label = { Text("送达备注（可选）") },\n'
        "                        minLines = 2,\n"
        "                        modifier = Modifier.fillMaxWidth(),\n"
        "                    )\n",
        "",
        "六处锚点都在页面上",
    ),
    (
        "「内部备注」那张卡被抄到送达备注上面（L-49 说它是这一页最底的一块）",
        DETAIL,
        "                    OutlinedTextField(\n"
        "                        value = remark,\n",
        '                    SectionTitle(Icons.Default.Notes, Color(0xFF1E6FFF), "内部备注")\n'
        "                    OutlinedTextField(\n"
        "                        value = remark,\n",
        "内部备注在送达备注下面",
    ),
    (
        "「高德导航」那颗按钮被挪到拍照上面（L-49 第①步＝拍照在最上面）",
        DETAIL,
        "                    // 点一下**直接进相机**（L-04 第 ① 条）；拍过之后这颗按钮就是「继续拍照」——\n",
        '                    Text("高德导航")\n'
        "                    // 点一下**直接进相机**（L-04 第 ① 条）；拍过之后这颗按钮就是「继续拍照」——\n",
        "拍照按钮在导航按钮上面",
    ),
    (
        # 2026-10-07（台账 L-50 / CHG-0080）：从前这条注入的是「完成按钮那一块被挪到送达备注上面」——
        # 那是 L-49 的排版（备注在完成上面）才有的破法；L-50 之后完成按钮本来就在备注上面，这条注入成了
        # 空转（实测 0 条红）。改成钉 L-50 真正的位置关系：完成按钮必须在**导航下面**。
        "完成按钮被挪到高德导航上面（L-50：完成按钮在导航下面、他画的圈）",
        DETAIL,
        "                        Button(\n"
        "                            onClick = onNavigate,\n",
        '                        Text("提交送达（" + photos.size + " 张照片）")\n'
        "                        Button(\n"
        "                            onClick = onNavigate,\n",
        "完成按钮在导航下面",
    ),
    (
        # 2026-10-06（台账 L-15）：从前这条注入的是"把内部备注挪到凭证上面"，它的 old 锚
        # 里带着 `!order.freightVisible`（那半句已经撤了）。改成钉新意图：免拍照那一支不许长回来。
        "挂车直结那一支又长回来了（挂车又能不拍照直接完成）",
        DETAIL,
        "                if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {\n"
        "                    // ⛔ 照片在这里读**实时值**（不是外层传进来的列表快照）：这一块是 item 闭包画的，\n",
        "                if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {\n"
        "                    if (order.freightVisible) {\n"
        "                        Button(onClick = { onDirectCompleteClick(null) },\n"
        "                            modifier = Modifier.fillMaxWidth().height(56.dp)) {\n"
        '                            Text("完成订单", style = MaterialTheme.typography.titleSmall)\n'
        "                        }\n"
        "                    }\n"
        "                    // ⛔ 照片在这里读**实时值**（不是外层传进来的列表快照）：这一块是 item 闭包画的，\n",
        "freightVisible 分支",
    ),
    (
        # 2026-10-07（台账 L-49 / CHG-0079）：从前这条注入的是「闸门加回 !order.freightVisible」——
        # 那道 **DSL 级**闸门已经被真机取证推翻了（它后面的 item 没照片时压根不注册）。改成钉新形状：
        # 完成块必须留在 item 内部、且由 `photos.isNotEmpty()` 把门（不能换成别的条件）。
        "完成块外面那道门被换掉（挂车又能不拍照直接完成）",
        DETAIL,
        "                        if (photos.isNotEmpty()) {\n"
        "                            Spacer(Modifier.height(16.dp))\n",
        "                        if (!order.freightVisible) {\n"
        "                            Spacer(Modifier.height(16.dp))\n",
        "完成块的闸门在 item 内部",
    ),
    (
        "完成块的门整个没了（一张没拍也能点提交）",
        DETAIL,
        "                        if (photos.isNotEmpty()) {\n"
        "                            Spacer(Modifier.height(16.dp))\n",
        "                        if (true) {\n"
        "                            Spacer(Modifier.height(16.dp))\n",
        "完成块的闸门在 item 内部",
    ),
    (
        "照片退回列表快照（外层传 photos = vm.capturedPhotos，item 只认旧值）",
        DETAIL,
        "            photosOf = { vm.capturedPhotos },\n",
        "            photos = vm.capturedPhotos,\n",
        "调用处传的也是取值函数",
    ),
    (
        "item 不再读实时值（改回吃外层捕获的那份）",
        DETAIL,
        "                    val photos = photosOf()\n",
        "                    val photos = emptyList<String>()\n",
        "司机动作块那一处 item 读了实时值",
    ),
    (
        "「送达备注」那一格被抄到完成按钮上面（两块备注必须都沉在最底）",
        DETAIL,
        "                    val photos = photosOf()\n",
        "                    val photos = photosOf()\n"
        '                    Text("送达备注（可选）")\n',
        "送达备注在完成按钮下面",
    ),
    (
        "导航与完成按钮之间那道 16dp 被抽掉（两颗按钮又贴在一起，容易误触）",
        DETAIL,
        "                            Spacer(Modifier.height(16.dp))\n",
        "                            Spacer(Modifier.height(0.dp))\n",
        "完成按钮跟导航之间隔着 16dp",
    ),
    (
        "带标题的「送达凭证」白卡又长回来（L-50 说的是不要标题、不要白卡）",
        DETAIL,
        "                        if (photos.isNotEmpty()) {\n"
        "                            Hint(\n",
        "                        SectionTitle(Icons.Default.PhotoCamera, Color(ProductPurple), "
        '"送达照片（已拍 " + photos.size + " 张）")\n'
        "                        if (photos.isNotEmpty()) {\n"
        "                            Hint(\n",
        "「送达凭证」白卡不许长回来",
    ),
    (
        "照片预览被挪到拍照按钮下面（跟导航挤成一堆）",
        DETAIL,
        "                        if (photos.isNotEmpty()) {\n"
        "                            Hint(\n",
        '                        Text(if (photos.isEmpty()) "拍照送达" else "继续拍照（" + photos.size + " 张）")\n'
        "                        if (photos.isNotEmpty()) {\n"
        "                            Hint(\n",
        "照片预览在拍照按钮上面",
    ),
    # ---- 4. 完成入口：至少一张照片 ----
    (
        "把 VM 里那道「空照片不许提交」的第二道门删掉",
        VM,
        "        if (capturedPhotos.isEmpty()) {\n"
        '            error = "请至少拍摄一张送达照片"\n'
        "            return\n"
        "        }\n",
        "",
        "第二道门还在",
    ),
    # ---- 5. 挂车直结那条路不许被照片门绑住 ----
    (
        "把删掉的「挂车直结」那条管线又接回来（`onDirectCompleteClick` 重新接上）",
        DETAIL,
        "                canFillNav = vm.canFillNavigation(role.key),\n",
        "                onDirectCompleteClick = { p -> vm.completeDirect({ onBack() }, p) },\n"
        "                canFillNav = vm.canFillNavigation(role.key),\n",
        "直结的三颗按钮都不在了",
    ),
    (
        "直结那条路也要求先拍照（用户要的「一步完成」变成两步）",
        VM,
        "    fun completeDirect(onDone: () -> Unit, payment: String? = null) {",
        "    fun completeDirect(onDone: () -> Unit, payment: String? = null) {\n"
        "        if (capturedPhotos.isEmpty()) return",
        "completeDirect（老包",
    ),
    # ---- 6. 内部备注的两道角色门 ----
    (
        "后端对货主不再抹空（货主能看到司机写的内部备注）",
        RESPONSE,
        '            data["internal_notes"] = ""\n',
        "",
        "后端读门",
    ),
    (
        "后端写门放松成「只放司机」（派单员被挡在外面）",
        API,
        "    if role not in (UserRole.DRIVER.value, UserRole.DISPATCHER.value):\n"
        '        raise HTTPException(status_code=403, detail="无权操作")\n',
        "    if role not in (UserRole.DRIVER.value,):\n"
        '        raise HTTPException(status_code=403, detail="无权操作")\n',
        "后端写门②",
    ),
    (
        "写备注不再要求 ORDER_INTERNAL_NOTE 权限",
        API,
        "    current: User = Depends(require_permission(Permission.ORDER_INTERNAL_NOTE)),",
        "    current: User = Depends(get_current_user),",
        "后端写门①",
    ),
    (
        "司机能给别人的单子写备注（「本单司机」那道门没了）",
        API,
        "        if order.driver_id != current.id:",
        "        if order.driver_id != order.driver_id:",
        "后端写门④",
    ),
    # ---- 7. append-only 不许被写成「编辑历史」----
    (
        "登录后就把送货备注抄进内部备注框（旧代码就是这么干的）",
        VM,
        '    var noteText by mutableStateOf("")',
        '    var noteText by mutableStateOf("")\n'
        "\n"
        "    /** 注入：把送货备注抄进内部备注输入框 */\n"
        '    fun prefillNote() { noteText = order?.driverRemark ?: "" }',
        "全仓没有人把 driverRemark 抄进 noteText",
    ),
    (
        "页面不再告诉用户「写进去是追加一条」",
        DETAIL,
        '"只有司机和派单员看得到。写进去是追加一条，已有的那条不会被改动。",',
        '"只有司机和派单员看得到。",',
        "页面文案明说这是「追加一条」",
    ),
    (
        "写完不清空输入框（第二次点「添加备注」会重复写同一条）",
        VM,
        '                noteText = ""\n',
        "",
        "写成功后清空输入框",
    ),
    (
        "输入框标题不再说「再写一条」（看起来像编辑框）",
        DETAIL,
        'label = { Text("再写一条备注（与派单员可见）") },',
        'label = { Text("备注") },',
        "输入框标题明说「再写一条」",
    ),
    # ---- 8. 破损只剩一份 ----
    (
        "页面上再抄一份货物破损卡（抽屉里那份回来了）",
        DETAIL,
        "                    OutlinedTextField(\n"
        "                        value = remark,",
        "                    DamageCard(role, order, false, { }, { }, { }, { })\n"
        "                    OutlinedTextField(\n"
        "                        value = remark,",
        "DamageCard 的调用点只有 1 处",
    ),
    # ---- 9. L-03 的收口不许被推翻 ----
    (
        "把页面末尾那个预览弹层删掉（照片点了没反应）",
        DETAIL,
        "    preview.Show()\n",
        "",
        "预览弹层仍只画一次",
    ),
]

#: 需要**新建文件**的注入（"任何 .kt 里都不许再有 DeliverySheet"是扫全仓算出来的，得证明它真的会数到新文件）
CREATIONS = [
    (
        "又在订单侧抄了一个拍照送达抽屉（扫全仓的那条判据必须点名它）",
        ORDER_DIR / "_LeakDeliverySheet.kt",
        "package com.tapmoay.sorders.ui.order\n\n"
        "@Composable\n"
        "private fun DeliverySheet(onDismiss: () -> Unit) {\n"
        "    onDismiss()\n"
        "}\n",
        "没有任何 DeliverySheet 定义",
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
