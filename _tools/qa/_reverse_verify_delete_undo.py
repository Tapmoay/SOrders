# -*- coding: utf-8 -*-
r"""反向验证「删了必须能当场撤回」这条红线**真的会红**（CHG-0015，2026-10-03）。

## 为什么这条要反向验证
这条红线的判据分成三层，每一层都有自己典型的失效方式：

1. **清单自己算**（扫 `ui/` 下所有 `repo.deleteX(` 要求同文件有 `repo.restoreX(`）：清单一旦缩水，
   「一个违规都没有」和「一个都没扫到」就是同一个输出。本脚本往一个**没有**还原入口的文件里再塞一个删除点，
   逼清单把它认出来。
2. **豁免表只能收紧**（每条都要求「那个调用点还在、且仍然没有配对的 restore」）：一张永远成立的豁免表
   等于没有判据。本脚本从表里挑一条，把它的还原补上 —— 那一条必须当场报红（欠账还清了就得销账）。
3. **撤回链路本身**（记一条 → 界面画一行 → 点撤销走 restore）：任何一环断了都**不影响编译**，
   最好的证据是「注释还在、代码没了」。本脚本把这条链一环一环拆开：状态拿掉、记录少一处、
   kind 写错、when 少一个分支、restore 换成 delete、界面那行整块删、位置挪到列表后面、
   动作改个名、词换成一个近义词。

⚠️ 快照 / 还原按**字节**做，跑完逐字节核对（本项目栽过「注入把 bug 留在源码里」）。

用法：python _tools/qa/_reverse_verify_delete_undo.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_delete_undo.py"

AND = "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND + "/ui/shipper/AddressScreen.kt"
VM = AND + "/ui/shipper/AddressViewModel.kt"
REPO = AND + "/data/repo/AppRepository.kt"
ACCOUNT = AND + "/ui/dispatcher/AccountManageViewModel.kt"
PRICE = AND + "/ui/dispatcher/PriceMatrixViewModel.kt"
DOC = "docs/changes/CHG-0015.md"
REGISTRY = "docs/changes/README.md"

BT = chr(96)  # 反引号（本文件里出现反引号会把外面的模板串截断，一律用这个拼）

#: 界面那一行撤回提示：起止锚点（整块挪走 / 整块删掉都要用）
#: ⚠️ 2026-10-03：这一段在 CHG-0024 之后被外层又包了一层 Column，缩进从 12 空格变成 20 空格，
#:    写死空格数的锚点当场腐烂 —— ① ② 两条注入直接 SKIP，而判据自己还以为绿着。
#:    所以这里跟 _check_delete_undo.py:72 的 LIST_ANCHOR 学：**只认内容，不认缩进**。
UNDO_START_TEXT = "vm.recentlyDeleted?.let { rd ->"
UNDO_END_TEXT = "HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)"
LIST_ANCHOR_TEXT = "Box(Modifier.weight(1f)) {"


def undo_span(s: str) -> tuple[int, int]:
    """撤回提示那一整块在 s 里的 [起, 止)（含收尾那一行和它的换行）；形态不对就给 (-1, -1)。

    起：`vm.recentlyDeleted?.let { rd ->` 那一行的行首；
    止：它收尾那个单独的 `}` 那一行的行尾。
    ⛔ 别退回「写死 20 个空格」那种写法 —— 外层再包一层就又腐烂一遍。
    """
    i = s.find(UNDO_START_TEXT)
    if i < 0:
        return -1, -1
    i = s.rfind("\n", 0, i) + 1
    j = s.find(UNDO_END_TEXT, i)
    if j < 0:
        return -1, -1
    j = s.find("\n", j) + 1
    close = s.find("\n", j)
    close = len(s) if close < 0 else close
    if s[j:close].strip() != "}":
        return -1, -1
    return i, close + 1


def drop_undo_block(s: str) -> str:
    """① 把撤回提示那一整块删掉（注释还在、代码没了）。"""
    i, j = undo_span(s)
    return s if i < 0 else s[:i] + s[j:]


def drop_line(s: str, needle: str) -> str:
    """整行删掉（表格、单行声明）。"""
    return "\n".join(ln for ln in s.split("\n") if needle not in ln)


def drop_block(s: str, needle: str, n: int = 3) -> str:
    """从含 needle 的那一行起整块删掉 n 行（记「刚删的那条」是 3 行）。"""
    lines = s.split("\n")
    for i, ln in enumerate(lines):
        if needle in ln:
            return "\n".join(lines[:i] + lines[i + n :])
    return s


def move_undo_after_list(s: str) -> str:
    """把撤回提示整块挪到列表容器**之后**（界面完全一样，只是「手边」不成立了）。"""
    i, e = undo_span(s)
    if i < 0 or LIST_ANCHOR_TEXT not in s:
        return s
    block, rest = s[i:e], s[:i] + s[e:]
    k = rest.find(LIST_ANCHOR_TEXT)
    k = rest.find("\n", k) + 1  # 挪到列表容器那一整行之后
    return rest[:k] + block + rest[k:]


#: (说明, 相对路径, 替换函数, 期望在输出里出现的关键词 —— 空串 = 只要非零退出)
CASES: list[tuple[str, str, object, str]] = [
    (
        "① 界面那行撤回提示整块被删（注释还在、代码没了 —— 最典型的假绿）",
        SCREEN,
        drop_undo_block,
        "页面上画了撤回入口",
    ),
    (
        "② 那行提示被挪到列表容器**之后**（界面一样，长列表里就看不见了）",
        SCREEN,
        move_undo_after_list,
        "提示画在列表容器",
    ),
    (
        "③ 「撤销」被换成近义词「撤回」（同一个页面上还有「撤回订单」，会混）",
        SCREEN,
        lambda s: s.replace('Text(\"撤销\")', 'Text(\"撤回\")', 1),
        "界面上写的是「撤销」",
    ),
    (
        "④ 「刚删的那条」这个状态被拿掉（撤回就没有主语了）",
        VM,
        lambda s: drop_line(s, "var recentlyDeleted by mutableStateOf<RecentlyDeleted?>(null)"),
        "刚删的那条",
    ),
    (
        "⑤ undoDelete() 这个动作改名（界面调的还是老名字）",
        VM,
        lambda s: s.replace("fun undoDelete()", "fun undoRemove()", 1),
        "有 undoDelete() 这个动作",
    ),
    (
        "⑥ 线路那一处删除不再记「刚删的那条」（删完不给人撤回路）",
        VM,
        lambda s: drop_block(s, "recentlyDeleted = RecentlyDeleted(", 3),
        "三处删除都记了",
    ),
    (
        "⑦ 记下的 kind 写成了别的字（line → route：分支永远匹配不上）",
        VM,
        lambda s: s.replace('kind = \"line\", label = \"常用线路\"', 'kind = \"route\", label = \"常用线路\"', 1),
        "kind 集合",
    ),
    (
        "⑧ undoDelete 少一个 when 分支（有一类删了撤不回来）",
        VM,
        lambda s: drop_line(s, '\"place\" -> container.repo.restoreLocation(rd.id)'),
        "kind 集合",
    ),
    (
        "⑨ 「撤销」调的还原接口被换成删除接口（点一下又删一次）",
        VM,
        lambda s: s.replace("container.repo.restoreAddress(rd.id)", "container.repo.deleteAddress(rd.id)", 1),
        "restoreAddress",
    ),
    (
        "⑩ 仓库层的还原接口被删掉一个（界面上凭空写的）",
        REPO,
        lambda s: drop_line(s, "suspend fun restoreLocation("),
        "仓库层三个还原接口",
    ),
    (
        "⑪ 一个页面里又多了一个没有配对的删除点（清单必须自己把它认出来，不能靠豁免表）",
        ACCOUNT,
        lambda s: s + "private fun _reverseProbe() { container.repo.deleteWidget(1L) }\n",
        "这些删了就找不回来",
    ),
    (
        "⑫ 豁免表里的一条欠账被偷偷补上（销账不销行 → 空转的豁免）",
        PRICE,
        lambda s: s + "private fun _reverseProbe() { container.repo.restorePriceRule(1L) }\n",
        "把行删掉",
    ),
    (
        "⑬ 登记簿里 CHG-0015 那一行被撤",
        REGISTRY,
        lambda s: drop_line(s, "| " + BT + "CHG-0015" + BT + " |"),
        "没登记",
    ),
    (
        "⑭ 文档少一节（九节是 _check_dev_spec 与本判据共同的底线）",
        DOC,
        lambda s: s.replace("## ⑨", "", 1),
        "文档缺节",
    ),
]


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    touched = sorted({rel for _l, rel, _m, _e in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate, expect in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        crlf = b"\r\n" in original_bytes
        plain = original_bytes.decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)  # type: ignore[operator]
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
            continue
        try:
            out_txt = mutated.replace("\r\n", "\n")
            if crlf:
                out_txt = out_txt.replace("\n", "\r\n")
            path.write_bytes(out_txt.encode("utf-8"))
            code, out = run_check()
        finally:
            path.write_bytes(original_bytes)
        hit = code != 0 and (not expect or expect in out)
        if hit:
            print("  [OK] " + label + " → 报红")
        else:
            fails.append(label + f"：注入之后没有按预期报红（退出码 {code}，期望关键词「{expect}」）")
            print("  [MISS] " + label + " → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())