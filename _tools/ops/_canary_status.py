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
#:      也**不要求** `pricing.resolution`：那是 R4-36 才加的，老快照没有 ——
#:      它由**单独一条判据**管（见 `resolution_cutover_ok`：新写入不许再缺）。
#:
#: ⭐ R4-45：⛔ 键名**只写在这里**，SQL 判据由它生成 —— 以前是手抄的一串字符串，
#:    与代码侧那份清单（`_check_pricing_provenance.PROVENANCE_REQUIRED`）没有任何机器对账，
#:    两边迟早漂移。漂移之后「生产上 100% 完整」与「代码里要求的那几格」说的就不是一回事。
PROV_REQUIRED_KEYS = ("v", "at", "source", "fee",
                      "pricing.kind", "pricing.contract.name", "pricing.contract.version")


def prov_missing_sql(key: str) -> str:
    """一格「缺了」的判据：**SQL NULL 或空串**。

    ⛔ 只写 `is null` 是不够的：一个写成 `""` 的键会被算成「在」，
    而代码侧判据用的是 `v not in (None, "", {})` —— 两边**不是同一个东西**，
    于是生产上能报 100% 完整，而代码侧对同一份快照判「缺」。
    （JSON `null` 仍然抓得住：`json_extract` 对它的结果本身就是 SQL NULL。）
    """
    return ("coalesce(json_unquote(json_extract(freight_rule_snapshot, '$."
            + key + "')), '') = ''")


PROV_REQUIRED_SQL = " or ".join(prov_missing_sql(k) for k in PROV_REQUIRED_KEYS)
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
                       + "@SINCE@" + " and coalesce(json_unquote(json_extract("
                       + "freight_rule_snapshot, '$.pricing.resolution')), '') <> ''") or "?"))
# ⭐ R4-45：resolution 的**缺口**还得能判「新不新」—— 于是把缺口的**最晚**时刻与
#    有值的**最早**时刻一起取回来，让数据自己说这次切换干不干净（⛔ 不比写死的时间戳：
#    那等于给「发布是什么时候」立第二个真相，发布一挪就得两边改）。
_GAP = (DB + ".orders where freight_rule_snapshot is not null" + "@SINCE@"
        + " and coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.resolution')), '') = ''")
_OK = (DB + ".orders where freight_rule_snapshot is not null" + "@SINCE@"
       + " and coalesce(json_unquote(json_extract(freight_rule_snapshot, '$.pricing.resolution')), '') <> ''")
_AT = "json_unquote(json_extract(freight_rule_snapshot, '$.at'))"
print("RESGAP|" + (sql("select count(*) from " + _GAP) or "?"))
print("RESGAPMAX|" + (sql("select coalesce(max(" + _AT + "), '-') from " + _GAP) or "-"))
print("RESOKMIN|" + (sql("select coalesce(min(" + _AT + "), '-') from " + _OK) or "-"))
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
# ⭐ **生产形状**（R4-45）：同一个逻辑值，从库里读出来有好几种写法
#
# R4-43 在生产上踩到过一次：`agreed` / `override` 是 JSON 布尔，MySQL 的
# `json_unquote(json_extract(...))` 还原出来的是**字符串 true/false**，
# 而自检里喂的样本是 1/0 ⇒ 那两个计数**恒为 0**，界面上完全看不出来。
#
# 教训不是"少认了一种写法"，而是：**自检的样本形状与生产的样本形状不一致**，
# 于是"判据自己测自己"永远绿。所以这里把读出来的一格明确分成**三态**，
# ⛔ 三者永远不许悄悄合并：
#
#   ok      —— 认得出，是白名单里的取值
#   missing —— 这一格**根本没有**（SQL NULL 经 coalesce 之后的占位符）
#   unknown —— 这一格**有内容、但认不出**（大小写漂移 / 新增取值 / 换了写法）
#
# ⛔ 把 unknown 并进任何一个已知桶都是**假绿**：它会让"认不出"看起来像"没发生"。
#    实测（R4-45 形状矩阵）：`CONTRACT`、`Contract`、`unknown` 这些 resolution
#    全都会被并进 `not_in_canary` + `inferred` —— 也就是**冒充成"R4-36 之前的老快照"**，
#    而 `inferred` 这个标签的原意是"这些笔没有 resolution 这一格"。
# ---------------------------------------------------------------------------
#: 一格"缺了"的**全部**写法 —— 就是 SQL 侧 `coalesce(..., X)` 真正会打出来的那几个占位符。
#: ⛔ 只放**真的会出现的**：`"null"` / `"None"` 这种**字面字符串**不是缺失，
#:    它是"有人把 `str(None)` 写进去了"——那是**形状异常**，并进"缺失"就等于放过它。
MISSING_MARKS = ("", "(无)", "(none)")

