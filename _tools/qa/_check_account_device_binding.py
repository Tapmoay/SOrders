#!/usr/bin/env python3
"""账号 ↔ 设备绑定与风控的**一条主路 + 六道闸**（FEAT-0018，2026-10-11 用户要求）。

用户原话（语音转写，逐字要点）：
  「一个账号大概只能绑定一个手机/一个设备（mac/设备序列号，唯一）。只不过……也不说完全只能
    绑定 3 个吧，如果超过了 3 个的话，它后面想接着绑定其他手机就不能瞬间，它是有时间限制的……
    大概它如果要再次再增加一个的话，就要过 6 个月了」；
  「我们的一个设备（一个唯一的设备地址）不能同时间、短时间内绑定多个账号 —— 防止有人利用
    这个漏洞批量注册一堆账号来攻击服务器」；
  「**测试账号除外**（内部账号没有这些限制，随便登录）」；
  同日口径更新：「一台设备也就是一部手机，它可以绑多部账号，**至少是可以绑 5 个**」；
  追加拍板：「6 个月冷却**保留**，但**派单员在账号管理里可以手动解冻**（就在编辑当中）——
  司机换手机、手机摔坏了，联系派单员解冻即可」。

## 这个功能为什么必须有一条自己的判据
六道闸里有**五道是沉默的**：少了任何一道，系统一切正常 —— 登录照样成功、App 照样进得去、
用户看不出区别，出事时（一个号被卖了 20 个人共用 / 一台设备刷出几百个号 / 老账号永远换不了
手机）已经晚了。它们唯一共同的可见痕迹是"某一天盘库里发现 account_devices 长得不对劲"。

| 闸 | 少了它的后果 | 谁会报错 |
|---|---|---|
| 一个账号 3 台（有效绑定） | 一个号被无限共用，风控形同虚设 | 没有人 |
| 6 个月冷却（以 bound_at 为准） | 换个手机就换一个号 ⇒ 3 台形同虚设 | 没有人 |
| 顶掉的是**最早绑的**那台 | 顶掉刚绑的新机，用户当场被踢回登录页 | 没有人 |
| 一台设备 5 个账号（硬上限） | 一台手机批量开号，正是用户要防的那件事 | 没有人 |
| 一台设备 24h 新增 ≤2（速率） | 脚本一分钟把这台设备的 5 个额度刷满 | 没有人 |
| 注册：同设备 24h ≤1 个新号 | 批量刷号的成本从"要花时间"变回一条 curl | 没有人 |
| 测试号三条全跳过 | 内部号被锁在门外（用户：「随便登录」） | 只有测试同事 |
| 派单员解冻（手工出口） | 司机换手机只能干等 6 个月，用户拍板的出路没了 | 只有用户投诉 |

R4-BOUNDARY-JUSTIFICATION: 这八条**没有一条**能被扩展点、类型系统或界面约定解决 ——
它们是"同一段业务规则在**两个入口**（登录 / 注册）上的阈值与顺序"：阈值改一个字
（6 个月 → 0、5 → 1、24h 2 → 无限），或者顺序挪一句（设备闸挪到 revoke 之后、
注册的设备闸挪到建号之后），代码照样跑、测试照样绿 —— 因为**没有任何东西会变红**。
唯一能在**代码进仓库之前**抓住它们的就是一条把"主路 + 六道闸 + 豁免 + 手工出口"同时钉住的
机器判据。配套的反向验证：`_tools/qa/_reverse_verify_account_device_binding.py`
（逐条注入，判据必须变红，末尾逐字节还原）。

## 判据口径
- **认代码形状，不认文字**：锚点都取自真正会执行的语句（`if expires_at > now:`、
  `replaced.unbind_reason = UNBIND_REASON_EXPIRED`、`Depends(require_permission(...))`），
  ⛔ 不锚注释里的说法 —— 本模块自己的模块 docstring 里就写着这六道闸的名字，锚文字会**恒真**。
- Python 侧的"函数体"用**原文切片**（`region`），⛔ 不剥注释：剥注释是为 Kotlin 写的
  （它把三引号当引号），套在 Python 模块 docstring 上会把文件剩下的部分全当成字符串。
- 每一条 `ok()` 的失败文案**互不相同**，反向验证才能证明"每条注入各自弄红了它该弄红的那条"。

用法：
  python _tools/qa/_check_account_device_binding.py               # 主工作树
  python _tools/qa/_check_account_device_binding.py <另一棵树>     # 反向验证用的临时树 / 「改前必红」
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]

DEV_SVC = ROOT / "backend/app/services/device_service.py"
DEV_API = ROOT / "backend/app/api/v1/devices.py"
DEV_SCHEMA = ROOT / "backend/app/schemas/device.py"
DEV_MODEL = ROOT / "backend/app/models/account_device.py"
MIGRATION = ROOT / "backend/app/migrations/031_account_devices.py"
AUTH = ROOT / "backend/app/api/v1/auth.py"
USERS = ROOT / "backend/app/api/v1/users.py"
GUARD = ROOT / "backend/app/services/login_guard.py"
ENUMS = ROOT / "backend/app/models/enums.py"
ROUTER = ROOT / "backend/app/api/v1/router.py"
MODELS_INIT = ROOT / "backend/app/models/__init__.py"
TESTS = ROOT / "backend/tests/test_device_binding.py"
REPORT_CENTER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"

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

    ⛔ 判空必须让调用方自己 `ok(...)` 报红 —— 本仓库被"清单为空 ⇒ 检查恒真"坑过多次。
    """
    i = src.find(signature)
    if i < 0:
        return ""
    j = src.find(end_marker, i + len(signature))
    return src[i:] if j < 0 else src[i:j]


