"""AI 空状态的「我是谁的助手」与推荐问题，是不是真按角色 × 阶段在变（CHG-0114）。

## 这个判据在防什么

用户 2026-10-11（m01175）看到货主页的空状态，说的是：
「我们 ai 那个**我是货主助手**要随着角色而发生改变啊。而目前只有 3 个派单元呃货主还有批发商
这 3 个就够了，然后我们对应的下面不是有预设的一些问题吗？这些问题要跟着角色来进行变的
比如说假如这个角色是第一次来那他应该会涉及到哪些问题……那我们其实也可以在设置当中
他自己手动的去编辑一些呃首次的问题预设」。

改之前，标题与那 4 条问题是 `ui/ai/AiChatScreen.kt` 里**两张写死的常量表**
（`SAMPLE_QUESTIONS_DISPATCHER` / `SAMPLE_QUESTIONS_SHIPPER`）加一句二元三元表达式
`if (isDispatcher) "我是派单助手" else "我是货主助手"`。于是：

- **批发商被当成普通货主**。他在后端不是独立角色（`AiRole` 只有 dispatcher/shipper），
  是 `shipper` ＋ `users.is_member=1`；写死的二元分支**认不出他**，
  他永远看到「帮我加一个常用地址」，而不是他最该问的「我的货主欠我多少」。
- **第一次来的人被当成老手**。他一条订单都还没有，却看到「我这个月的账结了吗？」——
  点下去只会得到一句"没查到"，而他不会点第二次。空状态是这一页的第一印象，
  第一印象给错，等于告诉他"这东西不是给你的"。

这一单把标题、首次档、整套问题都搬进 `ai/AiSuggest.kt`（纯数据 ＋ 纯函数，可单测），
把"固定 / 常用 / 用户自己编辑的首次预设"搬进 `ai/AiSuggestStore.kt`（本机 prefs，按用户分区）。

R4-BOUNDARY-JUSTIFICATION: 这一条**只能**靠机器判据。病不在任何一处逻辑里，而在
「两份内容各自写死、谁也不认识谁」：`AiRole` 枚举是后端契约的映射，**不能**为了界面
多一个批发商分支就去加第三个枚举值（那会让 `AiWrite.kt` 的权限映射、`AiRolePrompt` 的
提示词、后端 `role` 校验同时多一个必须维护的口径，且后端根本不认）；而"这个人是不是批发商"
只有在 `AiActor.memberShipper` 里才有答案，那是个**运行时**布尔值。
类型系统看不出"标题与问题表忘了跟着这个布尔值分叉"——改之前编译过、单测全绿、
真机点按也不报错。所以只能由一条静态判据钉住：**标题必须来自 `AiSuggestWho`，
问题必须来自 `AiSuggests`，界面文件里不许再有第二份写死的内容。**

## 检查什么

1. `ai/AiSuggest.kt` 存在，三类角色齐全、key 与标题都不重样；
2. 批发商是靠 `memberShipper` 分出来的（不是新增第四个 `AiRole`）；
3. 三套内容各自有 ≥3 个类别、首次档够摆满一屏；
4. `home()` 真的分"第一次来 / 用过"两档，`rank()` 把固定的排在前面；
5. `ui/ai/AiChatScreen.kt` 里**旧的两元标题与两张写死的问题表一个都不剩**；
6. 标题改成读 `who.title`，提示语按 `AiSuggestWho` 查表（三档齐全）；
7. 「典型问题」入口在输入框上方，**且不在 `showGuide` 分支里**（聊到一半也得能找到）；
8. 设置页能改首次预设（调 `setCustomFirst`），并能恢复默认；
9. `AiSuggestStore` 的 prefs 名带 scope 后缀（换账号不许看到上一个人的固定问题）；
10. 这套数据**不上传**（`AiSuggest*.kt` 里不许出现网络客户端）。
"""

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
UI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/ai"

SUGGEST_KT = AI / "AiSuggest.kt"
STORE_KT = AI / "AiSuggestStore.kt"
CONTAINER_KT = AI / "AiContainer.kt"
CHAT_KT = UI / "AiChatScreen.kt"
SETTINGS_KT = UI / "AiSettingsScreen.kt"
TEST_KT = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai/AiSuggestTest.kt"

#: 改之前写死在界面文件里的两张表 —— 它们**必须**已经搬走。
DEAD_CONSTS = ("SAMPLE_QUESTIONS_DISPATCHER", "SAMPLE_QUESTIONS_SHIPPER")