#: 布尔那两格的写法（比对前会 lower()）。⛔ 认不出时 as_bool 返回 None，**绝不当 False**。
_TRUEISH = ("1", "true", "yes", "on")
_FALSEISH = ("0", "false", "no", "off")

#: ⛔ **闭集**：这两个集合与 backend 的同名集合必须一致 ——
#: 由 `_tools/qa/_check_prod_shape.py` 拿 backend 的真身逐个对账（⛔ 不各写一套）。
KIND_CONTRACT = "freight_template"
KIND_LEGACY = "legacy_client"
RESOLUTIONS = ("contract", "fallback", "not_in_canary", "frozen")


def shape_of(raw, allowed: tuple) -> tuple[str, str]:
    """读出来的一格 → `("ok" | "missing" | "unknown", 归一后的原值)`。

    ⚠️ 两边都 strip()：`"frozen "`（尾空格）与 `"frozen"` 是**同一个值**，
    不该因为一个空格就被判成认不出（那样会天天误报）。
    """
    s = str(raw if raw is not None else "").strip()
    if s in MISSING_MARKS:
        return "missing", s
    if s in allowed:
        return "ok", s
    return "unknown", s


def as_bool(raw) -> bool | None:
    """生产上读出来的「是 / 否」→ True / False；⛔ **认不出 → None（说不清）**。

    ⚠️ 大小写与 1/0 都要认：MySQL 给的是 `true`/`false`（R4-43 实测），
    而别的写入路径给的可能是 `1`/`0`（R4-43 之前自检喂的就是它）。
    两种都是同一件事；⛔ 但"**认不出**"与"**是假**"不是同一件事 —— 所以这里是三态。
    """
    s = str(raw if raw is not None else "").strip().lower()
    if s in _TRUEISH:
        return True
    if s in _FALSEISH:
        return False
    return None


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

    ⭐ R4-45：`resolution` 与 `kind` 都是**闭集**，认不出的取值**单独落 `unknown`**，
    并把原值记进 `odd`。⛔ 以前它们会被并进 `not_in_canary` + `inferred` ——
    那等于把"认不出"冒充成"R4-36 之前的老快照、没被抽中"（形状矩阵实测：
    `CONTRACT` / `Contract` / `unknown` 全部走到那一支）。
    """
    out = {"contract": 0, "fallback": 0, "not_in_canary": 0, "frozen": 0,
           "stale": 0, "inferred": 0, "unknown": 0, "odd": []}
    for d in decisions:
        n = d["n"]
        rst, res = shape_of(d.get("resolution"), RESOLUTIONS)
        if rst == "unknown":
            out["unknown"] += n
            out["odd"].append("resolution=" + repr(res))
            continue
        if rst == "ok":
            out[res] += n
            continue
        # ---- 没有 resolution 这一格（R4-36 之前的老快照）：只能按 kind + reason 推断 ----
        kst, kind = shape_of(d.get("kind"), (KIND_CONTRACT, KIND_LEGACY))
        if kst != "ok":
            out["unknown"] += n
            out["odd"].append("kind=" + repr(kind))
            continue
        reason = str(d.get("reason") if d.get("reason") is not None else "")
        if reason.strip() in ("(none)", "(无)"):
            out["stale"] += n          # 缺 reason = R4-22 之前的旧式快照
            continue
        if reason.strip() == "":
            # ⚠️ **空串 ≠ 缺**：键在、只是内容空 —— 那是形状不对，⛔ 不许当成"旧式快照"。
            out["unknown"] += n
            out["odd"].append("reason=空串（⛔ 不是「缺」，是形状不对）")
            continue
        out["inferred"] += n
        if kind == KIND_CONTRACT:
            out["contract"] += n
        elif reason.strip() != "ok":
            out["fallback"] += n
        else:
            out["not_in_canary"] += n
    return out


def contract_branch(decisions: list[dict]) -> list[dict]:
    """**契约那一支**的样本 —— 与窗口的 `contract` 计数**同一口径**。

    ⛔ 以前这里按 `kind == "freight_template"` 取，而窗口按 `resolution` 取，
    于是 `frozen` 的契约单**只进这里、不进窗口**（形状矩阵实测：
    窗口 contract=4，而这里认到 10）—— ⑥ 的两个计数与窗口判据
    因此描述的是**两个不同的人群**，放在同一屏上就是在互相误导。
    """
    out = []
    for d in decisions:
        rst, res = shape_of(d.get("resolution"), RESOLUTIONS)
        if rst == "ok":
            if res == "contract":
                out.append(d)
        elif rst == "missing" and str(d.get("kind") or "").strip() == KIND_CONTRACT:
            out.append(d)      # R4-36 之前的老快照：按 kind 推断
    return out


def contract_detail(decisions: list[dict]) -> tuple[list[str], int, int, int]:
    """出口条件 ⑥：契约那一支里，算法值 == 人工最终值 / 人工改过价 / **认不出** 各多少笔。

    ⚠️ MySQL 的 json_unquote(json_extract(<JSON 布尔>)) 返回的是字符串 **true/false**，
    ⛔ 不是 1/0 —— R4-43 在生产上一跑就发现这两个计数**恒为 0**：
    自检里我喂的样本是 1/0，而生产给的是 true/false，样本形状与生产不一致。
    ⇒ 改用三态的 `as_bool`（认 1/0 也认 true/false/True/True），
    并且**认不出的单独计数**：⛔ 认不出**不是**"两个值都没发生" —— 只有把第三格
    摆出来，"形状换了"才会当场看得见，而不是又一次恒为 0。
    """
    hits = contract_branch(decisions)
    contracts = sorted({d["contract"] for d in hits})
    agreed_n = over_n = odd_n = 0
    for d in hits:
        a, o = as_bool(d.get("agreed")), as_bool(d.get("override"))
        if a is None or o is None:
            odd_n += d["n"]
            continue
        agreed_n += d["n"] if a else 0
        over_n += d["n"] if o else 0
    return contracts, agreed_n, over_n, odd_n


def resolution_cutover_ok(gap: int, gap_max: str, ok_min: str) -> tuple[bool, str]:
    """⭐ 观察期内 `pricing.resolution` 有没有**新的**缺口（R4-45）。

    口径 = **单调切换**：老快照缺这一格是合法的（R4-36 之前根本没有这一格），
    但只要窗口里已经开始出现带 resolution 的快照，**再往后就不许有缺的**。

    ⚠️ 为什么不比一个写死的"代码批次上线时刻"：那会引入**第二个真相**
    （发布时刻写在工具里、实际发布在别处），而且发布一挪就得两边改。
    ⇒ 让数据自己说话：**缺的那一批必须全都早于有的那一批**。
    这一条同时也不会变成"永远红"：切换干净过一次，它就永久绿。

    ⛔ 它拦的是 R4-36 那条语义**重新失效**：只要有一条新写入漏了这一格，
    「冻结」与「没抽中」就在生产上重新分不开（那正是 T0/T1/T2 当初卡住的原因）。
    """
    if gap == 0:
        return True, "窗口内没有一笔缺 resolution"
    if not ok_min or ok_min == "-":
        return False, ("窗口内有 " + str(gap) + " 笔缺 resolution，**一笔带它的都没有** "
                       "⇒ 分不清这些缺口是「R4-36 之前的存量」还是「新的写入漏了这一格」")
    if gap_max and gap_max != "-" and gap_max < ok_min:
        return True, ("窗口内 " + str(gap) + " 笔缺 resolution，**全部**早于第一笔带它的（"
                      + gap_max + " < " + ok_min + "）⇒ 是 R4-36 之前的存量，不是新缺口")
    return False, ("⛔ **出现了新的缺口**：最近一笔缺 resolution 的是 " + str(gap_max)
                   + "，而带 resolution 的样本最早出现在 " + str(ok_min)
                   + " —— 说明有一条写入路径没带这一格")


def window_verdict(decisions: list[dict], missing_prov: int = 0,
                   res_gap: int = 0, res_gap_max: str = "-",
                   res_ok_min: str = "-") -> list[tuple[str, bool]]:
    """⑧-a 观察窗口的门槛（⛔ 阈值只在文件头那几个常量里）。

    用户 §十三/§十四 要求**分开看三个维度**，⛔ 不许混成一个"通过/不通过"：
      · **Availability**（契约能不能算）—— 样本量、Contract 样本数、退回比例；
      · **Correctness**（算出来对不对）—— ⛔ **机器不判**，只把可观察的事实摆出来（见主输出）；
      · **Provenance**（说得清凭什么）—— 来源凭据完整率 100%、resolution 没有新缺口、
        没有新增无原因的旧式快照、**没有认不出的取值**。

    ⚠️ 用户 §十 把出口条件列成七条；这里把它拆成**九条可机判**的 —— 不是加码，是
    原来把 `error` 与 `ambiguous` 合成了一条（两种故障的修法完全不同），
    并且 **resolution 缺口**与**形状异常**当时压根没有判据（只有一句注释说"会单独报"，
    而那个数被算出来之后**丢掉不用**：`with_res` 是个死变量）。
    """
    f = four_way(decisions)
    in_bucket = f["contract"] + f["fallback"]
    # ⚠️ `frozen` **不进分母**：那一次压根没有重新抽签，它不是"抓到的样本"。
    # ⚠️ `unknown` 同样不进分母：认不出的东西算进"样本量"就是把没验证的当验证过的。
    total = in_bucket + f["not_in_canary"]
    ratio = (f["fallback"] / in_bucket) if in_bucket else None
    reasons = {str(d.get("reason") or "").strip().lower() for d in decisions}
    cut_ok, cut_why = resolution_cutover_ok(res_gap, res_gap_max, res_ok_min)
    return [
        ("样本量：桶内 ≥ " + str(WINDOW_MIN_IN_BUCKET) + " 且总数 ≥ " + str(WINDOW_MIN_TOTAL),
         in_bucket >= WINDOW_MIN_IN_BUCKET and total >= WINDOW_MIN_TOTAL),
        ("★ **真的被契约算出来**的决策 ≥ " + str(WINDOW_MIN_CONTRACT)
         + "（⛔ 只有「契约被用过」不够 —— 用户 §十三）", f["contract"] >= WINDOW_MIN_CONTRACT),
        ("★ 来源凭据**完整率 100%**（缺键 " + str(missing_prov) + " 份）", missing_prov == 0),
        ("★ `pricing.resolution` 没有**新的**缺口 —— " + cut_why, cut_ok),
        ("没有一个 " + WINDOW_FORBIDDEN_REASONS[0] + "（⛔ 与下一条**分开**：两种故障的修法不同）",
         WINDOW_FORBIDDEN_REASONS[0] not in reasons),
        ("没有一个 " + WINDOW_FORBIDDEN_REASONS[1] + "（⛔ 大小写漂移也算 —— 它曾经会静默通过）",
         WINDOW_FORBIDDEN_REASONS[1] not in reasons),
        ("桶内退回比例 ≤ " + str(WINDOW_MAX_FALLBACK_RATIO),
         ratio is not None and ratio <= WINDOW_MAX_FALLBACK_RATIO),
        ("观察期内**没有**新增无原因的旧式快照", f["stale"] == 0),
        ("⛔ 没有**认不出**的取值（"
         + ("、".join(sorted(set(f["odd"]))) if f["odd"] else "无")
         + " " + str(f["unknown"]) + " 笔）", not f["odd"]),
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
    # ⚠️ 期望值是 **40 不是 41**：老快照共 41 笔，其中 1 笔连 reason 都没有（stale）——
    #    它落的是 stale 这个**更强的结论**，不再算"按 kind+reason 推断出来的"。
    #    ⛔ 两处都算就是同一笔在两个标签里各出现一次（读的人会把它当成两笔）。
    chk("分类：没有 resolution 的老快照单独计数（⛔ 推断与事实要分得开）", f["inferred"], 40)
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

    contracts, agreed_n, over_n, odd_n = contract_detail(ds)
    chk("⑥ 契约身份去重", contracts, ["PricingContract v2"])
    chk("⑥ 算法值 == 人工最终值", agreed_n, 7)
    chk("⑥ 人工改过价（两个数都留）", over_n, 3)
    chk("⑥ 三个计数（相等 / 改过 / 认不出）加起来正好是契约支的总数",
        agreed_n + over_n + odd_n, f["contract"])

    # ⭐ 生产真实形状：MySQL 给的是 **true/false 字符串**（R4-43 实测）
    raw3 = [
        "DECISION|freight_template|ok|true|false|contract|PricingContract|2|1",
        "DECISION|freight_template|ok|false|true|contract|PricingContract|2|1",
    ]
    _, a3, o3, _n3 = contract_detail(parse_decisions(raw3))
    chk("⑥ 认得出 true/false 字符串（⛔ 只认 1/0 的话计数会恒为 0）", (a3, o3), (1, 1))

    # ================= ⭐ R4-45 形状矩阵（自检的样本形状必须覆盖生产可能的每一种）=================
    # ⚠️ 这一组的由来：R4-43 那个 bug 不是"少认了一种写法"，而是**自检喂的形状
    #    与生产给的形状不一致**（自检 1/0、生产 true/false）⇒ 判据自己测自己、永远绿。
    #    ⇒ 于是这里把每一种形状**都喂一遍**，并断言：认不出时**单独成数**，
    #      ⛔ 绝不被并进任何一个已知桶（并进去 = 把"认不出"伪装成"没发生"）。

    chk("形状：shape_of 认得出白名单取值", shape_of("frozen", RESOLUTIONS), ("ok", "frozen"))
    chk("形状：shape_of 容忍尾空格（⛔ 不该因为一个空格天天误报）",
        shape_of(" frozen ", RESOLUTIONS), ("ok", "frozen"))
    chk("形状：shape_of 把占位符判成「缺」", shape_of("(无)", RESOLUTIONS), ("missing", "(无)"))
    chk("形状：shape_of 把认不出的判成 unknown（⛔ 不吞）",
        shape_of("CONTRACT", RESOLUTIONS), ("unknown", "CONTRACT"))

    chk("形状：as_bool 认 1/0", (as_bool("1"), as_bool("0")), (True, False))
    chk("形状：as_bool 认 true/false（生产给的就是它）",
        (as_bool("true"), as_bool("false")), (True, False))
    chk("形状：as_bool 认大小写与 yes/no/on/off",
        (as_bool("TRUE"), as_bool("False"), as_bool("yes"), as_bool("off")),
        (True, False, True, False))
    chk("形状：as_bool 认不出时返回 **None**（⛔ 不是 False —— 两者不是同一件事）",
        (as_bool("2"), as_bool(""), as_bool("(无)"), as_bool(None)),
        (None, None, None, None))

    # ⛔ 这一条是整组里最值钱的：**认不出的 resolution 不许冒充老快照**
    raw4 = ["DECISION|legacy_client|ok|(无)|(无)|CONTRACT|FreightPricingCore|1|9"]
    f4a = four_way(parse_decisions(raw4))
    chk("形状⛔：认不出的 resolution 落 unknown 桶", f4a["unknown"], 9)
    chk("形状⛔：它**没有**被并进 not_in_canary（并进去 = 它冒充成「没被抽中」）",
        f4a["not_in_canary"], 0)
    chk("形状⛔：它也**没有**被并进 inferred（⛔ inferred 的原意是「R4-36 之前的老快照」）",
        f4a["inferred"], 0)
    chk("形状⛔：并把原值记下来（否则只知道「有认不出的」，不知道是谁）",
        "resolution='CONTRACT'" in f4a["odd"], True)

    f4b = four_way(parse_decisions(["DECISION|FREIGHT_TEMPLATE|ok|(无)|(无)||X|1|4"]))
    chk("形状⛔：认不出的 kind 也落 unknown（⛔ 不是 not_in_canary）",
        (f4b["unknown"], f4b["not_in_canary"] + f4b["contract"]), (4, 0))

    f4c = four_way(parse_decisions(["DECISION|legacy_client||(无)|(无)||X|1|4"]))
    chk("形状⛔：reason 是**空串**时落 unknown（⛔ 空串 ≠ 缺：键在、只是内容空）",
        (f4c["unknown"], f4c["stale"]), (4, 0))

    f4d = four_way(parse_decisions(["DECISION|legacy_client|ERROR|(无)|(无)|fallback|X|1|4"]))
    v4d = dict(window_verdict(parse_decisions(
        ["DECISION|legacy_client|ERROR|(无)|(无)|fallback|X|1|4"])))
    e4d = [k for k in v4d if k.startswith("没有一个 " + WINDOW_FORBIDDEN_REASONS[0])]
    chk("形状⛔：reason 的**大写漂移**（ERROR）仍然被 forbidden 判据抓住（⛔ 以前静默通过）",
        (f4d["fallback"], bool(e4d) and v4d[e4d[0]]), (4, False))

    # ⭐ 契约支的口径必须与窗口**同一人群**（⛔ 以前 frozen 的契约单只进 ⑥、不进窗口）
    raw5 = parse_decisions([
        "DECISION|freight_template|ok|1|0|contract|PricingContract|2|4",
        "DECISION|freight_template|ok|(无)|(无)|frozen|PricingContract|2|6",
    ])
    chk("口径：契约支 = resolution=contract（frozen 的契约单**不算**契约支）",
        sum(d["n"] for d in contract_branch(raw5)), four_way(raw5)["contract"])
    _, a5, o5, n5 = contract_detail(raw5)
    chk("口径：⑥ 的三个计数加起来 == 窗口的 contract（⛔ 两个人群不许各说各话）",
        a5 + o5 + n5, four_way(raw5)["contract"])

    raw6 = parse_decisions(["DECISION|freight_template|ok|TRUE|FALSE|contract|PricingContract|2|2"])
    _, a6, o6, n6 = contract_detail(raw6)
    chk("⑥ 形状：大字 TRUE/FALSE 也认得出", (a6, o6, n6), (2, 0, 0))
    raw7 = parse_decisions(["DECISION|freight_template|ok|(无)|(无)|contract|PricingContract|2|2"])
    _, a7, o7, n7 = contract_detail(raw7)
    chk("⑥ 形状⛔：认不出时**单独成数**（⛔ 不是「0 笔相等、0 笔改过」这种看不出来的假绿）",
        (a7, o7, n7), (0, 0, 2))

    # ---- resolution 缺口：**新不新**（R4-45）----
    chk("缺口：一笔都不缺 ⇒ 过", resolution_cutover_ok(0, "-", "-")[0], True)
    chk("缺口：有缺、有值、且缺口全在值之前 ⇒ 过（是 R4-36 的存量）",
        resolution_cutover_ok(3, "2026-09-27T07:30:00", "2026-09-27T10:30:00")[0], True)
    chk("缺口：有缺、**一笔值都没有** ⇒ 不过（分不清是存量还是新漏）",
        resolution_cutover_ok(3, "2026-09-27T07:30:00", "-")[0], False)
    chk("缺口：⛔ 缺口出现在有值的**之后** ⇒ 不过（新的写入漏了这一格）",
        resolution_cutover_ok(1, "2026-09-27T11:00:00", "2026-09-27T10:30:00")[0], False)
    chk("缺口：那句话说清了「分不清存量还是新漏」",
        "分不清" in resolution_cutover_ok(3, "x", "-")[1], True)

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
    cut = [k for k in fails if k.startswith("★ `pricing.resolution`")]
    chk("窗口：resolution 缺口单独成一条门槛（⛔ R4-45 之前这个数算出来就丢了）", bool(cut), True)
    chk("窗口：缺口 0 ⇒ 那一条过", fails[cut[0]] if cut else None, True)
    err_keys = [k for k in fails if k.startswith("没有一个 " + WINDOW_FORBIDDEN_REASONS[0])]
    amb_keys = [k for k in fails if k.startswith("没有一个 " + WINDOW_FORBIDDEN_REASONS[1])]
    chk("窗口：⛔ error 与 ambiguous **是两条**（两种故障的修法不同，不许合成一条）",
        (len(err_keys), len(amb_keys)), (1, 1))
    chk("窗口：没有 forbidden reason ⇒ 两条都过",
        bool(err_keys and amb_keys) and fails[err_keys[0]] and fails[amb_keys[0]], True)
    chk("窗口：退回 5/15 = 0.33 ≤ 0.8 ⇒ 过", fails["桶内退回比例 ≤ 0.8"], True)
    chk("窗口：有 stale ⇒ 不过", fails["观察期内**没有**新增无原因的旧式快照"], False)
    shape_key = [k for k in fails if k.startswith("⛔ 没有**认不出**")]
    chk("窗口：认不出的取值单独成一条门槛（⛔ 没有它，形状换了也照样全绿）",
        bool(shape_key) and fails[shape_key[0]], True)
    bad_shape = dict(window_verdict(parse_decisions(
        ["DECISION|legacy_client|ok|(无)|(无)|CONTRACT|X|1|1"])))
    bk = [k for k in bad_shape if k.startswith("⛔ 没有**认不出**")]
    chk("窗口：真有坏形状时那一条会红（⛔ 否则它就是一条永远绿的装饰）",
        bool(bk) and bad_shape[bk[0]], False)

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
        {"contract": 0, "fallback": 0, "not_in_canary": 0, "frozen": 0,
         "stale": 0, "inferred": 0, "unknown": 0, "odd": []})
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
    res_gap = "?"          # 窗口内缺 pricing.resolution 的快照数
    res_gap_max = "-"      # 缺的那一批里**最晚**的时刻（判断这个缺口新不新）
    res_ok_min = "-"       # 有 resolution 的那一批里**最早**的时刻
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
        elif parts[0] == "RESGAP":
            res_gap = parts[1] if len(parts) > 1 else "?"
        elif parts[0] == "RESGAPMAX":
            res_gap_max = parts[1] if len(parts) > 1 else "-"
        elif parts[0] == "RESOKMIN":
            res_ok_min = parts[1] if len(parts) > 1 else "-"

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
        contracts, agreed_n, over_n, odd_n = contract_detail(decisions)
        if contracts:
            print("        契约身份（生产上真的用到的那几版）：" + "、".join(contracts))
            print("        ⑥ 算法值 == 人工最终值：" + str(agreed_n) + " 笔"
                  + " ／ 人工改过价（两个数都留下了）：" + str(over_n) + " 笔")
            print("           ⚠️ 两个数都留下是可查的；⛔ 但「金额对不对」这件事**只能人看**，本工具不判。")
            if odd_n:
                # ⛔ 这一行才是 R4-43 那个坑的真正修法：认不出的形状**单独成数**，
                #    而不是悄悄并进"两个数都没发生"（那样它会恒为 0，谁也看不出来）。
                print("           ⛔ 另有 " + str(odd_n) + " 笔的 agreed/override **认不出形状**"
                      + "（既不算「相等」也不算「没发生」—— 形状换了就得当场看见）")
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
    res_gap_n = _i(res_gap)
    snap_n = _i(snaptotal)
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
    if f4["unknown"]:
        print("        ⛔ **认不出的取值**   unknown         " + str(f4["unknown"])
              + "   ← ⛔ 它们**不是**老快照：是形状换了（" + "、".join(sorted(set(f4["odd"]))) + "）")
        print("           ⇒ ⛔ 不许把它读成「没抽中」或「R4-36 之前的存量」—— 先查是谁换了写法。")
    print("        resolution 覆盖率  with_res         " + str(with_res) + " / " + str(snap_n)
          + "   ← ⭐ 它单独成一条判据（以前这个数算出来就丢掉了）")
    if res_gap_n:
        print("           ⛔ 缺 resolution 的 " + str(res_gap_n) + " 笔里，**最晚**一笔在 "
              + str(res_gap_max) + "；有 resolution 的最早一笔在 " + str(res_ok_min))
    if SINCE:
        print("        窗口起点（快照 pricing.at ≥）：" + SINCE_AT + " UTC")
    if not SINCE:
        print("        ⚠️ 没给 --since：上面是**历史累计**，⛔ 不能当观察窗口的结论。")
        print("           发布之后跑：python _tools/ops/_canary_status.py --since <发布日>")
        window_ok = None
    else:
        crit = window_verdict(decisions, missing_prov,
                              res_gap_n, str(res_gap_max), str(res_ok_min))
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
        print("          + resolution 没有**新的**缺口 + 观察期内没有新增无原因的旧式快照")
        print("          + ⛔ 没有**认不出**的取值（认不出并进已知桶 = 假绿，R4-45）")

    if strict and state != "ACTIVE":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())