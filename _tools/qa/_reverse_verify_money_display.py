#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_money_display.py` 的**安卓 + 后端**那一半真的会红。

## 为什么是这一份（而不是 2026-09-22 原来那份）
原来那份共 18 条注入，其中 **2 条打 H5**（`frontend/src/utils/formatMoney.ts` 的
`formatMoney2`、`frontend/src/views/dispatcher/DispatcherPending.vue` 里冒出来的
`toFixed(2)`）。2026-09-25 前端 H5 按用户拍板归档（`frontend/` 已不在仓库里，见计划表 §4.2）
→ 那两条没有主体，整份脚本被删。
但**安卓与后端那 16 条不能因此失去反向验证** —— 这一份把它们补回来：判据、注入点、期望命中的
判据标签都与原来一致，只是去掉了 H5 的两条。

## 这一页在防什么
「金额显示」这套红线全是**接线型判据**（某处必须有某个写法），而接线型判据最典型的失效方式是
**锚点太宽**：`Money.kt` 里 `trimMoneyZeros` 也写着 `trimEnd('0').trimEnd('.')`，
所以"整个文件里出现过就行了"是**假绿**的 —— 把 `formatMoney` 里的去零删掉，判据照样通过。
下面 ① 就是那一条（2026-09-22 实测抓到过）。

## 16 种破坏（每一种都必须让红线当场红，且报出**对应**那条判据）

| # | 注入 | 现实里谁会这么改 |
| --- | --- | --- |
| ① | 安卓 `formatMoney` 只删小数点、忘了删末尾的 0 | 抄了个半截实现 |
| ② | 去掉 `Locale.US` | 「反正都是中文机」 |
| ③ | 后端 `money_text` 不去零 | 只改了 App，后端那句文案照旧 |
| ④ | ⛔ `goodsTotalText()` 也去尾零 | **最危险的一种**："顺手统一口径" → 收款页判据与后端 `Decimal` 对不上，多行/多单永久收不了款 |
| ⑤ | 接口出参 `suppliers._money` 去尾零 | 同上，还把 `test_supplier_payables.py` 钉住的形状改掉 |
| ⑥ | `AiWriteArgs.money()` 去尾零 | "AI 卡片的金额也统一一下" → 下游 `== "0.00"`（付清了/免运费）静默不显示 |
| ⑦ | 界面上直接印后端原始金额 | 新增一处显示时没走漏斗 → 卡片上出现 `¥12.5000` |
| ⑧ | 后端新写的通知改了文案格式 | 新写一句通知时忘了过 `money_text` |
| ⑨ | 后端「固定工资 … 元/月」用回 `money()` | 见「元」就手写插值 |
| ⑩ | AI 提示词改回「保留两位小数」 | 改了代码没改提示词 → 聊天里照旧 `¥87.00` |
| ⑪ | 单测里用户点名的 `56.77` 那条被改掉 | 「测试太啰嗦」→ 把用户点名的那条删了 |
| ⑫ | 放行表里的标签文案被改 | 标签文案改了而放行表没跟着改（放行表开始长霉/化石） |
| ⑬ | 进 payload 的金额也改成去零 | 接口形状变了 + 下游 `== "0.00"` 会静默失效 |
| ⑭ | 哨兵比较被改成去零后的写法 | 「付清了」那句会静默不显示 |
| ⑮ | 撤回卡的金额自己写 `setScale(2)` | 第二份口径 |
| ⑯ | `moneyText` 自己写两位小数 | 卡片又变回 `8.00` |

⚠️ 与仓库里其它 `_reverse_verify_*.py` 同一套纪律：**按字节**备份/还原、跑完逐文件核对哈希、
全程不碰 `git checkout --`（那会在真有改动时抹掉工作）。
每条还要求红线报出的**是那一条**判据（`[!!]   <标签>`），而不是"随便红了就算抓到" ——
否则注入 ① 把 ② 弄红也会被记成通过。

用法：python _tools/qa/_reverse_verify_money_display.py
      python _tools/qa/_reverse_verify_money_display.py --list
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_money_display.py"

