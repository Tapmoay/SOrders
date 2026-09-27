# -*- coding: utf-8 -*-
"""**Canary 状态**：把「CONFIGURED」与「ACTIVE」分开（R4-28，⑧-a 出口条件 ②⑤⑦）。

## 它回答的问题

    「30% 写在环境变量里了」        ← 看 .env 就知道
    「生产实际上已经在以 30% 运行」  ← ⛔ 只能**逐个实例去问**

这是两个完全不同的问题。滚动发布期间完全可能是 A=30 / B=0，而 .env 上一个字都看不出来。
所以这个工具只做一件事：把**目标**（.env）与**实际**（每个进程的 /health）摆在一起，
然后给一个正式的状态。

## 正式状态（⑧-a 出口条件 ②）

| 状态 | 含义 |
| --- | --- |
| OFF | 目标 0 且所有实例都是 0（没开） |
| CONFIGURED_ONLY | .env 上写了要开，但**生产还没在这么跑**（有实例没生效 / 不一致 / 没重启） |
| ACTIVE | 六条子条件**全过**：目标非 0 ／ 实例可达且 health 绿 ／ 两实例一致 ／ 一致且等于目标 ／ schema 就绪 ／ 算价扩展已装配 |

## ⚠️ ACTIVE 不等于「Canary 被用上了」（出口条件 ⑦）

契约算不出来时会**如实退回旧路** —— 那是对的行为（Canary 不是 Full Cutover）。
但如果退回的比例是 100%，系统看起来"运行正常"，实际是**一次都没用上契约**。
所以这个工具最后一定会把 freight_template / legacy_client / 各种 reason 的条数打出来，
并在"配着但一次都没命中"时**当场标出来**。

## ⛔ 只读

它只 curl 本机的 /health、只跑 SELECT。生产主机/密钥/路径一律从 _prodssh import。

用法：
    python _tools/ops/_canary_status.py            # 看状态
    python _tools/ops/_canary_status.py --strict   # 不是 ACTIVE 就返回 1（给脚本用）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

DB = _prodssh.DB_NAME

# ---------------------------------------------------------------------------
# ⑧-a 观察窗口的**预注册门槛**（用户 §8：「达到预先定义的最小样本量 → 检查」）
#
# ⛔ 这几个数字的**唯一来源就是这里** —— 文档只写口径与理由，不抄数字。
# ⛔ 它们在**观察之前**就写死：不写死的话，"看多少算够"就会变成事后找理由。
# ---------------------------------------------------------------------------
#: 桶内决策（真的被 canary 抽中的那些）至少要这么多笔。
WINDOW_MIN_IN_BUCKET = 20
#: 决策总数（含没被抽中的）至少要这么多笔。
WINDOW_MIN_TOTAL = 40
#: 桶内退回比例的上限（退回可以有，但不能"配着却几乎一次都没用上"）。
WINDOW_MAX_FALLBACK_RATIO = 0.8
#: 观察期内**一个都不许出现**的原因码（它们都是有具体故障含义的）。
WINDOW_FORBIDDEN_REASONS = ("error", "ambiguous")


def _arg(flag: str) -> str:
    """取 --flag value（没给就返回空串）。"""
    argv = sys.argv
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else ""


#: 观察窗口起点（YYYY-MM-DD）。⛔ 不给就**只看历史累计**，那种数字不许当窗口结论。
SINCE = _arg("--since")

#: 远端只跑这一段（heredoc 用**带引号**的分隔符：外层的 bash 一个字符都不许展开）。
REMOTE = r"""set +e
@PY@ - <<'PYEOF'
import json, re, subprocess, urllib.request

DB = "sorders"


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def sql(q):
    # ⛔ SQL 用 **stdin** 送进 mysql（不是 shell 字符串）：$ 一个都不会被展开
    return subprocess.run(["mysql", "-N", "-B"], input=q,
                          capture_output=True, text=True).stdout.strip()


ports = sorted({int(m) for m in re.findall(r"port (\d+)", sh("pgrep -af 'uvicorn app.main:app'"))})
if not ports:
    ports = [8000]
for p in ports:
    try:
        with urllib.request.urlopen("http://127.0.0.1:" + str(p) + "/health", timeout=8) as r:
            d = json.load(r)
        pr = d.get("pricing") or {}
        print("HEALTH|" + str(p) + "|" + str(d.get("status")) + "|" + str(pr.get("canary_percent"))
              + "|" + str(pr.get("resolver")))
    except Exception as exc:
        print("HEALTH|" + str(p) + "|ERROR|?|" + type(exc).__name__)

print("SCHEMA|" + (sql("select coalesce(max(version),0) from " + DB + ".schema_versions") or "?"))
print("COLUMN|" + (sql("select count(*) from information_schema.columns where table_schema='" + DB
                      + "' and table_name='orders' and column_name='freight_rule_snapshot'") or "?"))
