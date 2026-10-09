"""反向验证 BUG-0029（客户收款的撤销 / 恢复）那批修复**真的在检查**。

2026-10-10 测试会话点名（台账 TB-09）：派单员登记一笔客户收款会一次写**四个落点**
（`shipper_receipts` 一行 ＋ 它写下的 `cash_flows`(`RECEIPT_*`) 若干行 ＋ 被翻成 `paid=true` 的订单
＋ 由前两者算出来的 `turnover` 的 collected/arrears 与 `customer-balances`），而撤销入口一个都没有
（`DELETE/PATCH /ledger/receipts/{id}`、`POST /{id}/restore`、`DELETE /cash-flows/{id}` 全部 404）；
系统自己的报错文案还写着「请联系管理员在账上冲正」，而管理员也没有入口。

修法：收款单挂软删两列（＋ 幂等 DDL）、新增撤销/恢复两个端点（**四个落点一起翻、只翻一次**）、
收款记录默认过滤 ＋ 回收站档、两个审计码与中文名、App 收款记录行上的「撤销」/「恢复」。
这份脚本逐条把修复弄坏，证明对应的检查（判据脚本 / 回归用例）会红。

| 注入 | 应该红的检查 |
|---|---|
| 只软删流水、不翻 orders.paid | 判据 / 落点② |
| 只翻 paid、不软删流水 | 判据 / 落点① |
| 撤销改成物理删除收款单 | 判据 / 落点③ ＋ 不物删 |
| 第二次撤销的闸门拆掉 | 判据 / 幂等的唯一依据 |
| 恢复不判「该单又被收过一次」 | 回归用例 / 恢复的四道门 |
| 恢复不把流水放回来 | 判据 / 原样放回 |
| 列表不再默认过滤已撤销的 | 判据 |
| 列表摘掉 include_deleted 档 | 判据 |
| 审计码摘掉一个 | 判据 |
| ReportCenter 的中文名摘掉 | 判据 |
| 模型不再挂 SoftDeleteMixin | 判据 |
| 线上迁移那段 DDL 删掉 | 判据 |
| 界面把「撤销」键摘掉 / 回收站档摘掉 | 判据 |
| Apis.kt 摘掉 restore 端点 | 判据 |
| AI 侧的排期理由删掉（覆盖率门禁） | 判据 |
| AiRevert 把那句假话改回去 | 判据 |
| 回归用例改名 / 变更单少一节 / 登记表去掉「已提交」/ 台账行改名 / 认领簿换号 | 判据 |

⚠️ 快照/还原按**字节**做（仓库里有 CRLF 文件），跑完逐字节核对；
⚠️ 跑的时候会拿一把锁（`_airepo.lock_reverse_verify`），并发的检查会自己停手。

用法：python -X utf8 _tools/finance/_reverse_verify_receipt_undo.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ai"))

from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = HERE / "_check_receipt_undo.py"

LEDGER = "backend/app/api/v1/ledger.py"
MODEL = "backend/app/models/shipper_receipt.py"
ENUMS = "backend/app/models/enums.py"
BOOT = "backend/app/core/schema_bootstrap.py"
APIS = "android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/AccountToolsScreens.kt"
REPORT = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"
REVERT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiRevert.kt"
COVER = "_tools/ai/_write_coverage.py"
KTEST = "backend/tests/test_receipt_undo.py"
DOC = "docs/changes/BUG-0029.md"
REG = "docs/changes/README.md"
LEDGERDOC = "docs/TEST_BUG_LEDGER.md"
CLAIM = "docs/AI_WORK_CLAIM.md"

#: pytest 的 node 相对 backend/ 写（run_test 的 cwd 就是 backend/）。
GATE_CASE = "tests/test_receipt_undo.py::test_restore_refuses_when_the_order_was_collected_again"


def _drop(text: str, needle: str) -> str:
    """把一个字面量整段删掉（锚点不在时原样返回 —— 上层会报「注入没生效」）。"""
    return text.replace(needle, "", 1)


# ① 只软删流水、不翻 paid（四个落点只回滚三个）
M_NO_PAID_FLIP = lambda s: s.replace("            o.paid = False\n", "            o.paid = bool(0)\n", 1)
# ② 只翻 paid、不软删流水（钱还在账上，单却说没收）
M_NO_FLOW_SOFTDEL = lambda s: s.replace("        f.is_deleted = True\n", "        f.is_deleted = False\n", 1)
# ③ 撤销改成物理删除（用户定的规矩是软删）
M_PHYSICAL_DELETE = lambda s: s.replace("    r.is_deleted = True\n", "    db.delete(r)\n", 1)
# ④ 第二次撤销的闸门拆掉（幂等没了：会把数改第二遍）
M_NO_IDEMPOTENT_GATE = lambda s: s.replace("    if r.is_deleted:\n", "    if False:\n", 1)
# ⑤ 恢复不判「该单又被收过一次」（同一笔钱会被算两遍）
M_NO_PAID_GATE = lambda s: s.replace(
    "            if o.paid:\n                raise HTTPException(\n",
    "            if False:\n                raise HTTPException(\n",
    1,
)
# ⑥ 恢复不把流水放回来（撤销掉的钱回不来）
M_NO_FLOW_RESTORE = lambda s: _drop(s, "        f.is_deleted = False\n        f.deleted_at = None\n")
# ⑦ 列表不再默认过滤已撤销的（撤销点了跟没点一样）
M_NO_LIST_FILTER = lambda s: _drop(s, "    if not include_deleted:\n        stmt = stmt.where(ShipperReceipt.is_deleted.is_(False))\n")
# ⑧ 列表摘掉 include_deleted 档（回收站没了 = 恢复没有落点）
M_NO_INCLUDE_DELETED = lambda s: _drop(s, "    include_deleted: bool = Query(False, description=" + chr(34) + "含已撤销的（回收站）" + chr(34) + "),\n")
# ⑨ 审计码摘掉一个
M_DROP_CODE = lambda s: _drop(s, "    RECEIPT_CANCEL = " + chr(34) + "RECEIPT_CANCEL" + chr(34) + "\n")
# ⑩ 审计页的中文名摘掉一个
M_DROP_LABEL = lambda s: _drop(s, "    " + chr(34) + "RECEIPT_CANCEL" + chr(34) + " -> " + chr(34) + "撤销收款" + chr(34) + "\n")
# ⑪ 模型不再挂 SoftDeleteMixin（收款单没有软删两列）
M_NO_MIXIN = lambda s: s.replace("class ShipperReceipt(Base, TimestampMixin, SoftDeleteMixin):", "class ShipperReceipt(Base, TimestampMixin):", 1)
# ⑫ 线上迁移那段 DDL 删掉（已上线的库没有这两列，撤销接口当场 500）
M_NO_MIGRATION = lambda s: s.replace('    if "shipper_receipts" in tables:\n', "    if False:\n", 1)
# ⑬ 界面把「撤销」键摘掉（又回到"只有接口没有界面"）
M_NO_CANCEL_BTN = lambda s: s.replace("Text(" + chr(34) + "撤销" + chr(34) + ", color = MaterialTheme.colorScheme.error)", "Text(" + chr(34) + "作废" + chr(34) + ", color = MaterialTheme.colorScheme.error)", 1)
# ⑭ 界面把回收站档摘掉（撤销完再也找不回来）
M_NO_BIN = lambda s: s.replace("Text(if (vm.showDeleted) " + chr(34) + "只看未撤销" + chr(34) + " else " + chr(34) + "显示已撤销" + chr(34) + ")", "Text(" + chr(34) + "收款记录" + chr(34) + ")", 1)
# ⑮ Apis.kt 摘掉 restore 端点
M_NO_RESTORE_API = lambda s: _drop(s, "    @POST(" + chr(34) + "ledger/receipts/{receiptId}/restore" + chr(34) + ")\n")
# ⑯ AI 侧的排期理由删掉（覆盖率门禁会红）
M_NO_EXCLUDED = lambda s: s.replace('    ("DELETE", "ledger/receipts/{}"): (', '    ("DELETE", "ledger/receipts/XXX"): (', 1)
# ⑰ AiRevert 把那句假话改回去
M_REVERT_BAD = lambda s: s.replace(
    "            " + chr(34) + "AI 替你撤回这笔收款这一步还没开；请到账本 →「客户收款」的收款记录里点那一行的「撤销」（那是可恢复的软删，不是把账抹掉）" + chr(34) + ",",
    "            " + chr(34) + "收款一旦入账，撤回来等于把账抹掉；要改请在账本里改那一笔" + chr(34) + ",",
    1,
)
# ⑱ 回归用例改名
M_RENAME_CASE = lambda s: s.replace("def test_cancel_never_physically_deletes_anything(", "def test_cancel_never_physically_deletes_anything_x(", 1)
# ⑲ 变更单少一节
M_DOC_SECTION = lambda s: s.replace("## ⑨ 关闭", "## ⑨ 收尾", 1)
# ⑳ 登记表去掉「已提交」
M_REG_UNSUBMIT = lambda s: s.replace("（5556/5558）；**已提交", "（5556/5558）；**待提交", 1)
# ㉑ 台账 TB-09 行改名
M_LEDGER_RENAME = lambda s: s.replace("| TB-09 |", "| TB-09x |", 1)
# ㉒ 认领簿换号
M_CLAIM_NUMBER = lambda s: s.replace("BUG-0029", "BUG-002X")

CASES = [
    ("只软删流水、不翻 orders.paid", LEDGER, M_NO_PAID_FLIP, "CHECK:落点②：订单收回未收款"),
    ("只翻 paid、不软删流水", LEDGER, M_NO_FLOW_SOFTDEL, "CHECK:落点①：这笔收款的资金流水逐行软删"),
    ("撤销改成物理删除收款单", LEDGER, M_PHYSICAL_DELETE, "CHECK:落点③：收款单本身软删"),
    ("第二次撤销的闸门拆掉", LEDGER, M_NO_IDEMPOTENT_GATE, "CHECK:「收款单已删」是幂等的唯一依据"),
    ("恢复不判「该单又被收过一次」", LEDGER, M_NO_PAID_GATE, GATE_CASE),
    ("恢复不把流水放回来", LEDGER, M_NO_FLOW_RESTORE, "CHECK:恢复把流水与收款单原样放回"),
    ("列表不再默认过滤已撤销的", LEDGER, M_NO_LIST_FILTER, "CHECK:默认过滤 is_deleted"),
    ("列表摘掉 include_deleted 档", LEDGER, M_NO_INCLUDE_DELETED, "CHECK:收款记录加了 include_deleted 档"),
    ("审计码摘掉一个", ENUMS, M_DROP_CODE, "CHECK:两个新审计码在 enums.py 里"),
    ("审计页的中文名摘掉一个", REPORT, M_DROP_LABEL, "CHECK:ReportCenter.kt 给了两个中文名"),
    ("模型不再挂 SoftDeleteMixin", MODEL, M_NO_MIXIN, "CHECK:模型上真的挂了 SoftDeleteMixin"),
    ("线上迁移那段 DDL 删掉", BOOT, M_NO_MIGRATION, "CHECK:线上迁移补了 shipper_receipts 的两列"),
    ("界面把「撤销」键摘掉", SCREEN, M_NO_CANCEL_BTN, "CHECK:收款页有「撤销」键"),
    ("界面把回收站档摘掉", SCREEN, M_NO_BIN, "CHECK:收款页有回收站档"),
    ("Apis.kt 摘掉 restore 端点", APIS, M_NO_RESTORE_API, "CHECK:Apis.kt 两个新端点"),
    ("AI 侧的排期理由删掉", COVER, M_NO_EXCLUDED, "CHECK:在 _write_coverage 的 EXCLUDED 里有书面理由"),
    ("AiRevert 把那句假话改回去", REVERT, M_REVERT_BAD, "CHECK:AiRevert 里那句"),
    ("回归用例改名", KTEST, M_RENAME_CASE, "CHECK:七条用例逐条还在"),
    ("变更单少一节", DOC, M_DOC_SECTION, "CHECK:变更单 docs/changes/BUG-0029.md 在，且九节齐全"),
    ("登记表去掉「已提交」", REG, M_REG_UNSUBMIT, "CHECK:登记表 docs/changes/README.md 有 BUG-0029 行"),
    ("台账 TB-09 行改名", LEDGERDOC, M_LEDGER_RENAME, "CHECK:台账 docs/TEST_BUG_LEDGER.md 的 TB-09 行标着「已修复」"),
    ("认领簿换号", CLAIM, M_CLAIM_NUMBER, "CHECK:认领簿有 BUG-0029 的声明"),
]


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def failed_count(out: str) -> int:
    hits = re.findall("([0-9]+) failed", out)
    return int(hits[-1]) if hits else 0


def run_test(node: str) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header"],
        cwd=str(ROOT / "backend"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_judge() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(JUDGE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    lock_reverse_verify()
    try:
        code, out = run_judge()
        if code != 0:
            print("❌ 前提不成立：源码完好时判据脚本就没过")
            print(out[-1500:])
            return 1
        code, out = run_test("tests/test_receipt_undo.py")
        if code != 0 or failed_count(out) > 0:
            print("❌ 前提不成立：源码完好时回归用例就没过")
            print(out[-1500:])
            return 1
        print("✅ 前提：源码完好时判据脚本与 7 条回归用例都是绿的")

        touched = sorted({rel for _l, rel, _m, _n in CASES})
        originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
        crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

        for label, rel, mutate, node in CASES:
            path = ROOT / rel
            plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
            mutated = mutate(plain)
            if mutated == plain:
                fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
                print(f"  [SKIP] {label}")
                continue
            try:
                write_src(path, mutated, crlfs[rel])
                if node.startswith("CHECK:"):
                    jcode, jout = run_judge()
                    expect = node.split(":", 1)[1]
                    hit = jcode != 0 and any("[FAIL]" in ln and expect in ln for ln in jout.splitlines())
                    kind = "判据"
                else:
                    tcode, tout = run_test(node)
                    hit = tcode != 0 and failed_count(tout) > 0
                    kind = "回归用例"
            finally:
                path.write_bytes(originals[rel])
            if hit:
                print(f"  [OK] {label} → {kind}报红")
            else:
                fails.append(f"{label}：注入之后**没有任何检查报红**（修复没有被钉住）")
                print(f"  [MISS] {label} → 全绿")

        dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
        if dirty:
            fails.append("跑完没逐字节还原：" + "、".join(dirty))
            for rel in dirty:
                (ROOT / rel).write_bytes(originals[rel])
            print("⚠️  已强制还原：" + "、".join(dirty))
        else:
            print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

        print()
        if fails:
            print("❌ 反向验证不通过：")
            for f in fails:
                print("   - " + f)
            return 1
        print(f"✅ {len(CASES)}/{len(CASES)} 都红了 —— BUG-0029 的修复每一处都被钉住。")
        return 0
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    sys.exit(main())
