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

    # T2：比对 —— 比例换了，来源**必须没换**（⛔ kind 与 reason **两个都要给**）
    python _tools/ops/_freeze_probe.py --order SO... --phase t2 \
        --expect-kind legacy_client --expect-reason <T0 记下的那个>

⛔ **T2 不许只比 kind**（R4-45）：契约算不出来时会退回旧路，于是「冻结住了」与
「这次没抽中」**都是 legacy_client** —— 只比 kind 的话这个实验恒成立、什么都证明不了。
这个门禁以前**只写在注释里**（代码允许 --expect-reason 缺省，缺了就跳过那一半，
然后照样打「✅ 冻结成立」）—— 写在注释里的门禁不是门禁，现在它进了判据。
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
            # ⭐ R4-36：`resolution` 才是分得出「冻结」与「没抽中」的那一格
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.resolution')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.contract.name')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.contract.version')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.agreed')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.pricing.override')), '(无)'), "
            "coalesce(json_unquote(json_extract(o.freight_rule_snapshot, '$.at')), '(无)') "
            "from " + DB + ".orders o where " + where + " limit 1")


def freeze_verdict(now_kind: str, now_reason: str,
                   expect_kind: str, expect_reason: str) -> tuple[bool, list[str]]:
    """T2 的判据（**纯函数** ⇒ --selftest 直接测，⛔ 不用连生产）。

    为什么抠出来并强制**两个都比**（R4-45）：这一段以前写在 `main()` 里，
    注释上写着"只比 kind 证明不了任何事（假绿）"，但代码允许 `--expect-reason` 缺省 ——
    缺了就**跳过 reason 那一半**，然后照样打出「✅ **冻结成立**」。
    ⛔ 于是"必须两个都比"这句话只存在于注释里，不在判据里。

    更值钱的是：**没给基准**（T0 忘了记）与**来源真的没换**，以前在屏幕上长得一模一样。
    现在前者是一个明确的"不成立 + 为什么"。
    """
    bad: list[str] = []
    if not expect_kind:
        bad.append("⛔ 没给 --expect-kind：T2 的意义就是跟 T0 记下来的值比 —— 没有基准就没有结论")
    elif now_kind != expect_kind:
        bad.append("kind：T0 是 " + expect_kind + "，现在是 " + now_kind)
    if not expect_reason:
        bad.append("⛔ 没给 --expect-reason：只比 kind 的话「冻结住了」与「这次没抽中」"
                   "**都是 legacy_client**，这个实验证明不了任何事（假绿）")
    elif now_reason != expect_reason:
        bad.append("reason：T0 是 " + expect_reason + "，现在是 " + now_reason)
    return (not bad), bad


def selftest() -> int:
    """⛔ 这几支**只在生产上真的做 T2 时才走到** —— 所以它们必须有机器证明。"""
    bad = 0
    seen = 0

    def chk(label: str, got, want) -> None:
        nonlocal bad, seen
        seen += 1
        ok = got == want
        print(("  OK   " if ok else "  BAD  ") + label + " → " + str(got)
              + ("" if ok else "（期望 " + str(want) + "）"))
        bad += 0 if ok else 1

    okv, why = freeze_verdict("legacy_client", "no_candidates", "legacy_client", "no_candidates")
    chk("两个都比、且都对 ⇒ 冻结成立", (okv, why), (True, []))

    okv, why = freeze_verdict("freight_template", "ok", "legacy_client", "no_candidates")
    chk("kind 换了 ⇒ 不成立，且点得出是 kind", (okv, any("kind" in b for b in why)), (False, True))

    okv, why = freeze_verdict("legacy_client", "ok", "legacy_client", "no_candidates")
    chk("★ 只换了 reason（「没抽中」冒充「冻结住了」）⇒ 不成立（⛔ 以前只比 kind 会假绿）",
        (okv, any("reason：" in b for b in why)), (False, True))

    okv, _ = freeze_verdict("legacy_client", "no_candidates", "", "no_candidates")
    chk("⛔ 没给 --expect-kind ⇒ 不成立（不许把「没有基准」当成「通过」）", okv, False)

    okv, why = freeze_verdict("legacy_client", "no_candidates", "legacy_client", "")
    chk("⛔ 没给 --expect-reason ⇒ 不成立（这一条就是 R4-45 补上的门禁）", okv, False)
    chk("并把「是缺基准」与「是值变了」说成两句不同的话",
        "没给" in why[0], True)

    print("")
    print("冻结现场实验自检：" + str(seen - bad) + "/" + str(seen) + " 通过")
    return 1 if bad else 0


