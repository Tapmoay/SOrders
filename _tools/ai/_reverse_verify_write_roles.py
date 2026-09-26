"""反向验证「AI 的写权限按角色裁剪」那几条红线**真的会红**。

### 用户的口径（原话）
> 「AI 的权限是按照角色的权限进行划分的——派单员属于管理员，权限最大、基本是全部；
>   货主好多权限根本不需要操作，它只需要知道自己该干的事情就可以了，所以权限比较小。」
> 「AI 说自己能干好多事情，是因为你那个系统提示词没写好、没有分开。」

四句话对应四组判据，每一句都要能被破坏、并且破坏之后必须报红：

1. **货主小** —— 他的动作走**白名单**；往白名单里塞一个派单/主数据/账本写入动作 → 必须红。
2. **认不出角色就什么都不给**（fail-closed）—— `null -> emptyList()` 改成 `null -> ALL` → 必须红。
3. **派单员是全部** —— `AiRole.DISPATCHER -> ALL` 被换掉（比如"也顺便裁一下"）→ 必须红。
4. **身份提示词按角色分**（v3.28 新加）—— 提示词写死"给派单员用的助手"、或货主那段被换成
   派单员那段 → 必须红（前三条挡不住这一类：权限裁得再干净，提示词照样能让它念出派单员的能力）。

用法：python _tools/ai/_reverse_verify_write_roles.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
SRC = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
CHECK = HERE / "_check_ai_guardrails.py"
GRADLE = ROOT / "_agent/gradle/gradle-8.9/bin/gradle.bat"
W = SRC / "AiWrite.kt"
LOOP = SRC / "AiAgentLoop.kt"
ROLE_PROMPT = SRC / "AiRolePrompt.kt"
TOOLS = SRC / "AiTools.kt"
UNIT = "__UNIT__"  # 这一条只有单测抓得住（见下面的说明）

# (说明, 期望变红的检查名关键词 / UNIT=靠单测抓, 破坏方式, 改哪个文件)
# ⚠️ 为什么要有 UNIT 这一档：**红线是文本检查，抓不到"语义被换掉"**。
#    「货主的身份段被换成派单员那段」在文本上还是 `SHIPPER_IDENTITY = …`，红线照样绿；
#    真正能抓住它的是单测（它断言货主那段里不许出现派单员的能力名）。
MUTATIONS: list[tuple[str, str | None, object, Path]] = [
    (
        "货主白名单里塞进「派单」（最典型的越权：他能把别人的单派出去）",
        "货主白名单里没有主数据",
        lambda s: s.replace("        ORDERS_CREATE,\n", "        ORDERS_ASSIGN,\n        ORDERS_CREATE,\n", 1),
        W,
    ),
    (
        "货主白名单里塞进「批发商调价」",
        "货主白名单里没有主数据",
        lambda s: s.replace("        ORDERS_CREATE,\n", "        PRICE_RULES_BATCH,\n        ORDERS_CREATE,\n", 1),
        W,
    ),
    (
        "货主白名单里塞进「记一笔账本流水」（他对账本只有只读）",
        "货主白名单里没有主数据",
        lambda s: s.replace("        ORDERS_CREATE,\n", "        LEDGER_CREATE_ENTRY,\n        ORDERS_CREATE,\n", 1),
        W,
    ),
    (
        "货主白名单里塞进「建账号」",
        "货主白名单里没有主数据",
        lambda s: s.replace("        ORDERS_CREATE,\n", "        USERS_CREATE,\n        ORDERS_CREATE,\n", 1),
        W,
    ),
    (
        "fail-closed 破了：认不出角色时给全部",
        "认不出角色就返回空",
        lambda s: s.replace("        null -> emptyList()", "        null -> ALL", 1),
        W,
    ),
    (
        "派单员被「顺便裁一下」（不再是全量）",
        "派单员确实是全量",
        lambda s: s.replace("        AiRole.DISPATCHER -> ALL", "        AiRole.DISPATCHER -> ALL.take(3)", 1),
        W,
    ),
    (
        "货主直接等于全量（等于没裁，只是换了写法）",
        "货主确实按白名单过滤",
        lambda s: s.replace(
            "        AiRole.SHIPPER -> ALL.filter { it.id in SHIPPER_ACTIONS }",
            "        AiRole.SHIPPER -> ALL",
            1,
        ),
        W,
    ),
    # ---- 身份提示词（v3.28）：提示词写死派单员 = 货主被念一遍派单员的能力 ----
    (
        "身份提示词又写死成派单员那一份（用户说的「没分开」）",
        "给派单员用的助手",
        lambda s: s.replace(
            "            appendLine(AiRolePrompt.brief(tools.role, tools.enabledReadModules))",
            '            appendLine("你是「SOrders 派单送货管理系统」里给派单员用的助手。")',
            1,
        ),
        LOOP,
    ),
    (
        "「你能改的域」不按角色算，写死派单员那七个",
        "提示词里不再写死派单员的七个域",
        lambda s: s.replace(
            'appendLine("     你这个角色能用的是这些域：${writeGroupsHint()}。")',
            'appendLine("     它按【订单】【账目】【商品】【批发商定价】【库存】【账号与收费规则】【消息】分组。")',
            1,
        ),
        LOOP,
    ),
    (
        "货主的身份段被换成派单员那段（货主读到「你管全部」）",
        UNIT,
        lambda s: s.replace(
            "    private const val SHIPPER_IDENTITY =",
            "    private const val SHIPPER_IDENTITY = DISPATCHER_IDENTITY +",
            1,
        ),
        ROLE_PROMPT,
    ),
    (
        "「不归你」那段被删（货主不知道哪些不归他，就会去试）",
        UNIT,
        lambda s: s.replace("            if (notMine.isNotEmpty()) {", "            if (false) {", 1),
        ROLE_PROMPT,
    ),
    # ---- 工具本身不按角色裁（v3.28 真机抓到的根因：货主拿到了 库存预警/司机跑车统计/出表格）----
    (
        "工具白名单又给货主放回「出表格」（他会承诺导出 Excel）",
        UNIT,
        lambda s: s.replace(
            "            AiRole.SHIPPER to setOf(READ_DATA, REMEMBER, PREVIEW_WRITE),",
            "            AiRole.SHIPPER to setOf(READ_DATA, REMEMBER, PREVIEW_WRITE, EXPORT_SHEET),",
            1,
        ),
        TOOLS,
    ),
    (
        "工具白名单又给货主放回「司机跑车统计」（他会说自己能查司机绩效）",
        UNIT,
        lambda s: s.replace(
            "            AiRole.SHIPPER to setOf(READ_DATA, REMEMBER, PREVIEW_WRITE),",
            "            AiRole.SHIPPER to setOf(READ_DATA, REMEMBER, PREVIEW_WRITE, DRIVER_PERFORMANCE),",
            1,
        ),
        TOOLS,
    ),
    (
        "工具清单不再按角色过滤（只裁说明，工具照给）",
        "工具清单按角色过滤",
        lambda s: s.replace("            return ALL.filter { it in on && it in mine }.map {", "            return ALL.filter { it in on }.map {", 1),
        TOOLS,
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
    # 还原**当场核对**（R3-07b）：写回后**重新读回来比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的内容 == 快照 才是（L2 要的就是这一句）。
    # 实测教训（2026-09-26）：有份反向验证的还原写的是**另一个文件的字节**，而它自己那句核对
    # 比的也是同一份错字节 ⇒ 恒等通过，把两个源码文件整份写坏。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_unit_tests() -> tuple[int, str]:
    r = subprocess.run(
        [str(GRADLE), "--project-dir", str(ROOT / "android"), ":app:testEmuDebugUnitTest", "--console=plain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    bad = 0

    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时红线没过\n{out[-1500:]}")
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    for label, expect, mutate, path in MUTATIONS:
        original, crlf = read_src(path)
        mutated = mutate(original)  # type: ignore[operator]
        if mutated == original:
            print(f"  [SKIP] {label} —— 注入没生效（源码里那段变了，请更新替换串）")
            bad += 1
            continue
        write_src(path, mutated, crlf)
        try:
            if expect == UNIT:
                code, out = run_unit_tests()
                hit = code != 0
                fails = [ln.strip() for ln in out.splitlines() if "FAILED" in ln]
                detail = f"单测报错 {len(fails)} 条" + (f"（{fails[0][:60]}）" if fails else "")
            else:
                code, out = run_check()
                if expect is None:
                    hit = code != 0
                else:
                    hit = code != 0 and any("[FAIL]" in ln and expect in ln for ln in out.splitlines())
                fails = [ln.strip() for ln in out.splitlines() if "[FAIL]" in ln]
                detail = f"实际红 {len(fails)} 条" + (f"（{fails[0][:70]}）" if fails else "")
        finally:
            restore_src(path, original, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    if bad:
        print(f"\n❌ {bad}/{total} 不达标。")
        return 1
    print(f"\n✅ {total}/{total} 都红了：角色裁剪这一节的判据真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