def slice_to_end(src: str, signature: str) -> str:
    """取 `signature` 起到**文件末尾**的原文（找不到回空串）—— 用于"这一段之后全是我的"。"""
    i = src.find(signature)
    return "" if i < 0 else src[i:]


svc = read(DEV_SVC)
dev_api = read(DEV_API)
dev_schema = read(DEV_SCHEMA)
dev_model = read(DEV_MODEL)
migration = read(MIGRATION)
auth = read(AUTH)
users_src = read(USERS)
guard = read(GUARD)
enums = read(ENUMS)
router_src = read(ROUTER)
models_init = read(MODELS_INIT)
tests = read(TESTS)
report_center = read(REPORT_CENTER)

bind = region(svc, "def bind_device(", "\ndef ")
dev_gate = region(svc, "def _check_device_side(", "\ndef ")
reg_gate = region(svc, "def check_device_registration(", "\ndef ")
login_region = region(auth, "def _login(", "\n@router.")
reg_region = region(auth, '@router.post("/register"', "\n@router.")
sec = slice_to_end(users_src, "账号 ↔ 设备（FEAT-0018）")
guard_reg = region(guard, "def registration_block_reason(", "\ndef ")
guard_dev = region(guard, "def device_registration_block_reason(", "\ndef ")
dev_register_region = region(dev_api, '@router.post("/register"', "\n@router.")
rc_label = slice_to_end(report_center, "private fun actionLabel(")

# ---------- 0. 切片非空（这几条不成立时下面每条都会假红/假绿，先单独报） ----------
ok(bool(bind.strip()), "取不到 device_service.bind_device 的函数体")
ok(bool(dev_gate.strip()), "取不到 device_service._check_device_side 的函数体")
ok(bool(reg_gate.strip()), "取不到 device_service.check_device_registration 的函数体")
ok(bool(login_region.strip()), "取不到 auth._login 的函数体")
ok(bool(reg_region.strip()), "取不到 auth.register 的端点体")
ok(bool(sec.strip()), "取不到 users.py 里的「账号 ↔ 设备（FEAT-0018）」那一段")
ok(bool(guard_reg.strip()), "取不到 login_guard.registration_block_reason 的函数体")
ok(bool(guard_dev.strip()), "取不到 login_guard.device_registration_block_reason 的函数体")
ok(bool(dev_register_region.strip()), "取不到 devices.py 的 /devices/register 端点体")
ok(bool(rc_label.strip()), "取不到 ReportCenter.kt 的 actionLabel（审计码的中文名表）")

