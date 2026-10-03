"""反向验证 CHG-0031（关键解释句四族不许被说明开关藏掉）那批修复**真的在检查**。

2026-10-04 用户点名：吃透「说明（Hint）」机制的取舍规则（**不重要的 / 繁琐的信息才隐藏或简化**），
把被误判为可隐藏的关键解释句找出来。修法是「四族词表（钱的口径 / 不可逆的后果 / 隐私与费用 /
当前状态的含义）进分类器 + 二十句从 Hint 改成常显 Text + 既有红线 `_check_hints.py` 加第 2b 组」，
这份脚本逐条把修复撤回，证明对应的检查（新判据 / 既有红线）会红。

| 注入 | 应该红的检查 |
|---|---|
| 词表里某一族被摘掉 / key_family 报废 | 新判据（词表那几项） |
| classify 不再认四族 | 新判据（classify 那一支） |
| 红线的第 2b 组下限改 0 / 不再用那份词表 | 新判据（判据侧那两项） |
| 四处关键句改回 Hint（账本口径 / 付款流水 / API Key 隐私 / 编辑横幅） | 既有红线第 2b 组 |
| 规范里的族名或拆句做法被删 | 新判据（规范那两项） |
| 改动文档 / 登记表 / 认领簿缺一件 | 新判据（文档与登记） |
| 本脚本自己的节点标记被削短 | 新判据（注入条数那一项） |

⚠️ 快照/还原按**字节**做（仓库里有 CRLF 文件），跑完逐字节核对。
⚠️ 跑的时候拿着注入锁（_airepo.lock_reverse_verify）：并发的检查会拒绝出结论。
⚠️ 只动源码与文档，不跑 gradle、不碰 android/app/build —— 跑完不必重启后端。

用法：python _tools/qa/_reverse_verify_hint_key_explain.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools/ai"))

from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = ROOT / "_tools/qa/_check_hint_key_explain.py"
HINTS = ROOT / "_tools/qa/_check_hints.py"
INV = "_tools/qa/_hint_inventory.py"
HINTS_SRC = "_tools/qa/_check_hints.py"
STYLE = "docs/HINT_STYLE.md"
DOC = "docs/changes/CHG-0031.md"
README = "docs/changes/README.md"
CLAIM = "docs/AI_WORK_CLAIM.md"
SELF = "_tools/qa/_reverse_verify_hint_key_explain.py"
AI_SET = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiSettingsScreen.kt"
AI_CHAT = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatScreen.kt"
LEDGER = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperLedgerScreen.kt"
SUPPLIERS = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/SuppliersScreen.kt"

#: 第 2b 组那两条判词（HINTS: 节点拿它判断"是不是这一组红的"）
WANT_HIDDEN = "被挂到开关上的关键解释句"
WANT_FLOOR = "条关键解释句（下限"


def rehide(text: str, sentence: str) -> str:
    """把某句话所在的 Text( 改回 Hint( —— 从这句话往回找最近的一次调用（不看缩进）。"""
    i = text.find(sentence)
    if i < 0:
        return text
    j = text.rfind("Text(", 0, i)
    if j < 0:
        return text
    return text[:j] + "Hint(" + text[j + len("Text("):]

CASES: list[tuple[str, str, object, str]] = [
    (
        "① 词表里「钱的口径」这一族被摘掉",
        INV,
        lambda s: s.replace('    "钱的口径": CALIBER_WORDS,', '    "钱的口径": (),', 1),
        "JUDGE:key_family() 认得出「钱的口径」的合成例句",
    ),
    (
        "② 词表里「隐私与费用」这一族整行删掉",
        INV,
        lambda s: s.replace('    "隐私与费用": PRIVACY_COST_WORDS,\n', "", 1),
        "JUDGE:key_family() 认得出「隐私与费用」的合成例句",
    ),
    (
        "③ key_family() 报废（哪一族都认不出）",
        INV,
        lambda s: s.replace("for name, words in KEY_FAMILIES.items():", "for name, words in []:", 1),
        "JUDGE:key_family() 认得出「当前状态的含义」的合成例句",
    ),
    (
        "④ classify() 不再把四族挡在 EXPLAIN 外面",
        INV,
        lambda s: s.replace("elif key_family(t) is not None:", "elif False:", 1),
        "JUDGE:classify() 里有 key_family(t) 那一支",
    ),
    (
        "⑤ 红线第 2b 组的下限被改成 0（空过）",
        HINTS_SRC,
        lambda s: s.replace("MIN_KEY_SENTENCES = 15", "MIN_KEY_SENTENCES = 0", 1),
        "JUDGE:下限 MIN_KEY_SENTENCES",
    ),
    (
        "⑥ 红线第 2b 组不再用那份词表（句子一条也认不出）",
        HINTS_SRC,
        lambda s: s.replace('keys = [r for r in rows if inv.key_family(r["text"]) is not None]', "keys = []", 1),
        "JUDGE:那一组用的是同一份词表",
    ),
    (
        "⑦ 红线修法里不再交代拆句",
        HINTS_SRC,
        lambda s: s.replace("拆句", "分成两句"),
        "JUDGE:修法里交代了拆句",
    ),
    (
        "⑧ 账本口径那句（只记在你自己这一本账上）改回 Hint",
        LEDGER,
        lambda s: rehide(s, "只记在你自己这一本账上 —— 公司那边的账不会变。"),
        "HINTS:" + WANT_HIDDEN,
    ),
    (
        "⑨ 付款流水那句（拆出来的那条 Text）改回 Hint",
        SUPPLIERS,
        lambda s: rehide(s, "付款一笔一笔记，一张单可以分很多次付；每付一次都会写一行资金流水，"),
        "HINTS:" + WANT_HIDDEN,
    ),
    (
        "⑩ API Key 隐私与费用那句改回 Hint",
        AI_SET,
        lambda s: rehide(s, "API Key 加密存在本机、不上传；费用你自己承担。"),
        "HINTS:" + WANT_HIDDEN,
    ),
    (
        "⑪ 编辑横幅那句（这条之后的对话会被撤掉）改回 Hint",
        AI_CHAT,
        lambda s: rehide(s, "这条之后的对话会被撤掉"),
        "HINTS:" + WANT_HIDDEN,
    ),
    (
        "⑫ 规范里「隐私与费用」这一族被改名（全篇都不再提）",
        STYLE,
        lambda s: s.replace("隐私与费用", "隐私开销"),
        "JUDGE:里写了「隐私与费用」",
    ),
    (
        "⑬ 规范里不再交代拆句的做法",
        STYLE,
        lambda s: s.replace("拆句", "分成两句"),
        "JUDGE:规范里交代了拆句的做法",
    ),
    (
        "⑭ 改动文档少一节（① 被抹掉）",
        DOC,
        lambda s: s.replace("## ① ", "## 一、", 1),
        "JUDGE:九节齐全",
    ),
    (
        "⑮ 登记表里 CHG-0031 那一行不见了",
        README,
        lambda s: s.replace("CHG-0031", "CHG-XXXX"),
        "JUDGE:登记表 docs/changes/README.md 里有 CHG-0031 那一行",
    ),
    (
        "⑯ 认领簿里的 CHG-0031 块不见了",
        CLAIM,
        lambda s: s.replace("CHG-0031", "CHG-XXXX"),
        "JUDGE:认领簿 docs/AI_WORK_CLAIM.md 里有 CHG-0031 的块",
    ),
    (
        "⑰ 本脚本自己的节点标记被削短（注入条数那一项要红）",
        SELF,
        lambda s: s.replace('"JUDGE:', '"XJUDGE:'),
        "JUDGE:注入 ≥12 条",
    ),
]



def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_script(p: Path) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(p)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def hit(out: str, want: str, mark: str) -> bool:
    return any(mark in ln and want in ln for ln in out.splitlines())


def run_all() -> int:
    fails: list[str] = []
    code, out = run_script(JUDGE)
    if code != 0:
        print("❌ 前提不成立：源码完好时新判据就没过")
        print(out[-1500:])
        return 1
    code, out = run_script(HINTS)
    if code != 0:
        print("❌ 前提不成立：源码完好时红线 _check_hints.py 就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时新判据与红线 _check_hints.py 都是绿的")

    touched = sorted({rel for _l, rel, _m, _n in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate, node in CASES:
        path = ROOT / rel
        plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
            continue
        try:
            write_src(path, mutated, crlfs[rel])
            kind, want = node.split(":", 1)
            rcode, rout = run_script(HINTS if kind == "HINTS" else JUDGE)
            if kind == "HINTS":
                hit_now = rcode != 0 and hit(rout, want, "[!!]")
            else:
                hit_now = rcode != 0 and hit(rout, want, "[FAIL]")
        finally:
            path.write_bytes(originals[rel])
        kind_name = "红线 _check_hints.py" if kind == "HINTS" else "新判据"
        if hit_now:
            print("  [OK] " + label + " → " + kind_name + "报红")
        else:
            fails.append(label + "：注入之后没有任何检查报红（修复没有被钉住）")
            print("  [MISS] " + label + " → 全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print("✅ 还原检查：" + str(len(touched)) + " 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print("✅ " + str(len(CASES)) + " 条注入都证明 CHG-0031 的修复真的被钉住了。")
    return 0


def main() -> int:
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    sys.exit(main())