rows = sql("select coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.kind')), '(none)'), "
           "coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.reason')), '(none)'), "
           "count(*) from " + DB + ".orders where freight_rule_snapshot is not null"
           + "@SINCE@" + " group by 1, 2 order by 3 desc")
for ln in rows.splitlines():
    if ln.strip():
        print("DECISION|" + ln.replace(chr(9), "|"))
print("SNAPTOTAL|" + (sql("select count(*) from " + DB + ".orders where freight_rule_snapshot is not null") or "?"))
print("ORDERS|" + (sql("select count(*) from " + DB + ".orders") or "?"))
PYEOF"""


# ⚠️ 远端那一段**必须**用 venv 里那个 python：生产机上 /usr/bin/python3 是 **3.6**，
#    连 subprocess 的 capture_output 都没有（第一版就栽在这上面：
#    TypeError: __init__() got an unexpected keyword argument 'capture_output'）。
# 观察窗口起点：快照里的 `pricing.at` 是 UTC 的 ISO 字符串（秒精度），可以直接按字典序比。
_SINCE_SQL = ("" if not SINCE else
              " and json_unquote(json_extract(freight_rule_snapshot, '$.at')) >= '" + SINCE + "T00:00:00'")
_REMOTE = REMOTE.replace("@PY@", _prodssh.VENV_PY).replace("@SINCE@", _SINCE_SQL)


def main() -> int:
    strict = "--strict" in sys.argv

    env = _prodssh.read_env()
    raw_target = (env.get("FREIGHT_PRICING_CANARY_PERCENT") or "0").strip()
    try:
        target = max(0, min(100, int(raw_target)))
    except ValueError:
        target = -1

    r = _prodssh.ssh_script(_REMOTE, timeout=180)
    out = r.stdout.decode("utf-8", "replace")

    instances: list[tuple[str, str, str, str]] = []
    decisions: list[tuple[str, str, int]] = []
    schema = col = snaptotal = orders = "?"
    for ln in out.splitlines():
        parts = ln.split("|")
        if parts[0] == "HEALTH" and len(parts) >= 5:
            instances.append((parts[1], parts[2], parts[3], "|".join(parts[4:])))
        elif parts[0] == "DECISION" and len(parts) >= 4:
            try:
                decisions.append((parts[1], parts[2], int(parts[3])))
            except ValueError:
                pass
        elif parts[0] == "SCHEMA":
            schema = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "COLUMN":
            col = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "SNAPTOTAL":
            snaptotal = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "ORDERS":
            orders = parts[1] if len(parts) > 1 else "?"

    print("== R4-PROD-CANARY 状态（⑧-a）—— 生产机，只读 ==")
    print("")
    print("[目标] .env 上 FREIGHT_PRICING_CANARY_PERCENT = "
          + (raw_target if target >= 0 else raw_target + "（⛔ 读不出整数）"))
    print("[实例] 实际生效的（逐个进程问出来的，⛔ 不是看 .env）")
    for port, status, pct, resolver in instances:
        if pct in ("None", "?", ""):
            # ⭐ 「字段读不出来」与「值不对」是**两件事**：
            #    前者说明这个实例跑的是**还没有指纹那一版**的代码（要发布），
            #    后者说明配置没生效（要重启 / 要对齐 .env）。修法完全不同。
            print("        :" + port + "  status=" + status
                  + "  ⛔ /health 上**没有** pricing 指纹 —— 这个实例跑的是还没指纹那一版的代码")
        else:
            print("        :" + port + "  status=" + status + "  canary_percent=" + pct
                  + "  resolver=" + resolver)
    print("[schema] 版本 " + str(schema) + "（本仓库迁移头 9）｜ orders.freight_rule_snapshot 列 "
          + ("在" if col == "1" else "⛔ 不在"))
    print("")
    print("[观测] 订单 " + str(orders) + " 张，其中**带来源凭据**的 " + str(snaptotal) + " 张")
    if decisions:
        for kind, reason, n in decisions:
            mark = ("  ← 契约真的算出来了" if kind == "freight_template"
                    else ("  ← R4-22 之前的旧快照，没有 reason 字段" if reason == "(none)" else ""))
            print("        " + kind.ljust(16) + " reason=" + reason.ljust(16) + str(n) + mark)
    else:
        print("        （还没有任何一张单带来源凭据 —— R4-21 之后产生的单才会有）")

    pcts = {p for _port, st, p, _res in instances if st != "ERROR" and p.isdigit()}
    reported = bool(instances) and all(p.isdigit() for _p, _s, p, _r in instances)
    all_reachable = bool(instances) and all(st == "ok" for _p, st, _pc, _r in instances)
    all_loaded = bool(instances) and all("未装配" not in res for _p, _s, _pc, res in instances)
    conds = [
        ("目标非 0（.env 上写了要开）", target > 0),
        ("每个实例都可达且 status=ok", all_reachable),
        ("每个实例都**报得出**指纹（跑的是带指纹那一版）", reported),
        ("各个实例的 effective 比例**一致**", reported and len(pcts) == 1),
        ("effective 比例 == 目标", reported and pcts == {str(target)}),
        ("schema 就绪（版本 ≥ 9 且来源凭据列在）",
         schema.isdigit() and int(schema) >= 9 and col == "1"),
        ("算价扩展已装配（组装点的槽位有人填）", all_loaded),
    ]

    if target == 0 and pcts == {"0"}:
        state = "OFF"
    elif all(c for _l, c in conds):
        state = "ACTIVE"
    else:
        state = "CONFIGURED_ONLY"

    print("")
    print("[判定] ⑧-a 出口条件 ② 的六条子条件：")
    for label, c in conds:
        print("        " + ("✅ " if c else "⛔ ") + label)
    print("        ⇒ Canary = " + state)
    if state == "CONFIGURED_ONLY":
        print("        ⚠️ 这句话的意思是：**.env 上写了，但生产还没在这么跑** ——")
        print("           要么有实例没重启/没读到，要么两个实例不一致（滚动发布期间会出现）。")

    hits = sum(n for k, _r, n in decisions if k == "freight_template")
    fallbacks = sum(n for k, r, n in decisions if r not in ("(none)", "ok"))
    print("")
    print("[出口条件 ⑦] fallback 必须可统计（⛔ 允许退回，但不许**没有记录**地退回）")
    old_style = sum(n for k, r, n in decisions if k == "legacy_client" and r == "(none)")
    print("        契约命中 " + str(hits) + " ／ 如实退回（带 reason）" + str(fallbacks)
          + ("　／ 旧快照（无 reason）" + str(old_style) if old_style else "")
          + "　—— 退回的每一条都带 reason，上面已经按 reason 分组")
    if target > 0 and hits == 0 and decisions:
        print("        ⛔ 配着 Canary，但**一次都没真正用上契约** ——")
        print("           这就是「系统看起来正常、其实 Canary 没在跑」那种假稳定。")
    elif target > 0 and not decisions:
        print("        ⚠️ 还没有任何决策记录 —— 观察窗口还没开始，别把「没有数据」读成「没问题」。")

    # ---------------- ⑧-a 观察窗口（预注册门槛见文件头那几个常量）----------------
    contract = sum(n for k, _r, n in decisions if k == "freight_template")
    fell_back = sum(n for k, r, n in decisions
                    if k == "legacy_client" and r not in ("(none)", "ok"))
    not_in_bucket = sum(n for k, r, n in decisions if k == "legacy_client" and r == "ok")
    stale = sum(n for k, r, n in decisions if r == "(none)")
    in_bucket = contract + fell_back

    print("")
    print("[观察窗口] 四分类（口径按 pricing.reason 判，⛔ 不是按我猜）")
    print("        契约算出来        contract        " + str(contract))
    print("        桶内退回（带原因） fell_back       " + str(fell_back))
    print("        没被抽中          not_in_bucket   " + str(not_in_bucket))
    print("        旧式快照（无原因） stale           " + str(stale)
          + "   ← 只该来自 R4-22 之前，观察期内**新增**任何一个都是问题")
    if not SINCE:
        print("        ⚠️ 没给 --since：上面是**历史累计**，⛔ 不能当观察窗口的结论。")
        print("           发布之后跑：python _tools/ops/_canary_status.py --since <发布日>")
        window_ok = None
    else:
        ratio = (fell_back / in_bucket) if in_bucket else None
        crit = [
            ("样本量：桶内 ≥ " + str(WINDOW_MIN_IN_BUCKET) + " 且总数 ≥ " + str(WINDOW_MIN_TOTAL),
             in_bucket >= WINDOW_MIN_IN_BUCKET and (contract + fell_back + not_in_bucket) >= WINDOW_MIN_TOTAL),
            ("契约真的被用上了（contract ≥ 1）", contract >= 1),
            ("没有一个 " + " / ".join(WINDOW_FORBIDDEN_REASONS),
             not any(r in WINDOW_FORBIDDEN_REASONS for _k, r, _n in decisions)),
            ("桶内退回比例 ≤ " + str(WINDOW_MAX_FALLBACK_RATIO),
             ratio is not None and ratio <= WINDOW_MAX_FALLBACK_RATIO),
            ("观察期内**没有**新增无原因的旧式快照", stale == 0),
        ]
        for label, c in crit:
            print("        " + ("✅ " if c else "⛔ ") + label)
        window_ok = all(c for _l, c in crit)
        print("        ⇒ 观察窗口 = " + ("通过" if window_ok else "**还没通过**（⛔ 不许「再看看」）"))

    if strict and state != "ACTIVE":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())