# ---------- 1. 账号那一侧：3 台 + 最早那台 + 6 个月冷却 ----------
ok("MAX_DEVICES_PER_ACCOUNT = 3" in svc,
   "一个账号的上限不是 3 台（MAX_DEVICES_PER_ACCOUNT = 3 不在；用户：「也不说完全只能绑定 3 个吧」= 上限就是 3）")
ok("if len(active) >= MAX_DEVICES_PER_ACCOUNT:" in bind,
   "bind_device 没有按**有效**绑定数判上限（if len(active) >= MAX_DEVICES_PER_ACCOUNT: 不在）")
ok("replaced = min(active, key=lambda r: (r.bound_at, r.id))" in bind,
   "被顶掉的不是「最早绑的那台」（min(active, key=lambda r: (r.bound_at, r.id)) 不在 —— 顶错一台会把刚绑的新机踢掉）")
ok("BIND_TTL_MONTHS = 6" in svc,
   "冷却期不是 6 个月（BIND_TTL_MONTHS = 6 不在；用户：「就要过 6 个月了」）")
ok("return add_months(bound_at, BIND_TTL_MONTHS)" in svc,
   "最早可替换时刻不是 bound_at + 6 个月（⛔ 冷却期必须以**绑定时间**为准，不是最后活跃时间）")
ok("expires_at = binding_expires_at(replaced.bound_at)" in bind,
   "冷却判定没有取「最早那台」的到期时刻（expires_at = binding_expires_at(replaced.bound_at) 不在）")
ok("if expires_at > now:" in bind and "raise DeviceBindingError(_account_full_detail(expires_at))" in bind,
   "冷却期内的第 4 台没有被拒（if expires_at > now: → DeviceBindingError 这条路不在；用户：「不能瞬间」）")
ok("replaced.unbound_at = now" in bind and "replaced.unbind_reason = UNBIND_REASON_EXPIRED" in bind,
   "被冷却顶掉那台没有留痕（unbound_at = now + unbind_reason = 'expired' 不在 —— 解绑不删行，什么时候绑过要查得到）")
ok('"expired"' in svc and "UNBIND_REASON_EXPIRED = " in svc,
   "被顶掉那台的原因不是 'expired' 这个字面量（派单员手动解冻是 'admin'，两者必须分得开）")
ok("if mine is not None and mine.unbound_at is None:" in bind and "mine.last_seen_at = now" in bind,
   "同一台设备再次登录没有走「只刷新 last_seen_at」那条（会白占一个额度、还会把冷却起点往后推）")
ok("mine.unbound_at = None" in bind and "mine.bound_at = now" in bind,
   "解冻之后再绑同一台设备没有**复用那一行**（unbound_at 清空 + bound_at 更新 不在；(user_id, device_id) 是唯一索引）")

# ---------- 2. 设备那一侧：5 个账号硬上限 + 24 小时新增 ≤2 ----------
ok("MAX_ACCOUNTS_PER_DEVICE = 5" in svc,
   "一台设备的上限不是 5 个账号（MAX_ACCOUNTS_PER_DEVICE = 5 不在；用户 2026-10-11：「一台手机至少是可以绑 5 个」）")
ok("if _accounts_on_device(db, device_id, exclude_user_id=user_id) >= MAX_ACCOUNTS_PER_DEVICE:" in svc,
   "硬上限没有按「这台设备上**有效**绑定的**不同账号**数」判（那条 if 不在 bind_device 之前）")
