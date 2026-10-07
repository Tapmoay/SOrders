"""反向验证：把 CHG-0074（台账 L-42：上传一张进货单照片 → AI 读出 → 确认卡 → 建采购单）的红线
逐条弄坏，看它们**真的会红**。

为什么这块必须反向验证：这条线的毛病全是「没报错、但也没发生」或者「看着像做了、其实把承诺改小了」——
  · 认图范围放宽（把「只认进货单 / 送货单」偷偷变成「任何写了商品与数量的纸」）：卡片照样出，量级全变；
  · 多行退化成一次一问（行参数改名 items / 卡片不再逐行列）：用户看到一张卡，但少了整张单的信息；
  · 上限自己另立一个数（不用 AiWriteArgs 的那两个）：「一次 30 行 / 单价 100 万」变成两处出处，改一处漏一处；
  · 成本闸漏掉「整条建立在成本上」的动作：关着开关的人照样能从卡片看到进货价（口径 m13365 ③ 明确不破例）；
  · 撤回承诺被改小（拆掉成对恢复 / 撤单卡片泄露金额 / 快照读的键与中文名对不上）：撤回卡会说假话；
  · AI 自己拼那三处钱事实（不调后端那一个入口，自己补一条入库流水）：库存与成本价从此有第二份真相；
  · 覆盖表退回 EXCLUDED（写域没开，用户却以为开了）：这四条正是本条目立项时明文「不做」的那四条；
  · 判据本身失效（路径写错 / 文档里那个 L-42 被删）：清单会永远绿。
所以每一条都要有对应的破坏用例，最后还要确认还原之后红线**逐字节**回到绿。

用法：python _tools/qa/_reverse_verify_ai_purchase_orders.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ai_purchase_orders.py"

AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"

PURCH = AI / "AiWritePurchases.kt"
SVC = AI / "AiWriteService.kt"
DS = AI / "AiWriteDataSource.kt"
RES = AI / "AiResources.kt"
REVERT = AI / "AiRevert.kt"

WRITE_COVERAGE = ROOT / "_tools/ai/_write_coverage.py"
CHG_DOC = ROOT / "docs/changes/CHG-0074.md"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "这一域顺手给货主也开（＝把派单员才有的货款事实递出去）",
        PURCH,
        "    private val ROLES: Set<AiRole> = setOf(AiRole.DISPATCHER)",
        "    private val ROLES: Set<AiRole> = setOf(AiRole.SHIPPER)",
        "这一域只给派单员",
    ),
    (
        "行参数改名 items（＝把多行能力藏起来，退回一次一问）",
        PURCH,
        '                    "rows",\n                    "进货单原文",',
        '                    "items",\n                    "进货单原文",',
        "行参数就叫 rows",
    ),
    (
        "上限自己另立一个数（＝同一个上限两处出处，改一处漏一处）",
        PURCH,
        "    val MAX_PRICE: BigDecimal = AiWriteArgs.MAX_AMOUNT",
        '    val MAX_PRICE: BigDecimal = BigDecimal("999999")',
        "金额与数量的上限只有一处出处",
    ),
    (
        "建单卡片不再承诺那三件事（＝用户不知道点下去会动库存与欠款）",
        PURCH,
        '        details += "———— 保存之后（三件事一起落）————"',
        '        details += "———— 保存之后 ————"',
        "建单卡片写清「保存之后」那一节",
    ),
    (
        "卡片里加 Markdown 粗体（＝纯文本渲染下满屏星号）",
        PURCH,
        '        details += "单据日期：" + docDate',
        '        details += "**单据日期**：" + docDate',
        "卡片文案里没有 Markdown 粗体",
    ),
    (
        "撤单卡片加一行合计（＝成本开关关着的人从卡片上看到钱）",
        PURCH,
        '        details += "撤错了可以让我恢复它（恢复＝按原样再落一遍上面这三件事）"',
        '        details += "撤错了可以让我恢复它（恢复＝按原样再落一遍上面这三件事）"\n'
        '        details += "合计 " + AiWriteArgs.moneyText(current.total) + " 元"',
        "撤单卡片里没有单价与合计",
    ),
    (
        "拿掉「整条建立在成本上」那道闸（＝关着开关也能看到进货价）",
        SVC,
        '        if (action.id in COST_BUILT_ACTIONS && !allowCost()) {\n'
        '            return AiWriteOutcome.Rejected(costGateMessage("进货价"))\n'
        "        }\n",
        "",
        "preview 里真的拦",
    ),
    (
        "改单顺手把行也传上去（＝整份替换语义下，没出现的行全被撤掉）",
        DS,
        "            PurchaseOrderUpdateRequest(supplierId = supplierId, docDate = docDate, remark = remark),",
        "            PurchaseOrderUpdateRequest(supplierId = supplierId, docDate = docDate, remark = remark,"
        " items = emptyList()),",
        "改单只改单头",
    ),
    (
        "建单前后自己补一条入库流水（＝第二份库存真相，AI 直写 inventory_movements）",
        DS,
        "    ): Long = repo.createPurchaseOrder(",
        "    ): Long = repo.createMovement(0L).let { repo.createPurchaseOrder(",
        "AI 不写 inventory_movements",
    ),
    (
        "拆掉成对恢复（＝撤单之后撤回入口找不到它，或恢复成不了对）",
        RES,
        "            paired(\n                AiWrites.PURCHASE_ORDERS_RESTORE,",
        "            updateOnly(\n                AiWrites.PURCHASE_ORDERS_RESTORE,",
        "三个动作：改 / 撤 / 成对恢复",
    ),
    (
        "快照多读一个没有中文名的键（＝撤回卡会露出裸键 total）",
        RES,
        '        readKeys = setOf("supplier_id", "doc_date", "remark"),',
        '        readKeys = setOf("supplier_id", "doc_date", "remark", "total"),',
        "labels 与 readKeys 一一对应",
    ),
    (
        "建单那条理由换成兜底话术（＝用户不知道出路是「撤掉采购单 #N」）",
        REVERT,
        '        "请跟我说一句「撤掉采购单 #N」，我按单号撤给你（撤单本身就是这三件事的反向操作）",',
        '        "可以改或删掉它。",',
        "理由里点名那条唯一的出路",
    ),
    (
        "把 EXCLUDED 加回去（＝写域没开，用户却以为开了）",
        WRITE_COVERAGE,
        '    # 发票台账（FEAT-0014，2026-10-05 本轮不开放 → **CHG-0086 / 台账 L-55，2026-10-08 已开放**）：',
        '    ("POST", "purchase-orders"): ("本轮不开放：占位。"),\n'
        '    # 发票台账（FEAT-0014，2026-10-05 本轮不开放 → **CHG-0086 / 台账 L-55，2026-10-08 已开放**）：',
        "四条写端点都不在 EXCLUDED 里了",
    ),
    (
        "覆盖表理由翻回「仍然不开放」（＝理由与事实各说各话）",
        WRITE_COVERAGE,
        "    # 采购单（FEAT-0013，2026-10-04）：**2026-10-07 CHG-0074（台账 L-42）起已开**。",
        "    # 采购单（FEAT-0013，2026-10-04）：**2026-10-07 CHG-0074（台账 L-42）起仍未开放**。",
        "理由改成了「起已开」的口径",
    ),
    (
        "变更单标题里那个台账条目被删（＝判据自己骗自己）",
        CHG_DOC,
        "三处一起落）（台账 L-42）",
        "三处一起落）",
        "变更单引着台账那一条",
    ),
    (
        "反验脚本的路径被挪走（判据里那条「反向验证脚本在」不能自己骗自己）",
        CHECK,
        'REVERSE = "_tools/qa/_reverse_verify_ai_purchase_orders.py"',
        'REVERSE = "_tools/qa/_reverse_verify_nothing.py"',
        "反向验证脚本在",
    ),
]


def read_src(p: Path):
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
    # 还原当场核对：写回后重新读回来逐字节比，对不上就非零退出。
    # 本句是原则：写了还原不是证明；重新读回来的字节 == 刚写出去的字节 才是。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check():
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str):
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    detail = "实际红 " + str(len(fails)) + " 条"
    if not hit:
        detail += "：" + str([f.strip()[:70] for f in fails[:2]])
    return hit, detail


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print("前提不成立：源码完好时这条红线没过\n" + out[-1200:])
        return 1
    print("前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print("  [SKIP] " + label + " —— 原文出现 " + str(src.count(old)) + " 次，无法唯一替换")
            bad += 1
            continue
        write_src(p=path, text=src.replace(old, new), crlf=crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            restore_src(path, src, crlf)
        tag = "OK" if hit else "MISS"
        print("  [" + tag + "] " + label + " → " + detail)
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print("❌ " + str(bad) + "/" + str(total) + " 条不成立（红线对它们不敏感）")
        return 1
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
