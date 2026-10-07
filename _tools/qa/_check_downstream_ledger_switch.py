# -*- coding: utf-8 -*-
"""「我的 → 管下游的账」那颗开关（CHG-0076 / 台账 L-39，2026-10-07）。

## 用户口径（原话 ref m01547）
「就是他在那个**我的**里面加一个**按钮**……因为有些批发商他可能**不想让我们去管他的账**，
所以我们就给一个功能，**开启**这个按钮：他那个我的账本就会显示**别人欠他的钱**……
如果**关闭**了的话，他就**没有这些功能**，他这个账本**只显示他欠我们的钱**。」
2026-10-07 定稿的四条口径（m13365）：① 两个读端点返空 ＋ 一个标记（⛔ 不是 403）
② 默认开（老库回填 true）③ 关掉连异常订单 / 核销一起收 ④ 派单员不给看也不代设。

## 为什么值得一条红线：这里是"两个布尔值被合成一个"最容易出事的地方
- `is_member` = **身份**（他是不是批发商：只有派单员能改，工作台那个「批发商」徽章靠它）；
- `downstream_ledger_enabled` = **他自己的偏好**（把不把这本账交给系统管）。

任何一处"看起来对"的偷懒写法，合起来都必错：
- 只按 `is_member` 判界面 ⇒ 关掉开关的批发商照样看到一段**全是 0.00 的「收入」**，还能点「核销」
  （后端 403 —— 他只会以为系统坏了）；
- 把开关写回 `is_member` ⇒ 关这本账**顺手把他降成普通货主**（徽章没了、整页结构变了）；
- 读端点返回 403 而不是"空 ＋ 标记" ⇒ **旧 App 弹报错**（他明明只是关了一个显示开关），
  而只看空列表又分不清"关掉了"还是"本来就没有"。

## 判据（每条都对着上面四条口径）
1. 一列新列 ＋ `NOT NULL DEFAULT 1`（⛔ 默认 0 = 上线那一刻所有批发商的下游账突然消失）
   ＋ 迁移可重跑 ＋ 模型 `default=True` ＋ `core/schema_bootstrap.py` 里一次都不提它；
2. 读：汇总 `if is_member and downstream:`、出参带 `downstream_ledger_enabled`、
   核销列表在**查库之前** `return []`、读路上一道 403 都没有；
3. 写：三个写端点 `_require_member` 之后**紧跟** `_require_downstream`（恰好 3 处）＋ 403 文案给出路；
4. 只许他本人：`PATCH /users/me/downstream-ledger`（入参只有 `enabled`）、依赖是"货主"
   （⛔ 不是 `USER_MANAGE`）、普通货主 403、幂等不写日志、真改动写一条 `USER_UPDATE`、
   端点里从不给 `is_member` 赋值、`backend/app/api` 下只有两个文件提这一列；
5. 客户端：VM 的 `canManageDownstream`（两个条件）＋ 账本页五处闸门 ＋ 收入段那道三条件闸门逐字
   ＋「我的」页那一行（只给批发商画 / 状态常显 / 真的发请求）＋ 两个 DTO 默认 true；
6. 随动：`_check_ledger_pay_block_gate.py` 与其反验用的是**同一份**闸门文本。

## R3-BOUNDARY-JUSTIFICATION

R3-BOUNDARY-JUSTIFICATION: 这条**没法用边界消除** —— 这里并存着**两个都是 `bool` 的列**
（`is_member` 是身份、`downstream_ledger_enabled` 是他的偏好），类型系统对它们一视同仁，
而三种最像的错法**都能编译、能跑、界面看着正常**：只按 `is_member` 判界面（关掉开关的批发商
照样看到一段全是 0.00 的「收入」）、把开关写回 `is_member`（关一本账顺手把人降成普通货主）、
读端点返 403 而不是「空 ＋ 标记」（旧 App 弹报错）。
运行时那半边（关掉后收入侧恒 0、被拦的删除没真删）由后端单测
`backend/tests/test_downstream_ledger_switch.py` 与真机取证顶着；
静态这半边唯一能问的边界是「这一列在哪些文件里、跟谁比」—— 那就是这条判据本身。

用法：python _tools/qa/_check_downstream_ledger_switch.py
配套：python _tools/qa/_reverse_verify_downstream_ledger_switch.py（14 种破坏方式全被抓）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
# 剥注释的规则**只有一份**（在 `_check_hints.py` 里）：这里不另写一个近似版，
# 否则两处会慢慢长歪（一个认字符串字面量、一个不认），红线的结论就不可信了。
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACK = ROOT / "backend"
API = BACK / "app" / "api"
AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"

MIGRATION = BACK / "app" / "migrations" / "026_user_downstream_ledger.py"
MODEL = BACK / "app" / "models" / "user.py"
BOOTSTRAP = BACK / "app" / "core" / "schema_bootstrap.py"
SCHEMA_USER = BACK / "app" / "schemas" / "user.py"
SCHEMA_SETTLE = BACK / "app" / "schemas" / "shipper_settlement.py"
API_LEDGER = API / "v1" / "shipper_ledger.py"
API_USERS = API / "v1" / "users.py"
TESTFILE = BACK / "tests" / "test_downstream_ledger_switch.py"
CONFTEST = BACK / "tests" / "conftest.py"

DTO = AND / "data" / "remote" / "dto" / "Dtos.kt"
APIS = AND / "data" / "remote" / "api" / "Apis.kt"
REPO = AND / "data" / "repo" / "AppRepository.kt"
PVM = AND / "ui" / "profile" / "ProfileViewModel.kt"
PSCREEN = AND / "ui" / "profile" / "ProfileScreen.kt"
LVM = AND / "ui" / "shipper" / "ShipperLedgerViewModel.kt"
LSCREEN = AND / "ui" / "shipper" / "ShipperLedgerScreen.kt"

GATE_CHECK = ROOT / "_tools" / "qa" / "_check_ledger_pay_block_gate.py"
GATE_REV = ROOT / "_tools" / "qa" / "_reverse_verify_ledger_pay_block_gate.py"

DQ = chr(34)
NL = chr(10)

COLUMN = "downstream_ledger_enabled"
#: 收入段那道闸门（与 `_check_ledger_pay_block_gate.py` **同一份文本**）。
RECV_GATE = "if (vm.isMember && s?.isMember == true && s.downstreamLedgerEnabled) {"
#: VM 里那道界面闸门：身份 ＋ 他自己的偏好，两个条件都要。
VM_GATE = "val canManageDownstream: Boolean get() = isMember && downstreamEnabled"
#: 写端点上那两行必须挨着（身份那一道在前）。
TWO_GATES = "_require_member(current)" + NL + "    _require_downstream(current)"

FILES = [MIGRATION, MODEL, BOOTSTRAP, SCHEMA_USER, SCHEMA_SETTLE, API_LEDGER, API_USERS,
         TESTFILE, CONFTEST, DTO, APIS, REPO, PVM, PSCREEN, LVM, LSCREEN, GATE_CHECK, GATE_REV]


def readn(p: Path) -> str:
    """读成 LF（`read()` 保留 CRLF —— 判据里那些逐字文本是按 LF 写的）。"""
    return read(p).replace(chr(13) + NL, NL)


def code(p: Path) -> str:
    return strip_comments(readn(p))


def between(src: str, start: str, end: str) -> str:
    """取 start 与其后**第一个** end 之间的原文（找不到 start 就回空串）。"""
    i = src.find(start)
    if i < 0:
        return ""
    j = src.find(end, i + len(start))
    return src[i:] if j < 0 else src[i:j]


def main() -> int:
    c = Checker()

    c.section("0. 反空转（文件被搬走 / 被清空时要先喊，不许安静地全绿）")
    missing = [p.relative_to(ROOT).as_posix() for p in FILES if not p.exists()]
    c.ok("这批判据要读的文件都在", not missing, "缺：" + "、".join(missing))
    if missing:
        return 1

    mig = readn(MIGRATION)
    model = readn(MODEL)
    bootstrap = readn(BOOTSTRAP)
    schema_user = readn(SCHEMA_USER)
    settle = readn(SCHEMA_SETTLE)
    ledger = readn(API_LEDGER)
    users = readn(API_USERS)
    test = readn(TESTFILE)
    conftest = readn(CONFTEST)
    dto = code(DTO)
    apis = code(APIS)
    repo = code(REPO)
    pvm = code(PVM)
    pscreen = code(PSCREEN)
    lvm = code(LVM)
    lscreen = code(LSCREEN)
    c.ok("每一份都真的读到了内容（否则下面每一条都是空转）",
         min(len(mig), len(model), len(ledger), len(users), len(lscreen), len(pscreen)) > 500,
         "mig=%d model=%d ledger=%d users=%d lscreen=%d pscreen=%d"
         % (len(mig), len(model), len(ledger), len(users), len(lscreen), len(pscreen)))

    c.section("1. 一列新列 ＋ 默认开（口径 ②：老库回填 true）")
    c.ok("迁移 VERSION 与文件名一致（026）＋ NAME 逐字 " + DQ + "downstream_ledger" + DQ,
         "VERSION = 26" in mig and ("NAME = " + DQ + "downstream_ledger" + DQ) in mig)
    c.ok("ALTER 那一句逐字 BOOLEAN NOT NULL DEFAULT 1（⛔ 默认 0 = 上线那一刻下游账突然消失）",
         "ADD COLUMN {COLUMN} BOOLEAN NOT NULL DEFAULT 1" in mig)
    c.ok("可重跑：先判表在不在、再判列在不在（MySQL 的 DDL 隐式提交）",
         "if TABLE not in set(insp.get_table_names()):" in mig
         and ("if COLUMN in {c[" + DQ + "name" + DQ + "] for c in insp.get_columns(TABLE)}:") in mig)
    c.ok("模型那一列在、默认同样是 True（新库由 create_all 按模型建）",
         "downstream_ledger_enabled: Mapped[bool] = mapped_column(Boolean, default=True)" in model)
    c.ok("⛔ core/schema_bootstrap.py 里一次都不提它（两处都写 = 同一件事两个来源）",
         COLUMN not in bootstrap)
    c.ok("它与 is_member 是**两列**并列（身份 vs 偏好，缺一不可）",
         "is_member: Mapped[bool] = mapped_column(Boolean, default=False)" in model and COLUMN in model)
    c.ok("迁移 docstring 记了为什么必须默认 1（同 024 那条教训）",
         "默认 0 会让上线那一刻所有批发商的下游账" in mig)

    c.section("2. 两个读端点：关掉返空 ＋ 一个标记（口径 ①，⛔ 不是 403）")
    summary_fn = between(ledger, "def ledger_summary(", "@router.get(" + DQ + "/settlements")
    list_fn = between(ledger, "def list_settlements(", "effective_limit = limit or DEFAULT_SETTLE_LIMIT")
    c.ok("汇总端点只读一次开关：downstream = _downstream_enabled(current)",
         "downstream = _downstream_enabled(current)" in ledger)
    c.ok("收入侧闸门是两个条件：if is_member and downstream:",
         "if is_member and downstream:" in ledger)
    c.ok("出参带标记：downstream_ledger_enabled=downstream,",
         "downstream_ledger_enabled=downstream," in ledger)
    c.ok("核销列表：关掉 ⇒ 直接 return []（判在 effective_limit 之前 = 不查库）",
         "if not _downstream_enabled(current):" in list_fn and list_fn.rstrip().endswith("return []"),
         "早退没写在 effective_limit 之前 —— 关掉的人照样会被查一次库")
    c.ok("读路上一道 403 都没有（关掉 ≠ 报错：旧 App 见到 403 会弹错）",
         "_require_downstream" not in summary_fn and "_require_downstream" not in list_fn)
    c.ok("出参 schema 那一格默认 True（老后端 / 没拨过 = 今天的行为）",
         COLUMN + ": bool = True" in settle)
    c.ok("标记只有一处来源（汇总出参那一个），核销列表那边没有第二个标记位",
         ledger.count(COLUMN + "=downstream,") == 1)

    c.section("3. 三个写端点：身份那一道之后紧跟开关那一道（口径 ③）")
    c.ok("`_require_member(current)` 之后紧跟 `_require_downstream(current)`，恰好 3 处",
         ledger.count(TWO_GATES) == 3, "实际 %d 处" % ledger.count(TWO_GATES))
    c.ok("没有第四处调用（读端点 / 汇总端点都不许走这一道）",
         ledger.count("_require_downstream(current)") == 3,
         "实际 %d 处" % ledger.count("_require_downstream(current)"))
    c.ok("403 文案说清出路（「我的 → 管下游的账」＋ 先回去把它打开）",
         "你已经在「我的 → 管下游的账」里关掉了这本账" in ledger
         and "先回去把它打开" in ledger)
    gate_fn = between(ledger, "def _require_downstream(", "def _own_order(")
    c.ok("那一道闸自己带 docstring 说明为什么与 `_require_member` 必须都在",
         "必须都在" in gate_fn and "界面藏起来的东西就不是" in gate_fn)
    c.ok("兜底口径与迁移一致：getattr(..., True) = 没拨过 = 开着",
         ("getattr(current, " + DQ + COLUMN + DQ + ", True)") in ledger)

    c.section("4. 只有他本人能拨（口径 ④：派单员不给看也不代设）")
    ep = between(users, "@router.patch(" + DQ + "/me/downstream-ledger" + DQ + ",", "def list_users(")
    c.ok("端点逐字：@router.patch(" + DQ + "/me/downstream-ledger" + DQ + ", response_model=UserOut)",
         ("@router.patch(" + DQ + "/me/downstream-ledger" + DQ + ", response_model=UserOut)") in users)
    c.ok("依赖是「货主」而不是 USER_MANAGE（派单员不代设）",
         "current: User = Depends(require_roles(UserRole.SHIPPER))," in ep
         and "Depends(require_permission(" not in ep)
    din = schema_user[schema_user.find("class DownstreamLedgerIn(BaseModel):"):]
    c.ok("入参 schema 只有 enabled 一个字段（⛔ 没有 user_id：他只能拨自己的）",
         "enabled: bool" in din and "user_id: " not in din)
    c.ok("端点的入参就是这个 schema（不是 UserUpdate —— 那条路是派单员改别人）",
         "body: DownstreamLedgerIn," in ep)
    c.ok("普通货主拨不了：403 ＋ 文案说清「只有批发商」",
         "HTTP_403_FORBIDDEN" in ep and "只有批发商（高级货主）有下游这本账" in ep)
    c.ok("幂等：拨到同一档直接 return（审计里不许全是「开了又开」）",
         "if before == after:" in ep and "return _to_out(current, current)" in ep)
    c.ok("真改动写一条审计，字段名逐字 " + DQ + COLUMN + DQ,
         ("{" + DQ + "field" + DQ + ": " + DQ + COLUMN + DQ + ", " + DQ + "from" + DQ + ": before, "
          + DQ + "to" + DQ + ": after}") in ep)
    c.ok("复用既有动作枚举 USER_UPDATE（⛔ 不新加：每个动作要在 App 侧有中文名）",
         "action=OperationAction.USER_UPDATE," in ep)
    c.ok("⛔ 端点里从不给 is_member 赋值（关这本账 ≠ 把他降成普通货主）",
         "is_member = " not in ep, "端点里出现了给 is_member 赋值的写法")
    api_hits = sorted(p.relative_to(ROOT).as_posix() for p in API.rglob("*.py") if COLUMN in readn(p))
    c.ok("backend/app/api 下只有两个文件提这一列（写只有 /me 这一个入口）",
         api_hits == ["backend/app/api/v1/shipper_ledger.py", "backend/app/api/v1/users.py"],
         "实际：" + "、".join(api_hits))

    c.section("5. 客户端：我的页那颗开关 ＋ 账本那两道闸门")
    c.ok("VM 的界面闸门逐字（两个条件都要）：" + VM_GATE, VM_GATE in lvm)
    c.ok("标记来自 summary 那一次请求（不是另发一条 users/me —— 免得界面与服务端错位）",
         "downstreamEnabled = summary?.downstreamLedgerEnabled ?: true" in lvm)
    c.ok("默认 true（老后端 / 还没取到 = 今天的行为）",
         "var downstreamEnabled by mutableStateOf(true)" in lvm)
    c.ok("账本页五处以上都读 vm.canManageDownstream（抽屉手势 / 人员行 / 分组分支 / 撤销卡 / 收款状态 / 核销按钮）",
         lscreen.count("vm.canManageDownstream") >= 5,
         "实际 %d 处" % lscreen.count("vm.canManageDownstream"))
    c.ok("抽屉手势那一处逐字：gesturesEnabled = vm.canManageDownstream && !vm.showFlow",
         "gesturesEnabled = vm.canManageDownstream && !vm.showFlow" in lscreen)
    c.ok("收入段那道闸门逐字（与 `_check_ledger_pay_block_gate.py` 同一份文本）", RECV_GATE in lscreen)
    c.ok("账本页只有那一道闸门读开关值本身（别处一律走 canManageDownstream）",
         lscreen.count("s.downstreamLedgerEnabled") == 1,
         "实际 %d 处" % lscreen.count("s.downstreamLedgerEnabled"))
    c.ok("⛔ 界面没有退回「只看身份」的老写法（关掉的人会是满屏 0.00 的收入）",
         "if (s?.isMember == true) {" not in lscreen)
    row = between(pscreen, "if (vm.user?.isMember == true) {", "showChevron = false,")
    c.ok("那一行只给批发商画（普通货主点下去只会拿到 403）",
         ("title = " + DQ + "管下游的账" + DQ) in row)
    c.ok("状态回执常显（「已开启 / 已关闭」走 Text；Hint 只剩教法句那一处）",
         row.count("Hint(") == 1 and (DQ + "已开启" + DQ) in row and (DQ + "已关闭" + DQ) in row,
         "状态被挂到「提示」总开关上了 —— 关掉提示的人看不见自己拨的是哪一档")
    c.ok("那一格真的发请求（只改本机的话，老包 / AI / 直接打接口照样看得见这本账）",
         "vm.setDownstreamLedger(" in row)
    c.ok("还是他说的那个「按钮」（Switch ＋ 点整行都能拨）",
         "Switch(" in row and "onClick = { vm.setDownstreamLedger(" in row)
    c.ok("ProfileViewModel：防连点 ＋ 只认服务端回执（不做乐观更新）",
         "if (downstreamLedgerSaving) return" in pvm
         and "downstreamLedgerEnabled = me.downstreamLedgerEnabled" in pvm)
    # ⚠️ 两个 DTO 不在同一个文件里：UserDto 在 dto/Dtos.kt，ShipperLedgerSummaryDto 在 api/Apis.kt。
    c.ok("两个 DTO 都默认 true（UserDto ＋ ShipperLedgerSummaryDto）",
         dto.count("val downstreamLedgerEnabled: Boolean = true") == 1
         and apis.count("val downstreamLedgerEnabled: Boolean = true") == 1,
         "Dtos.kt %d 处 / Apis.kt %d 处"
         % (dto.count("val downstreamLedgerEnabled: Boolean = true"),
            apis.count("val downstreamLedgerEnabled: Boolean = true")))
    c.ok("接口逐字：@PATCH(" + DQ + "users/me/downstream-ledger" + DQ + ")（没有 userId 路径段）",
         ("@PATCH(" + DQ + "users/me/downstream-ledger" + DQ + ")") in apis)
    c.ok("请求体只有一个字段（⛔ 别顺手加 userId）",
         "data class DownstreamLedgerRequest(" in apis and "val enabled: Boolean," in apis)
    c.ok("AppRepository 走**全限定名**（本文件只 import dto 包；包名写错会 Unresolved reference）",
         "com.tapmoay.sorders.data.remote.api.DownstreamLedgerRequest(enabled)" in repo
         and "import com.tapmoay.sorders.data.remote.api" not in repo)

    c.section("6. 测试与随动")
    want_cases = ["返空但不是403", "数字原样回来", "三个写端点都403", "普通货主不许拨",
                  "派单员不许代设", "同一档不写日志"]
    miss = [k for k in want_cases if k not in test]
    c.ok("后端单测六个用例都在（口径① 读返空 / ② 回得来 / ③ 写 403 / ④ 只许本人 / 幂等不写日志）",
         not miss and test.count("def test_") >= 6, "缺：" + "、".join(miss))
    c.ok("conftest 的共用账号基线把它复位成 true（否则账本那几条既有断言会被打空）",
         COLUMN in conftest)
    c.ok("既有红线用的是**同一份**闸门文本（两处不许慢慢长歪）",
         RECV_GATE in readn(GATE_CHECK) and RECV_GATE in readn(GATE_REV))
    c.ok("那份红线自己也点明了为什么加第二个条件（CHG-0076）",
         "CHG-0076" in readn(GATE_CHECK))

    print()
    if c.fails:
        print("❌ %d / %d 项不通过：" % (len(c.fails), len(c.fails) + c.n_ok))
        for label, detail in c.fails:
            print("   - " + label + (" —— " + detail if detail else ""))
        return 1
    print("✅ 全过（%d 项）" % c.n_ok)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
