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
6. ⭐ `_prod_smoke.py`（生产**只读**烟测，R3-05）同受第 1、2 条约束，而且**用户点名的八项**
   （版本 / 依赖 / migration / DB / Redis / nginx / uploads / trace）必须**各自都有真探针** ——
   只在一张清单里写八个名字不算覆盖。
7. 判据条数下限（防检查空转）。

R3-BOUNDARY-JUSTIFICATION: 这不是「又多一个检查器」——`_tools/ops/` 这套脚本的存在意义就是
「**在没有人看着的时候**替人盯着生产」，而它们自己的失效同样是静默的：事实脚本里混进一句写操作，
一个只读监控就开始改生产库；只读烟测里混进一句 `systemctl restart`，一次「只读核对」就重启了线上。
2026-09-26 用户拍板「③ 生产只读放行」之后新增了 `_prod_smoke.py` —— 它是要在生产上跑的东西，
所以它必须和 `_prodssh` 的事实脚本受**同一套**只读约束；这两条判据是本文件原有的第 1、2 条
扩展到新脚本上，不是另立一套标准。

用法：
    python _tools/ops/_check_ops.py --check   # 非零退出＝有问题
    python _tools/ops/_check_ops.py           # 打印逐条明细
"""

from __future__ import annotations

import ast
import io
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PROD = HERE / "_prodssh.py"
HEALTH = HERE / "_health_check.py"
MIN_RULES = 18

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

    # ---- 2b. 只读烟测脚本（R3-05）：同样只读、同样不自己写主机、八项各有真探针 ----
    smoke_path = HERE / "_prod_smoke.py"
    want(smoke_path.exists(), "只读烟测脚本在位（R3-05 的 --readonly）",
         "⛔ 找不到 _prod_smoke.py —— R3-05 的「只读烟测」没有落到脚本上")
    smoke = read(smoke_path) if smoke_path.exists() else ""
    sm = re.search(r'_SMOKE_TEMPLATE = r"""(.*?)"""', smoke, re.S)
    smoke_text = sm.group(1) if sm else ""
    want(bool(smoke_text), "解析出烟测脚本本体（判据自身有效）",
         "⛔ 解析不出 `_SMOKE_TEMPLATE` —— 下面那条只读判据正在空转")
    bad2 = [w.strip() for w in WRITES if w in smoke_text.upper()]
    want(not bad2, "烟测脚本里没有任何写操作（" + str(len(WRITES)) + " 种写法都查过）",
         "⛔ 烟测脚本里出现了写操作：" + str(bad2) + " —— 一次「只读核对」把生产改了，是最没人会想到的事故")
    want(bool(ip) and ip not in smoke and "_prodssh" in smoke,
         "烟测脚本没有重复写生产主机（一律 import _prodssh）",
         "⛔ _prod_smoke.py 里又写了一遍生产主机，或没有 import _prodssh")
    # ⭐ 八项「各自都有真探针」：名字写进清单不算覆盖，脚本里必须找得到对应的采集点/判据点。
    #    这张表与脚本里的 `SMOKE_COVERS` 是**两份独立的声明**，所以要互相对账 ——
    #    任何一边悄悄改名/删项，另一边立刻报红（防「覆盖面变成一句口号」）。
    markers = {
        "version": ("repo_commit", "venv_python"),
        "deps": ("pip freeze", "pkg_"),
        "migration": ("app.migrations", "schema_versions"),
        "db": ("db_reachable", "db_tables"),
        "redis": ("redis_ping",),
        "nginx": ("nginx_proxy_pass", "nginx_upstream"),
        "uploads": ("uploads_readable", "uploads_files"),
        "trace": ("X-Request-ID", "id_coverage"),
    }
    cov = re.search(r"SMOKE_COVERS = \(([^)]*)\)", smoke)
    named = tuple(re.findall(r'"([a-z]+)"', cov.group(1))) if cov else ()
    want(bool(named) and set(named) == set(markers),
         "用户点名的八项与判据的表对得上（" + str(len(markers)) + " 项）",
         "⛔ SMOKE_COVERS 与判据里的表对不上：脚本声明 " + str(named) + " / 判据要求 " + str(tuple(markers)))
    thin2 = [k for k, ms in markers.items() if not all(m in smoke for m in ms)]
    want(not thin2, "这八项各自都有真的探针，不是只在清单里写个名字",
         "⛔ 这些项在烟测脚本里找不到对应探针：" + str(thin2) + " —— 清单说有覆盖，脚本里没有")
    want(not any(h in smoke for h in ("systemctl restart", "nginx -s reload", "pip install")),
         "烟测脚本不做安装 / 重启 / 重载",
         "⛔ 烟测脚本里有安装/重启/重载 —— 那已经不是「只读核对」了")

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

    # ---- 7. 「已知/已接受」例外表：必须写理由、写退出条件、真的被用到，而且会查出化石 ----
    #    为什么要单独钉：这张表的**唯一风险**是变成「把红的说成可以不管」的垃圾桶。
    #    所以给它四条硬约束（每一条都对应一种真实退化）：
    #      ① 理由必须够长（一句话打发 = 没写理由）；② 必须写清**什么时候删掉它**（含「删」字）；
    #      ③ 必须在判据里**真的被用**（定义了没人用 = 摆设，那条红线照样会红）；
    #      ④ 跑完必须能报出**没命中的条目**（证书处理掉了还留着 = 化石）。
    #    另一条更根本的约束写在代码里：命中时降级成 **warn**，不是 ok。
    accepted: dict[str, str] = {}
    try:
        for node in ast.parse(health).body:
            if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                    and node.target.id == "ACCEPTED_CERT"):
                accepted = dict(ast.literal_eval(node.value))
    except (SyntaxError, ValueError):
        accepted = {}
    # ⚠️ 判据必须是 **bool(accepted)** 而不是 isinstance：写成语法错的表时 ast.parse 会抛，
    #    我原来把它兜成 {} 再判 isinstance({}, dict) → **永远成立**，于是下面四条约束一起空转
    #    （2026-09-25 写反向验证第 ⑤ 条时当场发现的）。
    want(bool(accepted),
         "例外表能解析出来（" + str(len(accepted)) + " 条）—— 判据自身有效",
         "⛔ 解析不出 ACCEPTED_CERT（表被写坏/是空的）—— 下面四条约束会一起空转")
    short = sorted(k for k, v in accepted.items() if len(str(v)) < 60)
    want(not short, "例外表每条的理由都写得下（≥60 字）",
         "⛔ 这些条目的理由太短（一句话打发等于没写理由）：" + str(short))
    no_exit = sorted(k for k, v in accepted.items() if "删" not in str(v))
    want(not no_exit, "例外表每条都写明了**什么时候删掉它**",
         "⛔ 这些条目没写退出条件（含「删」字）—— 没有退出条件的例外 = 永久豁免：" + str(no_exit))
    want("name in ACCEPTED_CERT" in health and "accepted_hit.add(name)" in health,
         "例外表真的被判据用到（不是定义了摆着）",
         "⛔ 例外表定义了却没在证书循环里用（那条红线照样会红）")
    want('rows.append(("warn", f"证书 {name}（已知/已接受）"' in health,
         "命中例外时降级成**告警**（不是 ok）",
         "⛔ 例外命中时没有降级成 warn —— 那就是「把红的说成可以不管」")
    want("set(ACCEPTED_CERT) - accepted_hit" in health,
         "跑完会报出**没命中的条目**（防化石）",
         "⛔ 没有化石探测：证书处理掉了、例外条目还留着，谁也不会发现")

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
