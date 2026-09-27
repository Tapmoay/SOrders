# -*- coding: utf-8 -*-
"""**T0 / T1 / T2 冻结现场实验**（R4-29）：在生产上证明"换了比例，来源没换"。

用户 2026-09-27 点名的那个实验：

> 「T0: canary = 30 → 创建 / 派单 → 得到某种 pricing source
>  T1: canary = 0  → 再触发一个后续写操作
>  T2: 检查 snapshot
>  如果仍然保持 T0 的 pricing source，那就证明：**你真的做了 Decision Freeze**。」

## ⛔ 这个脚本**不改任何配置、不重启、不写库**

它只做两件事：**读**一张单的来源凭据；以及**读**每个实例实际生效的比例。
中间的"改比例 + 滚动重启 + 再写一次"是**人做的生产动作** ——
脚本会把该做什么原样打印出来，但⛔ 不会替你做（改生产配置不是工具该自作主张的事）。

## 用法（三段式，与用户的 T0/T1/T2 一一对应）

    # T0：改比例**之前**，记下这张单现在的来源
    python _tools/ops/_freeze_probe.py --order SO202609270599071778 --phase t0

    # （人做）改 .env 的比例 → 逐实例滚动重启 → 再触发这张单的一次运费写入

    # T1：确认两个实例**实际生效**的比例真的变了（⛔ 不是看 .env）
    python _tools/ops/_freeze_probe.py --order SO... --phase t1

    # T2：比对 —— 比例换了，来源**必须没换**
    python _tools/ops/_freeze_probe.py --order SO... --phase t2 --expect-kind legacy_client
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

DB = _prodssh.DB_NAME

_REMOTE_PY = """import json, sqlite3, subprocess, urllib.request
sql = @SQL@
out = subprocess.run(["mysql", "-N", "-B"], input=sql, capture_output=True, text=True).stdout.strip()
print("ROW|" + out.replace(chr(9), "|"))
for p in sorted({int(m) for m in __import__("re").findall(r"port (\\d+)",
                                        subprocess.run(["pgrep", "-af", "uvicorn app.main:app"],
                                                       capture_output=True, text=True).stdout)}) or [8000]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:" + str(p) + "/health", timeout=8) as r:
            d = json.load(r)
        pr = d.get("pricing") or {}
        print("HEALTH|" + str(p) + "|" + str(pr.get("canary_percent")) + "|" + str(pr.get("resolver")))
    except Exception as exc:
        print("HEALTH|" + str(p) + "|ERROR|" + type(exc).__name__)
"""


def _sql(order: str) -> str:
    where = ("o.id = " + order) if order.isdigit() else ("o.order_no = " + repr(order).replace(chr(34), chr(39)))
    return ("select o.id, o.order_no, o.status, o.freight_fee, "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.kind')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.reason')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.contract.name')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.contract.version')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.agreed')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.override')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.at')), '(无)') "
            "from " + DB + ".orders o where " + where + " limit 1")


def _read(order: str):
    sql = _sql(order)
    remote = ("set +e\n" + _prodssh.VENV_PY + " - <<'PYEOF'\n"
              + _REMOTE_PY.replace("@SQL@", repr(sql)) + "PYEOF\n")
    out = _prodssh.ssh_script(remote, timeout=120).stdout.decode("utf-8", "replace")
    row = None
    health: list[tuple[str, str, str]] = []
    for ln in out.splitlines():
        parts = ln.split("|")
        if parts[0] == "ROW" and len(parts) >= 12:
            row = parts[1:]
        elif parts[0] == "HEALTH" and len(parts) >= 4:
            health.append((parts[1], parts[2], parts[3]))
    return row, health


def main() -> int:
    argv = sys.argv
    order = argv[argv.index("--order") + 1] if "--order" in argv else ""
    phase = argv[argv.index("--phase") + 1] if "--phase" in argv else "t0"
    expect = argv[argv.index("--expect-kind") + 1] if "--expect-kind" in argv else ""
    if not order:
        print("用法：--order <单号或 id> --phase t0|t1|t2 [--expect-kind legacy_client|freight_template]")
        return 2

    row, health = _read(order)
    if row is None:
        print("⛔ 生产库里找不到这一单：" + order)
        return 1
    (oid, ono, status, fee, kind, reason, cname, cver, agreed, override, at) = row[:11]

    print("== 冻结现场实验 · " + phase.upper() + " ==")
    print("   单：" + ono + "（id=" + oid + "，状态 " + status + "，运费 " + fee + "）")
    print("   来源凭据：kind=" + kind + "  reason=" + reason
          + "  contract=" + cname + " v" + cver
          + "  agreed=" + agreed + "  override=" + override + "  at=" + at)
    print("   实际生效的比例（逐个实例问出来的）：")
    for port, pct, resolver in health:
        print("        :" + port + "  canary_percent=" + pct + "  resolver=" + resolver)

    if phase == "t0":
        print("")
        print("   下一步（**人做**，脚本不替你做）：")
        print("     ① 改 /opt/SOrders/.env 的 FREIGHT_PRICING_CANARY_PERCENT（记得两边实例都要读到）")
        print("     ② 逐实例 drain / restart（按发布器的顺序，不要一次全重启）")
        print("     ③ 让这张单**再走一次真实的运费写入**（派单界面改价 / 或用真实接口）")
        print("     ④ 跑 --phase t1 确认比例真的变了，再跑 --phase t2 比对来源")
        print("")
        print("   ⚠️ T0 的 kind 要记下来：" + kind + " —— T2 必须还是它。")
        return 0

    if phase == "t1":
        pcts = {p for _p, p, _r in health if p.isdigit()}
        print("")
        if len(pcts) == 1:
            print("   ⇒ 两个实例一致，实际生效比例 = " + str(next(iter(pcts))) + "%")
        else:
            print("   ⛔ 实例之间**不一致**：" + str(sorted(pcts)) + " —— 现在做 T2 没有意义，")
            print("      先让它们一致（这正是出口条件 ② 要拦的那种状态）。")
            return 1
        return 0

    if phase == "t2":
        print("")
        if not expect:
            print("   ⛔ 少给 --expect-kind：T2 的意义就是**跟 T0 记下来的那一个比**。")
            return 2
        if kind == expect:
            print("   ✅ **冻结成立**：比例换过了，这张单的来源**没换**（仍然是 " + expect + "）。")
            return 0
        print("   ⛔ **冻结不成立**：T0 是 " + expect + "，现在是 " + kind
              + " —— 同一张单因为 canary 配置变化换了来源。")
        return 1

    print("⛔ 不认识的 phase：" + phase)
    return 2


if __name__ == "__main__":
    sys.exit(main())