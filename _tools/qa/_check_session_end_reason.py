# -*- coding: utf-8 -*-
"""红线：会话被终止时必须说得出**是哪一种原因**，说不准就说兜底句（BUG-0006，2026-10-03 E2E 走查「机制性发现」）。

## 这条是怎么来的
2026-10-03 的 E2E 走查（_tmp/E2E测试报告.md:151-156）里，5554 在巡检中被弹回登录页，界面上只有
一句 toast「登录已失效，请重新登录」。可这件事在服务端有**四种完全不同的原因**：

  · 被顶号（同一账号在另一台设备登录）→ 用户该做的是「如果不是我，去改密码」；
  · 账号被停用（派单员停的）        → 用户该做的是「找派单员问为什么」；
  · 自己刚改了密码 / 登出           → 用户什么都不用做，重新登录即可；
  · 令牌自然过期（满 24 小时）      → 用户什么都不用做，重新登录即可。

四种原因共用一句话，等于什么都没说 —— 而服务端明明握着 reason 字符串（真人会以为 App 坏了）。
同一份走查还记了两件事：core/ApiClient.kt 的兜底句把 **403（纯权限不足）** 也写成「登录已失效」；
users 表**没有 last_login_at**，于是「谁在什么时候顶掉了谁」事后在库里查不到。

## 为什么必须有机器的判据
这条修复的四个退化点，人工点一遍都发现不了（要凑齐两台设备 + 停用 + 改密 + 等 24 小时）：

1. **分支顺序写反了照样编译**：except ExpiredSignatureError 必须排在
   except (JWTError, ValueError, TypeError) **前面** —— 排在后面就永远走不到，
   而过期恰恰是最常见的那一种。代码读起来像是对的，只有机器比下标才看得出来。
2. **原因取到了、中途丢掉**：socket 那条链（_sessionRefused）原来把服务端报文里的
   reason 扔了、只发一个 tick；toast 那边又写回硬编码兜底句。两处都是「能跑、能编译、
   现象只在真机顶号时出现」。
3. **拿旧原因解释这一次**（最要命的一条）：库里 session_revoked_reason 是
   「上一次为什么被踢」的**历史值**。如果撤销时没有把 session_revoked_version 记下来、
   读的时候又不跟当前 token_version 对账，就会出现「我这次是令牌过期，界面却告诉我
   账号在另一台设备登录」—— 比不说原因更糟，用户会去改一个根本没被泄露的密码。
   所以判据同时钉死两头：记（撤销那一刻的版本号）与对账（recorded != current → 兜底句）。
4. **403 被当成登录失效**：用户被无辜踢下线，还被告知「重新登录」—— 登几次都一样。

判据分四层：
1. 后端 四句话分得开（顺序 / 各自的话 / 兜底句还在 / 时间戳为空时不拿「现在」冒充）；
2. 后端 原因从哪来（撤销那一刻写、写方只有一处、登录记 last_login_at 且不碰原因）；
3. 客户端 原因送到界面（401 才清会话、读原因不吃掉正文、一路带进 toast、socket 那条链也带）；
4. 配对与反空转：两端回归用例在、反向验证脚本在、文档/登记表/认领簿三处都记了这条。

R4-BOUNDARY-JUSTIFICATION: 这一条**边界解决不了**。四句话写全了、但分支顺序反了，编译与
接口测试都照样过（那台机器只是继续显示旧话）；原因丢在 socket 或 toast 那一跳，任何
HTTP 层的测试都看不见（那两个文件不参与后端用例）。「哪句话该出现」是**口径问题**，
只有扫源码结构与扫文案才问得出来。反向破坏用例由
_tools/qa/_reverse_verify_session_end_reason.py 负责；「用户确实看到了哪一句」那一头由
2026-10-03 模拟器 5554 的顶号取证（两台设备截图 + 界面上那句话）负责。
本判据只读源码与文档（read()），不连库、不 import 后端、不跑迁移、不起服务。

用法：python _tools/qa/_check_session_end_reason.py
     python _tools/qa/_check_session_end_reason.py --list   # 只列它到底在查什么
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
# 注释剥离**只有一份实现**（那个状态机是为通配符这类字符串字面量写的，抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"

DEPS = BACKEND / "app/deps.py"
AUTH = BACKEND / "app/api/v1/auth.py"
SVC = BACKEND / "app/services/auth_service.py"
MODEL = BACKEND / "app/models/user.py"
BOOT = BACKEND / "app/core/schema_bootstrap.py"
#: 正式搬迁（`migrations/README.md` 的分工：正式变更走迁移，自愈副本只是兜底）
MIG016 = BACKEND / "app/migrations/016_session_end_reason.py"
API = AND / "core/ApiClient.kt"
CONTAINER = AND / "core/AppContainer.kt"
NAV = AND / "ui/nav/NavGraph.kt"
SOCKET = AND / "core/SocketManager.kt"
HUB = AND / "core/RealtimeHub.kt"
PYTEST_FILE = BACKEND / "tests/test_session_end_reason.py"
KTEST_FILE = ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/SessionExpiryMessageTest.kt"
README = ROOT / "docs/changes/README.md"
DOC = ROOT / "docs/changes/BUG-0006.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = "_tools/qa/_reverse_verify_session_end_reason.py"

#: 扫到的界面文件数下限（防目录改名 / 搬走之后「一个文件都没扫到」也算过）
MIN_UI_FILES = 100

#: 兜底句（对不上账 / 压根没记原因时**只许**说这一句；一字不许改，走查里用户看到的就是它）
FALLBACK = "登录已失效，请重新登录"
#: 令牌满 24 小时
EXPIRED = "登录已过期（令牌 24 小时有效），请重新登录"
#: 账号没了
GONE = "这个账号不存在或已被删除，请联系派单员"
#: 账号被停用
DISABLED = "这个账号已被停用，请联系派单员"
#: 凭证无效（令牌读不出来时那条老路径，**必须还在**：它是「连是谁都不知道」时的唯一出口）
CREDS = 'credentials_exc = _unauthorized("登录已失效或凭证无效，请重新登录")'
#: 撤销那一刻的三样快照（少一样都对不上账）
SNAP_REASON = 'user.session_revoked_reason = (reason or "").strip()[:64]'
SNAP_AT = "user.session_revoked_at = utc_now_naive()"
SNAP_VER = 'user.session_revoked_version = int(getattr(user, "token_version", 0) or 0)'
#: 四列（原因 / 时间 / 版本凭据 / 最后登录）
COLUMNS = ("session_revoked_reason", "session_revoked_at", "session_revoked_version", "last_login_at")
#: 登录路径里那句豁免（测试号段不许被自动化用例踢下线）
EXEMPT = r"if not is_test_account\(user\.phone\):\s*\n\s+revoke_tokens_and_sockets\("
#: 反引号（Python 源码里不写反引号，判据要认登记表里的 Markdown 代码记号）
BT = chr(96)


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def kt(p: Path) -> str:
    """源码去掉注释之后的正文（词表判据必须去注释，否则自己写的注释会把它喂饱）。"""
    return strip_comments(read(p))


def py_code(src: str) -> str:
    """Python 源码去掉注释与文档字符串 —— 判据只许锚在**代码**上。

    ⛔ 本仓库反复踩过的同一个坑（`_check_migrations.py` 的 docstring 里记着）：判据搜纯文本时会被
    **自己写的说明文字**满足 —— 迁移文件的模块 docstring 里正好逐字写着这四列的名字，不剥散文
    的话「迁移里有这四列」会被散文喂饱：把迁移里的 DDL 全删空，判据照样绿。
    """
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    return re.sub(r"(?m)^[ \t]*#.*$", "", src)


def py_body(src: str, sig: str) -> str:
    """取 Python 函数的正文：从 sig 那一行到下一个**顶格**的 def / class / @ 或文件末。

    后端是缩进语言，不能像 Kotlin 那样数大括号（_check_freight_pricing_clarity.body_of
    是给大括号语言写的）；按顶格关键字收口才切得准。
    """
    i = src.find(sig)
    if i < 0:
        return ""
    j = i + len(sig)
    m = re.search(r"(?m)^(?=(?:def |class |@))", src[j:])
    return src[i : j + (m.start() if m else len(src) - j)]


def body_of(src: str, sig: str) -> str:
    """按大括号配对取出一个 Kotlin 函数体（sig 是函数签名那一行）。"""
    i = src.find(sig)
    if i < 0:
        return ""
    b = src.find("{", i + len(sig) - 1)
    if b < 0:
        return ""
    depth = 0
    for j in range(b, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
    return ""


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def section(title: str) -> None:
    print()
    print(f"-- {title} --")


def main() -> int:
    if refuse_if_injecting("登录失效原因检查"):
        return 1

    py_src = {p: read(p) for p in (DEPS, AUTH, SVC, MODEL, BOOT)}
    deps, auth, svc = py_src[DEPS], py_src[AUTH], py_src[SVC]
    model, boot = py_src[MODEL], py_src[BOOT]
    ui_files = sorted(AND.rglob("*.kt"))
    app = {p: kt(p) for p in ui_files}
    api, container = app.get(API, ""), app.get(CONTAINER, "")
    nav, socket, hub = app.get(NAV, ""), app.get(SOCKET, ""), app.get(HUB, "")

    c = Checker()

    # ---- 1. 后端：四种原因分得开 ----
    section("1. 后端：四种失效原因不许再共用一句话（deps.get_current_user）")
    una = py_body(deps, "def _unauthorized(")
    c.ok(
        "401 由 _unauthorized 统一构造，且带 WWW-Authenticate: Bearer",
        "status.HTTP_401_UNAUTHORIZED" in una and '"WWW-Authenticate": "Bearer"' in una,
        f"切到 {len(una)} 字符 —— 少了这个头，中间层与客户端只把它当普通错误："
        "用户既不知道原因，也拿不到「该重新登」的信号",
    )
    i_exp = deps.find("except ExpiredSignatureError:")
    i_gen = deps.find("except (JWTError")
    c.ok(
        "令牌过期单独一句，且排在通用 JWTError 分支**之前**（顺序反了＝永远走不到）",
        0 < i_exp < i_gen and EXPIRED in deps[i_exp : i_exp + 400],
        f"i_exp={i_exp} / i_gen={i_gen} —— python 按顺序匹配 except，过期分支排在后面就永远"
        "命不中（而过期恰恰是最常见的那一种）",
    )
    c.ok(
        "账号没了 / 账号被停用 各说各的（不再是同一句）",
        re.search(r"raise _unauthorized\(" + re.escape('"' + GONE + '"') + r"\)", deps) is not None
        and re.search(r"raise _unauthorized\(" + re.escape('"' + DISABLED + '"') + r"\)", deps) is not None,
        "这两件事的处置完全不同（找派单员问为什么 vs 联系派单员恢复），共用一句话用户无从判断",
    )
    c.ok(
        "凭证无效那条老路径还在（令牌读不出来时的唯一出口）",
        CREDS in deps,
        "连「是谁」都不知道的时候只能给这一句；删掉它会让这种情况掉进 500",
    )
    c.ok(
        "tv 对不上 → 401，且走 _session_ended_detail（说的是这一次的原因）",
        deps.find('payload.get("tv"') > 0
        and re.search(r'"tv"[\s\S]{0,400}?raise _unauthorized\(_session_ended_detail\(user\)\)', deps)
        is not None,
        "tv 对不上＝这台设备的会话已经结束了（被顶号 / 停用 / 改密 / 登出都走这里）",
    )
    ended = py_body(deps, "def _session_ended_detail(")
    c.ok(
        "原因对不上账就说兜底句（宁可少说，也不许拿旧原因解释这一次）",
        "not reason or recorded != current" in ended and FALLBACK in ended,
        f"切到 {len(ended)} 字符 —— 少了这层对账，用户会被告知一件没发生过的事"
        "（去改一个根本没泄露的密码）",
    )
    i_none = ended.find("if revoked_at is None:")
    i_stamp = ended.find("local_stamp(revoked_at)")
    c.ok(
        "撤销时间为空时不拿「现在」冒充（先判 None，再用 local_stamp）",
        0 <= i_none < i_stamp,
        f"i_none={i_none} / i_stamp={i_stamp} —— local_stamp(None) 会返回「现在」，"
        "顺序反了会让老账号看到一句「刚刚被顶号」",
    )
    sents = (FALLBACK, EXPIRED, GONE, DISABLED)
    c.ok(
        "四句话都在，且互不相同（四种原因＝四句看得见的话）",
        all(s in deps for s in sents) and len(set(sents)) == 4,
        "少一句就等于又回到「共用一句话」",
    )

    # ---- 2. 后端：原因从哪来（撤销那一刻落库） ----
    section("2. 后端：原因只在撤销那一刻落库（auth_service.revoke_tokens_and_sockets）")
    rev = py_body(svc, "def revoke_tokens_and_sockets(")
    i_bump = rev.find("bump_token_version(db, user)")
    i_snap = rev.find("session_revoked_reason =")
    i_task = rev.find(".add_task(")
    c.ok(
        "撤销 = 版本号 +1 与原因快照同一个函数，且撤销在先、排推送在后",
        -1 < i_bump < i_snap < i_task,
        f"顺序 bump={i_bump} / snapshot={i_snap} / add_task={i_task} —— 分两次提交会出现"
        "「版本号已经 +1、原因还是上一次的」的窗口，用户看到的是一句对不上的话",
    )
    c.ok(
        "快照写的就是这三样（原因 / 时间 / 那一刻的版本号）",
        SNAP_REASON in rev and SNAP_AT in rev and SNAP_VER in rev,
        "少一样都对不上账：没时间戳说不清「什么时候」，没版本号分不清「这句话还算不算数」",
    )
    writers = [
        p.name
        for p in sorted((BACKEND / "app").rglob("*.py"))
        if "session_revoked_reason =" in p.read_text(encoding="utf-8")
    ]
    c.ok(
        "写方全后端只有一处（读侧只读不写）",
        writers == ["auth_service.py"] and "session_revoked_reason =" not in deps,
        f"实际写方 {writers} —— 多一处就多一个「谁最后写谁说了算」的竞态",
    )
    cols = set(re.findall(r"(" + "|".join(COLUMNS) + r")\s*:\s*Mapped\[", model))
    c.ok("users 表四列都在模型里（原因 / 时间 / 版本凭据 / 最后登录）", cols == set(COLUMNS), f"只找到 {sorted(cols)}")
    # 2026-10-03（BUG-0006）：原先只看 `ADD COLUMN <列>` 那句 ALTER —— 反向验证把「门闩」
    # （`if "<列>" not in ucols:`）改成 `if False:` 时 ALTER 那行还在，判据照旧绿（漏网）。
    # 老库升级路径要成立，门闩与 ALTER **缺一不可**，所以两条一起认。
    missing = [
        n for n in COLUMNS
        if f'if "{n}" not in ucols:' not in boot or f"ADD COLUMN {n}" not in boot
    ]
    c.ok(
        "老库升级路径也在（schema_bootstrap 四个幂等补列块）",
        not missing,
        f"缺 {missing} —— 已经在跑的库不会因为模型改了就有这几列，"
        "上线后会以 Unknown column 的形式炸在登录路径上",
    )
    # ⛔ 「写进 schema_bootstrap 的自愈块」**不等于**老库能升级：应用启动只核对、不改库（R3-01），
    #    真正把列搬上老库的是 migrations/ 下的版本化迁移，自愈副本只是兜底。没有迁移的话
    #    `python -m app.migrations upgrade` 会说「结构已就绪」而库里依旧缺列 —— 本轮真机取证时
    #    就是这么发现的（服务重启后那 4 列仍然不在，登录路径会在取属性时炸 Unknown column）。
    mig = py_code(read(MIG016))
    mig_cols = set(re.findall(r'"(' + "|".join(COLUMNS) + r')\"\s*:', mig))
    c.ok(
        "正式搬迁走迁移 016（四列定义在迁移里：老库靠它升级，自愈副本只是兜底）",
        mig_cols == set(COLUMNS)
        and re.search(r"(?m)^VERSION = 16$", mig) is not None
        and re.search(r'(?m)^NAME = "session_end_reason"$', mig) is not None
        and "if name in have:" in mig
        and "UPDATE users SET" not in mig
        and "INSERT INTO users" not in mig,
        f"迁移 {MIG016.name} 里只找到 {sorted(mig_cols)} —— 应用启动只核对不改库："
        "老库等的是 python -m app.migrations upgrade，不是重启服务",
    )
    login = py_body(auth, "def _login(")
    c.ok("切出了 _login 的函数体（切不出＝判据要跟着改）", len(login) > 200, f"实际 {len(login)} 字符")
    c.ok(
        "登录记下 last_login_at（走查：被顶号后「事后查不到谁顶了谁」）",
        "user.last_login_at = utc_now_naive()" in login,
        "没有它，一次顶号在库里只留下「版本号 +1」，说不清是谁先谁后",
    )
    c.ok(
        "而且落在 commit 之前（同一个事务）",
        0 <= login.find("user.last_login_at") < login.find("db.commit()"),
        "commit 之后写＝另开一次提交，会出现「人已经登进来了、库里没有」",
    )
    c.ok(
        "登录路径不碰 session_revoked_reason（碰了＝把要说的话吃掉）",
        # 只认**赋值句**：函数体里那段解释这条红线的注释本身含这个词（第一版写成纯子串判断，
        # 被自己的注释喂饱 ⇒ 假阳性）。
        re.search(r"session_revoked_reason\s*=[^=]", login) is None,
        "被顶掉那台还要靠这次撤销记下的原因告诉用户发生了什么",
    )
    c.ok(
        "撤销仍挂在豁免判据下（测试号段不受影响）",
        re.search(EXEMPT, login) is not None,
        "自动化用例共用号段：豁免丢了会让跑一遍用例就把真机踢下线（_check_single_session.py 也钉着）",
    )

    # ---- 3. 客户端：原因送到界面 ----
    section("3. 客户端：原因一路送到界面（ApiClient → AppContainer → NavGraph / SocketManager）")
    line401 = next((ln.strip() for ln in api.splitlines() if "resp.code == 401" in ln), "")
    c.ok(
        "只有 401 才清会话（403 不许顺手把人踢下线）",
        line401 != "" and "403" not in line401,
        f"那一行是 {line401} —— 403 是「这个账号没这个权限」，踢下线也解决不了，用户登几次都一样",
    )
    c.ok(
        "拦截到 401 时把响应正文里的原因取出来（走 onSessionExpired）",
        "onSessionExpired(unauthorizedDetail(resp))" in api,
        "只发一个 tick＝界面只能自己编一句话（修复前就是硬编码兜底句）",
    )
    ud = body_of(api, "internal fun unauthorizedDetail(")
    c.ok(
        "读原因用 peekBody（读了不许把正文吃掉）",
        "peekBody(" in ud and ".string()" in ud and ".body" not in ud,
        f"切到 {len(ud)} 字符 —— 用 body 上的 string() 会把正文读掉，后面 Retrofit 反序列化"
        "拿到空串（不报错、字段全是 null，比崩了更难查）",
    )
    c.ok(
        "原因函数是 internal（单测够得着，Android 单测钉着「不许吃掉正文」）",
        "internal fun unauthorizedDetail(" in api,
        "改回 private 会让那条单测编不过（那是故意的：它就该够不着）",
    )
    c.ok(
        "回调签名带原因（不是无参 tick）",
        "onSessionExpired: (String?) -> Unit = {}" in api
        and "onSessionExpired = { reason -> clearSession(reason) }" in container,
        "类型对不上＝原因在容器门口就丢了",
    )
    c.ok(
        "容器记住原因（clearSession 收得下，也只在这里记住）",
        "val sessionExpiredReason = MutableStateFlow<String?>(null)" in container
        and "fun clearSession(reason: String? = null)" in container
        and "sessionExpiredReason.value = reason" in container,
        "clearSession 收不到原因＝界面拿不到（默认值 null 就是兜底句那条路）",
    )
    c.ok(
        "toast 有原因说原因、没原因兜底（两句都在同一处）",
        "val reason = container.sessionExpiredReason.value" in nav
        and 'reason ?: "登录已失效，请重新登录"' in nav,
        "少了 reason 就退回硬编码；少了兜底句会在 null 时显示 null",
    )
    hm = body_of(api, "internal fun httpMessage(")
    i_403 = hm.find("code == 403")
    c.ok(
        "403 与 401 的兜底不是同一句（403 不许提登录失效）",
        'code == 401 -> "登录已失效，请重新登录"' in hm
        and 'code == 403 -> "这个账号没有这个权限' in hm
        and i_403 > 0
        and "登录已失效" not in hm[i_403:]
        and "重新登录" not in hm[i_403:],
        "403 被写成「登录已失效」＝用户以为是掉线，反复重登（走查报告原话）",
    )
    c.ok(
        "socket 那条链也把原因带过去了（不再只发一个 tick）",
        "val sessionRefused: SharedFlow<String?> = _sessionRefused.asSharedFlow()" in socket
        and "notifyRefused(" in socket
        and "revokedReason(args)" in socket
        and "_sessionRefused.tryEmit(reason)" in socket
        and "sessionRefused.collect { reason ->" in hub
        and "container.clearSession(reason)" in hub,
        "长连接被撤销是「被顶号 / 被停用」最常被察觉的那条路；丢在这里＝界面还是只能编一句",
    )
    rev_fn = body_of(socket, "private fun revokedReason(")
    c.ok(
        "取不到原因就返回 null（客户端不许自己编一句）",
        rev_fn != "" and "null" in rev_fn and all(s not in socket for s in sents),
        f"切到 {len(rev_fn)} 字符 —— 四句话只能由后端说；客户端编出来的原因与库里的记账"
        "对不上，排查时会把两件事混成一件",
    )

    # ---- 4. 配对、用例与反空转 ----
    section("4. 配对、回归用例与反空转")
    n_py = len(re.findall(r"(?m)^def test_", read(PYTEST_FILE)))
    # 2026-10-03（BUG-0006）：原先写 `^\s*@Test` —— 正则只匹配前缀，`@TestX` 也照样命中，
    # 反向验证把注解改名后判据还是绿的（漏网）。改成整行匹配：注解必须自己站一行。
    n_kt = len(re.findall(r"(?m)^\s*@Test\s*$", read(KTEST_FILE)))
    c.ok(
        "后端回归用例齐（四种原因各一条 + 对账 + 不拿旧原因解释这一次）",
        n_py >= 8,
        f"tests/test_session_end_reason.py 里 {n_py} 条（≥8）",
    )
    c.ok(
        "Android 回归用例齐（正文不许被吃掉 + 401/403 不是同一句）",
        n_kt >= 5,
        f"SessionExpiryMessageTest.kt 里 {n_kt} 条（≥5）",
    )
    c.ok("这条红线配了反向验证脚本", (ROOT / REVERSE).exists(), f"找不到 {REVERSE}")
    c.ok(
        "改动文档在（走查项 + 四种原因）",
        DOC.exists() and "BUG-0006" in read(DOC) and FALLBACK in read(DOC),
        "docs/changes/BUG-0006.md 不在 / 少了走查项",
    )
    c.ok(
        "改动登记表里有 BUG-0006 行（进行中 / 已关闭两态）",
        ("| " + BT + "BUG-0006" + BT + " |") in read(README),
        "docs/changes/README.md 里没有 BUG-0006 那一行",
    )
    c.ok("认领簿里有 BUG-0006 的块", "BUG-0006" in read(CLAIM))
    c.ok(
        f"扫到的界面源码 ≥{MIN_UI_FILES} 个文件（防目录改名后「一个都没扫到」也算过）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)} 个",
    )
    c.ok(
        "后端五个文件都读到了非空内容（防路径写错之后全判空也算过）",
        all(len(v) > 200 for v in py_src.values()),
        " / ".join(f"{p.name}={len(v)}" for p, v in py_src.items()),
    )

    if "--list" in sys.argv:
        print()
        print("  == 它到底在查什么 ==")
        print("     · deps    四种原因分得开：过期分支**排在**通用 JWTError 之前、账号没了/被停用各一句、")
        print("               凭证无效那条老路还在、tv 对不上走 _session_ended_detail")
        print("     · 对账    not reason or recorded != current → 兜底句；时间为空不拿「现在」冒充")
        print("     · 记账    撤销那一刻写三样（原因/时间/版本号），写方全后端只此一处；")
        print("               users 四列 + schema_bootstrap 四个幂等补列块；登录记 last_login_at 且不碰原因")
        print("     · 客户端  只有 401 清会话、peekBody 读原因不吃正文、internal 够得着、")
        print("              AppContainer 记住、NavGraph 有原因说原因、403 与 401 不是同一句")
        print("     · socket  _sessionRefused 是 SharedFlow 带原因、报文里的 reason 带得走、客户端不编原因")
        print("     · 配      两端回归用例、反向验证脚本、改动文档、登记表、认领簿五件事都在")

    return c.report("会话被终止时说得出是哪一种原因、说不准就说兜底句（BUG-0006）")


if __name__ == "__main__":
    sys.exit(main())
