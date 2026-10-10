"""反向验证 `_check_shipper_ai_workflows.py`（FEAT-0020）：逐条把红线弄坏一次，看判据**真的报红**。

判据自己也会说谎 —— 锚点写歪、文件读错、清单指向不存在的路径，都会让它"永远绿"。
这个脚本把判据里每一条**关键断言**对应的源码各改坏一次（一次只改一处），改完立刻跑判据，
要求它**非零退出**且输出里出现**那一条的标签文字**，跑完逐字节还原。

八条注入（覆盖本单最要紧的几件事）：
1. 只读那条被改成「也发卡」—— 模型会去问一件不存在的事；
2. 货主那条交棒的写动作换成白名单外的 —— 用户点了确认必被 403；
3. 把某条的 roles 改回只有派单员 —— 那条链永远选不中（静默失效）；
4. 批发商那条改成碰派单员的价（price_rules.*）—— 动了不该动的钱；
5. 从 ALL 里删掉货主第 5 条 —— 登记表少一条；
6. 认不出角色改成「给派单员那批」（fail-open）；
7. 工具 schema 不再按角色裁 —— 货主会看到派单员那两条；
8. 只读出口里偷偷带上交棒 —— 只读也开始发卡。

三条失效方式（写这个脚本时最该防的）：
1. **注入没生效**（锚点行被重排/改字了）⇒ 判据当然还是绿的，看着像"判据没抓到"。
   这里对每一处都先比对新旧文本，一样就报"锚点变了，请更新本脚本"。
2. **还原不干净** ⇒ 工作树里留半截改动。跑完按字节核对，不一致就强制写回并报红。
3. **判据整体塌了**（某个文件被改名 ⇒ 判据一开始就 SystemExit）⇒ 那也算"报红"，
   但它没证明**那一条**在检查。所以每一条都要求输出里出现**该条的标签关键词**。

R4-BOUNDARY-JUSTIFICATION: 只读 4 个文件、只**临时**改其中被注入的那一个（跑完立刻按字节还原），
不碰数据库、不碰网络、不跑 gradle。改动全部落在工作树里，且每一处都在 finally 语义里还原。

用法：python _tools/qa/_reverse_verify_shipper_ai_workflows.py
"""
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_shipper_ai_workflows.py"
AND = "android/app/src/main/java/com/tapmoay/sorders/"
WORKFLOW = AND + "ai/AiWorkflow.kt"
RUNNER = AND + "ai/AiWorkflowRunner.kt"
TOOLS = AND + "ai/AiTools.kt"


def sub(old: str, new: str) -> Callable[[str], str]:
    """把出现的 old 换成 new（出现 0 次时由主流程报"锚点变了"）。"""

    def fn(text: str) -> str:
        return text.replace(old, new)

    return fn


def drop_line(needle: str) -> Callable[[str], str]:
    """删掉含 needle 的那一行（连行尾换行一起删）。"""

    def fn(text: str) -> str:
        return "\n".join(ln for ln in text.split("\n") if needle not in ln)

    return fn


def in_workflow(const: str, old: str, new: str) -> Callable[[str], str]:
    """在某一条工作流的构造块**之内**替换（块按括号配对扫，跳过字符串里的括号）。

    为什么要这么细：`roles = SHIPPER_ROLES,` 与 `nextAction = null,` 在货主那几条里**长得一样**，
    整篇 replace 会一次改掉五条 —— 那样就不知道判据是被哪一处弄红的了。
    """

    def fn(text: str) -> str:
        m = re.search(r"\n    val " + const + r" = AiWorkflow\(", text)
        if not m:
            return text
        i, depth, instr, esc = m.end(), 1, False, False
        while i < len(text) and depth > 0:
            ch = text[i]
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
        block = text[m.end():i]
        if old not in block:
            return text
        return text[:m.end()] + block.replace(old, new, 1) + text[i:]

    return fn


