#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反向验证：`_tools/qa/_check_palette_uniformity.py` 里那些红线**真的在检查**吗？

机器判据最怕的不是写错，是**写得太松**：正则退化成「全文里还有这几个字就行」、
阈值被放宽到「怎么都过」、判据被搬到别的脚本之后原地留了个空壳 —— 三种情况都
**不报错、不崩溃、照样全绿**，而屏幕上已经花了。

这个脚本用「把源码改坏 → 判据必须变红」来证明每一条判据都是活的：

  1. **判据空转**：注入之后退出码仍是 0（`✅ 全部 N 项通过`）⇒ 这条判据是死的；
  2. **只认名字不认形状**：把 `PaletteUniformity.kt` 的函数改名、把单测那一档删掉，
     判据必须跟着红（不能靠「文件还在」蒙过去）；
  3. **口径被单方面改掉**：把明度极差阈值 12 改成 30、把「太灰了一点」从文档里删掉、
     把生成口径 `min(max(0.62 × …` 改成 0.30 —— 用户画的那条线就没人守了。

## R4-BOUNDARY-JUSTIFICATION: 为什么这条红线只能在这儿守

色值是裸 ARGB `Long` / `Color`，**类型系统里没有「这一组值必须落在同一条明度带里」
这种类型** —— 编译器、detekt、Kotlin 的检查都不可能表达它。它只在**值的集合**上成立，
所以只能在「把 19 个值读出来、算一遍 Lab」的地方守：`PaletteUniformityTest.kt`（跑起来）
与本判据脚本（不跑也能查）。反向验证则证明这两处**没有一个是摆设**。

本脚本**只读写工作区里的文件**，不编译、不跑 UI、不连设备；每条注入跑完立刻按字节还原。

用法：
    python _tools/qa/_reverse_verify_palette_uniformity.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_palette_uniformity.py"

UNI = "android/app/src/main/java/com/tapmoay/sorders/ui/theme/PaletteUniformity.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/theme/PaletteUniformityTest.kt"
MODS = "android/app/src/main/java/com/tapmoay/sorders/ui/nav/Modules.kt"
COLOR = "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
DOC = "docs/changes/CHG-0102.md"
REG = "docs/changes/README.md"
ME = "_tools/qa/_reverse_verify_palette_uniformity.py"


def sub(old: str, new: str, idx: int = 0, expect: int | None = None):
    """把第 `idx` 处（0 起）`old` 换成 `new`。

    ⚠️ 为什么要 `idx`：`str.replace(old, new, 1)` 认的是第一处**子串**，而 `old` 经常被
    更长的行包含（踩过：`Icons.Default.Description,` 是另一行后一段，于是"改第 3 处"
    其实改了第 1 处，判据照样绿 —— 注入就成了自欺）。
    """
    def run(text: str) -> str:
        n = text.count(old)
        if n == 0:
            raise AssertionError("注入点不在了：" + repr(old[:80]))
        if expect is not None and n != expect:
            raise AssertionError("注入点命中 %d 次（期望 %d）：%r" % (n, expect, old[:80]))
        pos = -1
        for _ in range(idx + 1):
            pos = text.find(old, pos + 1)
        if pos < 0:
            raise AssertionError("第 %d 处不存在：%r" % (idx, old[:80]))
        return text[:pos] + new + text[pos + len(old):]
    return run


def sub_all(old: str, new: str):
    """把**每一处** `old` 都换掉。

    ⚠️ 为什么要这个：设计系统里用户原话与那三个数字在**两处**出现（顶部沿革那一块 ＋
    §4.25h 正文）。只换第一处的话，判据看的那一节原样还在 ⇒ 判据照样绿，注入就成了自欺
    （踩过：㉝~㊲ 五条一起假绿）。
    """
    def run(text: str) -> str:
        if old not in text:
            raise AssertionError("注入点不在了：" + repr(old[:80]))
        return text.replace(old, new)
    return run


