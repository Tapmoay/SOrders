# -*- coding: utf-8 -*-
"""反向验证：把 BUG-0006 那条红线逐条弄坏，证明它真的会红。

为什么要反向验证：一条判据可以永远绿（条件写错、扫到空字符串、路径搬走后 read() 返回空），
那样它就不是红线而是摆设。这里逐条注入「改坏了」的版本，每条都必须让
_tools/qa/_check_session_end_reason.py 非零退出：

- 后端-分句类：过期分支删掉 / 说过期改成共用句、停用改成共用句、凭证无效那条老路改名、
  tv 分支退回裸 credentials_exc（这几条都是「代码读起来还对」的改法）；
- 后端-对账类：拿掉 recorded != current、拿掉撤销时间为空的保护（拿旧原因解释这一次）；
- 后端-记账类：撤销里不排推送 / 少写时间戳 / 不 strip 截断、模型少一列、
  老库补列块删掉、登录不记 last_login_at、登录路径顺手清原因、豁免判据丢掉；
- 客户端类：403 也清会话、不取正文原因、用 body 上的 string() 吃掉正文、internal 改回 private、
  容器不记原因、toast 退回硬编码、403 写回「登录已失效」、socket 与 RealtimeHub 把 reason 丢掉；
- 用例/文档类：把两端的回归用例改名（判据按 def test_ / @Test 计数）、
  把反向脚本从配对表里删掉、把登记表那一行改名。

⚠️ 快照按字节做（CRLF / LF 都要原样还回去），跑完逐字节核对。

用法：python _tools/qa/_reverse_verify_session_end_reason.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_session_end_reason.py"

DEPS = "backend/app/deps.py"
AUTH = "backend/app/api/v1/auth.py"
SVC = "backend/app/services/auth_service.py"
MODEL = "backend/app/models/user.py"
BOOT = "backend/app/core/schema_bootstrap.py"
#: 正式搬迁（老库真正拿到这四列的地方；自愈副本只是兜底）
MIG = "backend/app/migrations/016_session_end_reason.py"
API = "android/app/src/main/java/com/tapmoay/sorders/core/ApiClient.kt"
CONTAINER = "android/app/src/main/java/com/tapmoay/sorders/core/AppContainer.kt"
NAV = "android/app/src/main/java/com/tapmoay/sorders/ui/nav/NavGraph.kt"
SOCKET = "android/app/src/main/java/com/tapmoay/sorders/core/SocketManager.kt"
HUB = "android/app/src/main/java/com/tapmoay/sorders/core/RealtimeHub.kt"
PYTEST_FILE = "backend/tests/test_session_end_reason.py"
KTEST_FILE = "android/app/src/test/java/com/tapmoay/sorders/core/SessionExpiryMessageTest.kt"
README = "docs/changes/README.md"

CR = bytes((13,))
LF = bytes((10,))
CRLF = CR + LF
BT = chr(96)

#: 判据里那个「配对表」常量（自指注入要锚赋值行，不要锚裸路径）
REVERSE_CONST = 'REVERSE = "_tools/qa/_reverse_verify_session_end_reason.py"'
#: 登记表里那一行
README_ROW = "| " + BT + "BUG-0006" + BT + " |"
#: 停用那句原话（注入要把它换成共用句）
DISABLED_RAISE = 'raise _unauthorized("这个账号已被停用，请联系派单员")'

CASES: list[tuple[str, str, object, str]] = [
    (
        "把 401 上的 WWW-Authenticate 头去掉（客户端拿不到「该重新登」的信号）",
        DEPS,
        lambda s: s.replace('"WWW-Authenticate": "Bearer"', '"X-Auth-Hint": "Bearer"', 1),
        "WWW-Authenticate",
    ),
    (
        "把「令牌过期」那条分支删掉（过期掉进通用句）",
        DEPS,
        lambda s: s.replace("    except ExpiredSignatureError:\n", "", 1),
        "令牌过期单独一句",
    ),
    (
        "过期那句改成与通用句共用（四句话少一句）",
        DEPS,
        lambda s: s.replace('raise _unauthorized("登录已过期（令牌 24 小时有效），请重新登录") from None',
                            "raise credentials_exc from None", 1),
        "令牌过期单独一句",
    ),
    (
        "把「账号被停用」改成通用句（用户不知道该找谁）",
        DEPS,
        lambda s: s.replace(DISABLED_RAISE, "raise credentials_exc", 1),
        "各说各的",
    ),
    (
        "把「凭证无效」那条老路径改名（令牌读不出来时掉进 500）",
        DEPS,
        lambda s: s.replace('credentials_exc = _unauthorized("登录已失效或凭证无效，请重新登录")',
                            'credentials_exc = _unauthorized("凭证无效")', 1),
        "唯一出口",
    ),
    (
        "tv 对不上退回裸 credentials_exc（又变成不说原因）",
        DEPS,
        lambda s: s.replace("raise _unauthorized(_session_ended_detail(user))", "raise credentials_exc", 1),
        "说的是这一次的原因",
    ),
    (
        "拿掉版本号对账（拿上一次的原因解释这一次）",
        DEPS,
        lambda s: s.replace("if not reason or recorded != current:", "if False:", 1),
        "不许拿旧原因解释这一次",
    ),
    (
        "拿掉「撤销时间为空」的保护（老账号看到一句「刚刚被顶号」）",
        DEPS,
        lambda s: s.replace("    if revoked_at is None:\n", "", 1),
        "不拿「现在」冒充",
    ),
    (
        "撤销里不排推送（令牌作废了、长连接照收）",
        SVC,
        lambda s: s.replace("background.add_task(revoke_user_sockets, user.id, reason)\n", "", 1),
        "排推送在后",
    ),
    (
        "快照少写时间戳（说不清「什么时候」）",
        SVC,
        lambda s: s.replace("user.session_revoked_at = utc_now_naive()",
                            "user.session_revoked_at = user.session_revoked_at", 1),
        "快照写的就是这三样",
    ),
    (
        "原因不 strip / 不截断（空格与超长都落库）",
        SVC,
        lambda s: s.replace('user.session_revoked_reason = (reason or "").strip()[:64]',
                            'user.session_revoked_reason = (reason or "")', 1),
        "快照写的就是这三样",
    ),
    (
        "模型少一列（last_login_at 又没了：事后查不到谁顶了谁）",
        MODEL,
        lambda s: s.replace("last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)\n", "", 1),
        "四列都在模型里",
    ),
    (
        "老库补列块删掉一个（已经在跑的库缺列，登录路径炸 Unknown column）",
        BOOT,
        lambda s: s.replace('if "last_login_at" not in ucols:', "if False:", 1),
        "老库升级路径也在",
    ),
    (
        "老库的正式搬迁没了（自愈副本还在，但 `python -m app.migrations upgrade` 会说「已就绪」，库里依旧缺列）",
        MIG,
        lambda s: s.replace("VERSION = 16", "VERSION = 15", 1),
        "正式搬迁走迁移 016",
    ),
    (
        "迁移里少搬一列（last_login_at 又只剩自愈那一路）",
        MIG,
        lambda s: s.replace('    "last_login_at": "last_login_at DATETIME",', "", 1),
        "正式搬迁走迁移 016",
    ),
    (
        "迁移不看列在不在就 ALTER（重跑必炸：README 硬要求「必须能重跑」）",
        MIG,
        lambda s: s.replace("if name in have:", "if False:", 1),
        "正式搬迁走迁移 016",
    ),
    (
        "登录不记 last_login_at",
        AUTH,
        lambda s: s.replace("user.last_login_at = utc_now_naive()", "pass", 1),
        "登录记下 last_login_at",
    ),
    (
        "登录路径顺手清掉原因（把要说的话吃掉）",
        AUTH,
        lambda s: s.replace("    if not is_test_account(user.phone):",
                            '    user.session_revoked_reason = ""\n    if not is_test_account(user.phone):', 1),
        "登录路径不碰 session_revoked_reason",
    ),
    (
        "豁免判据丢掉（跑一遍自动化用例就把真机踢下线）",
        AUTH,
        lambda s: s.replace("    if not is_test_account(user.phone):", "    if True:", 1),
        "豁免判据下",
    ),
    (
        "401 的拦截条件里塞进 403（没权限的人被踢下线）",
        API,
        lambda s: s.replace("if (resp.code == 401 && token != null",
                            "if ((resp.code == 401 || resp.code == 403) && token != null", 1),
        "只有 401 才清会话",
    ),
    (
        "不取响应正文里的原因（只发一个 tick）",
        API,
        lambda s: s.replace("onSessionExpired(unauthorizedDetail(resp))", "onSessionExpired(null)", 1),
        "把响应正文里的原因取出来",
    ),
    (
        "读原因改用 body 上的 string()（把正文吃掉，后面反序列化成空）",
        API,
        lambda s: s.replace("val body = resp.peekBody(64L * 1024).string()",
                            'val body = resp.body?.string() ?: ""', 1),
        "读原因用 peekBody",
    ),
    (
        "原因函数改回 private（Android 单测编不过）",
        API,
        lambda s: s.replace("internal fun unauthorizedDetail(resp: Response): String? = runCatching {",
                            "private fun unauthorizedDetail(resp: Response): String? = runCatching {", 1),
        "原因函数是 internal",
    ),
    (
        "容器不记原因（界面只能自己编一句）",
        CONTAINER,
        lambda s: s.replace("        sessionExpiredReason.value = reason", "        sessionExpiredReason.value = null", 1),
        "容器记住原因",
    ),
    (
        "toast 退回硬编码兜底句（原因到了门口又丢掉）",
        NAV,
        lambda s: s.replace('reason ?: "登录已失效，请重新登录",', '"登录已失效，请重新登录",', 1),
        "toast 有原因说原因",
    ),
    (
        "403 写回「登录已失效」（用户以为是掉线，反复重登）",
        API,
        lambda s: s.replace('code == 403 -> "这个账号没有这个权限（$code），换有权限的账号或找派单员开权限"',
                            'code == 403 -> "登录已失效，请重新登录"', 1),
        "403 与 401 的兜底不是同一句",
    ),
    (
        "socket 把报文里的 reason 丢掉（长连接那条路又变成一句兜底）",
        SOCKET,
        lambda s: s.replace('notifyRefused("会话被服务端撤销", revokedReason(args))',
                            'notifyRefused("会话被服务端撤销", null)', 1),
        "socket 那条链也把原因带过去了",
    ),
    (
        "RealtimeHub 不把原因传给 clearSession",
        HUB,
        lambda s: s.replace("if (container.tokenStore.cachedToken() != null) container.clearSession(reason)",
                            "if (container.tokenStore.cachedToken() != null) container.clearSession()", 1),
        "socket 那条链也把原因带过去了",
    ),
    (
        "后端回归用例改名（判据按 def test_ 计数）",
        PYTEST_FILE,
        lambda s: s.replace("def test_", "def case_"),
        "后端回归用例齐",
    ),
    (
        "Android 回归用例改名（判据按 @Test 计数）",
        KTEST_FILE,
        lambda s: s.replace("@Test", "@TestX"),
        "Android 回归用例齐",
    ),
    (
        "把反向脚本从配对表里删掉（判据就再也找不到它）",
        "_tools/qa/_check_session_end_reason.py",
        lambda s: s.replace(REVERSE_CONST,
                            'REVERSE = "_tools/qa/_reverse_verify_session_end_reasonX.py"', 1),
        "配了反向验证脚本",
    ),
    (
        "把登记表里那一行改名（文档与目录不再一一对应）",
        README,
        lambda s: s.replace(README_ROW, "| " + BT + "BUG-0006x" + BT + " |", 1),
        "改动登记表里有 BUG-0006 行",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据就没全绿 —— 先修判据，再谈反验。")
        print(out)
        return 1
    print("✅ 前提成立：源码完好时判据全绿。")
    print()

    touched = sorted({rel for _d, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    misses = 0
    for desc, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = CRLF in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            print(f"⚠️  注入没生效（锚点变了，请更新本脚本）：{desc}")
            misses += 1
            continue
        payload = mutated.replace("\n", "\r\n") if crlf else mutated
        try:
            path.write_bytes(payload.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print(f"✅ {desc}")
        else:
            misses += 1
            print(f"❌ {desc} —— 期望判据变红并说出「{expect}」，实际退出码 {code}")
            print(out[-1500:])

    print()
    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        print("❌ 还原检查失败，这些文件与运行前不一致：" + "、".join(dirty))
        return 1
    print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")
    if misses:
        print(f"❌ {misses} 条注入没证明判据会红。")
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
