#!/usr/bin/env python3
"""_prod_smoke.py —— 生产**只读**烟测（R3-05 的「只读烟测」这一步）。

### 为什么要有它（而不是「上去手工敲几条」）
用户 2026-09-26 拍的板是「③ 生产 → 先只读 → 只验证，不做业务写入 →
优先核对：**版本 / 依赖 / migration / DB / Redis / nginx / uploads / trace**」。
手工敲三条命令有三个问题：① 下次没人知道上次敲的是哪几条；②「我核过了」这句话**没有证据**；
③ 手工敲着敲着就会顺手敲一条写命令 —— 而那一刻没有任何东西拦得住。

所以这一步必须是**一段固定的、只读的脚本**：它自己声明只读（--readonly），
`_tools/ops/_check_ops.py` 逐条钉着它「一句写操作都不许有」，输出能进证据文档（--json）。

### 与另两个脚本的分工（⛔ 事实不许各写一份）
- `_prodssh.prod_facts_script()`：生产事实的**唯一出处**（主机 / 密钥 / 路径 / 采集口径只在 `_prodssh.py`）；
- `_health_check.py`：四个阈值 + 三档退出码，判的是「**要不要叫人起床**」（日常监控，天天跑）；
  本脚本**直接复用它的 `_facts()`**（含最近一次备份的年龄那一项），⛔ 不另抄一份采集命令；
- 本脚本：**发布前后的一次性只读核对**，判的是「这一轮的退出条件有没有**真凭据**」，
  所以它额外核 **依赖 / migration 版本 / nginx 形态 / request_id 贯穿 / 生产落后的提交数**。

### 依赖那一格为什么非要在生产上量
`docs/DEPENDENCY_DECISION.md` 的三处版本里，生产那一格一直是空的：本机是 48.0.0、声明写着
`cryptography>=42,<44` —— 拿**本机**去猜生产，只会把猜测变成结论。用户 2026-09-26 的决策①是
「**以生产真实 pip freeze 为准**」，所以这里逐条把「声明的包在**生产**上装的什么版本」量出来。
⛔ 本脚本**只记录、不判定对错**：该不该改声明是依赖治理那一轮的事（决策②：本轮不锁）。

### 退出码三档（⚠️ 与 `_health_check.py` 的语义**不同**，别混）
- **0** = 生产现状健康，**且**与这一版代码一致（＝发布已完成）；
- **1** = 生产现状健康，但与这一版代码**不一致**（发布之前就是这个样子）——
  这一档今天必然命中：生产停在 `648fbf8`（2026-09-23），落后本仓库一大截；
- **2** = 生产**现状本身**有问题（服务 / 库 / Redis / 磁盘 / 备份那种，跟发布没关系也要管）。

所以「1」不是失败，是**发布还没做**这件事的机器形态；发布之后本表应当全绿。

### ⛔ 它证不了什么
- 它不证明业务正确性（只读＝**永远不会写**，所以也没法证明「写路径在生产上是好的」）；
- 它不证明备份可用、不证明能回滚 —— 那要写操作（备份/迁移/启动/回滚），属**另一次许可**；
- 它不替代 `_trace_order.py`：这里只核「审计行里 request_id / command_id 真的落下来了」，
  人可读的单据全链路仍然用那个工具。

用法：
    python _tools/ops/_prod_smoke.py --readonly                # 唯一模式（只读）
    python _tools/ops/_prod_smoke.py --readonly --json out.json
    python _tools/ops/_prod_smoke.py --readonly --local        # 在生产机上跑（cron/排障）
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "qa"))
import _health_check  # noqa: E402
import _prodssh  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT_S = 180

#: 用户点名的八项 —— `_check_ops.py` 会逐项核对它们真的还在脚本里（防这一格悄悄消失）。
SMOKE_COVERS = ("version", "deps", "migration", "db", "redis", "nginx", "uploads", "trace")

#: 只读采集脚本。⛔ 用 raw 字符串 + replace（不是 f-string）：里面有大量 shell 的 $() ，
#:   f-string 会把它们当成 Python 表达式（`_prodssh._FACTS_TEMPLATE` 上踩过同一个坑）。
#: ⛔ 一句写操作都没有：不 INSERT/UPDATE/DELETE，不建文件，不 touch，不 restart，不改配置。
_SMOKE_TEMPLATE = r"""set +e
emit() { printf '%s=%s\n' "$1" "$2"; }
V="@BACKEND@/.venv/bin"

