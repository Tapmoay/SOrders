# -*- coding: utf-8 -*-
"""反向验证：把「effective config 指纹」那条判据逐条弄坏，看它**真的会红**。

这一条判据有一半是**跑起来问**的（真的 import 应用、真的调那个函数），
所以这里也有一半注入是**真的会改变运行结果**的 —— 例如给指纹多塞一个键、
塞一个连接串形状的值。剩下的是读源码的部分（/health 上有没有、装配根给没给身份）。

⚠️ 第 4 条特别值钱：它注入的是"指纹**自己去读一次环境变量**"，
那是**第二个真相来源**的形状 —— 而它跑起来完全正常、指纹也照样吐得出来。

用法：python _tools/qa/_reverse_verify_canary_config.py   # 全部成立 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_canary_config_fingerprint.py"

RUNTIME = ROOT / "backend/app/core/pricing_runtime.py"
MAIN = ROOT / "backend/app/main.py"

HEALTH_LINE = '            "pricing": pricing_fingerprint(),\n'
FP_RETURN = (
    '    return {"canary_percent": canary_percent(),\n'
    '            "resolver": _RESOLVER_ID or "(已装配，未命名)"}'
)
FP_GUARD = "    if _RESOLVER is None:\n"
ID_GUARD = '_RESOLVER_ID = (identity or "") if fn is not None else ""'
REGISTER_CALL = 'register_pricing_resolver(_resolve_pricing, identity="PricingContract v2 @ extensions.pricing")'
NON_SENSITIVE_LINE = "    ⛔ 只放**非敏感**的两样：一个 0..100 的整数、一个我们自己起的短名字。"


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

def s_drop_from_health(sb):
    """把指纹从 /health 上拿掉 —— 运维就再也问不出「这个实例实际是怎么跑的」。"""
    sb.replace(MAIN, HEALTH_LINE, "")


def s_extra_key(sb):
    """给指纹**多塞一个键**（键名撞敏感词）—— 形状判据必须当场响。"""
    sb.replace(RUNTIME, FP_RETURN,
               '    return {"canary_percent": canary_percent(),' + "\n"
               + '            "resolver": _RESOLVER_ID or "(已装配，未命名)",' + "\n"
               + '            "database_url": "***"}  # rv-injection')


def s_secret_value(sb):
    """键名干净、**值**是连接串形状 —— 值那条判据必须自己抓得住。"""
    sb.replace(RUNTIME, FP_RETURN,
               '    return {"canary_percent": canary_percent(),' + "\n"
               + '            "resolver": _RESOLVER_ID or "(已装配，未命名)",' + "\n"
               + '            "note": "mysql+pymysql://u:p@127.0.0.1:3306/sorders"}  # rv-injection')


def s_second_truth_source(sb):
    """⭐ 指纹**自己去读一次环境变量** —— 跑起来完全正常，但那是第二个真相来源。"""
    sb.replace(RUNTIME, FP_GUARD,
               '    _extra = __import__("os").environ.get("FREIGHT_PRICING_CANARY_PERCENT")  # rv-injection' + "\n"
               + FP_GUARD)


def s_register_without_identity(sb):
    """装配根登记时**不给身份** —— 指纹只剩比例，对账少一半。"""
    sb.replace(MAIN, REGISTER_CALL, "register_pricing_resolver(_resolve_pricing)")


def s_keep_stale_identity(sb):
    """未装配时**留着上一次的名字** —— 指纹会骗人。"""
    sb.replace(RUNTIME, ID_GUARD, '_RESOLVER_ID = identity or ""  # rv-injection')


def s_drop_warning(sb):
    """删掉「非敏感 / 不许长出口令」那句交代 —— 给下一个人的警告没了。"""
    sb.replace(RUNTIME, NON_SENSITIVE_LINE,
               "    ⛔ 只放两样：一个 0..100 的整数、一个我们自己起的短名字。")


# (说明, 场景, 期望关键字) ；关键字必须在**报红那一行**里出现
SCENARIOS = [
    ("把指纹从 /health 上拿掉", s_drop_from_health, "pricing 指纹"),
    ("给指纹多塞一个键（键名撞敏感词）", s_extra_key, "只有两个键"),
    ("指纹里塞一个连接串形状的**值**", s_secret_value, "连接串"),
    ("⭐ 指纹自己去读一次环境变量（第二个真相来源）", s_second_truth_source, "环境变量"),
    ("装配根登记时不给身份", s_register_without_identity, "identity="),
    ("未装配时留着上一次的名字（指纹骗人）", s_keep_stale_identity, "未装配"),
    ("删掉「非敏感 / 不许长出口令」的交代", s_drop_warning, "非敏感"),
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
        # ⚠️ 这条判据会 import 应用，日志走 stderr —— 取最后一行会取到日志，
        #    所以只从带 ✅/❌ 的行里取（第一版就打印了一行日志当"结论"）。
        verdict = [ln.strip() for ln in out.splitlines() if "✅" in ln or "❌" in ln]
        print("✅ 前提：源码完好时判据是绿的 —— " + (verdict[-1] if verdict else "（没拿到结论行）"))

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