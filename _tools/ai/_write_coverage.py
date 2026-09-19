"""算「AI 写能力覆盖率」：后端 74 个写端点里，哪些已经有 AI 动作、哪些还没有。

### 为什么要有它
"还差多少个接口「这个问题，靠回忆答不准，靠肉眼读 6 个 Kotlin 文件更不准。
链路是 3 跳的：`AiWriteAction` → 处理器/`CrudSpec` → `AppRepository` 方法 → `Apis.kt` 的
Retrofit 函数 → 后端端点。这里把这条链还原出来：

  1. 解析 `Apis.kt`：`@POST("orders/{id}/exception")` ↔ `suspend fun markException(...)`
  2. 解析 `AppRepository.kt`：`api.markException(...)` ↔ `suspend fun markException(...)`
  3. 在 `ai/` 包里搜第 2 步那些 repo 方法名的调用
  4. 与后端 `docs/ai/write-endpoints.json`（74 条，ast 抓的）对账

### ⚠️ 「还剩 14 个」不是一个结论，除非每个都说得出为什么（v3.20 加）
早先的输出只有一句「未覆盖 14"，于是这 14 个到底是」还没做「还是」决定不做「，
只有写这份脚本的人知道。**下一个人（或下一轮的我）会把它们当成待办**，
甚至为了凑数字去做一个不该做的动作（比如让模型上传图片——它给不出文件）。

所以现在每个未覆盖端点都必须在 [EXCLUDED] 里有一条**写下来的理由**；
没有理由的会被单独列成「⚠️ 未覆盖且没有理由」，并在退出码上体现。
这条判据本身也要能反向验证：把某条理由删掉，它必须变红（见 `_reverse_verify_coverage.py`）。

用法：
    python _tools/ai/_write_coverage.py              # 汇总 + 未覆盖清单
    python _tools/ai/_write_coverage.py --module orders
    python _tools/ai/_write_coverage.py --check       # 有「没有理由」的就非零退出（给红线用）
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
APIS = AND / "data/remote/api/Apis.kt"
REPO = AND / "data/repo/AppRepository.kt"
AI = AND / "ai"
ENDPOINTS = ROOT / "docs/ai/write-endpoints.json"

# ------------------------------------------------------------------ 不做的理由
#
# 键 = (METHOD, 归一化路径)。**这个表只许加，不许为了凑覆盖率删。**
# 每一类都对应一条已经定过的规矩，不是「这个懒得做」。
EXCLUDED: dict[tuple[str, str], str] = {
    # 凭据：AI 不碰登录/注册。与风险分级无关——它连「该不该做」都不成立。
    ("POST", "auth/login"): "登录/注册：AI 不该碰凭据（v3.7 定的永久排除）",
    ("POST", "auth/token"): "登录/注册：AI 不该碰凭据（v3.7 定的永久排除）",
    # 登出（2026-09-19 补：这条端点是被"清单自己算"那个修法**照出来**的 —— 它加进来之后
    # 一直没进那张签入的表，所以覆盖率看不见它）。理由与凭据同类：
    # 登出是**会话动作**，模型替用户退出登录只会让他莫名其妙地被踢回登录页。
    ("POST", "auth/logout"): "登录/注册：AI 不该碰凭据与会话（v3.7 定的永久排除）",
    # 用户明确说永久不做（目标④）。
    ("POST", "customers/merge"): "客户合并：用户明确说不需要、也没必要（目标④，永久排除）",
    # 上传类：模型给不出文件。让它「申请上传」只会产生一张永远填不满的卡。
    ("POST", "orders/{}/address-image"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    ("POST", "orders/{}/delivery-photos"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    ("POST", "products/{}/image"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    ("POST", "shipper/locations/image"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",
    # 坐标类（v3.41 新增）：与上传类同一类问题 —— 这个参数**模型无从得知**。
    # 经纬度是"人在现场用 GPS 测出来的事实"，模型编一个数就会把司机导航到别的地方，
    # 而且**看上去完全正常**（一串合法小数）。让 AI "申请补导航"只会得到一张
    # 编造坐标的卡 —— 比不做更糟。
    ("POST", "orders/{}/navigation"): "坐标类：经纬度是现场 GPS 测出来的事实，模型给不出、编一个会把司机带错（v3.41 永久排除）",
    ("POST", "places"): "坐标类：经纬度是现场 GPS 测出来的事实，模型给不出、编一个会把司机带错（v3.41 永久排除）",
    # 导出类：产物是一个下载文件，聊天里递不给用户（要做也是「读+出表格」，不是写动作）。
    ("POST", "ledger/export-jobs"): "导出类：产物是下载文件，聊天里递不给用户（另行按「出表格」能力做）",
    ("POST", "stats/export"): "导出类：产物是下载文件，聊天里递不给用户（另行按「出表格」能力做）",
    # 司机端：目标③明确「司机端暂不开放 AI（以后只做查订单价格）」。
    ("POST", "orders/{}/complete"): "司机端动作：目标③司机端不开放 AI",
    ("POST", "orders/{}/complete-with-upload"): "司机端动作：目标③司机端不开放 AI（且含上传）",
    ("POST", "orders/{}/driver-ack"): "司机端动作：目标③司机端不开放 AI",
    ("POST", "orders/{}/driver-note"): "司机端动作：目标③司机端不开放 AI",
    # 功能上已被另一个端点覆盖（不是缺口，是重复路径）。
    ("DELETE", "notifications/{}"): "与 POST /notifications/batch-delete 同功能：AI 走批量删除那条路",
    # 埋点类：这个端点不改任何业务状态，它是 App 在用户点选共享地点时**自动**调的
    # 使用计数（"大家都去过这儿"+1，第 2 次起还会顺手把地点收进他自己的「我的地点」）。
    # 模型没有"申请记一次使用"这种动作，也不该有：模型看不见那个共享地点列表
    #（它是全库共享、按距离/关键词搜出来的），硬造一个动作只会让它去点一个它看不见的东西；
    # 而"把常用地点收进我的地点"是**用户点选**的副产物，不是一件可以申请的事。
    ("POST", "places/{}/use"): (
        "埋点类：App 在用户点选共享地点时自动调的「使用计数」（不改任何业务状态）；"
        "模型没有「申请记一次使用」这种动作，也不该有——它看不见那个共享地点列表"
    ),
}

#: **AI 功能自己在用、但模型没法调**的写端点（第三个桶）。
#:
#: 为什么需要这一桶：`EXCLUDED` 的语义是"决定不做"，而 v3.32 的 AI 附件
#: （用户挂一份 Excel 让 AI 看）**做了**——只是入口不在模型手上：文件是**用户**
#: 在系统文件选择器里选的，App 上传解析后把表格正文随消息交给模型。
#: 模型侧根本没有"申请上传一个文件"这种动作可以存在，所以它既不是缺口、也不是"不做"。
#:
#: 这一桶必须配自己的反向约束（见下面的 direct_unused）：**声称"AI 在用"就必须真的在用**
#: ——ai/ 包里找不到对它的调用，这条声明就成了化石。
AI_DIRECT_USE: dict[tuple[str, str], str] = {
    ("POST", "files/parse-sheet"): (
        "AI 附件的入口：文件由用户在系统选择器里选，App 上传解析后把表格正文随消息交给模型"
        "（模型侧没有「申请上传」这个动作）"
    ),
}

# `@POST("orders/{id}/exception")` + 紧随其后的 `suspend fun markException(`
API_FN = re.compile(r'@(GET|POST|PATCH|DELETE|PUT)\("([^"]*)"\)[\s\S]{0,600}?fun\s+(\w+)\s*\(')
# AppRepository 里对 api 的调用：`api.orderApi.markException(...)` / `api.productApi.update(...)`
# ⚠️ 必须允许「api.子api.函数」两段：只写 `api\w*\.` 会贪婪吃掉 `api.orderApi`，抓出来的是子 api 名。
REPO_CALL = re.compile(r"\bapi(?:\.\w+)?\.(\w+)\s*\(")
# AppRepository 的方法（表达式体与块体都要认）：方法体里第一个 api 调用就是它对应的端点
REPO_METHOD = re.compile(
    r"(?:suspend\s+)?fun\s+(\w+)\s*\([^)]*\)[^\n{=]*[={]([\s\S]{0,900}?)(?=\n    (?:suspend\s+)?fun\s|\n\})",
    re.M,
)


def norm(path: str) -> str:
    """路径参数名两侧写法不同（后端 `{order_id}` / Retrofit `{orderId}`），统一成 `{}` 再比。"""
    return re.sub(r"\{[^}]*\}", "{}", path.strip("/"))


def api_paths() -> dict[tuple[str, str], str]:
    """(METHOD, 归一化路径) → Kotlin 函数名。"""
    out: dict[tuple[str, str], str] = {}
    for m in API_FN.finditer(APIS.read_text(encoding="utf-8")):
        out[(m.group(1), norm(m.group(2)))] = m.group(3)
    return out


def repo_to_api() -> dict[str, str]:
    """Api 函数名 → AppRepository 里的方法名（同一个端点的两种叫法）。"""
    src = REPO.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in REPO_METHOD.finditer(src):
        calls = REPO_CALL.findall(m.group(2))
        if calls:
            out.setdefault(calls[0], m.group(1))
    return out


def self_test_comment_blindness() -> None:
    """自检：**注释里的方法名不算覆盖**。

    为什么要有它（2026-09-19 审计）：覆盖率是"AI 写能力做完了没有"的唯一权威，而它的判据是
    "这个 repo 方法名在 ai/ 里出现过"。如果哪天有人把 `strip_comments` 去掉（或者换成
    不剥注释的写法），**在 KDoc 里写一句示例就能把某个写端点算成"已覆盖"** ——
    覆盖率虚高、不会红、下一个人会以为那个端点已经有 AI 动作。
    这条自检用一段合成源码当场比对：剥完注释后，注释里的 `markRead(` 必须**看不见**。
    """
    from _check_ai_guardrails import strip_comments  # 同目录脚本，模块级可导入

    sample = (
        "// 撤回走 repo.markRead(id)\n"
        "/* 也可以 repo.deleteLedgerEntry(x) */\n"
        "val n = 1\n"
    )
    names = set(re.findall(r"\b(\w+)\s*\(", strip_comments(sample)))
    leaked = names & {"markRead", "deleteLedgerEntry"}
    if leaked:
        raise SystemExit(
            f"❌ 覆盖率自检不通过：注释里的方法名被当成了真实调用（{sorted(leaked)}）——"
            "判据没剥注释，写一句 KDoc 示例就能把端点算成「已覆盖」。"
        )


def scan_called_names(src: str) -> set[str]:
    """**唯一的扫描入口**：剥掉注释之后，取源码里出现过的调用名。

    ⚠️ 自检与真实扫描都走这里（2026-09-19 审计）：如果自检自己调 `strip_comments`、
    而真实扫描走另一条路，那么"把剥注释删掉"这种破坏**自检照样绿** —— 我第一版就是这么写的，
    注入验证当场证明它抓不到。判据必须与被判据的代码**同一条路径**。
    """
    from _check_ai_guardrails import strip_comments  # 同目录脚本，模块级可导入

    return {m.group(1) for m in re.finditer(r"\b(\w+)\s*\(", strip_comments(src))}


def self_test_comment_blindness() -> None:
    """自检：**注释里的方法名不算覆盖**。

    为什么要有它：覆盖率是"AI 写能力做完了没有"的唯一权威，判据是"这个 repo 方法名在 ai/ 里
    出现过"。不剥注释时，**在 KDoc 里写一句示例**（"撤回走 `repo.markRead(id)`"）就能把对应写
    端点算成"已覆盖" —— 覆盖率虚高、不会红，下一个人会以为那个端点已经有 AI 动作了。
    """
    leaked = scan_called_names("// 撤回走 repo.markRead(id)\n/* repo.deleteLedgerEntry(x) */\nval n = 1\n")
    bad = leaked & {"markRead", "deleteLedgerEntry"}
    if bad:
        raise SystemExit(
            f"❌ 覆盖率自检不通过：注释里的方法名被当成真实调用了（{sorted(bad)}）——"
            "判据没剥注释，写一句 KDoc 示例就能把端点算成「已覆盖」。"
        )


def ai_mentioned_repos() -> set[str]:
    """ai/ 包里出现过哪些 repo 方法名（**只看真实代码，注释不算**，见自检的说明）。"""
    names: set[str] = set()
    for f in AI.glob("*.kt"):
        names |= scan_called_names(f.read_text(encoding="utf-8"))
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module")
    ap.add_argument("--check", action="store_true", help="有「未覆盖且没有理由」就非零退出")
    args = ap.parse_args()

    # ⛔ **端点清单自己算，不读那份签入的 JSON**（2026-09-19 修）。
    #
    # 原来这里读 `docs/ai/write-endpoints.json`，而那份文件是**手工重跑**
    # `_dump_write_endpoints.py` 才更新的 —— 没有任何检查盯着它新不新鲜。
    # 实测：它是 2026-09-18 21:57 写下的，之后新加的写端点（本轮 `place-categories` 五个）
    # **一个都没进这张表**，于是这条"AI 写能力覆盖率"红线报「0 个真缺口」——
    # **假绿**。这正是本仓库反复栽的那类坑（清单过期 → 结论变成"没问题"，
    # 而 `_dump_write_endpoints.py` 自己的注释里就写着这句话）。
    #
    # 现在直接调那个脚本的 `handlers()`（同一份解析，不抄第二遍），
    # 端点永远与源码同步；签入的 JSON 只当"给人看的快照"。
    from _dump_write_endpoints import handlers as dump_handlers  # noqa: E402

    eps = dump_handlers()
    apis = api_paths()
    repo = repo_to_api()
    self_test_comment_blindness()
    mentioned = ai_mentioned_repos()

    rows = []
    unmatched = []
    for e in eps:
        path = norm(e["path"].replace("/api/v1", ""))
        key = (e["method"], path)
        fn = apis.get(key, "")
        # 有的端点在 App 侧直接就没有封装（例如登录/导出），那就是「根本没打算给 AI"
        if not fn:
            unmatched.append((e["method"], path))
        repo_fn = repo.get(fn, "") if fn else ""
        # 覆盖判据（⚠️ 这里踩过假阳性）：
        #   · 强证据：**repo 包装名**在 ai/ 包里出现过（handler 只能通过 repo 去调端点）；
        #   · 弱证据：Api 函数名在 ai/ 里出现过**且名字足够独特**。
        # 为什么必须加「足够独特」：`DELETE /notifications/{id}` 的 Api 函数就叫 `delete`，
        # 而 `delete` 这个词在 ai/ 包里到处都是（`MutableList.delete`、`list.delete`…），
        # 于是它被误判成「已覆盖"——**一个什么都没实现的端点被算进了覆盖率**。
        # 宁可少算：漏算会让人多干一遍活，虚报会让人以为干完了。
        strong = bool(repo_fn) and repo_fn in mentioned
        weak = len(fn) >= 8 and fn in mentioned
        covered = strong or weak
        rows.append((path, e["method"], fn, repo_fn, covered, e, strong, key))

    mod = lambda p: p.get("file", "?")  # noqa: E731
    if args.module:
        rows = [r for r in rows if args.module in (r[5].get("file") or "")]

    todo = [r for r in rows if not r[4]]
    weak_only = [r for r in rows if r[4] and not r[6]]
    # 「AI 自己在用、模型没法调」的那些：既不进 todo，也不算"已覆盖的动作"。
    direct = [r for r in rows if r[7] in AI_DIRECT_USE]
    direct_ids = {id(r) for r in direct}
    todo = [r for r in todo if id(r) not in direct_ids]
    # 未覆盖的必须**每一条都说得出为什么**：有理由的 = 决定不做；没理由的 = 真缺口。
    reasoned = [r for r in todo if r[7] in EXCLUDED]
    unexplained = [r for r in todo if r[7] not in EXCLUDED]

    # ---- 三条"这张表真的在被使用"的反向约束（否则它只是装饰）----
    #
    # ① 表里的键必须都还是真端点：端点改了名/删了，理由就成了化石，
    #    而化石比没有更糟（下一个人会以为「这条已经处理过了」）。
    all_keys = {r[7] for r in rows}
    stale = sorted(k for k in EXCLUDED if k not in all_keys)
    stale_direct = sorted(k for k in AI_DIRECT_USE if k not in all_keys)
    # ② 写了「不做」的端点**不能同时被算成已覆盖**：两者不可能都对。
    #    这一条专治"覆盖判据被改坏"（什么都算覆盖）——那时 todo 恒为空，
    #    理由表就永远不会被查，整个检查会安静地变成空转。
    contradiction = sorted((r[1], r[0]) for r in rows if r[4] and r[7] in EXCLUDED)
    # ③ 「AI 在用」的说法必须真的成立：ai/ 包里找不到对它的调用 → 声明是假的。
    #    这一条同时挡住了"为了消掉一条缺口，随手把它塞进 AI_DIRECT_USE"。
    direct_unused = sorted((AI_DIRECT_USE[r[7]], r[0]) for r in direct if not r[4])

    print(f"写端点共 {len(rows)}，已覆盖 {len(rows) - len(todo)}，未覆盖 {len(todo)}"
          f"（其中 {len(reasoned)} 条有写下来的「不做」理由，{len(unexplained)} 条是真缺口）")
    print(f"（其中 {len(unmatched)} 条在 Android 侧没有 Retrofit 封装 → 本来就不给 AI；"
          f"{len(weak_only)} 条是弱证据判定的，值得抽查）\n")
    if reasoned:
        print("已记录「不做」的（不是待办）：")
        for path, method, fn, repo_fn, _, e, _, key in sorted(reasoned, key=lambda r: r[0]):
            print(f"  {method:6s} /{path:48s} {EXCLUDED[key]}")
        print()
    if unexplained:
        print("⚠️ 未覆盖且**没有理由**——要么去做，要么在 _write_coverage.py 的 EXCLUDED 里写清为什么不做：")
        for path, method, fn, repo_fn, _, e, _, _ in sorted(unexplained, key=lambda r: r[0]):
            body = (e.get("body") or "").split(".")[-1]
            print(f"  {method:6s} /{path:48s} {mod(e):22s} body={body}")
        print()
    if stale:
        print("⚠️ 理由表里有**对不上任何端点**的条目（端点改名/删了？理由成了化石）：")
        for method, path in stale:
            print(f"  {method:6s} /{path:48s} {EXCLUDED[(method, path)]}")
        print()
    if contradiction:
        print("⚠️ 写了「不做」的端点**同时被算成已覆盖**（两者不可能都对：要么删理由，要么覆盖是假的）：")
        for method, path in contradiction:
            print(f"  {method:6s} /{path:48s} {EXCLUDED[(method, path)]}")
        print()
    if direct:
        print("AI 功能自己在用、但模型没法调的（不是缺口、也不是「不做」）：")
        for path, method, fn, repo_fn, _, _e, _, _key in sorted(direct, key=lambda r: r[0]):
            print(f"  {method:6s} /{path:48s} {AI_DIRECT_USE[(method, path)]}")
        print()
    if stale_direct:
        print("⚠️ 「AI 在用」表里有**对不上任何端点**的条目（端点改名/删了？）：")
        for method, path in stale_direct:
            print(f"  {method:6s} /{path:48s}")
        print()
    if direct_unused:
        print("⚠️ 声称「AI 功能自己在用」但 ai/ 包里找不到调用（这句话不成立）：")
        for why, path in direct_unused:
            print(f"  /{path:48s} {why}")
        print()

    if args.check and (unexplained or stale or contradiction or stale_direct or direct_unused):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
