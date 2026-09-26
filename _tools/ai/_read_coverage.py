"""读侧覆盖率：**每个"AI 能读到的表"都被交代过**（写侧早有 `_write_coverage.py`，读侧一直缺）。

## 为什么必须补这一条（用户 2026-09-19 的要求）

> 「只要是我们改过、比如说新加了一些功能，AI 它都要具备操纵这些功能的能力」

写侧有一条机器判据盯着（新写端点要么有 AI 动作、要么写一条"不做"的理由）。
**读侧没有** —— 而读侧的清单 `docs/ai/ai_toolmap.json` 是**手写的**：
新加一个 `GET` 端点，它不会自动进 AI 的读目录，也没有任何人会红。
于是"这个功能 AI 用不了"这件事**不会以任何形式暴露出来**，
直到用户问 AI、AI 如实回一句"我查不了"。

这正是本项目栽过 6 次的那个形状：**要检查哪些东西的清单是手写的**。

## 口径

- 端点真相：`backend/scripts/gen_endpoint_index.py::collect()`（机器算，不读那份可能过期的文档）
- 只算 **GET 且路径里没有 `{}`** 的端点 —— 带路径参数的是"按 id 查详情"，
  而 **AI 看不到任何内部编号**（本项目第一条硬规矩），暴露了它也只能瞎猜 id。
  这一条与 `_gen_ai_read_catalog.py` 的收口口径**必须一致**（两处不一致就会出现
  "目录里没有、覆盖率说已覆盖"）。
- 每条端点要么出现在 toolmap 的读动作里，要么在 [EXCLUDED] 里有一条写清理由的"不做"。

用法：
    python _tools/ai/_read_coverage.py            # 打一张账
    python _tools/ai/_read_coverage.py --check    # 有"没交代"的就非零退出
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

#: `module_key` = 逻辑模块名（拆出去的兄弟文件折回原模块，见 `_airepo.MODULE_ALIAS`）——
#: 与 `_gen_ai_toolmap` / `_gen_ai_read_catalog` 同一处口径，否则这里会把
#: `orders_query.list_orders` 当成"没交代的端点"（2026-09-24 阶段 4 搬迁实测踩到）。
from _airepo import module_key  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
from gen_endpoint_index import SKIP_DIRS, collect  # noqa: E402

TOOLMAP = ROOT / "docs" / "ai" / "ai_toolmap.json"
APP_ROOT = str(ROOT / "backend" / "app")


def all_endpoints() -> list[dict]:
    """走**端点索引生成器那一份** collect()，不另写一遍 AST 解析。

    ⚠️ 不要自己去解析 `@router.get`：那份生成器已经处理了三种授权写法（注解 / Depends /
    体内 raise 403）和别名递归，抄一遍只会抄漏 —— 而漏掉的授权会变成"放行"。
    """
    import os

    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(APP_ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                full = os.path.join(dirpath, fn)
                files.append(os.path.relpath(full, APP_ROOT).replace("\\", "/"))
    files.sort()
    rows, _ = collect(APP_ROOT, files)
    return rows

#: 明确"不给 AI 读"的端点 → 理由（每条都要说清为什么，否则下一轮又会有人来问一遍）。
#: ⚠️ 键是 **`模块.handler`**（与 toolmap 里的 action 名同一种写法），不是路径 —— 路径会改。
EXCLUDED: dict[str, str] = {
    # ---- app 级端点（不在 `app/api/v1/*.py` 里，toolmap 生成器扫不到）----
    "main.health": "服务健康检查：给运维探针用的，不是业务数据。",
    "main.app_version": "App 版本信息：客户端启动时自己会读，模型拿它没用。",
    # 业务指标（GET /metrics，整改阶段 8 ② 的可观测性小事）：**给监控抓的**，不是业务数据。
    # 它还要 `X-Metrics-Token` 才回话（fail-closed），模型手上没有这个口令；
    # 就算读到了，一堆 `sorders_*_today` 计数也回答不了用户任何问题 ——
    # 用户问"今天几单"时，模型该做的是读订单表（`orders.list` 那条读动作）。
    "main.metrics": "运维指标（Prometheus 抓取口，需要 METRICS_TOKEN）：不是业务数据，模型用不上。",
    # ---- 开销分类名册（2026-09-20）----
    # 模型要"按分类看开销"时**不需要先读名册**：`expenses` 那张读表里每一行都带 `category`
    # 与 `link_kind`（分类名与"卡片突出哪一项"），直接按行里的分类筛就行。
    # 名册本身回答的是"界面上左栏按什么顺序排、卡片突出哪一项"——那是**界面配置**，
    # 不是一件业务事实；模型读了也用不上（它不画界面）。
    #
    # ⚠️ **2026-09-23 起这两张名册改为"给模型读"**（原话在第 76 与 85 行那两条理由里）：
    #    上面那条推理（"界面上怎么排"用不上）在**AI 不能改名册**时成立；
    #    但这一轮按用户那条硬规矩「人能操作、AI 就要能操作」把三张名册的
    #    建/改名/排序/删都开给了模型（`expense_category.*` / `freight_category.*` /
    #    `order_template_category.*`），于是"读名册"从"用不上"变成了**前置条件**：
    #    - **重排要求整份顺序**（名册里每一格都要出现一次，后端少一个就整份 400），
    #      模型不知道完整名册就只能瞎猜，而它猜出来的名字对不上时，用户看到的是
    #      "AI 说它排不了"；
    #    - **改名/删除前要报出"这一类下挂着几笔开销/几条价目"**，那个数字就在名册的
    #      `expense_count` / `template_count` / `rule_count` 上（卡片上必须写，见
    #      `AiWriteBasicData` 里那三组 `targetXxxCategory()`）。
    #    所以这两条 EXCLUDED 撤掉，改成给模型读（仍**只有派单员**能读：端点授权没变）。
    "freight_templates.quote_freight": (
        "**匹配本身就是服务端算的**：派单时由 App 拿这一单 + 司机去问价，"
        "模型不需要自己调它 —— 它要做的是改价目（`freight_template.*` 那几个写动作），"
        "而不是在对话里替某一单报价。"
    ),
    # ---- 测试账号的默认模型服务（2026-09-21）----
    # ⛔ 这一条**不是"模型用不上"，而是"模型绝对不许读"**：它返回的是**明文 API key**
    #    （App 自己没配 key 时用来兜底的那把）。读进上下文就等于把钥匙写进聊天记录 ——
    #    而聊天记录会落盘、会被截图、会随上下文发给模型服务商。
    #    再加上它本身也没有业务含义：模型不该知道"自己的 key 是从哪来的"。
    "system.read_ai_default": (
        "**凭据**：返回的是 App 自己用的明文 API key（测试账号兜底那把）。"
        "读进上下文＝把钥匙写进聊天记录（还会发给模型服务商），所以模型既用不上也不许读。"
    ),
    # ---- 单位换算的只读试算（R4-04 的扩展路由，GET /api/v1/unit-conversion/preview）----
    # ⛔ 先说清它是什么：它是一个**量纲计算器**，用的换算率全是**公开定义值**
    #    （1 斤 = 500 克、1 里 = 500 米、1 石 = 10 斗），模型本来就知道；
    #    再给它一条"帮我算一次"的动作，只是把同一件事做两遍。
    #    真正需要模型读的是**用户自己配的**换算率（`1 车 = 8 方`）—— 那条读动作已经有了
    #    （GET /api/v1/unit-conversions，见 toolmap 的 unit_conversions 模块）。
    #    这条端点服务的是**界面**：下单页上试算一下。
    # ⚠️ 出口：哪天它变成"读用户数据"（例如以后支持用户自定义的量纲单位表），
    #    就该按上面 ① 给它加一条读动作，而不是继续留在这里 —— 别让这条变成化石。
    "api.preview": (
        "**量纲计算器**：换算率全是公开定义值（1 斤 = 500 克、1 里 = 500 米），模型本来就知道；"
        "真正要读的「用户自己配的换算率」已经有读动作（GET /unit-conversions）。"
        "这条端点服务的是下单页上的试算，不是让模型去查一件事。"
    ),
    # ---- 算价试算（R4-05 的扩展路由，GET /api/v1/pricing/quote）----
    # ⛔ 这一条与本文件上面那条 FREIGHT_TEMPLATES 的口径是**同一条**，理由更硬一层：
    #    它算出的是**钱的一个数**。让模型在对话里报一个价，用户会把它当成真的 ——
    #    而派单那一刻真正的价来自**配置好的规则**（规则快照里定格的那一条）。
    #    两个来源 = 两个数，正是本项目最贵的那条规矩「一笔钱只有一个数」要防的事。
    #    ⚠️ 模型在这条链上该做的是**改配置**（写动作：价目 / 计费规则），不是替某一单报价。
    # ⚠️ 出口：若将来它变成"读**已经算好的**结果"（例如读某张订单当前的应收），
    #    那是另一条读动作（读数，不是算数），该按上面 ① 加，而不是继续留在这里。
    "api.quote": (
        "**算出的是钱的一个数**：让模型在对话里报价，用户会当成真的，而派单时的价来自配置好的规则 ——"
        "两个来源就是两个数，正是「一笔钱只有一个数」要防的事。"
        "模型在这条链上该做的是改配置（价目 / 计费规则那几个写动作），不是替某一单报价。"
    ),
}

MIN_ENDPOINTS = 100
MIN_ACTIONS = 30


def read_actions() -> dict[str, dict]:
    """toolmap 里声明为只读的动作：`模块.handler` → 动作。

    ⚠️ 键必须**带模块**：`list_categories` 这种名字在 `products` 与 `product_categories`
    两个模块里都可能出现，只按动作名索引会把它们混成一个。
    写法与 `_gen_ai_read_catalog.py` 里的 `read_ids` 完全一致（那才是消费方）。
    """
    tm = json.loads(TOOLMAP.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for mod, m in tm["modules"].items():
        for a in m["actions"]:
            if a.get("risk") != "read":
                continue
            out[f"{mod}.{a['action']}"] = {**a, "module": mod}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="有「没交代」的端点就非零退出")
    args = ap.parse_args()

    eps = all_endpoints()
    if len(eps) < MIN_ENDPOINTS:
        print(f"❌ 只扫到 {len(eps)} 个端点（<{MIN_ENDPOINTS}）—— 判据在空转，停。")
        return 1

    gets = []
    for r in eps:
        if r["method"] != "GET" or "{" in (r["prefix"] + r["sub"]):
            continue
        gets.append({
            "method": "GET",
            "path": r["prefix"] + r["sub"],
            # 与 toolmap 的 action 名同一种写法（`模块.handler`），见 `_gen_ai_read_catalog`
            "key": f"{module_key(Path(r['file']).stem)}.{r['name']}",
            "auth": r.get("auth") or [],
        })
    actions = read_actions()
    if len(actions) < MIN_ACTIONS:
        print(f"❌ toolmap 里的读动作只有 {len(actions)} 个（<{MIN_ACTIONS}）—— 判据在空转，停。")
        return 1

    covered, unexplained, excluded = [], [], []
    for r in gets:
        key = r["key"]
        if key in actions:
            covered.append(r)
        elif key in EXCLUDED:
            excluded.append(r)
        else:
            unexplained.append(r)

    print(f"GET 端点（无路径参数）：{len(gets)} 个")
    print(f"  ✅ AI 有读动作：{len(covered)}")
    print(f"  ⛔ 写明了「不做」：{len(excluded)}")
    print(f"  ❓ 没交代：{len(unexplained)}")
    if unexplained:
        print("\n这些端点**既没有 AI 读动作、也没有说不做的理由**（新加的端点最容易落在这里）：")
        for r in unexplained:
            print(f"   · {r['method']} {r['path']}  ({r['key']})  {'/'.join(r['auth'])[:46]}")
        print(
            "\n修法（二选一）：\n"
            "  ① 给 AI 加一个读动作：往 `docs/ai/ai_toolmap.json` 对应模块里加一条 "
            "`{\"action\": \"<handler>\", \"risk\": \"read\", \"path\": \"/api/v1/...\"}`，\n"
            "     并在 `_tools/ai/_gen_ai_read_catalog.py` 的 `CN_DESC` 里写一句中文说明，"
            "然后重跑那个生成器；\n"
            "  ② 在这个文件的 `EXCLUDED` 里写一条**理由**（具体到为什么模型用不上）。"
        )

    # ---- 三条反向约束（否则那张理由表只是装饰）----
    fails: list[str] = []
    real = {r["key"] for r in gets}
    stale = sorted(k for k in EXCLUDED if k not in real)
    if stale:
        fails.append(
            "EXCLUDED 里的这些已不是「无路径参数的 GET 端点」（理由成了化石，"
            "下一个人会以为「这条处理过了」）：" + "、".join(stale)
        )
    both = sorted(set(EXCLUDED) & set(actions))
    if both:
        fails.append("这些端点既被算成「有 AI 读动作」又写了「不做」—— 两者不可能都对：" + "、".join(both))
    # 反空转：**匹配上的**读动作数量（toolmap 里 action 名与 handler 名对不上时这里会掉下来）
    if len(covered) < MIN_ACTIONS:
        fails.append(
            f"toolmap 的读动作只有 {len(covered)} 个能对上真实 GET 端点（<{MIN_ACTIONS}）——"
            "多半是 action 名与 handler 名对不上了，判据在空转"
        )
    if unexplained:
        fails.append(f"有 {len(unexplained)} 个 GET 端点没交代（见上面的清单）")

    if fails:
        print("\n❌ 读侧覆盖率不通过：")
        for f in fails:
            print("   - " + f)
        return 1 if args.check else 0
    print("\n✅ 每个「AI 读得到的表」都交代过了：要么有读动作，要么写明了不做。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
