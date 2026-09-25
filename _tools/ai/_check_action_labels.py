"""审计页的「动作名 → 中文」**是不是漏了**（清单自己算：从后端源码扫）。

### 为什么要有这个脚本
审计卡片最上面那行字是**动作名**。表里漏一个，那一行的标题就直接显示原始码——
真机上出现过 `USER_RESTORE`、`USER_DELETE`、`PRODUCT_DELETE`、`PRODUCT_RESTORE`
四行英文（用户的反馈是「用户根本就看不懂」）。

漏的原因很典型：**写后端的人加了新动作，写前端的人不知道**。
所以判据不能手写清单，得**从后端源码里扫出所有动作名**，再逐个要求 App 侧有中文。

用法：
    python _tools/ai/_check_action_labels.py           # 打对照表
    python _tools/ai/_check_action_labels.py --check    # 漏了就非零退出
"""
import argparse
import re
import sys
from pathlib import Path

# ⚠️ stdout **和 stderr** 都要：`raise SystemExit("中文")` 走的是 stderr，
#    而 stderr 默认按系统编码（Windows 上是 GBK）写 —— 不重配的话错误提示在开发机上是乱码，
#    反向验证也就匹配不上那句话（2026-09-25 实测踩到）。
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
BACKEND = ROOT / "backend/app"
REPORT_CENTER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"

# 后端写日志的两种写法：`OperationAction.X` 或 `action="X"`（自定义字符串）
ACTION_IN_CODE = re.compile(r"OperationAction\.([A-Z][A-Z0-9_]{3,})|action\s*=\s*\"([A-Z][A-Z0-9_]{3,})\"")
# Kotlin 那张表：`"ORDER_CREATE" -> "新建订单"`
LABEL_IN_KOTLIN = re.compile(r"\"([A-Z][A-Z0-9_]{3,})\"\s*->\s*\"([^\"]+)\"")


def backend_actions() -> set[str]:
    out: set[str] = set()
    for p in BACKEND.rglob("*.py"):
        s = p.read_text(encoding="utf-8")
        for m in ACTION_IN_CODE.finditer(s):
            out.add(m.group(1) or m.group(2))
    return out


def _strip_kotlin_comments(block: str) -> str:
    """把 Kotlin 注释去掉（**字符串里的 `//` 保留**）。

    为什么要它：把一条中文**注释掉**（`// "ORDER_CREATE" -> "新建订单"`）时，原来那条正则
    **照样命中** —— 判据是绿的，而审计卡片上那一行又变回原始码（用户报过的那个缺陷）。
    2026-09-25 反向验证第 ③ 条实测：注释掉一条，红线仍然全绿。
    """
    out: list[str] = []
    for line in block.splitlines():
        buf: list[str] = []
        in_str = False
        i = 0
        while i < len(line):
            c = line[i]
            if in_str:
                buf.append(c)
                if c == chr(92) and i + 1 < len(line):
                    buf.append(line[i + 1])
                    i += 2
                    continue
                if c == '"':
                    in_str = False
                i += 1
                continue
            if c == '"':
                in_str = True
                buf.append(c)
                i += 1
                continue
            if line.startswith("//", i) or line.startswith("/*", i):
                break          # 注释：这一行剩下的都不要（本表里没有行内块注释）
            buf.append(c)
            i += 1
        out.append("".join(buf))
    return chr(10).join(out)


def kotlin_labels() -> dict[str, str]:
    s = REPORT_CENTER.read_text(encoding="utf-8")
    # 只看 actionLabel 那个 when 块，避免把别处的常量对映射也扫进来
    i = s.find("private fun actionLabel(")
    if i < 0:
        raise SystemExit("❌ 找不到 actionLabel（被改名或搬走了？）")
    j = s.find("\n}", i)
    # ⛔ 先剥注释再匹配：注释掉一条中文**不算**「有中文」（见 _strip_kotlin_comments）
    return {m.group(1): m.group(2) for m in LABEL_IN_KOTLIN.finditer(_strip_kotlin_comments(s[i:j]))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    backend = backend_actions()
    labels = kotlin_labels()
    missing = sorted(a for a in backend if a not in labels)
    stale = sorted(a for a in labels if a not in backend)  # 后端已经没有这个动作了

    if not args.check:
        print(f"后端写日志的动作 {len(backend)} 个 / App 侧有中文的 {len(labels)} 个\n")
        for a in sorted(backend):
            print(f"  {'✅' if a in labels else '❌'} {a:22s} {labels.get(a, '（漏了：卡片上会显示原始码）')}")
        if stale:
            print("\n（App 侧有、但后端不再写的：%s —— 留着无害，但如果一直没人写就该删）" % "、".join(stale))

    if missing:
        print(f"\n❌ {len(missing)} 个动作没有中文名，审计卡片上会直接显示原始码：")
        for a in missing:
            print("   - " + a)
        print("\n（这些名字是**从后端源码扫出来**的：后端加了新动作，App 侧这张表就得跟上。）")
        return 1
    # 反空转：两边都空说明解析挂了
    if len(backend) < 10 or len(labels) < 10:
        print(f"❌ 只解析出 后端 {len(backend)} / App {len(labels)} 个动作——解析挂了？")
        return 1
    print(f"✅ 动作名都有中文：后端 {len(backend)} 个，全部能在 App 侧找到中文名")
    return 0


if __name__ == "__main__":
    sys.exit(main())
