"""反向验证：把「核心冻结」那条判据逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这条判据守的是**流程**（改了核心要在声明页写一句为什么），
而流程类判据最容易被写成"看起来在检查、其实什么都不看"的东西——
比如只 grep 整个文件（那么把声明写在文件末尾的记录区也能过）、
或者不检查清单本身（那么把核心清单删空就是最省事的过检查办法）。

还有一个**正面**场景必须一起验：**写对了就必须能过**。
一条永远红的检查等于没有检查（本项目 §15 的教训），所以这里有一条 `[应通过]` 的场景。

用法：python _tools/qa/_reverse_verify_core_freeze.py    # 9 条场景全部成立 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_core_freeze.py"
CORE_LIST = HERE / "_core_files.txt"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"

#: 拿来"改一下核心"的文件：挑一个**只加一行注释**也绝对安全的（纯函数、无副作用）。
CORE_FILE = ROOT / "backend/app/core/business_time.py"
CORE_REL = "backend/app/core/business_time.py"

#: **证据档**那个文件（用户 2026-09-27 拍板升档的那个）：动它要多写三格。
SOCK_FILE = ROOT / "backend/app/core/socket_io.py"
SOCK_REL = "backend/app/core/socket_io.py"

DECL_GOOD = f"核心改动：{CORE_REL} —— 为什么必须动核心：反向验证场景\n"
DECL_NO_REASON = f"核心改动：{CORE_REL}\n"

#: 老式的一行声明（对**普通**核心文件够用；对证据档文件**不够**）
DECL_SOCK_ONE_LINE = f"核心改动：{SOCK_REL} —— 为什么必须动核心：反向验证场景\n"
#: 写了三格、缺"影响面运行时证明" —— 少一格就不许过（这正是升档要拦的形状）
DECL_SOCK_NO_PROOF = (
    f"核心改动：{SOCK_REL} —— 为什么必须动核心：反向验证场景\n"
    "  - 证据：反向验证注入（伪造的原始证据）\n"
    "  - 范围：只改这一条链\n"
)
#: ✅ 四格齐全（`原因` 由声明行的那句"为什么必须动核心"顶上）
DECL_SOCK_FULL = (
    f"核心改动：{SOCK_REL} —— 为什么必须动核心：反向验证场景\n"
    "  - 证据：反向验证注入（伪造的原始证据）\n"
    "  - 范围：只改这一条链\n"
    "  - 影响面运行时证明：反向验证注入（伪造的运行时观测）\n"
)


class Sandbox:
    """按字节记住原样，最后一次性还原（⛔ 不用 `git checkout --`：那会抹掉未提交的真实改动）。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def _keep(self, p: Path) -> None:
        if p not in self.saved:
            self.saved[p] = p.read_bytes()

    def append(self, p: Path, text: str) -> None:
        self._keep(p)
        # ⚠️ 拼接的必须是**当前内容**，不是保存的基线 —— 第一版写的是 `self.saved[p] + text`，
        #    于是在"先 strip、再 append"的注入里，**append 把 strip 抹掉了**（声明又回到「进行中」，
        #    注入于是恒不红；2026-09-25 实测抓到）。`saved` 只当还原点用。
        p.write_bytes(p.read_bytes() + text.encode("utf-8"))

    def replace(self, p: Path, old: str, new: str) -> None:
        self._keep(p)
        text = p.read_text(encoding="utf-8")   # 同上：当前内容
        assert text.count(old) == 1, f"{p.name}: 原文出现 {text.count(old)} 次，无法唯一替换"
        p.write_bytes(text.replace(old, new).encode("utf-8"))

    def write(self, p: Path, text: str) -> None:
        self._keep(p)
        p.write_bytes(text.encode("utf-8"))

    def touch_core(self) -> None:
        self.append(CORE_FILE, "\n# rv-injection: 假装有人顺手改了核心\n")

    def touch_socket(self) -> None:
        """"偷偷改一下投递边界" —— 只加一行注释，不改任何行为（不然会真的弄坏运行时）。"""
        self.append(SOCK_FILE, "\n# rv-injection: 假装有人顺手改了投递边界\n")

    def decl_in_progress(self, line: str) -> None:
        """把声明插进「进行中」一节的开头（判据只认这一节）。"""
        self.replace(CLAIM, "## 进行中\n", "## 进行中\n\n" + line)

    def strip_declarations(self, rel: str = CORE_REL, required: bool = True) -> None:
        """把声明页里**已有的**、关于这个核心文件的声明行全部删掉。

        ⚠️ 2026-09-25 实测（两条注入同时变 MISS）：判据第 3 条问的是「**未提交**的核心改动有没有声明」，
        而声明页里会**长期留着**历史声明行 —— 只要那个核心文件以前被谁声明过一次，
        "改了核心却一个字都没声明"这个前提就**永远不成立**了，注入于是再也不红。
        所以注入必须先把自己要证伪的前提造出来：清掉已有声明，再改核心。

        `required=False` 用于**当前声明页里本来就没有**该文件声明的注入（例如证据档那个文件）：
        那时"没有声明"这个前提**天然成立**，没什么可清；⛔ 但不能因此跳过断言 ——
        只要清掉了东西，就说明确实有过声明，那就必须真的清干净。
        """
        self._keep(CLAIM)
        text = self.saved[CLAIM].decode("utf-8")
        kept = [
            ln
            for ln in text.splitlines(keepends=True)
            if ("核心改动：" + rel) not in ln and ("核心改动：`" + rel + "`") not in ln
        ]
        stripped = "".join(kept)
        if required:
            assert stripped != text, "声明页里没有关于 " + rel + " 的声明，这条注入的前提不成立"
        if stripped != text:
            CLAIM.write_bytes(stripped.encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)
            if p.read_bytes() != raw:
                print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))

        self.saved.clear()


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def s_touch_only(sb: Sandbox) -> None:
    # ⚠️ 先清掉历史声明：否则"没声明"这个前提不成立（见 strip_declarations 的说明）
    sb.strip_declarations()
    sb.touch_core()


