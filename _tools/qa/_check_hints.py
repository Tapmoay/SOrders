"""红线：界面「提示/说明」的**统一入口**与**一个总开关**（用户 2026-09-21 定的规矩）。

## 为什么要有它
用户原话：
> 「打开就打开**所有的提示相关的内容**，关闭就关闭**所有的提示**，就按我们正常的按钮进行显示。」
> 「以后写其他的功能……要写说明或者提示，都要按照这个规范走**统一的接口**。」

规矩写在 `docs/HINT_STYLE.md`，接口写在 `ui/common/Hints.kt`。**没有这条红线的话**，
下一个写页面的人只要顺手写一句 `Text("按下去会怎样…")`，那句解释就**永远关不掉** ——
不报错、也没有任何提示。这正是这个仓库反复出现的那一类问题：
"两个人写得不一样，谁都不会红"（`AGENTS.md` 里那张"手写清单"的教训）。

## 判据（**两个方向都要管**，少一个方向就等于没管）
1. **该走 `Hint` 却裸 `Text`** → 红：关掉开关它还在。
2. **不该走 `Hint` 却走了** → 红：关掉开关把用户的**数据/状态/错误**一起关掉。
   判据**不是**逐条清单，而是算出来的：**一次 `Hint(` 调用里至少要有一段是解释句** ——
   纯数据/纯状态的调用没有存在的理由（那种调用一定是把金额、数量、状态回执挂上去了）。
3. **机制不许回退**：per-key 计数（"每条最多 3 次"）不许回来；开关的读写三件套必须在；
   根上必须提供 `LocalHints`；`HintOnce` 兼容壳只许减不许增。
4. **反空转**：分类器一旦坏掉（一条解释句都认不出来），第 1、2 条会**空过** →
   所以每一组都配下限（文案数 / 解释句数 / `Hint` 调用数）。
5. **生成物新鲜度**：目录文档委托给 `_hint_inventory.py --check`（它自己就是那份文档的作者）。

⚠️ **扫源码的断言先剥注释**：新 `HintPrefs.kt` 的 KDoc 里**写着**旧机制的名字
（"`seen`/`markSeen`/`hasLeft`/`MAX_TIMES` 已删除"）—— 不剥注释的话，"旧机制不许回来"这条
会被自己那段说明**误判成红**。这是本仓库踩过的同一类坑：判据得看**代码**，不是看提到它的字。

用法：python _tools/qa/_check_hints.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _hint_inventory as inv  # noqa: E402   —— 扫描规则**只有一份**，这里不另写

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"

HINTS_KT = ANDROID / "ui" / "common" / "Hints.kt"
PREFS_KT = ANDROID / "core" / "HintPrefs.kt"
MAIN_KT = ANDROID / "MainActivity.kt"
LOGIN_KT = ANDROID / "ui" / "login" / "LoginViewModel.kt"
STYLE_DOC = ROOT / "docs" / "HINT_STYLE.md"
CATALOG = ROOT / "docs" / "PROJECT_MAP" / "09A_HINT_CATALOG.md"

# ── 反空转下限（分类器/扫描规则坏掉时先喊，不许安静地全绿）──────────────────
MIN_TEXTS = 300          # 抽到的界面文案
MIN_EXPLAIN = 30         # 认出来的解释句
MIN_HINT_CALLS = 20      # 走统一入口的调用
HINT_ONCE_MAX = 6        # 兼容壳的调用点数：**只许减不许增**

# ── 已知的未完成项（每条都要写理由；必须仍然命中，否则红了让你删掉它）────────
# 「防化石」：被点名的东西一旦被修好，这条就成了谎话 —— 那时这里必须红，
# 逼人回来删掉它，而不是留一句谁也不敢动的旧话。
#
# 历史（2026-09-21）：这里曾有一条 `("ui/profile/ProfileScreen.kt", "说三次就不说了", …)` ——
# 那个文件的「提示」副标题当时还写着旧机制的话，而文件正被另一会话改。用户拍板
# 「可以你现在就改吧」之后改掉了（副标题 → `显示所有说明` / `不显示说明`，并改用
# `setByUser()`），**这条也随之删除**（它已经命中不到，会当场红）。
PENDING: list[tuple[str, str, str]] = []


def strip_comments(src: str) -> str:
    """去掉 `//` 行注释与 `/* */` 块注释（**保留字符串字面量**，别把 URL 当注释切了）。"""
    out: list[str] = []
    i, n = 0, len(src)
    in_str = in_block = in_line = False
    while i < n:
        c = src[i]
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
            continue
        if in_block:
            if src.startswith("*/", i):
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_str:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(src[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if src.startswith("//", i):
            in_line = True
            i += 2
            continue
        if src.startswith("/*", i):
            in_block = True
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


class Checker:
    def __init__(self) -> None:
        self.n_ok = 0
        self.fails: list[tuple[str, str]] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.n_ok += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append((label, detail))
            print(f"  [!!]   {label}")
            if detail:
                print(f"         {detail}")

    def section(self, title: str) -> None:
        print(f"\n== {title} ==")


def read(path: Path) -> str:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read()


def main() -> int:
    c = Checker()

    # ── 0. 反空转：扫描本身得是活的 ────────────────────────────────────────
    c.section("0. 反空转（扫描规则被改坏时必须先喊）")
    rows, n_files = inv.collect()
    explain = [r for r in rows if r["cat"] == "EXPLAIN"]
    c.ok(f"扫到 {n_files} 个 .kt / {len(rows)} 条界面文案（下限 {MIN_TEXTS}）",
         n_files >= 60 and len(rows) >= MIN_TEXTS,
         "源码根路径或抽取规则是不是失效了？")
    c.ok(f"认出 {len(explain)} 条解释句（下限 {MIN_EXPLAIN}）", len(explain) >= MIN_EXPLAIN,
         "分类器被改坏的话，下面第 1、2 组会**空过**")

    # ── 1. 解释句必须走统一入口 ───────────────────────────────────────────
    c.section("1. 该走 Hint 的（解释句）不许裸着 Text")
    bare = [r for r in explain if r["call"] == "Text"]
    c.ok(f"裸露的解释句 = {len(bare)}（必须为 0）", not bare,
         "\n".join(f"         {r['file']}:{r['line']}  {r['text'][:56]}" for r in bare[:8])
         + "\n         修法：把那处 `Text(` 改成 `Hint(`（两者参数表逐一对齐，改名即可）")

    # ── 2. 不许把数据/状态挂到开关上（反向那条）────────────────────────────
    c.section("2. 不该走 Hint 的（数据/状态）不许走 Hint")
    by_call: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in rows:
        if r["call"] == "Hint":
            by_call[(r["file"], r["call_off"])].append(r)
    c.ok(f"走统一入口的调用 = {len(by_call)} 处（下限 {MIN_HINT_CALLS}）",
         len(by_call) >= MIN_HINT_CALLS, "一个 Hint 调用都没有？接口是不是被搬走了")
    pure_data = {k: v for k, v in by_call.items()
                 if not any(x["cat"] == "EXPLAIN" for x in v)}
    c.ok(f"「一次 Hint 调用里一段解释句都没有」的 = {len(pure_data)}（必须为 0）",
         not pure_data,
         "\n".join(
             f"         {k[0]}:{v[0]['line']}  {[x['cat'] for x in v]}  {v[0]['text'][:52]}"
             for k, v in sorted(pure_data.items())[:8])
         + "\n         这就是「关掉提示顺手把数据/状态也关了」——改回 `Text(`，"
           "并在 `_hint_inventory.OVERRIDE` 里写一句理由（如果分类器判错了）")

    # ── 3. 机制不许回退（**先剥注释**，KDoc 里提到旧名字是正常的）───────────
    c.section("3. 机制不许回退")
    for path in (HINTS_KT, PREFS_KT, MAIN_KT, LOGIN_KT):
        if not path.exists():
            c.ok(f"{path.name} 存在", False, "接口/机制文件被改名或删了？红线就没东西可查了")
            print("\n❌ 关键文件缺失，后面的判据全部跳过（不许安静地绿）")
            return 1
        c.ok(f"{path.name} 存在", True)

    prefs_code = strip_comments(read(PREFS_KT))
    old_mech = [w for w in ("MAX_TIMES", "markSeen", "hasLeft", "fun seen(") if w in prefs_code]
    c.ok(f"旧机制（每条最多 3 次的 per-key 计数）没有回来：{old_mech or '干净'}",
         not old_mech,
         "用户 2026-09-21 明确取消了那套机制；要恢复必须先问用户，并同步改 docs/HINT_STYLE.md")
    for name in ("fun onLogin(", "fun onAppStart(", "fun setByUser("):
        c.ok(f"HintPrefs.kt 有 {name.strip('fun ')}", name in prefs_code,
             "默认值语义（首次登录那一轮 / 冷启动自动关 / 手拨过不再自动改）就挂在这三个方法上")
    c.ok("HintPrefs.kt 里有「总开关」那个可观察状态（`by mutableStateOf(` 委托）",
         "by mutableStateOf(" in prefs_code,
         "开关要是不可观察的，拨一下不会让已打开的页面跟着变。"
         "⚠️ 判据必须看**委托写法**，不能只看有没有 `mutableStateOf` 这个词 —— "
         "`import ...mutableStateOf` 那行会让「名字在不在」这种判据永远成立（反向验证⑧抓到过）")

    hints_code = strip_comments(read(HINTS_KT))
    c.ok("三条行为决定在 HintRound（纯函数）里，HintPrefs 只负责落盘",
         all(f"HintRound.{m}(" in prefs_code for m in ("onLogin", "onAppStart", "setByUser")),
         "判断放回一个需要 Context 的类里，就只能靠真机点开关验证 —— "
         "而「第一次登录 / 下次冷启动 / 手拨过再登录」这三种顺序恰恰最难手工复现")
    c.ok("HintRound 的状态机有单测（HintRoundTest）",
         (ROOT / "android" / "app" / "src" / "test" / "java" / "com" / "tapmoay" / "sorders"
          / "core" / "HintRoundTest.kt").exists(),
         "行为契约没有测试钉着，下次重构就会被顺手改掉")
    c.ok("Hints.kt::Hint 读的是根上提供的那份开关（LocalHints.current）",
         "LocalHints.current" in hints_code, "读不到开关就等于永远显示")
    c.ok("Hints.kt::Hint 关掉时**短路返回**",
         bool(re.search(r"if\s*\(.*!prefs\.visible.*\)\s*return", hints_code)),
         "必须是真的不画，而不是画成透明的（透明的还会占位、还能被读到）")
    c.ok("Hints.kt 指向书写规范 docs/HINT_STYLE.md", "HINT_STYLE.md" in hints_code,
         "不指向规范的话，下一个人不知道判据在哪")

    main_code = strip_comments(read(MAIN_KT))
    c.ok("MainActivity 提供了 LocalHints（否则开关对所有页面失效）",
         re.search(r"CompositionLocalProvider\s*\(\s*LocalHints\s+provides", main_code) is not None,
         "开关的**唯一那一份**必须从根上提供下去")
    c.ok("MainActivity 冷启动会走 hintPrefs.onAppStart()（这就是「之后就默认关闭」）",
         "hintPrefs.onAppStart()" in main_code, "少了它，首次登录那一轮的开关永远不会自动关")
    c.ok("LoginViewModel 登录成功会走 hintPrefs.onLogin()（首次登录那一轮开）",
         "hintPrefs.onLogin()" in strip_comments(read(LOGIN_KT)),
         "少了它，新用户看不到任何说明")

    once_calls = [r for r in rows if r["call"] == "HintOnce"]
    c.ok(f"兼容壳 HintOnce 的调用点数 = {len(once_calls)}（上限 {HINT_ONCE_MAX}，只许减不许增）",
         len(once_calls) <= HINT_ONCE_MAX,
         "\n".join(f"         {r['file']}:{r['line']}" for r in once_calls)
         + "\n         新代码一律直接用 `Hint(...)`；壳上写着「迁完删掉」")
    # 只看**壳自己那段 KDoc**（不是全文件随便找"删掉"两个字）。
    # ⚠️ 这里要用**原始源码**（`hints_code` 已经把注释剥掉了，而这段交代就在注释里）。
    hints_raw = read(HINTS_KT)
    shell_at = hints_raw.find("fun HintOnce(")
    shell_doc = hints_raw[max(0, shell_at - 900):shell_at] if shell_at >= 0 else ""
    c.ok("Hints.kt 里那个壳的 KDoc 交代了「迁完就把它删掉」",
         shell_at >= 0 and "删掉" in shell_doc and "Hint(" in shell_doc,
         "没有这句话，下一个人会以为两种写法都行（判据只看 HintOnce 之前那段 KDoc）")

    # ── 4. 规范 + 已知未完成项（防化石）────────────────────────────────────
    c.section("4. 规范文档与已知未完成项")
    doc = read(STYLE_DOC) if STYLE_DOC.exists() else ""
    c.ok("docs/HINT_STYLE.md 存在", bool(doc), "书写规范没了，这套规矩就没有落点")
    c.ok("规范里写了三类身份（解释 / 数据 / 警告）",
         all(w in doc for w in ("解释句", "数据", "警告")), "三类身份是这套东西的核心判据")
    c.ok("规范里写了长度尺子（20 / 40 字）", "20" in doc and "40" in doc,
         "用户要求「过于冗长要精简，但不能丢句意语义」，尺子得写死")
    c.ok("规范里写了开关的默认值（首次登录那一轮）", "首次登录" in doc,
         "默认值是用户拍板的，改它要先问用户")

    for rel, frag, why in PENDING:
        target = ANDROID / rel
        code = read(target) if target.exists() else ""
        c.ok(f"待办仍然存在（{rel} 的「{frag}」）—— 修好后请删掉 PENDING 里这一条",
             frag in code, f"理由原文：{why}")

    # ── 5. 生成物新鲜度（委托给作者脚本，不在这里重写比对）────────────────────
    c.section("5. 目录文档是不是过期")
    if not CATALOG.exists():
        c.ok("docs/PROJECT_MAP/09A_HINT_CATALOG.md 存在", False,
             "修法：python _tools/qa/_hint_inventory.py --md")
    else:
        r = subprocess.run([sys.executable, str(Path(inv.__file__)), "--check"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = [ln for ln in (r.stdout or "").splitlines() if ln.strip()][-4:]
        c.ok("目录文档与源码一致（不是过期目录）", r.returncode == 0, "\n".join("         " + t for t in tail))

    # ── 汇总 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项未通过（通过 {c.n_ok} 项）：")
        for label, _ in c.fails:
            print(f"   - {label}")
        return 1
    print(f"✅ 全部 {c.n_ok} 项通过：解释句只走 Hint、数据/警告/状态永不隐藏、"
          f"总开关的机制没回退、规范与目录都在。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
