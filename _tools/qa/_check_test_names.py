"""找一个 Windows 上会炸掉 Kotlin 编译的**测试函数名**。

Kotlin 的反引号函数名会原样变成 class 文件名，而 Windows 文件名不许出现 `" < > : | ? * / \\`。

⚠️ **点号（`.`）也非法**（2026-09-22 真编译踩到）：名字里写「用户第 1.1 条」那样带小数点的编号，
Kotlin 直接报 `Name contains illegal characters: ..`（只把它当文件名看是看不出来的 ——
`.` 在 Windows 文件名里合法，**是 JVM 的方法名规则**禁止它）。同一批还禁 `;`（JVM 规范
§4.2.1 的 unqualified name 不许有 `. ; [ /`），所以这里一起查。

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
#: JVM 的方法名规则（§4.2.1）另外禁这 4 个字符 —— 它们**在 Windows 文件名里合法**，
#: 所以只按"文件名"想会漏掉；`. ` 是实测炸过的那个（名字里写「1.1」这种编号）。
#: ⚠️ 全角冒号 `：` 合法（中文用例名一律用它），所以这里只放半角。
BAD_JVM = set(".;[]")
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
                hit = sorted({c for c in name if c in BAD or c in BAD_JVM})
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
