# -*- coding: utf-8 -*-
"""**最小真实价目的配置提案检查器**（R4-39，用户 §五：⛔ 不许为了让测试通过随手塞一条数据）。

用户 2026-09-27 §五 的原话：

> 「如果决定配置，不要直接拿一条随便的数据塞进去。至少做：
>  Template → 明确适用司机 → 明确有效时间 → 明确价格 → 明确 pricing kind → 确认覆盖范围。
>  并记录：**谁配的 / 什么时候配的 / 配置版本 / 适用于什么司机**。
>  这样未来出现『订单 A 为什么使用这条价目？』可以回答。」

再加上 §六 那条更要紧的：⛔ **不要为了"让 Contract 跑起来"把生产数据配得过于特殊** ——
「只给你自己的测试司机配一个特殊价格」会造成"Contract 成功，但它只在非常人工的边界条件下成功"。

## 它做什么（⛔ 全是只读）

给它**一个提案**（把哪份规则勾上哪条价目），它把该核的东西逐条摆出来：

1. 规则在不在、有没有被删、限不限车型；
2. 价目在不在、有没有被删、挂在哪条线路上、多少钱；
3. **会影响到哪些司机**（挂着这份规则的那些）—— 他们的车型和规则限的车型对不对得上；
4. **覆盖范围**：这些司机名下的单里，有多少会落进 canary 桶（按当前比例分桶，纯函数复算）；
5. **配置版本**：把这条提案的实质内容做一个 sha256 —— 以后对账就是比这个指纹，⛔ 不是靠记性。

⛔ 它**不写任何东西**：真正写那两行是人的决定（用户 §五：这是业务决定，不是技术部署）。

用法：
    python _tools/ops/_pricing_config_proposal.py --rule 1 --template 2
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _prodssh  # noqa: E402

DB = _prodssh.DB_NAME

_REMOTE = r"""set +e
@PY@ - <<'PYEOF'
import json, subprocess

DB = @DB@
RULE = @RULE@
TPL = @TPL@
PCT = @PCT@


def sql(q):
    return subprocess.run(["mysql", "-N", "-B"], input=q,
                          capture_output=True, text=True).stdout.strip()


def one(q):
    rows = sql(q).splitlines()
    return rows[0].split(chr(9)) if rows else []


print("RULE|" + chr(9).join(one(
    "select id, name, coalesce(vehicle_type, ''), piece_amount, piece_unit, is_deleted "
    "from " + DB + ".driver_billing_rules where id = " + str(RULE))))
print("TPL|" + chr(9).join(one(
    "select t.id, t.name, t.price_name, t.fee, coalesce(t.route_id, 0), "
    "coalesce(s.detail_address, ''), t.is_deleted "
    "from " + DB + ".freight_templates t left join " + DB + ".shipper_addresses s on s.id = t.route_id "
    "where t.id = " + str(TPL))))
print("LINK|" + (sql("select count(*) from " + DB + ".driver_billing_rule_templates "
                     "where rule_id = " + str(RULE) + " and template_id = " + str(TPL)) or "0"))
print("LINKS_ALL|" + (sql("select count(*) from " + DB + ".driver_billing_rule_templates") or "0"))
print("DRIVERS|" + (sql("select count(*) from " + DB + ".users where driver_rule_id = " + str(RULE)) or "0"))
for ln in sql("select id, full_name, coalesce(vehicle_type, ''), is_active "
              "from " + DB + ".users where driver_rule_id = " + str(RULE) + " order by id").splitlines():
    print("DRV|" + ln.replace(chr(9), "|"))
# ⛔ 以前这里查的是「这些司机名下的单」—— 那是**影响面**，不是**覆盖范围**。
#    R4-40 实测栽在这上面：提案 rule1×template2 报「4 张落桶」，而这张价目
#    按地址**一张都匹配不上** ⇒ 配了也永远不会产生 Contract Decision。
#    ⇒ 真正的覆盖 = 「这张价目按地址/线路能对上多少张未完结单」。
MATCH = ("(t.to_place = coalesce(o.address_detail, '') "
         "or t.route_id in (select sa.id from " + DB + ".shipper_addresses sa "
         "where sa.detail_address = coalesce(o.address_detail, '')))")
