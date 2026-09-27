# -*- coding: utf-8 -*-
"""反向验证：把「Canary 决策冻结」那条判据逐条弄坏，看它**真的会红**。

为什么必须反向验证（本项目的规矩）：这条判据最容易的坏法不是"报错"，而是**悄悄什么都不看** ——
比如把 frozen 参数留在签名里、函数体里却不再用它；或者把那两行**挪到比例后面**
（还在文件里、还在跑、单测如果只测比例也照样绿），而它已经不是冻结了。
所以这里逐条制造**具体的破坏**，其中第 2 条（挪位置）是这一份里最值钱的：
它证明的是"判据看的是**优先级顺序**，不是文件里有没有那行字"。

用法：python _tools/qa/_reverse_verify_canary_freeze.py   # 全部成立 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_canary_freeze.py"

RUNTIME = ROOT / "backend/app/core/pricing_runtime.py"
ORDER_MONEY = ROOT / "backend/app/services/order_money.py"
ASSIGN_API = ROOT / "backend/app/api/v1/orders_assignment.py"
TESTS = ROOT / "backend/tests/test_pricing_runtime.py"

FREEZE_IF = "    if frozen in (KIND_LEGACY, KIND_CONTRACT):"
PCT_LINE = "    pct = canary_percent() if percent is None else max(0, min(100, int(percent)))"
FREEZE_BLOCK = (
    FREEZE_IF + "\n"
    + "        # ⛔ 先看冻结：⛔ 不许把它挪到下面（那样比例 0 / 100 会越过冻结改掉来源）。\n"
    + "        return frozen\n"
    + PCT_LINE + "\n"
)
MOVED_BLOCK = PCT_LINE + "\n" + FREEZE_IF + "\n" + "        return frozen\n"
KIND_WHITELIST = "    return kind if kind in FREIGHT_KIND_CONTRACTS else None"


class Sandbox:
    """按字节记住原样，最后一次性还原（⛔ 不用 git checkout --：那会抹掉未提交的真实改动）。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def _keep(self, p: Path) -> None:
        if p not in self.saved:
            self.saved[p] = p.read_bytes()

    def replace(self, p: Path, old: str, new: str) -> None:
        self._keep(p)
        text = p.read_text(encoding="utf-8")
        assert text.count(old) == 1, str(p.name) + ": 原文出现 " + str(text.count(old)) + " 次，无法唯一替换"
        p.write_bytes(text.replace(old, new).encode("utf-8"))

    def append(self, p: Path, text: str) -> None:
        self._keep(p)
        p.write_bytes(p.read_bytes() + text.encode("utf-8"))

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


# ---------------------------------------------------------------- 注入场景

def s_drop_freeze(sb):
    """**把冻结整段删掉** —— 回到"每次写入都按当前比例重新抽签"。"""
    sb.replace(RUNTIME, FREEZE_BLOCK, PCT_LINE + "\n")


def s_move_freeze_after_percent(sb):
    """⭐ **把冻结挪到比例之后**（代码还在、还在跑，但它已经不是冻结了）。

    这是本判据存在的理由：单看"文件里有没有那两行"的判据**抓不到这一种**。
    """
    sb.replace(RUNTIME, FREEZE_BLOCK, MOVED_BLOCK)


def s_freeze_never_taken(sb):
    """让冻结分支**永远不成立**（if False and ...）—— 签名还在、参数没人用。"""
    sb.replace(RUNTIME, FREEZE_IF, "    if False and frozen in (KIND_LEGACY, KIND_CONTRACT):  # rv-injection")


def s_freeze_returns_something_else(sb):
    """冻结分支**不再原样返回**那一个来源（改成固定返回一个值）。"""
    sb.replace(RUNTIME, "        return frozen", "        return KIND_CONTRACT  # rv-injection")


def s_decide_forgets_frozen(sb):
    """组装点**忘了把冻结读出来**传进去（= 决策不再冻结，而只测比例的单测照样绿）。"""
    sb.replace(RUNTIME, ", frozen=freight_kind_of(order))", ")  # rv-injection")


def s_kind_accepts_anything(sb):
    """读冻结**不再检查白名单** —— 一个不认识的 kind 会把后面所有写入一起冻住。"""
    sb.replace(ORDER_MONEY, KIND_WHITELIST, "    return kind  # rv-injection")


