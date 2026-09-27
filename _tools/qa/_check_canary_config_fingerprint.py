# -*- coding: utf-8 -*-
"""**effective config 指纹判据**（R4-27）：生产**实际生效**的算价配置，问得出来吗。

R4-BOUNDARY-JUSTIFICATION: **代码边界解决不了这件事，因为缺口长在「谁去问」上。**

`.env` 里写着 `FREIGHT_PRICING_CANARY_PERCENT=30` 是**一个事实**；
「生产上两个实例实际上都在以 30% 跑」是**另一个事实**。滚动发布期间完全可能出现 A=30 / B=0，
而 .env 上一个字都看不出来 —— 单看任何一个文件都发现不了，只能**逐个进程去问**。
所以这一条是对账式的，与 `_check_ops.py` 属于同一类。

## 用户 2026-09-27 拍板的出口条件 ②

> 「我建议让 /health 或内部 diagnostics 有一个**非敏感的** config fingerprint /
>  effective config value，至少能证明：instance A → 30 / instance B → 30，
>  而不是『我记得两个都改了』。当然不要把整个 .env 暴露出去。」

## 判据（一半是**跑起来问**，一半是**读源码**）

跑起来问（真的 import 应用、真的调那个函数）：
1. 指纹**只有两个键**（加第三个必须来这里报到 —— "给 AI 开一条后路"那条规矩）；
2. 比例是 0..100 的整数；身份非空（装配根登记时给了名字）；
3. ⛔ 指纹里**没有任何敏感形状**的键或值（这一条会被 /health 直接吐到公网上）。

读源码：
4. 指纹**只有一处实现**，且比例来自**唯一一处**（`canary_percent()`）—— ⛔ 不许自己再读一次配置；
5. 未装配时**如实说未装配**（⛔ 不是留着上一次的名字骗人）；
6. `/health` 里**带**指纹，且**来自那一个函数**（⛔ 不是就地手写一份）；
7. 装配根登记解析器时**给了身份**（否则指纹只剩比例，对账少一半）。

用法：
    python _tools/qa/_check_canary_config_fingerprint.py            # 详细
    python _tools/qa/_check_canary_config_fingerprint.py --check    # 必跑模式（一行结论）
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
# 只读审计：库指到临时目录，别在仓库里建出 app.db
os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + (Path(tempfile.mkdtemp()) / "fp.db").as_posix()
)
sys.path.insert(0, str(BACKEND))

RUNTIME = BACKEND / "app" / "core" / "pricing_runtime.py"
MAIN = BACKEND / "app" / "main.py"

#: 指纹会被 /health 直接吐出去 —— 这些形状**一个都不许**出现（键名或值的形状）。
SENSITIVE_KEYWORDS = (
    "pass", "pwd", "secret", "token", "key", "url", "dsn", "credential", "host", "user",
    "database", "redis", "jwt",
)

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool) -> bool:
    global passes
    if cond:
        passes += 1
    else:
        fails.append(label)
    print(("  [OK]   " if cond else "  [FAIL] ") + label)
    return cond


def _body(text: str, start_marker: str, stop_markers: tuple[str, ...]) -> str:
    """从 start_marker 起、到下一个 stop_marker 为止的那一段（找不到就返回空串）。"""
    i = text.find(start_marker)
    if i < 0:
        return ""
    rest = text[i + len(start_marker):]
    ends = [rest.find(m) for m in stop_markers if rest.find(m) >= 0]
    return rest[:min(ends)] if ends else rest


def main() -> int:
    check = "--check" in sys.argv
    for p in (RUNTIME, MAIN):
        if not p.exists():
            print("❌ 找不到 " + str(p))
            return 1

    rt = RUNTIME.read_text(encoding="utf-8")
    main_src = MAIN.read_text(encoding="utf-8")

    if not check:
        print("== 1. 真的把它跑起来问一次（⛔ 不是读源码猜） ==")

    import app.main  # noqa: F401  —— 让装配根真的跑一遍（与生产同一段代码）
    from app.core.pricing_runtime import pricing_fingerprint

    fp = pricing_fingerprint()
    print("      实际指纹：" + repr(fp))
    ok("指纹只有两个键（加第三个必须来这里报到）", set(fp) == {"canary_percent", "resolver"})
    ok("比例是一个 0..100 的整数",
       isinstance(fp.get("canary_percent"), int) and 0 <= fp["canary_percent"] <= 100)
    ok("身份非空（装配根登记时给了名字）",
       bool(fp.get("resolver")) and fp["resolver"] != "(未装配)")

    bad_keys = [k for k in fp if any(w in k.lower() for w in SENSITIVE_KEYWORDS)]
    ok("⛔ 指纹里没有敏感形状的**键**", not bad_keys)
    if bad_keys:
        print("        ⛔ 撞上的键：" + ", ".join(bad_keys))

    # ⚠️ 值的形状判据要**窄**：第一版写成"含 @ 就算敏感"，
    #    当场把身份那句 "PricingContract v2 @ extensions.pricing" 误判成敏感 ——
    #    判据误报的代价是下一个人把它删掉，那比没有判据更糟。
    def _suspicious(v) -> bool:
        if not isinstance(v, str):
            return False
        return ("://" in v or re.search(r"[^\s@]+@[^\s@]+", v) is not None or len(v) > 80)

    bad_vals = [k for k, v in fp.items() if _suspicious(v)]
    ok("⛔ 指纹里没有敏感形状的**值**（连接串 / 邮箱 / 超长串）", not bad_vals)
    if bad_vals:
        print("        ⛔ 撞上的键：" + ", ".join(bad_vals))

    if not check:
        print("== 2. 指纹只有一处实现，且比例来自唯一一处 ==")

    ok("pricing_fingerprint 全仓只有一处定义", rt.count("def pricing_fingerprint(") == 1)
    body = _body(rt, "def pricing_fingerprint(", ("\ndef ", "\n# ---"))
    ok("找得到它的函数体", bool(body.strip()))
    ok("它调 canary_percent()（比例只有一个来源）", "canary_percent()" in body)
    ok("⛔ 它**没有**自己去读配置 / 环境变量（否则就是第二个来源）",
       not any(w in body for w in ("get_settings", "environ", "getenv", "settings.")))
    ok("未装配时**如实说未装配**（⛔ 不是留着上一次的名字骗人）",
       "_RESOLVER_ID = (identity or \"\") if fn is not None else \"\"" in rt)

    if not check:
        print("== 3. /health 里带指纹，而且来自那一个函数 ==")

    ok("/health 里带了 pricing 指纹", '"pricing": pricing_fingerprint(),' in main_src)
    ok("指纹来自那一个函数（⛔ 不是就地手写一份）",
       main_src.count("pricing_fingerprint()") == 1)
    ok("main.py import 的是核心那个函数", "from app.core.pricing_runtime import pricing_fingerprint" in main_src)

    if not check:
        print("== 4. 装配根登记时给了身份 ==")

    ok("register_pricing_resolver 调用时带了 identity=",
       re.search(r"register_pricing_resolver\([^)]*identity=", rt) is None
       and re.search(r"register_pricing_resolver\([^)]*identity=", main_src) is not None)
    ok("核心那个函数认 identity 关键字参数",
       'def register_pricing_resolver(fn, *, identity: str = "")' in rt)

    if not check:
        print("== 5. 给下一个人的警告还在 ==")

    ok("指纹函数里写明了「非敏感」与「不许长出口令」",
       "非敏感" in body and "口令" in body)

    if check:
        print(("✅" if not fails else "❌")
              + " effective config 指纹：只有 2 个键、非敏感、/health 上有、装配根给了身份"
              + ("" if not fails else "；" + str(len(fails)) + " 项不通过"))
    if fails:
        print("")
        print("❌ " + str(len(fails)) + " 项不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    if not check:
        print("")
        print("✅ 全部 " + str(passes) + " 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())