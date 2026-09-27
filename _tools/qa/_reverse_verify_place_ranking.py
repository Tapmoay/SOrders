#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反向验证：把「共享地点分档排序」那条判据**逐条弄坏**，看它**真的会红**。

### 为什么这块必须反向验证

这条判据守的是"**两个数字不许混**"（合并半径 vs 排序档位）。
它最容易退化成一条**永远绿**的检查：常量抄一遍、边界表抄一遍、
最后"看起来在核代码形状"其实什么都没读懂 —— 而线早就断了。

还有一条**正面**场景必须一起验：**不注入时必须绿**
（一条永远红的检查等于没有检查 —— 本项目 §15 的教训）。

### ⚠️ 场景表必须保持"字面量形状"

`_tools/qa/_check_reverse_verify_anchors.py` 会**静态**解析每一份反向验证脚本，
从形如「(标签, 目标文件, 被替换的原文, 替换成, …)」的**元组字面量**里抽锚点，
每天核对"原文还在不在"。⛔ 别把「原文」那一格写成变量或函数返回值 —— 那样锚点会**静默不检查**
（`_reverse_verify_dev_spec.py` 第一版就是这么栽的，抽出来是「0 条」而看起来是绿的）。

⛔ 每条注入都用 `Sandbox` 按**字节**记住原样并还原 —— 不用 `git checkout --`：
那会把未提交的真实改动一起抹掉。

用法：python _tools/qa/_reverse_verify_place_ranking.py    # 10 条场景全部成立 → 退出码 0
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

CHECK = HERE / "_check_place_ranking.py"

SERVICE = ROOT / "backend" / "app" / "services" / "place_service.py"
ENDPOINT = ROOT / "backend" / "app" / "api" / "v1" / "places.py"

#: (标签, 目标文件, 被替换的原文, 替换成, 期望变红, 跑哪条判据)
SCENARIOS = [
    ("（不注入：不坏就必须是绿的）", CHECK, False),

    ("第一档从 1 米改成 2 米（档位边界错）", SERVICE,
     "NEAR_TIERS: tuple[float, ...] = (1.0, 10.0, 50.0, 100.0)",
     "NEAR_TIERS: tuple[float, ...] = (2.0, 10.0, 50.0, 100.0)", True, CHECK),
    ("最远那一档从 100 米放宽到 200 米", SERVICE,
     "NEAR_TIERS: tuple[float, ...] = (1.0, 10.0, 50.0, 100.0)",
     "NEAR_TIERS: tuple[float, ...] = (1.0, 10.0, 50.0, 200.0)", True, CHECK),
    ("四档改成不嵌套（顺序乱了）", SERVICE,
     "NEAR_TIERS: tuple[float, ...] = (1.0, 10.0, 50.0, 100.0)",
     "NEAR_TIERS: tuple[float, ...] = (100.0, 50.0, 10.0, 1.0)", True, CHECK),
    ("没有坐标的行被当成 0 米（会跑到最前面）", SERVICE,
     '    return (len(NEAR_TIERS), float("inf"))',
     '    return (0, 0.0)', True, CHECK),

    # ⚠️ 锚点必须带上下文：模块开头的注释里**也**写着 `MERGE_METERS = 1.0`（说明"这是合并半径"），
    #    只写常量那一行会命中 2 处、替换不动（实测踩到）。
    ("合并半径 1 米被改成 2 米（Q3=A 被违反）", SERVICE,
     "MERGE_METERS = 1.0\n\n#: 同名地点", "MERGE_METERS = 2.0\n\n#: 同名地点", True, CHECK),
    ("同名合并半径 30 米被改成 50 米", SERVICE,
     "SAME_NAME_METERS = 30.0\n\n#: 「共享地点列表」", "SAME_NAME_METERS = 50.0\n\n#: 「共享地点列表」", True, CHECK),

    ("端点只在给了一个坐标时也去排序", ENDPOINT,
     "    if lat is not None and lng is not None:",
     "    if lat is not None or lng is not None:", True, CHECK),
    ("端点开始引用合并口径（两个口径串了）", ENDPOINT,
     "        near = place_service.near_places(db, stmt, lat=lat, lng=lng)",
     "        _mm = place_service.MERGE_METERS\n        near = place_service.near_places(db, stmt, lat=lat, lng=lng)",
     True, CHECK),

    ("near_places 不再先用 bbox 粗筛", SERVICE,
     "_bbox(lat, lng, meters)", "(lat, lat, lng, lng)", True, CHECK),
    ("near_places 整个没了", SERVICE,
     "def near_places(", "def near_places_gone(", True, CHECK),
]


class Sandbox:
    """按字节记住原样，最后一次性还原（⛔ 不用 git checkout --）。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def replace(self, p: Path, old: str, new: str) -> None:
        if p not in self.saved:
            self.saved[p] = p.read_bytes()
        text = p.read_text(encoding="utf-8")
        assert text.count(old) == 1, p.name + ": 原文出现 " + str(text.count(old)) + " 次，无法唯一替换"
        p.write_bytes(text.replace(old, new).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)
            if p.read_bytes() != raw:
                print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        self.saved.clear()


def run(script: Path) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    lock_reverse_verify()
    ok = 0
    failed: list[str] = []
    try:
        for i, case in enumerate(SCENARIOS, 1):
            if len(case) == 3:
                label, script, expect_red = case[0], case[1], case[2]
                target, old, new = None, None, None
            else:
                label, target, old, new, expect_red, script = case
            sb = Sandbox()
            try:
                if target is not None and old is not None and new is not None:
                    sb.replace(target, old, new)
                code, out = run(script)  # type: ignore[arg-type]
            finally:
                sb.restore()
            red = code != 0
            good = red if expect_red else (not red)
            print(("✅" if good else "❌") + " [" + str(i) + "/" + str(len(SCENARIOS)) + "] "
                  + ("应红" if expect_red else "应通过") + " · " + label + " → 实际 exit=" + str(code))
            if good:
                ok += 1
            else:
                failed.append(label)
                print("     输出尾部：\n" + "\n".join(out.strip().splitlines()[-6:]))
    finally:
        unlock_reverse_verify()

    print("")
    if failed:
        print("❌ 反向验证 " + str(ok) + "/" + str(len(SCENARIOS)) + " —— 这些场景没有按预期反应：")
        for f in failed:
            print("   - " + f)
        print("")
        print("   ⚠️ 先分清是**判据漏了**还是**注入没生效**（锚点腐烂）：")
        print("      注入没生效 → 改锚点；判据漏了 → 改判据。⛔ 两件事的修法相反，别搞反。")
        return 1
    print("✅ 反向验证 " + str(ok) + "/" + str(len(SCENARIOS))
          + "：每一条破坏都让判据**真的红了**，而正常情况它是绿的。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
