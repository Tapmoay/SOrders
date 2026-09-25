"""红线：**写业务数据的端点必须留下审计日志**（R14-1，2026-09-19 真机抓到）。

## 由来
真机上用 AI 建了一个挂账单位：库里多了一行 `arrears_units id=49`，而**审计页上什么都没有**
—— `arrears.py` 四个写端点、一次 `write_log` 都没调；`freight_templates.py` 同样
（4 个写端点、0 条日志）。这两块都是钱相关的主数据：
挂账单位决定"钱挂在谁名下"（改名后历史欠款按名字快照分组，谁也说不清是谁改的），
运费模板是派单填运费的参考价（改一个数字影响所有人报价）。
更根本的是：AI 写操作的设计承诺就是"**与人工操作同形、事后可回查**"，
而 `operation_logs` 是审计页唯一的数据源——不写日志＝那个动作在系统里等于没发生过。

## 判据（清单自己算，不手写）
1. 扫 `backend/app/api/v1/*.py`，凡是声明了写端点（`@router.post|patch|put|delete`）的模块，
   **要么**模块里有 `write_log(`，**要么**在下面的 [REASONS] 里有一条写清理由的豁免；
2. 豁免表里的键必须仍是"真模块且真有写端点"（防化石：模块被删/改名后还挂在表上）；
3. 数量判据：模块数 ≥ 15、有条数的模块 ≥ 10（清单过期/解析失效时先喊，而不是安静地少查一半）。
4. ⭐ **"写了日志"不等于"这次提交留了痕"**（2026-09-23 补，来自全项目复核）：
   `backend/app/**/*.py` 里，**凡是自己写了 `write_log(` 的函数**，其中每一处 `db.commit()`
   之前都必须出现过 `write_log(`（按"上一处 commit 之后、这一处 commit 之前"这个区间找，
   所以 `if/else` 两条分支各自提交能分别判断）。
   - 为什么模块级判据不够：`price_rules.py::create_price_rule` 的**复活分支**
     （给一个软删过的货主重新设价：同时把行从回收站复活 **且** 改了价）原来是
     `改完 → db.commit() → return`，**一条日志都没有** —— 而模块里有 4 处 `write_log(`，
     模块级判据全绿。真实后果：钱变了、审计页上查不到。
   - 早期版本的写法（"commit 之后还有没有 log"）有 6 处假阳性：被 docstring 里那句
     "调用方负责 `db.commit()`" 骗了。所以这里**先剥注释与文档字符串**再找。
   - 确实不需要留痕的提交点写在 [TX_EXEMPT] 里，逐条写清理由；上限 2 条（多了说明闸门在放水）。

用法：python _tools/qa/_check_audit_coverage.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "backend/app/api/v1"

#: 不写业务审计日志的模块 → **理由**。每条都要说清"为什么这里不记"，不能写"没必要"。
REASONS: dict[str, str] = {
    # 2026-09-24 阶段 4：退货端点单独成模块（api/v1/orders_return.py）。它的审计留痕写在
    # **唯一执行入口** services/order_return.py 里（端点只是转调它，不在 API 层重复记一遍）——
    # 搬迁前它混在 orders.py 里，那个文件里别的端点有 write_log，所以整块豁免看不出来。
    "orders_return.py": "审计留痕在 services/order_return.py（唯一执行入口）里写，API 层不重复记",
    # 2026-09-25 第二轮 R2-05（方向指南 §八「报表是事实消费者，不是生产者」）：
    # 异常解决那个**写**端点原来住在报表模块里，实现搬进订单域命令层后审计行也在那里写 ——
    # 所以下面两条是「写逻辑不在本模块」型豁免，不是「忘了记」。
    "exception_resolution.py": "写逻辑与审计留痕都在订单域命令层（app/commands/order.py::resolve_exception）",
    "stats.py": "只剩读端点与 POST /export（导出 xlsx 流，不落库、不改任何业务数据）",
    "auth.py": "登录/登出/换 token 是**会话**不是业务数据；失败尝试由 login_guard 限流记录，"
               "写进审计会把真正要回查的钱/单改动淹掉",
    "files.py": "只解析上传的表格（不落库、不改任何业务数据）",
    # AI 调用计数上报（2026-09-25 新增，报告 §15 ② 的 AI_calls）。三条理由：
    # ① 它写的不是业务事实，是一个**计数**（`ai_call_daily.calls += N`）；
    # ② 逐条记进 operation_logs 会把「谁改了什么」那张权威记录淹掉 ——
    #    用户每问一句 AI 就多一行，而审计页的价值恰恰在于它只有操作；
    # ③ 它本来就是**客户端报上来的**（模型跑在 App 里，后端看不到调用本身），
    #    记成「操作」等于把一句客户端声明写进审计。
    # ⛔ 与它相对的 `AI_write_confirmed` 反过来：那个是**后端从审计行数出来的**
    #    （`operation_logs.origin = ai`），所以「AI 真的写了什么」仍然逐行可回查。
    "ai_telemetry.py": "收的是客户端上报的**计数**（不是业务事实）；逐条记日志会把审计页淹掉，"
                       "而「AI 真的写了什么」由 operation_logs.origin=ai 那条路留痕",
    # ⛔ `notifications.py` 原来挂在这里，理由是"已读/删除是**消息状态**不是业务数据；
    #    逐条记日志会把审计页淹掉（一条群发就是几十行）"。**2026-09-23 全项目复核 A8
    #    让这条豁免过期了**：它确实不该逐条记"我自己标了已读"，但它同时允许
    #    **派单员删/改任何账号的消息** —— 一次
    #    `POST /notifications/batch-delete {recipient_id: X, all: true}` 会永久清空 X 的
    #    全部站内信，而那时**一条日志都不写**。现在按"动自己的不记、动**别人的**必须记"
    #    落地（动作码 `NOTIFICATION_MODERATE`），模块里因此有了 `write_log(`；
    #    按下面 ②b 那条判据，挂着它就是一条**假豁免**。
    #    注意：产品口径"派单员消息中心是全局视图"没变，这一轮只补留痕、没有收权限。
    # ⚠️ 这条**不是"不记日志"**，是"日志不写在这一层"（2026-09-21 退货申请）：
    #    四个写端点的日志都由 `services/order_return_request.py` 在**同一个事务里**写
    #    （`ORDER_RETURN_REQUEST` 提交 / `_REJECT` 驳回 / `_WITHDRAW` 撤回；
    #     办理那条走 `services/order_return.py::return_order` 的 `ORDER_RETURN`）——
    #    审计必须与数据变更同生共死，写在服务层才拿得到同一个 `db`。
    #    在端点里再补一次 `write_log` 就是**双重记账**（同一件事两行日志）。
    "return_requests.py": "日志在服务层写（`services/order_return_request.py` 三条动作码 + "
                          "办理走 `order_return.return_order` 的 `ORDER_RETURN`），"
                          "与数据变更同一个事务；端点层再写一次就是双重记账",
    # ⛔ `shipper.py` 原来挂在这里，理由是"货主自己的地址/联系人/地点是用户私有主数据，
    #    量极大、且不影响钱与订单归属"。**2026-09-19 这条豁免过期了**：共享地点库的
    #    「设为共享地址」端点（`POST /shipper/locations/{id}/share`）会把一条**私有**地点
    #    变成**所有人可见**的记录，那件事必须留痕（`PLACE_PUBLISH`），模块里因此有了
    #    `write_log(`。按下面 ②b 那条判据（豁免表里的模块代码里不许出现 `write_log(`），
    #    挂着它就是一条**假豁免**——读表的人会以为这个模块没留痕，于是不再去看它。
    #    （私有地址/联系人/地点那几条**确实**还是不记日志，理由与上面那句一样成立；
    #      但"模块级"的豁免做不到只说一半，所以它从这里拿掉了。）
    # ⛔ `stats.py` 原来挂在这里，理由是"报表只是读、它那两条 POST 是导出"——
    #    2026-09-19 审计第十四轮发现这条**已经过期**：`stats.py::resolve_exception_order`
    #    （异常单处理）会写 `write_log`，也就是说"它不写日志"这句话不再成立。
    #    假豁免比没豁免更糟：看表的人会以为这个模块没留痕，于是不再去看它。
    #    现在由下面 ②b 那条判据盯着（豁免表里的模块代码里不许出现 `write_log(`）。
    "usage.py": "重置的是**派生统计**（「常用度」＝列表排序的依据），不是业务数据："
                "订单/账目/主数据一条都不动，清掉只是让排序回到「先创建的在前」；"
                "与 notifications.py 那条同类（改的是状态，不是业务事实）",
}

WRITE_ROUTE = re.compile(r"@router\.(?:post|patch|put|delete)\(")

#: **判据 ④** 用到的表：「提交了、但同一个函数里没有任何 `write_log`」的文件 → 理由。
#: ⚠️ 空表是**正常状态**（现在的代码一处都没有）。往里加一条必须回答：
#: "这次提交为什么不需要在审计页上留痕？" —— 答不上来就别加，去把日志补上。
TX_EXEMPT: dict[str, str] = {}
MAX_TX_EXEMPT = 2
MIN_LOGGING_FUNCS = 20
MIN_COMMITS_IN_LOGGING_FUNCS = 30

FUNC_DEF = re.compile(r"^(?:async )?def (\w+)\s*\(")
DB_COMMIT = re.compile(r"\bdb\.commit\(\)")
WRITE_LOG = re.compile(r"\bwrite_log\(")


def _strip_lines(lines: list[str]) -> list[str]:
    """逐行剥掉注释与文档字符串（**保留行数**，否则报出来的行号会漂）。

    ⚠️ 不剥就等着收假阳性：第一版判据把 `order_return.py` 等 6 处**文档字符串**里那句
    "（调用方负责 `db.commit()`）" 当成了真提交 —— 6/8 的命中都是这么来的。
    """
    out: list[str] = []
    in_doc: str | None = None
    for ln in lines:
        if in_doc is not None:
            if in_doc in ln:
                in_doc = None
            out.append("")
            continue
        s = ln.strip()
        if s.startswith('"""') or s.startswith("'''"):
            q = s[:3]
            if s.count(q) < 2:
                in_doc = q
            out.append("")
            continue
        out.append(re.sub(r"#.*$", "", ln))
    return out