CASES: list[tuple[str, str, object, str]] = [
    # ---------------- 1. 纯函数的形状（改名/删掉都得红） ----------------
    ("① labLightness 被改名",
     UNI, sub("internal fun labLightness(argb: Long): Double",
              "internal fun labLightnessX(argb: Long): Double"),
     "PaletteUniformity.kt 里有"),
    ("② lightnessSpread 被删",
     UNI, sub("internal fun lightnessSpread(colors: List<Long>): Double",
              "internal fun spreadOf(colors: List<Long>): Double"),
     "PaletteUniformity.kt 里有"),
    ("③ argbGap 被改名（距离口径与 ModulesEntryTest 不再对得上）",
     UNI, sub("internal fun argbGap(a: Long, b: Long): Double",
              "internal fun gap(a: Long, b: Long): Double"),
     "PaletteUniformity.kt 里有"),
    ("④ hueDistance 被改名",
     UNI, sub("internal fun hueDistance(argbA: Long, argbB: Long): Double",
              "internal fun hueGap(argbA: Long, argbB: Long): Double"),
     "PaletteUniformity.kt 里有"),
    ("⑤ relativeChroma 被改名",
     UNI, sub("internal fun relativeChroma(argb: Long, maxChroma: Double): Double",
              "internal fun relChroma(argb: Long, maxChroma: Double): Double"),
     "PaletteUniformity.kt 里有"),

    # ---------------- 2. 单测七档（删一档 / 放宽阈值） ----------------
    ("⑥ 单测里「明度极差不超过 12」那一档被放宽成 30",
     TEST, sub("派单端那 19 格的明度极差不超过 12", "派单端那 19 格的明度极差不超过 30"),
     "单测里有「派单端那 19 格的明度极差不超过 12"),
    ("⑦ 货主端那一档被放宽成 30",
     TEST, sub("货主端 8 格的明度极差不超过 16", "货主端 8 格的明度极差不超过 30"),
     "单测里有「货主端 8 格的明度极差不超过 16"),
    ("⑧ 账本页那一档被放宽成 30",
     TEST, sub("账本管理入口页 7 格的明度极差不超过 15", "账本管理入口页 7 格的明度极差不超过 30"),
     "单测里有「账本管理入口页 7 格的明度极差不超过 15"),
    ("⑨ 彩度地板那一档被放宽成 5（低饱和就变回发灰了）",
     TEST, sub("最没颜色的那一格彩度也不低于 27", "最没颜色的那一格彩度也不低于 5"),
     "单测里有「最没颜色的那一格彩度也不低于 27"),
    ("⑩ 彩度落差那一档被放宽成 9 倍",
     TEST, sub("彩度差不超过 2 倍", "彩度差不超过 9 倍", idx=1, expect=2),
     "单测里有「fun `同屏里最艳与最不艳的两格"),
    ("⑪ 两两距离那一档被删（改个名）",
     TEST, sub("派单端 19 格两两距离都不低于 20（够不上 60 的约束，但也不许几乎同色）",
               "派单端 19 格看着还行"),
     "单测里有「两两距离都不低于 20"),

    # ---------------- 3. 派单端 19 格逐个点名 ----------------
    ("⑫ 预订单那一格被换了个近邻色",
     MODS, sub("color = 0xFF7A98D8L),", "color = 0xFF7A98D9L),"),
     "派单端「预订单」"),
    ("⑬ 代理下单那一格被换成订单管理的橄榄金（撞色）",
     MODS, sub("color = MgrGreen),       // 草绿 · 下单（与货主端下单同色）",
               "color = ProgressYellow),  // 草绿 · 下单（与货主端下单同色）"),
     "派单端「代理下单」"),
    ("⑭ 派单端消息中心被换成地址页的晴蓝",
     MODS, sub('ModuleEntry("消息中心", Routes.MESSAGES, Icons.Default.Notifications, color = MessageRed),',
               'ModuleEntry("消息中心", Routes.MESSAGES, Icons.Default.Notifications, color = ShipperTeal),'),
     "派单端「消息中心」"),
    ("⑮ 报表中心那一格被换成商品管理的丁香紫",
     MODS, sub("color = ReportIndigo,  // 蓝紫 · 报表",
               "color = ProductPurple,  // 蓝紫 · 报表"),
     "派单端「报表中心」"),
    ("⑯ 车辆管理那一格被换了个近邻色",
     MODS, sub("color = 0xFF4AA6A8L),", "color = 0xFF4AA6A9L),"),
     "派单端「车辆管理」"),
    ("⑰ 账户管理那一格被换了个近邻色",
     MODS, sub("color = 0xFFA2763DL),", "color = 0xFFA2763EL),"),
     "派单端「账户管理」"),
    ("⑱ 账本管理那一格被换成报表中心那支蓝紫（同屏撞色）",
     MODS, sub("color = MoneyOrange),           // 焦糖 · 账本（跨端同色）",
               "color = ReportIndigo),           // 焦糖 · 账本（跨端同色）"),
     "派单端「账本管理」"),
    ("⑲ 库存管理那一格被换了个近邻色",
     MODS, sub("color = 0xFF278A9DL),", "color = 0xFF278A9EL),"),
     "派单端「库存管理」"),
    ("⑳ 派单端少了一格（计费规则那行被注释掉）",
     MODS, sub('ModuleEntry("计费规则"', '// ModuleEntry("计费规则"'),
     "派单端格数就是 19"),

    # ---------------- 4. 派单端三条硬指标 ----------------
    ("㉑ 消息中心被换成中性灰（同屏出现一块灰）",
     MODS, sub("color = MessageRed),", "color = 0xFF808080L),", expect=4),
     "最灰的一格彩度"),
    ("㉒ 车辆管理被换成刺眼的纯绿（最艳/最灰拉开）",
     MODS, sub("color = 0xFF4AA6A8L),", "color = 0xFF00FF00L),"),
     "最艳/最灰"),
    ("㉓ 库存管理被改成与车辆管理同色（两格一模一样）",
     MODS, sub("color = 0xFF278A9DL),", "color = 0xFF4AA6A8L),"),
     "19 格两两互异"),
    ("㉔ 把整张派单端表的明度拉开（代理下单换成很深的墨绿）",
     MODS, sub("color = MgrGreen),       // 草绿 · 下单（与货主端下单同色）",
               "color = 0xFF1B3A22L),     // 草绿 · 下单（与货主端下单同色）"),
     "明度极差"),

    # ---------------- 5. 货主端与账本页 ----------------
    ("㉕ 货主端「我的账本」被换成很深的色（明度带破了）",
     MODS, sub("color = 0xFFC29750L),", "color = 0xFF201A08L),"),
     "货主端明度极差"),
    ("㉖ 货主端「我的订单」与「我的账本」同色了",
     MODS, sub("color = 0xFF8D7A3CL),", "color = 0xFFC29750L),"),
     "货主端 8 格互异"),
    ("㉗ 账本页「收支」被换成纯黑（明度带破了）",
     MODS, sub("color = 0xFF537BC6L),", "color = 0xFF000000L),"),
     "账本页明度极差"),
    ("㉘ 账本页「货主账」被换成中性灰",
     MODS, sub("color = 0xFF5BA592L),", "color = 0xFF808080L),"),
     "账本页最灰一格彩度"),
    ("㉙ 账本页「批发商账」被改成与「订单账」同色",
     MODS, sub("color = 0xFF8A7339L),", "color = 0xFFC78A4FL),"),
     "账本页 7 格互异"),
    ("㉚ 主题里的 MgrGreen 被换回中性灰（token 与宫格一起坏）",
     COLOR, sub("val MgrGreen = 0xFF59A570", "val MgrGreen = 0xFF8A8A8E"),
     "派单端「代理下单」"),

    # ---------------- 6. 设计系统 §4.25h 与用户口径 ----------------
    ("㉛ 设计系统那一节的编号被改掉（§4.25h 找不到）",
     DESIGN, sub("### 4.25h ", "### 4.25x "),
     "§4.25h"),
    ("㉜ 收尾锚句被改掉（判据按它找那一节）",
     DESIGN, sub("**这一节就是 §4.25h**", "**这一节就是 4.25x**"),
     "收尾锚句"),
    ("㉝ 用户那句「太灰了一点」被从规范里删掉",
     DESIGN, sub_all("太灰了一点", "有点花"),
     "太灰了一点"),
    ("㉞ 用户点名的那一档参数被改掉（相对彩度 0.62 被写成 0.30）",
     DESIGN, sub_all("相对彩度 0.62、明度带 58±5、彩度夹 28~44",
                     "相对彩度 0.30、明度带 48±8、彩度夹 20~30"),
     "用户点名的那一档"),
    ("㉟ 病根数字 7.2 倍被抹掉（后来人看不出为什么要改）",
     DESIGN, sub_all("7.2 倍", "1.2 倍"),
     "7.2 倍"),
    ("㊱ 生成口径被改成「按固定彩度给色」",
     DESIGN, sub_all("min(max(0.62", "min(max(0.30"),
     "按相对彩度给色"),
    ("㊲ 天花板夹取被删掉（青蓝会被推艳）",
     DESIGN, sub_all("max × 0.94", "max × 1.00"),
     "天花板夹取"),

    # ---------------- 7. 变更单 / 登记簿 / 反验脚本本身 ----------------
    ("㊳ 变更单没写 Blast Radius",
     DOC, sub("- **Blast Radius**：L0", "- **Blast Radius**：L9"),
     "Blast Radius"),
    ("㊴ 登记簿里 CHG-0102 那一行被撤掉",
     REG, lambda t: "\n".join(ln for ln in t.split("\n")
                              if not ln.startswith("| `CHG-0102` |")),
     "登记簿"),
    ("㊵ 反验脚本的注入表被换成空壳",
     ME, sub("CASES: list[tuple[str, str, object, str]] = [",
             "CASESX: list[tuple[str, str, object, str]] = [", expect=2),
     "注入表"),
]


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    rc, out = run_check()
    if rc != 0:
        print("⛔ 源码完好时判据就不是全绿 —— 先把 _check_palette_uniformity.py 修到全绿再来跑反向验证。")
        print(out[-3000:])
        return 1
    print("✅ 前置：源码完好时判据全绿（%s）" % CHECK.name)

    originals = {rel: (ROOT / rel).read_bytes() for rel in
                 {c[1] for c in CASES} | {ME}}
    bad: list[str] = []
    try:
        for i, (title, rel, mutate, keyword) in enumerate(CASES, 1):
            p = ROOT / rel
            raw = originals[rel]
            crlf = b"\r\n" in raw
            text = raw.decode("utf-8").replace("\r\n", "\n")
            try:
                broken = mutate(text)  # type: ignore[operator]
            except AssertionError as e:
                bad.append("%s —— %s" % (title, e))
                print("  [MISS] %s —— %s" % (title, e))
                continue
            blob = broken.replace("\n", "\r\n").encode("utf-8") if crlf else broken.encode("utf-8")
            p.write_bytes(blob)
            try:
                rc2, out2 = run_check()
            finally:
                p.write_bytes(raw)
            hit_red = rc2 != 0
            hit_kw = keyword in out2
            hit_any_fail = "[FAIL]" in out2
            if hit_red and (hit_kw or hit_any_fail):
                print("  [OK]   %s" % title)
            else:
                why = "判据还是绿的" if not hit_red else "红了但不是这一条"
                bad.append("%s —— %s（期望关键词「%s」）" % (title, why, keyword))
                print("  [FAIL] %s —— %s" % (title, why))
    finally:
        dirty = []
        for rel, raw in originals.items():
            if (ROOT / rel).read_bytes() != raw:
                (ROOT / rel).write_bytes(raw)
                dirty.append(rel)
        if dirty:
            print("⚠️ 有文件没还原干净，已强制还原：%s" % ", ".join(dirty))

    rc3, out3 = run_check()
    if rc3 != 0:
        print("⛔ 还原之后判据不是全绿 —— 注入把源码改坏了。")
        print(out3[-2000:])
        return 1

    print("")
    for rel, raw in originals.items():
        assert (ROOT / rel).read_bytes() == raw, rel
    print("✅ 还原检查：%d 个被注入的文件逐字节一致；还原之后判据全绿。" % len(originals))

    if bad:
        print("❌ %d/%d 条注入没有被判据抓住：" % (len(bad), len(CASES)))
        for b in bad:
            print("   - " + b)
        return 1
    print("✅ %d 条注入都证明这条红线真的在检查。" % len(CASES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
