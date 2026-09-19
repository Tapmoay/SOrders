"""SOrders 漏洞挖掘工具集 · 公共库。

## 为什么需要一层公共库
前面几轮"挖漏洞"是一个个手写探针：能挖到东西，但每换一个角度就要重写登录、
重写"怎么判断这是条真缺陷"、重写清理。代价是**判据写法每次都不一样**，
而"判据写空转"这件事这个项目已经栽过 5 次（检查全绿、其实一条都没查）。

所以这里把三件事固定下来，上层工具只管提问：

1. **看不见目标就不许下结论**：`Report.guard()` 在"枚举到 0 个端点""一次有效请求都没发出去"
   这类情况下**直接中止**并返回非零退出码。检查空转比检查报错危险得多。
2. **判据锚效果，不锚声明**：结论只能来自 HTTP 状态码/响应体，或数据库里的真实行。
   代码注释写着"会拒"不算证据——这个项目已经有过注释与行为相反的实例（DELETE 定义两次）。
3. **自己建的数据自己清 + 破坏性端点白纸黑字禁掉**：见 `DENY`。工具是给开发库用的，
   但"开发库"里也有真数据（生产导出过备份、UAT 单还在），不该由 fuzz 的随机性来决定删什么。

## 环境变量
- `SORDERS_BASE`：默认 `http://127.0.0.1:8000/api/v1`
- `SORDERS_DB`：默认 `<repo>/backend/sorders.db`（只读打开）
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("SORDERS_BASE", "http://127.0.0.1:8000/api/v1")
API_ROOT = BASE.split("/api/")[0]
DB_PATH = Path(os.environ.get("SORDERS_DB", str(ROOT / "backend" / "sorders.db")))
OUT_DIR = Path(__file__).resolve().parent / "out"

#: 本机开发账号（backend/scripts/seed_dev_users.py）。密码统一 123321。
CREDS: dict[str, tuple[str, str]] = {
    "dispatcher": ("13800000001", "123321"),
    "shipper": ("13800000002", "123321"),
    "driver": ("13800000003", "123321"),
}

#: 数据标记：本次运行建出来的行都带它，方便"只清自己的"。
MARK = "fz" + uuid.uuid4().hex[:5]

#: ⛔ 任何 fuzz 工具都不许调的端点。
#: 判据不是"危险"，而是"**调用它造成的损失不落在本工具建的数据上**"。
DENY: list[tuple[str, str, str]] = [
    ("DELETE", r"^/users/\d+$", "删账号：会连人带历史一起没了"),
    ("POST", r"^/users/\d+", "改账号：包含改密码/改角色，能把自己锁在门外"),
    ("POST", r"^/notifications/batch-delete$", "批量删消息：all=true 会清空收件箱"),
    ("POST", r"^/ledger/export-jobs$", "导出任务：产生后台作业"),
    ("POST", r"^/stats/export$", "导出：产物是文件，且会打全量数据"),
    ("POST", r"^/customers/merge$", "客户合并：不可逆"),
    ("POST", r"^/orders/\d+/restore$", "恢复软删单：会动不属于本工具的行"),
    ("POST", r"^/system/", "系统级端点"),
    ("POST", r"^/auth/", "凭据端点：登录/注册不在 fuzz 范围（登录走 Api.login）"),
    ("POST", r"^/files/", "上传：需要真实文件"),
]

#: ⛔ **一整类**端点：批量 / 全量 / 生成 / 回写。
#:
#: 为什么单列一条规则而不是逐个拉黑：2026-09-17 的事故就是漏了一个
#: ——`POST /price-rules/batch` 被喂了 1e20，它**没有上限校验也没有影响行数确认**，
#: 一次把 20 个批发商 × 144 个商品 = 2880 条专属价全改了（其中 2822 条是凭空新建的）。
#: 事后靠 09-15 的库备份 + operation_logs 的 before 值才还原回来（见
#: `_repair_price_rules_batch.py`）。
#: 教训：**"接口只会改我自己建的数据"这个假设，对批量端点根本不成立**，
#: 所以规则要按类写，不能按"我想起来的那一个"写。
BULK_PATTERN = re.compile(r"(^|[/_-])(batch|bulk|sync|generate|apply|rebuild|import|backfill|recalc|reseed)($|[/_-])")
BULK_WHY = "批量/全量端点：一次调用会改到本工具没建过的行，默认禁止"


def denied(method: str, path: str) -> str | None:
    p = path.split("?")[0]
    for m, rx, why in DENY:
        if method.upper() == m and re.search(rx, p):
            return why
    if BULK_PATTERN.search(p):
        return BULK_WHY
    return None


# --------------------------------------------------------------------- HTTP

@dataclass
class Resp:
    status: int
    text: str
    ms: float
    method: str
    path: str
    body: Any = None
    error: str = ""

    @property
    def is_5xx(self) -> bool:
        return 500 <= self.status < 600

    @property
    def is_2xx(self) -> bool:
        return 200 <= self.status < 300

    @property
    def detail(self) -> str:
        """人话版错误详情（后端 400 用 detail 字符串，422 用 detail 列表）。"""
        if isinstance(self.body, dict):
            d = self.body.get("detail")
            if isinstance(d, str):
                return d
            if isinstance(d, list):
                return "; ".join(str(x.get("msg", x)) if isinstance(x, dict) else str(x) for x in d)
        return self.text[:200]

    @property
    def pydantic_422(self) -> bool:
        """Pydantic 原生 422（英文结构体）。本项目要求给用户中文，所以这是缺陷。"""
        if self.status != 422 or not isinstance(self.body, dict):
            return False
        d = self.body.get("detail")
        return bool(
            isinstance(d, list)
            and d
            and all(isinstance(x, dict) and {"type", "loc", "msg"} <= set(x) for x in d)
            and not any("\u4e00" <= ch <= "\u9fff" for ch in json.dumps(d, ensure_ascii=False))
        )

    @property
    def sqlite_busy(self) -> bool:
        """本地 SQLite 的写锁冲突——环境限制，不是应用缺陷。"""
        low = self.text.lower()
        return "database is locked" in low or "database table is locked" in low

    def evidence(self, body_chars: int = 300) -> str:
        head = f"{self.method} {self.path} -> {self.status}"
        if self.error:
            head += f" ({self.error})"
        return f"{head} | {self.text[:body_chars]}"


class Api:
    """一个带 token 缓存的极简客户端。

    刻意不用 requests：这套工具要在**任何** python 上跑起来（包括没装依赖的），
    否则"能挖漏洞的工具"会退化成"在特定机器上能挖漏洞的工具"。
    """

    def __init__(self, base: str = BASE) -> None:
        self.base = base
        self.tokens: dict[str, str] = {}

    def req(
        self,
        method: str,
        path: str,
        body: Any = None,
        token: str | None = None,
        *,
        raw: bytes | None = None,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
        allow_denied: bool = False,
    ) -> Resp:
        if not allow_denied:
            why = denied(method, path)
            if why:
                raise PermissionError(f"端点被工具白名单禁掉：{method} {path}（{why}）")
        data = raw if raw is not None else (
            json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        )
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = "Bearer " + token
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                txt = r.read().decode("utf-8", "replace")
                return Resp(r.status, txt, (time.perf_counter() - t0) * 1000, method, path, _load(txt))
        except urllib.error.HTTPError as e:
            txt = e.read().decode("utf-8", "replace")
            return Resp(e.code, txt, (time.perf_counter() - t0) * 1000, method, path, _load(txt))
        except Exception as e:  # 连接层错误：如实记录，不伪装成 HTTP 状态
            return Resp(0, "", (time.perf_counter() - t0) * 1000, method, path, None, f"{type(e).__name__}: {e}")

    # -- 便捷
    def get(self, path: str, token: str | None = None, **kw) -> Resp:
        return self.req("GET", path, token=token, **kw)

    def post(self, path: str, body: Any = None, token: str | None = None, **kw) -> Resp:
        return self.req("POST", path, body, token, **kw)

    def patch(self, path: str, body: Any = None, token: str | None = None, **kw) -> Resp:
        return self.req("PATCH", path, body, token, **kw)

    def delete(self, path: str, token: str | None = None, **kw) -> Resp:
        return self.req("DELETE", path, token=token, **kw)

    def login(self, role: str) -> str:
        if role in self.tokens:
            return self.tokens[role]
        phone, pwd = CREDS[role]
        # 登录本身在 DENY 表里（凭据端点不是 fuzz 目标），但工具自己必须能进门
        r = self.post("/auth/login", {"phone": phone, "password": pwd}, allow_denied=True)
        if not r.is_2xx or not isinstance(r.body, dict) or "access_token" not in r.body:
            raise SystemExit(f"✗ 登录失败（{role} {phone}）：{r.evidence()} —— 后端没起来或账号/密码不对？")
        self.tokens[role] = r.body["access_token"]
        return self.tokens[role]

    def all_roles(self) -> dict[str, str]:
        return {r: self.login(r) for r in CREDS}


def _load(txt: str) -> Any:
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


# --------------------------------------------------------------------- 报告

@dataclass
class Finding:
    kind: str  # BUG / RISK / INFO
    title: str
    evidence: str
    where: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class Report:
    """结论收集器：区分 **确认缺陷 / 可疑待验证 / 信息**，并把"空转"变成硬失败。"""

    def __init__(self, title: str, *, module: str = "") -> None:
        self.title = title
        self.module = module or Path(sys.argv[0]).stem
        self.findings: list[Finding] = []
        self._seen: set[str] = set()
        self.n_checks = 0
        self.t0 = time.perf_counter()
        self.sections: list[str] = []
        print(f"\n{'=' * 78}\n{title}   [标记 {MARK}]\n{'=' * 78}")

    # -- 记账
    def section(self, name: str) -> None:
        self.sections.append(name)
        print(f"\n── {name} " + "─" * max(0, 66 - len(name)))

    def add(self, kind: str, title: str, evidence: str, where: str = "", **extra: Any) -> None:
        self.n_checks += 1
        key = f"{kind}|{title}"
        icon = {"BUG": "✗ 缺陷", "RISK": "? 可疑", "INFO": "· 信息"}[kind]
        print(f"  {icon}  {title}")
        print(f"          {evidence[:400]}")
        if key in self._seen:
            return
        self._seen.add(key)
        self.findings.append(Finding(kind, title, evidence, where, extra))

    def bug(self, title: str, evidence: str, where: str = "", **extra: Any) -> None:
        """**确认缺陷**：有可复现证据、后果明确。"""
        self.add("BUG", title, evidence, where, **extra)

    def risk(self, title: str, evidence: str, where: str = "", **extra: Any) -> None:
        """**可疑待验证**：行为不合预期，但"应该怎样"取决于产品口径，或证据不足以定罪。"""
        self.add("RISK", title, evidence, where, **extra)

    def info(self, title: str, evidence: str = "") -> None:
        self.add("INFO", title, evidence)

    def ok(self, title: str) -> None:
        """一条"查过没问题"也要计数——否则无法区分"没问题"和"没查"。"""
        self.n_checks += 1
        print(f"  ✓ 通过  {title}")

    # -- 反空转
    def guard(self, label: str, cond: bool, detail: str = "") -> None:
        """自检：**证明这次运行真的看得见目标**。不成立就直接退出（非零码）。"""
        self.n_checks += 1
        if cond:
            print(f"  ⊙ 自检  {label}")
            return
        print(f"\n⛔ 自检失败：{label}\n   {detail}\n"
              f"   这次运行**不能**得出结论（可能一条都没查），因此按失败退出。")
        sys.exit(3)

    # -- 收尾
    def finish(self) -> int:
        bugs = [f for f in self.findings if f.kind == "BUG"]
        risks = [f for f in self.findings if f.kind == "RISK"]
        infos = [f for f in self.findings if f.kind == "INFO"]
        dt = time.perf_counter() - self.t0
        OUT_DIR.mkdir(exist_ok=True)
        out = OUT_DIR / f"{self.module}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        out.write_text(json.dumps({
            "module": self.module, "title": self.title, "mark": MARK,
            "base": BASE, "checks": self.n_checks, "seconds": round(dt, 1),
            "bugs": [f.__dict__ for f in bugs], "risks": [f.__dict__ for f in risks],
            "infos": [f.__dict__ for f in infos],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n{'=' * 78}")
        print(f"小结：检查 {self.n_checks} 项 / 确认缺陷 {len(bugs)} / 可疑 {len(risks)} / 信息 {len(infos)}"
              f" / {dt:.1f}s")
        for f in bugs:
            print(f"  ✗ {f.title}")
        for f in risks:
            print(f"  ? {f.title}")
        print(f"明细：{out}")
        return 2 if bugs else 0


# ---------------------------------------------------------------- 数据库(只读)

def db_ro() -> sqlite3.Connection:
    """只读连接：fuzz 工具**永远不写库**，核对一律走 HTTP + 只读查询。"""
    if not DB_PATH.is_file():
        raise SystemExit(f"✗ 找不到数据库 {DB_PATH}（用 SORDERS_DB 指定）")
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def db_q(sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    with db_ro() as c:
        return list(c.execute(sql, params))


def db_one(sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    rows = db_q(sql, params)
    return rows[0] if rows else None


# ---------------------------------------------------------------- 金额/金额口径

CENT = Decimal("0.01")


def money(v: Any) -> Decimal:
    """与后端 `app/services/driver_pay.money` 同口径：先算后按分四舍五入。"""
    return Decimal(str(v if v is not None else "0")).quantize(CENT, rounding=ROUND_HALF_UP)


def dec(v: Any) -> Decimal:
    return Decimal(str(v if v is not None else "0"))


# ---------------------------------------------------------------- 值合成

NAME_HINTS: list[tuple[re.Pattern[str], Any]] = [
    (re.compile(r"(^|_)(phone|mobile|tel)($|_)"), "13900000001"),
    (re.compile(r"(^|_)(lat)($|_)"), "39.9042"),
    (re.compile(r"(^|_)(lng|lon)($|_)"), "116.4074"),
    (re.compile(r"(^|_)(date|day)($|_)"), None),  # 运行时填今天
    (re.compile(r"(_at|time|datetime)$"), None),
    (re.compile(r"(amount|price|fee|rate|cost|total|salary|money)"), "10.00"),
    (re.compile(r"(qty|quantity|count|num|pieces|stock|damage)"), 1),
    (re.compile(r"(^|_)(name|title|label|remark|note|reason|desc|description|address|detail)($|_)"),
     f"fuzz-{MARK}"),
    (re.compile(r"(_ids?|ids)$"), None),  # 运行时填本工具建的对象 id
    (re.compile(r"^(is_|has_|allow_|collect_)"), False),
    (re.compile(r"password"), "123321"),
]


def synth_value(name: str, typ: str = "str", schema: dict[str, Any] | None = None, pool: dict[str, list[int]] | None = None) -> Any:
    """按字段名/类型造一个"看起来合法"的值。

    刻意**不从 schema 的 example 抄**：后端 schema 里几乎没写 example，
    而字段名本身已经承载了口径（`quantity` 就是数量、`*_id` 就是引用）。
    """
    schema = schema or {}
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if schema.get("default") is not None:
        return schema["default"]
    base_type = {"integer": "int", "number": "str", "boolean": "bool", "array": "list", "object": "dict"}.get(typ, typ)
    # 引用类字段要真实 id，否则一律 400/404，什么也测不到
    if pool is not None and re.search(r"(^|_)id$|_ids$", name):
        for key, ids in pool.items():
            if ids and key in name:
                return ids[0] if not name.endswith("_ids") and name != "ids" else ids[:2]
    for rx, val in NAME_HINTS:
        if rx.search(name):
            if val is None:
                if rx.pattern.endswith("(date|day)($|_)"):
                    return date.today().isoformat()
                if rx.pattern.endswith("(_ids?|ids)$"):
                    return (pool or {}).get("order", [])[:1]
                return datetime.now(timezone.utc).isoformat()
            return val
    return {
        "int": 1, "str": f"fuzz-{MARK}", "bool": False, "list": [], "dict": {},
    }.get(base_type, f"fuzz-{MARK}")


def bad_values(typ: str) -> list[tuple[str, Any]]:
    """**故意坏的**值。每一类都对应一种真实的崩溃来源。"""
    common: list[tuple[str, Any]] = [
        ("null", None),
        ("空串", ""),
        ("空格串", "   "),
        ("超长(8k)", "x" * 8000),
        ("对象", {"a": 1}),
        ("数组", [1, 2]),
        ("超长数字", 99999999999999999999),
        ("负数", -1),
        ("零", 0),
        ("中文", "中文测试"),
        ("emoji", "🚚"),
        ("引号", "'; drop table orders; --"),
        ("百分号", "%s%d{}"),
        ("换行", "a\nb"),
    ]
    if typ in ("int", "integer"):
        return [(f"字符串给整数({n})", v) for n, v in common if not isinstance(v, (int, dict))] + [
            ("小数给整数", 1.5), ("布尔给整数", True), ("极大整数", 2**63),
        ]
    if typ in ("str", "string"):
        return common + [("布尔给字符串", True), ("数组给字符串", ["a"])]
    if typ in ("bool", "boolean"):
        return [("字符串给布尔", "yes"), ("数字给布尔", 2), ("null给布尔", None), ("对象给布尔", {})]
    if typ in ("list", "array"):
        return [("字符串给数组", "a"), ("数字给数组", 7), ("null给数组", None), ("对象给数组", {"a": 1})]
    return common


def openapi() -> dict[str, Any]:
    # ⚠️ openapi.json 挂在**根**上（/api/v1 之下没有），所以用 API_ROOT 而不是 BASE
    r = Api(API_ROOT).get("/openapi.json")
    if r.status != 200 or not isinstance(r.body, dict):
        # 有的部署把 openapi 关了；退到仓库里的快照
        snap = ROOT / "docs" / "openapi.snapshot.json"
        if snap.is_file():
            return json.loads(snap.read_text(encoding="utf-8"))
        raise SystemExit(f"✗ 拿不到 /openapi.json：{r.evidence()}（也没有仓库快照）")
    return r.body


def resolve_ref(doc: dict[str, Any], node: Any, _depth: int = 0) -> dict[str, Any]:
    if not isinstance(node, dict) or _depth > 6:
        return {}
    if "$ref" in node:
        ref = node["$ref"]
        if ref.startswith("#/"):
            cur: Any = doc
            for part in ref[2:].split("/"):
                cur = (cur or {}).get(part, {})
            return resolve_ref(doc, cur, _depth + 1)
    return node


def body_fields(doc: dict[str, Any], op: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """把请求体 schema 摊平成字段表：`[{name, type, required, schema}]`。

    支持 object 与「list[object]」（后端有若干端点的入参就是数组）。
    """
    rb = op.get("requestBody") or {}
    content = (rb.get("content") or {}).get("application/json") or {}
    schema = resolve_ref(doc, content.get("schema") or {})
    is_list = schema.get("type") == "array"
    if is_list:
        schema = resolve_ref(doc, schema.get("items") or {})
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    out = []
    for name, raw in props.items():
        sch = resolve_ref(doc, raw)
        out.append({
            "name": name,
            "type": sch.get("type") or ("str" if "anyOf" in sch else "str"),
            "required": name in required,
            "schema": sch,
        })
    return out, is_list


@dataclass
class Op:
    method: str
    path: str          # 形如 /orders/{order_id}
    fields: list[dict[str, Any]]
    is_list: bool = False
    summary: str = ""

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


def write_ops(doc: dict[str, Any], prefixes: Sequence[str] = (), skip_denied: bool = True) -> list[Op]:
    """枚举写端点（POST/PATCH/PUT/DELETE）。**机器算出来的清单**，不手写。

    ⚠️ openapi 里的路径带 `/api/v1` 前缀，而 `Api.base` 已经含它了：这里必须**归一化**，
    否则每个请求都会打到 `/api/v1/api/v1/...` 上，工具会"全部 404 却一条都不报错"。
    """
    out: list[Op] = []
    for path, methods in (doc.get("paths") or {}).items():
        path = re.sub(r"^/api/v1", "", path) or "/"
        for method, spec in methods.items():
            m = method.upper()
            if m not in ("POST", "PATCH", "PUT", "DELETE"):
                continue
            if prefixes and not any(path.startswith(p) for p in prefixes):
                continue
            if skip_denied and denied(m, re.sub(r"\{[^}]+\}", "1", path)):
                # ⚠️ 这一行必须用**填好数字的**路径去判：DENY 里的规则写的是 `/orders/\d+/restore`，
                # 拿带 `{order_id}` 的模板去判永远不匹配 —— 第一版就是这样，
                # 结果是"白名单看着有、其实一次都没生效"（探针反而去调了 /orders/{id}/restore）。
                continue
            f, is_list = body_fields(doc, spec)
            out.append(Op(m, path, f, is_list, (spec.get("summary") or "")[:40]))
    return sorted(out, key=lambda o: (o.path, o.method))


def fill_path(path: str, ids: dict[str, Any] | None = None, default: int = 999999999) -> str:
    """把 {order_id} 换成真实 id（有的话）或一个不存在的 id。"""
    ids = ids or {}
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        for key, val in ids.items():
            if key in name and isinstance(val, int):
                return str(val)
        return str(default)
    return re.sub(r"\{([^}]+)\}", sub, path)


def uniq(prefix: str) -> str:
    return f"{prefix}-{MARK}"
