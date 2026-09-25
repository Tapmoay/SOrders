#!/usr/bin/env python3
"""_check_multi_instance_readiness.py —— 多实例就绪度的**机器契约**（进 `_check_all.py` 自动跑）。

### 为什么需要它（第二轮 R2-06 · 指南 §十四）
指南 §十四 的原话是：把 5 道门做成文档，**但进一步把它变成 check_multi_instance_readiness.py**，
并且特别提醒一句：「检查器只作为验收工具，不是解决方案」。

所以这一条**不假装能证明多实例已经就绪**（那要真的起两台机器、真的发请求 —— 指南自己也说
「最终必须是真的：Instance A / Instance B 同时运行」）。它证明的是**另一件同样会被骗过去的事**：
文档说「这一关过了」，而代码里根本没有那个东西。本仓库在这种「文档与事实走散」上栽过很多次。

做法很直白：docs/MULTI_INSTANCE_READINESS.md 里每一道门写一个 gate 块，声明它 done 还是 not-done；
done 的把**证据源码路径**与 must_contain 那几串东西写出来，判据去源码里核对**真的在不在**。

### 判据（五条）
1. 每道门的键齐全、status 只能是 done / not-done；
2. ⭐ done 的门：evidence 里每个文件都存在，must_contain 里每一串都在那些文件里找得到；
3. ⭐ not-done 的门：必须写清「为什么还没做」与「什么时候做」（各 ≥12 字）——
   例外不是失败，没有解释的例外才是（第一轮就定下的口径）；
4. 门不许重名；must_contain 里不许写空串（写了等于没核）；
5. 反空转：门数 ≥10、must_contain 条目 ≥12 —— 文档被掏空时判据先喊，而不是安静地绿。

⚠️ 这一条**不碰生产**（指南 §十六 也说了：多实例要动生产，属于用户拍板）。它只读仓库里的文档与源码。

用法：python _tools/qa/_check_multi_instance_readiness.py [--check]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/MULTI_INSTANCE_READINESS.md"

MIN_GATES = 10
MIN_MARKERS = 12
MIN_TEXT = 12
REQUIRED = ("name", "中文名", "status")

BLOCK_RE = re.compile(r"(?ms)^```gate[ \t]*$(.*?)^```[ \t]*$")


def split_list(value: str) -> list[str]:
    v = (value or "").strip()
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]


def parse(text: str) -> tuple[list[dict], list[str]]:
    out: list[dict] = []
    bad: list[str] = []
    for m in BLOCK_RE.finditer(text):
        d: dict = {}
        for line in m.group(1).splitlines():
            if not line.strip():
                continue
            k, sep, v = line.partition(":")
            if not sep or not k.strip():
                bad.append(line.strip()[:70])
                continue
            d[k.strip()] = v.strip()
        out.append(d)
    return out, bad

def main() -> int:
    check_mode = "--check" in sys.argv[1:]
    gates, unparsed = parse(DOC.read_text(encoding="utf-8"))

    fails: list[str] = []
    passed = 0
    n_markers = 0

    if unparsed:
        fails.append("这些行不是「键: 值」的形状（判据读不出来）：" + "、".join(unparsed))
    else:
        passed += 1
    if len(gates) < MIN_GATES:
        fails.append(f"只登记到 {len(gates)} 道门（<{MIN_GATES}）—— 文档被掏空了？")
    else:
        passed += 1

    names: list[str] = []
    for g in gates:
        nm = g.get("name", "?")
        names.append(nm)
        miss = [k for k in REQUIRED if k not in g]
        if miss:
            fails.append(f"门 {nm} 缺字段：" + "、".join(miss))
            continue
        st = g["status"]
        if st not in ("done", "not-done"):
            fails.append(f"门 {nm} 的 status 只能是 done / not-done，现在是 {st!r}")
            continue
        if st == "done":
            files = split_list(g.get("evidence", ""))
            markers = split_list(g.get("must_contain", ""))
            if not files or not markers:
                fails.append(f"门 {nm} 标了 done，却没写 evidence / must_contain —— 那就无从核对")
                continue
            n_markers += len(markers)
            blob = ""
            for rel in files:
                path = ROOT / rel
                if not path.is_file():
                    fails.append(f"门 {nm} 的证据文件不存在：{rel}")
                else:
                    blob += path.read_text(encoding="utf-8", errors="replace")
            for mk in markers:
                if not mk.strip():
                    fails.append(f"门 {nm} 的 must_contain 里有空串（等于没核）")
                elif mk not in blob:
                    fails.append(f"门 {nm} 声称有这个形状，但证据源码里找不到：{mk!r}")
        else:
            for key in ("为什么还没做", "什么时候做"):
                if len(g.get(key, "").strip()) < MIN_TEXT:
                    fails.append(f"门 {nm} 是 not-done，但没写（或写得太短）「{key}」")
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        fails.append("门名重复：" + "、".join(sorted(dup)))
    if n_markers < MIN_MARKERS:
        fails.append(f"done 的门一共只核了 {n_markers} 串东西（<{MIN_MARKERS}）—— 契约太薄")
    else:
        passed += 1

    done_n = sum(1 for g in gates if g.get("status") == "done")
    print(f"多实例就绪：{len(gates)} 道门（已过 {done_n} / 没做 {len(gates) - done_n}）"
          f" / done 的门核了 {n_markers} 串代码形状")
    if fails:
        for f in sorted(set(fails)):
            print("  ❌ " + f)
        return 1
    if check_mode:
        print("  ✅ 全部通过")
    else:
        print(f"  ✅ {passed} 组判据全部通过：每道门都有状态，「已过」的拿去源码里核过形状，"
              "「没做」的都写清了为什么与什么时候做。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
