#!/usr/bin/env python3
"""`_probe_core_flows.verdict()` 的反向验证：三种结局都必须真的能发生。

## 为什么单独成脚本
探针本身要**活后端**才跑得起来，所以它进不了 `_check_all.py` 的必跑组；
但"疑点怎么判"这件事是**纯函数**，不需要后端 —— 而它恰恰是整套东西里最容易空转的一环：
把 unknown 判成 0、或者忘了报化石，探针就会**永远绿**，谁也不会发现
（本项目自己的话：「永远红的检查 = 没有检查」，反面同样成立：永远绿的更糟，因为没人会去看）。
所以把判据从"跑得起来"里拆出来，让它能被静态验证。

## 判据（每条都要真的能红，也要真的能绿）
① 空疑点 → 0；② 不可接受的疑点 → 1；③ 已接受的疑点 → 0 **且输出里带着它的理由**；
④ 例外表里有条目没命中 → 1 **且点名那一条**（化石）；⑤ 分组跑不做化石判定 → 0；
⑥ 例外表自己的纪律：每条理由必须写**什么时候删掉它**。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).with_name("_probe_core_flows.py")

FAILED: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  [通过] {label}")
    else:
        print(f"  [!!]   {label} —— {detail}")
        FAILED.append(label)


def load_probe():
    """按路径加载探针模块（它的名字以 `_` 开头，不能靠 import 语句）。"""
    spec = importlib.util.spec_from_file_location("_probe_core_flows", PROBE)
    assert spec and spec.loader, f"加载不了 {PROBE}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(mod, findings, only: str = "") -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.verdict(findings, only)
    return rc, buf.getvalue()


def main() -> int:
    probe = load_probe()
    accepted = probe.ACCEPTED_QUESTIONS
    keys = sorted(accepted)

    print("== 1. 三种结局真的分得开 ==")
    # ⚠️ 满量跑（only 为空）时"空疑点"不该是 0：例外表里的条目一条都没命中 = 化石（见 §2）。
    #    所以"干净通过"只能用**分组跑**来表达 —— 这也正是分组跑不做化石判定的理由。
    rc, _ = run(probe, [], only="商品")
    check("分组跑、没有疑点 → 0", rc == 0, f"返回 {rc}")

    rc, out = run(probe, [("", "商品默认单价不允许负数 —— 201 建出了负数单价的商品")])
    check("不可接受的疑点 → 1", rc == 1, f"返回 {rc}")
    check("不可接受的疑点要被打在输出里", "负数单价" in out, out[:120])

    check("例外表至少有一条（否则下面几条是空转）", len(keys) >= 1, f"共 {len(keys)} 条")
    k0 = keys[0]
    rc, out = run(probe, [(k0, "某条已接受的问题 —— 现场数据")])
    check("已接受的疑点 → 0", rc == 0, f"返回 {rc}")
    check("已接受的那条照样打印", "某条已接受的问题" in out, out[:160])
    check("打印时必须带着它自己的理由（不是只报个名字）",
          accepted[k0][:24] in out, "输出里找不到理由原文")

    print("\n== 2. 化石：例外表里的条目没命中 → 红，并点名 ==")
    rc, out = run(probe, [])
    check("有没命中的条目时，即使没有任何疑点也要红", rc == 1, f"返回 {rc}")
    check("要点名那一条", k0 in out, out[:160])
    check("要说清是化石而不是业务问题", "化石" in out, out[:200])

    rc, _ = run(probe, [], only="商品")
    check("分组跑不做化石判定（别的组的条目当然不命中）", rc == 0, f"返回 {rc}")

    if len(keys) >= 2:
        rc, out = run(probe, [(k0, "已接受的")])
        check("已接受 + 仍有化石 → 1（两者都要看）", rc == 1, f"返回 {rc}")
        check("化石点名的是**没命中**的那条，不是命中的那条",
              keys[1] in out and out.count(k0) <= 1, out[:240])
    else:
        print("  [跳过] 例外表只有一条，跳过「已接受 + 化石并存」这一条")

    print("\n== 3. 例外表自己的纪律 ==")
    for k in keys:
        reason = accepted[k]
        check(f"「{k}」的理由写了什么时候删掉它", "删掉这一条" in reason, reason[:80])
        check(f"「{k}」的理由够长（不是敷衍一行）", len(reason) >= 60, f"{len(reason)} 字")

    print("\n" + "=" * 64)
    if FAILED:
        print(f"❌ {len(FAILED)} 项没通过：" + "；".join(FAILED))
        return 1
    print("✅ 探针的判定逻辑分得开三种结局（已接受 / 真可疑 / 化石），例外表纪律齐全。")
    return 0


if __name__ == "__main__":
    sys.exit(main())