ok("MAX_NEW_ACCOUNTS_PER_DEVICE_24H = 2" in svc,
   "24 小时速率闸的阈值不是 2（MAX_NEW_ACCOUNTS_PER_DEVICE_24H = 2 不在）")
ok("if recent >= MAX_NEW_ACCOUNTS_PER_DEVICE_24H:" in dev_gate,
   "24 小时内新增账号没有速率闸（if recent >= MAX_NEW_ACCOUNTS_PER_DEVICE_24H: 不在 _check_device_side 里）")
ok("DEVICE_WINDOW = timedelta(hours=24)" in svc and "now - DEVICE_WINDOW" in dev_gate,
   "速率闸的窗口不是 24 小时（DEVICE_WINDOW = timedelta(hours=24) / now - DEVICE_WINDOW 不在）")
ok("exclude_user_id=user_id" in dev_gate,
   "设备侧计数没有把「本账号」排除（会把自己算成占额度的别人：本机第二次登录就被自己挡住）")
ok("_device_too_fast_detail()" in dev_gate,
   "速率闸没有给中文话术（_device_too_fast_detail() 不在 —— 403 的 detail 必须是说人话的中文）")

# ---------- 3. 注册那条（更紧）：同设备 24h ≤1 个新号 + 429 ----------
ok("MAX_NEW_ACCOUNTS_PER_DEVICE_REGISTER_24H = 1" in svc,
   "注册处的阈值不是 1（MAX_NEW_ACCOUNTS_PER_DEVICE_REGISTER_24H = 1 不在）")
ok("if recent >= MAX_NEW_ACCOUNTS_PER_DEVICE_REGISTER_24H:" in reg_gate,
   "注册那道闸不在 check_device_registration 里（if recent >= ...REGISTER_24H: 不在）—— 它是挡批量刷号的关键那条")
ok("raise DeviceBindingError(_device_register_detail())" in reg_gate,
   "注册那道闸没有给中文话术（_device_register_detail() 不在）")
ok("if not device_id:\n        return" in reg_gate,
   "没带设备信息时注册那道闸没有整条放行（老版本 App 会被挡在注册门外）")
ok("check_device_registration(db, device_id=device_id, phone=body.phone)" in reg_region,
   "auth.register 没有调那道注册设备闸（check_device_registration(...) 不在端点体里）")
ok(reg_region.find("check_device_registration(") < reg_region.find("phone = body.phone"),
   "注册设备闸不在建号**之前**（被拒时不该有号被建出来 —— 顺序反了会留下半个号）")
ok("HTTP_429_TOO_MANY_REQUESTS, detail=e.detail" in reg_region,
   "注册被设备闸拒了不是 429（契约：登录 403 / 注册 429）")
ok("bind_device(db, user=user, device_id=device_id, source=SOURCE_REGISTER)" in reg_region,
   "注册那条没有把「这台设备开了这个号」记下来（刚注册的号 + 刚登记的设备恰恰是刷号最典型的形状）")
ok("reason = login_guard.registration_block_reason(ip)" in reg_region
   and reg_region.find("login_guard.registration_block_reason(ip)") < reg_region.find("check_device_registration("),
   "注册的设备闸跑到来源 IP 限流**之前**了（顺序：先 IP 限流、再设备闸 —— FEAT-0017 那道防线必须仍在最前）")

# ---------- 4. 豁免：判据只有一处，三处闸全跳过 ----------
ok("is_test_account" in svc and "TEST_ACCOUNT_PHONE_PREFIX" not in svc and '"1380000000"' not in svc,
   "device_service 自己又写了一遍测试号前缀判断（豁免判据**只许有一处**：auth_service.is_test_account，那条注释写明了为什么）")
ok("if is_test_account(user.phone):\n        return None" in bind,
   "bind_device 没跳过测试号（用户：「测试账号除外」= 三条限制全跳过，而且连行都不记）")
