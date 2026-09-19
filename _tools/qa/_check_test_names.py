"""找一个 Windows 上会炸掉 Kotlin 编译的**测试函数名**。

Kotlin 的反引号函数名会原样变成 class 文件名，而 Windows 文件名不许出现 `" < > : | ? * / \\`。
本项目已经踩过两次：`fun 反引号…"现在归谁"…反引号()` → `InvalidPathException: Illegal char <">`，
报错信息里只有一串谜语（class 名被 GBK 打印成乱码），完全看不出"是函数名里的引号"。

⚠️ 触发条件是**函数体里有 lambda**（`= runBlocking { … }` 就是）：那时 Kotlin 会为它生成
`<类名>$<函数名>$1.class`，函数名于是变成文件名。没有 lambda 的用例名带引号不会炸——
**但那是定时炸弹**：哪天有人把它改成 `runBlocking { }`，编译就以一句乱码报错失败。
所以判据不看"有没有 lambda"，一律要求名字能当文件名用。

用法：python _tools/qa/_check_test_names.py    # 有非法字符就非零退出
"""
import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
BAD = set('"<>:|?*/\\')
# 反引号包住的名字里，冒号（含全角）是**允许**的——它在 Windows 文件名里不合法吗？
# `：`（全角）合法，`:`（半角）不合法。本项目的中文用例名一律用全角冒号，所以只查半角。
NAME_RE = re.compile(r"\bfun\s+`([^`]*)`")


def main() -> int:
    files = sorted((ROOT / "android/app/src/test").rglob("*.kt"))
    bad: list[str] = []
    n = 0
    for p in files:
        for i, line in enumerate(io.open(p, encoding="utf-8"), 1):
            for m in NAME_RE.finditer(line):
                n += 1
                name = m.group(1)
                hit = sorted({c for c in name if c in BAD})
                if hit:
                    bad.append(f"{p.relative_to(ROOT)}:{i} 名字里有 {hit} → {name}")
    print(f"扫了 {len(files)} 个测试文件、{n} 个反引号函数名")
    if bad:
        print("❌ 这些名字会让 Kotlin 编译报 IllegalPathException（class 文件名不合法）：")
        for b in bad:
            print("   - " + b)
        return 1
    if n < 100:
        print(f"❌ 只扫到 {n} 个反引号名字——正则或目录过期了，这条检查在空转")
        return 1
    print("✅ 测试函数名都能当文件名用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
