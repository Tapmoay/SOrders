# -*- coding: utf-8 -*-
"""反向验证：把「生产形状对账」那条判据逐条弄坏，看它**真的会红**。

## 为什么这一份特别要紧

R4-43 那个 bug 的形状是：**自检喂的样本形状 ≠ 生产给的样本形状** ⇒ 判据自己测自己、
永远绿。所以这一份反向验证里，有一半的注入点**故意不动判据本身，而是动"形状"**：

· 把"认不出"并回已知桶（判据看起来还在跑，只是再也说不出"认不出"）
· 把布尔读取退回只认 1/0（这正是 R4-43 的原形）
· 把 resolution 的缺口判据改成永远 True（装饰品）
· 让工具里的闭集与 backend 漂移一个取值（两边各自都对，合起来是错的）
· 往某个工具里塞一处**没登记**的读取点（新读一格的后果没人交代）
· 把 T2 的门禁退回"可缺省就跳过"（门禁只写在注释里的原形）

⚠️ 每一条都必须让**报红那一行**里出现下面那个关键字 —— 只看"退出码非 0"是不够的：
判据可能因为别的原因红（例如 import 炸了），那证明不了这一条在管用。

用法：python _tools/qa/_reverse_verify_prod_shape.py   # 全部成立 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = Path(__file__).resolve().parent / "_check_prod_shape.py"
STATUS = ROOT / "_tools/ops/_canary_status.py"
FREEZE = ROOT / "_tools/ops/_freeze_probe.py"


class Sandbox:
    """按字节记住原样，最后一次性还原（⛔ 不用 git checkout --：那会抹掉未提交的真实改动）。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def replace(self, p: Path, old: str, new: str) -> None:
        if p not in self.saved:
            self.saved[p] = p.read_bytes()
        text = p.read_text(encoding="utf-8")
        assert text.count(old) == 1, (p.name + ": 原文出现 " + str(text.count(old)) + " 次，无法唯一替换")
        p.write_bytes(text.replace(old, new).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)
            if p.read_bytes() != raw:
                print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        self.saved.clear()


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK), "--check"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# ---------------------------------------------------------------- 注入场景

def s_unknown_into_bucket(sb):
    """把"认不出的 resolution"并回 not_in_canary —— 判据还在跑，只是再也说不出"认不出"。"""
    sb.replace(STATUS,
               '        if rst == "unknown":\n            out["unknown"] += n',
               '        if rst == "unknown":\n            out["not_in_canary"] += n  # rv-injection')


def s_bool_only_10(sb):
    """布尔只认 1/0（**这正是 R4-43 的原形**：自检的形状，不是生产的形状）。"""
    sb.replace(STATUS, '_TRUEISH = ("1", "true", "yes", "on")', '_TRUEISH = ("1",)  # rv-injection')


def s_bool_none_as_false(sb):
    """认不出时返回 False —— "认不出"与"是假"被合并（⑨ 的计数会静静地错）。"""
    sb.replace(STATUS,
               '    if s in _FALSEISH:\n        return False\n    return None',
               '    return s in _TRUEISH  # rv-injection')


def s_cutover_always_true(sb):
    """把 resolution 缺口判据改成永远 True —— 一条**装饰品**判据。"""
    sb.replace(STATUS,
               '    if gap == 0:\n        return True, "窗口内没有一笔缺 resolution"',
               '    if True:  # rv-injection\n        return True, "窗口内没有一笔缺 resolution"')


def s_resolution_drift(sb):
    """让工具里的闭集与 backend 漂移一个取值（两边各自都对，合起来是错的）。"""
    sb.replace(STATUS,
               'RESOLUTIONS = ("contract", "fallback", "not_in_canary", "frozen")',
               'RESOLUTIONS = ("contract", "fallback", "not_in_canary", "froze")  # rv-injection')


