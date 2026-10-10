#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CHG-0087 反向验证：把「钱相关四条」的判据逐条弄红一次，确认它们不是空转的。

为什么必须有这个脚本
--------------------
静态判据最危险的失效方式不是「报错」，而是**空转**：判据写得再漂亮，只要它盯的那行源码
被挪走、改名、换一种写法，它就会永远绿下去 —— 收口时「跑了一遍全绿」和「判据其实什么都
没在管」从输出上看一模一样。本单这四条又是**钱的写端点**（手动定价 / 让价 / 取消让价 /
设挂账额度），判据空转的后果不是「功能少一个」，而是「卡上写的和真正发出去的不一样」，
所以收口不能只跑一次判据看它绿，还要逐条**注入一处真实的破坏**，看判据是否**恰好红在
那一条**上。

为什么「跳过」也算失败
----------------------
每条注入都要求原文在该文件里**恰好出现一次**：
  * 多于一次 = 锚点不唯一：改到哪一处不确定，改完是什么状态也不确定；
  * 零次     = 注入没生效（源码已经不是读到的样子），这条验证等于没做。
两种都记 [SKIP] 并计入失败 —— 宁可这里红，也不要带着「以为验过了」的错觉收工。

为什么文书那三处要单独一组（FILE_MUTATIONS）
------------------------------------------
「登记簿里有这一条」「工作声明里有这一条」「台账里有 L-56 那一行」这三条判据问的是
**整个文件里有没有这个记号**（读全文做子串判断），而记号在文件里出现不止一次（工作声明
里既在标题里出现、又在「变更单 docs/changes/CHG-0087.md」里出现；台账里既有章节标题、
又有 L-56 那一行）。只改一处**不足以**把这类判据弄红，所以这一组用「把所有出现都换掉」
的口径，dry 里只要求「至少出现 1 次」—— 与上面那组区别对待。

注入的破坏分八类（对应判据的八种失效方式）
------------------------------------------
① 定价门：锁死那一档被删 / 说不出为什么 / 已撤销那档漏掉；
② 定价的输入口径与卡片承诺（说「不适用」才清空、不说＝沿用、金额可填 0、不沉淀价目）；
③ 让价：范围上界、第二次是整份替换、值不对要在弹卡前拦下；
④ 取消让价：本来就没有让价时按后台原话拦下；
⑤ 资源表（额度按钱显示 / nullableWritable 点名额度）与撤回表（定价那条为什么没有按钮）；
⑥ 数据源那一跳（额度必须走 ArrearsUnitEditRequest）；
⑦ 工具与单测的钉子（红线白名单的单条读、覆盖表里塞回一条、动作总数上界、假数据源、
   说明书那两道闸门）；
⑧ 文书四处（变更单九节、登记簿、工作声明、台账那一行）。

⚠️ 跑的时候拿着注入锁（_airepo.lock_reverse_verify）：注入期间源码是坏的，并发的判据
   会被 _check_ai_money.py 开头那道 refuse_if_injecting 拦下来，不给可信结论。

用法
----
    python _tools/qa/_reverse_verify_ai_money.py          # 真注入：改文件 -> 跑判据 -> 还原
    python _tools/qa/_reverse_verify_ai_money.py --dry    # 只验锚点，一个字节都不改
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools" / "ai"))

from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

CHECK = ROOT / "_tools" / "qa" / "_check_ai_money.py"

AI = "android/app/src/main/java/com/tapmoay/sorders/ai/"
MC = AI + "AiWriteMoney.kt"
W = AI + "AiWrite.kt"
SRC = AI + "AiWriteDataSource.kt"
RES = AI + "AiResources.kt"
RV = AI + "AiRevert.kt"
T = "android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt"
PT = "android/app/src/test/java/com/tapmoay/sorders/ai/AiWritePromptTest.kt"
GUARDRAILS = "_tools/ai/_check_ai_guardrails.py"
WC = "_tools/ai/_write_coverage.py"
REGISTRY = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"
LEDGER = "_tmp/USER_BUG_LEDGER_20261006.md"
DOC = "docs/changes/CHG-0087.md"