MONEY_KT = "android/app/src/main/java/com/tapmoay/sorders/util/Money.kt"
MONEY_PY = "backend/app/services/money_text.py"
ARG_KT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteArgs.kt"
POOL_KT = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherPoolScreen.kt"
MSG_PY = "backend/app/services/message_center.py"
PAY_PY = "backend/app/services/driver_pay.py"
LOOP_KT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiAgentLoop.kt"
TEST_KT = "android/app/src/test/java/com/tapmoay/sorders/util/MoneyTest.kt"
RULES_KT = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt"
SHIPPER_LEDGER_KT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteShipperLedgerHandlers.kt"
SUPPLIER_KT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteSupplierHandlers.kt"
REVERT_KT = "android/app/src/main/java/com/tapmoay/sorders/ai/AiRevert.kt"
SUPPLIERS_PY = "backend/app/api/v1/suppliers.py"

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的标签片段)
CASES: list[tuple[str, str, str, str, str]] = [
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
        "③ 后端 `money_text` 不去零（App 改了、后端那句文案照旧 `¥62.00`）",
        MONEY_PY,
        '        s = s.rstrip("0").rstrip(".")\n',
        "",
        "后端 `money_text` 去尾零",
    ),
    (
        "④ ⛔ 顺手把 `goodsTotalText()` 也去尾零"
        "（收款页判据与后端 Decimal 对不上 → 永久收不了款）",
        MONEY_KT,
        "goodsTotal().setScale(2, RoundingMode.HALF_UP).toPlainString()",
        "goodsTotal().stripTrailingZeros().toPlainString()",
        "`goodsTotalText()` 仍是定点两位",
    ),
    (
        "⑤ 接口出参 `suppliers._money` 也去尾零（把 `\"1200.50\"` 那个形状改掉）",
        SUPPLIERS_PY,
        'return f"{q2(Decimal(v or 0)):.2f}"',
        'return f"{q2(Decimal(v or 0))}"',
        "供应商三个出参仍是 `:.2f`",
    ),
    (
        "⑥ AI 写入链路的 `AiWriteArgs.money()` 被「统一」成去尾零"
        "（下游 `== \"0.00\"` 的「付清了/免运费」会静默不显示）",
        ARG_KT,
        "fun money(v: BigDecimal): String = v.setScale(2, RoundingMode.HALF_UP).toPlainString()",
        "fun money(v: BigDecimal): String = v.stripTrailingZeros().toPlainString()",
        "⛔ AI 写入链路的 `AiWriteArgs.money()` 仍是两位小数",
    ),
    (
        "⑦ 新加一处金额显示时没走漏斗（卡片上会出现 `¥12.5000`）",
        POOL_KT,
        '"¥" + formatMoney(t.fee),',
        '"¥" + t.fee,',
        "每一处 `¥` 都过了显示漏斗",
    ),
    (
        "⑧ 后端新写的通知忘了过 `money_text`（正文里印出 `¥50.00`）",
        MSG_PY,
        'f"退货金额 ¥{money_text(returned_amount)}。{note}"',
        'f"退货金额 ¥{returned_amount}。{note}"',
        "`¥{…}`（f-string 里的金额）全走 `money_text`",
    ),
    (
        "⑨ `{{…}} 元` 那句又用回 `money()`（「固定工资 8000.00 元/月」）",
        PAY_PY,
        'f"固定工资 {money_text(self.salary)} 元/月"',
        'f"固定工资 {money(self.salary)} 元/月"',
        "`{…} 元` 的插值全走 `money_text`",
    ),
    (
        "⑩ AI 提示词改回「金额保留两位小数」（聊天里照旧 `¥87.00`）",
        LOOP_KT,
        "金额写「元」并**去掉末尾多余的 0**",
        "金额保留两位小数并写「元」",
        "⛔ 提示词里不再写「金额保留两位小数」",
    ),
    (
        "⑪ 单测里用户点名的 `56.77` 那条被改掉（实现改了、测试跟着松掉）",
        TEST_KT,
        'assertEquals("56.77", formatMoney("56.77"))',
        'assertEquals("56.8", formatMoney("56.77"))',
        '安卓单测钉着 `formatMoney("56.77") == "56.77"`',
    ),
    (
        "⑫ 放行表开始长霉：标签文案改了、表里那条就再也命中不到（化石）",
        RULES_KT,
        'placeholder = "每单 ¥"',
        'placeholder = "每单金额 ¥"',
        "放行表里每条都还命中得到",
    ),
    (
        "⑬ ⛔ 把一个**进 payload** 的金额也改成去零"
        "（接口形状变了 + 下游 `== \"0.00\"` 会静默失效）",
        SHIPPER_LEDGER_KT,
        'put("amount", AiWriteArgs.money(amount))',
        'put("amount", AiWriteArgs.moneyText(amount))',
        "⛔ 金额 payload 槽没有一处用显示口径",
    ),
    (
        "⑭ 哨兵比较被改成去零后的写法（「付清了」那句会静默不显示）",
        SUPPLIER_KT,
        'if (after == "0.00") "（这一笔付清了）"',
        'if (AiWriteArgs.moneyText(after) == "0") "（这一笔付清了）"',
        "哨兵比较还在",
    ),
    (
        "⑮ 撤回卡的金额自己写 `setScale(2)`（第二份口径）",
        REVERT_KT,
        "            formatMoney(raw)",
        "            raw.toBigDecimal().setScale(2, java.math.RoundingMode.HALF_UP).toPlainString()",
        "撤回卡的金额也走同一份显示口径",
    ),
    (
        "⑯ `moneyText` 被改成自己写两位小数（卡片又变回 `8.00`）",
        ARG_KT,
        "fun moneyText(v: BigDecimal): String = formatMoney(v.toPlainString())",
        "fun moneyText(v: BigDecimal): String = v.setScale(2, RoundingMode.HALF_UP).toPlainString()",
        "它复用全 App 那份显示口径",
    ),
]

