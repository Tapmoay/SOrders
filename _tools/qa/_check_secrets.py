"""扫一遍**被跟踪的文件里有没有秘密**（本地也要扫：这条分支迟早要推上去）。

为什么要它：这个仓库里既有 `.env.example`（示例）也有 `android/local.properties.example`，
而后者的 `amap_key` 是**真 key**（客户端 key，跟包名绑定，但仍然是凭据）。
"某次改配置顺手把真值写进 example"是这类事故最常见的形态，肉眼 review 10 万行 diff 不现实。

⚠️ 文件名以 `_check_` 开头是**故意的**：`_tools/qa/_check_all.py` 的清单按这个前缀算，
于是它会自动进"每次都要跑"的那一组（叫别的名字，它就只是一份没人跑的脚本）。

用法：
    python _tools/qa/_check_secrets.py            # 扫全部被跟踪的文件
"""
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()

# 已知的真凭据（本机 local.properties 里的高德 key）。出现在**任何被跟踪的文件**里都要报。
KNOWN = ["06393ebf50284409b532ef517b5e63cf"]
# 通用形状：赋值语句右边像凭据，而左边是凭据字段名
PATTERNS = [
    (re.compile(r"(?i)\b(api[_-]?key|secret|access[_-]?token|private[_-]?key)\b\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{16,})"),
     "凭据字段被赋了长字符串"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "OpenAI 风格 key"),
    (re.compile(r"(?i)\bpassword\b\s*[:=]\s*[\"'][^\"']{6,}[\"']"), "明文密码字面量"),
]
# 这些路径天然带示例/测试值，命中不算
# ⚠️ 必须包含 `/test/`（单元测试里的 `apiKey = "sk-unit-test-key…"` 是假值）——
#    第一版只写了 `test_`，于是 5 个测试文件被当成"泄露"报出来，
#    而**假阳性会让下一个人学会无视这条检查**（比漏报更常见的死法）。
ALLOW_PATH = ("example", "/test/", "test_", ".md", "docs/", "_tools/", "conftest")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def main() -> int:
    # ⚠️ **不要**在这里读命令行位置参数：`_check_all.py` 会把"要位置参数的脚本"当成工具排掉
    #    （那种脚本不带参数跑只会打印一行用法），于是这条检查就进不了"每次都要跑"的那一组。
    #    （踩过一次：连**这句注释**里照抄那个表达式都会被它的正则命中——判据是扫源码文本的。）
    files = tracked_files()
    print(f"当前分支被跟踪的文件 {len(files)} 个")

    hits: list[str] = []
    for f in files:
        p = ROOT / f
        if not p.is_file():
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for k in KNOWN:
            if k in txt:
                hits.append(f"{f}: 命中已知凭据（高德 key）")
        for rx, why in PATTERNS:
            for m in rx.finditer(txt):
                if any(a in f for a in ALLOW_PATH):
                    continue
                hits.append(f"{f}: {why} —— {m.group(0)[:60]}")

    if hits:
        print(f"❌ {len(hits)} 处可疑：")
        for h in hits:
            print("   - " + h)
        return 1
    # 反空转：文件都读不到的话上面什么都不会报
    if len(files) < 200:
        print(f"❌ 只扫到 {len(files)} 个被跟踪文件——清单过期了，这条检查在空转")
        return 1
    print("✅ 被跟踪的文件里没有已知凭据、也没有凭据形状的赋值")
    return 0


if __name__ == "__main__":
    sys.exit(main())
