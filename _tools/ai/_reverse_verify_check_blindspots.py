"""反向验证「红线检查自己的**写法盲区**」这两处修复真的生效（v3.44）。

### 这两处盲区是什么
`_check_ai_guardrails.py` 里有两条检查，判据都是"用正则猜代码长什么样"：

**① §2g-2b 目标参数与字段参数不许重名** —— 三个盲区叠在一起：
  · 字段名只认 `enumField("x"`（名字必须**紧跟左括号**），而代码里有 **11 处跨行写法**；
  · 字段构造函数的名单是**手写的 5 个**，漏了 `positionField`；
  · 目标参数只认 `targetXxx()`（**空括号**），而 `targetUser(cn)` / `targetDriverRule(required)`
    是带参数的 → 用它们的 **7 个动作**连目标名都没解出来。
  三个叠起来的净效果：**18 个动作的重名检查是空转**，而检查一直报 OK。

**② §2e-③b 卡片文案不许写 Markdown 星号** —— 区间边界靠 `\\n    },` 认收尾，
  而 `headline = { c -> "…" },` 这种**单行写法有 8 处**。这时正则匹配到的是**后面那块**的收尾，
  区间一路吃到下一块里去（实测：第 57 行的 headline 吃到第 68 行）。后果不是漏检，
  而是**报错指到错的卡片上**——误报与真报长得一样，而"永远在乱报的检查"等于没有检查。

### 为什么必须有这个脚本
这两条检查的特点是：**改回旧写法之后，红线仍然全绿**。所以"注入 bug 会变红"不够，
还要证明"旧判据在当前源码上就会出错"（下面 [SHAPE_DIFFS] 这一段就是这么做的：
同一份源码，旧判据与新判据的提取结果必须**不一致**；一旦有人把新判据改回去，这里立刻红）。

用法：python _tools/ai/_reverse_verify_check_blindspots.py     # 全部达标 → 退出码 0
"""
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = repo_root()
CHECK = HERE / "_check_ai_guardrails.py"
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
MASTER = AI / "AiWriteMasterData.kt"
BASIC = AI / "AiWriteBasicData.kt"

# 旧判据（**故意留在这里**）：这两行就是被修掉的那两个正则。
# 它们不参与"跑检查"，只用来在 [SHAPE_DIFFS] 里证明"旧判据确实看不见 / 确实多扫"。
OLD_FIELD_RE = re.compile(r'(?:textField|moneyField|boolField|enumField|dateField)\("(\w+)"')
OLD_RANGE_RE = re.compile(r"\n\s+details = \{(.*?)\n\s+\},", re.S)


def read_src(p: Path):
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check() -> str:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return (r.stdout or "") + (r.stderr or "")


def sub(path: Path, old: str, new: str):
    return (path, lambda src: src.replace(old, new, 1))


CLASH = "目标参数与字段参数没有重名"
COUNT = "至少扫到了几个带目标的动作"
LOCATED = "的块都定位到了"

MUTATIONS = [
    (
        "①-a 跨行写法里放一个撞名的字段（旧判据看不见跨行，会报 OK）",
        [sub(BASIC, '"vehicle_type", "新车型", "不改就不填",', '"vehicle", "新车型", "不改就不填",')],
        f"AiWriteBasicData.kt: {CLASH}",
    ),
    (
        "①-b 用 `positionField` 写的字段撞名（手写构造函数名单里没有它）",
        [sub(BASIC, 'positionField("position", "排到第几位"', 'positionField("category", "排到第几位"')],
        f"AiWriteBasicData.kt: {CLASH}",
    ),
    (
        "①-c 撞上**带参数的**目标辅助函数（`targetUser(\"账号\")` 旧判据解不出 param）",
        [sub(MASTER, 'textField("phone", "新手机号"', 'textField("user", "新手机号"')],
        f"AiWriteMasterData.kt: {CLASH}",
    ),
    (
        "①-d 把 `targets = listOf(` 改名（＝一个目标都扫不到，数量锚必须喊）",
        [(BASIC, lambda src: src.replace("targets = listOf(", "targetList = listOf("))],
        COUNT,
    ),
    (
        "②-a 把 lambda 的 `{` 挪到下一行（声明数 ≠ 配对数，必须喊出来而不是少扫 16 块）",
        [sub(MASTER, "            details = { c ->\n                buildList {",
              "            details =\n                { c ->\n                buildList {")],
        LOCATED,
    ),
    (
        # ⚠️ 这一条要的是**仍然全绿**：`**` 出现在 commit lambda 里（那是代码，不是卡片文案），
        #    而它前面那个动作的 `details` 恰好是单行写法——旧区间会一路吃到这里，报一张假红。
        "②-b commit 里放一句含 `**` 的代码（不是卡片文案）→ 必须仍然全绿",
        [sub(BASIC, ') { ds, p -> ds.deleteFreightTemplate(p.reqLong("template_id")) },',
              ') { ds, p -> ds.deleteFreightTemplate(p.reqLong("template_id").also'
              ' { println("**这段是代码不是卡片文案**") }) },')],
        "__EXPECT_GREEN__",
    ),
]


