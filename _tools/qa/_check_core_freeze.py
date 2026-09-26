"""**核心区冻结**判据：改了核心文件就必须先在声明页登记一句「为什么必须动核心」。

## 用户定的准则（2026-09-21 原话）
「我们现在…加购加功能的话，我们采一个核心的准则就是**核心的逻辑代码是不要乱动、核心是不要变**，
然后其他的就是**以插件的形式** —— 能调方法调方法、能继承就继承、能调 API 就调 API。」

准则本身写在 `docs/CORE_AND_EXTENSION.md`，核心区清单在 `_tools/qa/_core_files.txt`。
这条脚本只负责**让准则有牙**：光写在文档里，"顺手把核心改一改"谁都不会觉得有什么问题。

## 判据（6 条）
1. **清单不许被掏空**：核心区必须包含一组"骨架"文件（钱 / 状态机 / 权限 / 时区 / 可靠投递 / AI 写闸门），
   少一个就报红 —— 否则"把条目删掉"就是最省事的过检查办法。
2. **清单不许有化石**：写进清单的路径必须真实存在（文件被改名/删掉时必须同步改清单，
   否则下一个人会以为某个已经不存在的文件还在守着什么）。
3. **未提交的核心改动必须在声明页「进行中」一节里有一行 `核心改动：<路径> —— 为什么必须动核心：…`**。
   ⛔ 只认「进行中」那一段：写在别处（比如文件末尾的记录区）等于没声明。
4. **HEAD 那一个提交里改过的核心文件，声明页里也要有 `核心改动：<路径>` 一行**（2026-09-23 加）。
5. **报出"最近有哪些提交碰过核心区"**（只打印，不判红）—— 让改动者一眼看到这一带的近期历史。
6. **证据档文件（`_EVIDENCE_REQUIRED`）的例外声明必须写全四格**
   （证据 / 原因 / 范围 / 影响面运行时证明）—— 见下面「为什么 socket_io.py 要单独升一档」。

## 为什么 socket_io.py 要单独升一档（用户 2026-09-27 拍板）

用户原话：

> 「`socket_io.py` 应该加入 Core Freeze 的机器骨架判据……有合法例外：
>  **evidence / reason / scope / affected runtime proof** 才 ✅。
>  ⛔ **不需要把整个 `core/` 的 13 个文件重新审一遍** —— 那会把一个很小的治理缺口
>  重新扩大成 R4.1 大工程。」

背景：第 3/4 条只要求一行 `核心改动：<路径> —— 为什么必须动核心：<一句话>`。
对"顺手改一行"够用，但 `socket_io.py` 是**投递边界的承重件** ——
R3-06 的生产 Drill C 用原始输出证明它位于「至少一次投递」的成败语义上
（那次的证据是一条真实业务写入的收件箱事件被记成 `sent attempts=0`，
同一次演练日志里有 16 条 `Cannot publish to redis... giving up`）。
这样的文件，一行"为什么"撑不住：**必须同时说清"证据是什么、改动范围到哪、
运行时影响面被怎么证明过"**，否则下一个人只能看到"核心又被改了一处"。

所以升的是**这一档**（`_EVIDENCE_REQUIRED`，现在只有它一个成员），不是整个核心区。

## 为什么只看**未提交**的改动
声明页要解决的问题是「同一时间多个人在改同一个仓库」时互相覆盖 —— 那一刻改动就在工作区里。
提交之后改动已经进了 git 历史（`git log -p` 可查），声明页不再是唯一记录，也没必要再拦。

## ⚠️ 但"先提交、再声明"会把上面那条判据整个绕过去（2026-09-23 实测）
用户 2026-09-23 要求「**每一次改动要提交 git，方便下次改做回去**」—— 于是
"改完随手一提交"会成为常态，而第 3 条**只看未提交的改动**：一提交它就绿了。
本轮就是这么栽的：`accounting_service.py`（核心区：账本入账与欠款口径）改完提交之后
再跑这条检查，看到的是"✅ 全部 16 项通过"，而声明页里当时**一个字都没有**。
所以补第 4 条兜住：HEAD 那个提交碰过的核心文件，声明页里必须留下过一行 `核心改动：`。
它比第 3 条弱（不要求"动手之前"），但至少保证**每条核心改动都有一条书面理由**，
而不是"提交一按、检查全绿、理由永远不存在"。

用法：python _tools/qa/_check_core_freeze.py
"""
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402

