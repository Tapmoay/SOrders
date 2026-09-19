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
    "auth.py": "登录/登出/换 token 是**会话**不是业务数据；失败尝试由 login_guard 限流记录，"
               "写进审计会把真正要回查的钱/单改动淹掉",
    "files.py": "只解析上传的表格（不落库、不改任何业务数据）",
    "notifications.py": "已读/删除是**消息状态**不是业务数据；逐条记日志会把审计页淹掉"
                        "（一条群发就是几十行），而消息本身已经落库可查",
    "shipper.py": "货主自己的地址/联系人/地点是**用户私有主数据**，量极大（一人几十条），"
                  "且不影响钱与订单归属；但订单里会存地址快照，改地址改不到历史单",
    # ⛔ `stats.py` 原来挂在这里，理由是"报表只是读、它那两条 POST 是导出"——
    #    2026-09-19 审计第十四轮发现这条**已经过期**：`stats.py::resolve_exception_order`
    #    （异常单处理）会写 `write_log`，也就是说"它不写日志"这句话不再成立。
    #    假豁免比没豁免更糟：看表的人会以为这个模块没留痕，于是不再去看它。
    #    现在由下面 ②b 那条判据盯着（豁免表里的模块代码里不许出现 `write_log(`）。
}

WRITE_ROUTE = re.compile(r"@router\.(?:post|patch|put|delete)\(")


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
