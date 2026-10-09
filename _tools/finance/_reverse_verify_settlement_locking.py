"""反向验证 BUG-0024（司机结算单的「锁」）那批修复**真的在检查**。

2026-10-10 测试会话点名（台账 TB-08）：同一笔司机明细（driver_id=3 / 2026-06 / 明细 id=12）
能被两张草稿结算单同时锁住 —— 建单当刻根本不落锁，冲突拖到确认才报，而且报错把
「被别的结算单占用」与「明细已被删除」糊成一句；接口层那句注释写的是「建结算单＝把一批
待结明细锁进一张单子」，与行为正好相反。修法三件事：建单当刻真的写锁（settled_doc_id，
状态仍是 OPEN）、确认报错按成因逐笔分开说、注释与行为对齐。

这份脚本逐条把修复弄坏，证明对应的检查（判据脚本 / 回归用例）会红。

| 注入 | 应该红的检查 |
|---|---|
| 建单当刻不再上锁 | 判据 / 同一笔明细不能被两张草稿单同时锁住 |
| 取数不再按锁过滤（别人锁着的也算回来） | 判据 / 同一笔明细不能被两张草稿单同时锁住 |
| 确认时不认本单自己的锁 | 判据 / 确认时报错要把被占用与已删除分开说 |
| 报错退回「（被删除或已被别的结算单占用）」那句糊话 | 同上 |
| 三种成因不再分开说 | 判据 |
| 点名单号的地方不再附单号 | 判据 / 确认时报错要把被占用与已删除分开说 |
| 老草稿的分支重新可以抢别人锁住的明细 | 判据 |
| 作废解锁只放回 SETTLED（草稿锁的行放不掉） | 判据 / 作废草稿单把锁放回待结 |
| 作废解锁把 CANCELLED 的行也复活 | 判据 |
| 作废解锁不再认 settled_doc_id | 判据 |
| 建单就把明细标成已结 | 判据 |
| 接口层注释 / 取数 docstring / 作废注释里的说明删掉 | 判据 |
| 回归用例改名 / 变更单少一节 / 登记表去掉「已提交」/ 台账行改名 / 认领簿换号 | 判据 |

⚠️ 快照/还原按**字节**做（仓库里有 CRLF 文件），跑完逐字节核对。

用法：python _tools/finance/_reverse_verify_settlement_locking.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
JUDGE = HERE / "_check_settlement_locking.py"

ACCT = "backend/app/services/accounting_service.py"
API = "backend/app/api/v1/driver_settlements.py"
KTEST = "backend/tests/test_settlement_locking.py"
DOC = "docs/changes/BUG-0024.md"
REG = "docs/changes/README.md"
LEDGER = "docs/TEST_BUG_LEDGER.md"
CLAIM = "docs/AI_WORK_CLAIM.md"

#: pytest 的 node 相对 backend/ 写（run_test 的 cwd 就是 backend/），别写成 backend/tests/...
LOCK_CASE = "tests/test_settlement_locking.py::test_同一笔明细不能被两张草稿单同时锁住"
SPLIT_CASE = "tests/test_settlement_locking.py::test_确认时报错要把被占用与已删除分开说"
UNLOCK_CASE = "tests/test_settlement_locking.py::test_作废草稿单把锁放回待结"

# ① 建单当刻不再上锁（create 尾那处赋值删掉）
M_NO_LOCK = lambda s: s.replace(
    "    for b in bills:\n        b.settled_doc_id = s.id\n    return s",
    "    for b in bills:\n        pass\n    return s",
    1,
)
# ② 取数不再按锁过滤：默认把「别人锁着的」也算回来
M_NO_FILTER = lambda s: s.replace(
    "            rows = rows.where(DriverBill.settled_doc_id.is_(None))\n",
    '            rows = rows.where(DriverBill.id > 0)  # 注入：不再按「有没有人锁着」过滤\n',
    1,
)
# ③ 确认时不认本单自己的锁（doc_id=s.id 拿掉）
M_CONFIRM_NOLOCK = lambda s: s.replace(
    "                doc_id=s.id,  # 「没被锁的」+「本单自己锁住的」——本单锁的那几行仍是 OPEN",
    "                include_claimed=True,  # 注入：连别人锁着的也当成本单的",
    1,
)
# ④ 报错退回那句把两种成因糊在一起的老话
M_CONFLATED = lambda s: s.replace(
    'f"{_why_gone(db, s, gone)}。请作废后重新结算"',
    'f"（被删除或已被别的结算单占用），请作废后重新结算"',
    1,
)
# ⑤ 三种成因不再分开说
M_NO_BUCKETS = lambda s: s.replace(
    '    if occupied:\n        parts.append(f"{len(occupied)} 笔已被别的结算单占用（{_claimed_where(db, occupied)}）")',
    '    if occupied or deleted or stale:\n        parts.append("有几笔已经不在了")',
    1,
)
# ⑥ 点名到单号的地方不再附单号
M_NO_DOCNO = lambda s: s.replace(
    '        f"明细 {b.id} 在结算单 {_settlement_label(db, int(b.settled_doc_id))}"',
    '        f"明细 {b.id} 已经被别的单占用"',
    1,
)
# ⑦ 老草稿的分支重新可以去抢别人锁住的明细
M_LEGACY_GATE = lambda s: s.replace(
    "                            DriverBill.settled_doc_id.is_(None),\n", "", 1
)
# ⑧ 作废解锁只放回 SETTLED：草稿锁着的那几行放不掉
M_UNLOCK_NARROW = lambda s: s.replace(
    "                DriverBill.settled_doc_id == s.id,\n"
    "                or_(\n"
    "                    DriverBill.status == DriverBillStatus.SETTLED,\n"
    "                    DriverBill.status == DriverBillStatus.OPEN,\n"
    "                ),",
    "                DriverBill.settled_doc_id == s.id,\n"
    "                DriverBill.status == DriverBillStatus.SETTLED,",
    1,
)
# ⑨ 作废解锁把保留任务作废（CANCELLED）的明细也复活
M_UNLOCK_CANCELLED = lambda s: s.replace(
    "                DriverBill.settled_doc_id == s.id,\n"
    "                or_(\n"
    "                    DriverBill.status == DriverBillStatus.SETTLED,\n"
    "                    DriverBill.status == DriverBillStatus.OPEN,\n"
    "                ),",
    "                DriverBill.settled_doc_id == s.id,\n"
    "                or_(\n"
    "                    DriverBill.status == DriverBillStatus.SETTLED,\n"
    "                    DriverBill.status == DriverBillStatus.OPEN,\n"
    "                    DriverBill.status == DriverBillStatus.CANCELLED,\n"
    "                ),",
    1,
)
# ⑩ 作废解锁不再认 settled_doc_id（改认司机）
M_UNLOCK_BY_DRIVER = lambda s: s.replace(
    "                DriverBill.settled_doc_id == s.id,\n                or_(",
    "                DriverBill.driver_id == s.driver_id,\n                or_(",
    1,
)
# ⑪ 建单就把明细标成已结（钱还没出）
M_CREATE_SETTLED = lambda s: s.replace(
    "    for b in bills:\n        b.settled_doc_id = s.id\n    return s",
    "    for b in bills:\n        b.status = DriverBillStatus.SETTLED\n        b.settled_doc_id = s.id\n    return s",
    1,
)
# ⑫ 接口层那句注释退回旧说法（注释与行为又对不上）
M_API_COMMENT = lambda s: s.replace(
    "    # 「锁」在建单当刻**真的发生**（2026-10-10 BUG-0024 修的就是这句注释与行为相反）：",
    "    # 建结算单＝把一批待结明细锁进一张单子（此处只是原来那句注释，行为不保证）。",
    1,
)
# ⑬ 取数口径的 docstring 删掉（不再明说「待结 ≠ 没人锁」）
M_SB_DOC = lambda s: s.replace(
    "    ⛔ 「待结」≠「没人锁」（2026-10-10 BUG-0024）：", "    ⛔ 取数口径：", 1
)
# ⑭ 作废解锁的注释删掉（不再明说锁在建单当刻就打上了）
M_CANCEL_DOC = lambda s: s.replace(
    '    #    ⚠️ 但"锁"从 2026-10-10（BUG-0024）起**在建单当刻就打上了**：草稿单锁住的那几行',
    "    #    ⚠️ 解锁只认已结算的行。",
    1,
)
# ⑮ 回归用例改名（用例掉数）
M_RENAME_CASE = lambda s: s.replace(
    "def test_同一笔明细不能被两张草稿单同时锁住(", "def test_同一笔明细_改个名字(", 1
)
# ⑯ 变更单少一节
M_DOC_SECTION = lambda s: s.replace("## ⑨ 关闭", "## ⑨ 收尾", 1)
# ⑰ 登记表把「已提交」摘掉
M_REG_UNSUBMIT = lambda s: re.sub(
    r"(?m)^(\| \`BUG-0024\` \|.*?)\*\*已提交", r"\1**待提交", s, count=1
)
# ⑱ 台账 TB-08 行改名（状态就没法标「已修复」）
M_LEDGER_RENAME = lambda s: s.replace("| TB-08 |", "| TB-08x |", 1)
# ⑲ 认领簿里的 BUG-0024 全换成别的号
M_CLAIM_NUMBER = lambda s: s.replace("BUG-0024", "BUG-2499")

#: (说明, 相对路径, 注入, 期望变红的 node；CHECK: 前缀 = 跑判据脚本并找那条 [FAIL])
CASES: list[tuple[str, str, object, str]] = [
    ("建单当刻不再上锁（第二张草稿单又能锁同一笔明细）", ACCT, M_NO_LOCK,
     "CHECK:create_settlement 里 b.settled_doc_id = s.id 写在 db.flush() 之后"),
    ("建单当刻不再上锁（行为面）", ACCT, M_NO_LOCK, LOCK_CASE),
    ("取数不再按锁过滤：别人锁着的也算回来", ACCT, M_NO_FILTER,
     "CHECK:默认只取「没人锁的」"),
    ("取数不再按锁过滤（行为面）", ACCT, M_NO_FILTER, LOCK_CASE),
    ("确认时不认本单自己的锁", ACCT, M_CONFIRM_NOLOCK,
     "CHECK:confirm_settlement 取数带 doc_id=s.id"),
    ("点名单号的地方不再附单号（行为面：报错里没有 #999999）", ACCT, M_NO_DOCNO, SPLIT_CASE),
    ("报错退回「（被删除或已被别的结算单占用）」那句糊话", ACCT, M_CONFLATED,
     "CHECK:糊成一句的老话已经不在 accounting_service.py 里"),
    ("报错退回糊话（行为面）", ACCT, M_CONFLATED, SPLIT_CASE),
    ("三种成因不再分开说", ACCT, M_NO_BUCKETS, "CHECK:_why_gone 把三种成因分开"),
    ("点名单号的地方不再附单号", ACCT, M_NO_DOCNO, "CHECK:_claimed_where 附单号"),
    ("老草稿的分支重新可以抢别人锁住的明细", ACCT, M_LEGACY_GATE,
     "CHECK:老草稿的两条重取分支都加了"),
    ("作废解锁只放回 SETTLED（草稿锁的行放不掉）", ACCT, M_UNLOCK_NARROW,
     "CHECK:cancel 解锁同时放回 SETTLED 与 OPEN 两种状态"),
    ("作废解锁只放回 SETTLED（行为面）", ACCT, M_UNLOCK_NARROW, UNLOCK_CASE),
    ("作废解锁把 CANCELLED 的行也复活", ACCT, M_UNLOCK_CANCELLED,
     "CHECK:cancel 解锁里没有 CANCELLED"),
    ("作废解锁不再认 settled_doc_id", ACCT, M_UNLOCK_BY_DRIVER,
     "CHECK:cancel 解锁仍认 settled_doc_id == s.id"),
    ("建单就把明细标成已结（钱还没出）", ACCT, M_CREATE_SETTLED,
     "CHECK:create_settlement 里没有 b.status ="),
    ("接口层那句注释退回旧说法", API, M_API_COMMENT,
     "CHECK:接口层注释仍然写着「真的发生」"),
    ("取数 docstring 删掉（不许明说「待结 ≠ 没人锁」）", ACCT, M_SB_DOC,
     "CHECK:settleable_bills 的 docstring 写清「待结 ≠ 没人锁」"),
    ("作废解锁的注释删掉", ACCT, M_CANCEL_DOC,
     "CHECK:cancel 的注释写清「锁在建单当刻就打上了」"),
    ("回归用例改名（用例掉数）", KTEST, M_RENAME_CASE, "CHECK:七条用例逐条还在"),
    ("变更单少一节", DOC, M_DOC_SECTION, "CHECK:变更单 docs/changes/BUG-0024.md 在，且九节齐全"),
    ("登记表把「已提交」摘掉", REG, M_REG_UNSUBMIT, "CHECK:登记表 docs/changes/README.md 有 BUG-0024 行"),
    ("台账 TB-08 行改名", LEDGER, M_LEDGER_RENAME, "CHECK:台账 docs/TEST_BUG_LEDGER.md 的 TB-08 行标着「已修复」"),
    ("认领簿里的 BUG-0024 全换成别的号", CLAIM, M_CLAIM_NUMBER, "CHECK:认领簿写了「核心改动："),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def failed_count(out: str) -> int:
    hits = re.findall(r"(\d+) failed", out)
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
    code, out = run_judge()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据脚本就没过")
        print(out[-1500:])
        return 1
    code, out = run_test("tests/test_settlement_locking.py")
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
    print(f"✅ {len(CASES)}/{len(CASES)} 都红了 —— BUG-0024 的修复每一处都被钉住。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
