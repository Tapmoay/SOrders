"""契约模糊测试（fuzz #1）：把每个写端点的**每个字段**按类型喂坏值，找 500 与"非法却落库"。

## 它在问什么
不是"这段代码写错了吗"（单测问的是这个），而是：
**"这个接口收到现实里可能出现的脏输入时，会怎么反应？"**
- 500 = 没接住异常（用户看到的是"服务器错误"，而原因可能只是一串 8000 字符的名字）
- 200/201 = 它**收下了**（例如数量给 -5、金额给 1e20）→ 要顺着查库看后果
- 422 英文结构体 = 用户/AI 看到的是一段看不懂的 JSON（本项目要求中文）

## 用法
```
python _tools/fuzz/_fuzz_contract.py                  # 全部写端点
python _tools/fuzz/_fuzz_contract.py --only /orders   # 只看某前缀
python _tools/fuzz/_fuzz_contract.py --max 2000       # 请求预算
```
退出码：发现确认缺陷 = 2；自检失败（没测到东西）= 3。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fuzzlib import (  # noqa: E402
    Api, MARK, Op, Report, bad_values, body_fields, denied, db_one, db_q, fill_path,
    openapi, synth_value, uniq, write_ops,
)

#: 每个端点最多测几个字段（字段多的端点取前 N 个 + 全部必填）
MAX_FIELDS_PER_OP = 8
#: 每个字段最多喂几种坏值
MAX_BAD_PER_FIELD = 7


def pick_token(api: Api, op: Op) -> tuple[str | None, str]:
    """挑一个能调通这个端点的角色。都调不通就返回 None（不计入结论）。

    ⚠️ 探测体刻意用**非法**内容（`{"__probe__": 1}`）：FastAPI 先解安全依赖、再校验请求体，
    所以 403 仍然会先出来；而未授权的角色拿到 403、有权限的拿到 422/400/404。
    用"合法体"探测会**顺手建出数据**（`pick_token` 跑在每个端点之前，清理逻辑还没轮到）。
    """
    path = fill_path(op.path)
    if denied(op.method, path):
        return None, ""
    probe = None if op.method == "DELETE" else {"__probe__": 1}
    for role in ("dispatcher", "shipper", "driver"):
        tok = api.login(role)
        try:
            r = api.req(op.method, path, probe, tok)
        except PermissionError:
            return None, ""
        if r.status not in (401, 403):
            return tok, role
    return None, ""


def baseline_body(op: Op, ids: dict[str, list[int]]) -> dict:
    """只填必填字段的"最小合法体"——用最小体才看得出"删掉某个字段会怎样"。"""
    body = {}
    for f in op.fields:
        if f["required"]:
            body[f["name"]] = synth_value(f["name"], f["type"], f["schema"], ids)
    return body


def cleanup(api: Api, op: Op, resp, doc_ops: list[Op], tok: str, made: list[str]) -> None:
    """2xx 的突变会真的建出数据 —— 机器算出对应的 DELETE 端点把它收掉。"""
    if not resp.is_2xx or not isinstance(resp.body, dict):
        return
    new_id = resp.body.get("id")
    if not isinstance(new_id, int):
        return
    base = op.path.rstrip("/")
    for cand in doc_ops:
        if cand.method != "DELETE":
            continue
        # /products + /products/{product_id} → 匹配
        if re.fullmatch(re.escape(base) + r"/\{[^}]+\}", cand.path):
            if denied("DELETE", base + "/" + str(new_id)):
                continue
            r = api.delete(base + "/" + str(new_id), tok)
            made.append(f"{base}/{new_id} -> {r.status}")
            return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只看路径前缀（逗号分隔）")
    ap.add_argument("--max", type=int, default=1500, help="请求预算")
    ap.add_argument("--refs", action="store_true",
                    help="允许在**请求体**里填真实 id（默认全用不存在的 id）。"
                         "真实路径 id 永远不用：那会把业务数据真的改掉")
    args = ap.parse_args()

    rep = Report("契约模糊测试：脏输入下接口怎么反应", module="_fuzz_contract")
    api = Api()
    doc = openapi()
    prefixes = tuple(p for p in args.only.split(",") if p)

    ops = write_ops(doc, prefixes)
    # 排除"参数是文件"的端点：喂不了文件，测出来的是"没给文件"，没有信息量
    ops = [o for o in ops if "multipart/form-data" not in json.dumps(o.fields)]
    min_ops = 1 if prefixes else 60
    # 阈值 60：去掉白名单后的写端点当前是 79 个。留余量给"以后删几个端点"，
    # 但不能低到"枚举逻辑坏了也能过"——这个门槛就是把"清单算空了"变成硬失败的那种检查。
    rep.guard(f"枚举到写端点 ≥ {min_ops} 个（openapi 清单是机器算的）", len(ops) >= min_ops,
              f"实际 {len(ops)} 个（--only={args.only or '全部'}）")
    rep.guard("后端可达且能登录", bool(api.login("dispatcher")), "登录失败")

    # 真实 id 池：让带引用字段的请求能走到业务逻辑里
    pool: dict[str, list[int]] = {}
    for key, sql in (
        ("order", "select id from orders where deleted_at is null order by id desc limit 5"),
        ("product", "select id from products where is_deleted=0 order by id desc limit 5"),
        ("driver", "select id from users where role='DRIVER' order by id limit 5"),
        ("shipper", "select id from users where role='SHIPPER' order by id limit 5"),
        ("rule", "select id from driver_billing_rules order by id limit 5"),
        ("unit", "select id from arrears_units order by id limit 5"),
    ):
        try:
            pool[key] = [r[0] for r in db_q(sql)]
        except Exception:
            pool[key] = []
    rep.guard("id 池至少拿到订单/商品/司机（不然引用类字段全走 404）",
              all(pool.get(k) for k in ("order", "product", "driver")),
              f"pool={ {k: len(v) for k, v in pool.items()} }")

    # ---- 安全机制自检：**证明"不碰真实数据"这条约束真的生效**
    # （第一版这里没有自检，结果工具真的去调了 /orders/{id}/assign、
    #   并且拿真实订单 id 去批量派单——"看着安全"和"确实安全"是两件事）
    probe_path = fill_path("/orders/{order_id}/assign")
    rep.guard("路径参数一律换成不存在的 id（安全模式生效）",
              probe_path == "/orders/999999999/assign", f"实际 {probe_path}")
    rep.guard("白名单拦得住按真实 id 的恢复端点",
              denied("POST", "/orders/123/restore") is not None, "denied() 没认出 restore")
    # 批量端点必须**按类**拦住（不是只拦住出事的那一个）：
    # `POST /price-rules/batch` 曾经被本工具喂 1e20、一次改掉 2880 行专属价。
    for risky, label in (
        ("/price-rules/batch", "批量调价"),
        ("/orders/batch-assign", "批量派单"),
        ("/driver-bills/generate", "批量生成司机账单"),
        ("/ledger/sync-from-delivered-orders", "全量回写账本"),
    ):
        rep.guard(f"白名单拦得住{label}（{risky}）", denied("POST", risky) is not None,
                  "BULK_PATTERN 没覆盖到——这一类漏一个就会改到没建过的行")
    body_refs = pool if args.refs else {}
    print(f"  ⊙ 自检  请求体引用 id：{'真实 id（--refs）' if args.refs else '不存在 id（默认安全）'}")

    n_req = 0
    n_untested: list[str] = []
    english_422: list[str] = []
    missing_required_accepted: list[str] = []
    created: list[str] = []
    bad_type_bug: set[str] = set()
    server_errors: set[str] = set()
    accepted_bad: dict[str, str] = {}

    for op in ops:
        if n_req >= args.max:
            rep.info(f"请求预算用尽（{args.max}），后面的端点没测", f"剩余 {len(ops) - ops.index(op)} 个")
            break
        tok, role = pick_token(api, op)
        if tok is None:
            n_untested.append(op.key)
            continue
        path = fill_path(op.path)
        if denied(op.method, path):  # 双保险：即使枚举漏了，也不许真的发出去
            n_untested.append(op.key + "（白名单禁）")
            continue
        base_body = baseline_body(op, body_refs)
        if op.is_list:
            base_body = [base_body]

        rep.section(op.key + (f"  [{role}]" if role != "dispatcher" else ""))

        # ---- 基线：它到底能不能跑通
        r0 = api.req(op.method, path, base_body if op.method != "DELETE" else None, tok)
        n_req += 1
        if r0.is_5xx:
            server_errors.add(op.key)
            rep.bug(f"基线请求就 500：{op.key}",
                    f"最小合法体 {json.dumps(base_body, ensure_ascii=False)[:200]} → {r0.evidence(500)}")
        elif r0.is_2xx:
            rep.info(f"基线成功（{r0.status}）", r0.evidence(120))
            cleanup(api, op, r0, ops, tok, created)
        elif "不存在" in r0.text or r0.status == 404:
            rep.info(f"基线 404/不存在（预期：路径参数是假 id {path}）", r0.evidence(120))
        elif r0.status == 400:
            rep.info(f"基线 400（本工具造的最小体不够用，只测「能不能不崩」）", r0.detail[:160])

        fields = op.fields
        if len(fields) > MAX_FIELDS_PER_OP:
            req_f = [f for f in fields if f["required"]]
            rest = [f for f in fields if not f["required"]]
            fields = req_f + rest[: max(0, MAX_FIELDS_PER_OP - len(req_f))]

        for f in fields:
            if n_req >= args.max:
                break
            name, typ = f["name"], f["type"]

            # ---- ① 必填字段删掉，它接不接
            if f["required"] and name in base_body:
                stripped = dict(base_body)
                stripped.pop(name, None)
                r = api.req(op.method, path, [stripped] if op.is_list else stripped, tok)
                n_req += 1
                if r.is_5xx:
                    server_errors.add(op.key)
                    rep.bug(f"删掉必填字段 {name} 直接 500：{op.key}",
                            f"{r.evidence(300)}")
                elif r.is_2xx:
                    missing_required_accepted.append(f"{op.key} 缺 {name} → {r.status}")
                    cleanup(api, op, r, ops, tok, created)
                if r.pydantic_422:
                    english_422.append(f"{op.key}:{name}")

            # ---- ② 类型/边界喂坏值
            bads = bad_values(typ)[:MAX_BAD_PER_FIELD]
            for label, val in bads:
                if n_req >= args.max:
                    break
                body = dict(base_body)
                body[name] = val
                r = api.req(op.method, path, [body] if op.is_list else body, tok)
                n_req += 1
                if r.is_5xx:
                    if r.sqlite_busy:
                        rep.info(f"SQLite 写锁冲突（环境限制，不算缺陷）：{op.key} {name}={label}")
                        continue
                    server_errors.add(op.key)
                    rep.bug(f"{name} = {label} → 500：{op.key}",
                            f"{r.evidence(400)}\n    请求体 {json.dumps(body, ensure_ascii=False)[:300]}")
                elif r.pydantic_422:
                    english_422.append(f"{op.key}:{name}")
                elif r.is_2xx:
                    cleanup(api, op, r, ops, tok, created)
                    if label in ("负数", "零", "极大整数", "超长数字", "对象", "数组", "超长(8k)", "换行"):
                        key = f"{op.key}.{name}"
                        if key not in accepted_bad:
                            accepted_bad[key] = f"{name}={label} → {r.status} {r.text[:160]}"

    # ---------------------------------------------------------------- 结论
    rep.section("汇总")
    min_req = min(200, max(20, 5 * len(ops)))
    rep.guard(f"至少发出 {min_req} 个请求（低于此说明几乎没测到）", n_req >= min_req, f"实际 {n_req}")
    rep.guard("至少有一个端点被真正测过（有 2xx/4xx 业务响应）",
              n_req > len(n_untested), f"未测 {len(n_untested)}")

    rep.info(f"共发请求 {n_req} 个，覆盖 {len(ops) - len(n_untested)}/{len(ops)} 个写端点")
    if n_untested:
        rep.info(f"{len(n_untested)} 个端点三个角色都 403/401，没测到",
                 "、".join(n_untested[:15]) + ("…" if len(n_untested) > 15 else ""))
    if server_errors:
        rep.bug(f"{len(server_errors)} 个端点存在 5xx（见上文明细）", "、".join(sorted(server_errors)))
    else:
        rep.ok("没有任何端点对脏输入返回 5xx")
    if english_422:
        uniq_eps = sorted({e.split(":")[0] for e in english_422})
        rep.risk(f"{len(english_422)} 次校验失败返回英文 422 结构体（覆盖 {len(uniq_eps)} 个端点）",
                 "Pydantic 原生体：{\"detail\":[{\"type\":\"missing\",\"loc\":[...]}]} —— "
                 "手机/AI 界面直接把它摆给用户看。示例端点：" + "、".join(uniq_eps[:8]))
    if missing_required_accepted:
        rep.risk(f"{len(missing_required_accepted)} 次「契约说必填、实际不给也收」",
                 "；".join(missing_required_accepted[:8]))
    if accepted_bad:
        rep.risk(f"{len(accepted_bad)} 处「明显不合理的值被接受」（要看落库后果）",
                 "；".join(f"{k}: {v}" for k, v in list(accepted_bad.items())[:10]))
    if created:
        rep.info(f"突变过程中真的建出了 {len(created)} 行，已尽力删除", "；".join(created[:10]))
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