UNFINISHED = "o.status not in ('DELIVERED', 'CANCELLED', 'RETURNED')"
print("COVALL|" + (sql("select count(*) from " + DB + ".orders o, " + DB + ".freight_templates t "
                       + "where t.id = " + str(TPL) + " and " + UNFINISHED + " and " + MATCH) or "0"))
print("COVBUCKET|" + (sql("select count(*) from " + DB + ".orders o, " + DB + ".freight_templates t "
                          + "where t.id = " + str(TPL) + " and " + UNFINISHED + " and " + MATCH
                          + " and (o.id % 100) < " + str(PCT)) or "0"))
print("COVDRIVER|" + (sql("select count(*) from " + DB + ".orders o, " + DB + ".freight_templates t "
                          + "where t.id = " + str(TPL) + " and " + UNFINISHED + " and " + MATCH
                          + " and o.driver_id is not null") or "0"))
for ln in sql("select o.id, (o.id % 100), o.status, coalesce(o.driver_id, 0) from " + DB + ".orders o, "
              + DB + ".freight_templates t where t.id = " + str(TPL) + " and " + UNFINISHED
              + " and " + MATCH + " order by o.id").splitlines():
    print("COV|" + ln.replace(chr(9), "|"))
# 影响面：这些司机名下**未完结**的单有多少（原口径，改名，别与覆盖范围混）
print("ORDERS|" + (sql("select count(*) from " + DB + ".orders where driver_id in "
                       "(select id from " + DB + ".users where driver_rule_id = " + str(RULE) + ") "
                       "and status not in ('DELIVERED', 'CANCELLED', 'RETURNED')") or "0"))
print("BUCKET|" + (sql("select count(*) from " + DB + ".orders where driver_id in "
                       "(select id from " + DB + ".users where driver_rule_id = " + str(RULE) + ") "
                       "and status not in ('DELIVERED', 'CANCELLED', 'RETURNED') "
                       "and (id % 100) < " + str(PCT)) or "0"))