ok("if is_test_account(phone):\n        return" in reg_gate,
   "check_device_registration 没跳过测试号（内部号注册也不该被设备闸挡住）")

# ---------- 5. 登录挂钩点与三条红线（顺序不能反） ----------
ok("bind_device(" in login_region and "source=SOURCE_LOGIN" in login_region,
   "auth._login 里没有设备那条路（bind_device(..., source=SOURCE_LOGIN) 不在）")
ok(0 <= login_region.find("login_guard.note_success(login_id)")
   < login_region.find("bind_device("),
   "设备闸不在密码验证通过**之后**（跑到前面去 ⇒ 没通过验证的人也能问出「这个号绑了几台设备」）")
ok(0 <= login_region.find("bind_device(")
   < login_region.find("revoke_tokens_and_sockets("),
   "设备闸跑到 revoke 之后了（换台手机试一下会把用户手上那台正常工作的踢下线 —— 用户要的顶号只发生在登录成功后）")
ok(0 <= login_region.find("bind_device(") < login_region.find("db.commit()"),
   "设备闸跑到 commit 之后了（被拒时已经落库，回滚也回不掉）")
ok("except DeviceBindingError as e:" in login_region and "db.rollback()" in login_region,
   "登录被设备闸拒时没有回滚（这次登录不该留下任何痕迹：last_login_at 都还没写）")
ok("HTTP_403_FORBIDDEN, detail=e.detail" in login_region,
   "登录被设备闸拒了不是 403（契约：超限拒绝 登录 = 403）")
ok("reject_plaintext_credentials(request)" in login_region
   and login_region.find("reject_plaintext_credentials(request)") < login_region.find("bind_device("),
   "登录的明文拦截不在最前（凭据端点必须先拒明文通道）")

# ---------- 6. 三个端点（签名级角色门槛）+ 公开的设备登记 ----------
ok(sec.count("Depends(require_permission(Permission.USER_MANAGE))") == 3,
   "三个设备端点的角色门槛不是签名级的 require_permission(Permission.USER_MANAGE)（⛔ 不许写成体内的 if——那会进 _check_inline_role_gates 的棘轮）")
ok("raise HTTPException" not in sec,
   "设备那一段里出现了体内的 HTTPException（角色门槛与参数错误都该在签名/schema 上写）")
ok('@router.get("/{user_id}/devices", response_model=list[DeviceBindingOut])' in sec,
   "缺 GET /users/{id}/devices（派单员看「这个账号绑过哪些设备」）")
ok('@router.post("/{user_id}/devices/{binding_id}/unbind", status_code=status.HTTP_204_NO_CONTENT)' in sec,
   "缺 POST /users/{id}/devices/{binding_id}/unbind（解冻一台；契约是 204）")
ok('@router.post("/{user_id}/devices/unbind-all", status_code=status.HTTP_204_NO_CONTENT)' in sec,
   "缺 POST /users/{id}/devices/unbind-all（一键全解冻；契约是 204）")
ok("active=row.unbound_at is None" in sec,
   "出参没有算 active（已解冻的历史行必须 active=false —— 「上一台什么时候换掉的」要看得见）")
ok("expires_at=device_service.binding_expires_at(row.bound_at)" in sec,
   "出参没有给 expires_at（派单员要能看出「最早那台到哪天才能替换」）")
ok("device_id=row.device_id" in sec and "source=row.source" in sec,
   "出参没有把设备标识/来源带出来（列表里少了这两列，界面上无法回答「哪台、怎么绑的」）")
ok("def _binding_out(row: AccountDevice) -> DeviceBindingOut:" in sec,
   "缺 _binding_out（出参组装只有一处，⛔ 别在三个端点里各拼一遍）")
ok('@router.post("/register", response_model=DeviceRegisterOut)' in dev_register_region,
   "缺 POST /devices/register（App 拿 install_id 换签名的那一端）")