ROOT = repo_root()
CORE_LIST = Path(__file__).resolve().parent / "_core_files.txt"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"

#: 声明行的形状（用户/AI 在「进行中」里写的那一行）。刻意宽松：允许 `-`/`*` 列表符与缩进。
DECL = re.compile(r"^\s*[-*]?\s*核心改动\s*[:：]\s*(.+)$", re.M)

#: ⛔ **骨架判据**：这几个文件缺一个就说明清单被掏空了（不是为了好看，是为了防"删条目过检查"）。
#: 每一项都写清"它守着什么"，改这一行的人得先想清楚自己是不是在拆防线。
_SKELETON = {
    "backend/app/services/order_money.py": "一张单的钱",
    "backend/app/services/driver_pay.py": "司机应得",
    "backend/app/services/order_flow.py": "订单状态迁移",
    "backend/app/core/business_time.py": "业务时区",
    "backend/app/core/socket_io.py": "可靠投递原语（发件箱的成败语义建立在这条上）",
    "backend/app/core/rbac.py": "角色权限",
    "backend/app/models/enums.py": "领域词汇表",
    "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt": "AI 写闸门",
}

#: ⛔ **证据档**：这几个文件的例外声明除了"一句为什么"，还必须写全四格。
#: 加文件的判据不是"它重要"，而是"**它的错误不报错**" —— 可靠投递、账、状态机那几处的共同点
#: 是"坏掉时安安静静"（R3-06 那次：事件被记成 sent，业务侧一条异常都没有）。
#: ⚠️ 用户 2026-09-27 明确要求**只升这一项**，不许借机把整个核心区都升成这一档。
_EVIDENCE_REQUIRED = {
    "backend/app/core/socket_io.py": "可靠投递原语（发件箱的成败语义建立在这条上）",
}

#: 例外声明必须写全的四格（用户原话：evidence / reason / scope / affected runtime proof）。
#: `原因` 一格可以由同一行的 `为什么必须动核心：…` 顶上（那是全核心区本来就要写的那句话），
#: 所以实际要多写的是另外三格。
_EXCEPTION_FIELDS = ("证据", "原因", "范围", "影响面运行时证明")

#: 四格子字段的形状：缩进 + 可选的列表符 + 字段名 + 冒号 + 值（值不许为空 —— 空值等于没写）。
_SUBFIELD = re.compile(
    r"^\s+(?:[-*]\s*)?(证据|原因|范围|影响面运行时证明)\s*[:：]\s*(\S.*)$", re.M
)

#: 清单至少要有这么多条（低于这个数说明它在被掏空，而不是在维护）。
MIN_CORE = 10


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit(f"找不到文件：{p}（被改名/搬走了？这条判据要跟着改）")
    return p.read_text(encoding="utf-8")


def git(*args: str) -> str:
    """跑一条 git（`core.quotepath=false`：不然中文路径会被转义成 `\\346\\226\\207…`）。"""
    r = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{(r.stderr or '').strip()[:200]}")
    return r.stdout or ""


def core_entries() -> list[tuple[str, str]]:
    """解析核心清单 → [(相对路径, 为什么)]。"""
    out: list[tuple[str, str]] = []
    for raw in read(CORE_LIST).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, _, why = line.partition("|")
        out.append((path.strip().replace("\\", "/"), why.strip()))
    return out


