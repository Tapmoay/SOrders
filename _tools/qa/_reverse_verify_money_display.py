"""反向验证：`_tools/qa/_check_money_display.py` 那些判据**真的抓得住**吗（2026-09-22）。

手法与仓库里其它 `_reverse_verify_*.py` 同一套：**按字节备份 → 注入 → 跑红线（期望非零退出且命中
指定判据）→ 按字节还原 → 校验 sha256**。⛔ 全程不碰 `git checkout --`（那会在真有改动时抹掉工作）。

⚠️ 每个注入点都挑**真会有人这么改**的那条路，而不是"随便删一行"：

| # | 注入 | 现实里谁会这么改 |
| --- | --- | --- |
| ① | 安卓 `formatMoney` 只删小数点不删 0 | 抄了个半截实现 |
| ② | 去掉 `Locale.US` | 「反正都是中文机」 |
| ③ | H5 改回 `toFixed(2)` | 只改了安卓那一份，忘了 H5 |
| ④ | 后端 `money_text` 不去零 | 只改了前端，后端那句文案照旧 |
| ⑤ | `goodsTotalText()` 也去尾零 | **最危险的一种**："顺手统一口径"→ 收款页判据与后端 `Decimal` 对不上，多行/多单永久收不了款 |
| ⑥ | 接口出参 `suppliers._money` 去尾零 | 同上，还把 `test_supplier_payables.py` 钉住的形状改掉 |
| ⑦ | `AiWriteArgs.money()` 去尾零 | "AI 卡片的金额也统一一下"→ 下游 `== "0.00"`（付清了/免运费）静默不显示 |
| ⑧ | 界面上直接印后端原始金额 | 新增一处显示时没走漏斗 → 卡片上出现 `¥12.5000` |
| ⑨ | 后端文案改回 `¥{原始值}` | 新写一句通知时忘了过 `money_text` |
| ⑩ | AI 提示词改回「保留两位小数」 | 改了代码没改提示词 → 聊天里照旧 `¥87.00` |
| ⑪ | 单测里那三个例子被改掉 | 「测试太啰嗦」→ 把用户点名的 `56.77` 那条删了 |
| ⑫ | 放行表里的标签文案被改 | 标签文案改了而放行表没跟着改（放行表开始长霉/化石） |

用法：
    python _tools/qa/_reverse_verify_money_display.py          # 全部跑
    python _tools/qa/_reverse_verify_money_display.py --list   # 只列注入点
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import (  # noqa: E402
    lock_reverse_verify,
    refuse_if_injecting,
    unlock_reverse_verify,
)

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_money_display.py"

MONEY_KT = "android/app/src/main/java/com/tapmoay/sorders/util/Money.kt"
MONEY_TS = "frontend/src/utils/formatMoney.ts"
MONEY_PY = "backend/app/services/money_text.py"
ARG_KT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteArgs.kt"
POOL_KT = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherPoolScreen.kt"
MSG_PY = "backend/app/services/message_center.py"
PAY_PY = "backend/app/services/driver_pay.py"
LOOP_KT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiAgentLoop.kt"
TEST_KT = "android/app/src/test/java/com/tapmoay/sorders/util/MoneyTest.kt"
RULES_KT = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt"
PENDING_VUE = "frontend/src/views/dispatcher/DispatcherPending.vue"
SHIPPER_LEDGER_KT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteShipperLedgerHandlers.kt"
SUPPLIER_KT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteSupplierHandlers.kt"
REVERT_KT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiRevert.kt"

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的关键字)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 安卓 `formatMoney` 只删小数点、忘了删末尾的 0（半截实现）",
        MONEY_KT,
        '"%.2f".format(Locale.US, v).trimEnd(\'0\').trimEnd(\'.\')',
        '"%.2f".format(Locale.US, v)',
        "安卓 `formatMoney` 先按分四舍五入",
    ),
    (
        "② 去掉 `Locale.US`（默认语言是德语时 `%.2f` 会印成 `56,7`）",
        MONEY_KT,
        '"%.2f".format(Locale.US, v)',
        '"%.2f".format(v)',
        "安卓显式 `Locale.US`",
    ),
    (
        "③ H5 只改了安卓那一份、自己还是 `toFixed(2)`（同一屏两种写法）",
        MONEY_TS,
        "n.toFixed(2).replace(/\\.?0+$/, '')",
        "n.toFixed(2)",
        "H5 `formatMoney2` 去尾零",
    ),
    (
        "④ 后端 `money_text` 不去零（前端改了、后端那句文案照旧 `¥62.00`）",
        MONEY_PY,
        '        s = s.rstrip("0").rstrip(".")\n',
        "",
        "后端 `money_text` 去尾零",
    ),
    (
        "⑤ ⛔ 顺手把 `goodsTotalText()` 也去尾零（收款页判据与后端 Decimal 对不上 → 永久收不了款）",
        MONEY_KT,
        "goodsTotal().setScale(2, RoundingMode.HALF_UP).toPlainString()",
        "goodsTotal().stripTrailingZeros().toPlainString()",
        "`goodsTotalText()` 仍是定点两位",
    ),
    (
        "⑥ 接口出参 `suppliers._money` 也去尾零（把 `\"1200.50\"` 那个形状改掉）",
        "backend/app/api/v1/suppliers.py",
        'return f"{q2(Decimal(v or 0)):.2f}"',
        'return f"{q2(Decimal(v or 0))}"',
        "供应商三个出参仍是 `:.2f`",
    ),
    (
        "⑦ AI 写入链路的 `AiWriteArgs.money()` 被「统一」成去尾零"
        "（下游 `== \"0.00\"` 的「付清了/免运费」会静默不显示）",
        ARG_KT,
        "fun money(v: BigDecimal): String = v.setScale(2, RoundingMode.HALF_UP).toPlainString()",
        "fun money(v: BigDecimal): String = v.stripTrailingZeros().toPlainString()",
        "⛔ AI 写入链路的 `AiWriteArgs.money()` 仍是两位小数",
    ),
    (
        "⑧ 新加一处金额显示时没走漏斗（卡片上会出现 `¥12.5000`）",
        POOL_KT,
        '"¥" + formatMoney(t.fee),',
        '"¥" + t.fee,',
        "每一处 `¥` 都过了显示漏斗",
    ),
    (
        "⑨ 后端新写的通知忘了过 `money_text`（正文里印出 `¥50.00`）",
        MSG_PY,
        'f"退货金额 ¥{money_text(returned_amount)}。{note}"',
        'f"退货金额 ¥{returned_amount}。{note}"',
        "`¥{…}`（f-string 里的金额）全走 `money_text`",
    ),
    (
        "⑩ `{{…}} 元` 那句又用回 `money()`（「固定工资 8000.00 元/月」）",
        PAY_PY,
        "f\"固定工资 {money_text(self.salary)} 元/月\"",
        "f\"固定工资 {money(self.salary)} 元/月\"",
        "`{…} 元` 的插值全走 `money_text`",
    ),
    (
        "⑪ AI 提示词改回「金额保留两位小数」（聊天里照旧 `¥87.00`）",
        LOOP_KT,
        "金额写「元」并**去掉末尾多余的 0**",
        "金额保留两位小数并写「元」",
        "⛔ 提示词里不再写「金额保留两位小数」",
    ),
    (
        "⑫ 单测里用户点名的 `56.77` 那条被改掉（实现改了、测试跟着松掉）",
        TEST_KT,
        'assertEquals("56.77", formatMoney("56.77"))',
        'assertEquals("56.8", formatMoney("56.77"))',
        '安卓单测钉着 `formatMoney("56.77") == "56.77"`',
    ),
    (
        "⑬ 放行表开始长霉：标签文案改了、表里那条就再也命中不到（化石）",
        RULES_KT,
        'placeholder = "每单 ¥"',
        'placeholder = "每单金额 ¥"',
        "放行表里每条都还命中得到",
    ),
    (
        "⑭ H5 又冒出一处自己写的 `toFixed(2)`",
        PENDING_VUE,
        "function fmtLineSub(line: EditLineFormState) {",
        "function fmtLineSub(line: EditLineFormState) {\n  const probe = (0).toFixed(2)",
        "`toFixed(2)` 只允许在 `formatMoney.ts` 里",
    ),
    (
        "⑮ ⛔ 把一个**进 payload** 的金额也改成去零（接口形状变了 + 下游 `== \"0.00\"` 会静默失效）",
        SHIPPER_LEDGER_KT,
        'put("amount", AiWriteArgs.money(amount))',
        'put("amount", AiWriteArgs.moneyText(amount))',
        "`AiWriteArgs.money(` 剩下的",
    ),
    (
        "⑯ 哨兵比较被改成去零后的写法（「付清了」那句会静默不显示）",
        SUPPLIER_KT,
        'if (after == "0.00") "（这一笔付清了）"',
        'if (AiWriteArgs.moneyText(after) == "0") "（这一笔付清了）"',
        "哨兵比较还在",
    ),
    (
        "⑰ 撤回卡的金额自己写 `setScale(2)`（第二份口径）",
        REVERT_KT,
        "            formatMoney(raw)",
        "            raw.toBigDecimal().setScale(2, java.math.RoundingMode.HALF_UP).toPlainString()",
        "撤回卡的金额也走同一份显示口径",
    ),
    (
        "⑱ `moneyText` 被改成自己写两位小数（卡片又变回 `8.00`）",
        ARG_KT,
        "fun moneyText(v: BigDecimal): String = formatMoney(v.toPlainString())",
        "fun moneyText(v: BigDecimal): String = v.setScale(2, RoundingMode.HALF_UP).toPlainString()",
        "它复用全 App 那份显示口径",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    if refuse_if_injecting("金额显示反向验证"):
        return 1

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    lock_reverse_verify()
    caught = 0
    problems: list[str] = []
    try:
        for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
            path = ROOT / rel
            if not path.exists():
                problems.append(f"{name}：找不到 {rel}")
                print(f"\n[{i}] {name}\n  ❌ 找不到 {rel}")
                continue
            orig = path.read_bytes()
            orig_sha = sha(path)
            text = orig.decode("utf-8")
            eol = "\r\n" if "\r\n" in text else "\n"
            if eol != "\n":
                old = old.replace("\n", eol)
                new = new.replace("\n", eol)
            pat = old[3:] if old.startswith("re:") else re.escape(old)
            injected, n = re.subn(pat, new, text, count=1)
            if n != 1:
                problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:40]!r}）")
                print(f"\n[{i}] {name}\n  ❌ 锚点没命中，跳过（注入点腐烂了）")
                continue
            inj_bytes = injected.encode("utf-8")
            path.write_bytes(inj_bytes)
            try:
                rc, out = run_check()
            finally:
                now = path.read_bytes()
                if now != inj_bytes:
                    print(f"\n[{i}] {name}\n  🛑 有别的东西改了 {rel} —— **拒绝还原**，请人工处理！")
                    return 2
                path.write_bytes(orig)
            if sha(path) != orig_sha:
                print(f"\n[{i}] {name}\n  🛑 {rel} 还原后哈希对不上，停手")
                return 2

            hit = f"[!!]   {want}" in out
            if rc != 0 and hit:
                caught += 1
                print(f"\n[{i}] {name}\n  ✅ 被抓到（红线非零退出，命中「{want}」）")
            else:
                why = "红线居然还是绿的" if rc == 0 else f"退出了，但输出里没有「[!!]   {want}」"
                problems.append(f"{name}：{why}")
                print(f"\n[{i}] {name}\n  ❌ {why}")
                # 诊断：把红线**实际**报出来的失败项打出来。
                # 没有这一段，看到"没命中"只知道"没抓到"，不知道它到底报了什么（锚点腐烂时最费时间）。
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("[!!]")][:6]:
                    print(f"       红线实际报的：{ln}")
                if rc != 0 and not any(x.startswith("[!!]") for x in out.splitlines()):
                    tail = [x for x in out.splitlines() if x.strip()][-6:]
                    print("       红线没打印任何 [!!]（可能是崩了），末尾输出：")
                    for ln in tail:
                        print(f"         {ln}")
    finally:
        unlock_reverse_verify()

    print("\n" + "=" * 60)
    print(f"{caught}/{len(INJECTIONS)} 种破坏方式被抓住")
    if problems:
        print("❌ 有漏网的：")
        for p in problems:
            print("   -", p)
        return 1
    print("✅ 全部注入都被抓住，且每个文件都按字节还原")
    return 0


if __name__ == "__main__":
    sys.exit(main())
