#!/usr/bin/env python3
"""_check_ops.py —— `_tools/ops/` 这套监控自己的判据（整改报告 §18 规则 5：自动化工具必须自己可验证）。

### 为什么监控脚本要自己的检查
健康检查平时**什么都不说**（全绿是静默的），所以它的失效方式也都是静默的：

- 事实脚本里混进一句写操作（`DELETE`/`UPDATE`）→ 一个"只读监控"开始改生产库，而没人会想到去看它；
- 阈值常量被改成字面量散在代码里 → 改口径要满文件找，改漏一处就是两套标准；
- 退出码不再区分 告警/失败 → cron 与 CI 拿到的信号失去意义；
- 事实脚本与基线用的不是同一份（各写各的）→ 出现"基线里好好的、监控说挂了"。

### 判据
1. `_prodssh.prod_facts_script()` **只读**：不许出现 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT/FLUSH；
2. 主机 / 密钥 / 路径**只出现在 `_prodssh.py` 一处**（其余脚本一律 import）；
3. 阈值是常量、且真的被用到（改口径只改一处）；
4. 退出码分三档（0 全绿 / 1 告警 / 2 失败）且真的这么 return；
5. 报告 §15 ③ 点名的四项都在：`/health`、证书、磁盘、**数据库**（外加发件箱积压）；
6. 判据条数下限（防检查空转）。

用法：
    python _tools/ops/_check_ops.py --check   # 非零退出＝有问题
    python _tools/ops/_check_ops.py           # 打印逐条明细
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROD = HERE / "_prodssh.py"
HEALTH = HERE / "_health_check.py"
MIN_RULES = 12

#: 监控脚本里**绝不允许**出现的写操作（一个"只读监控"改生产库，是最没人会想到的事故）。
WRITES = ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "TRUNCATE ", "GRANT ", "FLUSH ", "CREATE ")


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8", errors="replace").read()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    check_mode = "--check" in sys.argv[1:]
    passed: list[str] = []
    failures: list[str] = []

    def want(ok: bool, good: str, bad: str) -> bool:
        (passed if ok else failures).append(("OK  " if ok else "BAD ") + (good if ok else bad))
        return ok

    want(PROD.exists() and HEALTH.exists(), "两个脚本都在", "⛔ 找不到 _prodssh.py / _health_check.py")
    if failures:
        for f in failures:
            print("  " + f)
        return 1

    prod = read(PROD)
    health = read(HEALTH)

    # ---- 1. 事实脚本只读 ----
    # 只扫**事实脚本本体**（模块里别的读函数不参与）。
    # ⚠️ 第一版按 `_SCRIPT = ` 找，而真名是 `_FACTS_TEMPLATE = r"""…"""` —— 于是它扫的是
    #    模块里随便一段 docstring，注入一个 `delete from` 都不会红（判据空转，实测抓到）。
    facts_match = re.search(r'_FACTS_TEMPLATE = r"""(.*?)"""', prod, re.S)
    script_text = facts_match.group(1) if facts_match else ""
    want(bool(script_text), "解析出事实脚本本体（判据自身有效）",
         "⛔ 解析不出 `_FACTS_TEMPLATE` —— 这条只读判据正在空转")
    bad = [w.strip() for w in WRITES if w in script_text.upper()]
    want(not bad, "事实脚本里没有任何写操作（" + str(len(WRITES)) + " 种写法都查过）",
         "⛔ 事实脚本里出现了写操作：" + str(bad) + " —— 一个只读监控改生产库是最没人会想到的事故")

    # ---- 2. 生产事实只在一处 ----
    # ⚠️ 名字是 `PROD_HOST`（不是 `HOST`）—— 第一版写死了 `^HOST=`，于是判据自报"找不到"（假红）。
    host = re.search(r'^PROD_HOST\s*=.*?"([\d.]+)"', prod, re.M)
    ip = host.group(1) if host else ""
    want(bool(ip), "主机写在 _prodssh.py 里（" + (ip or "?") + "）", "⛔ _prodssh.py 里找不到 PROD_HOST")
    others = [p.name for p in sorted(HERE.glob("*.py")) if p.name != "_prodssh.py" and ip and ip in read(p)]
    want(not others, "别的脚本没有重复写生产主机（一律 import _prodssh）",
         "⛔ 这些脚本里又写了一遍生产主机：" + str(others))

    # ---- 3. 阈值是常量且被用到 ----
    # ⚠️ 阈值有两种写法：单名 `X = 1` 与逗号并列 `A, B = 30, 7` —— 第一版只认前者，
    #    于是"常量少于 4 个"这条判据自己假红（实际有 6 个）。两种都要认。
    consts: list[str] = []
    for m in re.finditer(r"^([A-Z][A-Z0-9_, ]*?)\s*=\s*\d[\d,\s]*$", health, re.M):
        consts += [n.strip() for n in m.group(1).split(",") if n.strip()]
    used = [c for c in consts if len(re.findall(r"\b" + c + r"\b", health)) >= 2]
    want(len(consts) >= 4 and len(used) == len(consts),
         "阈值常量 " + str(len(consts)) + " 个，全部真的被用到",
         "⛔ 有阈值常量定义了却没用到：" + str(sorted(set(consts) - set(used))))
    want("OUTBOX_PENDING_WARN" in consts, "发件箱积压阈值是一个常量（口径一处）",
         "⛔ 找不到 OUTBOX_PENDING_WARN —— 发件箱积压的判据没接上")

    # ---- 4. 退出码三档 ----
    want(re.search(r"return 2 if fails else \(1 if warns else 0\)", health) is not None,
         "退出码三档：0 全绿 / 1 告警 / 2 失败",
         "⛔ 退出码不再分档 —— cron 与 CI 拿到的信号会失去意义")

    # ---- 5. 报告点名的四项都在 ----
    for key, label in (
        ("api_health", "服务 /health"),
        ("cert_", "证书剩余天数"),
        ("disk_pct", "磁盘"),
        ("db_reachable", "数据库可达性"),
        ("outbox_pending", "发件箱积压"),
        ("backup_latest_epoch", "最近一次备份的年龄"),
    ):
        want(key in health or key in prod, "盯住了：" + label, "⛔ 没有盯 " + label + "（报告 §15 ③ 点名要监控的）")

    total = len(passed) + len(failures)
    want(total >= MIN_RULES, "判据条数 " + str(total) + " ≥ " + str(MIN_RULES),
         "只跑了 " + str(total) + " 条判据（< " + str(MIN_RULES) + "）—— 检查可能空转了")

    print("运维监控判据：" + str(len(passed)) + " 通过 / " + str(len(failures)) + " 失败")
    if not check_mode:
        for n in passed:
            print("  ✅ " + n[4:])
    for f in failures:
        print("  " + f)
    if failures:
        return 1
    print("  ✅ 全部通过（只读、阈值一处、退出码分档、该盯的都盯着）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