# ---- 版本 ----
emit venv_python "$($V/python -V 2>&1 | tr -d '\n')"
emit venv_present "$([ -x $V/python ] && echo yes || echo no)"
emit app_has_migrations "$(cd @BACKEND@ && $V/python -c 'import app.migrations; print("yes")' 2>&1 | tail -1 | head -c 120)"
emit has_request_id_module "$(cd @BACKEND@ && $V/python -c 'import app.core.request_id; print("yes")' 2>&1 | tail -1 | head -c 120)"
emit tracked_dirty "$(cd /opt/SOrders && git status --porcelain 2>/dev/null | grep -vc '^??')"
emit untracked_file "$(cd /opt/SOrders && git status --porcelain 2>/dev/null | grep -c '^??')"

# ---- 依赖（决策①：生产**真实**装的版本）----
emit pip_freeze_count "$(cd @BACKEND@ && $V/pip freeze 2>/dev/null | wc -l)"
emit pip_freeze_sha "$(cd @BACKEND@ && $V/pip freeze 2>/dev/null | sha256sum | cut -c1-16)"
@PKG_LINES@

# ---- migration / DB（先问 information_schema：生产是**旧结构**时，硬查会 empty 而不是报错）----
emit has_schema_versions "$(mysql -N -B -e "select count(*) from information_schema.tables where table_schema='@DB@' and table_name='schema_versions';" 2>/dev/null)"
emit has_outbox "$(mysql -N -B -e "select count(*) from information_schema.tables where table_schema='@DB@' and table_name='outbox_events';" 2>/dev/null)"
emit has_trace_cols "$(mysql -N -B -e "select count(*) from information_schema.columns where table_schema='@DB@' and table_name='operation_logs' and column_name in ('request_id','command_id');" 2>/dev/null)"
emit schema_versions "$(mysql -N -B -e "select group_concat(version order by version) from @DB@.schema_versions;" 2>/dev/null)"
emit db_last_order "$(mysql -N -B -e "select concat_ws('|', order_no, status, created_at) from @DB@.orders order by id desc limit 1;" 2>/dev/null)"
emit db_last_order_logs "$(mysql -N -B -e "select concat_ws('|', o.order_no, (select count(*) from @DB@.operation_logs l where l.order_id=o.id)) from @DB@.orders o order by o.id desc limit 1;" 2>/dev/null)"
emit id_coverage "$(mysql -N -B -e "select concat(count(*), '|', sum(request_id is not null and request_id<>''), '|', sum(command_id is not null and command_id<>'')) from @DB@.operation_logs;" 2>/dev/null)"
emit db_time_zone "$(mysql -N -B -e "select concat(@@global.time_zone, '|', @@session.time_zone);" 2>/dev/null)"

# ---- Redis ----
emit redis_ping "$(redis-cli -h 127.0.0.1 -p 6379 ping 2>&1 | tr -d '\r')"
emit redis_keyspace "$(redis-cli -h 127.0.0.1 -p 6379 info keyspace 2>/dev/null | grep '^db' | tr '\n' ';')"

# ---- nginx（形态，供 R3-03 那一格对账）----
emit nginx_T_lines "$(nginx -T 2>/dev/null | wc -l)"
emit nginx_proxy_pass "$(nginx -T 2>/dev/null | grep -E 'proxy_pass' | sed 's/^[[:space:]]*//' | sort -u | tr '\n' ';')"
emit nginx_upstream "$(nginx -T 2>/dev/null | grep -A5 -E '^[[:space:]]*upstream[[:space:]]' | tr -d '\r' | tr '\n' ';' | head -c 400)"
emit nginx_failover "$(nginx -T 2>/dev/null | grep -E 'max_fails|fail_timeout|proxy_next_upstream' | tr -d ' ' | tr '\n' ';')"
emit nginx_socketio "$(nginx -T 2>/dev/null | grep -A8 'socket.io' | tr -d '\r' | tr '\n' ';' | head -c 400)"

