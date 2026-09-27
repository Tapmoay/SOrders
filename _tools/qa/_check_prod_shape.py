# -*- coding: utf-8 -*-
"""**生产形状对账判据**（R4-45）：同一个逻辑值，读它的那几处必须**说得是同一种话**。

R4-BOUNDARY-JUSTIFICATION: **代码边界解决不了这件事，因为缺口长在「两份清单各写各的」上。**

R4-43 在生产上踩到的那个 bug（`agreed`/`override` 的两个计数**恒为 0**）不是"少认了一种
写法"这么简单，它暴露的是一个**结构性**问题：

    自检喂的样本形状  ≠  生产给的样本形状
    ⇒ 判据自己测自己 ⇒ 永远绿

而形状这一类缺口**在任何单个文件里都看不出来**：读 JSON 的那一处语法正确、类型正确、
单测全绿，错的只有一件事 —— 它以为生产给的是 `1`/`0`，而生产给的是 `true`/`false`。

## 它查什么（七组，清单**自己算**，⛔ 不手写）

1. **闭集对账**：`_canary_status` 里的 `RESOLUTIONS` / `KIND_*` 必须与 backend 的同名集合
   逐个相同（⛔ 各写一套就一定会漂移，而漂移之后"生产上圆不圆"与"代码里认什么"是两回事）。
2. **读取点登记**：扫 `_tools/` 里**所有** `json_extract` 的键路径 —— 每一处都必须登记
   （含"认不出的后果"）；登记了但扫不到 = 化石，也红。
3. **两份「必须能恢复的键」清单对账**：生产 SQL 判据（`PROV_REQUIRED_KEYS`）与代码侧判据
   （`_check_pricing_provenance` 里那张表 + 它真的 `_dig` 过的那些键）—— 差异必须写进
   豁免表 + 理由 + 锚点仍在。
4. **缺键判据的形状**：`prov_missing_sql` 必须同时覆盖 **SQL NULL 与空串**
   （代码侧用的是 `v not in (None, "", {})`）—— ⛔ 只写 `is null` 时，一个写成 `""`
   的键会被算成"在"，于是**生产报 100% 完整、代码侧判它缺**。
5. **真的跑一遍形状矩阵**：import 那个工具，把每一种形状喂进它的纯函数 ——
   认不出的取值**必须单独成桶**，⛔ 不许并进任何一个已知桶。
6. **不许再有内联手写的布尔集合**：那种写法正是 R4-43 的温床（必须走三态的 `as_bool`）。
7. **T2 的门禁必须在代码里**：`_freeze_probe` 的「kind 与 reason 两个都要比」
   以前只写在注释里（代码允许缺省、缺了照样打「✅ 冻结成立」）。

⛔ 本判据**不检查金额对不对**，也不检查业务规则 —— 它只回答一件事：
**"读出来的这一格，各处认的是不是同一个东西"。**

用法：
    python _tools/qa/_check_prod_shape.py            # 详细
    python _tools/qa/_check_prod_shape.py --check    # 必跑模式（一行结论）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "_tools" / "ops"
QA = ROOT / "_tools" / "qa"
STATUS = OPS / "_canary_status.py"
FREEZE = OPS / "_freeze_probe.py"
RUNTIME = ROOT / "backend/app/core/pricing_runtime.py"
ORDER_MONEY = ROOT / "backend/app/services/order_money.py"

#: 扫到的键路径 → **为什么这一处必须知道"认不出"意味着什么**。
#: ⛔ 登记的是**消费者**（谁在读），不是"有哪些键"—— 同一个键被三处读就有三处要交代后果。
READ_REGISTRY: dict[str, str] = {
    "pricing.kind": "窗口分类 + 冻结实验都要它 —— 认不出时**不许**当成 legacy_client"
                    "（那会把「换了算法」读成「按老路走」）",
    "pricing.reason": "退回原因统计 —— 认不出时**不许**当成 fallback"
                      "（那会把「新原因码」读成「契约又失败了」）",
    "pricing.resolution": "「这一次走的是哪条路」—— 认不出时**不许**并进 not_in_canary"
                          "（那会把「冻结」读成「没抽中」，冻结就永远验不了）",
    "pricing.agreed": "出口条件 ⑥ 的一半 —— 认不出时**不许**当成 False（R4-43：计数会恒为 0）",
    "pricing.override": "出口条件 ⑥ 的另一半 —— 同上",
    "pricing.contract.name": "契约身份 —— 认不出时**不许**当成「没有契约」",
    "pricing.contract.version": "契约版本 —— 同上",
    "at": "窗口边界与「缺口新不新」都按它排序 —— 认不出时**不许**参与排序"
          "（否则一笔脏时间会把整批样本挤出窗口）",
}

#: 生产 SQL 判据要、而**代码侧判据没要**的键 → 理由（⛔ 必须仍然成立，且有锚点）。
#: 这是第 3 组唯一允许的差异形状：**差异本身要写下来**，而不是让它静默存在。
PROD_GATE_EXEMPT: dict[str, str] = {
    "at": "定价时刻 —— 生产拿它当**窗口边界**（按时间切样本）；代码侧 §五 P1-02c 问的是"
          "「这个金额凭什么」，不含时间戳。⛔ 这是**已知的口径差**，不是漏判。",
}
#: 上面每一条理由的**锚点**（锚点没了说明代码变了，这条豁免要重新复核 —— 防化石）。
EXEMPT_ANCHORS: dict[str, str] = {
    "at": "freight_rule_snapshot, '$.at'",
}

_JSON_PATH = re.compile(r"json_extract\([^,]+,\s*'\$\.([A-Za-z0-9_.]+)'")


def scanned_paths() -> dict[str, list[str]]:
    """扫**全部** `_tools/` 脚本里出现的键路径 → 路径 → 出处列表（清单自己算）。"""
    out: dict[str, list[str]] = {}
    for p in sorted(ROOT.joinpath("_tools").rglob("*.py")):
        for m in _JSON_PATH.finditer(p.read_text(encoding="utf-8")):
            out.setdefault(m.group(1), []).append(p.relative_to(ROOT).as_posix())
    return out


def resolution_set(src: str) -> tuple[set[str], bool]:
    """从 backend 源码抠出 `RESOLUTIONS` 的取值集合。

    ⚠️ 那里写的是**常量名**（`RESOLUTION_CONTRACT, …`），⛔ 不是字面量 ——
    第一版按 \\"字面量\\" 抠，抠出空集，于是"两边逐个相同"这条判据**永远红**。
    抠不出来时返回 `(空, False)`，让调用方**先喊**（⛔ 不是安静地全绿）。
    """
    m = re.search(r"RESOLUTIONS:\s*tuple\[str, \.\.\.\]\s*=\s*\(([^)]*)\)", src, re.S)
    if not m:
        return set(), False
    out: set[str] = set()
    for name in re.findall(r"[A-Z][A-Z_]+", m.group(1)):
        hit = re.findall(r"^" + re.escape(name) + r'\s*=\s*"([a-z_]+)"', src, re.M)
        out.update(hit)
    return out, True


def code_side_keys(src: str) -> set[str]:
    """代码侧"必须能恢复的键"= 那张表 **∪** 它真的 `_dig` 过的那些键。

    ⚠️ 只抠表是不够的：`v`（快照格式版本）不在表里，但代码侧确实核了它
    （`_dig(snap, ("v",)) == 1`）—— 只抠表会把它误判成"代码侧不管"。
    """
    out: set[str] = set()
    for mm in re.finditer(r"\(\(([^)]*)\),\s*\"", src):
        parts = re.findall(r'"([a-z_]+)"', mm.group(1))
        if parts:
            out.add(".".join(parts))
    for mm in re.finditer(r"_dig\([^,]*,\s*\(([^)]*)\)", src):
        parts = re.findall(r'"([a-z_]+)"', mm.group(1))
        if parts:
            out.add(".".join(parts))
    return out


def main() -> int:
    check = "--check" in sys.argv
    fails: list[str] = []
    passes = 0

    def ok(label: str, cond: bool, detail: str = "") -> None:
        nonlocal passes
        if cond:
            passes += 1
            if not check:
                print("  [OK]   " + label)
        else:
            fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))

    sys.path.insert(0, str(OPS))
    import _canary_status as cs  # noqa: E402

    status_src = STATUS.read_text(encoding="utf-8")
    freeze_src = FREEZE.read_text(encoding="utf-8")

    # ---------------------------------------------------------------- 1. 闭集对账
    if not check:
        print("== 1. 闭集：工具里的取值集合必须与 backend 的**逐个相同** ==")
    rt_src = RUNTIME.read_text(encoding="utf-8")
    backend_res, got_res = resolution_set(rt_src)
    ok("backend 的 RESOLUTIONS 抠得出来（抠不出说明改了写法，这条判据要跟着改）", got_res,
       "pricing_runtime.py 里没找到 RESOLUTIONS 的元组")
    ok("工具与 backend 的 resolution 闭集**逐个相同**（" + str(len(backend_res)) + " 个："
       + "/".join(sorted(backend_res)) + "）",
       bool(backend_res) and set(cs.RESOLUTIONS) == backend_res,
       "工具：" + str(sorted(cs.RESOLUTIONS)) + " vs 后端：" + str(sorted(backend_res)))
    ok("resolution 是**恰好四个**（加取值必须两边一起来）", len(set(cs.RESOLUTIONS)) == 4,
       str(cs.RESOLUTIONS))

    om_src = ORDER_MONEY.read_text(encoding="utf-8")
    m2 = re.search(r"FREIGHT_KIND_CONTRACTS:\s*dict\[str, dict\]\s*=\s*\{(.*?)\n\}", om_src, re.S)
    # ⚠️ 只认**顶层**键（4 个空格缩进）：不锚定的话会把嵌套的 name / version 也当成 kind
    backend_kinds = set(re.findall(r'^    "([a-z_]+)":\s*\{', m2.group(1), re.M)) if m2 else set()
    ok("backend 的 kind 集合抠得出来", bool(backend_kinds))
    ok("工具与 backend 的 kind 闭集**逐个相同**",
       bool(backend_kinds) and {cs.KIND_CONTRACT, cs.KIND_LEGACY} == backend_kinds,
       "工具：" + str(sorted({cs.KIND_CONTRACT, cs.KIND_LEGACY}))
       + " vs 后端：" + str(sorted(backend_kinds)))

    # ---------------------------------------------------------------- 2. 读取点登记
    if not check:
        print("")
        print("== 2. 读取点：每一处读生产快照的地方都要登记（清单自己算）==")
    found = scanned_paths()
    ok("扫到 " + str(len(found)) + " 个不同的键路径（下限 8：枚举失效时先喊，⛔ 不是安静地全绿）",
       len(found) >= 8, "扫到：" + str(sorted(found)))
    unregistered = sorted(set(found) - set(READ_REGISTRY))
    ok("没有**未登记**的读取点（新增一处读生产 JSON 必须登记它的后果）", not unregistered,
       "未登记：" + str(unregistered) + " ⇒ 写进 READ_REGISTRY 并说明「认不出时会发生什么」")
    ghost = sorted(set(READ_REGISTRY) - set(found))
    ok("登记表里没有**化石**（键已经没人读了）", not ghost, "已经扫不到：" + str(ghost))

    # ---------------------------------------------------------------- 3. 两份清单对账
    if not check:
        print("")
        print("== 3. 「必须能恢复的键」：生产判据 ⊆ 代码侧判据（差异必须写下来）==")
    prov_src = (QA / "_check_pricing_provenance.py").read_text(encoding="utf-8")
    code_keys = code_side_keys(prov_src)
    ok("代码侧那份清单抠得出来（" + str(len(code_keys)) + " 个键）", len(code_keys) >= 5,
       "抠到：" + str(sorted(code_keys)))
    prod_keys = set(cs.PROV_REQUIRED_KEYS)
    missing = sorted(prod_keys - code_keys - set(PROD_GATE_EXEMPT))
    ok("生产 SQL 判据要的键，代码侧要么也要、要么在豁免表里有理由", not missing,
       "两边都没交代：" + str(missing) + " ⇒ 生产在查一个代码侧根本不认的键（或反过来）")
    for k, _why in PROD_GATE_EXEMPT.items():
        anchor = EXEMPT_ANCHORS.get(k, "")
        ok("豁免「" + k + "」的理由仍然成立（锚点 " + repr(anchor[:26]) + "）",
           bool(anchor) and anchor in (status_src + prov_src),
           "锚点已经不在源码里了 —— 代码变了，这条豁免要重新复核（⛔ 不许留化石）")
    ok("豁免表里没有已经不存在的键（化石棘轮）",
       not sorted(set(PROD_GATE_EXEMPT) - prod_keys),
       "生产判据已经不查：" + str(sorted(set(PROD_GATE_EXEMPT) - prod_keys)))

    # ---------------------------------------------------------------- 4. 缺键判据的形状
    if not check:
        print("")
        print("== 4. 缺键的形状：NULL **与空串**都要算「缺」==")
    probe = cs.prov_missing_sql("v")
    ok("缺键判据覆盖 SQL NULL", "coalesce(" in probe, probe)
    ok("缺键判据覆盖**空串**（⛔ 只写 is null 时生产会报 100% 完整）",
       "= ''" in probe and "is null" not in probe, probe)
    ok("生产判据用的是**同一份键名**（SQL 由 PROV_REQUIRED_KEYS 生成，⛔ 不是手抄一串）",
       'PROV_REQUIRED_SQL = " or ".join(' in status_src and "PROV_REQUIRED_KEYS" in status_src)

    # ---------------------------------------------------------------- 5. 真的跑一遍形状矩阵
    if not check:
        print("")
        print("== 5. 形状矩阵：喂每一种形状，看它落哪个桶（⛔ 认不出的不许并桶）==")

    def one(res: str, kind: str = "legacy_client", reason: str = "ok",
            agreed: str = "(无)", override: str = "(无)") -> dict:
        return cs.four_way(cs.parse_decisions(
            ["DECISION|" + kind + "|" + reason + "|" + agreed + "|" + override + "|"
             + res + "|PricingContract|2|1"]))

    ok("resolution 四个合法值各自落各自的桶",
       [one(r)[r] for r in cs.RESOLUTIONS] == [1, 1, 1, 1])
    for bad in ("CONTRACT", "Contract", "unknown", "0", "null", "freeze"):
        f = one(bad)
        ok("⛔ resolution=" + repr(bad) + " 落 unknown（⛔ 不并进 not_in_canary / inferred）",
           f["unknown"] == 1 and f["not_in_canary"] == 0 and f["inferred"] == 0, str(f))
    f = one("", kind="FREIGHT_TEMPLATE")
    ok("⛔ kind 认不出时落 unknown（⛔ 不并按 kind 推断那一支）",
       f["unknown"] == 1 and f["contract"] == 0, str(f))
    f = one("", reason="")
    ok("⛔ reason 是空串时落 unknown（⛔ 空串 ≠ 缺：缺是「旧式快照」，空串是形状不对）",
       f["unknown"] == 1 and f["stale"] == 0, str(f))
    ok("缺的形状（占位符）仍然按「缺」处理（⛔ 修形状不许把老快照判成异常）",
       one("")["inferred"] == 1 and one("(无)")["inferred"] == 1)

    ok("resolution 缺口：缺口全在「有值的」之前 ⇒ 过（是 R4-36 的存量）",
       cs.resolution_cutover_ok(3, "2026-09-27T07:30:00", "2026-09-27T10:30:00")[0] is True)
    ok("resolution 缺口：⛔ 缺口出现在有值的**之后** ⇒ 不过（新的写入漏了这一格）",
       cs.resolution_cutover_ok(1, "2026-09-27T11:00:00", "2026-09-27T10:30:00")[0] is False,
       "把「单调切换」改成永远 True 的注入必须被这条抓住")
    ok("resolution 缺口：有缺、但一笔值都没有 ⇒ 不过（分不清是存量还是新漏）",
       cs.resolution_cutover_ok(3, "x", "-")[0] is False)
    ok("resolution 缺口：一笔都不缺 ⇒ 过", cs.resolution_cutover_ok(0, "-", "-")[0] is True)

    ok("as_bool 三态：1/0/true/false/True/TRUE/yes/on ⇒ 都是布尔",
       [cs.as_bool(v) for v in ("1", "0", "true", "false", "True", "TRUE", "yes", "on")]
       == [True, False, True, False, True, True, True, True])
    ok("as_bool 三态：认不出 ⇒ None（⛔ **不是 False** —— R4-43 就是把它当成了 False）",
       [cs.as_bool(v) for v in ("2", "", "(无)", None, "null")] == [None] * 5)

    def det(res: str, agreed: str, override: str) -> tuple:
        ds = cs.parse_decisions(["DECISION|freight_template|ok|" + agreed + "|" + override
                                 + "|" + res + "|PricingContract|2|1"])
        _c, a, o, n = cs.contract_detail(ds)
        return a, o, n

    ok("⑥ 认得出 true/false（生产形状）", det("contract", "true", "false") == (1, 0, 0))
    ok("⑥ 认得出 1/0（自检形状）", det("contract", "1", "0") == (1, 0, 0))
    ok("⑥ 认不出时**单独成数**（⛔ 不是「0 笔相等、0 笔改过」这种看不出来的假绿）",
       det("contract", "2", "2") == (0, 0, 1))
    ok("⑥ 的人群 = 窗口的契约支（⛔ frozen 的契约单不算进 ⑥）",
       det("frozen", "1", "0") == (0, 0, 0))

    # ---------------------------------------------------------------- 6. 不许内联手写布尔集合
    if not check:
        print("")
        print("== 6. 布尔那两格只许走 as_bool（⛔ 内联字面量正是 R4-43 的温床）==")
    INLINE = re.compile(r'in \(\s*"1",\s*"true"|in \(\s*"0",\s*"false"')
    for path, src in (("_canary_status.py", status_src), ("_freeze_probe.py", freeze_src)):
        hits = [ln.strip() for ln in src.splitlines() if INLINE.search(ln.split("#", 1)[0])]
        ok(path + " 里没有内联手写的布尔集合（走三态 as_bool）", not hits, str(hits[:2]))

    # ---------------------------------------------------------------- 7. T2 的门禁在代码里
    if not check:
        print("")
        print("== 7. T2「两个都比」的门禁必须在**代码里**，⛔ 不在注释里 ==")
    ok("_freeze_probe 有一个可测的纯函数 freeze_verdict", "def freeze_verdict(" in freeze_src)
    ok("⛔ 没有「reason 可缺省就跳过」的写法（写在注释里的门禁不是门禁）",
       "if expect_reason and" not in freeze_src,
       "又出现可缺省比对了 —— 那样只比 kind 也会打「✅ 冻结成立」")
    ok("它自己有 --selftest（工具不许自己测自己都没有）", "def selftest(" in freeze_src)

    if check:
        print(("✅" if not fails else "❌")
              + " 生产形状：" + str(len(READ_REGISTRY)) + " 个读取点已登记，"
              + "闭集与 backend 一致，缺键判据覆盖 NULL+空串，形状矩阵 " + str(passes) + " 项"
              + ("" if not fails else "；" + str(len(fails)) + " 项不通过"))
    if fails:
        print("")
        print("❌ " + str(len(fails)) + " 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    if not check:
        print("")
        print("✅ 全部 " + str(passes) + " 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