def s_second_freeze_reader(sb):
    """业务代码里**长出第二处读冻结**（各自去读一个"已经定过什么"）。"""
    sb.append(ASSIGN_API, "\n\ndef _frozen_probe(order):  # rv-injection\n    return freight_kind_of(order)\n")


def _rename_test(sb, name: str) -> None:
    # ⚠️ 只匹配 "def <名字>(" —— 有的用例带夹具参数、有的不带（纯函数那两条不带），
    #    写死整套签名的写法在这里会 assert 失败（第一版就栽在这上面）。
    sb.replace(TESTS, "def " + name + "(", "def _rv_disabled(  # rv-injection")


def s_drop_test_legacy_first(sb):
    """删掉**用户点名的实验 1**（先旧路、再开满 —— 来源不许变）。"""
    _rename_test(sb, "test_先形成旧路之后把比例开到满_这次计价仍然是旧路")


def s_drop_test_contract_first(sb):
    """删掉**用户点名的实验 2**（先契约、再关零 —— 来源不许变）。"""
    _rename_test(sb, "test_先形成契约之后把比例关到零_这次计价仍然是契约")


def s_drop_test_fresh_draws(sb):
    """删掉"没定过的单照样按比例抽签" —— 冻结退化成"Canary 永远关着"就没人拦了。"""
    _rename_test(sb, "test_没定过来源的单仍然按比例抽签")


def s_drop_header_rule(sb):
    """把模块头第 4 条铁律删掉 —— 代码里还冻着，但**没人再说得清为什么**。"""
    sb.replace(RUNTIME, "**不许让比例变化改掉**", "**（这条被删了）**")


# (说明, 场景, 期望关键字) ；关键字必须在**报红那一行**里出现
SCENARIOS = [
    ("把冻结整段删掉（每次重抽签）", s_drop_freeze, "冻结分支"),
    ("⭐ 把冻结**挪到比例之后**（还在跑，但不再是冻结）", s_move_freeze_after_percent, "之前"),
    ("让冻结分支永远不成立（if False and ...）", s_freeze_never_taken, "冻结分支"),
    ("冻结分支不再原样返回（改成固定值）", s_freeze_returns_something_else, "原样返回"),
    ("组装点忘了把冻结传进去", s_decide_forgets_frozen, "传进去了"),
    ("读冻结不再检查白名单（不认识的 kind 也冻）", s_kind_accepts_anything, "白名单"),
    ("业务代码里长出第二处读冻结", s_second_freeze_reader, "第二处"),
    ("删掉用户点名的实验 1（先旧路后开满）", s_drop_test_legacy_first, "实验 1"),
    ("删掉用户点名的实验 2（先契约后关零）", s_drop_test_contract_first, "实验 2"),
    ("删掉「没定过的单照样按比例」", s_drop_test_fresh_draws, "永远关着"),
    ("删掉模块头第 4 条铁律", s_drop_header_rule, "第 4 条铁律"),
]


def main() -> int:
    if not CHECK.exists():
        print("❌ 找不到 " + str(CHECK))
        return 1

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条判据没过\n" + out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时判据是绿的 —— " + last.strip())

        for label, setup, keyword in SCENARIOS:
            sb.restore()
            setup(sb)
            try:
                code, out = run_check()
            finally:
                sb.restore()
            fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            hit = code != 0 and any(keyword in ln for ln in fails)
            detail = ("实际红 " + str(len(fails)) + " 条"
                      + ("" if hit else "：" + str([f.strip()[:70] for f in fails[:2]])))
            print("  [" + ("OK" if hit else "MISS") + "] " + label + " → " + detail)
            if not hit:
                bad += 1

        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后判据全绿" if ok else "  [MISS] 还原后判据没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    total = len(SCENARIOS) + 1
    print("")
    if bad:
        print("❌ " + str(bad) + "/" + str(total) + " 条不成立")
        return 1
    print("✅ " + str(total) + "/" + str(total) + " 全部成立：每一种破坏都被点出来了，还原后判据恢复")
    return 0


if __name__ == "__main__":
    sys.exit(main())