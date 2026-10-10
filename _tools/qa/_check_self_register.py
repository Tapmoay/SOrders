#!/usr/bin/env python3
"""自助注册的**一条主路 + 五道边界**（FEAT-0017，2026-10-11 用户要求）。

用户原话（语音转写，逐字）：
  「我们登录界面它其实可以注册账号的，只要它输入它的电话号码，必须是正确的形式，
    然后再输入密码，就可以登录/注册一个账号了，注册，然后默认账号是货主。」

## 这个功能为什么必须有一条自己的判据
它不是"又加了一个端点"，而是**把一个 2026-09-18 被主动删掉的公开写端点放了回来**。
当年删它的理由今天仍然成立（一个没人用的公开写接口就是纯攻击面），只是前提变了：
这次**连 App 入口一起加**，而且注册**不要短信验证码**。于是"它到底是安全的"这件事
完全落在**五道防线上**，而五道防线里有四道是**沉默的**——少了任何一道都不会报错：

| 防线 | 少了它的后果 | 谁会报错 |
|---|---|---|
| 默认角色写死 = 货主 | 自助注册出派单员 ⇒ 任何人都能改账号/改价/看全部账本 | 没有人 |
| 属性不从 body 取 | `{"role":"dispatcher"}` 直接提权（与上一条互为兜底） | 没有人 |
| 明文通道 426 | 密码在公网 80 上裸奔 | 没有人 |
| 同 IP 次数限流 | 一个人一分钟开一万个货主号（每个都是真账号） | 没有人 |
| 重复号 400 | 撞唯一索引 500，或在别的实现里静默改掉**别人的密码** | 只有一个 500 |

R4-BOUNDARY-JUSTIFICATION: 这五道**没有任何一道**能被扩展点、类型系统或界面约定解决 ——
它们是"公开端点上的默认值"，默认值写错时系统一切正常：注册照样成功、App 照样进得去、
用户看不出任何区别，出事时（冒出派单员 / 密码泄露 / 库里一万个垃圾号）已经晚了。
唯一能在**代码进仓库之前**抓住它们的就是一条把"主路 + 五道边界"同时钉住的机器判据。
配套的反向验证：`_tools/qa/_reverse_verify_self_register.py`（逐条注入，判据必须变红）。

## 判据口径
- **认代码形状，不认文字**：锚点都取自真正会执行的语句（`role=UserRole.SHIPPER`、
  `raise HTTPException(...400...)`、`Depends(...)`），⛔ 不锚注释里的说法 ——
  `auth.py` 的模块 docstring 里就写着这五道防线的名字，锚文字会**恒真**。
- Python 侧的"函数体"用**原文切片**（`region`）而不是 `strip_comments`：
  后者是为 Kotlin 写的（它把三引号当引号），套在 Python 模块 docstring 上会把文件剩下的部分
  全当成字符串（实测踩到过：切片变成空白 ⇒ 断言静默恒真，正是本仓库最怕的假阴性）。
- 每一条 `ok()` 的失败文案**互不相同**，反向验证才能证明"每条注入各自弄红了它该弄红的那条"。

用法：
  python _tools/qa/_check_self_register.py               # 主工作树
  python _tools/qa/_check_self_register.py <另一棵树>     # 反向验证用的临时树 / 「改前必红」
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]

AUTH = ROOT / "backend/app/api/v1/auth.py"
AUTH_SCHEMA = ROOT / "backend/app/schemas/auth.py"
GUARD = ROOT / "backend/app/services/login_guard.py"
PHONE = ROOT / "backend/app/core/phone.py"
TRANSPORT = ROOT / "backend/app/core/transport.py"
TESTS = ROOT / "backend/tests/test_self_register.py"
TEST_AUTH = ROOT / "backend/tests/test_auth.py"
DTOS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"
APIS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt"
SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/login/LoginScreen.kt"
VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/login/RegisterViewModel.kt"
INPUT_RULES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/core/InputRules.kt"

PASS = 0
FAIL: list[str] = []


def ok(cond: bool, msg: str) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(msg)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def region(src: str, signature: str, end_marker: str = "\n@router.") -> str:
    """取 `signature` 起到下一个 `end_marker` 之间的**原文**（找不到就回空串）。

    ⛔ 判空必须让调用方自己 `ok(...)` 报红 —— 本仓库被"清单为空 ⇒ 检查恒真"坑过多次
    （见 `_check_tool_scripts.py` 的 MIN_FILES、`_check_inline_role_gates.py` 的空转自检）。
    """
    i = src.find(signature)
    if i < 0:
        return ""
    j = src.find(end_marker, i + len(signature))
    return src[i:] if j < 0 else src[i:j]


auth = read(AUTH)
auth_schema = read(AUTH_SCHEMA)
guard = read(GUARD)
tests = read(TESTS)
dtos = read(DTOS)
apis = read(APIS)
screen = read(SCREEN)
vm = read(VM)

# `register` 端点体（原文；到下一个 @router. 或文件末）
reg = region(auth, '@router.post("/register"', "\n@router.")
# `RegisterRequest` 模型体
req_model = region(auth_schema, "class RegisterRequest(", "\nclass ")
# `registration_block_reason` 函数体
blk = region(guard, "def registration_block_reason(", "\ndef ")

# ---------- 0. 切片非空（这条不成立时下面每条都会假红/假绿，先单独报） ----------
ok(bool(reg.strip()), "取不到 /register 端点体（auth.py 里 @router.post(\"/register\" 不见了？）")
ok(bool(req_model.strip()), "取不到 RegisterRequest 模型体（schemas/auth.py 里没有这个类？）")
ok(bool(blk.strip()), "取不到 registration_block_reason 函数体（login_guard.py 里没有它？）")

# ---------- 1. 主路：端点存在、公开、建号、给 token ----------
ok('@router.post("/register", response_model=Token)' in auth,
   "端点不是 @router.post(\"/register\", response_model=Token)（注册要直接给 token，与登录同形状）")
ok("def register(" in reg and "body: RegisterRequest" in reg,
   "端点的入参不是 RegisterRequest")
ok("password_hash=hash_password(body.password)" in reg,
   "端点没有把口令哈希后存（⛔ 绝不能存裸口令）")
ok("db.commit()" in reg, "端点没有提交事务（注册完库里没有这个号）")
ok("build_token_response(user)" in reg,
   "端点没有返回与登录一致的 token 形状（用户注册完还得再登一次）")
ok("Depends(get_db)" in reg, "端点没接 get_db")
ok(not re.search(r"Depends\(\s*(require_permission|require_roles|CurrentUser)", reg),
   "注册端点挂了鉴权依赖 —— 它必须是**公开**的（注册的人本来就还没账号）")
ok("class Token(BaseModel)" in auth_schema and "role: UserRole" in auth_schema,
   "schemas/auth.py 的 Token 形状变了（注册与登录必须共用同一个出参）")

# ---------- 2. 边界①：默认角色 = 货主（写死在端点里，不来自入参） ----------
ok("role=UserRole.SHIPPER" in reg,
   "默认角色不是写死的货主（role=UserRole.SHIPPER 不在端点里）")
ok("is_member=False" in reg, "注册出来的号默认可能被当成批发商（is_member=False 不在端点里）")
ok("is_active=True" in reg, "注册出来的号可能默认停用（is_active=True 不在端点里）")
ok('category=""' in reg, "注册出来的号带了分类（category=\"\" 不在端点里）")
ok("username=username" in reg and "phone=phone" in reg,
   "用户名/手机号不是同一个值（登录按字符串精确匹配，两者不一致会让用户登不进去）")

# ---------- 3. 边界②：请求体带 role/is_member/… 一律无效 ----------
ok(not re.search(r"\bbody\.(role|is_member|is_active|vehicle_type|salary|billing_mode|driver_rule_id|product_scope)\b", reg),
   "端点在从请求体取 role/is_member/is_active/vehicle_type 之类的属性 —— 这是一条提权路")
ok(not re.search(r"class RegisterRequest\([^)]*\):\s*(?:.|\n)*?^\s{4}(role|is_member|is_active|vehicle_type)\s*:",
                 auth_schema, re.M),
   "RegisterRequest 声明了 role/is_member/is_active/vehicle_type 字段（就算端点不读，也不该给这个口子）")
ok("full_name" in req_model and "password" in req_model and "phone" in req_model,
   "RegisterRequest 缺少 phone/password/full_name 三者之一")
ok("MobilePhone" in req_model,
   "手机号字段用的不是 core/phone.py 的 MobilePhone（那就是第二份手机号规则）")
ok("validate_mobile_phone" in read(PHONE) and "re.ASCII" in read(PHONE),
   "core/phone.py 的手机号规则被改了（re.ASCII 少了会被全角数字绕过）")

# ---------- 4. 边界③：明文通道拒收（与登录同一道） ----------
ok("reject_plaintext_credentials(request)" in reg,
   "注册端点没有调 reject_plaintext_credentials —— 明文通道上注册会成功，密码裸奔")
i_plain = reg.find("reject_plaintext_credentials(request)")
i_db = reg.find("db.commit()")
ok(0 <= i_plain < i_db,
   "明文拦截不在 db.commit() 之前（顺序错了：先写库再拦，那条号已经建出来了）")
ok("status.HTTP_426_UPGRADE_REQUIRED" in read(TRANSPORT),
   "core/transport.py 里不再是 426（登录那道防线也被一起改了？）")

# ---------- 5. 边界④：同 IP 次数限流 ----------
ok("login_guard.registration_block_reason(" in reg,
   "注册端点没有查限流（一个人可以在一分钟里开一万个货主号）")
ok("login_guard.note_registration(" in reg,
   "注册成功没有记这次（限流计数器永远是 0，那道门等于不存在）")
ok("MAX_REGISTRATIONS_PER_IP" in guard, "login_guard 里没有注册专用阈值常量")
ok("_key(\"reg_ip\"" in blk or "_key('reg_ip'" in blk,
   "注册计数的键不是 reg_ip（换个键会让既有清场代码扫不到，本机 Redis 残留 ⇒ 假红）")
ok("login_fail:" in guard, "计数键不再是 login_fail: 前缀家族（清场代码扫的是这个前缀）")
ok("HTTPException" in reg and "HTTP_429_TOO_MANY_REQUESTS" in reg,
   "超限时没有回 429")

# ---------- 6. 边界⑤：重复号 = 明确的 400（不是 500、也不是成功） ----------
ok('detail="该手机号已存在"' in reg,
   "重复手机号没有那条中文 400（文案要与派单员建号那条逐字一致）")
ok("status.HTTP_400_BAD_REQUEST" in reg, "重复号回的不是 400")
ok(re.search(r"select\(User\)\.where\(User\.phone == phone\)", reg) is not None,
   "端点没有先查手机号是否已存在")
ok("该用户名已存在" in reg,
   "没有处理「用户名被一个老号占着」的情况（那个手机号会登进两条记录里的一条）")

# ---------- 7. 留痕：既有动作码 + 不记凭据 ----------
ok("action=OperationAction.USER_CREATE" in reg,
   "注册没有写审计，或新造了动作码（既有 USER_CREATE 就是给这件事的）")
ok("write_log(" in reg, "端点里没有 write_log(")
ok(reg.find("write_log(") < reg.find("db.commit()"),
   "审计写在 commit 之后（回滚/异常时那一行会丢）")
ok("change_payload" in reg, "审计没有带 change_payload（事后看不出建的是哪个号）")
ok("self_register" in reg,
   "审计里没有标出这是**自助注册**（与派单员建号分不开）")
ok(not re.search(r"change_payload=\{[^}]*password", reg),
   "⛔ 审计 payload 里出现了 password（连哈希也不许记）")

# ---------- 8. 两段历史都还在（这是"改这里之前必须先读"的东西） ----------
ok("2026-09-18" in auth and "2026-10-11" in auth,
   "auth.py 的模块 docstring 没有把「2026-09-18 删除 / 2026-10-11 拿回」两段历史写全")
ok("sms" in auth.lower(), "auth.py 里没提短信那条路（它是当年删除的真正原因，必须写清不做）")
ok("sms_code.py" not in auth, "auth.py 里还引用着已删除的 sms_code.py")

# ---------- 9. 单测：五道边界每条都有用例 ----------
ok(TESTS.is_file(), "缺 backend/tests/test_self_register.py")
for name, why in (
    ("def test_register_creates_a_shipper_and_returns_a_token", "主路（默认货主 + 直接给 token）"),
    ("def test_role_in_body_is_ignored", "提权（请求体带 role 无效）"),
    ("def test_bad_phone_shape_is_rejected", "手机号形状（含全角/空格）"),
    ("def test_short_password_is_rejected", "密码长度口径"),
    ("def test_duplicate_phone_is_a_clear_chinese_400", "重复号 = 中文 400"),
    ("def test_plaintext_channel_is_rejected_with_426", "明文通道 426"),
    ("def test_registration_is_rate_limited_per_ip", "同 IP 次数限流 429"),
    ("def test_each_registration_writes_one_audit_row", "审计一行且不含口令"),
    ("def test_username_collision_is_also_blocked", "用户名被老号占着"),
    ("def test_password_is_hashed_not_stored", "存的是哈希"),
):
    ok(name in tests, f"单测缺 {name}（{why}）")
ok("X-Forwarded-Proto" in tests, "明文那条用例没有造 X-Forwarded-Proto 头")
ok("login_guard.MAX_REGISTRATIONS_PER_IP" in tests,
   "限流那条用例没有按阈值算次数（改阈值就会假红）")
ok("_reset()" in tests or "login_guard.reset_for_tests()" in tests,
   "用例没有清限流计数（本机 Redis 残留会让它偶发假红）")
ok("test_sms_registration_path_is_still_closed" in read(TEST_AUTH),
   "test_auth.py 里那条「短信那条路仍然关着」不见了（当年删它的理由还在）")

# ---------- 10. Android：入口是文字链、表单三个字段、错误说人话 ----------
ok(DTOS.is_file() and APIS.is_file() and SCREEN.is_file() and VM.is_file(),
   "Android 侧缺文件（Dtos.kt / Apis.kt / LoginScreen.kt / RegisterViewModel.kt）")
ok("data class RegisterRequest(" in dtos, "Dtos.kt 里没有 RegisterRequest")
ok("auth/register" in apis, "AuthApi 里没有 @POST(\"auth/register\")")
ok("suspend fun register(" in apis, "AuthApi 里没有 register(...) 函数")
ok("RegisterDialog(" in screen, "登录页没有注册小表单")
# ⚠️ 入口这一条必须锚**文字链自己**的动作：`Text("注册新账号")` 这个串在文件里出现两次
#    （弹层的标题也叫这个），只锚那个串的话，"把入口那一行删掉、只留弹层"照样绿 ——
#    而用户要的正是"入口在那里"（弹层本身没有任何东西能点开它）。
ok("onClick = { showRegister = true }" in screen,
   "登录页没有能点开的注册入口（onClick = { showRegister = true } 不在）")
ok('Text("注册新账号")' in screen, "登录页缺少「注册新账号」这个入口的文案")
ok("TextButton(" in screen, "注册入口不是文字链（用户明确要求不抢眼，⛔ 别做成第二个大按钮）")
ok(screen.count("Button(") >= 2 and "AlertDialog(" in screen,
   "注册表单不是弹层（⛔ 别把登录页重新做成两张卡/一整页）")
ok("InputRules.mobileInput(" in screen and "RegisterViewModel.MIN_PASSWORD" in screen,
   "注册表单没有做客户端预校验（手机号形状 / 密码长度）")
ok("InputRules.mobileError(" in vm,
   "ViewModel 没有先拦一道手机号（⛔ 但也不能只靠客户端——后端那条在 auth.py 里）")
ok("container.api.authApi.register(" in vm, "ViewModel 没有调 register 端点")
ok("container.tokenStore.save(session)" in vm and "socketManager.connect(" in vm,
   "注册成功后没有落盘会话/接长连接（会表现为「注册完收不到推送」）")
ok("ApiClient.toApiException(e).message" in vm,
   "错误没有走 toApiException（后端的中文原话会显示不出来）")
ok("mobileError" in read(INPUT_RULES),
   "InputRules 里的手机号校验不见了（它与后端是同一规则的两端）")

print("PASS =", PASS)
if FAIL:
    print("❌ 以下 %d 条不成立：" % len(FAIL))
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("✅ 全部 %d 项通过：注册主路（默认货主 + 直接给 token）与五道边界"
      "（提权 / 明文 / 限流 / 重复号 / 审计）都在，Android 侧入口是文字链 + 小表单"
      "（FEAT-0017，2026-10-11）。" % PASS)
