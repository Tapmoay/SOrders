"""反向验证：把「司机电话只有派单员与批发商能拨」那条红线逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这条规则坏掉的方式**全部不报错、不崩**——
放开角色门只是普通货主那边多一颗按钮；把判据就地抄一遍只是"以后改一处漏一处"；
改成 `ACTION_CALL` 只是"点一下就直接拨出去"（而且要权限，没申请时是**点一下什么都不发生**）；
去掉可拨性判断只是某张老单上多一颗**拨不出去的**按钮；后端把软删后缀原样下发更是连界面都不变
（`13800001234_del160` 读起来只像"号码存脏了"）。用户是按着那颗按钮打电话的人，这些都得由机器守着。

用法：python _tools/qa/_reverse_verify_order_driver_call.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_order_driver_call.py"

DETAIL = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"
DETAIL_VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailViewModel.kt"
DRIVER_CALL = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/DriverCall.kt"
GATE_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/common/DriverCallTest.kt"
ORDER_RESPONSE = ROOT / "backend/app/services/order_response.py"
BACKEND_TEST = ROOT / "backend/tests/test_order_driver_phone.py"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

#: 调用点那一段里被注入的那一行（多处注入共用，改它一处即可）
GATE = "onDial = if (canDialDriver(role, memberShipper) && dialable) {"

#: 把「我是不是批发商」喂给 `DetailBody` 的那一行
MEMBER_WIRE = "memberShipper = vm.isMemberShipper,"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "把「谁能拨」那道门整个放开（普通货主/司机也多一颗拨号按钮 —— 用户明说过"
        "「只有这两个人，司机是没有这个的」）",
        DETAIL,
        GATE,
        "onDial = if (dialable) {",
        "拨号按钮走的是共用判据",
    ),
    (
        "忘了把「我是不是批发商」接进判据（批发商白名单形同不存在）",
        DETAIL,
        GATE,
        "onDial = if (canDialDriver(role, false) && dialable) {",
        "拨号按钮走的是共用判据",
    ),
    (
        "忘了把「我是不是批发商」传下去（`DetailBody` 里恒为 false，批发商那颗按钮永远不出现）",
        DETAIL,
        MEMBER_WIRE,
        "memberShipper = false,",
        "传进 `DetailBody`",
    ),
    (
        "在页面里**就地再写一遍**角色判断（不调 `canDialDriver`：以后改口径只改一处、另一处照旧）",
        DETAIL,
        GATE,
        "onDial = if (role == Role.DISPATCHER && dialable) {",
        "没有**就地写的角色判断",
    ),
    (
        "去掉可拨性判断（老单上多一颗拨不出去的按钮，用户以为 App 坏了）",
        DETAIL,
        GATE,
        "onDial = if (canDialDriver(role, vm.isMemberShipper)) {",
        "能拨的形状就不给按钮",
    ),
    (
        "别处又冒出一份判据实现（两份判据必然分叉）",
        DETAIL,
        "import com.tapmoay.sorders.ui.common.*\n",
        "import com.tapmoay.sorders.ui.common.*\n\n"
        "private fun canDialDriver(role: Role) = role == Role.DISPATCHER\n",
        "只有一处定义",
    ),
    (
        "判据本体放宽成「所有货主」（批发商那一档被淹掉，普通货主也拿到动作）",
        DRIVER_CALL,
        "role == Role.SHIPPER && memberShipper",
        "role == Role.SHIPPER",
        "批发商放行",
    ),
    (
        "判据本体把司机也算进去（他多一颗「打给自己」的按钮）",
        DRIVER_CALL,
        "role == Role.DISPATCHER || (role == Role.SHIPPER && memberShipper)",
        "role == Role.DISPATCHER || role == Role.DRIVER || (role == Role.SHIPPER && memberShipper)",
        "司机不在",
    ),
    (
        "单测被改宽（普通货主那一条断言翻成 true —— 判据被放宽就没人拦了）",
        GATE_TEST,
        "assertFalse(canDialDriver(Role.SHIPPER, memberShipper = false))",
        "assertTrue(canDialDriver(Role.SHIPPER, memberShipper = false))",
        "单测盯着「普通货主不给」",
    ),
    (
        "`is_member` 取不到时默认**给**（一次 `/users/me` 抖动，普通货主就拿到按钮）",
        DETAIL_VM,
        "runCatching { container.repo.me().isMember }.getOrDefault(false)",
        "runCatching { container.repo.me().isMember }.getOrDefault(true)",
        "取不到时默认",
    ),
    (
        "客户端自己写一份电话校验（与 core/InputRules.kt 分叉）",
        DETAIL,
        "InputRules.phoneError(driverPhone) == null",
        'driverPhone.matches(Regex("^1\\\\d{10}$"))',
        "不自己写一份电话规则",
    ),
    (
        "改用 ACTION_CALL（要 CALL_PHONE 权限；有权限就一碰就拨出去）",
        DETAIL,
        "android.content.Intent.ACTION_DIAL,\n"
        '                                        android.net.Uri.parse("tel:" + driverPhone),',
        "android.content.Intent.ACTION_CALL,\n"
        '                                        android.net.Uri.parse("tel:" + driverPhone),',
        "ACTION_CALL",
    ),
    (
        "整颗拨号按钮不画了（「简化」掉用户点名的功能，而这一页看起来完全正常）",
        DETAIL,
        "        if (onDial != null) {",
        "        if (false) {",
        "整颗按钮不画",
    ),
    (
        "把按钮包进它自己的 Row（按钮另起一行 → 卡片白白高一行）",
        DETAIL,
        "        if (onDial != null) {",
        "        if (onDial != null) {\n            Row {",
        "同排",
    ),
    (
        "信息不再吃剩余宽度（不给 weight，右边的按钮会把名字挤瘪）",
        DETAIL,
        '        Column(Modifier.weight(1f)) {\n            Text(\n                "司机 " + name,',
        '        Column {\n            Text(\n                "司机 " + name,',
        "信息吃剩余宽度",
    ),
    (
        "把 `DriverRow` 的调用整行去掉（组件还在，但这一页再也不画它）",
        DETAIL,
        "                    DriverRow(\n                        name = order.driverName.orEmpty(),",
        "                    OtherRow(\n                        name = order.driverName.orEmpty(),",
        "有定义有调用",
    ),
    (
        "顺手把整行藏给非派单端（用户只说了**按钮**给谁；司机是谁这一行三个角色都看）",
        DETAIL,
        "                if (!order.driverName.isNullOrBlank()) {\n                    val driverPhone",
        "                if (role == Role.DISPATCHER && !order.driverName.isNullOrBlank()) {\n"
        "                    val driverPhone",
        "三个角色都画这一行",
    ),
    (
        "后端把库里的原样值直接下发（软删后缀 `_del160` 落在拨号按钮底下）",
        ORDER_RESPONSE,
        'data["driver_phone"] = dialable_phone(du)',
        'data["driver_phone"] = du.phone',
        "原样值直接下发",
    ),
    (
        "后端用例被改成空跑（`is not None` 等于什么都没验）",
        BACKEND_TEST,
        'assert after["driver_phone"] == "13900009999", f"软删后缀没去干净：{after[\'driver_phone\']!r}"',
        'assert after["driver_phone"] is not None, "随便什么值都行"',
        "用例真的在验",
    ),
    (
        "设计规范里删掉指路（规矩还在，但没人找得到判据脚本）",
        DESIGN,
        "`_tools/qa/_check_order_driver_call.py`（含反向验证；后端那一半在",
        "判据脚本（名字待补；后端那一半在",
        "指路到本判据",
    ),
    (
        "设计规范里把放宽的边界抹掉（「只有这两个人」变成一句含糊的「其他角色」）",
        DESIGN,
        "⛔ **普通货主与司机不给按钮**",
        "⛔ **其他角色不给按钮**",
        "普通货主与司机不给",
    ),
    (
        "定位表「订单详情页」那一行不再指路判据（改了核心文件却不更新地图）",
        LOCATOR,
        "判据 `_tools/qa/_check_order_driver_call.py` |",
        "判据（脚本名待补） |",
        "定位表的「订单详情页」那一行",
    ),
    (
        "定位表那行退回旧口径「只有派单端能拨」（下一轮以为批发商不该有）",
        LOCATOR,
        "**司机那一行：只有派单员与批发商能拨**",
        "**司机那一行：只有派单端能拨**",
        "只有派单员与批发商能拨",
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
