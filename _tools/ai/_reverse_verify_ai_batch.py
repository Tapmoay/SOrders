"""反向验证：把「AI 批量捷径」那一节红线（`_check_ai_guardrails.py` §32）逐条弄坏，看它**真的会红**。

### 为什么这一块必须反向验证
批量是**一次动多条**的能力，它坏掉的方式全都"不报错"：
- 少做一条（用户按"全做完了"理解）→ 那是最坏的一类反馈；
- 说好的"一张卡确认一次"变成"预览阶段就写库"（自动执行档混进来）；
- 卡片答应了一句做不到的话（"会出现撤回"，而批量没有撤回）；
- 把用户手里那张**单条卡**顺手删掉（内层的卡和批量的卡挤在同一个暂存区）；
- 反过来，把既有处理器改一遍去支持批量（那是用户明令禁止的"动核心"）。

这些只有机器判据能拦住，而"判据本身是不是在检查"只能靠注入法证明。

用法：python _tools/ai/_reverse_verify_ai_batch.py     # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ai_guardrails.py"

AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
BATCH = AI / "AiWriteBatch.kt"
SVC = AI / "AiWriteService.kt"
WRITE = AI / "AiWrite.kt"
TOOLS = AI / "AiTools.kt"
LOOP = AI / "AiAgentLoop.kt"

#: 自动执行档那道门**整块**（挪位置那条注入要把它删掉再加到别处）
AUTO_GATE = """        // ---- 不变量 1：自动执行档不许走批量 ----
        if (action.risk == AiWriteRisk.AUTO_EXECUTABLE) {
            throw AiWriteArgException(
                "「${action.title}」本来就不需要确认（一次全量生效），不能再套一层批量。" +
                    "直接调它一次就行。",
            )
        }