CRLF = chr(13) + chr(10)


class Sandbox:
    """按**字节**记账的注入沙箱：每次注入前先还原上一轮，跑完再逐字节核对。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, rel: str, old: str, new: str) -> None:
        p = ROOT / rel
        if not p.exists():
            raise ValueError("找不到 " + rel)
        self.saved.setdefault(p, p.read_bytes())
        raw = p.read_bytes()
        crlf = CRLF.encode("utf-8") in raw
        text = raw.decode("utf-8")
        if old not in text:
            # 第二轮 R2-05：报表源码搬进了 `services/reports/` —— **锚点跟着搬家走**。
            # 判据读的是「并集」（`_airepo.reports_source`），注入器也必须打在那份含原文的文件上，
            # 否则沙箱找不到原文 → [SKIP] → 而 SKIP 在本仓库是**计为不成立**的。
            # ⛔ 不逐条改锚点、也不改目标路径：以后报表再搬一次，这里自动跟上。
            import sys as _sys
            from pathlib import Path as _P
            _sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "ai"))
            from _airepo import reports_files as _rf
            for _c in _rf():
                _t = _c.read_text(encoding="utf-8", errors="replace")
                if _t.count(old) == 1:
                    p = _c
                    raw = p.read_bytes()
                    text = raw.decode("utf-8")
                    if CRLF.encode("utf-8") in raw:
                        text = text.replace(CRLF, chr(10))
                    self.saved.setdefault(p, raw)
                    break
        if crlf:
            text = text.replace(CRLF, chr(10))
        if text.count(old) != 1:
            raise ValueError(rel + " 里锚点出现 " + str(text.count(old)) + " 次（要恰好一次）")
        text = text.replace(old, new, 1)
        p.write_bytes((text.replace(chr(10), CRLF) if crlf else text).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(CASES, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条红线就没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时红线是绿的 —— " + last.strip())
        for label, rel, old, new, want in CASES:
            sb.restore()
            try:
                sb.apply(rel, old, new)
                code, out = run_check()
            except ValueError as exc:
                print("  [SKIP] " + label + " —— " + str(exc))
                bad += 1
                continue
            finally:
                sb.restore()
            # ⛔ 必须命中**那一条**判据：注入 ① 把 ② 弄红也算没抓到
            hit = code != 0 and ("[!!]   " + want) in out
            if hit:
                print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
            else:
                bad += 1
                why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("[!!]")][:6]:
                    print("       红线实际报的：" + ln)
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    dirty = sb.dirty()
    if dirty:
        bad += 1
        print("⛔ 跑完没逐字节还原：" + "、".join(dirty))
    total = len(CASES) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立：安卓 + 后端那一半的每一种破坏都被对应的判据抓到了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