# （说明, 相对路径, 原文, 替换成, 期望变红的检查名关键词）
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    # ---- ① 定价门 ----
    (
        "已送达且定过价那一档不再说「锁死」（改成还能改）",
        MC,
        "已送达的单运费是锁定的",
        "这一单的运费还能改",
        "定价门：已送达且定过价 = 锁死",
    ),
    (
        "锁死那句不再说明为什么（司机账单 / 两个页面两个数）",
        MC,
        "（事后改运费不会动司机账单，只会在两个页面上显示两个数）。",
        "（改了就改了）。",
        "定价门：锁死那句连带说出为什么",
    ),
    # ---- ② 定价的输入口径与卡片承诺 ----
    (
        "卡片上不再写「沿用现在的分类」（说了名字的那一路）",
        MC,
        "（沿用现在的分类）",
        "（分类照旧）",
        "卡片：分类沿用要写出来",
    ),
    (
        "参数提示里「可以填 0」没了（模型会以为 0 是非法值）",
        MC,
        "元。可以填 0（＝这一单不收运费）",
        "元。",
        "参数：金额可填 0",
    ),
    (
        "补定那一段不再写「这是补定」（补定与锁定就分不清了）",
        MC,
        "这是补定：",
        "这是补定。",
        "卡片：已送达补定那一段",
    ),
    # ---- ③ 让价 ----
    (
        "超上界那句不再把常量拼进话里（硬编码 200）",
        MC,
        'MAX_DISCOUNT_LINES + " 行，收到 "',
        '"200 行，收到 "',
        "超上界那句是把常量拼进话里",
    ),
    (
        "卡片不再说清「第二次让价是整份替换」（用户会以为是叠加）",
        MC,
        "这次会把它整份替换掉，不是叠加。",
        "这次会把它改掉。",
        "卡片：第二次让价是整份替换",
    ),
    # ---- ④ 取消让价 ----
    (
        "本来就没有让价时不再按后台原话拦下（改成泛泛一句）",
        MC,
        "后台的原话：「这一单本来就没有折扣。」",
        "后台说这一单没有折扣",
        "本来就没有让价：按后台原话拦下",
    ),
    # ---- ⑤ 资源表与撤回表 ----
    (
        "额度不再按钱显示（变成裸数字 8000 而不是 8000.00 元）",
        RES,
        'moneyKeys = setOf("credit_limit"),',
        'moneyKeys = setOf("name"),',
        "额度按钱显示",
    ),
    (
        "nullableWritable 不再点名额度（「写成不限额」那个撤回按钮就是假的）",
        RES,
        'nullableWritable = setOf("credit_limit"),',
        'nullableWritable = setOf("phone"),',
        "nullableWritable 点名额度",
    ),
    (
        "撤回表里定价那条不再说清「不顺手沉淀价目」",
        RV,
        "这一步不会顺手把价沉淀成价目",
        "价目不受影响",
        "撤回表：定价那条说清不顺手沉淀价目",
    ),
    # ---- ⑥ 数据源那一跳 ----
    (
        "设额度改用 ArrearsUnitUpdateRequest（null 键会被丢掉，「不限额」清不掉）",
        SRC,
        "ArrearsUnitEditRequest(",
        "ArrearsUnitUpdateRequest(",
        "额度实现必须用 ArrearsUnitEditRequest",
    ),
    # ---- ⑦ 工具与单测的钉子 ----
    (
        "红线白名单把「读单条额度」这一跳从读里划掉（prepare 里那一次读会被判成写）",
        GUARDRAILS,
        '"arrearsUnit",',
        '"arrearsUnits",',
        "红线白名单把单条读认成读",
    ),
    (
        "覆盖表里把定价那条塞回「不做」桶（写了不做的又做了）",
        WC,
        '    ("POST", "orders/{}/address-image"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",',
        '    ("POST", "orders/{}/price-freight"): "手动定价要同时定方式、值、范围、理由四件事（本轮不开放）",\n'
        '    ("POST", "orders/{}/address-image"): "上传类：要一个文件，模型给不出（v3.7 永久排除）",',
        "POST /orders/{}/price-freight 不再挂在「不做」里",
    ),
    (
        "单测里的动作总数上界缩回 165（下一批加动作时会先撞到这堵墙）",
        T,
        "AiWrites.ALL.size <= 176",
        "AiWrites.ALL.size <= 165",
        "单测里钉住了动作总数上界 176",
    ),
    (
        "假数据源不再记录「读回单条额度」那一跳",
        T,
        'moneyCalls += "arrearsUnit:',
        'moneyCalls += "arrearsUnits:',
        "假数据源把读额度的单条那一跳也记下来了",
    ),
    (
        "说明书带进上下文的参数约束上限缩回 2500（钱那三个数就不再进上下文）",
        PT,
        "上限 2600",
        "上限 2500",
        "说明书那两道闸门",
    ),
    # ---- ⑧ 文书 ----
    (
        "变更单少了「关闭」那一节（九节不齐）",
        DOC,
        "## ⑨ 关闭",
        "## ⑨ 收尾",
        "变更单九节齐",
    ),
]

