"""货主 / 批发商的 AI 工作流（FEAT-0020）：**他们也有自己那几条「一条龙」的活**。

## 用户口径（2026-10-11 本会话，逐字）
> 「为什么我们的货主或者批发商他的 AI 没有对应的技能和工作流呢，也是要具备的哦」

在此之前，`AiWorkflows.ALL` 里只有两条**派单员专属**的（对账 / 批量调价）—— 货主与批发商
一条都没有。本单补上：货主 5 条（下单 / 查单 / 账本小结 / 退货申请 / 改联系信息）、
批发商货主再多 1 条（改自己那一本下游价）。

## 为什么这条必须有机器的判据（每一处坏了都不报错、不崩、单测也可能全绿）
1. **角色写错 = 一条永远选不中的链**：`roles` 少写一个角色，那条工作流在提示词里还在、
   工具 enum 里还在，但**只有别人能用**；用户说那句话时模型认不出来，静默失效。
2. **交棒的写动作不在这个角色的白名单里 = 用户点了确认被 403**：这是本仓明确列出的
   最坏一类 bug（「能看见但一定失败」）。旧的两条之所以只给派单员，就是因为
   `ledger.sync_delivered` / `price_rules.batch` 不在货主白名单里 —— 补链时最容易踩的就是它。
3. **批发商那条碰错价 = 钱**：`shipper_price.*` 是「我卖给下游该收多少钱」（他自己那本账），
   `price_rules.*` 是「公司给他的批发商专属价」（只有派单员能改）。长得像，后果完全不同。
4. **只读那条配了卡 = 让模型去问一件不存在的事**：查单到哪了 / 本月账本小结**没有下一步要改的
   东西**，给了 `nextAction`，模型就会问「要不要发一张确认卡」，而那张卡该写什么、点了会改什么，
   谁都答不上来。
5. **步骤的 action 不在读白名单里 = 跑到一半被权限门挡掉**（结论只写了一半）。
   读门与写门是**两个门**，各自都要过。
6. **提示词里又抄一份清单**（角色提示词手写「货主能跑这几条」）= 加一条工作流就漏一次，
   与 `AiRolePrompt` 的既有规矩（能力清单必须算出来）同一条。
7. **工具 schema 不再按角色裁**：货主的模型会看到派单员那两条 id，试了才发现不行。
8. **判据自己空转**：清单指向不存在的文件、反验脚本失踪、FEAT-0020 文书缺节、
   登记簿 / 工作声明被改名。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
上面没有一条是类型属性：`roles` 是 `Set<AiRole>`，**少一个成员照样编译**；
`nextAction` 是 `String?`，写 `null` 与写一个 id 同型；「这条动作在不在某个角色的白名单里」
是**跨文件的集合关系**（`SHIPPER_ACTIONS` 在另一个文件、另一个维度）；「只读不发卡」
是**运行时分支**；「提示词里的清单一律算出来」更是源码结构上的事。
类型系统、Kotlin 编译器、单测都拦不住其中任何一条 —— 判据只能落在源码结构上，
再配反向验证 `_reverse_verify_shipper_ai_workflows.py`（逐条弄坏一次，看它真的变红）。

静默空转保护：MIN_KT（目录被搬走 / 一个 .kt 都没扫到也必须红）＋ 工作流条数下限。

用法：python _tools/qa/_check_shipper_ai_workflows.py
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AI = AND / "ai"
WORKFLOW = AI / "AiWorkflow.kt"
RUNNER = AI / "AiWorkflowRunner.kt"
TOOLS = AI / "AiTools.kt"
PROMPT = AI / "AiRolePrompt.kt"
CATALOG = ROOT / "docs/ai/ai_read_catalog.json"
TEST_REG = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWorkflowTest.kt"
TEST_RUN = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiWorkflowRunnerTest.kt"
DOC = ROOT / "docs/changes/FEAT-0020.md"
REG = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_shipper_ai_workflows.py"

sys.path.insert(0, str(ROOT / "_tools/ai"))
from _show_role_caps import shipper_whitelist  # noqa: E402
from _show_undo_status import action_constants, defined_actions  # noqa: E402

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 登记表里至少要有这么多条工作流（本单之后 = 8：派单员 2 ＋ 货主 5 ＋ 批发商 1）。
MIN_WORKFLOWS = 8

#: 三个角色各自该拿到哪几条（**逐字**：id 写错 = 那条永远选不中）。
WANT_DISPATCHER = ["ledger.reconcile", "price.batch"]
WANT_SHIPPER = ["order.place", "order.track", "ledger.monthly", "order.return_request", "order.contact"]
WANT_MEMBER = WANT_SHIPPER + ["price.mine"]

#: 只读的那两条（查完直接给结论、**不发卡**）。
READ_ONLY_IDS = ["order.track", "ledger.monthly"]

#: 本单要发的六个写动作（各自都必须在该角色的白名单里）。
WANT_NEXT = {
    "order.place": "orders.create",
    "order.return_request": "return_request.apply",
    "order.contact": "orders.update_contact",
    "price.mine": "shipper_price.set",
}

#: 变更单九节的标题（逐字照 _TEMPLATE.md）。
SECTIONS = [
    "## ① 六问",
    "## ② Must Change / Must Not Change",
    "## ③ Boundary（Core / Extension / Infrastructure / Presentation）",
    "## ④ Behavior Contract",
    "## ⑤ Data Contract",
    "## ⑥ CHG 专章",
    "## ⑦ 测试（四件事都要，缺一件就不算完整）",
    "## ⑧ 证据",
    "## ⑨ 关闭（六格）",
]


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print("  [OK]   " + label)
        else:
            self.fails.append(label + (" —— " + detail if detail else ""))
            print("  [FAIL] " + label + (" —— " + detail if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is not None, "没找到 " + repr(pattern))

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text, re.M)
        self.ok(label, m is None, "命中：" + repr(m.group(0)) if m else "")


def code_only(t: str) -> str:
    """去掉块注释与行注释（保留换行数）。KDoc 里也写着 `nextAction` 这些字样，判据只认代码。"""
    t = re.sub(r"/\*[\s\S]*?\*/", lambda m: chr(10) * m.group(0).count(chr(10)), t)
    return re.sub(r"//[^\n]*", "", t)


def read(p: Path) -> str:
    if not p.exists():
        msg = "找不到文件：" + str(p) + "（被改名/搬走了？这条判据要跟着改）"
        print(msg)
        raise SystemExit(msg)
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def workflow_blocks(src: str) -> list[dict]:
    """把 `val X = AiWorkflow( … )` 那一块块抠出来（**按括号配对扫，且跳过字符串里的括号**）。

    为什么不逐行正则：一条工作流的参数里带着中文说明与「、」，还有 `setOf(AiRole.SHIPPER)`
    这种嵌套调用 —— 正则一定会漏掉后半截，而漏掉的后果是判据看着通过、其实没读全。
    """
    out: list[dict] = []
    for m in re.finditer(r"\n    val ([A-Z_0-9]+) = AiWorkflow\(", src):
        i, depth, instr, esc = m.end(), 1, False, False
        while i < len(src) and depth > 0:
            ch = src[i]
            if instr:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    instr = False
            else:
                if ch == '"':
                    instr = True
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
            i += 1
        out.append({"name": m.group(1), "body": src[m.end():i - 1]})
    return out


def parse_workflows(src: str, consts: dict[str, str], actions: dict[str, str]) -> list[dict]:
    ids = dict(re.findall(r'const val ([A-Z_0-9]+) = "([^"]*)"', src))
    out: list[dict] = []
    for b in workflow_blocks(src):
        body = b["body"]
        m = re.search(r"\bid = ([A-Z_0-9]+)", body)
        item = {
            "name": b["name"],
            "id": ids.get(m.group(1), m.group(1)) if m else "?",
            "cn": (re.search(r'\bcn = "([^"]*)"', body) or [None, "?"])[1],
            "shipper_role": "roles = SHIPPER_ROLES" in body,
            "member_only": "memberOnly = true" in body,
            "steps": re.findall(r'AiWorkflowStep\("([^"]+)", "([^"]+)"\)', body),
        }
        na = re.search(r"\bnextAction = ([^,\n]+),", body)
        raw = na.group(1).strip() if na else ""
        item["read_only"] = raw == "null"
        item["next"] = None
        if not item["read_only"]:
            cm = re.match(r"AiWrites\.([A-Z_0-9]+)$", raw)
            item["next"] = actions.get(cm.group(1), raw) if cm else raw
        item["ask_null"] = bool(re.search(r"\bask = null,", body))
        item["when"] = body[body.find("whenToUse"):body.find("paramsCn")] if "paramsCn" in body else ""
        out.append(item)
    return out


def main() -> int:
    c = Checker()
    wf = read(WORKFLOW)
    wf_code = code_only(wf)
    runner = read(RUNNER)
    runner_code = code_only(runner)
    tools_code = code_only(read(TOOLS))
    prompt = read(PROMPT)

    consts = action_constants()
    actions = defined_actions(consts)
    shipper = shipper_whitelist(consts)
    defined = set(actions.values())
    flows = parse_workflows(wf, consts, actions)
    by_id = {f["id"]: f for f in flows}

    kt = sorted(AND.rglob("*.kt"))

    print("== 0. 反空转：扫描本身得是活的 ==")
    c.ok("扫到 %d 个 .kt（下限 %d）" % (len(kt), MIN_KT), len(kt) >= MIN_KT)
    c.ok("解析出 %d 条工作流（下限 %d）" % (len(flows), MIN_WORKFLOWS), len(flows) >= MIN_WORKFLOWS)
    c.ok("货主白名单解析到 %d 个动作（解析挂了就会是 0）" % len(shipper), len(shipper) >= 8)

    print("\n== 1. 谁有哪几条：派单员 2 / 货主 5 / 批发商货主 6 / 认不出 0 ==")
    dispatcher_ids = [f["id"] for f in flows if not f["shipper_role"] and not f["member_only"]]
    shipper_ids = [f["id"] for f in flows if f["shipper_role"] and not f["member_only"]]
    member_ids = shipper_ids + [f["id"] for f in flows if f["member_only"]]
    c.ok("派单员那两条一字不变：" + "、".join(dispatcher_ids), dispatcher_ids == WANT_DISPATCHER,
         "期望 " + "、".join(WANT_DISPATCHER))
    c.ok("货主 5 条：" + "、".join(shipper_ids), shipper_ids == WANT_SHIPPER, "期望 " + "、".join(WANT_SHIPPER))
    c.ok("批发商货主 6 条（多一条改自己下游价）：" + "、".join(member_ids), member_ids == WANT_MEMBER,
         "期望 " + "、".join(WANT_MEMBER))
    c.ok("id 不重复（重复的那条永远选不中）", len({f["id"] for f in flows}) == len(flows))
    # ALL 是**登记表**：解析出来的块与它必须一一对上（漏一条 = 工具 enum 里没有它、提示词里也没有）。
    all_block = re.search(r"val ALL: List<AiWorkflow> = listOf\(([\s\S]*?)\n    \)", wf_code)
    listed = re.findall(r"\b([A-Z_0-9]+),", all_block.group(1)) if all_block else []
    names = {f["name"]: f["id"] for f in flows}
    c.ok("ALL 里列的与解析出来的块一模一样（顺序也一样）：" + "、".join(listed),
         [names.get(n) for n in listed] == [f["id"] for f in flows],
         "ALL = " + str(listed))
    c.present("认不出角色 = 一条都不给（与工具白名单同一条 fail-closed）", wf_code,
              r"val role = actor\?\.role \?: return emptyList\(\)")
    c.present("批发商那条标了 memberOnly（普通货主不该有它）", wf_code, r"memberOnly = true,")
    c.present("memberOnly 只对批发商货主放行（!memberOnly 或 member）", wf_code, r"\(!it\.memberOnly \|\| member\)")

    print("\n== 2. 只读那两条：查完直接给结论，**不发卡** ==")
    read_only = [f["id"] for f in flows if f["read_only"]]
    c.ok("只读的就这两条：" + "、".join(read_only), read_only == READ_ONLY_IDS, "期望 " + "、".join(READ_ONLY_IDS))
    for i in READ_ONLY_IDS:
        f = by_id.get(i)
        if f is None:
            c.ok("登记表里有 " + i, False, "没解析到这一条")
            continue
        c.ok(i + " 没有交棒动作（有卡就会去问要不要发卡）", f["next"] is None, str(f["next"]))
        c.ok(i + " 没有要问的那一句", f["ask_null"])
        c.ok(i + " 的 whenToUse 写明「只读」（模型才敢照实说）", "只读" in f["when"])
    c.present("执行器里有一个**只读出口**", runner_code, r"private fun readOnlyOut\(")
    body = runner_code[runner_code.find("private fun readOnlyOut("):]
    body = body[:body.find("\n    private fun ") if "\n    private fun " in body else len(body)]
    c.ok("只读出口里不带交棒（没有 nextJson / next / ask）",
         "nextJson" not in body and 'put("next"' not in body and 'put("ask"' not in body)
    c.ok("只读那两条走的就是这个出口（≥2 处 return readOnlyOut）", runner_code.count("return readOnlyOut(") >= 2,
         "实测 %d 处" % runner_code.count("return readOnlyOut("))
    c.present("⛔ 只读工作流走到交棒那一步就当场抛（别静默发一张空卡）", runner_code,
              r'wf\.nextAction\s*\n\s*\?: error\("只读工作流没有交棒动作')

    print("\n== 3. 交棒的写动作必须在这个角色的白名单里（点了确认不许 403） ==")
    for f in flows:
        if f["read_only"]:
            continue
        want = WANT_NEXT.get(f["id"])
        if want is not None:
            c.ok(f["id"] + " 交棒给 " + want, f["next"] == want, "实际 " + str(f["next"]))
        pool = shipper if (f["shipper_role"] or f["member_only"]) else defined
        c.ok("「" + f["cn"] + "」要发的「" + str(f["next"]) + "」在这个角色的写白名单里",
             f["next"] in pool, "白名单里没有它")
    price = by_id.get("price.mine", {})
    c.ok("批发商那条只动 shipper_price.*（他自己那本下游账）",
         str(price.get("next", "")).startswith("shipper_price."), str(price.get("next")))
    c.ok("⛔ 不碰派单员那条批发商专属价（price_rules.*）",
         "price_rules" not in str(price.get("next", "")) and "price_rules" not in json.dumps(price.get("steps", []), ensure_ascii=False))

    print("\n== 4. 每一步的 action 都在这个角色的读白名单里（读门与写门是两个门） ==")
    cat = json.loads(read(CATALOG))
    readable: dict[str, dict[str, bool]] = {}
    for a in cat["actions"]:
        fid = a["module"] + "." + a["action"]
        for r in a["roles"]:
            readable.setdefault(r, {})[fid] = bool(a.get("member_only"))
    for f in flows:
        if not (f["shipper_role"] or f["member_only"]):
            continue
        for title, action in f["steps"]:
            c.ok("「" + f["cn"] + "」的步骤「" + title + "」= " + action + " 货主真能读", action in readable.get("shipper", {}))
            if f["member_only"]:
                c.ok("  ↑ 它是批发商专属的表（普通货主读不到，那条链也只给他）",
                     readable.get("shipper", {}).get(action) is True)

    print("\n== 5. 角色提示词：清单**算出来**，不是手写 ==")
    c.present("进 AI 时按角色算工作流清单", prompt, r"AiWorkflows\.forActor\(actor\)")
    c.present("有那一段「一条龙」的活", prompt, r"【你手上那几条「一条龙」的活")
    c.present("每条工作流都把 whenToUse 念给模型（它才认得出用户那句话）", prompt, r"w\.whenToUse")
    c.present("只读的那些要写明「不发卡」", prompt, r"没有确认卡")
    for i in WANT_SHIPPER + ["price.mine"]:
        # 提示词里出现的是 **id**（`w.id` 拼出来的），所以只查代码里有没有手抄的 id 清单。
        c.absent("⛔ 提示词里不许手抄 id（" + i + "）—— 加一条就漏一次", prompt, re.escape('"' + i + '"'))

    print("\n== 6. 工具 schema 按角色裁（三处同源：说明 ＋ enum ＋ 执行前的门） ==")
    c.present("run_workflow 走动态 spec", tools_code, r"RUN_WORKFLOW -> runWorkflowSpec\(actor\)")
    c.present("动态 spec 里按角色算清单与 enum", tools_code, r"AiWorkflows\.forActor\(actor\)")
    c.present("执行前的门用同一份判据", tools_code, r"if \(!AiWorkflows\.allows\(actor\(\), wf\.id\)\) \{")
    c.absent("⛔ 静态 SCHEMAS 里不许再抄一份 RUN_WORKFLOW（那是第二份会走散的清单）", tools_code,
             r"RUN_WORKFLOW to buildJsonObject \{")

    print("\n== 7. 单测：登记表与执行器都钉住了 ==")
    t_reg = read(TEST_REG)
    t_run = read(TEST_RUN)
    for name in ["八条工作流都在登记表里", "只读工作流不发卡", "写白名单", "认不出角色就一条都不给", "第 13 条"]:
        c.present("登记表单测有这一档：" + name, t_reg, re.escape(name))
    c.present("登记表单测钉住「每条 nextAction 都在白名单里」", t_reg, r"AiWrites\.allows\(a, action\)")
    c.present("登记表单测钉住 memberOnly 那一维", t_reg, r"memberOnly \|\| it\.memberShipper")
    c.present("执行器单测钉住「只读工作流没有 next/ask」", t_run, r"只读工作流不许有 next")
    c.present("执行器单测钉住 PATCH 语义（没点名的栏一个字都不带）", t_run, r"没点名的那几栏一个字都不许带")
    c.present("执行器单测钉住「改下游价不认百分比」", t_run, r"改下游价不认百分比")

    print("\n== 8. 文书与反验：齐不齐 ==")
    doc = read(DOC)
    for s in SECTIONS:
        c.ok("FEAT-0020.md 有这一节：" + s, s in doc)
    c.present("本单编号写在文书里", doc, r"FEAT-0020")
    c.present("文书里留了用户原话", doc, r"也是要具备的哦")
    c.present("登记簿里有本单", read(REG), r"FEAT-0020")
    c.present("工作声明里有本单", read(CLAIM), r"FEAT-0020")
    c.ok("反验脚本在（" + REVERSE.name + "）", REVERSE.exists())
    c.present("反验脚本自己也写了 R4 边界说明", read(REVERSE), r"R4-BOUNDARY-JUSTIFICATION:")

    print("\n" + "=" * 60)
    if c.fails:
        print("❌ %d/%d 项没通过：" % (len(c.fails), len(c.fails) + c.passes))
        for f in c.fails:
            print("   - " + f)
        return 1
    print("✅ 全部 %d 项通过：货主 5 条 / 批发商 6 条 / 派单员 2 条，只读的不发卡，" % c.passes)
    print("   每条交棒的写动作都在**对应角色**的白名单里，步骤也都在这角色能读的表里。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