# ---- uploads（⛔ 不做写入探测：那会往生产上传目录里放垃圾文件）----
emit uploads_readable "$([ -r @UPLOADS@ ] && echo yes || echo no)"

# ---- trace：X-Request-ID 必须**原样**回来（客户端 → 应用 → 响应头）----
RID="r3smoke-$(date +%s)-$$"
emit trace_probe_id "$RID"
emit trace_app_status "$(curl -s -o /dev/null -w '%{http_code}' -H "X-Request-ID: $RID" http://127.0.0.1:8000/health)"
emit trace_app_header "$(curl -s -D- -o /dev/null -H "X-Request-ID: $RID" http://127.0.0.1:8000/health | tr -d '\r' | awk 'tolower($1)=="x-request-id:"{print $2}')"
emit trace_nginx_status "$(curl -s -o /dev/null -w '%{http_code}' -H "X-Request-ID: $RID" http://127.0.0.1/api/v1/orders)"
emit trace_nginx_header "$(curl -s -D- -o /dev/null -H "X-Request-ID: $RID" http://127.0.0.1/api/v1/orders | tr -d '\r' | awk 'tolower($1)=="x-request-id:"{print $2}')"
"""


def repo_migration_head() -> int:
    """仓库里认的**迁移最新版本**：从迁移目录现数，⛔ 不手写（手写的那个数会在下一次迁移时过期）。

    ⚠️ 2026-09-26 修：第一版 glob 的是 `migrations/versions/0*.py` —— **那个目录不存在**（迁移就在
    `backend/app/migrations/` 下，见 `_runner.MIGRATIONS_DIR = Path(__file__).parent`），于是它**静默返回 0**，
    判据那一行就写成「生产库结构版本 = 仓库最新版本 0」—— 一条算不出真值却照样给结论的判据。
    ⛔ 现在：**数不出来就返回 0，调用处必须把 0 当成「数不出来」如实报**（不许当成版本 0）。
    """
    head = 0
    mdir = ROOT / "backend/app/migrations"
    for p in sorted(mdir.glob("0*.py")) if mdir.exists() else []:
        digits = "".join(ch for ch in p.stem.split("_")[0] if ch.isdigit())
        if digits:
            head = max(head, int(digits))
    return head


def newest_route_snapshot() -> tuple[str, int]:
    """仓库里最近一次路由快照（名字, 路径条数）—— ⛔ 只作对照，不是「当前代码」的权威。"""
    best: tuple[str, int] = ("", 0)
    files = sorted((ROOT / "_tools/qa/_api_snapshots").glob("*.json"))
    if not files:
        return best
    try:
        data = json.loads(files[-1].read_text(encoding="utf-8", errors="replace"))
        return files[-1].name, len(data.get("openapi", {}).get("paths", {}))
    except Exception:  # noqa: BLE001
        return files[-1].name, 0


def git(*args: str) -> tuple[int, str]:
    """本机只读 git（⛔ 只允许 rev-parse / merge-base / rev-list 这类不写不改的命令）。"""
    r = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, timeout=60)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip()


def prod_skew(commit: str) -> tuple[bool, str]:
    """生产那个提交在**本仓库历史**里吗？落后多少？（只读 git，不联网）"""
    if len(commit) != 40:
        return False, "生产提交读不出来"
    if git("merge-base", "--is-ancestor", commit, "HEAD")[0] != 0:
        return False, "生产提交**不在**本仓库历史里（生产上跑的不是这个仓库的提交？）"
    code, out = git("rev-list", "--count", commit + "..HEAD")
    if code != 0 or not out.isdigit():
        return False, "落后多少提交算不出来"
    n = int(out)
    return n == 0, ("与 HEAD 一致" if n == 0 else "落后 HEAD **" + str(n) + "** 个提交（发布还没做）")


def declared_packages() -> list[tuple[str, str, str]]:
    """(包名, 原始声明, 来源文件) —— 解析器**复用**依赖判据那一份（口径一处，⛔ 不在这儿再写一个）。"""
    from _check_dep_declaration import FILES, declared_lines  # noqa: PLC0415

    out: list[tuple[str, str, str]] = []
    try:
        from packaging.requirements import Requirement
    except ImportError:  # pragma: no cover
        return out
    for rel in FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        for line in declared_lines(path):
            try:
                out.append((Requirement(line).name, line, rel))
            except Exception:  # noqa: BLE001 —— 解析不了的由依赖判据去报，这里跳过
                continue
    return out


def pkg_lines(pkgs: list[tuple[str, str, str]]) -> str:
    """每个**声明的**包在生产 venv 里装的是哪一版（pip freeze 现读，⛔ 不猜）。"""
    out = []
    for name, _decl, _rel in pkgs:
        safe = name.replace(chr(39), "")
        out.append('emit pkg_' + safe + ' "$(cd @BACKEND@ && $V/pip freeze 2>/dev/null'
                   " | grep -i '^" + safe + "==' | head -1 | cut -d= -f3)\"")
    return "\n".join(out)


def build_script(pkgs: list[tuple[str, str, str]]) -> str:
    return (_SMOKE_TEMPLATE
            .replace("@PKG_LINES@", pkg_lines(pkgs))
            .replace("@BACKEND@", _prodssh.BACKEND_DIR)
            .replace("@UPLOADS@", _prodssh.UPLOADS_DIR)
            .replace("@DB@", _prodssh.DB_NAME)
            .replace("@SERVICE@", _prodssh.SERVICE))


def run_remote(script: str, local: bool) -> str:
    if local:
        r = subprocess.run(["bash", "-c", script], capture_output=True, timeout=TIMEOUT_S)
        return r.stdout.decode("utf-8", "replace")
    return _prodssh.ssh_script(script, timeout=TIMEOUT_S).stdout.decode("utf-8", "replace")


def parse_facts(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in text.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def version_in_range(decl: str, installed: str) -> bool | None:
    """声明区间收不收这个版本（读不出结论就返回 None —— ⛔ 不假装判过）。"""
    if not installed:
        return None
    try:
        from packaging.requirements import Requirement
        from packaging.version import Version
    except ImportError:  # pragma: no cover
        return None
    try:
        return Requirement(decl).specifier.contains(Version(installed), prereleases=True)
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--readonly", action="store_true",
                    help="只读模式（本脚本**只有**这一种模式，写在这里是为了让命令自己说得清）")
    ap.add_argument("--local", action="store_true", help="在生产机上直接跑（不 ssh）")
    ap.add_argument("--json", help="把原始事实写成 JSON（证据留档用；会额外把完整 pip freeze 一起存档）")
    a = ap.parse_args()

    pkgs = declared_packages()
    facts = parse_facts(run_remote(build_script(pkgs), a.local))
    facts.update(_health_check._facts(local=a.local))     # 采集口径只有一处（含备份年龄）

    rows: list[tuple[str, str, str, str]] = []            # (档, 名字, 细节, 类别)

    def chk(ok: bool, name: str, ok_detail: str, bad_detail: str = "",
            warn_only: bool = False, category: str = "health") -> None:
        level = "ok" if ok else ("warn" if warn_only else "fail")
        rows.append((level, name, ok_detail if ok else (bad_detail or ok_detail), category))

    f = facts.get
    head = repo_migration_head()
    snap_name, snap_paths = newest_route_snapshot()

    # ---- 1. 现状健康：服务 / 接口 / 磁盘 / 上传 / 备份（这些跟发布没关系，红了就要管）----
    chk(f("service_state") == "active", "服务 sorders-api 在跑",
        "systemctl is-active = active", "systemctl is-active = " + str(f("service_state")))
    chk(f("api_health") == "200", "GET /health = 200",
        "/health = 200（" + str(f("api_health_body"))[:40] + "）", "/health = " + str(f("api_health")))
    chk(f("db_reachable") == "1", "数据库可达", "select 1 = 1", "select 1 = " + str(f("db_reachable")))
    tables = f("db_tables") or "0"
    chk(tables.isdigit() and int(tables) >= 40, "表数量正常",
        tables + " 张表 / " + str(f("db_size_mb")) + " MB", "只数到 " + tables + " 张表")
    chk((f("redis_ping") or "").upper().startswith("PONG"), "Redis 在跑",
        "PING → PONG", "PING → " + str(f("redis_ping")))
    chk(f("uploads_readable") == "yes", "上传目录可读",
        str(f("uploads_files")) + " 个文件 / " + str(f("uploads_size")), "读不到 " + _prodssh.UPLOADS_DIR)
    pct = (f("disk_pct") or "0%").rstrip("%")
    used = int(pct) if pct.isdigit() else 0
    chk(used < 95, "磁盘没满", "已用 " + str(f("disk_pct")) + "（可用 " + str(f("disk_avail")) + "）",
        "已用 " + str(f("disk_pct")) + " —— 快满了")
    chk(used < 85, "磁盘宽裕（<85%）", "已用 " + str(f("disk_pct")), "已用 " + str(f("disk_pct")),
        warn_only=True)
    epoch = f("backup_latest_epoch") or ""
    if not epoch.replace(".", "", 1).isdigit():
        chk(False, "最近一次备份不太旧（≤36h）", "", "读不出备份年龄（" + _prodssh.BACKUP_ROOT + " 下没有 manifest？）",
            warn_only=True)
    else:
        import time  # noqa: PLC0415
        hours = (time.time() - float(epoch)) / 3600.0
        chk(hours <= 36, "最近一次备份不太旧（≤36h）",
            "最近备份 " + format(hours, ".1f") + " 小时前", "最近备份 " + format(hours, ".1f") + " 小时前",
            warn_only=True)
    chk((f("redis_requirepass_len") or "1").strip() not in ("1",), "Redis 设了口令",
        "requirepass 已设", "requirepass 为空（长度 " + str(f("redis_requirepass_len")) + "）—— 本机网络不可达所以不是洞，但仍是既知缺口",
        warn_only=True)
    tz = (f("db_time_zone") or "")
    chk("+00:00" in tz or "UTC" in tz.upper(), "MySQL 时区口径是 UTC",
        "time_zone = " + tz, "time_zone = " + tz + "（不是 UTC —— 代码里钉会话时区那一段还没上生产）",
        warn_only=True)

    # ---- 2. 与这一版代码的一致性（发布要做的事：今天必然有一批不成立）----
    commit = f("repo_commit") or ""
    chk(len(commit) == 40, "生产仓库提交可读", (commit[:12] or "") + " / 分支 " + str(f("repo_branch")),
        "读不出来（/opt/SOrders 不是 git 工作区？）", category="consistency")
    same, why = prod_skew(commit)
    chk(same, "生产代码 = 本仓库 HEAD", "与 HEAD 一致", "生产 " + (commit[:8] or "?") + "：" + why,
        category="consistency")
    chk(f("tracked_dirty") == "0", "生产**跟踪文件**没有被手改过",
        "git diff 干净", "有 " + str(f("tracked_dirty")) + " 个跟踪文件被改过（生产上有人手改了代码？）",
        category="consistency")
    chk(True, "生产工作区里的未跟踪文件（只记录，不判）",
        str(f("untracked_file")) + " 个（多为 .bak / .env.bak 之类）", category="consistency")
    paths = f("api_paths") or "0"
    chk(paths.isdigit() and int(paths) >= 100, "接口表可读（openapi 路由数）", "路由 " + paths + " 条",
        "路由数读不出来（" + paths + "）", category="consistency")
    chk(snap_paths == 0 or str(snap_paths) == paths, "生产路由数 = 仓库最近一次快照（" + snap_name + "）",
        paths + " 条路由，与快照一致",
        "生产 " + paths + " 条 vs 快照 " + str(snap_paths) + " 条（" + snap_name + "，它只是**某个时点**的记录）",
        warn_only=True, category="consistency")
    chk(bool(f("app_has_migrations")) and f("app_has_migrations") == "yes",
        "生产代码里有版本化迁移（app.migrations）", "import app.migrations 通过",
        "生产没有 app.migrations 模块（R3-01 的版本化迁移还没上生产）", category="consistency")
    has_sv = (f("has_schema_versions") or "0") == "1"
    vers = f("schema_versions") or ""
    if head <= 0:
        chk(False, "数得出仓库的迁移最新版本", "",
            "数不出来（backend/app/migrations/ 下没有 0*.py？）—— 下面的版本比对没有意义，先修这个工具",
            category="consistency")
    else:
        chk(has_sv and str(head) in vers.split(","), "生产库结构版本 = 仓库最新版本 " + str(head),
            "已应用 " + vers, "生产库没有 schema_versions 表" if not has_sv
            else ("生产已应用 " + vers + "；仓库最新 " + str(head)), category="consistency")
    has_trace = (f("has_trace_cols") or "0") == "2"
    cov = (f("id_coverage") or "").split("|")
    chk(has_trace and len(cov) == 3 and cov[0].isdigit() and int(cov[0]) > 0, "审计行带 request_id / command_id",
        "共 " + str(cov[0] if cov else "?") + " 行；带 request_id " + str(cov[1] if len(cov) > 1 else "?")
        + " 行；带 command_id " + str(cov[2] if len(cov) > 2 else "?") + " 行",
        "生产 operation_logs 没有 request_id / command_id 列（R3-04 的那一层还没上生产）",
        category="consistency")
    rid = f("trace_probe_id") or ""
    chk(rid != "" and f("trace_app_header") == rid, "request_id 直连应用**原样**回来（响应头 X-Request-ID）",
        "发出 " + rid + " → 回来同一个", "发出 " + rid + " → 响应头里没有它（" + str(f("trace_app_header"))
        + "）；生产代码里没有 app/core/request_id.py（" + str(f("has_request_id_module"))[:40] + "）",
        category="consistency")
    chk(rid != "" and f("trace_nginx_header") == rid, "request_id 经 nginx 也原样回来",
        "发出 " + rid + " → 回来同一个（/api/v1/orders " + str(f("trace_nginx_status")) + "）",
        "经 nginx 回来的是 " + str(f("trace_nginx_header")) + "（/api/v1/orders " + str(f("trace_nginx_status"))
        + "）—— 与上一条同源", warn_only=True, category="consistency")
    has_outbox = (f("has_outbox") or "0") == "1"
    chk(has_outbox, "生产库有 outbox_events 表", "存在", "生产库没有 outbox_events 表（发件箱还没上生产）",
        category="consistency")

    # ---- 3. 依赖：声明的包在生产上装的什么（决策① 的那一格；⛔ 只记录，不判定对错）----
    runtime = [(n, d, rel) for n, d, rel in pkgs if rel.endswith("requirements.txt")]
    dev = [(n, d, rel) for n, d, rel in pkgs if not rel.endswith("requirements.txt")]
    miss = [n for n, _d, _r in runtime if not (f("pkg_" + n) or "")]
    chk(not miss, "运行依赖在生产 venv 里都读得到（" + str(len(runtime)) + " 条）",
        "全部读得到", "读不到 " + str(len(miss)) + " 个：" + "、".join(miss[:5]), category="consistency")
    devmiss = [n for n, _d, _r in dev if not (f("pkg_" + n) or "")]
    chk(True, "开发依赖在生产上没装（只记录）",
        str(len(devmiss)) + "/" + str(len(dev)) + " 个开发依赖没装（生产不装开发依赖是正常的）",
        category="consistency")
    bad = [(n, d, f("pkg_" + n) or "") for n, d, _r in runtime
           if (f("pkg_" + n) or "") and version_in_range(d, f("pkg_" + n) or "") is False]
    chk(not bad, "声明的版本区间在**生产**上成立（" + str(len(runtime)) + " 条运行依赖）",
        "全部落在声明区间内",
        "落在声明区间外：" + "；".join(n + " 声明 " + d + " 实际 " + v for n, d, v in bad[:4]),
        warn_only=True, category="consistency")
    chk(bool(f("pip_freeze_count")) and (f("pip_freeze_count") or "0").isdigit(), "生产 pip freeze 可读",
        str(f("pip_freeze_count")) + " 个包 / sha " + str(f("pip_freeze_sha")), "读不出来",
        category="consistency")

    # ---- 4. nginx 形态（R3-03 那一格要的正是这个事实；⛔ 单后端形态下「失败摘除」不适用）----
    chk((f("nginx_T_lines") or "0") != "0", "nginx 配置可读",
        str(f("nginx_T_lines")) + " 行 / " + str(f("nginx_version")), "nginx -T 打不出东西",
        category="consistency")
    chk("127.0.0.1:8000" in (f("nginx_proxy_pass") or ""), "nginx 反代到后端",
        f("nginx_proxy_pass") or "", "proxy_pass = " + str(f("nginx_proxy_pass")), category="consistency")
    chk(True, "nginx 的 upstream 形态（只记录）",
        (f("nginx_upstream") or "没有 upstream 块 —— 单后端 proxy_pass（当前部署形态）")
        + "；失败摘除指令：" + (f("nginx_failover") or "无"),
        category="consistency")
    chk(bool(f("nginx_socketio")), "nginx 有 /socket.io/ 转发（WebSocket 升级头）",
        str(f("nginx_socketio"))[:120], "nginx 里没找到 /socket.io/ 转发", warn_only=True,
        category="consistency")

    # ---- 5. 记录项（不判对错，进证据文档）----
    chk(True, "最近一单（记录）", str(f("db_last_order")) + "；它的审计行 " + str(f("db_last_order_logs")),
        category="consistency")
    chk(True, "生产 venv（记录）", str(f("venv_python")) + "；Redis keyspace " + (f("redis_keyspace") or "（空）")
        + "；备份 " + str(f("backup_db_count")) + " 份 / " + str(f("backup_root_size")),
        category="consistency")

    fails = [r for r in rows if r[0] == "fail"]
    warns = [r for r in rows if r[0] == "warn"]
    bad_health = [r for r in fails if r[3] == "health"]
    bad_consist = [r for r in fails if r[3] == "consistency"]
    mark = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    print("生产只读烟测：" + str(len(rows) - len(fails) - len(warns)) + " 通过 / "
          + str(len(warns)) + " 告警 / " + str(len(fails)) + " 不一致   （⛔ 全程只读，没有一条写操作）")
    for lvl, name, detail, cat in rows:
        print("  " + mark[lvl] + " " + name + ("  —— " + detail if detail else ""))
    if not bad_health and (bad_consist or warns):
        print("  ⓘ 没有「现状本身有问题」的项；上面这些 ❌/⚠️ 是**发布还没做**的机器形态"
              "（生产停在 " + (f("repo_commit") or "?")[:8] + "）—— 发布之后本表应全绿。")

    if a.json:
        payload = {"facts": facts,
                   "rows": [{"level": l, "name": n, "detail": d, "category": c} for l, n, d, c in rows],
                   "declared": [{"name": n, "decl": d, "file": r, "prod": f("pkg_" + n)} for n, d, r in pkgs]}
        if not a.local:
            payload["pip_freeze"] = _prodssh.ssh_lines(
                "cd " + _prodssh.BACKEND_DIR + " && .venv/bin/pip freeze")
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="")
        print("  原始事实已写：" + a.json)

    return 2 if bad_health else (1 if (bad_consist or warns) else 0)


if __name__ == "__main__":
    raise SystemExit(main())
