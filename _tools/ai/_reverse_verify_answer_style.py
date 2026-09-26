"""反向验证「只给用户要的」那几条判据**真的会红**。

### 用户原话（2026-09-16，一次说了三个方面）
> 「AI 回答的时候没必要说的就不要说——不要说返回了什么什么，用户只要知道结果。」
> 「货主如果涉及到权限不够的话，不用说那么多，直接返回权限不够。」
> 「异常订单那个卡片还会显示一些没必要的数据——代码返回什么就照样渲染上去了。」
> 「大量商品或人员尽量用表格展示，不然全是文字的话，用户根本没办法看了。」

三组判据，每组都要能被破坏、破坏了必须报红：

1. **输出规则**（只讲结果 / 权限一句 / 多条用表格）—— 规则被删、或提示词不再拼它 → 红。
2. **话术**（读服务角色门 / 403 映射）—— 换回长篇解释 → 红。
3. **异常卡片**（状态中文化、缺谁不显示谁）—— 换回照抄后端字段 → 红。

用法：python _tools/ai/_reverse_verify_answer_style.py    # 全部报红 → 退出码 0
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
UI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher"
CHECK = HERE / "_check_ai_guardrails.py"
GRADLE = ROOT / "_agent/gradle/gradle-8.9/bin/gradle.bat"

STYLE = SRC / "AiAnswerStyle.kt"
LOOP = SRC / "AiAgentLoop.kt"
READSVC = SRC / "AiReadService.kt"
TOOLS = SRC / "AiTools.kt"
CARD = UI / "ReportCenter.kt"
PRIORITY = UI / "ReportPriority.kt"
BACKEND_PRODUCTS = ROOT / "backend/app/api/v1/products.py"
UNIT = "__UNIT__"

# (说明, 期望变红的检查名关键词 / UNIT=靠单测, 破坏方式, 改哪个文件)
MUTATIONS: list[tuple[str, str | None, object, Path]] = [
    (
        "「只讲结果」那条规则被删（它又开始汇报「返回了 N 条」）",
        "只讲结果",
        lambda s: s.replace('        appendLine("8.1 **只讲结果，不讲过程**（用户明确要求过）：")\n', "", 1),
        STYLE,
    ),
    (
        "提示词不再拼这条规则（规则还在，但没人用）",
        "提示词拼的是这一份",
        lambda s: s.replace("            append(AiAnswerStyle.RULES)\n", "", 1),
        LOOP,
    ),
    (
        "「权限不够只说一句」被删（又开始解释一大通）",
        "规则：权限不够只说一句",
        lambda s: s.replace('        appendLine("   - 权限不够时**只回一句**', '        appendLine("   - （略）', 1),
        STYLE,
    ),
    (
        "「条目多用表格」被删（又变成一大段文字）",
        "超过 3 项",
        lambda s: s.replace("**超过 3 项**）时**优先用表格", "）时**优先用表格", 1),
        STYLE,
    ),
    (
        "读服务的角色门换回长篇解释",
        "读服务的角色门措辞短",
        lambda s: s.replace(
            'return err("权限不够。告诉用户这个查不了，让他自己去 App 里对应的页面做；换个写法也一样不行。")',
            'return err("「${action.cn}」这个角色不能查（当前角色：${role?.key ?: "未知"}）。'
            '请如实告诉用户他这一步要去 App 里做，不要换个写法再试。")',
            1,
        ),
        READSVC,
    ),
    (
        "403 映射换回旧文案（模型会绕着它解释半天）",
        "403 映射措辞短",
        lambda s: s.replace(
            '403 -> "权限不够。一句话告诉用户这项他看不了；不要解释机制、不要复述这句话、不要给替代方案。"',
            '403 -> "当前登录账号没有权限查看这项数据。"',
            1,
        ),
        TOOLS,
    ),
    (
        "异常卡片又直接把后端状态码印上去",
        UNIT,
        lambda s: s.replace("                val st = AiOrderRef.statusLabel(e.status)", "                val st = e.status", 1),
        CARD,
    ),
    (
        "「谁的异常」又用空壳占位（缺司机也印「司机：」）",
        UNIT,
        lambda s: s.replace(
            "                val who = listOfNotNull(",
            "                val who = listOf((e.driverName ?: \"\") + \" \" + (e.shipperName ?: \"\")) //",
            1,
        ),
        CARD,
    ),
    (
        "提示词结尾那段又钉没了（模型对结尾最敏感，一删就又开始解释一大段）",
        "提示词结尾再钉一次那两条",
        lambda s: s.replace('            appendLine("【最后再确认两件事】")\n', "", 1),
        LOOP,
    ),
    # ---- 审计内容（第二遍真机才抓全：第一版只认两种 JSON 形状，其余原样摆出去）----
    (
        "审计内容又退回「兜底原样返回 JSON」（user_id 又露在屏幕上）",
        UNIT,
        lambda s: s.replace(
            "        ?: return stripApiSpeak(c) // 不是 JSON：本来就是人话（只清掉 API 说法）",
            "        ?: return c",
            1,
        ),
        PRIORITY,
    ),
    (
        "说明里的接口路径不再清理（用户又看到 POST /users/{id}/restore）",
        UNIT,
        lambda s: s.replace(
            'Regex("（可\\\\s*(?:GET|POST|PATCH|DELETE|PUT)\\\\s+[^）]*?恢复）").replace(s, "（可恢复）")',
            "s",
            1,
        ),
        PRIORITY,
    ),
    # ---- 审计卡片标题（第二遍真机：四行动作名是英文原始码）----
    (
        "后端加了个新动作、App 侧没跟中文名（卡片上又会出现英文原始码）",
        "审计里每个动作名都有中文",
        lambda s: s.replace(
            "        action=OperationAction.PRODUCT_UPDATE,",
            '        action="SOMETHING_NEW_ACTION",',
            1,
        ),
        BACKEND_PRODUCTS,
    ),
    (
        "审计卡片不再写「谁 · 什么时候」（只剩时间）",
        "审计卡片刻「谁 · 什么时候」",
        lambda s: s.replace(
            "                    auditWhoWhen(log.operatorName, log.createdAt),",
            "                    log.createdAt,",
            1,
        ),
        CARD,
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
    # 还原**当场核对**（R3-07b）：写回后**重新读回来逐字节比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是（L2 要的就是这一句）。
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
                detail = f"单测报错 {len(fails)} 条"
            else:
                code, out = run_check()
                hit = code != 0 and any("[FAIL]" in ln and expect in ln for ln in out.splitlines())
                fails = [ln.strip() for ln in out.splitlines() if "[FAIL]" in ln]
                detail = f"实际红 {len(fails)} 条" + (f"（{fails[0][:60]}）" if fails else "")
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
    print(f"\n✅ {total}/{total} 都红了：这一节的判据真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
