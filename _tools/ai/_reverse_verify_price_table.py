"""反向验证「按表格调价 + 调价必须留痕」这一节红线**真的会红**。

### 为什么值得单独一个脚本
这一节守着两件**做漏了也看不出来**的事：
① 按表格调价是**逐行**发请求的（一张 20 行的表 = 20 个请求），中间某一行失败时，
   其余行已经写进去了——如果最终答复只回一句"已完成"，**用户会以为 20 行全成了**；
② 用户明确要求"每条改动在操作日志里可回查"，而 `price_rules.py` 在 v3.21 之前
   **一条日志都不写**（枚举里躺着 PRICE_RULE_UPSERT，从来没人用过）。

这两条都属于"删掉之后功能照跑、只是悄悄变坏"的类型，所以必须有注入证据。

用法：python _tools/ai/_reverse_verify_price_table.py     # 5/5 都红 → 退出码 0
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
PRICING = AI / "AiWritePricing.kt"
SERVICE = AI / "AiWriteService.kt"
TABLE = AI / "AiPriceTable.kt"
WRITE = AI / "AiWrite.kt"
PRICE_API = ROOT / "backend/app/api/v1/price_rules.py"


def read_src(p: Path):
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check() -> str:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return (r.stdout or "") + (r.stderr or "")


def sub(path: Path, old: str, new: str):
    def mutate(src: str) -> str:
        return src.replace(old, new, 1)

    return (path, mutate)


MUTATIONS = [
    (
        "逐行失败被吞掉（不再收集失败行）——用户只会看到「已完成」",
        [
            sub(
                PRICING,
                "            } catch (e: Exception) {\n                failed += ",
                "            } catch (e: Exception) {\n                // failed += ",
            )
        ],
        "逐行失败被收集起来",
    ),
    (
        "执行结果不再汇报逐行结果（commitNote 被去掉）",
        [sub(PRICING, "    override fun commitNote(): String? = pendingNote.also { pendingNote = null }",
             "    private fun commitNoteLost(): String? = pendingNote")],
        "执行结果如实汇报",
    ),
    (
        "服务层不再把逐行结果拼进答复（红线只查代码形状，这里注入的是调用点）",
        [sub(SERVICE, "            val note = handler.commitNote()", "            val note: String? = null")],
        "服务层把逐行结果拼进最终答复",
    ),
    (
        "后端批量调价不再写审计日志（价改了却查不到是谁改的）",
        [sub(PRICE_API, "\n    _log_price_changes(\n        db,", "\n    _noop_log(\n        db,")],
        "日志与写价在同一个事务里",
    ),
    (
        "把表格调价塞进货主白名单（越权：货主能改价）",
        [sub(WRITE, "    val SHIPPER_ACTIONS: Set<String> = setOf(", "    val SHIPPER_ACTIONS: Set<String> = setOf(\n        PRICE_RULES_APPLY_TABLE,")],
        "调价类动作都不在货主白名单里",
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
                write_src(path, src, crlf)
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
    print("\n" + (f"✅ {total}/{total} 都红了：这节检查真的在检查。" if bad == 0 else f"❌ {bad}/{total} 不达标。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