def commits_without_log() -> tuple[list[tuple[str, str, int]], int, int]:
    """扫 `backend/app/**/*.py`：**自己写了 `write_log(` 的函数**里，哪些 `db.commit()` 之前没有任何日志。

    只看"自己写了日志的函数"：不写日志的模块本来就整块豁免（见 REASONS），
    把它们一起算进来只会淹掉真信号（实测：不过滤是 100+ 条噪音，过滤后是 1 条真信号）。
    返回 (命中列表, 扫过的写日志函数数, 这些函数里的 commit 数)。
    """
    hits: list[tuple[str, str, int]] = []
    funcs = commits = 0
    for f in sorted((ROOT / "backend/app").rglob("*.py")):
        keep = _strip_lines(f.read_text(encoding="utf-8").splitlines())
        rel = str(f.relative_to(ROOT))

        def scan(name: str, seg: list[tuple[int, str]]) -> None:
            nonlocal funcs, commits
            if not any(WRITE_LOG.search(x) for _i, x in seg):
                return
            funcs += 1
            prev = -1
            for i, ln in seg:
                if DB_COMMIT.search(ln):
                    commits += 1
                    if not any(WRITE_LOG.search(x) for j, x in seg if prev < j < i):
                        hits.append((rel, name, i + 1))
                    prev = i

        name: str | None = None
        seg: list[tuple[int, str]] = []
        for i, ln in enumerate(keep):
            m = FUNC_DEF.match(ln)
            if m:
                if name is not None:
                    scan(name, seg)
                name, seg = m.group(1), []
                continue
            if name is not None:
                seg.append((i, ln))
        if name is not None:
            scan(name, seg)
    return hits, funcs, commits



