"""反向验证：**AI 报价必须绑「这个货主的价」**那条红线（`_check_ai_guardrails.py` §34）真有牙。

## 为什么必须有这一份
红线段落是 2026-09-22 新增的（`§34` 18 项）。它守的是用户去年就报过的那个 bug 的另一半：
界面的报价在 569a23d 绑到了货主，**AI 这一半当时没人管** —— 建单/账本逼模型自己编一个价、
加行直接取"商品库默认价"（连这单的货主都不看）。后果是批发商谈好 10 元、AI 建出来的单按 20 元。

## 判据
每条注入都是一种**真实可能被改回去的形状**（不是随机破坏），要求：注入后跑红线，
**必须点出那一条**（用那一条的中文标题去比），否则说明这条判据是摆设。

⛔ 纪律：注入前按字节备份、跑完按字节还原；全部跑完再跑一次红线确认绿，并逐字节核对还原。
⚠️ 用 `io.open(..., newline="")` 读写：`Path.read_text` 会把 CRLF 折成 LF，
   于是"还原"写回去的其实已经不是原来的字节了（本仓库为这个坑付过代价）。
⚠️ 锚点里的 `\\n` 一律按**这个文件自己的行尾**展开：本仓库两种行尾都有
   （`AiWriteOrderLineHandlers.kt` / `AiWriteBasicHandlers.kt` 是 CRLF，`AiWriteDataSource.kt` 是 LF），
   写死 `\\n` 会让 CRLF 文件上的锚点一个都找不到 —— 而"找不到"只报 SKIP，
   看起来像通过了，其实那几条注入什么都没验证。
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
CHECK = ROOT / "_tools/ai/_check_ai_guardrails.py"

LINE = AI / "AiWriteOrderLineHandlers.kt"
ORDER = AI / "AiWriteOrderHandlers.kt"
BASIC = AI / "AiWriteBasicHandlers.kt"
SVC = AI / "AiWriteDataSource.kt"
PRICE = AI / "AiEffectivePrice.kt"

#: (用例名, 文件, 原文锚点, 注入成什么, 期望红线点出的那一条, 替换第几处)
CASES: list[tuple[str, Path, str, str, str, int]] = [
    (
        "加行退回「商品库默认价」兜底（就是这次修掉的那个缺陷）",
        LINE,
        "        val system = productId?.let { basis.of(order.shipperId, it) }\n",
        "        val system = productId?.let { p ->\n"
        "            ds.productPrices().firstOrNull { it.id == p }?.defaultPrice\n"
        "                ?.toBigDecimalOrNull()?.setScale(2, java.math.RoundingMode.HALF_UP)\n"
        "        }\n",
        "加行按**这个订单货主**的价补",
        1,
    ),
    (
        "口径文件把「专属价优先」改反（只认商品默认价）",
        PRICE,
        "        if (shipperId != null) {\n"
        "            special[shipperId to productId]?.let { return Price(it, fromSpecial = true) }\n"
        "        }\n",
        "",
        "生效价＝**这个货主的专属价**优先",
        1,
    ),
    (
        "建单不再用生效价（没给价就报错，逼模型自己编）",
        ORDER,
        "                system != null -> system.value\n",
        "",
        "建单没给价就用生效价",
        1,
    ),
    (
        "账本记一笔不绑货主（传 null 只走默认价）",
        BASIC,
        "basis.of(shipper?.id, it)",
        "basis.of(null, it)",
        "账本记一笔也绑货主",
        1,
    ),
    (
        "加行卡片上摘掉「与他的价不一致」那句提示",
        LINE,
        "                typed?.let { t -> basis.mismatchNote(t, system)?.let { add(it) } }\n",
        "",
        "三个消费点都接了它",
        1,
    ),
    (
        "查单只填一处 shipperId（另一种查法又绑不到价）",
        SVC,
        "                shipperId = d.shipperId,\n",
        "",
        "**两个**构造点都填了它",
        1,
    ),
]


def read_raw(p: Path) -> str:
    with io.open(p, encoding="utf-8", newline="") as f:
        return f.read()


def write_raw(p: Path, text: str) -> None:
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def run_check() -> str:
    r = subprocess.run(
        [sys.executable, "_tools/ai/_check_ai_guardrails.py"],
        cwd=str(ROOT), capture_output=True,
    )
    return ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")


def main() -> int:
    backups: dict[Path, Path] = {}
    tmp = Path(tempfile.mkdtemp(prefix="rv_price_basis_"))
    for _, path, *_ in CASES:
        if path in backups:
            continue
        bak = tmp / path.name
        shutil.copy2(path, bak)
        backups[path] = bak

    fails: list[str] = []
    byte_diff = 0
    try:
        for name, path, old, new, expect, nth in CASES:
            src = read_raw(path)
            # 锚点按**这个文件自己的行尾**展开（两种行尾都有，写死 \n 会全部 SKIP）
            nl = "\r\n" if "\r\n" in src else "\n"
            old, new = old.replace("\n", nl), new.replace("\n", nl)
            if src.count(old) < nth:
                fails.append(f"{name}：锚点没找到（{path.name} 里 `{old.strip()[:40]}` 出现 {src.count(old)} 次）")
                print(f"  [SKIP] {name} —— 锚点找不到，这条注入**没有验证到东西**")
                continue
            # 只换第 nth 处（其余留给别的用例）
            head, sep, tail = src.partition(old)
            for _ in range(nth - 1):
                h2, s2, t2 = tail.partition(old)
                head, sep, tail = head + sep + h2, s2, t2
            write_raw(path, head + new + tail)
            try:
                out = run_check()
            finally:
                shutil.copy2(backups[path], path)
            if expect in out:
                print(f"  [OK]   {name} → 红线点出「{expect}」")
            else:
                fails.append(f"{name}：红线没点出「{expect}」")
                print(f"  [FAIL] {name} → 红线没点出「{expect}」")
                print("         " + out.strip().splitlines()[-1][:160])
    finally:
        for path, bak in backups.items():
            shutil.copy2(bak, path)

    # 还原核对：逐字节
    for path, bak in backups.items():
        if path.read_bytes() != bak.read_bytes():
            byte_diff += 1
            fails.append(f"还原后 {path.name} 与运行前不一致")
    print(f"\n还原核对：{len(backups)} 个文件" + ("逐字节一致" if byte_diff == 0 else f"**有 {byte_diff} 个不一致**"))

    out = run_check()
    if "全部" not in out or "项通过" not in out:
        fails.append("还原后红线不通过")
        print("❌ 还原后红线不通过")
    else:
        print("✅ 还原后红线恢复通过")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不达标：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明「AI 报价绑货主」这条红线真的有牙。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