ok("Depends(" not in dev_register_region,
   "设备登记端点不是公开的（契约：它**故意**没有 token —— 装 App 的人本来就还没登录）")
ok("normalize_install_id(" in dev_register_region,
   "设备登记没有校验 install_id 的形状（返回值直接进库，长度与字符集要在这里卡死）")
ok("device_token(install_id)" in dev_register_region,
   "设备登记没有回一份服务端签名（token 不在 —— 那样 X-Device-Id 就是随便填的）")
ok("reject_plaintext_credentials(request)" in dev_register_region,
   "设备登记没有拒明文通道（公开写端点不带凭据也要按仓库纪律挡一道）")
ok("login_guard.device_registration_block_reason(" in dev_register_region
   and "login_guard.note_device_registration(" in dev_register_region,
   "设备登记没有来源 IP 限流（公开端点必须有一道按 IP 的闸，否则谁都能无限领签名）")
ok("api_router.include_router(devices.router)" in router_src,
   "设备登记的路由没有挂进 api_router（端点存在但访问不到）")

# ---------- 7. 审计：解冻必须留痕，且中文名表跟着补 ----------
ok("USER_DEVICE_UNBIND" in enums,
   "backend/app/models/enums.py 里没有 USER_DEVICE_UNBIND 这个审计码")
ok(sec.count("action=OperationAction.USER_DEVICE_UNBIND,") == 2,
   "两个解冻端点没有都写 USER_DEVICE_UNBIND 审计（手工放宽风控这件事必须留痕）")
ok('"device_id": row.device_id,' in sec,
   "单台解冻的审计里没有 device_id（事后查不出解冻的是哪台）")
ok('"count": len(rows),' in sec,
   "一键全解冻的审计里没有 count（「这一下动了几台」要一眼看得出）")
ok("UNBIND_REASON_ADMIN" in sec and 'reason": device_service.UNBIND_REASON_ADMIN' in sec,
   "解冻的审计里没有写 reason=admin（与系统自己顶掉的 'expired' 必须分得开）")
ok('"USER_DEVICE_UNBIND" -> "解冻设备"' in rc_label,
   "ReportCenter.kt::actionLabel 里没有 USER_DEVICE_UNBIND —— 审计页会显示成英文码（_check_action_labels.py 会先红）")

# ---------- 8. 403 话术：说人话 + 带最早可替换日期 + 给出解冻出路 ----------
ok('{expires_at:%Y-%m-%d}' in svc,
   "403 话术里没有**日期**（用户要的是「最早那台要到哪天才能替换」，不是一句「已满」）")
ok("这个账号已绑" in svc and "才能替换" in svc,
   "403 话术没有说清「已绑几台、最早那台什么时候可换」")
ok("派单员" in svc and "解冻" in svc,
   "403 话术没有告诉用户出路（用户拍板：「联系派单员解冻即可」—— 话术里必须写出这条路）")
ok("「账户管理 → 编辑」" in svc,
   "403 话术没有说清派单员在哪个界面解冻（「就在编辑当中」是用户原话里的位置）")