def main() -> int:
    fails: list[str] = []
    modules: dict[str, tuple[int, int]] = {}
    for f in sorted(API.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        writes = len(WRITE_ROUTE.findall(src))
        if writes:
            modules[f.name] = (writes, len(re.findall(r"\bwrite_log\(", src)))

    ok_modules = {n: v for n, v in modules.items() if v[1] > 0}
    unlogged = {n: v for n, v in modules.items() if v[1] == 0}
    print(f"写端点模块 {len(modules)} 个：有审计日志 {len(ok_modules)} 个，没日志 {len(unlogged)} 个")
    for n, (w, l) in sorted(unlogged.items()):
        print(f"   · {n:26} 写端点 {w:>2} 日志 {l}  {'（豁免：' + REASONS[n][:24] + '…）' if n in REASONS else '❌ 没有理由'}")

    # ① 没日志又没理由 → 红
    unexplained = [n for n in unlogged if n not in REASONS]
    if unexplained:
        fails.append("这些模块有写端点却既不写审计日志、也没有书面理由：" + "、".join(unexplained))

    # ② 豁免表不许变化石
    fossils = [n for n in REASONS if n not in modules]
    if fossils:
        fails.append("豁免表里的模块已经不存在/没有写端点了（化石条目）：" + "、".join(fossils))

    # ②b 豁免表不许**越过判据本身**（2026-09-19 审计第十四轮补）
    #     这条是反向验证逼出来的：原来的注入是"把一个记账模块也塞进豁免表"，
    #     而 `arrears.py` 现在**已经写了日志** → 塞进去等于什么都没做，注入自然全绿。
    #     也就是说：豁免表原来只需要"模块有写端点"就能生效，**跟它到底写没写日志无关** ——
    #     一个"其实已经写了 `write_log` 的模块"挂在豁免表上，只会让读表的人以为它没留痕。
    #     所以补一条：**豁免表里的模块代码里不许出现 `write_log(`**（写了就不该被豁免）。
    lying = [n for n in REASONS if n in modules and modules[n][1] > 0]
    if lying:
        fails.append(
            "这些模块其实**已经写了**审计日志，却还挂在豁免表上（过期/假的豁免会让人以为它没留痕）："
            + "、".join(lying)
        )
    # ②c 理由要真的是一句话（不许用 "TODO"/"无" 这类占位符把闸门糊过去）
    thin = [n for n, why in REASONS.items() if len(why.strip()) < 15]
    if thin:
        fails.append("这些豁免理由太短、等于没写理由：" + "、".join(thin))

    # ③ 数量判据（防空转/清单过期）
    if len(modules) < 15:
        fails.append(f"只认出 {len(modules)} 个写端点模块（<15）——判据可能已空转")
    if len(ok_modules) < 10:
        fails.append(f"只有 {len(ok_modules)} 个模块写了审计日志（<10）——判据可能已空转")

    # ④ 提交了、但同一个函数里**没有任何** write_log（2026-09-23 补，来自全项目复核）
    tx_hits, tx_funcs, tx_commits = commits_without_log()
    print(f"\n④ 有日志的函数 {tx_funcs} 个 / 其中 {tx_commits} 处 db.commit()：「提交前没有留痕」{len(tx_hits)} 处")
    for t_rel, t_fn, t_line in tx_hits:
        mark = f"（豁免：{TX_EXEMPT[Path(t_rel).name][:20]}…）" if Path(t_rel).name in TX_EXEMPT else "❌ 没有理由"
        print(f"   · {t_rel}:{t_line}  {t_fn}()  {mark}")
    tx_unexplained = [h for h in tx_hits if Path(h[0]).name not in TX_EXEMPT]
    if tx_unexplained:
        fails.append(
            "这些提交点之前没有任何审计日志（写业务数据必须能在审计页上回查）："
            + "、".join(f"{rel}:{line}（{fn}）" for rel, fn, line in tx_unexplained)
        )
    tx_fossils = [n for n in TX_EXEMPT if not any(Path(h[0]).name == n for h in tx_hits)]
    if tx_fossils:
        fails.append("TX_EXEMPT 里的文件现在并没有这个问题（化石条目，请删掉）：" + "、".join(tx_fossils))
    if len(TX_EXEMPT) > MAX_TX_EXEMPT:
        fails.append(f"TX_EXEMPT 有 {len(TX_EXEMPT)} 条（上限 {MAX_TX_EXEMPT}）——这个口子开太大了")
    if tx_funcs < MIN_LOGGING_FUNCS:
        fails.append(f"只认出 {tx_funcs} 个写日志的函数（<{MIN_LOGGING_FUNCS}）——判据可能已空转")
    if tx_commits < MIN_COMMITS_IN_LOGGING_FUNCS:
        fails.append(
            f"这些函数里只数到 {tx_commits} 处 db.commit()（<{MIN_COMMITS_IN_LOGGING_FUNCS}）——判据可能已空转"
        )

    if fails:
        print("\n❌ 审计留痕不完整：")
        for f in fails:
            print("   - " + f)
        print("\n（不写日志的模块要么补 write_log，要么在 REASONS 里写清理由——"
              "AI 写操作的承诺是『与人工操作同形、事后可回查』。）")
        return 1
    print("\n✅ 每个写端点模块都有审计日志，或有一条写清理由的豁免。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
