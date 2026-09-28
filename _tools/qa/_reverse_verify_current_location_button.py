#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反向验证：把「我就在这里」按钮那条判据**逐条弄坏**，看它**真的会红**（FEAT-0003）。

这条判据是**纯静态**的（扫 `OrderCreateScreen.kt` 的代码形状）。
静态判据最大的风险是"绿而瞎"：正则写歪一点，它就一直绿，而功能早就跑偏了。
所以这里逐条把**它声称要拦的那几种写法**真的写进源码，看它会不会红。

⚠️ 场景表必须保持"字面量形状"（`_check_reverse_verify_anchors.py` 要静态抽锚点）。
⛔ 每条注入按**字节**记住原样并还原 —— 不用 `git checkout --`。

用法：python _tools/qa/_reverse_verify_current_location_button.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = Path(__file__).resolve().parent / "_check_current_location_button.py"
SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"

#: (标签, 目标文件, 被替换的原文, 替换成, 期望变红, 跑哪条判据)
SCENARIOS = [
    ("（不注入：不坏就必须是绿的）", CHECK, False),

    ("按钮文案被改掉", SCREEN,
     'Text(if (locating) "正在定位…" else "我就在这里")',
     'Text(if (locating) "正在定位…" else "按钮在这里")', True, CHECK),
    ("拿不到定位时不再过滤 (0,0)", SCREEN,
     "if (!SunLocation.isPlausible(pt.lat, pt.lng)) {",
     "if (false) {", True, CHECK),
    ("失败分支里也去回填（拿不到点也填一个假地址）", SCREEN,
     '                locateError = "没拿到有效定位：请检查定位权限，或改用「地图选点」。"',
     '                locateError = "没拿到有效定位：请检查定位权限，或改用「地图选点」。"\n                vm.applyPicked(pt.lat, pt.lng, pt.address)', True, CHECK),
    ("回填时顺手写库", SCREEN,
     "            vm.applyPicked(pt.lat, pt.lng, pt.address)",
     "            container.repo.shareLocation(pt.lat, pt.lng, pt.address)", True, CHECK),
    ("退到系统定位（WGS84，国内偏几百米）", SCREEN,
     "    var locating by remember { mutableStateOf(false) }",
     "    var locating by remember { mutableStateOf(false) }\n    val _wgs = DeviceLocation.lastPoint", True, CHECK),
    ("回填不再走 applyPicked", SCREEN,
     "            vm.applyPicked(pt.lat, pt.lng, pt.address)",
     "            vm.showAddressSheet = false", True, CHECK),
    # CHG-0004：按钮**又被放回地址库抽屉**（用户 2026-09-28 点名不许放那儿）。
    # ⚠️ 注入要落在**真代码**上（判据会先剥掉 `//` 注释 —— 往注释里塞一句话是没用的）。
    ("按钮又被放回地址库抽屉里", SCREEN,
     "        Column(Modifier.fillMaxWidth().fillMaxHeight(0.92f).padding(bottom = 12.dp)) {",
     "        Column(Modifier.fillMaxWidth().fillMaxHeight(0.92f).padding(bottom = 12.dp)) {\n            Text(\"我就在这里\")", True, CHECK),
]


class Sandbox:
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
                print("⛔ 还原后与快照不一致：" + str(p))
        self.saved.clear()


def run(script: Path) -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    lock_reverse_verify()
    ok, failed = 0, []
    try:
        for i, case in enumerate(SCENARIOS, 1):
            if len(case) == 3:
                label, script, expect_red = case[0], case[1], case[2]
                target = old = new = None
            else:
                label, target, old, new, expect_red, script = case
            sb = Sandbox()
            try:
                if target is not None and old is not None and new is not None:
                    sb.replace(target, old, new)
                code, out = run(script)  # type: ignore[arg-type]
            finally:
                sb.restore()
            good = (code != 0) if expect_red else (code == 0)
            print(("✅" if good else "❌") + " [" + str(i) + "/" + str(len(SCENARIOS)) + "] "
                  + ("应红" if expect_red else "应通过") + " · " + label + " → exit=" + str(code))
            if good:
                ok += 1
            else:
                failed.append(label)
                print("     输出尾部：\n" + "\n".join(out.strip().splitlines()[-5:]))
    finally:
        unlock_reverse_verify()

    print("")
    if failed:
        print("❌ 反向验证 " + str(ok) + "/" + str(len(SCENARIOS)) + " —— 没按预期反应的：")
        for f in failed:
            print("   - " + f)
        print("")
        print("   ⚠️ 先分清「判据漏了」还是「注入没生效」：修法相反，别搞反。")
        return 1
    print("✅ 反向验证 " + str(ok) + "/" + str(len(SCENARIOS)) + "：每条破坏都让判据真的红了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
