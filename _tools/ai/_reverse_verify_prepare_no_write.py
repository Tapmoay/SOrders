"""反向验证「prepare 里绝对不许写后端」这条检查**真的在扫所有处理器文件**。

### 为什么值得单独一个脚本
v3.20 之前这条检查有两个空转（都属于"检查还在、但已经不看任何东西"）：
① 只扫 `AiWriteBasicHandlers.kt` + `AiWriteOrderHandlers.kt`；
② 写方法名单是手写的 9 个，而数据源接口已经有 50 多个方法。

于是"在 prepare 里顺手把库写掉"这种**最要命的 bug**，落在账本 / 商品行 / 消息 /
批量调价 / 结算这几个文件里是无声无息的——而它一旦发生，确认卡就变成了事后通知。
这个脚本就是证明"现在真的会红"：**故意往旧检查不看的那几个文件里注入写调用**，
再各注入一次"检查本身失效"的 bug（白名单过期、commit 被删）。

用法：python _tools/ai/_reverse_verify_prepare_no_write.py     # 6/6 都红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ai_guardrails.py"
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
SERVICE = AI / "AiWriteService.kt"
SETTLE = AI / "AiWriteSettlementHandlers.kt"
PRICING = AI / "AiWritePricing.kt"


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
    # 还原**当场核对**（R3-07b）：写回后**重新读回来比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的内容 == 快照 才是（L2 要的就是这一句）。
    # 实测教训（2026-09-26）：有份反向验证的还原写的是**另一个文件的字节**，而它自己那句核对
    # 比的也是同一份错字节 ⇒ 恒等通过，把两个源码文件整份写坏。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

def run_check() -> str:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return (r.stdout or "") + (r.stderr or "")


def sub(path: Path, old: str, new: str):
    """构造一个「把 old 换成 new」的变更（找不到 old 时会报 SKIP，不静默放过）。"""

    def mutate(src: str) -> str:
        return src.replace(old, new, 1)

    return (path, mutate)


# 每条 = (说明, [(文件, 变更), ...], 期望在 FAIL 里看到的字样)
MUTATIONS = [
    (
        "结算处理器（v3.20 新增文件）的 prepare 里偷偷写库",
        [
            sub(
                SETTLE,
                "        val named = resolveDriver(driverName)\n",
                "        val named = resolveDriver(driverName)\n"
                '        ds.generateDriverBills(null, "2026-09", "piece")\n',
            ),
        ],
        "AiWriteSettlementHandlers.kt: prepare 里没有写后端的调用",
    ),
    (
        "批量调价的 prepare 里偷偷写库（这个动作的卡片最需要「先算给你看」）",
        [
            sub(
                PRICING,
                "        // ---- 1. 范围：批发商 × 商品，都允许留空表示",
                "        ds.createExpense(null, null)\n"
                "        // ---- 1. 范围：批发商 × 商品，都允许留空表示",
            ),
        ],
        "AiWritePricing.kt: prepare 里没有写后端的调用",
    ),
    (
        "账本处理器（v3.17 新增文件）的 prepare 里偷偷写库",
        [
            sub(
                AI / "AiWriteLedgerHandlers.kt",
                "        return card(\n            summary = \"删账本流水",
                "        ds.deleteLedgerEntry(1)\n        return card(\n            summary = \"删账本流水",
            ),
        ],
        "AiWriteLedgerHandlers.kt: prepare 里没有写后端的调用",
    ),
    (
        "新增一个数据源方法并直接在 prepare 里用它（fail-closed：不在读白名单里就算写）",
        [
            sub(
                SERVICE,
                "    /** 删消息：`ids` 指定一批，或 `all=true` 清空自己的全部消息。 */\n",
                "    suspend fun brandNewWriteCall(x: Long)\n\n"
                "    /** 删消息：`ids` 指定一批，或 `all=true` 清空自己的全部消息。 */\n",
            ),
            sub(
                SETTLE,
                "        val named = resolveDriver(driverName)\n",
                "        ds.brandNewWriteCall(1)\n        val named = resolveDriver(driverName)\n",
            ),
        ],
        "AiWriteSettlementHandlers.kt: prepare 里没有写后端的调用",
    ),
    (
        "读方法被改名而白名单没跟着改（白名单成了化石，检查会空转）",
        [
            sub(
                SERVICE,
                "    suspend fun driverBills(driverId: Long?, month: String?, billType: String?): List<AiDriverBill>\n",
                "    suspend fun driverBillsRenamed(driverId: Long?, month: String?, billType: String?): List<AiDriverBill>\n",
            ),
        ],
        "读方法白名单没有过期",
    ),
    (
        "把某个处理器的 commit 整段删掉（卡片点下去什么都没发生）",
        [
            sub(
                SETTLE,
                "    override suspend fun commit(payload: JsonObject, idempotencyKey: String) {\n"
                '        ds.settlementAction(payload.reqLong("settlement_id"), "cancel", "cash")\n'
                "    }\n",
                "",
            ),
        ],
        "点确认真的会写",
    ),
]


def main() -> int:
    bad = 0
    base = run_check()
    base_ok = "项通过" in base
    print(f"  [{'OK' if base_ok else 'MISS'}] 基线：没有注入时红线全绿")
    bad += 0 if base_ok else 1

    for label, changes, expect in MUTATIONS:
        originals = []
        skip = False
        for path, mutate in changes:
            src, crlf = read_src(path)
            mutated = mutate(src)
            if mutated == src:
                print(f"  [SKIP] {label} —— 锚点没找到：{path.name}")
                skip = True
                break
            originals.append((path, src, crlf))
            write_src(path, mutated, crlf)
        if skip:
            for path, src, crlf in originals:
                write_src(path, src, crlf)
            bad += 1
            continue
        try:
            out = run_check()
        finally:
            for path, src, crlf in originals:
                restore_src(path, src, crlf)
        fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
        hit = any(expect in ln for ln in fails)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → 期望红：{expect}（实际红 {len(fails)} 条）")
        if not hit:
            for ln in fails[:3]:
                print("        " + ln.strip())
            bad += 1

    tail = run_check()
    ok = "项通过" in tail
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 2
    print("\n" + (f"✅ {total}/{total} 都红了：这条检查真的在检查。" if bad == 0 else f"❌ {bad}/{total} 不达标。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