def claim_section(name: str) -> str:
    """声明页里某一节（`## 进行中` / `## 已完成`）的正文，直到下一个 `## ` 标题。"""
    text = read(CLAIM)
    m = re.search(rf"^##\s*{re.escape(name)}\s*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def decl_blocks(section: str) -> list[tuple[str, str, str]]:
    """把一节正文切成**一条声明一块**：→ [(路径, 声明那一行, 它下面的子字段块)]。

    块 = 声明行**后面连续的缩进行**，遇到空行 / 下一条声明 / 顶格行就结束。
    刻意用"缩进"当边界：声明页是 Markdown，子字段本来就写成子列表；
    ⛔ 不按"往下 N 行"取 —— 那会把别人下一条声明的内容算进这一条。
    """
    out: list[tuple[str, str, str]] = []
    lines = section.splitlines()
    for i, ln in enumerate(lines):
        m = DECL.match(ln)
        if not m:
            continue
        block: list[str] = []
        for nxt in lines[i + 1:]:
            if not nxt.strip() or DECL.match(nxt) or not nxt[:1].isspace():
                break
            block.append(nxt)
        out.append((m.group(1), ln, "\n".join(block)))
    return out


def evidence_gaps(decl_line: str, block: str) -> list[str]:
    """证据档那四格里**还缺哪几格**（值不许为空）。"""
    have = {m.group(1) for m in _SUBFIELD.finditer(block)}
    missing = [f for f in _EXCEPTION_FIELDS if f not in have]
    # `原因` 可以由同一行那句 `为什么必须动核心：…` 顶上（全核心区本来就要写它）。
    if "原因" in missing and ("为什么" in decl_line or "——" in decl_line or "--" in decl_line):
        missing.remove("原因")
    return missing


def check_evidence(c, where: str, section: str, files: list[str]) -> None:
    """证据档文件动了 → 它的例外声明必须写全四格（`files` 传"这次真的动了的那些"）。"""
    blocks = decl_blocks(section)
    for p in files:
        mine = [b for b in blocks if p in b[0]]
        gaps = evidence_gaps(mine[0][1], mine[0][2]) if mine else list(_EXCEPTION_FIELDS)
        c.ok(
            f"[{where}] {p} 的例外声明四格齐全（证据 / 原因 / 范围 / 影响面运行时证明）",
            not gaps,
            f"缺：{[g for g in gaps if g != '原因'] or gaps}"
            + ("（一行'为什么'不够 —— 这一档要写清证据、范围与运行时影响面的证明）"
               if mine else "（整条声明都没有）"),
        )


def main() -> int:
    if refuse_if_injecting("核心冻结检查"):
        return 1
    c = Checker()

    print("== 1. 清单本身：不许被掏空 ==")
    entries = core_entries()
    paths = [p for p, _ in entries]
    c.ok(f"核心区清单有 {len(entries)} 条（≥{MIN_CORE}）", len(entries) >= MIN_CORE)
    c.ok("清单里没有重复条目", len(paths) == len(set(paths)),
         f"重复：{[p for p in paths if paths.count(p) > 1]}")
    missing = [p for p, why in _SKELETON.items() if p not in paths]
    c.ok(f"骨架文件都在清单里（{len(_SKELETON)} 项：钱 / 状态机 / 权限 / 时区 / 写闸门…）",
         not missing, f"缺：{missing}")
    c.ok("每条都写了『为什么它是核心』（一句话，不是只有路径）",
         all(why for _, why in entries),
         f"没写理由：{[p for p, why in entries if not why]}")
    # ⛔ 证据档的成员必须**同时也是核心清单里的条目** —— 否则它守的是一份已经不在清单上的名单，
    #    下一个人删条目时不会看到任何提示（这一档就悄悄失效了）。
    off_tier = [p for p in _EVIDENCE_REQUIRED if p not in paths]
    c.ok(f"证据档 {len(_EVIDENCE_REQUIRED)} 项都在核心清单里", not off_tier,
         f"不在清单里：{off_tier}")

    print("\n== 2. 清单不许有化石：写进去的路径必须真实存在 ==")
    ghosts = [p for p in paths if not (ROOT / p).exists()]
    c.ok("清单里的路径全部存在", not ghosts, f"不存在：{ghosts}")

    print("\n== 3. 未提交的核心改动必须在「进行中」里声明 ==")
    changed = [
        ln.strip() for ln in git("diff", "--name-only", "HEAD").splitlines() if ln.strip()
    ]
    touched = [p for p in changed if p in set(paths)]
    print(f"  本次未提交改动 {len(changed)} 个文件；其中核心区 {len(touched)} 个：{touched}")
    live = claim_section("进行中")
    c.ok("声明页里有「进行中」一节（否则这条判据无处可查）", bool(live.strip()))
    decls = DECL.findall(live)
    print(f"  「进行中」里的核心改动声明 {len(decls)} 行")
    undeclared = [p for p in touched if not any(p in d for d in decls)]
    c.ok(
        "改了核心文件就必须在「进行中」写一行 `核心改动：<路径> —— 为什么必须动核心：…`",
        not undeclared,
        f"没声明：{undeclared}（照 `docs/CORE_AND_EXTENSION.md` 的格式补一行即可）",
    )
    # 声明必须写在一行里（路径与理由同一行）：分开写＝下一个人读不到"为什么"。
    for d in decls:
        c.ok(f"声明行里有理由：{d.strip()[:40]}…", ("为什么" in d or "——" in d or "--" in d),
             "这一行只有路径，没写为什么必须动核心")

    print("\n== 4. HEAD 那个提交碰过的核心文件也要留下书面理由 ==")
    # ⚠️ 为什么要有这一段：第 3 条只看**未提交**的改动，而用户 2026-09-23 要求
    #    「每一次改动要提交 git」—— 提交之后第 3 条必然全绿（实测就是这么绕过去的）。
    #    这里按**提交里的文件名**再查一次，与第 3 条互补：一个管"动手前声明"，
    #    一个管"事后至少留下过一行理由"。
    #
    # ⛔ 2026-09-24 第 24 轮（第 22 轮 F6 报的"判据被历史掏空"）：原来这里在**整份 5800 行**
    #    的声明页里搜 `核心改动：<路径>` —— 而那份页面里躺着 39 行历史声明，
    #    于是**下次动 `driver_pay.py` 会因为两个月前那行自动变绿**（正是这段注释上面
    #    记着的那次事故的形状，换了个地方又长回来）。
    #    现在只认**这次提交自己的条目**（正文里提到 HEAD 短哈希的那些），
    #    没有就退到**最新那一条**（声明是往前追加的，最新条目就是"正在进行的那一轮"）。
    head_files = [
        ln.strip() for ln in git("show", "--name-only", "--pretty=format:", "HEAD").splitlines()
        if ln.strip()
    ]
    head_core = [p for p in head_files if p in set(paths)]
    head_hash = git("rev-parse", "--short", "HEAD").strip()
    blocks = [b for b in re.split(r"(?m)^###\s", read(CLAIM))[1:]]
    own = [b for b in blocks if head_hash and head_hash in b] or blocks[:1]
    decl_own = [d for b in own for d in DECL.findall(b)]
    print(f"  HEAD 改了 {len(head_files)} 个文件；其中核心区 {len(head_core)} 个：{head_core}")
    print(f"  本次提交自己的声明条目 {len(own)} 个（HEAD={head_hash}），里面 {len(decl_own)} 行 `核心改动：`")
    missing_head = [p for p in head_core if not any(p in d for d in decl_own)]
    c.ok(
        "HEAD 提交里改过的核心文件，**本次提交自己那一轮**的声明里有一行 `核心改动：<路径>`"
        "（提交后再补也算；翻旧账不算）",
        not missing_head,
        f"没有理由：{missing_head}（在最新那条声明里补一行，写清为什么必须动核心）",
    )

    print("\n== 5. 最近碰过核心区的提交（只报，不判红）==")
    log = git("log", "-6", "--pretty=%h %ad %s", "--date=short", "--", *paths[:1], *paths[1:]).strip()
    if log:
        for ln in log.splitlines():
            print("     " + ln)
    else:
        print("     （没有历史）")

    print("\n== 6. 证据档文件：例外声明必须写全四格 ==")
    # ⚠️ 为什么单独一档（用户 2026-09-27 拍板）：第 3/4 条只要求"一句为什么"。
    #    对"顺手改一行"够用；而 `socket_io.py` 是**投递边界的承重件** ——
    #    R3-06 生产 Drill C 用原始输出证明它位于「至少一次投递」的成败语义上。
    #    这种文件要的是"证据 / 原因 / 范围 / 影响面运行时证明"四格齐全，一行撑不住。
    #    ⛔ 只升这一档，不把整个核心区都升上来（用户明确要求）。
    ev_touched = [p for p in touched if p in _EVIDENCE_REQUIRED]
    print(f"  本次未提交改动里属于证据档的：{ev_touched}")
    check_evidence(c, "未提交", live, ev_touched)
    ev_head = [p for p in head_core if p in _EVIDENCE_REQUIRED]
    if ev_head:
        print(f"  HEAD 那个提交碰过的证据档文件：{ev_head}")
        check_evidence(c, "HEAD", "\n".join(own), ev_head)
    else:
        print("  HEAD 那个提交没碰证据档文件（这一条本次无事可判）")

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
