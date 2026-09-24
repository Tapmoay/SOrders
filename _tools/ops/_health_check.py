#!/usr/bin/env python3
"""_health_check.py —— 生产的**最小外部监控**（整改报告 §15 的第三件小事）。

### 为什么是这一件

报告的原话：“现在无监控、无告警、无 trace，甚至出现过**证书过期两个月无人发现**”。
实测把这句话坐实了：`docs/BASELINE.md` 里那条风险 —— 域名证书 `sorders.top` **已过期 75 天**。
所以先不要上复杂的 observability 平台，只做**四个一眼能判的阈值**：

| 检查 | 阈值 | 为什么是它 |
|---|---|---|
| 服务 + `/health` | 必须 200 | 服务挂了其他都不用看 |
| 证书剩余天数 | <30 天告警 / **<7 天失败** | 报告点名的那件事（过期了没人知道） |
| 磁盘使用率 | >85% 告警 / **>95% 失败** | 备份和图片会先把它吃满 |
| **最近一次备份的年龄** | >36 小时告警 | 有备份系统 ≠ 备份在跑（cron 死了没人知道） |

⛔ 全部**只读**（走 `_prodssh.prod_facts_script()`，那条路径刻意只读）；
⛔ 退出码机器可判：`0=全绿 / 1=有告警 / 2=有失败` —— 好让 cron/CI/人 各取所需。

用法：
    python _tools/ops/_health_check.py            # 打印一张表 + 退出码
    python _tools/ops/_health_check.py --quiet    # 只在非全绿时输出（给 cron）
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

#: (名字, 项, 阈值说明)；阈值都写成常量，改口径只改这里。
CERT_WARN_DAYS, CERT_FAIL_DAYS = 30, 7
DISK_WARN_PCT, DISK_FAIL_PCT = 85, 95
BACKUP_WARN_HOURS = 36
#: 发件箱（报告 §10）的积压阈值：待发堆起来 = worker 卡了；放弃数 ≠0 = 有人得去看 last_error。
OUTBOX_PENDING_WARN = 50

#: **已知且当前无解**的证书告警（键 = 证书名，值 = 为什么现在解不了 + 什么时候删掉这一条）。
#:
#: ⛔ 这不是「忽略」，恰恰相反 —— 这一条**每次运行都会打印**（连理由一起），只是不再把整体判成
#:    「失败」。判成失败的前提是「有人能去修」；域名未备案这件事**今天谁也修不了**，
#:    于是每天两次的 ❌ 只会训练所有人无视这张表 —— 本项目自己的话：「永远红的检查 = 没有检查」。
#:    所以：**已知的、有据可查的、当前无解的问题 → 降成告警并写明理由**；其余一律照旧判失败。
#: ⚠️ 三条纪律（`_tools/ops/_check_ops.py` 第 7 条逐条钉着）：① 每条都要写理由；
#:    ② 理由里要写**什么时候删掉它**；③ 跑完要报**没命中的条目**（证书处理掉了/改名了 → 那是化石）。
ACCEPTED_CERT: dict[str, str] = {
    "sorders.top": "域名**未备案** → 阿里云按 Host/SNI 拦截 80/443，Let\'s Encrypt 的 HTTP-01 挑战"
                   "被拦成 403（2026-09-25 实测：certbot 1.22 renew 报 unauthorized/403，"
                   "而从 127.0.0.1 直连 nginx 时挑战路径正常 404/200 = nginx 本身没问题）。"
                   "App 走的是 IP 证书（`/etc/nginx/ssl/sorders-ip-chain.crt`，实测还有 1089 天）。"
                   "**备案完成、或改用 DNS-01 挑战之后，删掉这一条。**",
    "sorders.top-0001": "同一个域名的第二份 lineage（certbot 的 `-0001`），未备案这件事完全一样。"
                        "**备案完成、或改用 DNS-01 挑战之后，删掉这一条。**",
}


def _run(script: str, local: bool):
    """跑同一段事实脚本：local=True 在**本机**跑（服务器上的 cron 模式），否则 ssh 过去跑。

    ⚠️ 两种模式的脚本**是同一份**（`_prodssh.prod_facts_script()`）—— 监控与基线看到的必须是同一批事实，
    否则会出现「基线里好好的、监控说挂了」。
    """
    if local:
        return subprocess.run(["bash", "-c", script], capture_output=True, timeout=120)
    return _prodssh.ssh_script(script, timeout=120)


def _lines(cmd: str, local: bool) -> list[str]:
    """同上，但只要 stdout 的非空行（备份年龄那段用）。"""
    if local:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, timeout=60)
        return [x.strip() for x in r.stdout.decode("utf-8", "replace").splitlines() if x.strip()]
    return _prodssh.ssh_lines(cmd)


def _facts(local: bool = False) -> dict[str, str]:
    """生产只读事实（复用基线采集那一段脚本 —— 口径只有一处）。"""
    out: dict[str, str] = {}
    script = _prodssh.prod_facts_script()
    r = _run(script, local)
    for ln in r.stdout.decode("utf-8", "replace").splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    # 最近一次备份的年龄（秒）：取 /opt/sorders-backup 下最新的 manifest.json
    cmd = f"find {_prodssh.BACKUP_ROOT} -name manifest.json -printf '%T@\\n' 2>/dev/null | sort -rn | head -1"
    age = _lines(cmd, local)
    out["backup_latest_epoch"] = age[0] if age else ""
    return out


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="生产最小外部监控（只读）")
    ap.add_argument("--quiet", action="store_true", help="只在非全绿时输出（给 cron）")
    ap.add_argument("--local", action="store_true",
                    help="在**服务器本机**跑（cron 用；默认走 ssh 从本机连过去）")
    args = ap.parse_args(argv)

    f = _facts(local=args.local)
    rows: list[tuple[str, str, str]] = []      # (级别, 项, 说明)
    accepted_hit: set[str] = set()             # 本次命中的「已知/已接受」条目（跑完拿它找化石）

    state = f.get("service_state", "?")
    health = f.get("api_health", "?")
    rows.append(("ok" if state == "active" and health == "200" else "fail",
                 "服务 / 健康检查",
                 f"systemd={state} ｜ /health={health} ｜ {f.get('api_health_body', '')[:60]}"))

    for key in sorted(k for k in f if k.endswith("_days_left")):
        try:
            days = int(f[key])
        except ValueError:
            continue
        lvl = "fail" if days < CERT_FAIL_DAYS else ("warn" if days < CERT_WARN_DAYS else "ok")
        name = key[len("cert_"):-len("_days_left")]
        if lvl != "ok" and name in ACCEPTED_CERT:
            accepted_hit.add(name)
            rows.append(("warn", f"证书 {name}（已知/已接受）",
                         f"剩余 {days} 天 —— 为什么现在解不了：{ACCEPTED_CERT[name]}"))
            continue
        rows.append((lvl, f"证书 {name}", f"剩余 {days} 天"))

    try:
        pct = int(str(f.get("disk_pct", "")).rstrip("%"))
    except ValueError:
        pct = -1
    lvl = "fail" if pct >= DISK_FAIL_PCT else ("warn" if pct >= DISK_WARN_PCT else "ok")
    rows.append((lvl if pct >= 0 else "warn", "磁盘",
                 f"用了 {pct}%（{f.get('disk_used', '?')} / {f.get('disk_total', '?')}，剩 {f.get('disk_avail', '?')}）"))

    epoch = f.get("backup_latest_epoch", "")
    if not epoch:
        rows.append(("fail", "最近一次备份", "**一个都没有**（备份系统没在跑）"))
    else:
        try:
            age_h = (datetime.now(timezone.utc).timestamp() - float(epoch)) / 3600
        except ValueError:
            age_h = -1
        lvl = "ok" if 0 <= age_h <= BACKUP_WARN_HOURS else ("warn" if age_h > BACKUP_WARN_HOURS else "warn")
        rows.append((lvl, "最近一次备份", f"{age_h:.1f} 小时前（阈值 {BACKUP_WARN_HOURS}h）"))

    # ---- 数据库可达性（报告 §15 ③ 点名的四项之一）----
    reachable = f.get("db_reachable", "").strip()
    rows.append((
        "ok" if reachable == "1" else "fail",
        "数据库",
        f"探针 select 1 = {reachable or '（无输出）'} ｜ {f.get('db_size_mb', '?')} MB / {f.get('db_tables', '?')} 表"
        f" ｜ 迁移版本 {f.get('db_schema_version') or '—'}",
    ))

    # ---- 发件箱积压（§10 之后，这条是"事件到底发出去没有"的唯一外部信号）----
    has_table = f.get("outbox_table", "").strip()
    if has_table != "1":
        rows.append(("warn", "发件箱", "生产库里还没有 `outbox_events` 表（新代码尚未部署）"))
    else:
        def _n(key: str) -> int:
            try:
                return int(f.get(key, "") or 0)
            except ValueError:
                return -1

        pending, sent, failed = _n("outbox_pending"), _n("outbox_sent"), _n("outbox_failed")
        if failed < 0 or pending < 0:
            lvl = "warn"
        elif failed > 0:
            lvl = "warn"      # 不是 fail：业务没坏，是"有事件发不出去"，要人去看 last_error
        elif pending > OUTBOX_PENDING_WARN:
            lvl = "warn"      # 待发堆起来 = worker 卡住/处理器在失败
        else:
            lvl = "ok"
        rows.append((lvl, "发件箱",
                     f"待发 {pending} / 已发 {sent} / 放弃 {failed}（待发阈值 {OUTBOX_PENDING_WARN}，放弃数必须为 0）"))

    # ---- 例外表不许长霉：没命中的条目 ＝ 证书已经处理掉或改名了，留着就是化石 ----
    stale_accepted = sorted(set(ACCEPTED_CERT) - accepted_hit)
    if stale_accepted:
        rows.append(("warn", "证书例外表",
                     "这些条目**没命中任何证书**（证书已处理/改名 → 把这一条删掉）："
                     + "、".join(stale_accepted)))

    fails = [r for r in rows if r[0] == "fail"]
    warns = [r for r in rows if r[0] == "warn"]
    if not args.quiet or fails or warns:
        mark = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
        print(f"生产健康检查（{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}Z）："
              f"{len(rows) - len(fails) - len(warns)} 项正常 / {len(warns)} 告警 / {len(fails)} 失败")
        for lvl, name, detail in rows:
            print(f"  {mark[lvl]} {name}：{detail}")
        print(f"\n主机：{f.get('host', '?')} ｜ 库：{f.get('db_size_mb', '?')} MB / {f.get('db_tables', '?')} 表 ｜ "
              f"上传：{f.get('uploads_size', '?')} ｜ 备份：{f.get('backup_db_count', '?')} 份")
    return 2 if fails else (1 if warns else 0)


if __name__ == "__main__":
    raise SystemExit(main())