# ---------- 9. 单测：六道闸 + 豁免 + 手工出口，每条都要有对应用例 ----------
ok(TESTS.is_file(), "缺 backend/tests/test_device_binding.py")
for name, why in (
    ("def test_test_account_ignores_every_device_limit", "豁免（测试号三条全跳过）"),
    ("def test_fourth_device_in_cooldown_is_rejected_with_the_expiry_date", "冷却期内第 4 台被拒 + 报对日期"),
    ("def test_cooled_down_oldest_device_can_be_replaced", "冷却到期后可替换（顶掉的是最早那台）"),
    ("def test_known_device_only_refreshes_last_seen", "本机重复登录只刷 last_seen_at"),
    ("def test_third_account_on_one_device_within_24h_is_rejected", "同设备 24h 第 3 个账号被拒（速率闸）"),
    ("def test_sixth_account_on_one_device_hits_the_hard_cap", "同设备第 6 个账号撞硬上限（5）"),
    ("def test_second_registration_from_one_device_within_24h_is_429", "注册同设备 24h 第 2 个号 = 429"),
    ("def test_dispatcher_unbind_all_lets_the_new_phone_in_immediately", "派单员解冻后能立刻绑新设备"),
    ("def test_single_unbind_is_idempotent_and_leaves_one_audit_line", "解冻留审计且幂等不重复记"),
    ("def test_unbind_all_audit_carries_the_count", "一键全解冻的审计带 count"),
    ("def test_device_endpoints_are_dispatcher_only", "三个端点非派单员进不来"),
    ("def test_device_register_signs_the_install_id", "设备登记发签名"),
    ("def test_forged_device_signature_is_treated_as_no_device", "伪签名 = 当作没有设备信息"),
    ("def test_device_register_is_rate_limited_per_ip", "设备登记按 IP 限流"),
):
    ok(name in tests, f"单测缺 {name}（{why}）")
ok("login_guard.MAX_DEVICE_REGISTRATIONS_PER_IP" in tests,
   "设备登记的限流用例没有按阈值算次数（改阈值就会假红）")
ok("_reset()" in tests or "login_guard.reset_for_tests()" in tests,
   "设备绑定用例没有清限流计数（本机 Redis 残留会让它偶发假红）")
ok("is_test_account(" in tests,
   "豁免那条用例没有**先断言**自己造的那个号确实是测试号（豁免判据只有一处，用例要盯着它）")
ok("X-Forwarded-Proto" in tests,
   "用例没有造明文/加密通道的头（凭据端点那两道防线就没人测了）")

# ---------- 10. 表 / 迁移 / 模型登记 ----------
ok(MIGRATION.is_file(), "缺 backend/app/migrations/031_account_devices.py（编号接着 030 往下）")
ok("VERSION = 31" in migration,
   "迁移的 VERSION 不是 31（编号接着 030 往下；文件名前缀与 VERSION 的一致性由 _check_migrations.py 管）")
ok("AccountDevice.__table__.create(bind=engine, checkfirst=True)" in migration,
   "迁移没有用模型建表（手写 CREATE TABLE 会让模型与库分叉；checkfirst=True 保证可重跑）")
ok('__tablename__ = "account_devices"' in dev_model,
   "模型没有落在 account_devices 表上")
ok('UniqueConstraint("user_id", "device_id"' in dev_model,
   "模型缺 (user_id, device_id) 唯一索引（同一对只许有一行，「复用那一行」全靠它）")
ok("unbound_at" in dev_model and "unbind_reason" in dev_model and "source" in dev_model,
   "模型缺 unbound_at / unbind_reason / source（解绑不删行、来源要写下来）")
ok('"AccountDevice"' in models_init and "from app.models.account_device import AccountDevice" in models_init,
   "app/models/__init__.py 没有导入 AccountDevice（create_all 与迁移都会漏掉这张表）")
ok('class DeviceRegisterIn(' in dev_schema and 'class DeviceBindingOut(' in dev_schema,
   "schemas/device.py 缺 DeviceRegisterIn / DeviceBindingOut")

print("PASS =", PASS)
if FAIL:
    print("❌ 以下 %d 条不成立：" % len(FAIL))
    for f in FAIL:
        print("   -", f)
    sys.exit(1)
print("✅ 全部 %d 项通过：账号↔设备绑定（3 台 / 6 个月冷却 / 最早那台）、设备↔账号"
      "（5 个硬上限 / 24h 新增 ≤2 / 注册 24h ≤1）、测试号豁免（判据只有一处）、"
      "派单员手工解冻（三个签名级门槛端点 + USER_DEVICE_UNBIND 审计）都在"
      "（FEAT-0018，2026-10-11）。" % PASS)