CASES: list[tuple[str, str, Callable[[str], str], str]] = [
    ("① 只读那条被改成「也发卡」（模型会去问一件不存在的事）", WORKFLOW, in_workflow("TRACK_ORDER", "        nextAction = null,\n        ask = null,", "        nextAction = AiWrites.ORDERS_CREATE,\n        ask = \"要不要我发一张确认卡？\","), "只读的就这两条"),
    ("② 货主那条交棒的写动作换成白名单外的（点了确认必被 403）", WORKFLOW, in_workflow("PLACE_ORDER", "nextAction = AiWrites.ORDERS_CREATE,", "nextAction = AiWrites.ORDERS_ASSIGN,"), "在这个角色的写白名单里"),
    ("③ 某条的 roles 改回只有派单员（那条链永远选不中）", WORKFLOW, in_workflow("FIX_CONTACT", "roles = SHIPPER_ROLES,", "roles = setOf(AiRole.DISPATCHER),"), "货主 5 条"),
    ("④ 批发商那条改成碰派单员的价（price_rules.* —— 动了不该动的钱）", WORKFLOW, in_workflow("MY_PRICES", "nextAction = AiWrites.SHIPPER_PRICE_SET,", "nextAction = AiWrites.PRICE_RULES_BATCH,"), "只动 shipper_price"),
    ("⑤ 从 ALL 里删掉货主第 5 条（登记表少一条 = 工具 enum 里没有它）", WORKFLOW, drop_line("        FIX_CONTACT,"), "ALL 里列的与解析出来的块一模一样"),
    ("⑥ 认不出角色改成「给派单员那批」（fail-open）", WORKFLOW, sub("val role = actor?.role ?: return emptyList()", "val role = actor?.role ?: AiRole.DISPATCHER"), "认不出角色 = 一条都不给"),
    ("⑦ 工具 schema 不再按角色裁（货主会看到派单员那两条）", TOOLS, sub("AiWorkflows.forActor(actor)", "AiWorkflows.ALL"), "动态 spec 里按角色算清单与 enum"),
    ("⑧ 只读出口里偷偷带上交棒（只读也开始发卡）", RUNNER, sub('put("read_only", true)', 'put("read_only", true)\n        put("nexts", buildJsonArray { })'), "只读出口里不带交棒"),
]


def main() -> int:
    if not CHECK.exists():
        print("❌ 找不到判据：" + str(CHECK))
        return 1
    bad = 0
    for name, rel, fn, keyword in CASES:
        path = ROOT / rel
        before = path.read_bytes()
        r = None
        try:
            # 统一成 LF 再匹配：checkout 之后这些 .kt 会变成 CRLF（git 的 autocrlf），
            # 而注入里的锚点是按 LF 写的 —— 还原用的是 before 那份原始字节，逐字节不受影响。
            text = before.decode("utf-8").replace("\r\n", "\n")
            after = fn(text)
            if after == text:
                print("❌ 锚点变了（注入没生效），请更新本脚本：" + name)
                bad += 1
                continue
            path.write_bytes(after.encode("utf-8"))
            r = subprocess.run(
                [sys.executable, "-X", "utf8", str(CHECK)],
                cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        finally:
            path.write_bytes(before)
        if path.read_bytes() != before:
            print("❌ 还原不干净（已强制写回）：" + name)
            path.write_bytes(before)
            bad += 1
            continue
        out = ((r.stdout or "") + (r.stderr or "")) if r else ""
        if r is None or r.returncode == 0:
            print("❌ 判据没抓到（弄坏了还是绿的）：" + name)
            bad += 1
        elif keyword not in out:
            print("❌ 报红了，但不是因为这一条（缺关键字「" + keyword + "」）：" + name)
            bad += 1
        else:
            print("✅ " + name)
    print("")
    if bad:
        print("❌ %d/%d 条注入没被正确抓到" % (bad, len(CASES)))
        return 1
    print("✅ 全部 %d 条注入都被判据抓到，且工作树已逐字节还原" % len(CASES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
