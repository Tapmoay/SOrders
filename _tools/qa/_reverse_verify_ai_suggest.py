#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反向验证：CHG-0114 的 AI 推荐问题（入口 / 角色 / 首次档 / 习惯 / 固定）。

对 `_tools/qa/_check_ai_suggest.py` 的每一条主张，往源码里注入一处**真实的破坏**，
然后跑判据。判据必须**非零退出**、且失败清单里出现这条注入的期望关键词；
跑完按字节还原并比 sha256（反向验证不许把工作区留在注入状态）。

用法：
  python -X utf8 _tools/qa/_reverse_verify_ai_suggest.py            # 跑全部
  python -X utf8 _tools/qa/_reverse_verify_ai_suggest.py --list      # 只列用例
  python -X utf8 _tools/qa/_reverse_verify_ai_suggest.py 3 5        # 只跑第 3、5 条

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
病不在类型系统里：把标题写回 `if (isDispatcher) … else …`、把某条问题塞回界面文件、
把「预设」悬浮球的透明度改成 1.0、把点选入口改成直接发（不弹二次确认）—— 这些都能编译、
都能过单测（单测跑的是 `AiSuggests` 这些纯函数，界面里少一个按钮、少一次确认它不知道）。
「批发商被当成货主」这种错在真机上只表现为**一句文案不对**，没有异常、没有崩溃。
所以只能靠静态判据钉住源码里的这些形状，再用反向验证证明判据真的会红。
"""
import hashlib
import io
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
CHK = ROOT / "_tools" / "qa" / "_check_ai_suggest.py"
AI = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders" / "ai"
UIAI = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders" / "ui" / "ai"

SUG = AI / "AiSuggest.kt"
STORE = AI / "AiSuggestStore.kt"
CONT = AI / "AiContainer.kt"
WRITE = AI / "AiWrite.kt"
CHAT = UIAI / "AiChatScreen.kt"
SETTINGS = UIAI / "AiSettingsScreen.kt"

#: (标题, 文件, 原文, 换成, 第几次出现(1 起), 判据里必须冒出来的关键词)
CASES: list[tuple[str, Path, str, str, int, str]] = [
    ("批发商又被叫成货主",
     SUG, 'MEMBER("member", "批发商", "我是批发商助手"),',
     'MEMBER("member", "货主", "我是货主助手"),', 1, "互不重样"),
    ("派单员那档标题丢了（只剩两个角色）",
     SUG, 'DISPATCHER("dispatcher", "派单员", "我是派单助手"),',
     'DISPATCHER("dispatcher", "派单员"),', 1, "三类角色的标题都写了"),
    ("界面绕过 whoOf，回到「不是派单员就是货主」的两元标题",
     CHAT, 'Text(who?.title ?: "我是你的助手",',
     'Text(if (isDispatcher) "我是派单助手" else "我是货主助手",', 1, "旧的两元标题已去掉"),
    ("写死的问题表又塞回界面文件",
     CHAT, 'Text(who?.title ?: "我是你的助手",',
     'listOf("哪个司机这个月跑得最多").size\n    Text(who?.title ?: "我是你的助手",', 1, "不在界面文件里"),
    ("「预设」悬浮球被摘掉（又回到只有空状态才点得到问题）",
     CHAT, 'SuggestFab(onOpen = { showLibrary = true })',
     'Unit', 1, "有「预设」悬浮球"),
    ("悬浮球挪到屏幕正中（不再是右边缘那一条）",
     CHAT, 'floatingActionButtonPosition = FabPosition.End',
     'floatingActionButtonPosition = FabPosition.Center', 1, "悬浮球贴在右边缘"),
    ("悬浮球不再半透明（一直亮着挡视线）",
     CHAT, 'modifier = Modifier.alpha(0.55f).widthIn(min = 48.dp)',
     'modifier = Modifier.alpha(1.0f).widthIn(min = 48.dp)', 1, "闲着的时候是半透明的"),
    ("点操作卡片直接发出去（防误触的挂起没了）",
     CHAT, 'SuggestOpRow(op, { pending = op.say })',
     'SuggestOpRow(op, { onPick(op.say) })', 1, "点选入口只是把话挂起"),
    ("二次确认弹窗被换成别的（认不出是它了）",
     CHAT, 'title = { Text("就发这一句？") },',
     'title = { Text("确认") },', 1, "点预设卡片先弹二次确认"),
    ("二次确认自己画了一层裸弹窗（不走零件，也没有那张卡的性格）",
     CHAT, 'CardAlertDialog(', 'AlertDialog(', 1,
     "二次确认走零件（`CardAlertDialog`）"),
    ("置顶后看不出已经置顶（「已置顶」没了）",
     CHAT, 'if (isPinned) "已置顶" else "置顶",',
     'if (isPinned) "置顶" else "置顶",', 1, "图钉旁边写着「置顶」"),
    ("空状态进不去面板了",
     CHAT, 'onOpenLibrary = { showLibrary = true },',
     'onOpenLibrary = {},', 1, "空状态里也能打开面板"),
    ("换账号不重建 suggest store（串号）",
     CONT, 'val suggests: AiSuggestStore get() { ensureScoped(); return suggestStoreRef!! }',
     'val suggests: AiSuggestStore get() { return suggestStoreRef!! }', 1, "ensureScoped"),
    ("prefs 名被改掉（存量偏好全丢）",
     STORE, 'private const val PREFS_NAME = "sorders_ai_suggest"',
     'private const val PREFS_NAME = "ai_suggest"', 1, "prefs 名是 sorders_ai_suggest"),
    ("后端凭空多出第三个角色（批发商变成独立 role）",
     WRITE, 'DISPATCHER("dispatcher", "派单员"),',
     'DISPATCHER("dispatcher", "派单员"),\n    MEMBER("member", "批发商"),', 1, "仍只有两个后端角色"),
    ("whoOf 不看会员标记了（批发商掉回货主）",
     SUG, 'actor.memberShipper -> AiSuggestWho.MEMBER',
     'false -> AiSuggestWho.MEMBER', 1, "whoOf 读了 memberShipper"),
    ("设置页不再保存首次预设",
     SETTINGS, 'ai.suggests.setCustomFirst(',
     'ai.suggests.clear(', 1, "设置页能保存首次预设"),
    # ---- 左抽屉 ＋ 操作清单（两百多条铺得下的前提） ----
    ("左抽屉被换回底部弹层（两百多条又摊成一长条）",
     CHAT, 'ModalNavigationDrawer(',
     'ModalBottomSheet(', 2, "面板是左抽屉"),
    ("把一条动作 id 抄死进界面文件（AI 加了新动作这里就瞎了）",
     SUG, 'AiSuggestSection("我常问的"',
     'AiSuggestSection("orders.assign"', 1, "没有抄死的动作 id"),
    ("类别不按注册表的域排，改成按动作 id 排",
     SUG, 'actions.groupBy { it.group }',
     'actions.sortedByDescending { it.id }.groupBy { it.group }', 1, "操作按注册表自己的 group 分组"),
    ("批发商又被当成普通货主（会员标记丢了）",
     SUG, 'memberShipper = true',
     'memberShipper = false', 1, "批发商仍然是货主 + memberShipper"),
]


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def sub(path: Path, old: str, new: str, idx: int) -> None:
    """把 path 里第 idx 次（1 起）出现的 old 换成 new；写回并保 LF。"""
    txt = io.open(path, encoding="utf-8", newline="").read()
    if idx <= 0:
        raise AssertionError(f"用例索引必须 >= 1：{path}")
    seen = 0
    out, pos = [], 0
    while True:
        at = txt.find(old, pos)
        if at < 0:
            break
        seen += 1
        if seen == idx:
            out.append(txt[pos:at])
            out.append(new)
            pos = at + len(old)
            break
        out.append(txt[pos:at + len(old)])
        pos = at + len(old)
    if seen < idx:
        raise AssertionError(f"源码里找不到第 {idx} 处 `{old[:60]}`：{rel(path)}")
    out.append(txt[pos:])
    io.open(path, "w", encoding="utf-8", newline="").write("".join(out))


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-X", "utf8", str(CHK)],
                       capture_output=True, cwd=str(ROOT))
    txt = p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")
    return p.returncode, txt


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if "--list" in args:
        for i, (title, path, *_rest) in enumerate(CASES, 1):
            print(f"{i:>2}. {title}  [{rel(path)}]")
        return 0
    picked = {int(a) for a in args if a.isdigit()} or set(range(1, len(CASES) + 1))

    rc, txt = run_check()
    if rc != 0:
        print("⛔ 反向验证开始前判据就是红的 —— 先把判据修绿再跑。")
        print(txt[-2000:])
        return 2
    print("基线：判据 ✅（未注入时是绿的）")

    files = sorted({c[1] for c in CASES})
    before = {f: f.read_bytes() for f in files}

    bad, ran = [], 0
    for i, (title, path, old, new, idx, want) in enumerate(CASES, 1):
        if i not in picked:
            continue
        ran += 1
        try:
            sub(path, old, new, idx)
        except AssertionError as e:
            bad.append(f"第 {i} 条「{title}」注入失败：{e}")
            path.write_bytes(before[path])          # 还原
            continue
        rc, txt = run_check()
        if rc == 0:
            bad.append(f"第 {i} 条「{title}」：注入了破坏，判据却还是绿的 ❌")
        elif want and want not in txt:
            bad.append(f"第 {i} 条「{title}」：判据红了，但失败清单里没有「{want}」")
        else:
            print(f"  ✅ {i:>2}. {title}")
        path.write_bytes(before[path])              # ⛔ 每条跑完立刻还原，下一条从干净源码出发

    # 逐字节还原 + sha256 比对
    drift = []
    for f, raw in before.items():
        if f.read_bytes() != raw:
            drift.append(rel(f))
    if drift:
        bad.append("注入后没能逐字节还原：" + "、".join(drift))
    else:
        print(f"还原：{len(before)} 个被注入文件与注入前逐字节一致 ✓")

    print()
    if bad:
        print(f"❌ {len(bad)} 条不合格（共跑 {ran} 条）：")
        for b in bad:
            print("  - " + b)
        return 1
    print(f"✅ {ran}/{ran} 条注入都让判据红了，且期望关键词都出现")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