"""

# (说明, [(文件, 原文, 替换成), …], 期望变红的检查名关键词)
SCENARIOS: list[tuple[str, list[tuple[Path, str, str]], str]] = [
    (
        "批量层不再实现同一个接口（另起一套执行器）",
        [(BATCH, ") : AiWriteHandler {", ") {")],
        "实现的是**同一个接口**",
    ),
    (
        "接线点丢了（表里还是原来的处理器，批量层形同虚设）",
        [(SVC, "AiWrites.byId(id)?.let { a -> BatchWriteHandler(a, h, store) } ?: h", "h")],
        "套的就是它",
    ),
    (
        "自动执行档那道门被删掉（预览阶段就写库）",
        [(BATCH, AUTO_GATE, "")],
        "自动执行档在**调用内层之前**就被挡掉",
    ),
    (
        "那道门挪到逐条 prepare 之后（位置错了这条红线就没意义）",
        [
            (BATCH, AUTO_GATE, ""),
            (
                BATCH,
                "        val card = store.card(",
                "        if (action.risk == AiWriteRisk.AUTO_EXECUTABLE) {\n"
                '            throw AiWriteArgException("挪到后面了")\n'
                "        }\n"
                "        val card = store.card(",
            ),
        ],
        "挡的位置在**第一次调用内层之前**",
    ),
    (
        "给批量加一个条数上限（用户明确说没有上限）",
        [
            (
                BATCH,
                "        val rows = ArrayList<AiPendingWrite>(items.size)",
                "        if (items.size > MAX_BATCH_ITEMS) throw AiWriteArgException(\"太多了\")\n"
                "        val rows = ArrayList<AiPendingWrite>(items.size)",
            ),
        ],
        "**不设条数上限**",
    ),
    (
        "某一条不合法时报的错不带「第几条」",
        [
            (
                BATCH,
                'throw AiWriteArgException("第 ${i + 1} 条：${e.message ?: "参数不正确。"}", e.candidates)',
                "throw e",
            ),
        ],
        "处理器抛的错补上「第几条」",
    ),
    (
        "失败的那几条干脆不记（用户会以为 20 条全成了）",
        [(BATCH, 'failed += "#${i + 1} " + brief(e)', "// 失败就算了")],
        "失败的那几条要逐条记下来",
    ),
    (
        "单条那条路吞掉内层的 commitNote（「按表格调价 10 行成功 2 行失败」又被盖住）",
        [(BATCH, "                note = inner.commitNote()\n", "")],
        "单条那条路转发内层的 commitNote",
    ),
    (
        "取消被当成失败吞掉（用户主动中止被汇报成「没写成功」）",
        [
            (
                BATCH,
                "            } catch (e: CancellationException) {\n"
                "                throw e\n"
                '            } catch (e: Exception) {\n'
                '                failed += "#${i + 1} " + brief(e)',
                '            } catch (e: Exception) {\n                failed += "#${i + 1} " + brief(e)',
            ),
        ],
        "取消原样抛",
    ),
    (
        "commitNote 不再取走即清空（下一次执行会读到上一次的结果）",
        [
            (
                BATCH,
                "override fun commitNote(): String? = note.also { note = null }",
                "override fun commitNote(): String? = note",
            ),
        ],
        "结果交给服务层拼进最终答复",
    ),
    (
        "批量卡的最后一行退回单条那句（答应了一件做不到的事）",
        [(WRITE, "                batch -> AiWrites.BATCH_UNDO_NOTE\n", "")],
        "最后一行按「撤回卡 / 批量卡 / 普通卡」三选一",
    ),
    (
        "批量标记改回 `items`（与退货明细同名 → 普通退货会被认成一批）",
        [(BATCH, 'const val BATCH_PAYLOAD = "_batch"', 'const val BATCH_PAYLOAD = "items"')],
        "批量标记是保留字",
    ),
    (
        "取走内层卡时不再分辨哪些是新的（把用户手里那张也删了）",
        [
            (
                BATCH,
                "store.list().filter { it.token !in known }.forEach { store.take(it.token) }",
                "store.list().forEach { store.take(it.token) }",
            ),
        ],
        "只取**这一次新登记**的卡",
    ),
    (
        "每条只留摘要、不列明细（用户核对不了到底改了什么）",
        [
            (
                BATCH,
                'listOf("———— 第 ${i + 1} 条 ————", r.summary) + r.bodyLines',
                'listOf("———— 第 ${i + 1} 条 ————", r.summary)',
            ),
            (
                BATCH,
                "listOf(r.summary) + r.bodyLines",
                "listOf(r.summary)",
            ),
        ],
        "明细行用的是没被追加过的那份",
    ),
    (
        "服务层又给批量去建撤回方案（AiRevert.plan 只认单条 payload）",
        [(SVC, "val undo = if (batched) {", "val undo = if (false) {")],
        "批量不建撤回方案",
    ),
    (
        "服务层又开始报「没能挂上撤回」（批量本来就没撤回）",
        [(SVC, "val broken = !batched &&", "val broken = true &&")],
        "批量也不报",
    ),
    (
        "参数说明里不再教 `items`（模型根本不知道有这条路）",
        [(TOOLS, "一次改多条（批量捷径）", "（这里原来有一段批量的说明）")],
        "参数说明里教了 `items`",
    ),
    (
        "提示词里不再要求「一次提交」（模型又会一条一条地调）",
        [(LOOP, "一次要改/要建好几条时，用「批量」一次提交", "（删掉了这条规则）")],
        "提示词里有一条",
    ),
]


class Sandbox:
    """按字节记住原样，最后一次性还原（⛔ 不用 `git checkout --`：那会抹掉未提交的真实改动）。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, edits: list[tuple[Path, str, str]]) -> None:
        for path, old, new in edits:
            if path not in self.saved:
                self.saved[path] = path.read_bytes()
            text = path.read_bytes().decode("utf-8")
            if text.count(old) != 1:
                raise AssertionError(f"{path.name}: 原文出现 {text.count(old)} 次，无法唯一替换")
            path.write_bytes(text.replace(old, new).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)
            # R3-07b：还原**当场核对**（写回后再读回来逐字节比）—— 对不上就非零退出，
            # ⛔ 别让注入留在源码树里（实测过一次：崩在还原前，注入留了一整天）。
            if p.read_bytes() != raw:
                print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
                raise SystemExit(2)
        self.saved.clear()


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    if not CHECK.exists():
        print(f"❌ 找不到 {CHECK}")
        return 1

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print(f"❌ 前提不成立：源码完好时红线没过\n{out[-1500:]}")
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print(f"✅ 前提：源码完好时红线是绿的 —— {last.strip()}")

        for label, edits, expect in SCENARIOS:
            sb.restore()
            try:
                sb.apply(edits)
            except AssertionError as e:
                print(f"  [SKIP] {label} —— {e}（判据该更新了）")
                bad += 1
                continue
            try:
                code, out = run_check()
            finally:
                sb.restore()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            hit = code != 0 and any(expect in ln for ln in fails)
            detail = f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")
            print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
            if not hit:
                bad += 1

        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    total = len(SCENARIOS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
