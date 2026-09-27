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
#: ⭐ **真的被契约算出来的**决策至少要这么多笔（用户 §十三：
#:    「100 笔里 90 legacy / 10 fallback / 0 contract，即使总数 ≥20 也没验证 Pricing Contract」）。
WINDOW_MIN_CONTRACT = 10
#: ⭐ 来源凭据的**完整率**必须 100%（用户 §十三：provenance completeness = 100%）。
#:    口径 = 窗口内每一份快照都能恢复这几个键（⛔ 不是"大部分能"）：
#:      v / at / source / fee / pricing.kind / pricing.contract.name / pricing.contract.version
#:    ⚠️ parsing 时**故意不要求** `rule` 与 `category`：没有匹配到价目时它们**合法地为空**。
#:      也**不要求** `pricing.resolution`：那是 R4-36 才加的，老快照没有 —— 单独报它的覆盖率。
PROV_REQUIRED_SQL = (
    "json_extract(freight_rule_snapshot, '$.v') is null or "
    "json_extract(freight_rule_snapshot, '$.at') is null or "
    "json_extract(freight_rule_snapshot, '$.source') is null or "
    "json_extract(freight_rule_snapshot, '$.fee') is null or "
    "json_extract(freight_rule_snapshot, '$.pricing.kind') is null or "
    "json_extract(freight_rule_snapshot, '$.pricing.contract.name') is null or "
    "json_extract(freight_rule_snapshot, '$.pricing.contract.version') is null"
)
#: 观察期内**一个都不许出现**的原因码（它们都是有具体故障含义的）。
WINDOW_FORBIDDEN_REASONS = ("error", "ambiguous")


def _arg(flag: str) -> str:
    """取 --flag value（没给就返回空串）。"""
    argv = sys.argv
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else ""


#: 观察窗口起点。⛔ 不给就**只看历史累计**，那种数字不许当窗口结论。
#: 两种写法：`YYYY-MM-DD`（按当天 00:00:00 UTC）或完整的 `YYYY-MM-DDTHH:MM:SS`。
#: ⚠️ 为什么要精确到秒：预注册的窗口边界**就是**边界的定义 ——
#:    发布是某一天的 15:40，而按日期过滤会把当天发布**之前**的单也算进去。
SINCE = _arg("--since")
SINCE_AT = (SINCE + "T00:00:00") if len(SINCE) == 10 else SINCE

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
# ⭐ 出口条件 ⑥（override 必须同时保留算法值与人工最终值）也要能在生产上**看出来**，
#    所以 agreed / override / 契约身份 一起取回来 —— ⛔ 不能只在单测里成立。
rows = sql("select coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.kind')), '(none)'), "
           "coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.reason')), '(none)'), "
           "coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.agreed')), '(无)'), "
           "coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.override')), '(无)'), "
           "coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.resolution')), ''), "
           "coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.contract.name')), '(无)'), "
           "coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.contract.version')), '(无)'), "
           "count(*) from " + DB + ".orders where freight_rule_snapshot is not null"
           + "@SINCE@" + " group by 1, 2, 3, 4, 5, 6, 7 order by 8 desc")
for ln in rows.splitlines():
    if ln.strip():
        print("DECISION|" + ln.replace(chr(9), "|"))
# ⚠️ 这个数**也要**跟着窗口走：不然屏幕上会同时出现「带凭据 2 张」和
#    「还没有任何一张单带凭据」—— 两句都对，放在一起就是误导（R4-34 发布后实测遇到）。
print("SNAPTOTAL|" + (sql("select count(*) from " + DB + ".orders where freight_rule_snapshot is not null"
           + "@SINCE@") or "?"))
print("ORDERS|" + (sql("select count(*) from " + DB + ".orders") or "?"))
# ---- 结构性前提：契约到底**能不能**算出东西来（⛔ 与样本量无关，先看这个）----
print("RULETPL|" + (sql("select count(*) from " + DB + ".driver_billing_rule_templates") or "?"))
print("TPL|" + (sql("select count(*) from " + DB + ".freight_templates where is_deleted = 0") or "?"))
print("RULEDRV|" + (sql("select count(*) from " + DB + ".users where driver_rule_id is not null") or "?"))
# ---- 来源凭据的完整率（用户 §十三：provenance completeness = 100%）----
print("PROVMISS|" + (sql("select count(*) from " + DB + ".orders where freight_rule_snapshot is not null"
                        + "@SINCE@" + " and (" + "@PROV@" + ")") or "?"))
