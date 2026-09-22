"""红线：**同一账号不许两台手机同时登录**（测试号段豁免）—— 2026-09-22 用户要求。

## 由来（用户原话）

> 「还做一个叫什么**防止两部手机同时登一个账号**，**测试账号除外** —— 只要是真实的账号的话，
>  他**不能在两部手机上同时登录**。」
> 「**也就是现在我们用的账号的形式全都自动豁免**。主要改变的就是**后面的尾号最多 9 个**。」

拍板：第二台登录时**后来者顶掉先登的**。

## 这条判据守的事，坏起来一句报错都没有

| 写坏的方式 | 表现 |
|---|---|
| 登录时压根不撤销（或被顺手删掉） | 两台手机长期同时在线，界面上一切正常 |
| 撤销了但**忘了 commit**，或 commit 在签发**之后** | 新令牌带着库里没生效的 `tv` → **刚登录就"登录已失效"**，用户自己都进不来 |
| 只 `bump_token_version`、不走 `revoke_tokens_and_sockets` | 旧那台 HTTP 全 401，**但推送照收**（外部检查 C-3 就是这条：只作废令牌不断长连接） |
| 豁免判据放宽成 `startswith(前缀)` | `13800000001234` 这种真实号被**悄悄放行** |
| 豁免判据在第二个文件里再写一遍 | 某一条路径把真实账号也放行，而两边都不报错 |
| 登录**失败**那条分支里也撤销 | 别人拿你手机号连打几次错密码，就能把你从自己手机上踢下线 |
| 把 `deps.py` 的 `tv` 校验删掉 | 本方案整个失去立足点（撤销了也没人查） |

## 判据（清单全部自己算）

1. `is_test_account` / 号段常量**只有一处定义**，且只在 `services/auth_service.py`；
   边界判据（**前缀 + 一位 1~9**）三个要素都在（长度、数字、范围）—— 少一个就是放宽了。
2. `_login` 里：**先撤销 → 再 commit → 最后签发**（顺序用下标比，比"有没有出现"强得多）。
3. 撤销走的是 `revoke_tokens_and_sockets`（不是裸 `bump_token_version`）。
4. 撤销只出现在**认证成功之后**：失败分支（`note_failure`）里不许有它。
5. `deps.get_current_user` 仍在比对 `tv`（核心文件，本方案只**用**它、不改它）。
6. `ai_test_phone_prefix` **没有**被拿来当豁免判据（那是"谁能用服务端默认 AI key"，
   合并会让"打开 AI 默认 key"顺手放宽登录限制）。
7. 反空转：文件在、切出来的 `_login` 函数体非空、认出的关键调用 ≥3 处。
8. 文档：`08_CODE_LOCATOR.md` 的登录/鉴权那一行记着这条规矩。

⚠️ 注入式反向验证（改坏 → 本脚本必须红）：`_tools/qa/_reverse_verify_single_session.py`。

用法：python _tools/qa/_check_single_session.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend/app"
AUTH = BACKEND / "api/v1/auth.py"
SVC = BACKEND / "services/auth_service.py"
DEPS = BACKEND / "deps.py"
CONFIG = BACKEND / "config.py"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"

#: 顺序判据要看的三个动作
REVOKE = "revoke_tokens_and_sockets("
COMMIT = "db.commit()"
ISSUE = "build_token_response("


class Checker:
    def __init__(self) -> None:
        self.n_ok = 0
        self.fails: list[tuple[str, str]] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.n_ok += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append((label, detail))
            print(f"  [!!]   {label}")
            if detail:
                print(f"         {detail}")

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（改名/移动了？本脚本的判据要跟着改，不许静默跳过）")
    return io.open(p, encoding="utf-8", errors="replace", newline="").read()


def py_code(text: str) -> str:
    """剥掉三引号串与 `#` 注释（**保住行数**）。

    ⚠️ 必须剥：下面要比"谁先谁后"，而 `_login` 的文档字符串里正好**逐个提到了**这三个调用
    （`revoke` / `commit` / `build_token_response` 都写在解释里）—— 不剥的话，
    把撤销整块删掉、只留注释，判据照样绿（那就是一条空转的判据）。
    """
    text = re.sub(r'"""(?:.|\n)*?"""', lambda m: "\n" * m.group(0).count("\n"), text)
    text = re.sub(r"'''(?:.|\n)*?'''", lambda m: "\n" * m.group(0).count("\n"), text)
    # 够用即可：这几个文件里没有含 `#` 的字符串常量（有的话下面这条会切早，届时先修本函数）
    return "\n".join(line.split("#", 1)[0] for line in text.split("\n"))


def func_body(code: str, name: str) -> str:
    """按**缩进**切一个 Python 函数的函数体（下一个顶格 `def`/`class`/`@` 之前）。"""
    m = re.search(rf"^def {re.escape(name)}\(", code, re.M)
    if not m:
        return ""
    rest = code[m.end():]
    nxt = re.search(r"^(?:def |class |@)", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def main() -> int:
    if refuse_if_injecting("单设备登录红线"):
        return 1

    c = Checker()
    auth = py_code(read(AUTH))
    svc = py_code(read(SVC))
    svc_raw = read(SVC)
    deps = py_code(read(DEPS))
    config = read(CONFIG)
    locator = read(LOCATOR)

    # ---- ① 豁免判据只有一处，且边界三要素都在 ----
    c.section("豁免判据：只有一处实现，且边界是「前缀 + 一位 1~9」")
    defs = [p for p in BACKEND.rglob("*.py") if "def is_test_account(" in read(p)]
    c.ok(
        f"`def is_test_account(` 全树只有一处（实测 {len(defs)}：{[str(p.relative_to(ROOT)) for p in defs]}）",
        defs == [SVC],
        "各写一份的后果是某条路径把真实账号也放行，而两边都不报错",
    )
    body = func_body(svc, "is_test_account")
    c.ok("切出了 is_test_account 的函数体（切不出＝判据要跟着改，不许静默通过）", "return" in body,
         f"截到 {body[:60]!r}")
    c.ok("边界①：长度必须等于「前缀 + 1 位」（防 `13800000001234` 被放过）",
         "len(p) !=" in body or "len(p) ==" in body)
    c.ok("边界②：尾号必须是数字", ".isdigit()" in body)
    c.ok("边界③：范围是 1~TEST_ACCOUNT_TAIL_MAX（用户：「尾号最多 9 个」）",
         "<= TEST_ACCOUNT_TAIL_MAX" in body and re.search(r"1\s*<=\s*int\(tail\)", body) is not None,
         f"实际函数体：{body.strip()[:120]!r}")
    c.ok("号段常量只有一处定义，且只在本文件被引用",
         svc_raw.count("TEST_ACCOUNT_PHONE_PREFIX = ") == 1
         and all("TEST_ACCOUNT_PHONE_PREFIX" not in read(p)
                 for p in BACKEND.rglob("*.py") if p != SVC))
    c.ok("⛔ 没有拿 `ai_test_phone_prefix` 当豁免判据（那是「谁能用服务端默认 AI key」）",
         "ai_test_phone_prefix" not in svc,
         "合并的话，「打开 AI 默认 key」会顺手放宽登录限制 —— 两件事没有任何关系")
    c.ok("config.py 里那个设置还在原位（不是被我搬走/改名了）",
         "ai_test_phone_prefix" in config)

    # ---- ② 登录路径：先撤销 → 再 commit → 最后签发 ----
    c.section("登录路径：先撤销旧会话 → commit → 再签发新令牌（顺序不能反）")
    login = func_body(auth, "_login")
    c.ok("切出了 _login 的函数体（切不出＝判据要跟着改）", len(login) > 200, f"实际 {len(login)} 字符")
    c.ok("登录时真的撤销了（真的调了那个入口）", REVOKE in login)
    c.ok("撤销走的是 revoke_tokens_and_sockets（不是裸 bump_token_version）",
         "bump_token_version(" not in login,
         "只推进版本号＝旧那台 HTTP 401、**但推送照收**（外部检查 C-3）")
    i_rev, i_commit, i_issue = login.find(REVOKE), login.find(COMMIT, login.find(REVOKE)), login.find(ISSUE)
    c.ok(
        f"⛔ 顺序：撤销({i_rev}) < commit({i_commit}) < 签发({i_issue})",
        -1 < i_rev < i_commit < i_issue,
        "先签发再 commit 的话，新令牌带着库里没生效的 tv → **刚登录就「登录已失效」**，而日志里没有异常",
    )
    c.ok("撤销挂在豁免判据下（测试号段不受影响）",
         re.search(r"if not is_test_account\(user\.phone\):\s*\n\s+revoke_tokens_and_sockets\(", login) is not None)
    # 失败分支的边界要用**它自己的下一条语句**（`raise`）来收口：按固定字符数切的话，
    # 窗口会把后面的撤销块也圈进来，于是这条判据永远红/永远绿（第一版就是 300 字符切多了）。
    fail_start = login.find("note_failure")
    fail_end = login.find("raise", fail_start) if fail_start >= 0 else -1
    fail_branch = login[fail_start:fail_end] if fail_start >= 0 and fail_end > fail_start else ""
    c.ok("⛔ 认证**失败**那条分支里没有撤销（否则打错密码就能把人踢下线）",
         bool(fail_branch) and REVOKE not in fail_branch,
         f"失败分支截到 {fail_branch[:80]!r}")

    # ---- ③ 立足点：deps 的 tv 校验还在 ----
    c.section("立足点：deps.get_current_user 仍在比对 tv（核心文件，本方案只**用**它）")
    c.ok("deps.py 里读令牌的 tv", 'payload.get("tv"' in deps)
    c.ok("deps.py 里比库里的 token_version（写法是 getattr，为了容老对象）",
         "token_version" in deps)
    c.ok("对不上就 401（`credentials_exc`）",
         re.search(r'"tv"[\s\S]{0,200}?credentials_exc', deps) is not None)

    # ---- ④ 反空转 ----
    c.section("反空转：关键调用数、被切的块都不能是空的")
    n_calls = login.count(REVOKE) + login.count(COMMIT) + login.count(ISSUE)
    c.ok(f"_login 里三个关键调用合计 ≥3 处（实测 {n_calls}）", n_calls >= 3)

    # ---- ⑤ 文档 ----
    c.section("文档：定位表里记着这条规矩（**含「谁顶掉谁」这个方向**）")
    c.ok("08_CODE_LOCATOR.md 写明「后来者顶掉先登的」",
         "后来者顶掉先登的" in locator,
         "只写「有这个功能」不够 —— 方向反了（先登的顶掉后来者）是另一种产品语义，"
         "而这句话正是下一个人照着实现时的依据")
    c.ok("并且点名了豁免判据与它的红线",
         "is_test_account" in locator and "_check_single_session.py" in locator)

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for label, detail in c.fails:
            print("   - " + label + (f" —— {detail}" if detail else ""))
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：真实账号单设备登录（后来者顶掉先登的），测试号段豁免。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