print("CATS|" + (sql("select count(*) from " + DB + ".freight_categories") or "0"))
print("TPLCATS|" + (sql("select count(*) from " + DB + ".freight_template_categories where template_id = " + str(TPL)) or "0"))
PYEOF
"""


def _i(v) -> int:
    return int(v) if str(v).isdigit() else 0


def main() -> int:
    argv = sys.argv
    if "--rule" not in argv or "--template" not in argv:
        print("用法：--rule <计费规则 id> --template <价目 id>")
        return 2
    rule = argv[argv.index("--rule") + 1]
    tpl = argv[argv.index("--template") + 1]
    pct = argv[argv.index("--percent") + 1] if "--percent" in argv else "30"

    script = (_REMOTE.replace("@PY@", _prodssh.VENV_PY).replace("@DB@", repr(DB))
              .replace("@RULE@", rule).replace("@TPL@", tpl).replace("@PCT@", pct))
    out = _prodssh.ssh_script(script, timeout=180, check=False).stdout.decode("utf-8", "replace")

    data: dict[str, str] = {}
    drivers: list[list[str]] = []
    covs: list[list[str]] = []
    for ln in out.splitlines():
        parts = ln.split("|")
        if parts[0] == "COV":
            covs.append(parts[1:])
        elif parts[0] == "DRV":
            drivers.append(parts[1:])
        elif len(parts) >= 2:
            data[parts[0]] = "|".join(parts[1:])

    r = (data.get("RULE", "") or "").split("\t")
    t = (data.get("TPL", "") or "").split("\t")
    print("== 配置提案检查（⛔ 只读，不写任何东西）==")
    print("")
    print("[规则] " + ((" #" + r[0] + "「" + r[1] + "」车型=" + (r[2] or "不限")
                       + " 每单 " + r[3] + " / " + r[4]) if len(r) >= 5 else "⛔ 找不到这份规则"))
    print("[价目] " + ((" #" + t[0] + "「" + t[1] + "」" + t[2] + " fee=" + t[3]
                       + " 线路=" + (t[5] or "(无)")) if len(t) >= 6 else "⛔ 找不到这条价目"))
    print("[现状] 这份规则已勾价目 " + data.get("LINKS_ALL", "?") + " 条（全库）；本提案的那一对现在"
          + ("**已经在**" if data.get("LINK") == "1" else "**不在**"))
    print("       影响面：挂这份规则的司机 " + data.get("DRIVERS", "?") + " 个，"
          + "他们名下未完结的单 " + data.get("ORDERS", "?") + " 张"
          + "（其中按 " + pct + "% 分桶会落进 canary 的 " + data.get("BUCKET", "?") + " 张）")
    print("")
    cov_all, cov_bucket = _i(data.get("COVALL")), _i(data.get("COVBUCKET"))
    print("[真实覆盖] ⭐ **这张价目按地址/线路能对上多少张未完结单**"
          + "（⛔ 与上面的影响面是两件事）")
    print("       能对上 " + str(cov_all) + " 张，其中在 canary 桶里的 " + str(cov_bucket)
          + " 张，已派了司机的 " + str(_i(data.get("COVDRIVER"))) + " 张")
    for c in covs[:10]:
        print("        #" + c[0] + "  桶=" + c[1] + "  " + c[2] + "  司机=" + (c[3] if c[3] != "0" else "(还没派)"))
    if cov_all == 0:
        print("       ⛔ **一张都对不上** ⇒ 这一对配下去**永远不会**产生 Contract Decision。"
              + " 要产生第一笔，得选一条**能对上现有单子**的价目。")
    print("       运费分类共 " + data.get("CATS", "?") + " 条；这条价目挂了 " + data.get("TPLCATS", "?") + " 个分类")
    print("")
    print("[会影响的司机]")
    for d in drivers[:12]:
        print("        #" + d[0] + " " + d[1] + "  车型=" + (d[2] or "(未填)") + "  在用=" + d[3])
    if len(drivers) > 12:
        print("        …还有 " + str(len(drivers) - 12) + " 个")

    # ⛔ 逐条把该核的说出来（用户 §五 的六项 + §六 那条"别配得太特殊"）
    print("")
    print("[逐条核对]")
    checks: list[tuple[str, bool, str]] = []
    checks.append(("规则存在且未删", len(r) >= 5 and r[5] == "0", "is_deleted=" + (r[5] if len(r) > 5 else "?")))
    checks.append(("价目存在且未删", len(t) >= 7 and t[6] == "0", "is_deleted=" + (t[6] if len(t) > 6 else "?")))
    checks.append(("价目挂在一条真实线路上", len(t) >= 5 and t[4] not in ("0", "", "None"), "route_id=" + (t[4] if len(t) > 4 else "?")))
    checks.append(("价目金额不是 0（0 元价目会让「自动带价」变成静默的 0）",
                   len(t) >= 4 and t[3] not in ("0.00", "0", ""), "fee=" + (t[3] if len(t) > 3 else "?")))
    checks.append(("有限车型的规则必须配给对得上的司机（⛔ 配错车型派单会被拦）",
                   all((not r[2]) or (d[2] or "") in ("", r[2]) for d in drivers) if len(r) >= 3 else False,
                   "规则限 " + ((r[2] if len(r) > 2 else "?") or "不限")))
    checks.append(("★ 这条价目**能对上**现有未完结单（否则配了也永远不产生 Contract Decision）",
                   _i(data.get("COVALL")) > 0, "能对上 " + str(_i(data.get("COVALL"))) + " 张"))
    checks.append(("受影响的司机不是「只有测试号」（§六：⛔ 别把生产配成人工边界）",
                   any(not (d[0] in ("3", "126", "167")) for d in drivers),
                   "司机 " + str(len(drivers)) + " 个"))
    for label, good, detail in checks:
        print("        " + ("✅ " if good else "⛔ ") + label + "　（" + detail + "）")

    fingerprint = hashlib.sha256(json.dumps(
        {"rule": rule, "template": tpl, "fee": (t[3] if len(t) > 3 else ""),
         "route": (t[4] if len(t) > 4 else ""), "vehicle": (r[2] if len(r) > 2 else "")},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    print("")
    print("[配置版本] 这一对 (rule=" + rule + ", template=" + tpl + ") 的实质指纹 = " + fingerprint)
    print("           以后对账就比这个指纹（改价目金额 / 改线路 / 改车型都会让它变）")
    print("[留档字段] 谁配的=____（人在执行时填）  何时=____  版本=" + fingerprint
          + "  适用司机=" + str(len(drivers)) + " 个")
    print("")
    allok = all(c[1] for c in checks)
    print("⇒ " + ("✅ 这个提案逐条都过 —— 但**写不写是业务决定**（用户 §五）"
                  if allok else "⛔ 有核对项没过，先别配"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())