def _read(order: str):
    sql = _sql(order)
    remote = ("set +e\n" + _prodssh.VENV_PY + " - <<'PYEOF'\n"
              + _REMOTE_PY.replace("@SQL@", repr(sql)) + "PYEOF\n")
    out = _prodssh.ssh_script(remote, timeout=120).stdout.decode("utf-8", "replace")
    row = None
    health: list[tuple[str, str, str]] = []
    for ln in out.splitlines():
        parts = ln.split("|")
        if parts[0] == "ROW" and len(parts) >= 13:
            row = parts[1:]
        elif parts[0] == "HEALTH" and len(parts) >= 4:
            health.append((parts[1], parts[2], parts[3]))
    return row, health


def main() -> int:
    argv = sys.argv
    if "--selftest" in argv:
        return selftest()
    order = argv[argv.index("--order") + 1] if "--order" in argv else ""
    phase = argv[argv.index("--phase") + 1] if "--phase" in argv else "t0"
    expect = argv[argv.index("--expect-kind") + 1] if "--expect-kind" in argv else ""
    expect_reason = argv[argv.index("--expect-reason") + 1] if "--expect-reason" in argv else ""
    if not order:
        print("用法：--order <单号或 id> --phase t0|t1|t2 "
              + "[--expect-kind legacy_client|freight_template --expect-reason <T0 记下的那个>]")
        print("     ⛔ T2 **两个都要给**：只比 kind 证明不了任何事（见下方说明）。")
        return 2

    row, health = _read(order)
    if row is None:
        print("⛔ 生产库里找不到这一单：" + order)
        return 1
    (oid, ono, status, fee, kind, reason, resolution, cname, cver,
     agreed, override, at) = row[:12]

    print("== 冻结现场实验 · " + phase.upper() + " ==")
    print("   单：" + ono + "（id=" + oid + "，状态 " + status + "，运费 " + fee + "）")
    print("   来源凭据：kind=" + kind + "  reason=" + reason + "  resolution=" + resolution
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
        print("   ⚠️ T0 要记下来**两个**：kind=" + kind + "、reason=" + reason + " —— T2 必须都还是它。")
        print("")
        print("   ⛔ 一条 R4-34 在生产上实测出来的**局限**，先说清楚免得把结论读大：")
        print("      · 如果 T0 的 kind 是 legacy_client，这个实验**分不出冻结与没抽中** ——")
        print("        冻结住 ⇒ 仍然按旧路记；没冻 ⇒ 比例调低后这一单也不在桶里。两条路**同一支代码**，")
        print("        都写 reason=ok，唯一的差别只体现在 kind 上（而两种情况下 kind 都是 legacy_client）。")
        print("      · 真正分得开的是**契约那一支**（T0 冻结成 freight_template，T1 把比例调到 0，")
        print("        T2 必须仍然是 freight_template）—— 而生产今天**造不出**契约决策")
        print("        （driver_billing_rule_templates 是 0 行，契约必然退回旧路）。")
        print("      ⇒ 所以这一格在生产上只能证明**旧路那一支没被改动**，⛔ 不能声明冻结已被生产验证。")
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
        # ⚠️ **`kind` 一个人分不出冻结**（R4-34 实测才想清楚）：
        #    契约算不出来时会退回旧路，所以"冻结住了"与"这次没被抽中"**都是 legacy_client**。
        #    真正分得开的是 `reason`：
        #      冻结 ⇒ 仍然走契约那一支 ⇒ 算不出来 ⇒ reason=no_candidates
        #      没冻 ⇒ 比例已经调到 0，这一单**根本不在桶里** ⇒ reason=ok
        #    ⛔ 所以 t2 必须**两个都比**（门禁在 freeze_verdict 里，⛔ 不在注释里）。
        okv, bad = freeze_verdict(kind, reason, expect, expect_reason)
        if okv:
            print("   ✅ **冻结成立**：比例换过了，这张单的来源**没换**（kind=" + kind
                  + "、reason=" + reason + "）。")
            return 0
        print("   ⛔ **冻结不成立**：")
        for b in bad:
            print("      · " + b)
        # 缺基准（用法问题，退出码 2）与来源真的换了（实验失败，退出码 1）**不是同一件事**。
        return 2 if any("没给 --" in b for b in bad) else 1

    print("⛔ 不认识的 phase：" + phase)
    return 2


if __name__ == "__main__":
    sys.exit(main())