# 这一组问的是「整个文件里有没有这个记号」，记号本身出现不止一次 ⇒ 用「全部换掉」的口径。
# （说明, 相对路径, 原文, 替换成, 期望变红的检查名关键词）
FILE_MUTATIONS: list[tuple[str, str, str, str, str]] = [
    (
        "登记簿里 CHG-0087 全部改号（文件在、登记簿里没有）",
        REGISTRY,
        "CHG-0087",
        "CHG-0099",
        "登记簿里有这一条",
    ),
    (
        "工作声明里 CHG-0087 全部改号（文件在、声明里没有）",
        CLAIM,
        "CHG-0087",
        "CHG-0099",
        "工作声明里有这一条",
    ),
    (
        "台账里 L-56 全部改号（行还在、编号不对）",
        LEDGER,
        "L-56",
        "L-99",
        "台账里有 L-56 那一行",
    ),
]


def read_src(rel: str) -> tuple[str, bool]:
    raw = (ROOT / rel).read_bytes()
    crlf = b"\r\n" in raw
    return raw.decode("utf-8").replace("\r\n", "\n"), crlf


def write_src(rel: str, text: str, crlf: bool) -> None:
    data = text.replace("\n", "\r\n") if crlf else text
    (ROOT / rel).write_bytes(data.encode("utf-8"))


def restore_src(rel: str, text: str, crlf: bool, expect: bytes) -> None:
    write_src(rel, text, crlf)
    back = (ROOT / rel).read_bytes()
    if back != expect:
        print("  [FATAL] 还原后字节不一致：{}".format(rel))
        raise SystemExit(2)


def run_check():
    # 子进程强制 UTF-8：Windows 控制台默认是 GBK，判据里的中文标签一旦被按 GBK 编码，
    # 这一侧按 UTF-8 解出来就是乱码，expect 关键词会永远匹配不上（全部误报 MISS）。
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(CHECK)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def fails_of(out: str) -> list[str]:
    return [line.strip() for line in out.splitlines() if line.strip().startswith("[FAIL]")]


def verdict(expect: str, proc) -> tuple[bool, str]:
    lines = fails_of(proc.stdout + proc.stderr)
    if proc.returncode == 0:
        return False, "判据**没红**（退出码 0）—— 这条检查是空转的"
    hit = [line for line in lines if expect in line]
    if hit:
        return True, hit[0]
    return False, "红了但不是这条（实际红 {} 条）：{}".format(len(lines), " | ".join(lines[:3]))


