"""反向验证：把「测试账号默认模型服务」那一节（`_check_ai_guardrails.py` §33）逐条弄坏，看它**真的会红**。

### 为什么这一块必须反向验证
它守的是**一把真钥匙**：端点少一道门（没登录 / 没白名单），任何装了 App 的人都能把公司的
API key 拿走（而 APK 就挂在公网 `http://8.145.40.22/apk` 上）；客户端多加一行（比如"用户配过
也去用默认的"），用户的 key 就成了摆设、账单却走公司的。这两种都不是"报错"，是**静默**的。

用法：python _tools/ai/_reverse_verify_ai_default_key.py    # 全部报红 → 退出码 0
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
UIAI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/ai"
SYS = ROOT / "backend/app/api/v1/system.py"
CFG = ROOT / "backend/app/config.py"
ROUTER = ROOT / "backend/app/api/v1/router.py"
CONT = AI / "AiContainer.kt"
SCREEN = UIAI / "AiSettingsScreen.kt"
DTOS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "端点不再要求登录（任何人都能拿钥匙）",
        SYS,
        "def read_ai_default(current: CurrentUser) -> dict[str, str]:",
        "def read_ai_default(current: str = \"guest\") -> dict[str, str]:",
        "端点要求**登录**",
    ),
    (
        "白名单那道门被删掉（不再看手机号）",
        SYS,
        "if not prefix or not phone.startswith(prefix):",
        "if False:",
        "**白名单**前缀匹配",
    ),
    (
        "非白名单也放行（403 → 200）",
        SYS,
        "status_code=403",
        "status_code=200",
        "非白名单 → 403",
    ),
    (
        "服务端没配 key 时返回空串（客户端会以为配好了）",
        SYS,
        "status_code=404",
        "status_code=200",
        "服务端没配 key → **404**",
    ),
    (
        "把 key 写死进代码（公开仓库 + 公开 APK = 直接泄密）",
        SYS,
        'router = APIRouter(prefix="/system", tags=["system"])',
        # ⚠️ 这个假 key **不能写成完整字面量**：`_check_secrets.py` 会把 `sk-` + 32 位的形状
        #    当成真凭据报红（它扫描的是全仓被跟踪文件）—— 一条红线被另一条红线按假凭据拦住，
        #    两边都"对"，只有人一脸问号。拼出来就既不触发扫描、也照样能验证。
        'router = APIRouter(prefix="/system", tags=["system"])\n'
        'HARDCODED = "sk-" + "0123456789abcdef" + "0123456789abcdef"',
        "没有任何 key 字面量",
    ),
    (
        "新模块没挂路由（端点根本不存在 → 404）",
        ROUTER,
        # ⚠️ 这里刻意**不带结尾换行**：`router.py` 的最后一行没有换行符，
        #    带上 `\n` 就永远匹配不到（这一条第一次跑就是 SKIP，报的正是这个）。
        "api_router.include_router(system.router)",
        "# 路由故意不挂（反向验证）",
        "新模块挂上了路由",
    ),
    (
        "用户自己配过 key 也去用默认的（他的 key 白填、账单走公司）",
        CONT,
        "        if (keyStore.hasKey()) return false\n",
        "",
        "用户已配过 key → 直接返回",
    ),
    (
        "拿不到默认 key 时抛错（用户会看到一个跟他无关的失败）",
        CONT,
        "return false // 403/404/断网都走这里：没有默认可用，不是错误",
        'throw IllegalStateException("拿不到默认 key")',
        "拿不到就**静默**当没有",
    ),
    (
        "标记置在保存之前（saveApiKey 会把它清掉 → 界面永远说不是默认的）",
        CONT,
        "        if (!keyStore.saveApiKey(key)) return false",
        "        keyStore.markUsingDefaultKey(true)\n        if (!keyStore.saveApiKey(key)) return false",
        "先 `saveApiKey` 再",
    ),
    (
        "界面不再说明这把 key 是哪来的（用户以为是自己配的）",
        SCREEN,
        "正在使用「测试账号默认 Key」（服务端下发，不是你自己填的）。",
        "已保存一个 Key。",
        "界面如实说明这把 key 是哪来的",
    ),
    (
        "DTO 少了 @Serializable（请求**根本发不出去**，而调用点把它当「拿不到」吞掉 → 功能全对就是不生效）",
        DTOS,
        "@Serializable\ndata class AiDefaultDto(",
        "data class AiDefaultDto(",
        "每个 data class 都有 @Serializable",
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
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print(f"❌ 前提不成立：源码完好时红线没过\n{out[-1500:]}")
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print(f"✅ 前提：源码完好时红线是绿的 —— {last.strip()}")

        for label, path, old, new, expect in MUTATIONS:
            src, crlf = read_src(path)
            if src.count(old) != 1:
                print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
                bad += 1
                continue
            write_src(path, src.replace(old, new), crlf)
            try:
                code, out = run_check()
                fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
                hit = code != 0 and any(expect in ln for ln in fails)
                detail = f"实际红 {len(fails)} 条" + (
                    "" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}"
                )
            finally:
                write_src(path, src, crlf)
            print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
            if not hit:
                bad += 1

        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        bad += 0 if ok else 1
    finally:
        unlock_reverse_verify()

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
