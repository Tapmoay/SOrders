"""反向验证 _tools/qa/_check_ai_role_read_scope.py（AI 的角色读范围声明，GOV-0024）。

## 为什么这一节也要配反向验证
「AI 的范围声明」整条链都是**静态结构断言**：那句话拼没拼进提示词、文案是不是逐字没变、
目录给的角色宽不宽、执行前的门还在不在。这类判据最容易变成空转 —— 锚点过期、扫错文件、
顺手把断言放宽，它照样全绿（本仓栽过 6 次，规矩是**新增红线就要有注入实验**）。

这一轮特别容易空转的四种（注入点都选在「看起来只是少了一句」的地方）：

1. **范围声明被删**：AiReadScope.rule(...) 那一行拿掉，提示词里就再没有一句
   「范围外的一律不要尝试」—— 不报错，模型只是又回去猜、去试（用户这次点的就是这个洞）；
2. **文案被改软**：判据钉的是**逐字**那句。「一律不要尝试」改成「尽量别读」等于没拦，
   而改动看起来只是「润色了一句文案」；
3. **目录被改宽 / 被删行**：目录是范围的**唯一权威**。给它加一个后端根本没给的角色，
   等于在提示词里承诺一件做不到的事（用户看到的是一串 403「查不到」）；整条删掉更安静 ——
   AI 会以为那个模块不存在；
4. **裁剪 / 执行门被短路**：AiReads.forRole 不再按角色过滤、或 AiReads.allows 那道门被摘掉
   —— 提示词、工具说明、执行前的门三处会**同时**变成「什么都能读」，一处都不报错。

## 判据变红的形状
每条注入都要求：_check_ai_role_read_scope.py **非零退出**，而且输出里出现
**本条指定的那个失败标签片段** —— 不是「随便红一下」就算过（红错了地方说明判据烂了）。

R4-BOUNDARY-JUSTIFICATION: 这份反向验证是 R4 新边界判据（_check_ai_role_read_scope.py）的
配套。理由三条：① 那条判据全是静态结构断言，本仓的规矩是**新增一条红线就配一条注入**；
② 它盯的那句话是**给模型的**（不是给人看的注释）—— 删掉不会让任何编译/测试失败，
只有注入实验能证明「删了就有人喊」；③ 注入表是 5 元组（说明 / 文件 / 原文 / 替换成 /
期望红关键词），静态审计 _tools/qa/_check_reverse_verify_anchors.py 会逐条复查锚点还在不在，
锚点腐烂不会再静默跳过。

用法：python _tools/qa/_reverse_verify_ai_role_read_scope.py
（注入 → 判据必须变红 → 逐字节还原，并**当场核对**还原结果）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
CHECKER = ROOT / "_tools/qa/_check_ai_role_read_scope.py"
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
CATALOG_KT = AI / "AiReadCatalog.kt"
SCOPE_KT = AI / "AiReadScope.kt"
PROMPT_KT = AI / "AiRolePrompt.kt"
READS_KT = AI / "AiReads.kt"
SERVICE_KT = AI / "AiReadService.kt"
GEN = ROOT / "_tools/ai/_gen_ai_read_catalog.py"
EXPENSE_API = ROOT / "backend/app/api/v1/expense_categories.py"

#: (说明, 目标文件, 原文, 替换成, 期望红关键词)
CASES: list[tuple[str, Path, str, str, str]] = [
    # -------------------------------------------------- ① 目录（范围的唯一权威）
    (
        "目录里给货主开了一条后端不给的表（挂账单位 → 提示词里凭空多一块）",
        CATALOG_KT,
        'ReadAction("arrears.list_units", "挂账单位列表", "/api/v1/arrears-units", "", setOf("dispatcher"), false, listOf(',
        'ReadAction("arrears.list_units", "挂账单位列表", "/api/v1/arrears-units", "", setOf("dispatcher", "shipper"), false, listOf(',
        "写宽",
    ),
    (
        "目录里把挂账单位这一行整条删掉（AI 会以为这个模块不存在 —— 静默少一块）",
        CATALOG_KT,
        '        ReadAction("arrears.list_units", "挂账单位列表", "/api/v1/arrears-units", "", setOf("dispatcher"), false, listOf(' + chr(10) + '        )),' + chr(10),
        '        // GOV-0024 反验：这一行被整条拿掉了' + chr(10),
        "有一条",
    ),
    # -------------------------------------------------- ② 提示词里那句（删 / 改软）
    (
        "提示词里那句范围声明被拿掉（模型又回去猜、去试 —— 用户点的就是这个洞）",
        PROMPT_KT,
        "            AiReadScope.rule(AiReadScope.modulesOf(reads), reads.size)?.let { appendLine(it) }",
        "            // GOV-0024 反验：范围声明被拿掉了",
        "唯一一行",
    ),
    (
        "文案被改软（判据钉的是逐字那句：「一律不要尝试」不许变成「尽量别读」）",
        SCOPE_KT,
        '        "你只能读上面这几块里的东西。范围外的一律不要尝试、也不要猜（后台会直接拦住，换一种问法也一样）。"',
        '        "你只能读上面这几块里的东西。范围外的尽量别读。"',
        "逐字一致",
    ),
    # -------------------------------------------------- ③ 裁剪 / 执行门被短路
    (
        "AiReads.forRole 不再按角色裁（三处同时变成「什么都能读」，一处都不报错）",
        READS_KT,
        "        return allActions().filter {" + chr(10) + "            k in it.roles &&",
        "        return allActions().filter {" + chr(10) + "            true &&",
        "按角色裁",
    ),
    (
        "执行前的门被短路（工具说明里看不到 ≠ 调不到：这一句就是那道门）",
        SERVICE_KT,
        "        if (!AiReads.allows(role, action.action, enabledModules())) {",
        "        if (false) {",
        "AiReads.allows",
    ),
    # -------------------------------------------------- ④ 后端那道门 / 角色推导
    (
        "后端把「仅派单员」那道门摘掉（端点退回仅登录 ⇒ 推出来的角色跟着变宽）",
        EXPENSE_API,
        "def list_categories(current: DispatcherUser, db: Session = Depends(get_db)) -> list[ExpenseCategoryOut]:",
        "def list_categories(current: CurrentUser, db: Session = Depends(get_db)) -> list[ExpenseCategoryOut]:",
        "只给派单员",
    ),
    (
        "生成器不再看入口级授权标签（= 目录被重生成成「谁都能读」的老样子）",
        GEN,
        "    roles = set(BACKEND_ROLES if allow is None else allow)",
        "    roles = set(BACKEND_ROLES)  # GOV-0024 反验：入口级授权标签被忽略（旧行为）",
        "只给派单员",
    ),
]


def run(path: Path) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def fail_lines(out: str, limit: int = 3) -> str:
    """判据输出里那几行失败标签（红的时候要能说清红的是哪一条）。"""
    hit = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("- ")]
    return " ／ ".join(hit[:limit])


def main() -> int:
    fails: list[str] = []
    code, out = run(CHECKER)
    if code != 0:
        print("❌ 前提不成立：源码完好时判据就没过 —— 先把 _check_ai_role_read_scope.py 跑绿")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时判据是绿的")
    for label, path, old, new, want in CASES:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8")
        # 本仓的 Kotlin 有 LF 也有 CRLF：锚点按**这份文件自己**的换行写法折一遍，
        # 否则另一种就是「静默不命中」（表现是「注入没生效」，最容易被当成「本来就绿」）。
        eol = chr(13) + chr(10) if (chr(13) + chr(10)) in original else chr(10)
        old_real = old.replace(chr(10), eol)
        new_real = new.replace(chr(10), eol)
        if old_real not in original:
            print("❌ 锚点过期：" + label)
            fails.append(label + "：注入锚点对不上源码（替换串过期了，请更新本脚本）")
            continue
        mutated = original.replace(old_real, new_real, 1)
        if mutated == original:
            fails.append(label + "：注入没生效（替换串与原文一样）")
            continue
        try:
            path.write_bytes(mutated.encode("utf-8"))
            code2, out2 = run(CHECKER)
        finally:
            path.write_bytes(original_bytes)
        # 还原**当场核对**（不是「看起来还原了」）—— 对不上就记账，别让坏代码留在树里
        if path.read_bytes() != original_bytes:
            fails.append("还原后与快照不一致（注入污染了源码树）：" + str(path))
        if code2 != 0 and want in out2:
            print("✅ 注入「" + label + "」→ 判据报红（命中「" + want + "」：" + fail_lines(out2) + "）")
        elif code2 == 0:
            fails.append(label + "：注入之后判据**全绿** —— 这条断言是空转的")
        else:
            fails.append(label + "：判据红了，但红的不是这一条（输出里找不到「" + want + "」）")
    print()
    if fails:
        print("❌ 反向验证不通过（" + str(len(fails)) + "/" + str(len(CASES)) + "）：")
        for f in fails:
            print("   - " + f)
        return 1
    print("✅ " + str(len(CASES)) + " 条注入全部证明会红（判据不是空转的），源码已按字节还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