def shape_diffs() -> int:
    """同一份源码：旧判据 vs 新判据。**不一致**才说明修复有意义（也才证明它没被改回去）。"""
    bad = 0
    sys.path.insert(0, str(HERE))
    import _check_ai_guardrails as G  # noqa: PLC0415

    src = G.strip_comments(BASIC.read_text(encoding="utf-8"))
    # ---- 字段名：多行写法 ----
    blocks = [G.balanced_inside(src, m.end() - 1) for m in re.finditer(r"fields = listOf\(", src)]
    new_all = {f for b in blocks for f in G.field_names(b)}
    old_all = {f for b in blocks for f in OLD_FIELD_RE.findall(b)}
    blind = sorted(new_all - old_all)
    print(f"  [{'OK' if blind else 'MISS'}] 旧字段判据看不见的字段有 {len(blind)} 个（跨行写法）：{blind}")
    bad += 0 if blind else 1
    # `positionField` / `vehicle_type` 必须在"旧判据看不见"的那一撮里
    for must in ("vehicle_type", "position"):
        if must not in blind:
            print(f"  [MISS] 期望 {must} 落在旧判据的盲区里（它其实被看见了？说明源码换了写法，请复核）")
            bad += 1

    # ---- 卡片文案区间：单行写法 ----
    anchor = 'details = { listOf("模板：${it.ref("template")?.label}"'
    i = src.find(anchor)
    if i < 0:
        print("  [SKIP] 找不到单行 details 的锚点（源码换了写法，请复核这条）")
        return bad + 1
    brace = src.index("{", i)
    new_region = G.balanced_inside(src, brace)
    m = OLD_RANGE_RE.search(src, src.rfind("\n", 0, i))
    old_region = m.group(1) if m else ""
    longer = len(old_region) > len(new_region)
    print(f"  [{'OK' if longer else 'MISS'}] 旧区间比新区间长 {len(old_region) - len(new_region)} 字符"
          f"（旧 {len(old_region)} / 新 {len(new_region)}）——旧判据把后面那块也扫进去了")
    if longer:
        print(f"        新区间原文：{new_region.strip()[:70]!r}")
        print(f"        旧区间多出来的部分：{old_region[len(new_region):].strip()[:70]!r}")
    bad += 0 if longer else 1
    return bad


def main() -> int:
    bad = 0
    base = run_check()
    base_ok = "项通过" in base
    print(f"  [{'OK' if base_ok else 'MISS'}] 基线：没有注入时红线全绿")
    bad += 0 if base_ok else 1

    for label, changes, expect in MUTATIONS:
        originals = []
        skip = False
        for path, mutate in changes:
            src, crlf = read_src(path)
            mutated = mutate(src)
            if mutated == src:
                print(f"  [SKIP] {label} —— 锚点没找到：{path.name}")
                skip = True
                break
            originals.append((path, src, crlf))
            write_src(path, mutated, crlf)
        if skip:
            for path, src, crlf in originals:
                write_src(path, src, crlf)
            bad += 1
            continue
        try:
            out = run_check()
        finally:
            for path, src, crlf in originals:
                write_src(path, src, crlf)

        fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
        if expect == "__EXPECT_GREEN__":
            hit = "项通过" in out and not fails
            print(f"  [{'OK' if hit else 'MISS'}] {label}")
            if not hit:
                for ln in fails[:3]:
                    print("        " + ln.strip())
            bad += 0 if hit else 1
            continue
        hit = any(expect in ln for ln in fails)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → 期望红：{expect}（实际红 {len(fails)} 条）")
        if not hit:
            for ln in fails[:3]:
                print("        " + ln.strip())
            bad += 1

    print("\n== 旧判据 vs 新判据（同一份源码，结果必须不一致）==")
    bad += shape_diffs()

    tail = run_check()
    ok = "项通过" in tail
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 5
    print("\n" + (f"✅ {total}/{total} 都达标：这两处写法盲区真的被堵上了。" if bad == 0 else f"❌ {bad}/{total} 不达标。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
