"""反向验证：把「核销那一族弹窗是卡片式（白底 ＋ 弹层圆角）」这条判据逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这一刀坏掉的方式**全部不报错** ——
- 零件的三行样式被抽掉一行（`containerColor` / `tonalElevation` / `shape`），
  编译通过、界面照常，只是核销弹窗又回到那层灰蓝（用户说的「太丑了」）；
- 5 处调用点**只改一半**（两个角色两个入口，很容易漏掉派单员那一族），同样没有任何报错；
- 最像「正经改法」的是方案 C：直接去改主题 token `SurfaceContainerHigh` —— 编译通过、
  所有核销弹窗一起变白，**顺手改掉了另外 6 处消费者**（AI 聊天 4 ＋ 富文本引用块 1 ＋ 消息未读底色 1）；
- 还有一种是**回潮**：台账 L-20 / CHG-0064 把全库收敛之后，某一处又自己画一层底
  （OrderDetailScreen 那个「打电话确认」冒出一处裸 `AlertDialog(`）—— 那时候全库只该剩
  `CardAlertDialog` 定义体内那一处。
所以下面每一条都对应 `_check_ledger_dialog_style.py` 里的一条判据，注入后必须出现**指定那句红**。

用法：python _tools/qa/_reverse_verify_ledger_dialog_style.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ledger_dialog_style.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
COMP = AND / "ui/common/Components.kt"
SHIPPER = AND / "ui/shipper/ShipperLedgerScreen.kt"
DISPATCHER = AND / "ui/dispatcher/LedgerPersonScreen.kt"
COLOR = AND / "ui/theme/Color.kt"
THEME = AND / "ui/theme/Theme.kt"
AI_CHAT = AND / "ui/ai/AiChatScreen.kt"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "零件的白底被抽回灰蓝（这一刀等于白改）",
        COMP,
        "        containerColor = MaterialTheme.colorScheme.surface,\n",
        "        containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,\n",
        "白底",
    ),
    (
        "零件把 M3 那 6dp 抬升加回来（白底上又刷一层主色薄雾，看着还是灰蓝）",
        COMP,
        "        containerColor = MaterialTheme.colorScheme.surface,\n        tonalElevation = 0.dp,\n",
        "        containerColor = MaterialTheme.colorScheme.surface,\n        tonalElevation = 6.dp,\n",
        "tonalElevation",
    ),
    (
        "零件的圆角退回卡片圆角（弹层那档被改掉）",
        COMP,
        "        shape = MaterialTheme.shapes.extraLarge,\n        containerColor = MaterialTheme.colorScheme.surface,\n",
        "        shape = MaterialTheme.shapes.medium,\n        containerColor = MaterialTheme.colorScheme.surface,\n",
        "弹层圆角",
    ),
    (
        "properties 不再透传（调用点传的 DialogProperties 被吃掉）",
        COMP,
        "        properties = properties,\n",
        "",
        "properties",
    ),
    (
        "签名少一个槽位（icon 被删，调用点就被迫改结构）",
        COMP,
        "    icon: (@Composable () -> Unit)? = null,\n",
        "",
        "签名",
    ),
    (
        "货主「恢复这笔核销」那一处改回裸弹窗（又变回灰蓝）",
        SHIPPER,
        "        CardAlertDialog(\n            onDismissRequest = { vm.cancelRestore() },\n",
        "        AlertDialog(\n            onDismissRequest = { vm.cancelRestore() },\n",
        "3 处核销弹窗全走",
    ),
    (
        "货主「订单核销记录」那一处改回裸弹窗（只改了一半）",
        SHIPPER,
        "    CardAlertDialog(\n        tone = DialogTone.DANGER,\n        onDismissRequest = { vm.closeSettlements() },\n",
        "    AlertDialog(\n        onDismissRequest = { vm.closeSettlements() },\n",
        "代码里再没有裸",
    ),
    (
        "派单员那一族少迁一处（同一个功能、两个角色、两个样式）",
        DISPATCHER,
        "    CardAlertDialog(\n        onDismissRequest = { if (!vm.settleSubmitting) onDismiss() },\n        // 单号另起一行、小一号（走查 P4：标题那 24sp 一行塞不下 20 个字符，会被从数字中间劈开）。\n        title = { DialogTitle(\"核销\", order.orderNo) },\n",
        "    AlertDialog(\n        onDismissRequest = { if (!vm.settleSubmitting) onDismiss() },\n        // 单号另起一行、小一号（走查 P4：标题那 24sp 一行塞不下 20 个字符，会被从数字中间劈开）。\n        title = { DialogTitle(\"核销\", order.orderNo) },\n",
        "2 处核销弹窗全走",
    ),
    (
        "回潮：司机端订单详情又冒出一处裸弹窗（CHG-0064 之后全库只该剩定义自己那一处）",
        DETAIL,
        "                        CardAlertDialog(\n                            onDismissRequest = { confirmCall",
        "                        AlertDialog(\n                            onDismissRequest = { confirmCall",
        "一处不剩",
    ),
    (
        "方案 C 回潮：把主题 token 改成白的（顺手改掉 6 处消费者）",
        COLOR,
        "val SurfaceContainerHigh = Color(0xFFE9E7E3)",
        "val SurfaceContainerHigh = Color(0xFFFFFFFF)",
        "SurfaceContainerHigh 仍是",
    ),
    (
        "方案 C 的另一半：Theme 不再把那个 token 接进 colorScheme",
        THEME,
        "    surfaceContainerHigh = SurfaceContainerHigh,\n",
        "    surfaceContainerHigh = Surface,\n",
        "接到 colorScheme.surfaceContainerHigh",
    ),
    (
        "顺手改了 token 的消费者（AI 聊天那块底被改白）",
        AI_CHAT,
        "val sectionBg = MaterialTheme.colorScheme.surfaceContainerHigh",
        "val sectionBg = MaterialTheme.colorScheme.surface",
        "消费者没被顺手改",
    ),
    (
        "DangerConfirmDialog 被顺手改名（全 App 共用的危险确认，判据钉着它）",
        COMP,
        "fun DangerConfirmDialog(",
        "fun DangerConfirmDialogLegacy(",
        "DangerConfirmDialog 还在",
    ),
    (
        "文档口径被改回去：README 那行不再链到 CHG-0051",
        README,
        "[CHG-0051.md](CHG-0051.md)",
        "[CHG-0051.md](#)",
        "README.md 有 CHG-0051",
    ),
    (
        "AI_WORK_CLAIM 的工作条目被删（后来的人查不到这一刀）",
        CLAIM,
        "会话：**CHG-0051",
        "会话：**CHG-00XX",
        "本事项的条目",
    ),
    (
        "AI_WORK_CLAIM 的交叉点行被改窄（只记了零件，没记三处调用点）",
        CLAIM,
        "`ui/common/Components.kt` ＋ `ui/shipper/ShipperLedgerScreen.kt` ＋ `ui/dispatcher/LedgerPersonScreen.kt`",
        "`ui/common/Components.kt`（只记了零件）",
        "交叉点表记了",
    ),
]

#: 需要**新建文件**的注入（本事项没有"全仓扫描新文件"那类判据，所以这里是空的）。
CREATIONS: list[tuple[str, Path, str, str]] = []


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
