"""AI 操作流水（CHG-0082 / 台账 L-52）—— 用户勾选的「每次 AI 动作都落一行，管理端可查」。

## 用户报的现象

用户 2026-10-08（ref m26776）在勾选表里选了「**要：新增 AI 操作审计，管理端可查**」：
AI 替他执行的每一个动作都要留下「谁 / 何时 / 哪个动作 / 成没成 / 失败原因」。
**失败的那一半必须也在** —— 他真正要回答的问题是「AI 是不是悄悄试过什么、被挡住了」。

## 机制（为什么是中间件，不是各端点自己写）

AI 的写动作走的是**普通业务端点**（模型只能"申请"，用户在确认卡上点过之后
ai/AiWriteService.commit 才去调真实接口），所以**没有任何一个"AI 端点"可以挂**。
唯一区分得出来的是请求头 X-SOrders-Origin: ai（App 里只有 ClientOrigin.asAi 一处会带）。
放在 ASGI 中间件里还有两个别处拿不到的好处：4xx/5xx 也看得见（响应体的 detail 就是失败原因）、
以后新增多少 AI 动作都不用改这里。

## 为什么必须有机器判据

这本账的每一个失败模式都是**静默**的：
- 中间件挂到 RequestIdMiddleware **外面** → request_id 恒为 NULL，两本账再也对不上（不报错）；
- record_ai_operation 改用请求那条会话 → 业务事务一回滚，**失败的那一行正好也没了**
  （而那正是这本账存在的理由；成功路径上一切正常，看不出来）；
- 攒响应体的条件写错（不看 status）→ 每个成功的大列表都被攒进内存，只有线上才会疼；
- Android 侧「只看失败」变成本地过滤 → 界面说"没有了"，而库里还有一堆失败记录没取；
- 动作名认不出时"顺手编一个中文名" → 审计页开始撒谎（用户据此判断 AI 没干过某件事）。

## 为什么全仓扫

这本账横跨四层：后端中间件（core/ai_operation.py）、挂载顺序（main.py）、端点
（api/v1/ai_operations.py），以及 Android 的发出端（core/ClientOrigin.kt + AiWriteService）
与读端（DTO / API / Repo / VM / 页面）。只查其中一层时，另一层改坏了没人会发现。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事

⚠️ 本判据**不替代**运行时证据，它只保证"形状没被改坏"。真正的证据是：
① 真机走查（派单员进设置页 → AI 操作流水：全部 / 只看失败 / 翻页三态）；
② 生产库 ai_operation_logs 里查得到那一行（配合 _tools/ops/_prod_smoke.py --readonly）。

判据 1..9：
1. 表与字段（模型 / 迁移 029 / ⛔ 不许进 schema_bootstrap）
2. 中间件三条硬纪律（独立会话 / 线程池 / 异常吞掉 / 取消原样抛）
3. 只在 AI 请求上记（is_ai_request 自己读头归一）
4. 挂载顺序（必须在 RequestId 里面）
5. 端点（权限沿用 OPERATION_LOG_READ / 三把筛子 / limit+1 / finish_page / user_name）
6. Android 发出端（只有确认执行那一步带头；预览不带头）
7. Android 读端（服务端过滤 / skip 游标 / id 去重 / 认不出不编名字）
8. 单测与入口存在
9. 防静默空转

用法：python _tools/qa/_check_ai_operation_log.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]

CORE = ROOT / "backend/app/core/ai_operation.py"
ORIGIN = ROOT / "backend/app/core/client_origin.py"
MAIN = ROOT / "backend/app/main.py"
API = ROOT / "backend/app/api/v1/ai_operations.py"
MODEL = ROOT / "backend/app/models/ai_operation_log.py"
SCHEMA = ROOT / "backend/app/schemas/ai_operation_log.py"
MIGRATION = ROOT / "backend/app/migrations/029_ai_operation_log.py"
BOOTSTRAP = ROOT / "backend/app/core/schema_bootstrap.py"
RBAC = ROOT / "backend/app/core/rbac.py"
BTEST = ROOT / "backend/tests/test_ai_operation_log.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
APICLIENT = AND / "core/ApiClient.kt"
CLIENTORIGIN = AND / "core/ClientOrigin.kt"
WRITESVC = AND / "ai/AiWriteService.kt"
DTOS = AND / "data/remote/dto/Dtos.kt"
APIS = AND / "data/remote/api/Apis.kt"
REPO = AND / "data/repo/AppRepository.kt"
ROUTES = AND / "ui/nav/Routes.kt"
NAVGRAPH = AND / "ui/nav/NavGraph.kt"
ROWS = AND / "ui/ai/AiOperationRows.kt"
VM = AND / "ui/ai/AiOperationsViewModel.kt"
SCREEN = AND / "ui/ai/AiOperationsScreen.kt"
SETTINGS = AND / "ui/ai/AiSettingsScreen.kt"
ROWS_TEST = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ui/ai/AiOperationRowsTest.kt"

REQUIRED_FILES = [
    CORE, ORIGIN, MAIN, API, MODEL, SCHEMA, MIGRATION, BTEST,
    APICLIENT, CLIENTORIGIN, WRITESVC, DTOS, APIS, REPO,
    ROUTES, NAVGRAPH, ROWS, VM, SCREEN, SETTINGS, ROWS_TEST,
]

#: 全仓 .kt 至少这么多（这个判据要扫 Android 侧，目录被搬走时必须报错而不是全绿）。
MIN_KT = 100


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def code_only(text: str) -> str:
    """去掉注释但**保留换行数**（行号才对得上）。

    ⛔ 不能图省事直接 re.sub 成空串：这几份文件里到处是"为什么这么做"的注释，
    判据要钉的是**代码**里还有没有那条纪律，不是注释里提没提它。
    """
    text = re.sub(r"/\*[\s\S]*?\*/", lambda m: "\n" * m.group(0).count("\n"), text)
    return re.sub(r"//[^\n]*", "", text)


def py_only(text: str) -> str:
    """Python 版的去注释：连 **docstring** 一起去掉（保留换行数）。

    ⛔ 为什么非要连 docstring 一起去：这几份文件的 docstring 里**故意写着**踩过的坑，
    例如 core/ai_operation.py 的 is_ai_request 上写着"不读 get_origin()"——
    不去掉的话，「⛔ 不许读 get_origin()」这条判据会被**解释它自己的注释**判红/判绿。
    """
    text = re.sub(r'"""[\s\S]*?"""', lambda m: "\n" * m.group(0).count("\n"), text)
    return re.sub(r"#[^\n]*", "", text)


def block(text: str, start: str, end: str) -> str:
    """把 start 到下一个 end 之间切出来（防"同一行纪律在文件里出现两次"时判据空转）。"""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:] if j < 0 else text[i:j]


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

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"不该出现却出现了 {pattern!r}")


def main() -> int:
    c = Checker()

    core = read(CORE)
    core_code = py_only(core)
    record = block(core_code, "def record_ai_operation(", "\nclass ")
    middleware = block(core_code, "class AiOperationMiddleware", "\ndef is_ai_request") or core_code
    is_ai = block(core_code, "def is_ai_request(", "\n\ndef ") or core_code

    print("\n== 1. 表与字段 ==")
    model = read(MODEL)
    c.present("模型表名是 ai_operation_logs", model, r'__tablename__ = "ai_operation_logs"')
    for col in [
        "user_id", "action", "method", "path", "status_code",
        "ok", "error", "request_id", "duration_ms", "created_at",
    ]:
        c.present(f"有 {col} 这一列", model, rf"{col}: Mapped\[")
    idx = len(re.findall(r"index=True", model))
    c.ok(f"带索引的列 >= 4（实际 {idx}）：管理端第一眼要筛的就是失败的/某个人的", idx >= 4, str(idx))
    c.present("created_at 用全仓同一个口径 utc_now_naive", model, r"created_at: Mapped\[datetime\][\s\S]{0,160}utc_now_naive")

    mig = read(MIGRATION)
    # ⚠️ 用 \n 包住而不是 ^...$：present() 走 re.search 且不开 MULTILINE，$ 会当成"文件结尾"。
    c.present("迁移号是 029", mig, r"\nVERSION = 29\n")
    c.present("迁移的表名与模型一致", mig, r'\nTABLE = "ai_operation_logs"\n')
    c.present("迁移可重跑（表在就返回）", mig, r"if TABLE in set\(inspect\(engine\)\.get_table_names\(\)\):\s*\n\s*return")
    c.present("迁移用模型建表（两种方言同一形状）", mig, r"AiOperationLog\.__table__\.create\(bind=engine, checkfirst=True\)")

    boot = read(BOOTSTRAP)
    # ⚠️ 用 py_only：这条判据的题眼是"bootstrap 里没有**建这张表**的代码"，
    #    而注释里提一句"这张表走迁移 029、不在这里建"是**好事**，不该被判红。
    c.absent("⛔ schema_bootstrap 里没有这张表（建表走迁移，见 _check_silent_release.py 第 5 条）",
             py_only(boot), r"ai_operation_logs")

    print("\n== 2. 中间件：三条硬纪律 ==")
    c.present("用独立的 SessionLocal（业务回滚不带走审计行）", record or core_code, r"db = SessionLocal\(\)")
    sig = re.search(r"def record_ai_operation\(([\s\S]{0,400}?)\) -> None:", record)
    c.ok("record_ai_operation 不收请求会话当参数（拿了就会跟着业务事务回滚）",
         sig is not None and "session" not in sig.group(1).lower() and "db:" not in sig.group(1),
         sig.group(1)[:120] if sig else "没切到签名")
    c.present("ok = status_code < 400（与访问日志同一口径）", record or core_code, r"ok=int\(status_code\) < 400")
    c.present("失败原因截断到 MAX_ERROR_LEN", core_code, r"MAX_ERROR_LEN = 500")
    c.present("路径按列宽截断（别让一次记录失败）", core_code, r"path\[:MAX_PATH_LEN\]")
    c.present("写库异常全吞掉、只记日志（审计不许把成功请求变成 500）",
              record or core_code, r"except Exception as exc:[\s\S]{0,200}logger\.warning\([\s\S]{0,80}\)")
    c.present("写失败时 rollback", record or core_code, r"db\.rollback\(\)")
    c.present("丢进线程池（异步上下文里不碰同步 Session）",
              core_code, r"await run_in_threadpool\(\s*\n?\s*record_ai_operation,")
    c.present("取消原样抛出（CancelledError 不许被当成记录失败）",
              middleware, r"except asyncio\.CancelledError:\s*\n\s*raise")
    c.present("只有失败才攒响应体（成功的列表可能很大）",
              middleware, r'message\["type"\] == "http\.response\.body" and state\["status"\] >= 400')
    c.present("没走到响应时也留一行（如实说明）", middleware, r"（这次请求没有走到响应）")

    print("\n== 3. 只在 AI 请求上记 ==")
    c.present("自己读 X-SOrders-Origin 头", is_ai, r"ORIGIN_HEADER\.lower\(\)\.encode\(\)")
    c.present("走同一套归一（认不出的值一律 human，不会误记成 ai）",
              is_ai, r"normalize_origin\(raw\) == AI")
    c.absent("不读 get_origin()（中间件比 RequestId 靠外，那个变量还没设上）",
             is_ai, r"get_origin\(\)")
    origin = read(ORIGIN)
    c.present("动作头 X-SOrders-Ai-Action 与 origin 头在同一处定义", origin, r'ACTION_HEADER = "X-SOrders-Ai-Action"')
    c.present("动作名只做字符集白名单（不是抄一份动作清单）", origin, r"_ACTION_CHARS")
    c.present("动作名长度与列宽同宽（64）", origin, r"ACTION_MAX_LEN = 64")
    c.present("认不出的动作名落 None（不报错、也不让任意字符串进库）",
              origin, r"def normalize_action[\s\S]{0,600}?return None")

    print("\n== 4. 挂载顺序（必须在 RequestId 里面）==")
    mainpy = py_only(read(MAIN))
    i_ai = mainpy.find("add_middleware(AiOperationMiddleware)")
    i_rid = mainpy.find("add_middleware(RequestIdMiddleware)")
    c.ok("先挂 AiOperation、后挂 RequestId（越后挂的越靠外 ⇒ 流水在里层）",
         0 <= i_ai < i_rid, f"i_ai={i_ai} i_rid={i_rid}")
    c.present("注释里写清了为什么顺序不能换", read(MAIN), r"越后挂的越靠外")

    print("\n== 5. 端点 ==")
    api = read(API)
    ep = block(py_only(api), '@router.get("/operations"', "\n@router.")
    c.ok("切到了 /ai/operations 这个端点自己", bool(ep), "没找到装饰器")
    c.present("权限沿用 OPERATION_LOG_READ（不新开权限点）",
              ep, r"require_permission\(Permission\.OPERATION_LOG_READ\)")
    c.absent("没有为了这一页新造权限点", api + read(RBAC), r"AI_OPERATION[A-Z_]*\s*=|AI_AUDIT")
    c.present("按 id 倒序（最新的在最上面）", ep, r"order_by\(AiOperationLog\.id\.desc\(\)\)")
    c.present("skip 是真游标", ep, r"offset\(skip\)")
    c.present("多取一行判截断（只看到最近 N 条最容易骗人）", ep, r"\.limit\(limit \+ 1\)")
    c.present("截断通过响应头说出来", ep, r"finish_page\(rows, limit, response\)")
    c.present("三把筛子：只看失败的", ep, r"if ok is not None:")
    c.present("三把筛子：只看某一类动作", ep, r"if action is not None:")
    c.present("三把筛子：只看某个人", ep, r"if user_id is not None:")
    c.present("limit 上限 1000、下限 1（负数在生产 MySQL 会 500）",
              ep, r"limit: int = Query\(200, ge=1, le=1000\)")
    c.present("skip 不许为负", ep, r"skip: int = Query\(0, ge=0\)")
    c.present("user 用 joinedload（不许每行再打一次库）", ep, r"joinedload\(AiOperationLog\.user\)")
    c.present("谁的名字由端点补（姓名优先、没有用手机号）",
              api, r"item\.user_name = \(u\.full_name or u\.phone\) if u is not None else None")
    c.present("出参 schema 与模型分开两份", read(SCHEMA), r"class AiOperationLogOut")
    c.present("后端自身有测试（含中间件顺序那条）",
              read(BTEST), r"request_id")

    print("\n== 6. Android 发出端 ==")
    apiclient = code_only(read(APICLIENT))
    c.present("只有 ClientOrigin 说是 AI 时才加头", apiclient,
              r"val origin = ClientOrigin\.current\(\) \?: return delegate\.newCall\(request\)")
    c.present("带上 origin 头", apiclient, r"header\(ClientOrigin\.HEADER, origin\)")
    c.present("连动作名一起带（管理端要看得懂是哪一次动作）", apiclient,
              r"ClientOrigin\.currentAction\(\)\?\.let \{ builder\.header\(ClientOrigin\.ACTION_HEADER, it\) \}")
    write_svc = code_only(read(WRITESVC))
    n_asai = len(re.findall(r"ClientOrigin\.asAi\(", write_svc))
    c.ok(f"ClientOrigin.asAi( 只有 1 处（实际 {n_asai}）：预览不写库、套上只会多记没发生的事",
         n_asai == 1, str(n_asai))
    c.present("那一处就是确认执行（commit）那一步", write_svc,
              r'ClientOrigin\.asAi\(p\.actionId\) \{ handler\.commit\(p\.payload, "ai-" \+ token\) \}')

    print("\n== 7. Android 读端 ==")
    dtos = read(DTOS)
    dto = block(dtos, "@Serializable\ndata class AiOperationDto", "\n@Serializable")
    c.ok("有 AiOperationDto", bool(dto), "没找到 DTO")
    for field, wire in [
        ("statusCode", "status_code"),
        ("durationMs", "duration_ms"),
        ("requestId", "request_id"),
        ("userName", "user_name"),
        ("createdAt", "created_at"),
    ]:
        c.present(f"DTO 字段 {field} 对上后端的 {wire}", dto, rf'"{wire}"')
    apis = read(APIS)
    c.present("客户端接口挂在 ai/operations", apis, r'@GET\("ai/operations"\)')
    api_iface = block(apis, "interface AiOperationsApi", "\n}")
    for q in ["limit", "skip", "ok", "action", "user_id"]:
        c.present(f"接口带 {q} 查询参数", api_iface, rf'@Query\("{q}"\)')
    repo = read(REPO)
    c.present("Repository 用响应头判截断（pageRows）", repo,
              r"fun aiOperationsPage[\s\S]{0,900}?\.pageRows\(\)")
    c.present("「只看失败」走服务端（本地过滤会与分页打架）", repo,
              r"ok = if \(onlyFailed\) false else null")
    rows = read(ROWS)
    c.present("动作名认得出 → 中文名（动作 id）", rows, r'return if \(title == id\) id else title \+ "（" \+ id \+ "）"')
    c.present("认不出 → 原样写 id（⛔ 不许编一个中文名）", rows, r"val title = AiWrites\.titleOf\(id\)")
    c.present("没有动作名的如实说「未标动作（只读查询）」", rows, r"未标动作（只读查询）")
    c.present("失败原因缺失时如实说没有", rows, r"后端没有留下原因（看状态码）")
    c.present("谁：昵称 → 用户 #id → 未登录请求（不许留空）", rows, r"未登录请求")
    c.present("耗时用 Locale.US 格式化（别跟着机器区域变小数点）", rows,
              r'String\.format\(Locale\.US, "%\.1f s", ms / 1000\.0\)')
    vm = read(VM)
    c.present("翻页用 skip = 已加载条数", vm, r"skip = rows\.size")
    c.present("追加前按 id 去重（LazyColumn key 撞了会崩）", vm, r"rows = rows \+ page\.rows\.filter \{ it\.id !in seen \}")
    c.present("两个分支都带 onlyFailed（只看失败在翻页后仍然生效）", vm,
              r"limit = PAGE, onlyFailed = onlyFailed")
    c.present("切换筛选先清空再取", vm, r"fun applyOnlyFailed\(value: Boolean\) \{[\s\S]{0,300}?rows = emptyList\(\)")
    c.absent("⛔ 不叫 setOnlyFailed（与 var 的 setter 撞 JVM 签名，编译期就炸）",
             vm, r"fun setOnlyFailed\(")
    c.present("取消原样抛出", vm, r"catch \(e: CancellationException\) \{\s*\n\s*throw e")
    screen = read(SCREEN)
    c.present("只有后面还有时才提示截断", screen, r"if \(vm\.canLoadMore\) \{")
    c.present("列表 key 用 id", screen, r"items\(vm\.rows, key = \{ it\.id \}\)")
    c.present("有「加载更早的」按钮（真翻页，不是只说一句被截断）", screen, r"加载更早的")
    c.present("筛选由界面调 VM", screen, r"vm\.applyOnlyFailed\(i == 1\)")
    settings = read(SETTINGS)
    c.present("入口只在派单员（管理端）渲染", settings,
              r"if \(ai\.currentActor\?\.role == AiRole\.DISPATCHER\) \{")
    c.present("入口点了会打开这一页", settings, r"onOpenOperations\(\)")
    c.present("路由常量在", read(ROUTES), r'const val AI_OPERATIONS = "ai/operations"')
    nav = read(NAVGRAPH)
    c.present("路由真的挂了这一页", nav, r"composable\(Routes\.AI_OPERATIONS\) \{[\s\S]{0,200}?AiOperationsScreen\(")

    print("\n== 8. 单测与防静默空转 ==")
    test = read(ROWS_TEST)
    n_test = len(re.findall(r"@Test", test))
    c.ok(f"AiOperationRowsTest 有 >= 8 个用例（实际 {n_test}）", n_test >= 8, str(n_test))

    kts = sorted(AND.rglob("*.kt"))
    c.ok(f"扫到的 .kt 数量 {len(kts)} >= {MIN_KT}", len(kts) >= MIN_KT, "目录被搬走了？")
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED_FILES if not p.exists()]
    c.ok(f"{len(REQUIRED_FILES)} 个关键文件都在", not missing, "；".join(missing))

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
