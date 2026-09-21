"""**核心区冻结**判据：改了核心文件就必须先在声明页登记一句「为什么必须动核心」。

## 用户定的准则（2026-09-21 原话）
「我们现在…加购加功能的话，我们采一个核心的准则就是**核心的逻辑代码是不要乱动、核心是不要变**，
然后其他的就是**以插件的形式** —— 能调方法调方法、能继承就继承、能调 API 就调 API。」

准则本身写在 `docs/CORE_AND_EXTENSION.md`，核心区清单在 `_tools/qa/_core_files.txt`。
这条脚本只负责**让准则有牙**：光写在文档里，"顺手把核心改一改"谁都不会觉得有什么问题。

## 判据（4 条）
1. **清单不许被掏空**：核心区必须包含一组"骨架"文件（钱 / 状态机 / 权限 / 时区 / AI 写闸门），
   少一个就报红 —— 否则"把条目删掉"就是最省事的过检查办法。
2. **清单不许有化石**：写进清单的路径必须真实存在（文件被改名/删掉时必须同步改清单，
   否则下一个人会以为某个已经不存在的文件还在守着什么）。
3. **未提交的核心改动必须在声明页「进行中」一节里有一行 `核心改动：<路径> —— 为什么必须动核心：…`**。
   ⛔ 只认「进行中」那一段：写在别处（比如文件末尾的记录区）等于没声明。
4. **报出"最近有哪些提交碰过核心区"**（只打印，不判红）—— 让改动者一眼看到这一带的近期历史。

## 为什么只看**未提交**的改动
声明页要解决的问题是「同一时间多个人在改同一个仓库」时互相覆盖 —— 那一刻改动就在工作区里。
提交之后改动已经进了 git 历史（`git log -p` 可查），声明页不再是唯一记录，也没必要再拦。

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
    "backend/app/core/rbac.py": "角色权限",
    "backend/app/models/enums.py": "领域词汇表",
    "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt": "AI 写闸门",
}

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

    print("\n== 4. 最近碰过核心区的提交（只报，不判红）==")
    log = git("log", "-6", "--pretty=%h %ad %s", "--date=short", "--", *paths[:1], *paths[1:]).strip()
    if log:
        for ln in log.splitlines():
            print("     " + ln)
    else:
        print("     （没有历史）")

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