def s_prov_back_to_isnull(sb):
    """缺键判据退回 is null —— 一个写成 "" 的键会被算成「在」（生产报 100% 完整）。"""
    sb.replace(STATUS,
               '    return ("coalesce(json_unquote(json_extract(freight_rule_snapshot, \'$."\n'
               '            + key + "\')), \'\') = \'\'")',
               '    return ("json_extract(freight_rule_snapshot, \'$." + key + "\') is null")  # rv-injection')


def s_prod_extra_key(sb):
    """生产判据多要一个代码侧根本不认的键（两份清单开始各说各话）。"""
    sb.replace(STATUS,
               'PROV_REQUIRED_KEYS = ("v", "at", "source", "fee",',
               'PROV_REQUIRED_KEYS = ("v", "at", "source", "fee", "pricing.zzy",  # rv-injection')


def s_inline_bool_set(sb):
    """内联手写的布尔集合回来了（R4-43 的温床：换一种写法就静默失效）。"""
    sb.replace(STATUS,
               '        a, o = as_bool(d.get("agreed")), as_bool(d.get("override"))',
               '        a, o = (d.get("agreed") in ("1", "true", "True")), as_bool(  # rv-injection\n'
               '            d.get("override"))')


def s_unregistered_read(sb):
    """往另一个工具里塞一处**没登记**的读取点（新读一格的后果没人交代）。"""
    sb.replace(FREEZE, "'$.pricing.kind'", "'$.pricing.zzz'  # rv-injection")


def s_registry_ghost(sb):
    """登记表里留一条化石（那条键已经没人读了）。"""
    sb.replace(CHECK, '    "pricing.agreed": ', '    "pricing.agreed_zzz": ')


def s_t2_optional_reason(sb):
    """T2 的门禁退回"可缺省就跳过" —— 写在注释里的门禁的原形。"""
    sb.replace(FREEZE,
               '    if not expect_reason:',
               '    if expect_reason and False:  # rv-injection')


# (说明, 场景, 期望关键字) ；关键字必须在**报红那一行**里出现
SCENARIOS = [
    ("把「认不出的 resolution」并回 not_in_canary", s_unknown_into_bucket, "落 unknown"),
    ("⭐ 布尔只认 1/0（R4-43 的原形：自检的形状 ≠ 生产的形状）", s_bool_only_10, "认得出 true/false"),
    ("认不出时返回 False（把「认不出」与「是假」合并）", s_bool_none_as_false, "认不出 ⇒ None"),
    ("resolution 缺口判据改成永远 True（装饰品）", s_cutover_always_true, "缺口出现在有值的"),
    ("工具与 backend 的 resolution 闭集漂移一个取值", s_resolution_drift, "逐个相同"),
    ("缺键判据退回 is null（空串会被算成「在」）", s_prov_back_to_isnull, "覆盖**空串**"),
    ("生产判据多要一个代码侧不认的键", s_prod_extra_key, "两边都没交代"),
    ("内联手写的布尔集合回来了", s_inline_bool_set, "内联手写的布尔集合"),
    ("另一个工具里多了没登记的读取点", s_unregistered_read, "未登记"),
    ("登记表里留一条化石", s_registry_ghost, "化石"),
    ("T2 的门禁退回「可缺省就跳过」", s_t2_optional_reason, "可缺省"),
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
            print("❌ 前提不成立：源码完好时这条判据没过\n" + out[-2000:])
            return 1
        verdict = [ln.strip() for ln in out.splitlines() if "✅" in ln or "❌" in ln]
        print("✅ 前提：源码完好时判据是绿的 —— " + (verdict[-1] if verdict else "（没拿到结论行）"))

        for label, setup, keyword in SCENARIOS:
            sb.restore()
            setup(sb)
            try:
                code, out = run_check()
            finally:
                sb.restore()
            reds = [ln for ln in out.splitlines() if "[FAIL]" in ln]
            hit = code != 0 and any(keyword in ln for ln in reds)
            detail = ("实际红 " + str(len(reds)) + " 条"
                      + ("" if hit else "：" + str([r.strip()[:80] for r in reds[:2]])))
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
