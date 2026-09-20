"""回答一个问题：**AI 到底覆盖了 App 的哪些功能，还差哪些**（按功能模块算，不是按端点算）。

### 为什么不能只看端点
`_write_coverage.py` 算的是"74 个写端点里 AI 能调几个"，那是**数据面**。
但用户问的是「我能不能用嘴把这件事办成」——同一件事在 App 里可能是：
  ① 一张能被读的表（AI 读得到）、② 一个写端点（AI 改得动）、
  ③ 一个**不是端点**的客户端动作（导出下载、拍照上传、点地图导航、打印、扫码）。
只数端点会把第 ③ 类悄悄算成"已覆盖"，而它恰恰是 AI 永远够不着的部分。

### 口径
- App 模块清单：**从 `Modules.kt` 解析**（自己算，不手写清单）。
- AI 能力：读能力来自 `docs/ai/ai_read_catalog.json`（36 条，带 module_cn），
  写能力来自 `AiWrite.kt` 的 `group`（8 个域，数量自己数）。
- 映射表 [MAP] 是**判断题**（哪个模块归哪个能力域），不是清单——所以两头都校验：
  模块清单变了没跟着改 → 报错；AI 能力没被任何模块认领 → 报错。

用法：
    python _tools/ai/_app_feature_coverage.py           # 打一张覆盖率账
    python _tools/ai/_app_feature_coverage.py --check    # 只校验映射自洽（不打印账）
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
MODULES_KT = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Modules.kt"
AI_DIR = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
READ_CATALOG = ROOT / "docs/ai/ai_read_catalog.json"
WRITE_ENDPOINTS = ROOT / "docs/ai/write-endpoints.json"

# App 模块 → (读能力 module_cn, 写能力 group, 说明)
# ⚠️ 这张表是**判断题**：`None` 表示"这个模块本来就没有对应的读写能力"，
#    而"我还没接"必须写成 `?` 并让 --check 报红——两者不能混。
MAP: dict[str, tuple[list[str] | str, list[str] | str, str]] = {
    # ⛔ 「派单作业」分组连同它的三个子入口（待派单池 / 全部订单 / 订单模板）在 2026-09-19 被拆掉：
    #    用户要求「将工作台里的派单那个图标给去掉」，并把「运费模板 / 计费规则」提成两个独立图标。
    #    去掉是安全的 —— 待派单池就是底部导航第一个 Tab，"全部订单"与「订单管理」图标
    #    指向同一条路由（同一页两个入口），所以没有任何能力因此失去入口。
    #    「订单/派单」读能力与「订单」写域仍然被下面的「订单管理」认领。
    # 运费模板的增删改挂在 G_ORDER 里（`AiWriteBasicData.kt` 的 FREIGHT_TEMPLATE_* 三条），
    # 不是"只能读"——一开始我按"模板只是参考数据"想当然写成了缺口，工具当场把它顶出来。
    "运费模板": (["订单/运费模板"], ["订单"], "运费模板增删改（动作在订单域里）"),
    # 计费规则（v3.36）：建规则/改规则/挂给司机都在「账号与收费规则」域里；
    # 读能力是 `driver_billing_rules.list_rules`（module_cn = 司机计费规则）。
    "计费规则": (["司机计费规则"], ["账号与收费规则"], "计费规则模板增删改 + 给司机挂载（AI 也能配）"),
    "代理下单": (["地址与联系人", "商品管理", "批发商定价", "订单/派单"], ["订单"], "下单全链路"),
    "地址与联系人": (["地址与联系人", "共享地点库", "地点分类"], ["地址与联系人", "地点分组", "共享地点"], "线路/地点/联系人增删改 + 回收站恢复 + 地点分组名册（按人分区，AI 也能建/排/把地点归到某一组）+ 共享库的管理（改/撤销/删除/设为共享，只有派单员）"),
    "订单管理": (["订单/派单", "订单商品行"], ["订单"], "含标记异常/解除异常/回收站"),
    "账户管理": (["司机/货主/批发商/账号", "统计口径"], ["账号与收费规则"], "建号/改资料/停用/换角色/删除"),
    # v3.44：司机管理多了「给他配哪辆车」这一条线（`vehicle.set_driver`），
    # 车辆名册也从"只读"变成可写（改车牌/车型/停用）——所以读能力里补了「车辆管理」之外的写域。
    "司机管理": (["司机/货主/批发商/账号", "车辆管理"], ["账号与收费规则"], "司机=一种账号；配车/换车/解绑在这屏"),
    "货主管理": (["司机/货主/批发商/账号", "统计口径"], ["账号与收费规则"], "货主/批发商都是账号"),
    "批发商管理": (["批发商定价", "司机/货主/批发商/账号"], ["批发商定价"], "专属价 + 批量调价"),
    # v3.43：商品分组名册是**商品管理页**里的一个入口（`ProductCategoriesScreen`），
    # 读能力「商品分类」与写能力「商品分类」都属于它——上一轮漏了这三处认领，
    # `--check` 一直红着（"能力白做了：用户从模块看找不到它"）。
    "商品管理": (["商品管理", "商品分类"], ["商品", "商品分类"], "含上下架/删商品/回收站恢复/分类名册与排序"),
    "库存管理": (["库存管理"], ["库存"], "调整库存（撤回=反向再记一条）"),
    # 2026-09-20：账本那 8 件事从账本页顶部搬到**工作台第二张卡片**
    # （`Modules.dispatcherLedgerEntries`），原来那一格「账本管理」因此拆成下面 8 条。
    # 拆开之后每一格各自认领自己那部分能力：4 类账里**只有订单账能写**
    # （它带着「记一笔 / 删流水」），另外三类是只读的看账视角；
    # 4 个工具各自对应它们自己的页面（与账本页无关，那几页本来就有入口）。
    "订单账": (["账本", "现金流水"], ["账目"], "记一笔/删流水（唯一能写的账本档位）"),
    "司机账": (["司机运费结算", "司机账单"], "None", "**只读**：按司机看账，写动作在「司机结算」那一格"),
    "货主账": (["账本", "客户"], "None", "**只读**：按货主看账"),
    "批发商账": (["账本", "客户"], "None", "**只读**：按批发商看账"),
    "客户收款": (["客户", "账本"], ["账目"], "收款单（逐单核销 / 滚动收款）"),
    "司机结算": (["司机结算单", "司机账单"], ["账目", "账号与收费规则"], "生成账单/确认/付款/作废"),
    "开销管理": (["费用"], ["账目"], "支出/开销增删改"),
    "车辆台账": (["车辆管理"], "None", "台账只读（改车牌/车型在「司机管理」的车辆域里）"),
    "司机运费结算": (["司机运费结算", "司机结算单", "司机账单"], ["账目", "账号与收费规则"], "生成账单/确认/付款/作废"),
    "挂账单位": (["挂账单位"], ["账目"], "挂账单位增删改"),
    "报表中心": (["报表中心", "统计口径", "操作日志"], "None", "**只读**：报表是分析视角，不该有写动作"),
    "消息中心": (["消息通知"], ["消息"], "发消息/改消息/删消息/标已读"),
    "我的订单": (["订单/派单"], ["订单"], "货主视角：下单 + 撤单 + 删自己的单"),
    "下单": (["地址与联系人", "商品管理", "批发商定价"], ["订单"], "货主下单"),
    "我的账本": (["账本"], "None", "**只读**：货主对账本只有只读权限（后端 403）"),
    "我的任务": (["订单/派单"], "None", "司机端：**目标③明确不开放 AI**，端口一个入口都没有"),
    "AI 助手": ([], [], "助手本身（不是业务模块）"),
}

# 明明"只有一边"或"两边都没有"却是**故意**的：不计入缺口
EXEMPT = {
    "我的任务": "司机端目标③：不开放 AI，端口一个入口都没有",
    "我的账本": "货主对账本只有只读权限（后端 403），不该有写动作",
    "报表中心": "报表是分析视角，只读；写动作会绕过业务规则",
    "AI 助手": "助手自己",
    # 2026-09-20 工作台第二张卡片里那三格看账视角 + 车辆台账：它们本来就只是"看"，
    # 真正的写动作各有归属（司机账→司机结算、车辆台账→司机管理里的车辆域）。
    "司机账": "只读的看账视角（按司机聚合），写动作在「司机结算」里",
    "货主账": "只读的看账视角（按货主聚合）",
    "批发商账": "只读的看账视角（按批发商聚合）",
    "车辆台账": "只读的台账；改车牌/车型/停用是「司机管理」那一屏的车辆域",
}


def app_modules() -> list[str]:
    """App 的功能模块清单：从 Modules.kt 解析（自己算，不手写）。"""
    s = MODULES_KT.read_text(encoding="utf-8")
    out: list[str] = []
    for m in re.finditer(r'ModuleEntry\(\s*(?:"([^"]+)"|label = "([^"]+)")', s):
        name = m.group(1) or m.group(2)
        if name not in out:
            out.append(name)
    return out


def read_capabilities() -> dict[str, list[str]]:
    """读能力按 module_cn 归类。"""
    d = json.loads(READ_CATALOG.read_text(encoding="utf-8"))
    by: dict[str, list[str]] = collections.defaultdict(list)
    for a in d["actions"]:
        by[a["module_cn"]].append(a["action"])
    return dict(by)


def write_capabilities() -> dict[str, int]:
    """写能力按 group 归类（中文域 → 动作数）。

    ⚠️ 必须扫**整个 ai/AiWrite*.kt**：域常量声明在 `AiWrite.kt`，
    而声明式 CRUD 的 `group = AiWrites.G_*` 散在 `AiWriteBasicData.kt` /
    `AiWriteMasterData.kt` 里——只读一个文件会把地址/商品/库存/账号/定价
    五个域算成"0 个写动作"（第一版就是这么错的，账面上少了 29 个动作）。
    """
    names: dict[str, str] = {}
    used: list[str] = []
    for p in AI_DIR.glob("AiWrite*.kt"):
        s = p.read_text(encoding="utf-8")
        names.update({m.group(1): m.group(2) for m in re.finditer(r'const val (G_\w+) = "([^"]+)"', s)})
        used += re.findall(r"group\s*=\s*(?:AiWrites\.)?(G_\w+)", s)
    if len(names) < 8:
        raise SystemExit(f"❌ 只认出 {len(names)} 个能力域（应有 8 个）——域常量被搬走了？")
    return dict(collections.Counter(names.get(g, g) for g in used))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验映射自洽")
    args = ap.parse_args()

    modules = app_modules()
    reads = read_capabilities()
    writes = write_capabilities()

    problems: list[str] = []
    # ① 模块清单动过但映射没跟着改 → 必须报出来，否则这张账会安静地少算
    for m in modules:
        if m not in MAP:
            problems.append(f"Modules.kt 里有「{m}」，但映射表没有它（新模块？）")
    for m in MAP:
        if m not in modules:
            problems.append(f"映射表里有「{m}」，但 Modules.kt 里已经没有它了（化石）")
    # ② AI 能力没被任何模块认领 → 能力白做了（用户从模块看找不到它）
    claimed_read = {x for r, _, _ in MAP.values() if isinstance(r, list) for x in r}
    claimed_write = {x for _, w, _ in MAP.values() if isinstance(w, list) for x in w}
    for cn in reads:
        if cn not in claimed_read:
            problems.append(f"读能力「{cn}」没有被任何模块认领")
    for g in writes:
        if g not in claimed_write:
            problems.append(f"写能力「{g}」没有被任何模块认领")
    # ③ 写了 "?" 的地方 = 我自己标了"还没接" → 报红提醒（不算自洽）
    todo = [m for m, (r, w, _) in MAP.items() if r == "?" or w == "?"]
    if todo:
        problems.append(f"标着「还没接」的模块：{'、'.join(todo)}")

    if problems:
        print("❌ 映射不自洽：")
        for p in problems:
            print("   - " + p)
        return 1

    if args.check:
        print(f"✅ 映射自洽：App 模块 {len(modules)} 个，读能力 {len(reads)} 组，写能力 {len(writes)} 个域")
        return 0

    we = json.loads(WRITE_ENDPOINTS.read_text(encoding="utf-8"))
    print(f"App 功能模块 {len(modules)} 个 | AI 读能力 {sum(len(v) for v in reads.values())} 条"
          f"（{len(reads)} 组）| AI 写能力 {sum(writes.values())} 个动作（{len(writes)} 个域）"
          f" | 后端写端点 {len(we)} 个\n")
    print(f"{'模块':<14}{'读':<6}{'写':<6}说明")
    print("-" * 96)
    full = half = none = 0
    gap: list[str] = []
    for m in modules:
        r, w, note = MAP[m]
        rc = len(r) if isinstance(r, list) else 0
        wc = sum(writes.get(x, 0) for x in w) if isinstance(w, list) else 0
        if rc and wc:
            full += 1
        elif rc or wc:
            half += 1
            if m not in EXEMPT:
                gap.append(f"{m}（只覆盖了{'读' if rc else '写'}）")
        else:
            none += 1
            if m not in EXEMPT:
                gap.append(m)
        print(f"{m:<14}{rc:<6}{wc:<6}{note}")
    print("-" * 96)
    print(f"读写都有 {full} 个 / 只有一边 {half} 个 / 都没有 {none} 个"
          f"（其中豁免 {len(EXEMPT)} 个：{'、'.join(EXEMPT)}）")
    print(f"\n真缺口：{('、'.join(gap)) if gap else '0 个'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
