"""把 Pydantic 的**英文**校验结构体翻成一句中文（App / AI / 人都要看得懂）。

### 为什么要有这一层
Pydantic 校验失败时 FastAPI 默认回：

```json
{"detail":[{"type":"string_too_long","loc":["body","delivery_description"],
            "msg":"String should have at most 512 characters","input":"…"}]}
```

这句英文会被手机界面**原样**摆给用户（`core/ApiClient.kt::parseDetail` 就是为此才写了
一张"英文 msg → 中文"的对照表），AI 也会把它抄进回答里。而这类错误**恰恰全都能自助修好**
（少写几个字、日期写成 2026-09-18、最多选 100 项），前提是这句话说清楚了三件事：
**哪个字段、哪里不对、应该改成什么**。

所以：**状态码仍然是 422**（客户端与测试的既有约定不变），只把 `detail` 换成人话。
原始错误数组仍放在 `errors` 里（排障用，界面不显示）。

⚠️ 覆盖不到的类型**不许把英文原文甩出去**（那是这个文件存在的全部意义）——
认不出来的一律给一句能行动的中文兜底。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

#: 字段名 → 中文（同一列的两种叫法都列上；查不到就用字段名本身，不猜）
FIELD_CN: dict[str, str] = {
    # 通用名
    "name": "名称",
    "title": "标题",
    "content": "内容",
    "remark": "备注",
    "note": "备注",
    "reason": "原因",
    "phone": "手机号",
    "password": "密码",
    "username": "登录名",
    "month": "月份",
    "amount": "金额",
    "quantity": "数量",
    "unit_price": "单价",
    "total": "金额",
    "note_text": "备注",
    # 订单
    "delivery_description": "送货说明",
    "address_detail": "送货地址",
    "contact_dongjia_phone": "货主电话",
    "contact_boss_phone": "老板电话",
    "internal_notes": "内部备注",
    "driver_remark": "司机备注",
    "damage_note": "货损说明",
    "delivery_photo_urls": "送达照片",
    "product_name_snapshot": "商品名",
    "temp_shipper_name": "临时货主",
    "exception_reason": "异常原因",
    "exception_resolution": "异常处理",
    # 地址 / 联系人 / 地点
    "receiver_name": "收货人",
    "detail_address": "地址",
    "origin_address": "起点地址",
    "display_name": "联系人姓名",
    "image_url": "图片",
    "image_urls": "图片",
    # 车辆 / 账务
    "plate_no": "车牌号",
    "vehicle_type": "车型",
    "entry_date": "记账日期",
    "exp_date": "开销日期",
    "received_at": "收款日期",
    "order_ids": "订单",
    "shipper_ids": "货主",
    "product_ids": "商品",
    "settle_mode": "收款方式",
    "payment": "收款方式",
    "action": "动作",
    "category": "分类",
    "commission_product_ids": "抽成商品",
    # 报表筛选与消息列表（2026-09-19 审计 R14-15：报表导出原来把非法日期抛成 500，
    # 改成真正的 `date` 类型后走这里；字段名不翻译的话用户看到的是英文 key）
    "kind": "报表类型",
    "mode": "统计口径",
    "date": "日期",
    "anchor": "日期",
    "date_from": "开始日期",
    "date_to": "结束日期",
    "days": "天数",
    "limit": "条数",
    "before_id": "翻页游标",
    "recipient_id": "收件人",
    "unread_only": "只看未读",
}

#: 枚举值 → 中文（只列"用户一眼认不出"的那些：cash/arrears/tmp…）
VALUE_CN: dict[str, str] = {
    "cash": "现金",
    "transfer": "转账",
    "wechat": "微信",
    "bank": "银行",
    "arrears": "挂账",
    "arrears_settle": "挂账结清",
    "confirm": "确认",
    "pay": "付款",
    "cancel": "作废",
    "itemized": "逐单核销",
    "rolling": "滚动收款",
    "tmp": "散客",
    "registered": "注册货主",
    "piece": "按单计费",
    "salary": "固定工资",
    "default": "通用价",
    "special": "专属价",
}

#: Pydantic 的 `type` → 中文句型。`{…}` 由 ctx 填。
#: ⚠️ 只能写**一定存在**的键：`string_too_long` 的 ctx 里只有 `max_length`（没有
#: `actual_length`，本轮实测 KeyError → 处理器自己 500）。实际长度由 `describe` 从
#: `input` 现算，拼进 `{actual}`（缺失时是空串，不会印出"（现在  个）"这类残句）。
TYPE_CN: dict[str, str] = {
    "missing": "必填",
    "string_too_long": "最多 {max_length} 个字{actual}",
    "string_too_short": "至少 {min_length} 个字",
    "string_type": "要填文字",
    "string_pattern_mismatch": "格式不对",
    "int_parsing": "要填整数",
    "int_type": "要填整数",
    "int_from_float": "要填整数（不能带小数点）",
    "float_parsing": "要填数字",
    "decimal_parsing": "要填数字",
    "decimal_max_digits": "数字太长了（最多 {max_digits} 位）",
    "decimal_max_places": "小数位太多了（最多 {decimal_places} 位）",
    "greater_than": "要大于 {gt}",
    "greater_than_equal": "不能小于 {ge}",
    "less_than": "要小于 {lt}",
    "less_than_equal": "不能大于 {le}",
    "list_too_long": "最多 {max_length} 项",
    "list_too_short": "至少 {min_length} 项",
    "too_long": "最多 {max_length} 项",
    "too_short": "至少 {min_length} 项",
    "list_type": "要填一组值",
    "bool_parsing": "要填是/否",
    "bool_type": "要填是/否",
    "date_parsing": "日期要写成 2026-09-18",
    "date_from_datetime_parsing": "日期要写成 2026-09-18",
    "datetime_parsing": "时间格式不对",
    "time_parsing": "时间格式不对",
    "enum": "取值不在允许范围内",
    "literal_error": "取值不在允许范围内",
    "json_invalid": "请求体不是合法的 JSON",
    "dict_type": "要填一组键值",
    "model_attributes_type": "要填一组字段",
}

#: `^(a|b|c)$` 这种"枚举式" pattern：直接把可选项列出来（比"格式不对"有用得多）
_ENUM_PATTERN = re.compile(r"^\^\(([^()]+)\)\$$")

FALLBACK = "填写的内容不符合要求，请检查后重试"


def _field_label(loc: tuple[Any, ...]) -> str:
    """错误位置 → 人话字段名（去掉 body/query/path 这类来源前缀与列表下标）。"""
    parts = [str(x) for x in loc if x not in ("body", "query", "path", "header", "cookie")]
    parts = [p for p in parts if not p.isdigit()]
    if not parts:
        return "请求内容"
    key = parts[-1]
    return FIELD_CN.get(key, key)


class _SafeDict(dict):
    """缺键时给空串：模板里写了可选片段也不至于抛 KeyError（处理器自己报错=用户拿到 500）。"""

    def __missing__(self, _key: str) -> str:
        return ""


def describe(errors: list[dict[str, Any]]) -> str:
    """一组 Pydantic 错误 → 一句话（多条用「；」连起来，最多 4 条）。"""
    out: list[str] = []
    for e in errors[:4]:
        etype = str(e.get("type", ""))
        ctx = dict(e.get("ctx") or {})
        msg = str(e.get("msg", ""))
        inp = e.get("input")
        # 我们自己 validator 抛的中文（pydantic 会加 "Value error, " 前缀）
        if etype == "value_error" and any("\u4e00" <= ch <= "\u9fff" for ch in msg):
            out.append(msg.replace("Value error, ", ""))
            continue
        label = _field_label(tuple(e.get("loc", ())))
        if etype == "string_pattern_mismatch":
            m = _ENUM_PATTERN.match(str(ctx.get("pattern", "")))
            opts = " / ".join(VALUE_CN.get(o, o) for o in m.group(1).split("|")) if m else ""
            out.append(f"{label}：只能是 {opts}" if opts else f"{label}：{TYPE_CN['string_pattern_mismatch']}")
            continue
        tpl = TYPE_CN.get(etype)
        if tpl:
            if isinstance(inp, str):
                ctx["actual"] = f"（现在 {len(inp)} 个）"
            reason = tpl.format_map(_SafeDict(ctx))
            # 枚举越界时把允许的取值也翻出来（"取值不在允许范围内"单说等于没说）
            allowed = ctx.get("expected")
            if etype == "enum" and isinstance(allowed, str):
                # Pydantic 给的是 `'fuel', 'repair' or 'toll'` 这种串：逗号与 or 都要当分隔符，
                # 否则会印出 "fuel / repair' or 'toll"（本轮实测）
                picks = [p.strip().strip("'\"") for p in re.split(r",|\bor\b", allowed)]
                picks = [p for p in picks if p]
                if picks:
                    reason += "：" + " / ".join(VALUE_CN.get(p, p) for p in picks)
        else:
            # 认不出来的类型：**不许**把英文原文甩给用户
            logger.info("未翻译的校验错误类型 %s：%s", etype, msg)
            reason = FALLBACK
        out.append(f"{label}：{reason}")
    return "；".join(out)


def safe_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """原始错误数组 → **可以 JSON 序列化**的副本。

    ⚠️ Pydantic 的 `ctx` 里装的是**异常对象**（`{"error": ValueError(...)}`），
    直接塞进 JSONResponse 会 `TypeError: Object of type ValueError is not JSON serializable`
    ——处理器自己抛异常，用户拿到的是 500（本轮实测踩到，27 个测试一起变红）。
    """
    out: list[dict[str, Any]] = []
    for e in errors:
        d: dict[str, Any] = {}
        for k, v in e.items():
            if k == "ctx":
                d["ctx"] = {ck: str(cv) for ck, cv in (v or {}).items()}
            elif isinstance(v, tuple):
                d[k] = list(v)          # loc 原来是 ('body','remark')，JSON 里给成数组更好读
            elif isinstance(v, (str, int, float, bool, type(None), list, dict)):
                d[k] = v
            else:
                d[k] = str(v)
        out.append(d)
    return out


def install(app: FastAPI) -> None:
    """注册到 app 上（做成函数是为了让测试能单独验它，不必起整个应用）。"""

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        detail = describe(errors)
        return JSONResponse(
            status_code=422,
            # `errors` 留原始结构给排障（界面只读 detail）
            content={"detail": detail or FALLBACK, "errors": safe_errors(errors)},
        )
