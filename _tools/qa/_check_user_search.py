"""红线：**按「人」搜索只有一条规则，而且名册页必须打到服务端**（2026-09-19，用户点名）。

## 由来

用户原话（2026-09-19）：
「还有其他的比如说，**司机管理**啊**账户管理**啊。这些也要添加搜索键。
  然后这个搜索键可以根据他们的**名称**还有**电话号码**以及**电话号码的后 4 位**进行搜索」。

同一轮他还推翻了账本管理上一版的「搜索 + 多选 chip 墙」：
「假如客户非常多司机非常多，那用户要是一个一个去选的话，那要有多麻烦啊。
  **所有的账本你可以一个仪表盘的思维进行去构建**」。

## 这条规则会被写坏成什么样（都不是假想）

| 写坏的方式 | 表现 |
|---|---|
| 各页各写一份匹配（姓名 / 姓名+用户名 / 姓名+手机+车牌） | **同一件事三个答案**：账号管理搜得到、货主管理搜不到；用户只会觉得"系统坏了" |
| 名册页退回**本地过滤**手里这一页 | 第 501 个账号在客户端**根本不存在** → "没有这个账号" → 再建一个 → 撞手机号唯一约束 |
| 漏掉"后 4 位" | 用户按手机尾号报人（司机在路上只会报尾号）时搜不到 —— 这是**需求本身**没做 |
| 账本又长回"多选 chip 墙" | 账户一多，"找到要点的那几个"比看账本身还花时间（用户明确说这是"麻烦"） |

## 判据（清单**全部自己算**，不手写文件名）

1. **规则只有一处**：Android 全树 `fun matches(` 只在 `core/UserSearch.kt`；后端
   `%...%` 的姓名/手机号谓词只在 `app/core/user_search.py`（`users.py` / `customers.py` 必须调它）。
2. **名册页必须走服务端**：`/users` 一页上限 500（`X-Truncated`），所以四个名册页
   （司机 / 货主 / 批发商 / 账户管理）的搜索必须经 `usersPage(..., q =` 发出去。
3. **"按人搜索"的框全部走这条规则**：从源码算出所有"提示语里同时出现人（姓名/司机/货主…）
   与号码（手机/电话）"的搜索框，每一个都必须用 `SearchField(` 或直接引用 `UserSearch`；
   例外要在 `EXCLUDED` 里写明理由（键必须命中一个真框，防化石）。
4. **后 4 位真的能搜**：客户端是手机号子串匹配、后端是两侧 `like('%kw%')`，
   并且 `UserSearchTest` 里有"后 4 位"那一条（行为由单测钉住，这里只钉"实现方式没被换掉"）。
5. **账本不许退回挑选器**：`DispatcherLedgerScreen/ViewModel` 里不许再出现
   `selectedAccounts` / `selectedDrivers` 这类"一个一个去选"的状态。
6. **账本账户卡片必须带手机号**：没有它，"同名不同人"分不开、按手机号搜也没得搜。
7. 反空转：认出的搜索框 < 4 个、名册页 < 4 个时先报错，而不是安静地什么都不查。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：
   `_tools/qa/_reverse_verify_user_search.py`。

用法：python _tools/qa/_check_user_search.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
#: 复用兄弟红线里剥 Kotlin 注释的实现（保留行号），不抄第二份。
from _check_pagination_wiring import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
APP = ROOT / "backend/app"

USER_SEARCH_KT = ANDROID / "core/UserSearch.kt"
USER_SEARCH_PY = APP / "core/user_search.py"
COMPONENTS_KT = ANDROID / "ui/common/Components.kt"
LEDGER_SCREEN = ANDROID / "ui/dispatcher/DispatcherLedgerScreen.kt"
LEDGER_VM = ANDROID / "ui/dispatcher/DispatcherLedgerViewModel.kt"

#: 名册页（用户点名的两个 + 同一支实现的另两个）：它们的搜索**必须**打到服务端。
ROSTER_VMS = [
    ANDROID / "ui/dispatcher/UsersManageViewModel.kt",   # 司机 / 货主 / 批发商（同一支）
    ANDROID / "ui/dispatcher/AccountManageViewModel.kt",  # 账户管理
]

#: 故意**不**算"按人搜索"的框：提示语里同时出现**地址词**的，它的匹配范围里有地址文本，
#: 套上"只认姓名/手机号"的规则会让「按地址找线路」直接失效 —— 那是**另一条规则**（地址搜索）。
#: 用判据算而不是手写名单：手写名单会过期，而"哪些框在搜地址"从提示语上就能看出来。
_ADDRESS_WORD = r"(地址|线路|地点)"

MIN_PERSON_BOXES = 4
MIN_ROSTER_PAGES = 2
MIN_BACKEND_CONSUMERS = 2

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的判据要跟着改，不许静默跳过）")
    return io.open(p, encoding="utf-8", errors="replace").read()


def kt_sources() -> dict[Path, str]:
    return {p: strip_comments(read(p)) for p in sorted(ANDROID.rglob("*.kt"))}


def kotlin_decl_block(src: str, header: str) -> str:
    """取出 `header` 那个声明的**参数表**（从 `(` 到配平的 `)`，找不到就返回空串）。

    为什么需要它：`Dtos.kt` 里好几个类都有 `val phone`（`UserDto` 也有）。
    全文级判据会被别的类蒙混过去 —— 而"某个 DTO 悄悄少了这个字段"正是要抓的坏法。

    ⚠️ 不能按 `{` 找类体：`data class X(...)` 是**没有类体**的写法（本项目 DTO 全是这样），
       `find("{")` 会一路吃到后面某个类的花括号，把整段都当成这一个类。
    """
    i = src.find(header)
    if i < 0:
        return ""
    j = src.find("(", i)
    if j < 0:
        return ""
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "(":
            depth += 1
        elif src[k] == ")":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    return src[i:]


#: 「按人搜索框」的判据：提示语里**同时**出现"人"和"号码"这两个词族。
_PERSON_WORD = r"(姓名|名字|司机|货主|批发商|账户|账号|收货人|联系人)"
_PHONE_WORD = r"(手机|电话)"
#: `placeholder` 后面那一段里出现的字符串字面量。
#  ⚠️ 不能只匹配 `placeholder = "…"`：真源码里有 `placeholder = when (tab) { 0 -> "搜…" }`
#     （地址页与下单页就是这么写的）—— 只认等号的话那两页会**从判据里消失**，
#     检查看着绿、其实没查它们。
_PLACEHOLDER_AT = re.compile(r"placeholder\s*=")
_QUOTED = re.compile('"([^"]*)"')
#: `placeholder = com.…UserSearch.HINT` 这种**引用同源常量**的写法也要认出来。
_PLACEHOLDER_REF = re.compile(r"placeholder\s*=\s*((?:com\.)?[\w.]+)\s*[,)]")


def person_search_boxes(src: str) -> list[str]:
    """这份源码里的「按人搜索框」。

    两类都算：
    · `SearchField(` 调用 —— 共享组件本身就是"按人搜索"那一份（提示语与清空按钮同源）；
    · 提示语里**同时**提人和号码、且**不提地址**的框（含引用 `UserSearch.HINT` 的写法）。
    """
    out: list[str] = []
    if re.search(r"(?<!fun )SearchField\(", src):
        out.append("SearchField")
    for m in _PLACEHOLDER_AT.finditer(src):
        for qm in _QUOTED.finditer(src[m.end(): m.end() + 240]):
            text = qm.group(1)
            if re.search(_ADDRESS_WORD, text):
                continue  # 地址搜索是**另一条规则**（见 [_ADDRESS_WORD] 的说明）
            if re.search(_PHONE_WORD, text) and re.search(_PERSON_WORD, text):
                out.append(text)
    for m in _PLACEHOLDER_REF.finditer(src):
        if "UserSearch" in m.group(1):
            out.append(m.group(1))
    return out


def main() -> int:
    kts = kt_sources()

    # ---- 1. 规则只有一处（两侧） ----
    print("规则唯一：按人搜索的匹配只有一份实现")
    kt_rule = read(USER_SEARCH_KT)
    ok("客户端规则在 core/UserSearch.kt，且 object 名就是 UserSearch", "object UserSearch" in kt_rule)
    ok(
        "客户端规则同时认**姓名**与**手机号**（少一边就等于某个字段搜不到）",
        "name?.contains(" in kt_rule and "phone?.contains(" in kt_rule,
        "matches() 里必须两个字段都参与匹配",
    )
    definers: list[Path] = []
    for p, s in kts.items():
        for m in re.finditer(r"\bfun matches\(", s):
            # 只看"长得像按人匹配"的那一份：函数体里得真的在比较字符串。
            # ⚠️ 不能只按名字认 —— `AiProviders.kt` 里也有一个 `fun matches(other: String)`，
            #    它是比 baseUrl 的，把它算进来这条判据就永远红（永远红的检查 = 没有检查）。
            if ".contains(" in s[m.end(): m.end() + 400]:
                definers.append(p)
    ok(
        "全树「按人匹配」的函数只在 UserSearch.kt 定义一次（别的页面各写一份就分叉了）",
        definers == [USER_SEARCH_KT],
        f"实际 {[str(p.relative_to(ROOT)) for p in definers]}",
    )

    py_rule = read(USER_SEARCH_PY)
    ok(
        "后端规则在 app/core/user_search.py，且用 `%...%` 子串匹配（后 4 位据此天然命中）",
        "def name_or_phone_like(" in py_rule and 'like = f"%{term}%"' in py_rule,
        "写成等值比较的话「后 4 位」这条需求直接失效",
    )
    consumers: list[str] = []
    for p in sorted(APP.rglob("*.py")):
        s = io.open(p, encoding="utf-8", errors="replace").read()
        if "name_or_phone_like(" in s and p != USER_SEARCH_PY:
            consumers.append(str(p.relative_to(ROOT)).replace("\\", "/"))
    ok(
        f"后端调用点 ≥{MIN_BACKEND_CONSUMERS}（账号名册 + 客户档案）",
        len(consumers) >= MIN_BACKEND_CONSUMERS,
        f"实际 {consumers}",
    )
    ok(
        "账号名册 users.py 与客户档案 customers.py 都在调用点里",
        any(c.endswith("api/v1/users.py") for c in consumers)
        and any(c.endswith("api/v1/customers.py") for c in consumers),
        f"实际 {consumers}",
    )
    # 反向：这两个消费点不许退回"就地手搓谓词"。
    # ⚠️ 只盯这两处，不做全库扫描：`orders.py`/`places.py` 也各有一条 `like` 谓词，
    #    但那两条是**另一条规则**（订单关键词 = 单号/地址/备注一起搜；地点 = 地点名+详细地址），
    #    把它们也算进来就成了噪音 —— 而噪音型红线的结局是被人无视（本项目栽过）。
    for rel, col in (
        ("backend/app/api/v1/users.py", "User"),
        ("backend/app/api/v1/customers.py", "Customer"),
    ):
        s = io.open(ROOT / rel, encoding="utf-8", errors="replace").read()
        bad = re.findall(rf"{col}\.(?:full_name|name|phone)\.like\(", s)
        ok(
            f"{rel} 里没有手搓的姓名/手机号 like（按人搜一律调 user_search）",
            not bad,
            f"又退回了就地谓词：{bad} —— 两边口径会分叉",
        )

    # ---- 2. 名册页必须走服务端 ----
    print("\n名册页：搜索必须打到服务端（一页上限 500，本地过滤物理上找不到第 501 个）")
    repo_src = kts[ANDROID / "data/repo/AppRepository.kt"]
    ok(
        "仓库层 usersPage 收 `q` 并传给接口（`q = q?.trim()`）",
        re.search(r"suspend fun usersPage\([\s\S]{0,400}?q: String\? = null", repo_src) is not None
        and "q = q?.trim()" in repo_src,
    )
    # ⚠️ 必须**在 listUsers 这一个方法体内**找 `@Query("q")`：`Apis.kt` 里有 5 个端点都叫 q
    #    （订单/流水/地点…），全文级判据会把"listUsers 的 q 被删掉"当成通过。
    apis_raw = read(ANDROID / "data/remote/api/Apis.kt")
    lu_start = apis_raw.find("suspend fun listUsers(")
    lu_block = apis_raw[lu_start: lu_start + 600] if lu_start >= 0 else ""
    ok(
        "接口层 listUsers 自己声明了 `@Query(\"q\")`（不是靠别的端点的 q 蒙混过去）",
        '@Query("q") q: String? = null' in lu_block,
        "没声明的话，请求打到后端会被 FastAPI 忽略 —— 搜索框看着在，什么都没搜",
    )
    roster_vm_src = kts[ROSTER_VMS[0]]
    ok(
        "名册页的 `shown` 在没有搜索时回落到**完整名册**（hits 不许顶掉 users）",
        "val shown: List<UserDto> get() = hits ?: users" in roster_vm_src,
        "让搜索结果覆盖 users，配车弹层/车队摘要就会出现「账号 #5（不在司机名册里）」这种假故障",
    )
    roster_hits = 0
    for p in ROSTER_VMS:
        s = kts[p]
        uses_server = re.search(r"usersPage\([\s\S]{0,200}?q = kw", s) is not None
        ok(f"{p.name} 的搜索走服务端 `q =`", uses_server, "没传 q 就是在过滤手里这一页")
        if uses_server:
            roster_hits += 1
    ok(
        "名字查找会把搜索结果也算上（搜到的人也能正确显示名字，而不是「不在名册里」）",
        "hits?.firstOrNull { it.id == driverId }" in roster_vm_src,
        "搜出来的人不在名册那一页里，只查 users 会把他说成「账号 #N（不在司机名册里）」",
    )
    ok(
        f"认出的走服务端的名册页 ≥{MIN_ROSTER_PAGES}（低于这个数说明判据失配、在空转）",
        roster_hits >= MIN_ROSTER_PAGES,
        f"实际 {roster_hits}",
    )

    # ---- 3. 所有"按人搜索"的框都走这条规则 ----
    print("\n所有「按人搜索」的框：走 SearchField 或直接引用 UserSearch")
    boxes: list[tuple[Path, str]] = []
    for p, s in kts.items():
        for text in person_search_boxes(s):
            boxes.append((p, text))
    ok(
        f"从源码认出 ≥{MIN_PERSON_BOXES} 个按人搜索框（判据失配时先报错，不许安静通过）",
        len(boxes) >= MIN_PERSON_BOXES,
        f"实际 {len(boxes)}：{[(str(p.relative_to(ROOT)), t) for p, t in boxes]}",
    )
    for p, text in boxes:
        # `SearchField` / 引用 `UserSearch.HINT` 本身就是同源的那一份，直接算过
        if text == "SearchField" or "UserSearch" in text:
            continue
        s = kts[p]
        # ⚠️ 判据要求**真的调用** `UserSearch.matches(`，不是"文件里提过 UserSearch"：
        #    后者只要留着 import 就能过 —— 而"把某一处改回就地 contains"正是要抓的那种坏法。
        ok(
            f"{p.name} 的「{text}」走 SearchField 或真的调用 UserSearch.matches",
            "SearchField(" in s or "UserSearch.matches(" in s,
            "各页自己写一份匹配口径 = 同一件事多个答案（搜得到/搜不到全看在哪一页）",
        )

    # ---- 4. 后 4 位真的能搜 ----
    print("\n后 4 位：客户端子串匹配 + 单测钉住")
    test_kt = ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/UserSearchTest.kt"
    if not test_kt.exists():
        ok("UserSearchTest.kt 存在（后 4 位的行为由单测钉住）", False, str(test_kt))
    else:
        ts = read(test_kt)
        ok(
            "单测里有「后 4 位」这一条（`8001` 命中 `13800008001`）",
            re.search(r'assertTrue\("手机号后 4 位", UserSearch\.matches\("8001"', ts) is not None,
            "这条断言就是「后 4 位能搜」的行为钉子，删了它规则改了没人知道",
        )
        ok(
            "单测里有**反例**（不匹配的号码不许命中）",
            re.search(r'assertFalse\(UserSearch\.matches\("8002"', ts) is not None,
            "只有正例的话，matches 恒 true 也能过",
        )
    ok(
        "SearchField 的默认提示语来自 UserSearch.HINT（各页同源，不抄第二份）",
        "placeholder: String = com.tapmoay.sorders.core.UserSearch.HINT" in kts[COMPONENTS_KT]
        or "placeholder: String = UserSearch.HINT" in kts[COMPONENTS_KT],
    )

    # ---- 5. 账本不许退回"一个一个去选" ----
    print("\n账本仪表盘：不许退回多选挑选器")
    for p in (LEDGER_SCREEN, LEDGER_VM):
        s = kts[p]
        bad = [w for w in ("selectedAccounts", "selectedDrivers", "AccountPicker(", "DriverPicker(") if w in s]
        ok(
            f"{p.name} 里没有「多选挑选器」的残留",
            not bad,
            f"用户 2026-09-19 明确否掉了它（「一个一个去选…要有多麻烦啊」）：{bad}",
        )
    ls = kts[LEDGER_SCREEN]
    ok(
        "账本有仪表盘卡（KpiBlock）与一个搜索框（SearchField，在侧边抽屉里）",
        "KpiBlock(" in ls and "SearchField(" in ls,
    )
    # 三类账共用**一份**行渲染：`LedgerAccountRow` 只有一处定义 + 一处调用，
    # 而"这一类账叫什么/什么颜色/什么图标"在 VM 的 `kind*` 三处（不再散在页面的 when 里）。
    # 判据是**数出来的**（定义 1 + 调用 1）：三段复制会把它变成 4 处，而那时这个数就报错。
    n_rows = ls.count("LedgerAccountRow(")
    ok(
        f"三类账走同一份行渲染（`LedgerAccountRow` 定义 1 + 调用 1，实测 {n_rows}）",
        n_rows == 2
        and "fun kindColor()" in kts[LEDGER_VM]
        and "fun kindIcon()" in kts[LEDGER_VM]
        and "fun kindLabel()" in kts[LEDGER_VM],
        "三段复制 = 改一处漏一处（上一版就是这么长出两套挑选器的）",
    )
    ok(
        "账本里按人过滤只有一处（侧边抽屉那份名单），走唯一实现 UserSearch.filter",
        "UserSearch.filter(accountRows()" in kts[LEDGER_VM],
        "自己写 contains 就又分叉了",
    )

    # ---- 6. 账户卡片必须带手机号 ----
    print("\n账户卡片：必须有手机号（否则同名不同人分不开、也没得搜）")
    ledger_schema = read(APP / "schemas/ledger.py")
    ok(
        "LedgerAccountOut 有 phone 与 is_active",
        re.search(r"class LedgerAccountOut\([\s\S]{0,900}?phone: str \| None", ledger_schema) is not None
        and re.search(r"class LedgerAccountOut\([\s\S]{0,900}?is_active: bool", ledger_schema) is not None,
        "没有 phone → 同名不同人分不开、也没得搜（用户那条需求只做了一半）",
    )
    ok(
        "司机账户组也带 driver_phone（三类账同一套认人方式）",
        '"driver_phone": None,' in read(APP / "api/v1/freight_settlement.py"),
        "少了这个键，司机账就只能按名字认人（同名司机分不开、也搜不到）",
    )
    dto_block = kotlin_decl_block(kts[ANDROID / "data/remote/dto/Dtos.kt"], "data class LedgerAccountOut(")
    ok(
        "Android 侧 DTO（**LedgerAccountOut 那一支**）收下这两个字段",
        "val phone: String? = null" in dto_block and '@SerialName("is_active")' in dto_block,
        "在这个文件里全文找 `val phone` 会被别的 DTO（UserDto 也有手机号）蒙混过去",
    )
    ok(
        "账户行真的把手机号显示出来了（不只是收下不用）",
        "row.phone" in ls and "未注册账号" in ls,
    )
    ok(
        "软删账号的手机号**真的**去尾再下发（不是只 import 了工具）",
        "strip_del_suffix(u.phone)" in read(APP / "api/v1/ledger.py")
        and "def strip_del_suffix(" in read(APP / "services/soft_delete.py"),
    )

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {passes} 项通过：按人搜索一条规则、名册页打到服务端、账本是仪表盘。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
