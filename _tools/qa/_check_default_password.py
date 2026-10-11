#!/usr/bin/env python
"""**所有账号的初始密码默认是 123321**（CHG-0118）的机器判据。

用户 2026-10-11 的口径（逐字）：「我们的所有账号初始密码默认是 123321，这是**规定死的**。
AI 也要知道 —— 比如说我叫它创建一个账号，它**直接帮我创建好、不要问我密码是什么**。」

盯住五件事（缺一件这条规定就没落地，而**每一件坏掉都不报错**）：

1. **后端有一处默认**：常量 security.py::DEFAULT_INITIAL_PASSWORD 存在且是 123321；
   UserCreate.password 的字段默认值**引用它**（不是抄一份字面量）；不给密码也能构造出请求体。
2. **字面量只有一处**（Python 侧）：backend/app 里 123321 只出现在那个常量赋值上
   —— 两处写字面量迟早分叉，届时"卡片说 123321、库里是别的"，没人会收到报错。
3. **AI 那条链**：users.create 的密码参数是**可选**（required = false）、说明里写明"不填用默认"、
   卡片写明用的是默认初始密码、执行时真的发出去；**提示词里写着"建账号不要追问密码"**。
4. **手工建号也有默认**：两个建号表单的 openCreate() 预填 AccountRules.passwordDraft(false)，
   而 openEdit() 必须是空串（预填 = 把别人的密码静默重置）。
5. **既有红线没被动**：密码不进审计 payload、不进返回体；"改密码"仍然是必填；
   _check_secrets.py 没被我们放宽（值豁免与命令行口令那条判据都还在）。

R4-BOUNDARY-JUSTIFICATION: 这条判据**不下沉到任何一层边界**。被查的五件事全是"同一个数写在哪、
谁读它"：常量在哪定义、schema 的默认值是不是引用它、给模型看的参数说明怎么写、卡片上那句话在不在、
表单初值是多少 —— 后端契约（UserCreate 的字段类型没变、仍然 str）、领域类型、权限模型里
都没有它们的位置。反过来：把常量抽到任何一层边界去也解决不了它要防的病（**两处字面量分叉**），
因为分叉发生在"有人又抄了一遍"的那一刻，边界看不见那一刻。

用法：python _tools/qa/_check_default_password.py   （--list 打一份人读清单）
"""

from __future__ import annotations

import io
import re
import sys
import tokenize
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SECURITY = BACKEND / "app/core/security.py"
SCHEMA = BACKEND / "app/schemas/user.py"
USERS_API = BACKEND / "app/api/v1/users.py"
PY_TEST = BACKEND / "tests/test_default_initial_password.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
AND_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders"
RULES = AND / "core/AccountRules.kt"
MASTER = AND / "ai/AiWriteMasterData.kt"
LOOP = AND / "ai/AiAgentLoop.kt"
ACC_VM = AND / "ui/dispatcher/AccountManageViewModel.kt"
USERS_VM = AND / "ui/dispatcher/UsersManageViewModel.kt"
ACC_SCREEN = AND / "ui/dispatcher/AccountManageScreen.kt"
KT_RULES_TEST = AND_TEST / "core/AccountRulesTest.kt"
KT_AI_TEST = AND_TEST / "ai/AiWriteTest.kt"

DOC = ROOT / "docs/ACCOUNT_RULES.md"
CHG = ROOT / "docs/changes/CHG-0118.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
MAP_INDEX = ROOT / "docs/PROJECT_MAP/INDEX.md"
BACKEND_DETAILS = ROOT / "docs/PROJECT_MAP/03_BACKEND_DETAILS.md"
SECRETS_CHECK = ROOT / "_tools/qa/_check_secrets.py"
REVERSE = ROOT / "_tools/qa/_reverse_verify_default_password.py"

NUM = "123321"


def py_code(src: str) -> str:
    """Python 源码**去掉注释**后的正文（用 tokenize，字符串里的 # 不会被误删）。"""
    try:
        toks = tokenize.generate_tokens(io.StringIO(src).readline)
        return " ".join(t.string for t in toks if t.type != tokenize.COMMENT)
    except Exception:
        return src


