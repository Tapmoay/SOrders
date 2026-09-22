"""反向验证：`_tools/qa/_check_map_picker.py` 那些判据**真的抓得住**吗（2026-09-22）。

手法与仓库里其它 `_reverse_verify_*.py` 同一套：**按字节备份 → 注入 → 跑红线（期望非零退出且命中
指定判据）→ 按字节还原 → 校验 sha256**。⛔ 全程不碰 `git checkout --`（那会在真有改动时抹掉工作）。

遵守注入锁的规矩（`_tools/ai/_airepo.py`）：`lock_reverse_verify` / `refuse_if_injecting`。

⚠️ 每个注入点都挑**真会有人这么改**的那条路：
   ① 瓦片地址贪方便写成 http（真机上被静默拦掉，只表现为"没有路名"）；
   ② 坐标闸被"简化"掉（(0,0) 写进订单与共享地点库）；
   ③ `applyMapType` 挪进相机回调（每拖一次地图叠一层瓦片）；
   ④ 卫星档删掉、只留标准（用户点名的功能消失）；
   ⑤ 恢复 `onDestroy`（高德 9.8.3 在 Android 15+/16 arm64 上 native SIGABRT）。

用法：
    python _tools/qa/_reverse_verify_map_picker.py          # 全部跑
    python _tools/qa/_reverse_verify_map_picker.py --list   # 只列注入点
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import (  # noqa: E402
    lock_reverse_verify,
    refuse_if_injecting,
    unlock_reverse_verify,
)

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_map_picker.py"
PICKER = "android/app/src/main/java/com/tapmoay/sorders/ui/common/AmapPicker.kt"

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的关键字)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 路网瓦片写成 http（本包禁明文 → 真机上被静默拦掉，只表现为「没有路名」）",
        PICKER,
        'URL("https://wprd0${(x + y) % 4 + 1}.is.autonavi.com/appmaptile?style=8&x=$x&y=$y&z=$zoom")',
        'URL("http://wprd0${(x + y) % 4 + 1}.is.autonavi.com/appmaptile?style=8&x=$x&y=$y&z=$zoom")',
        "路网注记瓦片用的是 https",
    ),
    (
        "② 坐标闸被「简化」掉（(0,0) 会写进订单与全库共享的地点库，导航指到几内亚湾）",
        PICKER,
        "                                if (!SunLocation.isPlausible(lat, lng)) {\n",
        "                                if (false) {\n",
        "用共用判据 `SunLocation.isPlausible`",
    ),
    (
        "③ `applyMapType` 挪进相机回调（每拖一次地图就叠一层瓦片）",
        PICKER,
        "                                if (!alive) return\n                                position?.let { p ->\n",
        "                                if (!alive) return\n                                AmapMapHolder.applyMapType(aMap)\n"
        "                                position?.let { p ->\n",
        "经持有者调用 `applyMapType` 恰好 2 处",
    ),
    (
        "④ 卫星档删掉、只留标准（用户 2026-09-22 点名的功能消失）",
        PICKER,
        "            aMap.mapType = if (satellite) AMap.MAP_TYPE_SATELLITE else AMap.MAP_TYPE_NORMAL\n",
        "            aMap.mapType = AMap.MAP_TYPE_NORMAL\n",
        "用了 SDK 的卫星图层常量",
    ),
    (
        "⑤ 恢复 `onDestroy`（高德 9.8.3 在 Android 15+/16 arm64 上会 native SIGABRT 闪退）",
        PICKER,
        "            try { mapView.onPause() } catch (_: Exception) {}\n",
        "            try { mapView.onPause(); mapView.onDestroy() } catch (_: Exception) {}\n",
        "没有 `onDestroy`",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    if refuse_if_injecting("地图选点反向验证"):
        return 1

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    lock_reverse_verify()
    caught = 0
    problems: list[str] = []
    try:
        for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
            path = ROOT / rel
            if not path.exists():
                problems.append(f"{name}：找不到 {rel}")
                print(f"\n[{i}] {name}\n  ❌ 找不到 {rel}")
                continue
            orig = path.read_bytes()
            orig_sha = sha(path)
            text = orig.decode("utf-8")
            eol = "\r\n" if "\r\n" in text else "\n"
            if eol != "\n":
                old = old.replace("\n", eol)
                new = new.replace("\n", eol)
            pat = old[3:] if old.startswith("re:") else re.escape(old)
            injected, n = re.subn(pat, new, text, count=1)
            if n != 1:
                problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:40]!r}）")
                print(f"\n[{i}] {name}\n  ❌ 锚点没命中，跳过（注入点腐烂了）")
                continue
            inj_bytes = injected.encode("utf-8")
            path.write_bytes(inj_bytes)
            try:
                rc, out = run_check()
            finally:
                now = path.read_bytes()
                if now != inj_bytes:
                    print(f"\n[{i}] {name}\n  🛑 有别的东西改了 {rel} —— **拒绝还原**，请人工处理！")
                    return 2
                path.write_bytes(orig)
            if sha(path) != orig_sha:
                print(f"\n[{i}] {name}\n  🛑 {rel} 还原后哈希对不上，停手")
                return 2

            hit = f"[!!]   {want}" in out
            if rc != 0 and hit:
                caught += 1
                print(f"\n[{i}] {name}\n  ✅ 被抓到（红线非零退出，命中「{want}」）")
            else:
                why = "红线居然还是绿的" if rc == 0 else f"退出了，但输出里没有「[!!]   {want}」"
                problems.append(f"{name}：{why}")
                print(f"\n[{i}] {name}\n  ❌ {why}")
    finally:
        unlock_reverse_verify()

    print("\n" + "=" * 60)
    print(f"{caught}/{len(INJECTIONS)} 种破坏方式被抓住")
    if problems:
        print("❌ 有漏网的：")
        for p in problems:
            print("   -", p)
        return 1
    print("✅ 全部注入都被抓住，且每个文件都按字节还原")
    return 0


if __name__ == "__main__":
    sys.exit(main())