def s_decl_in_done_section(sb: Sandbox) -> None:
    """声明写了，但写在文件**末尾**（「已完成」那一节里）——等于没声明。"""
    sb.strip_declarations()
    sb.touch_core()
    sb.append(CLAIM, "\n" + DECL_GOOD)


def s_decl_without_reason(sb: Sandbox) -> None:
    """声明只写了路径，没写"为什么必须动核心"。"""
    sb.touch_core()
    sb.decl_in_progress(DECL_NO_REASON)


def s_decl_ok(sb: Sandbox) -> None:
    """**正面场景**：按格式写在「进行中」里 → 必须通过。"""
    sb.touch_core()
    sb.decl_in_progress(DECL_GOOD)


def s_socket_touch_only(sb: Sandbox) -> None:
    """"偷偷改了投递边界，一个字都没声明" —— 这是升档要拦的第一种形状。"""
    sb.strip_declarations(SOCK_REL, required=False)
    sb.touch_socket()


def s_socket_one_line_decl(sb: Sandbox) -> None:
    """改了投递边界，但只写**老式的一行**（有路径、有"为什么"，没有证据/范围/影响面证明）。

    ⭐ 这条是升档的**核心**：老式一行对普通核心文件仍然够用（见 `s_decl_ok`），
    对证据档文件**不够** —— 两条注入一起跑才说明"升的是这一档，不是把判据整体收紧"。
    """
    sb.strip_declarations(SOCK_REL, required=False)
    sb.touch_socket()
    sb.decl_in_progress(DECL_SOCK_ONE_LINE)


def s_socket_missing_proof(sb: Sandbox) -> None:
    """四格里缺最后一格（影响面运行时证明）——少一格就不许过。"""
    sb.strip_declarations(SOCK_REL, required=False)
    sb.touch_socket()
    sb.decl_in_progress(DECL_SOCK_NO_PROOF)


def s_socket_decl_ok(sb: Sandbox) -> None:
    """**正面场景**：按四格写全 → 必须通过（否则这一档就是"永远红"＝没有检查）。"""
    sb.strip_declarations(SOCK_REL, required=False)
    sb.touch_socket()
    sb.decl_in_progress(DECL_SOCK_FULL)