print("PROVRES|" + (sql("select count(*) from " + DB + ".orders where freight_rule_snapshot is not null"
                       + "@SINCE@" + " and json_extract(freight_rule_snapshot, '$.pricing.resolution') is not null") or "?"))
PYEOF"""


# ⚠️ 远端那一段**必须**用 venv 里那个 python：生产机上 /usr/bin/python3 是 **3.6**，
#    连 subprocess 的 capture_output 都没有（第一版就栽在这上面：
#    TypeError: __init__() got an unexpected keyword argument 'capture_output'）。
# 观察窗口起点：快照里的 `pricing.at` 是 UTC 的 ISO 字符串（秒精度），可以直接按字典序比。
_SINCE_SQL = ("" if not SINCE else
              " and json_unquote(json_extract(freight_rule_snapshot, '$.at')) >= '" + SINCE_AT + "'")
_REMOTE = (REMOTE.replace("@PY@", _prodssh.VENV_PY)
           .replace("@SINCE@", _SINCE_SQL)
           .replace("@PROV@", PROV_REQUIRED_SQL))


# ---------------------------------------------------------------------------
# 纯函数（⇒ --selftest 直接测，⛔ 不用连生产）
#
# ⭐ 为什么把它们抠出来：这几段**只在生产上有数据时才走到**（例如"契约命中了"那一支），
#    而"只在生产上才跑的分支"正是最容易悄悄坏掉的地方 —— 坏了也没人当场知道。
# ---------------------------------------------------------------------------
def parse_decisions(lines: list[str]) -> list[dict]:
    """远端 `DECISION|kind|reason|agreed|override|contract|version|count` 行 → 结构化。"""
    out: list[dict] = []
    for ln in lines:
        parts = ln.split("|")
        if parts[0] != "DECISION" or len(parts) < 9:
            continue
        try:
            n = int(parts[8])
        except ValueError:
            continue
        out.append({"kind": parts[1], "reason": parts[2],
                    "agreed": parts[3], "override": parts[4],
                    "resolution": parts[5],
                    "contract": parts[6] + " v" + parts[7], "n": n})
    return out


def four_way(decisions: list[dict]) -> dict:
    """⑧-a 观察窗口的分类。

    ⭐ R4-36 起**优先读 `pricing.resolution`**（这一次走的是哪条路）—— 它把
    「没抽中」与「已冻结沿用旧路」分开了；⛔ 老快照（R4-36 之前）没有这一格，
    只能按 kind+reason **推断**，而推断**分不出 frozen** ⇒ 单独计数并如实标注。
    """
    out = {"contract": 0, "fallback": 0, "not_in_canary": 0, "frozen": 0,
           "stale": 0, "inferred": 0}
    for d in decisions:
        res, n = d.get("resolution") or "", d["n"]
        if res in ("contract", "fallback", "not_in_canary", "frozen"):
            out[res] += n
            continue
        out["inferred"] += n
        if d["reason"] == "(none)":
            out["stale"] += n
        elif d["kind"] == "freight_template":
            out["contract"] += n
        elif d["reason"] not in ("ok",):
            out["fallback"] += n
        else:
            out["not_in_canary"] += n
    return out


def contract_detail(decisions: list[dict]) -> tuple[list[str], int, int]:
    """出口条件 ⑥：契约那一支里，算法值 == 人工最终值 / 人工改过价 各多少笔。"""
    hits = [d for d in decisions if d["kind"] == "freight_template"]
    contracts = sorted({d["contract"] for d in hits})
    # ⚠️ MySQL 的 json_unquote(json_extract(<JSON 布尔>)) 返回的是字符串 **true/false**，
    #    ⛔ 不是 1/0 —— R4-43 在生产上一跑就发现这两个计数**恒为 0**：
    #    自检里我喂的样本是 1/0，而生产给的是 true/false，样本形状与生产不一致。
    #    ⇒ 两个都认；并且自检里**补上生产真实形状**的那一组（见 selftest）。
    TRUEISH = ("1", "true", "True")
    agreed_n = sum(d["n"] for d in hits if d["agreed"] in TRUEISH)
    over_n = sum(d["n"] for d in hits if d["override"] in TRUEISH)
    return contracts, agreed_n, over_n


def window_verdict(decisions: list[dict], missing_prov: int = 0) -> list[tuple[str, bool]]:
    """⑧-a 观察窗口的门槛（⛔ 阈值只在文件头那几个常量里）。

    用户 §十三/§十四 要求**分开看三个维度**，⛔ 不许混成一个"通过/不通过"：
      · **Availability**（契约能不能算）—— 样本量、Contract 样本数、退回比例；
      · **Correctness**（算出来对不对）—— ⛔ **机器不判**，只把可观察的事实摆出来（见主输出）；
      · **Provenance**（说得清凭什么）—— 来源凭据完整率 100%、不许新增无原因的旧式快照。
    """
    f = four_way(decisions)
    in_bucket = f["contract"] + f["fallback"]
    # ⚠️ `frozen` **不进分母**：那一次压根没有重新抽签，它不是"抓到的样本"。
    total = in_bucket + f["not_in_canary"]
    ratio = (f["fallback"] / in_bucket) if in_bucket else None
    return [
        ("样本量：桶内 ≥ " + str(WINDOW_MIN_IN_BUCKET) + " 且总数 ≥ " + str(WINDOW_MIN_TOTAL),
         in_bucket >= WINDOW_MIN_IN_BUCKET and total >= WINDOW_MIN_TOTAL),
        ("★ **真的被契约算出来**的决策 ≥ " + str(WINDOW_MIN_CONTRACT)
         + "（⛔ 只有「契约被用过」不够 —— 用户 §十三）", f["contract"] >= WINDOW_MIN_CONTRACT),
        ("★ 来源凭据**完整率 100%**（缺键 " + str(missing_prov) + " 份）", missing_prov == 0),
        ("没有一个 " + " / ".join(WINDOW_FORBIDDEN_REASONS),
         not any(d["reason"] in WINDOW_FORBIDDEN_REASONS for d in decisions)),
        ("桶内退回比例 ≤ " + str(WINDOW_MAX_FALLBACK_RATIO),
         ratio is not None and ratio <= WINDOW_MAX_FALLBACK_RATIO),
        ("观察期内**没有**新增无原因的旧式快照", f["stale"] == 0),
    ]


def window_feasibility(rule_tpl: int, templates: int, drivers_with_rule: int) -> tuple[bool, str]:
    """⑧-a 观察窗口**结构上有没有可能通过**（⛔ 与样本量无关 —— 先看这个，再看样本）。

    ⭐ 为什么要单列：预注册的五条判据里有两条是「契约真的被用上了」与「退回比例 ≤ 上限」。
    而**契约算不算得出来**取决于生产上配没配价目 —— 这件事**不会**随着样本变多而改善。
    ⛔ 不先看它，就会拿几周的真实流量去等一个**结构上不可能通过**的窗口。
    """
    if rule_tpl <= 0:
        return False, ("契约**结构上**必然退回：没有任何计费规则勾过价目"
                       + "（driver_billing_rule_templates = 0 行）"
                       + " ⇒ 桶内决策 100% 是 fell_back ⇒ 判据②（契约真的被用上）"
                       + "与判据④（退回比例 ≤ 上限）**不可能通过**。"
                       + " 窗口再等也不会过 —— 要先把那**一行配置**配上（见台账 R4-24）。")
    if templates <= 0:
        return False, ("价目表是空的（freight_templates = 0 行）⇒ 挂在规则上也没有价目可算")
    if drivers_with_rule <= 0:
        return False, ("一个司机都没挂计费规则 ⇒ 永远走不到候选集那一步")
    return True, ("结构上具备通过的条件：规则勾了 " + str(rule_tpl) + " 条价目、"
                  + "可用价目 " + str(templates) + " 条、" + str(drivers_with_rule) + " 个司机挂了规则")


def selftest() -> int:
    """⛔ 这几段**只在生产上有数据时才走到**（例如"契约命中了"那一支）——
    所以它们必须有机器证明，⛔ 不能等生产上第一次跑到才发现坏了。"""
    bad = 0
    seen = 0

    def chk(label: str, got, want) -> None:
        # ⛔ 条数**自己数**：第一版把总数写成 `total = 17`，而实际打了 18 条 ——
        #    于是屏幕上写着 17/17（全过），却有一条压根没被算进去。
        nonlocal bad, seen
        seen += 1
        ok = got == want
        print(("  OK   " if ok else "  BAD  ") + label + " → " + str(got)
              + ("" if ok else "（期望 " + str(want) + "）"))
        bad += 0 if ok else 1

    # ⚠️ 这五行是 **R4-36 之前的老快照形状**（第 6 格 resolution 是空的）——
    #    专门用来验「老数据只能推断、且推断分不出 frozen」那一条。
    raw = [
        "DECISION|freight_template|ok|1|0||PricingContract|2|7",
        "DECISION|freight_template|ok|0|1||PricingContract|2|3",
        "DECISION|legacy_client|no_candidates|(无)|(无)||FreightPricingCore|1|5",
        "DECISION|legacy_client|ok|(无)|(无)||FreightPricingCore|1|25",
        "DECISION|legacy_client|(none)|(无)|(无)||FreightPricingCore|1|1",
        "DECISION|垃圾行",
    ]
    ds = parse_decisions(raw)
    chk("解析：跳过垃圾行，其余 5 行都要在", len(ds), 5)
    chk("解析：契约身份拼成 name + v + version", ds[0]["contract"], "PricingContract v2")
    chk("解析：agreed/override 原样保留", (ds[0]["agreed"], ds[1]["override"]), ("1", "1"))

    f = four_way(ds)
    chk("分类：没有 resolution 的老快照单独计数（⛔ 推断与事实要分得开）", f["inferred"], 41)
    chk("分类：老快照里 contract / fallback / not_in_canary 仍按 kind+reason 推断",
        (f["contract"], f["fallback"], f["not_in_canary"]), (10, 5, 25))
    chk("分类：老快照的 stale", f["stale"], 1)
    chk("分类：老快照**分不出 frozen**（这一格必须是 0，⛔ 不许瞎猜）", f["frozen"], 0)

    # ⭐ R4-36：带 resolution 的快照按它分类 —— 「冻结」与「没抽中」必须分开
    raw2 = [
        "DECISION|freight_template|ok|1|0|contract|PricingContract|2|4",
        "DECISION|legacy_client|no_candidates|(无)|(无)|fallback|FreightPricingCore|1|3",
        "DECISION|legacy_client|ok|(无)|(无)|not_in_canary|FreightPricingCore|1|20",
        "DECISION|legacy_client|ok|(无)|(无)|frozen|FreightPricingCore|1|6",
    ]
    f2 = four_way(parse_decisions(raw2))
    chk("R4-36：resolution=contract", f2["contract"], 4)
    chk("R4-36：resolution=fallback", f2["fallback"], 3)
    chk("R4-36：resolution=not_in_canary", f2["not_in_canary"], 20)
    chk("R4-36：resolution=frozen 与「没抽中」**分开**（⛔ 合并就是这次要修的坑）",
        (f2["frozen"], f2["inferred"]), (6, 0))

    contracts, agreed_n, over_n = contract_detail(ds)
    chk("⑥ 契约身份去重", contracts, ["PricingContract v2"])
    chk("⑥ 算法值 == 人工最终值", agreed_n, 7)
    chk("⑥ 人工改过价（两个数都留）", over_n, 3)

    # ⭐ 生产真实形状：MySQL 给的是 **true/false 字符串**（R4-43 实测）
    raw3 = [
        "DECISION|freight_template|ok|true|false|contract|PricingContract|2|1",
        "DECISION|freight_template|ok|false|true|contract|PricingContract|2|1",
    ]
    _, a3, o3 = contract_detail(parse_decisions(raw3))
    chk("⑥ 认得出 true/false 字符串（⛔ 只认 1/0 的话计数会恒为 0）", (a3, o3), (1, 1))
    chk("⑥ 两者相加 == 契约命中总数", agreed_n + over_n, f["contract"])

    fails = dict(window_verdict(ds))
    chk("窗口：桶内 15 < 20 ⇒ 样本量不过", fails["样本量：桶内 ≥ 20 且总数 ≥ 40"], False)
    key = [k for k in fails if k.startswith("★ **真的被契约算出来**")]
    chk("窗口：契约真的算出来的样本数单独成一条门槛", bool(key), True)
    chk("窗口：契约样本 10 笔 = 门槛 ⇒ 恰好过（边界不许差一）", fails[key[0]] if key else None, True)
    thin = [d for d in ds if d["contract"] != "PricingContract v2"]
    thin_contract = sum(d["n"] for d in thin if d["kind"] == "freight_template")
    thin_key = [k for k in dict(window_verdict(thin)) if k.startswith("★ **真的被契约算出来**")][0]
    chk("窗口：契约样本 " + str(thin_contract) + " 笔 < 门槛 ⇒ 那一条不过",
        dict(window_verdict(thin))[thin_key], False)
    prov = [k for k in fails if k.startswith("★ 来源凭据")]
    chk("窗口：来源凭据完整率单独成一条门槛", bool(prov), True)
    chk("窗口：缺键 0 份 ⇒ 完整率那条过", fails[prov[0]] if prov else None, True)
    chk("窗口：没有 forbidden reason ⇒ 过", fails["没有一个 error / ambiguous"], True)
    chk("窗口：退回 5/15 = 0.33 ≤ 0.8 ⇒ 过", fails["桶内退回比例 ≤ 0.8"], True)
    chk("窗口：有 stale ⇒ 不过", fails["观察期内**没有**新增无原因的旧式快照"], False)

    # ---- 窗口可行性（纯函数）----
    ok0, why0 = window_feasibility(0, 8, 25)
    chk("可行性：没有任何规则勾过价目 ⇒ 不过", ok0, False)
    chk("可行性：并把「结构上不可能」说出来", "结构上" in why0, True)
    chk("可行性：点名要配的那张表", "driver_billing_rule_templates" in why0, True)
    ok1, why1 = window_feasibility(3, 0, 25)
    chk("可行性：价目表空的 ⇒ 不过", (ok1, "价目表是空的" in why1), (False, True))
    ok2, why2 = window_feasibility(3, 8, 0)
    chk("可行性：没司机挂规则 ⇒ 不过", (ok2, "都没挂计费规则" in why2), (False, True))
    ok3, why3 = window_feasibility(3, 8, 25)
    chk("可行性：三样都有 ⇒ 过", (ok3, "具备通过的条件" in why3), (True, True))

    empty = parse_decisions([])
    chk("空输入不炸", four_way(empty),
        {"contract": 0, "fallback": 0, "not_in_canary": 0, "frozen": 0, "stale": 0, "inferred": 0})
    chk("桶内为 0 时比例算不出来（⛔ 不是当成 0% 过）",
        dict(window_verdict(empty))["桶内退回比例 ≤ " + str(WINDOW_MAX_FALLBACK_RATIO)], False)

    print("")
    print("状态工具自检：" + str(seen - bad) + "/" + str(seen) + " 通过")
    return 1 if bad else 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

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
    raw_decisions: list[str] = []
    schema = col = snaptotal = orders = "?"
    rule_tpl = tpl_n = ruledrv = "?"
    provmiss = provres = "?"
    for ln in out.splitlines():
        parts = ln.split("|")
        if parts[0] == "HEALTH" and len(parts) >= 5:
            instances.append((parts[1], parts[2], parts[3], "|".join(parts[4:])))
        elif parts[0] == "DECISION":
            raw_decisions.append(ln)      # 解析交给纯函数（可 selftest）
        elif parts[0] == "SCHEMA":
            schema = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "COLUMN":
            col = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "SNAPTOTAL":
            snaptotal = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "ORDERS":
            orders = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "RULETPL":
            rule_tpl = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "TPL":
            tpl_n = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "RULEDRV":
            ruledrv = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "PROVMISS":
            provmiss = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "PROVRES":
            provres = parts[1] if len(parts) > 1 else "?"

    decisions = parse_decisions(raw_decisions)

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
    scope = ("窗口内（pricing.at ≥ " + SINCE_AT + " UTC）" if SINCE else "全库历史累计")
    print("[观测] " + scope + "：带来源凭据的订单 " + str(snaptotal) + " 张"
          + ("　（全库订单 " + str(orders) + " 张）" if SINCE else ""))
    if decisions:
        for d in decisions:
            mark = ("  ← 契约真的算出来了" if d["kind"] == "freight_template"
                    else ("  ← R4-22 之前的旧快照，没有 reason 字段" if d["reason"] == "(none)" else ""))
            print("        " + d["kind"].ljust(16) + " reason=" + d["reason"].ljust(16)
                  + str(d["n"]).ljust(5) + mark)
        contracts, agreed_n, over_n = contract_detail(decisions)
        if contracts:
            print("        契约身份（生产上真的用到的那几版）：" + "、".join(contracts))
        if contracts:
            print("        ⑥ 算法值 == 人工最终值：" + str(agreed_n) + " 笔"
                  + " ／ 人工改过价（两个数都留下了）：" + str(over_n) + " 笔")
            print("           ⚠️ 两个数都留下是可查的；⛔ 但「金额对不对」这件事**只能人看**，本工具不判。")
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

    hits = sum(d["n"] for d in decisions if d["kind"] == "freight_template")
    fallbacks = sum(d["n"] for d in decisions if d["reason"] not in ("(none)", "ok"))
    print("")
    print("[出口条件 ⑦] fallback 必须可统计（⛔ 允许退回，但不许**没有记录**地退回）")
    old_style = sum(d["n"] for d in decisions if d["kind"] == "legacy_client" and d["reason"] == "(none)")
    print("        契约命中 " + str(hits) + " ／ 如实退回（带 reason）" + str(fallbacks)
          + ("　／ 旧快照（无 reason）" + str(old_style) if old_style else "")
          + "　—— 退回的每一条都带 reason，上面已经按 reason 分组")
    if target > 0 and hits == 0 and decisions:
        print("        ⛔ 配着 Canary，但**一次都没真正用上契约** ——")
        print("           这就是「系统看起来正常、其实 Canary 没在跑」那种假稳定。")
    elif target > 0 and not decisions:
        print("        ⚠️ 还没有任何决策记录 —— 观察窗口还没开始，别把「没有数据」读成「没问题」。")

    # ---------------- ⑧-a 观察窗口（预注册门槛见文件头那几个常量）----------------
    def _i(v) -> int:
        return int(v) if str(v).isdigit() else 0

    missing_prov = _i(provmiss)
    with_res = _i(provres)
    f4 = four_way(decisions)
    contract, fell_back = f4["contract"], f4["fallback"]
    not_in_bucket, stale = f4["not_in_canary"], f4["stale"]
    in_bucket = contract + fell_back

    print("")

    feasible, why = window_feasibility(_i(rule_tpl), _i(tpl_n), _i(ruledrv))
    print("[窗口可行性] " + ("✅ " if feasible else "⛔ ") + why)

    print("[观察窗口] 分类（⭐ 优先读 pricing.resolution；老快照才按 kind+reason 推断）")
    print("        契约算出来        contract        " + str(contract))
    print("        桶内退回（带原因） fell_back       " + str(fell_back))
    print("        没被抽中          not_in_canary   " + str(not_in_bucket))
    print("        **冻结沿用旧路**   frozen          " + str(f4["frozen"])
          + "   ← ⭐ R4-36 起才分得出来（以前它与「没被抽中」写出来一模一样）")
    if f4["inferred"]:
        print("          ⚠️ 其中 " + str(f4["inferred"]) + " 笔是 **R4-36 之前的老快照**（没有 resolution 这一格），"
              + "只能按 kind+reason 推断 —— 而推断**分不出 frozen**。")
    print("        旧式快照（无原因） stale           " + str(stale)
          + "   ← 只该来自 R4-22 之前，观察期内**新增**任何一个都是问题")
    if SINCE:
        print("        窗口起点（快照 pricing.at ≥）：" + SINCE_AT + " UTC")
    if not SINCE:
        print("        ⚠️ 没给 --since：上面是**历史累计**，⛔ 不能当观察窗口的结论。")
        print("           发布之后跑：python _tools/ops/_canary_status.py --since <发布日>")
        window_ok = None
    else:
        crit = window_verdict(decisions, missing_prov)
        for label, c in crit:
            print("        " + ("✅ " if c else "⛔ ") + label)
        window_ok = all(c for _l, c in crit)
        print("        ⇒ 观察窗口 = " + ("通过" if window_ok else "**还没通过**（⛔ 不许「再看看」）"))
        print("")
        print("    [三维度] ⛔ 不许混成一个「通过 / 不通过」（用户 §十四）")
        print("        A **Availability**（契约能不能算）：上面的样本量 / Contract 样本数 / 退回比例")
        print("        B **Correctness**（算出来对不对）：⛔ **机器不判** —— 工具只回答「两个值在不在」；")
        print("          「这个数业务上该不该是这么多」**必须人看**（用户 §十五：这条边界不许为了自动化再塞回去）")
        print("        C **Provenance**（说得清凭什么）：来源凭据完整率 100% + 每条退回都带 reason")
        print("          + 观察期内没有新增无原因的旧式快照")

    if strict and state != "ACTIVE":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())