def block_after(src: str, needle: str, stop: str, limit: int = 6000) -> str:
    """从 needle 起、到 stop 为止的一段（找不到返回空串 —— 调用方必须显式判空）。"""
    i = src.find(needle)
    if i < 0:
        return ""
    j = src.find(stop, i + len(needle))
    return src[i: j if j > 0 else min(len(src), i + limit)]


def fn_body(src: str, header: str) -> str:
    """Kotlin 函数体：从 header 起，到下一个同缩进的 fun / private fun 为止。"""
    i = src.find(header)
    if i < 0:
        return ""
    rest = src[i + len(header):]
    m = re.search(r"\n {4}(?:private )?fun ", rest)
    return rest[: m.start()] if m else rest[:3000]


def const_of(src: str, name: str) -> str:
    m = re.search(re.escape(name) + r'\s*=\s*"([^"]*)"', src)
    return m.group(1) if m else ""


def main() -> int:
    c = Checker()
    needed = [SECURITY, SCHEMA, USERS_API, PY_TEST, RULES, MASTER, LOOP, ACC_VM, USERS_VM,
              ACC_SCREEN, KT_RULES_TEST, KT_AI_TEST, DOC, CHG, REGISTRY, CLAIM, REVERSE]
    missing = [str(p.relative_to(ROOT)) for p in needed if not p.exists()]

    c.section("0. 反空转（少一个文件就先喊，别让它空过）")
    c.ok(f"被检查的 {len(needed) - len(missing)} 个文件都在", not missing, "缺：" + "、".join(missing))
    if missing:
        print("\n" + "=" * 60)
        print(f"❌ 文件不全（{len(missing)} 个缺），后面的判据没有意义")
        return 1

    sec_src = read(SECURITY)
    schema_src = read(SCHEMA)
    api_src = read(USERS_API)

    # ── 1. 后端：常量 + 唯一一处默认（运行时不变量，不是文本）────────────────
    c.section("1. 后端：常量 + 唯一一处默认")
    const_value = const_of(sec_src, "DEFAULT_INITIAL_PASSWORD")
    c.ok(f"常量在（security.py::DEFAULT_INITIAL_PASSWORD = {const_value or '没找到'}）",
         const_value == NUM,
         "这条规定就是 123321；改它要先改 docs/ACCOUNT_RULES.md 与用户口径")

    runtime_ok = True
    runtime_why = ""
    try:
        sys.path.insert(0, str(BACKEND))
        from app.core.security import DEFAULT_INITIAL_PASSWORD  # noqa: E402
        from app.schemas.user import UserCreate  # noqa: E402
    except Exception as exc:  # 环境问题也要喊出来，不许静默跳过
        runtime_ok = False
        runtime_why = f"导不进后端模块（{exc}）—— 后面的运行时断言没法做，不算通过"
        DEFAULT_INITIAL_PASSWORD = None  # type: ignore[assignment]
        UserCreate = None  # type: ignore[assignment]
    if not runtime_ok:
        c.ok("运行时断言（导入后端模块）", False, runtime_why)
    else:
        c.ok(f"security.py 导出来就是 {DEFAULT_INITIAL_PASSWORD}（运行时，不是 grep）",
             DEFAULT_INITIAL_PASSWORD == NUM)
        field = UserCreate.model_fields["password"]
        c.ok("UserCreate.password 的字段默认值**就是那个常量**（默认只有一处）",
             field.default == DEFAULT_INITIAL_PASSWORD,
             f"现在默认值是 {field.default!r} —— 是必填（PydanticUndefined）还是又抄了一份字面量？")
        try:
            got = UserCreate(phone="13500118111", role="shipper").password
        except Exception as exc:
            got = f"构造失败：{exc}"
        c.ok("不给密码也能构造出建号请求体（'可选'在 schema 层就成立）",
             got == DEFAULT_INITIAL_PASSWORD, f"实际拿到 {got!r}")
        try:
            given = UserCreate(phone="13500118112", role="shipper", password="Zx9-Qw2-By7").password
        except Exception as exc:
            given = f"构造失败：{exc}"
        c.ok("给了密码就用给的（默认值不许盖掉用户给的）",
             given == "Zx9-Qw2-By7", f"实际拿到 {given!r}")
        try:
            UserCreate(phone="13500118113", role="shipper", password="12345")
            short_ok = False
        except Exception:
            short_ok = True
        c.ok("5 位密码照样被拒（min_length=6 没被这次改动碰掉）", short_ok,
             "默认值 6 位是下限；放宽它等于把'默认'变成'随便'")

    # ── 2. 字面量只有一处（Python 侧）──────────────────────────────────────
    c.section("2. 字面量只有一处（Python 侧）")
    c.ok(f"security.py 的**代码**里 {NUM} 出现 {py_code(sec_src).count(NUM)} 次（应为 1）",
         py_code(sec_src).count(NUM) == 1, "两处以上 = 又抄了一份，迟早分叉")
    c.ok(f"schemas/user.py 的代码里 {NUM} 出现 {py_code(schema_src).count(NUM)} 次（应为 0）",
         py_code(schema_src).count(NUM) == 0, "默认值必须引用常量，不许抄字面量")
    create_body = block_after(api_src, "def create_user(", "\n@router.")
    c.ok("create_user 里没有第二份默认值（0 次字面量）", create_body.count(NUM) == 0,
         "建号端点自己再写一遍 = 规定有两个真相")

    # ── 3. AI 那条链：参数可省 + 卡片写明 + 真的发出去 ──────────────────────
    c.section("3. AI 那条链（参数 / 卡片 / 执行）")
    # ⚠️ 一律比**去掉注释后的代码**（strip_comments 保留字符串字面量）：
    #    注释里写"这里必须写明用的是默认初始密码"是好事，但它不能顶替真正的代码 ——
    #    反向验证抓到过：把真代码删掉、注释还在，判据照样绿（那就是一条假判据）。
    master_src = strip_comments(read(MASTER))
    create_block = block_after(master_src, "id = AiWrites.USERS_CREATE", "\n        crud(")
    c.ok("users.create 这一段抓到了（抓不到的话下面几条是空转）", len(create_block) > 800)
    pwd_field = next((ln for ln in create_block.splitlines() if 'textField("password"' in ln), "")
    c.ok("密码字段不再是必填（required = false）",
         "required = false" in pwd_field,
         f"现在这一行是：{pwd_field.strip()[:120]}")
    c.ok("密码字段的说明写明'不填用默认初始密码'（模型只照说明写字）",
         "AccountRules.DEFAULT_INITIAL_PASSWORD" in pwd_field and "不用问用户" in pwd_field)
    c.ok("「不要自己编一个」这条限制仍在（含义收窄成'只能是默认值或用户给的'）",
         "不要自己编一个" in pwd_field)
    c.ok("密码字段仍然标着 secret = true（值进 payload、不上卡片）", "secret = true" in pwd_field)
    c.ok("卡片正文写明用的是默认初始密码（AccountRules.DEFAULT_PASSWORD_NOTE）",
         "AccountRules.DEFAULT_PASSWORD_NOTE" in create_block,
         "没有它，用户只能靠猜这个账号的密码是什么")
    c.ok("用户给了密码时卡片仍是「已设置，不显示」（不回显那条红线没松）",
         "密码：已设置，不显示" in create_block)
    c.ok("执行时没填就用默认（ifBlank { AccountRules.DEFAULT_INITIAL_PASSWORD }）",
         "ifBlank { AccountRules.DEFAULT_INITIAL_PASSWORD }" in create_block,
         "卡片说用默认、实际发别的 = 最坏的一种：用户拿默认密码登不进去")
    setpwd = block_after(master_src, "id = AiWrites.USERS_SET_PASSWORD", "\n        crud(")
    c.ok("users.set_password 这一段也抓到了", len(setpwd) > 400)
    setpwd_field = next((ln for ln in setpwd.splitlines() if 'textField("password"' in ln), "")
    c.ok("改密码（users.set_password）仍然是必填、仍然要求用户明确给出",
         "required = true" in setpwd_field,
         "「初始密码」有默认值，'改密码'没有 —— 这条规定不适用它")

    # ── 4. 提示词：不要追问密码 ────────────────────────────────────────────
    c.section("4. 提示词（AI 不该为了密码去追问）")
    loop_src = strip_comments(read(LOOP))  # 同上：注释里写一句不算
    c.ok("提示词里写明「不要追问密码」", "不要追问密码" in loop_src,
         "少了它，模型会照「不知道就去问」那条先反问密码")
    rule_block = block_after(loop_src, "例外（这是规定", 'appendLine("   - 成本与毛利')
    c.ok("这条例外抓到了（抓不到说明锚点变了，下面的判据会空过）", len(rule_block) > 200)
    c.ok("例外里点出默认值（AccountRules.DEFAULT_INITIAL_PASSWORD）",
         "AccountRules.DEFAULT_INITIAL_PASSWORD" in rule_block)
    c.ok("例外里同时说明：改一个已有账号的密码**仍然要问**",
         "改一个已有账号的密码" in rule_block,
         "只写前半句会把'改密码'也变成不问自取")
    c.ok("原来的「不知道就去问」那条还在（没被这段顶掉）", "绝不许替他决定" in loop_src)

    # ── 5. 手工建号表单：新建预填、编辑空串 ────────────────────────────────
    c.section("5. App 建号表单（手工建号也一个默认）")
    rules_src = read(RULES)
    kt_value = const_of(rules_src, "DEFAULT_INITIAL_PASSWORD")
    c.ok("AccountRules.DEFAULT_INITIAL_PASSWORD 与后端常量一致",
         kt_value == const_value and kt_value == NUM,
         f"Kotlin {kt_value!r} vs Python {const_value!r}")
    # ⚠️ 比的是**去掉注释后的代码**（strip_comments 保留字符串字面量）：
    #    注释里写一句"所有账号初始密码默认是 123321"是**好事**（下一个人看代码就知道），
    #    要防的是**代码里又抄了一份字面量**。
    offenders = [str(p.relative_to(ROOT)) for p in AND.rglob("*.kt")
                 if p != RULES and NUM in strip_comments(read(p))]
    c.ok(f"Kotlin 主代码里 {NUM} 只出现在 AccountRules.kt（其它 {len(offenders)} 个文件）",
         not offenders, "又抄了一遍：" + "、".join(offenders[:5]))
    acc_vm_src = read(ACC_VM)
    usr_vm_src = read(USERS_VM)
    c.ok("账户管理 openCreate() 预填默认值",
         "passwordDraft(isEdit = false)" in fn_body(acc_vm_src, "fun openCreate()"))
    c.ok("账户管理 openEdit() 是空串（= 不改密码）",
         "passwordDraft(isEdit = true)" in fn_body(acc_vm_src, "fun openEdit("),
         "预填会把'只改个手机号'变成'静默重置密码'")
    c.ok("用户/司机管理 openCreate() 预填默认值",
         "passwordDraft(isEdit = false)" in fn_body(usr_vm_src, "fun openCreate()"))
    c.ok("用户/司机管理 openEdit() 是空串",
         "passwordDraft(isEdit = true)" in fn_body(usr_vm_src, "fun openEdit("))
    c.ok("新增账户的密码框占位里写着默认值（用户看得见）",
         "AccountRules.DEFAULT_INITIAL_PASSWORD" in strip_comments(read(ACC_SCREEN)))
    c.ok("passwordDraft 的语义写在代码里（编辑返回空串）",
         'if (isEdit) "" else DEFAULT_INITIAL_PASSWORD' in rules_src)

    # ── 6. 既有红线没被动 ─────────────────────────────────────────────────
    c.section("6. 既有红线（审计不回显 / 返回体 / secrets 判据没被放宽）")
    # ⚠️ 必须**在 create_user 的函数体里**找 payload：`change_payload={` 这个串在本文件里
    #    出现 9 次（第一个在 L114，是另一个端点）——按全文找会抓到别人那一段，判据就成了空转。
    #    反向验证抓到过这一点（把密码插进建号 payload，判据照样绿）。
    create_fn = block_after(api_src, "def create_user(", "\n@router.")
    payload = block_after(create_fn, "change_payload={", "},")
    c.ok("建号那一段 payload 抓到了（抓不到的话下一条是空转）",
         "username" in payload, f"抓到的是：{payload.strip()[:120]}")
    c.ok("审计 payload 里没有 password（明文与哈希都不许进）",
         "password" not in payload.lower() and "password_hash" not in payload.lower(),
         "operation_logs 是给人看的审计页，不是凭据库")
    c.ok("建号仍然是 hash_password(body.password)（密码真的被用上了）",
         "hash_password(body.password)" in api_src)
    user_out = block_after(schema_src, "class UserOut", "class UserCreate")
    c.ok("UserOut 里没有 password 字段", "password" not in user_out.lower())
    secrets_src = read(SECRETS_CHECK)
    c.ok("_check_secrets.py 的 DEV_VALUES 仍然豁免 123321（我们没为过关去动它）",
         '"123321"' in secrets_src)
    c.ok("_check_secrets.py 的「命令行内联口令」判据还在（那次泄露的教训不许丢）",
         "LEAKED" in secrets_src and "password" in secrets_src)

    # ── 7. 文书与单测在位（让"下一个人不用问"）────────────────────────────
    c.section("7. 文书与单测")
    doc_src = read(DOC)
    c.ok("docs/ACCOUNT_RULES.md 存在且写着规定与默认值", NUM in doc_src and "规定" in doc_src)
    c.ok("账号规定不是孤儿文档（PROJECT_MAP/INDEX.md 里有一行指向它）",
         "ACCOUNT_RULES.md" in read(MAP_INDEX))
    c.ok("后端细节页也指了一笔（03_BACKEND_DETAILS.md）", "ACCOUNT_RULES.md" in read(BACKEND_DETAILS))
    chg = read(CHG)
    c.ok("docs/changes/CHG-0118.md 九节齐全",
         all(("## " + s) in chg for s in "①②③④⑤⑥⑦⑧⑨"),
         "少了哪一节？① 六问 ② Must Change ③ Boundary ④ Behavior ⑤ Data ⑥ CHG 专章 ⑦ 测试 ⑧ 证据 ⑨ 关闭")
    c.ok("变更单**点名**规定写在哪（ACCOUNT_RULES.md）", "ACCOUNT_RULES.md" in chg)
    c.ok("登记簿里有 CHG-0118 这一行",
         re.search(r"^\|\s*.CHG-0118.\s*\|", read(REGISTRY), re.M) is not None)
    c.ok("声明页里有 CHG-0118", "CHG-0118" in read(CLAIM))
    n_tests = len(re.findall(r"^def test_", read(PY_TEST), re.M))
    c.ok(f"后端单测 >= 6 例（实际 {n_tests}）", n_tests >= 6)
    ai_test = read(KT_AI_TEST)
    c.ok("App 单测钉住'不问密码就用默认'与'给了就用给的'",
         "不填就用规定的默认初始密码" in ai_test and "给了密码就用给的" in ai_test)
    c.ok("AccountRulesTest 在位", "class AccountRulesTest" in read(KT_RULES_TEST))

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, detail in c.fails:
            print(f"   - {label}")
            if detail:
                print(f"       {detail}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：后端一处默认（引用常量、非字面量）、AI 参数可省且卡片写明用的是 "
          f"默认为 {NUM}、提示词写了「不要追问密码」、两个建号表单都预填、编辑留空；"
          f"改密码仍必填、审计与返回体都不含密码、secrets 判据没被放宽；文书与单测在位。")
    return 0


if __name__ == "__main__":
    if "--list" in sys.argv:
        print("== 它到底在查什么（所有账号初始密码默认 123321 · CHG-0118）==")
        print("1. 后端常量 = 123321，UserCreate.password 的默认值**引用它**，不给密码也能构造")
        print("2. Python 侧字面量只有一处（security.py 的常量赋值），schema 与端点都不许再抄")
        print("3. AI：users.create 密码参数 required=false、说明写明不填用默认、卡片写明用的是默认值、")
        print("   执行时 ifBlank 落默认；改密码 users.set_password 仍然必填")
        print("4. 提示词里写着「建账号不要追问密码」（并保留'改密码仍然要问'）")
        print("5. 两个建号表单 openCreate 预填默认、openEdit 空串；Kotlin 主源码里字面量只有一处")
        print("6. 既有红线没被动：审计 payload 无 password、UserOut 无 password、_check_secrets.py 没被放宽")
        print("7. 文书（ACCOUNT_RULES.md 可达 + 变更单九节 + 登记簿 + 声明页）与单测在位")
    else:
        sys.exit(main())