def s_drop_socket_skeleton(sb: Sandbox) -> None:
    """把 `socket_io.py` 从核心清单里删掉 —— 用户 2026-09-27 点名的那个缺口不许再打开。"""
    sb.replace(
        CORE_LIST,
        "backend/app/core/socket_io.py|推送的**最底层投递原语**（`sio.emit` 只在这里）"
        "—— 发件箱的「至少一次投递」承诺就建立在它的成败语义上；R3-06 生产 Drill C 用原始输出证明"
        "它位于**可靠投递边界**，所以它不能因为「想做插件化」就从核心拆出去\n",
        "",
    )


def s_drop_skeleton(sb: Sandbox) -> None:
    """把"钱"那一格从核心清单里删掉（最省事的过检查办法）。"""
    sb.replace(
        CORE_LIST,
        "backend/app/services/order_money.py|一张单的钱（已收 / 挂账 / 退货红冲 / 现场收现金）只有这一处口径\n",
        "",
    )


def s_ghost_entry(sb: Sandbox) -> None:
    """清单里加一条不存在的路径（文件改名了但清单没跟着改＝化石）。"""
    sb.append(CORE_LIST, "backend/app/services/this_file_never_existed.py|反向验证用的假条目\n")


def s_empty_list(sb: Sandbox) -> None:
    """把清单清空（只剩注释）。"""
    sb.write(CORE_LIST, "# 反向验证：清单被掏空\n")


def s_duplicate_entry(sb: Sandbox) -> None:
    """同一条写两遍。"""
    sb.append(CORE_LIST, "backend/app/core/rbac.py|重复条目\n")


# (说明, 场景, 期望) ；期望 = ("red", 关键字) 或 ("green", "")
SCENARIOS = [
    ("改了核心文件但一个字都没声明", s_touch_only, ("red", "改了核心文件就必须在")),
    ("声明写了，但写在「已完成」那一节（不在「进行中」）", s_decl_in_done_section, ("red", "改了核心文件就必须在")),
    ("声明只写路径、没写『为什么必须动核心』", s_decl_without_reason, ("red", "声明行里有理由")),
    ("✅ 正面场景：按格式写进「进行中」→ 应当通过", s_decl_ok, ("green", "")),
    ("把『钱』那一格从核心清单里删掉", s_drop_skeleton, ("red", "骨架文件都在清单里")),
    ("清单里塞一条不存在的路径", s_ghost_entry, ("red", "清单里的路径全部存在")),
    ("把核心清单清空", s_empty_list, ("red", "核心区清单有")),
    ("同一条写两遍", s_duplicate_entry, ("red", "清单里没有重复条目")),
    # ---- 证据档（用户 2026-09-27 拍板：只升 socket_io.py 这一项）----
    ("偷偷改了 socket_io.py，一个字都没声明", s_socket_touch_only, ("red", "改了核心文件就必须在")),
    ("改了 socket_io.py，只写老式的一行声明（缺证据/范围/影响面证明）",
     s_socket_one_line_decl, ("red", "四格齐全")),
    ("改了 socket_io.py，四格里缺『影响面运行时证明』", s_socket_missing_proof, ("red", "四格齐全")),
    ("✅ 正面场景：改了 socket_io.py + 四格写全 → 应当通过", s_socket_decl_ok, ("green", "")),
    ("把 socket_io.py 从核心清单里删掉（骨架判据必须拦住）",
     s_drop_socket_skeleton, ("red", "骨架文件都在清单里")),
]


def main() -> int:
    if not CHECK.exists():
        print(f"❌ 找不到 {CHECK}")
        return 1

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1500:]}")
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print(f"✅ 前提：源码完好时红线是绿的 —— {last.strip()}")

        for label, setup, expect in SCENARIOS:
            sb.restore()
            setup(sb)
            try:
                code, out = run_check()
            finally:
                sb.restore()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            kind, keyword = expect
            if kind == "green":
                hit = code == 0
                detail = "通过（这正是要的）" if hit else "按格式声明后仍报红：" + (
                    fails[0].strip()[:80] if fails else "?"
                )
            else:
                hit = code != 0 and any(keyword in ln for ln in fails)
                detail = f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")
            print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
            if not hit:
                bad += 1

        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    total = len(SCENARIOS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条，正面场景也能过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
