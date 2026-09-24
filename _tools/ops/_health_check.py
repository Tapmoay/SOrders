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
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

#: (名字, 项, 阈值说明)；阈值都写成常量，改口径只改这里。
CERT_WARN_DAYS, CERT_FAIL_DAYS = 30, 7
DISK_WARN_PCT, DISK_FAIL_PCT = 85, 95
BACKUP_WARN_HOURS = 36


def _facts() -> dict[str, str]:
    """生产只读事实（复用基线采集那一段脚本 —— 口径只有一处）。"""
    out: dict[str, str] = {}
    r = _prodssh.ssh_script(_prodssh.prod_facts_script(), timeout=120)
    for ln in r.stdout.decode("utf-8", "replace").splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    # 最近一次备份的年龄（秒）：取 /opt/sorders-backup 下最新的 manifest.json
    age = _prodssh.ssh_lines(
        f"find {_prodssh.BACKUP_ROOT} -name manifest.json -printf '%T@\\n' 2>/dev/null | sort -rn | head -1")
    out["backup_latest_epoch"] = age[0] if age else ""
    return out


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="生产最小外部监控（只读）")
    ap.add_argument("--quiet", action="store_true", help="只在非全绿时输出")
    args = ap.parse_args(argv)

    f = _facts()
    rows: list[tuple[str, str, str]] = []      # (级别, 项, 说明)

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