#: 旧的两元标题：批发商认不出来就是这一句造成的。
DEAD_TITLE = 'if (isDispatcher) "我是派单助手" else "我是货主助手"'

#: 初次档里"老手才问得出来"的那几条，⛔ 不许再出现在界面文件里。
DEAD_QUESTIONS = ("哪个司机这个月跑得最多", "我这个月的账结了吗")

_total = 0
_bad: list[str] = []


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8").read()


def ok(cond: bool, what: str) -> None:
    global _total
    _total += 1
    if cond:
        print(f"  ✅ {what}")
    else:
        print(f"  ❌ {what}")
        _bad.append(what)


def code_only(src: str) -> str:
    """去掉 KDoc / 行注释（判据锚在代码上，不锚在我们的说明文字上）。

    ⚠️ 不剥会当场假红：`AiChatScreen.kt` 这一段上面正大光明写着
    「示例问题原来就在这个位置写死成两张常量表」——裸子串扫描会把**说明**当成"表还在"。
    与 `_check_app_icon_green.py::code_only` 是同一个道理。
    """
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"//[^\n]*", "", src)


def main() -> int:
    print("=== AI 推荐问题按角色/阶段分档（CHG-0114） ===")

    for p in (SUGGEST_KT, STORE_KT, CHAT_KT, SETTINGS_KT):
        ok(p.exists(), f"{p.relative_to(ROOT).as_posix()} 存在")
    if _bad:
        print(f"\n❌ {len(_bad)}/{_total} 项不通过")
        return 1

    sug = read(SUGGEST_KT)
    sug_code = code_only(sug)
    store = read(STORE_KT)
    chat = read(CHAT_KT)
    chat_code = code_only(chat)
    settings = read(SETTINGS_KT)
    settings_code = code_only(settings)

    # ---------- 1. 三类角色 ----------
    for key in ("dispatcher", "shipper", "member"):
        ok(re.search(r'%s\(\s*"%s"' % (key.upper(), key), sug_code) is not None,
           f"AiSuggestWho 里有 {key}")

    titles = re.findall(r'^\s+(?:DISPATCHER|SHIPPER|MEMBER)\("[a-z]+", "[^"]+", "([^"]+)"\)',
                        sug_code, re.M)
    ok(len(titles) == 3, f"三类角色的标题都写了（实际 {len(titles)} 条）")
    ok(len(set(titles)) == len(titles), "三句标题互不重样（都叫「我是货主助手」等于没分）")
    ok(any("批发商" in t for t in titles), "批发商有自己的标题")

    # ---------- 2. 批发商不是第四个 AiRole ----------
    ok("memberShipper" in sug_code, "whoOf 读了 memberShipper（批发商靠它分，不靠 AiRole）")
    roles = read(AI / "AiWrite.kt")
    enum_block = re.search(r"enum class AiRole\b[\s\S]*?\n\}", roles)
    n_roles = len(re.findall(r'^\s+[A-Z]+\("', enum_block.group(0) if enum_block else "", re.M))
    ok(n_roles == 2, f"AiRole 仍只有两个后端角色（实际 {n_roles} 个）——批发商是运行时属性，不是第三个枚举值")

    # ---------- 3. 三套内容 ----------
    packs = re.findall(r"private val (\w+_PACK) = AiSuggestPack\(", sug_code)
    ok(len(packs) == 3, f"三套内容都有（实际 {len(packs)} 套：{', '.join(packs)}）")
    ok(sug_code.count("AiSuggestCategory(") >= 9,
       f"每套至少 3 个类别（共 {sug_code.count('AiSuggestCategory(')} 个）")
    ok("HOME_LIMIT = 4" in sug_code, "首页摆 4 条")
    ok("USED_MIN_TAPS = 2" in sug_code, "点过一次不算常用（USED_MIN_TAPS = 2）")

    # ---------- 4. 算法两条纪律 ----------
    ok("firstTimer" in sug_code and "customFirst" in sug_code,
       "home() 分「第一次来 / 用过」两档，并认用户自己编辑的预设")
    ok(re.search(r"fun rank\(", sug_code) is not None, "rank() 存在（固定 → 常用 → 默认）")
    rank_body = re.search(r"fun rank\([\s\S]*?\n    \}", sug_code)
    ok(rank_body is not None and "pinned" in rank_body.group(0).split("val ")[0],
       "rank() 先处理固定项")

    # ---------- 5. 界面里的旧写法必须没了 ----------
    ok("SAMPLE_QUESTIONS" not in chat_code,
       f"两张写死的问题表已搬走（{'/'.join(DEAD_CONSTS)}）")
    ok(DEAD_TITLE not in chat_code, "旧的两元标题已去掉（批发商不再被当成货主）")
    for q in DEAD_QUESTIONS:
        ok(q not in chat_code, f"「{q}」不在界面文件里（已归 AiSuggest）")

    # ---------- 6. 标题与提示语都按角色 ----------
    ok("who?.title" in chat_code, "标题读 AiSuggestWho.title")
    ok("HINT_BY_WHO" in chat_code, "输入框提示语按角色查表")
    hint = re.search(r"HINT_BY_WHO = mapOf\(([\s\S]*?)\n\)", chat_code)
    ok(hint is not None and hint.group(1).count("AiSuggestWho.") == 3,
       "提示语三档齐全（派单员/货主/批发商各一条）")

    # ---------- 7. 「典型问题」入口随时可用 ----------
    # ⛔ 关键：它必须挂在 **bottomBar** 里、InputBar 之前 —— 不能只在空状态里。
    # 用户要的是"不用每次自己组织句子"，而聊到一半想换个话题恰恰是最需要它的时候。
    ok("SuggestEntryRow(onOpen = {" in chat_code, "有「典型问题」入口")
    ok(chat_code.count("SuggestEntryRow(onOpen = {") == 1, "入口只画一处（重复画会叠两个按钮）")
    bar_at = chat_code.find("bottomBar = {")
    back = chat_code.find("SuggestEntryRow(onOpen = {")
    input_at = chat_code.find("InputBar(")
    ok(0 < bar_at < back < input_at, "入口在 bottomBar 里、就在输入框上方（不是只在空状态）")
    # 空状态自己也要能进面板（两条路都通：输入框上方那颗按钮 ＋ 空状态底部的「按类别挑问题」）。
    ok("onOpenLibrary = { showLibrary = true }" in chat_code,
       "空状态里也能打开面板")
    ok("SuggestLibrarySheet(" in chat_code, "面板本身画了")
    ok("AiSuggests.usedQuestions(" in chat_code, "面板顶部有「我常问的」区")

    # ---------- 8. 设置页能改 ----------
    ok("setCustomFirst(" in settings_code, "设置页能保存首次预设")
    ok("AiSuggests.defaultFirst(" in settings_code, "设置页能恢复默认")
    ok("AI 操作流水" in settings or "SectionCard" in settings, "设置页用的是本来就有的卡片版式")

    # ---------- 9. 存储纪律 ----------
    ok("sorders_ai_suggest" in store, "prefs 名是 sorders_ai_suggest")
    ok("PREFS_NAME + scope" in store, "prefs 名带 scope 后缀（换账号不许串）")
    ok("AiScope" in store or "scope" in store, "AiSuggestStore 认 scope")
    ok("suggests" in read(CONTAINER_KT), "AiContainer 暴露了 suggests")
    ok("ensureScoped()" in read(CONTAINER_KT).split("val suggests")[1][:120],
       "取 suggests 前会 ensureScoped（换账号要重建）")

    # ---------- 10. 不上传 ----------
    for name, src in (("AiSuggest.kt", sug), ("AiSuggestStore.kt", store)):
        ok(not re.search(r"\b(OkHttp|HttpURLConnection|Retrofit|apiClient|ApiClient)\b", src),
           f"{name} 不碰网络（这套偏好只存本机）")

    # ---------- 11. 单测 ----------
    ok(TEST_KT.exists(), "有单测")
    if TEST_KT.exists():
        t = read(TEST_KT)
        ok(t.count("@Test") >= 15, f"单测条数够（实际 {t.count('@Test')} 条）")
        for who in ("DISPATCHER", "SHIPPER", "MEMBER"):
            ok(f"AiSuggestWho.{who}" in t or f"AiRole.{who if who != 'MEMBER' else 'SHIPPER'}" in t,
               f"单测覆盖 {who}")

    print()
    if _bad:
        print(f"❌ {len(_bad)}/{_total} 项不通过：")
        for b in _bad:
            print(f"  - {b}")
        return 1
    print(f"✅ {_total}/{_total} 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
