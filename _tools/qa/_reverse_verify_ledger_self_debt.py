"""BUG-0016 的反向验证：往源码里注入坏改动，判据 _check_ledger_self_debt.py 必须变红。

「写了还原」不是证明：restore_src 写回后会重新读一遍**逐字节**比对（比的是注入前的快照），
不一致就 SystemExit(2) —— 注入把源码树弄脏比判据假绿还糟。

每条坏改动都对应红线里的一句话（第 5 列是那条判据的标签关键词）：
  ① 电话那一半丢了   ② 名字那一半丢了   ③ 空串也算命中   ④ 身份 null 也报
  ⑤ 左栏不标了       ⑥ 卡片不标了       ⑦ 卡片红条退化成普通底色
  ⑧ 名字不再取 fullName（后端兜底写的就是它）   ⑨ 入口恒 false（红条永远不出现）
  ⑩ 取不到也写个空串   ⑪⑫ 设计规范 / 定位表的指路被删   ⑬ 单测里 null 不报那条被删
  ⑭ 卡片文案不再说破   ⑮ 左栏红字不是红字
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

QA = Path(__file__).resolve().parent
CHECK = QA / "_check_ledger_self_debt.py"

ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
GROUPING = ANDROID / "ui/shipper/ShipperLedgerGrouping.kt"
VM = ANDROID / "ui/shipper/ShipperLedgerViewModel.kt"
SCREEN = ANDROID / "ui/shipper/ShipperLedgerScreen.kt"
TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/shipper/ShipperLedgerGroupingTest.kt"
DESIGN = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

MUTATIONS: list[tuple[str, Path, str, str, str]] = [
    (
        "① 判定只看名字（电话那一半丢了）",
        GROUPING,
        "if (p.isNotEmpty() && mp.isNotEmpty() && p == mp) return true",
        "// （电话那一半被删了）",
        "电话那一半：两边都非空且相同才命中",
    ),
    (
        "② 判定只看电话（名字那一半丢了）",
        GROUPING,
        "return n.isNotEmpty() && mn.isNotEmpty() && n == mn",
        "return false",
        "名字那一半：两边都非空且相同才命中",
    ),
    (
        "③ 空串也算命中（「未指定货主」那档会混进来）",
        GROUPING,
        "if (p.isNotEmpty() && mp.isNotEmpty() && p == mp) return true",
        "if (p == mp) return true",
        "没有把空串当命中",
    ),
    (
        "④ 身份没拿到也报（冤枉别人）",
        GROUPING,
        "val mn = meName?.trim().orEmpty()",
        "val mn = meName!!.trim()",
        "没有 !! 硬解空",
    ),
    (
        "⑤ 左栏名册不再标这一档",
        SCREEN,
        'warn = if (vm.isSelfDebt(c)) "就是你自己 · 请先改收货人" else null,',
        "warn = null,",
        "左栏那一行把判定接上了",
    ),
    (
        "⑥ 卡片上那块红条不画了",
        SCREEN,
        "if (vm.isSelfDebt(g)) {",
        "if (false) {",
        "卡片那处也接上了同一个判定",
    ),
    (
        "⑦ 卡片红条退化成普通底色（红条变装饰）",
        SCREEN,
        "            Surface(\n                color = MaterialTheme.colorScheme.errorContainer,\n                shape = MaterialTheme.shapes.small,\n            ) {",
        "            Surface(\n                color = MaterialTheme.colorScheme.surfaceVariant,\n                shape = MaterialTheme.shapes.small,\n            ) {",
        "卡片用 errorContainer 底",
    ),
    (
        "⑧ 名字不再取 fullName（后端兜底写的正是它）",
        VM,
        "meName = me.fullName",
        "meName = null",
        "名字用 fullName",
    ),
    (
        "⑨ 界面入口恒 false（判据还在，红条永远不出现）",
        VM,
        "fun isSelfDebt(g: LedgerCustomer): Boolean = isSelfDebtCustomer(g.name, g.phone, meName, mePhone)",
        "fun isSelfDebt(g: LedgerCustomer): Boolean = false",
        "界面用的入口",
    ),
    (
        "⑩ 取不到账号资料也写个空串（盖掉 null 这条退路）",
        VM,
        "                mePhone = me.phone\n            } catch (_: Exception) {",
        '                mePhone = me.phone\n            } catch (_: Exception) {\n                meName = ""',
        "取失败时不写 meName",
    ),
    (
        "⑪ 设计规范那条指路被删",
        DESIGN,
        "_check_ledger_self_debt.py",
        "_check_ledger_self_debt_DELETED.py",
        "设计规范写了这条规矩并点名判据",
    ),
    (
        "⑫ 代码定位表那条指路被删",
        LOCATOR,
        "_check_ledger_self_debt.py",
        "_check_ledger_self_debt_DELETED.py",
        "代码定位表点名了判据",
    ),
    (
        "⑬ 单测里「身份没拿到不报」那条被删",
        TEST,
        'assertTrue(!isSelfDebtCustomer("Shipper", "13800000002", null, null))',
        "// （那条断言被删了）",
        "身份没拿到（null）不报",
    ),
    (
        "⑭ 卡片文案不再说破（只剩一个不明所以的色块）",
        SCREEN,
        "异常订单：这一档的客户就是你自己",
        "提示",
        "卡片上写着「异常订单」",
    ),
    (
        "⑮ 左栏那行不是红字（与副标题同色）",
        SCREEN,
        "                    style = MaterialTheme.typography.labelSmall,\n                    color = MaterialTheme.colorScheme.error,",
        "                    style = MaterialTheme.typography.labelSmall,\n                    color = MaterialTheme.colorScheme.onSurfaceVariant,",
        "红字用 error 色",
    ),
]


def read_src(p: Path) -> tuple[str, bytes]:
    raw = p.read_bytes()
    return raw.decode("utf-8").replace("\r\n", "\n"), raw


def write_src(p: Path, text: str, crlf: bool) -> None:
    p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def restore_src(p: Path, text: str, crlf: bool, raw: bytes) -> None:
    write_src(p, text, crlf)
    if p.read_bytes() != raw:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def failed_labels(out: str) -> list[str]:
    return [ln.strip() for ln in out.splitlines() if ln.strip().startswith("·")]


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：判据本来是红的 —— 先把它修绿再跑反向验证。")
        print(out.strip()[-2000:])
        return 1

    snapshots: dict[Path, tuple[str, bytes]] = {}
    bad = 0
    for label, path, old, new, expect in MUTATIONS:
        if path not in snapshots:
            snapshots[path] = read_src(path)
        text, raw = snapshots[path]
        n = text.count(old)
        if n != 1:
            print(f"[SKIP] {label}｜原文在 {path.name} 里出现 {n} 次（要求恰好 1 次）—— 注入没生效，这条不算数")
            bad += 1
            continue
        crlf = b"\r\n" in raw
        write_src(path, text.replace(old, new), crlf)
        try:
            mcode, mout = run_check()
        finally:
            restore_src(path, text, crlf, raw)
        labels = failed_labels(mout)
        if mcode != 0 and any(expect in ln for ln in labels):
            print(f"[OK] {label} ⇒ 判据变红，点名「{expect}」")
        else:
            bad += 1
            if mcode == 0:
                print(f"[BAD] {label} ⇒ 判据仍然全绿 —— 这条红线对它完全是瞎的")
            else:
                print(f"[BAD] {label} ⇒ 红了，但不是这一条（expect={expect}）")
                print("      实际失败行：" + " / ".join(labels)[:600])

    code, out = run_check()
    if code != 0:
        print("❌ 全部还原之后判据反而是红的 —— 还原没干净，先查源码树。")
        print(out.strip()[-2000:])
        return 2
    if bad:
        print(f"❌ 反向验证 {len(MUTATIONS) - bad}/{len(MUTATIONS)} 条成立（红线对剩下的不敏感，或注入没生效）")
        return 1
    print(f"✅ 反向验证 {len(MUTATIONS)}/{len(MUTATIONS)}：每条坏改动都让判据变红，且红的正是对应那一条。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
