"""模拟器 UI 操作助手（真机端到端实测用）：**每一步都按文字重新定位**，不写死坐标。

## 为什么必须按文字定位（2026-09-19 实测踩到）
登录页的输入框在**键盘弹出/收起时 y 会变**：我按"键盘收起时 dump 到的坐标"去点密码框，
结果密码串进了手机号栏（`13800000002123321`），点了登录直接被拒，而且**界面上看不出是哪一步错的**。
规律与 `_tools/notify/_ui.py` 里那条一样：**布局会变，坐标不能写死**。

用法：
    python _tools/qa/_emu_ui.py dump [关键字...]              # 打印节点（含 center），可只筛关键字
    python _tools/qa/_emu_ui.py tap  <文字> [--device 5556]   # 按文字找到就点它的中心
    python _tools/qa/_emu_ui.py type <文字> [--device 5556]   # 点一下再输入（ASCII）
    python _tools/qa/_emu_ui.py wait <文字> [--timeout 15]    # 轮询等到某段文字出现
    python _tools/qa/_emu_ui.py texts                            # 只列屏幕上所有文字（简短）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ADB = r"D:\APPS\sdk\platform-tools\adb.exe"


def _device(args) -> str:
    return f"emulator-{args.device}" if args.device else "emulator-5556"


def _dump_xml(dev: str) -> str:
    """把当前 UI 层级拉成 XML 文本（每次重新 dump，绝不复用旧坐标）。"""
    subprocess.run([ADB, "-s", dev, "shell", "uiautomator", "dump", "/sdcard/_ui.xml"],
                   capture_output=True)
    out = subprocess.run([ADB, "-s", dev, "shell", "cat", "/sdcard/_ui.xml"],
                         capture_output=True)
    return out.stdout.decode("utf-8", "replace")


def _nodes(xml_text: str) -> list[tuple[str, str, tuple[int, int], bool]]:
    """[(text, bounds, center, tappable/clickable)]"""
    root = ET.fromstring(xml_text)
    rows = []
    for n in root.iter("node"):
        t = (n.get("text") or "").strip()
        b = n.get("bounds") or ""
        try:
            a, c = b.split("][")
            x1, y1 = (int(v) for v in a.strip("[]").split(","))
            x2, y2 = (int(v) for v in c.strip("[]").split(","))
        except Exception:  # noqa: BLE001
            continue
        clickable = n.get("clickable") == "true"
        rows.append((t, b, ((x1 + x2) // 2, (y1 + y2) // 2), clickable))
    return rows


def _find(xml_text: str, needle: str):
    """找匹配文字的最靠前的可点节点（找不到就退回任意匹配节点）。"""
    rows = _nodes(xml_text)
    hits = [r for r in rows if needle in r[0]]
    if not hits:
        return None
    for r in hits:
        if r[3]:
            return r
    return hits[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["dump", "tap", "type", "wait", "texts"])
    ap.add_argument("value", nargs="*")
    ap.add_argument("--device", default="5556")
    ap.add_argument("--timeout", type=float, default=15.0)
    a = ap.parse_args()
    dev = _device(a)

    if a.cmd == "dump":
        xml = _dump_xml(dev)
        kws = a.value
        rows = _nodes(xml)
        for t, _b, c, clickable in rows:
            if not t:
                continue
            if kws and not any(k in t for k in kws):
                continue
            print(f"{'*' if clickable else ' '} {t[:36]:<38} center={c}")
        return 0

    if a.cmd == "texts":
        xml = _dump_xml(dev)
        seen = []
        for t, _b, _c, _k in _nodes(xml):
            if t and t not in seen:
                seen.append(t)
        print(" | ".join(seen[:40]))
        return 0

    needle = " ".join(a.value)
    if not needle:
        print("要给出文字")
        return 2

    if a.cmd == "wait":
        deadline = time.time() + a.timeout
        while time.time() < deadline:
            if _find(_dump_xml(dev), needle):
                print(f"✅ 等到了「{needle}」")
                return 0
            time.sleep(1.0)
        print(f"❌ 超时没等到「{needle}」")
        return 1

    hit = _find(_dump_xml(dev), needle)
    if hit is None:
        print(f"❌ 屏幕上找不到「{needle}」")
        return 1
    x, y = hit[2]
    subprocess.run([ADB, "-s", dev, "shell", "input", "tap", str(x), str(y)], capture_output=True)
    if a.cmd == "type":
        time.sleep(0.6)
        subprocess.run([ADB, "-s", dev, "shell", "input", "text", needle], capture_output=True)
    print(f"✅ 点了「{needle}」@ {x},{y}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
