"""反向验证「异常与审计的分级排序」那几条红线**真的会红**（注入 bug → 必须报错）。

### 这一节钉的是什么
用户原话：「上百条审计也翻不到，我们就应该主动去做一个分类——按危险层级或紧急层级排序」。
实现是 `ui/dispatcher/ReportPriority.kt` 里的纯函数（有单测），页面只负责**调用**它们。
所以最危险的破坏方式不是"函数写错了"（单测会拦住），而是**页面绕开函数自己 filter/sort**——
那样单测照样全绿，而用户看到的排序根本不是被测的那套。

用法：python _tools/ai/_reverse_verify_report_priority.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
SRC = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher"
CHECK = HERE / "_check_ai_guardrails.py"

REPORT = SRC / "ReportCenter.kt"
PRIORITY = SRC / "ReportPriority.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名里的关键词)
MUTATIONS = [
    (
        "页面绕开分级函数、自己 filter（单测管不到页面真正跑的那条路）",
        REPORT,
        "    val pending = pendingExceptions(vm.exceptions)",
        "    val pending = vm.exceptions.filter { it.exceptionResolvedAt == null }",
        "页面用的是分级函数",
    ),
    (
        "「已过去」不再单独分开（已送达的迟到单又混回待处理）",
        REPORT,
        "    val past = pastExceptions(vm.exceptions)",
        "    val past = emptyList<com.tapmoay.sorders.data.remote.dto.ExceptionOrderDto>()",
        "已过去的单单独分开",
    ),
    (
        "审计排序不走函数（页面自己排）",
        REPORT,
        "    val audits = sortedAudits(vm.operationLogs.take(60), auditFilter)",
        "    val audits = vm.operationLogs.take(60)",
        "审计排序走同一个函数",
    ),
    (
        "审计内容不再翻成人话（又把 JSON 摆给用户）",
        REPORT,
        "                    Text(auditChangeText(it), style = MaterialTheme.typography.bodyMedium",
        "                    Text(it, style = MaterialTheme.typography.bodyMedium",
        "审计内容翻成人话",
    ),
    (
        "危险层级不再区分「已经过去」（逾期送达被当成要处理的）",
        PRIORITY,
        '    if (r.contains("逾期送达") || r.contains("已撤销") || r.contains("已撤回")) return RiskLevel.PAST\n',
        "",
        None,  # 纯函数判据：靠单测
    ),
    (
        "删除不再优先于改钱（LEDGER_DELETE 被归到改钱）",
        PRIORITY,
        '    action.contains("DELETE") || action.contains("REMOVE") -> AuditKind.DELETE\n',
        "",
        None,
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_redline() -> tuple[int, str]:
    return run([sys.executable, str(CHECK)])


def run_tests() -> tuple[int, str]:
    """纯函数那两条注入靠单测抓——跑红线抓不到"函数写错了"（那本来就是单测的活）。"""
    gradle = ROOT / "_agent/gradle/gradle-8.9/bin/gradle.bat"
    r = subprocess.run(
        [str(gradle), "--project-dir", str(ROOT / "android"), ":app:testEmuDebugUnitTest", "--console=plain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    bad = 0
    code, out = run_redline()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            if expect is None:
                code, out = run_tests()
                hit = code != 0
                detail = "单测报错" if hit else "单测居然还是绿的"
            else:
                code, out = run_redline()
                hit = code != 0 and any(
                    "[FAIL]" in ln and expect in ln for ln in out.splitlines()
                )
                fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
                detail = f"实际红 {len(fails)} 条"
        finally:
            write_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_redline()
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
