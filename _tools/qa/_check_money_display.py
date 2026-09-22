"""红线：金额**显示**口径 —— 末尾多余的 0 去掉（`56.70 → 56.7`、`87.00 → 87`，`56.77` 一位不少）。

用户 2026-09-22 原话：「把所有的那个关于金钱的那个显示…**有零的全省**…如果是 56.7 啊，就直接
这样子，不要 56.70…包括 87…不要写 87.00 了…但是如果账单是 **56.77** 的话…**是必须要有的**，
它不能直接把七给约掉了」。

## 这一页在防什么（每条都对应一种"不报错"的坏）

1. **三端各写一份显示口径**：安卓 `util/Money.kt::formatMoney`（157 处调用）、
   H5 `utils/formatMoney.ts::formatMoney2`（27 处）、后端 `services/money_text.py`。
   只改一处的表现是**同一屏上两种写法**（`¥87` 与 `¥87.00` 并排），谁也不会报错。
2. **显示口径漏进"值"那一侧**（本项目最贵的一类，全都不报错）：
   · 拿它去填**可编辑**的价框 → 用户没改价、价却真的变了（`12.3456 → 12.35`，2026-09-21 踩过）；
   · 拿它当**判据** → 收款页那个数永远与后端 `Decimal` 对不上，多行/多单时**永久收不了款**（P0-4）；
   · 拿它去改**接口出参** → `backend/tests/test_supplier_payables.py` 逐条钉着 `"1200.50"`。
3. **新的金额显示绕开漏斗**：`"¥" + 后端原始值` 直接印 —— 后端 `Decimal` 序列化是 `'12.5000'`，
   卡片上就会出现 `¥12.5000`（真机上抓到过「每单 ¥120.00」这种，见 §3）。
4. **AI 回复提示词还写着"金额保留两位小数"**：那等于把旧规则塞回模型嘴边，聊天里照旧 `¥87.00`。

清单**全部由脚本自己算**（扫源码），不手写文件名单；每节都有数量判据防"解析失效后安静地什么都不查"。

用法：python _tools/qa/_check_money_display.py
配套：python _tools/qa/_reverse_verify_money_display.py（7 种破坏方式全被抓）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
ANDROID_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"
BACKEND = ROOT / "backend/app"
FRONTEND = ROOT / "frontend/src"

MONEY_KT = ANDROID / "util/Money.kt"
MONEY_TS = FRONTEND / "utils/formatMoney.ts"
MONEY_PY = BACKEND / "services/money_text.py"
AGENT_LOOP = ANDROID / "ai/AiAgentLoop.kt"

#: 安卓/H5 侧"这笔金额走的是显示口径"的标记。
FUNNEL = ("formatMoney(", "trimMoneyZeros(", "centsToMoney(", "money(", "moneyText(")

#: §3 里允许直接印 `¥` 的**非金额**用法（按内容片段认，不按行号 —— 行号会烂）。
#: 每条都要写清"为什么它不是一笔钱"。
NOT_MONEY: list[tuple[str, str]] = [
    ('prefix: String = "¥"', "共用组件 `MoneyText` 的默认前缀 —— 它自己那一行就把值过了 `formatMoney`"),
    ('"一车运费 ¥（可后补）"', "输入框的提示语，¥ 后面没有数字（值由用户自己填）"),
    ('"这一单的钱 ¥"', "同上：派单弹层里的提示语"),
    ('placeholder = "每单 ¥"', "同上：提示语"),
    ('placeholder = "运费 ¥"', "同上：提示语"),
    ('"¥（选填，留空记 0）"', "同上：提示语"),
    ('"运费 ¥（留空=待定）"', "同上：提示语"),
]

#: 后端"给人看的字"里允许不走 `money_text` 的（按内容片段认）。
BACKEND_TEXT_ALLOW: list[tuple[str, str]] = []


def _code_lines(src: str) -> list[tuple[int, str]]:
    """逐行 `(真实行号, 该行代码)`：字符串字面量原样保留，注释**内容**抹掉。

    ⚠️ 为什么不复用 `_check_hints.strip_comments`：它把块注释（`/** … */`，本仓库的 KDoc
    到处都是）的**换行也一起吃掉**，于是它给出的行号是"剥完之后"的行号 ——
    报出来会指到别的行去。**指错行比不指行更糟**（改的人会照着错行动手），
    所以这里逐行剥、行号一一对应。
    """
    out: list[tuple[int, str]] = []
    in_block = in_str = False
    for i, line in enumerate(src.splitlines(), 1):
        buf: list[str] = []
        j, n = 0, len(line)
        while j < n:
            c = line[j]
            if in_block:
                if line.startswith("*/", j):
                    in_block = False
                    j += 2
                else:
                    j += 1
                continue
            if in_str:
                buf.append(c)
                if c == "\\" and j + 1 < n:
                    buf.append(line[j + 1])
                    j += 2
                    continue
                if c == '"':
                    in_str = False
                j += 1
                continue
            if c == '"':
                in_str = True
                buf.append(c)
                j += 1
                continue
            if line.startswith("//", j):
                break
            if line.startswith("/*", j):
                in_block = True
                j += 2
                continue
            buf.append(c)
            j += 1
        out.append((i, "".join(buf)))
    return out


def _line_at(path: Path, lineno: int) -> str:
    """原始文件里第 [lineno] 行（用来核对"_code_lines 给出的行号真的指得到"）。"""
    lines = read(path).splitlines()
    return lines[lineno - 1] if 0 < lineno <= len(lines) else ""


def _kotlin_fun_body(src: str, name: str) -> str:
    """顶格 `fun <name>(` 到下一个顶格 `}` 之间的源码。

    ⚠️ **为什么要这么绕**：判据写成"整个文件里出现过 `trimEnd('0')`"是**假绿**的 ——
    `Money.kt` 里 `trimMoneyZeros` 也写着 `trimEnd('0').trimEnd('.')`，
    于是把 `formatMoney` 里的去零删掉，那条判据照样通过。
    2026-09-22 的反向验证第 ① 条就是这么抓到的（注入之后红线居然还是绿的）。
    """
    m = re.search(rf"^fun {re.escape(name)}\(", src, re.M)
    if not m:
        return ""
    end = src.find("\n}", m.end())
    return src[m.start(): end if end > 0 else len(src)]


def _py_fun_body(src: str, name: str) -> str:
    """`def <name>(` 到下一个顶格 `def `/`class `/装饰器 之间的源码（同上：钉在函数体里）。"""
    m = re.search(rf"^def {re.escape(name)}\(", src, re.M)
    if not m:
        return ""
    nxt = re.search(r"^(?:def |class |@)", src[m.end():], re.M)
    return src[m.start(): m.end() + (nxt.start() if nxt else len(src) - m.end())]


def _offenders(pattern: str, files, *, skip_path: str = "", must_contain: str = "") -> list[str]:
    """在 [files] 的**代码**里找 [pattern]（注释已剥掉），返回 `路径:行 → 原文`。

    [skip_path] 按**路径**跳过（不是按行内容 —— 否则"想放行某个文件"会变成"凡是提到它名字的行都放行"）。
    [must_contain] 有值时，只报"这一行里真的含它"的那些（用来表达"这一处必须过某个漏斗"）。
    """
    out: list[str] = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if skip_path and skip_path in rel:
            continue
        for i, code in _code_lines(read(p)):
            if not re.search(pattern, code):
                continue
            if must_contain and must_contain in code:
                continue
            out.append(f"{rel}:{i} → {code.strip()[:100]}")
    return out


def _js_code_lines(src: str):
    """H5 的**代码**行（只跳过**整行**注释：`//` `*` `/*` `<!--`）。

    为什么不引 `_check_client_contract.strip_js`：那是个脚本模块，为了跳注释去 import 它
    会把它的模块级代码一起跑起来。这里只需要"整行注释别算"这一条，够用且不会说谎。
    """
    for i, line in enumerate(src.splitlines(), 1):
        if line.strip().startswith(("//", "*", "/*", "<!--")):
            continue
        yield i, line


def main() -> int:
    if refuse_if_injecting("金额显示红线"):
        return 1

    c = Checker()
    kt_files = sorted(ANDROID.rglob("*.kt"))
    py_files = sorted(BACKEND.rglob("*.py"))

    # ── 0. 反空转 ─────────────────────────────────────────────────────────
    c.section("0. 反空转（文件/结构变了要先喊，而不是安静地什么都不查）")
    for p in (MONEY_KT, MONEY_TS, MONEY_PY, AGENT_LOOP):
        c.ok(f"{p.relative_to(ROOT).as_posix()} 在", p.exists())
    if not all(p.exists() for p in (MONEY_KT, MONEY_TS, MONEY_PY, AGENT_LOOP)):
        return 1
    c.ok(f"扫到的安卓源文件 >= 100 个（实际 {len(kt_files)}）", len(kt_files) >= 100)
    c.ok(f"扫到的后端源文件 >= 60 个（实际 {len(py_files)}）", len(py_files) >= 60)

    kt = strip_comments(read(MONEY_KT))
    ts = read(MONEY_TS)
    py = strip_comments(read(MONEY_PY))
    loop = strip_comments(read(AGENT_LOOP))

    # ── 1. 三端显示实现都去尾零 ───────────────────────────────────────────
    c.section("1. 三端显示口径都去尾零（少改一处＝同一屏两种写法）")
    # ⛔ 每条都钉在**那个函数体里**：整文件级的关键字会被同文件的另一个函数满足（假绿，
    #    反向验证第 ① 条实测抓到过）。
    fmt = _kotlin_fun_body(kt, "formatMoney")
    c.ok("找到 `formatMoney` 的函数体（不然后面几条都是在空转）", bool(fmt))
    c.ok("安卓 `formatMoney` 先按分四舍五入、再删末尾的 0 与小数点",
         "trimEnd('0').trimEnd('.')" in fmt and '"%.2f".format(' in fmt)
    c.ok("安卓进位仍走 `%.2f`（没换算法：任何一笔钱的数字都不许变）", '"%.2f".format(' in fmt)
    c.ok("安卓显式 `Locale.US`（默认语言是德语时 `%.2f` 会印成 `56,7`）",
         '"%.2f".format(Locale.US, v)' in fmt)
    c.ok("安卓负零摆正（`-0.001` 否则印成 `-0`）", '"-0"' in fmt)
    ts_fn = ts[ts.find("export function formatMoney2("):]
    c.ok("找到 H5 `formatMoney2` 的函数体", "export function formatMoney2(" in ts)
    c.ok("H5 `formatMoney2` 去尾零", re.search(r"replace\(/\\\.\?0\+\$/", ts_fn) is not None)
    c.ok("H5 找不到数就给 `0`（不是 `0.00`）", "return '0'" in ts_fn and "'0.00'" not in ts_fn)
    py_fn = _py_fun_body(py, "money_text")
    c.ok("找到后端 `money_text` 的函数体", bool(py_fn))
    c.ok("后端 `money_text` 去尾零", '.rstrip("0").rstrip(".")' in py_fn)
    c.ok("后端复用 `order_money.q2` 的进位（**不重写**第二份两位小数）",
         "from app.services.order_money import q2" in py and "quantize" not in py_fn)
    c.ok("后端负零摆正", '"-0"' in py_fn)

    # ── 2. ⛔ 值侧：一个字都不许动（反向约束 —— 防"顺手统一口径"）─────────
    c.section("2. ⛔ 值侧仍是两位小数（显示口径不许漏进判据/出参/输入框）")
    gtt = _kotlin_fun_body(kt, "OrderDto.goodsTotalText")
    c.ok("找到 `goodsTotalText` 的函数体", bool(gtt))
    c.ok("`goodsTotalText()` 仍是定点两位（收款页判据，去零就收不了款）",
         "goodsTotal().setScale(2, RoundingMode.HALF_UP).toPlainString()" in gtt)
    c.ok("`goodsTotalText` 的 KDoc 写明了它「是值、不许过显示口径」的身份",
         "不许过 [formatMoney]" in read(MONEY_KT))
    q2_fn = _py_fun_body(strip_comments(read(BACKEND / "services/order_money.py")), "q2")
    c.ok("后端 `q2` 仍 quantize 到 0.01 + ROUND_HALF_UP",
         'quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)' in q2_fn)
    sup_path = BACKEND / "api/v1/suppliers.py"
    if sup_path.exists():
        sup = strip_comments(read(sup_path))
        c.ok("供应商三个出参仍是 `:.2f` 字符串（接口出参＝值）",
             'def _money(v: Decimal | None) -> str:' in sup and ":.2f" in sup)
    else:
        # ⚠️ 这个文件属于另一个会话**未提交**的域（供应商/应付款）。红线不该因为
        #    "别人还没提交"而崩掉（换一份 checkout 就跑不了 = 检查白写），所以这里**跳过并说明**，
        #    而不是算成"通过"（算通过就成了永远绿的假判据）。
        print("  [--]   供应商出参文件不在（那个域还没提交）→ 这一条**跳过**，不算通过")
    rules = strip_comments(read(ANDROID / "core/InputRules.kt"))
    c.ok("金额**输入框**仍是「至多两位小数」（用户自己打的字不是显示）",
         "MONEY_DECIMALS" in rules and "take(maxDecimals)" in rules)
    arg = strip_comments(read(ANDROID / "ai/AiWriteArgs.kt"))
    c.ok("⛔ AI 写入链路的 `AiWriteArgs.money()` 仍是两位小数（它同时是发给后端的参数，"
         "且下游有 `== \"0.00\"` 比较）",
         "fun money(v: BigDecimal): String = v.setScale(2, RoundingMode.HALF_UP).toPlainString()" in arg)

    # ── 3. 清单自己算：安卓界面里的 `¥` 都必须过漏斗 ────────────────────────
    c.section("3. 清单自己算：`¥` 后面那个数必须走漏斗（绕开就是 `¥12.5000` 那种）")
    ui_files = [p for p in kt_files if "/ui/" in p.as_posix() or p.as_posix().endswith("util/Money.kt")]
    all_code = {p: _code_lines(read(p)) for p in ui_files}
    n_yen, bad, n_allow = 0, [], 0
    for p, lines in all_code.items():
        rel = p.relative_to(ROOT).as_posix()
        for i, code in lines:
            if "¥" not in code:
                continue
            n_yen += 1
            if any(f in code for f in FUNNEL):
                continue
            if any(snip in code for snip, _ in NOT_MONEY):
                n_allow += 1
                continue
            # 行号必须真的指得到：指错行比不指行更糟（改的人会照着错行动手）
            real = _line_at(p, i)
            drift = "" if code.strip()[:24] and code.strip()[:24] in real else "  ⚠️行号对不上原始文件"
            bad.append(f"{rel}:{i} → {code.strip()[:100]}{drift}")
    c.ok(f"界面里扫到 >= 80 处 `¥`（实际 {n_yen}，防解析失效后空转）", n_yen >= 80)
    c.ok(f"每一处 `¥` 都过了显示漏斗（{len(bad)} 处绕开；另有 {n_allow} 处是标签/占位符，见表）",
         not bad, "；".join(bad[:20]) + "\n     （绕开漏斗＝把后端 `12.5000` 直接印出来）")
    stale = [
        snip for snip, _ in NOT_MONEY
        if not any(snip in code for lines in all_code.values() for _, code in lines)
    ]
    c.ok(f"放行表里每条都还命中得到（防化石：{len(stale)} 条已失效）", not stale, "；".join(stale))

    # ── 3b. AI 层：卡片文字去尾零，进 payload 的仍是两位小数 ────────────────
    c.section("3b. AI 层：`moneyText`（卡片文字）与 `money`（值）的分工不许混")
    arg_kt = strip_comments(read(ANDROID / "ai/AiWriteArgs.kt"))
    c.ok("`AiWriteArgs.moneyText` 在（两个重载：BigDecimal / 后端下发的 String?）",
         "fun moneyText(v: BigDecimal)" in arg_kt and "fun moneyText(raw: String?)" in arg_kt)
    c.ok("它复用全 App 那份显示口径（**不重写**去零逻辑）",
         "fun moneyText(v: BigDecimal): String = formatMoney(v.toPlainString())" in arg_kt
         and "fun moneyText(raw: String?): String = formatMoney(raw)" in arg_kt)
    c.ok("KDoc 写明了「`== \"0.00\"` 那段字符串比较会静默不成立」这条危险",
         '== "0.00"' in read(ANDROID / "ai/AiWriteArgs.kt"))
    # 清单自己算：全 ai/ 目录里，`AiWriteArgs.money(` 只许出现在"值"的形态上
    money_sites = [
        (p.relative_to(ROOT).as_posix(), i, code.strip())
        for p in sorted((ANDROID / "ai").glob("*.kt"))
        for i, code in _code_lines(read(p))
        if "AiWriteArgs.money(" in code
    ]
    value_forms = ('put("price", ', 'put("value", ', 'put("amount", ',
                   "val amount = AiWriteArgs.money(amountValue)",
                   "val fee = feeRaw?.let { AiWriteArgs.money(")
    wrong = [f"{f}:{i} → {code[:90]}" for f, i, code in money_sites
             if not any(v in code for v in value_forms)]
    # ⚠️ **不数个数**：`AiWriteArgs.money(` 的处数会随着别的域新增处理器而变（每加一个域就多一两处
    #    「值」），钉死个数等于"谁加功能谁红"。真正的判据是**形态**：剩下的每一处都必须是「值」。
    #    下界 4 是防"有人把值也全改成去零、于是这条判据空转"。
    c.ok(f"`AiWriteArgs.money(` 剩下的 {len(money_sites)} 处**每一处都是「值」的形态**"
         f"（进 payload / 参与比较），没有一处是印在卡片上的",
         4 <= len(money_sites) <= 12 and not wrong,
         f"实际 {len(money_sites)} 处；形态不对的：" + "；".join(wrong[:6]))
    n_text = sum(read(p).count("AiWriteArgs.moneyText(") for p in (ANDROID / "ai").glob("*.kt"))
    c.ok(f"卡片文字走 `moneyText` >= 40 处（实际 {n_text}，防「定义了没人用」或被改回去）", n_text >= 40)
    # ⛔ 哨兵比较：去零会让这几句提示**静默不显示**，所以比较必须留在两位小数那一侧。
    #    ⚠️ 其中两处在另一个会话**还没提交**的域里（供应商/预付款、预订单）—— 文件不在就**跳过并说明**，
    #       而不是让整个红线崩掉（崩了就"换一份 checkout 跑不了"＝检查白写）。
    SENTINELS = (
        ("ai/AiWriteSupplierHandlers.kt", 'if (after == "0.00") "（这一笔付清了）"'),
        ("ai/AiWriteOrderTemplateHandlers.kt", 'fee == "0.00" -> "0 元（免运费）"'),
        ("ai/AiWriteOrderHandlers.kt", 'if (o.amount != "0.00")'),
    )
    n_sent = 0
    for f, sentinel in SENTINELS:
        p = ANDROID / f
        if not p.exists():
            print(f"  [--]   哨兵比较「{sentinel[:26]}…」跳过（{f.split('/')[-1]} 不在：那个域还没提交）")
            continue
        n_sent += 1
        c.ok(f"哨兵比较还在（{f}）：{sentinel[:38]}…", sentinel in read(p))
    # 防退化：一个都没查到就说明这条判据在空转（`>= 1` 而不是 3 —— 别的域没提交时本来就只剩 1 个）
    c.ok(f"哨兵比较至少查到了文件（实际 {n_sent} 个；主工作区里是 3 个）", n_sent >= 1)
    revert_kt = strip_comments(read(ANDROID / "ai/AiRevert.kt"))
    c.ok("撤回卡的金额也走同一份显示口径（不自己 `setScale(2)`）",
         "formatMoney(raw)" in revert_kt and "n.setScale(2, java.math.RoundingMode.HALF_UP)" not in revert_kt)

    # ── 4. 清单自己算：后端"给人看的字"都必须过 money_text ─────────────────
    c.section("4. 清单自己算：后端生成给用户看的文案必须过 `money_text`")
    defs = [p.relative_to(ROOT).as_posix() for p in py_files if "def money_text(" in read(p)]
    c.ok(f"`money_text` 全后端**只有一处定义**（实际 {defs}）", defs == ["backend/app/services/money_text.py"])
    raw_yen = _offenders(r"¥\{", py_files, skip_path="money_text(")
    raw_yen = [x for x in raw_yen if "money_text(" not in x]
    c.ok(f"`¥{{…}}`（f-string 里的金额）全走 `money_text`（{len(raw_yen)} 处绕开）", not raw_yen,
         "；".join(raw_yen[:20]))
    n_yen_py = len(re.findall(r"¥\{money_text\(", "\n".join(read(p) for p in py_files)))
    c.ok(f"后端至少 4 处用户可见金额文案（实际 {n_yen_py}）", n_yen_py >= 4)
    # `{expr} 元` 这种写法：元前面的插值必须是 money_text（否则就是"固定工资 8000.00 元/月"）
    yuan = [
        x for x in _offenders(r"\{[^{}]*\}\s*元", py_files, skip_path="money_text.py")
        if "money_text(" not in x
        and not any(snip in x for snip, _ in BACKEND_TEXT_ALLOW)
    ]
    c.ok(f"`{{…}} 元` 的插值全走 `money_text`（{len(yuan)} 处绕开）", not yuan, "；".join(yuan[:20]))
    bad_f2 = _offenders(r":\.2f", py_files, skip_path="api/v1/suppliers.py")
    c.ok(f"`:.2f` 只允许出现在接口出参 `suppliers.py`（{len(bad_f2)} 处越界）", not bad_f2,
         "；".join(bad_f2[:20]))
    c.ok("私有 `_plain` 已收进 `money_text`（后端不许有第二份去零实现）",
         not _offenders(r"def _plain\(", py_files))

    # ── 5. H5 漏斗唯一 ────────────────────────────────────────────────────
    c.section("5. H5：金额显示只有 `formatMoney2` 一处")
    ts_files = sorted(FRONTEND.rglob("*.ts")) + sorted(FRONTEND.rglob("*.vue"))
    c.ok(f"扫到 H5 源文件 >= 30 个（实际 {len(ts_files)}）", len(ts_files) >= 30)
    fixed = [
        p.relative_to(ROOT).as_posix() for p in ts_files
        if any("toFixed(2)" in ln for _, ln in _js_code_lines(read(p)))
    ]
    c.ok(f"`toFixed(2)` 只允许在 `formatMoney.ts` 里（实际 {fixed}）",
         fixed == ["frontend/src/utils/formatMoney.ts"])
    n_ts = sum(read(p).count("formatMoney2(") for p in ts_files)
    c.ok(f"H5 至少 20 处走 `formatMoney2`（实际 {n_ts}）", n_ts >= 20)

    # ── 6. AI 回复提示词 + 单测钉着用户给的三个例子 ─────────────────────────
    c.section("6. AI 那边：提示词写新规则，单测钉住用户给的三个例子")
    c.ok("⛔ 提示词里不再写「金额保留两位小数」（否则聊天里照旧 `¥87.00`）",
         "金额保留两位小数" not in loop)
    c.ok("提示词写明了去尾零", "去掉末尾多余的 0" in loop)
    c.ok("提示词同时写了「一位都不能少」（防模型把 56.77 写成 56.7）",
         "一位都不能少" in loop and "56.77" in loop)
    mt = read(ANDROID_TEST / "util/MoneyTest.kt")
    for src, want in (("56.70", "56.7"), ("87.00", "87"), ("56.77", "56.77")):
        c.ok(f"安卓单测钉着 `formatMoney(\"{src}\") == \"{want}\"`",
             re.search(rf'assertEquals\("{re.escape(want)}", formatMoney\("{re.escape(src)}"\)\)', mt) is not None)
    bt = read(ROOT / "backend/tests/test_money_display.py") if (ROOT / "backend/tests/test_money_display.py").exists() else ""
    c.ok("后端单测在（钉「显示去零 / 值不动」两侧）", 'money_text("56.77")' in bt and "q2(" in bt)
    c.ok("后端单测也钉住了「值侧仍两位小数」", 'str(q2(Decimal("87"))) == "87.00"' in bt)

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {c.n_ok} 项通过，{len(c.fails)} 项失败：")
        for label, detail in c.fails:
            print(f"   - {label}" + (f"\n     {detail}" if detail else ""))
        return 1
    print(f"✅ 金额显示口径 {c.n_ok} 项全绿（三端同一条规则：显示去尾零、值一位不动）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
