"""反向验证「确认卡文案不许写 Markdown」这条检查**真的会红**。

### 为什么值得单独一个脚本
这条检查是 v3.16 真机实测补的：拆单卡片上出现了字面的 `**撤不回来**`。
补上之后它一次抓出 **5 处**漏（其中 4 处是更早几轮就写进去的）——说明这类问题
"写的时候对、后来改坏"的概率不低，而**单测、编译都看不见**（它们管逻辑不管字面量）。
所以它必须有一份"注入 bug 就报错"的证据。

用法：python _tools/ai/_reverse_verify_card_markdown.py     # 3/3 都红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_ai_guardrails.py"
ORDER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteOrderHandlers.kt"
BASIC = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteBasicHandlers.kt"
SETTLE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteSettlementHandlers.kt"
NOTIFY = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteNotificationHandlers.kt"
PRICING = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWritePricing.kt"
# 核销回调那条路（2026-09-21：它的明细块里藏着一处"旧扫描永远扫不到"的字面星号）
SHIPPER = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteShipperLedgerHandlers.kt"
SERVICE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt"
# v3.44：撤回卡与「撤不回来」的理由也在确认卡上（`none(...)` / `AiInverse.lines` /
# `restoreLines`），而这份文件**不匹配 `AiWrite*` 前缀**——真机上就是它印出了字面星号
# （重排商品分类的确认卡最后一行 `**整份名册的顺序**`，截图 _archive/ai-e2e-v343/t3-02-card.png）。
REVERT = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiRevert.kt"
# 资源表（撤回卡文案 + 「逆操作是谁」都在这里声明）
RESOURCES = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiResources.kt"
# 确认卡的**渲染处**：信息区是"表格"还是"逐行纯文本"就看这一行（2026-09-20）
CHAT = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatScreen.kt"


def read_src(p: Path):
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out



def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**（R3-07b）：写回后**重新读回来比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的内容 == 快照 才是（L2 要的就是这一句）。
    # 实测教训（2026-09-26）：有份反向验证的还原写的是**另一个文件的字节**，而它自己那句核对
    # 比的也是同一份错字节 ⇒ 恒等通过，把两个源码文件整份写坏。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

def run_check() -> str:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return (r.stdout or "") + (r.stderr or "")


MUTATIONS = [
    (
        "手写处理器的 details 里塞回 Markdown 星号",
        ORDER,
        'add("原单会变成「已撤销」留痕——撤不回来，要合并只能重新建单")',
        'add("原单会变成「已撤销」留痕——**撤不回来**，要合并只能重新建单")',
        "AiWriteOrderHandlers.kt 的卡片文案里没有 Markdown 星号",
    ),
    (
        "内联 offer 的 detailLines 里塞回 Markdown 星号（另一种造卡形状）",
        BASIC,
        'add("日期：$expDate")',
        'add("日期：**$expDate**")',
        "AiWriteBasicHandlers.kt 的卡片文案里没有 Markdown 星号",
    ),
    (
        # v3.32：这条注入原来打的是"details 改名 → 检查必须报错"。
        # 检查已经改成按 `summary→payload` 区间取文案（不再认 details 的写法），
        # 于是那个注入不再代表任何失败模式了——换成**打在新判据上**的注入：
        # 卡片定位的唯一锚点是 `summary = `，把它改名，检查必须自己先报错
        # （"清单过期了要先报错，而不是安静地什么都不查"）。
        "卡片的锚点被改名（`summary = ` → `cardSummary = `）——定位计数必须报错",
        PRICING,
        'summary = "按表格调价：${rows.size} 行 · ${planned.size} 条价格",',
        'cardSummary = "按表格调价：${rows.size} 行 · ${planned.size} 条价格",',
        "卡片文案块都定位到了",
    ),
    (
        # v3.32 补的：详情行**先攒在变量里**再传进去的那种写法。
        # 旧检查只认 `buildList { }`，于是这种文件的卡片文案**从来没被扫过**——
        # 而按表格调价的卡片上一直印着字面的 `**仍然会执行**`（真机上被看见才发现）。
        "先攒变量形态的卡片文案里塞回 Markdown 星号（旧检查根本没扫到这种形状）",
        PRICING,
        'details += "⚠️ 会覆盖这些批发商已有的专属价（没有专属价的会新建一条）"',
        'details += "⚠️ 会覆盖这些批发商**已有的专属价**（没有专属价的会新建一条）"',
        "AiWritePricing.kt 的卡片文案里没有 Markdown 星号",
    ),
    (
        # v3.32 补的第二个出口：**执行完之后那句反馈**（Done 消息 / commitNote）。
        # 它和卡片是两个不同的渲染点，以前一处都没查过——
        # 实测抓到过「⚠️ 这次**没能挂上「撤回」**…」。
        "执行结果文案（Done / commitNote）里塞回 Markdown 星号（另一个出口）",
        SERVICE,
        # ⚠️ 2026-09-24 第 35 轮：这段用户可见的话术改过（把"挂不上撤回"的两种成因都说出来，
        #    第 25 轮 01 区 F2）—— 按本仓库的规矩**只改锚点、注入的判据一字未动**。
        'append("\\n⚠️ 这次没能挂上「撤回」。两种常见原因：")',
        'append("\\n⚠️ 这次**没能挂上「撤回」**。两种常见原因：")',
        "结果文案",
    ),
    # ⚠️ 下面两条针对的是 v3.20 抓到的"检查文件清单是手写的"那个坑：
    # 这两个文件（结算 v3.20 / 消息 v3.19）在旧清单里**根本不在**，
    # 星号漏进去也不会红（真机上真的漏了 10 处）。它们红了才说明"清单改成算出来的"生效了。
    (
        "结算处理器的卡片里塞回 Markdown 星号（旧清单根本没扫这个文件）",
        SETTLE,
        'add("这是一张草稿：还没有锁住任何账单，可以作废")',
        'add("这是一张**草稿**：还没有锁住任何账单，可以作废")',
        "AiWriteSettlementHandlers.kt 的卡片文案里没有 Markdown 星号",
    ),
    (
        "消息处理器的卡片里塞回 Markdown 星号（旧清单根本没扫这个文件）",
        NOTIFY,
        'add("删了就没了（收不回来）")',
        'add("**删了就没了**（收不回来）")',
        "AiWriteNotificationHandlers.kt 的卡片文案里没有 Markdown 星号",
    ),
    (
        # ⚠️ v3.44：这一条钉的是**真机实测抓到的第 4 次同类事故**——重排商品分类的确认卡
        #    最后一行印着字面的 `**整份名册的顺序**`，而当时所有卡片文案检查**全绿**：
        #    它们的文件清单是 `AI.glob("AiWrite*.kt")`，而 `AiRevert.kt` 不匹配这个前缀。
        "撤回卡的理由里塞回 Markdown 星号（AiRevert.kt 以前根本不在清单里）",
        REVERT,
        '"重排改的是「整份名册的顺序」（不是某一条记录的一个字段），撤回要把原来那一份顺序"',
        '"重排改的是「整份名册的顺序」（不是某一条记录的一个字段），撤回要把原来那一份顺序**整份**"',
        "AiRevert.kt（撤回卡 / 撤不回来的理由）里没有 Markdown 星号",
    ),
    (
        "撤回卡明细行里塞回 Markdown 星号（同一个文件的另一个出口）",
        REVERT,
        'add("增减量按「相反方向再记一条」来撤回，原来那条流水留着——流水本来就该留痕。")',
        'add("增减量按**相反方向再记一条**来撤回，原来那条流水留着——流水本来就该留痕。")',
        "AiRevert.kt（撤回卡 / 撤不回来的理由）里没有 Markdown 星号",
    ),
    (
        # ⚠️ v3.44：第一次修 ③e 时只 glob 了 `AiRevert*.kt`，**又漏了 `AiResources.kt`**
        #    （同一个坑的第 5 次，是真机 E2E 报告点出来的：那里还有 7 处字面星号）。
        #    现在清单按**内容**算，这条注入钉的就是"资源表也在被扫"。
        "资源表里的撤回卡文案塞回 Markdown 星号（AiResources.kt 以前也不在清单里）",
        RESOURCES,
        'lines = listOf("按刚才撤回时记下的司机、运费、收款方式，「重新派一次」")',
        'lines = listOf("按刚才撤回时记下的司机、运费、收款方式，「**重新派一次**」")',
        "AiResources.kt（撤回卡 / 撤不回来的理由）里没有 Markdown 星号",
    ),
    (
        # ⚠️ 真机实测抓到的**结构 bug**：`vehicle.set_driver` 被声明成"自己配自己"的成对动作，
        #    而 `pairedPlan` 第一行就排除自逆 → 撤回方案永远造不出来，卡片却敢印「会出现撤回」。
        #    这条注入把另一对正常的成对动作改成自逆，检查必须报红。
        "把成对动作的逆操作改成它自己（撤回永远造不出来，而卡片照样承诺）",
        RESOURCES,
        "paired(AiWrites.CONTACT_RESTORE, AiInverse(AiWrites.CONTACT_DELETE,",
        "paired(AiWrites.CONTACT_RESTORE, AiInverse(AiWrites.CONTACT_RESTORE,",
        "没有任何动作把逆操作声明成它自己",
    ),
    (
        # 2026-09-20：卡片**信息区**改成表格显示（用户：「所有卡片…尽量都使用表格的形式…
        # 核心目标是将信息正确且明显地展示出来」）。这条注入把它退回"逐行画纯文本"
        # ——正是用户嫌看不清的那个形态，检查必须报红。
        "卡片信息区退回「逐行画纯文本」（用户嫌看不清的那个形态）",
        CHAT,
        "                CardInfoTable(p.detailLines)",
        "                p.detailLines.forEach { line ->\n"
        "                    Text(line, style = MaterialTheme.typography.bodySmall)\n"
        "                }",
        "卡片信息区不许退回「逐行画纯文本」",
    ),
    (
        # ⚠️ 2026-09-21 找到的**扫描盲区**：`summary = ` 到 `payload = ` 的区间只要碰到一个
        #    "单独成行的 `)`"就提前收尾，这一行之后的明细**从来没被扫过**。
        #    核销卡这句 `**整单核销**` 就是这么一直印在屏幕上的（把造卡收口时才撞出来）。
        #    这条注入钉住"明细块已改成花括号配对"——旧的区间扫描**认不出**它（漏检）。
        "明细块里的 Markdown 星号（旧区间扫描因提前收尾而漏掉的那种形状）",
        SHIPPER,
        'add("（没有点名商品 = 整单核销：这一单还欠的全收）")',
        'add("（没有点名商品 = **整单核销**：这一单还欠的全收）")',
        "AiWriteShipperLedgerHandlers.kt 的卡片文案里没有 Markdown 星号",
    ),
    (
        # 造卡收成一处之后新增的判据：谁都不许再自己拼 `store.offer(...)`
        # （标题与风险档位会因此绕开动作登记表，而用户唯一看得见的就是这两样）。
        "处理器绕过造卡出口，自己拼 store.offer（标题/风险档位绕开登记表）",
        BASIC,
        '            store.card(\n                actionId,\n                summary = "支出：',
        '            store.offer(\n                actionId,\n                summary = "支出：',
        "AiWriteBasicHandlers.kt 没有绕过造卡出口（自己拼 store.offer）",
    ),
]


def main() -> int:
    bad = 0
    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) < 1:
            print(f"  [SKIP] {label} —— 原文没找到：{old[:40]}")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            out = run_check()
        finally:
            restore_src(path, src, crlf)
        fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
        hit = any(expect in ln for ln in fails)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → 期望红：{expect}（实际红 {len(fails)} 条）")
        if not hit:
            for ln in fails[:3]:
                print("        " + ln.strip())
            bad += 1
    tail = run_check()
    ok = "项通过" in tail
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1
    total = len(MUTATIONS) + 1
    print("\n" + (f"✅ {total}/{total} 都红了：这条检查真的在检查。" if bad == 0 else f"❌ {bad}/{total} 不达标。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