def dry_run() -> int:
    print("== 只验锚点（--dry）：一个字节都不改 ==")
    bad = 0
    for idx, (why, rel, old, _new, expect) in enumerate(MUTATIONS, start=1):
        text, _crlf = read_src(rel)
        n = text.count(old)
        if n == 1:
            print("  [OK]   {}. {} :: {}".format(idx, rel, why))
        else:
            bad += 1
            print("  [BAD]  {}. {} :: {} —— 原文出现 {} 次（期望 1 次）；期望判据：{}".format(idx, rel, why, n, expect))
    base = len(MUTATIONS)
    for idx, (why, rel, old, _new, expect) in enumerate(FILE_MUTATIONS, start=1):
        text, _crlf = read_src(rel)
        n = text.count(old)
        if n >= 1:
            print("  [OK]   {}. {} :: {}（全文换掉 {} 处）".format(base + idx, rel, why, n))
        else:
            bad += 1
            print("  [BAD]  {}. {} :: {} —— 出现 0 次；期望判据：{}".format(base + idx, rel, why, expect))
    print()
    if bad:
        print("❌ {} 条锚点不唯一 / 找不到。".format(bad))
        return 1
    print("✅ {} 条锚点全部命中（{} 条单点 ＋ {} 条全文）。".format(len(MUTATIONS) + len(FILE_MUTATIONS), len(MUTATIONS), len(FILE_MUTATIONS)))
    return 0


def run_all() -> int:
    if "--dry" in sys.argv:
        return dry_run()

    total = len(MUTATIONS) + len(FILE_MUTATIONS) + 1
    print("== 0. 前提：源码完好时判据必须全绿 ==")
    proc = run_check()
    if proc.returncode != 0:
        print("  [FATAL] 起点判据就是红的，没法做反向验证（先修好再加注入）。")
        for line in fails_of(proc.stdout + proc.stderr)[:10]:
            print("    " + line)
        return 2
    for line in (proc.stdout + proc.stderr).splitlines():
        if "全部" in line and "通过" in line:
            print("  [OK]  " + line.strip())
            break
    else:
        print("  [OK]  判据退出码 0")

    print()
    print("== 1. 逐条注入 -> 跑判据 -> 还原 ==")
    bad = 0
    for idx, (why, rel, old, new, expect) in enumerate(MUTATIONS, start=1):
        text, crlf = read_src(rel)
        n = text.count(old)
        if n != 1:
            bad += 1
            print("  [SKIP] {}. {} :: {} —— 原文出现 {} 次（期望 1 次）".format(idx, rel, why, n))
            continue
        before = (ROOT / rel).read_bytes()
        try:
            write_src(rel, text.replace(old, new), crlf)
            got = run_check()
            ok, detail = verdict(expect, got)
        finally:
            restore_src(rel, text, crlf, before)
        if ok:
            print("  [OK]   {}. {} :: {} -> 判据红在「{}」".format(idx, rel, why, expect))
        else:
            bad += 1
            print("  [MISS] {}. {} :: {} -> {}".format(idx, rel, why, detail))

    base = len(MUTATIONS)
    for idx, (why, rel, old, new, expect) in enumerate(FILE_MUTATIONS, start=1):
        seq = base + idx
        text, crlf = read_src(rel)
        n = text.count(old)
        if n < 1:
            bad += 1
            print("  [SKIP] {}. {} :: {} —— 原文出现 0 次".format(seq, rel, why))
            continue
        before = (ROOT / rel).read_bytes()
        try:
            write_src(rel, text.replace(old, new), crlf)
            got = run_check()
            ok, detail = verdict(expect, got)
        finally:
            restore_src(rel, text, crlf, before)
        if ok:
            print("  [OK]   {}. {} :: {}（{} 处）-> 判据红在「{}」".format(seq, rel, why, n, expect))
        else:
            bad += 1
            print("  [MISS] {}. {} :: {} -> {}".format(seq, rel, why, detail))

    print()
    print("== 2. 收尾：文件都还原之后，判据必须重新全绿 ==")
    proc = run_check()
    if proc.returncode == 0:
        print("  [OK]  判据重新全绿（没有文件被留在改坏的状态）")
    else:
        bad += 1
        print("  [MISS] 还原之后判据仍然是红的 —— 有文件没还原干净")
        for line in fails_of(proc.stdout + proc.stderr)[:10]:
            print("    " + line)

    print()
    if bad:
        print("❌ {}/{} 条不成立。".format(bad, total))
        return 1
    print("✅ {}/{} 全部成立：每条判据都被单独弄红过一次，而且只在它自己身上红。".format(total, total))
    return 0


def main() -> int:
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    sys.exit(main())