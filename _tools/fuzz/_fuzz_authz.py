"""鉴权模糊测试（fuzz #2）：**谁能调什么、能不能看别人的数据**。

## 它在问四件事
1. **不登录能不能进**：除公开端点外，任何端点无 token 必须 401（不是 500、更不是 200）。
2. **拿假 token 能不能进**：乱码 token / `alg=none` / 用别的密钥签的 token，一律 401。
3. **角色对不上能不能进**：把源码里的授权声明（`gen_endpoint_index.collect()` 算出来的）
   和**实测行为**逐条对账——声明"角色:dispatcher"的端点，货主/司机调它必须是 403。
   ⚠️ 只对**入口级**门槛断言（`角色:` / `权限:`）；体内 `raise 403` 的门槛要用真实对象
   才走得到，那些单独列出来（不假装测过）。
4. **跨租户能不能看**：货主 B 读/改/删货主 A 的单；司机带别人的 driver_id 查账单。

## 为什么判据要来自源码而不是手写
`08A_ENDPOINT_INDEX.md` 是 `backend/scripts/gen_endpoint_index.py` 的产物，而本脚本直接调它的
`collect()`——**永远是源码现状**，不会拿着一份过期的表去对账（这个项目栽过"文档与行为相反"）。

## 安全边界
- 只用**本工具自己建的对象**做跨租户试验；路径参数一律用不存在的 id 或不许碰的端点会被拦。
- 批量/全量端点走 `_fuzzlib.DENY`，不测。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fuzzlib import (  # noqa: E402
    Api, MARK, ROOT, Report, db_q, denied, openapi, uniq,
)

ALL_ROLES = ("dispatcher", "shipper", "driver")
ROLE_CN = {"dispatcher": "派单员", "shipper": "货主", "driver": "司机"}


def key_of(method: str, path: str) -> str:
    """归一化端点键：`/static/uploads/{file_path:path}` 与 `/static/uploads/{file_path}`
    是**同一个**端点——两边写法不同（源码里的参数名带类型标注），不归一就会
    "公开端点认不出来 → 报一个假缺陷"（第一版就是这么误报的）。"""
    return f"{method.upper()} " + re.sub(r"\{[^}]*\}", "{}", re.sub(r"^/api/v1", "", path) or "/")


def declared_roles() -> dict[str, dict]:
    """源码里的授权声明：{"METHOD /path": {"roles": set, "auth": str}}（不含 /api/v1 前缀）。"""
    gen = ROOT / "_tools/ai/_gen_ai_read_catalog.py"
    spec = importlib.util.spec_from_file_location("_gen_ai_read_catalog", gen)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    out: dict[str, dict] = {}
    for (method, url), info in mod.endpoint_roles().items():
        out[key_of(method, url)] = {"roles": set(info["roles"]), "auth": info["auth"]}
    return out


def openapi_ops() -> list[tuple[str, str, bool]]:
    """(method, path, 有请求体)——清单由 openapi 算出来，不手写。"""
    doc = openapi()
    out = []
    for raw, methods in (doc.get("paths") or {}).items():
        path = re.sub(r"^/api/v1", "", raw) or "/"
        for m, spec in methods.items():
            method = m.upper()
            if method not in ("GET", "POST", "PATCH", "PUT", "DELETE"):
                continue
            has_body = bool((spec.get("requestBody") or {}).get("content"))
            out.append((method, path, has_body))
    return sorted(set(out))


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def forge(payload: dict, secret: bytes, header: dict | None = None) -> str:
    h = b64(json.dumps(header or {"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    p = b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = b64(hmac.new(secret, f"{h}.{p}".encode(), hashlib.sha256).digest())
    return f"{h}.{p}.{sig}"


def tamper_behaviour(api: Api, rep: Report, ops: list[tuple[str, str, bool]]) -> None:
    """假 token 必须 401（挑几个代表性端点打，不必全量）。"""
    rep.section("假 token")
    good = api.login("dispatcher")
    payload = json.loads(base64.urlsafe_b64decode(good.split(".")[1] + "==").decode())
    samples = [("GET", "/orders", False), ("GET", "/products", False),
               ("GET", "/users/me", False), ("POST", "/orders", True),
               ("GET", "/reports/turnover", False)]
    bad_tokens = {
        "乱码": "abc.def.ghi",
        "空串": "",
        "alg=none": f"{b64(b'{\"alg\":\"none\",\"typ\":\"JWT\"}')}.{b64(json.dumps(payload).encode())}.",
        "别的密钥签的": forge({**payload, "sub": "1", "role": "dispatcher"}, b"not-the-real-secret"),
        "改过 payload 但签名没换": ".".join(good.split(".")[:2]) + "." + b64(b"0" * 32),
    }
    n_probe = 0
    for label, tok in bad_tokens.items():
        hit = 0
        for method, path, has_body in samples:
            if denied(method, path):
                continue
            r = api.req(method, path, {"__probe__": 1} if has_body else None,
                        tok, allow_denied=True)
            n_probe += 1
            if r.status not in (401, 403):
                hit += 1
                rep.bug(f"{label} token 被接受：{method} {path}", r.evidence(200))
        if not hit:
            rep.ok(f"{label} token 全部被拒（{len(samples)} 个端点）")
    rep.guard("假 token 探测真的发出去了", n_probe >= 15, f"实际 {n_probe}")


def anonymous_behaviour(api: Api, rep: Report, decl: dict[str, dict],
                        ops: list[tuple[str, str, bool]]) -> None:
    """无 token：公开端点之外必须 401。"""
    rep.section("不登录")
    public = {k for k, v in decl.items() if "公开" in v["auth"] or not v["auth"]}
    probed = 0
    for method, path, has_body in ops:
        key = key_of(method, path)
        if key in public or denied(method, path):
            continue
        filled = re.sub(r"\{[^}]+\}", "999999999", path)
        if denied(method, filled):
            continue
        r = api.req(method, filled, {"__probe__": 1} if has_body else None, None, allow_denied=True)
        probed += 1
        if r.status not in (401, 403):
            rep.bug(f"不登录也能调：{method} {path}", r.evidence(200))
    rep.guard("无 token 探测覆盖了 ≥80 个端点", probed >= 80, f"实际 {probed}")
    rep.info(f"公开端点（源码声明，允许免登录）：{len(public)} 个",
             "、".join(sorted(public)[:10]))


def role_matrix(api: Api, rep: Report, decl: dict[str, dict],
                ops: list[tuple[str, str, bool]]) -> None:
    """源码声明 vs 实测：声明只给某些角色的端点，别的角色必须被挡。"""
    rep.section("角色矩阵（声明 vs 实测）")
    tokens = api.all_roles()
    checked = 0
    skipped_body_gate: list[str] = []
    inconclusive: list[str] = []
    for method, path, has_body in ops:
        key = key_of(method, path)
        info = decl.get(key)
        if info is None or denied(method, path):
            continue
        auth = info["auth"]
        if "公开" in auth:
            continue
        if any(tag in auth for tag in ("体内", "需读源码")):
            # ⚠️ 这里原来**一律跳过** —— 于是 55 个"只有体内门槛"的端点一个都没测。
            #    但"体内门槛"只在**路径参数指向一个真实对象**时才需要先查到对象：
            #    像 `GET /cash-flows` 这种**没有路径参数**的端点，门槛必然当场执行，
            #    用假 id 的说法对它根本不成立（2026-09-23 复核：手工逐条打过，
            #    26 条断言全是 403，本来就该被这条判据自动盯着）。
            #    所以只跳过"体内门槛 + 有路径参数"那一类，把没有路径参数的交回下面的常规对账。
            if "{" in path:
                skipped_body_gate.append(key)
                continue
        allowed = set(info["roles"])
        if "权限:" in auth:
            # require_permission 对派单员一律放行（rbac.py 写死的最高业务权限）
            allowed.add("dispatcher")
        if allowed >= set(ALL_ROLES) or not allowed:
            continue
        filled = re.sub(r"\{[^}]+\}", "999999999", path)
        if denied(method, filled):
            continue
        for role in ALL_ROLES:
            if role in allowed:
                continue
            r = api.req(method, filled, {"__probe__": 1} if has_body else None,
                        tokens[role], allow_denied=True)
            checked += 1
            if r.status in (401, 403):
                continue
            if r.status < 400:
                rep.bug(
                    f"{ROLE_CN[role]}能调只给"
                    + "/".join(ROLE_CN[x] for x in sorted(allowed))
                    + f"的端点：{method} {path}",
                    f"源码声明「{auth}」；实测 {r.evidence(200)}",
                )
            else:
                # 400/404/422：**不能**据此判定鉴权 —— 体内门槛（先查对象再判角色）
                # 遇到不存在的 id 会先返回 404。这类只如实记为"没测出来"。
                inconclusive.append(
                    f"{method} {path}（{ROLE_CN[role]} → {r.status}）"
                )
    rep.guard("角色矩阵至少核对了 40 条（声明 vs 实测）", checked >= 40, f"实际 {checked}")
    if checked and not any(f.kind == "BUG" for f in rep.findings):
        rep.ok(f"角色矩阵 {checked} 条全部一致（声明不允许的角色都被 403 挡下）")
    if inconclusive:
        rep.risk(
            f"{len(inconclusive)} 条无法判定（返回 400/404，说明门槛在函数体内，要先查到对象）",
            "、".join(sorted(set(inconclusive))[:8]),
        )
    if skipped_body_gate:
        rep.info(
            f"{len(skipped_body_gate)} 个端点只有体内门槛（要真实对象才走得到），矩阵里**没测**",
            "、".join(sorted(skipped_body_gate)[:12]),
        )


#: 第二个货主身份（跨租户试验用）。取一次就缓存。
SECOND: dict[str, str] = {}


def second_shipper(api: Api, rep: Report) -> str | None:
    """拿一个"别的**货主**"的身份：先试现成账号（**核对角色**），没有就让**派单员**建一个。

    ⚠️ 2026-09-23 复核抓到这条判据的一个真问题：原来的候选是
    `("13800000004", "13800000005", "13800000006")`，而**谁先登录成功就用谁** ——
    本机这三个号里只有 `13800000006` 存在，它是**司机**（王大力）。于是"跨租户"那一节
    拿着司机 token 去做实验，还把它标成"第二个货主"：断言看着还在（司机当然也不该读别人的单），
    但真正要问的"**货主 B 能不能看货主 A 的单**"从来没测过 —— 典型的
    "判据看起来在查、其实查的是另一个角色"。
    现在：登录成功之后必须 `GET /users/me` **核对角色**，不是货主就换下一个；
    再加一条从库里找同角色账号的路（开发库里有 30+ 个演示货主），都没有才由派单员新建。
    """
    if "token" in SECOND:
        return SECOND["token"] or None

    def role_of(token: str) -> str:
        r = api.get("/users/me", token, allow_denied=True)
        if isinstance(r.body, dict):
            return str(r.body.get("role") or "").strip().lower()
        return ""

    candidates = ["13800000004", "13800000005", "13800000006"]
    # 从库里找现成的同角色账号（只读查询；账号是演示数据，口令统一 123321）
    try:
        rows = db_q(
            "select phone from users where upper(role) = 'SHIPPER' "
            "and phone not in ('13800000002') order by id limit 8"
        )
        candidates += [str(r["phone"]) for r in rows if r["phone"]]
    except Exception:  # noqa: BLE001 - 查不到就只试写死的几个
        pass
    for phone in candidates:
        r = api.post("/auth/login", {"phone": phone, "password": "123321"}, allow_denied=True)
        if not (r.is_2xx and isinstance(r.body, dict) and r.body.get("access_token")):
            continue
        token = r.body["access_token"]
        got = role_of(token)
        if got != "shipper":
            # ⚠️ 这里**不许**默默拿来用：角色不对就等于这一节没测
            rep.info(f"跳过 {phone}：它是「{got or '未知'}」不是货主（以前这里就是这么拿司机当货主的）")
            continue
        rep.info(f"用现成的第二个货主做跨租户试验：{phone}")
        SECOND["token"] = token
        return token

    phone = "139" + str(uuid.uuid4().int)[:8]
    created = api.post(
        "/users",
        {"phone": phone, "password": "123321", "full_name": uniq("跨租户试验货主"), "role": "shipper"},
        api.login("dispatcher"),
    )
    if created.is_2xx:
        tok = api.post("/auth/login", {"phone": phone, "password": "123321"}, allow_denied=True)
        if tok.is_2xx and isinstance(tok.body, dict) and tok.body.get("access_token"):
            t2 = tok.body["access_token"]
            if role_of(t2) == "shipper":
                SECOND["phone"] = phone
                SECOND["token"] = t2
                rep.info(f"派单员建了一个试验货主 {phone}（收尾会删掉）")
                return t2
            rep.info(f"新建的 {phone} 角色核对不上，放弃（不让这一节拿错角色去测）")
    SECOND["token"] = ""
    return None


def registration_boundary(api: Api, rep: Report) -> None:
    """自助注册的边界（2026-10-11 FEAT-0017 之后：**注册是开的，短信那条仍然关着**）。

    ## 这个探针换过一次方向，两段历史都要留住
    - **2026-09-18**：注册整体删掉（用户：「注册接口关掉，不需要用了」）。当时的判据是
      "两条路径都取不到（404）、账号数没变"，因为**没人用的公开写接口**就是纯攻击面，
      而且本地 `sms_reveal_code=true` 时验证码明文回显＝任何人都能自助开货主号。
    - **2026-10-11（FEAT-0017）**：用户要求在 App 登录页自助注册 ⇒ 端点回来，连入口一起加。
      所以现在**"注册能建出号"不是缺陷**；缺陷变成下面这三条：
      ① 短信验证码那条路又开了（当年删它的真正理由，本次范围不含）；
      ② 建出来的号**不是货主**（提权：自助注册出派单员＝任何人都能管整个系统）；
      ③ 明文通道上注册居然成功（密码裸奔）。
    这条探针**会真的建一个号**（走的就是"效果"这条路：只查源码看不出来默认角色到底写没写对）；
    号是随机手机号、且下面会核出它是货主，不会污染别的判断。
    """
    rep.section("自助注册的边界（FEAT-0017：注册开、短信关、默认货主）")
    phone = "139" + str(uuid.uuid4().int)[:8]
    before = db_q("select count(*) from users")[0][0]

    code = api.post("/auth/sms/send", {"phone": phone}, allow_denied=True)
    if code.status != 404:
        rep.bug(
            "注册验证码那条路又开了（2026-09-18 删它的真正理由：本地 sms_reveal_code=true 时明文回显）",
            f"POST /auth/sms/send → {code.status}",
        )
    else:
        rep.ok("注册验证码那条路仍然关着（404）")

    reg = api.post(
        "/auth/register",
        {"phone": phone, "password": "123321"},
        allow_denied=True,
    )
    after = db_q("select count(*) from users")[0][0]

    if reg.status == 200:
        rows = db_q("select role, is_member, is_active, category from users where phone=%s", (phone,))
        role, is_member, is_active, category = (rows[0] if rows else ("?", "?", "?", "?"))
        # ⚠️ SQLite 里 `user_role` 存的是枚举**名**（大写下划线），不是 API 的小写值 ——
        #    照 API 的形状写 `role == "shipper"` 会恒假，把"角色其实是对的"报成缺陷。
        role_norm = str(role or "").strip().lower()
        if role_norm == "shipper" and not is_member and is_active and (category or "") == "":
            rep.ok(f"自助注册建出来的是货主（shipper / 非批发商 / 启用 / 无分类），账号数 {before}→{after}")
        else:
            rep.bug(
                "自助注册建出来的账号属性不对（默认货主是用户明确要求，不是可选）",
                f"phone={phone} role={role} is_member={is_member} is_active={is_active} category={category!r}",
            )
    elif reg.status == 429:
        rep.ok("自助注册被限流挡住（429）—— 这台机器上注册次数已用满，属预期")
    else:
        rep.bug(
            "自助注册端点取不到（FEAT-0017 之后它必须是开着的；App 登录页的入口依赖它）",
            f"POST /auth/register → {reg.status}，body={str(reg.body)[:200]}",
        )

    plain = api.post("/auth/register", {"phone": phone, "password": "123321"},
                     headers={"X-Forwarded-Proto": "http"}, allow_denied=True)
    if plain.status == 426:
        rep.ok("明文通道上注册被拒（426）—— 与登录同一道防线")
    else:
        rep.bug(
            "明文通道上注册竟然成功了（密码在公网上裸奔）",
            f"带 X-Forwarded-Proto: http 的 POST /auth/register → {plain.status}",
        )


def body_gate_retest(api: Api, rep: Report) -> None:
    """体内门槛复测：挑后果最重的一个端点——**删订单**（删错就是数据没了）。

    `DELETE /orders/{order_id}` 的角色门槛写在函数体里（先查单、再判角色），
    所以矩阵里"用假 id 探"只能拿到 404，测不出鉴权。这里用真实对象把四条路走一遍。
    """
    rep.section("体内门槛复测：删订单（真实对象）")
    tok_a = api.login("shipper")
    tok_disp = api.login("dispatcher")
    tok_d = api.login("driver")
    tok_b = second_shipper(api, rep)

    def new_order() -> int | None:
        r = api.post("/orders", {
            "lines": [{"product_name_snapshot": uniq("删单试验品"), "quantity": 1, "unit_price": "9"}],
            "delivery_description": uniq("删单试验"),
        }, tok_a)
        return r.body.get("id") if r.is_2xx and isinstance(r.body, dict) else None

    oid = new_order()
    rep.guard("建出了一张待派单的单（否则这节等于没测）", bool(oid), "货主下单失败")

    # ① 货主删自己**进行中**的单 → 必须 400 + 中文（不是 204！）
    r = api.delete(f"/orders/{oid}", tok_a)
    if r.status == 400 and "已送达" in r.text:
        rep.ok(f"货主删自己进行中的单被拒且给了中文原因（{r.detail[:40]}）")
    elif r.is_2xx:
        rep.bug("货主能删掉自己**进行中**的订单（应该只有已送达/已撤销/异常单可删）", r.evidence(200))
    else:
        rep.risk("货主删自己进行中的单：状态码不是预期的 400", r.evidence(200))

    # ② 别的货主删 A 的单 → 必须 403/404，绝不能 204
    oid2 = new_order()
    if tok_b and oid2:
        r = api.delete(f"/orders/{oid2}", tok_b)
        if r.is_2xx:
            rep.bug("**别的货主能删掉这张单**（跨租户数据丢失）", f"DELETE /orders/{oid2} → {r.status}")
        else:
            rep.ok(f"别的货主删不掉 A 的单（{r.status}）")

    # ③ 司机删 → 必须 403
    if oid2:
        r = api.delete(f"/orders/{oid2}", tok_d)
        if r.is_2xx:
            rep.bug("司机能删订单（角色门槛失效）", f"DELETE /orders/{oid2} → {r.status}")
        else:
            rep.ok(f"司机删订单被拒（{r.status}）")

    # ④ 派单员删 → 应能删（204），顺便当清理
    if oid2:
        r = api.delete(f"/orders/{oid2}", tok_disp)
        if r.status == 204:
            rep.ok("派单员删任意状态订单：204（设计如此）")
        else:
            rep.risk("派单员删订单没成功（与「派单员可删任意状态」的设计不符）", r.evidence(200))
    if oid:
        api.delete(f"/orders/{oid}", tok_disp)


def idor(api: Api, rep: Report) -> None:
    """跨租户：B 能不能读/改/删 A 的单；司机能不能拿别人的 id 查账单。"""
    rep.section("跨租户（IDOR）")
    tok_a = api.login("shipper")          # 13800000002
    tok_d = api.login("driver")
    tok_disp = api.login("dispatcher")
    tok_b = second_shipper(api, rep)
    rep.guard("拿到了第二个货主身份（不然跨租户一条都测不了）", bool(tok_b), "两个货主都拿不到")

    # --- A 建一张单（只用自己建的对象做试验）
    order_id = None
    r = api.post("/orders", {
        "lines": [{"product_name_snapshot": uniq("IDOR试验品"), "quantity": 1, "unit_price": "10"}],
        "delivery_description": uniq("IDOR试验单"),
    }, tok_a)
    if r.is_2xx and isinstance(r.body, dict):
        order_id = r.body.get("id")
    rep.guard("货主 A 建出了一张自己的单", bool(order_id), r.evidence(300))

    # --- B 去碰 A 的单
    for method, label in (("GET", "读详情"), ("PATCH", "改"), ("DELETE", "删")):
        body = {"remark": "B 改的"} if method == "PATCH" else None
        rr = api.req(method, f"/orders/{order_id}", body, tok_b, allow_denied=True)
        if rr.status in (403, 404):
            rep.ok(f"货主 B {label} 货主 A 的单被拒（{rr.status}）")
        elif rr.status < 400:
            rep.bug(f"货主 B 能{label}货主 A 的单（IDOR）",
                    f"{method} /orders/{order_id} → {rr.status} {rr.text[:150]}")
        else:
            rep.ok(f"货主 B {label} 货主 A 的单被拒（{rr.status}）")

    # --- B 的列表里不许有 A 的单
    lst = api.get("/orders", tok_b)
    if isinstance(lst.body, list):
        leaked = [o for o in lst.body if o.get("id") == order_id]
        if leaked:
            rep.bug("货主 B 的订单列表里出现了货主 A 的单", f"GET /orders → {len(lst.body)} 条，含 {order_id}")
        else:
            rep.ok(f"货主 B 的订单列表不含 A 的单（共 {len(lst.body)} 条）")

    # --- 司机带别人的 driver_id 查账单
    others = [r0[0] for r0 in db_q("select id from users where role='DRIVER' order by id limit 5")]
    mine = json.loads(base64.urlsafe_b64decode(tok_d.split(".")[1] + "==").decode()).get("sub")
    for path in ("/driver-bills", "/freight-settlement"):
        if any(str(o) == str(mine) for o in others):
            others = [o for o in others if str(o) != str(mine)]
        if not others:
            continue
        other = others[0]
        rr = api.get(f"{path}?driver_id={other}", tok_d)
        if not rr.is_2xx or not isinstance(rr.body, (list, dict)):
            rep.ok(f"司机查别人的账单被拒或空：{path} -> {rr.status}")
            continue
        rows = rr.body if isinstance(rr.body, list) else rr.body.get("items") or rr.body.get("rows") or []
        foreign = [x for x in rows if isinstance(x, dict) and str(x.get("driver_id")) == str(other)]
        if foreign:
            rep.bug(f"司机能用 driver_id 查别人的账单：{path}",
                    f"driver_id={other}（自己={mine}）→ 返回 {len(foreign)} 条别人的记录")
        else:
            rep.ok(f"司机带别人的 driver_id 拿不到别人数据：{path}（返回 {len(rows)} 条）")

    # --- 收尾：这张试验单由派单员删掉（货主删不掉非终态单）
    if order_id:
        d = api.delete(f"/orders/{order_id}", tok_disp)
        rep.info(f"试验单 {order_id} 清理：{d.status}")


#: 「体内门槛 **+ 带请求体**」的端点：`{"__probe__":1}` 这类垃圾体一律只会拿到 422 ——
#: **FastAPI 的请求体校验排在处理器之前**，角色门槛有没有，422 里看不出来（矩阵会把它们
#: 记成"无法判定"，那是诚实的，但等于没测）。所以这里给每个端点配一个**合法但无害**的体，
#: 让门槛真的被走到；值里第二个元素写清"万一真建出来了，这个东西删得掉吗"。
#: 未列进来的端点会被如实列进"没测"清单（下面那条 guard 盯着覆盖数）。
VALID_BODIES: dict[str, tuple[dict, str]] = {
    "POST /customers": ({"name": f"越权试验{MARK}"}, "散客档案，删得掉（DELETE /customers/{id}）"),
    "POST /expense-categories": ({"name": f"越权试验{MARK}"}, "开销分类名册，删得掉"),
    "POST /expense-categories/reorder": ({"ids": [1]}, "只改显示顺序，编号不存在时后端会拒"),
    "POST /expenses": (
        {"exp_date": "2026-01-01", "category": f"越权试验{MARK}", "amount": "1.00",
         "note": f"越权试验{MARK}"},
        "一笔开销；只有角色门槛真的漏了才会建出来",
    ),
    "POST /driver-settlements": (
        {"driver_id": 0, "month": "2026-01", "note": f"越权试验{MARK}"},
        "司机结算单（草稿，不做付款）；driver_id=0 只是个不存在的编号，门槛漏了也建不出真单",
    ),
}


def body_gate_with_valid_body(api: Api, rep: Report, decl: dict[str, dict],
                              ops: list[tuple[str, str, bool]]) -> None:
    """带请求体的体内门槛：用**合法体**试越权（垃圾体只会 422，等于没测）。"""
    rep.section("体内门槛 + 带请求体：合法体试越权")
    tokens = api.all_roles()
    checked = 0
    untested: list[str] = []
    for method, path, has_body in ops:
        if not has_body or "{" in path:
            continue
        key = key_of(method, path)
        info = decl.get(key)
        if info is None or "公开" in info["auth"] or denied(method, path):
            continue
        if not any(tag in info["auth"] for tag in ("体内", "需读源码")):
            continue
        allowed = set(info["roles"])
        if "权限:" in info["auth"]:
            allowed.add("dispatcher")
        if allowed >= set(ALL_ROLES) or not allowed:
            continue
        spec = VALID_BODIES.get(f"{method} {path}")
        if spec is None:
            untested.append(key)
            continue
        body, _why = spec
        for role in ALL_ROLES:
            if role in allowed:
                continue
            r = api.req(method, path, body, tokens[role], allow_denied=True)
            checked += 1
            if r.status < 400:
                rep.bug(
                    f"{ROLE_CN[role]}能用**合法请求体**调只给"
                    + "/".join(ROLE_CN[x] for x in sorted(allowed))
                    + f"的写端点：{method} {path}",
                    f"源码声明「{info['auth']}」；实测 {r.evidence(200)}",
                )
    rep.guard("合法体探针真的发出去了（≥8 条）", checked >= 8, f"实际 {checked}")
    if checked and not any(f.kind == "BUG" for f in rep.findings):
        rep.ok(f"合法体试越权 {checked} 条全部被 403 挡下")
    if untested:
        rep.info(
            f"{len(untested)} 个带请求体的体内门槛端点没有配合法体（**没测**）："
            + "、".join(sorted(untested)[:10]),
            "补一条进 VALID_BODIES 就能测；不补就只能算「无法判定」",
        )


def cleanup_own_accounts(api: Api, rep: Report) -> None:
    """工具自己注册出来的账号自己收掉（只删它登记在 SECOND["phone"] 里的那个）。"""
    phone = SECOND.get("phone")
    if not phone:
        return
    rows = db_q("select id from users where phone = ?", (phone,))
    if not rows:
        rep.info(f"注册出来的试验账号 {phone} 没找到（可能已删）")
        return
    uid = rows[0][0]
    r = api.delete(f"/users/{uid}?hard=false", api.login("dispatcher"), allow_denied=True)
    rep.info(f"收掉本工具注册的试验账号 {phone}（id={uid}）：{r.status} {r.detail[:80]}")


def main() -> int:
    rep = Report("鉴权模糊测试：谁能调什么、能不能看别人的数据", module="_fuzz_authz")
    api = Api()
    ops = openapi_ops()
    decl = declared_roles()
    rep.guard("openapi 端点 ≥ 120 个", len(ops) >= 120, f"实际 {len(ops)}")
    rep.guard("源码授权声明 ≥ 120 条（来自 collect()，不是手写表）", len(decl) >= 120,
              f"实际 {len(decl)}")
    matched = sum(1 for m, p, _ in ops if key_of(m, p) in decl)
    rep.guard("openapi 与源码声明能对上 ≥ 100 条（对不上就说明两边命名漂了）",
              matched >= 100, f"实际 {matched}/{len(ops)}")

    anonymous_behaviour(api, rep, decl, ops)
    registration_boundary(api, rep)
    tamper_behaviour(api, rep, ops)
    role_matrix(api, rep, decl, ops)
    body_gate_with_valid_body(api, rep, decl, ops)
    body_gate_retest(api, rep)
    idor(api, rep)
    cleanup_own_accounts(api, rep)
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
